"""Uji unit HERMETIK Tahap 2 — paket HPP (6 Nov 2026).

Aturan owner: HPP = bahan (master `unit_cost`) + aksesoris milik DA + upah CMT + permak; upah
internal & overhead pabrik TIDAK masuk HPP; margin = (harga jual − HPP) ÷ harga jual di mana pun.
Angka harapan dihitung tangan di komentar tiap uji.
"""
import asyncio
import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from p3_fakes import FakeDB  # noqa: E402
from core import bom_uom  # noqa: E402
from core import catalog_margin as cm  # noqa: E402
from core import fg_cost_layers as fcl  # noqa: E402
from core import margin as mg  # noqa: E402
from core import po_wip  # noqa: E402
from core import product_costing as pc  # noqa: E402
from core import product_master as pm  # noqa: E402


def run(coro):
    return asyncio.run(coro)


U = {"id": "u1", "name": "Uji", "role": "admin"}


@pytest.fixture(autouse=True)
def _plain_uom(monkeypatch):
    async def ensure_uom(db, bom):
        return list(bom.get("materials") or []), []
    monkeypatch.setattr(bom_uom, "ensure_uom", ensure_uom)


@pytest.fixture
def posting(monkeypatch):
    """Mesin posting palsu: kumpulkan jurnal; peta akun bawaan profil."""
    from routes import rahaza_posting as rp
    from routes import rahaza_posting_profiles as pp
    jes = []
    maps = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}

    async def mapping(db, key):
        return dict(maps.get(key, {}))

    async def none(*a, **k):
        return None

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2)
        jes.append({"source_module": mod, "source_ref": ref, "memo": memo, "lines": lines})
        return {"ok": True, "je_id": f"je-{len(jes)}", "je_number": f"JE-{len(jes)}"}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(pp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)
    return jes


# ══════════════════════════════════════════════════════════════════════════════
# 3. SATU rumus margin
# ══════════════════════════════════════════════════════════════════════════════
def test_margin_helper_atas_harga_jual():
    # harga 100.000, HPP 70.000 → margin 30% (bukan markup 42,86%)
    assert mg.margin_pct(100000, 70000) == 30.0
    assert mg.margin_pct(0, 70000) is None and mg.margin_pct(100000, 0) is None
    # target 30% → 70.000 ÷ 0,7 = 100.000
    assert mg.price_for_margin(70000, 30) == 100000.0
    assert pc.suggested_price(70000, 30) == 100000.0
    assert pc.margin_of(100000, 70000)["margin_pct"] == 30.0
    row = cm.decorate({"harga_jual": 100000.0, "fg_material_id": "F"}, {"hpp": 70000.0, "source": cm.SRC_WAC})
    assert row["margin_pct"] == 30.0 and row["margin"] == 30000.0


# ══════════════════════════════════════════════════════════════════════════════
# 2 + 3. Kalkulator R&D: overhead bawaan 0, cutting & overhead di luar HPP
# ══════════════════════════════════════════════════════════════════════════════
def test_rnd_calculator_tanpa_overhead_dan_cutting():
    from routes.dewi_rnd_hpp import _calculate_hpp, rnd_hpp_owner_rule
    # bahan 50.000 + CMT 15.000 + kemasan 2.000 = 67.000; cutting 3.000 & overhead 10% = info
    c = _calculate_hpp({"cmt_cost_per_pcs": 15000, "cutting_cost_per_pcs": 3000,
                        "packaging_cost_per_pcs": 2000, "overhead_pct": 10, "margin_pct": 33},
                       cost_lines_total=50000)
    assert c["hpp_total"] == 67000.0 and c["direct_cost"] == 67000.0
    assert c["excluded_from_hpp"] == {"cutting_cost": 3000.0, "overhead_value": 7000.0}
    assert c["selling_price_proposal"] == mg.price_for_margin(67000, 33)
    assert _calculate_hpp({}, cost_lines_total=10)["overhead_pct"] == 0          # bawaan 0
    # dokumen LAMA (hpp_total memuat cutting + 10%): promosi memakai aturan owner
    old = {"hpp_total": 77000, "material_cost": 50000, "cmt_cost": 15000, "packaging_cost": 2000,
           "cutting_cost": 3000, "overhead_pct": 10}
    assert rnd_hpp_owner_rule(old) == 67000.0
    assert rnd_hpp_owner_rule({**c}) == 67000.0


def test_rnd_save_tidak_menimpa_model_fg_katalog(monkeypatch):
    import routes.dewi_rnd_hpp as rh
    db = FakeDB(rahaza_models=[{"id": "M", "rnd_style_id": "ST", "hpp": 1000, "hpp_bom": 1000}],
                rahaza_materials=[{"id": "F", "type": "fg", "model_id": "M", "hpp": 1200, "hpp_source": "bom"}],
                marketing_catalog_items=[{"id": "C", "fg_material_id": "F", "hpp": 1200, "hpp_source": "bom"}])
    monkeypatch.setattr(rh, "get_db", lambda: db)
    out = run(rh.create_hpp({"style_id": "ST", "status": "draft", "cmt_cost_per_pcs": 999,
                             "fabric_usage_per_pcs": 1, "fabric_price_per_meter": 99999}, user=U))
    assert out["_propagation"]["models"] == 0 and "dokumen R&D" in out["_propagation"]["note"]
    assert db.rahaza_models.docs[0]["hpp"] == 1000
    assert db.rahaza_materials.docs[0]["hpp"] == 1200
    assert db.marketing_catalog_items.docs[0]["hpp"] == 1200
    assert len(db.dewi_rnd_hpp.docs) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 11. BOM R&D: harga master menang untuk baris tertaut
