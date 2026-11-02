#!/usr/bin/env python3
"""scripts/check_fg_barcodes.py — audit kode barcode master barang (Paket 3a, 2026-11-02).

Fakta owner: barang jadi memakai **barcode SKU** (`rahaza_materials.code`, type `fg`,
= SKU varian `{MODEL}-{WARNA}-{UKURAN}`); bahan memakai kode master dari menu
"Buat Barcode". Skrip ini memeriksa apakah SETIAP barang punya kode yang bisa
dicetak & discan dengan benar:

  * FG tanpa kode/SKU, atau `code` ≠ `sku`;
  * kode yang tidak didukung Code128 (di luar ASCII cetak, spasi tepi, > 40 char)
    — aturan yang sama dengan pencetak label (`core.label_render.validate_code`);
  * kode KEMBAR (tanpa beda huruf besar/kecil) di antara barang aktif — scanner
    tidak bisa membedakan keduanya;
  * kode berisi spasi (sah untuk Code128, tetapi rawan salah ketik/scan) — dilaporkan;
  * SKU varian (`rahaza_model_variants.sku`) ≠ kode FG yang tertaut.

DRY-RUN BAWAAN. `--terapkan` HANYA mengisi FG yang `code`/`sku`-nya KOSONG dengan
usulan dari SKU varian (atau `make_sku(model, warna, ukuran, opsi)`) bila usulan itu
sah & tidak bentrok. Kode yang SUDAH ADA tidak pernah diubah: label fisik yang
sudah tertempel akan menjadi yatim — perubahan seperti itu keputusan owner.

Pakai:
    python3 scripts/check_fg_barcodes.py
    python3 scripts/check_fg_barcodes.py --terapkan
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def code_problem(code) -> str:
    """'' bila kode sah untuk Code128; selain itu alasannya — aturan SAMA dengan pencetak label."""
    from core.label_render import LabelCodeError, validate_code
    try:
        validate_code(code)
        return ""
    except LabelCodeError as e:
        return "kosong" if str(e) == "kode kosong" else str(e)


def propose_sku(fg: dict, variant: dict | None) -> str:
    if variant and variant.get("sku"):
        return str(variant["sku"]).strip().upper()
    from core.variant_identity import make_sku
    return make_sku(fg.get("model_code"), fg.get("color_code"), fg.get("size_code"),
                    fg.get("option_code"))


def audit(materials: list[dict], variants: list[dict]) -> dict:
    """Murni (tanpa DB) supaya bisa diuji unit."""
    active = [m for m in materials if m.get("active", True) is not False]
    fgs = [m for m in materials if m.get("type") == "fg"]
    var_by_id = {v.get("id"): v for v in variants}
    by_key = defaultdict(list)
    for m in active:
        if m.get("code"):
            by_key[str(m["code"]).strip().upper()].append(m)
    taken = set(by_key)

    out = {"fg_total": len(fgs), "fg_aktif": sum(1 for m in fgs if m.get("active", True) is not False),
           "fg_tanpa_kode": [], "fg_code_ne_sku": [], "kode_tidak_sah": [], "kode_kembar": [],
           "kode_berspasi": [], "sku_varian_beda": [], "usulan": []}
    for m in fgs:
        code, sku = (m.get("code") or "").strip(), (m.get("sku") or "").strip()
        if not code or not sku:
            var = var_by_id.get(m.get("variant_id"))
            prop = propose_sku(m, var)
            why = code_problem(prop) or ("bentrok dengan kode lain" if prop.upper() in taken and prop.upper() != code.upper() else "")
            row = {"id": m.get("id"), "name": m.get("name"), "code": code, "sku": sku,
                   "usulan": prop, "boleh_diterapkan": not why and not code, "alasan_tolak": why}
            out["fg_tanpa_kode"].append(row)
            if not why and (not code or not sku):
                out["usulan"].append(row)
        elif code.upper() != sku.upper():
            out["fg_code_ne_sku"].append({"id": m.get("id"), "code": code, "sku": sku})
        var = var_by_id.get(m.get("variant_id"))
        if var and var.get("sku") and code and str(var["sku"]).strip().upper() != code.upper():
            out["sku_varian_beda"].append({"id": m.get("id"), "code": code, "sku_varian": var["sku"]})
    for m in materials:
        p = code_problem(m.get("code"))
        if p and p != "kosong":
            out["kode_tidak_sah"].append({"id": m.get("id"), "type": m.get("type"), "code": m.get("code"), "alasan": p})
        if m.get("code") and " " in str(m["code"]).strip():
            out["kode_berspasi"].append({"id": m.get("id"), "type": m.get("type"), "code": m.get("code"),
                                         "name": m.get("name")})
    for key, rows in by_key.items():
        if len(rows) > 1:
            out["kode_kembar"].append({"kode": key, "barang": [(r.get("type"), r.get("code"), r.get("name")) for r in rows]})
    return out


async def run(db, *, apply: bool) -> dict:
    materials = await db.rahaza_materials.find(
        {}, {"_id": 0, "id": 1, "code": 1, "sku": 1, "type": 1, "name": 1, "active": 1, "variant_id": 1,
             "model_code": 1, "color_code": 1, "size_code": 1, "option_code": 1}).to_list(200000)
    variants = await db.rahaza_model_variants.find(
        {}, {"_id": 0, "id": 1, "sku": 1, "active": 1}).to_list(200000)
    res = audit(materials, variants)
    res["diterapkan"] = 0
    if apply:
        for row in res["usulan"]:
            patch = {"updated_at": datetime.now(timezone.utc), "barcode_backfill": "2026-11-02"}
            if not row["code"]:
                patch["code"] = row["usulan"]
            if not row["sku"]:
                patch["sku"] = row["usulan"] if not row["code"] else row["code"]
            r = await db.rahaza_materials.update_one(
                {"id": row["id"], "type": "fg"}, {"$set": patch})
            res["diterapkan"] += r.modified_count
    return res


def _print(res: dict, apply: bool, dbname: str) -> None:
    print(f"[Paket 3a] Audit barcode master · DB {dbname} · {'TERAPKAN' if apply else 'DRY-RUN'}")
    print(f"  FG: {res['fg_total']} ({res['fg_aktif']} aktif)")
    for key, label in (("fg_tanpa_kode", "FG tanpa kode/SKU"), ("fg_code_ne_sku", "FG code ≠ sku"),
                       ("kode_tidak_sah", "kode tidak sah untuk Code128"), ("kode_kembar", "kode kembar (aktif)"),
                       ("kode_berspasi", "kode berisi spasi (perlu keputusan owner)"),
                       ("sku_varian_beda", "SKU varian ≠ kode FG")):
        rows = res[key]
        print(f"  {label}: {len(rows)}")
        for r in rows[:25]:
            print(f"     · {r}")
    print(f"  usulan pengisian (hanya FG kosong): {len(res['usulan'])}")
    if apply:
        print(f"  diterapkan: {res['diterapkan']}")
    elif res["usulan"]:
        print("Jalankan ulang dengan --terapkan untuk mengisi kode yang kosong.")


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--terapkan", action="store_true", help="isi kode FG yang kosong (bawaan: dry-run)")
    a = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "backend" / ".env")
    except Exception:  # noqa: BLE001
        pass
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    try:
        res = await run(client[os.environ["DB_NAME"]], apply=a.terapkan)
    finally:
        client.close()
    _print(res, a.terapkan, os.environ["DB_NAME"])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
