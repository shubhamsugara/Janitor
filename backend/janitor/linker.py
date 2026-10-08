"""Compute each resource's status and a one-sentence reason. Pure: no I/O.

Precedence: in_use > managed > unknown > orphaned > idle (spec §6).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from janitor.config import Config
from janitor.models import Inventory, Resource, Segment, Share, Usage, age_days

UNPROVABLE_SHARES = {
    "group": "is public",
    "org": "is shared with an organization",
    "ou": "is shared with an organizational unit",
}
MANAGED_REASONS = {
    "aws_backup": "Created by AWS Backup. Manage it through its backup plan.",
    "dlm": "Created by a Data Lifecycle Manager policy. Manage it through that policy.",
    "rds_automated": "An automated RDS backup. RDS removes it when its retention period ends.",
}


@dataclass
class LinkContext:
    owner_account: str
    account_names: dict[str, str]  # every account Janitor scans
    orphan_after_days: int
    now: datetime
    failed: set[tuple[str, str, str]] = field(default_factory=set)  # (account, region, kind)
    scanned: set[tuple[str, str]] | None = None  # (account, region); None means everywhere

    @classmethod
    def from_config(
        cls, config: Config, now: datetime, segments: Iterable[Segment] = ()
    ) -> "LinkContext":
        return cls(
            owner_account=config.owner.account,
            account_names={account_id: a.name for account_id, a in config.accounts.items()},
            orphan_after_days=config.policy.orphan_after_days,
            now=now,
            failed={(s.account, s.region, s.kind) for s in segments if not s.ok},
            scanned={(a, region) for a in config.accounts for region in config.regions_for(a)},
        )

    def name(self, account_id: str) -> str:
        return self.account_names.get(account_id, account_id)

    def is_scanned(self, account_id: str, region: str) -> bool:
        return self.scanned is None or (account_id, region) in self.scanned

    def check_failed(self, account_id: str, region: str, kind: str) -> bool:
        return (account_id, region, kind) in self.failed


def link(inventory: Inventory, ctx: LinkContext) -> dict[str, tuple[str, str]]:
    """Return {resource_id: (status, reason)} for every resource in the inventory."""
    amis = {r.id: r for r in inventory.resources if r.type == "ami"}
    volumes = {(r.account, r.region, r.id) for r in inventory.resources if r.type == "volume"}
    databases = {(d.account, d.region, d.id) for d in inventory.databases}
    shares: dict[str, list[Share]] = defaultdict(list)
    for share in inventory.shares:
        shares[share.image_id].append(share)
    usage: dict[tuple[str, str], list[Usage]] = defaultdict(list)
    for use in inventory.usage:
        usage[(use.image_id, use.region)].append(use)
    backing: dict[str, list[str]] = defaultdict(
        list
    )  # snapshot -> AMIs whose block-device map names it
    for ami in amis.values():
        for snap_id in ami.snapshot_ids:
            backing[snap_id].append(ami.id)

    result = {}
    for r in inventory.resources:
        if r.type == "ami":
            result[r.id] = _ami(r, shares[r.id], usage[(r.id, r.region)], ctx)
        elif r.type == "snapshot":
            result[r.id] = _snapshot(r, amis, backing[r.id], volumes, ctx)
        elif r.type == "volume":
            result[r.id] = _volume(r, ctx)
        else:
            result[r.id] = _rds_snapshot(r, databases, ctx)
    return result


def _managed(r: Resource) -> tuple[str, str]:
    return "managed", MANAGED_REASONS.get(r.managed_by, "Created by an AWS-managed service.")


def _ami(r: Resource, shares: list[Share], usage: list[Usage], ctx: LinkContext) -> tuple[str, str]:
    # Launch permissions are region-scoped, so only usage in the AMI's own region counts.
    permitted = {r.account} | {s.principal for s in shares if s.principal_type == "account"}
    refs = [u for u in usage if u.account in permitted]
    if refs:
        first = refs[0]
        more = f" and {len(refs) - 1} more" if len(refs) > 1 else ""
        label = first.ref_type.replace("_", " ")
        return (
            "in_use",
            f"Used by {label} {first.ref_name or first.ref_id} in {ctx.name(first.account)}{more}.",
        )
    if r.managed_by:
        return _managed(r)
    for share in shares:
        if share.principal_type in UNPROVABLE_SHARES:
            return (
                "unknown",
                f"It {UNPROVABLE_SHARES[share.principal_type]}, so Janitor can't prove nothing uses it.",
            )
        if share.principal not in ctx.account_names:
            return (
                "unknown",
                f"It is shared with account {share.principal}, which Janitor doesn't scan.",
            )
        if share.principal_type == "account" and not ctx.is_scanned(share.principal, r.region):
            return (
                "unknown",
                f"It is shared with {ctx.name(share.principal)}, but Janitor doesn't scan "
                f"{ctx.name(share.principal)} in {r.region}.",
            )
    for account_id in sorted(permitted):
        if ctx.check_failed(account_id, r.region, "usage"):
            return (
                "unknown",
                f"Janitor couldn't read what {ctx.name(account_id)} uses in {r.region}, so it "
                "can't prove nothing uses it.",
            )
    age = age_days(r.created_at, ctx.now)
    if age >= ctx.orphan_after_days:
        return "orphaned", f"Nothing uses it in {r.region}, and it is {age} days old."
    return "idle", f"Nothing uses it in {r.region}, but it is only {age} days old."


def _snapshot(
    r: Resource,
    amis: dict[str, Resource],
    backing: list[str],
    volumes: set[tuple[str, str, str]],
    ctx: LinkContext,
) -> tuple[str, str]:
    registered = list(backing)
    if r.linked_ami_id in amis and r.linked_ami_id not in registered:
        registered.append(r.linked_ami_id)
    if registered:
        ami = amis[registered[0]]
        return "in_use", f"It backs {ami.id} ({ami.name}), which is still registered."
    if r.managed_by:
        return _managed(r)
    if r.account == ctx.owner_account and ctx.check_failed(r.account, r.region, "ami"):
        return "unknown", (
            f"Janitor couldn't list AMIs in {ctx.name(r.account)} {r.region}, so it can't tell "
            "whether an AMI uses it."
        )
    if r.linked_ami_id:
        if r.account != ctx.owner_account:
            return "unknown", (
                f"It names {r.linked_ami_id}, an AMI in {ctx.name(r.account)}, "
                "where Janitor doesn't list AMIs."
            )
        return (
            "orphaned",
            f"Its description names {r.linked_ami_id}, which is no longer registered.",
        )
    if r.source_volume_id and (r.account, r.region, r.source_volume_id) in volumes:
        return "idle", f"Its source volume {r.source_volume_id} still exists."
    if r.source_volume_id and ctx.check_failed(r.account, r.region, "volume"):
        return "unknown", (
            f"Janitor couldn't list volumes in {ctx.name(r.account)} {r.region}, so it can't tell "
            f"whether {r.source_volume_id} still exists."
        )
    age = age_days(r.created_at, ctx.now)
    if age >= ctx.orphan_after_days:
        return "orphaned", f"Its source volume is gone, and it is {age} days old."
    return "idle", f"Its source volume is gone, but it is only {age} days old."


def _volume(r: Resource, ctx: LinkContext) -> tuple[str, str]:
    if r.attached_instance:
        return "in_use", f"Attached to {r.attached_instance}."
    age = age_days(r.created_at, ctx.now)
    if age >= ctx.orphan_after_days:
        return "orphaned", f"Not attached, and created {age} days ago."
    return "idle", f"Not attached, but created only {age} days ago."


def _rds_snapshot(
    r: Resource, databases: set[tuple[str, str, str]], ctx: LinkContext
) -> tuple[str, str]:
    if r.managed_by:
        return _managed(r)
    kind = "cluster" if r.db_kind == "cluster" else "DB instance"
    if (r.account, r.region, r.source_db_id) in databases:
        return "idle", f"A manual snapshot. Its source {kind} {r.source_db_id} still exists."
    if ctx.check_failed(r.account, r.region, "database"):
        return "unknown", (
            f"Janitor couldn't list databases in {ctx.name(r.account)} {r.region}, so it can't "
            f"tell whether {kind} {r.source_db_id} still exists."
        )
    age = age_days(r.created_at, ctx.now)
    if age >= ctx.orphan_after_days:
        return "orphaned", f"Its source {kind} {r.source_db_id} is gone, and it is {age} days old."
    return "idle", f"Its source {kind} {r.source_db_id} is gone, but it is only {age} days old."
