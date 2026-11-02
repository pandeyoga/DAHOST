#!/usr/bin/env python3
"""scripts/migrate_fg_wac_init.py — WAC awal barang jadi (keputusan owner No.26a, 2026-11-02).

Barang jadi pindah dari FIFO lapisan ke rata-rata bergerak (WAC). WAC awal per FG dihitung
dengan rumus SSOT `core.fg_cost_layers.initial_wac_from_layers`:

    WAC awal = Σ (qty_remaining × unit_cost) / Σ qty_remaining     (lapisan yang masih bersisa)

= nilai lapisan yang selama ini dibukukan ke 1-1404, jadi rekonsiliasi FG tidak bergeser saat
pindah metode. Komponen (bahan/upah/overhead) = rata-rata tertimbang rincian lapisan.

Yang DILAPORKAN (bukan ditebak):
  * FG dengan lapisan Rp 0 yang masih bersisa → perlu BACKFILL biaya (BOM/jahit SPK) dulu;
  * FG yang punya stok bernilai tetapi tanpa lapisan → WAC 0, perlu nilai awal (opname No.27);
  * FG dengan `unit_cost` lama tanpa lapisan → dipakai apa adanya (`legacy_unit_cost`);
  * selisih stok bernilai vs sisa lapisan (qty) — sumber selisih nilai FG vs GL.

DRY-RUN BAWAAN (tidak menulis apa pun). `--terapkan` menulis WAC awal lewat fungsi yang SAMA
dengan inisialisasi otomatis di kode (`fcl.wac_state`), hanya untuk FG yang belum dinilai WAC.
Idempoten. Kode aplikasi juga menginisialisasi FG saat pertama kali tersentuh, jadi skrip ini
untuk laporan & inisialisasi massal sebelum laporan Nilai FG dibaca.

Pakai:
    python3 scripts/migrate_fg_wac_init.py                 # laporan dry-run
    python3 scripts/migrate_fg_wac_init.py --json out.json # + rincian per SKU ke berkas
    python3 scripts/migrate_fg_wac_init.py --terapkan
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def plan_for(mat: dict, layers: list, valued_qty: float) -> dict:
    """Rencana WAC awal satu FG (fungsi murni)."""
    from core import fg_cost_layers as fcl
    ini = fcl.initial_wac_from_layers(layers)
    legacy = float(mat.get("unit_cost") or 0)
    initialized = isinstance(mat.get(fcl.WAC_COMPONENTS), dict)
    wac, src = ini["unit_cost"], ("init_from_layers" if ini["qty"] > 0 else "none")
    if initialized:                       # sudah ber-WAC: angka berjalan, bukan rencana awal
        wac, src = round(legacy, 4), mat.get("wac_source") or "wac"
    elif ini["qty"] <= 0 and legacy > 0:
        wac, src = round(legacy, 4), "legacy_unit_cost"
    flags = []
    if ini["zero_cost_layers"] and not initialized:
        flags.append("lapisan_rp0_perlu_backfill")
    if valued_qty > 0 and wac <= 0:
        flags.append("stok_tanpa_biaya")
    if not initialized and abs(valued_qty - ini["qty"]) > 0.0001 and (ini["qty"] or valued_qty):
        flags.append("stok_beda_dengan_lapisan")
    return {"material_id": mat.get("id"), "code": mat.get("code") or "", "name": mat.get("name") or "",
            "already_initialized": initialized, "current_unit_cost": legacy,
            "hpp_master": float(mat.get("hpp") or 0), "hpp_source": mat.get("hpp_source") or "",
            "hpp_fifo_avg_old": float(mat.get("hpp_fifo_avg") or 0),
            "wac_initial": wac, "wac_source": src, "components": ini["components"],
            "layer_qty": ini["qty"], "layer_value": ini["value"], "open_layers": ini["open_layers"],
            "zero_cost_layers": ini["zero_cost_layers"], "zero_cost_qty": ini["zero_cost_qty"],
            "valued_qty": round(valued_qty, 4), "value_at_wac": round(valued_qty * wac, 2),
            "flags": flags}


async def run(db, *, apply: bool) -> dict:
    from core import fg_cost_layers as fcl
    from core.catalog_stock import blocked_location_ids
    layers = await db.fg_cost_layers.find({}, {"_id": 0}).to_list(200000)
    by_mat: dict = {}
    for ly in layers:
        by_mat.setdefault(ly.get("material_id") or "", []).append(ly)
    mats = await db.rahaza_materials.find(
        {"$or": [{"type": "fg"}, {"id": {"$in": [m for m in by_mat if m]}}]}, {"_id": 0}).to_list(200000)
    ids = [m["id"] for m in mats]
    blocked = await blocked_location_ids(db)
    from core.stock_schema import read_qty
    qty_by: dict = {}
    async for s in db.rahaza_material_stock.find({"material_id": {"$in": ids}}, {"_id": 0}):
        if fcl.is_valued_row(s, blocked):
            qty_by[s["material_id"]] = qty_by.get(s["material_id"], 0.0) + read_qty(s)
    plans = [plan_for(m, by_mat.get(m["id"], []), qty_by.get(m["id"], 0.0)) for m in mats]
    out = {"fg_total": len(plans),
           "already_initialized": sum(1 for p in plans if p["already_initialized"]),
           "with_layers": sum(1 for p in plans if p["open_layers"]),
           "zero_cost_layer_skus": [p for p in plans if "lapisan_rp0_perlu_backfill" in p["flags"]],
           "stock_without_cost": [p for p in plans if "stok_tanpa_biaya" in p["flags"]],
           "stock_vs_layer_diff": [p for p in plans if "stok_beda_dengan_lapisan" in p["flags"]],
           "legacy_unit_cost": [p for p in plans if p["wac_source"] == "legacy_unit_cost"],
           "value_at_wac": round(sum(p["value_at_wac"] for p in plans), 2),
           "layer_value": round(sum(p["layer_value"] for p in plans), 2),
           "applied": 0, "plans": plans}
    if apply:
        for p in plans:
            if p["already_initialized"] or p["wac_source"] == "none":   # tanpa lapisan & biaya: tidak ada yang ditulis
                continue
            await fcl.wac_state(db, p["material_id"], actor={"name": "migrate_fg_wac_init"})
            out["applied"] += 1
    return out


def _line(p: dict) -> str:
    return (f"   · {p['code'] or p['material_id'][:8]:<28} WAC awal {p['wac_initial']:>14,.2f} "
            f"({p['wac_source']}) · stok {p['valued_qty']:g} · lapisan {p['layer_qty']:g} "
            f"(Rp0: {p['zero_cost_layers']} lapisan/{p['zero_cost_qty']:g} pcs)")


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--terapkan", action="store_true", help="tulis WAC awal (bawaan: dry-run)")
    ap.add_argument("--json", help="simpan rincian per SKU ke berkas JSON")
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
    print(f"[No.26a] WAC awal barang jadi · DB {os.environ['DB_NAME']} · "
          f"{'TERAPKAN' if a.terapkan else 'DRY-RUN'}")
    print(f"  FG: {res['fg_total']} · sudah ber-WAC: {res['already_initialized']} · "
          f"punya lapisan bersisa: {res['with_layers']}")
    print(f"  nilai lapisan sekarang Rp {res['layer_value']:,.2f} · Σ stok bernilai × WAC awal "
          f"Rp {res['value_at_wac']:,.2f}")
    for title, key in (("FG dengan lapisan Rp 0 — PERLU BACKFILL biaya", "zero_cost_layer_skus"),
                       ("FG berstok tanpa biaya (WAC 0) — perlu nilai awal/opname", "stock_without_cost"),
                       ("FG stok ≠ sisa lapisan", "stock_vs_layer_diff"),
                       ("FG memakai unit_cost lama (tanpa lapisan)", "legacy_unit_cost")):
        rows = res[key]
        print(f"  {title}: {len(rows)}")
        for p in rows[:25]:
            print(_line(p))
        if len(rows) > 25:
            print(f"   … {len(rows) - 25} lagi (pakai --json)")
    if a.json:
        Path(a.json).write_text(json.dumps(res["plans"], ensure_ascii=False, indent=1, default=str),
                                encoding="utf-8")
        print(f"  rincian per SKU → {a.json}")
    if a.terapkan:
        print(f"  diinisialisasi: {res['applied']} FG")
    else:
        print("Jalankan ulang dengan --terapkan untuk menulis WAC awal.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
