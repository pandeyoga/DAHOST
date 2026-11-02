"""
Channel-to-GL Mapping
CV. Dewi Aditya — per-platform revenue routing untuk AR Invoice OS

Collection: rahaza_channel_gl_mapping
Setiap channel penjualan (toko Shopee, TikTok, Tokopedia, Maklon) punya:
  - debit_ar     : akun Piutang yang didebet (1-1301 Maklon / 1-1303 OS)
  - credit_revenue: akun Pendapatan yang dikredit (4-111..4-131, 4-210, 4-220)

Endpoints:
  GET  /api/rahaza/channel-gl-mapping          — list semua channel
  POST /api/rahaza/channel-gl-mapping          — buat channel baru
  PUT  /api/rahaza/channel-gl-mapping/{id}     — update channel
  DELETE /api/rahaza/channel-gl-mapping/{id}   — hapus channel
  POST /api/rahaza/channel-gl-mapping/seed-da  — seed default DA channels

2026-11-02 (D3) — keputusan owner: "Peta Akun Channel seharusnya tidak ada".
COA per toko marketplace sudah ada di master toko (`marketing_platform_accounts`:
`coa_revenue_code`, `ar_account_code`) dan dipakai jurnal pencairan/penarikan;
penjualan non-marketplace lewat Portal Penjualan memakai profil posting
`ar_invoice` (4-1100), bukan peta ini. Karena itu untuk toko MARKETPLACE peta ini
kini BACA-SAJA: GET tetap jalan (baris diberi `read_only`), sedangkan tulis
(POST/PUT/DELETE) dan seed-da menjawab 410 dengan pesan yang menunjuk tempat yang
benar. Menu "Peta Akun Channel" juga dilepas dari Portal Keuangan.
"""

import re

from fastapi import APIRouter, HTTPException, Request
from database import get_db
from auth import require_auth
from datetime import datetime, timezone
import uuid
from core.roles import FINANCE_ROLES  # T-08

router = APIRouter(prefix="/api/rahaza/channel-gl-mapping", tags=["Rahaza-ChannelGL"])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _uid():
    return str(uuid.uuid4())


async def _require_fin(request: Request) -> dict:
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role in FINANCE_ROLES + ("manager",):  # T-08
        return user
    raise HTTPException(403, "Akses ditolak — Finance/Admin only.")


# ─── 2026-11-02 (D3) — peta untuk toko marketplace = BACA-SAJA ────────────────
MARKETPLACE_PLATFORMS = ("shopee", "tiktok", "tiktokshop", "tiktok_shop", "tokopedia",
                         "lazada", "blibli")
GONE_MESSAGE = (
    "Peta Akun Channel untuk toko marketplace sudah dihentikan (keputusan owner D3: "
    "COA per toko, tidak ada peta COA kedua). Akun pendapatan & piutang toko diatur "
    "di master toko (Marketing › Kelola Akun) dan dipakai jurnal pencairan/penarikan. "
    "Penjualan di luar marketplace dicatat lewat Portal Penjualan.")


def is_marketplace_platform(platform) -> bool:
    return (platform or "").strip().lower() in MARKETPLACE_PLATFORMS


async def _is_store_key(db, channel_key) -> bool:
    key = (channel_key or "").strip()
    if not key:
        return False
    return bool(await db.marketing_platform_accounts.find_one(
        {"account_code": {"$regex": f"^{re.escape(key)}$", "$options": "i"}}, {"_id": 0, "id": 1}))


async def _reject_if_marketplace(db, *, platform=None, channel_key=None) -> None:
    if is_marketplace_platform(platform) or await _is_store_key(db, channel_key):
        raise HTTPException(410, GONE_MESSAGE)


# ─── Seed Data: DA Channels ──────────────────────────────────────────────────
# Format: (channel_key, channel_label, platform, debit_ar, credit_revenue)
DA_CHANNELS = [
    # Shopee
    ("shopee_grosirhijabsragen",  "Shopee – Grosirhijabsragen",  "shopee",    "1-1303", "4-1111"),
    ("shopee_daluna",             "Shopee – Daluna",             "shopee",    "1-1303", "4-1112"),
    ("shopee_moen",               "Shopee – Moen",               "shopee",    "1-1303", "4-1113"),
    ("shopee_lainnya",            "Shopee – Lain-lain",          "shopee",    "1-1303", "4-1114"),
    # TikTok Shop
    ("tiktok_daluna",             "TikTok – Daluna",             "tiktok",    "1-1303", "4-1121"),
    ("tiktok_outfit_boutique",    "TikTok – Outfit Boutique",    "tiktok",    "1-1303", "4-1122"),
    ("tiktok_style_by_moen",      "TikTok – Style by Moen",      "tiktok",    "1-1303", "4-1123"),
    ("tiktok_fatimahijab",        "TikTok – Fatimahijab",        "tiktok",    "1-1303", "4-1124"),
    ("tiktok_dezza_kids",         "TikTok – Dezza Kids",         "tiktok",    "1-1303", "4-1125"),
    ("tiktok_lainnya",            "TikTok – Lain-lain",          "tiktok",    "1-1303", "4-1126"),
    # Tokopedia
    ("tokopedia",                 "Tokopedia",                   "tokopedia", "1-1303", "4-1131"),
    # Maklon
    ("maklon_snbm",               "Maklon – SnBm (Sablon & Bordir)", "maklon","1-1301", "4-1510"),
    ("maklon_lainnya",            "Maklon – Klien Lain-lain",    "maklon",    "1-1301", "4-1520"),
]

