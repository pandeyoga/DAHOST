"""Migrasi 2026-11-08 (Asisten AI, audit §3.C #11) — cek data KEMBAR sebelum indeks unik impor dipasang.

KENAPA: kunci dedup Wizard Impor Marketing hanya diperiksa dengan membaca dulu lalu menyisipkan. Tanpa indeks
unik, dua sesi impor yang berjalan bersamaan bisa sama-sama menyisipkan baris yang sama (iklan, retur, sesi
live, KPI…) dan angkanya terhitung dua kali. `migrations/ensure_indexes.py` kini memasang indeks unik per jenis
impor (`core.marketing_import_indexes`). MongoDB MENOLAK membuat indeks unik selama masih ada data kembar —
migrasi ini menunjukkan kembaran itu LEBIH DULU, supaya pemasangan indeks di VPS tidak gagal diam-diam.

Yang dilakukan:
  * PRATINJAU (bawaan): untuk setiap indeks unik (umum + per jenis impor) — apakah sudah terpasang, berapa
    kelompok kunci kembar, dan contoh id dokumennya. Tidak menulis apa pun.
  * --apply: memasang indeks yang BELUM ada dan TIDAK terhalang data kembar. Indeks yang masih punya kembaran
    dilewati dan disebut; kembaran TIDAK dihapus otomatis (pilih mana yang benar lewat layar/rollback impor).

Sifat: idempoten (aman diulang). Hanya mencetak kunci & id dokumen, tanpa data pembeli.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_cek_duplikat_impor_marketing.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_cek_duplikat_impor_marketing.py --apply
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


async def run(db, apply: bool = False) -> dict:
    from core import marketing_import_indexes as mii
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk memasang indeks)'
    print(f"[cek-duplikat-impor-marketing] {mode}")
    out = {'indeks': [], 'terpasang_baru': 0, 'terhalang': 0, 'sudah_ada': 0}
    ensure = None
    if apply:
        from migrations.ensure_indexes import _ensure_unique_index as ensure
    for spec in mii.all_specs():
        ada = await mii.index_exists(db, spec)
        dup = await mii.find_duplicates(db, spec)
        row = {'koleksi': spec['collection'], 'indeks': spec['name'], 'label': spec['label'],
               'sudah_ada': ada, **dup, 'dipasang': False}
        if ada:
            out['sudah_ada'] += 1
        elif dup['kelompok_kembar']:
            out['terhalang'] += 1
        elif apply:
            row['dipasang'] = bool(await ensure(db, spec['collection'], spec['keys'],
                                                name=spec['name'], partial=spec['partial']))
            out['terpasang_baru'] += int(row['dipasang'])
        status = ('sudah terpasang' if ada else
                  f"TERHALANG {dup['kelompok_kembar']} kelompok kembar ({dup['dokumen_berlebih']} dokumen berlebih)"
                  if dup['kelompok_kembar'] else
                  ('dipasang' if row['dipasang'] else ('belum terpasang — siap dipasang' if not apply
                                                        else 'GAGAL dipasang (lihat log)')))
        print(f"  {spec['collection']}.{spec['name']}: {status}")
        for c in dup['contoh']:
            print(f"      kunci {c['kunci']} × {c['jumlah']}  id: {', '.join(c['id'])}")
        if ada and dup['kelompok_kembar']:
            print("      (indeks sudah ada tetapi data kembar ditemukan — periksa partialFilter indeks lama)")
        out['indeks'].append(row)
    print(f"  ringkas: {out['sudah_ada']} sudah ada · {out['terhalang']} terhalang data kembar · "
          f"{out['terpasang_baru']} dipasang sekarang")
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
