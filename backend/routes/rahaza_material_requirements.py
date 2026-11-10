"""
PT Rahaza — Master Product Fase 5: Laporan Kebutuhan Material (MRP-lite).

Agregasi kebutuhan material lintas banyak baris produksi (model × size × qty).
Berbeda dari `POST /api/rahaza/boms/{id}/requirements` (single BOM, single size),
endpoint ini menjumlahkan kebutuhan dari BANYAK item — cocok untuk perencanaan
pembelian (procurement) untuk satu PO produksi internal atau sekumpulan order.

Endpoint (prefix /api/rahaza):
  POST /material-requirements
    Body (salah satu sumber):
      A. { "lines": [ {model_id, size_id, qty_pcs}, ... ] }        # builder manual
      B. { "po_id": "<production_pos.id>" }                         # dari PO internal
    Opsi:
      rounding: "none" | "ceil" | "floor"   (default none) — dibulatkan pada TOTAL agregat
      include_stock: bool (default True)     — sertakan on-hand & kekurangan dari rahaza_material_stock

    Response:
      {
        source: "lines" | "po",
        po: { id, po_number, business_type } | null,
        lines_resolved: [ {model_id, model_code, size_id, size_code, qty_pcs, bom_id, version, material_count} ],
        lines_without_bom: [ {model_id, model_code, size_id, size_code, qty_pcs, reason} ],
        aggregated: [ {material_id, code, name, category, category_name, material_type, is_kglike,
                       unit, total_required, issued, remaining_required, onhand, reserved,
                       available, shortfall} ],
        (Tahap 2: `issued`/`remaining_required` hanya untuk sumber PO; `shortfall` = sisa − tersedia)
        totals: { grand_qty_pcs, total_material_lines, total_yarn_kg, total_shortfall_lines },
        warnings: [str]
      }

SSOT: BOM materials via routes.rahaza_bom.get_bom_materials (skema materials[] terunifikasi).
Stok fisik via core.stock_schema (read_qty/read_reserved) atas rahaza_material_stock.

Tahap 9 (7 Nov 2026) — menu "Bahan › Kebutuhan" di Portal Produksi DAN Maklon:
  GET /material-requirements/po/{po_id}   → `po_material_need()` — SATU hitungan per PO:
    · PO internal → BOM × qty lewat `core.material_issue_engine.bom_need_for_lines`, hitungan yang SAMA
      dengan kiriman ke CMT (yang mengurangi stok). Dulu layar ini menghitung BOM × qty sendiri.
    · PO maklon  → rencana bahan & aksesoris PO (`po_accessories`) lewat
      `core.accessory_procurement.po_requirements`, sama dengan layar PO.
  POST /material-requirements dengan `po_id` kini memakai fungsi yang sama (bentuk jawaban lama tetap).
  Sumber `lines` (model × ukuran tanpa PO) tetap untuk pemanggil lama; layar tidak memakainya lagi.
"""
from __future__ import annotations

import math
from fastapi import APIRouter, Request, HTTPException

from database import get_db
from auth import require_auth, serialize_doc
from routes.rahaza_bom import _is_kglike
from core import bom_uom  # 2026-08-02: konversi satuan baris BOM → satuan dasar
from core.stock_schema import read_qty, read_reserved
from core import material_fields  # FASE 6.6-B: SSOT nama field + alias legacy yarn_*

router = APIRouter(prefix="/api/rahaza", tags=["rahaza-material-requirements"])


def _round(v: float, kglike: bool, mode: str) -> float:
    if mode == "ceil":
        return math.ceil(v * 1000) / 1000 if kglike else float(math.ceil(v))
    if mode == "floor":
        return math.floor(v * 1000) / 1000 if kglike else float(math.floor(v))
    return round(v, 4)


async def _find_active_bom(db, model_id: str, size_id: str, color: str | None = None):
    """Cari BOM aktif utk (model_id, size_id[, warna]). Prioritas is_active True; fallback versi tertinggi.

    2026-11-02 (butir 10, F1b): bila warna varian diketahui, BOM warna itu yang dipakai lewat
    SATU penyelesai `core.product_costing.find_active_bom` (dulu MRP selalu memakai BOM warna
    lain — PO CRL 10 pcs dihitung 1 baris potongan BRG Rp 321.750, MI nyata 5 baris).
    """
    if not model_id or not size_id:
        return None
    if (color or "").strip():
        from core import product_costing as pc
        bom = await pc.find_active_bom(db, model_id, size_id, color)
        if bom:
            return bom
    bom = await db.rahaza_boms.find_one(
        {"model_id": model_id, "size_id": size_id, "active": True, "is_active": True}, {"_id": 0})
    if bom:
        return bom
    # fallback: BOM aktif apa pun utk kombinasi ini (versi tertinggi)
    cands = await db.rahaza_boms.find(
        {"model_id": model_id, "size_id": size_id, "active": True}, {"_id": 0}
    ).sort("version", -1).to_list(50)
    return cands[0] if cands else None


