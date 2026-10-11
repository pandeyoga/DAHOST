"""T-07 — hapus job produksi SATU PINTU: void JE WIP→FG, bersihkan layer/snapshot/cermin.

Dipakai `routes/production_execution.delete_job` dan `routes/vendor_shipment.delete_vendor_shipment`.
Job yang JE-nya berada di periode terkunci → raise HTTPException 409 (tidak menghapus apa pun).
"""
from datetime import date

from fastapi import HTTPException

WIP_FG_SOURCE_MODULE = "production_job"


def _wip_fg_ref(job_id: str) -> str:
    return f"wip_fg_job:{job_id}"


async def _assert_job_deletable(db, job_id: str) -> None:
    from routes.rahaza_posting import _ensure_period_open, _find_existing_je
    je = await _find_existing_je(db, WIP_FG_SOURCE_MODULE, _wip_fg_ref(job_id))
    if not je:
        return
    err = await _ensure_period_open(db, date.fromisoformat(je["date"]))
    if err:
        raise HTTPException(409, f"Job punya jurnal {je.get('je_number')} di periode terkunci — {err}")


async def _purge_job_side_effects(db, job_id: str, user: dict, reason: str) -> dict:
    from routes.rahaza_posting import _void_je_by_source
    void_res = await _void_je_by_source(db, WIP_FG_SOURCE_MODULE, _wip_fg_ref(job_id), user, reason)
    if not void_res.get("ok"):
        raise HTTPException(409, f"Jurnal job tidak bisa di-void: {void_res.get('error')}")
    layers = await db.fg_cost_layers.delete_many({"gl_job_id": job_id})
    snaps = await db.rahaza_hpp_snapshots.delete_many({"job_id": job_id})
    wip = await db.rahaza_wip_events.delete_many({"job_id": job_id})
    await db.production_job_items.delete_many({"job_id": job_id})
    await db.production_progress.delete_many({"job_id": job_id})
    return {"je_voided": bool(void_res.get("voided")), "je_number": void_res.get("je_number"),
            "fg_cost_layers": layers.deleted_count, "hpp_snapshots": snaps.deleted_count,
            "wip_events": wip.deleted_count}


async def delete_production_job(db, job_id: str, user: dict, *, reason: str = "job dihapus") -> dict:
    """Hapus job + anak-anaknya. Cek periode untuk semua JE dulu, baru menghapus."""
    child_ids = [c["id"] for c in await db.production_jobs.find(
        {"parent_job_id": job_id}, {"_id": 0, "id": 1}).to_list(1000)]
    for jid in child_ids + [job_id]:
        await _assert_job_deletable(db, jid)
    summary = {"job_id": job_id, "children": [], "je_voided": 0, "fg_cost_layers": 0,
               "hpp_snapshots": 0, "wip_events": 0}
    for jid in child_ids + [job_id]:
        r = await _purge_job_side_effects(db, jid, user, reason)
        await db.production_jobs.delete_one({"id": jid})
        summary["je_voided"] += int(r["je_voided"])
        for k in ("fg_cost_layers", "hpp_snapshots", "wip_events"):
            summary[k] += r[k]
        if jid != job_id:
            summary["children"].append(jid)
    return summary
