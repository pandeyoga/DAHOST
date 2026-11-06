"""Tahap 2 (6 Nov 2026) — paket MAKLON: keputusan owner dijalankan.

Satu uji (atau lebih) per butir:
  1. Piutang klien & hutang CMT TERJADWAL saat PO dikonfirmasi (tanpa jurnal); pendapatan per kiriman
     (Dr 1-1305-<KODE> / Cr 4-1500-<KODE> + PPN bila PKP); uang muka otomatis dipakai; pembayaran
     dibagi piutang/uang muka; koreksi & hapus kiriman dibalik; ubah PO menyegarkan jadwal; batal PO.
     Hutang CMT: bisa dibayar ≤ lolos QC − dibayar − tertahan; selisih diputuskan Keuangan.
  2. Akun per klien (Auto Akun) + migrasi (pratinjau / apply / reklasifikasi).
  3. Harga jasa wajib (tanpa cadangan upah CMT).
  4. Lebih qty boleh dengan alasan wajib (deklarasi, terima QC, kirim klien, tagihan).
  5. Tutup PO per ukuran; dua tombol satu pemeriksaan; PO tertutup terkunci.
  6. Komponen kurang: barang dari master + "Terkirim" memotong stok lewat mesin MI.
  7. HPP Jahit: aksesoris diprorata per pcs dikirim.
  8. Overhead 15% legacy dihapus.
  9. Quick Complete tidak melompati Draf.
 10. Ubah PO tidak mengembalikan status & tidak meninggalkan job yatim.
"""
import asyncio
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
import auth  # noqa: E402
import routes.coa_auto as coa_auto  # noqa: E402
import routes.dewi_maklon_finance as dmf  # noqa: E402
import routes.dewi_maklon_pos as dmpos  # noqa: E402
import routes.dewi_maklon_billing as billing  # noqa: E402
import routes.production_maklon_bridge as bridge  # noqa: E402
import routes.production_pos as ppos  # noqa: E402
import routes.rahaza_posting as rposting  # noqa: E402
import routes.rahaza_posting_profiles as profiles  # noqa: E402
import routes.dewi_cmt_component_requests as ccr  # noqa: E402
import routes.dewi_cmt_packing as dcp  # noqa: E402
import routes.buyer_shipment as bsr  # noqa: E402
from core import maklon_ledger as ml  # noqa: E402
from core import over_qty  # noqa: E402
from core import po_lock  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
USER = {"id": "u1", "name": "Admin Uji", "role": "admin"}
FIN = {"id": "f1", "name": "Keuangan Uji", "role": "accounting"}
TODAY = datetime.now(timezone.utc).strftime("%Y-%m")

MAPPING = {
    "maklon_ar_invoice": {"debit_ar": "1-1301", "credit_revenue_maklon": "4-1100", "credit_tax_output": "2-1400"},
    "maklon_advance_payment": {"debit_cash_default": "1-1201", "credit_advance_customer": "2-1700"},
    "cmt_ap_invoice": {"credit_ap": "2-1110", "debit_cmt_expense_maklon": "5-4200"},
    "ar_payment": {"credit_ar": "1-1301", "debit_cash_default": "1-1201"},
}


def run(c):
    return asyncio.run(c)


async def _user(*_a, **_k):
    return dict(USER)


async def _noop(*_a, **_k):
    return None


def _base_db():
    db = FakeDB()
    db.rahaza_periods.docs = [{"period_code": TODAY, "status": "open"}]
    db.rahaza_coa_accounts.docs = [
        {"code": c, "name": n, "type": t, "is_group": g, "active": True}
        for c, n, t, g in (("1-1301", "Piutang Dagang", "ASSET", False), ("1-1305", "Piutang Maklon", "ASSET", False),
                           ("4-1500", "Pendapatan Maklon", "REVENUE", True), ("4-1100", "Penjualan", "REVENUE", False),
                           ("2-1400", "PPN Keluaran", "LIABILITY", False), ("2-1700", "Uang Muka Maklon", "LIABILITY", False),
                           ("1-1201", "Bank BCA", "ASSET", False), ("2-1110", "Hutang CMT", "LIABILITY", False),
                           ("5-4200", "Biaya CMT Maklon", "COGS", False))]
    db.dewi_maklon_clients.docs = [{"id": "cl1", "code": "KOH-01", "name": "PT Klien Satu", "status": "active"}]
    db.rahaza_cash_accounts.docs = [{"id": "kas1", "name": "BCA", "gl_account_code": "1-1201", "active": True}]
    db.production_pos.docs = [{"id": "po1", "po_number": "PO-MKL-1", "business_type": "maklon", "status": "Draft",
                               "buyer_id": "cl1", "customer_name": "PT Klien Satu", "vendor_id": "v1",
                               "vendor_name": "CMT A"}]
    db.po_items.docs = [
        {"id": "pi-s", "po_id": "po1", "qty": 50, "size": "S", "sku": "KLN-S", "selling_price_snapshot": 20000,
         "cmt_price_snapshot": 12000, "created_at": "2026-11-01T00:00:00"},
        {"id": "pi-m", "po_id": "po1", "qty": 50, "size": "M", "sku": "KLN-M", "selling_price_snapshot": 20000,
         "cmt_price_snapshot": 12000, "created_at": "2026-11-01T00:00:01"}]
    db.vendor_partners.docs = [{"id": "v1", "name": "CMT A"}]
    return db


