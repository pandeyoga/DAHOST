"""Migrasi 2026-11-08 (keputusan pemilik, uji ketajaman toko-a) — segarkan SKOR SEHAT semua toko.

KENAPA: `marketing_platform_accounts.health_score` hanya dihitung saat input sales, impor, atau tombol
"Hitung ulang skor". Skor yang tersimpan menetap berminggu-minggu (jendela 30 hari sudah bergeser), dan
simpan snapshot Kesehatan Akun tidak pernah memicu hitung ulang (impor `routes.marketing` yang sudah tidak
ada, galat ditelan). Kode kini menghitung ulang skor basi saat layar dibaca; migrasi ini menyegarkan skor
yang TERSIMPAN sekali jalan supaya semua pembaca (laporan, Asisten AI, ekspor) langsung memakai angka baru.

Rumus = `routes.marketing_shared.compute_health_fields` (sama dengan layar): data sales 30 hari terakhir;
toko tanpa data 30 hari terakhir = "Belum ada data" (skor kosong), bukan skor 1.

Sifat: idempoten. Bawaan PRATINJAU (mencetak skor lama → skor baru per toko, tanpa menulis); tulis dengan
--apply (backup DB dulu: `mongodump --collection marketing_platform_accounts`). Hanya field `health_*` dan
`updated_at` yang ditulis.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_skor_sehat_toko.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_skor_sehat_toko.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
BATAS_TOKO = 2000


def _tampil(score, label) -> str:
    return f"{score} ({label})" if score is not None else (label or 'Belum ada data')


async def run(db, apply: bool = False) -> dict:
    from routes.marketing_shared import compute_health_fields, HEALTH_NO_DATA_LABEL

    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[skor-sehat-toko] {mode}")
    out = {'toko': 0, 'berubah': 0, 'tetap': 0, 'punya_skor': 0, 'belum_ada_data': 0, 'ditulis': 0,
           'gagal': 0, 'rincian': []}
    accounts = await db.marketing_platform_accounts.find(
        {}, {'_id': 0, 'id': 1, 'account_name': 1, 'health_score': 1, 'health_label': 1}).to_list(BATAS_TOKO)
    for acc in accounts:
        aid = acc.get('id')
        if not aid:
            continue
        out['toko'] += 1
        try:
            fields = await compute_health_fields(db, aid)
        except Exception as e:  # noqa: BLE001 — satu toko gagal tidak menghentikan yang lain
            out['gagal'] += 1
            print(f"  {acc.get('account_name') or aid}: GAGAL dihitung ({type(e).__name__})")
            continue
        lama, baru = acc.get('health_score'), fields['health_score']
        berubah = lama != baru or (acc.get('health_label') or HEALTH_NO_DATA_LABEL) != fields['health_label']
        out['berubah' if berubah else 'tetap'] += 1
        out['punya_skor' if baru is not None else 'belum_ada_data'] += 1
        out['rincian'].append({'account_id': aid, 'lama': lama, 'baru': baru, 'label': fields['health_label']})
        print(f"  {acc.get('account_name') or aid}: {_tampil(lama, acc.get('health_label'))} → "
              f"{_tampil(baru, fields['health_label'])}" + ('' if berubah else ' (sama)'))
        if apply:
            await db.marketing_platform_accounts.update_one(
                {'id': aid}, {'$set': {**fields, 'updated_at': fields['health_updated_at']}})
            out['ditulis'] += 1
    print(f"  toko: {out['toko']} · berubah: {out['berubah']} · punya skor: {out['punya_skor']} · "
          f"belum ada data 30 hari: {out['belum_ada_data']} · gagal: {out['gagal']}"
          + (f" · ditulis: {out['ditulis']}" if apply else ''))
    return out


async def main(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    out = await run(db, apply)
    return 1 if out['gagal'] else 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.apply)))
