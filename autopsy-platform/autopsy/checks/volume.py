"""Volume: does any recent day deviate from the trailing median rows per day?"""
from __future__ import annotations

from autopsy.checks.context import (
    DEFAULT_VOLUME_RATIO,
    WINDOW_DAYS,
    CheckContext,
    median,
    recent_daily_counts,
    skipped,
)
from autopsy.core.models import FAIL, OK, Finding

CHECK = "check_volume"


def check_volume(ctx: CheckContext, dataset: str) -> Finding:
    ds = ctx.dataset(dataset)
    if not ds.roles.event_time:
        return skipped(CHECK, ds, "dataset has no event_time role")

    counts = recent_daily_counts(ctx, ds)["counts"]
    ratio = ctx.threshold("volume_change_ratio", DEFAULT_VOLUME_RATIO)
    if len(counts) < 3:
        return skipped(CHECK, ds, f"fewer than 3 complete days of history in the last {WINDOW_DAYS}", {"days": counts})
    mid = median(list(counts.values()))
    if mid == 0:
        return skipped(CHECK, ds, "the trailing median is zero rows per day", {"days": counts})

    low, high = mid * (1 - ratio), mid * (1 + ratio)
    outside = [
        {"day": day, "rows": n, "change": round((n - mid) / mid, 2)}
        for day, n in counts.items() if not low <= n <= high
    ]
    evidence = {"median_rows_per_day": mid, "allowed_band": [round(low, 1), round(high, 1)],
                "outside_band": outside, "rows_per_day": counts}
    if outside:
        worst = max(outside, key=lambda o: abs(o["change"]))
        summary = (f"{len(outside)} of {len(counts)} days are outside the allowed band; "
                   f"worst is {worst['day']} with {worst['rows']} rows ({worst['change']:+.0%} vs median {mid:g}).")
        return Finding(CHECK, ds.name, FAIL, summary, evidence, ["find_duplicates", "check_freshness"])
    return Finding(CHECK, ds.name, OK, f"All {len(counts)} recent days are within the band around {mid:g} rows/day.",
                   evidence)
