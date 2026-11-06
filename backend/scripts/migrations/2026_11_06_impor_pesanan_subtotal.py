"""Migrasi 2026-11-06 (Tahap 2) — pemetaan kolom impor pesanan Shopee yang salah.

KENAPA: kamus sinonim impor "Pesanan Marketplace (ekspor Seller Center)" dulu memetakan
  · "Harga Setelah Diskon" (harga SATUAN)  → Subtotal Setelah Diskon (dasar omzet), dan
  · "Subtotal Pesanan" (subtotal setelah diskon) → Subtotal Sebelum Diskon.
Akibatnya omzet pesanan berisi lebih dari satu barang terhitung harga satu barang
(~15% lebih rendah pada berkas contoh). Kamusnya sudah dibetulkan
(`core.marketing_import_schema.RETIRED_MAPPINGS`), tetapi pemetaan yang SUDAH TERSIMPAN
masih memuat pasangan lama:
  1. ingatan susunan kolom (`marketing_data_import_formats`) — dipakai otomatis tiap impor;
  2. draf impor yang belum disimpan (`marketing_data_import_sessions`, status mapping/ready).

Yang dilakukan:
  · ingatan & DRAF: pasangan lama diganti hasil kamus yang benar (draf membaca ulang berkasnya
    saat dibuka, jadi pratinjau langsung benar). Hanya dengan --apply.
  · sesi yang SUDAH DISIMPAN (committed): TIDAK diubah — hanya dilaporkan (jumlah pesanan per
    sesi). Jalan perbaikannya: impor ulang berkas yang sama ke toko yang sama dengan pilihan
    "Perbarui yang lama"; omzet & rekap harian pesanan itu dihitung ulang.

Sifat: idempoten, tanpa hapus, hanya mencetak jumlah (tanpa data pembeli). Bawaan PRATINJAU.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_impor_pesanan_subtotal.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_impor_pesanan_subtotal.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import marketing_import_engine as eng  # noqa: E402
from core.marketing_import_schema import (  # noqa: E402
    RETIRED_MAPPINGS, get_source_type, is_retired_mapping,
)

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
SESSIONS = 'marketing_data_import_sessions'
FORMATS = 'marketing_data_import_formats'
ORDERS = 'marketing_orders'
DRAFT_STATUSES = ('mapping', 'ready')
NOTE = 'dipetakan ulang 2026-11-06 (kamus kolom diperbaiki)'


# ── perencanaan (murni, tanpa DB — diuji unit) ───────────────────────────────
def has_retired(source_type: str, mapping: list) -> bool:
    return any(m.get('field') and is_retired_mapping(source_type, eng._norm_header(m.get('column')), m['field'])
               for m in (mapping or []))


def fix_mapping(source_type: str, mapping: list, headers: list = None) -> tuple:
    """→ (pemetaan baru, kolom yang dipetakan ulang). Kolom lain tidak disentuh.

    Kolom berpasangan lama dipetakan ulang ke hasil kamus yang benar (`auto_map`), kecuali
    field itu sudah dipakai kolom lain — kolomnya lalu dibiarkan tidak dipakai (staf memilih).
    """
    st = get_source_type(source_type)
    cols = headers or [m.get('column') for m in mapping or [] if m.get('column')]
    auto = {a['column']: a for a in eng.auto_map(cols, st)}
    used = {m.get('field') for m in mapping or [] if m.get('field')
            and not is_retired_mapping(source_type, eng._norm_header(m.get('column')), m['field'])}
    out, changed = [], []
    for m in mapping or []:
        col, fld = m.get('column'), m.get('field')
        if not (fld and is_retired_mapping(source_type, eng._norm_header(col), fld)):
            out.append(m)
            continue
        a = auto.get(col) or {}
        new_f = a.get('field') if a.get('method') in ('exact', 'synonym', 'fuzzy') else None
        if new_f in used:
            new_f = None
        if new_f:
            used.add(new_f)
        out.append({**m, 'field': new_f,
                    'field_label': st.field(new_f).label if new_f else None,
                    'method': a.get('method') if new_f else 'none',
                    'score': a.get('score', 0.0) if new_f else 0.0,
                    'value_map': {}, 'note': NOTE})
        changed.append(col)
    return out, changed


# ── jalankan ─────────────────────────────────────────────────────────────────
async def run(apply: bool, db=None) -> dict:
    if db is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f"[impor-subtotal] DB={DB_NAME} · "
          f"{'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    types = list(RETIRED_MAPPINGS)
    now = datetime.now(timezone.utc)
    out = {'formats': 0, 'drafts': 0, 'committed': 0, 'committed_orders': 0}

    # 1) ingatan susunan kolom
    async for f in db[FORMATS].find({'source_type': {'$in': types}}, {'_id': 0}):
        if not has_retired(f['source_type'], f.get('mapping')):
            continue
        new, changed = fix_mapping(f['source_type'], f.get('mapping') or [], f.get('headers'))
        out['formats'] += 1
        print(f"  - ingatan pemetaan {str(f.get('fingerprint'))[:10]}… ({f['source_type']}): "
              f"{len(changed)} kolom dipetakan ulang")
        if apply:
            await db[FORMATS].update_one(
                {'source_type': f['source_type'], 'fingerprint': f.get('fingerprint')},
                {'$set': {'mapping': new, 'mapping_fixed_at': now, 'mapping_fix_note': NOTE}})

    # 2) draf yang belum disimpan
    async for s in db[SESSIONS].find({'source_type': {'$in': types},
                                       'status': {'$in': list(DRAFT_STATUSES)}}, {'_id': 0}):
        if not has_retired(s['source_type'], s.get('mapping')):
            continue
        new, changed = fix_mapping(s['source_type'], s.get('mapping') or [], s.get('headers'))
        report = eng.mapping_report(new, get_source_type(s['source_type']))
        out['drafts'] += 1
        print(f"  - draf {s.get('id')} (toko {s.get('account_code') or '-'}): "
              f"{len(changed)} kolom dipetakan ulang")
        if apply:
            await db[SESSIONS].update_one({'id': s['id']}, {'$set': {
                'mapping': new, 'mapping_report': report,
                'status': 'ready' if report['ready'] else 'mapping',
                'mapping_fixed_at': now, 'mapping_fix_note': NOTE, 'updated_at': now}})

    # 3) sesi yang sudah disimpan — dilaporkan saja
    async for s in db[SESSIONS].find({'source_type': {'$in': types}, 'status': 'committed',
                                       'rolled_back_at': None}, {'_id': 0}):
        if not has_retired(s['source_type'], s.get('mapping')):
            continue
        n = await db[ORDERS].count_documents({'_import_session_id': s.get('id')})
        out['committed'] += 1
        out['committed_orders'] += n
        when = s.get('committed_at')
        when = when.date().isoformat() if isinstance(when, datetime) else str(when or '-')[:10]
        print(f"  ! sesi tersimpan {s.get('id')} (toko {s.get('account_code') or '-'}, {when}): "
              f"{n} pesanan — TIDAK diubah")

    print(f"\n  ringkas: ingatan pemetaan {'dibetulkan' if apply else 'akan dibetulkan'}: {out['formats']} · "
          f"draf {'dibetulkan' if apply else 'akan dibetulkan'}: {out['drafts']} · "
          f"sesi tersimpan perlu impor ulang: {out['committed']} ({out['committed_orders']} pesanan)")
    if out['committed']:
        print("  Jalan perbaikan sesi tersimpan: impor ulang berkas yang sama ke toko yang sama, "
              "pilih “Perbarui yang lama”. Omzet & rekap harian pesanan itu dihitung ulang.")
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    asyncio.run(run(ap.parse_args().apply))
    sys.exit(0)
