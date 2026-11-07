"""Migrasi 2026-11-07 (Tahap 9) — batalkan DRAF Material Issue yang akan mengeluarkan stok DUA KALI.

KENAPA: PO yang dijahit CMT mengeluarkan materialnya otomatis saat Kirim ke CMT (satu MI per kiriman). Draf
otomatis dari job (GDG-2) dan draf massal yang dibuat untuk PO yang sama, bila disetujui, memotong stok lagi
(contoh di VPS: MI-20260924-004). Mulai Tahap 9 draf seperti itu tidak dibuat lagi; skrip ini membereskan sisanya.

Yang dilakukan: draf/menunggu-persetujuan MI dari job/WO/draf massal untuk PO yang SUDAH punya MI kiriman ke CMT
(status keluar) → status `cancelled` + alasan. Aturan sama dengan `core.kirim_cmt.double_drafts` (satu definisi,
dipakai juga saat kirim dan saat approve MI). Stok & jurnal tidak disentuh (draf belum memotong apa pun).

Sifat: IDEMPOTEN, tanpa hapus. Bawaan hanya PRATINJAU (daftar: nomor MI, nomor PO, alasan); tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_batal_mi_dobel.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_batal_mi_dobel.py --apply
"""
import argparse
import asyncio
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


async def run(apply: bool) -> int:
    from core import kirim_cmt
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f'[batal-mi-dobel] DB={DB_NAME} · {mode}')
    rows = await (kirim_cmt.cancel_double_drafts(db, actor='migrasi-2026-11-07') if apply
                  else kirim_cmt.double_drafts(db))
    if not rows:
        print('  tidak ada draf MI dobel.')
        return 0
    print(f'  {"MI":<22} {"PO":<22} alasan')
    for r in rows:
        print(f"  {r['mi_number']:<22} {r['po_number']:<22} {r['reason']}")
    print(f'  total: {len(rows)} draf {"dibatalkan" if apply else "akan dibatalkan"}')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    sys.exit(asyncio.run(run(ap.parse_args().apply)))
