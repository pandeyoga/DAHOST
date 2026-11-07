"""
services/cmt_belanja.py — READ-ONLY agregasi "BELANJA" (Fase 4):
- S5 REKAP AKSESORIS: kebutuhan aksesoris per PO maklon = po_accessories (eksplisit)
  + turunan BOM (dewi_maklon_bom_templates.qty_per_pcs × po_items.qty).
- M3 KAPASITAS CMT: beban (outstanding di CMT) vs kapasitas (vendor_partners.capacity_pcs).

Kontrak SSOT (INVARIANTS MCS-01/05): TIDAK membuat koleksi/field truth baru.
Semua = agregasi read-only di atas: production_pos/po_items · po_accessories ·
dewi_maklon_bom_templates · vendor_partners · (beban) rantai vendor_shipments/cmt_receipts via services.cmt_kejar.
"""
from typing import Dict, List, Any, Optional

# Kategori/nama material yang dianggap AKSESORIS bila muncul di BOM (case-insensitive contains).
ACC_HINTS = ("aksesoris", "accessor", "acc", "zipper", "resleting", "kancing",
             "button", "label", "benang", "thread", "elastic", "karet", "hangtag",
             "tali", "webbing", "kepala", "puller", "snap")


def _int(v) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return 0


def _f(v) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _norm(s: Any) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _is_accessory(category: str, name: str) -> bool:
    blob = f"{_norm(category)} {_norm(name)}"
    return any(h in blob for h in ACC_HINTS)


async def _maklon_pos(db, po_id: Optional[str], only_open: bool,
                      business_type: Optional[str] = "maklon") -> List[Dict[str, Any]]:
    # Tahap 9: maklon = bukan internal (aturan portal yang dipakai di mana-mana); 'internal' juga bisa
    from core.pantau_produksi import bt_filter
    q: Dict[str, Any] = dict(bt_filter(business_type))
    if po_id:
        q["id"] = po_id
    elif only_open:
        q["status"] = {"$nin": ["Closed", "Cancelled", "Selesai", "closed", "cancelled"]}
    return await db.production_pos.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


