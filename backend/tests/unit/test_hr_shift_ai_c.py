"""Uji HERMETIK agen SHIFT-AI — Tahap C audit HR 9 Nov 2026 (modul shift untuk staf SDM). FakeDB in-memory.

Yang dibuktikan (fungsi route SUNGGUHAN dipanggil dengan pengguna uji):
  * satu master shift: toleransi per shift (`toleransi_menit` → `grace_minutes` yang dibaca aturan absen; kosong =
    setelan umum), jam mulai istirahat, istirahat 0 menit sah;
  * pola rotasi (kelipatan 7 hari, shift aktif saja) → draf jadwal: 2 minggu PAGI/SIANG, Minggu libur, cuti disetujui
    dilewati, hari libur kalender jadi entri libur; entri menyimpan `shift_id`;
  * penugasan massal per departemen / pilihan baris; daftar karyawan + shift berlaku + asalnya;
  * roster kalender: draf → jadwal terbit → penugasan → shift utama; sel cuti/libur terkunci; bentrok
    (cuti = berat, libur & istirahat < 12 jam = peringatan); terbit ditahan bentrok berat kecuali `paksa`;
  * ubah sel massal (cuti dilewati, hari libur hanya bila `isi_libur`), salin minggu (rentang diperpanjang);
  * jadwal terbit dipakai aturan absen (`core.attendance_rules.resolve_day_shift`) dengan toleransi shift;
  * permintaan ganti/tukar shift Portal Saya: rekan → atasan (akun dari `manager_id`) → SDM; pemisahan tugas;
    shift berubah sejak diajukan → 409; disetujui = jadwal terbit `perubahan`;
  * "Pola jadwal" & "Jadwal otomatis" lama dipensiunkan (410); baca roster/penugasan hanya SDM/atasan.
"""
import asyncio
import os
import sys
from datetime import date

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402


def run(c):
    return asyncio.run(c)


async def _noop(*a, **k):
    return None


HARI_INI = date(2026, 11, 10)          # Selasa
HR = {"id": "u-hr", "name": "HR Uji", "role": "hr"}
HR2 = {"id": "u-hr2", "name": "HR Dua", "role": "hr"}
SPV = {"id": "u-spv", "name": "Spv Uji", "role": "spv_packing", "employee_id": "e-spv"}
ANI = {"id": "u-ani", "name": "Ani", "role": "tim_packing", "employee_id": "e-ani"}
BUDI = {"id": "u-budi", "name": "Budi", "role": "tim_packing", "employee_id": "e-budi"}
CICI = {"id": "u-cici", "name": "Cici", "role": "tim_packing", "employee_id": "e-cici"}

SHIFTS = [
    {"id": "sh-p", "code": "PAGI", "shift_code": "PAGI", "name": "Pagi", "shift_name": "Pagi", "start_time": "07:00",
     "end_time": "15:00", "active": True, "status": "active", "color": "#f59e0b", "toleransi_menit": 10,
     "grace_minutes": 10, "days_active": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]},
    {"id": "sh-s", "code": "SIANG", "shift_code": "SIANG", "name": "Siang", "shift_name": "Siang",
     "start_time": "15:00", "end_time": "23:00", "active": True, "status": "active", "color": "#3b82f6",
     "days_active": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]},
    {"id": "sh-x", "code": "LAMA", "shift_code": "LAMA", "name": "Lama", "start_time": "08:00", "end_time": "16:00",
     "active": False, "status": "inactive"},
]


