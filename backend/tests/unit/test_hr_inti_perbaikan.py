"""Uji HERMETIK perbaikan HR inti (9 Nov 2026) — FakeDB, tanpa server/Mongo. Satu kelas per temuan audit
(`private/audit/audit_hr_2026-11-09.md`) / keputusan owner Q1–Q11 ("ikuti rekomendasi").

  H8/P1 akses data SDM · Q8 slip & rincian gaji · H5 terlambat (libur, cuti ½ hari, tugas luar) · Q4 toleransi per
  shift · Q3 pulang cepat · M13 hitung ulang terlambat · H3 penyesuaian slip kena pajak · M2 bulan gaji · M4 plafon
  JP · Q1 bonus tanpa catatan · Q9 lembur jam nyata · Q6/H6 atasan → HR · Q7 kuota cuti UU · Q11 tugas luar ·
  Q2 grid tanpa pengajuan · pola Portal Saya.
"""
import asyncio
import importlib
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeCursor, FakeDB, FakeRequest  # noqa: E402


def _imp(name):
    """Rute unggah (UploadFile) memeriksa python-multipart saat impor — dilewati bila tidak terpasang."""
    try:
        return importlib.import_module(name)
    except RuntimeError:
        import fastapi.dependencies.utils as _fdu
        checks = {n: getattr(_fdu, n) for n in ("check_file_field", "ensure_multipart_is_installed")
                  if hasattr(_fdu, n)}
        for n in checks:
            setattr(_fdu, n, lambda *a, **k: None)
        try:
            return importlib.import_module(name)
        finally:
            for n, fn in checks.items():
                setattr(_fdu, n, fn)


import core.attendance_rules as ar  # noqa: E402
import core.leave_engine as le  # noqa: E402
import core.tugas_luar as tl  # noqa: E402
import routes.approval_multilevel as aml  # noqa: E402
import routes.rahaza_attendance as att  # noqa: E402
import routes.rahaza_hr_reports as hr_reports  # noqa: E402
import routes.rahaza_overtime as ot  # noqa: E402
import routes.rahaza_payroll_payslips as slips  # noqa: E402
import routes.rahaza_payroll_rules as rules  # noqa: E402
import routes.rahaza_payroll_runs as runs  # noqa: E402
import routes.rahaza_payroll_shared as shared  # noqa: E402
import routes.rahaza_payroll_tax as tax  # noqa: E402
import services.approval_chain_service as acs  # noqa: E402
import utils.attendance_policy as policy  # noqa: E402
import utils.employee_identity as ident  # noqa: E402
import utils.leave_types as ltypes  # noqa: E402

leave_mod = _imp("routes.rahaza_leave")
balances = _imp("routes.rahaza_leave_balances")
portal_hr = _imp("routes.dewi_portal_saya_hr")
travel = _imp("routes.employee_travel_requests")

run = asyncio.run
WIB = timezone(timedelta(hours=7))
OCT = ("2026-10-01", "2026-10-31")
OCT_WD = [date(2026, 10, d) for d in range(1, 32) if date(2026, 10, d).weekday() != 6]

HR = {"id": "u-hr", "role": "hr", "name": "Brenda HR", "email": "hr@x"}
HR2 = {"id": "u-hr2", "role": "hr", "name": "Citra HR", "email": "hr2@x"}
OWNER = {"id": "u-own", "role": "owner", "name": "Owner"}
SPV = {"id": "u-spv", "role": "spv_packing", "name": "Sari SPV", "email": "spv@x"}
OPS = {"id": "u-ani", "role": "tim_packing", "name": "Ani", "email": "ani@x"}
STAF_HR = {"id": "u-staf", "role": "staff_hr", "name": "Staf SDM"}
AKUNTAN = {"id": "u-akt", "role": "accounting", "name": "Akuntan"}
PIC = {"id": "u-pic", "role": "pic_toko", "name": "PIC Toko"}

SHIFT_REG = {"id": "sh-reg", "code": "REG", "name": "Reguler", "start_time": "08:00", "end_time": "16:00",
             "break_duration_minutes": 60, "active": True}
LT_CUTI = {"id": "lt-ct", "code": "ANNUAL", "name": "Cuti Tahunan", "quota_default": 12, "active": True,
           "unpaid": False, "request_type": "cuti"}
LT_SAKIT = {"id": "lt-sk", "code": "SICK", "name": "Izin Sakit", "quota_default": 14, "active": True,
            "unpaid": False, "request_type": "sakit", "requires_document": True, "max_days_without_doc": 2}
LT_HAID = {"id": "lt-hd", "code": "MENSTRUAL", "name": "Izin Haid", "quota_default": 2, "active": True,
           "unpaid": False, "request_type": "sakit"}
LT_NIKAH = {"id": "lt-nk", "code": "MARRIAGE", "name": "Izin Pernikahan Sendiri", "quota_default": 3, "active": True,
            "unpaid": False, "request_type": "izin", "legal_basis": "Pasal 93 ayat 4 UU 13/2003"}


def _utc(day: str, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=WIB).astimezone(timezone.utc)


def _status(coro):
    try:
        run(coro)
        return 200
    except HTTPException as e:
        return e.status_code


def _err(coro) -> HTTPException:
    with pytest.raises(HTTPException) as ei:
        run(coro)
    return ei.value


class AggDB(FakeDB):
    """FakeDB + aggregate kosong (dasbor SDM memakai $group; isi tidak diuji di sini)."""

    def __getitem__(self, name):
        col = super().__getitem__(name)
        if not hasattr(col, "aggregate"):
            col.aggregate = lambda pipeline: FakeCursor([])
        return col


@pytest.fixture
def db(monkeypatch):
    d = AggDB()
    d.rahaza_shifts.docs = [dict(SHIFT_REG)]
    d.rahaza_employees.docs = [
        {"id": "emp-a", "name": "Ani", "employee_code": "E01", "active": True, "user_id": "u-ani",
         "shift_id": "sh-reg", "manager_id": "emp-s", "join_date": "2024-01-01"},
        {"id": "emp-s", "name": "Sari", "employee_code": "S01", "active": True, "user_id": "u-spv",
         "shift_id": "sh-reg"},
        {"id": "emp-b", "name": "Budi", "employee_code": "E02", "active": True, "user_id": "u-budi",
         "shift_id": "sh-reg"},
        {"id": "emp-h", "name": "Brenda", "employee_code": "H01", "active": True, "user_id": "u-hr"},
    ]
    d.users.docs = [{"id": u, "active": True, "role": r} for u, r in (
        ("u-ani", "tim_packing"), ("u-spv", "spv_packing"), ("u-budi", "tim_packing"), ("u-hr", "hr"),
        ("u-hr2", "hr"))]
    d.rahaza_leave_types.docs = [dict(LT_CUTI), dict(LT_SAKIT), dict(LT_HAID), dict(LT_NIKAH)]

    async def noop(*a, **k):
        return None

    for mod in (att, hr_reports, ot, leave_mod, balances, portal_hr, runs, slips, aml, travel):
        monkeypatch.setattr(mod, "get_db", lambda: d)
        if hasattr(mod, "log_activity"):
            monkeypatch.setattr(mod, "log_activity", noop)
    return d


def as_user(monkeypatch, user):
    async def _auth(_request=None, *a, **k):
        return dict(user)
    for m in (att, hr_reports, ot, leave_mod, balances, portal_hr, runs, slips, aml):
        monkeypatch.setattr(m, "require_auth", _auth)


@pytest.fixture
def notifs(monkeypatch):
    """Tangkap publish_notification (penerima = ID AKUN)."""
    sent = []

    async def pub(db, **kw):
        sent.append(kw)
        return kw
    import routes.rahaza_notifications as rn
    monkeypatch.setattr(rn, "publish_notification", pub)
    return sent