@pytest.fixture
def env(monkeypatch):
    db = _base_db()
    jes = []

    async def create_je(_db, je_date=None, memo="", source_module="", source_ref="", lines_raw=None, user=None, **_k):
        ex = next((j for j in db.rahaza_journal_entries.docs if j["source_module"] == source_module
                   and j["source_ref"] == source_ref and j["status"] != "voided"), None)
        if ex:
            return {"ok": True, "je_id": ex["id"], "je_number": ex["je_number"], "already_posted": True}
        codes = {a["code"]: a for a in db.rahaza_coa_accounts.docs}
        for ln in lines_raw:
            acc = codes.get(ln["account_code"])
            if not acc or acc.get("is_group"):
                return {"ok": False, "error": f"akun {ln['account_code']} tidak sah"}
        d = round(sum(float(x.get("debit") or 0) for x in lines_raw), 2)
        c = round(sum(float(x.get("credit") or 0) for x in lines_raw), 2)
        assert d == c, (d, c, lines_raw)
        je = {"id": f"je{len(jes) + 1}", "je_number": f"JE-{len(jes) + 1:04d}", "source_module": source_module,
              "source_ref": source_ref, "status": "posted", "date": je_date.isoformat(), "memo": memo,
              "total_debit": d,
              "lines": [{**x, "account_type": codes[x["account_code"]].get("type")} for x in lines_raw
                        if float(x.get("debit") or 0) or float(x.get("credit") or 0)]}
        jes.append(je)
        db.rahaza_journal_entries.docs.append(je)
        return {"ok": True, "je_id": je["id"], "je_number": je["je_number"]}

    async def mapping(_db, et):
        return dict(MAPPING.get(et, {}))

    counter = {"n": 0}

    async def inv_number(_db):
        counter["n"] += 1
        return f"INV-MKL-2026-{counter['n']:04d}"

    monkeypatch.setattr(dmf, "_create_posted_je", create_je)
    monkeypatch.setattr(rposting, "_create_posted_je", create_je)
    monkeypatch.setattr(dmf, "get_mapping", mapping)
    monkeypatch.setattr(profiles, "get_mapping", mapping)
    monkeypatch.setattr(dmpos, "_next_ar_invoice_number", inv_number)
    for mod in (coa_auto, ppos, bridge, bsr, dmf):
        monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(auth, "log_activity", _noop)
    for mod in (ppos, bsr, dmf, billing, ccr):
        monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(ppos, "require_auth", _user)
    return {"db": db, "jes": jes}


def _confirm(db):
    return run(ppos.transition_po_status("po1", FakeRequest({"status": "Confirmed"})))


def _ar(db):
    return next(a for a in db.rahaza_ar_invoices.docs if a.get("linked_maklon_po_id") == "po1")


def _dispatch(db, sid, seq, item, qty, *, received=None, reason=None, day="2026-11-05"):
    if not any(s["id"] == sid for s in db.buyer_shipments.docs):
        db.buyer_shipments.docs.append({"id": sid, "shipment_number": f"SJ-{sid}", "receiver_type": "buyer",
                                        "po_id": "po1"})
    it = {"id": f"{sid}-{seq}-{item}", "shipment_id": sid, "dispatch_seq": seq, "po_id": "po1", "po_item_id": item,
          "sku": item, "qty_shipped": qty, "dispatch_date": day, "created_at": day}
    if received is not None:
        it["qty_received"] = received
    if reason:
        it["over_qty_reason"] = reason
    db.buyer_shipment_items.docs.append(it)
    return it


def _je_lines(je):
    return {(ln["account_code"], "D" if float(ln.get("debit") or 0) else "C"): float(ln.get("debit") or ln.get("credit"))
            for ln in je["lines"]}


# ══════════════════════════════════════════════════════════════════════════════
# 2 · Akun per klien
# ══════════════════════════════════════════════════════════════════════════════
def test_akun_klien_dibuat_otomatis_dan_idempoten(env):
    db = env["db"]
    out = run(ml.ensure_client_accounts(db, db.dewi_maklon_clients.docs[0], USER))
    assert out == {"maklon_client": "1-1305-KOH-01", "maklon_revenue": "4-1500-KOH-01"}
    rev = next(a for a in db.rahaza_coa_accounts.docs if a["code"] == "4-1500-KOH-01")
    assert rev["type"] == "REVENUE" and rev["parent_code"] == "4-1500" and not rev["is_group"]
    assert rev["flags"]["subledger_entity_type"] == "maklon_revenue" and rev["flags"]["subledger_entity_id"] == "cl1"
    run(ml.ensure_client_accounts(db, db.dewi_maklon_clients.docs[0], USER))
    assert len([a for a in db.rahaza_coa_accounts.docs if a["code"].startswith("4-1500-")]) == 1
    assert db.dewi_maklon_clients.docs[0]["revenue_account_code"] == "4-1500-KOH-01"
    assert coa_auto.DEFAULT_ENTITY_TYPES["maklon_revenue"]["parent_code"] == "4-1500"


