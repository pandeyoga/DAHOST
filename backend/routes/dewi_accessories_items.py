"""
Dewi Accessories - Items
Items CRUD (SSOT: rahaza_materials)
"""
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
import re
import uuid
import logging
from datetime import datetime, timezone
from database import get_db
from core import uom  # SSOT konversi satuan (multi-UOM berjenjang)
from utils.counters import gen_prefixed_number
from auth import require_auth, serialize_doc

_log = logging.getLogger(__name__)

router = APIRouter(tags=["accessories-items"])

# ── helpers ──────────────────────────────────────────────────────────────────
def _id():    return str(uuid.uuid4())
def _now_iso(): return datetime.now(timezone.utc).isoformat()
def _now():   return datetime.now(timezone.utc)

# 2026-11-06 (Tahap 1): SATU daftar satuan — `MATERIAL_UNITS` master material (cermin FE
# `lib/uom.js`). Dulu berkas ini punya salinan sendiri dan satuan tak dikenal DIAM-DIAM
# menjadi "pcs" (form menawarkan "lembar" → tersimpan "pcs"). Sekarang ditolak dengan pesan.
from routes.rahaza_inventory_shared import MATERIAL_UNITS  # noqa: E402

# 2026-11-06 (pola P8): kamus ejaan satuan dipindah ke `core.uom.UNIT_SPELLINGS` (satu sumber).
# Dulu di sini "roll" → "rol" dan "pack" → "pak", berlawanan dengan data master material.
from core.uom import canonical_unit  # noqa: E402


HPP_EDIT_BLOCKED_MSG = (
    "Harga satuan (HPP) tidak bisa diubah dari Ubah aksesoris. Pakai Valuasi HPP › Set HPP "
    "supaya perubahan nilai stok tercatat sebagai revaluasi berjurnal beserta alasannya."
)


def _normalize_unit(unit: str) -> str:
    if not unit:
        return "pcs"
    u = canonical_unit(unit)
    if u not in MATERIAL_UNITS:
        raise HTTPException(400, f"Satuan '{unit}' tidak dikenal. Pilih salah satu: {', '.join(MATERIAL_UNITS)}.")
    return u

# Fase 2.8: helper stok aksesoris KANONIK dipindah ke core.accessory_stock
# (satukan ke rahaza_material_stock flat via stock_service; hilangkan duplikasi Schema-B nested).
from core.accessory_stock import (  # noqa: E402
    get_accessory_location_id as _get_accessory_location_id,
    stock_qty as _stock_qty,
    all_accessory_stock as _all_accessory_stock,
)

async def _log_movement(db, user: dict, *, material_id: str, mv_type: str, qty: float,
                        notes: str = "", related_ref: str = "", related_type: str = ""):
    mat = await db.rahaza_materials.find_one(
        {"id": material_id}, {"_id": 0, "id": 1, "code": 1, "name": 1, "type": 1, "unit": 1}
    )
    if not mat:
        return
    loc_id = await _get_accessory_location_id(db)
    mvdoc = {
        "id": _id(),
        "material_id": material_id,
        "material": mat,
        "movement_type": mv_type,
        "qty_signed": qty,
        "location": {"id": loc_id, "code": "ZNA-AKSESORIS", "name": "Area Aksesoris"},
        "notes": notes,
        "reference_type": related_type,
        "reference_id": related_ref,
        "created_by": user.get("id", ""),
        "created_at": _now(),
    }
    await db.rahaza_material_movements.insert_one(mvdoc)

# 2026-11-06 (pola P2): salinan `_enrich_movement` yang tidak pernah dipanggil dihapus — versi yang
# dipakai ada di routes/dewi_accessories_stock.py (dulu salinan ini membaca `dewi_asset_loans` lewat
# `related_loan_id` yang tidak pernah ditulis).

# 2026-11-06 (Tahap 2): nama kategori untuk layar — satu definisi di core.accessory_stock
from core.accessory_stock import (  # noqa: E402
    category_map as _category_map,
    category_view as _category_view,
)


def _cat_fields(cat: dict) -> dict:
    return {"category": cat["id"], "category_id": cat["id"], "category_code": cat.get("code", ""),
            "category_name": cat.get("name", "")}


