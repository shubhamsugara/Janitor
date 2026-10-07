import importlib.util
import json
from datetime import timedelta

import pytest
from helpers import NOW, ROOT, SEED

from janitor.models import TYPES, parse_ts
from janitor.providers.base import CloudProvider
from janitor.providers.mock import MockProvider


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mock_inventory_has_every_type(inventory):
    assert {r.type for r in inventory.resources} == set(TYPES)
    assert inventory.shares and inventory.usage and inventory.databases


def test_timestamps_shift_with_the_clock():
    first = MockProvider(SEED, clock=lambda: NOW).list_inventory().resources[0]
    later = MockProvider(SEED, clock=lambda: NOW + timedelta(days=10)).list_inventory().resources[0]
    assert parse_ts(later.created_at) - parse_ts(first.created_at) == timedelta(days=10)


@pytest.mark.parametrize("cls", [CloudProvider, MockProvider])
def test_provider_interface_is_read_only(cls):
    """Lock 1 (spec §10): the only callable is a read. Update this list deliberately."""
    methods = [n for n in dir(cls) if not n.startswith("_") and callable(getattr(cls, n))]
    assert methods == ["list_inventory"]


def test_seed_file_matches_generator():
    assert _load_script("make_seed").build() == json.loads(SEED.read_text())


def test_usage_active_reflects_its_state():
    from janitor.models import Usage

    def use(ref_type, state):
        return Usage("ami-1", "222222222222", "us-east-1", ref_type, "x", "x", state)

    assert use("instance", "running").active is True
    assert use("instance", "stopped").active is False
    assert use("asg", "active").active is True
    assert use("asg", "inactive").active is False
    assert use("launch_template", "").active is None


def test_seed_has_running_and_stopped_users(inventory):
    states = {(u.ref_type, u.ref_state) for u in inventory.usage}
    assert {("instance", "running"), ("instance", "stopped"), ("asg", "active")} <= states
    volumes = [r for r in inventory.resources if r.type == "volume"]
    assert any(v.volume_type == "io2" and v.iops for v in volumes)
    assert any(r.storage_tier == "archive" for r in inventory.resources)
