"""
PT Rahaza — Fase 2 (Master Product Refactor): Warna (Colors) + Varian Model + SKU.

Prinsip: Product = header model (rahaza_models). Varian = kombinasi Warna × Size,
masing-masing punya SKU unik. SKU otomatis: {model.code}-{color.code}-{size.code}.

Endpoints (prefix /api/rahaza):
  Colors (master DINAMIS, configurable via UI):
    GET    /colors                                 : List (seed lazy palet techpack)
    POST   /colors                                 : Create
    PUT    /colors/{cid}                           : Update
    DELETE /colors/{cid}                           : Soft delete · `?hard=true` hapus permanen bila belum dipakai (409)
  Model Variants:
    GET    /variants                               : List (filter model_id / include_inactive)
    GET    /models/{model_id}/variants             : List varian per model (enriched)
    POST   /models/{model_id}/variants/generate    : Generate matriks (color_ids × size_ids) → SKU auto
    POST   /variants                               : Create single variant
    PUT    /variants/{vid}                          : Update (active/barcode/notes/product_status)
    DELETE /variants/{vid}                          : Soft delete · `?hard=true` hapus permanen bila belum dipakai (409)
  Penyaring daftar varian: `product_status=best_seller` · `stop,dead` · `belum_diisi` (core/product_status).

Schema rahaza_colors:   {id, code, name, hex, order_seq, active, created_at, updated_at}
Schema rahaza_model_variants:
  {id, model_id, model_code, size_id, size_code, color_id, color_code, color_name,
   sku(UNIQUE aktif), barcode?, notes?, product_status? (new|best_seller|slow|dead|stop|null),
   active, created_at, updated_at}
"""
from routes.shared import lolos_centang  # 14 Nov 2026 (tahap 2): centang owner dihormati
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc, log_activity
from utils.variant_ssot import ensure_fg_material
from core.cut_panel_master import ensure_panel_for_variant, ensure_bom_for_variant  # 2026-09-24: potongan + BOM otomatis per varian
from core import product_master as pm  # K-9a: varian dihentikan ⇒ item katalog nonaktif
from core import product_status as ps  # status produk per SKU (keputusan owner 6 Nov 2026)
from core.roles import PRODUCTION_ROLES, RND_ROLES  # gerbang hapus permanen master produk (10 Nov 2026)
import uuid
from datetime import datetime, timezone
from typing import Optional

router = APIRouter(prefix="/api/rahaza", tags=["rahaza-variants"])


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)


# ── Palet warna standar (techpack) — seed awal, bisa ditambah/hapus via UI ──
DEFAULT_COLORS = [
    {"code": "PTH", "name": "Putih",     "hex": "#FFFFFF", "order_seq": 1},
    {"code": "HTM", "name": "Hitam",     "hex": "#1A1A1A", "order_seq": 2},
    {"code": "ABU", "name": "Abu-abu",   "hex": "#9CA3AF", "order_seq": 3},
    {"code": "NVY", "name": "Navy",      "hex": "#1E3A5F", "order_seq": 4},
    {"code": "BIR", "name": "Biru",      "hex": "#2563EB", "order_seq": 5},
    {"code": "MRH", "name": "Merah",     "hex": "#DC2626", "order_seq": 6},
    {"code": "MRN", "name": "Maroon",    "hex": "#7F1D1D", "order_seq": 7},
    {"code": "HJU", "name": "Hijau",     "hex": "#16A34A", "order_seq": 8},
    {"code": "TSK", "name": "Tosca",     "hex": "#14B8A6", "order_seq": 9},
    {"code": "KNG", "name": "Kuning",    "hex": "#FACC15", "order_seq": 10},
    {"code": "ORG", "name": "Oranye",    "hex": "#EA580C", "order_seq": 11},
    {"code": "PNK", "name": "Pink",      "hex": "#EC4899", "order_seq": 12},
    {"code": "UNG", "name": "Ungu",      "hex": "#7C3AED", "order_seq": 13},
    {"code": "CKL", "name": "Coklat",    "hex": "#78350F", "order_seq": 14},
    {"code": "KRM", "name": "Krem",      "hex": "#F5E6D3", "order_seq": 15},
]


async def _require_admin(request: Request):
    """RBAC master product (keputusan user): SEMUA staff internal boleh CRUD.
    Hanya role eksternal (vendor/klien) yang ditolak."""
    user = await require_auth(request)
    if lolos_centang(user):  # 14 Nov 2026 (tahap 2): centang owner dihormati
        return user
    role = (user.get("role") or "").lower()
    if role in ("cmt_vendor", "vendor", "klien_maklon"):
        raise HTTPException(403, "Akses master hanya untuk staff internal.")
    return user


