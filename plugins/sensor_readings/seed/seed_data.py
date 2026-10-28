"""Seed a tiny temperature-sensor database: one table, hourly readings from five sensors.

usage: seed_data.py --db sensors.duckdb --scenario S0|S1 [--as-of 2026-10-28T12:00:00]
  S0  healthy
  S1  stale feed: the readings stop 2 days before --as-of
This file imports nothing from the Pipeline Autopsy platform.
"""
from __future__ import annotations

import argparse
import math
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

SENSORS = 5
DAYS = 20


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--scenario", default="S0", choices=["S0", "S1"])
    parser.add_argument("--as-of", default=os.environ.get("SENSOR_AS_OF"))
    args = parser.parse_args()

    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now().replace(microsecond=0)
    last = as_of.replace(minute=0, second=0, microsecond=0)
    if args.scenario == "S1":
        last -= timedelta(days=2)
    rng = random.Random(11)

    rows = []
    hour = last - timedelta(days=DAYS)
    while hour <= last:
        for sensor in range(1, SENSORS + 1):
            temp = 20 + 4 * math.sin(hour.hour / 24 * 2 * math.pi) + rng.gauss(0, 0.5)
            rows.append((sensor, hour.isoformat(sep=" "), round(temp, 2)))
        hour += timedelta(hours=1)

    path = Path(args.db)
    for suffix in ("", ".wal"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    con.execute("create table readings (sensor_id integer, recorded_at timestamp, temperature_c double)")
    con.executemany("insert into readings values (?, ?, ?)", rows)
    con.close()
    print(f"seeded {args.db}: scenario {args.scenario}, {len(rows)} readings up to {last.isoformat()}")


if __name__ == "__main__":
    main()
