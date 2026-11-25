"""Uji unit HERMETIK — Paket 1 "buku besar selalu ikut dokumen" (audit keuangan 25 Nov 2026): retur & penyesuaian.

Angka harapan DIHITUNG TANGAN:
  * Retur penjualan langsung: nota 5 pcs @100.000, HPP keluar 250.000 (50.000/pcs). Retur 3 → nota kredit
    300.000, piutang 500.000 → sisa 200.000 (`credited_amount` 300.000), balik HPP Dr 1-1404 / Cr 5-1000 150.000.
    Retur kedua 3 pcs → ditolak (sisa 2). Faktur sudah lunas → refund tunai 300.000: Dr 1-1301 / Cr 1-1101.
  * Retur Pembelian 6 kg @50.000 (HPP 55.000): kirim Dr 1-1620 300.000 + Dr 5-1900 30.000 / Cr 1-1401 330.000.
    Nota Debit sesudah faktur AP-0001 (4.500.000): Dr 2-1100-SUP-1 / Cr 1-1620 300.000 dan faktur
    `debit_note_amount` = 300.000. Faktur sudah dibayar 4.300.000 → sisa 200.000 < 300.000 → ditolak.
  * Batalkan penyesuaian opname −5 kg @1.000: stok 95 → 100, jurnal Dr 1-1401 / Cr 5-1950 5.000; pulihkan
    stok 100 → 95, jurnal Dr 5-1950 / Cr 1-1401 5.000. Baris "rusak": lawan 6-4300. Opname +5 lalu stok tinggal 2
    → batalkan hanya 2 (stok tidak di bawah 0): Dr 5-1950 / Cr 1-1401 2.000.

Jalankan:  cd backend && python -m pytest tests/unit/test_keuangan_paket1_retur.py -q
"""
import asyncio
import copy
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from core import purchase_returns as pr  # noqa: E402
from core import quarantine as qmod  # noqa: E402
from core import stock_service  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402
from utils.waktu import today_wib  # noqa: E402

DEFAULT_MAP = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}
SA = {"id": "u-sa", "name": "Super", "email": "sa@x", "role": "superadmin"}
TODAY = today_wib()
SALE = (TODAY - timedelta(days=3)).isoformat()


def run(coro):
    return asyncio.run(coro)


class Req:
    def __init__(self, body=None):
        self._b = body or {}

        class _S:
            pass
        self.state = _S()

    async def json(self):
        return copy.deepcopy(self._b)

    async def body(self):
        return b"{}" if self._b else b""


def interleave(monkeypatch, obj, name, second, out: list):
    """Panggilan PERTAMA `obj.name` menjalankan `second()` dulu (permintaan kedua yang datang saat efek pertama
    berjalan — klik ganda); hasil/galatnya disimpan di `out`."""
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


async def _mapping(db, key):
    return dict(DEFAULT_MAP.get(key, {}))


def _lines(je):
    return sorted((ln["account_code"], round(ln["debit"], 2), round(ln["credit"], 2)) for ln in je["lines"])


