"""/api/assets/disposal-requests (list + approve/reject) and /{asset_id}/(dispose|request-disposal).

This module MUST be imported BEFORE `assets_core` so that the literal
`/disposal-requests` paths are registered before the catch-all `/{asset_id}`.
"""
from datetime import date
from fastapi import Request, HTTPException

from database import get_db
from auth import require_auth
from ._helpers import router, _uid, _now, _ser


def _can_decide_finance(user: dict) -> bool:
    """Admin/owner, peran yang bisa membuka Portal Keuangan, atau peran lama finance/manager.
    2026-11-02: dulu hanya ("admin","superadmin","finance","manager") — peran `finance` tidak ada di
    sistem sehingga Keuangan (accounting/staff_keuangan) tidak bisa menyetujui pelepasan."""
    from routes.shared import SUPER_ROLES, check_portal_access
    role = (user.get("role") or "").lower()
    return role in SUPER_ROLES or role in ("superadmin", "finance", "manager") or check_portal_access(user, "finance")


async def _execute_disposal(db, asset: dict, disposal_date: str, disposal_value: float, reason: str, user: dict) -> dict:
    """2026-11-02 (K18): Portal Aset TIDAK lagi membuat jurnal pelepasan sendiri.

    Aset tertaut registri Keuangan → pelepasan & jurnal lewat SATU jalur Keuangan
    (`routes.rahaza_fixed_assets.dispose_fixed_asset`: NBV per tanggal pelepasan, akun milik aset,
    tolak tanggal sebelum penyusutan terakhir). Aset belum tertaut → status operasional saja, tanpa jurnal
    (nilai bukunya memang tidak ada di neraca). Dulu: jurnal draft akun profil + Dr 1-1201 tetap."""
    fid = asset.get("fixed_asset_id")
    if fid:
        if not _can_decide_finance(user):
            raise HTTPException(403, "Aset ini tertaut registri Keuangan: pelepasan (dan jurnalnya) hanya oleh Keuangan "
                                     "— ajukan 'Permintaan Pelepasan' agar disetujui Keuangan.")
        from routes.rahaza_fixed_assets import dispose_fixed_asset
        res = await dispose_fixed_asset(db, fid, {"disposal_date": disposal_date, "disposal_value": disposal_value,
                                                  "notes": reason}, user)
        return {"gain_loss": res.get("gain_loss"), "nbv": res.get("nbv_at_disposal"),
                "journal_id": ((res.get("posting_result") or {}).get("je_id")),
                "journal_number": ((res.get("posting_result") or {}).get("je_number")),
                "posting_result": res.get("posting_result"), "value_source": "finance_registry"}
    cost = float(asset.get("purchase_cost") or 0)
    accum = float(asset.get("accumulated_depreciation") or 0)
    return {"gain_loss": round(disposal_value - (cost - accum), 2), "nbv": round(cost - accum, 2),
            "journal_id": None, "journal_number": None, "posting_result": None, "value_source": "unlinked",
            "note": "Aset belum tertaut ke registri Keuangan — dilepas secara operasional tanpa jurnal."}


# ─── List + approve + reject (LITERAL paths → must register early) ──────────────────

@router.get("/disposal-requests")
async def list_disposal_requests(request: Request, status: str = "pending"):
    """List permintaan disposal. Status: pending | approved | rejected | all."""
    await require_auth(request)
    db = get_db()
    filt = {}
    if status != "all":
        filt["status"] = status
    reqs = await db.dewi_asset_disposal_requests.find(filt, {"_id": 0}).sort("requested_at", -1).to_list(100)
    return [_ser(r) for r in reqs]


@router.patch("/disposal-requests/{req_id}/approve")
async def approve_disposal_request(req_id: str, request: Request):
    """Approve permintaan disposal → eksekusi dispose + jurnal Finance."""
    user = await require_auth(request)
    if not _can_decide_finance(user):
        raise HTTPException(403, "Hanya admin/Keuangan/manager yang bisa approve disposal.")
    db = get_db()
    req = await db.dewi_asset_disposal_requests.find_one({"id": req_id})
    if not req:
        raise HTTPException(404, "Request tidak ditemukan.")
    if req["status"] != "pending":
        raise HTTPException(400, f"Request sudah {req['status']}.")

    body = await request.json()
    notes = (body.get("notes") or "").strip()

    asset = await db.dewi_assets.find_one({"id": req["asset_id"]})
    if not asset:
        raise HTTPException(404, "Aset tidak ditemukan.")

    disposal_value = float(req.get("disposal_value", 0))
    res = await _execute_disposal(db, asset, req["disposal_date"], disposal_value, req.get("reason", ""), user)
    gain_loss = float(res.get("gain_loss") or 0)
    je_id = res.get("journal_id")

    now = _now()
    await db.dewi_assets.update_one(
        {"id": asset["id"]},
        {"$set": {
            "status": "disposed", "disposed_at": now,
            "disposal_value": disposal_value,
            "disposal_reason": req.get("reason", ""),
            "disposal_journal_id": je_id,
            "updated_at": now,
        }},
    )
    await db.dewi_asset_disposal_requests.update_one(
        {"id": req_id},
        {"$set": {
            "status": "approved", "reviewed_by": user["id"],
            "reviewed_by_name": user.get("name", ""),
            "reviewed_at": now, "review_notes": notes, "journal_id": je_id,
        }},
    )
    return {"ok": True, "gain_loss": round(gain_loss, 2), "journal_id": je_id, "disposal": res}


