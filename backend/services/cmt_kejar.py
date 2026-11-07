"""
services/cmt_kejar.py — READ-ONLY agregasi "KEJAR CMT" + Dashboard Owner CMT.

Semua dihitung dari rantai SSOT (INVARIANTS MCS-01/03/04/05/06):
  production_pos/po_items · vendor_shipments/vendor_shipment_items · cmt_receipts/cmt_receipt_lines
  · dewi_cmt_permak · dewi_cmt_component_requests
TIDAK menulis koleksi apa pun. TIDAK membaca vendor_jobs/wh_cmt_dispatches (hindari split-brain).

Konsep:
- Target CMT (M4) = delivery_deadline − buffer_days (config maklon_cmt_buffer_days). Fallback: deadline internal.
- Bucket keterlambatan (S3): aman | on_track | mendekati | jatuh_tempo | telat(H+late_grace) | tanpa_deadline.
- Sisa di CMT (M5) = Σqty_sent(kiriman NORMAL) − Σqty_returned(cmt_receipt_lines approved).
- Kali setor (M5) = jumlah cmt_receipts Approved untuk PO.
- Ongkos jahit terhitung (M2) = Σ(cmt_price_snapshot × qty_accepted).

POTONGAN HARUS SESUAI ORDER (keluhan pemilik 2026-06, INV-F28)
--------------------------------------------------------------
Dulu "Potongan ke CMT" menjumlahkan SEMUA `vendor_shipment_items` milik PO tanpa
memandang jenis surat jalannya, jadi kiriman PENGGANTI/TAMBAHAN (surat jalan ANAK
hasil persetujuan permintaan material) ikut ditambahkan. Akibatnya potongan yang
dilaporkan MELEBIHI qty order (mis. order 100 → tertulis 105) dan "Sisa di CMT"
memunculkan sisa HANTU walau CMT sudah menyetor semuanya.
Sekarang:
  · `qty_sent_cmt`   = hanya kiriman **NORMAL** (potongan sesuai order),
  · `qty_sent_extra` = kiriman anak (pengganti/tambahan/permak) — DILAPORKAN
    TERPISAH, tidak dihilangkan, dengan rincian per jenis.
Ditambah dua angka yang diminta pemilik dan dua sudut pandang PO:
  · `qty_not_sent_cmt`  = order − terkirim NORMAL (masih di gudang; PO Draft
    otomatis terhitung penuh karena belum mengirim apa pun),
  · `qty_shipped_buyer` = sudah dikirim ke buyer, dari SSOT `core.dispatch_capacity`
    (rumus yang sama dengan pagar dispatch — bukan rumus kedua),
  · `scope=running` (default) membuang PO Completed/Closed/Cancelled;
    `scope=all` menghitung semuanya.
"""
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import logging

from core.cmt_receipt_status import (ST_DONE as _RC_DONE,
                                    canon_status_filter as _rc_filter)
from utils.waktu import today_wib

_log = logging.getLogger(__name__)

COMPONENT_OPEN_STATUSES = ("pending", "cutting", "ready")  # belum diterima

# Status PO yang dianggap SUDAH SELESAI (tidak berjalan lagi). Ditulis huruf kecil,
# dibandingkan case-insensitive supaya data lama ikut kena.
PO_DONE_STATUSES = {"completed", "complete", "done", "finished", "selesai",
                    "closed", "cancelled", "canceled", "batal", "archived"}
PO_DRAFT_STATUSES = {"draft", "rancangan"}
SCOPE_RUNNING, SCOPE_ALL = "running", "all"


def _po_status(po: Dict[str, Any]) -> str:
    return str(po.get("status") or "").strip().lower()


def is_running_po(po: Dict[str, Any]) -> bool:
    return _po_status(po) not in PO_DONE_STATUSES


def is_draft_po(po: Dict[str, Any]) -> bool:
    return _po_status(po) in PO_DRAFT_STATUSES


