"""The six tools: shapes, error handling, output caps, and one real stdio round trip."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys

import duckdb
import yaml

from autopsy.core.baseline import learn_baseline, save_baseline
from autopsy.core.manifest import parse_manifest
from autopsy.core.models import cap_payload
from autopsy.mcp_server.tools import Tools
from fake_connector import FakeConnector
from test_checks import NOW, TYPES, history


def make_tools(rows=None, **kw):
    manifest = parse_manifest({
        "project": "demo", "connector": "fake", "connection": {},
        "datasets": [
            {"name": "events", "source": "events_tbl", "feeds": ["totals"],
             "roles": {"event_time": "created_at", "key": ["event_id"], "measure": ["amount"], "required": ["region"]},
             "expected": {"max_age_hours": 30}},
            {"name": "totals", "source": "totals_tbl", "business_visible": True, "roles": {"measure": ["total"]}},
        ],
        "thresholds": {"max_null_rate": 0.05},
    })
    connector = FakeConnector({"events_tbl": (TYPES, rows if rows is not None else history()),
                               "totals_tbl": ({"total": "DOUBLE"}, [{"total": 1.0}])})
    return Tools(manifest, connector, now=NOW, **kw)


def test_describe_project_gives_roles_lineage_and_possible_checks():
    out = make_tools().describe_project()
    assert out["project"] == "demo" and out["baseline_available"] is False
    events, totals = out["datasets"]
    assert events["feeds"] == ["totals"] and totals["fed_by"] == ["events"] and totals["business_visible"] is True
    assert events["possible_checks"] == ["check_freshness", "check_volume", "check_schema", "profile_dataset",
                                         "find_duplicates"]
    assert totals["possible_checks"] == ["check_schema", "profile_dataset"]


def test_every_check_tool_returns_the_finding_shape():
    tools = make_tools()
    for tool in ("check_freshness", "check_volume", "check_schema", "find_duplicates", "profile_dataset"):
        out = tools.call(tool, "events")
        assert set(out) == {"check", "dataset", "status", "summary", "evidence", "next_checks", "truncated"}
        assert out["check"] == tool and out["dataset"] == "events"
        assert out["status"] in {"ok", "warn", "fail", "skipped"}


def test_unknown_dataset_and_unknown_column_come_back_as_data():
    tools = make_tools()
    assert tools.check_freshness("nope")["error"] == "unknown_dataset"
    assert tools.profile_dataset("events", ["nope"])["error"] == "unknown_column"
    assert "message" in tools.find_duplicates("nope")


def test_a_broken_database_becomes_an_error_object_not_a_crash():
    class Broken(FakeConnector):
        def aggregate(self, dataset, spec):
            raise RuntimeError("disk on fire")

    tools = make_tools()
    tools._connector = Broken({"events_tbl": (TYPES, [])})
    out = tools.check_volume("events")
    assert out["error"] == "check_failed" and "disk on fire" in out["message"]


def test_baseline_is_picked_up_without_restarting(tmp_path):
    tools = make_tools(state_dir=tmp_path)
    assert tools.check_schema("events")["status"] == "skipped"
    save_baseline(learn_baseline(tools.manifest, tools.connector, NOW), tmp_path)
    assert tools.check_schema("events")["status"] == "ok"


def test_findings_are_capped_in_rows_and_bytes():
    payload = {"rows": [{"day": f"2026-01-{i:02d}", "text": "x" * 40} for i in range(500)], "scalar": 1}
    capped, truncated = cap_payload(payload)
    assert truncated and len(capped["rows"]) <= 50 and len(json.dumps(capped)) <= 2048 and capped["scalar"] == 1
    small, truncated = cap_payload({"a": [1, 2, 3]})
    assert not truncated and small == {"a": [1, 2, 3]}


def test_a_tool_result_stays_small_even_for_a_dataset_with_a_long_history():
    out = make_tools(history(days=400, per_day=3)).check_volume("events")
    assert len(json.dumps(out)) <= 2300          # 2 KB of evidence plus the fixed envelope


def test_the_server_speaks_mcp_over_stdio(tmp_path):
    """Start the real server process and call two tools through the MCP client."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    db = tmp_path / "demo.duckdb"
    con = duckdb.connect(str(db))
    con.execute("create table events (event_id integer, created_at timestamp, amount double)")
    con.execute("insert into events values (1, '2026-10-27 08:00:00', 10.0), (1, '2026-10-27 09:00:00', 11.0)")
    con.close()
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.safe_dump({
        "project": "stdio_demo", "connector": "duckdb", "connection": {"path_env": "STDIO_DEMO_DB"},
        "datasets": [{"name": "feed", "source": "events",
                      "roles": {"event_time": "created_at", "key": ["event_id"], "measure": ["amount"]},
                      "expected": {"max_age_hours": 24}}],
    }))

    async def go():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "autopsy.mcp_server", "--manifest", str(manifest)],
            env={"STDIO_DEMO_DB": str(db), "AUTOPSY_NOW": "2026-10-27T12:00:00", "AUTOPSY_STATE_DIR": str(tmp_path)},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                described = json.loads((await session.call_tool("describe_project", {})).content[0].text)
                dup = json.loads((await session.call_tool("find_duplicates", {"dataset": "feed"})).content[0].text)
                return names, described, dup

    names, described, dup = asyncio.run(asyncio.wait_for(go(), 60))
    assert names == {"describe_project", "check_freshness", "check_schema", "profile_dataset", "find_duplicates",
                     "check_volume"}
    assert described["datasets"][0]["name"] == "feed"
    assert dup["status"] == "fail" and dup["evidence"]["repeated_keys"] == 1


def test_a_bad_manifest_stops_the_server_with_a_message_on_stderr(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("project: x\n")
    run = subprocess.run([sys.executable, "-m", "autopsy.mcp_server", "--manifest", str(bad)],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 2 and run.stdout == "" and "missing required field" in run.stderr
