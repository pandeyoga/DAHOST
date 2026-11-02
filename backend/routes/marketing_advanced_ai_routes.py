"""
Phase 5 — Advanced AI Features
A) Dynamic Pricing (ON/OFF + configurable guardrails + suggestion workflow)
B) Churn Prediction (RFM + AI explanation)
C) A/B Testing (content experiments + AI winner conclusion)
"""
import uuid
import logging
import json
import math
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel, Field
from database import get_db
from auth import require_auth
from services.ai import AIError, Pseudonymizer, ai_http_error, ai_text, clamp_number, pick_enum, require_ai

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/marketing/advanced-ai", tags=["marketing-advanced-ai"])


def _now(): return datetime.now(timezone.utc)

def ok(data=None, meta=None):
    r = {"success": True}
    if data is not None:
        r["data"] = data
    if meta is not None:
        r["metadata"] = meta
    return r

def serialize(o):
    if isinstance(o, list):
        return [serialize(i) for i in o]
    if isinstance(o, dict):
        return {k: serialize(v) for k, v in o.items() if k != "_id"}
    if isinstance(o, datetime):
        return o.isoformat()
    return o


# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 5A — DYNAMIC PRICING
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_PRICING_SETTINGS = {
    "enabled": False,
    "mode": "suggest_only",            # suggest_only | auto_apply
    "approval_required": True,
    "min_margin_pct_global": 25.0,      # minimum margin (%) harga setelah adjustment
    "max_price_increase_pct_per_run": 10.0,
    "max_price_decrease_pct_per_run": 15.0,
    "rounding_rule": 500,              # round to nearest X (e.g. 500, 1000)
    "exclude_skus": [],
    "exclude_categories": [],
    "include_platforms": ["shopee", "tiktok", "tokopedia"],
    "reason_weights": {
        "demand": 0.35,
        "stock": 0.25,
        "reviews": 0.20,
        "ads": 0.10,
        "complaints": 0.10
    },
    "run_cooldown_minutes": 30,         # min gap between runs
    "updated_at": None,
    "updated_by": None
}


