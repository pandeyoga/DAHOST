"""Keuangan › Hutang/Piutang: posisi per CMT & per klien, bayar/terima GABUNGAN, tagihan klien gabungan (16 Nov 2026).

Owner: "berapa pencairannya" — yang boleh DIBAYAR ke CMT = setoran lolos QC; yang boleh DITAGIH ke klien = yang sudah
dikirim; nilai PO = komitmen (tanpa jurnal baru). Klien membayar gabungan; satu pembayaran ke satu CMT boleh menutup
beberapa tagihannya, tetapi tidak pernah lintas CMT.

Yang dikunci (hermetik, FakeDB + jurnal palsu yang memeriksa keseimbangan dari uji Tahap 2 maklon):
  * pembagian terlama dulu + pemeriksaan pembagian (murni);
  * bayar CMT gabungan: terlama dulu, satu nomor bukti dicap ke tiap pembayaran & mutasi kas, ditolak bila melebihi
    boleh dibayar / tagihan CMT lain / CV lain / jumlah ≠ pembagian, gagal di tengah digulung balik, kunci dilepas;
  * posisi CMT: komitmen (jadwal) vs setor lolos QC vs dibayar vs ditahan vs boleh dibayar, PO internal tertutup ikut;
  * tagihan klien: batas = dikirim belum ditagih, lintas PO satu klien, batal hanya bila belum dibayar;
  * terima klien gabungan: terlama dulu, batas = dikirim − dibayar (bukan nilai PO), kelebihan → uang muka;
  * izin: bayar gabungan = centang Pembayaran & Pencairan › Setujui (sama dengan Bayar), tombol layar ikut centang;
  * koleksi, nomor dokumen, router terdaftar.
"""
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeRequest  # noqa: E402
import routes.dewi_maklon_finance as dmf  # noqa: E402
import routes.keuangan_gabungan as kg  # noqa: E402
import routes.production_maklon_bridge as bridge  # noqa: E402
import routes.production_pos as ppos  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
from core import alokasi_bayar as ab  # noqa: E402
from core import maklon_ledger as ml  # noqa: E402
from core import posisi_cmt as pc  # noqa: E402
from core import tagihan_klien as tk  # noqa: E402
from data.module_catalog import request_key  # noqa: E402
import test_tahap2_maklon as t2  # noqa: E402

env = t2.env
run, USER, FIN = t2.run, t2.USER, t2.FIN
_confirm, _ar = t2._confirm, t2._ar
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def genv(env, monkeypatch):
    db = env["db"]
    db.vendor_partners.docs.append({"id": "v2", "name": "CMT B"})
    db.rahaza_cash_accounts.docs.append({"id": "kasda", "name": "BRI DA", "gl_account_code": "1-1202", "active": True,
                                         "entity": "DA"})
    db.rahaza_coa_accounts.docs.append({"code": "1-1202", "name": "Bank BRI", "type": "ASSET", "is_group": False,
                                        "active": True})
    seq = {}

    async def nomor(_db, key):
        seq[key] = seq.get(key, 0) + 1
        return f"{key.split('.')[-1].upper()}-{seq[key]:04d}"

    pays, voids = [], []

    async def ap_pay(_db, inv, amount, acc_id, date, user, movement_id=None, **_k):
        pays.append((inv["id"], amount, movement_id))
        return {"ok": True, "je_id": f"jp{len(pays)}", "je_number": f"JE-P{len(pays)}"}

    async def void_je(_db, module, ref, user, reason=""):
        voids.append((module, ref))
        return {"ok": True, "voided": True, "je_number": f"JE-V{len(voids)}"}

    monkeypatch.setattr(ab, "terbitkan_nomor", nomor)
    monkeypatch.setattr(rp, "post_ap_payment", ap_pay)
    monkeypatch.setattr(rp, "_void_je_by_source", void_je)
    return {**env, "pays": pays, "voids": voids}


