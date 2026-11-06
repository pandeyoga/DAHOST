"""Dasbor Penggajian — ringkasan dari run gaji SUNGGUHAN (`rahaza_payroll_runs`).

2026-11-06 (Tahap 2): modul ini dulu jalur run KEDUA. `POST /trigger` membuat run "hantu" (field `period.from`,
`total_net_pay`, tanpa slip) yang tidak pernah dihitung; KPI membaca field hantu itu sehingga selalu 0; jadwal
"auto-run" disimpan tetapi tidak pernah menjalankan apa pun; `attendance-sync` menulis hitungan hadir versi
lain ke slip. Semua itu DIHAPUS. Run gaji hanya dibuat lewat `POST /api/rahaza/payroll-runs` (tab Proses Gaji);
dasbor ini hanya membaca.

Endpoints (baca saja, peran payroll):
  GET /api/payroll/automation/dashboard   — KPI: run per status, run terakhir, cakupan profil, dibayar tahun ini
  GET /api/payroll/automation/alerts      — peringatan: karyawan tanpa profil, draft lama, run final belum dibayar
  GET /api/payroll/automation/history     — riwayat run terakhir
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request

from auth import serialize_doc
from database import get_db
from routes.rahaza_payroll_shared import _require_hr
from utils.waktu import fmt_wib, today_wib, wib_year

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/payroll/automation", tags=["payroll-automation"])

RUN_FIELDS = {"_id": 0, "id": 1, "run_number": 1, "period_from": 1, "period_to": 1, "status": 1,
              "total_employees": 1, "total_gross": 1, "total_net": 1, "payment_status": 1, "created_at": 1,
              "finalized_at": 1, "paid_at": 1, "created_by_name": 1, "finalized_by_name": 1}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


async def _coverage(db) -> dict:
    active = {e["id"] async for e in db.rahaza_employees.find({"active": {"$ne": False}}, {"_id": 0, "id": 1})}
    with_prof = {p["employee_id"] async for p in db.rahaza_payroll_profiles.find(
        {"active": True}, {"_id": 0, "employee_id": 1})}
    covered = len(active & with_prof)
    return {"total_active_employees": len(active), "with_payroll_profile": covered,
            "without_profile": len(active) - covered,
            "coverage_pct": round(covered / max(len(active), 1) * 100, 1)}


@router.get("/dashboard")
async def payroll_dashboard(request: Request):
    """Ringkasan dari run gaji sungguhan (bukan run hantu)."""
    await _require_hr(request)
    db = get_db()
    year_start = f"{wib_year()}-01-01"
    runs = await db.rahaza_payroll_runs.find({"period_from": {"$gte": year_start}}, RUN_FIELDS).to_list(500)
    summary: dict = {}
    for r in runs:
        st = r.get("status") or "draft"
        slot = summary.setdefault(st, {"count": 0, "total_net_rp": 0.0})
        slot["count"] += 1
        slot["total_net_rp"] += float(r.get("total_net") or 0)
    latest = await db.rahaza_payroll_runs.find({}, RUN_FIELDS).sort("created_at", -1).limit(1).to_list(1)
    this_month = fmt_wib("%Y-%m")
    payslips_this_month = await db.rahaza_payslips.count_documents({"period_from": {"$gte": f"{this_month}-01"}})
    paid_ytd = sum(float(r.get("total_net") or 0) for r in runs
                   if r.get("status") == "finalized" and r.get("payment_status") == "paid")
    unpaid_final = sum(float(r.get("total_net") or 0) for r in runs
                       if r.get("status") == "finalized" and r.get("payment_status") != "paid")
    return {
        "ok": True,
        "run_summary": summary,
        "latest_run": serialize_doc(latest[0]) if latest else None,
        "employee_profile_coverage": await _coverage(db),
        "payslips_this_month": payslips_this_month,
        "total_disbursed_ytd": paid_ytd,
        "total_unpaid_finalized": unpaid_final,
    }


@router.get("/alerts")
async def payroll_alerts(request: Request):
    await _require_hr(request)
    db = get_db()
    alerts = []
    cov = await _coverage(db)
    if cov["without_profile"] > 0:
        alerts.append({"type": "missing_profile", "severity": "warning", "count": cov["without_profile"],
                       "message": f"{cov['without_profile']} karyawan aktif belum punya profil gaji.",
                       "action": "Buat profil gaji di tab Profil Gaji."})
    cutoff = _now() - timedelta(days=3)
    drafts = await db.rahaza_payroll_runs.find({"status": "draft"}, {"_id": 0, "created_at": 1}).to_list(200)
    stale = sum(1 for r in drafts if (_as_dt(r.get("created_at")) or _now()) <= cutoff)
    if stale:
        alerts.append({"type": "stale_draft", "severity": "warning", "count": stale,
                       "message": f"{stale} run gaji masih draf lebih dari 3 hari.",
                       "action": "Hitung ulang lalu finalisasi, atau hapus draf yang tidak dipakai."})
    unpaid = await db.rahaza_payroll_runs.count_documents({"status": "finalized", "payment_status": {"$ne": "paid"}})
    if unpaid:
        alerts.append({"type": "finalized_unpaid", "severity": "info", "count": unpaid,
                       "message": f"{unpaid} run gaji final belum dibayar.",
                       "action": "Catat pembayarannya di tab Proses Gaji."})
    month = fmt_wib("%Y-%m")
    today = today_wib()
    has_run = await db.rahaza_payroll_runs.find_one(
        {"period_to": {"$gte": f"{month}-01"}, "status": {"$ne": "cancelled"}}, {"_id": 0, "id": 1})
    if not has_run and today.day >= 20:
        alerts.append({"type": "no_run_this_month", "severity": "info", "count": 0,
                       "message": f"Belum ada run gaji untuk bulan ini (tanggal {today.day}).",
                       "action": "Buat run di tab Proses Gaji."})
    return {"ok": True, "data": alerts, "total": len(alerts)}


@router.get("/history")
async def run_history(request: Request, limit: int = Query(12, ge=1, le=36)):
    await _require_hr(request)
    db = get_db()
    runs = await db.rahaza_payroll_runs.find({}, RUN_FIELDS).sort("created_at", -1).limit(limit).to_list(limit)
    return {"ok": True, "data": [serialize_doc(r) for r in runs]}
