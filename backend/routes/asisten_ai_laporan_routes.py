"""GET /api/asisten-ai/laporan/{id}?format=pdf|xlsx — unduh laporan buatan Asisten AI (Tahap A, 7 Nov 2026).

Berkas dibuat alat `buat_laporan` (`core/laporan_ai.py`) dan disimpan di penyimpanan unggahan dengan path
acak yang tidak pernah dikirim ke layar. Satu-satunya jalan mengunduh adalah rute ini:
  * wajib login (Bearer) + akses Portal Management (dipasang di server.py, sama dengan Asisten AI);
  * hanya PEMBUAT laporan, ditambah owner/superadmin (`core.laporan_ai.boleh_unduh`).
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from auth import require_auth
from core import laporan_ai as la
from database import get_db

router = APIRouter(prefix="/api/asisten-ai", tags=["asisten-ai-laporan"])


def _ambil_berkas(path: str):
    import object_storage
    return object_storage.get_object(path)


@router.get("/laporan/{laporan_id}")
async def unduh_laporan(laporan_id: str, request: Request,
                        format: Optional[str] = Query(None, pattern="^(pdf|xlsx)$")):
    user = await require_auth(request)
    doc = await get_db()[la.COLL].find_one({"id": laporan_id}, {"_id": 0, "spec": 0})
    if not doc:
        raise HTTPException(404, "Laporan tidak ditemukan.")
    if not la.boleh_unduh(user, doc):
        raise HTTPException(403, "Laporan ini dibuat pengguna lain. Hanya pembuatnya dan owner yang bisa mengunduh.")
    berkas = la.berkas_dari(doc, format)
    if not berkas:
        raise HTTPException(404, f"Laporan ini tidak punya berkas {(format or '').upper() or 'apa pun'}.")
    found = _ambil_berkas(berkas["path"])
    if not found:
        raise HTTPException(404, "Berkas laporan sudah tidak tersedia. Minta Asisten AI membuatnya lagi.")
    nama = berkas.get("nama_berkas") or f"laporan.{berkas['format']}"
    return Response(
        content=found[0], media_type=la.CONTENT_TYPE[berkas["format"]],
        headers={"Content-Disposition": f"attachment; filename=\"{nama}\"; filename*=UTF-8''{quote(nama)}",
                 "Cache-Control": "private, no-store"})
