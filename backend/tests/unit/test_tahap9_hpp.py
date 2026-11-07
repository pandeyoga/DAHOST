"""Uji unit HERMETIK Tahap 9 — paket HPP (keputusan owner 7 Nov 2026 No. 5, 6, 13).

  * HPP aktual per PO = potongan (nilai cutting) + aksesoris diserahkan + upah CMT + permak — satu hitungan
    untuk PO internal & maklon (`core.hpp_aktual`).
  * Lapisan barang jadi: bahan AKTUAL per pcs dikirim (dokumen penyerahan dengan & tanpa `kind`), dibatasi sisa.
  * Sisa WIP saat Tutup PO → selisih biaya PO berjurnal jelas (profil `production_po_wip_variance`).
  * Maklon: isian overhead/margin ketikan dihapus; margin = harga jasa − HPP.
  * Biaya umum per pcs = informasi, tidak masuk HPP.
  * Benang (bahan pembantu) → beban 5-3400 saat dikeluarkan, tidak masuk HPP.
Angka harapan dihitung tangan di komentar tiap uji. Data uji fiktif.
"""
import asyncio
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from p3_fakes import FakeDB  # noqa: E402
from core import accessory_issue as ai  # noqa: E402
from core import dispatch_capacity as dcap  # noqa: E402
from core import fg_cost_layers as fcl  # noqa: E402
from core import hpp_aktual as ha  # noqa: E402
from core import po_wip  # noqa: E402
import routes.dewi_accessories_stock as stk  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402

