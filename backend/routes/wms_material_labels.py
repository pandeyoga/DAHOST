"""WMS — Label barcode BAHAN (kain, aksesoris, trims, kemasan, potongan).

Endpoint:
  GET  /api/wms/materials/{material_id}/label-pdf   — satu label (90×50 mm)
  POST /api/wms/materials/labels/batch-pdf          — banyak label pada A4

2026-11-02 (Paket 3a): `_attach_stock` dipindah ke `label_render.attach_stock_info`
(salinan identiknya ada di wms_barcode.py); kode tak sah → 400.

FASE H-3 (2026-08-16): gambar labelnya DIPINDAH ke `core/label_render.py`
(SSOT). Berkas ini tinggal mengurus HTTP + ambil data. Dua cacat yang ikut
tertutup oleh pemindahan itu (rinciannya di docstring core):
  · batch memakai 3 kolom × 90 mm pada A4 selebar 210 mm ⇒ kolom ketiga
    tercetak DI LUAR halaman;
  · satuan dibaca dari `uom` yang tidak ada di `rahaza_materials` (namanya
    `unit`) ⇒ semua label bahan mencetak "pcs", termasuk kain ber-satuan kg.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import require_auth, verify_download_token
from core import label_render as lr
from database import get_db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wms/materials", tags=["wms-material-labels"])

MAX_BATCH = 100


async def _auth_or_token(request: Request, token: Optional[str] = None):
    if token:
        user = verify_download_token(token)
        if user:
            return user
    return await require_auth(request)


def _pdf_or_400(fn, *args, **kwargs):
    """LabelCodeError (kode kosong / di luar Code128) → 400, bukan PDF ber-barcode salah."""
    try:
        return fn(*args, **kwargs)
    except lr.LabelCodeError as e:
        raise HTTPException(400, str(e))


@router.get("/{material_id}/label-pdf")
async def material_label_pdf(
    material_id: str,
    request: Request,
    token: Optional[str] = Query(None),
    include_stock: bool = Query(True, description="Cetak stok & lokasi di label"),
):
    await _auth_or_token(request, token)
    db = get_db()
    material = await db.rahaza_materials.find_one(
        {"$or": [{"id": material_id}, {"code": material_id}]}, {"_id": 0})
    if not material:
        raise HTTPException(404, f"Material tidak ditemukan: {material_id}")
    if include_stock:
        await lr.attach_stock_info(db, [material])
    if not lr.LABELS_OK:
        raise HTTPException(500, "Pustaka pencetak label tidak tersedia")
    pdf = _pdf_or_400(lr.single_label_pdf, "material", material, include_stock=include_stock)
    fname = f"material-{material.get('code', material_id)}.pdf"
    return StreamingResponse(pdf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


class BatchMaterialLabelsIn(BaseModel):
    material_ids: List[str]
    include_stock: bool = True


@router.post("/labels/batch-pdf")
async def batch_material_labels_pdf(data: BatchMaterialLabelsIn, request: Request):
    await require_auth(request)
    if not data.material_ids:
        raise HTTPException(400, "material_ids tidak boleh kosong")
    if len(data.material_ids) > MAX_BATCH:
        raise HTTPException(400, f"Maksimal {MAX_BATCH} material per batch")
    if not lr.LABELS_OK:
        raise HTTPException(500, "Pustaka pencetak label tidak tersedia")

    db = get_db()
    materials = await db.rahaza_materials.find(
        {"$or": [{"id": {"$in": data.material_ids}},
                 {"code": {"$in": data.material_ids}}]}, {"_id": 0}).to_list(MAX_BATCH)
    if not materials:
        raise HTTPException(404, "Tidak ada material ditemukan")
    if data.include_stock:
        await lr.attach_stock_info(db, materials)

    pdf = _pdf_or_400(lr.grid_labels_pdf, "material", materials, include_stock=data.include_stock,
                      title=f"Material Labels ({len(materials)})")
    return StreamingResponse(pdf, media_type="application/pdf", headers={
        "Content-Disposition":
            f'attachment; filename="material_labels_batch_{len(materials)}.pdf"'})
