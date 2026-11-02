"""/api/assets/batch-depreciate/{period} — LITERAL path; must precede /{asset_id}.

2026-11-02 (K18, keputusan owner): DIMATIKAN. Penyusutan hanya dari registri Keuangan
(`POST /api/rahaza/finance/fixed-assets/run-batch-depreciation`, menu Keuangan › Aset Tetap /
Penyesuaian Akhir Periode). Dulu endpoint ini membuat jurnal draft dengan akun hantu 6200/1590 dan
`source_ref` = nomor aset yang sama dengan jurnal pembelian → E11000 diam-diam (jurnal tidak terbentuk)
padahal akumulasi Portal Aset tetap naik. Path dipertahankan supaya klien lama mendapat pesan jelas.
"""
from fastapi import HTTPException, Request

from auth import require_auth
from ._helpers import router, DEPRECIATION_MOVED_MSG


@router.post("/batch-depreciate/{period}")
async def batch_depreciate(period: str, request: Request):
    """K18: ditolak 410 — pakai penyusutan batch registri Keuangan."""
    await require_auth(request)
    raise HTTPException(410, DEPRECIATION_MOVED_MSG)
