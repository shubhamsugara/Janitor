"""The read-only provider interface, and the scan plan both providers share.

There is no delete, modify, or tag method to call.
"""

from collections.abc import Callable
from typing import Protocol

from janitor.config import Config
from janitor.models import Inventory, Resource, Segment, Share

# What owning a type means Janitor must list. RDS snapshots are judged by their source databases.
KINDS_FOR = {
    "ami": ("ami",),
    "snapshot": ("snapshot",),
    "volume": ("volume",),
    "rds_snapshot": ("rds_snapshot", "database"),
}

OnSegment = Callable[[Segment], None]


class CloudProvider(Protocol):
    name: str

    def list_inventory(self, on_segment: OnSegment | None = None) -> Inventory: ...

    def recheck(self, items: list[dict]) -> dict[str, str]:
        """Re-read would-delete items live; return {id: reason} for any that must be skipped."""
        ...


def phase_one(config: Config) -> list[tuple[str, str, str]]:
    """(account, region, kind) for every resource list; usage comes after, from the shares found."""
    return [
        (account_id, region, kind)
        for account_id, account in config.accounts.items()
        for region in config.regions_for(account_id)
        for owned in account.owns
        for kind in KINDS_FOR[owned]
    ]


def usage_pairs(config: Config, amis: list[Resource], shares: list[Share]) -> list[tuple[str, str]]:
    """The owner in each of its regions, plus each scanned account an AMI is shared with, in that
    AMI's region. Launch permissions are region-scoped, so other regions can't use it.
    """
    owner = config.owner.account
    pairs = {(owner, region) for region in config.regions_for(owner)}
    region_of = {ami.id: ami.region for ami in amis}
    for share in shares:
        region = region_of.get(share.image_id)
        if (
            share.principal_type == "account"
            and share.principal in config.accounts
            and region in config.regions_for(share.principal)
        ):
            pairs.add((share.principal, region))
    return sorted(pairs)
