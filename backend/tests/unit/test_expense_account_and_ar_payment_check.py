"""Pengeluaran memilih akun beban yang sah; pembayaran faktur penjualan menolak rekening yang salah (2026-11-04).

Uji tugas lewat layar: form Pengeluaran tidak punya pilihan akun, jadi "listrik" terjurnal ke 6-2900
Beban Umum padahal ada 6-2200 Listrik & Air Kantor. Owner: akun beban WAJIB dipilih di layar. Server
mengecek akun yang dikirim (ada, aktif, bukan header, bertipe beban/HPP) — kosong tetap diterima untuk
pemanggil API lama. Rekening pembayaran (pengeluaran & faktur penjualan) yang tidak ada/nonaktif ditolak
sebelum dokumen berubah, sama seperti pembayaran faktur supplier.
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
import routes.rahaza_finance as rf  # noqa: E402

USER = {"id": "u1", "name": "Uji", "role": "superadmin"}


def run(c):
    return asyncio.run(c)


def _env(monkeypatch):
    db = FakeDB()
    db.rahaza_coa_accounts.docs = [
        {"code": "6-2200", "name": "Listrik & Air Kantor", "type": "EXPENSE", "active": True},
        {"code": "6-2000", "name": "Beban Umum (header)", "type": "EXPENSE", "active": True, "is_group": True},
        {"code": "6-9999", "name": "Akun lama", "type": "EXPENSE", "active": False},
        {"code": "4-1100", "name": "Penjualan Garment", "type": "REVENUE", "active": True},
        {"code": "1-1201", "name": "Bank BCA", "type": "ASSET", "active": True},
    ]
    db.rahaza_cash_accounts.docs = [{"id": "bca", "code": "1-1201", "name": "Bank BCA", "active": True}]
    db.rahaza_ar_invoices.docs = [{"id": "ar1", "invoice_number": "AR-UJI-1", "status": "issued",
                                   "total": 1_000_000, "paid_amount": 0, "balance": 1_000_000}]
    posted = []

    async def _auth(*_a, **_k):
        return dict(USER)

    async def _post(db_, doc, user):
        posted.append(doc)
        return {"ok": True, "je_id": "je1", "je_number": "JE-UJI-1"}
    monkeypatch.setattr(rf, "get_db", lambda: db)
    monkeypatch.setattr(rf, "_require_fin", _auth)
    monkeypatch.setattr(rf, "post_expense", _post)
    return db, posted


def test_pengeluaran_menyimpan_akun_beban_pilihan_dan_menjurnalnya(monkeypatch):
    db, posted = _env(monkeypatch)
    out = run(rf.create_expense(FakeRequest({"amount": 2_350_000, "gl_debit_code": "6-2200", "account_id": "bca",
                                             "category": "listrik", "description": "Listrik kantor"})))
    assert out["gl_debit_code"] == "6-2200" and posted[0]["gl_debit_code"] == "6-2200"


@pytest.mark.parametrize("code,pesan", [("9-9999", "tidak ditemukan"), ("6-9999", "non-aktif"),
                                        ("6-2000", "header"), ("4-1100", "REVENUE"), ("1-1201", "ASSET")])
def test_pengeluaran_menolak_akun_yang_bukan_beban(monkeypatch, code, pesan):
    db, posted = _env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(rf.create_expense(FakeRequest({"amount": 100_000, "gl_debit_code": code, "account_id": "bca"})))
    assert e.value.status_code == 400 and pesan in e.value.detail
    assert db.rahaza_expenses.docs == [] and posted == []


def test_pengeluaran_menolak_rekening_pembayar_yang_tidak_ada(monkeypatch):
    db, posted = _env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(rf.create_expense(FakeRequest({"amount": 100_000, "gl_debit_code": "6-2200", "account_id": "salah"})))
    assert e.value.status_code == 400 and "Rekening" in e.value.detail
    assert db.rahaza_expenses.docs == [] and posted == []


def test_pembayaran_faktur_penjualan_menolak_rekening_yang_tidak_ada(monkeypatch):
    db, _ = _env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(rf.record_ar_payment("ar1", FakeRequest({"amount": 500_000, "account_id": "kas-kecil-salah"})))
    assert e.value.status_code == 400 and "Rekening" in e.value.detail
    inv = db.rahaza_ar_invoices.docs[0]
    assert inv["paid_amount"] == 0 and inv["balance"] == 1_000_000 and inv["status"] == "issued"
