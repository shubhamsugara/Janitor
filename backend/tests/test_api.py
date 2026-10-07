from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from helpers import EXAMPLE, NOW, SEED, TEST_PRICES, stamp

from janitor import plans
from janitor.main import Settings, create_app
from janitor.models import Inventory, Resource
from janitor.scanner import Scanner
from janitor.store import Store


@pytest.fixture
def app(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html><head></head><body>spa</body></html>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    settings = Settings(
        config_path=str(EXAMPLE),
        db_path=str(tmp_path / "janitor.db"),
        seed_path=str(SEED),
        static_dir=str(static),
        prices_path=str(TEST_PRICES),
    )
    return create_app(settings, clock=lambda: NOW)


@pytest.fixture
def client(app):
    return TestClient(app)


def find(client, type, name, region="us-east-1"):
    items = client.get("/api/resources", params={"type": type, "q": name, "region": region}).json()[
        "items"
    ]
    return next(i for i in items if i["name"] == name)


def plan(client, *ids):
    return client.post("/api/actions/plan", json={"ids": list(ids)})


def test_health_and_meta(client):
    assert client.get("/health").json() == {"status": "ok"}
    meta = client.get("/api/meta").json()
    assert meta["provider"] == "mock" and meta["read_only"] is True
    assert {a["name"] for a in meta["accounts"]} == {"tools", "sbx", "dev", "uat", "qas", "prd"}
    assert "older than 90 days" in meta["definitions"]["statuses"]["orphaned"]["meaning"]


def test_overview(client):
    body = client.get("/api/overview").json()
    assert body["last_scan"]["status"] == "ok"
    assert {t["type"] for t in body["types"]} == {"ami", "snapshot", "volume", "rds_snapshot"}


def test_empty_database_returns_empty_results(tmp_path):
    settings = Settings(
        config_path=str(EXAMPLE),
        db_path=str(tmp_path / "j.db"),
        seed_path=str(SEED),
        static_dir=str(tmp_path),
        scan_on_startup=False,
    )
    client = TestClient(create_app(settings, clock=lambda: NOW))
    assert client.get("/api/overview").json()["last_scan"] is None
    assert client.get("/api/resources").json() == {
        "items": [],
        "total": 0,
        "stats": None,
        "scan_id": None,
    }
    assert plan(client, "vol-1").status_code == 409


def test_resource_list_filters_paginates_and_reports_stats(client):
    body = client.get(
        "/api/resources", params={"type": "ami", "status": "orphaned", "page_size": 2}
    ).json()
    assert len(body["items"]) == 2 and body["total"] > 2
    assert all(i["status"] == "orphaned" for i in body["items"])
    assert (
        body["stats"]["total"] == body["total"] and body["stats"]["est_monthly_usd"] > 0
    )  # AMIs cost their snapshots
    assert {"outcome", "status_reason", "tags"} <= set(body["items"][0])
    assert client.get("/api/resources", params={"sort": "nope"}).status_code == 422


def test_resource_detail(client):
    ami = find(client, "ami", f"base-linux-{stamp(20)}")
    body = client.get(f"/api/resources/{ami['id']}").json()
    assert body["resource"]["status"] == "in_use"
    assert [r["id"] for r in body["rules"]] == ["R1", "R2", "R3", "R4", "R5", "W4"]
    assert next(r for r in body["rules"] if r["id"] == "R1")["outcome"] == "block"
    assert {u["ref_name"] for u in body["related"]["usage"]} == {
        "dev-api-1",
        "prd-api-asg",
        "qas-api-1",
        "uat-api v3",
    }
    assert any(link["relation"] == "copy" for link in body["related"]["links"])
    assert client.get("/api/resources/vol-nope").status_code == 404


def test_rds_detail_by_arn(client):
    rds = client.get("/api/resources", params={"type": "rds_snapshot", "q": "dev-legacy"}).json()[
        "items"
    ][0]
    assert client.get(f"/api/resources/{quote(rds['id'], safe='')}").status_code == 200


def test_plan_all_blocked(client):
    body = plan(client, find(client, "ami", f"base-linux-{stamp(20)}")["id"]).json()
    assert body["variant"] == "all_blocked" and body["deletable"] == []
    assert "R1" in {r["rule_id"] for r in body["blocked"][0]["rules"]}


def test_plan_none_blocked_expands_ami_to_its_snapshot(client):
    ami = find(client, "ami", f"base-linux-{stamp(120)}")
    body = plan(client, ami["id"]).json()
    assert body["variant"] == "none_blocked" and not body["requires_typed_confirmation"]
    assert [(i["type"], i["parent"]) for i in body["deletable"]] == [
        ("ami", None),
        ("snapshot", ami["id"]),
    ]
    assert body["totals"] == {"count": 2, "size_gib": 8, "est_monthly_usd": 0.4}
    [impact] = body["share_impact"]
    assert {a["name"] for a in impact["accounts"]} == {"sbx", "dev", "uat", "qas", "prd"}


def test_plan_mixed_and_share_impact_lists_copies(client):
    used = find(client, "ami", f"base-linux-{stamp(20)}")["id"]
    source = find(client, "ami", f"base-linux-{stamp(200)}")["id"]
    body = plan(client, used, source).json()
    assert body["variant"] == "mixed"
    impact = next(s for s in body["share_impact"] if s["ami_id"] == source)
    assert [c["region"] for c in impact["copies"]] == ["eu-west-1"]


def test_plan_reports_missing_ids(client):
    vol = find(client, "volume", "dev-old-cache")["id"]
    body = plan(client, vol, "vol-0000000000000dead").json()
    assert body["missing"] == ["vol-0000000000000dead"] and body["variant"] == "none_blocked"
    assert plan(client, "vol-0000000000000dead").status_code == 404
    assert plan(client).status_code == 422


def test_typed_confirmation_for_prod_and_warnings(client):
    prod = plan(client, find(client, "volume", "prd-scratch-data")["id"]).json()
    assert prod["requires_typed_confirmation"]
    warned = plan(client, find(client, "volume", "dev-test-data")["id"]).json()
    assert warned["requires_typed_confirmation"]
    refused = client.post(
        "/api/actions/simulate", json={"plan_id": prod["plan_id"], "confirmation": ""}
    )
    assert refused.status_code == 422 and "Type delete" in refused.json()["detail"]
    done = client.post(
        "/api/actions/simulate", json={"plan_id": prod["plan_id"], "confirmation": "delete"}
    )
    assert done.status_code == 200 and len(done.json()["would_delete"]) == 1


def test_simulate_writes_audit(client):
    used = find(client, "ami", f"base-linux-{stamp(20)}")["id"]
    deletable = find(client, "ami", f"base-linux-{stamp(120)}")["id"]
    body = plan(client, used, deletable).json()
    result = client.post("/api/actions/simulate", json={"plan_id": body["plan_id"]}).json()
    assert len(result["would_delete"]) == 2 and [s["id"] for s in result["skipped"]] == [used]
    entry = client.get("/api/audit").json()["items"][0]
    assert entry["action"] == "simulate"
    assert {i["outcome"] for i in entry["payload"]["items"]} == {"would_delete", "skipped"}


def test_simulate_after_rescan_is_refused(client, app):
    body = plan(client, find(client, "volume", "dev-old-cache")["id"]).json()
    assert client.post("/api/scans").status_code == 202
    app.state.scanner.join(timeout=10)
    assert (
        client.post("/api/actions/simulate", json={"plan_id": body["plan_id"]}).status_code == 409
    )
    assert client.post("/api/actions/simulate", json={"plan_id": "nope"}).status_code == 404


def test_scan_conflict_and_latest(client, app):
    app.state.scanner._lock.acquire()
    try:
        assert client.post("/api/scans").status_code == 409
        assert client.get("/api/scans/latest").json()["running"] is True
    finally:
        app.state.scanner._lock.release()


def test_shared_snapshot_is_not_expanded(tmp_path, config):
    def r(id, type, **kw):
        return Resource(
            id=id,
            type=type,
            account="111111111111",
            region="us-east-1",
            name=id,
            created_at="2026-01-01T00:00:00Z",
            tags={"owner": "me"},
            **kw,
        )

    class Provider:
        name = "mock"

        def list_inventory(self):
            return Inventory(
                [
                    r("ami-a", "ami", snapshot_ids=["snap-shared"]),
                    r("ami-b", "ami", snapshot_ids=["snap-shared"]),
                    r("snap-shared", "snapshot"),
                ],
                [],
                [],
                [],
            )

    store = Store(tmp_path / "j.db")
    Scanner(store, Provider(), config, clock=lambda: NOW).run()
    alone = plans.make_plan(store, config, ["ami-a"], NOW)
    assert [i["id"] for i in alone["deletable"]] == ["ami-a"]
    both = plans.make_plan(store, config, ["ami-a", "ami-b"], NOW)
    assert [i["id"] for i in both["deletable"]] == ["ami-a", "ami-b", "snap-shared"]


def test_spa_is_served_with_fallback(client):
    assert "spa" in client.get("/").text
    assert "spa" in client.get("/amis").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    missing = client.get("/api/nope")
    assert missing.status_code == 404 and missing.json() == {"detail": "Not found."}


def _store_with(tmp_path, config, resources):
    class Provider:
        name = "mock"

        def list_inventory(self):
            return Inventory(resources, [], [], [])

    store = Store(tmp_path / "j.db")
    Scanner(store, Provider(), config, clock=lambda: NOW).run()
    return store


def _r(id, type, **kw):
    fields = {
        "account": "111111111111",
        "region": "us-east-1",
        "name": id,
        "created_at": "2026-01-01T00:00:00Z",
        "tags": {"owner": "me"},
    } | kw
    return Resource(id=id, type=type, **fields)


def test_managed_backing_snapshot_is_blocked(tmp_path, config):
    store = _store_with(
        tmp_path,
        config,
        [
            _r("ami-a", "ami", snapshot_ids=["snap-a"]),
            _r("snap-a", "snapshot", managed_by="aws_backup"),
        ],
    )
    body = plans.make_plan(store, config, ["ami-a"], NOW)
    assert [i["id"] for i in body["deletable"]] == ["ami-a"]
    assert [(i["id"], i["rules"][0]["rule_id"]) for i in body["blocked"]] == [("snap-a", "R3")]


def test_env_prod_tag_key_case_requires_typing(tmp_path, config):
    store = _store_with(
        tmp_path, config, [_r("vol-a", "volume", tags={"owner": "me", "Env": "PROD"})]
    )
    assert plans.make_plan(store, config, ["vol-a"], NOW)["requires_typed_confirmation"]


def test_simulate_refuses_after_config_change(tmp_path, config):
    store = _store_with(tmp_path, config, [_r("vol-a", "volume")])
    plan_id = plans.make_plan(store, config, ["vol-a"], NOW)["plan_id"]
    changed = config.model_copy(deep=True)
    changed.policy.protected_tags["keep"] = "yes"
    with pytest.raises(plans.PlanError) as refused:
        plans.simulate(store, changed, plan_id, "")
    assert refused.value.status_code == 409
    assert len(plans.simulate(store, config, plan_id, "")["would_delete"]) == 1


def test_volume_cost_has_a_breakdown(client):
    vol = find(client, "volume", "prd-scratch-data")
    labels = [line["label"] for line in vol["cost_breakdown"]["lines"]]
    assert labels[0] == "Storage (io2)" and "Provisioned IOPS 32,001–40,000" in labels
    assert vol["est_monthly_cost"] == vol["cost_breakdown"]["total"]


def test_graph_route(client):
    ami = find(client, "ami", f"base-linux-{stamp(20)}")
    body = client.get(f"/api/resources/{ami['id']}/graph").json()
    assert body["root"] == ami["id"] and body["used_by"]["total"] == 4
    assert client.get("/api/resources/ami-0000000000000dead/graph").status_code == 404


def test_graph_route_with_arn(client):
    rds = client.get("/api/resources", params={"type": "rds_snapshot", "q": "dev-orders"}).json()[
        "items"
    ][0]
    assert client.get(f"/api/resources/{quote(rds['id'], safe='')}/graph").status_code == 200
    assert (
        client.get(f"/api/resources/{quote(rds['id'], safe='')}").json()["resource"]["id"]
        == rds["id"]
    )


def test_selected_snapshot_goes_with_its_ami(tmp_path, config):
    store = _store_with(
        tmp_path, config, [_r("ami-a", "ami", snapshot_ids=["snap-a"]), _r("snap-a", "snapshot")]
    )
    body = plans.make_plan(store, config, ["ami-a", "snap-a"], NOW)
    assert body["variant"] == "none_blocked"
    assert [(i["id"], i["parent"]) for i in body["deletable"]] == [
        ("ami-a", None),
        ("snap-a", "ami-a"),
    ]


def test_selected_snapshot_of_a_blocked_ami_stays_blocked(tmp_path, config):
    retained = {"owner": "me", "retain": "true"}
    store = _store_with(
        tmp_path,
        config,
        [_r("ami-a", "ami", snapshot_ids=["snap-a"], tags=retained), _r("snap-a", "snapshot")],
    )
    body = plans.make_plan(store, config, ["ami-a", "snap-a"], NOW)
    assert body["variant"] == "all_blocked" and {i["id"] for i in body["blocked"]} == {
        "ami-a",
        "snap-a",
    }


def test_plan_rules_are_in_rule_order(client):
    body = plan(client, find(client, "ami", f"base-linux-{stamp(20)}")["id"]).json()
    assert [r["rule_id"] for r in body["blocked"][0]["rules"]] == ["R1", "R5"]


def test_skipped_items_name_their_rule(client):
    used = find(client, "ami", f"base-linux-{stamp(20)}")["id"]
    deletable = find(client, "ami", f"base-linux-{stamp(120)}")["id"]
    body = plan(client, used, deletable).json()
    result = client.post("/api/actions/simulate", json={"plan_id": body["plan_id"]}).json()
    assert [(s["id"], s["rule"]) for s in result["skipped"]] == [(used, "In use")]
    assert result["skipped"][0]["reason"].startswith("Used by")


def test_meta_exposes_policy_and_price_source(client):
    meta = client.get("/api/meta").json()
    assert meta["policy"] == {
        "orphan_after_days": 90,
        "min_age_days": 30,
        "typed_confirm_min_items": 10,
    }
    assert meta["prices"] == {"source_date": "2026-09-30", "fallback": False}


def test_huge_page_number_is_rejected_not_a_server_error(client):
    assert client.get("/api/resources", params={"page": 10**20}).status_code == 422
    assert client.get("/api/audit", params={"page": 10**20}).status_code == 422
