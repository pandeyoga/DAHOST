"""Migrasi 2026-11-04 — katalog Marketing dirapikan supaya isinya = master produk.

A. Item hasil impor Excel ditautkan ke katalog tokonya.

KENAPA: `scripts/import_master_template.py` (sheet 14_KATALOG_JUAL) menulis item katalog dengan
kunci `account_id`+`sku` TANPA `catalog_id`. Layar Manajemen Katalog, Isi dari Master, tarik HPP,
sinkron stok, dan produk sesi live membaca item per `catalog_id` → semua item asli yang tertaut
master tidak terlihat (yang tampil hanya item contoh), dan "Isi dari Master" menganggap produk itu
belum ada sehingga staf bisa menambahkannya dua kali.

Yang dilakukan:
  1. Item dengan `catalog_id` kosong → diberi `catalog_id` katalog aktif milik `account_id`-nya.
     Toko yang belum punya katalog → dibuatkan satu (`core.sku_bridge.ensure_catalog`, sama
     dengan Jembatan SKU). Toko dengan >1 katalog aktif → TIDAK diubah, hanya dilaporkan.
  2. Bila di katalog itu sudah ada item untuk barang jadi yang sama (`fg_material_id`) → item impor
     TIDAK ditautkan, hanya dilaporkan (supaya tidak dobel).
  3. Angka ringkas katalog (jumlah item, stok) dihitung ulang.

B. Item CONTOH dari tombol "Seed Demo Data" (`source='seed_demo'`, tanpa tautan master produk)
   dinonaktifkan (keputusan owner 4 Nov 2026) — tidak dihapus; riwayat produk sesi live yang
   memakainya tetap ada. Item contoh yang sudah ditautkan ke master oleh staf TIDAK disentuh.

Sifat: IDEMPOTEN, tanpa hapus. Bawaan hanya PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_04_katalog_dari_master.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_04_katalog_dari_master.py --apply
"""
import argparse
import asyncio
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
NO_CATALOG = {'$or': [{'catalog_id': None}, {'catalog_id': ''}, {'catalog_id': {'$exists': False}}]}


async def run(apply: bool) -> int:
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f'[katalog] DB={DB_NAME} · {mode}')

    touched = set()
    await _link_imported(db, apply, touched)
    await _deactivate_demo(db, apply, touched)
    if apply:
        from routes.marketing_catalog_mgmt import _refresh_catalog_stats
        for cid in touched:
            await _refresh_catalog_stats(db, cid)
    return 0


async def _deactivate_demo(db, apply: bool, touched: set) -> None:
    q = {'source': 'seed_demo', 'is_active': {'$ne': False},
         'fg_material_id': {'$in': [None, '']}, 'model_id': {'$in': [None, '']}}
    rows = await db.marketing_catalog_items.find(q, {'_id': 0, 'id': 1, 'catalog_id': 1, 'name': 1}).to_list(10000)
    used = await db.marketing_live_session_products.count_documents({'catalog_item_id': {'$in': [r['id'] for r in rows]}}) if rows else 0
    names = sorted({r.get('name') or '' for r in rows})
    print(f'[B] item contoh aktif tanpa tautan master: {len(rows)}' + (f" ({', '.join(names[:6])}{'…' if len(names) > 6 else ''})" if rows else ''))
    if rows:
        print(f'    dipakai {used} baris produk sesi live (riwayat tetap, tidak diubah)')
    if apply and rows:
        await db.marketing_catalog_items.update_many(
            {'id': {'$in': [r['id'] for r in rows]}},
            {'$set': {'is_active': False, 'deactivated_reason': 'item contoh seed demo (migrasi 2026-11-04)',
                      'deactivated_at': datetime.now(timezone.utc)}})
        touched.update(r['catalog_id'] for r in rows if r.get('catalog_id'))
        print(f'    dinonaktifkan: {len(rows)}')


async def _link_imported(db, apply: bool, touched: set) -> None:
    items = await db.marketing_catalog_items.find(
        NO_CATALOG, {'_id': 0, 'id': 1, 'account_id': 1, 'sku': 1, 'fg_material_id': 1}).to_list(100000)
    print(f'[A] item tanpa katalog: {len(items)}')
    if not items:
        return
    by_acc = defaultdict(list)
    for it in items:
        by_acc[it.get('account_id') or ''].append(it)

    accounts = {a['id']: a for a in await db.marketing_platform_accounts.find(
        {}, {'_id': 0, 'id': 1, 'account_code': 1, 'account_name': 1}).to_list(1000)}
    from core.sku_bridge import ensure_catalog

    linked, skipped = Counter(), Counter()
    for acc_id, rows in sorted(by_acc.items(), key=lambda kv: (accounts.get(kv[0]) or {}).get('account_code') or kv[0]):
        acc = accounts.get(acc_id)
        label = f"{(acc or {}).get('account_code') or '?'} {(acc or {}).get('account_name') or acc_id}"
        if not acc:
            skipped['toko tidak ada'] += len(rows)
            print(f'  ! {label}: {len(rows)} item — toko tidak ditemukan, dilewati')
            continue
        cats = await db.marketing_catalogs.find(
            {'account_id': acc_id, 'is_active': {'$ne': False}}, {'_id': 0, 'id': 1, 'name': 1}).to_list(10)
        if len(cats) > 1:
            skipped['toko punya >1 katalog'] += len(rows)
            print(f'  ! {label}: {len(rows)} item — toko punya {len(cats)} katalog aktif, pilih manual')
            continue
        if cats:
            cat = cats[0]
        elif apply:
            cat = await ensure_catalog(db, acc_id)
            print(f'  + katalog dibuat untuk {label}: {cat["name"]}')
        else:
            cat = {'id': None, 'name': f"(akan dibuat) Katalog {acc.get('account_name') or ''}"}
        existing_fg = set()
        if cat.get('id'):
            existing_fg = {d.get('fg_material_id') for d in await db.marketing_catalog_items.find(
                {'catalog_id': cat['id'], 'fg_material_id': {'$nin': [None, '']}},
                {'_id': 0, 'fg_material_id': 1}).to_list(100000)}
        ok_ids, dup = [], 0
        for it in rows:
            if it.get('fg_material_id') and it['fg_material_id'] in existing_fg:
                dup += 1
                continue
            ok_ids.append(it['id'])
        if dup:
            skipped['barang jadi sudah ada di katalog'] += dup
        print(f'  {label} → {cat["name"]}: {len(ok_ids)} item ditautkan' + (f', {dup} dilewati (sudah ada)' if dup else ''))
        if apply and ok_ids:
            await db.marketing_catalog_items.update_many(
                {'id': {'$in': ok_ids}, **NO_CATALOG}, {'$set': {'catalog_id': cat['id']}})
            touched.add(cat['id'])
        linked[label] += len(ok_ids)

    print(f'  total ditautkan: {sum(linked.values())} · dilewati: {dict(skipped) or 0}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    sys.exit(asyncio.run(run(ap.parse_args().apply)))