def _bill(bid, net, *, vendor="v1", paid=0, entity="SMU", day="2026-11-01", po="po1", **kw):
    return {"id": bid, "payment_code": f"PAY-CMT-{bid}", "po_id": po, "po_number": "PO-MKL-1", "vendor_id": vendor,
            "cmt_name": "CMT A" if vendor == "v1" else "CMT B", "subtotal": net, "net_amount": net,
            "total_amount": net, "paid_amount": paid, "status": "posted", "gl_je_id": "x",
            "gl_ap_account_code": "2-1110", "entity": entity, "invoice_date": day, "total_pcs": 10, **kw}


# ══════════════════════════════════════════════════════════════════════════════
# Pembagian (murni)
# ══════════════════════════════════════════════════════════════════════════════
def test_alokasi_terlama_dulu_dan_pemeriksaan_pembagian():
    baris = [{"id": "c", "batas": 400, "urut": "2026-11-05", "nomor": "C"},
             {"id": "a", "batas": 300, "urut": "2026-11-01", "nomor": "A"},
             {"id": "b", "batas": 500, "urut": "2026-11-03", "nomor": "B"},
             {"id": "z", "batas": 0, "urut": "2026-10-01", "nomor": "Z"}]
    assert ab.alokasi_terlama(600, baris) == ([{"id": "a", "jumlah": 300.0}, {"id": "b", "jumlah": 300.0}], 0.0)
    assert ab.alokasi_terlama(1500, baris) == ([{"id": "a", "jumlah": 300.0}, {"id": "b", "jumlah": 500.0},
                                                {"id": "c", "jumlah": 400.0}], 300.0)
    batas = {"a": 300, "b": 500}
    assert ab.periksa_alokasi([{"id": "b", "jumlah": 200}, {"id": "a", "jumlah": 0}], batas) == [{"id": "b", "jumlah": 200.0}]
    for salah, pesan in (([{"id": "x", "jumlah": 10}], "tidak termasuk"),
                         ([{"id": "a", "jumlah": 10}, {"id": "a", "jumlah": 5}], "dua kali"),
                         ([{"id": "a", "jumlah": 301}], "melebihi batasnya"),
                         ([], "minimal satu")):
        with pytest.raises(ValueError) as e:
            ab.periksa_alokasi(salah, batas)
        assert pesan in str(e.value)


# ══════════════════════════════════════════════════════════════════════════════
# Bayar CMT gabungan
# ══════════════════════════════════════════════════════════════════════════════
def test_bayar_cmt_gabungan_terlama_dulu_satu_bukti(genv):
    db = genv["db"]
    _confirm(db)
    db.dewi_cmt_payments.docs = [_bill("b3", 400000, day="2026-11-05"), _bill("b1", 300000, day="2026-11-01"),
                                 _bill("b2", 500000, day="2026-11-03")]
    out = run(pc.bayar_gabungan(db, vendor_id="v1", amount=600000, cash_account_id="kas1", payment_date="2026-11-16",
                                alokasi=None, user=FIN))
    assert out["status"] == "tercatat" and out["bukti_number"] == "BUKTI_CMT-0001" and out["amount"] == 600000
    assert [(a["payment_id"], a["jumlah"]) for a in out["alokasi"]] == [("b1", 300000.0), ("b2", 300000.0)]
    bills = {b["id"]: b for b in db.dewi_cmt_payments.docs}
    assert (bills["b1"]["status"], bills["b2"]["status"], bills["b3"]["paid_amount"]) == ("paid", "partial_paid", 0)
    assert all(b.get("pay_lock") is None for b in bills.values())                    # semua kunci dilepas
    disb = db.dewi_cmt_disbursements.docs
    assert len(disb) == 2 and {d["bukti_number"] for d in disb} == {"BUKTI_CMT-0001"}
    assert {d["batch_id"] for d in disb} == {out["id"]}
    assert {m["bukti_number"] for m in db.rahaza_cash_movements.docs} == {"BUKTI_CMT-0001"}
    assert len(genv["pays"]) == 2                                                    # jurnal bayar per tagihan
    saved = next(d for d in db[ab.COLL].docs if d["id"] == out["id"])
    assert saved["jenis"] == ab.JENIS_BAYAR_CMT and saved["pihak_id"] == "v1" and saved["entity"] == "SMU"
    assert [d["bukti_number"] for d in run(pc.daftar_bukti(db, ab.JENIS_BAYAR_CMT, "v1"))] == ["BUKTI_CMT-0001"]


