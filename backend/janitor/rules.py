"""Deterministic delete rules. The strictest outcome wins: block > warn > pass.

Only block and warn results are returned and stored; any rule without a result passed.
Rules that compare a resource with others (R6, W1, W2, W3) read a RuleContext, built once per
scan from the stored rows by context(), so policy edits apply without rescanning.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from janitor.config import Policy
from janitor.models import Database, Resource, RuleResult, age_days

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
    Rule(
        "R6",
        "Among the newest in its group",
        "block",
        "Janitor keeps the {keep_newest} newest AMIs in each name group, per region, so there is "
        "always something to roll back to.",
    ),
    Rule("R7", "Keep name pattern", "block", "Its name matches a keep pattern ({keep_patterns})."),
    Rule(
        "W1",
        "Source of live copies",
        "warn",  # policy.source_with_live_copies
        "It was copied to other regions. The copies keep working, but this is their source.",
    ),
    Rule(
        "W2",
        "Possible last copy",
        "warn",  # policy.rds_last_copy
        "It is the newest snapshot of a database that no longer exists, so it may be the last "
        "copy.",
    ),
    Rule(
        "W3",
        "Newest snapshot of a live volume",
        "warn",
        "It is the newest snapshot of a volume that still exists.",
    ),
    Rule("W4", "No owner tag", "warn", "It has no owner tag, so there's nobody to ask first."),
    Rule(
        "W5",
        "Shared RDS snapshot",
        "warn",
        "Other accounts can restore it. They lose access to it when it is deleted.",
    ),
    Rule(
        "W6",
        "Referenced",
        "warn",
        "No instance runs it, but a launch template, Auto Scaling group, or launch configuration "
        "still names it. Deleting it makes their next launch fail.",
    ),
    Rule(
        "W7",
        "Shared with ignored accounts",
        "warn",
        "It is shared with accounts janitor.yaml ignores, so Janitor didn't check them. Anyone "
        "there loses access to it.",
    ),
]
RULES_BY_ID = {rule.id: rule for rule in RULES}


CONFIGURABLE = {"W1": "source_with_live_copies", "W2": "rds_last_copy"}


def outcome(rule: Rule, policy: Policy) -> str:
    """W1 and W2 warn or block as policy says; every other rule's outcome is fixed."""
    return getattr(policy, CONFIGURABLE[rule.id]) if rule.id in CONFIGURABLE else rule.outcome


def explain(rule: Rule, policy: Policy) -> str:
    protected = ", ".join(f"{k}={v}" for k, v in policy.protected_tags.items()) or "none configured"
    return rule.explanation.format(
        protected=protected,
        min_age_days=policy.min_age_days,
        keep_newest=policy.keep_newest_per_name_group,
        keep_patterns=", ".join(policy.keep_name_patterns) or "none configured",
    )


@dataclass(frozen=True)
class RuleContext:
    """What a resource's rules need to know about the others in the same scan."""

    group_rank: dict[str, tuple[int, int, str]] = field(default_factory=dict)  # (rank, size, group)
    copies: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # [(copy id, region)]
    last_db_copy: dict[str, str] = field(default_factory=dict)  # RDS snapshot -> gone DB
    newest_of_volume: dict[str, str] = field(default_factory=dict)  # snapshot -> live volume


def name_group(name: str, policy: Policy) -> str:
    """The name minus a trailing date or version; a name the pattern misses is its own group."""
    match = policy.group_regex.match(name)
    return match.group("group") if match and match.group("group") else name


def _newest_first(items: list[Resource]) -> list[Resource]:
    # Ties by ID, so the ranking is stable from scan to scan.
    return sorted(sorted(items, key=lambda r: r.id), key=lambda r: r.created_at, reverse=True)


