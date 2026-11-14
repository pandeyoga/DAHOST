"""wms_quarantine — FASE 6 (INV-8): KARANTINA QC (barang reject) & disposisinya.

Endpoint (prefix /api/wms/quarantine):
  GET    /                        → daftar item karantina (filter status/material/source)
  GET    /summary                 → KPI (item terbuka, qty, nilai, umur tertua, per-alasan)
  GET    /location                → info lokasi karantina kanonik
  GET    /reject-categories       → kategori alasan reject (reuse standar GRN QC)
  POST   /{item_id}/release       → lepas ke lokasi storage (barang jadi tersedia lagi)
  POST   /{item_id}/return-supplier → 410 sejak 2026-11-02 (K11): pakai dokumen Retur Pembelian
  POST   /{item_id}/scrap         → buang (write-off)
  POST   /manual                  → masukkan material ke karantina secara manual (mis. temuan gudang)

ATURAN JURNAL (grounded, lihat plan.md FASE 6):
  * Reject **saat GR** ⇒ `valued=False` (AP invoice pakai net qty ⇒ belum pernah masuk
    nilai persediaan). Scrap barang belum bernilai ⇒ **TANPA JE**. `release` barang belum
    bernilai dari GR ⇒ **penerimaan susulan** (2026-11-02, K11): Dr persediaan / Cr GRNI pada
    harga GR/PO (harga potongan diketik Keuangan), bisa ditagih lewat Tagihan dari GR.
  * Reject dari **re-inspeksi pasca-terima** ⇒ `valued=True` (sudah masuk nilai).
    `scrap`/`return_supplier` ⇒ `post_inventory_adjust(−)` (`adjustment_reason='scrap'`
    → Dr Scrap Expense / Cr Inventory). `release` ⇒ tanpa JE (nilai tak berubah,
    hanya pindah lokasi).
"""
from routes.shared import lolos_centang  # 14 Nov 2026 (tahap 2): centang owner dihormati
from fastapi import APIRouter, Request, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone
import uuid
import logging

from database import get_db
from auth import require_auth, log_activity, serialize_doc
from core.authz import izin_atau_peran_lama  # 14 Nov 2026: centang owner = penentu
from core import quarantine, location_resolver
from utils.reject_reasons import normalize_reject_reasons  # FASE 19: SSOT bentuk alasan reject
from routes.rahaza_posting import post_inventory_adjust
from core import purchase_returns as pr  # 2026-11-02 (K11): penerimaan susulan & Retur Pembelian

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wms/quarantine", tags=["wms-quarantine"])

# ─────────────────────────────────────────────────────────────────────────────
# RBAC — SSOT dipindah ke `core/stock_rbac.py` (FASE 8) agar dipakai bersama
# karantina QC + scrap aksesoris. Nama lokal dipertahankan supaya tidak ada
# perubahan perilaku di file ini.
#
# Catatan historis (FASE 6.5 temuan #2): daftar role sempat diisi nama TEBAKAN
# (`gudang`, `staff_gudang`, `warehouse`, `warehouse_manager`, `manajer`,
# `keuangan`) yang TIDAK ADA di master role (koleksi `roles`, 21 entri). Karena
# `auth.check_role` mencocokkan EXACT, role gudang NYATA (`spv_packing`,
# `tim_packing`, `admin_aksesoris`) justru selalu 403. Sekarang daftar kanonik
# ada di satu tempat — lihat komentar lengkap di `core/stock_rbac.py`.
# ─────────────────────────────────────────────────────────────────────────────
from core.stock_rbac import DISPOSE_ROLES, SCRAP_ROLES  # noqa: E402


