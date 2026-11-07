"""Asisten AI — chat analis Portal Manajemen (Tahap A, 7 Nov 2026). Kontrak B.

Prefix `/api/asisten-ai`. Semua endpoint: login + akses Portal Manajemen (`require_portal`,
aturan yang sama dengan portal itu). Data yang dibaca alat mengikuti hak akses PENGGUNA sendiri
(alat memanggil endpoint aplikasi dengan token pengguna, lihat core/asisten_ai/alat_base.py).

  GET    /status                   kesiapan AI (kunci terisi? AI aktif? sisa anggaran) — kunci tidak dikirim
  GET    /saran?peran=             tombol saran per peran
  GET    /sessions                 percakapan milik sendiri (terbaru dulu)
  POST   /sessions {judul?}        percakapan baru
  GET    /sessions/{id}            isi percakapan (blok tampilan; isi mentah API tidak dikirim)
  PATCH  /sessions/{id} {judul}    ganti judul
  DELETE /sessions/{id}            hapus lunak
  POST   /sessions/{id}/messages {teks, cv, periode?}  → text/event-stream (mulai, status, pikir, teks,
         alat, grafik, tabel, sumber, laporan, selesai, galat)

Hentikan: klien membatalkan fetch → server melihat koneksi putus, loop berhenti, jawaban parsial
disimpan berstatus `terhenti`.
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from auth import require_auth
from core.asisten_ai import mesin, saran, simpan
from database import get_db
from routes.shared import require_portal_dep
from utils.waktu import today_wib

router = APIRouter(prefix="/api/asisten-ai", tags=["asisten-ai"],
                   dependencies=[Depends(require_portal_dep("management"))])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
_PERIODE_RX = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CV_SAH = ("DA", "SMU", "ALL")


def _token(request: Request) -> Optional[str]:
    h = request.headers.get("Authorization") or ""
    return h.split(" ", 1)[1].strip() if h.startswith("Bearer ") and " " in h else None


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:  # noqa: BLE001 — badan kosong/bukan JSON
        return {}
    return b if isinstance(b, dict) else {}


@router.get("/status")
async def status(request: Request):
    await require_auth(request)
    return await mesin.status_siap()


@router.get("/saran")
async def daftar_saran(request: Request, peran: Optional[str] = None):
    user = await require_auth(request)
    return saran.saran_untuk(peran or user.get("role"))


@router.get("/sessions")
async def daftar_sesi(request: Request):
    user = await require_auth(request)
    return await simpan.daftar_sesi(get_db(), user["id"])


@router.post("/sessions")
async def buat_sesi(request: Request):
    user = await require_auth(request)
    body = await _body(request)
    return await simpan.buat_sesi(get_db(), user["id"], body.get("judul"))


@router.get("/sessions/{sesi_id}")
async def ambil_sesi(sesi_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    sesi = await simpan.ambil_sesi(db, user["id"], sesi_id)
    if not sesi:
        raise HTTPException(404, "Percakapan tidak ditemukan.")
    return {"id": sesi["id"], "judul": sesi.get("judul") or simpan.JUDUL_BAWAAN,
            "created_at": sesi.get("created_at"), "updated_at": sesi.get("updated_at"),
            "sedang_berjalan": mesin.sedang_berjalan(sesi["id"]),
            "pesan": await simpan.ambil_pesan(db, user["id"], sesi_id)}


@router.patch("/sessions/{sesi_id}")
async def ubah_sesi(sesi_id: str, request: Request):
    user = await require_auth(request)
    body = await _body(request)
    try:
        out = await simpan.ubah_judul(get_db(), user["id"], sesi_id, body.get("judul"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not out:
        raise HTTPException(404, "Percakapan tidak ditemukan.")
    return out


@router.delete("/sessions/{sesi_id}")
async def hapus_sesi(sesi_id: str, request: Request):
    user = await require_auth(request)
    if not await simpan.hapus_sesi(get_db(), user["id"], sesi_id):
        raise HTTPException(404, "Percakapan tidak ditemukan.")
    return {"ok": True}


@router.post("/sessions/{sesi_id}/messages")
async def kirim_pesan(sesi_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    body = await _body(request)
    teks = str(body.get("teks") or "").strip()
    if not teks:
        raise HTTPException(400, "Pertanyaan wajib diisi.")
    if len(teks) > mesin.MAKS_TEKS_PENGGUNA:
        raise HTTPException(400, f"Pertanyaan terlalu panjang (maksimal {mesin.MAKS_TEKS_PENGGUNA} karakter).")
    cv = str(body.get("cv") or "DA").strip().upper()
    if cv not in CV_SAH:
        raise HTTPException(400, "Pilihan CV harus DA, SMU, atau ALL.")
    today = today_wib()
    periode = str(body.get("periode") or "").strip() or today.strftime("%Y-%m")
    if not _PERIODE_RX.match(periode):
        raise HTTPException(400, "Periode harus berformat YYYY-MM, mis. 2026-11.")
    sesi = await simpan.ambil_sesi(db, user["id"], sesi_id)
    if not sesi:
        raise HTTPException(404, "Percakapan tidak ditemukan.")

    jalan, galat = await mesin.siapkan_jalan(db=db, user=user, sesi=sesi, teks=teks, cv=cv, periode=periode,
                                             today=today, token=_token(request), app=request.app)
    if galat:
        return StreamingResponse(mesin.aliran_galat(galat["kode"], galat["pesan"]),
                                 media_type="text/event-stream", headers=_SSE_HEADERS)
    mesin.mulai(jalan)
    return StreamingResponse(mesin.aliran_sse(jalan, request), media_type="text/event-stream",
                             headers=_SSE_HEADERS)