def test_bayar_cmt_gabungan_pembagian_diubah_dan_ditolak(genv):
    db = genv["db"]
    _confirm(db)
    db.dewi_cmt_payments.docs = [
        _bill("b1", 300000, day="2026-11-01"), _bill("b2", 500000, day="2026-11-03"),
        _bill("bx", 200000, vendor="v2"), _bill("bda", 100000, entity="DA", po="po-int"),
        _bill("bt", 600000, paid=100000, variance_flagged=True, needs_finance_review=True, overbilled_amount=120000)]

    def bayar(amount, alokasi, akun="kas1"):
        return run(pc.bayar_gabungan(db, vendor_id="v1", amount=amount, cash_account_id=akun, payment_date=None,
                                     alokasi=alokasi, user=FIN))
    kasus = [
        (2_000_000, None, "melebihi yang boleh dibayar"),                                 # > Σ boleh dibayar CMT ini
        (400000, [{"id": "b1", "jumlah": 400000}], "melebihi batasnya"),                 # > boleh dibayar tagihan
        (200000, [{"id": "bx", "jumlah": 200000}], "satu pembayaran hanya untuk satu CMT"),  # tagihan CMT lain
        (100000, [{"id": "bda", "jumlah": 100000}], "dibukukan di CV Dewi Aditya"),      # CV tagihan ≠ CV rekening
        (500000, [{"id": "b1", "jumlah": 300000}], "tidak sama dengan jumlah pembagian"),
        (390000, [{"id": "bt", "jumlah": 390000}], "melebihi batasnya"),                 # tertahan selisih (380 rb)
    ]
    for amount, alokasi, pesan in kasus:
        with pytest.raises(ValueError) as e:
            bayar(amount, alokasi)
        assert pesan in str(e.value), (pesan, str(e.value))
    assert db.dewi_cmt_disbursements.docs == [] and db.rahaza_cash_movements.docs == []
    # pembagian diubah Keuangan: tagihan terbaru dulu dibayar sebagian
    out = bayar(250000, [{"id": "b2", "jumlah": 200000}, {"id": "b1", "jumlah": 50000}])
    assert [(a["payment_id"], a["jumlah"]) for a in out["alokasi"]] == [("b2", 200000.0), ("b1", 50000.0)]
    # rekening DA hanya membayar tagihan DA
    out = bayar(100000, None, akun="kasda")
    assert [a["payment_id"] for a in out["alokasi"]] == ["bda"] and out["entity"] == "DA"


def test_bayar_cmt_gabungan_gagal_di_tengah_digulung_balik(genv, monkeypatch):
    db = genv["db"]
    _confirm(db)
    db.dewi_cmt_payments.docs = [_bill("b1", 300000, day="2026-11-01"), _bill("b2", 500000, day="2026-11-03")]
    asli = dmf.pay_cmt_bill_locked

    async def kadang_gagal(_db, pid, payload, user, batch=None):
        if pid == "b2":
            raise HTTPException(400, "periode buku sudah ditutup")
        return await asli(_db, pid, payload, user, batch=batch)
    monkeypatch.setattr(dmf, "pay_cmt_bill_locked", kadang_gagal)
    with pytest.raises(ValueError) as e:
        run(pc.bayar_gabungan(db, vendor_id="v1", amount=800000, cash_account_id="kas1", payment_date=None,
                              alokasi=None, user=FIN))
    assert "periode buku sudah ditutup" in str(e.value) and "dibatalkan kembali" in str(e.value)
    b1 = next(b for b in db.dewi_cmt_payments.docs if b["id"] == "b1")
    assert b1["paid_amount"] == 0 and b1.get("pay_lock") is None
    assert [d["status"] for d in db.dewi_cmt_disbursements.docs] == ["voided"] and db.rahaza_cash_movements.docs == []
    assert len(genv["voids"]) == 1
    assert next(d for d in db[ab.COLL].docs)["status"] == "gagal"
    assert run(pc.daftar_bukti(db, ab.JENIS_BAYAR_CMT, "v1")) == []                # bukti gagal tidak tampil


