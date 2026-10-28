# Acme Shop (test plug-in)

A small fake online store, built separately from the platform as if by another team. It owns its database,
its pipeline and its manifest, and imports nothing from `autopsy/`. Its only job is to prove the platform finds
root causes it was never written for.

```
manifest.yaml                 connector, datasets, roles, lineage, limits (the only file the platform reads)
app/                          the live shop: storefront, finance dashboard, operations and incident lab (see "The live demo")
demo/run_demo.py              one command that starts the shop and Pipeline Autopsy together
seed/seed_data.py             30 days of clean data plus five failure scenarios
pipeline/run_pipeline.py      raw.orders + raw.customers -> staging.stg_orders -> mart.daily_revenue
pipeline/sql/                 the staging and mart SQL
logs/pipeline_run.log         long, noisy log (one line per row) for the context-window demo
expected/expected_results.yaml  the known root cause per scenario, used by `autopsy grade`
scripts/reset.sh              delete the db, reseed one scenario, rerun the pipeline
scripts/run_all.sh            baseline, then every scenario: inject, investigate, grade, tally
scripts/export_sqlite.py      copy the database to SQLite for the swap-the-database demo
```

| Logical dataset | Source table | Feeds | Business visible |
|---|---|---|---|
| `orders_raw` | `raw.orders` | `orders_clean` | no |
| `customers_raw` | `raw.customers` | `orders_clean` | no |
| `orders_clean` | `staging.stg_orders` | `daily_revenue` | no |
| `daily_revenue` | `mart.daily_revenue` | none | yes |

| ID | What breaks upstream | Symptom in `daily_revenue` | Root | Sev |
|---|---|---|---|---|
| S0 | nothing | none | none | none |
| S1 | one day's batch of orders is loaded twice | that day's revenue doubles | `orders_raw` / `find_duplicates` | SEV1 |
| S2 | `channel` is renamed `sales_channel` upstream; staging fills "unknown" | all revenue moves to channel "unknown" | `orders_raw` / `check_schema` | SEV2 |
| S3 | 40% of the last 4 days' orders arrive with a null `customer_id`; the join drops them | revenue about 40% low | `orders_raw` / `profile_dataset` | SEV2 |
| S4 | no orders loaded for the last 3 days | last 3 days missing | `orders_raw` / `check_freshness` | SEV3 |
| S5 | amounts of the last 5 days arrive in cents | revenue 100x too high | `orders_raw` / `profile_dataset` | SEV1 |

## The live demo

One command starts a believable shop and a Pipeline Autopsy that is already watching it:

```bash
python plugins/acme_shop/demo/run_demo.py          # with the venv that has the platform installed
```

It reseeds healthy data (into `demo/data/`, never your own database), starts Pipeline Autopsy on :8765 and imports this
manifest through its HTTP API, learns the baseline from the healthy data, turns on a one-minute schedule, then starts
the shop on :8780 and opens both. Ctrl+C stops everything.

In the shop, open **Operations, Incident lab** and press *Make it happen* on an incident. The shop rebuilds its reports,
the **Finance** tab visibly goes wrong, and within a minute (or at once with *Run checks*) Pipeline Autopsy opens an
incident that names the cause. *Roll back* in the shop and the incident resolves on the next check.

| Incident in the shop | What the business sees | What Autopsy should say |
|---|---|---|
| Partner feed replays a batch | one day of revenue doubles | `orders_raw` / `find_duplicates`, SEV1 |
| Checkout v2.4 renames a column | all revenue moves to an "unknown" channel | `orders_raw` / `check_schema`, SEV2 |
| Mobile release adds guest checkout | revenue about 40% low, no errors | `orders_raw` / `profile_dataset`, SEV2 |
| Order ingestion goes down | the last three days are missing | `orders_raw` / `check_freshness`, SEV3 |
| Pricing deploy sends cents | revenue 100x too high | `orders_raw` / `profile_dataset`, SEV1 |

The shop is a separate application with its own database and pipeline; the platform only reads the database through
`manifest.yaml`. Each incident also affects orders placed while it is live (a sticky incident) and rewrites the last few
days as if it had been live since then, because a demo cannot wait three days. Rolling back restores the original
values from the shop's own bookkeeping (the `app` schema, which the manifest never mentions).
`autopsy-platform/tests/test_acme_app.py` triggers every incident, checks the platform's verdict against
`expected/expected_results.yaml`, rolls it back, and checks the platform goes clean.

## Running it

```bash
export AUTOPSY_PYTHON="$(which python)"          # an interpreter with duckdb installed
export ACME_DB_PATH=plugins/acme_shop/acme.duckdb

plugins/acme_shop/scripts/reset.sh S0                    # healthy
autopsy validate plugins/acme_shop/manifest.yaml
autopsy baseline plugins/acme_shop/manifest.yaml         # learned once; reset.sh never relearns it

plugins/acme_shop/scripts/reset.sh S5                    # inject one failure
autopsy-platform/investigator/investigate.sh plugins/acme_shop/manifest.yaml s5
autopsy grade autopsy-platform/reports/incident_acme_shop_s5.md plugins/acme_shop/expected/expected_results.yaml S5
```

The data runs up to "now" when seeded, so reset right before investigating; pin it with `ACME_AS_OF` (seed) and
`AUTOPSY_NOW` (platform) for repeatable output.

## The swap demos (each leaves `git diff autopsy/` empty)

- **Swap the schema.** Rename `ordered_at` to `created_ts` in the seed and pipeline, change `orders_raw`'s
  `event_time` line in the manifest, rerun S5: same root cause. Automated in `tests/test_swaps.py`.
- **Swap the project.** `plugins/sensor_readings/` has one dataset, a ten-line manifest and one stale-feed scenario.
- **Swap the database.** `scripts/export_sqlite.py --db acme.duckdb --out acme.sqlite`, then use
  `connector: sqlite` with `path_env` pointing at the file. The `source` values do not change.

## Context-window demo (Chapter 4)

`logs/pipeline_run.log` is thousands of lines long, and in S2 the only hint of the cause is one `WARNING` line
buried in it. The platform's tools never read it. Run once with a rule that forbids opening logs in full (as
`.bob/rules/01-safety.md` does) and once without, and note the difference in tokens and in the answer.
