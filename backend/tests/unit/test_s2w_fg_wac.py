"""Uji unit HERMETIK paket S2-W (2026-11-02) — keputusan owner No.26(a): WAC untuk barang jadi.

Angka harapan DIHITUNG TANGAN (lihat komentar di tiap uji):
  * contoh audit g.md No.26 §4: batch A 100 @50.000 + batch B 100 @60.000 → WAC 55.000;
    jual 120 → HPP 6.600.000 (FIFO lama 6.200.000), sisa 80 × 55.000 = 4.400.000.
  * skenario runtime paket: CRL bahan 91.396,10 + jahit 15.000 / 25.000
      R1 10 @106.396,10 = 1.063.961,00 ; R2 10 @116.396,10 = 1.163.961,00
      WAC = 2.227.922,00 / 20 = 111.396,10
      jual 6 → 668.376,60 (bahan 548.376,60 + upah 120.000) ; sisa 14 → 1.559.545,40
      retur diterima 2 @WAC → +222.792,20 ; 16 × 111.396,10 = 1.782.337,60
      retur dibuang 1 → Dr 6-1300 / Cr 5-1000 111.396,10 (stok & 1-1404 tidak berubah)
  * stok minus: −5 @50.000, masuk 20 @60.000 → WAC 60.000, selisih 5 × 10.000 = 50.000
    Dr 5-1950 / Cr 1-1404 ; GL −250.000 + 1.200.000 − 50.000 = 900.000 = 15 × 60.000.
"""
import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(os.path.dirname(BACKEND), "scripts"))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from p3_fakes import FakeDB  # noqa: E402
from core import fg_cost_layers as fcl  # noqa: E402
from core import catalog_margin as cm  # noqa: E402


def run(coro):
    return asyncio.run(coro)


MAP = {
    "cogs_shipment": {"debit_cogs_material": "5-1000", "debit_cogs_labor": "5-2000",
                      "debit_cogs_overhead": "5-3500", "credit_fg_inventory": "1-1404"},
    "inventory_adjust": {"inventory_rm": "1-1401", "adjustment_expense": "5-1950"},
    "return_damaged_loss": {"debit_return_loss": "6-1300", "credit_cogs": "5-1000"},
    "cogs_marketplace_return": {"debit_fg_inventory": "1-1404", "credit_cogs": "5-1000"},
}


@pytest.fixture
def posting(monkeypatch):
    """Mesin posting palsu: kumpulkan jurnal, hitung saldo per akun."""
    from routes import rahaza_posting as rp
    jes = []

    async def mapping(db, key):
        return dict(MAP.get(key, {}))

    async def none(*a, **k):
        return None

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2)
        jes.append({"source_module": mod, "source_ref": ref, "memo": memo, "lines": lines})
        return {"ok": True, "je_id": f"je-{len(jes)}", "je_number": f"JE-{len(jes)}"}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)

    def gl(code):
        return round(sum(ln["debit"] - ln["credit"] for je in jes for ln in je["lines"]
                         if ln["account_code"] == code), 2)
    return {"jes": jes, "gl": gl}


def _db(**extra):
    return FakeDB(
        rahaza_materials=[{"id": "FG1", "code": "DA-1101-CRL", "type": "fg", "hpp": 32175.0,
                           "hpp_source": "bom", "hpp_fifo_avg": 99999.0}],
        rahaza_material_stock=[{"id": "st1", "material_id": "FG1", "location_id": "LOC-FG", "qty": 0.0,
                                "inventory_category": "fg_internal", "ownership": "cv_da"},
                               {"id": "st2", "material_id": "FG1", "location_id": "LOC-Q", "qty": 4.0}],
        rahaza_locations=[{"id": "LOC-FG", "code": "ZNA-FG"},
                          {"id": "LOC-Q", "code": "ZNA-KARANTINA", "storage_role": "karantina"}],
        marketing_catalog_items=[{"id": "C1", "fg_material_id": "FG1", "hpp": 32175.0, "hpp_source": "bom",
                                  "harga_jual": 150000.0}],
        **extra)


