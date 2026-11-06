"""
PT Rahaza — Production Calendar (Phase 22B)

Endpoints (prefix /api/rahaza):
  GET  /production-calendar                  — list entries (year, month filter)
  POST /production-calendar                  — create entry (holiday / exception day)
  PUT  /production-calendar/{id}             — update entry
  DELETE /production-calendar/{id}           — delete entry
  GET  /production-calendar/working-days     — count working days between dates
  POST /production-calendar/seed-national    — seed hari libur nasional Indonesia
"""
from fastapi import APIRouter, Request, HTTPException, Query
from database import get_db
from auth import require_auth
from datetime import datetime, timezone, date, timedelta
from typing import Optional
import uuid
import logging
from core.authz import only  # T-01 2.3
from core.roles import PRODUCTION_ROLES  # T-01 2.3
# 2026-11-06 (pola P5): preset libur nasional = `core.national_holidays` (tabel tahun → daftar, sumber
# SKB 3 Menteri 2026 & 2027). Daftar lama `NATIONAL_HOLIDAYS_2026` di berkas ini berisi tanggal salah
# (Idul Fitri 6–7 Apr, Nyepi 14 Mar, Waisak 24 Mei, …) dan hanya satu tahun.
from core import national_holidays as _nh
from core import workdays as _workdays
from utils.waktu import wib_year

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rahaza", tags=["rahaza-production-calendar"])


def _uid() -> str:
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


CALENDAR_TYPES = ("holiday", "exception", "special")


def calendar_entry_doc(entry_date: str, name: str, entry_type: str, *, notes: str = "",
                       affects_shifts=None, user: dict | None = None) -> dict:
    """Bentuk dokumen entri kalender — 2026-11-06 (T4): satu sumber untuk form & impor Excel."""
    d = date.fromisoformat(entry_date)
    return {
        "id": _uid(),
        "date": entry_date,
        "year": d.year,
        "month": d.month,
        "day": d.day,
        "weekday": d.strftime("%A"),
        "name": name,
        "type": entry_type,
        "notes": notes or "",
        "affects_shifts": list(affects_shifts or []),
        "created_at": _now().isoformat(),
        "created_by": (user or {}).get("id"),
        "created_by_name": (user or {}).get("name", (user or {}).get("email")),
    }


@router.get("/production-calendar")
async def list_calendar(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
    type_: Optional[str] = Query(None, alias="type", description="holiday | exception | special"),
):
    """List production calendar entries."""
    await require_auth(request)
    db = get_db()

    q = {}
    if year:
        q["year"] = year
    if month:
        q["month"] = month
    if type_:
        q["type"] = type_

    entries = await db.rahaza_production_calendar.find(q, {"_id": 0}).sort("date", 1).to_list(500)
    return entries


@router.post("/production-calendar")
async def create_calendar_entry(request: Request):
    """
    Create production calendar entry.
    Body: {date (YYYY-MM-DD), name, type (holiday|exception|special), notes, affects_shifts}
    type:
      holiday  — hari libur (tidak produksi)
      exception — hari kerja tidak biasa (half day, dll)
      special  — catatan khusus (audit, tamu buyer, dll)
    """
    user = await require_auth(request)
    db = get_db()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    entry_date = body.get("date", "").strip()
    name = body.get("name", "").strip()
    entry_type = body.get("type", "holiday")

    if not entry_date or not name:
        raise HTTPException(400, "date dan name wajib diisi")
    if entry_type not in CALENDAR_TYPES:
        raise HTTPException(400, "type harus: holiday | exception | special")

    try:
        date.fromisoformat(entry_date)
    except ValueError:
        raise HTTPException(400, "Format date harus YYYY-MM-DD")

    existing = await db.rahaza_production_calendar.find_one({"date": entry_date})
    if existing:
        raise HTTPException(409, f"Sudah ada entri untuk tanggal {entry_date}")

    doc = calendar_entry_doc(entry_date, name, entry_type, notes=body.get("notes", ""),
                             affects_shifts=body.get("affects_shifts", []), user=user)
    await db.rahaza_production_calendar.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/production-calendar/{entry_id}")
async def update_calendar_entry(entry_id: str, request: Request):
    """Update calendar entry."""
    user = await require_auth(request)
    db = get_db()

    entry = await db.rahaza_production_calendar.find_one({"id": entry_id}, {"_id": 0})
    if not entry:
        raise HTTPException(404, "Entri tidak ditemukan")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    updates = {}
    for field in ("name", "type", "notes", "affects_shifts"):
        if field in body:
            updates[field] = body[field]

    if updates:
        updates["updated_at"] = _now().isoformat()
        updates["updated_by"] = user.get("id")
        await db.rahaza_production_calendar.update_one({"id": entry_id}, {"$set": updates})

    updated = await db.rahaza_production_calendar.find_one({"id": entry_id}, {"_id": 0})
    return updated


