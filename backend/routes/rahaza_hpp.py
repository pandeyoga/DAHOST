"""
PT Rahaza — HPP / Costing (Fase 9)

2026-11-07 (Tahap 9, keputusan owner No. 6 & 13): SATU "HPP per PO" untuk PO internal & maklon dari data nyata
(`core.hpp_aktual`: potongan + aksesoris diserahkan + upah CMT + permak; biaya umum per pcs = informasi):
  - GET /hpp/po                 : daftar HPP per PO (business_type, search, status, date_from/to, client_id, page)
  - GET /hpp/po/{po_id}         : rincian satu PO (komponen, per baris, penyerahan, biaya umum, WIP)
  - GET /hpp/overhead-info      : biaya umum produksi per pcs satu bulan (informasi)
  Endpoint lama /hpp/maklon-order, /hpp/production-po, /hpp/maklon-client & `maklon_order_figures` mendelegasikan
  ke hitungan yang sama (dulu membaca `dewi_maklon_material_issues` yang tidak ditulis lagi).

2026-11-06 (Tahap 2, keputusan owner): HPP per Work Order = (bahan + upah CMT) / qty_completed.
Upah internal (payroll) & overhead tetap beban bulanan — hanya ditampilkan sebagai informasi.
Uraian lama di bawah dipertahankan sebagai riwayat:

HPP per Work Order = (material_cost + labor_cost + overhead_cost) / qty_completed
  - material_cost: total biaya material yg di-issue ke WO (dari material_issue confirmed × unit_cost)
                   jika material tidak punya unit_cost, pakai default_yarn_cost_per_kg dari settings
  - labor_cost: alokasi dari payroll pcs yang tag ke WO (via wip_events.work_order_id)
                jika belum ada payroll run, estimasi dari rate × qty
  - overhead_cost: overhead_rate_per_pcs × qty_completed (dari rahaza_costing_settings)

Endpoints (prefix /api/rahaza):
  - GET  /costing-settings
  - PUT  /costing-settings
  - GET  /hpp/work-order/{wo_id}      : compute HPP real-time
  - POST /hpp/work-order/{wo_id}/snapshot : simpan snapshot HPP utk audit
  - GET  /hpp/snapshots               : list snapshots
"""
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc
from core import material_fields  # FASE 6.6-B: SSOT nama field + alias legacy yarn_*
from routes._maklon_adapter import legacy_orders_view as _lmo
import uuid
from datetime import datetime, timezone
from core.roles import FINANCE_ROLES  # FIN-02

router = APIRouter(prefix="/api/rahaza", tags=["rahaza-hpp"])

SETTINGS_ID = "GLOBAL"


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)


async def _require_fin(request: Request):
    user = await require_auth(request)
    from routes.shared import lolos_centang
    if lolos_centang(user):  # 14 Nov 2026 (tahap 2): centang owner dihormati
        return user
    role = (user.get("role") or "").lower()
    if role in FINANCE_ROLES:  # FIN-02
        return user
    perms = user.get("_permissions") or []
    if "*" in perms or "finance.manage" in perms or "hpp.manage" in perms:
        return user
    from core.authz import pesan_centang
    raise HTTPException(403, pesan_centang(user))


@router.get("/costing-settings")
async def get_settings(request: Request):
    await require_auth(request)
    db = get_db()
    doc = await db.rahaza_costing_settings.find_one({"id": SETTINGS_ID}, {"_id": 0})
    if not doc:
        doc = {
            "id": SETTINGS_ID,
            "overhead_rate_per_pcs": 0,
            # FASE 6.6-B: kanonik `default_material_cost_per_kg` + alias legacy
            **material_fields.mirror("default_material_cost_per_kg", 0),
            "default_accessory_cost_per_unit": 0,
            "labor_rate_fallback_per_pcs": 0,
            "notes": "",
            "updated_at": _now(),
        }
        await db.rahaza_costing_settings.insert_one(doc)
    return serialize_doc(material_fields.with_aliases(doc, "default_material_cost_per_kg"))