# ══════════════════════════ HAPUS PERMANEN MASTER PRODUK (10 Nov 2026) ══════════════════════════
# Permintaan owner: "pastikan tabel tabel master data bisa dihapus". DELETE tanpa `?hard=true` tetap
# menonaktifkan (perilaku lama). Dengan `hard`: hapus permanen HANYA bila belum dipakai transaksi/dokumen
# mana pun — hitungan & kalimat 409 lewat `core.hapus_master` (layar menawarkan Nonaktifkan, lib/hapusMaster).
# Dipakai juga oleh master model & ukuran (`routes.rahaza_production`), kategori produk, dan BOM.

# Endpoint master produk sengaja terbuka untuk SEMUA staf internal (keputusan user, lihat `_require_admin`).
# Hapus permanen lebih berat dari ubah/nonaktifkan: hanya tim produksi/R&D/manajemen atau peran yang punya izin
# master produk/R&D. Jalur nonaktifkan TIDAK ikut diperketat.
PRODUK_HAPUS_ROLES = ("admin",) + PRODUCTION_ROLES + RND_ROLES
PRODUK_HAPUS_PERMS = ("products.delete", "rnd.manage", "bom.manage")


def izinkan_hapus_permanen(user: dict) -> None:
    """403 bila `user` tidak boleh menghapus permanen master produk (model, varian, warna, ukuran, kategori, BOM)."""
    if lolos_centang(user):  # 14 Nov 2026 (tahap 2): centang owner dihormati
        return user
    from auth import check_role
    if not (check_role(user, list(PRODUK_HAPUS_ROLES), PRODUK_HAPUS_PERMS) or lolos_centang(user)):
        raise HTTPException(403, "Akses ditolak: hapus permanen data master produk hanya untuk tim produksi, R&D, "
                                 "atau manajemen. Nonaktifkan saja, atau minta atasan menghapusnya.")


def _isi(field: str, nilai):
    """{field: nilai} atau None bila nilai kosong (filter yang dilewati `hitung_pemakaian`)."""
    return {field: nilai} if nilai else None


def _atau(*filters):
    fs = [f for f in filters if f]
    if not fs:
        return None
    return fs[0] if len(fs) == 1 else {"$or": fs}


