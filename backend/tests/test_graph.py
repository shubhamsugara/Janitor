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
    "unused",
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


def base_20(store, scan_id):
    return named(store, scan_id, f"base-linux-{stamp(20)}", region="us-east-1", type="ami")


def account_node(g, ami_id, account):
    return next(n for n in g["nodes"] if n["id"] == f"account:{ami_id}:{account}")


def test_ami_graph_hangs_usage_under_accounts(scanned):
    store, _, scan_id = scanned
    ami = base_20(store, scan_id)
    g = graph_of(scanned, ami)
    by_id = {n["id"]: n for n in g["nodes"]}
    edges = {(e["source"], e["target"], e["relation"]) for e in g["edges"]}
    assert by_id[ami.id]["depth"] == 0
    snap_id = ami.snapshot_ids[0]
    assert by_id[snap_id]["depth"] == -1 and (snap_id, ami.id, "backs") in edges

    accounts = {n["label"] for n in g["nodes"] if n["kind"] == "account" and n["depth"] == 1}
    assert accounts == {"dev", "prd", "qas", "uat", "1 account · not used"}  # sbx uses nothing
    dev = account_node(g, ami.id, "222222222222")
    assert (ami.id, dev["id"], "shared_with") in edges
    users = {n["label"]: n for n in g["nodes"] if n["depth"] == 2}
    assert {"dev-api-1", "qas-api-1", "prd-api-asg", "uat-api v3"} <= set(users)
    assert (dev["id"], users["dev-api-1"]["id"], "used_by") in edges
    assert users["dev-api-1"]["active"] is True and users["qas-api-1"]["active"] is False
    uat = account_node(g, ami.id, "666666666666")
    assert (uat["id"], users["uat-api v3"]["id"], "references") in edges
    assert g["truncated"] is False


def test_ami_graph_shows_its_copies_but_never_its_source_or_siblings(scanned):
    store, _, scan_id = scanned
    ami = base_20(store, scan_id)
    g = graph_of(scanned, ami)
    amis = [n for n in g["nodes"] if n["kind"] == "ami"]
    copy = next(n for n in amis if n["region"] == "us-west-2")
    assert {n["id"] for n in amis} == {ami.id, copy["id"]}
    assert copy["depth"] == 1
    # The copy expands to where it is used, and nothing else: no snapshots of its own.
    prd = account_node(g, copy["id"], "333333333333")
    assert prd["depth"] == 2
    assert any(n["label"] == "prd-dr-api-1" and n["depth"] == 3 for n in g["nodes"])
    copy_snaps = set(store.get_resources(scan_id, [copy["id"]])[0].snapshot_ids)
    assert not copy_snaps & {n["id"] for n in g["nodes"]}

    west = graph_of(scanned, store.get_resources(scan_id, [copy["id"]])[0])
    assert {n["id"] for n in west["nodes"] if n["kind"] == "ami"} == {copy["id"]}


def test_snapshot_used_by_goes_through_its_ami(scanned):
    store, _, scan_id = scanned
    ami = base_20(store, scan_id)
    [snap] = store.get_resources(scan_id, ami.snapshot_ids)
    g = graph_of(scanned, snap)
    assert g["used_by"]["total"] == 2 and g["used_by"]["active"] == 1
    summary = g["used_by"]["summary"]
    assert summary.startswith("Used by 1 running instance and 1 stopped instance in dev and qas")
    assert f"through {ami.id}" in summary
    depths = {n["id"]: n["depth"] for n in g["nodes"]}
    assert depths[ami.id] == 1
    assert depths[f"account:{ami.id}:222222222222"] == 2
    assert any(n["label"] == "dev-api-1" and n["depth"] == 3 for n in g["nodes"])


def test_used_by_separates_instances_from_references(scanned):
    store, _, scan_id = scanned
    summary = graph_of(scanned, base_20(store, scan_id))["used_by"]["summary"]
    assert summary == (
        "Used by 1 running instance and 1 stopped instance in dev and qas. "
        "Also named by 1 active Auto Scaling group and 1 launch template in prd and uat."
    )
    web = named(store, scan_id, f"app-web-{stamp(10)}", type="ami")
    used = graph_of(scanned, web)["used_by"]
    assert used == {
        "active": 0,
        "total": 0,
        "summary": "No instance uses it. Named by 1 active Auto Scaling group and 1 launch template in prd.",
    }


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
    g = graph_of(scanned, base_20(store, scan_id), lane_cap=3)
    lane_one = [n for n in g["nodes"] if n["depth"] == 1]
    assert len([n for n in lane_one if n["kind"] != "more"]) == 3
    more = next(n for n in g["nodes"] if n["id"] == "more:1")
    assert more["label"] == "+3 more" and g["truncated"] is True


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
    assert account["label"] == "444444444444 · couldn't check"


def test_unknown_resource_has_no_graph(scanned):
    store, config, scan_id = scanned
    assert build_graph(store, config, scan_id, "ami-0000000000000dead") is None


