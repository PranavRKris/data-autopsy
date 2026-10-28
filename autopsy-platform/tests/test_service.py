"""The service: connections, mapping, runs, incidents, schedule and the HTTP layer, on a small generic database."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta

import duckdb
import pytest
import yaml
from starlette.testclient import TestClient

from autopsy.core.manifest import load_manifest
from autopsy.service.app import create_app
from autopsy.service.engine import Service, ServiceError

NOW = datetime(2026, 10, 28, 13, 0, 0)

MAPPING = [
    {"name": "feed", "source": "feed", "feeds": ["rollup"],
     "roles": {"event_time": "seen_at", "key": ["id"], "measure": ["qty"], "required": ["ref"]}},
    {"name": "rollup", "source": "rollup", "business_visible": True,
     "roles": {"event_time": "day", "measure": ["total"]}},
]


def build_database(path, duplicate_a_day: bool = False) -> None:
    """20 days of 10 rows a day up to the pinned 'now', and one rollup row a day."""
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    con.execute("create table feed (id integer, seen_at timestamp, qty double, ref integer)")
    con.execute("create table rollup (day date, total double)")
    next_id, feed, rollup = 1, [], []
    for back in range(19, -1, -1):
        day = NOW.date() - timedelta(days=back)
        n = 5 if back == 0 else 10
        for k in range(n):
            feed.append([next_id, datetime(day.year, day.month, day.day, 1 + k), 10.0 + k, 100 + k])
            next_id += 1
        rollup.append([day, 10.0 * n])
    con.executemany("insert into feed values (?, ?, ?, ?)", feed)
    con.executemany("insert into rollup values (?, ?)", rollup)
    if duplicate_a_day:
        day = NOW.date() - timedelta(days=3)
        con.execute("insert into feed select id, seen_at, qty, ref from feed where cast(seen_at as date) = ?", [day])
    con.close()


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_NOW", NOW.isoformat())
    db = tmp_path / "w.duckdb"
    build_database(db)
    svc = Service(tmp_path / "state")
    connection = svc.create_connection("warehouse", "duckdb", {"path": str(db)})
    return svc, db, connection, tmp_path


@pytest.fixture
def project(world):
    svc, db, connection, _ = world
    svc.save_project("demo", connection["id"], MAPPING)
    svc.learn_baseline("demo")
    return svc, db, connection


# --- connections --------------------------------------------------------------------------

def test_connectors_describe_their_forms(world):
    svc = world[0]
    by_name = {c["name"]: c for c in svc.connectors()}
    assert set(by_name) >= {"duckdb", "sqlite", "files", "postgres"}
    assert any(f["type"] == "secret" for f in by_name["postgres"]["fields"])
    assert by_name["duckdb"]["available"] is True
    assert "live server" in by_name["postgres"]["verified"]       # the unverified connector says so


def test_secrets_are_stored_apart_and_never_returned(tmp_path):
    svc = Service(tmp_path / "state")
    made = svc.create_connection("pg", "postgres", {"host": "db.internal", "database": "d", "user": "ro"},
                                 {"password": "s3cret-value"})
    assert "s3cret-value" not in json.dumps(made) and made["secrets_set"] == ["password"]
    env_name = made["config"]["password_env"]
    assert os.environ[env_name] == "s3cret-value"
    assert "s3cret-value" not in json.dumps(svc.list_connections())
    assert "s3cret-value" in (tmp_path / "state" / "secrets.json").read_text()   # only here, and only here
    assert "s3cret-value" not in (tmp_path / "state" / "service.db").read_bytes().decode("latin-1")
    svc.delete_connection(made["id"])
    assert env_name not in os.environ and "s3cret" not in (tmp_path / "state" / "secrets.json").read_text()


def test_blank_secret_on_edit_keeps_the_stored_value(tmp_path):
    svc = Service(tmp_path / "state")
    made = svc.create_connection("pg", "postgres", {"host": "h", "database": "d", "user": "u"}, {"password": "one"})
    env_name = made["config"]["password_env"]
    svc.update_connection(made["id"], "pg", {"host": "h2", "database": "d", "user": "u"}, {"password": ""})
    assert os.environ[env_name] == "one" and svc.get_connection(made["id"])["config"]["host"] == "h2"
    svc.update_connection(made["id"], None, {"host": "h2", "database": "d", "user": "u"}, {"password": "two"})
    assert os.environ[env_name] == "two"


def test_connection_validation(tmp_path):
    svc = Service(tmp_path / "state")
    with pytest.raises(ServiceError) as e:
        svc.create_connection("x", "duckdb", {})
    assert e.value.status == 422 and e.value.extra["field"] == "path"
    with pytest.raises(ServiceError, match="unknown setting"):
        svc.create_connection("x", "duckdb", {"path": "a", "password": "inline"})
    with pytest.raises(ServiceError, match="unknown connector"):
        svc.create_connection("x", "nonesuch", {})
    svc.create_connection("same", "duckdb", {"path": "a"})
    with pytest.raises(ServiceError) as e:
        svc.create_connection("same", "duckdb", {"path": "b"})
    assert e.value.status == 409


def test_testing_a_connection_reports_instead_of_raising(world):
    svc, db, _, tmp_path = world
    bad = svc.test_connection("duckdb", {"path": str(tmp_path / "missing.duckdb")})
    assert bad["ok"] is False and "not found" in bad["message"]
    good = svc.test_connection("duckdb", {"path": str(db)})
    assert good["ok"] and {d["name"] for d in good["datasets"]} == {"feed", "rollup"}


def test_a_driver_failure_is_reported_in_the_form_not_as_a_500(tmp_path, monkeypatch):
    psycopg = pytest.importorskip("psycopg")

    def refuse(**kwargs):
        raise psycopg.OperationalError("connection refused\nsecond line")

    monkeypatch.setattr(psycopg, "connect", refuse)
    got = Service(tmp_path / "state").test_connection("postgres", {"host": "h", "database": "d", "user": "u"})
    assert got["ok"] is False and got["code"] == "connection_failed" and "refused" in got["message"]


def test_the_files_connector_works_through_the_service(tmp_path):
    folder = tmp_path / "exports"
    folder.mkdir()
    (folder / "events.csv").write_text("id,at,qty\n1,2026-10-01 08:00:00,5\n2,2026-10-02 09:00:00,7\n", encoding="utf-8")
    svc = Service(tmp_path / "state")
    made = svc.create_connection("exports", "files", {"path": str(folder)})
    schema = svc.connection_schema(made["id"])
    assert [d["name"] for d in schema["datasets"]] == ["events"]
    assert svc.sample(made["id"], "events")["rows"][0]["id"] == 1
    assert svc.suggest(made["id"], ["events"])["suggestions"]["events"]["event_time"] == "at"   # a reserved word, quoted by the connector


# --- mapping ------------------------------------------------------------------------------

def test_suggestions_pick_roles_from_types_and_uniqueness(world):
    svc, _, connection, _ = world
    got = svc.suggest(connection["id"], ["feed", "rollup"])["suggestions"]
    assert got["feed"]["event_time"] == "seen_at" and got["feed"]["key"] == ["id"]
    assert got["feed"]["measure"][0] == "qty" and "seen_at" not in got["feed"]["measure"]
    assert "ref" in got["feed"]["measure"] + got["feed"]["required"] and got["feed"]["rows"] == 195
    assert got["rollup"]["measure"] == ["total"] and got["rollup"]["event_time"] == "day"


def test_a_project_is_an_ordinary_manifest(project):
    svc, _, _ = project
    path = svc.manifest_path("demo")
    manifest = load_manifest(path)                       # the CLI and Bob read the same file
    assert [d.name for d in manifest.datasets] == ["feed", "rollup"] and manifest.upstream("rollup") == ["feed"]
    assert "password" not in path.read_text().lower()
    assert yaml.safe_load(svc.manifest_yaml("demo"))["project"] == "demo"
    assert svc.validate_project("demo")["ok"]


def test_a_mapping_that_does_not_match_the_database_is_refused_with_issues(world):
    svc, _, connection, _ = world
    broken = [{**MAPPING[0], "roles": {**MAPPING[0]["roles"], "measure": ["no_such_column"]}}, MAPPING[1]]
    with pytest.raises(ServiceError) as e:
        svc.save_project("demo", connection["id"], broken)
    assert e.value.status == 422 and e.value.code == "mapping_mismatch"
    assert any("no_such_column" in i["message"] for i in e.value.extra["issues"])
    assert svc.store.rows("select * from projects") == []


def test_lineage_cycles_and_duplicate_names_are_refused(world):
    svc, _, connection, _ = world
    cyc = [{**MAPPING[0]}, {**MAPPING[1], "feeds": ["feed"]}]
    with pytest.raises(ServiceError, match="cycle"):
        svc.save_project("demo", connection["id"], cyc)
    svc.save_project("demo", connection["id"], MAPPING)
    with pytest.raises(ServiceError) as e:
        svc.save_project("demo", connection["id"], MAPPING)
    assert e.value.status == 409


def test_a_used_connection_cannot_be_deleted_and_deleting_a_project_cleans_up(project):
    svc, _, connection = project
    with pytest.raises(ServiceError, match="demo"):
        svc.delete_connection(connection["id"])
    svc.run("demo")
    svc.delete_project("demo")
    assert not svc.manifest_path("demo").exists() and not (svc.state_dir / "demo.json").exists()
    assert svc.store.rows("select * from runs") == [] and svc.store.rows("select * from findings") == []
    svc.delete_connection(connection["id"])


def test_importing_a_manifest_brings_its_connection_along(world, tmp_path):
    svc, db, _, _ = world
    text = yaml.safe_dump({"project": "imported", "connector": "duckdb", "connection": {"path": str(db)},
                           "datasets": MAPPING})
    got = svc.import_manifest(text)
    assert got["validation"]["ok"] and got["project"]["name"] == "imported"
    with pytest.raises(ServiceError) as e:
        svc.import_manifest(text)
    assert e.value.status == 409
    leaky = yaml.safe_dump({"project": "leaky", "connector": "postgres",
                            "connection": {"host": "h", "password": "inline"}, "datasets": MAPPING})
    with pytest.raises(ServiceError, match="secret"):
        svc.import_manifest(leaky)


# --- runs and incidents -------------------------------------------------------------------

def test_a_healthy_database_has_no_incident(project):
    svc, _, _ = project
    run = svc.run("demo")
    assert run["status"] == "ok", run["summary"]
    assert run["counts"]["fail"] == 0 and run["findings"]
    assert {f["dataset"] for f in run["findings"]} == {"feed", "rollup"}
    assert svc.list_incidents() == []


def test_incident_lifecycle_open_recur_resolve(project):
    svc, db, _ = project
    build_database(db, duplicate_a_day=True)
    first = svc.run("demo")
    assert first["status"] == "fail"
    (incident,) = svc.list_incidents()
    assert (incident["root_dataset"], incident["root_check"]) == ("feed", "find_duplicates")
    assert incident["severity"] == "SEV1" and incident["occurrences"] == 1

    svc.run("demo")
    (again,) = svc.list_incidents()
    assert again["id"] == incident["id"] and again["occurrences"] == 2          # same cause, same incident

    detail = svc.get_incident(incident["id"])
    assert "feed" in detail["run"]["report"] and detail["run"]["root_check"] == "find_duplicates"
    assert svc.acknowledge(incident["id"], True)["acknowledged"] is True

    build_database(db)
    assert svc.run("demo")["status"] == "ok"
    assert svc.list_incidents() == []
    (resolved,) = svc.list_incidents(status="resolved")
    assert resolved["id"] == incident["id"] and resolved["resolved_at"]


def test_a_manual_investigation_never_resolves_other_incidents(project):
    svc, db, _ = project
    build_database(db, duplicate_a_day=True)
    svc.run("demo")
    build_database(db)
    svc.run("demo", "investigation", dataset="rollup", trigger="manual")
    assert len(svc.list_incidents()) == 1              # only a full monitor sweep may say a cause is gone


def test_findings_are_persisted_and_status_reads_the_latest(project):
    svc, db, _ = project
    svc.run("demo")
    build_database(db, duplicate_a_day=True)
    svc.run("demo")
    status = svc.project_status("demo")
    assert status["overall"] == "fail" and status["datasets"]["feed"]["find_duplicates"]["status"] == "fail"
    history = svc.history("demo")
    assert len(history["runs"]) == 2
    cell = next(c for c in history["cells"] if (c["dataset"], c["tool"]) == ("feed", "find_duplicates"))
    assert cell["statuses"] == ["ok", "fail"]


def test_a_database_that_cannot_be_reached_is_an_error_not_a_failure(project):
    svc, db, _ = project
    db.unlink()
    run = svc.run("demo")
    assert run["status"] == "error" and "not found" in run["summary"]
    assert svc.list_incidents() == []


def test_an_unknown_dataset_or_kind_is_refused(project):
    svc, _, _ = project
    with pytest.raises(ServiceError) as e:
        svc.run("demo", "investigation", dataset="nope")
    assert e.value.status == 404
    with pytest.raises(ServiceError) as e:
        svc.run("demo", "dance")
    assert e.value.status == 422


def test_two_runs_at_once_are_refused(project):
    svc, _, _ = project
    held = svc._lock("demo")
    held.acquire()
    try:
        with pytest.raises(ServiceError) as e:
            svc.run("demo")
        assert e.value.status == 409
    finally:
        held.release()


def test_lineage_and_trend_views(project):
    svc, db, _ = project
    build_database(db, duplicate_a_day=True)
    svc.run("demo")
    graph = svc.lineage("demo")
    nodes = {n["name"]: n for n in graph["nodes"]}
    assert graph["edges"] == [{"from": "feed", "to": "rollup"}]
    assert nodes["feed"]["level"] == 0 and nodes["rollup"]["level"] == 1
    assert nodes["feed"]["incident_root"] is True and nodes["rollup"]["business_visible"] is True
    trend = svc.trend("demo", "feed", days=14)
    assert len(trend["days"]) == len(trend["volume"]) == 14 and trend["days"][-1] == "2026-10-28"
    assert max(trend["volume"]) == 20 and trend["volume"][-1] == 5                 # the doubled day, and a partial today
    assert set(trend["columns"]) == {"qty", "ref"} and trend["baseline"]["volume"]["median"] == 10


# --- schedule -----------------------------------------------------------------------------

def test_the_schedule_runs_only_what_is_due(project):
    svc, _, _ = project
    clock = {"now": datetime(2026, 10, 28, 13, 0, 0)}
    svc.clock = lambda: clock["now"]
    assert svc.set_schedule("demo", True, 15)["next_run_at"] == "2026-10-28T13:15:00Z"
    assert svc.run_due() == []
    clock["now"] += timedelta(minutes=16)
    assert svc.run_due() == ["demo"]
    detail = svc.project_detail("demo")
    assert detail["last_run"]["trigger"] == "schedule"
    assert detail["schedule"]["next_run_at"] == "2026-10-28T13:31:00Z"
    svc.set_schedule("demo", False, 15)
    clock["now"] += timedelta(hours=2)
    assert svc.run_due() == []
    with pytest.raises(ServiceError):
        svc.set_schedule("demo", True, 0)


def test_the_scheduler_thread_runs_due_projects(project):
    from autopsy.service.scheduler import Scheduler

    svc, _, _ = project
    svc.set_schedule("demo", True, 1)
    svc.store.update("projects", "name", "demo", {"next_run_at": "2000-01-01T00:00:00Z"})
    ran = threading.Event()
    original = svc.run_due
    svc.run_due = lambda: (original(), ran.set())[0]
    scheduler = Scheduler(svc, tick_seconds=0.05)
    scheduler.start()
    try:
        assert ran.wait(timeout=20)
    finally:
        scheduler.stop()
    assert any(r["trigger"] == "schedule" for r in svc.list_runs("demo"))


# --- the HTTP layer -----------------------------------------------------------------------

@pytest.fixture
def api(world):
    svc, db, connection, tmp_path = world
    return TestClient(create_app(svc, scheduler=False)), svc, db, connection


def test_http_flow_from_connection_to_incident(api):
    client, svc, db, connection = api
    assert client.get("/api/health").json()["ok"] is True
    tested = client.post("/api/connections/test", json={"connector": "duckdb", "config": {"path": str(db)}})
    assert tested.status_code == 200 and tested.json()["ok"]
    schema = client.get(f"/api/connections/{connection['id']}/schema").json()
    assert {d["name"] for d in schema["datasets"]} == {"feed", "rollup"}
    created = client.post("/api/projects", json={"name": "demo", "connection_id": connection["id"], "datasets": MAPPING})
    assert created.status_code == 201, created.text
    assert client.post("/api/projects/demo/baseline", json={}).status_code == 200
    build_database(db, duplicate_a_day=True)
    run = client.post("/api/projects/demo/runs", json={"kind": "monitor"})
    assert run.status_code == 201 and run.json()["status"] == "fail"
    incident = client.get("/api/incidents").json()["incidents"][0]
    assert incident["root_check"] == "find_duplicates"
    assert client.post(f"/api/incidents/{incident['id']}/ack", json={"acknowledged": True}).json()["acknowledged"]
    overview = client.get("/api/overview").json()
    assert overview["projects"][0]["open_incidents"] == 1 and overview["projects"][0]["worst_severity"] == "SEV1"
    assert client.get("/api/projects/demo/manifest.yaml").headers["content-type"].startswith("text/yaml")
    assert "autopsy.mcp_server" in json.dumps(client.get("/api/projects/demo/mcp-config").json())


def test_http_errors_are_json_with_the_right_status(api):
    client, svc, db, connection = api
    assert client.get("/api/nope").status_code == 404 and client.get("/api/nope").json()["error"] == "not_found"
    assert client.get("/api/projects/missing").status_code == 404
    assert client.get("/api/runs/999").status_code == 404
    assert client.post("/api/connections", content=b"{not json", headers={"content-type": "application/json"}).status_code == 400
    assert client.post("/api/connections", json=[1, 2]).status_code == 400
    assert client.post("/api/connections", json={"name": "x", "connector": "duckdb", "config": {}}).status_code == 422
    bad = client.post("/api/projects", json={"name": "demo", "connection_id": connection["id"],
                                             "datasets": [{**MAPPING[0], "roles": {"event_time": "nope"}}, MAPPING[1]]})
    assert bad.status_code == 422 and bad.json()["error"] == "mapping_mismatch" and bad.json()["issues"]
    assert client.get("/api/runs?limit=abc").status_code == 422


def test_the_secret_never_appears_in_any_response(api):
    client, svc, db, connection = api
    made = client.post("/api/connections", json={"name": "pg", "connector": "postgres", "secrets": {"password": "hunter2-xyz"},
                                                 "config": {"host": "h", "database": "d", "user": "u"}})
    assert made.status_code == 201
    for url in ("/api/connections", f"/api/connections/{made.json()['id']}", "/api/overview"):
        assert "hunter2-xyz" not in client.get(url).text


def test_the_ui_is_served_from_the_root(api):
    client = api[0]
    page = client.get("/")
    if page.status_code == 200:
        assert "text/html" in page.headers["content-type"]


def test_a_web_page_on_another_site_cannot_drive_the_api(api):
    _, svc, db, _ = api
    app = create_app(svc, scheduler=False, allowed_hosts={"localhost", "127.0.0.1"})
    client = TestClient(app, base_url="http://localhost:8765")
    body = {"connector": "duckdb", "config": {"path": str(db)}}
    assert client.post("/api/connections/test", json=body).status_code == 200
    assert client.post("/api/connections/test", json=body, headers={"origin": "http://localhost:8765"}).status_code == 200
    foreign = client.post("/api/connections/test", json=body, headers={"origin": "https://evil.example"})
    assert foreign.status_code == 403 and foreign.json()["error"] == "forbidden_origin"
    simple = client.post("/api/connections/test", content=json.dumps(body), headers={"content-type": "text/plain"})
    assert simple.status_code == 415                 # a "simple" cross-site request would skip the CORS preflight
    rebound = TestClient(app, base_url="http://evil.example").get("/api/health")
    assert rebound.status_code == 403 and rebound.json()["error"] == "forbidden_host"