def test_posisi_cmt_komitmen_setor_dibayar_ditahan_boleh(genv):
    db = genv["db"]
    _confirm(db)                                                   # jadwal: 100 pcs × 12.000 = 1,2 jt ke v1
    db.dewi_cmt_payments.docs = [_bill("bt", 600000, paid=100000, variance_flagged=True, needs_finance_review=True,
                                       overbilled_amount=120000)]
    # PO internal yang sudah DITUTUP tetapi tagihannya masih terbuka tetap ikut posisi (buku DA)
    db.production_pos.docs.append({"id": "po-int", "po_number": "PO-INT-9", "business_type": "internal",
                                   "status": "Closed", "vendor_id": "v1"})
    db.po_items.docs.append({"id": "pi-int", "po_id": "po-int", "qty": 10, "sku": "INT", "cmt_price_snapshot": 10000})
    db.dewi_cmt_payments.docs.append(_bill("bint", 100000, entity="DA", po="po-int", day="2026-11-02"))
    out = run(pc.posisi_cmt(db))
    v1 = next(v for v in out["vendors"] if v["vendor_id"] == "v1")
    assert v1["vendor_name"] == "CMT A" and {r["po_number"] for r in v1["pos"]} == {"PO-MKL-1", "PO-INT-9"}
    mkl = next(r for r in v1["pos"] if r["po_id"] == "po1")
    assert (mkl["komitmen"], mkl["setor_qc"], mkl["dibayar"], mkl["ditahan"], mkl["boleh_dibayar"], mkl["belum_setor"]) \
        == (1_200_000, 600000, 100000, 120000, 380000, 600000)
    assert mkl["entity"] == "SMU" and mkl["jenis"] == "jadwal"
    assert v1["boleh_dibayar"] == 480000 and [t["id"] for t in v1["tagihan"]] == ["bt", "bint"]
    smu = run(pc.posisi_cmt(db, entity="SMU"))
    assert [r["po_id"] for r in smu["vendors"][0]["pos"]] == ["po1"] and smu["totals"]["boleh_dibayar"] == 380000
    assert run(pc.posisi_cmt(db, vendor_id="v2"))["vendors"] == []


# ══════════════════════════════════════════════════════════════════════════════
# Klien maklon: tagihan gabungan & terima gabungan
# ══════════════════════════════════════════════════════════════════════════════
def _kirim(db, po_id, sid, item, qty, day):
    if not any(s["id"] == sid for s in db.buyer_shipments.docs):
        db.buyer_shipments.docs.append({"id": sid, "shipment_number": f"SJ-{sid}", "receiver_type": "buyer",
                                        "po_id": po_id})
    db.buyer_shipment_items.docs.append({"id": f"{sid}-{item}", "shipment_id": sid, "dispatch_seq": 1, "po_id": po_id,
                                         "po_item_id": item, "sku": item, "qty_shipped": qty, "dispatch_date": day,
                                         "created_at": day})
    run(bridge.sync_po_to_maklon_finance(db, po_id, USER))


def _dua_po(db):
    """PO1 2 jt (kirim 30 pcs = 600 rb, 5 Nov) + PO3 400 rb (kirim penuh = 400 rb, 7 Nov) — klien yang sama."""
    _confirm(db)
    db.production_pos.docs.append({"id": "po3", "po_number": "PO-MKL-3", "business_type": "maklon", "status": "Draft",
                                   "buyer_id": "cl1", "customer_name": "PT Klien Satu", "vendor_id": "v1",
                                   "vendor_name": "CMT A"})
    db.po_items.docs.append({"id": "pi3", "po_id": "po3", "qty": 20, "size": "L", "sku": "KLN-L",
                             "selling_price_snapshot": 20000, "cmt_price_snapshot": 12000,
                             "created_at": "2026-11-02T00:00:00"})
    run(ppos.transition_po_status("po3", FakeRequest({"status": "Confirmed"})))
    _kirim(db, "po1", "sj1", "pi-s", 30, "2026-11-05")
    _kirim(db, "po3", "sj3", "pi3", 20, "2026-11-07")
    ar1 = _ar(db)
    ar3 = next(a for a in db.rahaza_ar_invoices.docs if a.get("linked_maklon_po_id") == "po3")
    return ar1, ar3


