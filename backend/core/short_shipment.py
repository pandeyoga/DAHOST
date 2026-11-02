"""core/short_shipment.py — SSOT SELISIH KIRIM (barang TIDAK sampai).

LATAR (memory/HANDOFF_SELISIH_CMT_BUYER.md §1, aturan owner 2026-07-31/08-01)
─────────────────────────────────────────────────────────────────────────────
Sistem selalu mencampur DUA kasus berbeda:

  Kasus 1 — REJECT: barang SAMPAI tapi cacat → produksi vendor tetap, barang
            masuk karantina QC lalu siklus permak. (SUDAH benar, bukan modul ini.)

  Kasus 2 — SELISIH KIRIM: barang TIDAK SAMPAI. Vendor mengklaim kirim 100, yang
            benar-benar diterima 90. Kata owner:
              · "dokumen data apa yang dikirimkan harus sesuai" ⇒ dokumen
                DIKOREKSI menjadi 90 (bukan 100 dengan selisih menggantung);
              · "10 barang ini … harus ada penyelesaiannya" ⇒ 10 pcs tetap
                KEWAJIBAN pihak pengirim (sisa kirim naik lagi → bisa dikirim ulang);
              · penyebab paling sering: salah input progres / barang ketinggalan,
                BUKAN klaim finansial. Karena itu TIDAK ADA potong tagihan otomatis.
              · keputusan finance (ditanggung CMT / DA) baru diambil bila barang
                dinyatakan hilang — di sisi buyer biasanya saat PO ditutup.
              · koreksi boleh sepihak oleh Admin DA + NOTIFIKASI ke vendor.
              · TANPA batas waktu: selisih tetap `open` sampai diselesaikan.

DUA DOKUMEN SELISIH (identitas kelas satu — sebelumnya cuma angka turunan):
  `cmt_short_shipments`  SEL-CMT-xxxxx  selisih kirim vendor CMT → DA
  `buyer_short_records`  SEL-BYR-xxxxx  selisih kirim DA → buyer

Semua mutasi buku kuantitas tetap lewat `core/production_qty_ledger`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from utils.waktu import wib_date_str

logger = logging.getLogger(__name__)

CMT_SHORT = "cmt_short_shipments"
BUYER_SHORT = "buyer_short_records"

# Penyelesaian selisih CMT→DA
CMT_RESOLUTIONS = {
    "dikirim_ulang":            "Barang ditemukan & dikirim ulang oleh vendor",
    "hilang_tanggungan_vendor": "Dinyatakan hilang — ditanggung vendor CMT",
    "hilang_tanggungan_da":     "Dinyatakan hilang — ditanggung DA",
    "salah_input_dikoreksi":    "Ternyata salah input — dokumen dikoreksi",
}
# Penyelesaian selisih DA→buyer
BUYER_RESOLUTIONS = {
    "dikirim_ulang":  "Barang ketinggalan/salah hitung → dikirim ulang",
    "tanggungan_cmt": "Keputusan finance: ditanggung vendor CMT",
    "tanggungan_da":  "Keputusan finance: ditanggung DA",
    "dibatalkan":     "Dibatalkan (salah catat qty diterima)",
}

STATUS_OPEN, STATUS_RESOLVED, STATUS_CANCELLED = "open", "resolved", "cancelled"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id():
    return str(uuid.uuid4())


def _i(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


async def _number(db, collection: str, prefix: str) -> str:
    from utils.counters import gen_prefixed_number
    return await gen_prefixed_number(db, collection, "short_number", prefix, 5)


async def _ledger_inc(db, job_item_id: str, inc: dict):
    if not job_item_id or not inc:
        return
    inc = {k: v for k, v in inc.items() if v}
    if not inc:
        return
    await db.production_job_items.update_one(
        {"id": job_item_id}, {"$inc": inc, "$set": {"updated_at": _now()}})
    # jaga agar tidak negatif (data lama / koreksi berulang)
    ji = await db.production_job_items.find_one(
        {"id": job_item_id}, {"_id": 0, "qty_short_open": 1, "qty_short_resolved": 1})
    fix = {k: 0 for k, v in (ji or {}).items() if k.startswith("qty_short") and _i(v) < 0}
    if fix:
        await db.production_job_items.update_one({"id": job_item_id}, {"$set": fix})


async def _notify(db, **kw):
    try:
        from utils.notif_unified import notif_insert
        return await notif_insert(db, **kw)
    except Exception:  # noqa: BLE001
        logger.exception("notifikasi selisih gagal dikirim")
        return None


# Penerima cadangan bila vendor belum punya akun portal (2026-08-07): notifikasi
# HARUS punya target, kalau tidak akan tersembunyi / bocor lintas role.
CMT_FALLBACK_ROLES = ("admin_maklon", "manager_produksi", "supervisor_produksi",
                      "admin_produksi", "owner", "admin", "superadmin")


async def _vendor_user_ids(db, vendor_id: str) -> list:
    if not vendor_id:
        return []
    rows = await db.users.find(
        {"$or": [{"vendor_id": vendor_id}, {"cmt_vendor_id": vendor_id}]},
        {"_id": 0, "id": 1}).to_list(20)
    return [r["id"] for r in rows if r.get("id")]


# 2026-11-02 (K17 butir 6): peran Keuangan yang BENAR-BENAR ada di aplikasi ini
# (`core/roles.py`). Dulu notifikasi selisih memakai `finance`/`admin_finance` (peran
# fiktif tanpa pengguna) sehingga Keuangan tidak pernah tahu ada selisih.
FINANCE_NOTIFY_ROLES = ("accounting", "staff_keuangan")


async def _admin_finance_user_ids(db) -> list:
    rows = await db.users.find(
        {"role": {"$in": ["superadmin", "admin", "admin_maklon", "owner", "manager",
                          *FINANCE_NOTIFY_ROLES]}},
        {"_id": 0, "id": 1}).to_list(50)
    return [r["id"] for r in rows if r.get("id")]


async def notify_finance(db, *, title: str, body: str, source_type: str, source_id: str,
                         source_ref: str = "", meta: dict | None = None,
                         subtype: str = "cmt_billing_variance") -> None:
    """Notifikasi ke peran Keuangan nyata (accounting, staff_keuangan) — satu pintu."""
    await _notify(db, type="dewi", subtype=subtype, severity="warning",
                  target_roles=list(FINANCE_NOTIFY_ROLES), title=title, body=body,
                  source_type=source_type, source_id=source_id, source_ref=source_ref,
                  meta={"link_module": "prod-cmt-billing", **(meta or {})})


# ═══════════════════════════════════════════════════════════════════════════
# K17 (keputusan owner b, 2026-11-02) — TAGIHAN CMT TIDAK DIUBAH OTOMATIS,
# tetapi DITANDAI untuk Keuangan setiap kali dasar tagihannya berubah.
# ═══════════════════════════════════════════════════════════════════════════
async def refresh_cmt_payment_variance(db, receipt_id: str) -> dict | None:
    """Hitung ulang angka selisih tagihan CMT satu penerimaan (tanpa mengubah nilai tagihan).

    `overbilled_pcs`  = pcs yang sudah ditagih tetapi tidak lagi lolos QC (koreksi turun)
    `open_short_qty`  = selisih kirim CMT→DA penerimaan ini yang masih terbuka
    `variance_unresolved_qty` = jumlah keduanya → kolom "selisih belum diselesaikan"
    """
    if not receipt_id:
        return None
    pay = await db.dewi_cmt_payments.find_one({"source_receipt_id": receipt_id}, {"_id": 0})
    if not pay:
        return None
    lines = await db.cmt_receipt_lines.find({"receipt_id": receipt_id}, {"_id": 0}).to_list(500)
    cur_by_line = {ln["id"]: _i(ln.get("qty_actual")) for ln in lines}
    over_pcs, over_amt = 0, 0.0
    for b in pay.get("breakdown") or []:
        billed = _i(b.get("qty_billed", b.get("qty_actual")))
        cur = cur_by_line.get(b.get("line_id"), billed)
        if billed > cur:
            over_pcs += billed - cur
            over_amt += (billed - cur) * float(b.get("cmt_rate_per_pcs") or 0)
    shorts = await db[CMT_SHORT].find({"receipt_id": receipt_id, "status": STATUS_OPEN},
                                      {"_id": 0}).to_list(None)
    open_short = sum(max(0, _i(s.get("qty_short")) - _i(s.get("qty_resolved"))) for s in shorts)
    upd = {"overbilled_pcs": over_pcs, "overbilled_amount": round(over_amt, 2),
           "open_short_qty": open_short, "variance_unresolved_qty": over_pcs + open_short,
           "updated_at": _now()}
    await db.dewi_cmt_payments.update_one({"id": pay["id"]}, {"$set": upd})
    return {**pay, **upd}


async def flag_cmt_payment_variance(db, receipt_id: str, *, reason: str, event_type: str,
                                    actor: dict | None = None, qty: int = 0,
                                    notify: bool = True) -> dict | None:
    """Tandai tagihan CMT (`variance_flagged`) + alasan + notifikasi Keuangan.

    Nilai tagihan TIDAK diubah (keputusan owner b). Dipanggil oleh koreksi hasil QC,
    koreksi deklarasi, dan penyelesaian selisih CMT.
    """
    pay = await refresh_cmt_payment_variance(db, receipt_id)
    if not pay:
        return None
    event = {"at": _now(), "type": event_type, "reason": reason, "qty": _i(qty),
             "by": (actor or {}).get("name", "sistem")}
    reasons = list(pay.get("variance_reasons") or [])
    if reason and reason not in reasons:
        reasons.append(reason)
    await db.dewi_cmt_payments.update_one({"id": pay["id"]}, {
        "$set": {"variance_flagged": True, "needs_finance_review": True,
                 "variance_reasons": reasons, "variance_reason": "; ".join(reasons),
                 "updated_at": _now()},
        "$push": {"variance_events": event}})
    if notify:
        body = (f"Tagihan CMT {pay.get('payment_code')} ({pay.get('cmt_name') or pay.get('vendor_name') or '-'}, "
                f"PO {pay.get('po_number') or '-'}) DITANDAI untuk Keuangan: {reason}. Nilai tagihan "
                f"tidak diubah otomatis (Rp {float(pay.get('subtotal') or 0):,.0f}); selisih belum "
                f"diselesaikan {pay.get('variance_unresolved_qty', 0)} pcs"
                + (f", lebih tagih Rp {float(pay.get('overbilled_amount') or 0):,.0f}"
                   if pay.get('overbilled_amount') else "") + ".")
        await notify_finance(db, title=f"Tagihan CMT perlu ditinjau — {pay.get('payment_code')}",
                             body=body, source_type="dewi_cmt_payments", source_id=pay["id"],
                             source_ref=pay.get("payment_code") or "",
                             meta={"payment_code": pay.get("payment_code"), "event": event_type,
                                   "receipt_id": receipt_id})
    return await db.dewi_cmt_payments.find_one({"id": pay["id"]}, {"_id": 0})


# ═══════════════════════════════════════════════════════════════════════════
# SISI 1 — SELISIH KIRIM VENDOR CMT → DA
# ═══════════════════════════════════════════════════════════════════════════
async def record_cmt_short(db, *, receipt: dict, line: dict, claimed: int, arrived: int,
                           job_item: dict | None = None, actor: dict | None = None,
                           reason: str = "") -> dict | None:
    """Buat/segarkan dokumen selisih kirim untuk SATU baris penerimaan.

    Idempoten per `receipt_line_id`: dipanggil ulang (mis. setelah koreksi) akan
    memperbarui qty, bukan membuat dokumen kedua.
    """
    short_qty = max(0, _i(claimed) - _i(arrived))
    existing = await db[CMT_SHORT].find_one({"receipt_line_id": line["id"]}, {"_id": 0})

    if short_qty <= 0:
        if existing and existing.get("status") == STATUS_OPEN:
            await cancel_cmt_short(db, existing["id"], actor=actor,
                                   reason=reason or "Selisih hilang setelah koreksi dokumen")
            return None
        return existing

    if existing:
        delta = short_qty - _i(existing.get("qty_short"))
        await db[CMT_SHORT].update_one({"id": existing["id"]}, {
            "$set": {"qty_claimed": _i(claimed), "qty_arrived": _i(arrived),
                     "qty_short": short_qty,
                     "status": STATUS_OPEN if short_qty > _i(existing.get("qty_resolved")) else existing.get("status"),
                     "updated_at": _now()},
            "$push": {"history": {"at": _now(), "by": (actor or {}).get("name", "sistem"),
                                  "action": "update", "qty_short": short_qty,
                                  "reason": reason or "koreksi dokumen"}}})
        if delta and (job_item or {}).get("id"):
            await _ledger_inc(db, job_item["id"], {"qty_short_open": delta})
        return await db[CMT_SHORT].find_one({"id": existing["id"]}, {"_id": 0})

    doc = {
        "id": _id(),
        "short_number": await _number(db, CMT_SHORT, "SEL-CMT-"),
        "short_date": wib_date_str(),
        "receipt_id": receipt.get("id"),
        "receipt_code": receipt.get("receipt_code"),
        "receipt_line_id": line["id"],
        "source_buyer_shipment_item_id": line.get("source_buyer_shipment_item_id") or "",
        "declaration_shipment_id": receipt.get("related_shipment_id") or "",
        "po_id": receipt.get("po_id") or "",
        "po_number": receipt.get("po_number") or "",
        "po_item_id": line.get("po_item_id") or "",
        "job_item_id": (job_item or {}).get("id") or line.get("job_item_id") or "",
        "vendor_id": receipt.get("cmt_vendor_id") or "",
        "vendor_name": receipt.get("cmt_name") or "",
        "sku": line.get("sku_code") or "",
        "product_name": line.get("product_name") or "",
        "color": line.get("color") or "", "size": line.get("size") or "",
        "qty_claimed": _i(claimed),
        "qty_arrived": _i(arrived),
        "qty_short": short_qty,
        "qty_resolved": 0,
        "status": STATUS_OPEN,
        "resolution": "",
        "resolution_notes": "",
        "resolved_at": "", "resolved_by": "",
        "created_by": (actor or {}).get("name", "sistem"),
        "created_at": _now(), "updated_at": _now(),
        "history": [{"at": _now(), "by": (actor or {}).get("name", "sistem"),
                     "action": "open", "qty_short": short_qty,
                     "reason": reason or "qty diterima DA lebih kecil dari klaim vendor"}],
    }
    await db[CMT_SHORT].insert_one(dict(doc))

    # ── Rambatkan koreksi ke DOKUMEN DEKLARASI VENDOR (surat jalan CMT→DA) ──
    await _propagate_declaration_correction(
        db, line=line, arrived=_i(arrived), claimed=_i(claimed), actor=actor,
        short_number=doc["short_number"])

    # ── Notifikasi vendor (sepihak, tanpa sanggahan — keputusan owner) ──
    body = (f"Deklarasi kirim {line.get('sku_code') or ''} dikoreksi dari {_i(claimed)} → "
            f"{_i(arrived)} pcs sesuai qty yang diterima DA. {short_qty} pcs BELUM SAMPAI "
            f"dan masih menjadi kewajiban Anda — mohon dicari lalu dikirim ulang. "
            f"Dokumen selisih: {doc['short_number']} (penerimaan {receipt.get('receipt_code')}).")
    for uid in await _vendor_user_ids(db, doc["vendor_id"]):
        await _notify(db, type="dewi", subtype="cmt_short_shipment", severity="warning",
                      user_id=uid, title=f"Selisih kirim {short_qty} pcs — {doc['short_number']}",
                      body=body, source_type=CMT_SHORT, source_id=doc["id"],
                      source_ref=doc["short_number"],
                      meta={"short_number": doc["short_number"], "qty_short": short_qty,
                            "po_number": doc["po_number"], "sku": doc["sku"],
                            "receipt_code": doc["receipt_code"]})
    if not await _vendor_user_ids(db, doc["vendor_id"]):
        # Vendor belum punya akun portal → beri tahu tim DA (jangan jadi siaran
        # tanpa target yang bocor lintas role).
        await _notify(db, type="dewi", subtype="cmt_short_shipment", severity="warning",
                      target_roles=list(CMT_FALLBACK_ROLES),
                      title=f"Selisih kirim {short_qty} pcs — {doc['short_number']}", body=body,
                      source_type=CMT_SHORT, source_id=doc["id"], source_ref=doc["short_number"],
                      meta={"short_number": doc["short_number"], "qty_short": short_qty,
                            "po_number": doc["po_number"], "sku": doc["sku"],
                            "receipt_code": doc["receipt_code"]})
    return doc


async def notify_declaration_correction(db, *, receipt: dict, line: dict, old_value: int,
                                        new_value: int, reason: str = "",
                                        actor: dict | None = None,
                                        field: str = "klaim kirim") -> int:
    """Vendor WAJIB diberi tahu setiap kali angka dokumennya dikoreksi Admin DA.

    Keputusan owner: koreksi boleh SEPIHAK, tetapi vendor mendapat notifikasi +
    label yang jelas (tanpa proses sanggahan). Dipakai oleh kedua fitur koreksi
    resmi — termasuk saat koreksi justru MENGHAPUS selisih (biar vendor tahu
    kewajibannya sudah tidak ada).
    """
    vendor_id = receipt.get("cmt_vendor_id") or ""
    body = (f"Angka {field} untuk {line.get('sku_code') or 'item'} pada penerimaan "
            f"{receipt.get('receipt_code')} (PO {receipt.get('po_number') or '-'}) dikoreksi "
            f"oleh Admin DA: {_i(old_value)} → {_i(new_value)} pcs."
            + (f" Alasan: {reason}." if reason else "")
            + " Dokumen deklarasi & sisa kirim Anda sudah disesuaikan otomatis.")
    uids = await _vendor_user_ids(db, vendor_id)
    sent = 0
    for uid in uids or [None]:
        await _notify(db, type="dewi", subtype="cmt_declaration_corrected", severity="warning",
                      user_id=uid, title=f"Koreksi {field} — {receipt.get('receipt_code')}",
                      body=body, source_type="cmt_receipt_lines", source_id=line.get("id"),
                      source_ref=receipt.get("receipt_code"),
                      meta={"receipt_code": receipt.get("receipt_code"),
                            "sku": line.get("sku_code"), "old": _i(old_value),
                            "new": _i(new_value), "field": field, "reason": reason})
        sent += 1
    return sent


async def _propagate_declaration_correction(db, *, line: dict, arrived: int, claimed: int,
                                            actor: dict | None = None,
                                            short_number: str = "") -> bool:
    """Koreksi dokumen deklarasi vendor (`buyer_shipment_items.qty_shipped`) supaya
    "dokumen = kenyataan" DAN sisa kirim vendor naik lagi sebesar yang belum sampai.

    Memakai mekanisme audit yang sudah ada (`edit_history`) — bukan tulis senyap.
    """
    item_id = line.get("source_buyer_shipment_item_id")
    if not item_id:
        return False
    item = await db.buyer_shipment_items.find_one({"id": item_id})
    if not item:
        return False
    old = _i(item.get("qty_shipped"))
    if old == arrived:
        return False
    entry = {"old_qty": old, "new_qty": arrived,
             "reason": (f"Koreksi otomatis: qty diterima DA {arrived} pcs dari klaim {claimed} pcs"
                        + (f" (dokumen selisih {short_number})" if short_number else "")),
             "edited_by": (actor or {}).get("name", "sistem"),
             "edited_by_id": (actor or {}).get("id", "system"),
             "edited_at": _now(), "source": "cmt_receipt_qc"}
    await db.buyer_shipment_items.update_one({"id": item_id}, {
        "$set": {"qty_shipped": arrived,
                 "qty_claimed_original": _i(item.get("qty_claimed_original")) or old,
                 "qty_received": arrived,
                 "qty_short_open": max(0, claimed - arrived),
                 "corrected_by_da_at": _now(), "updated_at": _now()},
        "$push": {"edit_history": entry}})
    return True


async def resolve_cmt_shorts_on_arrival(db, *, po_item_id: str = "", job_item_id: str = "",
                                        qty: int = 0, receipt: dict | None = None,
                                        line: dict | None = None, actor: dict | None = None,
                                        exclude_line_ids: list | None = None) -> dict:
    """Barang yang BARU SAMPAI menutup selisih lama item yang sama (kirim ulang).

    FIFO (selisih tertua dulu). Mengembalikan {resolved, shorts:[...]}.
    """
    remaining = _i(qty)
    out = {"resolved": 0, "shorts": []}
    if remaining <= 0:
        return out
    q: dict = {"status": STATUS_OPEN}
    if po_item_id:
        q["po_item_id"] = po_item_id
    elif job_item_id:
        q["job_item_id"] = job_item_id
    else:
        return out
    if exclude_line_ids:
        q["receipt_line_id"] = {"$nin": list(exclude_line_ids)}
    shorts = await db[CMT_SHORT].find(q, {"_id": 0}).sort("created_at", 1).to_list(50)
    for s in shorts:
        if remaining <= 0:
            break
        open_qty = max(0, _i(s.get("qty_short")) - _i(s.get("qty_resolved")))
        if open_qty <= 0:
            continue
        take = min(open_qty, remaining)
        fully = take >= open_qty
        await db[CMT_SHORT].update_one({"id": s["id"]}, {
            "$inc": {"qty_resolved": take},
            "$set": {"status": STATUS_RESOLVED if fully else STATUS_OPEN,
                     "resolution": "dikirim_ulang" if fully else s.get("resolution", ""),
                     "resolution_notes": (f"Ditutup oleh penerimaan "
                                          f"{(receipt or {}).get('receipt_code', '')}"),
                     "resolved_at": _now() if fully else "",
                     "resolved_by": (actor or {}).get("name", "sistem") if fully else "",
                     "updated_at": _now()},
            "$push": {"history": {"at": _now(), "by": (actor or {}).get("name", "sistem"),
                                  "action": "resolve_arrival", "qty": take,
                                  "receipt_code": (receipt or {}).get("receipt_code", ""),
                                  "reason": "barang ditemukan & dikirim ulang"}}})
        await _ledger_inc(db, s.get("job_item_id") or job_item_id,
                          {"qty_short_open": -take, "qty_short_resolved": take})
        if s.get("receipt_line_id"):
            await db.cmt_receipt_lines.update_one(
                {"id": s["receipt_line_id"]},
                {"$inc": {"qty_short_resolved": take},
                 "$set": {"short_status": STATUS_RESOLVED if fully else STATUS_OPEN}})
        out["resolved"] += take
        out["shorts"].append({"short_number": s.get("short_number"), "qty": take,
                              "status": STATUS_RESOLVED if fully else STATUS_OPEN})
        remaining -= take
    return out


async def cancel_cmt_short(db, short_id: str, *, actor: dict | None = None,
                           reason: str = "") -> dict | None:
    """Batalkan dokumen selisih (mis. ternyata salah input dan sudah dikoreksi)."""
    s = await db[CMT_SHORT].find_one({"id": short_id}, {"_id": 0})
    if not s or s.get("status") == STATUS_CANCELLED:
        return s
    open_qty = max(0, _i(s.get("qty_short")) - _i(s.get("qty_resolved")))
    await db[CMT_SHORT].update_one({"id": short_id}, {
        "$set": {"status": STATUS_CANCELLED, "resolution": "salah_input_dikoreksi",
                 "resolution_notes": reason, "resolved_at": _now(),
                 "resolved_by": (actor or {}).get("name", "sistem"), "updated_at": _now()},
        "$push": {"history": {"at": _now(), "by": (actor or {}).get("name", "sistem"),
                              "action": "cancel", "qty": open_qty, "reason": reason}}})
    await _ledger_inc(db, s.get("job_item_id"), {"qty_short_open": -open_qty})
    if s.get("receipt_line_id"):
        await db.cmt_receipt_lines.update_one(
            {"id": s["receipt_line_id"]},
            {"$set": {"short_status": STATUS_CANCELLED, "qty_short": 0}})
    try:
        await refresh_cmt_payment_variance(db, s.get("receipt_id"))
    except Exception:  # noqa: BLE001
        logger.exception("segarkan selisih tagihan CMT gagal (%s)", s.get("short_number"))
    return await db[CMT_SHORT].find_one({"id": short_id}, {"_id": 0})


async def resolve_cmt_short_manual(db, short_id: str, *, resolution: str, notes: str = "",
                                   actor: dict | None = None) -> dict:
    """Penyelesaian MANUAL selisih kirim CMT→DA (keputusan Admin/Finance).

    Tanpa batas waktu otomatis (keputusan owner) — selalu keputusan manusia.
    Tidak ada posting finansial otomatis: keputusan tanggungan hanya DICATAT
    (+notifikasi) supaya Finance memprosesnya lewat modul tagihan CMT.
    """
    if resolution not in CMT_RESOLUTIONS:
        raise ValueError(f"resolution tidak valid: {resolution}")
    s = await db[CMT_SHORT].find_one({"id": short_id}, {"_id": 0})
    if not s:
        raise LookupError("dokumen selisih tidak ditemukan")
    if s.get("status") != STATUS_OPEN:
        raise ValueError(f"selisih {s.get('short_number')} sudah berstatus '{s.get('status')}'")
    if resolution == "salah_input_dikoreksi":
        return await cancel_cmt_short(db, short_id, actor=actor,
                                      reason=notes or "dikoreksi manual")
    open_qty = max(0, _i(s.get("qty_short")) - _i(s.get("qty_resolved")))
    await db[CMT_SHORT].update_one({"id": short_id}, {
        "$inc": {"qty_resolved": open_qty},
        "$set": {"status": STATUS_RESOLVED, "resolution": resolution,
                 "resolution_notes": notes, "resolved_at": _now(),
                 "resolved_by": (actor or {}).get("name", "sistem"), "updated_at": _now()},
        "$push": {"history": {"at": _now(), "by": (actor or {}).get("name", "sistem"),
                              "action": "resolve_manual", "qty": open_qty,
                              "resolution": resolution, "reason": notes}}})
    await _ledger_inc(db, s.get("job_item_id"),
                      {"qty_short_open": -open_qty, "qty_short_resolved": open_qty})
    if s.get("receipt_line_id"):
        await db.cmt_receipt_lines.update_one(
            {"id": s["receipt_line_id"]},
            {"$inc": {"qty_short_resolved": open_qty}, "$set": {"short_status": STATUS_RESOLVED}})
    body = (f"Selisih kirim {s.get('short_number')} ({open_qty} pcs {s.get('sku')}, PO "
            f"{s.get('po_number')}) diselesaikan: {CMT_RESOLUTIONS[resolution]}."
            + (f" Catatan: {notes}" if notes else ""))
    for uid in await _vendor_user_ids(db, s.get("vendor_id", "")):
        await _notify(db, type="dewi", subtype="cmt_short_resolved",
                      severity="info" if resolution == "dikirim_ulang" else "warning",
                      user_id=uid, title=f"Selisih {s.get('short_number')} diselesaikan",
                      body=body, source_type=CMT_SHORT, source_id=short_id,
                      source_ref=s.get("short_number"),
                      meta={"short_number": s.get("short_number"), "resolution": resolution})
    # 2026-11-02 (K17 butir 6): docstring di atas berjanji Keuangan memprosesnya — dulu
    # notifikasi hanya ke vendor. Sekarang tagihan penerimaannya DITANDAI + Keuangan diberi tahu.
    try:
        await flag_cmt_payment_variance(
            db, s.get("receipt_id"), event_type=f"short_{resolution}", actor=actor, qty=open_qty,
            reason=(f"selisih kirim {s.get('short_number')} {open_qty} pcs {s.get('sku') or ''} "
                    f"diselesaikan: {CMT_RESOLUTIONS[resolution]}"
                    + (f" ({notes})" if notes else "")))
    except Exception:  # noqa: BLE001
        logger.exception("penandaan tagihan CMT untuk selisih %s gagal", s.get("short_number"))
    return await db[CMT_SHORT].find_one({"id": short_id}, {"_id": 0})


async def list_cmt_shorts(db, *, status: str = "open", po_id: str = "", vendor_id: str = "",
                          limit: int = 300) -> dict:
    q: dict = {}
    if status and status != "all":
        q["status"] = status
    if po_id:
        q["po_id"] = po_id
    if vendor_id:
        q["vendor_id"] = vendor_id
    rows = await db[CMT_SHORT].find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    for r in rows:
        r["qty_open"] = max(0, _i(r.get("qty_short")) - _i(r.get("qty_resolved")))
    return {
        "items": rows, "total": len(rows),
        "total_qty_short": sum(_i(r.get("qty_short")) for r in rows),
        "total_qty_open": sum(_i(r.get("qty_open")) for r in rows),
        "resolutions": CMT_RESOLUTIONS,
    }


async def cmt_short_totals(db, *, po_id: str = "") -> dict:
    q = {"po_id": po_id} if po_id else {}
    rows = await db[CMT_SHORT].find(q, {"_id": 0}).to_list(None)
    return {
        "qty_short_open": sum(max(0, _i(r.get("qty_short")) - _i(r.get("qty_resolved")))
                              for r in rows if r.get("status") == STATUS_OPEN),
        "qty_short_resolved": sum(_i(r.get("qty_resolved")) for r in rows
                                  if r.get("status") != STATUS_CANCELLED),
        "docs_open": sum(1 for r in rows if r.get("status") == STATUS_OPEN),
    }


# ═══════════════════════════════════════════════════════════════════════════
# SISI 2 — SELISIH KIRIM DA → BUYER
# ═══════════════════════════════════════════════════════════════════════════
async def record_buyer_short(db, *, shipment: dict, item: dict, qty_shipped: int,
                             qty_received: int, actor: dict | None = None,
                             reason: str = "") -> dict | None:
    """Buyer menerima LEBIH SEDIKIT dari yang dikirim → selisih punya identitas.

    Perlakuan SAMA dengan sisi CMT (keputusan owner: "sama halnya dengan poin satu"):
      1. dokumen surat jalan dikoreksi ke qty yang benar-benar diterima buyer;
      2. selisihnya menjadi dokumen `SEL-BYR-xxxxx` status `open` (bisa dikirim ulang);
      3. barang yang belum sampai DIKEMBALIKAN ke stok FG (masih kewajiban DA)
         sehingga kapasitas kirim ulang & nilai persediaan tetap benar;
      4. notifikasi ke Admin & Finance; keputusan tanggungan (CMT/DA) menyusul.
    """
    short_qty = max(0, _i(qty_shipped) - _i(qty_received))
    if short_qty <= 0:
        return None
    from core import production_qty_ledger as qled

    po_id = item.get("po_id") or shipment.get("po_id") or ""
    po_number = item.get("po_number") or shipment.get("po_number") or ""
    if po_id and not po_number:
        po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "po_number": 1})
        po_number = (po or {}).get("po_number", "")

    doc = {
        "id": _id(),
        "short_number": await _number(db, BUYER_SHORT, "SEL-BYR-"),
        "short_date": wib_date_str(),
        "shipment_id": shipment.get("id"),
        "shipment_number": shipment.get("shipment_number"),
        "shipment_item_id": item.get("id"),
        "dispatch_seq": _i(item.get("dispatch_seq")) or 1,
        "po_id": po_id, "po_number": po_number,
        "po_item_id": item.get("po_item_id") or "",
        "job_item_id": item.get("job_item_id") or "",
        "customer_name": shipment.get("customer_name") or "",
        "vendor_id": shipment.get("vendor_id") or "",
        "vendor_name": shipment.get("vendor_name") or "",
        "sku": item.get("sku") or "", "product_name": item.get("product_name") or "",
        "size": item.get("size") or "", "color": item.get("color") or "",
        "qty_shipped_claimed": _i(qty_shipped),
        "qty_received": _i(qty_received),
        "qty_short": short_qty,
        "qty_resolved": 0,
        "status": STATUS_OPEN,
        "resolution": "", "resolution_notes": "",
        "finance_decision": "", "finance_decided_by": "", "finance_decided_at": "",
        "resolved_at": "", "resolved_by": "",
        "stock_returned_at": "", "stock_writeoff_at": "",
        "created_by": (actor or {}).get("name", "sistem"),
        "created_at": _now(), "updated_at": _now(),
        "history": [{"at": _now(), "by": (actor or {}).get("name", "sistem"), "action": "open",
                     "qty_short": short_qty,
                     "reason": reason or "qty diterima buyer lebih kecil dari yang dikirim"}],
    }
    await db[BUYER_SHORT].insert_one(dict(doc))

    # 1+2. dokumen SJ dikoreksi ke kenyataan (klaim awal disimpan + audit trail)
    entry = {"old_qty": _i(qty_shipped), "new_qty": _i(qty_received),
             "reason": (f"Koreksi otomatis: qty diterima buyer {_i(qty_received)} pcs dari "
                        f"{_i(qty_shipped)} pcs dikirim (dokumen selisih {doc['short_number']})"),
             "edited_by": (actor or {}).get("name", "sistem"),
             "edited_by_id": (actor or {}).get("id", "system"),
             "edited_at": _now(), "source": "buyer_receipt_variance"}
    await db.buyer_shipment_items.update_one({"id": item["id"]}, {
        "$set": {"qty_shipped": _i(qty_received),
                 "qty_shipped_claimed": _i(item.get("qty_shipped_claimed")) or _i(qty_shipped),
                 "qty_short_open": short_qty, "updated_at": _now()},
        "$push": {"edit_history": entry}})

    # 3. barang belum sampai kembali ke stok FG (kewajiban DA untuk dikirim ulang)
    # 2026-11-02 (K17 butir 3): hanya bila baris ini MEMANG mengeluarkan stok (serah terima
    # PO internal tidak memotong stok ⇒ mengembalikan stok = stok fantom), dan
    # `fg_issued_qty` ikut turun supaya hapus/koreksi SJ tidak mengembalikan stok dua kali.
    try:
        mat = (await qled.resolve_fg_material(db, material_id=item.get("fg_material_id", ""),
                                              sku=doc["sku"])
               if item.get("fg_issued_at") else None)
        if mat:
            await db.buyer_shipment_items.update_one(
                {"id": item["id"]},
                {"$set": {"fg_issued_qty": max(0, _i(item.get("fg_issued_qty")) - short_qty)}})
            # 2026-11-02 (F1): barang yang belum sampai kembali ke stok dengan biaya saat ia
            # keluar (jejak FIFO baris SJ ini), bukan lapisan Rp 0 yang menurunkan rata-rata HPP.
            exit_cost = await qled.exit_cost_of(db, material_id=mat["id"],
                                                shipment_item_id=item.get("id") or "",
                                                sku=mat.get("code", doc["sku"]))
            posted = await qled.post_fg_accepted(
                db, material_id=mat["id"], qty=short_qty,
                ref={"source": "buyer_short_reopen", "short_id": doc["id"],
                     "short_number": doc["short_number"],
                     "shipment_id": doc["shipment_id"],
                     "shipment_number": doc["shipment_number"],
                     "shipment_item_id": item.get("id") or "",
                     "po_id": po_id, "po_number": po_number},
                actor=actor,
                meta={"material_code": mat.get("code", doc["sku"]),
                      "material_name": mat.get("name", ""), "unit": "pcs",
                      "type": "finished_goods"},
                exit_cost=exit_cost,
                # K14: barang PO maklon tidak membentuk lapisan biaya DA (juga saat kembali)
                skip_cost_layer=(shipment.get("business_type") == "maklon"))
            await db.rahaza_fg_movements.insert_one({
                "id": _id(), "sku_code": doc["sku"], "movement_type": "IN",
                "qty": short_qty, "source": "buyer_short_reopen",
                "ref_id": doc["id"], "ref_number": doc["short_number"],
                "material_id": mat["id"], "location_id": posted["location_id"],
                "notes": (f"Selisih kirim buyer {doc['short_number']} — {short_qty} pcs "
                          f"belum sampai, dikembalikan ke stok FG"),
                "created_by": (actor or {}).get("name", "sistem"), "created_at": _now()})
            await db[BUYER_SHORT].update_one({"id": doc["id"]},
                                             {"$set": {"stock_returned_at": _now()}})
    except Exception:  # noqa: BLE001
        logger.exception("pengembalian stok FG untuk selisih buyer %s gagal", doc["short_number"])

    # 4. notifikasi Admin & Finance
    body = (f"Buyer {doc['customer_name'] or '-'} menerima {_i(qty_received)} dari "
            f"{_i(qty_shipped)} pcs {doc['sku']} (PO {po_number}, SJ "
            f"{doc['shipment_number']}). {short_qty} pcs BELUM SAMPAI — dokumen selisih "
            f"{doc['short_number']} dibuka: kirim ulang, atau tentukan tanggungan "
            f"(CMT / DA) saat PO ditutup.")
    for uid in await _admin_finance_user_ids(db):
        await _notify(db, type="dewi", subtype="buyer_short_record", severity="warning",
                      user_id=uid, title=f"Selisih terima buyer {short_qty} pcs — {doc['short_number']}",
                      body=body, source_type=BUYER_SHORT, source_id=doc["id"],
                      source_ref=doc["short_number"],
                      meta={"short_number": doc["short_number"], "qty_short": short_qty,
                            "po_number": po_number, "sku": doc["sku"]})
    return doc


async def resolve_buyer_shorts_on_dispatch(db, *, po_item_id: str = "", qty: int = 0,
                                           shipment: dict | None = None,
                                           actor: dict | None = None,
                                           shipment_item_id: str = "") -> dict:
    """Dispatch baru untuk item yang sama menutup selisih buyer (kirim ulang).

    2026-11-02 (K17 butir 3): penutupan DITAUTKAN ke baris SJ penutupnya
    (`resolution_links[]`) supaya hapus/koreksi SJ itu MEMBUKA KEMBALI selisihnya
    (dulu SEL-BYR tetap `resolved` walau SJ kirim ulangnya sudah dihapus — w3 S10b).
    """
    remaining = _i(qty)
    out = {"resolved": 0, "shorts": []}
    if remaining <= 0 or not po_item_id:
        return out
    shorts = await db[BUYER_SHORT].find(
        {"po_item_id": po_item_id, "status": STATUS_OPEN}, {"_id": 0}
    ).sort("created_at", 1).to_list(50)
    for s in shorts:
        if remaining <= 0:
            break
        open_qty = max(0, _i(s.get("qty_short")) - _i(s.get("qty_resolved")))
        if open_qty <= 0:
            continue
        take = min(open_qty, remaining)
        fully = take >= open_qty
        await db[BUYER_SHORT].update_one({"id": s["id"]}, {
            "$inc": {"qty_resolved": take},
            "$set": {"status": STATUS_RESOLVED if fully else STATUS_OPEN,
                     "resolution": "dikirim_ulang" if fully else s.get("resolution", ""),
                     "resolution_notes": (f"Ditutup oleh pengiriman ulang "
                                          f"{(shipment or {}).get('shipment_number', '')}"),
                     "resolved_at": _now() if fully else "",
                     "resolved_by": (actor or {}).get("name", "sistem") if fully else "",
                     "updated_at": _now()},
            "$push": {"history": {"at": _now(), "by": (actor or {}).get("name", "sistem"),
                                  "action": "resolve_reship", "qty": take,
                                  "shipment_number": (shipment or {}).get("shipment_number", ""),
                                  "reason": "dikirim ulang"},
                      "resolution_links": {"shipment_id": (shipment or {}).get("id", ""),
                                      "shipment_number": (shipment or {}).get("shipment_number", ""),
                                      "shipment_item_id": shipment_item_id, "qty": take,
                                      "at": _now()}}})
        out["resolved"] += take
        out["shorts"].append({"short_number": s.get("short_number"), "qty": take})
        remaining -= take
    return out


async def reopen_buyer_shorts_for_item(db, *, shipment_item_id: str, qty: int | None = None,
                                       actor: dict | None = None, reason: str = "") -> dict:
    """Buka kembali selisih buyer yang DITUTUP oleh baris SJ `shipment_item_id`.

    `qty=None` = seluruh penutupan baris itu (SJ dihapus); angka = sebagian (qty dikirim
    dikoreksi turun). Selisih terbaru dibuka lebih dulu.
    """
    out = {"reopened": 0, "shorts": []}
    if not shipment_item_id:
        return out
    left = None if qty is None else _i(qty)
    shorts = await db[BUYER_SHORT].find(
        {"resolution_links": {"$exists": True}, "status": {"$ne": STATUS_CANCELLED}}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    shorts = [s for s in shorts
              if any(x.get("shipment_item_id") == shipment_item_id for x in (s.get("resolution_links") or []))]
    for s in shorts:
        if left is not None and left <= 0:
            break
        links = list(s.get("resolution_links") or [])
        by_item = sum(_i(x.get("qty")) for x in links if x.get("shipment_item_id") == shipment_item_id)
        take = by_item if left is None else min(by_item, left)
        if take <= 0:
            continue
        # kurangi tautan baris ini sebanyak `take`
        rest, new_links = take, []
        for x in links:
            if rest > 0 and x.get("shipment_item_id") == shipment_item_id:
                cut = min(rest, _i(x.get("qty")))
                rest -= cut
                if _i(x.get("qty")) - cut > 0:
                    new_links.append({**x, "qty": _i(x.get("qty")) - cut})
                continue
            new_links.append(x)
        await db[BUYER_SHORT].update_one({"id": s["id"]}, {
            "$inc": {"qty_resolved": -take},
            "$set": {"status": STATUS_OPEN, "resolution": "", "resolved_at": "", "resolved_by": "",
                     "resolution_links": new_links, "updated_at": _now()},
            "$push": {"history": {"at": _now(), "by": (actor or {}).get("name", "sistem"),
                                  "action": "reopen", "qty": take,
                                  "reason": reason or "pengiriman ulang dibatalkan/dikoreksi"}}})
        out["reopened"] += take
        out["shorts"].append({"short_number": s.get("short_number"), "qty": take})
        if left is not None:
            left -= take
    return out


async def _stock_back(db, item: dict, qty: int, ref: dict, actor: dict | None,
                      maklon: bool = False) -> int:
    """Barang yang tidak jadi sampai kembali ke stok FG (biaya = saat ia keluar)."""
    from core import production_qty_ledger as qled
    if qty <= 0 or not item.get("fg_issued_at"):
        return 0
    mat = await qled.resolve_fg_material(db, material_id=item.get("fg_material_id", ""),
                                         sku=item.get("sku", ""))
    if not mat:
        return 0
    exit_cost = await qled.exit_cost_of(db, material_id=mat["id"], shipment_item_id=item.get("id") or "",
                                        sku=mat.get("code", ""))
    posted = await qled.post_fg_accepted(
        db, material_id=mat["id"], qty=qty, ref=ref, actor=actor,
        meta={"material_code": mat.get("code", ""), "unit": "pcs", "type": "finished_goods"},
        exit_cost=exit_cost, skip_cost_layer=maklon)
    await db.rahaza_fg_movements.insert_one({
        "id": _id(), "sku_code": item.get("sku", ""), "movement_type": "IN", "qty": qty,
        "source": ref.get("source"), "ref_id": ref.get("short_id") or item.get("shipment_id"),
        "ref_number": ref.get("short_number") or ref.get("shipment_number", ""),
        "material_id": mat["id"], "location_id": posted["location_id"],
        "notes": ref.get("notes", ""), "created_by": (actor or {}).get("name", "sistem"),
        "created_at": _now()})
    await db.buyer_shipment_items.update_one(
        {"id": item["id"]}, {"$inc": {"fg_issued_qty": -qty}})
    return qty


async def _stock_out_again(db, item: dict, qty: int, ref: dict, actor: dict | None,
                           maklon: bool = False) -> int:
    """Selisih dibatalkan (barang ternyata sampai) → stok yang tadi dikembalikan keluar lagi."""
    from core import production_qty_ledger as qled
    if qty <= 0 or not item.get("fg_issued_at"):
        return 0
    mat = await qled.resolve_fg_material(db, material_id=item.get("fg_material_id", ""),
                                         sku=item.get("sku", ""))
    if not mat:
        return 0
    await qled.issue_fg(db, material_id=mat["id"], qty=qty, sku=item.get("sku", ""), ref=ref, actor=actor,
                        skip_cost=maklon)
    await db.rahaza_fg_movements.insert_one({
        "id": _id(), "sku_code": item.get("sku", ""), "movement_type": "OUT", "qty": qty,
        "source": ref.get("source"), "ref_id": ref.get("short_id") or item.get("shipment_id"),
        "ref_number": ref.get("short_number") or "", "material_id": mat["id"],
        "notes": ref.get("notes", ""), "created_by": (actor or {}).get("name", "sistem"),
        "created_at": _now()})
    await db.buyer_shipment_items.update_one({"id": item["id"]}, {"$inc": {"fg_issued_qty": qty}})
    return qty


class BuyerReceiptError(ValueError):
    """Koreksi qty diterima buyer ditolak (pesan siap tampil)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