# ═════════════════════════════════════════════════════════════════════════════
# H8 / P1 — data SDM lintas karyawan hanya HR/atasan
# ═════════════════════════════════════════════════════════════════════════════
class TestAksesDataSdm:
    def _seed(self, db):
        db.rahaza_attendance_events.docs = [
            {"id": "e1", "employee_id": "emp-a", "date": "2026-11-02", "status": "hadir", "hours_worked": 8},
            {"id": "e2", "employee_id": "emp-b", "date": "2026-11-02", "status": "sakit", "hours_worked": 0}]

    @pytest.mark.parametrize("user", [OPS, PIC])
    def test_rekap_absensi_staf_hanya_miliknya(self, db, monkeypatch, user):
        self._seed(db)
        as_user(monkeypatch, user)
        rows = run(att.attendance_summary(FakeRequest(), from_="2026-11-01", to="2026-11-30"))
        assert [r["employee_id"] for r in rows] == (["emp-a"] if user is OPS else [])

    def test_rekap_absensi_hr_semua(self, db, monkeypatch):
        self._seed(db)
        as_user(monkeypatch, HR)
        rows = run(att.attendance_summary(FakeRequest(), from_="2026-11-01", to="2026-11-30"))
        assert {r["employee_id"] for r in rows} == {"emp-a", "emp-b"}

    def test_dasbor_sdm_ditolak_staf_dan_total_gaji_khusus_penggajian(self, db, monkeypatch):
        db.rahaza_payroll_runs.docs = [{"id": "r1", "period_from": "2026-10-26", "period_to": "2026-11-25",
                                        "status": "draft", "total_net": 41_000_000, "created_at": "2026-11-07"}]
        for u in (OPS, PIC):
            as_user(monkeypatch, u)
            assert _status(att.hr_dashboard(FakeRequest())) == 403
        as_user(monkeypatch, STAF_HR)
        out = run(att.hr_dashboard(FakeRequest()))
        assert "total_net" not in out["latest_payroll_run"]
        as_user(monkeypatch, HR)
        assert run(att.hr_dashboard(FakeRequest()))["latest_payroll_run"]["total_net"] == 41_000_000

    def test_daftar_persetujuan_bertingkat_staf_hanya_miliknya_dan_cuti_disembunyikan(self, db, monkeypatch):
        db.approval_requests.docs = [
            {"id": 1, "type": "leave", "status": "pending", "requester_id": "u-x", "meta": {"reason": "sakit"},
             "created_at": "1"},
            {"id": 2, "type": "expense", "status": "pending", "requester_id": "u-x", "created_at": "2"},
            {"id": 3, "type": "expense", "status": "pending", "requester_id": "u-ani", "created_at": "3"}]
        as_user(monkeypatch, OPS)
        out = run(aml.list_requests(FakeRequest(), status=None, type=None, limit=50, skip=0))
        assert [r["id"] for r in out["data"]] == [3]
        assert _status(aml.get_request(FakeRequest(), "2")) == 403
        as_user(monkeypatch, HR)
        out = run(aml.list_requests(FakeRequest(), status=None, type=None, limit=50, skip=0))
        assert sorted(r["id"] for r in out["data"]) == [2, 3]          # Q6: jenis cuti tidak tampil
        assert run(aml.list_requests(FakeRequest(), status=None, type="leave", limit=50, skip=0))["data"] == []

    def test_mesin_rantai_menolak_memutus_cuti(self, db):
        db.approval_requests.docs = [{"id": 9, "type": "leave", "status": "pending", "current_level": 1,
                                      "max_level": 1, "levels": [{"level": 1, "role": "manager"}],
                                      "requester_id": "u-x"}]
        with pytest.raises(ValueError, match="Cuti & Lembur"):
            run(acs.process_action(db, 9, "approve", dict(OWNER)))
        assert run(acs.create_approval_request(db, "leave", "L1", "L1", {"id": "u"})) is None
        assert all(c["type"] not in ("leave", "overtime") for c in acs.active_default_chains())

    def test_tulis_struktur_organisasi_hanya_hr(self):
        import routes.dewi_org as org
        for path in ("/units", "/units/{unit_id}", "/positions", "/positions/{position_id}", "/seed"):
            routes_ = [r for r in org.router.routes if r.path.endswith(path) and set(r.methods) & {"POST", "PUT"}]
            assert routes_ and all(r.dependencies for r in routes_), path


# ═════════════════════════════════════════════════════════════════════════════
# Q8 — slip & rincian gaji per orang hanya peran penggajian; Keuangan total + nilai transfer
# ═════════════════════════════════════════════════════════════════════════════
class TestAksesGaji:
    def _seed(self, db):
        db.rahaza_payroll_runs.docs = [{"id": "r1", "run_number": "PR-1", "status": "finalized",
                                        "period_from": "2026-10-01", "period_to": "2026-10-31", "total_net": 5_000_000,
                                        "warnings": [{"employee_name": "Ani", "message": "x"}]}]
        db.rahaza_payslips.docs = [{"id": "s1", "run_id": "r1", "employee_id": "emp-a", "employee_code": "E01",
                                    "employee_name": "Ani", "gross_pay": 5_500_000, "net_pay": 5_000_000,
                                    "deductions": [{"type": "pph21", "amount": 50_000}]}]
        db.rahaza_employees.docs[0].update(bank_name="BCA", bank_account_number="1234567890")

    def test_keuangan_melihat_nilai_transfer_tanpa_rincian(self, db, monkeypatch):
        self._seed(db)
        as_user(monkeypatch, AKUNTAN)
        out = run(runs.get_run("r1", FakeRequest()))
        assert out["detail_hidden"] and out["payslips"] == [] and "warnings" not in out["run"]
        assert out["transfers"] == [{"id": "s1", "employee_id": "emp-a", "employee_code": "E01",
                                     "employee_name": "Ani", "department": "", "bank_name": "BCA",
                                     "bank_account_number": "1234567890", "net_pay": 5_000_000.0}]

    def test_hr_penggajian_melihat_rincian_dan_staf_hr_ditolak(self, db, monkeypatch):
        self._seed(db)
        as_user(monkeypatch, HR)
        out = run(runs.get_run("r1", FakeRequest()))
        assert not out["detail_hidden"] and out["payslips"][0]["deductions"]
        for u in (STAF_HR, OPS):
            as_user(monkeypatch, u)
            assert _status(runs.get_run("r1", FakeRequest())) == 403

    def test_csv_keuangan_hanya_kolom_transfer(self, db, monkeypatch):
        self._seed(db)
        as_user(monkeypatch, AKUNTAN)
        resp = run(runs.export_run_csv("r1", FakeRequest()))

        async def body():
            return b"".join([c if isinstance(c, bytes) else c.encode() async for c in resp.body_iterator])
        txt = run(body()).decode()
        assert txt.splitlines()[0].startswith("run_number,period_from,period_to,employee_code,employee_name,bank_name")
        assert "gross_pay" not in txt and "1234567890" in txt

    def test_laporan_penggajian_staf_hr_hanya_total(self, db, monkeypatch):
        self._seed(db)
        db.rahaza_payroll_runs.docs[0]["created_at"] = "2026-11-01"
        as_user(monkeypatch, STAF_HR)
        monkeypatch.setattr(hr_reports, "_require_hr_admin", lambda request: _async(dict(STAF_HR)))
        out = run(hr_reports.get_payroll_summary(FakeRequest(), None, None, None, None))
        assert out["summary"] == [] and out["detail_hidden"] and out["aggregates"]["total_net"] == 5_000_000

    def test_gerbang_rincian_sama_dengan_gerbang_penggajian(self):
        for role in ("superadmin", "admin", "owner", "hr", "manager"):
            assert shared.can_view_payroll_detail({"role": role})
        for role in ("hr_manager", "staff_hr", "accounting", "manager_produksi"):
            assert not shared.can_view_payroll_detail({"role": role})
        assert shared.can_view_payroll_detail({"role": "x", "_permissions": ["payroll.manage"]})
        assert shared.can_view_payroll_transfer({"role": "accounting"})
        assert not shared.can_view_payroll_transfer({"role": "staff_hr"})


