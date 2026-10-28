"""Runs, findings and incidents: what the service remembers, and the views the UI draws from it.

A monitor run checks every dataset. When something fails it starts an investigation (the same reference
investigator `autopsy investigate` uses) from the failing datasets, and the investigation opens or updates an
incident. A later monitor run with no failures resolves open incidents.
"""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from autopsy.core.baseline import load_baseline, utcnow
from autopsy.core.models import FAIL, OK, SKIPPED, WARN, Agg, AggSpec, AutopsyError, Bucket, Filter
from autopsy.investigate import investigate

if TYPE_CHECKING:
    from autopsy.service.engine import Service

log = logging.getLogger("autopsy.service")

ERROR = "error"
_SEVERITY_ORDER = "case severity when 'SEV1' then 1 when 'SEV2' then 2 when 'SEV3' then 3 else 4 end"
_RANK = {SKIPPED: 0, OK: 1, WARN: 2, ERROR: 3, FAIL: 4}
RUN_COLUMNS = ("id, project, kind, trigger, status, started_at, finished_at, duration_ms, summary, counts, "
               "root_dataset, root_check, severity, report is not null as has_report")


def worst(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: _RANK[s]) if statuses else SKIPPED


def finding_status(finding: dict[str, Any]) -> str:
    return ERROR if "error" in finding else finding["status"]


def finding_summary(finding: dict[str, Any]) -> str:
    return finding["message"] if "error" in finding else finding["summary"]


def describe_counts(counts: dict[str, int]) -> str:
    parts = [f"{counts[k]} {label}" for k, label in
             ((FAIL, "failed"), (ERROR, "could not run"), (WARN, "warning"), (OK, "ok"), (SKIPPED, "skipped")) if counts.get(k)]
    return ", ".join(parts) or "no checks"


