from helpers import TEST_PRICES

from janitor.config import Pricing
from janitor.models import Resource
from janitor.pricing import PriceTable, apply_costs, breakdown

TABLE = PriceTable.load(TEST_PRICES, Pricing())


def res(**kw):
    fields = {
        "id": "vol-1",
        "type": "volume",
        "account": "111111111111",
        "region": "us-east-1",
        "name": "v",
        "created_at": "2026-01-01T00:00:00Z",
        "size_gb": 100,
        "volume_type": "gp3",
    } | kw
    return Resource(**fields)


def amounts(b):
    return [(line["label"], line["amount"]) for line in b["lines"]]


def test_gp3_storage_iops_and_throughput():
    b = breakdown(res(iops=6000, throughput=250), TABLE)
    assert amounts(b) == [
        ("Storage (gp3)", 8.0),
        ("IOPS above 3,000", 15.0),
        ("Throughput above 125 MiB/s", 5.0),
    ]
    assert b["total"] == 28.0 and b["fallback"] is False and b["source_date"] == "2026-09-30"


def test_gp3_at_baseline_has_no_extras():
    assert amounts(breakdown(res(iops=3000, throughput=125), TABLE)) == [("Storage (gp3)", 8.0)]


def test_io1_provisioned_iops():
    b = breakdown(res(volume_type="io1", iops=3000), TABLE)
    assert amounts(b) == [("Storage (io1)", 12.5), ("Provisioned IOPS", 195.0)]


def test_io2_iops_are_tiered():
    b = breakdown(res(volume_type="io2", iops=40000), TABLE)
    assert amounts(b) == [
        ("Storage (io2)", 12.5),
        ("Provisioned IOPS 1–32,000", 2080.0),
        ("Provisioned IOPS 32,001–40,000", 364.0),
    ]


def test_snapshot_tiers_carry_the_upper_bound_note():
    standard = breakdown(res(type="snapshot", volume_type=None), TABLE)
    archive = breakdown(res(type="snapshot", volume_type=None, storage_tier="archive"), TABLE)
    assert amounts(standard) == [("Snapshot storage (standard)", 5.0)]
    assert amounts(archive) == [("Snapshot storage (archive)", 1.25)]
    assert standard["estimate"].startswith("Upper bound")


def test_rds_snapshot():
    b = breakdown(res(type="rds_snapshot", volume_type=None), TABLE)
    assert amounts(b) == [("Backup storage", 9.5)] and b["estimate"].startswith("Upper bound")


def test_missing_region_falls_back_to_config():
    b = breakdown(res(region="eu-west-1"), TABLE)
    assert amounts(b) == [("Storage (gp3)", 8.0)] and b["fallback"] is True


def test_missing_performance_rate_is_flagged():
    b = breakdown(res(region="eu-west-1", iops=6000), TABLE)
    assert amounts(b) == [("Storage (gp3)", 8.0)] and b["fallback"] is True


def test_ami_costs_its_snapshots():
    snap = res(id="snap-1", type="snapshot", volume_type=None, size_gb=8)
    ami = res(id="ami-1", type="ami", volume_type=None, size_gb=8, snapshot_ids=["snap-1"])
    apply_costs([ami, snap], TABLE)
    assert snap.est_monthly_cost == 0.4 and ami.est_monthly_cost == 0.4
    assert ami.cost_breakdown["lines"][0]["label"] == "Snapshot snap-1"


def test_est_monthly_cost_equals_breakdown_total(inventory):
    apply_costs(inventory.resources, TABLE)
    for r in inventory.resources:
        if r.cost_breakdown:
            assert r.est_monthly_cost == round(
                sum(x["amount"] for x in r.cost_breakdown["lines"]), 2
            )


def test_no_price_file_means_config_rates(tmp_path):
    table = PriceTable.load(tmp_path / "missing.json", Pricing())
    assert table.data == {} and table.source_date is None
    assert breakdown(res(), table)["fallback"] is True
