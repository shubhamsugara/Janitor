"""FastAPI app: the JSON API under /api, a health check, and the built SPA.

Run: uvicorn janitor.main:create_app --factory --host 127.0.0.1 --port 8080
"""

import os
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Self

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from janitor import definitions, export, plans
from janitor.config import load_config
from janitor.graph import build_graph
from janitor.models import TYPES, Segment, format_ts
from janitor.pricing import PriceTable
from janitor.providers.base import CloudProvider
from janitor.providers.mock import MockProvider
from janitor.rules import RULES, strictest
from janitor.scanner import Scanner, ScanRunning, recompute_rules, segment_message
from janitor.store import SORTABLE, Store

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_PAGE = 1_000_000  # larger offsets overflow SQLite's integer


class Settings(BaseModel):
    config_path: str | None = None
    db_path: str = "data/janitor.db"
    seed_path: str = str(REPO_ROOT / "fixtures" / "seed.json")
    static_dir: str = str(REPO_ROOT / "frontend" / "dist")
    prices_path: str = str(REPO_ROOT / "fixtures" / "prices.json")
    scan_on_startup: bool = True

    @classmethod
    def from_env(cls) -> Self:
        defaults = cls()
        return cls(
            config_path=os.environ.get("JANITOR_CONFIG"),
            db_path=os.environ.get("JANITOR_DB", defaults.db_path),
            seed_path=os.environ.get("JANITOR_SEED", defaults.seed_path),
            static_dir=os.environ.get("JANITOR_STATIC_DIR", defaults.static_dir),
            prices_path=os.environ.get("JANITOR_PRICES", defaults.prices_path),
        )


class PlanRequest(BaseModel):
    type: str | None = None
    ids: list[str]


class SimulateRequest(BaseModel):
    plan_id: str
    confirmation: str = ""


DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def list_filters(
    type: str | None = None,
    q: str | None = None,
    account: str | None = None,
    region: str | None = None,
    status: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    tag: str | None = None,
) -> dict:
    """The resource filters shared by the list, stats, and export routes."""
    for name, value in (("created_from", created_from), ("created_to", created_to)):
        if value is None:
            continue
        try:
            if not DATE.match(value):
                raise ValueError(value)
            date.fromisoformat(value)
        except ValueError:
            raise HTTPException(
                422, f"Use YYYY-MM-DD for {name}, for example 2026-01-31."
            ) from None
    return {
        "type": type,
        "q": q,
        "account": account,
        "region": region,
        "status": status,
        "created_from": created_from,
        "created_to": created_to,
        "tag": tag,
    }


Filters = Annotated[dict, Depends(list_filters)]


def _check_sort(sort: str) -> None:
    if sort.lstrip("-") not in SORTABLE:
        raise HTTPException(
            422, f"Can't sort by {sort.lstrip('-')}. Choose one of: {', '.join(sorted(SORTABLE))}."
        )


def make_provider(config, settings: Settings, clock) -> CloudProvider:
    if config.provider == "aws":
        from janitor.providers.aws import AwsProvider
        from janitor.providers.session import check_profiles

        check_profiles(config)  # stops startup with every bad profile named
        return AwsProvider(config, clock)
    return MockProvider(settings.seed_path, clock=clock, config=config)


