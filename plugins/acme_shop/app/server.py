"""Acme Shop web application.

usage: server.py --db acme.duckdb [--port 8780] [--autopsy-url http://127.0.0.1:8765/#/projects/acme_shop]

Serves the storefront, the finance dashboard and the operations / incident-lab pages (app/static), a small JSON API,
and two background jobs a real shop would have: the pipeline on a timer, and customers placing orders.
This file imports nothing from the Pipeline Autopsy platform.
"""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import random
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from shop import Shop, ShopError

STATIC = Path(__file__).resolve().parent / "static"
LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}
log = logging.getLogger("acme.app")


class Background:
    """The pipeline cron job and the simulated customers. Both can be switched on and off from the UI."""

    def __init__(self, shop: Shop, pipeline_interval: float, traffic_per_minute: float, traffic_on: bool, pipeline_on: bool):
        self.shop = shop
        self.settings = {
            "pipeline": {"enabled": pipeline_on, "interval_seconds": pipeline_interval},
            "traffic": {"enabled": traffic_on, "per_minute": traffic_per_minute},
        }
        self._stop = threading.Event()
        self._wake = threading.Event()          # set when a setting changes, so a new rate applies at once
        self._threads = [threading.Thread(target=self._pipeline_loop, daemon=True, name="pipeline-cron"),
                         threading.Thread(target=self._traffic_loop, daemon=True, name="customers")]

    def start(self) -> None:
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def update(self, body: dict) -> dict:
        for name, fields in (("pipeline", ("enabled", "interval_seconds")), ("traffic", ("enabled", "per_minute"))):
            for key in fields:
                if key in (body.get(name) or {}):
                    value = body[name][key]
                    if key == "enabled":
                        value = bool(value)
                    else:
                        value = float(value)
                        if not 1 <= value <= (3600 if key == "interval_seconds" else 600):
                            raise ShopError(f"{name}.{key} is out of range")
                    self.settings[name][key] = value
        self._wake.set()
        return self.settings

    def _pipeline_loop(self) -> None:
        last = time.monotonic()
        while not self._stop.wait(1.0):
            cfg = self.settings["pipeline"]
            if cfg["enabled"] and time.monotonic() - last >= cfg["interval_seconds"]:
                last = time.monotonic()
                try:
                    self.shop.run_pipeline()
                except Exception:
                    log.exception("scheduled pipeline run failed")

    def _traffic_loop(self) -> None:
        rng = random.Random()
        while not self._stop.is_set():
            cfg = self.settings["traffic"]
            delay = 60.0 / max(cfg["per_minute"], 1.0)
            if self._wake.wait(delay * rng.uniform(0.5, 1.5)):
                self._wake.clear()
                if self._stop.is_set():
                    return
                continue                        # the settings changed: work out the next order from the new rate
            if self._stop.is_set():
                return
            if cfg["enabled"]:
                try:
                    self.shop.place_order(channel=rng.choice(["web"] * 10 + ["mobile"] * 7 + ["store"] * 3))
                except Exception:
                    log.exception("simulated order failed")


