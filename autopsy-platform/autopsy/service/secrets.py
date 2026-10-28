"""Server-side secret store: values the manifest must never contain (passwords, tokens).

A manifest refers to a secret only by the NAME of an environment variable; this store keeps the value and
exports it into the service's own environment. The values are stored as plain text in one file under the state
directory, and the API never returns them. Use a real vault for anything beyond a single-user machine.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class SecretStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    def set(self, name: str, value: str) -> None:
        with self._lock:
            data = self._read()
            data[name] = value
            self._write(data)
            os.environ[name] = value

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._read()
            if data.pop(name, None) is not None:
                self._write(data)
            os.environ.pop(name, None)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._read())

    def export_env(self) -> None:
        """Make every stored secret visible to connectors as an environment variable."""
        with self._lock:
            for name, value in self._read().items():
                os.environ[name] = value
