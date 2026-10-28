"""The PostgreSQL connector without a server: pins the SQL it builds and the session it asks for.

This does NOT prove PostgreSQL accepts the SQL. The real contract tests in test_connector_contract.py run against a
live server only when AUTOPSY_TEST_POSTGRES_DSN is set.
"""
from __future__ import annotations

import sys
from datetime import datetime

import pytest

from autopsy.connectors.postgres_connector import PostgresConnector
from autopsy.core.models import Agg, AggSpec, Bucket, ConnectionFailed, Filter, UnknownDataset


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.log.append((sql, list(params or [])))
        self.sql = sql

    def fetchall(self):
        if "information_schema.tables" in self.sql:
            return [("public", "items"), ("etl", "stage")]
        if "information_schema.columns" in self.sql:
            return [("id", "integer", "NO"), ("created_at", "timestamp without time zone", "YES"),
                    ("price", "double precision", "YES"), ("label", "character varying", "YES")]
        return self.conn.rows


class FakeConnection:
    def __init__(self, rows=()):
        self.log, self.rows, self.closed = [], list(rows), False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def test_names_and_kinds_come_from_information_schema():
    conn = PostgresConnector(FakeConnection())
    assert conn.list_datasets() == ["items", "etl.stage"]
    assert [c.kind for c in conn.describe("items")] == ["numeric", "temporal", "numeric", "text"]
    assert conn.describe("public.items") == conn.describe("items")
    with pytest.raises(UnknownDataset):
        conn.describe("missing")


def test_the_sql_is_built_from_the_spec_with_bound_values():
    fake = FakeConnection(rows=[(datetime(2026, 10, 3), 2, 25.0)])
    conn = PostgresConnector(fake)
    got = conn.aggregate("items", AggSpec(
        select=[Agg("count", "*", "n"), Agg("median", "price", "mid")],
        group_by=[Bucket("created_at", "day")],
        where=[Filter("created_at", ">=", "2026-10-02"), Filter("label", "is_null")],
        having=[Filter("n", ">", 1)],
        order_by=["-day"],
        limit=5,
    ))
    sql, params = fake.log[-1]
    assert sql == (
        'select date_trunc(\'day\', "created_at") as "day", count(*) as "n", '
        'percentile_cont(0.5) within group (order by "price") as "mid" from "public"."items" '
        'where "created_at" >= %s and "label" is null group by 1 having count(*) > %s order by 1 desc limit 5'
    )
    assert params == [datetime(2026, 10, 2), 1]
    assert got == [{"day": "2026-10-03", "n": 2, "mid": 25.0}]


def test_a_value_is_never_pasted_into_the_sql():
    fake = FakeConnection(rows=[(0,)])
    PostgresConnector(fake).aggregate("items", AggSpec(select=[Agg("count", "*", "n")],
                                                       where=[Filter("label", "=", "x'; drop table items; --")]))
    sql, params = fake.log[-1]
    assert "drop table" not in sql and params == ["x'; drop table items; --"]


def test_non_default_schema_and_percent_signs_in_identifiers():
    fake = FakeConnection(rows=[(1,)])
    PostgresConnector(fake).aggregate("etl.stage", AggSpec(select=[Agg("count", "*", "n")]))
    assert 'from "etl"."stage"' in fake.log[-1][0]


def test_the_session_is_read_only_and_the_password_comes_from_the_environment(monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    seen = {}

    def fake_connect(**kwargs):
        seen.update(kwargs)
        return FakeConnection()

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    monkeypatch.setenv("PG_TEST_PASSWORD", "from-the-environment")
    PostgresConnector.from_connection({"host": "db.internal", "port": 5433, "database": "d", "user": "u",
                                       "password_env": "PG_TEST_PASSWORD", "sslmode": "require"})
    assert seen["password"] == "from-the-environment"
    assert seen["host"] == "db.internal" and seen["dbname"] == "d" and seen["port"] == 5433
    assert "default_transaction_read_only=on" in seen["options"]
    assert "statement_timeout" in seen["options"]


def test_a_missing_driver_says_how_to_install_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)
    with pytest.raises(ConnectionFailed, match="psycopg"):
        PostgresConnector(host="h", dbname="d", user="u")


def test_a_missing_environment_variable_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("PG_TEST_PASSWORD", raising=False)
    with pytest.raises(ConnectionFailed, match="PG_TEST_PASSWORD"):
        PostgresConnector.from_connection({"host": "h", "database": "d", "user": "u", "password_env": "PG_TEST_PASSWORD"})