async def _stock_for_material(db, material_id: str):
    """Total on-hand / reserved / available utk sebuah material lintas lokasi."""
    if not material_id:
        return 0.0, 0.0, 0.0
    rows = await db.rahaza_material_stock.find({"material_id": material_id}, {"_id": 0}).to_list(2000)
    onhand = sum(read_qty(s) for s in rows)
    reserved = sum(read_reserved(s) for s in rows)
    available = max(0.0, onhand - reserved)
    return round(onhand, 4), round(reserved, 4), round(available, 4)


async def issued_for_po(db, po_id: str) -> dict:
    """{material_id: qty} yang SUDAH keluar untuk PO ini (2026-11-06, Tahap 2).

    = Σ Pengeluaran Material berstatus `issued` milik PO (qty keluar − retur baik), + kain yang
    terpakai order Cutting yang ditautkan ke baris PO ini. Satuan = satuan dasar material
    (sama dengan kebutuhan BOM setelah `bom_uom.ensure_uom`)."""
    out: dict = {}
    if not po_id:
        return out
    async for mi in db.rahaza_material_issues.find(
            {"$or": [{"production_po_id": po_id}, {"po_id": po_id}], "status": "issued"},
            {"_id": 0, "items": 1}):
        for it in mi.get("items") or []:
            mid = it.get("material_id")
            if not mid:
                continue
            net = float(it.get("qty_issued") or 0) - float(it.get("qty_returned") or 0)
            out[mid] = out.get(mid, 0.0) + net
    from core.cutting_material_issue import ORDERS as _CUT_ORDERS  # 2026-11-06 (pola P2): koleksi dibaca lewat konstanta penulisnya (satu nama, tidak ada koleksi hantu)
    # 2026-11-10: order cutting banyak kain × banyak hasil — kain dibagi menurut pcs hasil yang tertaut PO ini
    # (`core.cutting_lines.fabric_used_for_po`; order satu baris = seluruh kainnya, sama seperti dulu).
    from core.cutting_lines import fabric_used_for_po
    async for co in db[_CUT_ORDERS].find(
            {"$or": [{"po_id": po_id}, {"outputs.po_id": po_id}], "status": {"$ne": "cancelled"}},
            {"_id": 0}):
        for mid, q in fabric_used_for_po(co, po_id).items():
            out[mid] = out.get(mid, 0.0) + float(q or 0)
    return {k: round(max(0.0, v), 4) for k, v in out.items()}


async def _get_costing_settings(db):
    s = await db.rahaza_costing_settings.find_one({"id": "GLOBAL"}, {"_id": 0}) or {}
    return {
        # FASE 6.6-B: baca kanonik `default_material_cost_per_kg` dulu, fallback legacy
        "default_yarn": float(material_fields.read_field(s, "default_material_cost_per_kg", 0) or 0),
        "default_acc": float(s.get("default_accessory_cost_per_unit") or 0),
    }


async def _resolve_unit_cost(db, rec: dict, settings: dict):
    """Resolusi harga satuan material (mirror logika HPP):
      1. dari master rahaza_materials (by material_id, lalu by code) → `unit_cost`
      2. fallback costing-settings: default_yarn_cost_per_kg (kain/benang) / default_accessory_cost_per_unit
    Return (unit_cost: float, source: 'material'|'default'|'none').
    """
    mat = None
    if rec.get("material_id"):
        mat = await db.rahaza_materials.find_one({"id": rec["material_id"]}, {"_id": 0, "unit_cost": 1})
    if not mat and rec.get("code"):
        mat = await db.rahaza_materials.find_one({"code": rec["code"]}, {"_id": 0, "unit_cost": 1})
    unit_cost = float((mat or {}).get("unit_cost") or 0)
    if unit_cost > 0:
        return round(unit_cost, 2), "material"
    fallback = settings["default_yarn"] if rec.get("is_kglike") else settings["default_acc"]
    if fallback > 0:
        return round(float(fallback), 2), "default"
    return 0.0, "none"


