"""core.client_goods — STOK TITIPAN KLIEN MAKLON (Tahap 9C, keputusan owner 7 Nov 2026).

Dasar keputusan:
  * CV Dewi Aditya (DA) memiliki semua bahan & stok; CV Sukma menjalankan maklon dan TIDAK punya stok.
  * Barang jadi maklon MILIK KLIEN — di luar neraca DA (jurnal penerimaan sudah melewatkan maklon).

Dulu (K14, 2 Nov) barang jadi maklon yang diterima dari CMT dibuatkan barang di MASTER PRODUK DA
(`rahaza_materials`, `owner_type="client"`) dan stoknya satu baris `rahaza_material_stock`. Kalau SKU klien
sama dengan SKU DA, barang klien tertempel ke barang DA. Sekarang:

  * Identitas barang = artikel **Katalog Buyer** klien (`dewi_maklon_buyer_catalog` + varian di dalamnya),
    tidak pernah master produk DA.
  * Stok dipegang **per klien × artikel/varian**, HANYA jumlah (pcs) — tanpa nilai, tanpa lapisan biaya,
    tanpa jurnal.
  * Wadahnya koleksi yang SUDAH ADA dan terdaftar: `dewi_maklon_inventory` ("material milik klien",
    buku mutasi per klien, `ownership="maklon_client"`). Barang jadi memakai `inventory_category="maklon_fg"`.
    Tidak ada koleksi baru.

Kontrak satu dokumen mutasi barang jadi klien (`inventory_category == "maklon_fg"`):
  id, movement_type (lihat JENIS), ownership="maklon_client", maklon_client_id, maklon_client_name,
  buyer_catalog_id, artikel_code, product_name, maklon_variant_id, sku, color, size, unit="pcs",
  stock_key (klien|artikel|varian — kunci saldo), qty (BERTANDA: + masuk, − keluar), location_id,
  source_type, source_key (unik bila diisi → idempoten), ref{...}, maklon_po_ref, po_id, notes,
  created_at, created_by, created_by_name.
Saldo = Σ qty per `stock_key`. Tidak ada field nilai/harga.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

COLL = "dewi_maklon_inventory"          # koleksi lama yang dipakai ulang (terdaftar di collection_registry)
CATALOG = "dewi_maklon_buyer_catalog"
CLIENTS = "dewi_maklon_clients"
KATEGORI = "maklon_fg"                  # sama dengan production_qty_ledger.MAKLON_FG_CATEGORY
OWNERSHIP = "maklon_client"
OWNERSHIP_FILTER = "titipan_klien"      # nilai saringan Kepemilikan di layar gudang
OWNERSHIP_DA = "cv_da"

# Label layar (bahasa staf, bukan kode)
OWNERSHIP_LABELS = {OWNERSHIP_DA: "Milik CV Dewi Aditya", OWNERSHIP_FILTER: "Titipan klien maklon"}
JENIS = {
    "masuk_terima_qc": "Masuk · terima & QC dari CMT",
    "masuk_permak": "Masuk · hasil permak",
    "koreksi_qc": "Koreksi hasil QC",
    "keluar_kirim_klien": "Keluar · kirim ke klien",
    "kembali_batal_kirim": "Kembali · surat jalan dihapus",
    "koreksi_kirim": "Koreksi jumlah dikirim",
    "kembali_selisih_klien": "Kembali · belum sampai di klien",
    "keluar_selisih_batal": "Keluar · selisih dibatalkan",
    "keluar_hilang": "Keluar · dinyatakan hilang",
    "pindah_dari_master_da": "Pindah dari master barang DA",
}


class ClientGoodsError(ValueError):
    """Barang klien tidak bisa dicatat (pesan siap tampil, bahasa Indonesia)."""


class ClientStockShortfall(ClientGoodsError):
    def __init__(self, identity: dict, need: float, have: float):
        self.identity, self.need, self.have = identity, need, have
        label = identity.get("sku") or identity.get("artikel_code") or "barang klien"
        super().__init__(
            f"Stok titipan klien {label} ({identity.get('client_name') or 'klien maklon'}) tidak cukup: "
            f"butuh {need:g} pcs, tersedia {have:g} pcs. Selesaikan Terima & QC dari CMT dulu.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _i(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _norm(v) -> str:
    return str(v or "").strip().lower()


def is_maklon(business_type) -> bool:
    """PO/kiriman maklon = jenis selain internal (kosong/None = internal, data lama)."""
    return bool(business_type) and str(business_type) != "internal"


def stock_key(client_id: str, catalog_id: str, variant_id: str = "", sku: str = "") -> str:
    """Kunci saldo: klien | artikel katalog | varian (atau SKU bila artikel belum punya varian)."""
    tail = variant_id or (f"sku:{str(sku or '').strip().upper()}" if sku else "-")
    return f"{client_id or '-'}|{catalog_id or '-'}|{tail}"


def pick_variant(cat: dict, *, variant_id: str = "", sku: str = "", color: str = "", size: str = "") -> dict | None:
    """Varian di DALAM artikel ini (fungsi murni): id → SKU → warna+ukuran. Tidak menebak di luar artikel."""
    variants = [v for v in (cat or {}).get("variants") or [] if isinstance(v, dict)]
    if variant_id:
        for v in variants:
            if v.get("id") == variant_id:
                return v
    if sku:
        hits = [v for v in variants if _norm(v.get("sku")) == _norm(sku)]
        if len(hits) == 1:
            return hits[0]
    if color and size:
        hits = [v for v in variants if _norm(v.get("color")) == _norm(color) and _norm(v.get("size")) == _norm(size)]
        if len(hits) == 1:
            return hits[0]
    return None


def identity_from(cat: dict, variant: dict | None, *, sku: str = "", color: str = "", size: str = "",
                  how: str = "", client_name: str = "") -> dict:
    """Identitas barang klien dari artikel + varian (fungsi murni)."""
    client_id = cat.get("client_id") or ""
    v = variant or {}
    v_sku = v.get("sku") or sku or ""
    return {
        "ok": True, "match": how,
        "client_id": client_id, "client_name": client_name or cat.get("client_name") or "",
        "buyer_catalog_id": cat.get("id") or "", "artikel_code": cat.get("artikel_code") or "",
        "product_name": cat.get("product_name") or "", "category": cat.get("category") or "",
        "maklon_variant_id": v.get("id") or "", "sku": v_sku,
        "color": v.get("color") or color or "", "size": v.get("size") or size or "",
        "stock_key": stock_key(client_id, cat.get("id") or "", v.get("id") or "", v_sku),
    }


def _fail(reason: str) -> dict:
    return {"ok": False, "reason": reason}


async def _client_name(db, client_id: str) -> str:
    if not client_id:
        return ""
    c = await db[CLIENTS].find_one({"id": client_id}, {"_id": 0, "name": 1})
    return (c or {}).get("name") or ""


async def resolve_identity(db, *, client_id: str = "", po_item: dict | None = None, po_item_id: str = "",
                           sku: str = "", color: str = "", size: str = "", product_name: str = "",
                           catalog_id: str = "", variant_id: str = "") -> dict:
    """Artikel Katalog Buyer untuk satu baris barang klien.

    Urutan (tanpa menebak):
      1. tautan baris PO (`po_items.catalog_item_id` + `maklon_variant_id`);
      2. SKU varian yang PERSIS sama di katalog klien itu (harus tepat satu artikel).
    Hasil `{"ok": False, "reason": …}` bila tidak ada artikel yang cocok — pemanggil menolak/menandai,
    bukan memakai master produk DA."""
    if po_item is None and po_item_id:
        po_item = await db.po_items.find_one({"id": po_item_id}, {"_id": 0})
    pi = po_item or {}
    catalog_id = catalog_id or pi.get("catalog_item_id") or pi.get("buyer_catalog_id") or ""
    variant_id = variant_id or pi.get("maklon_variant_id") or ""
    sku = (sku or pi.get("sku") or "").strip()
    color = color or pi.get("color") or ""
    size = size or pi.get("size") or ""
    label = sku or product_name or pi.get("product_name") or "barang"
    cat, how = None, ""
    if catalog_id:
        cat = await db[CATALOG].find_one({"id": catalog_id}, {"_id": 0})
        how = "tautan_po" if cat else ""
    if not cat and sku and client_id:
        cands = [c for c in await db[CATALOG].find({"client_id": client_id}, {"_id": 0}).to_list(2000)
                 if any(_norm(v.get("sku")) == _norm(sku) for v in (c.get("variants") or []) if isinstance(v, dict))]
        if len(cands) == 1:
            cat, how = cands[0], "sku_katalog"
        elif len(cands) > 1:
            return _fail(f"SKU {sku} ada di {len(cands)} artikel Katalog Buyer klien ini — "
                         "tautkan baris PO ke artikel yang benar.")
    if not cat:
        return _fail(f"{label} belum tertaut ke artikel Katalog Buyer klien — tautkan baris PO maklon ke "
                     "artikel katalognya (Klien & Katalog Buyer) supaya barang klien tercatat terpisah.")
    variant = pick_variant(cat, variant_id=variant_id, sku=sku, color=color, size=size)
    ident = identity_from(cat, variant, sku=sku, color=color, size=size, how=how,
                          client_name=await _client_name(db, cat.get("client_id") or ""))
    if client_id and cat.get("client_id") and cat["client_id"] != client_id:
        ident["warning"] = (f"Artikel {cat.get('artikel_code')} milik klien lain dari buyer PO — "
                            "stok dicatat atas nama pemilik artikel.")
    return ident


async def client_of_po(db, po_id: str) -> dict:
    """{'id','name','business_type'} klien PO (production_pos.buyer_id)."""
    if not po_id:
        return {"id": "", "name": "", "business_type": ""}
    po = await db.production_pos.find_one(
        {"id": po_id}, {"_id": 0, "buyer_id": 1, "customer_name": 1, "business_type": 1, "po_number": 1}) or {}
    return {"id": po.get("buyer_id") or "", "name": po.get("customer_name") or "",
            "business_type": po.get("business_type") or "", "po_number": po.get("po_number") or ""}


async def balance(db, key: str) -> float:
    """Saldo pcs satu `stock_key` (Σ qty bertanda)."""
    if not key:
        return 0.0
    rows = await db[COLL].find({"stock_key": key, "inventory_category": KATEGORI},
                               {"_id": 0, "qty": 1}).to_list(50000)
    return float(sum(_i(r.get("qty")) for r in rows))


async def record(db, *, identity: dict, qty: int, jenis: str, source_type: str, source_key: str = "",
                 ref: dict | None = None, actor: dict | None = None, notes: str = "",
                 location_id: str | None = None, allow_negative: bool = False) -> dict:
    """Catat SATU mutasi barang klien (qty bertanda). Idempoten per `source_key`.

    Keluar (qty < 0) tidak boleh membuat saldo minus kecuali `allow_negative`. Tidak menulis nilai,
    lapisan biaya, maupun jurnal — barang ini bukan milik DA."""
    qty = _i(qty)
    if not identity or not identity.get("ok"):
        raise ClientGoodsError((identity or {}).get("reason") or "Identitas barang klien tidak lengkap.")
    if qty == 0:
        return {"skipped": True, "qty": 0}
    if jenis not in JENIS:
        raise ClientGoodsError(f"Jenis mutasi barang klien tidak dikenal: {jenis}")
    if source_key:
        prev = await db[COLL].find_one({"source_key": source_key}, {"_id": 0})
        if prev:
            return {**prev, "already": True}
    if qty < 0 and not allow_negative:
        have = await balance(db, identity["stock_key"])
        if have + 1e-9 < -qty:
            raise ClientStockShortfall(identity, -qty, have)
    r = ref or {}
    doc = {
        "id": str(uuid.uuid4()), "movement_type": jenis,
        "ownership": OWNERSHIP, "inventory_category": KATEGORI,
        "maklon_client_id": identity.get("client_id") or "",
        "maklon_client_name": identity.get("client_name") or "",
        "buyer_catalog_id": identity.get("buyer_catalog_id") or "",
        "artikel_code": identity.get("artikel_code") or "",
        "product_name": identity.get("product_name") or "",
        "maklon_variant_id": identity.get("maklon_variant_id") or "",
        "sku": identity.get("sku") or "", "color": identity.get("color") or "",
        "size": identity.get("size") or "", "unit": "pcs",
        "stock_key": identity["stock_key"], "qty": qty,
        "location_id": location_id or "",
        "source_type": source_type, "source_key": source_key or None,
        "ref": r, "po_id": r.get("po_id") or "", "maklon_po_ref": r.get("po_number") or "",
        "notes": notes or "",
        "created_at": _now(), "created_by": (actor or {}).get("id") or "sistem",
        "created_by_name": (actor or {}).get("name") or "sistem",
    }
    if not source_key:
        doc.pop("source_key")
    try:
        await db[COLL].insert_one(dict(doc))
    except Exception as e:  # noqa: BLE001 — indeks unik source_key: permintaan kembar
        if source_key and type(e).__name__ == "DuplicateKeyError":
            prev = await db[COLL].find_one({"source_key": source_key}, {"_id": 0})
            return {**(prev or doc), "already": True}
        raise
    return doc


async def identity_for_key(db, key: str, fallback: dict | None = None) -> dict:
    """Identitas saldo yang SUDAH ada (dari mutasi terakhirnya) — dipakai saat barang yang tadinya
    keluar/masuk lewat stok titipan bergerak lagi (hapus SJ, koreksi, permak)."""
    fb = fallback or {}
    last = await db[COLL].find_one({"stock_key": key}, {"_id": 0}) or {}
    return {"ok": bool(key), "reason": "" if key else "Saldo titipan tidak dikenal.", "stock_key": key,
            "client_id": last.get("maklon_client_id") or fb.get("client_id") or "",
            "client_name": last.get("maklon_client_name") or "",
            "buyer_catalog_id": last.get("buyer_catalog_id") or "", "artikel_code": last.get("artikel_code") or "",
            "product_name": last.get("product_name") or fb.get("product_name") or "",
            "maklon_variant_id": last.get("maklon_variant_id") or "",
            "sku": last.get("sku") or fb.get("sku") or fb.get("sku_code") or "",
            "color": last.get("color") or fb.get("color") or "", "size": last.get("size") or fb.get("size") or ""}


async def record_for_key(db, *, key: str, qty: int, jenis: str, source_type: str, source_key: str = "",
                         ref: dict | None = None, actor: dict | None = None, notes: str = "",
                         allow_negative: bool = False, fallback: dict | None = None) -> dict | None:
    """Mutasi untuk baris (surat jalan / penerimaan) yang SUDAH tercatat di stok titipan
    (`client_stock_key` terisi). None bila tidak ada kunci (baris lama → jalur lama)."""
    if not key:
        return None
    return await record(db, identity=await identity_for_key(db, key, fallback), qty=qty, jenis=jenis,
                        source_type=source_type, source_key=source_key, ref=ref, actor=actor, notes=notes,
                        allow_negative=allow_negative)


async def precheck_dispatch(db, items_data: list, *, client_id: str = "") -> list:
    """Pagar sebelum surat jalan maklon ditulis: setiap baris harus artikel Katalog Buyer dan stok
    titipannya cukup. Melempar ClientGoodsError (pesan siap tampil). → daftar peringatan."""
    need: dict = {}
    idents: dict = {}
    warnings = []
    for it in items_data or []:
        qty = _i(it.get("qty_shipped"))
        if qty <= 0:
            continue
        ident = await resolve_identity(db, client_id=client_id, po_item_id=it.get("po_item_id") or "",
                                       sku=it.get("sku") or "", color=it.get("color") or "",
                                       size=it.get("size") or "", product_name=it.get("product_name") or "")
        if not ident.get("ok"):
            raise ClientGoodsError(ident["reason"])
        if ident.get("warning"):
            warnings.append(ident["warning"])
        idents[ident["stock_key"]] = ident
        need[ident["stock_key"]] = need.get(ident["stock_key"], 0) + qty
    for key, qty in need.items():
        have = await balance(db, key)
        if have + 1e-9 < qty:
            raise ClientStockShortfall(idents[key], qty, have)
    return warnings


# ─────────────────────────────────────────────────────────────────────────────
# BACA — daftar stok titipan & riwayat mutasi
# ─────────────────────────────────────────────────────────────────────────────
async def list_stock(db, *, client_id: str = "", include_zero: bool = False) -> list[dict]:
    """Saldo titipan per klien × artikel/varian.

    `include_zero=True` menambahkan varian AKTIF artikel Katalog Buyer klien (yang belum pernah punya
    mutasi) dengan qty 0 — bukan master produk DA (bug lama: "stok 0" menampilkan seluruh master DA)."""
    q = {"inventory_category": KATEGORI}
    if client_id:
        q["maklon_client_id"] = client_id
    moves = await db[COLL].find(q, {"_id": 0}).sort("created_at", 1).to_list(50000)
    groups: dict = {}
    for m in moves:
        k = m.get("stock_key")
        if not k:
            continue
        g = groups.setdefault(k, {"stock_key": k, "quantity": 0, "movements": 0})
        g["quantity"] += _i(m.get("qty"))
        g["movements"] += 1
        g["last_movement_at"] = m.get("created_at")
        for f in ("maklon_client_id", "maklon_client_name", "buyer_catalog_id", "artikel_code", "product_name",
                  "maklon_variant_id", "sku", "color", "size", "location_id"):
            if m.get(f):
                g[f] = m[f]
    cat_q = {"client_id": client_id} if client_id else {}
    cats = await db[CATALOG].find(cat_q, {"_id": 0}).to_list(5000)
    cat_map = {c.get("id"): c for c in cats}
    clients = {c.get("id"): c.get("name") or "" for c in
               await db[CLIENTS].find({}, {"_id": 0, "id": 1, "name": 1}).to_list(5000)}
    rows = []
    for g in groups.values():
        cat = cat_map.get(g.get("buyer_catalog_id")) or {}
        var = pick_variant(cat, variant_id=g.get("maklon_variant_id") or "") if cat else None
        rows.append({
            **g,
            "maklon_client_name": clients.get(g.get("maklon_client_id")) or g.get("maklon_client_name") or "",
            "artikel_code": cat.get("artikel_code") or g.get("artikel_code") or "",
            "product_name": cat.get("product_name") or g.get("product_name") or "",
            "category": cat.get("category") or "",
            "sku": (var or {}).get("sku") or g.get("sku") or "",
            "color": (var or {}).get("color") or g.get("color") or "",
            "size": (var or {}).get("size") or g.get("size") or "",
            "catalog_linked": bool(cat), "no_stock_row": False,
        })
    if include_zero:
        have = set(groups)
        for cat in cats:
            if (cat.get("status") or "active") != "active":
                continue
            for v in cat.get("variants") or []:
                if not isinstance(v, dict) or v.get("active") is False:
                    continue
                ident = identity_from(cat, v, how="katalog")
                if ident["stock_key"] in have:
                    continue
                rows.append({
                    "stock_key": ident["stock_key"], "quantity": 0, "movements": 0,
                    "maklon_client_id": ident["client_id"],
                    "maklon_client_name": clients.get(ident["client_id"]) or cat.get("client_name") or "",
                    "buyer_catalog_id": ident["buyer_catalog_id"], "artikel_code": ident["artikel_code"],
                    "product_name": ident["product_name"], "category": ident["category"],
                    "maklon_variant_id": ident["maklon_variant_id"], "sku": ident["sku"],
                    "color": ident["color"], "size": ident["size"], "location_id": "",
                    "catalog_linked": True, "no_stock_row": True,
                })
    else:
        rows = [r for r in rows if r["quantity"] != 0]
    rows.sort(key=lambda r: (_norm(r.get("maklon_client_name")), _norm(r.get("artikel_code")),
                             _norm(r.get("sku"))))
    return rows


async def movements(db, key: str, limit: int = 50) -> list[dict]:
    """Riwayat mutasi satu saldo titipan (terbaru dulu), dengan label bahasa Indonesia."""
    rows = await db[COLL].find({"stock_key": key, "inventory_category": KATEGORI}, {"_id": 0}) \
        .sort("created_at", -1).limit(max(1, min(500, int(limit or 50)))).to_list(500)
    out = []
    for m in rows:
        r = m.get("ref") or {}
        out.append({
            "id": m.get("id"), "created_at": m.get("created_at"),
            "jenis": m.get("movement_type"), "jenis_label": JENIS.get(m.get("movement_type"), "Mutasi"),
            "qty": _i(m.get("qty")),
            "dokumen": (r.get("receipt_code") or r.get("shipment_number") or r.get("permak_number")
                        or r.get("short_number") or r.get("source_label") or ""),
            "po_number": m.get("maklon_po_ref") or r.get("po_number") or "",
            "notes": m.get("notes") or "", "oleh": m.get("created_by_name") or "",
        })
    return out
