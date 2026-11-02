"""
PT Rahaza ERP — Integration Settings (API Keys Management)

Endpoints (prefix /api/rahaza/integration-settings):
  GET    /                    — list all keys (values masked)
  POST   /                    — upsert a key
  DELETE /{key_name}          — remove a key
  GET    /test/{key_name}     — cek kunci tersedia (nilai TIDAK pernah dikembalikan)

2026-11-02 (No.60): kategori AI hanya menawarkan ANTHROPIC_API_KEY. Pilihan lama
EMERGENT/OPENAI/GEMINI dihapus; bila masih tersimpan di DB ditandai "tidak dipakai".
Nilai kunci TIDAK PERNAH dikirim utuh ke frontend — hanya bentuk tersamar.

Storage: koleksi `rahaza_integration_settings`
  { key_name, masked_value, description, category, updated_at, updated_by }

Note: Actual values are stored in plain text in the DB (secured by DB access).
      Backend reads from DB first, fallback to environment variable.
"""
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth
from datetime import datetime, timezone
import uuid
import os
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rahaza/integration-settings", tags=["integration-settings"])


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask(value: str) -> str:
    """Bentuk tersamar: panjang TETAP (tidak membocorkan panjang kunci) + 4 karakter akhir.

    2026-11-02: dulu `*` sepanjang kunci — panjang & prefix ikut terlihat.
    """
    if not value:
        return ""
    if len(value) <= 12:
        return "••••••••"
    return "••••••••" + value[-4:]


# Kunci AI lama yang tidak dipakai lagi (No.60: hanya Anthropic).
DEPRECATED_AI_KEYS = {"EMERGENT_LLM_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"}


# ─── Known integration keys with metadata ────────────────────────────────────
KNOWN_KEYS = {
    "ANTHROPIC_API_KEY": {
        "label": "Anthropic API Key (Claude)",
        "description": "Satu-satunya kunci AI. Dipakai semua fitur AI (ringkasan, prediksi kas, "
                       "klasifikasi, asisten ERP, dll). Diambil dari console Anthropic, diawali 'sk-ant-'.",
        "category": "ai",
        "placeholder": "sk-ant-...",
    },
    "WHATSAPP_API_TOKEN": {
        "label": "WhatsApp Business API Token",
        "description": "Token untuk mengirim notifikasi via WhatsApp Business API. Untuk notifikasi alert produksi.",
        "category": "notification",
        "placeholder": "EAA...",
    },
    "TELEGRAM_BOT_TOKEN": {
        "label": "Telegram Bot Token",
        "description": "Token bot Telegram untuk mengirim notifikasi alert produksi.",
        "category": "notification",
        "placeholder": "123456:ABC...",
    },
    "STORAGE_ACCESS_KEY": {
        "label": "Storage Access Key",
        "description": "Kunci akses untuk object storage (S3-compatible) untuk upload file dan gambar.",
        "category": "storage",
        "placeholder": "AKIA...",
    },
    "STORAGE_SECRET_KEY": {
        "label": "Storage Secret Key",
        "description": "Secret key untuk object storage.",
        "category": "storage",
        "placeholder": "wJalr...",
    },
    "SMTP_HOST": {
        "label": "SMTP Host",
        "description": "Host server email untuk pengiriman notifikasi via email.",
        "category": "email",
        "placeholder": "smtp.gmail.com",
    },
    "SMTP_USERNAME": {
        "label": "SMTP Username",
        "description": "Username/email untuk autentikasi SMTP.",
        "category": "email",
        "placeholder": "user@domain.com",
    },
    "SMTP_PASSWORD": {
        "label": "SMTP Password",
        "description": "Password untuk autentikasi SMTP.",
        "category": "email",
        "placeholder": "password",
    },
}


def _invalidate_ai_key_cache(key_name: str) -> None:
    """Kunci Anthropic baru langsung dipakai fitur AI (tanpa menunggu cache 30 dtk)."""
    if key_name == "ANTHROPIC_API_KEY":
        try:
            from ai_cost_tracker import invalidate_api_key_cache, reset_client_cache
            invalidate_api_key_cache()
            reset_client_cache()
        except Exception:  # pragma: no cover
            logger.debug("invalidate AI key cache gagal", exc_info=True)


async def get_integration_key(key_name: str, db=None) -> str | None:
    """
    Resolve integration key: DB first, then environment.
    This function is used by other modules to get API keys.
    """
    # Try DB first
    if db is None:
        db = get_db()
    try:
        doc = await db.rahaza_integration_settings.find_one({"key_name": key_name})
        if doc and doc.get("value"):
            return doc["value"]
    except Exception as e:
        logger.warning(f"Failed to read integration key {key_name} from DB: {e}")
    # Fallback to environment
    return os.environ.get(key_name)


