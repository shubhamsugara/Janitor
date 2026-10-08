"""Plain-English help for statuses and rules, rendered with live config values.

The API serves this to the UI, so the help text and the logic come from one place.
"""

from janitor.config import Config
from janitor.rules import RULES, explain


def _tags(keys: list[str]) -> str:
    return " or ".join(f"`{k}`" for k in keys)


def deployments(config: Config) -> dict:
    """What the Deployments page shows, as terms engineers can use with each other."""
    tags = config.deployments.tags
    state = f"`{tags.state}`"
    terms = [
        ("Column", "An AWS account and region, labeled with the account's name from janitor.yaml."),
        (
            "Row (app)",
            f"The first of {_tags(tags.app)} on the ASG, instance, or task definition; else the "
            "ASG name, Name tag, or service name.",
        ),
        (
            "EC2 deployment",
            f"An Auto Scaling group with the {state} tag. Blue/green and destroy-before-create make "
            "one ASG per deploy; Janitor reads its pinned launch template version and that "
            "version's AMI. ASGs without the tag are skipped.",
        ),
        (
            "Standalone instance",
            "An EC2 instance without the `aws:autoscaling:groupName` tag: bastions, hand-built "
            "servers, a DR server kept stopped. One row per instance.",
        ),
        (
            "ECS deployment",
            f"An ECS service. Version is the task definition's {_tags(tags.version)} tag, else the "
            "container image tag.",
        ),
        (
            "Deploy state",
            f"EC2: the {state} tag (deploying, deployed, undeploying, undeployed). ECS: the primary "
            "deployment's rolloutState (IN_PROGRESS is deploying, FAILED is failed), and a "
            "DRAINING service is undeploying.",
        ),
        (
            "Run status",
            "Desired against running: ASG DesiredCapacity vs InService instances, ECS desiredCount "
            "vs runningCount, an instance's running or stopped state. Stopped: desired 0. No "
            "instances/tasks running: desired above 0, none running. N of M running: partly up. "
            "Stopping: desired 0, some still running.",
        ),
        ("Count", "Running instances or tasks, summed across everything in the cell."),
        (
            "Live version",
            "Every row in the cell except earlier versions. Two rows during a switch show as "
            "old → new; versions running side by side are listed.",
        ),
        (
            "Earlier version",
            f"An ASG tagged {state}=undeployed (scaled to 0, kept until someone prunes it), or the "
            "idle side of an ECS blue/green pair (desiredCount 0 beside a running service). ECS "
            "rolling deploys replace the task definition in place, so they have none here.",
        ),
        (
            "Drift",
            "An app runs different versions across columns. Amber cells are behind its highest "
            "version.",
        ),
    ]
    return {
        "summary": (
            "Which version of each app runs in each account and region, and whether it is "
            "running. From the same read-only scan; nothing here is judged or deleted."
        ),
        "terms": [{"term": term, "definition": text} for term, text in terms],
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
