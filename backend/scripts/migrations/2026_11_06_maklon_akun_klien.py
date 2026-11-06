"""Migrasi 2026-11-06 (Tahap 2, paket maklon) — akun per klien maklon + piutang terjadwal.

KENAPA (keputusan owner 6 Nov 2026):
  * Pendapatan maklon per klien dicatat di akun sendiri 4-1500-<KODE> (di bawah kelompok 4-1500
    Pendapatan Maklon) dan piutangnya di sub-ledger 1-1305-<KODE>. Dulu semua pendapatan maklon jatuh
    ke 4-1100 Penjualan Garment dan piutangnya ke 1-1301 Piutang Dagang.
  * Tidak ada lagi langkah "terbitkan invoice": begitu PO dikonfirmasi lahir piutang TERJADWAL, dan
    pendapatan dibukukan per kiriman ke klien (core.maklon_ledger).

LANGKAH:
  1. Akun per klien — tiap klien maklon aktif mendapat 1-1305-<KODE> (Auto Akun `maklon_client`) dan
     4-1500-<KODE> (Auto Akun `maklon_revenue`). Akun lama dicocokkan lewat tipe + id klien
     (flags.subledger_entity_type/_id), bukan nama.
  2. Draf piutang maklon lama (INV-MKL-… status draf, belum dijurnal) → piutang terjadwal. Kiriman ke
     klien yang sudah terjadi DIBUKUKAN pendapatannya (tanggal kirim; periode tertutup → hari ini).
  3. LAPORAN jurnal maklon lama (faktur yang sudah terbit) yang memakai akun pendapatan/piutang di
     luar 4-1500 / 1-1305. Hanya dilaporkan — kecuali dijalankan dengan `--apply --reclass`: per klien
     dibuat SATU jurnal penyesuaian (Dr akun pendapatan lama / Cr 4-1500-<KODE>; Dr 1-1305-<KODE> / Cr
     akun piutang lama untuk sisa piutang yang belum dibayar). Jurnal lama TIDAK diubah; dokumen piutang
     lama diarahkan ke akun piutang klien supaya pembayaran berikutnya menutup akun yang benar.

Sifat: idempoten (aman diulang), tanpa hapus, hanya mencetak JUMLAH (tanpa data pribadi).
Bawaan PRATINJAU; tulis dengan --apply (+ --reclass untuk jurnal penyesuaian).

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_maklon_akun_klien.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_maklon_akun_klien.py --apply
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_maklon_akun_klien.py --apply --reclass
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
SYS_USER = {'id': 'system', 'name': 'migrasi 2026-11-06'}
REV_GROUP = '4-1500'
AR_PARENT = '1-1305'


# ── murni (diuji unit) ───────────────────────────────────────────────────────
def is_own_revenue(code: str) -> bool:
    return bool(code) and (code == REV_GROUP or code.startswith(REV_GROUP[:5]))


def is_own_ar(code: str) -> bool:
    return bool(code) and (code == AR_PARENT or code.startswith(AR_PARENT + '-'))


def reclass_lines(rev_by_old: dict, ar_by_old: dict, new_rev: str, new_ar: str) -> list:
    """Baris jurnal penyesuaian satu klien. rev_by_old/ar_by_old = {akun lama: nilai}."""
    lines = []
    for code, amt in sorted(rev_by_old.items()):
        amt = round(float(amt or 0), 2)
        if amt > 0 and not is_own_revenue(code):
            lines += [{'account_code': code, 'debit': amt, 'credit': 0,
                       'description': 'Reklasifikasi pendapatan maklon ke akun klien'},
                      {'account_code': new_rev, 'debit': 0, 'credit': amt,
                       'description': 'Reklasifikasi pendapatan maklon ke akun klien'}]
    for code, amt in sorted(ar_by_old.items()):
        amt = round(float(amt or 0), 2)
        if amt > 0 and not is_own_ar(code):
            lines += [{'account_code': new_ar, 'debit': amt, 'credit': 0,
                       'description': 'Reklasifikasi sisa piutang maklon ke sub-ledger klien'},
                      {'account_code': code, 'debit': 0, 'credit': amt,
                       'description': 'Reklasifikasi sisa piutang maklon ke sub-ledger klien'}]
    return lines


# ── langkah ──────────────────────────────────────────────────────────────────
async def step_accounts(db, apply: bool) -> dict:
    out = {'clients': 0, 'ar_missing': 0, 'rev_missing': 0, 'created': 0, 'errors': 0}
    async for c in db.dewi_maklon_clients.find({'active': {'$ne': False}}, {'_id': 0}):
        out['clients'] += 1
        missing = []
        for etype, key in (('maklon_client', 'ar_missing'), ('maklon_revenue', 'rev_missing')):
            if not await db.rahaza_coa_accounts.find_one(
                    {'flags.subledger_entity_type': etype, 'flags.subledger_entity_id': c['id']}, {'_id': 0, 'code': 1}):
                out[key] += 1
                missing.append(etype)
        if apply and missing:
            from routes.coa_auto import ensure_subledger_for_entity
            for etype in missing:
                res = await ensure_subledger_for_entity(db, etype, c, SYS_USER)
                out['created' if res.get('ok') else 'errors'] += 1
    return out


async def step_schedules(db, apply: bool) -> dict:
    out = {'drafts': 0, 'converted': 0, 'errors': 0, 'dispatch_lines': 0}
    from core import dispatch_capacity as dcap
    async for ar in db.rahaza_ar_invoices.find(
            {'source_module': 'maklon_po', 'status': 'draft', 'schedule_mode': {'$ne': 'v2'}}, {'_id': 0}):
        if ar.get('gl_je_id'):
            continue
        po_id = ar.get('linked_maklon_po_id')
        po = await db.production_pos.find_one({'id': po_id}, {'_id': 0, 'status': 1, 'business_type': 1})
        if not po or po.get('business_type') != 'maklon':
            continue
        out['drafts'] += 1
        ids = [i['id'] async for i in db.po_items.find({'po_id': po_id}, {'_id': 0, 'id': 1})]
        out['dispatch_lines'] += len(await dcap.buyer_dispatch_items(db, po_item_ids=ids)) if ids else 0
        if apply:
            from core import maklon_ledger
            res = await maklon_ledger.sync_ar_schedule(db, po_id, SYS_USER)
            out['converted' if res.get('ok') and not res.get('legacy') else 'errors'] += 1
    return out


async def _legacy_postings(db) -> dict:
    """{client_id: {'rev': {akun: nilai}, 'ar_docs': [(doc_coll, doc_id, akun, sisa)]}} dari faktur lama."""
    per: dict = {}
    async for je in db.rahaza_journal_entries.find(
            {'source_module': 'maklon_ar_invoice', 'status': {'$ne': 'voided'}}, {'_id': 0}):
        ref = str(je.get('source_ref') or '')
        doc_id = ref.split(':', 1)[1] if ':' in ref else ''
        ar = await db.rahaza_ar_invoices.find_one({'id': doc_id}, {'_id': 0})
        coll = 'rahaza_ar_invoices'
        if not ar:
            ar = await db.dewi_maklon_invoices.find_one({'id': doc_id}, {'_id': 0})
            coll = 'dewi_maklon_invoices'
        if not ar:
            continue
        cid = ar.get('customer_id') or ar.get('client_id')
        if not cid:
            continue
        b = per.setdefault(cid, {'rev': {}, 'ar_docs': []})
        debit_lines = [ln for ln in je.get('lines') or [] if float(ln.get('debit') or 0) > 0]
        ar_code = (ar.get('gl_ar_account_code')
                   or (max(debit_lines, key=lambda x: float(x.get('debit') or 0)).get('account_code')
                       if debit_lines else None))
        for ln in je.get('lines') or []:
            cr = float(ln.get('credit') or 0)
            if cr > 0 and (ln.get('account_type') or '').upper() == 'REVENUE':
                b['rev'][ln['account_code']] = round(b['rev'].get(ln['account_code'], 0) + cr, 2)
        due = float(ar.get('amount_due') if ar.get('amount_due') is not None
                    else ar.get('balance_amount') or 0)
        b['ar_docs'].append((coll, ar['id'], ar_code, round(max(due, 0.0), 2)))
    return per


async def step_reclass(db, apply: bool, reclass: bool) -> dict:
    out = {'clients_with_old_postings': 0, 'revenue_outside_4_1500': 0.0, 'open_ar_outside_1_1305': 0.0,
           'journals_posted': 0, 'already_done': 0, 'skipped_no_account': 0, 'errors': 0}
    per = await _legacy_postings(db)
    for cid, b in per.items():
        rev = {k: v for k, v in b['rev'].items() if not is_own_revenue(k)}
        ar_by: dict = {}
        for _coll, _id, code, due in b['ar_docs']:
            if code and not is_own_ar(code) and due > 0:
                ar_by[code] = round(ar_by.get(code, 0) + due, 2)
        if not rev and not ar_by:
            continue
        out['clients_with_old_postings'] += 1
        out['revenue_outside_4_1500'] = round(out['revenue_outside_4_1500'] + sum(rev.values()), 2)
        out['open_ar_outside_1_1305'] = round(out['open_ar_outside_1_1305'] + sum(ar_by.values()), 2)
        if not (apply and reclass):
            continue
        ref = f'mklreclass:{cid}'
        from routes.rahaza_posting import _find_existing_je
        if await _find_existing_je(db, 'maklon_reclass', ref):
            out['already_done'] += 1
            continue
        from core.maklon_ledger import client_accounts
        acc = await client_accounts(db, cid, SYS_USER)
        if not acc.get('revenue') or (ar_by and not acc.get('ar')):
            out['skipped_no_account'] += 1
            continue
        lines = reclass_lines(rev, ar_by, acc['revenue'], acc.get('ar'))
        if not lines:
            continue
        from routes.dewi_maklon_finance import post_maklon_reclass
        from utils.waktu import today_wib
        res = await post_maklon_reclass(db, lines=lines, je_date=today_wib(), source_ref=ref, user=SYS_USER,
                                        memo='Reklasifikasi pendapatan & piutang maklon ke akun per klien (Tahap 2)')
        if not res.get('ok'):
            out['errors'] += 1
            continue
        out['journals_posted'] += 1
        if acc.get('ar'):
            for coll, did, code, due in b['ar_docs']:
                if code and not is_own_ar(code):
                    await db[coll].update_one({'id': did}, {'$set': {
                        'gl_ar_account_code': acc['ar'], 'gl_ar_account_code_before_reclass': code,
                        'reclass_je_number': res.get('je_number')}})
    return out


async def run(db, apply: bool = False, reclass: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[maklon-akun-klien] {mode}" + (' + reklasifikasi' if apply and reclass else ''))
    acc = await step_accounts(db, apply)
    print(f"  1. klien maklon aktif: {acc['clients']} · tanpa akun piutang: {acc['ar_missing']} · "
          f"tanpa akun pendapatan: {acc['rev_missing']}" + (f" · dibuat: {acc['created']} · gagal: {acc['errors']}"
                                                            if apply else ''))
    sch = await step_schedules(db, apply)
    print(f"  2. draf piutang maklon lama: {sch['drafts']} (baris kiriman ke klien: {sch['dispatch_lines']})"
          + (f" · dikonversi: {sch['converted']} · gagal: {sch['errors']}" if apply else ''))
    rc = await step_reclass(db, apply, reclass)
    print(f"  3. klien dengan jurnal faktur lama di luar akun klien: {rc['clients_with_old_postings']} · "
          f"pendapatan di luar 4-1500: Rp {rc['revenue_outside_4_1500']:,.0f} · sisa piutang di luar 1-1305: "
          f"Rp {rc['open_ar_outside_1_1305']:,.0f}"
          + (f" · jurnal penyesuaian: {rc['journals_posted']} · sudah ada: {rc['already_done']} · "
             f"tanpa akun: {rc['skipped_no_account']} · gagal: {rc['errors']}" if apply and reclass
             else ' (hanya laporan; reklasifikasi dengan --apply --reclass)'))
    return {'accounts': acc, 'schedules': sch, 'reclass': rc}


async def main(apply: bool, reclass: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    await run(db, apply, reclass)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--reclass', action='store_true', help='buat jurnal penyesuaian reklasifikasi (butuh --apply)')
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.apply, a.reclass)))
