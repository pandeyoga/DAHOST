"""Uji HERMETIK tahap 4 (2026-11-02) — keputusan owner No.54(a): tanggal operasional = WIB.

Jam dibekukan pada **2026-11-01 00:30 WIB** (= 2026-10-31 17:30 UTC): jendela 00:00–06:59 WIB
di mana `datetime.now(timezone.utc).date()/.strftime("%Y-%m")` masih menunjuk hari/bulan LALU.
Pembekuan dilakukan di SSOT `utils.waktu.now_wib` — semua helper (`today_wib`, `wib_year`,
`fmt_wib`, `wib_date_str`, `wib_day_bounds_utc`) membacanya, jadi uji ini membuktikan jalur
NYATA memakai SSOT, bukan `date.today()`/jam UTC.

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_s4_tanggal_wib.py -q
"""
import asyncio
import os
import sys
import types
from datetime import date, datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
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

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402

import utils.waktu as waktu  # noqa: E402

run = asyncio.run

# 2026-11-01 00:30 WIB — masih 31 Oktober menurut UTC.
BEKU = datetime(2026, 11, 1, 0, 30, tzinfo=waktu.WIB)


@pytest.fixture
def jam(monkeypatch):
    """Bekukan jam WIB di SSOT; kembalikan setter untuk mengganti instan."""
    state = {"t": BEKU}
    monkeypatch.setattr(waktu, "now_wib", lambda: state["t"])

    def atur(t):
        state["t"] = t
    return atur


# ═══════════════════════ 0. sanity: jendela yang dulu salah ═══════════════════════
def test_jendela_utc_memang_masih_bulan_lalu():
    """Menunjukkan bug lama: pada instan ini jam UTC masih Oktober."""
    utc = BEKU.astimezone(timezone.utc)
    assert utc.strftime("%Y-%m") == "2026-10" and utc.date() == date(2026, 10, 31)


def test_ssot_waktu_memakai_wib(jam):
    assert waktu.today_wib() == date(2026, 11, 1)
    assert waktu.fmt_wib("%Y-%m") == "2026-11"
    assert waktu.wib_date_str() == "2026-11-01"
    assert waktu.wib_year() == 2026 and waktu.wib_month() == 11
    mulai, selesai = waktu.wib_day_bounds_utc()
    assert mulai == datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc)
    assert selesai == datetime(2026, 11, 1, 17, 0, tzinfo=timezone.utc)


# ═══════════════════════ 1. kasbon: periode potong & statistik bulan ini ═══════════════════════
MAPPINGS = {"employee_loan_disbursement": {"debit_employee_loan_receivable": "1-1320", "credit_cash": "1-1201"}}
FIN = {"id": "u-fin", "role": "staff_keuangan", "name": "Fatimah", "email": "fin@x"}
HR = {"id": "u-hr", "role": "hr", "name": "Brenda HR", "email": "hr@x"}


@pytest.fixture
def kas_env(monkeypatch, jam):
    import routes.dewi_kasbon as kas
    import routes.rahaza_posting as posting
    import routes.rahaza_posting_profiles as profiles_mod

    db = FakeDB()
    db.rahaza_coa_accounts.docs = [
        {"code": "1-1200", "name": "Bank", "parent_code": None, "is_group": True, "active": True},
        {"code": "1-1201", "name": "Bank BCA", "parent_code": "1-1200", "is_group": False, "active": True},
        {"code": "1-1320", "name": "Piutang Karyawan", "parent_code": None, "is_group": False, "active": True},
    ]
    db.rahaza_cash_accounts.docs = [
        {"id": "ca-bca", "code": "1-1201", "name": "Bank BCA", "gl_account_code": "1-1201", "type": "bank", "active": True}]
    db.rahaza_employees.docs = [{"id": "emp-a", "name": "Ani", "active": True, "user_id": "u-ani"}]
    db.users.docs = [{"id": "u-ani", "role": "tim_packing", "email": "ani@x", "employee_id": "emp-a"}]
    jes = []

    async def fake_je(dbx, je_date, memo, source_module, source_ref, lines_raw, user, **kw):
        jes.append({"date": je_date, "source_ref": source_ref})
        return {"ok": True, "je_id": f"je-{len(jes)}", "je_number": f"JE-{len(jes):04d}"}

    async def fake_mapping(dbx, event_type):
        return dict(MAPPINGS.get(event_type, {}))

    monkeypatch.setattr(posting, "_create_posted_je", fake_je)
    monkeypatch.setattr(profiles_mod, "get_mapping", fake_mapping)
    return types.SimpleNamespace(kas=kas, db=db, jes=jes)


