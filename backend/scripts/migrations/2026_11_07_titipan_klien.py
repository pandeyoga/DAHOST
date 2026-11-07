"""Migrasi 2026-11-07 (Tahap 9C) — barang klien maklon dipindah dari MASTER PRODUK DA ke STOK TITIPAN KLIEN.

KENAPA: keputusan owner 7 Nov 2026 — CV Dewi Aditya memiliki semua bahan & stok, CV Sukma (maklon) tidak punya stok,
dan barang jadi maklon MILIK KLIEN (di luar neraca DA). Kode lama (K14, 2 Nov) membuat barang "milik klien" di master
produk DA (`rahaza_materials.owner_type = "client"`) dan menaruh stoknya di `rahaza_material_stock`. Kode baru
(`core.client_goods`) mencatat barang klien per klien × artikel Katalog Buyer, hanya pcs, di `dewi_maklon_inventory`.

LANGKAH (per barang "milik klien" di master DA):
  1. Cocokkan ke artikel Katalog Buyer TANPA MENEBAK:
       a. tautan dokumen sumbernya: baris Terima & QC yang menunjuk barang ini → baris PO → artikel/varian katalog
          (harus tepat SATU artikel/varian);
       b. bila tidak ada: SKU varian yang PERSIS sama di katalog klien pemiliknya (harus tepat satu).
     Artikel milik klien lain = TIDAK cocok. Yang tidak cocok hanya DIDAFTAR, tidak diubah.
  2. Stoknya dipindah: tiap baris `rahaza_material_stock` (qty ≠ 0) → satu mutasi "Pindah dari master barang DA" di
     stok titipan (kunci unik per baris → idempoten), lalu baris DA dinolkan + jejak di `rahaza_stock_ledger`.
  3. Dokumen yang menunjuk barang ini (baris Terima & QC, baris surat jalan yang sudah mengurangi stok, catatan
     selisih klien) diberi kunci stok titipan, supaya koreksi/hapus/selisih berikutnya bergerak di stok titipan.
  4. Barang di master DA DINONAKTIFKAN (tidak dihapus): `active = false` + tanda pindah.
  5. Dilaporkan (tanpa perubahan): baris Terima & QC PO maklon yang stoknya tercatat di barang DA BIASA (SKU klien sama
     dengan SKU DA, peringatan K14 lama) — stoknya tercampur dengan stok DA dan harus dipisah manual lewat opname.

Sifat: idempoten, tanpa hapus. Ringkasan berisi JUMLAH dan kode SKU saja (tanpa nama klien/orang, tanpa nilai uang).
Bawaan PRATINJAU dengan basis data BACA-SAJA (tulis apa pun = galat); tulis dengan --apply.

Runbook (VPS) — sesudah deploy kode Tahap 9C:
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_titipan_klien.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_titipan_klien.py --apply
"""
import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import client_goods as cg  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
TAG = 'migrasi-2026-11-07-titipan-klien'
SYSTEM_USER = {'id': 'system', 'name': 'migrasi 2026-11-07 titipan klien', 'role': 'system'}
DA_OWNERSHIP = (None, '', 'cv_da', 'own')


def _now():
    return datetime.now(timezone.utc)


def _qty(row: dict) -> float:
    for f in ('qty', 'quantity', 'total_qty'):
        v = row.get(f)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


# ── pembungkus BACA-SAJA untuk pratinjau ───────────────────────────────────────
class ReadOnlyError(RuntimeError):
    pass


_WRITES = {'insert_one', 'insert_many', 'update_one', 'update_many', 'replace_one', 'delete_one', 'delete_many',
           'bulk_write', 'find_one_and_update', 'find_one_and_replace', 'find_one_and_delete', 'create_index',
           'drop', 'drop_index'}


class _ROColl:
    def __init__(self, coll):
        self._c = coll

    def __getattr__(self, name):
        if name in _WRITES:
            async def _deny(*_a, **_k):
                raise ReadOnlyError(f'pratinjau mencoba menulis ({name}) — tidak diizinkan')
            return _deny
        return getattr(self._c, name)


class ReadOnlyDB:
    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return _ROColl(getattr(self._db, name))

    def __getitem__(self, name):
        return _ROColl(self._db[name])


