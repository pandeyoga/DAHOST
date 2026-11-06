"""
warehouse.py — Legacy Warehouse Module (di-include via server.py, bridge /api/wms/legacy/*).

STATUS (FASE F, 2026-07-25): masih LIVE untuk beberapa handler yang di-bridge
`wms_legacy.py`, TETAPI seluruh ketergantungan ke ledger legacy sudah DIPUTUS:
  - LIVE (dipakai UI via /api/wms/legacy/*):
      * /locations (GET) → KANONIK (FASE F+): `location_resolver.list_storage_locations` (wh_zones +
        rahaza storage) + `wh_positions`. create/update/delete_location → 410 (SSOT = Struktur Gudang).
        `warehouse_locations` legacy DI-RETIRE (dropdown ReceivingModule pindah ke /api/rahaza/storage-locations).
      * /receiving[/{id}] (GR, 3-way match, QC) → koleksi `warehouse_receiving` (DIPERTAHANKAN).
      * /dashboard-kpi, /dashboard, /stock, /stock/summary, /movements → kini baca KANONIK
        (`rahaza_material_stock` + `rahaza_stock_ledger`), BUKAN `warehouse_stock`/`warehouse_movements`.
  - DIHAPUS (FASE F): endpoint legacy `/putaway` (transfer) & `/opname` (variance) — penulis
    ledger ganda `warehouse_stock`/`warehouse_movements` (INV-11). Kanonik = wms_putaway.py + wms_opname3.py.
  - Koleksi `warehouse_stock`/`warehouse_movements`/`warehouse_putaway`/`warehouse_opname` kini
    TANPA writer/reader → DROP via scripts/migrate_drop_warehouse_ledger_legacy.py.
  - Inbound GR menambah stok via `core.stock_service.add` (FASE E2) + `_record_material_movement`.

JANGAN tambah tulisan stok tersebar di sini — pakai `core/stock_service`.
"""
# ruff: noqa: ERA001
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc, log_activity
from utils.counters import gen_prefixed_number
from core import stock_service  # FASE E2: satu pintu inbound (add) + ledger kanonik
from core import location_resolver  # FASE F+: master lokasi KANONIK (wh_zones + rahaza storage)
from core import quarantine  # FASE 6 (INV-8): qty reject GR → lokasi KARANTINA (blocked)
from core import fabric_roll_engine  # FASE H-5: roll kain LAHIR dari penerimaan (nomor otomatis)
from core import accessory_valuation  # 2026-08-21: HPP terbentuk dari HARGA PEMBELIAN (WAC)
from core.purchase_returns import gr_line_price  # 2026-11-02 (K11): satu definisi harga baris GR
from core.purchase_returns import is_finance  # 2026-11-06 (Tahap 2): harga GR tanpa PO hanya Keuangan
from core import procurement_guards as pguard  # 2026-11-06 (Tahap 2): satuan & harga baris GR satu pintu
from core import purchase_costing  # 2026-11-06 (Tahap 2): jurnal koreksi stok bernilai 0 (butir 7)
from datetime import datetime, timezone
import uuid
import logging
import re
from core.authz import only  # T-01 2.3
from core.roles import WAREHOUSE_ROLES  # T-01 2.3

logger = logging.getLogger(__name__)

# ⚠️  DEPRECATION NOTICE (Phase 3 — Dual API Conflict Resolution)
# This router is preserved for backward-compatibility only.
# All NEW frontend code MUST call the canonical mirror at /api/wms/legacy/*
# (see routes/wms_legacy.py — same handlers, same DB collections).
# Frontend migration completed for: LocationsModule, PutAwayModule,
# OpnameModule, ReceivingModule, WarehouseDashboard, MaklonMaterialIssuePanel.
# Once external clients (if any) finish migration, this entire file can
# be safely removed.
router = APIRouter(prefix="/api/warehouse", tags=["warehouse-legacy-deprecated"])


def new_id(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)


# 2026-11-06 (Tahap 1): status sementara selama GR dikonfirmasi. Klaim atomik draft → processing
# SEBELUM stok/jurnal disentuh, supaya klik ganda / dua pengguna tidak menambah stok dua kali.
GR_CLAIM_STATUS = "processing"


def _line_label(it: dict) -> str:
    return it.get("sku") or it.get("product_name") or it.get("material_name") or "?"