def cek_pemakaian_produk(*, model_id: str = None, variant_ids=(), skus=(), fg_ids=(), material_ids=()) -> list:
    """(label staf, koleksi, filter) — di mana sebuah model / varian (SKU) / barang jadi & potongan miliknya dipakai.

    Satu filter per koleksi (gabungan `$or`) supaya satu dokumen tidak terhitung dua kali. Pemetaan field dari
    penulisnya: PO (`production_pos.create_po_internal`), job (`production_execution`), order produksi
    (`rahaza_orders`), cutting (`cutting._resolve_identity`), katalog & pesanan marketing, peta SKU (`core.sku_bridge`),
    gudang/stok (`core.stock_service`, `wms_*`, `sales_direct`), R&D (`master_sync`, promosi style).
    """
    mid = model_id or None
    vin = {"$in": list(variant_ids)} if variant_ids else None
    sin = {"$in": [s for s in skus if s]} if any(skus) else None   # baris lama yang hanya menyimpan teks SKU
    fin = {"$in": list(fg_ids)} if fg_ids else None
    semua = list(dict.fromkeys([*fg_ids, *material_ids]))
    ain = {"$in": semua} if semua else None
    return [
        ("baris PO produksi", "po_items",
         _atau(_isi("model_id", mid), _isi("rahaza_variant_id", vin), _isi("fg_material_id", fin), _isi("sku", sin))),
        ("job produksi", "production_job_items", _atau(_isi("model_id", mid), _isi("rahaza_variant_id", vin))),
        ("order produksi", "rahaza_orders", _isi("items.model_id", mid)),
        ("order cutting", "cutting_orders",
         _atau(_isi("model_id", mid), _isi("variant_id", vin), _isi("output_material_id", ain),
               # 2026-11-10: order cutting banyak hasil menyimpan identitas per baris `outputs[]`
               _isi("outputs.model_id", mid), _isi("outputs.variant_id", vin),
               _isi("outputs.output_material_id", ain))),
        ("catatan WIP", "rahaza_wip_events", _isi("model_id", mid)),
        ("penugasan line", "rahaza_line_assignments", _isi("model_id", mid)),
        ("pengeluaran material", "rahaza_material_issues", _isi("model_id", mid)),
        ("item katalog marketing", "marketing_catalog_items",
         _atau(_isi("model_id", mid), _isi("variant_id", vin), _isi("fg_material_id", fin), _isi("material_id", fin),
               _isi("variant_sku", sin))),
        ("pesanan marketing", "marketing_orders",
         _atau(_isi("model_id", mid), _isi("items.model_id", mid), _isi("variant_id", vin),
               _isi("items.variant_id", vin), _isi("fg_material_id", fin), _isi("items.fg_material_id", fin),
               _isi("variant_sku", sin))),
        ("pemetaan SKU marketplace", "marketing_sku_bridge",
         _atau(_isi("model_id", mid), _isi("variant_id", vin), _isi("fg_material_id", fin))),
        ("peluncuran produk", "marketing_product_launches", _atau(_isi("model_id", mid), _isi("fg_material_id", fin))),
        ("permintaan komponen CMT", "dewi_cmt_component_requests", _isi("model_id", mid)),
        ("permintaan kreator", "dewi_kreator_requests", _isi("model_id", mid)),
        ("riwayat penerapan HPP", "product_cost_snapshots", _isi("model_id", mid)),
        ("riwayat harga SKU", "rahaza_sku_price_history", _atau(_isi("model_id", mid), _isi("fg_id", fin))),
        ("style R&D asal produk", "dewi_rnd_styles", _isi("promoted_to_model_id", mid)),
        ("varian R&D asal SKU", "dewi_rnd_variants", _isi("sizes.variant_id", vin)),
        ("retur gudang", "wh_returns", _atau(_isi("variant_id", vin), _isi("material_id", ain))),
        ("kiriman ke buyer", "buyer_shipment_items", _isi("fg_material_id", fin)),
        ("penerimaan dari CMT", "cmt_receipt_lines", _isi("fg_material_id", fin)),
        # stok & mutasi barang jadi / potongan milik master ini
        ("kartu stok", "rahaza_stock_ledger", _isi("material_id", ain)),
        ("mutasi material", "rahaza_material_movements", _isi("material_id", ain)),
        ("mutasi barang jadi", "rahaza_fg_movements", _isi("material_id", ain)),
        ("penerimaan gudang tertunda", "wh_pending_movements", _isi("material_id", ain)),
        ("reservasi barang jadi", "rahaza_fg_reservations", _isi("material_id", ain)),
        ("pengeluaran barang jadi", "rahaza_fg_issues", _isi("material_id", ain)),
        ("lapisan biaya barang jadi", "fg_cost_layers", _atau(_isi("model_id", mid), _isi("material_id", ain))),
        ("posisi rak gudang", "wh_positions", _isi("material_id", ain)),
        ("daftar ambil barang", "wh_picklists", _isi("items.material_id", ain)),
        ("surat jalan gudang", "wh_delivery_notes", _isi("lines.material_id", ain)),
        ("nota penjualan langsung", "sales_direct_notes", _isi("items.material_id", ain)),
        # data lama (mesin sudah diarsip, dokumennya bisa masih ada)
        ("job vendor lama", "vendor_jobs", _isi("model_id", mid)),
        ("WO lama", "rahaza_work_orders", _atau(_isi("model_id", mid), _isi("variant_id", vin))),
    ]


async def _baris_stok_bersaldo(db, material_ids) -> int:
    """Baris `rahaza_material_stock` yang saldonya bukan 0 (semua skema qty, `core.stock_schema.read_qty`)."""
    if not material_ids:
        return 0
    from core.stock_schema import read_qty
    rows = await db.rahaza_material_stock.find({"material_id": {"$in": list(material_ids)}}, {"_id": 0}).to_list(5000)
    return sum(1 for r in rows if abs(read_qty(r)) > 1e-9)


async def pemakaian_produk(db, *, model_id: str = None, variant_ids=(), skus=(), fg_ids=(), material_ids=()) -> dict:
    """{label: jumlah} pemakaian model/varian + stok bersaldo barang jadi/potongan miliknya (kosong = boleh dihapus)."""
    from core.hapus_master import hitung_pemakaian
    pakai = await hitung_pemakaian(db, cek_pemakaian_produk(
        model_id=model_id, variant_ids=variant_ids, skus=skus, fg_ids=fg_ids, material_ids=material_ids))
    n = await _baris_stok_bersaldo(db, [*fg_ids, *material_ids])
    return {"lokasi stok bersaldo": n, **pakai} if n else pakai


