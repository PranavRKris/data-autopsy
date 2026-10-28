"""Seed the Acme Shop database: healthy data (S0) plus five failure scenarios.

usage: seed_data.py --db acme.duckdb --scenario S0..S5 [--as-of 2026-10-28T12:00:00]

Data covers the 30 days up to --as-of, so a freshly seeded healthy database is fresh at that moment.
This file imports nothing from the Pipeline Autopsy platform.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import random
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

SCENARIOS = {
    "S0": "healthy control",
    "S1": "one day's batch of orders is loaded twice",
    "S2": "upstream renames channel to sales_channel",
    "S3": "40% of new orders arrive with a null customer_id",
    "S4": "no orders loaded for the last 3 days",
    "S5": "amounts arrive in cents instead of dollars",
}
CUSTOMERS = 200
DAYS = 30
CHANNELS = ["web"] * 10 + ["mobile"] * 7 + ["store"] * 3


def generate(as_of: datetime, seed: int = 7, days: int = DAYS):
    rng = random.Random(seed)
    customers = [(i, f"Customer {i}", (as_of - timedelta(days=rng.randint(60, 900))).date().isoformat())
                 for i in range(1, CUSTOMERS + 1)]
    orders = []
    order_id = 1000
    today = as_of.date()
    for back in range(days - 1, -1, -1):
        day = today - timedelta(days=back)
        count = rng.randint(180, 220)
        span = 86400.0
        if back == 0:                       # today is only partly over
            span = max((as_of - datetime(day.year, day.month, day.day)).total_seconds(), 60.0)
            count = max(1, int(count * span / 86400))
        stamps = sorted(rng.uniform(0, span) for _ in range(count))
        for offset in stamps:
            order_id += 1
            amount = round(min(max(rng.lognormvariate(math.log(60), 0.6), 1.0), 1500.0), 2)
            orders.append({
                "order_id": order_id,
                "customer_id": rng.randint(1, CUSTOMERS),
                "ordered_at": datetime(day.year, day.month, day.day) + timedelta(seconds=offset),
                "amount": amount,
                "channel": rng.choice(CHANNELS),
            })
    return customers, orders


def apply_scenario(orders: list[dict], scenario: str, as_of: datetime, seed: int = 7) -> list[dict]:
    rng = random.Random(seed + 1)
    today = as_of.date()
    if scenario == "S1":
        target = today - timedelta(days=3)
        orders = orders + [dict(o) for o in orders if o["ordered_at"].date() == target]
    elif scenario == "S3":
        for o in orders:
            if o["ordered_at"].date() >= today - timedelta(days=3) and rng.random() < 0.4:
                o["customer_id"] = None
    elif scenario == "S4":
        orders = [o for o in orders if o["ordered_at"].date() < today - timedelta(days=2)]
    elif scenario == "S5":
        for o in orders:
            if o["ordered_at"].date() >= today - timedelta(days=4):
                o["amount"] = round(o["amount"] * 100, 2)
    return orders


def write_database(db_path: Path, customers: list[tuple], orders: list[dict], scenario: str) -> None:
    channel_col = "sales_channel" if scenario == "S2" else "channel"
    for suffix in ("", ".wal"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        con.execute("create schema raw")
        con.execute("create table raw.customers (customer_id integer, name varchar, signup_date date)")
        con.execute(
            f"create table raw.orders (order_id integer, customer_id integer, ordered_at timestamp, "
            f"amount double, {channel_col} varchar)"
        )
        with tempfile.TemporaryDirectory() as tmp:
            for table, rows in (("raw.customers", customers),
                                ("raw.orders", [(o["order_id"], o["customer_id"], o["ordered_at"].isoformat(sep=" "),
                                                 o["amount"], o["channel"]) for o in orders])):
                path = os.path.join(tmp, table + ".csv")
                with open(path, "w", newline="", encoding="utf-8") as fh:
                    csv.writer(fh).writerows(rows)
                con.execute(f"copy {table} from '{path}' (format csv, header false)")
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--scenario", default="S0", choices=sorted(SCENARIOS))
    parser.add_argument("--as-of", default=os.environ.get("ACME_AS_OF"), help="ISO time the data runs up to (default: now, in UTC, which is how the platform reads naive timestamps)")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    customers, orders = generate(as_of, args.seed)
    orders = apply_scenario(orders, args.scenario, as_of, args.seed)
    write_database(Path(args.db), customers, orders, args.scenario)
    print(f"seeded {args.db}: scenario {args.scenario} ({SCENARIOS[args.scenario]}), "
          f"{len(customers)} customers, {len(orders)} orders, data up to {as_of.isoformat()}")


if __name__ == "__main__":
    main()
