"""core/wo_reader.py — SATU pembaca "Work Order" di atas `production_jobs` (FASE 3 / T-03).

Koleksi `rahaza_work_orders` (engine multi-stage lama) sudah DIARSIPKAN (FASE 4/E10) dan
tidak punya penulis; 22 berkas masih membacanya sehingga dashboard/laporan/AI selalu 0.
Adaptor ini memetakan job produksi nyata (`production_jobs` + `production_job_items`,
diperkaya `routes.production_execution._enrich_jobs`) ke bentuk WO yang sudah dipakai
konsumen lama, supaya pemanggil cukup mengganti `db.rahaza_work_orders.*` → fungsi di sini.

Peta field (WO lama ← job):
  wo_number ← job_number · order_id/po_id ← po_id · order_number_snapshot ← po_number
  model_name(_snapshot) ← product_name item pertama · model_code(_snapshot) ← sku item pertama
  qty ← total_available||total_ordered · completed_qty/qty_produced/progress_qty ← total_produced
  due_date/target_date/target_end_date/deadline ← deadline||delivery_deadline||PO.deadline
  start_date ← created_at · completed_at ← closed_at||updated_at (bila tertutup)
  status ∈ {released, in_progress, completed, cancelled}; status asli di `raw_status`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

WO_ACTIVE_STATUSES = ("released", "in_progress")
WO_STATUS_ALIASES = {
    "in_production": "in_progress", "planned": "released", "pending": "released",
    "not_started": "released", "draft": "released", "complete": "completed", "done": "completed",
}


def normalize_statuses(statuses: Optional[Iterable[str]]) -> Optional[set]:
    if statuses is None:
        return None
    return {WO_STATUS_ALIASES.get(s, s) for s in statuses}


def _first_item(items: list) -> dict:
    return items[0] if items else {}


async def load_wos(db, *, extra_filter: Optional[Dict[str, Any]] = None, ids: Optional[List[str]] = None,
                   po_ids: Optional[List[str]] = None, statuses: Optional[Iterable[str]] = None,
                   limit: int = 2000, sort=("created_at", -1)) -> List[Dict[str, Any]]:
    """Daftar WO (job induk) berbentuk WO lama. `statuses` memakai kosakata WO (alias diterima)."""
    from routes.production_execution import _enrich_jobs
    from core.production_job_lifecycle import JOB_CLOSED_STATUSES

    q: Dict[str, Any] = {"parent_job_id": {"$in": [None, ""]}, **(extra_filter or {})}
    if ids is not None:
        q["id"] = {"$in": list(ids)}
    if po_ids is not None:
        q["po_id"] = {"$in": list(po_ids)}
    jobs = await db.production_jobs.find(q, {"_id": 0}).sort(*sort).to_list(limit)
    if not jobs:
        return []
    enriched = await _enrich_jobs(db, jobs)
    job_ids = [j["id"] for j in enriched]
    items = await db.production_job_items.find(
        {"job_id": {"$in": job_ids}}, {"_id": 0, "job_id": 1, "sku": 1, "product_name": 1, "size": 1,
                                        "color": 1, "model_id": 1, "rahaza_variant_id": 1}).to_list(None)
    items_by_job: Dict[str, list] = {}
    for it in items:
        items_by_job.setdefault(it["job_id"], []).append(it)
    po_ids_ = list({j.get("po_id") for j in enriched if j.get("po_id")})
    pos = await db.production_pos.find(
        {"id": {"$in": po_ids_}}, {"_id": 0, "id": 1, "deadline": 1, "delivery_deadline": 1,
                                   "customer_name": 1, "po_number": 1}).to_list(None) if po_ids_ else []
    po_map = {p["id"]: p for p in pos}
    size_codes = list({it.get("size") for it in items if it.get("size")})
    size_map = {s_["code"]: s_["id"] for s_ in await db.rahaza_sizes.find(
        {"code": {"$in": size_codes}}, {"_id": 0, "id": 1, "code": 1}).to_list(None)} if size_codes else {}
    want = normalize_statuses(statuses)

    out: List[Dict[str, Any]] = []
    for j in enriched:
        raw_status = str(j.get("status") or "Open")
        low = raw_status.lower()
        closed = raw_status in JOB_CLOSED_STATUSES or low in ("completed", "closed", "done", "cancelled")
        if low == "cancelled":
            status = "cancelled"
        elif closed:
            status = "completed"
        elif (j.get("total_produced") or 0) > 0:
            status = "in_progress"
        else:
            status = "released"
        if want is not None and status not in want:
            continue
        po = po_map.get(j.get("po_id") or "", {})
        first = _first_item(items_by_job.get(j["id"], []))
        qty = j.get("total_available") or j.get("total_ordered") or 0
        produced = j.get("total_produced") or 0
        due = j.get("deadline") or j.get("delivery_deadline") or po.get("deadline") or po.get("delivery_deadline")
        completed_at = (j.get("closed_at") or j.get("completed_at") or j.get("updated_at")) if closed else None
        out.append({
            "id": j.get("id"),
            "wo_number": j.get("job_number") or j.get("id"),
            "job_number": j.get("job_number"),
            "po_id": j.get("po_id"), "order_id": j.get("po_id"),
            "po_number": j.get("po_number") or po.get("po_number"),
            "order_number_snapshot": j.get("po_number") or po.get("po_number"),
            "order_number": j.get("po_number") or po.get("po_number"),
            "customer_name": j.get("customer_name") or po.get("customer_name") or "",
            "buyer": j.get("customer_name") or po.get("customer_name") or "",
            "client_name": j.get("vendor_name") or "Produksi Internal",
            "vendor_id": j.get("vendor_id"), "vendor_name": j.get("vendor_name"),
            "business_type": j.get("business_type") or "internal",
            "source": "internal" if (j.get("business_type") or "internal") == "internal" else "maklon",
            "model_id": first.get("model_id"), "rahaza_variant_id": first.get("rahaza_variant_id"),
            "size_id": size_map.get(first.get("size") or ""),
            "model_code": first.get("sku") or "", "model_code_snapshot": first.get("sku") or "",
            "model_name": first.get("product_name") or "", "model_name_snapshot": first.get("product_name") or "",
            "style_name": first.get("product_name") or "",
            "size_code": first.get("size") or "", "color": first.get("color") or "",
            "item_count": j.get("item_count", len(items_by_job.get(j["id"], []))),
            "status": status, "raw_status": raw_status,
            "qty": qty, "completed_qty": produced, "qty_produced": produced, "progress_qty": produced,
            "qty_passed_qc": j.get("total_accepted") or 0, "qty_reject": j.get("total_reject") or 0,
            "qty_shipped": j.get("total_shipped_to_buyer") or 0,
            "due_date": due, "deadline": due, "target_date": due, "target_end_date": due,
            "start_date": j.get("created_at"), "created_at": j.get("created_at"),
            "updated_at": j.get("updated_at"), "completed_at": completed_at,
            "priority": j.get("priority") or "normal",
            "notes": j.get("notes") or "",
        })
    return out


async def get_wo(db, wo_id: str) -> Optional[Dict[str, Any]]:
    rows = await load_wos(db, ids=[wo_id], limit=1)
    return rows[0] if rows else None


async def find_wo_by_number(db, code: str) -> Optional[Dict[str, Any]]:
    import re
    rows = await load_wos(db, extra_filter={"job_number": {"$regex": f"^{re.escape(code)}$", "$options": "i"}}, limit=1)
    return rows[0] if rows else None


async def search_wos(db, regex, *, limit: int = 10) -> List[Dict[str, Any]]:
    """Pencarian bebas (regex Mongo) pada nomor job/PO/pelanggan."""
    rows = await load_wos(db, extra_filter={"$or": [
        {"job_number": regex}, {"po_number": regex}, {"customer_name": regex}, {"vendor_name": regex}]}, limit=limit)
    return rows[:limit]


async def count_wos(db, *, statuses: Optional[Iterable[str]] = None, created_since: Optional[str] = None,
                    completed_since: Optional[str] = None, overdue_before: Optional[str] = None,
                    extra_filter: Optional[Dict[str, Any]] = None) -> int:
    """Hitung WO (status WO dinormalisasi lewat load_wos karena in_progress bergantung progress)."""
    f: Dict[str, Any] = dict(extra_filter or {})
    if created_since:
        f["created_at"] = {"$gte": created_since}
    rows = await load_wos(db, extra_filter=f, statuses=statuses)
    if completed_since:
        rows = [r for r in rows if str(r.get("completed_at") or "") >= completed_since]
    if overdue_before:
        rows = [r for r in rows if r.get("due_date") and str(r["due_date"])[:10] < overdue_before[:10]]
    return len(rows)


async def status_counts(db) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in await load_wos(db):
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out
