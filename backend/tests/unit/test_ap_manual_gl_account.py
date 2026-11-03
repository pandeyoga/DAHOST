"""Faktur supplier manual (`POST /api/rahaza/ap-invoices`) boleh memilih akun debit (2026-11-03).

Dulu semua faktur manual dijurnal ke `ap_invoice.debit_expense_default` (6-2900 Beban Umum), jadi
ongkos jahit / kain yang ditagih tanpa GR salah masuk beban umum. Kini `gl_debit_code` diterima,
dicek (aktif, bukan grup, tipe beban/HPP/aset), disimpan, dan dipakai `post_ap_invoice`.
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
import routes.rahaza_ap_from_gr as gr  # noqa: E402
import routes.rahaza_finance as rf  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402

USER = {"id": "u1", "name": "Uji", "role": "superadmin"}
BODY = {"vendor_name": "Bu Lilis (CMT)", "items": [{"description": "Ongkos jahit 500 pcs", "qty": 500, "price": 5_500}],
        "tax_pct": 0, "issue_date": "2026-10-03", "due_date": "2026-10-10"}


def run(c):
    return asyncio.run(c)


def _db():
    db = FakeDB()
    db.company_settings.docs = [{"id": "cs", "type": "general", "tax_profile": {"pkp": False}}]
    db.rahaza_coa_accounts.docs = [
        {"code": "5-2200", "name": "Biaya Vendor CMT – Jahit", "type": "COGS", "active": True},
        {"code": "5-2000", "name": "HPP Tenaga Kerja Langsung", "type": "COGS", "active": True, "is_group": True},
        {"code": "4-1100", "name": "Penjualan Garment", "type": "REVENUE", "active": True},
        {"code": "6-9999", "name": "Akun lama", "type": "EXPENSE", "active": False},
    ]
    return db


def _env(monkeypatch, db):
    async def _auth(*_a, **_k):
        return dict(USER)

    async def _num(*_a, **_k):
        return "AP-UJI-0001"

    async def _no_warn(*_a, **_k):
        return {"warning": None, "grs": [], "amount": 0.0}
    monkeypatch.setattr(rf, "get_db", lambda: db)
    monkeypatch.setattr(rf, "_require_fin", _auth)
    monkeypatch.setattr(rf, "_gen_number", _num)
    monkeypatch.setattr(gr, "uninvoiced_gr_warning", _no_warn)


def test_faktur_manual_menyimpan_akun_debit_dan_jurnal_memakainya(monkeypatch):
    db = _db()
    _env(monkeypatch, db)
    inv = run(rf.create_ap(FakeRequest({**BODY, "gl_debit_code": "5-2200"})))
    assert inv["gl_debit_code"] == "5-2200" and inv["total"] == 2_750_000

    calls = []

    async def fake_create(db_, je_date, memo, source_module, source_ref, lines, user, **k):
        calls.append(lines)
        return {"ok": True, "je_id": "je1", "je_number": "JE-1"}

    async def fake_map(db_, ev):
        return {"credit_ap": "2-1100", "debit_expense_default": "6-2900"}

    async def _none(*_a, **_k):
        return None
    monkeypatch.setattr(rp, "_create_posted_je", fake_create)
    monkeypatch.setattr(rp, "get_mapping", fake_map)
    monkeypatch.setattr(rp, "_find_existing_je", _none)
    monkeypatch.setattr(rp, "_save_source_posting_result", _none)
    res = run(rp.post_ap_invoice(db, db.rahaza_ap_invoices.docs[0], dict(USER)))
    assert res["ok"], res
    dr = {ln["account_code"]: ln["debit"] for ln in calls[0] if ln["debit"]}
    assert dr == {"5-2200": 2_750_000}                       # bukan 6-2900 Beban Umum


def test_faktur_manual_tanpa_akun_tetap_bawaan(monkeypatch):
    db = _db()
    _env(monkeypatch, db)
    inv = run(rf.create_ap(FakeRequest(dict(BODY))))
    assert inv["gl_debit_code"] is None


@pytest.mark.parametrize("code,pesan", [("9-9999", "tidak ditemukan"), ("6-9999", "non-aktif"),
                                        ("5-2000", "header"), ("4-1100", "REVENUE")])
def test_faktur_manual_menolak_akun_yang_tidak_boleh(monkeypatch, code, pesan):
    db = _db()
    _env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(rf.create_ap(FakeRequest({**BODY, "gl_debit_code": code})))
    assert e.value.status_code == 400 and pesan in e.value.detail
    assert db.rahaza_ap_invoices.docs == []
