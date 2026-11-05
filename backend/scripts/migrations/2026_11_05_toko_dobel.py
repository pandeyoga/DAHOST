"""Migrasi 2026-11-05 — toko marketplace yang tercatat DUA KALI dinonaktifkan.

KENAPA: sampai 5 Nov 2026 siapa pun yang login boleh menambah toko, dan satu-satunya cek dobel
adalah kode toko. PIC toko lalu membuat toko yang SUDAH ADA dengan kode lain — contoh di VPS:
"SHOPEE - OUTFIT" (= SHP-02 Shopee Outfit Boutique) dan "TIKTOK - OUTFIT" (= TTK-02, username
sama `outfit_butiq`). Setiap toko baru juga langsung membuat akun Penjualan (4-11xx) dan Piutang
(1-1303-<kode>) di Bagan Akun, sehingga satu toko punya dua alamat jurnal.

"Toko yang sama" memakai aturan yang SAMA dengan penolak toko dobel di layar
(`core.marketing_account_scope.store_identity_keys`): platform sama (tiktok = tiktokshop) DAN
username ATAU nama sama (tanpa beda huruf/spasi/titik).

Per kelompok toko dobel:
  1. Toko yang DIPERTAHANKAN = yang paling banyak datanya; bila sama, yang paling lama dibuat.
  2. Toko dobel yang BELUM punya data (pesanan, item katalog, sales, iklan, sesi live, jurnal …)
     → nonaktif + `duplicate_of`; katalognya yang kosong dinonaktifkan; akun Penjualan & Piutang
     yang DIBUAT SISTEM untuk toko itu dinonaktifkan bila belum pernah dijurnal dan tidak dipakai
     toko lain. Jejaknya ditulis di `marketing_change_log`.
  3. Toko dobel yang SUDAH punya data → TIDAK diubah, hanya dilaporkan (diputuskan manual).

Sifat: idempoten, tanpa hapus. Bawaan hanya PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_05_toko_dobel.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_05_toko_dobel.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.marketing_account_scope import store_identity_keys  # noqa: E402
from core.store_cleanup import coa_unused_elsewhere, owned_coa, store_data_refs  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
ACCOUNTS = 'marketing_platform_accounts'
REASON = 'toko tercatat dua kali (migrasi 2026-11-05)'


# ── perencanaan (murni, tanpa DB — diuji unit) ───────────────────────────────
def cluster_duplicates(stores: list) -> list:
    """Kelompok toko yang identitasnya bertemu (union-find atas kunci identitas)."""
    parent = {s['id']: s['id'] for s in stores}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner = {}
    for s in stores:
        for k in store_identity_keys(s.get('platform'), s.get('username'), s.get('account_name')):
            if k in owner:
                parent[find(s['id'])] = find(owner[k])
            else:
                owner[k] = s['id']
    groups = {}
    for s in stores:
        groups.setdefault(find(s['id']), []).append(s)
    return [g for g in groups.values() if len(g) > 1]


_FAR = datetime.max.replace(tzinfo=timezone.utc)


def _created(s: dict) -> datetime:
    c = s.get('created_at')
    if isinstance(c, str):
        try:
            c = datetime.fromisoformat(c.replace('Z', '+00:00'))
        except ValueError:
            return _FAR
    if isinstance(c, datetime):
        return c if c.tzinfo else c.replace(tzinfo=timezone.utc)
    return _FAR


def choose_keeper(group: list, ref_total: dict) -> dict:
    """Yang dipertahankan: data terbanyak, lalu dibuat paling dulu, lalu kode terpendek."""
    return min(group, key=lambda s: (-ref_total.get(s['id'], 0), _created(s), len(s.get('account_code') or '')))


# ── baca DB — aturan "punya data" & "akun COA milik toko" ada di core.store_cleanup ─────
async def _data_refs(db, store: dict, collections: list) -> dict:
    return await store_data_refs(db, store, collections)


async def _coa_to_deactivate(db, dup: dict) -> list:
    """Akun COA buatan sistem untuk toko dobel yang aman dinonaktifkan (aktif, belum dijurnal,
    tidak dipakai toko lain)."""
    out = []
    for a in await owned_coa(db, dup):
        if a.get('active') is False or not await coa_unused_elsewhere(db, dup, a['code']):
            continue
        out.append({'code': a['code'], 'name': a.get('name')})
    return out


# ── jalankan ─────────────────────────────────────────────────────────────────
async def run(apply: bool) -> int:
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f"[toko-dobel] DB={DB_NAME} · {'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    stores = await db[ACCOUNTS].find(
        {'status': {'$ne': 'inactive'}, 'duplicate_of': {'$in': [None, '']}}, {'_id': 0}).to_list(2000)
    groups = cluster_duplicates(stores)
    if not groups:
        print('  tidak ada toko yang tercatat dua kali.')
        return 0
    collections = sorted(await db.list_collection_names())
    planned = held = 0
    for g in groups:
        refs = {s['id']: await _data_refs(db, s, collections) for s in g}
        total = {sid: sum(r.values()) for sid, r in refs.items()}
        keep = choose_keeper(g, total)
        print(f"\n  ■ {keep.get('account_code')} · {keep.get('account_name')} ({keep.get('platform')}, "
              f"username {keep.get('username') or '-'}) — DIPERTAHANKAN · data {total[keep['id']]}")
        for dup in g:
            if dup['id'] == keep['id']:
                continue
            label = f"{dup.get('account_code')} · {dup.get('account_name')} (username {dup.get('username') or '-'})"
            if total[dup['id']]:
                held += 1
                print(f"    ! {label} — PUNYA DATA, tidak diubah: {refs[dup['id']]}")
                continue
            drafts = await db.marketing_data_import_sessions.count_documents(
                {'account_id': dup['id'], 'committed_count': {'$in': [0, None]}})
            coa = await _coa_to_deactivate(db, dup)
            cats = await db.marketing_catalogs.find(
                {'account_id': dup['id'], 'is_active': {'$ne': False}}, {'_id': 0, 'id': 1, 'name': 1}).to_list(50)
            print(f"    - {label} — dinonaktifkan"
                  + (f"; akun COA: {', '.join(c['code'] + ' ' + (c['name'] or '') for c in coa)}" if coa else '')
                  + (f"; katalog kosong: {', '.join(c['name'] for c in cats)}" if cats else '')
                  + (f"; {drafts} draf impor yang belum pernah disimpan diabaikan" if drafts else ''))
            planned += 1
            if not apply:
                continue
            now = datetime.now(timezone.utc)
            await db[ACCOUNTS].update_one({'id': dup['id']}, {'$set': {
                'status': 'inactive', 'active': False, 'duplicate_of': keep['id'],
                'duplicate_of_code': keep.get('account_code'), 'deactivated_reason': REASON,
                'deactivated_at': now, 'updated_at': now}})
            for c in coa:
                await db.rahaza_coa_accounts.update_one({'code': c['code']}, {'$set': {
                    'active': False, 'deactivated_reason': f"{REASON}: {dup.get('account_code')}",
                    'updated_at': now}})
            if cats:
                await db.marketing_catalogs.update_many(
                    {'id': {'$in': [c['id'] for c in cats]}},
                    {'$set': {'is_active': False, 'deactivated_reason': REASON, 'updated_at': now}})
            from core import marketing_cycle as cycle
            await cycle.log_change(
                db, account_id=dup['id'], entity=ACCOUNTS, entity_id=dup['id'],
                action='duplicate_inactivated', before={'status': dup.get('status')},
                after={'status': 'inactive', 'duplicate_of': keep['id'],
                       'duplicate_of_code': keep.get('account_code'),
                       'coa_inactivated': [c['code'] for c in coa],
                       'catalogs_inactivated': [c['id'] for c in cats]},
                reason=REASON, user={'name': 'migrasi 2026-11-05', 'role': 'system'})
    print(f"\n  ringkas: {len(groups)} kelompok dobel · "
          f"{'dinonaktifkan' if apply else 'akan dinonaktifkan'}: {planned} · punya data (diputuskan manual): {held}")
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    sys.exit(asyncio.run(run(ap.parse_args().apply)))