# ═════════════════════════════ 1. Retur penjualan langsung ═════════════════════════════
def _sd_env(monkeypatch, db):
    import routes.sales_direct as sd
    from core import fg_cost_layers as fcl
    from core import production_qty_ledger as pql
    st = types.SimpleNamespace(adds=[], cns=[], jes=[], je_result=None, on_add=None, n=0)

    async def add(mid, loc, qty, **kw):
        st.adds.append((mid, loc, qty))
        if st.on_add:
            hook, st.on_add = st.on_add, None
            await hook()
        return {}

    async def push_layer(db_, **kw):
        return {"id": f"ly-{len(st.adds)}", "wac": {"unit_cost": kw.get("unit_cost")}}

    async def fg_loc(db_):
        return "LOC-FG"

    async def post_cn(db_, cn, user):
        st.cns.append(cn)
        return {"ok": True, "je_id": f"je-cn-{len(st.cns)}", "je_number": f"JE-CN-{len(st.cns)}"}

    async def create(db_, d, memo, mod, ref, lines, user, **kw):
        if st.je_result is not None:
            return dict(st.je_result)
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2), lines
        st.jes.append({"id": f"je-{len(st.jes) + 1}", "source_module": mod, "source_ref": ref, "date": d,
                       "lines": [dict(ln) for ln in lines]})
        return {"ok": True, "je_id": st.jes[-1]["id"], "je_number": f"JE-{len(st.jes)}"}

    async def period_ok(*_a, **_k):
        return None

    async def gen(db_, coll, field, prefix, width=4, **kw):
        st.n += 1
        return f"{prefix}{st.n:0{width}d}"
    monkeypatch.setattr(stock_service, "add", add)
    monkeypatch.setattr(fcl, "push_layer", push_layer)
    monkeypatch.setattr(pql, "resolve_fg_location_id", fg_loc)
    monkeypatch.setattr(rp, "post_credit_note", post_cn)
    monkeypatch.setattr(rp, "_create_posted_je", create)
    monkeypatch.setattr(rp, "get_mapping", _mapping)
    monkeypatch.setattr(pp, "get_mapping", _mapping)
    monkeypatch.setattr(rp, "_ensure_period_open", period_ok)
    monkeypatch.setattr(sd, "gen_prefixed_number", gen)
    return sd, st


def _sd_db(sale_date=SALE, **inv):
    db = fm.FakeDB()
    db.sales_direct_notes.docs.append({
        "id": "N1", "note_number": "SL-1", "status": "confirmed", "sale_date": sale_date, "customer_id": "C1",
        "customer_name": "Toko Uji", "ar_invoice_id": "AR1", "invoice_number": "AR-1",
        "items": [{"material_id": "FG1", "sku": "DA-1-M", "name": "Kaos", "qty": 5, "price": 100000,
                   "amount": 500000, "fg_cogs": 250000.0, "fg_cogs_layers": []}],
        "subtotal": 500000, "discount_amount": 0, "tax_pct": 0, "tax_amount": 0, "total": 500000})
    db.rahaza_ar_invoices.docs.append({"id": "AR1", "invoice_number": "AR-1", "total": 500000, "paid_amount": 0,
                                       "balance": 500000, "status": "issued", "gl_ar_account_code": "1-1301", **inv})
    db.rahaza_cash_accounts.docs += [
        {"id": "K1", "name": "Kas Toko", "gl_account_code": "1-1101", "active": True},
        {"id": "K-OFF", "name": "Kas Lama", "gl_account_code": "1-1102", "active": False},
        {"id": "K-SMU", "name": "Bank Sukma", "gl_account_code": "1-1210", "entity": "SMU"},
    ]
    return db


def _ret_body(qty=3, **kw):
    return {"items": [{"material_id": "FG1", "qty": qty}], "return_date": TODAY.isoformat(), "reason": "salah ukuran",
            **kw}


def test_retur_penjualan_normal_dokumen_lebih_dulu_lalu_posted(monkeypatch):
    db = _sd_db()
    sd, st = _sd_env(monkeypatch, db)
    out = run(sd.process_direct_sale_return(db, "N1", _ret_body(), SA))
    assert out["status"] == "posted" and out["post_error"] is None and out["total"] == 300000
    assert st.adds == [("FG1", "LOC-FG", 3)] and len(st.cns) == 1
    inv = db.rahaza_ar_invoices.docs[0]
    assert inv["credited_amount"] == 300000 and inv["balance"] == 200000
    cogs = next(je for je in st.jes if je["source_module"] == "cogs_sales_return")
    assert _lines(cogs) == [("1-1404", 150000.0, 0), ("5-1000", 0, 150000.0)]
    assert [r["status"] for r in db.sales_direct_returns.docs] == ["posted"]
    assert db.sales_direct_notes.docs[0].get("return_lock") is None          # kunci dilepas
    assert db.sales_direct_notes.docs[0]["returned_qty"] == 3