# ─── Tahap 9: kebutuhan bahan satu PO (tab Bahan › Kebutuhan, dua portal) ────────────────────
# Label jenis baris. `kind` boleh dikirim `bom_need_for_lines` (pemisahan kain potongan dari aksesoris);
# bila belum ada: master potongan (SSOT `core.cut_panel_master.is_panel_material`) = kain potongan, lalu
# `type` lama (yarn = kain/benang, lainnya aksesoris).
KIND_LABELS = {
    "potongan": "Kain potongan", "cut_piece": "Kain potongan", "cut": "Kain potongan",
    "panel": "Kain potongan", "kain_potongan": "Kain potongan",
    "aksesoris": "Aksesoris", "accessory": "Aksesoris",
    "yarn": "Kain / benang", "fabric": "Kain / benang", "bahan": "Kain / benang", "kain": "Kain / benang",
}
_KG_KINDS = ("yarn", "fabric", "bahan", "kain")
_CUT_KINDS = ("potongan", "cut_piece", "cut", "panel", "kain_potongan")
SOURCE_LABELS = {"bom": "BOM produk × qty PO", "rencana_po": "Rencana bahan & aksesoris PO"}


def _kind_of(entry: dict, master: dict | None = None) -> str:
    k = str(entry.get("kind") or "").strip().lower()
    if k:
        return k
    from core.cut_panel_master import is_panel_material
    if is_panel_material(master) or is_panel_material({"code": entry.get("code")}):
        return "potongan"
    return "yarn" if entry.get("type") == "yarn" else "aksesoris"


async def _masters_by_code(db, codes: list) -> dict:
    if not codes:
        return {}
    out = {}
    async for m in db.rahaza_materials.find(
            {"code": {"$in": codes}},
            {"_id": 0, "id": 1, "code": 1, "name": 1, "unit": 1, "unit_cost": 1, "hpp": 1, "is_cut_panel": 1}):
        out[(m.get("code") or "").strip().upper()] = m
    return out


async def po_material_need(db, po: dict, *, include_stock: bool = True) -> dict:
    """Kebutuhan bahan SATU PO — satu sumber angka untuk tab Bahan › Kebutuhan (kedua portal).

    Baris: kode, nama, jenis, satuan, dibutuhkan, sudah keluar untuk PO ini, sisa, tersedia di gudang,
    kurang (= sisa − tersedia), perkiraan nilai. Tidak menulis apa pun."""
    from core.entities import po_business_type
    po_id = po.get("id")
    bt = po_business_type(po)
    items = await db.po_items.find({"po_id": po_id}, {"_id": 0}).to_list(5000)
    total_pcs = sum(float(it.get("qty") or 0) for it in items)
    rows: list = []
    notes: list = []

    if bt == "internal":
        from core import material_issue_engine as mie
        need, bom_notes, _pcs = await mie.bom_need_for_lines(
            db, [{"po_item_id": it.get("id"), "qty": it.get("qty")} for it in items if it.get("id")])
        notes = list(bom_notes or [])
        masters = await _masters_by_code(db, sorted(need))
        issued_map = await issued_for_po(db, po_id)
        for code, e in need.items():
            m = masters.get(code) or {}
            mid = e.get("material_id") or m.get("id")
            req = round(float(e.get("qty") or 0), 4)
            issued = round(float(issued_map.get(mid, 0.0)), 4) if mid else 0.0
            remaining = round(max(0.0, req - issued), 4)
            available = None
            if include_stock and mid:
                _on, _res, available = await _stock_for_material(db, mid)
            shortage = round(max(0.0, remaining - available), 4) if available is not None else None
            unit_cost = float(m.get("unit_cost") or m.get("hpp") or 0)
            kind = _kind_of({**e, "code": code}, m)
            rows.append({
                "material_id": mid, "code": code, "name": e.get("name") or m.get("name") or code,
                "kind": kind, "kind_label": KIND_LABELS.get(kind, "Bahan"),
                "unit": e.get("unit") or m.get("unit") or "",
                "qty_required": req, "issued": issued, "remaining": remaining,
                "available": available, "shortage": shortage,
                "status": "unlinked" if not mid else ("shortage" if shortage else "ok"),
                "unit_cost": unit_cost, "value_estimate": round(req * unit_cost, 2),
            })
        source = "bom"
    else:
        from core.accessory_procurement import po_requirements
        res = await po_requirements(db, po)
        for r in res.get("rows") or []:
            da_owned = bool(r.get("da_owned"))
            unit_cost = float(r.get("unit_cost") or 0)
            req = round(float(r.get("qty_needed") or 0), 4)
            rows.append({
                "material_id": r.get("material_id"), "code": r.get("material_code") or "",
                "name": r.get("material_name") or "", "kind": "aksesoris",
                "kind_label": "Aksesoris" if da_owned else "Disediakan klien",
                "unit": r.get("unit") or "",
                "qty_required": req, "issued": round(float(r.get("issued") or 0), 4),
                "remaining": round(float(r.get("remaining") or 0), 4),
                "available": round(float(r.get("available") or 0), 4) if da_owned else None,
                "shortage": round(float(r.get("shortage") or 0), 4) if da_owned else None,
                "status": r.get("status") or "ok",
                "unit_cost": unit_cost, "value_estimate": round(req * unit_cost, 2) if da_owned else 0.0,
            })
        if not rows:
            notes.append("PO ini belum punya rencana bahan & aksesoris. Isi di form PO (bagian aksesoris).")
        source = "rencana_po"

    def _rank(r):
        k = r["kind"]
        return 0 if k in _CUT_KINDS else (1 if k in _KG_KINDS else 2)
    rows.sort(key=lambda r: (_rank(r), (r.get("name") or "").lower()))
    return {
        "po": {"id": po_id, "po_number": po.get("po_number") or "", "business_type": bt,
               "customer_name": po.get("customer_name") or "", "status": po.get("status") or "",
               "total_qty": total_pcs},
        "source": source, "source_label": SOURCE_LABELS[source],
        "rows": rows, "notes": notes,
        "totals": {
            "lines": len(rows),
            "shortage_lines": sum(1 for r in rows if r["status"] == "shortage"),
            "unlinked_lines": sum(1 for r in rows if r["status"] == "unlinked"),
            "client_lines": sum(1 for r in rows if r["status"] == "client"),
            "total_pcs": total_pcs,
            "value_estimate": round(sum(r["value_estimate"] for r in rows), 2),
        },
    }


