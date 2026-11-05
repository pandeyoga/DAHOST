"""Master toko: siapa boleh mengubah, dan toko yang sama tidak boleh tercatat dua kali (owner, 5 Nov 2026).

Kasus VPS: PIC toko (Mar'atus) menambah "SHOPEE - OUTFIT" (= SHP-02 Shopee Outfit Boutique, username
"outfit.boutique" vs "outfit boutique") dan "TIKTOK - OUTFIT" (= TTK-02, username sama `outfit_butiq`).
Dulu siapa pun yang login boleh menambah/mengubah toko dan cek dobel hanya kode toko; tiap toko baru juga
membuat akun Penjualan + Piutang di Bagan Akun.
"""
import asyncio
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
from core import marketing_account_scope as scope  # noqa: E402
import routes.marketing_accounts as ma  # noqa: E402
from routes.marketing_shared import PlatformAccountCreate, PlatformAccountUpdate  # noqa: E402

PIC = {"id": "u-mar", "name": "Mar'atus", "role": "pic_toko"}
SPV = {"id": "u-spv", "name": "SPV", "role": "spv_marketing"}
T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 5, tzinfo=timezone.utc)
STORES = [
    {"id": "a-shp02", "account_code": "SHP-02", "account_name": "Shopee Outfit Boutique", "platform": "shopee",
     "username": "outfit boutique", "status": "active", "created_at": T0},
    {"id": "a-ttk02", "account_code": "TTK-02", "account_name": "Tiktok Outfit Boutique", "platform": "tiktok",
     "username": "outfit_butiq", "status": "active", "created_at": T0},
    {"id": "a-shp03", "account_code": "SHP-03", "account_name": "Shopee Rayona", "platform": "shopee",
     "username": "rayonagrosirsolo", "status": "active", "created_at": T0},
    {"id": "a-ttk03", "account_code": "TTK-03", "account_name": "Tiktok Rayona", "platform": "tiktokshop",
     "username": "rayonagrosirsolo", "status": "active", "created_at": T0},
]


def _db():
    db = FakeDB()
    db.marketing_platform_accounts.docs = [dict(s) for s in STORES]
    return db


def _call(fn, db, user, monkeypatch, *args):
    async def _auth(_req):
        return user
    monkeypatch.setattr(ma, "require_auth", _auth)
    monkeypatch.setattr(ma, "get_db", lambda: db)
    req = FakeRequest()
    req.state.user = user
    return asyncio.run(fn(*args, req))


# ── aturan identitas toko (satu tempat: core.marketing_account_scope) ───────
def test_identitas_toko_tanpa_beda_titik_spasi_dan_alias_tiktok():
    k = scope.store_identity_keys
    assert k("shopee", "outfit.boutique", "") & k("shopee", "outfit boutique", "")
    assert k("tiktokshop", "outfit_butiq", "") & k("tiktok", "outfit_butiq", "")
    # username sama di platform BERBEDA = toko berbeda (Shopee Rayona vs TikTok Rayona)
    assert not (k("shopee", "rayonagrosirsolo", "Shopee Rayona") & k("tiktok", "rayonagrosirsolo", "Tiktok Rayona"))


# ── siapa boleh menambah / mengubah ─────────────────────────────────────────
def test_pic_toko_tidak_boleh_menambah_toko(monkeypatch):
    body = PlatformAccountCreate(account_code="SHOPEE - OUTFIT", account_name="Shopee Outfit Boutique",
                                 platform="shopee", username="outfit.boutique")
    with pytest.raises(HTTPException) as e:
        _call(ma.create_platform_account, _db(), PIC, monkeypatch, body)
    assert e.value.status_code == 403


