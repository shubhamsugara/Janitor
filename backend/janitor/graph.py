"""The linkage graph around one resource: where it came from and what depends on it.

Edges point downstream (source → derived → user). Traversal is breadth-first in both
directions to `depth` hops. A node's `depth` is its lane: negative upstream, 0 for the root,
positive downstream. Each lane holds at most `lane_cap` nodes; the rest collapse into one
"+N more" node, so a resource with a huge fan-out still gives a readable diagram.
"""

from collections import defaultdict, deque
from dataclasses import dataclass

from janitor.config import Config
from janitor.models import Resource, Share, Usage
from janitor.store import Store

RESOURCE_KINDS = {"ami", "snapshot", "volume", "rds_snapshot"}
REF_NOUNS = {
    "instance": ("instance", "instances"),
    "asg": ("Auto Scaling group", "Auto Scaling groups"),
    "launch_template": ("launch template", "launch templates"),
    "launch_config": ("launch configuration", "launch configurations"),
}
REF_ORDER = {"instance": 0, "asg": 1, "launch_template": 2, "launch_config": 3}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str


def _known(config: Config, account_id: str) -> bool:
    return account_id == config.admin.account or account_id in config.accounts


def permitted_usage(store: Store, scan_id: int, ami: Resource) -> list[Usage]:
    """Usage in the AMI's own region by accounts allowed to launch it (as the linker counts it)."""
    shares = store.shares_for(scan_id, ami.id)
    permitted = {ami.account} | {s.principal for s in shares if s.principal_type == "account"}
    return [u for u in store.usage_for(scan_id, ami.id, ami.region) if u.account in permitted]


def backing_amis(store: Store, scan_id: int, snap: Resource) -> list[Resource]:
    ids = list(
        dict.fromkeys(store.amis_using_snapshot(scan_id, snap.id) + [snap.linked_ami_id or ""])
    )
    return [r for r in store.get_resources(scan_id, [i for i in ids if i]) if r.type == "ami"]


def usage_node_id(u: Usage) -> str:
    if u.ref_type in ("instance", "launch_template"):
        return f"{u.ref_type}:{u.ref_id}"
    return (
        f"{u.ref_type}:{u.account}:{u.region}:{u.ref_id}"  # names are unique per account and region
    )


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _state_word(u: Usage) -> str:
    if u.ref_type == "instance":
        return "running" if u.active else (u.ref_state or "stopped")
    if u.ref_type == "asg":
        return "active" if u.active else "inactive"
    return ""


def summarize(refs: list[Usage], via: list[Resource] | None, config: Config) -> str:
    """One sentence: what uses it, how many are running, in which accounts, through which AMI."""
    if not refs:
        if via:
            return f"It backs {_join([f'{a.id} ({a.name})' for a in via])}, which nothing uses."
        return "Nothing uses it."
    ordered = sorted(
        refs,
        key=lambda u: (
            0 if u.active else 1 if u.active is False else 2,
            REF_ORDER.get(u.ref_type, 9),
        ),
    )
    counts: dict[tuple[str, str], int] = {}
    for u in ordered:
        key = (_state_word(u), u.ref_type)
        counts[key] = counts.get(key, 0) + 1
    parts = []
    for (state, ref_type), n in counts.items():
        singular, plural = REF_NOUNS.get(ref_type, (ref_type, ref_type + "s"))
        parts.append(f"{n} {state + ' ' if state else ''}{singular if n == 1 else plural}")
    accounts = sorted({config.account_name(u.account) for u in refs})
    text = f"Used by {_join(parts)} in {_join(accounts)}"
    if via:
        text += f", through {_join([f'{a.id} ({a.name})' for a in via])}"
    return text + "."


