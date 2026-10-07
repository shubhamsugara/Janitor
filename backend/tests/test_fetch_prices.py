import importlib.util

from helpers import ROOT

spec = importlib.util.spec_from_file_location("fetch_prices", ROOT / "scripts" / "fetch_prices.py")
fetch_prices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_prices)

HEADER = [
    "SKU",
    "TermType",
    "StartingRange",
    "EndingRange",
    "Unit",
    "PricePerUnit",
    "Product Family",
    "Location Type",
    "Volume API Name",
    "usageType",
]


def line(*values):
    return ",".join(f'"{v}"' for v in values) + "\n"


SAMPLE = [
    line("FormatVersion", "v1.0"),
    line("Publication Date", "2026-09-30T19:15:12Z"),
    line(*HEADER),
    line(
        "A",
        "OnDemand",
        "0",
        "Inf",
        "GB-Mo",
        "0.0800000000",
        "Storage",
        "AWS Region",
        "gp3",
        "EBS:VolumeUsage.gp3",
    ),
    line(
        "B",
        "OnDemand",
        "0",
        "Inf",
        "GB-Mo",
        "0.0960000000",
        "Storage",
        "AWS Local Zone",
        "gp3",
        "USE1-BOS1-EBS:VolumeUsage.gp3",
    ),
    # Real shape (checked 2026-10-07): one usage type per io2 tier, every range 0–Inf.
    line(
        "C",
        "OnDemand",
        "0",
        "Inf",
        "IOPS-Mo",
        "0.065",
        "System Operation",
        "AWS Region",
        "io2",
        "EBS:VolumeP-IOPS.io2",
    ),
    line(
        "D",
        "OnDemand",
        "0",
        "Inf",
        "IOPS-Mo",
        "0.0455",
        "System Operation",
        "AWS Region",
        "io2",
        "EBS:VolumeP-IOPS.io2.tier2",
    ),
    line(
        "E",
        "OnDemand",
        "0",
        "Inf",
        "IOPS-Mo",
        "0.03185",
        "System Operation",
        "AWS Region",
        "io2",
        "EBS:VolumeP-IOPS.io2.tier3",
    ),
    # io2 storage is priced per "GB-month", the other volume types per "GB-Mo".
    line(
        "J",
        "OnDemand",
        "0",
        "Inf",
        "GB-month",
        "0.125",
        "Storage",
        "AWS Region",
        "io2",
        "EBS:VolumeUsage.io2",
    ),
    line(
        "F",
        "OnDemand",
        "3000",
        "Inf",
        "IOPS-Mo",
        "0.005",
        "System Operation",
        "AWS Region",
        "gp3",
        "EBS:VolumeP-IOPS.gp3",
    ),
    line(
        "G",
        "OnDemand",
        "0",
        "Inf",
        "GiBps-mo",
        "40.96",
        "Provisioned Throughput",
        "AWS Region",
        "gp3",
        "EBS:VolumeP-Throughput.gp3",
    ),
    line(
        "H",
        "OnDemand",
        "0",
        "Inf",
        "GB-Mo",
        "0.05",
        "Storage Snapshot",
        "AWS Region",
        "",
        "EBS:SnapshotUsage",
    ),
    line(
        "I",
        "Reserved",
        "0",
        "Inf",
        "GB-Mo",
        "0.01",
        "Storage",
        "AWS Region",
        "gp2",
        "EBS:VolumeUsage.gp2",
    ),
]


def test_reads_publication_date_and_rates():
    date, data = fetch_prices.rows(SAMPLE)
    rates = {}
    fetch_prices.collect(data, rates)
    fetch_prices.finalize(rates)
    assert date == "2026-09-30T19:15:12Z"
    assert rates["ebs_gb_month"] == {
        "gp3": 0.08,
        "io2": 0.125,
    }  # local zone and reserved rows ignored
    assert rates["io2_iops_month_tiers"] == [[32000, 0.065], [64000, 0.0455], [None, 0.03185]]
    assert rates["gp3_iops_month"] == 0.005
    assert rates["gp3_throughput_mibps_month"] == 0.04  # per GiB/s converted to per MiB/s
    assert rates["snapshot_gb_month"] == {"standard": 0.05}


def test_reports_missing_rates():
    missing = fetch_prices.missing({"ebs_gb_month": {"gp3": 0.08}})
    assert "rds_snapshot_gb_month" in missing and "ebs_gb_month.gp2" in missing
    assert "snapshot_gb_month.archive" in missing
