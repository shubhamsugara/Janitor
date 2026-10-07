import pytest
from helpers import EXAMPLE, NOW, SEED

from janitor.config import load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "JANITOR_PROVIDER",
        "JANITOR_CONFIG",
        "JANITOR_DB",
        "JANITOR_SEED",
        "JANITOR_STATIC_DIR",
        "JANITOR_PRICES",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def config():
    return load_config(EXAMPLE)


@pytest.fixture
def inventory():
    from janitor.providers.mock import (
        MockProvider,  # imported here so config tests run before Task 1 Step 8
    )

    return MockProvider(SEED, clock=lambda: NOW).list_inventory()