@router.get("/material-requirements/po/{po_id}")
async def material_need_for_po(po_id: str, request: Request):
    """Tab Bahan › Kebutuhan (Tahap 9): kebutuhan bahan satu PO, PO internal maupun maklon."""
    await require_auth(request)
    db = get_db()
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO tidak ditemukan")
    return serialize_doc(await po_material_need(db, po))


def _legacy_rows_from_need(out: dict, rounding: str, include_stock: bool, include_cost: bool) -> tuple:
    """Bentuk jawaban lama POST /material-requirements (sumber PO) dari `po_material_need`."""
    aggregated, total_kg, short_lines, grand = [], 0.0, 0, 0.0
    for r in out["rows"]:
        kglike = r["kind"] in _KG_KINDS
        req = _round(r["qty_required"], kglike, rounding)
        avail = r.get("available") if include_stock else None
        shortfall = round(max(0.0, r["remaining"] - avail), 4) if avail is not None else None
        if shortfall:
            short_lines += 1
        sub = round(req * r["unit_cost"], 2) if include_cost else None
        grand += sub or 0.0
        if kglike:
            total_kg += req
        aggregated.append({
            "material_id": r.get("material_id"), "code": r.get("code"), "name": r.get("name"),
            "category": None, "category_name": r.get("kind_label"), "material_type": r.get("kind"),
            "is_kglike": kglike, "unit": r.get("unit"), "total_required": req,
            "issued": r.get("issued"), "remaining_required": r.get("remaining"),
            "onhand": None, "reserved": None, "available": avail, "shortfall": shortfall,
            "unit_cost": r["unit_cost"] if include_cost else None, "subtotal_cost": sub,
            "cost_source": ("material" if r["unit_cost"] > 0 else "none") if include_cost else None,
        })
    return aggregated, total_kg, short_lines, grand