# ══════════════════════════════════════════════════════════════════════════════
def test_rnd_bom_harga_master_menang(monkeypatch):
    import routes.dewi_rnd_hpp as rh
    master = {"id": "K", "code": "KAIN", "name": "Kain", "unit": "kg", "unit_cost": 80000.0}

    async def resolve_master(db, line):
        return master if line.get("material_id") == "K" else None

    async def resolve_rnd(db, line):
        return None
    monkeypatch.setattr(rh, "resolve_master_material", resolve_master)
    monkeypatch.setattr(rh, "resolve_rnd_material", resolve_rnd)
    linked = run(rh._cost_one_line(None, {"material_id": "K", "qty": 0.5, "unit": "kg", "unit_cost": 50000}))
    assert linked["unit_cost"] == 80000.0 and linked["line_cost"] == 40000.0        # 0,5 × 80.000
    assert linked["cost_source"] == "rahaza_materials.unit_cost" and linked["typed_price_ignored"] is True
    free = run(rh._cost_one_line(None, {"material_name": "Renda khusus", "qty": 2, "unit": "pcs",
                                        "unit_cost": 1500}))
    assert free["line_cost"] == 3000.0 and free["cost_source"] == "bom_line_unlinked"
    assert "belum tertaut" in free["cost_source_label"]


