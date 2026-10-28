"""PostgreSQL connector: the only file in the platform that contains PostgreSQL SQL.

The session is opened read-only (`default_transaction_read_only`), with a statement timeout, and every
value is a bound parameter. Needs the optional driver: pip install "psycopg[binary]".
"""
from __future__ import annotations

from typing import Any

from autopsy.connectors.base import (
    bucket_label,
    clamp_sample,
    coerce_filter_value,
    config_value,
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
STATEMENT_TIMEOUT_MS = 30_000


def _q(identifier: str) -> str:
    # psycopg reads % as a placeholder marker in every query it is given parameters for
    return '"' + identifier.replace('"', '""').replace("%", "%%") + '"'


class PostgresConnector:
    read_only = True

    def __init__(self, connection=None, **conninfo: Any):
        """`connection` is an open psycopg connection (tests pass one); otherwise connect with `conninfo`."""
        if connection is None:
            try:
                import psycopg
            except ImportError as exc:
                raise ConnectionFailed('the postgres connector needs the driver: pip install "psycopg[binary]"') from exc
            try:
                connection = psycopg.connect(
                    **conninfo,
                    connect_timeout=10,
                    options=f"-c default_transaction_read_only=on -c statement_timeout={STATEMENT_TIMEOUT_MS}",
                    autocommit=True,
                )
            except psycopg.Error as exc:
                raise ConnectionFailed(f"cannot connect: {str(exc).strip().splitlines()[0]}") from exc
        self._con = connection
        self._tables: dict[str, tuple[str, str]] | None = None
        self._columns: dict[str, list[ColumnInfo]] = {}

    @classmethod
    def from_connection(cls, connection: dict[str, Any]) -> "PostgresConnector":
        dsn = config_value(connection, "dsn")
        if dsn:
            return cls(conninfo=str(dsn))
        info: dict[str, Any] = {
            "host": config_value(connection, "host", required=True),
            "dbname": config_value(connection, "database", required=True),
            "user": config_value(connection, "user", required=True),
        }
        for key, name in (("port", "port"), ("password", "password"), ("sslmode", "sslmode")):
            value = config_value(connection, key)
            if value is not None:
                info[name] = value
        return cls(**info)

    def close(self) -> None:
        self._con.close()

    def _fetch(self, sql: str, params: list[Any] | None = None) -> list[tuple]:
        with self._con.cursor() as cur:
            cur.execute(sql, params or [])
            return cur.fetchall()

    # --- discovery ----------------------------------------------------------

    def _table_index(self) -> dict[str, tuple[str, str]]:
        if self._tables is None:
            rows = self._fetch(
                "select table_schema, table_name from information_schema.tables "
                "where table_schema not in ('information_schema', 'pg_catalog') "
                "order by 1, 2"
            )
            self._tables = {name if schema == "public" else f"{schema}.{name}": (schema, name) for schema, name in rows}
        return self._tables

    def list_datasets(self) -> list[str]:
        return list(self._table_index())

    def _resolve(self, dataset: str) -> tuple[str, str]:
        index = self._table_index()
        if dataset in index:
            return index[dataset]
        if dataset.startswith("public.") and dataset[7:] in index:
            return index[dataset[7:]]
        raise UnknownDataset(f"unknown dataset {dataset!r}")

    def describe(self, dataset: str) -> list[ColumnInfo]:
        schema, table = self._resolve(dataset)
        key = f"{schema}.{table}"
        if key not in self._columns:
            rows = self._fetch(
                "select column_name, data_type, is_nullable from information_schema.columns "
                "where table_schema = %s and table_name = %s order by ordinal_position",
                [schema, table],
            )
            self._columns[key] = [ColumnInfo(n, t, nullable == "YES", kind_of(t)) for n, t, nullable in rows]
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

        rows = self._fetch(sql, params)
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
        rows = self._fetch(f"select * from {_q(schema)}.{_q(table)} limit {clamp_sample(n)}")
        return [{name: plain(v) for name, v in zip(names, row)} for row in rows]

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
            "median": f"percentile_cont(0.5) within group (order by {col})",
            "sum": f"sum({col})",
        }[fn]

    @staticmethod
    def _clause(expr: str, flt: Filter, value: Any, params: list[Any]) -> str:
        if flt.op == "is_null":
            return f"{expr} is null"
        if flt.op == "is_not_null":
            return f"{expr} is not null"
        params.append(value)
        return f"{expr} {_OPS[flt.op]} %s"


register("postgres", PostgresConnector.from_connection)
