#!/usr/bin/env python3
"""scripts/release_manual_order_reservations.py — K6 (keputusan owner 2026-11-02).

Reservasi stok untuk ORDER MANUAL Marketing dimatikan (`RESERVE_MANUAL_ORDERS=False` di
`routes/marketing_orders_routes.py`). Order manual LAMA yang masih menggenggam reservasi
(audit m.md No.11: delivered tetap reserved, stok jual "hilang" selamanya) dilepas di sini.

Melengkapi — bukan menggandakan — `backend/migrations/repair_leaked_order_reservations.py`
(yang hanya MEMPERBAIKI order batal/retur dan sengaja hanya MELAPORKAN order kirim/selesai).
Pelepasan memakai SSOT yang sama: `core.order_status.release_reservations`.

Sasaran: `_source_type = manual_input` (order buatan layar Marketing) yang BUKAN batal/retur
dan masih menggenggam reservasi (`core.order_status.holds_reservation`). Order batal/retur
diserahkan ke migrasi F10 di atas.

DRY-RUN BAWAAN; `--terapkan` untuk melepas. Idempoten; setiap order yang dilepas diberi
penanda `reservation_released_reason = k6_manual_order_no_reservation`.

Pakai:
    python3 scripts/release_manual_order_reservations.py
    python3 scripts/release_manual_order_reservations.py --terapkan
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

REASON = "k6_manual_order_no_reservation"
TERMINAL = ("cancelled", "returned")


def manual_holding_query() -> dict:
    return {"_source_type": "manual_input", "status": {"$nin": list(TERMINAL)},
            "$or": [{"stock_reserved": True}, {"reserved_rows.0": {"$exists": True}},
                    {"items.reserved_rows.0": {"$exists": True}}, {"reserved_qty": {"$gt": 0}}]}


async def run(db, *, apply: bool) -> dict:
    from core import order_status as _os
    orders = await db.marketing_orders.find(manual_holding_query(), {"_id": 0}).to_list(100000)
    orders = [o for o in orders if _os.holds_reservation(o)]
    out = {"found": len(orders), "released_orders": 0, "released_qty": 0.0, "details": []}
    for o in orders:
        qty = float(o.get("reserved_qty") or 0) or sum(float(i.get("reserved_qty") or 0)
                                                       for i in (o.get("items") or []) if isinstance(i, dict))
        row = {"order_id": o.get("order_id"), "status": o.get("status"),
               "account": o.get("account_name"), "reserved_qty": qty}
        if apply:
            res = await _os.release_reservations(db, o, reason=REASON)
            patch = dict(res["patch"])
            patch.update({"stock_reserved": False, "reserved_qty": 0.0, "reserved_rows": [],
                          "reservation_released_reason": REASON,
                          "reservation_released_at": datetime.now(timezone.utc)})
            await db.marketing_orders.update_one({"id": o["id"]}, {"$set": patch})
            await _os.refresh_catalog_cache(db, res["touched"])
            row["released"] = res["released"]
            out["released_orders"] += 1
            out["released_qty"] = round(out["released_qty"] + float(res["released"] or 0), 4)
        out["details"].append(row)
    return out


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--terapkan", action="store_true", help="lepas reservasi (bawaan: dry-run)")
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
    print(f"[K6] Lepas reservasi order manual · DB {os.environ['DB_NAME']} · "
          f"{'TERAPKAN' if a.terapkan else 'DRY-RUN'}")
    print(f"  order manual masih menggenggam reservasi: {res['found']}")
    for d in res["details"][:50]:
        print(f"   · {d['order_id']} [{d['status']}] {d.get('account') or '-'} "
              f"reserved {d['reserved_qty']}" + (f" → dilepas {d.get('released')}" if a.terapkan else ""))
    if a.terapkan:
        print(f"  dilepas: {res['released_orders']} order · {res['released_qty']} pcs")
    else:
        print("Jalankan ulang dengan --terapkan untuk melepas.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
