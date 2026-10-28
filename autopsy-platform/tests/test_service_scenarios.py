"""The service finds the same root causes the reference investigator does, from an imported manifest alone.

No plug-in code runs inside the service: the plug-in's manifest is imported as text, exactly as a person would paste it,
and each scenario is built by the plug-in's own scripts and then noticed by a monitor run.
"""
from __future__ import annotations

import pytest

from autopsy.grade import grade_report, load_expected
from autopsy.service.engine import Service
from test_acme_scenarios import ACME, NOW, build

pytestmark = pytest.mark.skipif(not ACME.is_dir(), reason="plugins/acme_shop is not checked out next to the platform")


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    root = tmp_path_factory.mktemp("acme_service")
    patch = pytest.MonkeyPatch()
    patch.setenv("ACME_DB_PATH", str(root / "acme.duckdb"))
    patch.setenv("AUTOPSY_NOW", NOW.isoformat())
    build(root / "acme.duckdb", "S0", root / "log.txt")
    svc = Service(root / "state")
    imported = svc.import_manifest((ACME / "manifest.yaml").read_text(encoding="utf-8"))
    assert imported["validation"]["ok"], imported["validation"]
    svc.learn_baseline(imported["project"]["name"])
    yield svc, imported["project"]["name"], root
    patch.undo()


@pytest.mark.parametrize("scenario", ["S0", "S1", "S2", "S3", "S4", "S5"])
def test_a_monitor_run_opens_the_expected_incident(service, scenario):
    svc, project, root = service
    build(root / "acme.duckdb", scenario, root / "log.txt")
    run = svc.run(project, "monitor")
    expected = load_expected(ACME / "expected" / "expected_results.yaml", scenario)

    open_now = svc.list_incidents(project=project)
    if expected["root_dataset"] == "none":
        assert run["status"] == "ok", run["summary"]
        assert open_now == []
        return

    assert run["status"] == "fail", run["summary"]
    assert len(open_now) == 1, [(i["root_dataset"], i["root_check"]) for i in open_now]
    incident = open_now[0]
    checks = expected["root_check"] if isinstance(expected["root_check"], list) else [expected["root_check"]]
    assert incident["root_dataset"] == expected["root_dataset"] and incident["root_check"] in checks
    assert incident["severity"] == expected["severity"]

    report = svc.get_incident(incident["id"])["run"]["report"]
    grade = grade_report(report, expected, scenario)
    assert grade.root_ok and grade.severity_ok, f"{grade.line()}\n{report}"


def test_the_previous_incident_is_resolved_when_the_data_is_fixed(service):
    svc, project, root = service
    build(root / "acme.duckdb", "S1", root / "log.txt")
    svc.run(project, "monitor")
    assert len(svc.list_incidents(project=project)) == 1
    build(root / "acme.duckdb", "S0", root / "log.txt")
    assert svc.run(project, "monitor")["status"] == "ok"
    assert svc.list_incidents(project=project) == []
    assert svc.list_incidents(project=project, status="resolved")
