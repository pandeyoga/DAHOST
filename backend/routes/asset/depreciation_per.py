"""Per-asset depreciation:
  POST /{asset_id}/depreciate/{period}
  GET  /{asset_id}/depreciation-history
"""
from fastapi import Request, HTTPException

from database import get_db
from auth import require_auth
from ._helpers import router, _ser, DEPRECIATION_MOVED_MSG


@router.post("/{asset_id}/depreciate/{period}")
async def post_depreciation(asset_id: str, period: str, request: Request):
    """2026-11-02 (K18): DIMATIKAN — penyusutan hanya dari registri Keuangan (Aset Tetap).
    Dulu: jurnal draft akun hantu 6200/1590, source_ref sama dgn jurnal pembelian → E11000 diam-diam."""
    await require_auth(request)
    raise HTTPException(410, DEPRECIATION_MOVED_MSG)


@router.get("/{asset_id}/depreciation-history")
async def get_depreciation_history(asset_id: str, request: Request):
    """Riwayat penyusutan: aset tertaut → jadwal yang SUDAH diposting di registri Keuangan (K18);
    belum tertaut → kosong (Portal Aset tidak menyusutkan; tautkan ke aset Keuangan)."""
    await require_auth(request)
    db = get_db()
    asset = await db.dewi_assets.find_one({"id": asset_id}, {"_id": 0, "fixed_asset_id": 1})
    if not asset or not asset.get("fixed_asset_id"):
        return []
    rows = await db.rahaza_depr_schedules.find(
        {"asset_id": asset["fixed_asset_id"], "posted": True}, {"_id": 0}).sort("period", -1).to_list(240)
    return [_ser({**r, "amount": r.get("depr_amount"), "cumulative": r.get("accumulated_depr"),
                  "source": "finance_registry"}) for r in rows]
