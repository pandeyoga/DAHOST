"""Uji unit HERMETIK Tahap 2 Pengadaan (2026-11-06) — keputusan owner 6 Nov.

Angka harapan DIHITUNG TANGAN:
  * Faktur dari GR: GR 100 @1.000 (GRNI 100.000). Faktur 100 @1.100 = 110.000 + ongkir 5.000 + PPN 11 %
    non-PKP 12.100 = 127.100. Selisih 27.100.
      - stok masih 100 → semua ke persediaan; HPP (100 × 1.000 + 27.100) / 100 = 1.271.
      - stok tinggal 40 → 40 % = 10.840 ke persediaan (HPP (40 × 1.000 + 10.840) / 40 = 1.271), 16.260 ke 5-1900.
      - batal faktur, stok masih 40 → HPP kembali 1.000, tanpa jurnal koreksi; stok tinggal 20 → turun
        5.420 di stok, sisanya 5.420 jurnal Dr 1-1401 / Cr 5-1900.
  * Ongkir 5.000 − potongan 1.000 atas baris 30.000 & 10.000 → +3.000 & +1.000.
  * Stok 10 bernilai 0 lalu beli 5 @1.000 → HPP 1.000, stok lama dinilai ulang 10.000 → Dr 1-1402 / Cr 5-1950.
    Stok −4 @900 lalu beli @1.000 → −4 × (1.000 − 900) = −400.
  * Diterima dengan diskon: potongan 15.000 atas stok 10 @1.000 (nilai 10.000) → 10.000 ke persediaan
    (HPP 0), 5.000 ke 5-1900 (dulu 15.000 dikredit persediaan padahal stok hanya turun 10.000).
  * GR satuan roll (1 roll = 25 kg): 2 roll @25.000 → 50 kg @1.000.
  * Belanja mingguan: ambang 100, stok 20 → kurang 80; sisa PO lama 50 → kurang 30.

Jalankan:  cd backend && python -m pytest tests/unit/test_tahap2_pengadaan.py -q
"""
import asyncio
import copy
import importlib.util
import os
import sys
import types
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

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from core import procurement_guards as pg  # noqa: E402
from core import purchase_costing as pc  # noqa: E402
from core import purchase_returns as pr  # noqa: E402
from core import quarantine as qmod  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402

DEFAULT_MAP = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}
WH = {"id": "u-gd", "name": "Gudang Uji", "email": "gd@x", "role": "admin_gudang"}
PROC = {"id": "u-pr", "name": "Pengadaan Uji", "email": "pr@x", "role": "admin_pengadaan"}
FIN = {"id": "u-fin", "name": "Keuangan Uji", "email": "fin@x", "role": "accounting"}


def run(coro):
    return asyncio.run(coro)


class Req:
    def __init__(self, body=None):
        self._b = body or {}

        class _S:
            pass
        self.state = _S()

    async def json(self):
        return copy.deepcopy(self._b)

    async def body(self):
        return b"{}" if self._b else b""


async def _noop(*a, **k):
    return None


@pytest.fixture
def posting(monkeypatch):
    jes = []

    async def mapping(db, key):
        return dict(DEFAULT_MAP.get(key, {}))

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        lines = [dict(ln) for ln in lines if float(ln.get("debit") or 0) or float(ln.get("credit") or 0)]
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2), lines
        if posting_state.fail:
            return {"ok": False, "error": "periode tertutup"}
        je = {"id": f"je-{len(jes) + 1}", "je_number": f"JE-{len(jes) + 1}", "source_module": mod,
              "source_ref": ref, "lines": lines}
        jes.append(je)
        return {"ok": True, "je_id": je["id"], "je_number": je["je_number"]}

    async def none(*a, **k):
        return None
    posting_state = types.SimpleNamespace(fail=False)
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(pp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)

    def lines(i=-1, mod=None):
        rows = [j for j in jes if mod is None or j["source_module"] == mod]
        return sorted((ln["account_code"], round(ln["debit"], 2), round(ln["credit"], 2)) for ln in rows[i]["lines"])
    return types.SimpleNamespace(jes=jes, lines=lines, state=posting_state)


@pytest.fixture
def array_paths(monkeypatch):
    """Kueri `items.material_id` (jalur bertitik menembus ARRAY, semantik Mongo: cocok bila salah satu
    elemen cocok). Mongo palsu bersama tidak mendukungnya; ditambal HANYA selama uji berkas ini."""
    def get(doc, dotted):
        cur, through_list = [doc], False
        for part in dotted.split("."):
            nxt = []
            for c in cur:
                if isinstance(c, list):
                    through_list = True
                    nxt += [el[part] for el in c if isinstance(el, dict) and part in el]
                elif isinstance(c, dict) and part in c:
                    nxt.append(c[part])
            if not nxt:
                return fm._MISSING
            cur = nxt
        return cur if through_list else cur[0]
    monkeypatch.setattr(fm, "_get", get)


@pytest.fixture
def valued(monkeypatch):
    """qty bernilai per material yang dibaca `quarantine.valued_onhand` (diatur per uji)."""
    q = {}

    async def vonhand(db, mid):
        return float(q.get(mid, 0.0))
    monkeypatch.setattr(qmod, "valued_onhand", vonhand)
    return q


