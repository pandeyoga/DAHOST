"""Uji regresi HERMETIK paket W2-E (2026-11-02) — keputusan owner K22/K23/K24/K25/K26/K34/K38.

Tanpa server/Mongo (FakeDB). Angka di komentar dihitung tangan.
  K22/K23 BPJS bisa diatur + kepesertaan per program · K24 lembur cadangan 1/173 + tanpa hitung dobel
  K25 pemisahan tugas uang keluar + batas kasbon · K26 uang muka kas kecil 1-1610 + pertanggungjawaban
  K34 penyesuaian slip (± pendapatan/potongan) + batal run final · K38 peran credit_other_deduction tampil
"""
import asyncio
import os
import re
import sys
import types

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

import routes.dewi_kasbon as kas  # noqa: E402
import routes.employee_expense_claims as eec  # noqa: E402
import routes.employee_travel_requests as etr  # noqa: E402
import routes.employee_travel_settlements as ets  # noqa: E402
import routes.rahaza_master as master  # noqa: E402
import routes.rahaza_payroll_payslips as slips_mod  # noqa: E402
import routes.rahaza_payroll_runs as runs  # noqa: E402
import routes.rahaza_payroll_settings as pset  # noqa: E402
import routes.rahaza_payroll_shared as shared  # noqa: E402
import routes.rahaza_payroll_tax as tax  # noqa: E402
import routes.rahaza_petty_cash as pc  # noqa: E402
import routes.rahaza_posting as posting  # noqa: E402
import routes.rahaza_posting_profiles as profiles_mod  # noqa: E402

run = asyncio.run

HR = {"id": "u-hr", "role": "hr", "name": "Brenda HR", "email": "hr@x"}
FIN = {"id": "u-fin", "role": "staff_keuangan", "name": "Fatimah", "email": "fin@x"}
OWNER = {"id": "u-own", "role": "owner", "name": "Owner", "email": "own@x"}
ANI = {"id": "u-ani", "role": "tim_packing", "name": "Ani", "email": "ani@x"}

PAYROLL_FIN_MAP = {
    "debit_salary_expense": "6-2100", "credit_salary_payable": "2-1200", "credit_tax_pph21": "2-1301",
    "credit_bpjs_payable": "2-1500", "credit_bpjs_kes_payable": "2-1501", "credit_bpjs_tk_payable": "2-1502",
    "debit_bpjs_kes_employer_expense": "6-3200", "debit_bpjs_tk_employer_expense": "6-3300",
    "credit_other_deduction": "4-9000",
}
MAPPINGS = {
    "payroll_finalize": PAYROLL_FIN_MAP,
    "payroll_payment": {"credit_bank_default": "1-1201", "debit_salary_payable": "2-1200"},
    "employee_loan_repayment_payroll": {"debit_salary_payable": "2-1200", "credit_employee_loan_receivable": "1-1320"},
    "employee_loan_disbursement": {"debit_employee_loan_receivable": "1-1320", "credit_cash": "1-1201"},
    "petty_cash_replenish": {"debit_petty_cash": "1-1101", "credit_bank_default": "1-1201"},
    "petty_cash_expense": {"debit_expense_default": "6-2400", "credit_petty_cash": "1-1101",
                           "debit_employee_advance": "1-1610"},
    "expense": {"credit_cash_default": "1-1201"},
}


def _coa(code, name, parent=None, group=False):
    return {"code": code, "name": name, "parent_code": parent, "is_group": group, "active": True}


def _err(coro):
    with pytest.raises(HTTPException) as ei:
        run(coro)
    return ei.value


def _src(*parts):
    p = os.path.join(REPO, *parts)
    if not os.path.exists(p):
        pytest.skip(f"sumber frontend tidak tersedia: {p}")
    return open(p, encoding="utf-8").read()


def _net(lines):
    out = {}
    for ln in lines:
        out[ln["account_code"]] = round(out.get(ln["account_code"], 0) + float(ln.get("debit") or 0)
                                        - float(ln.get("credit") or 0), 2)
    return out


@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    db.rahaza_coa_accounts.docs = [
        _coa("1-1100", "Kas", group=True), _coa("1-1101", "Kas Kecil", "1-1100"),
        _coa("1-1200", "Bank", group=True), _coa("1-1201", "Bank BCA", "1-1200"),
        _coa("1-1320", "Piutang Karyawan"), _coa("1-1610", "Uang Muka Karyawan"),
        _coa("2-1200", "Hutang Gaji"), _coa("2-1500", "Hutang BPJS"), _coa("2-1501", "Hutang BPJS Kes"),
        _coa("2-1502", "Hutang BPJS TK"), _coa("6-2100", "Gaji"), _coa("6-2900", "Beban Umum"),
        _coa("6-3200", "BPJS Kes (Employer)"), _coa("6-3300", "BPJS TK (Employer)"), _coa("6-3400", "Perjalanan Dinas"),
    ]
    db.rahaza_cash_accounts.docs = [
        {"id": "ca-kk", "code": "1-1101", "name": "Kas Kecil", "gl_account_code": "1-1101", "active": True},
        {"id": "ca-bca", "code": "1-1201", "name": "Bank BCA", "gl_account_code": "1-1201", "active": True},
    ]
    db.rahaza_employees.docs = [
        {"id": "emp-a", "name": "Ani", "active": True, "user_id": "u-ani"},
        {"id": "emp-hr", "name": "Brenda", "active": True, "user_id": "u-hr"},
    ]
    jes = []

    async def fake_je(dbx, je_date, memo, source_module, source_ref, lines_raw, user, **kw):
        if getattr(fake_je, "fail", None):
            return {"ok": False, "error": fake_je.fail}
        n = len(jes) + 1
        doc = {"id": f"je-{n}", "je_number": f"JE-{n:04d}", "date": je_date.isoformat(), "status": "posted",
               "source_module": source_module, "source_ref": source_ref, "memo": memo,
               "lines": [dict(x) for x in lines_raw if float(x.get("debit") or 0) or float(x.get("credit") or 0)]}
        jes.append(doc)
        await dbx.rahaza_journal_entries.insert_one(doc)
        return {"ok": True, "je_id": doc["id"], "je_number": doc["je_number"]}
    fake_je.fail = None

    async def fake_mapping(dbx, event_type):
        return dict(MAPPINGS.get(event_type, {}))

    async def noop(*a, **k):
        return None

    actor = {"user": dict(HR)}

    async def gate(request):
        return dict(actor["user"])

    monkeypatch.setattr(posting, "_create_posted_je", fake_je)
    monkeypatch.setattr(posting, "get_mapping", fake_mapping)
    monkeypatch.setattr(profiles_mod, "get_mapping", fake_mapping)
    monkeypatch.setattr(pc, "_create_posted_je", fake_je)
    monkeypatch.setattr(pc, "get_mapping", fake_mapping)
    for mod in (runs, slips_mod, pset, etr, ets, eec, pc):
        monkeypatch.setattr(mod, "get_db", lambda: db)
        monkeypatch.setattr(mod, "log_activity", noop)
    for mod in (runs, slips_mod, pset):
        monkeypatch.setattr(mod, "_require_hr", gate)
    monkeypatch.setattr(runs, "require_auth", gate)
    import core.bulk_approve as cba
    monkeypatch.setattr(cba, "log_activity", noop)
    return types.SimpleNamespace(db=db, jes=jes, fake_je=fake_je, actor=actor)


