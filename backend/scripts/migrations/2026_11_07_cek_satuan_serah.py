"""Laporan 2026-11-07 (Tahap 9, keputusan owner no. 3) — SATUAN SERAH aksesoris yang perlu dicek gudang.

KENAPA: aksesoris kini diserahkan ke CMT dalam satuan serah (kemasan dari daftar satuan material, mis. "roll isi
2.240 cm", "bungkus isi 1.440 pcs") dan stok berkurang qty serah × isi kemasan. Nama "gross" di master dipakai untuk
isi yang berbeda-beda (144, 1.440, 400, 200, 1.000). Master TIDAK diubah oleh skrip ini — gudang memeriksa sendiri.

Yang dilaporkan (aturan sama dengan `core.satuan_serah.handover_unit`):
  · tanpa_kemasan     — satuan dasar berupa ukuran (cm, m, gram, kg) dan tidak ada kemasan;
  · kemasan_ganda     — lebih dari satu kemasan, tidak ada yang ditandai satuan pakai;
  · gross_tidak_baku  — kemasan bernama "gross" dengan isi selain 144.

Sifat: HANYA MEMBACA. Ringkasan jumlah saja (tanpa nama barang); `--csv <path>` menulis rinciannya ke berkas.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_cek_satuan_serah.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_cek_satuan_serah.py \
        --csv /tmp/cek_satuan_serah.csv
"""
import argparse
import asyncio
import csv
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
CHECK = ('tanpa_kemasan', 'kemasan_ganda', 'gross_tidak_baku')
ACC_TYPES = ('accessory', 'packaging')


def rows_from(materials, used_ids=frozenset()) -> list:
    """Fungsi murni (diuji): baris laporan untuk material aksesoris yang satuan serahnya perlu dicek."""
    from core import satuan_serah as ss
    from core import uom as uom_core
    out = []
    for m in materials:
        hu = ss.handover_unit(m)
        if hu['status'] not in CHECK:
            continue
        out.append({'code': m.get('code') or '', 'name': m.get('name') or '', 'status': hu['status'],
                    'status_label': hu['status_label'], 'base_uom': hu['base_uom'], 'handover_uom': hu['uom'],
                    'handover_factor': hu['factor'],
                    'uoms': '; '.join(f"{r['code']}={r['factor']:g}" for r in uom_core.resolve_uoms(m)),
                    'dipakai_po': 'ya' if m.get('id') in used_ids else 'tidak', 'catatan': hu['note']})
    return sorted(out, key=lambda r: (r['status'], r['code']))


async def run(csv_path: str | None) -> int:
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f'[cek-satuan-serah] DB={DB_NAME} · HANYA MEMBACA (master tidak diubah)')
    mats = await db.rahaza_materials.find(
        {'active': {'$ne': False}, 'type': {'$in': list(ACC_TYPES)}, 'is_cut_panel': {'$ne': True}},
        {'_id': 0}).to_list(20000)
    used = {r['accessory_id'] for r in await db.po_accessories.find(
        {'accessory_id': {'$nin': [None, '']}}, {'_id': 0, 'accessory_id': 1}).to_list(50000)}
    rows = rows_from(mats, frozenset(used))
    print(f'  aksesoris aktif diperiksa : {len(mats)}')
    for st in CHECK:
        n = sum(1 for r in rows if r['status'] == st)
        n_po = sum(1 for r in rows if r['status'] == st and r['dipakai_po'] == 'ya')
        print(f'  {st:<18}: {n} barang ({n_po} dipakai di rencana aksesoris PO)')
    print(f'  total perlu dicek        : {len(rows)}')
    if csv_path:
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                               ['code', 'name', 'status', 'status_label', 'base_uom', 'handover_uom',
                                'handover_factor', 'uoms', 'dipakai_po', 'catatan'])
            w.writeheader()
            w.writerows(rows)
        print(f'  rincian ditulis ke {csv_path}')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--csv', dest='csv_path', default=None, help='tulis rincian ke berkas CSV')
    sys.exit(asyncio.run(run(ap.parse_args().csv_path)))