def test_retur_ganda_ditolak_qty_yang_sudah_diretur_terhitung(monkeypatch):
    db = _sd_db()
    sd, st = _sd_env(monkeypatch, db)
    run(sd.process_direct_sale_return(db, "N1", _ret_body(3), SA))
    with pytest.raises(HTTPException) as e:                      # klik kedua sesudah yang pertama selesai
        run(sd.process_direct_sale_return(db, "N1", _ret_body(3), SA))
    assert e.value.status_code == 400 and "maksimal retur 2" in e.value.detail
    assert len(st.adds) == 1 and len(st.cns) == 1 and len(db.sales_direct_returns.docs) == 1
    assert db.rahaza_ar_invoices.docs[0]["credited_amount"] == 300000


def test_retur_bersamaan_kedua_409_tanpa_efek(monkeypatch):
    db = _sd_db()
    sd, st = _sd_env(monkeypatch, db)
    out = []

    async def second():
        return await sd.process_direct_sale_return(db, "N1", _ret_body(2), SA)

    async def hook():
        try:
            out.append(await second())
        except HTTPException as e:
            out.append(e)
    st.on_add = hook                                              # permintaan kedua tiba saat stok pertama masuk
    run(sd.process_direct_sale_return(db, "N1", _ret_body(3), SA))
    assert isinstance(out[0], HTTPException) and out[0].status_code == 409
    assert len(st.adds) == 1 and len(st.cns) == 1 and len(db.sales_direct_returns.docs) == 1
    assert db.sales_direct_notes.docs[0].get("return_lock") is None


@pytest.mark.parametrize("acc,kata", [("TIDAK-ADA", "tidak ditemukan"), ("K-OFF", "tidak aktif"),
                                      ("K-SMU", "CV Sukma"), (None, "wajib")])
def test_rekening_refund_salah_ditolak_sebelum_stok_berubah(monkeypatch, acc, kata):
    db = _sd_db(paid_amount=500000, status="paid", balance=0)
    sd, st = _sd_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(sd.process_direct_sale_return(db, "N1", _ret_body(refund_method="cash", cash_account_id=acc), SA))
    assert e.value.status_code == 400 and kata in e.value.detail
    assert st.adds == [] and st.cns == [] and db.sales_direct_returns.docs == []
    assert "credited_amount" not in db.rahaza_ar_invoices.docs[0]


def test_refund_tunai_jurnal_kas_dari_rekening_terpilih(monkeypatch):
    db = _sd_db(paid_amount=500000, status="paid", balance=0)
    sd, st = _sd_env(monkeypatch, db)
    out = run(sd.process_direct_sale_return(db, "N1", _ret_body(refund_method="cash", cash_account_id="K1"), SA))
    assert out["refund_amount"] == 300000 and out["post_error"] is None
    refund = next(je for je in st.jes if je["source_module"] == "sales_refund")
    assert _lines(refund) == [("1-1101", 0, 300000.0), ("1-1301", 300000.0, 0)]
    assert db.rahaza_cash_movements.docs[0]["amount"] == 300000


def test_periode_tertutup_ditolak_sebelum_efek(monkeypatch):
    old = (TODAY - timedelta(days=40)).isoformat()
    db = _sd_db(sale_date=old)
    db.rahaza_periods.docs.append({"id": "p1", "period_code": old[:7], "status": "closed"})
    sd, st = _sd_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(sd.process_direct_sale_return(db, "N1", {**_ret_body(), "return_date": old}, SA))
    assert e.value.status_code == 400 and "ditutup" in e.value.detail
    assert st.adds == [] and st.cns == [] and db.sales_direct_returns.docs == []


def test_tanggal_retur_sebelum_nota_atau_masa_depan_ditolak(monkeypatch):
    db = _sd_db()
    sd, st = _sd_env(monkeypatch, db)
    for d, kata in (((TODAY - timedelta(days=4)).isoformat(), "lebih awal"),
                    ((TODAY + timedelta(days=1)).isoformat(), "belum terjadi"), ("25/11/2026", "YYYY-MM-DD")):
        with pytest.raises(HTTPException) as e:
            run(sd.process_direct_sale_return(db, "N1", {**_ret_body(), "return_date": d}, SA))
        assert e.value.status_code == 400 and kata in e.value.detail
    assert st.adds == []