async def _async(v):
    return v


# ═════════════════════════════════════════════════════════════════════════════
# H5 + Q4 + Q5 — terlambat: hari libur, cuti ½ hari, cuti penuh, tugas luar, toleransi per shift
# ═════════════════════════════════════════════════════════════════════════════
EMP_A = {"id": "emp-a", "shift_id": "sh-reg"}


class TestTerlambat:
    def test_hari_kerja_biasa_tetap_sama(self, db):
        out = run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "08:20")))
        assert out["late_minutes"] == 15 and out["grace_minutes"] == 5   # perilaku lama: selisih − toleransi

    def test_minggu_dan_hari_libur_bukan_terlambat(self, db):
        out = run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-08", "10:00")))    # Minggu
        assert out["late_minutes"] == 0 and out["late_reason"] == "hari libur"
        db.rahaza_production_calendar.docs = [{"date": "2026-11-10", "type": "holiday", "name": "Hari Pahlawan"}]
        assert run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-10", "10:00")))["late_minutes"] == 0

    def test_minggu_yang_dijadwalkan_tetap_dinilai(self, db):
        db.rahaza_schedules.docs = [{"status": "published", "start_date": "2026-11-08", "end_date": "2026-11-08",
                                     "published_at": "x", "shifts": [{"employee_id": "emp-a", "date": "2026-11-08",
                                                                      "start_time": "08:00", "end_time": "16:00"}]}]
        assert run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-08", "08:30")))["late_minutes"] == 25

    def test_cuti_setengah_hari_pagi_acuan_sesudah_istirahat(self, db):
        db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "emp-a", "status": "approved",
                                          "from_date": "2026-11-04", "to_date": "2026-11-04", "is_half_day": True,
                                          "half_day_period": "AM"}]
        # 08:00–16:00 istirahat 60 → kerja 7 jam → pagi s.d. 11:30, siang mulai 12:30 (dulu: 265 menit terlambat)
        out = run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "12:30")))
        assert out["late_minutes"] == 0 and out["shift_start"] == "12:30"
        assert run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "12:50")))["late_minutes"] == 15

    def test_istirahat_tidak_diatur_separuh_rentang(self):
        assert ident.half_day_points({"start_time": "07:00", "end_time": "15:00"}) == (240, 240)
        assert ident.half_day_points({"start_time": "22:00", "end_time": "06:00", "break_minutes": 60}) == (210, 270)

    def test_cuti_penuh_dan_tugas_luar_nol(self, db):
        db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "emp-a", "status": "approved",
                                          "from_date": "2026-11-04", "to_date": "2026-11-05"}]
        assert run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "09:00")))["late_minutes"] == 0
        db.rahaza_attendance_events.docs = [{"employee_id": "emp-a", "date": "2026-11-06", "tugas_luar": True}]
        out = run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-06", "09:00")))
        assert out["late_minutes"] == 0 and out["late_reason"] == "tugas luar"

    def test_toleransi_per_shift_q4(self, db):
        db.rahaza_shifts.docs[0]["toleransi_menit"] = 15
        assert run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "08:20")))["late_minutes"] == 5
        db.rahaza_shifts.docs[0]["toleransi_menit"] = 0       # 0 = tanpa toleransi (dulu 0 dibaca 5)
        assert run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "08:20")))["late_minutes"] == 20
        del db.rahaza_shifts.docs[0]["toleransi_menit"]
        db.rahaza_shifts.docs[0]["grace_minutes"] = 10         # isian lama tetap terbaca
        assert run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "08:20")))["late_minutes"] == 10

    def test_payroll_abaikan_terlambat_lama_di_hari_cuti_dan_minggu(self, db):
        db.rahaza_payroll_settings.docs = [{"key": "late_penalty", "enabled": True, "mode": "per_minute",
                                            "amount_per_minute": 1_000}]
        ev = [{"id": f"e{d}", "employee_id": "emp-a", "date": d.isoformat(), "status": "hadir", "hours_worked": 8,
               "late_minutes": 0} for d in OCT_WD]
        ev[0]["late_minutes"] = 10                                                     # hadir: dihitung
        ev[1].update(status="cuti", late_minutes=265, leave_request_id="lv-x")        # cuti penuh: diabaikan
        ev.append({"id": "eSun", "employee_id": "emp-a", "date": "2026-10-11", "status": "hadir",
                   "late_minutes": 115, "shift_source": "karyawan"})                   # Minggu: diabaikan
        db.rahaza_attendance_events.docs = ev
        prof = {"employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": 2_700_000}
        s = run(shared._compute_payslip_for_employee(db, prof, *OCT, {"id": "emp-a"}))
        late = [d for d in s["deductions"] if d["type"] == "late"]
        assert s["late_minutes"] == 10 and late[0]["amount"] == 10_000


# ═════════════════════════════════════════════════════════════════════════════
# Permintaan agen SHIFT-AI (9 Nov): toleransi 0 sah, istirahat_mulai, shift_id entri jadwal, libur jadwal
# ═════════════════════════════════════════════════════════════════════════════
def _jadwal(db, entries, published_at="2026-11-01T00:00:00"):
    db.rahaza_schedules.docs.append({"status": "published", "start_date": "2026-11-01", "end_date": "2026-11-30",
                                     "published_at": published_at, "shifts": entries})


