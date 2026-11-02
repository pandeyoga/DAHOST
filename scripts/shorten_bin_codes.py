#!/usr/bin/env python3
"""scripts/shorten_bin_codes.py — pendekkan kode bin lama > 18 karakter (keputusan barcode owner, 2026-11-02).

Kode bin `{GEDUNG}-{ZONA}-{RAK}-Sxx-Pyy` yang panjang tidak terbaca andal di label 65 mm (uji decode
203 dpi: 25 karakter → 10/24). Skrip ini memakai GENERATOR YANG SAMA dengan pembuatan rak
(`routes.wms_structure.assign_bin_prefix` / `bin_code`) sehingga kode hasil migrasi = kode rak baru.

  * Per rak yang punya posisi ber-kode > 18 karakter: awalan pendek unik → kode baru per posisi.
  * Kode lama disimpan di `wh_positions.barcode_aliases` → label lama yang sudah tertempel tetap
    dikenali resolver (`core.scan_resolver.resolve_bin`, via `barcode_posisi_lama`).
  * Riwayat (`position_barcode` di mutasi/log) TIDAK diubah — itu catatan saat kejadian.
  * Posisi tanpa rak dilaporkan saja.

DRY-RUN BAWAAN; `--terapkan` menulis backup JSON (rak + posisi yang berubah) lalu mengubah data.
    python3 scripts/shorten_bin_codes.py
    python3 scripts/shorten_bin_codes.py --terapkan [--backup-dir backups/]
Setelah diterapkan: cetak ulang label rak (Struktur Gudang → ikon printer per rak).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def plan(db) -> dict:
    from routes.wms_structure import BIN_CODE_MAX, assign_bin_prefix, bin_code
    racks = {r["id"]: r for r in await db.wh_racks.find({}, {"_id": 0}).to_list(None)}
    long_pos = [p for p in await db.wh_positions.find({}, {"_id": 0}).to_list(None)
                if len(str(p.get("barcode") or "")) > BIN_CODE_MAX]
    by_rack: dict = {}
    orphans = []
    for p in long_pos:
        if p.get("rack_id") in racks:
            by_rack.setdefault(p["rack_id"], []).append(p)
        else:
            orphans.append(p)
    taken: set = set()
    out = []
    for rid in sorted(by_rack, key=lambda x: (racks[x].get("building_code") or "", racks[x].get("zone_code") or "",
                                               racks[x].get("code") or "")):
        rack = dict(racks[rid])
        rack.pop("bin_prefix", None)            # awalan lama (bila ada) dihitung ulang
        prefix = await assign_bin_prefix(db, rack, taken=taken)
        taken.add(prefix.upper())
        changes = [{"id": p["id"], "old": p["barcode"],
                    "new": bin_code(prefix, p.get("shelf_no") or 1, p.get("slot_no") or 1)}
                   for p in sorted(by_rack[rid], key=lambda x: (x.get("shelf_no") or 0, x.get("slot_no") or 0))]
        out.append({"rack_id": rid, "rack": f"{rack.get('building_code')}/{rack.get('zone_code')}/{rack.get('code')}",
                    "prefix": prefix, "changes": changes})
    return {"racks": out, "orphans": [{"id": p["id"], "barcode": p["barcode"]} for p in orphans],
            "total_long": len(long_pos)}


async def apply(db, p: dict, backup_dir: Path) -> dict:
    now = datetime.now(timezone.utc)
    ids = [c["id"] for r in p["racks"] for c in r["changes"]]
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = {"dibuat": now.isoformat(), "racks": await db.wh_racks.find(
        {"id": {"$in": [r["rack_id"] for r in p["racks"]]}}, {"_id": 0}).to_list(None),
        "positions": await db.wh_positions.find({"id": {"$in": ids}}, {"_id": 0}).to_list(None)}
    bfile = backup_dir / f"shorten_bin_codes_{now:%Y%m%d_%H%M%S}.json"
    bfile.write_text(json.dumps(backup, default=str, ensure_ascii=False, indent=1), encoding="utf-8")
    n = 0
    for r in p["racks"]:
        await db.wh_racks.update_one({"id": r["rack_id"]}, {"$set": {"bin_prefix": r["prefix"], "updated_at": now}})
        for c in r["changes"]:
            res = await db.wh_positions.update_one(
                {"id": c["id"], "barcode": c["old"]},
                {"$set": {"barcode": c["new"], "barcode_shortened_at": now},
                 "$addToSet": {"barcode_aliases": c["old"]}})
            n += res.modified_count
    return {"backup": str(bfile), "positions": n, "racks": len(p["racks"])}


def _print(p: dict, apply_: bool, dbname: str, done) -> None:
    print(f"[shorten_bin_codes] DB {dbname} · {'TERAPKAN' if apply_ else 'DRY-RUN'} · "
          f"{p['total_long']} posisi ber-kode > 18 karakter")
    for r in p["racks"]:
        print(f"  rak {r['rack']} → awalan {r['prefix']} ({len(r['changes'])} posisi)")
        for c in r["changes"][:3]:
            print(f"     {c['old']} ({len(c['old'])}) → {c['new']} ({len(c['new'])})")
        if len(r["changes"]) > 3:
            print(f"     … {len(r['changes']) - 3} posisi lain")
    for o in p["orphans"][:20]:
        print(f"  TANPA RAK (dilaporkan saja): {o['barcode']} ({o['id']})")
    if done:
        print(f"  backup: {done['backup']} · diubah {done['positions']} posisi di {done['racks']} rak")
        print("  Cetak ulang label rak dari Struktur Gudang; label lama tetap terbaca (alias).")
    elif p["racks"]:
        print("Jalankan ulang dengan --terapkan untuk menerapkan (backup JSON dibuat dulu).")


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--terapkan", action="store_true", help="ubah data (bawaan: dry-run)")
    ap.add_argument("--backup-dir", default=str(ROOT / "backups"), help="folder backup JSON")
    a = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "backend" / ".env")
    except Exception:  # noqa: BLE001
        pass
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    try:
        db = client[os.environ["DB_NAME"]]
        p = await plan(db)
        done = await apply(db, p, Path(a.backup_dir)) if a.terapkan else None
    finally:
        client.close()
    _print(p, a.terapkan, os.environ["DB_NAME"], done)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
