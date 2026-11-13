# ruff: noqa: F401
"""
marketing_dashboard.py — Dashboard & Analytics
Extracted from marketing.py (1757 LOC monolith)

Refactored: Session #11.19 Phase 3.2 Batch #3
Endpoints: GET /dashboard/overview, GET /accounts/{id}/dashboard, POST /accounts/{id}/recalculate-health, GET /dashboard/comparison, POST /seed-sample-data
"""
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field
from database import get_db
from auth import require_auth, serialize_doc, log_activity, require_demo_seed_allowed
# F6 (sesi #9) — dashboard gabungan WAJIB berlingkup toko.
from core import marketing_account_scope as _scope
from routes.marketing_shared import _uid, _now, _get_user, _sanitize, _recalculate_health_score, refresh_stale_health_scores
from core import marketing_sales_shape as _shape
# 2026-11-07 (Asisten AI) — SATU definisi omzet untuk dashboard, laporan, dan AI.
from core import ukuran_penjualan as _ukuran
from utils.waktu import today_wib, wib_date_str

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/marketing', tags=['Marketing-Dashboard'])

@router.get("/dashboard/overview")
async def get_dashboard_overview(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    account_id: Optional[str] = None,
):
    """
    Consolidated dashboard for all accounts.
    Shows: Total revenue (all accounts), Total orders, Account count, etc.

    Dashboard Marketing (14 Nov 2026, owner: "grafik hanya sales saja") — `account_id` menyaring
    satu toko, dan jawaban membawa `daily` (omzet, omzet live, pesanan per tanggal) serta
    `per_account`. Keduanya dihitung dari baris yang SAMA dengan `summary`, jadi grafik tren,
    kartu, dan tabel toko di layar tidak bisa berbeda angka (dulu layar menjumlah sendiri
    `/accounts/{id}/sales` per toko + rekap jenis "live" yang bukan omzet live resmi).
    """
    user = await require_auth(request)
    db = get_db()

    # Bug #3 fix: Query ALL accounts first, then derive active subset
    # F6 (sesi #9): hanya toko yang boleh dilihat pemakai ini yang ikut dijumlah —
    # dulu staf pemegang satu toko melihat "total omzet" sembilan toko.
    all_accounts = await _scope.visible_accounts(db, user, limit=500)
    if account_id:
        await _scope.assert_account_visible(db, user, account_id)
        all_accounts = [a for a in all_accounts if a.get("id") == account_id]
    active_accounts_list = [a for a in all_accounts if a.get("status") == "active"]
    active_ids = [a["id"] for a in active_accounts_list]
    
    # Date range default: last 30 days
    if not date_to:
        date_to = wib_date_str()
    if not date_from:
        date_from = (today_wib() - timedelta(days=30)).isoformat()
    
    # 2026-11-07 (Asisten AI, audit §3.C #1/#9) — dulu `to_list(500)`: 9 toko × 31 hari
    # × 2 jenis sudah melebihi batas itu, jadi omzet terhitung kurang tanpa galat. Sekarang
    # dibaca lewat `core.ukuran_penjualan` (tanpa batas baris, tanpa data contoh, satu
    # dokumen per toko-tanggal) — angka yang sama dengan laporan bulanan & Asisten AI.
    oms = await _ukuran.ringkas_omzet(db, active_accounts_list, date_from, date_to)
    total_revenue = oms["total"]["omzet"]
    total_orders = oms["total"]["pesanan"]
    # M-07 / Q-2 (9 Nov 2026) — omzet live resmi = pesanan berkanal LIVE (bagian dari omzet
    # total). Dulu = rekap jenis "live" hasil sinkron shift host + sesi kreator, sehingga satu
    # siaran terhitung dua kali (Rp578.854 untuk siaran Rp289.427) dan tidak turun saat sesi
    # kreator dihapus.
    live = await _ukuran.ringkas_live(db, active_accounts_list, date_from, date_to)
    total_revenue_live = live["omzet"]

    # Rincian harian & per toko — baris yang sama dengan total di atas (satu sumber).
    harian: dict = {}
    for r in oms["baris"]:
        h = harian.setdefault(r["date"], {"date": r["date"], "revenue": 0.0, "revenue_live": 0.0,
                                          "orders": 0})
        h["revenue"] += float(r.get("omzet") or 0)
        h["orders"] += int(r.get("pesanan") or 0)
    for d, v in (live.get("per_tanggal") or {}).items():
        harian.setdefault(d, {"date": d, "revenue": 0.0, "revenue_live": 0.0, "orders": 0})
        harian[d]["revenue_live"] += float(v or 0)
    daily = [{**h, "revenue": round(h["revenue"]), "revenue_live": round(h["revenue_live"])}
             for _d, h in sorted(harian.items())]
    per_account = [{
        "account_id": a["id"], "account_name": a.get("account_name"),
        "account_code": a.get("account_code"), "platform": a.get("platform"),
        "revenue": round(oms["per_toko"].get(a["id"], {}).get("omzet", 0)),
        "orders": oms["per_toko"].get(a["id"], {}).get("pesanan", 0),
        "revenue_live": round((live.get("per_toko") or {}).get(a["id"], 0)),
        "days_with_data": oms["per_toko"].get(a["id"], {}).get("hari_ada_data", 0),
    } for a in active_accounts_list]

    # Top performing account (by revenue) — only from active accounts
    account_revenue = {aid: t["omzet"] for aid, t in oms["per_toko"].items() if t["hari_ada_data"]}

    top_account_id = max(account_revenue, key=account_revenue.get) if account_revenue else None
    top_account = None
    if top_account_id:
        top_account = await db.marketing_platform_accounts.find_one({"id": top_account_id}, {"_id": 0, "account_name": 1, "platform": 1})
    
    return serialize_doc({
        "period": {
            "date_from": date_from,
            "date_to": date_to
        },
        "summary": {
            "total_accounts": len(all_accounts),
            "active_accounts": len(active_accounts_list),
            "total_revenue": round(total_revenue),
            "total_revenue_live": round(total_revenue_live),
            "live_definition": _ukuran.DEFINISI_LIVE,
            "total_orders": total_orders,
            "avg_order_value": round(total_revenue / total_orders) if total_orders > 0 else 0
        },
        "top_account": {
            "account_id": top_account_id,
            "account_name": top_account.get("account_name") if top_account else None,
            "platform": top_account.get("platform") if top_account else None,
            "revenue": round(account_revenue.get(top_account_id, 0)) if top_account_id else 0
        } if top_account else None,
        "daily": daily,
        "per_account": per_account,
        "live": {"sessions": live.get("sesi", 0), "orders": live.get("pesanan", 0),
                 "recorded_revenue": live.get("omzet_tercatat_sesi", 0),
                 "definition": _ukuran.DEFINISI_LIVE},
    })


