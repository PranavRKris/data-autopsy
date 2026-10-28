"""DuckDB connector: the only file in the platform that contains DuckDB SQL."""
from __future__ import annotations

import os
import time
from typing import Any

import duckdb

from autopsy.connectors.base import (
    bucket_label,
    clamp_sample,
    coerce_filter_value,
    kind_of,
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


LOCK_WAIT_SECONDS = 10.0
_BUSY = ("lock", "being used by another process", "cannot access the file")   # Linux and Windows wording


def _is_busy(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _BUSY)


def _open_read_only(path: str):
    """Open read-only, waiting briefly if a pipeline holds the write lock (DuckDB allows one writer process)."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            return duckdb.connect(path, read_only=True)
        except duckdb.IOException as exc:
            if _is_busy(exc) and time.monotonic() < deadline:
                time.sleep(0.25)
                continue
            raise ConnectionFailed(f"cannot open {path} read-only: {exc}") from exc
        except duckdb.Error as exc:
            raise ConnectionFailed(f"cannot open {path} read-only: {exc}") from exc


class DuckDBConnector:
    read_only = True

    def __init__(self, path: str):
        if not os.path.isfile(path):
            raise ConnectionFailed(f"database file not found: {path}")
        self._con = _open_read_only(path)
        self._tables: dict[str, tuple[str, str]] | None = None
        self._columns: dict[str, list[ColumnInfo]] = {}

    @classmethod
    def from_connection(cls, connection: dict[str, Any]) -> "DuckDBConnector":
        if "path_env" in connection:
            var = connection["path_env"]
            path = os.environ.get(var)
            if not path:
                raise ConnectionFailed(f"environment variable {var} is not set")
        elif "path" in connection:
            path = str(connection["path"])
        else:
            raise ConnectionFailed("duckdb connection needs 'path_env' (or 'path')")
        return cls(path)

    def close(self) -> None:
        self._con.close()

    # --- discovery ----------------------------------------------------------

    def _table_index(self) -> dict[str, tuple[str, str]]:
        if self._tables is None:
            rows = self._con.execute(
                "select table_schema, table_name from information_schema.tables "
                "where table_schema not in ('information_schema', 'pg_catalog') "
                "order by 1, 2"
            ).fetchall()
            self._tables = {}
            for schema, name in rows:
                self._tables[name if schema == "main" else f"{schema}.{name}"] = (schema, name)
        return self._tables

    def list_datasets(self) -> list[str]:
        return list(self._table_index())

    def _resolve(self, dataset: str) -> tuple[str, str]:
        index = self._table_index()
        if dataset in index:
            return index[dataset]
        if dataset.startswith("main.") and dataset[5:] in index:
            return index[dataset[5:]]
        raise UnknownDataset(f"unknown dataset {dataset!r}")

    def describe(self, dataset: str) -> list[ColumnInfo]:
        schema, table = self._resolve(dataset)
        key = f"{schema}.{table}"
        if key not in self._columns:
            rows = self._con.execute(
                "select column_name, data_type, is_nullable from information_schema.columns "
                "where table_schema = ? and table_name = ? order by ordinal_position",
                [schema, table],
            ).fetchall()
            self._columns[key] = [
                ColumnInfo(name, dtype, nullable == "YES", kind_of(dtype)) for name, dtype, nullable in rows
            ]
        return self._columns[key]

    # --- queries ------------------------------------------------------------

    def aggregate(self, dataset: str, spec: AggSpec) -> list[dict]:
        schema, table = self._resolve(dataset)
        columns = {c.name: c for c in self.describe(dataset)}
        outputs = validate_spec(spec, columns, dataset)

        params: list[Any] = []
        parts: list[str] = []
        for group in spec.group_by:
            if isinstance(group, Bucket):
                parts.append(f"date_trunc('{group.unit}', {_q(group.column)}) as {_q(group.name)}")
            else:
                parts.append(f"{_q(group)} as {_q(group)}")
        agg_sql: dict[str, str] = {}
        for agg in spec.select:
            agg_sql[agg.alias] = self._agg_expr(agg.fn, agg.column)
            parts.append(f"{agg_sql[agg.alias]} as {_q(agg.alias)}")

        sql = f"select {', '.join(parts)} from {_q(schema)}.{_q(table)}"
        if spec.where:
            clauses = [self._clause(_q(f.column), f, coerce_filter_value(columns[f.column], f.value), params)
                       for f in spec.where]
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

        rows = self._con.execute(sql, params).fetchall()
        buckets = {group_name(g): g.unit for g in spec.group_by if isinstance(g, Bucket)}
        result = []
        for row in rows:
            out = {}
            for name, value in zip(outputs, row):
                out[name] = bucket_label(value, buckets[name]) if name in buckets else plain(value)
            result.append(out)
        return result

    def sample(self, dataset: str, n: int = 5) -> list[dict]:
        schema, table = self._resolve(dataset)
        names = [c.name for c in self.describe(dataset)]
        cur = self._con.execute(f"select * from {_q(schema)}.{_q(table)} limit {clamp_sample(n)}")
        return [{name: plain(v) for name, v in zip(names, row)} for row in cur.fetchall()]

    # --- SQL fragments ------------------------------------------------------

    @staticmethod
    def _agg_expr(fn: str, column: str) -> str:
        if column == "*":
            return "count(*)"
        col = _q(column)
        return {
            "count": f"count({col})",
            "count_distinct": f"count(distinct {col})",
            "count_null": f"count(*) filter (where {col} is null)",
            "min": f"min({col})",
            "max": f"max({col})",
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


register("duckdb", DuckDBConnector.from_connection)
