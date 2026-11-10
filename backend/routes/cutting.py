"""
PORTAL CUTTING — Roll Kain ➜ Kain Pola (Potongan)
CV. Dewi Aditya ERP · FASE IA-4

MENGAPA MODUL INI ADA
---------------------
Di DA, kain datang sebagai ROLL (satuan Kg / Yard / Meter). Sebelum bisa dijahit,
roll harus dipotong jadi KAIN POLA ("potongan") per style + warna + size (satuan pcs).
Potongan inilah yang:
  · dihitung sebagai MATERIAL (bukan barang jadi) di gudang,
  · dipakai sebagai komponen BOM job produksi internal,
  · dikirim ke CMT lewat "Kirim Material CMT" / "Pengeluaran Material".
Sebelum modul ini, langkah tersebut tidak tercatat di sistem sehingga stok kain
tidak pernah berkurang dan potongan tidak pernah punya identitas stok.

KEPUTUSAN DESAIN (hasil pemetaan database — bukan tebakan)
----------------------------------------------------------
1. TIDAK membuat gudang/stok baru. Semua mutasi lewat SSOT `core.stock_service`
   (`issue()` untuk kain, `add()` untuk potongan) sehingga:
   `rahaza_material_stock` + `rahaza_stock_ledger` tetap satu-satunya kebenaran,
   dan seluruh laporan stok/valuasi lama otomatis ikut benar.
2. Output potongan = DOKUMEN BARU di `rahaza_materials` (master material) —
   sesuai keputusan owner. Ditandai `is_cut_panel: True`, `type: "fabric"`,
   `category: "POTONGAN"`, `unit: "pcs"`, plus `source_material_id` ke kain asalnya
   sehingga ketelusuran roll ➜ potongan tidak putus.
   Kode dibangkitkan deterministik: `CUT-<STYLE>-<WARNA>-<SIZE>`; bila sudah ada,
   dipakai ulang (idempoten) — mencegah duplikat master.
3. Roll fisik (`wh_fabric_rolls`) **WAJIB** untuk kain yang dilacak per gulungan
   (FASE H-6, keputusan owner 2026-08-16). Sebelum ini pemilihan roll bersifat
   opsional, artinya kain bisa dipotong tanpa satu gulungan pun berkurang: stok
   turun, roll tetap penuh, dan tidak ada cara menjawab "gulungan mana yang dipakai
   untuk order ini" saat buyer menuntut lot kain yang sama. Sekarang: sisa roll
   (`remaining_kg`/`remaining_m`) dikurangi FIFO lewat SATU pintu
   `core.fabric_roll_engine` (+ movement `wh_fabric_roll_movements`), TANPA
   memotong stok material dua kali (potong stok material hanya sekali, di sini).
   Bila kainnya belum punya gulungan sama sekali, permintaan DITOLAK dengan alasan
   yang menyebut jalan keluarnya (isi Rincian Roll di Penerimaan Barang, atau
   terbitkan gulungan retroaktif di Gudang → Roll Kain).
4. HPP: saat COMPLETE, harga satuan potongan dihitung
   = (qty kain terpakai × unit_cost kain) / qty potongan jadi, lalu ditulis ke
   `unit_cost` master potongan supaya jurnal persediaan & HPP hilir tetap benar.

5. BANYAK KAIN × BANYAK HASIL (keputusan owner 10 Nov 2026, SSOT `core.cutting_lines`):
   satu order = `inputs[]` (kain dari master + gulungan, boleh beberapa kain) dan `outputs[]` (model × varian ×
   target pcs + baris PO opsional, masing-masing master potongannya sendiri, `roll_ids` = gulungan yang dipakai
   untuk hasil itu — ketelusuran, bukan dasar HPP). Lapor progres: pemakaian & gulungan PER KAIN, pcs PER HASIL;
   stok tiap kain dipotong sekali, stok potongan bertambah per hasil. HPP potongan per pcs = Σ(kain terpakai ×
   harga satuan kain) ÷ total pcs hasil SEMUA baris (sama untuk semua baris; order satu-baris = angka lama).
   Dokumen lama satu-kain/satu-hasil tetap terbaca (dinormalkan saat dibaca) dan field lama tingkat atas tetap
   diisi (`cutting_lines.compat_fields`).

STATE MACHINE
-------------
   draft ──start──▶ in_progress ──complete──▶ completed
     │                   │
     └───cancel──────────┘   (cancel hanya bila belum ada progres)

Koleksi baru (tidak bentrok dengan koleksi manapun yang sudah ada — sudah diverifikasi):
  · cutting_orders
  · cutting_progress
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from auth import require_auth, serialize_doc, log_activity
from core import stock_service
from core import fabric_roll_engine  # FASE H-6: gulungan WAJIB ditunjuk saat memotong
from core import cutting_material_issue  # FASE H-6b: arus keluar kain punya DOKUMEN
from core import cut_panel_value    # SESI #32: nilai kain berpindah jadi nilai potongan
from core import cut_panel_health   # SESI #32: penjaga & pembersih potongan yatim
from core import cut_panel_master   # 2026-09-12: SSOT identitas potongan = model × warna × ukuran (BOM potongan)
from core import bom_uom as _bom_uom  # cakupan lebar: kemasan + global + kain (gsm & lebar)
from core import product_costing  # BOM → kebutuhan kain per pcs (rencana tidak lagi ditebak)
from core import cutting_lines  # 2026-11-10: banyak kain × banyak hasil per order (SSOT bentuk baris)
from core.stock_service import InsufficientStock
from core import doc_lock
from database import get_db
from utils.counters import gen_prefixed_number

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cutting", tags=["cutting"])

ORDERS = "cutting_orders"
PROGRESS = "cutting_progress"

STATUS_DRAFT = "draft"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

# Satuan kain yang wajar jadi INPUT cutting (roll).
# 2026-11-06 (pola P8): "roll" = ejaan resmi master satuan; "rol"/"gulung" tetap diterima (data lama)
#: Jenis lokasi yang tidak memegang stok kain (master `rahaza_locations.type`).
NON_STOCK_LOCATION_TYPES = ("kantor",)
INPUT_UNITS = {"kg", "gram", "m", "cm", "yard", "inch", "roll", "rol", "gulung", "bal"}
OUTPUT_UNIT = "pcs"
OUTPUT_CATEGORY = "POTONGAN"


async def ensure_cutting_indexes():
    """Indeks + PEMBUATAN koleksi cutting saat startup.

    Kenapa dipanggil di startup (bukan lazy saat order pertama dibuat):
    `mongodump` hanya menyalin koleksi yang SUDAH ADA. Kalau koleksi cutting baru
    lahir saat transaksi pertama, backup yang diambil sebelum itu tidak memuatnya
    dan proses restore akan menghapus jejak modul ini. Membuat indeks di startup
    memastikan `cutting_orders` & `cutting_progress` selalu ikut ter-backup.
    """
    db = get_db()
    await db[ORDERS].create_index("id", unique=True)
    await db[ORDERS].create_index("number", unique=True)
    await db[ORDERS].create_index("status")
    await db[ORDERS].create_index("input_material_id")
    await db[ORDERS].create_index("output_material_id")
    # 2026-11-10: order banyak baris dicari lewat barisnya (pemakaian master, kesehatan potongan, ketelusuran roll)
    await db[ORDERS].create_index("inputs.input_material_id")
    await db[ORDERS].create_index("outputs.output_material_id")
    await db[ORDERS].create_index("inputs.roll_ids.roll_id")
    await db[PROGRESS].create_index("id", unique=True)
    await db[PROGRESS].create_index("cutting_order_id")
    # FASE H-6b — satu laporan progres = MAKSIMAL satu dokumen Pengeluaran Material.
    # Indeks unik sparse-nya dibuat di satu tempat (core/cutting_material_issue)
    # supaya aturan idempotensinya tidak tersebar.
    await db[PROGRESS].create_index("material_issue_id")
    await cutting_material_issue.ensure_indexes(db)
    log.info("Cutting indexes created (cutting_orders, cutting_progress)")


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _slug(v: str, maxlen: int = 14) -> str:
    out = "".join(ch for ch in (v or "").upper() if ch.isalnum() or ch in (" ", "-"))
    out = "-".join(p for p in out.replace(" ", "-").split("-") if p)
    return out[:maxlen] or "NA"


async def _require_cutting_user(request: Request) -> dict:
    """Cutting = pekerjaan gudang/produksi.

    2026-08-06: gerbang izin dipusatkan ke `routes.shared.require_perm`
    (model fallback aman) supaya owner bisa memberi/mencabut hak lewat layar
    "Peran & Hak Akses" tanpa mengubah kode.
    """
    from routes.shared import require_perm
    return await require_perm(
        request, "cutting.manage", "cutting.input", "warehouse.manage",
        legacy_roles=(
            "spv_cuting", "operator_cuting",
            "supervisor_produksi", "admin_produksi", "supervisor",
            "admin_gudang",
        ),
        message="Akses ditolak: butuh izin cutting (cutting.manage / cutting.input).",
    )


async def _actor(user: dict) -> dict:
    return {"id": user.get("id"), "name": user.get("name", "")}


async def _get_order(db, oid: str) -> dict:
    doc = await db[ORDERS].find_one({"id": oid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Cutting order tidak ditemukan.")
    return doc


async def _stock_locations(db, material_id: str) -> list[dict]:
    """Daftar lokasi yang MEMANG punya stok untuk material ini, urut qty terbesar.

    Kenapa perlu: stok tidak disimpan global melainkan per (material, lokasi).
    Bug nyata yang ditemukan QA: cutting dibuat dengan lokasi bawaan sistem
    ("Gedung Produksi") padahal saldo kain berada di "Gudang Lantai 1/Area Gudang",
    sehingga validasi start LULUS (cek total lintas lokasi) tapi pemotongan stok
    GAGAL (cek per-lokasi). Sejak sekarang lokasi order selalu diarahkan ke lokasi
    yang benar-benar memegang stok.
    """
    from core.stock_schema import read_qty
    rows = await db.rahaza_material_stock.find({"material_id": material_id}, {"_id": 0}).to_list(500)
    out = []
    for r in rows:
        qty = float(read_qty(r) or 0)
        if qty <= 0:
            continue
        out.append({"location_id": r.get("location_id"), "qty": round(qty, 4)})
    if not out:
        return []
    ids = [o["location_id"] for o in out if o["location_id"]]
    names = {}
    async for loc in db.rahaza_locations.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "code": 1}):
        names[loc["id"]] = loc.get("name") or loc.get("code") or ""
    async for z in db.wh_zones.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "code": 1}):
        names.setdefault(z["id"], z.get("name") or z.get("code") or "")
    for o in out:
        o["location_name"] = names.get(o["location_id"], "Lokasi lain")
    out.sort(key=lambda x: -x["qty"])
    return out


async def _default_location(db, location_id: Optional[str] = None,
                            material_id: Optional[str] = None) -> tuple[str, str]:
    """Lokasi order cutting = lokasi yang DIPILIH pengguna (wajib).

    2026-11-02 — No.18(a) owner: pengguna wajib memilih lokasi. Dulu bila kosong/salah
    dipakai berturut-turut: stok terbanyak → lokasi bernama 'Gudang…' → lokasi aktif
    pertama. Dialog Order Cutting sudah mewajibkan "Gudang Sumber Kain" (saran stok
    terbanyak tampil & bisa diubah di layar), jadi tebakan diam-diam di sini dicabut.
    `material_id` dipertahankan di tanda tangan untuk kompatibilitas pemanggil.
    """
    location_id = (location_id or "").strip()
    if not location_id:
        raise HTTPException(400, "location_id wajib diisi — pilih Gudang Sumber Kain untuk order cutting ini.")
    loc = await db.rahaza_locations.find_one({"id": location_id}, {"_id": 0})
    if loc:
        return loc["id"], loc.get("name") or loc.get("code") or ""
    z = await db.wh_zones.find_one({"id": location_id}, {"_id": 0})
    if z:
        return z["id"], z.get("name") or z.get("code") or ""
    pos = await db.wh_positions.find_one({"id": location_id}, {"_id": 0})
    if pos:
        return pos["id"], pos.get("label") or pos.get("barcode") or pos.get("code") or ""
    raise HTTPException(400, "Gudang Sumber Kain yang dipilih tidak ditemukan di Struktur Gudang.")


async def _enrich(db, o: dict) -> dict:
    o["progress_count"] = await db[PROGRESS].count_documents({"cutting_order_id": o["id"]})
    # 2026-11-10: dokumen lama dinormalkan saat dibaca (`inputs[0]`/`outputs[0]`) — tidak dimigrasi paksa.
    ins, outs = cutting_lines.inputs_of(o), cutting_lines.outputs_of(o)
    for i in ins:
        i["input_remaining"] = round(max(_f(i.get("planned_input_qty")) - _f(i.get("consumed_input_qty")), 0), 4)
        i["label"] = cutting_lines.input_label(i)
    for x in outs:
        p = _f(x.get("planned_output_qty"))
        x["output_remaining"] = round(max(p - _f(x.get("produced_qty")), 0), 4)
        x["progress_pct"] = round(_f(x.get("produced_qty")) / p * 100, 1) if p > 0 else 0.0
        x["label"] = cutting_lines.output_label(x)
    o["inputs"], o["outputs"] = ins, outs
    o["multi"] = len(ins) > 1 or len(outs) > 1
    planned_in = _f(o.get("planned_input_qty"))
    consumed = _f(o.get("consumed_input_qty"))
    planned_out = sum(_f(x.get("planned_output_qty")) for x in outs) if outs else _f(o.get("planned_output_qty"))
    produced = sum(_f(x.get("produced_qty")) for x in outs) if outs else _f(o.get("produced_qty"))
    o["input_remaining"] = round(max(planned_in - consumed, 0), 4)
    o["output_remaining"] = round(max(planned_out - produced, 0), 4)
    o["progress_pct"] = round((produced / planned_out * 100), 1) if planned_out > 0 else 0.0
    o["yield_per_input"] = round(produced / consumed, 3) if consumed > 0 else 0.0
    o["roll_usage"] = cutting_lines.roll_usage(o)
    return o


async def _save_lines(db, oid: str, inputs: list, outputs: list, extra: Optional[dict] = None,
                      cond: Optional[dict] = None):
    """Tulis baris + field lama tingkat atas (kompatibel) dalam SATU update. `cond` = syarat tambahan (kunci)."""
    patch = {"inputs": inputs, "outputs": outputs, **cutting_lines.compat_fields(inputs, outputs),
             "updated_at": _now(), **(extra or {})}
    return await db[ORDERS].update_one({"id": oid, **(cond or {})}, {"$set": patch})


# ═════════════════════════════════════════════════════════════════════════════
# MASTER HELPERS — dipakai form frontend
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/input-materials")
async def list_input_materials(request: Request, q: Optional[str] = None):
    """Master material yang layak jadi INPUT cutting (kain/benang, BUKAN potongan)."""
    await require_auth(request)
    db = get_db()
    query: dict = {
        "active": True,
        "type": {"$in": ["fabric", "yarn"]},
        "is_cut_panel": {"$ne": True},
    }
    if q:
        query["$or"] = [
            {"code": {"$regex": q, "$options": "i"}},
            {"name": {"$regex": q, "$options": "i"}},
            {"color": {"$regex": q, "$options": "i"}},
        ]
    mats = await db.rahaza_materials.find(query, {"_id": 0}).sort("name", 1).to_list(5000)
    ids = [m["id"] for m in mats]
    onhand = await stock_service.onhand_map(ids, db=db) if ids else {}
    rolls = {}
    if ids:
        cur = db.wh_fabric_rolls.aggregate([
            {"$match": {"material_id": {"$in": ids}, "status": {"$nin": ["fully_issued", "rejected"]}}},
            {"$group": {"_id": "$material_id", "n": {"$sum": 1}}},
        ])
        async for r in cur:
            rolls[r["_id"]] = r["n"]
    # Peta lokasi-berstok per material (1 query, bukan N query) — dipakai form agar
    # user langsung tahu stok kain ADA DI GUDANG MANA.
    loc_names = {}
    async for loc in db.rahaza_locations.find({}, {"_id": 0, "id": 1, "name": 1, "code": 1}):
        loc_names[loc["id"]] = loc.get("name") or loc.get("code") or ""
    from core.stock_schema import read_qty
    per_mat: dict[str, list] = {}
    if ids:
        async for r in db.rahaza_material_stock.find({"material_id": {"$in": ids}}, {"_id": 0}):
            q = float(read_qty(r) or 0)
            if q <= 0:
                continue
            per_mat.setdefault(r["material_id"], []).append({
                "location_id": r.get("location_id"),
                "location_name": loc_names.get(r.get("location_id"), "Lokasi lain"),
                "qty": round(q, 4),
            })
    for m in mats:
        locs = sorted(per_mat.get(m["id"], []), key=lambda x: -x["qty"])
        m["stock_qty"] = round(_f(onhand.get(m["id"])), 4)
        m["roll_count"] = rolls.get(m["id"], 0)
        m["stock_locations"] = locs
        m["best_location_id"] = locs[0]["location_id"] if locs else None
        m["best_location_name"] = locs[0]["location_name"] if locs else ""
    return serialize_doc(mats)


@router.get("/locations")
async def list_locations(request: Request):
    """Lokasi gudang untuk dropdown form cutting.

    2026-11-07 (Tahap 5): lokasi KANTOR (Kantor Pusat, Ruang Admin/HR/Marketing) tidak memegang kain —
    dulu ikut tampil sebagai "Gudang Sumber Kain" sehingga order bisa menunjuk ruang kantor."""
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_locations.find(
        {"active": True, "type": {"$nin": list(NON_STOCK_LOCATION_TYPES)}}, {"_id": 0}).sort("name", 1).to_list(500)
    return serialize_doc(rows)


@router.get("/rolls")
async def list_rolls(request: Request, material_id: str, location_id: Optional[str] = None):
    """Gulungan yang masih bersisa untuk satu kain (WAJIB dipilih saat lapor progres).

    Urut nomor roll = FIFO penerimaan, sehingga gulungan tertua dipakai lebih dulu
    dan kain tidak menua di rak sampai warnanya berubah.
    """
    await require_auth(request)
    db = get_db()
    rows = await fabric_roll_engine.open_rolls(db, material_id)
    out = []
    far_ids: set = set()
    if location_id:
        # 2026-11-06 (Tahap 2): gulungan di gudang lain tidak bisa dipilih untuk order di gudang ini
        want = await _place_of(db, location_id)
        for r in rows:
            loc = r.get("location_id") or r.get("position_id") or ""
            if loc and want and await _place_of(db, loc) != want:
                far_ids.add(r["id"])
    for r in rows:
        if r["id"] in far_ids:
            continue
        out.append({**r,
                    "remaining": round(fabric_roll_engine.remaining_of(r), 3),
                    "remaining_uom": r.get("uom", "")})
    mat = await db.rahaza_materials.find_one(
        {"id": material_id}, {"_id": 0, "id": 1, "code": 1, "name": 1, "unit": 1,
                              "type": 1, "is_cut_panel": 1})
    tracked = bool(mat and fabric_roll_engine.is_roll_material(mat))
    return serialize_doc({
        "items": out,
        "total": len(out),
        # `roll_required` dipakai UI untuk menandai pemilih roll sebagai WAJIB (H-6)
        # dan menampilkan jalan keluar bila daftarnya kosong.
        "roll_required": tracked,
        "total_remaining": round(sum(x["remaining"] for x in out), 3),
        "other_location_count": len(far_ids),
        "uom": (out[0].get("uom") if out else (fabric_roll_engine.roll_uom(mat.get("unit")) if mat else "")),
    })


@router.get("/bom-requirement")
async def bom_requirement(request: Request, model_id: str, size_id: Optional[str] = None,
                          variant_id: Optional[str] = None, qty_pcs: float = 0,
                          input_material_id: Optional[str] = None, color: Optional[str] = None):
    """Kebutuhan bahan menurut BOM untuk rencana potongan (dipakai dialog Order Cutting).

    KENAPA: sebelum ini `planned_input_qty` (rencana pemakaian kain) DITEBAK manual
    padahal BOM per model+size sudah menyimpan kebutuhan per pcs. Endpoint ini
    mengembalikan kebutuhan **per pcs** dan **total** dalam satuan DASAR kain
    (lewat SSOT `core/bom_uom`), plus daftar aksesoris yang ikut dibutuhkan.
    Jujur: BOM tidak ada / kain terpilih tidak ada di BOM / satuan belum jelas
    dilaporkan di `gaps` — bukan diam-diam kosong.
    """
    await _require_cutting_user(request)
    db = get_db()
    data = await product_costing.bom_requirement_for_cutting(
        db, model_id=model_id, size_id=size_id, variant_id=variant_id,
        qty_pcs=_f(qty_pcs), input_material_id=input_material_id, color=color)
    return serialize_doc(data)


@router.get("/po-lines")
async def list_po_lines(request: Request, model_id: str):
    """Baris PO produksi (per ukuran) model ini yang masih terbuka — tautan OPSIONAL order cutting
    (2026-11-06, Tahap 2) supaya BOM per ukuran & warna PO yang dipakai."""
    await require_auth(request)
    db = get_db()
    items = await db.po_items.find({"model_id": model_id}, {"_id": 0}).to_list(500)
    po_ids = list({i.get("po_id") for i in items if i.get("po_id")})
    pos = {}
    if po_ids:
        for p in await db.production_pos.find(
                {"id": {"$in": po_ids}}, {"_id": 0, "id": 1, "po_number": 1, "status": 1}).to_list(500):
            pos[p["id"]] = p
    out = []
    for it in items:
        po = pos.get(it.get("po_id")) or {}
        if not po or po.get("status") in CLOSED_PO_STATUSES:
            continue
        out.append({"id": it.get("id"), "po_id": it.get("po_id"),
                    "po_number": po.get("po_number") or it.get("po_number") or "",
                    "size_id": it.get("size_id") or "", "size": it.get("size") or "",
                    "color": it.get("color") or "", "qty": it.get("qty") or 0, "sku": it.get("sku") or "",
                    "rahaza_variant_id": it.get("rahaza_variant_id") or ""})
    out.sort(key=lambda x: (x["po_number"], x["size"]))
    return serialize_doc(out)


@router.get("/output-materials")
async def list_output_materials(request: Request):
    """Semua master potongan yang pernah dihasilkan cutting.

    SESI #32 — layar Master Potongan tidak lagi hanya menampilkan QTY: tiap baris
    membawa NILAI (stok × HPP), STATUS nilainya (`valued`/`unvalued` + alasannya),
    ASAL-nya (kain sumber + nomor order cutting), dan penanda **yatim** beserta
    alasan mengapa ia belum boleh dibersihkan.
    """
    await require_auth(request)
    db = get_db()
    mats = await db.rahaza_materials.find(
        {"is_cut_panel": True, "active": True}, {"_id": 0}
    ).sort("code", 1).to_list(2000)
    ids = [m["id"] for m in mats]
    onhand = await stock_service.onhand_map(ids, db=db) if ids else {}
    for m in mats:
        qty = round(_f(onhand.get(m["id"])), 4)
        row = await cut_panel_health.inspect(db, m, onhand=qty)
        m["stock_qty"] = qty
        m["stock_value"] = row["stock_value"]
        m["value_status"] = row["value_status"]
        m["value_note"] = m.get("value_note") or ""
        m["orphan"] = row["orphan"]
        m["orphan_reasons"] = row["reasons"]
        m["orphan_reason_text"] = row["reason_text"]
        m["cleanable"] = row["cleanable"]
        m["block_reason"] = row["block_reason"]
        m["cutting_order_number"] = row["cutting_order_number"]
        m["source_material_code"] = row["source_material_code"]
    return serialize_doc(mats)


@router.get("/panels/health")
async def panels_health(request: Request, only_orphan: bool = True, limit: int = 500):
    """Kesehatan master POTONGAN: mana yang YATIM & mana yang boleh dibersihkan.

    Read-only. Dipakai kartu "Potongan yatim" di Portal Cutting dan gate INV-F37.
    """
    await require_auth(request)
    db = get_db()
    return serialize_doc(await cut_panel_health.scan(
        db, limit=limit, only_orphan=only_orphan))


@router.post("/panels/cleanup")
async def panels_cleanup(request: Request):
    """Bersihkan master potongan yatim yang TERBUKTI belum pernah dipakai.

    Body opsional: `{"ids": [...], "dry_run": true}`. Yang masih berstok / punya
    kartu stok / dirujuk dokumen lain TIDAK dihapus — alasannya dikembalikan.
    """
    user = await _require_cutting_user(request)
    db = get_db()
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — tombol tanpa argumen: bersihkan semua yang layak
        body = {}
    body = body or {}
    ids = [str(x) for x in (body.get("ids") or []) if str(x or "").strip()]
    res = await cut_panel_health.cleanup(
        db, user, ids=ids or None, dry_run=bool(body.get("dry_run")))
    if res.get("removed") and not res.get("dry_run"):
        await log_activity(user["id"], user.get("name", ""), "cleanup",
                           "cutting.panels", f"{res['removed']} potongan yatim")
    return serialize_doc(res)


@router.delete("/panels/{panel_id}")
async def delete_panel(panel_id: str, request: Request):
    """Hapus PERMANEN satu master potongan (tombol Hapus per baris, 10 Nov 2026).

    Pemeriksaannya SAMA dengan pembersihan massal: `core.cut_panel_health.inspect` (order cutting yang menunjuknya,
    buku besar & kartu stok, `REFERENCE_CHECKS`: BOM, pengeluaran/permintaan material, opname, PO, penerimaan) —
    daftar cek tidak disalin. Bedanya: potongan yang tidak yatim pun boleh dihapus selama memang belum dipakai.
    Bila sudah dipakai → 409 dengan rinciannya, dan layar menawarkan Nonaktifkan (Master Item).
    """
    user = await _require_cutting_user(request)
    db = get_db()
    panel = await db.rahaza_materials.find_one({"id": panel_id, "is_cut_panel": True}, {"_id": 0})
    if not panel:
        raise HTTPException(404, "Master potongan tidak ditemukan.")
    row = await cut_panel_health.inspect(db, panel)
    from core.hapus_master import tolak_bila_dipakai, SARAN_NONAKTIF
    pakai = {label: n for label, n in (("order cutting", row["orders_referencing"]),
                                        ("baris buku besar stok", row["ledger_rows"]),
                                        ("baris kartu stok", row["card_rows"])) if n}
    pakai.update(row["references"])
    kode = row["code"] or row["name"]
    if row["stock_qty"] > 0:
        raise HTTPException(409, f'Master potongan "{kode}" tidak bisa dihapus karena masih ada stok '
                                 f'{row["stock_qty"]:g} {row["unit"]} di gudang. {SARAN_NONAKTIF}')
    tolak_bila_dipakai("Master potongan", kode, pakai)
    await db.rahaza_materials.delete_one({"id": panel_id, "is_cut_panel": True})
    await log_activity(user["id"], user.get("name", ""), "delete", "cutting.panels", kode)
    return {"ok": True, "deleted": True, "message": f"Master potongan {kode} dihapus."}


async def _input_material(db, material_id: str) -> dict:
    return await db.rahaza_materials.find_one(
        {"id": material_id},
        {"_id": 0, "id": 1, "code": 1, "name": 1, "unit": 1, "type": 1,
         "is_cut_panel": 1, "color": 1},
    ) or {}


def _roll_hint(rolls: list[dict], maxn: int = 4) -> str:
    bits = [f"{r.get('roll_no')} (sisa {fabric_roll_engine.remaining_of(r):,.2f} {r.get('uom', '')})"
            for r in rolls[:maxn]]
    return ", ".join(bits) + (" …" if len(rolls) > maxn else "")


_NO_ROLL_WAY_OUT = (
    "Jalan keluarnya: isi kolom Rincian Roll saat Penerimaan Barang, atau terbitkan "
    "gulungan untuk penerimaan yang sudah lewat di Gudang → Roll Kain → tab "
    "\"Penerimaan tanpa roll\"."
)


async def _assert_rolls_available(db, mat: dict, label: str) -> list[dict]:
    """FASE H-6: kain yang dilacak per gulungan harus PUNYA gulungan bersisa.

    Diperiksa saat order dibuat (gagal cepat) supaya operator tidak menyiapkan order
    yang pasti mentok saat lapor progres.
    """
    if not fabric_roll_engine.is_roll_material(mat):
        return []
    rolls = await fabric_roll_engine.open_rolls(db, mat["id"])
    if not rolls:
        raise HTTPException(400, (
            f"Kain {label} belum punya satu pun gulungan bersisa di sistem, jadi tidak akan "
            f"bisa dibuktikan gulungan mana yang dipotong. {_NO_ROLL_WAY_OUT}"))
    return rolls


async def _plan_roll_consumption(db, o: dict, line: dict, body: dict, input_used: float) -> tuple[list, dict]:
    """Rencana pemakaian gulungan SATU KAIN (`line` = baris `inputs[]`) untuk satu laporan progres (H-6).

    Dihitung SEBELUM stok dipotong: kalau gulungan yang dipilih tidak cukup atau
    tidak dipilih, laporan ditolak tanpa menyisakan stok yang sudah turun sebagian.
    Kembalian `plan` kosong HANYA bila materialnya memang tidak dilacak per gulungan
    (mis. potongan bersatuan pcs) — bukan karena rollnya lupa dipilih.
    """
    mat = await _input_material(db, line["input_material_id"])
    label = cutting_lines.input_label(line)
    if not fabric_roll_engine.is_roll_material(mat):
        return [], {"tracked": False}

    open_rolls = await fabric_roll_engine.open_rolls(db, line["input_material_id"])
    if not open_rolls:
        raise HTTPException(400, (
            f"Kain {label} belum punya satu pun gulungan bersisa di sistem, jadi tidak bisa "
            f"dibuktikan gulungan mana yang dipotong. {_NO_ROLL_WAY_OUT}"))

    picked = [str(x).strip() for x in (body.get("roll_ids") or []) if str(x or "").strip()]
    single = str(body.get("roll_id") or "").strip()
    if single and single not in picked:
        picked.append(single)
    if not picked:
        raise HTTPException(400, (
            f"Pilih gulungan yang dipotong untuk {label} — tanpa itu sisa gulungan di sistem "
            "akan menyimpang dari kenyataan dan lot kain tidak bisa dipertanggungjawabkan ke "
            f"buyer. Gulungan yang masih bersisa: {_roll_hint(open_rolls)}"))

    by_id = {r["id"]: r for r in open_rolls}
    by_no = {str(r.get("roll_no", "")): r for r in open_rolls}
    chosen, unknown = [], []
    for rid in picked:
        r = by_id.get(rid) or by_no.get(rid)
        if r and all(r["id"] != c["id"] for c in chosen):
            chosen.append(r)
        elif not r:
            unknown.append(rid)
    if unknown:
        others = await db.wh_fabric_rolls.find(
            {"$or": [{"id": {"$in": unknown}}, {"roll_no": {"$in": unknown}}]},
            {"_id": 0, "roll_no": 1, "material_code": 1, "status": 1},
        ).to_list(20)
        detail = "; ".join(
            f"{x.get('roll_no')} milik {x.get('material_code') or '?'} (status {x.get('status')})"
            for x in others) or "gulungan tidak dikenal"
        raise HTTPException(400, (
            f"Gulungan yang dipilih tidak bisa dipakai untuk {label}: {detail}. Pilih dari "
            f"gulungan kain ini yang masih bersisa: {_roll_hint(open_rolls)}"))

    # 2026-11-06 (Tahap 2): gulungan harus berada di gudang yang sama dengan lokasi stok order.
    far = await _roll_location_errors(db, chosen, o.get("location_id"))
    if far:
        raise HTTPException(400, (
            f"Gulungan {', '.join(far)} tercatat di gudang lain, bukan di {o.get('location_name') or 'gudang order'}. "
            "Stok kain dipotong dari gudang order, jadi gulungannya juga harus dari sana — pindahkan "
            "gulungannya dulu atau pilih gulungan di gudang ini."))
    # Urut nomor roll = FIFO penerimaan (gulungan tertua dipakai lebih dulu).
    chosen.sort(key=lambda r: str(r.get("roll_no", "")))
    unit_label = f" {chosen[0].get('uom', '')}" if chosen else ""
    plan = fabric_roll_engine.allocate(chosen, input_used, unit_label)
    return plan, {"tracked": True, "picked": [r["id"] for r in chosen],
                  "available": len(open_rolls),
                  "lots": {r["id"]: (r.get("color_lot") or r.get("color") or "") for r in chosen}}


async def _ensure_output_material(db, o: dict, user: dict) -> dict:
    """Buat / pakai-ulang master material POTONGAN untuk order ini (idempoten).

    2026-09-12 (keputusan owner): identitas potongan = model × warna × ukuran lewat SSOT
    `core.cut_panel_master` (`CUT-<MODEL>-<WARNA>-<UKURAN>`), sama dengan baris potongan di
    BOM produk — sehingga hasil cutting LANGSUNG menjadi bahan ber-HPP untuk BOM tersebut.
    """
    if o.get("output_material_id"):
        mat = await db.rahaza_materials.find_one({"id": o["output_material_id"]}, {"_id": 0})
        if mat:
            return mat
    code = (o.get("output_material_code") or "").strip().upper()
    if code:
        existing = await db.rahaza_materials.find_one({"code": code, "active": True}, {"_id": 0})
        if existing:
            return existing
    model = (await db.rahaza_models.find_one({"id": o.get("model_id")}, {"_id": 0}) if o.get("model_id") else None) \
        or {"id": o.get("model_id") or "", "code": o.get("style_sku") or o.get("model_code") or "PANEL",
            "name": o.get("style_name") or ""}
    color_code, color_name = await cut_panel_master.resolve_color(
        db, color_id=o.get("color_id") or None, color=o.get("output_color") or None)
    src = await db.rahaza_materials.find_one({"id": o.get("input_material_id")}, {"_id": 0}) or {}
    doc, created = await cut_panel_master.ensure_panel(
        db, model=model, color_code=color_code, color_name=color_name,
        size_code=o.get("output_size") or "", size_id=o.get("size_id") or None,
        source_fabric=src, created_from="cutting", cutting_order=o)
    if created:
        await log_activity(user["id"], user.get("name", ""), "create", "cutting.output_material", doc["code"])
    return doc


# ═════════════════════════════════════════════════════════════════════════════
# 2026-11-06 (Tahap 2) — IDENTITAS OUTPUT, LOKASI GULUNGAN, SATUAN OPERATOR
# ═════════════════════════════════════════════════════════════════════════════
CLOSED_PO_STATUSES = ("Closed", "Closed Short", "Completed", "Cancelled", "cancelled")


async def _po_line(db, po_item_id: str) -> tuple[dict, dict]:
    """Baris PO produksi (ukuran) yang dipotong — OPSIONAL, untuk BOM per ukuran."""
    it = await db.po_items.find_one({"id": po_item_id}, {"_id": 0})
    if not it:
        raise HTTPException(400, "Baris PO yang dipilih tidak ditemukan.")
    po = await db.production_pos.find_one({"id": it.get("po_id")}, {"_id": 0}) or {}
    if po.get("status") in CLOSED_PO_STATUSES:
        raise HTTPException(400, f"PO {po.get('po_number') or ''} sudah ditutup — tidak bisa dipakai untuk order cutting.")
    return it, po


async def _resolve_identity(db, *, model_id: str, body: dict, fabric: dict) -> dict:
    """Model × varian × UKURAN (wajib) × warna, potongan BOM, dan tautan baris PO (opsional).

    Tahap 2: dulu ukuran boleh kosong ⇒ hasil potong masuk master potongan TANPA ukuran yang
    tidak dipakai BOM mana pun, dan kode output yang diketik bisa menunjuk material apa pun.
    Satu penyelesai ini dipakai buat order DAN ubah order (ubah model = output ikut diganti)."""
    po_item, po = None, None
    pid = (body.get("po_item_id") or "").strip()
    if pid:
        po_item, po = await _po_line(db, pid)
        if not model_id:
            model_id = po_item.get("model_id") or ""
        elif po_item.get("model_id") and po_item["model_id"] != model_id:
            raise HTTPException(400, "Baris PO yang dipilih untuk model lain — pilih baris PO model ini.")
    if not model_id:
        raise HTTPException(400, (
            "Model/style wajib dipilih dari Master Produk — bukan diketik. "
            "Pilih model di dialog cutting, atau buat modelnya dulu lewat tombol "
            "\"Model Baru\" supaya BOM & produksi mengenali produk ini."))
    model = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0})
    if not model:
        raise HTTPException(404, "Model produk tidak ditemukan di master.")
    if model.get("active") is False:
        raise HTTPException(400, f"Model '{model.get('name')}' sudah non-aktif — pilih model lain.")
    variant = None
    variant_id = (body.get("variant_id") or "").strip() or ((po_item or {}).get("rahaza_variant_id") or "")
    if variant_id:
        variant = await db.rahaza_model_variants.find_one({"id": variant_id, "model_id": model_id}, {"_id": 0})
        if not variant:
            raise HTTPException(400, "Varian (warna/size) bukan milik model yang dipilih.")
    size_doc = None
    size_id_body = (body.get("size_id") or "").strip() or ((po_item or {}).get("size_id") or "")
    if not variant and size_id_body:
        size_doc = await db.rahaza_sizes.find_one({"id": size_id_body}, {"_id": 0})
        if not size_doc:
            raise HTTPException(400, "Ukuran tidak ditemukan di master ukuran.")
    size_id = (variant or {}).get("size_id") or (size_doc or {}).get("id") or ""
    output_size = ((variant or {}).get("size_code") or (size_doc or {}).get("code") or "").strip()
    if not size_id or not output_size:
        raise HTTPException(400, (
            "Ukuran wajib dipilih (lewat varian warna·ukuran, ukuran BOM, atau baris PO). Tanpa ukuran, "
            "potongan masuk master tanpa ukuran yang tidak dipakai BOM mana pun."))
    if po_item and po_item.get("size_id") and po_item["size_id"] != size_id:
        raise HTTPException(400, "Ukuran yang dipilih berbeda dengan ukuran baris PO.")
    output_color = ((variant or {}).get("color_name") or (variant or {}).get("color")
                    or body.get("output_color") or (po_item or {}).get("color") or fabric.get("color") or "").strip()
    bom_panel = None
    _bom = await product_costing.find_active_bom(
        db, model_id, size_id, product_costing.color_of(variant) or output_color)
    for _ln in (_bom or {}).get("materials") or []:
        if cut_panel_master.is_panel_line(_ln):
            bom_panel = await db.rahaza_materials.find_one(
                {"id": _ln.get("material_id"), "active": True}, {"_id": 0, "id": 1, "code": 1, "name": 1})
            if bom_panel:
                break
    typed = (body.get("output_material_code") or "").strip().upper()
    typed_panel = None
    if typed and not bom_panel:
        # Kode ketikan hanya sah bila menunjuk POTONGAN model & ukuran ini (dulu material apa pun).
        cand = await db.rahaza_materials.find_one({"code": typed, "active": True}, {"_id": 0})
        if (not cand or not cand.get("is_cut_panel")
                or (cand.get("model_id") and cand["model_id"] != model_id)
                or (cand.get("size_code") and str(cand["size_code"]).upper() != output_size.upper())):
            raise HTTPException(400, (
                f"Kode potongan '{typed}' bukan potongan model {model.get('code') or ''} ukuran {output_size}. "
                "Kosongkan kodenya — sistem membuat kode potongan yang benar saat cutting dimulai."))
        typed_panel = {"id": cand["id"], "code": cand.get("code"), "name": cand.get("name")}
    panel = bom_panel or typed_panel
    return {
        "style_sku": (model.get("code") or "").strip(), "style_name": (model.get("name") or "").strip(),
        "model_id": model_id, "model_code": (model.get("code") or "").strip(),
        "model_name": (model.get("name") or "").strip(),
        "variant_id": (variant or {}).get("id") or "", "variant_sku": (variant or {}).get("sku") or "",
        "size_id": size_id, "color_id": (variant or {}).get("color_id") or "",
        "output_color": output_color, "output_size": output_size,
        "output_material_id": (panel or {}).get("id"),
        "output_material_code": (panel or {}).get("code") or "",
        "output_material_name": (panel or {}).get("name") or "",
        "output_from_bom": bool(bom_panel),
        "po_item_id": (po_item or {}).get("id") or "", "po_id": (po_item or {}).get("po_id") or "",
        "po_number": (po or {}).get("po_number") or (po_item or {}).get("po_number") or "",
    }


async def _place_of(db, location_id: Optional[str]) -> str:
    """Zona kanonik sebuah lokasi (bin → zonanya; lokasi lama → zona petanya)."""
    from core import location_resolver
    if not location_id:
        return ""
    canon = await location_resolver.to_canonical_location_id(db, location_id)
    pos = await db.wh_positions.find_one({"id": canon}, {"_id": 0, "zone_id": 1})
    return (pos or {}).get("zone_id") or canon


async def _roll_location_errors(db, rolls: list, order_location_id: str) -> list:
    """Gulungan yang tercatat di gudang LAIN dari lokasi stok order cutting (Tahap 2)."""
    want = await _place_of(db, order_location_id)
    bad = []
    for r in rolls:
        loc = r.get("location_id") or r.get("position_id") or ""
        if loc and want and await _place_of(db, loc) != want:
            bad.append(f"{r.get('roll_no')} ({r.get('location_name') or 'lokasi lain'})")
    return bad


def _to_order_unit(mat: dict, qty: float, uom: str, order_uom: str) -> tuple[float, Optional[dict]]:
    """Qty dalam satuan operator (gram, yard, …) → satuan order. Return (qty, jejak|None)."""
    op = (uom or "").strip().lower()
    order_uom = (order_uom or "").strip().lower()
    if not op or op == order_uom or qty == 0:
        return qty, None
    f_op, _b, st_op, note_op = _bom_uom.line_factor(mat, op)
    if st_op not in ("base", "uom", "global", "fabric"):
        raise HTTPException(400, note_op or f"Satuan '{op}' tidak bisa dikonversi ke '{order_uom}'.")
    f_ord, _b2, st_ord, _n = _bom_uom.line_factor(mat, order_uom)
    if st_ord not in ("base", "uom", "global", "fabric") or not f_ord:
        f_ord = 1.0
    converted = round(float(qty) * float(f_op) / float(f_ord), 4)
    return converted, {"input_qty": qty, "input_uom": op, "qty_order_unit": converted,
                       "order_unit": order_uom, "factor": float(f_op), "source": st_op}


# ═════════════════════════════════════════════════════════════════════════════
# CRUD ORDER
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/orders")
async def list_orders(request: Request, status: Optional[str] = None,
                      q: Optional[str] = None, limit: int = 200, skip: int = 0):
    await require_auth(request)
    db = get_db()
    query: dict = {}
    if status:
        query["status"] = status
    if q:
        query["$or"] = [
            {"number": {"$regex": q, "$options": "i"}},
            {"style_name": {"$regex": q, "$options": "i"}},
            {"style_sku": {"$regex": q, "$options": "i"}},
            {"input_material_name": {"$regex": q, "$options": "i"}},
            {"output_material_code": {"$regex": q, "$options": "i"}},
            # 2026-11-10: order banyak baris — cari juga di baris kain & hasil
            {"inputs.input_material_name": {"$regex": q, "$options": "i"}},
            {"inputs.input_material_code": {"$regex": q, "$options": "i"}},
            {"outputs.style_name": {"$regex": q, "$options": "i"}},
            {"outputs.output_material_code": {"$regex": q, "$options": "i"}},
            {"outputs.variant_sku": {"$regex": q, "$options": "i"}},
        ]
    rows = await db[ORDERS].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(500)
    for r in rows:
        await _enrich(db, r)
    return serialize_doc(rows)


def summarize_cutting_units(rows: list, totals: Optional[dict] = None) -> dict:
    """Ringkas hasil `$group` per satuan kain (murni; dipakai dashboard Cutting & Produksi).

    Tahap 1 (6 Nov 2026): dulu kain terpakai, sisa, dan yield seluruh order DIJUMLAH
    walau satuannya berbeda (kg + yard + meter = angka tanpa arti), dan order BATAL ikut
    masuk rencana. Sekarang angka kain per satuan (`by_unit`); angka tunggal hanya diisi
    bila semua order memakai satu satuan, selain itu None. Potongan (pcs) tetap dijumlah.

    2026-11-10: order banyak kain berbeda satuan muncul di tiap satuannya (pcs per satuan kain), jadi total
    rencana/hasil pcs dikirim terpisah lewat `totals` ({planned, produced}) supaya tidak terhitung dua kali."""
    units: dict = {}
    planned = produced = 0.0
    for r in rows or []:
        u = str(r.get("_id") or "").strip().lower() or "-"
        x = units.setdefault(u, {"unit": u, "orders": 0, "consumed": 0.0, "waste": 0.0, "produced": 0.0})
        x["orders"] += int(r.get("n") or 0)
        x["consumed"] += _f(r.get("consumed"))
        x["waste"] += _f(r.get("waste"))
        x["produced"] += _f(r.get("produced"))
        planned += _f(r.get("planned"))
        produced += _f(r.get("produced"))
    by_unit = []
    for x in sorted(units.values(), key=lambda v: -v["consumed"]):
        by_unit.append({"unit": x["unit"], "orders": x["orders"],
                        "consumed": round(x["consumed"], 3), "waste": round(x["waste"], 3),
                        "produced": round(x["produced"], 2),
                        "yield": round(x["produced"] / x["consumed"], 3) if x["consumed"] > 0 else None})
    single = by_unit[0] if len(by_unit) == 1 else None
    if totals is not None:
        planned, produced = _f(totals.get("planned")), _f(totals.get("produced"))
    return {"planned_output": round(planned, 2), "produced": round(produced, 2), "by_unit": by_unit,
            "consumed": single["consumed"] if single else None,
            "waste": single["waste"] if single else None,
            "yield": single["yield"] if single else None}


async def cutting_unit_totals(db) -> dict:
    """Total order cutting yang TIDAK batal, dipisah per satuan kain.

    2026-11-10: kain per satuan dibaca dari `unit_totals` order (satu entri per satuan, ditulis
    `cutting_lines.compat_fields`); dokumen lama tanpa `unit_totals` memakai field tingkat atasnya."""
    match = {"$match": {"status": {"$ne": STATUS_CANCELLED}}}
    rows = await db[ORDERS].aggregate([
        match,
        {"$project": {"produced": {"$ifNull": ["$produced_qty", 0]},
                      "ut": {"$ifNull": ["$unit_totals", [{"unit": "$input_unit",
                                                           "consumed": "$consumed_input_qty",
                                                           "waste": "$waste_qty"}]]}}},
        {"$unwind": "$ut"},
        {"$group": {"_id": "$ut.unit", "n": {"$sum": 1},
                    "produced": {"$sum": "$produced"},
                    "consumed": {"$sum": "$ut.consumed"},
                    "waste": {"$sum": "$ut.waste"}}},
    ]).to_list(50)
    tot = await db[ORDERS].aggregate([
        match,
        {"$group": {"_id": None, "planned": {"$sum": "$planned_output_qty"},
                    "produced": {"$sum": "$produced_qty"}}},
    ]).to_list(1)
    return summarize_cutting_units(rows, totals=(tot[0] if tot else {"planned": 0, "produced": 0}))


@router.get("/dashboard")
async def dashboard(request: Request):
    await require_auth(request)
    db = get_db()
    by_status = {}
    cur = db[ORDERS].aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}])
    async for r in cur:
        by_status[r["_id"]] = r["n"]
    tot = await cutting_unit_totals(db)
    panels = await db.rahaza_materials.count_documents({"is_cut_panel": True, "active": True})
    recent = await db[ORDERS].find({}, {"_id": 0}).sort("created_at", -1).limit(5).to_list(5)
    return serialize_doc({
        "total_orders": sum(by_status.values()),
        "by_status": {
            "draft": by_status.get(STATUS_DRAFT, 0),
            "in_progress": by_status.get(STATUS_IN_PROGRESS, 0),
            "completed": by_status.get(STATUS_COMPLETED, 0),
            "cancelled": by_status.get(STATUS_CANCELLED, 0),
        },
        # order batal tidak dihitung; kain/sisa/yield per satuan (`by_unit`)
        "planned_output_qty": tot["planned_output"],
        "produced_qty": tot["produced"],
        "consumed_input_qty": tot["consumed"],
        "waste_qty": tot["waste"],
        "avg_yield": tot["yield"],
        "by_unit": tot["by_unit"],
        "output_material_count": panels,
        "recent": recent,
    })


# ═════════════════════════════════════════════════════════════════════════════
# FASE H-6b — DOKUMEN PENGELUARAN MATERIAL UNTUK ARUS KELUAR CUTTING
# CATATAN URUTAN ROUTE (pelajaran sesi #16): dua route literal di bawah HARUS
# dideklarasikan SEBELUM `GET /orders/{oid}` — bukan karena bentrok segmen
# pertama, tetapi supaya kebiasaan "literal sebelum ber-parameter" tidak pernah
# dilanggar di berkas ini.
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/issue-docs/missing")
async def list_progress_without_issue_doc(request: Request, limit: int = 200,
                                          order_id: Optional[str] = None):
    """Progres cutting yang kainnya SUDAH keluar tetapi belum punya dokumen MI.

    Read-only (kecuali memulihkan tautan yang hilang — lihat docstring engine).
    Dipakai kartu "Progres tanpa dokumen MI" di Portal Cutting.
    """
    await require_auth(request)
    db = get_db()
    out = await cutting_material_issue.progress_without_doc(
        db, limit=limit, order_id=order_id)
    return serialize_doc(out)


@router.post("/issue-docs/backfill")
async def backfill_issue_docs(request: Request):
    """Terbitkan dokumen MI retroaktif untuk progres cutting lama (idempoten).

    TIDAK memotong stok: kain sudah berkurang saat progres dilaporkan.
    """
    user = await _require_cutting_user(request)
    db = get_db()
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — body OPSIONAL (tombol tanpa argumen)
        body = {}
    res = await cutting_material_issue.backfill(
        db, user, limit=int((body or {}).get("limit") or 500),
        order_id=(body or {}).get("order_id") or None)
    if res.get("created"):
        await log_activity(user["id"], user.get("name", ""), "backfill_mi",
                           "cutting.issue_docs", f"{res['created']} dokumen")
    return serialize_doc(res)


@router.get("/rolls/{roll_id}/usage")
async def roll_usage(roll_id: str, request: Request):
    """Satu gulungan dipakai untuk hasil potongan apa (2026-11-10, permintaan owner: "roll kain ini dipakai buat
    membuat potongan apa"). Read-only; dipakai rincian order cutting dan bisa dipanggil layar Roll Kain."""
    await require_auth(request)
    db = get_db()
    rows = await db[ORDERS].find(
        {"$or": [{"inputs.roll_ids.roll_id": roll_id}, {"roll_ids.roll_id": roll_id}]}, {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    items = []
    for o in rows:
        for u in cutting_lines.roll_usage(o):
            if u["roll_id"] == roll_id:
                items.append({**u, "cutting_order_id": o.get("id"), "cutting_number": o.get("number", ""),
                              "status": o.get("status", ""), "dipakai_untuk": cutting_lines.roll_usage_text(u)})
    return serialize_doc({"roll_id": roll_id, "items": items, "total": len(items),
                          "dipakai_untuk": "; ".join(f"{x['cutting_number']}: {x['dipakai_untuk']}" for x in items)})


async def _hpp_summary(db, o: dict) -> dict:
    """Ringkasan HPP order: biaya kain nyata ÷ pcs jadi, dan perkiraan dari rencana (harga kain sekarang)."""
    totals = await cut_panel_value.order_value_totals(db, o["id"])
    ins, outs = cutting_lines.inputs_of(o), cutting_lines.outputs_of(o)
    produced = sum(_f(x.get("produced_qty")) for x in outs)
    planned_pcs = sum(_f(x.get("planned_output_qty")) for x in outs)
    est, missing = 0.0, []
    for i in ins:
        m = await db.rahaza_materials.find_one({"id": i.get("input_material_id")}, {"_id": 0, "unit_cost": 1}) or {}
        cost = _f(m.get("unit_cost")) or _f(i.get("input_unit_cost"))
        if cost <= 0:
            missing.append(i.get("input_material_code") or i.get("input_material_name") or "")
        est += _f(i.get("planned_input_qty")) * cost
    value_total = _f(totals.get("value_total"))
    return {"value_total": round(value_total, 2), "produced": round(produced, 4),
            "per_pcs": cutting_lines.cost_per_pcs(value_total, produced),
            "estimate_total": round(est, 2), "planned_pcs": round(planned_pcs, 4),
            "estimate_per_pcs": cutting_lines.cost_per_pcs(est, planned_pcs),
            "missing_price": [x for x in missing if x]}


@router.get("/orders/{oid}")
async def get_order(oid: str, request: Request):
    await require_auth(request)
    db = get_db()
    o = await _get_order(db, oid)
    await _enrich(db, o)
    o["progress"] = await db[PROGRESS].find(
        {"cutting_order_id": oid}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    # 2026-11-10: stok per baris kain & per baris hasil
    for i in o["inputs"]:
        if i.get("input_material_id"):
            i["input_stock"] = round(_f(await stock_service.get_onhand(i["input_material_id"], db=db)), 4)
    for x in o["outputs"]:
        if x.get("output_material_id"):
            om = await db.rahaza_materials.find_one(
                {"id": x["output_material_id"]}, {"_id": 0, "id": 1, "unit_cost": 1, "value_status": 1})
            if om:
                x["output_stock"] = round(_f(await stock_service.get_onhand(om["id"], db=db)), 4)
                x["panel_unit_cost"] = round(_f(om.get("unit_cost")), 2)
    if o.get("output_material_id"):
        om = await db.rahaza_materials.find_one({"id": o["output_material_id"]}, {"_id": 0})
        if om:
            o["output_material"] = om
            o["output_stock"] = round(_f(await stock_service.get_onhand(om["id"], db=db)), 4)
    if o.get("input_material_id"):
        o["input_stock"] = round(_f(await stock_service.get_onhand(o["input_material_id"], db=db)), 4)
    o["hpp_summary"] = await _hpp_summary(db, o)
    return serialize_doc(o)


# ═════════════════════════════════════════════════════════════════════════════
# 2026-11-10 — BARIS KAIN & BARIS HASIL (dipakai buat & ubah order)
# ═════════════════════════════════════════════════════════════════════════════
_OUTPUT_KEYS = ("model_id", "variant_id", "size_id", "po_item_id", "output_color", "output_material_code")
_LEGACY_IDENTITY_KEYS = ("model_id", "variant_id", "size_id", "po_item_id")


def _body_lines(body: dict) -> tuple[list, list]:
    """Body baru (`inputs[]`/`outputs[]`) atau body LAMA (satu kain + satu hasil di tingkat atas) → daftar baris."""
    ins = body.get("inputs") if isinstance(body.get("inputs"), list) else None
    outs = body.get("outputs") if isinstance(body.get("outputs"), list) else None
    if ins is None:
        ins = ([{"input_material_id": body.get("input_material_id"),
                 "planned_input_qty": body.get("planned_input_qty"),
                 "roll_ids": body.get("roll_ids") or []}]
               if (body.get("input_material_id") or "").strip() else [])
    if outs is None:
        outs = [{**{k: body.get(k) for k in _OUTPUT_KEYS if k in body},
                 "planned_output_qty": body.get("planned_output_qty")}]
    return ins, outs


def _prefixed(e: HTTPException, prefix: str) -> HTTPException:
    return HTTPException(e.status_code, f"{prefix}{e.detail}") if prefix else e


async def _build_inputs(db, raw: list, loc_id: str, loc_name: str) -> list[dict]:
    """Validasi & susun baris KAIN: kain wajib dari master, satuan kain roll, rencana > 0, gulungan bersisa wajib
    untuk kain yang dilacak per gulungan, gulungan terpilih harus milik kain itu & di gudang order."""
    if not raw:
        raise HTTPException(400, "Material kain (input) wajib dipilih.")
    many = len(raw) > 1
    out, seen = [], set()
    for n, r in enumerate(raw, 1):
        pre = f"Kain baris {n}: " if many else ""
        mid = str((r or {}).get("input_material_id") or "").strip()
        if not mid:
            raise HTTPException(400, f"{pre}Material kain (input) wajib dipilih.")
        mat = await db.rahaza_materials.find_one({"id": mid, "active": True}, {"_id": 0})
        if not mat:
            raise HTTPException(404, f"{pre}Material kain tidak ditemukan / tidak aktif.")
        if mid in seen:
            raise HTTPException(400, (
                f"Kain {mat.get('code') or ''} dipilih dua kali — gabungkan jadi satu baris kain "
                "(gulungannya boleh dicentang lebih dari satu)."))
        seen.add(mid)
        if mat.get("is_cut_panel"):
            raise HTTPException(400, f"{pre}Material yang dipilih adalah POTONGAN, bukan kain roll.")
        unit = (mat.get("unit") or "").lower()
        if unit not in INPUT_UNITS:
            raise HTTPException(
                400, f"{pre}Satuan material '{unit}' bukan satuan kain roll ({sorted(INPUT_UNITS)}).")
        planned = _f(r.get("planned_input_qty"))
        if planned <= 0:
            raise HTTPException(400, f"{pre}Rencana pemakaian kain harus > 0.")
        avail_total = _f(await stock_service.get_onhand(mat["id"], db=db))
        stock_here = next((x["qty"] for x in await _stock_locations(db, mat["id"])
                           if x["location_id"] == loc_id), 0.0)
        # FASE H-6: kain yang dilacak per gulungan harus punya gulungan bersisa SEBELUM
        # order dibuat — gagal cepat lebih baik daripada order yang mentok saat progres.
        open_rolls = await _assert_rolls_available(db, mat, f"{mat.get('code')} — {mat.get('name')}")
        roll_docs: list = []
        rolls_in = r.get("roll_ids") or []
        if rolls_in:
            by_id = {x["id"]: x for x in open_rolls}
            by_no = {str(x.get("roll_no", "")): x for x in open_rolls}
            unknown = []
            for rid in rolls_in:
                rid = rid.get("roll_id") if isinstance(rid, dict) else rid
                x = by_id.get(str(rid)) or by_no.get(str(rid))
                if not x:
                    unknown.append(str(rid))
                    continue
                if any(d["roll_id"] == x["id"] for d in roll_docs):
                    continue
                roll_docs.append({
                    "roll_id": x["id"], "roll_no": x.get("roll_no", ""),
                    "uom": x.get("uom", ""), "color_lot": x.get("color_lot") or x.get("color") or "",
                    "remaining": round(fabric_roll_engine.remaining_of(x), 3),
                    "consumed_qty": 0.0,
                })
            if unknown:
                raise HTTPException(400, (
                    f"{pre}Gulungan {', '.join(unknown)} bukan milik kain {mat.get('code')} atau sudah "
                    f"habis. Gulungan yang bisa dipilih: {_roll_hint(open_rolls)}"))
            far = await _roll_location_errors(db, [by_id[d["roll_id"]] for d in roll_docs], loc_id)
            if far:
                raise HTTPException(400, (
                    f"{pre}Gulungan {', '.join(far)} tercatat di gudang lain, bukan di "
                    f"{loc_name or 'gudang sumber kain'}. Pindahkan gulungannya dulu (transfer) atau pilih "
                    "gulungan di gudang ini."))
            picked_total = sum(d["remaining"] for d in roll_docs)
            if picked_total + 0.0001 < planned:
                raise HTTPException(400, (
                    f"{pre}Sisa gulungan terpilih {picked_total:,.2f} {roll_docs[0]['uom']} lebih kecil "
                    f"dari rencana pemakaian {planned:,.2f} {unit}. Tambah gulungan atau "
                    "turunkan rencana pemakaiannya."))
        out.append({
            "line_id": f"in-{n}",
            "input_material_id": mat["id"],
            "input_material_code": mat.get("code", ""),
            "input_material_name": mat.get("name", ""),
            "input_unit": unit,
            "input_color": mat.get("color", ""),
            "input_unit_cost": _f(mat.get("unit_cost")),
            "planned_input_qty": round(planned, 4),
            "consumed_input_qty": 0.0, "waste_qty": 0.0, "leftover_qty": 0.0,
            # tidak memilih gulungan di awal masih boleh (dipilih saat lapor progres), tetapi order
            # menyimpan pengingat bahwa gulungan WAJIB ditunjuk nanti (`roll_required`).
            "roll_ids": roll_docs,
            "roll_required": bool(open_rolls),
            "stock_at_create": round(stock_here, 4),
            "stock_total_at_create": round(avail_total, 4),
        })
    return out


def _link_rolls(raw_ids, inputs: list[dict], prefix: str = "") -> list[str]:
    """Gulungan yang dipakai untuk satu baris hasil = bagian dari gulungan yang dipilih di baris kain order."""
    pool = {rr["roll_id"]: rr for i in inputs for rr in (i.get("roll_ids") or [])}
    by_no = {str(rr.get("roll_no") or ""): rid for rid, rr in pool.items()}
    out, unknown = [], []
    for v in raw_ids or []:
        rid = str(v.get("roll_id") if isinstance(v, dict) else v or "").strip()
        if not rid:
            continue
        rid = rid if rid in pool else by_no.get(rid, "")
        if not rid:
            unknown.append(str(v))
        elif rid not in out:
            out.append(rid)
    if unknown:
        raise HTTPException(400, (
            f"{prefix}Gulungan {', '.join(unknown)} tidak dipilih di bagian Kain & gulungan order ini — "
            "centang dulu gulungannya di baris kain."))
    return out


async def _build_outputs(db, raw: list, inputs: list[dict]) -> list[dict]:
    """Validasi & susun baris HASIL: model wajib dari master, ukuran wajib, target > 0, baris PO opsional,
    tidak ada dua baris hasil yang sama, gulungan dipakai ⊆ gulungan order (satu baris hasil = semua gulungan)."""
    raw = raw or [{}]
    many = len(raw) > 1
    fabric = {}
    if inputs:
        fabric = await db.rahaza_materials.find_one({"id": inputs[0]["input_material_id"]}, {"_id": 0}) or {}
    out, seen = [], set()
    for n, r in enumerate(raw, 1):
        r = r or {}
        pre = f"Hasil baris {n}: " if many else ""
        planned = _f(r.get("planned_output_qty"))
        if planned <= 0:
            raise HTTPException(400, f"{pre}Rencana hasil potongan (pcs) harus > 0.")
        try:
            ident = await _resolve_identity(db, model_id=str(r.get("model_id") or "").strip(),
                                            body=r, fabric=fabric)
        except HTTPException as e:
            raise _prefixed(e, pre)
        key = (ident["model_id"], ident["variant_id"], ident["size_id"],
               (ident["output_color"] or "").lower(), ident["po_item_id"])
        if key in seen:
            raise HTTPException(400, (
                f"{pre}Hasil yang sama (model · varian · ukuran · baris PO) sudah ada di baris lain — "
                "gabungkan target pcs-nya di satu baris."))
        seen.add(key)
        out.append({"line_id": f"out-{n}", **ident, "planned_output_qty": round(planned, 4),
                    "produced_qty": 0.0, "output_unit_cost": 0.0,
                    "roll_ids": _link_rolls(r.get("roll_ids"), inputs, pre)})
    if len(out) == 1:   # satu hasil: semua gulungan order memang dipakai untuk hasil itu
        out[0]["roll_ids"] = [rr["roll_id"] for i in inputs for rr in (i.get("roll_ids") or [])]
    return out


def _relink_outputs(outputs: list[dict], inputs: list[dict]) -> list[dict]:
    """Setelah baris kain berubah: buang tautan ke gulungan yang tidak lagi dipilih (satu hasil = semua)."""
    pool = [rr["roll_id"] for i in inputs for rr in (i.get("roll_ids") or [])]
    for x in outputs:
        x["roll_ids"] = list(pool) if len(outputs) == 1 else [r for r in (x.get("roll_ids") or []) if r in pool]
    return outputs


def _source_fabric_id(line: dict, inputs: list[dict]) -> str:
    """Kain asal sebuah hasil (dicatat di master potongan): kain dari gulungan yang ditautkan, selain itu kain pertama."""
    linked = set(line.get("roll_ids") or [])
    for i in inputs:
        if linked & {rr.get("roll_id") for rr in (i.get("roll_ids") or [])}:
            return i.get("input_material_id") or ""
    return (inputs[0].get("input_material_id") or "") if inputs else ""


# ═════════════════════════════════════════════════════════════════════════════
# CRUD ORDER (lanjutan)
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/orders")
async def create_order(request: Request):
    """Buat order cutting (draf). 2026-11-10: `inputs[]` (kain + gulungan, boleh banyak) dan `outputs[]` (model ×
    varian × target pcs + baris PO opsional, boleh banyak); body lama satu-kain/satu-hasil tetap diterima."""
    user = await _require_cutting_user(request)
    db = get_db()
    body = await request.json()
    raw_in, raw_out = _body_lines(body)
    if not raw_in:
        raise HTTPException(400, "Material kain (input) wajib dipilih.")
    # ── STYLE/PRODUK WAJIB DARI MASTER (keputusan pemilik 2026-08-21) ─────────
    # 2026-11-06 (Tahap 2): model × varian × UKURAN (wajib) × warna + potongan BOM + baris PO
    # (opsional) diselesaikan satu fungsi `_resolve_identity` (dipakai juga oleh ubah order).
    loc_id, loc_name = await _default_location(db, body.get("location_id"))
    inputs = await _build_inputs(db, raw_in, loc_id, loc_name)
    outputs = await _build_outputs(db, raw_out, inputs)

    number = await gen_prefixed_number(db, ORDERS, "number", f"CUT-{_now():%Y}-", 4)
    doc = {
        "id": _uid(),
        "number": number,
        "status": STATUS_DRAFT,
        "location_id": loc_id,
        "location_name": loc_name,
        "inputs": inputs,
        "outputs": outputs,
        # field lama tingkat atas (kompatibel) — order satu baris persis seperti dulu
        **cutting_lines.compat_fields(inputs, outputs),
        "output_unit": OUTPUT_UNIT,
        "output_unit_cost": 0.0,
        # meta
        "target_date": body.get("target_date") or None,
        "notes": body.get("notes") or "",
        "created_by": user["id"], "created_by_name": user.get("name", ""),
        "created_at": _now(), "updated_at": _now(),
        "started_at": None, "completed_at": None,
    }
    await db[ORDERS].insert_one(dict(doc))
    await log_activity(user["id"], user.get("name", ""), "create", "cutting.order", number)
    await _enrich(db, doc)
    return serialize_doc(doc)


@router.put("/orders/{oid}")
async def update_order(oid: str, request: Request):
    user = await _require_cutting_user(request)
    db = get_db()
    o = await _get_order(db, oid)
    if o["status"] != STATUS_DRAFT:
        raise HTTPException(400, "Hanya cutting berstatus draft yang bisa diubah.")
    body = await request.json()
    ins, outs = cutting_lines.inputs_of(o), cutting_lines.outputs_of(o)
    extra: dict = {}
    if "location_id" in body:
        extra["location_id"], extra["location_name"] = await _default_location(db, body.get("location_id"))
    loc_id = extra.get("location_id", o.get("location_id") or "")
    loc_name = extra.get("location_name", o.get("location_name") or "")
    if isinstance(body.get("inputs"), list) or isinstance(body.get("outputs"), list):
        # 2026-11-10: ubah lewat daftar baris (form yang sama dengan buat order)
        if isinstance(body.get("inputs"), list):
            ins = await _build_inputs(db, body["inputs"], loc_id, loc_name)
        if isinstance(body.get("outputs"), list):
            outs = await _build_outputs(db, body["outputs"], ins)
        else:
            outs = _relink_outputs(outs, ins)
    else:
        # Style/produk hanya boleh berganti lewat MASTER (model + varian) — bukan
        # ketikan bebas, agar order draft tidak bisa "lepas" dari master produk.
        # 2026-11-06 (Tahap 2): ganti model/varian/ukuran/baris PO = identitas DAN output dihitung
        # ulang (dulu output model lama tertinggal ⇒ hasil potong masuk potongan model lama).
        if any(k in body for k in _LEGACY_IDENTITY_KEYS):
            if len(outs) != 1:
                raise HTTPException(400, "Order ini punya beberapa baris hasil — ubah lewat daftar baris hasil.")
            cur = outs[0]
            merged = {"variant_id": cur.get("variant_id"), "size_id": cur.get("size_id"),
                      "po_item_id": cur.get("po_item_id"), "output_color": cur.get("output_color"),
                      **{k: body.get(k) for k in ("variant_id", "size_id", "po_item_id", "output_color",
                                                 "output_material_code") if k in body}}
            if "model_id" in body and (body.get("model_id") or "") != (cur.get("model_id") or ""):
                # model berganti: varian/ukuran/baris PO lama tidak berlaku lagi kecuali dikirim ulang
                for k in ("variant_id", "size_id", "po_item_id"):
                    if k not in body:
                        merged[k] = ""
            fabric = (await db.rahaza_materials.find_one({"id": ins[0]["input_material_id"]}, {"_id": 0})
                      if ins else None) or {}
            ident = await _resolve_identity(
                db, model_id=(body.get("model_id") if "model_id" in body else cur.get("model_id")) or "",
                body=merged, fabric=fabric)
            cur.update(ident)
        elif any(k in body for k in ("style_name", "style_sku", "output_material_code")):
            raise HTTPException(400, (
                "Nama style / kode potongan tidak bisa diketik langsung — kirim `model_id` dari Master "
                "Produk supaya BOM & produksi tetap mengenali produknya."))
        if "planned_input_qty" in body:
            if len(ins) != 1:
                raise HTTPException(400, "Order ini memakai beberapa kain — ubah rencana lewat daftar baris kain.")
            v = _f(body["planned_input_qty"])
            if v <= 0:
                raise HTTPException(400, "Rencana pemakaian kain harus > 0.")
            ins[0]["planned_input_qty"] = round(v, 4)
        if "planned_output_qty" in body:
            if len(outs) != 1:
                raise HTTPException(400, "Order ini punya beberapa baris hasil — ubah target lewat daftar baris hasil.")
            v = _f(body["planned_output_qty"])
            if v <= 0:
                raise HTTPException(400, "Rencana hasil potongan harus > 0.")
            outs[0]["planned_output_qty"] = round(v, 4)
    for k in ("notes", "target_date"):
        if k in body:
            extra[k] = (body.get(k) or "") if isinstance(body.get(k), str) else body.get(k)
    await _save_lines(db, oid, ins, outs, extra)
    await log_activity(user["id"], user.get("name", ""), "update", "cutting.order", o["number"])
    return serialize_doc(await _enrich(db, await _get_order(db, oid)))


def _panel_notice(res_panel: Optional[dict]) -> str:
    if res_panel and res_panel.get("removed"):
        return f"Master potongan {res_panel['code']} ikut dibersihkan (belum pernah dipakai)."
    if res_panel and res_panel.get("reason"):
        return f"Master potongan {res_panel['code']} DIPERTAHANKAN — {res_panel['reason']}"
    return ""


@router.delete("/orders/{oid}")
async def delete_order(oid: str, request: Request):
    user = await _require_cutting_user(request)
    db = get_db()
    o = await _get_order(db, oid)
    if o["status"] != STATUS_DRAFT:
        raise HTTPException(400, "Hanya draft yang bisa dihapus. Gunakan Batalkan untuk yang lain.")
    # SESI #32 — penjaga yang sama seperti `cancel`: draft yang (karena data lama)
    # sudah punya master potongan tidak boleh meninggalkannya jadi yatim.
    notes = []
    for x in cutting_lines.outputs_of(o):
        res_panel = await cut_panel_health.remove_if_unused(
            db, panel_id=x.get("output_material_id") or "", order_id=oid, user=user)
        if _panel_notice(res_panel):
            notes.append(_panel_notice(res_panel))
    await db[ORDERS].delete_one({"id": oid})
    await log_activity(user["id"], user.get("name", ""), "delete", "cutting.order", o["number"])
    out = {"ok": True}
    if notes:
        out["notice"] = " ".join(notes)
    return out


# ═════════════════════════════════════════════════════════════════════════════
# STATE TRANSITIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/orders/{oid}/start")
async def start_order(oid: str, request: Request):
    """draft ➜ in_progress. Sekalian membuat master material POTONGAN tiap baris hasil."""
    user = await _require_cutting_user(request)
    db = get_db()
    o = await _get_order(db, oid)
    if o["status"] != STATUS_DRAFT:
        raise HTTPException(400, f"Status '{o['status']}' tidak bisa di-start.")
    ins, outs = cutting_lines.inputs_of(o), cutting_lines.outputs_of(o)

    # VALIDASI PER-LOKASI (perbaikan bug QA-1): stok disimpan per (material, lokasi),
    # sementara dulu di sini hanya dicek TOTAL lintas lokasi. Akibatnya order lolos
    # start tapi gagal saat progress ("tersedia 0.0") karena lokasi order ternyata
    # bukan lokasi yang memegang stok. Sekarang: kalau lokasi order kosong tapi ada
    # gudang lain yang punya stok, order otomatis diarahkan ke gudang tersebut.
    # 2026-11-10: diperiksa per KAIN; banyak kain harus bisa diambil dari SATU gudang yang sama.
    spread: list = []
    for i in ins:
        locs = await _stock_locations(db, i["input_material_id"])
        if sum(x["qty"] for x in locs) <= 0:
            raise HTTPException(
                400, f"Stok kain {i.get('input_material_code')} kosong di semua gudang "
                     f"(0 {i.get('input_unit')}). Catat penerimaan barang di Gudang dulu.")
        spread.append((i, locs))
    moved_to = None
    if any(not any(x["location_id"] == o.get("location_id") for x in locs) for _i, locs in spread):
        if len(spread) == 1:
            best = spread[0][1][0]
        else:
            common = set.intersection(*[{x["location_id"] for x in locs} for _i, locs in spread])
            if not common:
                where = "; ".join(
                    f"{i.get('input_material_code')}: " + ", ".join(f"{x['location_name']} {x['qty']:g}" for x in locs)
                    for i, locs in spread)
                raise HTTPException(400, (
                    f"Kain order ini tidak ada di satu gudang yang sama ({where}). Pindahkan kainnya ke satu "
                    "gudang dulu (transfer), lalu mulai lagi."))
            def _min_qty(lid: str) -> float:
                return min(next(y["qty"] for y in locs if y["location_id"] == lid) for _i, locs in spread)
            best = max((x for x in spread[0][1] if x["location_id"] in common),
                       key=lambda x: _min_qty(x["location_id"]))
        o["location_id"], o["location_name"] = best["location_id"], best["location_name"]
        moved_to = best["location_name"]

    for x in outs:
        out_mat = await _ensure_output_material(
            db, {**x, "id": o["id"], "number": o["number"],
                 "input_material_id": _source_fabric_id(x, ins)}, user)
        x["output_material_id"] = out_mat["id"]
        x["output_material_code"] = out_mat["code"]
        x["output_material_name"] = out_mat["name"]
    await _save_lines(db, oid, ins, outs, {
        "status": STATUS_IN_PROGRESS,
        "location_id": o.get("location_id"), "location_name": o.get("location_name"),
        "started_at": _now(),
    })
    await log_activity(user["id"], user.get("name", ""), "start", "cutting.order", o["number"])
    out = await _enrich(db, await _get_order(db, oid))
    if moved_to:
        out["notice"] = f"Lokasi cutting dialihkan ke '{moved_to}' karena di sanalah stok kain berada."
    return serialize_doc(out)


@router.post("/orders/{oid}/progress")
async def add_progress(oid: str, request: Request):
    """Catat hasil potong sebagian: kain berkurang, potongan bertambah (SSOT stok).

    2026-11-06 (pola P9): order DIKUNCI selama satu laporan progres dicatat. Dulu Selesai/Batal bisa
    menyalip laporan yang sedang memotong stok (order batal/selesai tetapi stoknya tetap bergerak),
    dan dua laporan bersamaan berebut sisa gulungan yang sama.

    2026-11-10: body `inputs[]` = pemakaian PER KAIN ({line_id, input_consumed, input_uom, leftover_qty,
    leftover_uom, waste_qty, waste_uom, roll_ids}) dan `outputs[]` = pcs PER HASIL ({line_id, output_qty,
    roll_ids}). Body lama (satu kain + satu hasil di tingkat atas) tetap diterima untuk order satu baris."""
    user = await _require_cutting_user(request)
    db = get_db()
    token = await doc_lock.claim(db, ORDERS, oid, field="progress_lock", actor=user,
                                 not_found="Cutting order tidak ditemukan.",
                                 busy="Laporan progres lain untuk order ini sedang dicatat. Tunggu sebentar "
                                      "lalu muat ulang.")
    try:
        return await _add_progress_locked(db, oid, request, user)
    finally:
        await doc_lock.release(db, ORDERS, oid, token, field="progress_lock")


_PROGRESS_INPUT_KEYS = ("input_consumed", "input_uom", "leftover_qty", "leftover_uom", "waste_qty", "waste_uom",
                        "roll_ids", "roll_id")


def _progress_lines(body: dict, ins: list, outs: list) -> tuple[list, list]:
    """Pasangkan isian progres ke baris order → [(baris kain, isian)], [(baris hasil, isian)]."""
    b_in = body.get("inputs") if isinstance(body.get("inputs"), list) else None
    if b_in is None:
        if len(ins) != 1:
            raise HTTPException(400, "Order ini memakai beberapa kain — isi pemakaian per kain.")
        b_in = [{"line_id": ins[0]["line_id"], **{k: body.get(k) for k in _PROGRESS_INPUT_KEYS if k in body}}]
    b_out = body.get("outputs") if isinstance(body.get("outputs"), list) else None
    if b_out is None:
        if len(outs) != 1:
            raise HTTPException(400, "Order ini punya beberapa baris hasil — isi pcs per baris hasil.")
        b_out = [{"line_id": outs[0]["line_id"], "output_qty": body.get("output_qty")}]
    pin, pout = [], []
    for b in b_in:
        b = b or {}
        line = next((i for i in ins if i["line_id"] == b.get("line_id")
                     or (b.get("input_material_id") and i["input_material_id"] == b.get("input_material_id"))), None)
        if not line:
            raise HTTPException(400, "Kain yang dilaporkan bukan milik order ini — muat ulang lalu ulangi.")
        if any(p[0]["line_id"] == line["line_id"] for p in pin):
            raise HTTPException(400, f"Kain {cutting_lines.input_label(line)} dilaporkan dua kali dalam satu progres.")
        pin.append((line, b))
    for b in b_out:
        b = b or {}
        line = next((x for x in outs if x["line_id"] == b.get("line_id")
                     or (b.get("output_material_id") and x.get("output_material_id") == b.get("output_material_id"))),
                    None)
        if not line:
            raise HTTPException(400, "Baris hasil yang dilaporkan bukan milik order ini — muat ulang lalu ulangi.")
        if any(p[0]["line_id"] == line["line_id"] for p in pout):
            raise HTTPException(400, f"Hasil {cutting_lines.output_label(line)} dilaporkan dua kali dalam satu progres.")
        pout.append((line, b))
    return pin, pout


async def _add_progress_locked(db, oid: str, request: Request, user: dict):
    o = await _get_order(db, oid)
    if o["status"] != STATUS_IN_PROGRESS:
        raise HTTPException(400, "Progres hanya bisa diinput saat status 'in_progress'.")

    body = await request.json()
    ins, outs = cutting_lines.inputs_of(o), cutting_lines.outputs_of(o)
    pin, pout = _progress_lines(body, ins, outs)
    many_in = len(ins) > 1
    pin = [(line, b) for line, b in pin if _f(b.get("input_consumed")) > 0 or not many_in]
    pout = [(line, b) for line, b in pout if _f(b.get("output_qty")) != 0 or len(outs) == 1]
    if not pin or all(_f(b.get("input_consumed")) <= 0 for _l, b in pin):
        raise HTTPException(400, "Kain terpakai harus > 0.")
    if not pout or any(_f(b.get("output_qty")) < 0 for _l, b in pout) \
            or sum(_f(b.get("output_qty")) for _l, b in pout) <= 0:
        raise HTTPException(400, "Jumlah potongan jadi harus > 0.")

    loc_id = o["location_id"]
    actor = await _actor(user)
    ref = {"type": "cutting", "id": o["id"], "no": o["number"]}

    # ── 1) KAIN PER BARIS — satuan operator, sisa yang kembali ke stok, limbah, rencana gulungan ──
    # Semua dihitung & divalidasi DULU (sebelum stok apa pun dipotong): laporan yang ditolak tidak
    # menyisakan stok/gulungan yang sudah turun sebagian.
    used_lines: list[dict] = []
    for line, b in pin:
        pre = f"{cutting_lines.input_label(line)}: " if many_in else ""
        taken_in = _f(b.get("input_consumed"))
        if taken_in <= 0:
            raise HTTPException(400, f"{pre}Kain terpakai harus > 0.")
        leftover_in, waste_in = _f(b.get("leftover_qty")), _f(b.get("waste_qty"))
        if leftover_in < 0 or waste_in < 0:
            raise HTTPException(400, f"{pre}Sisa kain dan limbah tidak boleh negatif.")
        # ── 2026-08-05 · SATUAN HITUNG OPERATOR (opsional, `input_uom`) ───────────
        # Kain dicatat di satuan order (`input_unit`), operator boleh menghitung di satuan lain
        # (rol, gram, yard); qty diterjemahkan DULU ke satuan order. 2026-11-06 (Tahap 2): sisa kain
        # (`leftover_uom`) & limbah (`waste_uom`) juga bersatuan.
        order_uom = (line.get("input_unit") or "").strip().lower()
        mat_in = await db.rahaza_materials.find_one({"id": line["input_material_id"]}, {"_id": 0}) or {}
        taken, uom_applied = _to_order_unit(mat_in, taken_in, b.get("input_uom"), order_uom)
        same = b.get("input_uom")
        leftover, leftover_trace = _to_order_unit(mat_in, leftover_in, b.get("leftover_uom") or same, order_uom)
        waste, waste_trace = _to_order_unit(mat_in, waste_in, b.get("waste_uom") or same, order_uom)
        if taken <= 0:
            raise HTTPException(400, f"{pre}Hasil konversi kain terpakai harus > 0.")
        # Kain yang diambil = masuk potongan + limbah + sisa yang kembali ke stok. Sisa kain KEMBALI ke
        # stok kain pada harga kain (tidak dipotong dari stok/gulungan, tidak masuk nilai potongan);
        # limbah adalah pemakaian (ikut memotong stok & gulungan, nilainya ikut biaya potongan).
        if leftover + waste - taken > 0.0001:
            raise HTTPException(400, (
                f"{pre}Sisa kain ({leftover:g}) + limbah ({waste:g}) melebihi kain yang diambil ({taken:g} "
                f"{order_uom}). Periksa angkanya."))
        used = round(taken - leftover, 4)
        if used <= 0:
            raise HTTPException(400, f"{pre}Kain yang benar-benar terpakai (diambil − sisa) harus > 0.")
        # ── FASE H-6: rencana pemakaian GULUNGAN dihitung DULU (sebelum stok dipotong) ──
        plan, info = await _plan_roll_consumption(db, o, line, b, used)
        used_lines.append({"line": line, "mat": mat_in, "taken": round(taken, 4), "leftover": round(leftover, 4),
                           "waste": round(waste, 4), "used": used, "uom_applied": uom_applied,
                           "leftover_trace": leftover_trace, "waste_trace": waste_trace,
                           "plan": plan, "info": info})

    # Tautan gulungan → hasil yang diisi operator juga diperiksa SEBELUM stok bergerak.
    pool = {rr["roll_id"]: rr.get("roll_no", "") for i in ins for rr in (i.get("roll_ids") or [])}
    for u in used_lines:
        for p in u["plan"]:
            pool.setdefault(p["roll_id"], p.get("roll_no", ""))
    allowed = set(pool) | {no for no in pool.values() if no}
    for line, b in pout:
        bad = [str(v) for v in (b.get("roll_ids") or []) if str(v) not in allowed]
        if bad:
            raise HTTPException(400, (
                f"Hasil {cutting_lines.output_label(line)}: gulungan {', '.join(bad)} tidak dipilih di order "
                "maupun di progres ini — centang dulu gulungannya di bagian kain."))

    # ── 2) Kurangi stok KAIN — tiap kain SEKALI (guarded; boleh minus hanya bila mode
    #    sementara `inventory_allow_negative` ON). Bila kain ke-2 gagal, kain ke-1 dikembalikan.
    from core import negative_stock
    _neg_ok = await negative_stock.allowed(db)
    _loc_doc = await db.rahaza_locations.find_one({"id": loc_id}, {"_id": 0}) if _neg_ok else None
    issued: list[dict] = []
    for u in used_lines:
        mid = u["line"]["input_material_id"]
        try:
            await stock_service.issue(mid, loc_id, u["used"], ref=ref, actor=actor, db=db, allow_negative=_neg_ok,
                                      meta=negative_stock.stock_meta(u["mat"], _loc_doc) if _neg_ok else None)
            issued.append(u)
        except InsufficientStock as e:
            for back in issued:   # kembalikan kain yang sudah terpotong di laporan yang sama
                await stock_service.add(back["line"]["input_material_id"], loc_id, back["used"],
                                        ref={**ref, "type": "cutting_reversal"}, actor=actor, db=db)
            locs = await _stock_locations(db, mid)
            where = ", ".join(f"{x['location_name']}: {x['qty']}" for x in locs) or "tidak ada stok di gudang manapun"
            pre = f"{cutting_lines.input_label(u['line'])}: " if many_in else ""
            raise HTTPException(
                400, f"{pre}Stok kain tidak cukup di '{o.get('location_name')}': minta {e.requested}, "
                     f"tersedia {e.available} {u['line'].get('input_unit')}. Sebaran stok — {where}.")

    # ── 3) Tambah stok POTONGAN per baris hasil ──
    panels: list[dict] = []
    for line, b in pout:
        qty = round(_f(b.get("output_qty")), 4)
        if not line.get("output_material_id"):
            out_mat = await _ensure_output_material(
                db, {**line, "id": o["id"], "number": o["number"],
                     "input_material_id": _source_fabric_id(line, ins)}, user)
            line.update({"output_material_id": out_mat["id"], "output_material_code": out_mat["code"],
                         "output_material_name": out_mat["name"]})
        # SESI #32 — stok potongan SEBELUM penambahan (dipakai rata-rata bergerak)
        before = await cut_panel_value.panel_onhand(db, line["output_material_id"])
        if qty > 0:
            await stock_service.add(line["output_material_id"], loc_id, qty, ref=ref, actor=actor, db=db,
                                    meta={"material_code": line.get("output_material_code"),
                                          "material_name": line.get("output_material_name"),
                                          "material_type": "fabric", "unit": OUTPUT_UNIT,
                                          "category": OUTPUT_CATEGORY})
        panels.append({"line": line, "body": b, "panel_id": line["output_material_id"], "qty": qty,
                       "qty_before": before})

    # ── SESI #32 + 2026-11-10: NILAI KAIN YANG KELUAR **BERPINDAH** JADI NILAI POTONGAN ────
    # HPP masuk/pcs = Σ(kain terpakai × harga kain SAAT INI) ÷ Σ pcs hasil — SAMA untuk semua baris hasil;
    # tiap master potongan dirata-rata bergerak (SSOT core.accessory_valuation). `qty_before` dibaca
    # SEBELUM `stock_service.add` (pelajaran GR sesi #30). Kain tanpa harga → `unvalued` + alasannya.
    value_trace = await cut_panel_value.apply_progress_value_multi(
        db, fabrics=[{"fabric_id": u["line"]["input_material_id"], "qty": u["used"]} for u in used_lines],
        panels=[{"panel_id": p["panel_id"], "qty": p["qty"], "qty_before": p["qty_before"]} for p in panels],
        actor=actor, reference=o.get("number", ""))

    # ── 4) Roll fisik — SATU pintu pemakaian gulungan (`fabric_roll_engine.consume_rolls`), per kain ──
    all_consumption: list = []
    roll_required = False
    for u in used_lines:
        line = u["line"]
        roll_required = roll_required or bool(u["info"].get("tracked"))
        if not u["plan"]:
            u["consumption"] = []
            continue
        planned_ids = {p["roll_id"] for p in u["plan"]}
        for_whom = [x for x in outs if planned_ids & set(x.get("roll_ids") or [])] or [p["line"] for p in panels]
        notes = (f"Cutting {o['number']} — untuk "
                 + ", ".join(cutting_lines.output_label(x) for x in for_whom)).strip(" —")
        cons = await fabric_roll_engine.consume_rolls(
            db, u["plan"], {"type": "cutting", "id": o["id"], "number": o["number"], "notes": notes}, user)
        for p in cons:
            p["input_line_id"] = line["line_id"]
            p["material_code"] = line.get("input_material_code") or ""
            p["color_lot"] = u["info"].get("lots", {}).get(p["roll_id"], "")
            hit = next((rr for rr in line["roll_ids"] if rr.get("roll_id") == p["roll_id"]), None)
            if hit:
                hit["consumed_qty"] = round(_f(hit.get("consumed_qty")) + round(p["qty"], 3), 3)
                hit["remaining"] = p["remaining_after"]
                hit.setdefault("color_lot", p["color_lot"])
            else:
                # Gulungan yang baru dipilih saat progres ikut dicatat di order supaya
                # riwayat "gulungan mana dipakai order ini" tetap lengkap.
                line["roll_ids"].append({"roll_id": p["roll_id"], "roll_no": p.get("roll_no", ""),
                                         "uom": p.get("uom", ""), "color_lot": p["color_lot"],
                                         "remaining": p["remaining_after"],
                                         "consumed_qty": round(p["qty"], 3)})
        u["consumption"] = cons
        all_consumption.extend(cons)

    # ── 5) Tautan gulungan → hasil (ketelusuran): isian per hasil, selain itu tautan order ∩ gulungan
    #    progres ini, selain itu semua gulungan progres ini. Satu baris hasil = semua gulungan order. ──
    used_roll_ids = [p["roll_id"] for p in all_consumption]
    for p in panels:
        line, b = p["line"], p["body"]
        if len(outs) == 1:
            links = [rr["roll_id"] for i in ins for rr in (i.get("roll_ids") or [])]
        elif b.get("roll_ids"):
            links = _link_rolls(b.get("roll_ids"), ins, f"Hasil {cutting_lines.output_label(line)}: ")
        else:
            links = [r for r in used_roll_ids if r in (line.get("roll_ids") or [])] or list(used_roll_ids)
        p["roll_ids"] = links if len(outs) > 1 else [r for r in used_roll_ids]
        line["roll_ids"] = list(dict.fromkeys([*(line.get("roll_ids") or []), *links]))

    # ── 6) Catat progres (jejak lengkap per kain & per hasil) ──
    single_in = used_lines[0] if len(used_lines) == 1 else None
    single_panel = (value_trace.get("panels") or [{}])[0] if len(panels) == 1 else {}
    fab_trace = {f.get("fabric_id"): f for f in value_trace.get("fabrics") or []}
    pan_trace = {f.get("panel_id"): f for f in value_trace.get("panels") or []}
    input_used = round(sum(u["used"] for u in used_lines), 4)
    output_qty = round(sum(p["qty"] for p in panels), 4)
    waste = round(sum(u["waste"] for u in used_lines), 4)
    leftover = round(sum(u["leftover"] for u in used_lines), 4)
    prog = {
        "id": _uid(),
        "cutting_order_id": oid,
        "cutting_number": o["number"],
        "input_consumed": input_used,
        # 2026-11-06 (Tahap 2): jejak kain diambil, sisa yang kembali ke stok, dan limbah (satuan order)
        "input_taken": round(sum(u["taken"] for u in used_lines), 4),
        "leftover_qty": leftover,
        "leftover_input": single_in["leftover_trace"] if single_in else None,
        "waste_input": single_in["waste_trace"] if single_in else None,
        "output_qty": output_qty,
        "waste_qty": waste,
        "roll_id": (all_consumption[0]["roll_id"] if all_consumption
                    else (str(body.get("roll_id") or "").strip() or None)),
        # Jejak audit H-6: gulungan mana dipakai berapa untuk laporan progres ini.
        "roll_ids": [p["roll_id"] for p in all_consumption],
        "roll_numbers": [p.get("roll_no", "") for p in all_consumption],
        "roll_consumption": all_consumption,
        "roll_required": roll_required,
        "note": body.get("note") or "",
        # FASE H-6b: lokasi ASAL kain dicatat DI progres (bukan hanya di order)
        "location_id": loc_id,
        "location_name": o.get("location_name", ""),
        "uom_applied": single_in["uom_applied"] if single_in else None,
        # SESI #32 — jejak NILAI (dibaca `complete` & gate INV-F37)
        "fabric_unit_cost": value_trace.get("fabric_unit_cost", 0.0),
        "value_out": value_trace.get("value_out", 0.0),
        "cost_per_pcs_in": value_trace.get("cost_per_pcs_in", 0.0),
        "panel_unit_cost_before": single_panel.get("panel_unit_cost_before", 0.0),
        "panel_unit_cost_after": single_panel.get("panel_unit_cost_after", 0.0),
        "panel_qty_before": single_panel.get("panel_qty_before", 0.0),
        "value_status": value_trace.get("value_status", "unvalued"),
        "value_note": value_trace.get("value_note", ""),
        # 2026-11-10 — rincian per kain & per hasil
        "inputs": [{
            "line_id": u["line"]["line_id"], "input_material_id": u["line"]["input_material_id"],
            "input_material_code": u["line"].get("input_material_code", ""),
            "input_material_name": u["line"].get("input_material_name", ""),
            "input_unit": u["line"].get("input_unit", ""),
            "input_taken": u["taken"], "leftover_qty": u["leftover"], "input_consumed": u["used"],
            "waste_qty": u["waste"], "uom_applied": u["uom_applied"],
            "leftover_input": u["leftover_trace"], "waste_input": u["waste_trace"],
            "roll_consumption": u.get("consumption") or [],
            "fabric_unit_cost": fab_trace.get(u["line"]["input_material_id"], {}).get("fabric_unit_cost", 0.0),
            "value_out": fab_trace.get(u["line"]["input_material_id"], {}).get("value_out", 0.0),
        } for u in used_lines],
        "outputs": [{
            "line_id": p["line"]["line_id"], "output_material_id": p["panel_id"],
            "output_material_code": p["line"].get("output_material_code", ""),
            "label": cutting_lines.output_label(p["line"]), "output_qty": p["qty"],
            "roll_ids": p["roll_ids"],
            "panel_qty_before": pan_trace.get(p["panel_id"], {}).get("panel_qty_before", p["qty_before"]),
            "panel_unit_cost_before": pan_trace.get(p["panel_id"], {}).get("panel_unit_cost_before", 0.0),
            "panel_unit_cost_after": pan_trace.get(p["panel_id"], {}).get("panel_unit_cost_after", 0.0),
        } for p in panels],
        "created_by": user["id"], "created_by_name": user.get("name", ""),
        "created_at": _now(),
    }
    await db[PROGRESS].insert_one(dict(prog))

    # ── FASE H-6b: TERBITKAN DOKUMEN "PENGELUARAN MATERIAL" (`cutting_issue`) ──
    # Stok & gulungan sudah dipotong di atas — modul ini HANYA membuat dokumen +
    # baris kartu stok (satu baris per kain). Kegagalannya TIDAK membatalkan potong kain,
    # tetapi tidak hilang diam-diam: muncul di `GET /api/cutting/issue-docs/missing`.
    mi_doc = None
    mi_error = ""
    try:
        mi_doc = await cutting_material_issue.doc_for_progress(db, o, prog, user)
    except Exception as e:  # noqa: BLE001
        mi_error = str(e)
        log.exception("H-6b: dokumen MI gagal diterbitkan untuk progres cutting %s", prog["id"])
    if mi_doc:
        prog["material_issue_id"] = mi_doc["id"]
        prog["material_issue_number"] = mi_doc.get("mi_number", "")

    # ── 7) Akumulasi ke baris order (order DIKUNCI selama progres ⇒ tulis-ulang baris aman) ──
    for u in used_lines:
        line = u["line"]
        line["consumed_input_qty"] = round(_f(line.get("consumed_input_qty")) + u["used"], 4)
        line["waste_qty"] = round(_f(line.get("waste_qty")) + u["waste"], 4)
        line["leftover_qty"] = round(_f(line.get("leftover_qty")) + u["leftover"], 4)
    for p in panels:
        p["line"]["produced_qty"] = round(_f(p["line"].get("produced_qty")) + p["qty"], 4)
    await _save_lines(db, oid, ins, outs)
    await log_activity(user["id"], user.get("name", ""), "progress", "cutting.order", o["number"])
    out = await _enrich(db, await _get_order(db, oid))
    # Umpan balik langsung ke layar: gulungan mana berkurang berapa & sisanya.
    out["last_progress"] = {
        "input_consumed": input_used,
        "output_qty": output_qty,
        "roll_consumption": all_consumption,
        "roll_required": roll_required,
        "material_issue_id": (mi_doc or {}).get("id"),
        "material_issue_number": (mi_doc or {}).get("mi_number", ""),
        "fabric_unit_cost": prog["fabric_unit_cost"],
        "value_out": prog["value_out"],
        "cost_per_pcs_in": prog["cost_per_pcs_in"],
        "panel_unit_cost_before": prog["panel_unit_cost_before"],
        "panel_unit_cost_after": prog["panel_unit_cost_after"],
        "value_status": prog["value_status"],
        "value_note": prog["value_note"],
        "inputs": prog["inputs"],
        "outputs": prog["outputs"],
    }
    notices = []
    if leftover > 0:
        notices.append(
            f"Sisa kain {leftover:g} {used_lines[0]['line'].get('input_unit', '') if single_in else ''}".rstrip()
            + " tetap di stok kain (harga kain), tidak ikut nilai potongan.")
    if value_trace.get("value_status") == "valued":
        if len(panels) == 1:
            notices.append(
                f"Nilai kain {prog['value_out']:,.0f} berpindah ke potongan ⇒ HPP "
                f"potongan {prog['panel_unit_cost_before']:,.0f} → "
                f"{prog['panel_unit_cost_after']:,.0f}/pcs (rata-rata bergerak).")
        else:
            notices.append(
                f"Nilai kain {prog['value_out']:,.0f} ÷ {output_qty:g} pcs = {prog['cost_per_pcs_in']:,.0f}/pcs "
                "masuk ke semua baris hasil (rata-rata bergerak tiap master potongan).")
        if "belum punya harga" in (value_trace.get("value_note") or ""):
            out["value_warning"] = value_trace.get("value_note")
    else:
        out["value_warning"] = value_trace.get("value_note") or ""
        if out["value_warning"]:
            notices.append(out["value_warning"])
    if mi_doc and mi_doc.get("mi_number"):
        notices.append(
            f"Dokumen Pengeluaran Material {mi_doc['mi_number']} diterbitkan "
            f"(arus keluar kain tampil di layar Pengeluaran Material).")
    elif mi_error:
        out["mi_warning"] = (
            "Kain & gulungan SUDAH berkurang, tetapi dokumen Pengeluaran Material "
            f"gagal diterbitkan: {mi_error}. Buka Portal Cutting → kartu 'Progres "
            "tanpa dokumen MI' lalu tekan 'Terbitkan dokumen' untuk melengkapinya.")
        notices.append(out["mi_warning"])
    if all_consumption:
        notices.append("Gulungan dipakai: " + ", ".join(
            f"{p.get('roll_no')} −{p['qty']:,.2f} (sisa {p['remaining_after']:,.2f})"
            for p in all_consumption))
    if notices:
        out["notice"] = " ".join(notices)
    return serialize_doc(out)


@router.post("/orders/{oid}/complete")
async def complete_order(oid: str, request: Request):
    """in_progress ➜ completed + rekap NILAI potongan (SESI #32).

    Nilai TIDAK lagi dihitung ulang dengan harga kain yang di-snapshot saat order
    dibuat (harga basi). Angka order = **Σ nilai kain yang benar-benar keluar**
    pada tiap laporan progres (`cutting_progress.value_out`), dan master potongan
    TIDAK ditimpa karena HPP-nya sudah lahir per progres lewat rata-rata bergerak.
    Order LAMA (progresnya dilaporkan sebelum sesi #32, jadi tidak punya jejak
    nilai) tetap dilayani: dipakai cara lama sebagai cadangan, dan master yang
    masih Rp0 diisi supaya nilai persediaannya tidak nol selamanya.

    2026-11-10: HPP potongan per pcs = total biaya kain ÷ total pcs hasil SEMUA baris (sama untuk semua baris).
    """
    user = await _require_cutting_user(request)
    db = get_db()
    o = await _get_order(db, oid)
    if o["status"] != STATUS_IN_PROGRESS:
        raise HTTPException(400, f"Status '{o['status']}' tidak bisa di-complete.")
    ins, outs = cutting_lines.inputs_of(o), cutting_lines.outputs_of(o)
    produced = sum(_f(x.get("produced_qty")) for x in outs) if outs else _f(o.get("produced_qty"))
    if produced <= 0:
        raise HTTPException(400, "Belum ada progres. Input hasil potong dulu sebelum menyelesaikan.")

    totals = await cut_panel_value.order_value_totals(db, oid)
    value_source = "progress_trace"
    total_cost = _f(totals.get("value_total"))
    fallback_bits: list[str] = []
    unit_cost_in = 0.0
    if not totals.get("complete") or total_cost <= 0:
        # cadangan untuk order lama / kain belum bernilai: Σ kain terpakai × harga kain sekarang
        value_source = "fallback_unit_cost"
        total_cost = 0.0
        for i in ins:
            mat = await db.rahaza_materials.find_one({"id": i.get("input_material_id")}, {"_id": 0}) or {}
            cost = _f(mat.get("unit_cost")) or _f(i.get("input_unit_cost"))
            consumed = _f(i.get("consumed_input_qty"))
            total_cost += consumed * cost
            unit_cost_in = cost if len(ins) == 1 else unit_cost_in
            fallback_bits.append(f"{i.get('input_material_code') or 'kain'} {cost:,.0f}/{i.get('input_unit')} × "
                                 f"{consumed:g}")
    out_unit_cost = cutting_lines.cost_per_pcs(total_cost, produced)

    filled: list[str] = []
    for x in outs:
        x["output_unit_cost"] = out_unit_cost
        panel = await db.rahaza_materials.find_one(
            {"id": x.get("output_material_id")}, {"_id": 0}) if x.get("output_material_id") else None
        if panel and _f(panel.get("unit_cost")) <= 0 < out_unit_cost:
            # Order LAMA: nilainya belum pernah berpindah per progres ⇒ isi sekali di
            # sini supaya persediaan potongan tidak bernilai nol selamanya.
            await db.rahaza_materials.update_one(
                {"id": panel["id"]},
                {"$set": {"unit_cost": out_unit_cost, "value_status": "valued",
                          "value_source": "cutting_complete_backfill",
                          "value_note": (f"Diisi saat order {o.get('number')} diselesaikan "
                                         f"(progres lama tanpa jejak nilai)."),
                          "updated_at": _now()}},
            )
            filled.append(panel.get("code") or "")

    # 2026-11-06 (pola P9): selesai hanya bila MASIH berjalan & tidak ada laporan progres yang sedang
    # dicatat (nilai order dihitung dari progres yang sudah lengkap).
    _res = await _save_lines(db, oid, ins, outs, {
        "status": STATUS_COMPLETED,
        "output_unit_cost": out_unit_cost,
        "total_input_cost": round(total_cost, 2),
        "value_source": value_source,
        "completed_at": _now(),
    }, cond={"status": STATUS_IN_PROGRESS, **doc_lock.lock_free("progress_lock")})
    doc_lock.require_matched(_res, "Order ini sedang mencatat progres / baru saja diubah pengguna lain. "
                                   "Muat ulang lalu selesaikan lagi.")
    await log_activity(user["id"], user.get("name", ""), "complete", "cutting.order", o["number"])
    out = await _enrich(db, await _get_order(db, oid))
    notes = []
    if value_source == "progress_trace":
        notes.append(
            f"Nilai potongan order ini {total_cost:,.0f} (Σ nilai kain yang keluar) ÷ {produced:g} pcs ⇒ "
            f"{out_unit_cost:,.0f}/pcs. HPP master potongan tidak ditimpa karena sudah "
            f"dihitung rata-rata bergerak tiap progres.")
    elif total_cost <= 0:
        codes = ", ".join(i.get("input_material_code") or "" for i in ins) or o.get("input_material_code") or ""
        notes.append(
            f"HPP potongan = 0 karena harga satuan kain {codes} belum "
            f"ada. Harga kain lahir dari pembelian: buat PO lalu terima barang di Gudang, "
            f"atau perbaiki lewat Gudang → Valuasi HPP.")
    else:
        notes.append(
            f"Progres order ini dilaporkan sebelum jejak nilai ada, jadi nilai dihitung dari "
            f"harga kain sekarang ({'; '.join(fallback_bits)}) = {total_cost:,.0f}.")
    if filled:
        notes.append(f"HPP master potongan {', '.join(filled)} diisi {out_unit_cost:,.0f}/pcs (sebelumnya kosong).")
    out["notice"] = " ".join(notes)
    return serialize_doc(out)


@router.post("/orders/{oid}/cancel")
async def cancel_order(oid: str, request: Request):
    user = await _require_cutting_user(request)
    db = get_db()
    o = await _get_order(db, oid)
    if o["status"] in (STATUS_COMPLETED, STATUS_CANCELLED):
        raise HTTPException(400, f"Status '{o['status']}' tidak bisa dibatalkan.")
    n = await db[PROGRESS].count_documents({"cutting_order_id": oid})
    if n > 0:
        raise HTTPException(
            400, "Sudah ada progres (stok sudah bergerak). Selesaikan cutting, "
                 "lalu koreksi lewat Penyesuaian Stok di Gudang bila perlu.")
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — BODY OPSIONAL: pembatalan boleh dikirim
        # tanpa body sama sekali (mis. tombol "Batalkan" tanpa alasan). Ini bukan
        # kegagalan, jadi memang tidak ada yang perlu dicatat — `reason` di bawah
        # akan menjadi string kosong. Sengaja dibiarkan tanpa log agar tidak
        # membanjiri log dengan kejadian normal.
        body = {}
    # 2026-11-06 (pola P9): batal hanya bila status belum berubah & tidak ada progres yang sedang dicatat
    # (dulu progres yang sedang memotong stok lolos, order batal dengan stok yang sudah bergerak).
    _res = await db[ORDERS].update_one(
        {"id": oid, "status": o["status"], **doc_lock.lock_free("progress_lock")}, {"$set": {
            "status": STATUS_CANCELLED,
            "cancel_reason": (body or {}).get("reason") or "",
            "updated_at": _now(),
        }})
    doc_lock.require_matched(_res, "Order ini sedang mencatat progres / baru saja diubah pengguna lain — muat ulang.")
    # ── SESI #32 · PENJAGA ANTI-POTONGAN-YATIM ───────────────────────────────
    # `start` melahirkan master POTONGAN (2026-11-10: satu per baris hasil). Master yang BELUM
    # PERNAH BERGERAK (0 stok, 0 buku besar, 0 kartu stok, tidak dirujuk dokumen apa pun) ikut
    # dibuang, dan yang sudah pernah bergerak DIPERTAHANKAN dengan alasan yang dikatakan.
    ins, outs = cutting_lines.inputs_of(o), cutting_lines.outputs_of(o)
    notes, removed_any = [], False
    for x in outs:
        res_panel = await cut_panel_health.remove_if_unused(
            db, panel_id=x.get("output_material_id") or "", order_id=oid, user=user)
        if res_panel and res_panel.get("removed"):
            removed_any = True
            x["output_material_id"], x["output_material_code"], x["output_material_name"] = "", "", ""
            notes.append(f"Master potongan {res_panel['code']} ikut dibersihkan karena belum "
                         f"pernah dipakai (0 stok, tanpa kartu stok).")
        elif res_panel and res_panel.get("reason"):
            notes.append(f"Master potongan {res_panel['code']} DIPERTAHANKAN — {res_panel['reason']}")
    if removed_any:
        await _save_lines(db, oid, ins, outs)
    await log_activity(user["id"], user.get("name", ""), "cancel", "cutting.order", o["number"])
    out = await _enrich(db, await _get_order(db, oid))
    if notes:
        out["notice"] = " ".join(notes)
    return serialize_doc(out)
