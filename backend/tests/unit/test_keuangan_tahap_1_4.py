"""Audit Keuangan tahap 1–4 (2026-11-04): SSOT hutang (pemasok + CMT), posisi kas dari buku besar,
uang muka karyawan dari rekening (Kas Kecil disatukan), Beranda Keuangan.
"""
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_w2d_keuangan import DB  # noqa: E402  (FakeDB + aggregate secukupnya)
import core.payables as pay  # noqa: E402
import core.cash_position as cp  # noqa: E402
import routes.rahaza_petty_cash as pc  # noqa: E402

FIN = {"id": "u-fin", "name": "Fin", "email": "fin@x", "role": "accounting"}
TODAY = date(2026, 11, 4)


def run(c):
    return asyncio.run(c)


def _line(db, je, d, code, debit, credit, src="manual"):
    db.rahaza_journal_lines.docs.append({"id": f"l-{je}-{code}", "je_id": je, "date": d, "account_code": code,
                                         "debit": debit, "credit": credit, "source_module": src})


@pytest.fixture
def db():
    d = DB()
    d.rahaza_coa_accounts.docs += [{"code": "1-1100", "is_group": True}, {"code": "1-1101", "parent_code": "1-1100", "active": True},
                                   {"code": "1-1200", "is_group": True}, {"code": "1-1201", "parent_code": "1-1200", "active": True},
                                   {"code": "1-1610", "active": True}, {"code": "6-2400", "type": "EXPENSE", "active": True}]
    d.rahaza_cash_accounts.docs += [{"id": "kk", "code": "1-1101", "name": "Kas Kecil", "gl_account_code": "1-1101", "active": True},
                                    {"id": "bca", "code": "1-1201", "name": "BCA", "gl_account_code": "1-1201", "active": True}]
    return d


# ── SSOT hutang ──────────────────────────────────────────────────────────────
def test_hutang_gabung_pemasok_dan_cmt_tanpa_draf_dan_cmt_belum_dijurnal_terpisah(db):
    db.rahaza_ap_invoices.docs += [
        {"id": "a1", "invoice_number": "AP-1", "vendor_name": "Kain", "status": "sent", "total": 1000, "balance": 1000,
         "due_date": "2026-11-01", "gl_je_id": "j"},
        {"id": "a2", "invoice_number": "AP-2", "vendor_name": "Kain", "status": "partial_paid", "total": 500, "paid_amount": 200,
         "balance": 300, "due_date": "2026-12-01", "gl_je_id": "j"},
        {"id": "a3", "invoice_number": "AP-3", "vendor_name": "Draf", "status": "draft", "total": 900, "balance": 900},
    ]
    db.dewi_cmt_payments.docs += [
        {"id": "c1", "payment_code": "CMT-1", "cmt_name": "Jahit A", "status": "posted", "net_amount": 400,
         "paid_amount": 0, "outstanding_amount": 400, "created_at": "2026-08-01", "gl_je_id": "jc"},
        {"id": "c2", "payment_code": "CMT-2", "cmt_name": "Jahit B", "status": "approved", "net_amount": 250,
         "paid_amount": 0, "outstanding_amount": 250, "created_at": "2026-10-30"},
        {"id": "c3", "payment_code": "CMT-3", "cmt_name": "Jahit C", "status": "paid", "net_amount": 99, "outstanding_amount": 0},
        # lahir draft, jurnal otomatis gagal → hutang nyata, ikut sebagai "belum dijurnal"
        {"id": "c4", "payment_code": "CMT-4", "cmt_name": "Jahit D", "status": "draft", "net_amount": 60,
         "paid_amount": 0, "outstanding_amount": 60, "created_at": "2026-11-01"},
    ]
    rows = run(pay.open_payable_rows(db))
    assert {r["number"] for r in rows} == {"AP-1", "AP-2", "CMT-1", "CMT-2", "CMT-4"}  # draf AP & lunas tidak ikut
    ag = pay.aging(rows, TODAY)
    assert ag["total"] == 1000 + 300 + 400 and ag["unposted_total"] == 250 + 60         # CMT belum dijurnal terpisah
    assert ag["buckets"]["1_30"] == 1000 and ag["buckets"]["current"] == 300 and ag["buckets"]["90_plus"] == 400
    assert ag["overdue"] == 1400 and ag["details"][0]["number"] == "CMT-1"              # paling lama di atas


