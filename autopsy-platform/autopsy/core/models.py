"""Generic data types shared by every layer: datasets, query specs, findings, errors."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Output limits for anything Bob sees (the main context-window strategy).
MAX_ROWS = 50
MAX_BYTES = 2048

OK, WARN, FAIL, SKIPPED = "ok", "warn", "fail", "skipped"
STATUS_RANK = {OK: 0, SKIPPED: 0, WARN: 1, FAIL: 2}


class Severity(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"

    @property
    def rank(self) -> int:
        return int(self.value[-1])


# --- errors -----------------------------------------------------------------

class AutopsyError(Exception):
    """Typed error; `code` is what tools hand back to Bob."""

    code = "error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}


class UnknownDataset(AutopsyError):
    code = "unknown_dataset"


class UnknownColumn(AutopsyError):
    code = "unknown_column"


class InvalidSpec(AutopsyError):
    code = "invalid_spec"


class ConnectionFailed(AutopsyError):
    code = "connection_failed"


class ManifestError(AutopsyError):
    code = "invalid_manifest"


# --- schema description -----------------------------------------------------

@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str                 # the database's own type name
    nullable: bool = True
    kind: str = "other"       # normalized: numeric | temporal | text | boolean | other


# --- query spec -------------------------------------------------------------

AGG_FUNCTIONS = ("count", "count_distinct", "count_null", "min", "max", "avg", "median", "sum")
FILTER_OPS = ("=", "!=", ">", ">=", "<", "<=", "is_null", "is_not_null")
BUCKET_UNITS = ("day", "hour")
MAX_LIMIT = 1000


@dataclass(frozen=True)
class Agg:
    fn: str
    column: str              # a column name, or "*"
    alias: str


@dataclass(frozen=True)
class Bucket:
    """A time bucket of a column; its output name is `alias`, defaulting to the unit."""

    column: str
    unit: str
    alias: str | None = None

    @property
    def name(self) -> str:
        return self.alias or self.unit


@dataclass(frozen=True)
class Filter:
    """In `where`, `column` is a dataset column; in `having`, an output name."""

    column: str
    op: str
    value: Any = None


@dataclass
class AggSpec:
    select: list[Agg]
    group_by: list[str | Bucket] = field(default_factory=list)
    where: list[Filter] = field(default_factory=list)
    having: list[Filter] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)   # output name; prefix "-" for descending
    limit: int = MAX_LIMIT


def group_name(group: str | Bucket) -> str:
    return group.name if isinstance(group, Bucket) else group


# --- findings ---------------------------------------------------------------

@dataclass
class Finding:
    check: str
    dataset: str
    status: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    next_checks: list[str] = field(default_factory=list)

    def to_dict(self, max_rows: int = MAX_ROWS, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
        evidence, truncated = cap_payload(self.evidence, max_rows, max_bytes)
        return {
            "check": self.check,
            "dataset": self.dataset,
            "status": self.status,
            "summary": self.summary,
            "evidence": evidence,
            "next_checks": list(self.next_checks),
            "truncated": truncated,
        }


def cap_payload(payload: Any, max_rows: int = MAX_ROWS, max_bytes: int = MAX_BYTES) -> tuple[Any, bool]:
    """Trim lists to `max_rows`, then keep halving the biggest list until the JSON fits `max_bytes`."""
    truncated = False

    def trim(value: Any) -> Any:
        nonlocal truncated
        if isinstance(value, list):
            if len(value) > max_rows:
                truncated = True
            return [trim(v) for v in value[:max_rows]]
        if isinstance(value, dict):
            return {k: trim(v) for k, v in value.items()}
        return value

    def size(value: Any) -> int:
        return len(json.dumps(value, default=str))

    def lists(value: Any):
        if isinstance(value, list):
            yield value
            for v in value:
                yield from lists(v)
        elif isinstance(value, dict):
            for v in value.values():
                yield from lists(v)

    payload = trim(payload)
    while size(payload) > max_bytes:
        candidates = [lst for lst in lists(payload) if lst]
        if not candidates:
            break
        biggest = max(candidates, key=size)
        del biggest[len(biggest) // 2:]
        truncated = True
    return payload, truncated


def worst_status(statuses: list[str]) -> str:
    """Highest-ranked status; `skipped` only when nothing else was reported."""
    real = [s for s in statuses if s != SKIPPED]
    if not real:
        return SKIPPED if statuses else OK
    return max(real, key=lambda s: STATUS_RANK[s])
