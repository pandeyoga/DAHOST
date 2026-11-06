"""Migrasi 2026-11-06 (Tahap 2, paket gudang) — Surat Jalan INTERNAL lama yang tidak pernah memindah stok.

KENAPA: sampai Tahap 2, menerbitkan SJ-INTERNAL hanya membuat antrean "Scan-Out" (`wh_pending_movements`,
`type='outbound_rm'`, `source_type='delivery_note'`) untuk layar yang sudah DIHAPUS dari menu, dan
baris ke-2..n tertolak penjaga dobel (satu antrean per dokumen). Stok tidak pernah bergerak.
Sejak Tahap 2 SJ internal memindah stok sendiri (keluar saat terbit → Dalam Perjalanan → masuk
saat diterima). SJ LAMA yang sudah terbit tidak boleh dipindah otomatis: barangnya mungkin sudah
lama tiba dan stoknya sudah dikoreksi lewat opname/penyesuaian.

Yang dilakukan:
  * PRATINJAU (bawaan): hitung & daftar nomor SJ internal terbit/diterima tanpa jejak pindah stok,
    draft internal yang belum punya lokasi asal/tujuan, dan antrean Scan-Out yatim.
  * --apply: SJ internal lama ditandai `stock_legacy` (penerimaan/pembatalannya dokumen saja —
    keputusan pindah stoknya diambil manual lewat transfer), dan antrean Scan-Out yatim dibatalkan
    (tidak pernah memotong stok). Tidak ada stok/jurnal yang diubah.

Sifat: idempoten, tanpa hapus, hanya mencetak jumlah + nomor dokumen (tanpa nama penerima).

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_sj_internal.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_sj_internal.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
NOTE = ('SJ internal terbit sebelum Tahap 2 (6 Nov 2026) — stok tidak pernah dipindah sistem; '
        'diterima/dibatalkan sebagai dokumen saja. Koreksi stok manual lewat transfer bila perlu.')
PENDING_REASON = 'antrean Scan-Out SJ internal lama (layarnya sudah tidak ada) — migrasi 2026-11-06'


async def migrate(db, apply: bool) -> dict:
    legacy = await db.wh_delivery_notes.find(
        {'sj_type': 'SJ-INTERNAL', 'status': {'$in': ['issued', 'received']},
         'stock_out_at': {'$exists': False}, 'stock_legacy': {'$ne': True}},
        {'_id': 0, 'id': 1, 'sj_number': 1, 'status': 1, 'lines': 1}).to_list(5000)
    drafts = await db.wh_delivery_notes.find(
        {'sj_type': 'SJ-INTERNAL', 'status': 'draft'},
        {'_id': 0, 'id': 1, 'sj_number': 1, 'from_location_id': 1, 'to_location_id': 1}).to_list(5000)
    drafts_no_loc = [d for d in drafts if not d.get('from_location_id') or not d.get('to_location_id')]
    pendings = await db.wh_pending_movements.find(
        {'type': 'outbound_rm', 'source_type': 'delivery_note', 'status': {'$in': ['pending', 'partial']}},
        {'_id': 0, 'id': 1, 'ref_number': 1}).to_list(5000)
    out = {'legacy_issued': sum(1 for x in legacy if x.get('status') == 'issued'),
           'legacy_received': sum(1 for x in legacy if x.get('status') == 'received'),
           'legacy_lines': sum(len(x.get('lines') or []) for x in legacy),
           'legacy_numbers': sorted(str(x.get('sj_number') or x.get('id')) for x in legacy),
           'drafts_without_location': len(drafts_no_loc),
           'draft_numbers': sorted(str(x.get('sj_number') or x.get('id')) for x in drafts_no_loc),
           'orphan_pending': len(pendings), 'applied': bool(apply)}
    if not apply:
        return out
    now = datetime.now(timezone.utc)
    for x in legacy:
        await db.wh_delivery_notes.update_one(
            {'id': x['id'], 'stock_out_at': {'$exists': False}},
            {'$set': {'stock_legacy': True, 'stock_legacy_note': NOTE, 'updated_at': now}})
    for p in pendings:
        await db.wh_pending_movements.update_one(
            {'id': p['id'], 'status': {'$in': ['pending', 'partial']}},
            {'$set': {'status': 'cancelled', 'cancel_reason': PENDING_REASON, 'cancelled_at': now}})
    return out


def report(out: dict) -> None:
    print(f"  SJ internal terbit tanpa pindah stok : {out['legacy_issued']}")
    print(f"  SJ internal diterima tanpa pindah stok: {out['legacy_received']}  ({out['legacy_lines']} baris)")
    if out['legacy_numbers']:
        print('    nomor: ' + ', '.join(out['legacy_numbers'][:200]))
    print(f"  draft internal tanpa lokasi asal/tujuan (wajib diedit sebelum terbit): {out['drafts_without_location']}")
    if out['draft_numbers']:
        print('    nomor: ' + ', '.join(out['draft_numbers'][:200]))
    print(f"  antrean Scan-Out yatim dari SJ internal: {out['orphan_pending']}")
    print('  ' + ('DITULIS: SJ lama ditandai dokumen-saja, antrean yatim dibatalkan.' if out['applied']
                 else 'PRATINJAU — tidak ada yang diubah. Tambahkan --apply untuk menandai.'))


async def run(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f"[sj-internal] DB={DB_NAME} · {'TULIS' if apply else 'PRATINJAU'}")
    report(await migrate(db, apply))
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    sys.exit(asyncio.run(run(ap.parse_args().apply)))
