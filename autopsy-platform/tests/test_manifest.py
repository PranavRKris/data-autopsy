from __future__ import annotations

import pytest
import yaml

from autopsy.core.manifest import load_manifest, parse_manifest, validate_against
from autopsy.core.models import ManifestError
from fake_connector import FakeConnector

BASE = {
    "project": "demo",
    "connector": "duckdb",
    "connection": {"path_env": "DEMO_DB_PATH"},
    "datasets": [
        {"name": "events", "source": "raw.events", "feeds": ["totals"],
         "roles": {"event_time": "created_at", "key": "event_id", "measure": ["amount"], "required": ["event_id"]},
         "expected": {"max_age_hours": 36, "value_range": {"amount": [1, 5000]}}},
        {"name": "totals", "source": "mart.totals", "business_visible": True, "roles": {"event_time": "day"}},
    ],
    "thresholds": {"max_null_rate": 0.02},
}


def mutated(**changes):
    raw = yaml.safe_load(yaml.safe_dump(BASE))
    for path, value in changes.items():
        target = raw
        *parents, last = path.split("__")
        for part in parents:
            target = target[int(part)] if part.isdigit() else target[part]
        key = int(last) if last.isdigit() else last
        if value is ...:
            del target[key]
        else:
            target[key] = value
    return raw


def test_parses_the_generic_example():
    m = parse_manifest(BASE)
    assert m.project == "demo" and [d.name for d in m.datasets] == ["events", "totals"]
    events = m.dataset("events")
    assert events.roles.key == ("event_id",)                  # a single name is accepted
    assert events.expected.value_range == {"amount": (1.0, 5000.0)}
    assert m.threshold("max_null_rate") == 0.02


def test_lineage_helpers():
    m = parse_manifest(BASE)
    assert m.upstream("totals") == ["events"] and m.ancestors("totals") == ["events"]
    assert m.descendants("events") == ["totals"]


def test_loads_from_a_file(tmp_path):
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump(BASE))
    assert load_manifest(path).path == path
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "missing.yaml")


@pytest.mark.parametrize("changes, fragment", [
    ({"project": ...}, "missing required field 'project'"),
    ({"project": "../etc/x"}, "may only contain"),
    ({"mystery": 1}, "unknown field"),
    ({"datasets__0__roles__evnt_time": "x"}, "unknown field"),            # a typo is an error, not ignored
    ({"datasets__1__name": "events"}, "unique"),
    ({"datasets__0__feeds": ["ghost"]}, "unknown dataset"),
    ({"datasets__0__feeds": ["events"]}, "feed itself"),
    ({"datasets__1__feeds": ["events"]}, "cycle"),
    ({"datasets__0__expected__value_range": {"amount": [5, 1]}}, "low > high"),
    ({"thresholds": {"typo": 1}}, "unknown field"),
    ({"connection": {"password": "hunter2"}}, "looks like a secret"),
    ({"connection": {"api_key": "abc"}}, "looks like a secret"),
    ({"connection": {"path_env": "not a var name"}}, "environment variable"),
    ({"datasets": []}, "at least one dataset"),
])
def test_rejects_bad_manifests(changes, fragment):
    with pytest.raises(ManifestError, match=fragment):
        parse_manifest(mutated(**changes))


def test_secrets_may_be_named_but_never_stored():
    parse_manifest(mutated(connection={"host": "db.internal", "password_env": "DB_PASSWORD"}))


def conn(types_by_source):
    return FakeConnector({src: (types, []) for src, types in types_by_source.items()})


def test_validate_passes_when_roles_match_the_schema():
    c = conn({"raw.events": {"created_at": "TIMESTAMP", "event_id": "INTEGER", "amount": "DOUBLE"},
              "mart.totals": {"day": "DATE"}})
    assert [i for i in validate_against(parse_manifest(BASE), c) if i.level == "error"] == []


def test_validate_reports_each_kind_of_mismatch():
    c = conn({"raw.events": {"created_at": "VARCHAR", "event_id": "INTEGER", "amount": "VARCHAR"}})
    messages = [str(i) for i in validate_against(parse_manifest(BASE), c)]
    assert any("not a date/time" in m for m in messages)
    assert any("not numeric" in m for m in messages)
    assert any("mart.totals" in m and "does not exist" in m for m in messages)


def test_validate_flags_missing_columns_and_says_what_gets_skipped():
    c = conn({"raw.events": {"created_at": "TIMESTAMP", "amount": "DOUBLE"}, "mart.totals": {"day": "DATE"}})
    messages = [str(i) for i in validate_against(parse_manifest(BASE), c)]
    assert any("key column 'event_id' not found" in m for m in messages)
    assert any("[info] totals: no key role" in m for m in messages)
