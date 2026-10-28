"""The contract every connector must pass; passing it is the definition of "supported"."""
from __future__ import annotations

import pytest

from autopsy.core.models import (
    Agg,
    AggSpec,
    Bucket,
    Filter,
    InvalidSpec,
    UnknownColumn,
    UnknownDataset,
)

N = Agg("count", "*", "n")


def rows(case, **kw):
    return case.connector.aggregate("items", AggSpec(**kw))


def test_lists_and_describes(case):
    assert "items" in case.connector.list_datasets()
    cols = {c.name: c for c in case.connector.describe("items")}
    assert list(cols) == ["id", "name", "price", "created_at"]
    assert cols["id"].kind == "numeric"
    assert cols["name"].kind == "text"
    assert cols["created_at"].kind == "temporal"


def test_unknown_names_raise_typed_errors(case):
    c = case.connector
    with pytest.raises(UnknownDataset):
        c.describe("nope")
    with pytest.raises(UnknownDataset):
        c.aggregate("nope", AggSpec(select=[N]))
    with pytest.raises(UnknownDataset):
        c.sample("nope")
    with pytest.raises(UnknownColumn):
        rows(case, select=[Agg("max", "nope", "m")])
    with pytest.raises(UnknownColumn):
        rows(case, select=[N], group_by=["nope"])
    with pytest.raises(UnknownColumn):
        rows(case, select=[N], where=[Filter("nope", "=", 1)])


def test_scalar_aggregates(case):
    (row,) = rows(
        case,
        select=[
            N,
            Agg("count", "name", "named"),
            Agg("count_null", "name", "unnamed"),
            Agg("count_distinct", "name", "names"),
            Agg("min", "price", "lo"),
            Agg("max", "price", "hi"),
            Agg("avg", "price", "mean"),
            Agg("median", "price", "mid"),
            Agg("sum", "price", "total"),
            Agg("min", "created_at", "first"),
            Agg("max", "created_at", "last"),
        ],
    )
    assert row == {
        "n": 5, "named": 4, "unnamed": 1, "names": 4, "lo": 10.0, "hi": 40.0,
        "mean": 25.0, "mid": 25.0, "total": 100.0,
        "first": "2026-10-01T08:00:00", "last": "2026-10-03T23:59:00",
    }


def test_count_null_on_an_empty_selection_is_zero(case):
    (row,) = rows(case, select=[N, Agg("count_null", "name", "z")], where=[Filter("id", ">", 99)])
    assert row == {"n": 0, "z": 0}


def test_day_and_hour_buckets(case):
    by_day = rows(case, select=[N], group_by=[Bucket("created_at", "day")], order_by=["day"])
    assert by_day == [{"day": "2026-10-01", "n": 2}, {"day": "2026-10-02", "n": 1}, {"day": "2026-10-03", "n": 2}]
    by_hour = rows(case, select=[N], group_by=[Bucket("created_at", "hour", "h")], where=[Filter("id", "<=", 2)],
                   order_by=["h"])
    assert by_hour == [{"h": "2026-10-01T08:00:00", "n": 1}, {"h": "2026-10-01T09:00:00", "n": 1}]


def test_filters_accept_text_dates_and_nulls(case):
    assert rows(case, select=[N], where=[Filter("created_at", ">=", "2026-10-02")]) == [{"n": 3}]
    assert rows(case, select=[N], where=[Filter("created_at", "<", "2026-10-02T00:00:00")]) == [{"n": 2}]
    assert rows(case, select=[N], where=[Filter("name", "is_null")]) == [{"n": 1}]
    assert rows(case, select=[N], where=[Filter("name", "is_not_null")]) == [{"n": 4}]
    assert rows(case, select=[N], where=[Filter("id", "!=", 3)]) == [{"n": 4}]
    assert rows(case, select=[N], where=[Filter("id", ">=", 2), Filter("id", "<", 4)]) == [{"n": 2}]


