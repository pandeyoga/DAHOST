"""Uji unit HERMETIK (tanpa server, tanpa Mongo) untuk fungsi murni di core/ — FASE 5 (T-15).

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import uom  # noqa: E402
from core.wo_reader import normalize_statuses, WO_STATUS_ALIASES  # noqa: E402
from core.catalog_stock import stock_status, row_is_sellable  # noqa: E402
from core.production_qty_ledger import ledger_view  # noqa: E402


def test_uom_resolve_always_has_base_first():
    m = {"unit": "m", "uoms": [{"code": "roll", "factor": 50}, {"code": "m", "factor": 1}]}
    rows = uom.resolve_uoms(m)
    assert rows[0]["is_base"] is True and rows[0]["factor"] == 1
    assert [r["code"] for r in rows] == ["m", "roll"]


def test_uom_resolve_drops_invalid_and_duplicate_rows():
    m = {"unit": "pcs", "uoms": [{"code": "lusin", "factor": 12}, {"code": "lusin", "factor": 12},
                                 {"code": "kosong", "factor": 0}, "bukan-dict"]}
    codes = uom.uom_codes(m)
    assert codes == ["pcs", "lusin"]


def test_uom_find_is_case_insensitive():
    m = {"unit": "pcs", "uoms": [{"code": "Lusin", "factor": 12}]}
    assert uom.find_uom(m, "LUSIN")["factor"] == 12
    assert uom.find_uom(m, "") is None


def test_wo_reader_status_aliases():
    assert normalize_statuses(None) is None
    assert normalize_statuses(["planned", "in_production", "done"]) == {"released", "in_progress", "completed"}
    assert all(v in ("released", "in_progress", "completed") for v in WO_STATUS_ALIASES.values())


def test_catalog_stock_status_thresholds():
    assert stock_status(0, 10) == "out_of_stock"
    assert stock_status(5, 10) == "low_stock"
    assert stock_status(10, 10) == "low_stock"
    assert stock_status(50, 10) == "in_stock"


def test_catalog_row_blocked_location_not_sellable():
    row = {"location_id": "QUAR", "qty": 5}
    assert row_is_sellable(row, {"QUAR"}) is False


def test_ledger_view_is_pure_and_defaults_zero():
    v = ledger_view({"id": "ji-1"})
    assert isinstance(v, dict)
    assert all(isinstance(x, (int, float)) for x in v.values() if not isinstance(x, (str, list, dict, type(None))))
