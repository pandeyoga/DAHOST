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
    USAGE_LOGS,  # 2026-11-06 (pola P2): koleksi dibaca lewat konstanta penulisnya (satu nama, tidak ada koleksi hantu)
)
from database import get_db
from utils.waktu import today_wib

router = APIRouter(prefix="/api/ai/usage", tags=["ai-usage-monitor"])

# WS-B(d) — grup fitur AI yang dapat di-on/off oleh admin (match by prefix).
# 2026-11-02 (K29): daftar dipindah ke ai_cost_tracker.AI_FEATURE_GROUPS (SSOT) supaya
# label fitur di log (`feature_group`) selalu cocok dengan toggle di layar ini.
# 2026-11-07 (keputusan owner no. 5): semua tier = Claude Opus 5.5 (tier hanya mengatur effort),
# jadi aturan lama K29 "executive khusus Laporan Eksekutif" tidak berlaku lagi untuk tier bawaan.
DEFAULT_TIER_CHOICES = tuple(TIER_MODELS)


async def _check_admin(request: Request):
    """Baca Monitor AI (ringkasan, anggaran, hari ini, pengaturan): centang Manajemen › Monitor AI › Lihat.

    14 Nov 2026: dulu kode peran saja (superadmin/admin/manager/owner) — peran yang dicentang owner ditolak.
    `manager` hanya berlaku selama owner belum mengatur centang peran itu. Mengubah pengaturan tetap owner/admin
    (modul Monitor AI tidak punya aksi Ubah; keputusan owner 10 Nov)."""
    from core.authz import wajib_centang
    user = await require_auth(request)
    return wajib_centang(user, "mod.mgmt_ai_usage.view", peran_lama=("manager",), apa="melihat Monitor AI")


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
    today = today_wib().isoformat()
    settings = await get_ai_settings(db)
    daily_budget = float(settings.get("daily_budget_usd") or DEFAULT_DAILY_BUDGET_USD)

    # Total today
    overall = await db[USAGE_LOGS].aggregate([
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
    top_features = await db[USAGE_LOGS].aggregate([
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
    recent_errors = await db[USAGE_LOGS].aggregate([
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


# ── Asisten AI (proaktif) — Tahap D: validasi kunci pengaturan ingatan & jadwal ─────────────────────────
_PROAKTIF_BOOL = ("asisten_ingatan_aktif", "asisten_briefing_aktif", "asisten_peringatan_aktif",
                  "asisten_laporan_mingguan_aktif")
_PROAKTIF_JAM = {"asisten_briefing_jam": "Jam briefing pagi", "asisten_peringatan_jam": "Jam peringatan harian",
                 "asisten_laporan_mingguan_jam": "Jam laporan mingguan"}
_MAKS_PENERIMA = 20


async def _nilai_proaktif(db, k: str, v):
    """Nilai bersih untuk satu kunci pengaturan Asisten AI proaktif, atau HTTPException 400 (pesan ramah)."""
    from core.asisten_ai import proaktif as _pro
    if k in _PROAKTIF_BOOL:
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "ya", "on")
        if not isinstance(v, (bool, int)):
            raise HTTPException(400, "Saklar Asisten AI harus ya/tidak")
        return bool(v)
    if k in _PROAKTIF_JAM:
        jam = _pro.jam_sah(v)
        if jam is None:
            raise HTTPException(400, f"{_PROAKTIF_JAM[k]} harus berformat JJ:MM (00:00–23:59), mis. 07:00")
        return jam
    # asisten_briefing_penerima — daftar id pengguna aktif; kosong = semua owner aktif.
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise HTTPException(400, "Penerima briefing harus berupa daftar pengguna")
    ids = sorted({x.strip() for x in v})
    if len(ids) > _MAKS_PENERIMA:
        raise HTTPException(400, f"Penerima briefing paling banyak {_MAKS_PENERIMA} orang")
    if ids:
        ada = await db.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "status": 1, "active": 1,
                                                        "is_active": 1}).to_list(_MAKS_PENERIMA + 5)
        sah = {u.get("id") for u in ada if _pro.pengguna_aktif(u)}
        hilang = [x for x in ids if x not in sah]
        if hilang:
            raise HTTPException(400, f"{len(hilang)} penerima briefing tidak ditemukan atau tidak aktif")
    return ids
# ── akhir Asisten AI (proaktif) ──


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
        # Asisten AI (inti) — Tahap B: saklar tindakan + batas harian per pengguna.
        "asisten_tindakan_aktif", "asisten_batas_tindakan_harian",
        # Asisten AI per pengguna (10 Nov 2026): bawaan akun yang belum diatur + batas pertanyaan bawaan.
        "asisten_pengguna_bawaan_aktif", "asisten_batas_pertanyaan_harian",
        # Katalog aksi (12 Nov 2026, K4): batas nominal kartu uang (Rupiah; 0 = setiap kartu uang perlu persetujuan kedua).
        "asisten_batas_nominal_transaksi", "asisten_batas_nominal_harian",
        # Asisten AI (proaktif) — Tahap D: ingatan + briefing/peringatan/laporan mingguan.
        *_PROAKTIF_BOOL, *_PROAKTIF_JAM, "asisten_briefing_penerima",
    }
    update = {}
    for k in allowed:
        if k not in payload:
            continue
        v = payload[k]
        # Asisten AI (proaktif) — saklar, jam "HH:MM" (WIB), daftar penerima (id pengguna aktif).
        if k in _PROAKTIF_BOOL or k in _PROAKTIF_JAM or k == "asisten_briefing_penerima":
            update[k] = await _nilai_proaktif(db, k, v)
            continue
        # ── akhir Asisten AI (proaktif) ──
        if k == "ai_enabled":
            update[k] = bool(v)
        elif k in ("asisten_tindakan_aktif", "asisten_pengguna_bawaan_aktif"):
            update[k] = (v.strip().lower() in ("1", "true", "ya", "on")) if isinstance(v, str) else bool(v)
        elif k in ("asisten_batas_tindakan_harian", "asisten_batas_pertanyaan_harian"):
            label = "Batas tindakan" if k == "asisten_batas_tindakan_harian" else "Batas pertanyaan"
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{label} per pengguna per hari harus bilangan bulat")
            if isinstance(v, bool) or iv < 0 or iv > 1000 or (isinstance(v, float) and not v.is_integer()):
                raise HTTPException(400, f"{label} per pengguna per hari harus 0–1000")
            update[k] = iv
        elif k in ("asisten_batas_nominal_transaksi", "asisten_batas_nominal_harian"):
            label = "Batas nominal per transaksi" if k.endswith("transaksi") else "Batas nominal per hari"
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{label} harus bilangan bulat Rupiah")
            if isinstance(v, bool) or iv < 0 or iv > 10**13 or (isinstance(v, float) and not v.is_integer()):
                raise HTTPException(400, f"{label} harus 0 sampai 10 triliun Rupiah")
            update[k] = iv
        elif k in ("daily_budget_usd", "monthly_budget_usd", "per_feature_daily_usd"):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} harus berupa angka")
            if fv < 0:
                raise HTTPException(400, f"{k} tidak boleh negatif")
            update[k] = round(fv, 4)
        elif k == "default_tier":
            if v not in DEFAULT_TIER_CHOICES:
                raise HTTPException(400, f"default_tier harus salah satu dari {list(DEFAULT_TIER_CHOICES)}")
            update[k] = v
        elif k == "disabled_features":
            if not isinstance(v, list):
                raise HTTPException(400, "disabled_features harus berupa list")
            update[k] = [str(x).strip() for x in v if str(x).strip()]

    if not update:
        raise HTTPException(400, "Tidak ada field valid untuk diupdate")

    # Asisten AI per pengguna (10 Nov 2026): bawaan akun & batas pertanyaan bawaan HANYA diubah owner/superadmin.
    # Admin tetap bisa menyimpan formulir yang sama selama nilainya tidak berubah.
    if user.get("role") not in ("superadmin", "owner"):
        lama = await get_ai_settings(db, force=True)
        for k in ("asisten_pengguna_bawaan_aktif", "asisten_batas_pertanyaan_harian"):
            if k in update and update[k] != lama.get(k):
                raise HTTPException(403, "Hanya owner atau superadmin yang boleh mengubah bawaan Asisten AI per pengguna.")
        for k in ("asisten_batas_nominal_transaksi", "asisten_batas_nominal_harian"):
            if k in update and update[k] != int(lama.get(k) or 0):
                raise HTTPException(403, "Hanya owner atau superadmin yang boleh mengubah batas nominal Asisten AI.")

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    update["updated_by"] = user.get("email") or user.get("id")
    await db.ai_config.update_one({"id": "global"}, {"$set": update, "$setOnInsert": {"id": "global"}}, upsert=True)
    invalidate_ai_settings_cache()

    settings = await get_ai_settings(db, force=True)
    return {"success": True, "data": settings, "message": "Setting AI berhasil disimpan"}


# ── Asisten AI per pengguna (10 Nov 2026, keputusan owner) ───────────────────
# Saklar aktif/mati + batas pertanyaan & tindakan per akun (`users.asisten_ai`, aturan di
# core/asisten_ai/akses_pengguna.py). Daftar: superadmin/admin/owner (sama dengan pengubah setting AI);
# mengubah: HANYA owner/superadmin. Owner & superadmin selalu aktif (tidak bisa dimatikan).
PERAN_LIHAT_PENGGUNA_AI = ("superadmin", "admin", "owner")
PERAN_UBAH_PENGGUNA_AI = ("superadmin", "owner")
_PROYEKSI_PENGGUNA_AI = {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1, "status": 1, "active": 1,
                         "is_active": 1, "asisten_ai": 1}


def _peran_tanpa_asisten() -> set:
    """Peran yang ditolak router Asisten AI (eksternal + portal marketing) — tidak ditampilkan di daftar."""
    from core.authz import EXTERNAL_ROLES, MARKETING_PORTAL_ROLES
    return {*EXTERNAL_ROLES, *MARKETING_PORTAL_ROLES}


async def _pemakaian_asisten_hari_ini(db) -> tuple[dict, dict, dict]:
    """({uid: pertanyaan}, {uid: tindakan}, {uid: biaya USD}) hari ini (WIB)."""
    from core.asisten_ai import akses_pengguna as akp
    from core.asisten_ai.tindakan import KEADAAN_TERHITUNG
    from utils.waktu import wib_date_str
    pertanyaan = await akp.pertanyaan_per_pengguna(db)
    tindakan: dict = {}
    async for r in db.ai_actions.find({"tanggal_jalan": wib_date_str(), "keadaan": {"$in": list(KEADAAN_TERHITUNG)}},
                                      {"_id": 0, "user_id": 1}):
        if r.get("user_id"):
            tindakan[r["user_id"]] = tindakan.get(r["user_id"], 0) + 1
    biaya: dict = {}
    async for r in db[USAGE_LOGS].find({"date": today_wib().isoformat(), "feature_group": "asisten-ai"},
                                       {"_id": 0, "user_id": 1, "cost_usd": 1}):
        if r.get("user_id"):
            biaya[r["user_id"]] = biaya.get(r["user_id"], 0.0) + float(r.get("cost_usd") or 0)
    return pertanyaan, tindakan, biaya


def _baris_pengguna_ai(u: dict, settings: dict, pemakaian: tuple) -> dict:
    from core.asisten_ai import akses_pengguna as akp
    aturan = akp.aturan_dari(u, u.get("role"), settings)
    cfg = u.get("asisten_ai") if isinstance(u.get("asisten_ai"), dict) else {}
    pertanyaan, tindakan, biaya = pemakaian
    uid = u.get("id")
    return {
        "id": uid, "name": u.get("name") or u.get("email") or "", "email": u.get("email") or "",
        "role": u.get("role") or "", **aturan,
        "atur": {"aktif": cfg.get("aktif") if isinstance(cfg.get("aktif"), bool) else None,
                 "batas_pertanyaan_harian": akp.bilangan_batas(cfg.get("batas_pertanyaan_harian")),
                 "batas_tindakan_harian": akp.bilangan_batas(cfg.get("batas_tindakan_harian")),
                 "golongan": akp.golongan_tersimpan(cfg)},
        "diubah_oleh": cfg.get("diubah_oleh"), "diubah_at": cfg.get("diubah_at"),
        "pertanyaan_hari_ini": int(pertanyaan.get(uid, 0)), "tindakan_hari_ini": int(tindakan.get(uid, 0)),
        "biaya_hari_ini_usd": round(float(biaya.get(uid, 0.0)), 4),
    }


@router.get("/asisten-pengguna")
async def daftar_asisten_pengguna(request: Request):
    """Akun internal aktif + status Asisten AI efektif, batas, dan pemakaian hari ini."""
    from core.asisten_ai import akses_pengguna as akp
    from core.asisten_ai import proaktif as _pro
    user = await require_auth(request)
    if user.get("role") not in PERAN_LIHAT_PENGGUNA_AI:
        raise HTTPException(403, "Hanya owner, superadmin, atau admin yang bisa melihat Asisten AI per pengguna.")
    db = get_db()
    settings = await get_ai_settings(db, force=True)
    tolak = _peran_tanpa_asisten()
    rows = await db.users.find({}, dict(_PROYEKSI_PENGGUNA_AI)).to_list(2000)
    rows = [u for u in rows if u.get("id") and str(u.get("role") or "").lower() not in tolak
            and _pro.pengguna_aktif(u)]
    pemakaian = await _pemakaian_asisten_hari_ini(db)
    items = sorted((_baris_pengguna_ai(u, settings, pemakaian) for u in rows),
                   key=lambda r: (not r["aktif"], str(r["name"]).lower()))
    return {"success": True, "data": {
        "bawaan": akp.bawaan_dari(settings), "boleh_ubah": user.get("role") in PERAN_UBAH_PENGGUNA_AI,
        "items": items, "tanggal": today_wib().isoformat()}}


@router.put("/asisten-pengguna/{uid}")
async def ubah_asisten_pengguna(uid: str, request: Request, payload: dict = Body(...)):
    """{aktif: true|false|null, batas_pertanyaan_harian: n|null, batas_tindakan_harian: n|null,
    golongan: {B|C|D: true|false|null}} — null = ikut bawaan (golongan: mati)."""
    from core.asisten_ai import akses_pengguna as akp
    from routes.rahaza_audit import log_audit
    user = await require_auth(request)
    if user.get("role") not in PERAN_UBAH_PENGGUNA_AI:
        raise HTTPException(403, "Hanya owner atau superadmin yang boleh mengubah Asisten AI per pengguna.")
    db = get_db()
    target = await db.users.find_one({"id": uid}, dict(_PROYEKSI_PENGGUNA_AI))
    if not target:
        raise HTTPException(404, "Pengguna tidak ditemukan.")
    if str(target.get("role") or "").lower() in _peran_tanpa_asisten():
        raise HTTPException(400, "Akun ini (vendor, buyer, atau portal marketing) tidak bisa memakai Asisten AI.")
    try:
        isian = akp.rapikan_masukan(payload if isinstance(payload, dict) else {}, peran_target=target.get("role"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    sebelum = target.get("asisten_ai") if isinstance(target.get("asisten_ai"), dict) else {}
    sesudah = await akp.simpan(db, uid, isian, oleh=user.get("email") or user.get("id") or "")
    await log_audit(db, entity_type="user", entity_id=uid, action="asisten_ai_pengguna",
                    before={k: sebelum.get(k) for k in isian}, after={k: sesudah.get(k) for k in isian},
                    user=user, request=request)
    target["asisten_ai"] = sesudah
    settings = await get_ai_settings(db, force=True)
    return {"success": True, "data": _baris_pengguna_ai(target, settings, await _pemakaian_asisten_hari_ini(db)),
            "message": "Asisten AI untuk pengguna ini disimpan."}
# ── akhir Asisten AI per pengguna ──