class PricingSettingsIn(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = None
    approval_required: Optional[bool] = None
    min_margin_pct_global: Optional[float] = None
    max_price_increase_pct_per_run: Optional[float] = Field(default=None, ge=0)
    max_price_decrease_pct_per_run: Optional[float] = Field(default=None, ge=0)
    rounding_rule: Optional[int] = None
    exclude_skus: Optional[List[str]] = None
    exclude_categories: Optional[List[str]] = None
    include_platforms: Optional[List[str]] = None
    run_cooldown_minutes: Optional[int] = None


async def _get_pricing_settings(db) -> dict:
    doc = await db.marketing_dynamic_pricing_settings.find_one({"_type": "settings"})
    if not doc:
        return {**DEFAULT_PRICING_SETTINGS}
    doc.pop("_id", None)
    return doc


@router.get("/pricing/settings")
async def get_pricing_settings(request: Request):
    await require_auth(request)
    db = get_db()
    settings = await _get_pricing_settings(db)
    return ok(data=serialize(settings))


@router.put("/pricing/settings")
async def update_pricing_settings(payload: PricingSettingsIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    current = await _get_pricing_settings(db)
    update = {k: v for k, v in payload.dict().items() if v is not None}
    # K28 (2026-11-02): harga dinamis WAJIB disetujui manusia → mode "auto_apply" &
    # approval_required=False ditolak diam-diam (dulu disimpan tapi tidak pernah dibaca).
    update["mode"] = "suggest_only"
    update["approval_required"] = True
    merged = {**current, **update, "_type": "settings", "updated_at": _now(),
              "updated_by": _actor_label(user)}
    await db.marketing_dynamic_pricing_settings.update_one(
        {"_type": "settings"}, {"$set": merged}, upsert=True
    )
    merged.pop("_id", None)
    return ok(data=serialize(merged), meta={"message": "Settings disimpan"})


@router.post("/pricing/run")
async def run_pricing_suggestions(request: Request):
    """Generate dynamic pricing suggestions berdasarkan data penjualan + AI analysis."""
    user = await require_auth(request)
    db = get_db()
    settings = await _get_pricing_settings(db)

    if not settings.get("enabled"):
        raise HTTPException(400, "Dynamic Pricing sedang OFF. Aktifkan di Settings terlebih dahulu.")

    # 2026-11-02: gerbang tunggal services.ai (pesan ramah).
    await require_ai("marketing-pricing", user_id=user.get("id"), db=db, tier="light")

    # Rate limit check
    cooldown = settings.get("run_cooldown_minutes", 30)
    last = await db.marketing_dynamic_pricing_events.find_one(
        {"event_type": "run"}, sort=[("created_at", -1)]
    )
    if last:
        gap = (_now() - last["created_at"].replace(tzinfo=timezone.utc)).total_seconds() / 60
        if gap < cooldown:
            remain = round(cooldown - gap)
            raise HTTPException(429, f"Terlalu sering. Coba lagi dalam {remain} menit.")

    # Kumpulkan data produk dari orders (derive pricing context)
    pipeline = [
        {"$group": {
            "_id": "$product_name",
            "total_orders_30d": {"$sum": 1},
            "avg_price": {"$avg": {"$ifNull": ["$unit_price", "$price", 0]}},
            "total_revenue": {"$sum": {"$ifNull": ["$total_amount", 0]}},
            "return_count": {"$sum": {"$cond": [{"$eq": ["$status", "returned"]}, 1, 0]}},
            "cancel_count": {"$sum": {"$cond": [{"$eq": ["$status", "cancelled"]}, 1, 0]}},
            # K28 (2026-11-02): bukti pemetaan produk → item katalog/SKU untuk "Terapkan".
            "catalog_item_ids": {"$addToSet": "$catalog_item_id"},
            "skus": {"$addToSet": "$sku_id"},
        }},
        {"$match": {"_id": {"$ne": None}}},
        {"$sort": {"total_orders_30d": -1}},
        {"$limit": 20}
    ]
    products = []
    async for p in db.marketing_orders.aggregate(pipeline):
        products.append({
            "product": p["_id"],
            "orders_30d": p["total_orders_30d"],
            "avg_price_rp": round(p["avg_price"] or 0),
            "revenue_30d": round(p["total_revenue"] or 0),
            "return_rate_pct": round(p["return_count"] / max(p["total_orders_30d"], 1) * 100, 1),
            "cancel_rate_pct": round(p["cancel_count"] / max(p["total_orders_30d"], 1) * 100, 1),
            "_catalog_item_ids": [x for x in (p.get("catalog_item_ids") or []) if x],
            "_skus": [x for x in (p.get("skus") or []) if x],
        })

    # Review scores per product
    rev_pipeline = [
        {"$group": {
            "_id": "$product_name",
            "avg_rating": {"$avg": "$rating"},
            "review_count": {"$sum": 1}
        }}
    ]
    review_map = {}
    async for r in db.marketing_reviews.aggregate(rev_pipeline):
        review_map[r["_id"]] = {"avg_rating": round(r["avg_rating"] or 0, 1), "review_count": r["review_count"]}

    # Complaints per product
    comp_pipeline = [
        {"$group": {"_id": "$product_name", "complaints_30d": {"$sum": 1}}}
    ]
    comp_map = {}
    async for c in db.marketing_complaints.aggregate(comp_pipeline):
        comp_map[c["_id"]] = c["complaints_30d"]

    if not products:
        # K28 (2026-11-02): dulu 5 produk CONTOH dikarang lalu diusulkan harganya — usulan
        # untuk produk yang tidak ada di katalog tidak mungkin diterapkan. Sekarang jujur kosong.
        return ok(data={"suggestions": []},
                  meta={"count": 0, "products_analyzed": 0,
                        "message": "Belum ada data order produk untuk dianalisis."})

    # Enrich with reviews & complaints
    for p in products:
        rv = review_map.get(p["product"], {})
        p["avg_rating"] = rv.get("avg_rating", 4.5)
        p["review_count"] = rv.get("review_count", 0)
        p["complaints_30d"] = comp_map.get(p["product"], 0)

    # AI pricing analysis
    cfg_summary = {
        "min_margin_pct": settings["min_margin_pct_global"],
        "max_increase_pct": settings["max_price_increase_pct_per_run"],
        "max_decrease_pct": settings["max_price_decrease_pct_per_run"],
        "rounding": settings["rounding_rule"]
    }

    ai_system_msg = (
        "Kamu adalah sistem dynamic pricing untuk brand fashion Indonesia CV Dewi Aditya. "
        "Berikan rekomendasi harga yang cerdas, aman, dan realistis. "
        "Pertimbangkan demand, review, complaint, dan guardrails. "
        "Respond only with valid JSON."
    )

    by_product = {p["product"]: p for p in products}
    prompt_rows = [{k: v for k, v in p.items() if not k.startswith("_")} for p in products]
    prompt = (
        f"Data produk 30 hari terakhir:\n{json.dumps(prompt_rows, ensure_ascii=False, indent=2)}\n\n"
        f"Konfigurasi guardrails:\n{json.dumps(cfg_summary, ensure_ascii=False)}\n\n"
        f"Untuk setiap produk, tentukan apakah harga harus naik, turun, atau tetap. "
        f"Hitung suggested_price_rp (sudah dibulatkan ke {settings['rounding_rule']}). "
        f"Jika avg_price_rp = 0, skip produk tersebut.\n\n"
        f"Return JSON persis:\n"
        f"{{\"suggestions\": ["
        f"{{\"product\": \"nama produk\", "
        f"\"current_price_rp\": 185000, "
        f"\"suggested_price_rp\": 195000, "
        f"\"direction\": \"increase|decrease|hold\", "
        f"\"change_pct\": 5.4, "
        f"\"confidence\": \"high|medium|low\", "
        f"\"primary_reason\": \"demand tinggi (45 orders/30 hari)\", "
        f"\"secondary_reasons\": [\"rating 4.8 ★\"], "
        f"\"guardrail_ok\": true, "
        f"\"guardrail_note\": \"null atau penjelasan jika ada batasan yang tersentuh\""
        f"}}]}}"
    )

    suggestions_created = []
    try:
        response = await ai_text("marketing-pricing", ai_system_msg, prompt,
                                 tier="light", user_id=user.get("id"))
        clean = response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:-1])
        ai_result = json.loads(clean)

        for s in ai_result.get("suggestions", []):
            # K28 (2026-11-02): output AI divalidasi — produk harus ada di data, harga & arah
            # dihitung ulang server, guardrail dinilai server (bukan klaim AI).
            src = by_product.get(s.get("product"))
            new_price = clamp_number(s.get("suggested_price_rp"), 0, 1e12)
            if not src or not new_price or src["avg_price_rp"] <= 0:
                continue
            cur = float(src["avg_price_rp"])
            change = round((new_price - cur) / cur * 100, 1)
            direction = "increase" if change > 0 else "decrease" if change < 0 else "hold"
            if direction == "hold":
                continue
            guard_ok = (change <= float(settings["max_price_increase_pct_per_run"])
                        and -change <= float(settings["max_price_decrease_pct_per_run"]))
            doc = {
                "id": str(uuid.uuid4()),
                "product": src["product"],
                "catalog_item_ids": src.get("_catalog_item_ids", []),
                "skus": src.get("_skus", []),
                "current_price_rp": cur,
                "suggested_price_rp": new_price,
                "direction": direction,
                "change_pct": change,
                "confidence": pick_enum(s.get("confidence"), ("high", "medium", "low"), "low"),
                "primary_reason": str(s.get("primary_reason") or "")[:300],
                "secondary_reasons": [str(x)[:200] for x in (s.get("secondary_reasons") or [])][:5],
                "guardrail_ok": guard_ok,
                "guardrail_note": None if guard_ok else "Perubahan melewati batas guardrail — tidak bisa diterapkan.",
                "status": "pending",
                "created_at": _now(),
                "updated_at": _now(),
                "applied_at": None,
                "decided_by": None
            }
            await db.marketing_dynamic_pricing_suggestions.insert_one(doc)
            doc.pop("_id", None)
            suggestions_created.append(doc)

    except AIError as e:
        raise ai_http_error(e)
    except Exception as e:
        logger.error(f"Pricing AI error: {e}")
        raise HTTPException(502, "Usulan harga dari AI tidak dapat dibaca. Silakan coba lagi.")

    # Log run event
    await db.marketing_dynamic_pricing_events.insert_one({
        "id": str(uuid.uuid4()),
        "event_type": "run",
        "suggestions_count": len(suggestions_created),
        "created_at": _now(),
        "actor": _actor_label(user),  # 2026-11-02: aktor sebenarnya, bukan "admin"
        "actor_id": user.get("id"),
    })

    return ok(
        data={"suggestions": serialize(suggestions_created)},
        meta={"count": len(suggestions_created), "products_analyzed": len(products)}
    )