def _uid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# QTY BERNILAI (2026-11-02 — audit g.md No.20)
# Dulu `valued` adalah bendera SELURUH item: lepas 4 dari 10 reject GR (belum bernilai)
# mengkapitalisasi 4, lalu menandai ke-10-nya "bernilai". Sekarang yang dilacak adalah QTY
# (`valued_qty`). Definisinya dipindah ke SSOT `core.quarantine` (dipakai juga GR, Retur
# Pembelian, dan revaluasi HPP) — nama lama tetap tersedia di sini.
# ─────────────────────────────────────────────────────────────────────────────
from core.quarantine import split_valued, valued_remaining_of  # noqa: E402,F401
_valued_remaining = quarantine.valued_remaining


async def _get_item_or_404(db, item_id: str) -> dict:
    item = await db[quarantine.QUARANTINE_COLL].find_one({"id": item_id}, {"_id": 0})
    if not item:
        raise HTTPException(404, "Item karantina tidak ditemukan")
    return item


async def _post_je(db, *, item: dict, qty: float, direction: int, reason: str, user: dict) -> dict:
    """Buat movement `rahaza_material_movements` lalu posting JE inventory adjust.

    direction = +1 (kapitalisasi masuk nilai) atau -1 (write-off keluar nilai).
    """
    unit_cost = float(item.get("unit_cost") or 0)
    if unit_cost <= 0:
        return {"ok": False, "error": "Harga satuan (unit_cost) material = 0 — jurnal dilewati.",
                "skipped": True}
    mv = {
        "id": _uid(),
        "material_id": item["material_id"],
        "material_name": item.get("material_name", ""),
        "material_code": item.get("material_code", ""),
        "type": "adjust",
        "qty": float(qty) * (1 if direction > 0 else -1),
        "unit": item.get("unit", "pcs"),
        "unit_cost": unit_cost,
        "location_id": item.get("location_id"),
        "reference_type": "quarantine",
        "reference_id": item["id"],
        "related_type": "quarantine",
        "related_ref": item["id"],
        "adjustment_reason": reason,
        "notes": f"Karantina QC — {reason} {qty} {item.get('unit','pcs')} {item.get('material_code','')}",
        "created_by": user.get("id", ""),
        "created_by_name": user.get("name", ""),
        "created_at": _now(),
        "timestamp": _now(),
    }
    await db.rahaza_material_movements.insert_one(mv)
    mv.pop("_id", None)
    try:
        return await post_inventory_adjust(db, mv, user)
    except Exception as e:
        logger.exception("quarantine JE gagal")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────────
@router.get("")
async def list_quarantine(
    request: Request,
    status: str = Query("open", description="open | closed | all"),
    material_id: Optional[str] = None,
    source_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    needs_action: bool = Query(False, description="hanya item yang ketersediaannya BELUM terblokir"),
    legacy_returns: bool = Query(False, description="hanya item dengan retur supplier lama tanpa penyelesaian"),
):
    await require_auth(request)
    db = get_db()
    rows = await quarantine.list_items(db, status="all" if legacy_returns else status,
                                      material_id=material_id, source_id=source_id, limit=limit,
                                      needs_action=needs_action)
    # 2026-11-02 (K11): retur supplier lama (tanpa dokumen penyelesaian) ditandai; qty bernilai &
    # harga GR asal disajikan untuk tombol "Buat Retur Pembelian" / "Lepas".
    for r in rows:
        r["legacy_return_qty"] = legacy_return_qty(r)
        r["valued_remaining_qty"] = await _valued_remaining(db, r)
    if legacy_returns:
        rows = [r for r in rows if r["legacy_return_qty"] > 0]
    return serialize_doc(rows)