def shipment_kind(ship: Dict[str, Any] | None, item: Dict[str, Any] | None = None) -> str:
    """NORMAL vs kiriman anak (REPLACEMENT/ADDITIONAL/REWORK).

    Surat jalan anak dikenali dari `parent_shipment_id` ATAU `shipment_type`; item
    dipakai sebagai lapis kedua karena `vendor_shipment_items` juga menyimpan
    `shipment_type`/`parent_shipment_id` (mis. saat induknya sudah dihapus).
    """
    s = ship or {}
    it = item or {}
    t = str(s.get("shipment_type") or it.get("shipment_type") or "").strip().upper()
    has_parent = bool(s.get("parent_shipment_id") or it.get("parent_shipment_id"))
    if t and t != "NORMAL":
        return t
    if has_parent:
        return "REPLACEMENT"   # bertanda NORMAL tapi punya induk → tetap kiriman anak
    return "NORMAL"


def _int(v) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return 0


def _to_date(v) -> Optional[date]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


async def get_buffer_config(db) -> Dict[str, int]:
    async def _c(key, default):
        try:
            d = await db.dewi_system_config.find_one({"key": key}, {"_id": 0, "value": 1})
            return int(d["value"]) if d and d.get("value") is not None else default
        except Exception:
            # F13 — buffer & tenggang inilah yang menentukan bucket "telat" di
            # papan KEJAR CMT. Diam-diam memakai default berarti seluruh papan
            # bisa memakai aturan yang bukan pilihan owner tanpa satu pun tanda.
            _log.warning("[cmt-kejar] config '%s' tidak terbaca — memakai default %s",
                         key, default, exc_info=True)
            return default
    return {
        "buffer_days": await _c("maklon_cmt_buffer_days", 3),
        "late_grace_days": await _c("maklon_cmt_late_grace_days", 5),
    }


async def _approved_receipt_ids(db, po_id: str) -> List[str]:
    docs = await db.cmt_receipts.find(
        {"po_id": po_id, "status": _rc_filter(_RC_DONE)}, {"_id": 0, "id": 1}
    ).to_list(None)
    return [d["id"] for d in docs if d.get("id")]


def _bucket(outstanding_cmt: int, target: Optional[date], today: date, late_grace: int) -> Dict[str, Any]:
    if outstanding_cmt <= 0:
        return {"bucket": "aman", "overdue_days": 0, "days_to_target": None}
    if target is None:
        return {"bucket": "tanpa_deadline", "overdue_days": None, "days_to_target": None}
    overdue = (today - target).days
    to_target = (target - today).days
    if overdue > late_grace:
        b = "telat"
    elif overdue >= 0:
        b = "jatuh_tempo"
    elif to_target <= 3:
        b = "mendekati"
    else:
        b = "on_track"
    return {"bucket": b, "overdue_days": overdue, "days_to_target": to_target}