def test_values_are_bound_never_pasted(case):
    hostile = "x'; drop table items; --"
    assert rows(case, select=[N], where=[Filter("name", "=", hostile)]) == [{"n": 0}]
    assert rows(case, select=[N]) == [{"n": 5}]


def test_having_order_and_limit(case):
    got = rows(case, select=[N], group_by=[Bucket("created_at", "day")], having=[Filter("n", ">", 1)],
               order_by=["-day"], limit=1)
    assert got == [{"day": "2026-10-03", "n": 2}]


def test_group_by_plain_column_and_null_group(case):
    got = rows(case, select=[N], group_by=["name"], order_by=["-n", "name"], limit=2)
    assert len(got) == 2 and got[0]["n"] == 1


def test_invalid_specs_are_rejected(case):
    with pytest.raises(InvalidSpec):
        rows(case, select=[])
    with pytest.raises(InvalidSpec):
        rows(case, select=[N], limit=0)
    with pytest.raises(InvalidSpec):
        rows(case, select=[N], limit=1001)
    with pytest.raises(InvalidSpec):
        rows(case, select=[Agg("variance", "price", "v")])
    with pytest.raises(InvalidSpec):
        rows(case, select=[Agg("avg", "name", "v")])
    with pytest.raises(InvalidSpec):
        rows(case, select=[Agg("max", "*", "v")])
    with pytest.raises(InvalidSpec):
        rows(case, select=[Agg("count", "*", "bad alias")])
    with pytest.raises(InvalidSpec):
        rows(case, select=[N], where=[Filter("id", "like", "1")])
    with pytest.raises(InvalidSpec):
        rows(case, select=[N], where=[Filter("id", "=", None)])
    with pytest.raises(InvalidSpec):
        rows(case, select=[N], group_by=[Bucket("name", "day")])
    with pytest.raises(InvalidSpec):
        rows(case, select=[N], order_by=["missing"])


def test_sample_is_capped_and_plain(case):
    got = case.connector.sample("items", n=100)
    assert 1 <= len(got) <= 20
    assert len(case.connector.sample("items", n=2)) == 2
    for row in got:
        for value in row.values():
            assert value is None or type(value) in (str, int, float, bool)


def test_results_use_plain_python_types(case):
    for row in rows(case, select=[N, Agg("avg", "price", "mean"), Agg("max", "created_at", "last")]):
        for value in row.values():
            assert type(value) in (str, int, float)


def test_connector_never_writes(case):
    assert case.connector.read_only is True
    rows(case, select=[N])
    case.connector.sample("items")
    with pytest.raises(Exception):
        case.write_probe()
    assert case.unchanged()


def test_duckdb_waits_for_a_writer_to_let_go(tmp_path, monkeypatch):
    import duckdb

    from autopsy.connectors import duckdb_connector
    from autopsy.core.models import ConnectionFailed

    path = tmp_path / "busy.duckdb"
    duckdb.connect(str(path)).close()
    real = duckdb.connect
    attempts = {"n": 0}

    def busy_twice(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise duckdb.IOException('IO Error: Could not set lock on file "busy.duckdb": Conflicting lock is held')
        if attempts["n"] == 2:       # how Windows words the same thing
            raise duckdb.IOException('IO Error: Cannot open file "busy.duckdb": The process cannot access the file '
                                     'because it is being used by another process.')
        return real(*args, **kwargs)

    monkeypatch.setattr(duckdb_connector.duckdb, "connect", busy_twice)
    monkeypatch.setattr(duckdb_connector.time, "sleep", lambda s: None)
    duckdb_connector.DuckDBConnector(str(path)).close()
    assert attempts["n"] == 3

    monkeypatch.setattr(duckdb_connector, "LOCK_WAIT_SECONDS", 0.0)
    attempts["n"] = 0
    monkeypatch.setattr(duckdb_connector.duckdb, "connect",
                        lambda *a, **k: (_ for _ in ()).throw(duckdb.IOException("IO Error: could not set lock")))
    with pytest.raises(ConnectionFailed, match="lock"):
        duckdb_connector.DuckDBConnector(str(path))
