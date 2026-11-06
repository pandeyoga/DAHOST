"""Uji HERMETIK Tahap 5 — audit form portal SDM & Portal Saya (agen `sdm`, 2026-11-07). FakeDB in-memory.

  1 Data Karyawan: shift utama dari master shift (validasi, data impor lama tetap bisa disimpan)
  2 Grid absensi: shift bawaan per karyawan (jadwal terbit → penugasan → shift karyawan), bukan shift pertama
  3 Penugasan shift: karyawan wajib ada di master; kode/nama/departemen tersimpan; tanggal berakhir ≥ mulai
  4 Struktur Organisasi: headcount memakai karyawan AKTIF (`active`), bukan field `status: aktif` yang tidak ada
  5 Tombol "Muat Demo" (struktur, rekrutmen, onboarding, pembelajaran) tidak lagi menghapus data yang ada
  6 Onboarding: karyawan dicari lewat `id` (nama, departemen, jabatan terisi); id tak dikenal ditolak
  7 Pengaturan payroll: pesan validasi potongan terlambat tanpa istilah program
  8 Perjalanan dinas: tarif per diem bawaan sama dengan layar Konfigurasi Per Diem
"""
import asyncio
import os
import sys

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402


def run(coro):
    return asyncio.run(coro)


SHIFTS = [
    {"id": "s1", "code": "S1", "name": "Shift 1", "start_time": "07:00", "end_time": "15:00", "active": True},
    {"id": "s2", "code": "S2", "name": "Shift 2", "start_time": "15:00", "end_time": "23:00", "active": True},
    {"id": "reg", "code": "REG", "name": "Reguler", "start_time": "08:00", "end_time": "16:00", "active": True},
]


def _db_with_shifts():
    db = FakeDB()
    db.rahaza_shifts.docs = [dict(s) for s in SHIFTS] + [
        {"id": "old", "code": "OLD", "name": "Lama", "start_time": "06:00", "end_time": "14:00", "active": False}]
    return db


# ── 1 · Data Karyawan: shift utama ─────────────────────────────────────────────
class TestShiftKaryawan:
    def _f(self):
        from routes.rahaza_master import _employee_shift_fields
        return _employee_shift_fields

    def test_tidak_dikirim_tidak_disentuh(self):
        assert run(self._f()(_db_with_shifts(), {"name": "x"})) == {}

    def test_kosong_berarti_tanpa_shift(self):
        assert run(self._f()(_db_with_shifts(), {"shift_id": ""})) == {"shift_id": None, "shift_code": None}

    def test_dari_master_dengan_kode(self):
        assert run(self._f()(_db_with_shifts(), {"shift_id": "s2", "shift_code": "SALAH"})) == {
            "shift_id": "s2", "shift_code": "S2"}

    def test_id_tak_dikenal_ditolak(self):
        with pytest.raises(HTTPException) as e:
            run(self._f()(_db_with_shifts(), {"shift_id": "tidak-ada"}))
        assert e.value.status_code == 400 and "master shift" in e.value.detail

    def test_nilai_lama_yang_sama_tidak_divalidasi(self):
        """Data impor lama dengan shift yang sudah tidak ada tetap bisa diubah kolom lainnya."""
        body = {"shift_id": "hilang", "shift_code": "X", "name": "Budi"}
        assert run(self._f()(_db_with_shifts(), body, {"shift_id": "hilang"})) == {}
        assert "shift_id" not in body and "shift_code" not in body and body["name"] == "Budi"


