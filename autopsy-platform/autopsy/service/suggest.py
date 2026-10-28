"""Propose manifest roles for a dataset from its live schema and one aggregate pass, so a person confirms instead of types.

Decisions come from column types, nullability and uniqueness; the only name hints are generic suffixes
(a key often ends in `_id`, an event time in `_at`). The result is a suggestion for a person to edit, never a rule.
"""
from __future__ import annotations

from typing import Any

from autopsy.core.models import Agg, AggSpec

MAX_COLUMNS = 60
MAX_DISTINCT_COLUMNS = 16
ID_HINTS = ("_id", "_key", "_uuid")
ID_NAMES = ("id", "key", "uuid")
TIME_HINTS = ("_at", "_ts", "_time", "_date", "_datetime")
TIME_NAMES = ("timestamp", "created", "updated", "date", "time", "datetime")


def _looks_like_id(name: str) -> bool:
    low = name.lower()
    return low in ID_NAMES or low.endswith(ID_HINTS)


def _looks_like_time(name: str) -> bool:
    low = name.lower()
    return low in TIME_NAMES or low.endswith(TIME_HINTS)


def suggest_roles(connector, source: str) -> dict[str, Any]:
    columns = connector.describe(source)[:MAX_COLUMNS]
    distinct_for = [c.name for c in columns if c.kind in ("numeric", "text") and _looks_like_id(c.name)]
    distinct_for += [c.name for c in columns if c.kind in ("numeric", "text") and c.name not in distinct_for]
    distinct_for = distinct_for[:MAX_DISTINCT_COLUMNS]

    select = [Agg("count", "*", "n")]
    select += [Agg("count_null", c.name, f"nu_{i}") for i, c in enumerate(columns)]
    select += [Agg("count_distinct", name, f"di_{i}") for i, name in enumerate(distinct_for)]
    (stats,) = connector.aggregate(source, AggSpec(select=select))
    rows = stats["n"]
    null_rate = {c.name: (stats[f"nu_{i}"] / rows if rows else 0.0) for i, c in enumerate(columns)}
    distinct = {name: stats[f"di_{i}"] for i, name in enumerate(distinct_for)}

    notes: dict[str, str] = {}

    temporal = [c for c in columns if c.kind == "temporal"]
    temporal.sort(key=lambda c: (not _looks_like_time(c.name), null_rate[c.name]))
    event_time = temporal[0].name if temporal else None
    if event_time:
        notes["event_time"] = (f"{len(temporal)} date/time columns; this one is most complete"
                               if len(temporal) > 1 else "the only date/time column")

    unique = [c.name for c in columns
              if c.kind in ("numeric", "text") and rows and distinct.get(c.name) == rows and null_rate[c.name] == 0]
    unique.sort(key=lambda name: not _looks_like_id(name))
    key = unique[:1]
    if key:
        notes["key"] = f"every one of {rows} rows has a different, non-null {key[0]}"

    taken = {event_time, *key}
    measure = [c.name for c in columns
               if c.kind == "numeric" and c.name not in taken and not _looks_like_id(c.name)][:3]
    taken |= set(measure)
    if measure:
        notes["measure"] = "numeric columns that are not identifiers"

    required = [c.name for c in columns
                if c.name not in taken and rows and null_rate[c.name] == 0 and c.kind in ("numeric", "text", "boolean")][:4]
    if required:
        notes["required"] = "never empty in the current data"

    return {"source": source, "rows": rows, "event_time": event_time, "key": key, "measure": measure,
            "required": required, "notes": notes}
