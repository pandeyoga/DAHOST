"""core/qc_reader.py — SATU pembaca QC di atas `cmt_receipts` + `cmt_receipt_lines` (FASE 3 / T-17).

`rahaza_qc_events` (QC v2 engine lama) tidak punya penulis; 3 konsumen (laporan eksekutif,
AI RCA QC, agregat AI) selalu membaca 0. Sumber QC nyata sejak K5/Phase B adalah inspeksi
penerimaan FG dari CMT: `cmt_receipts.total_actual` (lolos) & `total_rejected` (reject),
rincian per SKU + alasan reject di `cmt_receipt_lines`.

Bentuk baris yang dikembalikan meniru event QC lama supaya konsumen tidak berubah banyak:
  checked_qty = total_actual + total_rejected · pass_qty = total_actual · fail_qty = total_rejected
  line_id/line_name ← cmt_vendor_id/cmt_name · model_id/model_name ← po_id/po_number
  created_at ← receipt_date (YYYY-MM-DD) · defect_reasons ← reject_reason baris (non-kosong)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.cmt_receipt_status import ST_CANCELLED


def _inspected_filter(d_start: str, d_end: str) -> Dict[str, Any]:
    return {
        "receipt_date": {"$gte": d_start[:10], "$lte": d_end[:10]},
        "status": {"$ne": ST_CANCELLED},
        "$expr": {"$gt": [{"$add": [{"$ifNull": ["$total_actual", 0]}, {"$ifNull": ["$total_rejected", 0]}]}, 0]},
    }


async def qc_summary(db, *, d_start: str, d_end: str) -> Dict[str, int]:
    """Σ checked/fail + jumlah dokumen penerimaan yang sudah diinspeksi dalam rentang tanggal."""
    pipeline = [
        {"$match": _inspected_filter(d_start, d_end)},
        {"$group": {
            "_id": None,
            "pass": {"$sum": {"$ifNull": ["$total_actual", 0]}},
            "fail": {"$sum": {"$ifNull": ["$total_rejected", 0]}},
            "events": {"$sum": 1},
        }},
    ]
    rows = await db.cmt_receipts.aggregate(pipeline).to_list(1)
    if not rows:
        return {"checked": 0, "fail": 0, "events": 0}
    r = rows[0]
    fail = int(r.get("fail") or 0)
    return {"checked": int(r.get("pass") or 0) + fail, "fail": fail, "events": int(r.get("events") or 0)}


async def qc_event_rows(db, *, d_start: str, d_end: str, vendor_id: Optional[str] = None,
                        po_id: Optional[str] = None, limit: int = 1000) -> List[Dict[str, Any]]:
    """Satu baris per penerimaan yang sudah diinspeksi, berbentuk event QC lama."""
    q = _inspected_filter(d_start, d_end)
    if vendor_id:
        q["cmt_vendor_id"] = vendor_id
    if po_id:
        q["po_id"] = po_id
    receipts = await db.cmt_receipts.find(q, {
        "_id": 0, "id": 1, "receipt_code": 1, "receipt_date": 1, "cmt_vendor_id": 1, "cmt_name": 1,
        "po_id": 1, "po_number": 1, "total_actual": 1, "total_rejected": 1,
    }).sort("receipt_date", -1).limit(limit).to_list(limit)
    if not receipts:
        return []
    reasons: Dict[str, List[str]] = {}
    async for ln in db.cmt_receipt_lines.find(
        {"receipt_id": {"$in": [r["id"] for r in receipts]}, "reject_qty": {"$gt": 0}},
        {"_id": 0, "receipt_id": 1, "reject_reason": 1},
    ):
        reason = (ln.get("reject_reason") or "").strip()
        if reason:
            reasons.setdefault(ln["receipt_id"], []).append(reason)
    out = []
    for r in receipts:
        passed = int(r.get("total_actual") or 0)
        fail = int(r.get("total_rejected") or 0)
        out.append({
            "id": r["id"], "receipt_code": r.get("receipt_code", ""),
            "checked_qty": passed + fail, "pass_qty": passed, "fail_qty": fail,
            "line_id": r.get("cmt_vendor_id") or "", "line_name": r.get("cmt_name") or "",
            "model_id": r.get("po_id") or "", "model_name": r.get("po_number") or "",
            "created_at": r.get("receipt_date") or "",
            "defect_reasons": reasons.get(r["id"], []),
        })
    return out
