"""Acme Shop application core: place orders, run the pipeline, read the revenue dashboard, and cause (and undo)
the production incidents the demo is about.

The shop owns its database. It imports nothing from the Pipeline Autopsy platform: the platform only ever reads
this database, through the manifest. Everything the shop keeps for its own bookkeeping lives in the `app` schema,
which the manifest never mentions.

Incident events mirror the seeded scenarios (S1-S5), so `expected/expected_results.yaml` still says what the
platform should find. A sticky event keeps affecting new orders until it is rolled back, and also rewrites the
last few days of orders as if the change had been live since then (the demo cannot wait three days).
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
LOCK_WAIT_SECONDS = 20.0
GUEST_RATE = 0.4
CHANNELS = ["web"] * 10 + ["mobile"] * 7 + ["store"] * 3

PRODUCTS = [
    {"id": "mug", "name": "Ceramic mug", "price": 14.00, "blurb": "Dishwasher safe, 350 ml", "hue": 28},
    {"id": "tote", "name": "Canvas tote", "price": 22.50, "blurb": "Heavy cotton, long handles", "hue": 95},
    {"id": "notebook", "name": "Dot-grid notebook", "price": 9.90, "blurb": "A5, 120 gsm paper", "hue": 205},
    {"id": "hoodie", "name": "Everyday hoodie", "price": 59.00, "blurb": "Brushed fleece, relaxed fit", "hue": 345},
    {"id": "sneakers", "name": "Trail sneakers", "price": 120.00, "blurb": "Light, grippy, waterproof", "hue": 160},
    {"id": "lamp", "name": "Desk lamp", "price": 74.00, "blurb": "Dimmable warm LED", "hue": 48},
    {"id": "headphones", "name": "Studio headphones", "price": 189.00, "blurb": "Closed back, 40 hour battery", "hue": 262},
    {"id": "backpack", "name": "Commuter backpack", "price": 98.00, "blurb": "Fits a 16 inch laptop", "hue": 12},
]

# What each event is, in the words of the team that would be paged, and what the platform should say about it.
EVENTS: dict[str, dict[str, Any]] = {
    "duplicate_batch": {
        "title": "Partner feed replays a batch",
        "story": "The marketplace partner's nightly export was retried after a timeout, and the loader accepted the same "
                 "day of orders twice.",
        "symptom": "One day of revenue in the finance dashboard is double.",
        "sticky": False,
        "scenario": "S1",
        "expect": "orders_raw / find_duplicates, SEV1",
        "rollback": "Delete the second copy of every repeated order.",
    },
    "schema_rename": {
        "title": "Checkout v2.4 renames a column",
        "story": "The checkout team shipped a release that writes the sales channel as sales_channel instead of channel, "
                 "without telling anyone downstream.",
        "symptom": "All revenue moves to a channel called \"unknown\"; the pipeline log has one warning.",
        "sticky": True,
        "scenario": "S2",
        "expect": "orders_raw / check_schema, SEV2",
        "rollback": "Revert the release: the column is renamed back.",
    },
    "guest_checkout": {
        "title": "Mobile release adds guest checkout",
        "story": "The new mobile app lets people check out without an account, and sends no customer id for them.",
        "symptom": "Revenue is about 40% lower than expected, and nothing errors: the join silently drops those orders.",
        "sticky": True,
        "scenario": "S3",
        "expect": "orders_raw / profile_dataset, SEV2",
        "rollback": "Restore the customer ids from the source of truth and turn guest checkout off.",
    },
    "ingestion_outage": {
        "title": "Order ingestion goes down",
        "story": "The queue consumer that loads orders crashed. The storefront keeps taking orders, but they pile up in a "
                 "dead-letter queue instead of reaching the warehouse.",
        "symptom": "The last three days of revenue are missing.",
        "sticky": True,
        "scenario": "S4",
        "expect": "orders_raw / check_freshness, SEV3",
        "rollback": "Restart the consumer: it backfills the missing days and replays the queued orders.",
    },
    "cents_bug": {
        "title": "Pricing deploy sends cents",
        "story": "A pricing service deploy started sending amounts in cents instead of dollars.",
        "symptom": "Revenue is a hundred times too high.",
        "sticky": True,
        "scenario": "S5",
        "expect": "orders_raw / profile_dataset, SEV1",
        "rollback": "Roll back the deploy and restore the dollar amounts.",
    },
}


def utc_now() -> datetime:
    """Timestamps are naive UTC, the convention the platform reads them in."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class ShopError(Exception):
    """A problem the caller caused (unknown product, event already active); the API reports it as a 4xx."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Shop:
    def __init__(self, db_path: str | Path, clock: Callable[[], datetime] = utc_now,
                 python: str = sys.executable, log_path: str | Path | None = None):
        self.db_path = str(db_path)
        self.clock = clock
        self.python = python
        self.log_path = Path(log_path) if log_path else PLUGIN / "logs" / "pipeline_run.log"
        self._lock = threading.RLock()          # one writer in this process at a time
        self._rng = random.Random()
        self.pipeline: dict[str, Any] = {"last_run_at": None, "ok": None, "duration_ms": None, "message": "not run yet",
                                         "log_lines": 0, "warnings": []}

    # --- database plumbing ---------------------------------------------------------------

    def _connect(self):
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                con = duckdb.connect(self.db_path)
                break
            except duckdb.IOException as exc:      # another process (a reader, the pipeline) has the file
                text = str(exc).lower()
                busy = any(m in text for m in ("lock", "being used by another process", "cannot access the file"))
                if not busy or time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        con.execute("create schema if not exists app")
        con.execute("create table if not exists app.state (key varchar primary key, value varchar)")
        con.execute("create table if not exists app.fault_log (order_id integer, fault varchar, "
                    "orig_customer_id integer, orig_amount double)")
        con.execute("create table if not exists app.dead_letter (queued_at timestamp, customer_id integer, "
                    "amount double, channel varchar)")
        if not con.execute("select count(*) from information_schema.tables where table_schema = 'app' "
                           "and table_name = 'outage_backup'").fetchone()[0] and self._has_orders(con):
            con.execute("create table app.outage_backup as select * from raw.orders where false")
        return con

    @staticmethod
    def _has_orders(con) -> bool:
        return bool(con.execute("select count(*) from information_schema.tables where table_schema = 'raw' "
                                "and table_name = 'orders'").fetchone()[0])

    @contextmanager
    def db(self):
        with self._lock:
            con = self._connect()
            try:
                yield con
            finally:
                con.close()

    @staticmethod
    def _channel_column(con) -> str:
        cols = [r[0] for r in con.execute("select column_name from information_schema.columns "
                                          "where table_schema = 'raw' and table_name = 'orders'").fetchall()]
        return "sales_channel" if "sales_channel" in cols else "channel"

    @staticmethod
    def _get_state(con, key: str, default: Any) -> Any:
        row = con.execute("select value from app.state where key = ?", [key]).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def _set_state(con, key: str, value: Any) -> None:
        con.execute("insert or replace into app.state values (?, ?)", [key, json.dumps(value)])

    def today(self):
        return self.clock().date()

    # --- the storefront ------------------------------------------------------------------

    def products(self) -> list[dict[str, Any]]:
        return PRODUCTS

    def customers(self, limit: int = 40) -> list[dict[str, Any]]:
        with self.db() as con:
            rows = con.execute("select customer_id, name from raw.customers order by customer_id limit ?", [limit]).fetchall()
        return [{"customer_id": r[0], "name": r[1]} for r in rows]

    def place_order(self, customer_id: int | None = None, items: list[dict[str, Any]] | None = None,
                    channel: str = "web") -> dict[str, Any]:
        """Take an order the way the live application does, faults and all."""
        by_id = {p["id"]: p for p in PRODUCTS}
        items = items or [{"product_id": self._rng.choice(PRODUCTS)["id"], "qty": 1}]
        total = 0.0
        for item in items:
            product = by_id.get(item.get("product_id"))
            qty = int(item.get("qty", 1))
            if product is None or not 1 <= qty <= 20:
                raise ShopError(f"unknown product or quantity: {item!r}")
            total += product["price"] * qty
        if channel not in ("web", "mobile", "store"):
            raise ShopError(f"unknown channel {channel!r}")
        with self.db() as con:
            if customer_id is None:
                customer_id = self._rng.randint(1, con.execute("select max(customer_id) from raw.customers").fetchone()[0])
            if not con.execute("select 1 from raw.customers where customer_id = ?", [customer_id]).fetchone():
                raise ShopError(f"no customer {customer_id}", 404)
            return self._record_order(con, customer_id, round(total, 2), channel)

    def _record_order(self, con, customer_id: int, amount: float, channel: str) -> dict[str, Any]:
        events = self._get_state(con, "events", {})
        now = self.clock()
        if "ingestion_outage" in events:
            con.execute("insert into app.dead_letter values (?, ?, ?, ?)", [now, customer_id, amount, channel])
            queued = con.execute("select count(*) from app.dead_letter").fetchone()[0]
            return {"status": "queued", "message": "Order accepted; it will reach reporting once ingestion recovers.",
                    "amount": amount, "queued": queued}
        order_id = con.execute("select coalesce(max(order_id), 1000) + 1 from raw.orders").fetchone()[0]
        stored_customer, stored_amount = customer_id, amount
        faults = []
        if "cents_bug" in events:
            stored_amount, faults = round(amount * 100, 2), faults + ["cents"]
        if "guest_checkout" in events and self._rng.random() < GUEST_RATE:
            stored_customer, faults = None, faults + ["guest"]
        con.execute(f"insert into raw.orders (order_id, customer_id, ordered_at, amount, {self._channel_column(con)}) "
                    "values (?, ?, ?, ?, ?)", [order_id, stored_customer, now, stored_amount, channel])
        for fault in faults:
            con.execute("insert into app.fault_log values (?, ?, ?, ?)", [order_id, fault, customer_id, amount])
        return {"status": "accepted", "order_id": order_id, "amount": amount, "message": "Thank you for your order."}

    def recent_orders(self, limit: int = 15) -> list[dict[str, Any]]:
        with self.db() as con:
            col = self._channel_column(con)
            rows = con.execute(f"select order_id, customer_id, ordered_at, amount, {col} from raw.orders "
                               "order by ordered_at desc, order_id desc limit ?", [min(int(limit), 100)]).fetchall()
        return [{"order_id": r[0], "customer_id": r[1], "ordered_at": r[2].isoformat(sep=" "),
                 "amount": r[3], "channel": r[4]} for r in rows]

    # --- the pipeline and the dashboard finance reads ---------------------------------------

    def run_pipeline(self) -> dict[str, Any]:
        """Run the pipeline as its own process, like a production cron job, and remember how it went."""
        with self._lock:
            started = time.monotonic()
            script = PLUGIN / "pipeline" / "run_pipeline.py"
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run([self.python, str(script), "--db", self.db_path, "--log", str(self.log_path)],
                                  capture_output=True, text=True, timeout=300)
            lines, warnings = 0, []
            if self.log_path.is_file():
                with self.log_path.open(encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        lines += 1
                        if " WARNING " in line or " ERROR " in line:
                            warnings.append(line.strip()[:240])
            self.pipeline = {
                "last_run_at": self.clock().isoformat(sep=" "), "ok": proc.returncode == 0,
                "duration_ms": int((time.monotonic() - started) * 1000), "log_lines": lines, "warnings": warnings[:5],
                "message": "Pipeline finished" if proc.returncode == 0 else (proc.stderr.strip().splitlines() or ["failed"])[-1][:240],
            }
            return self.pipeline

    def revenue(self, days: int = 14) -> dict[str, Any]:
        """What the finance dashboard shows: revenue per day and channel from the mart."""
        days = max(2, min(int(days), 60))
        first = self.today() - timedelta(days=days - 1)
        with self.db() as con:
            if not con.execute("select count(*) from information_schema.tables where table_schema = 'mart'").fetchone()[0]:
                return {"days": [], "channels": [], "built": False}
            rows = con.execute("select day, channel, revenue from mart.daily_revenue where day >= ? order by 1, 2",
                               [first]).fetchall()
        by_day: dict[str, dict[str, float]] = {}
        for day, channel, revenue in rows:
            by_day.setdefault(day.isoformat(), {})[channel] = round(revenue, 2)
        channels = sorted({c for d in by_day.values() for c in d}, key=lambda c: (c == "unknown", c))
        series = []
        for i in range(days):
            day = (first + timedelta(days=i)).isoformat()
            parts = by_day.get(day, {})
            series.append({"day": day, "total": round(sum(parts.values()), 2), "by_channel": parts})
        return {"days": series, "channels": channels, "built": True}

    def state(self) -> dict[str, Any]:
        with self.db() as con:
            events = self._get_state(con, "events", {})
            has = self._has_orders(con)
            counts = {
                "raw_orders": con.execute("select count(*) from raw.orders").fetchone()[0] if has else 0,
                "orders_today": con.execute("select count(*) from raw.orders where cast(ordered_at as date) = ?",
                                            [self.today()]).fetchone()[0] if has else 0,
                "queued_orders": con.execute("select count(*) from app.dead_letter").fetchone()[0],
            }
            newest = con.execute("select max(ordered_at) from raw.orders").fetchone()[0] if has else None
            columns = [r[0] for r in con.execute("select column_name from information_schema.columns "
                                                 "where table_schema = 'raw' and table_name = 'orders' "
                                                 "order by ordinal_position").fetchall()]
            staged = con.execute("select count(*) from information_schema.tables where table_schema = 'staging'").fetchone()[0]
            counts["staged_orders"] = con.execute("select count(*) from staging.stg_orders").fetchone()[0] if staged else 0
        return {
            "now": self.clock().isoformat(sep=" "), "events": events, "counts": counts,
            "newest_order_at": newest.isoformat(sep=" ") if newest else None, "orders_columns": columns,
            "pipeline": self.pipeline,
        }

    def event_catalog(self) -> list[dict[str, Any]]:
        with self.db() as con:
            active = self._get_state(con, "events", {})
        return [{"id": key, **meta, "active": key in active, "since": active.get(key, {}).get("since")}
                for key, meta in EVENTS.items()]

    # --- incidents ------------------------------------------------------------------------

    def trigger(self, event: str) -> dict[str, Any]:
        if event not in EVENTS:
            raise ShopError(f"unknown event {event!r}", 404)
        with self.db() as con:
            events = self._get_state(con, "events", {})
            if event in events:
                raise ShopError(f"{EVENTS[event]['title']} is already happening", 409)
            today = self.today()
            detail = getattr(self, f"_start_{event}")(con, today)
            events[event] = {"since": self.clock().isoformat(sep=" "), **detail}
            self._set_state(con, "events", events)
        return {"event": event, "active": True, **detail}

    def roll_back(self, event: str) -> dict[str, Any]:
        if event not in EVENTS:
            raise ShopError(f"unknown event {event!r}", 404)
        with self.db() as con:
            events = self._get_state(con, "events", {})
            if event not in events:
                raise ShopError(f"{EVENTS[event]['title']} is not happening", 409)
            del events[event]
            self._set_state(con, "events", events)       # new orders are healthy from here on
            detail = getattr(self, f"_end_{event}")(con, self.today())
        return {"event": event, "active": False, **detail}

    # each _start_* returns detail for the UI; each _end_* repairs what that event broke

    def _start_duplicate_batch(self, con, today) -> dict[str, Any]:
        day = today - timedelta(days=3)
        before = con.execute("select count(*) from raw.orders").fetchone()[0]
        con.execute("insert into raw.orders select * from raw.orders where cast(ordered_at as date) = ?", [day])
        return {"day": day.isoformat(), "rows_added": con.execute("select count(*) from raw.orders").fetchone()[0] - before}

    def _end_duplicate_batch(self, con, today) -> dict[str, Any]:
        removed = con.execute(
            "delete from raw.orders where rowid in (select rowid from (select rowid, row_number() over "
            "(partition by order_id order by rowid) as n from raw.orders) where n > 1) returning 1").fetchall()
        return {"rows_removed": len(removed)}

    def _start_schema_rename(self, con, today) -> dict[str, Any]:
        con.execute("alter table raw.orders rename column channel to sales_channel")
        return {"renamed": "channel -> sales_channel"}

    def _end_schema_rename(self, con, today) -> dict[str, Any]:
        con.execute("alter table raw.orders rename column sales_channel to channel")
        return {"renamed": "sales_channel -> channel"}

    def _start_guest_checkout(self, con, today) -> dict[str, Any]:
        first = today - timedelta(days=3)
        con.execute("insert into app.fault_log select order_id, 'guest', customer_id, amount from raw.orders "
                    "where cast(ordered_at as date) >= ? and customer_id is not null and hash(order_id) % 10 < 4 "
                    "and order_id not in (select order_id from app.fault_log where fault = 'guest')", [first])
        hit = con.execute("update raw.orders set customer_id = null where order_id in "
                          "(select order_id from app.fault_log where fault = 'guest') returning 1").fetchall()
        return {"orders_without_customer": len(hit), "from_day": first.isoformat()}

    def _end_guest_checkout(self, con, today) -> dict[str, Any]:
        restored = con.execute(
            "update raw.orders as o set customer_id = l.orig_customer_id from app.fault_log as l "
            "where o.order_id = l.order_id and l.fault = 'guest' returning 1").fetchall()
        con.execute("delete from app.fault_log where fault = 'guest'")
        return {"customer_ids_restored": len(restored)}

    def _start_cents_bug(self, con, today) -> dict[str, Any]:
        first = today - timedelta(days=4)
        con.execute("insert into app.fault_log select order_id, 'cents', customer_id, amount from raw.orders "
                    "where cast(ordered_at as date) >= ? and order_id not in "
                    "(select order_id from app.fault_log where fault = 'cents')", [first])
        hit = con.execute("update raw.orders set amount = round(amount * 100, 2) where order_id in "
                          "(select order_id from app.fault_log where fault = 'cents') returning 1").fetchall()
        return {"orders_affected": len(hit), "from_day": first.isoformat()}

    def _end_cents_bug(self, con, today) -> dict[str, Any]:
        restored = con.execute(
            "update raw.orders as o set amount = l.orig_amount from app.fault_log as l "
            "where o.order_id = l.order_id and l.fault = 'cents' returning 1").fetchall()
        con.execute("delete from app.fault_log where fault = 'cents'")
        return {"amounts_restored": len(restored)}

    def _start_ingestion_outage(self, con, today) -> dict[str, Any]:
        first = today - timedelta(days=2)
        con.execute("delete from app.outage_backup")
        con.execute("insert into app.outage_backup select * from raw.orders where cast(ordered_at as date) >= ?", [first])
        gone = con.execute("delete from raw.orders where cast(ordered_at as date) >= ? returning 1", [first]).fetchall()
        return {"orders_missing": len(gone), "from_day": first.isoformat()}

    def _end_ingestion_outage(self, con, today) -> dict[str, Any]:
        backfilled = con.execute("select count(*) from app.outage_backup").fetchone()[0]
        con.execute("insert into raw.orders select * from app.outage_backup")
        con.execute("delete from app.outage_backup")
        queued = con.execute("select queued_at, customer_id, amount, channel from app.dead_letter order by queued_at").fetchall()
        col = self._channel_column(con)
        next_id = con.execute("select coalesce(max(order_id), 1000) + 1 from raw.orders").fetchone()[0]
        for i, (queued_at, customer_id, amount, channel) in enumerate(queued):
            con.execute(f"insert into raw.orders (order_id, customer_id, ordered_at, amount, {col}) values (?, ?, ?, ?, ?)",
                        [next_id + i, customer_id, queued_at, amount, channel])
        con.execute("delete from app.dead_letter")
        return {"orders_backfilled": backfilled, "queued_orders_replayed": len(queued)}

    # --- demo housekeeping -------------------------------------------------------------------

    def reset(self) -> dict[str, Any]:
        """Back to healthy data that runs up to now, with the pipeline rebuilt."""
        with self._lock:
            seed = PLUGIN / "seed" / "seed_data.py"
            for attempt in range(10):
                proc = subprocess.run([self.python, str(seed), "--db", self.db_path, "--scenario", "S0",
                                       "--as-of", self.clock().isoformat()],
                                      capture_output=True, text=True, timeout=300)
                if proc.returncode == 0:
                    break
                time.sleep(0.5)          # a reader may still have the file open
            else:
                raise ShopError("could not reseed the database: " + (proc.stderr.strip().splitlines() or ["?"])[-1], 500)
            return self.run_pipeline()
