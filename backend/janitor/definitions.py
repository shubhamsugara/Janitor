"""Plain-English help for statuses and rules, rendered with live config values.

The API serves this to the UI, so the help text and the logic come from one place.
"""

from janitor.config import Config
from janitor.rules import RULES, explain


def _tags(keys: list[str]) -> str:
    return " or ".join(f"`{k}`" for k in keys)


def deployments(config: Config) -> dict:
    """What the Deployments page reads, with the configured tag names."""
    tags = config.deployments.tags
    return {
        "summary": (
            "A grid of apps by account and region, from the same read-only scan: which version "
            "runs where, and whether it is actually running. Nothing here is judged or deleted."
        ),
        "sources": [
            {
                "title": "Auto Scaling groups",
                "text": (
                    f"Groups your deploy tool tagged with `{tags.state}` (deploying, deployed, "
                    f"undeploying, undeployed). App from {_tags(tags.app)}, version from "
                    f"{_tags(tags.version)}, plus the launch template version the group pins and "
                    "its AMI. Untagged groups are skipped. Undeployed groups are earlier versions "
                    "kept at zero until someone removes them."
                ),
            },
            {
                "title": "Standalone instances",
                "text": (
                    "Instances in no Auto Scaling group, such as bastions, hand-built servers, or "
                    f"a DR server kept stopped. App from {_tags(tags.app)}, else the Name tag."
                ),
            },
            {
                "title": "ECS services",
                "text": (
                    "Every service in every cluster, with the version from its task definition's "
                    f"{_tags(tags.version)} tag, else the image tag. A service scaled to 0, like "
                    "the standby side of a blue/green pair, is an earlier version."
                ),
            },
        ],
        "run": [
            {"label": "Stopped", "meaning": "Scaled to 0: nothing is meant to run."},
            {
                "label": "No instances or tasks running",
                "meaning": "It should run but nothing does, for example tasks that keep failing.",
            },
            {"label": "N of M running", "meaning": "Partly up: fewer running than desired."},
            {"label": "Stopping", "meaning": "Scaled to 0, but some still run."},
        ],
        "notes": [
            "Columns are accounts, not env tags: ECS services rarely carry an env tag, so the "
            "account is what every row shares. The env tag shows in the details.",
            "The deploy state is the deploy tool's label; the run status comes from desired and "
            "running counts, so a deployed group scaled to 0 shows Stopped.",
            "Amber versions are behind the newest version of that app elsewhere.",
        ],
    }


def build(config: Config) -> dict:
    days = config.policy.orphan_after_days
    return {
        "statuses": {
            "in_use": {
                "label": "In use",
                "blocks": True,
                "meaning": "Something depends on it right now.",
                "what_to_do": "Stop using it first, then scan again.",
            },
            "managed": {
                "label": "Managed",
                "blocks": True,
                "meaning": "An AWS service creates and expires it.",
                "what_to_do": "Change the backup or lifecycle policy instead of deleting it here.",
            },
            "unknown": {
                "label": "Unknown",
                "blocks": True,
                "meaning": "Janitor can't prove whether anything uses it.",
                "what_to_do": "Fix the cause named in its reason, then scan again.",
            },
            "orphaned": {
                "label": "Orphaned",
                "blocks": False,
                "meaning": f"Nothing uses it, and it is older than {days} days.",
                "what_to_do": "Check its rules, then plan a delete.",
            },
            "idle": {
                "label": "Idle",
                "blocks": False,
                "meaning": f"Nothing uses it, but it is newer than {days} days or its source still exists.",
                "what_to_do": "Usually leave it; it may still be needed.",
            },
        },
        "by_type": {
            "ami": {
                "in_use": "An instance (running or stopped) was launched from it, in an account allowed to launch it, in its own region. Launch templates, Auto Scaling groups, and launch configurations that only name it add a Referenced warning instead.",
                "managed": "AWS Backup or Data Lifecycle Manager created it.",
                "unknown": "It is shared publicly, with an organization, or with an account Janitor doesn't scan.",
                "orphaned": f"Nothing uses it in its region, and it is older than {days} days.",
                "idle": f"Nothing uses it in its region, but it is newer than {days} days.",
            },
            "snapshot": {
                "in_use": "It backs an AMI that is still registered.",
                "managed": "AWS Backup or Data Lifecycle Manager created it.",
                "unknown": "It names an AMI in an account where Janitor doesn't list AMIs.",
                "orphaned": f"It names an AMI that is no longer registered, or its source volume is gone and it is older than {days} days.",
                "idle": f"It isn't linked to an AMI, and its source volume still exists or it is newer than {days} days.",
            },
            "volume": {
                "in_use": "It is attached to an instance.",
                "orphaned": f"It isn't attached, and it was created more than {days} days ago.",
                "idle": f"It isn't attached, but it was created less than {days} days ago.",
            },
            "rds_snapshot": {
                "managed": "An automated or AWS Backup snapshot. Its retention policy expires it.",
                "orphaned": f"A manual snapshot whose database is gone, older than {days} days.",
                "idle": f"A manual snapshot whose database still exists, or one newer than {days} days.",
            },
        },
        "rules": [
            {
                "id": r.id,
                "title": r.title,
                "outcome": r.outcome,
                "explanation": explain(r, config.policy),
            }
            for r in RULES
        ],
        "precedence": ["in_use", "managed", "unknown", "orphaned", "idle"],
        "notes": [
            "Volume age counts from creation. AWS doesn't record when a volume was detached.",
            "Costs are estimates (size × rate). Snapshots are incremental, so deleting one may free less.",
        ],
        "deployments": deployments(config),
    }