async def apply_buyer_receipt(db, *, shipment: dict, item: dict, new_received: int,
                              actor: dict | None = None, reason: str = "") -> dict:
    """K17 butir 3 — qty diterima buyer dicatat / dikoreksi DUA ARAH.

    Aturan:
      · diterima ≤ dikirim (klaim asli SJ). Dulu 7 untuk kirim 5 diterima (w3 S11b).
      · TURUN  → selisih baru (atau selisih terbuka baris ini diperbesar), barang yang belum
                 sampai kembali ke stok, dokumen SJ = qty diterima.
      · NAIK   → selisih terbuka baris ini dikurangi/dibatalkan, stok yang tadi dikembalikan
                 keluar lagi, dokumen SJ naik lagi. Dulu `qty_received` 10 > `qty_shipped` 8,
                 SEL-BYR tetap terbuka dan stok +2 fantom (w3 S12b).
    Caller tetap menulis `qty_received` + riwayatnya.
    """
    new_received = _i(new_received)
    cur = _i(item.get("qty_shipped"))
    claimed = _i(item.get("qty_shipped_claimed")) or cur
    if new_received < 0:
        raise BuyerReceiptError("qty_received tidak boleh negatif")
    if new_received > claimed:
        raise BuyerReceiptError(
            f"Qty diterima ({new_received}) melebihi qty dikirim pada surat jalan ini "
            f"({claimed} pcs). Buyer tidak mungkin menerima lebih dari yang dikirim — periksa "
            f"angkanya, atau buat pengiriman baru bila memang ada barang tambahan.")
    out = {"buyer_short": None, "short_extended": 0, "short_cancelled": 0,
           "stock_returned": 0, "stock_reissued": 0}
    if new_received == cur:
        return out
    open_s = await db[BUYER_SHORT].find_one(
        {"shipment_item_id": item["id"], "status": STATUS_OPEN}, {"_id": 0})
    who = (actor or {}).get("name", "sistem")
    if new_received < cur:
        delta = cur - new_received
        if not open_s:
            out["buyer_short"] = await record_buyer_short(
                db, shipment=shipment, item=item, qty_shipped=cur, qty_received=new_received,
                actor=actor, reason=reason)
            return out
        await db[BUYER_SHORT].update_one({"id": open_s["id"]}, {
            "$inc": {"qty_short": delta},
            "$set": {"qty_received": new_received, "updated_at": _now()},
            "$push": {"history": {"at": _now(), "by": who, "action": "extend", "qty": delta,
                                  "reason": reason or "qty diterima buyer dikoreksi turun"}}})
        await db.buyer_shipment_items.update_one({"id": item["id"]}, {
            "$set": {"qty_shipped": new_received, "updated_at": _now()},
            "$inc": {"qty_short_open": delta},
            "$push": {"edit_history": {"old_qty": cur, "new_qty": new_received, "edited_by": who,
                                       "edited_at": _now(), "source": "buyer_receipt_variance",
                                       "reason": f"selisih {open_s.get('short_number')} +{delta} pcs"}}})
        out["short_extended"] = delta
        try:
            out["stock_returned"] = await _stock_back(db, item, delta, {
                "source": "buyer_short_reopen", "short_id": open_s["id"],
                "short_number": open_s.get("short_number"), "shipment_id": shipment.get("id"),
                "shipment_item_id": item["id"],
                "notes": f"Selisih buyer {open_s.get('short_number')} bertambah {delta} pcs"}, actor,
                maklon=shipment.get("business_type") == "maklon")
        except Exception:  # noqa: BLE001
            logger.exception("pengembalian stok selisih buyer %s gagal", open_s.get("short_number"))
        out["buyer_short"] = await db[BUYER_SHORT].find_one({"id": open_s["id"]}, {"_id": 0})
        return out

    need = new_received - cur
    open_qty = max(0, _i((open_s or {}).get("qty_short")) - _i((open_s or {}).get("qty_resolved")))
    if need > open_qty:
        raise BuyerReceiptError(
            f"Koreksi naik qty diterima maksimal {cur + open_qty} pcs: selisih buyer baris ini "
            + (f"yang masih terbuka hanya {open_qty} pcs" if open_s else "tidak ada yang terbuka")
            + " (selisih yang sudah dikirim ulang / diputuskan Keuangan tidak bisa dibatalkan dari sini).",
            409)
    left_short = _i(open_s.get("qty_short")) - need
    fully = left_short <= _i(open_s.get("qty_resolved"))
    st = (STATUS_CANCELLED if _i(open_s.get("qty_resolved")) == 0 else STATUS_RESOLVED) if fully else STATUS_OPEN
    await db[BUYER_SHORT].update_one({"id": open_s["id"]}, {
        "$set": {"qty_short": max(0, left_short), "qty_received": new_received, "status": st,
                 "resolution": ("dibatalkan" if st == STATUS_CANCELLED else open_s.get("resolution", "")),
                 "resolution_notes": (reason or "qty diterima dikoreksi naik — barang ternyata sampai")
                 if st == STATUS_CANCELLED else open_s.get("resolution_notes", ""),
                 "updated_at": _now()},
        "$push": {"history": {"at": _now(), "by": who, "action": "cancel_part", "qty": need,
                              "reason": reason or "qty diterima buyer dikoreksi naik"}}})
    await db.buyer_shipment_items.update_one({"id": item["id"]}, {
        "$set": {"qty_shipped": new_received, "updated_at": _now()},
        "$inc": {"qty_short_open": -need},
        "$push": {"edit_history": {"old_qty": cur, "new_qty": new_received, "edited_by": who,
                                   "edited_at": _now(), "source": "buyer_receipt_variance",
                                   "reason": f"selisih {open_s.get('short_number')} −{need} pcs (koreksi naik)"}}})
    out["short_cancelled"] = need
    try:
        out["stock_reissued"] = await _stock_out_again(db, item, need, {
            "source": "buyer_short_cancel", "short_id": open_s["id"],
            "short_number": open_s.get("short_number"), "shipment_id": shipment.get("id"),
            "shipment_item_id": item["id"],
            "notes": f"Selisih buyer {open_s.get('short_number')} dibatalkan {need} pcs (barang sampai)"},
            actor, maklon=shipment.get("business_type") == "maklon")
    except Exception:  # noqa: BLE001
        logger.exception("stok keluar ulang selisih buyer %s gagal", open_s.get("short_number"))
    out["buyer_short"] = await db[BUYER_SHORT].find_one({"id": open_s["id"]}, {"_id": 0})
    return out


