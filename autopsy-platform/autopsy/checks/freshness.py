"""Freshness: is the newest row recent enough, and did any recent day load nothing?"""
from __future__ import annotations

from autopsy.checks.context import CheckContext, hours_between, parse_ts, recent_daily_counts, skipped
from autopsy.core.models import FAIL, OK, WARN, Agg, AggSpec, Finding

CHECK = "check_freshness"


def check_freshness(ctx: CheckContext, dataset: str) -> Finding:
    ds = ctx.dataset(dataset)
    et = ds.roles.event_time
    if not et:
        return skipped(CHECK, ds, "dataset has no event_time role")

    (row,) = ctx.connector.aggregate(ds.source, AggSpec(select=[Agg("max", et, "latest")]))
    if row["latest"] is None:
        return Finding(CHECK, ds.name, FAIL, "Dataset has no rows.", {"latest": None}, ["check_volume"])

    latest = parse_ts(row["latest"])
    age = round(hours_between(ctx.now, latest), 1)
    window = recent_daily_counts(ctx, ds)["counts"]
    empty_days = [day for day, n in window.items() if n == 0]

    limit = ds.expected.max_age_hours or ctx.threshold("max_age_hours")
    source = "manifest"
    if limit is None:
        base = ctx.baseline_for(ds)
        volume = base and base.get("daily_volume")
        if volume:
            limit = 24.0 * volume["max_gap_days"] * 1.5
            source = "baseline"
    evidence = {
        "latest": latest.isoformat(), "age_hours": age, "max_age_hours": limit,
        "limit_from": source if limit is not None else None, "empty_days_last_14": empty_days,
    }
    if limit is None:
        return skipped(CHECK, ds, "no max_age_hours in the manifest and no baseline to learn one from", evidence)

    if age > limit:
        return Finding(CHECK, ds.name, FAIL, f"Newest row is {age:g} hours old; the limit is {limit:g}.",
                       evidence, ["check_volume"])
    if empty_days:
        return Finding(CHECK, ds.name, WARN,
                       f"Newest row is fresh ({age:g}h) but {len(empty_days)} recent day(s) have no rows.",
                       evidence, ["check_volume"])
    return Finding(CHECK, ds.name, OK, f"Newest row is {age:g} hours old; the limit is {limit:g}.", evidence)
