"""Migrasi 2026-11-07 (pola P2) — sub-ledger hutang per PEMASOK di Auto Akun.

KENAPA: tipe entitas Auto Akun "supplier" menunjuk koleksi `rahaza_vendors`, padahal master pemasok
adalah `rahaza_suppliers` (layar Pemasok, PO, GR, faktur dari GR). Koleksi `rahaza_vendors` tidak
pernah ada, jadi:
  * sinkron master saat start (`core.finance_sync._backfill_subledgers`) tidak pernah membuat akun
    hutang 2-1100-<kode pemasok>;
  * posting faktur pemasok mencari sub-ledger di koleksi yang salah (dengan `vendor_id` yang juga
    tidak disimpan faktur dari GR) → hutang SELALU jatuh ke akun kontrol 2-1100.
Setelan tersimpan di `rahaza_coa_auto_settings` ikut membawa `collection: rahaza_vendors`, sehingga
mengganti bawaan di kode saja tidak cukup.

LANGKAH:
  1. Setelan Auto Akun: koleksi & field tujuan (milik program) yang berbeda dari bawaan disembuhkan
     (`routes.coa_auto.get_auto_settings` — mesin yang sama dengan start server).
  2. Tiap pemasok aktif tanpa sub-ledger → dibuatkan 2-1100-<KODE> + `ap_account_code` ditulis balik
     (`routes.coa_auto.ensure_subledger_for_entity`).
  3. LAPORAN saja: faktur pemasok yang SUDAH dijurnal ke akun kontrol (tidak direklasifikasi — saldo
     total 2-1100 tidak berubah karena sub-ledger ada di bawahnya).

Sifat: idempoten (aman diulang), tanpa hapus, hanya mencetak JUMLAH. Bawaan PRATINJAU; tulis --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_subledger_pemasok.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_subledger_pemasok.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
SYS_USER = {'id': 'system', 'name': 'migrasi 2026-11-07'}
SUPPLIERS = 'rahaza_suppliers'
ACTIVE_Q = {'active': {'$ne': False}, 'is_active': {'$ne': False}}


# ── murni (diuji unit) ───────────────────────────────────────────────────────
def settings_fixes(stored: dict, defaults: dict, owned=('collection', 'target_field')) -> dict:
    """{entity_type: {meta: (tersimpan, bawaan)}} untuk meta milik program yang menyimpang."""
    out = {}
    for key, dflt in (defaults or {}).items():
        cur = (stored or {}).get(key)
        if not isinstance(cur, dict):
            continue
        diff = {m: (cur.get(m), dflt[m]) for m in owned if m in dflt and cur.get(m) != dflt[m]}
        if diff:
            out[key] = diff
    return out


def suppliers_without_subledger(suppliers: list, have_ids: set) -> list:
    """Pemasok aktif (punya id) yang belum punya akun sub-ledger bertipe supplier."""
    return [s for s in suppliers if s.get('id') and s['id'] not in have_ids
            and s.get('active', True) is not False and s.get('is_active', True) is not False]


# ── langkah ──────────────────────────────────────────────────────────────────
async def step_settings(db, apply: bool) -> dict:
    from routes.coa_auto import DEFAULT_ENTITY_TYPES, get_auto_settings
    doc = await db.rahaza_coa_auto_settings.find_one({'id': 'default'}, {'_id': 0}) or {}
    fixes = settings_fixes(doc.get('entity_types') or {}, DEFAULT_ENTITY_TYPES)
    if apply and fixes:
        await get_auto_settings(db)          # menyembuhkan + menyimpan (mesin yang sama dgn startup)
    return {'types_fixed': len(fixes), 'supplier_was': (fixes.get('supplier') or {}).get('collection', (None,))[0]}


async def step_suppliers(db, apply: bool) -> dict:
    sups = await db[SUPPLIERS].find(ACTIVE_Q, {'_id': 0}).to_list(None)
    have = {a['flags']['subledger_entity_id'] async for a in db.rahaza_coa_accounts.find(
        {'flags.subledger_entity_type': 'supplier'}, {'_id': 0, 'flags': 1})}
    todo = suppliers_without_subledger(sups, have)
    out = {'suppliers_active': len(sups), 'without_subledger': len(todo), 'created': 0, 'errors': 0}
    if apply:
        from routes.coa_auto import ensure_subledger_for_entity
        for s in todo:
            res = await ensure_subledger_for_entity(db, 'supplier', s, SYS_USER)
            out['created' if res.get('ok') else 'errors'] += 1
    return out


async def step_report(db) -> dict:
    """Faktur pemasok yang sudah dijurnal ke akun kontrol (bukan 2-1100-<kode>)."""
    prof = await db.rahaza_posting_profiles.find_one({'event_type': 'ap_invoice'}, {'_id': 0, 'mapping': 1}) or {}
    control = (prof.get('mapping') or {}).get('credit_ap') or '2-1100'
    n = 0
    async for inv in db.rahaza_ap_invoices.find(
            {'gl_je_id': {'$nin': [None, '']}, 'supplier_id': {'$nin': [None, '']}},
            {'_id': 0, 'gl_ap_account_code': 1}):
        if (inv.get('gl_ap_account_code') or control) == control:
            n += 1
    return {'posted_to_control': n, 'control': control}


async def run(db, apply: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[subledger-pemasok] {mode}")
    st = await step_settings(db, apply)
    print(f"  1. setelan Auto Akun menyimpang: {st['types_fixed']} tipe"
          + (f" (supplier tersimpan → {st['supplier_was']})" if st['supplier_was'] else ''))
    sp = await step_suppliers(db, apply)
    print(f"  2. pemasok aktif: {sp['suppliers_active']} · tanpa sub-ledger hutang: {sp['without_subledger']}"
          + (f" · dibuat: {sp['created']} · gagal: {sp['errors']}" if apply else ''))
    rp = await step_report(db)
    print(f"  3. faktur pemasok sudah dijurnal ke akun kontrol {rp['control']}: {rp['posted_to_control']} "
          "(hanya laporan)")
    return {'settings': st, 'suppliers': sp, 'report': rp}


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
