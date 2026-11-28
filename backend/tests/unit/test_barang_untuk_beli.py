"""Uji unit HERMETIK — daftar barang untuk form Pengadaan (`GET /api/rahaza/materials?untuk_beli=true`).

Owner 28 Nov 2026: "di portal pembelian, saat menambahkan barang saat ini langsung ke semua master data, tolong
dikategorikan dulu dan ada filter". Potongan / kain pola hasil cutting dan penanda "kain belum ditentukan" tidak
pernah dibeli, jadi tidak ikut daftar.
Jalankan:  cd backend && python -m pytest tests/unit/test_barang_untuk_beli.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402


def _db():
    db = FakeDB()
    db.rahaza_materials.docs = [
        {"id": "k1", "code": "KN-K24-GRY", "name": "RIB KNIT 24\"", "type": "fabric", "category_code": "FABRIC", "active": True},
        {"id": "p1", "code": "CUT-DA-1101-BRG-ALLSIZE", "name": "Potongan Lyora", "type": "fabric", "is_cut_panel": True,
         "category_code": "CUT_PANEL", "active": True},
        {"id": "t1", "code": "KN-TBD-DST", "name": "KAIN BELUM DITENTUKAN", "type": "fabric", "category_code": "FABRIC",
         "active": True},
        {"id": "a1", "code": "A-K22-0001", "name": "Kancing 22L", "type": "accessory", "category_code": "ACCESSORY",
         "active": True},
        {"id": "f1", "code": "FG-001", "name": "Gamis", "type": "fg", "active": True},
    ]
    return db


def _panggil(monkeypatch, **params):
    import routes.rahaza_inventory_materials as rim
    db = _db()
    monkeypatch.setattr(rim, "get_db", lambda: db)

    async def _auth(_req):
        return {"id": "u1", "role": "owner"}
    monkeypatch.setattr(rim, "require_auth", _auth)
    req = SimpleNamespace(query_params=dict(params))
    return asyncio.run(rim.list_materials(req, **params))


def test_untuk_beli_tanpa_potongan_penanda_dan_barang_jadi(monkeypatch):
    rows = _panggil(monkeypatch, exclude_type="fg", untuk_beli="true")
    assert sorted(r["code"] for r in rows) == ["A-K22-0001", "KN-K24-GRY"]


def test_tanpa_untuk_beli_daftar_lama_tetap(monkeypatch):
    rows = _panggil(monkeypatch, exclude_type="fg")
    assert len(rows) == 4