# ══════════════════════ 3. selisih faktur → HPP (murni) ══════════════════════
def test_alokasi_ongkir_potongan_menurut_nilai_dan_sisa_pembulatan():
    landed, rest = pc.allocate_landed([{"amount": 30000}, {"amount": 10000}], freight=5000, discount=1000)
    assert landed == [33000.0, 11000.0] and rest == 0.0
    landed, rest = pc.allocate_landed([{"amount": 1}, {"amount": 1}, {"amount": 1}], freight=1)
    assert sum(landed) == pytest.approx(4.0) and rest == 0.0          # 0,33 + 0,33 + 0,34
    assert pc.allocate_landed([], freight=500) == ([], 500.0)           # tanpa baris → 5-1900
    assert pc.on_hand_ratio(100, 40) == 0.4 and pc.on_hand_ratio(100, 250) == 1.0 and pc.on_hand_ratio(10, 0) == 0.0


def _inv_db(valued_qty, valued, unit_cost=1000.0):
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "A", "code": "KN-1", "name": "Kain", "type": "fabric", "unit": "kg",
                                     "unit_cost": unit_cost})
    valued["A"] = valued_qty
    inv = {"id": "ap1", "invoice_number": "AP-1", "vendor_name": "PT Uji", "source": "gr", "gr_ids": ["GR1"],
           "gl_debit_code": "2-1150", "input_tax_treatment": "kapitalisasi", "issue_date": "2026-11-06",
           "items": [{"id": "i1", "gr_id": "GR1", "gr_item_id": "L1", "material_id": "A", "qty": 100,
                      "price": 1100, "amount": 110000, "gr_unit_cost": 1000, "gr_amount": 100000}],
           "subtotal": 110000, "freight_amount": 5000, "invoice_discount": 0, "tax_pct": 11, "tax_amount": 12100,
           "total": 127100, "gl_grni_amount": 100000, "gl_price_variance": 10000}
    db.rahaza_ap_invoices.docs.append(copy.deepcopy(inv))
    return db, inv


def test_faktur_selisih_semua_ke_hpp_bila_barang_masih_ada(posting, valued):
    db, inv = _inv_db(100, valued)
    res = run(rp.post_ap_invoice(db, inv, FIN))
    assert res["ok"], res
    assert posting.lines() == [("1-1401", 27100.0, 0), ("2-1100", 0, 127100.0), ("2-1150", 100000.0, 0)]
    assert db.rahaza_materials.docs[0]["unit_cost"] == pytest.approx(1271.0)
    h = db.rahaza_material_cost_history.docs[-1]
    assert h["material_id"] == "A" and h["source"] == "invoice_variance" and "AP-1" in h["notes"]
    adj = db.rahaza_ap_invoices.docs[0]["hpp_adjustment"]
    assert adj["status"] == "applied" and adj["to_inventory"] == 27100 and adj["to_ppv"] == 0


def test_faktur_bagian_terpakai_tetap_5_1900_dan_batal_membalik(posting, valued, monkeypatch):
    db, inv = _inv_db(40, valued)
    run(rp.post_ap_invoice(db, inv, FIN))
    assert posting.lines() == [("1-1401", 10840.0, 0), ("2-1100", 0, 127100.0), ("2-1150", 100000.0, 0),
                               ("5-1900", 16260.0, 0)]
    assert db.rahaza_materials.docs[0]["unit_cost"] == pytest.approx(1271.0)

    async def voided(*a, **k):
        return {"ok": True, "voided": True}
    monkeypatch.setattr(rp, "_void_je_by_source", voided)
    n = len(posting.jes)
    valued["A"] = 20                                    # 20 lagi terpakai sesudah faktur dijurnal
    out = run(rp.void_ap_invoice_posting(db, "ap1", FIN, reason="batal"))
    assert out["hpp_reversal"]["ok"]
    assert db.rahaza_materials.docs[0]["unit_cost"] == pytest.approx(1000.0)      # (20 × 1.271 − 5.420) / 20
    assert len(posting.jes) == n + 1 and posting.lines() == [("1-1401", 5420.0, 0), ("5-1900", 0, 5420.0)]
    assert db.rahaza_ap_invoices.docs[0]["hpp_adjustment"]["status"] == "reversed"


def test_faktur_batal_stok_utuh_tanpa_jurnal_koreksi(posting, valued, monkeypatch):
    db, inv = _inv_db(40, valued)
    run(rp.post_ap_invoice(db, inv, FIN))

    async def voided(*a, **k):
        return {"ok": True, "voided": True}
    monkeypatch.setattr(rp, "_void_je_by_source", voided)
    n = len(posting.jes)
    run(rp.void_ap_invoice_posting(db, "ap1", FIN))
    assert db.rahaza_materials.docs[0]["unit_cost"] == pytest.approx(1000.0) and len(posting.jes) == n


def test_faktur_jurnal_gagal_hpp_dikembalikan_dan_klaim_mencegah_dobel(posting, valued):
    db, inv = _inv_db(100, valued)
    posting.state.fail = True
    res = run(rp.post_ap_invoice(db, inv, FIN))
    assert not res["ok"] and db.rahaza_materials.docs[0]["unit_cost"] == pytest.approx(1000.0)
    assert db.rahaza_ap_invoices.docs[0]["hpp_adjustment"]["status"] == "failed"
    posting.state.fail = False
    # proses lain sedang menerapkan selisih faktur yang sama → tidak menggandakan revaluasi
    db.rahaza_ap_invoices.docs[0]["hpp_adjustment"] = {"status": "applying", "at": datetime.now(timezone.utc)}
    res = run(rp.post_ap_invoice(db, inv, FIN))
    assert not res["ok"] and "sedang/sudah" in res["error"] and posting.jes == []
    assert db.rahaza_materials.docs[0]["unit_cost"] == pytest.approx(1000.0)
    db.rahaza_ap_invoices.docs[0]["hpp_adjustment"] = {"status": "failed"}
    assert run(rp.post_ap_invoice(db, inv, FIN))["ok"]
    assert db.rahaza_materials.docs[0]["unit_cost"] == pytest.approx(1271.0)


