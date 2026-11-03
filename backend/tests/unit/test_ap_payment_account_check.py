"""Pembayaran faktur supplier menolak rekening yang tidak ada / nonaktif (2026-11-03, uji tugas).

Dulu `account_id` yang salah (mis. UUID salah ketik di layar lama "Diskon Pembelian") diam-diam
diabaikan: hutang tetap berkurang, mutasi kas tidak dibuat, dan jurnal jatuh ke rekening bawaan
profil posting. Kini ditolak SEBELUM hutang berkurang.
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
INV = {"id": "ap1", "invoice_number": "AP-UJI-1", "status": "sent", "total": 1_000_000,
       "paid_amount": 0, "balance": 1_000_000, "vendor_name": "CMT Uji"}


def run(c):
    return asyncio.run(c)


def _env(monkeypatch):
    db = FakeDB()
    db.rahaza_ap_invoices.docs = [dict(INV)]
    db.rahaza_cash_accounts.docs = [
        {"id": "bca", "code": "1-1201", "name": "Bank BCA", "active": True},
        {"id": "lama", "code": "1-1202", "name": "Bank Lama", "active": False},
    ]

    async def _auth(*_a, **_k):
        return dict(USER)
    monkeypatch.setattr(rf, "get_db", lambda: db)
    monkeypatch.setattr(rf, "_require_fin", _auth)
    return db


@pytest.mark.parametrize("account_id", ["29fe0da5-salah-ketik", "lama"])
def test_rekening_tidak_ada_atau_nonaktif_ditolak_sebelum_hutang_berkurang(monkeypatch, account_id):
    db = _env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(rf.record_ap_payment("ap1", FakeRequest({"amount": 500_000, "account_id": account_id})))
    assert e.value.status_code == 400 and "Rekening" in e.value.detail
    inv = db.rahaza_ap_invoices.docs[0]
    assert inv["paid_amount"] == 0 and inv["balance"] == 1_000_000 and inv["status"] == "sent"
    assert db.rahaza_ap_payments.docs == []
