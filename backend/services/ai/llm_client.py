"""Unified LLM client (Claude via the official Anthropic SDK).

2026-11-02 (No.60): SATU lapisan provider untuk semua route AI:

    routes → services.ai (ai_text / ai_json_call / call_claude / cached_call_claude)
           → ai_cost_tracker.tracked_llm_call → Anthropic

Aturan:
1. Route TIDAK boleh membaca env kunci sendiri (gerbang lama `EMERGENT_LLM_KEY`
   dihapus) — pakai `require_ai()` / `ai_available()`.
2. Model dipilih lewat TIER (executive/standard/light), tidak pernah nama model.
3. Galat ke pengguna selalu pesan ramah berbahasa Indonesia (`ai_http_error`);
   nama variabel env dan isi exception mentah tidak pernah dikirim ke frontend.
4. Cache respons tingkat aplikasi (MongoDB) agar prompt sama tidak dibayar dua kali.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from fastapi import HTTPException

import ai_cost_tracker as _tracker
from ai_cost_tracker import AIError, ai_available, ai_status, friendly_error, http_status_for

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = _tracker.TIER_MODELS[_tracker.DEFAULT_TIER][1]

__all__ = [
    "AIError", "LLMUnavailable", "ai_available", "ai_status", "require_ai",
    "ai_http_error", "ai_text", "ai_json_call", "call_claude", "cached_call_claude",
    "get_llm_key", "friendly_error",
]


class LLMUnavailable(HTTPException):
    """503 ramah saat AI belum bisa dipakai (kunci kosong / SDK tidak terpasang / dimatikan)."""

    def __init__(self, detail: Optional[str] = None):
        super().__init__(status_code=503, detail=detail or friendly_error("not_configured"))


def ai_http_error(err: Exception) -> HTTPException:
    """Ubah galat AI apa pun menjadi HTTPException berpesan ramah (tanpa detail teknis)."""
    if isinstance(err, HTTPException):
        return err
    code = getattr(err, "code", None) or "internal"
    message = str(err) if isinstance(err, AIError) else friendly_error(code)
    if code in _tracker.UNAVAILABLE_CODES:
        return LLMUnavailable(message)
    return HTTPException(status_code=http_status_for(code), detail=message)


async def require_ai(feature: str = "ai", *, user_id: Optional[str] = None, db=None,
                     tier: str = _tracker.DEFAULT_TIER) -> None:
    """Gerbang fitur AI: raise LLMUnavailable (503, ramah) bila AI belum siap.

    Percobaan yang ditolak dicatat ke log pemakaian supaya Monitor AI
    menampilkan "AI mati" + jumlah galat, bukan "healthy".
    """
    st = await ai_status(db)
    if not st["available"]:
        await _tracker.record_ai_failure(feature, st["code"], user_id=user_id, tier=tier)
        raise LLMUnavailable(st["message"])


async def get_llm_key(db=None) -> str:
    """Kompatibilitas: kunci Anthropic (DB → env) atau LLMUnavailable."""
    key, _src = await _tracker.resolve_api_key(db)
    if key:
        return key
    raise LLMUnavailable()


async def ai_text(
    feature: str,
    system_message: str,
    user_message: str,
    *,
    tier: str = _tracker.DEFAULT_TIER,
    user_id: Optional[str] = None,
    max_tokens: Optional[int] = None,
    image_base64: Optional[str] = None,
) -> str:
    """Panggil Claude, kembalikan teks. Raise AIError (pesan ramah + `.code`) bila gagal."""
    res = await _tracker.tracked_llm_call(
        feature=feature, user_id=user_id, model=tier,
        system_message=system_message, user_message=user_message,
        image_base64=image_base64, max_tokens=max_tokens,
    )
    if not res.success:
        raise AIError(res.error, over_budget=res.over_budget, code=res.error_code)
    return res.text


async def ai_json_call(
    feature: str,
    system_message: str,
    user_message: str,
    *,
    tier: str = _tracker.DEFAULT_TIER,
    user_id: Optional[str] = None,
    max_tokens: Optional[int] = None,
    image_base64: Optional[str] = None,
):
    """Seperti `ai_text` tetapi mem-parse JSON. Gagal parse → AIError(code='bad_output')."""
    text = await ai_text(feature, system_message, user_message, tier=tier, user_id=user_id,
                         max_tokens=max_tokens, image_base64=image_base64)
    try:
        return _tracker.extract_json(text)
    except Exception:
        raise AIError(code="bad_output")


async def call_claude(
    system_message: str,
    user_message: str,
    *,
    session_tag: str = "ai",
    db=None,
    tier: str = "standard",
    user_id: Optional[str] = None,
) -> str:
    """Satu titik panggilan untuk route lama. Return teks.

    `session_tag` menjadi label fitur di log pemakaian (sufiks id dibuang).

    Raises:
        LLMUnavailable(503): kunci kosong / SDK tidak terpasang / AI dimatikan admin.
        HTTPException(429/502/504): anggaran habis / galat layanan AI (pesan ramah).
    """
    resolved_tier = tier if tier in _tracker.TIER_MODELS else "standard"
    try:
        return await ai_text(session_tag, system_message, user_message,
                             tier=resolved_tier, user_id=user_id)
    except AIError as e:
        if e.code not in _tracker.UNAVAILABLE_CODES:
            logger.warning("AI call gagal (%s): %s", session_tag, e.code)
        raise ai_http_error(e)


# ---------------------------------------------------------------------------
# Cached call (app-level cache via MongoDB).
# ---------------------------------------------------------------------------
def _hash_cache_key(parts: list[str]) -> str:
    payload = "\u0001".join(p or "" for p in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def cached_call_claude(
    db,
    *,
    system_message: str,
    user_message: str,
    cache_namespace: str,
    cache_key_extra: list[str] | None = None,
    ttl_seconds: int = 3600,
    session_tag: str = "ai",
    tier: str = "standard",
) -> dict[str, Any]:
    """LLM call with application-level cache (MongoDB).

    Returns:
        dict with keys: text (str), cache_hit (bool), generated_at (iso str).
    """
    from datetime import datetime, timezone, timedelta

    extra = cache_key_extra or []
    key_hash = _hash_cache_key([cache_namespace, tier, system_message, user_message, *extra])
    now = datetime.now(timezone.utc)

    # Try cache hit
    try:
        cached = await db.ai_response_cache.find_one({"key_hash": key_hash}, {"_id": 0})
        if cached:
            exp = cached.get("expires_at")
            # expires_at stored as ISO string for portability
            if exp and isinstance(exp, str) and exp > now.isoformat():
                return {
                    "text": cached.get("text", ""),
                    "cache_hit": True,
                    "generated_at": cached.get("generated_at", now.isoformat()),
                }
    except Exception as e:  # pragma: no cover
        logger.warning("AI cache read error: %s", e)

    # Miss → call LLM
    text = await call_claude(
        system_message=system_message,
        user_message=user_message,
        session_tag=session_tag,
        db=db,
        tier=tier,
    )

    # Persist cache (fire-and-forget style; failure should not break user response)
    try:
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
        await db.ai_response_cache.update_one(
            {"key_hash": key_hash},
            {"$set": {
                "key_hash": key_hash,
                "namespace": cache_namespace,
                "text": text,
                "generated_at": now.isoformat(),
                "expires_at": expires_at,
                "ttl_seconds": ttl_seconds,
            }},
            upsert=True,
        )
    except Exception as e:  # pragma: no cover
        logger.warning("AI cache write error: %s", e)

    return {"text": text, "cache_hit": False, "generated_at": now.isoformat()}