# ══════════════════════════════════════════════════════════════════════════════
# 7. Promosi style → master membawa HPP & harga R&D
# ══════════════════════════════════════════════════════════════════════════════
def test_promosi_style_membawa_hpp_dan_harga(monkeypatch):
    import routes.dewi_rnd_styles as rs
    db = FakeDB(
        dewi_rnd_styles=[{"id": "ST", "style_code": "VST-9", "style_name": "Vest Uji",
                          "status": "approved_for_launch", "category": "vest"}],
        dewi_rnd_hpp=[
            {"id": "h-old", "style_id": "ST", "status": "approved", "hpp_total": 77000, "material_cost": 50000,
             "cmt_cost": 15000, "packaging_cost": 2000, "selling_price_proposal": 110000,
             "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc)},
            {"id": "h-draft", "style_id": "ST", "status": "draft", "hpp_total": 5, "created_at":
             datetime(2026, 11, 1, tzinfo=timezone.utc)}])
    monkeypatch.setattr(rs, "get_db", lambda: db)

    async def no_variants(*a, **k):
        return {"created_count": 0}
    monkeypatch.setattr(rs, "promote_rnd_variants_to_master", no_variants)
    run(rs.promote_style_to_production("ST", {}, user=U))
    m = db.rahaza_models.docs[0]
    # dokumen disetujui menang atas draf terbaru; HPP = 50.000 + 15.000 + 2.000 (tanpa overhead lama)
    assert m["hpp_rnd"] == 67000.0 and m["hpp"] == 67000.0 and m["hpp_source"] == "rnd"
    assert m["retail_price"] == 110000


# ══════════════════════════════════════════════════════════════════════════════
# 1. Suntingan master tidak menimpa HPP per warna; satu urutan HPP katalog
# ══════════════════════════════════════════════════════════════════════════════
def test_master_edit_tidak_menimpa_hpp_fg_dan_katalog():
    db = FakeDB(rahaza_materials=[
        {"id": "F-CRL", "type": "fg", "model_id": "M", "hpp": 91396.10, "hpp_source": "bom"},
        {"id": "F-NEW", "type": "fg", "model_id": "M", "hpp": 0}],
        marketing_catalog_items=[{"id": "C1", "fg_material_id": "F-CRL", "hpp": 111396.10, "hpp_source": "wac"},
                                 {"id": "C2", "fg_material_id": "F-NEW"}])
    model = {"id": "M", "hpp_bom": 60000.0, "category_name": "Vest", "weight_gram": 250}
    run(pm.propagate_master_changes(db, model))
    fg = {d["id"]: d for d in db.rahaza_materials.docs}
    assert fg["F-CRL"]["hpp"] == 91396.10 and fg["F-CRL"]["weight_gram"] == 250      # berat tetap turun
    assert fg["F-NEW"]["hpp"] == 60000.0                                              # kosong → diisi
    items = {d["id"]: d for d in db.marketing_catalog_items.docs}
    assert items["C1"]["hpp"] == 111396.10 and items["C2"]["hpp"] == 60000.0


def test_ensure_fg_material_tidak_menimpa_hpp_fg():
    from utils.variant_ssot import ensure_fg_material
    db = FakeDB(rahaza_models=[{"id": "M", "code": "VST-1", "hpp_bom": 60000.0}],
                rahaza_materials=[{"id": "F", "type": "fg", "code": "VST-1-CRL-M", "hpp": 91396.10,
                                   "hpp_source": "bom"}])
    run(ensure_fg_material(db, {"sku": "VST-1-CRL-M", "model_id": "M", "id": "V1"}))
    assert db.rahaza_materials.docs[0]["hpp"] == 91396.10


def test_urutan_hpp_katalog_satu_untuk_tambah_dan_segarkan():
    model = {"id": "M", "hpp_bom": 60000.0}
    wac = {"id": "F", "unit_cost": 111396.10, "wac_components": {"material": 111396.10}, "hpp": 91396.10,
           "hpp_source": "bom"}
    assert cm.resolve_catalog_hpp(wac, model) == (111396.10, "wac")
    assert cm.resolve_catalog_hpp({"id": "F", "hpp": 91396.10, "hpp_source": "bom"}, model) == (91396.10, "bom")
    assert cm.resolve_catalog_hpp({"id": "F", "hpp": 0}, model) == (60000.0, "bom")
    assert cm.resolve_catalog_hpp({"id": "F"}, None) == (0.0, "none")
    from routes import marketing_catalog_items as mci
    db = FakeDB(rahaza_models=[model], rahaza_materials=[{**wac, "model_id": "M"}])
    hpp, src, origin = run(mci._resolve_rnd_hpp(db, {"fg_material_id": "F"}))
    assert (hpp, src, origin) == (111396.10, "wac", "rahaza_materials")


# ══════════════════════════════════════════════════════════════════════════════
# 2. HPP per potong & lapisan FG tanpa upah internal / overhead
# ══════════════════════════════════════════════════════════════════════════════
def _costing_db(**extra):
    return FakeDB(
        rahaza_models=[{"id": "M", "code": "VST-1", "name": "Vest"}],
        rahaza_boms=[{"id": "B", "model_id": "M", "size_id": "S", "active": True, "is_active": True, "version": 1,
                      "materials": [{"material_id": "K", "code": "KAIN", "name": "Kain", "qty": 0.5, "qty_base": 0.5,
                                     "unit": "kg", "unit_base": "kg", "uom_status": "base"}]}],
        rahaza_materials=[{"id": "K", "code": "KAIN", "type": "fabric", "unit": "kg", "unit_cost": 80000.0,
                           "cost_method": "moving_average"}],
        rahaza_costing_settings=[{"id": "GLOBAL", "overhead_rate_per_pcs": 5000,
                                  "include_overhead_in_product_hpp": True,
                                  "process_rates": [{"process_id": "p", "code": "CUT", "rate_per_pcs": 2500}]}],
        rahaza_model_costing=[{"model_id": "M", "cmt_rate_per_pcs": 15000}],
        **extra)


def test_hpp_per_potong_bahan_plus_cmt_saja():
    db = _costing_db()
    d = run(pc.compute_model_cost(db, "M", with_candidates=False))
    s = d["sizes"][0]
    # 0,5 kg × 80.000 = 40.000 + CMT 15.000 = 55.000 (upah cutting 2.500 & overhead 5.000 di luar)
    assert s["hpp_unit"] == 55000.0 and s["overhead_cost"] == 0
    assert s["internal_labor_cost"] == 2500.0 and s["internal_labor_in_hpp"] is False
    assert d["internal_labor"]["label"] == "tidak masuk HPP" and d["overhead"]["included"] is False
    assert s["confidence"] == "full"
    assert not any(g["code"] == "internal_labor_missing" for g in d["gaps"])


def test_lapisan_fg_tanpa_upah_internal_dan_overhead():
    db = _costing_db(rahaza_wip_events=[{"model_id": "M", "event_type": "complete", "process_code": "CUT",
                                         "qty_done": 10, "rate_per_pcs": 3000}])
    out = run(fcl.compute_batch_unit_cost(db, po_item={"model_id": "M", "size_id": "S",
                                                       "cmt_price_snapshot": 15000}, qty=10))
    assert out["internal_labor_cost"] == 0 and out["overhead_cost"] == 0
    assert out["unit_cost"] == 55000.0                       # 40.000 bahan + 15.000 jahit


# ══════════════════════════════════════════════════════════════════════════════
# 4. Upah CMT HPP per potong: model_id saja, tanpa SPK batal/maklon, ditimbang qty, terbaru
# ══════════════════════════════════════════════════════════════════════════════
def test_pilih_tarif_cmt_spk():
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    recent, old = now - timedelta(days=10), now - timedelta(days=400)
    pos = {"A": {"status": "Closed", "business_type": "internal"},
           "B": {"status": "Cancelled", "business_type": "internal"},
           "C": {"status": "Confirmed", "business_type": "maklon"},
           "D": {"status": "In Production", "business_type": "internal"},
           "E": {"status": "Closed", "business_type": "internal"}}
    rows = [{"po_id": "A", "cmt_price_snapshot": 10000, "qty": 100, "created_at": recent},
            {"po_id": "D", "cmt_price_snapshot": 13000, "qty": 50, "created_at": recent},
            {"po_id": "B", "cmt_price_snapshot": 99000, "qty": 500, "created_at": recent},
            {"po_id": "C", "cmt_price_snapshot": 50000, "qty": 500, "created_at": recent},
            {"po_id": "E", "cmt_price_snapshot": 1000, "qty": 900, "created_at": old},
            {"po_id": "X", "cmt_price_snapshot": 1, "qty": 1, "created_at": recent}]
    p = pc.pick_cmt_rate_rows(rows, pos, now=now)
    # (10.000 × 100 + 13.000 × 50) / 150 = 11.000 — SPK lama (E) di luar jendela 180 hari
    assert p["rate"] == 11000.0 and p["qty"] == 150
    assert p["excluded"] == {"cancelled": 1, "other_business_type": 1, "po_missing": 1}
    # tanpa SPK dalam jendela → baris terbaru dipakai
    q = pc.pick_cmt_rate_rows([rows[4]], pos, now=now)
    assert q["rate"] == 1000.0 and "terbaru" in q["basis"]


def test_tarif_cmt_tidak_lagi_cocok_nama():
    db = FakeDB(po_items=[{"po_id": "P1", "product_name": "Vest", "model_id": "LAIN", "cmt_price_snapshot": 99999,
                           "qty": 10, "created_at": datetime.now(timezone.utc)}],
                production_pos=[{"id": "P1", "status": "Closed", "business_type": "internal"}])
    r = run(pc.resolve_cmt_rate(db, {"id": "M", "name": "Vest"}))
    assert r["rate"] == 0 and r["source"] == "none"


def test_tarif_jahit_terkunci_setelah_tagihan_cmt(monkeypatch):
    import routes.production_sewing_cost as sc
    db = FakeDB(production_pos=[{"id": "P1", "po_number": "SPK-1"}],
                po_items=[{"id": "i1", "po_id": "P1", "sku": "X", "cmt_price_snapshot": 10000}],
                dewi_cmt_payments=[{"id": "b1", "po_id": "P1", "payment_number": "CMT-001", "status": "draft"}])
    monkeypatch.setattr(sc, "get_db", lambda: db)

    async def auth(request):
        return U
    monkeypatch.setattr(sc, "require_auth", auth)

    class Req:
        class state:
            user = U
    with pytest.raises(Exception) as e:
        run(sc.set_po_sewing("P1", sc.RatesIn(items=[sc.RateIn(po_item_id="i1", rate_per_pcs=12000)]), Req()))
    assert getattr(e.value, "status_code", None) == 409 and "CMT-001" in e.value.detail
    assert db.po_items.docs[0]["cmt_price_snapshot"] == 10000
    db.dewi_cmt_payments.docs[0]["status"] = "cancelled"            # tagihan batal → boleh lagi
    assert run(sc.cmt_rate_lock(db, "P1")) is None


# ══════════════════════════════════════════════════════════════════════════════
# 6 + 12. HPP aktual per job: MI Kirim CMT, retur, upah CMT; harga kosong = gap
# ══════════════════════════════════════════════════════════════════════════════
def test_hpp_aktual_job_memuat_mi_kirim_cmt_retur_dan_upah_cmt():
    from routes import production_internal_adapter as pia
    db = FakeDB(
        production_jobs=[{"id": "J", "job_number": "JOB-1", "po_id": "P", "vendor_shipment_id": "SJ1"}],
        production_job_items=[{"job_id": "J", "po_item_id": "i1", "sku": "VST-1", "ordered_qty": 10,
                               "produced_qty": 10}],
        po_items=[{"id": "i1", "cmt_price_snapshot": 15000}],
        rahaza_materials=[{"id": "K", "name": "Kain", "unit_cost": 99999, "type": "fabric"},
                          {"id": "A", "name": "Kancing", "type": "accessory"}],
        rahaza_costing_settings=[{"id": "GLOBAL", "overhead_rate_per_pcs": 5000, "default_accessory_cost_per_unit": 0}],
        rahaza_wip_events=[{"job_id": "J", "event_type": "complete", "qty_done": 10, "rate_per_pcs": 2000}],
        rahaza_material_issues=[
            # MI Kirim Material CMT: lahir sebelum job, tanpa job_id — kini ikut
            {"id": "mi1", "vendor_shipment_id": "SJ1", "status": "issued", "source": "vendor_shipment",
             "items": [{"material_id": "K", "qty_issued": 6, "qty_returned": 1, "unit_cost_applied": 80000},
                       {"material_id": "A", "qty_issued": 10}]},
            {"id": "mi2", "vendor_shipment_id": "SJ-LAIN", "status": "issued",
             "items": [{"material_id": "K", "qty_issued": 50, "unit_cost_applied": 80000}]}])
    out = run(pia.compute_hpp_job(db, "J"))
    # bahan (6 − 1) × 80.000 = 400.000 ; upah CMT 10 × 15.000 = 150.000 ; total 550.000 / 10 = 55.000
    assert out["material_cost"] == 400000 and out["cmt_cost"] == 150000 and out["total_cost"] == 550000
    assert out["hpp_unit"] == 55000 and out["overhead_cost"] == 0 and out["internal_labor_cost"] == 20000
    assert any("Kancing" in g and "harga belum ada" in g for g in out["gaps"])


def test_harga_bahan_kosong_tidak_diam_diam():
    from routes import rahaza_hpp as rh
    assert rh.mi_item_cost_info({"unit_cost_applied": 9000}, {}, 50000, 300) == (9000.0, "issue")
    assert rh.mi_item_cost_info({}, {"unit_cost": 12000}, 50000, 300) == (12000.0, "master")
    assert rh.mi_item_cost_info({}, {"type": "accessory"}, 50000, 300) == (300.0, "default_estimate")
    assert rh.mi_item_cost_info({}, {"type": "accessory"}, 50000, 0) == (0.0, "missing")
    r = run(rh.mi_material_cost(FakeDB(rahaza_materials=[{"id": "A", "name": "Label", "type": "accessory"}]),
                                [{"items": [{"material_id": "A", "qty_issued": 4}]}], 0, 250))
    assert r["estimated_cost"] == 1000.0 and "estimasi" in r["gaps"][0]
    assert r["breakdown"][0]["cost_source_label"] == "estimasi (harga bawaan pengaturan)"


# ══════════════════════════════════════════════════════════════════════════════
# 8. Stok FG tanpa biaya: satu aturan + jurnal koreksi
# ══════════════════════════════════════════════════════════════════════════════
def test_stok_tanpa_biaya_lalu_biaya_datang_dijurnal(posting):
    # 10 pcs masuk Rp 0 (WAC 0) → tanpa jurnal; lalu 10 pcs @ 50.000 → WAC 50.000 dan
    # 10 pcs lama diakui 10 × 50.000 = 500.000 (Dr 1-1404 / Cr 5-1950) ⇒ Σ 20 × 50.000 = GL
    r = fcl.wac_after_receipt(10, 0, None, 10, 50000)
    assert r["rule"] == "reset_unvalued" and r["unit_cost"] == 50000 and r["adjustment_fg"] == 500000.0
    db = FakeDB(rahaza_materials=[{"id": "FG1", "code": "VST-1-CRL-M", "type": "fg"}],
                rahaza_material_stock=[{"id": "s", "material_id": "FG1", "location_id": "L", "qty": 10.0,
                                        "inventory_category": "fg_internal", "ownership": "cv_da"}])
    run(fcl.push_layer(db, material_id="FG1", qty=10, unit_cost=0.0, ref={"type": "cmt_receipt"}))
    assert posting == []                                          # WAC 0 → tetap tanpa biaya
    db.rahaza_material_stock.docs[0]["qty"] = 20.0
    run(fcl.push_layer(db, material_id="FG1", qty=10, unit_cost=50000.0, ref={"type": "cmt_receipt"}))
    je = posting[-1]
    assert je["source_module"] == "fg_wac_adjust" and "tanpa biaya" in je["memo"]
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in je["lines"]] == [
        ("1-1404", 500000.0, 0), ("5-1950", 0, 500000.0)]
    zero = [ly for ly in db.fg_cost_layers.docs if ly["unit_cost"] == 0][0]
    assert zero["wac_valued"] is True                             # laporan tidak lagi "tanpa biaya"
    from routes.rahaza_fin_reports import fg_valuation_row
    row = fg_valuation_row(qty=20, wac=50000, layers=db.fg_cost_layers.docs, wac_initialized=True)
    assert row["uncosted_qty"] == 0 and row["value"] == 1000000.0


