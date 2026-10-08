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
    iops: int | None = None  # volume
    throughput: int | None = None  # volume, MiB/s
    encrypted: bool | None = None  # volume
    storage_tier: str | None = None  # snapshot: "standard" or "archive"
    est_monthly_cost: float | None = None
    cost_breakdown: dict | None = None  # see janitor.pricing
    status: str = ""
    status_reason: str = ""
    referenced_by: str | None = None  # AMI: templates, ASGs, launch configs that name it (W6)
    ignored_shares: str | None = None  # AMI: ignored accounts it is shared with (W7)


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
    ref_state: str = ""  # instance: running/stopped/...; asg: active/inactive; templates: ""

    @property
    def active(self) -> bool | None:
        """Running instance or ASG with capacity: True. Templates are references, not running: None."""
        if self.ref_type == "instance":
            return self.ref_state == "running"
        if self.ref_type == "asg":
            return self.ref_state == "active"
        return None


@dataclass
class Database:
    id: str
    account: str
    region: str
    kind: str  # "instance" or "cluster"


@dataclass
class Segment:
    """One (account, region, kind) slice of a scan. A failed segment contributes no rows."""

    account: str
    region: str
    kind: str  # "ami", "snapshot", "volume", "rds_snapshot", "database", "usage", or "ecs"
    ok: bool
    items: int = 0
    error_kind: str = ""  # "expired", "denied", "throttled", "blocked", or "other"
    error: str = ""
    duration_ms: int = 0


@dataclass
class Unresolved:
    """An image reference Janitor can't read, such as resolve:ssm:/golden/web."""

    account: str
    region: str
    ref_type: str  # "launch_template" or "asg"
    ref_id: str
    value: str


@dataclass
class Deployment:
    """One deploy of an app: an ASG a deploy tool tagged, or an ECS service. Shown, never judged."""

    kind: str  # "ec2" or "ecs"
    account: str
    region: str
    env: str
    app: str
    version: str
    state: str  # "deploying", "deployed", "undeploying", "undeployed", or "failed"
    resource_id: str  # ASG name; service ARN
    name: str  # ASG name; service name
    created_at: str
    desired: int = 0
    running: int = 0
    deployment_id: str = ""  # ec2
    launch_template: str = ""  # ec2: template name
    launch_template_version: str = ""  # ec2: the version number the ASG pins
    ami_id: str | None = None  # ec2: the image that version (or launch configuration) names
    cluster: str = ""  # ecs
    task_definition: str = ""  # ecs: family:revision
    image: str = ""  # ecs: the first container's image


@dataclass
class Inventory:
    resources: list[Resource]
    shares: list[Share]
    usage: list[Usage]
    databases: list[Database]
    segments: list[Segment] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    deployments: list[Deployment] = field(default_factory=list)


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
