#!/usr/bin/env bash
# usage: run_all.sh [bob|reference]      (default: bob)
# The whole demo: healthy baseline, then each scenario is injected, investigated, graded, and tallied.
#   bob        runs the headless Bob investigation (investigator/investigate.sh)
#   reference  runs the deterministic reference investigator (no Bob needed)
# Honours AUTOPSY_PYTHON, BOB, ACME_DB_PATH, and the pinned clocks ACME_AS_OF / AUTOPSY_NOW.
set -uo pipefail

MODE="${1:-bob}"
ACME="$(cd "$(dirname "$0")/.." && pwd)"
PLATFORM="$(cd "$ACME/../../autopsy-platform" && pwd)"
PY="${AUTOPSY_PYTHON:-python}"
export ACME_DB_PATH="${ACME_DB_PATH:-$ACME/acme.duckdb}"
cd "$PLATFORM"

bash "$ACME/scripts/reset.sh" S0 >/dev/null
"$PY" -m autopsy.cli validate "$ACME/manifest.yaml" || exit 1
"$PY" -m autopsy.cli baseline "$ACME/manifest.yaml" || exit 1       # learned once, from the healthy data

pass=0; total=0; table=""
for scenario in S0 S1 S2 S3 S4 S5; do
  name="$(echo "$scenario" | tr 'A-Z' 'a-z')"
  report="reports/incident_acme_shop_${name}.md"
  bash "$ACME/scripts/reset.sh" "$scenario" >/dev/null
  if [ "$MODE" = "reference" ]; then
    mkdir -p reports
    "$PY" -m autopsy.cli investigate "$ACME/manifest.yaml" --output "$report"
  else
    bash investigator/investigate.sh "$ACME/manifest.yaml" "$name" >/dev/null
  fi
  result="$("$PY" -m autopsy.cli grade "$report" "$ACME/expected/expected_results.yaml" "$scenario")" && ok=PASS || ok=FAIL
  [ "$ok" = PASS ] && pass=$((pass + 1))
  total=$((total + 1))
  table="${table}| ${scenario} | ${ok} | ${result#*). } |"$'\n'
done

echo
echo "| Scenario | Result | Detail |"
echo "|----------|--------|--------|"
printf "%s" "$table"
echo
echo "$pass of $total scenarios correct (investigator: $MODE)"
[ "$pass" -eq "$total" ]