# ═══ K22/K23 — BPJS ═══════════════════════════════════════════════════════════
class TestKepesertaanBpjs:
    def test_data_lama_nomor_tk_saja_tidak_dipotong_kes(self):
        p = tax.resolve_bpjs_programs({"bpjs_ketenagakerjaan_number": "123"})
        assert p == {"kes": False, "jht": True, "jp": True, "jkk_jkm": True}
        assert tax.resolve_bpjs_programs({"bpjs_kesehatan_number": "9"}) == {
            "kes": True, "jht": False, "jp": False, "jkk_jkm": False}
        assert tax.resolve_bpjs_programs({"bpjs_kesehatan_number": "9", "bpjs_ketenagakerjaan_number": "1",
                                          "bpjs_programs": {"kes": True}}) == {
            "kes": True, "jht": False, "jp": False, "jkk_jkm": False}

    def test_hitung_tangan_tarif_bawaan(self):
        # dasar 2.600.000: Kes 1%=26.000 / 4%=104.000 ; JHT 2%=52.000 / 3,7%=96.200 ; JP 1%=26.000 / 2%=52.000
        # JKK very_low 0,24%=6.240 ; JKM 0,3%=7.800 → TK perusahaan 162.240, total perusahaan 266.240
        b = tax.compute_bpjs(2_600_000, programs={"kes": True, "jht": True, "jp": True, "jkk_jkm": True}, cfg={})
        assert (b["kes_emp"], b["kes_comp"], b["jht_emp"], b["jht_comp"]) == (26_000, 104_000, 52_000, 96_200)
        assert (b["jp_emp"], b["jp_comp"], b["jkk_comp"], b["jkm_comp"]) == (26_000, 52_000, 6_240, 7_800)
        assert (b["kes_company"], b["tk_company"], b["total_company"]) == (104_000, 162_240, 266_240)

    def test_setelan_kelas_risiko_dan_tarif(self):
        # kelas 'low' 0,54% × 2.600.000 = 14.040 ; tarif Kes karyawan 2% × 2.600.000 = 52.000
        b = tax.compute_bpjs(2_600_000, programs={"kes": True, "jkk_jkm": True},
                             cfg={"jkk_risk_tier": "low", "rates": {"kes_emp": 0.02}})
        assert b["jkk_comp"] == 14_040 and b["kes_emp"] == 52_000 and b["jht_emp"] == 0

    def test_mesin_slip_pemegang_nomor_tk(self, env):
        # Tutut: pokok 2.500.000 + Tunj. Jabatan 100.000 (upah tetap) = 2.600.000 → JHT 52.000 + JP 26.000 = 78.000
        env.db.da_payroll_allowances.docs = [{"is_active": True, "applicable_to": "all", "name": "Tunj. Jabatan",
                                              "calc_type": "fixed", "amount": 100_000, "is_fixed_wage": True}]
        prof = {"employee_id": "emp-t", "pay_scheme": "monthly", "base_rate": 2_500_000, "overtime_rate": 0}
        emp = {"id": "emp-t", "name": "Tutut", "bpjs_ketenagakerjaan_number": "12345"}
        s = run(shared._compute_payslip_for_employee(env.db, prof, "2026-10-01", "2026-10-31", emp))
        types_ = {d["type"]: d["amount"] for d in s["deductions"]}
        assert "bpjs_kesehatan" not in types_ and types_ == {"bpjs_jht": 52_000, "bpjs_jp": 26_000}
        assert s["gross_pay"] == 2_600_000 and s["net_pay"] == 2_522_000
        assert s["bpjs_employer"]["kes_total"] == 0 and s["bpjs_employer"]["tk_total"] == 162_240

    def test_saklar_jurnal_hanya_owner(self, env):
        env.db.rahaza_payroll_settings.docs.append({"key": "bpjs"})   # FakeDB tanpa upsert
        env.actor["user"] = dict(HR)
        e = _err(pset.set_bpjs(FakeRequest({"employer_contribution_journal": True})))
        assert e.status_code == 403
        out = run(pset.set_bpjs(FakeRequest({"jkk_risk_tier": "low"})))   # tarif boleh oleh HR
        assert out["settings"]["jkk_risk_tier"] == "low" and out["settings"]["employer_contribution_journal"] is False
        env.actor["user"] = dict(OWNER)
        out = run(pset.set_bpjs(FakeRequest({"employer_contribution_journal": True})))
        assert out["settings"]["employer_contribution_journal"] is True

    def test_form_karyawan_normalisasi(self):
        assert master._bpjs_programs_field({"bpjs_programs": {"kes": 1, "jp": True}}) == {
            "bpjs_programs": {"kes": True, "jht": False, "jp": True, "jkk_jkm": False}}
        assert master._bpjs_programs_field({}) == {}
        with pytest.raises(HTTPException):
            master._bpjs_programs_field({"bpjs_programs": "kes"})


