"""Migrasi 2026-11-08 (Asisten AI, audit §3.C #8) — hitung ulang rekap harian yang memuat pesanan BELUM DIBAYAR.

KENAPA: definisi omzet baku (keputusan owner, `core.ukuran_penjualan`) mengeluarkan pesanan `new` yang belum
dibayar. Rekap harian turunan yang dihitung SEBELUM perubahan ini masih menjumlah pesanan itu, sehingga omzet
toko terlalu besar sampai ekspor B/C menandainya batal. Kode baru langsung benar untuk impor berikutnya;
migrasi ini menghitung ulang tanggal LAMA yang terdampak.

Yang dilakukan:
  * PRATINJAU (bawaan): toko-tanggal yang punya pesanan belum dibayar, jumlah pesanannya, dan selisih omzet
    (omzet rekap sekarang vs omzet bila pesanan itu dikeluarkan).
  * --apply: `core.marketing_daily_rollup.recompute_pairs` untuk toko-tanggal itu. Tanggal yang di-override
    SPV TIDAK disentuh (aturan rollup), dan disebut.

Sifat: idempoten (menjalankan ulang tidak mengubah hasil). Hanya mencetak jumlah, tanpa data pembeli.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_rekap_tanpa_belum_bayar.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_rekap_tanpa_belum_bayar.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


async def run(db, apply: bool = False) -> dict:
    from core import marketing_daily_rollup as rollup
    from core import marketing_sales_shape as shape
    from core import ukuran_penjualan as uk
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[rekap-tanpa-belum-bayar] {mode}")
    per_pair: dict = {}
    async for o in db.marketing_orders.find({'status': 'new'}, {'_id': 0, 'account_id': 1, 'order_date': 1,
                                                                 'revenue_product': 1, 'items': 1, 'price_final': 1,
                                                                 'quantity': 1, **uk.PROYEKSI_STATUS}):
        if not uk.belum_dibayar(o) or uk.data_contoh(o):
            continue
        key = (o.get('account_id'), rollup.order_date_key(o.get('order_date')))
        if not all(key):
            continue
        b = per_pair.setdefault(key, {'pesanan': 0, 'nilai': 0.0})
        b['pesanan'] += 1
        b['nilai'] += rollup.order_revenue_product(o)
    stale = 0
    override = 0
    lebih = 0.0
    for (aid, d), b in sorted(per_pair.items()):
        doc = await db.marketing_sales_data.find_one({'account_id': aid, 'date': d, 'revenue_type': 'total'},
                                                     {'_id': 0})
        if not doc:
            continue
        if doc.get('source') == shape.SOURCE_MANUAL_OVERRIDE:
            override += 1
            continue
        f = shape.read_group(doc, 'fulfillment')
        if 'unpaid_orders' not in f:             # dihitung sebelum aturan baru
            stale += 1
            lebih += b['nilai']
    print(f"  toko-tanggal dengan pesanan belum dibayar: {len(per_pair)} "
          f"({sum(b['pesanan'] for b in per_pair.values())} pesanan)")
    print(f"  rekap yang masih menghitungnya sebagai omzet: {stale} · omzet berlebih ± Rp {lebih:,.0f}"
          .replace(',', '.'))
    if override:
        print(f"  dilewati karena di-override SPV: {override} (pakai Hitung Ulang paksa di layar Input Sales)")
    out = {'pairs': len(per_pair), 'stale': stale, 'override': override, 'omzet_berlebih': round(lebih, 2),
           'recomputed': 0}
    if apply and per_pair:
        res = await rollup.recompute_pairs(db, set(per_pair), actor='migrasi_rekap_belum_bayar')
        out['recomputed'] = res.get('upserted', 0) + res.get('deleted', 0)
        print(f"  dihitung ulang: {res.get('upserted', 0)} diperbarui · {res.get('deleted', 0)} dihapus · "
              f"{res.get('skipped_override', 0)} override dilewati")
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