@router.put("/costing-settings")
async def update_settings(request: Request):
    user = await _require_fin(request)
    db = get_db()
    body = await request.json()
    allowed = ["overhead_rate_per_pcs", "default_material_cost_per_kg", "default_yarn_cost_per_kg",
               "default_accessory_cost_per_unit", "labor_rate_fallback_per_pcs", "notes"]
    upd = {k: body[k] for k in allowed if k in body}
    for k in ("overhead_rate_per_pcs", "default_accessory_cost_per_unit", "labor_rate_fallback_per_pcs"):
        if k in upd:
            upd[k] = float(upd[k] or 0)
    # FASE 11: masih MENERIMA nama kanonik ATAU legacy dari klien (kompatibilitas),
    # tetapi yang DISIMPAN hanya nama kanonik (`WRITE_ALIASES` sudah kosong).
    upd.pop("default_material_cost_per_kg", None)
    upd.pop("default_yarn_cost_per_kg", None)
    upd.update(material_fields.mirror_from_body(body, "default_material_cost_per_kg", cast=float, default=None))
    upd["updated_at"] = _now()
    upd["updated_by"] = user["id"]
    await db.rahaza_costing_settings.update_one({"id": SETTINGS_ID}, {"$set": upd}, upsert=True)
    out = await db.rahaza_costing_settings.find_one({"id": SETTINGS_ID}, {"_id": 0})
    return serialize_doc(material_fields.with_aliases(out or {}, "default_material_cost_per_kg"))


def mi_item_net_qty(item: dict) -> float:
    """Qty bahan yang benar-benar terpakai satu baris MI = keluar (cadangan: kebutuhan) − sudah diretur."""
    gross = float(item.get("qty_issued") or item.get("qty_required") or 0)
    return max(0.0, round(gross - float(item.get("qty_returned") or 0), 4))


COST_SOURCE_LABEL = {
    "issue": "biaya saat keluar",
    "master": "harga master",
    "default_estimate": "estimasi (harga bawaan pengaturan)",
    "missing": "harga belum ada",
}


def mi_item_cost_info(item: dict, mat: dict, default_kg: float, default_acc: float) -> tuple:
    """(harga satuan, sumber) bahan satu baris MI untuk HPP.

    Tahap 1 (6 Nov 2026): biaya SAAT KELUAR (`unit_cost_applied` baris MI, sama dengan jurnal
    pengeluaran bahan) yang dipakai — dulu harga master HARI INI, sehingga HPP job lama ikut
    berubah tiap harga bahan naik/turun. Harga master hanya untuk baris lama yang belum
    menyimpan biaya saat keluar; harga bawaan pengaturan hanya bila master pun kosong.

    Tahap 2 (6 Nov 2026): harga bawaan pengaturan tidak lagi dipakai DIAM-DIAM — sumbernya
    `default_estimate` (dilabeli estimasi); tanpa bawaan pun ⇒ `missing` ("harga belum ada")."""
    unit_cost = float((item or {}).get("unit_cost_applied") or 0)
    if unit_cost > 0:
        return unit_cost, "issue"
    unit_cost = float((mat or {}).get("unit_cost") or 0)
    if unit_cost > 0:
        return unit_cost, "master"
    # FASE 12 / BUG-B2: dulu `mat.get("type") == "yarn"` saja ⇒ material
    # `fabric`/`kain`/`benang`/`interlining` tanpa unit_cost memakai default
    # AKSESORIS (per unit), bukan default bahan (per kg) ⇒ HPP salah diam-diam.
    unit_cost = float(default_kg if material_fields.is_kglike_material(mat or {}) else default_acc)
    return (unit_cost, "default_estimate") if unit_cost > 0 else (0.0, "missing")


def mi_item_unit_cost(item: dict, mat: dict, default_kg: float, default_acc: float) -> float:
    """Harga satuan saja (pemanggil lama) — lihat `mi_item_cost_info`."""
    return mi_item_cost_info(item, mat, default_kg, default_acc)[0]


def job_mi_filter(job_id: str, vendor_shipment_id: str | None = None) -> dict:
    """MI yang membebani satu job. 2026-11-06 (Tahap 2): bahan yang keluar lewat Kirim Material
    CMT lahir SEBELUM job ada (`job_id` kosong) tetapi menyimpan `vendor_shipment_id`; job CMT
    menunjuk surat jalan yang sama (1 job : 1 surat jalan) ⇒ ikut dihitung."""
    ors = [{"job_id": job_id}, {"work_order_id": job_id}]
    if vendor_shipment_id:
        ors.append({"vendor_shipment_id": vendor_shipment_id})
    return {"$or": ors, "status": "issued"}


