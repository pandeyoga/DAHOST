"""
Dewi Accessories - Opname (Portal Aksesoris)

2026-11-02 (keputusan owner K9 — "dipisahkan saja pakai mesin yang sama"): opname aksesoris tetap
punya menu sendiri di Portal Aksesoris, tetapi SEMUA aturannya kini dari `core.opname_engine`
(mesin yang sama dengan Opname Stok gudang). Dulu berkas ini punya mesin sendiri: stok sistem =
total SEMUA lokasi tetapi selisih ditulis ke satu lokasi aksesoris, baris tak dihitung dilewati,
satu jurnal per material (g.md No.17 §2b).

URL lama `/api/acc/opname*` dipertahankan sebagai pembungkus (bentuk respons lama dipetakan):
  * sesi baru = Sesi Opname di lokasi ber-peran `aksesoris`, filter jenis aksesoris;
  * sesi lama `wh_opname_sessions2` = arsip baca-saja.
Layar Portal Aksesoris memakai layar Sesi Opname yang sama (prop `kind="aksesoris"`).
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from database import get_db
from auth import require_auth, log_activity
from core import opname_engine as eng

router = APIRouter(tags=["accessories-opname"])

_STATUS_TO_ACC = {"counting": "Active", "submitted": "Submitted", "approving": "Submitted",
                  "approved": "Completed", "rejected": "Rejected", "cancelled": "Cancelled",
                  "open": "Active", "pending_approval": "Submitted"}


async def _accessory_location_id(db) -> str:
    from core.location_resolver import legacy_location_for_role
    loc = await legacy_location_for_role(db, "aksesoris")
    if not loc:
        raise HTTPException(400, "Lokasi aksesoris belum ditetapkan — beri satu lokasi peran 'aksesoris' "
                                 "di master lokasi, atau buat Sesi Opname dengan memilih lokasi.")
    return loc["id"]


def _to_acc(sess: dict, view: dict | None = None) -> dict:
    """Bentuk respons lama StokOpnameTab (ref_number, status Active/Submitted/…, lines acc_id…)."""
    summ = sess.get("summary") or {}
    out = {
        "id": sess.get("id"), "ref_number": sess.get("session_no") or "", "notes": sess.get("notes", ""),
        "status": _STATUS_TO_ACC.get(sess.get("status", ""), sess.get("status")), "raw_status": sess.get("status"),
        "engine": sess.get("engine") or "acc_lama", "archived": bool(sess.get("archived")),
        "location_code": sess.get("location_code"), "scope_label": sess.get("scope_label"),
        "total_items": summ.get("lines", 0), "counted_items": summ.get("counted", 0),
        "total_variance_items": summ.get("with_variance", 0),
        "total_variance_value": float(summ.get("total_variance_value") or 0),
        "je_posted": int(summ.get("je_posted") or 0), "je_number": summ.get("je_number"),
        "started_at": str(sess.get("created_at") or ""), "submitted_at": str(sess.get("submitted_at") or ""),
        "approved_at": str(sess.get("approved_at") or ""), "reject_reason": sess.get("reject_reason", ""),
        "summary": summ,
    }
    if view is not None:
        out["blind"] = view.get("blind")
        out["lines"] = [{
            "id": ln.get("key"), "session_id": sess.get("id"), "acc_id": ln.get("material_id"),
            "acc_code": ln.get("material_code"), "acc_name": ln.get("material_name"), "unit": ln.get("unit"),
            "status": ln.get("status"), "counted_qty": ln.get("counted_qty"),
            # hitung buta: qty sistem & selisih tidak ada selama sesi masih dihitung
            "system_qty": ln.get("system_qty"), "diff": ln.get("variance_qty"),
        } for ln in view.get("lines") or []]
    return out


@router.get("/opname")
async def list_opname(request: Request):
    await require_auth(request)
    rows = await eng.list_sessions(get_db(), kind="aksesoris", limit=500)
    return [_to_acc(s) for s in rows]


@router.post("/opname")
async def start_opname(request: Request):
    user = await require_auth(request)
    db = get_db()
    try:
        body = await request.json()
    except Exception:
        body = {}
    doc = await eng.create_session(db, user, location_id=body.get("location_id") or await _accessory_location_id(db),
                                   kinds=["aksesoris"], material_codes=body.get("material_codes") or [],
                                   notes=body.get("notes", ""), source="aksesoris")
    await log_activity(user.get("id", ""), user.get("name", ""), "acc_opname_create", eng.SESS,
                       f"Opname aksesoris {doc['session_no']} {doc['scope_label']}")
    view = await eng.session_view(db, await eng.get_session(db, doc["id"]))
    return JSONResponse(_to_acc(view["session"], view), status_code=201)


@router.get("/opname/{session_id}")
async def get_opname_detail(session_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    legacy = await eng.legacy_acc_detail(db, session_id)
    if legacy:
        return {**_to_acc(legacy), "lines": legacy.get("count_items") or []}
    view = await eng.session_view(db, await eng.get_session(db, session_id))
    return _to_acc(view["session"], view)


@router.put("/opname/{session_id}/count")
async def update_count(session_id: str, request: Request):
    """Ketik jumlah fisik satu aksesoris (set absolut, lantai lokasi). `counted_uom` = satuan kemasan."""
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    if body.get("acc_id") is None or body.get("counted_qty") is None:
        raise HTTPException(400, "acc_id dan counted_qty wajib diisi")
    sess = await eng.get_session(db, session_id, for_write=True)
    mat = await eng.resolve_item(db, material_id=body["acc_id"])
    if not mat:
        raise HTTPException(404, "Aksesoris tidak ditemukan")
    qty = float(body["counted_qty"])
    if qty < 0:
        raise HTTPException(400, "Jumlah hitung tidak boleh negatif")
    return await eng.record_count(db, user, sess, mat=mat, bin_id="", bin_label="",
                                  qty=qty, input_uom=body.get("counted_uom") or body.get("input_uom") or "",
                                  mode="set")


async def _submit(request: Request, session_id: str):
    user = await require_auth(request)
    db = get_db()
    try:
        body = await request.json()
    except Exception:
        body = {}
    sess = await eng.get_session(db, session_id, for_write=True)
    sess = await eng.submit(db, user, sess, confirm_zero=bool((body or {}).get("confirm_zero")),
                            notes=(body or {}).get("notes", ""))
    return {"ok": True, "status": "pending_approval", "session_no": sess.get("session_no"),
            "counted_items": (sess.get("summary") or {}).get("counted", 0),
            "variance_items": (sess.get("summary") or {}).get("with_variance", 0)}


@router.post("/opname/{session_id}/submit")
async def submit_opname(session_id: str, request: Request):
    return await _submit(request, session_id)


@router.post("/opname/{session_id}/complete")
async def complete_opname(session_id: str, request: Request):
    """DEPRECATED alias lama = submit (approval supervisor tetap wajib)."""
    res = await _submit(request, session_id)
    res["deprecated"] = True
    return res


@router.post("/opname/{session_id}/approve")
async def approve_opname(session_id: str, request: Request):
    from routes.wms_opname3 import assert_can_approve
    user = await require_auth(request)
    db = get_db()
    sess = await eng.get_session(db, session_id, for_write=True)
    assert_can_approve(user, "approve opname aksesoris", sess)   # 2026-11-09: stok awal = Keuangan/owner
    sess = await eng.approve(db, user, sess)
    summ = sess.get("summary") or {}
    return {"ok": True, "status": "approved", "adjustments_made": summ.get("stock_writes", 0),
            "je_posted": summ.get("je_posted", 0), "je_number": summ.get("je_number"),
            "je_error": summ.get("je_error"), "total_variance_value": summ.get("total_variance_value", 0)}


@router.post("/opname/{session_id}/reject")
async def reject_opname(session_id: str, request: Request):
    from routes.wms_opname3 import assert_can_approve
    user = await require_auth(request)
    db = get_db()
    try:
        body = await request.json()
    except Exception:
        body = {}
    sess = await eng.get_session(db, session_id, for_write=True)
    assert_can_approve(user, "menolak opname aksesoris", sess)
    return await eng.reject(db, user, sess, (body or {}).get("reason", "") or (body or {}).get("notes", ""))


@router.post("/opname/{session_id}/cancel")
async def cancel_opname(session_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    return await eng.cancel(db, user, await eng.get_session(db, session_id, for_write=True))
