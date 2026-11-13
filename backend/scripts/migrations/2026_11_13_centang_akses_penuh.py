"""Migrasi 2026-11-13 (owner: "role dan akses ... bisa semuanya, jangan setengah-setengah") — isi centang setiap peran
SAMA dengan aksesnya sekarang, supaya centang bisa menjadi satu-satunya penentu tanpa ada staf yang berubah hari pertama.

KENAPA: mulai rilis ini
  * gerbang modul berlaku untuk SEMUA modul (dulu portal tanpa satu pun centang `mod.*` memakai aturan lama);
  * tambah/ubah/hapus toko mengikuti centang Marketing › Kelola Akun (dulu dikunci kode untuk SPV/manajemen);
  * kotak centang baru: Keuangan › Pembayaran & Pencairan Uang (cairkan kasbon/klaim/pinjaman/uang muka, bayar tagihan
    pemasok/CMT, batal transfer bank) dan Gudang › Opname Stok Gudang (dulu ikut modul Stok);
  * beberapa aksi kini dihitung "Setujui": bayar gaji, QC penerimaan, batal jurnal, perbaikan massal kopling BOM.
Tanpa migrasi ini, peran yang dulu lolos lewat aturan lama atau daftar peran di kode akan tertolak.

Yang dilakukan per peran (bukan superadmin/admin/owner, bukan peran eksternal):
  A. portal yang bisa dibuka tetapi belum punya centang `mod.*` → centang setara izin lama (`module_catalog.
     suggest_from_legacy`, aturan tombol "Konversi izin lama" di Manajemen Role, mode ketat: aksi tanpa padanan
     izin lama mengikuti izin portal yang dipegang — Lihat/Kelola/Setujui);
  B. Kelola Akun › Tambah/Ubah/Hapus → peran yang dulu lolos `can_manage_stores` (kode peran SPV/manajemen
     marketing atau izin marketing.target.set);
  C. Pembayaran & Pencairan Uang › Setujui → peran Keuangan (kode peran) atau izin finance.manage / fin.payment.manage;
  D. aksi yang kini "Setujui" → peran yang dulu bisa melakukannya (centang lama + penjaga di kode);
  E. Opname Stok Gudang → salinan centang Stok untuk opname; "Setujui" bagi peran yang dulu bisa menyetujui opname,
     KECUALI peran di OPNAME_SETUJUI_DITUNDA (keputusan owner 13 Nov: Koordinator Packing "nanti dulu").
Hanya MENAMBAH centang (tidak ada yang dicabut). Izin lama tetap disimpan. Setiap peran yang berubah dicatat di
riwayat peran (rahaza_audit_logs, entity_type='role'). Idempoten. Hanya mencetak nama peran, jumlah akun, dan kunci.
Bawaan PRATINJAU; tulis dengan --apply (backup DB dulu). Aman dijalankan SEBELUM kode baru terpasang (bagian yang
butuh katalog baru dilewati dan disebut) lalu SEKALI LAGI sesudahnya.

Runbook (VPS):
    docker exec dahost-backend-1 python scripts/migrations/2026_11_13_centang_akses_penuh.py
    docker exec dahost-backend-1 python scripts/migrations/2026_11_13_centang_akses_penuh.py --apply
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
PELAKU = {'id': 'migrasi-2026-11-13-centang', 'name': 'Skrip centang akses penuh', 'role': 'sistem'}

# Penjaga di kode SEBELUM rilis ini (disalin di sini supaya migrasi tetap benar walau kodenya berubah).
TARGET_WRITER_ROLES = ("owner", "admin", "superadmin", "spv_marketing", "manager_marketing", "manager")
MGMT_ROLES = ("owner", "manager")
FINANCE_ROLES = ("accounting", "staff_keuangan", "manager_keuangan", "finance", "finance_manager", "accountant")
PAYROLL_HR_ROLES = ("hr", "manager")
BOM_REPAIR_ROLES = ("manager_produksi", "admin_produksi", "supervisor_produksi", "supervisor", "rnd_staff")
WAREHOUSE_APPROVE_ROLES = ("admin_gudang", "spv_packing", "admin_aksesoris", "supervisor", "manager")
# Keputusan owner 13 Nov 2026: hak menyetujui opname barang jadi untuk peran ini ditunda ("nanti dulu").
OPNAME_SETUJUI_DITUNDA = ("koordinator packing",)


def _boleh_lama(nama: str, izin: set, kode: tuple, kunci: tuple) -> bool:
    return nama in kode or "*" in izin or bool(izin & set(kunci))


def usulan(nama_peran: str, portals: list, keys: list) -> tuple[list, list]:
    """(kunci baru, catatan) untuk satu peran — fungsi murni, diuji tanpa Mongo."""
    from data.module_catalog import (
        GRANULAR_PORTALS, MODULE_BY_ID, expand_permissions, granular_portals, suggest_from_legacy, view_portals,
    )
    from routes.shared import ALL_ROLE_PORTALS, effective_portals
    nama = str(nama_peran or "").lower()
    punya = set(keys or [])
    izin = set(expand_permissions(punya))
    baru, catatan = set(), []
    # A. portal terbuka tanpa centang mod.* → setara izin lama
    terbuka = (set(effective_portals(nama, portals)) | view_portals(punya)) - set(ALL_ROLE_PORTALS) - {"sysadmin"}
    gran = granular_portals(punya)
    for portal in sorted(terbuka & set(GRANULAR_PORTALS) - gran):
        tambah = set(suggest_from_legacy(izin, portal, True, strict=True)) - punya
        if tambah:
            baru |= tambah
            catatan.append(f"A portal {portal}: {len(tambah)} centang setara izin lama")
    semua = punya | baru

    def ada(mid):
        return mid in MODULE_BY_ID

    def centang_lama(mid, aksi):
        # Dulu gerbang modul hanya aktif di portal yang sudah punya centang; di portal lain penjaga kode saja.
        return f"mod.{mid}.{aksi}" in punya or MODULE_BY_ID[mid]["portal"] not in gran
    # B. tambah/ubah/hapus toko → Kelola Akun
    if _boleh_lama(nama, izin, TARGET_WRITER_ROLES + MGMT_ROLES, ("marketing.target.set",)):
        baru |= {f"mod.mkt_accounts.{a}" for a in ("view", "create", "edit", "delete")}
        catatan.append("B Kelola Akun: dulu boleh menambah/mengubah toko")
    # C. Pembayaran & Pencairan Uang
    if ada("fin_pencairan") and _boleh_lama(nama, izin, FINANCE_ROLES, ("finance.manage", "fin.payment.manage")):
        baru.add("mod.fin_pencairan.approve")
        catatan.append("C Pembayaran & Pencairan: dulu boleh membayar/mencairkan")
    # D. aksi yang kini "Setujui"
    if _boleh_lama(nama, izin, PAYROLL_HR_ROLES, ("hr.manage", "payroll.manage")) and centang_lama("hr_payroll", "create") \
            and ("hr" in terbuka or "mod.hr_payroll.create" in semua):
        baru.add("mod.hr_payroll.approve")
        catatan.append("D bayar gaji → Penggajian › Setujui")
    if _boleh_lama(nama, izin, WAREHOUSE_APPROVE_ROLES, ("warehouse.approve", "inventory.manage", "warehouse.manage")) \
            and centang_lama("wh_receiving", "create") and ("warehouse" in terbuka or "mod.wh_receiving.create" in semua):
        baru.add("mod.wh_receiving.approve")
        catatan.append("D QC penerimaan → Penerimaan › Setujui")
    if _boleh_lama(nama, izin, FINANCE_ROLES, ("finance.manage",)) and centang_lama("fin_journal", "create") \
            and ("finance" in terbuka or "mod.fin_journal.create" in semua):
        baru.add("mod.fin_journal.approve")
        catatan.append("D batal jurnal → Jurnal › Setujui")
    if nama in BOM_REPAIR_ROLES and centang_lama("prod_master_product", "create") \
            and ({"production", "rnd"} & terbuka or "mod.prod_master_product.create" in semua):
        baru.add("mod.prod_master_product.approve")
        catatan.append("D perbaikan massal BOM → Master Produk › Setujui")
    # E. Opname Stok Gudang (dulu ikut modul Stok: path /api/wms/opname3)
    if ada("wh_opname") and ("warehouse" in terbuka or "warehouse" in gran):
        if "warehouse" in gran:  # portal sudah diatur per modul → salin centang Stok untuk opname
            for a in ("view", "create", "edit", "delete", "export"):
                if f"mod.wh_stock.{a}" in punya:
                    baru.add(f"mod.wh_opname.{a}")
        # "Setujui" opname dulu: izin lama wh.opname.approve/manage atau warehouse.approve (Setujui Stok menyiratkan
        # keduanya), dan gerbang modul meloloskan (portal belum diatur, atau centang Setujui Stok).
        izin_lama = izin | ({"wh.opname.approve", "warehouse.approve"} if "mod.wh_stock.approve" in punya else set())
        dulu_setuju = bool(izin_lama & {"wh.opname.approve", "wh.opname.manage", "warehouse.approve"}) \
            and ("warehouse" not in gran or "mod.wh_stock.approve" in punya)
        if dulu_setuju and nama not in OPNAME_SETUJUI_DITUNDA:
            baru |= {"mod.wh_opname.view", "mod.wh_opname.approve"}
            catatan.append("E Opname Stok Gudang › Setujui: dulu boleh menyetujui opname")
        elif dulu_setuju:
            catatan.append("E Opname › Setujui TIDAK diberikan (keputusan owner 13 Nov: nanti dulu)")
    baru = {k for k in baru if k.split(".")[1] in MODULE_BY_ID} - punya
    return sorted(baru), catatan


async def run(db, apply: bool = False) -> dict:
    from core.authz import EXTERNAL_ROLES
    from routes.shared import SUPER_ROLES
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[centang-akses-penuh] {mode}")
    akun = {}
    for u in await db.users.find({'is_active': {'$ne': False}}, {'_id': 0, 'role': 1}).to_list(20000):
        k = str(u.get('role') or '').lower()
        akun[k] = akun.get(k, 0) + 1
    out = {'peran_berubah': 0, 'centang_baru': 0, 'rincian': {}}
    now = datetime.now(timezone.utc)
    for r in await db.roles.find({}, {'_id': 0}).sort('name', 1).to_list(1000):
        nama = str(r.get('name') or '')
        if nama.lower() in SUPER_ROLES or nama.lower() in EXTERNAL_ROLES:
            continue
        keys = [x['permission_key'] async for x in db.role_permissions.find({'role_id': r['id']}, {'_id': 0})
                if x.get('permission_key')]
        baru, catatan = usulan(nama, r.get('portals') or [], keys)
        if not baru and not catatan:
            continue
        n_akun = akun.get(nama.lower(), 0)
        print(f"\n- {nama} ({n_akun} akun aktif): +{len(baru)} centang")
        for c in catatan:
            print(f"    {c}")
        for k in baru:
            print(f"    + {k}")
        out['rincian'][nama] = baru
        if baru:
            out['peran_berubah'] += 1
            out['centang_baru'] += len(baru)
        if apply and baru:
            await db.role_permissions.insert_many([
                {'id': str(uuid.uuid4()), 'role_id': r['id'], 'permission_key': k, 'created_at': now} for k in baru])
            from routes.rahaza_audit import log_audit
            await log_audit(db, entity_type='role', entity_id=r['id'], action='update',
                            before={'name': nama, 'permissions': sorted(keys)},
                            after={'name': nama, 'permissions': sorted(set(keys) | set(baru))}, user=PELAKU)
    print(f"\nRingkas: {out['peran_berubah']} peran · {out['centang_baru']} centang baru"
          + (" (DITULIS)" if apply else " (belum ditulis)"))
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