@router.get("/pricing/suggestions")
async def list_pricing_suggestions(
    request: Request,
    status: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20)
):
    await require_auth(request)
    db = get_db()
    filt = {}
    if status:
        filt["status"] = status
    if direction:
        filt["direction"] = direction
    total = await db.marketing_dynamic_pricing_suggestions.count_documents(filt)
    skip = (page - 1) * page_size
    docs = await db.marketing_dynamic_pricing_suggestions.find(filt).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
    return ok(
        data={"suggestions": serialize(docs)},
        meta={"total": total, "page": page, "page_size": page_size,
              "total_pages": max(1, math.ceil(total / page_size))}
    )


# 2026-11-02 (audit A §4.2): Approve/Reject/Apply memakai SATU gerbang izin yang sama.
# Dulu Apply hanya `require_auth` → cs_staff yang ditolak saat Approve bisa "Apply"
# usulan pending, dan semua aksi tercatat sebagai "admin".
_PRICING_APPROVE_KEYS = ('toko.approve', 'toko.manage', 'pricing.approve')
_PRICING_APPROVE_ROLES = ('manager_marketing', 'pic_marketing', 'pic_toko',
                          'manager', 'owner', 'admin', 'superadmin')

# K28 (2026-11-02, keputusan owner): Apply kini BENAR-BENAR menulis harga katalog lewat
# endpoint harga yang sudah ada (PUT item katalog) + jejak `marketing_change_log`.
# Bila produk usulan tidak terpetakan ke item katalog/SKU → ditolak dengan pesan jelas.
PRICING_APPLY_UNMAPPED_MSG = (
    "Produk \"{product}\" belum terpetakan ke item katalog/SKU, sehingga harga tidak bisa "
    "diterapkan otomatis. Tautkan pesanan produk ini ke item katalog (SKU/model) lalu ulangi, "
    "atau ubah harga manual di Katalog. Status usulan tidak diubah."
)


def _actor_label(user: dict) -> str:
    return (user or {}).get("name") or (user or {}).get("email") or (user or {}).get("id") or "-"


async def _require_pricing_approver(request: Request, message: str) -> dict:
    from routes.shared import require_perm
    return await require_perm(request, *_PRICING_APPROVE_KEYS,
                              legacy_roles=_PRICING_APPROVE_ROLES, message=message)


