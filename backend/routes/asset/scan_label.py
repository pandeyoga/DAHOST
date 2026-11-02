"""Scan / barcode / qrcode / label-PDF endpoints (per asset).

Includes:
  POST /{asset_id}/scan
  GET  /{asset_id}/scan-history
  GET  /{asset_id}/barcode      (410 — 2026-11-02: dipindah ke label aset tunggal)
  GET  /{asset_id}/qrcode       (410 — 2026-11-02: dipindah ke label aset tunggal)
  GET  /{asset_id}/label-pdf    (PDF, template=standard|sticker|a4 — generator core/label_render)

Note: /scan-by-number/{num} lives in scan_lookup.py (literal-path module).
"""
import logging
from fastapi import Request, HTTPException
from fastapi.responses import Response

from database import get_db
from auth import require_auth
from ._helpers import router, _uid, _now, _ser

logger = logging.getLogger("asset_mgmt.scan_label")


@router.post("/{asset_id}/scan")
async def scan_asset(asset_id: str, request: Request):
    """Scan asset untuk tracking lokasi/movement."""
    user = await require_auth(request)
    db = get_db()
    body = await request.json()

    asset = await db.dewi_assets.find_one({"id": asset_id}, {"_id": 0})
    if not asset:
        raise HTTPException(404, "Aset tidak ditemukan.")

    scan_doc = {
        "id": _uid(),
        "asset_id": asset_id,
        "asset_number": asset["asset_number"],
        "asset_name": asset["name"],
        "scanned_by": user["id"],
        "scanned_by_name": user.get("name", ""),
        "scan_type": body.get("scan_type", "location_check"),
        "location": (body.get("location") or "").strip(),
        "notes": (body.get("notes") or "").strip(),
        "scanned_at": _now(),
    }
    await db.dewi_asset_scans.insert_one(scan_doc)

    update = {}
    if body.get("location"):
        update["location"] = body["location"]
        update["updated_at"] = _now()
    if update:
        await db.dewi_assets.update_one({"id": asset_id}, {"$set": update})

    return {"ok": True, "scan_id": scan_doc["id"], "asset": _ser(asset)}


@router.get("/{asset_id}/scan-history")
async def get_asset_scan_history(asset_id: str, request: Request):
    """Riwayat scan asset."""
    await require_auth(request)
    db = get_db()
    scans = await db.dewi_asset_scans.find(
        {"asset_id": asset_id}, {"_id": 0}
    ).sort("scanned_at", -1).limit(50).to_list(50)
    return [_ser(s) for s in scans]


# ── 2026-11-02 (registri aset tunggal) ──────────────────────────────────────────
# Label aset dicetak SATU generator (`core/label_render`: kind `asset` 90×50 / `asset_small` 50×25)
# dengan kode registri induk Keuangan (`rahaza_fixed_assets.code`). Generator kembar di sini (PNG
# python-barcode + QR JSON berisi URL) DIHAPUS: barcode & QR berdiri sendiri kini ada di dalam label.
_LABEL_MOVED = ("Barcode/QR aset kini dicetak di label aset tunggal (kode registri Aset Tetap) — "
                "gunakan GET /api/assets/{id}/label-pdf.")


@router.get("/{asset_id}/barcode")
async def get_asset_barcode(asset_id: str, request: Request):
    await require_auth(request)
    raise HTTPException(410, _LABEL_MOVED)


@router.get("/{asset_id}/qrcode")
async def get_asset_qrcode(asset_id: str, request: Request):
    await require_auth(request)
    raise HTTPException(410, _LABEL_MOVED)


async def asset_label_response(db, *, asset_id: str = "", fixed_asset_id: str = "",
                               template: str = "standard") -> Response:
    """PDF label aset dari generator bersama. Dipakai Portal Aset & Keuangan › Aset Tetap."""
    from core import label_render as lr
    if not lr.LABELS_OK:
        raise HTTPException(500, "Pustaka pencetak label tidak tersedia")
    try:
        doc = await lr.asset_label_doc(db, asset_id=asset_id, fixed_asset_id=fixed_asset_id)
        if template == "a4":
            cols, rows, _, _ = lr.grid_geometry(lr.A4[0], lr.A4[1], lr.ASSET_LABEL_MM[0] * lr.mm,
                                                lr.ASSET_LABEL_MM[1] * lr.mm)
            pdf = lr.grid_labels_pdf("asset", [doc] * (cols * rows), title=f"Label aset {doc['label_code']}")
        else:
            pdf = lr.single_label_pdf("asset_small" if template == "sticker" else "asset", doc)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except lr.LabelCodeError as e:
        raise HTTPException(400, str(e))
    return Response(content=pdf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="asset-label-{doc["label_code"]}.pdf"'})


@router.get("/{asset_id}/label-pdf")
async def get_asset_label_pdf(asset_id: str, request: Request, template: str = "standard"):
    """Label aset (PDF). Template: standard (90×50) | sticker (50×25) | a4 (satu halaman A4 berisi label).
    Kode = kode registri Aset Tetap (Keuangan); aset yang belum tertaut ditolak 400."""
    await require_auth(request)
    return await asset_label_response(get_db(), asset_id=asset_id, template=template)