def test_tagihan_klien_lintas_po_batas_kiriman_belum_ditagih(genv):
    db, jes = genv["db"], genv["jes"]
    ar1, ar3 = _dua_po(db)
    c = run(tk.posisi_klien(db))["clients"][0]
    assert (c["komitmen"], c["dikirim"], c["boleh_ditagih"], c["sisa_piutang"]) == (2_400_000, 1_000_000, 1_000_000, 1_000_000)
    keys = [k["key"] for k in c["kiriman"]]
    assert len(keys) == 2 and keys[0].startswith(ar1["id"]) and keys[1].startswith(ar3["id"])
    n_jurnal = len(jes)
    t = run(tk.buat_tagihan(db, client_id="cl1", keys=keys, bill_date="2026-11-10", user=FIN))
    assert t["bill_number"] == "BILL_NUMBER-0001" and t["total"] == 1_000_000 and t["po_numbers"] == ["PO-MKL-1", "PO-MKL-3"]
    assert t["due_date"] == "2026-12-10" and len(jes) == n_jurnal                     # dokumen saja, tanpa jurnal
    c = run(tk.posisi_klien(db))["clients"][0]
    assert c["boleh_ditagih"] == 0 and c["ditagih"] == 1_000_000 and c["kiriman"] == []
    assert c["tagihan"][0]["status_bayar"] == "belum_dibayar" and c["tagihan"][0]["sisa"] == 1_000_000
    with pytest.raises(ValueError) as e:                                              # tidak bisa menagih dua kali
        run(tk.buat_tagihan(db, client_id="cl1", keys=keys[:1], bill_date=None, user=FIN))
    assert "sudah ditagih penuh" in str(e.value)
    # kiriman baru PO1 → hanya kiriman baru yang boleh ditagih
    _kirim(db, "po1", "sj4", "pi-m", 10, "2026-11-12")
    c = run(tk.posisi_klien(db))["clients"][0]
    assert c["boleh_ditagih"] == 200000 and [k["shipment_number"] for k in c["kiriman"]] == ["SJ-sj4"]
    # kiriman klien lain ditolak
    db.rahaza_ar_invoices.docs.append({"id": "ar-x", "customer_id": "cl2", "customer_name": "PT Lain",
                                       "source_module": "maklon_po", "schedule_mode": "v2", "status": "issued"})
    with pytest.raises(ValueError) as e:
        run(tk.buat_tagihan(db, client_id="cl1", keys=["ar-x|sjx|1"], bill_date=None, user=FIN))
    assert "milik klien lain" in str(e.value)
    assert db.dewi_maklon_clients.docs[0].get("tagihan_lock") is None


def test_batal_tagihan_hanya_bila_belum_dibayar(genv):
    db = genv["db"]
    ar1, _ = _dua_po(db)
    keys = [k["key"] for k in run(tk.posisi_klien(db))["clients"][0]["kiriman"]]
    t = run(tk.buat_tagihan(db, client_id="cl1", keys=keys, bill_date="2026-11-10", user=FIN))
    out = run(tk.batal_tagihan(db, t["id"], reason="salah pilih kiriman", user=FIN))
    assert out["status"] == "dibatalkan"
    assert run(tk.posisi_klien(db))["clients"][0]["boleh_ditagih"] == 1_000_000      # bisa ditagih ulang
    t2_ = run(tk.buat_tagihan(db, client_id="cl1", keys=keys, bill_date="2026-11-11", user=FIN))
    run(tk.terima_gabungan(db, client_id="cl1", amount=600000, cash_account_id="kas1", payment_date=None,
                           alokasi=[{"id": ar1["id"], "jumlah": 600000}], user=FIN))
    rinci = run(tk.rincian_tagihan(db, t2_["id"]))
    assert (rinci["status_bayar"], rinci["dibayar"], rinci["sisa"]) == ("sebagian", 600000, 400000)
    with pytest.raises(ValueError) as e:
        run(tk.batal_tagihan(db, t2_["id"], reason="coba batal", user=FIN))
    assert "sudah dibayar" in str(e.value)