@router.post("/pricing/suggestions/{suggestion_id}/approve")
async def approve_suggestion(suggestion_id: str, request: Request):
    user = await _require_pricing_approver(
        request, 'Akses ditolak: Anda tidak berhak menyetujui usulan harga.')
    db = get_db()
    doc = await db.marketing_dynamic_pricing_suggestions.find_one({"id": suggestion_id})
    if not doc:
        raise HTTPException(404, "Suggestion tidak ditemukan")
    if doc["status"] != "pending":
        raise HTTPException(400, f"Status sudah {doc['status']}")
    actor = _actor_label(user)
    await db.marketing_dynamic_pricing_suggestions.update_one(
        {"id": suggestion_id},
        {"$set": {"status": "approved", "updated_at": _now(),
                  "decided_by": actor, "decided_by_id": user.get("id")}}
    )
    await db.marketing_dynamic_pricing_events.insert_one({
        "id": str(uuid.uuid4()), "event_type": "approve",
        "suggestion_id": suggestion_id, "product": doc["product"],
        "current_price_rp": doc["current_price_rp"], "suggested_price_rp": doc["suggested_price_rp"],
        "created_at": _now(), "actor": actor, "actor_id": user.get("id"),
    })
    return ok(data={"status": "approved"})


@router.post("/pricing/suggestions/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: str, request: Request,
    reason: Optional[str] = Query(None)
):
    user = await _require_pricing_approver(
        request, 'Akses ditolak: Anda tidak berhak menolak usulan harga.')
    db = get_db()
    doc = await db.marketing_dynamic_pricing_suggestions.find_one({"id": suggestion_id})
    if not doc:
        raise HTTPException(404, "Suggestion tidak ditemukan")
    if doc["status"] not in ["pending", "approved"]:
        raise HTTPException(400, f"Status sudah {doc['status']}")
    actor = _actor_label(user)
    await db.marketing_dynamic_pricing_suggestions.update_one(
        {"id": suggestion_id},
        {"$set": {"status": "rejected", "updated_at": _now(), "decided_by": actor,
                  "decided_by_id": user.get("id"), "reject_reason": reason}}
    )
    await db.marketing_dynamic_pricing_events.insert_one({
        "id": str(uuid.uuid4()), "event_type": "reject",
        "suggestion_id": suggestion_id, "product": doc["product"],
        "reason": reason, "created_at": _now(), "actor": actor, "actor_id": user.get("id"),
    })
    return ok(data={"status": "rejected"})


async def _resolve_catalog_items(db, doc: dict) -> list:
    """Petakan usulan → item katalog: catalog_item_id order → SKU → nama persis (aktif saja)."""
    active = {"is_active": {"$ne": False}}
    ids = [i for i in (doc.get("catalog_item_ids") or []) if i]
    if ids:
        items = await db.marketing_catalog_items.find({"id": {"$in": ids}, **active}, {"_id": 0}).to_list(20)
        if items:
            return items
    skus = [str(s).strip().upper() for s in (doc.get("skus") or []) if s]
    if skus:
        items = await db.marketing_catalog_items.find({"sku": {"$in": skus}, **active}, {"_id": 0}).to_list(20)
        if items:
            return items
    name = str(doc.get("product") or "").strip()
    if name:
        return await db.marketing_catalog_items.find({"name": name, **active}, {"_id": 0}).to_list(20)
    return []


async def _margin_pct_at(db, item: dict, price: float):
    """Margin (%) item bila dijual di `price` — SSOT core.catalog_margin; None = belum terukur."""
    from core import catalog_margin as _cmargin
    fg = await _cmargin.fg_cost_map(db, [item.get("fg_material_id")])
    row = _cmargin.decorate({**item, "harga_jual": price}, fg.get(item.get("fg_material_id")))
    return row.get("margin_pct")