async def _category_patch(db, body: dict, existing: dict | None = None) -> dict:
    """Field kategori dari isian form: `category_id` (pilihan master) atau `category` (teks/ID/kode
    lama). Kategori master → id + kode + nama; teks bebas tak dikenal → disimpan sebagai teks (lama)."""
    patch: dict = {}
    if "sub_category" in body:
        patch["sub_category"] = (body.get("sub_category") or "").strip()
    if "category_id" not in body and "category" not in body:
        return patch
    val = str(body.get("category_id") or body.get("category") or "").strip()
    if existing is not None and "category_id" not in body:
        shown, _cid = _category_view(existing, await _category_map(db))
        if val == shown:
            return patch            # form lama mengirim ulang nama yang ditampilkan — tidak berubah
    if not val:
        return patch
    cat = (await db.rahaza_material_categories.find_one({"id": val}, {"_id": 0})
           or await db.rahaza_material_categories.find_one({"code": val.upper()}, {"_id": 0})
           or await db.rahaza_material_categories.find_one(
               {"name": {"$regex": f"^{re.escape(val)}$", "$options": "i"}}, {"_id": 0}))
    if cat:
        patch.update(_cat_fields(cat))
    elif "category_id" in body:
        raise HTTPException(400, "Kategori yang dipilih tidak ada di master kategori material.")
    else:
        patch.update(category=val, category_name=val)
    return patch


def _material_to_acc_item(mat: dict, stock_qty: float = 0.0, cats: dict | None = None) -> dict:
    # Pack conversion for display
    pack_size = mat.get("pack_size", 1)
    if pack_size <= 0:
        pack_size = 1
    pack_unit = mat.get("pack_unit", "pack")
    display_in_packs = mat.get("display_in_packs", False)
    _min_stock = float(mat.get("min_stock") or 0)
    _unit_cost = float(mat.get("unit_cost") or mat.get("hpp") or 0)
    _cat_name, _cat_id = _category_view(mat, cats)

    return {
        "id": mat.get("id", ""),
        "code": mat.get("code", ""),
        "name": mat.get("name", ""),
        "description": mat.get("description", ""),
        "unit": mat.get("unit", "pcs"),
        "color": mat.get("color", ""),
        # 2026-11-06 (Tahap 2): NAMA kategori (dulu ID master mentah); id terpisah untuk form & filter
        "category": _cat_name,
        "category_id": _cat_id,
        "sub_category": mat.get("sub_category", "") or "",
        # 2026-11-07 (Tahap 5): supplier & catatan IKUT dikirim. Dulu tidak ada di respons ⇒ form Ubah
        # Aksesoris terbuka dengan supplier/catatan kosong lalu PUT menimpanya jadi "" (data hilang tiap edit).
        "supplier": mat.get("supplier", "") or "",
        # 2026-11-07 (Tahap 6 PG5): tautan Master Supplier (nama di atas tetap untuk tampilan)
        "supplier_id": mat.get("supplier_id") or "",
        "supplier_code": mat.get("supplier_code") or "",
        "notes": mat.get("notes", "") or "",
        "min_stock": mat.get("min_stock", 0),
        "max_stock": mat.get("max_stock", 0),
        "stock_qty": stock_qty,
        # REGRESI FIX: status stok hilang saat refactor (FE menampilkan semua "Habis")
        "stock_status": ("out" if stock_qty <= 0
                        else "low" if (_min_stock > 0 and stock_qty <= _min_stock)
                        else "ok"),
        # FASE G+: harga satuan (dasar valuasi & posting JE selisih opname)
        "unit_cost": float(mat.get("unit_cost") or mat.get("hpp") or 0),
        "stock_value": round(stock_qty * float(mat.get("unit_cost") or mat.get("hpp") or 0), 2),
        # NEW: Pack info
        "pack_unit": pack_unit,
        "pack_size": pack_size,
        "display_in_packs": display_in_packs,
        "stock_qty_in_packs": round(stock_qty / pack_size, 2) if pack_size > 0 else stock_qty,
        "min_stock_in_packs": round(mat.get("min_stock", 0) / pack_size, 2) if pack_size > 0 else mat.get("min_stock", 0),
        # Multi-UOM (berjenjang) — SSOT core/uom. Field lama di atas tetap ada
        # sebagai cermin supaya klien lama tidak pecah (INV-UOM-4).
        "base_uom": uom.base_uom_of(mat),
        "uoms": uom.resolve_uoms(mat),
        "purchase_uom": uom.purchase_uom_of(mat),
        "issue_uom": uom.issue_uom_of(mat),
        "display_uom": uom.display_uom_of(mat),
        "stock_display": uom.format_dual(mat, stock_qty),
        "active": mat.get("active", True),
        "tags": mat.get("tags", []),
        "created_at": mat.get("created_at", _now_iso()),
    }

