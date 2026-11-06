# ruff: noqa: F401
"""
rahaza_payroll_profiles.py — Payroll Profile Management
Extracted from rahaza_payroll.py (1539 LOC monolith)

Refactored: Session #11.19 Phase 3.2 Batch #4
Endpoints: GET /payroll-profiles, GET /payroll-profiles/{id}, POST /payroll-profiles, PUT /payroll-profiles/{id}, DELETE /payroll-profiles/{id}
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from database import get_db
from auth import require_auth, serialize_doc, log_activity
from routes.rahaza_payroll_shared import (
    _uid, _now, VALID_SCHEMES, VALID_PERIOD_TYPES, VALID_RUN_STATUS,
    _get_applicable_allowances, _require_hr,
)
from routes.rahaza_posting import post_payroll_run
from utils.saga import SagaExecutor
import uuid
import io
import csv
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Optional
from utils.waktu import today_wib

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rahaza", tags=["rahaza-payroll-profiles"])


# ═══ VERSI TARIF PROFIL GAJI (Tahap 2, 2026-11-06) ════════════════════════════
# Kenaikan gaji yang disetujui (layar Penyesuaian maupun Kotak Masuk HR) membuat VERSI tarif baru dengan
# tanggal berlaku (`rate_versions`). Mesin hitung memakai versi yang berlaku per hari kerja (prorata bila
# kenaikan mulai di tengah periode). `base_rate`/`overtime_rate` di atas = tarif yang berlaku HARI INI
# (dibaca modul lain: kasbon, HPP, livehost) dan disinkronkan otomatis saat profil dibuka.

def _versions_with_initial(profile: dict) -> list:
    from routes.rahaza_payroll_rules import profile_versions
    vers = [dict(v) for v in profile_versions(profile)]
    if not profile.get("rate_versions"):
        vers[0].update(version=1, source="awal")
    return vers


def _current_rates(profile: dict, versions: list) -> dict:
    from routes.rahaza_payroll_rules import version_on
    cur = version_on({**profile, "rate_versions": versions}, today_wib())
    return {"base_rate": float(cur.get("base_rate") or 0), "overtime_rate": float(cur.get("overtime_rate") or 0)}


def _put_version(versions: list, new: dict) -> list:
    """Sisipkan versi; versi lain dengan tanggal berlaku SAMA diganti. Nomor versi berurutan."""
    eff = new.get("effective_from")
    out = [v for v in versions if v.get("effective_from") != eff]
    out.append(new)
    out.sort(key=lambda v: str(v.get("effective_from") or ""))
    for i, v in enumerate(out, 1):
        v["version"] = i
    return out


async def sync_profile_current_rate(db, profile: dict) -> dict:
    """Profil dengan versi tarif: samakan `base_rate`/`overtime_rate` dengan versi yang berlaku hari ini."""
    if not profile.get("rate_versions"):
        return profile
    cur = _current_rates(profile, profile["rate_versions"])
    if (abs(cur["base_rate"] - float(profile.get("base_rate") or 0)) > 0.001
            or abs(cur["overtime_rate"] - float(profile.get("overtime_rate") or 0)) > 0.001):
        await db.rahaza_payroll_profiles.update_one({"id": profile["id"]}, {"$set": {**cur, "updated_at": _now()}})
        profile = {**profile, **cur}
    return profile


async def apply_salary_adjustment_to_profile(db, adj: dict, user: dict) -> dict:
    """Kenaikan gaji DISETUJUI → versi tarif baru di Profil Gaji aktif, berlaku mulai `effective_date`
    (kosong = hari ini, WIB). Idempoten per `adjustment_id`. Return {profile_id, effective_from, warning}."""
    from routes.rahaza_payroll_shared import parse_ymd
    profile = await db.rahaza_payroll_profiles.find_one(
        {"employee_id": adj.get("employee_id"), "active": True}, {"_id": 0})
    if not profile:
        raise HTTPException(404, "Profil gaji aktif belum ada untuk karyawan ini — buat Profil Gaji dulu.")
    versions = _versions_with_initial(profile)
    if any(v.get("adjustment_id") == adj.get("id") for v in versions):
        return {"profile_id": profile["id"], "effective_from": adj.get("effective_date"), "already_applied": True}
    proposed = float(adj.get("proposed_base") or adj.get("new_value") or 0)
    if proposed <= 0:
        raise HTTPException(400, "Usulan gaji baru kosong — tidak bisa diterapkan ke Profil Gaji.")
    eff = parse_ymd(adj.get("effective_date"), field="tanggal berlaku")
    from routes.rahaza_payroll_rules import version_on
    prev = version_on({**profile, "rate_versions": versions}, eff)
    new = {"effective_from": eff.isoformat(), "base_rate": proposed,
           "overtime_rate": float(prev.get("overtime_rate") or 0), "source": "penyesuaian_gaji",
           "adjustment_id": adj.get("id"), "created_at": _now(), "created_by": user.get("id"),
           "created_by_name": user.get("name", "")}
    versions = _put_version(versions, new)
    await db.rahaza_payroll_profiles.update_one({"id": profile["id"]}, {"$set": {
        "rate_versions": versions, **_current_rates(profile, versions),
        "updated_at": _now(), "updated_by": user.get("id"), "updated_by_name": user.get("name", "")}})
    warning = None
    final = await db.rahaza_payslips.find_one(
        {"employee_id": adj.get("employee_id"), "period_to": {"$gte": eff.isoformat()}}, {"_id": 0, "run_id": 1})
    if final and await db.rahaza_payroll_runs.count_documents({"id": final.get("run_id"), "status": "finalized"}):
        warning = ("Kenaikan berlaku surut: run gaji final yang sudah mencakup tanggal berlaku tidak berubah — "
                   "bayar selisihnya lewat penyesuaian pendapatan di run berikutnya.")
    return {"profile_id": profile["id"], "effective_from": eff.isoformat(), "warning": warning}


def _manual_rate_edit(existing: dict, doc: dict, effective_from) -> dict:
    """Ubah tarif lewat form Profil Gaji. Profil tanpa versi: perilaku lama (tarif diganti). Profil bervesi:
    dengan `effective_from` → versi baru mulai tanggal itu; tanpa → versi yang berlaku hari ini dikoreksi."""
    if not existing.get("rate_versions") and not effective_from:
        return doc
    versions = _versions_with_initial(existing)
    if effective_from:
        from routes.rahaza_payroll_shared import parse_ymd
        eff = parse_ymd(effective_from, field="tanggal berlaku").isoformat()
        versions = _put_version(versions, {"effective_from": eff, "base_rate": doc["base_rate"],
                                           "overtime_rate": doc["overtime_rate"], "source": "profil_gaji",
                                           "created_at": _now()})
    else:
        from routes.rahaza_payroll_rules import version_on
        cur = version_on({**existing, "rate_versions": versions}, today_wib())
        for v in versions:
            if v is cur or (v.get("effective_from") == cur.get("effective_from")):
                v.update(base_rate=doc["base_rate"], overtime_rate=doc["overtime_rate"])
    return {**doc, "rate_versions": versions, **_current_rates(existing, versions)}


@router.get("/payroll-profiles")
async def list_profiles(request: Request, employee_id: Optional[str] = None, active_only: bool = True):
    # Tahap 1 (2026-11-06): daftar Profil Gaji memuat gaji semua karyawan → hanya HR & manajemen.
    # Dulu cukup login. Karyawan melihat gajinya sendiri lewat slip di Portal Saya.
    await _require_hr(request)
    db = get_db()
    q = {}
    if active_only:
        q["active"] = True
    if employee_id:
        q["employee_id"] = employee_id
    rows = await db.rahaza_payroll_profiles.find(q, {"_id": 0}).to_list(500)
    rows = [await sync_profile_current_rate(db, r) for r in rows]   # Tahap 2: versi tarif berlaku hari ini
    # Enrich with employee info
    emp_ids = list({r.get("employee_id") for r in rows if r.get("employee_id")})
    emps = await db.rahaza_employees.find({"id": {"$in": emp_ids}}, {"_id": 0}).to_list(500) if emp_ids else []
    e_map = {e["id"]: e for e in emps}
    for r in rows:
        e = e_map.get(r.get("employee_id")) or {}
        r["employee_code"] = e.get("employee_code")
        r["employee_name"] = e.get("name")
    rows.sort(key=lambda r: r.get("employee_code") or "")
    return serialize_doc(rows)


@router.get("/payroll-profiles/{employee_id}")
async def get_profile(employee_id: str, request: Request):
    await _require_hr(request)  # Tahap 1: sama dengan daftar profil
    db = get_db()
    row = await db.rahaza_payroll_profiles.find_one({"employee_id": employee_id, "active": True}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Profile payroll belum dibuat untuk pegawai ini.")
    row = await sync_profile_current_rate(db, row)
    emp = await db.rahaza_employees.find_one({"id": employee_id}, {"_id": 0}) or {}
    row["employee_code"] = emp.get("employee_code")
    row["employee_name"] = emp.get("name")
    return serialize_doc(row)


def _normalize_profile(body: dict) -> dict:
    pay_scheme = (body.get("pay_scheme") or "monthly").lower()
    period_type = (body.get("period_type") or "monthly").lower()
    if pay_scheme not in VALID_SCHEMES:
        raise HTTPException(400, f"pay_scheme harus salah satu: {VALID_SCHEMES}")
    if period_type not in VALID_PERIOD_TYPES:
        raise HTTPException(400, f"period_type harus salah satu: {VALID_PERIOD_TYPES}")
    cutoff = body.get("cutoff_config") or {}
    # Defaults
    if period_type == "weekly" and "week_start_day" not in cutoff:
        cutoff["week_start_day"] = 1  # Monday
    if period_type == "monthly" and "start_day" not in cutoff:
        cutoff["start_day"] = 1  # 1st of month
    # Validate ranges
    wsd = cutoff.get("week_start_day")
    if wsd is not None and (not isinstance(wsd, int) or not (0 <= wsd <= 6)):
        raise HTTPException(400, "week_start_day harus 0..6 (0=Senin..6=Minggu)")
    sd = cutoff.get("start_day")
    if sd is not None and (not isinstance(sd, int) or not (1 <= sd <= 28)):
        raise HTTPException(400, "start_day harus 1..28")
    pcs_rates = body.get("pcs_process_rates") or []
    norm_pcs_rates = []
    for r in pcs_rates:
        if not r.get("process_id"):
            continue
        norm_pcs_rates.append({
            "process_id": r["process_id"],
            "process_code": (r.get("process_code") or "").upper(),
            "rate": float(r.get("rate") or 0),
        })
    return {
        "employee_id": body.get("employee_id"),
        "pay_scheme": pay_scheme,
        "period_type": period_type,
        "cutoff_config": cutoff,
        "base_rate": float(body.get("base_rate") or 0),
        "overtime_rate": float(body.get("overtime_rate") or 0),
        "pcs_process_rates": norm_pcs_rates,
        "notes": body.get("notes") or "",
    }


@router.post("/payroll-profiles")
async def upsert_profile(request: Request):
    user = await _require_hr(request)
    db = get_db()
    body = await request.json()
    emp_id = body.get("employee_id")
    if not emp_id:
        raise HTTPException(400, "employee_id wajib.")
    emp = await db.rahaza_employees.find_one({"id": emp_id}, {"_id": 0})
    if not emp:
        raise HTTPException(404, f"Pegawai dengan id={emp_id} tidak ditemukan.")
    doc = _normalize_profile(body)
    existing = await db.rahaza_payroll_profiles.find_one({"employee_id": emp_id, "active": True}, {"_id": 0})
    if existing:
        doc = _manual_rate_edit(existing, doc, body.get("effective_from"))
    now = _now()
    doc.update({
        "active": True,
        "updated_at": now,
        "updated_by": user["id"],
        "updated_by_name": user.get("name", ""),
    })
    if existing:
        await db.rahaza_payroll_profiles.update_one({"id": existing["id"]}, {"$set": doc})
        out = await db.rahaza_payroll_profiles.find_one({"id": existing["id"]}, {"_id": 0})
    else:
        doc["id"] = _uid()
        doc["created_at"] = now
        doc["created_by"] = user["id"]
        doc["created_by_name"] = user.get("name", "")
        await db.rahaza_payroll_profiles.insert_one(doc)
        out = await db.rahaza_payroll_profiles.find_one({"id": doc["id"]}, {"_id": 0})
    await log_activity(user["id"], user.get("name", ""), "upsert", "rahaza.payroll_profile", emp_id)
    out["employee_code"] = emp.get("employee_code")
    out["employee_name"] = emp.get("name")
    return serialize_doc(out)


@router.put("/payroll-profiles/{pid}")
async def update_profile(pid: str, request: Request):
    user = await _require_hr(request)
    db = get_db()
    existing = await db.rahaza_payroll_profiles.find_one({"id": pid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Profile tidak ditemukan.")
    body = await request.json()
    body["employee_id"] = existing["employee_id"]  # cannot change
    doc = _manual_rate_edit(existing, _normalize_profile(body), body.get("effective_from"))
    doc.update({
        "updated_at": _now(),
        "updated_by": user["id"],
        "updated_by_name": user.get("name", ""),
    })
    await db.rahaza_payroll_profiles.update_one({"id": pid}, {"$set": doc})
    out = await db.rahaza_payroll_profiles.find_one({"id": pid}, {"_id": 0})
    return serialize_doc(out)


@router.delete("/payroll-profiles/{pid}")
async def delete_profile(pid: str, request: Request):
    user = await _require_hr(request)
    db = get_db()
    res = await db.rahaza_payroll_profiles.update_one({"id": pid, "active": True}, {"$set": {"active": False, "updated_at": _now(), "updated_by": user["id"]}})
    if res.matched_count == 0:
        raise HTTPException(404, "Profile tidak ditemukan atau sudah nonaktif.")
    return {"status": "deleted"}


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ FASE 8c — PAYROLL RUN & PAYSLIP                                           ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _to_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _date_range_filter(from_iso: str, to_iso: str) -> dict:
    return {"$gte": from_iso, "$lte": to_iso}


async def _generate_run_number(db) -> str:
    # RC-5 fix: atomic race-safe numbering (was count_documents()+1)
    from utils.counters import gen_prefixed_number
    today = today_wib().strftime("%Y%m%d")
    return await gen_prefixed_number(db, "rahaza_payroll_runs", "run_number", f"PR-{today}-", 3)


# FASE 15 — fungsi `_compute_payslip_for_employee` DIHAPUS dari modul ini.
# Dulu ada DUA versi bernama sama: yang di sini punya PPh21/BPJS/LWOP tapi TIDAK
# PERNAH DIPANGGIL, sementara `rahaza_payroll_runs.py` memakai versi di
# `rahaza_payroll_shared.py` yang TIDAK punya pajak/BPJS ⇒ potongan pajak & BPJS
# hilang dari payroll run sungguhan. Sekarang SSOT-nya satu, di shared.py
# (sudah diimpor di baris `from routes.rahaza_payroll_shared import ...` di atas).


