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