def test_jurnal_gagal_sesudah_efek_dicatat_di_post_error(monkeypatch):
    db = _sd_db()
    sd, st = _sd_env(monkeypatch, db)
    st.je_result = {"ok": False, "error": "Periode 2026-11 sudah closed. Posting ditolak."}
    out = run(sd.process_direct_sale_return(db, "N1", _ret_body(), SA))
    doc = db.sales_direct_returns.docs[0]
    assert out["status"] == doc["status"] == "posted" and len(st.adds) == 1
    assert doc["post_error"].startswith("Balik HPP:") and "closed" in doc["post_error"]
    assert doc["cogs_post_error"]


def test_gagal_sebelum_efek_retur_dibatalkan_dan_bisa_diulang(monkeypatch):
    db = _sd_db()
    sd, st = _sd_env(monkeypatch, db)

    async def boom(*_a, **_k):
        raise RuntimeError("db putus")
    monkeypatch.setattr(stock_service, "add", boom)
    with pytest.raises(RuntimeError):
        run(sd.process_direct_sale_return(db, "N1", _ret_body(5), SA))
    assert db.sales_direct_returns.docs[0]["status"] == "cancelled"
    assert db.sales_direct_notes.docs[0].get("return_lock") is None
    sd, st = _sd_env(monkeypatch, db)                              # diulang: qty 5 bebas lagi
    assert run(sd.process_direct_sale_return(db, "N1", _ret_body(5), SA))["status"] == "posted"


def test_gagal_di_tengah_efek_retur_tertahan_dan_masuk_daftar_belum_berjurnal(monkeypatch):
    db = _sd_db()
    sd, st = _sd_env(monkeypatch, db)

    async def boom(*_a, **_k):
        raise RuntimeError("koneksi putus")
    monkeypatch.setattr(rp, "post_credit_note", boom)
    with pytest.raises(RuntimeError):
        run(sd.process_direct_sale_return(db, "N1", _ret_body(3), SA))
    doc = db.sales_direct_returns.docs[0]
    assert doc["status"] == "processing" and doc["post_error"].startswith("Retur terhenti di tengah proses")
    assert "stok DA-1-M +3" in doc["process_steps"] and len(st.adds) == 1
    with pytest.raises(HTTPException) as e:                       # qty yang sudah masuk stok tidak bisa diretur lagi
        run(sd.process_direct_sale_return(db, "N1", _ret_body(3), SA))
    assert e.value.status_code == 400 and len(st.adds) == 1


# ═════════════════════════════ 2. Retur Pembelian & Nota Debit ═════════════════════════════
@pytest.fixture
def posting(monkeypatch):
    jes = []

    async def none(*a, **k):
        return None

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2), lines
        je = {"id": f"je-{len(jes) + 1}", "je_number": f"JE-{len(jes) + 1}", "source_module": mod,
              "source_ref": ref, "lines": [dict(ln) for ln in lines]}
        jes.append(je)
        return {"ok": True, "je_id": je["id"], "je_number": je["je_number"]}
    monkeypatch.setattr(rp, "get_mapping", _mapping)
    monkeypatch.setattr(pp, "get_mapping", _mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)
    return types.SimpleNamespace(jes=jes)


@pytest.fixture
def stock(monkeypatch):
    st = {"onhand": {}, "ops": []}

    def rec(op):
        async def f(*a, **k):
            st["ops"].append((op, a[:4]))
            return {}
        return f

    async def onhand(mid, db=None):
        return st["onhand"].get(mid, 0.0)
    for op in ("add", "issue", "move", "release", "reserve"):
        monkeypatch.setattr(stock_service, op, rec(op))
    monkeypatch.setattr(stock_service, "get_onhand", onhand)

    async def qloc(db):
        return "LOC-Q"
    monkeypatch.setattr(qmod, "get_quarantine_location_id", qloc)
    return st


