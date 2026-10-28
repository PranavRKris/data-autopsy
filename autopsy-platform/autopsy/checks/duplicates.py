"""Duplicates: does any value of the key role appear more than once?"""
from __future__ import annotations

from collections import Counter

from autopsy.checks.context import CheckContext, skipped
from autopsy.core.models import FAIL, MAX_LIMIT, OK, Agg, AggSpec, Filter, Finding

CHECK = "find_duplicates"
SAMPLE_KEYS = 5
PER_DAY_ROWS = 14


def find_duplicates(ctx: CheckContext, dataset: str) -> Finding:
    ds = ctx.dataset(dataset)
    key = list(ds.roles.key)
    if not key:
        return skipped(CHECK, ds, "dataset has no key role")

    select = [Agg("count", "*", "_n")]
    et = ds.roles.event_time
    if et:
        select.append(Agg("min", et, "_first"))
    rows = ctx.connector.aggregate(
        ds.source,
        AggSpec(select=select, group_by=key, having=[Filter("_n", ">", 1)], order_by=["-_n"], limit=MAX_LIMIT),
    )
    if not rows:
        return Finding(CHECK, ds.name, OK, f"No repeated values of key ({', '.join(key)}).",
                       {"repeated_keys": 0, "extra_rows": 0})

    extra = sum(r["_n"] - 1 for r in rows)
    capped = len(rows) == MAX_LIMIT
    per_day = Counter()
    for r in rows:
        if et and r.get("_first"):
            per_day[str(r["_first"])[:10]] += r["_n"] - 1
    evidence = {
        "repeated_keys": len(rows),
        "extra_rows": extra,
        "at_least": capped,
        "extra_rows_per_day": dict(sorted(per_day.items())[-PER_DAY_ROWS:]),
        "sample_keys": [{k: r[k] for k in key} | {"copies": r["_n"]} for r in rows[:SAMPLE_KEYS]],
    }
    more = "at least " if capped else ""
    summary = f"{more}{len(rows)} key value(s) repeat ({more}{extra} extra rows) on key ({', '.join(key)})."
    return Finding(CHECK, ds.name, FAIL, summary, evidence, ["check_volume"])
