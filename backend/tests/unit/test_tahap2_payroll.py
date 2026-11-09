"""Uji HERMETIK Tahap 2 — paket payroll (2026-11-06). Tanpa server/Mongo (FakeDB). Angka dihitung tangan.

Kalender Oktober 2026: 1 Okt = Kamis; Minggu = 4, 11, 18, 25 → 27 hari kerja (6 hari/minggu), 22 (5 hari).
Satu kelas per butir:
   1 kalender kerja · 2 potongan tidak masuk · 3 bonus kehadiran · 4 prorata masuk/keluar · 5 PPh21 TER
   6 lembur · 7 kenaikan gaji berversi · 8 satu sumber gaji · 9 pemisahan tugas · 10 BPJS/PPh21 semua skema
  11 dasbor (di test_p6) · 12 gaji bersih minus · 13 hitung ulang · 14 kunci absensi + koreksi
  15 daftar tunjangan · 16 migrasi
"""
import asyncio
import importlib.util
import os
import re
import sys
import types
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

try:  # pragma: no cover - CI tanpa openpyxl
    import openpyxl  # noqa: F401
except ImportError:  # pragma: no cover
    _op, _st, _ut = (types.ModuleType(n) for n in ("openpyxl", "openpyxl.styles", "openpyxl.utils"))
    for _n in ("Font", "PatternFill", "Alignment", "Border", "Side"):
        setattr(_st, _n, object)
    _st.numbers = types.SimpleNamespace()
    _ut.get_column_letter = lambda i: "A"
    _op.styles, _op.utils, _op.Workbook = _st, _ut, object
    sys.modules.update({"openpyxl": _op, "openpyxl.styles": _st, "openpyxl.utils": _ut})

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402

import auth  # noqa: E402
import routes.hr_approval_inbox as inbox  # noqa: E402
import routes.rahaza_master as master  # noqa: E402
import routes.rahaza_payroll_allowances as allowances  # noqa: E402
import routes.rahaza_payroll_profiles as profiles  # noqa: E402
import routes.rahaza_payroll_rules as rules  # noqa: E402
import routes.rahaza_payroll_runs as runs  # noqa: E402
import routes.rahaza_payroll_settings as pset  # noqa: E402
import routes.rahaza_payroll_shared as shared  # noqa: E402
import routes.rahaza_payroll_tax as tax  # noqa: E402
import routes.rahaza_salary_adjustments as sal_adj  # noqa: E402

run = asyncio.run

HR = {"id": "u-hr", "role": "hr", "name": "Brenda HR"}
HR2 = {"id": "u-hr2", "role": "manager", "name": "Manajer"}
ADMIN = {"id": "u-adm", "role": "admin", "name": "Admin"}
FIN = {"id": "u-fin", "role": "staff_keuangan", "name": "Fatimah"}
OPERATOR = {"id": "u-op", "role": "operator", "name": "Operator"}

OCT = ("2026-10-01", "2026-10-31")
OCT_WD = [date(2026, 10, d) for d in range(1, 32) if date(2026, 10, d).weekday() != 6]
BASE = 2_700_000   # 2.700.000 / 27 = 100.000 per hari kerja


def _prof(**kw):
    p = {"id": "p-a", "employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": BASE, "overtime_rate": 0,
         "active": True}
    p.update(kw)
    return p


def _emp(**kw):
    e = {"id": "emp-a", "name": "Ani", "employee_code": "E01"}
    e.update(kw)
    return e


def _ev(d, status="hadir", **kw):
    iso = d if isinstance(d, str) else d.isoformat()
    base = {"id": f"ev-{iso}", "employee_id": "emp-a", "date": iso, "status": status, "hours_worked": 8,
            "net_hours_worked": 8, "late_minutes": 0, "overtime_hours": 0}
    base.update(kw)
    return base


def _full_month(db, skip=()):
    db.rahaza_attendance_events.docs = [_ev(d) for d in OCT_WD if d.day not in skip]


def _slip(db, prof=None, emp=None, period=OCT, **kw):
    return run(shared._compute_payslip_for_employee(db, prof or _prof(), period[0], period[1], emp or _emp(), **kw))


def _ded(slip, typ):
    return [d for d in slip["deductions"] if d.get("type") == typ]


def _err(coro):
    with pytest.raises(HTTPException) as ei:
        run(coro)
    return ei.value


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def env(monkeypatch, db):
    """Gerbang & jurnal palsu untuk endpoint run/pengaturan."""
    actor = {"user": dict(HR)}

    async def gate(request):
        return dict(actor["user"])

    async def noop(*a, **k):
        return None

    async def ok_post(dbx, runx, user):
        return {"ok": True, "je_id": "je-1", "je_number": "JE-0001"}

    for mod in (runs, pset, profiles, sal_adj, allowances):
        monkeypatch.setattr(mod, "get_db", lambda: db)
        monkeypatch.setattr(mod, "log_activity", noop)
    for mod in (runs, pset, profiles, allowances, sal_adj):
        monkeypatch.setattr(mod, "_require_hr", gate)
    monkeypatch.setattr(runs, "post_payroll_run", ok_post)
    monkeypatch.setattr(runs, "require_auth", gate)
    monkeypatch.setattr(auth, "require_auth", gate)
    monkeypatch.setattr(inbox, "get_db", lambda: db)
    monkeypatch.setattr(inbox, "log_activity", noop)
    return types.SimpleNamespace(db=db, actor=actor)