def test_jalur_jual_tidak_jatuh_ke_perkiraan_bila_keluar_lewat_wac(posting):
    from routes import rahaza_posting as rp
    db = FakeDB(rahaza_hpp_snapshots=[{"work_order_id": "W", "qty_completed": 10, "material_cost": 500000}])
    shp = {"id": "SH1", "shipment_number": "SJ-1",
           "items": [{"sku": "X", "qty": 2, "work_order_id": "W", "fg_cogs": 0, "fg_cogs_layers": [],
                      "fg_cogs_uncosted_qty": 2}]}
    res = run(rp.post_cogs_shipment(db, shp, U))
    assert res["ok"] is False and res["reason"] == "zero_cogs" and res["basis"] == "wac" and posting == []
    assert rp.issued_via_wac([{"fg_cogs_layers": [{"qty": 1}]}]) is True
    assert rp.issued_via_wac([{"fg_cogs": 0}]) is False              # baris lama tanpa jejak WAC


# ══════════════════════════════════════════════════════════════════════════════
# 5. Sisa WIP per PO → selisih produksi saat PO ditutup
# ══════════════════════════════════════════════════════════════════════════════
def _wip_db(**extra):
    lines = [  # MI keluar 1.200.000 → WIP; retur 100.000 ← ; FG standar 1.000.000 →
        {"je_id": "je-mi", "account_code": "1-1403", "debit": 1200000, "credit": 0},
        {"je_id": "je-ret", "account_code": "1-1403", "debit": 0, "credit": 100000},
        {"je_id": "je-fg", "account_code": "1-1403", "debit": 0, "credit": 1000000},
        {"je_id": "je-mi", "account_code": "1-1401", "debit": 0, "credit": 1200000},
        {"je_id": "je-lain", "account_code": "1-1403", "debit": 777, "credit": 0}]
    return FakeDB(
        production_pos=[{"id": "P", "po_number": "SPK-9", "status": "Closed", "business_type": "internal"}],
        production_jobs=[{"id": "J", "po_id": "P"}],
        rahaza_material_issues=[{"id": "MI1", "production_po_id": "P"}],
        production_material_returns=[{"id": "R1", "material_issue_id": "MI1"}],
        fg_cost_layers=[{"id": "L1", "batch": {"po_id": "P"}, "gl_je_id": "je-fg"}],
        rahaza_journal_entries=[{"id": "je-mi", "source_ref": "mi:MI1", "status": "posted"},
                                {"id": "je-ret", "source_ref": "pmr:R1", "status": "posted"},
                                {"id": "je-lain", "source_ref": "mi:LAIN", "status": "posted"}],
        rahaza_journal_lines=lines, **extra)


