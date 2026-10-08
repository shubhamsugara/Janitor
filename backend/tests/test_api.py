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
    names = {a["name"] for a in meta["accounts"]}
    assert names == {"tools", "sbx", "dev", "uat", "qas", "prd", "444444444444"}  # 444 discovered
    assert "older than 90 days" in meta["definitions"]["statuses"]["orphaned"]["meaning"]


def test_overview(client):
    body = client.get("/api/overview").json()
    assert body["last_scan"]["status"] == "partial"  # the demo's unreachable account
    assert {f["account"] for f in body["segments_failed"]} == {"444444444444"}
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
    assert [r["id"] for r in body["rules"]] == ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "W1", "W2", "W3", "W4", "W5", "W6", "W7"]
    assert next(r for r in body["rules"] if r["id"] == "R1")["outcome"] == "block"
    assert {u["ref_name"] for u in body["related"]["usage"]} == {
        "dev-api-1",
        "prd-api-asg",
        "qas-api-1",
        "uat-api v3",
        # the seed's EC2 deployments (sbx has none of this AMI)
        "dev-api-3.1.0-21",
        "dev-api-3.2.0-22",
        "qas-api-3.1.0-9",
        "uat-api-3.1.0-11",
        "prd-api-3.0.5-31",
        "prd-api-3.0.4-30",
        "dev-worker-1.8.0-8",
        "prd-worker-1.7.2-6",
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
    r = _r

    class Provider:
        name = "mock"

        def list_inventory(self, on_segment=None):
            return Inventory(
                [
                    r("ami-a", "ami", snapshot_ids=["snap-shared"], name="web-1"),
                    r("ami-b", "ami", snapshot_ids=["snap-shared"], name="web-2"),
                    r("snap-shared", "snapshot"),
                    *_newer_versions(),
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

        def list_inventory(self, on_segment=None):
            return Inventory([*resources, *_newer_versions()], [], [], [])

    store = Store(tmp_path / "j.db")
    Scanner(store, Provider(), config, clock=lambda: NOW).run()
    return store


def _r(id, type, **kw):
    fields = {
        "account": "111111111111",
        "region": "us-east-1",
        "name": "web-1" if type == "ami" else id,  # with _newer_versions(), R6 keeps those
        "created_at": "2026-01-01T00:00:00Z",
        "tags": {"owner": "me"},
    } | kw
    return Resource(id=id, type=type, **fields)


def _newer_versions():
    """Three newer AMIs in the web-* group, so R6 keeps them and not the AMI under test."""
    return [
        _r(f"ami-new{n}", "ami", name=f"web-{n}", created_at="2026-03-01T00:00:00Z")
        for n in (7, 8, 9)
    ]


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
    assert body["root"] == ami["id"] and body["used_by"]["total"] == 2  # instances only
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
    assert [r["rule_id"] for r in body["blocked"][0]["rules"]] == ["R1", "R5", "R6", "W1"]


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


def test_bad_dates_are_rejected(client):
    response = client.get("/api/resources", params={"created_from": "31/01/2026"})
    assert response.status_code == 422 and "YYYY-MM-DD" in response.json()["detail"]
    assert client.get("/api/stats", params={"created_to": "2026-02-30"}).status_code == 422


def test_stats_route_follows_filters(client):
    all_volumes = client.get("/api/stats", params={"type": "volume"}).json()
    prd = client.get("/api/stats", params={"type": "volume", "account": "333333333333"}).json()
    assert 0 < prd["total"] < all_volumes["total"]
    assert [b["key"] for b in prd["by_account"]] == ["333333333333"]
    assert all_volumes["blocked"] + all_volumes["deletable"] == all_volumes["total"]


def test_header_stats_report_orphaned_size_and_cost(client):
    stats = client.get("/api/resources", params={"type": "volume"}).json()["stats"]
    assert 0 < stats["orphaned_gib"] < stats["size_gib"]
    assert stats["orphaned_usd"] < stats["est_monthly_usd"]


def test_export_csv_route(client):
    response = client.get(
        "/api/resources/export.csv", params={"type": "volume", "status": "orphaned"}
    )
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert 'filename="janitor-volume-20261001.csv"' in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    total = client.get("/api/stats", params={"type": "volume", "status": "orphaned"}).json()[
        "total"
    ]
    assert len(lines) == total + 1


def test_export_filename_ignores_unknown_type(client):
    response = client.get("/api/resources/export.csv", params={"type": 'x"\r\nSet-Cookie: a=b'})
    assert response.status_code == 200
    assert (
        response.headers["content-disposition"] == 'attachment; filename="janitor-all-20261001.csv"'
    )


def test_export_json_route(client):
    body = client.get("/api/resources/export.json", params={"type": "snapshot"}).json()
    assert body["total"] == len(body["items"]) and body["truncated"] is False
    assert body["stats"]["total"] == body["total"] and body["filters"] == {"type": "snapshot"}
    assert body["provider"] == "mock" and body["generated_at"] == "2026-10-01T00:00:00Z"


def test_export_rejects_bad_sort(client):
    assert client.get("/api/resources/export.csv", params={"sort": "nope"}).status_code == 422


def test_selected_snapshot_that_is_blocked_on_its_own_makes_the_plan_mixed(tmp_path, config):
    retained = {"owner": "me", "retain": "true"}
    store = _store_with(
        tmp_path,
        config,
        [_r("ami-a", "ami", snapshot_ids=["snap-a"]), _r("snap-a", "snapshot", tags=retained)],
    )
    body = plans.make_plan(store, config, ["ami-a", "snap-a"], NOW)
    assert body["variant"] == "mixed"
    assert [(i["id"], i["parent"]) for i in body["blocked"]] == [
        ("snap-a", None)
    ]  # counted as selected
    assert [i["id"] for i in body["deletable"]] == ["ami-a"]


class FakeAws:
    """An injected provider: one ok segment, one failed for dev with an expired session."""

    name = "mock"  # keeps the startup scan synchronous

    def __init__(self, fail_all=False):
        self.fail_all = fail_all

    def list_inventory(self, on_segment=None):
        from janitor.models import Segment

        segments = [
            Segment(
                "111111111111",
                "us-east-1",
                "volume",
                ok=not self.fail_all,
                items=1,
                error_kind="denied" if self.fail_all else "",
                error="ec2:DescribeVolumes",
            ),
            Segment(
                "222222222222", "us-east-1", "usage", ok=False, error_kind="expired", error="x"
            ),
        ]
        for seg in segments:
            if on_segment:
                on_segment(seg)
        return Inventory([_r("vol-1", "volume")], [], [], [], segments=segments)

    def recheck(self, items):
        return {}


def _settings(tmp_path):
    return Settings(
        config_path=str(EXAMPLE),
        db_path=str(tmp_path / "janitor.db"),
        seed_path=str(SEED),
        static_dir=str(tmp_path),
        prices_path=str(TEST_PRICES),
    )


def test_failed_checks_reach_overview_and_scan_progress(tmp_path):
    client = TestClient(create_app(_settings(tmp_path), clock=lambda: NOW, provider=FakeAws()))
    overview = client.get("/api/overview").json()
    assert overview["last_scan"]["status"] == "partial"
    (failed,) = overview["segments_failed"]
    assert (failed["account_name"], failed["region"], failed["kind"]) == (
        "dev",
        "us-east-1",
        "usage",
    )
    assert "Refresh your MFA session" in failed["message"]
    assert overview["newest_failed"] is None
    latest = client.get("/api/scans/latest").json()
    assert latest["progress"] == {"done": 2, "failed": 1}
    assert len(latest["segments"]) == 2


def test_a_failed_newest_scan_keeps_showing_the_previous_one(tmp_path):
    app = create_app(_settings(tmp_path), clock=lambda: NOW, provider=FakeAws())
    shown = app.state.store.latest_scan()["id"]
    app.state.scanner._provider = FakeAws(fail_all=True)
    app.state.scanner.run()
    overview = TestClient(app).get("/api/overview").json()
    assert overview["last_scan"]["id"] == shown
    assert "isn't allowed to call ec2:DescribeVolumes" in overview["newest_failed"]["message"]


def test_aws_mode_refuses_a_missing_admin_profile(tmp_path, monkeypatch):
    from aws_helpers import write_aws_config

    from janitor.providers.session import ProfileError

    write_aws_config(tmp_path, monkeypatch)
    config_file = tmp_path / "aws-config"
    config_file.write_text(
        config_file.read_text().replace("[profile example-tools]", "[profile other]")
    )
    monkeypatch.setenv("JANITOR_PROVIDER", "aws")
    with pytest.raises(ProfileError, match="example-tools"):
        create_app(_settings(tmp_path), clock=lambda: NOW)


def test_live_recheck_skips_a_changed_ami_and_keeps_its_snapshots(tmp_path, config):
    store = Store(tmp_path / "j.db")
    from janitor.providers.mock import MockProvider

    Scanner(store, MockProvider(SEED, clock=lambda: NOW), config, clock=lambda: NOW).run()
    ami = store.query_resources(store.latest_scan()["id"], {"q": f"base-linux-{stamp(120)}"})[0][0]
    made = plans.make_plan(store, config, [ami.id], NOW)
    seen = []

    def recheck(items):
        seen.extend(items)
        return {ami.id: "Instance i-1 in dev now uses it."}

    result = plans.simulate(store, config, made["plan_id"], "", recheck=recheck)
    assert {i["id"] for i in seen} == {i["id"] for i in made["deletable"]}
    ami_seen = next(i for i in seen if i["id"] == ami.id)
    assert {s["principal"] for s in ami_seen["shares"]} >= {"222222222222"}
    assert result["would_delete"] == []
    reasons = {s["id"]: (s["rule"], s["reason"]) for s in result["skipped"]}
    assert reasons[ami.id] == ("Changed since the scan", "Instance i-1 in dev now uses it.")
    snap = next(i["id"] for i in made["deletable"] if i["parent"] == ami.id)
    assert reasons[snap][1] == f"Kept because {ami.id} is now blocked."
    entry = store.list_audit(1, 1)[0][0]
    assert {i["id"]: i["outcome"] for i in entry["payload"]["items"]}[ami.id] == "skipped"


def test_switching_to_aws_does_not_show_mock_data(tmp_path):
    create_app(_settings(tmp_path), clock=lambda: NOW)  # mock scan into the shared database

    class AwsNamed(FakeAws):
        name = "aws"

    app = create_app(_settings(tmp_path), clock=lambda: NOW, provider=AwsNamed())
    app.state.scanner.join(timeout=10)  # with no AWS scan yet, one starts in the background
    overview = TestClient(app).get("/api/overview").json()
    assert overview["last_scan"]["provider"] == "aws"


def test_share_impact_marks_accounts_whose_usage_check_failed(tmp_path, config):
    from janitor.providers.mock import MockProvider

    store = Store(tmp_path / "j.db")
    scan_id = Scanner(store, MockProvider(SEED, clock=lambda: NOW), config, clock=lambda: NOW).run()
    partner = store.query_resources(scan_id, {"q": "partner-export", "type": "ami"})[0][0]
    impact = plans._share_impact(
        store, config, scan_id, {"id": partner.id, "region": partner.region}
    )
    assert impact["accounts"] == [{"id": "444444444444", "name": "444444444444", "scanned": False}]
    base = store.query_resources(
        scan_id, {"q": f"base-linux-{stamp(20)}", "type": "ami", "region": "us-east-1"}
    )[0][0]
    impact = plans._share_impact(store, config, scan_id, {"id": base.id, "region": base.region})
    assert all(a["scanned"] for a in impact["accounts"])


def test_share_impact_follows_the_usage_check_not_the_config(tmp_path, config):
    from janitor.models import Segment, Share

    class Provider:
        name = "mock"

        def list_inventory(self, on_segment=None):
            segments = [
                Segment("111111111111", "us-east-1", "usage", ok=True),
                Segment("222222222222", "us-east-1", "usage", ok=False, error_kind="expired"),
            ]
            for seg in segments:
                on_segment(seg)
            return Inventory(
                [_r("ami-a", "ami")], [Share("ami-a", "account", "222222222222")], [], [], segments
            )

        def recheck(self, items):
            return {}

    store = Store(tmp_path / "j.db")
    scan_id = Scanner(store, Provider(), config, clock=lambda: NOW).run()
    impact = plans._share_impact(store, config, scan_id, {"id": "ami-a", "region": "us-east-1"})
    assert impact["accounts"] == [{"id": "222222222222", "name": "dev", "scanned": False}]


def test_meta_lists_accounts_discovered_during_the_scan(tmp_path):
    from janitor.models import Segment

    class Discovering(FakeAws):
        def list_inventory(self, on_segment=None):
            seg = Segment("444444444444", "us-east-1", "volume", ok=True)
            on_segment(seg)
            return Inventory([_r("vol-1", "volume")], [], [], [], segments=[seg])

    client = TestClient(create_app(_settings(tmp_path), clock=lambda: NOW, provider=Discovering()))
    accounts = {a["id"]: a for a in client.get("/api/meta").json()["accounts"]}
    assert accounts["444444444444"]["name"] == "444444444444"
    assert accounts["111111111111"]["name"] == "tools"  # the admin comes first
    assert list(accounts)[0] == "111111111111"
    assert "owns" not in accounts["111111111111"]


def test_meta_says_which_accounts_have_each_type(client):
    by_type = client.get("/api/meta").json()["accounts_by_type"]
    assert by_type["ami"] == ["111111111111"]  # only the admin owns AMIs
    assert "222222222222" in by_type["volume"] and len(by_type["volume"]) > 1


def test_deployments_list_every_app_with_its_ami(client):
    body = client.get("/api/deployments").json()
    assert body["scan_id"]
    # Only the seed's unreachable partner account: Janitor couldn't check its deployments.
    assert {(f["account"], f["kind"]) for f in body["failed"]} == {
        ("444444444444", "usage"),
        ("444444444444", "ecs"),
    }
    items = body["items"]
    assert {i["kind"] for i in items} == {"ec2", "ecs"}
    live = next(i for i in items if i["name"] == "prd-api-3.0.5-31")
    assert (live["env"], live["app"], live["version"], live["account_name"]) == (
        "prd",
        "api",
        "3.0.5",
        "prd",
    )
    assert live["ami"]["name"] == f"base-linux-{stamp(20)}"
    assert live["ami"]["status"] == "in_use"
    orders = next(i for i in items if i["kind"] == "ecs" and i["env"] == "qas")
    assert (orders["state"], orders["ami"]) == ("failed", None)


def test_deployments_show_failed_usage_and_ecs_checks_only(tmp_path):
    from janitor.models import Segment

    class Failing:
        name = "aws"

        def list_inventory(self, on_segment=None):
            from janitor.models import Inventory

            segments = [
                Segment(
                    "222222222222",
                    "us-east-1",
                    "ecs",
                    ok=False,
                    error_kind="denied",
                    error="ecs:ListClusters",
                ),
                Segment("222222222222", "us-east-1", "volume", ok=False, error_kind="throttled"),
                Segment("111111111111", "us-east-1", "ami", ok=True),
            ]
            for seg in segments:
                on_segment and on_segment(seg)
            return Inventory([], [], [], [], segments=segments)

        def recheck(self, items):
            return {}

    settings = Settings(
        config_path=str(EXAMPLE), db_path=str(tmp_path / "j.db"), prices_path=str(TEST_PRICES)
    )
    app = create_app(settings, clock=lambda: NOW, provider=Failing())
    app.state.scanner.join(5)  # an AWS-named provider scans in the background at startup
    failed = TestClient(app).get("/api/deployments").json()["failed"]
    assert [(f["kind"], f["account_name"]) for f in failed] == [("ecs", "dev")]
    assert "ecs:ListClusters" in failed[0]["message"]


def test_meta_rule_outcome_follows_policy(tmp_path):
    import yaml

    data = yaml.safe_load(EXAMPLE.read_text())
    data["policy"]["rds_last_copy"] = "block"
    path = tmp_path / "janitor.yaml"
    path.write_text(yaml.safe_dump(data))
    settings = _settings(tmp_path)
    settings.config_path = str(path)
    client = TestClient(create_app(settings, clock=lambda: NOW))
    rules = {r["id"]: r for r in client.get("/api/meta").json()["definitions"]["rules"]}
    assert (rules["W2"]["outcome"], rules["W1"]["outcome"]) == ("block", "warn")
    assert "3 newest" in rules["R6"]["explanation"]


@pytest.mark.parametrize("pattern", ["(unclosed", "x" * 201, "a{4294967296}"])
def test_bad_name_regex_is_400(client, pattern):
    for route in ("/api/resources", "/api/stats", "/api/resources/export.json"):
        response = client.get(route, params={"name_regex": pattern})
        assert response.status_code == 400, route
        assert response.json()["detail"].startswith("That name pattern isn't")


def test_filters_apply_to_stats_and_export(client):
    params = {"type": "ami", "name_regex": "^BASE-linux", "region": "us-east-1"}
    body = client.get("/api/resources", params=params).json()
    assert body["total"] == 7 and all(i["name"].startswith("base-linux") for i in body["items"])
    assert client.get("/api/stats", params=params).json()["total"] == 7
    assert client.get("/api/resources/export.json", params=params).json()["total"] == 7
    source = find(client, "ami", f"base-linux-{stamp(20)}")["id"]
    copies = client.get("/api/resources", params={"type": "ami", "source_ami": source}).json()
    assert [i["region"] for i in copies["items"]] == ["us-west-2"]
    db = client.get(
        "/api/resources", params={"type": "rds_snapshot", "source_db": "dev-legacy"}
    ).json()
    assert db["total"] == 2


def plan_matching(client, filter, exclude=(), type="ami"):
    return client.post(
        "/api/actions/plan",
        json={"type": type, "selection": {"filter": filter, "exclude": list(exclude)}},
    )


def _top_level(body):
    return sorted(i["id"] for i in body["blocked"] + body["deletable"] if i["parent"] is None)


def test_plan_by_selection_resolves_with_exclude(client):
    filter = {"name_regex": "^base-linux", "region": "us-east-1"}
    listed = client.get("/api/resources", params={"type": "ami", **filter}).json()["items"]
    skip = listed[0]["id"]
    body = plan_matching(client, filter, exclude=[skip]).json()
    assert _top_level(body) == sorted(i["id"] for i in listed if i["id"] != skip)
    audit = client.get("/api/audit").json()["items"][0]
    assert audit["action"] == "plan"


def test_selection_type_comes_from_the_request(client):
    body = plan_matching(client, {"type": "volume", "region": "us-east-1"}, type="ami").json()
    assert {i["type"] for i in body["blocked"] + body["deletable"] if i["parent"] is None} == {
        "ami"
    }


def test_selection_resolves_against_current_scan(client):
    latest = client.get("/api/scans/latest").json()["scan"]["id"]
    assert plan_matching(client, {"region": "eu-west-1"}).json()["scan_id"] == latest


def test_selection_over_limit_is_400(client, monkeypatch):
    monkeypatch.setattr(plans, "MAX_SELECTION", 3)
    response = plan_matching(client, {"region": "us-east-1"})
    assert response.status_code == 400
    assert response.json()["detail"].endswith(
        "resources match. Narrow the filters to 3 or fewer, then plan again."
    )


def test_selection_matching_nothing_is_422(client):
    response = plan_matching(client, {"name_regex": "^nothing-matches$"})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body", [{"type": "ami"}, {"type": "ami", "ids": ["x"], "selection": {"filter": {}}}]
)
def test_plan_needs_exactly_one_of_ids_or_selection(client, body):
    assert client.post("/api/actions/plan", json=body).status_code == 422


def test_selection_filter_is_validated(client):
    assert plan_matching(client, {"name_regex": "(bad"}).status_code == 400
    assert plan_matching(client, {"name_regex": "a{4294967296}"}).status_code == 400
    assert plan_matching(client, {"created_from": "yesterday"}).status_code == 422