def test_faktur_pkp_ppn_dikreditkan_selisih_harga_saja_ke_hpp(posting, valued):
    db, inv = _inv_db(100, valued)
    inv.update(input_tax_treatment="kredit", freight_amount=0, total=122100)
    res = run(rp.post_ap_invoice(db, inv, FIN))
    assert res["ok"], res
    assert posting.lines() == [("1-1401", 10000.0, 0), ("1-1501", 12100.0, 0), ("2-1100", 0, 122100.0),
                               ("2-1150", 100000.0, 0)]


def test_buat_faktur_dari_gr_menyimpan_ongkir_potongan_dan_harga_faktur(monkeypatch):
    import routes.rahaza_ap_from_gr as apg
    db = fm.FakeDB()
    db.warehouse_receiving.docs.append({
        "id": "GR1", "receipt_number": "GR-1", "status": "received", "supplier_name": "PT Uji",
        "items": [{"id": "L1", "material_id": "A", "material_name": "Kain", "received_qty": 10, "unit_price": 1000}]})

    async def fin(_r):
        return FIN

    async def mapping(db_, key):
        return dict(DEFAULT_MAP.get(key, {}))

    async def num(db_):
        return "AP-T-1"
    monkeypatch.setattr(apg, "_require_finance", fin)
    monkeypatch.setattr(apg, "get_db", lambda: db)
    monkeypatch.setattr(apg, "get_mapping", mapping)
    monkeypatch.setattr(apg, "log_activity", _noop)
    monkeypatch.setattr(apg, "_gen_ap_number", num)
    ov = apg.CreateAPFromGRItem(gr_item_id="L1", invoiced_qty=10, unit_price=1100)
    inv = run(apg.create_ap_invoice_from_gr(apg.CreateAPFromGRPayload(
        gr_ids=["GR1"], items_override=[ov], freight_amount=500, invoice_discount=1000, tax_pct=10), Req()))
    # (11.000 − 1.000) × 10 % = 1.000 PPN; total 11.000 − 1.000 + 500 + 1.000 = 11.500
    assert (inv["subtotal"], inv["tax_amount"], inv["total"]) == (11000, 1000, 11500)
    assert (inv["freight_amount"], inv["invoice_discount"], inv["gl_grni_amount"]) == (500, 1000, 10000)
    assert db.warehouse_receiving.docs[0]["invoicing_lock"] is None              # klaim dilepas