async def mi_material_cost(db, mi_rows: list, default_kg: float, default_acc: float) -> dict:
    """Biaya bahan dari MI: Σ (keluar − diretur) × harga (lihat `mi_item_cost_info`) + kekurangan."""
    mat_ids = list({i.get("material_id") for mi in mi_rows for i in (mi.get("items") or []) if i.get("material_id")})
    mat_map = {}
    if mat_ids:
        async for d in db.rahaza_materials.find({"id": {"$in": mat_ids}}, {"_id": 0}):
            mat_map[d["id"]] = d
    total, estimated, rows, gaps = 0.0, 0.0, [], []
    for mi in mi_rows:
        for item in (mi.get("items") or []):
            mat = mat_map.get(item.get("material_id")) or {}
            unit_cost, src = mi_item_cost_info(item, mat, default_kg, default_acc)
            # 2026-11-02 (K10): pemakaian = keluar − diretur (Retur Material mengisi `qty_returned`)
            qty = mi_item_net_qty(item)
            amount = qty * unit_cost
            total += amount
            name = mat.get("name") or item.get("material_name") or item.get("material_id")
            if src == "default_estimate":
                estimated += amount
                gaps.append(f"{name}: harga belum ada — dipakai harga bawaan pengaturan (estimasi)")
            elif src == "missing" and qty > 0:
                gaps.append(f"{name}: harga belum ada — biaya bahan baris ini Rp 0")
            rows.append({
                "material_id": item.get("material_id"), "material_name": name,
                "type": mat.get("type") or item.get("type"),
                "qty": qty, "qty_returned": float(item.get("qty_returned") or 0),
                "unit": item.get("unit") or mat.get("unit"),
                "unit_cost": unit_cost, "amount": round(amount),
                "cost_source": src, "cost_source_label": COST_SOURCE_LABEL[src],
                "mi_number": mi.get("mi_number") or "", "mi_source": mi.get("source") or "",
            })
    return {"material_cost": total, "estimated_cost": estimated, "breakdown": rows, "gaps": gaps}


async def job_cmt_wage(db, job_id: str) -> dict:
    """Upah CMT satu job = Σ qty jadi × tarif jahit SPK (`po_items.cmt_price_snapshot`).
    2026-11-06 (Tahap 2): dulu HPP aktual job tidak memuat upah CMT sama sekali."""
    items = await db.production_job_items.find({"job_id": job_id}, {"_id": 0}).to_list(2000)
    pi_ids = list({i.get("po_item_id") for i in items if i.get("po_item_id")})
    rates = {}
    if pi_ids:
        async for p in db.po_items.find({"id": {"$in": pi_ids}}, {"_id": 0, "id": 1, "cmt_price_snapshot": 1}):
            rates[p["id"]] = float(p.get("cmt_price_snapshot") or 0)
    total, rows, gaps = 0.0, [], []
    for i in items:
        qty = float(i.get("produced_qty") or 0)
        rate = rates.get(i.get("po_item_id"), 0.0)
        if qty > 0 and rate <= 0:
            gaps.append(f"{i.get('sku') or i.get('product_name') or 'item'}: tarif jahit SPK belum diisi")
        total += qty * rate
        rows.append({"sku": i.get("sku") or "", "qty": qty, "rate": rate, "amount": round(qty * rate)})
    return {"cmt_cost": total, "breakdown": rows, "gaps": gaps}


