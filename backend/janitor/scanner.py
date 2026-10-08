"""Run one scan: read the inventory, compute statuses and rule results, store them."""

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime

from janitor.config import Config
from janitor.linker import LinkContext, link, references
from janitor.models import Segment
from janitor.pricing import PriceTable, apply_costs
from janitor.providers.base import CloudProvider
from janitor.rules import evaluate
from janitor.store import Store

log = logging.getLogger(__name__)


class ScanRunning(Exception):
    """Raised when a scan is requested while one is running."""


class AllChecksFailed(Exception):
    """Every check failed, so there is nothing to show from this scan."""


def segment_message(seg: Segment, config: Config) -> str:
    """What happened to a failed check, then what to do (copy rules, base spec §12)."""
    where = f"{config.account_name(seg.account)} · {seg.region}"
    if seg.error_kind == "expired":
        return "AWS session expired. Refresh your MFA session, then Scan now."
    if seg.error == "sts:AssumeRole":  # the hop from admin into this account, for every region
        return (
            f"Janitor can't assume {config.member_role or 'the member role'} in "
            f"{config.account_name(seg.account)}. Check that the role exists there and trusts the "
            "admin account, then Scan now."
        )
    if seg.error_kind == "denied":
        return f"Janitor isn't allowed to call {seg.error} in {where}. Ask for read access, then Scan now."
    if seg.error_kind == "throttled":
        return f"AWS throttled requests in {where}. Scan again in a few minutes."
    if seg.error_kind == "blocked":
        return "Janitor stopped a call that isn't read-only. Report this; nothing was sent."
    detail = seg.error.strip().rstrip(".") or "The check failed"
    return f"{detail}. Scan again; if it repeats, check the server log."


def recompute_rules(store: Store, config: Config, scan_id: int, now: datetime) -> None:
    """Rules run after each scan and at startup, so config changes apply without rescanning."""
    results = [hit for r in store.all_resources(scan_id) for hit in evaluate(r, config.policy, now)]
    store.save_rule_results(scan_id, results)


class Scanner:
    def __init__(
        self,
        store: Store,
        provider: CloudProvider,
        config: Config,
        clock: Callable[[], datetime] | None = None,
        prices: PriceTable | None = None,
    ):
        self._store = store
        self._provider = provider
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))
        self._prices = prices or PriceTable(config.pricing)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def run(self) -> int:
        """Scan in the calling thread and return the scan ID."""
        if not self._lock.acquire(blocking=False):
            raise ScanRunning
        try:
            return self._scan()
        finally:
            self._lock.release()

    def start(self) -> None:
        """Scan in a background thread."""
        if not self._lock.acquire(blocking=False):
            raise ScanRunning

        def work() -> None:
            try:
                self._scan()
            except Exception:
                log.exception("Scan failed")
            finally:
                self._lock.release()

        self._thread = threading.Thread(target=work, name="janitor-scan", daemon=True)
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _scan(self) -> int:
        now = self._clock()
        provider = self._provider.name
        scan_id = self._store.start_scan(provider)
        self._store.add_audit("scan_started", {"scan_id": scan_id, "provider": provider})
        try:
            inventory = self._provider.list_inventory(
                on_segment=lambda seg: self._store.add_segment(scan_id, seg)
            )
            failed = [s for s in inventory.segments if not s.ok]
            if inventory.segments and len(failed) == len(inventory.segments):
                raise AllChecksFailed(segment_message(failed[0], self._config))
            ctx = LinkContext.from_config(self._config, now, inventory.segments)
            statuses = link(inventory, ctx)
            named = references(inventory, ctx)
            for r in inventory.resources:
                r.status, r.status_reason = statuses[r.id]
                r.referenced_by = named.get(r.id) if r.status != "in_use" else None
            apply_costs(inventory.resources, self._prices)
            self._store.save_inventory(
                scan_id, inventory.resources, inventory.shares, inventory.usage, inventory.databases
            )
            self._store.set_notes(
                scan_id, {"unresolved": [asdict(u) for u in inventory.unresolved]}
            )
            recompute_rules(self._store, self._config, scan_id, now)
        except Exception as exc:
            self._store.set_notes(scan_id, {"error": str(exc)})
            self._store.finish_scan(scan_id, "failed")
            self._store.add_audit(
                "scan_finished", {"scan_id": scan_id, "status": "failed", "error": str(exc)}
            )
            if not isinstance(exc, AllChecksFailed):
                raise
            return scan_id  # an expected outcome, recorded on the scan; the old data stays
        status = "partial" if failed else "ok"
        self._store.finish_scan(scan_id, status)
        self._store.add_audit(
            "scan_finished",
            {
                "scan_id": scan_id,
                "status": status,
                "resources": len(inventory.resources),
                "failed_checks": len(failed),
            },
        )
        return scan_id