@router.post("/pricing/suggestions/{suggestion_id}/apply")
async def apply_suggestion(suggestion_id: str, request: Request,
                           catalog_item_id: Optional[str] = None):
    """Terapkan usulan harga — K28 (2026-11-02).

    Syarat: izin yang sama dengan Approve + status `approved` (persetujuan tetap wajib).
    Produk dipetakan ke item katalog (id order → SKU → nama); harga ditulis lewat endpoint
    harga katalog yang SUDAH ADA (`PUT /api/marketing/catalogs/{id}/items/{id}`) dan jejaknya
    ke `marketing_change_log` (nilai lama → baru, aktor dari token). Tanpa pemetaan → 409.
    """
    user = await _require_pricing_approver(
        request, 'Akses ditolak: Anda tidak berhak menerapkan usulan harga.')
    db = get_db()
    settings = await _get_pricing_settings(db)
    if not settings.get("enabled"):
        raise HTTPException(400, "Dynamic Pricing sedang OFF")
    doc = await db.marketing_dynamic_pricing_suggestions.find_one({"id": suggestion_id})
    if not doc:
        raise HTTPException(404, "Suggestion tidak ditemukan")
    if doc["status"] != "approved":
        raise HTTPException(400, "Usulan harus disetujui (Approve) lebih dulu sebelum diterapkan.")

    items = await _resolve_catalog_items(db, doc)
    if catalog_item_id:
        items = [i for i in items if i.get("id") == catalog_item_id]
    if not items:
        raise HTTPException(409, PRICING_APPLY_UNMAPPED_MSG.format(product=doc.get("product", "")))
    if len(items) > 1:
        pilihan = ", ".join(f"{i.get('sku') or '-'} ({i.get('id')})" for i in items[:10])
        raise HTTPException(409, f"Produk \"{doc.get('product', '')}\" cocok dengan {len(items)} item "
                                 f"katalog: {pilihan}. Pilih satu item (catalog_item_id) untuk diterapkan.")
    item = items[0]
    if not item.get("catalog_id"):
        raise HTTPException(409, PRICING_APPLY_UNMAPPED_MSG.format(product=doc.get("product", "")))

    old_price = float(item.get("harga_jual") or item.get("price") or 0)
    new_price = clamp_number(doc.get("suggested_price_rp"), 0, 1e12)
    if not new_price:
        raise HTTPException(409, "Harga usulan tidak sah (harus lebih dari 0).")
    if old_price > 0:
        change = (new_price - old_price) / old_price * 100
        if change > float(settings.get("max_price_increase_pct_per_run", 10)) or \
                -change > float(settings.get("max_price_decrease_pct_per_run", 15)):
            raise HTTPException(409, f"Perubahan {change:+.1f}% dari harga katalog sekarang "
                                     f"(Rp{old_price:,.0f}) melewati batas guardrail. Tidak diterapkan.")
    margin = await _margin_pct_at(db, item, new_price)
    min_margin = float(settings.get("min_margin_pct_global") or 0)
    if margin is not None and margin < min_margin:
        raise HTTPException(409, f"Margin pada harga baru {margin:.1f}% di bawah batas minimum "
                                 f"{min_margin:.1f}%. Tidak diterapkan.")

    # Tulis lewat endpoint harga katalog yang sudah ada (normalisasi harga_jual/price, stats).
    from routes.marketing_catalog_items import CatalogItemUpdate, update_catalog_item
    await update_catalog_item(item["catalog_id"], item["id"], CatalogItemUpdate(harga_jual=new_price), request)

    actor = _actor_label(user)
    from core.marketing_cycle import log_change
    await log_change(db, account_id=item.get("account_id"), entity="catalog_item", entity_id=item["id"],
                     action="price_change", before={"harga_jual": old_price}, after={"harga_jual": new_price},
                     reason=f"Usulan harga AI {suggestion_id} (disetujui {doc.get('decided_by') or '-'})",
                     user=user)
    await db.marketing_dynamic_pricing_suggestions.update_one(
        {"id": suggestion_id},
        {"$set": {"status": "applied", "applied_at": _now(), "updated_at": _now(),
                  "applied_by": actor, "applied_by_id": user.get("id"),
                  "catalog_item_id": item["id"], "sku": item.get("sku"),
                  "old_price_rp": old_price, "new_price_rp": new_price}})
    await db.marketing_dynamic_pricing_events.insert_one({
        "id": str(uuid.uuid4()), "event_type": "apply", "suggestion_id": suggestion_id,
        "product": doc.get("product"), "catalog_item_id": item["id"], "sku": item.get("sku"),
        "old_price_rp": old_price, "new_price_rp": new_price,
        "created_at": _now(), "actor": actor, "actor_id": user.get("id"),
    })
    return ok(data={"status": "applied", "catalog_item_id": item["id"], "sku": item.get("sku"),
                    "old_price_rp": old_price, "new_price_rp": new_price})


@router.get("/pricing/events")
async def list_pricing_events(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(30)
):
    await require_auth(request)
    db = get_db()
    total = await db.marketing_dynamic_pricing_events.count_documents({})
    skip = (page - 1) * page_size
    docs = await db.marketing_dynamic_pricing_events.find({}).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
    return ok(data={"events": serialize(docs)}, meta={"total": total})


# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 5B — CHURN PREDICTION
# ═══════════════════════════════════════════════════════════════════════════

def _empty_churn_result() -> dict:
    """Hasil churn kosong yang jujur (tanpa pelanggan fiktif) — 2026-11-02."""
    return {
        "summary": {
            "total_customers": 0,
            "segments": {"low": 0, "medium": 0, "high": 0, "critical": 0},
            "segment_insights": {},
            "general_strategy": "",
            "quick_wins": [],
            "no_data": True,
        },
        "customers": [],
    }


