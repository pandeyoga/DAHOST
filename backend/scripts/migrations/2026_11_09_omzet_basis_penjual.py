"""Migrasi 2026-11-09 (riset G5, keputusan owner K1/K5 "sesuai rekomendasi") — dasar omzet pesanan impor.

KENAPA: impor "Pesanan Marketplace" dulu memakai kolom platform "SKU Subtotal After Discount" (TikTok) /
"Subtotal Pesanan" (Shopee) langsung sebagai dasar omzet. Angka itu SUDAH dipotong diskon yang dibiayai
PLATFORM (terbukti 674/674 & 154/154 baris), padahal omzet perusahaan = sesudah diskon PENJUAL saja.
Pada berkas contoh TikTok omzet tercatat 2,2–4,1 % terlalu kecil. Mesin impor sudah dibetulkan
(`marketing_import_engine.omzet_basis_item`); pesanan yang SUDAH TERSIMPAN masih memakai dasar lama.

Yang dilakukan (hanya pesanan hasil impor `marketplace_orders` yang item-nya punya angka pembentuk):
  · per item: `sku_subtotal_after_all_discount` = nilai lama (angka platform), `sku_subtotal_after_discount`
    = dasar baru (sebelum diskon − diskon penjual), `omzet_basis_source`;
  · per pesanan: `revenue_product` & `revenue` = Σ dasar baru (subsidi platform tetap di
    `platform_discount_total`);
  · rekap harian turunan dihitung ulang untuk (toko, tanggal) yang berubah — kecuali periode terkunci
    (dilewati penghitung rekap seperti biasa).

Sifat: idempoten, tanpa hapus, hanya mencetak jumlah (tanpa data pembeli). Bawaan PRATINJAU.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_09_omzet_basis_penjual.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_09_omzet_basis_penjual.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.marketing_import_engine import omzet_basis_item  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
ORDERS = 'marketing_orders'
SUMBER = 'marketplace_orders'


def perbaiki_pesanan(o: dict) -> tuple:
    """(set Mongo untuk pesanan ini | None, selisih omzet). Murni — diuji unit."""
    items = [dict(it) for it in (o.get('items') or [])]
    if not items:
        return None, 0.0
    berubah = False
    total = 0.0
    for it in items:
        if it.get('omzet_basis_source'):
            total += float(it.get('sku_subtotal_after_discount') or 0)
            continue                                         # sudah dasar baru (idempoten)
        lama = it.get('sku_subtotal_after_discount')
        coba = dict(it)
        if lama is not None and coba.get('sku_subtotal_after_all_discount') is None:
            coba['sku_subtotal_after_all_discount'] = lama
        coba.pop('sku_subtotal_after_discount', None)
        nilai, cara, _w = omzet_basis_item(coba)
        if nilai is None or cara not in ('sebelum_dikurangi_diskon_penjual', 'platform_ditambah_subsidi'):
            total += float(lama or 0)
            continue
        it['sku_subtotal_after_all_discount'] = coba.get('sku_subtotal_after_all_discount')
        it['sku_subtotal_after_discount'] = nilai
        it['omzet_basis_source'] = cara
        berubah = True
        total += nilai
    if not berubah:
        return None, 0.0
    lama_omzet = float(o.get('revenue_product') or 0)
    total = round(total, 2)
    return {'items': items, 'revenue_product': total, 'revenue': total,
            'omzet_basis_migrasi': '2026-11-09'}, round(total - lama_omzet, 2)


async def run(apply: bool, db=None) -> dict:
    if db is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    q = {'_import_source_type': SUMBER, 'omzet_basis_migrasi': {'$exists': False}}
    n = naik = 0
    selisih = 0.0
    pasangan = set()
    async for o in db[ORDERS].find(q, {'_id': 0, 'id': 1, 'items': 1, 'revenue_product': 1,
                                       'account_id': 1, 'order_date': 1}):
        upd, d = perbaiki_pesanan(o)
        if upd is None:
            continue
        n += 1
        naik += d > 0
        selisih += d
        if apply:
            await db[ORDERS].update_one({'id': o['id']}, {'$set': upd})
            pasangan.add(o['id'])
    print(f"[omzet-basis] DB={DB_NAME} · pesanan {'diperbarui' if apply else 'akan diperbarui'}: {n} "
          f"(omzet naik di {naik} pesanan) · selisih omzet total Rp{round(selisih):,}".replace(',', '.'))
    out = {'pesanan': n, 'naik': naik, 'selisih': round(selisih, 2)}
    if apply and pasangan:
        from core import marketing_daily_rollup as rollup
        touched = set(await rollup.pairs_from_orders(db, {'id': {'$in': sorted(pasangan)}}))
        res = await rollup.recompute_pairs(db, touched, actor='migrasi-2026-11-09')
        out['rekap'] = {k: v for k, v in (res or {}).items() if k != 'details'}
        print(f"  rekap harian dihitung ulang: {out['rekap']}")
    if not apply:
        print("  Pratinjau saja. Jalankan lagi dengan --apply untuk menyimpan.")
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    asyncio.run(run(ap.parse_args().apply))
