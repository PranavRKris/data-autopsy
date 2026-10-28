"""Independence, enforced: no plug-in's tables, columns or names may appear anywhere under autopsy/."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

PLATFORM = Path(__file__).resolve().parents[1]
PLUGINS = PLATFORM.parent / "plugins"

# Words that are plain vocabulary of the platform itself (bucket units, role names), not project names.
GENERIC = {"day", "hour", "key", "name", "id", "type", "value", "count", "source", "rows", "date"}

needs_plugins = pytest.mark.skipif(not PLUGINS.is_dir(), reason="no plugins/ folder next to the platform")


def plugin_terms() -> dict[str, str]:
    """Every project-specific word the plug-in manifests declare, with where it came from."""
    terms: dict[str, str] = {}
    for manifest in sorted(PLUGINS.glob("*/manifest.yaml")):
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        origin = manifest.parent.name

        def add(word: str, what: str) -> None:
            if str(word).lower() not in GENERIC:
                terms[str(word)] = f"{origin}: {what}"

        add(raw["project"], "project")
        add(origin, "plug-in folder")
        for ds in raw["datasets"]:
            add(ds["name"], "dataset")
            add(ds["source"], "source")
            add(ds["source"].split(".")[-1], "table")      # schema names like "raw" are generic vocabulary
            roles = ds["roles"]
            for role in ("event_time", "key", "measure", "required"):
                value = roles.get(role)
                for col in [value] if isinstance(value, str) else value or []:
                    add(col, f"{role} column")
            for col in (ds.get("expected") or {}).get("value_range", {}):
                add(col, "column")
    return terms


def mentions(text: str, term: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", text, re.I) is not None


def platform_sources() -> list[Path]:
    return [p for p in (PLATFORM / "autopsy").rglob("*") if p.is_file() and p.suffix in {".py", ".md", ".yaml", ".sql", ".js", ".html", ".css", ".svg", ".json"}]


@needs_plugins
def test_the_plugins_declare_terms_to_look_for():
    assert len(plugin_terms()) >= 5


@needs_plugins
def test_no_plugin_name_appears_in_the_platform():
    terms = plugin_terms()
    hits = [
        f"{path.relative_to(PLATFORM)} mentions {term!r} ({origin})"
        for path in platform_sources()
        for term, origin in terms.items()
        if mentions(path.read_text(encoding="utf-8"), term)
    ]
    assert not hits, "\n".join(hits)


def test_the_platform_never_imports_from_plugins():
    pattern = re.compile(r"^\s*(from|import)\s+plugins\b", re.M)
    assert not [p for p in platform_sources() if pattern.search(p.read_text(encoding="utf-8"))]


@needs_plugins
def test_the_detector_would_catch_a_leak():
    """Guard the guard: a hard-coded plug-in table name must be seen by the same matching rule."""
    assert any(mentions("SELECT * FROM staging.stg_orders", t) for t in plugin_terms())