# ─── Helper: lookup channel GL by key ────────────────────────────────────────
async def get_channel_gl(db, channel_key: str) -> dict | None:
    """Return channel GL mapping doc or None if not found."""
    if not channel_key:
        return None
    return await db.rahaza_channel_gl_mapping.find_one(
        {"channel_key": channel_key, "active": True}, {"_id": 0}
    )


# ─── CRUD ────────────────────────────────────────────────────────────────────
@router.get("")
async def list_channels(request: Request):
    """Daftar semua channel GL mapping, diurutkan per platform."""
    await require_auth(request)
    db = get_db()
    docs = await db.rahaza_channel_gl_mapping.find(
        {"active": True}, {"_id": 0}
    ).sort([("platform", 1), ("channel_label", 1)]).to_list(200)
    # 2026-11-02 (D3) — bentuk respons tetap daftar (pembaca lama tidak rusak);
    # baris toko marketplace ditandai baca-saja beserta alasannya.
    store_codes = {str(c).upper() for c in
                   await db.marketing_platform_accounts.distinct("account_code") if c}
    for d in docs:
        ro = (is_marketplace_platform(d.get("platform"))
              or str(d.get("channel_key") or "").upper() in store_codes)
        d["read_only"] = ro
        if ro:
            d["read_only_reason"] = GONE_MESSAGE
    return docs


@router.post("")
async def create_channel(request: Request):
    """Buat channel GL mapping baru."""
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    channel_key = (body.get("channel_key") or "").strip().lower().replace(" ", "_")
    if not channel_key:
        raise HTTPException(400, "channel_key wajib.")
    await _reject_if_marketplace(db, platform=body.get("platform"), channel_key=channel_key)  # D3
    existing = await db.rahaza_channel_gl_mapping.find_one({"channel_key": channel_key})
    if existing:
        raise HTTPException(409, f"channel_key '{channel_key}' sudah ada.")
    doc = {
        "id": _uid(),
        "channel_key": channel_key,
        "channel_label": body.get("channel_label") or channel_key,
        "platform": (body.get("platform") or "other").lower(),
        "debit_ar": body.get("debit_ar") or "1-1303",
        "credit_revenue": body.get("credit_revenue") or "4-1121",
        "active": True,
        "created_at": _now(), "updated_at": _now(),
        "created_by": user["id"], "created_by_name": user.get("name", ""),
    }
    await db.rahaza_channel_gl_mapping.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@router.put("/{cid}")
async def update_channel(cid: str, request: Request):
    """Update channel GL mapping."""
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    doc = await db.rahaza_channel_gl_mapping.find_one({"id": cid})
    if not doc:
        raise HTTPException(404, "Channel tidak ditemukan.")
    # D3 — baris toko marketplace (atau mengubah baris menjadi marketplace) ditolak.
    await _reject_if_marketplace(db, platform=doc.get("platform"), channel_key=doc.get("channel_key"))
    await _reject_if_marketplace(db, platform=body.get("platform"))
    upd = {
        "channel_label":  body.get("channel_label", doc.get("channel_label")),
        "platform":       body.get("platform", doc.get("platform")),
        "debit_ar":       body.get("debit_ar", doc.get("debit_ar")),
        "credit_revenue": body.get("credit_revenue", doc.get("credit_revenue")),
        "updated_at": _now(),
        "updated_by": user["id"],
        "updated_by_name": user.get("name", ""),
    }
    await db.rahaza_channel_gl_mapping.update_one({"id": cid}, {"$set": upd})
    out = await db.rahaza_channel_gl_mapping.find_one({"id": cid}, {"_id": 0})
    return out


@router.delete("/{cid}")
async def delete_channel(cid: str, request: Request):
    """Soft-delete channel GL mapping."""
    user = await _require_fin(request)
    db = get_db()
    doc = await db.rahaza_channel_gl_mapping.find_one({"id": cid})
    if not doc:
        raise HTTPException(404, "Channel tidak ditemukan.")
    await _reject_if_marketplace(db, platform=doc.get("platform"), channel_key=doc.get("channel_key"))  # D3
    await db.rahaza_channel_gl_mapping.update_one(
        {"id": cid},
        {"$set": {"active": False, "updated_at": _now(), "updated_by": user["id"]}}
    )
    return {"ok": True}


# ─── Seed DA ─────────────────────────────────────────────────────────────────
@router.post("/seed-da")
async def seed_da_channels(request: Request):
    """Seed 13 channel default CV. Dewi Aditya. Idempotent — skip yang sudah ada.

    2026-11-02 (D3) — DIHENTIKAN (410): 11 dari 13 baris adalah toko marketplace
    dan 6 di antaranya menunjuk akun pendapatan yang sudah nonaktif (audit No.8).
    """
    await _require_fin(request)
    raise HTTPException(410, GONE_MESSAGE)
