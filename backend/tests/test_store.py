import sqlite3
from datetime import UTC, datetime

import pytest

from janitor.models import Deployment, Resource, RuleResult, Share, Usage
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
    store.save_rule_results(store.scan_id, [RuleResult("vol-1", "R4", "block", "Tagged.")])
    stats = store.stats(store.scan_id, {"type": "volume"}, datetime(2026, 2, 15, tzinfo=UTC))
    assert {
        k: stats[k]
        for k in (
            "total",
            "orphaned",
            "size_gib",
            "est_monthly_usd",
            "orphaned_gib",
            "orphaned_usd",
            "blocked",
            "deletable",
        )
    } == {
        "total": 4,
        "orphaned": 3,
        "size_gib": 40,
        "est_monthly_usd": 4.0,
        "orphaned_gib": 30,
        "orphaned_usd": 3.0,
        "blocked": 1,
        "deletable": 3,
    }
    assert stats["by_status"] == [
        {"key": "orphaned", "count": 3, "gib": 30, "usd": 3.0},
        {"key": "idle", "count": 1, "gib": 10, "usd": 1.0},
    ]
    assert stats["by_region"][0] == {"key": "us-east-1", "count": 3, "gib": 30, "usd": 3.0}
    assert [b["key"] for b in stats["by_age"]] == ["<30d", "30–90d", "90–180d", "180–365d", ">1y"]
    assert [b["count"] for b in stats["by_age"]] == [2, 2, 0, 0, 0]
    ami_stats = store.stats(store.scan_id, {"type": "ami"})
    assert ami_stats["est_monthly_usd"] is None and ami_stats["orphaned_usd"] is None
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


def test_new_fields_round_trip(tmp_path):
    from janitor.models import Database

    store = Store(tmp_path / "j.db")
    scan_id = store.start_scan("mock")
    breakdown = {"lines": [{"label": "Storage (gp3)", "amount": 1.6}], "total": 1.6}
    store.save_inventory(
        scan_id,
        [res("vol-9", iops=6000, throughput=250, encrypted=False, cost_breakdown=breakdown)],
        [],
        [Usage("ami-1", "222222222222", "us-east-1", "instance", "i-1", "web", "running")],
        [Database("db1", "222222222222", "us-east-1", "instance")],
    )
    [vol] = store.get_resources(scan_id, ["vol-9"])
    assert (vol.iops, vol.throughput, vol.encrypted) == (6000, 250, False)
    assert vol.cost_breakdown == breakdown
    assert store._db.execute("SELECT ref_state FROM usage").fetchone()[0] == "running"
    assert store._db.execute("SELECT COUNT(*) FROM databases").fetchone()[0] == 1


def test_schema_change_drops_scan_cache_but_keeps_audit(tmp_path):
    path = tmp_path / "j.db"
    old = Store(path)
    old.add_audit("plan", {"plan_id": "p1"})
    old.finish_scan(old.start_scan("mock"), "ok")
    old._db.execute("PRAGMA user_version = 1")
    old._db.commit()
    new = Store(path)
    assert new.last_scan() is None
    assert new.list_audit(1, 10)[1] == 1


def test_filters_accept_lists(store):
    assert ids(store, type="volume", region="us-east-1,eu-west-1") == [
        "vol-1",
        "vol-2",
        "vol-3",
        "vol-4",
    ]
    assert ids(store, account="111111111111,999999999999", type="ami") == ["ami-1", "ami-2"]


def test_segments_and_notes_round_trip(tmp_path):
    from janitor.models import Segment
    from janitor.store import Store

    store = Store(tmp_path / "j.db")
    scan_id = store.start_scan("aws")
    store.add_segment(scan_id, Segment("111111111111", "us-east-1", "ami", True, 3, duration_ms=12))
    store.set_notes(scan_id, {"unresolved": [{"value": "resolve:ssm:/x"}]})
    store.finish_scan(scan_id, "partial")
    (seg,) = store.segments(scan_id)
    assert (seg["account"], seg["kind"], seg["ok"], seg["items"], seg["duration_ms"]) == (
        "111111111111",
        "ami",
        1,
        3,
        12,
    )
    assert store.latest_scan()["notes"] == {"unresolved": [{"value": "resolve:ssm:/x"}]}


def test_each_provider_reads_only_its_own_scans(tmp_path):
    # Mock data must never show under the AWS badge (or the reverse) when both share data/.
    from janitor.store import Store

    path = tmp_path / "j.db"
    mock = Store(path, provider="mock")
    mock_scan = mock.start_scan("mock")
    mock.finish_scan(mock_scan, "ok")
    aws = Store(path, provider="aws")
    assert aws.latest_scan() is None and aws.last_scan() is None
    for _ in range(3):  # pruning keeps each provider's own newest scans
        aws.finish_scan(aws.start_scan("aws"), "ok")
    assert aws.latest_scan()["provider"] == "aws"
    assert mock.latest_scan()["id"] == mock_scan


def dep(name, **kw):
    fields = {
        "kind": "ec2",
        "account": "222222222222",
        "region": "us-east-1",
        "env": "dev",
        "app": "web",
        "version": "1.2.0",
        "state": "deployed",
        "resource_id": name,
        "name": name,
        "created_at": "2026-01-15T00:00:00Z",
    } | kw
    return Deployment(**fields)


def test_deployments_round_trip_and_are_pruned_with_their_scan(tmp_path):
    store = Store(tmp_path / "janitor.db")
    rows = [
        dep(
            "dev-web-1.2.0-2",
            desired=2,
            running=2,
            deployment_id="2",
            launch_template="web",
            launch_template_version="7",
            ami_id="ami-1",
        ),
        dep(
            "arn:svc/orders",
            kind="ecs",
            app="orders",
            cluster="apps",
            task_definition="orders:3",
            image="orders:2.0",
            ami_id=None,
        ),
    ]
    first = store.start_scan("mock")
    store.save_deployments(first, rows)
    store.finish_scan(first, "ok")
    assert store.deployments(first) == sorted(rows, key=lambda d: d.app)  # by app, then env
    for _ in range(2):
        later = store.start_scan("mock")
        store.finish_scan(later, "ok")
    assert store.deployments(first) == []


def test_shared_with_round_trips(tmp_path):
    store = Store(tmp_path / "j.db")
    scan_id = store.start_scan("mock")
    snap = res("arn:rds:1", type="rds_snapshot", shared_with=["222222222222", "all"])
    store.save_inventory(scan_id, [snap, res("vol-9")], [], [])
    got = {r.id: r for r in store.all_resources(scan_id)}
    assert got["arn:rds:1"].shared_with == ["222222222222", "all"]
    assert got["vol-9"].shared_with == []
