"""Uji regresi HERMETIK Tahap 1 — payroll & absensi (2026-11-06). Tanpa server/Mongo (FakeDB).

Satu kelas uji per butir yang disetujui owner:
  1 konfigurasi payroll hanya HR & manajemen · 2 tulis absensi HR hanya HR & manajemen (swalayan tetap)
  3 grid absensi HR tidak menimpa jam selfie / cuti · 4 kasbon tidak terpotong dua kali
  5 cuti tanpa gaji lintas periode · 6 batal bayar gaji gagal → tetap dibayar · 7 kabar slip gaji
  8 layar cuti Portal Saya · 9 saldo cuti tidak minus · 10 rekap absensi HR tidak terpotong 500
  11 selfie ditolak HR tidak dihitung hadir / jam

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import asyncio
import os
import re
import sys
import types
from datetime import date, datetime, timedelta, timezone

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

# CI hanya memasang dependensi inti (tanpa openpyxl) — modul payroll mengimpornya di level atas.
try:  # pragma: no cover - tergantung lingkungan
    import openpyxl  # noqa: F401
except ImportError:  # pragma: no cover
    _op, _st, _ut = (types.ModuleType(n) for n in ("openpyxl", "openpyxl.styles", "openpyxl.utils"))
    for _n in ("Font", "PatternFill", "Alignment", "Border", "Side"):
        setattr(_st, _n, object)
    _st.numbers = types.SimpleNamespace()
    _ut.get_column_letter = lambda i: "A"
    _op.styles, _op.utils, _op.Workbook = _st, _ut, object
    sys.modules.update({"openpyxl": _op, "openpyxl.styles": _st, "openpyxl.utils": _ut})

from starlette.requests import Request  # noqa: E402

from _fake_mongo import _MISSING, FakeCollection, FakeCursor, FakeDB, FakeRequest, _get  # noqa: E402

import auth  # noqa: E402
import routes.dewi_portal_saya_ext as portal_ext  # noqa: E402
import routes.rahaza_attendance as att  # noqa: E402
import routes.rahaza_auto_attendance_selfie as selfie  # noqa: E402
import routes.rahaza_hr_reports as hr_reports  # noqa: E402
import routes.rahaza_leave_balances as balances  # noqa: E402
import routes.rahaza_payroll_allowances as allowances  # noqa: E402
import routes.rahaza_payroll_profiles as profiles  # noqa: E402
import routes.rahaza_payroll_runs as runs  # noqa: E402
import routes.rahaza_payroll_shared as shared  # noqa: E402
import routes.rahaza_self as rahaza_self  # noqa: E402
import utils.attendance_policy as policy  # noqa: E402


def _import_needing_multipart(name):
    """Modul dengan rute unggah (UploadFile) memeriksa python-multipart saat impor; job CI unit tidak
    memasangnya. Rute unggah tidak diuji di sini → pemeriksaan dilewati saat impor saja."""
    import importlib
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


leave_mod = _import_needing_multipart("routes.rahaza_leave")
portal_hr = _import_needing_multipart("routes.dewi_portal_saya_hr")

run = asyncio.run


# ── Mongo palsu + aggregate ($match/$group) — hanya di berkas ini ────────────
def _val(doc, expr):
    if isinstance(expr, str) and expr.startswith("$"):
        v = _get(doc, expr[1:])
        return None if v is _MISSING else v
    if isinstance(expr, dict) and "$cond" in expr:
        cond, yes, no = expr["$cond"]
        return yes if _val(doc, cond) else no
    # 2026-11-09: rekap menit terlambat/pulang cepat memakai $ifNull & $gt (Q3)
    if isinstance(expr, dict) and "$ifNull" in expr:
        v, alt = expr["$ifNull"]
        got = _val(doc, v)
        return alt if got is None else got
    if isinstance(expr, dict) and "$gt" in expr:
        a, b = (_val(doc, x) for x in expr["$gt"])
        return (a or 0) > (b or 0)
    return expr


class _AggCollection(FakeCollection):
    def aggregate(self, pipeline):
        docs = [d for d in self.docs]
        out = None
        for stage in pipeline:
            if "$match" in stage:
                docs = list(self.find(stage["$match"])._docs)
            elif "$group" in stage:
                spec = dict(stage["$group"])
                id_spec = spec.pop("_id")
                groups: dict = {}
                for d in docs:
                    gid = {k: _val(d, v) for k, v in id_spec.items()}
                    key = tuple(sorted(gid.items(), key=lambda kv: kv[0]))
                    row = groups.setdefault(key, {"_id": gid, **{f: 0 for f in spec}})
                    for f, acc in spec.items():
                        row[f] += _val(d, acc["$sum"])
                out = list(groups.values())
                docs = out
            else:  # pragma: no cover
                raise NotImplementedError(stage)
        return FakeCursor(docs if out is None else out)


class AggDB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _AggCollection(name)
        return self._cols[name]


HR = {"id": "u-hr", "role": "hr", "name": "Brenda HR", "email": "hr@x"}


@pytest.fixture
def db(monkeypatch):
    d = AggDB()
    d.rahaza_employees.docs = [
        {"id": "emp-a", "name": "Ani", "employee_code": "E01", "active": True, "user_id": "u-operator"},
        {"id": "emp-b", "name": "Budi", "employee_code": "E02", "active": True, "user_id": "u-budi"},
    ]

    async def noop(*a, **k):
        return None

    for mod in (att, selfie, hr_reports, balances, allowances, profiles, runs, portal_ext, portal_hr,
                rahaza_self, leave_mod):
        monkeypatch.setattr(mod, "get_db", lambda: d)
        if hasattr(mod, "log_activity"):
            monkeypatch.setattr(mod, "log_activity", noop)
    return d


@pytest.fixture
def login(monkeypatch):
    """Login lewat `auth.require_auth` ASLI (JWT + loader dipalsukan): peran dibaca live dari 'DB'."""
    state = {}

    async def live(uid):
        return {"id": uid, "role": state["role"]}

    async def rbac(role, uid):
        return [], []

    async def portals(role, uid):
        return [], []

    monkeypatch.setattr(auth, "_load_live_user", live)
    monkeypatch.setattr(auth, "_load_rbac", rbac)
    monkeypatch.setattr(auth, "_load_portal_config", portals)

    def _req(role, body=None):
        state["role"] = role
        tok = auth.create_token({"id": f"u-{role}", "email": f"{role}@x.test", "role": role, "name": role})
        scope = {"type": "http", "method": "POST", "path": "/", "query_string": b"",
                 "headers": [(b"authorization", f"Bearer {tok}".encode())]}
        req = Request(scope)
        payload = dict(body or {})

        async def _json():
            return dict(payload)
        req.json = _json
        return req
    return _req


def _status(coro):
    try:
        run(coro)
        return 200
    except HTTPException as e:
        return e.status_code


def _src(*parts):
    p = os.path.join(REPO, *parts)
    if not os.path.exists(p):
        pytest.skip(f"sumber frontend tidak tersedia: {p}")
    return open(p, encoding="utf-8").read()


# ── Butir 1: konfigurasi payroll ─────────────────────────────────────────────
NON_HR = ["operator", "tim_packing", "admin_gudang", "accounting", "pic_toko", "supervisor_produksi"]
# Keputusan owner 6 Nov 2026: penggajian hanya untuk peran semula (HR Manager & Staf HR tidak).
HR_MGMT = ["hr", "manager", "owner", "admin", "superadmin"]
PAYROLL_TERTUTUP = NON_HR + ["hr_manager", "staff_hr"]


class TestKonfigurasiPayroll:
    @pytest.mark.parametrize("role", PAYROLL_TERTUTUP)
    def test_peran_lain_ditolak(self, db, login, role):
        body = {"name": "Insentif makan", "amount": 10000, "calc_type": "per_day_attendance"}
        assert _status(allowances.create_allowance(login(role, body))) == 403
        assert _status(allowances.update_allowance("al-1", login(role, {"amount": 1}))) == 403
        assert _status(allowances.delete_allowance("al-1", login(role))) == 403
        assert _status(profiles.list_profiles(login(role), employee_id=None, active_only=True)) == 403
        assert _status(profiles.get_profile("emp-a", login(role))) == 403
        assert db.da_payroll_allowances.docs == []

    @pytest.mark.parametrize("role", HR_MGMT)
    def test_hr_dan_manajemen_boleh(self, db, login, role):
        out = run(allowances.create_allowance(login(role, {"name": "Tunjangan jabatan", "amount": 500000})))
        assert out["ok"] and len(db.da_payroll_allowances.docs) == 1
        db.rahaza_payroll_profiles.docs = [{"id": "p1", "employee_id": "emp-a", "active": True, "base_rate": 1}]
        rows = run(profiles.list_profiles(login(role), employee_id=None, active_only=True))
        assert [r["employee_name"] for r in rows] == ["Ani"]

    def test_gerbang_payroll_tetap_peran_semula(self):
        assert set(shared.PAYROLL_HR_ROLES) == {"superadmin", "admin", "owner", "hr", "manager"}


# ── Butir 2: tulis absensi HR ────────────────────────────────────────────────
class TestTulisAbsensiHr:
    @pytest.mark.parametrize("role", NON_HR)
    def test_peran_lain_tidak_boleh_menulis_absensi_dan_lembur(self, db, login, role):
        body = {"employee_id": "emp-a", "date": "2026-11-05", "status": "hadir", "hours_worked": 8,
                "overtime_hours": 5}
        assert _status(att.upsert_attendance(login(role, body))) == 403
        assert _status(att.bulk_attendance(login(role, {"date": "2026-11-05", "entries": [body]}))) == 403
        assert db.rahaza_attendance_events.docs == []

    @pytest.mark.parametrize("role", ["hr", "hr_manager", "manager", "owner", "admin"])
    def test_hr_dan_manajemen_boleh(self, db, login, role):
        body = {"date": "2026-11-05", "entries": [{"employee_id": "emp-a", "status": "hadir", "hours_worked": 8}]}
        assert run(att.bulk_attendance(login(role, body)))["saved"] == 1

    def test_absen_selfie_swalayan_tetap_jalan_untuk_diri_sendiri(self, db, login, monkeypatch):
        async def policy_ok(_db, **kw):
            return {"office": {}, "geo": {"status": "in_range", "distance_m": 3}}
        monkeypatch.setattr(policy, "enforce_attendance_policy", policy_ok)
        monkeypatch.setattr(policy, "save_selfie", lambda *a, **k: None)
        out = run(selfie.selfie_clock_in(login("operator", {"lat": 1, "lng": 1, "photo_base64": "x"})))
        assert out["ok"] and out["attendance"]["employee_id"] == "emp-a"
        # atas nama karyawan lain → ditolak
        assert _status(selfie.selfie_clock_in(login("operator", {"employee_id": "emp-b", "photo_base64": "x"}))) == 403


# ── Butir 3: grid absensi HR ─────────────────────────────────────────────────
CIN = datetime(2026, 11, 5, 1, 30, tzinfo=timezone.utc)    # 08:30 WIB
COUT = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)   # 17:00 WIB


def _selfie_record():
    return {"id": "ev-1", "employee_id": "emp-a", "date": "2026-11-05", "status": "hadir",
            "clock_in": CIN, "clock_out": COUT, "hours_worked": 8.5, "net_hours_worked": 8.5,
            "late_minutes": 25, "is_late": True, "source": "selfie_geo_ai", "approval_status": "pending",
            "shift_id": None, "notes": ""}


class TestGridAbsensi:
    def test_simpan_catatan_tidak_menghapus_jam_selfie(self, db, login):
        db.rahaza_attendance_events.docs = [_selfie_record()]
        body = {"date": "2026-11-05", "entries": [{"employee_id": "emp-a", "notes": "Lupa absen istirahat"}]}
        assert run(att.bulk_attendance(login("hr", body)))["saved"] == 1
        rec = db.rahaza_attendance_events.docs[0]
        assert rec["clock_in"] == CIN and rec["clock_out"] == COUT
        assert rec["late_minutes"] == 25 and rec["hours_worked"] == 8.5
        assert rec["source"] == "selfie_geo_ai" and rec["notes"] == "Lupa absen istirahat"

    def test_lembur_diubah_hanya_lembur_yang_ditulis(self, db, login):
        db.rahaza_attendance_events.docs = [_selfie_record()]
        run(att.bulk_attendance(login("hr", {"date": "2026-11-05",
                                             "entries": [{"employee_id": "emp-a", "overtime_hours": 2}]})))
        rec = db.rahaza_attendance_events.docs[0]
        assert rec["overtime_hours"] == 2 and rec["clock_in"] == CIN and rec["late_minutes"] == 25

    def test_ubah_ke_alfa_jam_masuk_tetap_terlambat_nol(self, db, login):
        db.rahaza_attendance_events.docs = [_selfie_record()]
        run(att.upsert_attendance(login("hr", {"employee_id": "emp-a", "date": "2026-11-05", "status": "alfa",
                                               "shift_id": None, "hours_worked": 0, "overtime_hours": 0})))
        rec = db.rahaza_attendance_events.docs[0]
        assert rec["status"] == "alfa" and rec["clock_in"] == CIN and rec["late_minutes"] == 0
        assert rec["hours_worked"] == 0 and rec["net_hours_worked"] == 0

    def test_baris_baru_tetap_dibuat_lengkap(self, db, login):
        run(att.bulk_attendance(login("hr", {"date": "2026-11-05", "entries": [
            {"employee_id": "emp-b", "status": "hadir", "shift_id": None, "hours_worked": 8, "notes": ""}]})))
        rec = db.rahaza_attendance_events.docs[0]
        assert rec["id"] and rec["status"] == "hadir" and rec["hours_worked"] == 8 and rec["source"] == "supervisor"

    def test_layar_hanya_mengirim_kolom_yang_berubah(self):
        s = _src("frontend", "src", "components", "erp", "RahazaAttendanceModule.jsx")
        assert "savedRows" in s and re.search(r"changed\s*=\s*Object\.keys\(full\)\.filter", s)
        # tombol "Simpan Semua" memanggil saveAll(event): event tidak boleh dianggap daftar baris
        assert "Array.isArray(rowsArg)" in s

    def test_tandai_hadir_tidak_menimpa_catatan_yang_ada(self):
        s = _src("frontend", "src", "components", "erp", "RahazaAttendanceModule.jsx")
        body = s[s.index("const markAllHadirAndSave"):]
        body = body[:body.index("};") + 2]
        assert re.search(r"r\.existing_id\s*\|\|\s*\(r\.status \|\| 'hadir'\) !== 'hadir'", body)


# ── Butir 4: kasbon ──────────────────────────────────────────────────────────
PROFILE = {"employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": 3_000_000, "active": True}
EMP_A = {"id": "emp-a", "name": "Ani"}


def _seed_kasbon(db, run_status="draft"):
    db.dewi_kasbon_requests.docs = [{
        "id": "k1", "employee_id": "emp-a", "type": "kasbon", "status": "disbursed", "request_number": "KSB-1",
        "deduction_start_period": "2026-10", "outstanding_balance": 500_000.0, "paid_amount": 0.0,
        "disbursed_at": "2026-09-25", "repayments": []}]
    db.rahaza_payroll_runs.docs = [{"id": "r1", "run_number": "PR-1", "status": run_status,
                                    "period_from": "2026-10-01", "period_to": "2026-10-07"}]
    db.rahaza_payslips.docs = [{"id": "s1", "run_id": "r1", "employee_id": "emp-a", "period_from": "2026-10-01",
                                "deductions": [{"type": "kasbon", "kasbon_id": "k1", "amount": 500_000}]}]


def _kasbon_ded(slip):
    return [d for d in slip["deductions"] if d.get("type") == "kasbon"]


class TestKasbonSatuRun:
    def test_run_kedua_bulan_sama_tidak_memotong_lagi(self, db):
        _seed_kasbon(db, "draft")
        slip = run(shared._compute_payslip_for_employee(db, PROFILE, "2026-10-08", "2026-10-14", EMP_A))
        assert _kasbon_ded(slip) == []
        assert slip["source_refs"]["kasbon_skipped_other_run"] == [{"kasbon_id": "k1", "run_number": "PR-1"}]

    def test_run_lama_dibatalkan_kasbon_boleh_dipotong(self, db):
        _seed_kasbon(db, "cancelled")
        slip = run(shared._compute_payslip_for_employee(db, PROFILE, "2026-10-08", "2026-10-14", EMP_A))
        assert [d["amount"] for d in _kasbon_ded(slip)] == [500_000]

    def test_bulan_lain_tidak_terhalang(self, db):
        _seed_kasbon(db, "draft")
        db.dewi_kasbon_requests.docs[0].update(type="pinjaman", installment_amount=100_000.0)
        slip = run(shared._compute_payslip_for_employee(db, PROFILE, "2026-11-01", "2026-11-30", EMP_A))
        assert [d["amount"] for d in _kasbon_ded(slip)] == [100_000]

    def test_finalisasi_run_draft_lama_yang_dobel_ditolak(self, db, monkeypatch):
        _seed_kasbon(db, "finalized")
        db.dewi_kasbon_requests.docs[0]["repayments"] = [
            {"method": "payroll_deduction", "period": "2026-10", "run_id": "r1", "run_number": "PR-1", "amount": 500_000}]
        db.rahaza_payroll_runs.docs.append({"id": "r2", "run_number": "PR-2", "status": "draft",
                                            "period_from": "2026-10-08", "period_to": "2026-10-14"})
        db.rahaza_payslips.docs.append({"id": "s2", "run_id": "r2", "employee_id": "emp-a", "period_from": "2026-10-08",
                                        "gross_pay": 1000.0, "deductions_total": 500_000.0, "net_pay": 0.0,
                                        "deductions": [{"type": "kasbon", "kasbon_id": "k1", "amount": 500_000}]})

        async def hr_gate(request):
            return dict(HR)

        async def must_not_post(*a, **k):  # pragma: no cover - tidak boleh sampai ke jurnal
            raise AssertionError("jurnal tidak boleh diposting")
        monkeypatch.setattr(runs, "_require_hr", hr_gate)
        monkeypatch.setattr(runs, "post_payroll_run", must_not_post)
        with pytest.raises(HTTPException) as ei:
            run(runs.finalize_run("r2", FakeRequest()))
        assert ei.value.status_code == 409 and "KSB-1" in ei.value.detail and "PR-1" in ei.value.detail
        assert db.rahaza_payroll_runs.docs[1]["status"] == "draft"


# ── Butir 5: cuti tanpa gaji lintas periode ──────────────────────────────────
class TestLwopLintasPeriode:
    def _seed(self, db):
        db.rahaza_leave_types.docs = [{"id": "lt-lwop", "name": "Cuti tanpa gaji", "unpaid": True, "active": True}]
        # Rabu 28 Okt – Kamis 5 Nov 2026: 3 hari kerja di Oktober + 4 hari kerja di November = 7
        db.rahaza_leave_requests.docs = [{
            "id": "lv1", "employee_id": "emp-a", "status": "approved", "leave_type_id": "lt-lwop",
            "from_date": "2026-10-28", "to_date": "2026-11-05", "duration_days": 9, "duration_working_days": 7}]

    def _lwop(self, slip):
        # 2026-11-06 (Tahap 2): cuti tanpa gaji kini satu aturan dengan alpa → baris 'absence'
        rows = [d for d in slip["deductions"] if d.get("type") == "absence"]
        return rows[0] if rows else None

    def test_hanya_hari_di_periode_yang_dipotong(self, db):
        self._seed(db)
        okt = self._lwop(run(shared._compute_payslip_for_employee(db, PROFILE, "2026-10-01", "2026-10-31", EMP_A)))
        nov = self._lwop(run(shared._compute_payslip_for_employee(db, PROFILE, "2026-11-01", "2026-11-30", EMP_A)))
        # Tahap 2: 6 hari kerja/minggu → 28–31 Okt (Rab–Sab) = 4 hari, 2–5 Nov = 4 hari (dulu Senin–Jumat 3 + 4)
        assert okt["days"] == 4 and nov["days"] == 4
        # pembagi = hari kerja periode (6 hari/minggu): Okt 2026 = 27, Nov 2026 = 25
        assert okt["divisor"] == 27 and okt["amount"] == round(3_000_000 * 4 / 27)
        assert nov["divisor"] == 25 and nov["amount"] == round(3_000_000 * 4 / 25)

    def test_libur_dan_setengah_hari(self):
        leaves = [{"from_date": "2026-11-02", "to_date": "2026-11-06"},
                  {"from_date": "2026-11-10", "to_date": "2026-11-10", "is_half_day": True}]
        # 2–6 Nov = 5 hari kerja, 4 Nov libur → 4; setengah hari 10 Nov → 0,5
        assert shared.lwop_days_in_period(leaves, date(2026, 11, 1), date(2026, 11, 30), {"2026-11-04"}) == 4.5
        assert shared.lwop_days_in_period(leaves, date(2026, 11, 5), date(2026, 11, 5), set()) == 1


# ── Butir 6: batal bayar gaji ────────────────────────────────────────────────
class TestBatalBayarGaji:
    def _seed(self, db, period_status):
        db.rahaza_payroll_runs.docs = [{"id": "r1", "run_number": "PR-1", "status": "finalized",
                                        "payment_status": "paid", "payment_gl_je_number": "JE-PAY"}]
        db.rahaza_journal_entries.docs = [{"id": "je-pay", "je_number": "JE-PAY", "source_module": "payroll_payment",
                                           "source_ref": "payrollpay:r1", "date": "2026-10-31", "status": "posted"}]
        db.rahaza_periods.docs = [{"period_code": "2026-10", "status": period_status}]

    @pytest.fixture(autouse=True)
    def _gate(self, monkeypatch):
        async def hr_gate(request):
            return dict(HR)
        monkeypatch.setattr(runs, "_require_hr", hr_gate)

    def test_periode_tutup_status_tetap_dibayar(self, db):
        self._seed(db, "closed")
        with pytest.raises(HTTPException) as ei:
            run(runs.void_payroll_payment_endpoint("r1", FakeRequest({"reason": "salah rekening"})))
        assert ei.value.status_code == 400 and "gagal" in ei.value.detail and "tetap sudah dibayar" in ei.value.detail
        assert db.rahaza_payroll_runs.docs[0]["payment_status"] == "paid"
        assert db.rahaza_journal_entries.docs[0]["status"] == "posted"

    def test_periode_terbuka_pembayaran_dibatalkan(self, db):
        self._seed(db, "open")
        out = run(runs.void_payroll_payment_endpoint("r1", FakeRequest({"reason": "salah rekening"})))
        assert out["payment_status"] == "void" and db.rahaza_journal_entries.docs[0]["status"] == "voided"


# ── Butir 7: kabar slip gaji ─────────────────────────────────────────────────
class TestKabarSlipGaji:
    def test_nominal_nyata_dan_tautan_slip(self, db, monkeypatch):
        db.rahaza_payroll_runs.docs = [{"id": "r1", "run_number": "PR-1", "status": "draft",
                                        "period_from": "2026-10-01", "period_to": "2026-10-31"}]
        db.rahaza_payslips.docs = [{"id": "slip-ani", "run_id": "r1", "employee_id": "emp-a", "gross_pay": 4_250_000.0,
                                    "deductions_total": 0.0, "net_pay": 4_250_000.0, "deductions": []}]
        sent = []

        async def hr_gate(request):
            return dict(HR)

        async def ok_post(*a, **k):
            return {"ok": True, "je_id": "je-1", "je_number": "JE-1"}

        async def capture(_db, **kw):
            sent.append(kw)
        import routes.rahaza_notifications as notif
        monkeypatch.setattr(runs, "_require_hr", hr_gate)
        monkeypatch.setattr(runs, "post_payroll_run", ok_post)
        monkeypatch.setattr(notif, "publish_notification", capture)
        run(runs.finalize_run("r1", FakeRequest()))
        assert len(sent) == 1
        assert "Rp 4.250.000" in sent[0]["message"] and "Rp 0" not in sent[0]["message"]
        assert sent[0]["link_module"] == "portal-payslip" and sent[0]["link_id"] == "slip-ani"
        assert sent[0]["target_user_ids"] == ["u-operator"]


# ── Butir 8 & 9: cuti ────────────────────────────────────────────────────────
def _year():
    from utils.waktu import wib_year
    return wib_year()


class TestCutiPortalSaya:
    def test_kartu_saldo_memuat_sisa_dan_jatah(self, db, login):
        db.users.docs = [{"id": "u-operator", "employee_id": "emp-a"}]
        db.rahaza_leave_types.docs = [{"id": "lt-ct", "name": "Cuti tahunan", "quota_default": 12, "active": True}]
        db.rahaza_leave_balances.docs = [
            {"id": "b1", "employee_id": "emp-a", "leave_type_id": "lt-ct", "year": _year(), "allocated": 12, "used": 3},
            {"id": "b0", "employee_id": "emp-a", "leave_type_id": "lt-ct", "year": _year() - 1, "allocated": 12, "used": 12},
        ]
        out = run(portal_ext.get_my_leave_balance(login("operator")))
        assert [(b["quota"], b["used"], b["remaining"]) for b in out["balances"]] == [(12, 3, 9)]
        s = _src("frontend", "src", "components", "erp", "PortalSayaCuti.jsx")
        assert "b.remaining" in s and "b.quota" in s

    def test_dashboard_sisa_cuti_tidak_minus(self, db, login, monkeypatch):
        async def linked(_db, uid):
            return {"id": uid}, {"id": "emp-a", "name": "Ani"}
        monkeypatch.setattr(portal_hr, "_get_linked_employee", linked)
        db.rahaza_leave_types.docs = [{"id": "lt-ct", "name": "Cuti tahunan", "code": "CT"}]
        db.rahaza_leave_balances.docs = [
            {"id": "b1", "employee_id": "emp-a", "leave_type_id": "lt-ct", "year": _year(), "allocated": 12, "used": 3}]
        out = run(portal_hr.get_dashboard(login("operator")))
        assert out["leave_balance"][0]["remaining"] == 9 and out["leave_balance"][0]["quota"] == 12

    @pytest.mark.parametrize("status", ["pending_approval", "pending_hr_approval"])
    def test_batalkan_pengajuan_menunggu(self, db, login, monkeypatch, status):
        import utils.notif_unified as nu

        async def no_resolve(*a, **k):
            return 0
        monkeypatch.setattr(nu, "resolve_for_source", no_resolve)
        db.users.docs = [{"id": "u-operator", "employee_id": "emp-a"}]
        db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "emp-a", "status": status,
                                          "leave_type_id": "lt-ct", "from_date": "2026-11-20", "to_date": "2026-11-21",
                                          "duration_days": 2}]
        db.approval_requests.docs = [{"id": "ar1", "type": "leave", "ref_id": "lv1", "status": "pending"}]
        out = run(leave_mod.cancel_leave("lv1", login("operator", {"reason": "Batal berangkat"})))
        assert out["status"] == "cancelled" and out["cancel_reason"] == "Batal berangkat"
        assert db.approval_requests.docs[0]["status"] == "cancelled"
        assert db.rahaza_leave_balances.docs == []

    def test_batalkan_pengajuan_orang_lain_ditolak(self, db, login):
        db.users.docs = [{"id": "u-operator", "employee_id": "emp-a"}]
        db.rahaza_leave_requests.docs = [{"id": "lv2", "employee_id": "emp-b", "status": "pending_approval",
                                          "from_date": "2026-11-20", "to_date": "2026-11-20"}]
        assert _status(leave_mod.cancel_leave("lv2", login("operator", {}))) == 403
        assert db.rahaza_leave_requests.docs[0]["status"] == "pending_approval"

    def test_layar_menampilkan_batalkan_untuk_kedua_status_menunggu(self):
        s = _src("frontend", "src", "components", "erp", "PortalSayaCuti.jsx")
        assert "['pending_approval', 'pending_hr_approval'].includes(lv.status)" in s


class TestSaldoCutiTidakMinus:
    def _seed(self, db, days):
        db.rahaza_leave_types.docs = [{"id": "lt-ct", "name": "Cuti tahunan", "quota_default": 12, "active": True}]
        db.rahaza_leave_requests.docs = [{"id": "lv1", "employee_id": "emp-a", "status": "pending_approval",
                                          "leave_type_id": "lt-ct", "from_date": f"{_year()}-12-01",
                                          "to_date": f"{_year()}-12-{days:02d}", "duration_days": days,
                                          "approval_level_required": 1, "current_approval_level": 1}]

    def test_tanpa_dokumen_saldo_tetap_diperiksa(self, db, login):
        self._seed(db, 15)
        with pytest.raises(HTTPException) as ei:
            run(leave_mod.approve_leave("lv1", login("hr")))
        # Tahap 2 (2026-11-06): durasi = hari KERJA (6 hari/minggu) — 1–15 Des 2026 memuat 2 hari Minggu → 13 hari.
        from core import workdays
        n = len(workdays.working_days_between(f"{_year()}-12-01", f"{_year()}-12-15", workdays.off_weekdays_for(6), set()))
        assert ei.value.status_code == 400 and "Sisa: 12 hari" in ei.value.detail and f"diminta: {n} hari" in ei.value.detail
        assert db.rahaza_leave_requests.docs[0]["status"] == "pending_approval"
        assert db.rahaza_leave_balances.docs == []

    def test_cukup_disetujui_dan_saldo_terpakai(self, db, login):
        self._seed(db, 5)
        out = run(leave_mod.approve_leave("lv1", login("hr")))
        assert out["status"] == "approved"
        bal = db.rahaza_leave_balances.docs[0]
        assert bal["allocated"] == 12 and bal["used"] == 5

    def test_snapshot_dari_jatah_tanpa_menulis(self, db):
        db.rahaza_leave_types.docs = [{"id": "lt-x", "quota_default": 6}]
        snap = run(balances.balance_snapshot(db, "emp-a", "lt-x", 2026))
        assert snap == {"allocated": 6.0, "used": 0.0, "remaining": 6.0, "exists": False}
        assert db.rahaza_leave_balances.docs == []


# ── Butir 10: rekap absensi HR ───────────────────────────────────────────────
class TestRekapAbsensiTidakTerpotong:
    def _seed(self, db):
        db.rahaza_employees.docs = [{"id": f"e{i:02d}", "name": f"K{i}", "employee_code": f"E{i:02d}", "active": True}
                                    for i in range(25)]
        rows = []
        for i in range(25):
            for d in range(1, 32):
                rows.append({"id": f"a{i}-{d}", "employee_id": f"e{i:02d}", "date": f"2026-10-{d:02d}",
                             "status": "alfa" if d == 31 else "hadir", "is_late": d == 1})
        db.rahaza_attendance_events.docs = rows   # 775 record > batas lama 500

    def test_rekap_bulanan_lengkap(self, db, login):
        self._seed(db)
        out = run(hr_reports.get_attendance_summary(login("hr"), from_date="2026-10-01", to_date="2026-10-31"))
        agg = out["aggregates"]
        assert agg["total_employees"] == 25 and agg["total_hadir"] == 25 * 30 and agg["total_alfa"] == 25
        assert agg["total_terlambat"] == 25
        assert all(s["recorded_days"] == 31 and s["missing_days"] == 0 for s in out["summary"])
        assert sum(c["hadir"] for c in out["chart_data"]) == 750 and out["chart_data"][30]["alfa"] == 25

    def test_validasi_payroll_tanpa_peringatan_palsu(self, db, login):
        self._seed(db)
        out = run(hr_reports.validate_attendance_for_payroll(login("hr"), period_from="2026-10-01",
                                                              period_to="2026-10-31"))
        assert out["summary"]["total_warnings"] == 0
        assert {s["recorded_days"] for s in out["attendance_stats"]} == {31}


# ── Butir 11: selfie ditolak HR ──────────────────────────────────────────────
def _att(day, **kw):
    base = {"id": f"ev-{day}", "employee_id": "emp-a", "date": f"2026-10-{day:02d}", "status": "hadir",
            "hours_worked": 8.0, "net_hours_worked": 8.0, "overtime_hours": 0, "late_minutes": 0}
    base.update(kw)
    return base


class TestSelfieDitolak:
    def _seed(self, db):
        db.rahaza_attendance_events.docs = [
            _att(1), _att(2),
            _att(5, status="alfa", approval_status="rejected", late_minutes=40, overtime_hours=3),   # ditolak HR
            _att(6, approval_status="pending", hours_worked=7.0, net_hours_worked=7.0),              # menunggu review
        ]

    def test_payroll_tidak_menghitung_hadir_jam_lembur_terlambat(self, db):
        self._seed(db)
        prof = {"employee_id": "emp-a", "pay_scheme": "hourly", "base_rate": 10_000, "overtime_rate": 20_000}
        slip = run(shared._compute_payslip_for_employee(db, prof, "2026-10-01", "2026-10-31", EMP_A))
        assert slip["days_hadir"] == 3 and slip["net_hours_worked"] == 23.0    # 8 + 8 + 7 (menunggu = hadir)
        assert slip["earnings"][0]["amount"] == 230_000
        assert slip["late_minutes"] == 0 and slip["overtime_amount"] == 0
        assert slip["source_refs"]["attendance_rejected_count"] == 1

    def test_rekap_jam_absensi_dan_portal_saya(self, db, login, monkeypatch):
        self._seed(db)
        rows = run(att.attendance_summary(login("hr"), from_="2026-10-01", to="2026-10-31"))
        assert rows[0]["total_hours"] == 23.0 and rows[0]["total_overtime"] == 0
        assert rows[0]["days_hadir"] == 3 and rows[0]["days_alfa"] == 1

        async def linked(_db, uid):
            return {"id": uid}, {"id": "emp-a", "name": "Ani"}
        monkeypatch.setattr(rahaza_self, "_get_employee_for_user", linked)
        mine = run(rahaza_self.self_attendance(login("operator"), from_="2026-10-01", to="2026-10-31", limit=60))
        assert mine["total_hours_worked"] == 23.0 and mine["summary"]["alfa"] == 1

    def test_hr_menandai_hadir_lagi_dihitung(self):
        assert policy.attendance_counts({"approval_status": "pending", "status": "hadir"})
        assert not policy.attendance_counts({"approval_status": "rejected", "status": "alfa"})
        assert policy.attendance_counts({"approval_status": "rejected", "status": "hadir"})
        assert policy.attendance_counts({})


def test_tanggal_uji_konsisten():
    # Penjaga hitung tangan di atas: 28 Okt 2026 = Rabu, 5 Nov 2026 = Kamis.
    assert date(2026, 10, 28).weekday() == 2 and date(2026, 11, 5).weekday() == 3
    assert date(2026, 10, 28) + timedelta(days=8) == date(2026, 11, 5)