def test_terima_gabungan_terlama_dulu_kelebihan_jadi_uang_muka(genv):
    db = genv["db"]
    ar1, ar3 = _dua_po(db)
    out = run(tk.terima_gabungan(db, client_id="cl1", amount=1_200_000, cash_account_id="kas1",
                                 payment_date="2026-11-16", alokasi=None, user=FIN, reference_no="TRF-1"))
    assert out["status"] == "tercatat" and out["bukti_number"] == "BUKTI_KLIEN-0001"
    assert [(a["po_number"], a["jumlah"], a["ke_piutang"], a["ke_uang_muka"]) for a in out["alokasi"]] == [
        ("PO-MKL-1", 800000.0, 600000.0, 200000.0), ("PO-MKL-3", 400000.0, 400000.0, 0.0)]
    assert (out["ke_piutang"], out["ke_uang_muka"]) == (1_000_000, 200000)
    pays = [p for p in db.rahaza_ar_payments.docs if p.get("batch_id") == out["id"]]
    assert len(pays) == 2 and {p["bukti_number"] for p in pays} == {"BUKTI_KLIEN-0001"}
    assert {m.get("bukti_number") for m in db.rahaza_cash_movements.docs} == {"BUKTI_KLIEN-0001"}
    a1, a3 = _ar(db), next(a for a in db.rahaza_ar_invoices.docs if a["id"] == ar3["id"])
    assert (a1["amount_due"], a1["advance_balance"], a3["amount_due"], a3["status"]) == (0.0, 200000.0, 0.0, "paid")
    c = run(tk.posisi_klien(db))["clients"][0]
    assert (c["sisa_piutang"], c["uang_muka"]) == (0, 200000)
    assert db.dewi_maklon_clients.docs[0].get("pay_lock") is None


def test_terima_gabungan_batas_dikirim_bukan_nilai_po(genv):
    db = genv["db"]
    ar1, ar3 = _dua_po(db)
    db.rahaza_ar_invoices.docs.append({"id": "ar-x", "customer_id": "cl2", "customer_name": "PT Lain",
                                       "linked_maklon_po_number": "PO-X", "source_module": "maklon_po",
                                       "schedule_mode": "v2", "status": "issued"})

    def terima(amount, alokasi, akun="kas1"):
        return run(tk.terima_gabungan(db, client_id="cl1", amount=amount, cash_account_id=akun, payment_date=None,
                                      alokasi=alokasi, user=FIN))
    for amount, alokasi, akun, pesan in (
            (700000, [{"id": ar1["id"], "jumlah": 700000}], "kas1", "melebihi batasnya"),   # PO 2 jt, dikirim 600 rb
            (100000, [{"id": "ar-x", "jumlah": 100000}], "kas1", "milik klien lain"),
            (100000, None, "kasda", "rekening CV Sukma"),
            (500000, [{"id": ar1["id"], "jumlah": 600000}], "kas1", "melebihi jumlah diterima")):
        with pytest.raises(ValueError) as e:
            terima(amount, alokasi, akun)
        assert pesan in str(e.value), (pesan, str(e.value))
    assert db.rahaza_ar_payments.docs == []
    # kelebihan yang tidak muat di PO mana pun (PO3 sudah terkirim penuh; PO1 sisa nilai 2 jt) ditolak
    with pytest.raises(ValueError) as e:
        terima(3_500_000, None)
    assert "tidak bisa dicatat sebagai uang muka" in str(e.value)
    # pembagian diubah: PO terbaru dulu
    out = terima(400000, [{"id": ar3["id"], "jumlah": 400000}])
    assert [(a["po_number"], a["ke_piutang"]) for a in out["alokasi"]] == [("PO-MKL-3", 400000.0)]