def test_sisa_wip_po_ditelusuri_dan_ditutup(posting):
    db = _wip_db()
    pos = run(po_wip.po_wip_position(db, "P"))
    # 1.200.000 − 100.000 − 1.000.000 = 100.000 (jurnal PO lain tidak ikut)
    assert pos["residual"] == 100000.0 and pos["closed"] is True
    assert {g["source"]: g["net"] for g in pos["groups"]} == {
        "fg_receipt": -1000000.0, "material_issue": 1200000.0, "material_return": -100000.0}
    out = run(po_wip.on_po_closed(db, {"id": "P"}, U))
    assert out["posted"] is True
    je = posting[-1]
    assert je["source_ref"] == "po_wip_var:P:1"
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in je["lines"]] == [
        ("5-1960", 100000.0, 0), ("1-1403", 0, 100000.0)]
    assert db.production_pos.docs[0]["wip_variance_jes"][0]["amount"] == 100000.0


def test_sisa_wip_negatif_dan_po_maklon():
    assert po_wip.variance_lines(-250, "5-1960", "1-1403", "m") == [
        {"account_code": "1-1403", "debit": 250.0, "credit": 0, "description": "m"},
        {"account_code": "5-1960", "debit": 0, "credit": 250.0, "description": "m"}]
    assert po_wip.variance_lines(0.001, "5-1960", "1-1403", "m") == []
    db = _wip_db()
    db.production_pos.docs[0]["business_type"] = "maklon"

    async def mapping(db_):
        return {"debit_variance": "5-1960", "credit_wip": "1-1403"}
    orig = po_wip._mapping
    po_wip._mapping = mapping
    try:
        out = run(po_wip.clear_po_wip(db, "P", U))
    finally:
        po_wip._mapping = orig
    assert out["posted"] is False and "maklon" in out["note"].lower()