def _db():
    db = FakeDB()
    db.rahaza_shifts.docs = [dict(s) for s in SHIFTS]
    db.rahaza_employees.docs = [
        {"id": "e-ani", "employee_code": "K01", "name": "Ani", "active": True, "department": "Gudang",
         "location_id": "loc-1", "user_id": "u-ani", "manager_id": "e-spv"},
        {"id": "e-budi", "employee_code": "K02", "name": "Budi", "active": True, "department": "Gudang",
         "location_id": "loc-1", "user_id": "u-budi", "shift_id": "sh-s"},
        {"id": "e-cici", "employee_code": "K03", "name": "Cici", "active": True, "department": "Produksi",
         "location_id": "loc-2", "user_id": "u-cici"},
        {"id": "e-spv", "employee_code": "S01", "name": "Spv", "active": True, "department": "Gudang",
         "user_id": "u-spv"},
        {"id": "e-off", "employee_code": "K09", "name": "Nonaktif", "active": False, "department": "Gudang"},
    ]
    db.users.docs = [{"id": u["id"], "role": u["role"], "employee_id": u.get("employee_id"), "is_active": True}
                     for u in (HR, HR2, SPV, ANI, BUDI, CICI)]
    db.rahaza_locations.docs = [{"id": "loc-1", "name": "Gudang A"}, {"id": "loc-2", "name": "Pabrik"}]
    db.rahaza_production_calendar.docs = [{"date": "2026-11-20", "type": "holiday", "name": "Libur uji"}]
    return db


@pytest.fixture
def env(monkeypatch):
    import core.shift_permintaan as sp
    import routes.dewi_shift_scheduler as sch
    import routes.hr_shift_portal as portal
    import routes.hr_shifts as hs
    import services.hr_shift_service as svc
    db = _db()
    state = {"user": HR}

    async def auth(_r):
        return dict(state["user"])
    n = {"v": 100}

    async def ctr(_db, _k, **kw):
        n["v"] += 1
        return n["v"]
    for m in (sch, portal, hs):
        monkeypatch.setattr(m, "require_auth", auth)
        monkeypatch.setattr(m, "get_db", lambda: db)
    for m in (sch, hs):
        monkeypatch.setattr(m, "log_activity", _noop)
    monkeypatch.setattr(sch, "today_wib", lambda: HARI_INI)
    monkeypatch.setattr(portal, "today_wib", lambda: HARI_INI)
    monkeypatch.setattr(svc, "next_counter", ctr)
    monkeypatch.setattr(sp, "_notif", _noop)
    return {"db": db, "state": state, "sch": sch, "portal": portal, "hs": hs, "svc": svc, "sp": sp}


def as_(env, user):
    env["state"]["user"] = user


def _pola_2_minggu(env):
    sch = env["sch"]
    urutan = ["sh-p"] * 6 + [None] + ["sh-s"] * 6 + [None]
    return run(sch.buat_pola(FakeRequest(), sch.PolaModel(nama="Rotasi 2 minggu", urutan=urutan)))["data"]


# ═══════════════════════════════════════════════════════════════════════════
class TestMasterShift:
    def test_toleransi_disalin_ke_grace_dan_bisa_dikosongkan(self, env):
        hs, db = env["hs"], env["db"]
        out = run(hs.create_shift_endpoint(FakeRequest(), hs.ShiftCreateModel(
            shift_code="MLM", shift_name="Malam uji", start_time="23:00", end_time="07:00", is_overnight=True,
            toleransi_menit=15, istirahat_mulai="03:00")))["data"]
        assert out["toleransi_menit"] == 15 and out["grace_minutes"] == 15 and out["istirahat_mulai"] == "03:00"
        run(hs.update_shift(FakeRequest(), out["id"], hs.ShiftUpdateModel(toleransi_menit=None)))
        doc = next(d for d in db.rahaza_shifts.docs if d["id"] == out["id"])
        assert "toleransi_menit" not in doc and "grace_minutes" not in doc      # ikut setelan umum
        assert doc["istirahat_mulai"] == "03:00"                                # tidak dikirim = tidak berubah

    def test_istirahat_nol_sah_dan_toleransi_batas(self, env):
        hs, db = env["hs"], env["db"]
        run(hs.update_shift(FakeRequest(), "sh-s", hs.ShiftUpdateModel(break_duration_minutes=0, toleransi_menit=0)))
        doc = next(d for d in db.rahaza_shifts.docs if d["id"] == "sh-s")
        assert doc["effective_hours"] == 8.0 and doc["grace_minutes"] == 0
        with pytest.raises(HTTPException) as e:
            run(hs.update_shift(FakeRequest(), "sh-s", hs.ShiftUpdateModel(toleransi_menit=500)))
        assert e.value.status_code == 400 and "0–240" in e.value.detail

    def test_bentuk_shift_hr(self):
        from services.hr_shift_service import _to_hr_shape
        d = _to_hr_shape({"id": "a", "code": "A", "name": "A", "start_time": "08:00", "end_time": "16:00",
                          "grace_minutes": 7})
        assert d["toleransi_menit"] == 7 and d["istirahat_mulai"] is None