def _final_run_with_bpjs(db, journal: bool):
    db.rahaza_payroll_runs.docs.append({"id": "rb", "run_number": "PR-B", "status": "draft",
                                        "period_from": "2026-10-01", "period_to": "2026-10-31"})
    db.rahaza_payslips.docs.append({
        "id": "sb", "run_id": "rb", "employee_id": "emp-t", "gross_pay": 2_600_000.0, "deductions_total": 104_000.0,
        "net_pay": 2_496_000.0, "deductions": [{"type": "bpjs_kesehatan", "amount": 26_000},
                                              {"type": "bpjs_jht", "amount": 52_000}, {"type": "bpjs_jp", "amount": 26_000}],
        "bpjs_employer": {"kes_total": 104_000, "tk_total": 162_240}})
    db.rahaza_payroll_settings.docs.append({"key": "bpjs", "employer_contribution_journal": journal})


class TestJurnalDanBayarBpjs:
    def test_finalisasi_saklar_menyala(self, env):
        _final_run_with_bpjs(env.db, journal=True)
        out = run(runs.finalize_run("rb", FakeRequest()))
        assert out["status"] == "finalized" and out["bpjs_employer_totals"] == {"kes": 104_000, "tk": 162_240, "total": 266_240}
        lines = env.jes[0]["lines"]
        # Dr 6-2100 2.600.000 + 104.000 + 162.240 = 2.866.240 = Cr 2.496.000 + 26.000 + 78.000 + 104.000 + 162.240
        assert sum(x["debit"] for x in lines) == sum(x["credit"] for x in lines) == 2_866_240
        net = _net(lines)
        assert net == {"6-2100": 2_600_000, "2-1200": -2_496_000, "2-1501": -130_000, "2-1502": -240_240,
                       "6-3200": 104_000, "6-3300": 162_240}

    def test_finalisasi_saklar_mati_tanpa_beban_perusahaan(self, env):
        _final_run_with_bpjs(env.db, journal=False)
        run(runs.finalize_run("rb", FakeRequest()))
        net = _net(env.jes[0]["lines"])
        assert "6-3200" not in net and "6-3300" not in net
        assert net["2-1501"] == -26_000 and net["2-1502"] == -78_000

    def test_bayar_per_lembaga(self, env):
        _final_run_with_bpjs(env.db, journal=True)
        run(runs.finalize_run("rb", FakeRequest()))
        out = run(runs.pay_bpjs("rb", FakeRequest({"agency": "kes", "cash_account_id": "ca-bca",
                                                   "payment_date": "2026-11-10"})))
        je = env.jes[-1]
        # Kes: karyawan 26.000 + perusahaan 104.000 = 130.000
        assert je["source_ref"] == "bpjspay:rb:kes" and je["date"] == "2026-11-10"
        assert _net(je["lines"]) == {"2-1501": 130_000, "1-1201": -130_000}
        assert out["bpjs_payment_status"] == "partial"
        assert _err(runs.pay_bpjs("rb", FakeRequest({"agency": "kes"}))).status_code == 400
        out = run(runs.pay_bpjs("rb", FakeRequest({"agency": "tk", "cash_account_id": "ca-bca"})))
        assert _net(env.jes[-1]["lines"]) == {"2-1502": 240_240, "1-1201": -240_240}   # 78.000 + 162.240
        assert out["bpjs_payment_status"] == "paid" and out["bpjs_payment_amount"] == 370_240

    def test_bayar_tanpa_lembaga_ditolak_dan_run_lama_pakai_2_1500(self, env):
        env.db.rahaza_payroll_runs.docs.append({"id": "rl", "run_number": "PR-L", "status": "finalized",
                                                "period_from": "2026-09-01", "period_to": "2026-09-30",
                                                "deductions_by_type": {"bpjs_kesehatan": 26_000, "bpjs_jht": 52_000}})
        assert _err(runs.pay_bpjs("rl", FakeRequest({}))).status_code == 400
        run(runs.pay_bpjs("rl", FakeRequest({"agency": "tk", "cash_account_id": "ca-bca"})))
        assert _net(env.jes[-1]["lines"]) == {"2-1500": 52_000, "1-1201": -52_000}

    def test_frontend_bayar_bpjs_tanpa_prompt(self):
        s = _src("frontend", "src", "components", "erp", "RahazaPayrollRunModule.jsx")
        assert "prompt(" not in s and "CashAccountSelect" in s and "agency" in s