# ══════════════════════════════════════════════════════════════════════════════
# 3 · Harga jasa wajib
# ══════════════════════════════════════════════════════════════════════════════
def test_konfirmasi_menolak_baris_tanpa_harga_jasa(env):
    db = env["db"]
    db.po_items.docs[1]["selling_price_snapshot"] = 0
    with pytest.raises(HTTPException) as e:
        _confirm(db)
    assert e.value.status_code == 400 and "Harga jasa ke klien belum diisi" in e.value.detail and "KLN-M" in e.value.detail
    assert db.production_pos.docs[0]["status"] == "Draft" and not db.rahaza_ar_invoices.docs


def test_tanpa_cadangan_upah_cmt(env):
    db = env["db"]
    db.po_items.docs[1]["selling_price_snapshot"] = 0
    f = run(bridge.compute_po_fulfillment(db, "po1"))
    assert f["rate_by_item"]["pi-m"] == 0.0           # dulu 12.000 (upah CMT)
    assert ppos.missing_harga_jasa(db.po_items.docs) == ["KLN-M M"]
    src = (REPO / "backend" / "routes" / "production_maklon_bridge.py").read_text(encoding="utf-8")
    assert "cmt_fallback" not in src


def test_label_katalog_harga_jasa():
    src = (REPO / "frontend" / "src" / "components" / "erp" / "MaklonBuyerCatalogModule.jsx").read_text(encoding="utf-8")
    assert "Harga jasa ke klien (bawaan)" in src and "Harga Jual Default" not in src


# ══════════════════════════════════════════════════════════════════════════════
# 1 · Piutang terjadwal & pendapatan per kiriman
# ══════════════════════════════════════════════════════════════════════════════
def test_konfirmasi_membuat_piutang_terjadwal_tanpa_jurnal(env):
    db = env["db"]
    _confirm(db)
    ar = _ar(db)
    assert ar["schedule_mode"] == "v2" and ar["status"] == "scheduled"
    assert ar["scheduled_total"] == 2_000_000 and ar["billed_total"] == 0 and ar["total"] == 0
    assert ar["gl_ar_account_code"] == "1-1305-KOH-01" and ar["revenue_account_code"] == "4-1500-KOH-01"
    assert env["jes"] == []                                     # tidak ada jurnal saat konfirmasi
    sched = db.dewi_cmt_ap_schedules.docs
    assert len(sched) == 1 and sched[0]["vendor_id"] == "v1" and sched[0]["scheduled_amount"] == 1_200_000
    assert db.production_pos.docs[0].get("confirmed_by") == "Admin Uji"


def test_pendapatan_dibukukan_per_kiriman(env):
    db, jes = env["db"], env["jes"]
    _confirm(db)
    _dispatch(db, "sj1", 1, "pi-s", 30)
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))
    assert len(jes) == 1 and jes[0]["source_module"] == "maklon_revenue"
    assert _je_lines(jes[0]) == {("1-1305-KOH-01", "D"): 600000.0, ("4-1500-KOH-01", "C"): 600000.0}
    assert jes[0]["date"] == "2026-11-05"                       # tanggal kirim
    ar = _ar(db)
    assert (ar["billed_total"], ar["amount_due"], ar["status"]) == (600000.0, 600000.0, "issued")
    assert ar["due_date"] == "2026-12-05" and ar["scheduled_remaining"] == 1_400_000
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))     # idempoten
    assert len(jes) == 1


def test_ppn_bila_pkp(env):
    db, jes = env["db"], env["jes"]
    db.company_settings.docs = [{"type": "general", "tax_profile": {"pkp": True, "pkp_since": "2026-01-01"}}]
    _confirm(db)
    _dispatch(db, "sj1", 1, "pi-s", 10)
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))
    lines = _je_lines(jes[0])
    assert lines[("4-1500-KOH-01", "C")] == 200000 and lines[("2-1400", "C")] == 22000
    assert lines[("1-1305-KOH-01", "D")] == 222000 and _ar(db)["kena_ppn"] is True


def test_uang_muka_sebelum_kirim_dipakai_otomatis(env):
    db, jes = env["db"], env["jes"]
    _confirm(db)
    ar = _ar(db)
    pay = run(ml.record_client_payment(db, ar["id"], amount=500000, cash_account_id="kas1",
                                       payment_date="2026-11-03", user=FIN))
    assert (pay["ar_portion"], pay["advance_portion"]) == (0, 500000)
    assert _je_lines(jes[0]) == {("1-1201", "D"): 500000.0, ("2-1700", "C"): 500000.0}
    _dispatch(db, "sj1", 1, "pi-s", 30)
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))
    assert [j["source_module"] for j in jes] == ["maklon_payment", "maklon_revenue", "maklon_advance_apply"]
    assert _je_lines(jes[2]) == {("2-1700", "D"): 500000.0, ("1-1305-KOH-01", "C"): 500000.0}
    ar = _ar(db)
    assert (ar["amount_due"], ar["advance_balance"], ar["status"]) == (100000.0, 0.0, "partial_paid")
    assert db.rahaza_cash_movements.docs[0]["category"] == "ar_payment"