# ── posisi kas dari buku besar ───────────────────────────────────────────────
def test_posisi_kas_dari_buku_besar_tanpa_transfer_dan_saldo_awal(db):
    _line(db, "ob", "2026-10-01", "1-1201", 5_000, 0, "opening_balance")
    _line(db, "t1", "2026-11-02", "1-1201", 0, 700, "bank_transfer")
    _line(db, "t1", "2026-11-02", "1-1101", 700, 0, "bank_transfer")
    _line(db, "s1", "2026-11-03", "1-1201", 1_200, 0, "marketplace_settlement")
    _line(db, "e1", "2026-11-03", "1-1101", 0, 150, "expense")
    _line(db, "x", "2026-11-03", "6-2400", 150, 0, "expense")                         # bukan akun kas
    out = run(cp.cash_position(db, "2026-11-01", "2026-11-04"))
    assert out["balance"] == 5_000 + 1_200 - 150
    assert (out["cash_in"], out["cash_out"]) == (1_200, 150)                            # transfer & saldo awal tidak dihitung


# ── uang muka karyawan dari rekening ─────────────────────────────────────────
@pytest.fixture
def adv_env(db, monkeypatch):
    db.rahaza_employees.docs.append({"id": "e1", "name": "Budi", "employee_code": "K-01", "active": True})
    posted = []

    async def fake_post(db_, je_date, memo, event_type, source_ref, lines, user, **kw):
        posted.append({"source_ref": source_ref, "lines": lines})
        return {"ok": True, "je_id": f"je{len(posted)}", "je_number": f"JE-{len(posted)}"}

    async def fake_map(db_, ev):
        return {"debit_petty_cash": "1-1101", "debit_employee_advance": "1-1610"}

    async def no_log(*a, **k):
        return None

    monkeypatch.setattr(pc, "get_db", lambda: db)
    monkeypatch.setattr(pc, "_create_posted_je", fake_post)
    monkeypatch.setattr(pc, "_find_existing_je", lambda *a, **k: asyncio.sleep(0, None))
    monkeypatch.setattr(pc, "get_mapping", fake_map)
    monkeypatch.setattr(pc, "log_activity", no_log)
    import core.fin_statements as fs
    import routes.rahaza_payroll_shared as ps

    async def cash_codes(db_):
        return {"1-1101", "1-1201"}
    monkeypatch.setattr(fs, "cash_account_codes", cash_codes)
    monkeypatch.setattr(ps, "HTTPException", HTTPException)
    return posted


def test_uang_muka_dari_rekening_dan_sisa_kembali_ke_rekening_pilihan(db, adv_env):
    posted = adv_env
    out = run(pc.create_advance(pc.AdvanceCreateIn(cash_account_id="bca", employee_id="e1", amount=500,
                                                   txn_date="2026-11-01", settle_days=3), FIN))
    adv = out["advance"]
    assert adv["fund_id"] is None and adv["cash_gl_code"] == "1-1201" and adv["due_date"] == "2026-11-04"
    assert {(ln["account_code"], ln["debit"], ln["credit"]) for ln in posted[0]["lines"]} == {("1-1610", 500, 0), ("1-1201", 0, 500)}
    listed = run(pc.list_advances(status="open", employee_id=None, fund_id=None, user=FIN))
    assert listed["total_open"] == 500 and listed["items"][0]["cash_account_name"] == "BCA"
    # pertanggungjawaban: nota 380 + sisa 120 dikembalikan ke Kas Kecil
    run(pc.settle_advance(adv["id"], pc.AdvanceSettleIn(items=[pc.SettleItem(account_code="6-2400", amount=380)],
                                                        returned_amount=120, settle_date="2026-11-03",
                                                        return_cash_account_id="kk"), FIN))
    lines = {(ln["account_code"], ln["debit"], ln["credit"]) for ln in posted[1]["lines"]}
    assert lines == {("6-2400", 380, 0), ("1-1101", 120, 0), ("1-1610", 0, 500)}
    assert not db.rahaza_petty_cash_funds.docs                                           # tanpa dana kas kecil


def test_uang_muka_tolak_rekening_bukan_kas(db, adv_env):
    db.rahaza_cash_accounts.docs.append({"id": "aneh", "name": "Salah", "gl_account_code": "6-2400", "active": True})
    with pytest.raises(HTTPException) as e:
        run(pc.create_advance(pc.AdvanceCreateIn(cash_account_id="aneh", employee_id="e1", amount=10), FIN))
    assert e.value.status_code == 400 and not db.rahaza_petty_cash_txns.docs