async def resolve_buyer_short_manual(db, short_id: str, *, resolution: str, notes: str = "",
                                     actor: dict | None = None) -> dict:
    """Keputusan atas selisih buyer. `tanggungan_cmt`/`tanggungan_da` = barang
    dinyatakan HILANG ⇒ stok FG yang tadi dikembalikan dihapusbukukan supaya
    stok fisik tidak menggelembung, dan keputusan finance tercatat."""
    if resolution not in BUYER_RESOLUTIONS:
        raise ValueError(f"resolution tidak valid: {resolution}")
    s = await db[BUYER_SHORT].find_one({"id": short_id}, {"_id": 0})
    if not s:
        raise LookupError("catatan selisih buyer tidak ditemukan")
    if s.get("status") != STATUS_OPEN:
        raise ValueError(f"selisih {s.get('short_number')} sudah berstatus '{s.get('status')}'")
    from core import production_qty_ledger as qled

    open_qty = max(0, _i(s.get("qty_short")) - _i(s.get("qty_resolved")))
    is_loss = resolution in ("tanggungan_cmt", "tanggungan_da")
    new_status = STATUS_CANCELLED if resolution == "dibatalkan" else STATUS_RESOLVED
    upd = {
        "$set": {"status": new_status, "resolution": resolution, "resolution_notes": notes,
                 "resolved_at": _now(), "resolved_by": (actor or {}).get("name", "sistem"),
                 "updated_at": _now()},
        "$push": {"history": {"at": _now(), "by": (actor or {}).get("name", "sistem"),
                              "action": "resolve_manual", "qty": open_qty,
                              "resolution": resolution, "reason": notes}},
    }
    if resolution != "dibatalkan":
        upd["$inc"] = {"qty_resolved": open_qty}
    if is_loss:
        upd["$set"].update({"finance_decision": resolution,
                            "finance_decided_by": (actor or {}).get("name", "sistem"),
                            "finance_decided_at": _now()})
    await db[BUYER_SHORT].update_one({"id": short_id}, upd)

    writeoff = None
    if is_loss and s.get("stock_returned_at") and not s.get("stock_writeoff_at"):
        try:
            mat = await qled.resolve_fg_material(db, sku=s.get("sku", ""))
            if mat:
                await qled.issue_fg(
                    db, material_id=mat["id"], qty=open_qty, sku=s.get("sku", ""),
                    ref={"source": "buyer_short_writeoff", "short_id": short_id,
                         "short_number": s.get("short_number"), "resolution": resolution,
                         "po_id": s.get("po_id"), "po_number": s.get("po_number")},
                    actor=actor)
                await db.rahaza_fg_movements.insert_one({
                    "id": _id(), "sku_code": s.get("sku", ""), "movement_type": "OUT",
                    "qty": open_qty, "source": "buyer_short_writeoff",
                    "ref_id": short_id, "ref_number": s.get("short_number"),
                    "material_id": mat["id"],
                    "notes": (f"Selisih buyer {s.get('short_number')} dinyatakan hilang "
                              f"({BUYER_RESOLUTIONS[resolution]}) — stok FG dihapusbukukan"),
                    "created_by": (actor or {}).get("name", "sistem"), "created_at": _now()})
                await db[BUYER_SHORT].update_one({"id": short_id},
                                                 {"$set": {"stock_writeoff_at": _now()}})
                writeoff = open_qty
        except Exception as e:  # noqa: BLE001
            logger.exception("hapus buku stok FG selisih buyer gagal")
            await db[BUYER_SHORT].update_one(
                {"id": short_id}, {"$set": {"stock_writeoff_error": str(e)}})
    out = await db[BUYER_SHORT].find_one({"id": short_id}, {"_id": 0})
    if out is not None:
        out["stock_writeoff_qty"] = writeoff
    return out


