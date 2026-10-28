"""Files connector: a folder of CSV, TSV or Parquet files, each file one dataset (named by its file stem).

The files are loaded into an in-memory DuckDB, and then every kind of file and network access is switched off for
that connection, so nothing it runs can write to disk. The query code is the DuckDB connector's; this file only loads.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from autopsy.connectors.base import config_value
from autopsy.connectors.duckdb_connector import DuckDBConnector, _q
from autopsy.core.models import ConnectionFailed
from autopsy.core.registry import register

_READERS = {".csv": "read_csv_auto", ".tsv": "read_csv_auto", ".parquet": "read_parquet"}
MAX_BYTES = 1_000_000_000      # beyond this a folder belongs in a database, not in memory


class FilesConnector(DuckDBConnector):
    read_only = True

    def __init__(self, folder: str):
        root = Path(folder)
        if not root.is_dir():
            raise ConnectionFailed(f"folder not found: {folder}")
        files = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in _READERS)
        if not files:
            raise ConnectionFailed(f"no .csv, .tsv or .parquet files in {folder}")
        stems = [p.stem for p in files]
        if len(set(stems)) != len(stems):
            raise ConnectionFailed(f"two files in {folder} share the name {next(s for s in stems if stems.count(s) > 1)!r}")
        if sum(p.stat().st_size for p in files) > MAX_BYTES:
            raise ConnectionFailed(f"{folder} holds more than {MAX_BYTES // 1_000_000} MB; load it into a database instead")
        self._con = duckdb.connect(":memory:")
        try:
            for path in files:
                self._con.execute(f"create table {_q(path.stem)} as select * from {_READERS[path.suffix.lower()]}(?)",
                                  [str(path)])
            self._con.execute("set enable_external_access = false")     # from here on: no file or network access
            self._con.execute("set lock_configuration = true")
        except duckdb.Error as exc:
            self._con.close()
            raise ConnectionFailed(f"cannot read {path.name}: {exc}") from exc
        self._tables = None
        self._columns = {}

    @classmethod
    def from_connection(cls, connection: dict[str, Any]) -> "FilesConnector":
        return cls(str(config_value(connection, "path", required=True)))


register("files", FilesConnector.from_connection)