def used_by(store: Store, config: Config, scan_id: int, r: Resource) -> dict:
    via = None
    if r.type == "ami":
        refs = permitted_usage(store, scan_id, r)
    elif r.type == "snapshot":
        via = backing_amis(store, scan_id, r)
        refs = [u for ami in via for u in permitted_usage(store, scan_id, ami)]
    elif r.type == "volume" and r.attached_instance:
        return {
            "active": None,
            "total": 1,
            "summary": f"Attached to instance {r.attached_instance}.",
        }
    else:
        refs = []
    summary = summarize(refs, via, config)
    amis = [r] if r.type == "ami" else via or []
    blind_spot = _blind_spot(store, config, scan_id, amis) if not refs else None
    if blind_spot:
        backs = f"It backs {_join([f'{a.id} ({a.name})' for a in via])}. " if via else ""
        summary = f"{backs}Nothing in the scanned accounts uses it. {blind_spot}"
    return {"active": sum(1 for u in refs if u.active), "total": len(refs), "summary": summary}


def _blind_spot(store: Store, config: Config, scan_id: int, amis: list[Resource]) -> str | None:
    """Why "nothing uses it" can't be proven: the AMI reaches accounts Janitor doesn't scan."""
    shares = [s for ami in amis for s in store.shares_for(scan_id, ami.id)]
    if any(s.principal_type == "group" and s.principal == "all" for s in shares):
        return "It is public, so other AWS accounts may."
    unscanned = sorted(
        {
            s.principal
            for s in shares
            if s.principal_type == "account" and not _known(config, s.principal)
        }
    )
    if unscanned:
        return f"It is shared with {_join(unscanned)}, which Janitor doesn't scan, so it may be used there."
    if any(s.principal_type in ("org", "ou") for s in shares):
        return (
            "It is shared with an organization or OU, so accounts Janitor doesn't scan may use it."
        )
    return None


class _Walker:
    def __init__(self, store: Store, config: Config, scan_id: int):
        self.store, self.config, self.scan_id = store, config, scan_id
        self.resources: dict[str, Resource] = {}

    def resource_node(self, r: Resource) -> dict:
        self.resources[r.id] = r
        return {
            "id": r.id,
            "kind": r.type,
            "label": r.name or r.id,
            "status": r.status,
            "account": r.account,
            "account_name": self.config.account_name(r.account),
            "region": r.region,
            "active": None,
            "state": r.state,
        }

    def context_node(
        self,
        node_id: str,
        kind: str,
        label: str,
        account: str,
        region: str,
        active: bool | None = None,
        state: str = "",
    ) -> dict:
        return {
            "id": node_id,
            "kind": kind,
            "label": label,
            "status": None,
            "account": account,
            "account_name": self.config.account_name(account) if account else "",
            "region": region,
            "active": active,
            "state": state,
        }

    def share_node(self, share: Share, ami: Resource) -> dict:
        if share.principal_type == "account":
            scanned = _known(self.config, share.principal)
            label = (
                self.config.account_name(share.principal)
                if scanned
                else f"{share.principal} (not scanned)"
            )
            return self.context_node(
                f"account:{share.principal}:{ami.region}",
                "account",
                label,
                share.principal,
                ami.region,
            )
        label = "Public (all AWS accounts)" if share.principal == "all" else share.principal
        return self.context_node(
            f"{share.principal_type}:{share.principal}:{ami.region}",
            "account",
            label,
            "",
            ami.region,
        )

    def neighbors(self, node: dict) -> list[tuple[dict, Edge]]:
        r = self.resources.get(node["id"])
        if r is None:
            if node["kind"] != "database":
                return []  # instances, templates, ASGs, and accounts are leaves
            snaps = self.store.snapshots_of_database(
                self.scan_id, node["account"], node["region"], node["label"]
            )
            return [
                (self.resource_node(s), Edge(node["id"], s.id, "snapshot_of_db")) for s in snaps
            ]
        out: list[tuple[dict, Edge]] = []
        if r.type == "ami":
            for s in self.store.get_resources(self.scan_id, r.snapshot_ids):
                out.append((self.resource_node(s), Edge(s.id, r.id, "backs")))
            if r.source_ami_id:
                for src in self.store.get_resources(self.scan_id, [r.source_ami_id]):
                    out.append((self.resource_node(src), Edge(src.id, r.id, "copied_to")))
            for copy in self.store.copies_of(self.scan_id, r.id):
                out.append((self.resource_node(copy), Edge(r.id, copy.id, "copied_to")))
            for u in permitted_usage(self.store, self.scan_id, r):
                node_id = usage_node_id(u)
                user = self.context_node(
                    node_id,
                    u.ref_type,
                    u.ref_name or u.ref_id,
                    u.account,
                    u.region,
                    u.active,
                    u.ref_state,
                )
                out.append((user, Edge(r.id, node_id, "used_by")))
            for share in self.store.shares_for(self.scan_id, r.id):
                account = self.share_node(share, r)
                out.append((account, Edge(r.id, account["id"], "shared_with")))
        elif r.type == "snapshot":
            for ami in backing_amis(self.store, self.scan_id, r):
                out.append((self.resource_node(ami), Edge(r.id, ami.id, "backs")))
            if r.source_volume_id:
                for v in self.store.get_resources(self.scan_id, [r.source_volume_id]):
                    if (v.account, v.region) == (r.account, r.region):
                        out.append((self.resource_node(v), Edge(v.id, r.id, "snapshot_of")))
        elif r.type == "volume":
            if r.attached_instance:
                node_id = f"instance:{r.attached_instance}"
                instance = self.context_node(
                    node_id, "instance", r.attached_instance, r.account, r.region, None, "attached"
                )
                out.append((instance, Edge(r.id, node_id, "attached_to")))
            for s in self.store.snapshots_of_volume(self.scan_id, r.account, r.region, r.id):
                out.append((self.resource_node(s), Edge(r.id, s.id, "snapshot_of")))
        elif r.type == "rds_snapshot" and r.source_db_id:
            db = self.store.database(self.scan_id, r.account, r.region, r.source_db_id)
            if db:
                node_id = f"database:{db.account}:{db.region}:{db.id}"
                database = self.context_node(
                    node_id, "database", db.id, db.account, db.region, None, db.kind
                )
                out.append((database, Edge(node_id, r.id, "snapshot_of_db")))
        return out


