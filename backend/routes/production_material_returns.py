"""
Production Material Returns — Pengembalian Material dari Lantai Produksi ke Gudang
CV. Dewi Aditya — Task 2.5

Prefix: /api/production/material-returns

Alur:
  Production staff submit return → Supervisor produksi approve → Gudang receive → stok +

2026-11-02 (K10) — layar "Retur Material" (`prod-material-returns`, RahazaMaterialReturnModule.jsx):
  pilih MI / Surat Jalan asal (`GET /sources`, `GET /source`) → qty retur ≤ sisa (`returnable_now`)
  → supervisor setuju → gudang terima di lokasi WAJIB → stok kembali + jurnal balik pada HPP saat keluar
  (Dr persediaan / Cr WIP atau biaya proyek) + `qty_returned` & `return_status` baris MI.

Colleciton: production_material_returns
"""
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
from database import get_db
from auth import require_auth, log_activity
from utils.counters import next_counter, gen_prefixed_number
from core import stock_service
import logging
from core.authz import only  # T-01 2.3
from core.roles import PRODUCTION_ROLES  # T-01 2.3
from utils.waktu import fmt_wib

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/production/material-returns", tags=["production-material-returns"])


def _coerce_id(id_str: str):
    """Coba konversi ke int, fallback ke string untuk MongoDB lookup."""
    try:
        return int(id_str)
    except (ValueError, TypeError):
        return id_str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Pydantic ─────────────────────────────────────────────────────────────────

class ReturnItem(BaseModel):
    material_id: str = ""
    material_code: str = ""
    material_name: str = ""
    qty_returned: float = Field(ge=0)
    unit: str = "pcs"
    reason: str = "sisa_produksi"   # sisa_produksi | rusak | salah_material
    condition: str = "good"          # good | damaged | scrap
    note: str = ""


class ReturnCreateModel(BaseModel):
    work_order_id: str = ""
    work_order_code: str = ""
    production_line: str = ""
    return_reason: str = ""          # alasan umum
    notes: str = ""
    items: List[ReturnItem] = Field(default_factory=list)
    # 2026-11-02 (K10): jalur koreksi Surat Jalan material (Kirim Material CMT) yang bahannya sudah
    # keluar — retur ditautkan ke Material Issue asal (langsung, atau lewat surat jalannya).
    material_issue_id: str = ""
    vendor_shipment_id: str = ""


class ReturnUpdateModel(BaseModel):
    notes: Optional[str] = None
    items: Optional[List[ReturnItem]] = None
    return_reason: Optional[str] = None


class ActionModel(BaseModel):
    note: str = ""
    # 2026-11-02 — No.18(a): lokasi penerimaan retur DIPILIH gudang (dipakai /receive).
    location_id: Optional[str] = None


# ─── Helper ───────────────────────────────────────────────────────────────────

def _ok(data=None, message="", **kwargs):
    r = {"status": "ok"}
    if message:
        r["message"] = message
    if data is not None:
        r["data"] = data
    r.update(kwargs)
    return r