async def _compute_hpp(db, wo_id: str):
    from core.wo_reader import get_wo  # T-03: SSOT production_jobs
    wo = await get_wo(db, wo_id)
    if not wo:
        raise HTTPException(404, "Work order tidak ditemukan.")
    settings = await db.rahaza_costing_settings.find_one({"id": SETTINGS_ID}, {"_id": 0}) or {}
    default_yarn = float(material_fields.read_field(settings, "default_material_cost_per_kg", 0) or 0)
    default_acc = float(settings.get("default_accessory_cost_per_unit") or 0)
    overhead_rate = float(settings.get("overhead_rate_per_pcs") or 0)
    labor_fallback = float(settings.get("labor_rate_fallback_per_pcs") or 0)

    # ── 1) Material cost from confirmed material_issues for this WO
    # T-03: MI internal ter-anchor job_id. Tahap 2: + MI Kirim Material CMT (vendor_shipment_id job).
    job_doc = await db.production_jobs.find_one({"id": wo_id}, {"_id": 0, "vendor_shipment_id": 1}) or {}
    mi_rows = await db.rahaza_material_issues.find(
        job_mi_filter(wo_id, job_doc.get("vendor_shipment_id")), {"_id": 0}).to_list(500)
    mat_res = await mi_material_cost(db, mi_rows, default_yarn, default_acc)
    material_cost = mat_res["material_cost"]
    material_breakdown = mat_res["breakdown"]
    cmt = await job_cmt_wage(db, wo_id)

    # ── 2) Labor cost: sum of output events × rate for this WO
    wip = await db.rahaza_wip_events.find({"$or": [{"work_order_id": wo_id}, {"job_id": wo_id}], "event_type": {"$in": ["output", "complete"]}}, {"_id": 0}).to_list(500)  # T-03
    total_output = sum(int(e.get("qty") or 0) for e in wip)
    labor_cost = 0
    labor_breakdown = []
    # Group by operator → get their rate
    op_qty = {}
    for ev in wip:
        op_id = ev.get("operator_id")
        if not op_id:
            continue
        if op_id not in op_qty:
            op_qty[op_id] = {"qty": 0, "process_code": ev.get("process_code"), "process_id": ev.get("process_id")}
        op_qty[op_id]["qty"] += int(ev.get("qty") or 0)
    # Batch prefetch employees & payroll profiles for all unique op_ids
    op_ids = list(op_qty.keys())
    emp_map = {}
    profile_map = {}
    if op_ids:
        async for d in db.rahaza_employees.find({"id": {"$in": op_ids}}, {"_id": 0}):
            emp_map[d["id"]] = d
        async for d in db.rahaza_payroll_profiles.find(
            {"employee_id": {"$in": op_ids}, "active": True}, {"_id": 0}
        ):
            profile_map[d["employee_id"]] = d
    for op_id, info in op_qty.items():
        emp = emp_map.get(op_id) or {}
        profile = profile_map.get(op_id)
        rate = 0
        if profile and profile.get("pay_scheme") == "pcs":
            overrides = {r["process_id"]: r["rate"] for r in (profile.get("pcs_process_rates") or [])}
            rate = float(overrides.get(info["process_id"], profile.get("base_rate") or 0))
        if rate <= 0:
            rate = labor_fallback
        amount = info["qty"] * rate
        labor_cost += amount
        labor_breakdown.append({
            "operator_id": op_id, "operator_name": emp.get("name"),
            "process_code": info["process_code"], "process_id": info["process_id"], "qty": info["qty"], "rate": rate, "amount": round(amount),
        })
    
    # ── Group labor by process (Phase 3.1: breakdown per proses)
    labor_by_process = {}
    for lb in labor_breakdown:
        proc_id = lb.get("process_id")
        if proc_id not in labor_by_process:
            labor_by_process[proc_id] = {
                "process_id": proc_id,
                "process_code": lb.get("process_code"),
                "total_qty": 0,
                "total_cost": 0,
                "operators_count": 0,
            }
        labor_by_process[proc_id]["total_qty"] += lb["qty"]
        labor_by_process[proc_id]["total_cost"] += lb["amount"]
        labor_by_process[proc_id]["operators_count"] += 1
    
    labor_breakdown_by_process = list(labor_by_process.values())

    # ── 3) Overhead: overhead_rate × qty_completed (completed = output di proses final, simplifikasi pakai qty order)
    qty_completed = int(wo.get("qty_completed") or 0) or int(wo.get("qty") or 0)
    overhead_info = qty_completed * overhead_rate

    # 2026-11-06 (Tahap 2, keputusan owner): HPP = bahan + upah CMT. Upah internal (payroll) &
    # overhead tetap beban bulanan — dihitung sebagai INFORMASI, tidak masuk total.
    total_cost = material_cost + cmt["cmt_cost"]
    hpp_unit = total_cost / qty_completed if qty_completed > 0 else 0

    return {
        "work_order_id": wo_id,
        "wo_number": wo.get("wo_number"),
        "model_code": wo.get("model_code"),
        "size_code": wo.get("size_code"),
        "qty": wo.get("qty"),
        "qty_completed": qty_completed,
        "total_output_events": total_output,
        "material_cost": round(material_cost),
        "material_cost_estimated": round(mat_res["estimated_cost"]),
        "cmt_cost": round(cmt["cmt_cost"]),
        "labor_cost": round(cmt["cmt_cost"]),          # nama lama: kini = upah CMT (yang masuk HPP)
        "internal_labor_cost": round(labor_cost), "internal_labor_in_hpp": False,
        "overhead_cost": 0, "overhead_info": round(overhead_info), "overhead_in_hpp": False,
        "total_cost": round(total_cost),
        "hpp_unit": round(hpp_unit),
        "material_breakdown": material_breakdown,
        "cmt_breakdown": cmt["breakdown"],
        "labor_breakdown": labor_breakdown,
        "labor_breakdown_by_process": labor_breakdown_by_process,
        "overhead_rate_per_pcs": overhead_rate,
        "gaps": mat_res["gaps"] + cmt["gaps"],
        "computed_at": _now().isoformat(),
    }


