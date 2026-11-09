"""
WMS — Fabric Roll Tracking (P0-WH-1)
CV. Dewi Aditya — Garment-grade kain/roll tracking

Collections:
  wh_fabric_rolls:
    id, roll_no (unique), material_id, material_code, material_name,
    color, color_lot, supplier_name, uom (meter|kg),
    length_m, weight_kg, received_date, po_no,
    qc_status (pending|pass|partial|reject),
    status (in_stock|partly_issued|fully_issued|returned|rejected),
    position_id, position_barcode,
    remaining_m, remaining_kg,
    unit_cost, notes,
    created_at, created_by, updated_at, updated_by

  wh_fabric_roll_movements:
    id, roll_id, roll_no, movement_type (receive|putaway|issue|return|adjust|reject),
    qty, unit, reference_type (po|wo|cmt|manual), reference_id, reference_no,
    from_location, to_location, notes,
    created_at, created_by

Endpoints (prefix /api/wms/fabric-rolls):
  GET    /                          list + filters (material, color, status, qc, position)
  POST   /                          DITUTUP (410) sejak 10 Nov 2026 — lihat `create_roll`
  GET    /{roll_id}                  detail + movements
  PUT    /{roll_id}                  update (qc_status, position, notes)
  DELETE /{roll_id}                  soft delete (only draft/pending)
  POST   /{roll_id}/putaway          simpan ke posisi rak — posisi WAJIB ada di master struktur gudang
  POST   /{roll_id}/issue            issue to WO/CMT (reduce remaining)
  POST   /{roll_id}/return           return remaining to stock
  POST   /{roll_id}/reject           mark as reject + supplier claim
  POST   /{roll_id}/adjust           manual quantity adjust
  GET    /stats/summary              aggregate: total rolls, meters, kg by status
  GET    /by-material/{material_id}  all rolls for a material
  GET    /by-lot/{color_lot}         all rolls in same lot
  GET    /{roll_id}/label-pdf        barcode label PDF
"""
# ruff: noqa: F401
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from database import get_db
from auth import require_auth, serialize_doc
from core import fabric_roll_engine  # FASE H-5: satu pintu penerbitan & pemakaian roll
import logging
from core.authz import only  # T-01 2.3
from core.roles import WAREHOUSE_ROLES  # T-01 2.3

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wms/fabric-rolls", tags=["wms-fabric-rolls"])

QC_STATUSES = ["pending", "pass", "partial", "reject"]
ROLL_STATUSES = ["in_stock", "partly_issued", "fully_issued", "returned", "rejected"]
# 2026-11-09 (impor roll stok awal): roll menunggu persetujuan stok awal / dibatalkan — tidak bisa dipakai.
LOCKED_STATUSES = ("pending_opening", "cancelled")


def _assert_usable(roll: dict) -> None:
    if (roll or {}).get("status") in LOCKED_STATUSES:
        raise HTTPException(400, (
            f"Roll {roll.get('roll_no')} " + ("masih menunggu persetujuan stok awal oleh Keuangan — belum bisa dipakai."
                                             if roll.get("status") == "pending_opening" else "sudah dibatalkan.")))


def _now(): return datetime.now(timezone.utc)
def _id(): return str(uuid.uuid4())


class PutAwayIn(BaseModel):
    # 2026-11-10 (keputusan owner): posisi dipilih dari master (gudang → zona → rak → posisi) ATAU di-scan.
    # Salah satu wajib; server mencocokkannya ke `wh_positions` — dulu dua-duanya teks bebas dan disimpan apa adanya.
    position_id: str = ""
    position_barcode: str = ""
    notes: str = ""


class IssueIn(BaseModel):
    qty: float = Field(..., gt=0, description="Quantity dalam UOM (meter atau kg)")
    unit: str = "meter"
    reference_type: str = Field("wo", pattern="^(wo|cmt|manual)$")
    reference_id: str = ""
    reference_no: str = ""
    notes: str = ""


class ReturnIn(BaseModel):
    qty: float = Field(..., gt=0)
    unit: str = "meter"
    reference_type: str = "wo"
    reference_id: str = ""
    reference_no: str = ""
    notes: str = ""


