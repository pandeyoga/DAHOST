"""GET /api/asisten-ai/berkas/{id} — unduh berkas keluaran "hitung dengan kode" Asisten AI (Tahap E, 9 Nov 2026, K3).

Berkas dibuat kode Claude di ruang hitung, diambil lewat Files API, lalu disimpan salinannya oleh
`core/asisten_ai/berkas_kode.py` di penyimpanan unggahan (path acak `ai_berkas/<id>/…`, tidak pernah dikirim ke layar).
Satu-satunya jalan mengunduh adalah rute ini (pola sama dengan unduh laporan `asisten_ai_laporan_routes.py`):
  * wajib login (Bearer) + akses Portal Management (dipasang di server.py, sama dengan Asisten AI);
  * hanya PEMBUAT berkas (pemilik percakapan), ditambah owner/superadmin (`berkas_kode.boleh_unduh`);
  * selalu `Content-Disposition: attachment` + `nosniff`; jenis yang bisa dieksekusi peramban (html, svg, js, …)
    dikirim sebagai biner.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from auth import require_auth
from core.asisten_ai import berkas_kode as bk
from database import get_db

router = APIRouter(prefix="/api/asisten-ai", tags=["asisten-ai-berkas"])


def _ambil_berkas(path: str):
    import object_storage
    return object_storage.get_object(path)


def _nama_ascii(nama: str, fmt: str) -> str:
    n = re.sub(r"[^A-Za-z0-9 ._()-]+", "_", nama).strip(" ._") or "hasil"
    return n if n.lower().endswith(f".{fmt}") or fmt == "berkas" else f"{n}.{fmt}"


@router.get("/berkas/{berkas_id}")
async def unduh_berkas(berkas_id: str, request: Request):
    user = await require_auth(request)
    doc = await get_db()[bk.COLL].find_one({"id": berkas_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Berkas tidak ditemukan.")
    if not bk.boleh_unduh(user, doc):
        raise HTTPException(403, "Berkas ini dibuat di percakapan pengguna lain. Hanya pemiliknya dan owner yang bisa "
                                 "mengunduh.")
    found = _ambil_berkas(doc.get("path") or "")
    if not found:
        raise HTTPException(404, "Berkas sudah tidak tersedia. Minta Asisten AI membuatnya lagi.")
    fmt = doc.get("format") or bk.format_dari(doc.get("nama") or "")
    nama = doc.get("nama") or f"hasil.{fmt}"
    return Response(
        content=found[0], media_type=bk.content_type_dari(fmt, doc.get("mime")),
        headers={"Content-Disposition": f"attachment; filename=\"{_nama_ascii(nama, fmt)}\"; "
                                        f"filename*=UTF-8''{quote(nama)}",
                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
