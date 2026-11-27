"""Uji unit HERMETIK — Paket 1 "buku besar selalu ikut dokumen" (audit celah keuangan 25 Nov 2026), sisi faktur.

Yang dikunci:
  * batal faktur piutang ditolak bila sudah dibayar / punya nota kredit; jurnal gagal dibatalkan → status kembali;
    berhasil → `gl_je_id` dikosongkan sehingga terbit ulang memposting jurnal baru;
  * status lunas / dihapusbukukan tidak bisa dipilih manual;
  * batal faktur pemasok (bukan dari penerimaan) memakai pola yang sama; nota debit menahan pembatalan;
  * hapus buku: jurnal gagal → status & sisa kembali, alasan disimpan, bisa diulang;
  * batalkan pembayaran piutang/hutang (baru): kunci jurnal sama dengan saat diposting, sisa & status faktur kembali,
    mutasi kas dihapus, dua kali ditolak, jurnal gagal → pembayaran tetap berlaku;
  * pembayaran hutang dibatasi nota debit (`debit_note_amount`);
  * persetujuan ubah faktur: total < dibayar ditolak, jurnal lama gagal dibatalkan → faktur kembali seperti semula,
    posting ulang gagal → `post_error` disimpan dan dilaporkan (bukan diklaim berhasil).

Jalankan:  cd backend && python -m pytest tests/unit/test_keuangan_paket1_faktur.py -q
"""
import asyncio
import copy
import os
import sys
from datetime import datetime, timezone

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
import routes.invoice_edit_requests as ier  # noqa: E402
import routes.rahaza_finance as rf  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402

FIN = {"id": "u-fin", "name": "Keuangan Uji", "email": "fin@x", "role": "accounting"}
ALASAN = "Salah catat rekening bank"


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


def _auth(user):
    async def f(*_a, **_k):
        return dict(user)
    return f


# ── Mongo palsu: + `$expr`, update pipeline, find_one_and_update (secukupnya untuk rumus bayar/batal bayar) ──
def _ev(e, doc):
    if isinstance(e, str) and e.startswith("$"):
        v = fm._get(doc, e[1:])
        return None if v is fm._MISSING else v
    if isinstance(e, list):
        return [_ev(x, doc) for x in e]
    if isinstance(e, dict) and len(e) == 1 and str(next(iter(e))).startswith("$"):
        op, a = next(iter(e.items()))
        if op == "$ifNull":
            v = _ev(a[0], doc)
            return v if v is not None else _ev(a[1], doc)
        if op == "$add":
            return sum(float(_ev(x, doc) or 0) for x in a)
        if op == "$subtract":
            return float(_ev(a[0], doc) or 0) - float(_ev(a[1], doc) or 0)
        if op == "$round":
            return round(float(_ev(a[0], doc) or 0), a[1])
        if op == "$max":
            return max(_ev(x, doc) for x in a)
        if op == "$cond":
            return _ev(a[1], doc) if _ev(a[0], doc) else _ev(a[2], doc)
        if op == "$in":
            return _ev(a[0], doc) in _ev(a[1], doc)
        if op in ("$gte", "$lte", "$gt", "$lt", "$eq"):
            x, y = _ev(a[0], doc), _ev(a[1], doc)
            return {"$gte": x >= y, "$lte": x <= y, "$gt": x > y, "$lt": x < y, "$eq": x == y}[op]
        raise NotImplementedError(op)
    return e


def _match(doc, q):
    q = dict(q or {})
    expr = q.pop("$expr", None)
    if expr is not None and not _ev(expr, doc):
        return False
    return fm.match(doc, q)


def _apply(d, upd, q):
    if isinstance(upd, list):
        for stage in upd:
            vals = {k: _ev(v, d) for k, v in stage["$set"].items()}   # satu tahap dihitung dari dokumen masukan
            for k, v in vals.items():
                fm._set_path(d, k, copy.deepcopy(v))
    else:
        fm.FakeCollection._apply(d, upd, q=q)


