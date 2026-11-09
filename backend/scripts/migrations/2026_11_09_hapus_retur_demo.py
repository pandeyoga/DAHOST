"""Migrasi 2026-11-09 (audit gudang G13, keputusan ★ "ya") — buang RETUR MARKETING DEMO.

KENAPA: `marketing_returns` di VPS berisi 30 retur buatan seeder lama (`created_by='system'`, tanggal
Agustus–September, tanpa item katalog dan tanpa pesanan yang ada). Tombol Gudang → Retur Fisik → "Tarik
dari Marketing" akan menjadikannya 22 pekerjaan retur sampah yang tidak tertaut barang mana pun.

Yang dihapus (SEMUA syarat harus terpenuhi — `calon_demo`):
  * `created_by == 'system'` dan bukan hasil impor (tanpa `_import_session_id` / `import_session_id`);
  * tidak menunjuk item katalog (`catalog_item_id` kosong) dan nomor pesanannya tidak ada di `marketing_orders`;
  * tidak punya credit note (`rahaza_credit_notes`) dan tidak punya pekerjaan Retur Fisik yang SUDAH
    diputuskan / menggerakkan stok (restocked, Resolved, Reversed). Pekerjaan Retur Fisik yang masih
    Pending/Cancelled hasil "Tarik dari Marketing" atas retur demo ikut dihapus.
Yang tidak memenuhi syarat hanya DILAPORKAN beserta alasannya.

Sifat: idempoten. Bawaan PRATINJAU. `--apply` menulis cadangan JSON (dokumen yang akan dihapus) lebih
dulu ke `--cadangan` (bawaan: folder kerja), baru menghapus. JANGAN dijalankan di VPS tanpa backup DB dan
persetujuan owner atas daftar pratinjau.

Runbook (VPS, sesudah disetujui):
    docker exec dahost-backend-1 python scripts/migrations/2026_11_09_hapus_retur_demo.py
    docker exec dahost-backend-1 python scripts/migrations/2026_11_09_hapus_retur_demo.py --apply --cadangan /app/backups
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

MKT, WH = 'marketing_returns', 'wh_returns'
BATAS = 50_000
WH_TERHAPUS_OK = ('Pending', 'Cancelled')   # pekerjaan gudang yang belum memutuskan apa pun


def alasan_bukan_demo(ret: dict, order_ids: set, cn_ret_ids: set, wh_rows: list) -> str:
    """'' bila retur ini demo yang aman dihapus; selain itu alasan (fungsi murni, diuji unit)."""
    if str(ret.get('created_by') or '') != 'system':
        return 'dibuat pengguna (bukan seeder)'
    if ret.get('_import_session_id') or ret.get('import_session_id'):
        return 'hasil impor Seller Center'
    if ret.get('catalog_item_id'):
        return 'menunjuk item katalog'
    if ret.get('order_id') and ret['order_id'] in order_ids:
        return f"pesanan {ret['order_id']} ada di data pesanan"
    if ret.get('id') in cn_ret_ids:
        return 'sudah punya credit note'
    for w in wh_rows:
        if w.get('restocked') or w.get('status') not in WH_TERHAPUS_OK:
            return f"Retur Fisik {w.get('return_code') or w.get('id')} sudah diproses gudang ({w.get('status')})"
    return ''


async def run(db, apply: bool = False, cadangan: str = '.') -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[hapus-retur-demo] {mode}")
    rets = await db[MKT].find({'created_by': 'system'}, {'_id': 0}).to_list(BATAS)
    oids = sorted({r.get('order_id') for r in rets if r.get('order_id')})
    order_ids = {o['order_id'] for o in await db.marketing_orders.find(
        {'order_id': {'$in': oids}}, {'_id': 0, 'order_id': 1}).to_list(BATAS)} if oids else set()
    rids = [r['id'] for r in rets if r.get('id')]
    cn_ret_ids = set()
    if rids:
        async for cn in db.rahaza_credit_notes.find(
                {'$or': [{'marketing_return_id': {'$in': rids}}, {'return_id': {'$in': rids}},
                         {'source_id': {'$in': rids}}]}, {'_id': 0, 'marketing_return_id': 1, 'return_id': 1,
                                                          'source_id': 1}):
            cn_ret_ids |= {cn.get(k) for k in ('marketing_return_id', 'return_id', 'source_id') if cn.get(k)}
    wh_by: dict = {}
    if rids:
        async for w in db[WH].find({'source_marketing_return_id': {'$in': rids}}, {'_id': 0}):
            wh_by.setdefault(w['source_marketing_return_id'], []).append(w)
    hapus, simpan = [], []
    for r in rets:
        why = alasan_bukan_demo(r, order_ids, cn_ret_ids, wh_by.get(r.get('id'), []))
        (simpan if why else hapus).append((r, why))
    wh_hapus = [w for r, _ in hapus for w in wh_by.get(r['id'], [])]
    print(f"  retur Marketing created_by=system: {len(rets)} · demo aman dihapus: {len(hapus)} "
          f"(+ {len(wh_hapus)} pekerjaan Retur Fisik Pending/Batal) · dipertahankan: {len(simpan)}")
    for r, why in simpan[:50]:
        print(f"    tetap: {r.get('id')} {r.get('date')} {r.get('order_id') or '-'} — {why}")
    out = {'scanned': len(rets), 'demo': len(hapus), 'kept': len(simpan), 'wh_jobs': len(wh_hapus),
           'deleted': 0, 'deleted_wh': 0, 'backup': None}
    if not apply or not hapus:
        return out
    os.makedirs(cadangan, exist_ok=True)
    path = os.path.join(cadangan, f"cadangan_retur_demo_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'marketing_returns': [r for r, _ in hapus], 'wh_returns': wh_hapus}, f, default=str,
                  ensure_ascii=False, indent=1)
    out['backup'] = path
    print(f"  cadangan ditulis: {path}")
    ids = [r['id'] for r, _ in hapus]
    if wh_hapus:
        res = await db[WH].delete_many({'id': {'$in': [w['id'] for w in wh_hapus]},
                                        'status': {'$in': list(WH_TERHAPUS_OK)}, 'restocked': {'$ne': True}})
        out['deleted_wh'] = res.deleted_count
        try:
            from utils.notif_unified import resolve_for_source
            for w in wh_hapus:
                await resolve_for_source(db, WH, w['id'])
        except Exception as e:  # noqa: BLE001 — notifikasi tertinggal tidak menggagalkan migrasi
            print(f"  (penutupan notifikasi retur gagal: {e})")
    res = await db[MKT].delete_many({'id': {'$in': ids}, 'created_by': 'system'})
    out['deleted'] = res.deleted_count
    print(f"  dihapus: {out['deleted']} retur Marketing, {out['deleted_wh']} Retur Fisik")
    return out


async def main(apply: bool, cadangan: str) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    await run(db, apply, cadangan)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--cadangan', default='.', help='folder cadangan JSON (dibuat bila belum ada)')
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.apply, a.cadangan)))