def create_app(
    settings: Settings | None = None,
    clock: Callable[[], datetime] | None = None,
    provider: CloudProvider | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    clock = clock or (lambda: datetime.now(UTC))
    config = load_config(settings.config_path)
    provider = provider or make_provider(config, settings, clock)
    store = Store(settings.db_path, provider=provider.name)
    store.fail_running_scans()
    prices = PriceTable.load(settings.prices_path, config.pricing)
    scanner = Scanner(store, provider, config, clock, prices)
    latest = store.latest_scan()
    if latest:
        recompute_rules(store, config, latest["id"], clock())
    elif settings.scan_on_startup:
        if provider.name == "mock":
            scanner.run()  # the mock scan takes milliseconds
        else:
            scanner.start()  # a real scan takes minutes; answer requests meanwhile

    app = FastAPI(title="Janitor")
    app.state.store = store
    app.state.scanner = scanner

    def scan_id() -> int | None:
        scan = store.latest_scan()
        return scan["id"] if scan else None

    @app.get("/health")
    def health():
        return {"status": "ok"}

    def known_accounts() -> list[str]:
        """The admin, the named accounts, then any account the shown scan discovered."""
        scan = store.latest_scan()
        seen = [s["account"] for s in store.segments(scan["id"])] if scan else []
        return list(dict.fromkeys([config.admin.account, *config.accounts, *sorted(seen)]))

    @app.get("/api/meta")
    def meta():
        return {
            "provider": provider.name,
            "read_only": True,
            "owner": {"account": config.admin.account, "regions": config.regions},
            "accounts": [
                {
                    "id": account_id,
                    "name": config.account_name(account_id),
                    "regions": config.regions_for(account_id),
                }
                for account_id in known_accounts()
            ],
            "accounts_by_type": store.accounts_by_type(shown["id"])
            if (shown := store.latest_scan())
            else {},
            "policy": {
                "orphan_after_days": config.policy.orphan_after_days,
                "min_age_days": config.policy.min_age_days,
                "typed_confirm_min_items": config.policy.typed_confirm_min_items,
            },
            "prices": {"source_date": prices.source_date, "fallback": not prices.data},
            "definitions": definitions.build(config),
        }

    def failed_checks(scan_id: int) -> list[dict]:
        return [
            {
                "account": seg["account"],
                "account_name": config.account_name(seg["account"]),
                "region": seg["region"],
                "kind": seg["kind"],
                "error_kind": seg["error_kind"],
                "message": segment_message(Segment(**seg), config),
            }
            for seg in store.segments(scan_id)
            if not seg["ok"]
        ]

    @app.get("/api/overview")
    def overview():
        scan = store.latest_scan()
        newest = store.last_scan()
        newest_failed = None
        if newest and newest["status"] == "failed" and (not scan or newest["id"] != scan["id"]):
            newest_failed = {
                "finished_at": newest["finished_at"],
                "message": newest["notes"].get("error") or "The scan failed.",
            }
        return {
            "last_scan": scan,
            "scanning": scanner.running,
            "types": store.overview(scan["id"]) if scan else [],
            "segments_failed": failed_checks(scan["id"]) if scan else [],
            "unresolved": scan["notes"].get("unresolved", []) if scan else [],
            "newest_failed": newest_failed,
        }

    @app.get("/api/resources")
    def resources(
        filters: Filters,
        sort: str = "-created_at",
        page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    ):
        current = scan_id()
        if current is None:
            return {"items": [], "total": 0, "stats": None, "scan_id": None}
        _check_sort(sort)
        items, total = store.query_resources(current, filters, sort, page, page_size)
        hits = store.rule_results(current, [r.id for r in items])
        return {
            "items": [asdict(r) | {"outcome": strictest(hits.get(r.id, []))} for r in items],
            "total": total,
            "stats": store.stats(current, filters, clock()),
            "scan_id": current,
        }

    @app.get("/api/stats")
    def stats(filters: Filters):
        current = scan_id()
        return store.stats(current, filters, clock()) if current else None

    def export_scan(sort: str) -> int:
        current = scan_id()
        if current is None:
            raise HTTPException(409, "No scan yet. Run a scan, then export.")
        _check_sort(sort)
        return current

    @app.get("/api/resources/export.csv")
    def export_csv(filters: Filters, sort: str = "-created_at"):
        current = export_scan(sort)
        kind = (
            filters["type"] if filters["type"] in TYPES else "all"
        )  # never echo raw input into a header
        name = f"janitor-{kind}-{clock():%Y%m%d}.csv"
        return StreamingResponse(
            export.csv_lines(store, config, current, filters, sort),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/resources/export.json")
    def export_json(filters: Filters, sort: str = "-created_at"):
        current = export_scan(sort)
        body = export.json_export(store, config, current, filters, sort)
        return body | {
            "stats": store.stats(current, filters, clock()),
            "filters": {k: v for k, v in filters.items() if v},
            "generated_at": format_ts(clock()),
            "provider": provider.name,
        }

    @app.get("/api/resources/{resource_id:path}/graph")
    def resource_graph(resource_id: str):
        current = scan_id()
        result = build_graph(store, config, current, resource_id) if current else None
        if result is None:
            raise HTTPException(404, "That resource isn't in the latest scan. Reload the list.")
        return result

    @app.get("/api/resources/{resource_id:path}")
    def resource_detail(resource_id: str):
        current = scan_id()
        found = store.get_resources(current, [resource_id]) if current else []
        if not found:
            raise HTTPException(404, "That resource isn't in the latest scan. Reload the list.")
        r = found[0]
        hits = {h.rule_id: h for h in store.rule_results(current, [r.id]).get(r.id, [])}
        rules = [
            {
                "id": rule.id,
                "title": rule.title,
                "outcome": hits[rule.id].outcome if rule.id in hits else "pass",
                "message": hits[rule.id].message if rule.id in hits else "",
            }
            for rule in RULES
        ]
        return {
            "resource": asdict(r) | {"outcome": strictest(hits.values())},
            "rules": rules,
            "related": store.related(current, r),
        }

    @app.post("/api/scans", status_code=202)
    def start_scan():
        try:
            scanner.start()
        except ScanRunning as exc:
            raise HTTPException(409, "A scan is already running. Wait for it to finish.") from exc
        return {"started": True}

    @app.get("/api/scans/latest")
    def latest_scan():
        scan = store.last_scan()
        segments = store.segments(scan["id"]) if scan else []
        return {
            "scan": scan,
            "running": scanner.running,
            "segments": segments,
            "progress": {"done": len(segments), "failed": sum(not s["ok"] for s in segments)},
        }

    @app.post("/api/actions/plan")
    def plan(request: PlanRequest):
        try:
            return plans.make_plan(store, config, request.ids, clock())
        except plans.PlanError as error:
            raise HTTPException(error.status_code, error.message) from error

    @app.post("/api/actions/simulate")
    def simulate(request: SimulateRequest):
        try:
            return plans.simulate(
                store, config, request.plan_id, request.confirmation, recheck=provider.recheck
            )
        except plans.PlanError as error:
            raise HTTPException(error.status_code, error.message) from error

    @app.get("/api/audit")
    def audit(
        page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        items, total = store.list_audit(page, page_size)
        return {"items": items, "total": total}

    static = Path(settings.static_dir).resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        index = static / "index.html"
        if not index.exists():
            raise HTTPException(404, "The UI isn't built. Run make build, or use make dev.")
        file = (static / path).resolve()
        if path and file.is_file() and file.is_relative_to(static):
            return FileResponse(file)
        return FileResponse(index)

    return app
