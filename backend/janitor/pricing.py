"""Monthly cost estimates from AWS's price list, with a breakdown behind every number.

Rates come from fixtures/prices.json, built by scripts/fetch_prices.py. A region or rate
missing there falls back to config.pricing (or is left out), and the breakdown says so.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from janitor.config import Pricing
from janitor.models import Resource

SNAPSHOT_NOTE = "Upper bound: snapshots are incremental, so the billed size is usually smaller."
RDS_NOTE = "Upper bound: automated snapshots may be covered by free backup storage."
AMI_NOTE = "The cost of its backing snapshots. Totals that include those snapshots count them once."


@dataclass
class PriceTable:
    fallback: Pricing
    data: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None, fallback: Pricing) -> "PriceTable":
        if path and Path(path).exists():
            return cls(fallback, json.loads(Path(path).read_text()))
        return cls(fallback)

    @property
    def source_date(self) -> str | None:
        date = self.data.get("publication_date")
        return date[:10] if date else None

    def region(self, name: str) -> dict:
        return self.data.get("regions", {}).get(name, {})


class _Lines:
    def __init__(self) -> None:
        self.lines: list[dict] = []
        self.fallback = False

    def add(
        self,
        label: str,
        quantity: float,
        unit: str,
        rate: float | None,
        fallback_rate: float | None = None,
    ) -> bool:
        """Add one priced line. A missing rate uses the fallback, or the line is left out."""
        if rate is None:
            rate, self.fallback = fallback_rate, True
        if rate is None:
            return False
        self.lines.append(
            {
                "label": label,
                "quantity": quantity,
                "unit": unit,
                "rate": rate,
                "amount": round(quantity * rate, 4),
            }
        )
        return True


def _result(region: str, table: PriceTable, out: _Lines, note: str | None) -> dict:
    return {
        "region": region,
        "source_date": table.source_date,
        "estimate": note,
        "lines": out.lines,
        "fallback": out.fallback,
        "total": round(sum(line["amount"] for line in out.lines), 2),
    }


def _performance(r: Resource, vtype: str, rates: dict, out: _Lines) -> None:
    """IOPS and throughput charges. Config has no fallback rates for these."""
    if vtype == "gp3":
        extra_iops = max(0, (r.iops or 3000) - 3000)
        extra_throughput = max(0, (r.throughput or 125) - 125)
        if extra_iops:
            out.add("IOPS above 3,000", extra_iops, "IOPS-month", rates.get("gp3_iops_month"))
        if extra_throughput:
            out.add(
                "Throughput above 125 MiB/s",
                extra_throughput,
                "MiB/s-month",
                rates.get("gp3_throughput_mibps_month"),
            )
    elif vtype == "io1" and r.iops:
        out.add("Provisioned IOPS", r.iops, "IOPS-month", rates.get("io1_iops_month"))
    elif vtype == "io2" and r.iops:
        tiers = rates.get("io2_iops_month_tiers")
        if not tiers:
            out.add("Provisioned IOPS", r.iops, "IOPS-month", None)  # flags the gap
            return
        start = 0
        for cap, rate in tiers:
            top = r.iops if cap is None else min(r.iops, cap)
            if top > start:
                out.add(f"Provisioned IOPS {start + 1:,}–{top:,}", top - start, "IOPS-month", rate)
            if cap is None or r.iops <= cap:
                break
            start = cap


def breakdown(r: Resource, table: PriceTable) -> dict | None:
    """The monthly cost of one resource, line by line. AMIs are priced by apply_costs."""
    if r.size_gb is None or r.type == "ami":
        return None
    rates = table.region(r.region)
    out = _Lines()
    note = None
    if r.type == "volume":
        vtype = r.volume_type or "gp3"
        priced = out.add(
            f"Storage ({vtype})",
            r.size_gb,
            "GiB-month",
            rates.get("ebs_gb_month", {}).get(vtype),
            table.fallback.volume_gb_month.get(vtype),
        )
        if not priced:
            return None
        _performance(r, vtype, rates, out)
    elif r.type == "snapshot":
        tier = r.storage_tier or "standard"
        fallback_rate = (
            table.fallback.snapshot_archive_gb_month
            if tier == "archive"
            else table.fallback.snapshot_gb_month
        )
        out.add(
            f"Snapshot storage ({tier})",
            r.size_gb,
            "GiB-month",
            rates.get("snapshot_gb_month", {}).get(tier),
            fallback_rate,
        )
        note = SNAPSHOT_NOTE
    else:
        out.add(
            "Backup storage",
            r.size_gb,
            "GiB-month",
            rates.get("rds_snapshot_gb_month"),
            table.fallback.rds_snapshot_gb_month,
        )
        note = RDS_NOTE
    return _result(r.region, table, out, note)


def apply_costs(resources: list[Resource], table: PriceTable) -> None:
    """Set cost_breakdown and est_monthly_cost on every resource; an AMI sums its snapshots."""
    by_id = {}
    for r in resources:
        r.cost_breakdown = breakdown(r, table)
        r.est_monthly_cost = r.cost_breakdown["total"] if r.cost_breakdown else None
        by_id[r.id] = r
    for ami in (r for r in resources if r.type == "ami"):
        snaps = [by_id[s] for s in ami.snapshot_ids if s in by_id and by_id[s].cost_breakdown]
        if not snaps:
            continue
        out = _Lines()
        for s in snaps:
            out.add(f"Snapshot {s.id}", 1, "snapshot", s.est_monthly_cost)
        out.fallback = any(s.cost_breakdown["fallback"] for s in snaps)
        ami.cost_breakdown = _result(ami.region, table, out, AMI_NOTE)
        ami.est_monthly_cost = ami.cost_breakdown["total"]
