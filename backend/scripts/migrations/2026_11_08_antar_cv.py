"""Migrasi 2026-11-08 (Tahap 8 fase 2) — transaksi ANTAR CV: tim jahit CV Sukma, lawan transaksi, tagihan lama.

KENAPA: owner (7 Nov 2026) memutuskan vendor CMT tim jahit sendiri CV Sukma ditandai di master Vendor CMT, hutang/
piutang antar CV memakai hutang/piutang biasa berlabel "antar CV", dan PO maklon yang dijahit tim Sukma tidak
punya tagihan CMT. Kode baru (`core.intercompany`) menerapkannya untuk transaksi BARU; migrasi ini merapikan data
LAMA. Vendor dipilih lewat KODE (`--vendor-code`), tidak pernah lewat nama.

LANGKAH:
  1. Vendor tim jahit CV Sukma: `vendor_partners.owner_entity = 'SMU'` untuk vendor ber-kode `--vendor-code`.
  2. Lawan transaksi (master yang sudah ada, ditandai `intercompany_entity`) + sub-ledger lewat Auto Akun:
     pelanggan CV Sukma di buku DA (1-1301-…), klien maklon & pemasok CV Dewi Aditya di buku Sukma
     (1-1305-… / 4-1500-… / 2-1100-…).
  3. Tagihan CMT PO INTERNAL ke vendor itu: tagihan + jurnal DA-nya diberi label antar CV; tagihan yang BELUM
     dibayar sama sekali mendapat piutang pasangan di buku CV Sukma (dokumen + jurnal Dr 1-1305 / Cr 4-1500).
     Tagihan yang sudah dibayar sebagian/lunas hanya dilabeli dan dihitung (uangnya sudah keluar; pasangannya
     dicatat manual lewat Transaksi antar CV bila perlu — lihat Laporan Saldo antar CV).
  4. PO MAKLON ke vendor itu yang punya tagihan CMT / jadwal hutang: dilaporkan; dengan --apply tagihan yang BELUM
     dibayar dibatalkan (jurnal di-void) dan jadwal hutangnya dibatalkan. Yang sudah dibayar hanya dilaporkan.

Sifat: idempoten, tanpa hapus data, hanya mencetak JUMLAH (tanpa nama/angka pribadi). Bawaan PRATINJAU —
pratinjau memakai pembungkus basis data BACA-SAJA (tulis apa pun = galat), aman untuk salinan data produksi.

Runbook (VPS) — sesudah deploy kode Tahap 8 fase 2 dan migrasi 2026_11_08_entitas_cv:
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_antar_cv.py --vendor-code SGO
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_antar_cv.py --vendor-code SGO --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
VOID = ('cancelled', 'void', 'voided', 'rejected', 'batal')
SYSTEM_USER = {'id': 'system', 'name': 'migrasi 2026-11-08 antar CV', 'role': 'system'}


def _now():
    return datetime.now(timezone.utc)


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
            raise ReadOnlyError(f'pratinjau baca-saja: {name} pada {getattr(self._c, "name", "?")} ditolak')
        return getattr(self._c, name)


class ReadOnlyDB:
    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return _ROColl(self._db[name])

    def __getitem__(self, name):
        return _ROColl(self._db[name])


# ── aturan murni (diuji unit) ────────────────────────────────────────────────
def bill_bucket(bill: dict) -> str:
    """'unpaid' | 'partial' | 'paid' menurut nilai bersih tagihan & yang sudah dibayar."""
    from core.intercompany import bill_net_amount
    paid = float(bill.get('paid_amount') or 0)
    if paid <= 0.009:
        return 'unpaid'
    return 'paid' if paid >= bill_net_amount(bill) - 0.01 else 'partial'


async def find_vendor(db, code: str):
    code = (code or '').strip()
    if not code:
        return None
    v = await db.vendor_partners.find_one({'code': code}, {'_id': 0})
    if not v:
        v = await db.vendor_partners.find_one({'code': code.upper()}, {'_id': 0})
    return v


async def _bills_of_vendor(db, vendor: dict) -> list:
    from core import cmt_vendor_master
    flt = await cmt_vendor_master.payment_filter(db, vendor['id'])
    return [b async for b in db.dewi_cmt_payments.find(flt, {'_id': 0})
            if str(b.get('status') or '').lower() not in VOID]


async def step_vendor(db, apply: bool, code: str) -> dict:
    out = {'found': False, 'already': False, 'flagged': 0, 'other_flagged': 0}
    v = await find_vendor(db, code)
    out['other_flagged'] = await db.vendor_partners.count_documents({'owner_entity': 'SMU', 'code': {'$ne': code}})
    if not v:
        return out
    out['found'] = True
    out['already'] = v.get('owner_entity') == 'SMU'
    if not out['already']:
        out['flagged'] = 1
        if apply:
            await db.vendor_partners.update_one({'id': v['id']}, {'$set': {'owner_entity': 'SMU', 'updated_at': _now()}})
    out['_vendor'] = v
    return out


async def step_counterparts(db, apply: bool) -> dict:
    from core import intercompany as ic
    info = await ic.ensure_counterparts(db, SYSTEM_USER if apply else None, apply=apply)
    return {k: ('ada' if v.get('exists') and not v.get('created') else 'dibuat' if v.get('created')
                else 'akan dibuat') for k, v in info.items()}


async def step_internal_bills(db, apply: bool, vendor: dict) -> dict:
    from core import intercompany as ic
    from routes.dewi_maklon_finance import cmt_bill_entity
    out = {'bills': 0, 'labelled': 0, 'already_labelled': 0, 'journals_labelled': 0, 'mirror_created': 0,
           'mirror_exists': 0, 'mirror_failed': 0, 'unpaid': 0, 'partial': 0, 'paid': 0}
    for b in await _bills_of_vendor(db, vendor):
        if await cmt_bill_entity(db, b) != 'DA':
            continue
        out['bills'] += 1
        bucket = bill_bucket(b)
        out[bucket] += 1
        labels = ic.ic_labels('SMU', ic.KIND_SEWING, b['id'])
        if b.get('intercompany'):
            out['already_labelled'] += 1
        else:
            out['labelled'] += 1
            if apply:
                await db.dewi_cmt_payments.update_one({'id': b['id']}, {'$set': {**labels, 'updated_at': _now()}})
        if b.get('gl_je_id'):
            je = await db.rahaza_journal_entries.find_one({'id': b['gl_je_id']}, {'_id': 0, 'id': 1, 'intercompany': 1})
            if je is not None and not je.get('intercompany'):
                out['journals_labelled'] += 1
                if apply:
                    await db.rahaza_journal_entries.update_one({'id': b['gl_je_id']}, {'$set': labels})
                    await db.rahaza_journal_lines.update_many({'je_id': b['gl_je_id']}, {'$set': labels})
        if bucket != 'unpaid' or ic.bill_net_amount(b) <= 0 or not b.get('gl_je_id'):
            continue
        if await ic.find_sewing_ar(db, b['id']):
            out['mirror_exists'] += 1
            continue
        if not apply:
            out['mirror_created'] += 1
            continue
        fresh = await db.dewi_cmt_payments.find_one({'id': b['id']}, {'_id': 0})
        res = await ic.post_sewing_mirror(db, fresh, SYSTEM_USER)
        out['mirror_created' if res.get('ok') else 'mirror_failed'] += 1
    return out


async def step_maklon_bills(db, apply: bool, vendor: dict) -> dict:
    from routes.dewi_maklon_finance import cmt_bill_entity
    from routes.rahaza_posting import _void_je_by_source
    out = {'bills': 0, 'unpaid_cancelled': 0, 'unpaid': 0, 'paid_or_partial_kept': 0, 'journals_voided': 0,
           'void_failed': 0, 'schedules': 0, 'schedules_cancelled': 0, 'pos': 0}
    pos = set()
    for b in await _bills_of_vendor(db, vendor):
        if await cmt_bill_entity(db, b) != 'SMU':
            continue
        out['bills'] += 1
        pos.add(b.get('po_id'))
        if bill_bucket(b) != 'unpaid':
            out['paid_or_partial_kept'] += 1
            continue
        out['unpaid'] += 1
        if not apply:
            continue
        if b.get('gl_je_id'):
            v = await _void_je_by_source(db, 'cmt_ap_invoice', f"cmt_ap:{b['id']}", SYSTEM_USER,
                                         'Tahap 8: PO maklon dijahit tim CV Sukma — tanpa tagihan CMT', entity='SMU')
            if not v.get('ok'):
                out['void_failed'] += 1
                continue
            out['journals_voided'] += 1 if v.get('voided') else 0
        await db.dewi_cmt_payments.update_one({'id': b['id']}, {'$set': {
            'status': 'cancelled', 'cancel_reason': 'Dijahit tim sendiri — tanpa tagihan CMT (migrasi 2026-11-08)',
            'cancelled_at': _now(), 'updated_at': _now()}})
        out['unpaid_cancelled'] += 1
    async for s in db.dewi_cmt_ap_schedules.find({'vendor_id': vendor['id'], 'status': {'$ne': 'cancelled'}},
                                                 {'_id': 0, 'id': 1, 'po_id': 1, 'paid_amount': 1}):
        out['schedules'] += 1
        pos.add(s.get('po_id'))
        if apply and float(s.get('paid_amount') or 0) <= 0.009:
            await db.dewi_cmt_ap_schedules.update_one({'id': s['id']}, {'$set': {
                'status': 'cancelled', 'cancel_reason': 'Dijahit tim sendiri — tanpa jadwal hutang CMT',
                'updated_at': _now()}})
            out['schedules_cancelled'] += 1
    out['pos'] = len({p for p in pos if p})
    return out


async def run(db, *, apply: bool, vendor_code: str) -> dict:
    mode = 'TULIS (--apply)' if apply else 'PRATINJAU (tanpa perubahan, basis data baca-saja)'
    work = db if apply else ReadOnlyDB(db)
    print(f"[antar-cv] {mode} · kode vendor {vendor_code}")
    vs = await step_vendor(work, apply, vendor_code)
    vendor = vs.pop('_vendor', None)
    print(f"  1. vendor tim jahit CV Sukma: {'ditemukan' if vs['found'] else 'TIDAK ditemukan'} · "
          f"sudah ditandai {1 if vs['already'] else 0} · ditandai {vs['flagged']} · vendor lain bertanda {vs['other_flagged']}")
    cp = await step_counterparts(work, apply)
    print("  2. lawan transaksi: " + " · ".join(f"{k} {v}" for k, v in cp.items()))
    if not vendor:
        print("  3-4. dilewati (vendor tidak ditemukan)")
        return {'vendor': vs, 'counterparts': cp}
    if not apply:
        vendor = {**vendor, 'owner_entity': 'SMU'}
    ib = await step_internal_bills(work, apply, vendor)
    print(f"  3. tagihan CMT PO internal: {ib['bills']} (belum dibayar {ib['unpaid']} · sebagian {ib['partial']} · "
          f"lunas {ib['paid']}) · dilabeli {ib['labelled']} (sudah {ib['already_labelled']}) · jurnal dilabeli "
          f"{ib['journals_labelled']} · piutang pasangan Sukma {'dibuat' if apply else 'akan dibuat'} "
          f"{ib['mirror_created']} (sudah ada {ib['mirror_exists']}, gagal {ib['mirror_failed']})")
    mb = await step_maklon_bills(work, apply, vendor)
    print(f"  4. PO maklon dijahit tim Sukma: {mb['pos']} PO · tagihan CMT {mb['bills']} (belum dibayar {mb['unpaid']} → "
          f"{'dibatalkan ' + str(mb['unpaid_cancelled']) if apply else 'akan dibatalkan'} · sudah dibayar dilaporkan "
          f"{mb['paid_or_partial_kept']}) · jurnal di-void {mb['journals_voided']} (gagal {mb['void_failed']}) · "
          f"jadwal hutang {mb['schedules']} (dibatalkan {mb['schedules_cancelled']})")
    return {'vendor': vs, 'counterparts': cp, 'internal_bills': ib, 'maklon_bills': mb}


async def _main(apply: bool, vendor_code: str):
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        await run(client[DB_NAME], apply=apply, vendor_code=vendor_code)
    finally:
        client.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    ap.add_argument('--vendor-code', required=True, help='kode vendor CMT tim jahit CV Sukma (master Vendor CMT)')
    a = ap.parse_args()
    asyncio.run(_main(a.apply, a.vendor_code))