class TestPolaDanSusun:
    def test_pola_harus_minggu_penuh_dan_shift_aktif(self, env):
        sch = env["sch"]
        for urutan, kata in ((["sh-p"] * 5, "minggu penuh"), (["sh-x"] * 7, "nonaktif")):
            with pytest.raises(HTTPException) as e:
                run(sch.buat_pola(FakeRequest(), sch.PolaModel(nama="Salah", urutan=urutan)))
            assert kata in e.value.detail

    def test_draf_dari_pola_rotasi(self, env):
        sch, db = env["sch"], env["db"]
        pola = _pola_2_minggu(env)
        assert pola["minggu"] == 2
        db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "e-ani", "status": "approved",
                                          "from_date": "2026-11-18", "to_date": "2026-11-18", "leave_kind": "cuti"}]
        out = run(sch.buat_jadwal(FakeRequest(), sch.JadwalBaruModel(
            start_date="2026-11-16", end_date="2026-11-29", department="Gudang", cara="pola", pola_id=pola["id"])))
        doc = db.rahaza_schedules.docs[0]
        assert doc["status"] == "draft" and set(doc["employee_ids"]) == {"e-ani", "e-budi", "e-spv"}
        ani = {e["date"]: e for e in doc["shifts"] if e["employee_id"] == "e-ani"}
        assert ani["2026-11-16"]["shift_id"] == "sh-p" and ani["2026-11-16"]["shift_code"] == "PAGI"
        assert ani["2026-11-16"]["grace_minutes"] == 10                        # toleransi shift ikut entri
        assert ani["2026-11-22"].get("libur") is True                          # Minggu = libur menurut pola
        assert ani["2026-11-23"]["shift_id"] == "sh-s"                          # minggu ke-2 = SIANG
        assert "2026-11-18" not in ani                                          # cuti disetujui dilewati
        assert ani["2026-11-20"].get("libur") is True                           # libur kalender tidak dijadwalkan
        assert {"employee_id": "e-ani", "date": "2026-11-18", "alasan": "Cuti"} in out["data"]["dilewati"]

    def test_pratinjau_tidak_menyimpan(self, env):
        sch, db = env["sch"], env["db"]
        out = run(sch.pratinjau_jadwal(FakeRequest(), start_date="2026-11-16", end_date="2026-11-17", cara="shift",
                                       shift_id="sh-p", employee_ids="e-ani,e-budi"))["data"]
        assert db.rahaza_schedules.docs == []
        assert out["cakupan"][0]["per_shift"] == {"PAGI": 2} and out["metadata"]["total_shifts"] == 4

    def test_rentang_terlalu_panjang(self, env):
        sch = env["sch"]
        with pytest.raises(HTTPException) as e:
            run(sch.buat_jadwal(FakeRequest(), sch.JadwalBaruModel(start_date="2026-11-01", end_date="2027-02-01",
                                                                    cara="shift", shift_id="sh-p")))
        assert "62 hari" in e.value.detail


