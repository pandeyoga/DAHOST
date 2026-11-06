"""Migrasi 2026-11-07 — Tahap 6 (agen produksi): data lama ditautkan ke master yang kini wajib dipakai formulir.

KENAPA: keputusan owner 7 Nov (audit form Tahap 5) mengganti beberapa isian teks bebas dengan pilihan master
(id + nama). Dokumen lama tetap tampil apa adanya, tetapi tanpa id penyaring/rekap per master tidak cocok.
Migrasi ini HANYA menautkan nilai lama yang cocok PERSIS (tanpa beda huruf besar/kecil) dengan SATU entri
master; sisanya dibiarkan sebagai teks lama dan hanya dihitung.

  A. PO tanpa vendor yang sudah punya surat jalan NORMAL ke tepat SATU vendor → vendor PO diisi vendor itu
     (PR4: vendor kini dipilih saat kirim dan dicatat juga di PO). PO dengan >1 vendor hanya dilaporkan.
  B. Permak: `vendor_permak` teks → master Vendor CMT (`vendor_permak_kind/id/name`)               (PR1)
  C. Style RnD: `buyer` teks → master Klien maklon (`client_id/client_name`);
                `fabric_type` → nama kain master persis                                           (PR3)
  D. Riset Material: `vendor` teks → master supplier (`vendor_id/vendor_code`);
                     `category` → kategori material (`category_code`, nama master)                (PR6)
  E. Sample RnD: `sample_pic` teks → SATU karyawan aktif bernama sama (`sample_pic_employee_id`)   (HR4)

Sifat: IDEMPOTEN (hanya dokumen yang belum bertaut), tanpa hapus. Ringkasan berupa ANGKA saja (tanpa nama
orang/vendor). Bawaan hanya PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_produksi_tautan_master.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_produksi_tautan_master.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
EMPTY = {'$in': [None, '']}
TAG = 'migrasi-2026-11-07-tahap6'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(v) -> str:
    return str(v or '').strip().lower()


async def _index(cur, *fields) -> dict:
    """nilai (huruf kecil) → [dokumen]. Satu dokumen bisa terindeks lewat beberapa kolom (nama, kode)."""
    out: dict = {}
    async for d in cur:
        for f in fields:
            k = _key(d.get(f))
            if k and d not in out.setdefault(k, []):
                out[k].append(d)
    return out


def _one(idx: dict, value):
    hits = idx.get(_key(value)) or []
    return hits[0] if len(hits) == 1 else None


async def run(apply: bool) -> int:
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f'[tahap6-produksi] DB={DB_NAME} · {mode}')

    # ── A. PO tanpa vendor ← surat jalan NORMAL ─────────────────────────────────────────────────────
    a_ok = a_multi = 0
    async for po in db.production_pos.find({'vendor_id': EMPTY}, {'_id': 0, 'id': 1, 'po_number': 1}):
        vids = set()
        async for s in db.vendor_shipments.find({'po_id': po['id'], 'shipment_type': {'$in': [None, 'NORMAL']}},
                                                {'_id': 0, 'vendor_id': 1}):
            if s.get('vendor_id'):
                vids.add(s['vendor_id'])
        if len(vids) > 1:
            a_multi += 1
            print(f'  A ! PO {po.get("po_number")}: surat jalan ke {len(vids)} vendor berbeda — isi vendor PO manual')
        if len(vids) != 1:
            continue
        vid = vids.pop()
        from routes.production_rbac import resolve_vendor_doc
        v = await resolve_vendor_doc(db, vid)
        if not v:
            continue
        a_ok += 1
        if apply:
            await db.production_pos.update_one({'id': po['id'], 'vendor_id': EMPTY}, {'$set': {
                'vendor_id': vid, 'vendor_name': v.get('garment_name', ''), 'vendor_assigned_via': 'kirim_material',
                'vendor_assigned_by': TAG, 'vendor_assigned_at': _now(), 'updated_at': _now()}})
    print(f'  A PO tanpa vendor → diisi dari surat jalan: {a_ok} · lebih dari satu vendor (dilaporkan): {a_multi}')

    # ── B. Permak ───────────────────────────────────────────────────────────────────────────────────
    vp = await _index(db.vendor_partners.find({}, {'_id': 0, 'id': 1, 'name': 1, 'code': 1}), 'name', 'code')
    b_ok = b_left = 0
    async for d in db.dewi_cmt_permak.find({'vendor_permak': {'$nin': [None, '']}, 'vendor_permak_id': EMPTY},
                                           {'_id': 0, 'id': 1, 'vendor_permak': 1}):
        v = _one(vp, d.get('vendor_permak'))
        if not v:
            b_left += 1
            continue
        b_ok += 1
        if apply:
            await db.dewi_cmt_permak.update_one({'id': d['id'], 'vendor_permak_id': EMPTY}, {'$set': {
                'vendor_permak_kind': 'vendor_cmt', 'vendor_permak_id': v['id'],
                'vendor_permak_name': v.get('name') or '', 'vendor_permak': v.get('name') or '',
                'linked_by': TAG}})
    print(f'  B permak: vendor teks → master Vendor CMT {b_ok} · tetap teks lama {b_left}')

    # ── C. Style RnD ────────────────────────────────────────────────────────────────────────────────
    from routes.dewi_rnd_styles import fabric_type_names
    cl = await _index(db.dewi_maklon_clients.find({}, {'_id': 0, 'id': 1, 'name': 1, 'code': 1}), 'name', 'code')
    fabrics = {n.lower(): n for n in await fabric_type_names(db)}
    c_buyer = c_buyer_left = c_fab = c_fab_left = 0
    async for s in db.dewi_rnd_styles.find({'$or': [{'buyer': {'$nin': [None, '']}, 'client_id': EMPTY},
                                                    {'fabric_type': {'$nin': [None, '']}}]},
                                           {'_id': 0, 'id': 1, 'buyer': 1, 'client_id': 1, 'fabric_type': 1}):
        upd = {}
        if s.get('buyer') and not s.get('client_id'):
            c = _one(cl, s['buyer'])
            if c:
                upd.update({'client_id': c['id'], 'client_name': c.get('name') or '', 'buyer': c.get('name') or ''})
                c_buyer += 1
            else:
                c_buyer_left += 1
        ft = str(s.get('fabric_type') or '').strip()
        if ft:
            canon = fabrics.get(ft.lower())
            if canon and canon != ft:
                upd['fabric_type'] = canon
                c_fab += 1
            elif not canon:
                c_fab_left += 1
        if upd and apply:
            await db.dewi_rnd_styles.update_one({'id': s['id']}, {'$set': {**upd, 'updated_at': _now()}})
    print(f'  C style: buyer → Klien maklon {c_buyer} (tetap teks {c_buyer_left}) · '
          f'jenis kain dirapikan ke nama master {c_fab} (di luar master {c_fab_left})')

    # ── D. Riset Material ───────────────────────────────────────────────────────────────────────────
    from routes.dewi_rnd_materials import riset_categories
    sup = await _index(db.rahaza_suppliers.find({}, {'_id': 0, 'id': 1, 'name': 1, 'code': 1}), 'name', 'code')
    cats = await riset_categories(db)
    d_v = d_v_left = d_c = d_c_left = 0
    async for m in db.dewi_rnd_materials.find({'$or': [{'vendor': {'$nin': [None, '']}, 'vendor_id': EMPTY},
                                                       {'category': {'$nin': [None, '']}, 'category_code': EMPTY}]},
                                              {'_id': 0, 'id': 1, 'vendor': 1, 'vendor_id': 1, 'category': 1,
                                               'category_code': 1, 'vendor_is_prospect': 1}):
        upd = {}
        if m.get('vendor') and not m.get('vendor_id') and not m.get('vendor_is_prospect'):
            s = _one(sup, m['vendor'])
            if s:
                upd.update({'vendor_id': s['id'], 'vendor': s.get('name') or '', 'vendor_code': s.get('code') or '',
                            'vendor_is_prospect': False})
                d_v += 1
            else:
                d_v_left += 1
        if m.get('category') and not m.get('category_code'):
            k = _key(m['category'])
            c = next((c for c in cats if k in (c['code'].lower(), c['name'].lower())), None)
            if c:
                upd.update({'category': c['name'], 'category_code': c['code']})
                d_c += 1
            else:
                d_c_left += 1
        if upd and apply:
            await db.dewi_rnd_materials.update_one({'id': m['id']}, {'$set': {**upd, 'updated_at': _now()}})
    print(f'  D riset material: vendor → master supplier {d_v} (tetap teks {d_v_left}) · '
          f'kategori → daftar {d_c} (di luar daftar {d_c_left})')

    # ── E. Sample RnD ───────────────────────────────────────────────────────────────────────────────
    emp = await _index(db.rahaza_employees.find({'active': {'$ne': False}}, {'_id': 0, 'id': 1, 'name': 1}), 'name')
    e_ok = e_left = 0
    async for r in db.dewi_rnd_sample_requests.find(
            {'sample_pic': {'$nin': [None, '']}, 'sample_pic_employee_id': EMPTY,
             'sample_pic_external': {'$ne': True}}, {'_id': 0, 'id': 1, 'sample_pic': 1}):
        e = _one(emp, r.get('sample_pic'))
        if not e:
            e_left += 1
            continue
        e_ok += 1
        if apply:
            await db.dewi_rnd_sample_requests.update_one({'id': r['id'], 'sample_pic_employee_id': EMPTY}, {'$set': {
                'sample_pic_employee_id': e['id'], 'sample_pic': e.get('name') or '', 'sample_pic_external': False,
                'updated_at': _now()}})
    print(f'  E sample: PIC teks → karyawan {e_ok} · tetap teks lama {e_left}')
    print('[tahap6-produksi] selesai.')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    sys.exit(asyncio.run(run(ap.parse_args().apply)))