def _stock(db, delta, loc="LOC-FG"):
    row = next(r for r in db.rahaza_material_stock.docs if r["location_id"] == loc)
    row["qty"] = round(row["qty"] + delta, 4)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Rumus murni
# ══════════════════════════════════════════════════════════════════════════════
def test_weighted_receipt_matches_audit_example_and_issue_value():
    r = fcl.wac_after_receipt(100, 50000, {"material": 50000}, 100, 60000, {"material": 60000})
    assert r["rule"] == "weighted" and r["unit_cost"] == 55000.0 and r["adjustment_fg"] == 0
    v = fcl.value_issue(120, r["unit_cost"], r["components"])
    assert v["cogs"] == 6_600_000.0 and v["uncosted_qty"] == 0          # FIFO lama: 6.200.000
    assert round(80 * r["unit_cost"], 2) == 4_400_000.0


def test_components_weighted_and_sum_to_wac():
    r1 = fcl.wac_after_receipt(0, 0, None, 10, 106396.10, {"material_cost": 91396.10, "sewing_cost": 15000})
    assert r1["rule"] == "reset_empty" and r1["components"] == {"material": 91396.10, "labor": 15000.0, "overhead": 0.0}
    r2 = fcl.wac_after_receipt(10, r1["unit_cost"], r1["components"], 10, 116396.10,
                               {"material_cost": 91396.10, "sewing_cost": 25000})
    assert r2["unit_cost"] == 111396.10
    assert r2["components"] == {"material": 91396.10, "labor": 20000.0, "overhead": 0.0}
    v = fcl.value_issue(6, r2["unit_cost"], r2["components"])
    assert v["cogs"] == 668376.60 and v["components"] == {"material": 548376.60, "labor": 120000.0, "overhead": 0.0}


def test_zero_cost_receipt_does_not_dilute_wac():
    r = fcl.wac_after_receipt(10, 50000, {"material": 50000}, 10, 0)
    assert r["rule"] == "keep_zero_cost" and r["unit_cost"] == 50000.0 and r["adjustment_fg"] == 0


def test_negative_stock_resets_wac_and_books_difference():
    r = fcl.wac_after_receipt(-5, 50000, {"material": 50000}, 20, 60000)
    assert r["rule"] == "reset_negative" and r["unit_cost"] == 60000.0
    assert r["adjustment_fg"] == -50000.0                      # Cr 1-1404 / Dr 5-1950
    gl = -5 * 50000 + 20 * 60000 + r["adjustment_fg"]          # sebelum + penerimaan + selisih
    assert gl == 15 * r["unit_cost"] == 900000
    # biaya masuk lebih murah → selisih kebalikannya (Dr 1-1404 / Cr 5-1950)
    assert fcl.wac_after_receipt(-5, 50000, None, 20, 45000)["adjustment_fg"] == 25000.0
    # stok minus tanpa WAC lama (keluar tanpa biaya): seluruh biaya pcs minus → 5-1950
    assert fcl.wac_after_receipt(-3, 0, None, 10, 40000)["adjustment_fg"] == -120000.0
    # qty lama 0 → WAC = biaya masuk, tanpa selisih
    z = fcl.wac_after_receipt(0, 50000, None, 5, 70000)
    assert z["rule"] == "reset_empty" and z["unit_cost"] == 70000 and z["adjustment_fg"] == 0


def test_issue_without_wac_is_uncosted_not_guessed():
    assert fcl.value_issue(4, 0, None) == {"cogs": 0.0, "components": fcl._zero_comps(), "uncosted_qty": 4}


