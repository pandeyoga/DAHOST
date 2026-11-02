"""Uji unit HERMETIK paket P3 — biaya FG dari CMT (F1), BOM per warna (F1b), pesan
galat posting, status Laporan Nilai Persediaan FG (2026-11-02).

Angka harapan dihitung tangan dari BOM DA-1101 di seed go-live (audit p.md §0.1):
  CRL = potongan 32.175 + karet 0,6 × 912,766 + rit 0,016667 × 3.025
        + bisban 3,8 × 15.400 + label 0,001667 × 61.800 = 91.396,10 /pcs
  BRG = potongan 32.175 saja.

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from p3_fakes import FakeDB  # noqa: E402
from core import product_costing as pc  # noqa: E402
from core import production_qty_ledger as qled  # noqa: E402
from core import bom_uom  # noqa: E402


def run(coro):
    return asyncio.run(coro)


MODEL, SIZE = "m-1101", "s-all"
MATS = [
    {"id": "cut-crl", "code": "CUT-DA-1101-CRL-ALLSIZE", "type": "cut_panel", "unit": "pcs", "unit_cost": 32175.0},
    {"id": "cut-brg", "code": "CUT-DA-1101-BRG-ALLSIZE", "type": "cut_panel", "unit": "pcs", "unit_cost": 32175.0},
    {"id": "krt", "code": "A-KRT-0003", "type": "accessory", "unit": "m", "unit_cost": 912.766},
    {"id": "r45", "code": "A-R45-0001", "type": "accessory", "unit": "pack", "unit_cost": 3025.0},
    {"id": "bis", "code": "A-BIS-0001", "type": "accessory", "unit": "m", "unit_cost": 15400.0},
    {"id": "lbl", "code": "A-LBL-0004", "type": "accessory", "unit": "roll", "unit_cost": 61800.0},
]


def _line(mid, code, qty, unit):
    return {"material_id": mid, "code": code, "name": code, "qty": qty, "qty_base": qty,
            "unit": unit, "unit_base": unit, "uom_status": "base"}


BOM_BRG = {"id": "bom-brg", "model_id": MODEL, "size_id": SIZE, "color": "BURGUNDY", "color_code": "BRG",
           "active": True, "is_active": True, "version": 1,
           "materials": [_line("cut-brg", "CUT-DA-1101-BRG-ALLSIZE", 1.0, "pcs")]}
BOM_CRL = {"id": "bom-crl", "model_id": MODEL, "size_id": SIZE, "color": "CARAMEL", "color_code": "CRL",
           "active": True, "is_active": True, "version": 1,
           "materials": [_line("cut-crl", "CUT-DA-1101-CRL-ALLSIZE", 1.0, "pcs"),
                         _line("krt", "A-KRT-0003", 0.6, "m"),
                         _line("r45", "A-R45-0001", 0.016667, "pack"),
                         _line("bis", "A-BIS-0001", 3.8, "m"),
                         _line("lbl", "A-LBL-0004", 0.001667, "roll")]}
HAND_CRL = round(32175 + 0.6 * 912.766 + 0.016667 * 3025 + 3.8 * 15400 + 0.001667 * 61800, 2)


@pytest.fixture(autouse=True)
def _plain_uom(monkeypatch):
    async def ensure_uom(db, bom):
        return list(bom.get("materials") or []), []
    monkeypatch.setattr(bom_uom, "ensure_uom", ensure_uom)


def _db():
    # BRG disimpan duluan → perilaku lama (find_one tanpa warna) memilih BRG, persis seperti seed.
    return FakeDB(rahaza_boms=[BOM_BRG, BOM_CRL], rahaza_materials=MATS)


# ── F1b: pemilih BOM per warna ───────────────────────────────────────────────
def test_pick_bom_for_color_exact_general_other_none():
    general = {"id": "g", "color": "", "color_code": ""}
    cands = [BOM_BRG, BOM_CRL, general]
    assert pc.pick_bom_for_color(cands, "CARAMEL") == (BOM_CRL, pc.BOM_MATCH_EXACT)
    assert pc.pick_bom_for_color(cands, "crl") == (BOM_CRL, pc.BOM_MATCH_EXACT)      # kode, beda huruf
    assert pc.pick_bom_for_color(cands, "HITAM") == (general, pc.BOM_MATCH_GENERAL)
    assert pc.pick_bom_for_color([BOM_BRG, BOM_CRL], "HITAM")[1] == pc.BOM_MATCH_OTHER
    assert pc.pick_bom_for_color(cands, "")[1] == pc.BOM_MATCH_NONE


def test_hand_value_matches_audit():
    assert HAND_CRL == pytest.approx(91396.10, abs=0.01)


def test_material_cost_uses_color_bom_crl_not_brg():
    db = _db()
    crl = run(pc.compute_material_cost(db, MODEL, SIZE, color="CRL"))
    assert crl["bom_id"] == "bom-crl" and crl["bom_color_match"] == pc.BOM_MATCH_EXACT
    assert crl["material_cost"] == pytest.approx(91396.10, abs=0.01)
    # tanpa warna: perilaku lama persis (BOM pertama = BRG, 32.175)
    legacy = run(pc.compute_material_cost(db, MODEL, SIZE))
    assert legacy["bom_id"] == "bom-brg" and legacy["material_cost"] == pytest.approx(32175.0)


def test_color_without_own_bom_falls_back_safely_with_gap():
    db = _db()
    out = run(pc.compute_material_cost(db, MODEL, SIZE, color="HITAM"))
    assert out["bom_id"] == "bom-brg"                      # = BOM lama, bukan error
    assert out["bom_color_match"] == pc.BOM_MATCH_OTHER
    assert any(g["code"] == "bom_color_missing" for g in out["gaps"])


def test_color_scope_bridges_callers_without_color_arg():
    db = _db()

    async def go():
        with pc.bom_color_scope("CARAMEL"):
            inside = await pc.find_active_bom(db, MODEL, SIZE)
        outside = await pc.find_active_bom(db, MODEL, SIZE)
        explicit = None
        with pc.bom_color_scope("CARAMEL"):
            explicit = await pc.find_active_bom(db, MODEL, SIZE, "BRG")   # argumen menang
        return inside, outside, explicit
    inside, outside, explicit = run(go())
    assert inside["id"] == "bom-crl" and outside["id"] == "bom-brg" and explicit["id"] == "bom-brg"


def test_color_costs_per_fg_variant():
    db = _db()
    size_mc = run(pc.compute_material_cost(db, MODEL, SIZE))
    fg_rows = [{"id": "fg-crl", "code": "DA-1101-CRL-ALLSIZE", "color_code": "CRL", "color_name": "CARAMEL"},
               {"id": "fg-brg", "code": "DA-1101-BRG-ALLSIZE", "color_code": "BRG", "color_name": "BURGUNDY"}]
    colors, gaps = run(pc._color_costs(db, MODEL, {"size_id": SIZE, "size_code": "ALLSIZE"}, fg_rows, size_mc,
                                        cmt_rate=15000, labor_rate=0, overhead=0, cache={}))
    by = {c["fg_id"]: c for c in colors}
    assert by["fg-crl"]["material_cost"] == pytest.approx(91396.10, abs=0.01)
    assert by["fg-crl"]["hpp_unit"] == pytest.approx(106396.10, abs=0.01)     # + jahit SPK 15.000
    assert by["fg-brg"]["hpp_unit"] == pytest.approx(47175.0)
    assert not gaps


def test_apply_model_cost_writes_each_color_its_own_hpp(monkeypatch):
    db = FakeDB(rahaza_materials=[{"id": "fg-crl", "type": "fg"}, {"id": "fg-brg", "type": "fg"}],
                marketing_catalog_items=[{"id": "ci-1", "fg_material_id": "fg-crl"}],
                rahaza_models=[{"id": MODEL}])

    def color(fid, mc):
        return {"fg_id": fid, "code": fid, "color": fid[-3:].upper(), "bom_id": "b-" + fid, "bom_version": 1,
                "bom_color": "", "bom_color_match": "exact", "material_cost": mc, "fabric_cost": 0,
                "accessory_cost": 0, "other_cost": mc, "unvalued_count": 0, "bad_line_statuses": [],
                "computable": True, "hpp_unit": mc, "confidence": "partial"}

    async def fake_compute(db_, model_id, **kw):
        return {"model": {"code": "DA-1101", "name": "Lyora"}, "cmt": {"rate": 0, "source": "none"},
                "internal_labor": {"rate": 0, "source": "none"}, "overhead": {"rate": 0, "included": False},
                "gaps": [], "gap_count": 0,
                "sizes": [{"size_id": SIZE, "size_code": "ALLSIZE", "bom_id": "bom-brg", "hpp_unit": 32175.0,
                           "computable": True, "lines": [], "cmt_cost": 0, "internal_labor_cost": 0,
                           "overhead_cost": 0, "fg_variants": [{"id": "fg-crl"}, {"id": "fg-brg"}],
                           "colors": [color("fg-crl", 91396.10), color("fg-brg", 32175.0)]}]}
    monkeypatch.setattr(pc, "compute_model_cost", fake_compute)
    out = run(pc.apply_model_cost(db, MODEL, {"id": "u1", "name": "Uji"}))
    hpp = {d["id"]: d.get("hpp") for d in db.rahaza_materials.docs}
    assert hpp == {"fg-crl": pytest.approx(91396.10), "fg-brg": pytest.approx(32175.0)}
    assert db.marketing_catalog_items.docs[0]["hpp"] == pytest.approx(91396.10)
    assert out["ok"] and len(out["applied"]) == 2


# ── F1: post_fg_accepted membawa biaya ───────────────────────────────────────
def _patch_ledger(monkeypatch, captured):
    from core import stock_service
    from core import fg_cost_layers as fcl

    async def loc(db):
        return "loc-fg"

    async def add(*a, **kw):
        captured["stock_meta"] = kw.get("meta")
        return {"qty": a[2]}

    async def push_layer(db, **kw):
        captured["push"] = kw
        captured["hint"] = pc._BOM_COLOR_HINT.get()
        doc = {"id": "ly-new", "unit_cost": kw.get("unit_cost")}
        await db.fg_cost_layers.insert_one(dict(doc))
        return doc
    monkeypatch.setattr(qled, "resolve_fg_location_id", loc)
    monkeypatch.setattr(stock_service, "add", add)
    monkeypatch.setattr(fcl, "push_layer", push_layer)


def test_post_fg_accepted_uses_po_item_and_its_color(monkeypatch):
    cap = {}
    _patch_ledger(monkeypatch, cap)
    db = FakeDB(po_items=[{"id": "poi-1", "model_id": MODEL, "size_id": SIZE, "color": "CARAMEL",
                           "color_code": "CRL", "cmt_price_snapshot": 15000}])
    run(qled.post_fg_accepted(db, material_id="fg-crl", qty=10,
                              ref={"source": "cmt_receipt", "po_item_id": "poi-1"}))
    assert cap["push"]["po_item"]["id"] == "poi-1"           # dulu po_item={} → lapisan Rp 0
    assert cap["hint"] == "CRL"                              # BOM warna varian SPK
    assert cap["stock_meta"]["inventory_category"] == "fg_internal"


def test_exit_cost_summary_and_return_layer(monkeypatch):
    s = qled.summarize_exit_consumptions([
        {"qty": 8, "cogs": 851168.8, "uncosted_qty": 0, "layers_used": [{"layer_id": "L1"}]},
        {"qty": 2, "cogs": 212792.2, "uncosted_qty": 0, "layers_used": [{"layer_id": "L1"}]}])
    assert s["found"] and s["unit_cost"] == pytest.approx(106396.10, abs=0.01)
    db = FakeDB(fg_cost_consumptions=[{"material_id": "fg", "qty": 10, "cogs": 1063961.0, "uncosted_qty": 0,
                                       "layers_used": [{"layer_id": "L1"}], "ref": {"shipment_item_id": "bsi-1"}}],
                fg_cost_layers=[{"id": "L1", "gl_je_id": "je-wipfg"}])
    ec = run(qled.exit_cost_of(db, material_id="fg", shipment_item_id="bsi-1", sku="SKU"))
    assert ec["unit_cost"] == pytest.approx(106396.10) and ec["gl_je_id"] == "je-wipfg"
    cap = {}
    _patch_ledger(monkeypatch, cap)
    run(qled.post_fg_accepted(db, material_id="fg", qty=2, ref={"source": "buyer_shipment_cancel"}, exit_cost=ec))
    assert cap["push"]["unit_cost"] == pytest.approx(106396.10)          # bukan Rp 0
    layer = next(d for d in db.fg_cost_layers.docs if d["id"] == "ly-new")
    assert layer["gl_je_id"] == "je-wipfg"                                # tidak jadi "belum berjurnal" palsu
    none = qled.exit_cost_breakdown(qled.summarize_exit_consumptions([]))
    assert none["unit_cost"] == 0 and none["gaps"]                       # tidak ditebak, diberi alasan


def test_resolve_fg_location_no_first_active_fallback():
    db = FakeDB(rahaza_locations=[{"id": "ktr", "code": "KTR-PST", "type": "zona", "active": True}])
    assert run(qled.resolve_fg_location_id(db)) is None


# ── Pesan galat posting & WIP→FG ─────────────────────────────────────────────
def test_posting_error_message_reads_reason_and_detail():
    from routes.rahaza_posting import posting_error_message
    assert posting_error_message({"ok": False, "reason": "zero_wip_value", "detail": "Tidak ada MI"}) \
        == "Tidak ada MI (zero_wip_value)"
    assert posting_error_message({"ok": False, "error": "Periode tutup"}) == "Periode tutup"
    assert posting_error_message({"ok": False, "reason": "mapping_disabled"}) == "mapping_disabled"
    assert posting_error_message({}) == "Unknown posting error"


def test_wip_fg_receipt_zero_layer_saves_error_and_koreksi_suffix(monkeypatch):
    import routes.rahaza_posting as rp

    async def mapping(db, key):
        return {"debit_fg_inventory": "1-1404", "credit_wip": "1-1403"}

    async def none(*a, **k):
        return None
    made = []

    async def create(db, d, memo, mod, ref, lines, user):
        made.append((ref, lines))
        return {"ok": True, "je_id": "je-x", "je_number": "JE-X"}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)
    db = FakeDB(cmt_receipts=[{"id": "rc1", "receipt_code": "CMT-RCV-1"}],
                fg_cost_layers=[{"id": "L0", "total_cost": 0, "gl_je_id": None, "gaps": ["biaya jahit belum diisi"]},
                                {"id": "L2", "total_cost": 212792.2, "gl_je_id": None}])
    r0 = run(rp.post_wip_to_fg_on_cmt_receipt(db, {"id": "rc1"}, ["L0"], {}))
    assert r0["reason"] == "zero_layer_value"
    assert "biaya jahit belum diisi" in db.cmt_receipts.docs[0]["wip_fg_post_error"]
    r2 = run(rp.post_wip_to_fg_on_cmt_receipt(db, {"id": "rc1"}, ["L2"], {}, suffix="koreksi:L2"))
    assert r2["ok"] and made[-1][0] == "wip_fg_receipt:rc1:koreksi:L2"
    assert made[-1][1][0]["debit"] == pytest.approx(212792.2)
    assert db.cmt_receipts.docs[0]["wip_fg_extra_jes"][0]["je_number"] == "JE-X"


# ── Laporan Nilai Persediaan FG ──────────────────────────────────────────────
def test_fg_valuation_not_reconciled_when_uncosted():
    from routes.rahaza_fin_reports import fg_valuation_status
    st = fg_valuation_status(difference=0, unexplained=0, uncosted_qty=10)
    assert st["reconciled"] is False and st["explained"] is False and st["issues"]
    ok = fg_valuation_status(difference=0.4, unexplained=0.4, uncosted_qty=0)
    assert ok["reconciled"] is True and ok["explained"] is True and ok["issues"] == []
