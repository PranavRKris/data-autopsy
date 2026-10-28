"""Acme Shop pipeline: raw orders + customers -> staging.stg_orders -> mart.daily_revenue.

usage: run_pipeline.py --db acme.duckdb [--log logs/pipeline_run.log]

Writes a long, noisy log (one line per validated row), which is the point of the context-window demo.
This file imports nothing from the Pipeline Autopsy platform.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
log = logging.getLogger("acme.pipeline")


def connect(db_path: str, wait_seconds: float = 20.0):
    """Wait for another process (a reader, or the shop app) to let go of the database file."""
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return duckdb.connect(db_path)
        except duckdb.IOException as exc:
            text = str(exc).lower()
            busy = any(m in text for m in ("lock", "being used by another process", "cannot access the file"))
            if not busy or time.monotonic() > deadline:
                raise
            time.sleep(0.25)


def run(db_path: str, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_path, filemode="w", level=logging.DEBUG,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    con = connect(db_path)
    try:
        log.info("pipeline started, database %s", db_path)
        raw_cols = [r[0] for r in con.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'raw' and table_name = 'orders'").fetchall()]
        log.info("raw.orders columns: %s", raw_cols)

        rows = con.execute("select order_id, customer_id, ordered_at, amount from raw.orders order by order_id").fetchall()
        for order_id, customer_id, ordered_at, amount in rows:
            log.debug("validated order_id=%s customer_id=%s ordered_at=%s amount=%s parser=v2 ok", order_id,
                      customer_id, ordered_at, amount)
        log.info("validated %d raw order rows", len(rows))

        con.execute("create schema if not exists staging")
        con.execute("create schema if not exists mart")

        if "channel" in raw_cols:
            channel_expr = "o.channel"
        else:
            log.warning("column 'channel' not found in raw.orders; defaulting channel to 'unknown'")
            channel_expr = "'unknown'"
        con.execute((HERE / "sql" / "stg_orders.sql").read_text(encoding="utf-8").format(channel_expr=channel_expr))
        staged = con.execute("select count(*) from staging.stg_orders").fetchone()[0]
        log.info("staging.stg_orders built: %d rows (%d raw rows did not join to a customer)", staged, len(rows) - staged)

        con.execute((HERE / "sql" / "daily_revenue.sql").read_text(encoding="utf-8"))
        for day, channel, revenue in con.execute(
                "select day, channel, revenue from mart.daily_revenue order by 1, 2").fetchall():
            log.debug("mart row day=%s channel=%s revenue=%.2f", day, channel, revenue)
        marts = con.execute("select count(*) from mart.daily_revenue").fetchone()[0]
        log.info("mart.daily_revenue built: %d rows", marts)
        log.info("pipeline finished OK")
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--log", default=str(HERE.parent / "logs" / "pipeline_run.log"))
    args = parser.parse_args()
    run(args.db, Path(args.log))
    print(f"pipeline finished, log at {args.log}")


if __name__ == "__main__":
    main()
