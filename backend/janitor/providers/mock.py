"""Serves the committed seed fixture.

Timestamps shift by (now - anchor), so every resource keeps the age it had when the seed
was generated and the demo looks the same on any day.
"""

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from janitor.config import Config, load_config
from janitor.models import (
    Database,
    Inventory,
    Resource,
    Segment,
    Share,
    Usage,
    format_ts,
    parse_ts,
)
from janitor.providers.base import OnSegment, first_phase, member_accounts, second_phase

EXAMPLE = Path(__file__).resolve().parents[3] / "config" / "janitor.example.yaml"


class MockProvider:
    name = "mock"

    def __init__(
        self,
        seed_path: str | Path,
        clock: Callable[[], datetime] | None = None,
        config: Config | None = None,
    ):
        self._seed = json.loads(Path(seed_path).read_text())
        self._clock = clock or (lambda: datetime.now(UTC))
        self._config = config

    def list_inventory(self, on_segment: OnSegment | None = None) -> Inventory:
        inventory = self._read()
        inventory.segments = self._segments(inventory)
        for seg in inventory.segments:
            if on_segment:
                on_segment(seg)
        return inventory

    def recheck(self, items: list[dict]) -> dict[str, str]:
        return {}  # the fixture never changes behind Janitor's back

    def _segments(self, inv: Inventory) -> list[Segment]:
        """Every check the AWS provider would run, with the rows each would return.

        The seed's unreachable accounts fail every check, as a member role that can't be assumed
        would, so the demo shows an AMI that can't be proven unused.
        """
        config = self._config or load_config(EXAMPLE)
        counts: Counter = Counter()
        for r in inv.resources:
            counts[(r.account, r.region, r.type)] += 1
        for d in inv.databases:
            counts[(d.account, d.region, "database")] += 1
        for u in inv.usage:
            counts[(u.account, u.region, "usage")] += 1
        members = member_accounts(config, inv.shares)
        amis = [r for r in inv.resources if r.type == "ami"]
        planned = first_phase(config) + second_phase(config, members, amis, inv.shares)
        unreachable = set(self._seed.get("unreachable", []))
        return [
            Segment(a, r, k, ok=False, error_kind="denied", error="sts:AssumeRole")
            if a in unreachable
            else Segment(a, r, k, ok=True, items=counts[(a, r, k)])
            for a, r, k in planned
        ]

    def _read(self) -> Inventory:
        shift = self._clock() - parse_ts(self._seed["anchor"])
        resources = []
        for item in self._seed["resources"]:
            resource = Resource(**item)
            resource.created_at = format_ts(parse_ts(resource.created_at) + shift)
            resources.append(resource)
        unreachable = set(self._seed.get("unreachable", []))  # a failed check contributes no rows
        return Inventory(
            resources=[r for r in resources if r.account not in unreachable],
            shares=[Share(**s) for s in self._seed["shares"]],
            usage=[Usage(**u) for u in self._seed["usage"] if u["account"] not in unreachable],
            databases=[
                Database(**d) for d in self._seed["databases"] if d["account"] not in unreachable
            ],
        )
