#!/usr/bin/env python3
"""scripts/match_catalog_sku.py — K8 (keputusan owner 2026-11-02): COCOKKAN ITEM KATALOG.

Audit m.md No.9: 640 dari 682 item katalog (data go-live) TIDAK punya `catalog_id`,
padahal impor pesanan & layar Pemetaan SKU mencari item lewat katalog toko
(`marketing_catalogs.account_id` → `marketing_catalog_items.catalog_id`). Akibatnya Seller
SKU yang jelas ada di katalog toko tetap "belum tertaut".

Pencocokan (tanpa menebak):
  * katalog tujuan = katalog milik toko item itu (`account_id`);
  * identitas barang diperiksa ke master: `fg_material_id` harus ada di `rahaza_materials`,
    dan kode SKU item = kode FG master (atau = kode varian bila `variant_id` diisi);
  * SKU yang sama tidak boleh sudah ada di katalog tujuan (duplikat).

Hasil per item:
  COCOK       — satu katalog toko, FG ada, SKU = kode FG/varian, tidak duplikat
  RAGU        — toko punya >1 katalog, SKU ≠ kode FG/varian, SKU duplikat, atau FG bukan barang jadi
  TIDAK COCOK — toko tanpa katalog / item tanpa toko / item tanpa FG / FG tidak ada di master

DRY-RUN BAWAAN. Laporan CSV selalu ditulis. `--terapkan` HANYA mengisi `catalog_id`
untuk yang COCOK (ditandai `catalog_link_source=match_catalog_sku_k8` + waktu).

Pakai:
    python3 scripts/match_catalog_sku.py                       # laporan CSV (dry-run)
    python3 scripts/match_catalog_sku.py --csv /tmp/k8.csv
    python3 scripts/match_catalog_sku.py --terapkan
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

COCOK, RAGU, TIDAK = "cocok", "ragu", "tidak_cocok"
NO_CATALOG = {"$or": [{"catalog_id": None}, {"catalog_id": ""}, {"catalog_id": {"$exists": False}}]}


def _norm(s) -> str:
    return str(s or "").strip().upper()


def classify(item: dict, catalogs_of_account: list, material: dict | None,
             variant: dict | None, existing_skus_in_catalog: set) -> tuple:
    """Murni (diuji): → ``(status, catalog_id|None, alasan)``."""
    if not item.get("account_id"):
        return TIDAK, None, "item tanpa toko (account_id kosong)"
    if not catalogs_of_account:
        return TIDAK, None, "toko belum punya katalog"
    if not item.get("fg_material_id"):
        return TIDAK, None, "item tanpa tautan barang jadi (fg_material_id kosong)"
    if not material:
        return TIDAK, None, f"FG {item.get('fg_material_id')} tidak ada di master material"
    if len(catalogs_of_account) > 1:
        return RAGU, None, f"toko punya {len(catalogs_of_account)} katalog — pilih manual"
    cat_id = catalogs_of_account[0]["id"]
    sku = _norm(item.get("sku"))
    codes = {_norm(material.get("code")), _norm(material.get("sku"))} - {""}
    if variant:
        codes |= {_norm(variant.get("sku")), _norm(variant.get("code"))} - {""}
    if (material.get("type") or "fg").lower() not in ("fg", "finished_goods", "barang_jadi"):
        return RAGU, cat_id, f"master {material.get('code')} bukan barang jadi (type={material.get('type')})"
    if not sku:
        return RAGU, cat_id, "SKU item kosong"
    if sku not in codes:
        return RAGU, cat_id, f"SKU {item.get('sku')} ≠ kode FG/varian {', '.join(sorted(codes)) or '-'}"
    if sku in existing_skus_in_catalog:
        return RAGU, cat_id, f"SKU {item.get('sku')} sudah ada di katalog tujuan (duplikat)"
    return COCOK, cat_id, "SKU = kode FG master; satu katalog toko"


async def run(db, *, apply: bool, csv_path: Path) -> dict:
    items = await db.marketing_catalog_items.find(NO_CATALOG, {"_id": 0}).to_list(100000)
    cats_by_acc = defaultdict(list)
    async for c in db.marketing_catalogs.find({}, {"_id": 0, "id": 1, "account_id": 1, "name": 1}):
        cats_by_acc[c.get("account_id")].append(c)
    mids = sorted({i.get("fg_material_id") for i in items if i.get("fg_material_id")})
    mats = {m["id"]: m async for m in db.rahaza_materials.find(
        {"id": {"$in": mids}}, {"_id": 0, "id": 1, "code": 1, "sku": 1, "type": 1, "name": 1})}
    vids = sorted({i.get("variant_id") for i in items if i.get("variant_id")})
    variants = {v["id"]: v async for v in db.rahaza_model_variants.find(
        {"id": {"$in": vids}}, {"_id": 0, "id": 1, "sku": 1, "code": 1})} if vids else {}
    skus_in_cat = defaultdict(set)
    async for it in db.marketing_catalog_items.find({"catalog_id": {"$nin": [None, ""]}},
                                                    {"_id": 0, "catalog_id": 1, "sku": 1}):
        skus_in_cat[it["catalog_id"]].add(_norm(it.get("sku")))
    accounts = {a["id"]: a.get("account_code") async for a in db.marketing_platform_accounts.find(
        {}, {"_id": 0, "id": 1, "account_code": 1})}

    rows, counts, applied = [], Counter(), 0
    planned_per_cat = defaultdict(set)
    for it in items:
        cats = cats_by_acc.get(it.get("account_id")) or []
        cat_id = cats[0]["id"] if len(cats) == 1 else None
        taken = skus_in_cat.get(cat_id, set()) | planned_per_cat.get(cat_id, set())
        st, cid, why = classify(it, cats, mats.get(it.get("fg_material_id")),
                                variants.get(it.get("variant_id")), taken)
        if st == COCOK:
            planned_per_cat[cid].add(_norm(it.get("sku")))
        counts[st] += 1
        rows.append({"status": st, "item_id": it.get("id"), "toko": accounts.get(it.get("account_id"), ""),
                     "sku": it.get("sku") or "", "nama": it.get("name") or "",
                     "fg_material_id": it.get("fg_material_id") or "",
                     "kode_fg": (mats.get(it.get("fg_material_id")) or {}).get("code", ""),
                     "catalog_id_tujuan": cid or "", "alasan": why})
        if apply and st == COCOK:
            r = await db.marketing_catalog_items.update_one(
                {"id": it["id"], **NO_CATALOG},
                {"$set": {"catalog_id": cid, "catalog_link_source": "match_catalog_sku_k8",
                          "catalog_linked_at": datetime.now(timezone.utc)}})
            applied += r.modified_count
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["status"])
        w.writeheader()
        w.writerows(rows)
    return {"scanned": len(items), "counts": dict(counts), "applied": applied, "csv": str(csv_path)}


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--terapkan", action="store_true", help="isi catalog_id untuk yang COCOK saja")
    ap.add_argument("--csv", default="", help="lokasi laporan CSV (bawaan ./match_catalog_sku_<waktu>.csv)")
    a = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "backend" / ".env")
    except Exception:  # noqa: BLE001
        pass
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    try:
        res = await run(client[os.environ["DB_NAME"]], apply=a.terapkan,
                        csv_path=Path(a.csv or f"match_catalog_sku_{datetime.now():%Y%m%d_%H%M%S}.csv"))
    finally:
        client.close()
    mode = "TERAPKAN" if a.terapkan else "DRY-RUN"
    print(f"[K8] Pencocokan katalog · DB {os.environ['DB_NAME']} · {mode}")
    print(f"  item tanpa catalog_id: {res['scanned']} · {res['counts']}")
    print(f"  catalog_id diisi: {res['applied']} · laporan: {res['csv']}")
    if not a.terapkan:
        print("Jalankan ulang dengan --terapkan untuk mengisi catalog_id item yang COCOK.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