def test_status_bayar_tagihan_dihitung_dari_pembayaran_po_murni():
    kiriman = {"A|s1|1": {"dibayar": 500}, "B|s2|1": {"dibayar": 0}}
    tag = [{"id": "t2", "bill_date": "2026-11-02", "bill_number": "T2", "status": "aktif",
            "lines": [{"key": "A|s1|1", "amount": 300}], "total": 300},
           {"id": "t1", "bill_date": "2026-11-01", "bill_number": "T1", "status": "aktif",
            "lines": [{"key": "A|s1|1", "amount": 400}, {"key": "B|s2|1", "amount": 100}], "total": 500},
           {"id": "tb", "bill_date": "2026-10-01", "bill_number": "TB", "status": "dibatalkan",
            "lines": [{"key": "A|s1|1", "amount": 999}], "total": 999}]
    bayar = tk.bayar_per_baris(kiriman, tag)
    assert bayar == {("t1", "A|s1|1"): 400, ("t1", "B|s2|1"): 0, ("t2", "A|s1|1"): 100}
    assert tk.status_bayar_tagihan(tag[1], bayar) == {"dibayar": 400.0, "sisa": 100.0, "status_bayar": "sebagian"}
    assert tk.status_bayar_tagihan(tag[0], bayar)["status_bayar"] == "sebagian"
    assert tk.status_bayar_tagihan(tag[2], bayar)["status_bayar"] == "dibatalkan"
    assert tk.tertagih_per_kiriman(tag) == {"A|s1|1": 700.0, "B|s2|1": 100.0}
    # boleh ditagih = kiriman − sudah ditagih; kiriman yang LUNAS sebelum ditagih (uang muka / bayar per PO) tidak ditagih
    k = {"key": "K", "total": 100.0, "dibayar": 100.0}
    assert tk.boleh_tagih_kiriman(k, {}) == 0
    assert tk.boleh_tagih_kiriman({**k, "dibayar": 60.0}, {}) == 100.0           # dibayar sebagian → ditagih utuh
    assert tk.boleh_tagih_kiriman({**k, "dibayar": 0.0}, {"K": 40.0}) == 60.0


# ══════════════════════════════════════════════════════════════════════════════
# Izin, registri, layar
# ══════════════════════════════════════════════════════════════════════════════
class _Req:
    def __init__(self, headers=None):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}   # Starlette: nama header huruf kecil
        self.query_params = {}


def test_izin_bayar_gabungan_sama_dengan_bayar_tagihan(genv, monkeypatch):
    bayar = "mod.fin_pencairan.approve"
    assert request_key("POST", "/api/dewi/maklon/finance/cmt-bayar-gabungan") == bayar
    assert request_key("POST", "/api/dewi/maklon/finance/cmt-payments/c1/pay") == bayar
    assert request_key("GET", "/api/dewi/maklon/finance/cmt-posisi") == "mod.mak_billing.view"
    assert request_key("GET", "/api/dewi/maklon/finance/cmt-bayar-gabungan/b1/pdf") == "mod.mak_billing.export"
    for path in ("/api/dewi/maklon/finance/tagihan-klien", "/api/dewi/maklon/finance/tagihan-klien/t1/batal",
                 "/api/dewi/maklon/finance/klien-terima-gabungan"):
        assert request_key("POST", path) == "mod.mak_billing.create", path
    db = genv["db"]
    monkeypatch.setattr(kg, "get_db", lambda: db)
    staf = {"id": "s1", "name": "Staf", "role": "staf_keuangan", "_permissions": ["mod.fin_ap.view"],
            "_role_perms": ["mod.fin_ap.view"]}

    async def auth_staf(_r):
        return dict(staf)
    monkeypatch.setattr(kg, "require_auth", auth_staf)
    payload = kg.BayarCmtGabunganIn(vendor_id="v1", amount=1000, cash_account_id="kas1")
    with pytest.raises(HTTPException) as e:
        run(kg.cmt_bayar_gabungan(payload, _Req()))
    assert e.value.status_code == 403 and "Pembayaran & Pencairan Uang" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(kg.klien_terima_gabungan(kg.TerimaKlienGabunganIn(client_id="cl1", amount=1000, cash_account_id="kas1"),
                                     _Req()))
    assert e.value.status_code == 403
    staf["_permissions"] = staf["_role_perms"] = [bayar]
    with pytest.raises(HTTPException) as e:                      # lolos izin → aturan bisnis menjawab 400
        run(kg.cmt_bayar_gabungan(payload, _Req()))
    assert e.value.status_code == 400 and "boleh dibayar" in e.value.detail
    with pytest.raises(HTTPException) as e:                      # rekening CV lain dari pilihan CV layar
        run(kg.cmt_bayar_gabungan(payload, _Req({"X-CV": "DA"})))
    assert e.value.status_code == 400 and "rekening" in e.value.detail.lower()