@router.post("/{item_id}/retry-block")
async def retry_block_item(item_id: str, request: Request):
    """Coba blokir ULANG ketersediaan item karantina yang blokirnya gagal.

    Tanpa endpoint ini, daftar "Perlu Tindakan Manual" hanya bisa memberi tahu tanpa
    bisa memperbaiki — kegagalan blokir harus dibetulkan lewat database.
    """
    user = await require_auth(request)
    if not (izin_atau_peran_lama(user, DISPOSE_ROLES) or lolos_centang(user)):
        raise HTTPException(403, "Hanya staf gudang/supervisor yang boleh memblokir ulang stok karantina")
    db = get_db()
    actor = {"id": user.get("id", ""), "name": user.get("name", ""), "email": user.get("email", "")}
    try:
        res = await quarantine.retry_block(db, item_id=item_id, actor=actor)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            409,
            f"Gagal memblokir ulang ketersediaan: {e}. Biasanya karena stok fisik di "
            f"lokasi karantina lebih kecil dari qty karantina (stok sudah dipakai jalur "
            f"lain) — perlu opname/koreksi stok dulu.")
    await log_activity(user.get("id", ""), user.get("name", ""), "quarantine_retry_block",
                       "wh_quarantine_items",
                       f"Blokir ulang ketersediaan karantina {item_id}: {res.get('diblokir')}")
    return res


@router.get("/summary")
async def quarantine_summary(request: Request):
    await require_auth(request)
    db = get_db()
    return serialize_doc(await quarantine.summary(db))


@router.get("/location")
async def quarantine_location(request: Request):
    await require_auth(request)
    db = get_db()
    info = await quarantine.get_quarantine_location_info(db)
    storage = await location_resolver.list_storage_locations(db)
    info["storage_locations"] = [s for s in storage if s.get("id") != info["id"]]
    return serialize_doc(info)


@router.get("/reject-categories")
async def reject_categories(request: Request):
    await require_auth(request)
    from routes.rahaza_grn_qc import REJECT_CATEGORIES
    return REJECT_CATEGORIES


# ─────────────────────────────────────────────────────────────────────────────
# DISPOSISI
# ─────────────────────────────────────────────────────────────────────────────
async def gr_source_of(db, item: dict) -> tuple:
    """(dokumen GR, baris GR) asal item karantina reject GR — (None, None) bila bukan dari GR."""
    src = item.get("source") or {}
    if src.get("type") not in ("goods_receipt", "grn_inspection") or not src.get("id"):
        return None, None
    gr = await db.warehouse_receiving.find_one({"id": src["id"]}, {"_id": 0})
    if not gr:
        return None, None
    line = next((li for li in gr.get("items") or [] if pr.line_id_of(li) == src.get("line_id")), None)
    if line is None:
        line = next((li for li in gr.get("items") or [] if li.get("material_id") == item.get("material_id")), None)
    return gr, line


def release_price(body_price, default_price: float, user: dict) -> float:
    """Harga lepas reject (K11): bawaan = harga GR/PO; harga potongan hanya boleh diketik Keuangan."""
    if body_price in (None, ""):
        return float(default_price or 0)
    try:
        price = float(body_price)
    except (TypeError, ValueError):
        raise HTTPException(400, "unit_price harus berupa angka.")
    if price < 0:
        raise HTTPException(400, "unit_price tidak boleh negatif.")
    if abs(price - float(default_price or 0)) > 0.005 and not pr.is_finance(user):
        raise HTTPException(403, "Harga potongan lepas reject hanya boleh diketik Keuangan "
                                 f"(harga bawaan PO/GR: {float(default_price or 0):g}).")
    return price


