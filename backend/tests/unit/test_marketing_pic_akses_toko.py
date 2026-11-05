"""PIC toko otomatis melihat tokonya (keputusan owner 5 Nov 2026).

Kasus: owner memilih Rina sebagai PIC TikTok Daluna & Shopee GHS di Manajemen Akun, tetapi saat Rina
membuka Kelola Akun tampil "Belum ada akun toko". Sebab: form menyimpan PIC di `pic_user_id`, sedangkan
aturan visibilitas membaca `pic_id` — isian lama yang berisi PEMBUAT toko. Sekarang pemegang toko =
PIC (`pic_user_id`) + staf di Assign Staf; pembuat toko tidak lagi ikut.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
from core import marketing_account_scope as scope  # noqa: E402
import routes.marketing_account_assign as assign  # noqa: E402

RINA = {"id": "u-rina", "name": "Rina", "email": "rina@x.id", "role": "pic_toko", "status": "active"}
NIKEN = {"id": "u-niken", "name": "Niken", "email": "niken@x.id", "role": "pic_toko", "status": "active"}
PEMBUAT = {"id": "u-pembuat", "name": "Pembuat", "email": "p@x.id", "role": "staff_marketing", "status": "active"}
MANAGER = {"id": "u-mgr", "name": "Manager", "email": "m@x.id", "role": "manager_marketing", "status": "active"}


def _db():
    db = FakeDB()
    db.users.docs = [dict(u) for u in (RINA, NIKEN, PEMBUAT, MANAGER)]
    db.marketing_platform_accounts.docs = [
        # PIC dipilih di Manajemen Akun; `pic_id` lama berisi pembuat toko
        {"id": "a-daluna", "account_name": "TikTok Daluna", "status": "active", "platform": "tiktok",
         "pic_user_id": "u-rina", "pic_user_name": "Rina", "pic_id": "u-pembuat", "assigned_staff": []},
        {"id": "a-ghs", "account_name": "Shopee GHS", "status": "active", "platform": "shopee",
         "pic_user_id": "u-rina", "pic_user_name": "Rina"},
        # dipegang lewat Assign Staf saja
        {"id": "a-sukma", "account_name": "Shopee Sukma", "status": "active", "platform": "shopee",
         "assigned_staff": ["u-niken"]},
        # PIC-nya manager (melihat semua toko) — tidak boleh dianggap "staf hantu"
        {"id": "a-rayona", "account_name": "Shopee Rayona", "status": "active", "platform": "shopee",
         "pic_user_id": "u-mgr", "pic_user_name": "Manager"},
        # tanpa PIC dan tanpa staf
        {"id": "a-kosong", "account_name": "Toko Kosong", "status": "active", "platform": "shopee"},
    ]
    return db


def _ids(db, user):
    return asyncio.run(scope.visible_account_ids(db, user))


def test_pic_melihat_toko_yang_dipilih_untuknya():
    assert sorted(_ids(_db(), RINA)) == ["a-daluna", "a-ghs"]


def test_staf_assign_tetap_melihat_tokonya():
    assert _ids(_db(), NIKEN) == ["a-sukma"]


def test_pembuat_toko_bukan_pic():
    # dulu `pic_id` (pembuat) memberi akses — sekarang tidak
    assert _ids(_db(), PEMBUAT) == []


def test_peran_semua_toko_tanpa_filter():
    assert _ids(_db(), MANAGER) is None


def _call(fn, db, user, monkeypatch, **kw):
    async def _auth(_req):
        return user
    monkeypatch.setattr(assign, "require_auth", _auth)
    monkeypatch.setattr(assign, "get_db", lambda: db)
    req = FakeRequest()
    req.state.user = user
    return asyncio.run(fn(req, **kw))


def test_assign_staf_menampilkan_pic_yang_dipilih(monkeypatch):
    out = _call(assign.overview, _db(), MANAGER, monkeypatch, include_inactive=True)
    rows = {r["id"]: r for r in out["rows"]}
    assert rows["a-daluna"]["pic"]["name"] == "Rina"        # bukan "Pembuat"
    # toko ber-PIC tidak dihitung "belum terpegang"; hanya toko tanpa PIC & tanpa staf
    assert out["unassigned_count"] == 1


def test_per_staf_menghitung_toko_sebagai_pic(monkeypatch):
    out = _call(assign.by_staff, _db(), MANAGER, monkeypatch)
    rows = {r["id"]: r for r in out["rows"]}
    rina = rows["u-rina"]
    assert rina["accounts_count"] == 2 and all(a["as_pic"] for a in rina["accounts"])
    assert rows["u-niken"]["accounts_count"] == 1
    assert "Rina" not in out["without_account"]
    assert out["ghost_staff_ids"] == []                       # PIC manager bukan staf hantu
