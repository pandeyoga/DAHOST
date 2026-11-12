"""Uji HERMETIK Asisten AI per pengguna (keputusan owner 10 Nov 2026) — saklar per akun + batas harian.

Mongo = tiruan in-memory (`_fake_mongo`), setelan AI dibaca dari dict uji, mesin jawaban diganti tiruan:
TIDAK ada panggilan Anthropic sungguhan.

Jalankan:  cd backend && python -m pytest tests/unit/test_asisten_ai_per_pengguna.py -n 0 -q
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ai_fakes  # noqa: E402,F401 — env uji (JWT_SECRET, MONGO_URL tiruan) + path backend; tanpa koneksi DB
from _fake_mongo import FakeDB  # noqa: E402

import ai_cost_tracker as t  # noqa: E402
from core.asisten_ai import akses_pengguna as akp  # noqa: E402
from core.asisten_ai import mesin  # noqa: E402
from core.asisten_ai import tindakan as tdk  # noqa: E402
from routes import ai_usage_monitor as mon  # noqa: E402
from routes import asisten_ai_routes as r  # noqa: E402
from utils.waktu import today_wib, wib_date_str  # noqa: E402

OWNER = {"id": "u-owner", "name": "Pemilik", "email": "owner@contoh.test", "role": "owner", "status": "active"}
SUPER = {"id": "u-super", "name": "Super", "email": "super@contoh.test", "role": "superadmin", "status": "active"}
ADMIN = {"id": "u-admin", "name": "Admin", "email": "admin@contoh.test", "role": "admin", "status": "active"}
STAF = {"id": "u-staf", "name": "Staf Gudang", "email": "staf@contoh.test", "role": "staff_gudang", "status": "active"}
MGR = {"id": "u-mgr", "name": "Manajer", "email": "mgr@contoh.test", "role": "manager", "status": "active"}
VENDOR = {"id": "u-vendor", "name": "Vendor", "email": "v@contoh.test", "role": "vendor", "status": "active"}
PIC = {"id": "u-pic", "name": "PIC Toko", "email": "pic@contoh.test", "role": "pic_toko", "status": "active"}
NONAKTIF = {"id": "u-off", "name": "Keluar", "email": "off@contoh.test", "role": "staff_gudang", "status": "inactive",
            "active": False}


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class Req:
    """Request palsu: json(), headers (token), app, state."""

    def __init__(self, body=None):
        self._body = body or {}
        self.headers = {"Authorization": "Bearer tok-uji"}
        self.app = None
        self.state = SimpleNamespace()
        self.client = SimpleNamespace(host="127.0.0.1")

    async def json(self):
        return dict(self._body)


@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    for u in (OWNER, SUPER, ADMIN, STAF, MGR, VENDOR, PIC, NONAKTIF):
        db.users.docs.append(dict(u))
    setelan = {**t._default_ai_settings()}
    state = {"u": STAF}

    async def _setelan(*_a, **_k):
        return dict(setelan)

    async def _auth(_req):
        return dict(state["u"])

    monkeypatch.setattr(t, "get_ai_settings", _setelan)
    monkeypatch.setattr(mon, "get_ai_settings", _setelan)
    monkeypatch.setattr(r, "get_db", lambda: db)
    monkeypatch.setattr(mon, "get_db", lambda: db)
    monkeypatch.setattr(r, "require_auth", _auth)
    monkeypatch.setattr(mon, "require_auth", _auth)
    return SimpleNamespace(db=db, setelan=setelan, state=state)


def _sse(resp) -> list:
    async def _kumpul():
        return [c if isinstance(c, str) else c.decode() async for c in resp.body_iterator]
    out = []
    for c in run(_kumpul()):
        m = re.match(r"event: (\w+)\ndata: (.*)\n\n$", c, re.S)
        assert m, c
        out.append((m.group(1), json.loads(m.group(2))))
    return out


def _pertanyaan(db, uid, dibuat, *, peran="user", otomatis=False):
    d = {"id": f"m-{len(db.ai_chat_messages.docs)}", "sesi_id": "s-1", "user_id": uid, "peran": peran,
         "dibuat": dibuat, "status": "selesai"}
    if otomatis:
        d["otomatis"] = True
    db.ai_chat_messages.docs.append(d)


def _sekarang_iso():
    return datetime.now(timezone.utc).isoformat()


def _kemarin_iso():
    return (datetime.fromisoformat(akp.awal_hari_iso()) - timedelta(seconds=1)).isoformat()


# ═══ Aturan efektif (fungsi murni) ═══════════════════════════════════════════
def test_bawaan_staf_mati_owner_superadmin_selalu_aktif():
    s = t._default_ai_settings()
    assert s["asisten_pengguna_bawaan_aktif"] is False and s["asisten_batas_pertanyaan_harian"] == 0
    a = akp.aturan_dari(STAF, "staff_gudang", s)
    assert (a["aktif"], a["sumber"], a["batas_pertanyaan"], a["batas_tindakan"]) == (False, "bawaan", 0, 30)
    for u in (OWNER, SUPER):
        a = akp.aturan_dari({**u, "asisten_ai": {"aktif": False}}, u["role"], s)
        assert a["aktif"] is True and a["sumber"] == "peran" and a["selalu_aktif"] is True
    # admin BUKAN selalu aktif — ikut bawaan
    assert akp.aturan_dari(ADMIN, "admin", s)["aktif"] is False


def test_akun_menimpa_bawaan_dan_batas_per_akun():
    s = {**t._default_ai_settings(), "asisten_pengguna_bawaan_aktif": True, "asisten_batas_pertanyaan_harian": 20,
         "asisten_batas_tindakan_harian": 15}
    assert akp.aturan_dari(STAF, None, s)["aktif"] is True
    a = akp.aturan_dari({**STAF, "asisten_ai": {"aktif": False}}, None, s)
    assert (a["aktif"], a["sumber"]) == (False, "akun")
    a = akp.aturan_dari({**STAF, "asisten_ai": {"batas_pertanyaan_harian": 5, "batas_tindakan_harian": 0}}, None, s)
    assert (a["batas_pertanyaan"], a["batas_pertanyaan_sumber"]) == (5, "akun")
    assert (a["batas_tindakan"], a["batas_tindakan_sumber"]) == (0, "akun")
    # nilai tersimpan rusak diabaikan → bawaan
    a = akp.aturan_dari({**STAF, "asisten_ai": {"aktif": "ya", "batas_pertanyaan_harian": "x",
                                                "batas_tindakan_harian": 5000}}, None, s)
    assert (a["aktif"], a["sumber"], a["batas_pertanyaan"], a["batas_tindakan"]) == (True, "bawaan", 20, 15)


def test_rapikan_masukan_validasi():
    assert akp.rapikan_masukan({"aktif": True, "batas_pertanyaan_harian": "10", "batas_tindakan_harian": ""},
                               peran_target="staff_gudang") == {
        "aktif": True, "batas_pertanyaan_harian": 10, "batas_tindakan_harian": None}
    assert akp.rapikan_masukan({"aktif": None}, peran_target="staff_gudang") == {"aktif": None}
    salah = [({"aktif": "ya"}, "staff_gudang"), ({"aktif": False}, "owner"), ({"aktif": False}, "superadmin"),
             ({"batas_pertanyaan_harian": 1001}, "x"), ({"batas_tindakan_harian": -1}, "x"),
             ({"batas_tindakan_harian": True}, "x"), ({"batas_pertanyaan_harian": 2.5}, "x"),
             ({"batas_pertanyaan_harian": "dua"}, "x"), ({}, "x")]
    for body, peran in salah:
        with pytest.raises(ValueError):
            akp.rapikan_masukan(body, peran_target=peran)


def test_hitung_pertanyaan_hari_ini_tanpa_kemarin_otomatis_dan_jawaban():
    db = FakeDB()
    _pertanyaan(db, "u1", _sekarang_iso())
    _pertanyaan(db, "u1", akp.awal_hari_iso())            # tepat tengah malam WIB = hari ini
    _pertanyaan(db, "u1", _kemarin_iso())                 # kemarin
    _pertanyaan(db, "u1", _sekarang_iso(), otomatis=True)  # permintaan briefing otomatis
    _pertanyaan(db, "u1", _sekarang_iso(), peran="asisten")
    _pertanyaan(db, "u2", _sekarang_iso())
    assert run(akp.jumlah_pertanyaan_hari_ini(db, "u1")) == 2
    assert run(akp.pertanyaan_per_pengguna(db)) == {"u1": 2, "u2": 1}
    # awal hari WIB = 17:00 UTC hari sebelumnya
    assert akp.awal_hari_iso(today_wib()).endswith("T17:00:00+00:00")


# ═══ Rute Asisten AI ══════════════════════════════════════════════════════════
def _status_siap(monkeypatch, siap=True):
    async def _st():
        out = {"siap": siap, "model": "Uji", "tindakan_aktif": True, "batas_tindakan_harian": 30}
        if not siap:
            out.update({"alasan": "kunci_kosong", "pesan": "kunci"})
        return out
    monkeypatch.setattr(r.mesin, "status_siap", _st)


def test_status_staf_bawaan_mati_lalu_dinyalakan(env, monkeypatch):
    _status_siap(monkeypatch)
    out = run(r.status(Req()))
    assert out["siap"] is False and out["alasan"] == "pengguna_nonaktif" and "owner" in out["pesan"]
    assert out["pengguna"]["aktif"] is False and out["pengguna"]["sumber"] == "bawaan"
    # akun dinyalakan + batas tindakan sendiri
    env.db.users.docs[3]["asisten_ai"] = {"aktif": True, "batas_tindakan_harian": 7}
    out = run(r.status(Req()))
    assert out["siap"] is True and "alasan" not in out
    assert out["batas_tindakan_harian"] == 7 and out["pengguna"]["sumber"] == "akun"
    # akun dimatikan menang walau AI sendiri belum siap
    env.db.users.docs[3]["asisten_ai"] = {"aktif": False}
    _status_siap(monkeypatch, siap=False)
    assert run(r.status(Req()))["alasan"] == "pengguna_nonaktif"


def test_status_batas_pertanyaan_tercapai(env, monkeypatch):
    _status_siap(monkeypatch)
    env.setelan.update({"asisten_pengguna_bawaan_aktif": True, "asisten_batas_pertanyaan_harian": 2})
    _pertanyaan(env.db, STAF["id"], _sekarang_iso())
    out = run(r.status(Req()))
    assert out["siap"] is True and out["pengguna"]["pertanyaan_hari_ini"] == 1
    _pertanyaan(env.db, STAF["id"], _sekarang_iso())
    out = run(r.status(Req()))
    assert out["siap"] is False and out["alasan"] == "batas_pertanyaan" and "2 pertanyaan" in out["pesan"]
    # AI sendiri belum siap → alasan global tetap dipakai
    _status_siap(monkeypatch, siap=False)
    assert run(r.status(Req()))["alasan"] == "kunci_kosong"


def test_owner_selalu_bisa_membuat_percakapan_staf_mati_ditolak(env):
    with pytest.raises(HTTPException) as e:
        run(r.buat_sesi(Req({"ruang": "saya"})))
    assert e.value.status_code == 403 and "belum diaktifkan" in e.value.detail
    assert env.db.ai_chat_sessions.docs == []
    env.state["u"] = OWNER
    assert run(r.buat_sesi(Req({})))["ruang"] == "umum"
    # staf dinyalakan per akun → boleh di ruang Portal Saya
    env.state["u"] = STAF
    env.db.users.docs[3]["asisten_ai"] = {"aktif": True}
    assert run(r.buat_sesi(Req({})))["ruang"] == "saya"


def test_kirim_pesan_ditolak_tanpa_menyimpan_dan_batas_diteruskan(env, monkeypatch):
    env.db.ai_chat_sessions.docs.append({"id": "s-1", "user_id": STAF["id"], "ruang": "saya", "dihapus": False})
    dipanggil = {}

    async def _siapkan(**kw):
        dipanggil.update(kw)
        return None, {"kode": "uji_berhenti", "pesan": "berhenti di uji"}
    monkeypatch.setattr(r.mesin, "siapkan_jalan", _siapkan)

    # 1) akun mati → galat SSE pengguna_nonaktif, mesin tidak dipanggil, tidak ada pesan tersimpan
    ev = _sse(run(r.kirim_pesan("s-1", Req({"teks": "Sisa cuti saya?"}))))
    assert ev == [("galat", {"kode": "pengguna_nonaktif", "pesan": akp.PESAN_NONAKTIF})]
    assert dipanggil == {} and env.db.ai_chat_messages.docs == []

    # 2) dinyalakan, batas pertanyaan akun 2, batas tindakan akun 4 → diteruskan ke mesin
    env.db.users.docs[3]["asisten_ai"] = {"aktif": True, "batas_pertanyaan_harian": 2, "batas_tindakan_harian": 4}
    _pertanyaan(env.db, STAF["id"], _kemarin_iso())
    _pertanyaan(env.db, STAF["id"], _sekarang_iso())
    ev = _sse(run(r.kirim_pesan("s-1", Req({"teks": "Sisa cuti saya?"}))))
    assert ev[0][1]["kode"] == "uji_berhenti" and dipanggil["batas_tindakan"] == 4

    # 3) pertanyaan ke-3 hari ini → batas_pertanyaan
    _pertanyaan(env.db, STAF["id"], _sekarang_iso())
    dipanggil.clear()
    ev = _sse(run(r.kirim_pesan("s-1", Req({"teks": "Lagi"}))))
    assert ev[0][0] == "galat" and ev[0][1]["kode"] == "batas_pertanyaan" and "2 pertanyaan" in ev[0][1]["pesan"]
    assert dipanggil == {}


def test_putuskan_setujui_ditolak_batal_tetap_boleh(env, monkeypatch):
    dipanggil = {}

    async def _putusan(**kw):
        dipanggil.update(kw)
        raise tdk.GalatTindakan(404, "berhenti di uji")
    monkeypatch.setattr(r.mesin, "siapkan_putusan", _putusan)
    with pytest.raises(HTTPException) as e:
        run(r.putuskan_tindakan("t-1", Req({"keputusan": "setujui"})))
    assert e.value.status_code == 403 and "dibatalkan" in e.value.detail and dipanggil == {}
    with pytest.raises(HTTPException) as e:
        run(r.putuskan_tindakan("t-1", Req({"keputusan": "batal"})))
    assert e.value.status_code == 404 and dipanggil["keputusan"] == "batal"
    # owner: batas tindakan bawaan diteruskan
    env.state["u"] = OWNER
    dipanggil.clear()
    with pytest.raises(HTTPException):
        run(r.putuskan_tindakan("t-1", Req({"keputusan": "setujui"})))
    assert dipanggil["batas_tindakan"] == 30


def test_unggah_lampiran_ditolak_untuk_akun_mati(env):
    ditutup = []

    class Berkas:
        filename = "a.csv"

        async def read(self, _n=None):
            raise AssertionError("berkas tidak boleh dibaca bila akun mati")

        async def close(self):
            ditutup.append(True)
    with pytest.raises(HTTPException) as e:
        run(r.unggah_lampiran(Req(), berkas=Berkas()))
    assert e.value.status_code == 403 and ditutup == [True]


# ═══ Mesin & persetujuan memakai batas tindakan akun ═════════════════════════
def test_siapkan_jalan_memakai_batas_tindakan_akun(monkeypatch):
    async def _gerbang(*_a, **_k):
        return t.GateResult(ok=True, api_key="kunci-uji")

    async def _pengaturan():
        return {"aktif": True, "batas": 30}

    async def _ing():
        return False
    monkeypatch.setattr(mesin, "gerbang", _gerbang)
    monkeypatch.setattr(mesin.tdk, "pengaturan", _pengaturan)
    monkeypatch.setattr(mesin.ing, "aktif", _ing)
    mesin._AKTIF.clear()
    kw = dict(db=FakeDB(), user=STAF, sesi={"id": "s-x", "ruang": "saya"}, teks="halo", cv="DA", periode="2026-11",
              today=today_wib())
    j, galat = run(mesin.siapkan_jalan(**kw))
    assert galat is None and j.batas_tindakan == 30
    j, galat = run(mesin.siapkan_jalan(**kw, batas_tindakan=3))
    assert galat is None and j.batas_tindakan == 3


def test_persetujuan_kartu_memakai_batas_tindakan_akun(monkeypatch):
    db = FakeDB()
    for i in range(2):
        db.ai_actions.docs.append({"id": f"a-{i}", "user_id": STAF["id"], "tanggal_jalan": wib_date_str(),
                                   "keadaan": "dijalankan"})

    async def _pengaturan():
        return {"aktif": True, "batas": 30}
    monkeypatch.setattr(tdk, "pengaturan", _pengaturan)
    monkeypatch.setattr(tdk.ab, "cari_tindakan", lambda _n: SimpleNamespace(risiko="rendah", input_schema={}))
    doc = {"id": "a-baru", "user_id": STAF["id"], "keadaan": "menunggu", "nama": "uji", "args": {}, "rencana": {}}
    with pytest.raises(tdk.GalatTindakan) as e:
        run(tdk.periksa_dan_kunci(db, STAF, doc, keputusan="setujui", ubahan=None, alasan="",
                                  buat_ctx_baca=lambda d: None, batas=2))
    assert e.value.status == 409 and "2 tindakan" in e.value.pesan


# ═══ Monitor AI: daftar & ubah per pengguna ══════════════════════════════════
def test_daftar_per_pengguna_isi_dan_pemakaian(env):
    env.state["u"] = OWNER
    env.db.users.docs[3]["asisten_ai"] = {"aktif": True, "batas_pertanyaan_harian": 10}
    _pertanyaan(env.db, STAF["id"], _sekarang_iso())
    _pertanyaan(env.db, STAF["id"], _kemarin_iso())
    env.db.ai_actions.docs.append({"id": "a1", "user_id": STAF["id"], "tanggal_jalan": wib_date_str(),
                                   "keadaan": "dijalankan"})
    env.db.ai_actions.docs.append({"id": "a2", "user_id": STAF["id"], "tanggal_jalan": wib_date_str(),
                                   "keadaan": "dibatalkan"})
    env.db[t.USAGE_LOGS].docs.extend([
        {"user_id": STAF["id"], "date": today_wib().isoformat(), "feature_group": "asisten-ai", "cost_usd": 0.25},
        {"user_id": STAF["id"], "date": today_wib().isoformat(), "feature_group": "asisten-ai", "cost_usd": 0.5},
        {"user_id": STAF["id"], "date": today_wib().isoformat(), "feature_group": "hr-ai", "cost_usd": 9.0}])
    out = run(mon.daftar_asisten_pengguna(Req()))["data"]
    ids = [x["id"] for x in out["items"]]
    assert set(ids) == {OWNER["id"], SUPER["id"], ADMIN["id"], STAF["id"], MGR["id"]}   # tanpa vendor/PIC/nonaktif
    assert out["boleh_ubah"] is True and out["bawaan"] == {"aktif": False, "batas_pertanyaan": 0, "batas_tindakan": 30}
    staf = next(x for x in out["items"] if x["id"] == STAF["id"])
    assert (staf["aktif"], staf["sumber"], staf["batas_pertanyaan"]) == (True, "akun", 10)
    assert staf["atur"] == {"aktif": True, "batas_pertanyaan_harian": 10, "batas_tindakan_harian": None,
                            "golongan": {"B": None, "C": None, "D": None}}
    assert (staf["pertanyaan_hari_ini"], staf["tindakan_hari_ini"], staf["biaya_hari_ini_usd"]) == (1, 1, 0.75)
    mgr = next(x for x in out["items"] if x["id"] == MGR["id"])
    assert (mgr["aktif"], mgr["sumber"]) == (False, "bawaan")
    assert next(x for x in out["items"] if x["id"] == OWNER["id"])["selalu_aktif"] is True
    # admin boleh melihat tetapi tidak mengubah; manajer tidak boleh melihat
    env.state["u"] = ADMIN
    assert run(mon.daftar_asisten_pengguna(Req()))["data"]["boleh_ubah"] is False
    env.state["u"] = MGR
    with pytest.raises(HTTPException) as e:
        run(mon.daftar_asisten_pengguna(Req()))
    assert e.value.status_code == 403


def test_ubah_per_pengguna_hak_validasi_dan_simpan(env):
    env.state["u"] = ADMIN
    with pytest.raises(HTTPException) as e:
        run(mon.ubah_asisten_pengguna(MGR["id"], Req(), payload={"aktif": True}))
    assert e.value.status_code == 403
    env.state["u"] = OWNER
    for uid, body, kode in ((MGR["id"], {"aktif": "ya"}, 400), (OWNER["id"], {"aktif": False}, 400),
                            (VENDOR["id"], {"aktif": True}, 400), ("u-tidak-ada", {"aktif": True}, 404),
                            (MGR["id"], {"batas_pertanyaan_harian": 5000}, 400), (MGR["id"], {}, 400)):
        with pytest.raises(HTTPException) as e:
            run(mon.ubah_asisten_pengguna(uid, Req(), payload=body))
        assert e.value.status_code == kode, (uid, body)
    out = run(mon.ubah_asisten_pengguna(MGR["id"], Req(), payload={"aktif": True, "batas_pertanyaan_harian": 15}))
    assert out["data"]["aktif"] is True and out["data"]["batas_pertanyaan"] == 15
    simpan = next(u for u in env.db.users.docs if u["id"] == MGR["id"])["asisten_ai"]
    assert simpan["aktif"] is True and simpan["batas_pertanyaan_harian"] == 15
    assert simpan["diubah_oleh"] == OWNER["email"] and simpan["diubah_at"]
    # ubah sebagian: kunci lain tetap; null = kembali ikut bawaan
    run(mon.ubah_asisten_pengguna(MGR["id"], Req(), payload={"batas_tindakan_harian": 3}))
    simpan = next(u for u in env.db.users.docs if u["id"] == MGR["id"])["asisten_ai"]
    assert (simpan["aktif"], simpan["batas_pertanyaan_harian"], simpan["batas_tindakan_harian"]) == (True, 15, 3)
    out = run(mon.ubah_asisten_pengguna(MGR["id"], Req(), payload={"aktif": None}))
    assert (out["data"]["aktif"], out["data"]["sumber"]) == (False, "bawaan")
    # owner boleh mengatur batas akunnya sendiri (tetap aktif)
    out = run(mon.ubah_asisten_pengguna(OWNER["id"], Req(), payload={"aktif": True, "batas_tindakan_harian": 50}))
    assert out["data"]["aktif"] is True and out["data"]["batas_tindakan"] == 50
    # superadmin juga boleh mengubah
    env.state["u"] = SUPER
    assert run(mon.ubah_asisten_pengguna(STAF["id"], Req(), payload={"aktif": False}))["data"]["sumber"] == "akun"


def test_setelan_bawaan_baru_tersimpan_dan_divalidasi(env):
    env.db.ai_config.docs.append({"id": "global"})     # Mongo tiruan tidak mendukung upsert
    env.state["u"] = OWNER
    run(mon.update_settings(Req(), payload={"asisten_pengguna_bawaan_aktif": "true",
                                            "asisten_batas_pertanyaan_harian": 25}))
    doc = env.db.ai_config.docs[0]
    assert doc["asisten_pengguna_bawaan_aktif"] is True and doc["asisten_batas_pertanyaan_harian"] == 25
    for p in ({"asisten_batas_pertanyaan_harian": 1001}, {"asisten_batas_pertanyaan_harian": "x"},
              {"asisten_batas_pertanyaan_harian": True}):
        with pytest.raises(HTTPException) as e:
            run(mon.update_settings(Req(), payload=p))
        assert e.value.status_code == 400
    # admin: boleh menyimpan formulir selama bawaan per pengguna TIDAK berubah; mengubahnya → 403
    env.state["u"] = ADMIN
    env.setelan.update({"asisten_pengguna_bawaan_aktif": False, "asisten_batas_pertanyaan_harian": 0})
    run(mon.update_settings(Req(), payload={"asisten_pengguna_bawaan_aktif": False, "asisten_batas_pertanyaan_harian": 0,
                                            "asisten_batas_tindakan_harian": 12}))
    assert env.db.ai_config.docs[0]["asisten_batas_tindakan_harian"] == 12
    for p in ({"asisten_pengguna_bawaan_aktif": True}, {"asisten_batas_pertanyaan_harian": 5}):
        with pytest.raises(HTTPException) as e:
            run(mon.update_settings(Req(), payload=p))
        assert e.value.status_code == 403