async def hapus_barang_milik(db, material_ids) -> int:
    """Hapus barang jadi/potongan milik master yang dihapus + baris stok bersaldo 0-nya. → jumlah barang terhapus."""
    ids = list(material_ids or [])
    if not ids:
        return 0
    await db.rahaza_material_stock.delete_many({"material_id": {"$in": ids}})
    res = await db.rahaza_materials.delete_many({"id": {"$in": ids}})
    return int(res.deleted_count or 0)


# ══════════════════════════════ COLORS MASTER ══════════════════════════════

async def _ensure_colors(db):
    """Lazy-seed palet warna default bila koleksi masih kosong."""
    if await db.rahaza_colors.count_documents({}) == 0:
        docs = [{
            "id": _uid(), "code": c["code"], "name": c["name"], "hex": c["hex"],
            "order_seq": c["order_seq"], "active": True,
            "created_at": _now(), "updated_at": _now(),
        } for c in DEFAULT_COLORS]
        # 2026-11-06 (pola P8): `_id` tetap per kode — dua permintaan bersamaan tidak menggandakan palet
        from core.reference_dedup import seed_once
        await seed_once(db, "rahaza_colors", docs)


@router.get("/colors")
async def list_colors(request: Request, include_inactive: bool = False):
    await require_auth(request)
    db = get_db()
    await _ensure_colors(db)
    q = {} if include_inactive else {"active": True}
    rows = await db.rahaza_colors.find(q, {"_id": 0}).sort("order_seq", 1).to_list(300)
    return serialize_doc(rows)


