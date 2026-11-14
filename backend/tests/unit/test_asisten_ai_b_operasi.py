"""Uji agen OPERASI Asisten AI Tahap B (8 Nov 2026). Hermetik: Mongo palsu, ctx palsu perekam, tanpa jaringan.

1. Celah izin (berlaku juga untuk layar biasa):
   · persetujuan bertingkat (`services.approval_chain_service.process_action`): peran level aktif ditegakkan,
     menyetujui ajuan sendiri ditolak, tulis SATU kali (dulu dua), tulis bersyarat anti klik ganda;
   · penugasan & jadwal shift (`routes.hr_shifts`, `routes.dewi_shift_scheduler`): hanya HR/manajemen;
   · "Jalankan sekarang" penjadwal (`routes.dewi_scheduler`): hanya superadmin/admin/owner;
   · pemicu manual cron Keuangan (`routes.cron_jobs`) SENGAJA tetap untuk peran keuangan (tidak diubah).
2. Alat tindakan (`core.asisten_ai.alat.tindakan_operasi`, Kontrak D): `siapkan` hanya GET, `jalankan` menulis
   lewat endpoint layar, `batalkan` memulihkan; galat izin ramah berbahasa Indonesia.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
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

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402

from core.asisten_ai import alat_base as ab  # noqa: E402
from core.asisten_ai.alat_base import AlatError  # noqa: E402
from core.asisten_ai.alat import tindakan_operasi as T  # noqa: E402
from core.asisten_ai.alat import okr as OKR  # noqa: E402
from services import approval_chain_service as acs  # noqa: E402


def run(c):
    return asyncio.run(c)


def U(uid, role, **kw):
    return {"id": uid, "name": f"Uji {uid}", "email": f"{uid}@contoh.test", "role": role, **kw}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1a. Persetujuan bertingkat
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
class HitungDB(FakeDB):
    """FakeDB yang menghitung update_one pada approval_requests."""

    def __init__(self):
        super().__init__()
        self.tulis = 0
        col = self["approval_requests"]
        asli = col.update_one

        async def _hitung(q, upd, upsert=False):
            self.tulis += 1
            return await asli(q, upd, upsert)
        col.update_one = _hitung


def _req(db, rid=1, requester="u-pemohon", levels=("manager", "hr"), meta=None):
    # 2026-11-09 (Q6): jenis "leave" tidak lagi diputus mesin rantai (cuti → core.leave_engine); uji mesin rantai
    # memakai jenis lain yang masih aktif (klaim biaya).
    lv = [{"level": i + 1, "role": r, "label": {"manager": "Manajer", "hr": "HR", "owner": "Direktur"}.get(r, r),
           "status": "pending" if i == 0 else "waiting", "approver_id": None, "approver_name": None, "note": "",
           "actioned_at": None} for i, r in enumerate(levels)]
    db.approval_requests.docs.append({"_id": rid, "id": rid, "type": "expense", "ref_id": "L1", "ref_code": "L1",
                                      "requester_id": requester, "requester_name": "Pemohon", "current_level": 1,
                                      "max_level": len(lv), "status": "pending", "levels": lv, "meta": meta or {},
                                      "created_at": "x", "updated_at": "x", "completed_at": None})


def test_penyetuju_benar_naik_satu_level_dan_menulis_satu_kali():
    db = HitungDB()
    _req(db)
    out = run(acs.process_action(db, 1, "approve", U("u-mgr", "manager"), "ok"))
    assert out["status"] == "pending" and out["current_level"] == 2
    assert db.tulis == 1, "dulu badan fungsi tertulis dua kali → dua kali update_one"
    doc = db.approval_requests.docs[0]
    assert [lv["status"] for lv in doc["levels"]] == ["approved", "pending"]
    assert doc["levels"][0]["approver_id"] == "u-mgr"
    out = run(acs.process_action(db, 1, "approve", U("u-hr", "staff_hr"), ""))
    assert out["status"] == "approved" and out["completed_at"] and db.tulis == 2


def test_peran_bukan_penyetuju_level_aktif_ditolak():
    db = HitungDB()
    _req(db)
    for role in ("staff_hr", "tim_packing", "admin_gudang", "marketing_kol", ""):
        with pytest.raises(PermissionError, match="tidak berhak"):
            run(acs.process_action(db, 1, "approve", U("u-x", role)))
        with pytest.raises(PermissionError):
            run(acs.process_action(db, 1, "reject", U("u-x", role)))
    assert db.tulis == 0 and db.approval_requests.docs[0]["status"] == "pending"


def test_alias_peran_level_dan_super_role_tetap_boleh():
    for role in ("supervisor_produksi", "manager_keuangan", "admin", "owner", "superadmin"):
        db = HitungDB()
        _req(db)
        out = run(acs.process_action(db, 1, "approve", U("u-a", role)))
        assert out["current_level"] == 2, role


def test_menyetujui_ajuan_sendiri_ditolak_semua_peran_tapi_menolak_boleh():
    for role in ("manager", "owner", "superadmin"):
        db = HitungDB()
        _req(db, requester="u-saya")
        with pytest.raises(PermissionError, match="ajuan Anda sendiri"):
            run(acs.process_action(db, 1, "approve", U("u-saya", role)))
        assert db.tulis == 0
    db = HitungDB()
    _req(db, requester="u-saya")
    out = run(acs.process_action(db, 1, "reject", U("u-saya", "manager"), "salah ketik"))
    assert out["status"] == "rejected" and [lv["status"] for lv in out["levels"]] == ["rejected", "skipped"]


def test_ajuan_atas_nama_karyawan_sendiri_ditolak():
    # HR mengetik cuti atas nama karyawan e-1; akun karyawan itu (manajer) tidak boleh menyetujuinya
    db = HitungDB()
    _req(db, requester="u-hr", meta={"employee_id": "e-1"})
    with pytest.raises(PermissionError):
        run(acs.process_action(db, 1, "approve", U("u-karyawan", "manager", employee_id="e-1")))
    db.users.docs.append({"id": "u-lain", "employee_id": None, "status": "active"})
    db.rahaza_employees.docs.append({"id": "e-1", "user_id": "u-lain"})
    with pytest.raises(PermissionError):  # tautan arah rahaza_employees.user_id
        run(acs.process_action(db, 1, "approve", U("u-lain", "manager")))
    out = run(acs.process_action(db, 1, "approve", U("u-mgr2", "manager")))
    assert out["current_level"] == 2


def test_klik_ganda_tidak_memutus_level_yang_sama_dua_kali():
    db = HitungDB()
    _req(db)
    run(acs.process_action(db, 1, "approve", U("u-mgr", "manager")))
    # request yang sama dibaca sebelum klik pertama selesai (status/level lama) → tulis bersyarat tidak cocok
    basi = dict(db.approval_requests.docs[0], current_level=1)
    basi["levels"] = [dict(basi["levels"][0], status="pending"), dict(basi["levels"][1], status="waiting")]
    asli = db.approval_requests.find_one

    async def _basi(q=None, projection=None, **kw):
        return dict(basi)
    db.approval_requests.find_one = _basi
    with pytest.raises(ValueError, match="baru saja diputuskan"):
        run(acs.process_action(db, 1, "approve", U("u-mgr", "manager")))
    db.approval_requests.find_one = asli
    assert db.approval_requests.docs[0]["current_level"] == 2


def test_route_approve_menjawab_403_ramah(monkeypatch):
    from routes import approval_multilevel as am
    db = HitungDB()
    _req(db, requester="u-saya")

    async def _auth(request):
        return U("u-saya", "manager")

    async def _log(*a, **k):
        return None
    monkeypatch.setattr(am, "require_auth", _auth)
    monkeypatch.setattr(am, "get_db", lambda: db)
    monkeypatch.setattr(am, "log_activity", _log)
    with pytest.raises(HTTPException) as e:
        run(am.approve_request(FakeRequest(), "1", am.ActionModel(note="")))
    assert e.value.status_code == 403 and "sendiri" in e.value.detail
    with pytest.raises(HTTPException) as e:  # status sudah final → 400, bukan 500
        db.approval_requests.docs[0]["status"] = "approved"
        run(am.reject_request(FakeRequest(), "1", am.ActionModel(note="")))
    assert e.value.status_code == 400


def test_badan_process_action_tidak_lagi_tertulis_dua_kali():
    import inspect
    src = inspect.getsource(acs.process_action)
    assert src.count("update_one(") == 1 and src.count('lv_entry["status"] =') == 1


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1b. Penugasan / jadwal shift
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_penulis_shift_hanya_hr_dan_manajemen():
    from routes.hr_shifts import _require_shift_writer
    for role in ("hr", "hr_manager", "staff_hr", "manager", "owner", "admin", "superadmin"):
        _require_shift_writer(U("u", role))
    _require_shift_writer(U("u", "peran_kustom", _permissions=["hr.attendance.manage"]))
    _require_shift_writer(U("u", "peran_kustom", _permissions=["hr.manage"]))
    _require_shift_writer(U("u", "peran_kustom", _permissions=["*"]))
    for role in ("tim_packing", "admin_gudang", "marketing_kol", "pic_toko", "accounting", ""):
        with pytest.raises(HTTPException) as e:
            _require_shift_writer(U("u", role))
        assert e.value.status_code == 403 and "HR" in e.value.detail


def test_route_penugasan_shift_menolak_staf(monkeypatch):
    from routes import hr_shifts as hs
    dipanggil = []

    async def _assign(db, **kw):
        dipanggil.append(kw)
        return {"id": "a1", **kw}

    async def _log(*a, **k):
        return None
    monkeypatch.setattr(hs, "assign_shift", _assign)
    monkeypatch.setattr(hs, "get_db", lambda: FakeDB())
    monkeypatch.setattr(hs, "log_activity", _log)
    body = hs.AssignShiftModel(employee_id="e1", shift_id="s1", effective_from="2026-11-10")
    for user, boleh in ((U("u1", "tim_packing"), False), (U("u2", "hr"), True)):
        async def _auth(request, _u=user):
            return _u
        monkeypatch.setattr(hs, "require_auth", _auth)
        if boleh:
            assert run(hs.create_assignment(FakeRequest(), body))["status"] == "ok"
        else:
            with pytest.raises(HTTPException) as e:
                run(hs.create_assignment(FakeRequest(), body))
            assert e.value.status_code == 403
    assert len(dipanggil) == 1


def test_route_penjadwal_shift_generate_dan_terbitkan_menolak_staf(monkeypatch):
    from routes import dewi_shift_scheduler as ss
    db = FakeDB()
    db.rahaza_schedules.docs.append({"id": "j1", "status": "draft"})
    monkeypatch.setattr(ss, "get_db", lambda: db)

    async def _tanpa_log(*a, **k):
        return None
    monkeypatch.setattr(ss, "log_activity", _tanpa_log)   # Tahap C: terbit kini dicatat di log aktivitas

    async def _staf(request):
        return U("u1", "admin_gudang")
    monkeypatch.setattr(ss, "require_auth", _staf)
    # Tahap C audit HR (9 Nov 2026): jadwal otomatis lama dipensiunkan (410), tetapi gerbang penulis tetap lebih dulu.
    with pytest.raises(HTTPException) as e:
        run(ss.generate_schedule(FakeRequest()))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        run(ss.buat_jadwal(FakeRequest(), ss.JadwalBaruModel(start_date="2026-11-10", end_date="2026-11-11",
                                                               cara="shift", shift_id="sh-x")))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        run(ss.publish_schedule(FakeRequest(), "j1"))
    assert e.value.status_code == 403 and db.rahaza_schedules.docs[0]["status"] == "draft"

    async def _hr(request):
        return U("u2", "hr")
    monkeypatch.setattr(ss, "require_auth", _hr)
    assert run(ss.publish_schedule(FakeRequest(), "j1"))["success"] is True
    assert db.rahaza_schedules.docs[0]["status"] == "published"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1c. Jalankan sekarang (penjadwal) + cron Keuangan (sengaja tidak diubah)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_jalankan_sekarang_penjadwal_hanya_admin_owner(monkeypatch):
    from routes import dewi_scheduler as ds
    jalan = []

    async def _job():
        jalan.append(1)
        return {"ok": True}
    monkeypatch.setitem(ds.JOB_REGISTRY, "uji_job", {"fn": _job, "description": "uji", "cron_label": "-"})
    for role in ("manager", "pic_toko", "marketing_kol", "hr", "accounting", ""):
        with pytest.raises(HTTPException) as e:
            run(ds.run_now("uji_job", user=U("u", role)))
        assert e.value.status_code == 403 and "admin atau owner" in e.value.detail
    assert jalan == []
    for role in ("admin", "owner", "superadmin"):
        assert run(ds.run_now("uji_job", user=U("u", role)))["status"] == "success"
    assert len(jalan) == 3


def test_cron_keuangan_tetap_untuk_peran_keuangan(monkeypatch):
    """Bukan celah: `/api/cron/{job}/run-now` dipakai layar Keuangan › Pemeliharaan (tombol 'Jalankan sekarang'),
    gerbangnya sudah peran keuangan + admin/owner. Tidak diubah (aturan owner: konfirmasi desain dulu)."""
    from routes import cron_jobs as cj
    for role, boleh in (("accounting", True), ("manager_keuangan", True), ("owner", True), ("hr", False),
                        ("tim_packing", False)):
        async def _auth(request, _r=role):
            return U("u", _r)
        monkeypatch.setattr(cj, "require_auth", _auth)
        if boleh:
            assert run(cj._require_fin(FakeRequest()))["role"] == role
        else:
            with pytest.raises(HTTPException) as e:
                run(cj._require_fin(FakeRequest()))
            assert e.value.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 2. Alat tindakan — ctx palsu perekam
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
class Ctx:
    """`ctx` palsu: merekam panggilan `api` dan menjawab dari tabel {(METHOD, path): jawaban|callable}."""

    def __init__(self, user, rute=None, today="2026-11-08"):
        from datetime import date
        self.user, self.cv, self.today = user, "DA", date.fromisoformat(today)
        self.rute = dict(rute or {})
        self.calls = []

    async def api(self, method, path, params=None, json=None, **kw):
        self.calls.append((method.upper(), path, dict(params or {}), json))
        r = self.rute.get((method.upper(), path))
        if r is None:
            raise AssertionError(f"panggilan tak terduga {method} {path}")
        if isinstance(r, Exception):
            raise r
        return r(params, json) if callable(r) else r

    @property
    def tulis(self):
        return [c for c in self.calls if c[0] != "GET"]


def K(nama):
    """Kelas alat tindakan (atribut `kelas` di Alat — versi inti maupun stub Tahap B)."""
    ab.muat_semua_alat()
    return ab._DAFTAR[nama].kelas


NAMA_TINDAKAN = ("buat_pengingat", "buat_objektif_okr", "perbarui_key_result", "buat_draf_pr",
                 "jadwalkan_laporan", "kirim_notifikasi")


def _cek_rencana(r):
    assert set(r) <= {"judul", "ringkas", "perubahan", "catatan", "peringatan", "ubah", "tautan"}
    assert r["judul"] and isinstance(r["perubahan"], list) and r["perubahan"]
    for p in r["perubahan"]:
        assert isinstance(p["sebelum"], str) and isinstance(p["sesudah"], str) and p["label"]
    for u in r.get("ubah") or []:
        assert u["jenis"] in ("rupiah", "angka", "teks", "tanggal", "pilihan") and u["kunci"]
    if r.get("tautan"):
        assert re.match(r"^[a-z0-9][a-z0-9-]{1,63}$", r["tautan"]["menu"])
    assert len(json.dumps(r, ensure_ascii=False)) <= 8000
    teks = json.dumps(r, ensure_ascii=False)
    assert "Traceback" not in teks and "None" not in teks


def test_alat_tindakan_terdaftar_sesuai_kontrak_d():
    ab.muat_semua_alat()
    for n in NAMA_TINDAKAN:
        a = ab._DAFTAR[n]
        assert a.kind == "action" and getattr(a, "risiko", "rendah") == "rendah"
        sch = a.input_schema
        assert sch["type"] == "object" and sch["additionalProperties"] is False
        assert "menekan Setujui" in a.description, n
        assert T.__name__ in a.asal
        kls = K(n)
        assert asyncio.iscoroutinefunction(kls.siapkan) and asyncio.iscoroutinefunction(kls.jalankan)
    # pembatalan hanya di alat yang endpoint-nya memungkinkan
    assert not hasattr(K("kirim_notifikasi"), "batalkan")
    for n in NAMA_TINDAKAN[:-1]:
        assert asyncio.iscoroutinefunction(K(n).batalkan)
    # tindakan tidak dikirim ke model di Tahap A; alat baca daftar_okr ikut
    nama_api = [t["name"] for t in ab.tools_untuk_api()]
    assert "daftar_okr" in nama_api and not set(NAMA_TINDAKAN) & set(nama_api)


# — buat_pengingat ——————————————————————————————————————————————————————————————————————————————
def test_pengingat_pribadi_siapkan_baca_saja_jalankan_dan_batalkan():
    kls = K("buat_pengingat")
    args = {"judul": "Cek setoran Shopee", "waktu": "2026-11-10T09:00", "ulang": "mingguan", "keterangan": "x"}
    ctx = Ctx(U("u1", "pic_toko"), {("GET", "/api/portal/reminders"): {"items": []},
                                    ("POST", "/api/portal/reminders"): lambda p, j: {"id": "r1", **j},
                                    ("DELETE", "/api/portal/reminders/r1"): {"ok": True}})
    r = run(kls.siapkan(ctx, dict(args)))
    _cek_rencana(r)
    assert not ctx.tulis and "Selasa, 10 November 2026 pukul 09.00 WIB" in json.dumps(r, ensure_ascii=False)
    out = run(kls.jalankan(ctx, dict(args), r))
    post = ctx.tulis[0]
    assert post[:2] == ("POST", "/api/portal/reminders")
    assert post[3]["remind_at"] == "2026-11-10T09:00" and post[3]["recurrence"] == "weekly"
    assert out["pembatalan"] == {"jenis": "pribadi", "id": "r1"} and out["ringkas"]
    assert "dihapus" in run(kls.batalkan(ctx, out["pembatalan"]))["ringkas"]
    assert ctx.tulis[-1][:2] == ("DELETE", "/api/portal/reminders/r1")
    ctx.rute[("DELETE", "/api/portal/reminders/r1")] = AlatError(404, "x")
    assert "sudah tidak ada" in run(kls.batalkan(ctx, out["pembatalan"]))["ringkas"]


def test_pengingat_pribadi_isian_salah_ramah():
    kls = K("buat_pengingat")
    ctx = Ctx(U("u1", "hr"), {("GET", "/api/portal/reminders"): {"items": [
        {"title": "Rapat", "remind_at": "2026-11-01T08:00"}]}})
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(ctx, {"judul": "Rapat"}))
    assert e.value.status == 400 and "waktu" in e.value.pesan
    with pytest.raises(AlatError):
        run(kls.siapkan(ctx, {"judul": "Rapat", "waktu": "2026-11-01T08:00", "vendor": "v"}))
    r = run(kls.siapkan(ctx, {"judul": "Rapat", "waktu": "2026-11-01T08:00"}))
    assert len(r["peringatan"]) == 2  # sudah lewat + kembar


VENDOR = [{"id": "v1", "garment_name": "CMT Contoh Satu", "garment_code": "C1", "status": "active", "password": "x"},
          {"id": "v2", "garment_name": "CMT Contoh Dua", "garment_code": "C2", "status": "active"}]


def test_pengingat_vendor_izin_peran_produksi():
    kls = K("buat_pengingat")
    args = {"jenis": "vendor", "judul": "Setor data", "vendor": "CMT Contoh Satu", "keterangan": "Mohon setor",
            "waktu": "2026-11-09T16:00"}
    staf = Ctx(U("u1", "pic_toko"), {})
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(staf, dict(args)))
    # 14 Nov 2026: pesan menyebut centang yang dibutuhkan (Produksi › Vendor CMT › Tambah), bukan daftar kode peran
    assert e.value.status == 403 and "Vendor CMT" in e.value.pesan and "Peran & Hak Akses" in e.value.pesan
    assert not staf.calls
    rute = {("GET", "/api/garments"): VENDOR,
            ("POST", "/api/reminders"): lambda p, j: {"id": "vr1", **j},
            ("DELETE", "/api/reminders/vr1"): {"success": True}}
    prod = Ctx(U("u2", "admin_produksi"), rute)
    r = run(kls.siapkan(prod, dict(args)))
    _cek_rencana(r)
    assert not prod.tulis and "password" not in json.dumps(r) and any("Hapus" in c and "Vendor CMT" in c for c in r["catatan"])
    out = run(kls.jalankan(prod, dict(args), r))
    assert prod.tulis[0][3]["vendor_id"] == "v1" and prod.tulis[0][3]["priority"] == "normal"
    assert prod.tulis[0][3]["message"] == ("Mohon setor\nMohon ditindaklanjuti sebelum Senin, 9 November 2026 "
                                           "pukul 16.00 WIB.")
    assert out["pembatalan"] is None  # admin_produksi tidak boleh menghapus (endpoint: admin saja)
    adm = Ctx(U("u3", "admin"), rute)
    assert run(kls.jalankan(adm, dict(args), r))["pembatalan"] == {"jenis": "vendor", "id": "vr1"}
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(prod, dict(args, vendor="contoh")))
    assert e.value.status == 409 and "v1" in e.value.pesan and "v2" in e.value.pesan
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(prod, dict(args, vendor="tidak ada")))
    assert e.value.status == 404
    with pytest.raises(AlatError) as e:  # batas tindak lanjut sudah lewat
        run(kls.siapkan(prod, dict(args, waktu="2026-11-01T08:00")))
    assert e.value.status == 400 and "lewat" in e.value.pesan


def test_pengingat_isian_wajib_judul_dan_waktu():
    """Kontrak dengan skrip tiruan inti: isian wajib cukup judul + waktu (pengingat pribadi)."""
    sch = ab._DAFTAR["buat_pengingat"].input_schema
    assert sch["required"] == ["judul", "waktu"]
    assert not ab.periksa_skema(sch, {"judul": "Pengingat dari Asisten AI (mode uji)", "waktu": "2026-11-09T09:00"})


# — OKR ——————————————————————————————————————————————————————————————————————————————————————————
OBJ = {"id": "o1", "title": "Naikkan omzet", "period": "2026-Q4", "status": "active", "key_results": [
    {"id": "k1", "objective_id": "o1", "title": "Pesanan per hari", "metric_type": "number", "target_value": 100,
     "current_value": 40, "unit": "pcs", "notes": None},
    {"id": "k2", "objective_id": "o1", "title": "Margin", "metric_type": "percentage", "target_value": 30,
     "current_value": 30}]}


def test_buat_objektif_okr_izin_dan_alur():
    kls = K("buat_objektif_okr")
    args = {"judul": "Perluas toko", "periode": "2026-Q4", "prioritas": "tinggi",
            "key_results": [{"judul": "Toko baru", "jenis": "angka", "target": 3, "satuan": "toko"},
                            {"judul": "Omzet toko baru", "jenis": "rupiah", "target": 50_000_000}]}
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(Ctx(U("u1", "hr"), {}), dict(args)))
    assert e.value.status == 403 and "OKR Tracker" in e.value.pesan and "Peran & Hak Akses" in e.value.pesan
    ctx = Ctx(U("u2", "manager"), {
        ("GET", "/api/management/okr/objectives"): {"data": [{"id": "ox", "title": "Perluas toko"}]},
        ("POST", "/api/management/okr/objectives"): lambda p, j: {"data": {"id": "o9", "key_results": [
            {"id": "a"}, {"id": "b"}]}},
        ("DELETE", "/api/management/okr/objectives/o9"): {"success": True}})
    r = run(kls.siapkan(ctx, dict(args)))
    _cek_rencana(r)
    assert not ctx.tulis and r["peringatan"] and "Rp 50.000.000" in json.dumps(r, ensure_ascii=False)
    assert {u["kunci"] for u in r["ubah"]} == {"judul", "key_results.0.target", "key_results.1.target"}
    out = run(kls.jalankan(ctx, dict(args), r))
    body = ctx.tulis[0][3]
    assert body["priority"] == "high" and body["key_results"][1]["metric_type"] == "currency"
    assert body["key_results"][0]["current_value"] == 0 and out["pembatalan"] == {"objective_id": "o9"}
    assert "diarsipkan" in run(kls.batalkan(ctx, out["pembatalan"]))["ringkas"]


def test_perbarui_key_result_lama_ke_baru_dan_pembatalan():
    import copy
    kls = K("perbarui_key_result")
    data = {"obj": copy.deepcopy(OBJ)}

    def _patch(p, j):
        for k in data["obj"]["key_results"]:
            if k["id"] == "k1":
                k.update({"current_value": j["current_value"], **({"notes": j["notes"]} if "notes" in j else {})})
        return {"success": True}
    ctx = Ctx(U("u1", "manager"), {
        ("GET", "/api/management/okr/objectives"): lambda p, j: {"data": [copy.deepcopy(data["obj"])]},
        ("PATCH", "/api/management/okr/key-results/k1"): _patch})
    args = {"key_result_id": "k1", "nilai": 55}
    r = run(kls.siapkan(ctx, dict(args)))
    _cek_rencana(r)
    assert r["perubahan"][0] == {"label": "Pesanan per hari", "sebelum": "40 pcs", "sesudah": "55 pcs"}
    assert r["perubahan"][1]["sebelum"] == "40%" and r["perubahan"][1]["sesudah"] == "55%"
    assert r["perubahan"][2]["sebelum"] == "70%" and r["perubahan"][2]["sesudah"] == "77,5%"
    assert not ctx.tulis
    out = run(kls.jalankan(ctx, dict(args), r))
    assert ctx.tulis[0][3] == {"current_value": 55.0} and out["pembatalan"]["current_value"] == 40.0
    # kartu lama dipakai lagi setelah nilainya berubah → ditolak, tidak menulis
    with pytest.raises(AlatError) as e:
        run(kls.jalankan(ctx, dict(args), r))
    assert e.value.status == 409 and len(ctx.tulis) == 1
    assert "40" in run(kls.batalkan(ctx, out["pembatalan"]))["ringkas"]
    assert data["obj"]["key_results"][0]["current_value"] == 40.0


def test_perbarui_key_result_galat_ramah():
    kls = K("perbarui_key_result")
    ctx = Ctx(U("u1", "manager"), {("GET", "/api/management/okr/objectives"): {"data": [OBJ]}})
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(ctx, {"key_result_id": "kX", "nilai": 1}))
    assert e.value.status == 404 and "daftar_okr" in e.value.pesan
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(ctx, {"key_result_id": "k1", "nilai": 40}))
    assert e.value.status == 400
    # 403 dari endpoint (mis. gerbang modul OKR) diteruskan sebagai AlatError ramah
    ctx.rute[("PATCH", "/api/management/okr/key-results/k1")] = AlatError(403, "Akun ini tidak punya akses ke data tersebut.")
    r = run(kls.siapkan(ctx, {"key_result_id": "k1", "nilai": 41}))
    with pytest.raises(AlatError) as e:
        run(kls.jalankan(ctx, {"key_result_id": "k1", "nilai": 41}, r))
    assert e.value.status == 403 and "akses" in e.value.pesan


def test_daftar_okr_ringkas():
    ctx = Ctx(U("u1", "manager"), {("GET", "/api/management/okr/objectives"): {"data": [dict(OBJ, progress=70)]}})
    out = run(OKR.daftar_okr(ctx, {"periode": "2026-Q4"}))
    assert ctx.calls[0][2]["period"] == "2026-Q4"
    kr = out["hasil"]["objektif"][0]["key_results"][0]
    assert kr["id"] == "k1" and kr["nilai_sekarang"] == 40 and out["_sumber"]


# — buat_draf_pr ————————————————————————————————————————————————————————————————————————————————
BELANJA = {"summary": {"week": "2026-W46", "week_label": "10–16 Nov", "without_threshold": 3}, "rows": [
    {"material_id": "m1", "code": "AKS-01", "name": "Kancing", "onhand": 10, "base_uom": "pcs", "qty_buy": 2,
     "purchase_uom": "gross", "est_total": 120000, "valued": True, "already_requested": False},
    {"material_id": "m2", "code": "AKS-02", "name": "Resleting", "onhand": 0, "base_uom": "pcs", "qty_buy": 100,
     "purchase_uom": "pcs", "est_total": 0, "valued": False, "already_requested": False},
    {"material_id": "m3", "code": "KN-01", "name": "Kain", "onhand": 1, "base_uom": "kg", "qty_buy": 25,
     "purchase_uom": "roll", "est_total": 2_000_000, "valued": True, "already_requested": True,
     "pr": {"label": "PR PR-0009 (draft)"}}]}


def test_draf_pr_dari_belanja_mingguan_tidak_pernah_diajukan():
    kls = K("buat_draf_pr")
    pr = {"id": "pr1", "request_number": "PR-0010", "status": "draft", "items": [{}, {}], "total_estimated": 120000}
    ctx = Ctx(U("u1", "admin_gudang"), {
        ("GET", "/api/rahaza/shopping-list/weekly"): BELANJA,
        ("POST", "/api/rahaza/shopping-list/create-pr"): lambda p, j: {"request": pr, "skipped": []},
        ("GET", "/api/procurement/requests/pr1"): lambda p, j: dict(pr),
        ("DELETE", "/api/procurement/requests/pr1"): {"ok": True}})
    r = run(kls.siapkan(ctx, {"prioritas": "tinggi"}))
    _cek_rencana(r)
    teks = json.dumps(r, ensure_ascii=False)
    assert not ctx.tulis and "Rp 120.000" in teks and "KN-01" in teks and "anti dobel" in teks
    assert any("DRAF" in c for c in r["catatan"]) and any("belum punya harga" in p for p in r["peringatan"])
    out = run(kls.jalankan(ctx, {"prioritas": "tinggi"}, r))
    post = ctx.tulis[0]
    assert post[:2] == ("POST", "/api/rahaza/shopping-list/create-pr")
    assert post[3]["material_ids"] == ["m1", "m2"] and post[3]["priority"] == "high"
    assert not [c for c in ctx.calls if "submit" in c[1] or "approve" in c[1]]
    assert out["pembatalan"] == {"pr_id": "pr1", "nomor": "PR-0010"} and "belum diajukan" in out["ringkas"]
    assert "dihapus" in run(kls.batalkan(ctx, out["pembatalan"]))["ringkas"]
    pr["status"] = "submitted"
    with pytest.raises(AlatError) as e:
        run(kls.batalkan(ctx, out["pembatalan"]))
    assert e.value.status == 409 and ctx.tulis[-1][0] == "DELETE" and len([c for c in ctx.tulis if c[0] == "DELETE"]) == 1


def test_draf_pr_menolak_cv_gabungan():
    kls = K("buat_draf_pr")
    ctx = Ctx(U("u1", "admin_gudang"), {("GET", "/api/rahaza/shopping-list/weekly"): BELANJA})
    ctx.cv = "ALL"
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(ctx, {}))
    assert e.value.status == 400 and "Gabungan" in e.value.pesan and not ctx.calls
    ctx.cv = "DA"
    assert any("CV Dewi Aditya" in c for c in run(kls.siapkan(ctx, {}))["catatan"])


def test_draf_pr_pilihan_kode_dan_kosong():
    kls = K("buat_draf_pr")
    ctx = Ctx(U("u1", "admin_gudang"), {("GET", "/api/rahaza/shopping-list/weekly"): BELANJA})
    r = run(kls.siapkan(ctx, {"kode_barang": ["aks-01", "zz-9"]}))
    assert r["perubahan"][0]["label"].startswith("AKS-01") and "ZZ-9" in r["peringatan"][0]
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(ctx, {"kode_barang": ["KN-01"]}))
    assert e.value.status == 409 and "anti dobel" in e.value.pesan


# — jadwalkan_laporan ———————————————————————————————————————————————————————————————————————————
JADWAL = {"enabled": True, "extra_emails": ["lama@contoh.test"], "schedule_label": "Setiap tanggal 1 pukul 06:00",
          "smtp": {"configured": False}, "recipients": [{"source": "role_keuangan"}, {"source": "role_keuangan"},
                                                        {"source": "email_tambahan"}]}


def test_jadwal_laporan_izin_lama_baru_dan_pembatalan():
    kls = K("jadwalkan_laporan")
    args = {"laporan": "valuasi_aksesoris_bulanan", "email_tambah": ["baru@contoh.test"], "aktif": True}
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(Ctx(U("u1", "pic_toko"), {}), dict(args)))
    assert e.value.status == 403
    simpan = {}
    ctx = Ctx(U("u2", "accounting"), {
        ("GET", "/api/acc/valuation/report-schedule"): lambda p, j: dict(JADWAL),
        ("PUT", "/api/acc/valuation/report-schedule"): lambda p, j: simpan.update(j) or dict(j)})
    r = run(kls.siapkan(ctx, dict(args)))
    _cek_rencana(r)
    assert r["perubahan"][1] == {"label": "Email tambahan", "sebelum": "lama@contoh.test",
                                 "sesudah": "lama@contoh.test, baru@contoh.test"}
    assert len(r["peringatan"]) == 2 and "2 akun keuangan" in r["catatan"][0] and not ctx.tulis
    out = run(kls.jalankan(ctx, dict(args), r))
    assert simpan == {"enabled": True, "extra_emails": ["lama@contoh.test", "baru@contoh.test"]}
    assert out["pembatalan"] == {"enabled": True, "extra_emails": ["lama@contoh.test"]}
    run(kls.batalkan(ctx, out["pembatalan"]))
    assert simpan == {"enabled": True, "extra_emails": ["lama@contoh.test"]}
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(ctx, {"laporan": "valuasi_aksesoris_bulanan", "aktif": True}))
    assert e.value.status == 400 and "tidak ada yang perlu diubah" in e.value.pesan
    with pytest.raises(AlatError):
        run(kls.siapkan(ctx, {"laporan": "valuasi_aksesoris_bulanan", "email_tambah": ["bukan-email"]}))


# — kirim_notifikasi ————————————————————————————————————————————————————————————————————————————
PENGGUNA = [U("u-a", "hr", name="Ani Uji"), U("u-b", "manager", name="Budi Uji"),
            U("u-c", "manager", name="Budi Contoh"), U("u-v", "cmt_vendor", name="Vendor Uji"),
            dict(U("u-n", "hr", name="Nonaktif Uji"), status="inactive")]


def test_notifikasi_penerima_aturan_dan_kirim():
    kls = K("kirim_notifikasi")
    terkirim = []

    def _post(p, j):
        terkirim.append(j)
        return {"ok": True, "notification": {"notification_id": f"n{len(terkirim)}"}}
    ctx = Ctx(U("u-me", "admin_gudang"), {("GET", "/api/auth/users"): PENGGUNA,
                                          ("POST", "/api/collab/notifications"): _post})
    args = {"penerima": ["Ani Uji"], "peran": "manager", "judul": "Stok kancing menipis", "isi": "Cek layar",
            "menu": "wh-shopping-list"}
    r = run(kls.siapkan(ctx, dict(args)))
    _cek_rencana(r)
    assert "3 orang" in r["perubahan"][0]["sesudah"] and not ctx.tulis
    assert "Vendor" not in json.dumps(r) and "Nonaktif" not in json.dumps(r)
    out = run(kls.jalankan(ctx, dict(args), r))
    assert [j["target_user_id"] for j in terkirim] == ["u-a", "u-b", "u-c"]
    assert terkirim[0]["source_url"] == "#wh-shopping-list" and terkirim[0]["metadata"]["link_module"] == "wh-shopping-list"
    assert out["pembatalan"] is None and out["hasil"]["terkirim"] == 3
    for buruk, kode in ((["Budi"], 409), (["Vendor Uji"], 404), (["Nonaktif Uji"], 404)):
        with pytest.raises(AlatError) as e:
            run(kls.siapkan(ctx, {"penerima": buruk, "judul": "abc", "isi": "abc"}))
        assert e.value.status == kode
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(Ctx(U("u-v", "cmt_vendor"), {}), {"penerima": ["u-a"], "judul": "abc", "isi": "abc"}))
    assert e.value.status == 403


def test_notifikasi_batas_dan_kegagalan():
    kls = K("kirim_notifikasi")
    banyak = [U(f"u{i}", "tim_packing") for i in range(30)]
    ctx = Ctx(U("u-me", "owner"), {("GET", "/api/auth/users"): banyak})
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(ctx, {"peran": "tim_packing", "judul": "abc", "isi": "abc"}))
    assert e.value.status == 400 and "25" in e.value.pesan
    ctx = Ctx(U("u-me", "owner"), {("GET", "/api/auth/users"): PENGGUNA,
                                   ("POST", "/api/collab/notifications"): AlatError(403, "Peran Anda tidak boleh.")})
    with pytest.raises(AlatError) as e:  # gagal di penerima pertama → gagal bersih
        run(kls.jalankan(ctx, {"penerima": ["u-a", "u-b"], "judul": "abc", "isi": "abc"}, {}))
    assert e.value.status == 403
    n = {"i": 0}

    def _sebagian(p, j):
        n["i"] += 1
        if n["i"] == 2:
            raise AlatError(404, "Penerima notifikasi tidak ditemukan.")
        return {"notification": {"notification_id": "n"}}
    ctx.rute[("POST", "/api/collab/notifications")] = _sebagian
    out = run(kls.jalankan(ctx, {"penerima": ["u-a", "u-b", "u-c"], "judul": "abc", "isi": "abc"}, {}))
    assert "2 dari 3" in out["ringkas"] and out["hasil"]["gagal"] == 1


# — gerbang izin modul dinilai SEBELUM kartu ditawarkan (tanpa menulis) ————————————————————————————————————
def test_gerbang_modul_menolak_kartu_dan_pembatalan_hanya_bila_boleh(monkeypatch):
    import middleware.module_permission_gate as mpg
    ditolak = set()

    async def _evaluasi(method, path, payload):
        assert payload["id"] == "u1" and payload["role"] == "tim_packing"
        for m, awalan in ditolak:
            if method == m and path.startswith(awalan):
                return ({"id": "proc_requests", "label": "Permintaan Pengadaan (PR)", "portal": "procurement"},
                        "delete" if m == "DELETE" else "create", "portal")
        return None
    monkeypatch.setattr(mpg, "evaluate", _evaluasi)
    kls = K("buat_draf_pr")
    pr = {"id": "pr1", "request_number": "PR-0011", "status": "draft", "items": [{}], "total_estimated": 1}
    ctx = Ctx(U("u1", "tim_packing"), {("GET", "/api/rahaza/shopping-list/weekly"): BELANJA,
                                       ("POST", "/api/rahaza/shopping-list/create-pr"): {"request": pr}})
    ctx._token = "token-uji"
    ditolak.add(("POST", "/api/rahaza/shopping-list/create-pr"))
    with pytest.raises(AlatError) as e:
        run(kls.siapkan(ctx, {}))
    assert e.value.status == 403 and "Portal Pengadaan" in e.value.pesan and not ctx.calls
    ditolak.clear()
    ditolak.add(("DELETE", "/api/procurement/requests/"))
    r = run(kls.siapkan(ctx, {}))
    assert any("tidak bisa dihapus lewat Asisten AI" in c for c in r["catatan"])
    out = run(kls.jalankan(ctx, {}, r))
    assert out["pembatalan"] is None and out["hasil"]["pr_id"] == "pr1"
    ditolak.clear()
    assert run(kls.jalankan(ctx, {}, r))["pembatalan"] == {"pr_id": "pr1", "nomor": "PR-0011"}
