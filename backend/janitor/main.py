"""FastAPI app: the JSON API under /api, a health check, and the built SPA.

Run: uvicorn janitor.main:create_app --factory --host 127.0.0.1 --port 8080
"""

import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Self

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from janitor import definitions, plans
from janitor.config import load_config
from janitor.graph import build_graph
from janitor.pricing import PriceTable
from janitor.providers.mock import MockProvider
from janitor.rules import RULES, strictest
from janitor.scanner import Scanner, ScanRunning, recompute_rules
from janitor.store import Store

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def create_app(
    settings: Settings | None = None, clock: Callable[[], datetime] | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    clock = clock or (lambda: datetime.now(UTC))
    config = load_config(settings.config_path)
    if config.provider != "mock":
        raise RuntimeError(
            "This version has only the mock provider. Set provider: mock, then start again."
        )
    provider = MockProvider(settings.seed_path, clock=clock)
    store = Store(settings.db_path)
    store.fail_running_scans()
    prices = PriceTable.load(settings.prices_path, config.pricing)
    scanner = Scanner(store, provider, config, clock, prices)
    latest = store.latest_scan()
    if latest:
        recompute_rules(store, config, latest["id"], clock())
    elif settings.scan_on_startup:
        scanner.run()  # the mock scan takes milliseconds

    app = FastAPI(title="Janitor")
    app.state.store = store
    app.state.scanner = scanner

    def scan_id() -> int | None:
        scan = store.latest_scan()
        return scan["id"] if scan else None

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/meta")
    def meta():
        return {
            "provider": provider.name,
            "read_only": True,
            "owner": config.owner.model_dump(),
            "accounts": [
                {
                    "id": account_id,
                    "name": a.name,
                    "owns": a.owns,
                    "regions": config.regions_for(account_id),
                }
                for account_id, a in config.accounts.items()
            ],
            "definitions": definitions.build(config),
        }

    @app.get("/api/overview")
    def overview():
        scan = store.latest_scan()
        return {
            "last_scan": scan,
            "scanning": scanner.running,
            "types": store.overview(scan["id"]) if scan else [],
        }

    @app.get("/api/resources")
    def resources(
        type: str | None = None,
        q: str | None = None,
        account: str | None = None,
        region: str | None = None,
        status: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        tag: str | None = None,
        sort: str = "-created_at",
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    ):
        current = scan_id()
        if current is None:
            return {"items": [], "total": 0, "stats": None, "scan_id": None}
        filters = {
            "type": type,
            "q": q,
            "account": account,
            "region": region,
            "status": status,
            "created_from": created_from,
            "created_to": created_to,
            "tag": tag,
        }
        try:
            items, total = store.query_resources(current, filters, sort, page, page_size)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        hits = store.rule_results(current, [r.id for r in items])
        return {
            "items": [asdict(r) | {"outcome": strictest(hits.get(r.id, []))} for r in items],
            "total": total,
            "stats": store.stats(current, filters),
            "scan_id": current,
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
        return {"scan": store.last_scan(), "running": scanner.running}

    @app.post("/api/actions/plan")
    def plan(request: PlanRequest):
        try:
            return plans.make_plan(store, config, request.ids, clock())
        except plans.PlanError as error:
            raise HTTPException(error.status_code, error.message) from error

    @app.post("/api/actions/simulate")
    def simulate(request: SimulateRequest):
        try:
            return plans.simulate(store, config, request.plan_id, request.confirmation)
        except plans.PlanError as error:
            raise HTTPException(error.status_code, error.message) from error

    @app.get("/api/audit")
    def audit(
        page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=200)] = 50
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