@router.post("/colors")
async def create_color(request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nama warna wajib diisi.")
    # code = singkatan (dipakai di SKU). Default: 3 huruf pertama nama (upper).
    code = (body.get("code") or name[:3]).strip().upper().replace(" ", "")
    if not code:
        raise HTTPException(400, "Kode warna wajib diisi.")
    if await db.rahaza_colors.find_one({"code": code, "active": True}):
        raise HTTPException(409, f"Kode warna '{code}' sudah dipakai. Gunakan kode lain.")
    # 2026-11-06 (pola P8): nama warna setara (Putih = White, Abu = Abu-abu) ditolak — aturan kembar keputusan 6a
    from core.reference_dedup import assert_unique_ref
    from core.variant_identity import color_group_key
    await assert_unique_ref(db, "rahaza_colors", name=name, label="Warna", key_fn=color_group_key)
    hex_val = (body.get("hex") or "#CCCCCC").strip()
    if not hex_val.startswith("#"):
        hex_val = "#" + hex_val
    doc = {
        "id": _uid(), "code": code, "name": name, "hex": hex_val,
        "order_seq": int(body.get("order_seq") or 50),
        "active": True, "created_at": _now(), "updated_at": _now(),
    }
    await db.rahaza_colors.insert_one(doc)
    await log_activity(user["id"], user.get("name", ""), "create", "rahaza.color", code)
    return serialize_doc(doc)


@router.put("/colors/{cid}")
async def update_color(cid: str, request: Request):
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    upd = {"updated_at": _now()}
    if "name" in body:
        upd["name"] = (body["name"] or "").strip()
    if "code" in body:
        new_code = (body["code"] or "").strip().upper().replace(" ", "")
        if new_code:
            dup = await db.rahaza_colors.find_one({"code": new_code, "active": True, "id": {"$ne": cid}})
            if dup:
                raise HTTPException(409, f"Kode warna '{new_code}' sudah dipakai.")
            upd["code"] = new_code
    if "hex" in body:
        h = (body["hex"] or "").strip()
        if h and not h.startswith("#"):
            h = "#" + h
        upd["hex"] = h
    if "order_seq" in body:
        upd["order_seq"] = int(body.get("order_seq") or 50)
    if "active" in body:
        upd["active"] = bool(body["active"])
    res = await db.rahaza_colors.update_one({"id": cid}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(404, "Warna tidak ditemukan.")
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.color", cid)
    return serialize_doc(await db.rahaza_colors.find_one({"id": cid}, {"_id": 0}))


async def pemakaian_warna(db, color: dict) -> dict:
    """Di mana satu warna master dipakai. Rujukan ber-id selalu dihitung; rujukan lewat KODE/NAMA (BOM, baris PO,
    katalog maklon) hanya bila tidak ada warna lain berkode/bernama sama — kalau ada, rujukan itu milik kembarannya."""
    from core.hapus_master import hitung_pemakaian
    cid = color.get("id")
    code = (color.get("code") or "").strip()
    name = (color.get("name") or "").strip()
    if code and await db.rahaza_colors.count_documents({"code": code, "id": {"$ne": cid}}):
        code = ""
    if name and await db.rahaza_colors.count_documents({"name": name, "id": {"$ne": cid}}):
        name = ""
    return await hitung_pemakaian(db, [
        ("varian produk", "rahaza_model_variants", {"color_id": cid}),
        ("barang jadi", "rahaza_materials", {"color_id": cid}),
        ("order cutting", "cutting_orders", {"$or": [{"color_id": cid}, {"outputs.color_id": cid}]}),
        ("varian R&D", "dewi_rnd_variants", {"color_id": cid}),
        ("tech pack", "dewi_rnd_tech_packs", {"$or": [{"colorways.color_id": cid}, {"fabrics.color_id": cid},
                                                     {"bom_items.color_id": cid}]}),
        ("riset material", "dewi_rnd_materials", {"colors.color_id": cid}),
        ("warna lain (sebagai nama lain)", "rahaza_colors", {"alias_of_color_id": cid}),
        ("BOM", "rahaza_boms", _isi("color_code", code)),
        ("baris PO produksi", "po_items", _isi("color_code", code)),
        ("artikel katalog maklon", "dewi_maklon_buyer_catalog",
         _atau(_isi("variants.color_code", code), _isi("color_options", name))),
    ])


@router.delete("/colors/{cid}")
async def deactivate_color(cid: str, request: Request, hard: bool = False):
    """Tanpa `hard`: nonaktifkan (perilaku lama; ditolak 400 bila masih dipakai varian aktif). `?hard=true`
    (10 Nov 2026): hapus permanen bila warna belum dipakai varian/barang/cutting/R&D/BOM/PO/katalog maklon;
    bila sudah → 409 dengan rinciannya."""
    user = await _require_admin(request)
    db = get_db()
    if hard:
        izinkan_hapus_permanen(user)
        from core.hapus_master import tolak_bila_dipakai
        color = await db.rahaza_colors.find_one({"id": cid}, {"_id": 0})
        if not color:
            raise HTTPException(404, "Warna tidak ditemukan.")
        nama = f"{color.get('name') or ''} ({color.get('code') or ''})".replace(" ()", "").strip()
        tolak_bila_dipakai("Warna", nama, await pemakaian_warna(db, color))
        await db.rahaza_colors.delete_one({"id": cid})
        await log_activity(user["id"], user.get("name", ""), "delete", "rahaza.color",
                           f"id={cid} kode={color.get('code')}")
        return {"status": "deleted", "deleted": True, "message": f"Warna {nama} dihapus."}
    # Guard: cegah nonaktif bila warna dipakai varian aktif (jaga integritas SKU)
    in_use = await db.rahaza_model_variants.count_documents({"color_id": cid, "active": True})
    if in_use > 0:
        raise HTTPException(400, f"Warna dipakai oleh {in_use} varian aktif. Hapus/nonaktifkan varian terkait dulu.")
    res = await db.rahaza_colors.update_one({"id": cid}, {"$set": {"active": False, "updated_at": _now()}})
    if res.matched_count == 0:
        raise HTTPException(404, "Warna tidak ditemukan.")
    await log_activity(user["id"], user.get("name", ""), "deactivate", "rahaza.color", cid)
    return {"status": "deactivated"}


# ══════════════════════════════ MODEL VARIANTS ══════════════════════════════

def _status_or_400(value):
    """Kode/label status produk → kode; kosong → None ("belum diisi"); tak dikenal → 400."""
    try:
        return ps.parse(value)
    except ps.ProductStatusError as e:
        raise HTTPException(400, str(e)) from None


def _status_filter_or_400(value) -> dict:
    try:
        return ps.filter_query(value)
    except ps.ProductStatusError as e:
        raise HTTPException(400, str(e)) from None


def _with_status(rows: list) -> list:
    """Kontrak daftar varian: field `product_status` selalu ada (null = belum diisi)."""
    for r in rows:
        r.setdefault(ps.FIELD, None)
    return rows


def _make_sku(model_code: str, color_code: str, size_code: str) -> str:
    parts = [str(model_code or "").strip().upper(),
             str(color_code or "").strip().upper(),
             str(size_code or "").strip().upper()]
    return "-".join(p for p in parts if p)


async def _enrich_variant(db, v, model=None, colors_map=None, sizes_map=None):
    """Pastikan denormalized fields (model_code/size_code/color_*) terisi."""
    if not v:
        return v
    if not v.get("model_code"):
        model = model or await db.rahaza_models.find_one({"id": v.get("model_id")}, {"_id": 0})
        v["model_code"] = (model or {}).get("code")
        v["model_name"] = (model or {}).get("name")
    return v


@router.get("/variants")
async def list_variants(request: Request, model_id: Optional[str] = None, include_inactive: bool = False,
                        product_status: Optional[str] = None):
    await require_auth(request)
    db = get_db()
    q = {} if include_inactive else {"active": True}
    if model_id:
        q["model_id"] = model_id
    q.update(_status_filter_or_400(product_status))
    rows = await db.rahaza_model_variants.find(q, {"_id": 0}).sort("sku", 1).to_list(2000)
    return serialize_doc(_with_status(rows))


@router.get("/models/{model_id}/variants")
async def list_model_variants(model_id: str, request: Request, include_inactive: bool = False,
                              product_status: Optional[str] = None):
    await require_auth(request)
    db = get_db()
    model = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0})
    if not model:
        raise HTTPException(404, "Model tidak ditemukan.")
    q = {"model_id": model_id} if include_inactive else {"model_id": model_id, "active": True}
    q.update(_status_filter_or_400(product_status))
    rows = await db.rahaza_model_variants.find(q, {"_id": 0}).sort([("color_code", 1), ("size_code", 1)]).to_list(2000)
    # ringkasan status model = SEMUA varian aktif (tidak ikut penyaring), dihitung saat dibaca
    summary = (await ps.model_summaries(db, [model_id])).get(model_id) or ps.summarize([])
    return serialize_doc({
        "model": {"id": model["id"], "code": model["code"], "name": model["name"],
                  ps.SUMMARY_FIELD: summary},
        "variants": _with_status(rows),
        "count": len(rows),
    })