async def _build_ref(db) -> str:
    prefix = f"PMR/{fmt_wib('%Y/%m/')}"
    # RC-5 fix: atomic race-safe numbering (was count_documents()+1)
    # 2026-11-02 (K10): layar "Retur Material" hidup lagi (koreksi Surat Jalan material yang bahannya
    # sudah keluar) → jenis dokumen ini kembali terdaftar di katalog penomoran
    # (`production_material_returns.ref_no`, otomatis) dan pengecualian G12-nya dicabut.
    return await gen_prefixed_number(db, "production_material_returns", "ref_no", prefix, 4)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_returns(
    request: Request,
    status: Optional[str] = None,
    work_order_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    await require_auth(request)
    db = get_db()
    q = {}
    if status:
        q["status"] = status
    if work_order_id:
        q["work_order_id"] = work_order_id
    total = await db.production_material_returns.count_documents(q)
    items = await db.production_material_returns.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return _ok(items, total=total, skip=skip, limit=limit)


async def _resolve_mi(db, material_issue_id: str = "", vendor_shipment_id: str = "") -> Optional[dict]:
    """MI asal retur (2026-11-02, K10): id MI langsung, atau MI 'issued' milik surat jalan material."""
    if material_issue_id:
        mi = await db.rahaza_material_issues.find_one({"id": material_issue_id}, {"_id": 0})
        if not mi:
            raise HTTPException(404, "Material Issue asal tidak ditemukan.")
    elif vendor_shipment_id:
        mi = await db.rahaza_material_issues.find_one(
            {"vendor_shipment_id": vendor_shipment_id, "status": "issued"}, {"_id": 0})
        if not mi:
            raise HTTPException(400, "Surat jalan ini tidak punya Material Issue yang sudah keluar — "
                                     "tidak ada bahan untuk diretur (surat jalan boleh dihapus).")
    else:
        return None
    if mi.get("status") != "issued":
        raise HTTPException(400, f"MI {mi.get('mi_number')} berstatus '{mi.get('status')}' — hanya MI yang "
                                 "bahannya sudah keluar yang bisa diretur.")
    return mi


def mi_returnable(mi: dict) -> dict:
    """{material_id: qty yang masih bisa diretur} = dikeluarkan − sudah diretur (fungsi murni)."""
    out: dict = {}
    for it in mi.get("items") or []:
        mid = it.get("material_id")
        if not mid:
            continue
        out[mid] = out.get(mid, 0.0) + float(it.get("qty_issued") or 0) - float(it.get("qty_returned") or 0)
    return {k: round(v, 4) for k, v in out.items()}


def mi_after_return(mi: dict, returned: dict) -> dict:
    """Baris MI + `return_status` setelah retur `returned` {material_id: qty baik} (fungsi murni).
    Status dokumen MI TETAP 'issued' (dibaca HPP & gerbang produksi); retur dicatat per baris."""
    left = dict(returned)
    items = []
    for it in mi.get("items") or []:
        it = dict(it)
        mid = it.get("material_id")
        cap = max(0.0, float(it.get("qty_issued") or 0) - float(it.get("qty_returned") or 0))
        take = min(cap, left.get(mid, 0.0))
        if take > 0:
            it["qty_returned"] = round(float(it.get("qty_returned") or 0) + take, 4)
            left[mid] = round(left[mid] - take, 4)
        items.append(it)
    issued = sum(float(i.get("qty_issued") or 0) for i in items)
    ret = sum(float(i.get("qty_returned") or 0) for i in items)
    status = "full" if issued > 0 and ret >= issued - 1e-6 else ("partial" if ret > 1e-9 else None)
    return {"items": items, "return_status": status, "qty_returned_total": round(ret, 4)}


def deduct_pending(can: dict, pending_docs) -> dict:
    """Sisa yang bisa diretur dikurangi retur lain yang MASIH BERJALAN (fungsi murni, 2026-11-02 K10)."""
    out = dict(can)
    for p in pending_docs or []:
        for it in p.get("items") or []:
            if it.get("material_id") in out:
                out[it["material_id"]] = round(out[it["material_id"]] - float(it.get("qty_returned") or 0), 4)
    return out


async def returnable_now(db, mi: dict, exclude_return_id=None) -> dict:
    """{material_id: sisa} = dikeluarkan − sudah diretur − retur submitted/approved lain atas MI yang sama.
    Satu-satunya rumus sisa retur — dipakai form (`/source`), pembuatan, dan submit."""
    q: dict = {"material_issue_id": mi["id"], "status": {"$in": ["submitted", "approved"]}}
    if exclude_return_id is not None:
        q["id"] = {"$ne": exclude_return_id}
    pending = await db.production_material_returns.find(q, {"_id": 0, "items": 1}).to_list(200)
    return deduct_pending(mi_returnable(mi), pending)


def qty_errors(items: list, can: dict) -> list:
    """Pesan error per material bila qty retur > sisa (fungsi murni)."""
    want: dict = {}
    label: dict = {}
    for it in items or []:
        mid = it.get("material_id")
        want[mid] = want.get(mid, 0.0) + float(it.get("qty_returned") or 0)
        label[mid] = it.get("material_code") or mid
    return [f"'{label.get(mid)}': retur {q:g} > sisa {max(0.0, can.get(mid, 0.0)):g}"
            for mid, q in want.items() if q - can.get(mid, 0.0) > 0.001]


# ─── 2026-11-02 (K10): sumber retur untuk layar Retur Material ──────────────────
# Path literal WAJIB dideklarasikan sebelum `/{return_id}`.
@router.get("/sources")
async def list_return_sources(request: Request, q: str = "", limit: int = Query(30, ge=1, le=100)):
    """MI yang bahannya sudah keluar & belum diretur penuh (pilihan MI / Surat Jalan di form retur)."""
    await require_auth(request)
    db = get_db()
    flt: dict = {"status": "issued", "return_status": {"$ne": "full"}}
    if q.strip():
        import re as _re
        rx = {"$regex": _re.escape(q.strip()), "$options": "i"}
        flt["$or"] = [{"mi_number": rx}, {"vendor_shipment_number": rx}, {"wo_number_snapshot": rx},
                      {"po_number_snapshot": rx}, {"vendor_name": rx}]
    rows = await db.rahaza_material_issues.find(flt, {"_id": 0}).sort("issued_at", -1).limit(limit).to_list(limit)
    out = []
    for mi in rows:
        can = mi_returnable(mi)
        if not any(v > 0.0001 for v in can.values()):
            continue
        out.append({"id": mi["id"], "mi_number": mi.get("mi_number"), "issued_at": mi.get("issued_at"),
                    "vendor_shipment_id": mi.get("vendor_shipment_id") or "",
                    "vendor_shipment_number": mi.get("vendor_shipment_number") or "",
                    "vendor_name": mi.get("vendor_name") or "", "return_status": mi.get("return_status"),
                    "wo_number": mi.get("wo_number_snapshot") or mi.get("po_number_snapshot") or "",
                    "lines": len(can)})
    return _ok(out)


@router.get("/source")
async def get_return_source(request: Request, material_issue_id: str = "", vendor_shipment_id: str = ""):
    """MI asal + baris yang masih bisa diretur (sisa = keluar − sudah diretur − retur berjalan)."""
    await require_auth(request)
    db = get_db()
    mi = await _resolve_mi(db, material_issue_id, vendor_shipment_id)
    if not mi:
        raise HTTPException(400, "Pilih Material Issue atau Surat Jalan asal.")
    can = await returnable_now(db, mi)
    mids = sorted(can)
    mats = {m["id"]: m async for m in db.rahaza_materials.find({"id": {"$in": mids}}, {"_id": 0})}
    lines, seen = [], set()
    for it in mi.get("items") or []:
        mid = it.get("material_id")
        if not mid or mid in seen:
            continue
        seen.add(mid)
        m = mats.get(mid) or {}
        lines.append({"material_id": mid, "material_code": m.get("code") or it.get("material_code") or "",
                      "material_name": m.get("name") or it.get("material_name") or "",
                      "unit": m.get("unit") or it.get("unit") or "pcs",
                      "qty_issued": round(sum(float(x.get("qty_issued") or 0) for x in mi["items"]
                                              if x.get("material_id") == mid), 4),
                      "qty_returned": round(sum(float(x.get("qty_returned") or 0) for x in mi["items"]
                                                if x.get("material_id") == mid), 4),
                      "returnable": max(0.0, can.get(mid, 0.0))})
    return _ok({"material_issue_id": mi["id"], "mi_number": mi.get("mi_number"),
                "vendor_shipment_id": mi.get("vendor_shipment_id") or "",
                "vendor_shipment_number": mi.get("vendor_shipment_number") or "",
                "vendor_name": mi.get("vendor_name") or "", "work_order_id": mi.get("work_order_id") or "",
                "return_status": mi.get("return_status"), "lines": lines})


@router.post("")
async def create_return(request: Request, body: ReturnCreateModel):
    user = await require_auth(request)
    db = get_db()
    mi = await _resolve_mi(db, body.material_issue_id, body.vendor_shipment_id)
    items = [i.dict() for i in body.items]
    if mi:
        # baris retur MI wajib menunjuk material yang memang dikeluarkan MI itu
        can = mi_returnable(mi)
        for it in items:
            if it.get("material_id") not in can:
                raise HTTPException(400, f"Material '{it.get('material_code') or it.get('material_id')}' tidak "
                                         f"dikeluarkan oleh MI {mi.get('mi_number')}.")
        errors = qty_errors(items, await returnable_now(db, mi))
        if errors:
            raise HTTPException(400, f"Qty retur melebihi sisa MI {mi.get('mi_number')}: {'; '.join(errors)}")
    ref_no = await _build_ref(db)
    doc_id = await next_counter(db, "production_material_returns")
    now = _now()
    doc = {
        "id": doc_id,
        "ref_no": ref_no,
        "work_order_id": body.work_order_id,
        "work_order_code": body.work_order_code,
        "production_line": body.production_line,
        "return_reason": body.return_reason,
        "notes": body.notes,
        "material_issue_id": (mi or {}).get("id") or "",
        "mi_number": (mi or {}).get("mi_number") or "",
        "vendor_shipment_id": (mi or {}).get("vendor_shipment_id") or body.vendor_shipment_id or "",
        "vendor_shipment_number": (mi or {}).get("vendor_shipment_number") or "",
        "items": items,
        "status": "draft",
        "submitted_by": user.get("full_name") or user.get("email") or "",
        "submitted_by_id": str(user.get("id") or user.get("_id") or ""),
        "approved_by": None,
        "approved_at": None,
        "received_by": None,
        "received_at": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.production_material_returns.insert_one({"_id": doc_id, **doc})
    await log_activity(
        str(user.get("id") or user.get("_id") or ""),
        user.get("full_name") or user.get("name") or user.get("email") or "",
        "create",
        "production_material_returns",
        f"Return {ref_no} created: {doc_id}"
    )
    return _ok(doc, message=f"Return {ref_no} berhasil dibuat.")


@router.get("/summary")
async def returns_summary(request: Request):
    await require_auth(request)
    db = get_db()
    statuses = ["draft", "submitted", "approved", "received", "rejected"]
    summary = {}
    for s in statuses:
        summary[s] = await db.production_material_returns.count_documents({"status": s})
    return _ok(summary)


@router.get("/{return_id}")
async def get_return(request: Request, return_id: str):
    await require_auth(request)
    db = get_db()
    doc = await db.production_material_returns.find_one({"id": _coerce_id(return_id)}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Return tidak ditemukan.")
    return _ok(doc)


@router.put("/{return_id}")
async def update_return(request: Request, return_id: str, body: ReturnUpdateModel):
    await require_auth(request)
    db = get_db()
    doc = await db.production_material_returns.find_one({"id": _coerce_id(return_id)})
    if not doc:
        raise HTTPException(404, "Return tidak ditemukan.")
    if doc.get("status") not in ("draft",):
        raise HTTPException(400, "Hanya return dengan status draft yang bisa diedit.")
    update = {k: v for k, v in body.dict(exclude_none=True).items()}
    if "items" in update:
        update["items"] = [i.dict() if hasattr(i, 'dict') else i for i in update["items"]]
    update["updated_at"] = _now()
    await db.production_material_returns.update_one({"id": _coerce_id(return_id)}, {"$set": update})
    return _ok(message="Return berhasil diupdate.")


@router.post("/{return_id}/submit")
async def submit_return(request: Request, return_id: str):
    """Ubah status dari draft → submitted untuk dikirim ke supervisor."""
    user = await require_auth(request)
    db = get_db()
    doc = await db.production_material_returns.find_one({"id": _coerce_id(return_id)})
    if not doc:
        raise HTTPException(404, "Return tidak ditemukan.")
    if doc.get("status") != "draft":
        raise HTTPException(400, f"Status saat ini: {doc.get('status')}. Hanya draft yang bisa disubmit.")
    if not doc.get("items"):
        raise HTTPException(400, "Tambahkan minimal 1 item sebelum submit.")

    # ── 2026-11-02 (K10): retur atas MI tertentu — qty ≤ dikeluarkan − sudah diretur − retur lain
    #    yang masih berjalan untuk MI yang sama (per material) ──────────────────────────────
    if doc.get("material_issue_id"):
        mi = await _resolve_mi(db, doc["material_issue_id"])
        errors = qty_errors(doc.get("items") or [],
                            await returnable_now(db, mi, exclude_return_id=_coerce_id(return_id)))
        if errors:
            raise HTTPException(400, f"Qty retur melebihi sisa MI {mi.get('mi_number')}: {'; '.join(errors)}")

    # ── Task 2.5: Validasi qty return tidak melebihi yang pernah dikeluarkan ─────
    wo_id = doc.get("work_order_id")
    if wo_id and not doc.get("material_issue_id"):
        all_issues = await db.rahaza_material_issues.find(
            {"work_order_id": wo_id, "status": {"$in": ["approved", "issued"]}},
            {"_id": 0, "items": 1}
        ).to_list(200)
        if all_issues:
            issued_map: dict = {}
            for mi in all_issues:
                for mi_item in (mi.get("items") or []):
                    code = (mi_item.get("material_code") or "").strip()
                    if code:
                        issued_map[code] = issued_map.get(code, 0) + float(mi_item.get("qty_issued") or 0)
            # Total yang sudah pernah direturn (di luar dokumen ini)
            existing = await db.production_material_returns.find(
                {
                    "work_order_id": wo_id,
                    "status": {"$in": ["submitted", "approved", "received"]},
                    "id": {"$ne": _coerce_id(return_id)},
                },
                {"_id": 0, "items": 1}
            ).to_list(200)
            returned_map: dict = {}
            for ret in existing:
                for r_item in (ret.get("items") or []):
                    code = (r_item.get("material_code") or "").strip()
                    if code:
                        returned_map[code] = returned_map.get(code, 0) + float(r_item.get("qty_returned") or 0)
            errors = []
            for ret_item in doc.get("items", []):
                code = (ret_item.get("material_code") or "").strip()
                qty  = float(ret_item.get("qty_returned") or 0)
                if code in issued_map and qty > 0:
                    available = issued_map[code] - returned_map.get(code, 0)
                    if qty > available + 0.001:
                        errors.append(f"'{code}': return {qty} > tersedia {max(0, available):.2f}")
            if errors:
                raise HTTPException(400, f"Qty return melebihi jumlah yang dikeluarkan: {'; '.join(errors)}")

    now = _now()
    await db.production_material_returns.update_one(
        {"id": _coerce_id(return_id)},
        {"$set": {"status": "submitted", "submitted_at": now, "updated_at": now}},
    )
    await log_activity(
        str(user.get("id") or user.get("_id") or ""),
        user.get("full_name") or user.get("name") or user.get("email") or "",
        "submit",
        "production_material_returns",
        f"Return {return_id} submitted"
    )
    return _ok(message="Return berhasil disubmit, menunggu persetujuan supervisor.")


@router.post("/{return_id}/approve")
async def approve_return(request: Request, return_id: str, body: ActionModel):
    """Supervisor produksi menyetujui return."""
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role not in ("superadmin", "admin", "owner", "manager"):
        raise HTTPException(403, "Hanya supervisor/manager yang dapat menyetujui.")
    db = get_db()
    doc = await db.production_material_returns.find_one({"id": _coerce_id(return_id)})
    if not doc:
        raise HTTPException(404, "Return tidak ditemukan.")
    if doc.get("status") != "submitted":
        raise HTTPException(400, "Hanya return submitted yang bisa disetujui.")
    now = _now()
    await db.production_material_returns.update_one(
        {"id": _coerce_id(return_id)},
        {"$set": {
            "status": "approved",
            "approved_by": user.get("full_name") or user.get("email") or "",
            "approved_by_id": str(user.get("id") or user.get("_id") or ""),
            "approved_at": now,
            "approve_note": body.note,
            "updated_at": now,
        }},
    )
    await log_activity(
        str(user.get("id") or user.get("_id") or ""),
        user.get("full_name") or user.get("name") or user.get("email") or "",
        "approve",
        "production_material_returns",
        f"Return {return_id} approved: {body.note}"
    )
    return _ok(message="Return disetujui. Menunggu penerimaan di gudang.")


@router.post("/{return_id}/reject")
async def reject_return(request: Request, return_id: str, body: ActionModel):
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role not in ("superadmin", "admin", "owner", "manager"):
        raise HTTPException(403, "Hanya supervisor/manager yang dapat menolak.")
    db = get_db()
    doc = await db.production_material_returns.find_one({"id": _coerce_id(return_id)})
    if not doc:
        raise HTTPException(404, "Return tidak ditemukan.")
    if doc.get("status") not in ("submitted",):
        raise HTTPException(400, "Hanya return submitted yang bisa ditolak.")
    now = _now()
    await db.production_material_returns.update_one(
        {"id": _coerce_id(return_id)},
        {"$set": {"status": "rejected", "reject_note": body.note, "updated_at": now}},
    )
    await log_activity(
        str(user.get("id") or user.get("_id") or ""),
        user.get("full_name") or user.get("name") or user.get("email") or "",
        "reject",
        "production_material_returns",
        f"Return {return_id} rejected: {body.note}"
    )
    return _ok(message="Return ditolak.")


@router.post("/{return_id}/receive")
async def receive_return(request: Request, return_id: str, body: ActionModel):
    """Gudang menerima material return dan update stok."""
    user = await require_auth(request)
    db = get_db()
    doc = await db.production_material_returns.find_one({"id": _coerce_id(return_id)}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Return tidak ditemukan.")
    if doc.get("status") != "approved":
        raise HTTPException(400, "Return harus disetujui supervisor sebelum diterima gudang.")
    now = _now()
    # Update stok: tambah kembali qty ke rahaza_material_stock
    items = doc.get("items", [])
    # 2026-11-02 — No.18(a): lokasi WAJIB dipilih; dulu "lokasi aktif pertama" (KTR-PST).
    loc_id = (body.location_id or "").strip() or None
    needs_loc = any(it.get("material_id") and float(it.get("qty_returned", 0) or 0) > 0
                    and it.get("condition", "good") == "good" for it in items)
    if needs_loc:
        if not loc_id:
            raise HTTPException(400, "location_id wajib diisi — pilih lokasi gudang penerima retur material.")
        from core import location_resolver
        if not await location_resolver.location_exists(db, loc_id):
            raise HTTPException(400, "Lokasi penerima retur tidak ditemukan di Struktur Gudang.")
    # 2026-11-02 (K10): MI asal (langsung, atau MI 'issued' WO-nya) → HPP saat keluar per material
    mi = await _resolve_mi(db, doc.get("material_issue_id") or "") if doc.get("material_issue_id") else None
    issue_cost = await _issue_costs(db, doc, mi)
    je_lines, good_by_mat = [], {}
    for item in items:
        mat_id = item.get("material_id")
        qty = float(item.get("qty_returned", 0))
        condition = item.get("condition", "good")
        if not mat_id or qty <= 0:
            continue
        if condition == "good" and loc_id:
            good_by_mat[mat_id] = good_by_mat.get(mat_id, 0.0) + qty
            ic = issue_cost.get(mat_id) or {}
            je_lines.append({"material_id": mat_id, "qty": qty, "unit_cost": ic.get("unit_cost", 0.0),
                             "kind": ic.get("kind"), "cost_target": ic.get("cost_target")})
        if condition in ("good", "scrap"):   # 'damaged' tidak kembali ke stok
            # INV-6 FIX: kembalikan stok via stock_service (qty kanonik + alias + available),
            # bukan field hantu qty_available/qty_on_hand tanpa lokasi. Hanya 'good' yang jadi
            # stok siap pakai; 'scrap' hanya dicatat movement (tidak masuk stok usable).
            if condition == "good" and loc_id:
                mat = await db.rahaza_materials.find_one({"id": mat_id}, {"_id": 0})
                mtype = ((mat or {}).get("type") or "").lower()
                await stock_service.add(
                    mat_id, loc_id, qty,
                    meta={
                        "material_type": mtype or None,
                        "material_code": item.get("material_code"),
                        "material_name": item.get("material_name"),
                        "ownership": "cv_da",
                        "inventory_category": "fg_internal" if mtype == "fg" else "raw_material",
                    },
                    ref={"source": "production_return", "return_id": str(return_id),
                         "ref_code": doc.get("ref_no", ""), "condition": condition},
                    actor={"id": str(user.get("id") or ""), "email": user.get("email", "")},
                    db=db,
                )
            # Catat movement (audit) — semua kondisi good/scrap
            await db.rahaza_material_movements.insert_one({
                "material_id": mat_id,
                "material_code": item.get("material_code", ""),
                "material_name": item.get("material_name", ""),
                "movement_type": "production_return",
                "qty": qty,
                "condition": condition,
                "ref_id": return_id,
                "ref_code": doc.get("ref_no", ""),
                "note": f"Return dari produksi ({condition}): {body.note or 'received'}",
                "created_at": now,
            })
    # ── 2026-11-02 (K10): jurnal balik Dr persediaan (per jenis) / Cr WIP pada nilai keluar ──
    posting = {"ok": True, "skipped": True, "reason": "tidak ada bahan kondisi baik yang kembali ke stok"}
    if je_lines:
        from routes.rahaza_posting import post_material_return
        try:
            posting = await post_material_return(
                db, {**doc, "received_at": now, "mi_number": doc.get("mi_number") or (mi or {}).get("mi_number")},
                je_lines, user)
        except Exception as e:  # noqa: BLE001 — stok sudah kembali; kegagalan jurnal dicatat di dokumen
            logger.exception("jurnal retur material gagal")
            posting = {"ok": False, "error": str(e)}
    # ── status MI ikut diperbarui (qty_returned per baris + return_status partial/full) ──
    mi_update = None
    if mi and good_by_mat:
        mi_update = mi_after_return(mi, good_by_mat)
        await db.rahaza_material_issues.update_one({"id": mi["id"]}, {"$set": {
            "items": mi_update["items"], "return_status": mi_update["return_status"],
            "qty_returned_total": mi_update["qty_returned_total"], "updated_at": now}})
    await db.production_material_returns.update_one(
        {"id": _coerce_id(return_id)},
        {"$set": {
            "status": "received",
            "received_by": user.get("full_name") or user.get("email") or "",
            "received_by_id": str(user.get("id") or user.get("_id") or ""),
            "received_at": now,
            "receive_note": body.note,
            "location_id": loc_id,
            "gl_je_number": posting.get("je_number"),
            "gl_error": None if posting.get("ok") else posting.get("error"),
            "updated_at": now,
        }},
    )
    await log_activity(
        str(user.get("id") or user.get("_id") or ""),
        user.get("full_name") or user.get("name") or user.get("email") or "",
        "receive",
        "production_material_returns",
        f"Return {return_id} received: {len(items)} items"
    )
    return _ok(message=f"Material return diterima. {len(items)} item dikembalikan ke stok.",
               posting=posting, mi_return_status=(mi_update or {}).get("return_status"))


async def _issue_costs(db, doc: dict, mi: Optional[dict]) -> dict:
    """{material_id: {unit_cost, kind, cost_target}} — HPP SAAT KELUAR (`unit_cost_applied` baris MI),
    dari MI asal atau MI 'issued' WO-nya (terbaru). Tanpa MI: HPP master (cadangan)."""
    from routes.rahaza_posting import inventory_kind
    mis = [mi] if mi else []
    if not mis and doc.get("work_order_id"):
        mis = await db.rahaza_material_issues.find(
            {"work_order_id": doc["work_order_id"], "status": "issued"}, {"_id": 0}).sort("issued_at", -1).to_list(50)
    out: dict = {}
    for m in mis:
        for it in m.get("items") or []:
            mid = it.get("material_id")
            if mid and mid not in out and float(it.get("unit_cost_applied") or 0) > 0:
                out[mid] = {"unit_cost": float(it["unit_cost_applied"]), "cost_target": m.get("cost_target")}
    for it in doc.get("items") or []:
        mid = it.get("material_id")
        if not mid:
            continue
        mat = await db.rahaza_materials.find_one({"id": mid}, {"_id": 0}) or {}
        slot = out.setdefault(mid, {"unit_cost": float(mat.get("unit_cost") or 0), "cost_target": None})
        slot["kind"] = inventory_kind(mat)
    return out


@router.delete("/{return_id}", dependencies=only(*PRODUCTION_ROLES))  # T-01 2.3
async def delete_return(request: Request, return_id: str):
    await require_auth(request)
    db = get_db()
    doc = await db.production_material_returns.find_one({"id": _coerce_id(return_id)})
    if not doc:
        raise HTTPException(404, "Return tidak ditemukan.")
    if doc.get("status") not in ("draft",):
        raise HTTPException(400, "Hanya draft yang bisa dihapus.")
    await db.production_material_returns.delete_one({"id": _coerce_id(return_id)})
    return _ok(message="Return dihapus.")
