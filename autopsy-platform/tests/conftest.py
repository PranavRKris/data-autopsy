"""Shared fixtures: the tiny known dataset every connector must handle identically."""
from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from fake_connector import FakeConnector

ITEM_TYPES = {"id": "INTEGER", "name": "VARCHAR", "price": "DOUBLE", "created_at": "TIMESTAMP"}
ITEM_ROWS = [
    {"id": 1, "name": "a", "price": 10.0, "created_at": datetime(2026, 10, 1, 8, 0)},
    {"id": 2, "name": "b", "price": 20.0, "created_at": datetime(2026, 10, 1, 9, 30)},
    {"id": 3, "name": "c", "price": 30.0, "created_at": datetime(2026, 10, 2, 10, 0)},
    {"id": 4, "name": None, "price": 40.0, "created_at": datetime(2026, 10, 3, 11, 0)},
    {"id": 5, "name": "e", "price": None, "created_at": datetime(2026, 10, 3, 23, 59)},
]


class Case:
    """One connector under test, with a way to try a write and to see whether the data changed."""

    def __init__(self, connector, write_probe, unchanged, cleanup=None):
        self.connector = connector
        self.write_probe = write_probe      # raises if the connection is read-only
        self.unchanged = unchanged          # True while the underlying data is untouched
        self.cleanup = cleanup


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duckdb_case(tmp_path: Path) -> Case:
    from autopsy.connectors.duckdb_connector import DuckDBConnector

    path = tmp_path / "items.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create table items (id integer, name varchar, price double, created_at timestamp)")
    con.executemany("insert into items values (?, ?, ?, ?)", [tuple(r.values()) for r in ITEM_ROWS])
    con.close()
    before = _digest(path)
    conn = DuckDBConnector(str(path))
    return Case(conn, lambda: conn._con.execute("create table intruder (i integer)"), lambda: _digest(path) == before)


def _sqlite_case(tmp_path: Path) -> Case:
    from autopsy.connectors.sqlite_connector import SQLiteConnector

    path = tmp_path / "items.sqlite"
    con = sqlite3.connect(path)
    con.execute("create table items (id integer, name text, price real, created_at timestamp)")
    con.executemany(
        "insert into items values (?, ?, ?, ?)",
        [(r["id"], r["name"], r["price"], r["created_at"].isoformat(sep=" ")) for r in ITEM_ROWS],
    )
    con.commit()
    con.close()
    before = _digest(path)
    conn = SQLiteConnector(str(path))
    return Case(conn, lambda: conn._con.execute("create table intruder (i integer)"), lambda: _digest(path) == before)


def _fake_case(tmp_path: Path) -> Case:
    conn = FakeConnector({"items": (ITEM_TYPES, ITEM_ROWS)})

    def write_probe():
        raise PermissionError("the fake connector exposes no write path")

    return Case(conn, write_probe, conn.unchanged)


def _files_case(tmp_path: Path) -> Case:
    from autopsy.connectors.files_connector import FilesConnector

    folder = tmp_path / "exports"
    folder.mkdir()
    path = folder / "items.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(list(ITEM_TYPES))
        for r in ITEM_ROWS:
            writer.writerow(["" if v is None else v.isoformat(sep=" ") if isinstance(v, datetime) else v for v in r.values()])
    before = _digest(path)
    conn = FilesConnector(str(folder))
    return Case(conn, lambda: conn._con.execute(f"copy (select 1) to '{path.as_posix()}'"), lambda: _digest(path) == before)


def _postgres_case(tmp_path: Path) -> Case:
    """Runs only when AUTOPSY_TEST_POSTGRES_DSN points at a scratch database; it creates and drops public.items."""
    import psycopg

    from autopsy.connectors.postgres_connector import PostgresConnector

    dsn = os.environ["AUTOPSY_TEST_POSTGRES_DSN"]
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute("drop table if exists public.items")
        admin.execute("create table public.items (id integer, name varchar, price double precision, created_at timestamp)")
        for r in ITEM_ROWS:
            admin.execute("insert into public.items values (%s, %s, %s, %s)", list(r.values()))
    conn = PostgresConnector.from_connection({"dsn": dsn})

    def unchanged() -> bool:
        with psycopg.connect(dsn, autocommit=True) as check:
            return check.execute("select count(*) from public.items").fetchone()[0] == 5 and                 check.execute("select to_regclass('public.intruder')").fetchone()[0] is None

    def cleanup() -> None:
        conn.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute("drop table if exists public.items")

    return Case(conn, lambda: conn._con.execute("create table public.intruder (i integer)"), unchanged, cleanup)


CASES = {"fake": _fake_case, "duckdb": _duckdb_case, "sqlite": _sqlite_case, "files": _files_case}
if os.environ.get("AUTOPSY_TEST_POSTGRES_DSN"):
    CASES["postgres"] = _postgres_case


@pytest.fixture(params=sorted(CASES))
def case(request, tmp_path) -> Case:
    made = CASES[request.param](tmp_path)
    yield made
    if made.cleanup:
        made.cleanup()