# ═══ 1. Kalender kerja ═════════════════════════════════════════════════════════
class TestKalenderKerja:
    def test_bawaan_6_hari_dan_libur_kalender_produksi(self, db):
        _full_month(db, skip=(5,))
        db.rahaza_attendance_events.docs.append(_ev("2026-10-05", "alpa"))
        s = _slip(db)
        assert s["work_days"]["period"] == 27 and s["work_days"]["per_week"] == 6
        assert _ded(s, "absence")[0]["amount"] == 100_000
        db.rahaza_production_calendar.docs = [{"date": "2026-10-20", "type": "holiday"}]
        s = _slip(db)
        assert s["work_days"]["period"] == 26 and _ded(s, "absence")[0]["amount"] == round(BASE / 26)

    def test_lima_hari_dari_pengaturan(self, db):
        db.rahaza_payroll_settings.docs = [{"key": "work_calendar", "work_days_per_week": 5}]
        db.rahaza_attendance_events.docs = [_ev("2026-10-05", "alpa"), _ev("2026-10-10", "alpa")]  # Sabtu = libur
        s = _slip(db)
        assert s["work_days"]["period"] == 22
        assert _ded(s, "absence")[0]["days"] == 1 and _ded(s, "absence")[0]["amount"] == round(BASE / 22)

    def test_pengaturan_layar_dan_api(self, env):
        env.db.rahaza_payroll_settings.docs.append({"key": "work_calendar"})   # FakeDB tanpa upsert
        out = run(pset.set_work_calendar(FakeRequest({"work_days_per_week": 5})))
        assert out["settings"]["work_days_per_week"] == 5
        assert _err(pset.set_work_calendar(FakeRequest({"work_days_per_week": 9}))).status_code == 400
        allset = run(pset.list_settings(FakeRequest()))
        assert allset["work_calendar"]["work_days_per_week"] == 5 and "pph21" in allset

    def test_lwop_helper_pakai_core_workdays(self):
        lv = [{"from_date": "2026-11-07", "to_date": "2026-11-07"}]     # Sabtu
        assert shared.lwop_days_in_period(lv, date(2026, 11, 1), date(2026, 11, 30), set()) == 1
        assert shared.lwop_days_in_period(lv, date(2026, 11, 1), date(2026, 11, 30), set(),
                                          off_weekdays=frozenset({5, 6})) == 0

    def test_tidak_ada_aturan_hari_kerja_kedua_di_payroll(self):
        for name in ("rahaza_payroll_shared.py", "rahaza_payroll_runs.py", "rahaza_payroll_rules.py",
                     "rahaza_payroll_payslips.py", "rahaza_payroll_tax.py"):
            src = open(os.path.join(BACKEND, "routes", name), encoding="utf-8").read()
            assert "weekday() < 5" not in src and "working_days = 22" not in src and "or 22" not in src, name


# ═══ 2. Potongan tidak masuk ═══════════════════════════════════════════════════
class TestPotonganTidakMasuk:
    def _seed(self, db):
        _full_month(db, skip=(5, 6, 7, 8, 9, 12, 13, 14))
        db.rahaza_leave_types.docs = [{"id": "lt-izin", "request_type": "izin", "unpaid": False},
                                      {"id": "lt-lwop", "request_type": "cuti", "unpaid": True}]
        db.rahaza_leave_requests.docs = [
            {"id": "lv-paid", "employee_id": "emp-a", "status": "approved", "leave_type_id": "lt-izin",
             "leave_kind": "izin", "pay_decision": "paid", "from_date": "2026-10-06", "to_date": "2026-10-06",
             "attachment_url": "/f/surat.jpg"},
            {"id": "lv-unpaid", "employee_id": "emp-a", "status": "approved", "leave_type_id": "lt-izin",
             "leave_kind": "izin", "pay_decision": "unpaid", "from_date": "2026-10-07", "to_date": "2026-10-07"}]
        db.rahaza_attendance_events.docs += [
            _ev("2026-10-05", "alpa"),
            _ev("2026-10-06", "izin", leave_request_id="lv-paid", paid_leave=True),
            _ev("2026-10-07", "izin", leave_request_id="lv-unpaid", paid_leave=False),
            _ev("2026-10-08", "sakit"),                                   # tanpa pengajuan disetujui
            _ev("2026-10-09", "alfa", half_day=True),                     # status lama, setengah hari
            _ev("2026-10-11", "alpa"),                                    # Minggu — bukan hari kerja
        ]

    def test_aturan_satu_baris(self, db):
        self._seed(db)
        s = _slip(db)
        row = _ded(s, "absence")[0]
        # alpa 1 + izin tak dibayar 1 + sakit tanpa pengajuan 1 + alfa setengah hari 0,5 = 3,5 hari × 100.000
        assert row["days"] == 3.5 and row["amount"] == 350_000 and row["divisor"] == 27
        assert row["alpa_days"] == 1.5 and row["unpaid_leave_days"] == 2
        assert "2026-10-06" not in row["dates"] and "2026-10-11" not in row["dates"]
        assert _ded(s, "lwop") == []
        assert s["earnings"][0]["amount"] == BASE                     # gaji pokok penuh, potongan terpisah
        assert s["net_pay"] == BASE - 350_000

    def test_hari_tanpa_catatan_tidak_dipotong_tapi_diperingatkan(self, db):
        self._seed(db)
        s = _slip(db)
        assert s["attendance_summary"]["tanpa_catatan"] == 3              # 12, 13, 14 Okt
        w = [x for x in s["warnings"] if x["type"] == "attendance_missing"]
        assert w and w[0]["message"].startswith("3 hari kerja tanpa catatan absen")

    def test_cuti_lama_tanpa_catatan_harian_tetap_satu_kali(self, db):
        # cuti tanpa gaji disetujui (data lama: tanpa catatan absen harian) → tetap dipotong, tidak dobel
        db.rahaza_leave_types.docs = [{"id": "lt-lwop", "request_type": "cuti", "unpaid": True}]
        db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "emp-a", "status": "approved",
                                          "leave_type_id": "lt-lwop", "from_date": "2026-10-28", "to_date": "2026-10-31"}]
        s = _slip(db)
        assert _ded(s, "absence")[0]["days"] == 4
        db.rahaza_attendance_events.docs = [_ev(f"2026-10-{d}", "cuti", leave_request_id="lv1") for d in (28, 29, 30, 31)]
        assert _ded(_slip(db), "absence")[0]["days"] == 4

    def test_selfie_ditolak_alpa_menunggu_hadir(self, db):
        _full_month(db, skip=(5, 6))
        db.rahaza_attendance_events.docs += [_ev("2026-10-05", "alfa", approval_status="rejected"),
                                             _ev("2026-10-06", "hadir", approval_status="pending")]
        assert _ded(_slip(db), "absence")[0]["days"] == 1


