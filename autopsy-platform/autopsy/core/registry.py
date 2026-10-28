"""Connector name -> connector factory. Supporting a new database means registering one name here."""
from __future__ import annotations

import importlib
from typing import Any, Callable

from autopsy.core.models import ManifestError

Factory = Callable[[dict[str, Any]], Any]

_REGISTRY: dict[str, Factory] = {}

# Built-in connectors are imported lazily, only when a manifest names them.
_BUILTIN = {
    "duckdb": "autopsy.connectors.duckdb_connector",
    "sqlite": "autopsy.connectors.sqlite_connector",
    "files": "autopsy.connectors.files_connector",
    "postgres": "autopsy.connectors.postgres_connector",
}


def register(name: str, factory: Factory) -> None:
    _REGISTRY[name] = factory


def create_connector(name: str, connection: dict[str, Any]):
    if name not in _REGISTRY and name in _BUILTIN:
        importlib.import_module(_BUILTIN[name])   # the module registers itself
    try:
        factory = _REGISTRY[name]
    except KeyError:
        known = sorted(set(_REGISTRY) | set(_BUILTIN))
        raise ManifestError(f"unknown connector {name!r}; registered: {', '.join(known)}") from None
    return factory(connection)
