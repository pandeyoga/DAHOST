"""Uji unit HERMETIK — baris PO maklon WAJIB varian Katalog Buyer (keputusan owner 22 Nov 2026).

Kejadian: PO Kamira koh Tri, satu seri dua warna, artikel tanpa varian → "baris kembar" + warna diketik bebas.
Jalankan:  cd backend && python -m pytest tests/unit/test_maklon_varian_wajib.py -q
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
from core import maklon_varian as mv  # noqa: E402
from core import po_tolak_dobel as ptd  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _db():
    db = FakeDB()
    db.dewi_maklon_buyer_catalog.docs = [
        {"id": "kam", "client_id": "tri", "artikel_code": "BJ_1940", "product_name": "KAMIRA", "status": "active",
         "buyer_ref_code": "KMR", "variants": [
             {"id": "v-put-l", "sku": "BJ_1940-PTH-L", "color": "Putih", "color_code": "PTH", "size": "L",
              "active": True},
             {"id": "v-hit-l", "sku": "BJ_1940-BLK-L", "color": "Hitam", "color_code": "BLK", "size": "L",
              "active": True},
             {"id": "v-lama", "sku": "BJ_1940-NVY-L", "color": "Navy", "color_code": "NVY", "size": "L",
              "active": False}]},
        {"id": "polos", "client_id": "tri", "artikel_code": "BJ_2000", "product_name": "TANPA VARIAN",
         "status": "active", "variants": []},
        {"id": "lain", "client_id": "bukan-tri", "artikel_code": "X1", "product_name": "MILIK BUYER LAIN",
         "status": "active", "variants": [{"id": "vx", "sku": "X1-PTH-L", "color": "Putih", "size": "L"}]},
    ]
    return db


def test_satu_seri_dua_warna_dari_varian_bukan_kembar():
    db = _db()
    rows = run(mv.rapikan_baris(db, [
        {"catalog_item_id": "kam", "maklon_variant_id": "v-put-l", "qty": 171, "serial_number": "AF-4522-1",
         "sku": "ketikan", "color": "puith"},                                   # ketikan formulir diabaikan
        {"catalog_item_id": "kam", "maklon_variant_id": "BJ_1940-BLK-L", "qty": 150, "serial_number": "AF-4522-1"},
    ], "tri"))
    assert [(r["sku"], r["color"], r["size"], r["color_code"]) for r in rows] == [
        ("BJ_1940-PTH-L", "Putih", "L", "PTH"), ("BJ_1940-BLK-L", "Hitam", "L", "BLK")]
    assert rows[1]["maklon_variant_id"] == "v-hit-l" and rows[0]["product_name"] == "KAMIRA"
    assert rows[0]["buyer_ref_code"] == "KMR"
    assert ptd.baris_kembar(rows) == []                                        # beda varian → bukan kembar
    assert len(ptd.baris_kembar([rows[0], {**rows[0], "qty": 5}])) == 1        # varian sama → kembar


@pytest.mark.parametrize("baris,potongan", [
    ({"qty": 1}, "pilih artikel dari Katalog Buyer"),
    ({"catalog_item_id": "polos", "qty": 1, "color": "Putih"}, "belum punya varian"),
    ({"catalog_item_id": "kam", "qty": 1}, "pilih varian"),
    ({"catalog_item_id": "kam", "maklon_variant_id": "v-lama", "qty": 1}, "pilih varian"),   # varian nonaktif
    ({"catalog_item_id": "lain", "maklon_variant_id": "vx", "qty": 1}, "bukan milik buyer"),
])
def test_baris_tidak_sah_ditolak_dengan_pesan_jelas(baris, potongan):
    with pytest.raises(HTTPException) as e:
        run(mv.rapikan_baris(_db(), [baris], "tri"))
    assert e.value.status_code == 400 and potongan in e.value.detail


def test_baris_lama_tanpa_varian_tetap_bisa_disimpan_bila_tidak_diubah():
    lama = {"b1": {"id": "b1", "catalog_item_id": "polos", "maklon_variant_id": None, "sku": "BJ_2000",
                   "color": "PUTIH", "size": "L"}}
    rows = run(mv.rapikan_baris(_db(), [{"id": "b1", "catalog_item_id": "polos", "sku": "BJ_2000", "color": "PUTIH",
                                         "size": "L", "qty": 200}], "tri", lama_by_id=lama))
    assert rows[0]["qty"] == 200 and rows[0]["color"] == "PUTIH"
    with pytest.raises(HTTPException):                                          # warnanya diubah → wajib varian
        run(mv.rapikan_baris(_db(), [{"id": "b1", "catalog_item_id": "polos", "sku": "BJ_2000", "color": "HITAM",
                                      "size": "L", "qty": 200}], "tri", lama_by_id=lama))


def test_kode_warna_varian_dari_master_walau_tanpa_field_active():
    import routes.dewi_maklon_buyer_catalog as mod
    db = FakeDB()
    db.rahaza_colors.docs = [{"code": "SKB", "name": "Sakura Blush"}]           # warna lama tanpa `active`
    assert run(mod._color_code_for(db, "sakura blush")) == "SKB"
    assert run(mod._color_code_for(db, "Warna Baru")) == "WAR"
