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
    assert by_name(store, scan_id, "prod-ledger-archive").status == "orphaned"
    assert rules_of(store, scan_id, by_name(store, scan_id, "prod-ledger-archive")) == {"R4"}
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
    assert by_name(store, scan_id, "prod-scratch-data").tags["env"] == "prod"
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

        def list_inventory(self) -> Inventory:
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