# ═══ K24 — Lembur ══════════════════════════════════════════════════════════════
def _ot_env(db, ot_rate=0, scheme="monthly", base=3_460_000):
    prof = {"employee_id": "emp-a", "pay_scheme": scheme, "base_rate": base, "overtime_rate": ot_rate}
    db.rahaza_attendance_events.docs = [
        {"employee_id": "emp-a", "date": "2026-10-05", "status": "hadir", "overtime_hours": 3},   # sama dgn pengajuan
        {"employee_id": "emp-a", "date": "2026-10-06", "status": "hadir", "overtime_hours": 2},
        # 2026-11-09 (Q9): lembur dibayar dari jam NYATA — Minggu 11 Okt ada absen 4 jam kerja bersih.
        {"employee_id": "emp-a", "date": "2026-10-11", "status": "hadir", "hours_worked": 4, "net_hours_worked": 4},
    ]
    db.rahaza_overtime_requests.docs = [
        {"employee_id": "emp-a", "date": "2026-10-05", "status": "approved", "hours": 3, "rate_multiplier": 1.5},
        {"employee_id": "emp-a", "date": "2026-10-11", "status": "approved", "hours": 4, "rate_multiplier": 2},
    ]
    return prof


class TestLembur:
    def test_cadangan_1_per_173_tanpa_hitung_dobel(self, env):
        # 3.460.000/173 = 20.000/jam. 05-10 pengajuan 3j (absensi 3j hari itu = jam yang SAMA): 1×1,5+2×2 = 5,5;
        # 2026-11-06 (Tahap 2): 06-10 absensi 2j TANPA pengajuan → tidak dibayar; 11-10 (Minggu = hari istirahat,
        # 6 hari kerja) pengajuan 4j: 4 × 2 = 8 (pengali pengajuan diabaikan) → 13,5 × 20.000 = 270.000
        prof = _ot_env(env.db)
        s = run(shared._compute_payslip_for_employee(env.db, prof, "2026-10-01", "2026-10-31", {"id": "emp-a", "name": "Ani"}))
        assert s["overtime_basis"] == "upah_tetap_div_173" and s["overtime_base_hourly"] == 20_000
        assert s["overtime_amount"] == 270_000 and s["source_refs"]["overtime_unapproved_hours"] == 2
        assert s["gross_pay"] == 3_460_000 + 270_000 and s["overtime_warning"] is None

    def test_tarif_profil_dipakai_dan_tidak_dobel(self, env):
        # 2026-11-06 (Tahap 2): tarif profil 25.000 = Rp per jam lembur pertama → upah sejam 25.000/1,5;
        # faktor per hari sama dengan uji di atas (5,5 + 8 = 13,5) → 13,5 × 16.666,67 = 225.000
        prof = _ot_env(env.db, ot_rate=25_000)
        s = run(shared._compute_payslip_for_employee(env.db, prof, "2026-10-01", "2026-10-31", {"id": "emp-a", "name": "Ani"}))
        assert s["overtime_basis"] == "profile" and s["overtime_amount"] == 225_000

    def test_pengali_bisa_diatur(self, env):
        env.db.rahaza_payroll_settings.docs.append({"key": "overtime", "basis": "upah_tetap_div_173", "divisor": 173,
                                                    "first_hour_multiplier": 2, "next_hours_multiplier": 3})
        prof = _ot_env(env.db)
        env.db.rahaza_overtime_requests.docs.pop()   # sisakan 05-10 (3j) + absensi 06-10 (2j)
        # 05-10: 2 + 2×3 = 8 ; 06-10 tanpa pengajuan tidak dibayar (Tahap 2) → 8 × 20.000 = 160.000
        s = run(shared._compute_payslip_for_employee(env.db, prof, "2026-10-01", "2026-10-31", {"id": "emp-a", "name": "Ani"}))
        assert s["overtime_amount"] == 160_000

    def test_peringatan_tarif_nol_di_run(self, env, monkeypatch):
        env.db.rahaza_payroll_settings.docs.append({"key": "overtime", "basis": "manual"})
        prof = _ot_env(env.db)
        s = run(shared._compute_payslip_for_employee(env.db, prof, "2026-10-01", "2026-10-31", {"id": "emp-a", "name": "Ani"}))
        assert s["overtime_amount"] == 0 and "TIDAK dibayar" in s["overtime_warning"]
        env.db.rahaza_payroll_profiles.docs = [dict(prof, active=True)]

        async def runno(dbx):
            return "PR-OT"
        monkeypatch.setattr(runs, "_generate_run_number", runno)
        out = run(runs.create_run(FakeRequest({"period_from": "2026-10-01", "period_to": "2026-10-31"})))
        assert "overtime_rate_zero" in [w["type"] for w in out["warnings"]]   # Tahap 2: + peringatan lain
        assert "warnings" in _src("frontend", "src", "components", "erp", "RahazaPayrollRunModule.jsx")


