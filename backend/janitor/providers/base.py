"""The read-only provider interface, and the scan plan both providers share.

There is no delete, modify, or tag method to call.
"""

from collections.abc import Callable
from typing import Protocol

from janitor.config import Config
from janitor.models import Inventory, Segment, Share

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
MEMBER_KINDS = ("snapshot", "volume", "rds_snapshot", "database", "usage")


def first_phase(config: Config) -> list[tuple[str, str, str]]:
    """The admin's own lists, in every region. Usage waits for the AMI IDs."""
    return [
        (config.admin.account, region, kind) for region in config.regions for kind in ADMIN_FIRST
    ]


def member_accounts(config: Config, shares: list[Share]) -> list[str]:
    """Every account an AMI is shared with, plus every listed account; never the admin."""
    found = {s.principal for s in shares if s.principal_type == "account"} | set(config.accounts)
    return sorted(found - {config.admin.account})


def second_phase(config: Config, members: list[str]) -> list[tuple[str, str, str]]:
    """Usage in the admin account, then each member's lists and usage, in every region."""
    admin = [(config.admin.account, region, "usage") for region in config.regions]
    return admin + [
        (account, region, kind)
        for account in members
        for region in config.regions
        for kind in MEMBER_KINDS
    ]
