"""Serves the committed seed fixture.

Timestamps shift by (now - anchor), so every resource keeps the age it had when the seed
was generated and the demo looks the same on any day.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from janitor.models import Database, Inventory, Resource, Share, Usage, format_ts, parse_ts


class MockProvider:
    name = "mock"

    def __init__(self, seed_path: str | Path, clock: Callable[[], datetime] | None = None):
        self._seed = json.loads(Path(seed_path).read_text())
        self._clock = clock or (lambda: datetime.now(UTC))

    def list_inventory(self) -> Inventory:
        shift = self._clock() - parse_ts(self._seed["anchor"])
        resources = []
        for item in self._seed["resources"]:
            resource = Resource(**item)
            resource.created_at = format_ts(parse_ts(resource.created_at) + shift)
            resources.append(resource)
        return Inventory(
            resources=resources,
            shares=[Share(**s) for s in self._seed["shares"]],
            usage=[Usage(**u) for u in self._seed["usage"]],
            databases=[Database(**d) for d in self._seed["databases"]],
        )