def test_pembayaran_setelah_kirim_tutup_piutang_lalu_uang_muka(env):
    db, jes = env["db"], env["jes"]
    _confirm(db)
    _dispatch(db, "sj1", 1, "pi-s", 40)
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))
    pay = run(ml.record_client_payment(db, _ar(db)["id"], amount=1_000_000, cash_account_id="kas1",
                                       payment_date=None, user=FIN))
    assert (pay["ar_portion"], pay["advance_portion"]) == (800000.0, 200000.0)
    assert _je_lines(jes[-1]) == {("1-1201", "D"): 1_000_000.0, ("1-1305-KOH-01", "C"): 800000.0,
                                  ("2-1700", "C"): 200000.0}
    with pytest.raises(ValueError):                             # melebihi sisa PO (2 jt − 1 jt)
        run(ml.record_client_payment(db, _ar(db)["id"], amount=1_100_000, cash_account_id="kas1",
                                     payment_date=None, user=FIN))


def test_koreksi_turun_dan_hapus_kiriman_dibalik(env):
    db, jes = env["db"], env["jes"]
    _confirm(db)
    it = _dispatch(db, "sj1", 1, "pi-s", 30)
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))
    next(x for x in db.buyer_shipment_items.docs if x["id"] == it["id"])["qty_received"] = 25
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))
    assert _je_lines(jes[1]) == {("4-1500-KOH-01", "D"): 100000.0, ("1-1305-KOH-01", "C"): 100000.0}
    db.buyer_shipment_items.docs = []
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))
    ar = _ar(db)
    assert ar["billed_total"] == 0 and ar["revenue_lines"] == [] and ar["status"] == "scheduled"
    assert len({j["source_ref"] for j in jes}) == 3            # tiap koreksi = jurnal baru, jurnal lama utuh


def test_ubah_po_menyegarkan_jadwal(env):
    db = env["db"]
    _confirm(db)
    body = {"items": [{"id": "pi-s", "qty": 60, "sku": "KLN-S", "size": "S"},
                      {"id": "pi-m", "qty": 50, "sku": "KLN-M", "size": "M"}], "status": "Draft"}
    run(ppos.update_po("po1", FakeRequest(body)))
    assert db.production_pos.docs[0]["status"] == "Confirmed"          # status TIDAK kembali ke Draf
    assert next(i for i in db.po_items.docs if i["id"] == "pi-s")["selling_price_snapshot"] == 20000
    assert _ar(db)["scheduled_total"] == 2_200_000
    assert db.dewi_cmt_ap_schedules.docs[0]["scheduled_amount"] == 1_320_000


def test_ubah_po_tidak_menghapus_baris_ber_job(env):
    db = env["db"]
    _confirm(db)
    db.production_job_items.docs = [{"id": "ji1", "job_id": "j1", "po_item_id": "pi-m", "produced_qty": 0}]
    with pytest.raises(HTTPException) as e:
        run(ppos.update_po("po1", FakeRequest({"items": [{"id": "pi-s", "qty": 50, "sku": "KLN-S", "size": "S"}]})))
    assert e.value.status_code == 400 and "job produksi" in e.value.detail
    assert len(db.po_items.docs) == 2


def test_batal_po_void_jadwal_sebelum_jurnal_dan_ditolak_sesudahnya(env, monkeypatch):
    db = env["db"]
    _confirm(db)
    run(ml.void_schedules(db, "po1", USER, "uji"))
    assert _ar(db)["status"] == "cancelled" and db.dewi_cmt_ap_schedules.docs[0]["status"] == "cancelled"
    db2 = _base_db()
    monkeypatch.setattr(ppos, "get_db", lambda: db2)
    monkeypatch.setattr(bsr, "get_db", lambda: db2)
    env["db"] = db2
    run(ppos.transition_po_status("po1", FakeRequest({"status": "Confirmed"})))
    _dispatch(db2, "sj1", 1, "pi-s", 5)
    run(bridge.sync_po_to_maklon_finance(db2, "po1", USER))
    with pytest.raises(ValueError) as e:
        run(ml.void_schedules(db2, "po1", USER, "uji"))
    assert "pendapatan sudah dibukukan" in str(e.value)


def test_tagihan_lebih_qty_tanpa_alasan_ditahan():
    lines = [{"id": "a", "po_item_id": "p", "qty_shipped": 8, "dispatch_date": "2026-11-01"},
             {"id": "b", "po_item_id": "p", "qty_shipped": 5, "dispatch_date": "2026-11-02"},
             {"id": "c", "po_item_id": "p", "qty_shipped": 2, "dispatch_date": "2026-11-03", "over_qty_reason": "bonus klien"}]
    targets, held = ml.billable_targets(lines, {"p": 10})
    assert targets == {"a": 8, "b": 2, "c": 2} and held[0]["shipment_item_id"] == "b" and held[0]["qty"] == 3


def test_jadwal_hutang_cmt_per_vendor_murni():
    items = [{"id": "s", "qty": 50}, {"id": "m", "qty": 50}]
    sent = [{"vendor_id": "v2", "po_item_id": "s", "qty": 20}]
    assert ml.split_by_vendor(items, sent, "v1", False) == {"v2": {"s": 20}, "v1": {"s": 30, "m": 50}}
    assert ml.split_by_vendor(items, sent, "v1", True) == {"v2": {"s": 20}}


