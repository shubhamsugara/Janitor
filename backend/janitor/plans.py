"""Plan and simulate deletes. Janitor never deletes; simulate only records what would happen."""

import hashlib
import uuid
from datetime import datetime

from janitor.config import Config
from janitor.linker import MANAGED_REASONS
from janitor.models import Resource, RuleResult
from janitor.rules import RULES, RULES_BY_ID, evaluate
from janitor.store import Store

MAX_SELECTION = 1000
RULE_ORDER = {rule.id: n for n, rule in enumerate(RULES)}


class PlanError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _item(r: Resource, hits: list[RuleResult], parent: str | None = None) -> dict:
    return {
        "id": r.id,
        "type": r.type,
        "name": r.name,
        "account": r.account,
        "region": r.region,
        "status": r.status,
        "status_reason": r.status_reason,
        "size_gb": r.size_gb,
        "est_monthly_cost": r.est_monthly_cost,
        "tags": r.tags,
        "parent": parent,
        "rules": [
            {
                "rule_id": h.rule_id,
                "title": RULES_BY_ID[h.rule_id].title,
                "outcome": h.outcome,
                "message": h.message,
            }
            for h in sorted(hits, key=lambda h: RULE_ORDER[h.rule_id])
        ],
    }


def _blocked(item: dict) -> bool:
    return any(rule["outcome"] == "block" for rule in item["rules"])


def _block_rule(rules: list[dict]) -> dict:
    """The first blocking rule, in RULES order (items' rules are sorted)."""
    return next(
        (r for r in rules if r["outcome"] == "block"), {"title": "Blocked", "message": "Blocked."}
    )


def _totals(items: list[dict]) -> dict:
    """AMIs have no size or cost of their own; their snapshots carry it."""
    data = [i for i in items if i["type"] != "ami"]
    return {
        "count": len(items),
        "size_gib": sum(i["size_gb"] or 0 for i in data),
        "est_monthly_usd": round(sum(i["est_monthly_cost"] or 0 for i in data), 2),
    }


def _config_hash(config: Config) -> str:
    return hashlib.sha256(config.model_dump_json().encode()).hexdigest()


def _needs_typing(deletable: list[dict], config: Config) -> bool:
    return (
        len(deletable) >= config.policy.typed_confirm_min_items
        or any(rule["outcome"] == "warn" for i in deletable for rule in i["rules"])
        or any(
            key.lower() == "env" and str(value).lower() == "prod"
            for i in deletable
            for key, value in i["tags"].items()
        )
    )


def _backing_snapshots(
    store: Store,
    config: Config,
    scan_id: int,
    selected: list[Resource],
    items: list[dict],
    now: datetime,
) -> list[dict]:
    """Snapshots used only by the AMIs being deleted go with them (spec §9).

    That includes snapshots the user also selected directly: on their own they are "in use"
    (R1), but only by AMIs this plan deregisters.
    """
    deleting = {i["id"] for i in items if i["type"] == "ami" and not _blocked(i)}
    taken: set[str] = set()
    out = []
    for ami in (r for r in selected if r.id in deleting):
        for snap_id in ami.snapshot_ids:
            if snap_id in taken:
                continue
            found = store.get_resources(scan_id, [snap_id])
            if not found:
                continue
            snap = found[0]
            users = set(store.amis_using_snapshot(scan_id, snap_id))
            if snap.linked_ami_id and store.get_resources(scan_id, [snap.linked_ami_id]):
                users.add(snap.linked_ami_id)
            if users - deleting:
                continue  # another registered AMI still needs it
            taken.add(snap_id)
            # It is in use only because of the AMI being deleted, so R1 doesn't apply. Its stored
            # status (in_use) outranks managed, so R3 has to be checked here.
            hits = evaluate(snap, config.policy, now, skip=frozenset({"R1"}))
            if snap.managed_by:
                reason = MANAGED_REASONS.get(snap.managed_by, "Created by an AWS-managed service.")
                hits.insert(0, RuleResult(snap.id, "R3", "block", reason))
            out.append(_item(snap, hits, parent=ami.id))
    return out


def _share_impact(store: Store, config: Config, scan_id: int, item: dict) -> dict:
    shares = store.shares_for(scan_id, item["id"])
    return {
        "ami_id": item["id"],
        "region": item["region"],
        "accounts": [
            {
                "id": s.principal,
                "name": config.account_name(s.principal),
                "scanned": s.principal in config.accounts,
            }
            for s in shares
            if s.principal_type == "account"
        ],
        "other": [s.principal for s in shares if s.principal_type != "account"],
        "copies": [
            {"id": c.id, "region": c.region, "status": c.status}
            for c in store.copies_of(scan_id, item["id"])
        ],
    }


