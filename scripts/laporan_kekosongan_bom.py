"""Laporan jujur: model mana yang BOM/aksesorisnya BENAR-BENAR kosong — langsung dari DB (bukan dari Excel).

Jalankan:  cd /app/backend && set -a && . .env && set +a && python ../scripts/laporan_kekosongan_bom.py [--json out.json]
Hanya membaca DB. Status per model:
  A_TANPA_SKU              belum punya varian/SKU sama sekali → tidak bisa punya BOM
  B_ADA_SKU_NOL_BOM        punya varian aktif, tidak satu pun BOM
  C_SEBAGIAN_VARIAN_TANPA_BOM  sebagian varian aktif belum punya BOM
  D_BOM_TANPA_AKSESORIS    semua BOM ada tapi TIDAK ADA baris aksesoris (hanya potongan kain hasil impor)
  D2_SEBAGIAN_BOM_TANPA_AKSESORIS  sebagian BOM punya aksesoris, sebagian tidak (papan R&D lama TIDAK menandai ini)
  E_LENGKAP                semua varian aktif punya BOM dan semua BOM punya aksesoris
  F_DIHENTIKAN             punya varian tapi semua nonaktif → tidak perlu BOM
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter, defaultdict

from motor.motor_asyncio import AsyncIOMotorClient


def _acc(ln: dict) -> bool:
    return (ln.get("material_type") or ln.get("type")) == "accessory" and not ln.get("is_cut_panel")


async def analyse(db) -> list[dict]:
    models = await db.rahaza_models.find({"active": {"$ne": False}}, {"_id": 0, "id": 1, "code": 1, "name": 1}).sort("code", 1).to_list(5000)
    V, B = defaultdict(list), defaultdict(list)
    for v in await db.rahaza_model_variants.find({}, {"_id": 0}).to_list(50000):
        V[v["model_id"]].append(v)
    for b in await db.rahaza_boms.find({"active": {"$ne": False}}, {"_id": 0}).to_list(50000):
        B[b["model_id"]].append(b)
    out = []
    for m in models:
        mv, mb = V.get(m["id"], []), B.get(m["id"], [])
        act = [v for v in mv if v.get("active") is not False]
        keys = {((b.get("color_code") or "").upper(), b.get("size_id")) for b in mb}
        no_bom = [v["sku"] for v in act if ((v.get("color_code") or "").upper(), v.get("size_id")) not in keys]
        bom_no_acc = [b.get("color_code") for b in mb if not any(_acc(ln) for ln in b.get("materials") or [])]
        if mv and not act:
            st = "F_DIHENTIKAN"
        elif not mv:
            st = "A_TANPA_SKU"
        elif not mb:
            st = "B_ADA_SKU_NOL_BOM"
        elif no_bom:
            st = "C_SEBAGIAN_VARIAN_TANPA_BOM"
        elif len(bom_no_acc) == len(mb):
            st = "D_BOM_TANPA_AKSESORIS"
        elif bom_no_acc:
            st = "D2_SEBAGIAN_BOM_TANPA_AKSESORIS"
        else:
            st = "E_LENGKAP"
        out.append({"status": st, "code": m["code"], "name": m["name"], "varian_aktif": len(act), "varian_total": len(mv),
                    "bom_aktif": len(mb), "varian_tanpa_bom": no_bom, "bom_tanpa_aksesoris": bom_no_acc})
    return out


def print_report(rows: list[dict], title: str) -> None:
    c = Counter(r["status"] for r in rows)
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")
    print(f"total model aktif: {len(rows)}")
    for k in sorted(c):
        print(f"  {c[k]:3d}  {k}")
    need = [r for r in rows if r["status"] not in ("E_LENGKAP", "F_DIHENTIKAN")]
    print(f"\n→ HARUS DIISI: {len(need)} model  |  lengkap: {c.get('E_LENGKAP', 0)}  |  dihentikan (tidak perlu): {c.get('F_DIHENTIKAN', 0)}")
    for r in need:
        extra = ""
        if r["varian_tanpa_bom"]:
            extra = " varian tanpa BOM: " + ", ".join(r["varian_tanpa_bom"])
        elif r["status"] == "D2_SEBAGIAN_BOM_TANPA_AKSESORIS":
            extra = " BOM tanpa aksesoris: " + ", ".join(r["bom_tanpa_aksesoris"])
        print(f"  {r['status']:32s} {r['code']:8s} {r['name']:16s} varian {r['varian_aktif']:2d} · BOM {r['bom_aktif']:2d}{extra}")


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    rows = await analyse(db)
    print_report(rows, "KONDISI DB SAAT INI")
    if "--json" in sys.argv:
        json.dump(rows, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