@router.post("/material-requirements")
async def aggregate_material_requirements(request: Request):
    await require_auth(request)
    db = get_db()
    body = await request.json()

    rounding = body.get("rounding", "none")
    if rounding not in ("none", "ceil", "floor"):
        rounding = "none"
    include_stock = bool(body.get("include_stock", True))
    include_cost = bool(body.get("include_cost", True))


    warnings: list[str] = []
    source = "lines"
    po_meta = None

    # ── Build the list of production lines: {model_id, size_id, qty_pcs} ──
    raw_lines: list[dict] = []

    po_id = body.get("po_id")
    if po_id:
        # Tahap 9: sumber PO memakai SATU hitungan (`po_material_need`) — bentuk jawaban lama tetap.
        po = await db.production_pos.find_one({"id": po_id}, {"_id": 0})
        if not po:
            raise HTTPException(404, "PO tidak ditemukan")
        out = await po_material_need(db, po, include_stock=include_stock)
        aggregated, total_kg, short_lines, grand = _legacy_rows_from_need(
            out, rounding, include_stock, include_cost)
        warnings = list(out["notes"])
        if not out["po"]["total_qty"]:
            warnings.append("PO tidak memiliki item.")
        return serialize_doc({
            "source": "po", "po": {"id": po.get("id"), "po_number": po.get("po_number"),
                                   "business_type": po.get("business_type")},
            "rounding": rounding, "include_stock": include_stock, "include_cost": include_cost,
            "lines_resolved": [], "lines_without_bom": [], "aggregated": aggregated, "uom_notices": [],
            "totals": {
                "grand_qty_pcs": round(out["po"]["total_qty"], 4),
                "total_material_lines": len(aggregated),
                **material_fields.mirror("total_material_kg", round(total_kg, 4)),
                "total_shortfall_lines": short_lines,
                "grand_total_cost": round(grand, 2),
                "lines_resolved_count": 0, "lines_without_bom_count": 0,
            },
            "warnings": warnings,
        })
    else:
        lines_in = body.get("lines") or []
        if not isinstance(lines_in, list) or not lines_in:
            raise HTTPException(400, "Sertakan `lines` (daftar {model_id,size_id,qty_pcs}) atau `po_id`.")
        for ln in lines_in:
            raw_lines.append({
                "model_id": ln.get("model_id"),
                "size_id": ln.get("size_id"),
                "color": ln.get("color_code") or ln.get("color") or "",
                "qty_pcs": float(ln.get("qty_pcs") or 0),
                "_label": "",
            })

    # ── Explode each line via its BOM and aggregate ──
    agg: dict = {}          # key -> aggregate record (raw sums)
    lines_resolved = []
    lines_without_bom = []
    uom_notices = []   # peringatan satuan yang perlu dibereskan di master/BOM
    grand_qty_pcs = 0.0

    for ln in raw_lines:
        model_id = ln.get("model_id")
        size_id = ln.get("size_id")
        qty_pcs = float(ln.get("qty_pcs") or 0)
        grand_qty_pcs += qty_pcs

        # resolve model/size codes (for display) — best effort
        model = await db.rahaza_models.find_one({"id": model_id}, {"_id": 0, "code": 1, "name": 1}) if model_id else None
        size = await db.rahaza_sizes.find_one({"id": size_id}, {"_id": 0, "code": 1}) if size_id else None
        model_code = (model or {}).get("code")
        size_code = (size or {}).get("code")

        if qty_pcs <= 0:
            lines_without_bom.append({
                "model_id": model_id, "model_code": model_code, "size_id": size_id,
                "size_code": size_code, "qty_pcs": qty_pcs, "reason": "qty 0",
            })
            continue

        bom = await _find_active_bom(db, model_id, size_id, ln.get("color"))
        if not bom:
            lines_without_bom.append({
                "model_id": model_id, "model_code": model_code, "size_id": size_id,
                "size_code": size_code, "qty_pcs": qty_pcs,
                "reason": "BOM aktif tidak ditemukan utk model+size ini",
                "label": ln.get("_label", ""),
            })
            continue

        # 2026-08-02 · SATUAN: qty BOM diubah ke SATUAN DASAR dulu (INV-UOM-2:
        # stok & harga selalu satuan dasar). Tanpa ini, baris BOM "250 gram"
        # dibandingkan dengan stok "kg" dan biaya dihitung 500× lipat.
        mats, uom_warnings = await bom_uom.ensure_uom(db, bom)
        for w in uom_warnings:
            if w not in uom_notices:
                uom_notices.append(w)
        lines_resolved.append({
            "model_id": model_id, "model_code": bom.get("model_code") or model_code,
            "size_id": size_id, "size_code": bom.get("size_code") or size_code,
            "qty_pcs": qty_pcs, "bom_id": bom.get("id"), "version": bom.get("version"),
            "material_count": len(mats),
            "label": ln.get("_label", ""),
        })

        for m in mats:
            key = m.get("material_id") or (m.get("code") or "").strip().upper() or (m.get("name") or "").strip().lower()
            if not key:
                continue
            qty_total = bom_uom.qty_base_of(m) * qty_pcs
            rec = agg.get(key)
            if not rec:
                rec = {
                    "material_id": m.get("material_id"),
                    "code": m.get("code"),
                    "name": m.get("name"),
                    "category": m.get("category"),
                    "category_name": m.get("category_name"),
                    "material_type": m.get("material_type"),
                    "unit": bom_uom.base_unit_of(m),
                    "unit_input": m.get("unit"),
                    "uom_status": m.get("uom_status"),
                    "is_kglike": _is_kglike({**m, "unit": bom_uom.base_unit_of(m)}),
                    "_raw_total": 0.0,
                }
                agg[key] = rec
            rec["_raw_total"] += qty_total

    # ── Finalize aggregate: rounding + stock/shortfall ──
    aggregated = []
    total_yarn_kg = 0.0
    total_shortfall_lines = 0
    grand_total_cost = 0.0
    settings = await _get_costing_settings(db) if include_cost else None
    # 2026-11-06 (Tahap 2): laporan per PO mengurangi yang SUDAH dikeluarkan untuk PO itu —
    # kekurangan dihitung dari sisa kebutuhan, bukan kebutuhan penuh (dulu material yang sudah
    # keluar tetap tampil "kurang" dan memicu belanja ulang).
    issued_map = await issued_for_po(db, po_id) if source == "po" else {}
    for rec in agg.values():
        kglike = rec["is_kglike"]
        total_required = _round(rec["_raw_total"], kglike, rounding)
        issued = round(issued_map.get(rec.get("material_id"), 0.0), 4) if source == "po" else None
        remaining_required = (round(max(0.0, total_required - issued), 4)
                              if issued is not None else total_required)
        onhand = reserved = available = None
        shortfall = None
        if include_stock and rec.get("material_id"):
            onhand, reserved, available = await _stock_for_material(db, rec["material_id"])
            shortfall = round(max(0.0, remaining_required - available), 4)
            if shortfall > 0:
                total_shortfall_lines += 1
        unit_cost = subtotal_cost = None
        cost_source = None
        if include_cost:
            unit_cost, cost_source = await _resolve_unit_cost(db, rec, settings)
            subtotal_cost = round(total_required * unit_cost, 2)
            grand_total_cost += subtotal_cost
        aggregated.append({
            "material_id": rec["material_id"],
            "code": rec["code"],
            "name": rec["name"],
            "category": rec["category"],
            "category_name": rec["category_name"],
            "material_type": rec["material_type"],
            "is_kglike": kglike,
            "unit": rec["unit"],
            "total_required": total_required,
            "issued": issued,
            "remaining_required": remaining_required,
            "onhand": onhand,
            "reserved": reserved,
            "available": available,
            "shortfall": shortfall,
            "unit_cost": unit_cost,
            "subtotal_cost": subtotal_cost,
            "cost_source": cost_source,
        })
        if kglike:
            total_yarn_kg += total_required

    # sort: kg-like (kain/benang) dulu, lalu nama
    aggregated.sort(key=lambda r: (0 if r["is_kglike"] else 1, (r.get("name") or "").lower()))

    if source == "po" and po_meta and po_meta.get("business_type") == "maklon":
        warnings.append("PO Maklon: item maklon umumnya tanpa BOM internal (produksi oleh vendor CMT), "
                        "sehingga baris tanpa BOM adalah normal.")
    if uom_notices:
        warnings.append("Satuan pada BOM perlu dibereskan: " + " | ".join(uom_notices[:5]))
    if include_cost and any(r.get("cost_source") == "default" for r in aggregated):
        warnings.append("Sebagian harga satuan memakai default costing-settings "
                        "(material belum punya unit_cost) — estimasi biaya bersifat kasar.")

    return serialize_doc({
        "source": source,
        "po": po_meta,
        "rounding": rounding,
        "include_stock": include_stock,
        "include_cost": include_cost,
        "lines_resolved": lines_resolved,
        "lines_without_bom": lines_without_bom,
        "aggregated": aggregated,
        "uom_notices": uom_notices,
        "totals": {
            "grand_qty_pcs": round(grand_qty_pcs, 4),
            "total_material_lines": len(aggregated),
            # FASE 6.6-B: kanonik `total_material_kg` + alias legacy `total_yarn_kg`
            **material_fields.mirror("total_material_kg", round(total_yarn_kg, 4)),
            "total_shortfall_lines": total_shortfall_lines,
            "grand_total_cost": round(grand_total_cost, 2),
            "lines_resolved_count": len(lines_resolved),
            "lines_without_bom_count": len(lines_without_bom),
        },
        "warnings": warnings,
    })