def test_split_issue_entries_sum_and_trail():
    val = fcl.value_issue(7, 111396.10, {"material": 91396.10, "labor": 20000})
    rows = fcl.split_issue_entries(7, 111396.10, val, [{"layer_id": "L1", "qty": 3, "batch_unit_cost": 106396.10},
                                                       {"layer_id": "L2", "qty": 2, "batch_unit_cost": 116396.10}])
    assert [r["layer_id"] for r in rows] == ["L1", "L2", ""]     # 2 pcs tanpa lapisan tetap bernilai WAC
    assert round(sum(r["total"] for r in rows), 2) == val["cogs"] == 779772.70
    for k in fcl.COMP_KEYS:
        assert round(sum(r["components"][k] for r in rows), 2) == val["components"][k]
    assert all(r["basis"] == "wac" and r["unit_cost"] == 111396.10 for r in rows)


def test_initial_wac_from_layers_reports_zero_cost_layers():
    ini = fcl.initial_wac_from_layers([
        {"qty_remaining": 6, "unit_cost": 50000, "breakdown": {"material_cost": 40000, "sewing_cost": 10000}},
        {"qty_remaining": 4, "unit_cost": 0},
        {"qty_remaining": 0, "unit_cost": 90000}])
    # (6 × 50.000 + 4 × 0) / 10 = 30.000 — sama dengan nilai lapisan di GL
    assert ini["unit_cost"] == 30000.0 and ini["value"] == 300000.0 and ini["qty"] == 10
    assert ini["components"] == {"material": 24000.0, "labor": 6000.0, "overhead": 0.0}
    assert ini["zero_cost_layers"] == 1 and ini["zero_cost_qty"] == 4


def test_reversal_removes_receipt_at_original_cost():
    # 10 @100 + 10 @120 → WAC 110 ; batalkan 10 @120 (stok sisa 10) → WAC 100
    r = fcl.wac_after_reversal(10, 110, None, 10, 120)
    assert r["unit_cost"] == 100.0 and r["adjustment_fg"] == 0
    # stok sudah habis: sisa nilai (10 × 110 − 10 × 120 = −100) → selisih ke 5-1950
    e = fcl.wac_after_reversal(0, 110, None, 10, 120)
    assert e["unit_cost"] == 110 and e["adjustment_fg"] == 100.0


def test_valued_rows_exclude_quarantine_and_client_goods():
    rows = [{"location_id": "A", "qty": 5, "ownership": "cv_da"}, {"location_id": "Q", "qty": 3},
            {"location_id": "A2", "qty": 2, "ownership": "maklon_client"}, {"location_id": "B", "qty": -1}]
    assert fcl.valued_qty(rows, {"Q"}) == 4.0


