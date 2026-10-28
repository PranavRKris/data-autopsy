"""Export the Acme Shop DuckDB database to SQLite, for the swap-the-database demo.

usage: export_sqlite.py --db acme.duckdb --out acme.sqlite

SQLite has no schemas, so a table such as raw.orders is created under that literal quoted name,
which lets the manifest's `source` values stay exactly as they are. Imports nothing from the platform.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import date, datetime
from pathlib import Path

import duckdb


def q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def export(db: str, out: str) -> int:
    Path(out).unlink(missing_ok=True)
    src = duckdb.connect(db, read_only=True)
    dst = sqlite3.connect(out)
    tables = src.execute(
        "select table_schema, table_name from information_schema.tables "
        "where table_schema not in ('information_schema', 'pg_catalog') order by 1, 2").fetchall()
    for schema, table in tables:
        columns = src.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_schema = ? and table_name = ? order by ordinal_position", [schema, table]).fetchall()
        name = f"{schema}.{table}"
        dst.execute(f"create table {q(name)} ({', '.join(f'{q(c)} {t}' for c, t in columns)})")
        rows = [
            tuple(v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat() if isinstance(v, date) else v
                  for v in row)
            for row in src.execute(f"select * from {q(schema)}.{q(table)}").fetchall()
        ]
        dst.executemany(f"insert into {q(name)} values ({', '.join('?' for _ in columns)})", rows)
    dst.commit()
    dst.close()
    src.close()
    return len(tables)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(f"exported {export(args.db, args.out)} tables to {args.out}")


if __name__ == "__main__":
    main()
