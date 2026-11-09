"""Migrasi 2026-11-10 (Monitoring Staf, keputusan owner K9) — tutup tugas otomatis "Input Sales Harian".

KENAPA: penjadwal Marketing membuat satu tugas "Input Sales Harian — <toko> (<tanggal>)" setiap toko yang belum
mengisi rekap kemarin. Di salinan VPS 9 Nov ada 392 tugas seperti itu dan TIDAK SATU PUN diselesaikan (371 tanpa
penanggung jawab). Owner memutuskan (10 Nov) tugas itu diganti kewajiban harian "Data penjualan toko kemarin" di
Monitoring Staf (dicek dari data, pemegang = PIC toko). Penjadwal sudah berhenti membuatnya; skrip ini menutup
tugas lama yang masih terbuka supaya papan tugas Marketing tidak penuh tugas mati.

Yang dilakukan: tugas `source=auto_generated`, `related_entity=sales_data`, status `to_do`/`in_progress` →
status `cancelled` + `cancel_reason`, `cancelled_at`, `cancelled_by="system"`. Tidak ada yang dihapus. Tugas
buatan staf/template dan tugas health score tidak disentuh. Idempoten. Bawaan PRATINJAU.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_10_tutup_tugas_input_sales.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_10_tutup_tugas_input_sales.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

SARINGAN = {
    'source': 'auto_generated',
    'related_entity': 'sales_data',
    'status': {'$in': ['to_do', 'in_progress']},
}
ALASAN = ('Ditutup otomatis 10 Nov 2026: input sales harian kini dipantau sebagai kewajiban harian '
          '"Data penjualan toko kemarin" di Manajemen › Monitoring Staf.')


def ubahan(kini: datetime) -> dict:
    return {'$set': {'status': 'cancelled', 'cancel_reason': ALASAN, 'cancelled_at': kini,
                     'cancelled_by': 'system', 'updated_at': kini}}


async def jalankan(db, apply: bool) -> dict:
    n = await db.marketing_tasks.count_documents(SARINGAN)
    out = {'terbuka': n, 'ditutup': 0}
    if apply and n:
        res = await db.marketing_tasks.update_many(SARINGAN, ubahan(datetime.now(timezone.utc)))
        out['ditutup'] = getattr(res, 'modified_count', 0) or 0
    return out


async def main(apply: bool):
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    out = await jalankan(db, apply)
    print(f"[tutup-tugas-input-sales] DB={DB_NAME} · tugas otomatis input sales yang masih terbuka: {out['terbuka']}")
    if apply:
        print(f"  ditutup: {out['ditutup']}")
    else:
        print("  Pratinjau saja. Jalankan lagi dengan --apply untuk menyimpan.")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    asyncio.run(main(ap.parse_args().apply))