# ═══ 3. Bonus kehadiran ════════════════════════════════════════════════════════
class TestBonusKehadiran:
    def _seed(self, db, **cfg):
        db.da_payroll_allowances.docs = [
            {"allowance_id": "al-bonus", "name": "Bonus Kehadiran", "calc_type": "fixed", "amount": 200_000,
             "applicable_to": "all", "is_active": True},
            {"allowance_id": "al-trans", "name": "Tunjangan Transport", "calc_type": "fixed", "amount": 100_000,
             "applicable_to": "all", "is_active": True}]
        if cfg:
            db.rahaza_payroll_settings.docs = [{"key": "attendance_bonus", **cfg}]

    def _bonus(self, s):
        return next(a for a in s["allowances"] if a["allowance_id"] == "al-bonus")

    def test_tanpa_catatan_tidak_hangus_tapi_semua_alpa_hangus(self, db):
        # 2026-11-09 (Q1, keputusan owner): hari kerja TANPA catatan = dianggap hadir (gaji tidak dipotong DAN bonus
        # tidak hangus) — dulu 0 catatan menghanguskan bonus "tidak ada hari hadir". Tetap diperingatkan.
        self._seed(db)
        s = _slip(db)
        assert self._bonus(s)["amount"] == 200_000 and not self._bonus(s).get("forfeited")
        assert any(w["type"] == "attendance_missing" and "bonus" in w["message"] for w in s["warnings"])
        db.rahaza_attendance_events.docs = [_ev(d, "alpa") for d in OCT_WD]
        b = self._bonus(_slip(db))
        assert b["amount"] == 0 and "tidak ada hari hadir" in b["forfeit_reasons"]

    def test_hadir_penuh_dibayar_alpa_hangus(self, db):
        self._seed(db)
        _full_month(db)
        assert self._bonus(_slip(db))["amount"] == 200_000
        _full_month(db, skip=(5,))
        db.rahaza_attendance_events.docs.append(_ev("2026-10-05", "alpa"))
        s = _slip(db)
        assert self._bonus(s)["amount"] == 0 and "1 hari alpa" in self._bonus(s)["forfeit_reasons"]
        assert next(a for a in s["allowances"] if a["allowance_id"] == "al-trans")["amount"] == 100_000

    def test_per_jenis_bisa_diatur(self, db):
        self._seed(db, max_alpa_days=1, forfeit_if_late=True, max_late_days_allowed=2, late_minutes_limit=30,
                   forfeit_if_izin_no_note=True)
        _full_month(db, skip=(5, 6))
        db.rahaza_attendance_events.docs += [_ev("2026-10-05", "alpa"), _ev("2026-10-06", "izin")]
        db.rahaza_attendance_events.docs[0]["late_minutes"] = 20
        s = _slip(db)
        assert self._bonus(s)["forfeit_reasons"] == ["1 hari izin/sakit tanpa surat"]      # alpa ≤ 1 dibolehkan
        db.rahaza_attendance_events.docs[1]["late_minutes"] = 15                             # total 35 menit
        assert "terlambat 35 menit (batas 30)" in self._bonus(_slip(db))["forfeit_reasons"]

    def test_pengaturan_mati_dan_pilihan_tunjangan(self, db):
        self._seed(db, enabled=False)
        assert self._bonus(_slip(db))["amount"] == 200_000
        self._seed(db, allowance_ids=["al-trans"])
        db.rahaza_attendance_events.docs = [_ev("2026-10-05", "alpa")]   # 1 alpa tercatat → tunjangan pilihan hangus
        s = _slip(db)
        assert self._bonus(s)["amount"] == 200_000
        assert next(a for a in s["allowances"] if a["allowance_id"] == "al-trans")["amount"] == 0