def test_layar_tombol_mengikuti_centang_dan_alamat_layanan():
    fin = REPO / "frontend" / "src" / "components" / "erp" / "finance"
    cmt = (fin / "PosisiCmt.jsx").read_text(encoding="utf-8")
    klien = (fin / "PosisiKlien.jsx").read_text(encoding="utf-8")
    assert "punyaCentang(hasPerm, CENTANG_BAYAR)" in cmt and "'/api/dewi/maklon/finance/cmt-bayar-gabungan'" in cmt
    assert "'/api/dewi/maklon/finance/cmt-posisi'" in cmt
    keys = re.search(r"CENTANG_PIUTANG_KLIEN = \[([^\]]+)\]", klien).group(1)
    from routes.dewi_maklon_billing import _PAY_PERMS
    assert {k.strip(" '") for k in keys.split(",")} == set(_PAY_PERMS["create"])
    for alamat in ("'/api/dewi/maklon/finance/klien-posisi'", "'/api/dewi/maklon/finance/tagihan-klien'",
                   "'/api/dewi/maklon/finance/klien-terima-gabungan'"):
        assert alamat in klien, alamat
    for berkas, layar in (("HutangModule.jsx", "PosisiCmt"), ("PiutangModule.jsx", "PosisiKlien")):
        isi = (fin / berkas).read_text(encoding="utf-8")
        assert f"<{layar} " in isi and "<ViewToggle" in isi, berkas


def test_registri_koleksi_nomor_dan_router():
    from core.collection_registry import REGISTRY, kind_of
    from data.doc_number_registry import REGISTRY_BY_KEY as K
    from utils.counters import validate_format
    for coll in (tk.COLL, ab.COLL):
        assert coll in REGISTRY and kind_of(coll) == "transaksi"
    for key, head in ((tk.NOMOR_TAGIHAN, "TGK-"), (ab.NOMOR_BAYAR_CMT, "BKK-CMT-"), (ab.NOMOR_TERIMA_KLIEN, "BKM-KLN-")):
        e = K[key]
        assert e["auto_only"] and validate_format(e["default_format"], e.get("tokens")).startswith(head)
    assert (K[ab.NOMOR_BAYAR_CMT]["collection"], K[ab.NOMOR_BAYAR_CMT]["field"]) == (ab.COLL, "bukti_number")
    server = (REPO / "backend" / "server.py").read_text(encoding="utf-8")
    assert "from routes.keuangan_gabungan import router" in server
    # satu logika bayar & terima: pembayaran gabungan memanggil fungsi yang sama dengan pembayaran satu dokumen
    src_cmt = (REPO / "backend" / "core" / "posisi_cmt.py").read_text(encoding="utf-8")
    src_kln = (REPO / "backend" / "core" / "tagihan_klien.py").read_text(encoding="utf-8")
    assert "pay_cmt_bill_locked(" in src_cmt and "_create_posted_je" not in src_cmt
    assert "ml.record_client_payment(" in src_kln and "_create_posted_je" not in src_kln
    assert ml.dispatch_groups is __import__("routes.dewi_maklon_billing", fromlist=["x"]).dispatch_groups