class RunsMixin:
    # --- bookkeeping --------------------------------------------------------------------

    def _begin_run(self: "Service", project: str, kind: str, trigger: str) -> int:
        return self.store.insert("runs", {"project": project, "kind": kind, "trigger": trigger,
                                          "status": "running", "started_at": self.now()})

    def _finish_run(self: "Service", run_id: int, started: float, status: str, summary: str,
                    counts: dict[str, int] | None = None, root: tuple[str | None, str | None, str | None] = (None, None, None),
                    report: str | None = None) -> None:
        self.store.update("runs", "id", run_id, {
            "status": status, "finished_at": self.now(), "duration_ms": int((time.perf_counter() - started) * 1000),
            "summary": summary, "counts": counts, "root_dataset": root[0], "root_check": root[1], "severity": root[2],
            "report": report})
        self.store.run("update projects set last_run_at = ? where name = (select project from runs where id = ?)",
                       (self.now(), run_id))

    def _persist_findings(self: "Service", run_id: int, project: str, items: list[tuple[str, str, dict[str, Any]]]) -> None:
        at = self.now()
        with self.store.connect() as con:
            con.executemany(
                "insert into findings (run_id, project, dataset, tool, status, summary, data, at) values (?, ?, ?, ?, ?, ?, ?, ?)",
                [(run_id, project, dataset, tool, finding_status(f), finding_summary(f), json.dumps(f, default=str), at)
                 for dataset, tool, f in items])

    @staticmethod
    def _counts(items: list[tuple[str, str, dict[str, Any]]]) -> dict[str, int]:
        tally = Counter(finding_status(f) for _, _, f in items)
        return {k: tally.get(k, 0) for k in (OK, WARN, FAIL, SKIPPED, ERROR)}

    # --- running ------------------------------------------------------------------------

    def run(self: "Service", project: str, kind: str = "monitor", dataset: str | None = None,
            trigger: str = "manual", auto_investigate: bool | None = None) -> dict[str, Any]:
        from autopsy.service.engine import conflict, invalid, not_found

        row = self._project(project)
        if kind not in ("monitor", "investigation"):
            raise invalid("kind must be 'monitor' or 'investigation'", "invalid_run")
        if dataset and dataset not in {d["name"] for d in row["spec"]["datasets"]}:
            raise not_found(f"dataset {dataset!r} in project {project!r}")
        lock = self._lock(project)
        if not lock.acquire(blocking=False):
            raise conflict(f"a run is already in progress for project {project!r}")
        try:
            if kind == "monitor":
                auto = row["schedule"].get("auto_investigate", True) if auto_investigate is None else auto_investigate
                run_id = self._monitor(project, trigger, auto)
            else:
                run_id = self._investigation(project, [dataset] if dataset else None, trigger, resolve_others=False)
            return self.get_run(run_id)
        finally:
            lock.release()

    def run_due(self: "Service") -> list[str]:
        """Run every scheduled project whose time has come (the scheduler calls this)."""
        from autopsy.service.engine import ServiceError, stamp

        ran = []
        for name in self.due_projects():
            interval = self._project(name)["schedule"].get("interval_minutes", 60)
            try:
                self.run(name, "monitor", trigger="schedule")
                ran.append(name)
            except ServiceError:
                log.info("scheduled run of %s skipped: a run is already in progress", name)
            except Exception:
                log.exception("scheduled run of %s failed", name)
            finally:
                self.store.update("projects", "name", name,
                                  {"next_run_at": stamp(self.clock() + timedelta(minutes=int(interval)))})
        return ran

    def _monitor(self: "Service", project: str, trigger: str, auto_investigate: bool) -> int:
        started = time.perf_counter()
        run_id = self._begin_run(project, "monitor", trigger)
        tools = self.tools_for(project)
        try:
            described = tools.describe_project()
            items = [(d["name"], tool, tools.call(tool, d["name"])) for d in described["datasets"] for tool in d["possible_checks"]]
            self._persist_findings(run_id, project, items)
            counts = self._counts(items)
            status = worst([finding_status(f) for _, _, f in items]) if items else SKIPPED
            summary = f"{len(items)} checks across {len(described['datasets'])} dataset(s): {describe_counts(counts)}"
            if status == ERROR and counts[OK] + counts[WARN] == 0:
                first = next(f for _, _, f in items if "error" in f)
                summary = f"Could not run checks: {first['message']}"
            self._finish_run(run_id, started, status, summary, counts)
            failing = sorted({d for d, _, f in items if f.get("status") == FAIL})
            if failing and auto_investigate:
                self._investigation(project, failing, "auto", resolve_others=True, tools=tools)
            elif not failing and status != ERROR:
                self._resolve_incidents(project)
        except Exception as exc:
            log.exception("monitor run of %s failed", project)
            self._finish_run(run_id, started, ERROR, f"Run failed: {type(exc).__name__}: {exc}"[:300])
        finally:
            tools.close()
        return run_id

    def _investigation(self: "Service", project: str, start: list[str] | None, trigger: str,
                       resolve_others: bool, tools=None) -> int:
        started = time.perf_counter()
        run_id = self._begin_run(project, "investigation", trigger)
        own = tools is None
        tools = tools or self.tools_for(project)
        try:
            inv = investigate(tools, start)
            items = [(d, t, f) for d, fs in inv.findings.items() for t, f in fs.items()]
            self._persist_findings(run_id, project, items)
            counts = self._counts(items)
            failing = counts[FAIL] > 0
            if inv.root_dataset and failing:
                finding = inv.findings[inv.root_dataset][inv.root_check]
                summary = f"{inv.severity}: {inv.root_dataset} / {inv.root_check}. {finding_summary(finding)}"
                self._finish_run(run_id, started, FAIL, summary, counts,
                                 (inv.root_dataset, inv.root_check, inv.severity), inv.report)
                self._open_incident(project, inv, run_id, summary, resolve_others)
            else:
                status = worst([finding_status(f) for _, _, f in items])
                summary = ("No incident found: " if status != FAIL else "") + describe_counts(counts)
                root = (inv.root_dataset, inv.root_check, inv.severity) if inv.root_dataset else (None, None, None)
                self._finish_run(run_id, started, status, summary, counts, root, inv.report)
                if resolve_others:
                    self._resolve_incidents(project)
        except Exception as exc:
            log.exception("investigation of %s failed", project)
            self._finish_run(run_id, started, ERROR, f"Investigation failed: {type(exc).__name__}: {exc}"[:300])
        finally:
            if own:
                tools.close()
        return run_id

    # --- incidents ----------------------------------------------------------------------

    def _open_incident(self: "Service", project: str, inv, run_id: int, summary: str, resolve_others: bool) -> None:
        now = self.now()
        open_rows = self.store.rows("select * from incidents where project = ? and status = 'open'", (project,))
        match = next((i for i in open_rows if (i["root_dataset"], i["root_check"]) == (inv.root_dataset, inv.root_check)), None)
        if inv.other_roots:
            summary += f" Other failing roots: {', '.join(inv.other_roots)}."
        if match:
            self.store.update("incidents", "id", match["id"], {
                "last_seen": now, "occurrences": match["occurrences"] + 1, "severity": inv.severity,
                "run_id": run_id, "summary": summary})
        else:
            self.store.insert("incidents", {
                "project": project, "root_dataset": inv.root_dataset, "root_check": inv.root_check,
                "severity": inv.severity, "status": "open", "first_seen": now, "last_seen": now,
                "run_id": run_id, "summary": summary})
        if resolve_others:      # only a full monitor sweep can say that a different cause is gone
            for other in open_rows:
                if match is None or other["id"] != match["id"]:
                    self._resolve(other["id"], now)

    def _resolve(self: "Service", incident_id: int, now: str) -> None:
        self.store.update("incidents", "id", incident_id, {"status": "resolved", "resolved_at": now})

    def _resolve_incidents(self: "Service", project: str) -> None:
        now = self.now()
        for row in self.store.rows("select id from incidents where project = ? and status = 'open'", (project,)):
            self._resolve(row["id"], now)

    def list_incidents(self: "Service", project: str | None = None, status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        where, params = [], []
        if project:
            where.append("project = ?")
            params.append(project)
        if status != "all":
            where.append("status = ?")
            params.append(status)
        sql = "select * from incidents" + (" where " + " and ".join(where) if where else "")
        sql += f" order by (status = 'open') desc, {_SEVERITY_ORDER}, last_seen desc limit ?"
        return [{**r, "acknowledged": bool(r["acknowledged"])} for r in self.store.rows(sql, (*params, limit))]

    def get_incident(self: "Service", incident_id: int) -> dict[str, Any]:
        from autopsy.service.engine import not_found

        row = self.store.row("select * from incidents where id = ?", (incident_id,))
        if row is None:
            raise not_found(f"incident {incident_id}")
        related = self.store.rows(
            f"select {RUN_COLUMNS} from runs where project = ? and kind = 'investigation' and root_dataset = ? "
            "and root_check = ? order by id desc limit 20", (row["project"], row["root_dataset"], row["root_check"]))
        return {**row, "acknowledged": bool(row["acknowledged"]),
                "run": self.get_run(row["run_id"]) if row["run_id"] else None, "related_runs": related}

    def acknowledge(self: "Service", incident_id: int, acknowledged: bool) -> dict[str, Any]:
        self.get_incident(incident_id)
        self.store.update("incidents", "id", incident_id, {"acknowledged": int(bool(acknowledged))})
        return self.get_incident(incident_id)

    # --- reading runs -------------------------------------------------------------------

    def get_run(self: "Service", run_id: int) -> dict[str, Any]:
        from autopsy.service.engine import not_found

        row = self.store.row("select * from runs where id = ?", (run_id,))
        if row is None:
            raise not_found(f"run {run_id}")
        findings = self.store.rows(
            "select dataset, tool, status, summary, data, at from findings where run_id = ? order by id", (run_id,))
        return {**row, "findings": [{"dataset": f["dataset"], "tool": f["tool"], "status": f["status"],
                                     "summary": f["summary"], "finding": f["data"]} for f in findings]}

    def list_runs(self: "Service", project: str | None = None, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        where, params = [], []
        for column, value in (("project", project), ("kind", kind)):
            if value:
                where.append(f"{column} = ?")
                params.append(value)
        sql = f"select {RUN_COLUMNS} from runs" + (" where " + " and ".join(where) if where else "")
        return [{**r, "has_report": bool(r["has_report"])}
                for r in self.store.rows(sql + " order by id desc limit ?", (*params, min(int(limit), 500)))]

    def last_run(self: "Service", project: str) -> dict[str, Any] | None:
        rows = self.store.rows(f"select {RUN_COLUMNS} from runs where project = ? and kind = 'monitor' "
                               "and status != 'running' order by id desc limit 1", (project,))
        return {**rows[0], "has_report": bool(rows[0]["has_report"])} if rows else None

    # --- views the UI draws -------------------------------------------------------------

    def project_status(self: "Service", project: str) -> dict[str, Any]:
        rows = self.store.rows(
            "select f.dataset, f.tool, f.status, f.summary, f.run_id, f.at from findings f join "
            "(select dataset, tool, max(id) as mid from findings where project = ? group by dataset, tool) m "
            "on f.id = m.mid order by f.dataset, f.tool", (project,))
        datasets: dict[str, dict[str, Any]] = {}
        for r in rows:
            datasets.setdefault(r["dataset"], {})[r["tool"]] = {k: r[k] for k in ("status", "summary", "run_id", "at")}
        per_dataset = {d: worst([c["status"] for c in checks.values()]) for d, checks in datasets.items()}
        tally = Counter(r["status"] for r in rows)
        return {"overall": worst(list(per_dataset.values())) if per_dataset else None, "datasets": datasets,
                "per_dataset": per_dataset, "counts": {k: tally.get(k, 0) for k in (OK, WARN, FAIL, SKIPPED, ERROR)},
                "checked_at": max((r["at"] for r in rows), default=None)}

    def history(self: "Service", project: str, limit: int = 30) -> dict[str, Any]:
        runs = self.store.rows("select id, started_at, status, trigger from runs where project = ? and kind = 'monitor' "
                               "and status != 'running' order by id desc limit ?", (project, min(int(limit), 200)))[::-1]
        if not runs:
            return {"runs": [], "cells": []}
        index = {r["id"]: i for i, r in enumerate(runs)}
        marks = ",".join("?" for _ in runs)
        found = self.store.rows(f"select run_id, dataset, tool, status from findings where run_id in ({marks}) order by id",
                                [r["id"] for r in runs])
        cells: dict[tuple[str, str], list[str | None]] = {}
        for f in found:
            cells.setdefault((f["dataset"], f["tool"]), [None] * len(runs))[index[f["run_id"]]] = f["status"]
        return {"runs": runs, "cells": [{"dataset": d, "tool": t, "statuses": s} for (d, t), s in sorted(cells.items())]}

    def lineage(self: "Service", project: str) -> dict[str, Any]:
        manifest = self.manifest_for(project)
        status = self.project_status(project)["per_dataset"]
        roots = {i["root_dataset"] for i in self.list_incidents(project=project, status="open")}
        nodes = [{"name": d.name, "source": d.source, "business_visible": d.business_visible,
                  "level": _depth(manifest, d.name),
                  "status": status.get(d.name), "incident_root": d.name in roots,
                  "roles": {"event_time": d.roles.event_time, "key": list(d.roles.key),
                            "measure": list(d.roles.measure), "required": list(d.roles.required)}}
                 for d in manifest.datasets]
        return {"nodes": nodes, "edges": [{"from": d.name, "to": t} for d in manifest.datasets for t in d.feeds]}

    def trend(self: "Service", project: str, dataset: str, days: int = 30) -> dict[str, Any]:
        days = max(2, min(int(days), 90))
        row = self._project(project)
        manifest = self.manifest_for(project)
        ds = manifest.dataset(dataset)
        today = utcnow().date()
        first = today - timedelta(days=days - 1)
        out: dict[str, Any] = {"dataset": dataset, "event_time": ds.roles.event_time, "today": today.isoformat(),
                               "days": [], "volume": [], "columns": {}, "baseline": None}
        baseline = load_baseline(project, self.state_dir)
        recorded = baseline.dataset(dataset) if baseline else None
        if recorded:
            out["baseline"] = {"volume": recorded.get("daily_volume"), "columns": recorded.get("stats", {})}
        if not ds.roles.event_time:
            return out
        tracked = list(dict.fromkeys([*ds.roles.measure, *ds.roles.required]))
        with self._connector(self._connection(row["connection_id"])) as connector:
            kinds = {c.name: c.kind for c in connector.describe(ds.source)}
            select = [Agg("count", "*", "n")]
            for i, col in enumerate(tracked):
                select.append(Agg("count_null", col, f"nu_{i}"))
                if kinds.get(col) == "numeric":
                    select.append(Agg("median", col, f"md_{i}"))
            rows = connector.aggregate(ds.source, AggSpec(
                select=select, group_by=[Bucket(ds.roles.event_time, "day")],
                where=[Filter(ds.roles.event_time, ">=", first.isoformat())], order_by=["day"], limit=1000))
        by_day = {r["day"]: r for r in rows}
        out["days"] = [(first + timedelta(days=i)).isoformat() for i in range(days)]
        out["volume"] = [by_day.get(d, {}).get("n", 0) for d in out["days"]]
        for i, col in enumerate(tracked):
            points = []
            for d in out["days"]:
                r = by_day.get(d)
                n = r["n"] if r else 0
                points.append({"null_rate": (r[f"nu_{i}"] / n) if r and n else None, "median": r.get(f"md_{i}") if r else None})
            out["columns"][col] = {"kind": kinds.get(col), "points": points}
        return out

    def project_summary(self: "Service", project: str) -> dict[str, Any]:
        row = self._project(project)
        status = self.project_status(project)
        incidents = self.list_incidents(project=project, status="open")
        baseline = load_baseline(project, self.state_dir)
        schedule = {**{"enabled": False, "interval_minutes": 60, "auto_investigate": True}, **row["schedule"],
                    "next_run_at": row["next_run_at"]}
        return {
            "name": project, "connector": self._connection(row["connection_id"])["connector"],
            "datasets": len(row["spec"]["datasets"]),
            "business_visible": [d["name"] for d in row["spec"]["datasets"] if d.get("business_visible")],
            "status": status["overall"], "counts": status["counts"], "checked_at": status["checked_at"],
            "baseline_at": baseline.data.get("created_at") if baseline else None,
            "open_incidents": len(incidents), "worst_severity": incidents[0]["severity"] if incidents else None,
            "last_run": self.last_run(project), "schedule": schedule,
        }

    def overview(self: "Service") -> dict[str, Any]:
        names = [r["name"] for r in self.store.rows("select name from projects order by name")]
        return {"projects": [self.project_summary(n) for n in names],
                "open_incidents": self.list_incidents(status="open", limit=20),
                "recent_runs": self.list_runs(limit=15)}


def _depth(manifest, name: str) -> int:
    ups = manifest.upstream(name)
    return max([0, *[1 + _depth(manifest, u) for u in ups]])
