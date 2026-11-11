"""Hutang usaha — SATU sumber untuk tagihan pemasok (AP) dan tagihan CMT (2026-11-04, audit Keuangan).

Kenapa ada: audit menemukan 6 rumus "hutang belum dibayar" di 6 layar (Rekap, Aging Hutang, Faktur
Supplier, Nota Debit, Prediksi Kas, Diskon Pembelian) dan tak satu pun menghitung tagihan CMT
(`dewi_cmt_payments`). Umur Hutang juga hanya membaca 500 faktur pertama. Owner (4 Nov 2026):
tagihan pemasok & CMT satu daftar "Hutang Pemasok & CMT" (11 Nov 2026: menu "Hutang", satu daftar tanpa tab).

Aturan:
  · AP terbuka  = `rahaza_ap_invoices` status sent/partial_paid/overdue dengan sisa > 0 (draf bukan hutang).
  · CMT terbuka = `dewi_cmt_payments` bukan cancelled/void/paid dengan sisa > 0. Tagihan CMT LAHIR
    berstatus draft lalu langsung dijurnal (production_maklon_bridge) → draft = jurnalnya gagal, hutangnya
    tetap nyata, jadi ikut sebagai "belum dijurnal".
    `gl_posted` menandai yang sudah dijurnal; hanya yang sudah dijurnal masuk total "hutang tercatat"
    supaya sama dengan buku besar (yang belum dijurnal ditampilkan terpisah).
"""
from __future__ import annotations

from datetime import date, datetime

AP_OPEN = ("sent", "partial_paid", "overdue")
CMT_CLOSED = ("cancelled", "void", "paid")
BUCKETS = ("current", "1_30", "31_60", "61_90", "90_plus")


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso(v) -> str:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v or "")[:10]


def _cmt_amount(p: dict) -> float:
    for k in ("net_amount", "total_amount", "subtotal"):
        if p.get(k) is not None:
            return _num(p.get(k))
    return 0.0


def ap_row(r: dict) -> dict:
    total = _num(r.get("total"))
    paid = _num(r.get("paid_amount"))
    bal = _num(r.get("balance")) if r.get("balance") is not None else max(total - paid, 0.0)
    return {
        "kind": "ap", "id": r.get("id"), "number": r.get("invoice_number"),
        "vendor_name": r.get("vendor_name") or "(tanpa nama)", "issue_date": _iso(r.get("issue_date")),
        "due_date": _iso(r.get("due_date")), "total": round(total, 2), "paid": round(paid, 2),
        "balance": round(bal, 2), "status": (r.get("status") or "").lower(),
        "gl_posted": bool(r.get("gl_je_id")) or (r.get("status") or "").lower() != "draft",
        "reference": ", ".join(r.get("po_numbers") or r.get("gr_numbers") or []),
    }


def cmt_row(p: dict) -> dict:
    total = _cmt_amount(p)
    paid = _num(p.get("paid_amount"))
    out = _num(p.get("outstanding_amount")) if p.get("outstanding_amount") is not None else total - paid
    issue = _iso(p.get("issue_date") or p.get("period_end") or p.get("created_at"))
    return {
        "kind": "cmt", "id": p.get("id"), "number": p.get("payment_code"),
        "vendor_name": p.get("cmt_name") or p.get("vendor_name") or "(tanpa nama)", "issue_date": issue,
        "due_date": _iso(p.get("due_date")) or issue, "total": round(total, 2), "paid": round(paid, 2),
        "balance": round(max(out, 0.0), 2), "status": (p.get("status") or "").lower(),
        "gl_posted": bool(p.get("gl_je_id")),
        "reference": p.get("po_number") or p.get("source_receipt_code") or "",
    }


async def open_payable_rows(db, include_cmt: bool = True, entity: str | None = None) -> list[dict]:
    """Semua tagihan yang masih harus dibayar (tanpa batas jumlah baris).

    Tahap 8: setiap baris membawa `entity` (CV pemilik hutang). Faktur pemasok = field `entity` dokumen
    (lama = DA); tagihan CMT = jenis PO (maklon → CV Sukma, internal/tanpa jenis → DA).
    `entity` DA|SMU menyaring satu buku; None/ALL = semua."""
    from core.entities import entity_of_doc, entity_for_business_type, matches_entity, DA
    rows = []
    async for r in db.rahaza_ap_invoices.find({"status": {"$in": list(AP_OPEN)}}, {"_id": 0}):
        rows.append({**ap_row(r), "entity": entity_of_doc(r)})
    if include_cmt:
        bills = [p async for p in db.dewi_cmt_payments.find({"status": {"$nin": list(CMT_CLOSED)}}, {"_id": 0})]
        po_ids = sorted({b.get("po_id") for b in bills if b.get("po_id")})
        bt = {}
        if po_ids:
            async for po in db.production_pos.find({"id": {"$in": po_ids}}, {"_id": 0, "id": 1, "business_type": 1}):
                bt[po["id"]] = po.get("business_type")
        for p in bills:
            ent = p.get("entity") or (entity_for_business_type(bt.get(p.get("po_id"))) if p.get("po_id") else DA)
            rows.append({**cmt_row(p), "entity": ent})
    return [r for r in rows if r["balance"] > 0.5 and matches_entity(r.get("entity"), entity)]


def days_overdue(due_iso: str, today: date) -> int:
    try:
        return (today - date.fromisoformat(due_iso[:10])).days
    except (TypeError, ValueError):
        return 0


def bucket_of(days: int) -> str:
    if days <= 0:
        return "current"
    if days <= 30:
        return "1_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "90_plus"


def aging(rows: list[dict], today: date, recorded_only: bool = True) -> dict:
    """Kelompok umur + rincian. `recorded_only` = hanya yang sudah dijurnal (sama dengan buku besar)."""
    buckets = {b: 0.0 for b in BUCKETS}
    details, unposted = [], []
    for r in rows:
        d = days_overdue(r["due_date"], today)
        item = {**r, "days_overdue": d, "bucket": bucket_of(d)}
        if recorded_only and not r["gl_posted"]:
            unposted.append(item)
            continue
        buckets[item["bucket"]] += r["balance"]
        details.append(item)
    details.sort(key=lambda x: (-x["days_overdue"], -x["balance"]))
    return {
        "buckets": {k: round(v) for k, v in buckets.items()},
        "total": round(sum(buckets.values())),
        "overdue": round(sum(v for k, v in buckets.items() if k != "current")),
        "details": details,
        "unposted": unposted,
        "unposted_total": round(sum(r["balance"] for r in unposted)),
    }