def _validate_line_qty(items: list) -> None:
    """Qty baris GR harus angka ≥ 0 dan qty ditolak ≤ qty diterima; `accepted_qty` dihitung ulang
    (dulu nilai lama yang tersimpan dipakai validasi gulungan walau qty sudah diubah)."""
    bad = []
    for it in items:
        try:
            rq = float(it.get("received_qty") or 0)
            rj = float(it.get("rejected_qty") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Qty baris {_line_label(it)} harus berupa angka.")
        if rq < 0 or rj < 0:
            raise HTTPException(400, f"Qty baris {_line_label(it)} tidak boleh negatif.")
        if rj - rq > 1e-9:
            bad.append(f"{_line_label(it)} (ditolak {rj:g} > diterima {rq:g})")
        it["accepted_qty"] = round(max(0.0, rq - rj), 4)
    if bad:
        raise HTTPException(400, "Qty ditolak tidak boleh melebihi qty diterima: " + "; ".join(bad[:10]) + ".")


# ── Sprint 1.1: Sync bridge helper ────────────────────────────────────────────
# FASE F (2026-07-25): helper `_sync_to_material_stock` DIHAPUS.
# Satu-satunya penulis stok kini `core/stock_service`. Endpoint legacy
# putaway-transfer & opname-variance yang memakainya juga DIHAPUS di bawah.


async def _record_material_movement(db, material_id: str, location_id: str, location_name: str,
                                     qty: float, unit: str, reference_type: str,
                                     reference_id: str, reference_number: str,
                                     notes: str, user: dict, unit_cost: float = 0.0,
                                     material_name: str = None) -> dict:
    """Record a rahaza_material_movement for audit trail + stock module."""
    doc = {
        "id": new_id(),
        "material_id": material_id,
        "material_name": material_name,
        "unit_cost": float(unit_cost or 0),
        "location_id": location_id,
        "location_name": location_name,
        "type": "receive",
        "qty": float(qty),
        "unit": unit,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "reference_number": reference_number,
        "notes": notes,
        "created_by": user["id"],
        "created_by_name": user.get("name", "-"),
        "created_at": now(),
    }
    await db.rahaza_material_movements.insert_one(dict(doc))
    return doc


async def _normalize_gr_lines(db, user: dict, po_id, items: list, stored_items: list | None = None) -> list:
    """2026-11-06 (Tahap 2): aturan baris GR satu pintu (`core.procurement_guards.normalize_gr_items`).

    Baris ber-PO SELALU memakai harga baris PO (dulu harga PO hanya mengisi baris kosong — penerima bisa
    mengetik harga lain); baris tanpa PO hanya Keuangan yang boleh memberi harga; satuan dikonversi ke
    satuan dasar. Return label baris yang menunggu harga Keuangan. Mengubah `items`."""
    po = await db.rahaza_purchase_orders.find_one({"id": po_id}, {"_id": 0}) if po_id else None
    try:
        return await pguard.normalize_gr_items(db, items, po_doc=po or ({"items": []} if po_id else None),
                                               finance=is_finance(user), stored_items=stored_items)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Locations / Bin ───────────────────────────────────────────────────────────

@router.get("/locations")
async def get_locations(request: Request):
    """FASE F+ (2026-07-25): master lokasi KANONIK. Sumber SSOT:
    `location_resolver.list_storage_locations` (wh_zones + rahaza storage) + `wh_positions` (bin).
    TIDAK lagi baca `warehouse_locations` (di-drop). Konsumen UI (ReceivingModule) kini pakai
    /api/rahaza/storage-locations langsung; endpoint ini shim kompat via bridge."""
    await require_auth(request)
    db = get_db()
    canonical = await location_resolver.list_storage_locations(db)
    for loc in canonical:
        loc.setdefault("source", "rahaza_location")
    positions = await db.wh_positions.find({}, {"_id": 0}).sort(
        [("building_code", 1), ("zone_code", 1), ("rack_code", 1), ("shelf_no", 1), ("slot_no", 1)]
    ).to_list(1000)
    mapped = []
    for p in positions:
        path = "/".join([str(p.get(k, "")) for k in ("building_code", "zone_code", "rack_code") if p.get(k)])
        mapped.append({
            "id": p.get("id"),
            "code": p.get("barcode") or p.get("label") or path,
            "name": p.get("label") or path or p.get("barcode", ""),
            "type": "position",
            "zone": p.get("zone_code", ""),
            "aisle": p.get("rack_code", ""),
            "bay": str(p.get("shelf_no", "")),
            "level": str(p.get("slot_no", "")),
            "capacity": 0,
            "active": p.get("status") != "inactive",
            "source": "wh_positions",
            "status": p.get("status", ""),
        })
    return serialize_doc(canonical + mapped)


_LOC_DEPRECATED = (
    "Endpoint dihapus (FASE F+, 2026-07-25). Kelola lokasi via Struktur Gudang "
    "(SSOT: wh_buildings/wh_zones/wh_racks) atau master rahaza_locations. "
    "`warehouse_locations` legacy sudah di-retire."
)


@router.post("/locations")
async def create_location(request: Request):
    """DEPRECATED (FASE F+) — 410. SSOT lokasi = Struktur Gudang / rahaza_locations."""
    await require_auth(request)
    raise HTTPException(410, _LOC_DEPRECATED)


@router.put("/locations/{location_id}")
async def update_location(location_id: str, request: Request):
    """DEPRECATED (FASE F+) — 410. SSOT lokasi = Struktur Gudang / rahaza_locations."""
    await require_auth(request)
    raise HTTPException(410, _LOC_DEPRECATED)


@router.delete("/locations/{location_id}", dependencies=only(*WAREHOUSE_ROLES))  # T-01 2.3
async def delete_location(location_id: str, request: Request):
    """DEPRECATED (FASE F+) — 410. SSOT lokasi = Struktur Gudang / rahaza_locations."""
    await require_auth(request)
    raise HTTPException(410, _LOC_DEPRECATED)


# ── Goods Receiving ─────────────────────────────────────────────────────────

@router.get("/receiving")
async def get_receiving(request: Request):
    await require_auth(request)
    db = get_db()
    receipts = await db.warehouse_receiving.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return serialize_doc(receipts)


@router.get("/receiving/{receipt_id}")
async def get_receipt(receipt_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    receipt = await db.warehouse_receiving.find_one({"id": receipt_id}, {"_id": 0})
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    return serialize_doc(receipt)


@router.post("/receiving")
async def create_receiving(request: Request):
    user = await require_auth(request)
    body = await request.json()
    db = get_db()

    # 2026-11-07 (Tahap 6, keputusan owner PG3): GR manual BARU hanya dari pemasok. Sumber "Produksi" /
    # "Pindahan gudang" dengan asal barang yang diketik ditolak — pindahan stok lewat menu Transfer. GR lama
    # bersumber itu tetap bisa dibuka & dikonfirmasi (PUT tidak memeriksa sumber).
    src_err = pguard.manual_gr_source_error(body.get("source_type"))
    if src_err:
        raise HTTPException(400, src_err)
    # PG1: barang jadi tidak dibeli → tidak ada di daftar Penerimaan Barang (layar memuat exclude_type=fg)
    _mids = list({it.get("material_id") for it in (body.get("items") or [])
                  if isinstance(it, dict) and it.get("material_id")})
    if _mids:
        fg_err = pguard.finished_goods_error(
            await db.rahaza_materials.find({"id": {"$in": _mids}}, {"_id": 0, "id": 1, "code": 1, "name": 1, "type": 1})
            .to_list(len(_mids) + 5), "Penerimaan Barang")
        if fg_err:
            raise HTTPException(400, fg_err)

    # 2026-11-06 (Tahap 1): SATU pencacah nomor GR. Dulu layar ini memakai pencacah `gr_number`
    # sedangkan "Buat GR dari PO" memakai `gen_prefixed_number` — dua deret pada satu index unik
    # `receipt_number` ⇒ cepat atau lambat bertabrakan (HTTP 500). Kanonik = gen_prefixed_number
    # (kunci `warehouse_receiving.receipt_number`, format bisa diatur owner, menyembuhkan diri).
    receipt_number = await gen_prefixed_number(db, "warehouse_receiving", "receipt_number", "GR-", 5)
    
    # Sprint 2.1: PO reference for 3-way matching (optional but recommended)
    po_id = body.get("po_id") or None
    po_number = body.get("po_number") or ""
    
    receipt = {
        "id": new_id(),
        "receipt_number": receipt_number,
        "source_type": body.get("source_type", "supplier"),
        "source_ref": body.get("source_ref", ""),
        "supplier_name": body.get("supplier_name", ""),
        "location_id": body.get("location_id", ""),
        "location_name": body.get("location_name", ""),
        "status": "draft",
        "items": [],
        "notes": body.get("notes", ""),
        "received_by": user["name"],
        "received_by_id": user["id"],
        # Sprint 2.1: Link to Purchase Order
        "po_id": po_id,
        "po_number": po_number,
        "created_at": now(),
        "updated_at": now(),
    }
    
    for item in body.get("items", []):
        # BUG-guard (numeric bounds): reject negative qty/harga in receiving items.
        try:
            expected_qty = float(item.get("expected_qty", 0) or 0)
            received_qty = float(item.get("received_qty", item.get("qty", item.get("quantity", 0))) or 0)
            rejected_qty = float(item.get("rejected_qty", 0) or 0)
            unit_price = float(item.get("unit_price", item.get("unit_cost", 0)) or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "qty/harga item penerimaan harus berupa angka.")
        if min(expected_qty, received_qty, rejected_qty, unit_price) < 0:
            raise HTTPException(400, "qty/harga item penerimaan tidak boleh negatif.")
        if rejected_qty - received_qty > 1e-9:
            raise HTTPException(400, f"Qty ditolak tidak boleh melebihi qty diterima ({_line_label(item)}: "
                                     f"ditolak {rejected_qty:g} > diterima {received_qty:g}).")
        receipt_item = {
            "id": new_id(),
            "product_name": item.get("product_name", ""),
            "sku": item.get("sku", ""),
            # Sprint 1.1: material_id links to rahaza_materials for sync bridge
            "material_id": item.get("material_id") or None,
            # 2026-11-02 (K11): tautan baris PO (harga PO, 3-way match per baris, Retur Pembelian)
            "po_item_id": item.get("po_item_id") or None,
            "material_name": item.get("material_name") or item.get("product_name", ""),
            "expected_qty": expected_qty,
            "received_qty": received_qty,
            "rejected_qty": rejected_qty,
            "unit": item.get("unit", "pcs"),
            "inspection_status": item.get("inspection_status") or "pending",
            "inspection_notes": item.get("inspection_notes") or "",
            # FASE 6 (INV-8): alasan reject WAJIB ikut tersimpan — dipakai karantina QC
            # (ringkasan per-alasan & tindak lanjut retur/scrap). Sebelumnya hilang.
            "reject_reasons": item.get("reject_reasons") or [],
            # 2026-11-06 (Tahap 1): selalu turunan (diterima − ditolak), bukan angka kiriman klien
            "accepted_qty": round(max(0.0, received_qty - rejected_qty), 4),
            "lot_number": item.get("lot_number") or "",
            "expiry_date": item.get("expiry_date") or None,
            # ── FASE H-5: rincian gulungan per baris kain ────────────────────────
            # Disimpan APA ADANYA di draft (belum divalidasi) — pemeriksaan ketat
            # "total roll = qty diterima" dilakukan saat GR di-set 'received', karena
            # qty diterima masih bisa berubah selama masih draft/inspeksi.
            "rolls": [
                {
                    "qty": float(ln.get("qty") or 0),
                    "color_lot": str(ln.get("color_lot") or "").strip(),
                    "notes": str(ln.get("notes") or "").strip(),
                }
                for ln in (item.get("rolls") or []) if isinstance(ln, dict)
            ],
            # Phase 8A: Asset vs Material differentiation
            "item_type": item.get("item_type", "material"),  # "material" or "asset"
            "unit_price": unit_price,  # For asset capitalization
            "asset_category": item.get("asset_category") or None,  # For auto-create fixed asset
        }
        receipt["items"].append(receipt_item)

    # 2026-11-06 (Tahap 2): satuan → satuan dasar; harga dari PO / hanya Keuangan (tanpa PO)
    receipt.update(pguard.price_status_fields(await _normalize_gr_lines(db, user, po_id, receipt["items"])))
    await db.warehouse_receiving.insert_one(receipt)
    await log_activity(user["id"], user["name"], "create", "warehouse_receiving", f"Created GR {receipt_number}")
    return serialize_doc(receipt)


@router.put("/receiving/{receipt_id}")
async def update_receiving(receipt_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    
    existing = await db.warehouse_receiving.find_one({"id": receipt_id})
    if not existing:
        raise HTTPException(404, "Receipt not found")
    
    body = await request.json()
    updates = {}

    # 2026-11-06 (Tahap 1): GR yang sedang dikonfirmasi tidak boleh diubah, dan konfirmasi kedua
    # (klik ganda / dua pengguna) atas GR yang sudah diterima ditolak — bukan diproses ulang.
    if existing.get("status") == GR_CLAIM_STATUS:
        raise HTTPException(409, f"Penerimaan {existing.get('receipt_number') or ''} sedang dikonfirmasi "
                                 "pengguna lain. Tunggu sebentar lalu muat ulang.")
    if existing.get("status") == "received" and body.get("status") == "received":
        raise HTTPException(409, f"Penerimaan {existing.get('receipt_number') or ''} sudah dikonfirmasi — "
                                 "stok dan jurnalnya sudah tercatat. Muat ulang daftar penerimaan.")

    # 2026-11-02 (audit No.44b): GR 'received' sudah menambah stok, jurnal persediaan, aset tetap &
    # qty diterima PO. Mundur ke draft/inspecting lalu 'received' lagi menggandakan semuanya
    # (uji: stok 5→10, jurnal & aset dobel). Koreksi lewat retur ke pemasok / penyesuaian stok.
    if existing.get("status") == "received" and "status" in body and body.get("status") != "received":
        raise HTTPException(
            400, f"GR {existing.get('receipt_number') or receipt_id} sudah diterima (received); status "
                 f"tidak bisa dikembalikan ke '{body.get('status')}'. Koreksi lewat retur ke pemasok "
                 f"atau penyesuaian stok.")

    if "status" in body:
        updates["status"] = body["status"]
    if "items" in body:
        # 2026-11-06 (Tahap 2): PUT mengganti baris SELURUHNYA — harga penerima tidak boleh ikut masuk.
        # Baris ber-PO = harga PO; tanpa PO = hanya Keuangan; satuan dikonversi ke satuan dasar.
        body["items"] = list(body.get("items") or [])
        updates.update(pguard.price_status_fields(await _normalize_gr_lines(
            db, user, existing.get("po_id"), body["items"], stored_items=existing.get("items"))))
        updates["items"] = body["items"]
    if "notes" in body:
        updates["notes"] = body["notes"]
    # 2026-08-19 — LOKASI TUJUAN boleh ditetapkan saat KONFIRMASI. GR yang lahir
    # dari PO dibuat tanpa lokasi (`location_id: ""`), dan lokasi fisiknya baru
    # diketahui ketika barangnya benar-benar diletakkan. Tanpa ini, stok masuk ke
    # baris berlokasi KOSONG: ada di sistem, tidak ada di rak mana pun, dan
    # Put-Away tidak bisa menemukannya.
    if body.get("location_id"):
        updates["location_id"] = body["location_id"]
        if body.get("location_name"):
            updates["location_name"] = body["location_name"]
    updates["updated_at"] = now()
    
    # ── Sprint 1.1: Dual-ledger sync bridge ────────────────────────────────
    # When transitioning to 'received', update BOTH ledgers:
    #   1. warehouse_stock (bin-level, used by put-away / dashboard)
    #   2. rahaza_material_stock (material-level, used by Material Issue / BOM)
    if body.get("status") == "received" and existing.get("status") != "received":
        items_to_process = body.get("items") or existing.get("items", [])
        loc_name = body.get("location_name") or existing.get("location_name", "")
        loc_id   = body.get("location_id") or existing.get("location_id", "")

        # ── PENJAGA (2026-08-19) — PENERIMAAN KOSONG DITOLAK ────────────────
        # Cacat yang dilaporkan pemilik & terbukti pada GR-00001: `expected_qty=100`
        # tetapi `received_qty=0` walau status sudah `received`. GR yang lahir dari
        # PO selalu dibuat `received_qty=0.0` (benar — barangnya belum dihitung),
        # dan dulu layar detail hanya MENAMPILKAN angka itu tanpa kolom isian, jadi
        # satu-satunya tindakan yang tersedia adalah mengkonfirmasi NOL. Hasilnya
        # penerimaan tercatat "received", PO ikut terhitung, tetapi stok TIDAK
        # bertambah sedikit pun — pembelian mustahil menambah barang.
        #
        # Kolomnya sudah dipasang di layar; penjaga ini menutup pintu yang sama di
        # tingkat API supaya integrasi/skrip pun tidak bisa membuat penerimaan hampa.
        # 2026-11-06 (Tahap 1): ditolak ≤ diterima, accepted_qty dihitung ulang (dipakai validasi roll)
        _validate_line_qty(items_to_process)
        _touched = sum(float(it.get("received_qty") or 0) + float(it.get("rejected_qty") or 0)
                       for it in items_to_process)
        if _touched <= 0:
            raise HTTPException(
                400,
                "Qty diterima masih 0 — penerimaan kosong ditolak. Isi 'Qty Diterima' "
                "pada tiap baris (atau tekan \"Terima semua sesuai PO\") sebelum "
                "dikonfirmasi. Mengkonfirmasi 0 akan mencatat penerimaan tanpa "
                "menambah stok sama sekali.",
            )

        # ── PENJAGA LOKASI (2026-08-19) ─────────────────────────────────────
        # GR dari PO lahir tanpa `location_id`. Kalau dikonfirmasi begitu saja,
        # stok mendarat di baris berlokasi KOSONG: barangnya ada di sistem tetapi
        # tidak ada di rak mana pun, sehingga Put-Away & pencarian posisi tidak
        # bisa menemukannya. Ditegakkan di API (bukan hanya di layar) karena
        # integrasi/skrip memakai pintu yang sama — dan itulah yang terbukti
        # terjadi: satu penerimaan uji lolos lewat API tanpa lokasi.
        if not loc_id:
            raise HTTPException(
                400,
                "Lokasi tujuan belum dipilih — penerimaan ditolak. Kirim "
                "`location_id` (atau pilih 'Lokasi Tujuan' di layar) supaya stok "
                "yang masuk mendarat di rak yang jelas.",
            )

        # ── 2026-11-06 (Tahap 1): BARIS TANPA TAUTAN MASTER ITEM DITOLAK ──────────
        # Dulu baris tanpa `material_id` dilewati diam-diam: GR tercatat 'received', tetapi qty-nya
        # tidak masuk stok maupun jurnal (lalu bisa ditagih ke GRNI yang tidak pernah dikredit).
        # Baris aset tetap (item_type='asset') dikapitalisasi lewat registri aset, jadi dikecualikan.
        unlinked = [_line_label(it) for it in items_to_process
                    if not it.get("material_id") and (it.get("item_type") or "material") != "asset"
                    and (float(it.get("received_qty") or 0) > 0 or float(it.get("rejected_qty") or 0) > 0)]
        if unlinked:
            raise HTTPException(
                400,
                "Baris berikut belum tertaut ke Master Item sehingga tidak bisa masuk stok: "
                + ", ".join(unlinked[:10]) + ". Tautkan barisnya ke Master Item (atau tandai sebagai "
                "aset) sebelum penerimaan dikonfirmasi.")

        # ── 2026-11-06 (Tahap 1): PO YANG SUDAH DIBATALKAN TIDAK BISA DITERIMA ────
        po_doc = None
        if existing.get("po_id"):
            po_doc = await db.rahaza_purchase_orders.find_one({"id": existing["po_id"]}, {"_id": 0})
            if po_doc and po_doc.get("status") == "cancelled":
                raise HTTPException(
                    400,
                    f"PO {po_doc.get('po_number') or existing.get('po_number') or ''} sudah dibatalkan — "
                    "penerimaan ini tidak bisa dikonfirmasi. Hapus draf penerimaan ini, atau minta "
                    "Pengadaan membuat PO baru.")

        # ── HARGA WAJIB (2026-11-02, K11 — owner: penerimaan tanpa PO BOLEH, harga WAJIB) ──
        # GR TANPA PO wajib berharga: dulu form manual tanpa kolom harga → persediaan Rp 0 di GL, HPP
        # tidak bergerak, dan faktur yang datang masuk beban umum.
        # 2026-11-06 (Tahap 2, keputusan owner): baris ber-PO SELALU = harga baris PO (penerima tidak bisa
        # mengubahnya; harga PO hanya diubah Keuangan). GR tanpa PO: hanya Keuangan yang memberi harga —
        # selama belum ada, GR "menunggu harga dari Keuangan" dan tidak bisa dikonfirmasi.
        if "items" not in body:
            await _normalize_gr_lines(db, user, existing.get("po_id"), items_to_process,
                                      stored_items=existing.get("items"))
        no_price = [pguard.line_label(it) for it in items_to_process
                    if (it.get("material_id") or (it.get("item_type") or "material") == "asset")
                    and float(it.get("received_qty") or 0) > 0 and gr_line_price(it) <= 0]
        if no_price:
            if existing.get("po_id"):
                raise HTTPException(
                    400,
                    f"Harga baris PO {existing.get('po_number') or ''} masih 0 untuk: " + ", ".join(no_price[:5])
                    + f" — penerimaan ini {pguard.PRICE_PENDING_NOTE}. Penerima tidak bisa mengisi harga; "
                    "Keuangan mengubah harga baris PO lebih dulu (Purchase Order → Ubah harga).")
            raise HTTPException(
                400,
                "Harga satuan wajib diisi Keuangan untuk penerimaan tanpa PO — penerimaan ini "
                f"{pguard.PRICE_PENDING_NOTE}. Baris tanpa harga: " + ", ".join(no_price[:5])
                + ". Harga ini menjadi nilai persediaan, HPP rata-rata, dan dasar tagihan pemasok.")

        # ── P1.C: Anti over-receive validation ─────────────────────────────
        # Jika GR linked ke PO dan enforce_po_qty=True, validasi bahwa net_qty
        # (received - rejected) untuk tiap material_id tidak melebihi qty
        # remaining di PO.
        po_id_link = existing.get("po_id")
        enforce_po = bool(existing.get("enforce_po_qty", bool(po_id_link)))
        if po_id_link and enforce_po:
            if po_doc:
                # 2026-11-06 (Tahap 1): sisa PO dicocokkan PER BARIS PO (`po_item_id`). Dulu hanya per
                # material, sehingga material sama di dua baris PO bisa melebihi satu baris dan menutupi
                # baris lainnya. Baris GR lama tanpa `po_item_id` tetap diperiksa per material.
                remaining_map: dict = {}
                remaining_by_line: dict = {}
                for po_it in (po_doc.get("items") or []):
                    remaining = max(
                        0.0,
                        float(po_it.get("qty_ordered") or 0) - float(po_it.get("qty_received") or 0),
                    )
                    if po_it.get("id"):
                        remaining_by_line[po_it["id"]] = remaining
                    mid = po_it.get("material_id")
                    if mid:
                        remaining_map[mid] = remaining_map.get(mid, 0.0) + remaining

                net_per_material: dict = {}
                net_per_line: dict = {}
                line_mid: dict = {}
                for it in items_to_process:
                    mid = it.get("material_id")
                    net = float(it.get("received_qty", 0)) - float(it.get("rejected_qty", 0))
                    if net <= 0:
                        continue
                    pid = it.get("po_item_id")
                    if pid and pid in remaining_by_line:
                        net_per_line[pid] = net_per_line.get(pid, 0.0) + net
                        line_mid[pid] = mid
                    if mid:
                        net_per_material[mid] = net_per_material.get(mid, 0.0) + net

                async def _over(mid, net, remaining):
                    mat = await db.rahaza_materials.find_one({"id": mid}, {"_id": 0, "name": 1, "code": 1}) \
                        if mid else None
                    nm = (mat and (mat.get("name") or mat.get("code"))) or mid or "baris PO"
                    raise HTTPException(
                        400,
                        f"Penerimaan melebihi sisa PO ditolak untuk {nm}: qty bersih {net:g} melebihi sisa "
                        f"PO {remaining:g} (PO {existing.get('po_number')}).",
                    )

                for pid, net in net_per_line.items():
                    if net - remaining_by_line[pid] > 0.0001:
                        await _over(line_mid.get(pid), net, remaining_by_line[pid])
                for mid, net in net_per_material.items():
                    remaining = remaining_map.get(mid, 0.0)
                    if net - remaining > 0.0001:  # small epsilon for float
                        await _over(mid, net, remaining)
        
        # ── FASE E2: INBOUND TUNGGAL VIA stock_service ─────────────────────
        # Dokumen GR tetap SATU-SATUNYA pintu inbound (PO→GR, QC, lot/expiry,
        # 3-way matching). Penambahan stok DIALIRKAN lewat `stock_service.add`
        # (satu pintu kanonik → `rahaza_material_stock` + ledger `rahaza_stock_ledger`).
        #
        # Ledger ganda `warehouse_stock` + `warehouse_movements` TIDAK ditulis lagi
        # (sumber duplikasi INV-11). Reader legacy yang masih baca `warehouse_stock`
        # akan dimigrasi/dihapus di Fase F. Movement kanonik tetap dicatat di
        # `rahaza_material_movements` (via `_record_material_movement`).
        # ── FASE 6 (INV-8): qty REJECT → KARANTINA (bukan hilang tanpa jejak) ──
        # accepted (net) → lokasi storage GR; rejected → lokasi KARANTINA (stok
        # diblokir/available=0) + dok `wh_quarantine_items` utk disposisi lanjutan.
        # ── FASE H-5 (2026-08-16): ROLL KAIN LAHIR DI SINI ──────────────────
        # Sebelum ini, GR menambah stok kain lewat `stock_service.add` tanpa pernah
        # menyentuh `wh_fabric_rolls` — gudang bisa punya 420 kg kain di sistem dan
        # NOL gulungan yang bisa ditunjuk, sementara Portal Cutting memerlukan roll
        # untuk melacak lot kain. Rincian roll (jumlah + berat/panjang tiap roll)
        # DIVALIDASI DULU untuk SEMUA baris sebelum satu pun stok ditulis, supaya
        # tidak ada GR setengah jadi: stok bertambah tapi rollnya gagal dibuat.
        roll_plan: dict = {}
        rolls_created: list = []      # nomor roll yang benar-benar terbit di GR ini
        rolls_pending: list = []      # baris kain yang MASUK STOK tanpa rincian roll
        for item in items_to_process:
            mid = item.get("material_id")
            lines = item.get("rolls") or []
            if not mid:
                continue
            mat_r = await db.rahaza_materials.find_one(
                {"id": mid}, {"_id": 0, "id": 1, "code": 1, "name": 1, "unit": 1,
                              "type": 1, "is_cut_panel": 1, "color": 1, "color_name": 1})
            if not mat_r:
                if not lines:
                    continue
                raise HTTPException(400, f"Material baris penerimaan tidak ditemukan: {mid}")
            accepted_probe = float(item.get("accepted_qty") if item.get("accepted_qty") is not None
                                   else max(0.0, float(item.get("received_qty", 0) or 0)
                                            - float(item.get("rejected_qty", 0) or 0)))
            if not lines:
                # Kain yang masuk stok TANPA rincian roll bukan kesalahan fatal (GR bisa
                # datang dari jalur otomatis/PO tanpa timbangan per gulungan), tetapi
                # lubangnya harus KELIHATAN: baris ini dilaporkan balik ke UI dan muncul
                # di daftar "Penerimaan tanpa roll" untuk diterbitkan kemudian (backfill).
                if accepted_probe > 0 and fabric_roll_engine.is_roll_material(mat_r):
                    rolls_pending.append({
                        "item_id": item.get("id"),
                        "material_id": mid,
                        "material_code": mat_r.get("code") or "",
                        "material_name": mat_r.get("name") or "",
                        "unit": mat_r.get("unit") or "",
                        "accepted_qty": round(accepted_probe, 3),
                    })
                continue
            if not fabric_roll_engine.is_roll_material(mat_r):
                raise HTTPException(400, (
                    f"{mat_r.get('code')} bersatuan '{mat_r.get('unit')}' tidak dilacak per "
                    "gulungan, jadi rincian roll tidak berlaku untuk baris ini."))
            accepted = accepted_probe
            if accepted <= 0:
                raise HTTPException(400, (
                    f"{mat_r.get('code')} — {mat_r.get('name')}: qty diterima 0, jadi tidak ada "
                    "gulungan yang bisa diterbitkan. Hapus rincian rollnya atau perbaiki qty."))
            roll_plan[item.get("id")] = (
                mat_r,
                fabric_roll_engine.validate_roll_lines(
                    lines, accepted, mat_r.get("unit") or "",
                    f"{mat_r.get('code')} — {mat_r.get('name')}"),
            )

        # ── 2026-11-06 (Tahap 1): KLAIM ATOMIK SEBELUM EFEK SAMPING ────────────
        # Semua validasi di atas tidak mengubah apa pun. Mulai baris ini stok, jurnal, HPP, roll, dan
        # karantina ditulis — jadi GR diklaim dulu (status lama → 'processing') dengan syarat statusnya
        # belum berubah. Klik ganda / pengguna kedua tidak lolos klaim dan mendapat 409. Bila proses
        # gagal di tengah, klaim dilepas (status kembali) supaya GR bisa dikonfirmasi ulang.
        prev_status = existing.get("status")   # None = dokumen lama tanpa status (cocok dgn filter None)
        claim = await db.warehouse_receiving.update_one(
            {"id": receipt_id, "status": prev_status},
            {"$set": {"status": GR_CLAIM_STATUS, "processing_at": now(), "processing_by": user.get("id")}})
        if not claim.matched_count:
            raise HTTPException(409, f"Penerimaan {existing.get('receipt_number') or ''} sedang/sudah "
                                     "dikonfirmasi pengguna lain. Muat ulang daftar penerimaan.")
        try:
            quarantined_total = 0.0
            quarantine_records = []
            rejected_doc_total = 0.0
            for item in items_to_process:
                received_qty = float(item.get("received_qty", 0) or 0)
                rejected_qty = float(item.get("rejected_qty", 0) or 0)
                net_qty = received_qty - rejected_qty

                sku   = item.get("sku", "")
                pname = item.get("product_name", "")
                unit  = item.get("unit", "pcs")
                lot_number  = item.get("lot_number") or ""
                expiry_date = item.get("expiry_date") or None
                material_id = item.get("material_id")

                if not material_id:
                    # Tanpa material_id item tak bisa masuk stok kanonik. JANGAN tulis
                    # ledger bayangan — catat warning & lewati (GR tetap tercatat).
                    logger.warning(
                        f"GR {existing.get('receipt_number','')}: item '{pname or sku}' "
                        f"tanpa material_id — dilewati (tidak masuk stok kanonik)."
                    )
                    continue

                if net_qty > 0:
                    # ── Satu pintu: stock_service.add (kanonik + ledger) ─────────────
                    # FATAL bila gagal: biarkan exception naik → status GR TIDAK di-set
                    # 'received' (baris update di ~L476 tak tercapai) → tidak ada stok
                    # bayangan / GR "received" tanpa stok. User bisa retry.
                    # Stok SEBELUM barang masuk — dipakai menghitung HPP rata-rata
                    # bergerak di bawah (harus dibaca sebelum `add`, bukan sesudah).
                    # 2026-11-02 (K11/No.26): hanya qty yang ADA DI NILAI PERSEDIAAN — reject GR di
                    # karantina (belum bernilai) tidak ikut membobot WAC (uji T1: 55.000 → 55.263,16).
                    qty_before_receipt = float(await quarantine.valued_onhand(db, material_id) or 0)
                    await stock_service.add(
                        material_id, loc_id, net_qty,
                        meta={
                            "inventory_category": item.get("inventory_category"),
                            "unit": unit,
                            "material_name": pname or None,
                            "material_code": sku or None,
                            "location_code": loc_name or None,
                        },
                        ref={
                            "source": "goods_receipt",
                            "ref_type": "goods_receipt",
                            "ref_id": receipt_id,
                            "ref_number": existing.get("receipt_number", ""),
                            "lot_number": lot_number,
                            "expiry_date": expiry_date,
                        },
                        actor={"id": user.get("id"), "name": user.get("name"), "email": user.get("email", "")},
                        db=db,
                    )

                    # ── Movement kanonik (audit) — non-fatal ─────────────────────────
                    gr_mv = None
                    try:
                        gr_mv = await _record_material_movement(
                            db, material_id, loc_id, loc_name, net_qty, unit,
                            "goods_receipt", receipt_id,
                            existing.get("receipt_number", ""),
                            f"GR {existing.get('receipt_number', '')} — {pname} dari {existing.get('supplier_name', existing.get('source_type', ''))}",
                            user,
                            unit_cost=gr_line_price(item),
                            material_name=pname,
                        )
                    except Exception as e:
                        logger.error(f"GR movement log failed (material_id={material_id}): {e}")
                        # Non-fatal: stok kanonik sudah tertulis; jangan putus flow.
                    # ── C-02 (audit 2026-09-04): GR bernilai → Dr Persediaan / Cr GRNI (2-1150).
                    # Tagihan supplier (AP-dari-GR) kemudian Dr GRNI / Cr Hutang Usaha. Non-fatal.
                    if gr_mv and gr_mv.get("unit_cost", 0) > 0:
                        try:
                            from routes.rahaza_posting import post_inventory_receive
                            gr_gl = await post_inventory_receive(db, gr_mv, user)
                            item["gl_je_number"] = gr_gl.get("je_number")
                            item["gl_error"] = gr_gl.get("error")
                        except Exception as e:
                            logger.error(f"GR GL posting gagal (material_id={material_id}): {e}")
                    logger.info(f"GR inbound via stock_service: material_id={material_id} +{net_qty} {unit} @ loc={loc_id}")

                    # ── HARGA SATUAN (HPP) DARI PEMBELIAN — keputusan pemilik 2026-08-21 ──
                    # Sebelumnya harga satuan HANYA bisa diketik di Master Item, dan
                    # penerimaan barang (GR) tidak pernah menyentuhnya: PO boleh berisi
                    # harga per satuan, barang masuk, tetapi nilai persediaan tetap
                    # memakai angka ketikan lama (atau 0 ⇒ jurnal persediaan tidak
                    # terbentuk). Sekarang setiap penerimaan bernilai memperbarui HPP
                    # dengan **rata-rata bergerak** (SSOT core/accessory_valuation) —
                    # berlaku untuk SEMUA jenis barang (kain, aksesoris, benang, dll),
                    # bukan hanya aksesoris seperti sebelumnya.
                    cost_in = gr_line_price(item)
                    if cost_in > 0:
                        try:
                            res_cost = await accessory_valuation.apply_receipt_cost(
                                db, material_id, net_qty, cost_in,
                                qty_before=qty_before_receipt,
                                actor={"id": user.get("id"), "name": user.get("name", "")},
                                notes=(f"GR {existing.get('receipt_number', '')}"
                                       f"{' · PO ' + str(existing.get('po_number')) if existing.get('po_number') else ''}"),
                            )
                            item["unit_cost_applied"] = res_cost["new_unit_cost"]
                            # 2026-11-06 (Tahap 2, butir 7): stok lama bernilai 0 (atau minus) ikut dinilai
                            # harga beli ini → jurnal koreksi supaya nilai stok = buku besar (cara FG).
                            gap_je = await purchase_costing.post_receipt_wac_gap(
                                db, material_id=material_id, cost_result=res_cost, qty_in=net_qty,
                                cost_in=cost_in, source_ref=f"gr:{receipt_id}:{item.get('id') or material_id}",
                                memo=(f"Nilai ulang stok lama {pname or sku or material_id} oleh harga beli GR "
                                      f"{existing.get('receipt_number', '')}"), user=user)
                            if gap_je:
                                item["wac_gap_je_number"] = gap_je.get("je_number")
                                item["wac_gap_error"] = gap_je.get("error")
                            logger.info(
                                f"GR HPP: material_id={material_id} {res_cost['old_unit_cost']} → "
                                f"{res_cost['new_unit_cost']} (harga beli {cost_in}, qty {net_qty})")
                        except Exception as e:  # noqa: BLE001 — HPP tidak boleh menggagalkan penerimaan
                            logger.error(f"GR HPP gagal (material_id={material_id}): {e}")

                    # ── FASE H-5: terbitkan roll untuk baris kain (nomor otomatis) ──
                    if item.get("id") in roll_plan:
                        mat_r, lines_ok = roll_plan[item["id"]]
                        made = await fabric_roll_engine.create_rolls_from_receipt(
                            db, {**existing, "location_name": loc_name, "location_id": loc_id},
                            item, mat_r, lines_ok, user)
                        rolls_created.extend(r["roll_no"] for r in made)
                        item["roll_ids"] = [r["id"] for r in made]
                        item["roll_numbers"] = [r["roll_no"] for r in made]

                # ── 2026-11-02 (K11): pisahkan alasan reject — hanya alasan FISIK yang masuk karantina.
                # Alasan dokumen/kuantitas (kurang dari PO, terlambat, dokumen) TIDAK menambah stok;
                # hanya dicatat di baris GR. PO tetap terbuka untuk sisanya (PO dihitung qty bersih).
                from routes.rahaza_grn_qc import split_reject_qty
                phys_qty, doc_qty = split_reject_qty(item.get("reject_reasons") or [], rejected_qty)
                if doc_qty > 0:
                    item["rejected_doc_qty"] = doc_qty
                    item["reject_doc_note"] = (
                        f"{doc_qty:g} {unit} ditolak karena alasan dokumen/kuantitas — tidak masuk stok "
                        "maupun karantina; sisa PO tetap terbuka.")
                    rejected_doc_total += doc_qty
                # ── FASE 6: reject masuk KARANTINA (non-fatal, GR tetap 'received') ──
                if phys_qty > 0:
                    try:
                        qdoc = await quarantine.quarantine_in(
                            db,
                            material_id=material_id,
                            qty=phys_qty,
                            unit=unit,
                            source={
                                "type": "goods_receipt",
                                "id": receipt_id,
                                "number": existing.get("receipt_number", ""),
                                "line_id": item.get("id"),
                                "supplier_name": existing.get("supplier_name", ""),
                                "po_number": existing.get("po_number", ""),
                            },
                            reject_reasons=item.get("reject_reasons") or [],
                            # reject saat GR: qty ini TIDAK di-invoice (AP pakai net qty)
                            # ⇒ belum pernah masuk nilai persediaan.
                            valued=False,
                            notes=f"Reject saat penerimaan GR {existing.get('receipt_number','')}",
                            actor={"id": user.get("id"), "name": user.get("name"), "email": user.get("email", "")},
                            # 2026-11-02 (K11): harga GR asal = harga bawaan lepas reject / Retur Pembelian
                            unit_cost=gr_line_price(item) or None,
                        )
                        item["quarantined_qty"] = phys_qty
                        item["quarantine_item_id"] = qdoc["id"]
                        quarantined_total += phys_qty
                        quarantine_records.append({"material_id": material_id, "qty": phys_qty,
                                                   "quarantine_item_id": qdoc["id"]})
                        logger.info(f"GR reject → karantina: material_id={material_id} {phys_qty} {unit}")
                    except Exception as e:
                        logger.error(f"GR quarantine gagal (material_id={material_id}): {e}")

            if quarantine_records or rejected_doc_total > 0:
                updates["items"] = items_to_process
            if rejected_doc_total > 0:
                updates["reject_doc_summary"] = {"total_qty": round(rejected_doc_total, 4), "at": now()}
            if quarantine_records:
                updates["quarantine_summary"] = {
                    "total_qty": round(quarantined_total, 4),
                    "records": quarantine_records,
                    "location": (await quarantine.get_quarantine_location_info(db)),
                    "at": now(),
                }

            # ── FASE H-5: simpan jejak roll di dokumen GR (dipakai UI + backfill) ──
            # `items` WAJIB ikut tersimpan supaya `roll_ids`/`roll_numbers` per baris tidak
            # hilang — daftar "Penerimaan tanpa roll" memakai `source_receipt_item_id`,
            # jadi baris GR harus tetap bisa dipasangkan dengan gulungannya.
            if rolls_created or rolls_pending:
                updates["items"] = items_to_process
                updates["rolls_created"] = rolls_created
                updates["rolls_pending"] = rolls_pending
                updates["rolls_summary"] = {
                    "issued_count": len(rolls_created),
                    "issued_numbers": rolls_created,
                    "pending_lines": len(rolls_pending),
                    "at": now(),
                }
                if rolls_created:
                    logger.info(
                        f"GR {existing.get('receipt_number','')}: {len(rolls_created)} roll terbit "
                        f"({', '.join(rolls_created[:5])}{'…' if len(rolls_created) > 5 else ''})")

            # ── Sprint 2.1: Update PO received qty (3-way matching) ───────────────
            po_id = existing.get("po_id")
            if po_id:
                try:
                    from routes.rahaza_po import update_po_received_qty
                    # Build items list with material_id and qty for PO update
                    items_for_po = []
                    for item in items_to_process:
                        net_qty = float(item.get("received_qty", 0)) - float(item.get("rejected_qty", 0))
                        if net_qty > 0:
                            items_for_po.append({
                                "material_id": item.get("material_id"),
                                "po_item_id": item.get("po_item_id"),
                                "qty": net_qty,
                            })
                    if items_for_po:
                        await update_po_received_qty(db, po_id, items_for_po)
                        logger.info(f"GR {existing.get('receipt_number')} updated PO {existing.get('po_number')} received qty")
                except Exception as e:
                    logger.error(f"Failed to update PO received qty: {e}")
                    # Non-fatal: don't break the receive flow
        
            # ── Phase 8A: Asset Capitalization (Auto-create Fixed Asset + GL Posting) ───
            try:
                await _capitalize_assets_from_grn(db, receipt_id, existing, items_to_process, user)
            except Exception as e:
                logger.error(f"Failed to capitalize assets from GR: {e}")
                # Non-fatal: log warning but don't break the receive flow
            # 2026-11-02 (K11): baris yang diterima SELALU disimpan (harga dari PO, catatan reject
            # dokumen, qty karantina) — tagihan dari GR & Retur Pembelian membaca harga baris ini.
            updates["items"] = items_to_process
            updates["received_at"] = existing.get("received_at") or now()
            updates["processing_at"] = None
            updates.update(pguard.price_status_fields([]))   # dikonfirmasi = semua baris berharga
            await db.warehouse_receiving.update_one({"id": receipt_id}, {"$set": updates})
        except BaseException:
            await db.warehouse_receiving.update_one(
                {"id": receipt_id, "status": GR_CLAIM_STATUS},
                {"$set": {"status": prev_status, "processing_at": None}})
            raise
    else:
        # perubahan biasa (draf/inspeksi) tidak boleh menimpa GR yang sedang dikonfirmasi
        res = await db.warehouse_receiving.update_one(
            {"id": receipt_id, "status": {"$ne": GR_CLAIM_STATUS}}, {"$set": updates})
        if not res.matched_count:
            raise HTTPException(409, f"Penerimaan {existing.get('receipt_number') or ''} sedang dikonfirmasi "
                                     "pengguna lain. Tunggu sebentar lalu muat ulang.")
    await log_activity(user["id"], user["name"], "update", "warehouse_receiving",
                       f"{existing.get('receipt_number', '')} → {body.get('status', 'updated')}")
    
    updated = await db.warehouse_receiving.find_one({"id": receipt_id}, {"_id": 0})
    return serialize_doc(updated)


@router.delete("/receiving/{receipt_id}", dependencies=only(*WAREHOUSE_ROLES))  # T-01 2.3
async def delete_receiving(receipt_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    receipt = await db.warehouse_receiving.find_one({"id": receipt_id})
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    if receipt.get("status") == "received":
        raise HTTPException(400, "Tidak bisa hapus GR yang sudah 'received'")
    if receipt.get("status") == GR_CLAIM_STATUS:
        raise HTTPException(409, "Penerimaan ini sedang dikonfirmasi — tidak bisa dihapus.")
    await db.warehouse_receiving.delete_one({"id": receipt_id, "status": {"$nin": ["received", GR_CLAIM_STATUS]}})
    return {"status": "deleted"}


# ── Stock Summary & Movements ─────────────────────────────────────────────────

@router.get("/stock")
async def get_stock(request: Request, location_id: str = None, sku: str = None):
    """FASE F: baca stok KANONIK `rahaza_material_stock` (bukan lagi `warehouse_stock`).
    Endpoint legacy tanpa konsumen UI aktif; dipertahankan sbg shim read-only kanonik."""
    await require_auth(request)
    db = get_db()
    query = {"qty": {"$gt": 0}}
    if location_id:
        query["location_id"] = location_id
    if sku:
        query["$or"] = [
            {"material_code": {"$regex": re.escape(sku), "$options": "i"}},
            {"sku": {"$regex": re.escape(sku), "$options": "i"}},
        ]
    stock = await db.rahaza_material_stock.find(query, {"_id": 0}).to_list(500)
    return serialize_doc(stock)


@router.get("/stock/summary")
async def get_stock_summary(request: Request):
    """FASE F: ringkasan stok KANONIK dari `rahaza_material_stock`."""
    await require_auth(request)
    db = get_db()
    pipeline = [
        {"$match": {"qty": {"$gt": 0}}},
        {"$group": {
            "_id": None,
            "total_skus": {"$sum": 1},
            "total_qty": {"$sum": "$qty"},
            "total_value": {"$sum": {"$multiply": ["$qty", {"$ifNull": ["$unit_cost", 0]}]}}
        }}
    ]
    results = await db.rahaza_material_stock.aggregate(pipeline).to_list(1)
    return serialize_doc(results[0] if results else {"total_skus": 0, "total_qty": 0, "total_value": 0})


@router.get("/movements")
async def get_movements(request: Request, location_id: str = None, sku: str = None, limit: int = 100):
    """FASE F: pergerakan stok KANONIK dari `rahaza_stock_ledger` (bukan `warehouse_movements`)."""
    await require_auth(request)
    db = get_db()
    query = {}
    if location_id:
        query["location_id"] = location_id
    if sku:
        query["material_id"] = {"$regex": re.escape(sku), "$options": "i"}
    movements = await db.rahaza_stock_ledger.find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(500)
    return serialize_doc(movements)


# ── Dashboard ──────────────────────────────────────────────────

@router.get("/dashboard-kpi")
async def warehouse_dashboard_kpi(request: Request):
    """Sprint 3.4 + FASE F: KPI KANONIK untuk WarehouseDashboard.jsx.
    total_items/total_qty/total_locations dari `rahaza_material_stock` (SSOT);
    pending_gr tetap dari `warehouse_receiving` (masih aktif via GR)."""
    await require_auth(request)
    db = get_db()

    # 2026-11-06 (pola P4): satu definisi GR terbuka (core.procurement_guards.GR_OPEN_STATUSES)
    pending_gr = await db.warehouse_receiving.count_documents({"status": {"$in": list(pguard.GR_OPEN_STATUSES)}})

    pipeline = [
        {"$match": {"qty": {"$gt": 0}}},
        {"$group": {
            "_id": None,
            "total_items": {"$sum": 1},
            "total_qty": {"$sum": "$qty"},
            "locations": {"$addToSet": "$location_id"},
        }},
    ]
    agg = await db.rahaza_material_stock.aggregate(pipeline).to_list(1)
    row = agg[0] if agg else {}
    total_items = int(row.get("total_items", 0))
    total_qty = float(row.get("total_qty", 0) or 0)
    total_locations = len([x for x in (row.get("locations") or []) if x])

    return serialize_doc({
        "total_items": total_items,
        "total_locations": total_locations,
        "pending_gr": pending_gr,
        "total_qty": round(total_qty, 2),
    })


@router.get("/dashboard")
async def warehouse_dashboard(request: Request):
    """FASE F: dashboard gudang KANONIK dari `rahaza_material_stock` + `rahaza_stock_ledger`."""
    await require_auth(request)
    db = get_db()

    pending_receipts = await db.warehouse_receiving.count_documents(
        {"status": {"$in": list(pguard.GR_OPEN_STATUSES)}})  # 2026-11-06 (pola P4)

    pipeline = [
        {"$match": {"qty": {"$gt": 0}}},
        {"$group": {
            "_id": None,
            "total_skus": {"$sum": 1},
            "total_qty": {"$sum": "$qty"},
            "locations": {"$addToSet": "$location_id"},
        }},
    ]
    agg = await db.rahaza_material_stock.aggregate(pipeline).to_list(1)
    row = agg[0] if agg else {}
    total_skus = int(row.get("total_skus", 0))
    total_qty = float(row.get("total_qty", 0) or 0)
    total_locations = len([x for x in (row.get("locations") or []) if x])

    recent_movements = await db.rahaza_stock_ledger.find({}, {"_id": 0}).sort("created_at", -1).limit(5).to_list(500)

    return serialize_doc({
        "total_locations": total_locations,
        "total_skus": total_skus,
        "total_qty": total_qty,
        "pending_receipts": pending_receipts,
        "recent_movements": recent_movements,
    })


# ── Put-Away & Stock Opname (LEGACY) — DIHAPUS (FASE F, 2026-07-25) ─────────────
# Endpoint `/api/warehouse/putaway` (transfer) & `/api/warehouse/opname` (variance)
# adalah GEN-1 legacy penulis ledger ganda `warehouse_stock`/`warehouse_movements`
# (sumber INV-11). Tidak ada konsumen UI/BE (audit Fase F = 0). Kanonik:
#   Put-Away → /api/wms/putaway/*  (routes/wms_putaway.py, sadar-lokasi)
#   Opname   → /api/wms/opname3/*  (routes/wms_opname3.py, scan-driven + finance)
# Koleksi terkait DROP via scripts/migrate_drop_warehouse_ledger_legacy.py.


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 8A: ASSET CAPITALIZATION DARI GRN
# ══════════════════════════════════════════════════════════════════════════════

async def _capitalize_assets_from_grn(db, receipt_id: str, grn: dict, items: list, user: dict):
    """
    Phase 8A: Auto-create Fixed Assets + GL Posting untuk GRN items dengan item_type='asset'.
    
    Logic:
    1. Detect items dengan item_type='asset'
    2. Create fixed asset record di rahaza_fixed_assets
    3. Auto-post GL: Dr. Fixed Asset / Cr. AP Clearing
    4. Link GRN item dengan asset_id

    2026-11-02 (K18): pendaftaran lewat SATU pintu registri Keuangan
    (`routes.rahaza_fixed_assets.register_fixed_asset`) — validasi, akun kategori, jadwal penyusutan,
    dan jurnal perolehan (Dr akun aset kategori / Cr Hutang Belum Ditagih) sama dengan form Aset Tetap.
    Dulu aset GR tanpa jadwal penyusutan & selalu Dr 1-2500. Idempoten per baris GR (`grn_item_id`).
    """
    from routes.rahaza_fixed_assets import register_fixed_asset
    from utils.waktu import today_wib

    assets_created = []

    for item in items:
        # Check if this is an asset item
        if item.get("item_type", "material") != "asset":
            continue

        net_qty = float(item.get("received_qty", 0)) - float(item.get("rejected_qty", 0))
        if net_qty <= 0:
            continue
        if item.get("id") and await db.rahaza_fixed_assets.find_one(
                {"grn_id": receipt_id, "grn_item_id": item.get("id")}, {"_id": 1}):
            continue  # sudah dikapitalisasi (penerimaan ulang tidak menggandakan aset/jurnal)
        
        # Get asset parameters
        unit_price = float(item.get("unit_price", 0))
        if unit_price <= 0:
            logger.warning(f"GRN item {item.get('product_name')} is asset but unit_price=0, skipping capitalization")
            continue
        
        total_cost = round(unit_price * net_qty, 2)
        asset_category = item.get("asset_category", "lain-lain")
        
        # Generate asset code — SESI #27: field yang benar adalah `code` (nama
        # dokumennya), bukan `asset_code`. Dengan nama field yang salah,
        # penyemaian counter membaca `asset_code` yang TIDAK PERNAH ada di
        # dokumen ⇒ counter selalu mulai dari 0 saat pertama kali dipakai.
        # `config_key` menyambungkannya ke katalog Penomoran Dokumen owner.
        asset_code = await gen_prefixed_number(
            db, "rahaza_fixed_assets", "code", "FA-", 5,
            config_key="rahaza_fixed_assets.code")
        
        # Default useful life per category (months)
        useful_life_map = {
            "tanah": 0,  # No depreciation
            "bangunan": 240,  # 20 years
            "mesin": 120,  # 10 years
            "kendaraan": 60,  # 5 years
            "peralatan": 60,  # 5 years
            "it": 36,  # 3 years
            "furnitur": 60,  # 5 years
            "lain-lain": 60,  # 5 years default
        }
        useful_life = useful_life_map.get(asset_category, 60)

        # Create fixed asset — registri yang SAMA dengan form Keuangan (K18)
        payload = {
            "name": item.get("product_name", "Unnamed Asset"),
            "category": asset_category,
            "acquisition_type": "purchase",
            "funding_source": "grni",
            "_system_gr": True,
            "serial_number": item.get("serial_number", ""),
            "purchase_date": today_wib().isoformat(),
            "purchase_cost": total_cost,
            "residual_value": 0,  # Default: no residual
            "useful_life_months": useful_life,
            "depreciation_method": "straight_line" if useful_life > 0 else "none",
            "location": grn.get("location_name", ""),
            "supplier": grn.get("supplier_name", ""),
            "notes": f"Auto-created from GR {grn.get('receipt_number', '')} - {item.get('product_name', '')}",
        }
        extra = {
            "grn_id": receipt_id,
            "grn_number": grn.get("receipt_number", ""),
            "grn_item_id": item.get("id", ""),
            "po_id": grn.get("po_id"),
            "po_number": grn.get("po_number", ""),
            "supplier_name": grn.get("supplier_name", ""),
            "qty_received": net_qty,
            "unit": item.get("unit", "pcs"),
            "updated_at": now(),
            "created_by_name": user.get("name", "system"),
        }
        try:
            asset_doc = await register_fixed_asset(db, payload, user, code=asset_code, extra=extra)
        except HTTPException as e:
            # Penerimaan stok tetap jalan; kapitalisasi ditandai gagal supaya Keuangan menindaklanjuti.
            logger.warning(f"Kapitalisasi aset GR {grn.get('receipt_number', '')} gagal: {e.detail}")
            # 2026-11-06 (Tahap 2): tanda juga ditulis ke baris DI MEMORI — penyimpanan akhir GR menimpa
            # `items` seluruhnya dengan daftar ini (dulu tanda di DB hilang tertimpa).
            item.update({"capitalize_error": str(e.detail), "capitalized": False})
            await db.warehouse_receiving.update_one(
                {"id": receipt_id, "items.id": item.get("id")},
                {"$set": {"items.$.capitalize_error": str(e.detail), "items.$.capitalized": False}})
            assets_created.append({"asset_id": None, "asset_code": asset_code, "asset_name": payload["name"],
                                   "total_cost": total_cost, "posting_result": {"ok": False, "error": str(e.detail)}})
            continue
        posting_result = asset_doc.get("_posting_result")
        logger.info(f"✅ Fixed asset created: {asset_code} - {asset_doc['name']} (Rp {total_cost:,.0f}) "
                    f"JE {(posting_result or {}).get('je_number', 'N/A')}")

        # Update GRN item dengan asset_id — 2026-11-06 (Tahap 2): juga di baris DI MEMORI, karena
        # penyimpanan akhir GR (`updates["items"] = items_to_process`) menimpa tulisan posisional ini.
        item.update({"asset_id": asset_doc["id"], "asset_code": asset_code, "capitalized": True,
                     "capitalized_at": now(), "capitalize_error": None})
        await db.warehouse_receiving.update_one(
            {"id": receipt_id, "items.id": item.get("id")},
            {"$set": {
                "items.$.asset_id": asset_doc["id"],
                "items.$.asset_code": asset_code,
                "items.$.capitalized": True,
                "items.$.capitalized_at": now(),
                "items.$.capitalize_error": None,
            }}
        )

        assets_created.append({
            "asset_id": asset_doc["id"],
            "asset_code": asset_code,
            "asset_name": asset_doc["name"],
            "total_cost": total_cost,
            "posting_result": posting_result,
        })
    
    if assets_created:
        logger.info(f"🎯 Phase 8A: {len(assets_created)} fixed assets capitalized from GR {grn.get('receipt_number', '')}")
    
    return assets_created

