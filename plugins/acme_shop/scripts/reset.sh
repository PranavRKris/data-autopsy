#!/usr/bin/env bash
# usage: reset.sh <S0|S1|S2|S3|S4|S5>
# Deletes the database, reseeds one scenario and reruns the pipeline, so every demo run is repeatable.
# Honours ACME_DB_PATH, ACME_AS_OF (pin the data's end time) and AUTOPSY_PYTHON (interpreter with duckdb).
set -euo pipefail

SCENARIO="${1:?usage: reset.sh <S0..S5>}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PY="${AUTOPSY_PYTHON:-python}"
DB="${ACME_DB_PATH:-$HERE/acme.duckdb}"

rm -f "$DB" "$DB.wal"
"$PY" "$HERE/seed/seed_data.py" --db "$DB" --scenario "$SCENARIO"
"$PY" "$HERE/pipeline/run_pipeline.py" --db "$DB" --log "$HERE/logs/pipeline_run.log"
