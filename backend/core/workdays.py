"""Hari kerja aktif — SATU aturan untuk payroll, absensi, cuti, dan laporan HR (2026-11-06, Tahap 2).

Keputusan owner 6 Nov 2026: kerja 6 hari per minggu (bisa diatur, bawaan 6); pembagi gaji = hari kerja
aktif bulan itu = hari kerja mingguan dikurangi hari libur di Kalender Produksi.

Pengaturan disimpan di `rahaza_payroll_settings` dokumen `{key: "work_calendar", work_days_per_week: 6}`
(diubah dari Pengaturan Payroll). Hari libur dibaca dari `rahaza_production_calendar` (`type: "holiday"`).

Pakai modul ini — JANGAN menulis ulang `weekday() < 5` di tempat lain.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

WORK_CALENDAR_KEY = "work_calendar"
DEFAULT_WORK_DAYS_PER_WEEK = 6


def _to_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def off_weekdays_for(work_days_per_week: int) -> frozenset[int]:
    """Hari libur mingguan (0=Senin … 6=Minggu). 6 hari kerja → Minggu libur; 5 → Sabtu+Minggu."""
    n = max(1, min(7, int(work_days_per_week or DEFAULT_WORK_DAYS_PER_WEEK)))
    return frozenset(range(n, 7))


async def get_work_calendar(db) -> dict:
    doc = await db.rahaza_payroll_settings.find_one({"key": WORK_CALENDAR_KEY}, {"_id": 0}) or {}
    n = int(doc.get("work_days_per_week") or DEFAULT_WORK_DAYS_PER_WEEK)
    n = max(1, min(7, n))
    return {"work_days_per_week": n, "off_weekdays": off_weekdays_for(n)}


async def holiday_set(db, date_from, date_to) -> set[str]:
    f, t = _to_date(date_from).isoformat(), _to_date(date_to).isoformat()
    rows = await db.rahaza_production_calendar.find(
        {"date": {"$gte": f, "$lte": t}, "type": "holiday"}, {"_id": 0, "date": 1}).to_list(400)
    return {str(r.get("date"))[:10] for r in rows}


def is_working_day(d, off_weekdays, holidays: set[str]) -> bool:
    d = _to_date(d)
    return d.weekday() not in off_weekdays and d.isoformat() not in holidays


def working_days_between(date_from, date_to, off_weekdays, holidays: set[str]) -> list[date]:
    """Murni (tanpa DB): daftar hari kerja dari `date_from` s.d. `date_to` (inklusif)."""
    cur, end = _to_date(date_from), _to_date(date_to)
    out = []
    while cur <= end:
        if is_working_day(cur, off_weekdays, holidays):
            out.append(cur)
        cur += timedelta(days=1)
    return out


async def working_days(db, date_from, date_to) -> list[date]:
    cal = await get_work_calendar(db)
    hol = await holiday_set(db, date_from, date_to)
    return working_days_between(date_from, date_to, cal["off_weekdays"], hol)


async def count_working_days(db, date_from, date_to) -> int:
    return len(await working_days(db, date_from, date_to))