# ── pencocokan (tanpa menebak) ─────────────────────────────────────────────────
async def match_item(db, item: dict) -> dict:
    """Artikel Katalog Buyer untuk satu barang "milik klien" di master DA → identitas atau {'ok': False, 'reason'}."""
    owner = item.get('owner_client_id') or ''
    lines = await db.cmt_receipt_lines.find({'fg_material_id': item['id']}, {'_id': 0}).to_list(5000)
    pi_ids = sorted({ln.get('po_item_id') for ln in lines if ln.get('po_item_id')})
    links = set()
    for pid in pi_ids:
        pi = await db.po_items.find_one({'id': pid}, {'_id': 0, 'catalog_item_id': 1, 'maklon_variant_id': 1}) or {}
        if pi.get('catalog_item_id'):
            links.add((pi['catalog_item_id'], pi.get('maklon_variant_id') or ''))
    if len(links) > 1:
        return {'ok': False, 'reason': f'baris penerimaannya menunjuk {len(links)} artikel/varian katalog berbeda'}
    if len(links) == 1:
        cat_id, var_id = links.pop()
        ident = await cg.resolve_identity(db, catalog_id=cat_id, variant_id=var_id, sku=item.get('code') or '',
                                          color=item.get('color') or item.get('color_name') or '',
                                          size=item.get('size_code') or '')
    elif owner:
        ident = await cg.resolve_identity(db, client_id=owner, sku=item.get('code') or '',
                                          color=item.get('color') or item.get('color_name') or '',
                                          size=item.get('size_code') or '')
    else:
        return {'ok': False, 'reason': 'pemilik klien tidak tercatat dan tidak ada tautan baris PO ke katalog'}
    if not ident.get('ok'):
        return {'ok': False, 'reason': 'tidak ada artikel Katalog Buyer yang cocok persis'}
    if owner and ident.get('client_id') and ident['client_id'] != owner:
        return {'ok': False, 'reason': 'artikel katalog yang cocok milik klien lain'}
    if not ident.get('maklon_variant_id') and not ident.get('sku'):
        return {'ok': False, 'reason': 'artikel cocok tetapi varian tidak bisa ditentukan'}
    return ident


async def candidates(db) -> list:
    """Barang "milik klien" di master DA + barang yang baris stoknya bertanda barang klien (data lama)."""
    items = {m['id']: m for m in await db.rahaza_materials.find({'owner_type': 'client'}, {'_id': 0}).to_list(20000)}
    rows = await db.rahaza_material_stock.find(
        {'$or': [{'inventory_category': cg.KATEGORI}, {'ownership': {'$nin': list(DA_OWNERSHIP)}}]},
        {'_id': 0, 'material_id': 1, 'ownership': 1}).to_list(20000)
    for r in rows:
        mid = r.get('material_id')
        if mid and mid not in items:
            m = await db.rahaza_materials.find_one({'id': mid}, {'_id': 0})
            if m:
                items[mid] = {**m, 'owner_client_id': m.get('owner_client_id') or (
                    r.get('ownership') if r.get('ownership') not in DA_OWNERSHIP + ('maklon', 'maklon_client') else '')}
    return sorted(items.values(), key=lambda m: str(m.get('code') or ''))


async def move_item(db, item: dict, ident: dict, apply: bool) -> dict:
    out = {'rows': 0, 'qty': 0.0, 'negative_rows': 0, 'reserved_rows': 0, 'links': 0}
    rows = await db.rahaza_material_stock.find({'material_id': item['id']}, {'_id': 0}).to_list(1000)
    for r in rows:
        q = _qty(r)
        if not q:
            continue
        out['rows'] += 1
        out['qty'] += q
        if q < 0:
            out['negative_rows'] += 1
        if float(r.get('reserved_quantity') or 0):
            out['reserved_rows'] += 1
        if not apply:
            continue
        await cg.record(db, identity=ident, qty=int(round(q)), jenis='pindah_dari_master_da', source_type='migrasi',
                        source_key=f"migrasi_t9:{r.get('id') or item['id'] + ':' + str(r.get('location_id'))}",
                        ref={'source_label': 'Pindah dari master barang DA', 'material_id': item['id'],
                             'stock_row_id': r.get('id'), 'migration': TAG},
                        actor=SYSTEM_USER, notes='Stok barang klien dipindah dari master produk DA (Tahap 9C)',
                        location_id=r.get('location_id') or '', allow_negative=True)
        await db.rahaza_material_stock.update_one(
            {'material_id': item['id'], 'location_id': r.get('location_id')},
            {'$set': {'qty': 0, 'quantity': 0, 'total_qty': 0, 'available_quantity': 0, 'reserved_quantity': 0,
                      'updated_at': _now(), 'moved_to_client_stock_at': _now(),
                      'client_stock_key': ident['stock_key']}})
        await db.rahaza_stock_ledger.insert_one({
            'id': str(uuid.uuid4()), 'op': 'pindah_titipan_klien', 'material_id': item['id'],
            'location_id': r.get('location_id'), 'delta': -q, 'qty_after': 0, 'qty_before': q,
            'ref': {'source': TAG, 'client_stock_key': ident['stock_key']}, 'actor': SYSTEM_USER,
            'created_at': _now()})
    if apply:
        tag = {'client_goods': True, 'client_stock_key': ident['stock_key']}
        for coll, q in (('cmt_receipt_lines', {'fg_material_id': item['id']}),
                        ('buyer_shipment_items', {'fg_material_id': item['id'], 'fg_issued_at': {'$nin': [None, '']}})):
            res = await db[coll].update_many({**q, 'client_stock_key': {'$in': [None, '']}}, {'$set': tag})
            out['links'] += getattr(res, 'modified_count', 0) or 0
        ship_ids = [s['id'] for s in await db.buyer_shipment_items.find(
            {'fg_material_id': item['id']}, {'_id': 0, 'id': 1}).to_list(5000)]
        if ship_ids:
            res = await db.buyer_short_records.update_many(
                {'shipment_item_id': {'$in': ship_ids}, 'client_stock_key': {'$in': [None, '']}},
                {'$set': {'client_stock_key': ident['stock_key']}})
            out['links'] += getattr(res, 'modified_count', 0) or 0
        await db.rahaza_materials.update_one({'id': item['id']}, {'$set': {
            'active': False, 'client_goods_moved_at': _now(), 'client_goods_stock_key': ident['stock_key'],
            'deactivated_reason': 'Barang klien maklon dipindah ke stok titipan klien (Tahap 9C)',
            'deactivated_by': TAG, 'updated_at': _now()}})
    return out


