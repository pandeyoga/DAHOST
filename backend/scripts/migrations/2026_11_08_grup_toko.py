"""Migrasi 2026-11-08 (keputusan pemilik, uji ketajaman toko-a) — rapikan GRUP toko ke daftar tetap.

KENAPA: form Kelola Akun memakai pilihan tetap untuk "Grup" (Official Store · Reseller · Distributor ·
Lainnya = `official_store` · `reseller` · `distributor` · `other`), tetapi data lama berisi teks bebas
(huruf besar/kecil, spasi, sinonim). Akibatnya saringan grup tidak menemukan toko itu dan form menampilkan
pilihan kosong. Pemilik memutuskan: daftar tetap DIPERTAHANKAN; nilai lama dipetakan ke daftar itu.

Aturan pemetaan (`petakan_grup`):
  * Nilai yang sudah benar → tidak disentuh.
  * Huruf besar/kecil, spasi, garis bawah, tanda hubung diabaikan ("Official Store", "official-store").
  * Sinonim yang jelas (`SINONIM`), mis. "toko resmi"/"mall" → official_store, "agen"/"dropship" → reseller,
    "grosir" → distributor, "lain-lain" → other.
  * Kosong / null / "-" → `other` (bawaan server saat toko dibuat).
  * Nilai lain (mis. nama merek) TIDAK DIPETAKAN dan TETAP seperti semula — pratinjau mendaftarnya supaya
    pemilik bisa memilih grupnya sendiri lewat Kelola Akun.

Sifat: idempoten. Bawaan PRATINJAU (mencetak tabel nilai lama → grup baru + jumlah toko, dan daftar nilai yang
tidak bisa dipetakan); tulis dengan --apply (backup DB dulu: `mongodump --collection marketing_platform_accounts`).
Hanya field `group` (dan `updated_at`) yang ditulis.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_grup_toko.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_grup_toko.py --apply
"""
import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
BATAS_TOKO = 5000

# Daftar tetap = pilihan form Kelola Akun (`frontend/src/components/erp/AccountManagementModule.jsx` › GROUPS).
GRUP_TETAP = {'official_store': 'Official Store', 'reseller': 'Reseller', 'distributor': 'Distributor',
              'other': 'Lainnya'}

# Kunci = bentuk ternormalisasi (huruf kecil, tanpa spasi/garis bawah/tanda hubung).
SINONIM = {
    # official_store
    'officialstore': 'official_store', 'official': 'official_store', 'officialshop': 'official_store',
    'tokoresmi': 'official_store', 'resmi': 'official_store', 'mall': 'official_store',
    'shopeemall': 'official_store', 'tokopediaofficial': 'official_store',
    # reseller
    'reseller': 'reseller', 'reseler': 'reseller', 'resseller': 'reseller', 'agen': 'reseller',
    'agent': 'reseller', 'dropship': 'reseller', 'dropshipper': 'reseller',
    # distributor
    'distributor': 'distributor', 'distributer': 'distributor', 'distribusi': 'distributor',
    'grosir': 'distributor', 'wholesale': 'distributor',
    # other
    'other': 'other', 'others': 'other', 'lainnya': 'other', 'lain': 'other', 'lainlain': 'other',
}
# Label tampilan juga dikenali ("Official Store", "Lainnya", …).
for _kode, _label in GRUP_TETAP.items():
    SINONIM.setdefault(re.sub(r'[\s_\-]+', '', _label.lower()), _kode)
    SINONIM.setdefault(re.sub(r'[\s_\-]+', '', _kode), _kode)


def _norm(raw) -> str:
    return re.sub(r'[\s_\-\.]+', '', str(raw).strip().lower())


def petakan_grup(raw):
    """Nilai grup lama → kode daftar tetap, atau `None` bila tidak bisa dipetakan (nilai dibiarkan)."""
    if raw is None or (isinstance(raw, str) and raw.strip() in ('', '-', '—')):
        return 'other'
    if not isinstance(raw, str):
        return None
    if raw in GRUP_TETAP:
        return raw
    return SINONIM.get(_norm(raw))


def _tampil(raw) -> str:
    return '(kosong)' if raw is None or (isinstance(raw, str) and not raw.strip()) else repr(raw)


async def run(db, apply: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[grup-toko] {mode}")
    out = {'toko': 0, 'sudah_benar': 0, 'dipetakan': 0, 'tidak_dipetakan': 0, 'ditulis': 0,
           'pemetaan': {}, 'nilai_tidak_dipetakan': {}}
    accounts = await db.marketing_platform_accounts.find(
        {}, {'_id': 0, 'id': 1, 'group': 1}).to_list(BATAS_TOKO)
    per_nilai: dict = {}
    for acc in accounts:
        if not acc.get('id'):
            continue
        out['toko'] += 1
        raw = acc.get('group')
        per_nilai.setdefault(raw if isinstance(raw, str) or raw is None else str(raw), []).append(acc['id'])

    now = datetime.now(timezone.utc)
    for raw in sorted(per_nilai, key=lambda v: (v is None, str(v))):
        ids = per_nilai[raw]
        target = petakan_grup(raw)
        if target is None:
            out['tidak_dipetakan'] += len(ids)
            out['nilai_tidak_dipetakan'][str(raw)] = len(ids)
            continue
        if raw == target:
            out['sudah_benar'] += len(ids)
            continue
        out['dipetakan'] += len(ids)
        out['pemetaan'][_tampil(raw)] = {'ke': target, 'toko': len(ids)}
        print(f"  {_tampil(raw)} → {target} ({GRUP_TETAP[target]}): {len(ids)} toko")
        if apply:
            r = await db.marketing_platform_accounts.update_many(
                {'id': {'$in': ids}}, {'$set': {'group': target, 'updated_at': now}})
            out['ditulis'] += getattr(r, 'modified_count', len(ids))
    if out['nilai_tidak_dipetakan']:
        print("  Tidak bisa dipetakan (DIBIARKAN; pilih grupnya lewat Kelola Akun):")
        for raw, n in out['nilai_tidak_dipetakan'].items():
            print(f"    {raw!r}: {n} toko")
    print(f"  toko: {out['toko']} · sudah benar: {out['sudah_benar']} · dipetakan: {out['dipetakan']} · "
          f"tidak dipetakan: {out['tidak_dipetakan']}" + (f" · ditulis: {out['ditulis']}" if apply else ''))
    return out


async def main(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    await run(db, apply)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.apply)))