# ─── S5 REKAP AKSESORIS ───────────────────────────────────────────────────────
async def rekap_aksesoris(db, po_id: Optional[str] = None, only_open: bool = True,
                          business_type: Optional[str] = "maklon") -> Dict[str, Any]:
    pos = await _maklon_pos(db, po_id, only_open, business_type)
    po_ids = [p["id"] for p in pos]
    po_by_id = {p["id"]: p for p in pos}

    # 1) Aksesoris eksplisit dari po_accessories
    acc_rows: List[Dict[str, Any]] = []
    if po_ids:
        acc_rows = await db.po_accessories.find(
            {"po_id": {"$in": po_ids}}, {"_id": 0}
        ).to_list(3000)

    # 2) po_items (untuk turunan BOM) + active BOM per catalog
    items: List[Dict[str, Any]] = []
    if po_ids:
        items = await db.po_items.find(
            {"po_id": {"$in": po_ids}},
            {"_id": 0, "po_id": 1, "po_number": 1, "catalog_item_id": 1, "qty": 1, "product_name": 1},
        ).to_list(5000)
    catalog_ids = list({it.get("catalog_item_id") for it in items if it.get("catalog_item_id")})
    bom_by_catalog: Dict[str, Dict[str, Any]] = {}
    if catalog_ids:
        boms = await db.dewi_maklon_bom_templates.find(
            {"buyer_catalog_id": {"$in": catalog_ids}, "is_active": True}, {"_id": 0}
        ).to_list(1000)
        for b in boms:
            bom_by_catalog[b["buyer_catalog_id"]] = b

    # Akumulator gabungan (accessory needs) keyed by normalized name
    acc_agg: Dict[str, Dict[str, Any]] = {}
    bom_mat_agg: Dict[str, Dict[str, Any]] = {}
    by_po: Dict[str, Dict[str, Any]] = {}

    def _po_bucket(pid: str) -> Dict[str, Any]:
        if pid not in by_po:
            p = po_by_id.get(pid, {})
            by_po[pid] = {
                "po_id": pid, "po_number": p.get("po_number", ""),
                "customer_name": p.get("customer_name", ""),
                "po_date": p.get("po_date"),
                "accessory_qty": 0.0, "item_qty": 0, "sources": {"po_accessory": 0.0, "bom": 0.0},
            }
        return by_po[pid]

    def _add_acc(name, code, unit, qty, source, pid):
        key = _norm(name) or _norm(code)
        if not key:
            return
        rec = acc_agg.setdefault(key, {
            "name": name or code, "code": code or "", "unit": unit or "pcs",
            "total_qty": 0.0, "sources": {"po_accessory": 0.0, "bom": 0.0}, "by_po": {},
        })
        rec["total_qty"] += qty
        rec["sources"][source] = rec["sources"].get(source, 0.0) + qty
        if not rec["code"] and code:
            rec["code"] = code
        pu = rec["by_po"].setdefault(pid, {
            "po_id": pid, "po_number": po_by_id.get(pid, {}).get("po_number", ""),
            "qty": 0.0, "sources": {"po_accessory": 0.0, "bom": 0.0},
        })
        pu["qty"] += qty
        pu["sources"][source] = pu["sources"].get(source, 0.0) + qty
        b = _po_bucket(pid)
        b["accessory_qty"] += qty
        b["sources"][source] = b["sources"].get(source, 0.0) + qty

    # 1) po_accessories → selalu aksesoris
    for a in acc_rows:
        _add_acc(a.get("accessory_name"), a.get("accessory_code"), a.get("unit", "pcs"),
                 _f(a.get("qty_needed")), "po_accessory", a.get("po_id"))

    # 2) BOM-derived (qty_per_pcs × po_item.qty)
    for it in items:
        pid = it.get("po_id")
        qty = _int(it.get("qty"))
        _po_bucket(pid)["item_qty"] += qty
        bom = bom_by_catalog.get(it.get("catalog_item_id"))
        if not bom or qty <= 0:
            continue
        for m in (bom.get("materials") or []):
            need = _f(m.get("qty_per_pcs")) * qty
            if need <= 0:
                continue
            mname = m.get("material_name", "")
            cat = m.get("category", "")
            unit = m.get("unit", "pcs")
            # semua material BOM → masuk bom_materials (referensi), aksesoris juga masuk rekap accessory
            mkey = _norm(mname)
            mrec = bom_mat_agg.setdefault(mkey, {
                "name": mname, "category": cat, "unit": unit, "total_qty": 0.0,
                "is_accessory": _is_accessory(cat, mname), "by_po": {},
            })
            mrec["total_qty"] += need
            mp = mrec["by_po"].setdefault(pid, {
                "po_id": pid, "po_number": po_by_id.get(pid, {}).get("po_number", ""), "qty": 0.0,
            })
            mp["qty"] += need
            if _is_accessory(cat, mname):
                _add_acc(mname, m.get("code", ""), unit, need, "bom", pid)

    # Finalisasi bentuk list
    def _round(v):
        return round(v, 2) if isinstance(v, float) else v

    accessories = []
    for rec in acc_agg.values():
        rec["total_qty"] = _round(rec["total_qty"])
        rec["sources"] = {k: _round(v) for k, v in rec["sources"].items()}
        rec["by_po"] = sorted(
            [{**pu, "qty": _round(pu["qty"]),
              "sources": {k: _round(v) for k, v in pu["sources"].items()}} for pu in rec["by_po"].values()],
            key=lambda x: x["po_number"])
        accessories.append(rec)
    accessories.sort(key=lambda r: -r["total_qty"])

    bom_materials = []
    for rec in bom_mat_agg.values():
        rec["total_qty"] = _round(rec["total_qty"])
        rec["by_po"] = sorted(
            [{**pu, "qty": _round(pu["qty"])} for pu in rec["by_po"].values()],
            key=lambda x: x["po_number"])
        bom_materials.append(rec)
    bom_materials.sort(key=lambda r: (not r["is_accessory"], -r["total_qty"]))

    # by_month (dari po_date)
    by_month: Dict[str, float] = {}
    for b in by_po.values():
        d = b.get("po_date")
        mkey = None
        if d:
            try:
                mkey = str(d)[:7]
            except Exception:
                mkey = None
        if mkey:
            by_month[mkey] = by_month.get(mkey, 0.0) + b["accessory_qty"]

    by_po_list = sorted(
        [{**b, "accessory_qty": _round(b["accessory_qty"]),
          "sources": {k: _round(v) for k, v in b["sources"].items()}} for b in by_po.values()],
        key=lambda x: x["po_number"])

    total_acc = _round(sum(r["total_qty"] for r in accessories))
    return {
        "po_id": po_id,
        "po_count": len(pos),
        "totals": {
            "accessory_qty": total_acc,
            "distinct_accessories": len(accessories),
            "from_po_accessory": _round(sum(r["sources"].get("po_accessory", 0) for r in accessories)),
            "from_bom": _round(sum(r["sources"].get("bom", 0) for r in accessories)),
        },
        "accessories": accessories,
        "bom_materials": bom_materials,
        "by_po": by_po_list,
        "by_month": sorted([{"month": k, "accessory_qty": _round(v)} for k, v in by_month.items()],
                           key=lambda x: x["month"]),
    }


# ─── M3 KAPASITAS CMT ─────────────────────────────────────────────────────────
async def capacity_overview(db, business_type: Optional[str] = None) -> Dict[str, Any]:
    """Beban di CMT vs kapasitas (vendor_partners.capacity_pcs). READ-ONLY.

    Tahap 9 (keputusan 7 & 11): beban dihitung dari SEMUA PO berjalan — internal DAN maklon, karena satu
    CMT mengerjakan keduanya (dulu hanya maklon, sehingga CMT yang penuh order internal tampak kosong).
    Angka diambil dari `core.pantau_produksi.capacity` (sumber yang sama dengan layar Pantau Produksi),
    ditambah pemisahan beban internal/maklon dan laju setor nyata per hari.
    """
    from core.pantau_produksi import capacity
    return await capacity(db, business_type)