# ═══ K25 — Pemisahan tugas ═════════════════════════════════════════════════════
class TestPemisahanTugasKasbon:
    def test_hr_tidak_boleh_mereview_ajuannya_sendiri(self, env):
        env.db.dewi_kasbon_requests.docs.append({"id": "k1", "employee_id": "emp-hr", "status": "submitted",
                                                 "amount": 500_000.0, "submitted_by": "hr@x", "installment_count": 1})
        e = _err(kas.hr_review_kasbon("k1", FakeRequest({"action": "approve"}), db=env.db, user=HR))
        assert e.status_code == 403 and "sendiri" in e.detail

    def test_nilai_disetujui_tidak_melebihi_diminta(self, env):
        env.db.dewi_kasbon_requests.docs.append({"id": "k2", "employee_id": "emp-a", "status": "submitted", "type": "pinjaman",
                                                 "amount": 3_000_000.0, "outstanding_balance": 3_000_000.0,
                                                 "installment_count": 3, "installment_amount": 1_000_000})
        assert _err(kas.hr_review_kasbon("k2", FakeRequest({"action": "approve", "approved_amount": 5_000_000}),
                                         db=env.db, user=HR)).status_code == 400
        out = run(kas.hr_review_kasbon("k2", FakeRequest({"action": "approve", "approved_amount": 1_500_000}),
                                       db=env.db, user=HR))
        r = out["request"]   # 1.500.000 / 3 cicilan = 500.000
        assert (r["amount"], r["requested_amount"], r["outstanding_balance"], r["installment_amount"]) == (
            1_500_000, 3_000_000, 1_500_000, 500_000)

    def test_batas_kasbon_dari_pengaturan(self, env):
        env.db.rahaza_payroll_settings.docs.append({"key": "kasbon", "max_pct_of_base_salary": 50, "max_installments": 3})
        env.db.rahaza_payroll_profiles.docs = [{"employee_id": "emp-a", "active": True, "pay_scheme": "monthly",
                                                "base_rate": 2_000_000}]
        user = dict(ANI, employee_id="emp-a")
        # batas 50% × 2.000.000 = 1.000.000
        e = _err(kas.submit_kasbon_request(FakeRequest({"type": "kasbon", "amount": 1_500_000}), db=env.db, user=user))
        assert e.status_code == 400 and "1.000.000" in e.detail
        e = _err(kas.submit_kasbon_request(FakeRequest({"type": "pinjaman", "amount": 900_000, "installment_count": 6}),
                                           db=env.db, user=user))
        assert e.status_code == 400 and "cicilan" in e.detail

    def test_tanpa_batas_bila_belum_diisi(self, env, monkeypatch):
        async def num(*a, **k):
            return "KSB-0001"
        monkeypatch.setattr(kas, "issue_number", num)
        out = run(kas.submit_kasbon_request(FakeRequest({"type": "kasbon", "amount": 50_000_000}), db=env.db,
                                            user=dict(ANI, employee_id="emp-a")))
        assert out["ok"] and out["request"]["amount"] == 50_000_000


def _travel(db, tid="t1", emp="u-ani", status="submitted", requested=1_000_000.0, **kw):
    db.employee_travel_requests.docs.append({"id": tid, "trip_number": f"TR-{tid}", "employee_id": emp, "created_by": emp,
                                             "employee_name": "X", "destination": "Bandung", "status": status,
                                             "cash_advance_requested": requested, "cash_advance_approved": 0,
                                             "cash_advance_paid": 0, "start_date": "2026-10-21", "end_date": "2026-10-22",
                                             **kw})


class TestPemisahanTugasDinasKlaim:
    def test_dinas_milik_sendiri_dan_nilai_lebih(self, env):
        _travel(env.db, "t1", emp="u-hr")
        assert _err(etr.approve_travel_request("t1", etr.ApprovePayload(), user=HR)).status_code == 403
        _travel(env.db, "t2")
        e = _err(etr.approve_travel_request("t2", etr.ApprovePayload(cash_advance_approved=5_000_000), user=HR))
        assert e.status_code == 400 and "melebihi" in e.detail
        out = run(etr.approve_travel_request("t2", etr.ApprovePayload(cash_advance_approved=800_000), user=HR))
        assert out["cash_advance_approved"] == 800_000

    def test_hr_tidak_membayar_uang_muka(self, env):
        _travel(env.db, "t3", status="approved", cash_advance_approved=1_000_000.0, cash_advance_decided=True)
        p = etr.AdvancePaidPayload(amount_paid=1_000_000, bank_account_id="ca-bca", payment_date="2026-10-20")
        assert _err(etr.mark_advance_paid("t3", p, user=HR)).status_code == 403
        assert run(etr.mark_advance_paid("t3", p, user=FIN))["new_status"] == "advance_paid"

    def test_uang_muka_disetujui_nol_tidak_tanpa_batas(self, env):
        _travel(env.db, "t4", status="approved", cash_advance_decided=True)
        e = _err(etr.mark_advance_paid("t4", etr.AdvancePaidPayload(amount_paid=500_000, bank_account_id="ca-bca"), user=FIN))
        assert e.status_code == 400 and "Tidak ada uang muka" in e.detail

    def test_persetujuan_massal_melewati_ajuan_sendiri(self, env):
        _travel(env.db, "t5", emp="u-hr")
        _travel(env.db, "t6")
        res = run(etr.bulk_approve_travel(etr.BulkApproveTravelRequest(travel_ids=["t5", "t6"]), user=HR))
        assert res["results"]["success"] == ["t6"] and res["results"]["failed"][0]["id"] == "t5"
        t6 = next(d for d in env.db.employee_travel_requests.docs if d["id"] == "t6")
        assert t6["cash_advance_approved"] == 1_000_000 and t6["cash_advance_decided"] is True

    def test_klaim_sendiri_dan_pencairan_hr(self, env):
        env.db.rahaza_expense_claims.docs += [
            {"id": "c1", "claim_number": "EC-1", "status": "submitted", "employee_id": "u-hr", "total_amount": 1.0},
            {"id": "c2", "claim_number": "EC-2", "status": "approved", "employee_id": "u-ani", "total_amount": 150_000.0}]
        assert _err(eec.approve_claim("c1", eec.ApprovePayload(), user=HR)).status_code == 403
        assert _err(eec.disburse_claim("c2", eec.DisbursePayload(bank_account_id="ca-bca"), user=HR)).status_code == 403

    def test_settlement_sendiri_dan_posting_hr(self, env):
        env.db.employee_travel_settlements.docs += [
            {"id": "s1", "status": "submitted", "employee_id": "u-ani", "created_by": "u-hr", "settlement_number": "TS-1"},
            {"id": "s2", "status": "approved", "employee_id": "u-ani", "settlement_number": "TS-2"}]
        assert _err(ets.approve_settlement("s1", ets.ApprovePayload(), user=HR)).status_code == 403
        assert _err(ets.post_settlement_gl("s2", ets.PostPayload(), user=HR)).status_code == 403