class TestPenugasanMassal:
    def test_per_departemen_dan_pilihan_baris(self, env):
        hs, db = env["hs"], env["db"]
        out = run(hs.create_assignment_massal(FakeRequest(), hs.AssignMassalModel(
            department="Gudang", shift_id="sh-p", effective_from="2026-11-01")))
        assert out["data"]["berhasil"] == 3 and out["data"]["gagal"] == []        # karyawan nonaktif tidak ikut
        out = run(hs.create_assignment_massal(FakeRequest(), hs.AssignMassalModel(
            employee_ids=["e-cici"], shift_id="sh-s", effective_from="2026-11-01")))
        assert out["data"]["berhasil"] == 1
        rows = {r["employee_id"]: r for r in run(hs.penugasan_per_karyawan(FakeRequest(), tanggal="2026-11-10"))["data"]}
        assert rows["e-ani"]["shift"]["kode"] == "PAGI" and rows["e-ani"]["sumber"] == "penugasan"
        assert rows["e-cici"]["shift"]["kode"] == "SIANG" and rows["e-ani"]["location_name"] == "Gudang A"

    def test_tanpa_pilihan_ditolak_dan_staf_ditolak(self, env):
        hs = env["hs"]
        with pytest.raises(HTTPException) as e:
            run(hs.create_assignment_massal(FakeRequest(), hs.AssignMassalModel(shift_id="sh-p", effective_from="2026-11-01")))
        assert e.value.status_code == 400
        as_(env, ANI)
        with pytest.raises(HTTPException) as e:
            run(hs.create_assignment_massal(FakeRequest(), hs.AssignMassalModel(
                department="Gudang", shift_id="sh-p", effective_from="2026-11-01")))
        assert e.value.status_code == 403
        with pytest.raises(HTTPException) as e:
            run(hs.penugasan_per_karyawan(FakeRequest()))
        assert e.value.status_code == 403


