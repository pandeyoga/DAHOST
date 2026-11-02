"""Uji regresi HERMETIK paket P5 (2026-11-02) — SDM, payroll, kasbon, klaim, dinas. Tanpa server/Mongo.

Satu kelas uji per butir perintah owner:
  1 run payroll ganda · 2 karyawan nonaktif · 3 finalisasi gagal posting · 4 akun bayar gaji kas/bank
  5 "Potong Gaji" Keuangan · 6 Keuangan bayar uang muka dinas · 7 rekening & tanggal pilihan pengguna
  8 settlement sebelum uang muka · 9 "Muat Demo" dihapus · 10 privasi kasbon · 11 "Bulan lalu" WIB
  12 notifikasi ke pemohon

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import asyncio
import os
import re
import sys
import types
from datetime import date

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

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402

import routes.dewi_kasbon as kas  # noqa: E402
import routes.employee_expense_claims as eec  # noqa: E402
import routes.employee_travel_requests as etr  # noqa: E402
import routes.employee_travel_settlements as ets  # noqa: E402
import routes.rahaza_payroll_runs as runs  # noqa: E402
import routes.rahaza_payroll_shared as shared  # noqa: E402
import routes.rahaza_posting as posting  # noqa: E402
import routes.rahaza_posting_profiles as profiles_mod  # noqa: E402

run = asyncio.run

HR = {"id": "u-hr", "role": "hr", "name": "Brenda HR", "email": "hr@x"}
FIN = {"id": "u-fin", "role": "staff_keuangan", "name": "Fatimah", "email": "fin@x"}
ACC = {"id": "u-acc", "role": "accounting", "name": "Tutut", "email": "acc@x"}
ANI = {"id": "u-ani", "role": "tim_packing", "name": "Ani", "email": "ani@x"}
BUDI = {"id": "u-budi", "role": "tim_packing", "name": "Budi", "email": "budi@x"}

MAPPINGS = {
    "employee_loan_disbursement": {"debit_employee_loan_receivable": "1-1320", "credit_cash": "1-1201"},
    "employee_loan_repayment_manual": {"debit_bank": "1-1201", "credit_employee_loan_receivable": "1-1320"},
    "employee_loan_repayment_payroll": {"debit_salary_payable": "2-1200", "credit_employee_loan_receivable": "1-1320"},
    "payroll_payment": {"credit_bank_default": "1-1201", "debit_salary_payable": "2-1200"},
    "expense": {"credit_cash_default": "1-1201"},
}


def _coa(code, name, parent=None, group=False):
    return {"code": code, "name": name, "parent_code": parent, "is_group": group, "active": True}


@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    db.rahaza_coa_accounts.docs = [
        _coa("1-1100", "Kas", group=True), _coa("1-1101", "Kas Kecil", "1-1100"),
        _coa("1-1200", "Bank", group=True), _coa("1-1201", "Bank BCA", "1-1200"), _coa("1-1202", "Bank Mandiri", "1-1200"),
        _coa("1-1320", "Piutang Karyawan"), _coa("1-1610", "Uang Muka Karyawan"), _coa("2-1200", "Hutang Gaji"),
        _coa("6-2000", "Beban Umum", group=True), _coa("6-2900", "Beban Umum & Lain-lain", "6-2000"),
        _coa("6-3400", "Biaya Perjalanan Dinas"), _coa("6-3500", "Biaya Reimbursement"),
    ]
    db.rahaza_cash_accounts.docs = [
        {"id": "ca-kk", "code": "1-1101", "name": "Kas Kecil", "gl_account_code": "1-1101", "type": "cash", "active": True},
        {"id": "ca-bca", "code": "1-1201", "name": "Bank BCA", "gl_account_code": "1-1201", "type": "bank", "active": True},
        {"id": "ca-mdr", "code": "1-1202", "name": "Bank Mandiri", "gl_account_code": "1-1202", "type": "bank", "active": True},
    ]
    db.rahaza_employees.docs = [
        {"id": "emp-a", "name": "Ani", "active": True, "user_id": "u-ani"},
        {"id": "emp-b", "name": "Budi", "active": True, "user_id": "u-budi"},
        {"id": "emp-t", "name": "Tanti", "active": False, "user_id": "u-tanti"},
    ]
    db.users.docs = [{"id": u["id"], "role": u["role"], "email": u["email"], "employee_id": e}
                     for u, e in ((ANI, "emp-a"), (BUDI, "emp-b"), (HR, None), (FIN, None), (ACC, None))]
    db.rahaza_payroll_profiles.docs = [
        {"employee_id": e, "pay_scheme": "monthly", "base_rate": 1000, "active": True} for e in ("emp-a", "emp-b", "emp-t")]

    jes = []

    async def fake_je(dbx, je_date, memo, source_module, source_ref, lines_raw, user, **kw):
        if getattr(fake_je, "fail", None):
            return {"ok": False, "error": fake_je.fail}
        jes.append({"date": je_date, "source_module": source_module, "source_ref": source_ref, "lines": lines_raw})
        return {"ok": True, "je_id": f"je-{len(jes)}", "je_number": f"JE-{len(jes):04d}"}

    async def fake_mapping(dbx, event_type):
        return dict(MAPPINGS.get(event_type, {}))

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(posting, "_create_posted_je", fake_je)
    monkeypatch.setattr(profiles_mod, "get_mapping", fake_mapping)
    for mod in (runs, etr, ets, eec):
        monkeypatch.setattr(mod, "get_db", lambda: db)
        monkeypatch.setattr(mod, "log_activity", noop)

    async def hr_gate(request):
        return dict(HR)

    async def fake_compute(dbx, p, pf, pt, emp):
        return {"id": f"slip-{p['employee_id']}-{pf}", "employee_id": p["employee_id"], "employee_name": emp["name"],
                "pay_scheme": p["pay_scheme"], "gross_pay": 1000.0, "deductions_total": 0.0, "net_pay": 1000.0,
                "deductions": [], "period_from": pf, "period_to": pt}

    counter = {"n": 0}

    async def fake_runno(dbx):
        counter["n"] += 1
        return f"PR-UJI-{counter['n']:03d}"

    monkeypatch.setattr(runs, "_require_hr", hr_gate)
    monkeypatch.setattr(runs, "_compute_payslip_for_employee", fake_compute)
    monkeypatch.setattr(runs, "_generate_run_number", fake_runno)
    return types.SimpleNamespace(db=db, jes=jes, fake_je=fake_je)


def _err(coro):
    with pytest.raises(HTTPException) as ei:
        run(coro)
    return ei.value


def _src(*parts):
    p = os.path.join(REPO, *parts)
    if not os.path.exists(p):
        pytest.skip(f"sumber frontend tidak tersedia: {p}")
    return open(p, encoding="utf-8").read()


# ── Butir 1 ─────────────────────────────────────────────────────────────────────
class TestRunGanda:
    def test_periods_overlap(self):
        assert shared.periods_overlap("2026-10-01", "2026-10-31", "2026-09-30", "2026-10-31")
        assert shared.periods_overlap("2026-10-01", "2026-10-31", "2026-10-31", "2026-11-30")
        assert not shared.periods_overlap("2026-10-01", "2026-10-31", "2026-11-01", "2026-11-30")

    def test_run_kedua_periode_sama_ditolak(self, env):
        r1 = run(runs.create_run(FakeRequest({"period_from": "2026-10-01", "period_to": "2026-10-31"})))
        assert r1["status"] == "draft"
        e = _err(runs.create_run(FakeRequest({"period_from": "2026-10-01", "period_to": "2026-10-31"})))
        assert e.status_code == 409 and r1["run_number"] in e.detail
        assert env.db.rahaza_payroll_runs.docs.__len__() == 1

    def test_run_tumpang_tindih_ditolak(self, env):
        run(runs.create_run(FakeRequest({"period_from": "2026-10-01", "period_to": "2026-10-31"})))
        e = _err(runs.create_run(FakeRequest({"period_from": "2026-09-30", "period_to": "2026-10-31"})))
        assert e.status_code == 409

    def test_boleh_bila_run_lama_dibatalkan(self, env):
        r1 = run(runs.create_run(FakeRequest({"period_from": "2026-10-01", "period_to": "2026-10-31"})))
        env.db.rahaza_payroll_runs.docs[0]["status"] = "cancelled"
        r2 = run(runs.create_run(FakeRequest({"period_from": "2026-10-01", "period_to": "2026-10-31"})))
        assert r2["id"] != r1["id"]

    def test_skema_berbeda_tidak_bentrok(self, env):
        env.db.rahaza_payroll_runs.docs.append({"id": "rw", "run_number": "PR-W", "status": "finalized",
                                                "period_from": "2026-10-01", "period_to": "2026-10-31"})
        env.db.rahaza_payslips.docs.append({"run_id": "rw", "employee_id": "emp-a", "pay_scheme": "weekly"})
        out = run(runs.create_run(FakeRequest({"period_from": "2026-10-01", "period_to": "2026-10-31"})))
        assert out["total_employees"] == 2


# ── Butir 2 ─────────────────────────────────────────────────────────────────────
class TestKaryawanNonaktif:
    def test_nonaktif_dikecualikan(self, env):
        out = run(runs.create_run(FakeRequest({"period_from": "2026-10-01", "period_to": "2026-10-31"})))
        emp_in_run = {s["employee_id"] for s in env.db.rahaza_payslips.docs if s["run_id"] == out["id"]}
        assert emp_in_run == {"emp-a", "emp-b"}
        assert out["total_employees"] == 2 and out["total_gross"] == 2000.0
        assert [x["employee_id"] for x in out["excluded_employees"]] == ["emp-t"]

    def test_employee_is_active(self):
        assert shared.employee_is_active({"active": True}) and shared.employee_is_active({})
        assert not shared.employee_is_active({"active": False}) and not shared.employee_is_active(None)


# ── Butir 3 ─────────────────────────────────────────────────────────────────────
def _seed_run_with_kasbon(db):
    db.rahaza_payroll_runs.docs.append({"id": "r1", "run_number": "PR-1", "status": "draft",
                                        "period_from": "2026-12-01", "period_to": "2026-12-31"})
    db.rahaza_payslips.docs.append({"run_id": "r1", "employee_id": "emp-a", "gross_pay": 2000.0, "deductions_total": 500.0,
                                    "net_pay": 1500.0, "deductions": [{"type": "kasbon", "kasbon_id": "k1", "amount": 500}]})
    db.dewi_kasbon_requests.docs.append({"id": "k1", "employee_id": "emp-a", "type": "kasbon", "status": "disbursed",
                                         "amount": 500.0, "outstanding_balance": 500.0, "paid_amount": 0.0,
                                         "repayments": [], "request_number": "KSB-1"})


class TestFinalisasiGagalPosting:
    def test_jurnal_ditolak_run_tetap_draft_kasbon_utuh(self, env, monkeypatch):
        _seed_run_with_kasbon(env.db)

        async def fail_post(dbx, runx, user):
            return {"ok": False, "error": "Tanggal jurnal 2026-12-31 terlalu jauh di masa depan."}
        monkeypatch.setattr(runs, "post_payroll_run", fail_post)
        e = _err(runs.finalize_run("r1", FakeRequest()))
        assert e.status_code == 400 and "DRAFT" in e.detail and "terlalu jauh" in e.detail
        assert env.db.rahaza_payroll_runs.docs[0]["status"] == "draft"
        k = env.db.dewi_kasbon_requests.docs[0]
        assert k["status"] == "disbursed" and k["outstanding_balance"] == 500.0 and k["repayments"] == []

    def test_jurnal_sukses_baru_final_dan_kasbon_terpotong(self, env, monkeypatch):
        _seed_run_with_kasbon(env.db)

        async def ok_post(dbx, runx, user):
            assert runx["total_kasbon"] == 500.0  # komponen dihitung sebelum posting
            return {"ok": True, "je_id": "je-p", "je_number": "JE-PAY"}
        monkeypatch.setattr(runs, "post_payroll_run", ok_post)
        out = run(runs.finalize_run("r1", FakeRequest()))
        assert out["status"] == "finalized"
        k = env.db.dewi_kasbon_requests.docs[0]
        assert k["status"] == "paid_off" and k["outstanding_balance"] == 0
        assert [j["source_module"] for j in env.jes] == ["employee_loan_repayment_payroll"]

    def test_jurnal_potongan_kasbon_gagal_kasbon_tidak_lunas(self, env):
        _seed_run_with_kasbon(env.db)
        env.fake_je.fail = "akun 1-1320 tidak aktif"
        try:
            res = run(kas.apply_payroll_deductions_core(env.db, "2026-12", [{"kasbon_id": "k1", "amount": 500}], HR,
                                                        run_id="r1", je_date="2026-12-31"))
        finally:
            env.fake_je.fail = None
        assert res["ok"] is False and "TIDAK dicatat" in res["message"]
        k = env.db.dewi_kasbon_requests.docs[0]
        assert k["status"] == "disbursed" and k["outstanding_balance"] == 500.0 and k["repayments"] == []

    def test_potongan_tidak_dobel_saat_diulang(self, env):
        _seed_run_with_kasbon(env.db)
        env.db.dewi_kasbon_requests.docs[0].update({"type": "pinjaman", "amount": 1500.0, "outstanding_balance": 1500.0,
                                                    "installment_amount": 500.0})
        for _ in range(2):
            run(kas.apply_payroll_deductions_core(env.db, "2026-12", [{"kasbon_id": "k1", "amount": 500}], HR,
                                                  run_id="r1", je_date="2026-12-31"))
        k = env.db.dewi_kasbon_requests.docs[0]
        assert k["outstanding_balance"] == 1000.0 and len(k["repayments"]) == 1


# ── Butir 4 ─────────────────────────────────────────────────────────────────────
class TestAkunBayarGaji:
    def _final_run(self, db):
        db.rahaza_payroll_runs.docs.append({"id": "rf", "run_number": "PR-F", "status": "finalized", "total_net": 1500.0,
                                            "period_from": "2026-10-01", "period_to": "2026-10-31"})

    def test_akun_beban_ditolak(self, env):
        self._final_run(env.db)
        e = _err(runs.pay_payroll_run("rf", FakeRequest({"payment_date": "2026-10-31", "bank_account_code": "6-2900"})))
        assert e.status_code == 400 and "bukan akun kas/bank" in e.detail
        assert env.db.rahaza_payroll_runs.docs[0].get("payment_status") is None

    def test_akun_header_ditolak(self, env):
        self._final_run(env.db)
        e = _err(runs.pay_payroll_run("rf", FakeRequest({"bank_account_code": "1-1200"})))
        assert e.status_code == 400 and "header" in e.detail

    def test_akun_bank_diterima(self, env, monkeypatch):
        self._final_run(env.db)
        seen = {}

        async def fake_pay(dbx, runx, payment_date, bank_code, user):
            seen.update(bank=bank_code, date=payment_date)
            return {"ok": True, "je_id": "je-x", "je_number": "JE-X"}
        monkeypatch.setattr(posting, "post_payroll_payment", fake_pay)
        out = run(runs.pay_payroll_run("rf", FakeRequest({"payment_date": "2026-10-31", "bank_account_code": "1-1202"})))
        assert out["payment_status"] == "paid" and seen == {"bank": "1-1202", "date": "2026-10-31"}

    def test_daftar_rekening_nyata(self, env):
        rows = run(shared.list_payment_cash_accounts(env.db))
        assert [r["gl_account_code"] for r in rows] == ["1-1101", "1-1201", "1-1202"]


# ── Butir 5 ─────────────────────────────────────────────────────────────────────
class TestPotongGajiKeuangan:
    def _kasbon(self, db):
        db.dewi_kasbon_requests.docs.append({"id": "kb", "employee_id": "emp-b", "type": "kasbon", "status": "disbursed",
                                             "amount": 400000.0, "outstanding_balance": 400000.0, "paid_amount": 0.0,
                                             "repayments": [], "request_number": "KSB-B", "deduction_start_period": "2026-09"})

    def test_potong_gaji_manual_ditolak(self, env):
        self._kasbon(env.db)
        body = {"amount": 400000, "method": "payroll_deduction", "date": "2026-09-25", "period": "2026-09"}
        e = _err(kas.record_repayment("kb", FakeRequest(body), db=env.db, user=FIN))
        assert e.status_code == 400 and "run payroll" in e.detail
        k = env.db.dewi_kasbon_requests.docs[0]
        assert k["status"] == "disbursed" and k["outstanding_balance"] == 400000.0 and env.jes == []

    def test_bayar_manual_uang_nyata_ke_rekening_dipilih(self, env):
        self._kasbon(env.db)
        body = {"amount": 400000, "method": "manual", "date": "2026-10-02", "cash_account_id": "ca-kk"}
        out = run(kas.record_repayment("kb", FakeRequest(body), db=env.db, user=FIN))
        assert out["ok"] and out["request"]["status"] == "paid_off"
        je = env.jes[-1]
        assert je["date"] == date(2026, 10, 2) and je["lines"][0]["account_code"] == "1-1101"

    def test_endpoint_batch_wajib_run_final(self, env):
        self._kasbon(env.db)
        e = _err(kas.apply_payroll_deductions(FakeRequest({"period": "2026-09",
                                                           "deductions": [{"kasbon_id": "kb", "amount": 400000}]}),
                                              db=env.db, user=FIN))
        assert e.status_code == 400
        e = _err(kas.apply_payroll_deductions(FakeRequest({"run_id": "x"}), db=env.db, user=BUDI))
        assert e.status_code == 403
        assert env.db.dewi_kasbon_requests.docs[0]["outstanding_balance"] == 400000.0


# ── Butir 6 & 8 (dinas) ──────────────────────────────────────────────────────────
def _travel(db, tid="t1", approved=1000000.0, paid=0.0, status="approved"):
    db.employee_travel_requests.docs.append({"id": tid, "trip_number": f"TR-{tid}", "employee_id": "u-acc",
                                             "employee_name": "Tutut", "destination": "Bandung", "status": status,
                                             "cash_advance_approved": approved, "cash_advance_paid": paid,
                                             "start_date": "2026-10-21", "end_date": "2026-10-22"})


class TestKeuanganBayarUangMuka:
    @pytest.mark.parametrize("who", [FIN, ACC])
    def test_peran_keuangan_boleh(self, env, who):
        _travel(env.db)
        out = run(etr.mark_advance_paid("t1", etr.AdvancePaidPayload(amount_paid=1000000, bank_account_id="ca-mdr",
                                                                     payment_date="2026-10-20"), user=who))
        assert out["new_status"] == "advance_paid"

    @pytest.mark.parametrize("who", [ANI, HR])  # 2026-11-02 (K25): HR tidak lagi membayar uang muka
    def test_peran_lain_ditolak(self, env, who):
        _travel(env.db)
        e = _err(etr.mark_advance_paid("t1", etr.AdvancePaidPayload(amount_paid=1000000), user=who))
        assert e.status_code == 403

    def test_penyetuju_tidak_berubah(self):
        assert "hr" in etr.APPROVER_ROLES and "tim_packing" not in etr.APPROVER_ROLES


class TestSettlementSebelumUangMuka:
    def test_settlement_ditolak_bila_uang_muka_belum_dibayar(self, env):
        _travel(env.db, approved=800000.0)
        e = _err(ets.create_settlement("t1", ets.SettlementCreate(actual_items=[
            {"date": "2026-10-25", "category": "transport", "amount": 800000}]), user=ACC))
        assert e.status_code == 400 and "belum dibayar" in e.detail
        assert env.db.employee_travel_settlements.docs == []

    def test_uang_muka_ditolak_bila_settlement_sudah_ada(self, env):
        _travel(env.db, approved=0.0)
        env.db.employee_travel_settlements.docs.append({"id": "s1", "travel_request_id": "t1",
                                                        "settlement_number": "TS-1", "status": "draft"})
        e = _err(etr.mark_advance_paid("t1", etr.AdvancePaidPayload(amount_paid=300000), user=FIN))
        assert e.status_code == 400 and "TS-1" in e.detail and env.jes == []

    def test_posting_settlement_basi_ditolak(self, env):
        _travel(env.db, approved=800000.0, paid=800000.0, status="advance_paid")
        env.db.employee_travel_settlements.docs.append({"id": "s1", "travel_request_id": "t1", "settlement_number": "TS-1",
                                                        "status": "approved", "advance_received": 0.0, "total_actual": 800000.0,
                                                        "difference": -800000.0, "settlement_type": "additional"})
        e = _err(ets.post_settlement_gl("s1", ets.PostPayload(), user=FIN))
        assert e.status_code == 400 and "berbeda" in e.detail and env.jes == []


# ── Butir 7 ─────────────────────────────────────────────────────────────────────
class TestRekeningDanTanggalPilihan:
    def _approved_kasbon(self, db):
        db.dewi_kasbon_requests.docs.append({"id": "ka", "employee_id": "emp-a", "type": "kasbon", "status": "hr_approved",
                                             "amount": 500000.0, "outstanding_balance": 500000.0, "request_number": "KSB-A"})

    def test_kasbon_cair_pakai_rekening_dan_tanggal_cair(self, env):
        self._approved_kasbon(env.db)
        body = {"disbursement_date": "2026-10-15", "deduction_start_period": "2026-12", "cash_account_id": "ca-kk"}
        out = run(kas.finance_disburse("ka", FakeRequest(body), db=env.db, user=FIN))
        assert out["ok"] and out["request"]["disbursement_account_code"] == "1-1101"
        je = env.jes[-1]
        assert je["date"] == date(2026, 10, 15)
        assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in je["lines"]] == [
            ("1-1320", 500000.0, 0), ("1-1101", 0, 500000.0)]

    def test_kasbon_cair_rekening_tak_dikenal_ditolak(self, env):
        self._approved_kasbon(env.db)
        e = _err(kas.finance_disburse("ka", FakeRequest({"cash_account_id": "palsu"}), db=env.db, user=FIN))
        assert e.status_code == 400 and env.db.dewi_kasbon_requests.docs[0]["status"] == "hr_approved"

    def test_uang_muka_dinas_pakai_rekening_dan_tanggal(self, env):
        _travel(env.db)
        run(etr.mark_advance_paid("t1", etr.AdvancePaidPayload(amount_paid=1000000, bank_account_id="ca-mdr",
                                                               payment_date="2026-10-20"), user=FIN))
        je = env.jes[-1]
        assert je["date"] == date(2026, 10, 20)
        assert [ln["account_code"] for ln in je["lines"]] == ["1-1610", "1-1202"]

    def test_klaim_pakai_rekening_dan_tanggal(self, env):
        env.db.rahaza_expense_claims.docs.append({"id": "c1", "claim_number": "EC-1", "status": "approved",
                                                  "total_amount": 150000.0, "employee_id": "u-acc", "employee_name": "Tutut"})
        run(eec.disburse_claim("c1", eec.DisbursePayload(bank_account_id="ca-kk", payment_date="2026-10-25"), user=FIN))
        je = env.jes[-1]
        assert je["date"] == date(2026, 10, 25) and je["lines"][1]["account_code"] == "1-1101"

    def test_tanggal_format_salah_ditolak(self):
        e = _err_sync(lambda: shared.parse_ymd("15/10/2026", field="tanggal pencairan"))
        assert e.status_code == 400

    def test_frontend_tanpa_daftar_hardcode_dan_kirim_rekening(self):
        pr = _src("frontend", "src", "components", "erp", "RahazaPayrollRunModule.jsx")
        assert "BANK_OPTIONS" not in pr and "'1-1200'" not in pr and "usePaymentCashAccounts" in pr
        sel = _src("frontend", "src", "components", "erp", "SdmCashAccountSelect.jsx")
        assert "/api/rahaza/payment-cash-accounts" in sel
        for f in ("EmployeeExpenseApprovalModule.jsx", "EmployeeExpenseModule.jsx"):
            s = _src("frontend", "src", "components", "erp", f)
            assert re.search(r"doAction\('disburse',\s*\{[^}]*bank_account_id", s), f
        for f in ("EmployeeExpenseApprovalModule.jsx", "EmployeeTravelModule.jsx"):
            s = _src("frontend", "src", "components", "erp", f)
            assert re.search(r"doAction\('advance-paid',\s*\{[^}]*bank_account_id[^}]*payment_date", s), f
        fk = _src("frontend", "src", "components", "erp", "FinanceKasbonModule.jsx")
        assert "cash_account_id" in fk and "'payroll_deduction'" not in fk
        assert any(r.path == "/api/rahaza/payment-cash-accounts" for r in runs.router.routes)


def _err_sync(fn):
    with pytest.raises(HTTPException) as ei:
        fn()
    return ei.value


# ── Butir 9 ─────────────────────────────────────────────────────────────────────
class TestMuatDemoDihapus:
    def test_endpoint_seed_tidak_ada(self):
        assert not any(getattr(r, "path", "").endswith("/kasbon/seed") for r in kas.router.routes)
        assert not hasattr(kas, "seed_demo")

    def test_tombol_muat_demo_tidak_ada(self):
        s = _src("frontend", "src", "components", "erp", "HRKasbonModule.jsx")
        assert not re.search(r"fetch\([^)]*kasbon/seed", s)
        assert not re.search(r">\s*Muat Demo\s*<", s) and "handleSeed" not in s


# ── Butir 10 ────────────────────────────────────────────────────────────────────
class TestPrivasiKasbon:
    def _data(self, db):
        for kid, emp in (("ka", "emp-a"), ("kb", "emp-b")):
            db.dewi_kasbon_requests.docs.append({"id": kid, "employee_id": emp, "status": "disbursed", "amount": 1.0,
                                                 "outstanding_balance": 1.0, "created_at": "2026-11-01", "type": "kasbon",
                                                 "deduction_start_period": "2026-11"})

    def _list(self, db, user, **kw):
        return run(kas.list_kasbon_requests(db=db, user=user, status=None, type=None, employee_id=kw.get("employee_id"),
                                            department=None, page=1, limit=50))

    def test_karyawan_hanya_melihat_miliknya(self, env):
        self._data(env.db)
        assert [r["id"] for r in self._list(env.db, ANI)["requests"]] == ["ka"]
        assert self._list(env.db, ANI, employee_id="emp-b")["requests"] == []
        assert _err(kas.get_kasbon_detail("kb", db=env.db, user=ANI)).status_code == 403
        assert run(kas.get_kasbon_detail("ka", db=env.db, user=ANI))["request"]["id"] == "ka"
        assert _err(kas.kasbon_stats(db=env.db, user=ANI)).status_code == 403
        assert _err(kas.get_employee_deductions("emp-b", period="2026-11", db=env.db, user=ANI)).status_code == 403
        assert run(kas.get_employee_deductions("emp-a", period="2026-11", db=env.db, user=ANI))["ok"]

    def test_hr_dan_keuangan_melihat_semua(self, env):
        self._data(env.db)
        assert self._list(env.db, HR)["total"] == 2 and self._list(env.db, FIN)["total"] == 2
        assert run(kas.get_kasbon_detail("kb", db=env.db, user=FIN))["ok"]
        assert run(kas.kasbon_stats(db=env.db, user=HR))["ok"]


# ── Butir 11 ────────────────────────────────────────────────────────────────────
class TestBulanLaluWIB:
    def test_last_month_period_tanpa_toisostring(self):
        s = _src("frontend", "src", "components", "erp", "RahazaPayrollRunModule.jsx")
        m = re.search(r"function lastMonthPeriod\(.*?\)\s*\{(.*?)\n\}", s, re.S)
        assert m, "lastMonthPeriod tidak ditemukan"
        body = m.group(1)
        assert "toISOString" not in body and "wibDateParts" in body
        sel = _src("frontend", "src", "components", "erp", "SdmCashAccountSelect.jsx")
        assert "timeZone: 'Asia/Jakarta'" in sel

    def test_tanggal_bawaan_backend_wib(self):
        from datetime import datetime
        assert shared.WIB.key == "Asia/Jakarta"
        assert shared._today_wib() == datetime.now(shared.WIB).date()


# ── Butir 12 ────────────────────────────────────────────────────────────────────
class TestNotifikasiPemohon:
    def _notifs(self, db, uid):
        return [n for n in db.notifications.docs if n.get("user_id") == uid]

    def test_kasbon_disetujui_dan_ditolak(self, env):
        for kid in ("k1", "k2"):
            env.db.dewi_kasbon_requests.docs.append({"id": kid, "employee_id": "emp-a", "status": "submitted",
                                                     "amount": 400000.0, "type_label": "Kasbon", "request_number": kid})
        run(kas.hr_review_kasbon("k1", FakeRequest({"action": "approve"}), db=env.db, user=HR))
        run(kas.hr_review_kasbon("k2", FakeRequest({"action": "reject", "notes": "kurang"}), db=env.db, user=HR))
        ns = self._notifs(env.db, "u-ani")
        assert [n["subtype"] for n in ns] == ["kasbon_approved", "kasbon_rejected"]
        assert all(n["meta"]["link_module"] == "portal-kasbon" for n in ns)

    def test_dinas_disetujui_dan_ditolak(self, env):
        _travel(env.db, tid="t1", status="submitted")
        _travel(env.db, tid="t2", status="submitted")
        run(etr.approve_travel_request("t1", etr.ApprovePayload(), user=HR))
        run(etr.reject_travel_request("t2", etr.RejectPayload(reason="anggaran"), user=HR))
        ns = self._notifs(env.db, "u-acc")
        assert [n["subtype"] for n in ns] == ["travel_request_approved", "travel_request_rejected"]
        assert all(n["meta"]["link_module"] == "portal-dashboard" for n in ns)

    def test_klaim_disetujui_dan_ditolak(self, env):
        for cid in ("c1", "c2"):
            env.db.rahaza_expense_claims.docs.append({"id": cid, "claim_number": cid, "status": "submitted",
                                                      "total_amount": 1.0, "employee_id": "u-acc", "title": "Taksi"})
        run(eec.approve_claim("c1", eec.ApprovePayload(), user=HR))
        run(eec.reject_claim("c2", eec.RejectPayload(reason="tanpa struk"), user=HR))
        ns = self._notifs(env.db, "u-acc")
        assert [n["subtype"] for n in ns] == ["expense_claim_approved", "expense_claim_rejected"]

    def test_tautan_menu_portal_saya_nyata(self):
        nav = _src("frontend", "src", "components", "erp", "portal-shell", "portalNav.js")
        reg = _src("frontend", "src", "components", "erp", "moduleRegistry.js")
        for mid in ("portal-kasbon", etr.SELF_LINK_MODULE, eec.SELF_LINK_MODULE):
            assert f"id: '{mid}'" in nav and f"'{mid}':" in reg, mid
