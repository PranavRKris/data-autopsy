"""Load and validate a project manifest: the only file a new project has to write."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from autopsy.core.models import ManifestError, UnknownDataset

if TYPE_CHECKING:
    from autopsy.connectors.base import Connector

_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_ENV_VAR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_KEY = re.compile(r"pass(word|wd)?|secret|token|credential|api[_-]?key|private[_-]?key", re.I)

_TOP_KEYS = {"project", "connector", "connection", "datasets", "thresholds"}
_DATASET_KEYS = {"name", "source", "roles", "business_visible", "feeds", "expected"}
_ROLE_KEYS = {"event_time", "key", "measure", "required"}
_EXPECTED_KEYS = {"max_age_hours", "max_null_rate", "value_range"}
_THRESHOLD_KEYS = {"max_age_hours", "max_null_rate", "volume_change_ratio", "median_shift_factor"}


@dataclass(frozen=True)
class Roles:
    event_time: str | None = None
    key: tuple[str, ...] = ()
    measure: tuple[str, ...] = ()
    required: tuple[str, ...] = ()

    def columns(self) -> list[str]:
        cols = ([self.event_time] if self.event_time else []) + [*self.key, *self.measure, *self.required]
        return list(dict.fromkeys(cols))


@dataclass(frozen=True)
class Expected:
    max_age_hours: float | None = None
    max_null_rate: float | None = None
    value_range: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class Dataset:
    name: str
    source: str
    roles: Roles
    business_visible: bool = False
    feeds: tuple[str, ...] = ()
    expected: Expected = Expected()


@dataclass(frozen=True)
class Manifest:
    project: str
    connector: str
    connection: dict[str, Any]
    datasets: tuple[Dataset, ...]
    thresholds: dict[str, float] = field(default_factory=dict)
    path: Path | None = None

    def dataset(self, name: str) -> Dataset:
        for ds in self.datasets:
            if ds.name == name:
                return ds
        raise UnknownDataset(f"{name!r} is not a dataset in the manifest for project {self.project!r}")

    def upstream(self, name: str) -> list[str]:
        """Datasets that feed `name` directly."""
        return [ds.name for ds in self.datasets if name in ds.feeds]

    def ancestors(self, name: str) -> list[str]:
        """Every dataset upstream of `name`, nearest first."""
        seen: list[str] = []
        frontier = [name]
        while frontier:
            nxt = []
            for current in frontier:
                for up in self.upstream(current):
                    if up not in seen:
                        seen.append(up)
                        nxt.append(up)
            frontier = nxt
        return seen

    def descendants(self, name: str) -> list[str]:
        seen: list[str] = []
        frontier = [name]
        while frontier:
            nxt = []
            for current in frontier:
                for down in self.dataset(current).feeds:
                    if down not in seen:
                        seen.append(down)
                        nxt.append(down)
            frontier = nxt
        return seen

    def threshold(self, key: str) -> float | None:
        return self.thresholds.get(key)


def load_manifest(path: str | Path) -> Manifest:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"manifest {path} is not valid YAML: {exc}") from exc
    return parse_manifest(raw, path)


def parse_manifest(raw: Any, path: Path | None = None) -> Manifest:
    if not isinstance(raw, dict):
        raise ManifestError("manifest must be a YAML mapping")
    _no_unknown(raw, _TOP_KEYS, "manifest")
    for required in ("project", "connector", "connection", "datasets"):
        if required not in raw:
            raise ManifestError(f"manifest is missing required field {required!r}")

    project = str(raw["project"])
    if not _NAME.match(project):
        raise ManifestError(f"project name {project!r} may only contain letters, digits, '_', '-' and '.'")
    connection = raw["connection"]
    if not isinstance(connection, dict):
        raise ManifestError("connection must be a mapping")
    _reject_secrets(connection)

    datasets = tuple(_parse_dataset(d) for d in _list(raw["datasets"], "datasets"))
    if not datasets:
        raise ManifestError("manifest must declare at least one dataset")
    names = [d.name for d in datasets]
    if len(set(names)) != len(names):
        raise ManifestError("dataset names must be unique")
    for ds in datasets:
        for target in ds.feeds:
            if target not in names:
                raise ManifestError(f"dataset {ds.name!r} feeds unknown dataset {target!r}")
            if target == ds.name:
                raise ManifestError(f"dataset {ds.name!r} cannot feed itself")

    thresholds = raw.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        raise ManifestError("thresholds must be a mapping")
    _no_unknown(thresholds, _THRESHOLD_KEYS, "thresholds")
    thresholds = {k: _number(v, f"thresholds.{k}") for k, v in thresholds.items()}

    manifest = Manifest(project, str(raw["connector"]), dict(connection), datasets, thresholds, path)
    for ds in datasets:        # lineage must be acyclic or the upstream walk never ends
        if ds.name in manifest.descendants(ds.name):
            raise ManifestError(f"lineage cycle through dataset {ds.name!r}")
    return manifest


def _parse_dataset(raw: Any) -> Dataset:
    if not isinstance(raw, dict):
        raise ManifestError("each dataset must be a mapping")
    _no_unknown(raw, _DATASET_KEYS, f"dataset {raw.get('name', '?')!r}")
    for required in ("name", "source", "roles"):
        if required not in raw:
            raise ManifestError(f"dataset {raw.get('name', '?')!r} is missing required field {required!r}")
    name = str(raw["name"])
    roles_raw = raw["roles"]
    if not isinstance(roles_raw, dict):
        raise ManifestError(f"roles of dataset {name!r} must be a mapping")
    _no_unknown(roles_raw, _ROLE_KEYS, f"roles of {name!r}")
    event_time = roles_raw.get("event_time")
    if event_time is not None and not isinstance(event_time, str):
        raise ManifestError(f"event_time of {name!r} must be a single column name")
    roles = Roles(
        event_time=event_time,
        key=_names(roles_raw.get("key"), f"{name}.roles.key"),
        measure=_names(roles_raw.get("measure"), f"{name}.roles.measure"),
        required=_names(roles_raw.get("required"), f"{name}.roles.required"),
    )

    expected_raw = raw.get("expected") or {}
    _no_unknown(expected_raw, _EXPECTED_KEYS, f"expected of {name!r}")
    ranges = {}
    for col, bounds in (expected_raw.get("value_range") or {}).items():
        if not (isinstance(bounds, (list, tuple)) and len(bounds) == 2):
            raise ManifestError(f"value_range for {name}.{col} must be [low, high]")
        lo, hi = _number(bounds[0], "value_range"), _number(bounds[1], "value_range")
        if lo > hi:
            raise ManifestError(f"value_range for {name}.{col} has low > high")
        ranges[str(col)] = (lo, hi)
    expected = Expected(
        max_age_hours=_opt_number(expected_raw.get("max_age_hours"), f"{name}.expected.max_age_hours"),
        max_null_rate=_opt_number(expected_raw.get("max_null_rate"), f"{name}.expected.max_null_rate"),
        value_range=ranges,
    )
    return Dataset(
        name=name,
        source=str(raw["source"]),
        roles=roles,
        business_visible=bool(raw.get("business_visible", False)),
        feeds=_names(raw.get("feeds"), f"{name}.feeds"),
        expected=expected,
    )


def _no_unknown(mapping: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ManifestError(f"unknown field(s) {', '.join(unknown)} in {where}; allowed: {', '.join(sorted(allowed))}")


def _list(value: Any, where: str) -> list:
    if not isinstance(value, list):
        raise ManifestError(f"{where} must be a list")
    return value


def _names(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    raise ManifestError(f"{where} must be a column name or a list of column names")


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{where} must be a number")
    return float(value)


def _opt_number(value: Any, where: str) -> float | None:
    return None if value is None else _number(value, where)


def _reject_secrets(connection: dict[str, Any]) -> None:
    """Secrets belong in environment variables; the manifest may only name the variable."""
    for key, value in connection.items():
        if key.endswith("_env"):
            if not isinstance(value, str) or not _ENV_VAR.match(value):
                raise ManifestError(f"connection.{key} must be the NAME of an environment variable")
        elif _SECRET_KEY.search(key):
            raise ManifestError(
                f"connection.{key} looks like a secret value; store it in an environment variable "
                f"and reference it as '{key}_env: <VARIABLE_NAME>'"
            )


# --- validation against the live database -------------------------------------

@dataclass(frozen=True)
class Issue:
    level: str          # error | info
    dataset: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.dataset}: {self.message}"


def validate_against(manifest: Manifest, connector: "Connector") -> list[Issue]:
    """Check every role column against the live schema, through the connector only."""
    issues: list[Issue] = []
    available = set(connector.list_datasets())
    for ds in manifest.datasets:
        if ds.source not in available:
            issues.append(Issue("error", ds.name, f"source {ds.source!r} does not exist in the database"))
            continue
        columns = {c.name: c for c in connector.describe(ds.source)}
        for role, cols in (
            ("event_time", [ds.roles.event_time] if ds.roles.event_time else []),
            ("key", ds.roles.key), ("measure", ds.roles.measure), ("required", ds.roles.required),
        ):
            for col in cols:
                if col not in columns:
                    issues.append(Issue("error", ds.name, f"{role} column {col!r} not found in {ds.source}"))
        et = columns.get(ds.roles.event_time or "")
        if et and et.kind != "temporal":
            issues.append(Issue("error", ds.name, f"event_time column {et.name!r} is {et.type}, not a date/time"))
        for col in ds.roles.measure:
            if col in columns and columns[col].kind != "numeric":
                issues.append(Issue("error", ds.name, f"measure column {col!r} is {columns[col].type}, not numeric"))
        for col in ds.expected.value_range:
            if col not in columns:
                issues.append(Issue("error", ds.name, f"value_range column {col!r} not found in {ds.source}"))
        if not ds.roles.key:
            issues.append(Issue("info", ds.name, "no key role: the duplicate check is skipped"))
        if not ds.roles.event_time:
            issues.append(Issue("info", ds.name, "no event_time role: freshness and volume checks are skipped"))
    return issues
