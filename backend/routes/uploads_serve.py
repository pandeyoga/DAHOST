"""GET /api/uploads/{path} — berkas unggahan dari penyimpanan lokal (fallback object storage).

Dipindah dari `server.py` (2026-11-07) supaya bisa diuji tanpa mengimpor seluruh aplikasi.

KEAMANAN (2026-11-07): dulu SEMUA berkas di sini terbuka tanpa login — termasuk selfie absen,
surat dokter cuti, foto profil, dan KTP/KK/BPJS karyawan. Kini berkas sensitif
(`core/sensitive_files.py`) wajib token Bearer atau `?auth=`, diperiksa `auth.verify_download_token`
seperti `GET /api/files/{path}`. Foto produk, logo, foto aset, dan lampiran chat tetap terbuka.
"""
from fastapi import APIRouter, HTTPException, Query, Request, Response

import object_storage as _objstore
from core.sensitive_files import file_request_user, is_sensitive_upload, normalize_upload_path
from database import get_db

router = APIRouter()


@router.get('/api/uploads/{path:path}')
async def serve_upload(path: str, request: Request, auth: str = Query(None)):
    if '..' in path:
        raise HTTPException(status_code=400, detail='path tidak valid')
    norm = normalize_upload_path(path)
    if not norm:
        raise HTTPException(status_code=404, detail='Berkas tidak ditemukan')
    sensitive = await is_sensitive_upload(get_db(), path)
    if sensitive and not file_request_user(request, auth):
        raise HTTPException(status_code=401, detail='Silakan masuk untuk membuka berkas ini.')
    found = _objstore.get_object(norm)
    if not found:
        raise HTTPException(status_code=404, detail='Berkas tidak ditemukan')
    headers = {'Cache-Control': 'private, no-store'} if sensitive else None
    return Response(content=found[0], media_type=found[1], headers=headers)