@router.post("/models/{model_id}/variants/generate")
async def generate_variants(model_id: str, request: Request):
    """Generate matriks varian dari kombinasi color_ids × size_ids → SKU otomatis.
    Body: { color_ids: [..], size_ids: [..] (opsional=semua size aktif) }
    Idempoten: kombinasi (model,size,color) yang sudah ada → dilewati."""
    user = await _require_admin(request)
    db = get_db()
    model = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0})
    if not model:
        raise HTTPException(404, "Model tidak ditemukan.")
    body = await request.json()
    color_ids = body.get("color_ids") or []
    if not color_ids:
        raise HTTPException(400, "Pilih minimal 1 warna.")
    size_ids = body.get("size_ids") or []
    status = _status_or_400(body.get("product_status"))

    # Resolve colors
    colors = await db.rahaza_colors.find({"id": {"$in": color_ids}, "active": True}, {"_id": 0}).to_list(300)
    if not colors:
        raise HTTPException(400, "Warna terpilih tidak valid/aktif.")
    # Resolve sizes (default: semua size aktif)
    if size_ids:
        sizes = await db.rahaza_sizes.find({"id": {"$in": size_ids}, "active": {"$ne": False}}, {"_id": 0}).sort("order_seq", 1).to_list(300)
    else:
        sizes = await db.rahaza_sizes.find({"active": {"$ne": False}}, {"_id": 0}).sort("order_seq", 1).to_list(300)
    if not sizes:
        raise HTTPException(400, "Tidak ada size aktif.")

    # Prefetch existing variants for this model (active) → idempotent skip
    existing = await db.rahaza_model_variants.find({"model_id": model_id, "active": True}, {"_id": 0}).to_list(5000)
    existing_combo = {(e.get("size_id"), e.get("color_id")) for e in existing}
    existing_sku = {e.get("sku") for e in existing}

    created, skipped = [], []
    to_insert = []
    for color in colors:
        for size in sizes:
            combo = (size["id"], color["id"])
            if combo in existing_combo:
                skipped.append({"size_code": size.get("code"), "color_code": color.get("code"), "reason": "sudah ada"})
                continue
            sku = _make_sku(model.get("code"), color.get("code"), size.get("code"))
            if sku in existing_sku or any(d["sku"] == sku for d in to_insert):
                skipped.append({"size_code": size.get("code"), "color_code": color.get("code"), "reason": f"SKU '{sku}' bentrok"})
                continue
            doc = {
                "id": _uid(),
                "model_id": model_id, "model_code": model.get("code"), "model_name": model.get("name"),
                "size_id": size["id"], "size_code": size.get("code"),
                "color_id": color["id"], "color_code": color.get("code"), "color_name": color.get("name"),
                "color_hex": color.get("hex"),
                "sku": sku, "barcode": "", "notes": "", "product_status": status,
                "active": True, "created_at": _now(), "updated_at": _now(),
            }
            to_insert.append(doc)
            created.append({"sku": sku, "size_code": size.get("code"), "color_code": color.get("code")})
    if to_insert:
        await db.rahaza_model_variants.insert_many(to_insert)
        await log_activity(user["id"], user.get("name", ""), "generate_variants", "rahaza.model", model_id)
        # GAP-4: auto-create FG master (rahaza_materials type='fg', code==sku) per varian, stok 0.
        panels_created = 0
        for v in to_insert:
            try:
                await ensure_fg_material(db, v, user=user)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("ensure_fg_material gagal utk varian %s", v.get("sku"))
            try:
                _p, _new = await ensure_panel_for_variant(db, v, model)
                panels_created += 1 if _new else 0
                await ensure_bom_for_variant(db, v, model, _p, user)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("ensure_panel_for_variant gagal utk varian %s", v.get("sku"))
        return {"created": created, "skipped": skipped, "created_count": len(created), "skipped_count": len(skipped),
                "cut_panels_created": panels_created}
    return {"created": created, "skipped": skipped, "created_count": len(created), "skipped_count": len(skipped)}