def _rtp_env(monkeypatch, db, user=SA):
    import routes.rahaza_purchase_returns as rpr

    async def auth(_r):
        return user

    async def noop(*a, **k):
        return None

    async def yes(db_, lid):
        return True
    for f in ("_require_proc_wh", "_require_fin", "_require_view"):
        monkeypatch.setattr(rpr, f, auth)
    monkeypatch.setattr(rpr, "get_db", lambda: db)
    monkeypatch.setattr(rpr, "log_activity", noop)
    from core import location_resolver
    monkeypatch.setattr(location_resolver, "location_exists", yes)
    import routes.rahaza_inventory_shared as ris

    async def logmv(db_, user_, **kw):
        return kw
    monkeypatch.setattr(ris, "_log_movement", logmv)
    n = {"i": 0}

    async def gen(db_, coll, field, prefix, width=4, **kw):
        n["i"] += 1
        return f"{prefix}{n['i']:0{width}d}"
    monkeypatch.setattr(rpr, "gen_prefixed_number", gen)
    return rpr


def _rtp_db(*, billed=False, **inv):
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "X", "code": "KN-K20-TRC", "name": "Kain", "type": "fabric",
                                     "unit": "kg", "unit_cost": 55000.0})
    db.warehouse_receiving.docs.append({
        "id": "GR1", "receipt_number": "GR-00001", "status": "received", "supplier_name": "PT Uji",
        "items": [{"id": "L1", "material_id": "X", "received_qty": 100, "rejected_qty": 10, "unit_price": 50000.0,
                   "unit": "kg"}]})
    if billed:
        db.warehouse_receiving.docs[0].update({"ap_invoice_id": "AP1", "ap_invoice_number": "AP-0001"})
        db.rahaza_ap_invoices.docs.append({"id": "AP1", "invoice_number": "AP-0001", "vendor_name": "PT Uji",
                                           "status": "sent", "total": 4500000, "balance": 4500000,
                                           "gl_ap_account_code": "2-1100-SUP-1", **inv})
    db.rahaza_material_stock.docs.append({"material_id": "X", "location_id": "GD-L2", "qty": 190,
                                          "reserved_quantity": 0})
    return db


def _rtp_draft(rpr):
    return run(rpr.create_purchase_return(Req({"settlement": "debit_note", "reason": "berlubang", "gr_id": "GR1",
                                               "lines": [{"material_id": "X", "location_id": "GD-L2", "qty": 6,
                                                          "gr_item_id": "L1"}]})))


def test_kirim_ganda_bersamaan_409_stok_keluar_sekali(monkeypatch, posting, stock):
    db = _rtp_db()
    rpr = _rtp_env(monkeypatch, db)
    doc = _rtp_draft(rpr)
    out = []
    interleave(monkeypatch, stock_service, "issue", lambda: rpr.send_purchase_return(doc["id"], Req()), out)
    sent = run(rpr.send_purchase_return(doc["id"], Req()))
    assert isinstance(out[0], HTTPException) and out[0].status_code == 409
    assert sent["status"] == "awaiting_settlement"
    assert [op for op in stock["ops"] if op[0] == "issue"] == [("issue", ("X", "GD-L2", 6.0))]
    assert len([je for je in posting.jes if je["source_ref"].endswith(":send")]) == 1
    assert db[pr.RTP_COLL].docs[0].get("proc_lock") is None
    with pytest.raises(HTTPException) as e:                       # kirim lagi sesudah selesai
        run(rpr.send_purchase_return(doc["id"], Req()))
    assert e.value.status_code == 400
    assert len([op for op in stock["ops"] if op[0] == "issue"]) == 1


def test_batal_retur_tidak_menyalip_kirim_yang_berjalan(monkeypatch, posting, stock):
    db = _rtp_db()
    rpr = _rtp_env(monkeypatch, db)
    doc = _rtp_draft(rpr)
    out = []
    interleave(monkeypatch, stock_service, "issue", lambda: rpr.cancel_purchase_return(doc["id"], Req()), out)
    run(rpr.send_purchase_return(doc["id"], Req()))
    assert isinstance(out[0], HTTPException) and out[0].status_code == 409
    assert db[pr.RTP_COLL].docs[0]["status"] == "awaiting_settlement"