def test_profil_dan_akun_selisih_produksi_terdaftar():
    from data.coa_unified import DA_UNIFIED_ACCOUNTS
    from routes import rahaza_posting_profiles as pp
    prof = {p["event_type"]: p["mapping"] for p in pp.DEFAULT_PROFILES}["production_po_wip_variance"]
    assert prof == {"debit_variance": "5-1960", "credit_wip": "1-1403"}
    assert any(r[0] == "5-1960" and r[2] == "COGS" for r in DA_UNIFIED_ACCOUNTS)
    src = Path(BACKEND, "routes", "production_pos.py").read_text(encoding="utf-8")
    assert src.count("po_wip.on_po_closed(db, po, user)") == 2      # tutup biasa + tutup kurang


# ══════════════════════════════════════════════════════════════════════════════
# 9. Marjin historis memakai HPP beku; pemetaan SKU tidak menimpanya
# ══════════════════════════════════════════════════════════════════════════════
def test_marjin_bulan_lalu_memakai_hpp_beku():
    from core import marketing_cycle as mc
    from _fake_mongo import FakeDB as FM          # pembanding tanggal campuran str/datetime aman
    db = FM()
    db[mc.ORDERS].docs = [{"account_id": "A", "order_date": "2026-10-05", "status": "completed",
                           "items": [{"catalog_item_id": "C", "qty": 2, "price": 100000, "hpp_snapshot": 60000}]}]
    db[mc.CATALOG_ITEMS].docs = [{"id": "C", "hpp": 90000}]
    r = run(mc.margin_from_orders(db, "A", "2026-10"))
    # 2 × 60.000 (beku), bukan 2 × 90.000 (HPP katalog hari ini)
    assert r["hpp"] == 120000.0 and r["lines_hpp_frozen"] == 1


def test_pemetaan_sku_tidak_menimpa_hpp_beku():
    from core import sku_bridge as sb

    class Coll:
        def __init__(self):
            self.calls = []

        async def update_many(self, flt, upd, array_filters=None):
            self.calls.append((upd, array_filters))

            class R:
                modified_count = 1
            return R()

    coll = Coll()

    class DB:
        def __getitem__(self, name):
            return coll
    run(sb._backfill_orders(DB(), "PS1", {"id": "C", "fg_material_id": "F", "hpp": 70000}))
    link, snap = coll.calls
    assert not any("hpp_snapshot" in k for k in link[0]["$set"])
    assert snap[0]["$set"] == {"items.$[it].hpp_snapshot": 70000.0}
    assert snap[1] == [{"it.platform_sku_id": "PS1", "it.hpp_snapshot": None}]      # hanya yang kosong
    src = Path(BACKEND, "routes", "marketing_data_import.py").read_text(encoding="utf-8")
    assert '"items.$[it].hpp_snapshot": item.get("hpp")' not in src
    assert '"it.hpp_snapshot": None' in src


