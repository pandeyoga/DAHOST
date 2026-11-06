"""Migrasi 2026-11-06 (Tahap 2 Pengadaan) — perbaikan data dua cacat lama.

A. RIWAYAT HARGA TANPA `material_id`
   Template Excel "Harga·Satuan·Rekening" (core/master_fill.apply_materials) dulu menulis riwayat harga
   dengan bentuk sendiri: `material_code`, `unit_cost`, `before`, `by`, `at` — tanpa `material_id`,
   `old_unit_cost`/`new_unit_cost`, maupun `created_at`. Akibatnya layar Riwayat Harga Barang (yang
   membaca per `material_id`) tidak pernah menampilkan perubahan itu. Baris seperti itu dilengkapi ke
   bentuk SSOT `core.accessory_valuation._record_history` (material dicari lewat kodenya). Kode yang
   tidak ada lagi di Master Item hanya dihitung dan dilaporkan.

B. TAUTAN ASET HILANG DI BARIS PENERIMAAN
   `_capitalize_assets_from_grn` menulis `asset_id` ke baris GR, lalu penyimpanan akhir GR menimpa
   seluruh `items` dengan salinan tanpa tanda itu. Aset tetapnya ADA (`rahaza_fixed_assets.grn_id` +
   `grn_item_id`) tetapi barisnya tidak menunjuk ke sana. Tautan dikembalikan dari registri aset.

Sifat: idempoten, tanpa hapus, hanya mencetak JUMLAH (tanpa data pribadi). Bawaan PRATINJAU; tulis
dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_pengadaan_riwayat_aset.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_pengadaan_riwayat_aset.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
HISTORY = 'rahaza_material_cost_history'
MIGRATION = 'migrasi 2026-11-06 pengadaan'


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ── perencanaan (murni, tanpa DB — diuji unit) ───────────────────────────────
def history_patch(row: dict, material_id: str) -> dict:
    """Bidang yang dilengkapi pada satu baris riwayat lama (bentuk SSOT `_record_history`)."""
    new = _f(row.get('unit_cost') if row.get('new_unit_cost') is None else row.get('new_unit_cost'))
    old = _f(row.get('before') if row.get('old_unit_cost') is None else row.get('old_unit_cost'))
    at = row.get('created_at') or row.get('at') or datetime.now(timezone.utc)
    return {'material_id': material_id, 'old_unit_cost': round(old, 4), 'new_unit_cost': round(new, 4),
            'unit_cost_in': round(new, 4), 'qty_before': _f(row.get('qty_before')), 'qty_in': _f(row.get('qty_in')),
            'method': row.get('method') or 'manual', 'created_at': at,
            'notes': row.get('notes') or 'Harga dari template Harga·Satuan·Rekening (dilengkapi migrasi)',
            'actor': row.get('actor') or {'id': '', 'name': row.get('by') or 'sistem'},
            'repaired_by': MIGRATION}


def gr_asset_patch(items: list, assets_by_line: dict) -> tuple:
    """(items baru, jumlah baris yang ditautkan) — baris aset tanpa `asset_id` yang asetnya ada."""
    changed = 0
    out = []
    for li in items or []:
        li = dict(li)
        a = assets_by_line.get(li.get('id'))
        if (li.get('item_type') or 'material') == 'asset' and not li.get('asset_id') and a:
            li.update({'asset_id': a.get('id'), 'asset_code': a.get('code') or a.get('asset_code'),
                       'capitalized': True, 'capitalize_error': None})
            changed += 1
        out.append(li)
    return out, changed


# ── jalankan (db disuntikkan supaya bisa diuji dengan DB palsu) ──────────────
async def migrate(db, apply: bool) -> dict:
    stats = {'history_rows': 0, 'history_fixed': 0, 'history_unknown_code': 0,
             'gr_docs': 0, 'gr_lines_linked': 0}
    # A. riwayat harga tanpa material_id
    rows = await db[HISTORY].find({'material_id': {'$in': [None, '']}}, {'_id': 0}).to_list(50000)
    codes = sorted({r.get('material_code') for r in rows if r.get('material_code')})
    by_code = {}
    if codes:
        for m in await db.rahaza_materials.find({'code': {'$in': codes}}, {'_id': 0, 'id': 1, 'code': 1}).to_list(len(codes) + 10):
            by_code[m['code']] = m['id']
    for r in rows:
        stats['history_rows'] += 1
        mid = by_code.get(r.get('material_code'))
        if not mid or not r.get('id'):
            stats['history_unknown_code'] += 1
            continue
        stats['history_fixed'] += 1
        if apply:
            await db[HISTORY].update_one({'id': r['id'], 'material_id': {'$in': [None, '']}},
                                         {'$set': history_patch(r, mid)})
    # B. tautan aset di baris GR
    assets = await db.rahaza_fixed_assets.find({'grn_id': {'$nin': [None, '']}},
                                               {'_id': 0, 'id': 1, 'code': 1, 'grn_id': 1, 'grn_item_id': 1}).to_list(20000)
    by_gr: dict = {}
    for a in assets:
        if a.get('grn_item_id'):
            by_gr.setdefault(a['grn_id'], {})[a['grn_item_id']] = a
    for gr_id, lines in by_gr.items():
        gr = await db.warehouse_receiving.find_one({'id': gr_id}, {'_id': 0, 'id': 1, 'items': 1})
        if not gr:
            continue
        items, n = gr_asset_patch(gr.get('items') or [], lines)
        if not n:
            continue
        stats['gr_docs'] += 1
        stats['gr_lines_linked'] += n
        if apply:
            await db.warehouse_receiving.update_one({'id': gr_id}, {'$set': {'items': items}})
    return stats


async def run(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f"[pengadaan-2026-11-06] DB={DB_NAME} · "
          f"{'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    s = await migrate(db, apply)
    verb = 'dilengkapi' if apply else 'akan dilengkapi'
    print(f"  A. riwayat harga tanpa material: {s['history_rows']} baris · {verb}: {s['history_fixed']} · "
          f"kode tidak ada di Master Item (dibiarkan): {s['history_unknown_code']}")
    print(f"  B. baris penerimaan aset tanpa tautan: {s['gr_lines_linked']} baris di {s['gr_docs']} penerimaan "
          f"{'ditautkan' if apply else 'akan ditautkan'}")
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    sys.exit(asyncio.run(run(ap.parse_args().apply)))
