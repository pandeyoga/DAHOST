"""
universal_scan.py — Universal Multi-Entity Barcode / QR Code Resolver

GET  /api/scan/{code}   — Resolve kode ke entity (FG/bahan/bin/roll/bundle/dokumen/aset)
POST /api/scan/resolve  — Sama, tapi lewat body (untuk QR JSON panjang)
GET  /api/scan/history  — Riwayat scan terbaru (audit trail)

2026-11-02 (Paket 3a): pencarian dipindah ke `core.scan_resolver` (SSOT). Dulu
berkas ini punya tujuh resolver sendiri yang mencari field/koleksi yang tidak ada
(`rahaza_materials.material_code`, `wms_fabric_rolls.roll_number`) sehingga SKU FG,
kode bahan, roll, bin, dan QR label FG selalu "tidak ditemukan". Bentuk respons
lama (`entity_type`, `entity_number`, `display_name`, `meta`, `quick_actions`)
dipertahankan; kolom baku resolver (`tipe`, `id`, `kode`, `sku`, `nama`,
`satuan`, `aktif`, `via`) ikut dikirim. Parameter opsional `expect` membatasi tipe.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth
from core import scan_resolver as sr

logger = logging.getLogger("universal_scan")

router = APIRouter(prefix="/api/scan", tags=["universal_scan"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _uid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


def _ser(doc: dict) -> dict:
    if not doc:
        return doc
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if hasattr(v, "isoformat"):
            doc[k] = v.isoformat()
    return doc


# tipe resolver → (entity_type lama, label, aksi cepat {id, label, module})
_LEGACY = {
    "fg": ("fg", "Barang Jadi (SKU)", ("view_fg", "Lihat Stok Barang Jadi", "wh-fg")),
    "material": ("material", "Material / Aksesori", ("view_material", "Lihat Stok", "wh-materials")),
    "bin": ("bin", "Lokasi / Bin", ("view_bin", "Lihat Struktur Gudang", "wh-structure")),
    "roll": ("fabric_roll", "Roll Kain", ("view_roll", "Lihat Roll Kain", "wms-fabric-rolls")),
    "bundle": ("bundle", "Bundle Produksi", ("view_bundle", "Lihat Detail Bundle", "prod-bundles")),
    "aset": ("asset", "Aset", ("view_asset", "Lihat Detail Aset", "asset-list")),
}
_DOC_LEGACY = {
    "work_order": ("work_order", "Work Order", ("view_wo", "Lihat Work Order", "prod-work-orders")),
    "purchase_order": ("purchase_order", "Purchase Order",
                       ("view_po", "Lihat Purchase Order", "proc-purchase-orders")),
    "delivery_order": ("delivery_order", "Delivery Order", ("view_do", "Lihat DO", "do-management")),
}


def _legacy_view(res: dict) -> dict:
    """Hasil baku resolver → bentuk respons Universal Scan (kompatibel FE lama)."""
    if res["tipe"] == "dokumen":
        etype, elabel, qa = _DOC_LEGACY.get(res["subtipe"], ("document", "Dokumen", None))
    else:
        etype, elabel, qa = _LEGACY[res["tipe"]]
    doc = res.get("_doc") or {}
    status = doc.get("status") or ("" if res.get("aktif", True) else "inactive")
    if res["tipe"] in ("fg", "material"):
        status = "active" if res.get("aktif", True) else "inactive"
    actions = []
    if qa:
        actions.append({"id": qa[0], "label": qa[1], "module": qa[2], "entity_id": res["id"]})
    if res["tipe"] == "aset":
        actions.append({"id": "scan_asset", "label": "Catat Scan / Update Lokasi", "action": "scan_asset",
                        "entity_id": res["id"], "asset_number": res["kode"]})
    return {
        "entity_type": etype,
        "entity_type_label": elabel,
        "entity_id": res["id"],
        "entity_number": res["kode"],
        "display_name": res["nama"] or res["kode"],
        "status": status,
        "meta": res.get("meta") or {},
        "quick_actions": actions,
        **sr.public(res),
    }


async def _do_resolve(db, raw_code: str, user: dict, expect=None):
    code = sr.normalize_code(raw_code)
    result = None
    try:
        res = await sr.resolve(db, code, expect=expect)
        result = _legacy_view(res) if res else None
    except Exception as e:  # noqa: BLE001 — satu resolver error tidak boleh jadi 500
        logger.warning(f"Resolver error untuk {code!r}: {e}")

    # Log scan event
    scan_doc = {
        "id": _uid(),
        "raw_code": code,
        "scanned_by": user["id"],
        "scanned_by_name": user.get("name", ""),
        "found": result is not None,
        "entity_type": result["entity_type"] if result else None,
        "tipe": result["tipe"] if result else None,
        "entity_id": result["entity_id"] if result else None,
        "entity_number": result["entity_number"] if result else None,
        "display_name": result["display_name"] if result else None,
        "scanned_at": _now(),
    }
    try:
        await db.dewi_universal_scans.insert_one(scan_doc)
    except Exception as e:
        logger.warning(f"Failed to log scan: {e}")

    if not result:
        return {"found": False, "raw_code": code, "scan_id": scan_doc["id"]}

    return {"found": True, "scan_id": scan_doc["id"], **result}


def _expect_or_400(value):
    try:
        return sr.parse_expect(value)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/history")
async def get_scan_history(request: Request, limit: int = 50):
    """Riwayat scan universal (50 terbaru)."""
    await require_auth(request)
    db = get_db()
    docs = await db.dewi_universal_scans.find(
        {}, {"_id": 0}
    ).sort("scanned_at", -1).limit(max(1, min(limit, 200))).to_list(200)
    return [_ser(d) for d in docs]


@router.post("/resolve")
async def resolve_scan_post(request: Request):
    """Resolve kode dari body JSON (untuk QR code panjang). Body: {code, expect?}."""
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    code = sr.normalize_code(body.get("code") or "")
    if not code:
        raise HTTPException(400, "Field 'code' tidak boleh kosong.")
    return await _do_resolve(db, code, user, expect=_expect_or_400(body.get("expect")))


@router.get("/{code:path}")
async def resolve_scan_get(code: str, request: Request, expect: str = ""):
    """Resolve kode dari URL path parameter."""
    user = await require_auth(request)
    db = get_db()
    if not sr.normalize_code(code):
        raise HTTPException(400, "Kode tidak boleh kosong.")
    return await _do_resolve(db, code, user, expect=_expect_or_400(expect))
