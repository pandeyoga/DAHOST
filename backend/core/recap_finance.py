"""FIN-01: agregasi Rekap Keuangan membaca kolom yang benar-benar ditulis (date/total/balance)."""


def invoice_total_expr():
    return {"$ifNull": ["$total_amount", {"$ifNull": ["$total", 0]}]}


def open_balance_expr():
    return {"$ifNull": ["$balance", {"$ifNull": ["$amount_due", {"$ifNull": ["$outstanding_amount", 0]}]}]}


def payment_date_match(date_filter: dict) -> dict:
    if not date_filter:
        return {}
    return {"$or": [{"date": date_filter}, {"date": {"$exists": False}, "payment_date": date_filter}]}


def recap_open_statuses(canonical: list) -> list:
    return list(dict.fromkeys(list(canonical) + ["unpaid", "partial"]))


async def sum_invoices(coll, date_filter: dict, excluded: list):
    match = {"status": {"$nin": excluded}}
    if date_filter:
        match["issue_date"] = date_filter
    agg = await coll.aggregate([
        {"$match": match},
        {"$group": {"_id": None, "total": {"$sum": invoice_total_expr()}, "count": {"$sum": 1}}},
    ]).to_list(1)
    return (agg[0]["total"], agg[0]["count"]) if agg else (0, 0)