def test_bayar_cmt_dibatasi_nilai_lolos_qc_dan_bagian_tertahan(env, monkeypatch):
    db = env["db"]
    _confirm(db)
    bill = {"id": "pay1", "payment_code": "PAY-CMT-1", "po_id": "po1", "vendor_id": "v1", "subtotal": 600000,
            "net_amount": 600000, "paid_amount": 100000, "status": "posted", "gl_je_id": "x",
            "variance_flagged": True, "needs_finance_review": True, "overbilled_amount": 120000,
            "variance_reason": "koreksi QC turun", "gl_ap_account_code": "2-1110", "total_pcs": 50}
    db.dewi_cmt_payments.docs = [bill]
    assert ml.cmt_bill_blocked(bill) == 120000 and ml.cmt_bill_payable(bill) == 380000
    with pytest.raises(HTTPException) as e:
        run(dmf.pay_cmt_payment("pay1", dmf.CmtPayIn(cash_account_id="kas1", amount=400000), user=FIN))
    assert "Bisa dibayar Rp 380.000 dari Rp 600.000" in e.value.detail and "tertahan" in e.value.detail
    run(ml.refresh_ap_schedules(db, "po1", USER))
    s = db.dewi_cmt_ap_schedules.docs[0]
    assert (s["matured_amount"], s["paid_amount"], s["blocked_amount"], s["payable_amount"]) == (600000, 100000, 120000, 380000)
    assert db.dewi_cmt_payments.docs[0]["ap_schedule_id"] == s["id"]


def test_keuangan_memotong_selisih_tagihan_cmt(env):
    db, jes = env["db"], env["jes"]
    db.dewi_cmt_payments.docs = [{"id": "pay1", "payment_code": "PAY-CMT-1", "po_id": "po1", "subtotal": 600000,
                                  "net_amount": 600000, "paid_amount": 0, "needs_finance_review": True,
                                  "variance_flagged": True, "overbilled_amount": 120000,
                                  "gl_ap_account_code": "2-1110"}]
    db.rahaza_journal_entries.docs.append({"id": "jeA", "je_number": "JE-A", "source_module": "cmt_ap_invoice",
                                           "source_ref": "cmt_ap:pay1", "status": "posted",
                                           "lines": [{"account_code": "5-4200", "debit": 600000, "credit": 0},
                                                     {"account_code": "2-1110", "debit": 0, "credit": 600000}]})
    out = run(dmf.resolve_cmt_variance("pay1", dmf.CmtVarianceResolveIn(decision="potong", notes="reject final"),
                                       user=FIN))
    assert out["net_amount"] == 480000 and out["variance_resolution"]["decision"] == "potong"
    assert _je_lines(jes[-1]) == {("2-1110", "D"): 120000.0, ("5-4200", "C"): 120000.0}
    assert ml.cmt_bill_payable(out) == 480000


# ══════════════════════════════════════════════════════════════════════════════
# 5 · Tutup PO per ukuran + kunci
# ══════════════════════════════════════════════════════════════════════════════
def _to_production_complete(db):
    db.production_pos.docs[0]["status"] = "Production Complete"


def test_kekurangan_dihitung_per_ukuran(env):
    db = env["db"]
    _confirm(db)
    _dispatch(db, "sj1", 1, "pi-s", 45, received=45)
    _dispatch(db, "sj1", 1, "pi-m", 55, received=55, reason="klien minta lebih")
    f = run(bridge.compute_po_fulfillment(db, "po1"))
    assert f["total_fulfilled"] == 100 and f["qty_short"] == 5 and not f["is_full"]   # dulu: penuh
    assert [(ln["size"], ln["short"], ln["over"]) for ln in f["lines"]] == [("S", 5, 0), ("M", 0, 5)]
    out = run(bridge.try_auto_close_po_on_full(db, "po1", USER))
    assert out["closed"] is False and db.production_pos.docs[0]["status"] != "Completed"


def test_dua_tombol_tutup_satu_pemeriksaan(env):
    db = env["db"]
    _confirm(db)
    _dispatch(db, "sj1", 1, "pi-s", 45, received=45)
    _dispatch(db, "sj1", 1, "pi-m", 50, received=50)
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))
    _to_production_complete(db)
    with pytest.raises(HTTPException) as e:
        run(ppos.close_po("po1", FakeRequest({"close_reason": "Other"})))
    assert "kurang 5 pcs" in e.value.detail and "S kurang 5" in e.value.detail
    out = run(ppos.close_po("po1", FakeRequest({"closed_reason": "mutual_agreement", "close_notes": "sepakat"})))
    assert out["status"] == "Closed Short" and db.production_pos.docs[0]["status"] == "Closed Short"
    ar = _ar(db)
    assert ar["scheduled_total"] == ar["billed_total"] == 1_900_000          # jadwal menyusut, tanpa nota kredit
    assert not db.dewi_maklon_credit_notes.docs


def test_po_tertutup_terkunci(env):
    db = env["db"]
    for st in ("Closed", "Closed Short", "Completed"):
        db.production_pos.docs[0]["status"] = st
        with pytest.raises(HTTPException) as e:
            run(po_lock.assert_po_open(db, "po1", "kiriman"))
        assert e.value.status_code == 409 and "terkunci" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(ppos.update_po("po1", FakeRequest({"notes": "x"})))
    assert e.value.status_code == 409
    db.rahaza_materials.docs = [{"id": "m1", "code": "KAN-1", "name": "Kain", "type": "fabric", "unit": "kg"}]
    with pytest.raises(HTTPException) as e:
        run(ccr.create_request({"po_id": "po1", "request_type": "component",
                                "items": [{"material_id": "m1", "qty": 1}]}, user=USER))
    assert e.value.status_code == 409
    db.production_pos.docs[0]["status"] = "In Production"
    run(po_lock.assert_po_open(db, "po1", "kiriman"))   # terbuka → tidak melempar


