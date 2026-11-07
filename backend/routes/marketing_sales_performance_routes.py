"""
Sales Performance Dashboard — Backend Routes
Phase 3 Week 6: Aggregate sales data from marketing_sales_data + marketing_orders
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Query
from database import get_db
from auth import require_auth
# F6 (sesi #9) — performa penjualan WAJIB berlingkup toko.
from core import marketing_account_scope as _scope
# 2026-11-07 (Asisten AI) — SATU definisi omzet untuk semua layar & AI.
from core import ukuran_penjualan as _ukuran
from utils.waktu import today_wib

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/marketing/performance", tags=["marketing-performance"])

# ── Standardized Response Helper ──
def success_response(data=None, pagination=None, metadata=None):
    response = {"success": True}
    if data is not None:
        response["data"] = data
    if pagination is not None:
        response["pagination"] = pagination
    if metadata is not None:
        response["metadata"] = metadata
    return response

def _now() -> datetime:
    return datetime.now(timezone.utc)

def serialize(obj):
    if isinstance(obj, list):
        return [serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items() if k != "_id"}
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj

# ── Endpoints ──

async def _performance_accounts(db, user, *, account_id=None, account=None, platform=None):
    """Toko untuk layar performa: lingkup pemakai (F6) + saringan toko/nama/platform."""
    if account_id:
        await _scope.assert_account_visible(db, user, account_id)
    accs = await _ukuran.toko_terlihat(db, user, toko_id=account_id or None)
    if account and not account_id:
        accs = [a for a in accs if a.get("account_name") == account]
    if platform:
        fam = _scope.platform_family(platform)
        accs = [a for a in accs if _scope.platform_family(a.get("platform")) == fam]
    return accs


def _range(start: Optional[str], end: Optional[str], days: int = 30) -> tuple:
    """Rentang tanggal kalender (bagian tanggal APA ADANYA, seperti rekap harian)."""
    today = today_wib()
    d1 = (end or "")[:10] or today.isoformat()
    d0 = (start or "")[:10] or (today - timedelta(days=days)).isoformat()
    try:
        return _ukuran.periode(d0, d1, maks_hari=3700)
    except _ukuran.PeriodeSalah as e:
        raise HTTPException(400, str(e)) from None


@router.get("/overview")
async def performance_overview(
    request: Request,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="alias start_date"),
    date_to: Optional[str] = Query(None, description="alias end_date"),
    platform: Optional[str] = Query(None),
    account: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
):
    """Ringkasan performa penjualan.

    2026-11-07 (Asisten AI, audit §3.C #8/#9) — SATU definisi omzet
    (`core.ukuran_penjualan`): total, per platform, dan tren harian dari REKAP HARIAN
    (sama dengan dashboard, laporan bulanan, target, dan Asisten AI); pecahan kanal
    dari pesanan dengan aturan yang sama (batal & belum dibayar tidak dihitung,
    data contoh dibuang). Dulu angka ini dihitung langsung dari pesanan dengan
    aturan sendiri — pesanan belum dibayar ikut omzet, dan pesanan bertanggal teks
    hilang dari tren.
    """
    user = await require_auth(request)
    db = get_db()
    d0, d1 = _range(start_date or date_from, end_date or date_to)
    accs = await _performance_accounts(db, user, account_id=account_id, account=account,
                                       platform=platform)
    oms = await _ukuran.ringkas_omzet(db, accs, d0, d1)
    tot = oms["total"]
    by_acc = {a["id"]: a for a in accs}

    by_platform: dict = {}
    for aid, t in oms["per_toko"].items():
        if not t["hari_ada_data"]:
            continue
        p = _scope.platform_family((by_acc.get(aid) or {}).get("platform")) or "lainnya"
        b = by_platform.setdefault(p, {"revenue": 0.0, "orders": 0})
        b["revenue"] += t["omzet"]
        b["orders"] += t["pesanan"]

    daily: dict = {}
    for r in oms["baris"]:
        b = daily.setdefault(r["date"], {"date": r["date"], "revenue": 0.0, "orders": 0})
        b["revenue"] += r["omzet"]
        b["orders"] += r["pesanan"]

    orders = await _ukuran.baca_pesanan(db, list(by_acc), d0, d1)
    by_channel = {c["kunci"]: {"revenue": c["omzet"], "orders": c["pesanan"]}
                  for c in _ukuran.rincian_kanal(orders)}

    return success_response(data={
        "total_revenue": tot["omzet"],
        "total_order_amount": tot["nilai_pesanan"],
        "total_orders": tot["pesanan"],
        "total_items": tot["unit"],
        "aov": tot["aov"],
        "returned_value": tot["retur_nilai"],
        "revenue_after_returns": tot["omzet_setelah_retur"],
        "revenue_label": "sebelum potongan platform",
        "definition": _ukuran.DEFINISI_OMZET,
        "by_platform": by_platform,
        "by_channel": by_channel,
        "daily_trend": [daily[k] for k in sorted(daily)],
    }, metadata={
        "start_date": d0,
        "end_date": d1,
    })


@router.get("/top-products")
async def top_products(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=5, le=50),
    account_id: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
):
    """Produk terlaris per ITEM KATALOG.

    2026-11-07 (audit §3.C #2) — dulu dikelompokkan menurut NAMA teks, dan baris
    pesanan manual (tanpa `sku_subtotal_after_discount`) jatuh ke omzet SELURUH
    pesanan, sehingga pesanan 3 produk menyumbang omzetnya tiga kali. Sekarang
    omzet & pcs dibaca per baris SKU lewat pembaca kanonik dan dikelompokkan per
    `catalog_item_id` (cadangan: SKU, lalu nama untuk baris yang belum tertaut).
    """
    user = await require_auth(request)
    db = get_db()
    d0, d1 = _range(None, None, days=days)
    accs = await _performance_accounts(db, user, account_id=account_id, platform=platform)
    orders = await _ukuran.baca_pesanan(db, [a["id"] for a in accs], d0, d1)
    rows = await _ukuran.rincian_item(db, orders, "katalog")

    products = [{
        "product_name": r["label"],
        "sku": r["sku"] or None,
        "catalog_item_id": r["kunci"][5:] if r["kunci"].startswith("item:") else None,
        "total_qty": r["unit"],
        "total_revenue": r["omzet"],
        "order_count": r["pesanan"],
    } for r in rows[:limit]]
    return success_response(data={"products": products}, metadata={"days": days, "limit": limit,
                                                                   "start_date": d0, "end_date": d1})