# ── 2 · Grid absensi: shift bawaan per karyawan ────────────────────────────────
class TestShiftBawaanGrid:
    def test_urutan_jadwal_penugasan_karyawan(self):
        from core.attendance_rules import default_shift_ids
        db = _db_with_shifts()
        day = "2026-11-09"
        db.rahaza_schedules.docs = [{"status": "published", "start_date": "2026-11-09", "end_date": "2026-11-15",
                                     "published_at": "2026-11-01T00:00:00",
                                     "shifts": [{"employee_id": "e1", "date": day, "shift_code": "S2"}]},
                                    {"status": "draft", "start_date": "2026-11-09", "end_date": "2026-11-15",
                                     "shifts": [{"employee_id": "e2", "date": day, "shift_code": "S2"}]}]
        db.hr_shift_assignments.docs = [
            {"employee_id": "e1", "shift_id": "s1", "status": "active", "effective_from": "2026-01-01", "effective_until": None},
            {"employee_id": "e2", "shift_id": "s1", "status": "active", "effective_from": "2026-01-01", "effective_until": ""},
            {"employee_id": "e3", "shift_id": "s1", "status": "active", "effective_from": "2026-01-01", "effective_until": "2026-10-31"},
        ]
        emps = [{"id": "e1", "shift_id": "reg"}, {"id": "e2", "shift_id": "reg"}, {"id": "e3", "shift_id": "reg"},
                {"id": "e4"}, {"id": "e5", "shift_id": "old"}]
        out = run(default_shift_ids(db, emps, day, SHIFTS))
        assert out["e1"] == "s2"     # jadwal terbit menang atas penugasan
        assert out["e2"] == "s1"     # jadwal draf tidak berlaku → penugasan
        assert out["e3"] == "reg"    # penugasan sudah berakhir → shift karyawan
        assert "e4" not in out       # tidak diketahui → grid memakai shift pertama
        assert "e5" not in out       # shift nonaktif tidak dipakai

    def test_tanpa_karyawan(self):
        from core.attendance_rules import default_shift_ids
        assert run(default_shift_ids(_db_with_shifts(), [], "2026-11-09", SHIFTS)) == {}


# ── 3 · Penugasan shift ────────────────────────────────────────────────────────
class TestPenugasanShift:
    def _db(self):
        db = _db_with_shifts()
        db.rahaza_employees.docs = [
            {"id": "e1", "employee_code": "K-001", "name": "Ani", "department": "Produksi", "active": True},
            {"id": "e9", "employee_code": "K-009", "name": "Keluar", "active": False},
        ]
        return db

    def test_karyawan_tidak_dikenal_ditolak(self):
        from services import hr_shift_service as hs
        with pytest.raises(ValueError, match="Karyawan tidak ditemukan"):
            run(hs.assign_shift(self._db(), "emp-001", "s1", "2026-11-01", None, "HR"))

    def test_karyawan_nonaktif_ditolak(self):
        from services import hr_shift_service as hs
        with pytest.raises(ValueError):
            run(hs.assign_shift(self._db(), "e9", "s1", "2026-11-01", None, "HR"))

    def test_tanggal_berakhir_sebelum_mulai(self):
        from services import hr_shift_service as hs
        with pytest.raises(ValueError, match="Tanggal berakhir"):
            run(hs.assign_shift(self._db(), "e1", "s1", "2026-11-10", "2026-11-01", "HR"))

    def test_menyimpan_kode_nama_departemen(self, monkeypatch):
        from services import hr_shift_service as hs

        async def _ctr(db, key, **kw):
            return 7
        monkeypatch.setattr(hs, "next_counter", _ctr)
        db = self._db()
        doc = run(hs.assign_shift(db, "e1", "s2", "2026-11-01", None, "HR"))
        assert doc["employee_code"] == "K-001" and doc["employee_name"] == "Ani"
        assert doc["department"] == "Produksi" and doc["shift_code"] == "S2"


# ── 4 · Struktur Organisasi: headcount karyawan aktif ──────────────────────────
class TestHeadcountOrg:
    def _db(self):
        db = FakeDB()
        db.dewi_org_units.docs = [
            {"unit_id": "u1", "name": "Produksi", "type": "department", "level": 0, "is_active": True,
             "headcount_actual": 99, "headcount_target": 3},
        ]
        db.rahaza_employees.docs = [
            {"id": "a", "department": "Produksi", "active": True},
            {"id": "b", "department": "Produksi", "active": True},
            {"id": "c", "department": "Produksi", "active": False},
        ]
        return db

    def test_headcount_dari_karyawan_aktif(self):
        from routes.dewi_org import headcount_analysis, get_org_chart
        hc = run(headcount_analysis(db=self._db(), user={}))
        assert hc["units"][0]["actual"] == 2 and hc["units"][0]["gap"] == 1
        chart = run(get_org_chart(db=self._db(), user={}))
        assert chart["total_employees"] == 2