# ══════════════════════════════════════════════════════════════════════════════
# 4 · Lebih qty dengan alasan wajib
# ══════════════════════════════════════════════════════════════════════════════
def test_lebih_qty_kirim_klien_wajib_alasan(env):
    db = env["db"]
    _confirm(db)
    _dispatch(db, "sj0", 1, "pi-s", 48)
    rows = run(bsr._over_qty_rows(db, [{"po_item_id": "pi-s", "qty_shipped": 5}], bsr.RECEIVER_BUYER, None))
    assert rows[0]["limit"] == 2 and rows[0]["over"] == 3
    with pytest.raises(HTTPException) as e:
        over_qty.require_reason(rows, "", "kirim_klien")
    assert e.value.status_code == 428 and "Kirim ke klien melebihi batas" in e.value.detail
    assert over_qty.require_reason(rows, "klien setuju tambah", "kirim_klien") == "klien setuju tambah"
    assert over_qty.require_reason([], None, "kirim_klien") == ""            # di bawah batas: tanpa alasan
    run(over_qty.record(db, "po1", "kirim_klien", rows, "klien setuju tambah", USER, ref={"shipment_id": "sjX"}))
    ev = db.production_pos.docs[0]["over_qty_events"][0]
    assert (ev["over"], ev["reason"], ev["by"]) == (3, "klien setuju tambah", "Admin Uji")


def test_lebih_qty_deklarasi_cmt_tidak_hitung_rework(env):
    db = env["db"]
    db.buyer_shipments.docs = [{"id": "d1", "receiver_type": "da"}]
    db.buyer_shipment_items.docs = [{"id": "x", "shipment_id": "d1", "po_item_id": "pi-s", "qty_shipped": 50, "job_id": "j1"},
                                    {"id": "y", "shipment_id": "d1", "po_item_id": "pi-s", "qty_shipped": 4, "job_id": "jr"}]
    db.production_jobs.docs = [{"id": "j1", "shipment_type": "NORMAL"}, {"id": "jr", "shipment_type": "REWORK"}]
    rows = run(bsr._over_qty_rows(db, [{"po_item_id": "pi-s", "qty_shipped": 1}], bsr.RECEIVER_DA, "j1"))
    assert rows and rows[0]["limit"] == 0                                  # 50 baru sudah = pesanan
    assert run(bsr._over_qty_rows(db, [{"po_item_id": "pi-s", "qty_shipped": 3}], bsr.RECEIVER_DA, "jr")) == []