async def list_buyer_shorts(db, *, status: str = "open", po_id: str = "",
                            shipment_id: str = "", limit: int = 300) -> dict:
    q: dict = {}
    if status and status != "all":
        q["status"] = status
    if po_id:
        q["po_id"] = po_id
    if shipment_id:
        q["shipment_id"] = shipment_id
    rows = await db[BUYER_SHORT].find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    for r in rows:
        r["qty_open"] = max(0, _i(r.get("qty_short")) - _i(r.get("qty_resolved")))
    return {
        "items": rows, "total": len(rows),
        "total_qty_short": sum(_i(r.get("qty_short")) for r in rows),
        "total_qty_open": sum(_i(r.get("qty_open")) for r in rows),
        "resolutions": BUYER_RESOLUTIONS,
    }


async def buyer_short_totals(db, *, po_ids: list | None = None) -> dict:
    """{po_id: {qty_short_open, qty_short_resolved, docs}} untuk laporan selisih."""
    q = {"po_id": {"$in": list(po_ids)}} if po_ids else {}
    rows = await db[BUYER_SHORT].find(q, {"_id": 0}).to_list(None)
    out: dict = {}
    for r in rows:
        p = out.setdefault(r.get("po_id") or "", {
            "qty_short_open": 0, "qty_short_resolved": 0, "docs": 0, "items": []})
        open_qty = max(0, _i(r.get("qty_short")) - _i(r.get("qty_resolved")))
        if r.get("status") == STATUS_OPEN:
            p["qty_short_open"] += open_qty
        if r.get("status") != STATUS_CANCELLED:
            p["qty_short_resolved"] += _i(r.get("qty_resolved"))
        p["docs"] += 1
        p["items"].append({"short_number": r.get("short_number"), "sku": r.get("sku"),
                           "qty_short": _i(r.get("qty_short")), "qty_open": open_qty,
                           "status": r.get("status"), "resolution": r.get("resolution"),
                           "po_item_id": r.get("po_item_id")})
    return out
