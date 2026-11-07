"""Migrasi 2026-11-08 (Asisten AI, audit §3.C #4) — buang DATA CONTOH dari koleksi Marketing.

KENAPA: seeder demo dulu otomatis mengisi iklan, sesi live, dan kesehatan akun dengan angka ACAK setiap kali
koleksinya kosong — juga di produksi. Angka acak itu terbaca sebagai biaya iklan, ROAS, dan omzet live
sungguhan oleh layar dan oleh Asisten AI. Kode kini hanya mengisi data contoh di lingkungan demo
(`ALLOW_DEMO_SEED=true`) dan semua pembaca angka membuang `_seed_origin`; migrasi ini membersihkan sisanya.

Yang dilakukan:
  * Koleksi TRANSAKSI Marketing (`TRANSAKSI`): dokumen ber-`_seed_origin: true` dihapus.
  * Koleksi MASTER (`MASTER`: host, kreator, katalog): hanya DILAPORKAN — master bisa sudah dipakai data
    sungguhan (pesanan menaut item katalog, kreator punya akun login). Hapus lewat layar bila memang contoh.
  * `marketing_account_health` buatan seeder LAMA (sebelum ada penanda) dilaporkan sebagai "mirip contoh"
    (bentuk dokumen persis seeder, bukan hasil impor). Ikut dihapus HANYA dengan
    `--termasuk-kesehatan-tanpa-penanda`.
  * Pesanan contoh yang terhapus: rekap harian tanggalnya dihitung ulang (supaya omzet tidak nyangkut).

Sifat: idempoten. Bawaan PRATINJAU; tulis dengan --apply (backup DB dulu). Hanya mencetak jumlah.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_hapus_data_contoh_marketing.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_hapus_data_contoh_marketing.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

SEED = {'_seed_origin': True}
TRANSAKSI = (
    'marketing_ads_data', 'marketing_live_sessions', 'marketing_live_session_products',
    'marketing_account_health', 'marketing_content_calendar', 'marketing_discounts',
    'marketing_product_launches', 'marketing_samples', 'marketing_orders', 'marketing_sales_data',
    'marketing_returns', 'marketing_settlements', 'marketing_reviews', 'marketing_complaints',
)
MASTER = ('marketing_livehosts', 'marketing_kol_creators', 'marketing_catalogs', 'marketing_catalog_items')
# Bentuk dokumen persis `seed_health_if_empty` lama (tanpa penanda): tidak ada field lain.
_HEALTH_SEED_KEYS = {
    'id', 'platform', 'account_id', 'account_name', 'snapshot_date', 'ses_score', 'late_shipment_rate',
    'cancellation_rate', 'response_rate', 'response_time_hours', 'order_defect_rate', 'return_rate',
    'rating_score', 'total_reviews', 'status', 'notes', 'created_at', 'updated_at',
}


def health_like_seed(doc: dict) -> bool:
    """Dokumen kesehatan akun berbentuk persis seeder lama (bukan impor, bukan entri staf)."""
    keys = set(doc) - {'_id'}
    return (not doc.get('_seed_origin') and keys == _HEALTH_SEED_KEYS
            and doc.get('notes') == [] and doc.get('created_at') == doc.get('snapshot_date'))


async def run(db, apply: bool = False, health_unmarked: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[hapus-data-contoh-marketing] {mode}")
    out = {'transaksi': {}, 'master': {}, 'kesehatan_mirip_contoh': 0, 'dihapus': 0, 'rekap_dihitung_ulang': 0}

    pairs = set()
    if apply:
        from core import marketing_daily_rollup as rollup
        pairs = await rollup.pairs_from_orders(db, dict(SEED))

    for coll in TRANSAKSI:
        n = await db[coll].count_documents(dict(SEED))
        deleted = 0
        if apply and n:
            deleted = (await db[coll].delete_many(dict(SEED))).deleted_count
        out['transaksi'][coll] = {'contoh': n, 'dihapus': deleted}
        out['dihapus'] += deleted
        print(f"  {coll}: {n} dokumen contoh" + (f" · dihapus {deleted}" if apply else ''))

    like_ids = []
    async for d in db.marketing_account_health.find({'_seed_origin': {'$ne': True},
                                                     '_import_session_id': {'$exists': False}}):
        if health_like_seed(d):
            like_ids.append(d.get('id'))
    out['kesehatan_mirip_contoh'] = len(like_ids)
    print(f"  marketing_account_health tanpa penanda tetapi berbentuk seeder lama: {len(like_ids)}"
          + ('' if health_unmarked else ' (tidak dihapus; pakai --termasuk-kesehatan-tanpa-penanda)'))
    if apply and health_unmarked and like_ids:
        r = await db.marketing_account_health.delete_many({'id': {'$in': [i for i in like_ids if i]}})
        out['dihapus'] += r.deleted_count
        print(f"      dihapus {r.deleted_count}")

    for coll in MASTER:
        n = await db[coll].count_documents(dict(SEED))
        out['master'][coll] = n
        print(f"  {coll} (master, hanya dilaporkan): {n} dokumen contoh")

    if apply and pairs:
        res = await rollup.recompute_pairs(db, pairs, actor='migrasi_hapus_data_contoh')
        out['rekap_dihitung_ulang'] = res.get('dates', 0)
        print(f"  rekap harian dihitung ulang: {res.get('dates', 0)} toko-tanggal")
    print(f"  total dihapus: {out['dihapus']}")
    return out


async def main(apply: bool, health_unmarked: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    await run(db, apply, health_unmarked)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--termasuk-kesehatan-tanpa-penanda', dest='health', action='store_true')
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.apply, a.health)))
