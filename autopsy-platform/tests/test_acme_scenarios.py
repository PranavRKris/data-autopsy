"""The platform's "done means": every seeded Acme Shop failure gets the right root cause from the manifest alone.

Runs the plug-in's own seed and pipeline scripts as subprocesses, then investigates with the reference
investigator (the same tool functions Bob calls) and grades the report with `autopsy grade`.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from autopsy.core.baseline import learn_baseline, save_baseline
from autopsy.core.manifest import load_manifest, validate_against
from autopsy.core.registry import create_connector
from autopsy.grade import grade_report, load_expected
from autopsy.investigate import investigate
from autopsy.mcp_server.tools import Tools

ACME = Path(__file__).resolve().parents[2] / "plugins" / "acme_shop"
AS_OF = datetime(2026, 10, 28, 12, 0, 0)
NOW = datetime(2026, 10, 28, 13, 0, 0)

pytestmark = pytest.mark.skipif(not ACME.is_dir(), reason="plugins/acme_shop is not checked out next to the platform")


def build(db: Path, scenario: str, log: Path) -> None:
    for script, extra in (("seed/seed_data.py", ["--scenario", scenario, "--as-of", AS_OF.isoformat()]),
                          ("pipeline/run_pipeline.py", ["--log", str(log)])):
        subprocess.run([sys.executable, str(ACME / script), "--db", str(db), *extra], check=True, capture_output=True)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("acme")
    db, state = root / "acme.duckdb", root / "state"
    patch = pytest.MonkeyPatch()
    patch.setenv("ACME_DB_PATH", str(db))
    manifest = load_manifest(ACME / "manifest.yaml")

    build(db, "S0", root / "log.txt")          # the baseline is learned once, from healthy data
    connector = create_connector(manifest.connector, manifest.connection)
    assert not [i for i in validate_against(manifest, connector) if i.level == "error"]
    save_baseline(learn_baseline(manifest, connector, NOW), state)
    connector.close()
    yield manifest, db, state, root
    patch.undo()


@pytest.mark.parametrize("scenario", ["S0", "S1", "S2", "S3", "S4", "S5"])
def test_scenario_names_the_expected_root_cause(env, scenario):
    manifest, db, state, root = env
    build(db, scenario, root / "log.txt")
    tools = Tools(manifest, state_dir=state, now=NOW)
    try:
        inv = investigate(tools)
    finally:
        tools.close()

    expected = load_expected(ACME / "expected" / "expected_results.yaml", scenario)
    grade = grade_report(inv.report, expected, scenario)
    assert grade.root_ok, f"{grade.line()}\n{inv.report}"
    assert grade.severity_ok, f"{grade.line()}\n{inv.report}"


def test_healthy_data_has_no_failing_check_anywhere(env):
    manifest, db, state, root = env
    build(db, "S0", root / "log.txt")
    tools = Tools(manifest, state_dir=state, now=NOW)
    try:
        inv = investigate(tools)
    finally:
        tools.close()
    bad = {(d, t): f["summary"] for d, fs in inv.findings.items() for t, f in fs.items() if f.get("status") != "ok"}
    assert not bad
