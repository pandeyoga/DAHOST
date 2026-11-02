"""Core CRUD for assets: list (GET /), create (POST /), get (GET /{id}), update (PUT /{id}).

The LITERAL `/{asset_id}` path MUST be registered AFTER all other literal endpoints
(disposal-requests, expiring-alerts, my-assets, scan-by-number, batch-depreciate,
reports/*, predictive-maintenance/*, bulk-import/*).
The orchestrator `dewi_asset_management.py` enforces this load order.
"""
from datetime import date
import math
from typing import Optional
from fastapi import Request, HTTPException, Query

from database import get_db
from auth import require_auth
from ._helpers import (
    router, _uid, _now, _ser,
    _calc_straight_line_monthly,
    _ensure_default_categories, _gen_asset_number,
    load_finance_assets, apply_finance_overlay, validate_finance_link,
)


@router.get("")
async def list_assets(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    category_id: Optional[str] = None,
    search: Optional[str] = None,
    assigned_to: Optional[str] = None,
):
    await require_auth(request)
    db = get_db()
    query: dict = {}
    if status:
        query["status"] = status
    if category_id:
        query["category_id"] = category_id
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"asset_number": {"$regex": search, "$options": "i"}},
            {"serial_number": {"$regex": search, "$options": "i"}},
        ]
    if assigned_to:
        query["assigned_to_id"] = assigned_to

    total = await db.dewi_assets.count_documents(query)
    skip = (page - 1) * limit
    assets = await db.dewi_assets.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    # K18: nilai keuangan aset tertaut dari registri Keuangan
    fin = await load_finance_assets(db, [a.get("fixed_asset_id") for a in assets])
    return {
        "items": [_ser(apply_finance_overlay(a, fin.get(a.get("fixed_asset_id")))) for a in assets],
        "pagination": {
            "page": page, "page_size": limit, "total": total,
            "total_pages": math.ceil(total / limit) if total else 1,
        },
    }


@router.post("")
async def create_asset(request: Request):
    user = await require_auth(request)
    db = get_db()
    await _ensure_default_categories(db)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nama aset wajib diisi.")
    # K18: tautan ke registri Keuangan (opsional saat ini; nilai keuangan diambil dari sana)
    fixed_asset_id = (body.get("fixed_asset_id") or "").strip() or None
    fa = await validate_finance_link(db, fixed_asset_id) if fixed_asset_id else None
    purchase_cost = float((fa or {}).get("purchase_cost") or body.get("purchase_cost") or 0)
    if purchase_cost <= 0:
        raise HTTPException(400, "Harga beli harus lebih dari 0.")
    if fa and not body.get("purchase_date"):
        body["purchase_date"] = fa.get("purchase_date")

    cat = None
    if body.get("category_id"):
        cat = await db.dewi_asset_categories.find_one({"id": body["category_id"]}, {"_id": 0})
    if not cat:
        cat = {"id": "", "name": "Lain-lain", "code": "LN",
               "useful_life_years": 5, "depr_method": "straight_line"}

    useful_life_months = int(body.get("useful_life_months") or (cat["useful_life_years"] * 12))
    residual_value = float(body.get("residual_value") or purchase_cost * 0.05)
    depr_method = body.get("depr_method") or cat.get("depr_method", "straight_line")

    asset_number = await _gen_asset_number(db, cat["code"],
                                           (body.get("asset_number") or "").strip())
    purchase_date = (body.get("purchase_date") or date.today().isoformat())[:10]
    monthly_depr = _calc_straight_line_monthly(purchase_cost, residual_value, useful_life_months)

    doc = {
        "id": _uid(),
        "asset_number": asset_number,
        "name": name,
        "category_id": cat["id"],
        "category_name": cat["name"],
        "purchase_date": purchase_date,
        "purchase_cost": purchase_cost,
        "residual_value": residual_value,
        "useful_life_months": useful_life_months,
        "depreciation_method": depr_method,
        "monthly_depreciation": monthly_depr,
        "accumulated_depreciation": 0.0,
        "location": (body.get("location") or "").strip(),
        "serial_number": (body.get("serial_number") or "").strip(),
        "brand": (body.get("brand") or "").strip(),
        "model": (body.get("model") or "").strip(),
        "department": (body.get("department") or "").strip(),
        "status": "active",
        "assigned_to_id": None,
        "assigned_to_name": None,
        "notes": (body.get("notes") or "").strip(),
        "procurement_request_id": body.get("procurement_request_id"),
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "created_at": _now(),
        "updated_at": _now(),
        "disposed_at": None,
        "journal_purchase_id": None,
        "warranty_expiry_date": (body.get("warranty_expiry_date") or "")[:10] or None,
        "warranty_provider":    (body.get("warranty_provider") or "").strip(),
        "warranty_terms":       (body.get("warranty_terms") or "").strip(),
        "insurance_policy_number": (body.get("insurance_policy_number") or "").strip(),
        "insurance_provider":      (body.get("insurance_provider") or "").strip(),
        "insurance_expiry_date":   (body.get("insurance_expiry_date") or "")[:10] or None,
        "insurance_value":         float(body.get("insurance_value") or 0),
        "fixed_asset_id":          fixed_asset_id,
        "fixed_asset_code":        (fa or {}).get("code"),
    }

    # 2026-11-02 (K18): TANPA jurnal. Dulu jurnal draft Dr 1-2500 / Cr 1-1201 (selalu dianggap
    # tunai BCA) — bila diposting, saldo BCA turun walau aset dibeli kredit. Jurnal perolehan kini
    # hanya dari Keuangan › Aset Tetap (pilihan sumber dana) atau jalur GR.
    await db.dewi_assets.insert_one(doc)
    fin = await load_finance_assets(db, [fixed_asset_id])
    return _ser(apply_finance_overlay(doc, fin.get(fixed_asset_id)))


