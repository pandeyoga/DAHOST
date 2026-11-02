"""Output AI = USULAN yang dikonfirmasi pengguna (K28, keputusan owner 2026-11-02).

AI tidak lagi menimpa nilai resmi (kategori/severity komplain, kategori ulasan,
`ai_score` kandidat). Hasilnya disimpan sebagai `ai_suggestion`:

    {"values": {...}, "reason": "...", "confidence": 0.9, "feature": "...",
     "status": "pending", "suggested_at": iso, "suggested_by": "...", ...}

Pengguna menekan Terima / Ubah / Tolak → `decide_suggestion()` memvalidasi nilai
akhir ke enum yang sah, mengembalikan patch nilai resmi + usulan yang sudah
diputuskan (aktor & waktu dicatat SAAT keputusan, nilai lama ikut disimpan).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Union

from fastapi import HTTPException
from pydantic import BaseModel

from services.ai.privacy import pick_enum

SUGGESTION_ACTIONS = ("accept", "modify", "reject")
_STATUS_AFTER = {"accept": "accepted", "modify": "modified", "reject": "rejected"}

Validator = Union[tuple, list, frozenset, set, Callable[[Any], Any]]


class SuggestionDecision(BaseModel):
    """Body endpoint keputusan usulan AI (dipakai komplain, ulasan, kandidat)."""
    action: str
    values: Optional[dict] = None
    note: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def actor_label(user: Optional[dict]) -> str:
    u = user or {}
    return u.get("name") or u.get("email") or u.get("id") or "-"


def new_suggestion(values: Mapping[str, Any], *, feature: str, user: Optional[dict] = None,
                   reason: Any = "", confidence: Any = None, extra: Optional[dict] = None) -> dict:
    """Bentuk dokumen usulan AI yang seragam (status `pending`)."""
    try:
        conf = None if confidence is None else round(max(0.0, min(1.0, float(confidence))), 3)
    except (TypeError, ValueError):
        conf = None
    doc = {
        "values": dict(values),
        "reason": str(reason or "")[:1000],
        "confidence": conf,
        "feature": feature,
        "status": "pending",
        "suggested_at": _now_iso(),
        "suggested_by": actor_label(user),        # yang MEMINTA usulan (bukan yang memutuskan)
        "suggested_by_id": (user or {}).get("id"),
    }
    if extra:
        doc.update(extra)
    return doc


def _validate(field: str, value: Any, rule: Validator):
    if callable(rule):
        try:
            return rule(value)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, f"Nilai '{field}' tidak sah: {e}")
    ok = pick_enum(value, rule)
    if ok is None:
        raise HTTPException(400, f"Nilai '{field}' tidak sah. Pilihan: {', '.join(map(str, rule))}")
    return ok


def decide_suggestion(suggestion: Optional[dict], decision: SuggestionDecision, *,
                      user: dict, rules: Mapping[str, Validator],
                      current: Optional[Mapping[str, Any]] = None) -> tuple[dict, dict]:
    """Putuskan usulan. Return (patch_nilai_resmi, usulan_setelah_diputuskan).

    - accept : nilai usulan dipakai apa adanya (tetap divalidasi ulang).
    - modify : nilai usulan ditimpa `decision.values` (hanya field di `rules`).
    - reject : nilai resmi TIDAK berubah.
    `current` = nilai resmi sebelum keputusan → disimpan sebagai `previous_values`.
    """
    if not suggestion:
        raise HTTPException(404, "Tidak ada usulan AI untuk data ini.")
    if suggestion.get("status") != "pending":
        raise HTTPException(409, f"Usulan AI sudah diputuskan ({suggestion.get('status')}).")
    action = str(decision.action or "").strip().lower()
    if action not in SUGGESTION_ACTIONS:
        raise HTTPException(400, "Aksi harus accept (Terima), modify (Ubah), atau reject (Tolak).")

    official: dict = {}
    if action in ("accept", "modify"):
        proposed = dict(suggestion.get("values") or {})
        if action == "modify":
            overrides = {k: v for k, v in (decision.values or {}).items() if k in rules and v is not None}
            if not overrides:
                raise HTTPException(400, "Isi nilai yang diubah (Ubah) terlebih dahulu.")
            proposed.update(overrides)
        for field, rule in rules.items():
            if field in proposed and proposed[field] is not None:
                official[field] = _validate(field, proposed[field], rule)
        if not official:
            raise HTTPException(400, "Usulan AI tidak berisi nilai yang sah untuk diterapkan.")

    decided = {
        **suggestion,
        "status": _STATUS_AFTER[action],
        "final_values": official,
        "previous_values": {k: (current or {}).get(k) for k in rules},
        "decided_by": actor_label(user),
        "decided_by_id": user.get("id"),
        "decided_at": _now_iso(),
        "decision_note": (decision.note or "")[:500],
    }
    return official, decided
