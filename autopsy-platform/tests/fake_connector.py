"""In-memory connector: proves every check runs with no real database.

It interprets AggSpec on plain Python rows and shares spec validation with the real connectors.
"""
from __future__ import annotations

import copy
import statistics
from datetime import date, datetime
from typing import Any

from autopsy.connectors.base import (
    bucket_label,
    clamp_sample,
    coerce_filter_value,
    kind_of,
    parse_temporal,
    plain,
    validate_spec,
)
from autopsy.core.models import AggSpec, Bucket, ColumnInfo, Filter, UnknownDataset, group_name


class FakeConnector:
    read_only = True

    def __init__(self, tables: dict[str, tuple[dict[str, str], list[dict]]]):
        """tables: dataset -> ({column: type name}, rows)."""
        self._types = {name: types for name, (types, _) in tables.items()}
        self._rows = {name: [dict(r) for r in rows] for name, (_, rows) in tables.items()}
        self._pristine = copy.deepcopy(self._rows)

    def unchanged(self) -> bool:
        return self._rows == self._pristine

    def list_datasets(self) -> list[str]:
        return list(self._rows)

    def _check(self, dataset: str) -> None:
        if dataset not in self._rows:
            raise UnknownDataset(f"unknown dataset {dataset!r}")

    def describe(self, dataset: str) -> list[ColumnInfo]:
        self._check(dataset)
        return [ColumnInfo(n, t, True, kind_of(t)) for n, t in self._types[dataset].items()]

    def sample(self, dataset: str, n: int = 5) -> list[dict]:
        self._check(dataset)
        return [{k: plain(v) for k, v in row.items()} for row in self._rows[dataset][:clamp_sample(n)]]

    def aggregate(self, dataset: str, spec: AggSpec) -> list[dict]:
        self._check(dataset)
        columns = {c.name: c for c in self.describe(dataset)}
        outputs = validate_spec(spec, columns, dataset)

        rows = [r for r in self._rows[dataset] if all(self._match(r, f, columns) for f in spec.where)]

        groups: dict[tuple, list[dict]] = {}
        for row in rows:
            key = tuple(self._group_value(row, g) for g in spec.group_by)
            groups.setdefault(key, []).append(row)
        if not spec.group_by:
            groups = {(): rows}

        result = []
        for key, members in groups.items():
            out = {group_name(g): v for g, v in zip(spec.group_by, key)}
            for agg in spec.select:
                out[agg.alias] = self._agg(agg.fn, agg.column, members)
            if all(self._compare(out[f.column], f.op, f.value) for f in spec.having):
                result.append(out)

        for item in reversed(spec.order_by):
            name = item.lstrip("-")
            result.sort(key=lambda r: (r[name] is None, r[name]), reverse=item.startswith("-"))
        return [{k: plain(out[k]) for k in outputs} for out in result[: spec.limit]]

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _group_value(row: dict, group: str | Bucket) -> Any:
        if isinstance(group, Bucket):
            return bucket_label(row.get(group.column), group.unit)
        return row.get(group)

    @staticmethod
    def _agg(fn: str, column: str, rows: list[dict]) -> Any:
        if column == "*":
            return len(rows)
        values = [r.get(column) for r in rows]
        present = [v for v in values if v is not None]
        if fn == "count":
            return len(present)
        if fn == "count_distinct":
            return len(set(present))
        if fn == "count_null":
            return len(values) - len(present)
        if not present:
            return None
        return {
            "min": min, "max": max, "sum": sum,
            "avg": lambda v: sum(v) / len(v), "median": statistics.median,
        }[fn](present)

    def _match(self, row: dict, flt: Filter, columns: dict[str, ColumnInfo]) -> bool:
        value = coerce_filter_value(columns[flt.column], flt.value)
        actual = row.get(flt.column)
        if isinstance(actual, (date, datetime)) and isinstance(value, (date, datetime)):
            actual, value = parse_temporal(actual), parse_temporal(value)
        return self._compare(actual, flt.op, value)

    @staticmethod
    def _compare(actual: Any, op: str, value: Any) -> bool:
        if op == "is_null":
            return actual is None
        if op == "is_not_null":
            return actual is not None
        if actual is None:
            return False
        return {
            "=": actual == value, "!=": actual != value, ">": actual > value,
            ">=": actual >= value, "<": actual < value, "<=": actual <= value,
        }[op]
