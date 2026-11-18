"""Uji unit HERMETIK — banyak akun per kreator + sesi live di akun kreator (18 Nov 2026, owner: "creator juga bisa
tambahkan akun lain seperti akun kreator yang di manage dll jadi tidak harus 1 toko 1 akun").

Jalankan:  cd backend && python -m pytest tests/unit/test_akun_kreator.py -q
"""
import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402
import _fake_mongo as fm  # noqa: E402
from core import akun_kreator as ak  # noqa: E402

USER = {"id": "u1", "name": "Uji", "email": "u@x", "role": "superadmin"}


def run(coro):
    return asyncio.run(coro)


def test_normalisasi_banyak_akun_per_platform():
    akun = ak.normalisasi([
        {"platform": "tiktokshop", "username": "@rayona.live", "jenis": "dikelola", "toko_ids": ["T1", "X"]},
        {"platform": "tiktok", "username": "@rayona.style"},
        {"platform": "TikTok", "username": "@Rayona.Live"},                 # kembar → disatukan
        {"platform": "shopee", "username": "   "},                          # kosong → dilewati
    ], toko_valid={"T1"})
    assert [(a["platform"], a["username"], a["jenis"], a["toko_ids"]) for a in akun] == [
        ("tiktok", "@rayona.live", "dikelola", ["T1"]), ("tiktok", "@rayona.style", "pribadi", [])]
    assert ak.platforms_dari(akun) == {"tiktok": "@rayona.live"}
    with pytest.raises(HTTPException):
        ak.normalisasi([{"platform": "friendster", "username": "x"}])
    with pytest.raises(HTTPException):
        ak.normalisasi([{"platform": "tiktok", "username": "x", "jenis": "sewa"}])


def test_kreator_lama_dibaca_dari_platforms_dan_handle_semua_akun():
    lama = {"platforms": {"tiktok": "@ayu", "shopee": "ayu_shop"}}
    assert [(a["platform"], a["username"]) for a in ak.akun_of(lama)] == [("tiktok", "@ayu"), ("shopee", "ayu_shop")]
    baru = {"platforms": {"tiktok": "@ayu"}, "accounts": [{"id": "a1", "platform": "tiktok", "username": "@ayu"},
                                                          {"id": "a2", "platform": "tiktok", "username": "@ayu.kedua"}]}
    assert ak.handles(baru) == ["@ayu", "@ayu.kedua"]


def test_tanda_strip_bukan_akun_dan_tidak_bentrok():
    """VPS 18 Nov: 3 kreator mengisi Shopee lama dengan "-" (artinya tidak ada). Itu bukan akun — kalau dihitung,
    menyimpan ulang kreator mana pun ditolak "sudah tercatat milik kreator lain"."""
    assert ak.akun_of({"platforms": {"tiktok": "@ayu", "shopee": "-"}}) == [
        {"id": "lama-tiktok", "platform": "tiktok", "username": "@ayu", "jenis": "pribadi", "toko_ids": []}]
    assert ak.normalisasi([{"platform": "shopee", "username": "—"}, {"platform": "shopee", "username": " - "}]) == []
    assert ak.handles({"platforms": {"shopee": "-"}}) == []
    db = fm.FakeDB()
    db.marketing_kol_creators.docs += [{"id": "c1", "name": "Novita", "platforms": {"tiktok": "@nov", "shopee": "-"}}]
    run(ak.cek_bentrok(db, [{"platform": "shopee", "username": "-"}], "c2"))      # tidak dianggap bentrok


def _env(monkeypatch):
    import routes.marketing_kol_creators as kc
    db = fm.FakeDB()
    db.marketing_platform_accounts.docs += [{"id": "T1", "account_name": "Tiktok Rayona", "platform": "tiktokshop"}]

    async def auth(req):
        return dict(USER)

    async def none(*a, **k):
        return None

    async def gabung(db_, user, baru, lama, apa=""):
        return list(baru or [])
    monkeypatch.setattr(kc, "require_auth", auth)
    monkeypatch.setattr(kc, "get_db", lambda: db)
    monkeypatch.setattr(kc, "log_activity", none)
    monkeypatch.setattr(kc._scope, "toko_lingkup", none)
    monkeypatch.setattr(kc._scope, "gabung_toko_terlihat", gabung)
    req = fm.FakeRequest()
    req.state.user = dict(USER)
    return kc, db, req


