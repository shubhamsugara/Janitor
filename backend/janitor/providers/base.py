"""The read-only provider interface. There is no delete, modify, or tag method to call."""

from typing import Protocol

from janitor.models import Inventory


class CloudProvider(Protocol):
    name: str

    def list_inventory(self) -> Inventory: ...