def make_handler(shop: Shop, background: Background, autopsy_url: str):
    def routes():
        return [
            ("GET", r"/api/config", lambda m, q, b: {"autopsy_url": autopsy_url, "background": background.settings}),
            ("GET", r"/api/state", lambda m, q, b: shop.state()),
            ("GET", r"/api/products", lambda m, q, b: {"products": shop.products()}),
            ("GET", r"/api/customers", lambda m, q, b: {"customers": shop.customers()}),
            ("GET", r"/api/orders", lambda m, q, b: {"orders": shop.recent_orders(int(q.get("limit", ["15"])[0]))}),
            ("POST", r"/api/orders", lambda m, q, b: shop.place_order(b.get("customer_id"), b.get("items"), b.get("channel", "web"))),
            ("GET", r"/api/revenue", lambda m, q, b: shop.revenue(int(q.get("days", ["14"])[0]))),
            ("POST", r"/api/pipeline/run", lambda m, q, b: shop.run_pipeline()),
            ("PUT", r"/api/background", lambda m, q, b: background.update(b)),
            ("GET", r"/api/events", lambda m, q, b: {"events": shop.event_catalog()}),
            ("POST", r"/api/events/(?P<event>[a-z_]+)/trigger", lambda m, q, b: shop.trigger(m["event"])),
            ("POST", r"/api/events/(?P<event>[a-z_]+)/rollback", lambda m, q, b: shop.roll_back(m["event"])),
            ("POST", r"/api/reset", lambda m, q, b: shop.reset()),
        ]

    table = [(method, re.compile(pattern + "$"), fn) for method, pattern, fn in routes()]

    class Handler(BaseHTTPRequestHandler):
        server_version = "AcmeShop/1.0"

        def log_message(self, fmt, *args):      # quiet; the shop is not the thing being demonstrated
            log.debug(fmt, *args)

        def _send(self, status: int, payload, content_type: str = "application/json") -> None:
            data = payload if isinstance(payload, bytes) else json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _guard(self, has_body: bool) -> str | None:
            """This shop can delete data, so a web page on another site must not be able to drive it."""
            host = self.headers.get("Host", "")
            hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
            if hostname.lower() not in LOOPBACK:
                return "host not allowed"
            if self.command != "GET":
                origin = self.headers.get("Origin")
                if origin and urlsplit(origin).netloc.lower() != host.lower():
                    return "cross-site request refused"
                if has_body and "application/json" not in self.headers.get("Content-Type", "").lower():
                    return "send JSON"
            return None

        def _dispatch(self) -> None:
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            refused = self._guard(bool(raw))
            if refused:
                return self._send(HTTPStatus.FORBIDDEN, {"error": "forbidden", "message": refused})
            if parts.path.startswith("/api/"):
                body = {}
                if raw:
                    try:
                        body = json.loads(raw)
                    except json.JSONDecodeError:
                        return self._send(400, {"error": "invalid_json", "message": "body is not valid JSON"})
                    if not isinstance(body, dict):
                        return self._send(400, {"error": "invalid_json", "message": "body must be a JSON object"})
                for method, pattern, fn in table:
                    match = pattern.match(parts.path)
                    if match and method == self.command:
                        try:
                            return self._send(200, fn(match.groupdict(), parse_qs(parts.query), body))
                        except ShopError as exc:
                            return self._send(exc.status, {"error": "refused", "message": str(exc)})
                        except Exception as exc:
                            log.exception("error in %s %s", self.command, parts.path)
                            return self._send(500, {"error": "internal", "message": f"{type(exc).__name__}: {exc}"[:300]})
                return self._send(404, {"error": "not_found", "message": f"no route {self.command} {parts.path}"})
            if self.command != "GET":
                return self._send(405, {"error": "method_not_allowed", "message": "GET only"})
            self._static(parts.path)

        def _static(self, path: str) -> None:
            relative = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (STATIC / relative).resolve()
            if not target.is_file() or STATIC.resolve() not in target.parents:
                return self._send(404, {"error": "not_found", "message": "no such file"})
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), kind + ("; charset=utf-8" if kind.startswith("text/") or kind.endswith("javascript") else ""))

        do_GET = do_POST = do_PUT = do_DELETE = _dispatch

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--autopsy-url", default="http://127.0.0.1:8765/#/projects/acme_shop")
    parser.add_argument("--pipeline-interval", type=float, default=30.0, help="seconds between pipeline runs")
    parser.add_argument("--traffic-per-minute", type=float, default=5.0)
    parser.add_argument("--pipeline-log", help="where the pipeline writes its (long) log; default plugins/acme_shop/logs")
    parser.add_argument("--no-traffic", action="store_true", help="start with simulated customers off")
    parser.add_argument("--no-pipeline", action="store_true", help="start with the pipeline timer off")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    shop = Shop(args.db, log_path=args.pipeline_log)
    background = Background(shop, args.pipeline_interval, args.traffic_per_minute, not args.no_traffic, not args.no_pipeline)
    background.start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(shop, background, args.autopsy_url))
    print(f"Acme Shop on http://{args.host}:{args.port}  (database {args.db})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        background.stop()
        server.server_close()


if __name__ == "__main__":
    main()