def context(resources: list[Resource], databases: list[Database], policy: Policy) -> RuleContext:
    groups: dict[tuple, list[Resource]] = defaultdict(list)
    by_db: dict[tuple, list[Resource]] = defaultdict(list)
    by_volume: dict[tuple, list[Resource]] = defaultdict(list)
    amis: dict[str, Resource] = {}
    volumes = set()
    for r in resources:
        if r.type == "ami":
            amis[r.id] = r
            groups[(r.account, r.region, name_group(r.name, policy))].append(r)
        elif r.type == "rds_snapshot" and r.source_db_id:
            by_db[(r.account, r.region, r.source_db_id)].append(r)
        elif r.type == "snapshot" and r.source_volume_id:
            by_volume[(r.account, r.region, r.source_volume_id)].append(r)
        elif r.type == "volume":
            volumes.add((r.account, r.region, r.id))

    ctx = RuleContext()
    for (_, _, group), members in groups.items():
        for rank, r in enumerate(_newest_first(members), start=1):
            ctx.group_rank[r.id] = (rank, len(members), group)
    for r in amis.values():
        source = amis.get(r.source_ami_id or "")
        if source and r.region != source.region:
            ctx.copies.setdefault(source.id, []).append((r.id, r.region))
    live_dbs = {(d.account, d.region, d.id) for d in databases}
    for key, snaps in by_db.items():
        if key not in live_dbs:
            ctx.last_db_copy[_newest_first(snaps)[0].id] = key[2]
    for key, snaps in by_volume.items():
        if key in volumes:
            ctx.newest_of_volume[_newest_first(snaps)[0].id] = key[2]
    return ctx


def _ordinal(n: int) -> str:
    if n == 1:
        return "newest"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} newest"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def evaluate(
    r: Resource,
    policy: Policy,
    now: datetime,
    ctx: RuleContext | None = None,
    skip: frozenset[str] = frozenset(),
) -> list[RuleResult]:
    """Return the block and warn results for one resource."""
    ctx = ctx or RuleContext()
    hits: list[RuleResult] = []

    def hit(rule_id: str, message: str) -> None:
        if rule_id not in skip:
            hits.append(RuleResult(r.id, rule_id, outcome(RULES_BY_ID[rule_id], policy), message))

    if r.status == "in_use":
        hit("R1", r.status_reason)
    if r.status == "unknown":
        hit("R2", r.status_reason)
    if r.status == "managed":
        hit("R3", r.status_reason)
    # Match keys in any case, and check every variant: AWS tag keys are case-sensitive, so
    # one resource can carry both Retain=true and retain=no. Any matching variant protects it.
    protected = next(
        (
            (k, v)
            for key, value in policy.protected_tags.items()
            for k, v in r.tags.items()
            if k.lower() == key.lower() and str(v).lower() == value.lower()
        ),
        None,
    )
    if protected:
        hit("R4", f"Tagged {protected[0]}={protected[1]}.")
    age = age_days(r.created_at, now)
    if age < policy.min_age_days:
        hit("R5", f"Created {age} days ago; the minimum age is {policy.min_age_days} days.")
    keep = policy.keep_newest_per_name_group
    if r.id in ctx.group_rank and ctx.group_rank[r.id][0] <= keep:
        rank, size, group = ctx.group_rank[r.id]
        where = (
            f"the only AMI named {group}"
            if size == 1
            else f"the {_ordinal(rank)} of {size} AMIs named {group}*"
        )
        hit("R6", f"It is {where} in {r.region}; Janitor keeps the {keep} newest.")
    if r.type == "ami":
        pattern = next((p for p in policy.keep_regexes if p.search(r.name)), None)
        if pattern:
            hit("R7", f"Its name matches the keep pattern {pattern.pattern}.")
    if r.id in ctx.copies:
        copies = ctx.copies[r.id]
        regions = sorted({region for _, region in copies})
        plural = "" if len(copies) == 1 else "s"
        hit(
            "W1",
            f"It was copied to {_join(regions)} ({len(copies)} AMI{plural}). The copies keep "
            "working, but this is their source.",
        )
    if r.id in ctx.last_db_copy:
        hit(
            "W2",
            f"Database {ctx.last_db_copy[r.id]} is gone, and this is its newest snapshot. It may "
            "be the last copy.",
        )
    if r.id in ctx.newest_of_volume:
        hit("W3", f"It is the newest snapshot of {ctx.newest_of_volume[r.id]}, which still exists.")
    if not any(key.lower() == "owner" for key in r.tags):
        hit("W4", "It has no owner tag.")
    if r.type == "rds_snapshot" and r.shared_with:
        hit(
            "W5",
            "It is public."
            if "all" in r.shared_with
            else f"Shared with {_join(r.shared_with)}. They lose access to it.",
        )
    if r.referenced_by:
        hit("W6", r.referenced_by)
    if r.ignored_shares:
        hit(
            "W7",
            f"Shared with {r.ignored_shares}, which Janitor is set to ignore. "
            "Anyone there loses access to it.",
        )
    return hits


def strictest(results: Iterable[RuleResult]) -> str:
    return max((r.outcome for r in results), key=ORDER.__getitem__, default="pass")