def test_nota_debit_ganda_ditolak_satu_jurnal_satu_potongan(monkeypatch, posting, stock):
    db = _rtp_db()
    rpr = _rtp_env(monkeypatch, db)
    doc = _rtp_draft(rpr)
    run(rpr.send_purchase_return(doc["id"], Req()))
    out = []
    interleave(monkeypatch, rp, "post_purchase_return",
               lambda: rpr.issue_debit_note(Req({"purchase_return_id": doc["id"]})), out)
    dn = run(rpr.issue_debit_note(Req({"purchase_return_id": doc["id"]})))
    assert isinstance(out[0], HTTPException) and out[0].status_code == 409
    assert len(db[pr.DN_COLL].docs) == 1 and dn["grni_amount"] == 300000
    dn_jes = [je for je in posting.jes if je["source_ref"].startswith("dn:")]
    assert [je["source_ref"] for je in dn_jes] == [f"dn:{doc['id']}"]          # kunci jurnal tetap per retur
    assert len(db.warehouse_receiving.docs[0]["items"][0]["billing_deductions"]) == 1
    assert db[pr.RTP_COLL].docs[0]["status"] == "settled" and db[pr.RTP_COLL].docs[0].get("proc_lock") is None
    with pytest.raises(HTTPException) as e:                       # diterbitkan lagi sesudah selesai
        run(rpr.issue_debit_note(Req({"purchase_return_id": doc["id"]})))
    assert e.value.status_code == 400 and len(db[pr.DN_COLL].docs) == 1


def test_nota_debit_sesudah_faktur_menambah_debit_note_amount(monkeypatch, posting, stock):
    db = _rtp_db(billed=True)
    rpr = _rtp_env(monkeypatch, db)
    doc = _rtp_draft(rpr)
    run(rpr.send_purchase_return(doc["id"], Req()))
    dn = run(rpr.issue_debit_note(Req({"purchase_return_id": doc["id"]})))
    inv = db.rahaza_ap_invoices.docs[0]
    assert inv["debit_note_amount"] == 300000 and dn["ap_amount"] == 300000
    assert dn["ap_invoice_id"] == "AP1"
    assert dn["ap_invoice_allocations"] == [{"ap_invoice_id": "AP1", "invoice_number": "AP-0001", "amount": 300000.0}]
    assert _lines(posting.jes[-1]) == [("1-1620", 0, 300000.0), ("2-1100-SUP-1", 300000.0, 0)]
    assert rpr.ap_open_amount(inv) == 4200000
    # sisa dibayar lunas (pembayaran hutang menulis balance = total − nota debit − dibayar = 0): saldo pemasok 0,
    # nota debit tidak terhitung dua kali
    inv.update({"paid_amount": 4200000, "balance": 0, "status": "paid"})
    row = run(rpr.supplier_balances(Req()))["items"][0]
    assert (row["invoice_balance"], row["debit_note_ap"], row["net_payable"]) == (300000, 300000, 0)


def test_nota_debit_melebihi_sisa_faktur_dipotong_sebesar_sisa_kelebihan_piutang_pemasok(monkeypatch, posting, stock):
    """Barang diretur sesudah faktur hampir lunas: faktur dipotong sebesar sisanya, kelebihannya tetap mendebit Hutang
    (pemasok berutang ke DA, ditagih lewat Refund) — perilaku lama dipertahankan, bukan ditolak."""
    db = _rtp_db(billed=True, paid_amount=4300000)                # sisa 200.000 < potongan 300.000
    rpr = _rtp_env(monkeypatch, db)
    doc = _rtp_draft(rpr)
    run(rpr.send_purchase_return(doc["id"], Req()))
    dn = run(rpr.issue_debit_note(Req({"purchase_return_id": doc["id"]})))
    inv = db.rahaza_ap_invoices.docs[0]
    assert inv["debit_note_amount"] == 200000 and rpr.ap_open_amount(inv) == 0
    assert dn["ap_amount"] == 300000 and dn["kelebihan_piutang_pemasok"] == 100000
    assert dn["ap_invoice_allocations"] == [{"ap_invoice_id": "AP1", "invoice_number": "AP-0001", "amount": 200000.0}]
    assert _lines(posting.jes[-1]) == [("1-1620", 0, 300000.0), ("2-1100-SUP-1", 300000.0, 0)]


