"""Run one scan: read the inventory, compute statuses and rule results, store them."""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from janitor.config import Config, Pricing
from janitor.linker import LinkContext, link
from janitor.models import Resource
from janitor.providers.base import CloudProvider
from janitor.rules import evaluate
from janitor.store import Store

log = logging.getLogger(__name__)


class ScanRunning(Exception):
    """Raised when a scan is requested while one is running."""


def estimate_cost(r: Resource, pricing: Pricing) -> float | None:
    """Monthly estimate: size × rate. AMIs have no cost of their own; their snapshots do."""
    if r.size_gb is None or r.type == "ami":
        return None
    if r.type == "snapshot":
        rate = pricing.snapshot_gb_month
    elif r.type == "rds_snapshot":
        rate = pricing.rds_snapshot_gb_month
    else:
        rate = pricing.volume_gb_month.get(r.volume_type or "")
        if rate is None:
            return None
    return round(r.size_gb * rate, 2)


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
    ):
        self._store = store
        self._provider = provider
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))
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
            inventory = self._provider.list_inventory()
            statuses = link(inventory, LinkContext.from_config(self._config, now))
            for r in inventory.resources:
                r.status, r.status_reason = statuses[r.id]
                r.est_monthly_cost = estimate_cost(r, self._config.pricing)
            self._store.save_inventory(
                scan_id, inventory.resources, inventory.shares, inventory.usage
            )
            recompute_rules(self._store, self._config, scan_id, now)
        except Exception as exc:
            self._store.finish_scan(scan_id, "failed")
            self._store.add_audit(
                "scan_finished", {"scan_id": scan_id, "status": "failed", "error": str(exc)}
            )
            raise
        self._store.finish_scan(scan_id, "ok")
        self._store.add_audit(
            "scan_finished",
            {"scan_id": scan_id, "status": "ok", "resources": len(inventory.resources)},
        )
        return scan_id
