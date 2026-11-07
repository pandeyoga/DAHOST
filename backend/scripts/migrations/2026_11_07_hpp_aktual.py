"""Migrasi 2026-11-07 (Tahap 9, keputusan owner No. 5 & 13) — HPP aktual per PO, benang = bahan pembantu.

LANGKAH (semua idempoten, tanpa hapus, hanya mencetak JUMLAH):
  1. Penanda bahan pembantu: kategori material Benang Jahit (kode SEWING_THREAD) diberi `bahan_pembantu: true`
     bila penandanya belum diisi. Kode sudah menganggap kategori itu bahan pembantu walau penanda kosong; langkah
     ini membuat penandanya terlihat di data (satu-satunya penanda — `core.hpp_aktual.AUX_FLAG`).
  2. Profil posting `inventory_issue` mendapat peran `debit_production_supplies` (bahan pembantu produksi, bawaan
     akun 5-3400) bila belum ada. Startup server juga menambahkannya (`upgrade_posting_profiles`); langkah ini
     untuk DB yang dimigrasi sebelum server baru menyala. Akun yang sudah diisi pengguna tidak disentuh.
  3. HPP maklon ketikan (`dewi_maklon_hpp`: komponen, overhead %, margin %) DIARSIPKAN: dokumen diberi
     `superseded_by='hpp_per_po'` + tanggal. Isinya tidak diubah/dihapus; tidak ada layar yang membacanya lagi
     (HPP maklon = HPP per PO dari data nyata). Hanya jumlah dokumen yang dicetak.

Bawaan PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_hpp_aktual.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_hpp_aktual.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
AUX_FLAG = 'bahan_pembantu'
AUX_CODES = ('SEWING_THREAD',)
ROLE = 'debit_production_supplies'
ROLE_DEFAULT = '5-3400'
SUPERSEDED = 'hpp_per_po'


def _now():
    return datetime.now(timezone.utc)


# ── murni (diuji unit) ───────────────────────────────────────────────────────
def plan_categories(cats: list) -> list:
    """id kategori yang perlu diberi penanda bahan pembantu (kode bawaan, penanda belum diisi)."""
    return [c['id'] for c in cats or [] if c.get('id') and c.get(AUX_FLAG) is None
            and str(c.get('code') or '').strip().upper() in AUX_CODES]


def plan_profile(profile: dict | None, account_exists: bool) -> str:
    """'add' | 'present' | 'no_profile' | 'no_account' untuk peran bahan pembantu di profil inventory_issue."""
    if not profile:
        return 'no_profile'
    if ROLE in (profile.get('mapping') or {}) or ROLE in (profile.get('user_removed_roles') or []):
        return 'present'
    return 'add' if account_exists else 'no_account'


# ── langkah ──────────────────────────────────────────────────────────────────
async def step_categories(db, apply: bool) -> dict:
    cats = await db.rahaza_material_categories.find({}, {'_id': 0, 'id': 1, 'code': 1, AUX_FLAG: 1}).to_list(500)
    ids = plan_categories(cats)
    flagged = sum(1 for c in cats if c.get(AUX_FLAG) is True)
    done = 0
    if apply and ids:
        r = await db.rahaza_material_categories.update_many(
            {'id': {'$in': ids}, AUX_FLAG: None},
            {'$set': {AUX_FLAG: True, 'updated_at': _now(), 'bahan_pembantu_set_by': 'migrasi 2026_11_07_hpp_aktual'}})
        done = r.modified_count
    mats = 0
    if ids:
        mats = await db.rahaza_materials.count_documents({'$or': [{'category': {'$in': ids}},
                                                                  {'category_id': {'$in': ids}}]})
    return {'categories': len(cats), 'already_flagged': flagged, 'to_flag': len(ids), 'flagged': done,
            'materials_in_flagged_categories': mats}


async def step_profile(db, apply: bool) -> dict:
    prof = await db.rahaza_posting_profiles.find_one({'event_type': 'inventory_issue'}, {'_id': 0})
    acc = await db.rahaza_coa_accounts.find_one({'code': ROLE_DEFAULT, 'is_group': {'$ne': True}}, {'_id': 0, 'code': 1})
    plan = plan_profile(prof, bool(acc))
    done = False
    if apply and plan == 'add':
        r = await db.rahaza_posting_profiles.update_one(
            {'event_type': 'inventory_issue', f'mapping.{ROLE}': {'$exists': False}},
            {'$set': {f'mapping.{ROLE}': ROLE_DEFAULT, 'updated_at': _now()}})
        done = bool(r.modified_count)
    return {'plan': plan, 'added': done}


async def step_manual_hpp(db, apply: bool) -> dict:
    q = {'superseded_by': {'$exists': False}}
    total = await db.dewi_maklon_hpp.count_documents({})
    todo = await db.dewi_maklon_hpp.count_documents(q)
    with_overhead = await db.dewi_maklon_hpp.count_documents({**q, 'overhead_pct': {'$gt': 0}})
    done = 0
    if apply and todo:
        r = await db.dewi_maklon_hpp.update_many(q, {'$set': {
            'superseded_by': SUPERSEDED, 'superseded_at': _now(),
            'superseded_note': 'Tahap 9 (keputusan owner 7 Nov No. 13): HPP maklon dihitung dari data nyata.'}})
        done = r.modified_count
    return {'docs': total, 'to_archive': todo, 'with_typed_overhead': with_overhead, 'archived': done}


async def run(db, apply: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[hpp-aktual] {mode}")
    c = await step_categories(db, apply)
    print(f"  1. kategori material: {c['categories']} · sudah berpenanda bahan pembantu {c['already_flagged']}"
          f" · perlu diberi penanda {c['to_flag']} (barang di kategori itu: {c['materials_in_flagged_categories']})"
          + (f" · diberi penanda {c['flagged']}" if apply else ''))
    p = await step_profile(db, apply)
    label = {'add': 'perlu ditambah', 'present': 'sudah ada', 'no_profile': 'profil belum ada (dibuat startup)',
             'no_account': f'akun {ROLE_DEFAULT} belum ada — isi di Profil Posting'}[p['plan']]
    print(f"  2. peran bahan pembantu di profil pengeluaran bahan: {label}" + (" · ditambah" if p['added'] else ''))
    m = await step_manual_hpp(db, apply)
    print(f"  3. HPP maklon ketikan: {m['docs']} dokumen · belum diarsipkan {m['to_archive']}"
          f" (dengan overhead ketikan {m['with_typed_overhead']})" + (f" · diarsipkan {m['archived']}" if apply else ''))
    return {'categories': c, 'profile': p, 'manual_hpp': m}


async def _main(apply: bool):
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        await run(client[DB_NAME], apply=apply)
    finally:
        client.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    asyncio.run(_main(ap.parse_args().apply))