class RejectIn(BaseModel):
    reason: str = Field(..., min_length=3)
    claim_to_supplier: bool = False
    notes: str = ""


class AdjustIn(BaseModel):
    delta_m: float = Field(0.0, description="+/- meter adjustment")
    delta_kg: float = Field(0.0, description="+/- kg adjustment")
    reason: str = Field(..., min_length=3)


# ── Helpers ─────────────────────────────────────────────────────────────────────

async def _log_movement(db, roll: dict, movement_type: str, qty: float, unit: str,
                        ref_type: str, ref_id: str, ref_no: str,
                        from_loc: str, to_loc: str, notes: str, user_name: str):
    mov = {
        "id": _id(),
        "roll_id": roll["id"],
        "roll_no": roll["roll_no"],
        "movement_type": movement_type,
        "qty": qty,
        "unit": unit,
        "reference_type": ref_type,
        "reference_id": ref_id,
        "reference_no": ref_no,
        "from_location": from_loc,
        "to_location": to_loc,
        "notes": notes,
        "created_at": _now(),
        "created_by": user_name,
    }
    await db.wh_fabric_roll_movements.insert_one(mov)


def _recalc_status(roll: dict) -> str:
    remaining = roll.get("remaining_m", 0) or roll.get("remaining_kg", 0)
    if roll.get("status") in ("rejected", "returned"):
        return roll["status"]
    original = roll.get("length_m", 0) or roll.get("weight_kg", 0)
    if original <= 0:
        return "in_stock"
    if remaining <= 0:
        return "fully_issued"
    if remaining < original:
        return "partly_issued"
    return "in_stock"


# ── Endpoints ─────────────────────────────────────────────────────────────────────

