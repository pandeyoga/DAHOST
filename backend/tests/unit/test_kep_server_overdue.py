"""Keputusan owner 8 Nov 2026 (butir 2): lewat jatuh tempo = jatuh tempo SEBELUM hari ini (WIB).

Laporan Eksekutif (`ar_overdue_rp`) dan laporan piutang lewat jatuh tempo untuk hapus buku
(`/api/rahaza/ar-invoices/overdue-report`) dulu menghitung faktur yang jatuh tempo HARI INI sebagai terlambat
(6 faktur / 111 jt vs 5 / 88,4 jt di Umur piutang & Ringkasan Bisnis). Hermetik: Mongo palsu.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import _fake_mongo as fm  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

import routes.dewi_executive_report as er  # noqa: E402
import routes.rahaza_finance as rf  # noqa: E402

TODAY = date(2026, 11, 8)


def _invoices():
    return [
        {"id": "a", "invoice_number": "AR-HARI-INI", "status": "issued", "due_date": "2026-11-08", "balance": 22_608_000,
         "total": 22_608_000},
        {"id": "b", "invoice_number": "AR-KEMARIN", "status": "issued", "due_date": "2026-11-07", "balance": 10_000_000,
         "total": 10_000_000},
        {"id": "c", "invoice_number": "AR-LAMA", "status": "overdue", "due_date": "2026-09-01", "balance": 5_000_000,
         "total": 5_000_000},
        {"id": "d", "invoice_number": "AR-BESOK", "status": "issued", "due_date": "2026-11-09", "balance": 1_000_000,
         "total": 1_000_000},
        {"id": "e", "invoice_number": "AR-LUNAS", "status": "paid", "due_date": "2026-10-01", "balance": 0, "total": 9},
    ]


def test_laporan_eksekutif_tidak_menghitung_jatuh_tempo_hari_ini():
    q = er.ar_overdue_match(TODAY.isoformat())
    hit = [i["invoice_number"] for i in _invoices() if fm.match(i, q)]
    assert hit == ["AR-KEMARIN", "AR-LAMA"]
    assert q["due_date"] == {"$lt": "2026-11-08"}


def _overdue_report(monkeypatch, days):
    db = FakeDB()
    db.rahaza_ar_invoices.docs = _invoices()

    async def _fin(_req):
        return {"id": "u", "role": "accounting"}
    monkeypatch.setattr(rf, "_require_fin", _fin)
    monkeypatch.setattr(rf, "get_db", lambda: db)
    monkeypatch.setattr(rf, "today_wib", lambda: TODAY)
    return asyncio.run(rf.get_overdue_ar_report(object(), days=days))


def test_laporan_hapus_buku_days_0_hanya_yang_terlambat(monkeypatch):
    out = _overdue_report(monkeypatch, 0)
    nums = [i["invoice_number"] for i in out["invoices"]]
    assert "AR-HARI-INI" not in nums and "AR-BESOK" not in nums
    assert nums == ["AR-LAMA", "AR-KEMARIN"]          # terlama dulu
    assert out["summary"]["total_overdue_invoices"] == 2
    assert out["summary"]["total_overdue_amount"] == 15_000_000
    assert min(i["overdue_days"] for i in out["invoices"]) >= 1


def test_laporan_hapus_buku_ambang_hari_tetap_berlaku(monkeypatch):
    out = _overdue_report(monkeypatch, 30)
    assert [i["invoice_number"] for i in out["invoices"]] == ["AR-LAMA"]
    out = _overdue_report(monkeypatch, 1)
    assert len(out["invoices"]) == 2