# ═══ 4. Prorata masuk / keluar ═════════════════════════════════════════════════
class TestProrata:
    def test_masuk_tengah_bulan(self, db):
        # 15–31 Okt = 15 hari kerja → 2.700.000 × 15/27 = 1.500.000
        s = _slip(db, emp=_emp(join_date="2026-10-15"))
        assert s["earnings"][0]["amount"] == 1_500_000 and s["work_days"]["employed"] == 15
        assert "15/27 hari kerja" in s["earnings"][0]["label"]

    def test_keluar_tengah_bulan_ikut_run_dan_prorata(self, env, monkeypatch):
        env.db.rahaza_payroll_profiles.docs = [_prof(), _prof(id="p-b", employee_id="emp-b"),
                                               _prof(id="p-c", employee_id="emp-c"), _prof(id="p-d", employee_id="emp-d")]
        env.db.rahaza_employees.docs = [
            _emp(active=False, resign_date="2026-10-10"),                       # keluar 10 Okt → 9 hari
            {"id": "emp-b", "name": "Budi", "active": False},                   # nonaktif tanpa tanggal keluar
            {"id": "emp-c", "name": "Cici", "join_date": "2026-11-02"},         # belum mulai
            {"id": "emp-d", "name": "Dodi", "resign_date": "2026-09-30"}]       # keluar sebelum periode

        async def runno(dbx):
            return "PR-T2"
        monkeypatch.setattr(runs, "_generate_run_number", runno)
        out = run(runs.create_run(FakeRequest({"period_from": OCT[0], "period_to": OCT[1]})))
        assert out["total_employees"] == 1 and out["total_gross"] == 900_000
        reasons = {x["employee_id"]: x["reason"] for x in out["excluded_employees"]}
        assert reasons == {"emp-b": "karyawan nonaktif", "emp-c": "belum mulai bekerja di periode ini",
                           "emp-d": "sudah keluar sebelum periode ini"}

    def test_tunjangan_tetap_ikut_prorata(self, db):
        db.da_payroll_allowances.docs = [{"allowance_id": "al-j", "name": "Tunjangan Jabatan", "calc_type": "fixed",
                                          "amount": 270_000, "applicable_to": "all", "is_active": True}]
        s = _slip(db, emp=_emp(join_date="2026-10-15"))
        assert s["allowances"][0]["amount"] == 150_000


# ═══ 5. PPh21 ══════════════════════════════════════════════════════════════════
class TestPph21:
    def test_tabel_ter_dan_kategori(self):
        cfg = tax.default_pph21_config()
        assert tax.ter_category("TK/0", cfg) == "A" and tax.ter_category("K/1", cfg) == "B"
        assert tax.ter_category("K/3", cfg) == "C"
        assert tax.ter_rate(5_400_000, "A", cfg) == 0 and tax.ter_rate(5_400_001, "A", cfg) == 0.0025
        assert tax.ter_rate(10_000_000, "A", cfg) == 0.02 and tax.ter_rate(10_000_000, "B", cfg) == 0.015
        assert tax.ter_rate(10_000_000, "C", cfg) == 0.015 and tax.ter_rate(2_000_000_000, "A", cfg) == 0.34

    def test_npwp_16_digit_dan_nik(self):
        assert tax.valid_tax_id("3273011503850001") and tax.valid_tax_id("12.345.678.9-012.345")
        assert not tax.valid_tax_id("12345")
        assert tax.has_tax_id({"ktp_number": "3273011503850001"}) and not tax.has_tax_id({})

    def test_ter_bulanan_tanpa_npwp(self, db):
        s = _slip(db, prof=_prof(base_rate=10_000_000))
        p = _ded(s, "pph21")[0]
        assert p["amount"] == 200_000 and s["tax"]["pph21"]["category"] == "A"       # 2% × 10.000.000
        db.rahaza_payroll_settings.docs = [{"key": "pph21", "no_npwp_surcharge_enabled": True}]
        assert _ded(_slip(db, prof=_prof(base_rate=10_000_000)), "pph21")[0]["amount"] == 240_000
        assert _ded(_slip(db, prof=_prof(base_rate=10_000_000), emp=_emp(npwp_number="3273011503850001")),
                    "pph21")[0]["amount"] == 200_000

    def test_bpjs_kes_bukan_pengurang_premi_perusahaan_bruto(self, db):
        # Kes karyawan 1% tidak mengurangi bruto; premi Kes perusahaan 4% × 10jt = 400.000 MASUK bruto
        s = _slip(db, prof=_prof(base_rate=10_000_000), emp=_emp(bpjs_programs={"kes": True}))
        assert s["tax"]["taxable_gross"] == 10_400_000
        assert _ded(s, "pph21")[0]["amount"] == 260_000                              # TER A 10.350.001–10.700.000 = 2,5%

    def test_pkp_setahun_desember(self, db):
        # 11 slip Jan–Nov (bruto pajak 10.054.000, PPh21 TER 226.215, JHT 200.000, JP 100.000) + Desember
        db.rahaza_payroll_runs.docs = [{"id": "r-prev", "status": "finalized"}]
        for m in range(1, 12):
            db.rahaza_payslips.docs.append({
                "id": f"s{m}", "run_id": "r-prev", "employee_id": "emp-a", "period_to": f"2026-{m:02d}-28",
                "gross_pay": 10_000_000, "tax": {"tax_month": f"2026-{m:02d}", "taxable_gross": 10_054_000},
                "deductions": [{"type": "pph21", "amount": 226_215}, {"type": "bpjs_jht", "amount": 200_000},
                               {"type": "bpjs_jp", "amount": 100_000}]})
        emp = _emp(bpjs_programs={"jht": True, "jp": True, "jkk_jkm": True})
        s = _slip(db, prof=_prof(base_rate=10_000_000), emp=emp, period=("2026-12-01", "2026-12-31"))
        # setahun: bruto 120.648.000 − biaya jabatan 6.000.000 − JHT/JP 3.600.000 − PTKP 54.000.000
        # = PKP 57.048.000 × 5% = 2.852.400 − dipotong Jan–Nov 2.488.365 = 364.035
        assert s["tax"]["taxable_gross"] == 10_054_000
        assert s["tax"]["pph21"]["method"] == "annual" and s["tax"]["pph21"]["pkp"] == 57_048_000
        assert _ded(s, "pph21")[0]["amount"] == 364_035

    def test_pengaturan_hr_atau_keuangan(self, env):
        env.db.rahaza_payroll_settings.docs.append({"key": "pph21"})
        env.actor["user"] = dict(FIN)
        out = run(pset.set_pph21(FakeRequest({"ptkp": {"TK/0": 60_000_000}})))
        assert out["settings"]["ptkp"]["TK/0"] == 60_000_000 and out["settings"]["ptkp"]["K/3"] == 72_000_000
        bad = {"ter": {"A": [[5_000_000, 0], [4_000_000, 0.01], [None, 0.02]]}}
        assert _err(pset.set_pph21(FakeRequest(bad))).status_code == 400
        env.actor["user"] = dict(OPERATOR)
        assert _err(pset.get_pph21(FakeRequest())).status_code == 403