@router.get("")
async def list_rolls(
    request: Request,
    material_id: Optional[str] = None,
    material_code: Optional[str] = None,
    color: Optional[str] = None,
    color_lot: Optional[str] = None,
    status: Optional[str] = None,
    qc_status: Optional[str] = None,
    position_id: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    await require_auth(request)
    db = get_db()
    q = {}
    if material_id:
        q["material_id"] = material_id
    if material_code:
        q["material_code"] = {"$regex": material_code, "$options": "i"}
    if color:
        q["color"] = {"$regex": color, "$options": "i"}
    if color_lot:
        q["color_lot"] = {"$regex": color_lot, "$options": "i"}
    if status:
        q["status"] = status
    if qc_status:
        q["qc_status"] = qc_status
    if position_id:
        q["position_id"] = position_id
    if search:
        q["$or"] = [
            {"roll_no": {"$regex": search, "$options": "i"}},
            {"material_name": {"$regex": search, "$options": "i"}},
            {"color": {"$regex": search, "$options": "i"}},
            {"color_lot": {"$regex": search, "$options": "i"}},
            {"supplier_name": {"$regex": search, "$options": "i"}},
        ]
    total = await db.wh_fabric_rolls.count_documents(q)
    skip = (page - 1) * limit
    rolls = await db.wh_fabric_rolls.find(q, {"_id": 0}).sort("received_date", -1).skip(skip).limit(limit).to_list(limit)
    return {
        # Setiap roll dikirim BESERTA satuan aslinya (`uom`, `qty_total`,
        # `qty_remaining`) + info konversi `qty_*_m`. Layar tidak boleh lagi
        # menebak "meter" dari nama field `length_m`/`remaining_m` (2026-08-21).
        "items": [serialize_doc(fabric_roll_engine.with_display_uom(r)) for r in rolls],
        "pagination": {
            "page": page, "limit": limit, "total": total,
            "total_pages": max(1, (total + limit - 1) // limit),
            "has_next": (skip + limit) < total,
            "has_prev": page > 1,
        }
    }


# 2026-11-10 (keputusan owner): input roll manual DITUTUP. Roll buatan tangan berstatus "Tersedia" tanpa
# menambah stok bahan dan tanpa jurnal ⇒ gulungan tanpa stok, atau gulungan dobel untuk kain yang sudah
# punya roll dari penerimaannya. Tiga jalur resmi (semuanya menjaga stok = isi gulungan):
#   1. Penerimaan Barang › rincian gulungan pada baris kain (`routes/warehouse.py` → engine);
#   2. "Penerimaan tanpa roll" (`/missing-from-receipts` + `/issue-from-receipt`);
#   3. Impor roll stok awal (`/import/*`, disetujui Keuangan lewat sesi Opname stok awal).
# Tidak ada pemanggil resmi lain (diperiksa: layar, impor stok awal, uji unit). Skrip demo/verifikasi lama yang
# masih memanggil jalur ini akan mendapat 410 dengan kalimat yang sama.
JALUR_ROLL_RESMI = (
    "Roll kain tidak bisa lagi dibuat manual: roll manual tidak menambah stok bahan dan tidak tercatat di "
    "jurnal, sehingga roll dan stok tidak cocok. Roll lahir dari tiga jalur: (1) Penerimaan Barang — isi "
    "rincian gulungan pada baris kain; (2) Roll Kain › Penerimaan tanpa roll — untuk penerimaan yang sudah "
    "lewat; (3) Impor roll stok awal — untuk kain yang sudah ada di gudang sebelum sistem dipakai.")


@router.post("")
async def create_roll(request: Request):
    """DITUTUP (410). Body sengaja tidak dibaca: isian apa pun dijawab dengan jalur resminya, bukan galat 422."""
    await require_auth(request)
    raise HTTPException(410, JALUR_ROLL_RESMI)


# ── FASE H-5: penerimaan kain yang belum punya gulungan (backfill) ───────────────
# Kenapa endpoint ini ada: kain yang sudah masuk stok tetapi tidak punya satu pun
# gulungan akan MENGHENTIKAN Portal Cutting (H-6 mewajibkan roll). Daftar ini
# membuat lubangnya kelihatan sebelum bagian potong berhenti bekerja, dan
# tombolnya menerbitkan roll untuk penerimaan yang sudah lewat.

@router.get("/number-policy")
async def roll_number_policy(request: Request):
    """Format + contoh nomor roll berikutnya (untuk petunjuk di layar)."""
    await require_auth(request)
    db = get_db()
    from core.doc_number_policy import next_preview, policy
    pol = await policy(db, fabric_roll_engine.ROLL_NUMBER_KEY)
    try:
        preview = await next_preview(db, fabric_roll_engine.ROLL_NUMBER_KEY, None)
    except Exception as e:  # noqa: BLE001 — petunjuk UI tak boleh menjatuhkan layar
        log.warning(f"roll number preview gagal: {e}")
        preview = pol.get("contoh") or ""
    return {"key": pol["key"], "label": pol["label"], "mode": pol["mode"],
            "format": pol["format"], "contoh": pol.get("contoh"), "next_number": preview}


@router.get("/missing-from-receipts")
async def missing_from_receipts(request: Request, limit: int = Query(50, ge=1, le=200)):
    """Baris penerimaan kain berstatus `received` yang belum punya gulungan."""
    await require_auth(request)
    db = get_db()
    rows = await fabric_roll_engine.receipts_missing_rolls(db, limit=limit)
    return {"items": serialize_doc(rows), "total": len(rows)}


class IssueFromReceiptIn(BaseModel):
    receipt_id: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    lines: list = Field(..., description="[{qty, color_lot, notes}] — total harus = qty diterima")


@router.post("/issue-from-receipt")
async def issue_from_receipt(data: IssueFromReceiptIn, request: Request):
    """Terbitkan gulungan untuk satu baris penerimaan yang sudah lewat (idempoten)."""
    user = await require_auth(request)
    db = get_db()
    gr = await db.warehouse_receiving.find_one({"id": data.receipt_id}, {"_id": 0})
    if not gr:
        raise HTTPException(404, "Penerimaan barang tidak ditemukan.")
    if gr.get("status") != "received":
        raise HTTPException(400, (
            f"GR {gr.get('receipt_number','')} berstatus '{gr.get('status')}'. Gulungan hanya "
            "diterbitkan untuk penerimaan yang sudah diterima — selesaikan penerimaannya dulu "
            "(rincian roll bisa diisi langsung di layar Penerimaan Barang)."))
    item = next((it for it in (gr.get("items") or []) if it.get("id") == data.item_id), None)
    if not item:
        raise HTTPException(404, "Baris penerimaan tidak ditemukan di GR tersebut.")
    already = await db.wh_fabric_rolls.count_documents({"source_receipt_item_id": data.item_id})
    if already:
        raise HTTPException(409, (
            f"Baris ini sudah punya {already} gulungan. Menerbitkan ulang akan membuat dua "
            "gulungan fisik untuk kain yang sama — dibatalkan."))
    mat = await db.rahaza_materials.find_one(
        {"id": item.get("material_id")},
        {"_id": 0, "id": 1, "code": 1, "name": 1, "unit": 1, "type": 1,
         "is_cut_panel": 1, "color": 1, "color_name": 1})
    if not mat:
        raise HTTPException(400, "Material baris penerimaan tidak ditemukan di master.")
    if not fabric_roll_engine.is_roll_material(mat):
        raise HTTPException(400, (
            f"{mat.get('code')} bersatuan '{mat.get('unit')}' tidak dilacak per gulungan."))
    accepted = float(item.get("accepted_qty") if item.get("accepted_qty") is not None
                     else max(0.0, float(item.get("received_qty", 0) or 0)
                              - float(item.get("rejected_qty", 0) or 0)))
    lines_ok = fabric_roll_engine.validate_roll_lines(
        data.lines, accepted, mat.get("unit") or "",
        f"{mat.get('code')} — {mat.get('name')}")
    made = await fabric_roll_engine.create_rolls_from_receipt(
        db, gr, item, mat, lines_ok, user)
    roll_nos = [r["roll_no"] for r in made]
    # Jejak dua arah: baris GR menyimpan gulungan yang lahir darinya.
    await db.warehouse_receiving.update_one(
        {"id": data.receipt_id, "items.id": data.item_id},
        {"$set": {
            "items.$.rolls": lines_ok,
            "items.$.roll_ids": [r["id"] for r in made],
            "items.$.roll_numbers": roll_nos,
            "updated_at": _now(),
        }},
    )
    await db.warehouse_receiving.update_one(
        {"id": data.receipt_id},
        {"$pull": {"rolls_pending": {"item_id": data.item_id}},
         "$push": {"rolls_created": {"$each": roll_nos}}},
    )
    log.info(f"H-5 backfill: {len(made)} roll terbit dari GR {gr.get('receipt_number','')} "
             f"baris {data.item_id}")
    return {"ok": True, "rolls": serialize_doc(made), "roll_numbers": roll_nos,
            "message": (f"{len(made)} gulungan diterbitkan untuk "
                        f"{mat.get('code')} — {mat.get('name')}: {', '.join(roll_nos)}")}


@router.get("/stats/summary")
async def roll_stats(request: Request):
    await require_auth(request)
    db = get_db()
    pipeline = [
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
            "total_m": {"$sum": "$remaining_m"},
            "total_kg": {"$sum": "$remaining_kg"},
        }}
    ]
    stats = await db.wh_fabric_rolls.aggregate(pipeline).to_list(20)
    return {"by_status": [{**s, "_id": s["_id"]} for s in stats]}


