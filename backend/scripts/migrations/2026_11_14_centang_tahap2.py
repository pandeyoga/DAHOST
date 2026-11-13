"""Migrasi 2026-11-14 (akses tahap 2, owner: "bisa semuanya, jangan setengah-setengah") — centang untuk hak yang baru
punya kotak sendiri, supaya akses hari pertama tetap sama.

KENAPA: rilis tahap 2 membuat "Input atas nama CMT" (Produksi/Maklon › Input atas nama Vendor CMT, `mod.prod_cmt_override.*`)
mengikuti centang. Dulu hak ini dikunci kode peran `core/cmt_override.OVERRIDE_ROLES`
(admin_produksi, supervisor_produksi, ppic + peran super). Tanpa migrasi ini, peran berkode tersebut kehilangan haknya.
Perubahan lain tahap 2 (penjaga di kode ikut menerima centang, endpoint Kirim CMT dan lainnya masuk katalog) tidak
membutuhkan centang baru.

Hanya MENAMBAH centang. Dicatat di riwayat peran (rahaza_audit_logs, entity_type='role'). Idempoten. Hanya mencetak
nama peran, jumlah akun, dan kunci. Bawaan PRATINJAU; tulis dengan --apply (backup DB dulu).

Runbook (VPS):
    docker exec dahost-backend-1 python scripts/migrations/2026_11_14_centang_tahap2.py
    docker exec dahost-backend-1 python scripts/migrations/2026_11_14_centang_tahap2.py --apply
"""
import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
PELAKU = {'id': 'migrasi-2026-11-14-centang-tahap2', 'name': 'Skrip centang akses tahap 2', 'role': 'sistem'}
# Disalin dari core/cmt_override.OVERRIDE_ROLES sebelum rilis ini (tanpa peran super, yang selalu boleh).
OVERRIDE_ROLES_LAMA = ("admin_produksi", "supervisor_produksi", "ppic")
OVERRIDE_KEYS = tuple(f"mod.prod_cmt_override.{a}" for a in ("view", "create", "edit", "delete", "export"))


def usulan(nama_peran: str, keys: list) -> list:
    """Kunci baru untuk satu peran (fungsi murni)."""
    if str(nama_peran or "").lower() in OVERRIDE_ROLES_LAMA:
        return sorted(set(OVERRIDE_KEYS) - set(keys or []))
    return []


async def run(db, apply: bool = False) -> dict:
    from routes.shared import SUPER_ROLES
    print(f"[centang-tahap2] {'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    akun = {}
    for u in await db.users.find({'is_active': {'$ne': False}}, {'_id': 0, 'role': 1}).to_list(20000):
        k = str(u.get('role') or '').lower()
        akun[k] = akun.get(k, 0) + 1
    out = {'peran_berubah': 0, 'centang_baru': 0}
    now = datetime.now(timezone.utc)
    for r in await db.roles.find({}, {'_id': 0}).sort('name', 1).to_list(1000):
        nama = str(r.get('name') or '')
        if nama.lower() in SUPER_ROLES:
            continue
        keys = [x['permission_key'] async for x in db.role_permissions.find({'role_id': r['id']}, {'_id': 0})
                if x.get('permission_key')]
        baru = usulan(nama, keys)
        if not baru:
            continue
        print(f"- {nama} ({akun.get(nama.lower(), 0)} akun aktif): +{len(baru)} centang Input atas nama Vendor CMT")
        out['peran_berubah'] += 1
        out['centang_baru'] += len(baru)
        if apply:
            await db.role_permissions.insert_many([
                {'id': str(uuid.uuid4()), 'role_id': r['id'], 'permission_key': k, 'created_at': now} for k in baru])
            from routes.rahaza_audit import log_audit
            await log_audit(db, entity_type='role', entity_id=r['id'], action='update',
                            before={'name': nama, 'permissions': sorted(keys)},
                            after={'name': nama, 'permissions': sorted(set(keys) | set(baru))}, user=PELAKU)
    print(f"Ringkas: {out['peran_berubah']} peran · {out['centang_baru']} centang baru"
          + (" (DITULIS)" if apply else " (belum ditulis)"))
    return out


async def main(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    await run(AsyncIOMotorClient(MONGO_URL)[DB_NAME], apply)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    sys.exit(asyncio.run(main(ap.parse_args().apply)))
