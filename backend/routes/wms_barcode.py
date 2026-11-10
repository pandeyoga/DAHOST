"""FASE H-3 (2026-08-16) — MENU "BUAT BARCODE": satu pintu cetak label.

Keadaan sebelum berkas ini (diukur, bukan dugaan):
  · `POST /api/wms/materials/labels/batch-pdf` & `POST /api/wms/fg/labels/batch-pdf`
    sudah ada berbulan-bulan dengan **0 pemanggil di seluruh frontend** ⇒ dari sudut
    pandang pemakai, barcode bahan & barang jadi TIDAK BISA dicetak.
  · Keduanya hanya bisa 1 label per item — padahal pekerjaan gudang selalu
    "cetak 50 lembar untuk satu artikel".
  · Jalur FG membaca `rahaza_fg_matrix` yang di basis data ini **KOSONG (0 dokumen)**,
    sementara barang jadi yang nyata hidup di `rahaza_materials` (`type='fg'`, 332
    dokumen, lahir otomatis dari varian master). Artinya tombol cetak FG akan
    SELALU menjawab 404 "tidak ditemukan" — cacat yang mustahil terlihat dari
    daftar endpoint, karena endpoint-nya sendiri "ada".

Aturan yang dipegang endpoint ini:
  1. **Nilai barcode = kode master.** Tidak ada field untuk mengetik kode bebas.
     Barcode yang kodenya dikarang akan discan menjadi item yang tidak ada di
     sistem — dan barang fisiknya sudah tertempel label itu (aturan F14).
  2. **Sumber "otomatis dari produksi" wajib menyebut yang TIDAK ketemu di master.**
     Baris PO yang SKU-nya belum punya varian master dilaporkan
     `master_linked: false` beserta alasannya, bukan dibuang diam-diam dan bukan
     dicetak seolah-olah sah.
  3. **Batas label per cetak** (`MAX_LABELS`) supaya satu klik tidak melahirkan
     PDF ribuan halaman yang menggantung browser.
  4. **Riwayat cetak dicatat** (`wh_barcode_print_jobs`): "siapa mencetak label
     apa, berapa lembar, kapan" adalah satu-satunya cara menjawab pertanyaan
     "kenapa ada dua label dengan kode sama di gudang".

10 Nov 2026 (permintaan owner — "pilih dari master tapi tidak bisa search dan tidak bisa filter … harusnya
bisa juga dari pembelian misal kain roll"):
  5. `/items` menerima penyaring **kategori** & **warna** (label manusia dari master, bukan id kategori) dan
     mengembalikan pilihan penyaringnya; daftar bisa dimuat bertahap (`skip`), tidak lagi berhenti di 60.
  6. Sumber otomatis kedua: **Dari penerimaan barang** (`/receipt-options`, `/from-receipt`). Bahan non-kain
     → label bahan (jumlah lembar bawaan = qty diterima bila satuannya hitungan); kain → **label roll**, satu
     per gulungan yang lahir dari penerimaan itu (`wh_fabric_rolls.source_receipt_id` /
     `source_receipt_item_id`, ditulis `fabric_roll_engine.create_rolls_from_receipt`). Kain yang belum punya
     roll TIDAK dicetak dengan kode bahan sebagai gantinya — diarahkan ke Roll Kain › Penerimaan tanpa roll.
     Nilai barcode roll = nomor roll (sama dengan label roll satuan), tetap bukan ketikan bebas.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import log_activity, require_auth, serialize_doc
from core import fabric_roll_engine as fre
from core import label_render as lr
from database import get_db
from utils.counters import gen_prefixed_number
from utils.waktu import fmt_wib

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wms/barcode", tags=["wms-barcode"])

MAX_LABELS = 500          # total lembar per satu PDF
MAX_COPIES_PER_ROW = 200
KINDS = ("material", "fg")
# 2026-11-02 (keputusan owner): pilihan ukuran label barang jadi — standar 100×70 atau hangtag 70×40.
FG_SIZES = {"standard": "fg", "hangtag": "fg_hangtag"}
MASTER_LIMIT = 20000
# 2026-11-10: sumber cetak yang dicatat di riwayat (layar: Manual · Dari produksi · Dari pembelian).
SOURCES = ("manual", "produksi", "pembelian")
TANPA_KATEGORI = "__tanpa__"
RECEIPT_OPTIONS_MAX = 100
# Satuan HITUNGAN: 1 satuan = 1 benda/kemasan yang bisa ditempeli label → lembar bawaan = qty diterima.
COUNT_UNITS = {"pcs", "buah", "biji", "unit", "helai", "lembar", "set", "pair", "pasang", "lusin", "kodi",
               "gross", "roll", "rol", "pack", "pak", "karton", "dus", "box", "sak"}
# Label jenis bahan (dicetak di label bila master tidak punya nama kategori) — bukan kode `type` mentah.
TYPE_LABEL = {"fabric": "Kain", "kain": "Kain", "yarn": "Benang", "benang": "Benang", "interlining": "Interlining",
              "accessory": "Aksesoris", "packaging": "Kemasan", "other": "Lainnya", "fg": "Barang jadi"}
_UUIDISH = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", re.I)


def _now():
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _kind_filter(kind: str) -> dict:
    return {"type": "fg"} if kind == "fg" else {"type": {"$ne": "fg"}}


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(400, f"kind harus salah satu dari {KINDS}")
    return kind


async def _category_names(db) -> dict:
    """id/kode kategori master material → nama. Dokumen master lama menyimpan `category` = id kategori
    (UUID); nama itu yang ditampilkan & dicetak, bukan id-nya."""
    rows = await db.rahaza_material_categories.find(
        {}, {"_id": 0, "id": 1, "code": 1, "name": 1}).to_list(500)
    out = {}
    for c in rows:
        nm = str(c.get("name") or "").strip()
        for k in (c.get("id"), c.get("code")):
            if k and nm:
                out[str(k)] = nm
    return out


def _category_label(m: dict, names: dict) -> str:
    nm = str(m.get("category_name") or "").strip()
    if nm:
        return nm
    for k in ("category", "category_id", "category_code"):
        v = str(m.get(k) or "").strip()
        if v and v in names:
            return names[v]
    v = str(m.get("category") or "").strip()
    return "" if (not v or _UUIDISH.match(v)) else v


def _color_label(m: dict) -> str:
    return str(m.get("color_name") or m.get("color") or "").strip()


def _slim(m: dict, names: Optional[dict] = None) -> dict:
    return {
        "id": m.get("id"), "code": m.get("code") or m.get("sku"),
        "name": m.get("name"), "unit": lr.unit_of(m), "type": m.get("type"),
        "category": _category_label(m, names or {}), "color": _color_label(m),
        "size": m.get("size_code") or m.get("size") or "",
        "model_code": m.get("model_code") or "", "is_cut_panel": bool(m.get("is_cut_panel")),
    }


def _options(counter: Counter, extra_last: Optional[tuple] = None) -> list:
    opts = [{"value": k, "label": k, "count": n} for k, n in sorted(counter.items(), key=lambda kv: kv[0].lower())]
    if extra_last and extra_last[2]:
        opts.append({"value": extra_last[0], "label": extra_last[1], "count": extra_last[2]})
    return opts


# ══════════════════════════════════════════════════════════════════════════════
# 1. Pemilih item dari MASTER
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/items")
async def barcode_items(
    request: Request,
    kind: str = Query("material"),
    q: str = Query("", max_length=120),
    category: str = Query("", max_length=120),
    color: str = Query("", max_length=120),
    skip: int = Query(0, ge=0),
    limit: int = Query(60, ge=1, le=300),
):
    """Daftar item master untuk dipilih. Barcode HANYA boleh dari master ini.

    Penyaring kategori/warna memakai LABEL manusia (nama kategori master, warna), karena `category` di master
    bisa berisi id kategori. Kategori & warna disaring di sini dari satu pembacaan master jenis itu (≈2 ribu
    dokumen, kolom ringkas) — pilihan penyaringnya ikut dikembalikan supaya layar tidak menebak.
    """
    await require_auth(request)
    _check_kind(kind)
    db = get_db()
    names = await _category_names(db)
    base = await db.rahaza_materials.find(
        {"active": {"$ne": False}, **_kind_filter(kind)},
        {"_id": 0, "id": 1, "code": 1, "sku": 1, "name": 1, "category": 1, "category_name": 1,
         "category_id": 1, "category_code": 1, "color": 1, "color_name": 1},
    ).limit(MASTER_LIMIT).to_list(MASTER_LIMIT)

    needle = q.strip().lower()
    cat_count, color_count, tanpa = Counter(), Counter(), 0
    hits = []
    for m in base:
        cat = _category_label(m, names)
        if cat:
            cat_count[cat] += 1
        else:
            tanpa += 1
        if category:
            if category == TANPA_KATEGORI:
                if cat:
                    continue
            elif cat != category:
                continue
        col = _color_label(m)
        if col:
            color_count[col] += 1        # pilihan warna mengikuti kategori terpilih
        if color and col != color:
            continue
        if needle and not any(needle in str(m.get(k) or "").lower() for k in ("code", "name", "sku")):
            continue
        hits.append(m)
    hits.sort(key=lambda m: str(m.get("code") or m.get("sku") or ""))
    page_ids = [m.get("id") for m in hits[skip:skip + limit]]
    full = {d["id"]: d for d in await db.rahaza_materials.find(
        {"id": {"$in": page_ids}}, {"_id": 0}).to_list(limit)} if page_ids else {}
    rows = [full[i] for i in page_ids if i in full]
    return {"kind": kind, "total": len(hits), "returned": len(rows), "skip": skip,
            "has_more": skip + len(rows) < len(hits),
            "items": [_slim(m, names) for m in rows],
            "categories": _options(cat_count, (TANPA_KATEGORI, "Tanpa kategori", tanpa)),
            "colors": _options(color_count)}


# ══════════════════════════════════════════════════════════════════════════════
# 2. Sumber OTOMATIS: dari PO produksi
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/production-options")
async def production_options(request: Request, limit: int = Query(30, ge=1, le=100)):
    """PO produksi terbaru + jumlah pcs — untuk mode 'otomatis dari produksi'."""
    await require_auth(request)
    db = get_db()
    pos = await db.production_pos.find(
        {}, {"_id": 0, "id": 1, "po_number": 1, "business_type": 1, "status": 1,
             "customer_name": 1, "buyer_name": 1, "created_at": 1}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    ids = [p["id"] for p in pos]
    agg = {}
    if ids:
        async for it in db.po_items.find({"po_id": {"$in": ids}},
                                         {"_id": 0, "po_id": 1, "qty": 1}):
            e = agg.setdefault(it["po_id"], {"items": 0, "qty": 0})
            e["items"] += 1
            e["qty"] += int(it.get("qty") or 0)
    for p in pos:
        e = agg.get(p["id"], {"items": 0, "qty": 0})
        p["item_count"] = e["items"]
        p["total_qty"] = e["qty"]
    return serialize_doc(pos)


async def _resolve_fg_master(db, item: dict) -> Optional[dict]:
    """SKU PO → varian FG master. Tiga percobaan, dari paling pasti ke paling longgar.

    Kenapa tidak cukup mencocokkan SKU: SKU pada `po_items` demo internal berbunyi
    `DA-TS01-ALLSIZE` (tanpa kode warna) sementara varian master bernama
    `DA-TS01-HTM-ALLSIZE`. Mencocokkan hanya lewat SKU akan melaporkan "tidak ada
    di master" untuk barang yang jelas ADA — dan orang akan berhenti percaya
    penandanya.
    """
    sku = (item.get("sku") or "").strip()
    if sku:
        m = await db.rahaza_materials.find_one(
            {"type": "fg", "$or": [{"code": sku}, {"sku": sku}]}, {"_id": 0})
        if m:
            return m
    model_id, size_id = item.get("model_id"), item.get("size_id")
    color = (item.get("color") or "").strip().lower()
    if model_id and size_id:
        cands = await db.rahaza_materials.find(
            {"type": "fg", "model_id": model_id, "size_id": size_id}, {"_id": 0}
        ).to_list(200)
        if cands:
            if color:
                for c in cands:
                    names = {str(c.get(k) or "").strip().lower()
                             for k in ("color", "color_name", "color_code")}
                    if color in names:
                        return c
            elif len(cands) == 1:
                return cands[0]
    if model_id and (item.get("size") or "").strip():
        size = item["size"].strip().upper()
        cands = await db.rahaza_materials.find(
            {"type": "fg", "model_id": model_id, "size_code": size}, {"_id": 0}
        ).to_list(200)
        for c in cands:
            names = {str(c.get(k) or "").strip().lower()
                     for k in ("color", "color_name", "color_code")}
            if not color or color in names:
                return c
    return None


@router.get("/from-production")
async def from_production(request: Request, po_id: str = Query(..., min_length=1)):
    """Baris label yang MENGIKUTI produksi: artikel + jumlah dari PO."""
    await require_auth(request)
    db = get_db()
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO produksi tidak ditemukan")
    items = await db.po_items.find({"po_id": po_id}, {"_id": 0}).to_list(MASTER_LIMIT)
    rows, unlinked = [], 0
    for it in items:
        fg = await _resolve_fg_master(db, it)
        if fg:
            rows.append({
                "material_id": fg.get("id"), "code": fg.get("code") or fg.get("sku"),
                "name": fg.get("name"), "size": fg.get("size_code") or it.get("size") or "",
                "color": fg.get("color_name") or fg.get("color") or it.get("color") or "",
                "copies": int(it.get("qty") or 0), "master_linked": True,
                "po_sku": it.get("sku") or "",
            })
        else:
            unlinked += 1
            rows.append({
                "material_id": None, "code": it.get("sku") or "",
                "name": it.get("product_name") or "", "size": it.get("size") or "",
                "color": it.get("color") or "", "copies": int(it.get("qty") or 0),
                "master_linked": False, "po_sku": it.get("sku") or "",
                "reason": "SKU ini belum punya varian di master Barang Jadi — "
                          "buat variannya dulu di Master Produk, jangan cetak label "
                          "dengan kode yang tidak dikenal sistem.",
            })
    return {"po_id": po_id, "po_number": po.get("po_number"),
            "business_type": po.get("business_type"), "kind": "fg",
            "rows": rows, "unlinked_count": unlinked,
            "total_copies": sum(r["copies"] for r in rows)}


# ══════════════════════════════════════════════════════════════════════════════
# 2b. Sumber OTOMATIS: dari penerimaan barang (pembelian) — 10 Nov 2026
# ══════════════════════════════════════════════════════════════════════════════

def _accepted(it: dict) -> float:
    """Qty yang benar-benar masuk gudang dari satu baris penerimaan (diterima − ditolak)."""
    if it.get("accepted_qty") is not None:
        return max(0.0, _f(it.get("accepted_qty")))
    return max(0.0, _f(it.get("received_qty")) - _f(it.get("rejected_qty")))


def default_copies(qty: float, unit: str) -> int:
    """Lembar bawaan label bahan dari penerimaan: qty diterima bila satuannya HITUNGAN, bulat, dan ≤ 200;
    selain itu 1 (kg/meter/yard tidak bisa diartikan "satu label per satuan"). Tetap bisa diubah di layar."""
    u = str(unit or "").strip().lower()
    if u in COUNT_UNITS and 0 < qty <= MAX_COPIES_PER_ROW and abs(qty - round(qty)) < 1e-9:
        return int(round(qty))
    return 1


def _roll_row(roll: dict) -> dict:
    v = fre.with_display_uom(roll)
    return {
        "label_kind": "roll", "roll_id": roll.get("id"), "code": roll.get("roll_no") or "",
        "name": roll.get("material_name") or "", "material_code": roll.get("material_code") or "",
        "color": roll.get("color") or "", "color_lot": roll.get("color_lot") or "",
        "unit": v.get("uom") or "", "qty_total": v.get("qty_total"), "qty_remaining": v.get("qty_remaining"),
        "status": roll.get("status") or "", "copies": 1, "master_linked": True,
    }


def roll_label_doc(roll: dict) -> dict:
    """Isi label roll — format SAMA dengan label roll satuan (`wms_fabric_rolls.roll_label_pdf`)."""
    v = fre.with_display_uom(roll)
    unit = v.get("uom") or "meter"
    return {**v, "qty_text": f"Qty: {v['qty_total']:,.2f} {unit} · sisa {v['qty_remaining']:,.2f} {unit}"}


@router.get("/receipt-options")
async def receipt_options(request: Request, limit: int = Query(RECEIPT_OPTIONS_MAX, ge=1, le=RECEIPT_OPTIONS_MAX)):
    """Penerimaan barang yang SUDAH diterima (stoknya sudah masuk), terbaru dulu — untuk 'Dari penerimaan barang'."""
    await require_auth(request)
    db = get_db()
    grs = await db.warehouse_receiving.find(
        {"status": "received"},
        {"_id": 0, "id": 1, "receipt_number": 1, "supplier_name": 1, "po_number": 1, "po_id": 1,
         "received_at": 1, "created_at": 1, "items": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit)
    ids = [g.get("id") for g in grs if g.get("id")]
    rolls = Counter()
    if ids:
        for r in await db.wh_fabric_rolls.find(
                {"source_receipt_id": {"$in": ids}, "status": {"$ne": "cancelled"}},
                {"_id": 0, "source_receipt_id": 1}).to_list(MASTER_LIMIT):
            rolls[r.get("source_receipt_id")] += 1
    return serialize_doc([{
        "id": g.get("id"), "receipt_number": g.get("receipt_number") or "",
        "supplier_name": g.get("supplier_name") or "", "po_number": g.get("po_number") or "",
        "received_at": g.get("received_at") or g.get("created_at"),
        "item_count": len(g.get("items") or []), "roll_count": rolls.get(g.get("id"), 0),
    } for g in grs])


@router.get("/from-receipt")
async def from_receipt(request: Request, receipt_id: str = Query(..., min_length=1)):
    """Baris label yang MENGIKUTI penerimaan barang: bahan non-kain → label bahan; kain → label per roll."""
    await require_auth(request)
    db = get_db()
    gr = await db.warehouse_receiving.find_one({"id": receipt_id}, {"_id": 0})
    if not gr:
        raise HTTPException(404, "Penerimaan barang tidak ditemukan.")
    no = gr.get("receipt_number") or ""
    if gr.get("status") != "received":
        raise HTTPException(400, f"Penerimaan {no} belum selesai diterima — label dicetak setelah barangnya "
                                 "diterima dan masuk stok.")
    items = gr.get("items") or []
    mat_ids = list({it.get("material_id") for it in items if it.get("material_id")})
    mats = {m["id"]: m for m in await db.rahaza_materials.find(
        {"id": {"$in": mat_ids}}, {"_id": 0}).to_list(MASTER_LIMIT)} if mat_ids else {}
    rolls = [r for r in await db.wh_fabric_rolls.find(
        {"source_receipt_id": receipt_id}, {"_id": 0}).sort("roll_no", 1).to_list(MASTER_LIMIT)
        if r.get("status") != "cancelled"]
    by_item, by_mat_loose = defaultdict(list), defaultdict(list)
    for r in rolls:
        if r.get("source_receipt_item_id"):
            by_item[r["source_receipt_item_id"]].append(r)
        else:
            by_mat_loose[r.get("material_id")].append(r)
    names = await _category_names(db)

    mat_rows, roll_rows, unlinked, no_roll, skipped = {}, [], [], [], []
    used = set()
    for idx, it in enumerate(items):
        nama = it.get("material_name") or it.get("product_name") or ""
        accepted = _accepted(it)
        if (it.get("item_type") or "material") == "asset":
            skipped.append({"code": it.get("sku") or "", "name": nama,
                            "reason": "Barang aset — labelnya dicetak dari Aset Tetap."})
            continue
        mat = mats.get(it.get("material_id"))
        if not mat:
            unlinked.append({
                "label_kind": "material", "material_id": None, "code": it.get("sku") or "", "name": nama,
                "line_id": it.get("id") or f"baris-{idx}", "copies": 1, "master_linked": False,
                "reason": "Baris penerimaan ini tidak tertaut ke master bahan — tautkan barangnya ke master "
                          "dulu; label dengan kode yang tidak dikenal sistem tidak dicetak."})
            continue
        if fre.is_roll_material(mat):
            rs = [r for r in (by_item.get(it.get("id")) or by_mat_loose.get(mat["id"]) or [])
                  if r.get("id") not in used]
            if not rs:
                if accepted > 0:
                    no_roll.append({"material_code": mat.get("code") or "", "material_name": mat.get("name") or "",
                                    "accepted_qty": round(accepted, 3), "unit": it.get("unit") or mat.get("unit") or ""})
                continue
            for r in rs:
                used.add(r.get("id"))
                roll_rows.append(_roll_row(r))
            continue
        if accepted <= 0:
            skipped.append({"code": mat.get("code") or "", "name": mat.get("name") or nama,
                            "reason": "Seluruh qty ditolak QC — tidak ada barang yang masuk gudang."})
            continue
        if mat.get("type") == "fg":
            skipped.append({"code": mat.get("code") or "", "name": mat.get("name") or nama,
                            "reason": "Barang jadi — labelnya dicetak di jenis Barang jadi."})
            continue
        row = mat_rows.get(mat["id"])
        if row:
            row["qty_received"] += accepted
        else:
            mat_rows[mat["id"]] = {
                "label_kind": "material", "material_id": mat["id"], "code": mat.get("code") or mat.get("sku"),
                "name": mat.get("name") or nama, "unit": it.get("unit") or lr.unit_of(mat),
                "color": _color_label(mat), "size": "", "category": _category_label(mat, names),
                "qty_received": accepted, "master_linked": True}
    # Roll dari penerimaan ini yang barisnya sudah tidak ada di dokumen tetap ikut — gulungannya nyata.
    roll_rows += [_roll_row(r) for r in rolls if r.get("id") not in used]
    for row in mat_rows.values():
        row["qty_received"] = round(row["qty_received"], 3)
        row["copies"] = default_copies(row["qty_received"], row["unit"])
    rows = list(mat_rows.values()) + roll_rows + unlinked
    message = ""
    if no_roll:
        message = (f"{len(no_roll)} baris kain dari penerimaan ini belum punya roll, jadi label rollnya belum bisa "
                   "dicetak. Terbitkan rollnya dulu di Roll Kain › Penerimaan tanpa roll, lalu ambil lagi dari "
                   "penerimaan ini.")
    return serialize_doc({
        "receipt_id": receipt_id, "receipt_number": no, "supplier_name": gr.get("supplier_name") or "",
        "po_number": gr.get("po_number") or "", "received_at": gr.get("received_at") or gr.get("created_at"),
        "kind": "material", "rows": rows,
        "material_count": len(mat_rows), "roll_count": len(roll_rows), "unlinked_count": len(unlinked),
        "fabric_without_rolls": no_roll, "skipped": skipped, "message": message,
        "total_copies": sum(r["copies"] for r in rows if r.get("master_linked")),
    })


# ══════════════════════════════════════════════════════════════════════════════
# 3. Cetak batch (1 PDF gabungan) + riwayat
# ══════════════════════════════════════════════════════════════════════════════

class BarcodeRow(BaseModel):
    id: Optional[str] = None
    code: Optional[str] = None
    copies: int = 1


class BarcodeRollRow(BaseModel):
    """Satu roll kain (2026-11-10): barcode = nomor roll, dicari di `wh_fabric_rolls` — bukan ketikan bebas."""
    id: Optional[str] = None
    roll_no: Optional[str] = None
    copies: int = 1


class BarcodeBatchIn(BaseModel):
    kind: str = "material"
    rows: List[BarcodeRow] = []
    rolls: List[BarcodeRollRow] = []  # label roll kain (hanya jenis bahan) — 2026-11-10
    include_stock: bool = True
    source: str = "manual"           # manual | produksi | pembelian
    po_id: Optional[str] = None
    receipt_id: Optional[str] = None  # sumber "pembelian": penerimaan barang asal — 2026-11-10
    note: str = ""
    size: str = "standard"           # FG: standard (100×70) | hangtag (70×40) — 2026-11-02


@router.post("/batch-pdf")
async def barcode_batch_pdf(data: BarcodeBatchIn, request: Request):
    user = await require_auth(request)
    kind = _check_kind(data.kind)
    size = (data.size or "standard").lower() if kind == "fg" else "standard"
    if size not in FG_SIZES:
        raise HTTPException(400, f"Ukuran label harus salah satu dari {tuple(FG_SIZES)}")
    render_kind = FG_SIZES[size] if kind == "fg" else kind
    if not lr.LABELS_OK:
        raise HTTPException(500, "Pustaka pencetak label (reportlab/barcode) tidak tersedia")
    if not data.rows and not data.rolls:
        raise HTTPException(400, "Belum ada item yang dipilih untuk dicetak.")
    if data.rolls and kind != "material":
        raise HTTPException(400, "Label roll kain hanya bisa dicetak di jenis Bahan & aksesoris.")

    total = 0
    for r in [*data.rows, *data.rolls]:
        if r.copies < 1 or r.copies > MAX_COPIES_PER_ROW:
            raise HTTPException(400, f"Jumlah label per item harus 1–{MAX_COPIES_PER_ROW}.")
        total += r.copies
    if total > MAX_LABELS:
        raise HTTPException(400, f"Total {total} label melebihi batas {MAX_LABELS} lembar "
                                 f"per cetak. Pecah menjadi beberapa kali cetak.")

    db = get_db()
    ids = [r.id for r in data.rows if r.id]
    codes = [r.code for r in data.rows if r.code]
    found = await db.rahaza_materials.find(
        {"$or": [{"id": {"$in": ids}}, {"code": {"$in": codes}}, {"sku": {"$in": codes}}]},
        {"_id": 0}).to_list(MASTER_LIMIT) if (ids or codes) else []
    by_id = {m["id"]: m for m in found if m.get("id")}
    by_code = {}
    for m in found:
        for key in (m.get("code"), m.get("sku")):
            if key:
                by_code.setdefault(key, m)
    names = await _category_names(db) if kind == "material" else {}

    docs, missing, wrong_kind = [], [], []
    resolved_rows = []
    render_of = {}   # satu dokumen gambar per material (stok ditempel sekali)
    for r in data.rows:
        mat = by_id.get(r.id) if r.id else None
        if not mat and r.code:
            mat = by_code.get(r.code)
        if not mat:
            missing.append(r.code or r.id or "?")
            continue
        is_fg = mat.get("type") == "fg"
        if (kind == "fg") != is_fg:
            wrong_kind.append(mat.get("code"))
            continue
        if kind == "material":
            # 2026-11-10: baris "KATEGORI · satuan" di label = nama kategori master (dulu `category` mentah →
            # id kategori/UUID tercetak di label bahan yang kategorinya tersimpan sebagai id).
            key = mat.get("id") or mat.get("code")
            if key not in render_of:
                render_of[key] = {**mat, "category": _category_label(mat, names)
                                  or TYPE_LABEL.get(str(mat.get("type") or "").lower(), "Bahan")}
            mat = render_of[key]
        docs.extend([mat] * r.copies)
        resolved_rows.append({"material_id": mat.get("id"), "code": mat.get("code"),
                              "name": mat.get("name"), "copies": r.copies})
    if missing:
        raise HTTPException(400, "Kode berikut tidak ada di master, jadi labelnya tidak "
                                 "dicetak (barcode harus bisa discan menjadi item yang "
                                 f"benar-benar ada): {', '.join(map(str, missing[:10]))}")
    if wrong_kind:
        raise HTTPException(400, f"Item {', '.join(map(str, wrong_kind[:10]))} bukan jenis "
                                 f"'{kind}'. Pindah ke tab yang sesuai.")

    # Roll kain: dicari di `wh_fabric_rolls` (id atau nomor roll). Yang tidak ada / dibatalkan → ditolak.
    roll_docs, resolved_rolls = [], []
    if data.rolls:
        rids = [r.id for r in data.rolls if r.id]
        rnos = [r.roll_no for r in data.rolls if r.roll_no]
        found_rolls = await db.wh_fabric_rolls.find(
            {"$or": [{"id": {"$in": rids}}, {"roll_no": {"$in": rnos}}]}, {"_id": 0}).to_list(MASTER_LIMIT)
        rby_id = {x["id"]: x for x in found_rolls if x.get("id")}
        rby_no = {x["roll_no"]: x for x in found_rolls if x.get("roll_no")}
        rmissing, rcancel = [], []
        for r in data.rolls:
            roll = (rby_id.get(r.id) if r.id else None) or (rby_no.get(r.roll_no) if r.roll_no else None)
            if not roll:
                rmissing.append(r.roll_no or r.id or "?")
                continue
            if roll.get("status") == "cancelled":
                rcancel.append(roll.get("roll_no") or "?")
                continue
            roll_docs.extend([roll_label_doc(roll)] * r.copies)
            resolved_rolls.append({"roll_id": roll.get("id"), "roll_no": roll.get("roll_no"),
                                   "material_code": roll.get("material_code") or "",
                                   "name": roll.get("material_name") or "", "copies": r.copies})
        if rmissing:
            raise HTTPException(400, "Roll berikut tidak ditemukan di daftar Roll Kain, jadi labelnya tidak "
                                     f"dicetak: {', '.join(map(str, rmissing[:10]))}")
        if rcancel:
            raise HTTPException(400, f"Roll {', '.join(map(str, rcancel[:10]))} sudah dibatalkan — labelnya "
                                     "tidak dicetak.")

    if kind == "material" and data.include_stock and docs:
        await lr.attach_stock_info(db, list({m["id"]: m for m in docs}.values()))

    n_labels = len(docs) + len(roll_docs)
    try:
        if roll_docs:
            pdf = lr.grid_labels_pdf_mixed(
                [("material", d) for d in docs] + [("roll", d) for d in roll_docs],
                include_stock=data.include_stock, title=f"Barcode bahan & roll ({n_labels} label)")
        else:
            pdf = lr.grid_labels_pdf(render_kind, docs, include_stock=data.include_stock,
                                     title=f"Barcode {kind} ({len(docs)} label)")
    except lr.LabelCodeError as e:
        raise HTTPException(400, str(e))

    source = data.source if data.source in SOURCES else "manual"
    receipt_number = ""
    if data.receipt_id:
        gr = await db.warehouse_receiving.find_one({"id": data.receipt_id}, {"_id": 0, "receipt_number": 1})
        receipt_number = (gr or {}).get("receipt_number") or ""
    job = {
        "id": uuid.uuid4().hex,
        "job_number": await gen_prefixed_number(
            db, "wh_barcode_print_jobs", "job_number",
            f"BC-{fmt_wib('%Y%m%d')}-", 3),
        "kind": kind, "source": source,
        "po_id": data.po_id, "receipt_id": data.receipt_id, "receipt_number": receipt_number,
        "note": (data.note or "")[:500],
        "rows": resolved_rows, "rolls": resolved_rolls,
        "item_count": len(resolved_rows) + len(resolved_rolls), "total_labels": n_labels,
        "roll_labels": len(roll_docs),
        "include_stock": bool(data.include_stock), "size": size,
        "created_at": _now(), "created_by": user.get("id"),
        "created_by_name": user.get("name") or user.get("email") or "",
    }
    await db.wh_barcode_print_jobs.insert_one(dict(job))
    await log_activity(user.get("id"), user.get("name", ""), "print",
                       "wms.barcode", job["job_number"])

    fname = f"barcode-{kind}-{job['job_number']}.pdf"
    return StreamingResponse(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{fname}"',
        "X-Barcode-Job": job["job_number"], "X-Barcode-Labels": str(n_labels),
    })


@router.get("/history")
async def barcode_history(request: Request, limit: int = Query(30, ge=1, le=200),
                          kind: str = Query("")):
    await require_auth(request)
    db = get_db()
    flt = {}
    if kind:
        flt["kind"] = _check_kind(kind)
    rows = await db.wh_barcode_print_jobs.find(flt, {"_id": 0}).sort(
        "created_at", -1).limit(limit).to_list(limit)
    return serialize_doc(rows)
