"""Uji unit HERMETIK — sisa kirim CMT→DA dari PENERIMAAN (17 Nov 2026, layar owner Kirim ke DA JOB-0018:
"Diklaim ke DA 0 · Diterima DA 0 · Sisa kirim 0", isian 284 ditolak browser "Value must be 0.").

Skenario nyata yang diuji:
  · JOB-0018: 284 pcs diterima LANGSUNG di Terima & QC (tanpa deklarasi) ⇒ diterima DA 284, sisa kirim 0;
  · JOB-0008/0009: draf penerimaan dari deklarasi DIBATALKAN ⇒ tidak terhitung diterima, deklarasinya dilepas,
    sisa kirim terbuka lagi;
  · draf penerimaan yang belum selesai QC = sedang QC (tidak bisa dideklarasi ulang);
  · selisih kirim (klaim 100, sampai 90) membuka sisa kirim 10 (aturan owner);
  · server menolak deklarasi yang melebihi sisa kirim, dengan pesan Indonesia yang menyebut nomor penerimaan.

Jalankan:  cd backend && python -m pytest tests/unit/test_kirim_ke_da_sisa.py -q
"""
import asyncio
import os
import sys

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
from _fake_mongo import FakeRequest  # noqa: E402
from core import dispatch_capacity as dcap  # noqa: E402

SA = {"id": "u-sa", "name": "Super Uji", "email": "sa@x", "role": "superadmin"}


def run(coro):
    return asyncio.run(coro)


def _db(produced=284, ordered=287):
    db = fm.FakeDB()
    db.production_pos.docs.append({"id": "po1", "po_number": "PO-MKL-UJI", "business_type": "maklon"})
    db.po_items.docs.append({"id": "poi1", "po_id": "po1", "qty": ordered, "sku": "8425", "size": "XL"})
    db.production_jobs.docs.append({"id": "job1", "job_number": "JOB-UJI", "po_id": "po1", "vendor_id": "v1"})
    db.production_job_items.docs.append({"id": "ji1", "job_id": "job1", "po_item_id": "poi1", "produced_qty": produced,
                                         "available_qty": ordered, "sku": "8425", "size": "XL"})
    return db


def _rcv(db, rid, code, status, actual=None, reject=0, claim=None, ship=None, seq=1):
    db.cmt_receipts.docs.append({"id": rid, "receipt_code": code, "status": status, "po_id": "po1",
                                 "related_shipment_id": ship, "related_dispatch_seq": seq})
    db.cmt_receipt_lines.docs.append({"id": f"l-{rid}", "receipt_id": rid, "po_item_id": "poi1", "qty_actual": actual,
                                      "reject_qty": reject, "qty_claimed_by_cmt": claim})


def _deklarasi(db, sid="sj1", qty=52, seq=1):
    db.buyer_shipments.docs.append({"id": sid, "shipment_number": "SJ-CMT-UJI", "receiver_type": "da", "job_id": "job1"})
    db.buyer_shipment_items.docs.append({"id": f"bi-{sid}-{seq}", "shipment_id": sid, "dispatch_seq": seq, "po_item_id": "poi1",
                                         "job_id": "job1", "ordered_qty": 287, "qty_shipped": qty})


def test_penerimaan_langsung_di_terima_qc_terbaca_dan_sisa_kirim_nol():
    db = _db()
    _rcv(db, "r18", "CMT-RCV-00018", "completed_qc", actual=284)
    r = run(dcap.cmt_send_room(db, ["poi1"]))["poi1"]
    assert (r["produced"], r["received"], r["in_qc"], r["room"]) == (284, 284, 0, 0)
    assert r["claimed"] == 284 and r["receipt_codes"] == ["CMT-RCV-00018"]


def test_penerimaan_batal_tidak_terhitung_dan_deklarasinya_dilepas():
    db = _db(produced=52, ordered=52)
    _deklarasi(db, qty=52)
    _rcv(db, "r6", "CMT-RCV-00006", "cancelled", claim=52, ship="sj1")
    r = run(dcap.cmt_send_room(db, ["poi1"]))["poi1"]
    assert (r["received"], r["in_qc"], r["room"]) == (0, 0, 52)       # barang belum sampai ⇒ boleh dikirim
    n = run(dcap.release_declaration_of_receipt(db, db.cmt_receipts.docs[0], "diganti sesuai sheet"))
    it = db.buyer_shipment_items.docs[0]
    assert n == 1 and it["receipt_cancelled"] and it["receipt_cancelled_code"] == "CMT-RCV-00006"
    assert dcap.shipment_progress([it])["total_shipped"] == 0
    assert run(dcap.release_declaration_of_receipt(db, db.cmt_receipts.docs[0])) == 0   # idempoten
    import routes.buyer_shipment as bs
    assert run(bs._declared_main_by_item(db, ["poi1"])) == {}           # batas lebih-pesan tidak menghitungnya


