"""The swap demos: change the outside world, leave autopsy/ untouched, get the same root cause.

  swap the schema    rename a column in Acme's raw data and one manifest line
  swap the project   investigate the second plug-in with the same tools
  swap the database  export Acme to SQLite and change `connector: duckdb` to `connector: sqlite`
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from autopsy.core.baseline import learn_baseline, save_baseline
from autopsy.core.manifest import load_manifest, validate_against
from autopsy.core.registry import create_connector
from autopsy.grade import grade_report, load_expected
from autopsy.investigate import investigate
from autopsy.mcp_server.tools import Tools

PLUGINS = Path(__file__).resolve().parents[2] / "plugins"
PLATFORM_CODE = Path(__file__).resolve().parents[1] / "autopsy"
AS_OF = datetime(2026, 10, 28, 12, 0, 0)
NOW = datetime(2026, 10, 28, 13, 0, 0)

pytestmark = pytest.mark.skipif(not PLUGINS.is_dir(), reason="no plugins/ folder next to the platform")


def code_fingerprint() -> str:
    h = hashlib.sha256()
    for path in sorted(PLATFORM_CODE.rglob("*.py")):
        h.update(path.read_bytes())
    return h.hexdigest()


def run(*args) -> None:
    subprocess.run([sys.executable, *map(str, args)], check=True, capture_output=True)


def baseline_then_investigate(manifest_path: Path, state: Path, build_healthy, build_failure, expected_path, scenario):
    manifest = load_manifest(manifest_path)
    build_healthy()
    connector = create_connector(manifest.connector, manifest.connection)
    assert not [i for i in validate_against(manifest, connector) if i.level == "error"]
    save_baseline(learn_baseline(manifest, connector, NOW), state)
    connector.close()

    build_failure()
    tools = Tools(manifest, state_dir=state, now=NOW)
    try:
        inv = investigate(tools)
    finally:
        tools.close()
    grade = grade_report(inv.report, load_expected(expected_path, scenario), scenario)
    assert grade.root_ok and grade.severity_ok, f"{grade.line()}\n{inv.report}"


def test_swap_the_schema(tmp_path, monkeypatch):
    """Rename ordered_at to created_ts in Acme's raw data; one manifest line follows; S5 is found as before."""
    before = code_fingerprint()
    acme = tmp_path / "acme_shop"
    shutil.copytree(PLUGINS / "acme_shop", acme, ignore=shutil.ignore_patterns("*.duckdb", "*.wal", "__pycache__"))

    def edit(rel: str, old: str, new: str, count: int = -1) -> None:
        path = acme / rel
        text = path.read_text(encoding="utf-8")
        assert old in text, f"{old!r} not found in {rel}"
        path.write_text(text.replace(old, new, count), encoding="utf-8")

    edit("seed/seed_data.py", "ordered_at timestamp", "created_ts timestamp")
    edit("pipeline/sql/stg_orders.sql", "o.ordered_at,", "o.created_ts as ordered_at,")
    edit("pipeline/run_pipeline.py", "customer_id, ordered_at, amount from raw.orders",
         "customer_id, created_ts, amount from raw.orders")
    edit("manifest.yaml", "event_time: ordered_at", "event_time: created_ts", 1)     # orders_raw only

    db = tmp_path / "acme.duckdb"
    monkeypatch.setenv("ACME_DB_PATH", str(db))

    def build(scenario):
        run(acme / "seed" / "seed_data.py", "--db", db, "--scenario", scenario, "--as-of", AS_OF.isoformat())
        run(acme / "pipeline" / "run_pipeline.py", "--db", db, "--log", tmp_path / "log.txt")

    baseline_then_investigate(acme / "manifest.yaml", tmp_path / "state", lambda: build("S0"), lambda: build("S5"),
                              acme / "expected" / "expected_results.yaml", "S5")
    assert code_fingerprint() == before


def test_swap_the_project(tmp_path, monkeypatch):
    sensors = PLUGINS / "sensor_readings"
    if not sensors.is_dir():
        pytest.skip("plugins/sensor_readings is not present")
    before = code_fingerprint()
    db = tmp_path / "sensors.duckdb"
    monkeypatch.setenv("SENSOR_DB_PATH", str(db))

    def build(scenario):
        run(sensors / "seed" / "seed_data.py", "--db", db, "--scenario", scenario, "--as-of", AS_OF.isoformat())

    baseline_then_investigate(sensors / "manifest.yaml", tmp_path / "state", lambda: build("S0"), lambda: build("S1"),
                              sensors / "expected_results.yaml", "S1")
    assert code_fingerprint() == before


def test_swap_the_database(tmp_path, monkeypatch):
    """Same Acme data in SQLite, same manifest apart from the connector settings, same root cause."""
    before = code_fingerprint()
    acme = PLUGINS / "acme_shop"
    duck, lite = tmp_path / "acme.duckdb", tmp_path / "acme.sqlite"
    monkeypatch.setenv("ACME_DB_PATH", str(duck))
    monkeypatch.setenv("ACME_SQLITE_PATH", str(lite))

    raw = yaml.safe_load((acme / "manifest.yaml").read_text(encoding="utf-8"))
    raw["connector"] = "sqlite"
    raw["connection"] = {"path_env": "ACME_SQLITE_PATH"}
    manifest_path = tmp_path / "manifest_sqlite.yaml"
    manifest_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    def build(scenario):
        run(acme / "seed" / "seed_data.py", "--db", duck, "--scenario", scenario, "--as-of", AS_OF.isoformat())
        run(acme / "pipeline" / "run_pipeline.py", "--db", duck, "--log", tmp_path / "log.txt")
        run(acme / "scripts" / "export_sqlite.py", "--db", duck, "--out", lite)

    baseline_then_investigate(manifest_path, tmp_path / "state", lambda: build("S0"), lambda: build("S5"),
                              acme / "expected" / "expected_results.yaml", "S5")
    assert code_fingerprint() == before
