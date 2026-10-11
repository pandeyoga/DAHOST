"""Bersihkan harga potongan kain (CUT-*) yang bukan hasil cutting nyata → Rp 0 (unvalued).
HPP model yang bergantung pada potongan itu ditandai 'menunggu_cutting' (bukan angka basi).
Jalankan: cd /app/backend && set -a && . .env && set +a && python ../scripts/konsolidasi/bersihkan_harga_potongan.py
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc)
    q = {"is_cut_panel": True, "value_status": {"$ne": "actual"}}
    ids = [p["id"] async for p in db.rahaza_materials.find(q, {"_id": 0, "id": 1})]
    r = await db.rahaza_materials.update_many(q, {
        "$set": {"unit_cost": 0.0, "value_status": "unvalued", "cost_source": "menunggu_cutting", "updated_at": now,
                 "value_note": "Menunggu hasil Order Cutting: harga = total kain terpakai ÷ jumlah potongan (keputusan owner 2026-09-23)."},
        "$unset": {"standard_cost_basis": "", "_standard_cost_enabled": ""}})
    # baris BOM yang memakai potongan itu → unit_cost_base 0
    n_lines = 0
    async for b in db.rahaza_boms.find({"materials.material_id": {"$in": ids}}, {"_id": 0, "id": 1, "materials": 1}):
        mats = [dict(ln, unit_cost_base=0.0) if ln.get("material_id") in set(ids) else ln for ln in b["materials"]]
        await db.rahaza_boms.update_one({"id": b["id"]}, {"$set": {"materials": mats, "updated_at": now}})
        n_lines += 1
    # HPP model: potongan Rp 0 → HPP belum bisa terbit (aturan sistem) → tandai jujur, jangan biarkan angka basi
    model_ids = {b["model_id"] async for b in db.rahaza_boms.find({"active": True, "materials.material_id": {"$in": ids}}, {"_id": 0, "model_id": 1})}
    rm = await db.rahaza_models.update_many({"id": {"$in": list(model_ids)}}, {
        "$set": {"hpp": 0, "hpp_source": "menunggu_cutting",
                 "hpp_validation": {"status": "menunggu_cutting", "reasons": ["Potongan kain belum bernilai — menunggu Order Cutting pertama"], "at": now},
                 "hpp_updated_at": now},
        "$unset": {"hpp_breakdown": ""}})
    rf = await db.rahaza_materials.update_many({"type": "fg", "hpp": {"$gt": 0}}, {"$set": {"hpp": 0, "hpp_note": "menunggu_cutting", "updated_at": now}})
    await db.rahaza_material_cost_history.insert_one({"material_code": "CUT-*", "unit_cost": 0, "source": "bersihkan_harga_potongan_2026-09-23",
                                                      "note": f"{r.modified_count} potongan → 0; {rm.modified_count} model HPP menunggu cutting", "at": now})
    print(f"potongan dinolkan={r.modified_count} bom_diperbarui={n_lines} model_hpp_menunggu_cutting={rm.modified_count} fg_hpp_dinolkan={rf.modified_count}")


if __name__ == "__main__":
    asyncio.run(main())