# ══════════════════════════════════════════════════════════════════════════════
# 2. Skenario penuh (FakeDB): 2 penerimaan → jual → retur diterima → retur dibuang
# ══════════════════════════════════════════════════════════════════════════════
def test_full_scenario_value_equals_gl(posting):
    from core import returns_bridge as rb
    from routes.rahaza_fin_reports import fg_valuation_row
    from routes.rahaza_posting import _fifo_rows_to_components
    db = _db()
    gl_fg = 0.0
    for qty, sew in ((10, 15000), (10, 25000)):
        _stock(db, qty)
        cost = round(91396.10 + sew, 2)
        ly = run(fcl.push_layer(db, material_id="FG1", qty=qty, unit_cost=cost, ref={"type": "cmt_receipt"},
                                breakdown={"material_cost": 91396.10, "sewing_cost": sew}))
        gl_fg += ly["total_cost"]                                    # JE WIP→FG = Σ lapisan
    mat = run(db.rahaza_materials.find_one({"id": "FG1"}))
    assert mat["unit_cost"] == 111396.10 and mat["wac_components"]["labor"] == 20000.0
    assert mat["hpp"] == 32175.0 and "hpp_fifo_avg" not in mat           # hpp = estimasi, tidak ditimpa
    assert run(db.marketing_catalog_items.find_one({"id": "C1"}))["hpp"] == 111396.10
    # karantina 4 pcs TIDAK ikut qty lama: (10 × 106.396,10 + 10 × 116.396,10) / 20
    _stock(db, -6)
    out = run(fcl.consume_fifo(db, material_id="FG1", qty=6, ref={"type": "direct_sale"}))
    assert out["cogs"] == 668376.60 and out["uncosted_qty"] == 0
    comp = run(_fifo_rows_to_components(db, [{"sku": "X", "qty_shipped": 6, "fg_cogs": out["cogs"],
                                              "fg_cogs_layers": out["layers_used"]}]))
    assert (comp["material"], comp["labor"], comp["total"], comp["basis"]) == (548376.60, 120000.0, 668376.60, "wac")
    gl_fg -= comp["total"]
    lys = sorted(db.fg_cost_layers.docs, key=lambda d: d["created_at"])
    assert [ly["qty_remaining"] for ly in lys] == [4, 10]                # jejak FIFO tetap berjalan
    # retur diterima 2 pcs (keputusan gudang) → WAC saat keputusan
    _stock(db, 2)
    v = run(rb._value_restock(db, {"id": "W1", "return_code": "RET-1"}, "FG1", 2, {"name": "gudang"}))
    assert v["hpp_unit_cost"] == 111396.10 and v["cogs_post_error"] is None
    assert posting["jes"][-1]["lines"][0] == {"account_code": "1-1404", "debit": 222792.20, "credit": 0,
                                               "description": "Retur RET-1 FG kembali (2 × 111396)"}
    # retur DIBUANG 1 pcs (K40): Dr 6-1300 / Cr 5-1000, stok & 1-1404 tidak berubah
    d = run(rb._value_damaged(db, {"id": "W2", "return_code": "RET-2"}, "FG1", 1, {"name": "gudang"},
                              disposed=True))
    je = posting["jes"][-1]
    assert d["loss_amount"] == 111396.10 and d["loss_kind"] == "disposed"
    assert je["source_ref"] == "whret_disposed:W2" and "dibuang" in je["memo"]
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in je["lines"]] == [
        ("6-1300", 111396.10, 0), ("5-1000", 0, 111396.10)]
    mat = run(db.rahaza_materials.find_one({"id": "FG1"}))
    assert mat["unit_cost"] == 111396.10
    row = fg_valuation_row(qty=16, wac=mat["unit_cost"], layers=db.fg_cost_layers.docs, wac_initialized=True)
    # GL 1-1404 = WIP→FG (Σ lapisan) − HPP jual + jurnal restock (dari mesin posting)
    assert row["value"] == 1782337.60 == round(gl_fg + posting["gl"]("1-1404"), 2)


def test_negative_stock_receipt_posts_5_1950(posting):
    db = _db()
    _stock(db, 10)
    run(fcl.push_layer(db, material_id="FG1", qty=10, unit_cost=50000.0, ref={"type": "cmt_receipt"}))
    _stock(db, -15)                                                      # Stok Boleh Minus ON → −5
    out = run(fcl.consume_fifo(db, material_id="FG1", qty=15))
    assert out["cogs"] == 750000.0                                       # 15 × 50.000 (5 pcs saat minus)
    _stock(db, 20)
    ly = run(fcl.push_layer(db, material_id="FG1", qty=20, unit_cost=60000.0, ref={"type": "cmt_receipt"}))
    assert ly["wac"]["rule"] == "reset_negative" and ly["wac"]["unit_cost"] == 60000.0
    je = posting["jes"][-1]
    assert je["source_module"] == "fg_wac_adjust" and je["source_ref"] == f"fg_wac_adj:{ly['id']}"
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in je["lines"]] == [
        ("5-1950", 50000.0, 0), ("1-1404", 0, 50000.0)]
    gl = 10 * 50000 - out["cogs"] + 20 * 60000 + posting["gl"]("1-1404")
    assert gl == 15 * 60000 == 900000