# ══════════════════════════════════════════════════════════════════════════════
# 10. Nilai persediaan FG "per tanggal" memakai stok & WAC tanggal itu
# ══════════════════════════════════════════════════════════════════════════════
def test_nilai_fg_per_tanggal_dari_buku_besar(monkeypatch):
    from routes import rahaza_fin_reports as fr
    from routes.rahaza_fin_reports import wac_at_date
    after = datetime(2026, 11, 5, 3, tzinfo=timezone.utc)
    db = FakeDB(
        rahaza_materials=[{"id": "FG1", "code": "X", "type": "fg", "unit_cost": 60000.0,
                           "wac_components": {"material": 60000.0}}],
        rahaza_material_stock=[{"id": "s", "material_id": "FG1", "location_id": "L", "qty": 15.0,
                                "inventory_category": "fg_internal", "ownership": "cv_da"}],
        # sesudah 3 Nov: masuk 10, keluar 5 ⇒ stok 3 Nov = 15 − 10 + 5 = 10
        rahaza_stock_ledger=[{"material_id": "FG1", "location_id": "L", "op": "add", "delta": 10, "created_at": after},
                             {"material_id": "FG1", "location_id": "L", "op": "issue", "delta": -5, "created_at": after},
                             {"material_id": "FG1", "location_id": "L", "op": "reserve", "delta": 3, "created_at": after}],
        rahaza_material_cost_history=[{"material_id": "FG1", "old_unit_cost": 50000.0, "new_unit_cost": 60000.0,
                                       "created_at": after}])

    class _Agg:
        async def to_list(self, n=None):
            return [{"_id": "FG1"}]
    db.rahaza_material_stock.aggregate = lambda pipe: _Agg()

    async def gl(db_, match):
        assert match["date"] == {"$lte": "2026-11-03"}
        return {"1-1404": {"debit": 500000.0, "credit": 0}}
    monkeypatch.setattr(fr, "_aggregate_by_account", gl)
    rep = run(fr.compute_fg_valuation(db, "2026-11-03"))
    row = rep["rows"][0]
    assert rep["stock_basis"] == "ledger_as_of" and row["stock_qty"] == 10 and row["wac_unit_cost"] == 50000.0
    assert rep["totals"]["value"] == rep["totals"]["gl_balance"] == 500000.0 and rep["reconciled"]
    assert wac_at_date([]) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 13. Estimasi AI tidak menghitung bahan klien
# ══════════════════════════════════════════════════════════════════════════════
def test_estimasi_ai_tanpa_bahan_klien_dan_overhead():
    from routes import dewi_maklon_quote as q
    p = q.QuoteRequestIn(product_name="Kaos", category="kaos", quantity=100, target_margin_pct=20)
    h = q._heuristic_quote(p)
    # kaos: bahan 28.000 (milik klien → 0), upah 12.600, overhead 0 ⇒ HPP 12.600 ; harga 12.600 ÷ 0,8 = 15.750
    assert h["hpp_breakdown"]["material"] == 0 and h["hpp_breakdown"]["overhead"] == 0
    assert h["hpp_per_pcs"] == 12600 and h["estimated_unit_price"] == 15750 and h["margin_pct"] == 20.0
    own = q._heuristic_quote(q.QuoteRequestIn(product_name="Kaos", category="kaos", quantity=100,
                                              target_margin_pct=20, fabric_provided_by="cv_da"))
    assert own["hpp_breakdown"]["material"] == 28000
    ai = {"hpp_breakdown": {"material": 30000, "labor": 12000, "overhead": 5000, "finishing": 3000},
          "estimated_unit_price": 70000, "source": "ai"}
    fixed = q.apply_owner_cost_rules(ai, p)
    # bahan klien & overhead dikeluarkan: HPP 15.000 → harga 15.000 ÷ 0,8 = 18.750
    assert fixed["hpp_per_pcs"] == 15000 and fixed["estimated_unit_price"] == 18750
    assert fixed["excluded_from_hpp"] == {"material_client": 30000.0, "overhead": 5000.0}
    assert fixed["margin_pct"] == 20.0 and fixed["estimated_total"] == 1875000


