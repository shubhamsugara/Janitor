import csv
import io

from helpers import NOW

from janitor import export
from janitor.models import Inventory, Resource
from janitor.scanner import Scanner
from janitor.store import Store


def _store(tmp_path, config, resources):
    class Provider:
        name = "mock"

        def list_inventory(self, on_segment=None):
            return Inventory(resources, [], [], [])

    store = Store(tmp_path / "j.db")
    return store, Scanner(store, Provider(), config, clock=lambda: NOW).run()


def _r(id, name, **kw):
    return Resource(
        id=id,
        type="volume",
        account="111111111111",
        region="us-east-1",
        name=name,
        created_at="2026-01-01T00:00:00Z",
        size_gb=10,
        volume_type="gp3",
        tags={"owner": "me"} | kw.pop("tags", {}),
        **kw,
    )


def test_safe_cell():
    assert export.safe_cell("=1+1") == "'=1+1"
    assert export.safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert export.safe_cell("plain") == "plain"
    assert export.safe_cell(None) == ""
    assert export.safe_cell(12.5) == "12.5"


def test_csv_escapes_formula_cells(tmp_path, config):
    store, scan_id = _store(
        tmp_path, config, [_r("vol-1", '=HYPERLINK("http://x")', tags={"note": "+cmd"})]
    )
    text = "".join(export.csv_lines(store, config, scan_id, {"type": "volume"}, "-created_at"))
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == export.CSV_COLUMNS
    row = dict(zip(rows[0], rows[1], strict=True))
    assert row["name"].startswith("'=") and row["account_name"] == "tools"
    assert row["delete_check"] in ("pass", "warn", "block")


def test_csv_includes_every_matching_row(tmp_path, config):
    store, scan_id = _store(tmp_path, config, [_r(f"vol-{n}", f"v{n}") for n in range(1203)])
    lines = list(export.csv_lines(store, config, scan_id, {"type": "volume"}, "id"))
    assert len(lines) == 1204  # header + every row, across pages of 1,000


def test_json_export_caps_rows(tmp_path, config):
    store, scan_id = _store(tmp_path, config, [_r(f"vol-{n}", f"v{n}") for n in range(12)])
    body = export.json_export(store, config, scan_id, {"type": "volume"}, "id", limit=5)
    assert len(body["items"]) == 5 and body["total"] == 12 and body["truncated"] is True
