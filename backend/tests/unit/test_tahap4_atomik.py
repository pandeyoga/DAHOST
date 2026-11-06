"""Tahap 4 (6 Nov 2026) — pola P9: transisi status non-atomik & proses ganda.

Setiap uji memanggil handler DUA KALI: bersamaan (permintaan kedua disisipkan TEPAT saat efek samping
pertama berjalan — klik ganda / dua pengguna) atau "basi" (dokumen diubah pengguna lain di sela baca &
tulis). Yang diuji: efek samping (stok, kas, jurnal, dokumen turunan, kabar) terjadi SEKALI, yang kalah
mendapat 409 berbahasa Indonesia, dan kunci/klaim dilepas bila proses gagal.

Jalankan:  cd backend && python -m pytest tests/unit/test_tahap4_atomik.py -q
"""
import asyncio
import copy
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from _fake_mongo import FakeRequest  # noqa: E402
from core import doc_lock  # noqa: E402

FIN = {"id": "u-fin", "name": "Keuangan Uji", "email": "fin@x", "role": "accounting"}
HR = {"id": "u-hr", "name": "HR Uji", "email": "hr@x", "role": "hr"}
SA = {"id": "u-sa", "name": "Super Uji", "email": "sa@x", "role": "superadmin"}


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


def _auth(user):
    async def f(*_a, **_k):
        return dict(user)
    return f


def _ret(value):
    async def f(*_a, **_k):
        return value
    return f


class _Coll(fm.FakeCollection):
    """+ find_one_and_update (penghitung nomor: $inc/$setOnInsert/upsert, kembalikan SESUDAH)."""

    async def find_one_and_update(self, q, upd, upsert=False, return_document=None, **_kw):
        for d in self.docs:
            if fm.match(d, q):
                break
        else:
            if not upsert:
                return None
            d = {k: v for k, v in q.items() if not k.startswith("$")}
            d.update(copy.deepcopy(upd.get("$setOnInsert") or {}))
            self.docs.append(d)
        for k, v in (upd.get("$set") or {}).items():
            d[k] = copy.deepcopy(v)
        for k, v in (upd.get("$inc") or {}).items():
            d[k] = (d.get(k) or 0) + v
        return copy.deepcopy(d)


