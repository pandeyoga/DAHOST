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

═══════════════════════════════════════════════════════════════════════════════
2026-11-10 — KEPUTUSAN OWNER "WAJIB REFERENSI + TAUTKAN" (retur fisik tanpa dobel)
═══════════════════════════════════════════════════════════════════════════════
  * "Catat retur" manual di gudang WAJIB memilih pesanan yang ADA di `marketing_orders`
    (sumber yang sama dengan :func:`resolve_identity` & :func:`ensure_rts_returns`) lewat
    no. pesanan / resi (:func:`order_lookup`, :func:`prepare_manual_return`); barang diambil
    dari baris pesanan itu (cadangan: master produk jadi bila barisnya belum tertaut, W4).
  * Retur gudang AKTIF (bukan Batal/Dibalik) untuk pesanan/barang yang sama ⇒ catat ulang
    DITOLAK (:class:`ReturnDuplicateError` → 409) dengan nomor retur yang sudah ada.
  * Jembatan Marketing → Gudang (:func:`ensure_wh_return`) MENAUTKAN retur Marketing ke
    retur gudang aktif tanpa retur Marketing (dicatat manual / RTS) untuk pesanan & barang
    yang sama (:func:`find_unlinked_match`) alih-alih membuat pekerjaan kedua.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from core import stock_service
from utils.counters import gen_prefixed_number
from utils.waktu import today_wib

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


# 2026-11-09 (audit gudang G5) — satu kalimat untuk semua jalur keputusan yang menambah stok.
UNLINKED_DECISION_MSG = (
    "Retur ini belum tertaut master barang jadi, jadi stok tidak bisa ditambah. Tekan 'Pilih barang' "
    "di detail retur dan pilih SKU yang benar-benar kembali, lalu putuskan lagi.")


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


async def sellable_location(db, location_id: str) -> dict:
    """2026-11-09 (audit gudang G16) — lokasi pilihan untuk barang retur kondisi BAIK.

    Harus lokasi aktif `rahaza_locations` dan BUKAN lokasi karantina/terblokir (barang baik masuk stok
    jual). Barang rusak tetap ke lokasi berperan karantina (:func:`resolve_location`)."""
    from core.catalog_stock import blocked_location_ids
    loc = await db.rahaza_locations.find_one({"id": location_id, "active": {"$ne": False}},
                                            {"_id": 0, "id": 1, "code": 1, "name": 1})
    if not loc:
        raise ReturnBridgeError("Lokasi simpan retur tidak ditemukan di Struktur Gudang — pilih dari daftar.")
    if loc["id"] in await blocked_location_ids(db):
        raise ReturnBridgeError(f"Lokasi {loc.get('code')} adalah lokasi karantina/terblokir — barang retur "
                                "kondisi baik harus masuk lokasi stok jual.")
    return {"id": loc["id"], "code": loc.get("code") or "", "name": loc.get("name") or loc.get("code") or "",
            "sellable": True}


async def restock_location(db, condition, location_id: str | None = None) -> dict:
    """Lokasi tujuan stok retur: kondisi Baik + lokasi dipilih → lokasi itu; selain itu menurut peran."""
    if location_id and is_sellable_condition(condition):
        return await sellable_location(db, location_id)
    return await resolve_location(db, condition)


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

    # 0) 2026-11-14 — baris pesanan yang DIPILIH di form "Buat refund" (order_doc_id + order_line)
    if ret.get("order_doc_id") and ret.get("order_line"):
        order = await db.marketing_orders.find_one({"id": ret["order_doc_id"]}, {"_id": 0})
        lines = order_lines(order) if order else []
        n = _int(ret.get("order_line"), 0)
        ln = lines[n - 1] if 1 <= n <= len(lines) else None
        mid = (ln or {}).get("fg_material_id") or (ln or {}).get("material_id")
        snap = await _material_snapshot(db, mid) if mid else {}
        if snap:
            out.update(snap)
            out["catalog_item_id"] = ln.get("catalog_item_id") or ret.get("catalog_item_id")
            out["variant_id"] = ln.get("variant_id") or snap.get("variant_id")
            out["link_status"] = LINK_OK
            out["source"] = "order_line"
            return out

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


def alasan_tanpa_retur_fisik(ret: dict) -> str:
    """Alasan retur ini TIDAK butuh pekerjaan Retur Fisik di gudang, atau ``""``.

    2026-11-09 (keputusan owner, kebutuhan lintas-agen AI-impor) — impor "Retur & Refund"
    menurunkan ``goods_returned=False`` untuk jenis "Refund only" (dana kembali TANPA barang
    kembali). Membuat pekerjaan Pending untuknya membuat gudang menunggu paket yang tidak
    pernah datang. Hanya ``False`` yang eksplisit yang dilewati — ``None`` (kolom jenis
    pengembalian tidak ada / retur dari form) tetap dijembatani seperti biasa.
    """
    if (ret or {}).get("goods_returned") is not False:
        return ""
    jenis = str(ret.get("refund_type_raw") or "").strip() or "Refund only"
    return (f"jenis pengembalian “{jenis}” — dana dikembalikan tanpa barang dikirim balik, "
            "jadi tidak ada paket yang perlu diterima gudang dan stok tidak bertambah.")


async def _stamp_skip(db, marketing_return_id: str, alasan: str) -> None:
    """Catat di retur Marketing KENAPA tidak ada Retur Fisik (layar Toko & audit membacanya)."""
    try:
        await db[MKT].update_one({"id": marketing_return_id}, {"$set": {
            "wh_skip_reason": alasan, "wh_sync_ok": True, "wh_sync_error": "",
            "wh_sync_at": _now(), "updated_at": _now()}})
    except Exception as e:  # noqa: BLE001
        logger.error("[retur-jembatan] gagal mencatat alasan tanpa Retur Fisik %s: %s",
                     marketing_return_id, e)


# ═════════════════════════════════════════════════════════════════════════════
# 2026-11-10 (keputusan owner) — RETUR FISIK TANPA DOBEL: wajib pesanan + tautkan
# ═════════════════════════════════════════════════════════════════════════════
# Retur yang tidak lagi "hidup": dibatalkan, atau keputusannya dibalik (penggantinya — bila
# dibuka ulang — adalah dokumen baru yang aktif).
INACTIVE_STATUSES = (STATUS_CANCELLED, STATUS_REVERSED)
STATUS_LABEL = {"Pending": "menunggu paket", "Received": "diterima", "Inspected": "diinspeksi",
                "Resolved": "selesai", "Cancelled": "dibatalkan", "Reversed": "keputusan dibalik"}


class ReturnDuplicateError(ReturnBridgeError):
    """Sudah ada Retur Fisik aktif untuk pesanan/barang yang sama (route → 409)."""

    def __init__(self, message: str, existing: list):
        super().__init__(message)
        self.existing = existing