def test_nota_debit_gagal_di_tengah_potongan_faktur_dikembalikan(monkeypatch, posting, stock):
    db = _rtp_db(billed=True)
    rpr = _rtp_env(monkeypatch, db)
    doc = _rtp_draft(rpr)
    run(rpr.send_purchase_return(doc["id"], Req()))

    async def boom(db_, coll, field, prefix, width=4, **kw):
        raise RuntimeError("penomoran putus")
    monkeypatch.setattr(rpr, "gen_prefixed_number", boom)
    with pytest.raises(RuntimeError):
        run(rpr.issue_debit_note(Req({"purchase_return_id": doc["id"]})))
    assert db.rahaza_ap_invoices.docs[0]["debit_note_amount"] == 0
    assert db[pr.RTP_COLL].docs[0]["status"] == "awaiting_settlement" and db[pr.DN_COLL].docs == []


# ═════════════════════════════ 3. Batalkan / pulihkan penyesuaian stok ═════════════════════════════
@pytest.fixture
def gl(monkeypatch):
    st = types.SimpleNamespace(jes=[], voids=[], adjusts=[], fail=None, adjust_error=None)

    async def find(db, mod, ref, entity=None):
        return {"id": "je-op", "je_number": "JE-OP"} if (mod, ref) == ("inventory_count_variance", "opname:S1") else None

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        if st.fail:
            return {"ok": False, "error": st.fail}
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2), lines
        st.jes.append({"id": f"je-{len(st.jes) + 1}", "date": d, "source_module": mod, "source_ref": ref,
                       "lines": [dict(ln) for ln in lines]})
        return {"ok": True, "je_id": st.jes[-1]["id"], "je_number": f"JE-{len(st.jes)}"}

    async def void(db, mod, ref, user, reason="", **kw):
        st.voids.append((mod, ref))
        return {"ok": True, "voided": True}

    async def adjust(mid, loc, new_qty, **kw):
        if st.adjust_error:
            raise st.adjust_error
        st.adjusts.append((mid, loc, new_qty, kw.get("ref")))
        for r in kw["db"].rahaza_material_stock.docs:
            if r["material_id"] == mid and r["location_id"] == loc:
                r["qty"] = new_qty
        return {}
    monkeypatch.setattr(rp, "get_mapping", _mapping)
    monkeypatch.setattr(pp, "get_mapping", _mapping)
    monkeypatch.setattr(rp, "_find_existing_je", find)
    monkeypatch.setattr(rp, "_create_posted_je", create)
    monkeypatch.setattr(rp, "_void_je_by_source", void)
    monkeypatch.setattr(stock_service, "adjust", adjust)
    return st


def _undo_db(*, delta=-5.0, qty=95.0, reason="", opname=True):
    db = fm.FakeDB()
    line = {"key": "M1", "material_id": "M1", "material_code": "KN-1", "material_name": "Kain", "unit": "kg",
            "kind": "bahan", "bin_id": "", "unit_cost": 1000.0, "reason": reason}
    db.wh_opname3_sessions.docs.append({
        "id": "S1", "session_no": "OPN-1", "engine": "k9", "status": "approved", "lines": [line],
        "result": {"lines": [{**line, "variance_qty": delta, "variance_value": round(delta * 1000.0, 2)}]}})
    db.rahaza_stock_ledger.docs.append({
        "id": "lg1", "op": "adjust", "material_id": "M1", "location_id": "L1", "delta": delta,
        "created_at": datetime.now(timezone.utc),
        "ref": {"source": "opname", "type": "opname", "session_id": "S1", "session_no": "OPN-1"} if opname else {}})
    db.rahaza_material_stock.docs.append({"material_id": "M1", "location_id": "L1", "qty": qty})
    return db