def _fan_out_store(tmp_path, config):
    from janitor.models import Inventory, Resource, Share, Usage

    ami = Resource(
        id="ami-big",
        type="ami",
        account="111111111111",
        region="us-east-1",
        name="big",
        created_at="2026-01-01T00:00:00Z",
        size_gb=8,
        tags={"owner": "me"},
    )
    usage = [
        Usage(
            "ami-big",
            "333333333333",
            "us-east-1",
            "instance",
            f"i-stop{n:03d}",
            f"stopped-{n:03d}",
            "stopped",
        )
        for n in range(30)
    ]
    usage += [
        Usage(
            "ami-big",
            "333333333333",
            "us-east-1",
            "instance",
            f"i-run{n}",
            f"running-{n}",
            "running",
        )
        for n in range(2)
    ]
    shares = [
        Share("ami-big", "account", "333333333333"),
        Share("ami-big", "account", "444444444444"),
    ]

    class Provider:
        name = "mock"

        def list_inventory(self, on_segment=None):
            return Inventory([ami], shares, usage, [])

    store = Store(tmp_path / "fan.db")
    return store, Scanner(store, Provider(), config, clock=lambda: NOW).run()


def test_lane_cap_keeps_running_users(tmp_path, config):
    store, scan_id = _fan_out_store(tmp_path, config)
    g = build_graph(store, config, scan_id, "ami-big", lane_cap=10)
    assert {n["label"] for n in g["nodes"] if n["depth"] == 1} == {"prd", "1 account · not used"}
    lane_two = {n["label"] for n in g["nodes"] if n["depth"] == 2}
    assert {"running-0", "running-1"} <= lane_two
    assert next(n for n in g["nodes"] if n["id"] == "more:2")["label"] == "+22 more"
    assert ("account:ami-big:333333333333", "more:2") in {
        (e["source"], e["target"]) for e in g["edges"]
    }


def test_used_by_admits_what_janitor_cant_see(scanned):
    store, _, scan_id = scanned
    public = named(store, scan_id, f"public-demo-{stamp(180)}", type="ami")
    partner = named(store, scan_id, f"partner-export-{stamp(250)}", type="ami")
    assert graph_of(scanned, public)["used_by"]["summary"] == (
        "Nothing in the scanned accounts uses it. It is public, so other AWS accounts may."
    )
    assert graph_of(scanned, partner)["used_by"]["summary"] == (
        "Nothing in the scanned accounts uses it. Janitor couldn't check 444444444444, "
        "so it may be used there."
    )
    [snap] = store.get_resources(scan_id, partner.snapshot_ids)
    assert graph_of(scanned, snap)["used_by"]["summary"] == (
        f"It backs {partner.id} ({partner.name}). Nothing in the scanned accounts uses it. "
        "Janitor couldn't check 444444444444, so it may be used there."
    )


def test_a_template_reference_doesnt_hide_an_account_janitor_couldnt_check(tmp_path, config):
    from janitor.models import Inventory, Resource, Segment, Share, Usage

    ami = Resource(
        "ami-ref", "ami", "111111111111", "us-east-1", "ref", "2026-01-01T00:00:00Z", 8, tags={}
    )
    segments = [
        Segment("111111111111", "us-east-1", "usage", ok=True),
        Segment("666666666666", "us-east-1", "usage", ok=True),
        Segment("444444444444", "us-east-1", "usage", ok=False, error_kind="denied"),
    ]

    class Provider:
        name = "mock"

        def list_inventory(self, on_segment=None):
            for seg in segments:
                on_segment(seg)
            return Inventory(
                [ami],
                [
                    Share("ami-ref", "account", "666666666666"),
                    Share("ami-ref", "account", "444444444444"),
                ],
                [
                    Usage(
                        "ami-ref", "666666666666", "us-east-1", "launch_template", "lt-1", "uat-api"
                    )
                ],
                [],
                segments,
            )

    store = Store(tmp_path / "ref.db")
    scan_id = Scanner(store, Provider(), config, clock=lambda: NOW).run()
    summary = build_graph(store, config, scan_id, "ami-ref")["used_by"]["summary"]
    assert summary == (
        "No instance uses it. Named by 1 launch template in uat. "
        "Janitor couldn't check 444444444444, so it may be used there."
    )


def test_ignored_accounts_collapse_and_raise_no_blind_spot(tmp_path, config):
    ignoring = config.model_copy(update={"ignore_accounts": ["444444444444"]})
    store = Store(tmp_path / "ign.db")
    scan_id = Scanner(
        store, MockProvider(SEED, clock=lambda: NOW, config=ignoring), ignoring, clock=lambda: NOW
    ).run()
    partner = named(store, scan_id, f"partner-export-{stamp(250)}", type="ami")
    g = build_graph(store, ignoring, scan_id, partner.id)
    labels = {n["label"] for n in g["nodes"] if n["kind"] == "account"}
    assert labels == {"1 ignored account"}
    assert g["used_by"]["summary"] == "Nothing uses it."