class Coll(fm.FakeCollection):
    def find(self, q=None, projection=None):
        return fm.FakeCursor([d for d in self.docs if _match(d, q)])

    async def find_one(self, q=None, projection=None, **kw):
        for d in self.docs:
            if _match(d, q):
                return copy.deepcopy(d)
        return None

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if _match(d, q):
                _apply(d, upd, q)
                return fm._Result(matched=1, modified=1)
        return fm._Result()

    async def find_one_and_update(self, q, upd, return_document=None, **_kw):
        for d in self.docs:
            if _match(d, q):
                _apply(d, upd, q)
                return copy.deepcopy(d)
        return None


class DB(fm.FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = Coll(name)
        return self._cols[name]


@pytest.fixture
def db(monkeypatch):
    import auth
    d = DB()
    monkeypatch.setattr(rf, "get_db", lambda: d)
    monkeypatch.setattr(rf, "_require_fin", _auth(FIN))
    monkeypatch.setattr(rf, "log_activity", _noop)
    monkeypatch.setattr(rf, "_today_iso", lambda: "2026-11-25")
    monkeypatch.setattr(auth, "log_activity", _noop)
    monkeypatch.setattr(ier, "get_db", lambda: d)
    monkeypatch.setattr(ier, "_require_approver", _auth(FIN))
    monkeypatch.setattr(ier, "log_activity", _noop)
    return d


def fake(monkeypatch, mod, name, *results):
    """Ganti `mod.name` dengan fungsi palsu; panggilan ke-n mengembalikan `results[n]` (terakhir diulang)."""
    calls = []

    async def f(*a, **k):
        calls.append((a, k))
        r = results[min(len(calls), len(results)) - 1]
        if isinstance(r, Exception):
            raise r
        return r(*a, **k) if callable(r) else copy.deepcopy(r)
    monkeypatch.setattr(mod, name, f)
    return calls


def _ar(db, **kw):
    doc = {"id": "ar1", "invoice_number": "AR-1", "status": "issued", "total": 1_000_000, "subtotal": 1_000_000,
           "tax_amount": 0, "paid_amount": 0, "balance": 1_000_000, "total_amount": 1_000_000, "amount_paid": 0,
           "amount_due": 1_000_000, "due_date": "2099-12-31", "gl_je_id": "je-inv", "gl_je_number": "JE-INV",
           "notes": "lama", **kw}
    db.rahaza_ar_invoices.docs.append(doc)
    return db.rahaza_ar_invoices.docs[-1]


def _ap(db, **kw):
    doc = {"id": "ap1", "invoice_number": "AP-1", "status": "sent", "total": 1_000_000, "subtotal": 1_000_000,
           "tax_amount": 0, "paid_amount": 0, "balance": 1_000_000, "due_date": "2099-12-31", "gl_je_id": "je-ap",
           "vendor_name": "PT Pemasok", **kw}
    db.rahaza_ap_invoices.docs.append(doc)
    return db.rahaza_ap_invoices.docs[-1]


# ══════════════════════════ 1. Status faktur piutang ══════════════════════════
def test_batal_faktur_piutang_yang_sudah_dibayar_atau_bernota_kredit_ditolak(db, monkeypatch):
    voids = fake(monkeypatch, rf, "void_ar_invoice_posting", {"ok": True, "voided": True})
    _ar(db, status="partial_paid", paid_amount=400_000, balance=600_000)
    with pytest.raises(HTTPException) as e:
        run(rf.change_ar_status("ar1", FakeRequest({"status": "cancelled"})))
    assert e.value.status_code == 409 and "pembayaran Rp 400.000" in e.value.detail and "dulu" in e.value.detail
    db.rahaza_ar_invoices.docs[0].update(status="issued", paid_amount=0, credited_amount=150_000)
    with pytest.raises(HTTPException) as e:
        run(rf.change_ar_status("ar1", FakeRequest({"status": "cancelled"})))
    assert e.value.status_code == 409 and "nota kredit" in e.value.detail
    assert db.rahaza_ar_invoices.docs[0]["status"] == "issued" and voids == []


def test_batal_faktur_piutang_jurnal_gagal_status_kembali_lalu_terbit_ulang_berjurnal(db, monkeypatch):
    _ar(db)
    voids = fake(monkeypatch, rf, "void_ar_invoice_posting",
                 {"ok": False, "error": "Periode 2026-10 sudah ditutup."},
                 {"ok": True, "voided": False, "reversed": True, "reversal_je_id": "rev1"})
    posted = fake(monkeypatch, rf, "post_ar_invoice", {"ok": True, "je_id": "je-baru", "je_number": "JE-BARU"})
    with pytest.raises(HTTPException) as e:
        run(rf.change_ar_status("ar1", FakeRequest({"status": "cancelled"})))
    assert e.value.status_code == 409 and "ditutup" in e.value.detail
    inv = db.rahaza_ar_invoices.docs[0]
    assert inv["status"] == "issued" and inv["gl_je_id"] == "je-inv"          # dokumen = buku besar
    out = run(rf.change_ar_status("ar1", FakeRequest({"status": "cancelled"})))
    assert out["status"] == "cancelled" and out["_posting_result"]["reversed"] is True
    assert inv["gl_je_id"] is None and inv["gl_je_number"] is None and len(voids) == 2
    run(rf.change_ar_status("ar1", FakeRequest({"status": "issued"})))      # terbit ulang → jurnal baru
    assert len(posted) == 1 and inv["status"] == "issued"


def test_status_lunas_dan_hapus_buku_tidak_dipilih_manual(db, monkeypatch):
    _ar(db)
    _ap(db)
    for status in ("paid", "written_off", "partial_paid"):
        with pytest.raises(HTTPException) as e:
            run(rf.change_ar_status("ar1", FakeRequest({"status": status})))
        assert e.value.status_code == 400 and "pembayaran" in e.value.detail
    for status in ("paid", "partial_paid"):
        with pytest.raises(HTTPException) as e:
            run(rf.change_ap_status("ap1", FakeRequest({"status": status})))
        assert e.value.status_code == 400
    assert db.rahaza_ar_invoices.docs[0]["status"] == "issued" and db.rahaza_ap_invoices.docs[0]["status"] == "sent"


def test_faktur_berjurnal_tidak_kembali_ke_draf_lewat_status(db):
    _ar(db)
    with pytest.raises(HTTPException) as e:
        run(rf.change_ar_status("ar1", FakeRequest({"status": "draft"})))
    assert e.value.status_code == 409 and "Batalkan persetujuan" in e.value.detail
    assert db.rahaza_ar_invoices.docs[0]["status"] == "issued"


# ══════════════════════════ 2. Batal faktur pemasok (bukan dari penerimaan) ══════════════════════════
def test_batal_faktur_pemasok_jurnal_gagal_status_kembali(db, monkeypatch):
    _ap(db)
    fake(monkeypatch, rf, "void_ap_invoice_posting", {"ok": False, "error": "Periode 2026-10 sudah ditutup."},
         {"ok": True, "voided": True})
    with pytest.raises(HTTPException) as e:
        run(rf.change_ap_status("ap1", FakeRequest({"status": "cancelled"})))
    inv = db.rahaza_ap_invoices.docs[0]
    assert e.value.status_code == 409 and "ditutup" in e.value.detail
    assert inv["status"] == "sent" and inv["gl_je_id"] == "je-ap"
    out = run(rf.change_ap_status("ap1", FakeRequest({"status": "cancelled"})))
    assert out["status"] == "cancelled" and inv["gl_je_id"] is None


def test_batal_faktur_pemasok_bernota_debit_ditolak(db, monkeypatch):
    voids = fake(monkeypatch, rf, "void_ap_invoice_posting", {"ok": True, "voided": True})
    _ap(db, debit_note_amount=250_000)
    with pytest.raises(HTTPException) as e:
        run(rf.change_ap_status("ap1", FakeRequest({"status": "cancelled"})))
    assert e.value.status_code == 409 and "nota debit" in e.value.detail and voids == []
    assert db.rahaza_ap_invoices.docs[0]["status"] == "sent"


# ══════════════════════════ 3. Hapus buku ══════════════════════════
def test_hapus_buku_jurnal_gagal_dikembalikan_lalu_bisa_diulang(db, monkeypatch):
    _ar(db, status="overdue", paid_amount=400_000, balance=600_000, amount_due=600_000, due_date="2026-01-10")
    fake(monkeypatch, rp, "post_bad_debt_writeoff",
         {"ok": False, "error": "Mapping 'bad_debt_writeoff' belum lengkap."},
         {"ok": True, "je_id": "je-bd", "je_number": "JE-BD"})
    with pytest.raises(HTTPException) as e:
        run(rf.write_off_bad_debt("ar1", FakeRequest({"reason": "Pelanggan bangkrut"})))
    inv = db.rahaza_ar_invoices.docs[0]
    assert e.value.status_code == 409 and "belum lengkap" in e.value.detail
    assert (inv["status"], inv["balance"], inv["amount_due"]) == ("overdue", 600_000, 600_000)
    assert "belum lengkap" in inv["post_error"] and "write_off_amount" not in inv and "write_off_reason" not in inv
    out = run(rf.write_off_bad_debt("ar1", FakeRequest({"reason": "Pelanggan bangkrut"})))   # ulang → berhasil
    assert out["status"] == "written_off" and out["balance"] == 0 and out["write_off_amount"] == 600_000
    assert out["post_error"] is None


def test_hapus_buku_basi_ditolak_409(db, monkeypatch):
    posted = fake(monkeypatch, rp, "post_bad_debt_writeoff", {"ok": True, "je_id": "x", "je_number": "X"})
    _ar(db, status="partial_paid", paid_amount=400_000, balance=600_000)
    col = db.rahaza_ar_invoices
    orig = col.find_one

    async def basi(q=None, projection=None, **kw):   # pembayaran lain masuk di sela baca & tulis
        doc = await orig(q, projection, **kw)
        col.docs[0].update(paid_amount=500_000, balance=500_000)
        return doc
    col.find_one = basi
    with pytest.raises(HTTPException) as e:
        run(rf.write_off_bad_debt("ar1", FakeRequest({"reason": "Pelanggan bangkrut"})))
    assert e.value.status_code == 409 and col.docs[0]["status"] == "partial_paid" and posted == []


# ══════════════════════════ 4. Batalkan pembayaran ══════════════════════════
def _ar_dibayar(db):
    _ar(db, status="paid", paid_amount=1_000_000, balance=0, amount_paid=1_000_000, amount_due=0)
    db.rahaza_ar_payments.docs += [
        {"id": "p1", "invoice_id": "ar1", "invoice_number": "AR-1", "amount": 600_000, "movement_id": "mv1",
         "gl_je_id": "je-p1", "created_at": datetime(2026, 11, 20, tzinfo=timezone.utc)},
        {"id": "p2", "invoice_id": "ar1", "invoice_number": "AR-1", "amount": 400_000, "movement_id": None,
         "gl_je_id": "je-p2", "created_at": datetime(2026, 11, 21, tzinfo=timezone.utc)},
    ]
    db.rahaza_cash_movements.docs.append({"id": "mv1", "direction": "in", "amount": 600_000, "category": "ar_payment"})


def test_batal_pembayaran_piutang_mengembalikan_sisa_status_dan_kas(db, monkeypatch):
    _ar_dibayar(db)
    voids = fake(monkeypatch, rf, "_void_je_by_source", {"ok": True, "voided": True, "je_number": "JE-P"})
    out = run(rf.void_ar_payment("ar1", "p1", FakeRequest({"alasan": ALASAN})))
    assert voids[0][0][1:3] == ("ar_payment", "arpay:mv1:600000")        # kunci yang sama dengan saat diposting
    assert (out["status"], out["paid_amount"], out["balance"], out["amount_due"]) == ("partial_paid", 400_000, 600_000, 600_000)
    p1 = db.rahaza_ar_payments.docs[0]
    assert p1["status"] == "voided" and p1["void_reason"] == ALASAN and p1["voided_by"] == "u-fin"
    assert "void_claim_at" not in p1 and db.rahaza_cash_movements.docs == []
    out = run(rf.void_ar_payment("ar1", "p2", FakeRequest({"alasan": ALASAN})))
    assert voids[1][0][1:3] == ("ar_payment", "arpay:p2:400000")           # tanpa mutasi kas → ID pembayaran
    assert (out["status"], out["paid_amount"], out["balance"]) == ("issued", 0, 1_000_000)


def test_batal_pembayaran_dua_kali_ditolak(db, monkeypatch):
    _ar_dibayar(db)
    voids = fake(monkeypatch, rf, "_void_je_by_source", {"ok": True, "voided": True})
    run(rf.void_ar_payment("ar1", "p1", FakeRequest({"alasan": ALASAN})))
    with pytest.raises(HTTPException) as e:
        run(rf.void_ar_payment("ar1", "p1", FakeRequest({"alasan": ALASAN})))
    assert e.value.status_code == 409 and "sudah dibatalkan" in e.value.detail
    # klik ganda: permintaan kedua datang saat yang pertama masih memegang klaim
    db.rahaza_ar_payments.docs[1].update(status="voiding", void_claim_at=datetime.now(timezone.utc))
    with pytest.raises(HTTPException) as e:
        run(rf.void_ar_payment("ar1", "p2", FakeRequest({"alasan": ALASAN})))
    assert e.value.status_code == 409 and "sedang dibatalkan" in e.value.detail
    inv = db.rahaza_ar_invoices.docs[0]
    assert len(voids) == 1 and inv["paid_amount"] == 400_000 and inv["balance"] == 600_000


def test_batal_pembayaran_jurnal_gagal_pembayaran_tetap_berlaku(db, monkeypatch):
    _ar_dibayar(db)
    fake(monkeypatch, rf, "_void_je_by_source", {"ok": False, "error": "Periode 2026-11 sudah ditutup."})
    with pytest.raises(HTTPException) as e:
        run(rf.void_ar_payment("ar1", "p1", FakeRequest({"alasan": ALASAN})))
    assert e.value.status_code == 409 and "ditutup" in e.value.detail and "tetap tercatat" in e.value.detail
    p1, inv = db.rahaza_ar_payments.docs[0], db.rahaza_ar_invoices.docs[0]
    assert "status" not in p1 and "void_claim_at" not in p1                    # klaim dilepas
    assert (inv["status"], inv["paid_amount"], inv["balance"]) == ("paid", 1_000_000, 0)
    assert [m["id"] for m in db.rahaza_cash_movements.docs] == ["mv1"]


def test_batal_pembayaran_jurnal_lama_tanpa_kunci_tidak_diam_diam_lolos(db, monkeypatch):
    _ar_dibayar(db)
    db.rahaza_journal_entries.docs.append({"id": "je-p1", "je_number": "JE-LAMA", "status": "posted",
                                           "source_ref": "arpay:ar1:2026-11-20:600000"})
    fake(monkeypatch, rf, "_void_je_by_source", {"ok": True, "voided": False, "reason": "JE not found"})
    with pytest.raises(HTTPException) as e:
        run(rf.void_ar_payment("ar1", "p1", FakeRequest({"alasan": ALASAN})))
    assert e.value.status_code == 409 and "JE-LAMA" in e.value.detail
    assert db.rahaza_ar_invoices.docs[0]["paid_amount"] == 1_000_000


def test_batal_pembayaran_hutang_bruto_dengan_potongan_dan_nota_debit(db, monkeypatch):
    _ap(db, status="paid", total=1_000_000, debit_note_amount=200_000, paid_amount=800_000, balance=0,
        due_date="2026-11-01")
    db.rahaza_ap_payments.docs.append({"id": "q1", "invoice_id": "ap1", "amount": 750_000, "discount_amount": 50_000,
                                       "gross_amount": 800_000, "movement_id": "mv9"})
    db.rahaza_cash_movements.docs.append({"id": "mv9", "direction": "out", "amount": 750_000})
    voids = fake(monkeypatch, rf, "_void_je_by_source", {"ok": True, "voided": True})
    out = run(rf.void_ap_payment("ap1", "q1", FakeRequest({"alasan": ALASAN})))
    assert voids[0][0][1:3] == ("ap_payment", "appay:mv9:800000")          # bruto, sama dengan post_ap_payment
    assert (out["status"], out["paid_amount"], out["balance"]) == ("overdue", 0, 800_000)   # sisa = total − nota debit
    assert db.rahaza_cash_movements.docs == [] and db.rahaza_ap_payments.docs[0]["status"] == "voided"


def test_batal_pembayaran_alasan_antar_cv_dan_maklon_ditolak(db, monkeypatch):
    _ar_dibayar(db)
    voids = fake(monkeypatch, rf, "_void_je_by_source", {"ok": True, "voided": True})
    with pytest.raises(HTTPException) as e:
        run(rf.void_ar_payment("ar1", "p1", FakeRequest({"alasan": "salah"})))
    assert e.value.status_code == 400 and "minimal 10" in e.value.detail
    db.rahaza_ar_payments.docs[0]["intercompany"] = True
    with pytest.raises(HTTPException) as e:
        run(rf.void_ar_payment("ar1", "p1", FakeRequest({"alasan": ALASAN})))
    assert e.value.status_code == 409 and "antar CV" in e.value.detail
    db.rahaza_ar_payments.docs[1]["source"] = "maklon"
    with pytest.raises(HTTPException) as e:
        run(rf.void_ar_payment("ar1", "p2", FakeRequest({"alasan": ALASAN})))
    assert e.value.status_code == 409 and "maklon" in e.value.detail
    assert voids == [] and db.rahaza_ar_invoices.docs[0]["paid_amount"] == 1_000_000


def test_rumus_batal_bayar_mengikuti_nota_kredit():
    doc = {"total": 1_000_000, "credited_amount": 300_000, "paid_amount": 700_000, "status": "paid"}
    for stage in rf.payment_void_update("ar", 200_000, "issued"):
        doc.update({k: _ev(v, doc) for k, v in stage["$set"].items()})
    assert (doc["status"], doc["paid_amount"], doc["balance"], doc["amount_due"]) == ("partial_paid", 500_000, 200_000, 200_000)
    doc = {"total": 1_000_000, "paid_amount": 1_000_000, "status": "written_off"}
    for stage in rf.payment_void_update("ar", 1_000_000, "issued"):
        doc.update({k: _ev(v, doc) for k, v in stage["$set"].items()})
    assert doc["status"] == "written_off"                                     # status akhir tidak disentuh


# ══════════════════════════ 5. Nota debit membatasi pembayaran hutang ══════════════════════════
def test_pembayaran_hutang_dibatasi_nota_debit(db, monkeypatch):
    _ap(db, debit_note_amount=300_000)
    fake(monkeypatch, rf, "post_ap_payment", {"ok": True, "je_id": "je-pay", "je_number": "JE-PAY"})
    fake(monkeypatch, rf, "post_ap_invoice", {"ok": True, "je_id": "je-ap", "je_number": "JE-AP"})
    with pytest.raises(HTTPException) as e:
        run(rf.record_ap_payment("ap1", FakeRequest({"amount": 800_000})))
    inv = db.rahaza_ap_invoices.docs[0]
    assert e.value.status_code == 400 and "nota debit Rp 700.000" in e.value.detail
    assert inv["paid_amount"] == 0 and db.rahaza_ap_payments.docs == []
    out = run(rf.record_ap_payment("ap1", FakeRequest({"amount": 650_000, "discount_amount": 50_000})))
    assert (out["status"], out["paid_amount"], out["balance"]) == ("paid", 700_000, 0)
    assert rf.ap_open_balance({"total": 1_000_000, "debit_note_amount": 300_000, "paid_amount": 0,
                               "balance": 1_000_000}) == 700_000
    assert rf.ap_open_balance({"total": 1_000_000, "paid_amount": 0, "balance": 1_000_000}) == 1_000_000


# ══════════════════════════ 6. Persetujuan ubah faktur ══════════════════════════
def _permintaan(db, **after):
    db.invoice_edit_requests.docs.append({
        "id": "q1", "status": "Pending", "invoice_number": "AR-1", "target_collection": "rahaza_ar_invoices",
        "target_invoice_id": "ar1", "before_snapshot": {}, "after_snapshot": after or {"total_amount": 900_000,
                                                                                         "notes": "baru"}})


def test_ubah_faktur_total_di_bawah_dibayar_ditolak(db, monkeypatch):
    _ar(db, status="partial_paid", paid_amount=500_000, balance=500_000)
    _permintaan(db, total_amount=400_000)
    voids = fake(monkeypatch, rp, "void_ar_invoice_posting", {"ok": True, "voided": True})
    with pytest.raises(HTTPException) as e:
        run(ier.approve_request("q1", FakeRequest({})))
    assert e.value.status_code == 409 and "Rp 500.000" in e.value.detail and voids == []
    assert db.rahaza_ar_invoices.docs[0]["total"] == 1_000_000
    assert db.invoice_edit_requests.docs[0]["status"] == "Pending"


def test_ubah_faktur_jurnal_lama_gagal_dibatalkan_semua_kembali(db, monkeypatch):
    _ar(db)
    _permintaan(db)
    fake(monkeypatch, rp, "void_ar_invoice_posting", {"ok": False, "error": "Periode 2026-10 sudah ditutup."},
         {"ok": True, "voided": True})
    seen = []

    def posting(_db, fresh, _user):
        seen.append(fresh.get("gl_je_id"))
        return {"ok": True, "je_id": "je-2", "je_number": "JE-2"}
    posted = fake(monkeypatch, rp, "post_ar_invoice", posting)
    with pytest.raises(HTTPException) as e:
        run(ier.approve_request("q1", FakeRequest({})))
    inv, req = db.rahaza_ar_invoices.docs[0], db.invoice_edit_requests.docs[0]
    assert e.value.status_code == 409 and "ditutup" in e.value.detail and posted == []
    assert (inv["total"], inv["balance"], inv["notes"], inv["gl_je_id"]) == (1_000_000, 1_000_000, "lama", "je-inv")
    assert req["status"] == "Pending" and req.get("decide_lock") is None
    out = run(ier.approve_request("q1", FakeRequest({})))                     # periode dibuka → disetujui
    assert out["warning"] is None and out["gl_resync"]["ok"] is True and seen == [None]   # gl_je_id lama dikosongkan dulu
    assert (inv["total"], inv["balance"], inv["amount_due"], inv["notes"]) == (900_000, 900_000, 900_000, "baru")
    assert req["status"] == "Approved"


def test_ubah_faktur_posting_ulang_gagal_disimpan_dan_dilaporkan(db, monkeypatch):
    _ar(db)
    _permintaan(db)
    fake(monkeypatch, rp, "void_ar_invoice_posting", {"ok": True, "voided": True})
    fake(monkeypatch, rp, "post_ar_invoice", {"ok": False, "error": "Mapping 'ar_invoice' belum lengkap."})
    out = run(ier.approve_request("q1", FakeRequest({})))
    inv, req = db.rahaza_ar_invoices.docs[0], db.invoice_edit_requests.docs[0]
    assert out["gl_resync"]["ok"] is False and "gagal" in out["warning"] and "belum lengkap" in out["message"]
    assert inv["gl_je_id"] is None and "belum lengkap" in inv["post_error"] and inv["total"] == 900_000
    assert req["status"] == "Approved" and req["gl_resync_ok"] is False
