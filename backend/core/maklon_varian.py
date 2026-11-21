"""core/maklon_varian.py — baris PO maklon WAJIB memakai varian katalog buyer (keputusan owner 22 Nov 2026).

Kejadian 21 Nov (Admin Produksi, PO Kamira koh Tri): artikel katalog tanpa varian → setiap baris PO ber-SKU sama
(kode artikel) dan warna/ukuran DIKETIK. Dua warna dari satu seri lalu dianggap "baris kembar", dan warna bebas
("Putih" / "PUTIH " / salah ketik) tidak sinkron master. Owner: "Varian wajib" — sama dengan prinsip kain R&D
("harus singkron bukan dipilih bebas").

Aturan (satu pintu untuk SEMUA jalur layar/API yang membuat atau mengubah baris PO maklon):
* baris harus menunjuk artikel Katalog Buyer milik buyer PO itu, artikel tidak dihentikan;
* artikel harus punya varian aktif, dan baris harus memilih salah satunya (`maklon_variant_id`);
* SKU, warna, kode warna, ukuran, dan nama produk DIAMBIL dari varian/katalog — isian ketikan dari formulir diabaikan;
* baris lama yang tidak diubah (artikel, varian, SKU, warna, ukuran sama) dibiarkan, supaya PO yang dibuat sebelum
  aturan ini tetap bisa diubah jumlah/harganya.
Jalur impor saldo awal / PO sampel memanggil `create_po_internal` langsung dan tidak lewat sini.
"""
from __future__ import annotations

from fastapi import HTTPException

STATUS_TOLAK = {"discontinued", "inactive"}


def _s(v) -> str:
    return str(v or "").strip()


def _sama_dengan_lama(it: dict, old: dict) -> bool:
    for k in ("catalog_item_id", "maklon_variant_id", "sku", "color", "size"):
        if k in it and _s(it.get(k)) != _s(old.get(k)):
            return False
    return True


async def rapikan_baris(db, items: list, buyer_id: str | None, *, lama_by_id: dict | None = None) -> list:
    """Periksa & isi ulang baris PO maklon dari varian katalog. 400 dengan pesan jelas bila tidak sah."""
    lama_by_id = lama_by_id or {}
    katalog: dict = {}
    out = []
    for n, raw in enumerate(items or [], start=1):
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        it = dict(raw)
        old = lama_by_id.get(it.get("id")) if it.get("id") else None
        if old and _sama_dengan_lama(it, old):
            out.append(it)
            continue
        cid = _s(it.get("catalog_item_id") or (old or {}).get("catalog_item_id"))
        vid = _s(it.get("maklon_variant_id"))
        if not cid:
            raise HTTPException(400, f"Baris {n}: pilih artikel dari Katalog Buyer.")
        if cid not in katalog:
            katalog[cid] = await db.dewi_maklon_buyer_catalog.find_one(
                {"id": cid}, {"_id": 0, "id": 1, "client_id": 1, "artikel_code": 1, "product_name": 1,
                              "status": 1, "variants": 1, "buyer_ref_code": 1})
        cat = katalog[cid]
        if not cat:
            raise HTTPException(400, f"Baris {n}: artikel katalog tidak ditemukan — pilih ulang artikelnya.")
        nama = f"{cat.get('artikel_code') or ''} {cat.get('product_name') or ''}".strip()
        if buyer_id and _s(cat.get("client_id")) and _s(cat.get("client_id")) != _s(buyer_id):
            raise HTTPException(400, f"Baris {n}: artikel {nama} bukan milik buyer PO ini.")
        if _s(cat.get("status")) in STATUS_TOLAK:
            raise HTTPException(400, f"Baris {n}: artikel {nama} nonaktif/dihentikan — aktifkan dulu di Katalog Buyer.")
        aktif = [v for v in (cat.get("variants") or []) if v.get("active") is not False]
        if not aktif:
            raise HTTPException(
                400, f"Baris {n}: artikel {nama} belum punya varian warna/ukuran. Tambahkan varian di Klien & Katalog "
                     "Buyer dulu (warna & ukuran dari master), lalu pilih variannya di baris PO.")
        v = next((x for x in aktif if vid and (_s(x.get("id")) == vid or _s(x.get("sku")) == vid)), None)
        if not v:
            raise HTTPException(400, f"Baris {n} ({nama}): pilih varian warna/ukuran dari daftar varian artikel.")
        it.update({
            "catalog_item_id": cid,
            "maklon_variant_id": v.get("id") or v.get("sku"),
            "sku": v.get("sku") or "",
            "color": v.get("color") or "",
            "color_code": v.get("color_code") or "",
            "size": v.get("size") or "",
            "product_name": cat.get("product_name") or it.get("product_name") or "",
            "buyer_ref_code": _s(it.get("buyer_ref_code")) or _s(v.get("buyer_ref_code")) or _s(cat.get("buyer_ref_code")),
        })
        out.append(it)
    return out