@router.get("")
async def list_settings(request: Request):
    """List all configured integration keys (values masked)."""
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role not in ["superadmin", "admin"]:
        raise HTTPException(403, "Hanya superadmin/admin yang dapat mengakses pengaturan integrasi.")
    db = get_db()

    # Get configured keys from DB
    stored = await db.rahaza_integration_settings.find({}, {"_id": 0}).to_list(500)
    stored_map = {d["key_name"]: d for d in stored}

    # Merge with known keys metadata
    result = []
    for key_name, meta in KNOWN_KEYS.items():
        doc = stored_map.get(key_name)
        # Check if value exists in env
        env_value = os.environ.get(key_name)
        has_env = bool(env_value)
        has_db = bool(doc and doc.get("value"))
        value = doc.get("value") if doc else (env_value or "")
        result.append({
            "key_name": key_name,
            "label": meta["label"],
            "description": meta["description"],
            "category": meta["category"],
            "placeholder": meta["placeholder"],
            "masked_value": _mask(value) if value else "",
            "is_configured": has_db or has_env,
            "source": "db" if has_db else ("env" if has_env else "none"),
            "updated_at": doc.get("updated_at") if doc else None,
            "updated_by": doc.get("updated_by") if doc else None,
        })

    # Also include any custom keys in DB not in KNOWN_KEYS
    for key_name, doc in stored_map.items():
        if key_name not in KNOWN_KEYS:
            value = doc.get("value", "")
            deprecated = key_name in DEPRECATED_AI_KEYS
            result.append({
                "key_name": key_name,
                "label": key_name,
                "description": ("Tidak dipakai lagi — AI kini hanya memakai ANTHROPIC_API_KEY. "
                                "Boleh dihapus.") if deprecated else doc.get("description", ""),
                "category": "custom" if deprecated else doc.get("category", "custom"),
                "deprecated": deprecated,
                "placeholder": "",
                "masked_value": _mask(value) if value else "",
                "is_configured": bool(value),
                "source": "db",
                "updated_at": doc.get("updated_at"),
                "updated_by": doc.get("updated_by"),
            })

    return {"ok": True, "data": result}


@router.post("")
async def upsert_setting(request: Request):
    """Create or update an integration key."""
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role not in ["superadmin", "admin"]:
        raise HTTPException(403, "Hanya superadmin/admin yang dapat mengubah pengaturan integrasi.")
    db = get_db()
    body = await request.json()

    key_name = (body.get("key_name") or "").strip().upper()
    value = (body.get("value") or "").strip()
    description = (body.get("description") or "").strip()
    category = (body.get("category") or "custom").strip()

    if not key_name:
        raise HTTPException(400, "key_name wajib diisi.")
    if not value:
        raise HTTPException(400, "value wajib diisi.")
    # Validate key name format
    import re
    if not re.match(r'^[A-Z0-9_]+$', key_name):
        raise HTTPException(400, "key_name hanya boleh berisi huruf kapital, angka, dan underscore.")
    # 2026-11-02 (No.60): provider AI selain Anthropic tidak dipakai lagi.
    if key_name in DEPRECATED_AI_KEYS:
        raise HTTPException(400, "Kunci AI ini tidak dipakai lagi. Fitur AI hanya memakai ANTHROPIC_API_KEY.")
    if key_name == "ANTHROPIC_API_KEY" and not value.startswith("sk-ant-"):
        raise HTTPException(400, "Format kunci Anthropic tidak valid (harus diawali 'sk-ant-').")

    now = _now()
    doc = {
        "key_name": key_name,
        "value": value,
        "description": description,
        "category": category,
        "updated_at": now,
        "updated_by": user.get("name") or user.get("email") or user.get("id"),
    }
    await db.rahaza_integration_settings.update_one(
        {"key_name": key_name},
        {"$set": doc},
        upsert=True,
    )
    logger.info(f"Integration key {key_name} upserted by {user.get('email')}")
    _invalidate_ai_key_cache(key_name)
    return {
        "ok": True,
        "key_name": key_name,
        "masked_value": _mask(value),
        "updated_at": now,
        "message": f"Kunci {key_name} berhasil disimpan.",
    }


@router.delete("/{key_name}")
async def delete_setting(key_name: str, request: Request):
    """Remove an integration key from DB (will fallback to env)."""
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role not in ["superadmin"]:
        raise HTTPException(403, "Hanya superadmin yang dapat menghapus kunci integrasi.")
    db = get_db()
    key_name = key_name.upper()
    result = await db.rahaza_integration_settings.delete_one({"key_name": key_name})
    if result.deleted_count == 0:
        raise HTTPException(404, f"Kunci {key_name} tidak ditemukan di database.")
    logger.info(f"Integration key {key_name} deleted by {user.get('email')}")
    _invalidate_ai_key_cache(key_name)
    return {"ok": True, "message": f"Kunci {key_name} dihapus dari database. Bila kunci juga diatur di server, nilai server yang dipakai."}


@router.get("/test/{key_name}")
async def test_key(key_name: str, request: Request):
    """Test if a key is resolvable (returns resolved status, not the value)."""
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role not in ["superadmin", "admin"]:
        raise HTTPException(403, "Hanya superadmin/admin yang dapat menguji kunci.")
    db = get_db()
    key_name = key_name.upper()
    value = await get_integration_key(key_name, db)
    if not value:
        return {"ok": False, "source": "none", "message": f"Kunci {key_name} tidak ditemukan.", "has_value": False}
    # Check source
    doc = await db.rahaza_integration_settings.find_one({"key_name": key_name})
    source = "db" if (doc and doc.get("value")) else "env"
    return {"ok": True, "source": source, "has_value": True, "masked_value": _mask(value), "message": f"Kunci {key_name} tersedia dari {source}."}
