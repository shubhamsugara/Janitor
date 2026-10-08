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
    account_names: dict[str, str]  # display names; discovered accounts show their ID
    orphan_after_days: int
    now: datetime
    failed: set[tuple[str, str, str]] = field(default_factory=set)  # (account, region, kind)
    scanned: set[tuple[str, str]] | None = None  # (account, region); None means everywhere
    ignored: set[str] = field(default_factory=set)  # never checked, and never held against an AMI

    @classmethod
    def from_config(
        cls, config: Config, now: datetime, segments: Iterable[Segment] = ()
    ) -> "LinkContext":
        return cls(
            owner_account=config.admin.account,
            account_names={config.admin.account: config.admin.name}
            | {account_id: a.name for account_id, a in config.accounts.items()},
            orphan_after_days=config.policy.orphan_after_days,
            now=now,
            failed={(s.account, s.region, s.kind) for s in segments if not s.ok},
            # Accounts are discovered during the scan, so "scanned" means a usage check ran there.
            scanned={(s.account, s.region) for s in segments if s.kind == "usage"} or None,
            ignored=set(config.ignore_accounts),
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


REFERENCE_NOUNS = {
    "launch_template": "Launch template",
    "asg": "Auto Scaling group",
    "launch_config": "Launch configuration",
}


def references(inventory: Inventory, ctx: LinkContext) -> dict[str, str]:
    """{ami_id: sentence} for AMIs that templates, ASGs, or launch configs still name (W6).

    Only references a permitted account could launch, in the AMI's own region, count.
    """
    amis = {r.id: r for r in inventory.resources if r.type == "ami"}
    permitted: dict[str, set[str]] = {i: {a.account} for i, a in amis.items()}
    for share in inventory.shares:
        if share.principal_type == "account" and share.image_id in permitted:
            permitted[share.image_id].add(share.principal)
    found: dict[str, list[Usage]] = defaultdict(list)
    for u in inventory.usage:
        ami = amis.get(u.image_id)
        if (
            ami
            and u.ref_type in REFERENCE_NOUNS
            and u.region == ami.region
            and u.account in permitted[ami.id]
        ):
            found[ami.id].append(u)
    out = {}
    for ami_id, refs in found.items():
        named = [
            f"{REFERENCE_NOUNS[u.ref_type]} {u.ref_name or u.ref_id} in {ctx.name(u.account)}"
            for u in refs[:2]
        ]
        if len(refs) == 1:
            out[ami_id] = f"{named[0]} still names it, so its next launch would fail."
        else:
            names = (
                f"{named[0]}, {named[1]}, and {len(refs) - 2} more"
                if len(refs) > 2
                else (f"{named[0]} and {named[1]}")
            )
            out[ami_id] = f"{names} still name it, so their next launch would fail."
    return out


def ignored_shares(inventory: Inventory, ctx: LinkContext) -> dict[str, str]:
    """{ami_id: "id, id"} for AMIs shared with accounts the config ignores (W7)."""
    found: dict[str, list[str]] = defaultdict(list)
    for share in inventory.shares:
        if share.principal_type == "account" and share.principal in ctx.ignored:
            found[share.image_id].append(share.principal)
    return {ami_id: ", ".join(sorted(set(ids))) for ami_id, ids in found.items()}


def _managed(r: Resource) -> tuple[str, str]:
    return "managed", MANAGED_REASONS.get(r.managed_by, "Created by an AWS-managed service.")


def _ami(r: Resource, shares: list[Share], usage: list[Usage], ctx: LinkContext) -> tuple[str, str]:
    # Launch permissions are region-scoped, so only usage in the AMI's own region counts.
    shares = [s for s in shares if s.principal not in ctx.ignored]  # the user vouched for these
    permitted = {r.account} | {s.principal for s in shares if s.principal_type == "account"}
    refs = [u for u in usage if u.account in permitted and u.ref_type == "instance"]
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
        return "orphaned", f"No instance uses it in {r.region}, and it is {age} days old."
    return "idle", f"No instance uses it in {r.region}, but it is only {age} days old."


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
