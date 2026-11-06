"""
Dewi Accessories - Requests
Internal requests from divisions
"""
from fastapi import APIRouter, HTTPException, Request
import uuid
import logging
from datetime import datetime, timezone
from auth import require_auth

_log = logging.getLogger(__name__)

router = APIRouter(tags=["accessories-requests"])

# ── helpers ──────────────────────────────────────────────────────────────────
def _id():    return str(uuid.uuid4())
def _now_iso(): return datetime.now(timezone.utc).isoformat()
def _now():   return datetime.now(timezone.utc)

# 2026-11-06 (pola P8): salinan `_normalize_unit`/`_VALID_UNITS` yang tidak dipakai dihapus —
# ejaan satuan resmi ada di `core.uom.canonical_unit` (dipakai `dewi_accessories_items`).

# Fase 2.8: helper stok aksesoris KANONIK dipindah ke core.accessory_stock
# (satukan ke rahaza_material_stock flat via stock_service; hilangkan duplikasi Schema-B nested).
from core.accessory_stock import (  # noqa: E402
    get_accessory_location_id as _get_accessory_location_id,
)

async def _log_movement(db, user: dict, *, material_id: str, mv_type: str, qty: float,
                        notes: str = "", related_ref: str = "", related_type: str = ""):
    mat = await db.rahaza_materials.find_one(
        {"id": material_id}, {"_id": 0, "id": 1, "code": 1, "name": 1, "type": 1, "unit": 1}
    )
    if not mat:
        return
    loc_id = await _get_accessory_location_id(db)
    mvdoc = {
        "id": _id(),
        "material_id": material_id,
        "material": mat,
        "movement_type": mv_type,
        "qty_signed": qty,
        "location": {"id": loc_id, "code": "ZNA-AKSESORIS", "name": "Area Aksesoris"},
        "notes": notes,
        "reference_type": related_type,
        "reference_id": related_ref,
        "created_by": user.get("id", ""),
        "created_at": _now(),
    }
    await db.rahaza_material_movements.insert_one(mvdoc)

# 2026-11-06 (pola P2): salinan `_enrich_movement` yang tidak pernah dipanggil dihapus — versi yang
# dipakai ada di routes/dewi_accessories_stock.py (dulu salinan ini membaca `dewi_asset_loans` lewat
# `related_loan_id` yang tidak pernah ditulis).

# (dead code dibersihkan) _material_to_acc_item duplikat tak terpakai — SSOT serializer item aksesoris ada di routes/dewi_accessories_items.py

# ═════════════════════════════════════════════════════════════════════════════
# FASE 10 — ENDPOINT LEGACY DIMATIKAN (410 GONE)
# ─────────────────────────────────────────────────────────────────────────────
# `/api/acc/internal-requests/*` dulu menulis ke koleksi `acc_internal_requests`,
# padahal SSOT permintaan aksesoris adalah `dewi_accessory_requests`
# (`request_type='internal_issuance'`, P3 TD-009). Efek sampingnya nyata:
#   * KPI "Request Pending" di Dashboard Aksesoris membaca SSOT ⇒ SELALU 0 walau
#     ada permintaan yang dibuat dari UI (karena UI menulis ke koleksi legacy);
#   * inbox/approval SSOT tidak pernah melihat permintaan tersebut;
#   * koleksi legacy tidak bisa di-drop karena masih ada penulis aktif.
# Sejak FASE 10 UI sudah memakai SSOT (yang kini juga MEMOTONG STOK saat deliver),
# jadi endpoint ini dimatikan agar tidak ada jalur menulis ganda.
# Data lama sudah dipindahkan oleh `migrations/migrate_acc_requests_consolidation.py`.
# ═════════════════════════════════════════════════════════════════════════════

_GONE_MSG = (
    "Permintaan internal aksesoris sekarang dilayani SSOT "
    "/api/dewi/accessory-requests (request_type='internal_issuance'): "
    "POST untuk membuat, /{id}/allocate untuk menyetujui, /{id}/deliver untuk "
    "menyerahkan (memotong stok + jurnal), /{id}/reject untuk menolak. "
    "Endpoint lama dimatikan karena menulis ke koleksi ganda."
)


@router.get("/internal-requests")
async def list_internal_requests_gone(request: Request):
    await require_auth(request)
    raise HTTPException(410, _GONE_MSG)


@router.post("/internal-requests")
async def create_internal_request_gone(request: Request):
    await require_auth(request)
    raise HTTPException(410, _GONE_MSG)


@router.put("/internal-requests/{req_id}")
async def update_internal_request_gone(req_id: str, request: Request):
    await require_auth(request)
    raise HTTPException(410, _GONE_MSG)


# ═══════════════════════════════════════════════════════════════
# PEMINJAMAN AKSESORIS (preserved: acc_loans)
# ═══════════════════════════════════════════════════════════════