def test_pic_toko_tidak_boleh_mengubah_toko(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _call(ma.update_platform_account, _db(), PIC, monkeypatch, "a-shp02",
              PlatformAccountUpdate(account_name="Ganti"))
    assert e.value.status_code == 403


def test_pic_toko_tidak_boleh_mengarsipkan(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _call(ma.archive_platform_account, _db(), PIC, monkeypatch, "a-shp02")
    assert e.value.status_code == 403


# ── toko dobel ditolak ──────────────────────────────────────────────────────
@pytest.mark.parametrize("platform,username,name", [
    ("shopee", "outfit.boutique", "Toko Baru"),          # username sama (beda titik/spasi)
    ("tiktokshop", "outfit_butiq", "Nama Lain"),          # username sama, alias tiktok
    ("shopee", "akun_baru", "Shopee Outfit Boutique"),    # nama sama
])
def test_toko_yang_sama_ditolak_saat_dibuat(monkeypatch, platform, username, name):
    body = PlatformAccountCreate(account_code="KODE-BARU", account_name=name, platform=platform, username=username)
    with pytest.raises(HTTPException) as e:
        _call(ma.create_platform_account, _db(), SPV, monkeypatch, body)
    assert e.value.status_code == 400 and "sudah tercatat" in e.value.detail


def test_ganti_username_menjadi_toko_lain_ditolak(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _call(ma.update_platform_account, _db(), SPV, monkeypatch, "a-shp03",
              PlatformAccountUpdate(username="outfit.boutique"))
    assert e.value.status_code == 400 and "SHP-02" in e.value.detail


def test_simpan_ulang_tanpa_ganti_identitas_tidak_ditolak(monkeypatch):
    # data lama yang sudah dobel tidak boleh membuat toko aslinya tidak bisa disimpan lagi
    db = _db()
    db.marketing_platform_accounts.docs.append(
        {"id": "a-dobel", "account_code": "TIKTOK - OUTFIT", "account_name": "Tiktok Outfit Boutique",
         "platform": "tiktokshop", "username": "outfit_butiq", "status": "active", "created_at": T1})
    ttk02 = next(a for a in db.marketing_platform_accounts.docs if a["id"] == "a-ttk02")
    asyncio.run(ma._assert_not_duplicate_on_update(   # tidak melempar
        db, ttk02, PlatformAccountUpdate(username="outfit_butiq", account_name="Tiktok Outfit Boutique", group="x")))


# ── migrasi bersih-bersih: pengelompokan & pilihan toko yang dipertahankan ──
def _migrasi():
    p = ROOT / "scripts" / "migrations" / "2026_11_05_toko_dobel.py"
    spec = importlib.util.spec_from_file_location("toko_dobel", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_mengelompokkan_toko_dobel_dan_mempertahankan_yang_lama():
    mig = _migrasi()
    stores = [dict(s) for s in STORES] + [
        {"id": "a-d1", "account_code": "SHOPEE - OUTFIT", "account_name": "Shopee Outfit Boutique",
         "platform": "shopee", "username": "outfit.boutique", "created_at": T1},
        {"id": "a-d2", "account_code": "TIKTOK - OUTFIT", "account_name": "Tiktok Outfit Boutique",
         "platform": "tiktokshop", "username": "outfit_butiq", "created_at": T1},
    ]
    groups = sorted(sorted(s["account_code"] for s in g) for g in mig.cluster_duplicates(stores))
    assert groups == [["SHOPEE - OUTFIT", "SHP-02"], ["TIKTOK - OUTFIT", "TTK-02"]]   # Rayona bukan dobel
    g = [s for s in stores if s["id"] in ("a-shp02", "a-d1")]
    assert mig.choose_keeper(g, {})["account_code"] == "SHP-02"                     # yang lebih dulu dibuat
    assert mig.choose_keeper(g, {"a-d1": 5})["account_code"] == "SHOPEE - OUTFIT"   # yang punya data menang


# ── hapus permanen (super admin, hanya toko tanpa data) ─────────────────────
SUPER = {"id": "u-super", "name": "Super Admin", "role": "superadmin"}
DOBEL = {"id": "a-d1", "account_code": "SHOPEE - OUTFIT", "account_name": "Shopee Outfit Boutique",
         "platform": "shopee", "username": "outfit.boutique", "status": "active", "created_at": T1,
         "coa_revenue_code": "4-1118", "coa_receivable_code": "1-1303-SHOPEE-OUTFIT"}


def _db_dobel(monkeypatch):
    from core import coa_bindings as cb
    async def _no_bindings(db, codes=None, **kw):
        return {c: [] for c in (codes or [])}
    monkeypatch.setattr(cb, "collect_bindings", _no_bindings)
    db = _db()
    db.marketing_platform_accounts.docs.append(dict(DOBEL))
    db.rahaza_coa_accounts.docs = [
        {"code": "4-1115", "name": "Penjualan – Shopee Outfit Boutique", "active": True,
         "created_by_name": "finance_sync", "flags": {"store_account_code": "SHP-02"}},
        {"code": "4-1118", "name": "Penjualan – Shopee Outfit Boutique", "active": True,
         "created_by": "system", "created_by_name": "finance_sync", "flags": {"store_account_code": "SHOPEE - OUTFIT"}},
        {"code": "1-1303-SHOPEE-OUTFIT", "name": "Piutang Channel — Shopee Outfit Boutique", "active": True,
         "flags": {"subledger": True, "subledger_entity_id": "a-d1"}},
    ]
    # draf impor yang belum pernah disimpan BUKAN data (kasus VPS 5 Nov)
    db.marketing_data_import_sessions.docs = [{"id": "s1", "account_id": "a-d1", "status": "ready", "committed_count": 0}]
    return db


def test_hapus_permanen_toko_tanpa_data_ikut_membereskan_akun_coa(monkeypatch):
    from core import store_cleanup
    db = _db_dobel(monkeypatch)
    res = asyncio.run(store_cleanup.delete_store_permanently(db, dict(DOBEL), SUPER))
    assert not [a for a in db.marketing_platform_accounts.docs if a["id"] == "a-d1"]
    assert sorted(res["coa_deleted"]) == ["1-1303-SHOPEE-OUTFIT", "4-1118"]
    assert [a["code"] for a in db.rahaza_coa_accounts.docs] == ["4-1115"]       # akun toko asli utuh
    assert res["drafts_deleted"] == 1
    assert db.marketing_change_log.docs[-1]["action"] == "store_deleted"


def test_hapus_permanen_ditolak_bila_toko_punya_data(monkeypatch):
    from core import store_cleanup
    db = _db_dobel(monkeypatch)
    db.marketing_content_calendar.docs = [{"id": "k1", "account_id": "a-d1", "title": "test"}]
    with pytest.raises(ValueError) as e:
        asyncio.run(store_cleanup.delete_store_permanently(db, dict(DOBEL), SUPER))
    assert "1 jadwal konten" in str(e.value)
    db.marketing_content_calendar.docs = []
    db.koleksi_baru_lain.docs = [{"id": "z1", "account_id": "a-d1"}]
    with pytest.raises(ValueError) as e:
        asyncio.run(store_cleanup.delete_store_permanently(db, dict(DOBEL), SUPER))
    assert "1 data lain" in str(e.value) and "koleksi_baru_lain" not in str(e.value)   # nama program tidak tampil
    assert [a for a in db.marketing_platform_accounts.docs if a["id"] == "a-d1"]  # tidak terhapus


@pytest.mark.parametrize("user", [SPV, {"id": "u-adm", "name": "Admin", "role": "admin"}, PIC])
def test_hapus_permanen_hanya_super_admin(monkeypatch, user):
    with pytest.raises(HTTPException) as e:
        _call(ma.delete_platform_account_permanently, _db_dobel(monkeypatch), user, monkeypatch, "a-d1")
    assert e.value.status_code == 403


def test_hapus_permanen_lewat_endpoint(monkeypatch):
    async def _no_log(*a, **k):
        return None
    monkeypatch.setattr(ma, "log_activity", _no_log)
    db = _db_dobel(monkeypatch)
    out = _call(ma.delete_platform_account_permanently, db, SUPER, monkeypatch, "a-d1")
    assert out["ok"] and "dihapus permanen" in out["message"]
    db.marketing_platform_accounts.docs.append(dict(DOBEL, id="a-d2"))
    db.marketing_orders.docs = [{"id": "o1", "account_id": "a-d2"}]
    with pytest.raises(HTTPException) as e:
        _call(ma.delete_platform_account_permanently, db, SUPER, monkeypatch, "a-d2")
    assert e.value.status_code == 409 and "1 pesanan" in e.value.detail