class DB(fm.FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _Coll(name)
        return self._cols[name]


def stale(db, coll, **changes):
    """Bacaan `find_one` BERIKUTNYA pada koleksi ini mengembalikan dokumen lama, lalu dokumen tersimpan
    langsung diubah (`changes`) — meniru pengguna lain yang menulis di sela baca & tulis handler."""
    col = db[coll]
    orig = col.find_one
    st = {"done": False}

    async def fo(q=None, projection=None, **kw):
        doc = await orig(q, projection, **kw)
        if doc is not None and not st["done"]:
            st["done"] = True
            for d in col.docs:
                if fm.match(d, q):
                    d.update(copy.deepcopy(changes))
                    break
        return doc
    col.find_one = fo


def interleave(monkeypatch, obj, name, second, out: list):
    """Panggilan PERTAMA `obj.name` menjalankan `second()` dulu (permintaan kedua yang datang saat efek
    samping pertama berjalan); hasil/galatnya disimpan di `out`."""
    orig = getattr(obj, name)
    st = {"n": 0}

    async def wrapped(*a, **k):
        st["n"] += 1
        if st["n"] == 1:
            try:
                out.append(await second())
            except HTTPException as e:
                out.append(e)
        return await orig(*a, **k)
    monkeypatch.setattr(obj, name, wrapped)


def counting(monkeypatch, obj, name, result=None):
    calls = []

    async def f(*a, **k):
        calls.append((a, k))
        return result(*a, **k) if callable(result) else (result if result is not None else {"ok": True})
    monkeypatch.setattr(obj, name, f)
    return calls


def _409(x):
    return isinstance(x, HTTPException) and x.status_code == 409


def _ditolak(x):
    """Permintaan kedua ditolak: 409 (kalah klaim) atau 400 (melihat status yang sudah diklaim)."""
    return isinstance(x, HTTPException) and x.status_code in (400, 409)


# ══════════════════════════ 0. helper core.doc_lock ═══════════════════════════════
def test_doc_lock_klaim_kedua_409_lepas_lalu_kunci_basi_bisa_diambil():
    db = fm.FakeDB()
    db.x.docs.append({"id": "d1", "status": "draft"})
    tok = run(doc_lock.claim(db, "x", "d1", field="k"))
    with pytest.raises(HTTPException) as e:
        run(doc_lock.claim(db, "x", "d1", field="k", busy="sibuk"))
    assert e.value.status_code == 409 and e.value.detail == "sibuk"
    with pytest.raises(HTTPException) as e:
        run(doc_lock.claim(db, "x", "nope", field="k", not_found="tidak ada"))
    assert e.value.status_code == 404
    run(doc_lock.release(db, "x", "d1", "token-lain", field="k"))       # token asing tidak melepas
    assert db.x.docs[0]["k"] == tok
    run(doc_lock.release(db, "x", "d1", tok, field="k"))
    assert db.x.docs[0]["k"] is None
    # kunci basi (proses mati) boleh diambil alih
    db.x.docs[0].update(k="mati", k_at=datetime.now(timezone.utc) - timedelta(minutes=30))
    assert run(doc_lock.claim(db, "x", "d1", field="k"))
    # syarat tambahan (status) ikut diperiksa
    db.x.docs[0].update(k=None)
    with pytest.raises(HTTPException):
        run(doc_lock.claim(db, "x", "d1", field="k", extra={"status": "posted"}))
    with pytest.raises(HTTPException) as e:
        doc_lock.require_matched(fm._Result(), "kalah")
    assert e.value.status_code == 409 and e.value.detail == "kalah"


# ══════════════════════════ A. Uang ═══════════════════════════════════════════════
def test_bayar_tagihan_cmt_klik_ganda_kas_dan_jurnal_sekali(monkeypatch):
    import routes.dewi_maklon_finance as dmf
    import routes.rahaza_posting as rp
    db = fm.FakeDB()
    db.dewi_cmt_payments.docs.append({"id": "pay1", "payment_code": "PAY-CMT-1", "net_amount": 500000.0,
                                      "paid_amount": 0.0, "status": "posted", "gl_je_id": "je-ap"})
    db.rahaza_cash_accounts.docs.append({"id": "kas1", "name": "Kas Besar"})
    monkeypatch.setattr(dmf, "get_db", lambda: db)
    monkeypatch.setattr(dmf, "log_activity", _noop)
    out = []
    pays = counting(monkeypatch, rp, "post_ap_payment", {"ok": True, "je_id": "je-1", "je_number": "JE-1"})
    payload = dmf.CmtPayIn(cash_account_id="kas1", amount=500000)
    interleave(monkeypatch, rp, "post_ap_payment",
               lambda: dmf.pay_cmt_payment("pay1", payload, user=FIN), out)
    res = run(dmf.pay_cmt_payment("pay1", payload, user=FIN))
    assert res["payment_status"] == "paid" and _409(out[0]) and "sedang dibayar" in out[0].detail
    assert len(pays) == 1 and len(db.rahaza_cash_movements.docs) == 1 and len(db.dewi_cmt_disbursements.docs) == 1
    p = db.dewi_cmt_payments.docs[0]
    assert p["paid_amount"] == 500000.0 and p["pay_lock"] is None          # kunci dilepas
    with pytest.raises(HTTPException) as e:                                 # klik lagi sesudah lunas
        run(dmf.pay_cmt_payment("pay1", payload, user=FIN))
    assert e.value.status_code == 400 and len(db.rahaza_cash_movements.docs) == 1


def test_batal_bayar_cmt_ganda_paid_amount_turun_sekali(monkeypatch):
    import routes.dewi_maklon_finance as dmf
    import routes.rahaza_posting as rp
    db = fm.FakeDB()
    db.dewi_cmt_payments.docs.append({"id": "pay1", "payment_code": "PAY-CMT-1", "net_amount": 500000.0,
                                      "paid_amount": 500000.0, "status": "paid", "gl_je_id": "je-ap"})
    db.dewi_cmt_disbursements.docs.append({"id": "d1", "payment_id": "pay1", "amount": 200000.0, "status": "posted"})
    db.rahaza_cash_movements.docs.append({"id": "d1", "amount": 200000})
    monkeypatch.setattr(dmf, "get_db", lambda: db)
    voids = counting(monkeypatch, rp, "_void_je_by_source", {"ok": True, "voided": True, "je_number": "JE-9"})
    out = []
    interleave(monkeypatch, rp, "_void_je_by_source",
               lambda: dmf.void_cmt_disbursement("pay1", "d1", user=FIN), out)
    run(dmf.void_cmt_disbursement("pay1", "d1", user=FIN))
    assert _409(out[0]) and len(voids) == 1
    assert db.dewi_cmt_payments.docs[0]["paid_amount"] == 300000.0          # dulu 100.000 (dikurangi 2×)
    with pytest.raises(HTTPException) as e:                                 # void lagi sesudah selesai
        run(dmf.void_cmt_disbursement("pay1", "d1", user=FIN))
    assert e.value.status_code == 404 and db.dewi_cmt_payments.docs[0]["paid_amount"] == 300000.0


def _kasbon_env(monkeypatch, status="disbursed"):
    import routes.dewi_kasbon as kas
    db = fm.FakeDB()
    db.dewi_kasbon_requests.docs.append({
        "id": "kb", "employee_id": "emp-b", "type": "kasbon", "status": status, "amount": 400000.0,
        "outstanding_balance": 400000.0, "paid_amount": 0.0, "repayments": [], "request_number": "KSB-1",
        "created_by": "u-pemohon"})
    monkeypatch.setattr(kas, "resolve_payment_account",
                        _auth({"gl_code": "1-1101", "name": "Kas", "cash_account_id": "ca-kk"}))
    return kas, db


def test_angsuran_kasbon_klik_ganda_jurnal_dan_saldo_sekali(monkeypatch):
    kas, db = _kasbon_env(monkeypatch)
    jes = counting(monkeypatch, kas, "_post_kasbon_gl", {"ok": True, "je_id": "je-r", "je_number": "JE-R"})
    body = {"amount": 150000, "method": "manual", "date": "2026-11-02", "cash_account_id": "ca-kk"}
    out = []
    interleave(monkeypatch, kas, "_post_kasbon_gl",
               lambda: kas.record_repayment("kb", FakeRequest(body), db=db, user=FIN), out)
    run(kas.record_repayment("kb", FakeRequest(body), db=db, user=FIN))
    k = db.dewi_kasbon_requests.docs[0]
    assert _409(out[0]) and len(jes) == 1 and len(k["repayments"]) == 1
    assert k["outstanding_balance"] == 250000.0 and k["paid_amount"] == 150000.0 and k["repay_lock"] is None


def test_review_kasbon_kalah_balapan_409_tanpa_kabar_berlawanan(monkeypatch):
    kas, db = _kasbon_env(monkeypatch, status="submitted")
    monkeypatch.setattr(kas, "ensure_not_self_approval", lambda *a, **k: None)
    monkeypatch.setattr(kas, "kasbon_limit_check", _auth({"ok": True, "errors": []}))
    monkeypatch.setattr(kas, "_own_employee_ids", _auth([]))
    notes = counting(monkeypatch, kas, "notify_requester")
    stale(db, "dewi_kasbon_requests", status="hr_rejected")              # HR lain menolak lebih dulu
    with pytest.raises(HTTPException) as e:
        run(kas.hr_review_kasbon("kb", FakeRequest({"action": "approve"}), db=db, user=HR))
    assert e.value.status_code == 409 and notes == []
    assert db.dewi_kasbon_requests.docs[0]["status"] == "hr_rejected"
    # batal pemohon tidak menimpa kasbon yang baru saja disetujui
    db.dewi_kasbon_requests.docs[0]["status"] = "submitted"
    stale(db, "dewi_kasbon_requests", status="hr_approved")
    with pytest.raises(HTTPException) as e:
        run(kas.cancel_kasbon("kb", FakeRequest({"reason": "x"}), db=db, user=HR))
    assert e.value.status_code == 409 and db.dewi_kasbon_requests.docs[0]["status"] == "hr_approved"


def _loan_db():
    db = fm.FakeDB()
    db.rahaza_employee_loans.docs.append({"id": "ln1", "loan_number": "LN-1", "employee_id": "e1",
                                          "status": "active", "outstanding_balance": 1000000.0,
                                          "paid_amount": 0.0, "paid_installments": 0})
    return db


def test_angsuran_pinjaman_manual_ganda_dan_potong_payroll_sekali_per_run(monkeypatch):
    import routes.rahaza_employee_loans as rel
    import routes.rahaza_posting as rp
    db = _loan_db()
    monkeypatch.setattr(rel, "get_db", lambda: db)
    monkeypatch.setattr(rel, "require_auth", _auth(FIN))
    monkeypatch.setattr(rel, "log_activity", _noop)
    out = []
    coll = db.rahaza_employee_loan_repayments
    orig_insert = coll.insert_one

    async def insert_and_race(doc):
        if not out:
            try:
                out.append(await rel.manual_loan_repayment("ln1", FakeRequest({"repayment_amount": 300000})))
            except HTTPException as e:
                out.append(e)
        return await orig_insert(doc)
    coll.insert_one = insert_and_race
    run(rel.manual_loan_repayment("ln1", FakeRequest({"repayment_amount": 300000})))
    assert _409(out[0]) and len(coll.docs) == 1
    assert db.rahaza_employee_loans.docs[0]["outstanding_balance"] == 700000.0
    # potong payroll: run yang sama dikirim dua kali → dipotong SEKALI
    coll.insert_one = orig_insert
    jes = counting(monkeypatch, rp, "post_employee_loan_repayment_payroll", {"ok": True})
    body = {"payroll_run_id": "run-1", "period": "2026-10", "deduction_amount": 100000}
    run(rel.deduct_loan_from_payroll("ln1", FakeRequest(body)))
    again = run(rel.deduct_loan_from_payroll("ln1", FakeRequest(body)))
    assert again.get("already") is True and len(jes) == 1
    assert db.rahaza_employee_loans.docs[0]["outstanding_balance"] == 600000.0


def test_posting_penyesuaian_bank_ganda_mutasi_kas_sekali(monkeypatch):
    import routes.rahaza_bank_recon as rbr
    import routes.rahaza_posting as rp
    db = fm.FakeDB()
    db.rahaza_bank_recon_adjustments.docs.append({"id": "adj1", "status": "draft", "adjustment_type": "bank_charge",
                                                  "amount": 6500, "bank_account_id": "bca",
                                                  "adjustment_date": "2026-11-02"})
    monkeypatch.setattr(rbr, "get_db", lambda: db)
    monkeypatch.setattr(rbr, "_require_fin", _auth(FIN))
    monkeypatch.setattr(rbr, "log_activity", _noop)
    counting(monkeypatch, rp, "post_bank_recon_adjustment", {"ok": True, "je_id": "je", "je_number": "JE-B"})
    out = []
    interleave(monkeypatch, rp, "post_bank_recon_adjustment",
               lambda: rbr.post_bank_adjustment("adj1", FakeRequest()), out)
    run(rbr.post_bank_adjustment("adj1", FakeRequest()))
    assert _409(out[0]) and len(db.rahaza_cash_movements.docs) == 1
    assert db.rahaza_bank_recon_adjustments.docs[0]["status"] == "posted"
    with pytest.raises(HTTPException) as e:                                 # klik lagi sesudah selesai
        run(rbr.post_bank_adjustment("adj1", FakeRequest()))
    assert e.value.status_code == 400 and len(db.rahaza_cash_movements.docs) == 1


def _claim_db():
    db = fm.FakeDB()
    db.rahaza_expense_claims.docs.append({"id": "c1", "claim_number": "CLM-1", "employee_id": "u-emp",
                                          "employee_name": "Ani", "status": "approved", "total_amount": 250000.0})
    return db


def test_klaim_biaya_tolak_tidak_menyalip_pencairan_dan_setuju_basi_409(monkeypatch):
    import routes.employee_expense_claims as eec
    import routes.rahaza_posting as rp
    import routes.rahaza_posting_profiles as pp
    db = _claim_db()
    monkeypatch.setattr(eec, "get_db", lambda: db)
    monkeypatch.setattr(eec, "log_activity", _noop)
    monkeypatch.setattr(eec, "resolve_payment_account", _auth({"gl_code": "1-1201", "name": "BCA",
                                                                "cash_account_id": "bca"}))
    monkeypatch.setattr(pp, "get_mapping", _auth({"credit_cash_default": "1-1201"}))
    counting(monkeypatch, rp, "_create_posted_je", {"ok": True, "je_id": "je-c", "je_number": "JE-C"})
    out = []
    interleave(monkeypatch, rp, "_create_posted_je",
               lambda: eec.reject_claim("c1", eec.RejectPayload(reason="tidak sah"), user=HR), out)
    res = run(eec.disburse_claim("c1", eec.DisbursePayload(bank_account_id="bca", payment_date="2026-11-02"),
                                 user=FIN))
    assert res["new_status"] == "posted" and _409(out[0])
    assert db.rahaza_expense_claims.docs[0]["status"] == "posted"
    # setuju yang kalah balapan tidak mengirim kabar "disetujui"
    db.rahaza_expense_claims.docs[0].update(status="submitted")
    notes = counting(monkeypatch, eec, "_notify_claim_decision")
    monkeypatch.setattr(eec, "ensure_not_self_approval", lambda *a, **k: None)
    stale(db, "rahaza_expense_claims", status="rejected")
    with pytest.raises(HTTPException) as e:
        run(eec.approve_claim("c1", eec.ApprovePayload(note=""), user=HR))
    assert e.value.status_code == 409 and notes == []


def _travel_db():
    db = fm.FakeDB()
    db.employee_travel_requests.docs.append({
        "id": "t1", "trip_number": "TRV-1", "employee_id": "u-emp", "employee_name": "Budi", "status": "approved",
        "cash_advance_requested": 1000000.0, "cash_advance_approved": 1000000.0, "cash_advance_decided": True,
        "destination": "Bandung"})
    return db


def test_dinas_tolak_tidak_menyalip_bayar_uang_muka_dan_selesai_basi(monkeypatch):
    import routes.employee_travel_requests as etr
    import routes.rahaza_posting as rp
    import routes.rahaza_posting_profiles as pp
    db = _travel_db()
    monkeypatch.setattr(etr, "get_db", lambda: db)
    monkeypatch.setattr(etr, "log_activity", _noop)
    monkeypatch.setattr(etr, "resolve_payment_account", _auth({"gl_code": "1-1201", "name": "BCA",
                                                                "cash_account_id": "bca"}))

    async def role_code(_db, _ev, _role, default):
        return default
    monkeypatch.setattr(pp, "role_code", role_code)
    counting(monkeypatch, rp, "_create_posted_je", {"ok": True, "je_id": "je-t", "je_number": "JE-T"})
    out = []
    interleave(monkeypatch, rp, "_create_posted_je",
               lambda: etr.reject_travel_request("t1", etr.RejectPayload(reason="batal"), user=HR), out)
    res = run(etr.mark_advance_paid("t1", etr.AdvancePaidPayload(amount_paid=1000000, bank_account_id="bca",
                                                                  payment_date="2026-11-02"), user=FIN))
    assert res["new_status"] == "advance_paid" and _409(out[0])
    assert db.employee_travel_requests.docs[0]["status"] == "advance_paid"
    stale(db, "employee_travel_requests", status="rejected")
    with pytest.raises(HTTPException) as e:
        run(etr.complete_travel_request("t1", user=HR))
    assert e.value.status_code == 409 and db.employee_travel_requests.docs[0]["status"] == "rejected"


def test_penyelesaian_dinas_tolak_tidak_menyalip_posting_dan_posting_massal_hormati_kunci(monkeypatch):
    import routes.employee_travel_settlements as ets
    import routes.rahaza_posting as rp
    db = fm.FakeDB()
    db.employee_travel_settlements.docs.append({
        "id": "s1", "settlement_number": "STL-1", "status": "approved", "travel_request_id": "t1",
        "total_actual": 800000.0, "advance_received": 800000.0, "difference": 0.0, "settlement_type": "exact"})
    monkeypatch.setattr(ets, "get_db", lambda: db)
    monkeypatch.setattr(ets, "log_activity", _noop)

    async def stale_ok(*_a, **_k):
        return None
    monkeypatch.setattr(ets, "_stale_advance_error", stale_ok)
    monkeypatch.setattr(ets, "_travel_codes", _auth({"expense": "6-3400", "advance": "1-1610", "bank": "1-1201"}))
    counting(monkeypatch, rp, "_create_posted_je", {"ok": True, "je_id": "je-s", "je_number": "JE-S"})
    out = []
    interleave(monkeypatch, rp, "_create_posted_je",
               lambda: ets.reject_settlement("s1", ets.RejectPayload(reason="salah"), user=HR), out)
    run(ets.post_settlement_gl("s1", ets.PostPayload(), user=FIN))
    assert _409(out[0]) and db.employee_travel_settlements.docs[0]["status"] == "posted"
    # posting massal tidak menyerobot penyelesaian yang sedang dikunci proses lain
    db.employee_travel_settlements.docs.append({"id": "s2", "settlement_number": "STL-2", "status": "approved",
                                                "post_lock": "lain", "post_lock_at": datetime.now(timezone.utc)})
    res = run(ets.bulk_post_settlements(ets.BulkPostSettlementRequest(settlement_ids=["s2"]), user=FIN))
    assert res["failed_count"] == 1 and "Sedang diproses" in res["results"]["failed"][0]["reason"]


def test_kotak_masuk_sdm_tidak_menolak_yang_sudah_dibayar_atau_disetujui(monkeypatch):
    import routes.hr_approval_inbox as inbox
    db = fm.FakeDB()
    db.rahaza_expense_claims.docs.append({"id": "c1", "claim_number": "CLM-1", "status": "posted"})
    db.employee_travel_requests.docs.append({"id": "t1", "trip_number": "TRV-1", "status": "advance_paid"})
    db.rahaza_salary_adjustments.docs.append({"id": "a1", "status": "approved"})
    db.rahaza_employees.docs.append({"id": "e1", "resignation_status": "accepted"})
    monkeypatch.setattr(inbox, "get_db", lambda: db)
    monkeypatch.setattr(inbox, "log_activity", _noop)
    monkeypatch.setattr(inbox, "_require_approver_role", lambda u: None)
    monkeypatch.setattr(inbox, "_kabari_pemohon", _noop)
    p = inbox.ActionPayload(reason="tidak jadi")
    for typ, rid in (("expense_claim", "c1"), ("travel_request", "t1"), ("salary_adjustment", "a1"),
                     ("resignation", "e1")):
        with pytest.raises(HTTPException) as e:
            run(inbox.reject_request(typ, rid, p, user=HR))
        assert e.value.status_code == 409, typ
    assert db.rahaza_expense_claims.docs[0]["status"] == "posted"
    assert db.employee_travel_requests.docs[0]["status"] == "advance_paid"
    assert db.rahaza_salary_adjustments.docs[0]["status"] == "approved"
    assert db.rahaza_employees.docs[0]["resignation_status"] == "accepted"


def test_kotak_masuk_sdm_setuju_gaji_basi_409_profil_tidak_diubah(monkeypatch):
    import routes.hr_approval_inbox as inbox
    import routes.rahaza_payroll_profiles as rpp
    db = fm.FakeDB()
    db.rahaza_salary_adjustments.docs.append({"id": "a1", "status": "pending_hr", "employee_id": "e1"})
    monkeypatch.setattr(inbox, "get_db", lambda: db)
    monkeypatch.setattr(inbox, "log_activity", _noop)
    monkeypatch.setattr(inbox, "_require_approver_role", lambda u: None)
    applied = counting(monkeypatch, rpp, "apply_salary_adjustment_to_profile", {"effective_from": "2026-12-01"})
    stale(db, "rahaza_salary_adjustments", status="rejected")
    with pytest.raises(HTTPException) as e:
        run(inbox.approve_request("salary_adjustment", "a1", inbox.ActionPayload(note=""), user=HR))
    assert e.value.status_code == 409 and applied == []
    # jalur normal: status disetujui DULU, baru profil; profil gagal → status kembali
    db.rahaza_salary_adjustments.docs[0]["status"] = "pending_hr"

    async def boom(*_a, **_k):
        raise RuntimeError("profil terkunci")
    monkeypatch.setattr(rpp, "apply_salary_adjustment_to_profile", boom)
    with pytest.raises(RuntimeError):
        run(inbox.approve_request("salary_adjustment", "a1", inbox.ActionPayload(note=""), user=HR))
    assert db.rahaza_salary_adjustments.docs[0]["status"] == "pending_hr"


# ══════════════════════════ B. Stok ═══════════════════════════════════════════════
def _wms_env(monkeypatch, *movements):
    import routes.wms_receiving as wr
    db = fm.FakeDB()
    db.wh_pending_movements.docs.extend(copy.deepcopy(list(movements)))
    monkeypatch.setattr(wr, "get_db", lambda: db)
    monkeypatch.setattr(wr, "require_auth", _auth(SA))
    monkeypatch.setattr(wr, "log_activity", _noop)
    monkeypatch.setattr(wr.location_resolver, "location_exists", _ret(True))
    return wr, db


def _mv(mid, typ, expected=10):
    return {"id": mid, "ref_number": f"REF-{mid}", "type": typ, "status": "pending", "expected_qty": expected,
            "scanned_qty": 0, "unit": "pcs", "material_id": "A", "material_code": "A-1", "material_name": "Kain A",
            "location_id": "L1", "source_type": "manual", "source_id": ""}


def test_scan_masuk_klik_ganda_stok_bertambah_sekali_dan_gagal_dikembalikan(monkeypatch):
    wr, db = _wms_env(monkeypatch, _mv("m1", "inbound"), _mv("m2", "inbound"))
    adds = counting(monkeypatch, wr.stock_service, "add", {})
    out = []
    data = wr.ScanInIn(scanned_qty=10, location_id="L1")
    interleave(monkeypatch, wr.stock_service, "add", lambda: wr.scan_in("m1", data, FakeRequest()), out)
    res = run(wr.scan_in("m1", data, FakeRequest()))
    m1 = db.wh_pending_movements.docs[0]
    assert res["status"] == "confirmed" and _ditolak(out[0]) and len(adds) == 1
    assert m1["scanned_qty"] == 10 and len(db.rahaza_fg_movements.docs) == 1
    # balapan murni: scan lain mencadangkan qty di sela baca & tulis → 409, stok tidak disentuh
    db.wh_pending_movements.docs.append(_mv("m3", "inbound"))
    stale(db, "wh_pending_movements", scanned_qty=4, status="partial")
    with pytest.raises(HTTPException) as e:
        run(wr.scan_in("m3", wr.ScanInIn(scanned_qty=6, location_id="L1"), FakeRequest()))
    assert e.value.status_code == 409 and len(adds) == 1 and db.wh_pending_movements.docs[2]["scanned_qty"] == 4

    async def boom(*_a, **_k):
        raise RuntimeError("db putus")
    monkeypatch.setattr(wr.stock_service, "add", boom)
    with pytest.raises(RuntimeError):
        run(wr.scan_in("m2", data, FakeRequest()))
    m2 = db.wh_pending_movements.docs[1]
    assert (m2["scanned_qty"], m2["status"]) == (0, "pending")            # cadangan qty dikembalikan


def test_scan_keluar_klik_ganda_stok_turun_sekali_dan_stok_kurang_dikembalikan(monkeypatch):
    wr, db = _wms_env(monkeypatch, _mv("o1", "outbound_rm", 5), _mv("o2", "outbound_rm", 5))
    issues = counting(monkeypatch, wr.stock_service, "issue", {"qty": 3})
    out = []
    data = wr.ScanOutIn(scanned_qty=5, location_id="L1")
    interleave(monkeypatch, wr.stock_service, "issue", lambda: wr.scan_out("o1", data, FakeRequest()), out)
    res = run(wr.scan_out("o1", data, FakeRequest()))
    assert res["status"] == "confirmed" and _ditolak(out[0]) and len(issues) == 1
    db.wh_pending_movements.docs.append(_mv("o3", "outbound_rm", 5))
    stale(db, "wh_pending_movements", scanned_qty=5, status="confirmed")
    with pytest.raises(HTTPException) as e:
        run(wr.scan_out("o3", data, FakeRequest()))
    assert e.value.status_code == 409 and len(issues) == 1

    async def kurang(mid, loc, qty, **_k):
        raise wr.stock_service.InsufficientStock(mid, loc, qty, 1)
    monkeypatch.setattr(wr.stock_service, "issue", kurang)
    with pytest.raises(HTTPException) as e:
        run(wr.scan_out("o2", data, FakeRequest()))
    assert e.value.status_code == 400 and db.wh_pending_movements.docs[1]["scanned_qty"] == 0
    # batal tidak menimpa movement yang baru saja di-scan penuh perangkat lain
    stale(db, "wh_pending_movements", status="confirmed", scanned_qty=5)
    with pytest.raises(HTTPException) as e:
        run(wr.cancel_pending("o2", FakeRequest()))
    assert e.value.status_code == 409 and db.wh_pending_movements.docs[1]["status"] == "confirmed"


def test_lepas_reservasi_fg_ganda_dilepas_sekali_dan_gagal_kembali_aktif(monkeypatch):
    import routes.rahaza_fg_matrix as fgm
    db = fm.FakeDB()
    db.rahaza_fg_reservations.docs += [{"id": "r1", "status": "active", "material_id": "A", "qty": 5,
                                        "reservation_no": "RSV-1"},
                                       {"id": "r2", "status": "active", "material_id": "A", "qty": 5}]
    monkeypatch.setattr(fgm, "get_db", lambda: db)
    monkeypatch.setattr(fgm, "require_auth", _auth(SA))
    monkeypatch.setattr(fgm, "log_activity", _noop)
    rel = counting(monkeypatch, fgm.stock_service, "release_material", {"released": 5})
    out = []
    interleave(monkeypatch, fgm.stock_service, "release_material",
               lambda: fgm.release_fg("r1", FakeRequest()), out)
    run(fgm.release_fg("r1", FakeRequest()))
    assert _409(out[0]) and len(rel) == 1 and db.rahaza_fg_reservations.docs[0]["status"] == "released"

    async def boom(*_a, **_k):
        raise RuntimeError("db putus")
    monkeypatch.setattr(fgm.stock_service, "release_material", boom)
    with pytest.raises(HTTPException) as e:
        run(fgm.release_fg("r2", FakeRequest()))
    assert e.value.status_code == 500 and db.rahaza_fg_reservations.docs[1]["status"] == "active"


def test_undo_dan_restore_penyesuaian_stok_ganda_stok_dibalik_sekali(monkeypatch):
    import routes.dewi_warehouse_smart as dws
    db = fm.FakeDB()
    db.rahaza_stock_ledger.docs.append({"id": "lg1", "op": "adjust", "delta": 5.0, "material_id": "A",
                                        "location_id": "L1", "created_at": datetime.now(timezone.utc)})
    db.rahaza_material_stock.docs.append({"material_id": "A", "location_id": "L1", "qty": 10.0})
    monkeypatch.setattr(dws, "get_db", lambda: db)
    monkeypatch.setattr(dws, "require_auth", _auth(SA))
    adj = counting(monkeypatch, dws.stock_service, "adjust", {})
    out = []
    interleave(monkeypatch, dws.stock_service, "adjust",
               lambda: dws.undo_stock_adjustment("lg1", FakeRequest()), out)
    run(dws.undo_stock_adjustment("lg1", FakeRequest()))
    # permintaan kedua melihat tanda undo yang sudah diklaim → ditolak, stok TIDAK dibalik lagi
    assert out[0].status_code in (400, 409) and len(adj) == 1
    assert db.rahaza_stock_ledger.docs[0]["soft_deleted"] is True
    out.clear()
    interleave(monkeypatch, dws.stock_service, "adjust",
               lambda: dws.restore_stock_adjustment("lg1", FakeRequest()), out)
    run(dws.restore_stock_adjustment("lg1", FakeRequest()))
    assert out[0].status_code in (400, 409) and len(adj) == 2
    assert db.rahaza_stock_ledger.docs[0]["soft_deleted"] is False


def test_finalisasi_kirim_pesanan_bersamaan_lapisan_hpp_dimakan_sekali(monkeypatch):
    import routes.fulfillment as ful
    from core import fg_cost_layers as fcl
    db = fm.FakeDB()
    db.marketing_orders.docs.append({"id": "o1", "order_id": "ORD-1", "fulfillment_status": "allocated",
                                     "fulfillment_items": [{"material_id": "A", "qty_allocated": 2, "sku_code": "S1"}]})
    db.wh_pending_movements.docs.append({"id": "m1", "source_id": "o1", "source_type": "fulfillment",
                                         "type": "outbound_fg", "status": "confirmed"})
    monkeypatch.setattr(ful, "log_activity", _noop)
    cogs = counting(monkeypatch, ful, "post_cogs_shipment", {"ok": True, "je_id": "je", "je_number": "JE-H"})
    eat = counting(monkeypatch, fcl, "consume_fifo", {"cogs": 20000.0, "layers_used": [], "uncosted_qty": 0})
    out = []
    interleave(monkeypatch, fcl, "consume_fifo", lambda: ful.finalize_fulfillment_dispatch(db, "o1", SA), out)
    res = run(ful.finalize_fulfillment_dispatch(db, "o1", SA))
    assert res.get("ok") is not False and out[0] == {"ok": False, "reason": "finalize_in_progress"}
    assert len(eat) == 1 and len(cogs) == 1 and db.marketing_orders.docs[0]["fulfillment_status"] == "dispatched"
    assert run(ful.finalize_fulfillment_dispatch(db, "o1", SA)) == {"ok": True, "already_dispatched": True}


def test_batal_dan_hapus_mi_tidak_menimpa_mi_yang_baru_dikeluarkan(monkeypatch):
    import routes.rahaza_inventory_workflow as riw
    db = fm.FakeDB()
    db.rahaza_material_issues.docs += [{"id": "mi1", "mi_number": "MI-1", "status": "pending_approval"},
                                       {"id": "mi2", "mi_number": "MI-2", "status": "draft"}]
    monkeypatch.setattr(riw, "get_db", lambda: db)
    monkeypatch.setattr(riw, "_require_admin", _auth(SA))
    stale(db, "rahaza_material_issues", status="issued")
    with pytest.raises(HTTPException) as e:
        run(riw.cancel_mi("mi1", FakeRequest()))
    assert e.value.status_code == 409 and db.rahaza_material_issues.docs[0]["status"] == "issued"
    db2 = fm.FakeDB()
    db2.rahaza_material_issues.docs.append({"id": "mi2", "mi_number": "MI-2", "status": "draft"})
    monkeypatch.setattr(riw, "get_db", lambda: db2)
    stale(db2, "rahaza_material_issues", status="pending_approval")
    with pytest.raises(HTTPException) as e:
        run(riw.delete_mi("mi2", FakeRequest()))
    assert e.value.status_code == 409 and len(db2.rahaza_material_issues.docs) == 1


def test_selesai_qc_terima_fg_bersamaan_kedua_409_dan_batal_tidak_menyalip(monkeypatch):
    import routes.dewi_cmt_packing as dcp
    import routes.shared as shared
    db = fm.FakeDB()
    db.cmt_receipts.docs += [{"id": "r1", "status": "on_qc"}, {"id": "r2", "status": "on_qc"}]
    monkeypatch.setattr(dcp, "get_db", lambda: db)
    monkeypatch.setattr(shared, "require_perm", _auth(SA))
    seen = []

    async def locked(rid, request):                 # selama QC diselesaikan, permintaan lain datang
        for coro in (dcp._finish_receipt(rid, request), dcp.reject_receipt(rid, FakeRequest({"reason": "x"}))):
            try:
                await coro
            except HTTPException as e:
                seen.append(e.status_code)
        db.cmt_receipts.docs[0]["status"] = "completed_qc"
        return {"ok": True}
    monkeypatch.setattr(dcp, "_finish_receipt_locked", locked)
    assert run(dcp._finish_receipt("r1", FakeRequest())) == {"ok": True}
    assert seen == [409, 409] and db.cmt_receipts.docs[0]["finish_lock"] is None
    assert db.cmt_receipts.docs[0]["status"] == "completed_qc"
    stale(db, "cmt_receipts", status="completed_qc")           # QC selesai di sela baca & tulis "batal"
    with pytest.raises(HTTPException) as e:
        run(dcp.reject_receipt("r2", FakeRequest({"reason": "x"})))
    assert e.value.status_code == 409 and db.cmt_receipts.docs[1]["status"] == "completed_qc"


def test_cutting_selesai_batal_dan_progres_kedua_menunggu_progres_berjalan(monkeypatch):
    import routes.cutting as cut
    db = fm.FakeDB()
    db.cutting_orders.docs.append({"id": "co1", "number": "CUT-1", "status": "in_progress", "produced_qty": 10,
                                   "consumed_input_qty": 5, "input_material_id": "K1", "input_unit": "kg"})
    monkeypatch.setattr(cut, "get_db", lambda: db)
    monkeypatch.setattr(cut, "_require_cutting_user", _auth(SA))
    monkeypatch.setattr(cut, "log_activity", _noop)
    monkeypatch.setattr(cut.cut_panel_value, "order_value_totals", _auth({"complete": True, "value_total": 1000.0}))
    seen = []

    async def locked(_db, oid, request, user):
        for coro in (cut.add_progress(oid, FakeRequest({})), cut.complete_order(oid, FakeRequest()),
                     cut.cancel_order(oid, FakeRequest({}))):
            try:
                await coro
            except HTTPException as e:
                seen.append(e.status_code)
        return {"ok": True}
    monkeypatch.setattr(cut, "_add_progress_locked", locked)
    run(cut.add_progress("co1", FakeRequest({})))
    assert seen == [409, 409, 409] and db.cutting_orders.docs[0]["status"] == "in_progress"
    assert db.cutting_orders.docs[0]["progress_lock"] is None
    stale(db, "cutting_orders", status="completed")
    with pytest.raises(HTTPException) as e:
        run(cut.cancel_order("co1", FakeRequest({})))
    assert e.value.status_code == 409 and db.cutting_orders.docs[0]["status"] == "completed"


def test_po_maklon_lama_konfirmasi_dan_dispatch_ganda_sekali(monkeypatch):
    import routes.dewi_maklon_pos as dmpos
    import routes.shared as shared
    db = DB()
    db.dewi_maklon_pos.docs.append({"id": "p1", "po_number": "MKL-1", "status": "draft", "client_id": "c1",
                                    "client_name": "Klien", "total_qty": 10,
                                    "items": [{"item_id": "i1", "artikel": "Kaos", "qty": 10, "seri_no": 1,
                                               "selling_price_per_pcs": 1000.0, "qty_dispatched": 0}]})
    db.dewi_maklon_dispatches.docs.append({"id": "d1", "dispatch_number": "DSP-1", "po_id": "p1", "status": "draft",
                                           "items": [{"item_id": "i1", "qty_dispatched": 4}]})
    monkeypatch.setattr(dmpos, "get_db", lambda: db)
    monkeypatch.setattr(dmpos, "log_activity", _noop)
    monkeypatch.setattr(shared, "assert_can_act", lambda *a, **k: None)
    out = []
    interleave(monkeypatch, dmpos, "_next_ar_invoice_number", lambda: dmpos.confirm_maklon_po("p1", user=SA), out)
    res = run(dmpos.confirm_maklon_po("p1", user=SA))
    assert res["status"] == "confirmed" and _ditolak(out[0]) and len(db.rahaza_ar_invoices.docs) == 1
    db.dewi_maklon_pos.docs.append({**copy.deepcopy(db.dewi_maklon_pos.docs[0]), "id": "p2", "status": "draft"})
    stale(db, "dewi_maklon_pos", status="confirmed")            # dikonfirmasi pengguna lain di sela baca & tulis
    with pytest.raises(HTTPException) as e:
        run(dmpos.confirm_maklon_po("p2", user=SA))
    assert e.value.status_code == 409 and len(db.rahaza_ar_invoices.docs) == 1
    stale(db, "dewi_maklon_dispatches", status="dispatched")      # dikonfirmasi pengguna lain lebih dulu
    with pytest.raises(HTTPException) as e:
        run(dmpos.confirm_dispatch("d1", user=SA))
    assert e.value.status_code == 409 and db.dewi_maklon_pos.docs[0]["items"][0]["qty_dispatched"] == 0


# ══════════════════════════ C. Dokumen turunan & transisi ═════════════════════════
def _pr_env(monkeypatch, status="approved"):
    import routes.dewi_procurement as dp
    db = DB()
    db.dewi_procurement_requests.docs.append({"id": "pr1", "request_number": "PR-1", "status": status,
                                              "requested_by": SA["id"], "total_estimated": 100000.0,
                                              "current_approver_stage": "dept",
                                              "items": [{"id": "it1", "name": "Kancing", "qty": 10,
                                                         "estimated_price": 10000, "uom": "pcs"}]})
    monkeypatch.setattr(dp, "get_db", lambda: db)
    monkeypatch.setattr(dp, "require_auth", _auth(SA))
    return dp, db


def test_po_dari_pr_klik_ganda_satu_po(monkeypatch):
    import routes.rahaza_po as rpo
    dp, db = _pr_env(monkeypatch)
    monkeypatch.setattr(rpo, "_resolve_supplier", _ret({"supplier_id": "s1", "vendor_name": "PT Uji"}))
    monkeypatch.setattr(rpo, "_norm_po_items", _ret([{"material_id": "A", "qty_ordered": 10, "unit_cost": 10000}]))
    monkeypatch.setattr(rpo, "_enrich_po", _noop)
    monkeypatch.setattr(rpo, "_gen_po_number", _ret("PO-0001"))
    out = []
    interleave(monkeypatch, rpo, "_gen_po_number",
               lambda: dp.create_po_from_pr("pr1", FakeRequest({"supplier_id": "s1"})), out)
    res = run(dp.create_po_from_pr("pr1", FakeRequest({"supplier_id": "s1"})))
    assert res["po_number"] == "PO-0001" and _409(out[0]) and len(db.rahaza_purchase_orders.docs) == 1
    pr = db.dewi_procurement_requests.docs[0]
    assert pr["status"] == "in_procurement" and pr["linked_po_id"] == res["id"] and pr["po_lock"] is None
    with pytest.raises(HTTPException) as e:                                   # klik lagi sesudah selesai
        run(dp.create_po_from_pr("pr1", FakeRequest({"supplier_id": "s1"})))
    assert e.value.status_code == 400 and len(db.rahaza_purchase_orders.docs) == 1


def test_pr_setuju_tolak_batal_basi_409(monkeypatch):
    dp, db = _pr_env(monkeypatch, status="submitted")
    ev = {"can_approve": True, "can_reject": True, "stage": "dept", "is_override": False,
          "override_reasons": [], "blocked_reason": None}
    monkeypatch.setattr(dp, "_chain_config", _ret({}))
    monkeypatch.setattr(dp, "_pr_chain", lambda *a, **k: ["dept"])
    monkeypatch.setattr(dp, "_eval_approval", lambda *a, **k: dict(ev))
    monkeypatch.setattr(dp, "_with_department", _auth(SA))
    monkeypatch.setattr(dp, "_status_after_stage", lambda *a, **k: "approved")
    monkeypatch.setattr(dp, "_next_stage_after", lambda *a, **k: None)
    notes = counting(monkeypatch, dp, "_notify_procurement_event")
    monkeypatch.setattr(dp, "_notify_requester", _noop)
    stale(db, "dewi_procurement_requests", status="rejected")
    with pytest.raises(HTTPException) as e:
        run(dp.approve_request("pr1", FakeRequest({})))
    assert e.value.status_code == 409 and notes == [] and db.dewi_procurement_requests.docs[0]["status"] == "rejected"
    db.dewi_procurement_requests.docs[0]["status"] = "submitted"
    stale(db, "dewi_procurement_requests", status="approved")
    with pytest.raises(HTTPException) as e:
        run(dp.reject_request("pr1", FakeRequest({"reason": "mahal"})))
    assert e.value.status_code == 409 and db.dewi_procurement_requests.docs[0]["status"] == "approved"
    db.dewi_procurement_requests.docs[0]["status"] = "submitted"
    stale(db, "dewi_procurement_requests", status="approved")
    with pytest.raises(HTTPException) as e:
        run(dp.cancel_request("pr1", FakeRequest({})))
    assert e.value.status_code == 409 and db.dewi_procurement_requests.docs[0]["status"] == "approved"


def test_po_pembelian_setuju_dan_batal_basi_409(monkeypatch):
    import routes.rahaza_po as rpo
    db = DB()
    db.rahaza_purchase_orders.docs.append({"id": "po1", "po_number": "PO-1", "status": "pending_approval",
                                           "current_approver_stage": "dept", "items": []})
    monkeypatch.setattr(rpo, "get_db", lambda: db)
    monkeypatch.setattr(rpo, "require_auth", _auth(SA))
    monkeypatch.setattr(rpo, "_require_admin", _auth(SA))
    monkeypatch.setattr(rpo, "log_activity", _noop)
    ev = {"can_approve": True, "can_reject": True, "stage": "dept", "is_override": False,
          "override_reasons": [], "blocked_reason": None}

    async def ctx(_db, po_id, _user):
        po = await _db.rahaza_purchase_orders.find_one({"id": po_id}, {"_id": 0})
        return po, ["dept", "finance"], dict(ev), {}
    monkeypatch.setattr(rpo, "_po_ctx", ctx)
    stale(db, "rahaza_purchase_orders", current_approver_stage="finance")   # tahap ini sudah disetujui orang lain
    with pytest.raises(HTTPException) as e:
        run(rpo.approve_po("po1", FakeRequest({})))
    assert e.value.status_code == 409 and db.rahaza_purchase_orders.docs[0].get("approval_steps") is None
    stale(db, "rahaza_purchase_orders", status="fully_received")
    with pytest.raises(HTTPException) as e:
        run(rpo.cancel_po("po1", FakeRequest({"reason": "x"})))
    assert e.value.status_code == 409 and db.rahaza_purchase_orders.docs[0]["status"] == "fully_received"


def test_qty_diterima_po_dua_gr_bersamaan_tidak_saling_menimpa():
    import routes.rahaza_po as rpo
    db = DB()
    db.rahaza_purchase_orders.docs.append({"id": "po1", "po_number": "PO-1", "status": "approved", "items": [
        {"id": "pi1", "material_id": "A", "qty_ordered": 20, "qty_received": 0}]})
    col = db.rahaza_purchase_orders
    orig = col.update_one
    st = {"raced": False}

    async def racing_update(q, upd, upsert=False):
        if not st["raced"]:                 # GR lain menulis tepat sebelum tulisan GR ini
            st["raced"] = True
            await orig({"id": "po1"}, {"$set": {"items": [{"id": "pi1", "material_id": "A", "qty_ordered": 20,
                                                            "qty_received": 5}], "status": "partially_received"}})
        return await orig(q, upd, upsert)
    col.update_one = racing_update
    run(rpo.update_po_received_qty(db, "po1", [{"material_id": "A", "po_item_id": "pi1", "qty": 8}]))
    po = col.docs[0]
    assert po["items"][0]["qty_received"] == 13 and po["status"] == "partially_received"   # dulu 8 (5 hilang)


def test_status_po_produksi_basi_409_tanpa_sinkron_keuangan(monkeypatch):
    import routes.production_pos as ppos
    import routes.production_maklon_bridge as bridge
    db = DB()
    db.production_pos.docs.append({"id": "pp1", "po_number": "PO-PRD-1", "status": "Confirmed",
                                   "business_type": "maklon"})
    monkeypatch.setattr(ppos, "get_db", lambda: db)
    monkeypatch.setattr(ppos, "require_auth", _auth(SA))
    monkeypatch.setattr(ppos, "check_role", lambda *a, **k: True)
    monkeypatch.setattr(ppos, "deny_klien", lambda *a, **k: None)
    sync = counting(monkeypatch, bridge, "try_sync_maklon_finance")
    stale(db, "production_pos", status="Distributed")
    with pytest.raises(HTTPException) as e:
        run(ppos.transition_po_status("pp1", FakeRequest({"status": "Distributed"})))
    assert e.value.status_code == 409 and sync == []


def test_kirim_buyer_ganda_efek_dispatch_sekali(monkeypatch):
    import routes.rahaza_shipments as rs
    db = DB()
    db.rahaza_shipments.docs.append({"id": "sh1", "status": "draft", "items": []})
    monkeypatch.setattr(rs, "get_db", lambda: db)
    monkeypatch.setattr(rs, "require_auth", _auth(SA))
    monkeypatch.setattr(rs, "log_audit", _noop)
    inv = counting(monkeypatch, rs, "_create_ar_invoice_from_shipment", None)
    stale(db, "rahaza_shipments", status="dispatched")
    with pytest.raises(HTTPException) as e:
        run(rs.change_status("sh1", {"status": "dispatched"}, FakeRequest()))
    assert e.value.status_code == 409 and inv == []


def test_kirim_material_ke_cmt_ganda_satu_surat_jalan_dan_gagal_kembali_draf(monkeypatch):
    import routes.wms_cmt_dispatches as wcd
    import routes.wms_delivery_notes as wdn
    db = DB()
    line = {"material_code": "K1", "material_name": "Kain", "qty": 10, "unit": "meter"}
    db.wh_cmt_dispatches.docs += [{"id": "d1", "dispatch_no": "DSP-1", "status": "draft", "cmt_name": "CMT A",
                                   "lines": [dict(line)]},
                                  {"id": "d2", "dispatch_no": "DSP-2", "status": "draft", "cmt_name": "CMT A",
                                   "lines": [dict(line)]}]
    monkeypatch.setattr(wcd, "get_db", lambda: db)
    monkeypatch.setattr(wcd, "require_auth", _auth(SA))
    monkeypatch.setattr(wdn, "_next_sj_number", _ret("SJ-CMT-0001"))
    out = []
    interleave(monkeypatch, wdn, "_next_sj_number", lambda: wcd.execute_dispatch("d1", FakeRequest(), {}), out)
    res = run(wcd.execute_dispatch("d1", FakeRequest(), {}))
    assert res["ok"] and _ditolak(out[0]) and len(db.wh_delivery_notes.docs) == 1
    assert db.wh_cmt_dispatches.docs[0]["status"] == "dispatched"

    async def boom(*_a, **_k):
        raise RuntimeError("penomoran gagal")
    monkeypatch.setattr(wdn, "_next_sj_number", boom)
    with pytest.raises(RuntimeError):
        run(wcd.execute_dispatch("d2", FakeRequest(), {}))
    assert db.wh_cmt_dispatches.docs[1]["status"] == "draft"


def test_job_produksi_dan_permintaan_material_klik_ganda_409(monkeypatch):
    import routes.production_execution as pe
    import routes.exceptions as exc
    db = DB()
    db.vendor_shipments.docs.append({"id": "vs1"})
    db.material_requests.docs.append({"id": "mr1", "status": "Pending"})
    for mod in (pe, exc):
        monkeypatch.setattr(mod, "get_db", lambda: db)
        monkeypatch.setattr(mod, "require_auth", _auth(SA))
        monkeypatch.setattr(mod, "deny_klien", lambda *a, **k: None)
    monkeypatch.setattr(pe, "require_write_actor", lambda *a, **k: None)
    monkeypatch.setattr(exc, "check_role", lambda *a, **k: True)
    seen = []

    async def job_locked(request, _db, body, user):
        try:
            await pe.create_job(FakeRequest(body))
        except HTTPException as e:
            seen.append(e.status_code)
        return {"ok": True}

    async def mr_locked(_db, req_id, body, user):
        try:
            await exc.update_material_request(req_id, FakeRequest(body))
        except HTTPException as e:
            seen.append(e.status_code)
        return {"ok": True}
    monkeypatch.setattr(pe, "_create_job_locked", job_locked)
    monkeypatch.setattr(exc, "_update_material_request_locked", mr_locked)
    run(pe.create_job(FakeRequest({"vendor_shipment_id": "vs1", "vendor_id": "v1"})))
    run(exc.update_material_request("mr1", FakeRequest({"status": "Approved"})))
    assert seen == [409, 409]
    assert db.vendor_shipments.docs[0]["job_lock"] is None and db.material_requests.docs[0]["decide_lock"] is None


def test_commit_dan_rollback_impor_marketing_saling_menunggu(monkeypatch):
    import routes.marketing_data_import as md
    db = DB()
    db[md.SESSIONS].docs.append({"id": "s1", "status": "mapped"})
    monkeypatch.setattr(md, "get_db", lambda: db)
    monkeypatch.setattr(md, "require_auth", _auth(SA))
    seen = []

    async def commit_locked(sid, request, body=None):
        for coro in (md.commit(sid, FakeRequest()), md.rollback(sid, FakeRequest())):
            try:
                await coro
            except HTTPException as e:
                seen.append(e.status_code)
        return {"ok": True}
    monkeypatch.setattr(md, "_commit_locked", commit_locked)
    assert run(md.commit("s1", FakeRequest())) == {"ok": True}
    assert seen == [409, 409] and db[md.SESSIONS].docs[0]["commit_lock"] is None


def test_ubah_faktur_setuju_tolak_tidak_saling_menyalip(monkeypatch):
    import routes.invoice_edit_requests as ier
    db = DB()
    db.invoice_edit_requests.docs.append({"id": "q1", "status": "Pending", "invoice_number": "INV-1"})
    monkeypatch.setattr(ier, "get_db", lambda: db)
    monkeypatch.setattr(ier, "_require_approver", _auth(FIN))
    monkeypatch.setattr(ier, "log_activity", _noop)
    seen = []

    async def approve_locked(_db, req_id, notes, user):
        try:
            await ier.reject_request(req_id, FakeRequest({"approval_notes": "tidak"}))
        except HTTPException as e:
            seen.append(e.status_code)
        await _db.invoice_edit_requests.update_one({"id": req_id}, {"$set": {"status": "Approved"}})
        return {"ok": True}
    monkeypatch.setattr(ier, "_approve_request_locked", approve_locked)
    run(ier.approve_request("q1", FakeRequest({})))
    assert seen == [409] and db.invoice_edit_requests.docs[0]["status"] == "Approved"


# ══════════════════════════ D. SDM ════════════════════════════════════════════════
def test_cuti_tolak_basi_409_tidak_menimpa_cuti_disetujui(monkeypatch):
    from core import leave_engine as le
    db = DB()
    db.rahaza_leave_requests.docs.append({"id": "lv1", "status": "pending_approval", "employee_id": "e1"})
    monkeypatch.setattr(le, "ensure_not_own_leave", _noop)
    stale(db, "rahaza_leave_requests", status="approved")
    with pytest.raises(HTTPException) as e:
        run(le.reject_leave_request(db, "lv1", HR, "tidak"))
    assert e.value.status_code == 409 and db.rahaza_leave_requests.docs[0]["status"] == "approved"


def test_lembur_setuju_tolak_batal_basi_409_tanpa_kabar(monkeypatch):
    import routes.rahaza_overtime as ot
    db = DB()
    db.rahaza_overtime_requests.docs.append({"id": "ot1", "status": "pending", "submitted_by": "u-emp"})
    monkeypatch.setattr(ot, "ensure_not_own_overtime", _noop)
    notes = counting(monkeypatch, ot, "notify_overtime_decision")
    for fn, args in ((ot.approve_overtime_request, ()), (ot.reject_overtime_request, ("x",))):
        db.rahaza_overtime_requests.docs[0]["status"] = "pending"
        stale(db, "rahaza_overtime_requests", status="cancelled")
        with pytest.raises(HTTPException) as e:
            run(fn(db, "ot1", HR, *args))
        assert e.value.status_code == 409
    assert notes == []
    db.rahaza_overtime_requests.docs[0]["status"] = "pending"
    monkeypatch.setattr(ot, "get_db", lambda: db)
    monkeypatch.setattr(ot, "require_auth", _auth(HR))
    stale(db, "rahaza_overtime_requests", status="approved")
    with pytest.raises(HTTPException) as e:
        run(ot.cancel_request("ot1", FakeRequest()))
    assert e.value.status_code == 409 and db.rahaza_overtime_requests.docs[0]["status"] == "approved"


def test_koreksi_absen_setuju_ganda_absensi_ditulis_sekali(monkeypatch):
    import routes.rahaza_attendance_corrections as rac
    import routes.rahaza_attendance as ra
    import utils.employee_identity as ei
    db = DB()
    db.rahaza_attendance_corrections.docs.append({"id": "k1", "status": "pending", "employee_id": "e1",
                                                  "date": "2026-11-02", "requested": {"clock_in": "07:30"},
                                                  "reason": "lupa absen"})
    monkeypatch.setattr(ei, "resolve_my_employee", _ret(None))
    monkeypatch.setattr(rac, "attendance_lock", _ret(None))
    monkeypatch.setattr(rac, "write_attendance_audit", _noop)

    async def build_doc(_db, body, user):
        return {"id": "ev1", **body}
    monkeypatch.setattr(ra, "_build_att_doc", build_doc)
    out = []
    interleave(monkeypatch, ra, "_build_att_doc", lambda: rac.decide_correction(db, "k1", HR, approve=True), out)
    res = run(rac.decide_correction(db, "k1", HR, approve=True))
    assert res["status"] == "approved" and _ditolak(out[0]) and len(db.rahaza_attendance_events.docs) == 1
    assert db.rahaza_attendance_corrections.docs[0]["status"] == "approved"
    # gagal di tengah → kembali menunggu (bisa diputus ulang)
    db.rahaza_attendance_corrections.docs.append({"id": "k2", "status": "pending", "employee_id": "e2",
                                                  "date": "2026-11-02", "requested": {}, "reason": "x"})

    async def boom(*_a, **_k):
        raise RuntimeError("tulis absen gagal")
    monkeypatch.setattr(ra, "_build_att_doc", boom)
    with pytest.raises(RuntimeError):
        run(rac.decide_correction(db, "k2", HR, approve=True))
    assert db.rahaza_attendance_corrections.docs[1]["status"] == "pending"


def test_penyesuaian_gaji_setuju_hr_basi_409_profil_tidak_berubah(monkeypatch):
    import routes.rahaza_salary_adjustments as rsa
    import routes.rahaza_payroll_profiles as rpp
    db = DB()
    db.rahaza_salary_adjustments.docs.append({"id": "a1", "status": "pending_hr", "employee_name": "Ani",
                                              "raise_pct": 5})
    monkeypatch.setattr(rsa, "get_db", lambda: db)
    monkeypatch.setattr(rsa, "_require_hr", _auth(HR))
    monkeypatch.setattr(rsa, "log_activity", _noop)
    applied = counting(monkeypatch, rpp, "apply_salary_adjustment_to_profile", {"effective_from": "2026-12-01"})
    stale(db, "rahaza_salary_adjustments", status="rejected")
    with pytest.raises(HTTPException) as e:
        run(rsa.approve_by_hr("a1", FakeRequest({})))
    assert e.value.status_code == 409 and applied == []
    db.rahaza_salary_adjustments.docs[0]["status"] = "pending_hr"
    monkeypatch.setattr(rsa, "_notify_employee_raise_approved", _noop)
    run(rsa.approve_by_hr("a1", FakeRequest({})))
    a = db.rahaza_salary_adjustments.docs[0]
    assert len(applied) == 1 and a["status"] == "approved" and a["applied_effective_from"] == "2026-12-01"
    db.rahaza_salary_adjustments.docs[0]["status"] = "pending_hr"
    stale(db, "rahaza_salary_adjustments", status="approved")
    with pytest.raises(HTTPException) as e:
        run(rsa.cancel_adjustment("a1", FakeRequest()))
    assert e.value.status_code == 409 and db.rahaza_salary_adjustments.docs[0]["status"] == "approved"


# ══════════════════════════ E. Keuangan: periode, faktur, selisih kirim ═══════════
def test_periode_buka_basi_tidak_membuka_periode_terkunci(monkeypatch):
    import routes.rahaza_periods as per
    db = DB()
    db.rahaza_periods.docs.append({"period_code": "2026-09", "status": "closed"})
    monkeypatch.setattr(per, "get_db", lambda: db)
    monkeypatch.setattr(per, "_require_fin_mgr", _auth(FIN))
    monkeypatch.setattr(per, "log_activity", _noop)
    stale(db, "rahaza_periods", status="locked")
    with pytest.raises(HTTPException) as e:
        run(per.reopen_period("2026-09", FakeRequest()))
    assert e.value.status_code == 409 and db.rahaza_periods.docs[0]["status"] == "locked"


def test_batal_dan_kirim_faktur_tidak_menimpa_pembayaran_yang_baru_masuk(monkeypatch):
    import routes.rahaza_finance as rf
    db = DB()
    db.rahaza_ap_invoices.docs.append({"id": "ap1", "invoice_number": "AP-1", "status": "sent", "paid_amount": 0})
    db.rahaza_ar_invoices.docs.append({"id": "ar1", "invoice_number": "AR-1", "status": "issued"})
    monkeypatch.setattr(rf, "get_db", lambda: db)
    monkeypatch.setattr(rf, "_require_fin", _auth(FIN))
    posted = counting(monkeypatch, rf, "post_ap_invoice")
    stale(db, "rahaza_ap_invoices", status="partial_paid", paid_amount=100000)
    with pytest.raises(HTTPException) as e:
        run(rf.change_ap_status("ap1", FakeRequest({"status": "cancelled"})))
    assert e.value.status_code == 409 and db.rahaza_ap_invoices.docs[0]["status"] == "partial_paid"
    db.rahaza_ap_invoices.docs[0]["status"] = "sent"
    stale(db, "rahaza_ap_invoices", status="partial_paid")              # bayar masuk saat "kirim" ulang
    with pytest.raises(HTTPException) as e:
        run(rf.send_ap_invoice("ap1", FakeRequest()))
    assert e.value.status_code == 409 and db.rahaza_ap_invoices.docs[0]["status"] == "partial_paid" and posted == []
    stale(db, "rahaza_ar_invoices", status="paid")
    with pytest.raises(HTTPException) as e:
        run(rf.change_ar_status("ar1", FakeRequest({"status": "cancelled"})))
    assert e.value.status_code == 409 and db.rahaza_ar_invoices.docs[0]["status"] == "paid"


def test_selisih_kirim_cmt_diselesaikan_ganda_buku_kuantitas_sekali(monkeypatch):
    from core import short_shipment as ss
    db = DB()
    db[ss.CMT_SHORT].docs.append({"id": "sh1", "short_number": "SLS-1", "status": "open", "qty_short": 5,
                                  "qty_resolved": 0, "job_item_id": "ji1", "sku": "S1", "po_number": "PO-1"})
    inc = counting(monkeypatch, ss, "_ledger_inc")
    monkeypatch.setattr(ss, "_notify", _noop)
    monkeypatch.setattr(ss, "_vendor_user_ids", _ret([]))
    monkeypatch.setattr(ss, "flag_cmt_payment_variance", _noop)
    stale(db, ss.CMT_SHORT, status="resolved", qty_resolved=5)
    with pytest.raises(ss.AlreadyDecided):
        run(ss.resolve_cmt_short_manual(db, "sh1", resolution=next(iter(
            k for k in ss.CMT_RESOLUTIONS if k != "salah_input_dikoreksi")), notes="x", actor=SA))
    assert inc == [] and db[ss.CMT_SHORT].docs[0]["qty_resolved"] == 5
    db[ss.CMT_SHORT].docs[0].update(status="open", qty_resolved=0)
    monkeypatch.setattr(ss, "refresh_cmt_payment_variance", _noop)
    stale(db, ss.CMT_SHORT, status="cancelled")
    run(ss.cancel_cmt_short(db, "sh1", actor=SA, reason="salah input"))
    assert inc == []                                       # pembatalan kedua tidak mengurangi buku lagi


def test_pembayaran_klien_maklon_dan_faktur_lama_klik_ganda_409(monkeypatch):
    from core import maklon_ledger as ml
    import routes.dewi_maklon_billing as billing
    db = DB()
    db.rahaza_ar_invoices.docs.append({"id": "ar1", "schedule_mode": "v2"})
    db.dewi_maklon_invoices.docs.append({"id": "inv1", "status": "issued"})
    monkeypatch.setattr(billing, "get_db", lambda: db)
    seen = []

    async def ar_locked(_db, ar_id, **kw):
        try:
            await ml.record_client_payment(_db, ar_id, **kw)
        except HTTPException as e:
            seen.append(e.status_code)
        return {"id": "pay-1"}

    async def inv_locked(_db, payload, user):
        try:
            await billing.record_payment(payload, user=user)
        except HTTPException as e:
            seen.append(e.status_code)
        return {"message": "Pembayaran dicatat"}
    monkeypatch.setattr(ml, "_record_client_payment_locked", ar_locked)
    monkeypatch.setattr(billing, "_record_invoice_payment_locked", inv_locked)
    kw = dict(amount=500000, cash_account_id="kas1", payment_date=None, user=FIN)
    assert run(ml.record_client_payment(db, "ar1", **kw)) == {"id": "pay-1"}
    payload = billing.PaymentIn(invoice_id="inv1", amount=100000, method=billing.PAYMENT_METHODS[0])
    run(billing.record_payment(payload, user=FIN))
    assert seen == [409, 409]
    assert db.rahaza_ar_invoices.docs[0]["pay_lock"] is None and db.dewi_maklon_invoices.docs[0]["pay_lock"] is None
    with pytest.raises(ValueError):                     # piutang tidak ada → pesan lama (400 di rute)
        run(ml.record_client_payment(db, "nope", **kw))


def test_mi_ajukan_dan_tolak_basi_409(monkeypatch):
    import routes.rahaza_inventory_issues as rii
    db = DB()
    db.rahaza_material_issues.docs.append({"id": "mi1", "mi_number": "MI-1", "status": "pending_approval",
                                           "items": []})
    monkeypatch.setattr(rii, "get_db", lambda: db)
    monkeypatch.setattr(rii, "_require_mi_approver", _auth(SA))
    monkeypatch.setattr(rii, "log_activity", _noop)
    stale(db, "rahaza_material_issues", status="issued")         # di-approve & stok terpotong lebih dulu
    with pytest.raises(HTTPException) as e:
        run(rii.reject_mi("mi1", FakeRequest({"reason": "x"})))
    assert e.value.status_code == 409 and db.rahaza_material_issues.docs[0]["status"] == "issued"


def test_tolak_permintaan_aksesoris_tidak_menyalip_serah(monkeypatch):
    import routes.dewi_accessory_requests as dar
    db = DB()
    db.dewi_accessory_requests.docs.append({"id": "ar1", "status": "allocated", "delivering": True})
    monkeypatch.setattr(dar, "get_db", lambda: db)
    monkeypatch.setattr(dar, "_assert_can_fulfil", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        run(dar.reject_request("ar1", {"reason": "x"}, user=SA))
    assert e.value.status_code == 409 and db.dewi_accessory_requests.docs[0]["status"] == "allocated"


def test_aksi_tugas_marketing_dan_quick_complete_po_klik_ganda_409(monkeypatch):
    import routes.marketing_tasks as mt
    import routes.production_pos as ppos
    db = DB()
    db.marketing_tasks.docs.append({"id": "tk1", "status": "open"})
    db.production_pos.docs.append({"id": "pp1", "status": "Confirmed"})
    monkeypatch.setattr(mt, "get_db", lambda: db)
    monkeypatch.setattr(mt, "require_auth", _auth(SA))
    monkeypatch.setattr(mt, "_get_user", lambda r: dict(SA))
    monkeypatch.setattr(ppos, "get_db", lambda: db)
    monkeypatch.setattr(ppos, "require_auth", _auth(SA))
    monkeypatch.setattr(ppos, "check_role", lambda *a, **k: True)
    monkeypatch.setattr(ppos, "deny_klien", lambda *a, **k: None)
    seen = []

    async def task_locked(_db, task_id, payload, user):
        try:
            await mt.complete_task_action(task_id, payload, FakeRequest())
        except HTTPException as e:
            seen.append(e.status_code)
        return {"ok": True}

    async def quick_locked(_db, po_id, body, user):
        try:
            await ppos.quick_complete_po(po_id, FakeRequest({}))
        except HTTPException as e:
            seen.append(e.status_code)
        return {"ok": True}
    monkeypatch.setattr(mt, "_complete_task_action_locked", task_locked)
    monkeypatch.setattr(ppos, "_quick_complete_po_locked", quick_locked)
    run(mt.complete_task_action("tk1", mt.TaskCompleteAction(), FakeRequest()))
    run(ppos.quick_complete_po("pp1", FakeRequest({})))
    assert seen == [409, 409]
    assert db.marketing_tasks.docs[0]["action_lock"] is None and db.production_pos.docs[0]["job_lock"] is None


def test_gulungan_kain_keluar_bersamaan_sisa_tidak_tertimpa(monkeypatch):
    import routes.wms_fabric_rolls as wfr
    db = DB()
    db.wh_fabric_rolls.docs.append({"id": "rl1", "roll_no": "R-1", "uom": "meter", "status": "available",
                                    "remaining_m": 50.0, "length_m": 50.0})
    monkeypatch.setattr(wfr, "get_db", lambda: db)
    monkeypatch.setattr(wfr, "require_auth", _auth(SA))
    moves = counting(monkeypatch, wfr, "_log_movement")
    stale(db, "wh_fabric_rolls", remaining_m=20.0)                # pengeluaran lain 30 m baru saja tercatat
    with pytest.raises(HTTPException) as e:
        run(wfr.issue_roll("rl1", wfr.IssueIn(qty=30, unit="meter"), FakeRequest()))
    assert e.value.status_code == 409 and db.wh_fabric_rolls.docs[0]["remaining_m"] == 20.0 and moves == []


def test_batal_retur_fisik_tidak_menimpa_keputusan_gudang(monkeypatch):
    import routes.dewi_wh_returns as dwr
    db = DB()
    db.wh_returns.docs.append({"id": "w1", "status": "Inspected", "timeline": []})
    monkeypatch.setattr(dwr, "get_db", lambda: db)
    monkeypatch.setattr(dwr, "require_auth", _auth(SA))
    stale(db, "wh_returns", status="Resolved", restocked=True)
    with pytest.raises(HTTPException) as e:
        run(dwr.cancel_return("w1", FakeRequest({"reason": "x"})))
    assert e.value.status_code == 409 and db.wh_returns.docs[0]["status"] == "Resolved"