def test_terima_qc_melebihi_deklarasi_wajib_alasan(monkeypatch):
    db = FakeDB()
    db.cmt_receipts.docs = [{"id": "r1", "receipt_code": "RCV-1", "status": "on_qc", "po_id": "po9"}]
    db.production_pos.docs = [{"id": "po9", "business_type": "maklon", "status": "In Production", "po_number": "PO-9"}]
    db.cmt_receipt_lines.docs = [{"id": "l1", "receipt_id": "r1", "sku_code": "SKU-A", "qty_actual": 52,
                                  "reject_qty": 1, "qty_shipped_by_cmt": 50, "po_item_id": "pi9"}]
    import routes.shared as shared
    monkeypatch.setattr(shared, "require_perm", _user)
    monkeypatch.setattr(dcp, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(dcp._finish_receipt("r1", FakeRequest({})))
    assert e.value.status_code == 428 and "Terima & QC dari CMT" in e.value.detail and "lebih 3 pcs" in e.value.detail
    assert db.cmt_receipts.docs[0]["status"] == "on_qc"


# ══════════════════════════════════════════════════════════════════════════════
# 6 · Komponen kurang
# ══════════════════════════════════════════════════════════════════════════════
def test_komponen_kurang_wajib_dari_master(env):
    db = env["db"]
    db.rahaza_materials.docs = [{"id": "m1", "code": "KAN-1", "name": "Kain", "type": "fabric", "unit": "kg"},
                                {"id": "fg1", "code": "FG-1", "name": "Kaos DA", "type": "fg"},
                                {"id": "a1", "code": "KANCING", "name": "Kancing", "type": "accessory", "unit": "pcs"}]
    for items, frag in (([{"component_type": "lengan", "qty": 2}], "ketik bebas"),
                        ([{"material_id": "fg1", "qty": 1}], "produk jadi"),
                        ([{"material_id": "a1", "qty": 1}], "bukan bahan")):
        with pytest.raises(HTTPException) as e:
            run(ccr._resolve_items_from_master(db, "component", items))
        assert frag in e.value.detail
    out = run(ccr._resolve_items_from_master(db, "accessory", [{"material_id": "a1", "qty": 10}]))
    assert out[0]["material_code"] == "KANCING" and out[0]["unit"] == "pcs"


def test_komponen_terkirim_memotong_stok_lewat_mesin_mi(env, monkeypatch):
    db = env["db"]
    db.production_pos.docs[0]["status"] = "In Production"
    from core import material_issue_engine as mie
    import routes.rahaza_inventory_shared as ris
    calls = {}

    async def best(_db, mid, qty):
        return "loc1", 99

    async def issue(_db, mi, user, loc_overrides=None, ref_type=None):
        calls["mi"], calls["ref"] = mi, ref_type
        return {"_posting_result": {"ok": True, "je_number": "JE-MI"}}

    async def mi_no(_db):
        return "MI-1"
    monkeypatch.setattr(mie, "best_location_for", best)
    monkeypatch.setattr(mie, "issue_material_issue", issue)
    monkeypatch.setattr(ris, "_gen_mi_number", mi_no)
    doc = {"id": "rq1", "request_code": "REQ-1", "po_id": "po1", "status": "ready",
           "items": [{"material_id": "a1", "material_code": "KANCING", "qty": 10}]}
    db.dewi_cmt_component_requests.docs = [doc]
    out = run(ccr.set_status("rq1", {"status": "delivered"}, user=USER))
    assert out["material_issue"]["material_issue_number"] == "MI-1"
    assert calls["mi"]["cost_target"] == "maklon" and calls["ref"] == "cmt_component_request"   # 5-4100
    assert db.dewi_cmt_component_requests.docs[0]["material_issue_id"]
    db.production_pos.docs[0]["business_type"] = "internal"
    db.dewi_cmt_component_requests.docs[0].update({"status": "ready", "material_issue_id": None})
    run(ccr.set_status("rq1", {"status": "delivered"}, user=USER))
    assert calls["mi"]["cost_target"] is None                                                  # WIP
    bad = {"id": "rq2", "request_code": "REQ-2", "status": "ready", "items": [{"component_type": "lengan", "qty": 1}]}
    db.dewi_cmt_component_requests.docs.append(bad)
    with pytest.raises(HTTPException):
        run(ccr.set_status("rq2", {"status": "delivered"}, user=USER))


# ══════════════════════════════════════════════════════════════════════════════
# 7 · HPP Jahit prorata · 8 · tanpa overhead · 9 · Quick Complete
# ══════════════════════════════════════════════════════════════════════════════
def test_hpp_jahit_aksesoris_prorata_pcs_dikirim(env):
    db = env["db"]
    db.rahaza_material_issues.docs = [{"id": "mi1", "production_po_id": "po1", "status": "issued", "qty_wo_pcs": 100,
                                       "items": [{"qty_issued": 100, "unit_cost_applied": 1000}]}]
    db.dewi_cmt_payments.docs = [{"id": "p1", "po_id": "po1", "subtotal": 1_080_000, "total_pcs": 90, "status": "posted"}]
    db.cmt_receipts.docs = [{"id": "r1", "status": "completed_qc"}]
    db.cmt_receipt_lines.docs = [{"id": "l1", "receipt_id": "r1", "po_item_id": "pi-s", "qty_actual": 90, "reject_qty": 10}]
    a = run(bridge.maklon_actual_costs(db, "po1"))
    assert a["accessory_cost_per_pcs"] == 1000 and a["accessory_cost_absorbed"] == 90000
    assert a["accessory_cost_unabsorbed"] == 10000 and a["hpp_per_pcs"] == 13000     # dulu 13.111
    assert a["total_cost"] == 1_180_000                                                # margin tetap biaya penuh


def test_overhead_legacy_dihapus(env, monkeypatch):
    db = env["db"]
    db.dewi_maklon_pos.docs = [{"id": "po1", "po_number": "PO-MKL-1", "client_id": "cl1", "client_name": "x",
                                "status": "confirmed", "total_qty": 10,
                                "items": [{"qty": 10, "selling_price_per_pcs": 20000}]}]
    monkeypatch.setattr(billing, "get_db", lambda: db)
    run(billing.upsert_hpp(billing.HPPIn(order_id="po1", overhead_pct=15,
                                         components=[billing.HPPComponent(name="jahit", qty=10, unit_cost=1000)]),
                           user=USER))
    doc = db.dewi_maklon_hpp.docs[0]
    assert doc["overhead_pct"] == 0 and doc["overhead_amount"] == 0 and doc["total_hpp"] == 10000


def test_quick_complete_tidak_melompati_draf(env):
    db = env["db"]
    with pytest.raises(HTTPException) as e:
        run(ppos.quick_complete_po("po1", FakeRequest({})))
    assert "konfirmasi PO dulu" in e.value.detail and db.production_pos.docs[0]["status"] == "Draft"
    src = (REPO / "backend" / "routes" / "production_pos.py").read_text(encoding="utf-8")
    assert "{'status': 'Distributed', 'updated_at': now()}" not in src


# ══════════════════════════════════════════════════════════════════════════════
# 2 · Migrasi + umur piutang
# ══════════════════════════════════════════════════════════════════════════════
def _load_migration():
    p = REPO / "backend" / "scripts" / "migrations" / "2026_11_06_maklon_akun_klien.py"
    spec = importlib.util.spec_from_file_location("mkl_akun", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_pratinjau_apply_reklasifikasi(env):
    db, jes = env["db"], env["jes"]
    mig = _load_migration()
    db.production_pos.docs[0]["status"] = "In Production"
    db.rahaza_ar_invoices.docs = [{"id": "old", "invoice_number": "INV-MKL-OLD", "source_module": "maklon_po",
                                   "linked_maklon_po_id": "po1", "status": "draft", "customer_id": "cl1"},
                                  {"id": "iss", "invoice_number": "INV-MKL-ISS", "source_module": "maklon_po",
                                   "linked_maklon_po_id": "poX", "status": "partial_paid", "customer_id": "cl1",
                                   "amount_due": 300000, "gl_ar_account_code": "1-1301"}]
    db.rahaza_journal_entries.docs.append({
        "id": "jeOld", "je_number": "JE-OLD", "source_module": "maklon_ar_invoice", "source_ref": "maklon_ar:iss",
        "status": "posted", "lines": [{"account_code": "1-1301", "debit": 1_000_000, "credit": 0, "account_type": "ASSET"},
                                      {"account_code": "4-1100", "debit": 0, "credit": 1_000_000, "account_type": "REVENUE"}]})
    _dispatch(db, "sj1", 1, "pi-s", 10)
    before = len(db.rahaza_coa_accounts.docs)
    pre = run(mig.run(db, apply=False))
    assert pre["accounts"]["rev_missing"] == 1 and pre["schedules"]["drafts"] == 1
    assert pre["reclass"]["revenue_outside_4_1500"] == 1_000_000 and pre["reclass"]["open_ar_outside_1_1305"] == 300000
    assert len(db.rahaza_coa_accounts.docs) == before and not jes                  # pratinjau: tanpa tulis
    out = run(mig.run(db, apply=True))
    assert out["accounts"]["created"] == 2 and out["schedules"]["converted"] == 1
    assert next(a for a in db.rahaza_ar_invoices.docs if a["id"] == "old")["schedule_mode"] == "v2"
    assert [j["source_module"] for j in jes] == ["maklon_revenue"] and out["reclass"]["journals_posted"] == 0
    rc = run(mig.run(db, apply=True, reclass=True))["reclass"]
    assert rc["journals_posted"] == 1
    assert _je_lines(jes[-1]) == {("4-1100", "D"): 1_000_000.0, ("4-1500-KOH-01", "C"): 1_000_000.0,
                                  ("1-1305-KOH-01", "D"): 300000.0, ("1-1301", "C"): 300000.0}
    assert next(a for a in db.rahaza_ar_invoices.docs if a["id"] == "iss")["gl_ar_account_code"] == "1-1305-KOH-01"
    again = run(mig.run(db, apply=True, reclass=True))
    assert again["reclass"]["already_done"] == 1 and len([j for j in jes if j["source_module"] == "maklon_reclass"]) == 1
    assert mig.reclass_lines({"4-1500-X": 5}, {"1-1305-X": 5}, "4-1500-X", "1-1305-X") == []


def test_umur_piutang_menampilkan_terjadwal(env):
    db = env["db"]
    _confirm(db)
    import routes.rahaza_ar_360 as ar360
    s = run(ar360._scheduled_by_customer(db))
    assert s["cl1"]["scheduled"] == 2_000_000 and s["cl1"]["count"] == 1
    assert _ar(db)["status"] not in ar360.OPEN_AR_STATUSES                       # bukan saldo umur piutang


def test_daftar_piutang_keuangan_tidak_menerbitkan_ulang_dan_bayar_lewat_mesin_sama(env, monkeypatch):
    db = env["db"]
    import routes.rahaza_finance as rf
    _confirm(db)
    ar = _ar(db)

    async def fin(_req):
        return dict(FIN)
    monkeypatch.setattr(rf, "_require_fin", fin)
    monkeypatch.setattr(rf, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(rf.send_ar_invoice(ar["id"], FakeRequest({})))
    assert "dicatat otomatis" in e.value.detail
    out = run(rf.record_ar_payment(ar["id"], FakeRequest({"amount": 300000, "account_id": "kas1"})))
    assert out["amount_paid"] == 300000 and out["advance_balance"] == 300000          # sebelum kirim = uang muka
    assert db.rahaza_ar_payments.docs[0]["advance_portion"] == 300000


def test_faktur_cetak_per_kiriman_dan_per_po(env):
    db = env["db"]
    _confirm(db)
    _dispatch(db, "sj1", 1, "pi-s", 20)
    _dispatch(db, "sj2", 1, "pi-m", 10, day="2026-11-06")
    run(bridge.sync_po_to_maklon_finance(db, "po1", USER))
    run(ml.record_client_payment(db, _ar(db)["id"], amount=450000, cash_account_id="kas1", payment_date=None, user=FIN))
    ar = _ar(db)
    groups = billing.dispatch_groups(ar)
    assert [(g["shipment_id"], g["total"], g["paid"], g["balance"]) for g in groups] == [
        ("sj1", 400000.0, 400000.0, 0.0), ("sj2", 200000.0, 50000.0, 150000.0)]
    inv = billing.invoice_doc_for(ar, "sj2", 1)
    assert inv["invoice_number"].endswith("/2") and inv["total_amount"] == 200000 and inv["lines"][0]["qty"] == 10
    whole = billing.invoice_doc_for(ar)
    assert whole["total_amount"] == 2_000_000 and whole["balance_amount"] == 1_550_000
