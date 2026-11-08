"""Migrasi 2026-11-08 (keputusan pemilik) — rapikan GRUP toko ke daftar MEREK.

KENAPA: form Kelola Akun memakai pilihan tetap untuk "Grup". Versi pertama daftar itu berisi jenis toko
(Official Store · Reseller · Distributor), padahal data yang diisi staf berisi nama merek ("Rayona", "Daluna",
"Outfit Boutique"). Pemilik memutuskan (8 Nov 2026): Grup = MEREK — Rayona · Daluna · Outfit Boutique · Lainnya
(`rayona` · `daluna` · `outfit_boutique` · `other`, daftar di `core/grup_toko.py`). Skrip ini mengubah nilai lama
ke kode daftar itu supaya saringan grup menemukan tokonya dan form menampilkan pilihannya.

Aturan pemetaan (`petakan_grup(nilai, nama_toko)`):
  * Nilai yang sudah berupa kode daftar → tidak disentuh.
  * Nama merek / label dengan beda huruf-spasi-tanda hubung ("Rayona", "outfit boutique") → kode mereknya.
  * Kosong / "-" / jenis toko versi lama ("official_store", "Reseller", "grosir", …) → merek yang disebut di NAMA
    toko bila tepat satu ("Shopee Outfit Boutique" → outfit_boutique); selain itu `other` (Lainnya).
  * Teks lain yang tidak dikenal → DIBIARKAN; pratinjau mendaftarnya supaya pemilik memilih grupnya lewat
    Kelola Akun.

Sifat: idempoten. Bawaan PRATINJAU (nilai lama → grup baru + jumlah toko, dan nilai yang tidak bisa dipetakan);
tulis dengan --apply (backup DB dulu). Hanya field `group` (dan `updated_at`) yang ditulis.

Runbook (VPS):
    docker exec dahost-backend-1 python scripts/migrations/2026_11_08_grup_toko.py
    docker exec dahost-backend-1 python scripts/migrations/2026_11_08_grup_toko.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.grup_toko import GRUP_BAWAAN, GRUP_TOKO, kode_grup, norm, tebak_merek  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
BATAS_TOKO = 5000

# Daftar tetap = pilihan form Kelola Akun (`frontend/src/components/erp/AccountManagementModule.jsx` › GROUPS).
GRUP_TETAP = GRUP_TOKO

# Jenis toko versi pertama daftar (bukan merek) — bentuk ternormalisasi.
JENIS_LAMA = {
    'officialstore', 'official', 'officialshop', 'tokoresmi', 'resmi', 'mall', 'shopeemall', 'tokopediaofficial',
    'reseller', 'reseler', 'resseller', 'agen', 'agent', 'dropship', 'dropshipper',
    'distributor', 'distributer', 'distribusi', 'grosir', 'wholesale',
}


def _kosong(raw) -> bool:
    return raw is None or (isinstance(raw, str) and raw.strip() in ('', '-', '—'))


def petakan_grup(raw, nama_toko=None):
    """Nilai grup lama → kode daftar merek, atau `None` bila tidak bisa dipetakan (nilai dibiarkan)."""
    kode = kode_grup(raw)
    if kode:
        return kode
    if _kosong(raw) or (isinstance(raw, str) and norm(raw) in JENIS_LAMA):
        return tebak_merek(nama_toko) or GRUP_BAWAAN
    return None


def _tampil(raw) -> str:
    return '(kosong)' if _kosong(raw) else repr(raw)


async def run(db, apply: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[grup-toko] {mode}")
    out = {'toko': 0, 'sudah_benar': 0, 'dipetakan': 0, 'tidak_dipetakan': 0, 'ditulis': 0,
           'pemetaan': {}, 'nilai_tidak_dipetakan': {}}
    accounts = await db.marketing_platform_accounts.find(
        {}, {'_id': 0, 'id': 1, 'group': 1, 'account_name': 1}).to_list(BATAS_TOKO)
    per_target: dict = {}   # (nilai lama, kode baru) → [id]
    for acc in accounts:
        if not acc.get('id'):
            continue
        out['toko'] += 1
        raw = acc.get('group')
        target = petakan_grup(raw, acc.get('account_name'))
        if target is None:
            out['tidak_dipetakan'] += 1
            out['nilai_tidak_dipetakan'][str(raw)] = out['nilai_tidak_dipetakan'].get(str(raw), 0) + 1
        elif raw == target:
            out['sudah_benar'] += 1
        else:
            per_target.setdefault((_tampil(raw), target), []).append(acc['id'])

    now = datetime.now(timezone.utc)
    for (lama, target), ids in sorted(per_target.items()):
        out['dipetakan'] += len(ids)
        out['pemetaan'][f'{lama} → {target}'] = len(ids)
        print(f"  {lama} → {target} ({GRUP_TETAP[target]}): {len(ids)} toko")
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
