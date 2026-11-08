"""Uji agen PEMASARAN Asisten AI Tahap B (8 Nov 2026).

1. Celah izin yang ditutup (berlaku juga untuk layar biasa): target kreator, hapus target (baru),
   pembuatan tugas marketing, diskon, harga jual katalog + riwayat harga.
2. Matematika alat baca ``skenario_target`` + keluaran alatnya (lewat endpoint analitik SUNGGUHAN).
3. Lima alat tindakan (Kontrak D): ``siapkan`` hanya membaca, ``jalankan`` menulis lewat ``ctx.api``,
   ``batalkan`` memulihkan — ``ctx.api`` tiruan meneruskan panggilan ke fungsi route ASLI di atas Mongo
   palsu, jadi penjaga izin, lingkup toko, CV, dan kunci periode endpoint ikut teruji.
Hermetik: tanpa jaringan, tanpa API Anthropic.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
from datetime import date, datetime, timezone
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

import _fake_mongo as fm  # noqa: E402
from _fake_mongo import FakeCollection, FakeDB  # noqa: E402

from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai.alat import skenario_target as SK  # noqa: E402
from core.asisten_ai.alat import tindakan_pemasaran as TP  # noqa: E402
from core.asisten_ai.alat_base import AlatError  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════════
# Perlengkapan
# ══════════════════════════════════════════════════════════════════════════════
OWNER = {"id": "u-owner", "role": "owner", "name": "Pemilik Uji", "email": "owner@uji"}
MGR = {"id": "u-mgr", "role": "manager_marketing", "name": "Manajer Uji", "email": "mgr@uji", "_role_perms": []}
SPV = {"id": "u-spv", "role": "spv_marketing", "name": "SPV Uji", "email": "spv@uji", "_role_perms": []}
STAF = {"id": "u-staf", "role": "staff_marketing", "name": "Staf Uji", "email": "staf@uji", "_role_perms": []}
STAF2 = {"id": "u-staf2", "role": "staff_marketing", "name": "Staf Dua", "email": "staf2@uji", "_role_perms": []}
PIC = {"id": "u-pic", "role": "pic_toko", "name": "Pic Uji", "email": "pic@uji", "_role_perms": []}
GUDANG = {"id": "u-gdg", "role": "admin_gudang", "name": "Gudang Uji", "email": "gdg@uji", "_role_perms": []}
CS = {"id": "u-cs", "role": "cs_staff", "name": "CS Uji", "email": "cs@uji", "_role_perms": []}
KREATOR = {"id": "u-cc", "role": "content_creator", "name": "Kreator Uji", "email": "cc@uji", "_role_perms": []}
HARI = date(2026, 11, 8)


class UpsertCollection(FakeCollection):
    """Mongo palsu + `upsert=True` + `$setOnInsert` (dipakai PUT anggaran)."""

    async def update_one(self, q, upd, upsert=False):
        r = await super().update_one(q, upd, upsert=upsert)
        if r.matched_count if hasattr(r, "matched_count") else getattr(r, "matched", 0):
            return r
        if any(fm.match(d, q) for d in self.docs) or not upsert:
            return r
        doc = {k: v for k, v in q.items() if not str(k).startswith("$") and not isinstance(v, dict)}
        doc.update(copy.deepcopy(upd.get("$setOnInsert") or {}))
        doc.update(copy.deepcopy(upd.get("$set") or {}))
        self.docs.append(doc)
        return r


class DB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = UpsertCollection(name)
        return self._cols[name]


def _akun(aid, nama, platform="shopee", **kw):
    return {"id": aid, "account_name": nama, "account_code": aid, "platform": platform, "status": "active", **kw}


def _rekap(aid, tanggal, omzet, pesanan):
    return {"id": f"sd-{aid}-{tanggal}", "account_id": aid, "date": tanggal, "revenue_type": "total",
            "metrics": {"revenue": omzet, "revenue_product": omzet, "orders": pesanan, "units": pesanan,
                        "buyers": pesanan}, "fulfillment": {}, "revenue_basis": "produk_setelah_diskon",
            "updated_at": "2026-11-01T00:00:00"}


def _db():
    db = DB()
    db.marketing_platform_accounts.docs += [
        _akun("A1", "Shopee Uji Satu", pic_user_id="u-staf"),
        _akun("A2", "TikTok Uji Dua", "tiktok", assigned_staff=["u-pic"]),
        _akun("A3", "Shopee Sukma Uji", entity="SMU"),
    ]
    for aid, base in (("A1", 3_000_000.0), ("A2", 1_000_000.0)):
        for m, f in (("2026-08", 0.9), ("2026-09", 1.0), ("2026-10", 1.1)):
            for d in range(1, 11):
                db.marketing_sales_data.docs.append(_rekap(aid, f"{m}-{d:02d}", base * f, 10))
    db.users.docs += [dict(u, status="active") for u in (OWNER, MGR, SPV, STAF, STAF2, PIC)]
    db.marketing_livehosts.docs += [
        {"id": "H1", "name": "Host Uji Sari", "status": "active", "assigned_account_ids": ["A1"]},
        {"id": "H2", "name": "Host Uji Bima", "status": "active", "assigned_account_ids": ["A2"]},
    ]
    db.marketing_kol_creators.docs += [{"id": "K1", "name": "Kreator Satu", "assigned_account_ids": ["A1"]}]
    return db


class Req:
    """Request tiruan: state.user, headers (X-CV), query_params, json()."""

    def __init__(self, user, body=None, cv=None):
        class _S:
            pass
        self.state = _S()
        self.state.user = user
        self.headers = {"x-cv": cv} if cv else {}          # Starlette: nama header huruf kecil
        self.query_params = {}
        self._body = body or {}

    async def json(self):
        return copy.deepcopy(self._body)


def _auth(user):
    async def _f(request=None, *a, **k):
        if request is not None and getattr(request, "state", None) is not None:
            request.state.user = user
        return user
    return _f


@pytest.fixture
def env(monkeypatch):
    """DB palsu dipasang ke semua route Marketing yang dipakai alat; `pakai(user)` memilih pengguna."""
    import auth
    from routes import marketing_accounts as acc
    from routes import marketing_analitik as ma
    from routes import marketing_budget as mb
    from routes import marketing_catalog_items as mci
    from routes import marketing_content_calendar_routes as cc
    from routes import marketing_discounts_routes as dis
    from routes import marketing_live_sessions_routes as ls
    from routes import marketing_targets as tgt
    from routes import marketing_tasks as mt
    db = _db()
    mods = (acc, ma, mb, mci, cc, dis, ls, tgt, mt)
    for m in mods:
        monkeypatch.setattr(m, "get_db", lambda: db)
    monkeypatch.setattr(ls, "_LP_INDEXES_READY", True)

    async def _diam(*a, **k):
        return None
    monkeypatch.setattr(mt, "log_activity", _diam)
    monkeypatch.setattr(mci, "_refresh_catalog_stats", _diam)
    monkeypatch.setattr("utils.waktu.today_wib", lambda: HARI)
    monkeypatch.setattr("routes.marketing_targets.now_wib", lambda: datetime(2026, 11, 8, 9, tzinfo=timezone.utc))
    monkeypatch.setattr(ma, "today_wib", lambda: HARI)

    def pakai(user):
        for m in mods + (auth,):
            if hasattr(m, "require_auth"):
                monkeypatch.setattr(m, "require_auth", _auth(user))
    pakai(MGR)
    return {"db": db, "pakai": pakai, "tgt": tgt, "mt": mt, "dis": dis, "mci": mci, "mb": mb, "ma": ma,
            "cc": cc, "ls": ls, "acc": acc}


# ── ctx.api tiruan: dispatcher ke fungsi route ASLI ────────────────────────────
class Ctx:
    def __init__(self, env, user=MGR, cv="DA", today=HARI, tindakan_id="tdk-uji-1"):
        self.env, self.user, self.cv, self.today, self.tindakan_id = env, user, cv, today, tindakan_id
        self.calls = []
        env["pakai"](user)

    @property
    def tulis(self):
        return [c for c in self.calls if c["method"] != "GET"]

    async def api(self, method, path, params=None, json=None, headers=None):
        self.calls.append({"method": method, "path": path, "params": dict(params or {}),
                           "json": copy.deepcopy(json), "headers": dict(headers or {})})
        e, p, r = self.env, dict(params or {}), Req(self.user, json, cv=self.cv)
        try:
            out = await self._rute(e, method, path, p, json, r)
        except HTTPException as x:
            raise AlatError(x.status_code, ab._pesan_status(x.status_code, {"detail": x.detail})) from None
        return __import__("json").loads(__import__("json").dumps(out, default=str))

    async def _rute(self, e, method, path, p, body, r):
        tgt, mb, mt, cc, ls = e["tgt"], e["mb"], e["mt"], e["cc"], e["ls"]
        if (method, path) == ("GET", "/api/marketing/analitik/target"):
            return await e["ma"].analitik_target(r, dari_bulan=p.get("dari_bulan"), sampai_bulan=p.get("sampai_bulan"),
                                                 toko_id=p.get("toko_id"))
        if (method, path) == ("GET", "/api/marketing/targets"):
            return await tgt.list_targets(r, year=p.get("year"), month=p.get("month"), account_id=None)
        if (method, path) == ("POST", "/api/marketing/targets"):
            return await tgt.upsert_target(tgt.TargetUpsert(**body), r)
        if method == "DELETE" and path.startswith("/api/marketing/targets/"):
            return await tgt.delete_target(path.rsplit("/", 1)[1], r, reason=p.get("reason"))
        if (method, path) == ("GET", "/api/marketing/periods/locks"):
            return await mb.list_period_locks(r, account_id=None)
        if (method, path) == ("GET", "/api/marketing/budget"):
            return await mb.get_budget(r, account_id=p["account_id"], period=p["period"])
        if (method, path) == ("PUT", "/api/marketing/budget"):
            return await mb.upsert_budget(mb.BudgetUpsert(**body), r)
        if (method, path) == ("GET", "/api/marketing/budget/period-settings"):
            return await mb.read_period_settings(r)
        if method == "GET" and path.startswith("/api/marketing/accounts/"):
            return await e["acc"].get_platform_account(path.rsplit("/", 1)[1], r)
        if (method, path) == ("GET", "/api/auth/users"):
            return [{"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"]}
                    for u in self.env["db"].users.docs if u.get("role") not in ("admin_gudang",)]
        if (method, path) == ("POST", "/api/marketing/tasks"):
            return await mt.create_task(mt.TaskCreate(**body), r)
        if method == "GET" and path.startswith("/api/marketing/tasks/"):
            return await mt.get_task(path.rsplit("/", 1)[1], r)
        if method == "PUT" and path.startswith("/api/marketing/tasks/"):
            return await mt.update_task(path.rsplit("/", 1)[1], mt.TaskUpdate(**body), r)
        if (method, path) == ("POST", "/api/marketing/content-calendar"):
            return await cc.create_entry(cc.ContentEntryIn(**body), r)
        if (method, path) == ("GET", "/api/marketing/content-calendar"):
            return await cc.list_entries(r, page=1, page_size=p.get("page_size", 20), account_id=p.get("account_id", ""),
                                         status="", platform="", account="", content_type="",
                                         date_from=p.get("date_from", ""), date_to=p.get("date_to", ""))
        if method == "POST" and re.fullmatch(r"/api/marketing/content-calendar/[^/]+/status", path):
            return await cc.update_status(path.split("/")[-2], r)
        if (method, path) == ("GET", "/api/marketing/livehost"):
            # tiruan `marketing_livehost_hosts.list_livehosts` (modul itu membuat folder unggahan saat diimpor):
            # host aktif, dipotong lingkup toko pemakai — aturan yang sama.
            from core import marketing_account_scope as sc
            vis = await sc.visible_account_ids(self.env["db"], self.user)
            return [h for h in self.env["db"].marketing_livehosts.docs if h.get("status") == p.get("status", h.get("status"))
                    and (vis is None or set(h.get("assigned_account_ids") or []) & set(vis))]
        if (method, path) == ("POST", "/api/marketing/live/sessions"):
            return await ls.create_live_session(ls.LiveSessionIn(**body), r)
        if method == "GET" and path.startswith("/api/marketing/live/sessions/"):
            return await ls.get_live_session(path.rsplit("/", 1)[1], r)
        if method == "PUT" and path.startswith("/api/marketing/live/sessions/"):
            return await ls.update_live_session(path.rsplit("/", 1)[1], ls.LiveSessionUpdate(**body), r)
        raise AlatError(404, f"rute uji tidak ada: {method} {path}")


def _log(db, **kw):
    return [r for r in db.marketing_change_log.docs if all(r.get(k) == v for k, v in kw.items())]


def _forbid(coro, code=403):
    with pytest.raises(HTTPException) as ei:
        run(coro)
    assert ei.value.status_code == code, ei.value.detail
    return ei.value.detail


# ══════════════════════════════════════════════════════════════════════════════
# 1. CELAH IZIN (layar biasa + Asisten AI)
# ══════════════════════════════════════════════════════════════════════════════
def test_target_kreator_hanya_spv_manager_owner(env):
    tgt, db = env["tgt"], env["db"]
    body = tgt.CreatorTargetUpsert(creator_id="K1", year=2026, month=12, revenue_target=5_000_000)
    for u in (STAF, PIC, CS, KREATOR, GUDANG):
        env["pakai"](u)
        assert "target kreator" in _forbid(tgt.upsert_creator_target(body, Req(u)))
    assert not db.marketing_creator_targets.docs
    for u in (MGR, SPV, OWNER):
        env["pakai"](u)
        out = run(tgt.upsert_creator_target(body, Req(u)))
        assert out["target"]["revenue_target"] == 5_000_000
    assert len(db.marketing_creator_targets.docs) == 1
    # izin eksplisit dari owner tetap dihormati
    env["pakai"](dict(STAF, _permissions=["marketing.target.set"]))
    run(tgt.upsert_creator_target(body, Req(STAF)))


def test_hapus_target_baru_dijaga_seperti_menetapkan_dan_masuk_jejak(env):
    tgt, db = env["tgt"], env["db"]
    run(tgt.upsert_target(tgt.TargetUpsert(account_id="A1", year=2026, month=12, revenue_target=9e7), Req(MGR)))
    tid = db.marketing_account_targets.docs[0]["id"]
    env["pakai"](STAF)
    _forbid(tgt.delete_target(tid, Req(STAF), reason=None))
    db.marketing_period_locks.docs.append({"account_id": "A1", "period": "2026-12", "locked": True,
                                           "closed_by_name": "SPV Uji"})
    env["pakai"](MGR)
    assert "DITUTUP" in _forbid(tgt.delete_target(tid, Req(MGR), reason=None), 423)
    db.marketing_period_locks.docs.clear()
    run(tgt.delete_target(tid, Req(MGR), reason="uji"))
    assert not db.marketing_account_targets.docs
    j = _log(db, action="target_delete")[0]
    assert j["before"]["revenue_target"] == 9e7 and j["after"] is None and j["actor_role"] == "manager_marketing"
    _forbid(tgt.delete_target("tidak-ada", Req(MGR), reason=None), 404)


def _tugas(mt, **kw):
    return mt.TaskCreate(**{"task_type": "operational", "title": "Cek harga pesaing", **kw})


def test_buat_tugas_hanya_pic_atau_peran_yang_berhak(env):
    mt, db = env["mt"], env["db"]
    for u in (GUDANG, CS, KREATOR, STAF2):
        env["pakai"](u)
        assert "PIC" in _forbid(mt.create_task(_tugas(mt, account_id="A1"), Req(u)))
    # staf yang PIC toko A1 (Manajemen Akun) boleh untuk A1, tidak untuk tugas tanpa toko / toko lain
    env["pakai"](STAF)
    run(mt.create_task(_tugas(mt, account_id="A1"), Req(STAF)))
    _forbid(mt.create_task(_tugas(mt), Req(STAF)))
    _forbid(mt.create_task(_tugas(mt, account_id="A2"), Req(STAF)))
    for u in (MGR, SPV, PIC, OWNER):                                     # PIC (pic_toko) memegang A2
        env["pakai"](u)
        run(mt.create_task(_tugas(mt, account_id="A2"), Req(u)))
    env["pakai"](PIC)                                                    # peran PIC, tetapi toko A1 bukan miliknya
    assert "di-assign" in _forbid(mt.create_task(_tugas(mt, account_id="A1"), Req(PIC)))
    env["pakai"](dict(GUDANG, _permissions=["toko.manage"], _role_perms=["toko.manage"]))
    run(mt.create_task(_tugas(mt), Req(GUDANG)))
    assert len(db.marketing_tasks.docs) == 6


def _diskon(dis, **kw):
    return dis.DiscountIn(**{"account_id": "A1", "account_name": "Shopee Uji Satu", "platform": "shopee",
                             "name": "Flash sale uji", "discount_type": "flash_sale", "discount_value": 20,
                             "start_date": "2026-11-20", "end_date": "2026-11-22", **kw})


def test_diskon_hanya_tim_marketing_pengelola_toko(env):
    dis, db = env["dis"], env["db"]
    for u in (GUDANG, CS, KREATOR):
        env["pakai"](u)
        assert "kampanye diskon" in _forbid(dis.create_discount(_diskon(dis), Req(u)))
    env["pakai"](STAF)
    out = run(dis.create_discount(_diskon(dis), Req(STAF)))["data"]
    _forbid(dis.create_discount(_diskon(dis, account_id="A2", account_name="TikTok Uji Dua"), Req(STAF)))
    env["pakai"](MGR)
    other = run(dis.create_discount(_diskon(dis, account_id="A2", account_name="TikTok Uji Dua"), Req(MGR)))["data"]
    env["pakai"](STAF)
    _forbid(dis.update_discount(other["id"], dis.DiscountUpdate(name="ubah"), Req(STAF)))         # toko lain
    _forbid(dis.update_discount(out["id"], dis.DiscountUpdate(account_id="A2"), Req(STAF)))       # pindah toko
    run(dis.update_discount(out["id"], dis.DiscountUpdate(discount_value=25), Req(STAF)))
    # peran yang izinnya SUDAH diatur owner: wajib toko.manage (fallback peran lama berhenti)
    env["pakai"](dict(STAF, _role_perms=["mod.mkt_content.view"], _permissions=["mod.mkt_content.view"]))
    _forbid(dis.create_discount(_diskon(dis), Req(STAF)))
    assert len(db.marketing_discounts.docs) == 2 and db.marketing_discounts.docs[0]["discount_value"] == 25


def _katalog(db):
    db.marketing_catalogs.docs += [{"id": "C1", "account_id": "A1"}, {"id": "C2", "account_id": "A2"}]
    db.marketing_catalog_items.docs += [
        {"id": "I1", "catalog_id": "C1", "sku": "SKU-1", "harga_jual": 100000.0, "price": 100000.0,
         "harga_coret": 130000.0, "stock_quantity": 5},
        {"id": "I2", "catalog_id": "C2", "account_id": "A2", "sku": "SKU-2", "harga_jual": 50000.0, "price": 50000.0}]


def test_harga_jual_katalog_dijaga_dan_riwayat_harga_dicatat(env):
    mci, db = env["mci"], env["db"]
    _katalog(db)
    for u in (GUDANG, KREATOR):
        env["pakai"](u)
        assert "harga jual" in _forbid(mci.update_catalog_item("C1", "I1", mci.CatalogItemUpdate(harga_jual=1), Req(u)))
    env["pakai"](STAF)
    _forbid(mci.update_catalog_item("C2", "I2", mci.CatalogItemUpdate(harga_jual=45000), Req(STAF)))  # toko lain
    run(mci.update_catalog_item("C1", "I1", mci.CatalogItemUpdate(harga_jual=95000, reason="ikut pesaing"), Req(STAF)))
    item = db.marketing_catalog_items.docs[0]
    assert item["harga_jual"] == 95000 and item["price"] == 95000 and "reason" not in item
    j = _log(db, entity="catalog_item", action="price_change")
    assert len(j) == 1 and j[0]["before"] == {"harga_jual": 100000.0} and j[0]["after"] == {"harga_jual": 95000.0}
    assert j[0]["actor_id"] == "u-staf" and j[0]["reason"] == "ikut pesaing" and j[0]["account_id"] == "A1"
    env["pakai"](SPV)
    run(mci.update_catalog_item("C1", "I1", mci.CatalogItemUpdate(platform_url="https://toko.uji/1"), Req(SPV)))
    run(mci.update_catalog_item("C1", "I1", mci.CatalogItemUpdate(harga_jual=95000), Req(SPV)))   # tidak berubah
    assert len(_log(db, action="price_change")) == 1
    run(mci.update_catalog_item("C1", "I1", mci.CatalogItemUpdate(original_price=140000), Req(SPV)))
    assert _log(db, action="price_change")[-1]["after"] == {"harga_coret": 140000.0}


def test_jejak_perubahan_memberi_label_manusiawi_untuk_aksi_baru():
    from routes import marketing_change_log as cl
    assert cl.ENTITY_LABEL["catalog_item"] == "Harga jual katalog"
    assert cl.ACTION_LABEL["price_change"] == "Harga jual diubah" and cl.ACTION_LABEL["target_delete"] == "Target dihapus"
    d = cl._diff({"harga_jual": 100000.0}, {"harga_jual": 95000.0})
    assert d == [{"field": "harga_jual", "field_label": "Harga jual", "before": 100000.0, "after": 95000.0,
                  "is_money": True, "is_list": False}]


# ══════════════════════════════════════════════════════════════════════════════
# 2. SKENARIO TARGET
# ══════════════════════════════════════════════════════════════════════════════
def test_pembantu_bulan_dan_pembulatan():
    assert SK.geser_bulan("2026-11", 2) == "2027-01" and SK.geser_bulan("2026-01", -1) == "2025-12"
    assert SK.jarak_bulan("2026-11", "2027-01") == 2
    assert SK.bulat_rp(12_345_678) == 12_300_000 and SK.bulat_rp(12_350_000) == 12_400_000
    assert SK.bulat_rp(1_234_567) == 1_230_000 and SK.bulat_rp(123_456) == 123_000
    assert SK.bulat_pesanan(1235) == 1240 and SK.bulat_pesanan(57.4) == 57


def test_tren_dan_musim_dibatasi():
    assert round(SK.tren_bulanan([100, 110, 120]), 4) == round(10 / 110, 4)
    assert SK.tren_bulanan([0, 100, 200]) == 0.10                 # toko baru: bulan nol dilewati, lalu dibatasi
    assert SK.tren_bulanan([0, 0, 100]) == 0.0 and SK.tren_bulanan([100, 80, 60]) < 0
    assert SK.faktor_musim([100, 100, 100], 150) == 1.5
    assert SK.faktor_musim([0, 0, 100], 150) is None              # < 2 bulan tahun lalu
    assert SK.faktor_musim([100, 100], 1000) == 1.6 and SK.faktor_musim([100, 100], 10) == 0.7
    assert SK.faktor_musim([100, 100], None) is None


def test_hitung_toko_tiga_skenario():
    h = SK.hitung_toko([90e6, 100e6, 110e6], [900, 1000, 1100], jarak=3)
    # D = 100 jt; tren 10%/bulan × 3 bulan = 30% → dibatasi 25%; tanpa musim → proyeksi 125 jt
    assert h["rata_rata_omzet"] == 100e6 and h["dampak_tren_persen"] == 25.0 and h["faktor_musim"] is None
    sk = h["skenario"]
    assert (sk["konservatif"]["target_omzet"], sk["realistis"]["target_omzet"], sk["agresif"]["target_omzet"]) == \
        (112_500_000, 125_000_000, 150_000_000)
    assert sk["realistis"]["target_pesanan"] == 1250 and sk["konservatif"]["target_pesanan"] == 1130
    assert sk["agresif"]["vs_rata_rata_persen"] == 50.0
    m = SK.hitung_toko([100e6] * 3, [1000] * 3, jarak=2, ly_dasar=[80e6] * 3, ly_target=120e6,
                       persen={"konservatif": -5, "realistis": 5, "agresif": 30})
    assert m["faktor_musim"] == 1.5 and m["proyeksi_omzet"] == 150e6
    assert m["skenario"]["realistis"]["target_omzet"] == 157_500_000
    assert m["skenario"]["realistis"]["vs_tahun_lalu_persen"] == 31.2
    assert SK.hitung_toko([0, 0, 0], [0, 0, 0], jarak=2) is None


def test_alat_skenario_target_lewat_endpoint_analitik(env):
    db = env["db"]
    db.marketing_account_targets.docs.append({"id": "T-A1-12", "account_id": "A1", "year": 2026, "month": 12,
                                              "revenue_target": 25_000_000, "orders_target": 90})
    ctx = Ctx(env, user=MGR)
    out = run(ab._DAFTAR["skenario_target"].handler(ctx, {}))
    h = out["hasil"]
    assert [c["params"] for c in ctx.calls] == [
        {"dari_bulan": "2026-08", "sampai_bulan": "2026-12"}, {"dari_bulan": "2025-08", "sampai_bulan": "2025-12"}]
    assert all(c["method"] == "GET" for c in ctx.calls) and out["_sumber"]
    assert h["bulan_target"] == "2026-12" and h["label_bulan_target"] == "Desember 2026"
    a1 = next(t for t in h["toko"] if t["toko_id"] == "A1")
    # A1: 27 jt / 30 jt / 33 jt (definisi omzet baku dari rekap harian) → rata-rata 30 jt
    assert [b["omzet"] for b in a1["bulan_dasar"]] == [27e6, 30e6, 33e6] and a1["rata_rata_omzet"] == 30e6
    assert a1["target_sekarang"] == {"omzet": 25_000_000, "pesanan": 90}
    assert a1["skenario"]["realistis"]["target_omzet"] == 37_500_000          # tren +25% (dibatasi), tanpa musim
    assert {t["toko_id"] for t in h["toko"]} == {"A1", "A2"}                 # A3 milik CV Sukma tidak ikut
    assert any("BELUM diperhitungkan" in s for s in h["asumsi"])
    isian = h["isian_pasang_target"]["realistis"]
    assert isian["bulan"] == "2026-12" and {"toko_id": "A1", "target_omzet": 37_500_000.0,
                                             "target_pesanan": 130} in isian["toko"]
    assert ab.periksa_skema(ab._DAFTAR["pasang_target_toko"].input_schema, isian) == []
    assert len(json.dumps(out, ensure_ascii=False, default=str)) <= 15000
    # pengisi isian mode uji (inti): `periode` + daftar objek PERTAMA di hasil = tabel_skenario dengan kunci isian
    assert h["periode"] == "2026-12"
    pertama = next(v for v in h.values() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v))
    assert pertama is h["tabel_skenario"]
    baris = next(x for x in pertama if x["toko_id"] == "A1")
    assert baris == {"toko_id": "A1", "toko": "Shopee Uji Satu", "konservatif": 33_800_000, "realistis": 37_500_000,
                     "agresif": 45_000_000, "target_omzet": 37_500_000, "target_pesanan": 130}
    tiruan = {"bulan": h["periode"], "skenario": "realistis",
              "toko": [{k: r[k] for k in ("toko_id", "target_omzet", "target_pesanan")} for r in pertama]}
    assert ab.periksa_skema(ab._DAFTAR["pasang_target_toko"].input_schema, tiruan) == []


def test_skenario_target_musim_tahun_lalu_dan_penolakan(env):
    db = env["db"]
    for m, v in (("2025-08", 2e6), ("2025-09", 2e6), ("2025-10", 2e6), ("2025-12", 3e6)):
        for d in range(1, 11):
            db.marketing_sales_data.docs.append(_rekap("A1", f"{m}-{d:02d}", v, 5))
    h = run(ab._DAFTAR["skenario_target"].handler(Ctx(env), {"toko_id": "A1"}))["hasil"]
    a1 = h["toko"][0]
    assert a1["faktor_musim"] == 1.5 and "Desember 2025" in a1["dasar_musim"]
    assert a1["proyeksi_omzet"] == 56_300_000 and any(s.startswith("Musim =") for s in h["asumsi"])
    with pytest.raises(AlatError) as ei:
        run(ab._DAFTAR["skenario_target"].handler(Ctx(env), {"bulan": "2026-10"}))
    assert ei.value.status == 400 and "sudah lewat" in ei.value.pesan
    with pytest.raises(AlatError):
        run(ab._DAFTAR["skenario_target"].handler(Ctx(env), {"persen_realistis": 30, "persen_agresif": 10}))
    # staf berlingkup toko hanya melihat tokonya sendiri
    h = run(ab._DAFTAR["skenario_target"].handler(Ctx(env, user=STAF), {}))["hasil"]
    assert [t["toko_id"] for t in h["toko"]] == ["A1"]


def test_skenario_target_banyak_toko_tetap_di_bawah_15rb(env):
    db = env["db"]
    for i in range(60):
        aid = f"Z{i:02d}"
        db.marketing_platform_accounts.docs.append(_akun(aid, f"Toko Uji Panjang Sekali Namanya {i:02d}"))
        for m in ("2026-08", "2026-09", "2026-10"):
            db.marketing_sales_data.docs.append(_rekap(aid, f"{m}-05", 1e6 + i * 1e5, 10))
    out = run(ab._DAFTAR["skenario_target"].handler(Ctx(env), {}))
    assert len(json.dumps(out, ensure_ascii=False, default=str)) <= 15000
    assert out["hasil"].get("dipotong_untuk_ai")


def test_deskripsi_alat_tanpa_tanggal_dan_skema_ketat():
    for nama in ("skenario_target", "pasang_target_toko", "rencana_anggaran_marketing", "buat_tugas_marketing",
                 "jadwalkan_konten", "jadwalkan_live"):
        a = ab._DAFTAR[nama]
        teks = json.dumps(a.untuk_api(), ensure_ascii=False)
        assert not re.search(r"\d{4}-\d{2}-\d{2}", teks) and "2026" not in teks, nama
        assert a.input_schema["additionalProperties"] is False
        assert a.kind == ("read" if nama == "skenario_target" else "action")
    assert ab._DAFTAR["pasang_target_toko"].kelas is TP.PasangTargetToko
    assert TP.PasangTargetToko._alat is ab._DAFTAR["pasang_target_toko"]      # bentuk dekorator inti


# ══════════════════════════════════════════════════════════════════════════════
# 3. ALAT TINDAKAN (Kontrak D)
# ══════════════════════════════════════════════════════════════════════════════
def _target_args(**kw):
    return {"bulan": "2026-12", "skenario": "realistis",
            "toko": [{"toko_id": "A1", "target_omzet": 37_500_000}, {"toko_id": "A2", "target_omzet": 12_000_000,
                                                                      "target_pesanan": 100}], **kw}


def test_pasang_target_siapkan_hanya_membaca_dan_rencana_sesuai_kontrak(env):
    db = env["db"]
    db.marketing_account_targets.docs.append({"id": "T1", "account_id": "A1", "year": 2026, "month": 12,
                                              "revenue_target": 30_000_000, "orders_target": 90,
                                              "health_score_target": 70, "notes": "catatan lama"})
    ctx = Ctx(env)
    r = run(TP.PasangTargetToko.siapkan(ctx, _target_args()))
    assert not ctx.tulis and {c["path"] for c in ctx.calls} == {
        "/api/marketing/analitik/target", "/api/marketing/targets", "/api/marketing/periods/locks"}
    assert r["judul"] == "Pasang target toko Desember 2026" and "skenario realistis" in r["ringkas"]
    assert r["perubahan"] == [
        {"label": "Shopee Uji Satu", "sebelum": "Rp 30.000.000 · 90 pesanan", "sesudah": "Rp 37.500.000 · 90 pesanan"},
        {"label": "TikTok Uji Dua", "sebelum": "—", "sesudah": "Rp 12.000.000 · 100 pesanan"}]
    assert r["catatan"][0] == "Periode Desember 2026 masih terbuka untuk semua toko ini."
    assert r["ubah"][0] == {"kunci": "toko.0.target_omzet", "label": "Target omzet Shopee Uji Satu",
                            "jenis": "rupiah", "nilai": 37_500_000.0}
    assert r["tautan"] == {"label": "Buka layar Target & Anggaran", "menu": "marketing-targets"}
    assert len(json.dumps(r, ensure_ascii=False)) <= 8000


def test_pasang_target_jalankan_lewat_endpoint_lalu_batalkan_memulihkan(env):
    db, tgt = env["db"], env["tgt"]
    db.marketing_account_targets.docs.append({"id": "T1", "account_id": "A1", "year": 2026, "month": 12,
                                              "revenue_target": 30_000_000, "orders_target": 90,
                                              "health_score_target": 70, "notes": "catatan lama"})
    ctx = Ctx(env)
    args = _target_args(alasan="pakai yang realistis")
    rencana = run(TP.PasangTargetToko.siapkan(ctx, args))
    hasil = run(TP.PasangTargetToko.jalankan(ctx, args, rencana))
    assert hasil["ringkas"] == "Target 2 toko Desember 2026 terpasang (total Rp 49.500.000)."
    assert hasil["sebelum"] == [{"label": "Shopee Uji Satu", "nilai": "Rp 30.000.000 · 90 pesanan"},
                                {"label": "TikTok Uji Dua", "nilai": "—"}]
    assert hasil["sesudah"][1] == {"label": "TikTok Uji Dua", "nilai": "Rp 12.000.000 · 100 pesanan"}
    w = ctx.tulis
    assert [(c["method"], c["path"]) for c in w] == [("POST", "/api/marketing/targets")] * 2
    assert all(c["headers"] == {"X-Via": "asisten-ai", "X-Asisten-Tindakan": "tdk-uji-1"} for c in w)
    a1 = next(d for d in db.marketing_account_targets.docs if d["account_id"] == "A1")
    assert (a1["revenue_target"], a1["orders_target"], a1["health_score_target"], a1["notes"]) == \
        (37_500_000, 90, 70, "catatan lama")                              # isian lain TIDAK tertimpa
    assert len(db.marketing_account_targets.docs) == 2
    j = _log(db, entity="marketing_account_targets")
    assert {x["action"] for x in j} == {"target_update", "target_create"}
    assert all(x["reason"] == "Asisten AI · skenario realistis · pakai yang realistis" for x in j)
    assert json.loads(json.dumps(hasil["pembatalan"]))                     # bisa disimpan sebagai JSON
    # — balikkan —
    ctx2 = Ctx(env)
    out = run(TP.PasangTargetToko.batalkan(ctx2, hasil["pembatalan"]))
    assert "1 target baru dihapus" in out["ringkas"]
    assert [(c["method"], c["path"].split("/")[-1] if c["method"] == "DELETE" else c["path"]) for c in ctx2.tulis] == \
        [("DELETE", next(x["target_id"] for x in hasil["pembatalan"]["toko"] if x["dibuat"])),
         ("POST", "/api/marketing/targets")]
    assert len(db.marketing_account_targets.docs) == 1
    a1 = db.marketing_account_targets.docs[0]
    assert (a1["account_id"], a1["revenue_target"], a1["orders_target"], a1["notes"]) == ("A1", 30_000_000, 90, "catatan lama")
    assert _log(db, action="target_delete")


def test_pasang_target_batalkan_menolak_bila_sudah_diubah_orang_lain(env):
    db, tgt = env["db"], env["tgt"]
    ctx = Ctx(env)
    args = {"bulan": "2026-12", "toko": [{"toko_id": "A1", "target_omzet": 40e6}]}
    hasil = run(TP.PasangTargetToko.jalankan(ctx, args, run(TP.PasangTargetToko.siapkan(ctx, args))))
    run(tgt.upsert_target(tgt.TargetUpsert(account_id="A1", year=2026, month=12, revenue_target=41e6), Req(MGR)))
    ctx2 = Ctx(env)
    with pytest.raises(AlatError) as ei:
        run(TP.PasangTargetToko.batalkan(ctx2, hasil["pembatalan"]))
    assert ei.value.status == 409 and "Rp 41.000.000" in ei.value.pesan and not ctx2.tulis


def test_pasang_target_penolakan_ramah(env):
    db = env["db"]
    with pytest.raises(AlatError) as ei:                                   # staf toko: bukan penulis target
        run(TP.PasangTargetToko.siapkan(Ctx(env, user=STAF), _target_args()))
    assert ei.value.status == 403 and "SPV/Manager Marketing" in ei.value.pesan
    with pytest.raises(AlatError) as ei:                                   # toko CV lain
        run(TP.PasangTargetToko.siapkan(Ctx(env), {"bulan": "2026-12", "toko": [{"toko_id": "A3", "target_omzet": 1e6}]}))
    assert ei.value.status == 403 and "A3" in ei.value.pesan and "CV DA" in ei.value.pesan
    # …tetapi boleh bila pilihan CV-nya Sukma
    r = run(TP.PasangTargetToko.siapkan(Ctx(env, cv="SMU"), {"bulan": "2026-12",
                                                            "toko": [{"toko_id": "A3", "target_omzet": 1e6}]}))
    assert r["perubahan"][0]["label"] == "Shopee Sukma Uji"
    db.marketing_period_locks.docs.append({"account_id": "A2", "period": "2026-12", "locked": True})
    with pytest.raises(AlatError) as ei:
        run(TP.PasangTargetToko.siapkan(Ctx(env), _target_args()))
    assert ei.value.status == 423 and "TikTok Uji Dua" in ei.value.pesan
    with pytest.raises(AlatError) as ei:
        run(TP.PasangTargetToko.siapkan(Ctx(env), {"bulan": "2026-10", "toko": [{"toko_id": "A1", "target_omzet": 1}]}))
    assert ei.value.status == 400
    with pytest.raises(AlatError):
        run(TP.PasangTargetToko.siapkan(Ctx(env), {"bulan": "2026-12", "toko": [
            {"toko_id": "A1", "target_omzet": 1}, {"toko_id": "A1", "target_omzet": 2}]}))


def test_pasang_target_gagal_di_tengah_dikembalikan_semua(env):
    db = env["db"]
    db.marketing_account_targets.docs.append({"id": "T1", "account_id": "A1", "year": 2026, "month": 12,
                                              "revenue_target": 30e6, "orders_target": 90})
    ctx = Ctx(env)
    args = _target_args()
    rencana = run(TP.PasangTargetToko.siapkan(ctx, args))
    db.marketing_period_locks.docs.append({"account_id": "A2", "period": "2026-12", "locked": True})  # ditutup sesudah kartu
    with pytest.raises(AlatError) as ei:
        run(TP.PasangTargetToko.jalankan(ctx, args, rencana))
    assert ei.value.status == 423 and "tidak ada yang berubah" in ei.value.pesan
    assert [(d["account_id"], d["revenue_target"]) for d in db.marketing_account_targets.docs] == [("A1", 30e6)]


def test_rencana_anggaran_siapkan_jalankan_batalkan(env):
    db = env["db"]
    ctx = Ctx(env)
    args = {"periode": "2026-12", "toko": [{"toko_id": "A1", "anggaran": {"ads": 5_000_000, "kol": 2_000_000}}],
            "alasan": "kampanye 12.12"}
    db.marketing_budgets.docs.append({"id": "B1", "account_id": "A1", "period": "2026-12", "notes": "lama",
                                      "budget_by_category": {"ads": 3_000_000, "sample": 500_000}})
    r = run(TP.RencanaAnggaranMarketing.siapkan(ctx, args))
    assert not ctx.tulis
    assert {"label": "Shopee Uji Satu · Iklan", "sebelum": "Rp 3.000.000", "sesudah": "Rp 5.000.000"} in r["perubahan"]
    assert {"label": "Shopee Uji Satu · Total", "sebelum": "Rp 3.500.000", "sesudah": "Rp 7.500.000"} in r["perubahan"]
    assert any("periode 7 hari" in p for p in r["peringatan"])             # layar bawaan mingguan
    hasil = run(TP.RencanaAnggaranMarketing.jalankan(ctx, args, r))
    doc = db.marketing_budgets.docs[0]
    assert doc["budget_by_category"] == {"ads": 5e6, "kol": 2e6, "komisi": 0.0, "livehost": 0.0, "sample": 5e5,
                                         "diskon": 0.0} and doc["notes"] == "lama"
    assert _log(db, action="budget_upsert")[-1]["reason"] == "Asisten AI · kampanye 12.12"
    run(TP.RencanaAnggaranMarketing.batalkan(Ctx(env), hasil["pembatalan"]))
    assert db.marketing_budgets.docs[0]["budget_by_category"]["ads"] == 3e6
    assert db.marketing_budgets.docs[0]["budget_by_category"]["kol"] == 0.0
    with pytest.raises(AlatError) as ei:
        run(TP.RencanaAnggaranMarketing.siapkan(Ctx(env, user=STAF), args))
    assert ei.value.status == 403 and "rencana anggaran" in ei.value.pesan


def test_rencana_anggaran_batalkan_toko_baru_jadi_nol_dan_periksa_perubahan(env):
    db = env["db"]
    ctx = Ctx(env)
    args = {"periode": "2026-11-16", "toko": [{"toko_id": "A2", "anggaran": {"ads": 1_000_000}}]}
    hasil = run(TP.RencanaAnggaranMarketing.jalankan(ctx, args, run(TP.RencanaAnggaranMarketing.siapkan(ctx, args))))
    assert db.marketing_budgets.docs[0]["period"] == "2026-11-16"
    out = run(TP.RencanaAnggaranMarketing.batalkan(Ctx(env), hasil["pembatalan"]))
    assert "kini Rp 0" in out["ringkas"] and sum(db.marketing_budgets.docs[0]["budget_by_category"].values()) == 0
    hasil = run(TP.RencanaAnggaranMarketing.jalankan(ctx, args, {}))
    db.marketing_budgets.docs[0]["budget_by_category"]["ads"] = 9e6                       # diubah orang lain
    with pytest.raises(AlatError) as ei:
        run(TP.RencanaAnggaranMarketing.batalkan(Ctx(env), hasil["pembatalan"]))
    assert ei.value.status == 409


def test_buat_tugas_pic_toko_bawaan_dan_batalkan(env):
    db = env["db"]
    ctx = Ctx(env)
    args = {"tugas": [{"judul": "Pasang voucher 12.12", "toko_id": "A1", "tenggat": "2026-11-20",
                       "prioritas": "high", "daftar_periksa": ["Buat voucher", "Cek tampilan"]},
                      {"judul": "Rekap ulasan minggu ini", "ditugaskan_ke": "Staf Dua", "jenis": "review"}]}
    r = run(TP.BuatTugasMarketing.siapkan(ctx, args))
    assert not ctx.tulis
    assert r["perubahan"][0]["sesudah"] == ("Operasional · prioritas tinggi · Shopee Uji Satu · untuk Staf Uji · "
                                            "20 November 2026 17:00")
    assert "untuk Staf Dua" in r["perubahan"][1]["sesudah"]
    hasil = run(TP.BuatTugasMarketing.jalankan(ctx, args, r))
    t0, t1 = db.marketing_tasks.docs
    assert (t0["assigned_to"], t0["account_id"], t0["priority"], t0["status"]) == ("u-staf", "A1", "high", "to_do")
    assert t0["due_date"] == "2026-11-20T10:00:00.000Z" and len(t0["checklist"]) == 2
    assert (t1["assigned_to"], t1["task_type"]) == ("u-staf2", "review")
    t1["status"] = "in_progress"                                           # sudah mulai dikerjakan
    with pytest.raises(AlatError) as ei:
        run(TP.BuatTugasMarketing.batalkan(Ctx(env), hasil["pembatalan"]))
    assert ei.value.status == 409 and t0["status"] == "to_do"
    t1["status"] = "to_do"
    run(TP.BuatTugasMarketing.batalkan(Ctx(env), hasil["pembatalan"]))
    assert [t["status"] for t in db.marketing_tasks.docs] == ["cancelled", "cancelled"]


def test_buat_tugas_aturan_pembuat_dan_isian(env):
    with pytest.raises(AlatError) as ei:                                   # staf bukan PIC toko A2
        run(TP.BuatTugasMarketing.siapkan(Ctx(env, user=STAF), {"tugas": [{"judul": "Tugas uji", "toko_id": "A2"}]}))
    assert ei.value.status == 403
    r = run(TP.BuatTugasMarketing.siapkan(Ctx(env, user=STAF), {"tugas": [{"judul": "Tugas uji", "toko_id": "A1"}]}))
    assert "untuk Staf Uji" in r["perubahan"][0]["sesudah"]
    for isian, kata in (({"judul": "Input omzet", "jenis": "data_entry"}, "wajib menyebut tokonya"),
                        ({"judul": "Tugas uji", "tenggat": "2026-11-01"}, "sudah lewat"),
                        ({"judul": "Tugas uji", "ditugaskan_ke": "Tak Dikenal"}, "tidak ditemukan"),
                        ({"judul": "Tugas uji", "ditugaskan_ke": "Uji"}, "beberapa orang"),
                        ({"judul": "Tugas uji", "toko_id": "A2", "ditugaskan_ke": "pic_toko"}, "belum punya PIC")):
        with pytest.raises(AlatError) as ei:
            run(TP.BuatTugasMarketing.siapkan(Ctx(env), {"tugas": [isian]}))
        assert kata in ei.value.pesan, isian


def test_jadwalkan_konten_dan_batalkan_kecuali_sudah_tayang(env):
    db = env["db"]
    ctx = Ctx(env)
    args = {"konten": [{"toko_id": "A1", "tanggal": "2026-11-12", "jam": "19:00", "jenis": "reels_tiktok",
                        "judul": "Teaser 12.12", "kreator_id": "K1"},
                       {"toko_id": "A2", "tanggal": "2026-11-13", "jenis": "foto_produk", "judul": "Foto koleksi baru"}]}
    r = run(TP.JadwalkanKonten.siapkan(ctx, args))
    assert not ctx.tulis and r["perubahan"][0] == {"label": "Shopee Uji Satu · 12 November 2026 19:00",
                                                   "sebelum": "—", "sesudah": "Reels / TikTok: Teaser 12.12"}
    hasil = run(TP.JadwalkanKonten.jalankan(ctx, args, r))
    k0, k1 = db.marketing_content_calendar.docs
    assert (k0["account_id"], k0["platform"], k0["status"], k0["post_time"], k0["creator_id"]) == \
        ("A1", "shopee", "scheduled", "19:00", "K1")
    assert (k1["platform"], k1["account_name"]) == ("tiktok", "TikTok Uji Dua")
    k1["status"], k1["published_url"] = "posted", "https://tiktok.uji/1"
    with pytest.raises(AlatError) as ei:
        run(TP.JadwalkanKonten.batalkan(Ctx(env), hasil["pembatalan"]))
    assert ei.value.status == 409 and "TAYANG" in ei.value.pesan and k0["status"] == "scheduled"
    k1["status"] = "scheduled"
    run(TP.JadwalkanKonten.batalkan(Ctx(env), hasil["pembatalan"]))
    assert [k["status"] for k in db.marketing_content_calendar.docs] == ["cancelled", "cancelled"]
    for isian, kata in (({"toko_id": "A1", "tanggal": "2026-11-12", "jenis": "podcast", "judul": "Uji"}, "tidak dikenal"),
                        ({"toko_id": "A1", "tanggal": "2026-11-01", "jenis": "story", "judul": "Uji"}, "sudah lewat")):
        with pytest.raises(AlatError) as ei:
            run(TP.JadwalkanKonten.siapkan(Ctx(env), {"konten": [isian]}))
        assert kata in ei.value.pesan
    with pytest.raises(AlatError) as ei:                                   # staf: toko lain di luar lingkup
        run(TP.JadwalkanKonten.siapkan(Ctx(env, user=STAF), {"konten": [dict(args["konten"][1])]}))
    assert ei.value.status == 403


def test_jadwalkan_live_host_harus_di_assign_dan_batalkan(env):
    db = env["db"]
    ctx = Ctx(env)
    args = {"sesi": [{"toko_id": "A1", "host": "sari", "tanggal": "2026-11-11", "jam_mulai": "20:00",
                      "durasi_menit": 90, "judul": "Live 11.11"}]}
    r = run(TP.JadwalkanLive.siapkan(ctx, args))
    assert not ctx.tulis and r["perubahan"][0]["sesudah"] == "Live 11.11 · host Host Uji Sari · 90 menit"
    hasil = run(TP.JadwalkanLive.jalankan(ctx, args, r))
    s = db.marketing_live_sessions.docs[0]
    assert (s["account_id"], s["host_id"], s["status"], s["start_time"], s["duration_minutes"]) == \
        ("A1", "H1", "scheduled", "20:00", 90)
    run(TP.JadwalkanLive.batalkan(Ctx(env), hasil["pembatalan"]))
    assert db.marketing_live_sessions.docs[0]["status"] == "cancelled"
    with pytest.raises(AlatError) as ei:
        run(TP.JadwalkanLive.siapkan(Ctx(env), {"sesi": [dict(args["sesi"][0], host="Host Uji Bima")]}))
    assert "belum di-assign" in ei.value.pesan
    hasil = run(TP.JadwalkanLive.jalankan(Ctx(env), args, {}))
    db.marketing_live_sessions.docs[-1]["status"] = "completed"
    with pytest.raises(AlatError) as ei:
        run(TP.JadwalkanLive.batalkan(Ctx(env), hasil["pembatalan"]))
    assert ei.value.status == 409


def test_semua_tindakan_terdaftar_dengan_skema_yang_menerima_contoh(env):
    contoh = {
        "pasang_target_toko": _target_args(),
        "rencana_anggaran_marketing": {"periode": "2026-12", "toko": [{"toko_id": "A1", "anggaran": {"ads": 1}}]},
        "buat_tugas_marketing": {"tugas": [{"judul": "Uji tugas"}]},
        "jadwalkan_konten": {"konten": [{"toko_id": "A1", "tanggal": "2026-11-12", "jenis": "story", "judul": "Uji"}]},
        "jadwalkan_live": {"sesi": [{"toko_id": "A1", "host": "H1", "tanggal": "2026-11-12", "jam_mulai": "20:00",
                                     "judul": "Uji"}]},
    }
    for nama, isian in contoh.items():
        a = ab._DAFTAR[nama]
        assert ab.periksa_skema(a.input_schema, isian) == [], nama
        assert a.risiko == "rendah" and a.menu and a.label
        assert ab.periksa_skema(a.input_schema, {**isian, "liar": 1}), nama      # additionalProperties False
        assert hasattr(a.kelas, "batalkan")


def test_semua_tindakan_menolak_mode_gabungan(env):
    contoh = {
        TP.PasangTargetToko: _target_args(),
        TP.RencanaAnggaranMarketing: {"periode": "2026-12", "toko": [{"toko_id": "A1", "anggaran": {"ads": 1}}]},
        TP.BuatTugasMarketing: {"tugas": [{"judul": "Uji tugas"}]},
        TP.JadwalkanKonten: {"konten": [{"toko_id": "A1", "tanggal": "2026-11-12", "jenis": "story", "judul": "Uji"}]},
        TP.JadwalkanLive: {"sesi": [{"toko_id": "A1", "host": "H1", "tanggal": "2026-11-12", "jam_mulai": "20:00",
                                     "judul": "Uji"}]},
    }
    for kelas, isian in contoh.items():
        ctx = Ctx(env, cv="ALL")
        with pytest.raises(AlatError) as ei:
            run(kelas.siapkan(ctx, isian))
        assert ei.value.status == 400 and "Gabungan" in ei.value.pesan and not ctx.calls, kelas.__name__
    # skenario (baca) tetap boleh di Gabungan
    h = run(ab._DAFTAR["skenario_target"].handler(Ctx(env, cv="ALL"), {}))["hasil"]
    assert {t["toko_id"] for t in h["toko"]} == {"A1", "A2"}       # A3 (Sukma) tanpa penjualan bulan dasar