@router.post("/{item_id}/release")
async def release_item(item_id: str, request: Request):
    """Lepas barang karantina ke lokasi storage (mis. lolos re-inspeksi / setelah rework).
    Body: {qty?, to_location_id, notes?, unit_price?}

    2026-11-02 (K11): bagian BELUM bernilai dari reject GR = PENERIMAAN SUSULAN pada GR yang sama —
    Dr persediaan (per jenis) / Cr 2-1150 GRNI sebesar qty × harga (bawaan harga GR/PO; harga
    potongan diketik Keuangan), HPP rata-rata diperbarui, qty bisa ditagih lewat Tagihan dari GR,
    dan qty diterima PO bertambah. Dulu Dr persediaan / Cr beban pada HPP master (uji T1)."""
    user = await require_auth(request)
    if not izin_atau_peran_lama(user, DISPOSE_ROLES) and not pr.is_finance(user) and not lolos_centang(user):
        raise HTTPException(403, "Hanya staf gudang/supervisor yang boleh melepas barang karantina")
    db = get_db()
    body = await request.json() if await request.body() else {}
    item = await _get_item_or_404(db, item_id)
    if item.get("status") != "open":
        raise HTTPException(400, "Item karantina sudah ditutup")

    to_loc = body.get("to_location_id")
    if not to_loc:
        raise HTTPException(400, "to_location_id wajib diisi (lokasi tujuan penyimpanan)")
    if not await location_resolver.location_exists(db, to_loc):
        raise HTTPException(404, "Lokasi tujuan tidak ditemukan")

    actor = {"id": user.get("id", ""), "name": user.get("name", ""), "email": user.get("email", "")}
    # 2026-11-06 (Tahap 1): kunci disposisi atomik — sisa & qty bernilai dibaca ULANG setelah kunci
    token = await _claim_or_409(db, item_id, actor)
    try:
        return await _release_locked(db, user, actor, item_id, body, to_loc)
    finally:
        await quarantine.release_item_claim(db, item_id, token)


async def _claim_or_409(db, item_id: str, actor: dict) -> str:
    try:
        return await quarantine.claim_item(db, item_id, actor)
    except quarantine.ItemBusy as e:
        raise HTTPException(409, str(e))


async def _release_locked(db, user: dict, actor: dict, item_id: str, body: dict, to_loc: str) -> dict:
    item = await _get_item_or_404(db, item_id)
    if item.get("status") != "open":
        raise HTTPException(400, "Item karantina sudah ditutup")
    qty = float(body.get("qty") or item.get("remaining_qty") or 0)
    valued_before = await _valued_remaining(db, item)
    valued_part, unvalued_part = split_valued(qty, valued_before)
    gr, line = await gr_source_of(db, item) if unvalued_part > 0 else (None, None)
    price = None
    qty_before = None
    if gr is not None and line is not None:
        price = release_price(body.get("unit_price"), pr.gr_line_price(line) or item.get("unit_cost"), user)
        if price <= 0:
            raise HTTPException(400, "Harga lepas reject 0 — baris GR asal tidak berharga. Keuangan wajib "
                                     "mengetik harga (unit_price).")
        # qty bernilai SEBELUM bagian ini masuk nilai persediaan (dibaca sebelum mutasi)
        qty_before = await quarantine.valued_onhand(db, item["material_id"])
    try:
        res = await quarantine.quarantine_out(db, item=item, action=quarantine.ACTION_RELEASE,
                                             qty=qty, to_location_id=to_loc, actor=actor,
                                             notes=body.get("notes", ""),
                                             extra={"unit_price": price} if price is not None else None)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # JE: bagian BELUM bernilai → penerimaan susulan (GR) / kapitalisasi (lainnya). Bagian sudah
    # bernilai → tanpa JE (pindah lokasi). Sisa karantina TETAP belum bernilai.
    posting = {"ok": True, "skipped": True, "reason": "sudah bernilai — pindah lokasi tidak mengubah nilai"}
    late = None
    if unvalued_part > 0 and price is not None:
        late = await pr.receive_late(db, gr=gr, line=line, qty=unvalued_part, unit_price=price,
                                     location_id=to_loc, source="quarantine_release", ref_id=item_id,
                                     ref_number=f"karantina {item.get('material_code', '')}", user=user,
                                     qty_before=qty_before)
        posting = late["posting"]
    elif unvalued_part > 0:
        posting = await _post_je(db, item=item, qty=unvalued_part, direction=+1,
                                 reason="quarantine_release", user=user)
    await db[quarantine.QUARANTINE_COLL].update_one({"id": item_id}, {
        "$set": {"valued_qty": round(valued_before - valued_part, 4)},
        "$inc": {"released_capitalized_qty": unvalued_part if posting.get("ok") and unvalued_part > 0 else 0}})

    await log_activity(user.get("id", ""), user.get("name", ""), "quarantine_release",
                       "wh_quarantine_items",
                       f"Lepas {qty} {item.get('unit','')} {item.get('material_code','')} dari karantina"
                       + (f" @ {price:g} (penerimaan susulan GR {gr.get('receipt_number', '')})" if late else ""))
    return {"ok": True, "action": "release", "qty": qty, "to_location_id": to_loc,
            "remaining_qty": res["remaining_qty"], "closed": res["closed"], "posting": posting,
            "late_receipt": (late or {}).get("late_receipt"), "unit_price": price,
            "wac": (late or {}).get("wac")}