# ═══ K26 — Uang muka kas kecil ════════════════════════════════════════════════
class TestUangMukaKasKecil:
    def _fund(self, env, days=0):
        env.db.rahaza_petty_cash_funds.docs.append({"id": "f1", "name": "KK", "status": "active",
                                                    "current_balance": 1_000_000.0, "advance_settle_days": days})
        env.db.employee_expense_gl_mappings.docs.append({"category": "transport", "gl_account_code": "6-3400",
                                                         "is_active": True})

    def test_advance_wajib_karyawan_dan_ke_1_1610(self, env):
        self._fund(env)
        e = _err(pc.create_txn(pc.TxnCreate(fund_id="f1", txn_type="advance", amount=500_000, payee="Totti"), dict(FIN)))
        assert e.status_code == 400 and "karyawan" in e.detail
        out = run(pc.create_txn(pc.TxnCreate(fund_id="f1", txn_type="advance", amount=500_000, employee_id="emp-a",
                                             txn_date="2026-10-01"), dict(FIN)))
        assert _net(env.jes[-1]["lines"]) == {"1-1610": 500_000, "1-1101": -500_000}
        assert out["txn"]["employee_name"] == "Ani" and out["new_balance"] == 500_000

    def test_pertanggungjawaban_nota_per_kategori_dan_sisa(self, env):
        self._fund(env, days=7)
        adv = run(pc.create_txn(pc.TxnCreate(fund_id="f1", txn_type="advance", amount=500_000, employee_id="emp-a",
                                             txn_date="2026-10-01"), dict(FIN)))["txn"]
        assert adv["due_date"] == "2026-10-08"
        bad = pc.AdvanceSettleIn(items=[pc.SettleItem(category="konsumsi", amount=100_000)])
        assert "belum dipetakan" in _err(pc.settle_advance(adv["id"], bad, dict(FIN))).detail
        body = pc.AdvanceSettleIn(items=[pc.SettleItem(category="transport", amount=300_000),
                                         pc.SettleItem(category="konsumsi", account_code="6-2900", amount=80_000)],
                                  returned_amount=120_000, settle_date="2026-10-05")
        out = run(pc.settle_advance(adv["id"], body, dict(FIN)))
        # Dr 6-3400 300.000 + Dr 6-2900 80.000 + Dr 1-1101 120.000 / Cr 1-1610 500.000
        assert _net(env.jes[-1]["lines"]) == {"6-3400": 300_000, "6-2900": 80_000, "1-1101": 120_000, "1-1610": -500_000}
        assert out["advance"]["advance_status"] == "settled" and out["advance"]["open_amount"] == 0
        assert env.db.rahaza_petty_cash_funds.docs[0]["current_balance"] == 620_000   # 1.000.000 − 500.000 + 120.000

    def test_bertahap_dan_tidak_boleh_lebih(self, env):
        self._fund(env)
        adv = run(pc.create_txn(pc.TxnCreate(fund_id="f1", txn_type="advance", amount=500_000, employee_id="emp-a"),
                                dict(FIN)))["txn"]
        run(pc.settle_advance(adv["id"], pc.AdvanceSettleIn(items=[pc.SettleItem(category="transport", amount=200_000)]),
                              dict(FIN)))
        e = _err(pc.settle_advance(adv["id"], pc.AdvanceSettleIn(returned_amount=400_000), dict(FIN)))
        assert e.status_code == 400 and "300.000" in e.detail.replace(",", ".")
        lst = run(pc.list_advances(status="open", employee_id=None, fund_id=None, user=dict(FIN)))
        assert lst["total_open"] == 300_000 and lst["by_employee"][0]["employee_name"] == "Ani"

    def test_daftar_terlambat(self, env):
        self._fund(env, days=3)
        run(pc.create_txn(pc.TxnCreate(fund_id="f1", txn_type="advance", amount=100_000, employee_id="emp-a",
                                       txn_date="2020-01-01"), dict(FIN)))
        lst = run(pc.list_advances(status="open", employee_id=None, fund_id=None, user=dict(FIN)))
        assert lst["items"][0]["overdue"] is True and lst["by_employee"][0]["overdue_count"] == 1

    def test_pengeluaran_tanpa_atk_bawaan(self, env):
        self._fund(env)
        e = _err(pc.create_txn(pc.TxnCreate(fund_id="f1", txn_type="expense", amount=50_000, category="ATK"), dict(FIN)))
        assert e.status_code == 400 and "pilih akun" in e.detail
        run(pc.create_txn(pc.TxnCreate(fund_id="f1", txn_type="expense", amount=50_000, category="transport"), dict(FIN)))
        assert _net(env.jes[-1]["lines"]) == {"6-3400": 50_000, "1-1101": -50_000}
        e = _err(pc.create_txn(pc.TxnCreate(fund_id="f1", txn_type="expense", amount=1, account_code="1-1201"), dict(FIN)))
        assert "bukan akun beban" in e.detail

    def test_return_hanya_untuk_uang_muka_lama(self, env):
        self._fund(env)
        run(pc.create_txn(pc.TxnCreate(fund_id="f1", txn_type="advance", amount=500_000, employee_id="emp-a"), dict(FIN)))
        e = _err(pc.create_txn(pc.TxnCreate(fund_id="f1", txn_type="return", amount=100_000), dict(FIN)))
        assert e.status_code == 400 and "Pertanggungjawaban" in e.detail


# ═══ K34 — Penyesuaian slip & batal run ═══════════════════════════════════════
def _draft_slip(db):
    db.rahaza_payroll_runs.docs.append({"id": "r1", "run_number": "PR-1", "status": "draft",
                                        "period_from": "2026-10-01", "period_to": "2026-10-31"})
    db.rahaza_payslips.docs.append({
        "id": "s1", "run_id": "r1", "employee_id": "emp-a", "gross_pay": 3_000_000.0, "deductions_total": 180_000.0,
        "net_pay": 2_820_000.0, "deductions": [{"type": "late", "label": "Terlambat", "amount": 50_000},
                                               {"type": "bpjs_kesehatan", "label": "BPJS Kes", "amount": 30_000},
                                               {"type": "kasbon", "kasbon_id": "k9", "label": "Kasbon", "amount": 100_000}]})