def _qty(db):
    return db.rahaza_material_stock.docs[0]["qty"]


def test_batalkan_penyesuaian_menjurnal_pembalik_lalu_pulihkan_menjurnal_ulang(gl):
    import routes.dewi_warehouse_smart as dws
    db = _undo_db()
    res = run(dws.undo_adjustment(db, "lg1", SA))
    assert res["undone"] and res["je_number"] == "JE-1" and _qty(db) == 100.0
    je = gl.jes[0]
    assert (je["source_module"], je["source_ref"], je["date"]) == ("inventory_count_variance", "undo_adjustment:lg1:1",
                                                                   TODAY)
    assert _lines(je) == [("1-1401", 5000.0, 0), ("5-1950", 0, 5000.0)]       # opname −5 dibalik: persediaan naik
    ent = db.rahaza_stock_ledger.docs[0]
    assert ent["soft_deleted"] is True and ent["undo_je_number"] == "JE-1" and ent["undo_applied_qty"] == 5.0
    assert gl.adjusts[0][3]["gl_je_number"] == "JE-1"
    run(dws.restore_adjustment(db, "lg1", SA))
    assert _qty(db) == 95.0 and gl.jes[1]["source_ref"] == "restore_adjustment:lg1:1"
    assert _lines(gl.jes[1]) == [("1-1401", 0, 5000.0), ("5-1950", 5000.0, 0)]
    run(dws.undo_adjustment(db, "lg1", SA))                        # siklus kedua = kunci jurnal baru
    assert gl.jes[2]["source_ref"] == "undo_adjustment:lg1:2"


def test_jurnal_gagal_undo_ditolak_stok_tidak_berubah(gl):
    import routes.dewi_warehouse_smart as dws
    db = _undo_db()
    gl.fail = "Periode 2026-11 sudah closed. Posting ditolak."
    with pytest.raises(HTTPException) as e:
        run(dws.undo_adjustment(db, "lg1", SA))
    assert e.value.status_code == 400 and "Stok belum diubah" in e.value.detail
    assert gl.adjusts == [] and _qty(db) == 95.0
    assert db.rahaza_stock_ledger.docs[0]["soft_deleted"] is False            # masih bisa dibatalkan nanti


def test_stok_gagal_sesudah_jurnal_jurnalnya_dibatalkan(gl):
    import routes.dewi_warehouse_smart as dws
    db = _undo_db()
    gl.adjust_error = RuntimeError("db putus")
    with pytest.raises(RuntimeError):
        run(dws.undo_adjustment(db, "lg1", SA))
    assert gl.voids == [("inventory_count_variance", "undo_adjustment:lg1:1")]
    assert db.rahaza_stock_ledger.docs[0]["soft_deleted"] is False


def test_baris_rusak_dibalik_ke_beban_rusak(gl):
    import routes.dewi_warehouse_smart as dws
    db = _undo_db(reason="rusak")
    run(dws.undo_adjustment(db, "lg1", SA))
    assert _lines(gl.jes[0]) == [("1-1401", 5000.0, 0), ("6-4300", 0, 5000.0)]


def test_undo_tidak_di_bawah_nol_jurnal_sebesar_yang_dibalik(gl):
    import routes.dewi_warehouse_smart as dws
    db = _undo_db(delta=5.0, qty=2.0)                               # opname +5, sisa stok kini 2
    res = run(dws.undo_adjustment(db, "lg1", SA))
    assert _qty(db) == 0.0 and res["applied_qty"] == -2.0
    assert _lines(gl.jes[0]) == [("1-1401", 0, 2000.0), ("5-1950", 2000.0, 0)]


def test_penyesuaian_tanpa_sesi_opname_tanpa_jurnal(gl):
    import routes.dewi_warehouse_smart as dws
    db = _undo_db(opname=False)
    res = run(dws.undo_adjustment(db, "lg1", SA))
    assert res["je_number"] is None and gl.jes == [] and _qty(db) == 100.0
    assert "bukan dari sesi opname" in db.rahaza_stock_ledger.docs[0]["undo_gl_note"]