@router.get("/items")
async def list_items(request: Request):
    await require_auth(request)
    db = get_db()
    sp = request.query_params
    query: dict = {"type": "accessory", "active": True}
    conds = []
    if sp.get("search"):
        rx = re.compile(re.escape(sp["search"]), re.IGNORECASE)
        conds.append({"$or": [{"name": rx}, {"code": rx}, {"category": rx}, {"category_name": rx},
                              {"sub_category": rx}]})
    if sp.get("category"):
        # 2026-11-06 (Tahap 2): filter boleh id master, nama kategori, atau teks lama
        v = sp["category"]
        conds.append({"$or": [{"category": v}, {"category_id": v}, {"category_name": v}]})
    if conds:
        query["$and"] = conds

    mats = await db.rahaza_materials.find(query, {"_id": 0}).sort("name", 1).to_list(2000)
    stock_map = await _all_accessory_stock(db)
    cats = await _category_map(db)
    items = [_material_to_acc_item(m, stock_map.get(m["id"], 0.0), cats) for m in mats]
    return serialize_doc(items)


@router.post("/items")
async def create_item(request: Request):
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name wajib diisi")

    # RC-5 fix: atomic race-safe numbering (was count_documents()+1)
    code = (body.get("code") or await gen_prefixed_number(db, "rahaza_materials", "code", "ACC-", 4)).strip().upper()

    # 2026-11-06 (pola P8): cek kode SAMA dengan master material (`rahaza_inventory_materials`):
    # kode unik di SEMUA jenis material aktif (indeks unik `code` + active). Dulu hanya sesama
    # aksesoris → kode milik kain/FG lolos cek lalu gagal di indeks sebagai galat 500.
    clash = await db.rahaza_materials.find_one({"code": code, "active": True}, {"_id": 0, "type": 1, "name": 1})
    if clash:
        raise HTTPException(409, f"Kode '{code}' sudah terpakai ({clash.get('name') or clash.get('type')}).")

    unit = _normalize_unit(body.get("unit") or "pcs")

    # Satuan & kemasan — divalidasi + dinormalkan terpusat di core/uom.
    # Mengembalikan `uoms` + cermin field lama (pack_unit/pack_size/
    # display_in_packs) sehingga kode lama tetap bekerja (INV-UOM-4).
    try:
        uom_patch = uom.apply_payload({**body, "unit": unit})
    except uom.UomError as e:
        raise HTTPException(400, f"Satuan tidak valid: {e}")

    # 2026-11-06 (Tahap 2): kategori dari master kategori material (pilihan form); teks lama tetap diterima
    cat_patch = await _category_patch(db, body)
    if "category" not in cat_patch:
        acc_cat = await db.rahaza_material_categories.find_one({"code": "ACCESSORY"}, {"_id": 0})
        cat_patch.update(_cat_fields(acc_cat) if acc_cat else {"category": "Umum"})
    # 2026-11-07 (Tahap 6 PG5): supplier ditautkan ke Master Supplier (`supplier_id`), nama dari master
    from routes.procurement_suppliers import supplier_link_patch
    sup_patch = await supplier_link_patch(db, body)
    doc = {
        "id": _id(),
        "code": code,
        "name": name,
        "type": "accessory",
        "unit": unit,
        "category": cat_patch.pop("category", "Umum"),
        **cat_patch,
        "description": body.get("description", ""),
        "min_stock": float(body.get("min_stock") or 0),
        # FASE G+: harga satuan wajib agar selisih opname bisa dinilai & posting ke keuangan
        "unit_cost": float(body.get("unit_cost") or body.get("hpp") or 0),
        "supplier": "", "supplier_id": None, "supplier_code": None,
        **sup_patch,
        "notes": body.get("notes", ""),
        # Satuan & kemasan (uoms + cermin pack_*) — SSOT di core/uom
        **uom_patch,
        "active": True,
        "created_by": user.get("name", ""),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.rahaza_materials.insert_one(doc)
    out = _material_to_acc_item(doc, 0.0)
    return JSONResponse(serialize_doc(out), status_code=201)


@router.put("/items/{item_id}")
async def update_item(item_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    body = await request.json()
    existing = await db.rahaza_materials.find_one({"id": item_id, "type": "accessory"})
    if not existing:
        raise HTTPException(404, "Aksesoris tidak ditemukan")

    upd: dict = {}
    allowed = ("name", "description", "notes")
    for k in allowed:
        if k in body:
            upd[k] = body[k]
    # 2026-11-07 (Tahap 6 PG5): supplier lewat Master Supplier (`supplier_id` divalidasi, nama dari master)
    from routes.procurement_suppliers import supplier_link_patch
    upd.update(await supplier_link_patch(db, body, existing))
    # 2026-11-06 (Tahap 2): kategori lewat master (form mengirim ulang NAMA yang ditampilkan → tidak
    # menimpa ID kategori master dengan teks)
    upd.update(await _category_patch(db, body, existing))
    if "code" in body and body["code"]:
        upd["code"] = str(body["code"]).strip().upper()
    if "unit" in body and body["unit"]:
        # satuan lama yang tidak diubah tetap boleh disimpan apa adanya
        same = str(body["unit"]).strip().lower() == str(existing.get("unit") or "").strip().lower()
        upd["unit"] = existing.get("unit") if same else _normalize_unit(body["unit"])
    if "min_stock" in body:
        try:
            upd["min_stock"] = float(body["min_stock"] or 0)
        except Exception:
            upd["min_stock"] = 0.0
    # 2026-11-06 (Tahap 1, aturan owner K12): HPP TIDAK diubah lewat "Ubah aksesoris". Dulu
    # field ini menimpa `unit_cost` langsung — tanpa jurnal, tanpa riwayat — sehingga nilai stok
    # berbeda dari buku besar. Koreksi HPP hanya lewat Valuasi HPP → Set HPP (revaluasi berjurnal
    # + alasan). Nilai yang sama (form lama mengirim ulang seluruh isian) tetap diterima.
    if "unit_cost" in body or "hpp" in body:
        raw = body.get("unit_cost") if body.get("unit_cost") not in (None, "") else body.get("hpp")
        try:
            sent = float(raw or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Harga satuan harus berupa angka.")
        from core.accessory_valuation import resolve_unit_cost
        if abs(sent - resolve_unit_cost(existing)) > 1e-6:
            raise HTTPException(400, HPP_EDIT_BLOCKED_MSG)

    # Satuan & kemasan — hanya diproses bila salah satu field satuan dikirim,
    # supaya PATCH parsial (mis. hanya ubah nama) tidak menyentuh `uoms`.
    if any(k in body for k in ("uoms", "unit", "base_uom", "pack_unit", "pack_size",
                               "display_in_packs", "purchase_uom", "issue_uom", "display_uom")):
        # 2026-11-06 (Tahap 2 Pengadaan): satuan dasar dikunci selama PO/GR/daftar harga/karantina terbuka
        from core import procurement_guards
        _nb = upd.get("unit") or body.get("base_uom") or uom.base_uom_of(existing)
        _docs = await procurement_guards.check_base_unit_change(db, existing, _nb)
        if _docs:
            raise HTTPException(409, procurement_guards.open_documents_message(existing, uom.normalize_code(_nb), _docs))
        try:
            upd.update(uom.apply_payload({**body, **({"unit": upd["unit"]} if "unit" in upd else {})},
                                         existing))
        except uom.UomError as e:
            raise HTTPException(400, f"Satuan tidak valid: {e}")
    if "deleted" in body:
        upd["active"] = not bool(body["deleted"])
    upd["updated_at"] = _now_iso()

    await db.rahaza_materials.update_one({"id": item_id}, {"$set": upd})
    result = await db.rahaza_materials.find_one({"id": item_id}, {"_id": 0})
    qty = await _stock_qty(db, item_id)
    return serialize_doc(_material_to_acc_item(result, qty, await _category_map(db)))


@router.delete("/items/{item_id}")
async def delete_item(item_id: str, request: Request, hard: bool = Query(False)):
    """Tanpa `hard`: nonaktifkan (perilaku lama). `?hard=true` (10 Nov 2026, permintaan owner): hapus permanen
    bila aksesoris BELUM dipakai — satu aturan dengan Master Item (`rahaza_inventory_materials.material_usage`:
    stok bersaldo, kartu stok, BOM, PR/PO/penerimaan, opname, dll.); bila sudah → 409 dan layar menawarkan
    Nonaktifkan. Dulu layar berjanji "ditolak bila masih berstok / di BOM" padahal server tidak memeriksa apa pun."""
    from routes.shared import require_perm
    user = await require_perm(request, 'accessories.approve', 'warehouse.manage',
                              legacy_roles=('admin_aksesoris', 'spv_aksesoris', 'admin_gudang', 'owner', 'admin', 'superadmin'),
                              message='Akses ditolak: Anda tidak berhak menonaktifkan aksesoris.')  # T-01 2.3
    db = get_db()
    if hard:
        mat = await db.rahaza_materials.find_one({"id": item_id, "type": "accessory"}, {"_id": 0})
        if not mat:
            raise HTTPException(404, "Aksesoris tidak ditemukan")
        from routes.rahaza_inventory_materials import hapus_material_permanen
        out = await hapus_material_permanen(db, mat, user or {}, "Aksesoris")
        return {"ok": True, **out}
    res = await db.rahaza_materials.update_one(
        {"id": item_id, "type": "accessory"},
        {"$set": {"active": False, "updated_at": _now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Aksesoris tidak ditemukan")
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# STOK — receive / issue / movements / overview
# ═══════════════════════════════════════════════════════════════