# ═════════════════════════ 11a. klaim atomik faktur dari GR ═════════════════════
def test_dua_faktur_dari_gr_yang_sama_bersamaan_ditolak(monkeypatch):
    import routes.rahaza_ap_from_gr as apg
    db = fm.FakeDB()
    db.warehouse_receiving.docs.append({"id": "GR1", "status": "received", "supplier_name": "PT Uji",
                                        "invoicing_lock": "tok-lain", "invoicing_lock_at": datetime.now(timezone.utc),
                                        "items": [{"id": "L1", "received_qty": 1, "unit_price": 1}]})

    async def fin(_r):
        return FIN
    monkeypatch.setattr(apg, "_require_finance", fin)
    monkeypatch.setattr(apg, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(apg.create_ap_invoice_from_gr(apg.CreateAPFromGRPayload(gr_ids=["GR1"]), Req()))
    assert e.value.status_code == 409 and db.warehouse_receiving.docs[0]["invoicing_lock"] == "tok-lain"
    # klaim basi (proses mati > 10 menit) boleh diambil alih
    db.warehouse_receiving.docs[0]["invoicing_lock_at"] = datetime.now(timezone.utc) - timedelta(minutes=30)
    tok = run(apg._claim_grs(db, ["GR1"], "tok-baru"))
    assert tok == ["GR1"] and db.warehouse_receiving.docs[0]["invoicing_lock"] == "tok-baru"


# ═══════════════════════════ 8. Rekonsiliasi PO ══════════════════════════════
def test_rekonsiliasi_faktur_multi_po_dibagi_per_baris_dan_po_batal_tetap_tampil(monkeypatch):
    import routes.rahaza_ap_from_gr as apg
    db = fm.FakeDB()
    db.rahaza_purchase_orders.docs += [
        {"id": "PO1", "po_number": "PO-1", "status": "approved", "vendor_name": "PT Uji", "po_date": "2026-11-01",
         "items": [{"id": "p1", "material_id": "A", "qty_ordered": 10, "unit_cost": 1000}]},
        {"id": "PO2", "po_number": "PO-2", "status": "cancelled", "vendor_name": "PT Uji", "po_date": "2026-11-02",
         "items": [{"id": "p2", "material_id": "A", "qty_ordered": 5, "unit_cost": 1000}]}]
    db.warehouse_receiving.docs += [
        {"id": "G1", "po_id": "PO1", "status": "received", "items": [{"id": "L1", "po_item_id": "p1", "material_id": "A",
                                                                       "received_qty": 10, "unit_price": 1000}]},
        {"id": "G2", "po_id": "PO2", "status": "received", "items": [{"id": "L2", "po_item_id": "p2", "material_id": "A",
                                                                       "received_qty": 5, "unit_price": 1000}]}]
    db.rahaza_ap_invoices.docs.append({
        "id": "I1", "invoice_number": "AP-1", "status": "sent", "po_ids": ["PO1", "PO2"], "subtotal": 15000,
        "tax_amount": 1500, "total": 16500, "paid_amount": 3300, "items": [
            {"gr_id": "G1", "po_item_id": "p1", "material_id": "A", "qty": 10, "amount": 10000},
            {"gr_id": "G2", "po_item_id": "p2", "material_id": "A", "qty": 5, "amount": 5000}]})

    async def fin(_r):
        return FIN
    monkeypatch.setattr(apg, "_require_finance_view", fin)
    monkeypatch.setattr(apg, "get_db", lambda: db)
    dash = run(apg.three_way_match_dashboard(Req(), status=None, vendor_name=None, supplier_id=None, limit=100))
    rows = {r["po_number"]: r for r in dash["rows"]}
    assert set(rows) == {"PO-1", "PO-2"} and rows["PO-2"]["po_status"] == "cancelled"
    assert (rows["PO-1"]["total_invoiced_qty"], rows["PO-1"]["total_invoiced_value"]) == (10, 11000)
    assert (rows["PO-2"]["total_invoiced_qty"], rows["PO-2"]["total_invoiced_value"]) == (5, 5500)
    assert rows["PO-1"]["total_paid"] == 2200 and rows["PO-1"]["match_status"] == "matched"
    det = run(apg.three_way_match_detail("PO1", Req()))
    assert det["lines"][0]["invoiced_qty"] == 10                     # baris PO-2 (material sama) tidak ikut


# ═══════════════════════════ 1. harga baris PO ══════════════════════════════
def _po_env(monkeypatch, db, user):
    import routes.rahaza_po as rpo

    async def auth(_r):
        return user

    async def flags(db_, u, pos):
        return pos
    monkeypatch.setattr(rpo, "require_auth", auth)
    monkeypatch.setattr(rpo, "get_db", lambda: db)
    monkeypatch.setattr(rpo, "log_activity", _noop)
    monkeypatch.setattr(rpo, "_po_flags", flags)
    return rpo


def _po_db(status="approved"):
    db = fm.FakeDB()
    db.rahaza_purchase_orders.docs.append({
        "id": "PO1", "po_number": "PO-1", "status": status, "vendor_name": "PT Uji", "items": [
            {"id": "p1", "material_id": None, "description": "Kain", "uom": "roll", "uom_factor": 25,
             "qty_ordered": 100, "qty_received": 0, "unit_cost": 1000, "unit_cost_input": 25000}]})
    db.warehouse_receiving.docs.append({"id": "G1", "po_id": "PO1", "status": "draft",
                                        "items": [{"id": "L1", "po_item_id": "p1", "unit_cost": 1000}]})
    return db


def test_harga_po_setelah_draf_hanya_keuangan_dengan_alasan_dan_tercatat(monkeypatch):
    db = _po_db()
    rpo = _po_env(monkeypatch, db, PROC)
    with pytest.raises(HTTPException) as e:                          # Pengadaan tidak boleh
        run(rpo.change_po_line_price("PO1", "p1", Req({"unit_cost_input": 27500, "reason": "nego"})))
    assert e.value.status_code == 403
    rpo = _po_env(monkeypatch, db, FIN)
    with pytest.raises(HTTPException) as e:                          # alasan wajib
        run(rpo.change_po_line_price("PO1", "p1", Req({"unit_cost_input": 27500})))
    assert e.value.status_code == 400 and "Alasan" in e.value.detail
    out = run(rpo.change_po_line_price("PO1", "p1", Req({"unit_cost_input": 27500, "reason": "harga naik"})))
    it = out["items"][0]
    assert it["unit_cost"] == 1100 and it["unit_cost_input"] == 27500 and out["total_value"] == 110000
    ch = db.rahaza_purchase_orders.docs[0]["price_changes"][0]
    assert (ch["old_unit_cost"], ch["new_unit_cost"], ch["reason"], ch["by_name"]) == (1000, 1100, "harga naik",
                                                                                       "Keuangan Uji")
    assert db.warehouse_receiving.docs[0]["items"][0]["unit_cost"] == 1100        # GR draf ikut


def test_harga_po_draf_lewat_edit_pengadaan_bukan_jalur_keuangan(monkeypatch):
    db = _po_db(status="draft")
    rpo = _po_env(monkeypatch, db, FIN)
    with pytest.raises(HTTPException) as e:
        run(rpo.change_po_line_price("PO1", "p1", Req({"unit_cost": 1200, "reason": "x"})))
    assert e.value.status_code == 400 and "draf" in e.value.detail
    import routes.rahaza_po as rpo_mod
    assert "pending_approval" in rpo_mod.PRICE_LOCKED_STATUSES and "draft" not in rpo_mod.PRICE_LOCKED_STATUSES


# ═══════════════════════ 2 · 6 · 7 · 11c. Penerimaan Barang ═══════════════════════
def _gr_env(monkeypatch, db, user, valued_qty=0.0):
    import routes.warehouse as wh
    st = types.SimpleNamespace(adds=[], user=user)

    async def auth(_r):
        return st.user

    async def add(mid, loc, qty, **kw):
        st.adds.append((mid, loc, qty))
        return {}

    async def vonhand(db_, mid):
        return valued_qty

    async def qinfo(db_):
        return {"id": "LOC-Q", "code": "KARANTINA", "name": "Karantina"}

    async def gen(db_, coll, field, prefix, width=4, **kw):
        st.n += 1
        return f"{prefix}{st.n:0{width}d}"
    st.n = 0
    monkeypatch.setattr(wh, "require_auth", auth)
    monkeypatch.setattr(wh, "get_db", lambda: db)
    monkeypatch.setattr(wh, "log_activity", _noop)
    monkeypatch.setattr(wh, "gen_prefixed_number", gen)
    monkeypatch.setattr(wh.stock_service, "add", add)
    monkeypatch.setattr(wh.quarantine, "valued_onhand", vonhand)
    monkeypatch.setattr(wh.quarantine, "get_quarantine_location_info", qinfo)
    import routes.rahaza_po as rpo
    monkeypatch.setattr(rpo, "update_po_received_qty", _noop)
    return wh, st


def _mat_db(**mat):
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "A", "code": "A-KCG", "name": "Kancing", "type": "accessory", "unit": "pcs",
                                     "unit_cost": 1000.0, **mat})
    return db