@router.get("/hpp/snapshots")
async def list_snapshots(request: Request):
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_hpp_snapshots.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return serialize_doc(rows)


# ══════════════════════════════════════════════════════════════════════════════
# NEW ENDPOINTS — GAP #6: HPP Aktual (Maklon, PO, Client Analysis)
# Phase 3.2: Snapshot endpoints for PO and Maklon Order
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/hpp/maklon-order/{order_id}/snapshot")
async def snapshot_hpp_maklon_order(order_id: str, request: Request):
    await _require_fin(request)  # FIN-04
    """
    Simpan snapshot HPP maklon order untuk audit trail.
    Collection: dewi_hpp_snapshots_maklon
    """
    user = await require_auth(request)
    db = get_db()
    
    # Compute current HPP
    order = await _lmo(db).find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "Maklon order tidak ditemukan.")
    
    # Reuse logic from hpp_for_maklon_order (simplified call)
    # For now, we'll just store the order_id and timestamp
    # In production, you'd compute full HPP and store it
    snapshot_data = {
        "id": _uid(),
        "order_id": order_id,
        "order_code": order.get("order_code", ""),
        "snapshot_type": "maklon_order",
        "created_at": _now(),
        "created_by": user.get("email", ""),
        # Add computed HPP data here (material, labor, overhead, total)
        "note": "Snapshot HPP maklon order untuk audit"
    }
    
    await db.dewi_hpp_snapshots_maklon.insert_one(snapshot_data)
    return serialize_doc({"message": "Snapshot HPP maklon order tersimpan", "snapshot_id": snapshot_data["id"]})


@router.post("/hpp/production-po/{po_id}/snapshot")
async def snapshot_hpp_production_po(po_id: str, request: Request):
    await _require_fin(request)  # FIN-04
    """
    Simpan snapshot HPP production PO untuk audit trail.
    Collection: dewi_hpp_snapshots_po
    """
    user = await require_auth(request)
    db = get_db()
    
    # Compute current HPP
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "Production PO tidak ditemukan.")
    
    snapshot_data = {
        "id": _uid(),
        "po_id": po_id,
        "po_number": po.get("po_number", ""),
        "snapshot_type": "production_po",
        "created_at": _now(),
        "created_by": user.get("email", ""),
        "note": "Snapshot HPP production PO untuk audit"
    }
    
    await db.dewi_hpp_snapshots_po.insert_one(snapshot_data)
    return serialize_doc({"message": "Snapshot HPP production PO tersimpan", "snapshot_id": snapshot_data["id"]})


@router.get("/hpp/snapshots/maklon")
async def list_maklon_snapshots(request: Request):
    """List semua snapshot HPP maklon orders"""
    await require_auth(request)
    db = get_db()
    rows = await db.dewi_hpp_snapshots_maklon.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return serialize_doc(rows)


@router.get("/hpp/snapshots/po")
async def list_po_snapshots(request: Request):
    """List semua snapshot HPP production POs"""
    await require_auth(request)
    db = get_db()
    rows = await db.dewi_hpp_snapshots_po.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return serialize_doc(rows)


# ══════════════════════════════════════════════════════════════════════════════
# Tahap 9 (keputusan owner 7 Nov 2026 No. 6 & 13) — SATU "HPP per PO" untuk PO internal & maklon.
# Semua angka dari `core.hpp_aktual` (data nyata: potongan + aksesoris diserahkan + upah CMT + permak).
# Endpoint lama di bawah (order maklon, PO produksi, per klien, unduhan) MENDELEGASIKAN ke hitungan yang sama.
# ══════════════════════════════════════════════════════════════════════════════
from core import hpp_aktual as _ha  # noqa: E402


async def _read_hpp(request: Request) -> dict:
    """Baca HPP: login, bukan klien maklon, bukan vendor CMT (HPP = data internal DA/Sukma)."""
    user = await require_auth(request)
    from routes.production_rbac import deny_klien, is_vendor
    deny_klien(user)
    if is_vendor(user):
        raise HTTPException(403, "Vendor CMT tidak punya akses ke HPP.")
    return user