def test_lazy_init_from_layers_and_legacy_unit_cost():
    db = _db(fg_cost_layers=[{"id": "L1", "material_id": "FG1", "qty_remaining": 6, "unit_cost": 50000,
                              "breakdown": {"material_cost": 50000}, "created_at": 1},
                             {"id": "L2", "material_id": "FG1", "qty_remaining": 4, "unit_cost": 0, "created_at": 2}])
    st = run(fcl.wac_state(db, "FG1"))
    assert st["unit_cost"] == 30000.0 and st["source"] == "init_from_layers" and st["initialized"]
    mat = run(db.rahaza_materials.find_one({"id": "FG1"}))
    assert mat["unit_cost"] == 30000.0 and mat["wac_source"] == "init_from_layers"
    assert db.rahaza_material_cost_history.docs[-1]["new_unit_cost"] == 30000.0
    db2 = FakeDB(rahaza_materials=[{"id": "FG2", "type": "fg", "unit_cost": 45000.0},
                                   {"id": "FG3", "type": "fg", "hpp": 32175.0}])
    assert run(fcl.wac_state(db2, "FG2"))["source"] == "legacy_unit_cost"
    # tanpa lapisan & tanpa biaya: tidak menulis unit_cost 0 (penerimaan pertama yang menulis)
    assert run(fcl.wac_state(db2, "FG3"))["source"] == "none"
    assert "unit_cost" not in db2.rahaza_materials.docs[1] and "wac_components" not in db2.rahaza_materials.docs[1]


def test_reverse_receipt_restores_previous_wac(posting):
    db = _db()
    _stock(db, 10)
    run(fcl.push_layer(db, material_id="FG1", qty=10, unit_cost=100.0))
    _stock(db, 10)
    run(fcl.push_layer(db, material_id="FG1", qty=10, unit_cost=120.0))
    assert run(fcl.wac_state(db, "FG1"))["unit_cost"] == 110.0
    _stock(db, -10)                                                      # pemanggil sudah keluarkan stok
    r = run(fcl.reverse_receipt(db, material_id="FG1", qty=10, unit_cost=120.0, ref={"id": "W9"}))
    assert r["unit_cost"] == 100.0 and r["adjustment_je"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. Jurnal & jalur
# ══════════════════════════════════════════════════════════════════════════════
def test_components_function_legacy_fifo_rows_and_mixed():
    from routes.rahaza_posting import _fifo_rows_to_components
    db = FakeDB(fg_cost_layers=[{"id": "OLD", "breakdown": {"material_cost": 30000, "sewing_cost": 10000}}])
    legacy = {"sku": "A", "qty_shipped": 2, "fg_cogs": 80000,
              "fg_cogs_layers": [{"layer_id": "OLD", "qty": 2, "unit_cost": 40000, "total": 80000}]}
    r = run(_fifo_rows_to_components(db, [legacy]))
    assert (r["material"], r["labor"], r["basis"]) == (60000.0, 20000.0, "fifo_batch")
    wac = {"sku": "B", "qty_shipped": 1, "fg_cogs": 100.0, "fg_cogs_layers": [
        {"layer_id": "L9", "qty": 1, "total": 100.0, "basis": "wac",
         "components": {"material": 70.0, "labor": 30.0, "overhead": 0.0}}]}
    m = run(_fifo_rows_to_components(db, [legacy, wac]))
    assert m["basis"] == "mixed" and m["total"] == 80100.0 and m["labor"] == 20030.0


def test_sales_return_damaged_goes_to_loss_not_fg():
    from routes.sales_direct import return_cogs_lines
    items = [{"cogs": 222792.20, "condition": "good"}, {"cogs": 111396.10, "condition": "damaged"}]
    lines = return_cogs_lines("RT-1", items, {"5-1000": 0.8, "5-2000": 0.2}, "1-1404", "6-1300")
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in lines] == [
        ("1-1404", 222792.20, 0), ("6-1300", 111396.10, 0),
        ("5-1000", 0, 267350.64), ("5-2000", 0, 66837.66)]
    old = return_cogs_lines("RT-1", items, {"5-1000": 1.0}, "1-1404", None)   # tanpa profil kerugian
    assert old[0] == {"account_code": "1-1404", "debit": 334188.30, "credit": 0, "description": "Retur RT-1 FG kembali"}


