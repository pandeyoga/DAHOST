"""
CV. Dewi Aditya — Salary Grades / Struktur Gaji per Tier (Phase 9.2 P2)

Master salary bands with min / mid / max per grade.
Assigned per-employee. Used for payroll transparency & fairness audit.

Collection: rahaza_salary_grades
  { id, grade_code, grade_name, level, department (opt),
    min_salary, mid_salary, max_salary, currency='IDR',
    description, is_active, created_at, updated_at }

Employee field: salary_grade_id (reference) — linked via
  PUT /api/rahaza/employees/{id} with body {salary_grade_id}
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, log_activity
from core.authz import izin_atau_peran_lama, pesan_centang  # 14 Nov 2026: centang owner = penentu

router = APIRouter(prefix="/api/rahaza/salary-grades", tags=["rahaza-salary-grades"])


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)
def _s(d):
    if not d:
        return None
    d = dict(d)
    d.pop("_id", None)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


# 2026-11-08: kode peran lama ATAU izin `salary.manage` ("Kelola struktur & penyesuaian gaji").
SALARY_GRADE_ROLES = ("superadmin", "admin", "owner", "hr")
SALARY_GRADE_PERM = "salary.manage"


async def _require_admin(request: Request):
    user = await require_auth(request)
    if not izin_atau_peran_lama(user, SALARY_GRADE_ROLES, SALARY_GRADE_PERM):
        raise HTTPException(403, pesan_centang(user, apa="mengelola struktur gaji"))
    return user


@router.get("")
async def list_grades(request: Request, active_only: bool = True):
    await require_auth(request)
    db = get_db()
    filt = {"is_active": True} if active_only else {}
    docs = await db.rahaza_salary_grades.find(filt, {"_id": 0}).sort("level", 1).to_list(500)
    return {"ok": True, "grades": [_s(d) for d in docs]}


@router.post("")
async def create_grade(request: Request):
    await _require_admin(request)
    db = get_db()
    body = await request.json()
    code = (body.get("grade_code") or "").strip().upper()
    if not code:
        raise HTTPException(400, "grade_code wajib.")
    if await db.rahaza_salary_grades.find_one({"grade_code": code}):
        raise HTTPException(409, f"Grade '{code}' sudah ada.")
    if body.get("grade_name"):  # 2026-11-06 (pola P8)
        from core.reference_dedup import assert_unique_ref
        await assert_unique_ref(db, "rahaza_salary_grades", name=body.get("grade_name"), name_field="grade_name",
                                label="Grade gaji")
    doc = {
        "id": _uid(),
        "grade_code": code,
        "grade_name": body.get("grade_name") or code,
        "level": int(body.get("level") or 1),
        "department": body.get("department") or "",
        "min_salary": float(body.get("min_salary") or 0),
        "mid_salary": float(body.get("mid_salary") or 0),
        "max_salary": float(body.get("max_salary") or 0),
        "currency": body.get("currency") or "IDR",
        "description": body.get("description") or "",
        "is_active": bool(body.get("is_active", True)),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.rahaza_salary_grades.insert_one(doc)
    return {"ok": True, "grade": _s(doc)}


@router.put("/{grade_id}")
async def update_grade(grade_id: str, request: Request):
    await _require_admin(request)
    db = get_db()
    body = await request.json()
    body.pop("_id", None)
    body.pop("id", None)
    body.pop("created_at", None)
    body["updated_at"] = _now()
    res = await db.rahaza_salary_grades.update_one({"id": grade_id}, {"$set": body})
    if res.matched_count == 0:
        raise HTTPException(404, "Grade tidak ditemukan.")
    doc = await db.rahaza_salary_grades.find_one({"id": grade_id}, {"_id": 0})
    return {"ok": True, "grade": _s(doc)}


@router.delete("/{grade_id}")
async def delete_grade(grade_id: str, request: Request, hard: bool = False):
    """Tanpa `hard`: nonaktifkan (perilaku lama). `?hard=true` (10 Nov 2026, owner "master data bisa dihapus"):
    hapus permanen bila golongan belum dipakai karyawan atau jabatan (Struktur Organisasi menyimpan KODE golongan);
    selain itu 409 dan layar menawarkan Nonaktifkan."""
    user = await _require_admin(request)
    db = get_db()
    if hard:
        from core.hapus_master import hitung_pemakaian, tolak_bila_dipakai
        g = await db.rahaza_salary_grades.find_one({"id": grade_id}, {"_id": 0})
        if not g:
            raise HTTPException(404, "Golongan gaji tidak ditemukan.")
        cek = [("karyawan", "rahaza_employees", {"salary_grade_id": grade_id})]
        if g.get("grade_code"):
            cek.append(("jabatan", "dewi_org_positions", {"salary_grade": g["grade_code"]}))
        tolak_bila_dipakai("Golongan gaji", g.get("grade_name") or g.get("grade_code") or "", await hitung_pemakaian(db, cek))
        await db.rahaza_salary_grades.delete_one({"id": grade_id})
        await log_activity(user.get("id") or "", user.get("name") or "", "delete", "rahaza.salary_grade", g.get("grade_code") or grade_id)
        return {"ok": True, "deleted": True}
    # Soft delete
    res = await db.rahaza_salary_grades.update_one(
        {"id": grade_id}, {"$set": {"is_active": False, "updated_at": _now()}}
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Grade tidak ditemukan.")
    return {"ok": True}


@router.get("/audit")
async def audit(request: Request):
    """Check employees whose base_rate is outside their assigned grade range."""
    await require_auth(request)
    db = get_db()
    grades = await db.rahaza_salary_grades.find({"is_active": True}, {"_id": 0}).to_list(500)
    grade_map = {g["id"]: g for g in grades}

    employees = await db.rahaza_employees.find(
        {"active": True, "salary_grade_id": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "id": 1, "name": 1, "employee_code": 1, "salary_grade_id": 1, "base_rate": 1},
    ).to_list(500)

    # 2026-11-06 (Tahap 2): SATU sumber gaji = Profil Gaji (bukan field gaji di Data Karyawan).
    prof_rate = {p["employee_id"]: float(p.get("base_rate") or 0) for p in await db.rahaza_payroll_profiles.find(
        {"employee_id": {"$in": [e["id"] for e in employees]}, "active": True},
        {"_id": 0, "employee_id": 1, "base_rate": 1}).to_list(1000)}
    violations = []
    for emp in employees:
        g = grade_map.get(emp.get("salary_grade_id"))
        if not g:
            continue
        rate = prof_rate.get(emp["id"], float(emp.get("base_rate") or 0))
        if rate < g["min_salary"] or rate > g["max_salary"]:
            violations.append({
                "employee_code": emp["employee_code"],
                "name": emp["name"],
                "grade": g["grade_name"],
                "base_rate": rate,
                "grade_min": g["min_salary"],
                "grade_max": g["max_salary"],
                "status": "below" if rate < g["min_salary"] else "above",
            })
    return {"ok": True, "violations": violations, "total_graded": len(employees), "total_grades": len(grades)}
