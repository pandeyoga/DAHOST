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
  * KATALOG contoh (keputusan owner 8 Nov: "hapus semuanya") — HANYA dengan `--termasuk-katalog-contoh`:
      - item katalog ber-`_seed_origin` yang id-nya tidak muncul di dokumen koleksi lain mana pun → dihapus;
      - katalog ber-`_seed_origin` yang DIPAKAI (berisi item asli, item contoh yang masih ditaut, atau id-nya
        ditaut dokumen lain) TIDAK dihapus — tanda contohnya dicabut (`$unset _seed_origin`), karena katalog
        toko buatan seeder lama ternyata sudah diisi item hasil impor sungguhan;
      - katalog contoh yang kosong dan tidak ditaut → dihapus.
    Host live & kreator KOL contoh tetap hanya dilaporkan (bisa punya akun login).

Sifat: idempoten. Bawaan PRATINJAU; tulis dengan --apply (backup DB dulu). Hanya mencetak jumlah.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_hapus_data_contoh_marketing.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_hapus_data_contoh_marketing.py --apply
    ... --apply --termasuk-katalog-contoh        # katalog/item katalog contoh (lihat di atas)
"""
import argparse
import asyncio
import json
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


KATALOG, ITEM_KATALOG = 'marketing_catalogs', 'marketing_catalog_items'
BATAS_BACA = 200_000


async def id_yang_ditaut(db, ids: set) -> set:
    """Id dari `ids` yang muncul di dokumen koleksi LAIN mana pun (selain katalog & item katalog).

    Pindai menyeluruh (semua field, termasuk larik bersarang) supaya tidak ada rujukan yang terlewat;
    hanya dipakai migrasi sekali jalan di DB kecil.
    """
    ids = {i for i in ids if i}
    kena: set = set()
    if not ids:
        return kena
    for coll in sorted(await db.list_collection_names()):
        if coll in (KATALOG, ITEM_KATALOG) or coll.startswith('system.'):
            continue
        for d in await db[coll].find({}).to_list(BATAS_BACA):
            s = json.dumps(d, default=str)
            for i in ids - kena:
                if i in s:
                    kena.add(i)
            if kena == ids:
                return kena
    return kena


async def katalog_contoh(db, apply: bool) -> dict:
    """Item katalog & katalog contoh: hapus yang tidak dipakai, cabut tanda contoh katalog yang dipakai."""
    out = {'item_contoh': 0, 'item_ditaut': 0, 'item_dihapus': 0,
           'katalog_contoh': 0, 'katalog_dihapus': 0, 'katalog_dicabut_tanda': 0}
    items = await db[ITEM_KATALOG].find(dict(SEED), {'_id': 0, 'id': 1, 'catalog_id': 1}).to_list(BATAS_BACA)
    cats = await db[KATALOG].find(dict(SEED), {'_id': 0, 'id': 1}).to_list(BATAS_BACA)
    item_ids = {d.get('id') for d in items if d.get('id')}
    cat_ids = {d.get('id') for d in cats if d.get('id')}
    ditaut = await id_yang_ditaut(db, item_ids | cat_ids)
    hapus_item = sorted(item_ids - ditaut)
    out.update(item_contoh=len(item_ids), item_ditaut=len(item_ids & ditaut), katalog_contoh=len(cat_ids))

    if apply and hapus_item:
        r = await db[ITEM_KATALOG].delete_many({'id': {'$in': hapus_item}, '_seed_origin': True})
        out['item_dihapus'] = r.deleted_count
    sisa_contoh_per_katalog: dict = {}
    for d in items:
        if d.get('id') in ditaut:
            sisa_contoh_per_katalog[d.get('catalog_id')] = sisa_contoh_per_katalog.get(d.get('catalog_id'), 0) + 1

    cabut, hapus_kat = [], []
    for cid in sorted(cat_ids):
        asli = await db[ITEM_KATALOG].count_documents({'catalog_id': cid, '_seed_origin': {'$ne': True}})
        dipakai = asli > 0 or sisa_contoh_per_katalog.get(cid, 0) > 0 or cid in ditaut
        (cabut if dipakai else hapus_kat).append(cid)
    if apply and cabut:
        r = await db[KATALOG].update_many({'id': {'$in': cabut}, '_seed_origin': True},
                                          {'$unset': {'_seed_origin': ''}})
        out['katalog_dicabut_tanda'] = r.modified_count
    if apply and hapus_kat:
        r = await db[KATALOG].delete_many({'id': {'$in': hapus_kat}, '_seed_origin': True})
        out['katalog_dihapus'] = r.deleted_count

    akhir = (lambda n: f" · {n}" if apply else '')
    print(f"  item katalog contoh: {len(item_ids)} (ditaut data lain: {out['item_ditaut']}, "
          f"akan dihapus: {len(hapus_item)})" + akhir(f"dihapus {out['item_dihapus']}"))
    print(f"  katalog contoh: {len(cat_ids)} (dipakai → tanda contoh dicabut: {len(cabut)}, "
          f"kosong & tak ditaut → dihapus: {len(hapus_kat)})"
          + akhir(f"dicabut {out['katalog_dicabut_tanda']}, dihapus {out['katalog_dihapus']}"))
    return out


def health_like_seed(doc: dict) -> bool:
    """Dokumen kesehatan akun berbentuk persis seeder lama (bukan impor, bukan entri staf)."""
    keys = set(doc) - {'_id'}
    return (not doc.get('_seed_origin') and keys == _HEALTH_SEED_KEYS
            and doc.get('notes') == [] and doc.get('created_at') == doc.get('snapshot_date'))


async def run(db, apply: bool = False, health_unmarked: bool = False, katalog: bool = False) -> dict:
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

    if katalog:
        k = await katalog_contoh(db, apply)
        out['katalog'] = k
        out['dihapus'] += k['item_dihapus'] + k['katalog_dihapus']
    else:
        print("  (katalog contoh tidak disentuh; pakai --termasuk-katalog-contoh)")

    if apply and pairs:
        res = await rollup.recompute_pairs(db, pairs, actor='migrasi_hapus_data_contoh')
        out['rekap_dihitung_ulang'] = res.get('dates', 0)
        print(f"  rekap harian dihitung ulang: {res.get('dates', 0)} toko-tanggal")
    print(f"  total dihapus: {out['dihapus']}")
    return out


async def main(apply: bool, health_unmarked: bool, katalog: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    await run(db, apply, health_unmarked, katalog)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--termasuk-kesehatan-tanpa-penanda', dest='health', action='store_true')
    ap.add_argument('--termasuk-katalog-contoh', dest='katalog', action='store_true')
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.apply, a.health, a.katalog)))
