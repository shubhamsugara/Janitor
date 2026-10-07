"""Deterministic delete rules. The strictest outcome wins: block > warn > pass.

Only block and warn results are returned and stored; any rule without a result passed.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from janitor.config import Policy
from janitor.models import Resource, RuleResult, age_days

ORDER = {"pass": 0, "warn": 1, "block": 2}


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    outcome: str
    explanation: str  # format string; fields come from explain()


RULES = [
    Rule("R1", "In use", "block", "Something still uses it. Deleting it would break that."),
    Rule(
        "R2",
        "Usage unknown",
        "block",
        "Janitor can't prove nothing uses it, so it won't offer it for deletion.",
    ),
    Rule(
        "R3",
        "Managed by AWS",
        "block",
        "An AWS service owns its lifecycle. Change that service's policy instead.",
    ),
    Rule("R4", "Protected tag", "block", "It carries a protected tag ({protected})."),
    Rule(
        "R5",
        "Too new",
        "block",
        "It is younger than {min_age_days} days, so it gets time to be adopted.",
    ),
    Rule("W4", "No owner tag", "warn", "It has no owner tag, so there's nobody to ask first."),
]
RULES_BY_ID = {rule.id: rule for rule in RULES}


def explain(rule: Rule, policy: Policy) -> str:
    protected = ", ".join(f"{k}={v}" for k, v in policy.protected_tags.items()) or "none configured"
    return rule.explanation.format(protected=protected, min_age_days=policy.min_age_days)


def evaluate(
    r: Resource, policy: Policy, now: datetime, skip: frozenset[str] = frozenset()
) -> list[RuleResult]:
    """Return the block and warn results for one resource."""
    hits: list[RuleResult] = []

    def hit(rule_id: str, message: str) -> None:
        if rule_id not in skip:
            hits.append(RuleResult(r.id, rule_id, RULES_BY_ID[rule_id].outcome, message))

    if r.status == "in_use":
        hit("R1", r.status_reason)
    if r.status == "unknown":
        hit("R2", r.status_reason)
    if r.status == "managed":
        hit("R3", r.status_reason)
    for key, value in policy.protected_tags.items():
        if str(r.tags.get(key, "")).lower() == value.lower():
            hit("R4", f"Tagged {key}={r.tags[key]}.")
            break
    age = age_days(r.created_at, now)
    if age < policy.min_age_days:
        hit("R5", f"Created {age} days ago; the minimum age is {policy.min_age_days} days.")
    if not any(key.lower() == "owner" for key in r.tags):
        hit("W4", "It has no owner tag.")
    return hits


def strictest(results: Iterable[RuleResult]) -> str:
    return max((r.outcome for r in results), key=ORDER.__getitem__, default="pass")
