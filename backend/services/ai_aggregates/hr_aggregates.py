"""HR aggregates for AI endpoints."""
from __future__ import annotations

from datetime import datetime


async def attendance_issues(db, *, since: datetime) -> int:
    """Count attendance events that are late or non-present since date.

    T-17 (FASE 3): SSOT = rahaza_attendance_events (rahaza_attendance tak pernah ditulis).
    """
    return await db.rahaza_attendance_events.count_documents({
        "date": {"$gte": since.strftime("%Y-%m-%d")},
        "$or": [{"is_late": True}, {"status": {"$in": ["alfa", "alpha", "izin", "sakit", "absent", "late"]}}],
    })


async def production_employee_count(db) -> int:
    """Active employees in production departments."""
    return await db.rahaza_employees.count_documents({
        "employment_status": "active",
        "department": {"$in": ["Produksi", "Production", "Jahit"]},
    })
