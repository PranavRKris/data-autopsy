"""Learn what "normal" looks like from a healthy period, and load it back.

Baselines live under state/, never in a project's database.
"""
from __future__ import annotations

import json
import os
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autopsy.core.manifest import Manifest
from autopsy.core.models import Agg, AggSpec, Bucket, Filter

if TYPE_CHECKING:
    from autopsy.connectors.base import Connector

PLATFORM_ROOT = Path(__file__).resolve().parents[2]


def utcnow() -> datetime:
    """Current UTC time as a naive datetime. AUTOPSY_NOW (ISO) pins the clock for repeatable demos and tests."""
    pinned = os.environ.get("AUTOPSY_NOW")
    if pinned:
        return datetime.fromisoformat(pinned)
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def state_dir() -> Path:
    return Path(os.environ.get("AUTOPSY_STATE_DIR") or PLATFORM_ROOT / "state")


def baseline_path(project: str, directory: Path | None = None) -> Path:
    return (directory or state_dir()) / f"{project}.json"


@dataclass(frozen=True)
class Baseline:
    data: dict[str, Any]

    def dataset(self, name: str) -> dict[str, Any] | None:
        return self.data.get("datasets", {}).get(name)


def load_baseline(project: str, directory: Path | None = None) -> Baseline | None:
    path = baseline_path(project, directory)
    if not path.is_file():
        return None
    return Baseline(json.loads(path.read_text(encoding="utf-8")))


def learn_baseline(
    manifest: Manifest,
    connector: "Connector",
    now: datetime | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Snapshot the schema, per-column statistics and daily volumes of every dataset."""
    now = now or utcnow()
    datasets = {}
    for ds in manifest.datasets:
        columns = connector.describe(ds.source)
        kinds = {c.name: c.kind for c in columns}
        where = []
        if ds.roles.event_time and since:
            where.append(Filter(ds.roles.event_time, ">=", since))
        if ds.roles.event_time and until:
            where.append(Filter(ds.roles.event_time, "<", until))

        tracked = list(dict.fromkeys([*ds.roles.measure, *ds.roles.required]))
        select = [Agg("count", "*", "n")]
        for i, col in enumerate(tracked):
            select.append(Agg("count_null", col, f"nulls_{i}"))
            if kinds.get(col) == "numeric":
                select += [Agg("min", col, f"min_{i}"), Agg("max", col, f"max_{i}"), Agg("median", col, f"median_{i}")]
        (row,) = connector.aggregate(ds.source, AggSpec(select=select, where=where))

        stats: dict[str, Any] = {}
        for i, col in enumerate(tracked):
            n = row["n"]
            entry: dict[str, Any] = {"null_rate": (row[f"nulls_{i}"] / n) if n else 0.0}
            if f"min_{i}" in row:
                entry.update(min=row[f"min_{i}"], max=row[f"max_{i}"], median=row[f"median_{i}"])
            stats[col] = entry

        datasets[ds.name] = {
            "source": ds.source,
            "columns": [{"name": c.name, "type": c.type} for c in columns],
            "rows": row["n"],
            "stats": stats,
            "daily_volume": _daily_volume(connector, ds.source, ds.roles.event_time, where, now.date()),
        }
    return {"project": manifest.project, "created_at": now.isoformat(), "datasets": datasets}


def _daily_volume(connector, source, event_time, where, today: date) -> dict[str, Any] | None:
    if not event_time:
        return None
    rows = connector.aggregate(
        source,
        AggSpec(
            select=[Agg("count", "*", "n")],
            group_by=[Bucket(event_time, "day")],
            where=[*where, Filter(event_time, "<", today.isoformat())],   # today is still partial
            order_by=["day"],
        ),
    )
    if not rows:
        return None
    days = [date.fromisoformat(r["day"]) for r in rows]
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    return {
        "days": len(rows),
        "median": statistics.median(r["n"] for r in rows),
        "min": min(r["n"] for r in rows),
        "max": max(r["n"] for r in rows),
        "max_gap_days": max(gaps, default=1),
    }


def save_baseline(data: dict[str, Any], directory: Path | None = None) -> Path:
    path = baseline_path(data["project"], directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def previous_days(today: date, n: int) -> list[str]:
    """The `n` complete days before `today`, oldest first."""
    return [(today - timedelta(days=i)).isoformat() for i in range(n, 0, -1)]