@router.get("/accounts/{account_id}/dashboard")
async def get_account_dashboard(
    account_id: str,
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None)
):
    """
    Per-account dashboard with detailed metrics.
    Shows dual revenue stream (total + live) separately.
    """
    await require_auth(request)
    db = get_db()
    
    account = await db.marketing_platform_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(404, "Account not found")
    await refresh_stale_health_scores(db, [account])   # skor sehat segar (keputusan 8 Nov 2026)

    # Date range default: last 30 days
    if not date_to:
        date_to = wib_date_str()
    if not date_from:
        date_from = (today_wib() - timedelta(days=30)).isoformat()
    
    # Get sales data for this account
    query = {
        "account_id": account_id,
        "date": {"$gte": date_from, "$lte": date_to},
        "revenue_type": "total",
    }

    # 2026-11-07 (audit #1) — tanpa batas 500 baris & tanpa data contoh.
    # 9 Nov 2026 — satu dokumen per tanggal (kembaran lama: yang terbaru), aturan baku.
    query.update(_ukuran.TANPA_CONTOH)
    _pick: dict = {}
    async for _d in db.marketing_sales_data.find(query, {"_id": 0}):
        _k = str(_d.get("date") or "")[:10]
        if _k in _pick and str(_d.get("updated_at") or "") <= str(_pick[_k].get("updated_at") or ""):
            continue
        _pick[_k] = _d
    sales_data = [_pick[k] for k in sorted(_pick)]
    _live = await _ukuran.ringkas_live(db, [account], date_from, date_to)
    
    # Separate total vs live
    total_revenue = 0
    total_orders = 0
    live_revenue = 0
    live_orders = 0
    
    daily_chart_total = []
    daily_chart_live = []
    
    # Latest metrics for health indicators
    latest_fulfillment = {}
    latest_satisfaction = {}
    
    for sale in sales_data:
        m = _shape.read_metrics(sale)      # F0.3 — aman untuk dokumen lama & kanonik
        if sale.get("revenue_type") == "total":
            total_revenue += m.get("revenue", 0)
            total_orders += m.get("orders", 0)
            daily_chart_total.append({
                "date": sale.get("date"),
                "revenue": m.get("revenue", 0),
                "orders": m.get("orders", 0)
            })
            # Get latest fulfillment & satisfaction
            if _shape.read_group(sale, "fulfillment"):
                latest_fulfillment = _shape.read_group(sale, "fulfillment")
            if _shape.read_group(sale, "customer_satisfaction"):
                latest_satisfaction = _shape.read_group(sale, "customer_satisfaction")
            # Q-2 — omzet live resmi = pesanan berkanal LIVE (kanal di rekap total)
            _lv = _ukuran._num(_shape.read_group(sale, "traffic").get("live"))
            live_revenue += _lv
            if _lv:
                daily_chart_live.append({"date": sale.get("date"), "revenue": _lv, "orders": None})
    live_orders = _live["pesanan"]
    live_revenue = _live["omzet"]      # satu definisi (termasuk rekap live ketikan toko manual)
    
    return serialize_doc({
        "account": {
            "id": account["id"],
            "account_code": account["account_code"],
            "account_name": account["account_name"],
            "platform": account["platform"],
            "status": account["status"],
            "health_score": account.get("health_score", 0)
        },
        "period": {
            "date_from": date_from,
            "date_to": date_to
        },
        "total_revenue_stream": {
            "revenue": round(total_revenue),
            "orders": total_orders,
            "aov": round(total_revenue / total_orders) if total_orders > 0 else 0,
            "daily_chart": daily_chart_total
        },
        "live_revenue_stream": {
            "revenue": round(live_revenue),
            "orders": live_orders,
            "aov": round(live_revenue / live_orders) if live_orders > 0 else 0,
            "daily_chart": daily_chart_live,
            "sessions": _live["sesi"],
            "recorded_in_sessions": _live["omzet_tercatat_sesi"],
            "definition": _ukuran.DEFINISI_LIVE,
        },
        "health_metrics": {
            "rating": latest_satisfaction.get("rating", 0),
            "review_count": latest_satisfaction.get("review_count", 0),
            "response_rate": latest_satisfaction.get("response_rate", 0),
            "fulfillment_rate": latest_fulfillment.get("fulfillment_rate", 0),
            "cancellation_rate": latest_fulfillment.get("cancellation_rate", 0),
            "return_rate": latest_fulfillment.get("return_rate", 0),
            "late_shipment_rate": latest_fulfillment.get("late_shipment_rate", 0)
        }
    })


