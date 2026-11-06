"""Migrasi 2026-11-06 (Tahap 2, paket payroll) — data pendukung aturan gaji baru.

1. Kalender kerja: dokumen `rahaza_payroll_settings {key: "work_calendar"}` dibuat dengan 6 hari kerja per
   minggu bila belum ada (keputusan owner; bisa diubah di Pengaturan Payroll).
2. Tanggal masuk kerja: payroll memprorata gaji dari `join_date`. Karyawan tanpa `join_date` dianggap bekerja
   penuh sepanjang periode — DILAPORKAN jumlahnya supaya HR melengkapinya di Data Karyawan. `joined_at`
   SENGAJA tidak disalin (nilainya = waktu data dibuat di sistem, bukan tanggal masuk kerja).
3. Satu sumber gaji: field lama `base_rate`/`wage_scheme` di Data Karyawan dibandingkan dengan Profil Gaji
   aktif — DILAPORKAN jumlah yang berbeda (tidak diubah; Profil Gaji yang dipakai payroll).
4. Run gaji "hantu" dari tombol lama di Dasbor Penggajian (`POST /api/payroll/automation/trigger`: draf tanpa
   slip, field `period.from`) → ditandai `cancelled` dengan alasan (tanpa hapus) supaya tidak tampil sebagai
   run draf. Run yang punya slip TIDAK disentuh.

Sifat: idempoten, tanpa hapus, hanya mencetak jumlah (tanpa data pribadi). Bawaan PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_payroll_tahap2.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_payroll_tahap2.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
GHOST_REASON = 'run hantu dari Dasbor Penggajian lama — tanpa slip (migrasi 2026-11-06)'

SCHEME_ALIASES = {'bulanan': 'monthly', 'mingguan': 'weekly', 'borongan_jam': 'hourly', 'borongan_pcs': 'pcs'}


# ── perencanaan (murni, tanpa DB — diuji unit) ───────────────────────────────
def salary_field_differs(emp: dict, profile: dict | None) -> bool:
    """Field gaji lama di Data Karyawan berbeda dengan Profil Gaji aktif (atau ada tarif tanpa profil)."""
    legacy_rate = float(emp.get('base_rate') or 0)
    legacy_scheme = SCHEME_ALIASES.get(str(emp.get('wage_scheme') or ''), str(emp.get('wage_scheme') or ''))
    if profile is None:
        return legacy_rate > 0
    if legacy_rate and abs(legacy_rate - float(profile.get('base_rate') or 0)) > 0.5:
        return True
    return bool(legacy_scheme) and legacy_scheme != profile.get('pay_scheme') and legacy_rate > 0


def is_ghost_run(run: dict) -> bool:
    return (run.get('status') == 'draft' and not run.get('period_from')
            and isinstance(run.get('period'), dict) and run.get('trigger_mode') == 'manual_automation')


# ── jalankan ─────────────────────────────────────────────────────────────────
async def run(apply: bool, db=None) -> dict:
    if db is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f"[payroll-tahap2] DB={DB_NAME} · {'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    now = datetime.now(timezone.utc)
    out = {}

    # 1. kalender kerja
    cal = await db.rahaza_payroll_settings.find_one({'key': 'work_calendar'}, {'_id': 0})
    out['work_calendar_created'] = 0
    if cal:
        print(f"  1. kalender kerja sudah ada: {cal.get('work_days_per_week')} hari/minggu")
    else:
        print('  1. kalender kerja belum ada → ' + ('dibuat 6 hari/minggu' if apply else 'akan dibuat 6 hari/minggu'))
        if apply:
            await db.rahaza_payroll_settings.insert_one({
                'key': 'work_calendar', 'work_days_per_week': 6, 'updated_at': now,
                'updated_by': 'system', 'updated_by_name': 'migrasi 2026-11-06'})
        out['work_calendar_created'] = 1

    # 2. tanggal masuk kerja
    emps = await db.rahaza_employees.find({}, {'_id': 0, 'id': 1, 'active': 1, 'join_date': 1, 'joined_at': 1,
                                               'base_rate': 1, 'wage_scheme': 1}).to_list(10000)
    active = [e for e in emps if e.get('active') is not False]
    missing = [e for e in active if not str(e.get('join_date') or '').strip()]
    out['employees_active'] = len(active)
    out['employees_missing_join_date'] = len(missing)
    out['employees_missing_join_date_with_joined_at'] = sum(1 for e in missing if e.get('joined_at'))
    print(f"  2. karyawan aktif tanpa tanggal masuk kerja: {len(missing)} dari {len(active)} "
          f"({out['employees_missing_join_date_with_joined_at']} hanya punya waktu input sistem) — lengkapi di Data Karyawan")

    # 3. field gaji lama vs Profil Gaji
    profiles = {p['employee_id']: p for p in await db.rahaza_payroll_profiles.find(
        {'active': True}, {'_id': 0, 'employee_id': 1, 'base_rate': 1, 'pay_scheme': 1}).to_list(10000)}
    differ = [e for e in emps if salary_field_differs(e, profiles.get(e.get('id')))]
    out['salary_field_differences'] = len(differ)
    out['salary_field_without_profile'] = sum(1 for e in differ if e.get('id') not in profiles)
    print(f"  3. field gaji di Data Karyawan berbeda dengan Profil Gaji: {len(differ)} "
          f"(tanpa profil gaji: {out['salary_field_without_profile']}) — payroll memakai Profil Gaji")

    # 4. run hantu
    drafts = await db.rahaza_payroll_runs.find({'status': 'draft'}, {'_id': 0}).to_list(2000)
    ghosts = []
    for r in drafts:
        if is_ghost_run(r) and not await db.rahaza_payslips.count_documents({'run_id': r['id']}):
            ghosts.append(r)
    out['ghost_runs'] = len(ghosts)
    print(f"  4. run gaji hantu (draf tanpa slip dari dasbor lama): {len(ghosts)} → "
          + ('ditandai dibatalkan' if apply else 'akan ditandai dibatalkan'))
    if apply:
        for r in ghosts:
            await db.rahaza_payroll_runs.update_one({'id': r['id'], 'status': 'draft'}, {'$set': {
                'status': 'cancelled', 'cancel_reason': GHOST_REASON, 'cancelled_at': now,
                'cancelled_by_name': 'migrasi 2026-11-06', 'updated_at': now}})
    print('  selesai.')
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    asyncio.run(run(ap.parse_args().apply))
    sys.exit(0)
