"""GET /api/assets/dashboard — top-level KPIs, category breakdown, recent + expiring counts.
GET /api/assets/finance-registry — daftar aset registri Keuangan untuk ditaut (K18, 2026-11-02)."""
from datetime import timedelta
from typing import Optional
from fastapi import Request

from database import get_db
from auth import require_auth
from ._helpers import router, _ser, _ensure_default_categories, load_finance_assets, apply_finance_overlay
from utils.waktu import today_wib


@router.get("/finance-registry")
async def finance_registry_lookup(request: Request, search: Optional[str] = None, include_linked: bool = False):
    """K18: aset tetap di registri Keuangan (rahaza_fixed_assets) yang bisa DITAUT ke catatan Portal Aset.
    Data acuan baca-saja (kode, nama, kategori, nilai buku) — peran Portal Aset (mis. admin_gudang) tidak
    perlu akses Portal Keuangan untuk memilih tautan."""
    await require_auth(request)
    db = get_db()
    q = {"status": {"$ne": "disposed"}}
    if search:
        import re
        rx = {"$regex": re.escape(search), "$options": "i"}
        q["$or"] = [{"code": rx}, {"name": rx}, {"serial_number": rx}]
    rows = await db.rahaza_fixed_assets.find(q, {"_id": 0, "id": 1}).sort("code", 1).to_list(500)
    fin = await load_finance_assets(db, [r["id"] for r in rows])
    linked = {a.get("fixed_asset_id"): a.get("asset_number") async for a in db.dewi_assets.find(
        {"fixed_asset_id": {"$in": list(fin)}}, {"_id": 0, "fixed_asset_id": 1, "asset_number": 1})}
    out = []
    for r in rows:
        f = fin.get(r["id"])
        if not f or (linked.get(r["id"]) and not include_linked):
            continue
        out.append({**f, "linked_asset_number": linked.get(r["id"])})
    return out


@router.get("/dashboard")
async def get_asset_dashboard(request: Request):
    await require_auth(request)
    db = get_db()
    await _ensure_default_categories(db)

    total = await db.dewi_assets.count_documents({"status": {"$ne": "disposed"}})
    active = await db.dewi_assets.count_documents({"status": "active"})
    in_maintenance = await db.dewi_assets.count_documents({"status": "in_maintenance"})
    disposed = await db.dewi_assets.count_documents({"status": "disposed"})

    # 2026-11-02 (K18): nilai aset tertaut diambil dari registri Keuangan (harga, akumulasi, nilai buku).
    live = await db.dewi_assets.find({"status": {"$ne": "disposed"}},
                                     {"_id": 0, "id": 1, "fixed_asset_id": 1, "purchase_cost": 1,
                                      "accumulated_depreciation": 1}).to_list(5000)
    fin = await load_finance_assets(db, [a.get("fixed_asset_id") for a in live])
    for a in live:
        apply_finance_overlay(a, fin.get(a.get("fixed_asset_id")))
    totals = {"total_cost": sum(float(a.get("purchase_cost") or 0) for a in live),
              "total_accumulated_depr": sum(float(a.get("accumulated_depreciation") or 0) for a in live)}
    nbv = totals["total_cost"] - totals["total_accumulated_depr"]
    linked_count = sum(1 for a in live if a.get("finance_asset"))

    cat_pipeline = [
        {"$match": {"status": {"$ne": "disposed"}}},
        {"$group": {"_id": "$category_name", "count": {"$sum": 1}, "total_cost": {"$sum": "$purchase_cost"}}},
        {"$sort": {"count": -1}},
    ]
    by_category = await db.dewi_assets.aggregate(cat_pipeline).to_list(20)

    recent = await db.dewi_assets.find(
        {}, {"_id": 0, "id": 1, "name": 1, "asset_number": 1, "status": 1,
             "purchase_cost": 1, "category_name": 1, "created_at": 1}
    ).sort("created_at", -1).limit(5).to_list(5)

    current_period = today_wib().strftime("%Y-%m")
    # K18: penyusutan bulan ini = jadwal registri Keuangan yang sudah diposting (aset tertaut)
    depr_this_month = await db.rahaza_depr_schedules.aggregate([
        {"$match": {"period": current_period, "posted": True, "asset_id": {"$in": list(fin)}}},
        {"$group": {"_id": None, "total": {"$sum": "$depr_amount"}}},
    ]).to_list(1)
    depr_amount = depr_this_month[0]["total"] if depr_this_month else 0

    today_str = today_wib().isoformat()
    in_30_days = (today_wib() + timedelta(days=30)).isoformat()
    warranty_expiring_count = await db.dewi_assets.count_documents({
        "warranty_expiry_date": {"$gte": today_str, "$lte": in_30_days},
        "status": {"$ne": "disposed"},
    })
    insurance_expiring_count = await db.dewi_assets.count_documents({
        "insurance_expiry_date": {"$gte": today_str, "$lte": in_30_days},
        "status": {"$ne": "disposed"},
    })

    return {
        "summary": {
            "total_assets": total,
            "active": active,
            "in_maintenance": in_maintenance,
            "disposed": disposed,
            "total_purchase_cost": round(totals["total_cost"], 2),
            "total_accumulated_depreciation": round(totals["total_accumulated_depr"], 2),
            "total_nbv": round(nbv, 2),
            "depreciation_this_month": round(depr_amount, 2),
            "linked_to_finance": linked_count,
            "not_linked_to_finance": len(live) - linked_count,
            "value_source": "finance_registry_for_linked_assets",
            "warranty_expiring_soon": warranty_expiring_count,
            "insurance_expiring_soon": insurance_expiring_count,
        },
        "by_category": [
            {"category": b["_id"], "count": b["count"], "total_cost": b["total_cost"]}
            for b in by_category
        ],
        "recent_assets": [_ser(a) for a in recent],
    }
