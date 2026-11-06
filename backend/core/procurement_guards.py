"""core.procurement_guards — aturan baris Penerimaan Barang & penjaga satuan dasar (Tahap 2 Pengadaan, 2026-11-06).

KEPUTUSAN OWNER (6 Nov 2026)
----------------------------
* Penerimaan (GR) memakai harga PO dan TIDAK bisa mengubahnya. Hanya Keuangan yang boleh mengubah harga
  baris PO (setelah PO keluar dari draf) — lihat `routes/rahaza_po.change_po_line_price`.
* GR tanpa PO: harga wajib dan hanya Keuangan yang mengisinya. Selama belum ada harga, GR berstatus
  "menunggu harga dari Keuangan" dan tidak bisa dikonfirmasi.
* Satuan GR harus salah satu satuan barang itu (satu sumber dengan PO: `core.bom_uom.factor_to_base` di
  atas `core.uom`), lalu qty & harga dikonversi ke SATUAN DASAR (INV-UOM-1/2) sebelum disimpan.
* Satuan dasar material tidak boleh diganti selama masih ada dokumen terbuka dalam satuan lama
  (PO, GR, daftar harga pemasok, karantina) — `base_unit_open_documents`.
"""
from __future__ import annotations

from core import bom_uom as _bom_uom
from core import uom as _uom
from core.purchase_returns import gr_line_price

PO_OPEN_STATUSES = ("draft", "pending_approval", "approved", "partially_received", "rejected")
GR_OPEN_STATUSES = ("draft", "inspecting", "processing")
PRICE_PENDING_NOTE = "menunggu harga dari Keuangan"


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def line_label(it: dict) -> str:
    return it.get("sku") or it.get("product_name") or it.get("material_name") or "?"


# ═════════════════════════════════════════════════════════════════════════════
# 1. BARIS GR: SATUAN → SATUAN DASAR, HARGA DARI PO / KEUANGAN
# ═════════════════════════════════════════════════════════════════════════════
def convert_line_to_base(it: dict, mat: dict) -> float:
    """Konversi qty & harga satu baris GR dari satuan pilihan ke satuan dasar (mengubah `it`).

    Return faktor yang dipakai (1 = sudah satuan dasar). Melempar `uom.UomError` bila satuannya bukan
    satuan barang ini. Satuan masukan disimpan (`gr_uom`, `gr_uom_factor`, `*_input`) sebagai jejak; sesudah
    dikonversi `unit` = satuan dasar sehingga penyimpanan ulang tidak mengonversi dua kali."""
    base = _uom.base_uom_of(mat)
    unit = _bom_uom.norm_unit(it.get("unit") or base) or base
    if unit == base:
        it["unit"] = base
        return 1.0
    factor, _src = _bom_uom.factor_to_base(mat, unit)
    factor = float(factor or 1.0)
    if abs(factor - 1.0) < 1e-12:
        it["unit"] = base
        return 1.0
    for k in ("expected_qty", "received_qty", "rejected_qty"):
        if it.get(k) not in (None, ""):
            v = _f(it.get(k))
            it[f"{k}_input"] = v
            it[k] = round(v * factor, 4)
    price = gr_line_price(it)
    if price > 0:
        it["unit_price_input"] = price
        it["unit_price"] = round(price / factor, 6)
        it.pop("unit_cost", None)
    # rincian gulungan (`rolls`) selalu diketik dalam satuan dasar — tidak dikonversi
    it.update({"gr_uom": unit, "gr_uom_factor": round(factor, 8), "unit": base, "base_uom": base})
    if it.get("accepted_qty") is not None:
        it["accepted_qty"] = round(max(0.0, _f(it.get("received_qty")) - _f(it.get("rejected_qty"))), 4)
    return factor


def po_price_maps(po_doc: dict | None) -> tuple[dict, dict]:
    """(harga per baris PO, harga per material) — satuan dasar."""
    by_item, by_mat = {}, {}
    for pi in (po_doc or {}).get("items") or []:
        c = _f(pi.get("unit_cost"))
        if pi.get("id"):
            by_item[pi["id"]] = c
        if pi.get("material_id"):
            by_mat.setdefault(pi["material_id"], c)
    return by_item, by_mat


def _set_price(it: dict, price: float) -> None:
    it["unit_price"] = round(_f(price), 6)
    it["unit_cost"] = round(_f(price), 6)