class TestRosterDanBentrok:
    def _draf(self, env, **kw):
        sch = env["sch"]
        body = dict(start_date="2026-11-16", end_date="2026-11-22", employee_ids=["e-ani", "e-budi"], cara="shift",
                    shift_id="sh-p")
        body.update(kw)
        run(sch.buat_jadwal(FakeRequest(), sch.JadwalBaruModel(**body)))
        return env["db"].rahaza_schedules.docs[-1]

    def test_urutan_sumber_dan_kunci(self, env):
        sch, db = env["sch"], env["db"]
        db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "e-budi", "status": "approved",
                                          "from_date": "2026-11-17", "to_date": "2026-11-17", "leave_kind": "sakit"}]
        out = run(sch.roster(FakeRequest(), dari="2026-11-16", sampai="2026-11-22", department="Gudang"))["data"]
        budi = next(k for k in out["karyawan"] if k["id"] == "e-budi")
        sel = {c["t"]: c for c in budi["sel"]}
        assert sel["2026-11-16"]["s"] == "sh-s" and sel["2026-11-16"]["src"] == "karyawan"
        assert sel["2026-11-17"]["kunci"] == "cuti" and sel["2026-11-17"]["ket"] == "Sakit"
        assert sel["2026-11-20"]["kunci"] == "libur" and sel["2026-11-22"]["ket"] == "Libur mingguan"
        assert out["tanggal"][0]["label"] == "Sen 16 Nov"
        # shift utama di hari cuti = bentrok berat; di hari libur kalender = peringatan
        jenis = {(b["employee_id"], b["date"]): b["tingkat"] for b in out["bentrok"]}
        assert jenis[("e-budi", "2026-11-17")] == "berat" and jenis[("e-budi", "2026-11-20")] == "peringatan"

    def test_draf_ubah_sel_lalu_terbit_dipakai_absen(self, env):
        sch, db = env["sch"], env["db"]
        doc = self._draf(env)
        out = run(sch.ubah_sel(FakeRequest(), doc["id"], sch.UbahSelModel(perubahan=[
            sch.UbahSel(employee_id="e-ani", date="2026-11-17", shift_id="sh-s"),
            sch.UbahSel(employee_id="e-ani", date="2026-11-20", shift_id="sh-s"),   # libur kalender → dilewati
            sch.UbahSel(employee_id="e-ani", date="2026-11-19", shift_id=None),     # jadi libur
        ])))["data"]
        assert out["diubah"] == 2 and out["dilewati"][0]["date"] == "2026-11-20"
        r = run(sch.roster(FakeRequest(), dari="2026-11-16", sampai="2026-11-19", jadwal_id=doc["id"],
                           department="Gudang"))["data"]
        ani = {c["t"]: c for c in next(k for k in r["karyawan"] if k["id"] == "e-ani")["sel"]}
        assert ani["2026-11-17"]["s"] == "sh-s" and ani["2026-11-17"]["src"] == "draf"
        assert ani["2026-11-19"]["lj"] is True and ani["2026-11-19"]["s"] is None
        # SIANG 17 (s.d. 23:00) → PAGI 18 (07:00) = istirahat 8 jam → peringatan
        assert any(b["jenis"] == "istirahat" and b["date"] == "2026-11-18" for b in r["bentrok"])
        # sebelum terbit, aturan absen belum memakai draf
        from core.attendance_rules import resolve_day_shift
        emp = next(e for e in db.rahaza_employees.docs if e["id"] == "e-ani")
        assert run(resolve_day_shift(db, emp, "2026-11-17")) is None
        run(sch.publish_schedule(FakeRequest(), doc["id"], None))
        sh = run(resolve_day_shift(db, emp, "2026-11-16"))
        assert sh["code"] == "PAGI" and sh["source"] == "jadwal" and sh["grace_minutes"] == 10
        # terbit: tanggal lewat tidak bisa diubah, hari ini ke depan bisa
        env["sch"].today_wib = lambda: date(2026, 11, 18)
        out = run(sch.ubah_sel(FakeRequest(), doc["id"], sch.UbahSelModel(perubahan=[
            sch.UbahSel(employee_id="e-ani", date="2026-11-16", shift_id="sh-s"),
            sch.UbahSel(employee_id="e-ani", date="2026-11-21", shift_id="sh-s")])))["data"]
        assert out["diubah"] == 1 and "sudah lewat" in out["dilewati"][0]["alasan"]

    def test_terbit_ditahan_bentrok_berat_kecuali_paksa(self, env):
        sch, db = env["sch"], env["db"]
        doc = self._draf(env)
        db.rahaza_leave_requests.docs = [{"id": "lv2", "employee_id": "e-ani", "status": "approved",
                                          "from_date": "2026-11-18", "to_date": "2026-11-18", "leave_kind": "cuti"}]
        b = run(sch.bentrok_jadwal(FakeRequest(), doc["id"]))["data"]
        assert b["jumlah"]["berat"] == 1
        with pytest.raises(HTTPException) as e:
            run(sch.publish_schedule(FakeRequest(), doc["id"], None))
        assert e.value.status_code == 409 and e.value.detail["jumlah"]["berat"] == 1
        run(sch.publish_schedule(FakeRequest(), doc["id"], sch.TerbitModel(paksa=True)))
        assert db.rahaza_schedules.docs[-1]["status"] == "published"

    def test_salin_minggu_memperpanjang(self, env):
        sch, db = env["sch"], env["db"]
        doc = self._draf(env)
        run(sch.ubah_sel(FakeRequest(), doc["id"], sch.UbahSelModel(perubahan=[
            sch.UbahSel(employee_id="e-budi", date="2026-11-16", shift_id="sh-s")])))
        out = run(sch.salin_minggu(FakeRequest(), doc["id"], sch.SalinMingguModel(dari="2026-11-18", ke="2026-11-25")))
        assert out["data"]["end_date"] == "2026-11-29"
        d = db.rahaza_schedules.docs[-1]
        budi = {e["date"]: e for e in d["shifts"] if e["employee_id"] == "e-budi"}
        assert budi["2026-11-23"]["shift_id"] == "sh-s" and budi["2026-11-24"]["shift_id"] == "sh-p"
        assert budi["2026-11-29"].get("libur") is True

    def test_hapus_hanya_draf_dan_tarik_jadwal_depan(self, env):
        sch, db = env["sch"], env["db"]
        doc = self._draf(env)
        run(sch.publish_schedule(FakeRequest(), doc["id"], None))
        with pytest.raises(HTTPException):
            run(sch.delete_schedule(FakeRequest(), doc["id"]))
        run(sch.batalkan_jadwal(FakeRequest(), doc["id"]))           # mulai 16 Nov > hari ini 10 Nov
        assert db.rahaza_schedules.docs[-1]["status"] == "dibatalkan"

    def test_staf_tidak_boleh_membaca_roster(self, env):
        as_(env, ANI)
        with pytest.raises(HTTPException) as e:
            run(env["sch"].roster(FakeRequest(), dari="2026-11-16", sampai="2026-11-17"))
        assert e.value.status_code == 403


