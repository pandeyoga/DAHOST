"""
WMS — Printable Barcode Labels (PDF)
Generate label PDF berisi barcode Code128 untuk:
  - Single posisi: GET /api/wms/positions/{position_id}/label-pdf
  - Semua posisi dalam rak: GET /api/wms/racks/{rack_id}/labels-pdf
  - Multiple posisi by IDs: POST /api/wms/labels/batch-pdf {position_ids: [...]}
  - Label LOKASI (2026-11-02, K9): GET /api/wms/locations/{location_id}/label-pdf,
    GET /api/wms/locations/labels-pdf?ids=a,b (kosong = semua lokasi aktif)

Layout: 3 kolom × 8 baris label per A4 (24 label/halaman), 65 × 33 mm.

2026-11-02 (Paket 3a): gambar label dipindah ke `core/label_render.py`
(`draw_bin_label`, generator Code128 vektor yang sama dengan label FG/bahan/roll).
Dulu berkas ini punya generator PNG sendiri: kode posisi 25 karakter diperkecil
ke lebar modul ±0,18 mm (uji decode 203 dpi: 0/24 label terbaca; kini 10/24 —
kode posisi sependek mungkin tetap disarankan, 18 karakter: 24/24).
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from database import get_db
from auth import require_auth, verify_download_token
from core import label_render as lr

router = APIRouter(prefix="/api/wms", tags=["wms-labels"])


def _build_pdf(positions: List[dict], title: str):
    """PDF label posisi (A4 3×8) — 400 bila ada posisi tanpa barcode yang sah."""
    if not lr.LABELS_OK:
        raise HTTPException(500, "Pustaka pencetak label (reportlab) tidak tersedia")
    try:
        return lr.grid_labels_pdf("bin", positions, title=title, footer=True)
    except lr.LabelCodeError as e:
        raise HTTPException(400, str(e))


async def _auth_or_token(request: Request, token: Optional[str] = None):
    """Auth via Authorization header OR ?token= query param (browser-open PDF)."""
    if token:
        user = verify_download_token(token)
        if user:
            return user
    # Fallback to header
    return await require_auth(request)


# ══════════════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/positions/{position_id}/label-pdf")
async def position_label_pdf(position_id: str, request: Request, token: Optional[str] = Query(None)):
    """Single label PDF (1 label centered on page)."""
    await _auth_or_token(request, token)
    db = get_db()
    pos = await db.wh_positions.find_one({"id": position_id}, {"_id": 0})
    if not pos:
        raise HTTPException(404, "Posisi tidak ditemukan")
    pdf = _build_pdf([pos], f"Label-{pos.get('barcode')}")
    return StreamingResponse(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="label_{pos.get("barcode","pos")}.pdf"'},
    )


@router.get("/racks/{rack_id}/labels-pdf")
async def rack_labels_pdf(rack_id: str, request: Request, token: Optional[str] = Query(None)):
    """All labels for one rack (sheet-fit, 24 per A4)."""
    await _auth_or_token(request, token)
    db = get_db()
    rack = await db.wh_racks.find_one({"id": rack_id}, {"_id": 0})
    if not rack:
        raise HTTPException(404, "Rak tidak ditemukan")
    positions = await db.wh_positions.find({"rack_id": rack_id}, {"_id": 0})\
        .sort([("shelf_no", 1), ("slot_no", 1)]).to_list(500)
    if not positions:
        raise HTTPException(400, "Rak tidak memiliki posisi")
    title = f"Labels Rak {rack.get('building_code','')}-{rack.get('zone_code','')}-{rack.get('code','')}"
    pdf = _build_pdf(positions, title)
    return StreamingResponse(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="labels_rack_{rack.get("code","")}.pdf"'},
    )


# ── LABEL LOKASI (2026-11-02, K9) ────────────────────────────────────────────
# Sesi Opname per lokasi: petugas men-scan label LOKASI (Code128 = `rahaza_locations.code`) untuk
# konteks "lantai / belum dirak". Resolver bersama (`core.scan_resolver.resolve_bin`) sudah
# mengenali kode lokasi. Digambar generator label bin yang sama (`core.label_render`, ukuran
# 65 × 33 mm): baris atas "LOKASI · peran", baris kedua nama lokasi.
def location_label_doc(loc: dict) -> dict:
    role = loc.get("storage_role") or loc.get("type") or ""
    return {"id": loc.get("id"), "barcode": loc.get("code") or "", "building_code": "LOKASI",
            "zone_code": str(role).upper() if role else "", "label": loc.get("name") or "",
            "name": loc.get("name") or loc.get("code")}


@router.get("/locations/{location_id}/label-pdf")
async def location_label_pdf(location_id: str, request: Request, token: Optional[str] = Query(None)):
    """Label satu lokasi (A4, posisi kiri-atas) — dicetak berlembar di printer kantor."""
    await _auth_or_token(request, token)
    db = get_db()
    loc = await db.rahaza_locations.find_one({"id": location_id}, {"_id": 0})
    if not loc:
        raise HTTPException(404, "Lokasi tidak ditemukan")
    pdf = _build_pdf([location_label_doc(loc)], f"Label Lokasi {loc.get('code')}")
    return StreamingResponse(pdf, media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="label_lokasi_{loc.get("code","")}.pdf"'})


@router.get("/locations/labels-pdf")
async def locations_labels_pdf(request: Request, ids: Optional[str] = Query(None), token: Optional[str] = Query(None)):
    """Label banyak lokasi (`ids` dipisah koma; kosong = semua lokasi aktif)."""
    await _auth_or_token(request, token)
    db = get_db()
    q = {"id": {"$in": [i for i in (ids or "").split(",") if i]}} if ids else {"active": {"$ne": False}}
    locs = await db.rahaza_locations.find(q, {"_id": 0}).sort("code", 1).to_list(500)
    if not locs:
        raise HTTPException(404, "Tidak ada lokasi cocok")
    pdf = _build_pdf([location_label_doc(x) for x in locs], f"Label Lokasi ({len(locs)})")
    return StreamingResponse(pdf, media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="label_lokasi.pdf"'})


class BatchLabelsIn(BaseModel):
    position_ids: List[str]


@router.post("/labels/batch-pdf")
async def batch_labels_pdf(data: BatchLabelsIn, request: Request):
    """Generate PDF for arbitrary set of position IDs."""
    await require_auth(request)
    if not data.position_ids:
        raise HTTPException(400, "position_ids tidak boleh kosong")
    db = get_db()
    positions = await db.wh_positions.find(
        {"id": {"$in": data.position_ids}}, {"_id": 0}
    ).sort([("building_code", 1), ("zone_code", 1), ("rack_code", 1), ("shelf_no", 1), ("slot_no", 1)]).to_list(500)
    if not positions:
        raise HTTPException(404, "Tidak ada posisi cocok")
    pdf = _build_pdf(positions, f"Labels Batch ({len(positions)} posisi)")
    return StreamingResponse(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="labels_batch.pdf"'},
    )