def _bt_query(business_type: str) -> dict:
    """Saringan jenis PO (aturan bersama layar PO): internal = 'internal', maklon = bukan 'internal'."""
    bt = (business_type or "").strip().lower()
    if bt == "internal":
        return {"business_type": "internal"}
    if bt == "maklon":
        return {"business_type": {"$ne": "internal"}}
    return {}


def _day(s: str, *, end: bool = False):
    try:
        d = datetime.strptime(str(s)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    if end:
        from datetime import timedelta
        d = d + timedelta(days=1)
    return d


def _po_query(business_type: str, search: str, date_from: str, date_to: str, client_id: str) -> dict:
    q: dict = {"status": {"$nin": list(_ha.PO_HIDDEN_STATUSES)}, **_bt_query(business_type)}
    if search:
        rx = {"$regex": search.strip(), "$options": "i"}
        q["$or"] = [{"po_number": rx}, {"customer_name": rx}, {"vendor_name": rx}]
    rng = {}
    if _day(date_from):
        rng["$gte"] = _day(date_from)
    if _day(date_to, end=True):
        rng["$lt"] = _day(date_to, end=True)
    if rng:
        q["po_date"] = rng
    if client_id:
        q["buyer_id"] = client_id
    return q


def _list_row(fig: dict) -> dict:
    row = {k: v for k, v in fig.items() if k not in ("lines", "issue_lines")}
    row["line_count"] = len(fig.get("lines") or [])
    return row


def _summary(figs: list, business_type: str) -> dict:
    tot = sum(f["total_hpp"] for f in figs)
    pcs = sum(f["qty_accepted"] for f in figs)
    absorbed = sum(f["absorbed_cost"] for f in figs if f["qty_accepted"])
    out = {"po_count": len(figs), "total_hpp": round(tot, 2), "qty_accepted": int(pcs),
           "hpp_per_pcs": round(absorbed / pcs, 2) if pcs else None,
           "unabsorbed_cost": round(sum(f["unabsorbed_cost"] for f in figs if f.get("business_type") == "internal"), 2),
           "missing_rate_pos": sum(1 for f in figs if f.get("items_missing_rate"))}
    mk = [f for f in figs if f.get("business_type") == "maklon"]
    if mk:
        rev = sum(f["revenue"] for f in mk)
        cost = sum(f["total_hpp"] for f in mk)
        # 8 Nov 2026: margin terealisasi = pendapatan − biaya pcs yang sudah dikirim ke klien (dasar sepadan);
        # `margin` lama (pendapatan − total biaya sampai saat ini) tetap dikirim untuk pemanggil lama.
        realized = sum(f.get("realized_cost") or 0 for f in mk)
        out.update({"revenue": round(rev, 2), "margin": round(rev - cost, 2),
                    "margin_pct": round((rev - cost) / rev * 100, 2) if rev else None,
                    "cost_to_date": round(cost, 2), "realized_cost": round(realized, 2),
                    "margin_realized": round(rev - realized, 2),
                    "margin_realized_pct": round((rev - realized) / rev * 100, 2) if rev else None})
    return out


@router.get("/hpp/po")
async def hpp_po_list(request: Request, business_type: str = "", search: str = "", status: str = "",
                      date_from: str = "", date_to: str = "", client_id: str = "",
                      page: int = 1, per_page: int = 25):
    """Daftar HPP aktual per PO (satu layar untuk Portal Produksi & Maklon, disaring jenis PO)."""
    await _read_hpp(request)
    db = get_db()
    base = _po_query(business_type, search, date_from, date_to, client_id)
    closed = list(_ha.CLOSED_STATUSES)
    counts = {"all": await db.production_pos.count_documents(base),
              "closed": await db.production_pos.count_documents({**base, "status": {"$in": closed}})}
    counts["open"] = counts["all"] - counts["closed"]
    q = dict(base)
    if status == "closed":
        q["status"] = {"$in": closed}
    elif status == "open":
        q["status"] = {"$nin": list(_ha.PO_HIDDEN_STATUSES) + closed}
    per_page = max(5, min(int(per_page or 25), 100))
    page = max(1, int(page or 1))
    pos = await db.production_pos.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    figs = await _ha.po_hpp_many(db, pos, with_overhead=False)
    paged = figs[(page - 1) * per_page: page * per_page]
    accs = await _ha.overhead_accounts(db)
    cache: dict = {}
    for f in paged:
        f["overhead_info"] = await _ha._po_overhead(db, f, accs, cache)
    month = (str(date_to)[:7] if _day(date_to) else datetime.now(timezone.utc).strftime("%Y-%m"))
    bt = "maklon" if (business_type or "").lower() == "maklon" else "internal"
    return serialize_doc({
        "items": [_list_row(f) for f in paged], "total": len(figs), "page": page, "per_page": per_page,
        "counts": counts, "summary": _summary(figs, business_type),
        "overhead": await _ha.overhead_month(db, month, bt, accounts=accs),
        "capped": len(pos) >= 500,
    })


@router.get("/hpp/po/{po_id}")
async def hpp_po_detail(po_id: str, request: Request):
    """Rincian HPP aktual satu PO: komponen, per baris (aktual vs standar BOM), penyerahan bahan, upah CMT,
    biaya umum per pcs (informasi) dan — PO internal — posisi WIP / selisih saat ditutup."""
    await _read_hpp(request)
    fig = await _ha.po_hpp(get_db(), po_id, detail=True)
    if not fig:
        raise HTTPException(404, "PO tidak ditemukan.")
    return serialize_doc(fig)


@router.get("/hpp/overhead-info")
async def hpp_overhead_info(request: Request, month: str = "", business_type: str = "internal"):
    """Biaya umum produksi per pcs satu bulan (informasi, TIDAK masuk HPP)."""
    await _read_hpp(request)
    ym = month[:7] if (len(month) >= 7 and month[4] == "-") else datetime.now(timezone.utc).strftime("%Y-%m")
    return serialize_doc(await _ha.overhead_month(get_db(), ym, business_type))


# ── endpoint lama → hitungan yang sama ────────────────────────────────────────
@router.get("/hpp/maklon-order/{order_id}")
async def hpp_for_maklon_order(order_id: str, request: Request):
    """LAMA (HPP aktual order maklon). Tahap 9: dulu membaca `dewi_maklon_material_issues` yang tidak ditulis
    lagi; kini = HPP per PO (`core.hpp_aktual`). Kunci lama dipertahankan untuk pemanggil lama."""
    await _read_hpp(request)
    db = get_db()
    fig = await _ha.po_hpp(db, order_id, detail=False)
    if not fig:
        raise HTTPException(404, "Maklon order tidak ditemukan.")
    material = round(fig["cut_cost"] + fig["accessory_cost"], 2)
    return serialize_doc({
        "order_id": order_id, "order_code": fig["po_number"], "client_name": fig["client_name"],
        "product_name": (fig["lines"][0]["product_name"] if fig["lines"] else ""),
        "qty_ordered": fig["qty_ordered"], "qty_completed": fig["qty_accepted"],
        "material_cost_actual": material, "cmt_cost_actual": fig["cmt_cost"], "permak_cost_actual": fig["permak_cost"],
        "labor_cost_actual": 0, "labor_in_hpp": False, "overhead_cost_actual": 0, "overhead_in_hpp": False,
        "total_cost_actual": fig["total_hpp"], "hpp_unit_actual": fig["hpp_per_pcs"] or 0,
        "estimated_hpp_total": None, "estimated_hpp_unit": None, "delta_unit": None, "delta_pct": None,
        "material_breakdown": fig["issue_lines"], "labor_breakdown": [], "labor_breakdown_by_process": [],
        "hpp": _list_row(fig), "source": "hpp_per_po", "computed_at": _now().isoformat(),
    })


@router.get("/hpp/production-po/{po_id}")
async def hpp_for_production_po(po_id: str, request: Request):
    """LAMA (HPP per PO produksi = Σ HPP job). Tahap 9: = HPP per PO (`core.hpp_aktual`)."""
    await _read_hpp(request)
    fig = await _ha.po_hpp(get_db(), po_id, detail=False)
    if not fig:
        raise HTTPException(404, "Production PO tidak ditemukan.")
    return serialize_doc({
        "po_id": po_id, "po_number": fig["po_number"], "customer_name": fig["client_name"], "status": fig["status"],
        "total_cost_actual": fig["total_hpp"], "total_cost_estimated": None, "delta_total": None, "delta_pct": None,
        "hpp_per_pcs": fig["hpp_per_pcs"], "components": fig["components"], "lines": fig["lines"],
        "wo_count": 0, "wo_breakdown": [], "source": "hpp_per_po", "computed_at": _now().isoformat(),
    })


async def maklon_order_figures(db, order: dict) -> dict:
    """Angka NYATA satu order maklon untuk analisa/unduhan per klien. Tahap 9: dari HPP per PO (dulu
    `dewi_maklon_material_issues` yang tidak ditulis lagi; HPP & margin "belum ada data")."""
    fig = await _ha.po_hpp(db, (order or {}).get("id"), detail=False)
    if not fig:
        qty = int((order or {}).get("qty_ordered") or 0)
        return {"qty": qty, "revenue": 0.0, "material_cost": 0.0, "hpp_estimated": None, "hpp_actual": None,
                "margin": None}
    return {"qty": fig["qty_ordered"], "revenue": fig["revenue"],
            "material_cost": round(fig["cut_cost"] + fig["accessory_cost"], 2), "hpp_estimated": None,
            "hpp_actual": fig["total_hpp"], "margin": fig["margin"], "hpp_per_pcs": fig["hpp_per_pcs"],
            "margin_per_pcs": fig["margin_per_pcs"]}


@router.get("/hpp/maklon-client/{client_id}")
async def hpp_for_maklon_client(client_id: str, request: Request):
    """LAMA — ringkasan per klien maklon. Tahap 9: PO maklon klien ini (`production_pos.buyer_id`) dengan HPP
    per PO yang sama. Saringan: date_from, date_to (tanggal PO), status (koma), page, limit."""
    await _read_hpp(request)
    db = get_db()
    client = await db.dewi_maklon_clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Klien maklon tidak ditemukan.")
    sp = request.query_params
    page = max(1, int(sp.get("page", 1) or 1))
    limit = max(1, min(int(sp.get("limit", 50) or 50), 200))
    q = _po_query("maklon", "", sp.get("date_from") or "", sp.get("date_to") or "", client_id)
    statuses = [s.strip() for s in (sp.get("status") or "").split(",") if s.strip()]
    if statuses:
        q["status"] = {"$in": statuses}
    total_count = await db.production_pos.count_documents(q)
    pos = await db.production_pos.find(q, {"_id": 0}).sort("po_date", -1).to_list(500)
    pos = pos[(page - 1) * limit: page * limit]
    figs = await _ha.po_hpp_many(db, pos, with_overhead=False)
    orders, on_time, late = [], 0, 0
    for po, f in zip(pos, figs):
        deadline, done_at = po.get("deadline"), po.get("closed_at")
        try:
            ok = bool(deadline and done_at and done_at <= deadline)
        except TypeError:          # tanggal campuran (dengan/tanpa zona waktu) — tidak dinilai
            ok, deadline = False, None
        if f["closed"] and deadline and done_at:
            on_time += ok
            late += not ok
        orders.append({"order_id": po["id"], "order_code": f["po_number"],
                       "product_name": (f["lines"][0]["product_name"] if f["lines"] else ""),
                       "qty": f["qty_ordered"], "status": po.get("status", ""), "revenue": f["revenue"],
                       "material_cost": round(f["cut_cost"] + f["accessory_cost"], 2), "hpp_estimated": None,
                       "hpp_actual": f["total_hpp"], "hpp_per_pcs": f["hpp_per_pcs"], "margin": f["margin"],
                       "is_on_time": ok if (deadline and done_at) else None,
                       "deadline_date": deadline, "completion_date": done_at})
    rev = sum(o["revenue"] for o in orders)
    hpp = sum(o["hpp_actual"] for o in orders)
    total_pages = (total_count + limit - 1) // limit if limit else 1
    return serialize_doc({
        "client_id": client_id, "client_code": client.get("code", ""), "client_name": client.get("name", ""),
        "total_orders": len(orders), "total_qty": sum(o["qty"] for o in orders), "total_revenue": round(rev, 2),
        "total_material_cost": round(sum(o["material_cost"] for o in orders), 2),
        "total_hpp_estimated": None, "total_hpp_actual": round(hpp, 2), "margin_amount": round(rev - hpp, 2),
        "margin_pct": round((rev - hpp) / rev * 100, 2) if rev else None,
        "on_time_count": on_time, "late_count": late,
        "on_time_rate": round(on_time / (on_time + late) * 100, 2) if (on_time + late) else 0,
        "orders": orders,
        "pagination": {"page": page, "limit": limit, "total_count": total_count, "total_pages": total_pages,
                       "has_next": page < total_pages, "has_prev": page > 1},
        "source": "hpp_per_po", "computed_at": _now().isoformat(),
    })