@router.post("/churn/run")
async def run_churn_analysis(request: Request):
    """RFM-based churn analysis + AI explanation & recommendations."""
    user = await require_auth(request)
    db = get_db()

    # Build customer profiles from orders
    now = _now()
    pipeline = [
        {"$match": {"status": {"$nin": ["cancelled", "returned"]}}},
        {"$group": {
            "_id": "$buyer_name",
            "last_order": {"$max": "$created_at"},
            "first_order": {"$min": "$created_at"},
            "order_count": {"$sum": 1},
            "total_spent": {"$sum": {"$ifNull": ["$total_amount", 0]}},
            "platforms": {"$addToSet": "$platform"}
        }},
        {"$match": {"_id": {"$ne": None}}},
        {"$sort": {"last_order": -1}},
        {"$limit": 200}
    ]

    customers = []
    async for c in db.marketing_orders.aggregate(pipeline):
        last_dt = c["last_order"]
        if hasattr(last_dt, 'tzinfo') and last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        first_dt = c["first_order"]
        if hasattr(first_dt, 'tzinfo') and first_dt.tzinfo is None:
            first_dt = first_dt.replace(tzinfo=timezone.utc)

        recency_days = (now - last_dt).days
        tenure_days = max((now - first_dt).days, 1)
        freq_per_month = c["order_count"] / max(tenure_days / 30, 1)

        # RFM scoring (1–5)
        r = 5 if recency_days <= 14 else 4 if recency_days <= 30 else 3 if recency_days <= 60 else 2 if recency_days <= 90 else 1
        f = 5 if c["order_count"] >= 10 else 4 if c["order_count"] >= 5 else 3 if c["order_count"] >= 3 else 2 if c["order_count"] >= 2 else 1
        m = 5 if c["total_spent"] >= 2000000 else 4 if c["total_spent"] >= 1000000 else 3 if c["total_spent"] >= 500000 else 2 if c["total_spent"] >= 200000 else 1
        rfm = r + f + m

        # Churn risk
        if rfm >= 12:
            risk = "low"
        elif rfm >= 8:
            risk = "medium"
        elif rfm >= 5:
            risk = "high"
        else:
            risk = "critical"

        customers.append({
            "customer": c["_id"],
            "recency_days": recency_days,
            "order_count": c["order_count"],
            "total_spent_rp": round(c["total_spent"]),
            "freq_per_month": round(freq_per_month, 1),
            "r_score": r, "f_score": f, "m_score": m,
            "rfm_total": rfm,
            "churn_risk": risk,
            "platforms": c["platforms"]
        })

    if not customers:
        # 2026-11-02: DULU 15 pelanggan FIKTIF ("Ayu Sari", "Budi Santoso", …) dikarang
        # dengan angka acak, dikirim ke AI, lalu DISIMPAN ke marketing_churn_scores.
        # Sekarang: tanpa data order → hasil kosong yang jujur, tanpa panggilan AI.
        return ok(data=_empty_churn_result(), meta={
            "analyzed_at": _now().isoformat(),
            "message": "Belum ada data order pelanggan untuk dianalisis.",
        })

    # Summary
    segments = {"low": [], "medium": [], "high": [], "critical": []}
    for c in customers:
        segments[c["churn_risk"]].append(c)

    # AI explanation for high/critical customers
    high_risk = [c for c in customers if c["churn_risk"] in ["high", "critical"]][:10]

    # 2026-11-02: gerbang tunggal services.ai (sesudah data dipastikan ada).
    await require_ai("marketing-churn", user_id=user.get("id"), db=db, tier="light")
    ai_system_msg = ("Kamu adalah customer retention specialist untuk brand fashion Indonesia. "
                     "Berikan rekomendasi retensi yang praktis dan empati. Respond only with valid JSON.")

    # K27 (2026-11-02): nama pembeli → kode samaran PLG-xxx; dipetakan balik di server.
    ps = Pseudonymizer()
    high_risk_ai = [{**c, "customer": ps.code(c["customer"], "pelanggan")} for c in high_risk]
    prompt = (
        f"Data customer berisiko churn (high/critical) dari CV Dewi Aditya (fashion brand), "
        f"nama pelanggan disamarkan dengan kode PLG-xxx (pakai kode itu apa adanya):\n"
        f"{json.dumps(high_risk_ai, ensure_ascii=False, indent=2, default=str)}\n\n"
        f"Summary segment: low={len(segments['low'])}, medium={len(segments['medium'])}, high={len(segments['high'])}, critical={len(segments['critical'])}\n\n"
        f"Return JSON persis:\n"
        f"{{\"segment_insights\": {{"
        f"  \"critical\": \"insight 1-2 kalimat\","
        f"  \"high\": \"insight 1-2 kalimat\","
        f"  \"medium\": \"insight 1-2 kalimat\","
        f"  \"low\": \"insight 1-2 kalimat\""
        f"}},"
        f"\"customer_actions\": ["
        f"  {{\"customer\": \"nama\", \"risk\": \"critical\", \"action\": \"aksi retensi konkret\", \"channel\": \"WA/Email/push\", \"message_template\": \"template pesan Bahasa Indonesia\"}}"
        f"],"
        f"\"general_strategy\": \"strategi retensi umum 2-3 kalimat\","
        f"\"quick_wins\": [\"aksi cepat 1\", \"aksi cepat 2\"]}}"
    )

    ai_result = {}
    try:
        response = await ai_text("marketing-churn", ai_system_msg, prompt,
                                 tier="light", user_id=user.get("id"))
        clean = response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:-1])
        ai_result = ps.restore(json.loads(clean))
    except AIError as e:
        logger.warning(f"Churn AI error: {e.code}")
        ai_result = {"general_strategy": f"{e} Skor RFM tetap tersedia.", "quick_wins": []}
    except Exception as e:
        logger.error(f"Churn AI error: {e}")
        ai_result = {"general_strategy": "Penjelasan AI tidak dapat dibaca. Skor RFM tetap tersedia.", "quick_wins": []}

    # Build action map
    action_map = {a.get("customer"): a for a in (ai_result.get("customer_actions") or []) if isinstance(a, dict)}
    for c in customers:
        if c["customer"] in action_map:
            c["ai_action"] = action_map[c["customer"]].get("action")
            c["ai_channel"] = action_map[c["customer"]].get("channel")
            c["ai_template"] = action_map[c["customer"]].get("message_template")

    # Upsert churn scores
    for c in customers:
        await db.marketing_churn_scores.update_one(
            {"customer": c["customer"]},
            {"$set": {**c, "analyzed_at": _now()}},
            upsert=True
        )

    return ok(data={
        "summary": {
            "total_customers": len(customers),
            "segments": {k: len(v) for k, v in segments.items()},
            "segment_insights": ai_result.get("segment_insights", {}),
            "general_strategy": ai_result.get("general_strategy", ""),
            "quick_wins": ai_result.get("quick_wins", [])
        },
        "customers": serialize(customers)
    }, meta={"analyzed_at": _now().isoformat()})


