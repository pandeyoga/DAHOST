"""Standar UI/UX v2 (8 Nov 2026) — jumlah stok PER KATALOG dihitung langsung (stok jual LIVE).

Keluhan owner: tabel Manajemen Katalog menampilkan "100% sehat" karena memakai
`low_stock_count/out_of_stock_count` TERSIMPAN di `marketing_catalogs` (cache basi), padahal
`/stock-dashboard` menghitung 640 item habis. Kini `stock_dashboard` mengembalikan
`catalog_breakdown` = {catalog_id: {total, in_stock, low_stock, out_of_stock, unlinked}} dari loop
yang sama dengan kartu ringkasan, sehingga tabel dan kartu tidak bisa berbeda.
"""
import asyncio
import copy
import os
import pathlib
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from _fake_mongo import FakeCollection, FakeCursor, FakeDB, FakeRequest, match  # noqa: E402


class _AggCollection(FakeCollection):
    """Koleksi palsu + `aggregate` ($match/$group-$sum) — secukupnya untuk stock_dashboard."""

    def aggregate(self, pipeline):
        docs = [copy.deepcopy(d) for d in self.docs]
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if match(d, stage["$match"])]
            elif "$group" in stage:
                spec, groups = stage["$group"], {}
                for d in docs:
                    key = {k: d[v[1:]] for k, v in spec["_id"].items() if v[1:] in d}
                    g = groups.setdefault(repr(sorted(key.items(), key=lambda kv: kv[0])),
                                          {"_id": key, **{a: 0 for a in spec if a != "_id"}})
                    for a, op in spec.items():
                        if a != "_id":
                            assert op == {"$sum": 1}
                            g[a] += 1
                docs = list(groups.values())
            else:
                raise NotImplementedError(stage)
        return FakeCursor(docs)


class _AggDB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _AggCollection(name)
        return self._cols[name]


def _import_catalog_mgmt():
    orig = pathlib.Path.mkdir

    def _mkdir(self, *a, **k):
        try:
            return orig(self, *a, **k)
        except OSError:
            return None
    pathlib.Path.mkdir = _mkdir
    try:
        import routes.marketing_catalog_mgmt as cm
    finally:
        pathlib.Path.mkdir = orig
    return cm


ADMIN = {"id": "u-adm", "name": "Admin", "role": "superadmin"}


def _db():
    db = _AggDB()
    db.marketing_platform_accounts.docs = [
        {"id": "acc-a", "platform": "shopee", "status": "active"},
        {"id": "acc-b", "platform": "tiktok", "status": "active"},
        {"id": "acc-c", "platform": "shopee", "status": "active"},
    ]
    # Cache tersimpan sengaja SALAH (0 rendah / 0 habis) — angka tabel tidak boleh memakainya.
    db.marketing_catalogs.docs = [
        {"id": "cat-a", "account_id": "acc-a", "platform": "shopee", "is_active": True,
         "item_count": 4, "low_stock_count": 0, "out_of_stock_count": 0},
        {"id": "cat-b", "account_id": "acc-b", "platform": "tiktok", "is_active": True,
         "item_count": 2, "low_stock_count": 0, "out_of_stock_count": 0},
        {"id": "cat-kosong", "account_id": "acc-c", "platform": "shopee", "is_active": True,
         "item_count": 0, "low_stock_count": 0, "out_of_stock_count": 0},
        {"id": "cat-off", "account_id": "acc-a", "platform": "shopee", "is_active": False},
    ]
    db.rahaza_materials.docs = [
        {"id": "fg-1", "type": "fg", "code": "FG-1"},   # stok 50 → tersedia
        {"id": "fg-2", "type": "fg", "code": "FG-2"},   # stok 3  → stok rendah
        {"id": "fg-3", "type": "fg", "code": "FG-3"},   # stok 0  → habis
    ]
    db.rahaza_material_stock.docs = [
        {"material_id": "fg-1", "location_id": "L1", "qty": 50},
        {"material_id": "fg-2", "location_id": "L1", "qty": 3},
    ]
    db.marketing_catalog_items.docs = [
        {"id": "a1", "catalog_id": "cat-a", "fg_material_id": "fg-1", "is_active": True, "stock_status": "in_stock"},
        {"id": "a2", "catalog_id": "cat-a", "fg_material_id": "fg-2", "is_active": True, "stock_status": "in_stock"},
        {"id": "a3", "catalog_id": "cat-a", "fg_material_id": "fg-3", "is_active": True, "stock_status": "in_stock"},
        {"id": "a4", "catalog_id": "cat-a", "is_active": True, "stock_status": "in_stock"},           # belum tertaut
        {"id": "a5", "catalog_id": "cat-a", "fg_material_id": "fg-3", "is_active": False},           # nonaktif
        {"id": "b1", "catalog_id": "cat-b", "fg_material_id": "fg-3", "is_active": True},
        {"id": "b2", "catalog_id": "cat-b", "fg_material_id": "fg-3", "is_active": True, "name": "B2"},
        {"id": "off1", "catalog_id": "cat-off", "fg_material_id": "fg-1", "is_active": True},
    ]
    return db


def _dashboard(monkeypatch):
    cm = _import_catalog_mgmt()
    db = _db()

    async def _auth(_req):
        return ADMIN
    monkeypatch.setattr(cm, "require_auth", _auth)
    monkeypatch.setattr(cm, "get_db", lambda: db)
    req = FakeRequest()
    req.state.user = ADMIN
    return asyncio.run(cm.stock_dashboard(req, account_id=None, platform=None))


def test_jumlah_per_katalog_dari_stok_live_bukan_cache(monkeypatch):
    out = _dashboard(monkeypatch)
    per = out["catalog_breakdown"]
    assert per["cat-a"] == {"total": 4, "in_stock": 1, "low_stock": 1, "out_of_stock": 1, "unlinked": 1}
    assert per["cat-b"] == {"total": 2, "in_stock": 0, "low_stock": 0, "out_of_stock": 2, "unlinked": 0}
    # katalog aktif tanpa item aktif tetap muncul dengan 0 (bukan hilang / bukan "100% sehat")
    assert per["cat-kosong"] == {"total": 0, "in_stock": 0, "low_stock": 0, "out_of_stock": 0, "unlinked": 0}
    # katalog nonaktif tidak dihitung (sama dengan kartu ringkasan)
    assert "cat-off" not in per


def test_jumlah_per_katalog_sama_dengan_kartu_ringkasan(monkeypatch):
    out = _dashboard(monkeypatch)
    s, per = out["summary"], out["catalog_breakdown"].values()
    for k in ("in_stock", "low_stock", "out_of_stock", "unlinked"):
        assert sum(p[k] for p in per) == s[k]
    assert sum(p["total"] for p in per) == s["total_items"] == 6
