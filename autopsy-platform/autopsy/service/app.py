"""The HTTP API and the web UI. Every route is a thin call into Service; see docs/api.md for the contract."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from autopsy import __version__
from autopsy.core.models import AutopsyError
from autopsy.service.engine import Service, ServiceError, not_found
from autopsy.service.scheduler import Scheduler

log = logging.getLogger("autopsy.service")
STATIC = Path(__file__).parent / "static"


def _int(value: Any, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        raise ServiceError(422, "invalid", f"{value!r} is not a number") from None


def create_app(service: Service | None = None, scheduler: bool = True, tick_seconds: float = 5.0,
               allowed_hosts: set[str] | None = None) -> Starlette:
    """`allowed_hosts` limits the Host header (set when bound to loopback, which defeats DNS rebinding)."""
    svc = service or Service()
    sched = Scheduler(svc, tick_seconds)

    def guard(request: Request, has_body: bool = False) -> JSONResponse | None:
        """The API has no login, so a browser page on another site must not be able to drive it."""
        host = request.headers.get("host", "")
        if allowed_hosts is not None and (urlsplit("//" + host).hostname or "").lower() not in allowed_hosts:
            return JSONResponse({"error": "forbidden_host", "message": f"host {host!r} is not allowed"}, 403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc.lower() != host.lower():
                return JSONResponse({"error": "forbidden_origin", "message": "cross-site requests are not allowed"}, 403)
            if has_body and "application/json" not in request.headers.get("content-type", "").lower():
                return JSONResponse({"error": "unsupported_media_type",
                                     "message": "send the body as application/json"}, 415)
        return None

    # handlers take (path params, query params, json body) and return JSON-able data
    def health(p, q, b):
        return {"ok": True, "version": __version__, "time": svc.now(), "state_dir": str(svc.state_dir),
                "scheduler": {"running": sched.running, "last_tick": sched.last_tick}}

    def connection_body(b) -> tuple[str, dict, dict]:
        return b.get("connector", ""), b.get("config") or {}, b.get("secrets") or {}

    routes: list[tuple[str, str, Callable, int]] = [
        ("GET", "/api/health", health, 200),
        ("GET", "/api/overview", lambda p, q, b: svc.overview(), 200),
        ("GET", "/api/connectors", lambda p, q, b: {"connectors": svc.connectors()}, 200),
        # connections
        ("GET", "/api/connections", lambda p, q, b: {"connections": svc.list_connections()}, 200),
        ("POST", "/api/connections/test", lambda p, q, b: svc.test_connection(*connection_body(b)), 200),
        ("POST", "/api/connections", lambda p, q, b: svc.create_connection(b.get("name", ""), *connection_body(b)), 201),
        ("GET", "/api/connections/{id}", lambda p, q, b: svc.get_connection(p["id"]), 200),
        ("PUT", "/api/connections/{id}", lambda p, q, b: svc.update_connection(
            p["id"], b.get("name"), b.get("config") or {}, b.get("secrets") or {}), 200),
        ("DELETE", "/api/connections/{id}", lambda p, q, b: svc.delete_connection(p["id"]) or {"deleted": True}, 200),
        ("POST", "/api/connections/{id}/test", lambda p, q, b: svc.test_saved_connection(p["id"]), 200),
        ("GET", "/api/connections/{id}/schema", lambda p, q, b: svc.connection_schema(p["id"]), 200),
        ("POST", "/api/connections/{id}/suggest", lambda p, q, b: svc.suggest(p["id"], b.get("sources") or []), 200),
        ("POST", "/api/connections/{id}/sample", lambda p, q, b: svc.sample(
            p["id"], b.get("source", ""), _int(b.get("n"), 5)), 200),
        # projects
        ("POST", "/api/projects/import", lambda p, q, b: svc.import_manifest(
            b.get("yaml", ""), b.get("connection_id"), b.get("connection_name")), 201),
        ("GET", "/api/projects/{name}", lambda p, q, b: svc.project_detail(p["name"]), 200),
        ("PUT", "/api/projects/{name}", lambda p, q, b: svc.save_project(
            p["name"], b.get("connection_id", ""), b.get("datasets") or [], b.get("thresholds"), create=False), 200),
        ("DELETE", "/api/projects/{name}", lambda p, q, b: svc.delete_project(p["name"]) or {"deleted": True}, 200),
        ("POST", "/api/projects", lambda p, q, b: svc.save_project(
            b.get("name", ""), b.get("connection_id", ""), b.get("datasets") or [], b.get("thresholds")), 201),
        ("GET", "/api/projects", lambda p, q, b: {"projects": svc.overview()["projects"]}, 200),
        ("GET", "/api/projects/{name}/manifest", lambda p, q, b: {"yaml": svc.manifest_yaml(p["name"])}, 200),
        ("GET", "/api/projects/{name}/mcp-config", lambda p, q, b: svc.mcp_config(p["name"]), 200),
        ("POST", "/api/projects/{name}/validate", lambda p, q, b: svc.validate_project(p["name"]), 200),
        ("POST", "/api/projects/{name}/baseline", lambda p, q, b: svc.learn_baseline(
            p["name"], b.get("since"), b.get("until")), 200),
        ("POST", "/api/projects/{name}/runs", lambda p, q, b: svc.run(
            p["name"], b.get("kind", "monitor"), b.get("dataset"), "manual", b.get("auto_investigate")), 201),
        ("GET", "/api/projects/{name}/runs", lambda p, q, b: {"runs": svc.list_runs(
            p["name"], q.get("kind"), _int(q.get("limit"), 50))}, 200),
        ("GET", "/api/projects/{name}/history", lambda p, q, b: svc.history(p["name"], _int(q.get("limit"), 30)), 200),
        ("GET", "/api/projects/{name}/lineage", lambda p, q, b: svc.lineage(p["name"]), 200),
        ("GET", "/api/projects/{name}/datasets/{dataset}/trend", lambda p, q, b: svc.trend(
            p["name"], p["dataset"], _int(q.get("days"), 30)), 200),
        ("PUT", "/api/projects/{name}/schedule", lambda p, q, b: svc.set_schedule(
            p["name"], b.get("enabled", False), b.get("interval_minutes", 60), b.get("auto_investigate", True)), 200),
        # runs and incidents
        ("GET", "/api/runs", lambda p, q, b: {"runs": svc.list_runs(
            q.get("project"), q.get("kind"), _int(q.get("limit"), 50))}, 200),
        ("GET", "/api/runs/{id}", lambda p, q, b: svc.get_run(_int(p["id"], 0)), 200),
        ("GET", "/api/incidents", lambda p, q, b: {"incidents": svc.list_incidents(
            q.get("project"), q.get("status", "open"), _int(q.get("limit"), 100))}, 200),
        ("GET", "/api/incidents/{id}", lambda p, q, b: svc.get_incident(_int(p["id"], 0)), 200),
        ("POST", "/api/incidents/{id}/ack", lambda p, q, b: svc.acknowledge(
            _int(p["id"], 0), b.get("acknowledged", True)), 200),
    ]

    def view(handler: Callable, ok_status: int):
        async def endpoint(request: Request):
            body: dict[str, Any] = {}
            raw = await request.body() if request.method in ("POST", "PUT", "PATCH") else b""
            refused = guard(request, has_body=bool(raw))
            if refused:
                return refused
            if raw:
                try:
                    body = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    return JSONResponse({"error": "invalid_json", "message": "request body is not valid JSON"}, 400)
                if not isinstance(body, dict):
                    return JSONResponse({"error": "invalid_json", "message": "request body must be a JSON object"}, 400)
            try:
                result = await run_in_threadpool(handler, dict(request.path_params), dict(request.query_params), body)
            except ServiceError as exc:
                return JSONResponse(exc.payload, exc.status)
            except AutopsyError as exc:
                return JSONResponse(exc.to_dict(), 404 if exc.code in ("unknown_dataset", "unknown_column") else 400)
            except Exception as exc:
                log.exception("unhandled error in %s %s", request.method, request.url.path)
                return JSONResponse({"error": "internal", "message": f"{type(exc).__name__}: {exc}"[:300]}, 500)
            return JSONResponse(result, ok_status)

        return endpoint

    async def manifest_file(request: Request):
        refused = guard(request)
        if refused:
            return refused
        name = request.path_params["name"]
        try:
            text = await run_in_threadpool(svc.manifest_yaml, name)
        except ServiceError as exc:
            return JSONResponse(exc.payload, exc.status)
        return PlainTextResponse(text, media_type="text/yaml",
                                 headers={"Content-Disposition": 'attachment; filename="' + name + '.yaml"'})

    async def unknown_api(request: Request):
        return JSONResponse(not_found(f"route {request.url.path}").payload, 404)

    @asynccontextmanager
    async def lifespan(app):
        if scheduler:
            sched.start()
        yield
        sched.stop()

    # literal paths must be tried before {name} ones, so sort by whether they hold parameters
    ordered = sorted(routes, key=lambda r: ("{" in r[1], -len(r[1])))
    table = [Route(path, view(handler, status), methods=[method]) for method, path, handler, status in ordered]
    table.append(Route("/api/projects/{name}/manifest.yaml", manifest_file, methods=["GET"]))
    table.append(Route("/api/{rest:path}", unknown_api, methods=["GET", "POST", "PUT", "DELETE"]))
    if STATIC.is_dir():
        table.append(Mount("/", StaticFiles(directory=STATIC, html=True), name="ui"))
    app = Starlette(routes=table, lifespan=lifespan)
    app.state.service = svc
    return app
