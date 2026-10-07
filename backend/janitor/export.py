"""Export the filtered resource list: CSV with every row, JSON (capped) for the PDF report."""

import csv
import io
from collections.abc import Iterator

from janitor.config import Config
from janitor.rules import strictest
from janitor.store import Store

CSV_COLUMNS = [
    "id",
    "name",
    "type",
    "account",
    "account_name",
    "region",
    "status",
    "status_reason",
    "delete_check",
    "created_at",
    "size_gib",
    "est_monthly_usd",
    "tags",
]
PDF_LIMIT = 5000
PAGE = 1000
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> str:
    """Spreadsheet apps run cells starting with these as formulas; a leading ' stops that."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def _rows(
    store: Store, config: Config, scan_id: int, filters: dict, sort: str, limit: int | None = None
) -> Iterator[dict]:
    page, sent = 1, 0
    while True:
        items, _ = store.query_resources(scan_id, filters, sort, page, PAGE)
        hits = store.rule_results(scan_id, [r.id for r in items])
        for r in items:
            if limit is not None and sent >= limit:
                return
            yield {
                "id": r.id,
                "name": r.name,
                "type": r.type,
                "account": r.account,
                "account_name": config.account_name(r.account),
                "region": r.region,
                "status": r.status,
                "status_reason": r.status_reason,
                "delete_check": strictest(hits.get(r.id, [])),
                "created_at": r.created_at,
                "size_gib": r.size_gb,
                "est_monthly_usd": r.est_monthly_cost,
                "tags": ";".join(f"{k}={v}" for k, v in sorted(r.tags.items())),
            }
            sent += 1
        if len(items) < PAGE:
            return
        page += 1


def csv_lines(
    store: Store, config: Config, scan_id: int, filters: dict, sort: str
) -> Iterator[str]:
    """The CSV, one line at a time, so large exports stream instead of filling memory."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def flush() -> str:
        text = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return text

    writer.writerow(CSV_COLUMNS)
    yield flush()
    for row in _rows(store, config, scan_id, filters, sort):
        writer.writerow([safe_cell(row[column]) for column in CSV_COLUMNS])
        yield flush()


def json_export(
    store: Store, config: Config, scan_id: int, filters: dict, sort: str, limit: int = PDF_LIMIT
) -> dict:
    items = list(_rows(store, config, scan_id, filters, sort, limit))
    total = store.query_resources(scan_id, filters, sort, 1, 1)[1]
    return {"items": items, "total": total, "truncated": total > len(items), "limit": limit}
