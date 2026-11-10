"""core/fg_pick.py — PILIH BARANG JADI TANPA SCAN (permintaan owner 10 Nov 2026).

Owner: "barang keluar product digudang tanpa scan bisa di cari dan bisa pilih multiple".
Staf gudang mencari barang jadi lewat kotak cari (nama, SKU, warna, ukuran) lalu mencentang
beberapa produk sekaligus beserta jumlahnya. Dipakai DUA layar yang sudah ada (bukan layar baru):

  * Gudang › OUTBOUND › Scan Keluar Penjualan — tombol "Pilih tanpa scan". Pilihan diproses
    lewat mesin scan yang SAMA (`core.scan_out.pick` → `scan(material_id=…)`): lembar harian,
    potong stok, nilai WAC, batal baris, Tutup Hari. Baris diberi tanda `tanpa_scan`.
  * Gudang › Master Item › Produk jadi › "Keluarkan stok" — formulir kini boleh banyak produk
    (`routes.rahaza_inventory_fg` `/fg-issue/batch`, satu nomor pengeluaran untuk semua baris).

Modul ini HANYA MEMBACA (tidak ada efek stok/jurnal). Aturan:
  1. Hanya master barang jadi milik DA (`type == fg`, bukan barang klien maklon, tidak nonaktif)
     — himpunan yang sama dengan `core.scan_out.fg_material_ids`.
  2. Kata cari dipecah per spasi (maks. 5 kata), di-escape, tidak peka huruf besar/kecil; SETIAP
     kata harus cocok di salah satu kolom (kode, SKU, nama, warna, ukuran, model) — pola yang sama
     dengan pemilih produk Katalog (`marketing_catalog_mgmt.search_fg_products`).
  3. Stok per lokasi dibaca dari baris `rahaza_material_stock` apa adanya; bila lokasi diberikan,
     baris yang BUKAN stok jual (karantina/titipan/kategori lain) diberi `masalah` dengan kalimat
     yang SAMA dengan penolakan scan (`core.scan_out.row_problem`) — layar menonaktifkan pilihannya.
  4. Tanpa kata cari, daftar = barang yang punya stok (di lokasi itu bila diberikan), stok terbanyak
     dulu. Dengan kata cari, barang yang punya stok tampil lebih dulu, lalu urut kode.
"""
from __future__ import annotations

import re
from typing import Optional

MAX_WORDS = 5
MAX_LIMIT = 200
DEFAULT_LIMIT = 50
SEARCH_FIELDS = ("code", "sku", "name", "color", "color_name", "size_code", "size", "model_code", "model_name")


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def search_words(q) -> list:
    """Teks cari → daftar kata (maks. MAX_WORDS, tanpa kata kosong)."""
    return [w for w in str(q or "").strip().split() if w][:MAX_WORDS]


def fg_filter(q="", ids: Optional[list] = None) -> dict:
    """Penyaring Mongo master barang jadi DA (aturan 1 + 2)."""
    flt: dict = {"type": "fg", "owner_type": {"$ne": "client"}, "active": {"$ne": False}}
    words = search_words(q)
    if words:
        flt["$and"] = [{"$or": [{k: {"$regex": re.escape(w), "$options": "i"}} for k in SEARCH_FIELDS]}
                       for w in words]
    if ids is not None:
        flt["id"] = {"$in": list(ids)}
    return flt


def clamp_limit(limit) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, n))


def item_view(m: dict) -> dict:
    """Bagian master yang ditampilkan di pemilih."""
    return {"id": m.get("id"), "code": m.get("code") or m.get("sku") or "", "name": m.get("name") or "",
            "color": m.get("color_name") or m.get("color") or "",
            "size": m.get("size_code") or m.get("size") or "",
            "unit": str(m.get("unit") or m.get("uom") or "pcs")}


def sort_items(items: list, *, has_location: bool, searching: bool) -> list:
    """Aturan 4 (fungsi murni)."""
    qty_key = "stok_lokasi" if has_location else "stok_total"
    if searching:
        return sorted(items, key=lambda r: (0 if _f(r.get(qty_key)) > 0 else 1, r.get("code") or ""))
    return sorted(items, key=lambda r: (-_f(r.get(qty_key)), r.get("code") or ""))


async def search(db, *, q: str = "", location_id: str = "", only_in_stock: bool = False,
                 limit=DEFAULT_LIMIT) -> dict:
    """Cari barang jadi untuk dipilih tanpa scan.

    Return ``{"items": [...], "total": n, "limit": k, "terpotong": bool}``; setiap item:
    ``{id, code, name, color, size, unit, stok_total, lokasi: [{location_id, code, name, qty, jual}],
    stok_lokasi?, masalah?}`` (`stok_lokasi`/`masalah` hanya bila `location_id` diberikan)."""
    from core import location_resolver
    from core.catalog_stock import blocked_location_ids
    from core.scan_out import row_problem
    lim = clamp_limit(limit)
    loc = (location_id or "").strip()
    searching = bool(search_words(q))
    blocked = await blocked_location_ids(db)

    if searching:
        mats = await db.rahaza_materials.find(fg_filter(q), {"_id": 0}).to_list(5000)
    else:
        # Tanpa kata cari: hanya barang yang memegang stok (di lokasi itu bila dipilih).
        sq: dict = {"qty": {"$gt": 0}}
        if loc:
            sq["location_id"] = loc
        held = {r.get("material_id") async for r in db.rahaza_material_stock.find(sq, {"_id": 0, "material_id": 1})}
        held.discard(None)
        mats = await db.rahaza_materials.find(fg_filter("", ids=sorted(held)), {"_id": 0}).to_list(5000) if held else []
    ids = [m["id"] for m in mats if m.get("id")]
    rows = await db.rahaza_material_stock.find({"material_id": {"$in": ids}}, {"_id": 0}).to_list(100000) if ids else []
    by_mat: dict = {}
    for r in rows:
        by_mat.setdefault(r.get("material_id"), []).append(r)
    disp = await location_resolver.build_display_map(
        db, [r["location_id"] for r in rows if r.get("location_id") and _f(r.get("qty")) > 0] + ([loc] if loc else []))

    items = []
    for m in mats:
        mrows = by_mat.get(m.get("id"), [])
        view = item_view(m)
        held_rows = [r for r in mrows if _f(r.get("qty")) > 0 and r.get("location_id")]
        held_rows.sort(key=lambda r: -_f(r.get("qty")))
        view["lokasi"] = [{"location_id": r["location_id"],
                           "code": (disp.get(r["location_id"]) or {}).get("code") or r.get("location_code") or "",
                           "name": (disp.get(r["location_id"]) or {}).get("name") or r.get("location_name") or "",
                           "qty": _f(r.get("qty")), "jual": row_problem(r, blocked) is None}
                          for r in held_rows]
        view["stok_total"] = round(sum(_f(r.get("qty")) for r in mrows if row_problem(r, blocked) is None), 4)
        if loc:
            here = next((r for r in mrows if r.get("location_id") == loc), None)
            view["stok_lokasi"] = _f((here or {}).get("qty"))
            why = row_problem(here, blocked)
            view["masalah"] = f"{view['code']}: {why}." if why else None
            if only_in_stock and view["stok_lokasi"] <= 0:
                continue
        elif only_in_stock and not view["lokasi"]:
            continue
        items.append(view)
    items = sort_items(items, has_location=bool(loc), searching=searching)
    return {"items": items[:lim], "total": len(items), "limit": lim, "terpotong": len(items) > lim}