def make_plan(store: Store, config: Config, ids: list[str], now: datetime) -> dict:
    scan = store.latest_scan()
    if scan is None:
        raise PlanError(409, "No scan yet. Run a scan, then plan again.")
    scan_id = scan["id"]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise PlanError(422, "Select at least one resource.")
    if len(ids) > MAX_SELECTION:
        raise PlanError(422, f"Select {MAX_SELECTION:,} or fewer resources.")
    selected = store.get_resources(scan_id, ids)
    if not selected:
        raise PlanError(
            404,
            "None of the selected resources are in the latest scan. Reload the page, then select again.",
        )
    hits = store.rule_results(scan_id, [r.id for r in selected])
    items = [_item(r, hits.get(r.id, [])) for r in selected]
    backing = _backing_snapshots(store, config, scan_id, selected, items, now)
    backing_ids = {b["id"] for b in backing}
    items = [i for i in items if i["id"] not in backing_ids] + backing
    selected_ids = {r.id for r in selected}
    for i in items:
        if _blocked(i) and i["id"] in selected_ids:
            i["parent"] = None  # selected and kept: the user's own item, not one riding along
    blocked = [i for i in items if _blocked(i)]
    deletable = [i for i in items if not _blocked(i)]
    any_blocked = any(i["parent"] is None for i in blocked)
    any_deletable = any(i["parent"] is None for i in deletable)
    variant = (
        "mixed"
        if any_blocked and any_deletable
        else "none_blocked"
        if any_deletable
        else "all_blocked"
    )
    found = {r.id for r in selected}
    plan = {
        "plan_id": uuid.uuid4().hex,
        "scan_id": scan_id,
        "config_hash": _config_hash(config),
        "variant": variant,
        "blocked": blocked,
        "deletable": deletable,
        "missing": [i for i in ids if i not in found],
        "totals": _totals(deletable),
        "share_impact": [
            _share_impact(store, config, scan_id, i) for i in deletable if i["type"] == "ami"
        ],
        "requires_typed_confirmation": _needs_typing(deletable, config),
    }
    store.save_plan(plan["plan_id"], scan_id, {"ids": ids}, plan)
    store.add_audit(
        "plan",
        {
            "plan_id": plan["plan_id"],
            "scan_id": scan_id,
            "variant": variant,
            "deletable": len(deletable),
            "blocked": len(blocked),
        },
    )
    return plan


def simulate(store: Store, config: Config, plan_id: str, confirmation: str) -> dict:
    saved = store.get_plan(plan_id)
    if saved is None:
        raise PlanError(404, "That plan doesn't exist. Plan the delete again.")
    plan = saved["results"]
    scan = store.latest_scan()
    if scan is None or scan["id"] != plan["scan_id"]:
        raise PlanError(409, "The data changed since this plan was made. Plan the delete again.")
    if plan.get("config_hash") != _config_hash(config):
        # Rules, protected tags, and the typed-confirmation threshold may all differ now.
        raise PlanError(
            409, "Janitor's settings changed since this plan was made. Plan the delete again."
        )
    if plan["requires_typed_confirmation"] and confirmation.strip().lower() != "delete":
        raise PlanError(422, "Type delete to confirm.")

    # Re-check top-level items against the stored rule results: a safety net if they changed.
    top = [i["id"] for i in plan["deletable"] if i["parent"] is None]
    current = store.rule_results(plan["scan_id"], top)
    now_blocked: dict[str, tuple[str, str]] = {}  # id -> (rule title, message)
    for item_id in top:
        hit = next((h for h in current.get(item_id, []) if h.outcome == "block"), None)
        if hit:
            now_blocked[item_id] = (RULES_BY_ID[hit.rule_id].title, hit.message)

    skipped = []
    for i in plan["blocked"]:
        rule = _block_rule(i["rules"])
        skipped.append(
            {"id": i["id"], "name": i["name"], "rule": rule["title"], "reason": rule["message"]}
        )
    would_delete = []
    for item in plan["deletable"]:
        blocked = now_blocked.get(item["id"])
        if blocked is None and item["parent"] in now_blocked:
            blocked = ("Kept with its AMI", f"Kept because {item['parent']} is now blocked.")
        if blocked:
            skipped.append(
                {"id": item["id"], "name": item["name"], "rule": blocked[0], "reason": blocked[1]}
            )
        else:
            would_delete.append(item)

    totals = _totals(would_delete)
    store.add_audit(
        "simulate",
        {
            "plan_id": plan_id,
            "scan_id": plan["scan_id"],
            "totals": totals,
            "items": [{"id": i["id"], "outcome": "would_delete"} for i in would_delete]
            + [{"id": s["id"], "outcome": "skipped", "reason": s["reason"]} for s in skipped],
        },
    )
    return {"would_delete": would_delete, "skipped": skipped, "failed": [], "totals": totals}