@router.get("/churn/scores")
async def get_churn_scores(
    request: Request,
    risk: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(30)
):
    await require_auth(request)
    db = get_db()
    filt = {}
    if risk:
        filt["churn_risk"] = risk
    total = await db.marketing_churn_scores.count_documents(filt)
    skip = (page - 1) * page_size
    docs = await db.marketing_churn_scores.find(filt).sort("rfm_total", 1).skip(skip).limit(page_size).to_list(page_size)
    return ok(data={"customers": serialize(docs)}, meta={"total": total, "page": page})


# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 5C — A/B TESTING
# ═══════════════════════════════════════════════════════════════════════════

class ABExperimentIn(BaseModel):
    name: str
    hypothesis: str
    test_type: str = "content_hook"    # content_hook | pricing | discount | product_title
    platform: str = "tiktok"
    variants: List[dict] = Field(default=[])
    goal_metric: str = "conversion"    # conversion | ctr | engagement
    duration_days: int = 7


class ABResultIn(BaseModel):
    variant_id: str
    views: Optional[int] = 0
    clicks: Optional[int] = 0
    orders: Optional[int] = 0
    revenue_rp: Optional[float] = 0
    engagement: Optional[float] = 0


@router.post("/ab-tests")
async def create_ab_test(payload: ABExperimentIn, request: Request):
    await require_auth(request)
    db = get_db()

    variants = []
    for i, v in enumerate(payload.variants):
        variants.append({
            "id": str(uuid.uuid4()),
            "label": v.get("label", f"Variant {chr(65+i)}"),
            "content": v.get("content", ""),
            "views": 0, "clicks": 0, "orders": 0, "revenue_rp": 0, "engagement": 0,
            "ctr": 0.0, "conversion_rate": 0.0
        })

    if not variants:
        # Default 2 blank variants
        variants = [
            {"id": str(uuid.uuid4()), "label": "Variant A", "content": "", "views": 0, "clicks": 0, "orders": 0, "revenue_rp": 0, "engagement": 0, "ctr": 0.0, "conversion_rate": 0.0},
            {"id": str(uuid.uuid4()), "label": "Variant B", "content": "", "views": 0, "clicks": 0, "orders": 0, "revenue_rp": 0, "engagement": 0, "ctr": 0.0, "conversion_rate": 0.0}
        ]

    start_date = _now()
    end_date = start_date + timedelta(days=payload.duration_days)

    doc = {
        "id": str(uuid.uuid4()),
        "name": payload.name,
        "hypothesis": payload.hypothesis,
        "test_type": payload.test_type,
        "platform": payload.platform,
        "goal_metric": payload.goal_metric,
        "duration_days": payload.duration_days,
        "status": "draft",
        "variants": variants,
        "winner_variant_id": None,
        "winner_reason": None,
        "start_date": start_date,
        "end_date": end_date,
        "created_at": _now(),
        "updated_at": _now()
    }
    await db.marketing_ab_experiments.insert_one(doc)
    doc.pop("_id", None)
    return ok(data=serialize(doc))


@router.get("/ab-tests")
async def list_ab_tests(
    request: Request,
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20)
):
    await require_auth(request)
    db = get_db()
    filt = {}
    if status:
        filt["status"] = status
    total = await db.marketing_ab_experiments.count_documents(filt)
    skip = (page - 1) * page_size
    docs = await db.marketing_ab_experiments.find(filt).sort("created_at", -1).skip(skip).limit(page_size).to_list(page_size)
    return ok(data={"experiments": serialize(docs)}, meta={"total": total})


