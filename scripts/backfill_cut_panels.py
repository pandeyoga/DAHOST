"""Backfill master POTONGAN (CUT-<MODEL>-<WARNA>-<UKURAN>) untuk semua varian aktif
yang belum punya — idempoten, tidak menyentuh potongan yang sudah ada.

    cd /app/backend && python /app/scripts/backfill_cut_panels.py [--dry-run]
"""
import asyncio, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from core.cut_panel_master import ensure_panel_for_variant  # noqa: E402


async def main(dry: bool):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    models = {m["id"]: m async for m in db.rahaza_models.find({}, {"_id": 0, "sop_steps": 0})}
    created, existing = [], 0
    async for v in db.rahaza_model_variants.find({"active": {"$ne": False}}, {"_id": 0}):
        model = models.get(v.get("model_id"))
        if not model:
            continue
        if dry:
            from core.cut_panel_master import panel_code, find_panel
            code = panel_code(model.get("code") or "", v.get("color_code") or "", v.get("size_code") or "")
            if await find_panel(db, model_id=model["id"], color_code=v.get("color_code") or "",
                                size_code=v.get("size_code") or "", code=code):
                existing += 1
            else:
                created.append(code)
            continue
        panel, new = await ensure_panel_for_variant(db, v, model)
        if new:
            created.append(panel["code"])
        else:
            existing += 1
    print(f"{'DRY-RUN ' if dry else ''}potongan sudah ada: {existing} · dibuat: {len(created)}")
    for c in created[:30]:
        print("  +", c)


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