@router.delete("/production-calendar/{entry_id}", dependencies=only(*PRODUCTION_ROLES))  # T-01 2.3
async def delete_calendar_entry(entry_id: str, request: Request):
    """Delete calendar entry."""
    await require_auth(request)
    db = get_db()

    result = await db.rahaza_production_calendar.delete_one({"id": entry_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Entri tidak ditemukan")

    return {"ok": True, "entry_id": entry_id}


@router.get("/production-calendar/working-days")
async def get_working_days(
    request: Request,
    from_date: str = Query(..., description="YYYY-MM-DD"),
    to_date: str = Query(..., description="YYYY-MM-DD"),
    include_saturday: Optional[bool] = Query(None),
):
    """
    Calculate working days between two dates.
    Excludes weekly off-days and production calendar holidays.

    2026-11-06 (pola P5): dulu bawaan `include_saturday=False` → Sabtu selalu dianggap libur (5 hari kerja),
    padahal keputusan owner 6 hari kerja (`core.workdays`, Pengaturan Payroll). Kini bawaan = setelan itu;
    `include_saturday` hanya menimpa bila dikirim eksplisit.
    """
    await require_auth(request)
    db = get_db()

    try:
        d_from = date.fromisoformat(from_date)
        d_to = date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(400, "Format date harus YYYY-MM-DD")

    if d_from > d_to:
        raise HTTPException(400, "from_date harus sebelum to_date")

    cal = await _workdays.get_work_calendar(db)
    off = set(cal["off_weekdays"])
    if include_saturday is True:
        off.discard(5)
    elif include_saturday is False:
        off.add(5)
    holiday_set = await _workdays.holiday_set(db, d_from, d_to)

    total_days = 0
    working_days = 0
    holiday_count = 0
    weekend_count = 0

    current = d_from
    while current <= d_to:
        total_days += 1
        is_off = current.weekday() in off
        is_holiday = current.isoformat() in holiday_set
        if not is_off and not is_holiday:
            working_days += 1
        if is_holiday:
            holiday_count += 1
        if is_off:
            weekend_count += 1
        current += timedelta(days=1)

    return {
        "from_date": from_date,
        "to_date": to_date,
        "total_calendar_days": total_days,
        "working_days": working_days,
        "holidays": holiday_count,
        "weekends_excluded": weekend_count,
        "include_saturday": 5 not in off,
        "work_days_per_week": 7 - len(off),
    }


async def seed_national_year(db, year: int) -> dict:
    """Isi libur nasional + cuti bersama SATU tahun dari preset. Tanggal yang sudah berisi entri dilewati.

    Tahun tanpa preset → HTTPException 404 dengan kalimat untuk layar (bukan diam-diam 0)."""
    rows = _nh.holidays_for(year)
    if rows is None:
        raise HTTPException(404, _nh.missing_year_message(year))
    existing_dates = set()
    async for d in db.rahaza_production_calendar.find(
            {"date": {"$in": [h["date"] for h in rows]}}, {"_id": 0, "date": 1}):
        existing_dates.add(d["date"])
    now_iso = _now().isoformat()
    docs = [_nh.calendar_doc(h, uid=_uid(), now_iso=now_iso) for h in rows if h["date"] not in existing_dates]
    if docs:
        await db.rahaza_production_calendar.insert_many(docs)
    return {"ok": True, "year": year, "seeded": len(docs), "skipped": len(rows) - len(docs),
            "total_preset": len(rows),
            "cuti_bersama": sum(1 for d in docs if d["kind"] == _nh.KIND_CUTI),
            "perkiraan": sum(1 for d in docs if d["perkiraan"]),
            "source": _nh.SOURCES.get(year, ""), "available_years": _nh.available_years()}


@router.post("/production-calendar/seed-national")
async def seed_national_holidays(request: Request, year: Optional[int] = None):
    """Isi hari libur nasional & cuti bersama Indonesia untuk `year` (bawaan: tahun berjalan WIB).

    2026-11-06 (pola P5): preset per tahun dari `core.national_holidays`; tahun tanpa data ditolak dengan
    pesan yang jelas (dulu selalu menulis daftar 2026 yang tanggalnya salah)."""
    await require_auth(request)
    db = get_db()
    return await seed_national_year(db, int(year or wib_year()))