@router.post("/{item_id}/return-supplier")
async def return_to_supplier(item_id: str, request: Request):
    """DIHENTIKAN 2026-11-02 (K11): diganti dokumen Retur Pembelian (`POST /api/rahaza/purchase-returns`).

    Jalur lama mengeluarkan barang tanpa pemasok, nota, maupun cara penyelesaian, dan barang
    bernilai dijurnal sebagai beban (uji T1: 330.000). Disposisi `return_supplier` lama tetap
    terbaca di daftar karantina sebagai "Retur lama tanpa penyelesaian"."""
    await require_auth(request)
    raise HTTPException(410, "Retur supplier langsung dari karantina sudah diganti dokumen Retur Pembelian — "
                             "gunakan tombol \"Buat Retur Pembelian\" (pilih penyelesaian: tukar barang, potong "
                             "tagihan, refund, diterima dengan diskon, atau dimusnahkan).")


def legacy_return_qty(item: dict) -> float:
    """Qty disposisi `return_supplier` lama TANPA dokumen Retur Pembelian (murni). Hanya barang dari
    pemasok (GR / re-inspeksi / temuan gudang) — retur rework ke vendor CMT (permak) bukan retur pembelian."""
    if ((item.get("source") or {}).get("type") or "manual") not in ("goods_receipt", "grn_inspection", "manual"):
        return 0.0
    return round(sum(float(d.get("qty") or 0) for d in item.get("dispositions") or []
                     if isinstance(d, dict) and d.get("action") == quarantine.ACTION_RETURN
                     and not d.get("purchase_return_id")), 4)


@router.post("/{item_id}/scrap")
async def scrap_item(item_id: str, request: Request):
    """Buang barang karantina (write-off). Body: {qty?, notes?}"""
    user = await require_auth(request)
    if not (izin_atau_peran_lama(user, SCRAP_ROLES) or lolos_centang(user)):
        raise HTTPException(403, "Scrap = write-off nilai persediaan. Hanya Admin Gudang, Supervisor, "
                                 "Keuangan, atau Owner yang boleh melakukannya. Silakan ajukan ke atasan Anda.")
    db = get_db()
    body = await request.json() if await request.body() else {}
    item = await _get_item_or_404(db, item_id)
    if item.get("status") != "open":
        raise HTTPException(400, "Item karantina sudah ditutup")
    actor = {"id": user.get("id", ""), "name": user.get("name", ""), "email": user.get("email", "")}
    # 2026-11-06 (Tahap 1): kunci disposisi atomik — sisa & qty bernilai dibaca ULANG setelah kunci
    token = await _claim_or_409(db, item_id, actor)
    try:
        return await _scrap_locked(db, user, actor, item_id, body)
    finally:
        await quarantine.release_item_claim(db, item_id, token)


