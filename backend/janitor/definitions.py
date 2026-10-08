"""Plain-English help for statuses and rules, rendered with live config values.

The API serves this to the UI, so the help text and the logic come from one place.
"""

from janitor.config import Config
from janitor.rules import RULES, explain


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
    }