def test_draf_penerimaan_dihitung_sedang_qc_bukan_sisa_kirim():
    db = _db(produced=30, ordered=40)
    _rcv(db, "r9", "CMT-RCV-00009", "on_qc", claim=30)
    r = run(dcap.cmt_send_room(db, ["poi1"]))["poi1"]
    assert (r["received"], r["in_qc"], r["claimed"], r["room"]) == (0, 30, 30, 0)


def test_selisih_kirim_membuka_sisa_kirim_lagi():
    db = _db(produced=100, ordered=100)
    _rcv(db, "r1", "CMT-RCV-1", "completed_qc", actual=88, reject=2, claim=100)
    r = run(dcap.cmt_send_room(db, ["poi1"]))["poi1"]
    assert (r["claimed"], r["received"], r["room"]) == (100, 90, 10)


def test_pagar_server_menolak_deklarasi_barang_yang_sudah_diterima():
    import routes.buyer_shipment as bs
    db = _db()
    _rcv(db, "r18", "CMT-RCV-00018", "completed_qc", actual=284)
    items = [{"po_item_id": "poi1", "sku": "8425", "size": "XL", "qty_shipped": 284}]
    with pytest.raises(HTTPException) as e:
        run(bs._guard_cmt_send_room(db, items, "job1"))
    assert e.value.status_code == 400
    assert "melebihi sisa kirim 0 pcs" in e.value.detail and "CMT-RCV-00018" in e.value.detail
    db.production_job_items.docs[0]["produced_qty"] = 287                 # 3 pcs baru selesai dijahit
    run(bs._guard_cmt_send_room(db, [{**items[0], "qty_shipped": 3}], "job1"))
    db.production_jobs.docs.append({"id": "jr", "shipment_type": "REWORK", "vendor_id": "v1"})
    run(bs._guard_cmt_send_room(db, items, "jr"))                           # kiriman balik rework: alur sendiri


def test_progres_nol_pesannya_minta_isi_progres():
    import routes.buyer_shipment as bs
    db = _db(produced=0)
    with pytest.raises(HTTPException) as e:
        run(bs._guard_cmt_send_room(db, [{"po_item_id": "poi1", "sku": "8425", "qty_shipped": 5}], "job1"))
    assert "isi progres jahit dulu" in e.value.detail


def test_batalkan_penerimaan_melepas_deklarasinya(monkeypatch):
    import routes.dewi_cmt_packing as dcp
    import routes.shared as shared
    db = _db(produced=52, ordered=52)
    _deklarasi(db, qty=52)
    _rcv(db, "r6", "CMT-RCV-00006", "on_qc", claim=52, ship="sj1")
    monkeypatch.setattr(dcp, "get_db", lambda: db)

    async def ok(*_a, **_k):
        return dict(SA)
    monkeypatch.setattr(shared, "require_perm", ok)
    run(dcp.reject_receipt("r6", FakeRequest({"reason": "barang belum disetor"})))
    assert db.cmt_receipts.docs[0]["status"] == "cancelled"
    it = db.buyer_shipment_items.docs[0]
    assert it["receipt_cancelled"] and it["receipt_cancelled_reason"] == "barang belum disetor"
    assert run(dcap.cmt_send_room(db, ["poi1"]))["poi1"]["room"] == 52


def test_migrasi_menandai_pembatalan_lama():
    import importlib.util
    path = os.path.join(BACKEND, "scripts", "migrations", "2026_11_17_deklarasi_penerimaan_batal.py")
    spec = importlib.util.spec_from_file_location("mig_deklarasi_batal", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    db = _db(produced=52, ordered=52)
    _deklarasi(db, qty=52)
    _rcv(db, "r6", "CMT-RCV-00006", "cancelled", claim=52, ship="sj1")
    assert run(mig.run(db, apply=False)) == {"penerimaan": 1, "baris": 1}
    assert not db.buyer_shipment_items.docs[0].get("receipt_cancelled")
    run(mig.run(db, apply=True))
    assert db.buyer_shipment_items.docs[0]["receipt_cancelled"]
    assert run(mig.run(db, apply=False)) == {"penerimaan": 0, "baris": 0}
