"""core.kirim_cmt — SATU hitungan kiriman ke CMT (Tahap 9, 7 Nov 2026).

Dipakai oleh pratinjau form, pembuatan kiriman (normal, tambahan, pengganti), surat jalan, SPP, dan
dokumen pengeluaran (Material Issue). Sebelumnya ada dua angka untuk satu penyerahan: stok berkurang persis
angka BOM (pecahan 4 desimal), sedangkan panel aksesoris yang bisa diubah & tercetak di surat jalan tidak
mengurangi stok — dan semua yang bukan satuan kg dianggap "aksesoris", sehingga potongan ikut tampil di panel
aksesoris.

ATURAN (keputusan owner 7 Nov 2026, `keputusan_tahap9_2026-11-07.md`):
  * POTONGAN (hasil Cutting, `is_cut_panel` / kode `CUT-`) diambil otomatis dari BOM: pcs per SKU, pas, tidak
    bisa diubah. Kiriman DIBLOKIR bila stok potongan kurang — juga saat setelan "stok boleh minus" ON — dan
    bila BOM warna itu tidak ada (tidak memakai BOM warna lain). Stok diambil dari beberapa lokasi bila perlu.
    Nilai potongan = `unit_cost` potongan (nilai cutting), disimpan `unit_cost_applied` per baris.
  * AKSESORIS (keputusan 3): angka BOM hanya PERKIRAAN; user mengisi jumlah FINAL dalam SATUAN SERAH. Stok
    berkurang tepat qty serah × isi kemasan (satuan dasar). Setelan "stok boleh minus" berlaku di sini.
  * Keputusan 4: semua yang diserahkan langsung menjadi biaya PO saat dikirim — tidak ada lokasi "Di CMT".
  * Satu dokumen pengeluaran per kiriman: `rahaza_material_issues` dengan `po_id`, `shipment_id`, dan
    `items[]` {material_id, qty_issued (satuan dasar), unit_cost_applied, kind: potongan|aksesoris,
    po_item_id (potongan)}; PO maklon `cost_target='maklon'` (jurnal tetap `rahaza_posting.post_inventory_issue`).
    KONTRAK INI DIBACA AGEN HPP — nama field jangan diubah.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from core import satuan_serah as ss
from core.material_issue_engine import BomMissing

logger = logging.getLogger(__name__)

KIND_POTONGAN = "potongan"
KIND_AKSESORIS = "aksesoris"
KIND_KILOAN = "kiloan"
DA_OWNERSHIP = ("cv_da_stock", "cv_da", "da_provided")
MI_INACTIVE = ("rejected", "cancelled")
MI_SOURCE_INTERNAL = "vendor_shipment"
MI_SOURCE_MAKLON = "vendor_shipment_maklon"
_EPS = 1e-9


def _f(v: Any) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return x if x == x else 0.0


def _r(v: Any, nd: int = 4) -> float:
    return round(_f(v), nd)


class KirimBlocked(BomMissing):
    """Kiriman tidak boleh dibuat (stok potongan kurang, BOM warna tidak ada, aksesoris tanpa master, …)."""

    def __init__(self, reasons: list, calc: Optional[dict] = None):
        self.reasons = list(reasons or [])
        self.calc = calc
        super().__init__("; ".join(self.reasons) or "Kiriman tidak bisa dibuat.")


# ═════════════════════════════════════════════════════════════════════════════
# 1. JENIS MATERIAL — satu definisi "potongan vs aksesoris"
# ═════════════════════════════════════════════════════════════════════════════
def kind_of(mat: Optional[dict] = None, line: Optional[dict] = None) -> str:
    """'potongan' (hasil Cutting) | 'kiloan' (kain roll/benang berkg — keluar lewat Cutting/Request Internal)
    | 'aksesoris' (selain itu). Potongan dikenali dari master (`is_cut_panel`, kategori CUT_PANEL) atau
    baris BOM (`is_cut_panel` / kode `CUT-`) — sama dengan `core.cut_panel_master`."""
    from core.cut_panel_master import is_panel_line, is_panel_material
    from core.material_fields import is_kglike
    m, ln = mat or {}, line or {}
    if is_panel_material(m) or is_panel_line(ln) or str(m.get("category_code") or "").upper() == "CUT_PANEL":
        return KIND_POTONGAN
    if m:
        # jenis master yang menentukan (aksesoris bersatuan kg — mis. karet — tetap aksesoris)
        return KIND_KILOAN if is_kglike(m.get("type")) else KIND_AKSESORIS
    if ln:
        from routes.rahaza_bom import _is_kglike
        from core import bom_uom
        if _is_kglike({**ln, "unit": bom_uom.base_unit_of(ln)}):
            return KIND_KILOAN
    return KIND_AKSESORIS


def is_maklon(po: Optional[dict]) -> bool:
    from core.entities import is_maklon_po
    return is_maklon_po(po)


# ═════════════════════════════════════════════════════════════════════════════
# 2. BOM PER WARNA (tanpa jatuh ke warna lain)
# ═════════════════════════════════════════════════════════════════════════════
async def resolve_bom(db, po_item: dict) -> tuple:
    """(bom | None, masalah | None). BOM warna baris PO, lalu BOM umum (tanpa warna). TIDAK PERNAH BOM warna lain."""
    from routes.production_internal_adapter import _active_bom
    label = po_item.get("sku") or po_item.get("product_name") or po_item.get("id") or "?"
    if not po_item.get("model_id") or not po_item.get("size_id"):
        return None, f"{label}: baris PO belum tertaut model & ukuran master — BOM tidak bisa dibaca"
    color = (po_item.get("color") or "").strip()
    code = (po_item.get("color_code") or "").strip()
    bom = await _active_bom(db, po_item["model_id"], po_item["size_id"], color or code, color_code=code)
    if not bom:
        warna = color or code
        return None, (f"{label}: BOM untuk warna {warna} belum ada — buat BOM warna itu di Master Produk "
                      "(sistem tidak memakai BOM warna lain)" if warna else
                      f"{label}: belum ada BOM aktif untuk model & ukuran ini")
    return bom, None


# ═════════════════════════════════════════════════════════════════════════════
# 3. STOK PER LOKASI + ALOKASI BANYAK LOKASI
# ═════════════════════════════════════════════════════════════════════════════
async def _karantina(db) -> set:
    return {loc["id"] async for loc in db.rahaza_locations.find(
        {"$or": [{"storage_role": "karantina"}, {"role": "karantina"}]}, {"_id": 0, "id": 1})}


async def stock_by_location(db, material_ids) -> dict:
    """{material_id: [{location_id, qty}]} tanpa karantina, urut stok terbanyak dulu (satu kueri)."""
    ids = sorted({m for m in material_ids if m})
    if not ids:
        return {}
    kar = await _karantina(db)
    out: dict = {}
    async for s in db.rahaza_material_stock.find({"material_id": {"$in": ids}},
                                                 {"_id": 0, "material_id": 1, "location_id": 1, "qty": 1}):
        if not s.get("location_id") or s["location_id"] in kar:
            continue
        out.setdefault(s["material_id"], []).append({"location_id": s["location_id"], "qty": _f(s.get("qty"))})
    for rows in out.values():
        rows.sort(key=lambda r: (-r["qty"], r["location_id"]))
    return out


def allocate(rows: list, need: float, used: dict) -> tuple:
    """Ambil `need` dari beberapa lokasi (stok terbanyak dulu). `used` = {location_id: qty} yang sudah dialokasikan
    baris lain material yang sama di kiriman ini. Return ([{location_id, qty}], kurang)."""
    left = max(0.0, _f(need))
    out = []
    for r in rows or []:
        if left <= _EPS:
            break
        free = r["qty"] - _f(used.get(r["location_id"]))
        if free <= _EPS:
            continue
        take = min(free, left)
        out.append({"location_id": r["location_id"], "qty": round(take, 6)})
        used[r["location_id"]] = _f(used.get(r["location_id"])) + take
        left -= take
    return out, round(max(0.0, left), 6)


def available_total(rows: list, used: dict) -> float:
    return round(sum(max(0.0, r["qty"] - _f(used.get(r["location_id"]))) for r in rows or []), 6)


# ═════════════════════════════════════════════════════════════════════════════
# 4. RENCANA AKSESORIS PO (po_accessories + satuan serah)
# ═════════════════════════════════════════════════════════════════════════════
async def _materials_by(db, ids=(), codes=()) -> tuple:
    by_id, by_code = {}, {}
    ids = sorted({i for i in ids if i})
    codes = sorted({str(c).strip().upper() for c in codes if c})
    if ids:
        async for m in db.rahaza_materials.find({"id": {"$in": ids}}, {"_id": 0}):
            by_id[m["id"]] = m
    if codes:
        async for m in db.rahaza_materials.find({"code": {"$in": codes}, "active": {"$ne": False}}, {"_id": 0}):
            by_code[str(m.get("code") or "").upper()] = m
    return by_id, by_code


def _pick(by_id: dict, by_code: dict, mid=None, code=None) -> Optional[dict]:
    return by_id.get(mid) or by_code.get(str(code or "").strip().upper())


async def po_plan(db, po: dict) -> dict:
    """Rencana aksesoris PO yang DISERAHKAN DA (satu sumber untuk form kirim, SPP, dan surat jalan).

    Return {rows, client_rows, excluded_potongan}. Baris lama tanpa field satuan serah dilengkapi saat dibaca
    (tidak menulis). Potongan yang dulu ikut tercatat sebagai aksesoris (cacat "9 dari 26 baris") dibuang."""
    raw = await db.po_accessories.find({"po_id": po.get("id")}, {"_id": 0}).to_list(2000)
    by_id, by_code = await _materials_by(db, [r.get("accessory_id") for r in raw],
                                         [r.get("accessory_code") for r in raw])
    maklon = is_maklon(po)
    rows, client_rows, excluded = [], [], []
    for r in raw:
        mat = _pick(by_id, by_code, r.get("accessory_id"), r.get("accessory_code"))
        if kind_of(mat, {"code": r.get("accessory_code")}) == KIND_POTONGAN:
            excluded.append(r.get("accessory_code") or r.get("accessory_name") or "")
            continue
        if maklon and (r.get("ownership") or "client_provided") not in DA_OWNERSHIP:
            client_rows.append({"accessory_name": r.get("accessory_name") or "", "accessory_code": r.get("accessory_code")
                                or "", "qty_needed": _f(r.get("qty_needed")), "unit": r.get("unit") or ""})
            continue
        auto = ss.is_auto_row(r)
        if r.get("handover_uom") and r.get("plan_qty_handover") not in (None, ""):
            row = dict(r)
            row.setdefault("handover_label", ss.unit_label(mat, r["handover_uom"], r.get("handover_factor")))
            row["source"] = ss.SOURCE_BOM if auto else (r.get("source") if r.get("source") in
                                                        (ss.SOURCE_BOM, ss.SOURCE_TAMBAHAN) else ss.SOURCE_TAMBAHAN)
        else:  # baris lama: qty_needed (satuan dasar) = perkiraan BOM / tambahan manual
            src = ss.SOURCE_BOM if auto else ss.SOURCE_TAMBAHAN
            pf = ss.plan_fields(mat, bom_qty_base=_f(r.get("qty_needed")), source=src,
                                plan_qty_handover=(None if auto else ss.ceil_units(_f(r.get("qty_needed")),
                                                                                    ss.handover_unit(mat)["factor"])),
                                usage_unit=r.get("unit") or "")
            row = {**r, **pf}
        row["material"] = mat
        row["material_id"] = (mat or {}).get("id") or r.get("accessory_id")
        rows.append(row)
    return {"rows": rows, "client_rows": client_rows, "excluded_potongan": [x for x in excluded if x]}


# ═════════════════════════════════════════════════════════════════════════════
# 5. HITUNGAN KIRIMAN (pratinjau = yang disimpan = yang dicetak)
# ═════════════════════════════════════════════════════════════════════════════
async def _po_items(db, ids) -> dict:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    return {p["id"]: p async for p in db.po_items.find({"id": {"$in": ids}}, {"_id": 0})}


async def _pcs_sent_before(db, po_id: str, exclude_shipment_id: str = "") -> float:
    sids = [s["id"] async for s in db.vendor_shipments.find(
        {"po_id": po_id, "shipment_type": {"$in": ["NORMAL", None, ""]}, "opening": {"$ne": True}},
        {"_id": 0, "id": 1}) if s["id"] != exclude_shipment_id]
    if not sids:
        return 0.0
    total = 0.0
    async for it in db.vendor_shipment_items.find({"shipment_id": {"$in": sids}}, {"_id": 0, "qty_sent": 1}):
        total += _f(it.get("qty_sent"))
    return total


async def sample_warning(db, po: Optional[dict]) -> Optional[dict]:
    """Keputusan 10: PO maklon yang sampelnya belum disetujui → PERINGATAN (kiriman tetap boleh).

    Status sampel dibaca lewat SATU penilai (`core.sample_status.sample_flags`) — sama dengan tanda
    "Sampel belum disetujui" di daftar & rincian PO, supaya form kirim dan layar PO tidak pernah berbeda."""
    if not po or not is_maklon(po):
        return None
    from core.sample_status import sample_flags
    st = (await sample_flags(db, [po])).get(po.get("id"))
    if not st or st.get("has_approved") or not st.get("warning"):
        return None
    num = po.get("po_number") or ""
    if not st.get("count"):
        return {"code": "belum_ada", "message": f"PO {num} belum punya sampel yang disetujui "
                                                "klien. Kiriman tetap bisa dibuat."}
    label = (st.get("latest_label") or st.get("latest_status") or "").lower()
    return {"code": "belum_disetujui",
            "message": f"Sampel PO {num} belum disetujui ({label}). Kiriman tetap bisa dibuat."}


async def compute(db, *, po_id: str, lines: list | None = None, accessory_input: list | None = None,
                  materials: list | None = None, mode: str = "normal", shipment_id: str = "",
                  with_stock: bool = True) -> dict:
    """Hitungan satu kiriman ke CMT.

    lines            = [{po_item_id, qty}] — pcs garmen per SKU (potongan dari BOM)
    accessory_input  = [{key|material_id|accessory_id, qty_handover, handover_uom?}] — jumlah FINAL user
                       (bentuk lama {qty_sent} = satuan dasar juga diterima)
    materials        = [{material_id, qty, uom?}] — baris langsung (permintaan tambahan): potongan / aksesoris
    mode             = 'normal' (aksesoris dari rencana PO) | 'tambahan' (hanya yang diminta) | 'spp' (seluruh PO)
    """
    from core import bom_uom, negative_stock
    from core.accessory_issue import po_issued_by_material
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0}) if po_id else None
    if not po:
        return {"applicable": False, "blocking": True, "blocking_reasons": ["PO tidak ditemukan."],
                "potongan": [], "aksesoris": [], "warnings": []}
    maklon = is_maklon(po)
    neg_ok = await negative_stock.allowed(db) if with_stock else False
    lines = [ln for ln in (lines or []) if ln.get("po_item_id") and _f(ln.get("qty")) > 0]
    pis = await _po_items(db, [ln["po_item_id"] for ln in lines])
    blocks, warnings = [], []
    pot_rows, est_by_key = [], {}
    kiloan_seen = set()

    # ── (a) potongan dari BOM per SKU (+ perkiraan aksesoris untuk kiriman ini) ──────────────────────
    bom_lines = []
    for ln in lines:
        pi = pis.get(ln["po_item_id"])
        if not pi:
            blocks.append(f"Baris PO {ln['po_item_id']} tidak ditemukan.")
            continue
        qty = int(round(_f(ln["qty"])))
        if maklon and not pi.get("model_id"):
            continue                 # maklon: kain & potongan milik klien — tidak dari gudang DA
        bom, problem = await resolve_bom(db, pi)
        if problem:
            blocks.append(problem)
            continue
        mats, uom_warn = await bom_uom.ensure_uom(db, bom)
        warnings.extend(w for w in uom_warn if w not in warnings)
        bom_lines.append((pi, qty, bom, mats))
    by_id, by_code = await _materials_by(
        db, [m.get("material_id") for _, _, _, ms in bom_lines for m in ms]
        + [m.get("material_id") for m in (materials or [])],
        [m.get("code") for _, _, _, ms in bom_lines for m in ms])
    for pi, qty, bom, mats in bom_lines:
        label = pi.get("sku") or pi.get("product_name") or pi["id"]
        panels = 0
        for m in mats:
            mat = _pick(by_id, by_code, m.get("material_id"), m.get("code"))
            k = kind_of(mat, m)
            per = bom_uom.qty_base_of(m)
            if k == KIND_POTONGAN:
                panels += 1
                pcode = str((mat or {}).get("color_code") or "").upper()
                want = str(pi.get("color_code") or "").upper()
                if pcode and want and pcode != want:
                    blocks.append(f"{label}: BOM menunjuk potongan warna lain ({(mat or {}).get('code')}) — "
                                  "perbaiki BOM warna ini di Master Produk")
                    continue
                if not mat:
                    blocks.append(f"{label}: potongan {m.get('code') or m.get('name')} belum ada di master material")
                    continue
                pot_rows.append({"po_item_id": pi["id"], "sku": pi.get("sku") or "", "size": pi.get("size") or "",
                                 "color": pi.get("color") or "", "product_name": pi.get("product_name") or "",
                                 "material_id": mat["id"], "code": mat.get("code") or "", "name": mat.get("name") or "",
                                 "unit": "pcs", "qty_per_pcs": per, "qty_pcs": qty, "qty": _r(per * qty, 6),
                                 "unit_cost": _f(mat.get("unit_cost")), "kind": KIND_POTONGAN})
            elif k == KIND_KILOAN:
                kiloan_seen.add(m.get("code") or m.get("name") or "")
            else:
                key = ss.row_key({"material_id": (mat or {}).get("id") or m.get("material_id"),
                                  "code": m.get("code"), "name": m.get("name")})
                e = est_by_key.setdefault(key, {"qty": 0.0, "material": mat, "code": m.get("code"),
                                                "name": m.get("name")})
                e["qty"] += per * qty
        if not panels:
            blocks.append(f"{label}: BOM belum punya baris potongan — perbarui BOM ke potongan di Master Produk")
    if kiloan_seen:
        warnings.append("Baris kain/benang kiloan di BOM tidak dikeluarkan saat kirim (kain keluar lewat Cutting, "
                        f"benang lewat Request Internal): {', '.join(sorted(x for x in kiloan_seen if x))}")

    # ── (b) baris langsung (permintaan tambahan): potongan / aksesoris ───────────────────────────────
    direct_acc = []
    for d in materials or []:
        mat = by_id.get(d.get("material_id"))
        if not mat:
            blocks.append(f"Barang {d.get('material_code') or d.get('material_id') or '?'} tidak ada di master material.")
            continue
        k = kind_of(mat)
        if k == KIND_KILOAN:
            blocks.append(f"{mat.get('code')}: kain/benang kiloan tidak dikirim ke CMT — kain dipotong dulu di "
                          "Cutting, benang lewat Request Internal (bahan pembantu).")
            continue
        if k == KIND_POTONGAN:
            q = _f(d.get("qty"))
            pot_rows.append({"po_item_id": d.get("po_item_id") or "", "sku": d.get("sku") or "", "size": "",
                             "color": mat.get("color") or "", "product_name": "", "material_id": mat["id"],
                             "code": mat.get("code") or "", "name": mat.get("name") or "", "unit": "pcs",
                             "qty_per_pcs": 1.0, "qty_pcs": q, "qty": _r(q, 6), "unit_cost": _f(mat.get("unit_cost")),
                             "kind": KIND_POTONGAN})
        else:
            direct_acc.append((mat, d))

    # ── (c) aksesoris: rencana PO (normal/spp) atau yang diminta (tambahan) ──────────────────────────
    inputs = {}
    for a in accessory_input or []:
        k = ss.row_key({"material_id": a.get("material_id") or a.get("accessory_id"), "code": a.get("accessory_code"),
                        "name": a.get("accessory_name")}) or str(a.get("key") or "").lower()
        if a.get("key"):
            inputs[str(a["key"]).lower()] = a
        if k:
            inputs[k] = a
    acc_rows = []
    issued = await po_issued_by_material(db, po["id"]) if mode != "spp" else {}
    if mode in ("normal", "spp"):
        plan = await po_plan(db, po)
        po_qty = sum(_f(i.get("qty")) for i in await db.po_items.find(
            {"po_id": po["id"]}, {"_id": 0, "qty": 1}).to_list(5000))
        now_pcs = sum(_f(ln["qty"]) for ln in lines)
        before_pcs = await _pcs_sent_before(db, po["id"], shipment_id) if mode == "normal" else 0.0
        cum = 1.0 if (mode == "spp" or po_qty <= 0) else min(1.0, (before_pcs + now_pcs) / po_qty)
        seen = set()
        for r in plan["rows"]:
            key = ss.row_key(r)
            seen.add(key)
            factor = _f(r.get("handover_factor")) or 1.0
            plan_base = ss.to_base(r.get("plan_qty_handover"), factor)
            before = _f(issued.get(r.get("material_id"))) if mode == "normal" else 0.0
            remaining = max(0.0, plan_base - before)
            est = est_by_key.get(key)
            est_now = _f(est["qty"]) if est else (_f(r.get("bom_qty_base")) * (now_pcs / po_qty) if po_qty else 0.0)
            if mode == "spp":
                default = _f(r.get("plan_qty_handover"))
            else:
                default = min(ss.ceil_units(max(0.0, plan_base * cum - before), factor),
                              ss.ceil_units(remaining, factor))
            acc_rows.append(_acc_row(r.get("material"), r, key=key, factor=factor, uom=r.get("handover_uom"),
                                     label=r.get("handover_label"), est_now=est_now, plan=r.get("plan_qty_handover"),
                                     before=before, remaining=remaining, default=default, inp=inputs.get(key),
                                     source=r.get("source")))
        for key, e in est_by_key.items():                 # BOM berubah sesudah PO disimpan: ikut, rencana = perkiraan
            if key in seen or mode == "spp":
                continue
            hu = ss.handover_unit(e["material"])
            before = _f(issued.get((e["material"] or {}).get("id")))
            default = ss.ceil_units(max(0.0, e["qty"] - 0), hu["factor"])
            acc_rows.append(_acc_row(e["material"], {"accessory_name": e["name"], "accessory_code": e["code"]},
                                     key=key, factor=hu["factor"], uom=hu["uom"], label=hu["label"], est_now=e["qty"],
                                     plan=None, before=before, remaining=None, default=default, inp=inputs.get(key),
                                     source=ss.SOURCE_BOM))
        if plan["excluded_potongan"]:
            warnings.append(f"{len(plan['excluded_potongan'])} baris rencana aksesoris PO adalah potongan — tidak "
                            "dihitung sebagai aksesoris (potongan diambil dari BOM per SKU).")
        client_rows = plan["client_rows"]
    else:
        client_rows = []
    from core import uom as uom_core
    for mat, d in direct_acc:
        u = uom_core.normalize_code(d.get("uom") or d.get("unit"))
        if u and u != uom_core.base_uom_of(mat) and not uom_core.find_uom(mat, u):
            try:                                   # satuan sedimensi (m → cm, lusin → pcs)
                f, _src = bom_uom.factor_to_base(mat, u)
                hu = {"uom": u, "factor": f, "label": ss.unit_label(mat, u, f) if f != 1 else u}
            except uom_core.UomError:
                blocks.append(f"{mat.get('code')}: satuan '{u}' tidak dikenal untuk barang ini — pilih satuan dari "
                              "daftar satuan material.")
                continue
        else:
            hu = ss.resolve_handover(mat, u)
        key = ss.row_key({"material_id": mat["id"]})
        acc_rows.append(_acc_row(mat, {"accessory_name": mat.get("name"), "accessory_code": mat.get("code")},
                                 key=key, factor=hu["factor"], uom=hu["uom"], label=hu["label"], est_now=0.0,
                                 plan=None, before=_f(issued.get(mat["id"])), remaining=None,
                                 default=_f(d.get("qty")), inp=inputs.get(key), source="permintaan"))

    # ── (d) stok: potongan WAJIB cukup; aksesoris ikut setelan stok boleh minus ─────────────────────
    stock = await stock_by_location(db, [p["material_id"] for p in pot_rows]
                                    + [a["material_id"] for a in acc_rows if a.get("material_id")]) if with_stock else {}
    used: dict = {}
    loc_codes = {}
    for p in pot_rows:
        u = used.setdefault(p["material_id"], {})
        p["available"] = available_total(stock.get(p["material_id"]), u)
        allocs, short = allocate(stock.get(p["material_id"]), p["qty"], u) if with_stock else ([], 0.0)
        p["allocations"], p["short"] = allocs, short
        p["value"] = round(p["qty"] * p["unit_cost"], 2)
        p["blocking"] = bool(with_stock and short > _EPS)
        if p["blocking"]:
            p["problem"] = (f"stok potongan kurang {ss.fmt_num(short)} pcs — catat hasil cutting dulu"
                            if p["available"] > _EPS else "belum ada stok potongan — catat hasil cutting dulu")
            blocks.append(f"{p['code']} ({p['sku'] or p['name']}): butuh {ss.fmt_num(p['qty'])} pcs, stok "
                          f"{ss.fmt_num(p['available'])} pcs. Catat hasil cutting dulu.")
        else:
            p["problem"] = ""
    for a in acc_rows:
        a["allocations"], a["short"], a["available"] = [], 0.0, 0.0
        a["blocking"], a["negative"] = False, False
        if a["qty_base"] <= _EPS:
            continue
        if not a.get("material_id"):
            a["blocking"] = True
            a["problem"] = "belum tertaut master material"
            blocks.append(f"Aksesoris {a['name'] or a['code']} belum tertaut master material — perbaiki BOM/rencana PO.")
            continue
        if not with_stock:
            continue
        u = used.setdefault(a["material_id"], {})
        rows = stock.get(a["material_id"]) or []
        a["available"] = available_total(rows, u)
        allocs, short = allocate(rows, a["qty_base"], u)
        if short > _EPS:
            if neg_ok:
                target = rows[0]["location_id"] if rows else None
                if not target:
                    fb = await negative_stock.fallback_location(db, a.get("_material") or {})
                    target = (fb or {}).get("id")
                    if fb:
                        loc_codes[target] = fb.get("code")
                if target:
                    hit = next((x for x in allocs if x["location_id"] == target), None)
                    if hit:
                        hit["qty"] = round(hit["qty"] + short, 6)
                    else:
                        allocs.append({"location_id": target, "qty": short})
                    a["negative"] = True
                    a["problem"] = f"stok kurang — akan minus {ss.fmt_num(short)} {a['usage_unit']}"
                    short = 0.0
            if short > _EPS:
                a["blocking"] = True
                a["problem"] = (f"stok kurang {ss.fmt_num(short)} {a['usage_unit']}" if rows
                                else "belum punya stok di gudang")
                blocks.append(f"{a['code'] or a['name']}: diserahkan {ss.fmt_num(a['qty_handover'])} {a['handover_label']}"
                              f" = {ss.fmt_num(a['qty_base'])} {a['usage_unit']}, stok {ss.fmt_num(a['available'])}.")
        a["allocations"], a["short"] = allocs, short
    for a in acc_rows:
        a.pop("_material", None)

    pot_value = round(sum(p["value"] for p in pot_rows), 2)
    acc_value = round(sum(a["value"] for a in acc_rows), 2)
    return {
        "applicable": True, "po_id": po["id"], "po_number": po.get("po_number") or "",
        "business_type": "maklon" if maklon else "internal", "mode": mode,
        "allow_negative": neg_ok, "total_pcs": int(sum(_f(ln["qty"]) for ln in lines)),
        "potongan": pot_rows, "aksesoris": acc_rows, "client_accessories": client_rows,
        "blocking": bool(blocks), "blocking_reasons": blocks, "warnings": warnings,
        "has_negative": any(a.get("negative") for a in acc_rows),
        "value": {"potongan": pot_value, "aksesoris": acc_value, "total": round(pot_value + acc_value, 2)},
        "sample_warning": await sample_warning(db, po) if mode != "spp" else None,
    }


def _acc_row(mat, src: dict, *, key, factor, uom, label, est_now, plan, before, remaining, default, inp, source) -> dict:
    m = mat or {}
    factor = _f(factor) or 1.0
    if inp is not None and inp.get("qty_handover") not in (None, ""):
        hu = ss.resolve_handover(mat, inp.get("handover_uom") or uom) if mat else {"uom": uom, "factor": factor,
                                                                                    "label": label}
        uom, factor, label = hu["uom"], _f(hu["factor"]) or 1.0, hu["label"]
        qty_hand, edited = round(max(0.0, _f(inp["qty_handover"])), 4), True
    elif inp is not None and inp.get("qty_sent") not in (None, ""):          # klien lama: qty satuan dasar
        qty_hand, edited = round(max(0.0, _f(inp["qty_sent"])) / factor, 6), True
    else:
        qty_hand, edited = round(max(0.0, _f(default)), 4), False
    qty_base = round(qty_hand * factor, 6)
    unit_cost = _f(m.get("unit_cost"))
    return {
        "key": key, "material_id": m.get("id") or src.get("accessory_id") or "",
        "code": m.get("code") or src.get("accessory_code") or "", "name": m.get("name") or src.get("accessory_name") or "",
        "usage_unit": (m.get("base_uom") or m.get("unit") or src.get("unit") or "pcs"),
        "handover_uom": uom, "handover_factor": factor, "handover_label": label or uom,
        "estimate_base": round(_f(est_now), 4), "estimate_handover": ss.ceil_units(est_now, factor),
        "plan_qty_handover": plan, "handed_before_base": round(_f(before), 4),
        "remaining_base": None if remaining is None else round(_f(remaining), 4),
        "remaining_handover": None if remaining is None else round(_f(remaining) / factor, 4),
        "default_handover": round(_f(default), 4), "qty_handover": qty_hand, "edited": edited,
        "qty_base": qty_base, "unit_cost": unit_cost, "value": round(qty_base * unit_cost, 2),
        "source": source or ss.SOURCE_BOM, "kind": KIND_AKSESORIS, "_material": m,
        # owner 11 Nov 2026: harga jual ke CMT yang diisi di PO → isian nota terisi otomatis (tetap bisa diubah)
        "harga_jual_po": ss.harga_untuk(src, factor),
        "options": ss.handover_unit(mat)["options"] if mat else [],
    }


# ═════════════════════════════════════════════════════════════════════════════
# 6. TERBITKAN DOKUMEN PENGELUARAN (satu MI per kiriman) + catat aksesoris kiriman
# ═════════════════════════════════════════════════════════════════════════════
def mi_items_from_calc(calc: dict) -> list:
    """Baris MI dari hitungan — satu baris per (material, lokasi[, po_item]). Inilah yang memotong stok."""
    from routes.rahaza_inventory_shared import _uid
    items = []
    for p in calc.get("potongan") or []:
        for al in p.get("allocations") or []:
            items.append({"id": _uid(), "material_id": p["material_id"], "qty_required": al["qty"], "qty_issued": 0,
                          "location_id": al["location_id"], "kind": KIND_POTONGAN, "po_item_id": p["po_item_id"],
                          "sku": p.get("sku") or "", "unit_cost_applied": p["unit_cost"], "allow_negative": False,
                          "notes": f"Potongan {p.get('sku') or ''}".strip()})
    for a in calc.get("aksesoris") or []:
        if a["qty_base"] <= _EPS:
            continue
        for al in a.get("allocations") or []:
            items.append({"id": _uid(), "material_id": a["material_id"], "qty_required": al["qty"], "qty_issued": 0,
                          "location_id": al["location_id"], "kind": KIND_AKSESORIS, "unit_cost_applied": a["unit_cost"],
                          "allow_negative": bool(calc.get("allow_negative")), "handover_uom": a["handover_uom"],
                          "handover_factor": a["handover_factor"], "qty_handover": a["qty_handover"],
                          "notes": f"Aksesoris {ss.fmt_num(a['qty_handover'])} {a['handover_label']}"})
    return items


async def existing_mi(db, shipment_id: str) -> Optional[dict]:
    return await db.rahaza_material_issues.find_one(
        {"vendor_shipment_id": shipment_id, "status": {"$nin": list(MI_INACTIVE)}}, {"_id": 0})


async def issue_calc(db, *, shipment: dict, calc: dict, user: dict) -> dict:
    """Potong stok sesuai hitungan (`compute`) lewat mesin yang sama dengan approve MI. Idempoten per kiriman."""
    from core import material_issue_engine as mie
    from routes.rahaza_inventory_shared import _gen_mi_number, _now, _uid
    if calc.get("blocking"):
        raise KirimBlocked(calc.get("blocking_reasons") or [], calc)
    prev = await existing_mi(db, shipment["id"])
    if prev:
        return {"ok": True, "already": True, "mi": prev, "mi_number": prev.get("mi_number"), "kirim": calc}
    items = mi_items_from_calc(calc)
    if not items:
        return {"ok": True, "already": False, "skipped": True, "mi": None, "kirim": calc,
                "material_lines": 0, "bom_notes": calc.get("warnings") or []}
    maklon = calc.get("business_type") == "maklon"
    po_id = calc.get("po_id")
    mi = {
        "id": _uid(), "mi_number": await _gen_mi_number(db, sistem=True),
        "work_order_id": None, "wo_number_snapshot": "", "job_id": None,
        # kontrak Tahap 9 (dibaca agen HPP) + nama lama (dibaca HPP job, retur, daftar MI)
        "po_id": po_id, "shipment_id": shipment["id"],
        "production_po_id": po_id, "po_number_snapshot": calc.get("po_number") or shipment.get("po_number") or "",
        "vendor_shipment_id": shipment["id"], "vendor_shipment_number": shipment.get("shipment_number") or "",
        "shipment_type": shipment.get("shipment_type") or "NORMAL",
        "vendor_id": shipment.get("vendor_id") or "", "vendor_name": shipment.get("vendor_name") or "",
        "business_type": calc.get("business_type"), **({"cost_target": "maklon"} if maklon else {}),
        "qty_wo_pcs": calc.get("total_pcs") or 0, "items": items, "status": "pending_approval",
        "source": MI_SOURCE_MAKLON if maklon else MI_SOURCE_INTERNAL, "kirim_t9": True,
        "notes": f"Otomatis dari kiriman ke CMT {shipment.get('shipment_number') or ''}",
        "bom_notes": calc.get("warnings") or [],
        "created_by": user.get("id"), "created_by_name": user.get("name", ""),
        "created_at": _now(), "updated_at": _now(),
    }
    await db.rahaza_material_issues.insert_one(dict(mi))
    try:
        fresh = await mie.issue_material_issue(db, mi, user,
                                               ref_type="maklon_material_issue" if maklon else "cmt_material_issue")
    except Exception:
        await db.rahaza_material_issues.update_one({"id": mi["id"]}, {"$set": {
            "status": "cancelled", "cancel_reason": "pengeluaran gagal — kiriman dibatalkan", "updated_at": _now()}})
        raise
    await db.vendor_shipments.update_one({"id": shipment["id"]}, {"$set": {
        "material_issue_id": mi["id"], "material_issue_number": mi["mi_number"],
        "kirim_value": calc.get("value"), "updated_at": _now()}})
    return {"ok": True, "already": False, "mi": fresh, "mi_number": mi["mi_number"], "kirim": calc,
            "material_lines": len(items), "bom_notes": calc.get("warnings") or [],
            "negative_stock_lines": fresh.get("negative_stock_lines") or []}


async def record_accessories(db, shipment: dict, calc: dict) -> int:
    """Aksesoris yang diserahkan di kiriman ini → `accessory_shipment_items` (dibaca surat jalan & pemeriksaan
    vendor). Angkanya SAMA dengan baris MI: qty serah + satuan serah + qty dasar."""
    from core.helpers import new_id, now
    n = 0
    for a in calc.get("aksesoris") or []:
        if a["qty_handover"] <= _EPS:
            continue
        await db.accessory_shipment_items.insert_one({
            "id": new_id(), "shipment_id": shipment["id"], "shipment_number": shipment.get("shipment_number"),
            "po_id": calc.get("po_id"), "po_number": calc.get("po_number") or "",
            "accessory_id": a["material_id"], "accessory_name": a["name"], "accessory_code": a["code"],
            "qty_sent": int(a["qty_handover"]) if float(a["qty_handover"]).is_integer() else a["qty_handover"],
            "unit": a["handover_uom"], "unit_label": a["handover_label"], "handover_uom": a["handover_uom"],
            "handover_factor": a["handover_factor"], "qty_base": a["qty_base"], "usage_unit": a["usage_unit"],
            "estimate_base": a["estimate_base"], "kind": KIND_AKSESORIS,
            "shipment_type": shipment.get("shipment_type", "NORMAL"),
            "parent_shipment_id": shipment.get("parent_shipment_id"),
            "source": a.get("source") or ss.SOURCE_BOM,
            "notes": "Diserahkan (jumlah final)" if a.get("edited") else "Diserahkan (sesuai rencana PO)",
            "created_at": now(),
        })
        n += 1
    return n


async def issue_for_shipment(db, shipment: dict, ship_items: list, user: dict, *, accessory_input=None,
                             materials=None, mode: str = "normal") -> dict:
    """Kiriman (normal / tambahan / pengganti) → hitung → potong stok (satu MI) → catat aksesoris kiriman."""
    lines = [{"po_item_id": it.get("po_item_id"), "qty": it.get("qty_sent")} for it in ship_items or []
             if it.get("po_item_id")]
    po_id = shipment.get("po_id") or next((it.get("po_id") for it in ship_items or [] if it.get("po_id")), "")
    calc = await compute(db, po_id=po_id, lines=lines, accessory_input=accessory_input, materials=materials,
                         mode=mode, shipment_id=shipment["id"])
    res = await issue_calc(db, shipment={**shipment, "po_id": po_id}, calc=calc, user=user)
    if not res.get("already"):
        res["accessory_lines"] = await record_accessories(db, shipment, calc)
    else:
        res["accessory_lines"] = 0
    return res


async def shipment_lines(db, ship: dict) -> dict:
    """Isi satu kiriman dari dokumen pengeluarannya (SAMA dengan yang memotong stok & tercetak di surat jalan)."""
    mi = await db.rahaza_material_issues.find_one({"id": ship.get("material_issue_id")}, {"_id": 0}) \
        if ship.get("material_issue_id") else None
    mi = mi or await existing_mi(db, ship["id"])
    items = (mi or {}).get("items") or []
    mats = {m["id"]: m async for m in db.rahaza_materials.find(
        {"id": {"$in": sorted({i.get("material_id") for i in items if i.get("material_id")})}}, {"_id": 0})} if items else {}
    pis = {p["id"]: p async for p in db.po_items.find(
        {"id": {"$in": sorted({i.get("po_item_id") for i in items if i.get("po_item_id")})}}, {"_id": 0})} if items else {}
    pot, acc_mi = {}, {}
    for it in items:
        mat = mats.get(it.get("material_id")) or {}
        kind = it.get("kind") or kind_of(mat)
        q = float(it.get("qty_issued") or it.get("qty_required") or 0)
        cost = float(it.get("unit_cost_applied") or mat.get("unit_cost") or 0)
        if kind == KIND_POTONGAN:
            k = (it.get("po_item_id") or "", it.get("material_id"))
            pi = pis.get(it.get("po_item_id")) or {}
            r = pot.setdefault(k, {"po_item_id": k[0], "sku": it.get("sku") or pi.get("sku") or "",
                                   "size": pi.get("size") or "", "color": pi.get("color") or "",
                                   "material_id": it.get("material_id"), "code": mat.get("code") or "",
                                   "name": mat.get("name") or "", "qty": 0.0, "value": 0.0, "unit_cost": cost})
            r["qty"] += q
            r["value"] += q * cost
        else:
            r = acc_mi.setdefault(it.get("material_id"), {"material_id": it.get("material_id"), "code": mat.get("code") or "",
                                                         "name": mat.get("name") or "", "qty_base": 0.0, "value": 0.0,
                                                         "usage_unit": mat.get("unit") or "", "unit_cost": cost,
                                                         "qty_handover": it.get("qty_handover"),
                                                         "handover_uom": it.get("handover_uom"),
                                                         "handover_factor": it.get("handover_factor")})
            r["qty_base"] += q
            r["value"] += q * cost
    asi = await db.accessory_shipment_items.find({"shipment_id": ship["id"]}, {"_id": 0}).to_list(500)
    aks = []
    for a in asi:
        base = a.get("qty_base")
        mi_row = acc_mi.pop(a.get("accessory_id"), None)
        aks.append({"material_id": a.get("accessory_id"), "code": a.get("accessory_code") or "",
                    "name": a.get("accessory_name") or "", "qty_handover": a.get("qty_sent"),
                    "handover_label": a.get("unit_label") or a.get("unit") or "",
                    "qty_base": base if base is not None else (mi_row or {}).get("qty_base"),
                    "usage_unit": a.get("usage_unit") or (mi_row or {}).get("usage_unit") or a.get("unit") or "",
                    "value": round((mi_row or {}).get("value") or 0, 2), "from_issue": mi_row is not None})
    for r in acc_mi.values():           # baris keluar tanpa catatan serah (dokumen lama)
        f = float(r.get("handover_factor") or 1) or 1.0
        mat = mats.get(r["material_id"])
        aks.append({**r, "qty_handover": r.get("qty_handover") or round(r["qty_base"] / f, 4),
                    "handover_label": ss.unit_label(mat, r.get("handover_uom") or (mat or {}).get("unit"), f),
                    "value": round(r["value"], 2), "from_issue": True})
    journal = None
    if mi:
        journal = {"mi_id": mi["id"], "mi_number": mi.get("mi_number"), "status": mi.get("status"),
                   "je_number": mi.get("gl_je_number"), "posted": bool(mi.get("gl_je_id")),
                   "error": mi.get("post_error") or "", "negative_lines": len(mi.get("negative_stock_lines") or [])}
    return {"potongan": [{**r, "qty": round(r["qty"], 4), "value": round(r["value"], 2)} for r in pot.values()],
            "aksesoris": aks, "journal": journal,
            "value": round(sum(r["value"] for r in pot.values()) + sum(float(a.get("value") or 0) for a in aks), 2)}


async def spp_lines(db, po: dict) -> dict:
    """Bagian BOM di SPP (Surat Perintah Produksi) — PO internal DAN maklon, dari hitungan yang sama:
    potongan per SKU (seluruh qty PO) · aksesoris rencana PO (satuan serah) · bahan klien (maklon, referensi)."""
    items = await db.po_items.find({"po_id": po["id"]}, {"_id": 0, "id": 1, "qty": 1}).to_list(5000)
    calc = await compute(db, po_id=po["id"], lines=[{"po_item_id": i["id"], "qty": i.get("qty")} for i in items],
                         mode="spp", with_stock=False)
    bulk = []
    if is_maklon(po):
        bom = await db.dewi_maklon_bom.find_one({"po_id": po["id"]}, {"_id": 0, "materials": 1}) or {}
        for m in bom.get("materials") or []:
            if m.get("line_type") == "bulk" and _f(m.get("qty_estimated") or m.get("qty_total_est")) > 0:
                bulk.append({"name": m.get("material_name") or "", "unit": m.get("unit") or "",
                             "per_pcs": _f(m.get("qty_per_pcs")), "qty": _f(m.get("qty_estimated") or m.get("qty_total_est")),
                             "owner": "Klien" if (m.get("ownership") or "client_provided") == "client_provided" else "CV DA"})
    return {"potongan": calc.get("potongan") or [], "aksesoris": calc.get("aksesoris") or [],
            "client_accessories": calc.get("client_accessories") or [], "bulk": bulk,
            "problems": calc.get("blocking_reasons") or [], "warnings": calc.get("warnings") or [],
            "business_type": calc.get("business_type")}


# ═════════════════════════════════════════════════════════════════════════════
# 7. DRAF DOBEL (GDG-2 / draf massal) — dimatikan untuk PO yang dijahit CMT
# ═════════════════════════════════════════════════════════════════════════════
async def po_sewn_by_cmt(db, po_id: str) -> bool:
    """PO dijahit CMT = PO ber-vendor atau sudah punya kiriman ke CMT."""
    if not po_id:
        return False
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "vendor_id": 1})
    if (po or {}).get("vendor_id"):
        return True
    return bool(await db.vendor_shipments.find_one({"po_id": po_id}, {"_id": 0, "id": 1}))


async def double_drafts(db, po_id: Optional[str] = None) -> list:
    """Draf MI dari job/WO (GDG-2, draf massal) yang materialnya SUDAH keluar lewat kiriman ke CMT.

    Return [{mi_id, mi_number, po_id, po_number, reason}] — dipakai pembatalan otomatis saat kirim dan
    migrasi `2026_11_07_batal_mi_dobel.py` (satu definisi)."""
    shipped = {}
    q_ship = {"vendor_shipment_id": {"$nin": [None, ""]}, "status": "issued"}
    if po_id:
        q_ship["production_po_id"] = po_id
    async for m in db.rahaza_material_issues.find(q_ship, {"_id": 0, "production_po_id": 1, "mi_number": 1}):
        if m.get("production_po_id"):
            shipped.setdefault(m["production_po_id"], m.get("mi_number"))
    if not shipped:
        return []
    jobs = {}
    async for j in db.production_jobs.find({"po_id": {"$in": list(shipped)}}, {"_id": 0, "id": 1, "po_id": 1}):
        jobs[j["id"]] = j["po_id"]
    pos = {p["id"]: p.get("po_number") or "" async for p in db.production_pos.find(
        {"id": {"$in": list(shipped)}}, {"_id": 0, "id": 1, "po_number": 1})}
    out = []
    q = {"status": {"$in": ["draft", "pending_approval", "submitted"]}, "vendor_shipment_id": {"$in": [None, ""]},
         "component_request_id": {"$in": [None, ""]}, "ref_type": {"$ne": "cutting_issue"},
         "$or": [{"production_po_id": {"$in": list(shipped)}}, {"job_id": {"$in": list(jobs)}},
                 {"work_order_id": {"$in": list(jobs)}}]}
    async for m in db.rahaza_material_issues.find(q, {"_id": 0, "id": 1, "mi_number": 1, "production_po_id": 1,
                                                       "job_id": 1, "work_order_id": 1, "bulk_batch": 1}):
        pid = m.get("production_po_id") or jobs.get(m.get("job_id")) or jobs.get(m.get("work_order_id"))
        if not pid:
            continue
        asal = "draf massal" if m.get("bulk_batch") else "draf otomatis dari job"
        out.append({"mi_id": m["id"], "mi_number": m.get("mi_number") or "", "po_id": pid,
                    "po_number": pos.get(pid, ""),
                    "reason": f"{asal}; material PO ini sudah keluar lewat kiriman ke CMT ({shipped[pid]})"})
    return sorted(out, key=lambda r: (r["po_number"], r["mi_number"]))


async def cancel_double_drafts(db, po_id: Optional[str] = None, *, actor: str = "sistem") -> list:
    from core.helpers import now
    rows = await double_drafts(db, po_id)
    for r in rows:
        await db.rahaza_material_issues.update_one(
            {"id": r["mi_id"], "status": {"$in": ["draft", "pending_approval", "submitted"]}},
            {"$set": {"status": "cancelled", "cancel_reason": r["reason"], "cancelled_by": actor,
                      "cancelled_at": now(), "updated_at": now()}})
    return rows


async def assert_not_double(db, mi: dict) -> None:
    """Penjaga approve MI: draf job/massal untuk PO yang materialnya sudah keluar lewat kiriman → 400."""
    if mi.get("vendor_shipment_id") or mi.get("component_request_id") or mi.get("ref_type") == "cutting_issue":
        return
    for r in await double_drafts(db):
        if r["mi_id"] == mi.get("id"):
            from fastapi import HTTPException
            raise HTTPException(400, f"MI {mi.get('mi_number') or ''} tidak bisa disetujui: {r['reason']}. "
                                     "Menyetujuinya akan mengeluarkan stok dua kali — dokumen ini dibatalkan.")
