"""The service's core: connections, projects, manifests, baselines. Run history and incidents are in runs.py.

Everything here goes through the same manifest loader, connectors and tools as the CLI and the MCP server, so a project
made in the UI is an ordinary manifest that `autopsy` and Bob can use unchanged.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from autopsy.connectors.specs import SPECS, connector_specs, secret_fields
from autopsy.core.baseline import learn_baseline as learn, load_baseline, save_baseline, state_dir as default_state_dir, utcnow
from autopsy.core.manifest import Manifest, parse_manifest, validate_against
from autopsy.core.models import AutopsyError, ManifestError
from autopsy.core.registry import create_connector
from autopsy.mcp_server.tools import Tools
from autopsy.service.runs import RunsMixin
from autopsy.service.secrets import SecretStore
from autopsy.service.store import Store
from autopsy.service.suggest import suggest_roles

_SLUG = re.compile(r"[^A-Za-z0-9_.-]+")
DEFAULT_SCHEDULE = {"enabled": False, "interval_minutes": 60, "auto_investigate": True}


class ServiceError(Exception):
    """An error the API reports with a status code and a stable `error` code."""

    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra

    @property
    def payload(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.extra}


def not_found(what: str) -> ServiceError:
    return ServiceError(404, "not_found", f"{what} not found")


def conflict(message: str) -> ServiceError:
    return ServiceError(409, "conflict", message)


def invalid(message: str, code: str = "invalid", **extra: Any) -> ServiceError:
    return ServiceError(422, code, message, **extra)


def wall() -> datetime:
    """Real UTC time. Service bookkeeping (run times, schedules) never uses the pinned data clock."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def stamp(moment: datetime) -> str:
    return moment.isoformat() + "Z"


