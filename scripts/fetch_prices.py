#!/usr/bin/env python3
"""Build fixtures/prices.json from AWS's public Price List bulk files. Stdlib only.

Usage: python3 scripts/fetch_prices.py [region ...]   (default: us-east-1 us-west-2 eu-west-1)

The EC2 file is about 300 MB per region, so rows are streamed and filtered, never held in
memory. Exits 1 if any rate Janitor needs is missing, so a renamed usage type gets noticed.
"""

import csv
import io
import json
import sys
import urllib.request
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

BASE = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{offer}/current/{region}/index.csv"
OUT = Path(__file__).resolve().parents[1] / "fixtures" / "prices.json"
DEFAULT_REGIONS = ["us-east-1", "us-west-2", "eu-west-1"]
VOLUME_TYPES = ("gp3", "gp2", "io1", "io2", "st1", "sc1", "standard")
# io2 IOPS: one usage type per tier, each listed 0–Inf, so the caps come from AWS's docs.
IO2_TIERS = {
    "VolumeP-IOPS.io2": 32000,
    "VolumeP-IOPS.io2.tier2": 64000,
    "VolumeP-IOPS.io2.tier3": None,
}
REQUIRED = [
    "gp3_iops_month",
    "gp3_throughput_mibps_month",
    "io1_iops_month",
    "io2_iops_month_tiers",
    "rds_snapshot_gb_month",
]


def rows(lines: Iterable[str]) -> tuple[str | None, Iterator[dict]]:
    """Split a price-list CSV into its publication date and its data rows (as dicts)."""
    lines = iter(lines)
    date = None
    for line in lines:  # metadata lines come before the header
        if line.startswith('"Publication Date"'):
            date = next(csv.reader([line]))[1]
        elif line.startswith('"SKU"'):
            header = next(csv.reader([line]))
            return date, (
                dict(zip(header, values, strict=False)) for values in csv.reader(lines)
            )
    return date, iter(())


def collect(data: Iterable[dict], rates: dict) -> None:
    """Fold the on-demand, in-region rows Janitor needs into one region's `rates`."""
    for row in data:
        if (
            row.get("TermType") != "OnDemand"
            or row.get("Location Type", "AWS Region") != "AWS Region"
        ):
            continue
        try:
            price = float(row.get("PricePerUnit") or "")
        except ValueError:
            continue
        usage = row.get("usageType", "")
        unit = row.get("Unit", "")
        api = row.get("Volume API Name", "")
        if (
            row.get("Product Family") == "Storage"
            and api in VOLUME_TYPES
            and unit in ("GB-Mo", "GB-month")  # io2 storage uses the long form
        ):
            rates.setdefault("ebs_gb_month", {})[api] = price
        elif usage.endswith("EBS:VolumeP-IOPS.gp3") and price > 0:
            rates["gp3_iops_month"] = price
        elif usage.endswith("EBS:VolumeP-Throughput.gp3") and price > 0:
            per_gib = unit.lower().startswith("gibps")
            rates["gp3_throughput_mibps_month"] = (
                round(price / 1024, 6) if per_gib else price
            )
        elif usage.endswith("EBS:VolumeP-IOPS.piops"):
            rates["io1_iops_month"] = price
        elif (tier := usage.rpartition("EBS:")[2]) in IO2_TIERS:
            rates.setdefault("_io2", {})[IO2_TIERS[tier]] = price
        elif usage.endswith("EBS:SnapshotUsage") and unit == "GB-Mo":
            rates.setdefault("snapshot_gb_month", {})["standard"] = price
        elif usage.endswith("EBS:SnapshotArchiveStorage"):
            rates.setdefault("snapshot_gb_month", {})["archive"] = price
        elif usage.endswith("RDS:ChargedBackupUsage"):
            rates["rds_snapshot_gb_month"] = price


def finalize(rates: dict) -> dict:
    io2 = rates.pop("_io2", None)
    if io2:
        rates["io2_iops_month_tiers"] = sorted(
            ([cap, price] for cap, price in io2.items()),
            key=lambda tier: float("inf") if tier[0] is None else tier[0],
        )
    return rates


def missing(rates: dict) -> list[str]:
    gaps = [key for key in REQUIRED if key not in rates]
    gaps += [
        f"ebs_gb_month.{t}"
        for t in VOLUME_TYPES
        if t not in rates.get("ebs_gb_month", {})
    ]
    gaps += [
        f"snapshot_gb_month.{t}"
        for t in ("standard", "archive")
        if t not in rates.get("snapshot_gb_month", {})
    ]
    return gaps


def fetch_lines(url: str) -> Iterator[str]:
    with urllib.request.urlopen(url, timeout=120) as response:
        yield from io.TextIOWrapper(response, encoding="utf-8", newline="")


def main(argv: list[str]) -> int:
    regions = argv or DEFAULT_REGIONS
    out = {
        "currency": "USD",
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "publication_date": None,
        "regions": {},
        "source": [],
    }
    problems = []
    for region in regions:
        rates: dict = {}
        for offer in ("AmazonEC2", "AmazonRDS"):
            url = BASE.format(offer=offer, region=region)
            print(f"Reading {url}", file=sys.stderr)
            date, data = rows(fetch_lines(url))
            collect(data, rates)
            out["source"].append(url)
            if offer == "AmazonEC2" and date:
                out["publication_date"] = date
        out["regions"][region] = finalize(rates)
        problems += [f"{region}: {gap}" for gap in missing(rates)]
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(f"Wrote {OUT}")
    for problem in problems:
        print(f"Missing rate: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
