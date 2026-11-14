"""
CV. Dewi Aditya — Approval Delegation (Phase 9.4 P2)

Manager delegates their approval authority to someone else during leave/absence.

Collection: rahaza_approval_delegations
  { id, delegator_id (user), delegatee_id (user), scope: ['leave','overtime','all'],
    start_date, end_date, reason, is_active, created_at, revoked_at }

Usage: When resolving approver for a resource:
  1. Check if delegator has active delegation today for this scope
  2. If yes, route approval to delegatee
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth
from core.roles import HR_ROLES  # T-01 2.3
from utils.waktu import today_wib

router = APIRouter(prefix="/api/rahaza/delegations", tags=["rahaza-delegations"])


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)
def _s(d):
    if not d:
        return None
    d = dict(d)
    d.pop("_id", None)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


async def get_active_delegation(db, user_id: str, scope: str = "all") -> Optional[dict]:
    """Check if user_id has active delegation for given scope today."""
    today = today_wib().isoformat()
    return await db.rahaza_approval_delegations.find_one({
        "delegator_id": user_id,
        "is_active": True,
        "start_date": {"$lte": today},
        "end_date": {"$gte": today},
        "$or": [{"scopes": scope}, {"scopes": "all"}],
    }, {"_id": 0})


@router.get("")
async def list_delegations(request: Request, active_only: bool = False):
    await require_auth(request)
    db = get_db()
    filt = {}
    if active_only:
        today = today_wib().isoformat()
        filt = {"is_active": True, "start_date": {"$lte": today}, "end_date": {"$gte": today}}
    docs = await db.rahaza_approval_delegations.find(filt, {"_id": 0}).sort("start_date", -1).to_list(500)
    return {"ok": True, "delegations": [_s(d) for d in docs]}


@router.post("")
async def create_delegation(request: Request):
    user = await require_auth(request)
    db = get_db()
    body = await request.json()

    delegator_id = body.get("delegator_id") or user["id"]
    delegatee_id = body.get("delegatee_id")
    if not delegatee_id:
        raise HTTPException(400, "delegatee_id wajib.")
    if delegatee_id == delegator_id:
        raise HTTPException(400, "Tidak bisa delegasi ke diri sendiri.")

    doc = {
        "id": _uid(),
        "delegator_id": delegator_id,
        "delegator_name": body.get("delegator_name") or user.get("name", ""),
        "delegatee_id": delegatee_id,
        "delegatee_name": body.get("delegatee_name") or "",
        "scopes": body.get("scopes") or ["all"],  # ['leave','overtime','all']
        "start_date": body.get("start_date") or today_wib().isoformat(),
        "end_date": body.get("end_date") or today_wib().isoformat(),
        "reason": body.get("reason") or "",
        "is_active": True,
        "created_at": _now(),
        "revoked_at": None,
    }
    await db.rahaza_approval_delegations.insert_one(doc)
    return {"ok": True, "delegation": _s(doc)}


@router.delete("/{delegation_id}")
async def revoke_delegation(delegation_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    doc = await db.rahaza_approval_delegations.find_one({"id": delegation_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Delegation tidak ditemukan.")
    # T-01 2.3: hanya pendelegasi sendiri atau HR/admin yang boleh mencabut.
    # Pendelegasi sendiri (kepemilikan) atau pengelola SDM: centang aksi endpoint (Struktur Organisasi & Delegasi) /
    # izin hr.manage; 14 Nov 2026: kode peran HR hanya selama owner belum mengatur centang peran itu.
    from core.authz import boleh_centang, pesan_centang
    if doc.get("delegator_id") != user.get("id") and not boleh_centang(user, "hr.manage", peran_lama=HR_ROLES):
        raise HTTPException(403, "Delegasi ini milik orang lain. " + pesan_centang(user, apa="mencabut delegasi orang lain"))
    res = await db.rahaza_approval_delegations.update_one(
        {"id": delegation_id},
        {"$set": {"is_active": False, "revoked_at": _now()}}
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Delegation tidak ditemukan.")
    return {"ok": True}