U = {"id": "u1", "name": "Uji", "role": "admin"}
DEFAULT_MAP = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}
T_NOV = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)
THREAD_CAT = {"id": "cat-thr", "code": "SEWING_THREAD", "name": "Benang Jahit"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def posting(monkeypatch):
    """Mesin posting palsu: profil BAWAAN, jurnal dikumpulkan (D = K diperiksa)."""
    jes = []

    async def mapping(db, key):
        return dict(DEFAULT_MAP.get(key, {}))

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


def _lines(je):
    return [(ln["account_code"], round(ln["debit"], 2), round(ln["credit"], 2)) for ln in je["lines"]]


def _qmap(monkeypatch, rows: dict):
    """po_item_quantities palsu: {po_item_id: {accepted_total, dispatched, shipped}}."""
    async def fake(db, ids):
        return {i: {"accepted_total": 0, "dispatched": 0, "shipped": 0, **rows.get(i, {})} for i in ids or []}
    monkeypatch.setattr(dcap, "po_item_quantities", fake)


# PO internal fiktif: S dikirim 60 pcs, M dikirim 40 pcs
ITEMS = [{"id": "pi-s", "po_id": "PO1", "qty": 60, "sku": "UJI-T9-S", "size": "S", "color": "Hitam",
          "model_id": "MDL", "size_id": "sz-s", "cmt_price_snapshot": 15000},
         {"id": "pi-m", "po_id": "PO1", "qty": 40, "sku": "UJI-T9-M", "size": "M", "color": "Hitam",
          "model_id": "MDL", "size_id": "sz-m", "cmt_price_snapshot": 15000}]
SHIP = [{"shipment_id": "SJ1", "po_item_id": "pi-s", "qty_sent": 60},
        {"shipment_id": "SJ1", "po_item_id": "pi-m", "qty_sent": 40}]
MATS = [{"id": "cut-s", "code": "CUT-MDL-HTM-S", "type": "fabric", "is_cut_panel": True, "model_id": "MDL",
         "size_code": "S", "color_code": "HTM", "color_name": "Hitam", "unit": "pcs", "unit_cost": 20000},
        {"id": "cut-m", "code": "CUT-MDL-HTM-M", "type": "fabric", "is_cut_panel": True, "model_id": "MDL",
         "size_code": "M", "color_code": "HTM", "color_name": "Hitam", "unit": "pcs", "unit_cost": 20000},
        {"id": "kcg", "code": "KCG-01", "type": "accessory", "unit": "pcs", "unit_cost": 100, "category": "cat-acc"},
        {"id": "thr", "code": "BNG-01", "type": "accessory", "unit": "roll", "unit_cost": 13000,
         "category": "cat-thr"}]


def _mi_new():
    """Kontrak baru agen kirim: po_id, shipment_id, kind, po_item_id."""
    return {"id": "MI1", "mi_number": "MI-UJI-1", "po_id": "PO1", "shipment_id": "SJ1", "status": "issued",
            "items": [{"material_id": "cut-s", "qty_issued": 60, "unit_cost_applied": 20000, "kind": "potongan",
                       "po_item_id": "pi-s"},
                      {"material_id": "cut-m", "qty_issued": 40, "unit_cost_applied": 20000, "kind": "potongan",
                       "po_item_id": "pi-m"},
                      {"material_id": "kcg", "qty_issued": 500, "unit_cost_applied": 100, "kind": "aksesoris"}]}


def _mi_old():
    """Dokumen LAMA: production_po_id, vendor_shipment_id, tanpa kind/po_item_id."""
    return {"id": "MI1", "mi_number": "MI-UJI-1", "production_po_id": "PO1", "vendor_shipment_id": "SJ1",
            "status": "issued",
            "items": [{"material_id": "cut-s", "qty_issued": 60, "unit_cost_applied": 20000},
                      {"material_id": "cut-m", "qty_issued": 40, "unit_cost_applied": 20000},
                      {"material_id": "kcg", "qty_issued": 500, "unit_cost_applied": 100}]}


def _db(mi, **extra):
    base = dict(production_pos=[{"id": "PO1", "po_number": "PO-UJI-T9-1", "business_type": "internal",
                                 "status": "In Production", "vendor_name": "CMT Uji"}],
                po_items=[dict(i) for i in ITEMS], vendor_shipment_items=[dict(s) for s in SHIP],
                vendor_shipments=[{"id": "SJ1", "status": "sent", "shipment_type": "NORMAL"}],
                rahaza_materials=[dict(m) for m in MATS], rahaza_material_issues=[mi],
                rahaza_material_categories=[THREAD_CAT, {"id": "cat-acc", "code": "ACCESSORY", "name": "Aksesoris"}])
    base.update(extra)
    return FakeDB(**base)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Lapisan barang jadi dari dokumen penyerahan (dengan & tanpa `kind`)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("mi_factory", [_mi_new, _mi_old], ids=["kontrak-baru", "dokumen-lama"])
def test_lapisan_aktual_dari_dokumen_penyerahan(mi_factory):
    db = _db(mi_factory())
    s = run(ha.po_issue_summary(db, "PO1"))
    # potongan S 60 × 20.000 = 1.200.000; M 40 × 20.000 = 800.000; aksesoris 500 × 100 = 50.000
    assert s["cut"] == {"pi-s": 1200000.0, "pi-m": 800000.0} and s["acc_value"] == 50000.0
    assert s["sent"] == {"pi-s": 60.0, "pi-m": 40.0} and s["sent_basis"] == "kiriman"
    # terima S 50 pcs: potongan 20.000/pcs + aksesoris 50.000 ÷ 100 pcs dikirim = 500/pcs → bahan 20.500/pcs
    out = run(fcl.compute_batch_unit_cost(db, po_item=ITEMS[0], qty=50))
    assert out["material_source"] == "aktual" and out["material_basis"] == "aktual"
    assert out["material_cost"] == 20500.0 and out["cut_value"] == 1000000.0 and out["accessory_value"] == 25000.0
    assert out["unit_cost"] == 35500.0                       # + upah jahit 15.000 dari form PO
    # standar = BOM (tidak ada BOM di DB uji) → tidak memakai penyerahan
    std = run(fcl.compute_batch_unit_cost(db, po_item=ITEMS[0], qty=50, basis="standard"))
    assert std["material_source"] == "none" and "material_basis" not in std


def test_po_tanpa_penyerahan_memakai_bom_standar_dan_menyebutnya():
    db = FakeDB(po_items=[dict(ITEMS[0])])
    out = run(fcl.compute_batch_unit_cost(db, po_item=ITEMS[0], qty=10))
    assert out["material_source"] == "none"
    assert any("BOM standar" in g for g in out["gaps"])


def test_benang_ikut_terkirim_tidak_masuk_hpp():
    mi = _mi_new()
    mi["items"].append({"material_id": "thr", "qty_issued": 2, "unit_cost_applied": 13000, "kind": "aksesoris"})
    s = run(ha.po_issue_summary(_db(mi), "PO1"))
    assert s["acc_value"] == 50000.0 and s["aux_value"] == 26000.0           # 2 roll × 13.000 di luar HPP
    aux = [ln for ln in s["lines"] if ln["kind"] == ha.KIND_AUX]
    assert len(aux) == 1 and aux[0]["in_hpp"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 2. Alokasi per pcs dikirim + batas sisa
# ══════════════════════════════════════════════════════════════════════════════
def test_alokasi_per_pcs_dikirim_dan_batas_sisa():
    s = {"cut": {"A": 1000.0}, "cut_value": 1000.0, "acc_value": 400.0, "sent": {"A": 10.0}, "sent_total": 10.0,
         "sent_basis": "kiriman"}
    empty = ha.absorbed_from_layers([])
    a = ha.allocate_batch(s, "A", 4, empty)                 # 4 × (100 + 40) = 560
    assert (a["cut_value"], a["accessory_value"], a["capped"]) == (400.0, 160.0, False)
    # aksesoris semua diserahkan di kiriman pertama (5 pcs), kiriman kedua 5 pcs tanpa aksesoris:
    # per pcs dikirim turun menjadi 40, tetapi lapisan pertama sudah menyerap 400 → batch kedua 0, tidak lebih
    layers = [{"qty_in": 5, "batch": {"po_item_id": "A"},
               "breakdown": {"material_basis": "aktual", "cut_value": 500.0, "accessory_value": 400.0}}]
    b = ha.allocate_batch(s, "A", 5, ha.absorbed_from_layers(layers))
    assert (b["cut_value"], b["accessory_value"], b["capped"]) == (500.0, 0.0, True)
    # penerimaan dobel (qty melebihi yang dikirim): tidak mengkredit WIP lebih dari yang didebit
    full = [{"qty_in": 10, "batch": {"po_item_id": "A"},
             "breakdown": {"material_basis": "aktual", "cut_value": 1000.0, "accessory_value": 400.0}}]
    c = ha.allocate_batch(s, "A", 10, ha.absorbed_from_layers(full))
    assert c["material_value"] == 0.0 and c["capped"] is True
    # lapisan LAMA (BOM) ikut membatasi: 600 bahan sudah keluar dari WIP lewat lapisan BOM
    old = [{"qty_in": 6, "batch": {"po_item_id": "A"}, "breakdown": {"material_cost": 100.0}}]
    d = ha.allocate_batch(s, "A", 10, ha.absorbed_from_layers(old))
    assert d["material_value"] == 800.0                     # 1.400 − 600


def test_potongan_lama_tanpa_baris_dibagi_per_pcs_dikirim():
    mi = _mi_old()
    mi["items"] = [{"material_id": "cut-x", "qty_issued": 100, "unit_cost_applied": 1000}]
    db = _db(mi)
    db.rahaza_materials.docs.append({"id": "cut-x", "code": "CUT-LAIN", "is_cut_panel": True, "model_id": "LAIN"})
    s = run(ha.po_issue_summary(db, "PO1"))
    assert s["cut"] == {"pi-s": 60000.0, "pi-m": 40000.0}  # 100.000 dibagi 60 : 40
    assert any("dibagi per pcs" in g for g in s["gaps"])


# ══════════════════════════════════════════════════════════════════════════════
# 3. WIP→FG = nilai lapisan aktual; sisa WIP saat Tutup PO → selisih biaya PO
# ══════════════════════════════════════════════════════════════════════════════
def test_wip_ke_fg_sama_dengan_lapisan_dan_sisa_ditutup_saat_po_ditutup(posting, monkeypatch):
    db = _db(_mi_new())
    # terima S 55 (5 tidak diterima), M 40
    ly_s = run(fcl.compute_batch_unit_cost(db, po_item=ITEMS[0], qty=55))
    ly_m = run(fcl.compute_batch_unit_cost(db, po_item=ITEMS[1], qty=40))
    layers = [{"id": "L1", "material_id": "fg-s", "qty_in": 55, "unit_cost": ly_s["unit_cost"],
               "total_cost": round(ly_s["unit_cost"] * 55, 2), "batch": {"po_id": "PO1", "po_item_id": "pi-s"},
               "breakdown": {k: v for k, v in ly_s.items() if k != "gaps"}},
              {"id": "L2", "material_id": "fg-m", "qty_in": 40, "unit_cost": ly_m["unit_cost"],
               "total_cost": round(ly_m["unit_cost"] * 40, 2), "batch": {"po_id": "PO1", "po_item_id": "pi-m"},
               "breakdown": {k: v for k, v in ly_m.items() if k != "gaps"}}]
    db.fg_cost_layers.docs = [dict(x) for x in layers]
    db.cmt_receipts.docs = [{"id": "R1", "po_id": "PO1", "receipt_code": "RC-UJI", "status": "completed_qc",
                             "qc_completed_at": T_NOV, "total_actual": 95}]
    res = run(rp.post_wip_to_fg_on_cmt_receipt(db, db.cmt_receipts.docs[0], ["L1", "L2"], U))
    # S: 55 × (20.000 + 500 + 15.000) = 1.952.500; M: 40 × 35.500 = 1.420.000 → 3.372.500
    assert res["ok"] and _lines(posting[-1]) == [("1-1404", 3372500.0, 0), ("1-1403", 0, 3372500.0)]
    # buku besar PO: bahan diserahkan 2.050.000 + upah CMT 95 × 15.000 = 1.425.000 masuk WIP
    db.rahaza_journal_entries.docs = [{"id": "je-mi", "source_ref": "mi:MI1", "status": "posted"}]
    db.dewi_cmt_payments.docs = [{"id": "B1", "po_id": "PO1", "gl_je_id": "je-cmt", "subtotal": 1425000,
                                  "total_pcs": 95, "status": "posted"}]
    for ly in db.fg_cost_layers.docs:
        ly["gl_je_id"] = "je-fg"
    db.rahaza_journal_lines.docs = [
        {"je_id": "je-mi", "account_code": "1-1403", "debit": 2050000, "credit": 0},
        {"je_id": "je-cmt", "account_code": "1-1403", "debit": 1425000, "credit": 0},
        {"je_id": "je-fg", "account_code": "1-1403", "debit": 0, "credit": 3372500}]
    _qmap(monkeypatch, {"pi-s": {"accepted_total": 55}, "pi-m": {"accepted_total": 40}})
    pos = run(po_wip.po_wip_position(db, "PO1"))
    # sisa = bahan 5 pcs S yang tidak diterima: 5 × 20.000 + 5 × 500 = 102.500
    assert pos["residual"] == 102500.0
    out = run(po_wip.on_po_closed(db, {"id": "PO1"}, U))
    je = posting[-1]
    assert out["posted"] is True and je["source_ref"] == "po_wip_var:PO1:1"
    assert _lines(je) == [("5-1960", 102500.0, 0), ("1-1403", 0, 102500.0)]
    assert "Selisih biaya PO PO-UJI-T9-1" in je["memo"] and "5 pcs dikirim" in je["memo"]
    fig = run(ha.po_hpp(db, "PO1", detail=False))
    # HPP aktual PO = 2.000.000 + 50.000 + 1.425.000 = 3.475.000; bagian pcs lolos QC = 3.372.500
    assert fig["total_hpp"] == 3475000.0 and fig["absorbed_cost"] == 3372500.0
    assert fig["unabsorbed_cost"] == 102500.0 and fig["hpp_per_pcs"] == 35500.0      # 3.372.500 ÷ 95
    # rincian per komponen (bagian pcs lolos QC ÷ pcs lolos QC) menjumlah ke HPP per pcs yang sama
    assert round(sum(c["per_pcs"] for c in fig["components"]), 2) == 35500.0


def test_hook_tutup_po_tetap_minimal_di_production_pos():
    src = Path(BACKEND, "routes", "production_pos.py").read_text(encoding="utf-8")
    assert src.count("po_wip.on_po_closed(db, po, user)") == 2      # kait yang sama, tanpa hitungan kedua
    assert DEFAULT_MAP["production_po_wip_variance"] == {"debit_variance": "5-1960", "credit_wip": "1-1403"}


# ══════════════════════════════════════════════════════════════════════════════
# 4. Maklon: tanpa isian manual; margin = harga jasa − HPP
# ══════════════════════════════════════════════════════════════════════════════
def _maklon_db():
    return FakeDB(
        production_pos=[{"id": "PM1", "po_number": "PO-UJI-T9-MKL", "business_type": "maklon", "status": "In Production",
                         "customer_name": "Klien Uji", "buyer_id": "cl-uji"}],
        po_items=[{"id": "pm-1", "po_id": "PM1", "qty": 100, "sku": "UJI-T9-K", "cmt_price_snapshot": 12000,
                   "selling_price_snapshot": 20000}],
        vendor_shipment_items=[{"shipment_id": "SJM", "po_item_id": "pm-1", "qty_sent": 100}],
        vendor_shipments=[{"id": "SJM", "status": "sent"}],
        rahaza_materials=[{"id": "kcg", "code": "KCG-01", "type": "accessory", "unit_cost": 1000}],
        rahaza_material_issues=[{"id": "MIM", "mi_number": "MI-UJI-M", "po_id": "PM1", "shipment_id": "SJM",
                                 "cost_target": "maklon", "status": "issued",
                                 "items": [{"material_id": "kcg", "qty_issued": 100, "unit_cost_applied": 1000,
                                            "kind": "aksesoris"}]}],
        dewi_cmt_payments=[{"id": "BM", "po_id": "PM1", "subtotal": 1080000, "total_pcs": 90, "status": "posted"}],
        dewi_cmt_permak=[{"id": "PK", "po_id": "PM1", "po_item_id": "pm-1", "total_cost": 9000}],
        # isian ketikan LAMA: overhead 15% & komponen — tidak boleh dibaca lagi
        dewi_maklon_hpp=[{"order_id": "PM1", "overhead_pct": 15, "profit_margin_pct": 30,
                          "components": [{"name": "ketikan", "qty": 1, "unit_cost": 999999, "total": 999999}]}])


def test_hpp_maklon_tanpa_komponen_manual(monkeypatch):
    from routes import dewi_maklon_billing as billing
    db = _maklon_db()
    _qmap(monkeypatch, {"pm-1": {"accepted_total": 90, "dispatched": 80, "shipped": 80}})
    monkeypatch.setattr(billing, "get_db", lambda: db)
    out = run(billing.get_hpp("PM1", user=U))
    # HPP = aksesoris 100.000 + CMT 1.080.000 + permak 9.000 = 1.189.000 (tanpa 999.999 & tanpa overhead 15%)
    assert out["total_hpp"] == 1189000.0 and out["overhead_amount"] == 0 and out["manual_snapshot"] is None
    assert out["profit_margin_pct"] is None and out["suggested_price_per_pcs"] is None
    # per pcs lolos QC: (aksesoris 1.000 × 90 + 1.080.000 + 9.000) ÷ 90 = 13.100 → margin/pcs 20.000 − 13.100
    assert out["hpp_per_pcs"] == 13100.0 and out["margin_per_pcs"] == 6900.0
    # margin PO = pendapatan (80 diterima klien × 20.000) − HPP penuh
    assert out["revenue"] == 1600000.0 and out["margin"] == 411000.0
    assert {c["key"] for c in out["components"]} == {"aksesoris", "upah_cmt", "permak"}
    with pytest.raises(HTTPException) as e:
        run(billing.upsert_hpp(billing.HPPIn(order_id="PM1", components=[]), user=U))
    assert e.value.status_code == 410
    assert len(db.dewi_maklon_hpp.docs) == 1 and db.dewi_maklon_hpp.docs[0]["overhead_pct"] == 15   # tidak ditulis


def test_satu_hitungan_untuk_endpoint_lama(monkeypatch):
    from routes import production_maklon_bridge as bridge
    db = _maklon_db()
    _qmap(monkeypatch, {"pm-1": {"accepted_total": 90, "dispatched": 80, "shipped": 80}})
    a = run(bridge.maklon_actual_costs(db, "PM1"))
    fig = run(ha.po_hpp(db, "PM1", detail=False))
    assert a["total_cost"] == fig["total_hpp"] == 1189000.0 and a["source"] == "hpp_per_po"
    assert a["accessory_cost_per_pcs"] == 1000.0 and a["accessory_cost_unabsorbed"] == 10000.0
    src = Path(BACKEND, "routes", "rahaza_hpp.py").read_text(encoding="utf-8")
    assert "db.dewi_maklon_material_issues" not in src.split("from core import hpp_aktual as _ha")[1]


# ══════════════════════════════════════════════════════════════════════════════
# 5. Biaya umum per pcs = informasi, tidak masuk HPP
# ══════════════════════════════════════════════════════════════════════════════
def test_biaya_umum_per_pcs_informasi_tidak_masuk_hpp(monkeypatch):
    db = _db(_mi_new())
    db.rahaza_coa_accounts.docs = [
        {"code": "5-3100", "name": "Listrik Pabrik", "flags": {"is_cogs_overhead": True}},
        {"code": "5-3400", "name": "Bahan Pembantu Produksi", "flags": {"is_cogs_overhead": True}},
        {"code": "5-3000", "name": "HPP Overhead", "is_group": True, "flags": {"is_cogs_overhead": True}}]
    db.rahaza_journal_lines.docs = [
        {"account_code": "5-3100", "date": "2026-11-03", "debit": 600000, "credit": 0, "entity": "DA"},
        {"account_code": "5-3400", "date": "2026-11-20", "debit": 400000, "credit": 0},
        {"account_code": "5-3100", "date": "2026-11-04", "debit": 777000, "credit": 0, "entity": "SMU"},   # CV lain
        {"account_code": "5-3100", "date": "2026-10-30", "debit": 555000, "credit": 0, "entity": "DA"}]    # bulan lain
    db.cmt_receipts.docs = [{"id": "R1", "po_id": "PO1", "status": "completed_qc", "qc_completed_at": T_NOV,
                             "total_actual": 100}]
    _qmap(monkeypatch, {"pi-s": {"accepted_total": 60}, "pi-m": {"accepted_total": 40}})
    m = run(ha.overhead_month(db, "2026-11", "internal"))
    assert m["overhead"] == 1000000.0 and m["pcs"] == 100 and m["per_pcs"] == 10000.0 and m["in_hpp"] is False
    # buku CV Sukma tanpa beban bulan itu → "belum ada data", bukan Rp 0 per pcs
    assert run(ha.overhead_month(db, "2026-10", "maklon"))["per_pcs"] is None
    fig = run(ha.po_hpp(db, "PO1", detail=False))
    assert fig["overhead_info"]["per_pcs"] == 10000.0 and fig["overhead_info"]["in_hpp"] is False
    # HPP tetap potongan + aksesoris + upah CMT + permak (tagihan CMT belum ada) — tanpa 10.000/pcs biaya umum
    assert fig["total_hpp"] == 2050000.0
    assert sum(c["amount"] for c in fig["components"]) == fig["total_hpp"]


# ══════════════════════════════════════════════════════════════════════════════
# 6. Benang = bahan pembantu → 5-3400 saat dikeluarkan
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def stock(monkeypatch):
    qty = {}

    async def usable(db, mid):
        return float(qty.get(mid, 0))

    async def add(db, mid, loc, q):
        qty[mid] = float(qty.get(mid, 0)) + q

    async def loc(db):
        return "LOC-ACC"
    monkeypatch.setattr(ai, "_usable_qty", usable)
    monkeypatch.setattr(ai, "_stock_qty", usable)
    monkeypatch.setattr(ai, "_add_stock", add)
    monkeypatch.setattr(ai, "_get_accessory_location_id", loc)
    monkeypatch.setattr(stk, "_get_accessory_location_id", loc)
    return qty


def _thread_db(cat=None):
    return FakeDB(rahaza_materials=[{"id": "thr", "code": "BNG-01", "name": "Benang Uji", "type": "accessory",
                                     "active": True, "unit": "roll", "unit_cost": 13000, "category": "cat-thr"},
                                    {"id": "kcg", "code": "KCG-01", "name": "Kancing Uji", "type": "accessory",
                                     "active": True, "unit": "pcs", "unit_cost": 100, "category": "cat-acc"}],
                  rahaza_material_categories=[cat or THREAD_CAT, {"id": "cat-acc", "code": "ACCESSORY"}])


def test_benang_dari_request_internal_dibebankan_ke_5_3400(posting, stock):
    assert DEFAULT_MAP["inventory_issue"]["debit_production_supplies"] == "5-3400"
    assert ai.PROFILE_ROLES["inventory_issue"][ai.COST_AUX] == "debit_production_supplies"
    db = _thread_db()
    stock["thr"] = 10
    tgt = run(ai.resolve_cost_target(db, divisi="Produksi"))
    assert tgt["cost_target"] == "wip"                      # aturan 6 Nov: divisi Produksi → WIP …
    res = run(ai.issue_accessory(db, U, acc_id="thr", qty=3, target=tgt))
    assert res["cost_target"] == "bahan_pembantu"           # … kecuali bahan pembantu (keputusan No. 5)
    assert _lines(posting[-1]) == [("5-3400", 39000.0, 0), ("1-1402", 0, 39000.0)]       # 3 × 13.000
    assert db.rahaza_material_movements.docs[-1]["cost_target"] == "bahan_pembantu"
    # aksesoris biasa tetap WIP
    stock["kcg"] = 10
    run(ai.issue_accessory(db, U, acc_id="kcg", qty=2, target=tgt))
    assert _lines(posting[-1]) == [("1-1403", 200.0, 0), ("1-1402", 0, 200.0)]


def test_penanda_kategori_menang_atas_bawaan(posting, stock):
    db = _thread_db({**THREAD_CAT, "bahan_pembantu": False})
    stock["thr"] = 5
    res = run(ai.issue_accessory(db, U, acc_id="thr", qty=1, target={"cost_target": "wip"}))
    assert res["cost_target"] == "wip"
    other = {"id": "cat-oli", "code": "OLI", "bahan_pembantu": True}
    assert ha.category_is_aux(other) is True and ha.category_is_aux({"code": "ACCESSORY"}) is False


def test_benang_tidak_dibandingkan_kebutuhan_po():
    db = _thread_db()
    db.production_pos.docs = [{"id": "PO1", "po_number": "PO-UJI", "business_type": "internal"}]
    rows = [{"material": db.rahaza_materials.docs[0], "qty": 50}]
    assert run(ai.guard_po_over_issue(db, {"po_id": "PO1", "po_number": "PO-UJI"}, rows, "")) == []


def test_material_issue_berisi_benang_memecah_debit(posting):
    db = _thread_db()
    mi = {"id": "MIX", "mi_number": "MI-UJI-X", "items": [
        {"material_id": "kcg", "qty_issued": 10, "unit_cost_applied": 100},
        {"material_id": "thr", "qty_issued": 1, "unit_cost_applied": 13000}]}
    res = run(rp.post_inventory_issue(db, mi, U))
    assert res["ok"] is True
    assert _lines(posting[-1]) == [("1-1403", 1000.0, 0), ("5-3400", 13000.0, 0), ("1-1402", 0, 14000.0)]


# ══════════════════════════════════════════════════════════════════════════════
# 7. Migrasi 2026_11_07_hpp_aktual (pratinjau / tulis, idempoten)
# ══════════════════════════════════════════════════════════════════════════════
def _mig():
    p = Path(BACKEND, "scripts", "migrations", "2026_11_07_hpp_aktual.py")
    spec = importlib.util.spec_from_file_location("mig_hpp_aktual", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_migrasi_pratinjau_lalu_tulis_idempoten(capsys):
    m = _mig()
    assert m.plan_categories([{"id": "a", "code": "SEWING_THREAD"}, {"id": "b", "code": "SEWING_THREAD",
                                                                      "bahan_pembantu": False}]) == ["a"]
    assert m.plan_profile({"mapping": {}}, True) == "add" and m.plan_profile({"mapping": {}}, False) == "no_account"
    db = FakeDB(rahaza_material_categories=[dict(THREAD_CAT)],
                rahaza_materials=[{"id": "thr", "category": "cat-thr"}],
                rahaza_posting_profiles=[{"event_type": "inventory_issue", "mapping": {"debit_wip": "1-1403"}}],
                rahaza_coa_accounts=[{"code": "5-3400"}],
                dewi_maklon_hpp=[{"order_id": "PM1", "overhead_pct": 15}])
    pre = run(m.run(db, apply=False))
    assert pre["categories"]["to_flag"] == 1 and pre["profile"]["plan"] == "add" and pre["manual_hpp"]["to_archive"] == 1
    assert "bahan_pembantu" not in db.rahaza_material_categories.docs[0]                   # pratinjau tidak menulis
    run(m.run(db, apply=True))
    assert db.rahaza_material_categories.docs[0]["bahan_pembantu"] is True
    assert db.rahaza_posting_profiles.docs[0]["mapping"]["debit_production_supplies"] == "5-3400"
    assert db.dewi_maklon_hpp.docs[0]["superseded_by"] == "hpp_per_po" and db.dewi_maklon_hpp.docs[0]["overhead_pct"] == 15
    again = run(m.run(db, apply=True))
    assert again["categories"]["to_flag"] == 0 and again["profile"]["plan"] == "present"
    assert again["manual_hpp"]["to_archive"] == 0
    assert "Klien" not in capsys.readouterr().out                                          # ringkasan tanpa nama


# ══════════════════════════════════════════════════════════════════════════════
# 8. Layar: satu hub HPP, tanpa isian manual, tanpa <select polos
# ══════════════════════════════════════════════════════════════════════════════
ERP = Path(BACKEND).parent / "frontend" / "src" / "components" / "erp"


def test_layar_hpp_satu_hub_dan_tanpa_isian_manual():
    hub = (ERP / "hubs" / "FinanceHppHub.jsx").read_text(encoding="utf-8")
    for key in ("{ key: 'actual'", "{ key: 'unit'", "{ key: 'rates'"):
        assert key in hub
    mk = (ERP / "MaklonHppModule.jsx").read_text(encoding="utf-8")
    assert "hppTabsFor" in mk and "overhead_pct" not in mk and "/api/dewi/maklon/hpp" not in mk
    sew = (ERP / "costing" / "SewingCostModule.jsx").read_text(encoding="utf-8")
    assert "hppTabsFor" in sew and "sewing-cost/pos" not in sew
    po = (ERP / "RahazaHPPModule.jsx").read_text(encoding="utf-8")
    assert "<PageLayout" in po and "DetailPanel" in po and "/rahaza/hpp/po" in po and "business_type" in po
    rates = (ERP / "costing" / "StandardRateModule.jsx").read_text(encoding="utf-8")
    assert "<PageLayout" in rates and "process_rates" in rates
    for src in (hub, mk, sew, po, rates):
        assert "<sel" + "ect" not in src and "window.confirm" not in src