async def _scrap_locked(db, user: dict, actor: dict, item_id: str, body: dict) -> dict:
    item = await _get_item_or_404(db, item_id)
    if item.get("status") != "open":
        raise HTTPException(400, "Item karantina sudah ditutup")
    qty = float(body.get("qty") or item.get("remaining_qty") or 0)
    valued_before = await _valued_remaining(db, item)
    try:
        res = await quarantine.quarantine_out(db, item=item, action=quarantine.ACTION_SCRAP,
                                              qty=qty, actor=actor, notes=body.get("notes", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))

    # write-off hanya untuk bagian yang SUDAH bernilai — 2026-11-02
    valued_part, _unvalued = split_valued(qty, valued_before)
    posting = {"ok": True, "skipped": True,
               "reason": "belum pernah masuk nilai persediaan → tidak perlu write-off"}
    if valued_part > 0:
        posting = await _post_je(db, item=item, qty=valued_part, direction=-1, reason="scrap", user=user)
    await db[quarantine.QUARANTINE_COLL].update_one(
        {"id": item_id}, {"$set": {"valued_qty": round(valued_before - valued_part, 4)}})

    await log_activity(user.get("id", ""), user.get("name", ""), "quarantine_scrap",
                       "wh_quarantine_items",
                       f"Scrap {qty} {item.get('unit','')} {item.get('material_code','')}")
    return {"ok": True, "action": "scrap", "qty": qty,
            "remaining_qty": res["remaining_qty"], "closed": res["closed"], "posting": posting}


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL IN (temuan gudang: barang rusak ditemukan saat penyimpanan)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/manual")
async def manual_quarantine(request: Request):
    """Pindahkan stok yang SUDAH ada di lokasi storage ke KARANTINA.
    Body: {material_id, qty, from_location_id, reason_code?, notes?}"""
    user = await require_auth(request)
    if not (izin_atau_peran_lama(user, DISPOSE_ROLES) or lolos_centang(user)):
        raise HTTPException(403, "Hanya staf gudang/supervisor yang boleh mengarantina stok")
    db = get_db()
    body = await request.json()
    material_id = body.get("material_id")
    qty = float(body.get("qty") or 0)
    from_loc = body.get("from_location_id")
    if not material_id or qty <= 0 or not from_loc:
        raise HTTPException(400, "material_id, qty (>0) dan from_location_id wajib diisi")

    actor = {"id": user.get("id", ""), "name": user.get("name", ""), "email": user.get("email", "")}
    # Alasan bisa datang dalam 2 bentuk:
    #   * `reason_code` (dipakai FE ManualModal — 1 alasan untuk seluruh qty)
    #   * `reject_reasons` [{code, qty, notes}] (dipakai integrasi/script & jalur GR)
    # Terima keduanya supaya alasan tidak pernah hilang (dulu array diabaikan → alasan
    # tampil "-" di UI dan masuk bucket "OTHER" di ringkasan).
    # FASE 19: pembersihan ad-hoc di sini DIGANTI SSOT `utils/reject_reasons.py`
    # (dulu dua penulis punya aturan berbeda — itu akar 500 di ringkasan karantina).
    reasons = normalize_reject_reasons(body.get("reject_reasons"), default_qty=qty)
    if not reasons and body.get("reason_code"):
        reasons = normalize_reject_reasons(
            [{"code": body["reason_code"], "qty": qty, "notes": body.get("notes", "")}],
            default_qty=qty)
    try:
        doc = await quarantine.quarantine_in(
            db, material_id=material_id, qty=qty,
            # JANGAN paksa 'pcs': bila FE tak kirim unit, pakai satuan master material
            # (kain 'm' pernah tampil sebagai 'pcs' karena default hardcoded).
            unit=body.get("unit") or None,
            source={"type": "manual", "id": "", "number": "", "supplier_name": "", "po_number": ""},
            reject_reasons=reasons,
            # stok yang dipindah dari storage SUDAH masuk nilai persediaan
            valued=True, notes=body.get("notes", ""), actor=actor, from_location_id=from_loc)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Gagal mengarantina: {e}")

    await log_activity(user.get("id", ""), user.get("name", ""), "quarantine_manual_in",
                       "wh_quarantine_items",
                       f"Karantina manual {qty} {doc.get('material_code','')}")
    return serialize_doc(doc)