async def caps_for_pos(db, pos: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Peta kapasitas kirim (SSOT `core.dispatch_capacity`) untuk SEMUA item PO
    sekaligus — supaya papan & kartu memakai rumus yang sama dengan pagar dispatch
    tanpa memanggil ulang per PO."""
    po_ids = [p["id"] for p in pos if p.get("id")]
    if not po_ids:
        return {}
    items = await db.po_items.find({"po_id": {"$in": po_ids}}, {"_id": 0, "id": 1}).to_list(None)
    ids = [i["id"] for i in items if i.get("id")]
    if not ids:
        return {}
    from core import dispatch_capacity as dcap
    rows = await dcap.by_po_items(db, ids)
    return {r["key"]: r for r in rows}


async def compute_po_kejar(db, po: Dict[str, Any], cfg: Dict[str, int], today: date = None,
                           caps: Dict[str, Dict[str, Any]] | None = None,
                           totals: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Satu baris papan Kejar CMT. Angka qty = jumlah baris PO (`core.pantau_produksi`); `totals` boleh
    diberikan pemanggil yang sudah menghitung semua PO sekaligus (`caps` diabaikan — warisan)."""
    today = today or today_wib()
    po_id = po["id"]
    if totals is None:
        totals = (await _totals_by_po(db, [po])).get(po_id) or {}
    t = totals
    first = _to_date(t.get("first_sent"))

    delivery_deadline = _to_date(po.get("delivery_deadline"))   # Deadline Mitra/Buyer
    internal_deadline = _to_date(po.get("deadline"))
    base_deadline = delivery_deadline or internal_deadline
    target_cmt = None
    if base_deadline:
        from datetime import timedelta
        target_cmt = base_deadline - timedelta(days=cfg["buffer_days"])

    outstanding_cmt = _int(t.get("di_cmt"))
    b = _bucket(outstanding_cmt, target_cmt, today, cfg["late_grace_days"])
    days_at_cmt = (today - first).days if (first and outstanding_cmt > 0) else None
    from core import pantau_produksi as pp

    return {
        "po_id": po_id,
        "po_number": po.get("po_number", ""),
        "customer_name": po.get("customer_name", ""),
        "vendor_id": po.get("vendor_id", ""),
        "vendor_name": po.get("vendor_name", ""),
        "business_type": pp.bt_of(po),
        "status": po.get("status", ""),
        "qty_ordered": _int(t.get("ordered")),
        "qty_sent_cmt": _int(t.get("sent_cmt")),          # HANYA kiriman NORMAL (sesuai order)
        "qty_sent_extra": _int(t.get("sent_extra")),      # pengganti/tambahan (terpisah)
        "qty_sent_extra_by_type": dict(t.get("sent_extra_by_type") or {}),
        "qty_not_sent_cmt": _int(t.get("not_sent")),      # masih di gudang
        "qty_shipped_buyer": _int(t.get("dispatched")),   # sudah dikirim ke klien / diserahkan ke gudang
        "qty_shippable_buyer": _int(t.get("shippable")),  # sisa bisa kirim
        "is_draft": is_draft_po(po),
        "is_running": is_running_po(po),
        "qty_returned": _int(t.get("returned")),          # disetor CMT (penerimaan selesai QC)
        "qty_in_qc": _int(t.get("in_qc")),                # sudah di DA, sedang QC
        "qty_reject": _int(t.get("reject")),
        "qty_repaired": _int(t.get("repaired")),
        "qty_scrap": _int(t.get("scrap")),
        "qty_reject_open": _int(t.get("reject_open")),
        "qty_short_open": _int(t.get("cmt_short_open")),
        "qty_accepted": _int(t.get("accepted")),
        "qty_outstanding_cmt": outstanding_cmt,           # sisa di CMT
        "kali_setor": _int(t.get("receipt_count")),
        "ongkos_jahit_terhitung": round(float(t.get("cmt_cost") or 0), 2),
        "delivery_deadline": delivery_deadline.isoformat() if delivery_deadline else None,
        "internal_deadline": internal_deadline.isoformat() if internal_deadline else None,
        "target_cmt_date": target_cmt.isoformat() if target_cmt else None,
        "earliest_dispatch_date": first.isoformat() if first else None,
        "days_at_cmt": days_at_cmt,
        **b,
    }


async def _totals_by_po(db, pos: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Jumlah baris PO per PO — semua PO sekaligus (satu putaran kueri, `core.pantau_produksi`)."""
    from core import pantau_produksi as pp
    lines = await pp.po_lines(db, pos)
    by: Dict[str, list] = {}
    for ln in lines:
        by.setdefault(ln["po_id"], []).append(ln)
    out = {}
    for p in pos:
        ls = by.get(p["id"], [])
        t = pp.sum_lines(ls)
        firsts = [ln["first_sent"] for ln in ls if ln.get("first_sent")]
        t["first_sent"] = min(firsts) if firsts else None
        out[p["id"]] = t
    return out


async def _maklon_pos(db, scope: str = SCOPE_RUNNING, business_type: Optional[str] = "maklon") -> List[Dict[str, Any]]:
    """PO menurut sudut pandang yang dipilih pemakai.

    `scope='running'` (default) = PO yang MASIH BERJALAN: Draft · Confirmed ·
    Distributed · In Production. PO **Completed**/Closed/Cancelled dibuang —
    dulu hanya `Closed/Cancelled/Selesai` yang dibuang sehingga PO yang sudah
    selesai tetap menggelembungkan seluruh kartu (keluhan pemilik, INV-F28).
    `scope='all'` = semua PO. Tahap 9: `business_type` 'maklon' (= bukan internal, bawaan lama),
    'internal', atau 'all'.
    """
    from core import pantau_produksi as pp
    pos = await db.production_pos.find(
        pp.bt_filter(business_type), {"_id": 0}).sort("created_at", -1).to_list(500)
    if scope == SCOPE_ALL:
        return pos
    return [p for p in pos if is_running_po(p)]


def _norm_scope(scope: Optional[str]) -> str:
    """Hanya dua kosakata: 'running' (default) dan 'all'/'semua'."""
    return SCOPE_ALL if str(scope or "").strip().lower() in ("all", "semua") else SCOPE_RUNNING


async def list_kejar(db, bucket: Optional[str] = None, only_open: bool = True,
                     scope: Optional[str] = None, business_type: Optional[str] = "maklon") -> Dict[str, Any]:
    scope = _norm_scope(scope if scope is not None else (SCOPE_RUNNING if only_open else SCOPE_ALL))
    cfg = await get_buffer_config(db)
    today = today_wib()
    pos = await _maklon_pos(db, scope, business_type)
    totals = await _totals_by_po(db, pos)
    rows = []
    for po in pos:
        r = await compute_po_kejar(db, po, cfg, today, totals=totals.get(po["id"]))
        if bucket and r["bucket"] != bucket:
            continue
        rows.append(r)
    order = {"telat": 0, "jatuh_tempo": 1, "mendekati": 2, "on_track": 3, "tanpa_deadline": 4, "aman": 5}
    rows.sort(key=lambda r: (order.get(r["bucket"], 9), -(r["overdue_days"] or -999)))
    return {"config": cfg, "scope": scope, "business_type": business_type or "all",
            "count": len(rows), "rows": rows}


async def owner_dashboard(db, scope: Optional[str] = None, business_type: Optional[str] = "maklon") -> Dict[str, Any]:
    """M2 — KPI Dashboard Owner CMT (agregasi PO menurut scope & jenis PO)."""
    scope = _norm_scope(scope)
    cfg = await get_buffer_config(db)
    today = today_wib()
    pos = await _maklon_pos(db, scope, business_type)
    totals = await _totals_by_po(db, pos)

    agg = {
        "scope": scope,
        "total_po": len(pos),
        "po_draft": 0,
        "qty_ordered": 0, "qty_sent_cmt": 0, "qty_returned": 0, "qty_accepted": 0,
        "qty_outstanding_cmt": 0, "kali_setor": 0, "ongkos_jahit_terhitung": 0.0,
        "qty_sent_extra": 0, "qty_sent_extra_by_type": {},
        "qty_not_sent_cmt": 0, "qty_not_sent_draft": 0,
        "qty_shipped_buyer": 0, "qty_shippable_buyer": 0,
        "qty_reject": 0, "qty_repaired": 0, "qty_scrap": 0,
        "qty_reject_open": 0, "qty_short_open": 0, "qty_in_qc": 0,
        "buckets": {"telat": 0, "jatuh_tempo": 0, "mendekati": 0, "on_track": 0, "aman": 0, "tanpa_deadline": 0},
        "telat_pos": [],
    }
    po_rows_bal = []
    for po in pos:
        r = await compute_po_kejar(db, po, cfg, today, totals=totals.get(po["id"]))
        po_rows_bal.append({"po_id": po["id"], "po_number": r["po_number"], **(totals.get(po["id"]) or {})})
        for k in ("qty_reject", "qty_repaired", "qty_scrap", "qty_reject_open",
                  "qty_short_open", "qty_in_qc"):
            agg[k] += r[k]
        agg["qty_ordered"] += r["qty_ordered"]
        agg["qty_sent_cmt"] += r["qty_sent_cmt"]
        agg["qty_returned"] += r["qty_returned"]
        agg["qty_accepted"] += r["qty_accepted"]
        agg["qty_outstanding_cmt"] += r["qty_outstanding_cmt"]
        agg["kali_setor"] += r["kali_setor"]
        agg["ongkos_jahit_terhitung"] += r["ongkos_jahit_terhitung"]
        agg["qty_sent_extra"] += r["qty_sent_extra"]
        for k, v in (r.get("qty_sent_extra_by_type") or {}).items():
            agg["qty_sent_extra_by_type"][k] = agg["qty_sent_extra_by_type"].get(k, 0) + v
        agg["qty_not_sent_cmt"] += r["qty_not_sent_cmt"]
        agg["qty_shipped_buyer"] += r["qty_shipped_buyer"]
        agg["qty_shippable_buyer"] += r["qty_shippable_buyer"]
        if r.get("is_draft"):
            agg["po_draft"] += 1
            agg["qty_not_sent_draft"] += r["qty_not_sent_cmt"]
        agg["buckets"][r["bucket"]] = agg["buckets"].get(r["bucket"], 0) + 1
        if r["bucket"] == "telat":
            agg["telat_pos"].append({
                "po_id": r["po_id"], "po_number": r["po_number"], "customer_name": r["customer_name"],
                "overdue_days": r["overdue_days"], "qty_outstanding_cmt": r["qty_outstanding_cmt"],
                "target_cmt_date": r["target_cmt_date"],
            })
    agg["ongkos_jahit_terhitung"] = round(agg["ongkos_jahit_terhitung"], 2)

    # Komponen kurang (aksesoris) belum diterima — hanya PO dalam cakupan (Tahap 9)
    po_ids = [p["id"] for p in pos]
    comp = await db.dewi_cmt_component_requests.find(
        {"status": {"$in": list(COMPONENT_OPEN_STATUSES)}, "po_id": {"$in": po_ids}}, {"_id": 0}
    ).to_list(None) if po_ids else []
    comp_qty = 0
    for c in comp:
        for it in (c.get("items") or []):
            comp_qty += _int(it.get("qty"))
    agg["komponen_kurang_open"] = {"requests": len(comp), "qty": comp_qty}

    # Biaya permak + permak aktif — hanya PO dalam cakupan (Tahap 9)
    permaks = await db.dewi_cmt_permak.find({"po_id": {"$in": po_ids}}, {"_id": 0}).to_list(None) if po_ids else []
    biaya_permak = round(sum(float(p.get("total_cost") or 0) for p in permaks), 2)
    permak_open = sum(1 for p in permaks if p.get("status") in ("open", "in_progress"))
    agg["biaya_permak"] = biaya_permak
    agg["permak_open"] = permak_open

    # ── PEMERIKSA KESEIMBANGAN — satu definisi dengan Pantau Produksi (core.pantau_produksi) ──
    # Kalau satu identitas pecah, PO penyebabnya disebut namanya supaya bisa langsung diperiksa.
    from core import pantau_produksi as pp
    bal = pp.balance_checks(po_rows_bal, limit=12)
    for c in bal["checks"]:
        c["offenders"] = [o["po_number"] for o in c["offenders"]]
    agg["balance"] = bal
    agg["business_type"] = business_type or "all"

    agg["config"] = cfg
    return agg
