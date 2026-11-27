"""Hutang pemasok otomatis saat barang PO diterima (owner 27 Nov 2026: "perbaiki soal pengadaan").

Masalah sebelumnya: barang PO diterima gudang → buku besar mencatat "Hutang belum ditagih" (GRNI), tetapi di menu Hutang
pemasok itu hanya tampil "Belum difakturkan". Supaya bisa dibayar, staf Keuangan harus (1) membuat faktur dari penerimaan
di Rekonsiliasi PO lalu (2) menyetujuinya; tanpa staf Keuangan hutangnya tidak pernah muncul (kasus Alvino Tex 26 Nov).

Sekarang, begitu penerimaan barang dari PO dikonfirmasi gudang, sistem langsung:
  1. membuat tagihan pemasok dari penerimaan itu (fungsi RESMI `routes.rahaza_ap_from_gr`) — qty diterima × harga PO,
     PPN & termin dari PO, jatuh tempo = tanggal terima + termin;
  2. menyetujuinya: status `sent` + jurnal Dr Hutang belum ditagih / Cr Hutang pemasok (`post_ap_invoice`).
Tagihan langsung tampil di Hutang › Belum dibayar. Bila faktur pemasok ternyata berbeda (harga, PPN, ongkir), Keuangan
mengoreksinya lewat "Ubah faktur" (persetujuan perubahan faktur).

Tidak pernah menggagalkan penerimaan barang: galat dicatat di penerimaan (`ap_auto_error`) — penerimaannya tetap tampil
di Hutang › Belum difakturkan dan bisa difakturkan manual seperti dulu. Jurnal yang gagal tercatat di tagihan
(`post_error`) dan muncul di Keuangan › Jurnal › Belum masuk jurnal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


def _tgl(v) -> str | None:
    if not v:
        return None
    return (v.isoformat() if hasattr(v, "isoformat") else str(v))[:10]


async def tagih_penerimaan(db, receipt_id: str, user: dict) -> dict:
    """Penerimaan PO yang baru dikonfirmasi → tagihan pemasok otomatis yang sudah disetujui. Tidak pernah melempar."""
    try:
        return await _tagih(db, receipt_id, user)
    except Exception as e:  # noqa: BLE001 — penerimaan barang tidak boleh gagal karena tagihan
        detail = getattr(e, "detail", None) or str(e)
        log.exception("hutang otomatis untuk penerimaan %s gagal", receipt_id)
        try:
            await db.warehouse_receiving.update_one({"id": receipt_id}, {"$set": {
                "ap_auto_error": str(detail)[:300], "ap_auto_error_at": _now()}})
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": str(detail)}


async def _tagih(db, receipt_id: str, user: dict) -> dict:
    from fastapi import HTTPException

    from core import purchase_returns as pr
    from routes import rahaza_ap_from_gr as apgr
    from routes.rahaza_posting import post_ap_invoice
    from utils.waktu import today_wib

    gr = await db.warehouse_receiving.find_one({"id": receipt_id}, {"_id": 0})
    if not gr or not gr.get("po_id"):
        return {"ok": False, "lewati": "bukan penerimaan dari PO"}
    if gr.get("status") not in apgr.BILLABLE_GR_STATUSES:
        return {"ok": False, "lewati": f"status penerimaan {gr.get('status')}"}
    if not pr.gr_billable_lines(gr):
        return {"ok": False, "lewati": "semua baris sudah ditagih"}
    po = await db.rahaza_purchase_orders.find_one({"id": gr["po_id"]}, {"_id": 0}) or {}

    tgl = _tgl(gr.get("received_at")) or today_wib().isoformat()
    payload = apgr.CreateAPFromGRPayload(
        gr_ids=[receipt_id],
        tax_pct=float(po.get("tax_pct") or 0),
        issue_date=tgl,
        payment_terms=po.get("payment_terms") or None,
        notes=(f"Dibuat otomatis saat barang diterima ({gr.get('receipt_number') or ''}, "
               f"PO {po.get('po_number') or gr.get('po_number') or ''}). Bila faktur pemasok berbeda, ubah lewat "
               f"Persetujuan Perubahan Faktur."),
    )
    token = f"otomatis-{receipt_id}"
    try:
        claimed = await apgr._claim_grs(db, [receipt_id], token)
    except HTTPException as e:
        return {"ok": False, "lewati": f"penerimaan sedang difakturkan: {e.detail}"}
    try:
        inv = await apgr._create_ap_invoice_from_gr_locked(db, payload, user)
    finally:
        await apgr._release_grs(db, claimed, token)

    inv_id = inv["id"]
    await db.rahaza_ap_invoices.update_one({"id": inv_id, "status": "draft"}, {"$set": {
        "status": "sent", "auto_from_gr": True, "approved_at": _now(),
        "approved_by": (user or {}).get("id") or "system",
        "approved_by_name": f"Otomatis saat penerimaan ({(user or {}).get('name') or 'sistem'})",
        "updated_at": _now()}})
    fresh = await db.rahaza_ap_invoices.find_one({"id": inv_id}, {"_id": 0})
    try:
        posting = await post_ap_invoice(db, fresh, user)
    except Exception as e:  # noqa: BLE001 — tercatat sebagai post_error (daftar Belum masuk jurnal)
        log.exception("jurnal tagihan otomatis %s gagal", inv.get("invoice_number"))
        posting = {"ok": False, "error": str(e)}
        await db.rahaza_ap_invoices.update_one({"id": inv_id}, {"$set": {
            "post_error": str(e)[:300], "post_error_at": _now()}})
    # uang muka PO (CBD / DP) langsung memotong tagihan ini (core.uang_muka_pemasok)
    from core.uang_muka_pemasok import terapkan_ke_tagihan
    potong = await terapkan_ke_tagihan(db, inv_id, user)
    peringatan = None
    if (po.get("payment_terms") or "") == "cbd" and not float(potong.get("dipakai") or 0):
        peringatan = (f"PO {po.get('po_number') or ''} bertermin Bayar di muka, tetapi belum ada uang muka yang "
                      f"dicatat. Tagihan {inv.get('invoice_number')} tetap menunggu dibayar.")
    await db.warehouse_receiving.update_one({"id": receipt_id}, {
        "$set": {"ap_auto_invoice_id": inv_id, "ap_auto_invoice_number": inv.get("invoice_number"),
                 "ap_auto_uang_muka": float(potong.get("dipakai") or 0), "ap_auto_peringatan": peringatan},
        "$unset": {"ap_auto_error": "", "ap_auto_error_at": ""}})
    try:
        from auth import log_activity
        await log_activity((user or {}).get("id") or "", (user or {}).get("name") or "", "ap_otomatis",
                           "rahaza_ap_invoices",
                           f"Tagihan {inv.get('invoice_number')} Rp {float(inv.get('total') or 0):,.0f} dibuat & disetujui "
                           f"otomatis dari penerimaan {gr.get('receipt_number')}")
    except Exception:  # noqa: BLE001
        log.exception("log_activity hutang otomatis gagal")
    return {"ok": True, "invoice_id": inv_id, "invoice_number": inv.get("invoice_number"),
            "total": inv.get("total"), "posting": posting, "uang_muka": potong.get("dipakai"), "peringatan": peringatan}
