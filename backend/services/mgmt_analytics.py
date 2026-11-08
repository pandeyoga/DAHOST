"""
services/mgmt_analytics.py — helper agregasi SSOT untuk ringkasan & laporan.

MENGAPA ADA
-----------
Laporan manajemen (`routes/rahaza_reports.py`) dan laporan maklon
(`routes/dewi_phase7_reports.py`) dulu masing-masing menghitung sendiri dari
koleksi yang berbeda-beda — sebagian sudah mati. File ini menjadi SATU tempat
pengambilan cakupan data (PO → item → job → item job → buku kuantitas) supaya
tidak lahir sumber kebenaran kedua.

ATURAN
------
* Kuantitas SELALU lewat `core.production_qty_ledger.ledger_view()`.
* Domain dipisah tegas: `internal` (produksi internal DA) vs `maklon`.
* Fungsi di sini HANYA membaca (tidak pernah menulis).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException

from core.production_qty_ledger import ledger_view
from utils.waktu import today_wib

MAX_DOCS = 20000

# Ember status PO (lihat routes/shared.PO_STATUSES). Dibandingkan lowercase.
PO_DRAFT = {"draft"}
PO_CONFIRMED = {"confirmed"}
PO_DONE = {"closed", "completed", "done"}
PO_CANCELLED = {"cancelled", "canceled"}

LEDGER_KEYS = ("produced", "declared", "accepted", "reject", "rework_open",
               "repaired", "scrap", "short_open")


def today() -> date:
    return today_wib()


def norm_domain(v: str | None) -> str:
    v = (v or "all").strip().lower()
    return v if v in ("internal", "maklon", "all") else "all"


def domain_label(domain: str) -> str:
    return {
        "internal": "Produksi Internal DA",
        "maklon": "Produksi Maklon",
        "all": "Gabungan (Internal DA + Maklon)",
    }[norm_domain(domain)]


def domain_q(domain: str, field: str = "business_type") -> dict:
    """Filter domain untuk koleksi yang punya `business_type`."""
    domain = norm_domain(domain)
    if domain == "internal":
        return {field: "internal"}
    if domain == "maklon":
        return {field: {"$ne": "internal"}}
    return {}


def resolve_period(date_from: str | None, date_to: str | None,
                   default_days: int = 30) -> tuple[str, str]:
    """Tentukan rentang tanggal laporan.

    Tanggal yang DIKIRIM selalu divalidasi — walau hanya salah satu sisi. Dulu
    validasi hanya jalan bila keduanya ada, sehingga `?date_from=abc` diam-diam
    diabaikan dan laporan tetap 200 dengan periode bawaan (menyesatkan).
    """
    def _valid(v, name):
        if v in (None, ""):
            return None
        try:
            datetime.fromisoformat(str(v))
        except (ValueError, TypeError):
            raise HTTPException(400, f"Format {name} tidak valid. Gunakan YYYY-MM-DD.")
        return str(v)

    date_from = _valid(date_from, "date_from")
    date_to = _valid(date_to, "date_to")
    t = today()
    if date_from and date_to:
        if date_to < date_from:
            raise HTTPException(400, "date_to tidak boleh lebih awal dari date_from.")
        return date_from, date_to
    if date_from:
        return date_from, max(date_from, t.isoformat())
    if date_to:
        d = datetime.fromisoformat(date_to).date()
        return (d - timedelta(days=default_days - 1)).isoformat(), date_to
    return (t - timedelta(days=default_days - 1)).isoformat(), t.isoformat()


def as_iso_date(v) -> str:
    """Samakan tanggal dari datetime / date / string ISO → 'YYYY-MM-DD'."""
    if not v:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)[:10]


def in_period(v, start: str, end: str) -> bool:
    d = as_iso_date(v)
    return bool(d) and start <= d <= end


def i(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def po_buckets(pos: list) -> dict:
    b = {"total": len(pos), "draft": 0, "confirmed": 0, "running": 0, "done": 0, "cancelled": 0}
    for p in pos:
        s = (p.get("status") or "").strip().lower()
        if s in PO_DRAFT:
            b["draft"] += 1
        elif s in PO_CONFIRMED:
            b["confirmed"] += 1
        elif s in PO_CANCELLED:
            b["cancelled"] += 1
        elif s in PO_DONE:
            b["done"] += 1
        else:
            b["running"] += 1
    return b


async def domain_scope(db, domain: str) -> dict:
    """Ambil sekali: PO (per domain), item PO, job, item job, buku kuantitas.

    Buku kuantitas di-dedup per `po_item_id` supaya satu item PO dengan beberapa
    job item tidak dihitung dua kali (aturan sama seperti `po_ledger_totals`).
    """
    domain = norm_domain(domain)
    pos = await db.production_pos.find(
        domain_q(domain),
        {"_id": 0, "id": 1, "po_number": 1, "status": 1, "business_type": 1,
         "customer_name": 1, "buyer_id": 1, "vendor_id": 1, "vendor_name": 1,
         "po_date": 1, "deadline": 1, "delivery_deadline": 1, "created_at": 1},
    ).to_list(MAX_DOCS)
    po_ids = [p["id"] for p in pos]
    items = await db.po_items.find(
        {"po_id": {"$in": po_ids}},
        {"_id": 0, "id": 1, "po_id": 1, "po_number": 1, "sku": 1, "product_name": 1,
         "size": 1, "color": 1, "qty": 1, "model_id": 1,
         "selling_price_snapshot": 1, "cmt_price_snapshot": 1},
    ).to_list(MAX_DOCS) if po_ids else []
    jobs = await db.production_jobs.find(
        {"po_id": {"$in": po_ids}},
        {"_id": 0, "id": 1, "job_number": 1, "po_id": 1, "po_number": 1, "status": 1,
         "vendor_id": 1, "vendor_name": 1, "business_type": 1, "parent_job_id": 1,
         "deadline": 1, "delivery_deadline": 1, "created_at": 1, "customer_name": 1},
    ).to_list(MAX_DOCS) if po_ids else []
    job_ids = [j["id"] for j in jobs]
    job_items = await db.production_job_items.find(
        {"job_id": {"$in": job_ids}}, {"_id": 0},
    ).to_list(MAX_DOCS) if job_ids else []

    per_item: dict = {}
    per_job: dict = {}
    for ji in job_items:
        v = ledger_view(ji)
        key = ji.get("po_item_id") or ji.get("id")
        p = per_item.setdefault(key, {k: 0 for k in LEDGER_KEYS})
        jrow = per_job.setdefault(ji.get("job_id"), {k: 0 for k in LEDGER_KEYS} | {"ordered": 0})
        jrow["ordered"] += i(ji.get("ordered_qty"))
        for k, src in (("produced", "produced_qty"), ("declared", "qty_declared"),
                       ("accepted", "qty_accepted"), ("reject", "qty_reject"),
                       ("rework_open", "qty_rework_open"), ("repaired", "qty_repaired"),
                       ("scrap", "qty_scrap"), ("short_open", "qty_short_open")):
            p[k] += v[src]
            jrow[k] += v[src]
    ledger = {k: sum(p[k] for p in per_item.values()) for k in LEDGER_KEYS}

    items_by_po: dict = {}
    for it in items:
        items_by_po.setdefault(it["po_id"], []).append(it)
    jobs_by_po: dict = {}
    for j in jobs:
        jobs_by_po.setdefault(j.get("po_id"), []).append(j)

    return {
        "domain": domain,
        "pos": pos, "po_ids": po_ids, "items": items, "items_by_po": items_by_po,
        "jobs": jobs, "job_ids": job_ids, "job_items": job_items,
        "jobs_by_po": jobs_by_po,
        "ledger": ledger, "ledger_per_item": per_item, "ledger_per_job": per_job,
        "po_by_id": {p["id"]: p for p in pos},
        "job_by_id": {j["id"]: j for j in jobs},
        "item_by_id": {it["id"]: it for it in items},
    }


async def buyer_dispatch_map(db, po_ids: list) -> dict:
    """{po_id: {'qty': n, 'last_dispatch': 'YYYY-MM-DD', 'shipments': n}} dari SSOT kirim buyer."""
    if not po_ids:
        return {}
    ships = await db.buyer_shipments.find(
        {"po_id": {"$in": po_ids}}, {"_id": 0, "id": 1, "po_id": 1},
    ).to_list(MAX_DOCS)
    ship_po = {s["id"]: s.get("po_id") for s in ships}
    items = await db.buyer_shipment_items.find(
        {"shipment_id": {"$in": list(ship_po.keys())}},
        {"_id": 0, "shipment_id": 1, "qty_shipped": 1, "dispatch_date": 1},
    ).to_list(MAX_DOCS) if ship_po else []
    out: dict = {}
    for s in ships:
        row = out.setdefault(s.get("po_id"), {"qty": 0, "last_dispatch": "", "shipments": 0})
        row["shipments"] += 1
    for it in items:
        po_id = ship_po.get(it.get("shipment_id"))
        if not po_id:
            continue
        row = out.setdefault(po_id, {"qty": 0, "last_dispatch": "", "shipments": 0})
        row["qty"] += i(it.get("qty_shipped"))
        d = as_iso_date(it.get("dispatch_date"))
        if d and d > row["last_dispatch"]:
            row["last_dispatch"] = d
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 8 Nov 2026 (keputusan owner): SATU sumber "output produksi" & "ketepatan kirim" untuk
# Ringkasan Bisnis (`/api/rahaza/management/overview`, `/on-time-delivery`) DAN Dashboard Eksekutif
# (`/api/dashboard`, `/api/dashboard/analytics`). Dashboard dulu membaca `rahaza_wip_events` dan koleksi pesanan
# lama `rahaza_orders` (kosong), Ringkasan Bisnis membaca `production_progress` + `cmt_receipts` → angka berbeda.
# ─────────────────────────────────────────────────────────────────────────────
async def output_sources(db, sc: dict) -> dict:
    """Catatan output produksi cakupan `domain_scope`: progres internal (`production_progress`, per job) +
    penerimaan barang dari CMT (`cmt_receipts`, per PO). Dibaca sekali, dijumlah per periode oleh pemanggil."""
    progress = await db.production_progress.find(
        {"job_id": {"$in": sc["job_ids"]}}, {"_id": 0, "job_id": 1, "completed_quantity": 1,
                                             "progress_date": 1},
    ).to_list(MAX_DOCS) if sc["job_ids"] else []
    receipts = await db.cmt_receipts.find(
        {"po_id": {"$in": sc["po_ids"]}},
        {"_id": 0, "id": 1, "po_id": 1, "receipt_date": 1, "status": 1,
         "total_actual": 1, "total_rejected": 1, "total_qty_short": 1},
    ).to_list(MAX_DOCS) if sc["po_ids"] else []
    return {"progress": progress, "receipts": receipts}


def output_in_period(src: dict, start: str, end: str) -> dict:
    """Output pada [start, end] (tanggal ISO, inklusif): progres internal + qty diterima dari CMT."""
    prog = sum(i(r.get("completed_quantity")) for r in src.get("progress") or []
               if in_period(r.get("progress_date"), start, end))
    recv = sum(i(r.get("total_actual")) for r in src.get("receipts") or []
               if in_period(r.get("receipt_date"), start, end))
    return {"progress": prog, "received": recv, "total": prog + recv}


async def on_time_stats(db, sc: dict, days: int = 90) -> dict:
    """Ketepatan kirim: tanggal dispatch terakhir ke buyer (dalam `days` hari) vs deadline PO.
    Hanya PO yang punya deadline DAN sudah dikirim yang dinilai."""
    since = (today() - timedelta(days=days)).isoformat()
    ships = await db.buyer_shipments.find(
        {"po_id": {"$in": sc["po_ids"]}}, {"_id": 0, "id": 1, "po_id": 1},
    ).to_list(MAX_DOCS) if sc["po_ids"] else []
    ship_po = {s["id"]: s.get("po_id") for s in ships}
    items = await db.buyer_shipment_items.find(
        {"shipment_id": {"$in": list(ship_po.keys())}},
        {"_id": 0, "shipment_id": 1, "dispatch_date": 1, "qty_shipped": 1},
    ).to_list(MAX_DOCS) if ship_po else []

    last_dispatch: dict = {}
    for it in items:
        d = as_iso_date(it.get("dispatch_date"))
        if not d or d < since:
            continue
        po_id = ship_po.get(it.get("shipment_id"))
        if not po_id:
            continue
        if d > last_dispatch.get(po_id, ""):
            last_dispatch[po_id] = d

    total = on_time = 0
    late_rows = []
    for po_id, d in last_dispatch.items():
        po = sc["po_by_id"].get(po_id) or {}
        due = as_iso_date(po.get("deadline") or po.get("delivery_deadline"))
        if not due:
            continue  # tanpa deadline → tidak bisa dinilai (jangan dipaksa)
        total += 1
        if d <= due:
            on_time += 1
        else:
            late_rows.append({"po_number": po.get("po_number"), "deadline": due, "dispatch": d})
    rate = (on_time / total * 100) if total else 0.0
    return {"total_po": total, "on_time": on_time, "late": total - on_time, "rate_pct": round(rate, 1),
            "late_examples": late_rows[:5], "shipments": len(ships), "shipment_items": len(items)}