def test_fg_issue_journal_by_reason_and_unmapped_reason_is_refused(posting):
    from routes.rahaza_posting import post_fg_issue_cogs
    db = _db()
    _stock(db, 10)
    run(fcl.push_layer(db, material_id="FG1", qty=10, unit_cost=50000.0, breakdown={"material_cost": 50000}))
    _stock(db, -2)
    res = run(post_fg_issue_cogs(db, {"id": "I1", "issue_number": "FGI-1", "material_id": "FG1", "qty": 2,
                                      "reason": "retur", "reason_label": "Retur / Rusak"}, {"name": "u"}))
    assert res["ok"] and res["cogs"] == 100000.0 and res["debit_mapping"] == "return_damaged_loss.debit_return_loss"
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in posting["jes"][-1]["lines"]] == [
        ("6-1300", 100000.0, 0), ("1-1404", 0, 100000.0)]
    before = [ly["qty_remaining"] for ly in db.fg_cost_layers.docs]
    s = run(post_fg_issue_cogs(db, {"id": "I2", "material_id": "FG1", "qty": 1, "reason": "sample"}, {}))
    assert not s["ok"] and s["reason"] == "mapping_missing" and "fg_issue.debit_sample" in s["error"]
    assert [ly["qty_remaining"] for ly in db.fg_cost_layers.docs] == before     # tidak dinilai/dimakan
    k = run(post_fg_issue_cogs(db, {"id": "I3", "material_id": "FG1", "qty": 1, "reason": "koreksi_stok"}, {}))
    assert k["ok"] and posting["jes"][-1]["lines"][0]["account_code"] == "5-1950"


def test_damaged_restock_uses_wac_and_old_key(posting):
    from core import returns_bridge as rb
    db = _db()
    _stock(db, 10)
    run(fcl.push_layer(db, material_id="FG1", qty=10, unit_cost=55997.25))
    d = run(rb._value_damaged(db, {"id": "W5", "return_code": "RET-5"}, "FG1", 2, {}))
    assert d["loss_amount"] == 111994.50 and d["loss_kind"] == "damaged"
    assert posting["jes"][-1]["source_ref"] == "whret_damaged:W5"


# ══════════════════════════════════════════════════════════════════════════════
# 4. HPP master vs aktual (katalog/margin) & laporan
# ══════════════════════════════════════════════════════════════════════════════
def test_catalog_shows_wac_else_labelled_estimate_and_apply_cannot_override():
    est = cm.effective_fg_cost({"hpp": 32175.0, "hpp_source": "bom", "unit_cost": 0})
    assert est == {"hpp": 32175.0, "source": "fg_estimasi", "is_estimate": True,
                   "label": "estimasi (kalkulator HPP)", "estimate_from": "bom"}
    # `unit_cost` lama tanpa penilaian WAC bukan biaya nyata
    assert cm.effective_fg_cost({"unit_cost": 5.0})["source"] == ""
    # "Terapkan HPP per Potong" menulis `hpp` → WAC (`unit_cost`) tetap yang dipakai
    after_apply = {"hpp": 47175.0, "hpp_source": "bom", "unit_cost": 111396.10,
                   "wac_components": {"material": 91396.10, "labor": 20000.0, "overhead": 0.0}}
    w = cm.effective_fg_cost(after_apply)
    assert (w["hpp"], w["source"], w["is_estimate"]) == (111396.10, "fg_wac", False)
    row = cm.decorate({"harga_jual": 150000.0, "fg_material_id": "FG1"}, w)
    assert row["hpp_source_label"] == "WAC aktual" and row["hpp_is_estimate"] is False
    assert row["margin"] == 38603.90
    e = cm.decorate({"harga_jual": 150000.0, "fg_material_id": "FG1"}, est)
    assert e["hpp_is_estimate"] is True and e["hpp_source_label"] == "estimasi (kalkulator HPP)"


