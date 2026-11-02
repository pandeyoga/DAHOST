"""
Session 19 — E-3: AI Cost Monitoring API

Endpoints (prefix: /api/ai/usage)
- GET  /summary              — aggregated stats (period configurable)
- GET  /logs                 — recent log entries
- GET  /budgets              — current budget configuration
- GET  /today                — today's usage status (real-time)

Access: superadmin / admin / manager / owner only.
"""
from fastapi import APIRouter, Request, Query, HTTPException, Body
from datetime import datetime, timezone, timedelta
from auth import require_auth
from ai_cost_tracker import (
    get_usage_summary,
    get_recent_logs,
    get_ai_settings,
    invalidate_ai_settings_cache,
    ai_status,
    effective_budgets,
    month_to_date_cost,
    AI_FEATURE_GROUPS,
    TIER_MODELS,
    DEFAULT_DAILY_BUDGET_USD,
    DEFAULT_MONTHLY_BUDGET_USD,
    DEFAULT_PER_FEATURE_DAILY_USD,
)
from database import get_db

router = APIRouter(prefix="/api/ai/usage", tags=["ai-usage-monitor"])

# WS-B(d) — grup fitur AI yang dapat di-on/off oleh admin (match by prefix).
# 2026-11-02 (K29): daftar dipindah ke ai_cost_tracker.AI_FEATURE_GROUPS (SSOT) supaya
# label fitur di log (`feature_group`) selalu cocok dengan toggle di layar ini.
# Tier yang boleh jadi default: executive (Opus) KHUSUS Laporan Eksekutif.
DEFAULT_TIER_CHOICES = tuple(k for k in TIER_MODELS if k != "executive")


async def _check_admin(request: Request):
    user = await require_auth(request)
    if user.get("role") not in ["superadmin", "admin", "manager", "owner"]:
        raise HTTPException(403, "Admin access required")
    return user


@router.get("/summary")
async def usage_summary(request: Request, days: int = Query(7, ge=1, le=90)):
    await _check_admin(request)
    summary = await get_usage_summary(days)
    return {"success": True, "data": summary}


@router.get("/logs")
async def usage_logs(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    feature: str = Query(None),
):
    await _check_admin(request)
    logs = await get_recent_logs(limit, feature)
    return {"success": True, "data": logs}


@router.get("/budgets")
async def get_budgets(request: Request):
    await _check_admin(request)
    # 2026-11-02 (K29): anggaran EFEKTIF (setelan Monitor AI → env), bukan angka env bawaan.
    return {
        "success": True,
        "data": {
            **(await effective_budgets(get_db())),
            "info": "Atur batas anggaran di tab Pengaturan Monitor AI.",
        },
    }


