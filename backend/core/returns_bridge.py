"""core.returns_bridge — SESI #29 (W4, permintaan pemilik).

**JEMBATAN SATU-ARAH: retur pembeli (Marketing) → Retur Fisik (Gudang) → STOK.**

═══════════════════════════════════════════════════════════════════════════════
MASALAH YANG DIUKUR SEBELUM MODUL INI ADA (2026-08-19, DB preview)
═══════════════════════════════════════════════════════════════════════════════
  · `marketing_returns`      = **30 dokumen** (retur pembeli NYATA)
  · `wh_returns`             = **0 dokumen**  ⇒ layar "Retur Fisik" gudang KOSONG
                               SELAMANYA
  · `production_returns`     = 0, `production_return_items` = 0
  · Jembatan yang ada (`POST /api/marketing/returns/{id}/create-wh-return`):
      - harus DIKLIK MANUAL dan hanya boleh saat approved/completed,
      - mengirim `sku_code=""` dan memaksa `qty=1` ⇒ gudang tidak tahu barang
        apa yang kembali, jadi restock mustahil tepat.
  · Restock di `POST /api/wh/returns/{id}/resolve` menulis ke
    `rahaza_fg_inventory` — koleksi **MATI (0 dokumen)** — dan BUKAN lewat
    `core/stock_service`. Artinya: walau petugas menekan "Restock ke Gudang",
    **stok nyata tidak pernah bertambah** dan tidak ada satu baris ledger pun.

KEPUTUSAN PEMILIK (2026-08-19)
------------------------------
  1. Retur yang dibuat di Marketing **OTOMATIS** memunculkan pekerjaan di Gudang
     (tanpa klik manual) dan **OTOMATIS restock**.
  2. Ada **pilihan kondisi barang**:
       · **Baik**  → stok masuk zona jual `ZNA-FG`  → ikut terhitung stok jual.
       · **Rusak** → stok masuk `ZNA-KARANTINA`     → TIDAK terhitung stok jual
         (K-6a `core/catalog_stock.blocked_location_ids` sudah mengecualikan
         setiap lokasi ber-kode KARANTINA), jadi barang rusak TIDAK BISA terjual.

PRINSIP MODUL INI (sama seperti `core/sku_bridge`)
-------------------------------------------------
  * **SATU PINTU stok**: setiap penambahan stok memakai `core/stock_service.add`
    ⇒ alias skema (`qty`/`total_qty`/`quantity`) & `available_quantity` konsisten
    dan setiap mutasi punya baris `rahaza_stock_ledger`.
  * **IDEMPOTEN**: satu retur Marketing hanya boleh melahirkan SATU `wh_returns`
    (kunci `source_marketing_return_id`) dan hanya boleh menambah stok SEKALI
    (penjaga atomik `restocked`). Menekan tombol dua kali tidak menggandakan stok.
  * **TIDAK MENEBAK**: identitas barang diambil dari master (item katalog atau
    baris pesanan yang sudah tertaut SKU Bridge). Bila pesanan multi-baris dan
    tidak ada penunjuk pasti, retur tetap MUNCUL di gudang tetapi ditandai
    `needs_manual_resolution` dan stok TIDAK disentuh — lebih baik pekerjaan
    terlihat lalu diperbaiki manusia daripada stok bertambah pada barang salah.
  * **BERJEJAK**: timeline `wh_returns` mencatat langkah otomatis, dan retur
    Marketing menerima balikan (`wh_return_id/code/status`, `wh_stock_effect`).

═══════════════════════════════════════════════════════════════════════════════
2026-11-02 — KEPUTUSAN OWNER K1 (MENCABUT W4 "restock otomatis saat retur dibuat")
═══════════════════════════════════════════════════════════════════════════════
  * Retur Marketing (form, approve, impor "Retur & Refund", sinkron) HANYA membuat
    pekerjaan Retur Fisik **Pending** (`auto_restock=False` menjadi bawaan).
  * Gudang: **Terima** (isi qty AKTUAL) → **Periksa** (kondisi) → **Keputusan**
    (Terima → stok jual · Rusak → karantina · Tolak → dikembalikan ke pembeli ·
    Dibuang). Stok & jurnal HANYA lahir pada keputusan gudang.
  * Marketing Tolak/Hapus SEBELUM gudang memutuskan ⇒ pekerjaan gudang dibatalkan
    (:func:`cancel_for_marketing_return`). SESUDAH keputusan ⇒ hanya bisa dibalik
    lewat jurnal pembalik + stok keluar berjejak (:func:`reverse_decision`).
  * K2 diganti K15: retur yang DITERIMA gudang menambah stok & membalik HPP lewat
    fungsi penilaian yang sudah ada (`_value_restock`/`_value_damaged`) — berkas
    ini hanya mengatur ALUR/WAKTU-nya, bukan cara menilai HPP.
  * K6: pembatalan pesanan SETELAH dikirim melahirkan pengajuan Retur Fisik "RTS"
    Pending (:func:`ensure_rts_returns`) — stok baru masuk saat gudang menerima.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from core import stock_service
from utils.counters import gen_prefixed_number

logger = logging.getLogger(__name__)

WH = "wh_returns"
MKT = "marketing_returns"

# ── kosakata kondisi barang ──────────────────────────────────────────────────
COND_GOOD = "Baik"
COND_DAMAGED = "Rusak"
CONDITIONS = (COND_GOOD, COND_DAMAGED, "Rusak Ringan", "Rusak Berat", "Tidak Layak Jual")
_GOOD_ALIASES = {"baik", "good", "bagus", "layak jual", "ok", "normal", "mulus"}

# Lokasi tujuan restock (kode master `rahaza_locations`).
LOC_SELLABLE = "ZNA-FG"          # Area Produk Jadi — ikut stok jual
LOC_QUARANTINE = "ZNA-KARANTINA"  # Area Karantina QC — DIKECUALIKAN dari stok jual

# Status tautan identitas barang retur.
LINK_OK = "linked"
LINK_AMBIGUOUS = "needs_manual_resolution"
LINK_NONE = "no_master_link"

ACTION_RESTOCK = "Restock ke Gudang"
ACTION_QUARANTINE = "Karantina (Rusak)"
# 2026-11-02 (K1) — keputusan "Tolak": barang dikembalikan ke pembeli, TANPA stok/jurnal.
ACTION_REJECT_TO_BUYER = "Ditolak — Dikembalikan ke Pembeli"
ACTION_DISPOSE = "Dibuang / Dispose"

# 2026-11-02 (K1) — status alur Retur Fisik.
STATUS_PENDING = "Pending"
STATUS_RESOLVED = "Resolved"
STATUS_CANCELLED = "Cancelled"
STATUS_REVERSED = "Reversed"          # keputusan dibalik (jurnal pembalik + stok keluar)
OPEN_STATUSES = ("Pending", "Received", "Inspected")   # belum diputuskan gudang


class ReturnBridgeError(Exception):
    """Kegagalan yang harus terlihat (mis. lokasi master tidak ada)."""


# ═════════════════════════════════════════════════════════════════════════════
# 2026-11-02 (K30) — "PERLU TINDAKAN" untuk gudang: retur menunggu keputusan
# ═════════════════════════════════════════════════════════════════════════════
def wh_decider_roles() -> list:
    """Peran nyata Portal Gudang yang berwenang memutuskan retur (SSOT PORTAL_ACCESS ∩ WAREHOUSE_ROLES,
    sama dengan grup `wh_return` di routes/approval_badge.py)."""
    from core.roles import WAREHOUSE_ROLES
    from utils.notif_unified import decider_roles
    return decider_roles("warehouse", WAREHOUSE_ROLES)


async def notify_pending(db, wh: dict, *, actor=None) -> str | None:
    """Notifikasi action `wh_return_pending` ke peran gudang untuk SATU retur yang menunggu
    keputusan. Pembuatnya (bila pengguna) tidak ikut menerima. Ditutup otomatis oleh resolver
    (`SOURCE_RULES['wh_return']`) begitu status keluar dari Pending/Received/Inspected."""
    if not wh or not wh.get("id") or wh.get("status") not in OPEN_STATUSES:
        return None
    try:
        from utils.notif_unified import notif_insert
        who = (actor or {}).get("id")
        prod = wh.get("product_name") or wh.get("sku_code") or "barang"
        src = {"marketing_return": "retur Marketing", "order_cancel_after_ship": "pembatalan setelah kirim (RTS)"
               }.get(wh.get("source") or "", "retur")
        return await notif_insert(
            db, type="rahaza", subtype="wh_return_pending", severity="warning",
            title=f"Retur {wh.get('return_code') or ''} menunggu keputusan gudang".replace("  ", " "),
            body=(f"{src.capitalize()} {wh.get('order_number') or '-'}: {prod} × {wh.get('qty') or 1}. "
                  "Terima paket, periksa kondisi, lalu putuskan (stok & jurnal lahir saat keputusan)."),
            source_type="wh_return", source_id=wh["id"], source_ref=wh.get("return_code"),
            target_roles=wh_decider_roles(), exclude_user_ids=[who] if who else None,
            status="sent", meta={"link_module": "wh-returns"})
    except Exception:  # noqa: BLE001 — notifikasi tidak boleh menggagalkan pekerjaan gudang
        logger.warning("[retur] notifikasi Perlu Tindakan gagal untuk %s", wh.get("return_code"), exc_info=True)
        return None


async def close_pending_notifs(db, wh_id: str) -> int:
    """Periksa ulang (resolver K30 yang ada) action retur ini sesudah statusnya berubah."""
    try:
        from utils.notif_unified import resolve_for_source
        return await resolve_for_source(db, WH, wh_id)
    except Exception:  # noqa: BLE001
        logger.warning("[retur] penutupan notifikasi gagal untuk %s", wh_id, exc_info=True)
        return 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


def _actor_name(actor) -> str:
    a = actor or {}
    return a.get("name") or a.get("full_name") or a.get("email") or "sistem"


def _int(v, default: int = 0) -> int:
    try:
        n = int(float(v))
        return n
    except (TypeError, ValueError):
        return default


# ═════════════════════════════════════════════════════════════════════════════
# KONDISI & LOKASI
# ═════════════════════════════════════════════════════════════════════════════
def normalize_condition(raw) -> str:
    """Samakan ejaan kondisi. Apa pun yang bukan 'Baik' dianggap RUSAK.

    Sengaja konservatif: kalau kondisi tidak terbaca, barang TIDAK dianggap layak
    jual — lebih aman menahan barang di karantina daripada menjual barang rusak.
    """
    s = str(raw or "").strip()
    if not s:
        return COND_GOOD
    if s.lower() in _GOOD_ALIASES:
        return COND_GOOD
    for c in CONDITIONS:
        if s.lower() == c.lower():
            return c
    return COND_DAMAGED


def is_sellable_condition(cond) -> bool:
    return normalize_condition(cond) == COND_GOOD


async def resolve_location(db, condition) -> dict:
    """Lokasi tujuan stok retur menurut kondisi barang."""
    sellable = is_sellable_condition(condition)
    from core.location_resolver import legacy_location_for_role
    role, code = ("fg", LOC_SELLABLE) if sellable else ("karantina", LOC_QUARANTINE)
    loc = await legacy_location_for_role(db, role)
    if not loc:
        raise ReturnBridgeError(
            f"Lokasi berperan '{role}' (atau kode '{code}') tidak ada di Struktur Gudang. "
            "Tandai lokasinya dulu — stok retur tidak boleh disimpan tanpa lokasi.")
    return {
        "id": loc["id"],
        "code": loc.get("code") or code,
        "name": loc.get("name") or code,
        "sellable": sellable,
    }


# ═════════════════════════════════════════════════════════════════════════════
# IDENTITAS BARANG (tanpa menebak)
# ═════════════════════════════════════════════════════════════════════════════
async def _material_snapshot(db, material_id: str) -> dict:
    mat = await db.rahaza_materials.find_one({"id": material_id}, {"_id": 0})
    if not mat:
        return {}
    return {
        "material_id": mat["id"],
        "material_code": mat.get("code") or mat.get("sku") or "",
        "material_name": mat.get("name") or "",
        "unit": mat.get("unit") or "pcs",
        "material_type": mat.get("type") or "fg",
        "category_name": mat.get("category_name") or mat.get("category") or "",
        "color_name": mat.get("color_name") or mat.get("color") or "",
        "option_name": mat.get("option_name") or "",
        "variant_id": mat.get("variant_id"),
    }


async def _from_catalog_item(db, catalog_item_id: str) -> dict | None:
    it = await db.marketing_catalog_items.find_one({"id": catalog_item_id}, {"_id": 0})
    if not it:
        return None
    mid = it.get("fg_material_id") or it.get("material_id")
    if not mid:
        return None
    snap = await _material_snapshot(db, mid)
    if not snap:
        return None
    snap["catalog_item_id"] = it["id"]
    snap["source"] = "catalog_item"
    return snap


async def resolve_identity(db, ret: dict) -> dict:
    """Tentukan barang & jumlah yang kembali. Hasil:

        {link_status, material_id, material_code, material_name, unit, qty,
         variant_id, catalog_item_id, source, reason, candidates[]}

    Urutan sumber (dari paling pasti):
      1. `catalog_item_id` pada retur (dipilih pemakai dari katalog toko)
      2. `sku` pada retur → item katalog / master material ber-kode sama
      3. `order_id` → `marketing_orders.items[]` yang sudah tertaut SKU Bridge
         · 1 baris tertaut          → dipakai
         · >1 baris & nama produk retur cocok TEPAT SATU baris → dipakai
         · sisanya                  → `needs_manual_resolution` + kandidat
    """
    out = {
        "link_status": LINK_NONE,
        "material_id": None,
        "material_code": "",
        "material_name": "",
        "unit": "pcs",
        # 2026-11-02 — impor "Retur & Refund" menulis `quantity` (form menulis `qty`).
        "qty": max(1, _int(ret.get("qty") or ret.get("qty_return") or ret.get("quantity"), 1)),
        "variant_id": None,
        "catalog_item_id": ret.get("catalog_item_id"),
        "source": "",
        "reason": "",
        "candidates": [],
    }

    # 1) item katalog yang dipilih pemakai
    if ret.get("catalog_item_id"):
        snap = await _from_catalog_item(db, ret["catalog_item_id"])
        if snap:
            out.update(snap)
            out["link_status"] = LINK_OK
            return out
        out["reason"] = ("Item katalog retur ini belum tertaut ke master barang jadi "
                         "(FG). Petakan dulu lewat Jembatan SKU.")

    # 2) SKU pada retur
    sku = (ret.get("sku") or "").strip()
    if sku:
        it = await db.marketing_catalog_items.find_one({"sku": sku}, {"_id": 0})
        if it:
            snap = await _from_catalog_item(db, it["id"])
            if snap:
                out.update(snap)
                out["link_status"] = LINK_OK
                out["source"] = "catalog_sku"
                return out
        mat = await db.rahaza_materials.find_one(
            {"$or": [{"code": sku}, {"sku": sku}], "type": "fg"}, {"_id": 0})
        if mat:
            out.update(await _material_snapshot(db, mat["id"]))
            out["link_status"] = LINK_OK
            out["source"] = "material_code"
            return out

    # 3) lewat pesanan (hasil SKU Bridge sesi #28)
    order_id = (ret.get("order_id") or "").strip()
    if order_id:
        order = await db.marketing_orders.find_one({"order_id": order_id}, {"_id": 0})
        if not order:
            out["reason"] = (f"Pesanan {order_id} tidak ada di data pesanan Marketing, "
                             "jadi barangnya tidak bisa dipastikan.")
            return out
        items = order.get("items") or []
        linked = [i for i in items if i.get("fg_material_id")]
        if not linked:
            out["reason"] = (f"Pesanan {order_id} belum tertaut master barang "
                             "(Jembatan SKU). Petakan SKU-nya dulu.")
            return out
        chosen = None
        if len(linked) == 1:
            chosen = linked[0]
            src = "order_item"
        else:
            want = (ret.get("product") or "").strip().lower()
            hits = [i for i in linked
                    if want and want in str(i.get("product_name_raw") or "").lower()]
            if len(hits) == 1:
                chosen = hits[0]
                src = "order_item_name_match"
            else:
                out["link_status"] = LINK_AMBIGUOUS
                out["reason"] = (
                    f"Pesanan {order_id} punya {len(linked)} baris barang. Retur harus "
                    "menunjuk SATU produk — pilih produknya dari katalog pada retur ini "
                    "supaya stok tidak bertambah pada barang yang salah.")
                out["candidates"] = [{
                    "catalog_item_id": i.get("catalog_item_id"),
                    "fg_material_id": i.get("fg_material_id"),
                    "product_name": i.get("product_name_raw") or "",
                    "variation": i.get("variation_raw") or "",
                    "quantity": _int(i.get("quantity"), 1),
                } for i in linked]
                return out
        snap = await _material_snapshot(db, chosen["fg_material_id"])
        if not snap:
            out["reason"] = ("Baris pesanan menunjuk master barang yang sudah tidak ada "
                             f"({chosen.get('fg_material_id')}).")
            return out
        out.update(snap)
        out["catalog_item_id"] = chosen.get("catalog_item_id") or out.get("catalog_item_id")
        out["variant_id"] = chosen.get("variant_id") or snap.get("variant_id")
        if not (ret.get("qty") or ret.get("qty_return") or ret.get("quantity")):
            out["qty"] = max(1, _int(chosen.get("quantity"), 1))
        out["link_status"] = LINK_OK
        out["source"] = src
        return out

    if not out["reason"]:
        out["reason"] = ("Retur ini tidak menyebut produk maupun nomor pesanan, jadi "
                         "barang yang kembali tidak bisa dipastikan.")
    return out


# ═════════════════════════════════════════════════════════════════════════════
# MEMBUAT PEKERJAAN DI GUDANG (idempoten)
# ═════════════════════════════════════════════════════════════════════════════
async def _next_code(db) -> str:
    """Nomor retur gudang. Selalu OTOMATIS (dokumen ini lahir dari sistem, bukan
    diketik pemakai), tetapi FORMATNYA sama dengan yang dipakai layar manual —
    dibaca dari kebijakan penomoran pemilik (`doc_number_configs`) supaya arsip
    retur tidak berisi dua pola nomor yang berbeda."""
    key = "wh_returns.return_code"
    try:
        from core import doc_number_policy as _dnp
        from utils.counters import render_format
        pol = await _dnp.policy(db, key)
        prefix, width = render_format(pol["format"], ctx={})
    except Exception as e:  # noqa: BLE001 — jangan sampai retur gagal karena format
        logger.warning("[retur-jembatan] format nomor retur tidak terbaca (%s) — "
                       "pakai pola cadangan RET-YYYYMMDD-###", e)
        prefix, width = f"RET-{_now():%Y%m%d}-", 3
    return await gen_prefixed_number(db, WH, "return_code", prefix, width,
                                     config_key=key)


def _wh_skeleton(code: str, actor_name: str, note: str) -> dict:
    """Kerangka dokumen Retur Fisik (field alur kerja kosong) — SATU tempat, dipakai
    jembatan retur Marketing, pengajuan RTS (K6), dan pembukaan ulang (K1)."""
    return {
        "id": _uid(),
        "return_code": code,
        "status": STATUS_PENDING,
        "timeline": [{"status": STATUS_PENDING, "at": _now_iso(), "by": actor_name, "note": note}],
        "received_at": "", "received_by": "", "received_qty": None,
        "unboxing_condition_notes": "", "unboxing_photo_notes": "", "package_condition": "",
        "inspected_at": "", "inspected_by": "",
        "item_condition": "", "return_cause": "", "cause_detail": "", "recommended_action": "",
        "resolved_at": "", "resolved_by": "",
        "action_taken": "", "action_notes": "",
        "reshipment_resi": "", "appeal_status": "", "restock_qty": 0,
        "restocked": False,
        "restock_location_id": None, "restock_location_code": "",
        "restock_condition": "", "stock_effect": "",
        "created_by": actor_name, "created_at": _now_iso(), "updated_at": _now_iso(),
    }


async def find_linked_wh(db, ret: dict) -> dict | None:
    """Pekerjaan Retur Fisik milik satu retur Marketing.

    2026-11-02 (K1) — sesudah keputusan DIBALIK lalu dibuka ulang, satu retur bisa
    punya dua dokumen (lama `Reversed`, baru aktif). Yang aktif selalu didahulukan;
    dokumen `Reversed` hanya dikembalikan bila tidak ada yang lain (supaya jembatan
    tidak membuat pekerjaan ketiga untuk barang yang sudah diselesaikan)."""
    if not ret or not ret.get("id"):
        return None
    if ret.get("wh_return_id"):
        doc = await db[WH].find_one({"id": ret["wh_return_id"]}, {"_id": 0})
        if doc and doc.get("status") != STATUS_REVERSED:
            return doc
    rows = await db[WH].find({"source_marketing_return_id": ret["id"]}, {"_id": 0}).to_list(20)
    active = [r for r in rows if r.get("status") != STATUS_REVERSED]
    if active:
        return active[0]
    return rows[0] if rows else None


async def ensure_wh_return(db, ret: dict, *, actor=None, condition=None,
                           auto_restock: bool = False) -> dict:
    """Pastikan retur Marketing punya SATU pekerjaan Retur Fisik di Gudang.

    2026-11-02 (K1) — bawaan ``auto_restock=False``: retur Marketing HANYA membuat
    pekerjaan **Pending**; stok & jurnal menunggu keputusan gudang. Parameter
    ``auto_restock=True`` dibiarkan untuk pemanggil lama yang sadar, tetapi tidak
    lagi dipakai jalur Marketing mana pun.

    Return: {created, restocked, wh_return, identity, message}
    """
    actor = actor or {}
    cond = normalize_condition(condition if condition is not None
                               else ret.get("item_condition") or ret.get("goods_condition"))

    # ── idempoten: sudah pernah dijembatani? ──────────────────────────────────
    existing = await find_linked_wh(db, ret)
    if existing:
        res = {"created": False, "restocked": False, "wh_return": existing,
               "identity": None, "message": f"Sudah terhubung ke {existing.get('return_code')}"}
        if auto_restock and not existing.get("restocked") \
                and existing.get("link_status") == LINK_OK:
            done = await auto_process(db, existing["id"], condition=cond, actor=actor)
            res["restocked"] = bool(done.get("restocked"))
            res["wh_return"] = done.get("wh_return") or existing
            res["message"] = done.get("message") or res["message"]
        await _stamp_marketing(db, ret["id"], res["wh_return"])
        return res

    ident = await resolve_identity(db, ret)
    code = await _next_code(db)
    actor_name = _actor_name(actor)
    reason_txt = " — ".join([x for x in [ret.get("reason_label"), ret.get("reason_detail")] if x])

    doc = _wh_skeleton(code, actor_name, (
        f"Dibuat otomatis dari retur Marketing (pesanan {ret.get('order_id') or '-'}) — "
        "menunggu paket diterima gudang (K1: stok baru bergerak saat keputusan gudang)"))
    doc.update({
        "return_type": "customer_refund",
        # ── info pesanan (dipetakan dari retur Marketing) ─────────────────────
        "order_number": ret.get("order_id", ""),
        "resi_number": "",
        "channel": ret.get("platform", ""),
        "customer_name": ret.get("customer_name") or ret.get("account_name") or "Pembeli Marketplace",
        "customer_contact": "",
        "sku_code": ident.get("material_code") or (ret.get("sku") or ""),
        "product_name": ident.get("material_name") or ret.get("product") or "",
        "qty": max(1, _int(ident.get("qty"), 1)),
        "order_value": float(ret.get("price") or 0),
        "initial_reason": reason_txt,
        "notes": (f"Otomatis dari retur Toko/Marketing #{ret['id']}. "
                  f"Refund: Rp {float(ret.get('refund_amount') or 0):,.0f}. "
                  f"{ret.get('notes') or ''}").strip(),
        # ── tautan master barang (kunci agar restock tidak buta) ──────────────
        "material_id": ident.get("material_id"),
        "fg_material_id": ident.get("material_id"),
        "variant_id": ident.get("variant_id"),
        "catalog_item_id": ident.get("catalog_item_id"),
        "material_unit": ident.get("unit") or "pcs",
        "material_category": ident.get("category_name") or "",
        "material_color": ident.get("color_name") or "",
        "material_option": ident.get("option_name") or "",
        "link_status": ident.get("link_status"),
        "link_reason": ident.get("reason") or "",
        "link_source": ident.get("source") or "",
        "link_candidates": ident.get("candidates") or [],
        # ── asal (jembatan satu arah) ─────────────────────────────────────────
        "source": "marketing_return",
        "source_marketing_return_id": ret["id"],
        "source_marketing_order_id": ret.get("order_id"),
        "source_account_name": ret.get("account_name") or "",
        # kondisi yang DILAPORKAN Marketing hanya petunjuk; gudang yang memutuskan (K1)
        "reported_condition": cond,
    })
    await db[WH].insert_one(doc)
    doc.pop("_id", None)
    if not auto_restock:
        await notify_pending(db, doc, actor=actor)   # 2026-11-02 (K30)

    out = {"created": True, "restocked": False, "wh_return": doc, "identity": ident,
           "message": (f"Retur fisik {code} dibuat di Gudang (Pending). Stok BELUM bergerak — "
                       "gudang menerima paket, mengisi qty aktual, memeriksa, lalu memutuskan.")}

    if auto_restock and ident.get("link_status") == LINK_OK:
        done = await auto_process(db, doc["id"], condition=cond, actor=actor)
        out["restocked"] = bool(done.get("restocked"))
        out["wh_return"] = done.get("wh_return") or doc
        out["message"] = done.get("message") or out["message"]
    elif auto_restock:
        out["message"] = (f"Retur fisik {code} dibuat, TAPI stok belum ditambah: "
                          f"{ident.get('reason') or 'barang belum tertaut master'}")

    await _stamp_marketing(db, ret["id"], out["wh_return"])
    return out


async def _stamp_marketing(db, marketing_return_id: str, wh: dict) -> None:
    """Tulis balikan ke retur Marketing supaya layar Toko tahu keadaan fisiknya."""
    wh = wh or {}
    try:
        await db[MKT].update_one({"id": marketing_return_id}, {"$set": {
            "wh_return_id": wh.get("id"),
            "wh_return_code": wh.get("return_code", ""),
            "wh_return_status": wh.get("status", "Pending"),
            # 2026-11-02 (K1/K36) — keputusan gudang ikut dibalikkan: rekap omzet
            # menghitung retur HANYA setelah keputusan ini ada.
            "wh_action_taken": wh.get("action_taken", ""),
            "wh_decided_at": wh.get("resolved_at", "") if wh.get("status") == STATUS_RESOLVED else "",
            "wh_received_qty": wh.get("received_qty"),
            "wh_link_status": wh.get("link_status", ""),
            "wh_link_reason": wh.get("link_reason", ""),
            "wh_restock_qty": wh.get("restock_qty", 0),
            "wh_restocked": bool(wh.get("restocked")),
            "wh_stock_effect": wh.get("stock_effect", ""),
            "wh_restock_location_code": wh.get("restock_location_code", ""),
            "wh_item_condition": wh.get("item_condition", ""),
            "wh_sync_ok": True,
            "wh_sync_error": "",
            "wh_sync_at": _now(),
            "updated_at": _now(),
        }})
    except Exception as e:  # noqa: BLE001
        # Jangan gagalkan pekerjaan fisik gudang karena balikan ke Marketing gagal,
        # TAPI jangan diam: kalau ini gagal, layar Toko akan menyangka retur belum
        # ditangani padahal stok sudah bertambah.
        logger.error("[retur-jembatan] gagal menandai retur Marketing %s: %s",
                     marketing_return_id, e)


# ═════════════════════════════════════════════════════════════════════════════
# RESTOCK (satu pintu `core/stock_service`)
# ═════════════════════════════════════════════════════════════════════════════
async def _unit_cost_for(db, mid: str) -> float:
    from core import fg_cost_layers as fcl
    snap = await fcl.hpp_snapshot(db, mid)
    unit_cost = float(snap.get("hpp_fifo_avg") or snap.get("hpp_last_batch") or 0)
    if unit_cost <= 0:
        mat = await db.rahaza_materials.find_one({"id": mid}, {"_id": 0, "hpp": 1, "unit_cost": 1}) or {}
        unit_cost = float(mat.get("hpp") or mat.get("unit_cost") or 0)
    return round(unit_cost, 2)


async def _value_damaged(db, wh_ret: dict, mid: str, qty: int, actor: dict,
                         disposed: bool = False) -> dict:
    """Retur rusak → karantina (nilai 0): reklas HPP menjadi Kerugian Retur Rusak (Iter 122).

    2026-11-02 (owner No.26a): nilai = qty × WAC FG saat keputusan (`fcl.wac_state`).
    K40: `disposed=True` = keputusan "Dibuang" — jurnal sama (Dr 6-1300 / Cr 5-1000
    senilai WAC), barang TIDAK masuk stok. Pemanggil: `routes/dewi_wh_returns.resolve_return`
    untuk aksi "Dibuang / Dispose" (hasilnya `loss_*`, sehingga Balik Keputusan ikut
    membuat jurnal pembaliknya)."""
    from core import fg_cost_layers as fcl
    from routes.rahaza_posting import post_return_damaged_loss
    out = {"loss_unit_cost": 0.0, "loss_amount": 0.0, "loss_je_id": None,
           "loss_je_number": None, "loss_post_error": None, "loss_basis": "wac",
           "loss_kind": "disposed" if disposed else "damaged"}
    try:
        unit_cost = (await fcl.wac_state(db, mid, actor=actor))["unit_cost"]   # WAC 4 desimal; jurnal dibulatkan per total
        out["loss_unit_cost"] = unit_cost
        out["loss_amount"] = round(unit_cost * qty, 2)
        je = await post_return_damaged_loss(db, wh_ret, qty, unit_cost, actor or {}, disposed=disposed)
        out["loss_je_id"] = je.get("je_id")
        out["loss_je_number"] = je.get("je_number")
        out["loss_post_error"] = None if je.get("ok") else je.get("error")
    except Exception as e:  # noqa: BLE001
        logger.error("[retur-jembatan] kerugian retur %s %s gagal: %s",
                     out["loss_kind"], wh_ret.get("return_code"), e)
        out["loss_post_error"] = str(e)
    return out


async def _value_restock(db, wh_ret: dict, mid: str, qty: int, actor: dict) -> dict:
    """Lapisan HPP + jurnal balik HPP untuk retur yang kembali ke stok jual.

    2026-11-02 (owner No.26a / K15): nilai = qty × WAC FG saat keputusan gudang. Barang
    masuk lewat `fcl.push_layer` (penerimaan WAC; biayanya = WAC sehingga WAC tidak
    bergeser kecuali stok sedang minus/kosong) + Dr 1-1404 / Cr HPP senilai sama."""
    from core import fg_cost_layers as fcl
    from routes.rahaza_posting import post_marketplace_return_restock
    out = {"hpp_unit_cost": 0.0, "hpp_layer_id": None, "cogs_je_id": None,
           "cogs_je_number": None, "cogs_post_error": None, "hpp_basis": "wac"}
    try:
        state = await fcl.wac_state(db, mid, actor=actor)
        unit_cost = state["unit_cost"]   # biaya masuk = WAC persis → WAC tidak bergeser
        out["hpp_unit_cost"] = unit_cost
        ref = {"type": "wh_return_restock", "id": wh_ret["id"],
               "return_code": wh_ret.get("return_code", ""),
               "marketing_return_id": wh_ret.get("source_marketing_return_id")}
        if unit_cost > 0:
            layer = await fcl.push_layer(db, material_id=mid, qty=qty, ref=ref, actor=actor,
                                         unit_cost=unit_cost, components=state["components"],
                                         breakdown={"source": "marketplace_return", "unit_cost": unit_cost})
            out["hpp_layer_id"] = (layer or {}).get("id")
        je = await post_marketplace_return_restock(db, wh_ret, qty, unit_cost, actor or {})
        out["cogs_je_id"] = je.get("je_id")
        out["cogs_je_number"] = je.get("je_number")
        out["cogs_post_error"] = None if je.get("ok") else je.get("error")
        # 2026-11-02 — lapisan restock DITAUTKAN ke jurnalnya (Dr 1-1404). Dulu `gl_je_id`
        # kosong sehingga Laporan Nilai FG menghitungnya "belum berjurnal" (palsu 110.994,50
        # di uji audit g.md T5) walau nilainya sudah ada di GL.
        if je.get("ok") and je.get("je_id") and out["hpp_layer_id"]:
            await db[fcl.LAYERS].update_one({"id": out["hpp_layer_id"]}, {"$set": {
                "gl_je_id": je["je_id"], "gl_basis": "wh_return_restock"}})
    except Exception as e:  # noqa: BLE001
        logger.error("[retur-jembatan] nilai HPP retur %s gagal: %s", wh_ret.get("return_code"), e)
        out["cogs_post_error"] = str(e)
    return out


async def restock(db, wh_ret: dict, *, condition=None, qty=None, actor=None,
                  note: str = "") -> dict:
    """Tambah stok barang retur. IDEMPOTEN & guarded.

    · Penjaga atomik `restocked` dipasang SEBELUM stok ditambah supaya klik ganda
      / dua proses paralel tidak pernah menambah stok dua kali.
    · Barang Baik → `ZNA-FG` (ikut stok jual). Barang Rusak → `ZNA-KARANTINA`
      (dikecualikan dari stok jual oleh K-6a) ⇒ barang rusak tidak bisa terjual.
    """
    actor = actor or {}
    mid = wh_ret.get("material_id") or wh_ret.get("fg_material_id")
    if not mid:
        raise ReturnBridgeError(
            "Retur ini belum tertaut master barang jadi, jadi stok tidak bisa "
            "ditambah. Pilih produknya dari katalog di retur Marketing, atau "
            "petakan SKU-nya lewat Jembatan SKU.")
    cond = normalize_condition(condition if condition is not None
                               else wh_ret.get("item_condition"))
    n = max(1, _int(qty if qty is not None else wh_ret.get("qty"), 1))
    loc = await resolve_location(db, cond)

    # ── penjaga idempotensi (atomik) ──────────────────────────────────────────
    claim = await db[WH].update_one(
        {"id": wh_ret["id"], "restocked": {"$ne": True}},
        {"$set": {"restocked": True, "restock_claimed_at": _now_iso()}})
    if claim.matched_count == 0:
        cur = await db[WH].find_one({"id": wh_ret["id"]}, {"_id": 0})
        return {"restocked": False, "already": True, "wh_return": cur,
                "message": "Stok retur ini sudah pernah ditambahkan (tidak digandakan)."}

    snap = await _material_snapshot(db, mid)
    # 2026-11-02 — kosakata kategori/kepemilikan SAMA dengan pembaca stok jual
    # (`/api/sales/fg-stock` & Fulfillment menyaring `inventory_category=fg_internal`,
    # Fulfillment juga `ownership=cv_da`) dan dengan penulis FG lain
    # (`production_qty_ledger.post_fg_accepted`, `sales_direct` retur). Dulu
    # `finished_goods/own` — kosakata yang tidak dibaca siapa pun.
    # Barang RUSAK (karantina) sengaja TANPA `inventory_category`, sama seperti penulis
    # karantina lain (`core/quarantine`), supaya tidak ikut terhitung stok jual.
    stock_meta = {
        "material_code": snap.get("material_code", ""),
        "material_name": snap.get("material_name", ""),
        "material_type": snap.get("material_type", "fg"),
        "unit": snap.get("unit", "pcs"),
        "category_name": snap.get("category_name", ""),
        "location_code": loc["code"],
        "ownership": "cv_da",
    }
    if loc["sellable"]:
        stock_meta["inventory_category"] = "fg_internal"
    try:
        row = await stock_service.add(
            mid, loc["id"], n,
            meta=stock_meta,
            ref={
                "type": "wh_return_restock",
                "ref_id": wh_ret["id"],
                "ref_no": wh_ret.get("return_code", ""),
                "marketing_return_id": wh_ret.get("source_marketing_return_id"),
                "order_number": wh_ret.get("order_number", ""),
                "condition": cond,
            },
            actor={"id": actor.get("id"), "name": _actor_name(actor)},
            db=db,
        )
    except Exception as e:
        # Batalkan klaim supaya retur bisa dicoba lagi setelah masalahnya beres —
        # kalau flag dibiarkan menyala, barang fisik ada tapi stoknya tak pernah
        # bisa dimasukkan lagi oleh siapa pun.
        await db[WH].update_one({"id": wh_ret["id"]},
                                {"$set": {"restocked": False},
                                 "$unset": {"restock_claimed_at": ""}})
        logger.error("[retur-jembatan] restock GAGAL untuk %s: %s",
                     wh_ret.get("return_code"), e)
        raise

    effect = "sellable" if loc["sellable"] else "quarantine"

    # ── Iter 121 (B-08): barang retur kondisi baik masuk stok jual HARUS bernilai ──
    # lapisan HPP (biaya = HPP FIFO saat ini) + JE Dr FG / Cr HPP. Gagal jurnal tidak
    # membatalkan restock (barang fisik sudah masuk) tetapi dicatat di dokumen retur.
    hpp = {}
    if loc["sellable"]:
        hpp = await _value_restock(db, wh_ret, mid, n, actor)
    else:
        hpp = await _value_damaged(db, wh_ret, mid, n, actor)

    patch = {
        "restock_qty": n,
        **hpp,
        "restock_at": _now_iso(),
        "restock_by": _actor_name(actor),
        "restock_location_id": loc["id"],
        "restock_location_code": loc["code"],
        "restock_location_name": loc["name"],
        "restock_condition": cond,
        "stock_effect": effect,
        "material_id": mid,
        "fg_material_id": mid,
        "sku_code": wh_ret.get("sku_code") or snap.get("material_code", ""),
        "product_name": wh_ret.get("product_name") or snap.get("material_name", ""),
        "updated_at": _now_iso(),
    }
    await db[WH].update_one({"id": wh_ret["id"]}, {"$set": patch, "$push": {"timeline": {
        "status": wh_ret.get("status", "Resolved"), "at": _now_iso(),
        "by": _actor_name(actor),
        "note": (f"Stok +{n} {snap.get('unit', 'pcs')} {snap.get('material_code', '')} "
                 f"→ {loc['name']} ({loc['code']}) · kondisi {cond} · "
                 f"{'ikut stok jual' if loc['sellable'] else 'TIDAK dijual (karantina)'}"
                 + (f" · {note}" if note else "")),
    }}})

    await refresh_catalog_cache(db, mid)
    fresh = await db[WH].find_one({"id": wh_ret["id"]}, {"_id": 0})
    return {
        "restocked": True,
        "already": False,
        "qty": n,
        "condition": cond,
        "location": loc,
        "stock_effect": effect,
        "onhand_after": float((row or {}).get("qty") or 0),
        "wh_return": fresh,
        "message": (f"Stok +{n} → {loc['name']} ({loc['code']}) · kondisi {cond}"
                    + ("" if loc["sellable"] else " · tidak dijual (karantina)")),
    }


async def refresh_catalog_cache(db, material_id: str) -> int:
    """Segarkan cache stok jual item katalog yang memakai material ini (K-7a).

    Stok jual dihitung LIVE saat katalog dibaca, tetapi cache-nya dipakai untuk
    daftar & lencana "stok rendah". Kalau tidak disegarkan, layar Toko masih
    menunjukkan angka lama sesaat setelah retur masuk.
    """
    try:
        from core import catalog_stock as _cs
        items = await db.marketing_catalog_items.find(
            {"$or": [{"fg_material_id": material_id}, {"material_id": material_id}]},
            {"_id": 0}).to_list(200)
        blocked = await _cs.blocked_location_ids(db)
        n = 0
        for it in items:
            await _cs.sync_item_cache(db, it, blocked_locs=blocked)
            n += 1
        return n
    except Exception as e:  # noqa: BLE001
        logger.error("[retur-jembatan] gagal menyegarkan cache stok katalog %s: %s",
                     material_id, e)
        return 0


# ═════════════════════════════════════════════════════════════════════════════
# PROSES OTOMATIS: terima → inspeksi → selesai + restock
# ═════════════════════════════════════════════════════════════════════════════
async def auto_process(db, wh_return_id: str, *, condition=None, qty=None,
                       actor=None, note: str = "") -> dict:
    """Terima + periksa + putuskan dalam satu langkah (tombol gudang "Terima & Putuskan").

    2026-11-02 (K1) — sejak W4 dicabut, fungsi ini TIDAK lagi dipanggil saat retur
    Marketing dibuat; ia hanya dipakai GUDANG (`/quick-restock`) sebagai keputusan
    cepat dengan qty AKTUAL. Timeline tetap ditulis langkah-per-langkah
    (Received → Inspected → Resolved) supaya jejak auditnya sama lengkap dengan
    proses manual. Qty keputusan tidak boleh melebihi qty yang diterima.
    """
    actor = actor or {}
    who = _actor_name(actor)
    doc = await db[WH].find_one({"id": wh_return_id}, {"_id": 0})
    if not doc:
        raise ReturnBridgeError(f"Retur fisik {wh_return_id} tidak ditemukan")
    if doc.get("restocked"):
        return {"restocked": False, "already": True, "wh_return": doc,
                "message": "Stok retur ini sudah pernah ditambahkan (tidak digandakan)."}
    if doc.get("status") not in OPEN_STATUSES:
        raise ReturnBridgeError(
            f"Retur fisik {doc.get('return_code')} berstatus '{doc.get('status')}' — "
            "hanya pekerjaan yang belum diputuskan yang bisa diproses.")

    cond = normalize_condition(condition if condition is not None
                               else doc.get("item_condition"))
    n = decision_qty(doc, qty)
    sellable = is_sellable_condition(cond)
    action = ACTION_RESTOCK if sellable else ACTION_QUARANTINE

    steps = [
        {"status": "Received", "at": _now_iso(), "by": who,
         "note": f"Barang retur diterima gudang · qty aktual {n}"},
        {"status": "Inspected", "at": _now_iso(), "by": who,
         "note": f"Kondisi: {cond} · Rekomendasi: {action}"},
        {"status": "Resolved", "at": _now_iso(), "by": who,
         "note": f"Keputusan gudang: {action}" + (f" · {note}" if note else "")},
    ]
    await db[WH].update_one({"id": wh_return_id}, {
        "$set": {
            "status": "Resolved",
            "received_at": doc.get("received_at") or _now_iso(),
            "received_by": doc.get("received_by") or who,
            "received_qty": doc.get("received_qty") if doc.get("received_qty") is not None else n,
            "unboxing_condition_notes": (doc.get("unboxing_condition_notes")
                                         or "Diterima & diputuskan cepat oleh gudang"),
            "package_condition": "",
            "inspected_at": _now_iso(), "inspected_by": who,
            "item_condition": cond,
            "return_cause": doc.get("return_cause") or "Kesalahan Customer",
            "cause_detail": doc.get("initial_reason") or "",
            "recommended_action": action,
            "resolved_at": _now_iso(), "resolved_by": who,
            "action_taken": action,
            "action_notes": note or "Keputusan cepat gudang (Terima & Putuskan)",
            "auto_processed": True,
            "updated_at": _now_iso(),
        },
        "$push": {"timeline": {"$each": steps}},
    })

    fresh = await db[WH].find_one({"id": wh_return_id}, {"_id": 0})
    res = await restock(db, fresh, condition=cond, qty=n, actor=actor, note=note)
    if res.get("wh_return") and doc.get("source_marketing_return_id"):
        await _stamp_marketing(db, doc["source_marketing_return_id"], res["wh_return"])
    await close_pending_notifs(db, wh_return_id)   # 2026-11-02 (K30)
    return res


# ═════════════════════════════════════════════════════════════════════════════
# BACKFILL: tarik retur Marketing yang belum pernah dijembatani
# ═════════════════════════════════════════════════════════════════════════════
SKIP_STATUSES = {"rejected", "cancelled"}


async def sync_all(db, *, actor=None, dry_run: bool = False,
                   auto_restock: bool = False, condition=None,
                   limit: int = 500) -> dict:
    """Jembatani SEMUA retur Marketing yang belum punya pekerjaan gudang.

    Retur berstatus `rejected`/`cancelled` DILEWATI: barangnya memang tidak
    kembali, jadi menambah stok untuknya akan berbohong.
    """
    q = {"status": {"$nin": list(SKIP_STATUSES)}}
    rets = await db[MKT].find(q, {"_id": 0}).sort("date", -1).to_list(limit)
    out = {"scanned": len(rets), "created": 0, "already": 0, "restocked": 0,
           "skipped": 0, "failed": 0, "dry_run": bool(dry_run), "details": []}
    for r in rets:
        wh_exists = await db[WH].find_one({"source_marketing_return_id": r["id"]},
                                          {"_id": 0, "id": 1, "return_code": 1,
                                           "restocked": 1})
        if wh_exists and not dry_run:
            out["already"] += 1
            continue
        if dry_run:
            ident = await resolve_identity(db, r)
            out["details"].append({
                "marketing_return_id": r["id"], "order_id": r.get("order_id"),
                "product": r.get("product"), "link_status": ident["link_status"],
                "material_code": ident.get("material_code"), "qty": ident.get("qty"),
                "reason": ident.get("reason"),
                "already": bool(wh_exists),
            })
            if wh_exists:
                out["already"] += 1
            elif ident["link_status"] == LINK_OK:
                out["created"] += 1
            else:
                out["skipped"] += 1
            continue
        try:
            res = await ensure_wh_return(db, r, actor=actor, condition=condition,
                                        auto_restock=auto_restock)
            if res.get("created"):
                out["created"] += 1
            else:
                out["already"] += 1
            if res.get("restocked"):
                out["restocked"] += 1
            wh = res.get("wh_return") or {}
            if wh.get("link_status") != LINK_OK:
                out["skipped"] += 1
            out["details"].append({
                "marketing_return_id": r["id"], "order_id": r.get("order_id"),
                "wh_return_code": wh.get("return_code"),
                "link_status": wh.get("link_status"),
                "restocked": bool(wh.get("restocked")),
                "stock_effect": wh.get("stock_effect", ""),
                "message": res.get("message", ""),
            })
        except Exception as e:  # noqa: BLE001
            out["failed"] += 1
            out["details"].append({"marketing_return_id": r["id"], "error": str(e)[:300]})
            logger.error("[retur-jembatan] gagal menjembatani retur %s: %s", r["id"], e)
    return out


# ═════════════════════════════════════════════════════════════════════════════
# 2026-11-02 (K1) — QTY KEPUTUSAN, PEMBATALAN DARI MARKETING, PEMBALIKAN KEPUTUSAN
# ═════════════════════════════════════════════════════════════════════════════
def decision_qty(doc: dict, qty=None) -> int:
    """Qty yang diputuskan gudang. Bawaan = qty DITERIMA (langkah Terima); bila
    belum diterima, qty pengajuan. Harus 1 ≤ qty ≤ batas itu — dulu `restock_qty`
    tanpa batas dan qty 0 diam-diam menjadi 1 (`max(1, …)`)."""
    rq = (doc or {}).get("received_qty")
    limit = _int(rq) if rq not in (None, "") else max(1, _int((doc or {}).get("qty"), 1))
    n = limit if qty in (None, "") else _int(qty, -1)
    if n < 1:
        raise ReturnBridgeError(
            "Qty keputusan minimal 1 pcs. Bila tidak ada barang yang layak masuk stok, "
            f"pilih '{ACTION_REJECT_TO_BUYER}' atau '{ACTION_DISPOSE}'.")
    if n > limit:
        raise ReturnBridgeError(
            f"Qty keputusan {n} melebihi qty yang diterima gudang ({limit} pcs).")
    return n


def is_decided(wh: dict) -> bool:
    """Sudah ada keputusan gudang yang berlaku (bukan dibatalkan/dibalik)?"""
    return (wh or {}).get("status") == STATUS_RESOLVED


async def cancel_for_marketing_return(db, ret: dict, *, actor=None,
                                      reason: str = "") -> dict:
    """K1 — Marketing MENOLAK/MENGHAPUS retur.

    * Pekerjaan gudang BELUM diputuskan (Pending/Received/Inspected) ⇒ DIBATALKAN
      (status Cancelled, berjejak di timeline) — tidak ada stok/jurnal yang perlu dibalik.
    * SUDAH diputuskan ⇒ TIDAK diubah di sini; dokumen gudang diberi tanda
      ``marketing_rejected_after_decision`` supaya gudang membaliknya lewat
      :func:`reverse_decision` (jurnal pembalik + stok keluar berjejak).

    → ``{"state": none|cancelled|decided|closed, "wh_return": dict|None, "message"}``
    """
    wh = await find_linked_wh(db, ret)
    if not wh:
        return {"state": "none", "wh_return": None, "message": ""}
    who = _actor_name(actor)
    code = wh.get("return_code") or wh.get("id")
    status = wh.get("status") or STATUS_PENDING
    if status in OPEN_STATUSES:
        note = (f"Dibatalkan karena retur Marketing {reason or 'ditolak/dihapus'} "
                "sebelum gudang memutuskan (K1)")
        await db[WH].update_one({"id": wh["id"], "status": {"$in": list(OPEN_STATUSES)}}, {
            "$set": {"status": STATUS_CANCELLED, "cancelled_at": _now_iso(),
                     "cancelled_by": who, "cancel_reason": note,
                     "cancelled_by_marketing": True, "updated_at": _now_iso()},
            "$push": {"timeline": {"status": STATUS_CANCELLED, "at": _now_iso(),
                                   "by": who, "note": note}}})
        fresh = await db[WH].find_one({"id": wh["id"]}, {"_id": 0}) or wh
        await close_pending_notifs(db, wh["id"])   # 2026-11-02 (K30)
        return {"state": "cancelled", "wh_return": fresh,
                "message": f"Pekerjaan Retur Fisik {code} di Gudang ikut dibatalkan."}
    if status == STATUS_RESOLVED:
        await db[WH].update_one({"id": wh["id"]}, {
            "$set": {"marketing_rejected_after_decision": True,
                     "marketing_rejected_at": _now_iso(), "updated_at": _now_iso()},
            "$push": {"timeline": {"status": status, "at": _now_iso(), "by": who,
                                   "note": ("Marketing menandai retur ini "
                                            f"{reason or 'ditolak'} SETELAH keputusan gudang — "
                                            "balik keputusan bila barang harus keluar lagi")}}})
        return {"state": "decided", "wh_return": wh,
                "message": (f"Retur Fisik {code} SUDAH diputuskan gudang "
                            f"({wh.get('action_taken') or '-'}). Stok & jurnalnya tidak diubah "
                            "otomatis — minta Gudang menekan 'Balik Keputusan' (jurnal pembalik + "
                            "stok keluar berjejak).")}
    return {"state": "closed", "wh_return": wh, "message": ""}


async def _post_reversal_je(db, je_id: str, wh: dict, actor: dict, reason: str) -> dict:
    """Jurnal PEMBALIK satu jurnal retur (debit ⇄ kredit), idempoten per jurnal asal."""
    from datetime import date
    from routes.rahaza_posting import _create_posted_je, _find_existing_je
    je = await db.rahaza_journal_entries.find_one({"id": je_id}, {"_id": 0})
    if not je:
        return {"ok": False, "skipped": True, "error": f"jurnal {je_id} tidak ada"}
    if je.get("status") != "posted":
        return {"ok": False, "skipped": True,
                "error": f"jurnal {je.get('je_number')} berstatus {je.get('status')} — tidak dibalik"}
    source_ref = f"whret_reverse:{je_id}"
    existing = await _find_existing_je(db, "wh_return_reversal", source_ref)
    if existing:
        return {"ok": True, "already": True, "je_id": existing["id"],
                "je_number": existing.get("je_number")}
    code = wh.get("return_code") or wh.get("id")
    lines = [{"account_code": ln.get("account_code"),
              "debit": float(ln.get("credit") or 0), "credit": float(ln.get("debit") or 0),
              "description": f"Balik {je.get('je_number')} — retur {code}: {reason}"[:200]}
             for ln in (je.get("lines") or [])]
    return await _create_posted_je(db, date.today(),
                                   f"Pembalik keputusan retur {code} ({je.get('je_number')})",
                                   "wh_return_reversal", source_ref, lines, actor or {})


async def _unwind_restock_layer(db, wh: dict, qty: int, actor: dict) -> dict:
    """Lapisan HPP yang dibuat restock dikurangi sebanyak qty yang keluar lagi
    (supaya Laporan Nilai FG tidak memuat barang yang sudah dikeluarkan)."""
    from core import fg_cost_layers as fcl
    lid = wh.get("hpp_layer_id")
    if not lid or qty <= 0:
        return {"layer_id": lid, "qty": 0}
    layer = await db[fcl.LAYERS].find_one({"id": lid}, {"_id": 0}) or {}
    take = min(int(qty), _int(layer.get("qty_remaining")))
    if take > 0:
        await db[fcl.LAYERS].update_one({"id": lid}, {"$inc": {"qty_remaining": -take},
                                                      "$set": {"updated_at": _now()}})
        await db[fcl.CONSUMPTIONS].insert_one({
            "id": _uid(), "material_id": wh.get("material_id") or wh.get("fg_material_id"),
            "qty": take, "cogs": round(float(layer.get("unit_cost") or 0) * take, 2),
            "uncosted_qty": max(0, int(qty) - take),
            "layers_used": [{"layer_id": lid, "qty": take,
                             "unit_cost": float(layer.get("unit_cost") or 0)}],
            "ref": {"type": "wh_return_reversal", "id": wh.get("id"),
                    "return_code": wh.get("return_code")},
            "actor": _actor_name(actor), "created_at": _now()})
    return {"layer_id": lid, "qty": take, "short": max(0, int(qty) - take)}


async def reverse_decision(db, wh_return_id: str, *, actor=None, reason: str = "",
                           reopen: bool = True) -> dict:
    """K1 — BALIK keputusan gudang yang sudah dibukukan.

    Satu-satunya jalan mengubah keputusan yang sudah menggerakkan stok/jurnal:
      1. stok yang dulu masuk DIKELUARKAN lagi lewat `stock_service.issue`
         (ref ``wh_return_reversal`` ⇒ berjejak di ledger);
      2. setiap jurnal keputusan (balik HPP / kerugian rusak) dibuatkan JURNAL
         PEMBALIK (debit ⇄ kredit), bukan dihapus/di-void;
      3. dokumen lama menjadi ``Reversed``; bila ``reopen`` (bawaan), pekerjaan BARU
         dibuka berstatus Received (barang fisik masih di gudang) untuk diputuskan
         ulang — dokumen baru = kunci idempoten jurnal baru, jadi tidak bertabrakan
         dengan jurnal keputusan lama.
    """
    actor = actor or {}
    who = _actor_name(actor)
    reason = (reason or "").strip()
    if not reason:
        raise ReturnBridgeError("Alasan pembalikan keputusan wajib diisi.")
    doc = await db[WH].find_one({"id": wh_return_id}, {"_id": 0})
    if not doc:
        raise ReturnBridgeError(f"Retur fisik {wh_return_id} tidak ditemukan")
    if doc.get("status") != STATUS_RESOLVED:
        raise ReturnBridgeError(
            f"Hanya keputusan yang sudah Resolved yang bisa dibalik (status sekarang "
            f"'{doc.get('status')}'). Pekerjaan yang belum diputuskan cukup dibatalkan.")
    claim = await db[WH].update_one(
        {"id": wh_return_id, "status": STATUS_RESOLVED, "reversal_claimed": {"$ne": True}},
        {"$set": {"reversal_claimed": True, "updated_at": _now_iso()}})
    if not claim.matched_count:
        raise ReturnBridgeError("Keputusan ini sedang/sudah dibalik oleh permintaan lain.")

    code = doc.get("return_code") or doc.get("id")
    mid = doc.get("material_id") or doc.get("fg_material_id")
    qty = _int(doc.get("restock_qty"))
    stock_out = None
    if doc.get("restocked") and qty > 0 and mid and doc.get("restock_location_id"):
        try:
            row = await stock_service.issue(
                mid, doc["restock_location_id"], qty,
                ref={"type": "wh_return_reversal", "ref_id": doc["id"], "ref_no": code,
                     "marketing_return_id": doc.get("source_marketing_return_id"),
                     "reason": reason},
                actor={"id": actor.get("id"), "name": who}, db=db)
            stock_out = {"qty": qty, "location_code": doc.get("restock_location_code"),
                         "onhand_after": float((row or {}).get("qty") or 0)}
        except Exception as e:
            await db[WH].update_one({"id": wh_return_id}, {"$set": {"reversal_claimed": False}})
            raise ReturnBridgeError(
                f"Stok {qty} pcs di {doc.get('restock_location_code') or 'lokasi restock'} tidak "
                f"bisa dikeluarkan lagi ({e}). Barangnya mungkin sudah terjual/berpindah — "
                "koreksi lewat Stock Opname, bukan lewat pembalikan retur.") from e
    layer = await _unwind_restock_layer(db, doc, qty, actor) if stock_out else None
    # 2026-11-02 (owner No.26a): penerimaan WAC restock ikut DIBATALKAN pada biaya asalnya
    # (`hpp_unit_cost`) — cermin jurnal pembalik di bawah (Dr 5-1000 / Cr 1-1404 senilai sama),
    # sehingga WAC kembali dan Σ stok × WAC tetap = saldo GL 1-1404 (selisih 0). Hanya untuk
    # restock ke stok jual; karantina bernilai 0 dan tidak pernah masuk WAC.
    wac_reversal = None
    unit_in = float(doc.get("hpp_unit_cost") or 0)
    if stock_out and mid and unit_in > 0 and doc.get("stock_effect") == "sellable":
        from core import fg_cost_layers as fcl
        try:
            res_w = await fcl.reverse_receipt(
                db, material_id=mid, qty=qty, unit_cost=unit_in, actor=actor,
                ref={"type": "wh_return_reversal", "id": doc["id"], "return_code": code})
            wac_reversal = {k: res_w.get(k) for k in ("unit_cost", "wac_before", "qty_after",
                                                       "adjustment_fg", "rule")}
            wac_reversal["adjustment_je_id"] = (res_w.get("adjustment_je") or {}).get("je_id")
        except Exception as e:  # noqa: BLE001 — stok sudah keluar; galat WAC dicatat, tidak ditelan
            logger.error("[retur-jembatan] pembalikan WAC %s gagal: %s", code, e)
            wac_reversal = {"error": str(e)}

    reversals = []
    for key in ("cogs_je_id", "loss_je_id"):
        je_id = doc.get(key)
        if not je_id:
            continue
        try:
            res = await _post_reversal_je(db, je_id, doc, actor, reason)
        except Exception as e:  # noqa: BLE001 — stok sudah keluar; galat jurnal dicatat
            res = {"ok": False, "error": str(e)}
        reversals.append({"of": key, "je_id": je_id, "ok": bool(res.get("ok")),
                          "reversal_je_id": res.get("je_id"),
                          "reversal_je_number": res.get("je_number"),
                          "error": None if res.get("ok") else res.get("error")})

    note = (f"Keputusan '{doc.get('action_taken')}' DIBALIK: {reason}"
            + (f" · stok −{qty} dari {doc.get('restock_location_code')}" if stock_out else "")
            + "".join(f" · pembalik {r['reversal_je_number']}" for r in reversals
                      if r.get("reversal_je_number")))
    await db[WH].update_one({"id": wh_return_id}, {
        "$set": {"status": STATUS_REVERSED, "decision_reversed_at": _now_iso(),
                 "decision_reversed_by": who, "decision_reversed_reason": reason,
                 "reversal_stock_out": stock_out, "reversal_layer": layer,
                 "reversal_wac": wac_reversal,
                 "reversal_journals": reversals, "restocked": False,
                 "restock_reversed": bool(stock_out), "updated_at": _now_iso()},
        "$push": {"timeline": {"status": STATUS_REVERSED, "at": _now_iso(), "by": who,
                               "note": note}}})

    new_doc = None
    if reopen:
        new_code = await _next_code(db)
        keep = ("return_type", "order_number", "resi_number", "channel", "customer_name",
                "customer_contact", "sku_code", "product_name", "qty", "order_value",
                "initial_reason", "notes", "material_id", "fg_material_id", "variant_id",
                "catalog_item_id", "material_unit", "material_category", "material_color",
                "material_option", "link_status", "link_reason", "link_source",
                "link_candidates", "source", "source_marketing_return_id",
                "source_marketing_order_id", "source_account_name", "reported_condition",
                "rts", "source_order_doc_id", "source_order_line", "account_id")
        new_doc = _wh_skeleton(new_code, who,
                               f"Dibuka ulang dari {code} setelah keputusan dibalik: {reason}")
        new_doc.update({k: doc.get(k) for k in keep if k in doc})
        if new_doc.get("source_order_line") is not None:
            # kunci idempoten RTS (pesanan, baris) tetap milik dokumen lama
            new_doc["source_order_line"] = f"{doc.get('source_order_line')}-ulang"
        new_doc.update({
            "status": "Received",
            "received_at": _now_iso(), "received_by": who,
            "received_qty": (doc.get("received_qty") if doc.get("received_qty") is not None
                             else doc.get("qty")),
            "unboxing_condition_notes": f"Barang fisik masih di gudang (dibuka ulang dari {code})",
            "supersedes_wh_return_id": doc["id"],
        })
        new_doc["timeline"].append({"status": "Received", "at": _now_iso(), "by": who,
                                    "note": "Siap diperiksa & diputuskan ulang"})
        await db[WH].insert_one(new_doc)
        new_doc.pop("_id", None)
        await db[WH].update_one({"id": wh_return_id}, {"$set": {"superseded_by": new_doc["id"]}})
        await notify_pending(db, new_doc, actor=actor)   # 2026-11-02 (K30): putuskan ulang

    if mid and stock_out:
        await refresh_catalog_cache(db, mid)
    final_old = await db[WH].find_one({"id": wh_return_id}, {"_id": 0})
    if doc.get("source_marketing_return_id"):
        await _stamp_marketing(db, doc["source_marketing_return_id"], new_doc or final_old)
    return {"reversed": True, "wh_return": final_old, "reopened": new_doc,
            "stock_out": stock_out, "journals": reversals, "wac": wac_reversal,
            "message": note + (f" · dibuka ulang sebagai {new_doc['return_code']}" if new_doc else "")}


# ═════════════════════════════════════════════════════════════════════════════
# 2026-11-02 (K6) — PEMBATALAN SETELAH KIRIM ⇒ PENGAJUAN RETUR FISIK "RTS"
# ═════════════════════════════════════════════════════════════════════════════
SHIPPED_STATUSES = ("shipped", "delivered", "completed")
SHIPPED_STAMPS = ("shipped_date", "shipped_at", "delivered_date", "completed_date")


def was_shipped(order: dict) -> bool:
    """Paket sudah diambil kurir? (status kirim/selesai, atau stempel tanggal kirimnya ada)."""
    o = order or {}
    if str(o.get("status") or "").strip().lower() in SHIPPED_STATUSES:
        return True
    return any(o.get(k) for k in SHIPPED_STAMPS)


async def ensure_rts_returns(db, order: dict, *, actor=None, reason: str = "") -> dict:
    """Pesanan DIBATALKAN SETELAH DIKIRIM (gagal kirim / RTS) ⇒ satu pengajuan Retur
    Fisik **Pending** per baris barang. Tanpa stok & jurnal: stok baru masuk saat
    gudang Terima → Periksa → Putuskan (alur K1). Idempoten per (pesanan, baris)."""
    actor = actor or {}
    who = _actor_name(actor)
    lines = [ln for ln in (order.get("items") or []) if isinstance(ln, dict)]
    if not lines:
        lines = [{"fg_material_id": order.get("fg_material_id"),
                  "quantity": order.get("quantity"), "sku_code": order.get("sku_id"),
                  "product_name": order.get("product_name")}]
    created, existing = [], []
    for idx, ln in enumerate(lines, start=1):
        found = await db[WH].find_one({"source_order_doc_id": order.get("id"),
                                       "source_order_line": idx}, {"_id": 0})
        if found:
            existing.append(found.get("return_code"))
            continue
        raw_q = ln.get("quantity") if ln.get("quantity") is not None else ln.get("qty")
        qty = max(1, _int(raw_q, 1))
        mid = ln.get("fg_material_id") or ln.get("material_id")
        snap = await _material_snapshot(db, mid) if mid else {}
        sku = (ln.get("sku_code") or ln.get("seller_sku") or ln.get("sku") or "").strip()
        name = (ln.get("product_name") or ln.get("product_name_raw") or "").strip()
        code = await _next_code(db)
        doc = _wh_skeleton(code, who, (
            f"RTS otomatis: pesanan {order.get('order_id') or '-'} dibatalkan SETELAH dikirim"
            + (f" ({reason})" if reason else "") + " — menunggu paket kembali ke gudang"))
        doc.update({
            "return_type": "expedition_return",
            "rts": True,
            "order_number": order.get("order_id") or "",
            "resi_number": order.get("tracking_number") or "",
            "channel": order.get("platform") or "",
            "customer_name": (order.get("customer_name") or order.get("buyer_username")
                              or "Pembeli Marketplace"),
            "customer_contact": "",
            "sku_code": snap.get("material_code") or sku,
            "product_name": snap.get("material_name") or name,
            "qty": qty,
            "order_value": float(ln.get("sku_subtotal_after_discount") or ln.get("price") or 0),
            "initial_reason": reason or "Pesanan dibatalkan setelah dikirim (gagal kirim/RTS)",
            "notes": f"Otomatis dari pembatalan pesanan {order.get('order_id') or '-'} baris {idx}",
            "material_id": mid if snap else None,
            "fg_material_id": mid if snap else None,
            "variant_id": ln.get("variant_id") or snap.get("variant_id"),
            "catalog_item_id": ln.get("catalog_item_id"),
            "material_unit": snap.get("unit") or "pcs",
            "material_category": snap.get("category_name") or "",
            "material_color": snap.get("color_name") or "",
            "material_option": snap.get("option_name") or "",
            "link_status": LINK_OK if snap else LINK_NONE,
            "link_reason": "" if snap else (
                "Baris pesanan belum tertaut master barang jadi — petakan SKU-nya lewat "
                "Jembatan SKU sebelum gudang memutuskan."),
            "link_source": "order_item" if snap else "",
            "source": "order_cancel_after_ship",
            "source_order_doc_id": order.get("id"),
            "source_order_line": idx,
            "source_account_name": order.get("account_name") or "",
            "account_id": order.get("account_id"),
        })
        await db[WH].insert_one(doc)
        doc.pop("_id", None)
        await notify_pending(db, doc, actor=actor)   # 2026-11-02 (K30)
        created.append(code)
    if created:
        try:
            await db.marketing_orders.update_one({"id": order.get("id")}, {"$set": {
                "rts_wh_return_codes": existing + created, "rts_created_at": _now()}})
        except Exception as e:  # noqa: BLE001
            logger.error("[retur-RTS] gagal menandai pesanan %s: %s", order.get("order_id"), e)
    return {"created": created, "existing": existing}
