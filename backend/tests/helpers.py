"""Constants shared by tests. NOW equals the seed's anchor, so seed ages are exact."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from janitor.models import format_ts

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "config" / "janitor.example.yaml"
SEED = ROOT / "fixtures" / "seed.json"
NOW = datetime(2026, 10, 1, tzinfo=UTC)
TOOLS, DEV, PROD, UNSCANNED = "111111111111", "222222222222", "333333333333", "444444444444"


def stamp(days: int) -> str:
    """The 14-digit timestamp the seed puts in names."""
    return (NOW - timedelta(days=days)).strftime("%Y%m%d%H%M%S")


def days_ago(days: int) -> str:
    return format_ts(NOW - timedelta(days=days))


SBX, UAT, QAS = "555555555555", "666666666666", "777777777777"
