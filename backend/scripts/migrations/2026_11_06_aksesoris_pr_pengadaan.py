"""Migrasi 2026-11-06 (Tahap 2) — Request Pembelian Aksesoris yang masih terbuka → Permintaan Pengadaan.

KENAPA: sampai Tahap 2, Request Pembelian Aksesoris (`acc_purchase_requests`) punya alur sendiri:
disetujui → "Order" → "Terima Barang" yang MENAMBAH STOK tanpa nilai dan tanpa jurnal, dan tidak
pernah tersambung ke PO pengadaan. Sekarang pembelian aksesoris hanya lewat Pengadaan (Permintaan
Pengadaan → PO → Penerimaan Barang, bernilai & berjurnal) dan tombol "Terima Barang" dihapus.
PR aksesoris yang masih terbuka harus ikut pindah supaya barangnya tetap bisa dipesan & diterima.

Yang dipindah (belum punya tautan `procurement_pr_id`):
  * Draf      → Permintaan Pengadaan draf (pemohon mengajukannya dari tab PR aksesoris / Pengadaan)
  * Diajukan  → Permintaan Pengadaan pada tahap persetujuan yang sama (rantai & jejak dibawa)
  * Disetujui / Dipesan → Permintaan Pengadaan "disetujui" (siap dibuatkan PO; barang diterima di
    Penerimaan Barang). Dipesan di luar sistem tetap butuh PO supaya penerimaannya bernilai.
Fungsi pemindahnya SAMA dengan tombol "Teruskan ke Pengadaan" (`core.accessory_procurement`).

Sifat: idempoten (yang sudah bertautan dilewati), tanpa hapus. Bawaan hanya PRATINJAU; tulis
dengan --apply. Hanya mencetak jumlah (tanpa nama/isi dokumen).

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_aksesoris_pr_pengadaan.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_aksesoris_pr_pengadaan.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
OPEN_STATUSES = ('Draft', 'Submitted', 'Approved', 'Ordered')
ACTOR = {'id': 'system', 'name': 'Migrasi 2026-11-06', 'role': 'system'}


async def migrate(db, *, apply: bool) -> dict:
    """Pratinjau / tulis. Return hitungan per status asal + jumlah yang dipindah / gagal."""
    from core import accessory_procurement as ap

    rows = await db.acc_purchase_requests.find(
        {'status': {'$in': list(OPEN_STATUSES)}, 'procurement_pr_id': {'$in': [None, '']}},
        {'_id': 0}).to_list(5000)
    out = {'found': len(rows), 'by_status': {}, 'moved': 0, 'skipped_empty': 0, 'failed': 0}
    for acc in rows:
        st = acc.get('status')
        out['by_status'][st] = out['by_status'].get(st, 0) + 1
        if not ap.acc_pr_body(acc)['items']:
            out['skipped_empty'] += 1
            continue
        if not apply:
            continue
        try:
            await ap.forward_acc_pr(db, acc, ACTOR, submit=False)
            out['moved'] += 1
        except Exception as e:  # noqa: BLE001 — satu dokumen gagal tidak menghentikan yang lain
            out['failed'] += 1
            print(f"  ! satu PR gagal dipindah: {type(e).__name__}")
    return out


async def run(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f"[aksesoris-pr→pengadaan] DB={DB_NAME} · "
          f"{'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    res = await migrate(db, apply=apply)
    per = ', '.join(f"{k}: {v}" for k, v in sorted(res['by_status'].items())) or '-'
    print(f"  PR aksesoris terbuka tanpa tautan Pengadaan: {res['found']} ({per})")
    print(f"  tanpa baris barang (dilewati): {res['skipped_empty']}")
    if apply:
        print(f"  dipindah: {res['moved']} · gagal: {res['failed']}")
    else:
        print(f"  akan dipindah: {res['found'] - res['skipped_empty']}")
    return 1 if res['failed'] else 0


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true')
    sys.exit(asyncio.run(run(p.parse_args().apply)))