@router.post("/variants")
async def create_variant(request: Request):
    """Create single variant (pilih model + warna + size → SKU auto)."""
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    model_id = body.get("model_id")
    size_id = body.get("size_id")
    color_id = body.get("color_id")
    if not (model_id and size_id and color_id):
        raise HTTPException(400, "model_id, size_id, color_id wajib diisi.")
    status = _status_or_400(body.get("product_status"))
    model = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0})
    size = await db.rahaza_sizes.find_one({"id": size_id}, {"_id": 0})
    color = await db.rahaza_colors.find_one({"id": color_id}, {"_id": 0})
    if not model:
        raise HTTPException(404, "Model tidak ditemukan.")
    if not size:
        raise HTTPException(404, "Size tidak ditemukan.")
    if not color:
        raise HTTPException(404, "Warna tidak ditemukan.")
    # Idempotent: cek kombinasi
    dup = await db.rahaza_model_variants.find_one(
        {"model_id": model_id, "size_id": size_id, "color_id": color_id, "active": True}, {"_id": 0})
    if dup:
        raise HTTPException(409, f"Varian {dup.get('sku')} sudah ada.")
    sku = (body.get("sku") or _make_sku(model.get("code"), color.get("code"), size.get("code"))).strip().upper()
    if await db.rahaza_model_variants.find_one({"sku": sku, "active": True}):
        raise HTTPException(409, f"SKU '{sku}' sudah dipakai.")
    doc = {
        "id": _uid(),
        "model_id": model_id, "model_code": model.get("code"), "model_name": model.get("name"),
        "size_id": size_id, "size_code": size.get("code"),
        "color_id": color_id, "color_code": color.get("code"), "color_name": color.get("name"),
        "color_hex": color.get("hex"),
        "sku": sku, "barcode": (body.get("barcode") or "").strip(), "notes": body.get("notes") or "",
        "product_status": status,
        "active": True, "created_at": _now(), "updated_at": _now(),
    }
    await db.rahaza_model_variants.insert_one(doc)
    # GAP-4: auto-create FG master (code==sku) untuk varian tunggal, stok 0.
    try:
        await ensure_fg_material(db, doc, user=user)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("ensure_fg_material gagal utk varian %s", doc.get("sku"))
    try:
        panel, _new = await ensure_panel_for_variant(db, doc, model)
        doc["cut_panel_code"] = panel.get("code")
        doc["bom"] = await ensure_bom_for_variant(db, doc, model, panel, user)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("ensure_panel_for_variant gagal utk varian %s", doc.get("sku"))
    await log_activity(user["id"], user.get("name", ""), "create", "rahaza.variant", sku)
    return serialize_doc(doc)


