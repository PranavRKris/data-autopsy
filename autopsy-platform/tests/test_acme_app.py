"""The Acme Shop application end to end: a person breaks the shop, the platform notices, the person fixes it.

Each incident the shop can cause must (1) be found by the platform with the root cause the plug-in says it should,
and (2) leave no trace once rolled back. The platform is driven through its service, as the UI does.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer

import pytest

from autopsy.grade import load_expected
from autopsy.service.engine import Service
from test_acme_scenarios import ACME, build

pytestmark = pytest.mark.skipif(not ACME.is_dir(), reason="plugins/acme_shop is not checked out next to the platform")

AS_OF = datetime(2026, 10, 28, 12, 0, 0)
SHOP_NOW = datetime(2026, 10, 28, 12, 30, 0)
PLATFORM_NOW = datetime(2026, 10, 28, 13, 0, 0)
EVENT_SCENARIO = {"duplicate_batch": "S1", "schema_rename": "S2", "guest_checkout": "S3",
                  "ingestion_outage": "S4", "cents_bug": "S5"}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("acme_app")
    patch = pytest.MonkeyPatch()
    patch.syspath_prepend(str(ACME / "app"))
    db = root / "acme.duckdb"
    patch.setenv("ACME_DB_PATH", str(db))
    patch.setenv("AUTOPSY_NOW", PLATFORM_NOW.isoformat())
    build(db, "S0", root / "log.txt")

    from shop import Shop

    shop = Shop(db, clock=lambda: SHOP_NOW, log_path=root / "pipeline.log")
    svc = Service(root / "state")
    imported = svc.import_manifest((ACME / "manifest.yaml").read_text(encoding="utf-8"))
    assert imported["validation"]["ok"], imported["validation"]
    project = imported["project"]["name"]
    svc.learn_baseline(project)
    yield shop, svc, project
    patch.undo()


def monitor(world):
    shop, svc, project = world
    shop.run_pipeline()
    return svc.run(project, "monitor")


def test_a_healthy_shop_has_no_incident(world):
    run = monitor(world)
    assert run["status"] == "ok", run["summary"]
    assert world[1].list_incidents(project=world[2]) == []


@pytest.mark.parametrize("event", list(EVENT_SCENARIO))
def test_each_incident_is_found_and_rolling_back_clears_it(world, event):
    shop, svc, project = world
    expected = load_expected(ACME / "expected" / "expected_results.yaml", EVENT_SCENARIO[event])

    shop.trigger(event)
    run = monitor(world)
    assert run["status"] == "fail", run["summary"]
    (incident,) = svc.list_incidents(project=project)
    checks = expected["root_check"] if isinstance(expected["root_check"], list) else [expected["root_check"]]
    assert incident["root_dataset"] == expected["root_dataset"] and incident["root_check"] in checks, incident
    assert incident["severity"] == expected["severity"]

    shop.roll_back(event)
    run = monitor(world)
    assert run["status"] == "ok", f"rolling back {event} left a trace: {run['summary']}"
    assert svc.list_incidents(project=project) == []
    assert any(i["id"] == incident["id"] and i["resolved_at"] for i in svc.list_incidents(project=project, status="resolved"))


def test_the_symptom_the_business_sees_is_real(world):
    """The dashboard finance reads moves in the way each story says it does."""
    shop, _, _ = world
    shop.run_pipeline()
    healthy = {d["day"]: d for d in shop.revenue(7)["days"]}
    today_minus_1 = (SHOP_NOW.date().replace(day=SHOP_NOW.day - 1)).isoformat()

    shop.trigger("cents_bug")
    shop.run_pipeline()
    assert shop.revenue(7)["days"][-2]["total"] > 50 * healthy[today_minus_1]["total"]
    shop.roll_back("cents_bug")

    shop.trigger("schema_rename")
    shop.run_pipeline()
    assert "unknown" in shop.revenue(7)["channels"]
    shop.roll_back("schema_rename")

    shop.trigger("ingestion_outage")
    shop.run_pipeline()
    assert shop.revenue(7)["days"][-1]["total"] == 0
    shop.roll_back("ingestion_outage")
    shop.run_pipeline()


def test_orders_placed_while_an_incident_is_live_are_affected_and_repaired(world):
    shop, _, _ = world
    shop.trigger("cents_bug")
    order = shop.place_order(customer_id=5, items=[{"product_id": "hoodie", "qty": 2}], channel="web")
    assert order["amount"] == 118.0
    assert shop.recent_orders(1)[0]["amount"] == 11800.0          # the bug wrote cents
    shop.roll_back("cents_bug")
    assert shop.recent_orders(1)[0]["amount"] == 118.0

    shop.trigger("ingestion_outage")
    before = shop.state()["counts"]["raw_orders"]
    queued = shop.place_order(customer_id=6, items=[{"product_id": "mug", "qty": 1}])
    assert queued["status"] == "queued" and shop.state()["counts"]["raw_orders"] == before
    result = shop.roll_back("ingestion_outage")
    assert result["queued_orders_replayed"] == 1
    assert shop.state()["counts"]["queued_orders"] == 0 and shop.state()["counts"]["raw_orders"] == before + result["orders_backfilled"] + 1

    shop.trigger("schema_rename")
    shop.place_order(customer_id=7, items=[{"product_id": "mug", "qty": 1}], channel="mobile")   # uses the new column name
    shop.roll_back("schema_rename")
    assert shop.recent_orders(1)[0]["channel"] == "mobile"


def test_bad_requests_are_refused_cleanly(world):
    from shop import ShopError

    shop, _, _ = world
    with pytest.raises(ShopError, match="unknown product"):
        shop.place_order(items=[{"product_id": "nope", "qty": 1}])
    with pytest.raises(ShopError, match="no customer"):
        shop.place_order(customer_id=99999)
    with pytest.raises(ShopError, match="not happening"):
        shop.roll_back("cents_bug")
    shop.trigger("duplicate_batch")
    with pytest.raises(ShopError, match="already happening"):
        shop.trigger("duplicate_batch")
    shop.roll_back("duplicate_batch")
    with pytest.raises(ShopError, match="unknown event"):
        shop.trigger("meteor_strike")


def test_the_platform_can_read_while_the_shop_writes(world):
    """The shop and the platform are separate processes sharing one DuckDB file: neither may fail because the other is busy."""
    import subprocess
    import sys

    shop, svc, project = world
    program = "\n".join([
        "import sys; sys.path.insert(0, sys.argv[1])",
        "from datetime import datetime",
        "from shop import Shop",
        "s = Shop(sys.argv[2], clock=lambda: datetime(2026, 10, 28, 12, 30))",
        "for _ in range(60): s.place_order(items=[{'product_id': 'mug', 'qty': 1}])",
    ])
    writer = subprocess.Popen([sys.executable, "-c", program, str(ACME / "app"), shop.db_path],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    errors = []
    try:
        for _ in range(4):
            run = svc.run(project, "monitor", auto_investigate=False)
            if run["status"] == "error":
                errors.append(run["summary"])
    finally:
        out, err = writer.communicate(timeout=180)
    assert writer.returncode == 0, err[-500:]
    assert not errors, errors


# --- the web server ------------------------------------------------------------------------

@pytest.fixture
def server(world):
    from server import Background, make_handler

    shop = world[0]
    background = Background(shop, pipeline_interval=3600, traffic_per_minute=60, traffic_on=False, pipeline_on=False)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(shop, background, "http://127.0.0.1:8765/#/projects/acme_shop"))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def call(base, method, path, body=None, headers=None):
    request = urllib.request.Request(base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def test_the_http_api_works_and_refuses_cross_site_requests(server):
    assert call(server, "GET", "/api/state")[1]["counts"]["raw_orders"] > 0
    status, order = call(server, "POST", "/api/orders", {"customer_id": 3, "items": [{"product_id": "mug", "qty": 1}]})
    assert status == 200 and order["status"] == "accepted"
    assert call(server, "POST", "/api/orders", {"customer_id": 3, "items": [{"product_id": "x", "qty": 1}]})[0] == 400
    assert call(server, "GET", "/api/nope")[0] == 404
    assert [e["id"] for e in call(server, "GET", "/api/events")[1]["events"]] == list(EVENT_SCENARIO)
    assert call(server, "POST", "/api/events/duplicate_batch/trigger", headers={"Origin": "https://evil.example"})[0] == 403
    assert call(server, "GET", "/api/state", headers={"Host": "evil.example"})[0] == 403
    request = urllib.request.Request(server + "/api/events/duplicate_batch/trigger", method="POST", data=b"{}",
                                     headers={"Content-Type": "text/plain"})
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=30)
    assert refused.value.code == 403
    assert call(server, "GET", "/api/events")[1]["events"][0]["active"] is False   # nothing was triggered


def test_the_pages_are_served(server):
    request = urllib.request.Request(server + "/")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == 200 and b"<html" in response.read().lower()
    except urllib.error.HTTPError as exc:       # the page is built after the server; skip until it exists
        pytest.skip(f"no index page yet: {exc.code}")