async def sum_payments(coll, date_filter: dict):
    agg = await coll.aggregate([
        {"$match": payment_date_match(date_filter)},
        {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$amount", 0]}}}},
    ]).to_list(1)
    return agg[0]["total"] if agg else 0


async def sum_direct_sale_receipts(db, date_filter: dict):
    """2026-11-02 (K20): kas masuk Penjualan Langsung (Portal Penjualan › bayar nota).

    Jalur itu (`routes/sales_direct._apply_ar_payment`) menulis mutasi kas `ar_payment` + jurnal,
    tetapi TIDAK menulis `rahaza_ar_payments`, sehingga Rekap tidak pernah menghitungnya. Dihitung:
    mutasi masuk kategori `ar_payment` atas invoice `source_module=direct_sale` yang BELUM tercatat
    di `rahaza_ar_payments.movement_id` (pembayaran lewat layar Keuangan sudah terhitung di sana)."""
    inv_ids = await db.rahaza_ar_invoices.distinct("id", {"source_module": "direct_sale"})
    if not inv_ids:
        return 0
    linked = set(await db.rahaza_ar_payments.distinct("movement_id", {"movement_id": {"$ne": None}}))
    match = {"category": "ar_payment", "direction": "in", "ref_id": {"$in": inv_ids}}
    if date_filter:
        match["date"] = date_filter
    total = 0.0
    async for mv in db.rahaza_cash_movements.find(match, {"_id": 0, "id": 1, "amount": 1}):
        if mv.get("id") not in linked:
            total += float(mv.get("amount") or 0)
    return round(total, 2)


async def gl_gross_profit(db, date_from: str = "", date_to: str = "") -> dict:
    """2026-11-02 (K20): kartu "Laba kotor (buku besar)" — rumus Laba/Rugi yang SAMA dengan layar L/R
    (pendapatan bersih akun REVENUE: DPP tanpa PPN, setelah retur/diskon, termasuk pencairan
    marketplace; dikurangi HPP akun COGS) untuk periode yang sama dengan Rekap."""
    from routes.rahaza_fin_reports import compute_profit_loss
    t = (await compute_profit_loss(db, date_from or None, date_to or None))["totals"]
    return {"revenue": t["revenue"], "cogs": t["cogs"], "gross_profit": t["gross_profit"]}


async def vendor_payables(db, date_filter: dict, excluded: list, open_statuses: list, limit: int = 10) -> list:
    """2026-11-03: daftar "Hutang Vendor" di Rekap — dulu `garment_summary` selalu `[]` sehingga kartu
    itu selalu "Tidak ada data" walau Total Outstanding AP terisi. Per pemasok: Σ tagihan periode ini
    dan sisa yang belum dibayar (status terbuka). Kunci `garment_name` dipertahankan untuk layar lama."""
    match = {"status": {"$nin": excluded}}
    if date_filter:
        match["issue_date"] = date_filter
    rows = await db.rahaza_ap_invoices.aggregate([
        {"$match": match},
        {"$group": {"_id": {"$ifNull": ["$vendor_name", "(tanpa nama)"]},
                    "total_invoiced": {"$sum": invoice_total_expr()},
                    "outstanding": {"$sum": {"$cond": [{"$in": ["$status", open_statuses]}, open_balance_expr(), 0]}},
                    "invoices": {"$sum": 1}}},
        {"$sort": {"outstanding": -1, "total_invoiced": -1}},
        {"$limit": limit},
    ]).to_list(limit)
    return [{"vendor_name": r["_id"], "garment_name": r["_id"], "total_invoiced": round(r["total_invoiced"], 2),
             "outstanding": round(r["outstanding"], 2), "invoices": r["invoices"]} for r in rows]


async def compute_financial_recap(db, date_from: str, date_to: str, today, open_statuses_canonical: list) -> dict:
    """Isi `GET /api/financial-recap` (FinancialRecapModule.jsx) — dipindah dari server.py (2026-11-02)
    supaya bisa diuji tanpa memuat seluruh server.

    K20 (keputusan owner 2026-11-02):
      · `gross_margin` TETAP = Σ tagihan pelanggan (AR) − Σ tagihan pemasok (AP) (spesifikasi uji owner T1),
        tetapi BUKAN laba → label layar "Selisih tagihan pelanggan − tagihan pemasok (bukan laba)";
      · `gl_gross_profit` = laba kotor buku besar periode yang sama (rumus L/R);
      · kas masuk = pembayaran AR (`rahaza_ar_payments`) + pembayaran Penjualan Langsung.
    """
    from datetime import timedelta
    from dateutil.relativedelta import relativedelta

    date_filter = {}
    if date_from:
        date_filter["$gte"] = date_from
    if date_to:
        date_filter["$lte"] = date_to
    excluded = ["cancelled", "draft", "void", "written_off"]

    total_sales, total_ar_invoices = await sum_invoices(db.rahaza_ar_invoices, date_filter, excluded)
    total_vendor, total_ap_invoices = await sum_invoices(db.rahaza_ap_invoices, date_filter, excluded)
    cash_in_ar = await sum_payments(db.rahaza_ar_payments, date_filter)
    cash_in_direct = await sum_direct_sale_receipts(db, date_filter)
    total_cash_in = cash_in_ar + cash_in_direct
    total_cash_out = await sum_payments(db.rahaza_ap_payments, date_filter)

    open_statuses = recap_open_statuses(open_statuses_canonical)
    ar_out_agg = await db.rahaza_ar_invoices.aggregate([
        {"$match": {"status": {"$in": open_statuses}}},
        {"$group": {"_id": None, "total": {"$sum": open_balance_expr()}}},
    ]).to_list(1)
    ar_outstanding = ar_out_agg[0]["total"] if ar_out_agg else 0
    ap_out_agg = await db.rahaza_ap_invoices.aggregate([
        {"$match": {"status": {"$in": open_statuses}}},
        {"$group": {"_id": None, "total": {"$sum": open_balance_expr()}}},
    ]).to_list(1)
    ap_outstanding = ap_out_agg[0]["total"] if ap_out_agg else 0

    # Selisih AR − AP (rumus T1) — bukan laba
    gross_margin = total_sales - total_vendor
    gross_margin_pct = round((gross_margin / total_sales * 100), 1) if total_sales > 0 else 0
    gl = await gl_gross_profit(db, date_from, date_to)

    # Monthly trend (last 6 months)
    monthly_trend = []
    for i in range(5, -1, -1):
        m_date = today - relativedelta(months=i)
        m_str = m_date.strftime("%Y-%m")
        m_label = m_date.strftime("%b %Y")
        m_start = f"{m_str}-01"
        m_end = (m_date.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).strftime("%Y-%m-%d")
        m_filter = {"$gte": m_start, "$lte": m_end}
        ms, _ = await sum_invoices(db.rahaza_ar_invoices, m_filter, excluded)
        mc, _ = await sum_invoices(db.rahaza_ap_invoices, m_filter, excluded)
        m_gl = await gl_gross_profit(db, m_start, m_end)
        monthly_trend.append({
            "month": m_label,
            "sales": ms,
            "cost": mc,
            "margin": ms - mc,
            "gl_gross_profit": m_gl["gross_profit"],
            "cash_in": await sum_payments(db.rahaza_ar_payments, m_filter) + await sum_direct_sale_receipts(db, m_filter),
            "cash_out": await sum_payments(db.rahaza_ap_payments, m_filter),
        })
    return {
        "total_sales_value": total_sales,
        "total_vendor_cost": total_vendor,
        "total_buyer_invoices": total_ar_invoices,
        "total_vendor_invoices": total_ap_invoices,
        "total_cash_in": total_cash_in,
        "cash_in_breakdown": {"ar_payments": cash_in_ar, "direct_sales": cash_in_direct},
        "total_cash_out": total_cash_out,
        "total_adjustments": 0,
        "accounts_receivable_outstanding": ar_outstanding,
        "accounts_payable_outstanding": ap_outstanding,
        "gross_margin": gross_margin,
        "gross_margin_pct": gross_margin_pct,
        "gross_margin_label": "Selisih tagihan pelanggan − tagihan pemasok (bukan laba)",
        "gl_gross_profit": gl["gross_profit"],
        "gl_revenue": gl["revenue"],
        "gl_cogs": gl["cogs"],
        "gl_gross_profit_label": "Laba kotor (buku besar)",
        "monthly_trend": monthly_trend,
        "garment_summary": await vendor_payables(db, date_filter, excluded, open_statuses),
        "date_from": date_from,
        "date_to": date_to,
    }