# ── 2026-11-09: IMPOR ROLL KAIN MASSAL (stok awal, klarifikasi owner C5) ───────────────────────────
@router.get("/import/template")
async def roll_import_template(request: Request):
    await require_auth(request)
    from io import BytesIO
    from core import fabric_roll_import as fri
    data = await fri.build_template(get_db())
    return StreamingResponse(BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="template_impor_roll_kain.xlsx"'})


async def _read_upload(request: Request) -> tuple:
    form = await request.form()
    f = form.get("file")
    if f is None or not hasattr(f, "read"):
        raise HTTPException(400, "Unggah berkas Excel (.xlsx) di isian 'file'.")
    data = await f.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "Berkas terlalu besar (maks. 10 MB).")
    return data, getattr(f, "filename", "") or ""


@router.post("/import/preview", dependencies=only(*WAREHOUSE_ROLES, perm="inv.stock.manage"))
async def roll_import_preview(request: Request):
    """Pratinjau impor roll (tidak menulis apa pun)."""
    await require_auth(request)
    from core import fabric_roll_import as fri
    data, _name = await _read_upload(request)
    return serialize_doc(await fri.parse(get_db(), data))


@router.post("/import/apply", dependencies=only(*WAREHOUSE_ROLES, perm="inv.stock.manage"))
async def roll_import_apply(request: Request):
    """Terapkan impor: roll menunggu + sesi Opname stok awal per lokasi (disetujui Keuangan/owner)."""
    user = await require_auth(request)
    from core import fabric_roll_import as fri
    data, name = await _read_upload(request)
    return serialize_doc(await fri.apply(get_db(), user, data, name))