# ═══ 6. Lembur ═════════════════════════════════════════════════════════════════
class TestLembur:
    def test_hanya_pengajuan_atau_tanda_hr_pengali_per_hari(self, db):
        # upah sejam 3.460.000/173 = 20.000
        db.rahaza_attendance_events.docs = [
            _ev("2026-10-05", overtime_hours=3),                          # tanpa pengajuan → tidak dibayar
            _ev("2026-10-06", overtime_hours=2, overtime_paid=True),      # ditandai HR → 1,5 + 2 = 3,5
            _ev("2026-10-07", overtime_hours=2),                          # pengajuan 1 jam → 1,5
            _ev("2026-10-08", overtime_hours=2, overtime_paid=False)]     # HR: tidak dibayar
        db.rahaza_overtime_requests.docs = [
            {"employee_id": "emp-a", "date": "2026-10-07", "status": "approved", "hours": 1, "rate_multiplier": 3},
            {"employee_id": "emp-a", "date": "2026-10-08", "status": "approved", "hours": 2},
            # Minggu: 7 × 2 + 1 × 3 + 1 × 4 = 21 (pengali pilihan pemohon 1,5 diabaikan)
            {"employee_id": "emp-a", "date": "2026-10-11", "status": "approved", "hours": 9, "rate_multiplier": 1.5},
            {"employee_id": "emp-a", "date": "2026-10-12", "status": "pending", "hours": 5}]
        # 2026-11-09 (Q9): lembur dibayar dari jam NYATA — Minggu 11 Okt punya absen 9 jam kerja bersih.
        db.rahaza_attendance_events.docs.append(_ev("2026-10-11", hours_worked=9, net_hours_worked=9))
        s = _slip(db, prof=_prof(base_rate=3_460_000))
        by = {o["date"]: o for o in s["overtime_entries"]}
        assert by["2026-10-05"]["paid_hours"] == 0 and by["2026-10-08"]["paid_hours"] == 0
        assert by["2026-10-06"]["factor"] == 3.5 and by["2026-10-07"]["factor"] == 1.5
        assert by["2026-10-11"]["factor"] == 21 and "2026-10-12" not in by
        assert s["overtime_amount"] == 26 * 20_000 and s["overtime_hours"] == 12
        assert any(w["type"] == "overtime_unapproved" and w["message"].startswith("3 jam") for w in s["warnings"])

    def test_tingkatan_hari_libur_bisa_diatur(self, db):
        db.rahaza_payroll_settings.docs = [{"key": "overtime", "basis": "upah_tetap_div_173", "divisor": 173,
                                            "rest_day_first_multiplier": 3, "rest_day_first_hours_6d": 5}]
        db.rahaza_production_calendar.docs = [{"date": "2026-10-20", "type": "holiday"}]   # Selasa libur
        db.rahaza_overtime_requests.docs = [{"employee_id": "emp-a", "date": "2026-10-20", "status": "approved",
                                             "hours": 6}]
        db.rahaza_attendance_events.docs = [_ev("2026-10-20", hours_worked=6, net_hours_worked=6)]   # Q9: jam nyata
        s = _slip(db, prof=_prof(base_rate=3_460_000))
        assert s["overtime_entries"][0]["factor"] == 5 * 3 + 1 * 3

    def test_tier_factor_murni(self):
        assert rules.tier_factor(3, [[1, 1.5], [None, 2]]) == 5.5
        assert rules.tier_factor(0.5, [[1, 1.5], [None, 2]]) == 0.75


# ═══ 7. Kenaikan gaji berversi ═════════════════════════════════════════════════
class TestKenaikanGaji:
    def _adj(self, db, eff="2026-10-15"):
        db.rahaza_salary_adjustments.docs = [{"id": "adj-1", "employee_id": "emp-a", "status": "pending_hr",
                                              "current_base": BASE, "proposed_base": 3_240_000,
                                              "effective_date": eff, "created_by": "u-x"}]
        db.rahaza_payroll_profiles.docs = [_prof()]

    def test_kotak_masuk_hr_membuat_versi_dan_payroll_prorata(self, env):
        self._adj(env.db)
        out = run(inbox.approve_request("salary_adjustment", "adj-1", None, user=dict(HR)))
        assert out["new_status"] == "approved"
        prof = env.db.rahaza_payroll_profiles.docs[0]
        assert [(v["effective_from"], v["base_rate"]) for v in prof["rate_versions"]] == [
            (None, BASE), ("2026-10-15", 3_240_000)]
        assert prof["base_rate"] == 3_240_000                                    # hari ini sudah berlaku
        s = _slip(env.db, prof=prof)
        # 1–14 Okt = 12 hari × 2.700.000/27 + 15–31 Okt = 15 hari × 3.240.000/27 = 1.200.000 + 1.800.000
        assert [e["amount"] for e in s["earnings"]] == [1_200_000, 1_800_000] and s["earnings_total"] == 3_000_000

    def test_layar_penyesuaian_sama_dan_idempoten(self, env):
        self._adj(env.db, eff="2027-01-01")
        out = run(sal_adj.approve_by_hr("adj-1", FakeRequest({})))
        assert "2027-01-01" in out["message"]
        prof = env.db.rahaza_payroll_profiles.docs[0]
        assert prof["base_rate"] == BASE                                         # belum berlaku hari ini
        run(profiles.apply_salary_adjustment_to_profile(env.db, env.db.rahaza_salary_adjustments.docs[0], HR))
        assert len(env.db.rahaza_payroll_profiles.docs[0]["rate_versions"]) == 2

    def test_ubah_tarif_manual_dengan_tanggal_berlaku(self, env):
        env.db.rahaza_employees.docs = [_emp()]
        env.db.rahaza_payroll_profiles.docs = [_prof()]
        run(profiles.update_profile("p-a", FakeRequest({"pay_scheme": "monthly", "base_rate": 3_000_000,
                                                         "effective_from": "2026-10-20"})))
        prof = env.db.rahaza_payroll_profiles.docs[0]
        assert rules.rate_on(prof, date(2026, 10, 19)) == BASE and rules.rate_on(prof, date(2026, 10, 20)) == 3_000_000


