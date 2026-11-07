"""Migrasi 2026-11-07 (Tahap 9, agen pantau) — balik jurnal OVER/UNDER dari laporan selisih vendor.

KENAPA: jurnal `production_variance` (Laporan Variance → "Posting ke GL") membuat nilai buku berbeda dari stok:
  · OVERPRODUCTION = Dr Persediaan FG / Cr Pendapatan selisih TANPA gerakan stok — barang lebihnya sudah masuk
    stok dan buku lewat Terima & QC, jadi tercatat dua kali.
  · UNDERPRODUCTION = Dr Rugi selisih / Cr WIP sebesar biaya FG (termasuk upah jahit yang tidak pernah terjadi);
    sisa WIP PO yang sama ditutup lagi saat Tutup PO (`core.po_wip`).
Mulai Tahap 9 endpoint posting-nya menjawab 410. Migrasi ini MEMBALIK jurnal lama yang terlanjur diposting
(jurnal pembalik, bukan hapus — jejak audit tetap) dan menandai laporan vendornya `gl_retired`.

Sifat: idempoten (jurnal yang sudah punya pembalik dilewati), tanpa hapus, hanya mencetak JUMLAH dan nomor jurnal
(tanpa data pribadi). Bawaan PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_jurnal_selisih_produksi.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_jurnal_selisih_produksi.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
SOURCE = 'production_variance'
REVERSE_SOURCE = 'production_variance_retired'
REASON = 'Tahap 9: jurnal selisih dari laporan vendor dipensiunkan (nilai buku harus sama dengan stok)'
ACTOR = {'id': 'migrasi-tahap9', 'name': 'Migrasi Tahap 9'}


# ── murni (diuji unit) ───────────────────────────────────────────────────────
def plan(journals: list) -> dict:
    """Pisahkan jurnal yang perlu dibalik dari yang sudah dibalik / sudah batal."""
    out = {'reverse': [], 'already': 0, 'voided': 0}
    for je in journals or []:
        if (je.get('status') or '') == 'voided':
            out['voided'] += 1
        elif je.get('reversed_by_je_id'):
            out['already'] += 1
        else:
            out['reverse'].append(je)
    return out


async def run(db, apply: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[jurnal-selisih-produksi] {mode}")
    journals = await db.rahaza_journal_entries.find({'source_module': SOURCE}, {'_id': 0}).to_list(None)
    p = plan(journals)
    total = sum(float(je.get('total_debit') or je.get('amount') or 0) for je in p['reverse'])
    res = {'found': len(journals), 'to_reverse': len(p['reverse']), 'already_reversed': p['already'],
           'voided': p['voided'], 'reversed': 0, 'failed': 0, 'flagged_reports': 0}
    print(f"  jurnal laporan selisih: {res['found']} · perlu dibalik {res['to_reverse']} "
          f"(nilai ±{round(total, 2)}) · sudah dibalik {res['already_reversed']} · batal {res['voided']}")
    if apply and p['reverse']:
        from routes.rahaza_posting import reverse_journal_entry
        for je in p['reverse']:
            lines = await db.rahaza_journal_lines.find({'je_id': je['id']}, {'_id': 0}).to_list(None)
            out = await reverse_journal_entry(db, {**je, 'lines': lines}, ACTOR, REASON,
                                              source_module=REVERSE_SOURCE)
            if out.get('ok'):
                res['reversed'] += 1
                print(f"    {je.get('je_number')} → pembalik {out.get('je_number')}")
            else:
                res['failed'] += 1
                print(f"    {je.get('je_number')} GAGAL: {out.get('error') or out.get('reason')}")
    if apply:
        r = await db.production_variances.update_many(
            {'gl_retired': {'$ne': True}},
            {'$set': {'gl_retired': True, 'gl_retired_reason': REASON}})
        res['flagged_reports'] = r.modified_count
        print(f"  laporan vendor ditandai tidak dijurnal: {res['flagged_reports']}")
    return res


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