@router.get("/imports")
async def roll_imports(request: Request, limit: int = Query(20, ge=1, le=100)):
    await require_auth(request)
    from core import fabric_roll_import as fri
    rows = await get_db()[fri.IMPORTS].find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return serialize_doc(rows)


@router.get("/by-material/{material_id}")
async def rolls_by_material(material_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    rolls = await db.wh_fabric_rolls.find({"material_id": material_id}, {"_id": 0}).sort("received_date", -1).to_list(500)
    return [serialize_doc(fabric_roll_engine.with_display_uom(r)) for r in rolls]


@router.get("/by-lot/{color_lot}")
async def rolls_by_lot(color_lot: str, request: Request):
    await require_auth(request)
    db = get_db()
    rolls = await db.wh_fabric_rolls.find({"color_lot": {"$regex": color_lot, "$options": "i"}}, {"_id": 0}).to_list(500)
    return [serialize_doc(r) for r in rolls]


@router.get("/{roll_id}")
async def get_roll(roll_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    roll = await db.wh_fabric_rolls.find_one({"$or": [{"id": roll_id}, {"roll_no": roll_id}]}, {"_id": 0})
    if not roll:
        raise HTTPException(404, "Roll tidak ditemukan")
    movements = await db.wh_fabric_roll_movements.find({"roll_id": roll["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return {**serialize_doc(fabric_roll_engine.with_display_uom(roll)),
            "movements": [serialize_doc(m) for m in movements]}


@router.put("/{roll_id}")
async def update_roll(roll_id: str, data: dict, request: Request):
    user = await require_auth(request)
    db = get_db()
    roll = await db.wh_fabric_rolls.find_one({"id": roll_id})
    if not roll:
        raise HTTPException(404, "Roll tidak ditemukan")
    allowed = {"qc_status", "notes", "color", "color_lot", "supplier_name", "unit_cost", "po_no"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "Tidak ada field yang dapat diupdate")
    updates["updated_at"] = _now()
    updates["updated_by"] = user.get("name", user["id"])
    await db.wh_fabric_rolls.update_one({"id": roll_id}, {"$set": updates})
    out = await db.wh_fabric_rolls.find_one({"id": roll_id}, {"_id": 0})
    return {"ok": True, "roll": serialize_doc(out)}


_TAK_BISA_DISIMPAN = {"rejected": "ditolak QC", "fully_issued": "sudah habis", "cancelled": "sudah dibatalkan"}


async def _posisi_dari_master(db, position_id: str, position_barcode: str) -> dict:
    """Posisi tujuan put-away HARUS dokumen `wh_positions` di rak/zona/gudang yang aktif (2026-11-10).

    Dulu `position_id`/`position_barcode` diketik bebas dan disimpan apa adanya: roll bisa "berada" di posisi
    yang tidak ada di peta gudang, dan pencarian roll per posisi tidak pernah menemukannya. Barcode dicocokkan
    lewat SSOT kode scan (`core.scan_resolver.position_by_barcode`: huruf besar/kecil & awalan scanner, label lama
    ikut dikenali) — sama dengan put-away barang, scan masuk/keluar, dan opname.
    """
    from core.scan_resolver import position_by_barcode
    pid, code = (position_id or "").strip(), (position_barcode or "").strip()
    if not pid and not code:
        raise HTTPException(400, "Pilih posisi dari daftar gudang › zona › rak › posisi, atau scan barcode posisinya.")
    if pid:
        pos = await db.wh_positions.find_one({"id": pid}, {"_id": 0})
        if not pos:
            raise HTTPException(400, "Posisi yang dipilih tidak ada di master struktur gudang (mungkin raknya sudah "
                                     "dihapus). Muat ulang, lalu pilih posisinya lagi.")
        if code:
            by_code = await position_by_barcode(db, code)
            if not by_code or by_code.get("id") != pos["id"]:
                raise HTTPException(400, f"Barcode '{code}' bukan milik posisi yang dipilih ({pos.get('barcode')}).")
    else:
        pos = await position_by_barcode(db, code)
        if not pos:
            raise HTTPException(400, f"Barcode posisi '{code}' tidak dikenal di master struktur gudang. Periksa "
                                     "labelnya, atau pilih posisi dari daftar gudang › zona › rak › posisi.")
    if pos.get("active") is False:
        raise HTTPException(400, f"Posisi {pos.get('barcode')} sudah dinonaktifkan — pilih posisi lain.")
    rak = await db.wh_racks.find_one({"id": pos.get("rack_id")}, {"_id": 0, "id": 1, "active": 1})
    if not rak or rak.get("active") is False:
        raise HTTPException(400, f"Rak posisi {pos.get('barcode')} sudah dinonaktifkan atau dihapus — pilih posisi "
                                 "di rak yang aktif.")
    for coll, key, nama in (("wh_zones", "zone_id", "Zona"), ("wh_buildings", "building_id", "Gudang")):
        induk = await db[coll].find_one({"id": pos.get(key)}, {"_id": 0, "id": 1, "active": 1}) if pos.get(key) else None
        if induk is not None and induk.get("active") is False:
            raise HTTPException(400, f"{nama} posisi {pos.get('barcode')} sudah dinonaktifkan — pilih posisi lain.")
    return pos


@router.post("/{roll_id}/putaway")
async def putaway_roll(roll_id: str, data: PutAwayIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    roll = await db.wh_fabric_rolls.find_one({"id": roll_id})
    if not roll:
        raise HTTPException(404, "Roll tidak ditemukan")
    if roll.get("status") in _TAK_BISA_DISIMPAN:
        raise HTTPException(400, f"Roll {roll.get('roll_no')} {_TAK_BISA_DISIMPAN[roll['status']]} — "
                                 "tidak bisa disimpan ke posisi.")
    pos = await _posisi_dari_master(db, data.position_id, data.position_barcode)
    barcode = pos.get("barcode") or ""   # kode baku dari master (bukan ketikan/scan mentah)
    old_pos = roll.get("position_barcode", "")
    await db.wh_fabric_rolls.update_one({"id": roll_id}, {"$set": {
        "position_id": pos["id"],
        "position_barcode": barcode,
        "updated_at": _now(),
        "updated_by": user.get("name", user["id"]),
    }})
    await _log_movement(db, roll, "putaway", 0, roll.get("uom", "meter"),
                        "manual", "", "", old_pos, barcode,
                        data.notes or f"Disimpan ke posisi {barcode}",
                        user.get("name", ""))
    return {"ok": True, "position_id": pos["id"], "position_barcode": barcode}


@router.post("/{roll_id}/issue")
async def issue_roll(roll_id: str, data: IssueIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    roll = await db.wh_fabric_rolls.find_one({"id": roll_id})
    if not roll:
        raise HTTPException(404, "Roll tidak ditemukan")
    _assert_usable(roll)
    if roll.get("status") in ("rejected", "fully_issued"):
        raise HTTPException(400, f"Roll berstatus '{roll['status']}' tidak dapat di-issue")
    # Satuan pengeluaran WAJIB satuan gulungan itu sendiri (2026-08-21).
    # Dulu embernya dipilih dari `data.unit`: gulungan YARD yang dikeluarkan
    # sebagai "meter" tetap mengurangi angka yard (label bohong), dan bila
    # pemakai memilih "kg" sistem menjawab "sisa 0" padahal gulungannya penuh.
    field = fabric_roll_engine.remaining_field(roll)
    r_uom = str(roll.get("uom") or "").strip().lower()
    d_uom = str(data.unit or "").strip().lower()
    if d_uom and r_uom and d_uom != r_uom:
        raise HTTPException(400, (
            f"Gulungan {roll.get('roll_no')} bersatuan {r_uom} — keluarkan dalam {r_uom}, "
            f"bukan {d_uom}."))
    remaining = roll.get(field, 0)
    if data.qty > remaining:
        raise HTTPException(400, f"Sisa hanya {remaining:.2f} {r_uom}. Issue {data.qty:.2f} melebihi sisa")
    new_remaining = remaining - data.qty
    new_status = _recalc_status({**roll, field: new_remaining})
    # 2026-11-06 (pola P9): sisa lama di filter — dua pengeluaran bersamaan dulu sama-sama lolos cek sisa
    # dan yang terakhir menimpa (sisa gulungan lebih besar dari kenyataan).
    res = await db.wh_fabric_rolls.update_one({"id": roll_id, field: roll.get(field), "status": roll.get("status")},
                                              {"$set": {
        field: new_remaining,
        "status": new_status,
        "updated_at": _now(),
        "updated_by": user.get("name", user["id"]),
    }})
    if not res.matched_count:
        raise HTTPException(409, "Sisa gulungan ini baru saja berubah (dikeluarkan/dikembalikan pengguna lain) — "
                                 "muat ulang lalu ulangi.")
    await _log_movement(db, roll, "issue", data.qty, r_uom or d_uom,
                        data.reference_type, data.reference_id, data.reference_no,
                        roll.get("position_barcode", ""), data.reference_no,
                        data.notes, user.get("name", ""))
    return {"ok": True, "issued_qty": data.qty, "remaining": new_remaining, "status": new_status}


@router.post("/{roll_id}/return")
async def return_roll(roll_id: str, data: ReturnIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    roll = await db.wh_fabric_rolls.find_one({"id": roll_id})
    if not roll:
        raise HTTPException(404, "Roll tidak ditemukan")
    _assert_usable(roll)
    field = "remaining_m" if data.unit == "meter" else "remaining_kg"
    new_remaining = roll.get(field, 0) + data.qty
    new_status = _recalc_status({**roll, field: new_remaining})
    res = await db.wh_fabric_rolls.update_one({"id": roll_id, field: roll.get(field), "status": roll.get("status")},
                                              {"$set": {   # 2026-11-06 (pola P9): sisa lama di filter
        field: new_remaining,
        "status": new_status,
        "updated_at": _now(),
        "updated_by": user.get("name", user["id"]),
    }})
    if not res.matched_count:
        raise HTTPException(409, "Sisa gulungan ini baru saja berubah (dikeluarkan/dikembalikan pengguna lain) — "
                                 "muat ulang lalu ulangi.")
    await _log_movement(db, roll, "return", data.qty, data.unit,
                        data.reference_type, data.reference_id, data.reference_no,
                        data.reference_no, roll.get("position_barcode", ""),
                        data.notes, user.get("name", ""))
    return {"ok": True, "returned_qty": data.qty, "remaining": new_remaining, "status": new_status}


@router.post("/{roll_id}/reject")
async def reject_roll(roll_id: str, data: RejectIn, request: Request):
    from routes.shared import require_perm
    user = await require_perm(
        request, 'warehouse.approve', 'warehouse.manage', 'inventory.manage',
        legacy_roles=('admin_gudang', 'spv_packing', 'supervisor', 'manager_produksi',
                      'supervisor_produksi', 'owner', 'admin', 'superadmin'),
        message='Akses ditolak: Anda tidak berhak menolak roll kain.')
    db = get_db()
    roll = await db.wh_fabric_rolls.find_one({"id": roll_id})
    if not roll:
        raise HTTPException(404, "Roll tidak ditemukan")
    _assert_usable(roll)
    if roll.get("status") == "rejected":
        raise HTTPException(400, "Roll sudah ditandai reject")
    await db.wh_fabric_rolls.update_one({"id": roll_id}, {"$set": {
        "status": "rejected",
        "qc_status": "reject",
        "reject_reason": data.reason,
        "claim_to_supplier": data.claim_to_supplier,
        "updated_at": _now(),
        "updated_by": user.get("name", user["id"]),
    }})
    await _log_movement(db, roll, "reject", roll.get("remaining_m", 0) or roll.get("remaining_kg", 0),
                        roll.get("uom", "meter"), "manual", "", "",
                        roll.get("position_barcode", ""), "rejected",
                        data.reason, user.get("name", ""))
    return {"ok": True, "status": "rejected", "claim": data.claim_to_supplier}


@router.post("/{roll_id}/adjust")
async def adjust_roll(roll_id: str, data: AdjustIn, request: Request):
    user = await require_auth(request)
    db = get_db()
    roll = await db.wh_fabric_rolls.find_one({"id": roll_id})
    if not roll:
        raise HTTPException(404, "Roll tidak ditemukan")
    _assert_usable(roll)
    new_m = max(0, roll.get("remaining_m", 0) + data.delta_m)
    new_kg = max(0, roll.get("remaining_kg", 0) + data.delta_kg)
    new_status = _recalc_status({**roll, "remaining_m": new_m, "remaining_kg": new_kg})
    await db.wh_fabric_rolls.update_one({"id": roll_id}, {"$set": {
        "remaining_m": new_m, "remaining_kg": new_kg, "status": new_status,
        "updated_at": _now(), "updated_by": user.get("name", user["id"]),
    }})
    qty = abs(data.delta_m) or abs(data.delta_kg)
    unit = "meter" if data.delta_m != 0 else "kg"
    await _log_movement(db, roll, "adjust", qty, unit, "manual", "", "",
                        "", "", data.reason, user.get("name", ""))
    return {"ok": True, "remaining_m": new_m, "remaining_kg": new_kg, "status": new_status}


@router.get("/{roll_id}/label-pdf")
async def roll_label_pdf(roll_id: str, request: Request, token: Optional[str] = None):
    from auth import verify_download_token
    if token:
        user = verify_download_token(token)
        if not user:
            raise HTTPException(401, "Invalid token")
    else:
        user = await require_auth(request)
    db = get_db()
    roll = await db.wh_fabric_rolls.find_one(
        {"$or": [{"id": roll_id}, {"roll_no": roll_id}]}, {"_id": 0})
    if not roll:
        raise HTTPException(404, "Roll tidak ditemukan")
    # 2026-11-02 (Paket 3a): gambar label lewat SSOT `core/label_render`
    # (Code128 vektor, quiet zone 10X) — dulu generator PNG sendiri di sini.
    # Qty dicetak sesuai satuan roll (dulu selalu "x m / y kg").
    from core import label_render as lr
    if not lr.LABELS_OK:
        raise HTTPException(500, "ReportLab tidak tersedia")
    v = fabric_roll_engine.with_display_uom(roll)
    unit = v.get("uom") or "meter"
    doc = {**v, "qty_text": f"Qty: {v['qty_total']:,.2f} {unit} · sisa {v['qty_remaining']:,.2f} {unit}"}
    try:
        buf = lr.single_label_pdf("roll", doc)
    except lr.LabelCodeError as e:
        raise HTTPException(400, str(e))
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="roll-{roll["roll_no"]}.pdf"'},
    )


@router.delete("/{roll_id}", dependencies=only(*WAREHOUSE_ROLES, perm="inv.stock.manage"))  # T-01 2.3
async def delete_roll(roll_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    roll = await db.wh_fabric_rolls.find_one({"id": roll_id})
    if not roll:
        raise HTTPException(404, "Roll tidak ditemukan")
    if roll.get("status") not in ("in_stock", "rejected"):
        raise HTTPException(400, "Hanya roll in_stock/rejected yang dapat dihapus")
    has_movements = await db.wh_fabric_roll_movements.count_documents({"roll_id": roll_id})
    if has_movements > 1:  # >1 karena ada log receive saat create
        raise HTTPException(400, "Roll sudah punya riwayat movement, tidak dapat dihapus")
    await db.wh_fabric_rolls.delete_one({"id": roll_id})
    await db.wh_fabric_roll_movements.delete_many({"roll_id": roll_id})
    return {"ok": True}
