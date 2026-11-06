"""Migrasi 2026-11-07 (keamanan) — hapus sandi teks biasa yang pernah disimpan di database.

KENAPA: impor vendor (`POST /api/import-data` type=garments, `routes/operations_import.py`) dulu menyimpan sandi
awal akun vendor apa adanya di `garments.vendor_password_plain`. Siapa pun yang bisa membaca data vendor (atau
cadangan database) bisa masuk sebagai vendor. Layar Buyer lama juga membaca `buyers.buyer_password_plain`.
Kini sandi awal hanya ditampilkan SEKALI di respons impor dan tidak pernah disimpan; akun login tetap memakai
sandi ter-hash di `users.password`.

Yang dilakukan: `$unset` kolom sandi teks biasa (`PLAINTEXT_FIELDS`) dari koleksi akun (`COLLECTIONS`).
Sandi login (hash) TIDAK disentuh. Vendor yang lupa sandinya: admin mengatur ulang sandi di Manajemen Pengguna.

Sifat: idempoten (aman diulang), hanya mencetak JUMLAH (tanpa isi sandi/data pribadi).
Bawaan PRATINJAU; tulis dengan --apply (backup DB dulu).

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_hapus_sandi_teks.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_hapus_sandi_teks.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

# Kolom sandi teks biasa yang pernah ditulis/dibaca kode (bukan `password` ter-hash).
PLAINTEXT_FIELDS = ('vendor_password_plain', 'buyer_password_plain', 'password_plain', 'plain_password')
# Koleksi yang menyimpan akun/mitra dengan login.
COLLECTIONS = ('garments', 'buyers', 'users', 'dewi_client_users', 'dewi_maklon_clients', 'marketing_kol_creators')


def has_field_query() -> dict:
    return {'$or': [{f: {'$exists': True}} for f in PLAINTEXT_FIELDS]}


def unset_spec() -> dict:
    return {'$unset': {f: '' for f in PLAINTEXT_FIELDS}}


async def run(db, apply: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[hapus-sandi-teks] {mode}")
    out: dict = {}
    total = 0
    for coll in COLLECTIONS:
        per_field = {f: await db[coll].count_documents({f: {'$exists': True}}) for f in PLAINTEXT_FIELDS}
        docs = await db[coll].count_documents(has_field_query())
        cleaned = 0
        if apply and docs:
            res = await db[coll].update_many(has_field_query(), unset_spec())
            cleaned = res.modified_count
        out[coll] = {'docs': docs, 'fields': {f: n for f, n in per_field.items() if n}, 'cleaned': cleaned}
        total += docs
        fields = ', '.join(f"{f}: {n}" for f, n in per_field.items() if n) or '-'
        print(f"  {coll}: {docs} dokumen berisi sandi teks ({fields})" + (f" · dibersihkan: {cleaned}" if apply else ''))
    print(f"  total dokumen: {total}")
    out['total'] = total
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
