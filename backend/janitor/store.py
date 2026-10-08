"""SQLite storage: scans, inventory, rule results, plans, and an append-only audit log.

Every inventory row carries scan_id. Readers use the newest scan with status 'ok', so a
running scan never mixes with it. Data from all but the two newest completed scans is
pruned; the audit log never is.
"""

import json
import sqlite3
import threading
from collections import defaultdict
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path

from janitor.models import Database, Resource, RuleResult, Segment, Share, Usage, format_ts

SCHEMA_VERSION = 3  # bump when a scan table changes shape; old scan data is dropped
RESOURCE_FIELDS = [f.name for f in fields(Resource)]
JSON_FIELDS = {"tags", "snapshot_ids", "cost_breakdown"}
SORTABLE = {
    "id",
    "name",
    "created_at",
    "size_gb",
    "status",
    "region",
    "account",
    "est_monthly_cost",
}
SCAN_TABLES = ("resources", "shares", "usage", "policy_results", "databases", "scan_segments")
READABLE = "status IN ('ok', 'partial')"  # a partial scan is shown; failed checks show as unknown
AGE_BUCKETS = (("<30d", 30), ("30–90d", 90), ("90–180d", 180), ("180–365d", 365))
AGE_KEYS = [label for label, _ in AGE_BUCKETS] + [">1y"]
BLOCKED_SQL = (
    "EXISTS (SELECT 1 FROM policy_results p WHERE p.scan_id = resources.scan_id "
    "AND p.resource_id = resources.id AND p.outcome = 'block')"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
  id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
  provider TEXT NOT NULL, status TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS scan_segments (
  scan_id INTEGER NOT NULL, account TEXT NOT NULL, region TEXT NOT NULL, kind TEXT NOT NULL,
  ok INTEGER NOT NULL, items INTEGER NOT NULL, error_kind TEXT NOT NULL, error TEXT NOT NULL,
  duration_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS resources (
  scan_id INTEGER NOT NULL, id TEXT NOT NULL, type TEXT NOT NULL, account TEXT NOT NULL,
  region TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL, size_gb INTEGER,
  state TEXT, tags TEXT NOT NULL, snapshot_ids TEXT NOT NULL, source_ami_id TEXT,
  linked_ami_id TEXT, source_volume_id TEXT, attached_instance TEXT, volume_type TEXT,
  source_db_id TEXT, db_kind TEXT, managed_by TEXT, iops INTEGER, throughput INTEGER,
  encrypted INTEGER, storage_tier TEXT, est_monthly_cost REAL, cost_breakdown TEXT,
  status TEXT NOT NULL, status_reason TEXT NOT NULL,
  PRIMARY KEY (scan_id, id));
CREATE INDEX IF NOT EXISTS resources_type_status ON resources (scan_id, type, status);
CREATE TABLE IF NOT EXISTS shares (
  scan_id INTEGER NOT NULL, image_id TEXT NOT NULL, principal_type TEXT NOT NULL, principal TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage (
  scan_id INTEGER NOT NULL, image_id TEXT NOT NULL, account TEXT NOT NULL, region TEXT NOT NULL,
  ref_type TEXT NOT NULL, ref_id TEXT NOT NULL, ref_name TEXT NOT NULL,
  ref_state TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS databases (
  scan_id INTEGER NOT NULL, id TEXT NOT NULL, account TEXT NOT NULL, region TEXT NOT NULL,
  kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policy_results (
  scan_id INTEGER NOT NULL, resource_id TEXT NOT NULL, rule_id TEXT NOT NULL,
  outcome TEXT NOT NULL, message TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS policy_results_resource ON policy_results (scan_id, resource_id);
CREATE TABLE IF NOT EXISTS plans (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, scan_id INTEGER NOT NULL,
  selection_json TEXT NOT NULL, results_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  payload_json TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
  BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
  BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
"""


def _now() -> str:
    return format_ts(datetime.now(UTC))


def _scan(row: sqlite3.Row) -> dict:
    return dict(row) | {"notes": json.loads(row["notes"] or "{}")}


def _marks(items: list) -> str:
    return ",".join("?" * len(items))


def _chunks(items: list, size: int = 500):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _row(scan_id: int, r: Resource) -> tuple:
    data = asdict(r)
    return (
        scan_id,
        *(json.dumps(data[f]) if f in JSON_FIELDS else data[f] for f in RESOURCE_FIELDS),
    )


def _resource(row: sqlite3.Row) -> Resource:
    data = {f: row[f] for f in RESOURCE_FIELDS}
    for f in JSON_FIELDS:
        data[f] = json.loads(data[f])
    if data["encrypted"] is not None:
        data["encrypted"] = bool(data["encrypted"])  # SQLite stores booleans as 0/1
    return Resource(**data)


def _where(scan_id: int, filters: dict) -> tuple[str, list]:
    clauses, params = ["scan_id = ?"], [scan_id]
    if filters.get("type"):
        clauses.append("type = ?")
        params.append(filters["type"])
    for key in ("account", "region", "status"):  # comma-separated lists
        values = [v for v in (filters.get(key) or "").split(",") if v]
        if values:
            clauses.append(f"{key} IN ({_marks(values)})")
            params += values
    if filters.get("q"):
        escaped = filters["q"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(name LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\')")
        params += [f"%{escaped}%"] * 2
    if filters.get("created_from"):
        clauses.append("substr(created_at, 1, 10) >= ?")
        params.append(filters["created_from"])
    if filters.get("created_to"):
        clauses.append("substr(created_at, 1, 10) <= ?")
        params.append(filters["created_to"])
    if filters.get("tag"):
        key, sep, value = filters["tag"].partition("=")
        if sep:
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(resources.tags) WHERE key = ? AND value = ?)"
            )
            params += [key, value]
        else:
            clauses.append("EXISTS (SELECT 1 FROM json_each(resources.tags) WHERE key = ?)")
            params.append(key)
    return " AND ".join(clauses), params


class Store:
    def __init__(self, path: str | Path, provider: str | None = None):
        """With `provider`, readers see only that provider's scans (mock and AWS share data/)."""
        self._provider = provider
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            if self._db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                # Scan data is a cache, so drop it when its shape changes. The audit log stays.
                drops = "".join(
                    f"DROP TABLE IF EXISTS {t};" for t in (*SCAN_TABLES, "scans", "plans")
                )
                self._db.executescript(drops)
                self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._db.executescript(SCHEMA)

    def _q(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def _write(self, sql: str, params=()) -> int:
        with self._lock, self._db:
            return self._db.execute(sql, params).lastrowid

    # Scans

    def start_scan(self, provider: str) -> int:
        return self._write(
            "INSERT INTO scans (started_at, provider, status) VALUES (?, ?, 'running')",
            (_now(), provider),
        )

    def finish_scan(self, scan_id: int, status: str) -> None:
        self._write(
            "UPDATE scans SET finished_at = ?, status = ? WHERE id = ?", (_now(), status, scan_id)
        )
        self._prune()

    def fail_running_scans(self) -> None:
        """A scan still 'running' at startup died with the previous process."""
        self._write(
            "UPDATE scans SET finished_at = ?, status = 'failed' WHERE status = 'running'",
            (_now(),),
        )

    def _mine(self) -> tuple[str, tuple]:
        return ("provider = ?", (self._provider,)) if self._provider else ("1 = 1", ())

    def latest_scan(self) -> dict | None:
        """The newest scan readers should show: completed, possibly with failed checks."""
        mine, params = self._mine()
        rows = self._q(
            f"SELECT * FROM scans WHERE {READABLE} AND {mine} ORDER BY id DESC LIMIT 1", params
        )
        return _scan(rows[0]) if rows else None

    def last_scan(self) -> dict | None:
        mine, params = self._mine()
        rows = self._q(f"SELECT * FROM scans WHERE {mine} ORDER BY id DESC LIMIT 1", params)
        return _scan(rows[0]) if rows else None

    def set_notes(self, scan_id: int, notes: dict) -> None:
        self._write("UPDATE scans SET notes = ? WHERE id = ?", (json.dumps(notes), scan_id))

    def add_segment(self, scan_id: int, seg: Segment) -> None:
        self._write(
            "INSERT INTO scan_segments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                scan_id,
                seg.account,
                seg.region,
                seg.kind,
                int(seg.ok),
                seg.items,
                seg.error_kind,
                seg.error,
                seg.duration_ms,
            ),
        )

    def segments(self, scan_id: int) -> list[dict]:
        rows = self._q("SELECT * FROM scan_segments WHERE scan_id = ? ORDER BY rowid", (scan_id,))
        return [{k: row[k] for k in row.keys() if k != "scan_id"} for row in rows]

    def _prune(self) -> None:
        keep = []
        for (provider,) in self._q("SELECT DISTINCT provider FROM scans"):
            keep += [
                r["id"]
                for r in self._q(
                    f"SELECT id FROM scans WHERE {READABLE} AND provider = ? ORDER BY id DESC LIMIT 2",
                    (provider,),
                )
            ]
            # The newest scan's checks explain a failure even when its rows aren't kept.
            keep += [
                r["id"]
                for r in self._q("SELECT MAX(id) AS id FROM scans WHERE provider = ?", (provider,))
            ]
        keep += [r["id"] for r in self._q("SELECT id FROM scans WHERE status = 'running'")]
        marks = _marks(keep) or "-1"
        with self._lock, self._db:
            for table in SCAN_TABLES:
                self._db.execute(f"DELETE FROM {table} WHERE scan_id NOT IN ({marks})", keep)

    # Inventory

    def save_inventory(
        self,
        scan_id: int,
        resources: list[Resource],
        shares: list[Share],
        usage: list[Usage],
        databases: list[Database] = (),
    ) -> None:
        cols = ",".join(["scan_id", *RESOURCE_FIELDS])
        marks = _marks([None] * (len(RESOURCE_FIELDS) + 1))
        with self._lock, self._db:
            self._db.executemany(
                f"INSERT INTO resources ({cols}) VALUES ({marks})",
                [_row(scan_id, r) for r in resources],
            )
            self._db.executemany(
                "INSERT INTO shares VALUES (?, ?, ?, ?)",
                [(scan_id, s.image_id, s.principal_type, s.principal) for s in shares],
            )
            self._db.executemany(
                "INSERT INTO usage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        scan_id,
                        u.image_id,
                        u.account,
                        u.region,
                        u.ref_type,
                        u.ref_id,
                        u.ref_name,
                        u.ref_state,
                    )
                    for u in usage
                ],
            )
            self._db.executemany(
                "INSERT INTO databases VALUES (?, ?, ?, ?, ?)",
                [(scan_id, d.id, d.account, d.region, d.kind) for d in databases],
            )

    def query_resources(
        self,
        scan_id: int,
        filters: dict,
        sort: str = "-created_at",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Resource], int]:
        column = sort.lstrip("-")
        if column not in SORTABLE:
            raise ValueError(
                f"Can't sort by {column}. Choose one of: {', '.join(sorted(SORTABLE))}."
            )
        direction = "DESC" if sort.startswith("-") else "ASC"
        where, params = _where(scan_id, filters)
        total = self._q(f"SELECT COUNT(*) FROM resources WHERE {where}", params)[0][0]
        rows = self._q(
            f"SELECT * FROM resources WHERE {where} ORDER BY {column} {direction}, id "
            "LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return [_resource(r) for r in rows], total

    def stats(self, scan_id: int, filters: dict, now: datetime | None = None) -> dict:
        where, params = _where(scan_id, filters)
        row = self._q(
            "SELECT COUNT(*) AS total, COALESCE(SUM(status = 'orphaned'), 0) AS orphaned, "
            "COALESCE(SUM(size_gb), 0) AS size_gib, SUM(est_monthly_cost) AS cost, "
            "COALESCE(SUM(CASE WHEN status = 'orphaned' THEN size_gb END), 0) AS orphaned_gib, "
            "SUM(CASE WHEN status = 'orphaned' THEN est_monthly_cost END) AS orphaned_cost, "
            f"COALESCE(SUM({BLOCKED_SQL}), 0) AS blocked "
            f"FROM resources WHERE {where}",
            params,
        )[0]
        cost, orphaned_cost = row["cost"], row["orphaned_cost"]
        now_ts = format_ts(now or datetime.now(UTC))
        cases = " ".join(
            f"WHEN julianday(?) - julianday(created_at) < {days} THEN '{label}'"
            for label, days in AGE_BUCKETS
        )
        by_age = {
            b["key"]: b
            for b in self._breakdown(
                f"CASE {cases} ELSE '>1y' END", [now_ts] * len(AGE_BUCKETS), where, params
            )
        }
        return {
            "total": row["total"],
            "orphaned": row["orphaned"],
            "size_gib": row["size_gib"],
            "est_monthly_usd": None if cost is None else round(cost, 2),
            "orphaned_gib": row["orphaned_gib"],
            "orphaned_usd": None if orphaned_cost is None else round(orphaned_cost, 2),
            "blocked": row["blocked"],
            "deletable": row["total"] - row["blocked"],
            "by_status": self._breakdown("status", [], where, params),
            "by_account": self._breakdown("account", [], where, params),
            "by_region": self._breakdown("region", [], where, params),
            "by_age": [
                by_age.get(k, {"key": k, "count": 0, "gib": 0, "usd": None}) for k in AGE_KEYS
            ],
        }

    def _breakdown(self, expr: str, expr_params: list, where: str, params: list) -> list[dict]:
        """Count, GiB, and cost grouped by `expr` (a column name or a fixed CASE expression)."""
        rows = self._q(
            f"SELECT {expr} AS key, COUNT(*) AS count, COALESCE(SUM(size_gb), 0) AS gib, "
            f"SUM(est_monthly_cost) AS usd FROM resources WHERE {where} "
            "GROUP BY key ORDER BY count DESC, key",
            [*expr_params, *params],
        )
        return [
            {
                "key": r["key"],
                "count": r["count"],
                "gib": r["gib"],
                "usd": None if r["usd"] is None else round(r["usd"], 2),
            }
            for r in rows
        ]

    def overview(self, scan_id: int) -> list[dict]:
        rows = self._q(
            "SELECT type, COUNT(*) AS total, COALESCE(SUM(status = 'orphaned'), 0) AS orphaned, "
            "COALESCE(SUM(CASE WHEN status = 'orphaned' THEN size_gb END), 0) AS orphaned_gib, "
            "SUM(CASE WHEN status = 'orphaned' THEN est_monthly_cost END) AS orphaned_usd "
            "FROM resources WHERE scan_id = ? GROUP BY type ORDER BY type",
            (scan_id,),
        )
        return [
            dict(r)
            | {"orphaned_usd": None if r["orphaned_usd"] is None else round(r["orphaned_usd"], 2)}
            for r in rows
        ]

    def get_resources(self, scan_id: int, ids: list[str]) -> list[Resource]:
        found = {}
        for chunk in _chunks(list(ids)):
            for row in self._q(
                f"SELECT * FROM resources WHERE scan_id = ? AND id IN ({_marks(chunk)})",
                [scan_id, *chunk],
            ):
                found[row["id"]] = _resource(row)
        return [found[i] for i in ids if i in found]

    def all_resources(self, scan_id: int) -> list[Resource]:
        return [
            _resource(r) for r in self._q("SELECT * FROM resources WHERE scan_id = ?", (scan_id,))
        ]

    def amis_using_snapshot(self, scan_id: int, snapshot_id: str) -> list[str]:
        rows = self._q(
            "SELECT r.id FROM resources r, json_each(r.snapshot_ids) j "
            "WHERE r.scan_id = ? AND r.type = 'ami' AND j.value = ?",
            (scan_id, snapshot_id),
        )
        return [r["id"] for r in rows]

    def shares_for(self, scan_id: int, image_id: str) -> list[Share]:
        rows = self._q(
            "SELECT image_id, principal_type, principal FROM shares WHERE scan_id = ? AND image_id = ?",
            (scan_id, image_id),
        )
        return [Share(**dict(r)) for r in rows]

    def copies_of(self, scan_id: int, ami_id: str) -> list[Resource]:
        rows = self._q(
            "SELECT * FROM resources WHERE scan_id = ? AND type = 'ami' AND source_ami_id = ?",
            (scan_id, ami_id),
        )
        return [_resource(r) for r in rows]

    def usage_for(self, scan_id: int, image_id: str, region: str) -> list[Usage]:
        rows = self._q(
            "SELECT image_id, account, region, ref_type, ref_id, ref_name, ref_state FROM usage "
            "WHERE scan_id = ? AND image_id = ? AND region = ?",
            (scan_id, image_id, region),
        )
        return [Usage(**dict(r)) for r in rows]

    def snapshots_of_volume(
        self, scan_id: int, account: str, region: str, volume_id: str
    ) -> list[Resource]:
        rows = self._q(
            "SELECT * FROM resources WHERE scan_id = ? AND type = 'snapshot' AND account = ? "
            "AND region = ? AND source_volume_id = ?",
            (scan_id, account, region, volume_id),
        )
        return [_resource(r) for r in rows]

    def snapshots_of_database(
        self, scan_id: int, account: str, region: str, db_id: str
    ) -> list[Resource]:
        rows = self._q(
            "SELECT * FROM resources WHERE scan_id = ? AND type = 'rds_snapshot' AND account = ? "
            "AND region = ? AND source_db_id = ?",
            (scan_id, account, region, db_id),
        )
        return [_resource(r) for r in rows]

    def database(self, scan_id: int, account: str, region: str, db_id: str) -> Database | None:
        rows = self._q(
            "SELECT id, account, region, kind FROM databases WHERE scan_id = ? AND account = ? "
            "AND region = ? AND id = ?",
            (scan_id, account, region, db_id),
        )
        return Database(**dict(rows[0])) if rows else None

    def related(self, scan_id: int, r: Resource) -> dict:
        """Linked resources for the detail panel, computed from columns."""
        out: dict = {"links": [], "shares": [], "usage": []}
        select = "SELECT id, name, region, status FROM resources WHERE scan_id = ? AND "

        def add(relation: str, sql: str, params: tuple) -> None:
            out["links"] += [
                {"relation": relation, **dict(row)}
                for row in self._q(select + sql, (scan_id, *params))
            ]

        if r.type == "ami":
            add(
                "snapshot",
                "type = 'snapshot' AND id IN (SELECT value FROM json_each(?))",
                (json.dumps(r.snapshot_ids),),
            )
            add("copy", "type = 'ami' AND source_ami_id = ?", (r.id,))
            if r.source_ami_id:
                add("copied from", "id = ?", (r.source_ami_id,))
            out["shares"] = [
                {"principal_type": s.principal_type, "principal": s.principal}
                for s in self.shares_for(scan_id, r.id)
            ]
            out["usage"] = [
                dict(u)
                for u in self._q(
                    "SELECT account, region, ref_type, ref_id, ref_name, ref_state FROM usage "
                    "WHERE scan_id = ? AND image_id = ? AND region = ?",
                    (scan_id, r.id, r.region),
                )
            ]
        elif r.type == "snapshot":
            add(
                "backs AMI",
                "type = 'ami' AND (id = ? OR EXISTS "
                "(SELECT 1 FROM json_each(resources.snapshot_ids) WHERE value = ?))",
                (r.linked_ami_id, r.id),
            )
            if r.source_volume_id:
                add("source volume", "id = ?", (r.source_volume_id,))
        elif r.type == "volume":
            add("snapshot", "type = 'snapshot' AND source_volume_id = ?", (r.id,))
        else:
            add(
                "same database",
                "type = 'rds_snapshot' AND source_db_id = ? AND account = ? "
                "AND region = ? AND id <> ?",
                (r.source_db_id, r.account, r.region, r.id),
            )
        return out

    # Rule results

    def save_rule_results(self, scan_id: int, results: list[RuleResult]) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM policy_results WHERE scan_id = ?", (scan_id,))
            self._db.executemany(
                "INSERT INTO policy_results VALUES (?, ?, ?, ?, ?)",
                [(scan_id, h.resource_id, h.rule_id, h.outcome, h.message) for h in results],
            )

    def rule_results(self, scan_id: int, ids: list[str]) -> dict[str, list[RuleResult]]:
        out: dict[str, list[RuleResult]] = defaultdict(list)
        for chunk in _chunks(list(ids)):
            rows = self._q(
                "SELECT resource_id, rule_id, outcome, message FROM policy_results "
                f"WHERE scan_id = ? AND resource_id IN ({_marks(chunk)})",
                [scan_id, *chunk],
            )
            for row in rows:
                out[row["resource_id"]].append(RuleResult(**dict(row)))
        return dict(out)

    # Plans and audit

    def save_plan(self, plan_id: str, scan_id: int, selection: dict, results: dict) -> None:
        self._write(
            "INSERT INTO plans VALUES (?, ?, ?, ?, ?)",
            (plan_id, _now(), scan_id, json.dumps(selection), json.dumps(results)),
        )

    def get_plan(self, plan_id: str) -> dict | None:
        rows = self._q("SELECT * FROM plans WHERE id = ?", (plan_id,))
        if not rows:
            return None
        row = rows[0]
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "scan_id": row["scan_id"],
            "selection": json.loads(row["selection_json"]),
            "results": json.loads(row["results_json"]),
        }

    def add_audit(self, action: str, payload: dict, actor: str = "local") -> int:
        return self._write(
            "INSERT INTO audit (ts, actor, action, payload_json) VALUES (?, ?, ?, ?)",
            (_now(), actor, action, json.dumps(payload)),
        )

    def list_audit(self, page: int, page_size: int) -> tuple[list[dict], int]:
        total = self._q("SELECT COUNT(*) FROM audit")[0][0]
        rows = self._q(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        )
        items = [
            {
                "id": r["id"],
                "ts": r["ts"],
                "actor": r["actor"],
                "action": r["action"],
                "payload": json.loads(r["payload_json"]),
            }
            for r in rows
        ]
        return items, total