def test_kasbon_cair_tanpa_tanggal_periode_potong_bulan_wib(kas_env):
    """Contoh nyata audit: cair tgl 1 pukul 00:30 WIB → periode potong '2026-11', BUKAN '2026-10'."""
    db = kas_env.db
    db.dewi_kasbon_requests.docs.append({"id": "ka", "employee_id": "emp-a", "type": "kasbon", "status": "hr_approved",
                                         "amount": 500000.0, "outstanding_balance": 500000.0, "request_number": "KSB-A"})
    out = run(kas_env.kas.finance_disburse("ka", FakeRequest({"cash_account_id": "ca-bca"}), db=db, user=FIN))
    assert out["ok"]
    req = db.dewi_kasbon_requests.docs[0]
    assert req["disbursement_date"] == "2026-11-01"
    assert req["deduction_start_period"] == "2026-11"
    assert kas_env.jes[-1]["date"] == date(2026, 11, 1)


def test_kasbon_statistik_bulan_ini_menurut_wib(kas_env):
    db = kas_env.db
    db.dewi_kasbon_requests.docs = [
        # 2026-11-01 01:00 WIB (tersimpan UTC 31 Okt) → bulan INI
        {"id": "k1", "status": "submitted", "amount": 100.0, "created_at": "2026-10-31T18:00:00+00:00"},
        # 2026-10-31 23:00 WIB → bulan LALU
        {"id": "k2", "status": "submitted", "amount": 200.0, "created_at": "2026-10-31T16:00:00+00:00"},
        # datetime naif (data seed lama, UTC) 2026-10-31 20:00 UTC = 1 Nov 03:00 WIB → bulan INI
        {"id": "k3", "status": "submitted", "amount": 400.0, "created_at": datetime(2026, 10, 31, 20, 0)},
    ]
    out = run(kas_env.kas.kasbon_stats(db=db, user=HR))
    assert out["stats"]["this_month_requests"] == 2
    assert out["stats"]["this_month_amount"] == 500.0


# ═══════════════════════ 2. kueri "hari ini" pada timestamp UTC ═══════════════════════
def test_qc_fail_rate_hari_ini_memakai_batas_hari_wib(jam):
    import routes.rahaza_next_actions as na
    db = FakeDB()
    pagi = "2026-10-31T17:45:00+00:00"   # 00:45 WIB hari INI
    db.rahaza_wip_events.docs = (
        [{"event_type": "qc_pass", "qty": 9, "timestamp": pagi}] * 2
        + [{"event_type": "qc_fail", "qty": 2, "timestamp": pagi}]
        # 23:30 WIB KEMARIN — tidak boleh ikut (dulu dihitung krn tanggal UTC-nya sama)
        + [{"event_type": "qc_fail", "qty": 50, "timestamp": "2026-10-31T16:30:00+00:00"}]
    )
    out = run(na.rule_qc_fail_rate_today(db, "production"))
    # hanya 20 pcs pagi ini (2 gagal = 10%); 50 pcs kemarin malam tidak ikut
    assert out is not None and out["count"] == 2 and out["title"].endswith("10.0%")


def test_shift_aktif_karyawan_memakai_tanggal_wib(monkeypatch, jam):
    import routes.hr_shifts as hs
    seen = {}

    async def fake_shift(db, employee_id, day):
        seen["day"] = day
        return {"shift": "pagi"}

    async def noop(request):
        return {"id": "u"}

    monkeypatch.setattr(hs, "get_employee_shift", fake_shift)
    monkeypatch.setattr(hs, "require_auth", noop)
    monkeypatch.setattr(hs, "get_db", lambda: None)
    run(hs.employee_active_shift(FakeRequest(), "emp-a"))
    assert seen["day"] == "2026-11-01"      # dulu '2026-10-31' (tanggal UTC)


def test_laporan_harian_tanggal_bawaan_wib(jam):
    from routes.dewi_phase7_reports import _today_str
    assert _today_str() == "2026-11-01"
    mulai, selesai = waktu.wib_day_bounds_utc(date.fromisoformat(_today_str()))
    assert mulai.isoformat() == "2026-10-31T17:00:00+00:00" and selesai - mulai == timedelta(days=1)


# ═══════════════════════ 3. nomor dokumen & periode tahun ═══════════════════════
def test_nomor_invoice_maklon_tahun_wib(monkeypatch, jam):
    import routes.dewi_maklon_pos as pos
    jam(datetime(2027, 1, 1, 0, 30, tzinfo=waktu.WIB))   # UTC masih 31 Des 2026
    seen = {}

    async def fake_gen(db, coll, field, prefix, width, **kw):
        seen["prefix"] = prefix
        return f"{prefix}0001"

    monkeypatch.setattr(pos, "gen_prefixed_number", fake_gen)
    assert run(pos._next_ar_invoice_number(None)) == "INV-MKL-2027-0001"
    assert seen["prefix"] == "INV-MKL-2027-"


def test_nomor_kode_harian_helpers_tanggal_wib(jam):
    from utils import helpers
    assert helpers._today_iso() == "2026-11-01"
    db = FakeDB()
    assert run(helpers._next_code(db, "CUT", "x", "code")) == "CUT-20261101-001"


