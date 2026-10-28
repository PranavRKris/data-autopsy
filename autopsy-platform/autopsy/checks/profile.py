"""Profile: null rates, value ranges and median shifts on the measure and required roles.

Limits come from the manifest first, then from the baseline; with neither, nothing is compared.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from autopsy.checks.context import DEFAULT_SHIFT_FACTOR, CheckContext, skipped
from autopsy.core.models import FAIL, OK, WARN, Agg, AggSpec, Filter, Finding, UnknownColumn, worst_status

CHECK = "profile_dataset"
RECENT_DAYS = 3
WARN_SHIFT = 2.0


def profile_dataset(ctx: CheckContext, dataset: str, columns: list[str] | None = None) -> Finding:
    ds = ctx.dataset(dataset)
    kinds = {c.name: c.kind for c in ctx.connector.describe(ds.source)}
    chosen = list(dict.fromkeys(columns)) if columns else list(dict.fromkeys([*ds.roles.measure, *ds.roles.required]))
    if not chosen:
        return skipped(CHECK, ds, "dataset has no measure or required roles")
    for col in chosen:
        if col not in kinds:
            raise UnknownColumn(f"unknown column {col!r} in dataset {dataset!r}")

    base = ctx.baseline_for(ds)
    base_stats = (base or {}).get("stats", {})
    factor = ctx.threshold("median_shift_factor", DEFAULT_SHIFT_FACTOR)
    null_limit_default = ds.expected.max_null_rate if ds.expected.max_null_rate is not None \
        else ctx.threshold("max_null_rate")

    overall = _stats(ctx, ds, chosen, kinds, [])
    recent = None
    if ds.roles.event_time:
        # complete days only: today is partial, which skews medians of pre-aggregated datasets
        today = ctx.now.date()
        window = [Filter(ds.roles.event_time, ">=", (today - timedelta(days=RECENT_DAYS)).isoformat()),
                  Filter(ds.roles.event_time, "<", today.isoformat())]
        recent = _stats(ctx, ds, chosen, kinds, window)
        if recent["rows"] == 0:
            recent = None

    problems: list[str] = []
    problem_kinds: list[str] = []
    statuses: list[str] = []
    compared = 0
    per_column: dict[str, Any] = {}
    for col in chosen:
        cur, bs = overall["columns"][col], base_stats.get(col)
        entry: dict[str, Any] = dict(cur)
        statuses_before = len(statuses)

        # null rate: worst of the whole dataset and the recent window
        limit, limit_from = null_limit_default, "manifest"
        if limit is None and bs is not None:
            limit, limit_from = max(2 * bs["null_rate"], 0.01), "baseline"
        if limit is not None:
            compared += 1
            rates = {"overall": cur["null_rate"]}
            if recent:
                rates["recent"] = recent["columns"][col]["null_rate"]
            entry["null_limit"] = limit
            worst_window, worst_rate = max(rates.items(), key=lambda kv: kv[1])
            if worst_rate > limit:
                statuses.append(FAIL)
                problem_kinds.append("null_rate")
                problems.append(f"{col}: {worst_rate:.1%} null in the {worst_window} data (limit {limit:.1%}, from {limit_from})")

        if kinds[col] == "numeric" and cur.get("min") is not None:
            bounds, bounds_from = ds.expected.value_range.get(col), "manifest"
            if bounds is None and bs is not None and bs.get("min") is not None:
                bounds, bounds_from = _baseline_bounds(bs["min"], bs["max"], factor), "baseline"
            if bounds is not None:
                compared += 1
                entry["allowed_range"] = [round(bounds[0], 4), round(bounds[1], 4)]
                if cur["min"] < bounds[0] or cur["max"] > bounds[1]:
                    statuses.append(FAIL)
                    problem_kinds.append("range")
                    problems.append(f"{col}: values {cur['min']:g}..{cur['max']:g} outside {bounds_from} range "
                                    f"{bounds[0]:g}..{bounds[1]:g}")

            if bs is not None and bs.get("median"):
                compared += 1
                window = recent["columns"][col] if recent else cur
                if window.get("median") is not None:
                    shift = window["median"] / bs["median"]
                    entry["median_vs_baseline"] = round(shift, 3)
                    if shift >= factor or shift <= 1 / factor:
                        statuses.append(FAIL)
                        problem_kinds.append("median_shift")
                        problems.append(f"{col}: median {window['median']:g} is {shift:.3g}x the baseline {bs['median']:g}")
                    elif shift >= WARN_SHIFT or shift <= 1 / WARN_SHIFT:
                        statuses.append(WARN)
                        problems.append(f"{col}: median {window['median']:g} is {shift:.3g}x the baseline {bs['median']:g}")
        if len(statuses) == statuses_before:
            statuses.append(OK)
        per_column[col] = entry

    evidence: dict[str, Any] = {"rows": overall["rows"], "columns": per_column, "problems": problems,
                                "problem_kinds": sorted(set(problem_kinds))}
    if recent:
        evidence["recent"] = {
            "days": RECENT_DAYS, "rows": recent["rows"],
            "columns": {c: {k: v for k, v in s.items() if k in ("null_rate", "median")}
                        for c, s in recent["columns"].items()},
        }
    if compared == 0:
        return skipped(CHECK, ds, "no limits in the manifest and no baseline to compare against", evidence)

    status = worst_status(statuses)
    if status == OK:
        return Finding(CHECK, ds.name, OK, f"{len(chosen)} column(s) profiled; nothing outside its limits.", evidence)
    return Finding(CHECK, ds.name, status, "; ".join(problems) + ".", evidence, ["check_volume", "find_duplicates"])


def _stats(ctx: CheckContext, ds, chosen: list[str], kinds: dict[str, str], where: list[Filter]) -> dict[str, Any]:
    select = [Agg("count", "*", "rows")]
    for i, col in enumerate(chosen):
        select.append(Agg("count_null", col, f"nulls_{i}"))
        if kinds[col] == "numeric":
            select += [Agg("min", col, f"min_{i}"), Agg("max", col, f"max_{i}"), Agg("median", col, f"median_{i}")]
    (row,) = ctx.connector.aggregate(ds.source, AggSpec(select=select, where=where))
    rows = row["rows"]
    out: dict[str, Any] = {}
    for i, col in enumerate(chosen):
        entry: dict[str, Any] = {"null_rate": round(row[f"nulls_{i}"] / rows, 4) if rows else 0.0}
        if f"min_{i}" in row:
            entry.update(min=row[f"min_{i}"], max=row[f"max_{i}"], median=row[f"median_{i}"])
        out[col] = entry
    return {"rows": rows, "columns": out}


def _baseline_bounds(low: float, high: float, factor: float) -> tuple[float, float]:
    """Room around the healthy range before a value counts as outside it."""
    if low > 0:
        return low / factor, high * factor
    span = max(high - low, abs(high), 1.0)
    return low - span * factor, high + span * factor
