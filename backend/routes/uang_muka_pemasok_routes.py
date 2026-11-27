"""Uang muka ke pemasok (CBD / DP) di PO — endpoint. Aturan & jurnal di `core.uang_muka_pemasok` (27 Nov 2026).

Izin: melihat = siapa pun yang boleh membuka PO (gerbang modul); bayar / kembalikan / batalkan = izin pembayaran Keuangan
(sama dengan Bayar hutang, `routes.rahaza_finance._require_fin`) + gerbang `fin_pencairan` (ENDPOINT_RULES).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from auth import require_auth, serialize_doc
from core import uang_muka_pemasok as um
from database import get_db

router = APIRouter(prefix="/api/rahaza", tags=["procurement"])


@router.get("/purchase-orders/{po_id}/uang-muka")
async def daftar_uang_muka(po_id: str, user: dict = Depends(require_auth)):
    return serialize_doc(await um.daftar(get_db(), po_id))


@router.post("/purchase-orders/{po_id}/uang-muka")
async def bayar_uang_muka(po_id: str, request: Request):
    from routes.rahaza_finance import _require_fin
    user = await _require_fin(request)
    return serialize_doc(await um.bayar(get_db(), po_id, await request.json(), user))


@router.post("/purchase-orders/{po_id}/uang-muka/{adv_id}/kembalikan")
async def kembalikan_uang_muka(po_id: str, adv_id: str, request: Request):
    from routes.rahaza_finance import _require_fin
    user = await _require_fin(request)
    return serialize_doc(await um.kembalikan(get_db(), adv_id, await request.json(), user))


@router.post("/purchase-orders/{po_id}/uang-muka/{adv_id}/batal")
async def batal_uang_muka(po_id: str, adv_id: str, request: Request):
    from routes.rahaza_finance import _require_fin
    user = await _require_fin(request)
    body = await request.json()
    return serialize_doc(await um.batalkan(get_db(), adv_id, body.get("alasan"), user))
