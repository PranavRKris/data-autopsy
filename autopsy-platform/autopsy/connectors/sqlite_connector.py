"""SQLite connector: the only file in the platform that contains SQLite SQL.

Temporal columns are stored as ISO text; every temporal comparison goes through date()/datetime() so
both 'YYYY-MM-DD HH:MM:SS' and 'YYYY-MM-DDTHH:MM:SS' spellings behave the same.
"""
from __future__ import annotations

import os
import sqlite3
import statistics
from pathlib import Path
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
from autopsy.core.models import (
    AggSpec,
    Bucket,
    ColumnInfo,
    ConnectionFailed,
    Filter,
    UnknownDataset,
    group_name,
)
from autopsy.core.registry import register

_OPS = {"=": "=", "!=": "<>", ">": ">", ">=": ">=", "<": "<", "<=": "<="}


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class _Median:
    def __init__(self):
        self.values: list[float] = []

    def step(self, value):
        if value is not None:
            self.values.append(value)

    def finalize(self):
        return statistics.median(self.values) if self.values else None


class SQLiteConnector:
    read_only = True

    def __init__(self, path: str):
        if not os.path.isfile(path):
            raise ConnectionFailed(f"database file not found: {path}")
        try:
            self._con = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
            self._con.create_aggregate("median", 1, _Median)
        except sqlite3.Error as exc:
            raise ConnectionFailed(f"cannot open {path} read-only: {exc}") from exc
        self._columns: dict[str, list[ColumnInfo]] = {}

    @classmethod
    def from_connection(cls, connection: dict[str, Any]) -> "SQLiteConnector":
        if "path_env" in connection:
            var = connection["path_env"]
            path = os.environ.get(var)
            if not path:
                raise ConnectionFailed(f"environment variable {var} is not set")
        elif "path" in connection:
            path = str(connection["path"])
        else:
            raise ConnectionFailed("sqlite connection needs 'path_env' (or 'path')")
        return cls(path)

    def close(self) -> None:
        self._con.close()

    def list_datasets(self) -> list[str]:
        rows = self._con.execute(
            "select name from sqlite_master where type in ('table', 'view') and name not like 'sqlite_%' order by name"
        ).fetchall()
        return [r[0] for r in rows]

    def describe(self, dataset: str) -> list[ColumnInfo]:
        if dataset not in self.list_datasets():
            raise UnknownDataset(f"unknown dataset {dataset!r}")
        if dataset not in self._columns:
            rows = self._con.execute(f"pragma table_info({_q(dataset)})").fetchall()
            self._columns[dataset] = [ColumnInfo(r[1], r[2], not r[3], kind_of(r[2])) for r in rows]
        return self._columns[dataset]

    def aggregate(self, dataset: str, spec: AggSpec) -> list[dict]:
        columns = {c.name: c for c in self.describe(dataset)}
        outputs = validate_spec(spec, columns, dataset)

        params: list[Any] = []
        parts: list[str] = []
        for group in spec.group_by:
            if isinstance(group, Bucket):
                fmt = "%Y-%m-%d" if group.unit == "day" else "%Y-%m-%dT%H:00:00"
                parts.append(f"strftime('{fmt}', {_q(group.column)}) as {_q(group.name)}")
            else:
                parts.append(f"{_q(group)} as {_q(group)}")
        agg_sql: dict[str, str] = {}
        for agg in spec.select:
            agg_sql[agg.alias] = self._agg_expr(agg.fn, agg.column, columns)
            parts.append(f"{agg_sql[agg.alias]} as {_q(agg.alias)}")

        sql = f"select {', '.join(parts)} from {_q(dataset)}"
        if spec.where:
            clauses = []
            for f in spec.where:
                col = columns[f.column]
                expr = self._temporal(col) if col.kind == "temporal" else _q(f.column)
                clauses.append(self._clause(expr, f, self._bind(col, f.value), params))
            sql += " where " + " and ".join(clauses)
        if spec.group_by:
            sql += " group by " + ", ".join(str(i + 1) for i in range(len(spec.group_by)))
        if spec.having:
            expr_of = {group_name(g): _q(g.column) if isinstance(g, Bucket) else _q(g) for g in spec.group_by}
            expr_of.update(agg_sql)
            sql += " having " + " and ".join(self._clause(expr_of[f.column], f, f.value, params) for f in spec.having)
        if spec.order_by:
            order = [f"{outputs.index(o.lstrip('-')) + 1}{' desc' if o.startswith('-') else ''}" for o in spec.order_by]
            sql += " order by " + ", ".join(order)
        sql += f" limit {int(spec.limit)}"

        agg_cols = {a.alias: columns.get(a.column) for a in spec.select}
        buckets = {group_name(g): g.unit for g in spec.group_by if isinstance(g, Bucket)}
        result = []
        for row in self._con.execute(sql, params).fetchall():
            out = {}
            for name, value in zip(outputs, row):
                col = agg_cols.get(name)
                if name in buckets:
                    value = bucket_label(value, buckets[name])
                elif col is not None and col.kind == "temporal" and value is not None:
                    value = self._temporal_value(col, value)
                out[name] = plain(value)
            result.append(out)
        return result

    def sample(self, dataset: str, n: int = 5) -> list[dict]:
        names = [c.name for c in self.describe(dataset)]
        cur = self._con.execute(f"select * from {_q(dataset)} limit {clamp_sample(n)}")
        return [{name: plain(v) for name, v in zip(names, row)} for row in cur.fetchall()]

    # --- SQL fragments ------------------------------------------------------

    @staticmethod
    def _temporal(col: ColumnInfo) -> str:
        fn = "date" if col.type.upper() == "DATE" else "datetime"
        return f"{fn}({_q(col.name)})"

    @staticmethod
    def _temporal_value(col: ColumnInfo, value: Any) -> str:
        ts = parse_temporal(value)
        return ts.date().isoformat() if col.type.upper() == "DATE" else ts.isoformat()

    @staticmethod
    def _bind(col: ColumnInfo, value: Any) -> Any:
        value = coerce_filter_value(col, value)
        if col.kind == "temporal" and value is not None:
            ts = parse_temporal(value)
            return ts.date().isoformat() if col.type.upper() == "DATE" else ts.strftime("%Y-%m-%d %H:%M:%S")
        return value

    def _agg_expr(self, fn: str, column: str, columns: dict[str, ColumnInfo]) -> str:
        if column == "*":
            return "count(*)"
        col = _q(column)
        ref = self._temporal(columns[column]) if columns[column].kind == "temporal" and fn in ("min", "max") else col
        return {
            "count": f"count({col})",
            "count_distinct": f"count(distinct {col})",
            "count_null": f"coalesce(sum(case when {col} is null then 1 else 0 end), 0)",
            "min": f"min({ref})",
            "max": f"max({ref})",
            "avg": f"avg({col})",
            "median": f"median({col})",
            "sum": f"sum({col})",
        }[fn]

    @staticmethod
    def _clause(expr: str, flt: Filter, value: Any, params: list[Any]) -> str:
        if flt.op == "is_null":
            return f"{expr} is null"
        if flt.op == "is_not_null":
            return f"{expr} is not null"
        params.append(value)
        return f"{expr} {_OPS[flt.op]} ?"


register("sqlite", SQLiteConnector.from_connection)