# ═══ 8. Satu sumber gaji ═══════════════════════════════════════════════════════
class TestSatuSumberGaji:
    def test_data_karyawan_tidak_menulis_gaji(self, monkeypatch, db):
        async def gate(request):
            return dict(HR)

        async def noop(*a, **k):
            return None
        monkeypatch.setattr(master, "_require_admin", gate)
        monkeypatch.setattr(master, "get_db", lambda: db)
        monkeypatch.setattr(master, "log_activity", noop)
        db.rahaza_employees.docs = [{"id": "emp-a", "name": "Ani", "base_rate": 1}]
        out = run(master.update_employee("emp-a", FakeRequest({"base_rate": 9_999_999, "wage_scheme": "bulanan",
                                                                "join_date": "2026-10-15T00:00:00"})))
        assert out["base_rate"] == 1 and "wage_scheme" not in out and out["join_date"] == "2026-10-15"

    def test_layar_data_karyawan_baca_saja(self):
        src = open(os.path.join(REPO, "frontend", "src", "components", "erp", "HREmployeeModule.jsx"),
                   encoding="utf-8").read()
        assert "set('base_rate')" not in src and "set('wage_scheme')" not in src
        assert "join_date" in src and "resign_date" in src and "Profil Gaji" in src
        assert "!== 15" not in src                                               # NPWP 16 digit diterima


# ═══ 9. Pemisahan tugas ════════════════════════════════════════════════════════
def _draft(db, created_by="u-hr", net=2_000_000):
    db.rahaza_payroll_runs.docs.append({"id": "r1", "run_number": "PR-1", "status": "draft", "created_by": created_by,
                                        "period_from": OCT[0], "period_to": OCT[1]})
    db.rahaza_payslips.docs.append({"id": "s1", "run_id": "r1", "employee_id": "emp-a", "employee_name": "Ani",
                                    "period_from": OCT[0], "period_to": OCT[1], "gross_pay": 2_000_000,
                                    "deductions_total": 2_000_000 - net, "net_pay": net, "deductions": []})


class TestPemisahanTugas:
    def test_pembuat_tidak_boleh_finalisasi(self, env):
        _draft(env.db)
        e = _err(runs.finalize_run("r1", FakeRequest()))
        assert e.status_code == 403 and "Pemisahan tugas" in e.detail
        env.actor["user"] = dict(HR2)
        assert run(runs.finalize_run("r1", FakeRequest()))["status"] == "finalized"

    def test_admin_boleh_dengan_alasan(self, env):
        _draft(env.db, created_by="u-adm")
        env.actor["user"] = dict(ADMIN)
        assert "alasan" in _err(runs.finalize_run("r1", FakeRequest())).detail
        out = run(runs.finalize_run("r1", FakeRequest({"override_reason": "HR lain cuti"})))
        assert out["status"] == "finalized" and out["sod_overrides"][0]["reason"] == "HR lain cuti"

    def test_pembuat_tidak_boleh_membayar(self, env):
        env.db.rahaza_payroll_runs.docs.append({"id": "rf", "run_number": "PR-F", "status": "finalized",
                                                "created_by": "u-hr", "total_net": 1000})
        e = _err(runs.pay_payroll_run("rf", FakeRequest({"bank_account_code": "1-1201"})))
        assert e.status_code == 403


# ═══ 10. BPJS & PPh21 semua skema ══════════════════════════════════════════════
class TestSemuaSkema:
    def test_borongan_pcs_kumulatif_per_bulan(self, db):
        emp = _emp(bpjs_programs={"kes": True})
        prof = _prof(pay_scheme="pcs", base_rate=1_500)
        db.rahaza_wip_events.docs = [{"operator_id": "emp-a", "event_type": "output", "event_date": "2026-10-14",
                                      "qty": 1_000, "process_id": "p1"}]
        s1 = _slip(db, prof=prof, emp=emp, period=("2026-10-08", "2026-10-14"))
        assert _ded(s1, "bpjs_kesehatan")[0]["amount"] == 15_000                     # 1% × 1.500.000
        assert "pph21" in s1["tax"]
        db.rahaza_payroll_runs.docs = [{"id": "rw1", "status": "draft"}]
        db.rahaza_payslips.docs = [{**s1, "run_id": "rw1"}]
        db.rahaza_wip_events.docs.append({"operator_id": "emp-a", "event_type": "output",
                                          "event_date": "2026-10-20", "qty": 1_000, "process_id": "p1"})
        s2 = _slip(db, prof=prof, emp=emp, period=("2026-10-15", "2026-10-21"))
        # bulan Okt: dasar 1.500.000 + 1.500.000 = 3.000.000 → Kes 30.000 − sudah 15.000 = 15.000
        assert s2["tax"]["bpjs_month_base"] == 3_000_000 and _ded(s2, "bpjs_kesehatan")[0]["amount"] == 15_000

    def test_dua_run_bulanan_tidak_memotong_dua_kali(self, db):
        emp = _emp(bpjs_programs={"kes": True})
        s1 = _slip(db, emp=emp)
        db.rahaza_payroll_runs.docs = [{"id": "rm1", "status": "finalized"}]
        db.rahaza_payslips.docs = [{**s1, "run_id": "rm1"}]
        s2 = _slip(db, emp=emp, period=("2026-10-25", "2026-10-31"))
        assert _ded(s1, "bpjs_kesehatan")[0]["amount"] == 27_000 and _ded(s2, "bpjs_kesehatan") == []