class TestPensiun:
    def test_pola_lama_dan_generate_410(self, env):
        sch = env["sch"]
        for fn in (sch.create_shift_template, sch.generate_schedule):
            with pytest.raises(HTTPException) as e:
                run(fn(FakeRequest()))
            assert e.value.status_code == 410
        assert run(sch.list_shift_templates(FakeRequest()))["dipensiunkan"] is True


class TestPermintaanShift:
    def test_ganti_atasan_lalu_sdm(self, env):
        portal, sch, db = env["portal"], env["sch"], env["db"]
        run(env["hs"].create_assignment_massal(FakeRequest(), env["hs"].AssignMassalModel(
            employee_ids=["e-ani"], shift_id="sh-p", effective_from="2026-11-01")))
        as_(env, ANI)
        out = run(portal.ajukan(FakeRequest(), portal.PermintaanModel(
            jenis="ganti", tanggal="2026-11-12", shift_id="sh-s", alasan="Ada urusan keluarga pagi")))["data"]
        assert out["status"] == "menunggu_atasan" and out["shift_asal"]["kode"] == "PAGI"
        assert "atasan_user_ids" not in out                                  # tidak dibocorkan ke layar
        rid = out["id"]
        as_(env, BUDI)                                                         # bukan atasan
        with pytest.raises(HTTPException) as e:
            run(portal.putus_atasan(FakeRequest(), rid, portal.JawabanModel(setujui=True)))
        assert e.value.status_code == 403
        as_(env, SPV)
        assert run(portal.permintaan_saya(FakeRequest()))["perlu_persetujuan_saya"][0]["id"] == rid
        run(portal.putus_atasan(FakeRequest(), rid, portal.JawabanModel(setujui=True, catatan="Oke")))
        as_(env, HR)
        assert [r["id"] for r in run(sch.daftar_permintaan(FakeRequest()))["data"]] == [rid]
        run(sch.putuskan_permintaan(FakeRequest(), rid, sch.PutusanModel(setujui=True)))
        req = db.hr_shift_requests.docs[0]
        assert req["status"] == "disetujui" and [r["tahap"] for r in req["riwayat"]] == ["pengajuan", "atasan", "sdm"]
        from core.attendance_rules import resolve_day_shift
        emp = next(e for e in db.rahaza_employees.docs if e["id"] == "e-ani")
        assert run(resolve_day_shift(db, emp, "2026-11-12"))["code"] == "SIANG"
        assert run(resolve_day_shift(db, emp, "2026-11-13"))["code"] == "PAGI"
        jd = next(j for j in db.rahaza_schedules.docs if j.get("jenis") == "perubahan")
        assert jd["status"] == "published" and jd["shifts"][0]["shift_id"] == "sh-s"

    def test_tukar_rekan_lalu_sdm_tanpa_atasan(self, env):
        portal, sch, db = env["portal"], env["sch"], env["db"]
        db.rahaza_employees.docs[0].pop("manager_id")
        db.rahaza_employees.docs[0]["shift_id"] = "sh-p"
        as_(env, ANI)
        rekan = run(portal.rekan_tukar(FakeRequest(), tanggal="2026-11-12"))["rekan"]
        assert {r["employee_id"] for r in rekan} == {"e-budi", "e-spv"}
        out = run(portal.ajukan(FakeRequest(), portal.PermintaanModel(
            jenis="tukar", tanggal="2026-11-12", rekan_employee_id="e-budi", alasan="Tukar karena kuliah")))["data"]
        assert out["status"] == "menunggu_rekan" and out["rekan_shift_asal"]["kode"] == "SIANG"
        as_(env, CICI)
        with pytest.raises(HTTPException):
            run(portal.jawab_rekan(FakeRequest(), out["id"], portal.JawabanModel(setuju=True)))
        as_(env, BUDI)
        assert run(portal.jawab_rekan(FakeRequest(), out["id"], portal.JawabanModel(setuju=True)))["data"]["status"] == "menunggu_hr"
        as_(env, HR)
        run(sch.putuskan_permintaan(FakeRequest(), out["id"], sch.PutusanModel(setujui=True)))
        from core.attendance_rules import resolve_day_shift
        ani, budi = db.rahaza_employees.docs[0], db.rahaza_employees.docs[1]
        assert run(resolve_day_shift(db, ani, "2026-11-12"))["code"] == "SIANG"
        assert run(resolve_day_shift(db, budi, "2026-11-12"))["code"] == "PAGI"

    def test_shift_berubah_sejak_diajukan_409(self, env):
        portal, sch, db = env["portal"], env["sch"], env["db"]
        db.rahaza_employees.docs[0].pop("manager_id")
        db.rahaza_employees.docs[0]["shift_id"] = "sh-p"
        as_(env, ANI)
        rid = run(portal.ajukan(FakeRequest(), portal.PermintaanModel(
            jenis="ganti", tanggal="2026-11-12", shift_id="sh-s", alasan="Alasan uji panjang")))["data"]["id"]
        db.rahaza_employees.docs[0]["shift_id"] = "sh-s"
        as_(env, HR)
        with pytest.raises(HTTPException) as e:
            run(sch.putuskan_permintaan(FakeRequest(), rid, sch.PutusanModel(setujui=True)))
        assert e.value.status_code == 409 and "sudah berubah" in e.value.detail
        assert db.hr_shift_requests.docs[0]["status"] == "menunggu_hr"
        assert not [j for j in db.rahaza_schedules.docs if j.get("jenis") == "perubahan"]

    def test_pemisahan_tugas_dan_validasi(self, env):
        portal, sch, db = env["portal"], env["sch"], env["db"]
        db.rahaza_employees.docs.append({"id": "e-hr", "name": "HR Uji", "active": True, "user_id": "u-hr",
                                         "department": "SDM", "shift_id": "sh-p"})
        as_(env, HR)
        rid = run(portal.ajukan(FakeRequest(), portal.PermintaanModel(
            jenis="ganti", tanggal="2026-11-12", shift_id="sh-s", alasan="Permintaan HR sendiri")))["data"]["id"]
        with pytest.raises(HTTPException) as e:
            run(sch.putuskan_permintaan(FakeRequest(), rid, sch.PutusanModel(setujui=True)))
        assert e.value.status_code == 403
        as_(env, HR2)
        run(sch.putuskan_permintaan(FakeRequest(), rid, sch.PutusanModel(setujui=False, catatan="Tidak bisa")))
        assert db.hr_shift_requests.docs[0]["status"] == "ditolak"
        as_(env, ANI)
        for body, kata in ((dict(jenis="ganti", tanggal="2026-11-01", shift_id="sh-s", alasan="Sudah lewat"), "lewat"),
                           (dict(jenis="ganti", tanggal="2026-11-12", shift_id="sh-x", alasan="Shift lama"), "aktif"),
                           (dict(jenis="libur", tanggal="2026-11-12", alasan="Jenis salah"), "Jenis")):
            with pytest.raises(HTTPException) as e:
                run(portal.ajukan(FakeRequest(), portal.PermintaanModel(**body)))
            assert kata in e.value.detail

    def test_batalkan_oleh_pemohon(self, env):
        portal, db = env["portal"], env["db"]
        as_(env, ANI)
        rid = run(portal.ajukan(FakeRequest(), portal.PermintaanModel(
            jenis="ganti", tanggal="2026-11-12", shift_id="sh-s", alasan="Batal nanti")))["data"]["id"]
        with pytest.raises(HTTPException):
            run(portal.ajukan(FakeRequest(), portal.PermintaanModel(
                jenis="ganti", tanggal="2026-11-12", shift_id="sh-s", alasan="Dobel tanggal")))
        run(portal.batalkan(FakeRequest(), rid))
        assert db.hr_shift_requests.docs[0]["status"] == "dibatalkan"
        jadwal = run(portal.jadwal_saya(FakeRequest(), hari=3))
        assert [h["date"] for h in jadwal["hari"]] == ["2026-11-10", "2026-11-11", "2026-11-12"]
