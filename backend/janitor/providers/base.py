"""The read-only provider interface, and the scan plan both providers share.

There is no delete, modify, or tag method to call.
"""

from collections.abc import Callable
from typing import Protocol

from janitor.config import Config
from janitor.models import Inventory, Resource, Segment, Share

OnSegment = Callable[[Segment], None]


class CloudProvider(Protocol):
    name: str

    def list_inventory(self, on_segment: OnSegment | None = None) -> Inventory: ...

    def recheck(self, items: list[dict]) -> dict[str, str]:
        """Re-read would-delete items live; return {id: reason} for any that must be skipped."""
        ...


ADMIN_FIRST = (
    "ami",
    "snapshot",
    "volume",
)  # AMIs first: their launch permissions name the accounts
MEMBER_KINDS = ("snapshot", "volume", "rds_snapshot", "database", "usage", "ecs")


def first_phase(config: Config) -> list[tuple[str, str, str]]:
    """The admin's own lists, in every region. Usage waits for the AMI IDs."""
    return [
        (config.admin.account, region, kind) for region in config.regions for kind in ADMIN_FIRST
    ]


def member_accounts(config: Config, shares: list[Share]) -> list[str]:
    """Every account an AMI is shared with, plus every listed account; never the admin, and never
    an ignored account."""
    found = {s.principal for s in shares if s.principal_type == "account"} | set(config.accounts)
    return sorted(found - {config.admin.account} - set(config.ignore_accounts))


def second_phase(
    config: Config, members: list[str], amis: list[Resource], shares: list[Share]
) -> list[tuple[str, str, str]]:
    """Usage and ECS services in the admin account, then each member's lists, usage, and ECS.

    A member's resources and ECS services are listed in its own regions. Its usage is also checked wherever an
    admin AMI is shared with it: launch permissions are region-scoped, so an AMI in us-east-1
    shared with an EU-only account can still be launched there, and only a check proves it isn't.
    """
    shared_in: dict[str, set[str]] = {}
    region_of = {a.id: a.region for a in amis}
    for share in shares:
        if share.principal_type == "account" and share.image_id in region_of:
            shared_in.setdefault(share.principal, set()).add(region_of[share.image_id])
    plan = [(config.admin.account, r, k) for r in config.regions for k in ("usage", "ecs")]
    for account in members:
        own = config.regions_for(account)
        plan += [(account, region, kind) for region in own for kind in MEMBER_KINDS]
        plan += [
            (account, region, "usage")
            for region in sorted(shared_in.get(account, set()) - set(own))
        ]
    return plan
