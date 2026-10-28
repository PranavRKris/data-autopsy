"""The six tools as plain functions of (manifest, baseline, database state).

The MCP server only wraps these, and the reference investigator and the tests call them directly,
so what Bob sees is exactly what is tested. Tools never build SQL; they call checks, which build specs.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from autopsy.checks import (
    CheckContext,
    check_freshness,
    check_schema,
    check_volume,
    find_duplicates,
    profile_dataset,
)
from autopsy.core.baseline import Baseline, load_baseline, utcnow
from autopsy.core.manifest import Dataset, Manifest, load_manifest
from autopsy.core.models import MAX_ROWS, AutopsyError, cap_payload
from autopsy.core.registry import create_connector

CHECK_TOOLS = ("check_freshness", "check_volume", "check_schema", "profile_dataset", "find_duplicates")


class Tools:
    def __init__(
        self,
        manifest: Manifest,
        connector: Any = None,
        baseline: Baseline | None = None,
        state_dir: Path | None = None,
        now: Callable[[], datetime] | datetime | None = None,
    ):
        self.manifest = manifest
        self._connector = connector
        self._baseline = baseline
        self._state_dir = state_dir
        self._now = now

    @classmethod
    def from_manifest_path(cls, path: str | Path, **kwargs) -> "Tools":
        return cls(load_manifest(path), **kwargs)

    # --- plumbing -----------------------------------------------------------

    @property
    def connector(self):
        if self._connector is None:
            self._connector = create_connector(self.manifest.connector, self.manifest.connection)
        return self._connector

    def close(self) -> None:
        """Release the database connection (the file may be rebuilt between runs)."""
        if self._connector is not None and hasattr(self._connector, "close"):
            self._connector.close()
        self._connector = None

    def baseline(self) -> Baseline | None:
        return self._baseline or load_baseline(self.manifest.project, self._state_dir)

    def now(self) -> datetime:
        if callable(self._now):
            return self._now()
        return self._now or utcnow()

    def context(self) -> CheckContext:
        return CheckContext(self.manifest, self.connector, self.baseline(), self.now())

    def _run(self, check: Callable, dataset: str, **kwargs) -> dict[str, Any]:
        try:
            return check(self.context(), dataset, **kwargs).to_dict()
        except AutopsyError as exc:
            return exc.to_dict()
        except Exception as exc:  # a database error must reach Bob as data, so the investigation can continue
            return {"error": "check_failed", "message": f"{type(exc).__name__}: {exc}"[:300]}

    # --- the six tools ------------------------------------------------------

    def describe_project(self) -> dict[str, Any]:
        baseline = self.baseline()
        datasets = [self._describe(ds) for ds in self.manifest.datasets]
        payload = {
            "project": self.manifest.project,
            "connector": self.manifest.connector,
            "baseline_available": baseline is not None,
            "datasets": datasets[:MAX_ROWS],
        }
        return cap_payload(payload, MAX_ROWS, 16384)[0]

    def check_freshness(self, dataset: str) -> dict[str, Any]:
        return self._run(check_freshness, dataset)

    def check_schema(self, dataset: str) -> dict[str, Any]:
        return self._run(check_schema, dataset)

    def profile_dataset(self, dataset: str, columns: list[str] | None = None) -> dict[str, Any]:
        return self._run(profile_dataset, dataset, columns=columns)

    def find_duplicates(self, dataset: str) -> dict[str, Any]:
        return self._run(find_duplicates, dataset)

    def check_volume(self, dataset: str) -> dict[str, Any]:
        return self._run(check_volume, dataset)

    def call(self, tool: str, dataset: str) -> dict[str, Any]:
        return getattr(self, tool)(dataset)

    # --- describe_project helpers ---------------------------------------------

    def _describe(self, ds: Dataset) -> dict[str, Any]:
        roles = {name: value for name, value in (
            ("event_time", ds.roles.event_time), ("key", list(ds.roles.key)),
            ("measure", list(ds.roles.measure)), ("required", list(ds.roles.required)),
        ) if value}
        return {
            "name": ds.name,
            "roles": roles,
            "business_visible": ds.business_visible,
            "feeds": list(ds.feeds),
            "fed_by": self.manifest.upstream(ds.name),
            "possible_checks": possible_checks(ds),
        }


def possible_checks(ds: Dataset) -> list[str]:
    """Which tools can say something about this dataset, given the roles it declares."""
    checks = ["check_schema"]
    if ds.roles.event_time:
        checks = ["check_freshness", "check_volume", *checks]
    if ds.roles.measure or ds.roles.required:
        checks.append("profile_dataset")
    if ds.roles.key:
        checks.append("find_duplicates")
    return checks