def test_gr_ber_po_harga_selalu_dari_po_penerima_tidak_bisa_mengubah(monkeypatch, posting):
    db = _mat_db()
    db.rahaza_purchase_orders.docs.append({"id": "PO1", "po_number": "PO-1", "status": "approved", "items": [
        {"id": "p1", "material_id": "A", "qty_ordered": 10, "qty_received": 0, "unit_cost": 1000.0}]})
    db.warehouse_receiving.docs.append({"id": "GR1", "receipt_number": "GR-1", "status": "draft", "po_id": "PO1",
                                        "po_number": "PO-1", "location_id": "L", "items": []})
    wh, st = _gr_env(monkeypatch, db, WH, valued_qty=50)
    line = {"id": "L1", "material_id": "A", "po_item_id": "p1", "received_qty": 10, "unit": "pcs", "unit_price": 1500}
    saved = run(wh.update_receiving("GR1", Req({"items": [dict(line)]})))
    assert saved["items"][0]["unit_price"] == 1000 and saved["awaiting_finance_price"] is False
    out = run(wh.update_receiving("GR1", Req({"status": "received", "items": [dict(line)]})))
    assert out["status"] == "received" and out["items"][0]["unit_price"] == 1000
    assert posting.lines(mod="inventory_receive") == [("1-1402", 10000.0, 0), ("2-1150", 0, 10000.0)]


def test_gr_ber_po_harga_po_nol_menunggu_keuangan(monkeypatch, posting):
    db = _mat_db()
    db.rahaza_purchase_orders.docs.append({"id": "PO1", "po_number": "PO-1", "status": "approved", "items": [
        {"id": "p1", "material_id": "A", "qty_ordered": 10, "qty_received": 0, "unit_cost": 0}]})
    db.warehouse_receiving.docs.append({"id": "GR1", "receipt_number": "GR-1", "status": "draft", "po_id": "PO1",
                                        "po_number": "PO-1", "location_id": "L", "items": [
                                            {"id": "L1", "material_id": "A", "po_item_id": "p1", "received_qty": 5,
                                             "unit_price": 900}]})
    wh, st = _gr_env(monkeypatch, db, WH)
    with pytest.raises(HTTPException) as e:
        run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert e.value.status_code == 400 and "menunggu harga dari Keuangan" in e.value.detail and st.adds == []


def test_gr_tanpa_po_harga_hanya_keuangan(monkeypatch, posting):
    db = _mat_db()
    wh, st = _gr_env(monkeypatch, db, WH)
    gr = run(wh.create_receiving(Req({"location_id": "L", "items": [
        {"material_id": "A", "sku": "A-KCG", "received_qty": 10, "unit": "pcs", "unit_price": 1500}]})))
    assert gr["items"][0]["unit_price"] == 0 and gr["awaiting_finance_price"] is True
    assert gr["price_pending_lines"] == ["A-KCG"]
    with pytest.raises(HTTPException) as e:
        run(wh.update_receiving(gr["id"], Req({"status": "received"})))
    assert e.value.status_code == 400 and "menunggu harga dari Keuangan" in e.value.detail
    item = dict(db.warehouse_receiving.docs[0]["items"][0], unit_price=1200)
    run(wh.update_receiving(gr["id"], Req({"items": [dict(item, unit_price=999)]})))   # gudang: diabaikan
    assert db.warehouse_receiving.docs[0]["items"][0]["unit_price"] == 0
    st.user = FIN
    saved = run(wh.update_receiving(gr["id"], Req({"items": [item]})))
    assert saved["items"][0]["unit_price"] == 1200 and saved["awaiting_finance_price"] is False
    st.user = WH
    out = run(wh.update_receiving(gr["id"], Req({"status": "received"})))    # gudang mengonfirmasi
    assert out["status"] == "received" and out["items"][0]["unit_price"] == 1200


def test_gr_satuan_harus_satuan_barang_dan_dikonversi_ke_dasar(monkeypatch, posting):
    db = _mat_db(unit="kg", type="fabric", uoms=[{"code": "kg", "factor": 1, "is_base": True},
                                                 {"code": "roll", "factor": 25}])
    wh, st = _gr_env(monkeypatch, db, FIN)
    gr = run(wh.create_receiving(Req({"location_id": "L", "items": [
        {"material_id": "A", "sku": "KN", "received_qty": 2, "unit": "roll", "unit_price": 25000}]})))
    it = gr["items"][0]
    assert (it["unit"], it["received_qty"], it["unit_price"]) == ("kg", 50.0, 1000.0)
    assert (it["gr_uom"], it["gr_uom_factor"], it["received_qty_input"], it["unit_price_input"]) == ("roll", 25, 2, 25000)
    with pytest.raises(HTTPException) as e:
        run(wh.create_receiving(Req({"location_id": "L", "items": [
            {"material_id": "A", "sku": "KN", "received_qty": 2, "unit": "lusin", "unit_price": 1}]})))
    assert e.value.status_code == 400 and "bukan satuan barang" in e.value.detail


