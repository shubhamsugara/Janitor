import sqlite3

import pytest

from janitor.models import Resource, RuleResult, Share, Usage
from janitor.store import Store


def res(id, **kw):
    fields = {
        "type": "volume",
        "account": "111111111111",
        "region": "us-east-1",
        "name": id,
        "created_at": "2026-01-15T00:00:00Z",
        "size_gb": 10,
        "status": "orphaned",
        "est_monthly_cost": 1.0,
    } | kw
    return Resource(id=id, **fields)


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "janitor.db")
    scan_id = store.start_scan("mock")
    store.save_inventory(
        scan_id,
        [
            res("vol-1", name="Base-Linux-data", tags={"owner": "me", "env": "prod"}),
            res("vol-2", name="100%_done", region="eu-west-1", status="idle"),
            res("vol-3", name="100xxdone", created_at="2026-01-31T23:59:59Z"),
            res("vol-4", created_at="2026-02-01T00:00:00Z", tags={"janitor:keep": "true"}),
            res(
                "ami-1",
                type="ami",
                size_gb=8,
                est_monthly_cost=None,
                snapshot_ids=["snap-1"],
                status="in_use",
            ),
            res(
                "ami-2",
                type="ami",
                source_ami_id="ami-1",
                region="eu-west-1",
                est_monthly_cost=None,
            ),
            res("snap-1", type="snapshot", linked_ami_id="ami-1", status="in_use"),
        ],
        [Share("ami-1", "account", "222222222222")],
        [Usage("ami-1", "222222222222", "us-east-1", "instance", "i-1", "web")],
    )
    store.finish_scan(scan_id, "ok")
    store.scan_id = scan_id
    return store


def ids(store, **filters):
    items, total = store.query_resources(store.scan_id, filters, sort="id")
    assert total == len(items)
    return [r.id for r in items]


def test_round_trip_keeps_every_field(store):
    [ami] = store.get_resources(store.scan_id, ["ami-1"])
    assert ami.snapshot_ids == ["snap-1"] and ami.est_monthly_cost is None and ami.type == "ami"


def test_filters_combine_with_and(store):
    assert ids(store, type="volume", region="us-east-1", status="orphaned") == [
        "vol-1",
        "vol-3",
        "vol-4",
    ]
    assert ids(store, type="volume", status="idle,in_use") == ["vol-2"]


def test_q_is_case_insensitive_and_literal(store):
    assert ids(store, q="base-linux") == ["vol-1"]
    assert ids(store, q="100%") == ["vol-2"]
    assert ids(store, q="%_d") == ["vol-2"]
    assert ids(store, q="AMI-") == ["ami-1", "ami-2"]


def test_date_range_is_inclusive(store):
    assert ids(store, type="volume", created_from="2026-01-15", created_to="2026-01-31") == [
        "vol-1",
        "vol-2",
        "vol-3",
    ]


def test_tag_filter(store):
    assert ids(store, tag="env=prod") == ["vol-1"]
    assert ids(store, tag="janitor:keep=true") == ["vol-4"]
    assert ids(store, tag="owner") == ["vol-1"]


def test_pagination_and_sort(store):
    items, total = store.query_resources(
        store.scan_id, {"type": "volume"}, sort="-created_at", page=2, page_size=2
    )
    assert total == 4 and [r.id for r in items] == ["vol-1", "vol-2"]
    with pytest.raises(ValueError, match="sort"):
        store.query_resources(store.scan_id, {}, sort="raw_json")


def test_stats_and_overview(store):
    assert store.stats(store.scan_id, {"type": "volume"}) == {
        "total": 4,
        "orphaned": 3,
        "size_gib": 40,
        "est_monthly_usd": 4.0,
    }
    assert store.stats(store.scan_id, {"type": "ami"})["est_monthly_usd"] is None
    vol = next(t for t in store.overview(store.scan_id) if t["type"] == "volume")
    assert vol == {
        "type": "volume",
        "total": 4,
        "orphaned": 3,
        "orphaned_gib": 30,
        "orphaned_usd": 3.0,
    }


def test_relations(store):
    assert store.amis_using_snapshot(store.scan_id, "snap-1") == ["ami-1"]
    assert [c.id for c in store.copies_of(store.scan_id, "ami-1")] == ["ami-2"]
    [ami] = store.get_resources(store.scan_id, ["ami-1"])
    related = store.related(store.scan_id, ami)
    assert {(link["relation"], link["id"]) for link in related["links"]} == {
        ("snapshot", "snap-1"),
        ("copy", "ami-2"),
    }
    assert related["shares"] == [{"principal_type": "account", "principal": "222222222222"}]
    assert related["usage"][0]["ref_name"] == "web"


def test_rule_results_replace_per_scan(store):
    store.save_rule_results(store.scan_id, [RuleResult("vol-1", "W4", "warn", "No owner.")])
    store.save_rule_results(store.scan_id, [RuleResult("vol-2", "R5", "block", "Too new.")])
    assert list(store.rule_results(store.scan_id, ["vol-1", "vol-2"])) == ["vol-2"]


def test_latest_scan_ignores_running_and_failed(store):
    store.start_scan("mock")
    failed = store.start_scan("mock")
    store.finish_scan(failed, "failed")
    assert store.latest_scan()["id"] == store.scan_id
    store.fail_running_scans()
    assert store.last_scan()["status"] == "failed"


def test_prune_keeps_two_completed_scans(store):
    for _ in range(3):
        scan_id = store.start_scan("mock")
        store.save_inventory(scan_id, [res("vol-x")], [], [])
        store.finish_scan(scan_id, "ok")
    kept = {row[0] for row in store._db.execute("SELECT DISTINCT scan_id FROM resources")}
    assert len(kept) == 2 and store.latest_scan()["id"] in kept


def test_plans_and_audit(store):
    store.save_plan("p1", store.scan_id, {"ids": ["vol-1"]}, {"variant": "none_blocked"})
    assert store.get_plan("p1")["results"] == {"variant": "none_blocked"}
    assert store.get_plan("nope") is None
    store.add_audit("plan", {"plan_id": "p1"})
    store.add_audit("simulate", {"plan_id": "p1"})
    items, total = store.list_audit(page=1, page_size=1)
    assert (
        total == 2 and items[0]["action"] == "simulate" and items[0]["payload"] == {"plan_id": "p1"}
    )


def test_audit_is_append_only(store):
    store.add_audit("plan", {})
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._db.execute("UPDATE audit SET actor = 'x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._db.execute("DELETE FROM audit")