def test_carry_forward_cuti_1_januari_pagi_wib(monkeypatch, jam):
    try:
        import utils.scheduler as sch
    except ImportError:  # pragma: no cover
        pytest.skip("apscheduler tidak tersedia")
    jam(datetime(2027, 1, 1, 1, 0, tzinfo=waktu.WIB))     # job 01:00 WIB = 31 Des 18:00 UTC
    db = FakeDB()
    db.rahaza_leave_types.docs = [{"id": "lt1", "name": "Cuti Tahunan", "active": True,
                                   "quota_default": 12, "max_carry_days": 5}]
    db.rahaza_employees.docs = [{"id": "e1", "name": "Ani", "active": True}]
    db.rahaza_leave_balances.docs = [{"id": "b26", "employee_id": "e1", "leave_type_id": "lt1",
                                      "year": 2026, "allocated": 12, "used": 4}]
    monkeypatch.setattr(sch, "get_db", lambda: db)
    run(sch.job_leave_carry_forward())
    baru = [b for b in db.rahaza_leave_balances.docs if b.get("year") == 2027]
    assert len(baru) == 1 and baru[0]["carry_from_year"] == 2026 and baru[0]["allocated"] == 17


# ═══════════════════════ 4. helper lokal = delegasi SSOT (tanpa duplikasi) ═══════════════════════
def test_helper_lokal_mendelegasi_ke_ssot(monkeypatch, jam):
    from core import marketing_cycle, scan_out
    from core import opname_engine as eng
    import routes.rahaza_payroll_shared as shared
    import routes.marketing_orders_routes as mor

    # modul yang mengimpor `now_wib` langsung → patch nama di modulnya (cara modul memanggilnya)
    for mod in (marketing_cycle, mor):
        monkeypatch.setattr(mod, "now_wib", lambda: BEKU)
    assert scan_out.today_str() == "2026-11-01"
    assert shared._today_wib() == date(2026, 11, 1)
    assert shared.WIB is waktu.WIB and marketing_cycle.WIB is waktu.WIB
    assert marketing_cycle.today_wib() == BEKU
    assert mor._now_wib_wall() == datetime(2026, 11, 1, 0, 30)          # jam dinding WIB tanpa tzinfo
    assert mor._wib_day_start() == datetime(2026, 11, 1, 0, 0)
    assert eng.wib_date(datetime(2026, 10, 31, 17, 30, tzinfo=timezone.utc)) == "2026-11-01"
    assert not hasattr(__import__("core.accessory_valuation", fromlist=["x"]), "_jakarta_date_str")


# ── 2026-11-02 integrasi tahap 4: tanggal dari timestamp tersimpan & pembanding bertipe benar ──
def test_wib_date_of_membaca_instan_utc_sebagai_tanggal_wib():
    from datetime import datetime, timezone, date
    from utils.waktu import wib_date_of
    assert wib_date_of(datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)) == "2026-11-01"
    assert wib_date_of(datetime(2026, 10, 31, 23, 30)) == "2026-11-01"          # naive = UTC
    assert wib_date_of("2026-10-31T23:30:00+00:00") == "2026-11-01"
    assert wib_date_of("2026-10-31T23:30:00Z") == "2026-11-01"
    assert wib_date_of("2026-10-31") == "2026-10-31"                             # sudah tanggal kalender
    assert wib_date_of(date(2026, 10, 31)) == "2026-10-31"
    assert wib_date_of(None) == "" and wib_date_of("") == ""
    assert wib_date_of("bukan tanggal") == ""


def test_cmt_lifecycle_date_key_pakai_wib():
    from datetime import datetime, timezone
    import routes.dewi_cmt_lifecycle as lc
    assert lc._date_key(datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)) == "2026-11-01"
    assert lc._date_key(None) == ""


def test_filter_tanggal_dashboard_memakai_datetime_bukan_string():
    """Tiga kueri yang dulu membandingkan field datetime BSON dengan STRING (selalu 0)."""
    import inspect
    import routes.fulfillment as ff
    import routes.rahaza_next_actions as na
    import routes.dewi_procurement as pr
    src_ff = inspect.getsource(ff)
    assert '{"dispatched_at": {"$gte": _day0}}' in src_ff
    src_na = inspect.getsource(na.rule_qc_fail_rate_today)
    assert '{"timestamp": {"$gte": start}}' in src_na
    assert "start = wib_day_bounds_utc()[0].isoformat()" not in src_na
    src_pr = inspect.getsource(pr)
    assert 'month_start = wib_day_bounds_utc(today_wib().replace(day=1))[0]' in src_pr


def test_pengingat_jatuh_tempo_dibanding_jam_dinding_wib():
    import inspect
    import routes.dewi_portal_saya_workspace as ws
    src = inspect.getsource(ws.get_due_reminders)
    assert 'fmt_wib("%Y-%m-%dT%H:%M")' in src and "_now_iso()" not in src
