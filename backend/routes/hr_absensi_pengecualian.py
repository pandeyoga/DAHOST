"""Rekap absensi & pengecualian (audit HR Tahap D, 9 Nov 2026) — BACA SAJA.

  GET /api/hr/absensi/pengecualian?dari=&sampai=&departemen=&employee_id=
Aturan di `core/absensi_pengecualian.py` (deterministik; Asisten AI hanya merangkum hasilnya). Hanya SDM/atasan/
pemegang Portal SDM (`can_view_all_employees`) — isinya absensi seluruh karyawan.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from auth import require_auth
from core import absensi_pengecualian as ap
from core.shift_roster import GalatRoster
from database import get_db
from utils.waktu import today_wib

router = APIRouter(prefix="/api/hr/absensi", tags=["hr-absensi-pengecualian"])


@router.get("/pengecualian")
async def pengecualian(request: Request, dari: str, sampai: str, departemen: Optional[str] = None,
                       employee_id: Optional[str] = None):
    user = await require_auth(request)
    from utils.employee_identity import can_view_all_employees
    if not can_view_all_employees(user):
        raise HTTPException(403, "Hanya SDM dan atasan yang boleh membaca rekap absensi karyawan lain.")
    try:
        return await ap.rekap(get_db(), dari=dari, sampai=sampai, today=today_wib(), departemen=departemen,
                              employee_ids=[employee_id] if employee_id else None)
    except GalatRoster as e:
        raise HTTPException(e.status, e.pesan)