async def report_mixed(db) -> list:
    """Baris Terima & QC PO maklon yang stoknya masuk barang DA BIASA (SKU sama) — hanya dilaporkan."""
    out = []
    lines = await db.cmt_receipt_lines.find(
        {'fg_stock_posted_at': {'$nin': [None, '']}, 'fg_material_id': {'$nin': [None, '']},
         'client_stock_key': {'$in': [None, '']}}, {'_id': 0}).to_list(50000)
    rc_cache: dict = {}
    for ln in lines:
        rid = ln.get('receipt_id')
        if rid not in rc_cache:
            rc = await db.cmt_receipts.find_one({'id': rid}, {'_id': 0, 'po_id': 1, 'receipt_code': 1}) or {}
            po = await db.production_pos.find_one({'id': rc.get('po_id')}, {'_id': 0, 'business_type': 1}) or {}
            rc_cache[rid] = (rc, cg.is_maklon(po.get('business_type')))
        rc, maklon = rc_cache[rid]
        if not maklon:
            continue
        m = await db.rahaza_materials.find_one({'id': ln['fg_material_id']}, {'_id': 0, 'owner_type': 1})
        if (m or {}).get('owner_type') == 'client':
            continue
        out.append({'receipt_code': rc.get('receipt_code') or rid, 'sku': ln.get('sku_code') or '',
                    'qty': int(ln.get('fg_stock_posted_qty') or 0)})
    return out


async def run(db, *, apply: bool) -> dict:
    mode = 'TULIS (--apply)' if apply else 'PRATINJAU (tanpa perubahan, basis data baca-saja)'
    work = db if apply else ReadOnlyDB(db)
    print(f'[titipan-klien] {mode}')
    summary = {'candidates': 0, 'already_moved': 0, 'matched': 0, 'moved': 0, 'unmatched': 0,
               'stock_rows': 0, 'stock_qty': 0.0, 'negative_rows': 0, 'reserved_rows': 0, 'links': 0,
               'unmatched_list': [], 'mixed_receipt_lines': []}
    for item in await candidates(work):
        summary['candidates'] += 1
        if item.get('client_goods_moved_at'):
            summary['already_moved'] += 1
            continue
        ident = await match_item(work, item)
        if not ident.get('ok'):
            summary['unmatched'] += 1
            summary['unmatched_list'].append({'sku': item.get('code') or '', 'reason': ident['reason']})
            continue
        summary['matched'] += 1
        res = await move_item(work, item, ident, apply)
        for k_src, k_dst in (('rows', 'stock_rows'), ('qty', 'stock_qty'), ('negative_rows', 'negative_rows'),
                             ('reserved_rows', 'reserved_rows'), ('links', 'links')):
            summary[k_dst] += res[k_src]
        if apply:
            summary['moved'] += 1
    summary['mixed_receipt_lines'] = await report_mixed(work)
    print(f"  barang 'milik klien' di master DA: {summary['candidates']} · sudah dipindah {summary['already_moved']} · "
          f"cocok ke Katalog Buyer {summary['matched']} · {'dipindah' if apply else 'akan dipindah'} "
          f"{summary['moved'] if apply else summary['matched']} · TIDAK cocok (tidak diubah) {summary['unmatched']}")
    print(f"  baris stok DA dipindah: {summary['stock_rows']} · total {summary['stock_qty']:g} pcs · baris minus "
          f"{summary['negative_rows']} · baris berreservasi {summary['reserved_rows']} · tautan dokumen {summary['links']}")
    for u in summary['unmatched_list']:
        print(f"    ! SKU {u['sku']}: {u['reason']}")
    print(f"  baris Terima & QC PO maklon yang stoknya tercampur di barang DA (SKU sama, periksa manual lewat opname): "
          f"{len(summary['mixed_receipt_lines'])}")
    for x in summary['mixed_receipt_lines'][:50]:
        print(f"    ! {x['receipt_code']} · SKU {x['sku']} · {x['qty']} pcs")
    return summary


async def _main(apply: bool):
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        await run(client[DB_NAME], apply=apply)
    finally:
        client.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    a = ap.parse_args()
    asyncio.run(_main(a.apply))
