"""routes.marketing_laporan_ai — **Laporan Marketing mode AI** (mingguan/bulanan) — audit Marketing §6.4.

  ``GET  /api/marketing/laporan-ai/fakta``  paket fakta berangka (dihitung kode, tanpa AI) — dipakai layar
                                            dan alat Asisten AI `paket_laporan_marketing`
  ``POST /api/marketing/laporan-ai/susun``  buka percakapan Asisten AI yang menyusun laporan PDF/Excel dari
                                            paket fakta (penjaga angka di alat `buat_laporan_marketing`)

Lingkup toko & CV mengikuti pembaca analitik resmi (`ukuran_penjualan.toko_terlihat`).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from auth import require_auth
from core import entities as _ent
from core import laporan_marketing as lm
from core import marketing_account_scope as scope
from core import ukuran_penjualan as U
from database import get_db
from utils.waktu import today_wib

router = APIRouter(prefix="/api/marketing/laporan-ai", tags=["marketing-laporan-ai"])


async def _konteks(request: Request, toko_id: Optional[str]):
    user = await require_auth(request)
    db = get_db()
    cv = _ent.entity_from_request(request, allow_all=True)
    if toko_id:
        await scope.assert_account_visible(db, user, toko_id)
    accounts = await U.toko_terlihat(db, user, cv=cv, toko_id=toko_id or None)
    return user, db, cv, accounts


@router.get("/fakta")
async def fakta(request: Request,
                jenis: str = Query("mingguan", pattern="^(mingguan|bulanan|rentang)$"),
                dari: Optional[str] = Query(None), sampai: Optional[str] = Query(None),
                toko_id: Optional[str] = Query(None), simpan: bool = Query(True)):
    user, db, cv, accounts = await _konteks(request, toko_id)
    try:
        a, b, label = lm.periode_laporan(jenis, today_wib(), dari, sampai)
        isi = await lm.paket_fakta(db, accounts, jenis=jenis, dari=a, sampai=b, label=label, cv=cv)
    except lm.GalatLaporan as e:
        raise HTTPException(e.status, e.pesan) from None
    except (U.PeriodeSalah, ValueError) as e:
        raise HTTPException(400, str(e)) from None
    if not accounts:
        isi.setdefault("kualitas_data", {}).setdefault("catatan", []).insert(
            0, scope.NO_ACCOUNT_HINT if not scope.sees_all_accounts(user) else "Tidak ada toko pada pilihan CV ini.")
    fid = await lm.simpan_fakta(db, isi, user) if simpan else None
    return {"ok": True, "fakta_id": fid, "cv_label": _ent.entity_short(cv), **isi}


class SusunIn(BaseModel):
    jenis: str = "mingguan"
    dari: Optional[str] = None
    sampai: Optional[str] = None
    toko_id: Optional[str] = None


@router.post("/susun")
async def susun(body: SusunIn, request: Request):
    """Mulai percakapan Asisten AI yang menyusun Laporan Marketing (PDF + Excel)."""
    user, db, cv, _accounts = await _konteks(request, body.toko_id)
    if body.jenis not in lm.JENIS:
        raise HTTPException(400, "Jenis laporan harus mingguan, bulanan, atau rentang.")
    try:
        a, b, label = lm.periode_laporan(body.jenis, today_wib(), body.dari, body.sampai)
    except lm.GalatLaporan as e:
        raise HTTPException(e.status, e.pesan) from None
    except ValueError:
        raise HTTPException(400, "Tanggal periode harus berformat TTTT-BB-HH.") from None
    teks = lm.prompt_laporan(body.jenis, a, b, label, body.toko_id)
    return await lm.mulai_percakapan(request, user, judul=f"Laporan Marketing {label}", teks=teks, cv=cv)