def test_stok_bernilai_nol_dinilai_harga_beli_dijurnal_koreksi(monkeypatch, posting):
    assert pc.wac_receipt_gap(10, 0, 5, 1000, 1000) == 10000
    # stok minus dijurnal apply_receipt_cost (paket gudang) — bukan di sini, supaya tidak dobel
    assert pc.wac_receipt_gap(-4, 900, 10, 1000, 1000) == 0
    assert pc.wac_receipt_gap(10, 800, 10, 1000, 900) == 0             # rata-rata biasa → tanpa jurnal
    db = _mat_db(unit_cost=0.0)
    db.warehouse_receiving.docs.append({"id": "GR1", "receipt_number": "GR-1", "status": "draft", "location_id": "L",
                                        "items": [{"id": "L1", "material_id": "A", "received_qty": 5,
                                                   "unit_price": 1000}]})
    wh, st = _gr_env(monkeypatch, db, WH, valued_qty=10)
    run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert db.rahaza_materials.docs[0]["unit_cost"] == 1000
    assert posting.lines(mod="inventory_value_gap") == [("1-1402", 10000.0, 0), ("5-1950", 0, 10000.0)]
    assert db.warehouse_receiving.docs[0]["items"][0]["wac_gap_je_number"]


def test_kapitalisasi_aset_gr_tanda_aset_tidak_hilang(monkeypatch):
    import routes.warehouse as wh
    import routes.rahaza_fixed_assets as rfa

    async def reg(db_, payload, user, code=None, extra=None):
        return {"id": "FA-ID", "name": payload["name"], "_posting_result": {"ok": True}}

    async def num(*a, **k):
        return "FA-00001"
    monkeypatch.setattr(rfa, "register_fixed_asset", reg)
    monkeypatch.setattr(wh, "gen_prefixed_number", num)
    item = {"id": "L9", "item_type": "asset", "product_name": "Mesin", "received_qty": 1, "unit_price": 3_000_000}
    run(wh._capitalize_assets_from_grn(fm.FakeDB(), "GR1", {"id": "GR1"}, [item], FIN))
    assert item["asset_id"] == "FA-ID" and item["asset_code"] == "FA-00001" and item["capitalized"] is True


# ═══════════════════ 4. pintu belakang unit_cost ditutup ═══════════════════
def test_template_excel_harga_awal_hanya_tanpa_stok_berstok_lewat_revaluasi(monkeypatch, posting):
    from core import master_fill as mf
    from core import stock_service
    db = fm.FakeDB()
    db.rahaza_materials.docs += [
        {"id": "N", "code": "N-1", "name": "Baru", "type": "accessory", "unit": "pcs", "unit_cost": 0},
        {"id": "S", "code": "S-1", "name": "Berstok", "type": "accessory", "unit": "pcs", "unit_cost": 1000}]
    onhand = {"N": 0.0, "S": 10.0}

    async def get_onhand(mid, db=None):
        return onhand.get(mid, 0.0)

    async def vonhand(db_, mid):
        return onhand.get(mid, 0.0)

    async def gen(*a, **k):
        return "RVL-1"
    monkeypatch.setattr(stock_service, "get_onhand", get_onhand)
    monkeypatch.setattr(qmod, "valued_onhand", vonhand)
    import utils.counters as uc
    monkeypatch.setattr(uc, "gen_prefixed_number", gen)
    mats = [{"code": "N-1", "base_unit": "pcs", "buy_unit": "pcs", "pack_size": 1, "unit_cost": 500.0, "unit_cost_before": 0},
            {"code": "S-1", "base_unit": "pcs", "buy_unit": "pcs", "pack_size": 1, "unit_cost": 1200.0, "unit_cost_before": 1000}]
    rep = {}
    run(mf.apply_materials(db, copy.deepcopy(mats), FIN, report=rep))
    by = {m["id"]: m for m in db.rahaza_materials.docs}
    assert by["N"]["unit_cost"] == 500.0 and by["S"]["unit_cost"] == 1000      # berstok tidak ditimpa
    assert rep["price_opening"] == ["N-1"] and rep["price_skipped"][0]["code"] == "S-1"
    h = db.rahaza_material_cost_history.docs[0]
    assert h["material_id"] == "N" and h["source"] == "opening" and h["new_unit_cost"] == 500
    rep = {}
    run(mf.apply_materials(db, copy.deepcopy(mats[1:]), FIN, revaluation_reason="harga awal owner", report=rep))
    assert db.rahaza_materials.docs[1]["unit_cost"] == 1200 and rep["price_revalued"][0]["code"] == "S-1"
    assert posting.lines(mod="inventory_revaluation") == [("1-1402", 2000.0, 0), ("5-1950", 0, 2000.0)]


def test_impor_data_harga_barang_berstok_ditolak_dan_riwayat_ber_material_id(monkeypatch):
    import routes.data_transfer as dt
    from core import stock_service
    db = fm.FakeDB()

    async def get_onhand(mid, db=None):
        return {"S": 4.0}.get(mid, 0.0)
    monkeypatch.setattr(stock_service, "get_onhand", get_onhand)
    berstok = {"id": "S", "code": "S-1", "unit_cost": 1000}
    err = run(dt._material_cost_guard(db, {"code": "S-1", "unit_cost": 1500}, berstok))
    assert "berstok 4" in err and "Set HPP" in err
    assert run(dt._material_cost_guard(db, {"code": "S-1", "unit_cost": 1000}, berstok)) is None   # sama
    assert run(dt._material_cost_guard(db, {"code": "S-1"}, berstok)) is None                        # kosong
    assert run(dt._material_cost_guard(db, {"code": "N-1", "unit_cost": 9}, {"id": "N", "unit_cost": 0})) is None
    run(dt._record_material_cost(db, {"code": "N-1", "unit_cost": 9}, {"id": "N", "unit_cost": 0}, FIN))
    assert db.rahaza_material_cost_history.docs[0]["material_id"] == "N"