@router.get("/today")
async def today_status(request: Request):
    await _check_admin(request)
    db = get_db()
    today = datetime.now(timezone.utc).date().isoformat()
    settings = await get_ai_settings(db)
    daily_budget = float(settings.get("daily_budget_usd") or DEFAULT_DAILY_BUDGET_USD)

    # Total today
    overall = await db.rahaza_ai_usage_logs.aggregate([
        {"$match": {"date": today}},
        {"$group": {
            "_id": None,
            "calls": {"$sum": 1},
            "successful": {"$sum": {"$cond": ["$success", 1, 0]}},
            "failed": {"$sum": {"$cond": ["$success", 0, 1]}},
            "cost_usd": {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$tokens_total"},
        }},
    ]).to_list(length=1)
    stats = overall[0] if overall else {
        "calls": 0, "successful": 0, "failed": 0, "cost_usd": 0, "tokens": 0
    }
    stats.pop("_id", None)
    cost = round(stats.get("cost_usd", 0), 4)

    # Top features today
    top_features = await db.rahaza_ai_usage_logs.aggregate([
        {"$match": {"date": today}},
        {"$group": {
            "_id": "$feature",
            "calls": {"$sum": 1},
            "cost_usd": {"$sum": "$cost_usd"},
        }},
        {"$project": {
            "_id": 0, "feature": "$_id", "calls": 1,
            "cost_usd": {"$round": ["$cost_usd", 4]},
        }},
        {"$sort": {"cost_usd": -1}},
        {"$limit": 10},
    ]).to_list(length=10)

    pct_daily = (cost / daily_budget * 100) if daily_budget > 0 else 0
    # 2026-11-02 (K29): batas bulanan dari setelan yang sama ikut ditampilkan & menentukan status.
    monthly_budget = float(settings.get("monthly_budget_usd") or DEFAULT_MONTHLY_BUDGET_USD)
    month_cost = round(await month_to_date_cost(db), 4)
    pct_monthly = (month_cost / monthly_budget * 100) if monthly_budget > 0 else 0

    # 2026-11-02: status JUJUR — dulu "healthy" walau kunci kosong & SDM tidak terpasang,
    # karena panggilan yang gagal sebelum ke Anthropic tidak pernah dicatat.
    status = await ai_status(db)
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent_errors = await db.rahaza_ai_usage_logs.aggregate([
        {"$match": {"success": False, "created_at": {"$gte": since_24h}}},
        {"$group": {"_id": {"$ifNull": ["$error_code", "lainnya"]}, "n": {"$sum": 1},
                    "last_at": {"$max": "$created_at"}, "message": {"$last": "$error"}}},
        {"$sort": {"n": -1}},
    ]).to_list(length=20)
    recent_error_count = sum(int(r.get("n") or 0) for r in recent_errors)
    health = _health_label(
        ai_available=status["available"], ai_enabled=bool(settings.get("ai_enabled", True)),
        pct_daily=max(pct_daily, pct_monthly), successful=int(stats.get("successful", 0) or 0),
        failed=int(stats.get("failed", 0) or 0),
    )

    return {
        "success": True,
        "data": {
            "date": today,
            "total_calls": stats.get("calls", 0),
            "successful_calls": stats.get("successful", 0),
            "failed_calls": stats.get("failed", 0),
            "total_cost_usd": cost,
            "total_tokens": stats.get("tokens", 0),
            "daily_budget_usd": daily_budget,
            "budget_used_pct": round(pct_daily, 1),
            "monthly_budget_usd": monthly_budget,
            "month_cost_usd": month_cost,
            "monthly_used_pct": round(pct_monthly, 1),
            "health": health,
            "top_features": top_features,
            "ai_available": status["available"],
            "ai_enabled": bool(settings.get("ai_enabled", True)),
            "ai_status": {
                "code": status["code"],
                "message": status["message"],
                "key_configured": status["key_configured"],
                "key_source": status["key_source"],
                "sdk_installed": status["sdk_installed"],
                "sdk_version": status["sdk_version"],
            },
            "recent_error_count": recent_error_count,
            "recent_errors": [
                {"code": r["_id"], "count": r["n"], "last_at": r.get("last_at"), "message": r.get("message")}
                for r in recent_errors
            ],
        },
    }


def _health_label(*, ai_available: bool, ai_enabled: bool, pct_daily: float,
                  successful: int, failed: int) -> str:
    """Status kesehatan AI hari ini (2026-11-02).

    `offline`  : AI tidak bisa dipakai (kunci kosong / SDK tidak terpasang)
    `disabled` : dimatikan admin (master switch)
    `error`    : ada panggilan gagal dan tidak ada yang sukses / ≥50% gagal
    selain itu berdasar pemakaian anggaran: critical/warning/monitor/healthy
    """
    if not ai_available:
        return "offline"
    if not ai_enabled:
        return "disabled"
    total = successful + failed
    if failed > 0 and (successful == 0 or failed / max(total, 1) >= 0.5):
        return "error"
    return (
        "critical" if pct_daily >= 100 else
        "warning" if pct_daily >= 80 else
        "monitor" if pct_daily >= 50 else
        "healthy"
    )


# ── WS-B(d): AI Settings (Admin gear) ────────────────────────────────────────
@router.get("/settings")
async def get_settings(request: Request):
    """Setting AI saat ini (budget, tier default, master switch, toggle fitur)."""
    await _check_admin(request)
    db = get_db()
    settings = await get_ai_settings(db, force=True)
    return {
        "success": True,
        "data": {
            **settings,
            "feature_groups": AI_FEATURE_GROUPS,
            "tiers": list(DEFAULT_TIER_CHOICES),
            "executive_features": ["executive-narrative"],  # K29: satu-satunya pemakai Opus
            "tier_models": {k: f"{v[0]}/{v[1]}" for k, v in TIER_MODELS.items()},
            "ai_status": await ai_status(db),
            "env_defaults": {
                "daily_budget_usd": DEFAULT_DAILY_BUDGET_USD,
                "monthly_budget_usd": DEFAULT_MONTHLY_BUDGET_USD,
                "per_feature_daily_usd": DEFAULT_PER_FEATURE_DAILY_USD,
            },
        },
    }


@router.put("/settings")
async def update_settings(request: Request, payload: dict = Body(...)):
    """Update setting AI. Hanya superadmin/admin/owner (bukan manager)."""
    user = await require_auth(request)
    if user.get("role") not in ["superadmin", "admin", "owner"]:
        raise HTTPException(403, "Hanya admin/owner yang boleh mengubah setting AI")
    db = get_db()

    allowed = {
        "ai_enabled", "daily_budget_usd", "monthly_budget_usd",
        "per_feature_daily_usd", "default_tier", "disabled_features",
    }
    update = {}
    for k in allowed:
        if k not in payload:
            continue
        v = payload[k]
        if k == "ai_enabled":
            update[k] = bool(v)
        elif k in ("daily_budget_usd", "monthly_budget_usd", "per_feature_daily_usd"):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} harus berupa angka")
            if fv < 0:
                raise HTTPException(400, f"{k} tidak boleh negatif")
            update[k] = round(fv, 4)
        elif k == "default_tier":
            # K29 (2026-11-02): Opus (executive) hanya untuk Laporan Eksekutif, bukan default.
            if v not in DEFAULT_TIER_CHOICES:
                raise HTTPException(400, f"default_tier harus salah satu dari {list(DEFAULT_TIER_CHOICES)} "
                                         "(executive/Opus khusus Laporan Eksekutif)")
            update[k] = v
        elif k == "disabled_features":
            if not isinstance(v, list):
                raise HTTPException(400, "disabled_features harus berupa list")
            update[k] = [str(x).strip() for x in v if str(x).strip()]

    if not update:
        raise HTTPException(400, "Tidak ada field valid untuk diupdate")

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    update["updated_by"] = user.get("email") or user.get("id")
    await db.ai_config.update_one({"id": "global"}, {"$set": update, "$setOnInsert": {"id": "global"}}, upsert=True)
    invalidate_ai_settings_cache()

    settings = await get_ai_settings(db, force=True)
    return {"success": True, "data": settings, "message": "Setting AI berhasil disimpan"}
