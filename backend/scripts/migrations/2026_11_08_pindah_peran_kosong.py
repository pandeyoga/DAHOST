"""Migrasi 2026-11-08 (keputusan pemilik, audit peran & akses) — pindahkan pengguna dari peran bawaan yang KOSONG
ke peran yang sudah diatur pemilik.

KENAPA: audit data produksi menemukan akun aktif berperan `operator_cuting` — peran bawaan sistem tanpa portal dan
tanpa izin (dibuat ulang otomatis oleh `auth._seed_default_roles`), sehingga orangnya tidak bisa membuka apa pun.
Peran yang memang diatur pemilik untuk pekerjaan yang sama adalah "Operator Cuting" (portal Cutting/Gudang, 23 izin).

Yang dilakukan (per pasangan di PINDAH):
  * akun yang perannya (tanpa beda huruf) sama dengan peran asal → `role` = nama peran tujuan, `role_id` = id-nya;
  * hanya bila peran ASAL benar-benar kosong (tanpa portal & tanpa izin) dan peran TUJUAN ada serta punya portal —
    selain itu dilewati dan disebut alasannya.
Sifat: idempoten. Hanya mencetak nama peran dan jumlah akun (tanpa nama/email orang).
Bawaan PRATINJAU; tulis dengan --apply (backup DB dulu).

Runbook (VPS):
    docker exec dahost-backend-1 python scripts/migrations/2026_11_08_pindah_peran_kosong.py
    docker exec dahost-backend-1 python scripts/migrations/2026_11_08_pindah_peran_kosong.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

# peran asal (kode bawaan kosong) → peran tujuan (diatur pemilik)
PINDAH = {
    'operator_cuting': 'Operator Cuting',
}


def _sama(a, b) -> bool:
    return str(a or '').strip().lower() == str(b or '').strip().lower()


async def _peran(db, nama):
    rows = await db.roles.find({}, {'_id': 0, 'id': 1, 'name': 1, 'portals': 1}).to_list(1000)
    persis = [r for r in rows if r.get('name') == nama]
    return (persis or [r for r in rows if _sama(r.get('name'), nama)] or [None])[0]


async def run(db, apply: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[pindah-peran-kosong] {mode}")
    now = datetime.now(timezone.utc).isoformat()
    out = {'dipindah': 0, 'pasangan': {}}
    pengguna = await db.users.find({}, {'_id': 0, 'id': 1, 'role': 1, 'is_active': 1}).to_list(10000)
    for asal, tujuan in PINDAH.items():
        p_asal, p_tujuan = await _peran(db, asal), await _peran(db, tujuan)
        akun = [u for u in pengguna if _sama(u.get('role'), asal)]
        aktif = sum(1 for u in akun if u.get('is_active') is not False)
        alasan = None
        if not p_tujuan:
            alasan = f'peran tujuan "{tujuan}" tidak ada'
        elif not (p_tujuan.get('portals') or []):
            alasan = f'peran tujuan "{tujuan}" tidak punya portal'
        elif p_asal and ((p_asal.get('portals') or []) or await db.role_permissions.count_documents({'role_id': p_asal.get('id')})):
            alasan = f'peran asal "{asal}" tidak kosong (punya portal/izin) — tidak disentuh'
        dipindah = 0
        if not alasan and apply:
            for u in akun:
                res = await db.users.update_one({'id': u['id']}, {'$set': {
                    'role': p_tujuan['name'], 'role_id': p_tujuan.get('id'), 'updated_at': now}})
                dipindah += res.modified_count
        out['pasangan'][asal] = {'akun': len(akun), 'aktif': aktif, 'alasan_lewat': alasan, 'dipindah': dipindah}
        out['dipindah'] += dipindah
        print(f"  {asal} → {tujuan}: {len(akun)} akun ({aktif} aktif)"
              + (f" · DILEWATI: {alasan}" if alasan else '')
              + (f" · dipindah: {dipindah}" if apply and not alasan else ''))
    print(f"  total akun dipindah: {out['dipindah']}")
    return out


async def main(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    await run(db, apply)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    sys.exit(asyncio.run(main(ap.parse_args().apply)))
