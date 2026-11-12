"""Analisa Merchandiser (keputusan owner K-M1..K-M10, 12 Nov 2026) — layar Portal Manajemen & alat Asisten AI.

Angka dari SATU sumber `core.merchandiser` (laju jual, stok perkiraan, WIP, minggu persediaan, kelas, saran).
Hanya membaca. Staf DA saja (klien & vendor CMT ditolak; peran portal marketing ditolak di server.py).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from auth import require_auth
from core import merchandiser as mc
from database import get_db
from routes.production_rbac import deny_klien, is_vendor
from utils.waktu import today_wib

router = APIRouter(prefix="/api/merchandiser", tags=["merchandiser"])


async def _staff(request: Request) -> dict:
    user = await require_auth(request)
    deny_klien(user)
    if is_vendor(user):
        raise HTTPException(403, "Analisa Merchandiser hanya untuk staf DA.")
    return user


@router.get("/analisa")
async def get_analisa(request: Request,
                      tingkat: str = Query("model", pattern="^(model|warna|varian)$"),
                      minggu: Optional[int] = Query(None, ge=1, le=26),
                      toko: Optional[str] = Query(None, max_length=80),
                      model_id: Optional[str] = Query(None, max_length=80),
                      kelas: Optional[str] = Query(None, max_length=60)):
    """Per model | warna | varian: laju jual mingguan, stok perkiraan, WIP, minggu persediaan, kelas, saran.
    `kelas` (opsional, dipisah koma): mati,lambat,awas,sehat,laris,habis."""
    await _staff(request)
    out = await mc.analisa(get_db(), hari_ini=today_wib(), minggu=minggu, toko=toko or None, tingkat=tingkat,
                           model_id=model_id or None)
    if kelas:
        pilih = {k.strip() for k in kelas.split(",") if k.strip()}
        if pilih - set(mc.KELAS):
            raise HTTPException(400, "Pilihan kelas tidak dikenal.")
        out["baris"] = [r for r in out["baris"] if r["kelas"] in pilih]
    return out


@router.get("/cek-rencana")
async def get_cek_rencana(request: Request, model_id: str = Query(..., max_length=80),
                          qty: float = Query(..., gt=0, le=1_000_000),
                          variant_id: Optional[str] = Query(None, max_length=80)):
    """Persediaan sesudah tambahan produksi/pembelian `qty` pcs → aman | perlu alasan (beserta alasannya)."""
    await _staff(request)
    return await mc.cek_rencana(get_db(), hari_ini=today_wib(), model_id=model_id, qty=qty,
                                variant_id=variant_id or None)
