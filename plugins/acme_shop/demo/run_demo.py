"""One command to run the whole demo: a believable shop, and Pipeline Autopsy watching it.

usage: python plugins/acme_shop/demo/run_demo.py [--no-browser] [--keep-state] [--autopsy-port 8765] [--shop-port 8780]

Run it with the Python that has the platform installed (pip install -e "autopsy-platform[dev]"). It
  1. reseeds healthy data and builds the pipeline output,
  2. starts Pipeline Autopsy and, through its HTTP API only, imports this plug-in's manifest, learns the baseline from
     the healthy data, runs the first checks and turns on a one-minute schedule,
  3. starts the shop (storefront, finance dashboard, operations and incident lab),
  4. opens both in your browser and waits; Ctrl+C stops everything.
This file talks to the platform over HTTP and imports nothing from it.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
DEMO = Path(__file__).resolve().parent


def api(base: str, method: str, path: str, body: dict | None = None, timeout: float = 120.0) -> dict:
    request = urllib.request.Request(
        base + path, method=method, data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read() or b"{}")
        raise SystemExit(f"{method} {path} failed ({exc.code}): {detail.get('message', detail)}") from None


def wait_for(url: str, name: str, process: subprocess.Popen, log: Path, seconds: float = 40.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"{name} exited early (code {process.returncode}); see {log}")
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.4)
    raise SystemExit(f"{name} did not come up within {seconds:.0f}s; see {log}")


def port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def run(cmd: list[str], env: dict, what: str) -> None:
    for attempt in range(8):
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if proc.returncode == 0:
            return
        time.sleep(1.0)          # a reader may still hold the database file
    raise SystemExit(f"{what} failed:\n{proc.stderr or proc.stdout}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--autopsy-port", type=int, default=8765)
    parser.add_argument("--shop-port", type=int, default=8780)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--keep-state", action="store_true", help="keep Pipeline Autopsy's history from the last demo")
    args = parser.parse_args()

    py = sys.executable
    if subprocess.run([py, "-c", "import autopsy, duckdb"], capture_output=True).returncode != 0:
        raise SystemExit('Pipeline Autopsy is not installed for this Python. Run: pip install -e "autopsy-platform[dev]"\n'
                         "(or start this script with the project's .venv Python)")
    for port in (args.autopsy_port, args.shop_port):
        if port_in_use(port):
            raise SystemExit(f"port {port} is already in use; stop what is using it or pass another port")

    state, logs = DEMO / "state", DEMO / "logs"
    if state.exists() and not args.keep_state:
        shutil.rmtree(state)
    logs.mkdir(parents=True, exist_ok=True)
    # the demo has its own database and log, so it never touches a database you set up by hand
    db = DEMO / "data" / "acme.duckdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    pipeline_log = logs / "pipeline_run.log"
    env = {k: v for k, v in os.environ.items() if k not in ("AUTOPSY_NOW", "ACME_AS_OF")}
    env["ACME_DB_PATH"] = str(db)

    print("1/4  Seeding healthy data and building the pipeline output ...")
    for suffix in ("", ".wal"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    # timestamps are naive UTC, which is how the platform reads them
    as_of = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat()
    run([py, str(PLUGIN / "seed" / "seed_data.py"), "--db", str(db), "--scenario", "S0", "--as-of", as_of], env, "seeding")
    run([py, str(PLUGIN / "pipeline" / "run_pipeline.py"), "--db", str(db), "--log", str(pipeline_log)],
        env, "the pipeline")

    children: list[subprocess.Popen] = []
    try:
        print("2/4  Starting Pipeline Autopsy and teaching it this project ...")
        autopsy_log = logs / "autopsy.log"
        autopsy = subprocess.Popen([py, "-m", "autopsy.cli", "serve", "--port", str(args.autopsy_port), "--state-dir", str(state)],
                                   env=env, stdout=autopsy_log.open("w"), stderr=subprocess.STDOUT)
        children.append(autopsy)
        base = f"http://127.0.0.1:{args.autopsy_port}"
        wait_for(base + "/api/health", "Pipeline Autopsy", autopsy, autopsy_log)

        imported = api(base, "POST", "/api/projects/import", {"yaml": (PLUGIN / "manifest.yaml").read_text(encoding="utf-8")})
        if not imported["validation"]["ok"]:
            raise SystemExit(f"the manifest does not match the database: {imported['validation']}")
        project = imported["project"]["name"]
        api(base, "POST", f"/api/projects/{project}/baseline", {})
        first = api(base, "POST", f"/api/projects/{project}/runs", {"kind": "monitor"})
        api(base, "PUT", f"/api/projects/{project}/schedule", {"enabled": True, "interval_minutes": 1, "auto_investigate": True})
        if first["status"] != "ok":
            print(f"     note: the first check run was {first['status']}: {first['summary']}")

        print("3/4  Starting the shop ...")
        shop_log = logs / "shop.log"
        shop = subprocess.Popen([py, str(PLUGIN / "app" / "server.py"), "--db", str(db), "--port", str(args.shop_port),
                                 "--autopsy-url", f"{base}/#/projects/{project}", "--pipeline-log", str(pipeline_log)],
                                env=env, stdout=shop_log.open("w"), stderr=subprocess.STDOUT)
        children.append(shop)
        shop_url = f"http://127.0.0.1:{args.shop_port}"
        wait_for(shop_url + "/api/state", "the shop", shop, shop_log)

        autopsy_url = f"{base}/#/projects/{project}"
        print("4/4  Ready.\n")
        print(f"   Shop (storefront, finance, incident lab)   {shop_url}")
        print(f"   Pipeline Autopsy                           {autopsy_url}\n")
        print("   Try it: open the shop's Operations tab, press 'Make it happen' on an incident, watch Finance change,")
        print("   then watch Pipeline Autopsy (it checks every minute; 'Run checks' there is instant).")
        print("   Ctrl+C stops both.\n")
        if not args.no_browser:
            webbrowser.open(shop_url + "/#/operations")
            webbrowser.open(autopsy_url)
        while True:
            for child in children:
                if child.poll() is not None:
                    raise SystemExit(f"a demo process exited (code {child.returncode}); see {logs}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping ...")
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    main()