def order_lines(order: dict) -> list:
    """Baris barang satu pesanan Marketing. Bentuk impor = ``items[]``; pesanan lama tanpa
    ``items`` dibaca sebagai SATU baris dari kepala pesanan (sama dengan RTS K6)."""
    o = order or {}
    lines = [ln for ln in (o.get("items") or []) if isinstance(ln, dict)]
    if lines:
        return lines
    return [{"fg_material_id": o.get("fg_material_id"), "quantity": o.get("quantity"),
             "sku_code": o.get("sku_id"), "product_name": o.get("product_name")}]


def _line_name(ln: dict) -> str:
    return str(ln.get("product_name") or ln.get("product_name_raw") or "").strip()


def _line_sku(ln: dict) -> str:
    return str(ln.get("sku_code") or ln.get("seller_sku") or ln.get("sku") or "").strip()


def _line_qty(ln: dict) -> int:
    """Qty baris pesanan; 0 = tidak diketahui."""
    raw = ln.get("quantity") if ln.get("quantity") is not None else ln.get("qty")
    return max(0, _int(raw, 0))


def _line_value(ln: dict) -> float:
    try:
        return float(ln.get("sku_subtotal_after_discount") or ln.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0


def _line_no(v) -> int | None:
    """`source_order_line` → nomor baris (pembukaan ulang K1 menambah akhiran '-ulang')."""
    try:
        return int(str(v).split("-")[0])
    except (TypeError, ValueError):
        return None


def summarize_wh(wh: dict) -> dict:
    """Ringkasan satu retur gudang untuk pesan 409 / layar pemilih pesanan."""
    wh = wh or {}
    return {"id": wh.get("id"), "return_code": wh.get("return_code") or "",
            "status": wh.get("status") or "",
            "status_label": STATUS_LABEL.get(wh.get("status") or "", wh.get("status") or ""),
            "product_name": wh.get("product_name") or wh.get("sku_code") or "",
            "sku_code": wh.get("sku_code") or "",
            "order_number": wh.get("order_number") or "",
            "source_order_line": _line_no(wh.get("source_order_line")),
            "from_marketing": bool(wh.get("source_marketing_return_id"))}


async def active_returns_for_order(db, order_number: str, resi: str = "") -> list:
    """Retur gudang AKTIF (bukan Batal/Dibalik) untuk satu pesanan (atau resi paketnya)."""
    ors = [{"order_number": order_number}] if order_number else []
    if resi:
        ors.append({"resi_number": resi})
    if not ors:
        return []
    return await db[WH].find({"$or": ors, "status": {"$nin": list(INACTIVE_STATUSES)}},
                             {"_id": 0}).sort("created_at", 1).to_list(50)


def same_item(wh: dict, *, line_no: int | None, material_id: str | None, n_lines: int,
              strict: bool = False) -> bool:
    """Apakah retur gudang ``wh`` menyangkut barang yang sama dengan (baris, barang) ini?

    Pesanan satu baris ⇒ selalu sama. Multi-baris: baris pesanan dibandingkan dulu, lalu
    master barangnya. Bila retur lama tidak menunjuk baris maupun barang:
      · ``strict=False`` (catat manual) ⇒ dianggap SAMA — lebih aman ditolak lalu dibuka
        daripada paket yang sama tercatat dua kali;
      · ``strict=True`` (jembatan) ⇒ TIDAK sama — jangan menautkan tanpa bukti."""
    if n_lines <= 1:
        return True
    wl = _line_no(wh.get("source_order_line"))
    wm = wh.get("material_id") or wh.get("fg_material_id")
    if line_no and wl:
        return wl == line_no
    if material_id and wm:
        return wm == material_id
    return not strict


def line_unit_price(ln: dict) -> float:
    """Harga satuan yang dibayar pembeli untuk satu baris (subtotal sesudah diskon ÷ qty; cadangan harga satuan)."""
    q = _line_qty(ln) or 1
    for k in ("sku_subtotal_after_discount", "subtotal"):
        try:
            v = float(ln.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            return round(v / q, 2)
    for k in ("sku_unit_price", "sku_unit_original_price", "price_final", "price"):
        try:
            v = float(ln.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            return round(v, 2)
    return 0.0


async def order_lookup(db, q: str, *, limit: int = 15, scope: dict | None = None) -> list:
    """Cari pesanan Marketing (`marketing_orders`) lewat no. pesanan ATAU no. resi untuk form
    "Catat retur" (Gudang) dan "Buat refund" (Marketing). Tiap pesanan membawa baris barangnya (tertaut master
    atau belum) dan retur gudang aktif yang sudah ada — baris yang sudah punya retur ditandai ``blocked_by``.

    2026-11-14 — ``scope`` = saringan toko pemakai (Marketing hanya melihat tokonya); tiap baris juga membawa
    tingkat tautannya (``varian`` · ``model`` · ``belum``, :func:`core.sku_kunci.tingkat_tautan`), model, kunci
    Jembatan SKU, dan harga satuan yang dibayar pembeli."""
    from core import sku_kunci as _skk
    q = (q or "").strip()
    if len(q) < 3:
        return []
    rx = {"$regex": re.escape(q), "$options": "i"}
    filt = {"$or": [{"order_id": rx}, {"tracking_number": rx}]}
    if scope:
        filt = {"$and": [filt, scope]}
    orders = await db.marketing_orders.find(filt, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    models: dict = {}
    out = []
    for o in orders:
        order_no = str(o.get("order_id") or "")
        resi = str(o.get("tracking_number") or "").strip()
        lines = order_lines(o)
        act = await active_returns_for_order(db, order_no, resi)
        items = []
        for i, ln in enumerate(lines, start=1):
            mid = ln.get("fg_material_id") or ln.get("material_id")
            snap = await _material_snapshot(db, mid) if mid else {}
            mat = await db.rahaza_materials.find_one({"id": mid}, {"_id": 0, "variant_id": 1, "model_id": 1})                 if mid else None
            tingkat = _skk.tingkat_tautan(ln, mat)
            model_id = ln.get("model_id") or (mat or {}).get("model_id")
            if model_id and model_id not in models:
                m = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0, "code": 1, "name": 1}) or {}
                models[model_id] = m
            blk = [w for w in act if w.get("order_number") != order_no or same_item(
                w, line_no=i, material_id=snap.get("material_id"), n_lines=len(lines))]
            items.append({
                "line": i, "product_name": _line_name(ln), "variation": ln.get("variation_raw") or "",
                "sku": _line_sku(ln), "seller_sku": str(ln.get("seller_sku") or "").strip(),
                "quantity": _line_qty(ln), "value": _line_value(ln), "unit_price": line_unit_price(ln),
                "material_id": snap.get("material_id"), "material_code": snap.get("material_code", ""),
                "material_name": snap.get("material_name", ""),
                "catalog_item_id": ln.get("catalog_item_id"),
                "variant_id": ln.get("variant_id") or snap.get("variant_id"),
                "link_level": tingkat, "model_id": model_id,
                "model_code": (models.get(model_id) or {}).get("code", "") if model_id else "",
                "model_name": (models.get(model_id) or {}).get("name", "") if model_id else "",
                "bridge_key": _skk.kunci_baris(ln, o.get("account_id")),
                "blocked_by": [summarize_wh(w) for w in blk]})
        out.append({
            "id": o.get("id"), "order_id": order_no, "tracking_number": resi,
            "platform": o.get("platform") or o.get("purchase_channel") or "",
            "account_id": o.get("account_id"), "account_name": o.get("account_name") or "",
            "customer_name": o.get("customer_name") or o.get("buyer_username") or "",
            "status": o.get("status") or "",
            "order_date": str(o.get("order_date") or o.get("created_at") or "")[:10],
            "items": items, "active_returns": [summarize_wh(w) for w in act]})
    return out


async def find_order_for_manual(db, *, order_doc_id: str = "", order_number: str = "",
                                resi: str = "") -> dict:
    """Pesanan Marketing yang dirujuk "Catat retur". Tidak ditemukan ⇒ :class:`ReturnBridgeError`."""
    if order_doc_id:
        o = await db.marketing_orders.find_one({"id": order_doc_id}, {"_id": 0})
        if not o:
            raise ReturnBridgeError("Pesanan yang dipilih tidak ada lagi di data pesanan Marketing — "
                                    "cari ulang pesanannya.")
        return o
    ors = []
    if order_number:
        ors.append({"order_id": order_number})
    if resi:
        ors.append({"tracking_number": resi})
    if not ors:
        raise ReturnBridgeError("Pilih pesanan yang dikembalikan — cari lewat no. pesanan atau no. resi.")
    rows = await db.marketing_orders.find({"$or": ors}, {"_id": 0}).to_list(5)
    if not rows:
        raise ReturnBridgeError(
            f"Pesanan atau resi {order_number or resi} tidak ada di data pesanan Marketing. Retur fisik hanya "
            "bisa dicatat untuk pesanan yang ada — minta tim Marketing mengimpor pesanannya dulu, lalu cari lagi.")
    if len(rows) > 1:
        raise ReturnBridgeError(
            f"No. pesanan/resi {order_number or resi} cocok dengan {len(rows)} pesanan — pilih pesanannya dari "
            "daftar pencarian.")
    return rows[0]


async def prepare_manual_return(db, body: dict) -> dict:
    """Validasi "Catat retur" manual (Tipe 1 ekspedisi / Tipe 2 pembeli) — fungsi murni-DB, diuji unit.

    → ``{order, line_no, line, n_lines, identity, qty, order_value}``. Melempar
    :class:`ReturnBridgeError` (400) bila pesanan/barang/qty tidak sah, dan
    :class:`ReturnDuplicateError` (409) bila sudah ada retur gudang aktif untuk pesanan/barang itu."""
    body = body if isinstance(body, dict) else {}
    order = await find_order_for_manual(
        db, order_doc_id=str(body.get("order_doc_id") or "").strip(),
        order_number=str(body.get("order_number") or "").strip(),
        resi=str(body.get("resi_number") or "").strip())
    order_no = str(order.get("order_id") or "")
    lines = order_lines(order)
    n = len(lines)
    raw_line = body.get("order_line")
    if raw_line in (None, ""):
        if n > 1:
            raise ReturnBridgeError(f"Pesanan {order_no} berisi {n} barang — pilih barang yang kembali.")
        line_no = 1
    else:
        line_no = _int(raw_line, 0)
        if not 1 <= line_no <= n:
            raise ReturnBridgeError("Barang yang dipilih tidak ada di pesanan ini — pilih ulang dari daftar "
                                    "barang pesanan.")
    line = lines[line_no - 1]

    # ── barang: dari baris pesanan bila tertaut master; selain itu dari master produk jadi (W4) ──
    ident = {"link_status": LINK_NONE, "source": "",
             "reason": ("Baris pesanan ini belum tertaut master produk jadi — tekan 'Pilih barang' di "
                        "detail retur sebelum memutuskan.")}
    mid_line = line.get("fg_material_id") or line.get("material_id")
    snap = await _material_snapshot(db, mid_line) if mid_line else {}
    if snap:
        ident.update(snap, link_status=LINK_OK, source="order_item", reason="")
    else:
        pick = str(body.get("material_id") or body.get("fg_material_id") or "").strip()
        code = str(body.get("sku_code") or "").strip()
        if pick:
            snap = await _material_snapshot(db, pick)
            if not snap:
                raise ReturnBridgeError(f"Master barang '{pick}' tidak ditemukan")
        elif code:
            mat = await db.rahaza_materials.find_one({"$or": [{"code": code}, {"sku": code}]}, {"_id": 0})
            snap = await _material_snapshot(db, mat["id"]) if mat else {}
        if snap:
            ident.update(snap, link_status=LINK_OK, source="manual_master_pick", reason="")
    if ident.get("variant_id") is None and line.get("variant_id"):
        ident["variant_id"] = line.get("variant_id")

    # ── qty: bawaan = qty baris pesanan; tidak boleh melebihinya ──
    lq = _line_qty(line)
    raw_q = body.get("qty")
    qty = (lq or 1) if raw_q in (None, "") else _int(raw_q, -1)
    if qty < 1:
        raise ReturnBridgeError("Qty retur minimal 1 pcs.")
    if lq and qty > lq:
        raise ReturnBridgeError(f"Qty retur {qty} melebihi qty barang ini di pesanan ({lq} pcs).")

    # ── retur ganda: retur gudang aktif untuk pesanan/resi & barang yang sama ⇒ 409 ──
    resi = str(order.get("tracking_number") or "").strip()
    act = await active_returns_for_order(db, order_no, resi)
    clash = [w for w in act if w.get("order_number") != order_no or same_item(
        w, line_no=line_no, material_id=ident.get("material_id"), n_lines=n)]
    if clash:
        kode = ", ".join(f"{w.get('return_code')} ({STATUS_LABEL.get(w.get('status'), w.get('status'))})"
                         for w in clash)
        raise ReturnDuplicateError(
            f"Pesanan {order_no} sudah punya retur gudang {kode}. Buka retur itu — paket yang sama tidak "
            "boleh dicatat dua kali.", [summarize_wh(w) for w in clash])

    value = _line_value(line)
    if not value:
        try:
            value = float(body.get("order_value") or 0)
        except (TypeError, ValueError):
            value = 0.0
    return {"order": order, "line_no": line_no, "line": line, "n_lines": n, "identity": ident,
            "qty": qty, "order_value": value}


# ═════════════════════════════════════════════════════════════════════════════
# 2026-11-14 — "BUAT REFUND" MARKETING = "CATAT RETUR" GUDANG: wajib pesanan + tautkan
# ═════════════════════════════════════════════════════════════════════════════
REFUND_INACTIVE = ("rejected", "cancelled")
REFUND_STATUS_LABEL = {"pending": "menunggu", "approved": "disetujui", "completed": "selesai"}


class RefundDuplicateError(ReturnBridgeError):
    """Baris pesanan ini sudah punya refund Marketing aktif (route → 409)."""

    def __init__(self, message: str, existing: list):
        super().__init__(message)
        self.existing = existing


async def marketing_refunds_for_order(db, order_number: str) -> list:
    """Refund Marketing AKTIF (bukan ditolak/dibatalkan) untuk satu no. pesanan."""
    if not order_number:
        return []
    return await db[MKT].find(
        {"order_id": order_number, "status": {"$nin": list(REFUND_INACTIVE)}},
        {"_id": 0, "id": 1, "order_line": 1, "status": 1, "date": 1, "product": 1, "catalog_item_id": 1,
         "qty": 1, "refund_type": 1, "refund_amount": 1}).sort("created_at", 1).to_list(50)


def refund_same_line(ref: dict, *, line_no: int, n_lines: int, line: dict | None = None) -> bool:
    """Refund ``ref`` menyangkut baris pesanan ini? Refund lama tanpa nomor baris hanya dianggap sama bila
    pesanannya satu baris atau item katalognya terbukti sama (tanpa bukti ⇒ tidak menghalangi)."""
    if n_lines <= 1:
        return True
    rl = _int(ref.get("order_line"), 0)
    if rl:
        return rl == line_no
    cid = (line or {}).get("catalog_item_id")
    return bool(cid and ref.get("catalog_item_id") == cid)


def summarize_refund(ref: dict) -> dict:
    return {"id": ref.get("id"), "status": ref.get("status") or "",
            "status_label": REFUND_STATUS_LABEL.get(ref.get("status") or "", ref.get("status") or ""),
            "date": str(ref.get("date") or "")[:10], "product": ref.get("product") or "",
            "order_line": _int(ref.get("order_line"), 0) or None, "qty": ref.get("qty")}


async def prepare_marketing_refund(db, body: dict, *, user=None, exclude_id: str | None = None) -> dict:
    """Validasi form "Buat refund" Marketing (keputusan 14 Nov: sama dengan "Catat retur" gudang 10 Nov).

    → ``{order, line_no, line, n_lines, identity, qty, price, mapping, link_level_before}``.

    * pesanan WAJIB ada di `marketing_orders` (dipilih lewat :func:`order_lookup`); pesanan yang belum ada harus
      diimpor dulu — tidak ada lagi nomor pesanan ketik bebas;
    * barang = baris pesanan. Baris yang sudah tertaut varian dipakai apa adanya. Baris yang belum tertaut / baru
      tertaut MODEL wajib disertai ``variant_id`` pilihan staf, yang DISIMPAN ke Jembatan SKU lewat
      :func:`core.sku_bridge.apply_mapping` (jalur yang sama dengan layar Jembatan SKU) — pesanan lain dengan SKU +
      variasi yang sama ikut tertaut;
    * qty 1..qty baris; harga = harga satuan yang dibayar pembeli (cadangan ``price`` dari form bila pesanan tidak
      membawa harga);
    * baris yang sudah punya refund aktif ditolak (:class:`RefundDuplicateError` → 409) — SEBELUM ada tulisan apa pun.
    """
    from core import sku_bridge as _sb
    from core import sku_kunci as _skk
    body = body if isinstance(body, dict) else {}
    order_doc_id = str(body.get("order_doc_id") or "").strip()
    if not order_doc_id:
        raise ReturnBridgeError("Pilih pesanan yang direfund — cari lewat no. pesanan atau no. resi. Pesanan yang "
                                "belum ada di sistem harus diimpor dulu (Impor Data › Pesanan).")
    order = await find_order_for_manual(db, order_doc_id=order_doc_id)
    order_no = str(order.get("order_id") or "")
    lines = order_lines(order)
    n = len(lines)
    raw_line = body.get("order_line")
    if raw_line in (None, ""):
        if n > 1:
            raise ReturnBridgeError(f"Pesanan {order_no} berisi {n} barang — pilih barang yang kembali.")
        line_no = 1
    else:
        line_no = _int(raw_line, 0)
        if not 1 <= line_no <= n:
            raise ReturnBridgeError("Barang yang dipilih tidak ada di pesanan ini — pilih ulang dari daftar barang "
                                    "pesanan.")
    line = lines[line_no - 1]

    # ── qty: bawaan = qty baris pesanan; tidak boleh melebihinya ──
    lq = _line_qty(line)
    raw_q = body.get("qty")
    qty = (lq or 1) if raw_q in (None, "") else _int(raw_q, -1)
    if qty < 1:
        raise ReturnBridgeError("Qty retur minimal 1 pcs.")
    if lq and qty > lq:
        raise ReturnBridgeError(f"Qty retur {qty} melebihi qty barang ini di pesanan ({lq} pcs).")

    # ── refund ganda untuk baris yang sama ⇒ 409, sebelum menulis apa pun ──
    clash = [r for r in await marketing_refunds_for_order(db, order_no)
             if r.get("id") != exclude_id and refund_same_line(r, line_no=line_no, n_lines=n, line=line)]
    if clash:
        teks = ", ".join(f"{summarize_refund(r)['date'] or '-'} ({summarize_refund(r)['status_label']})"
                         for r in clash)
        raise RefundDuplicateError(
            f"Barang ini di pesanan {order_no} sudah punya refund {teks}. Buka refund itu — satu barang tidak boleh "
            "direfund dua kali.", [summarize_refund(r) for r in clash])

    # ── barang: baris tertaut varian dipakai; selain itu varian pilihan staf → Jembatan SKU ──
    mid = line.get("fg_material_id") or line.get("material_id")
    mat = await db.rahaza_materials.find_one({"id": mid}, {"_id": 0, "variant_id": 1, "model_id": 1}) if mid else None
    level = _skk.tingkat_tautan(line, mat)
    pick = str(body.get("variant_id") or "").strip()
    mapping = None
    if level != _skk.TINGKAT_VARIAN:
        if not pick:
            raise ReturnBridgeError(
                "Barang di baris pesanan ini belum tertaut ke varian master"
                + (" (baru tertaut model)" if level == _skk.TINGKAT_MODEL else "")
                + " — pilih variannya (warna & ukuran) dulu.")
        if not await db.rahaza_model_variants.find_one({"id": pick, "active": {"$ne": False}}, {"_id": 0, "id": 1}):
            raise ReturnBridgeError("Varian master yang dipilih tidak ada atau sudah tidak aktif — pilih varian lain.")
        key = _skk.kunci_baris(line, order.get("account_id"))
        if not key:
            raise ReturnBridgeError("Baris pesanan ini tidak punya SKU maupun nama produk, jadi tidak bisa ditautkan "
                                    "ke master. Tautkan dulu lewat Jembatan SKU.")
        mapping = await _sb.apply_mapping(
            db, key, variant_id=pick, account_id=order.get("account_id"), user=user, method="retur",
            product_name=_line_name(line), variation=line.get("variation_raw") or "")
        if not mapping.get("ok"):
            raise ReturnBridgeError(mapping.get("message") or "Varian gagal ditautkan lewat Jembatan SKU.")
        order = await db.marketing_orders.find_one({"id": order["id"]}, {"_id": 0}) or order
        line = order_lines(order)[line_no - 1]
        mid = line.get("fg_material_id") or line.get("material_id")
    elif pick and pick != (line.get("variant_id") or (mat or {}).get("variant_id")):
        raise ReturnBridgeError("Baris pesanan ini sudah tertaut ke varian master lain. Bila tautannya salah, ubah "
                                "di Jembatan SKU dulu.")
    snap = await _material_snapshot(db, mid) if mid else {}
    if not snap:
        raise ReturnBridgeError("Barang jadi baris pesanan ini tidak ditemukan di master — periksa tautannya di "
                                "Jembatan SKU.")
    ident = {**snap, "link_status": LINK_OK, "source": "order_line", "reason": "",
             "catalog_item_id": line.get("catalog_item_id"),
             "variant_id": line.get("variant_id") or snap.get("variant_id")}
    price = line_unit_price(line)
    if not price:
        try:
            price = max(0.0, float(body.get("price") or 0))
        except (TypeError, ValueError):
            price = 0.0
    return {"order": order, "line_no": line_no, "line": line, "n_lines": n, "identity": ident, "qty": qty,
            "price": price, "mapping": mapping, "link_level_before": level}


def _line_of_return(lines: list, ret: dict, ident: dict) -> int | None:
    """Baris pesanan yang dimaksud satu retur Marketing (tanpa menebak: penunjuk pasti dulu —
    item katalog, master barang, SKU — lalu nama produk yang cocok TEPAT satu baris)."""
    n = _int(ret.get("order_line"), 0)
    if 1 <= n <= len(lines):          # 2026-11-14 — retur menunjuk baris pesanan langsung
        return n
    sku = str(ret.get("sku") or "").strip()
    hits = set()
    for i, ln in enumerate(lines, start=1):
        if ret.get("catalog_item_id") and ln.get("catalog_item_id") == ret.get("catalog_item_id"):
            hits.add(i)
        elif ident.get("material_id") and ln.get("fg_material_id") == ident.get("material_id"):
            hits.add(i)
        elif sku and sku in (ln.get("seller_sku"), ln.get("platform_sku_id"), ln.get("sku_code"), ln.get("sku")):
            hits.add(i)
    if len(hits) == 1:
        return hits.pop()
    if not hits:
        want = str(ret.get("product") or "").strip().lower()
        names = [i for i, ln in enumerate(lines, start=1) if want and want in _line_name(ln).lower()]
        if len(names) == 1:
            return names[0]
    return None


async def find_unlinked_match(db, ret: dict, ident: dict) -> dict | None:
    """Retur gudang AKTIF tanpa retur Marketing (dicatat manual lebih dulu / RTS) untuk pesanan
    dan barang yang sama dengan retur Marketing ``ret``; ``None`` bila tidak ada yang PASTI cocok.

    Pesanan multi-baris (atau pesanannya tidak ada di data Marketing) hanya ditautkan bila baris
    atau master barangnya terbukti sama (``same_item(strict=True)``)."""
    order_no = str((ret or {}).get("order_id") or "").strip()
    if not order_no:
        return None
    rows = await db[WH].find({"order_number": order_no, "status": {"$nin": list(INACTIVE_STATUSES)},
                              "source_marketing_return_id": {"$in": [None, ""]}},
                             {"_id": 0}).sort("created_at", 1).to_list(50)
    if not rows:
        return None
    order = await db.marketing_orders.find_one({"order_id": order_no}, {"_id": 0})
    lines = order_lines(order) if order else []
    n = len(lines) if order else 2          # pesanan tak dikenal ⇒ perlakukan seperti multi-baris
    line_no = _line_of_return(lines, ret, ident or {}) if order else None
    for wh in rows:
        if same_item(wh, line_no=line_no, material_id=(ident or {}).get("material_id"), n_lines=n, strict=True):
            return wh
    return None


async def _link_unlinked(db, wh: dict, ret: dict, ident: dict, *, actor=None, cond=None) -> dict | None:
    """Tautkan retur Marketing ``ret`` ke retur gudang ``wh`` yang sudah ada (atomik: hanya bila
    ``wh`` masih aktif & belum milik retur Marketing lain). ``None`` bila didahului proses lain."""
    who = _actor_name(actor)
    ident = ident or {}
    reason_txt = " — ".join([x for x in [ret.get("reason_label"), ret.get("reason_detail")] if x])
    patch = {"source_marketing_return_id": ret["id"],
             "source_marketing_order_id": ret.get("order_id"),
             "source_account_name": ret.get("account_name") or wh.get("source_account_name") or "",
             "reported_condition": cond, "marketing_linked_at": _now_iso(),
             "marketing_linked_by": who, "updated_at": _now_iso()}
    if reason_txt and not wh.get("initial_reason"):
        patch["initial_reason"] = reason_txt
    notes = [f"Ditautkan ke retur Marketing (pesanan {ret.get('order_id') or '-'}) — paket ini sudah "
             "dicatat gudang lebih dulu, jadi tidak dibuat pekerjaan kedua"]
    wm = wh.get("material_id") or wh.get("fg_material_id")
    if not wm and ident.get("link_status") == LINK_OK and wh.get("status") in OPEN_STATUSES \
            and not wh.get("restocked"):
        patch.update({
            "material_id": ident.get("material_id"), "fg_material_id": ident.get("material_id"),
            "variant_id": ident.get("variant_id"), "catalog_item_id": ident.get("catalog_item_id"),
            "sku_code": ident.get("material_code") or wh.get("sku_code") or "",
            "product_name": ident.get("material_name") or wh.get("product_name") or "",
            "material_unit": ident.get("unit") or "pcs",
            "material_category": ident.get("category_name") or "",
            "material_color": ident.get("color_name") or "", "material_option": ident.get("option_name") or "",
            "link_status": LINK_OK, "link_reason": "", "link_source": ident.get("source") or "marketing_return"})
        notes.append(f"barang diisi dari retur Marketing: {ident.get('material_code') or '-'}")
    elif wm and ident.get("material_id") and ident["material_id"] != wm:
        notes.append(f"Marketing menyebut {ident.get('material_code') or 'barang lain'}, gudang mencatat "
                     f"{wh.get('sku_code') or '-'} — keputusan mengikuti barang fisik")
    mq = max(1, _int(ident.get("qty") or ret.get("qty") or ret.get("quantity"), 1))
    if mq != _int(wh.get("qty"), 0):
        notes.append(f"qty pengajuan Marketing {mq} pcs, dicatat gudang {wh.get('qty')} pcs")
    res = await db[WH].update_one(
        {"id": wh["id"], "source_marketing_return_id": {"$in": [None, ""]},
         "status": {"$nin": list(INACTIVE_STATUSES)}},
        {"$set": patch, "$push": {"timeline": {"status": wh.get("status"), "at": _now_iso(), "by": who,
                                               "note": " · ".join(notes)}}})
    if not res.matched_count:
        return None
    return await db[WH].find_one({"id": wh["id"]}, {"_id": 0})


async def ensure_wh_return(db, ret: dict, *, actor=None, condition=None,
                           auto_restock: bool = False) -> dict:
    """Pastikan retur Marketing punya SATU pekerjaan Retur Fisik di Gudang.

    2026-11-02 (K1) — bawaan ``auto_restock=False``: retur Marketing HANYA membuat
    pekerjaan **Pending**; stok & jurnal menunggu keputusan gudang. Parameter
    ``auto_restock=True`` dibiarkan untuk pemanggil lama yang sadar, tetapi tidak
    lagi dipakai jalur Marketing mana pun.

    2026-11-09 — retur ``goods_returned=False`` ("Refund only") TIDAK dibuatkan pekerjaan baru
    (:func:`alasan_tanpa_retur_fisik`); pekerjaan yang SUDAH ada tidak disentuh.

    2026-11-10 (keputusan owner "wajib referensi + tautkan") — sebelum membuat pekerjaan baru,
    retur gudang AKTIF tanpa retur Marketing untuk pesanan & barang yang sama (dicatat manual
    lebih dulu / RTS) DITAUTKAN (:func:`find_unlinked_match`) ⇒ ``linked=True``, tetap SATU
    pekerjaan dan stok sekali.

    Return: {created, restocked, wh_return, identity, message} (+ ``skipped``, ``reason``, ``linked``)
    """
    actor = actor or {}
    cond = normalize_condition(condition if condition is not None
                               else ret.get("item_condition") or ret.get("goods_condition"))

    # ── idempoten: sudah pernah dijembatani? ──────────────────────────────────
    existing = await find_linked_wh(db, ret)
    ident = None
    linked_now = False
    if not existing:
        # ── 2026-11-09 — "Refund only": barang TIDAK kembali, jadi tidak ada paket yang ditunggu ──
        alasan = alasan_tanpa_retur_fisik(ret)
        if alasan:
            await _stamp_skip(db, ret["id"], alasan)
            logger.info("[retur-jembatan] retur %s tidak dibuatkan Retur Fisik: %s", ret.get("id"), alasan)
            return {"created": False, "restocked": False, "skipped": True, "wh_return": None,
                    "identity": None, "reason": alasan,
                    "message": f"Retur fisik tidak dibuat: {alasan}"}
        ident = await resolve_identity(db, ret)
        # ── 2026-11-10 — paket sudah dicatat gudang lebih dulu ⇒ TAUTKAN, jangan buat yang kedua ──
        cand = await find_unlinked_match(db, ret, ident)
        if cand:
            existing = await _link_unlinked(db, cand, ret, ident, actor=actor, cond=cond)
            linked_now = bool(existing)
    if existing:
        res = {"created": False, "restocked": False, "wh_return": existing,
               "identity": ident, "message": f"Sudah terhubung ke {existing.get('return_code')}"}
        if linked_now:
            res["linked"] = True
            res["message"] = (f"Retur Marketing ditautkan ke Retur Fisik {existing.get('return_code')} yang "
                              "sudah dicatat gudang — tidak dibuat pekerjaan kedua.")
        if auto_restock and not existing.get("restocked") \
                and existing.get("link_status") == LINK_OK:
            done = await auto_process(db, existing["id"], condition=cond, actor=actor)
            res["restocked"] = bool(done.get("restocked"))
            res["wh_return"] = done.get("wh_return") or existing
            res["message"] = done.get("message") or res["message"]
        await _stamp_marketing(db, ret["id"], res["wh_return"])
        if linked_now and is_decided(res["wh_return"]):
            # Gudang SUDAH memutuskan paket ini sebelum retur Marketing-nya masuk ⇒ rekap omzet
            # tanggal retur dihitung ulang sekarang (K36: retur mengurangi omzet setelah keputusan).
            from core import marketing_returns as _mret
            await _mret.refresh_rekap_for_return_ids(db, [ret["id"]], actor=_actor_name(actor))
        return res

    code = await _next_code(db)
    actor_name = _actor_name(actor)
    reason_txt = " — ".join([x for x in [ret.get("reason_label"), ret.get("reason_detail")] if x])
    # 2026-11-14 — refund yang dibuat dari pesanan terpilih: retur fisik menunjuk pesanan & BARIS yang sama
    # (kunci yang sama dengan "Catat retur" gudang dan RTS, jadi paket ini tidak tercatat dua kali).
    order = None
    if ret.get("order_doc_id"):
        order = await db.marketing_orders.find_one({"id": ret["order_doc_id"]}, {"_id": 0})
    line_no = _int(ret.get("order_line"), 0) or None
    line_label = ""
    if order and line_no:
        _lines = order_lines(order)
        if 1 <= line_no <= len(_lines):
            _ln = _lines[line_no - 1]
            line_label = " · ".join(x for x in (_line_name(_ln), _ln.get("variation_raw") or "") if x)

    doc = _wh_skeleton(code, actor_name, (
        f"Dibuat otomatis dari retur Marketing (pesanan {ret.get('order_id') or '-'}) — "
        "menunggu paket diterima gudang (K1: stok baru bergerak saat keputusan gudang)"))
    doc.update({
        "return_type": "customer_refund",
        # ── info pesanan (dipetakan dari retur Marketing) ─────────────────────
        "order_number": ret.get("order_id", ""),
        "resi_number": str((order or {}).get("tracking_number") or "").strip(),
        "channel": ret.get("platform", ""),
        "customer_name": (ret.get("customer_name") or (order or {}).get("customer_name")
                          or (order or {}).get("buyer_username") or ret.get("account_name")
                          or "Pembeli Marketplace"),
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
        "source_order_doc_id": (order or {}).get("id"),
        "source_order_line": line_no if order else None,
        "order_line_label": line_label,
        "account_id": ret.get("account_id"),
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


def _as_dt(v):
    """ISO string / datetime → datetime aware (UTC). None bila tidak terbaca."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


async def scan_out_cost(db, material_id: str, before=None) -> dict | None:
    """HPP yang TERCATAT saat barang ini di-scan keluar (2026-11-06, Tahap 2).

    Scan keluar tidak ditautkan ke nomor pesanan (K15), jadi acuannya = baris scan keluar AKTIF
    terakhir SKU ini yang terjadi sebelum/saat retur diterima. None bila tidak ada (cadangan WAC)."""
    from core import scan_out as so
    ref_at = _as_dt(before)
    rows = await db[so.LINES].find(
        {"material_id": material_id, "kind": so.KIND_SCAN, "status": "active", "unit_cost": {"$gt": 0}},
        {"_id": 0}).sort("scanned_at", -1).to_list(500)
    for r in rows:
        at = _as_dt(r.get("scanned_at"))
        if ref_at is not None and (at is None or at > ref_at):
            continue
        qty = max(1, _int(r.get("qty"), 1))
        comps = {k: round(float((r.get("components") or {}).get(k) or 0) / qty, 4)
                 for k in ("material", "labor", "overhead")}
        return {"unit_cost": round(float(r["unit_cost"]), 4), "components": comps,
                "line_id": r.get("id"), "sheet_number": r.get("sheet_number"), "scanned_at": r.get("scanned_at")}
    return None


async def _return_cost_basis(db, wh_ret: dict, mid: str, actor: dict) -> dict:
    """Biaya retur fisik: HPP saat scan keluar (keputusan Tahap 2); cadangan = WAC hari keputusan."""
    from core import fg_cost_layers as fcl
    so_cost = await scan_out_cost(db, mid, before=wh_ret.get("received_at") or wh_ret.get("created_at"))
    if so_cost:
        return {**so_cost, "basis": "scan_out"}
    state = await fcl.wac_state(db, mid, actor=actor)
    return {"unit_cost": state["unit_cost"], "components": state["components"], "basis": "wac"}


async def _value_damaged(db, wh_ret: dict, mid: str, qty: int, actor: dict,
                         disposed: bool = False) -> dict:
    """Retur rusak → karantina (nilai 0): reklas HPP menjadi Kerugian Retur Rusak (Iter 122).

    2026-11-02 (owner No.26a): nilai = qty × WAC FG saat keputusan (`fcl.wac_state`).
    K40: `disposed=True` = keputusan "Dibuang" — jurnal sama (Dr 6-1300 / Cr 5-1000
    senilai WAC), barang TIDAK masuk stok. Pemanggil: `routes/dewi_wh_returns.resolve_return`
    untuk aksi "Dibuang / Dispose" (hasilnya `loss_*`, sehingga Balik Keputusan ikut
    membuat jurnal pembaliknya)."""
    from routes.rahaza_posting import post_return_damaged_loss
    out = {"loss_unit_cost": 0.0, "loss_amount": 0.0, "loss_je_id": None,
           "loss_je_number": None, "loss_post_error": None, "loss_basis": "wac",
           "loss_kind": "disposed" if disposed else "damaged"}
    try:
        # 2026-11-06 (Tahap 2): nilai = HPP yang dijurnal saat barang di-scan keluar (cadangan WAC).
        basis = await _return_cost_basis(db, wh_ret, mid, actor)
        unit_cost = basis["unit_cost"]   # 4 desimal; jurnal dibulatkan per total
        out["loss_basis"] = basis["basis"]
        out["loss_unit_cost"] = unit_cost
        out["loss_amount"] = round(unit_cost * qty, 2)
        je = await post_return_damaged_loss(db, wh_ret, qty, unit_cost, actor or {}, disposed=disposed,
                                            components=basis.get("components"))
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
        # 2026-11-06 (Tahap 2): biaya masuk = HPP yang dijurnal saat barang di-scan keluar, supaya
        # jurnal balik HPP menutup PERSIS nilai keluarnya (cadangan: WAC hari keputusan).
        basis = await _return_cost_basis(db, wh_ret, mid, actor)
        unit_cost = basis["unit_cost"]
        out["hpp_unit_cost"] = unit_cost
        out["hpp_basis"] = basis["basis"]
        if basis.get("line_id"):
            out["hpp_scan_line_id"] = basis["line_id"]
            out["hpp_scan_sheet"] = basis.get("sheet_number")
        ref = {"type": "wh_return_restock", "id": wh_ret["id"],
               "return_code": wh_ret.get("return_code", ""),
               "marketing_return_id": wh_ret.get("source_marketing_return_id")}
        if unit_cost > 0:
            layer = await fcl.push_layer(db, material_id=mid, qty=qty, ref=ref, actor=actor,
                                         unit_cost=unit_cost, components=basis["components"],
                                         breakdown={"source": "marketplace_return", "unit_cost": unit_cost})
            out["hpp_layer_id"] = (layer or {}).get("id")
        je = await post_marketplace_return_restock(db, wh_ret, qty, unit_cost, actor or {},
                                                   components=basis.get("components"))
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
                  note: str = "", location_id: str | None = None) -> dict:
    """Tambah stok barang retur. IDEMPOTEN & guarded.

    · Penjaga atomik `restocked` dipasang SEBELUM stok ditambah supaya klik ganda
      / dua proses paralel tidak pernah menambah stok dua kali.
    · Barang Baik → `ZNA-FG` (ikut stok jual). Barang Rusak → `ZNA-KARANTINA`
      (dikecualikan dari stok jual oleh K-6a) ⇒ barang rusak tidak bisa terjual.
    · 2026-11-09 (G16): barang Baik boleh ke lokasi stok jual PILIHAN (`location_id`, dari langkah Terima).
    """
    actor = actor or {}
    mid = wh_ret.get("material_id") or wh_ret.get("fg_material_id")
    if not mid:
        raise ReturnBridgeError(UNLINKED_DECISION_MSG)
    cond = normalize_condition(condition if condition is not None
                               else wh_ret.get("item_condition"))
    n = max(1, _int(qty if qty is not None else wh_ret.get("qty"), 1))
    loc = await restock_location(db, cond, location_id)

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


async def set_material(db, wh_return_id: str, material_id: str, *, actor=None, note: str = "") -> dict:
    """2026-11-09 (audit gudang G5) — "Pilih barang": gudang menautkan retur ke SATU master FG.

    Syarat: retur belum diputuskan (Pending/Received/Inspected) dan stoknya belum pernah ditambah;
    master = barang jadi AKTIF milik DA (barang klien maklon ditolak — bukan stok DA, K14).
    Retur yang sudah tertaut boleh diganti barangnya selama belum diputuskan (jejak barang lama dicatat).
    → {wh_return, message}"""
    actor = actor or {}
    if not material_id:
        raise ReturnBridgeError("Pilih barang jadi dari master dulu.")
    doc = await db[WH].find_one({"id": wh_return_id}, {"_id": 0})
    if not doc:
        raise ReturnBridgeError("Retur fisik tidak ditemukan")
    if doc.get("status") not in OPEN_STATUSES or doc.get("restocked"):
        raise ReturnBridgeError(
            f"Retur {doc.get('return_code')} sudah diputuskan ('{doc.get('status')}') — barangnya tidak bisa "
            "diganti. Gunakan 'Balik Keputusan' bila keputusannya salah.")
    mat = await db.rahaza_materials.find_one({"id": material_id}, {"_id": 0})
    if not mat or (mat.get("type") or "fg") != "fg":
        raise ReturnBridgeError("Barang yang dipilih bukan master barang jadi.")
    if mat.get("active") is False:
        raise ReturnBridgeError(f"{mat.get('code')} sudah nonaktif di master — pilih SKU yang masih aktif.")
    if mat.get("owner_type") == "client":
        raise ReturnBridgeError(f"{mat.get('code')} barang milik klien maklon — bukan stok jual DA.")
    snap = await _material_snapshot(db, material_id)
    who = _actor_name(actor)
    old = doc.get("material_id") or doc.get("fg_material_id")
    cands = {c.get("fg_material_id") for c in (doc.get("link_candidates") or []) if c.get("fg_material_id")}
    txt = (f"Barang dipilih gudang: {snap['material_code']} {snap['material_name']}"
           + (f" (ganti dari {doc.get('sku_code') or old})" if old and old != material_id else "")
           + (" · sesuai kandidat pesanan" if material_id in cands else "")
           + (f" · {note.strip()}" if note and note.strip() else ""))
    patch = {
        "material_id": material_id, "fg_material_id": material_id, "variant_id": snap.get("variant_id"),
        "sku_code": snap["material_code"], "product_name": snap["material_name"] or doc.get("product_name") or "",
        "material_unit": snap.get("unit") or "pcs", "material_category": snap.get("category_name") or "",
        "material_color": snap.get("color_name") or "", "material_option": snap.get("option_name") or "",
        "link_status": LINK_OK, "link_reason": "", "link_source": "manual_pick_wh",
        "linked_by": who, "linked_at": _now_iso(), "updated_at": _now_iso(),
    }
    res = await db[WH].update_one({"id": wh_return_id, "status": {"$in": list(OPEN_STATUSES)},
                                   "restocked": {"$ne": True}},
                                  {"$set": patch, "$push": {"timeline": {
                                      "status": doc.get("status"), "at": _now_iso(), "by": who, "note": txt}}})
    if not res.matched_count:
        raise ReturnBridgeError("Retur ini baru saja diproses pengguna lain — muat ulang.")
    fresh = await db[WH].find_one({"id": wh_return_id}, {"_id": 0})
    if fresh.get("source_marketing_return_id"):
        await _stamp_marketing(db, fresh["source_marketing_return_id"], fresh)
    return {"wh_return": fresh, "message": txt}


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
                       actor=None, note: str = "", location_id: str | None = None) -> dict:
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
    # 2026-11-09 (G5/G16): semua syarat stok diperiksa SEBELUM status ditulis "Resolved" — dulu lokasi
    # yang tidak ada / barang tak tertaut baru ketahuan sesudahnya ⇒ retur "Selesai" tanpa stok.
    if not (doc.get("material_id") or doc.get("fg_material_id")):
        raise ReturnBridgeError(UNLINKED_DECISION_MSG)
    await restock_location(db, cond, location_id)
    before = {k: doc.get(k) for k in (
        "status", "received_at", "received_by", "received_qty", "unboxing_condition_notes",
        "package_condition", "inspected_at", "inspected_by", "item_condition", "return_cause",
        "cause_detail", "recommended_action", "resolved_at", "resolved_by", "action_taken",
        "action_notes", "auto_processed")}

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
    try:
        res = await restock(db, fresh, condition=cond, qty=n, actor=actor, note=note, location_id=location_id)
    except Exception:
        # stok tidak bertambah (klaim `restocked` sudah dilepas restock) ⇒ keputusan cepat dibatalkan,
        # retur kembali ke tahap sebelumnya (jejak timeline tetap, ditambah catatan gagal).
        await db[WH].update_one({"id": wh_return_id, "restocked": {"$ne": True}}, {
            "$set": {**before, "updated_at": _now_iso()},
            "$push": {"timeline": {"status": before.get("status") or STATUS_PENDING, "at": _now_iso(),
                                   "by": who, "note": "Keputusan cepat GAGAL — stok tidak berubah, retur dibuka lagi"}}})
        raise
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
    # `linked` (2026-11-10) = retur Marketing yang DITAUTKAN ke retur gudang yang sudah dicatat lebih dulu
    out = {"scanned": len(rets), "created": 0, "already": 0, "linked": 0, "restocked": 0,
           "skipped": 0, "failed": 0, "dry_run": bool(dry_run), "details": []}
    for r in rets:
        wh_exists = await db[WH].find_one({"source_marketing_return_id": r["id"]},
                                          {"_id": 0, "id": 1, "return_code": 1,
                                           "restocked": 1})
        if wh_exists and not dry_run:
            out["already"] += 1
            continue
        tanpa_fisik = "" if wh_exists else alasan_tanpa_retur_fisik(r)
        if tanpa_fisik:
            # 2026-11-09 — "Refund only": dilaporkan, tidak dijembatani (dry-run maupun nyata)
            out["skipped"] += 1
            out["details"].append({"marketing_return_id": r["id"], "order_id": r.get("order_id"),
                                   "skipped": True, "reason": tanpa_fisik})
            if not dry_run:
                await _stamp_skip(db, r["id"], tanpa_fisik)
            continue
        if dry_run:
            ident = await resolve_identity(db, r)
            cand = None if wh_exists else await find_unlinked_match(db, r, ident)
            out["details"].append({
                "marketing_return_id": r["id"], "order_id": r.get("order_id"),
                "product": r.get("product"), "link_status": ident["link_status"],
                "material_code": ident.get("material_code"), "qty": ident.get("qty"),
                "reason": ident.get("reason"),
                "already": bool(wh_exists),
                "would_link_to": (cand or {}).get("return_code"),
            })
            if wh_exists:
                out["already"] += 1
            elif cand:
                out["linked"] += 1
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
            elif res.get("linked"):
                out["linked"] += 1
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
    return await _create_posted_je(db, today_wib(),
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
    lines = order_lines(order)
    created, existing = [], []
    for idx, ln in enumerate(lines, start=1):
        # 2026-11-10 — retur yang DICATAT MANUAL gudang lebih dulu untuk baris ini memakai kunci yang
        # sama (`prepare_manual_return`), jadi paket yang sama tidak menjadi dua pekerjaan; yang
        # dibatalkan tidak dihitung.
        found = await db[WH].find_one({"source_order_doc_id": order.get("id"),
                                       "source_order_line": idx,
                                       "$or": [{"source": {"$ne": "manual"}},
                                               {"status": {"$ne": STATUS_CANCELLED}}]}, {"_id": 0})
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
