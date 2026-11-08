"""Migrasi 2026-11-08 (keputusan owner) — nama Indonesia untuk dua akun bawaan yang masih berbahasa Inggris.

KENAPA: bagan akun bawaan (`routes/rahaza_coa.SEED_TEMPLATE`) memberi dua akun beban nama Inggris/campuran. Nama itu
tampil di Bagan Akun, Laba Rugi (per bulan), Neraca lajur, dan Pemetaan akun (temuan V11 audit UI Keuangan):
  * 6-3500 "Biaya Reimbursement Karyawan" → "Biaya Penggantian Klaim Karyawan"
      dipakai klaim biaya karyawan yang diganti perusahaan (konsumsi, representasi, training, kesehatan):
      akun debit bawaan `employee_expense_claims` + pemetaan GL klaim (`employee_expense_gl_mapping.DEFAULT_GL_SEED`).
  * 6-4400 "Beban Kerugian Piutang (Bad Debt Expense)" → "Beban Kerugian Piutang Tak Tertagih"
      dipakai penghapusan piutang tak tertagih (profil posting `bad_debt_writeoff`, `debit_bad_debt_expense`).
Seed di kode sudah memakai nama baru; migrasi ini mengganti data yang SUDAH ada di database.

Yang dilakukan:
  * `rahaza_coa_accounts`: `name` diganti HANYA bila nama sekarang masih persis nama Inggris lama. Akun yang namanya
    sudah diubah pengguna dilewati dan disebut. Kode, tipe, saldo, dan jurnal tidak disentuh (laporan membaca nama
    dari bagan akun).
  * `employee_expense_gl_mappings`: salinan nama akun (`gl_account_name`) untuk kode yang sama, dengan syarat sama
    (layar Pemetaan GL klaim menampilkan salinan ini).

Sifat: idempoten (menjalankan ulang tidak mengubah apa pun). Hanya mencetak kode, nama akun, dan jumlah.
Bawaan PRATINJAU; tulis dengan --apply (backup DB dulu).

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_nama_akun_indonesia.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_nama_akun_indonesia.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

# kode → (nama lama persis, nama baru). Nama baru WAJIB sama dengan rahaza_coa.SEED_TEMPLATE (dikunci uji).
GANTI_NAMA = {
    '6-3500': ('Biaya Reimbursement Karyawan', 'Biaya Penggantian Klaim Karyawan'),
    '6-4400': ('Beban Kerugian Piutang (Bad Debt Expense)', 'Beban Kerugian Piutang Tak Tertagih'),
}


async def run(db, apply: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[nama-akun-indonesia] {mode}")
    now = datetime.now(timezone.utc).isoformat()
    out = {'akun': {}, 'pemetaan_gl': {}, 'diganti': 0, 'pemetaan_diganti': 0}
    for code, (lama, baru) in GANTI_NAMA.items():
        rows = await db.rahaza_coa_accounts.find({'code': code}, {'_id': 0, 'code': 1, 'name': 1}).to_list(50)
        perlu = [r for r in rows if r.get('name') == lama]
        lain = sorted({r.get('name') or '' for r in rows if r.get('name') not in (lama, baru)})
        sudah = sum(1 for r in rows if r.get('name') == baru)
        diganti = 0
        if apply and perlu:
            res = await db.rahaza_coa_accounts.update_many(
                {'code': code, 'name': lama}, {'$set': {'name': baru, 'updated_at': now}})
            diganti = res.modified_count
        out['akun'][code] = {'perlu': len(perlu), 'sudah': sudah, 'nama_lain': lain, 'diganti': diganti}
        out['diganti'] += diganti
        if not rows:
            print(f"  {code}: tidak ada di bagan akun — dilewati")
        else:
            print(f"  {code}: perlu diganti {len(perlu)} · sudah nama baru {sudah}"
                  + (f" · nama lain (tidak disentuh): {', '.join(lain)}" if lain else '')
                  + (f" · diganti: {diganti}" if apply else '')
                  + (f"\n      \"{lama}\" → \"{baru}\"" if perlu else ''))

        q_map = {'gl_account_code': code, 'gl_account_name': lama}
        n_map = await db.employee_expense_gl_mappings.count_documents(q_map)
        map_diganti = 0
        if apply and n_map:
            res = await db.employee_expense_gl_mappings.update_many(
                q_map, {'$set': {'gl_account_name': baru, 'updated_at': now}})
            map_diganti = res.modified_count
        out['pemetaan_gl'][code] = {'perlu': n_map, 'diganti': map_diganti}
        out['pemetaan_diganti'] += map_diganti
        if n_map:
            print(f"      pemetaan GL klaim dengan nama lama: {n_map}" + (f" · diganti: {map_diganti}" if apply else ''))
    print(f"  total akun diganti: {out['diganti']} · pemetaan GL diganti: {out['pemetaan_diganti']}")
    return out


async def main(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    await run(db, apply)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.apply)))
