"""Finance aggregates for AI endpoints.

Replaces fetch-and-sum-in-Python patterns with MongoDB aggregation pipelines.
All functions return small, AI-ready dicts.

RC-28 (SSOT MASTER REPAIR PLAN PART 4):
  - rahaza_invoices (phantom) -> rahaza_ar_invoices (field: issue_date/total/status)
  - rahaza_payments (phantom) -> rahaza_cash_movements direction 'in'
    category ar_payment/ar_receipt (pembayaran masuk nyata)

2026-11-02 (audit A §6.1/§6.3, perbaikan konteks AI yang pasti salah):
  - Faktur AR berstatus draft / batal / void TIDAK dihitung (dulu semua status ikut,
    sehingga draft Rp5 jt & faktur batal terbaca sebagai pendapatan).
  - Tanggal faktur = `issue_date`, atau `invoice_date` untuk faktur maklon; nilai =
    `total`, atau `total_amount` untuk faktur maklon (dua skema yang hidup di data).
  - Maklon TIDAK lagi dijumlahkan dua kali di forecast: faktur maklon sudah ada di
    `rahaza_ar_invoices` (`source_module='maklon_po'`), jadi `maklon_rp` hanya rincian.
  - Live selling = ESTIMASI marketing (D1): diberi label estimasi dan TIDAK masuk
    `total_rp`. Data nyata menyimpan `session_date` sebagai datetime dan nilai di
    `revenue` (bukan `gmv`), sehingga dulu selalu terbaca 0.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Status faktur yang BUKAN pendapatan (belum terbit / dibatalkan).
EXCLUDED_AR_STATUSES = ["draft", "cancelled", "canceled", "void", "voided"]

_AR_DATE = {"$ifNull": ["$issue_date", "$invoice_date"]}
_AR_AMOUNT = {"$toDouble": {"$ifNull": ["$total", {"$ifNull": ["$total_amount", 0]}]}}

LIVE_ESTIMATE_NOTE = "ESTIMASI marketing (bukan angka akuntansi, tidak masuk GL)"


def _ar_valid_match(since_date: str) -> dict:
    """Filter faktur AR sah sejak tanggal (YYYY-MM-DD), dua skema tanggal."""
    return {
        "status": {"$nin": EXCLUDED_AR_STATUSES},
        "$or": [
            {"issue_date": {"$gte": since_date}},
            {"issue_date": {"$in": [None, ""]}, "invoice_date": {"$gte": since_date}},
        ],
    }


def _live_match(since: datetime) -> dict:
    """`session_date` bisa datetime (data nyata) atau string YYYY-MM-DD (skema lama)."""
    return {"$or": [
        {"session_date": {"$gte": since}},
        {"session_date": {"$gte": since.strftime("%Y-%m-%d")}},
    ]}


_LIVE_VALUE = {"$toDouble": {"$ifNull": ["$gmv", {"$ifNull": ["$revenue", 0]}]}}


async def daily_finance_metrics(db, *, since_iso: str) -> dict:
    """Return invoice rollup since `since_iso` (faktur sah saja).

    Output keys: invoice_count, paid_count, total_invoiced_rp.
    """
    pipeline = [
        {"$match": _ar_valid_match(since_iso[:10])},
        {"$group": {
            "_id": None,
            "invoice_count": {"$sum": 1},
            "paid_count": {
                "$sum": {"$cond": [{"$eq": ["$status", "paid"]}, 1, 0]},
            },
            "total_invoiced_rp": {"$sum": _AR_AMOUNT},
        }},
    ]
    rows = await db.rahaza_ar_invoices.aggregate(pipeline).to_list(1)
    if not rows:
        return {"invoice_count": 0, "paid_count": 0, "total_invoiced_rp": 0.0}
    r = rows[0]
    return {
        "invoice_count": int(r.get("invoice_count") or 0),
        "paid_count": int(r.get("paid_count") or 0),
        "total_invoiced_rp": float(r.get("total_invoiced_rp") or 0.0),
    }


async def daily_live_session_revenue(db, *, since: datetime) -> dict:
    """ESTIMASI omzet live marketing sejak `since` (D1: bukan pendapatan akuntansi)."""
    pipeline = [
        {"$match": _live_match(since)},
        {"$group": {
            "_id": None,
            "session_count": {"$sum": 1},
            "revenue_rp": {"$sum": _LIVE_VALUE},
        }},
    ]
    rows = await db.marketing_live_sessions.aggregate(pipeline).to_list(1)
    if not rows:
        return {"session_count": 0, "revenue_rp": 0.0, "is_estimate": True, "note": LIVE_ESTIMATE_NOTE}
    r = rows[0]
    return {
        "session_count": int(r.get("session_count") or 0),
        "revenue_rp": float(r.get("revenue_rp") or 0.0),
        "is_estimate": True,
        "note": LIVE_ESTIMATE_NOTE,
    }


async def monthly_revenue_rollup(
    db, *, since_iso: str, lmo_adapter=None, since_datetime: datetime,
) -> list[dict]:
    """Rekap pendapatan bulanan untuk forecast.

    Returns: list[{month, invoice_rp, maklon_rp, total_rp, live_estimasi_rp, live_is_estimate}]
    sorted asc. `total_rp` = pendapatan akuntansi (= invoice_rp). `maklon_rp` adalah
    BAGIAN dari invoice_rp (rincian). `live_estimasi_rp` = estimasi marketing, tidak
    dijumlahkan. `lmo_adapter` tidak dipakai lagi (dulu sumber hitungan ganda maklon);
    parameter dipertahankan agar pemanggil lama tetap jalan.
    """
    inv_pipeline = [
        {"$match": _ar_valid_match(since_iso[:10])},
        {"$project": {
            "_id": 0,
            "month": {"$substr": [_AR_DATE, 0, 7]},
            "total": _AR_AMOUNT,
            "is_maklon": {"$eq": ["$source_module", "maklon_po"]},
        }},
        {"$group": {
            "_id": "$month",
            "total": {"$sum": "$total"},
            "maklon": {"$sum": {"$cond": ["$is_maklon", "$total", 0]}},
        }},
    ]
    inv_rows = await db.rahaza_ar_invoices.aggregate(inv_pipeline).to_list(60)

    live_month = {"$cond": [
        {"$eq": [{"$type": "$session_date"}, "date"]},
        {"$dateToString": {"format": "%Y-%m", "date": "$session_date", "timezone": "Asia/Jakarta"}},
        {"$substr": [{"$toString": "$session_date"}, 0, 7]},
    ]}
    live_pipeline = [
        {"$match": _live_match(since_datetime)},
        {"$project": {"_id": 0, "month": live_month, "revenue": _LIVE_VALUE}},
        {"$group": {"_id": "$month", "total": {"$sum": "$revenue"}}},
    ]
    live_rows = await db.marketing_live_sessions.aggregate(live_pipeline).to_list(60)

    monthly: dict[str, dict[str, float]] = {}

    def _slot(m: str) -> dict:
        return monthly.setdefault(m, {"invoice": 0.0, "maklon": 0.0, "live": 0.0})

    for r in inv_rows:
        m = r.get("_id") or ""
        if m:
            _slot(m)["invoice"] = float(r.get("total") or 0)
            _slot(m)["maklon"] = float(r.get("maklon") or 0)
    for r in live_rows:
        m = r.get("_id") or ""
        if m:
            _slot(m)["live"] = float(r.get("total") or 0)

    return [
        {
            "month": m,
            "invoice_rp": round(v["invoice"]),
            "maklon_rp": round(v["maklon"]),
            "total_rp": round(v["invoice"]),
            "live_estimasi_rp": round(v["live"]),
            "live_is_estimate": True,
        }
        for m, v in sorted(monthly.items())
    ]


async def fraud_detection_signals(db, *, since_iso: str, since_dt: datetime) -> dict:
    """Compute statistical signals for fraud detection (no full-doc fetch)."""
    match = _ar_valid_match(since_iso[:10])
    # Invoice basic stats via aggregation
    inv_stats_pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "count": {"$sum": 1},
            "avg": {"$avg": _AR_AMOUNT},
            "stdDev": {"$stdDevPop": _AR_AMOUNT},
        }},
    ]
    inv_stats_rows = await db.rahaza_ar_invoices.aggregate(inv_stats_pipeline).to_list(1)
    stats = inv_stats_rows[0] if inv_stats_rows else {"count": 0, "avg": 0.0, "stdDev": 0.0}
    avg = float(stats.get("avg") or 0)
    std = float(stats.get("stdDev") or 0)

    # Outlier invoices (>= 3 sigma) — server-side filter, hard limit
    outliers: list[dict] = []
    if std > 0:
        threshold_low = avg - 3 * std
        threshold_high = avg + 3 * std
        cursor = db.rahaza_ar_invoices.aggregate([
            {"$match": match},
            {"$project": {"_id": 0, "id": 1, "status": 1, "amount": _AR_AMOUNT}},
            {"$match": {"$or": [{"amount": {"$lt": threshold_low}}, {"amount": {"$gt": threshold_high}}]}},
            {"$limit": 20},
        ])
        async for inv in cursor:
            outliers.append({
                "type": "invoice_anomaly",
                "id": inv.get("id"),
                "total": float(inv.get("amount") or 0),
                "expected_range": f"{round(avg - 2 * std):,} - {round(avg + 2 * std):,}",
            })

    # RC-28: pembayaran masuk nyata = rahaza_cash_movements direction 'in'
    payment_count = await db.rahaza_cash_movements.count_documents({
        "direction": "in",
        "category": {"$in": ["ar_payment", "ar_receipt"]},
        "date": {"$gte": since_iso[:10]},
    })

    # Large stock adjustments — only field projections + DB sort
    adj_pipeline = [
        {"$match": {
            "created_at": {"$gte": since_dt},
            "movement_type": {"$in": ["adjustment", "reset", "outbound_rm", "inbound_rm"]},
        }},
        {"$project": {
            "_id": 0,
            "id": 1, "sku": 1, "material_code": 1,
            "qty": 1, "movement_type": 1,
            "abs_qty": {"$abs": {"$toDouble": {"$ifNull": ["$qty", 0]}}},
        }},
        {"$sort": {"abs_qty": -1}},
        {"$limit": 20},
    ]
    adj_rows = await db.rahaza_material_movements.aggregate(adj_pipeline).to_list(20)

    return {
        "invoice_stats": {
            "count": int(stats.get("count") or 0),
            "avg": round(avg),
            "std": round(std),
        },
        "top_invoice_outliers": outliers,
        "payment_count": payment_count,
        "top_stock_adjustments": [
            {
                "id": a.get("id"),
                "sku": a.get("sku") or a.get("material_code"),
                "qty": float(a.get("qty") or 0),
                "movement_type": a.get("movement_type"),
            }
            for a in adj_rows
        ],
    }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
