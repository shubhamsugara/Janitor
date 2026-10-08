import pytest
from helpers import NOW, SEED

from janitor.models import Inventory
from janitor.providers.mock import MockProvider
from janitor.scanner import Scanner, ScanRunning, recompute_rules
from janitor.store import Store


@pytest.fixture
def setup(tmp_path, config):
    store = Store(tmp_path / "janitor.db")
    scanner = Scanner(store, MockProvider(SEED, clock=lambda: NOW), config, clock=lambda: NOW)
    return store, scanner


def by_name(store, scan_id, name, **filters):
    items, _ = store.query_resources(scan_id, {"q": name, **filters})
    return next(r for r in items if r.name == name)


def rules_of(store, scan_id, resource):
    return {h.rule_id for h in store.rule_results(scan_id, [resource.id]).get(resource.id, [])}


def test_scan_stores_statuses_costs_and_rules(setup):
    store, scanner = setup
    scan_id = scanner.run()
    assert store.latest_scan()["id"] == scan_id
    assert by_name(store, scan_id, "dev-old-cache").est_monthly_cost == 20.0  # 200 GiB × gp2 0.10
    assert by_name(store, scan_id, "prd-ledger-archive").status == "orphaned"
    assert rules_of(store, scan_id, by_name(store, scan_id, "prd-ledger-archive")) == {"R4"}
    assert "W4" in rules_of(store, scan_id, by_name(store, scan_id, "dev-test-data"))
    actions = [e["action"] for e in store.list_audit(1, 10)[0]]
    assert actions == ["scan_finished", "scan_started"]


def test_demo_moments(setup):
    store, scanner = setup
    scan_id = scanner.run()
    assert (
        store.query_resources(scan_id, {"q": "partner-export", "type": "ami"})[0][0].status
        == "unknown"
    )
    assert by_name(store, scan_id, "copy-of-retired-api-root").status == "orphaned"
    assert by_name(store, scan_id, "prd-scratch-data").tags["env"] == "prod"
    eu_copies = store.query_resources(
        scan_id, {"type": "ami", "region": "eu-west-1", "status": "in_use"}
    )[0]
    assert len(eu_copies) == 1 and eu_copies[0].source_ami_id


def test_only_one_scan_at_a_time(setup):
    _, scanner = setup
    scanner._lock.acquire()
    try:
        assert scanner.running
        with pytest.raises(ScanRunning):
            scanner.run()
        with pytest.raises(ScanRunning):
            scanner.start()
    finally:
        scanner._lock.release()


def test_background_scan(setup):
    store, scanner = setup
    scanner.start()
    scanner.join(timeout=10)
    assert store.latest_scan() is not None and not scanner.running


def test_provider_failure_marks_scan_failed(tmp_path, config):
    class Broken:
        name = "mock"

        def list_inventory(self, on_segment=None) -> Inventory:
            raise RuntimeError("boom")

    store = Store(tmp_path / "janitor.db")
    with pytest.raises(RuntimeError):
        Scanner(store, Broken(), config, clock=lambda: NOW).run()
    assert store.last_scan()["status"] == "failed" and store.latest_scan() is None
    assert store.list_audit(1, 1)[0][0]["payload"]["error"] == "boom"


def test_config_change_takes_effect_without_rescanning(setup, config):
    store, scanner = setup
    scan_id = scanner.run()
    young = store.query_resources(scan_id, {"q": "test-build", "type": "ami"})[0][0]
    assert "R5" in rules_of(store, scan_id, young)
    relaxed = config.model_copy(deep=True)
    relaxed.policy.min_age_days = 0
    recompute_rules(store, relaxed, scan_id, NOW)
    assert "R5" not in rules_of(store, scan_id, young)


def test_scan_stores_databases(setup):
    store, scanner = setup
    scanner.run()
    assert store._db.execute("SELECT COUNT(*) FROM databases").fetchone()[0] >= 4


class Segmented:
    """A provider that returns given segments around a small inventory."""

    name = "aws"

    def __init__(self, segments, unresolved=()):
        self.segments, self.unresolved = segments, list(unresolved)

    def list_inventory(self, on_segment=None) -> Inventory:
        from helpers import days_ago

        from janitor.models import Resource

        for seg in self.segments:
            if on_segment:
                on_segment(seg)
        vol = Resource("vol-1", "volume", "111111111111", "us-east-1", "v", days_ago(5))
        return Inventory([vol], [], [], [], segments=self.segments, unresolved=self.unresolved)

    def recheck(self, items):
        return {}


def test_a_failed_segment_makes_the_scan_partial_and_it_is_still_read(tmp_path, config):
    from janitor.models import Segment, Unresolved

    segments = [
        Segment("111111111111", "us-east-1", "volume", ok=True, items=1),
        Segment("222222222222", "us-east-1", "usage", ok=False, error_kind="expired", error="x"),
    ]
    unresolved = [Unresolved("222222222222", "us-east-1", "asg", "web", "resolve:ssm:/golden")]
    store = Store(tmp_path / "janitor.db")
    scan_id = Scanner(store, Segmented(segments, unresolved), config, clock=lambda: NOW).run()
    scan = store.latest_scan()
    assert (scan["id"], scan["status"]) == (scan_id, "partial")
    assert [(s["kind"], s["ok"]) for s in store.segments(scan_id)] == [("volume", 1), ("usage", 0)]
    assert scan["notes"]["unresolved"][0]["value"] == "resolve:ssm:/golden"


def test_every_segment_failing_fails_the_scan_and_keeps_the_old_data(tmp_path, config):
    from janitor.models import Segment

    store = Store(tmp_path / "janitor.db")
    ok = Scanner(store, MockProvider(SEED, clock=lambda: NOW), config, clock=lambda: NOW).run()
    down = [
        Segment(
            "111111111111",
            "us-east-1",
            "volume",
            ok=False,
            error_kind="denied",
            error="ec2:DescribeVolumes",
        )
    ]
    Scanner(store, Segmented(down), config, clock=lambda: NOW).run()
    assert store.last_scan()["status"] == "failed"
    assert store.latest_scan()["id"] == ok
    assert store.segments(store.last_scan()["id"])[0]["error_kind"] == "denied"


def test_segment_messages(config):
    from janitor.models import Segment
    from janitor.scanner import segment_message

    def msg(kind, error=""):
        return segment_message(
            Segment("222222222222", "us-east-1", "usage", False, 0, kind, error), config
        )

    assert msg("expired") == "AWS session expired. Refresh your MFA session, then Scan now."
    assert msg("denied", "ec2:DescribeInstances") == (
        "Janitor isn't allowed to call ec2:DescribeInstances in dev · us-east-1. "
        "Ask for read access, then Scan now."
    )
    assert (
        msg("throttled")
        == "AWS throttled requests in dev · us-east-1. Scan again in a few minutes."
    )
    assert "isn't read-only" in msg("blocked")
    assert msg("other", "Endpoint unreachable") == (
        "Endpoint unreachable. Scan again; if it repeats, check the server log."
    )
