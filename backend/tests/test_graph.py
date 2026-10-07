import pytest
from helpers import NOW, SEED, stamp

from janitor.graph import RESOURCE_KINDS, build_graph
from janitor.providers.mock import MockProvider
from janitor.scanner import Scanner
from janitor.store import Store

CONTEXT_PREFIXES = {
    "instance",
    "asg",
    "launch_template",
    "launch_config",
    "account",
    "group",
    "org",
    "ou",
    "database",
    "more",
}


@pytest.fixture
def scanned(tmp_path, config):
    store = Store(tmp_path / "j.db")
    scan_id = Scanner(store, MockProvider(SEED, clock=lambda: NOW), config, clock=lambda: NOW).run()
    return store, config, scan_id


def named(store, scan_id, name, **filters):
    items, _ = store.query_resources(scan_id, {"q": name, **filters})
    return next(r for r in items if r.name == name)


def graph_of(scanned, resource, **kw):
    store, config, scan_id = scanned
    return build_graph(store, config, scan_id, resource.id, **kw)


def test_ami_graph_shows_snapshot_copy_users_and_shares(scanned):
    store, _, scan_id = scanned
    ami = named(store, scan_id, f"base-linux-{stamp(20)}", region="us-east-1", type="ami")
    g = graph_of(scanned, ami)
    by_id = {n["id"]: n for n in g["nodes"]}
    edges = {(e["source"], e["target"], e["relation"]) for e in g["edges"]}
    assert by_id[ami.id]["depth"] == 0
    snap_id = ami.snapshot_ids[0]
    assert by_id[snap_id]["depth"] == -1 and (snap_id, ami.id, "backs") in edges
    users = {
        n["label"]: n
        for n in g["nodes"]
        if n["kind"] in ("instance", "asg", "launch_template") and n["depth"] == 1
    }
    assert set(users) == {"dev-api-1", "prd-api-asg", "qas-api-1", "uat-api v3"}
    assert users["dev-api-1"]["active"] is True and users["qas-api-1"]["active"] is False
    assert users["uat-api v3"]["active"] is None
    copy = next(n for n in g["nodes"] if n["kind"] == "ami" and n["region"] == "us-west-2")
    assert copy["depth"] == 1 and (ami.id, copy["id"], "copied_to") in edges
    accounts = {n["label"] for n in g["nodes"] if n["kind"] == "account" and n["depth"] == 1}
    assert accounts == {"sbx", "dev", "uat", "qas", "prd"}
    assert g["truncated"] is False


def test_snapshot_used_by_goes_through_its_ami(scanned):
    store, _, scan_id = scanned
    ami = named(store, scan_id, f"base-linux-{stamp(20)}", region="us-east-1", type="ami")
    [snap] = store.get_resources(scan_id, ami.snapshot_ids)
    g = graph_of(scanned, snap)
    assert g["used_by"]["total"] == 4 and g["used_by"]["active"] == 2
    summary = g["used_by"]["summary"]
    assert summary.startswith("Used by 1 running instance, 1 active Auto Scaling group")
    assert f"through {ami.id}" in summary and "dev, prd, qas and uat" in summary
    depths = {n["id"]: n["depth"] for n in g["nodes"]}
    assert depths[ami.id] == 1
    assert any(n["label"] == "dev-api-1" and n["depth"] == 2 for n in g["nodes"])


def test_volume_graph_shows_instance_and_snapshots(scanned):
    store, _, scan_id = scanned
    vol = named(store, scan_id, "tools-ci-data", type="volume")
    g = graph_of(scanned, vol)
    relations = {e["relation"] for e in g["edges"]}
    assert {"attached_to", "snapshot_of"} <= relations
    assert any(n["label"] == "tools-ci-data-weekly" and n["depth"] == 1 for n in g["nodes"])
    assert g["used_by"]["summary"] == f"Attached to instance {vol.attached_instance}."


def test_rds_graph_shows_database_and_siblings(scanned):
    store, _, scan_id = scanned
    snap = named(store, scan_id, f"dev-orders-{stamp(95)}", type="rds_snapshot")
    g = graph_of(scanned, snap)
    db = next(n for n in g["nodes"] if n["kind"] == "database")
    assert db["id"] == "database:222222222222:us-east-1:dev-orders" and db["depth"] == -1
    siblings = [n for n in g["nodes"] if n["kind"] == "rds_snapshot" and n["id"] != snap.id]
    assert len(siblings) == 3 and all(n["depth"] == 0 for n in siblings)
    assert g["used_by"] == {"active": 0, "total": 0, "summary": "Nothing uses it."}


def test_lane_cap_collapses_extra_nodes(scanned):
    store, _, scan_id = scanned
    ami = named(store, scan_id, f"base-linux-{stamp(20)}", region="us-east-1", type="ami")
    g = graph_of(scanned, ami, lane_cap=3)
    lane_one = [n for n in g["nodes"] if n["depth"] == 1]
    assert len([n for n in lane_one if n["kind"] != "more"]) == 3
    more = next(n for n in g["nodes"] if n["id"] == "more:1")
    assert more["label"] == "+7 more" and g["truncated"] is True


def test_context_ids_are_prefixed(scanned):
    store, _, scan_id = scanned
    ami = named(store, scan_id, f"partner-export-{stamp(250)}", type="ami")
    g = graph_of(scanned, ami)
    for node in g["nodes"]:
        if node["kind"] in RESOURCE_KINDS:
            assert ":" not in node["id"]
        else:
            assert node["id"].split(":")[0] in CONTEXT_PREFIXES
    account = next(n for n in g["nodes"] if n["kind"] == "account")
    assert account["label"] == "444444444444 (not scanned)"


def test_unknown_resource_has_no_graph(scanned):
    store, config, scan_id = scanned
    assert build_graph(store, config, scan_id, "ami-0000000000000dead") is None
