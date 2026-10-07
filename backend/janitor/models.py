"""Records shared by the provider, linker, rules, and store."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

TYPES = ("ami", "snapshot", "volume", "rds_snapshot")
STATUSES = ("in_use", "managed", "unknown", "orphaned", "idle")


@dataclass
class Resource:
    id: str  # native ID for EC2; the snapshot ARN for RDS
    type: str
    account: str
    region: str
    name: str
    created_at: str  # ISO 8601 UTC, e.g. "2026-01-31T12:00:00Z"
    size_gb: int | None = None
    state: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    snapshot_ids: list[str] = field(default_factory=list)  # AMI: snapshots in its block-device map
    source_ami_id: str | None = None  # AMI copy: the AMI it was copied from
    linked_ami_id: str | None = None  # snapshot: the AMI its description names
    source_volume_id: str | None = None  # snapshot
    attached_instance: str | None = None  # volume
    volume_type: str | None = None  # volume
    source_db_id: str | None = None  # RDS snapshot
    db_kind: str | None = None  # RDS snapshot: "instance" or "cluster"
    managed_by: str | None = None  # "aws_backup", "dlm", or "rds_automated"
    est_monthly_cost: float | None = None
    status: str = ""
    status_reason: str = ""


@dataclass
class Share:
    image_id: str
    principal_type: str  # "account", "group", "org", or "ou"
    principal: str


@dataclass
class Usage:
    image_id: str
    account: str
    region: str
    ref_type: str  # "instance", "launch_template", "asg", or "launch_config"
    ref_id: str
    ref_name: str = ""


@dataclass
class Database:
    id: str
    account: str
    region: str
    kind: str  # "instance" or "cluster"


@dataclass
class Inventory:
    resources: list[Resource]
    shares: list[Share]
    usage: list[Usage]
    databases: list[Database]


@dataclass
class RuleResult:
    resource_id: str
    rule_id: str
    outcome: str  # "block" or "warn"; passing rules are not stored
    message: str


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_ts(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_days(created_at: str, now: datetime) -> int:
    return (now - parse_ts(created_at)).days
