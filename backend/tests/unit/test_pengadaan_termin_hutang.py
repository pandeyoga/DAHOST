"""Uji unit HERMETIK — Pengadaan (owner 27 Nov 2026: "saat pembelian tidak ada penentuan termin, hutang baru muncul
… draf saya bingung").

* Termin & PPN ditentukan di PO (bawaan master pemasok, boleh diubah).
* Barang PO diterima → tagihan pemasok dibuat & disetujui otomatis (core.hutang_otomatis); galat tidak menggagalkan
  penerimaan.
Jalankan:  cd backend && python -m pytest tests/unit/test_pengadaan_termin_hutang.py -q
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

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB  # noqa: E402

GUDANG = {"id": "u-gudang", "name": "Staf Gudang", "role": "staff_gudang"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _tanpa_log(monkeypatch):
    import auth

    async def _log(*a, **k):
        return None
    monkeypatch.setattr(auth, "log_activity", _log)


# ── Termin & PPN di PO ──
def test_termin_po_isian_lalu_po_lalu_pemasok_lalu_net30():
    from routes.rahaza_po import _termin_po
    assert _termin_po({"payment_terms": "net14"}, {}, {"payment_terms": "net60"}) == \
        {"payment_terms": "net14", "payment_term_days": 14}
    assert _termin_po({}, {"payment_terms": "cod"}, {"payment_terms": "net60"})["payment_terms"] == "cod"
    assert _termin_po({}, {}, {"payment_terms": "net60"}) == {"payment_terms": "net60", "payment_term_days": 60}
    assert _termin_po({}, {}, None) == {"payment_terms": "net30", "payment_term_days": 30}
    with pytest.raises(HTTPException) as e:
        _termin_po({"payment_terms": "net999"}, {}, None)
    assert e.value.status_code == 400


def test_ppn_po_bawaan_pemasok_pkp_dan_bisa_diubah():
    from routes.rahaza_po import _ppn_po
    assert _ppn_po({}, {}, True) == 11.0                     # pemasok PKP → PPN 11%
    assert _ppn_po({}, {}, False) == 0.0                     # non-PKP → tanpa PPN
    assert _ppn_po({"tax_pct": 0}, {}, True) == 0.0          # diubah di PO
    assert _ppn_po({"tax_pct": ""}, {"tax_pct": 11}, False) == 11.0
    for salah in (-1, 120, "abc"):
        with pytest.raises(HTTPException):
            _ppn_po({"tax_pct": salah}, {}, True)


def test_nilai_po_subtotal_ppn_total():
    from routes.rahaza_po import _nilai_po
    n = _nilai_po([{"qty_ordered": 1000, "unit_cost": 18000}], 11)
    assert n == {"total_value": 18_000_000, "tax_pct": 11.0, "tax_amount": 1_980_000, "grand_total": 19_980_000}


# ── Hutang otomatis saat barang diterima ──
def _db_gr(**gr_kw):
    db = FakeDB()
    db.rahaza_purchase_orders.docs = [{"id": "po1", "po_number": "PO-1", "tax_pct": 11, "payment_terms": "net14",
                                       "vendor_name": "Alvino Tex"}]
    db.warehouse_receiving.docs = [{
        "id": "gr1", "receipt_number": "GR-1", "po_id": "po1", "po_number": "PO-1", "status": "received",
        "supplier_name": "Alvino Tex", "received_at": "2026-11-26T03:00:00",
        "items": [{"id": "l1", "material_id": "m1", "received_qty": 1000, "rejected_qty": 0, "unit_cost": 18000}],
        **gr_kw}]
    return db


def test_penerimaan_po_langsung_jadi_tagihan_disetujui(monkeypatch):
    from core import hutang_otomatis as ho
    import routes.rahaza_ap_from_gr as apgr
    import routes.rahaza_posting as rp
    tangkap = {}

    async def _buat(db, payload, user):
        tangkap["payload"] = payload
        doc = {"id": "ap1", "invoice_number": "AP-1", "status": "draft", "total": 19_980_000}
        await db.rahaza_ap_invoices.insert_one(dict(doc))
        return doc

    async def _post(db, inv, user):
        tangkap["post_status"] = inv["status"]
        return {"ok": True, "je_id": "je1", "je_number": "JE-1"}
    monkeypatch.setattr(apgr, "_create_ap_invoice_from_gr_locked", _buat)
    monkeypatch.setattr(rp, "post_ap_invoice", _post)
    db = _db_gr()
    out = run(ho.tagih_penerimaan(db, "gr1", GUDANG))
    assert out["ok"] and out["invoice_number"] == "AP-1"
    p = tangkap["payload"]
    assert p.tax_pct == 11.0 and p.payment_terms == "net14" and p.issue_date == "2026-11-26" and p.gr_ids == ["gr1"]
    inv = db.rahaza_ap_invoices.docs[0]
    assert inv["status"] == "sent" and inv["auto_from_gr"] is True and tangkap["post_status"] == "sent"
    gr = db.warehouse_receiving.docs[0]
    assert gr["ap_auto_invoice_number"] == "AP-1" and not gr.get("invoicing_lock")


def test_galat_tagihan_tidak_menggagalkan_penerimaan(monkeypatch):
    from core import hutang_otomatis as ho
    import routes.rahaza_ap_from_gr as apgr

    async def _buat(db, payload, user):
        raise HTTPException(400, "Harga baris 0")
    monkeypatch.setattr(apgr, "_create_ap_invoice_from_gr_locked", _buat)
    db = _db_gr()
    out = run(ho.tagih_penerimaan(db, "gr1", GUDANG))           # tidak melempar
    assert out["ok"] is False and "Harga baris 0" in out["error"]
    gr = db.warehouse_receiving.docs[0]
    assert gr["ap_auto_error"] == "Harga baris 0" and not gr.get("invoicing_lock")
    assert db.rahaza_ap_invoices.docs == []


def test_penerimaan_tanpa_po_atau_sudah_ditagih_dilewati(monkeypatch):
    from core import hutang_otomatis as ho
    import routes.rahaza_ap_from_gr as apgr

    async def _buat(db, payload, user):
        raise AssertionError("tidak boleh membuat tagihan")
    monkeypatch.setattr(apgr, "_create_ap_invoice_from_gr_locked", _buat)
    assert "lewati" in run(ho.tagih_penerimaan(_db_gr(po_id=None), "gr1", GUDANG))
    assert "lewati" in run(ho.tagih_penerimaan(_db_gr(ap_invoice_id="ap-lama"), "gr1", GUDANG))
    assert "lewati" in run(ho.tagih_penerimaan(_db_gr(status="draft"), "gr1", GUDANG))
