"""core/bulk_approve.py — SATU implementasi bulk approve (FASE 5 / T-20).

Dulu tiga salinan identik di employee_expense_claims / employee_travel_requests /
employee_travel_settlements, masing-masing dengan APPROVER_ROLES sendiri (akar T-08).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from fastapi import HTTPException

from auth import log_activity
from core.authz import izin_atau_peran_lama  # 14 Nov 2026: centang owner = penentu
from core.roles import APPROVER_ROLES, EXPENSE_APPROVE_PERMS

logger = logging.getLogger(__name__)


async def bulk_approve(db, user: dict, ids: Iterable[str], *, collection: str, number_field: str, module: str,
                       approval_note: str = "", allowed_roles=APPROVER_ROLES,
                       allowed_perms=EXPENSE_APPROVE_PERMS,
                       allowed_from_status=("submitted",)) -> dict:
    # 2026-11-08: kode peran ATAU izin approve (sama dengan tombol setujui satu per satu) — peran buatan owner.
    if not izin_atau_peran_lama(user, allowed_roles, allowed_perms):
        from core.authz import pesan_centang
        raise HTTPException(403, pesan_centang(user, apa="menyetujui"))
    ids = list(ids)
    results = {"success": [], "failed": []}
    coll = db[collection]
    for doc_id in ids:
        try:
            doc = await coll.find_one({"id": doc_id}, {"_id": 0})
            if not doc:
                results["failed"].append({"id": doc_id, "reason": "Tidak ditemukan"})
                continue
            if doc.get("status") not in allowed_from_status:
                results["failed"].append({"id": doc_id, "reason": f'Status {doc.get("status")} tidak bisa di-approve'})
                continue
            now = datetime.now(timezone.utc)
            await coll.update_one({"id": doc_id, "status": {"$in": list(allowed_from_status)}}, {"$set": {
                "status": "approved", "approved_at": now, "approved_by": user.get("id"),
                "approved_by_name": user.get("name"), "approval_note": approval_note or "", "updated_at": now,
            }})
            await log_activity(user.get("id"), user.get("name"), "approve", module,
                               f"Bulk approve {module} {doc.get(number_field)}")
            results["success"].append(doc_id)
        except Exception as e:  # noqa: BLE001
            logger.error("Bulk approve %s %s error: %s", module, doc_id, e)
            results["failed"].append({"id": doc_id, "reason": str(e)})
    return {"ok": True, "total": len(ids), "success_count": len(results["success"]),
            "failed_count": len(results["failed"]), "results": results}