@router.put("/variants/{vid}")
async def update_variant(vid: str, request: Request):
    """Update varian: barcode/notes/active/product_status. (size/color/sku tidak diubah di sini —
    ganti varian = hapus & generate ulang untuk jaga konsistensi SKU).

    `product_status` kosong/null = "belum diisi". `stop` TIDAK menonaktifkan varian (keputusan owner):
    varian tetap aktif, hanya tidak diusulkan untuk cutting/restock."""
    user = await _require_admin(request)
    db = get_db()
    body = await request.json()
    upd = {"updated_at": _now()}
    if "barcode" in body:
        upd["barcode"] = (body["barcode"] or "").strip()
    if "notes" in body:
        upd["notes"] = body.get("notes") or ""
    if "active" in body:
        upd["active"] = bool(body["active"])
    if ps.FIELD in body:
        upd[ps.FIELD] = _status_or_400(body.get(ps.FIELD))
    res = await db.rahaza_model_variants.update_one({"id": vid}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(404, "Varian tidak ditemukan.")
    await log_activity(user["id"], user.get("name", ""), "update", "rahaza.variant", vid)
    return serialize_doc(await db.rahaza_model_variants.find_one({"id": vid}, {"_id": 0}))


async def hapus_varian_permanen(db, vid: str, user: dict) -> dict:
    """Hapus permanen satu varian (SKU) + barang jadi miliknya (`ensure_fg_material`, ditaut `variant_id`) bila
    belum dipakai PO/job/cutting/katalog/pesanan/stok; bila sudah → 409. BOM & potongan per model-ukuran-warna
    TIDAK ikut dihapus: kuncinya bukan varian (bisa dipakai varian lain/opsi lain dan dipakai lagi bila varian
    dibuat ulang) — hapus lewat layar BOM bila memang tidak dipakai."""
    from core.hapus_master import tolak_bila_dipakai
    v = await db.rahaza_model_variants.find_one({"id": vid}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Varian tidak ditemukan.")
    fgs = await db.rahaza_materials.find({"type": "fg", "variant_id": vid}, {"_id": 0, "id": 1}).to_list(50)
    fg_ids = [f["id"] for f in fgs if f.get("id")]
    tolak_bila_dipakai("Varian", v.get("sku") or "", await pemakaian_produk(
        db, variant_ids=[vid], skus=[v.get("sku")], fg_ids=fg_ids))
    fg_deleted = await hapus_barang_milik(db, fg_ids)
    await db.rahaza_model_variants.delete_one({"id": vid})
    await log_activity(user["id"], user.get("name", ""), "delete", "rahaza.variant",
                       f"id={vid} sku={v.get('sku')} barang_jadi={fg_deleted}")
    return {"status": "deleted", "deleted": True, "sku": v.get("sku", ""), "fg_deleted": fg_deleted,
            "message": f"Varian {v.get('sku', '')} dihapus."}


@router.delete("/variants/{vid}")
async def deactivate_variant(vid: str, request: Request, hard: bool = False):
    """Nonaktifkan varian (SKU). **K-9a**: item katalog yang menawarkan SKU ini
    ikut dinonaktifkan dan DAFTAR TERDAMPAK dikembalikan ke staf.
    `?hard=true` (10 Nov 2026): hapus permanen bila belum dipakai (`hapus_varian_permanen`, 409 bila sudah)."""
    user = await _require_admin(request)
    db = get_db()
    if hard:
        izinkan_hapus_permanen(user)
        return await hapus_varian_permanen(db, vid, user)
    v = await db.rahaza_model_variants.find_one({"id": vid}, {"_id": 0, "sku": 1})
    if not v:
        raise HTTPException(404, "Varian tidak ditemukan.")
    affected = await pm.deactivate_catalog_items_for_variant(db, vid)
    await db.rahaza_model_variants.update_one({"id": vid}, {"$set": {"active": False, "updated_at": _now()}})
    await log_activity(user["id"], user.get("name", ""), "deactivate", "rahaza.variant", vid)
    return {
        "status": "deactivated",
        "sku": v.get("sku", ""),
        "affected_catalog_items": affected,
        "affected_count": len(affected),
        "message": (f"Varian {v.get('sku','')} dinonaktifkan. {len(affected)} item katalog "
                    "ikut dinonaktifkan." if affected
                    else f"Varian {v.get('sku','')} dinonaktifkan. Tidak ada item katalog terdampak."),
    }
