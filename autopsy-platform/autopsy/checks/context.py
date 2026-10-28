"""What a check needs to run: a manifest, a connector, an optional baseline, and the current time."""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from autopsy.connectors.base import Connector, parse_temporal
from autopsy.core.baseline import Baseline, previous_days, utcnow
from autopsy.core.manifest import Dataset, Manifest
from autopsy.core.models import SKIPPED, Agg, AggSpec, Bucket, Filter, Finding

DEFAULT_VOLUME_RATIO = 0.5
DEFAULT_SHIFT_FACTOR = 5.0
WINDOW_DAYS = 14


@dataclass
class CheckContext:
    manifest: Manifest
    connector: Connector
    baseline: Baseline | None = None
    now: datetime = field(default_factory=utcnow)

    def dataset(self, name: str) -> Dataset:
        return self.manifest.dataset(name)       # raises UnknownDataset

    def baseline_for(self, ds: Dataset) -> dict[str, Any] | None:
        return self.baseline.dataset(ds.name) if self.baseline else None

    def threshold(self, key: str, default: float | None = None) -> float | None:
        value = self.manifest.threshold(key)
        return default if value is None else value


def skipped(check: str, ds: Dataset, reason: str, evidence: dict[str, Any] | None = None) -> Finding:
    return Finding(check, ds.name, SKIPPED, f"Skipped: {reason}.", evidence or {})


def hours_between(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 3600


def parse_ts(value: Any) -> datetime:
    return parse_temporal(value)


def recent_daily_counts(ctx: CheckContext, ds: Dataset) -> dict[str, Any]:
    """Rows per day for the last 14 complete days (today is partial and left out).

    Days before the dataset's first row are not "missing", so they are left out of the window.
    """
    et = ds.roles.event_time
    assert et, "caller must check the event_time role first"
    today = ctx.now.date()
    window = previous_days(today, WINDOW_DAYS)
    first = ctx.connector.aggregate(ds.source, AggSpec(select=[Agg("min", et, "first")]))[0]["first"]
    rows = ctx.connector.aggregate(
        ds.source,
        AggSpec(
            select=[Agg("count", "*", "n")],
            group_by=[Bucket(et, "day")],
            where=[Filter(et, ">=", window[0]), Filter(et, "<", today.isoformat())],
            order_by=["day"],
            limit=WINDOW_DAYS + 1,
        ),
    )
    counts = {r["day"]: r["n"] for r in rows}
    first_day = parse_ts(first).date().isoformat() if first is not None else None
    days = [d for d in window if first_day is not None and d >= first_day]
    return {"counts": {d: counts.get(d, 0) for d in days}, "first_day": first_day}


def median(values: list[float]) -> float:
    return statistics.median(values)


def as_date(value: str) -> date:
    return date.fromisoformat(value)