class TestPenyesuaianSlip:
    def test_tambah_kurang_pendapatan_dan_potongan(self, env):
        _draft_slip(env.db)
        assert "Alasan" in _err(slips_mod.adjust_payslip("r1", "s1", FakeRequest({"earning_adjustment": 200_000}))).detail
        body = {"earning_adjustment": 200_000, "deduction": 25_000, "reason": "bonus target, ganti rugi",
                "deduction_overrides": [{"index": 0, "amount": 20_000}, {"index": 2, "amount": 60_000}]}
        out = run(slips_mod.adjust_payslip("r1", "s1", FakeRequest(body)))
        s = out["payslip"]
        # bruto 3.000.000 + 200.000 = 3.200.000 ; potongan 20.000 + 30.000 + 60.000 + 25.000 = 135.000 → neto 3.065.000
        assert (s["gross_pay"], s["deductions_total"], s["net_pay"]) == (3_200_000, 135_000, 3_065_000)
        assert s["deductions"][0]["original_amount"] == 50_000 and out["run_totals"]["total_net"] == 3_065_000
        # kurangi pendapatan: −300.000 dari bruto sistem 3.000.000 → 2.700.000 (bukan dari 3.200.000)
        out = run(slips_mod.adjust_payslip("r1", "s1", FakeRequest({"earning_adjustment": -300_000, "reason": "koreksi"})))
        assert out["payslip"]["gross_pay"] == 2_700_000 and out["payslip"]["net_pay"] == 2_565_000

    def test_batasan(self, env):
        _draft_slip(env.db)
        req = lambda b: FakeRequest({**b, "reason": "x"})  # noqa: E731
        assert _err(slips_mod.adjust_payslip("r1", "s1", req({"deduction": -1}))).status_code == 400
        assert "BPJS" in _err(slips_mod.adjust_payslip("r1", "s1", req({"deduction_overrides": [{"index": 1, "amount": 0}]}))).detail
        assert "DIKURANGI" in _err(slips_mod.adjust_payslip("r1", "s1", req({"deduction_overrides": [{"index": 0, "amount": 60_000}]}))).detail
        env.db.rahaza_payroll_runs.docs[0]["status"] = "finalized"
        assert _err(slips_mod.adjust_payslip("r1", "s1", req({"deduction": 1}))).status_code == 400

    def test_jurnal_seimbang_dengan_pendapatan_tambahan(self, env):
        _draft_slip(env.db)
        env.db.rahaza_payslips.docs[0]["deductions"] = [{"type": "late", "label": "Terlambat", "amount": 50_000}]
        env.db.rahaza_payslips.docs[0].update(deductions_total=50_000.0, net_pay=2_950_000.0)
        run(slips_mod.adjust_payslip("r1", "s1", FakeRequest({"earning_adjustment": 200_000, "reason": "bonus"})))
        run(runs.finalize_run("r1", FakeRequest()))
        # Dr 6-2100 3.200.000 − 50.000 = 3.150.000 / Cr 2-1200 3.150.000
        assert _net(env.jes[0]["lines"]) == {"6-2100": 3_150_000, "2-1200": -3_150_000}


def _run_with_kasbon(env):
    env.db.rahaza_payroll_runs.docs.append({"id": "rc", "run_number": "PR-C", "status": "draft",
                                            "period_from": "2026-10-01", "period_to": "2026-10-31"})
    env.db.rahaza_payslips.docs.append({"id": "sc", "run_id": "rc", "employee_id": "emp-a", "pay_scheme": "monthly",
                                        "gross_pay": 2_000_000.0, "deductions_total": 500_000.0, "net_pay": 1_500_000.0,
                                        "deductions": [{"type": "kasbon", "kasbon_id": "kc", "amount": 500_000}]})
    env.db.dewi_kasbon_requests.docs.append({"id": "kc", "employee_id": "emp-a", "type": "kasbon", "status": "disbursed",
                                             "amount": 500_000.0, "outstanding_balance": 500_000.0, "paid_amount": 0.0,
                                             "repayments": [], "request_number": "KSB-C"})
    env.actor["user"] = dict(HR)
    run(runs.finalize_run("rc", FakeRequest()))