@router.get("/{asset_id}")
async def get_asset(asset_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    asset = await db.dewi_assets.find_one({"id": asset_id}, {"_id": 0})
    if not asset:
        raise HTTPException(404, "Aset tidak ditemukan.")

    cost = float(asset.get("purchase_cost", 0))
    residual = float(asset.get("residual_value", 0))
    accum = float(asset.get("accumulated_depreciation", 0))
    nbv = cost - accum

    # K18: Portal Aset tidak lagi menyusutkan (koleksi riwayat lamanya tidak ditulis lagi);
    # riwayat penyusutan aset tertaut diambil dari jadwal registri Keuangan di bawah.
    depr_history = []

    asset_out = _ser(asset)
    asset_out["nbv"] = round(nbv, 2)
    asset_out["depreciation_history"] = [_ser(d) for d in depr_history]
    fin = (await load_finance_assets(db, [asset.get("fixed_asset_id")])).get(asset.get("fixed_asset_id"))
    apply_finance_overlay(asset_out, fin)  # K18: nilai buku dari registri Keuangan bila tertaut
    if fin:
        asset_out["depreciation_history"] = [_ser(d) for d in await db.rahaza_depr_schedules.find(
            {"asset_id": fin["id"], "posted": True}, {"_id": 0}).sort("period", -1).limit(12).to_list(12)]
    asset_out["fully_depreciated"] = asset_out["nbv"] <= residual
    return asset_out


@router.put("/{asset_id}")
async def update_asset(asset_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    asset = await db.dewi_assets.find_one({"id": asset_id})
    if not asset:
        raise HTTPException(404, "Aset tidak ditemukan.")
    body = await request.json()
    allowed = [
        "name", "location", "serial_number", "brand", "model",
        "department", "notes", "status",
        "warranty_expiry_date", "warranty_provider", "warranty_terms",
        "insurance_policy_number", "insurance_provider",
        "insurance_expiry_date", "insurance_value",
    ]
    update = {k: body[k] for k in allowed if k in body}
    # K18: menaut / melepas tautan aset Keuangan (registri induk)
    if "fixed_asset_id" in body:
        fid = (body.get("fixed_asset_id") or "").strip() or None
        fa = await validate_finance_link(db, fid, own_asset_id=asset_id) if fid else None
        update["fixed_asset_id"] = fid
        update["fixed_asset_code"] = (fa or {}).get("code")
        if fa:
            update["purchase_cost"] = float(fa.get("purchase_cost") or 0)
    if update:
        update["updated_at"] = _now()
        await db.dewi_assets.update_one({"id": asset_id}, {"$set": update})
    return {"ok": True}