def test_penerimaan_manual_harga_hanya_keuangan(monkeypatch):
    import routes.rahaza_inventory_stock as ris
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "A", "code": "A-1", "type": "accessory", "unit": "pcs", "unit_cost": 1000})

    async def wh_user(_r):
        return WH

    async def yes(db_, lid):
        return True
    monkeypatch.setattr(ris, "_require_admin", wh_user)
    monkeypatch.setattr(ris, "get_db", lambda: db)
    monkeypatch.setattr(ris.location_resolver, "location_exists", yes)
    with pytest.raises(HTTPException) as e:
        run(ris.material_receive(Req({"material_id": "A", "location_id": "L", "qty": 5, "unit_cost": 1200})))
    assert e.value.status_code == 403 and "Keuangan" in e.value.detail


# ═══════════════════════ 5. satuan dasar dikunci ═══════════════════════
def test_ganti_satuan_dasar_ditolak_selama_dokumen_terbuka(monkeypatch, array_paths):
    db = _mat_db()
    db.rahaza_purchase_orders.docs.append({"id": "PO1", "po_number": "PO-9", "status": "approved", "items": [
        {"material_id": "A", "qty_ordered": 10, "qty_received": 4}]})
    db.warehouse_receiving.docs.append({"id": "G1", "receipt_number": "GR-9", "status": "draft",
                                        "items": [{"material_id": "A"}]})
    db.rahaza_supplier_price_lists.docs.append({"id": "pl", "material_id": "A", "is_active": True,
                                                "supplier_name": "PT Uji"})
    db.wh_quarantine_items.docs.append({"id": "q1", "material_id": "A", "status": "open", "remaining_qty": 2})
    mat = db.rahaza_materials.docs[0]
    docs = run(pg.check_base_unit_change(db, mat, "lusin"))
    assert [d["type"] for d in docs] == ["po", "gr", "price_list", "quarantine"]
    assert run(pg.check_base_unit_change(db, mat, "pcs")) == []                    # satuan sama
    msg = pg.open_documents_message(mat, "lusin", docs)
    assert "PO PO-9" in msg and "Penerimaan barang GR-9" in msg and "Karantina" in msg
    import routes.rahaza_inventory_materials as rim

    async def admin(_r):
        return FIN
    monkeypatch.setattr(rim, "_require_admin", admin)
    monkeypatch.setattr(rim, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(rim.update_material("A", Req({"unit": "kg"})))
    assert e.value.status_code == 409 and "dokumen terbuka" in e.value.detail
    prev = run(rim.rebase_material_uom("A", Req({"new_base_uom": "lusin", "factor": 0.0833, "preview": True})))
    assert len(prev["open_documents"]) == 4 and prev["blocked_reason"]
    with pytest.raises(HTTPException) as e:
        run(rim.rebase_material_uom("A", Req({"new_base_uom": "lusin", "factor": 0.0833})))
    assert e.value.status_code == 409
    # PO yang sudah diterima penuh & dokumen lain selesai → boleh
    db.rahaza_purchase_orders.docs[0]["items"][0]["qty_received"] = 10
    db.warehouse_receiving.docs[0]["status"] = "received"
    db.rahaza_supplier_price_lists.docs[0]["is_active"] = False
    db.wh_quarantine_items.docs[0]["status"] = "closed"
    assert run(pg.check_base_unit_change(db, mat, "lusin")) == []


# ═══════════════════ 9. diterima dengan diskon: stok = buku besar ═══════════════════
def test_potongan_melebihi_nilai_stok_sisanya_ke_5_1900(valued):
    db = _mat_db()
    valued["A"] = 10
    ab = run(pc.absorb_value_change(db, "A", -15000, actor=FIN, source="accept_discount"))
    assert ab["to_inventory"] == -10000 and ab["to_ppv"] == -5000 and db.rahaza_materials.docs[0]["unit_cost"] == 0
    lines = pr.plan_discount_valued(10, 2500, 1000, billed=False, absorbed=True, kind="aksesoris",
                                    inventory_amount=10000)
    assert sorted((ln["role"], ln["debit"], ln["credit"]) for ln in lines) == [
        ("grni", 15000, 0), ("inventory", 0, 10000), ("price_variance", 0, 5000)]
    # setengah barang sudah terpakai → hanya separuh potongan menurunkan stok
    db2 = _mat_db()
    valued["A"] = 10
    ab = run(pc.absorb_value_change(db2, "A", -4000, ratio=pc.on_hand_ratio(20, 10), actor=FIN))
    assert ab["to_inventory"] == -2000 and ab["to_ppv"] == -2000
    assert db2.rahaza_materials.docs[0]["unit_cost"] == 800


def test_retur_kirim_dan_nota_debit_memegang_kunci_karantina(monkeypatch):
    import routes.rahaza_purchase_returns as rpr
    db = fm.FakeDB()
    db.wh_quarantine_items.docs.append({"id": "q1", "material_id": "A", "status": "open", "remaining_qty": 5,
                                        "disposition_lock": "tok-lain", "disposition_lock_at": datetime.now(timezone.utc)})
    with pytest.raises(HTTPException) as e:
        run(rpr._claim_quarantine_lines(db, [{"source": "quarantine", "quarantine_item_id": "q1"}], {"id": "u"}))
    assert e.value.status_code == 409
    db.wh_quarantine_items.docs[0]["disposition_lock"] = None
    toks = run(rpr._claim_quarantine_lines(db, [{"source": "quarantine", "quarantine_item_id": "q1"},
                                                 {"source": "stock", "material_id": "A"}], {"id": "u"}))
    assert len(toks) == 1 and db.wh_quarantine_items.docs[0]["disposition_lock"] == toks[0][1]
    run(rpr._release_quarantine_lines(db, toks))
    assert db.wh_quarantine_items.docs[0]["disposition_lock"] is None
    import inspect
    assert "_claim_quarantine_lines" in inspect.getsource(rpr.send_purchase_return)
    assert "_claim_quarantine_lines" in inspect.getsource(rpr.issue_debit_note)


# ═══════════════════════════ 10. Belanja Mingguan ═══════════════════════════
def test_belanja_mingguan_po_lama_terbuka_mengurangi_kekurangan(monkeypatch, array_paths):
    from core import shopping_list as sl
    from core import stock_service
    db = fm.FakeDB()
    lama = datetime.now(timezone.utc) - timedelta(days=21)
    db.rahaza_materials.docs += [
        {"id": "A", "code": "A-1", "name": "Kancing", "type": "accessory", "unit": "pcs", "active": True,
         "min_stock_qty": 100, "unit_cost": 1000},
        {"id": "B", "code": "B-1", "name": "Label", "type": "accessory", "unit": "pcs", "active": True,
         "min_stock_qty": 100, "unit_cost": 1000},
        {"id": "C", "code": "C-1", "name": "Tali", "type": "accessory", "unit": "pcs", "active": True,
         "min_stock_qty": 100, "unit_cost": 1000}]
    db.rahaza_purchase_orders.docs += [
        {"id": "PO1", "po_number": "PO-LAMA", "status": "approved", "created_at": lama,
         "items": [{"material_id": "A", "qty_ordered": 60, "qty_received": 10}]},          # sisa 50
        {"id": "PO2", "po_number": "PO-PENUH", "status": "partially_received", "created_at": lama,
         "items": [{"material_id": "B", "qty_ordered": 200, "qty_received": 100}]}]       # sisa 100 ≥ kurang
    db.dewi_procurement_requests.docs.append({"id": "PR1", "request_number": "PR-1", "status": "in_procurement",
                                              "linked_po_id": "PO9", "created_at": lama,
                                              "items": [{"material_id": "C", "qty": 80}]})  # sudah jadi PO
    async def onhand_map(ids=None, db=None):
        return {"A": 20.0, "B": 20.0, "C": 20.0}
    monkeypatch.setattr(stock_service, "onhand_map", onhand_map)
    out = run(sl.weekly(db))
    rows = {r["code"]: r for r in out["rows"]}
    a = rows["A-1"]
    assert (a["shortage_gross"], a["incoming_po_qty"], a["shortage"], a["already_requested"]) == (80, 50, 30, False)
    assert "dikurangi sisa PO terbuka 50" in a["qty_note"] and a["qty_buy"] == 30
    assert rows["B-1"]["already_requested"] is True and rows["B-1"]["pr"]["number"] == "PO-PENUH"
    assert rows["C-1"]["already_requested"] is False and rows["C-1"]["shortage"] == 80   # PR ber-PO tidak dobel
    assert out["summary"]["need_buy"] == 2


# ═════════════════════════════ migrasi data ═════════════════════════════
def _migrasi():
    p = Path(BACKEND) / "scripts" / "migrations" / "2026_11_06_pengadaan_riwayat_aset.py"
    spec = importlib.util.spec_from_file_location("pengadaan_t2_mig", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_riwayat_material_id_dan_tautan_aset_gr_idempoten():
    mig = _migrasi()
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "M1", "code": "A-BIS"})
    at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    db.rahaza_material_cost_history.docs += [
        {"id": "h1", "material_code": "A-BIS", "unit_cost": 1200, "before": 1000, "source": "template_harga_owner",
         "by": "Owner", "at": at},
        {"id": "h2", "material_code": "HILANG", "unit_cost": 5, "before": 0, "source": "template_harga_owner"},
        {"id": "h3", "material_id": "M1", "old_unit_cost": 1, "new_unit_cost": 2}]
    db.warehouse_receiving.docs.append({"id": "GR1", "items": [
        {"id": "L1", "item_type": "asset", "received_qty": 1},
        {"id": "L2", "material_id": "M1", "received_qty": 1}]})
    db.rahaza_fixed_assets.docs.append({"id": "FA1", "code": "FA-00001", "grn_id": "GR1", "grn_item_id": "L1"})
    prev = run(mig.migrate(db, apply=False))
    assert prev == {"history_rows": 2, "history_fixed": 1, "history_unknown_code": 1, "gr_docs": 1, "gr_lines_linked": 1}
    assert "material_id" not in db.rahaza_material_cost_history.docs[0]                 # pratinjau tidak menulis
    run(mig.migrate(db, apply=True))
    h = db.rahaza_material_cost_history.docs[0]
    assert (h["material_id"], h["old_unit_cost"], h["new_unit_cost"], h["created_at"]) == ("M1", 1000, 1200, at)
    li = db.warehouse_receiving.docs[0]["items"][0]
    assert (li["asset_id"], li["asset_code"], li["capitalized"]) == ("FA1", "FA-00001", True)
    again = run(mig.migrate(db, apply=True))
    assert again["history_fixed"] == 0 and again["gr_lines_linked"] == 0
