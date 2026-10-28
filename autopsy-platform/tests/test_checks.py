"""Every check runs against the in-memory connector, so none of this needs a database file."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from autopsy.checks import (
    CheckContext,
    check_freshness,
    check_schema,
    check_volume,
    find_duplicates,
    profile_dataset,
)
from autopsy.core.baseline import Baseline, learn_baseline
from autopsy.core.manifest import parse_manifest
from autopsy.core.models import UnknownColumn, UnknownDataset
from fake_connector import FakeConnector

NOW = datetime(2026, 10, 28, 12, 0)
TYPES = {"event_id": "INTEGER", "created_at": "TIMESTAMP", "amount": "DOUBLE", "region": "VARCHAR"}


def history(days=20, per_day=10, skip_days=(), amount=100.0, null_region_from=None, repeat_day=None):
    """`per_day` events a day for `days` days up to today (today is partial: 3 events)."""
    rows, n = [], 0
    for back in range(days, -1, -1):
        day = NOW.date() - timedelta(days=back)
        if back in skip_days:
            continue
        count = 3 if back == 0 else per_day
        for i in range(count):
            n += 1
            row = {
                "event_id": n, "created_at": datetime(day.year, day.month, day.day, 1 + i), "amount": amount + i,
                "region": None if null_region_from is not None and back <= null_region_from else "north",
            }
            rows.append(row)
            if repeat_day == back:
                rows.append(dict(row))
    return rows


def manifest(**overrides):
    ds = {"name": "events", "source": "events_tbl", "business_visible": True,
          "roles": {"event_time": "created_at", "key": ["event_id"], "measure": ["amount"], "required": ["region"]},
          "expected": {"max_age_hours": 30}}
    ds.update(overrides.pop("dataset", {}))
    raw = {"project": "demo", "connector": "fake", "connection": {}, "datasets": [ds], **overrides}
    return parse_manifest(raw)


def ctx_for(rows, types=None, with_baseline=False, baseline_rows=None, **manifest_kw):
    m = manifest(**manifest_kw)
    connector = FakeConnector({"events_tbl": (types or TYPES, rows)})
    baseline = None
    if with_baseline:
        healthy = FakeConnector({"events_tbl": (TYPES, baseline_rows if baseline_rows is not None else history())})
        baseline = Baseline(learn_baseline(m, healthy, NOW))
    return CheckContext(m, connector, baseline, NOW)


# --- freshness ----------------------------------------------------------------

def test_freshness_ok():
    f = check_freshness(ctx_for(history()), "events")
    assert f.status == "ok" and f.evidence["empty_days_last_14"] == []


def test_freshness_fails_when_the_newest_row_is_too_old():
    rows = [r for r in history() if r["created_at"].date() < NOW.date() - timedelta(days=2)]
    f = check_freshness(ctx_for(rows), "events")
    assert f.status == "fail"
    assert f.evidence["max_age_hours"] == 30 and f.evidence["age_hours"] > 30
    assert "check_volume" in f.next_checks


def test_freshness_warns_about_a_gap_inside_the_window():
    f = check_freshness(ctx_for(history(skip_days=(5,))), "events")
    assert f.status == "warn"
    assert f.evidence["empty_days_last_14"] == [(NOW.date() - timedelta(days=5)).isoformat()]


def test_freshness_fails_on_an_empty_dataset():
    assert check_freshness(ctx_for([]), "events").status == "fail"


def test_freshness_skips_without_an_event_time_role():
    f = check_freshness(ctx_for(history(), dataset={"roles": {"key": ["event_id"]}}), "events")
    assert f.status == "skipped"


def test_freshness_learns_its_limit_from_the_baseline():
    ctx = ctx_for(history(), with_baseline=True, dataset={"expected": {}})
    f = check_freshness(ctx, "events")
    assert f.status == "ok" and f.evidence["limit_from"] == "baseline" and f.evidence["max_age_hours"] == 36


def test_freshness_skips_when_there_is_no_limit_at_all():
    assert check_freshness(ctx_for(history(), dataset={"expected": {}}), "events").status == "skipped"


# --- schema -------------------------------------------------------------------

def test_schema_skips_without_a_baseline():
    assert check_schema(ctx_for(history()), "events").status == "skipped"


def test_schema_ok_when_nothing_changed():
    assert check_schema(ctx_for(history(), with_baseline=True), "events").status == "ok"


def test_schema_fails_on_missing_and_renamed_columns():
    renamed = {("area" if k == "region" else k): v for k, v in TYPES.items()}
    rows = [{("area" if k == "region" else k): v for k, v in r.items()} for r in history()]
    f = check_schema(ctx_for(rows, types=renamed, with_baseline=True), "events")
    assert f.status == "fail" and f.evidence["missing"] == ["region"] and f.evidence["new"] == ["area"]


def test_schema_fails_on_a_retyped_column_and_only_warns_on_a_new_one():
    f = check_schema(ctx_for(history(), types={**TYPES, "amount": "VARCHAR"}, with_baseline=True), "events")
    assert f.status == "fail" and f.evidence["retyped"][0]["column"] == "amount"
    f = check_schema(ctx_for(history(), types={**TYPES, "extra": "INTEGER"}, with_baseline=True), "events")
    assert f.status == "warn" and f.evidence["new"] == ["extra"]


# --- duplicates ---------------------------------------------------------------

def test_duplicates_ok():
    assert find_duplicates(ctx_for(history()), "events").status == "ok"


def test_duplicates_counts_repeated_keys_and_extra_rows():
    f = find_duplicates(ctx_for(history(repeat_day=4)), "events")
    assert f.status == "fail"
    assert f.evidence["repeated_keys"] == 10 == f.evidence["extra_rows"]
    assert list(f.evidence["extra_rows_per_day"]) == [(NOW.date() - timedelta(days=4)).isoformat()]
    assert len(f.evidence["sample_keys"]) == 5


def test_duplicates_on_a_composite_key():
    rows = history()
    f = find_duplicates(ctx_for(rows, dataset={"roles": {"key": ["event_id", "region"]}}), "events")
    assert f.status == "ok"
    f = find_duplicates(ctx_for(rows, dataset={"roles": {"key": ["region"]}}), "events")
    assert f.status == "fail"


def test_duplicates_skips_without_a_key():
    assert find_duplicates(ctx_for(history(), dataset={"roles": {"event_time": "created_at"}}), "events").status == "skipped"


# --- volume -------------------------------------------------------------------

def test_volume_ok():
    f = check_volume(ctx_for(history()), "events")
    assert f.status == "ok" and f.evidence["median_rows_per_day"] == 10


def test_volume_catches_a_spike_and_a_drop():
    f = check_volume(ctx_for(history(repeat_day=4)), "events")
    assert f.status == "fail" and f.evidence["outside_band"][0]["change"] == 1.0
    f = check_volume(ctx_for(history(skip_days=(3, 2, 1))), "events")
    assert f.status == "fail" and len(f.evidence["outside_band"]) == 3


def test_volume_ignores_days_before_the_first_row_and_needs_history():
    f = check_volume(ctx_for(history(days=2)), "events")
    assert f.status == "skipped"


def test_volume_honours_the_threshold():
    rows = [r for i, r in enumerate(history()) if i % 11 != 0]       # a mild dip on some days
    tight = check_volume(ctx_for(rows, thresholds={"volume_change_ratio": 0.05}), "events")
    loose = check_volume(ctx_for(rows, thresholds={"volume_change_ratio": 0.9}), "events")
    assert tight.status == "fail" and loose.status == "ok"


# --- profile ------------------------------------------------------------------

def test_profile_ok_against_the_manifest_limits():
    f = profile_dataset(ctx_for(history(), dataset={"expected": {"value_range": {"amount": [1, 500]}, "max_null_rate": 0.1}}), "events")
    assert f.status == "ok"


def test_profile_fails_on_a_null_spike_in_the_recent_window():
    rows = history(null_region_from=3)
    f = profile_dataset(ctx_for(rows, thresholds={"max_null_rate": 0.02}), "events")
    assert f.status == "fail" and "null_rate" in f.evidence["problem_kinds"]
    assert f.evidence["recent"]["columns"]["region"]["null_rate"] == 1.0


def test_profile_fails_when_values_leave_the_manifest_range():
    f = profile_dataset(ctx_for(history(amount=100000.0), dataset={"expected": {"value_range": {"amount": [1, 500]}}}), "events")
    assert f.status == "fail" and "range" in f.evidence["problem_kinds"]


def test_profile_catches_a_unit_shift_from_the_baseline_alone():
    shifted = [dict(r, amount=r["amount"] * 100) if r["created_at"].date() >= NOW.date() - timedelta(days=3) else r
               for r in history()]
    ctx = ctx_for(shifted, with_baseline=True, dataset={"expected": {}})
    f = profile_dataset(ctx, "events")
    assert f.status == "fail" and "median_shift" in f.evidence["problem_kinds"]


def test_profile_warns_on_a_moderate_shift():
    shifted = [dict(r, amount=r["amount"] * 3) for r in history()]
    ctx = ctx_for(shifted, with_baseline=True, dataset={"expected": {}}, thresholds={"median_shift_factor": 10})
    assert profile_dataset(ctx, "events").status == "warn"


def test_profile_skips_when_there_is_nothing_to_compare_against():
    assert profile_dataset(ctx_for(history(), dataset={"expected": {}}), "events").status == "skipped"


def test_profile_restricts_to_requested_columns_and_rejects_unknown_ones():
    ctx = ctx_for(history(), thresholds={"max_null_rate": 0.5})
    assert list(profile_dataset(ctx, "events", columns=["region"]).evidence["columns"]) == ["region"]
    with pytest.raises(UnknownColumn):
        profile_dataset(ctx, "events", columns=["nope"])


# --- shared behaviour ---------------------------------------------------------

def test_unknown_dataset_names_raise_a_typed_error():
    ctx = ctx_for(history())
    for check in (check_freshness, check_schema, check_volume, find_duplicates, profile_dataset):
        with pytest.raises(UnknownDataset):
            check(ctx, "nope")


def test_connector_is_never_written_to():
    ctx = ctx_for(history(repeat_day=2), with_baseline=True)
    for check in (check_freshness, check_schema, check_volume, find_duplicates, profile_dataset):
        check(ctx, "events")
    assert ctx.connector.unchanged()
