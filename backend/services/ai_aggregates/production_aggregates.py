"""Production & maklon aggregates for AI endpoints.

T-03 (FASE 3): SSOT WO = production_jobs via core.wo_reader (rahaza_work_orders diarsip).
Bentuk keluaran lama dipertahankan: order_code<-wo_number, product_name<-model_name,
quantity<-qty, target_date<-due_date.
"""
from __future__ import annotations

from datetime import datetime, timezone

_ACTIVE_WO_STATUSES = ["in_progress", "released"]


async def production_summary(db, *, since_iso: str) -> dict:
    """Counts of WOs created and completed since timestamp."""
    from core.wo_reader import count_wos
    new_count = await count_wos(db, created_since=since_iso)
    done_count = await count_wos(db, statuses=["completed"], completed_since=since_iso)
    return {"work_order_baru": new_count, "work_order_selesai": done_count}


async def maklon_summary(db, *, since_iso: str, lmo_adapter) -> dict:
    """Counts of maklon orders entered and completed via SSOT view."""
    new_count = await lmo_adapter(db).count_documents({"order_date": {"$gte": since_iso}})
    done_count = await lmo_adapter(db).count_documents({
        "stage": {"$in": ["completed", "invoiced"]},
        "updated_at": {"$gte": since_iso},
    })
    return {"order_masuk": new_count, "order_selesai": done_count}


async def active_workorders(db, *, limit: int = 10) -> list[dict]:
    """Top active work orders (projection only)."""
    from core.wo_reader import load_wos
    rows = sorted(await load_wos(db, statuses=_ACTIVE_WO_STATUSES),
                  key=lambda r: str(r.get("due_date") or "9999"))[:limit]
    # Bentuk output kompatibel dgn konsumen lama
    return [
        {
            "id": r.get("id"),
            "order_code": r.get("wo_number", ""),
            "product_name": r.get("model_name", ""),
            "quantity": r.get("qty", 0),
            "priority": r.get("priority", "normal"),
            "target_date": r.get("target_date") or r.get("due_date"),
            "status": r.get("status"),
            "stage": r.get("status"),
        }
        for r in rows
    ]


async def active_maklon(db, *, lmo_adapter, limit: int = 10) -> list[dict]:
    return await lmo_adapter(db).find(
        {"stage": {"$in": ["confirmed", "material_ready", "cutting", "sewing", "qc"]}},
        {
            "_id": 0, "order_code": 1, "garment_type": 1,
            "quantity": 1, "deadline_date": 1, "stage": 1,
        },
    ).sort("deadline_date", 1).limit(limit).to_list(limit)


async def production_counts(db, *, lmo_adapter) -> dict:
    """Counts of active WOs/maklon for optimizer overview."""
    from core.wo_reader import count_wos
    wo_active = await count_wos(db, statuses=_ACTIVE_WO_STATUSES)
    maklon_active = await lmo_adapter(db).count_documents(
        {"stage": {"$in": ["confirmed", "material_ready", "cutting", "sewing", "qc"]}}
    )
    return {"wo_active": wo_active, "maklon_active": maklon_active}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