# ═══ 12. Gaji bersih minus ═════════════════════════════════════════════════════
class TestGajiMinus:
    def test_finalisasi_diblokir_dengan_nama(self, env):
        _draft(env.db, created_by="u-lain", net=-5_000)
        e = _err(runs.finalize_run("r1", FakeRequest()))
        assert e.status_code == 400 and "Ani" in e.detail and "minus" in e.detail
        assert env.db.rahaza_payroll_runs.docs[0]["status"] == "draft"

    def test_mesin_hitung_memberi_peringatan(self, db):
        db.dewi_kasbon_requests.docs = []
        db.da_payroll_allowances.docs = []
        db.rahaza_payroll_settings.docs = [{"key": "late_penalty", "enabled": True, "mode": "per_minute",
                                            "amount_per_minute": 1_000_000}]
        db.rahaza_attendance_events.docs = [_ev("2026-10-05", late_minutes=10)]
        s = _slip(db, prof=_prof(base_rate=1_000_000))
        assert s["net_pay"] < 0 and any(w["type"] == "negative_net" for w in s["warnings"])


# ═══ 13. Hitung ulang ══════════════════════════════════════════════════════════
class TestHitungUlang:
    def test_penyesuaian_manual_dipertahankan(self, env):
        env.db.rahaza_employees.docs = [_emp()]
        env.db.rahaza_payroll_profiles.docs = [_prof()]
        _draft(env.db, created_by="u-lain")
        env.db.rahaza_payslips.docs[0].update(manual_addition=50_000, manual_deduction=20_000,
                                              adjustment_notes="bonus proyek")
        env.db.rahaza_attendance_events.docs = [_ev("2026-10-05", "alpa")]
        out = run(runs.recalculate_run("r1", FakeRequest()))
        slip = env.db.rahaza_payslips.docs[0]
        assert slip["id"] == "s1" and slip["adjustment_notes"] == "bonus proyek"
        assert slip["gross_pay"] == BASE + 50_000 and slip["deductions_total"] == 100_000 + 20_000
        assert out["total_net"] == BASE + 50_000 - 120_000 and out["recalculated_by"] == "u-hr"
        env.db.rahaza_payroll_runs.docs[0]["status"] = "finalized"
        assert _err(runs.recalculate_run("r1", FakeRequest())).status_code == 400


# ═══ 14. Kunci absensi + koreksi ═══════════════════════════════════════════════
class TestKunciAbsensi:
    def test_terkunci_hanya_run_final(self, db):
        db.rahaza_payroll_runs.docs = [{"id": "r1", "run_number": "PR-1", "status": "draft"}]
        db.rahaza_payslips.docs = [{"id": "s1", "run_id": "r1", "employee_id": "emp-a",
                                    "period_from": OCT[0], "period_to": OCT[1]}]
        assert not run(shared.is_attendance_locked(db, "emp-a", "2026-10-15"))
        db.rahaza_payroll_runs.docs[0]["status"] = "finalized"
        assert run(shared.is_attendance_locked(db, "emp-a", "2026-10-15"))
        assert run(shared.attendance_lock(db, "emp-a", date(2026, 10, 31)))["run_number"] == "PR-1"
        assert not run(shared.is_attendance_locked(db, "emp-a", "2026-11-01"))
        assert not run(shared.is_attendance_locked(db, "emp-b", "2026-10-15"))
        db.rahaza_payroll_runs.docs[0]["status"] = "cancelled"
        assert not run(shared.is_attendance_locked(db, "emp-a", "2026-10-15"))

    def test_koreksi_sesudah_kunci_masuk_run_berikutnya_sekali(self, db):
        # Run Okt final memotong alpa 5 Okt; HR lalu mengoreksi 5 Okt menjadi hadir → Nov mengembalikan 100.000
        db.rahaza_attendance_events.docs = [_ev("2026-10-05", "alpa")]
        okt = _slip(db)
        assert okt["attendance_snapshot"] == {"2026-10-05": {"ded": 1.0, "ot": 0.0}}
        db.rahaza_payroll_runs.docs = [{"id": "r-okt", "run_number": "PR-OKT", "status": "finalized"}]
        db.rahaza_payslips.docs = [{**okt, "run_id": "r-okt"}]
        db.rahaza_attendance_events.docs = [_ev("2026-10-05", "hadir")]
        nov = _slip(db, period=("2026-11-01", "2026-11-30"), run_id="r-nov")
        row = [e for e in nov["earnings"] if e["type"] == "attendance_correction"]
        assert row and row[0]["amount"] == 100_000 and "PR-OKT" in row[0]["label"]
        assert nov["corrections"][0]["source_slip_id"] == okt["id"]
        run(shared.apply_correction_trail(db, [nov]))                             # Nov difinalisasi
        again = _slip(db, period=("2026-11-01", "2026-11-30"), run_id="r-nov2")
        assert not [e for e in again["earnings"] if e["type"] == "attendance_correction"]
        run(shared.apply_correction_trail(db, [nov], revert=True))                # run Nov dibatalkan
        assert [e["amount"] for e in _slip(db, period=("2026-11-01", "2026-11-30"), run_id="r-nov3")["earnings"]
                if e["type"] == "attendance_correction"] == [100_000]