@router.get("/ab-tests/{exp_id}")
async def get_ab_test(exp_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    doc = await db.marketing_ab_experiments.find_one({"id": exp_id})
    if not doc:
        raise HTTPException(404, "Experiment tidak ditemukan")
    return ok(data=serialize(doc))


@router.patch("/ab-tests/{exp_id}/status")
async def update_ab_status(
    exp_id: str, request: Request,
    new_status: str = Query(...)
):
    await require_auth(request)
    db = get_db()
    valid = ["draft", "running", "paused", "concluded"]
    if new_status not in valid:
        raise HTTPException(400, f"Status harus salah satu dari {valid}")
    doc = await db.marketing_ab_experiments.find_one({"id": exp_id})
    if not doc:
        raise HTTPException(404, "Experiment tidak ditemukan")
    await db.marketing_ab_experiments.update_one(
        {"id": exp_id},
        {"$set": {"status": new_status, "updated_at": _now()}}
    )
    return ok(data={"status": new_status})


@router.post("/ab-tests/{exp_id}/record")
async def record_ab_result(exp_id: str, payload: ABResultIn, request: Request):
    await require_auth(request)
    db = get_db()
    doc = await db.marketing_ab_experiments.find_one({"id": exp_id})
    if not doc:
        raise HTTPException(404, "Experiment tidak ditemukan")

    variants = doc.get("variants", [])
    updated = False
    for v in variants:
        if v["id"] == payload.variant_id:
            v["views"]     = payload.views or 0
            v["clicks"]    = payload.clicks or 0
            v["orders"]    = payload.orders or 0
            v["revenue_rp"]= payload.revenue_rp or 0
            v["engagement"]= payload.engagement or 0
            v["ctr"]       = round(v["clicks"] / max(v["views"], 1) * 100, 2)
            v["conversion_rate"] = round(v["orders"] / max(v["clicks"], 1) * 100, 2)
            updated = True
            break

    if not updated:
        raise HTTPException(404, "Variant tidak ditemukan")
    await db.marketing_ab_experiments.update_one(
        {"id": exp_id}, {"$set": {"variants": variants, "updated_at": _now()}}
    )
    return ok(data={"message": "Hasil diperbarui"})


@router.post("/ab-tests/{exp_id}/conclude")
async def conclude_ab_test(exp_id: str, request: Request):
    """AI decides winner based on goal metric and data."""
    user = await require_auth(request)
    db = get_db()
    doc = await db.marketing_ab_experiments.find_one({"id": exp_id})
    if not doc:
        raise HTTPException(404, "Experiment tidak ditemukan")
    await require_ai("marketing-ab-conclude", user_id=user.get("id"), db=db, tier="light")

    variants = doc.get("variants", [])
    if not any(v.get("views", 0) > 0 for v in variants):
        raise HTTPException(400, "Belum ada data hasil yang diinput. Gunakan tombol 'Input Hasil' terlebih dahulu.")

    ai_system_msg = ("Kamu adalah analis marketing A/B testing untuk brand fashion Indonesia. "
                     "Berikan kesimpulan yang jelas berdasarkan data. Respond only with valid JSON.")

    prompt = (
        f"A/B Experiment: {doc['name']}\n"
        f"Hypothesis: {doc['hypothesis']}\n"
        f"Goal Metric: {doc['goal_metric']}\n"
        f"Test Type: {doc['test_type']} | Platform: {doc['platform']}\n\n"
        f"Data variants:\n{json.dumps(variants, ensure_ascii=False, indent=2)}\n\n"
        f"Tentukan pemenang berdasarkan goal metric ({doc['goal_metric']}). "
        f"Jika tidak ada perbedaan signifikan (< 5%), nyatakan inconclusive.\n\n"
        f"Return JSON persis:\n"
        f"{{\"winner_label\": \"Variant A atau label pemenang\", "
        f"\"winner_variant_id\": \"id variant\", "
        f"\"is_conclusive\": true, "
        f"\"confidence\": \"high|medium|low\", "
        f"\"winner_reason\": \"alasan 2-3 kalimat mengapa ini pemenang\", "
        f"\"improvement_pct\": 12.5, "
        f"\"key_insight\": \"insight utama dari eksperimen ini\", "
        f"\"recommendation\": \"rekomendasi langkah selanjutnya\"}}"
    )

    try:
        response = await ai_text("marketing-ab-conclude", ai_system_msg, prompt,
                                 tier="light", user_id=user.get("id"))
        clean = response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:-1])
        result = json.loads(clean)
    except AIError as e:
        raise ai_http_error(e)
    except Exception as e:
        logger.error(f"AB conclude error: {e}")
        raise HTTPException(502, "Kesimpulan AI tidak dapat dibaca. Silakan coba lagi.")

    await db.marketing_ab_experiments.update_one(
        {"id": exp_id},
        {"$set": {
            "status": "concluded",
            "winner_variant_id": result.get("winner_variant_id"),
            "winner_label": result.get("winner_label"),
            "winner_reason": result.get("winner_reason"),
            "is_conclusive": result.get("is_conclusive", True),
            "confidence": result.get("confidence"),
            "improvement_pct": result.get("improvement_pct"),
            "key_insight": result.get("key_insight"),
            "recommendation": result.get("recommendation"),
            "updated_at": _now()
        }}
    )
    return ok(data=serialize(result))


@router.patch("/ab-tests/{exp_id}/variants/{variant_id}")
async def update_variant_content(exp_id: str, variant_id: str, request: Request):
    """Update variant content (label, content text)."""
    await require_auth(request)
    body = await request.json()
    db = get_db()
    doc = await db.marketing_ab_experiments.find_one({"id": exp_id})
    if not doc:
        raise HTTPException(404, "Experiment tidak ditemukan")
    variants = doc.get("variants", [])
    for v in variants:
        if v["id"] == variant_id:
            if "label" in body:
                v["label"] = body["label"]
            if "content" in body:
                v["content"] = body["content"]
    await db.marketing_ab_experiments.update_one(
        {"id": exp_id}, {"$set": {"variants": variants, "updated_at": _now()}}
    )
    return ok(data={"message": "Variant diperbarui"})