@router.patch("/disposal-requests/{req_id}/reject")
async def reject_disposal_request(req_id: str, request: Request):
    """Reject permintaan disposal → kembalikan status aset ke active."""
    user = await require_auth(request)
    if not _can_decide_finance(user):
        raise HTTPException(403, "Hanya admin/Keuangan/manager yang bisa reject disposal.")
    db = get_db()
    req = await db.dewi_asset_disposal_requests.find_one({"id": req_id})
    if not req:
        raise HTTPException(404, "Request tidak ditemukan.")
    if req["status"] != "pending":
        raise HTTPException(400, f"Request sudah {req['status']}.")

    body = await request.json()
    notes = (body.get("notes") or "").strip()

    now = _now()
    await db.dewi_asset_disposal_requests.update_one(
        {"id": req_id},
        {"$set": {
            "status": "rejected", "reviewed_by": user["id"],
            "reviewed_by_name": user.get("name", ""),
            "reviewed_at": now, "review_notes": notes,
        }},
    )
    await db.dewi_assets.update_one(
        {"id": req["asset_id"]},
        {"$set": {"status": "active", "updated_at": now}},
    )
    return {"ok": True}


# ─── Per-asset disposal actions (registered later for path-priority safety) ────────────────────────────
# NOTE: These start with /{asset_id}/ but they live AFTER `/disposal-requests`
# because that route is registered above. FastAPI matches by registration order.

@router.post("/{asset_id}/dispose")
async def dispose_asset(asset_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    asset = await db.dewi_assets.find_one({"id": asset_id})
    if not asset:
        raise HTTPException(404, "Aset tidak ditemukan.")
    if asset.get("status") == "disposed":
        raise HTTPException(400, "Aset sudah dilepas.")
    body = await request.json()
    disposal_date = (body.get("disposal_date") or date.today().isoformat())[:10]
    disposal_value = float(body.get("disposal_value") or 0)
    reason = (body.get("reason") or "").strip()

    res = await _execute_disposal(db, asset, disposal_date, disposal_value, reason, user)
    gain_loss = res.get("gain_loss")
    je_id = res.get("journal_id")
    await db.dewi_assets.update_one(
        {"id": asset_id},
        {"$set": {
            "status": "disposed",
            "disposed_at": _now(),
            "disposal_value": disposal_value,
            "disposal_reason": reason,
            "disposal_journal_id": je_id,
            "updated_at": _now(),
        }},
    )
    return {"ok": True, "gain_loss": gain_loss, "journal_id": je_id, "disposal": res}


@router.post("/{asset_id}/request-disposal")
async def request_disposal(asset_id: str, request: Request):
    """Buat permintaan disposal untuk aset bernilai tinggi (NBV > threshold)."""
    user = await require_auth(request)
    db = get_db()
    asset = await db.dewi_assets.find_one({"id": asset_id})
    if not asset:
        raise HTTPException(404, "Aset tidak ditemukan.")
    if asset.get("status") == "disposed":
        raise HTTPException(400, "Aset sudah dilepas.")

    cost = float(asset.get("purchase_cost", 0))
    accum = float(asset.get("accumulated_depreciation", 0))
    nbv = cost - accum

    existing = await db.dewi_asset_disposal_requests.find_one(
        {"asset_id": asset_id, "status": "pending"}
    )
    if existing:
        raise HTTPException(400, "Sudah ada permintaan disposal yang menunggu approval.")

    body = await request.json()
    disposal_date = (body.get("disposal_date") or date.today().isoformat())[:10]
    disposal_value = float(body.get("disposal_value") or 0)
    reason = (body.get("reason") or "").strip()

    if not reason:
        raise HTTPException(400, "Alasan disposal wajib diisi.")

    doc = {
        "id": _uid(),
        "asset_id": asset_id,
        "asset_number": asset.get("asset_number", ""),
        "asset_name": asset.get("name", ""),
        "nbv": round(nbv, 2),
        "disposal_date": disposal_date,
        "disposal_value": disposal_value,
        "reason": reason,
        "status": "pending",
        "requested_by": user["id"],
        "requested_by_name": user.get("name", ""),
        "requested_at": _now(),
        "reviewed_by": None,
        "reviewed_by_name": "",
        "reviewed_at": None,
        "review_notes": "",
        "journal_id": None,
    }
    await db.dewi_asset_disposal_requests.insert_one(doc)
    await db.dewi_assets.update_one(
        {"id": asset_id},
        {"$set": {"status": "pending_disposal", "updated_at": _now()}},
    )
    return _ser(doc)