class TestBatalRunFinal:
    def test_dua_langkah_hr_lalu_keuangan(self, env, monkeypatch):
        _run_with_kasbon(env)
        k = env.db.dewi_kasbon_requests.docs[0]
        assert k["status"] == "paid_off" and len(env.jes) == 2   # JE gaji + JE potongan kasbon
        assert _err(runs.cancel_run("rc", FakeRequest({"action": "request"}))).status_code == 400   # tanpa alasan
        out = run(runs.cancel_run("rc", FakeRequest({"action": "request", "reason": "salah hitung lembur"})))
        assert out["cancel_request"]["status"] == "pending" and out["status"] == "finalized"
        assert _err(runs.cancel_run("rc", FakeRequest({"action": "approve"}))).status_code == 403   # HR tidak menyetujui
        env.actor["user"] = dict(FIN)
        out = run(runs.cancel_run("rc", FakeRequest({"action": "approve"})))
        assert out["status"] == "cancelled" and len(out["cancel_reversal_jes"]) == 2
        # Semua akun kembali nol: gaji, hutang gaji, piutang kasbon
        assert set(_net([ln for je in env.jes for ln in je["lines"]]).values()) == {0}
        assert all(je["date"] == "2026-10-31" for je in env.jes[2:])   # periode Okt masih terbuka
        k = env.db.dewi_kasbon_requests.docs[0]
        assert (k["status"], k["outstanding_balance"], k["repayments"]) == ("disbursed", 500_000, [])
        assert len(k["repayments_reversed"]) == 1
        # periode bisa dibuat ulang
        assert run(shared.find_duplicate_run_conflicts(env.db, "2026-10-01", "2026-10-31",
                                                       [{"employee_id": "emp-a", "pay_scheme": "monthly"}])) == []

    def test_pengaju_tidak_boleh_menyetujui_sendiri(self, env):
        _run_with_kasbon(env)
        # manager_keuangan ber-izin payroll.manage = boleh mengajukan (HR) DAN menyetujui (Keuangan)
        env.actor["user"] = {"id": "u-mk", "role": "manager_keuangan", "name": "MK", "_permissions": ["payroll.manage"]}
        run(runs.cancel_run("rc", FakeRequest({"action": "request", "reason": "x"})))
        e = _err(runs.cancel_run("rc", FakeRequest({"action": "approve"})))
        assert e.status_code == 403 and "Pemisahan tugas" in e.detail

    def test_owner_satu_langkah_dan_periode_tertutup(self, env):
        _run_with_kasbon(env)
        env.db.rahaza_periods.docs.append({"period_code": "2026-10", "status": "closed"})
        env.actor["user"] = dict(OWNER)
        out = run(runs.cancel_run("rc", FakeRequest({"reason": "run ganda"})))
        assert out["status"] == "cancelled"
        assert all(je["date"] == shared._today_wib().isoformat() for je in env.jes[2:])

    def test_ditolak_bila_sudah_dibayar(self, env):
        _run_with_kasbon(env)
        env.db.rahaza_payroll_runs.docs[0].update(payment_status="paid", payment_gl_je_number="JE-PAY")
        env.actor["user"] = dict(OWNER)
        e = _err(runs.cancel_run("rc", FakeRequest({"reason": "x"})))
        assert e.status_code == 400 and "void pembayaran gaji" in e.detail
        assert env.db.rahaza_payroll_runs.docs[0]["status"] == "finalized" and len(env.jes) == 2

    def test_jurnal_pembalik_gagal_run_tetap_final(self, env):
        _run_with_kasbon(env)
        env.actor["user"] = dict(OWNER)
        env.fake_je.fail = "Periode 2026-11 sudah closed."
        try:
            e = _err(runs.cancel_run("rc", FakeRequest({"reason": "x"})))
        finally:
            env.fake_je.fail = None
        assert "TERHENTI" in e.detail and env.db.rahaza_payroll_runs.docs[0]["status"] == "finalized"
        assert env.db.dewi_kasbon_requests.docs[0]["status"] == "paid_off"

    def test_hapus_run_final_ditolak(self, env):
        _run_with_kasbon(env)
        assert "Batalkan Run" in _err(runs.delete_run("rc", FakeRequest())).detail


# ═══ K38 + Profil Posting ══════════════════════════════════════════════════════
class TestProfilPosting:
    def test_peran_baru_tampil_di_bawaan(self):
        d = {p["event_type"]: p["mapping"] for p in profiles_mod.DEFAULT_PROFILES}
        assert d["payroll_finalize"]["credit_other_deduction"] == "4-9000"
        assert d["payroll_finalize"]["credit_bpjs_kes_payable"] == "2-1501"
        assert d["payroll_finalize"]["debit_bpjs_tk_employer_expense"] == "6-3300"
        assert d["petty_cash_expense"]["debit_employee_advance"] == "1-1610"

    def test_upgrade_menambah_peran_tanpa_menimpa_pilihan_finance(self):
        doc = {"mapping": {"credit_bpjs_payable": "2-1500"}, "user_roles": ["credit_bpjs_payable"],
               "user_removed_roles": ["debit_bpjs_kes_employer_expense"], "updated_by": "u-fin"}
        d = {p["event_type"]: p["mapping"] for p in profiles_mod.DEFAULT_PROFILES}
        m = profiles_mod.upgrade_profile_mapping("payroll_finalize", dict(doc["mapping"]), doc, d["payroll_finalize"])
        assert m["credit_other_deduction"] == "4-9000" and m["credit_bpjs_kes_payable"] == "2-1501"
        assert "debit_bpjs_kes_employer_expense" not in m


# ═══ Frontend (cek sumber) ═════════════════════════════════════════════════════
class TestFrontend:
    def test_tab_pengaturan_payroll_satu_layar(self):
        hub = _src("frontend", "src", "components", "erp", "hubs", "HRPayrollHub.jsx")
        # 2026-11-08 (keputusan owner): label tab "Pengaturan Payroll" → "Pengaturan gaji"
        assert "'Pengaturan gaji'" in hub and "'Pengaturan Payroll'" not in hub
        assert "RahazaPayrollSettingsModule" in hub
        s = _src("frontend", "src", "components", "erp", "RahazaPayrollSettingsModule.jsx")
        for k in ("late-penalty", "attendance-bonus", "payroll-settings/bpjs", "payroll-settings/overtime",
                  "payroll-settings/kasbon"):
            assert k in s, k

    def test_layar_lain(self):
        emp = _src("frontend", "src", "components", "erp", "HREmployeeModule.jsx")
        assert "bpjs_programs" in emp
        pr = _src("frontend", "src", "components", "erp", "RahazaPayrollRunModule.jsx")
        assert "/cancel" in pr and "earning_adjustment" in pr and "deduction_overrides" in pr
        pcs = _src("frontend", "src", "components", "erp", "PettyCashModule.jsx")
        assert "/advances" in pcs and "/settle" in pcs and "employee_id" in pcs
        assert not re.search(r"SelectItem value=\"1-1\d{3}\"", pcs)
        hk = _src("frontend", "src", "components", "erp", "HRKasbonModule.jsx")
        assert "approved_amount" in hk
