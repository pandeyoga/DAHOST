"""Migrasi 2026-11-10 (keputusan owner, akses per peran) — rapikan peran kembar di Manajemen Role.

KENAPA: sampai 10 Nov setiap start backend membuat ulang peran bawaan yang namanya tidak ditemukan PERSIS
(`auth._seed_default_roles`). Peran yang diganti nama owner (mis. "admin_aksesoris" → "Admin Aksesoris") muncul
lagi sebagai peran kosong dengan keterangan yang sama, jadi di layar tampak kembar. Ditambah satu peran buatan tangan
yang salah eja ("operator cutting" kembar dari "Operator Cuting"). Mulai rilis ini peran bawaan hanya diisi pada
instalasi baru, jadi peran yang dihapus skrip ini TIDAK muncul lagi. Jalankan SESUDAH kode baru terpasang.

Yang dilakukan:
  * hapus peran kembar di HAPUS (selalu) dan HAPUS_BAWAAN_KOSONG (hanya dengan --termasuk-bawaan-kosong);
    syarat setiap peran: 0 akun (nama tanpa beda huruf atau role_id), tanpa portal, tanpa izin, tanpa menu
    disembunyikan — selain itu DILEWATI dan disebut alasannya;
  * ganti kode peran di GANTI_NAMA (hanya dengan --ganti-nama); akun pemakainya ikut dipindah (users.role/role_id),
    sama seperti tombol Simpan di Manajemen Role;
  * cetak dampak aturan baru "portal dicentang = final": peran yang portal bawaannya tidak ikut terbuka lagi.
Setiap perubahan dicatat di riwayat peran (rahaza_audit_logs, entity_type='role').
Sifat: idempoten. Hanya mencetak nama peran dan jumlah akun (tanpa nama/email orang).
Bawaan PRATINJAU; tulis dengan --apply (backup DB dulu).

Runbook (VPS):
    docker exec dahost-backend-1 python scripts/migrations/2026_11_10_rapikan_peran_kembar.py
    docker exec dahost-backend-1 python scripts/migrations/2026_11_10_rapikan_peran_kembar.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

# peran kembar → peran yang dipakai (hanya untuk keterangan)
HAPUS = {
    'operator cutting': 'Operator Cuting',
    'admin_aksesoris': 'Admin Aksesoris',
}
# peran bawaan yang dibuat ulang otomatis 16 Okt sesudah owner mengganti nama/menghapus aslinya
HAPUS_BAWAAN_KOSONG = {
    'admin_gudang': 'PIC CMT/Adm. Gudang',
    'accounting': 'Finance & Purchase',
    'admin_maklon': 'Admin Monitoring',
    'cs_staff': 'Customer Service',
    'marketing_kol': '(dihapus owner 30 Sep)',
}
GANTI_NAMA = {
    'Operator Cuting': 'Operator Cutting',
}
PELAKU = {'id': 'migrasi-2026-11-10-peran', 'name': 'Skrip rapikan peran kembar', 'role': 'sistem'}


def _sama(a, b) -> bool:
    return str(a or '').strip().lower() == str(b or '').strip().lower()


async def _akun(db, peran: dict) -> int:
    rows = await db.users.find({}, {'_id': 0, 'role': 1, 'role_id': 1}).to_list(20000)
    return sum(1 for u in rows if _sama(u.get('role'), peran.get('name')) or (peran.get('id') and u.get('role_id') == peran['id']))


async def _izin(db, peran: dict) -> list:
    rows = await db.role_permissions.find({'role_id': peran.get('id')}, {'_id': 0, 'permission_key': 1}).to_list(5000)
    return sorted({r.get('permission_key') for r in rows if r.get('permission_key')})


async def _hapus(db, nama: str, kembar_dari: str, apply: bool, out: dict):
    peran = await db.roles.find_one({'name': nama}, {'_id': 0})
    if not peran:
        print(f"  - {nama}: tidak ada (sudah bersih)")
        return
    akun, izin = await _akun(db, peran), await _izin(db, peran)
    alasan = ('masih dipakai %d akun' % akun if akun else
              'punya portal' if peran.get('portals') else
              'punya %d izin' % len(izin) if izin else
              'punya menu disembunyikan' if peran.get('hidden_modules') else
              'peran sistem' if peran.get('is_system') else None)
    if alasan:
        out['dilewati'].append(nama)
        print(f"  - {nama} (kembar {kembar_dari}): DILEWATI — {alasan}")
        return
    print(f"  - {nama} (kembar {kembar_dari}): 0 akun, tanpa portal/izin → " + ('DIHAPUS' if apply else 'akan dihapus'))
    out['hapus'].append(nama)
    if apply:
        from routes.rahaza_audit import log_audit
        await db.role_permissions.delete_many({'role_id': peran.get('id')})
        await db.roles.delete_one({'id': peran.get('id'), 'name': nama})
        await log_audit(db, entity_type='role', entity_id=peran.get('id'), action='delete',
                        before={**peran, 'permissions': []}, after=None, user=PELAKU)


async def _ganti_nama(db, lama: str, baru: str, apply: bool, akan_dihapus: set, out: dict):
    from core.reference_dedup import ref_key
    peran = await db.roles.find_one({'name': lama}, {'_id': 0})
    if not peran:
        print(f"  - {lama} → {baru}: peran '{lama}' tidak ada" + (' (sudah diganti)' if await db.roles.find_one({'name': baru}) else ''))
        return
    semua = await db.roles.find({}, {'_id': 0, 'id': 1, 'name': 1}).to_list(1000)
    bentrok = [r['name'] for r in semua if r.get('id') != peran.get('id') and r.get('name') not in akan_dihapus
               and (r.get('name') == baru or ref_key(r.get('name')) == ref_key(baru))]
    if bentrok:
        out['dilewati'].append(lama)
        print(f"  - {lama} → {baru}: DILEWATI — nama setara sudah dipakai {bentrok}")
        return
    akun = await _akun(db, peran)
    print(f"  - {lama} → {baru}: {akun} akun ikut pindah → " + ('DIGANTI' if apply else 'akan diganti'))
    out['ganti'].append(lama)
    if apply:
        from routes.rahaza_audit import log_audit
        now = datetime.now(timezone.utc).isoformat()
        await db.roles.update_one({'id': peran['id']}, {'$set': {'name': baru, 'updated_at': now}})
        rows = await db.users.find({}, {'_id': 0, 'id': 1, 'role': 1, 'role_id': 1}).to_list(20000)
        for u in rows:
            if _sama(u.get('role'), lama) or u.get('role_id') == peran['id']:
                await db.users.update_one({'id': u['id']}, {'$set': {'role': baru, 'role_id': peran['id'], 'updated_at': now}})
        await log_audit(db, entity_type='role', entity_id=peran['id'], action='update',
                        before={'name': lama}, after={'name': baru}, user=PELAKU)


async def _dampak(db):
    """Peran yang portalnya sudah dicentang tetapi bawaan kodenya memberi portal lain (kini tidak ikut terbuka)."""
    from routes.shared import SUPER_ROLES, default_portals
    print("\nDampak aturan baru 'portal dicentang = final' (portal bawaan yang tidak ikut terbuka lagi):")
    ada = False
    for r in await db.roles.find({}, {'_id': 0, 'id': 1, 'name': 1, 'portals': 1}).sort('name', 1).to_list(1000):
        if not r.get('portals') or str(r.get('name') or '').lower() in SUPER_ROLES:
            continue
        lepas = [p for p in default_portals(r.get('name')) if p not in r['portals']]
        if lepas:
            ada = True
            print(f"  - {r['name']}: {await _akun(db, r)} akun · tidak ikut lagi: {', '.join(lepas)}")
    if not ada:
        print("  (tidak ada)")


async def run(db, apply: bool = False, termasuk_bawaan_kosong: bool = False, ganti_nama: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[rapikan-peran-kembar] {mode}")
    out = {'hapus': [], 'ganti': [], 'dilewati': []}
    target = dict(HAPUS)
    if termasuk_bawaan_kosong:
        target.update(HAPUS_BAWAAN_KOSONG)
    print("Hapus peran kembar:")
    for nama, kembar_dari in target.items():
        await _hapus(db, nama, kembar_dari, apply, out)
    if not termasuk_bawaan_kosong:
        print(f"  (peran bawaan kosong lain tidak disentuh: {', '.join(HAPUS_BAWAAN_KOSONG)} — pakai --termasuk-bawaan-kosong)")
    if ganti_nama:
        print("Ganti kode peran:")
        for lama, baru in GANTI_NAMA.items():
            await _ganti_nama(db, lama, baru, apply, set(out['hapus']), out)
    await _dampak(db)
    print(f"\nRingkas: hapus {len(out['hapus'])} · ganti nama {len(out['ganti'])} · dilewati {len(out['dilewati'])}")
    return out


async def main(args) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    await run(db, args.apply, args.termasuk_bawaan_kosong, args.ganti_nama)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    ap.add_argument('--termasuk-bawaan-kosong', action='store_true',
                    help='ikut hapus peran bawaan kosong yang dibuat ulang otomatis 16 Okt')
    ap.add_argument('--ganti-nama', action='store_true', help="ganti kode 'Operator Cuting' → 'Operator Cutting'")
    sys.exit(asyncio.run(main(ap.parse_args())))