# ══════════════════════════════════════════════════════════════════════════════
# 14. Migrasi pemulihan HPP (pratinjau / --apply, idempoten)
# ══════════════════════════════════════════════════════════════════════════════
def _migration():
    p = Path(BACKEND) / "scripts" / "migrations" / "2026_11_06_hpp_pulihkan.py"
    spec = importlib.util.spec_from_file_location("hpp_pulihkan", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_memulihkan_hpp_tertimpa():
    mig = _migration()
    t1, t2 = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 20, tzinfo=timezone.utc)
    db = FakeDB(
        product_cost_snapshots=[
            {"model_id": "M", "created_at": t1, "applied_sizes": [{"fg_id": "F-CRL", "size_id": "S", "hpp_unit": 80000}]},
            {"model_id": "M", "created_at": t2, "applied_sizes": [
                {"fg_id": "F-CRL", "size_id": "S", "hpp_unit": 91396.10, "breakdown": {"cmt": 0}},
                {"fg_id": "F-BRG", "size_id": "S", "hpp_unit": 32175.0}]}],
        rahaza_models=[{"id": "M", "hpp_bom": 61785.55, "hpp": 77000, "hpp_source": "rnd", "hpp_rnd": 77000}],
        rahaza_materials=[
            {"id": "F-CRL", "type": "fg", "model_id": "M", "size_id": "S", "hpp": 61785.55, "hpp_source": "bom"},
            {"id": "F-BRG", "type": "fg", "model_id": "M", "size_id": "S", "hpp": 77000, "hpp_source": "rnd"},
            {"id": "F-NEW", "type": "fg", "model_id": "M", "size_id": "S2", "hpp": 61785.55}],
        marketing_catalog_items=[{"id": "C1", "fg_material_id": "F-CRL", "hpp": 61785.55, "hpp_source": "bom"},
                                 {"id": "C2", "fg_material_id": "F-BRG", "hpp": 5, "hpp_source": "wac"}],
        dewi_rnd_hpp=[{"id": "r", "overhead_pct": 10}])
    prev = run(mig.plan_and_apply(db, apply=False))
    assert (prev["fg_restore"], prev["items_restore"], prev["items_kept_wac"], prev["models_restore"]) == (2, 1, 1, 1)
    assert db.rahaza_materials.docs[0]["hpp"] == 61785.55                 # pratinjau tidak menulis
    run(mig.plan_and_apply(db, apply=True))
    fg = {d["id"]: d for d in db.rahaza_materials.docs}
    assert fg["F-CRL"]["hpp"] == 91396.10 and fg["F-BRG"]["hpp"] == 32175.0 and fg["F-BRG"]["hpp_source"] == "bom"
    assert fg["F-NEW"]["hpp"] == 61785.55                                 # tidak pernah diterapkan → tidak disentuh
    items = {d["id"]: d for d in db.marketing_catalog_items.docs}
    assert items["C1"]["hpp"] == 91396.10 and items["C2"]["hpp"] == 5      # ber-WAC tidak disentuh
    assert db.rahaza_models.docs[0]["hpp"] == 61785.55 and db.rahaza_models.docs[0]["hpp_source"] == "bom"
    again = run(mig.plan_and_apply(db, apply=True))
    assert (again["fg_restore"], again["items_restore"], again["models_restore"]) == (0, 0, 0)   # idempoten
    assert again["rnd_docs_with_overhead"] == 1


def test_migrasi_penerapan_terakhir_nol_tidak_memasang_angka_lama():
    # Uji di VPS 6 Nov: penerapan September bernilai, penerapan 5 Nov bernilai 0 (potongan Rp 0, keputusan
    # 23 Sep) → FG ber-HPP 0 TIDAK boleh diisi angka September yang basi.
    mig = _migration()
    sep, nov = datetime(2026, 9, 12, tzinfo=timezone.utc), datetime(2026, 11, 5, tzinfo=timezone.utc)
    db = FakeDB(
        product_cost_snapshots=[
            {"model_id": "M", "created_at": sep, "applied_sizes": [{"fg_id": "F1", "size_id": "S", "hpp_unit": 45000}]},
            {"model_id": "M", "created_at": nov, "applied_sizes": [{"fg_id": "F1", "size_id": "S", "hpp_unit": 0}]}],
        rahaza_models=[{"id": "M"}],
        rahaza_materials=[{"id": "F1", "type": "fg", "model_id": "M", "size_id": "S", "hpp": 0, "hpp_source": "bom"}],
        marketing_catalog_items=[], dewi_rnd_hpp=[])
    prev = run(mig.plan_and_apply(db, apply=False))
    assert prev["fg_restore"] == 0
    run(mig.plan_and_apply(db, apply=True))
    assert db.rahaza_materials.docs[0]["hpp"] == 0


def test_migrasi_ukuran_dilewati_penerapan_baru_tidak_dipulihkan():
    mig = _migration()
    sep, nov = datetime(2026, 9, 12, tzinfo=timezone.utc), datetime(2026, 11, 5, tzinfo=timezone.utc)
    db = FakeDB(
        product_cost_snapshots=[
            {"model_id": "M", "created_at": sep, "applied_sizes": [{"size_id": "S", "hpp_unit": 9300}]},
            {"model_id": "M", "created_at": nov, "applied_sizes": [],
             "skipped_sizes": [{"size_id": "S", "fg_id": "F1", "reason": "baris BOM belum bisa dinilai"}]}],
        rahaza_models=[{"id": "M"}],
        rahaza_materials=[{"id": "F1", "type": "fg", "model_id": "M", "size_id": "S", "hpp": 0, "hpp_source": "bom"}],
        marketing_catalog_items=[], dewi_rnd_hpp=[])
    assert run(mig.plan_and_apply(db, apply=False))["fg_restore"] == 0


def test_migrasi_model_menunggu_cutting_tidak_diisi_hpp_bom_lama():
    mig = _migration()
    assert mig.model_target({"id": "M", "hpp": 0, "hpp_source": "menunggu_cutting", "hpp_bom": 11406.68}) is None
    assert mig.model_target({"id": "M", "hpp": 77000, "hpp_source": "rnd", "hpp_bom": 61785.55}) is not None
