"""What a connector needs from a person: the fields of its connection form, without importing its driver.

A field of type `secret` is never stored in a manifest; the service keeps the value and the manifest names an
environment variable (`<key>_env`). A field with `env_ok` may instead be given as the name of an environment variable.
"""
from __future__ import annotations

import importlib.util
from typing import Any

SPECS: dict[str, dict[str, Any]] = {
    "duckdb": {
        "label": "DuckDB",
        "description": "A DuckDB database file, opened read-only.",
        "verified": "Passes the connector contract tests.",
        "needs": None,
        "fields": [
            {"key": "path", "label": "Database file", "type": "path", "required": True, "env_ok": True,
             "placeholder": "C:/data/warehouse.duckdb", "help": "Path on the machine running the service."},
        ],
    },
    "sqlite": {
        "label": "SQLite",
        "description": "A SQLite database file, opened read-only.",
        "verified": "Passes the connector contract tests.",
        "needs": None,
        "fields": [
            {"key": "path", "label": "Database file", "type": "path", "required": True, "env_ok": True,
             "placeholder": "C:/data/app.sqlite", "help": "Path on the machine running the service."},
        ],
    },
    "files": {
        "label": "CSV / Parquet folder",
        "description": "A folder of .csv, .tsv and .parquet files. Each file is one dataset, named by its file name.",
        "verified": "Passes the connector contract tests.",
        "needs": None,
        "fields": [
            {"key": "path", "label": "Folder", "type": "path", "required": True, "env_ok": True,
             "placeholder": "C:/data/exports", "help": "Files are only read, never changed."},
        ],
    },
    "postgres": {
        "label": "PostgreSQL",
        "description": "A PostgreSQL database. The session is read-only with a 30 second statement timeout.",
        "verified": "Not run against a live server in development: contract tests run only when "
                    "AUTOPSY_TEST_POSTGRES_DSN is set.",
        "needs": "psycopg",
        "install_hint": 'pip install "psycopg[binary]"',
        "fields": [
            {"key": "host", "label": "Host", "type": "text", "required": True, "env_ok": True,
             "placeholder": "db.internal"},
            {"key": "port", "label": "Port", "type": "number", "required": False, "default": 5432},
            {"key": "database", "label": "Database", "type": "text", "required": True, "env_ok": True},
            {"key": "user", "label": "User", "type": "text", "required": True, "env_ok": True,
             "help": "Use an account that can only SELECT."},
            {"key": "password", "label": "Password", "type": "secret", "required": False},
            {"key": "sslmode", "label": "SSL mode", "type": "select", "required": False, "default": "prefer",
             "options": ["disable", "prefer", "require", "verify-full"]},
        ],
    },
}


def connector_specs() -> list[dict[str, Any]]:
    out = []
    for name, spec in SPECS.items():
        needs = spec["needs"]
        available = needs is None or importlib.util.find_spec(needs) is not None
        out.append({"name": name, **{k: v for k, v in spec.items() if k != "needs"}, "available": available})
    return out


def secret_fields(connector: str) -> list[str]:
    return [f["key"] for f in SPECS.get(connector, {}).get("fields", []) if f["type"] == "secret"]