async def normalize_gr_items(db, items: list, *, po_doc: dict | None, finance: bool,
                             stored_items: list | None = None) -> list:
    """SATU pintu aturan baris GR (dipanggil saat buat, simpan, dan konfirmasi). Mengubah `items`.

    * satuan → satuan dasar (`convert_line_to_base`); satuan asing ditolak (ValueError, pesan jelas);
    * baris ber-PO: harga = harga baris PO (isian penerima diabaikan);
    * baris tanpa PO: hanya Keuangan yang boleh mengisi harga — isian peran lain diganti harga tersimpan.
    Return label baris yang masih menunggu harga Keuangan (baris bertautan material / aset)."""
    stored = {str(s.get("id")): s for s in (stored_items or []) if isinstance(s, dict) and s.get("id")}
    ids = list({it.get("material_id") for it in items if isinstance(it, dict) and it.get("material_id")})
    mats = {}
    if ids:
        for m in await db.rahaza_materials.find({"id": {"$in": ids}}, {"_id": 0}).to_list(len(ids) + 5):
            mats[m["id"]] = m
    by_item, by_mat = po_price_maps(po_doc)
    pending = []
    for it in items:
        if not isinstance(it, dict):
            continue
        mat = mats.get(it.get("material_id"))
        if mat:
            try:
                convert_line_to_base(it, mat)
            except _uom.UomError:
                codes = [u["unit"] for u in _bom_uom.allowed_units(mat)][:8]
                raise ValueError(
                    f"{line_label(it)}: satuan '{it.get('unit')}' bukan satuan barang {mat.get('code') or ''} — "
                    f"pilih salah satu: {', '.join(codes)}.")
        if po_doc:
            price = by_item.get(it.get("po_item_id")) if it.get("po_item_id") in by_item else \
                by_mat.get(it.get("material_id"), 0.0)
            _set_price(it, price or 0.0)
        elif not finance:
            old = stored.get(str(it.get("id"))) if it.get("id") else None
            _set_price(it, gr_line_price(old or {}))
        is_line = bool(it.get("material_id")) or (it.get("item_type") or "material") == "asset"
        if is_line and gr_line_price(it) <= 0:
            pending.append(line_label(it))
    return pending


def price_status_fields(pending: list) -> dict:
    """Penanda dokumen GR untuk layar ("menunggu harga dari Keuangan")."""
    return {"awaiting_finance_price": bool(pending), "price_pending_lines": list(pending)[:20]}


# ═════════════════════════════════════════════════════════════════════════════
# 2. SATUAN DASAR DIKUNCI SELAMA ADA DOKUMEN TERBUKA
# ═════════════════════════════════════════════════════════════════════════════
async def base_unit_open_documents(db, material_id: str, limit: int = 50) -> list:
    """Dokumen terbuka yang masih memakai satuan dasar lama material ini (dibaca saja)."""
    out: list = []
    if not material_id:
        return out
    async for po in db.rahaza_purchase_orders.find(
            {"status": {"$in": list(PO_OPEN_STATUSES)}, "items.material_id": material_id},
            {"_id": 0, "id": 1, "po_number": 1, "status": 1, "items": 1}):
        rem = sum(max(0.0, _f(i.get("qty_ordered")) - _f(i.get("qty_received")))
                  for i in po.get("items") or [] if i.get("material_id") == material_id)
        if rem > 1e-9 or po.get("status") in ("draft", "pending_approval", "rejected"):
            out.append({"type": "po", "type_label": "PO", "id": po.get("id"), "number": po.get("po_number") or "",
                        "status": po.get("status") or ""})
    async for gr in db.warehouse_receiving.find(
            {"status": {"$in": list(GR_OPEN_STATUSES)}, "items.material_id": material_id},
            {"_id": 0, "id": 1, "receipt_number": 1, "status": 1}):
        out.append({"type": "gr", "type_label": "Penerimaan barang", "id": gr.get("id"),
                    "number": gr.get("receipt_number") or "", "status": gr.get("status") or ""})
    async for pl in db.rahaza_supplier_price_lists.find(
            {"material_id": material_id, "is_active": True},
            {"_id": 0, "id": 1, "supplier_id": 1, "supplier_name": 1, "uom": 1}):
        out.append({"type": "price_list", "type_label": "Daftar harga pemasok", "id": pl.get("id"),
                    "number": pl.get("supplier_name") or pl.get("supplier_id") or "", "status": "aktif"})
    from core.quarantine import QUARANTINE_COLL  # 2026-11-06 (pola P2): koleksi dibaca lewat konstanta penulisnya (satu nama, tidak ada koleksi hantu)
    async for qi in db[QUARANTINE_COLL].find(
            {"material_id": material_id, "status": "open"}, {"_id": 0, "id": 1, "remaining_qty": 1}):
        out.append({"type": "quarantine", "type_label": "Karantina QC", "id": qi.get("id"),
                    "number": f"sisa {_f(qi.get('remaining_qty')):g}", "status": "terbuka"})
    return out[:limit]


def open_documents_message(material: dict, new_base: str, docs: list) -> str:
    head = ", ".join(f"{d['type_label']} {d['number']}".strip() for d in docs[:8])
    more = f" dan {len(docs) - 8} lainnya" if len(docs) > 8 else ""
    return (f"Satuan dasar {material.get('code') or ''} tidak bisa diganti ke '{new_base}': masih ada "
            f"{len(docs)} dokumen terbuka dalam satuan '{_uom.base_uom_of(material)}' — {head}{more}. "
            "Selesaikan, batalkan, atau nonaktifkan dokumen itu dulu supaya angkanya tidak terbaca dalam "
            "satuan yang salah.")


async def check_base_unit_change(db, material: dict | None, new_base: str) -> list:
    """Dokumen yang menghalangi penggantian satuan dasar (kosong = boleh). Satuan sama ⇒ []."""
    if not material or not material.get("id"):
        return []
    nb = _uom.normalize_code(new_base)
    if not nb or nb == _uom.base_uom_of(material):
        return []
    return await base_unit_open_documents(db, material["id"])
