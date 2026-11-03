"""Migrasi 2026-11-04 — Kas Kecil disatukan ke Rekening & Mutasi (keputusan owner, audit Keuangan).

KENAPA: dana kas kecil (`rahaza_petty_cash_funds`) menulis jurnal ke akun GL yang SAMA dengan rekening
"Kas Kecil" di Kas & Bank (peran `petty_cash_replenish.debit_petty_cash`, bawaan 1-1101). Dua layar untuk
satu akun → dua saldo yang bisa berbeda. Mulai sekarang:
  · Kas Kecil = rekening kas biasa (mutasi dari buku besar, pengeluaran lewat menu Pengeluaran,
    pengisian lewat Transfer Antar Rekening);
  · uang muka karyawan di menu Kasbon & Uang Muka (dibayar dari rekening mana saja).

Yang dilakukan (TIDAK membuat / mengubah jurnal):
  1. Pastikan rekening kas dengan akun GL kas kecil ada & aktif (dibuat tanpa jurnal saldo awal —
     riwayatnya sudah ada di buku besar).
  2. Dana kas kecil aktif → status 'merged' (+ rekening tujuan). Laporan: saldo dana vs saldo GL.
  3. Uang muka karyawan yang masih terbuka dari dana → ditautkan ke rekening itu, supaya
     pertanggungjawabannya bisa diselesaikan dari menu Uang Muka (sisa uang kembali ke Kas Kecil).
  4. Laporan saja: uang muka LAMA tanpa karyawan yang belum kembali, transaksi yang jurnalnya gagal.

Sifat: IDEMPOTEN, tanpa hapus. Bawaan hanya PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_04_kas_kecil_ke_rekening.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_04_kas_kecil_ke_rekening.py --apply
"""
import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rp(v) -> str:
    return f"Rp {float(v or 0):,.0f}".replace(',', '.')


async def _gl_balance(db, code: str) -> float:
    async for r in db.rahaza_journal_lines.aggregate([
            {'$match': {'account_code': code}},
            {'$group': {'_id': None, 'd': {'$sum': '$debit'}, 'c': {'$sum': '$credit'}}}]):
        return round(float(r.get('d') or 0) - float(r.get('c') or 0), 2)
    return 0.0


async def run(apply: bool) -> int:
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f'[kas-kecil] DB={DB_NAME} · {mode}')
    from routes.rahaza_posting import get_mapping   # sumber yang sama dengan posting kas kecil
    code = (await get_mapping(db, 'petty_cash_replenish')).get('debit_petty_cash') or '1-1101'
    coa = await db.rahaza_coa_accounts.find_one({'code': code}, {'_id': 0, 'name': 1, 'active': 1})
    print(f'  akun GL kas kecil: {code} {(coa or {}).get("name", "(tidak ada di Bagan Akun!)")}')
    if not coa:
        print('  ! akun GL kas kecil tidak ada di Bagan Akun — perbaiki pemetaan dulu. Berhenti.')
        return 1

    # 1. rekening kas untuk akun itu
    acc = await db.rahaza_cash_accounts.find_one({'gl_account_code': code}, {'_id': 0})
    if acc:
        print(f'  rekening: {acc.get("code")} · {acc.get("name")} (aktif={acc.get("active", True)})')
        if acc.get('active') is False and apply:
            await db.rahaza_cash_accounts.update_one({'id': acc['id']}, {'$set': {'active': True, 'updated_at': _now()}})
            print('    → diaktifkan kembali')
    else:
        acc = {'id': str(uuid.uuid4()), 'code': code, 'name': (coa or {}).get('name') or 'Kas Kecil', 'type': 'cash',
               'gl_account_code': code, 'opening_balance': 0.0, 'active': True,
               'created_at': _now(), 'created_by': 'migrasi-2026-11-04', 'notes': 'Dari penyatuan Kas Kecil'}
        print(f'  rekening belum ada → {"dibuat" if apply else "akan dibuat"}: {acc["code"]} · {acc["name"]}')
        if apply:
            await db.rahaza_cash_accounts.insert_one(dict(acc))

    # 2. dana kas kecil
    gl_bal = await _gl_balance(db, code)
    funds = [f async for f in db.rahaza_petty_cash_funds.find({}, {'_id': 0})]
    fund_total = round(sum(float(f.get('current_balance') or 0) for f in funds if f.get('status') == 'active'), 2)
    print(f'  dana kas kecil: {len(funds)} (aktif {sum(1 for f in funds if f.get("status") == "active")}) · '
          f'Σ saldo dana aktif {_rp(fund_total)} · saldo GL {code} {_rp(gl_bal)}')
    if abs(fund_total - gl_bal) > 0.5 and funds:
        print('    ! saldo dana ≠ saldo GL. Angka yang dipakai mulai sekarang = saldo GL (Rekening & Mutasi).')
    for f in funds:
        if f.get('status') != 'active':
            continue
        print(f'    - {f.get("name")} saldo {_rp(f.get("current_balance"))} → {"merged" if apply else "akan merged"}')
        if apply:
            await db.rahaza_petty_cash_funds.update_one({'id': f['id'], 'status': 'active'}, {'$set': {
                'status': 'merged', 'merged_at': _now(), 'merged_into_cash_account_id': acc['id'],
                'balance_at_merge': float(f.get('current_balance') or 0), 'updated_at': _now()}})

    # 3. uang muka karyawan terbuka dari dana
    q = {'txn_type': 'advance', 'employee_id': {'$nin': [None, '']}, 'open_amount': {'$gt': 0.009},
         'cash_gl_code': {'$exists': False}}
    adv = [a async for a in db.rahaza_petty_cash_txns.find(q, {'_id': 0, 'id': 1, 'employee_name': 1, 'open_amount': 1})]
    print(f'  uang muka karyawan terbuka (dari dana): {len(adv)} · {_rp(sum(float(a.get("open_amount") or 0) for a in adv))}')
    for a in adv:
        print(f'    - {a.get("employee_name")} {_rp(a.get("open_amount"))}')
    if apply and adv:
        await db.rahaza_petty_cash_txns.update_many({'id': {'$in': [a['id'] for a in adv]}}, {'$set': {
            'cash_gl_code': code, 'cash_account_id': acc['id'], 'cash_account_name': acc.get('name'),
            'migrated_at': _now()}})

    # 4. laporan saja
    legacy = [t async for t in db.rahaza_petty_cash_txns.find(
        {'txn_type': {'$in': ['advance', 'return']}, 'employee_id': {'$in': [None, '']}, 'gl_posted': True},
        {'_id': 0, 'txn_type': 1, 'amount': 1})]
    legacy_open = sum(float(t.get('amount') or 0) * (1 if t['txn_type'] == 'advance' else -1) for t in legacy)
    if legacy_open > 0.5:
        print(f'  ! uang muka LAMA tanpa karyawan belum kembali: {_rp(legacy_open)} — sudah dibebankan saat dicatat; '
              'bila uangnya kembali catat sebagai penerimaan ke rekening Kas Kecil.')
    failed = await db.rahaza_petty_cash_txns.count_documents({'gl_posted': False})
    if failed:
        print(f'  ! {failed} transaksi kas kecil jurnalnya belum terbentuk — tidak ikut saldo GL. Periksa sebelum menutup periode.')
    print('[kas-kecil] selesai.')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    sys.exit(asyncio.run(run(ap.parse_args().apply)))
