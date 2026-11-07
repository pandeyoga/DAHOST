"""Rincian PO di halaman — satu endpoint untuk PO Internal dan PO Maklon (Tahap 9, keputusan 8).

Layar PO (engine/ProductionPOModule) membuka rincian di bawah tabel; isinya dari `core.po_detail` yang
membaca data PO utama (`production_pos` + dokumen turunannya). Endpoint lama Detail PO maklon
(`/api/dewi/maklon/pos/{id}/360` dan `/timeline`) meneruskan ke modul yang sama.
"""
from fastapi import APIRouter, Request

from auth import require_auth
from core import po_detail
from database import get_db
from routes.production_rbac import deny_klien

router = APIRouter(prefix="/api", tags=["production-po-detail"])


@router.get("/production-pos/{po_id}/detail")
async def production_po_detail(po_id: str, request: Request):
    """Ringkasan, bahan & aksesoris, kiriman & penerimaan, tagihan, sampel (maklon) satu PO."""
    user = await require_auth(request)
    deny_klien(user)
    return await po_detail.build_po_detail(get_db(), po_id)


@router.get("/production-pos/{po_id}/timeline")
async def production_po_timeline(po_id: str, request: Request):
    """Riwayat satu PO (PO, kiriman, penerimaan & QC, permak, kiriman hasil, tagihan, sampel)."""
    user = await require_auth(request)
    deny_klien(user)
    return await po_detail.build_timeline(get_db(), po_id)
