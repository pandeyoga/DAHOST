"""Belum masuk jurnal — daftar + posting ulang (Paket 1 audit keuangan 25 Nov 2026). Aturan di `core.jurnal_tertunda`.

Izin: melihat = siapa pun yang boleh membuka Jurnal (gerbang modul `fin_journal`); posting ulang = izin menyetujui
jurnal (sama dengan tombol posting jurnal), dicek lagi di sini.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import require_auth
from core import jurnal_tertunda as jt
from database import get_db

router = APIRouter(prefix="/api/rahaza/finance/jurnal-tertunda", tags=["finance"])

_IZIN_ULANG = ("finance.approve", "finance.manage", "finance.post")
_PERAN_ULANG = ("owner", "admin", "superadmin", "accounting", "manager_keuangan", "finance_manager",
                "staff_keuangan", "finance")


def _boleh_ulang(user: dict) -> bool:
    from routes.shared import can_act
    return can_act(user, *_IZIN_ULANG, legacy_roles=_PERAN_ULANG)


@router.get("")
async def daftar(user: dict = Depends(require_auth)):
    from routes.shared import assert_can_act
    assert_can_act(user, "finance.read", *_IZIN_ULANG, portal=None, legacy_roles=_PERAN_ULANG,
                   what="melihat dokumen yang belum masuk jurnal")
    out = await jt.daftar(get_db())
    return {**out, "boleh_ulang": _boleh_ulang(user)}


@router.post("/{jenis}/{doc_id}/ulang")
async def posting_ulang(jenis: str, doc_id: str, user: dict = Depends(require_auth)):
    from routes.shared import assert_can_act
    assert_can_act(user, *_IZIN_ULANG, portal=None, legacy_roles=_PERAN_ULANG, what="memposting ulang jurnal")
    return await jt.ulang(get_db(), jenis, doc_id, user)
