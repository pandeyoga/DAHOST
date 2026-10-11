#!/usr/bin/env python3
"""scripts/verify_bom_idempotent.py — UJI IDEMPOTEN WAJIB importir BOM_AKSESORIS.

    python3 scripts/verify_bom_idempotent.py /path/berkas.xlsx

Alur: snapshot rahaza_boms → apply #1 → snapshot → apply #2 → snapshot. Lulus bila:
  * jumlah dokumen rahaza_boms setelah #1 == setelah #2,
  * isi `materials` tiap BOM identik (kode, qty, unit, qty_base) antara #1 dan #2,
  * apply #2 melaporkan boms_touched == 0 dan bom_lines_appended == 0.
Skrip ini MENGUBAH DB (memakai MONGO_URL/DB_NAME dari backend/.env) — jalankan di preview, bukan VPS.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def snapshot(db) -> dict:
    out = {}
    async for b in db.rahaza_boms.find({"active": {"$ne": False}, "is_active": True}, {"_id": 0, "id": 1, "model_id": 1, "size_id": 1, "color_code": 1, "materials": 1}):
        out[(b["model_id"], b.get("size_id"), (b.get("color_code") or "").upper())] = tuple(
            (ln.get("code"), round(float(ln.get("qty") or 0), 6), ln.get("unit"), round(float(ln.get("qty_base") or 0), 6)) for ln in b.get("materials") or [])
    return out


async def main(path: Path) -> int:
    from dotenv import load_dotenv
    from motor.motor_asyncio import AsyncIOMotorClient
    load_dotenv(ROOT / "backend" / ".env")
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    from core import master_fill as mf
    data = path.read_bytes()
    user = {"id": "system", "name": "verify_idempotent"}
    before = await snapshot(db)
    parsed = await mf.parse_fill_workbook(db, data)
    print(f"parse: {parsed['totals']['bom_lines']} baris · {parsed['totals']['bom_groups']} kelompok · {parsed['totals']['bom_models']} model · {parsed['totals']['bom_skipped']} dilewati")
    r1 = await mf.apply_fill(db, parsed, user, scope="bom")
    s1 = await snapshot(db)
    print(f"apply #1: touched={r1['boms_touched']} appended={r1['bom_lines_appended']} replaced={r1['bom_lines_replaced']} base_created={r1['bom_base_created']} "
          f"hpp_unvalidated={r1['hpp_unvalidated']} · dokumen BOM {len(before)} → {len(s1)}")
    parsed2 = await mf.parse_fill_workbook(db, data)
    r2 = await mf.apply_fill(db, parsed2, user, scope="bom")
    s2 = await snapshot(db)
    print(f"apply #2: touched={r2['boms_touched']} appended={r2['bom_lines_appended']} replaced={r2['bom_lines_replaced']} base_created={r2['bom_base_created']} · dokumen BOM {len(s2)}")
    diff = [k for k in set(s1) | set(s2) if s1.get(k) != s2.get(k)]
    # model yang tidak disebut berkas tidak boleh berubah
    touched_models = {g["model_id"] for g in parsed["bom_groups"]}
    untouched_changed = [k for k in set(before) | set(s1) if k[0] not in touched_models and before.get(k) != s1.get(k)]
    ok = len(s1) == len(s2) and not diff and r2["boms_touched"] == 0 and r2["bom_lines_appended"] == 0 and r2["bom_base_created"] == 0 and not untouched_changed
    print(("LULUS" if ok else "GAGAL") + f": dokumen sama={len(s1) == len(s2)} · isi beda={len(diff)} · model di luar berkas berubah={len(untouched_changed)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(Path(sys.argv[1]))))
