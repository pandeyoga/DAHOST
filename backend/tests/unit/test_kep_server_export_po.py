"""Keputusan owner 8 Nov 2026 (butir 1, keamanan): unduhan Excel server PO produksi.

`/api/export-excel?type=production-pos` dulu mengabaikan saringan layar daftar PO (status, kata cari, jenis) dan
memuat harga jasa + upah CMT untuk SIAPA SAJA yang login. Sekarang:
* saringan = aturan yang SAMA dengan `GET /production-pos` (`routes.production_pos.po_list_query`);
* kolom harga hanya untuk Keuangan (`core.purchase_returns.is_finance`, gerbang harga PO yang sudah ada);
* klien maklon / vendor CMT ditolak (403).
Hermetik: Mongo palsu, tanpa jaringan.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402

import routes.operations_excel as ox  # noqa: E402
from routes.production_pos import po_list_query  # noqa: E402


class _Req:
    def __init__(self, params):
        self.query_params = params


def _db():
    db = FakeDB()
    db.production_pos.docs = [
        {"id": "p1", "po_number": "PO-INT-001", "customer_name": "Gudang FG", "business_type": "internal",
         "status": "Confirmed", "created_at": "2026-11-01"},
        {"id": "p2", "po_number": "PO-MKL-002", "customer_name": "Klien Satu", "business_type": "maklon",
         "status": "Confirmed", "created_at": "2026-11-02"},
        {"id": "p3", "po_number": "PO-MKL-003", "customer_name": "Klien Dua", "business_type": "maklon",
         "status": "Draft", "created_at": "2026-11-03"},
    ]
    db.po_items.docs = [
        {"id": f"i{n}", "po_id": f"p{n}", "sku": f"SKU{n}", "product_name": "Kaos", "size": "M", "color": "Hitam",
         "qty": 10 * n, "selling_price_snapshot": 50000, "cmt_price_snapshot": 12000}
        for n in (1, 2, 3)
    ]
    return db


def _export(monkeypatch, db, role, params):
    async def _auth(_req):
        return {"id": "u1", "name": "Uji", "role": role, "_permissions": []}
    monkeypatch.setattr(ox, "require_auth", _auth)
    monkeypatch.setattr(ox, "get_db", lambda: db)

    async def run():
        resp = await ox.export_excel(_Req(params))
        chunks = [c async for c in resp.body_iterator]
        return b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)

    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(asyncio.run(run())))
    return [list(r) for r in wb.active.iter_rows(values_only=True)]


def test_query_sama_dengan_daftar_po():
    q = po_list_query({"status": "Confirmed", "business_type": "maklon", "search": "MKL"})
    assert q["status"] == "Confirmed"
    assert q["business_type"] == {"$ne": "internal"}
    assert {"po_number": {"$regex": "MKL", "$options": "i"}} in q["$or"]
    assert po_list_query({"business_type": "internal"}) == {"business_type": "internal"}
    assert po_list_query({}) == {}


def test_unduhan_mengikuti_saringan_layar(monkeypatch):
    rows = _export(monkeypatch, _db(), "admin_produksi",
                   {"type": "production-pos", "status": "Confirmed", "business_type": "maklon"})
    po_numbers = [r[1] for r in rows[1:]]
    assert po_numbers == ["PO-MKL-002"]          # internal & draf tersaring keluar
    rows = _export(monkeypatch, _db(), "admin_produksi", {"type": "production-pos", "search": "int-001"})
    assert [r[1] for r in rows[1:]] == ["PO-INT-001"]
    rows = _export(monkeypatch, _db(), "admin_produksi", {"type": "production-pos"})
    assert len(rows) == 4                          # tanpa saringan = semua (maks. 500)


def test_harga_disembunyikan_untuk_non_keuangan(monkeypatch):
    for role in ("admin_produksi", "supervisor_produksi", "admin_maklon", "ppic", "manager"):
        rows = _export(monkeypatch, _db(), role, {"type": "production-pos"})
        header = rows[0]
        assert "Harga jasa" not in header and "Upah CMT" not in header, role
        assert 50000 not in rows[1] and 12000 not in rows[1], role
        assert header[1] == "No. PO" and header[-1] == "Qty"


def test_harga_tampil_untuk_keuangan(monkeypatch):
    for role in ("accounting", "staff_keuangan", "owner"):
        rows = _export(monkeypatch, _db(), role, {"type": "production-pos", "status": "Confirmed",
                                                   "business_type": "internal"})
        assert rows[0][-2:] == ["Harga jasa", "Upah CMT"], role
        assert rows[1][-2:] == [50000, 12000]
        assert rows[1][6] == "Dikonfirmasi"      # status berbahasa Indonesia


def test_laporan_produksi_juga_tanpa_harga(monkeypatch):
    db = _db()
    rows = _export(monkeypatch, db, "admin_produksi", {"type": "production-report"})
    assert "Selling Price" not in rows[0] and "Total CMT" not in rows[0]
    assert len(rows[0]) == len(rows[1]) == 15
    rows = _export(monkeypatch, _db(), "accounting", {"type": "production-report"})
    assert "Selling Price" in rows[0] and "Total CMT" in rows[0] and len(rows[1]) == 19


def test_klien_dan_vendor_ditolak(monkeypatch):
    for role in ("klien_maklon", "cmt_vendor", "vendor"):
        with pytest.raises(HTTPException) as e:
            _export(monkeypatch, _db(), role, {"type": "production-pos"})
        assert e.value.status_code == 403, role
