"""Migrasi 2026-11-17 (layar owner Kirim ke DA: "Diterima DA 0 · Sisa kirim 0") — lepas deklarasi kirim CMT→DA
yang penerimaannya SUDAH DIBATALKAN sebelum rilis ini.

KENAPA: dulu "Batalkan penerimaan" hanya mengubah status penerimaan. Dispatch deklarasinya tetap dianggap sudah
diterima DA, sehingga sisa kirim CMT 0 padahal barangnya belum sampai, progres surat jalan deklarasi tetap
"terkirim", dan batas lebih-pesan ikut menghitungnya. Rilis ini menandai baris dispatch itu `receipt_cancelled`
saat penerimaan dibatalkan (core.dispatch_capacity.release_declaration_of_receipt); migrasi ini menerapkan hal yang
sama untuk pembatalan lama.

Hanya MENANDAI baris dispatch (tidak menghapus apa pun). Idempoten. Bawaan PRATINJAU; tulis dengan --apply
(backup DB dulu).

Runbook (VPS):
    docker exec dahost-backend-1 python scripts/migrations/2026_11_17_deklarasi_penerimaan_batal.py
    docker exec dahost-backend-1 python scripts/migrations/2026_11_17_deklarasi_penerimaan_batal.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


async def run(db, apply: bool = False) -> dict:
    from core.cmt_receipt_status import canon_status, ST_CANCELLED
    from core.dispatch_capacity import release_declaration_of_receipt, _i
    print(f"[deklarasi-batal] {'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    out = {'penerimaan': 0, 'baris': 0}
    async for r in db.cmt_receipts.find({'related_shipment_id': {'$nin': [None, '']}}, {'_id': 0}):
        if canon_status(r.get('status')) != ST_CANCELLED:
            continue
        seq = _i(r.get('related_dispatch_seq')) or 1
        rows = [it for it in await db.buyer_shipment_items.find({'shipment_id': r['related_shipment_id']}, {'_id': 0}).to_list(None)
                if (_i(it.get('dispatch_seq')) or 1) == seq and not it.get('receipt_cancelled')]
        if not rows:
            continue
        ship = await db.buyer_shipments.find_one({'id': r['related_shipment_id']}, {'_id': 0, 'shipment_number': 1})
        print(f"- {r.get('receipt_code')} → {(ship or {}).get('shipment_number', '?')} kirim ke-{seq}: "
              f"{len(rows)} baris, {sum(_i(x.get('qty_shipped')) for x in rows)} pcs")
        out['penerimaan'] += 1
        out['baris'] += len(rows)
        if apply:
            await release_declaration_of_receipt(db, r, r.get('reject_reason') or '')
    print(f"Ringkas: {out['penerimaan']} penerimaan batal · {out['baris']} baris dispatch"
          + (" (DITULIS)" if apply else " (belum ditulis)"))
    return out


async def main(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    await run(AsyncIOMotorClient(MONGO_URL)[DB_NAME], apply)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    sys.exit(asyncio.run(main(ap.parse_args().apply)))
