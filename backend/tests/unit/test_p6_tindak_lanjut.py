"""Uji regresi HERMETIK paket P6 (2026-11-02) — tindak lanjut paket akses/keuangan/marketing/SDM.

Satu kelas uji per butir perintah:
  1 kunci jurnal pencairan `<nomor>@<id>` di pemeriksa lama · 2 sinkron tidak menimpa credit_ap pilihan Finance
  3 tombol tutup/kunci periode & tutup tahun · 4 sisa Peta Akun Channel (kartu + cek S5)
  5 Kas Kecil: rekening sumber & jurnal-dulu · 6 posting settlement dinas kirim rekening
  7 payroll dengan potongan manual · 8 PDF slip run draft · 9 /trigger cek run ganda

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import asyncio
import importlib.util
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

import core.finance_sync as fs  # noqa: E402
import routes.marketing_settlements as ms  # noqa: E402
import routes.payroll_automation as pa  # noqa: E402
import routes.rahaza_payroll_payslips as slips_mod  # noqa: E402
import routes.rahaza_payroll_runs as runs  # noqa: E402
import routes.rahaza_petty_cash as pc  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402

run = asyncio.run

HR = {"id": "u-hr", "role": "hr", "name": "Brenda HR", "email": "hr@x"}
FIN = {"id": "u-fin", "role": "accounting", "name": "Fatimah", "email": "fin@x"}


def _src(*parts):
    p = os.path.join(REPO, *parts)
    if not os.path.exists(p):
        pytest.skip(f"sumber tidak tersedia: {p}")
    return open(p, encoding="utf-8").read()


def _script(name):
    p = os.path.join(REPO, "scripts", f"{name}.py")
    if not os.path.exists(p):
        pytest.skip(f"skrip tidak tersedia: {p}")
    spec = importlib.util.spec_from_file_location(f"_uji_{name}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _err(coro):
    with pytest.raises(HTTPException) as ei:
        run(coro)
    return ei.value


def _coa(code, name, parent=None, group=False, typ="ASSET"):
    return {"code": code, "name": name, "parent_code": parent, "is_group": group, "active": True, "type": typ}


def _balanced(lines):
    d = round(sum(float(x.get("debit") or 0) for x in lines), 2)
    c = round(sum(float(x.get("credit") or 0) for x in lines), 2)
    return d == c and d > 0


# ── Butir 1 ─────────────────────────────────────────────────────────────────────
class TestKunciJurnalPencairan:
    def test_ref_q_menerima_kunci_baru_dan_lama(self):
        mod = _script("verify_pencairan_finance")
        rx = mod.ref_q("GATE42-1")["$regex"]
        assert re.search(rx, ms.doc_je_ref("GATE42-1", "doc-uuid"))   # kunci baru <nomor>@<id>
        assert re.search(rx, "GATE42-1")                               # kunci lama (nomor mentah)
        assert not re.search(rx, "GATE42-10") and not re.search(rx, "GATE42-1-2")

    def test_pemeriksa_lama_tidak_lagi_mencocokkan_nomor_mentah(self):
        v = _src("scripts", "verify_pencairan_finance.py")
        assert not re.search(r'"source_ref":\s*f"\{TAG\}-1"', v)
        t = _src("backend", "tests", "test_iter210_marketing_pencairan.py")
        assert 'e.get("source_ref") ==' not in t and t.count("_ref_is(e.get(\"source_ref\")") == 2


# ── Butir 2 ─────────────────────────────────────────────────────────────────────
class TestSinkronCreditAp:
    def test_aturan_murni(self):
        need = fs.cmt_ap_credit_needs_fix
        assert need({"mapping": {}, "updated_by": "u-fin"})                                  # kosong
        assert need({"mapping": {"credit_ap": "2-1100"}, "updated_by": "u-fin"})              # bawaan lama
        assert need({"mapping": {"credit_ap": "2-1199"}, "updated_by": "system"})             # belum disentuh
        assert not need({"mapping": {"credit_ap": "2-1110"}})
        assert not need({"mapping": {"credit_ap": "2-1120"}, "updated_by": "u-fin"})          # pilihan lama pengguna
        assert not need({"mapping": {"credit_ap": "2-1100"}, "user_roles": ["credit_ap"]})    # dipilih lewat layar
        assert not need({"mapping": {}, "user_removed_roles": ["credit_ap"]})

    @pytest.fixture
    def db(self, monkeypatch):
        db = FakeDB()
        for code, typ in (("2-1110", "LIABILITY"), ("2-1120", "LIABILITY"), ("1-1403", "ASSET"), ("5-2200", "EXPENSE"),
                          ("5-4200", "EXPENSE"), ("2-1100", "LIABILITY"), ("4-9000", "OTHER_INCOME")):
            db.rahaza_coa_accounts.docs.append(_coa(code, code, typ=typ))
        db.rahaza_posting_profiles.docs.append({
            "event_type": "cmt_ap_invoice", "active": True, "updated_by": "system",
            "mapping": {"debit_cmt_wip_internal": "1-1403", "debit_cmt_expense_internal": "5-2200",
                        "debit_cmt_expense_maklon": "5-4200", "credit_ap": "2-1100", "debit_penalty_income": "4-9000"}})

        async def fin_gate(request):
            return dict(FIN)

        async def noop(*a, **k):
            return None
        monkeypatch.setattr(pp, "_require_fin", fin_gate)
        monkeypatch.setattr(pp, "get_db", lambda: db)
        monkeypatch.setattr(pp, "log_activity", noop)
        return db

    def _credit_ap(self, db):
        return db.rahaza_posting_profiles.docs[0]["mapping"]["credit_ap"]

    def test_bawaan_lama_diperbaiki_sekali(self, db):
        rep = {}
        run(fs._sync_auto_settings(db, rep))
        assert self._credit_ap(db) == "2-1110" and rep["posting_profile_fixed"]
        rep2 = {}
        run(fs._sync_auto_settings(db, rep2))
        assert "posting_profile_fixed" not in rep2

    def test_ubah_nilai_lalu_sync_nilai_tetap(self, db):
        run(fs._sync_auto_settings(db, {}))
        prof = db.rahaza_posting_profiles.docs[0]
        run(pp.update_profile("cmt_ap_invoice", FakeRequest({"mapping": dict(prof["mapping"], credit_ap="2-1120")})))
        assert "credit_ap" in db.rahaza_posting_profiles.docs[0]["user_roles"]
        for _ in range(2):  # dua kali "restart"
            rep = {}
            run(fs._sync_auto_settings(db, rep))
            assert "posting_profile_fixed" not in rep
        assert self._credit_ap(db) == "2-1120"
        # pengguna bahkan boleh kembali ke 2-1100 dengan sengaja
        prof = db.rahaza_posting_profiles.docs[0]
        run(pp.update_profile("cmt_ap_invoice", FakeRequest({"mapping": dict(prof["mapping"], credit_ap="2-1100")})))
        run(fs._sync_auto_settings(db, {}))
        assert self._credit_ap(db) == "2-1100"


# ── Butir 3 ─────────────────────────────────────────────────────────────────────
class TestTombolPeriode:
    def test_tombol_tutup_kunci_dinonaktifkan_bila_belum_berakhir(self):
        s = _src("frontend", "src", "components", "erp", "RahazaPeriodsModule.jsx")
        assert "thisMonthWIB" in s and "periodNotEndedReason" in s
        assert s.count("disabled={!!blockReason}") == 2 and s.count("title={blockReason || undefined}") == 2

    def test_tombol_tutup_tahun_sebelum_31_des(self):
        s = _src("frontend", "src", "components", "erp", "RahazaPeriodsExtras.jsx")
        assert "todayWIB" in s and "yearNotEnded" in s and "title={yearBlockReason || undefined}" in s
        assert re.search(r"disabled=\{[^}]*yearNotEnded", s)


# ── Butir 4 ─────────────────────────────────────────────────────────────────────
class TestSisaPetaAkunChannel:
    def test_kartu_dashboard_dihapus(self):
        s = _src("frontend", "src", "components", "erp", "FinanceDashboard.jsx")
        assert not re.search(r"id:\s*'fin-channel-gl'", s) and not re.search(r"label:\s*'Peta Akun Channel'", s)

    def test_s5_aturan_baru_tanpa_peta(self):
        mod = _script("verify_finance_sync")
        act = {c: _coa(c, n, typ="REVENUE") for c, n in (
            ("4-1111", "Penjualan – Shopee GHS"), ("4-1112", "Penjualan – Shopee Daluna"),
            ("4-1119", "Penjualan – Shopee Lain-lain"), ("4-1121", "Penjualan – TikTok Daluna"))}
        act["4-1110"] = _coa("4-1110", "Penjualan Shopee", group=True, typ="REVENUE")
        ok = [{"account_code": "SHP-01", "platform": "shopee", "coa_revenue_code": "4-1111"},
              {"account_code": "TTS-01", "platform": "tiktokshop", "coa_revenue_code": "4-1121"}]
        bad, conflict = mod.s5_store_revenue_issues(ok, act, {})   # tanpa baris peta → tetap hijau
        assert bad == [] and conflict == []
        stores = ok + [{"account_code": "SHP-02", "platform": "shopee", "coa_revenue_code": "4-1111"},   # dipakai bersama
                       {"account_code": "SHP-03", "platform": "shopee", "coa_revenue_code": "4-1119"},   # penampung
                       {"account_code": "SHP-04", "platform": "shopee", "coa_revenue_code": "4-1121"},   # kelompok salah
                       {"account_code": "SHP-05", "platform": "shopee", "coa_revenue_code": "4-1110"},   # header
                       {"account_code": "SHP-06", "platform": "shopee"}]                                 # kosong
        bad, _ = mod.s5_store_revenue_issues(stores, act, {})
        assert [b.split(":")[0] for b in bad] == ["SHP-02", "SHP-03", "SHP-04", "SHP-05", "SHP-06"]
        _, conflict = mod.s5_store_revenue_issues(ok, act, {"SHP-01": {"credit_revenue": "4-1112"}})
        assert conflict == ["SHP-01:4-1112≠4-1111"]

    def test_s5_tidak_lagi_mewajibkan_baris_peta(self):
        s = _src("scripts", "verify_finance_sync.py")
        assert "not cm or" not in s and "s5_store_revenue_issues(stores, act, maps)" in s


# ── Butir 5 ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def kas(monkeypatch):
    db = FakeDB()
    db.rahaza_coa_accounts.docs = [
        _coa("1-1100", "Kas", group=True), _coa("1-1101", "Kas Kecil", "1-1100"),
        _coa("1-1200", "Bank", group=True), _coa("1-1201", "Bank BCA", "1-1200"), _coa("1-1202", "Bank Mandiri", "1-1200"),
        _coa("6-2900", "Beban Umum & Lain-lain", typ="EXPENSE"),
    ]
    db.rahaza_cash_accounts.docs = [
        {"id": "ca-kk", "code": "1-1101", "name": "Kas Kecil", "gl_account_code": "1-1101", "active": True},
        {"id": "ca-bca", "code": "1-1201", "name": "Bank BCA", "gl_account_code": "1-1201", "active": True},
        {"id": "ca-mdr", "code": "1-1202", "name": "Bank Mandiri", "gl_account_code": "1-1202", "active": True},
    ]
    jes = []

    async def fake_je(dbx, je_date, memo, source_module, source_ref, lines_raw, user, **kw):
        if getattr(fake_je, "fail", None):
            return {"ok": False, "error": fake_je.fail}
        jes.append({"source_module": source_module, "source_ref": source_ref, "lines": lines_raw})
        return {"ok": True, "je_id": f"je-{len(jes)}", "je_number": f"JE-{len(jes):04d}"}

    async def fake_mapping(dbx, event_type):
        return {"petty_cash_replenish": {"debit_petty_cash": "1-1101", "credit_bank_default": "1-1201"}}.get(event_type, {})

    async def no_existing(*a, **k):
        return None

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(pc, "get_db", lambda: db)
    monkeypatch.setattr(pc, "log_activity", noop)
    monkeypatch.setattr(pc, "_create_posted_je", fake_je)
    monkeypatch.setattr(pc, "_find_existing_je", no_existing)
    monkeypatch.setattr(pc, "get_mapping", fake_mapping)
    fake_je.fail = None
    return types.SimpleNamespace(db=db, jes=jes, fake_je=fake_je)


class TestKasKecil:
    @pytest.mark.parametrize("code,needle", [
        ("1-1203", "tidak ditemukan"),       # Bank BRI hard-code lama: tidak ada di COA
        ("1-1101", "kas kecil"),             # akun dana kas kecil itu sendiri
        ("6-2900", "bukan akun kas/bank"),   # akun beban
        ("1-1200", "header"),                # akun induk
    ])
    def test_rekening_sumber_tidak_sah_ditolak(self, kas, code, needle):
        e = _err(pc.create_fund(pc.FundCreate(name="KK Uji", opening_balance=500_000, bank_account_code=code), dict(FIN)))
        assert e.status_code == 400 and needle in e.detail.lower()
        assert kas.db.rahaza_petty_cash_funds.docs == [] and kas.db.rahaza_petty_cash_txns.docs == [] and kas.jes == []

    def test_buat_dana_jurnal_dulu(self, kas):
        out = run(pc.create_fund(pc.FundCreate(name="KK Uji", opening_balance=500_000, bank_account_code="1-1202"), dict(FIN)))
        assert out["current_balance"] == 500_000 and out["bank_account_code"] == "1-1202"
        lines = {(x["account_code"], "D" if x["debit"] else "C") for x in kas.jes[0]["lines"]}
        assert lines == {("1-1101", "D"), ("1-1202", "C")} and _balanced(kas.jes[0]["lines"])

    def test_buat_dana_jurnal_gagal_dana_tidak_lahir(self, kas):
        kas.fake_je.fail = "periode 2026-11 closed"
        e = _err(pc.create_fund(pc.FundCreate(name="KK Uji", opening_balance=500_000, bank_account_code="1-1201"), dict(FIN)))
        assert e.status_code == 400 and "closed" in e.detail
        assert kas.db.rahaza_petty_cash_funds.docs == [] and kas.db.rahaza_petty_cash_txns.docs == []

    def _fund(self, kas, bank="1-1202"):
        return run(pc.create_fund(pc.FundCreate(name="KK Uji", opening_balance=100_000, bank_account_code=bank), dict(FIN)))

    def test_isi_ulang_jurnal_gagal_saldo_tetap(self, kas):
        f = self._fund(kas)
        kas.fake_je.fail = "akun 1-1202 tidak aktif"
        e = _err(pc.replenish_fund(f["id"], pc.ReplenishIn(amount=50_000, bank_account_code="1-1201"), dict(FIN)))
        assert e.status_code == 400
        assert kas.db.rahaza_petty_cash_funds.docs[0]["current_balance"] == 100_000
        assert [t["txn_type"] for t in kas.db.rahaza_petty_cash_txns.docs] == ["opening"]

    def test_isi_ulang_sukses_dan_bawaan_rekening_dana(self, kas):
        f = self._fund(kas)
        out = run(pc.replenish_fund(f["id"], pc.ReplenishIn(amount=50_000), dict(FIN)))
        assert out["new_balance"] == 150_000 and kas.db.rahaza_petty_cash_funds.docs[0]["current_balance"] == 150_000
        assert ("1-1202", 50_000) in [(x["account_code"], x["credit"]) for x in kas.jes[-1]["lines"]]

    def test_isi_ulang_dari_kas_kecil_sendiri_ditolak(self, kas):
        f = self._fund(kas)
        e = _err(pc.replenish_fund(f["id"], pc.ReplenishIn(amount=50_000, bank_account_code="1-1101"), dict(FIN)))
        assert e.status_code == 400 and kas.db.rahaza_petty_cash_funds.docs[0]["current_balance"] == 100_000

    def test_daftar_dana_menyebut_akun_kas_kecil(self, kas):
        assert run(pc.list_funds(dict(FIN)))["petty_cash_account_code"] == "1-1101"

    def test_frontend_tanpa_rekening_hardcode(self):
        s = _src("frontend", "src", "components", "erp", "PettyCashModule.jsx")
        assert not re.search(r'SelectItem value="1-1\d{3}"', s) and "bank_account_code: '1-1201'" not in s
        assert "usePaymentCashAccounts" in s and "petty_cash_account_code" in s
        assert "toISOString().slice(0, 10)" not in s


# ── Butir 6 ─────────────────────────────────────────────────────────────────────
class TestPostingSettlementDinas:
    def test_kirim_rekening_dan_pratinjau_rekening_pilihan(self):
        s = _src("frontend", "src", "components", "erp", "EmployeeTravelSettlementModule.jsx")
        assert re.search(r"doAction\('post',\s*\{\s*bank_account_id", s)
        prev = s[s.index("function GLPreview"):s.index("// ─ Settlement Form")]
        assert "1-1201" not in prev and "bankAccount?.gl_account_code" in prev
        assert "usePaymentCashAccounts" in s


# ── Butir 7 ─────────────────────────────────────────────────────────────────────
PAYROLL_MAP = {"debit_salary_expense": "6-2100", "credit_salary_payable": "2-1200",
               "credit_tax_pph21": "2-1301", "credit_bpjs_payable": "2-1500"}


@pytest.fixture
def pay(monkeypatch):
    db = FakeDB()
    db.rahaza_payroll_runs.docs.append({"id": "r1", "run_number": "PR-1", "status": "draft",
                                        "period_from": "2026-10-01", "period_to": "2026-10-31"})
    db.rahaza_payslips.docs.append({
        "id": "s1", "run_id": "r1", "employee_id": "emp-a", "employee_code": "E01", "gross_pay": 5_000_000.0,
        "deductions": [{"type": "bpjs_kesehatan", "label": "BPJS Kes", "amount": 50_000},
                       {"type": "pph21", "label": "PPh21", "amount": 25_000}],
        "deductions_total": 75_000.0, "net_pay": 4_925_000.0})
    jes = []
    mapping = dict(PAYROLL_MAP)

    async def fake_je(dbx, je_date, memo, source_module, source_ref, lines_raw, user, **kw):
        jes.append({"source_module": source_module, "source_ref": source_ref, "lines": lines_raw})
        return {"ok": True, "je_id": f"je-{len(jes)}", "je_number": f"JE-{len(jes):04d}"}

    async def fake_mapping(dbx, event_type):
        return dict(mapping) if event_type == "payroll_finalize" else {}

    async def hr_gate(request):
        return dict(HR)

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(rp, "_create_posted_je", fake_je)
    monkeypatch.setattr(rp, "get_mapping", fake_mapping)
    for mod in (runs, slips_mod):
        monkeypatch.setattr(mod, "get_db", lambda: db)
        monkeypatch.setattr(mod, "log_activity", noop)
        monkeypatch.setattr(mod, "_require_hr", hr_gate)
    return types.SimpleNamespace(db=db, jes=jes, mapping=mapping)


class TestPayrollPotonganManual:
    def test_agregator_menghitung_potongan_manual(self):
        t = rp.payroll_deduction_totals([{"deductions": [{"type": "pph21", "amount": 10}], "manual_deduction": 100_000},
                                         {"deductions": [], "manual_deduction": "x"}])
        assert t["manual"] == 100_000 and t["pph21"] == 10 and t["other"] == 0
        assert t["by_type"][rp.MANUAL_DEDUCTION_KEY] == 100_000

    def _adjust_and_finalize(self, pay):
        res = run(slips_mod.adjust_payslip("r1", "s1", FakeRequest({"deduction": 100_000, "notes": "ganti rugi"})))
        assert res["run_totals"]["total_deductions"] == 175_000
        return run(runs.finalize_run("r1", FakeRequest()))

    def test_run_dengan_potongan_manual_bisa_final_dan_seimbang(self, pay):
        out = self._adjust_and_finalize(pay)
        assert out["status"] == "finalized" and out["deductions_by_type"][rp.MANUAL_DEDUCTION_KEY] == 100_000
        lines = pay.jes[0]["lines"]
        assert _balanced(lines)
        got = {(x["account_code"], x["debit"], x["credit"]) for x in lines}
        assert ("6-2100", 5_000_000, 0) in got                    # beban gaji tetap bruto
        assert ("2-1200", 0, 4_825_000) in got                    # neto ke karyawan
        assert ("4-9000", 0, 100_000) in got                      # potongan manual → Pendapatan Lain-Lain

    def test_peran_credit_other_deduction_dihormati(self, pay):
        pay.mapping["credit_other_deduction"] = "2-1900"
        self._adjust_and_finalize(pay)
        assert ("2-1900", 0, 100_000) in {(x["account_code"], x["debit"], x["credit"]) for x in pay.jes[0]["lines"]}

    def test_header_lama_tanpa_kunci_manual_tetap_bisa_diposting(self, pay):
        run(slips_mod.adjust_payslip("r1", "s1", FakeRequest({"deduction": 100_000, "notes": "ganti rugi"})))  # K34: alasan wajib
        r = dict(pay.db.rahaza_payroll_runs.docs[0], total_pph21=25_000, total_bpjs_employee=50_000, total_kasbon=0,
                 total_other_deductions=0, deductions_by_type={"pph21": 25_000, "bpjs_kesehatan": 50_000})
        res = run(rp.post_payroll_run(pay.db, r, dict(HR)))
        assert res["ok"] and _balanced(pay.jes[0]["lines"])

    def test_komponen_tetap_ditolak_bila_benar_tidak_konsisten(self, pay):
        r = dict(pay.db.rahaza_payroll_runs.docs[0], total_gross=5_000_000, total_deductions=175_000, total_net=4_825_000)
        res = run(rp.post_payroll_run(pay.db, r, dict(HR)))   # slip tanpa potongan manual → selisih 100.000
        assert not res["ok"] and "tidak konsisten" in res["error"] and pay.jes == []


# ── Butir 8 ─────────────────────────────────────────────────────────────────────
class TestPdfSlipDraft:
    def test_aturan_sama_dengan_daftar_slip(self):
        import inspect
        src = inspect.getsource(slips_mod.export_payslip_pdf)
        assert "_can_view_all_payslips(request, user)" in src and "only_published_slips(db, [slip])" in src


# ── Butir 9 ─────────────────────────────────────────────────────────────────────
# 2026-11-06 (Tahap 2): /trigger (jalur run kedua yang membuat run hantu) DIHAPUS — run gaji hanya lewat
# POST /api/rahaza/payroll-runs (yang sudah punya cek run ganda). Dasbor kini membaca run sungguhan.
@pytest.fixture
def trig(monkeypatch):
    db = FakeDB()
    db.rahaza_employees.docs = [{"id": "emp-a", "name": "Ani"}, {"id": "emp-b", "name": "Budi"},
                                {"id": "emp-t", "name": "Tanti", "active": False}]
    db.rahaza_payroll_profiles.docs = [{"employee_id": "emp-a", "pay_scheme": "monthly", "active": True}]

    async def auth_ok(request):
        return dict(HR)
    monkeypatch.setattr(pa, "_require_hr", auth_ok)
    monkeypatch.setattr(pa, "get_db", lambda: db)
    return db


class TestTriggerRunGanda:
    def test_jalur_run_kedua_dihapus(self):
        assert not hasattr(pa, "trigger_payroll_run") and not hasattr(pa, "set_schedule")
        paths = {r.path for r in pa.router.routes}
        assert not any(p.endswith(("/trigger", "/schedule", "/attendance-sync")) for p in paths)

    def test_dasbor_membaca_run_sungguhan(self, trig):
        from utils.waktu import wib_year
        y = wib_year()
        trig.rahaza_payroll_runs.docs = [
            {"id": "r1", "run_number": "PR-1", "status": "finalized", "payment_status": "paid",
             "period_from": f"{y}-01-01", "period_to": f"{y}-01-31", "total_net": 5_000_000, "created_at": "2"},
            {"id": "r2", "run_number": "PR-2", "status": "draft", "period_from": f"{y}-02-01",
             "period_to": f"{y}-02-28", "total_net": 1_000_000, "created_at": "3"}]
        out = run(pa.payroll_dashboard(FakeRequest()))
        assert out["total_disbursed_ytd"] == 5_000_000 and out["run_summary"]["draft"]["count"] == 1
        assert out["latest_run"]["run_number"] == "PR-2"
        assert out["employee_profile_coverage"]["with_payroll_profile"] == 1
        assert out["employee_profile_coverage"]["total_active_employees"] == 2