@router.post("/accounts/{account_id}/recalculate-health")
async def recalculate_account_health(account_id: str, request: Request):
    """
    Manually trigger health score recalculation for an account.
    Useful after bulk data import or corrections.
    """
    await require_auth(request)
    db = get_db()
    
    account = await db.marketing_platform_accounts.find_one({"id": account_id}, {"_id": 0})
    if not account:
        raise HTTPException(404, "Account not found")
    
    new_score = await _recalculate_health_score(db, account_id)
    
    return serialize_doc({
        "message": "Health score recalculated",
        "account_id": account_id,
        "account_name": account["account_name"],
        "new_health_score": new_score
    })


@router.get("/dashboard/comparison")
async def get_comparison_dashboard(
    request: Request,
    accounts: str = Query(..., description="Comma-separated account IDs (max 5)"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None)
):
    """
    Comparison dashboard for side-by-side account analysis.
    Max 5 accounts can be compared at once.
    """
    user = await require_auth(request)
    db = get_db()

    # Parse account IDs
    account_ids = [aid.strip() for aid in accounts.split(",") if aid.strip()]
    # F6: membandingkan toko orang lain juga dilarang (jaring pengaman middleware
    # sudah menolak, ini penjaga eksplisit supaya alasannya jelas di route).
    for aid in account_ids:
        await _scope.assert_account_visible(db, user, aid)
    if len(account_ids) > 5:
        raise HTTPException(400, "Maximum 5 accounts can be compared at once")
    if len(account_ids) < 2:
        raise HTTPException(400, "At least 2 accounts required for comparison")
    
    # Date range default: last 30 days
    if not date_to:
        date_to = wib_date_str()
    if not date_from:
        date_from = (today_wib() - timedelta(days=30)).isoformat()
    
    comparison_data = []

    # ── FIX N+1: Batch fetch accounts + sales in 2 queries instead of N×2 ─────
    accounts_list = await db.marketing_platform_accounts.find(
        {"id": {"$in": account_ids}}, {"_id": 0}
    ).to_list(500)
    await refresh_stale_health_scores(db, accounts_list)   # skor sehat segar (keputusan 8 Nov 2026)
    accounts_map = {a["id"]: a for a in accounts_list}

    # 2026-11-06 (pola P7): semua baris periode (dulu to_list(500) — 5 toko × 1 tahun = 1.825 baris; omzet &
    # pesanan toko terakhir terpotong diam-diam). Urut tanggal supaya "rating terakhir" memang yang terakhir.
    all_sales = [s async for s in db.marketing_sales_data.find(
        {
            "account_id": {"$in": account_ids},
            "date": {"$gte": date_from, "$lte": date_to},
            "revenue_type": "total",
            **_ukuran.TANPA_CONTOH,     # 2026-11-07 — data contoh tidak pernah dihitung
        },
        {"_id": 0}
    ).sort("date", 1)]

    # Group sales by account_id in memory
    from collections import defaultdict as _defaultdict
    sales_by_account = _defaultdict(list)
    for s in all_sales:
        sales_by_account[s["account_id"]].append(s)

    for account_id in account_ids:
        account = accounts_map.get(account_id)
        if not account:
            continue  # Skip invalid IDs

        sales_data = sales_by_account.get(account_id, [])

        total_revenue = sum(_shape.read_metrics(s).get("revenue", 0) for s in sales_data)
        total_orders = sum(_shape.read_metrics(s).get("orders", 0) for s in sales_data)

        # Get latest satisfaction
        latest_rating = 0
        if sales_data:
            last_sale = sales_data[-1]
            latest_rating = _shape.read_group(last_sale, "customer_satisfaction").get("rating", 0)

        comparison_data.append({
            "account_id": account["id"],
            "account_code": account["account_code"],
            "account_name": account["account_name"],
            "platform": account["platform"],
            "health_score": account.get("health_score"),  # None = N/A
            "total_revenue": round(total_revenue),
            "total_orders": total_orders,
            "aov": round(total_revenue / total_orders) if total_orders > 0 else 0,
            "rating": latest_rating
        })
    
    return serialize_doc({
        "period": {
            "date_from": date_from,
            "date_to": date_to
        },
        "accounts": comparison_data
    })


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY: Seed sample data for testing
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/seed-sample-data")
async def seed_sample_data(request: Request):
    """
    Seed sample platform accounts and sales data for testing.
    USE ONLY FOR DEVELOPMENT/TESTING.
    """
    require_demo_seed_allowed()  # pagar produksi: ALLOW_DEMO_SEED=false → 403 (2026-11-04)
    await require_auth(request)
    db = get_db()
    
    # Create 3 sample accounts
    accounts = [
        {
            "id": _uid(),
            "account_code": "SHOPEE-OFFICIAL",
            "account_name": "Shopee Official Store DEMO",
            "platform": "shopee",
            "username": "demobrand_official",
            "status": "active",
            "group": "other",
            "credentials": {"has_api_integration": False},
            "import_config": {"saved_templates": []},
            "assigned_staff": [],
            "health_score": 0,
            "created_at": _now(),
            "created_by": "seed",
            "updated_at": _now()
        },
        {
            "id": _uid(),
            "account_code": "SHOPEE-RESELLER",
            "account_name": "Shopee Reseller A",
            "platform": "shopee",
            "username": "demobrand_reseller",
            "status": "active",
            "group": "other",
            "credentials": {"has_api_integration": False},
            "import_config": {"saved_templates": []},
            "assigned_staff": [],
            "health_score": 0,
            "created_at": _now(),
            "created_by": "seed",
            "updated_at": _now()
        },
        {
            "id": _uid(),
            "account_code": "TIKTOK-STORE",
            "account_name": "TikTok Shop DEMO",
            "platform": "tiktokshop",
            "username": "demobrand_tiktok",
            "status": "active",
            "group": "other",
            "credentials": {"has_api_integration": False},
            "import_config": {"saved_templates": []},
            "assigned_staff": [],
            "health_score": 0,
            "created_at": _now(),
            "created_by": "seed",
            "updated_at": _now()
        }
    ]
    
    # Insert accounts
    for acc in accounts:
        existing = await db.marketing_platform_accounts.find_one({"account_code": acc["account_code"]}, {"_id": 0})
        if not existing:
            await db.marketing_platform_accounts.insert_one(acc)
    
    return serialize_doc({"message": "Sample data seeded", "accounts_created": len(accounts)})



# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: TASK MANAGEMENT SYSTEM (Trello-style)
# ══════════════════════════════════════════════════════════════════════════════

