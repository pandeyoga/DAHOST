"""Uji unit HERMETIK — uang muka ke pemasok (CBD / DP di PO), owner 27 Nov 2026: "bagaimana jika pembayarannya CBD?".
Jalankan:  cd backend && python -m pytest tests/unit/test_uang_muka_pemasok.py -q
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

FIN = {"id": "u-fin", "name": "Keuangan", "role": "owner"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _tanpa_log(monkeypatch):
    import auth

    async def _log(*a, **k):
        return None
    monkeypatch.setattr(auth, "log_activity", _log)


@pytest.fixture
def jurnal(monkeypatch):
    """Jurnal dicatat di daftar (fungsi jurnal pusat diuji terpisah)."""
    from core import uang_muka_pemasok as um
    catat = []

    async def _j(db, d, memo, sumber, ref, lines, user, entity):
        catat.append({"sumber": sumber, "ref": ref, "date": d.isoformat(), "entity": entity,
                      "lines": [(ln["account_code"], ln["debit"], ln["credit"]) for ln in lines]})
        return {"ok": True, "je_id": f"je{len(catat)}", "je_number": f"JE-{len(catat)}"}
    monkeypatch.setattr(um, "_jurnal", _j)
    return catat


def _db(status="approved"):
    db = FakeDB()
    db.rahaza_purchase_orders.docs = [{"id": "po1", "po_number": "PO-1", "status": status, "entity": "DA",
                                       "supplier_name": "Alvino Tex", "total_value": 18_000_000, "tax_pct": 11,
                                       "grand_total": 19_980_000, "payment_terms": "cbd"}]
    db.rahaza_cash_accounts.docs = [{"id": "acc1", "name": "BCA DA", "gl_account_code": "1-1219", "entity": "DA",
                                     "active": True},
                                    {"id": "acc-smu", "name": "BCA Sukma", "gl_account_code": "1-1213", "entity": "SMU",
                                     "active": True}]
    return db


def test_bayar_di_muka_mencatat_uang_muka_kas_dan_jurnal(jurnal):
    from core import uang_muka_pemasok as um
    db = _db()
    adv = run(um.bayar(db, "po1", {"amount": 10_000_000, "cash_account_id": "acc1", "date": "2026-11-27"}, FIN))
    assert adv["status"] == "aktif" and adv["amount"] == 10_000_000 and um.sisa(adv) == 10_000_000
    assert db.rahaza_purchase_orders.docs[0]["uang_muka_total"] == 10_000_000
    mv = db.rahaza_cash_movements.docs[0]
    assert mv["direction"] == "out" and mv["amount"] == 10_000_000 and mv["account_id"] == "acc1"
    assert jurnal[0]["lines"] == [("1-1630", 10_000_000, 0), ("1-1219", 0, 10_000_000)]
    assert adv["gl_je_number"] == "JE-1"


def test_bayar_di_muka_ditolak_melebihi_nilai_po_atau_po_belum_disetujui(jurnal):
    from core import uang_muka_pemasok as um
    db = _db()
    run(um.bayar(db, "po1", {"amount": 19_000_000, "cash_account_id": "acc1"}, FIN))
    with pytest.raises(HTTPException) as e:
        run(um.bayar(db, "po1", {"amount": 1_000_000, "cash_account_id": "acc1"}, FIN))   # 20 jt > 19,98 jt
    assert e.value.status_code == 400 and "melebihi nilai PO" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(um.bayar(_db("draft"), "po1", {"amount": 1_000, "cash_account_id": "acc1"}, FIN))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:                                               # rekening CV lain
        run(um.bayar(_db(), "po1", {"amount": 1_000, "cash_account_id": "acc-smu"}, FIN))
    assert e.value.status_code == 400


def _tagihan(db, total=19_980_000):
    db.rahaza_ap_invoices.docs = [{"id": "inv1", "invoice_number": "AP-1", "status": "sent", "total": total,
                                   "paid_amount": 0, "balance": total, "po_ids": ["po1"], "issue_date": "2026-11-28",
                                   "gl_ap_account_code": "2-1100-SUP-0002"}]


def test_tagihan_dipotong_uang_muka_sebagian(jurnal):
    from core import uang_muka_pemasok as um
    db = _db()
    run(um.bayar(db, "po1", {"amount": 10_000_000, "cash_account_id": "acc1"}, FIN))
    _tagihan(db)
    out = run(um.terapkan_ke_tagihan(db, "inv1", FIN))
    assert out["ok"] and out["dipakai"] == 10_000_000
    inv = db.rahaza_ap_invoices.docs[0]
    assert inv["paid_amount"] == 10_000_000 and inv["status"] == "partial_paid" and inv["balance"] == 9_980_000
    pay = db.rahaza_ap_payments.docs[0]
    assert pay["source"] == "uang_muka" and pay["amount"] == 10_000_000 and pay["date"] == "2026-11-28"
    assert jurnal[-1]["sumber"] == "ap_advance_apply"
    assert jurnal[-1]["lines"] == [("2-1100-SUP-0002", 10_000_000, 0), ("1-1630", 0, 10_000_000)]
    adv = db.rahaza_ap_advances.docs[0]
    assert adv["status"] == "habis" and um.sisa(adv) == 0 and adv["pemakaian"][0]["invoice_number"] == "AP-1"


def test_uang_muka_penuh_tagihan_lunas_sisa_menunggu_penerimaan_berikutnya(jurnal):
    from core import uang_muka_pemasok as um
    db = _db()
    run(um.bayar(db, "po1", {"amount": 19_980_000, "cash_account_id": "acc1"}, FIN))
    _tagihan(db, total=9_990_000)                         # barang datang setengah
    run(um.terapkan_ke_tagihan(db, "inv1", FIN))
    assert db.rahaza_ap_invoices.docs[0]["status"] == "paid"
    adv = db.rahaza_ap_advances.docs[0]
    assert adv["status"] == "aktif" and um.sisa(adv) == 9_990_000      # sisa untuk penerimaan berikutnya
    assert run(um.sisa_po(db, "po1")) == 9_990_000


def test_kembalikan_sisa_dan_batal_hanya_bila_belum_terpakai(jurnal):
    from core import uang_muka_pemasok as um
    db = _db()
    adv = run(um.bayar(db, "po1", {"amount": 5_000_000, "cash_account_id": "acc1"}, FIN))
    run(um.kembalikan(db, adv["id"], {"amount": 2_000_000, "cash_account_id": "acc1"}, FIN))
    a = db.rahaza_ap_advances.docs[0]
    assert um.sisa(a) == 3_000_000 and a["dikembalikan"] == 2_000_000
    assert jurnal[-1]["lines"] == [("1-1219", 2_000_000, 0), ("1-1630", 0, 2_000_000)]
    assert db.rahaza_cash_movements.docs[-1]["direction"] == "in"
    with pytest.raises(HTTPException) as e:                # sudah dikembalikan sebagian → tidak bisa dibatalkan
        run(um.batalkan(db, adv["id"], "Salah catat nominal transfer", FIN))
    assert e.value.status_code == 409


def test_batalkan_uang_muka_salah_catat(jurnal, monkeypatch):
    from core import uang_muka_pemasok as um
    import routes.rahaza_posting as rp

    async def _void(db, sumber, ref, user, reason="", entity=None, boleh_balik=True):
        return {"ok": True, "voided": True}
    monkeypatch.setattr(rp, "_void_je_by_source", _void)
    db = _db()
    adv = run(um.bayar(db, "po1", {"amount": 5_000_000, "cash_account_id": "acc1"}, FIN))
    with pytest.raises(HTTPException):
        run(um.batalkan(db, adv["id"], "salah", FIN))       # alasan terlalu pendek
    out = run(um.batalkan(db, adv["id"], "Salah catat nominal transfer", FIN))
    assert out["status"] == "batal" and db.rahaza_cash_movements.docs == []
    assert db.rahaza_purchase_orders.docs[0]["uang_muka_total"] == 0
    assert run(um.sisa_po(db, "po1")) == 0
