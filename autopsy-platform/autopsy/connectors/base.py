"""The Connector interface, plus the spec validation and value normalization every connector shares.

Nothing here builds SQL; SQL lives only in the per-database connector files.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from autopsy.core.models import (
    AGG_FUNCTIONS,
    BUCKET_UNITS,
    FILTER_OPS,
    MAX_LIMIT,
    AggSpec,
    Bucket,
    ColumnInfo,
    ConnectionFailed,
    Filter,
    InvalidSpec,
    UnknownColumn,
    group_name,
)

SAMPLE_CAP = 20
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@runtime_checkable
class Connector(Protocol):
    read_only: bool

    def list_datasets(self) -> list[str]: ...
    def describe(self, dataset: str) -> list[ColumnInfo]: ...
    def aggregate(self, dataset: str, spec: AggSpec) -> list[dict]: ...
    def sample(self, dataset: str, n: int = 5) -> list[dict]: ...


def config_value(connection: dict[str, Any], key: str, default: Any = None, required: bool = False) -> Any:
    """A connection setting given directly (`key`) or by naming an environment variable (`key_env`)."""
    if f"{key}_env" in connection:
        var = connection[f"{key}_env"]
        value = os.environ.get(var)
        if not value:
            raise ConnectionFailed(f"environment variable {var} is not set")
        return value
    if key in connection and connection[key] not in (None, ""):
        return connection[key]
    if required:
        raise ConnectionFailed(f"connection needs {key!r} (or '{key}_env')")
    return default


def kind_of(type_name: str) -> str:
    """Normalize a database type name into numeric | temporal | text | boolean | other."""
    t = type_name.upper()
    if t.startswith(("TIMESTAMP", "DATETIME", "DATE", "TIME")):
        return "temporal"
    if t.startswith(("BOOL",)):
        return "boolean"
    if any(t.startswith(p) for p in ("TINYINT", "SMALLINT", "INT", "BIGINT", "HUGEINT", "UTINYINT",
                                     "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE",
                                     "REAL", "DECIMAL", "NUMERIC", "NUMBER")):
        return "numeric"
    if t.startswith(("VARCHAR", "TEXT", "STRING", "CHAR", "CLOB")):
        return "text"
    return "other"


def plain(value: Any) -> Any:
    """Convert driver-specific values into plain Python (str / int / float / bool / None)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    return str(value)


def parse_temporal(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise InvalidSpec(f"not a date/time value: {value!r}") from exc


def bucket_label(value: Any, unit: str) -> str | None:
    """Label of the time bucket containing `value`: YYYY-MM-DD for day, YYYY-MM-DDTHH:00:00 for hour."""
    if value is None:
        return None
    ts = parse_temporal(value)
    if unit == "day":
        return ts.date().isoformat()
    return ts.replace(minute=0, second=0, microsecond=0).isoformat()


def coerce_filter_value(column: ColumnInfo, value: Any) -> Any:
    """Bind temporal filter values as datetimes so no database compares a date column with text."""
    if column.kind == "temporal" and value is not None and not isinstance(value, (datetime, date)):
        return parse_temporal(value)
    return value


def find_column(columns: dict[str, ColumnInfo], name: str, dataset: str) -> ColumnInfo:
    try:
        return columns[name]
    except KeyError:
        raise UnknownColumn(f"unknown column {name!r} in dataset {dataset!r}") from None


def validate_spec(spec: AggSpec, columns: dict[str, ColumnInfo], dataset: str) -> list[str]:
    """Check a spec against the dataset's columns; return the output column names in order."""
    if not spec.select:
        raise InvalidSpec("select must contain at least one aggregate")
    if not 1 <= spec.limit <= MAX_LIMIT:
        raise InvalidSpec(f"limit must be between 1 and {MAX_LIMIT}")

    outputs: list[str] = []
    for group in spec.group_by:
        if isinstance(group, Bucket):
            if group.unit not in BUCKET_UNITS:
                raise InvalidSpec(f"unknown bucket unit {group.unit!r}")
            col = find_column(columns, group.column, dataset)
            if col.kind != "temporal":
                raise InvalidSpec(f"cannot bucket non-temporal column {group.column!r}")
        else:
            find_column(columns, group, dataset)
        outputs.append(group_name(group))

    for agg in spec.select:
        if agg.fn not in AGG_FUNCTIONS:
            raise InvalidSpec(f"unknown aggregate {agg.fn!r}")
        if not _NAME.match(agg.alias):
            raise InvalidSpec(f"alias {agg.alias!r} must be a plain identifier")
        if agg.column == "*":
            if agg.fn != "count":
                raise InvalidSpec(f"{agg.fn} needs a column, not '*'")
        else:
            col = find_column(columns, agg.column, dataset)
            if agg.fn in ("avg", "sum", "median") and col.kind != "numeric":
                raise InvalidSpec(f"{agg.fn} needs a numeric column; {agg.column!r} is {col.type}")
        outputs.append(agg.alias)

    if len(set(outputs)) != len(outputs):
        raise InvalidSpec("output names (group columns and aliases) must be unique")

    for flt in spec.where:
        _validate_filter(flt)
        find_column(columns, flt.column, dataset)
    for flt in spec.having:
        _validate_filter(flt)
        if flt.column not in outputs:
            raise InvalidSpec(f"having refers to unknown output {flt.column!r}")
    for item in spec.order_by:
        if item.lstrip("-") not in outputs:
            raise InvalidSpec(f"order_by refers to unknown output {item!r}")
    return outputs


def _validate_filter(flt: Filter) -> None:
    if flt.op not in FILTER_OPS:
        raise InvalidSpec(f"unknown filter operator {flt.op!r}")
    if flt.op in ("is_null", "is_not_null"):
        if flt.value is not None:
            raise InvalidSpec(f"{flt.op} takes no value")
    elif flt.value is None:
        raise InvalidSpec(f"operator {flt.op!r} needs a value (use is_null for nulls)")


def clamp_sample(n: int) -> int:
    return max(1, min(int(n), SAMPLE_CAP))