def test_buat_dan_ubah_kreator_dengan_banyak_akun_dan_bentrok(monkeypatch):
    kc, db, req = _env(monkeypatch)
    from routes.marketing_kol_shared import CreatorCreate, CreatorUpdate
    run(kc.create_creator(CreatorCreate(name="Ayu", creator_code="KOL-1", assigned_account_ids=["T1"], accounts=[
        {"platform": "tiktok", "username": "@ayu"},
        {"platform": "tiktok", "username": "@rayona.live", "jenis": "dikelola", "toko_ids": ["T1"]}]), req))
    c = db.marketing_kol_creators.docs[0]
    assert len(c["accounts"]) == 2 and c["platforms"] == {"tiktok": "@ayu"}
    with pytest.raises(HTTPException) as e:          # akun yang sama tidak boleh milik dua kreator
        run(kc.create_creator(CreatorCreate(name="Budi", creator_code="KOL-2",
                                            accounts=[{"platform": "tiktok", "username": "@Rayona.Live"}]), req))
    assert "sudah tercatat milik kreator Ayu" in e.value.detail
    run(kc.update_creator(c["id"], CreatorUpdate(accounts=[{"platform": "shopee", "username": "ayu_shop"}]), req))
    c = db.marketing_kol_creators.docs[0]
    assert [a["username"] for a in c["accounts"]] == ["ayu_shop"] and c["platforms"] == {"shopee": "ayu_shop"}
    # kreator lama (tanpa `accounts`) tetap tampil dengan akunnya
    db.marketing_kol_creators.docs.append({"id": "lama", "name": "Lama", "creator_code": "KOL-0",
                                           "platforms": {"tiktok": "@lama"}, "assigned_account_ids": []})
    out = run(kc.get_creator("lama", req))
    assert out["accounts"][0]["username"] == "@lama"


def test_pesanan_afiliasi_dari_akun_kedua_tercatat_ke_kreatornya():
    from core import marketing_account_scope as sc
    db = fm.FakeDB()
    db[sc.CREATORS].docs.append({"id": "c1", "name": "Ayu", "creator_code": "KOL-1", "platforms": {"tiktok": "@ayu"},
                                 "accounts": [{"id": "a1", "platform": "tiktok", "username": "@ayu"},
                                              {"id": "a2", "platform": "tiktok", "username": "@rayona.live"}]})
    assert run(sc.creator_for_handle(db, "rayona.live"))["id"] == "c1"


def test_sesi_live_di_akun_kreator(monkeypatch):
    import routes.marketing_kol_ops as ko
    from routes.marketing_kol_shared import SessionCreate
    db = fm.FakeDB()
    db.marketing_platform_accounts.docs.append({"id": "T1", "account_name": "Tiktok Rayona", "platform": "tiktokshop"})
    db.marketing_kol_creators.docs.append({"id": "c1", "name": "Ayu", "creator_code": "KOL-1",
                                           "assigned_account_ids": ["T1"],
                                           "accounts": [{"id": "a2", "platform": "tiktok", "username": "@rayona.live",
                                                         "jenis": "dikelola"}]})

    async def auth(req):
        return dict(USER)

    async def none(*a, **k):
        return None
    monkeypatch.setattr(ko, "require_auth", auth)
    monkeypatch.setattr(ko, "get_db", lambda: db)
    monkeypatch.setattr(ko, "log_activity", none)
    import routes.marketing_live_sales_sync as ls
    monkeypatch.setattr(ls, "sync_live_sales_to_marketing", none)
    req = fm.FakeRequest()
    req.state.user = dict(USER)
    run(ko.create_session(SessionCreate(creator_id="c1", account_id="T1", date="2026-11-18", platform="tiktokshop",
                                        creator_account_id="a2", revenue=500000), req))
    s = db.marketing_creator_sessions.docs[0]
    assert (s["live_di"], s["live_account_username"], s["account_id"], s["revenue"]) == ("akun_kreator", "@rayona.live", "T1", 500000)
    run(ko.create_session(SessionCreate(creator_id="c1", account_id="T1", date="2026-11-18", platform="tiktokshop"), req))
    assert db.marketing_creator_sessions.docs[1]["live_di"] == "akun_toko"
    with pytest.raises(HTTPException):
        run(ko.create_session(SessionCreate(creator_id="c1", account_id="T1", date="2026-11-18", platform="tiktokshop",
                                            creator_account_id="tidak-ada"), req))