class TestKontrakShiftAgenShift:
    def test_1_toleransi_nol_dan_salinan_grace(self, db):
        db.rahaza_shifts.docs[0].update(toleransi_menit=0, grace_minutes=0)       # agen SHIFT menyalin ke keduanya
        out = run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "08:03")))
        assert out["grace_minutes"] == 0 and out["late_minutes"] == 3            # dulu 0 → bawaan 5 → 0 menit

    def test_2_cuti_pagi_memakai_istirahat_mulai(self, db):
        db.rahaza_shifts.docs[0].update(istirahat_mulai="12:00", break_duration_minutes=60)
        db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "emp-a", "status": "approved",
                                          "from_date": "2026-11-04", "to_date": "2026-11-04", "is_half_day": True,
                                          "half_day_period": "AM"}]
        out = run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "13:10")))
        assert out["shift_start"] == "13:00" and out["late_minutes"] == 5            # acuan 12:00 + 60 menit
        assert ident.half_day_points({"start_time": "08:00", "end_time": "16:00", "break_minutes": 60,
                                      "break_start": "12:00"}) == (240, 300)
        db.rahaza_leave_requests.docs[0].update(from_date="2026-11-05", to_date="2026-11-05", half_day_period="PM")
        early = run(ident.compute_early_leave_minutes(db, EMP_A, _utc("2026-11-05", "11:40"), "2026-11-05"))
        assert early["shift_end"] == "12:00" and early["early_leave_minutes"] == 20

    def test_3_entri_jadwal_shift_id_lebih_dulu_dari_jam_salinan(self, db):
        db.rahaza_shifts.docs.append({"id": "sh-pagi", "code": "P", "name": "Pagi", "start_time": "07:00",
                                      "end_time": "15:00", "toleransi_menit": 10, "active": True})
        # jam tersalin di entri sudah usang (08:00) — master shift sekarang 07:00, toleransi 10
        _jadwal(db, [{"employee_id": "emp-a", "date": "2026-11-04", "shift_id": "sh-pagi", "shift_code": "P",
                      "start_time": "08:00", "end_time": "16:00"}])
        out = run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "07:20")))
        assert (out["shift_start"], out["shift_source"], out["late_minutes"]) == ("07:00", "jadwal", 10)
        ids = run(ar.default_shift_ids(db, [{"id": "emp-a", "shift_id": "sh-reg"}], "2026-11-04",
                                       db.rahaza_shifts.docs))
        assert ids == {"emp-a": "sh-pagi"}

    def test_3b_entri_libur_tanpa_shift_terlambat_nol(self, db, monkeypatch):
        _jadwal(db, [{"employee_id": "emp-a", "date": "2026-11-04", "libur": True}])
        assert run(ar.resolve_day_shift(db, EMP_A, "2026-11-04")) is None             # tidak jatuh ke shift bawaan
        out = run(ident.compute_late_minutes(db, EMP_A, _utc("2026-11-04", "10:00")))
        assert out["late_minutes"] == 0 and out["late_reason"] == "libur menurut jadwal shift"
        early = run(ident.compute_early_leave_minutes(db, EMP_A, _utc("2026-11-04", "11:00"), "2026-11-04"))
        assert early["early_leave_minutes"] == 0
        off = set()
        assert run(ar.default_shift_ids(db, [{"id": "emp-a", "shift_id": "sh-reg"}], "2026-11-04",
                                        db.rahaza_shifts.docs, off_out=off)) == {} and off == {"emp-a"}
        as_user(monkeypatch, HR)
        grid = run(att.attendance_grid(FakeRequest(), date="2026-11-04"))
        assert {r["employee_id"]: r["jadwal_libur"] for r in grid["rows"]}["emp-a"] is True

    def test_3c_jadwal_saya_mengikuti_entri_libur(self, db, monkeypatch):
        import routes.rahaza_auto_attendance_config as cfg
        monkeypatch.setattr(cfg, "get_db", lambda: db)
        monkeypatch.setattr(cfg, "require_auth", lambda request: _async(dict(OPS)))
        monkeypatch.setattr(cfg, "today_wib", lambda: date(2026, 11, 4))
        _jadwal(db, [{"employee_id": "emp-a", "date": "2026-11-04", "libur": True}])
        out = run(cfg.get_my_schedule(FakeRequest(), days=2))
        d4, d5 = out["days"]
        assert (d4["kind"], d4["label"], d4["shift"]) == ("libur", "Libur (jadwal shift)", None)
        assert d5["kind"] == "kerja" and d5["shift"]["code"] == "REG"

    def test_4_hitung_ulang_memakai_aturan_jadwal(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        _jadwal(db, [{"employee_id": "emp-a", "date": "2026-11-04", "libur": True}])
        db.rahaza_attendance_events.docs = [{"id": "e1", "employee_id": "emp-a", "date": "2026-11-04",
                                             "status": "hadir", "clock_in": _utc("2026-11-04", "10:00"),
                                             "late_minutes": 115}]
        out = run(att.recompute_timing(FakeRequest({"from": "2026-11-01", "to": "2026-11-09"})))
        ev = db.rahaza_attendance_events.docs[0]
        assert out["changed"] == 1 and ev["late_minutes"] == 0 and ev["late_reason"] == "libur menurut jadwal shift"


# ═════════════════════════════════════════════════════════════════════════════
# Q3 — pulang cepat dicatat (tidak memotong) + M13 hitung ulang terlambat
# ═════════════════════════════════════════════════════════════════════════════
class TestPulangCepatDanHitungUlang:
    def test_pulang_cepat_dan_setengah_hari_siang(self, db):
        out = run(ident.compute_early_leave_minutes(db, EMP_A, _utc("2026-11-04", "15:00"), "2026-11-04"))
        assert out["early_leave_minutes"] == 60 and out["shift_end"] == "16:00"
        db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "emp-a", "status": "approved",
                                          "from_date": "2026-11-05", "to_date": "2026-11-05", "is_half_day": True,
                                          "half_day_period": "PM"}]
        out = run(ident.compute_early_leave_minutes(db, EMP_A, _utc("2026-11-05", "11:30"), "2026-11-05"))
        assert out["early_leave_minutes"] == 0 and out["shift_end"] == "11:30"
        assert run(ident.compute_early_leave_minutes(db, EMP_A, _utc("2026-11-08", "11:00"),
                                                     "2026-11-08"))["early_leave_minutes"] == 0   # Minggu

    def test_absen_pulang_hr_mencatat_dan_slip_tidak_memotong(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_attendance_events.docs = [{"id": "e1", "employee_id": "emp-a", "date": "2026-11-04",
                                             "status": "hadir", "clock_in": _utc("2026-11-04", "08:00")}]
        out = run(att.bulk_attendance(FakeRequest({"date": "2026-11-04", "entries": [
            {"employee_id": "emp-a", "clock_out": _utc("2026-11-04", "14:30").isoformat()}]})))
        assert out["saved"] == 1
        assert db.rahaza_attendance_events.docs[0]["early_leave_minutes"] == 90
        prof = {"employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": 2_700_000}
        s = run(shared._compute_payslip_for_employee(db, prof, "2026-11-01", "2026-11-30", {"id": "emp-a"}))
        assert s["early_leave_minutes"] == 90 and not [d for d in s["deductions"] if d["type"] == "late"]

    def test_rekap_absensi_memuat_terlambat_dan_pulang_cepat(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_attendance_events.docs = [
            {"id": "e1", "employee_id": "emp-a", "date": "2026-11-04", "status": "hadir", "late_minutes": 12,
             "early_leave_minutes": 30},
            {"id": "e2", "employee_id": "emp-a", "date": "2026-11-05", "status": "cuti", "late_minutes": 200}]
        (row,) = run(att.attendance_summary(FakeRequest(), from_="2026-11-01", to="2026-11-30"))
        assert (row["total_late_minutes"], row["days_late"], row["total_early_leave_minutes"]) == (12, 1, 30)

    def test_hitung_ulang_periode_lewati_tanggal_final(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_attendance_events.docs = [
            {"id": "e1", "employee_id": "emp-a", "date": "2026-11-08", "status": "hadir",       # Minggu, data lama
             "clock_in": _utc("2026-11-08", "10:00"), "late_minutes": 115},
            {"id": "e2", "employee_id": "emp-a", "date": "2026-10-20", "status": "hadir",       # terkunci
             "clock_in": _utc("2026-10-20", "10:00"), "late_minutes": 999}]
        db.rahaza_payroll_runs.docs = [{"id": "rf", "run_number": "PR-F", "status": "finalized",
                                        "period_from": "2026-10-01", "period_to": "2026-10-31"}]
        db.rahaza_payslips.docs = [{"id": "sf", "run_id": "rf", "employee_id": "emp-a"}]
        out = run(att.recompute_timing(FakeRequest({"from": "2026-10-15", "to": "2026-11-09"})))
        assert (out["changed"], out["locked"]) == (1, 1)
        by = {e["id"]: e for e in db.rahaza_attendance_events.docs}
        assert by["e1"]["late_minutes"] == 0 and by["e2"]["late_minutes"] == 999
        assert any(a["source"] == "hitung_ulang" for a in db.rahaza_attendance_audit.docs)
        as_user(monkeypatch, OPS)
        assert _status(att.recompute_timing(FakeRequest({"from": "2026-11-01", "to": "2026-11-09"}))) == 403

    def test_persetujuan_cuti_menghitung_ulang_terlambat_yang_sudah_tercatat(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        db.rahaza_attendance_events.docs = [{"id": "e1", "employee_id": "emp-b", "date": "2026-11-04",
                                             "status": "hadir", "clock_in": _utc("2026-11-04", "12:30"),
                                             "late_minutes": 265}]
        db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "emp-b", "leave_type_id": "lt-ct",
                                          "from_date": "2026-11-04", "to_date": "2026-11-04", "is_half_day": True,
                                          "half_day_period": "AM", "status": "pending_approval",
                                          "approval_level_required": 1, "current_approval_level": 1,
                                          "reason": "urusan keluarga"}]
        run(le.approve_leave_request(db, "lv1", dict(HR)))
        ev = db.rahaza_attendance_events.docs[0]
        assert ev["status"] == "cuti" and ev["half_day_period"] == "AM" and ev["late_minutes"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# H3 — penyesuaian pendapatan (THR/bonus) ikut PPh21; M2 bulan gaji; M4 plafon JP
# ═════════════════════════════════════════════════════════════════════════════
def _emp_pajak(**kw):
    e = {"id": "emp-a", "name": "Ani", "employee_code": "E01", "tax_ptkp": "TK/0", "ktp_number": "3273011503850001",
         "bpjs_programs": {"kes": True, "jht": True, "jp": True, "jkk_jkm": True}}
    e.update(kw)
    return e


def _month(y, m):
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()


class TestPajakPenyesuaian:
    def _draft(self, db, base=6_000_000, period=("2026-03-01", "2026-03-31")):
        prof = {"employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": base}
        s = run(shared._compute_payslip_for_employee(db, prof, *period, _emp_pajak()))
        db.rahaza_employees.docs[0].update(_emp_pajak())
        db.rahaza_payroll_runs.docs.append({"id": "r-m", "run_number": "PR-M", "status": "draft",
                                            "period_from": period[0], "period_to": period[1]})
        db.rahaza_payslips.docs.append({**s, "id": "s-m", "run_id": "r-m"})
        return s

    def test_thr_lewat_adj_dipajaki_ter_bulan_itu(self, db, monkeypatch):
        monkeypatch.setattr(slips, "_require_hr", lambda request: _async(dict(HR)))
        before = self._draft(db)
        pph0 = sum(d["amount"] for d in before["deductions"] if d["type"] == "pph21")
        out = run(slips.adjust_payslip("r-m", "s-m", FakeRequest({"earning_adjustment": 6_000_000,
                                                                  "reason": "THR Idulfitri"})))
        s = out["payslip"]
        pph = sum(d["amount"] for d in s["deductions"] if d["type"] == "pph21")
        # bruto kena pajak = 12.000.000 + premi JKK/JKM/Kes 272.400 = 12.272.400 → TER A 4% = 490.896 (audit sim_pajak)
        assert s["tax"]["taxable_gross"] == 12_272_400 and pph == 490_896 and pph0 == 47_043
        assert "PPh21 dihitung ulang" in out["warning"]
        bpjs = [d["amount"] for d in s["deductions"] if d["type"].startswith("bpjs")]
        assert bpjs == [d["amount"] for d in before["deductions"] if d["type"].startswith("bpjs")]   # BPJS tetap
        assert s["net_pay"] == s["gross_pay"] - s["deductions_total"]

    def test_potongan_tambahan_tidak_mengubah_pph21(self, db, monkeypatch):
        monkeypatch.setattr(slips, "_require_hr", lambda request: _async(dict(HR)))
        before = self._draft(db)
        out = run(slips.adjust_payslip("r-m", "s-m", FakeRequest({"deduction": 100_000, "reason": "ganti rugi"})))
        assert [d for d in out["payslip"]["deductions"] if d["type"] == "pph21"] == \
            [d for d in before["deductions"] if d["type"] == "pph21"] and out["warning"] is None

    def test_setahun_desember_memuat_thr(self, db):
        """sim_pajak audit: gaji 6 jt TK/0, THR 6 jt Maret lewat Adj → PPh21 setahun 1.052.250 (dulu 767.250)."""
        prof = {"employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": 6_000_000}
        emp = _emp_pajak()
        db.rahaza_employees.docs[0].update(emp)
        total = 0
        for m in range(1, 13):
            pf, pt = _month(2026, m)
            s = run(shared._compute_payslip_for_employee(db, prof, pf, pt, emp, run_id=f"r{m}"))
            if m == 3:
                s = {**s, "manual_addition": 6_000_000, "gross_before_adjustment": s["gross_pay"],
                     "gross_pay": s["gross_pay"] + 6_000_000}
                s = run(shared.recompute_slip_pph21(db, s, emp, run_id=f"r{m}"))
            db.rahaza_payroll_runs.docs.append({"id": f"r{m}", "status": "finalized"})
            db.rahaza_payslips.docs.append({**s, "id": f"s{m}", "run_id": f"r{m}"})
            total += sum(d["amount"] for d in s["deductions"] if d["type"] == "pph21")
        assert total == 1_052_250

    def test_hitung_ulang_pajak_tanpa_penyesuaian_sama_dengan_mesin(self, db):
        import test_hr_inti_regresi_angka as reg  # noqa: F401 — skenario yang sama dengan uji regresi
        prof = {"employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": 15_200_000}
        for period in (OCT, ("2026-12-01", "2026-12-31")):
            s = run(shared._compute_payslip_for_employee(db, prof, *period, _emp_pajak(tax_ptkp="K/1")))
            again = run(shared.recompute_slip_pph21(db, s, _emp_pajak(tax_ptkp="K/1"), run_id=None))
            assert [d for d in again["deductions"] if d["type"] == "pph21"] == \
                [d for d in s["deductions"] if d["type"] == "pph21"]

    def test_hitung_ulang_run_membawa_adj_ke_pajak(self, db, monkeypatch):
        monkeypatch.setattr(runs, "_require_hr", lambda request: _async(dict(HR)))
        self._draft(db)
        db.rahaza_payroll_profiles.docs = [{"employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": 6_000_000,
                                            "active": True}]
        db.rahaza_payslips.docs[0].update(manual_addition=6_000_000, adjustment_notes="THR")
        run(runs.recalculate_run("r-m", FakeRequest()))
        s = db.rahaza_payslips.docs[0]
        assert s["gross_pay"] == 12_000_000
        assert sum(d["amount"] for d in s["deductions"] if d["type"] == "pph21") == 490_896


class TestBulanGaji:
    def test_kasbon_mulai_november_dipotong_di_run_26_okt_25_nov(self, db):
        db.dewi_kasbon_requests.docs = [{"id": "k1", "employee_id": "emp-a", "status": "disbursed",
                                         "deduction_start_period": "2026-11", "type": "kasbon",
                                         "request_number": "KB-1", "outstanding_balance": 300_000,
                                         "disbursed_at": "2026-11-03"}]
        prof = {"employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": 3_000_000}
        s = run(shared._compute_payslip_for_employee(db, prof, "2026-10-26", "2026-11-25", {"id": "emp-a"}))
        assert [d["amount"] for d in s["deductions"] if d["type"] == "kasbon"] == [300_000]
        assert s["payroll_month"] == "2026-11" and rules.payroll_month("2026-10-26", "2026-11-25") == "2026-11"

    def test_klaim_kasbon_run_lain_per_bulan_gaji(self, db):
        db.rahaza_payroll_runs.docs = [{"id": "r1", "run_number": "PR-1", "status": "draft"}]
        db.rahaza_payslips.docs = [{"id": "s1", "run_id": "r1", "employee_id": "emp-a", "period_from": "2026-10-26",
                                    "period_to": "2026-11-25", "deductions": [{"type": "kasbon", "kasbon_id": "k1"}]}]
        assert run(shared.kasbon_claimed_by_other_runs(db, "emp-a", "2026-11", ["k1"])) == {"k1": "PR-1"}
        assert run(shared.kasbon_claimed_by_other_runs(db, "emp-a", "2026-10", ["k1"])) == {}


class TestPlafonJp:
    def test_jadwal_plafon(self):
        assert tax.jp_ceiling_on("2025-02-28") == 10_042_300
        assert tax.jp_ceiling_on("2025-03-01") == 10_547_400
        assert tax.jp_ceiling_on("2026-10-31") == 11_086_300

    def test_slip_2026_memakai_plafon_baru_dan_isian_hr_dihormati(self, db):
        prof = {"employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": 15_200_000}
        s = run(shared._compute_payslip_for_employee(db, prof, *OCT, _emp_pajak()))
        assert [d["amount"] for d in s["deductions"] if d["type"] == "bpjs_jp"] == [110_863]   # 1% × 11.086.300
        db.rahaza_payroll_settings.docs = [{"key": "bpjs", "ceilings": {"jp": 10_042_300}}]   # bawaan lama tersimpan
        s = run(shared._compute_payslip_for_employee(db, prof, *OCT, _emp_pajak()))
        assert [d["amount"] for d in s["deductions"] if d["type"] == "bpjs_jp"] == [110_863]
        db.rahaza_payroll_settings.docs = [{"key": "bpjs", "ceilings": {"jp": 12_000_000}}]   # isian HR sendiri
        s = run(shared._compute_payslip_for_employee(db, prof, *OCT, _emp_pajak()))
        assert [d["amount"] for d in s["deductions"] if d["type"] == "bpjs_jp"] == [120_000]


# ═════════════════════════════════════════════════════════════════════════════
# Q1 — bonus kehadiran: hari tanpa catatan tidak menghanguskan
# ═════════════════════════════════════════════════════════════════════════════
class TestBonusTanpaCatatan:
    def test_minimal_hadir_menghitung_hari_tanpa_catatan(self):
        cfg = {"min_days_present": 20}
        assert rules.bonus_forfeit_reasons(cfg, {}, days_present=5, days_late=0, late_minutes=0,
                                           presumed_days=21) == []
        assert rules.bonus_forfeit_reasons(cfg, {}, days_present=5, days_late=0, late_minutes=0) == [
            "hadir 5 hari (minimal 20)"]
        assert rules.bonus_forfeit_reasons({}, {"alpa": 1}, days_present=0, days_late=0, late_minutes=0,
                                           presumed_days=10) == ["1 hari alpa"]


# ═════════════════════════════════════════════════════════════════════════════
# Q9 — lembur dari jam nyata, ≤ pengajuan, dibulatkan ke bawah per 30 menit; batas → peringatan
# ═════════════════════════════════════════════════════════════════════════════
class TestLemburJamNyata:
    PROF = {"employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": 3_460_000}   # 20.000/jam (1/173)

    def _ev(self, day, cin="08:00", cout="16:00", **kw):
        return {"id": f"e{day}", "employee_id": "emp-a", "date": day, "status": "hadir",
                "clock_in": _utc(day, cin), "clock_out": _utc(day, cout), "hours_worked": 8, **kw}

    def test_jam_absen_dibulatkan_dan_dibatasi_pengajuan(self, db):
        db.rahaza_attendance_events.docs = [self._ev("2026-10-05", cout="17:50"),   # 1 j 50 m → 1,5 j
                                            self._ev("2026-10-06", cout="20:00")]   # 4 j, pengajuan 2 j → 2 j
        db.rahaza_overtime_requests.docs = [
            {"employee_id": "emp-a", "date": "2026-10-05", "status": "approved", "hours": 3},
            {"employee_id": "emp-a", "date": "2026-10-06", "status": "approved", "hours": 2}]
        s = run(shared._compute_payslip_for_employee(db, self.PROF, *OCT, {"id": "emp-a", "shift_id": "sh-reg"}))
        by = {o["date"]: o for o in s["overtime_entries"]}
        assert by["2026-10-05"]["paid_hours"] == 1.5 and by["2026-10-05"]["actual_source"] == "jam absen"
        assert by["2026-10-06"]["paid_hours"] == 2 and by["2026-10-06"]["requested_hours"] == 2
        assert s["overtime_rule"] == rules.OVERTIME_RULE

    def test_pengajuan_tanpa_absen_tidak_dibayar_dan_diperingatkan(self, db):
        db.rahaza_overtime_requests.docs = [{"employee_id": "emp-a", "date": "2026-10-11", "status": "approved",
                                             "hours": 2}]
        s = run(shared._compute_payslip_for_employee(db, self.PROF, *OCT, {"id": "emp-a", "shift_id": "sh-reg"}))
        assert s["overtime_amount"] == 0 and s["overtime_entries"][0]["basis"] == "pengajuan tanpa absen"
        assert any(w["type"] == "overtime_no_attendance" for w in s["warnings"])

    def test_batas_4_jam_dan_18_jam_peringatan_bukan_tolak(self, db):
        days = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
        db.rahaza_attendance_events.docs = [self._ev(d, overtime_hours=5) for d in days]
        db.rahaza_overtime_requests.docs = [{"employee_id": "emp-a", "date": d, "status": "approved", "hours": 5}
                                            for d in days]
        s = run(shared._compute_payslip_for_employee(db, self.PROF, *OCT, {"id": "emp-a", "shift_id": "sh-reg"}))
        msgs = [w["message"] for w in s["warnings"] if w["type"] == "overtime_limit"]
        assert sum(o["paid_hours"] for o in s["overtime_entries"]) == 25          # tetap dibayar
        assert len([m for m in msgs if "jam/hari" in m]) == 5 and any("jam/minggu" in m for m in msgs)

    def test_pengajuan_lebih_4_jam_diberi_peringatan(self, db, monkeypatch):
        as_user(monkeypatch, OPS)
        out = run(ot.create_overtime_request(db, dict(OPS), {"date": "2026-11-04", "hours": 5, "reason": "stok"}))
        assert out["warnings"] and "4 jam" in out["warnings"][0]

    def test_slip_final_lama_dikoreksi_dengan_aturan_lama(self, db):
        """Slip final sebelum Q9 (tanpa `overtime_rule`) tidak memunculkan selisih palsu di run berikutnya."""
        db.rahaza_overtime_requests.docs = [{"employee_id": "emp-a", "date": "2026-10-11", "status": "approved",
                                             "hours": 2}]
        old = run(shared._compute_payslip_for_employee(db, self.PROF, *OCT, {"id": "emp-a"}))
        old.pop("overtime_rule")
        old["attendance_snapshot"] = {"2026-10-11": {"ded": 0.0, "ot": 4.0}}   # dulu dibayar 2 j × 2
        db.rahaza_payroll_runs.docs = [{"id": "r-okt", "run_number": "PR-OKT", "status": "finalized"}]
        db.rahaza_payslips.docs = [{**old, "run_id": "r-okt"}]
        nov = run(shared._compute_payslip_for_employee(db, self.PROF, "2026-11-01", "2026-11-30", {"id": "emp-a"},
                                                      run_id="r-nov"))
        assert not [e for e in nov["earnings"] if e["type"] == "attendance_correction"]
        assert not [d for d in nov["deductions"] if d["type"] == "absence_correction"]


# ═════════════════════════════════════════════════════════════════════════════
# Q6 + H6 — persetujuan atasan langsung → HR; kabar ke AKUN atasan
# ═════════════════════════════════════════════════════════════════════════════
class TestAtasanLaluHr:
    BODY = {"leave_type_id": "lt-ct", "from_date": "2026-11-11", "to_date": "2026-11-12", "reason": "acara keluarga"}

    def test_pengajuan_ke_atasan_dan_kabar_ke_akun_atasan(self, db, notifs):
        lv = run(leave_mod.create_leave_request(db, dict(OPS), dict(self.BODY)))
        assert lv["approval_level_required"] == 2 and lv["approval_route"]["level_1"] == "atasan"
        assert lv["approval_route"]["manager_employee_id"] == "emp-s"
        # H6/P4: dulu target = "emp-s" (ID KARYAWAN) → tidak pernah sampai. Sekarang akun atasan.
        assert notifs[-1]["target_user_ids"] == ["u-spv"] and notifs[-1]["link_module"] == "portal-cuti"

    def test_tanpa_atasan_langsung_hr(self, db, notifs):
        lv = run(leave_mod.create_leave_request(db, dict(HR), {**self.BODY, "employee_id": "emp-b"}))
        assert lv["approval_level_required"] == 1 and lv["approval_route"]["level_1"] == "hr"
        assert notifs[-1]["target_user_ids"] == ["u-hr2"]                 # HR lain (bukan pengaju, bukan atasan)

    def test_hr_tidak_bisa_melompati_atasan_tapi_atasan_lalu_hr(self, db, notifs, monkeypatch):
        lv = run(leave_mod.create_leave_request(db, dict(OPS), dict(self.BODY)))
        e = _err(le.approve_leave_request(db, lv["id"], dict(HR)))
        assert e.status_code == 403 and "Sari" in e.detail
        # atasan (spv packing tanpa izin SDM) menyetujui lewat Portal Saya
        as_user(monkeypatch, SPV)
        team = run(portal_hr.team_approvals(FakeRequest()))
        assert team["is_manager"] and [i["id"] for i in team["items"]] == [lv["id"]]
        run(portal_hr.team_decide("leave", lv["id"], "approve", FakeRequest({})))
        assert db.rahaza_leave_requests.docs[-1]["status"] == "pending_hr_approval"
        assert _status(portal_hr.team_decide("leave", lv["id"], "approve", FakeRequest({}))) == 403  # tahap HR
        out = run(le.approve_leave_request(db, lv["id"], dict(HR)))
        assert out["final"] and out["leave"]["status"] == "approved"

    def test_bukan_atasan_ditolak_di_persetujuan_tim(self, db, notifs, monkeypatch):
        lv = run(leave_mod.create_leave_request(db, dict(OPS), dict(self.BODY)))
        as_user(monkeypatch, {"id": "u-budi", "role": "tim_packing", "name": "Budi"})
        assert _status(portal_hr.team_decide("leave", lv["id"], "approve", FakeRequest({}))) == 403
        assert run(portal_hr.team_approvals(FakeRequest()))["items"] == []

    def test_endpoint_setuju_cuti_tidak_lagi_khusus_peran_hr_tapi_dicek_per_tahap(self, db, notifs, monkeypatch):
        lv = run(leave_mod.create_leave_request(db, dict(OPS), dict(self.BODY)))
        as_user(monkeypatch, SPV)
        run(leave_mod.approve_leave(lv["id"], FakeRequest({})))
        assert db.rahaza_leave_requests.docs[-1]["current_approval_level"] == 2
        as_user(monkeypatch, {"id": "u-x", "role": "tim_packing"})
        assert _status(leave_mod.approve_leave(lv["id"], FakeRequest({}))) == 403

    def test_lembur_dua_tingkat(self, db, notifs, monkeypatch):
        out = run(ot.create_overtime_request(db, dict(OPS), {"date": "2026-11-04", "hours": 2, "reason": "stok"}))
        o = out["overtime"]
        assert o["approval_level_required"] == 2 and notifs[-1]["target_user_ids"] == ["u-spv"]
        assert _err(ot.approve_overtime_request(db, o["id"], dict(HR))).status_code == 403
        as_user(monkeypatch, SPV)
        run(portal_hr.team_decide("overtime", o["id"], "approve", FakeRequest({})))
        doc = db.rahaza_overtime_requests.docs[-1]
        assert doc["status"] == "pending" and doc["current_approval_level"] == 2
        assert run(ot.approve_overtime_request(db, o["id"], dict(HR)))["status"] == "approved"


# ═════════════════════════════════════════════════════════════════════════════
# Q7 — kuota cuti mengikuti UU 13/2003
# ═════════════════════════════════════════════════════════════════════════════
class TestKuotaCuti:
    def _lv(self, db, lt, f, t=None, lid="lv1", emp="emp-b", **kw):
        doc = {"id": lid, "employee_id": emp, "leave_type_id": lt, "from_date": f, "to_date": t or f,
               "status": "pending_approval", "approval_level_required": 1, "current_approval_level": 1,
               "reason": "x", **kw}
        db.rahaza_leave_requests.docs.append(doc)
        return doc

    def test_aturan_tertebak_dari_jenis_bawaan(self):
        assert ltypes.quota_rule_of(LT_CUTI) == "tahunan"
        assert ltypes.quota_rule_of(LT_HAID) == "per_bulan"
        assert ltypes.quota_rule_of(LT_SAKIT) == "sakit_bersurat"
        assert ltypes.quota_rule_of(LT_NIKAH) == "per_kejadian"
        assert ltypes.quota_rule_of({"code": "PERSONAL", "name": "Izin Pribadi", "request_type": "izin"}) == "per_tahun"

    def test_formulir_jenis_cuti_menyimpan_aturan_kuota(self):
        d = ltypes.build_leave_type_doc({"code": "IZ_X", "name": "Izin khusus X", "request_type": "izin",
                                         "quota_rule": "per_kejadian", "quota_default": 2})
        assert d["quota_rule"] == "per_kejadian" and d["max_carry_days"] == 0 and d["min_service_months"] == 12
        assert ltypes.build_leave_type_doc({"code": "ANNUAL", "name": "Cuti Tahunan"})["quota_rule"] == "tahunan"
        with pytest.raises(HTTPException):
            ltypes.build_leave_type_doc({"code": "X", "name": "X", "quota_rule": "bebas"})
        assert ltypes.public_leave_type(LT_HAID)["quota_rule_label"] == "per bulan"

    def test_cuti_tahunan_baru_berhak_setelah_12_bulan_tanpa_prorata(self, db):
        db.rahaza_employees.docs[2]["join_date"] = "2026-03-15"
        self._lv(db, "lt-ct", "2026-11-11")
        e = _err(le.approve_leave_request(db, "lv1", dict(HR)))
        assert e.status_code == 400 and "15/03/2027" in e.detail
        run(le.approve_leave_request(db, "lv1", dict(HR), pay_decision="unpaid"))   # tetap bisa tidak dibayar
        snap = run(balances.balance_snapshot(db, "emp-b", "lt-ct", 2026, lt=LT_CUTI))
        assert snap["allocated"] == 0
        assert run(balances.balance_snapshot(db, "emp-b", "lt-ct", 2027, lt=LT_CUTI))["allocated"] == 12   # penuh

    def test_haid_paling_banyak_2_hari_per_bulan(self, db):
        self._lv(db, "lt-hd", "2026-11-03", "2026-11-04")
        run(le.approve_leave_request(db, "lv1", dict(HR)))
        self._lv(db, "lt-hd", "2026-11-20", lid="lv2")
        assert "per bulan" in _err(le.approve_leave_request(db, "lv2", dict(HR))).detail
        self._lv(db, "lt-hd", "2026-12-01", "2026-12-02", lid="lv3")
        assert run(le.approve_leave_request(db, "lv3", dict(HR)))["final"]               # bulan baru boleh lagi
        assert db.rahaza_leave_balances.docs == []                                        # bukan jatah tahunan

    def test_izin_khusus_per_kejadian(self, db):
        self._lv(db, "lt-nk", "2026-11-02", "2026-11-05", attachment_url="/undangan.jpg")  # 4 hari kerja > 3
        assert "per kejadian" in _err(le.approve_leave_request(db, "lv1", dict(HR))).detail
        db.rahaza_leave_requests.docs[0]["to_date"] = "2026-11-04"                         # 3 hari: boleh
        assert run(le.approve_leave_request(db, "lv1", dict(HR)))["final"]
        assert db.rahaza_leave_balances.docs == []                                         # bukan jatah tahunan

    def test_sakit_bersurat_tanpa_kuota_tanpa_surat_pakai_jatah(self, db):
        db.rahaza_leave_balances.docs = [{"id": "b1", "employee_id": "emp-b", "leave_type_id": "lt-sk",
                                          "year": 2026, "allocated": 14, "used": 14}]
        self._lv(db, "lt-sk", "2026-11-02", "2026-11-06", attachment_url="/surat.pdf")
        assert run(le.approve_leave_request(db, "lv1", dict(HR)))["final"]                # saldo habis tetap dibayar
        assert db.rahaza_leave_balances.docs[0]["used"] == 14
        self._lv(db, "lt-sk", "2026-11-09", lid="lv2")
        assert "Sisa cuti tidak cukup" in _err(le.approve_leave_request(db, "lv2", dict(HR))).detail

    def test_alokasi_ulang_tidak_menghapus_pemakaian(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        monkeypatch.setattr(balances, "_require_admin", lambda request: _async(dict(HR)))
        db.rahaza_leave_types.docs = [dict(LT_CUTI)]
        db.rahaza_employees.docs = [db.rahaza_employees.docs[2]]
        db.rahaza_leave_balances.docs = [{"id": "b1", "employee_id": "emp-b", "leave_type_id": "lt-ct", "year": 2026,
                                          "allocated": 12, "used": 3}]
        db.rahaza_leave_requests.docs = [{"id": "lv9", "employee_id": "emp-b", "leave_type_id": "lt-ct",
                                          "status": "approved", "balance_deducted_by_year": {"2026": 3}}]
        run(balances.allocate_year(FakeRequest({"year": 2026, "force_reset": True})))
        assert db.rahaza_leave_balances.docs[0]["used"] == 3                               # dulu 0

    def test_carry_over_bawaan_nol_dan_hanya_cuti_tahunan(self, db, monkeypatch):
        import utils.scheduler as sch
        monkeypatch.setattr(sch, "get_db", lambda: db)
        monkeypatch.setattr(sch, "wib_year", lambda: 2027)
        db.rahaza_leave_types.docs = [dict(LT_CUTI), dict(LT_SAKIT, max_carry_days=5)]
        db.rahaza_leave_balances.docs = [
            {"id": "b1", "employee_id": "emp-b", "leave_type_id": "lt-ct", "year": 2026, "allocated": 12, "used": 2},
            {"id": "b2", "employee_id": "emp-b", "leave_type_id": "lt-sk", "year": 2026, "allocated": 14, "used": 0}]
        run(sch.job_leave_carry_forward())
        assert [b for b in db.rahaza_leave_balances.docs if b["year"] == 2027] == []      # dulu "or 5" → 5 hari
        db.rahaza_leave_types.docs[0]["max_carry_days"] = 6
        run(sch.job_leave_carry_forward())
        (b,) = [b for b in db.rahaza_leave_balances.docs if b["year"] == 2027]
        assert b["leave_type_id"] == "lt-ct" and b["carry_days"] == 6


# ═════════════════════════════════════════════════════════════════════════════
# Q11 — dinas disetujui → hadir (tugas luar) tanpa geofence
# ═════════════════════════════════════════════════════════════════════════════
class TestTugasLuar:
    TRIP = {"id": "tr1", "trip_number": "TRV-1", "employee_id": "u-ani", "destination": "Bandung",
            "start_date": "2026-11-06", "end_date": "2026-11-09", "status": "submitted"}

    def test_hari_kerja_dinas_tercatat_hadir_dan_dikembalikan(self, db):
        db.employee_travel_requests.docs = [dict(self.TRIP)]
        db.rahaza_attendance_events.docs = [
            {"id": "e7", "employee_id": "emp-a", "date": "2026-11-07", "status": "alpa"},
            {"id": "e9", "employee_id": "emp-a", "date": "2026-11-09", "status": "cuti", "leave_request_id": "lv"}]
        out = run(tl.write_duty_days(db, dict(self.TRIP), dict(HR)))
        assert (out["created"], out["updated"], len(out["skipped"])) == (1, 1, 1)        # 6 baru, 7 alpa→hadir, 9 cuti
        by = {e["date"]: e for e in db.rahaza_attendance_events.docs}
        assert by["2026-11-06"]["status"] == "hadir" and by["2026-11-06"]["tugas_luar"]
        assert by["2026-11-07"]["status"] == "hadir" and "2026-11-08" not in by           # Minggu dilewati
        run(tl.restore_duty_days(db, dict(self.TRIP), dict(HR)))
        by = {e["date"]: e for e in db.rahaza_attendance_events.docs}
        assert "2026-11-06" not in by and by["2026-11-07"]["status"] == "alpa" and not by["2026-11-07"]["tugas_luar"]

    def test_absen_di_tempat_dinas_tanpa_geofence(self, db):
        db.rahaza_office_locations.docs = [{"is_primary": True, "lat": -7.0, "lng": 110.0, "geofence_radius_m": 30,
                                            "require_geofence": True, "require_selfie": False}]
        with pytest.raises(HTTPException):
            run(policy.enforce_attendance_policy(db, photo_b64="x", lat=-6.9, lng=107.6, action="masuk",
                                                 fix={"gps_at": 1000, "sent_at": 2000, "accuracy": 10}))
        out = run(policy.enforce_attendance_policy(db, photo_b64="x", lat=-6.9, lng=107.6, action="masuk",
                                                   fix={"gps_at": 1000, "sent_at": 2000, "accuracy": 10},
                                                   duty_day=True))
        assert out["geo"]["status"] == "tugas_luar"

    def test_persetujuan_dinas_menulis_absensi(self, db, monkeypatch):
        db.employee_travel_requests.docs = [dict(self.TRIP)]

        async def no_notif(*a, **k):
            return None
        monkeypatch.setattr(travel, "_notify_travel_decision", no_notif)
        monkeypatch.setattr(travel, "is_travel_approver", lambda u: True)
        out = run(travel.approve_travel_request("tr1", travel.ApprovePayload(), user=dict(HR)))
        assert out["attendance"]["created"] == 3                                          # 6, 7, 9 Nov


# ═════════════════════════════════════════════════════════════════════════════
# Q2 — status izin/sakit/cuti di grid tanpa pengajuan: peringatan & arahan
# ═════════════════════════════════════════════════════════════════════════════
class TestGridTanpaPengajuan:
    def test_simpan_grid_memberi_peringatan_dan_baris_ditandai(self, db, monkeypatch):
        as_user(monkeypatch, HR)
        out = run(att.bulk_attendance(FakeRequest({"date": "2026-11-04", "entries": [
            {"employee_id": "emp-a", "status": "sakit"}, {"employee_id": "emp-b", "status": "hadir",
                                                         "shift_id": "sh-reg", "hours_worked": 8}]})))
        assert [w["employee_id"] for w in out["warnings"]] == ["emp-a"] and "dipotong" in out["warnings"][0]["message"]
        grid = run(att.attendance_grid(FakeRequest(), date="2026-11-04"))
        rows = {r["employee_id"]: r for r in grid["rows"]}
        assert rows["emp-a"]["needs_leave_request"] and not rows["emp-b"]["needs_leave_request"]


# ═════════════════════════════════════════════════════════════════════════════
# Pola Portal Saya
# ═════════════════════════════════════════════════════════════════════════════
class TestPolaPortalSaya:
    def test_dasbor_menghitung_pengajuan_menunggu(self, db, monkeypatch):
        as_user(monkeypatch, OPS)
        db.rahaza_leave_requests.docs = [{"id": "l1", "employee_id": "emp-a", "status": "pending_approval"},
                                         {"id": "l2", "employee_id": "emp-a", "status": "pending_hr_approval"}]

        async def linked(_db, uid):
            return {"id": uid}, db.rahaza_employees.docs[0]
        monkeypatch.setattr(portal_hr, "_get_linked_employee", linked)
        assert run(portal_hr.get_dashboard(FakeRequest()))["pending_leave"] == 2          # dulu selalu 0

    def test_tarik_pengajuan_dari_portal_tidak_menghapus(self, db, monkeypatch):
        as_user(monkeypatch, OPS)
        db.rahaza_leave_requests.docs = [{"id": "l1", "employee_id": "emp-a", "status": "pending_approval"}]

        async def linked(_db, uid):
            return {"id": uid}, db.rahaza_employees.docs[0]
        monkeypatch.setattr(portal_hr, "_get_linked_employee", linked)
        assert run(portal_hr.cancel_leave("l1", FakeRequest()))["ok"]
        assert db.rahaza_leave_requests.docs[0]["status"] == "cancelled"                  # dulu 400 / dihapus

    def test_label_bulan_slip_portal_saya_bulan_akhir(self):
        import inspect
        src = inspect.getsource(portal_hr.get_dashboard)
        assert 'slip.get("period_to")' in src