def test_valuation_row_and_status():
    from routes.rahaza_fin_reports import fg_valuation_row, fg_valuation_status
    layers = [{"qty_remaining": 4, "unit_cost": 106396.10, "total_cost": 1063961.0, "gl_je_id": "je1"},
              {"qty_remaining": 10, "unit_cost": 116396.10, "total_cost": 1163961.0, "gl_je_id": None},
              {"qty_remaining": 2, "unit_cost": 0, "total_cost": 0, "gl_je_id": None}]
    r = fg_valuation_row(qty=16, wac=111396.10, layers=layers, wac_initialized=True)
    assert r["value"] == r["layer_value"] == 1782337.60 and r["avg_unit_cost"] == 111396.10
    assert r["unposted_value"] == 1163961.0 and r["unposted_layers"] == 1
    assert r["uncosted_qty"] == 2 and r["layer_qty"] == 16 and r["qty_diff"] == 0
    assert fg_valuation_row(qty=5, wac=0, layers=[], wac_initialized=False)["uncosted_qty"] == 5
    st = fg_valuation_status(difference=0.0, unexplained=0.0, uncosted_qty=0)
    assert st["reconciled"] and st["explained"]
    bad = fg_valuation_status(difference=500.0, unexplained=500.0, uncosted_qty=0)
    assert not bad["reconciled"] and "Σ stok × WAC" in bad["issues"][0]


def test_compute_fg_valuation_reconciles_with_gl(monkeypatch):
    from routes import rahaza_fin_reports as fr
    db = _db()
    db.rahaza_materials.docs[0].update({"unit_cost": 111396.10, "wac_components": {"material": 111396.10}})
    db.rahaza_material_stock.docs[0]["qty"] = 16.0

    class _Agg:
        def __init__(self, rows):
            self.rows = rows

        async def to_list(self, n=None):
            return self.rows
    db.rahaza_material_stock.aggregate = lambda pipe: _Agg([{"_id": "FG1"}])

    async def gl(db_, match):
        return {"1-1404": {"debit": 2449906.60, "credit": 667569.0}}         # saldo 1.782.337,60
    monkeypatch.setattr(fr, "_aggregate_by_account", gl)
    rep = run(fr.compute_fg_valuation(db, "2026-11-02"))
    t = rep["totals"]
    assert rep["basis"] == "wac" and t["value"] == t["gl_balance"] == 1782337.60
    assert rep["reconciled"] is True and t["difference"] == 0
    row = rep["rows"][0]
    assert row["stock_qty"] == 16 and row["physical_qty"] == 20              # karantina 4 tidak bernilai


def test_migration_plan_flags():
    from migrate_fg_wac_init import plan_for
    p = plan_for({"id": "FG1", "code": "X"}, [{"qty_remaining": 6, "unit_cost": 50000},
                                              {"qty_remaining": 4, "unit_cost": 0}], 12)
    assert p["wac_initial"] == 30000.0 and p["value_at_wac"] == 360000.0
    assert p["flags"] == ["lapisan_rp0_perlu_backfill", "stok_beda_dengan_lapisan"]
    q = plan_for({"id": "FG2", "code": "Y"}, [], 3)
    assert q["wac_initial"] == 0 and "stok_tanpa_biaya" in q["flags"]


def test_wiring_sources():
    """Pemanggil di berkas paket lain tetap memakai nama lama → kini WAC."""
    assert fcl.consume_fifo is fcl.issue_wac
    src = open(os.path.join(BACKEND, "routes", "sales_direct.py"), encoding="utf-8").read()
    body = src[src.index("async def _post_cogs"):src.index("@router.post(\"/direct-sales/{sid}/confirm\")")]
    assert "HPP master Rp" not in body and "rahaza_materials.find_one" not in body   # cadangan perkiraan dicabut