class Service(RunsMixin):
    def __init__(self, state: Path | str | None = None, clock=wall):
        self.state_dir = Path(state) if state else default_state_dir()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.state_dir / "service.db")
        self.secrets = SecretStore(self.state_dir / "secrets.json")
        self.secrets.export_env()
        self.clock = clock
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._env_guard = threading.Lock()

    def now(self) -> str:
        return stamp(self.clock())

    # --- connectors and connections -----------------------------------------------

    def connectors(self) -> list[dict[str, Any]]:
        return connector_specs()

    def _clean_config(self, connector: str, config: dict[str, Any], secrets: dict[str, str]) -> dict[str, Any]:
        config = {k: v for k, v in (config or {}).items() if v not in (None, "")}
        spec = SPECS.get(connector)
        if spec is None:
            raise invalid(f"unknown connector {connector!r}; available: {', '.join(SPECS)}", "unknown_connector")
        secret_keys = set(secret_fields(connector))
        allowed: set[str] = set()
        for field in spec["fields"]:
            if field["type"] == "secret":
                allowed.add(f"{field['key']}_env")
            else:
                allowed.add(field["key"])
                if field.get("env_ok"):
                    allowed.add(f"{field['key']}_env")
        unknown = sorted(set(config) - allowed)
        if unknown:
            raise invalid(f"unknown setting(s) for {connector}: {', '.join(unknown)}", "invalid_connection")
        for key in secrets:
            if key not in secret_keys:
                raise invalid(f"{key!r} is not a secret field of {connector}", "invalid_connection")
        for field in spec["fields"]:
            key = field["key"]
            given = key in config or f"{key}_env" in config or (secrets.get(key) if field["type"] == "secret" else False)
            if field.get("required") and not given:
                raise invalid(f"{field['label']} is required", "invalid_connection", field=key)
        return config

    def _public_connection(self, row: dict[str, Any]) -> dict[str, Any]:
        used = [p["name"] for p in self.store.rows("select name from projects where connection_id = ?", (row["id"],))]
        return {
            "id": row["id"], "name": row["name"], "connector": row["connector"], "config": row["config"],
            "secrets_set": sorted(row["secret_envs"]), "used_by": used, "created_at": row["created_at"],
            "last_test": None if row["last_test_at"] is None else
            {"at": row["last_test_at"], "ok": bool(row["last_test_ok"]), "message": row["last_test_message"]},
        }

    def _connection(self, connection_id: str) -> dict[str, Any]:
        row = self.store.row("select * from connections where id = ?", (connection_id,))
        if row is None:
            raise not_found(f"connection {connection_id!r}")
        return row

    def list_connections(self) -> list[dict[str, Any]]:
        return [self._public_connection(r) for r in self.store.rows("select * from connections order by name")]

    def get_connection(self, connection_id: str) -> dict[str, Any]:
        return self._public_connection(self._connection(connection_id))

    def _store_secrets(self, connection_id: str, secrets: dict[str, str], config: dict[str, Any],
                       envs: dict[str, str]) -> dict[str, str]:
        for key, value in secrets.items():
            if value:
                env = f"AUTOPSY_SECRET_{connection_id.upper()}_{key.upper()}"
                self.secrets.set(env, value)
                config[f"{key}_env"] = env
                envs[key] = env
        return envs

    def create_connection(self, name: str, connector: str, config: dict[str, Any],
                          secrets: dict[str, str] | None = None) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise invalid("a connection needs a name", "invalid_connection", field="name")
        if self.store.row("select 1 from connections where name = ?", (name,)):
            raise conflict(f"a connection named {name!r} already exists")
        secrets = secrets or {}
        config = self._clean_config(connector, config, secrets)
        connection_id = uuid.uuid4().hex[:8]
        envs = self._store_secrets(connection_id, secrets, config, {})
        self.store.insert("connections", {
            "id": connection_id, "name": name, "connector": connector, "config": config,
            "secret_envs": envs, "created_at": self.now(),
        })
        return self.get_connection(connection_id)

    def update_connection(self, connection_id: str, name: str | None, config: dict[str, Any],
                          secrets: dict[str, str] | None = None) -> dict[str, Any]:
        row = self._connection(connection_id)
        secrets = secrets or {}
        # a secret left blank keeps its stored value
        cleaned = self._clean_config(row["connector"], {**config, **{f"{k}_env": v for k, v in row["secret_envs"].items()
                                                                     if k not in secrets or not secrets[k]}}, secrets)
        envs = dict(row["secret_envs"])
        self._store_secrets(connection_id, secrets, cleaned, envs)
        values: dict[str, Any] = {"config": cleaned, "secret_envs": envs}
        if name and name.strip() != row["name"]:
            if self.store.row("select 1 from connections where name = ?", (name.strip(),)):
                raise conflict(f"a connection named {name.strip()!r} already exists")
            values["name"] = name.strip()
        self.store.update("connections", "id", connection_id, values)
        self._rewrite_manifests(connection_id)
        return self.get_connection(connection_id)

    def delete_connection(self, connection_id: str) -> None:
        row = self._connection(connection_id)
        used = [p["name"] for p in self.store.rows("select name from projects where connection_id = ?", (connection_id,))]
        if used:
            raise conflict(f"connection {row['name']!r} is used by project(s): {', '.join(used)}")
        for env in row["secret_envs"].values():
            self.secrets.delete(env)
        self.store.run("delete from connections where id = ?", (connection_id,))

    @contextmanager
    def _connector(self, connection: dict[str, Any]) -> Iterator[Any]:
        connector = create_connector(connection["connector"], connection["config"])
        try:
            yield connector
        finally:
            if hasattr(connector, "close"):
                connector.close()

    @staticmethod
    def _datasets_of(connector: Any) -> list[dict[str, Any]]:
        return [{"name": n, "columns": len(connector.describe(n))} for n in connector.list_datasets()]

    def test_connection(self, connector: str, config: dict[str, Any], secrets: dict[str, str] | None = None) -> dict[str, Any]:
        """Try a connection that is not saved yet. Secret values live in the environment only for the test."""
        secrets = secrets or {}
        config = self._clean_config(connector, config, secrets)
        temp = {}
        token = uuid.uuid4().hex[:6].upper()
        for key, value in secrets.items():
            if value:
                temp[key] = f"AUTOPSY_TEST_{token}_{key.upper()}"
        with self._env_guard:
            try:
                for key, env in temp.items():
                    os.environ[env] = secrets[key]
                    config[f"{key}_env"] = env
                return self._try({"connector": connector, "config": config})
            finally:
                for env in temp.values():
                    os.environ.pop(env, None)

    def test_saved_connection(self, connection_id: str) -> dict[str, Any]:
        row = self._connection(connection_id)
        result = self._try(row)
        self.store.update("connections", "id", connection_id, {
            "last_test_at": self.now(), "last_test_ok": int(result["ok"]), "last_test_message": result["message"]})
        return result

    def _try(self, connection: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._connector(connection) as connector:
                datasets = self._datasets_of(connector)
        except AutopsyError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message, "datasets": []}
        except Exception as exc:  # a driver error must reach the form as text, not as a 500
            return {"ok": False, "code": "connection_failed", "message": f"{type(exc).__name__}: {exc}"[:300], "datasets": []}
        noun = "dataset" if len(datasets) == 1 else "datasets"
        return {"ok": True, "message": f"Connected: {len(datasets)} {noun} found", "datasets": datasets}

    def connection_schema(self, connection_id: str, limit: int = 100) -> dict[str, Any]:
        row = self._connection(connection_id)
        try:
            with self._connector(row) as connector:
                names = connector.list_datasets()
                datasets = [{"name": n, "columns": [
                    {"name": c.name, "type": c.type, "kind": c.kind, "nullable": c.nullable}
                    for c in connector.describe(n)]} for n in names[:limit]]
        except AutopsyError as exc:
            raise ServiceError(400, exc.code, exc.message) from exc
        return {"datasets": datasets, "total": len(names), "truncated": len(names) > limit}

    def suggest(self, connection_id: str, sources: list[str]) -> dict[str, Any]:
        row = self._connection(connection_id)
        out: dict[str, Any] = {}
        try:
            with self._connector(row) as connector:
                for source in sources[:50]:
                    try:
                        out[source] = suggest_roles(connector, source)
                    except AutopsyError as exc:
                        out[source] = exc.to_dict()
        except AutopsyError as exc:
            raise ServiceError(400, exc.code, exc.message) from exc
        return {"suggestions": out}

    def sample(self, connection_id: str, source: str, n: int = 5) -> dict[str, Any]:
        row = self._connection(connection_id)
        try:
            with self._connector(row) as connector:
                columns = [c.name for c in connector.describe(source)]
                return {"source": source, "columns": columns, "rows": connector.sample(source, n)}
        except AutopsyError as exc:
            raise ServiceError(404 if exc.code == "unknown_dataset" else 400, exc.code, exc.message) from exc

    # --- projects and manifests -----------------------------------------------------

    def _project(self, name: str) -> dict[str, Any]:
        row = self.store.row("select * from projects where name = ?", (name,))
        if row is None:
            raise not_found(f"project {name!r}")
        return row

    def _lock(self, project: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(project, threading.Lock())

    @staticmethod
    def _normalize_datasets(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for ds in datasets or []:
            roles = ds.get("roles") or {}
            clean_roles: dict[str, Any] = {}
            if roles.get("event_time"):
                clean_roles["event_time"] = roles["event_time"]
            for role in ("key", "measure", "required"):
                if roles.get(role):
                    clean_roles[role] = list(roles[role])
            entry: dict[str, Any] = {"name": ds.get("name"), "source": ds.get("source"), "roles": clean_roles}
            if ds.get("business_visible"):
                entry["business_visible"] = True
            if ds.get("feeds"):
                entry["feeds"] = list(ds["feeds"])
            expected = {k: v for k, v in (ds.get("expected") or {}).items() if v not in (None, "", {})}
            if expected:
                entry["expected"] = expected
            out.append(entry)
        return out

    @staticmethod
    def _clean_thresholds(thresholds: dict[str, Any] | None) -> dict[str, Any]:
        return {k: v for k, v in (thresholds or {}).items() if v not in (None, "")}

    def manifest_dict(self, project: dict[str, Any]) -> dict[str, Any]:
        connection = self._connection(project["connection_id"])
        raw = {"project": project["name"], "connector": connection["connector"],
               "connection": connection["config"], "datasets": project["spec"]["datasets"]}
        if project["spec"].get("thresholds"):
            raw["thresholds"] = project["spec"]["thresholds"]
        return raw

    def manifest_for(self, name: str) -> Manifest:
        return parse_manifest(self.manifest_dict(self._project(name)), self.manifest_path(name))

    def manifest_path(self, name: str) -> Path:
        return self.state_dir / "manifests" / f"{name}.yaml"

    def manifest_yaml(self, name: str) -> str:
        header = "# Generated by the Pipeline Autopsy service. Edit the project in the UI, or use this file with `autopsy` and Bob.\n"
        return header + yaml.safe_dump(self.manifest_dict(self._project(name)), sort_keys=False, allow_unicode=True)

    def _write_manifest(self, name: str) -> Path:
        path = self.manifest_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.manifest_yaml(name), encoding="utf-8")
        return path

    def _rewrite_manifests(self, connection_id: str) -> None:
        for p in self.store.rows("select name from projects where connection_id = ?", (connection_id,)):
            self._write_manifest(p["name"])

    def _check_against_database(self, manifest: Manifest, connection: dict[str, Any]) -> list[dict[str, str]]:
        try:
            with self._connector(connection) as connector:
                issues = validate_against(manifest, connector)
        except AutopsyError as exc:
            raise invalid(exc.message, exc.code) from exc
        return [{"level": i.level, "dataset": i.dataset, "message": i.message} for i in issues]

    def save_project(self, name: str, connection_id: str, datasets: list[dict[str, Any]],
                     thresholds: dict[str, Any] | None = None, create: bool = True,
                     check_database: bool = True) -> dict[str, Any]:
        name = (name or "").strip()
        existing = self.store.row("select * from projects where name = ?", (name,))
        if create and existing:
            raise conflict(f"project {name!r} already exists")
        if not create and not existing:
            raise not_found(f"project {name!r}")
        connection = self._connection(connection_id)
        spec = {"datasets": self._normalize_datasets(datasets), "thresholds": self._clean_thresholds(thresholds)}
        raw = {"project": name, "connector": connection["connector"], "connection": connection["config"],
               "datasets": spec["datasets"], **({"thresholds": spec["thresholds"]} if spec["thresholds"] else {})}
        try:
            manifest = parse_manifest(raw)
        except ManifestError as exc:
            raise invalid(exc.message, "invalid_manifest") from exc
        if check_database:
            issues = self._check_against_database(manifest, connection)
            errors = [i for i in issues if i["level"] == "error"]
            if errors:
                raise invalid(f"{len(errors)} problem(s) between the mapping and the database", "mapping_mismatch",
                              issues=issues)
        now = self.now()
        if existing:
            self.store.update("projects", "name", name, {"connection_id": connection_id, "spec": spec, "updated_at": now})
        else:
            self.store.insert("projects", {"name": name, "connection_id": connection_id, "spec": spec,
                                           "created_at": now, "updated_at": now, "schedule": DEFAULT_SCHEDULE})
        self._write_manifest(name)
        return self.project_detail(name)

    def import_manifest(self, text: str, connection_id: str | None = None, connection_name: str | None = None) -> dict[str, Any]:
        """Bring an existing manifest file into the service; its connection becomes a saved connection."""
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise invalid(f"not valid YAML: {exc}", "invalid_manifest") from exc
        try:
            manifest = parse_manifest(raw)
        except ManifestError as exc:
            raise invalid(exc.message, "invalid_manifest") from exc
        if self.store.row("select 1 from projects where name = ?", (manifest.project,)):
            raise conflict(f"project {manifest.project!r} already exists")
        if connection_id is None:
            base = (connection_name or manifest.project).strip()
            name, n = base, 1
            while self.store.row("select 1 from connections where name = ?", (name,)):
                n += 1
                name = f"{base}-{n}"
            connection = self.create_connection(name, manifest.connector, dict(manifest.connection))
            connection_id = connection["id"]
        datasets = raw["datasets"]
        project = self.save_project(manifest.project, connection_id, datasets, raw.get("thresholds"), check_database=False)
        return {"project": project, "validation": self.validate_project(manifest.project)}

    def validate_project(self, name: str) -> dict[str, Any]:
        row = self._project(name)
        manifest = self.manifest_for(name)
        try:
            issues = self._check_against_database(manifest, self._connection(row["connection_id"]))
        except ServiceError as exc:
            return {"ok": False, "message": exc.message, "issues": []}
        errors = [i for i in issues if i["level"] == "error"]
        return {"ok": not errors, "issues": issues,
                "message": "The mapping matches the database" if not errors else f"{len(errors)} problem(s) found"}

    def delete_project(self, name: str) -> None:
        self._project(name)
        self.store.run("delete from incidents where project = ?", (name,))
        self.store.run("delete from runs where project = ?", (name,))
        self.store.run("delete from projects where name = ?", (name,))
        for path in (self.state_dir / f"{name}.json", self.manifest_path(name)):
            path.unlink(missing_ok=True)

    def project_detail(self, name: str) -> dict[str, Any]:
        row = self._project(name)
        connection = self._connection(row["connection_id"])
        return {
            "name": name,
            "connection": {"id": connection["id"], "name": connection["name"], "connector": connection["connector"]},
            "datasets": row["spec"]["datasets"],
            "thresholds": row["spec"].get("thresholds") or {},
            "schedule": {**DEFAULT_SCHEDULE, **row["schedule"], "next_run_at": row["next_run_at"]},
            "baseline": self.baseline_info(name),
            "created_at": row["created_at"], "updated_at": row["updated_at"], "last_run_at": row["last_run_at"],
            "status": self.project_status(name),
            "open_incidents": self.list_incidents(project=name, status="open"),
            "last_run": self.last_run(name),
        }

    def mcp_config(self, name: str) -> dict[str, Any]:
        row = self._project(name)
        connection = self._connection(row["connection_id"])
        path = self._write_manifest(name)
        env_names = sorted({*connection["secret_envs"].values(),
                            *(v for k, v in connection["config"].items() if k.endswith("_env"))})
        return {
            "manifest_path": str(path),
            "mcpServers": {f"autopsy-{name}": {
                "command": sys.executable,
                "args": ["-m", "autopsy.mcp_server", "--manifest", str(path)],
                "env": {e: "<same value this service has>" for e in env_names},
            }},
            "note": "Bob's server needs the same environment variables as this service; secrets are not shown here.",
        }

    # --- baselines ------------------------------------------------------------------

    def baseline_info(self, name: str) -> dict[str, Any] | None:
        baseline = load_baseline(name, self.state_dir)
        if baseline is None:
            return None
        datasets = baseline.data.get("datasets", {})
        return {"created_at": baseline.data.get("created_at"),
                "datasets": {n: {"rows": d.get("rows"), "columns": len(d.get("columns", []))} for n, d in datasets.items()}}

    def learn_baseline(self, name: str, since: str | None = None, until: str | None = None,
                       trigger: str = "manual") -> dict[str, Any]:
        row = self._project(name)
        manifest = self.manifest_for(name)
        started = time.perf_counter()
        run_id = self._begin_run(name, "baseline", trigger)
        try:
            with self._connector(self._connection(row["connection_id"])) as connector:
                data = learn(manifest, connector, utcnow(), since or None, until or None)
            save_baseline(data, self.state_dir)
        except AutopsyError as exc:
            self._finish_run(run_id, started, "error", f"Baseline failed: {exc.message}")
            raise ServiceError(400, exc.code, exc.message) from exc
        total = sum(d["rows"] for d in data["datasets"].values())
        self._finish_run(run_id, started, "ok",
                         f"Baseline learned from {total:,} rows across {len(data['datasets'])} dataset(s)")
        return {"run_id": run_id, "baseline": self.baseline_info(name)}

    # --- schedule -------------------------------------------------------------------

    def set_schedule(self, name: str, enabled: bool, interval_minutes: int, auto_investigate: bool = True) -> dict[str, Any]:
        self._project(name)
        interval = int(interval_minutes)
        if not 1 <= interval <= 7 * 24 * 60:
            raise invalid("interval_minutes must be between 1 and 10080", "invalid_schedule")
        schedule = {"enabled": bool(enabled), "interval_minutes": interval, "auto_investigate": bool(auto_investigate)}
        next_run = stamp(self.clock() + timedelta(minutes=interval)) if enabled else None
        self.store.update("projects", "name", name, {"schedule": schedule, "next_run_at": next_run})
        return {**schedule, "next_run_at": next_run}

    def due_projects(self, now: str | None = None) -> list[str]:
        now = now or self.now()
        rows = self.store.rows("select name, schedule, next_run_at from projects where next_run_at is not null")
        return [r["name"] for r in rows if r["schedule"].get("enabled") and r["next_run_at"] <= now]

    def tools_for(self, name: str) -> Tools:
        return Tools(self.manifest_for(name), state_dir=self.state_dir)