# ── 5 · Muat Demo tidak menghapus data yang ada ────────────────────────────────
class TestDemoTidakMenghapus:
    def test_struktur_organisasi(self):
        from routes.dewi_org import seed_org
        db = FakeDB()
        db.dewi_org_units.docs = [{"unit_id": "nyata", "name": "Gudang"}]
        with pytest.raises(HTTPException) as e:
            run(seed_org(db=db, user={}))
        assert e.value.status_code == 409
        assert db.dewi_org_units.docs == [{"unit_id": "nyata", "name": "Gudang"}]

    def test_rekrutmen_onboarding_pembelajaran(self):
        from routes.dewi_recruitment import seed_recruitment
        from routes.dewi_onboarding import seed_onboarding
        from routes.dewi_lms import seed_lms
        for fn, col in ((seed_recruitment, "dewi_recruitment_candidates"),
                        (seed_onboarding, "dewi_onboarding_checklists"),
                        (seed_lms, "dewi_lms_courses")):
            db = FakeDB()
            db[col].docs = [{"id": "nyata"}]
            with pytest.raises(HTTPException) as e:
                run(fn(db=db, user={}))
            assert e.value.status_code == 409
            assert db[col].docs == [{"id": "nyata"}]

    def test_struktur_kosong_boleh_dimuat(self):
        from routes.dewi_org import seed_org
        db = FakeDB()
        run(seed_org(db=db, user={}))
        assert db.dewi_org_units.docs


# ── 6 · Onboarding: karyawan dari master ───────────────────────────────────────
class TestOnboardingKaryawan:
    def _db(self):
        db = FakeDB()
        db.rahaza_employees.docs = [{"id": "e1", "employee_code": "K-1", "name": "Sari", "department": "QC",
                                     "job_title": "Operator QC", "active": True}]
        return db

    def test_data_karyawan_terisi(self):
        from routes.dewi_onboarding import create_checklist
        db = self._db()
        out = run(create_checklist(body={"employee_id": "e1"}, db=db, user={"name": "HR"}))
        cl = out["checklist"]
        assert cl["employee_name"] == "Sari" and cl["employee_dept"] == "QC"
        assert cl["employee_position"] == "Operator QC"

    def test_id_tak_dikenal_ditolak(self):
        from routes.dewi_onboarding import create_checklist
        with pytest.raises(HTTPException) as e:
            run(create_checklist(body={"employee_id": "emp-001", "employee_name": "X"}, db=self._db(), user={}))
        assert e.value.status_code == 400


# ── 7 · Pesan validasi potongan terlambat ──────────────────────────────────────
class TestPesanPengaturanPayroll:
    def test_tanpa_istilah_program(self, monkeypatch):
        from routes import rahaza_payroll_settings as ps

        async def _hr(request):
            return {"id": "u", "name": "HR", "role": "hr"}
        monkeypatch.setattr(ps, "_require_hr", _hr)
        monkeypatch.setattr(ps, "get_db", lambda: FakeDB())
        from _fake_mongo import FakeRequest
        with pytest.raises(HTTPException) as e:
            run(ps.set_late_penalty(FakeRequest({"enabled": True, "mode": "per_minute", "amount_per_minute": 0})))
        assert "per_minute" not in e.value.detail and "amount_per_minute" not in e.value.detail
        assert "per menit" in e.value.detail


# ── 8 · Perjalanan dinas: tarif per diem bawaan satu sumber ────────────────────
class TestPerDiemBawaan:
    def test_bawaan_sama_dengan_layar_konfigurasi(self):
        from routes.employee_travel_requests import _get_per_diem_rate
        from routes.employee_per_diem import DEFAULT_RATES
        db = FakeDB()
        for dt in ("dalam_kota", "luar_kota", "luar_negeri"):
            assert run(_get_per_diem_rate(db, dt))["daily_rate"] == DEFAULT_RATES[dt]["daily_rate"]

    def test_tarif_terkonfigurasi_dipakai(self):
        from routes.employee_travel_requests import _get_per_diem_rate
        db = FakeDB()
        db.employee_per_diem_rates.docs = [{"destination_type": "luar_kota", "daily_rate": 275000, "is_active": True}]
        assert run(_get_per_diem_rate(db, "luar_kota"))["daily_rate"] == 275000
