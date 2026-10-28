"""The service's own SQLite database: connections, projects, runs, findings and incidents.

This is the platform's state, not a project's data: it lives under the state directory, never in a project database.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
create table if not exists connections (
  id text primary key, name text unique not null, connector text not null,
  config text not null, secret_envs text not null default '{}', created_at text not null,
  last_test_at text, last_test_ok integer, last_test_message text);
create table if not exists projects (
  name text primary key, connection_id text not null, spec text not null,
  created_at text not null, updated_at text not null,
  schedule text not null default '{}', next_run_at text, last_run_at text);
create table if not exists runs (
  id integer primary key autoincrement, project text not null, kind text not null, trigger text not null,
  status text not null, started_at text not null, finished_at text, duration_ms integer, summary text,
  counts text, root_dataset text, root_check text, severity text, report text);
create index if not exists runs_project on runs(project, id desc);
create table if not exists findings (
  id integer primary key autoincrement, run_id integer not null references runs(id) on delete cascade,
  project text not null, dataset text not null, tool text not null, status text not null, summary text,
  data text not null, at text not null);
create index if not exists findings_run on findings(run_id);
create index if not exists findings_latest on findings(project, dataset, tool, id desc);
create table if not exists incidents (
  id integer primary key autoincrement, project text not null, root_dataset text not null, root_check text not null,
  severity text not null, status text not null, acknowledged integer not null default 0,
  first_seen text not null, last_seen text not null, resolved_at text, occurrences integer not null default 1,
  run_id integer, summary text);
create index if not exists incidents_project on incidents(project, status);
"""

_JSON_COLUMNS = {"config", "secret_envs", "spec", "schedule", "counts", "data"}


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("pragma foreign_keys = on")
        con.execute("pragma journal_mode = wal")
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def rows(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self.connect() as con:
            return [_decode(r) for r in con.execute(sql, params).fetchall()]

    def row(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        found = self.rows(sql, params)
        return found[0] if found else None

    def run(self, sql: str, params: tuple | list = ()) -> int:
        """Execute one write; return the new row id."""
        with self.connect() as con:
            return con.execute(sql, params).lastrowid or 0

    def insert(self, table: str, values: dict[str, Any]) -> int:
        cols = list(values)
        return self.run(
            f"insert into {table} ({', '.join(cols)}) values ({', '.join('?' for _ in cols)})",
            [_encode(c, values[c]) for c in cols],
        )

    def update(self, table: str, key: str, key_value: Any, values: dict[str, Any]) -> None:
        sets = ", ".join(f"{c} = ?" for c in values)
        self.run(f"update {table} set {sets} where {key} = ?", [*[_encode(c, v) for c, v in values.items()], key_value])


def _encode(column: str, value: Any) -> Any:
    return json.dumps(value, default=str) if column in _JSON_COLUMNS and not isinstance(value, str) else value


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for column in _JSON_COLUMNS & set(out):
        if isinstance(out[column], str):
            out[column] = json.loads(out[column])
    return out