def _priority(node: dict) -> int:
    """Which neighbors survive the lane cap: resources, running users, shares, then the rest."""
    if node["kind"] in RESOURCE_KINDS:
        return 0
    if node["active"]:
        return 1
    if node["kind"] in ("account", "database"):
        return 2
    return 3 if node["active"] is False else 4


def build_graph(
    store: Store, config: Config, scan_id: int, root_id: str, depth: int = 2, lane_cap: int = 25
) -> dict | None:
    found = store.get_resources(scan_id, [root_id])
    if not found:
        return None
    walker = _Walker(store, config, scan_id)
    root = walker.resource_node(found[0]) | {"depth": 0}
    nodes = {root["id"]: root}
    edges: set[Edge] = set()
    lane_size: dict[int, int] = defaultdict(int, {0: 1})
    hidden: dict[int, set[str]] = defaultdict(set)
    queue = deque([(root, 0)])
    while queue:
        node, hops = queue.popleft()
        if hops == depth:
            continue
        for neighbor, edge in sorted(walker.neighbors(node), key=lambda pair: _priority(pair[0])):
            if neighbor["id"] in nodes:
                edges.add(edge)
                continue
            downstream = edge.source == node["id"]
            lane = node["depth"] + (1 if downstream else -1)
            if lane_size[lane] >= lane_cap:
                hidden[lane].add(neighbor["id"])
                more = f"more:{lane}"
                ends = (node["id"], more) if downstream else (more, node["id"])
                edges.add(Edge(*ends, edge.relation))  # the "+N more" node stays connected
                continue
            lane_size[lane] += 1
            nodes[neighbor["id"]] = neighbor | {"depth": lane}
            edges.add(edge)
            queue.append((nodes[neighbor["id"]], hops + 1))
    for lane, ids in sorted(hidden.items()):
        nodes[f"more:{lane}"] = {
            "id": f"more:{lane}",
            "kind": "more",
            "label": f"+{len(ids)} more",
            "status": None,
            "account": "",
            "account_name": "",
            "region": "",
            "active": None,
            "state": "",
            "depth": lane,
        }
    return {
        "root": root_id,
        "nodes": list(nodes.values()),
        "edges": [
            {"source": e.source, "target": e.target, "relation": e.relation}
            for e in sorted(edges, key=lambda e: (e.source, e.target, e.relation))
        ],
        "used_by": used_by(store, config, scan_id, found[0]),
        "truncated": bool(hidden),
    }