# ═══ 15. Daftar tunjangan ══════════════════════════════════════════════════════
class TestDaftarTunjangan:
    def test_hanya_peran_payroll(self, monkeypatch, db):
        async def op(request):
            return dict(OPERATOR)
        monkeypatch.setattr(shared, "require_auth", op)
        monkeypatch.setattr(allowances, "get_db", lambda: db)
        assert _err(allowances.list_allowances(FakeRequest())).status_code == 403

        async def hr(request):
            return dict(HR)
        monkeypatch.setattr(shared, "require_auth", hr)
        assert run(allowances.list_allowances(FakeRequest()))["ok"]


# ═══ 16. Migrasi ═══════════════════════════════════════════════════════════════
def _migration():
    p = os.path.join(BACKEND, "scripts", "migrations", "2026_11_06_payroll_tahap2.py")
    spec = importlib.util.spec_from_file_location("mig_payroll_t2", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigrasi:
    def _seed(self, db):
        db.rahaza_employees.docs = [{"id": "e1", "join_date": "2025-01-01", "base_rate": 3_000_000, "wage_scheme": "bulanan"},
                                    {"id": "e2", "joined_at": "2026-11-01T00:00:00", "base_rate": 0},
                                    {"id": "e3", "base_rate": 4_500, "wage_scheme": "borongan_pcs"},
                                    {"id": "e4", "active": False}]
        db.rahaza_payroll_profiles.docs = [{"employee_id": "e1", "active": True, "base_rate": 3_200_000,
                                            "pay_scheme": "monthly"}]
        db.rahaza_payroll_runs.docs = [
            {"id": "g1", "status": "draft", "period": {"from": "2026-10-01", "to": "2026-10-31"},
             "trigger_mode": "manual_automation"},
            {"id": "ok1", "status": "draft", "period_from": "2026-10-01", "period_to": "2026-10-31"}]

    def test_pratinjau_lalu_tulis_idempoten(self, db, capsys):
        mig = _migration()
        self._seed(db)
        out = run(mig.run(False, db=db))
        assert out == {"work_calendar_created": 1, "employees_active": 3, "employees_missing_join_date": 2,
                       "employees_missing_join_date_with_joined_at": 1, "salary_field_differences": 2,
                       "salary_field_without_profile": 1, "ghost_runs": 1}
        assert db.rahaza_payroll_settings.docs == [] and db.rahaza_payroll_runs.docs[0]["status"] == "draft"
        run(mig.run(True, db=db))
        assert db.rahaza_payroll_settings.docs[0]["work_days_per_week"] == 6
        assert db.rahaza_payroll_runs.docs[0]["status"] == "cancelled" and db.rahaza_payroll_runs.docs[1]["status"] == "draft"
        again = run(mig.run(True, db=db))
        assert again["work_calendar_created"] == 0 and again["ghost_runs"] == 0
        assert len(db.rahaza_payroll_settings.docs) == 1
        printed = capsys.readouterr().out
        assert "Ani" not in printed and "e1" not in printed


def test_tanggal_uji_konsisten():
    assert date(2026, 10, 1).weekday() == 3 and date(2026, 10, 11).weekday() == 6
    assert len(OCT_WD) == 27 and date(2026, 10, 20).weekday() == 1
    assert (date(2026, 10, 31) - timedelta(days=0)).weekday() == 5
    assert re.match(r"\d{4}-\d{2}-\d{2}", OCT[0])


# ═══ Penyatuan absen ↔ payroll: koreksi absen tanggal terkunci → penyesuaian run berikutnya ═══
class TestKoreksiAbsenDariPaketAbsen:
    def test_koreksi_tertunda_dibayar_sekali_lalu_ditandai(self, db):
        db.rahaza_attendance_events.docs = [_ev("2026-10-05", "alpa")]
        okt = _slip(db)
        db.rahaza_payroll_runs.docs = [{"id": "r-okt", "run_number": "PR-OKT", "status": "finalized"}]
        db.rahaza_payslips.docs = [{**okt, "run_id": "r-okt"}]
        # absensi 5 Okt TIDAK berubah (terkunci); koreksi HR disimpan paket absen sebagai penyesuaian payroll
        db.rahaza_attendance_corrections.docs = [{
            "id": "k1", "employee_id": okt["employee_id"], "date": "2026-10-05", "status": "approved",
            "apply_mode": "penyesuaian_payroll", "requested": {"status": "hadir"},
            "payroll_adjustment": {"status": "pending", "run_id": None, "applied_at": None}}]
        nov = _slip(db, period=("2026-11-01", "2026-11-30"), run_id="r-nov")
        row = [e for e in nov["earnings"] if e["type"] == "attendance_correction"]
        assert row and row[0]["amount"] == 100_000
        assert nov["corrections"][0]["attendance_correction_ids"] == ["k1"]
        run(shared.apply_correction_trail(db, [{**nov, "run_id": "r-nov"}]))
        assert db.rahaza_attendance_corrections.docs[0]["payroll_adjustment"]["status"] == "applied"
        # run berikutnya: tidak dibayar lagi dan tidak ditarik kembali
        again = _slip(db, period=("2026-11-01", "2026-11-30"), run_id="r-nov2")
        assert not [e for e in again["earnings"] if e["type"] == "attendance_correction"]
        assert not [d for d in again["deductions"] if d["type"] == "absence_correction"]
        run(shared.apply_correction_trail(db, [{**nov, "run_id": "r-nov"}], revert=True))
        assert db.rahaza_attendance_corrections.docs[0]["payroll_adjustment"]["status"] == "pending"
