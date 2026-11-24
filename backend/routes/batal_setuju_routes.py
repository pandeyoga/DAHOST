"""Batalkan persetujuan — satu pintu untuk semua jenis persetujuan (permintaan owner 24 Nov 2026).

Aturan lengkap ada di `core.batal_setuju`; daftar jenis di `core.batal_setuju_jenis`.

    GET  /api/batal-setuju/jenis                    → jenis yang dikenal (label, portal)
    GET  /api/batal-setuju/disetujui?hari=30        → yang disetujui 30 hari terakhir (Pusat Persetujuan)
    GET  /api/batal-setuju/{jenis}/{id}/cek         → boleh dibatalkan? + kalimat penahan
    POST /api/batal-setuju/{jenis}/{id}  {alasan}   → batalkan; status kembali ke sebelum disetujui
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from auth import require_auth
from core import batal_setuju as bs
from database import get_db

router = APIRouter(prefix="/api/batal-setuju", tags=["batal-setuju"])


class BodyBatal(BaseModel):
    alasan: str = Field("", max_length=1000)


@router.get("/jenis")
async def daftar_jenis(user: dict = Depends(require_auth)):
    """Jenis yang dikenal + `boleh` (pengguna ini boleh membatalkan = boleh menyetujui) — layar menyembunyikan
    tombol Batalkan persetujuan bila tidak boleh."""
    from routes.shared import can_act, lolos_centang
    bs._muat()
    centang = lolos_centang(user)
    return {"data": [{"kode": j.kode, "label": j.label, "portal": j.portal, "modul": j.modul,
                      "kembali_ke": j.label_kembali,
                      "boleh": bool(centang or can_act(user, *j.izin, legacy_roles=j.peran_lama))}
                     for j in bs.JENIS.values()]}


@router.get("/disetujui")
async def daftar_disetujui(hari: int = Query(30, ge=1, le=366), user: dict = Depends(require_auth)):
    data = await bs.disetujui_terbaru(get_db(), user, hari=hari)
    return {"data": data, "total": len(data)}


@router.get("/{jenis}/{doc_id}/cek")
async def cek_batal(jenis: str, doc_id: str, user: dict = Depends(require_auth)):
    j = bs.ambil_jenis(jenis)
    bs.periksa_izin(j, user)
    db = get_db()
    doc = await bs._dok(db, j, doc_id)
    hasil = await bs.cek(db, j, doc)
    return {**hasil, "jenis": j.kode, "label": j.label, "nama": j.nama(doc), "label_kembali": j.label_kembali}


@router.post("/{jenis}/{doc_id}")
async def batal_setuju(jenis: str, doc_id: str, body: BodyBatal, user: dict = Depends(require_auth)):
    return await bs.batalkan(get_db(), jenis, doc_id, user, body.alasan)
