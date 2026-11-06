"""Migrasi 2026-11-07 (Tahap 6, keputusan owner PG5) — supplier aksesoris ditautkan ke Master Supplier.

KENAPA: master aksesoris (`rahaza_materials` bertipe accessory) dan Request Pembelian Aksesoris
(`acc_purchase_requests`) dulu menyimpan supplier sebagai NAMA saja (kunci `supplier`). Mulai Tahap 6 form
keduanya memilih dari Master Supplier dan menyimpan `supplier_id` (+ `supplier_code`); nama tetap disimpan
untuk tampilan. Migrasi ini mengisi `supplier_id` pada dokumen LAMA.

ATURAN COCOK: nama tersimpan == nama supplier master setelah huruf besar/kecil & spasi diabaikan
(`routes.procurement_suppliers.loose_name_key` — aturan yang SAMA dengan tautan otomatis saat form lama
mengirim nama saja). Hanya bila cocok dengan TEPAT SATU supplier. Cocok >1 = ambigu, 0 = tanpa pasangan —
keduanya hanya dihitung (tidak diubah); pilih suppliernya lewat form Ubah Aksesoris.

Sifat: idempoten (dokumen yang sudah punya `supplier_id` dilewati), tanpa hapus, nama tidak diubah, hanya
mencetak JUMLAH. Bawaan PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_supplier_id_aksesoris.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_supplier_id_aksesoris.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
UNLINKED_Q = {'$or': [{'supplier_id': {'$exists': False}}, {'supplier_id': None}, {'supplier_id': ''}]}
# (koleksi, filter dokumen, label laporan) — field nama supplier di keduanya: `supplier`
TARGETS = (
    ('rahaza_materials', {'type': 'accessory'}, 'master aksesoris'),
    ('acc_purchase_requests', {}, 'request pembelian aksesoris'),
)
FIELD = 'supplier'


def _key(name) -> str:
    from routes.procurement_suppliers import loose_name_key
    return loose_name_key(name)


# ── murni (diuji unit) ───────────────────────────────────────────────────────
def plan_links(rows: list, suppliers: list, field: str = FIELD) -> dict:
    """Rencana tautan: {'link': [(id dokumen, supplier)], 'ambiguous': n, 'no_match': n, 'empty': n}."""
    idx: dict = {}
    for s in suppliers or []:
        k = _key(s.get('name'))
        if k and s.get('id'):
            idx.setdefault(k, []).append(s)
    out = {'link': [], 'ambiguous': 0, 'no_match': 0, 'empty': 0}
    for r in rows or []:
        k = _key(r.get(field))
        if not k:
            out['empty'] += 1
            continue
        hits = idx.get(k) or []
        if len(hits) == 1:
            out['link'].append((r.get('id'), hits[0]))
        elif hits:
            out['ambiguous'] += 1
        else:
            out['no_match'] += 1
    return out


# ── langkah ──────────────────────────────────────────────────────────────────
async def step(db, coll: str, base_q: dict, suppliers: list, apply: bool) -> dict:
    rows = await db[coll].find({**base_q, **UNLINKED_Q}, {'_id': 0, 'id': 1, FIELD: 1}).to_list(None)
    plan = plan_links(rows, suppliers)
    res = {'unlinked': len(rows), 'to_link': len(plan['link']), 'ambiguous': plan['ambiguous'],
           'no_match': plan['no_match'], 'no_name': plan['empty'], 'linked': 0}
    if apply:
        for doc_id, sup in plan['link']:
            if not doc_id:
                continue
            r = await db[coll].update_one({'id': doc_id, **UNLINKED_Q},
                                          {'$set': {'supplier_id': sup['id'], 'supplier_code': sup.get('code')}})
            res['linked'] += r.modified_count
    return res


async def run(db, apply: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[supplier-id-aksesoris] {mode}")
    suppliers = await db.rahaza_suppliers.find({}, {'_id': 0, 'id': 1, 'code': 1, 'name': 1}).to_list(None)
    print(f"  master supplier: {len(suppliers)}")
    out = {}
    for i, (coll, q, label) in enumerate(TARGETS, 1):
        r = await step(db, coll, q, suppliers, apply)
        out[coll] = r
        print(f"  {i}. {label}: belum tertaut {r['unlinked']} · cocok 1 supplier {r['to_link']}"
              f" · ambigu {r['ambiguous']} · tanpa pasangan {r['no_match']} · tanpa nama {r['no_name']}"
              + (f" · ditautkan {r['linked']}" if apply else ''))
    return out


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
    asyncio.run(_main(ap.parse_args().apply))
