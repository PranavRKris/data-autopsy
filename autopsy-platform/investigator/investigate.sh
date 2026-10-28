#!/usr/bin/env bash
# usage: investigate.sh <manifest> <report-name> [dataset]
# Runs one headless Bob investigation in the Incident Investigator mode and saves the final answer
# to reports/incident_<project>_<report-name>.md.
# Honours AUTOPSY_PYTHON (interpreter with autopsy installed) and BOB (the Bob Shell command).
set -euo pipefail

MANIFEST="$(realpath "${1:?usage: investigate.sh <manifest> <report-name> [dataset]}")"
if command -v cygpath >/dev/null 2>&1; then MANIFEST="$(cygpath -m "$MANIFEST")"; fi   # Git Bash on Windows
NAME="${2:?usage: investigate.sh <manifest> <report-name> [dataset]}"
PY="${AUTOPSY_PYTHON:-python}"
BOB="${BOB:-bob}"

cd "$(dirname "$0")/.."                         # the .bob/ rules and reports/ live in the platform root
export AUTOPSY_MANIFEST="$MANIFEST"             # the MCP server reads this
PROJECT="$("$PY" -m autopsy.cli project-name "$MANIFEST")"
START="${3:-its business-visible datasets}"

mkdir -p reports
"$BOB" --chat-mode=incident-investigator \
    -p "Investigate why the output of project $PROJECT looks wrong, starting from $START. Use only the autopsy tools." \
    --hide-intermediary-output > "reports/incident_${PROJECT}_${NAME}.md"
echo "report written to reports/incident_${PROJECT}_${NAME}.md"
