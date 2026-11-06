"""Migrasi 2026-11-06 (Tahap 2 paket absen) — rapikan absensi & saldo cuti yang ditulis aturan lama.

KENAPA: sampai 6 Nov 2026 setiap cuti/izin/sakit yang disetujui ditulis ke absensi sebagai "cuti" di SETIAP
hari kalender (Minggu & libur ikut, sakit/izin jadi cuti, setengah hari jadi sehari penuh), dan saldo dipotong
hari KALENDER. Aturan baru (core.leave_engine): hanya HARI KERJA, status = jenis pengajuan, saldo = hari kerja.

Per cuti disetujui (yang belum ditandai `migrasi_absen_2026_11_06`):
  1. Record absensi cuti itu di hari BUKAN hari kerja → status 'libur' (tanda cuti dilepas, jejak di
     `migrated_from`). Tidak dihapus.
  2. Record di hari kerja dengan status 'cuti' padahal pengajuannya sakit/izin → status sakit/izin.
  3. Kolom kontrak payroll yang belum ada diisi: leave_kind, half_day, paid_leave (dari tanda dibayar jenis
     cutinya — keputusan bayar per pengajuan belum ada waktu itu; `pay_decision` pengajuan diisi sama).
  4. Saldo: pengajuan yang disetujui lewat persetujuan UTAMA dulu memotong `duration_days` (hari kalender) →
     selisih dengan hari kerja dikembalikan ke saldo tahun itu, `balance_deducted_days` = hari kerja.
     Pengajuan yang disetujui lewat persetujuan massal / Kotak Masuk SDM dulu TIDAK memotong saldo sama sekali →
     hanya DILAPORKAN (keputusan manual HR), tidak dipotong otomatis.
  Yang TIDAK diubah, hanya dilaporkan: record yang tanggalnya sudah masuk gaji final, record hari libur yang
  berisi absen sungguhan (jam masuk/pulang), dan hari kerja cuti yang tidak punya record sama sekali.

Sifat: idempoten, tanpa hapus, hanya mencetak hitungan (tanpa nama/data pribadi).
Bawaan PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_absen_cuti.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_absen_cuti.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import workdays  # noqa: E402
from core.leave_engine import is_half_day, leave_kind  # noqa: E402
from utils.leave_types import is_unpaid  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
MARK = 'migrasi_absen_2026_11_06'


def _has_own_data(r: dict) -> bool:
    return bool(r.get('clock_in') or r.get('clock_out') or r.get('sessions') or r.get('photo_selfie_url')
                or r.get('fingerprint'))


def approved_via_main(leave: dict) -> bool:
    """Persetujuan UTAMA lama menulis `approval_step_N` dan memotong saldo; massal/kotak masuk tidak."""
    for k in ('approval_step_2', 'approval_step_1'):
        st = leave.get(k)
        if isinstance(st, dict) and st.get('action') == 'approved':
            return True
    return False


# ── perencanaan (murni, tanpa DB — diuji unit) ───────────────────────────────
def plan_leave(leave: dict, lt: dict, rows: list, working: set, locked: set) -> dict:
    """Rencana perubahan untuk SATU cuti disetujui.

    `working` = tanggal hari kerja dalam rentang cuti; `locked` = tanggal yang sudah masuk gaji final.
    Return {"rows": [{id, set}], "leave_set": {...}, "balance_restore": hari, counts…}."""
    kind = leave_kind(leave, lt)
    half = is_half_day(leave)
    paid = not is_unpaid(lt)
    out = {'rows': [], 'leave_set': {}, 'balance_restore': 0.0, 'to_libur': 0, 'to_kind': 0, 'filled': 0,
           'skip_locked': 0, 'skip_own_data': 0, 'missing_days': 0, 'balance_manual': 0}
    seen = set()
    for r in rows:
        d = str(r.get('date') or '')[:10]
        seen.add(d)
        upd = {}
        if d not in working:
            if d in locked:
                out['skip_locked'] += 1
                continue
            if _has_own_data(r):
                out['skip_own_data'] += 1
                continue
            upd = {'status': 'libur', 'leave_request_id': None, 'leave_kind': None, 'paid_leave': None,
                   'half_day': False,
                   'migrated_from': {'status': r.get('status'), 'leave_request_id': r.get('leave_request_id'),
                                     'by': MARK}}
            out['to_libur'] += 1
        else:
            if d in locked:
                if (r.get('status') or '').lower() == 'cuti' and kind != 'cuti':
                    out['skip_locked'] += 1
                continue
            if (r.get('status') or '').lower() == 'cuti' and kind != 'cuti':
                upd['status'] = kind
                upd['migrated_from'] = {'status': r.get('status'), 'by': MARK}
                out['to_kind'] += 1
            fill = {}
            if r.get('leave_kind') is None:
                fill['leave_kind'] = kind
            if r.get('paid_leave') is None:
                fill['paid_leave'] = paid
            if half and not r.get('half_day'):
                fill['half_day'] = True
            if fill:
                out['filled'] += 1
                upd.update(fill)
        if upd:
            out['rows'].append({'id': r['id'], 'set': upd})
    out['missing_days'] = len([d for d in working if d not in seen])

    weight = 0.5 if half else 1.0
    work_days = len(working) * weight
    if leave.get('balance_deducted_days') is None:
        if approved_via_main(leave):
            old = float(leave.get('duration_days') or 0)
            out['balance_restore'] = round(max(old - work_days, 0.0), 2)
            out['leave_set']['balance_deducted_days'] = min(old, work_days)
        else:
            out['balance_manual'] = 1
    if not leave.get('pay_decision'):
        out['leave_set']['pay_decision'] = 'paid' if paid else 'unpaid'
    if not leave.get('leave_kind'):
        out['leave_set']['leave_kind'] = kind
    out['leave_set']['duration_working_days'] = work_days
    return out


# ── jalankan ─────────────────────────────────────────────────────────────────
async def _locked_dates(db, employee_id: str, days: list) -> set:
    from core.attendance_rules import attendance_lock
    return {d for d in days if await attendance_lock(db, employee_id, d)}


async def run(apply: bool, db=None) -> dict:
    if db is None:
        from motor.motor_asyncio import AsyncIOMotorClient
        db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f"[absen-cuti] DB={DB_NAME} · {'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    cal = await workdays.get_work_calendar(db)
    leaves = await db.rahaza_leave_requests.find(
        {'status': 'approved', MARK: {'$exists': False}}, {'_id': 0}).to_list(20000)
    totals = {'leaves': len(leaves), 'to_libur': 0, 'to_kind': 0, 'filled': 0, 'skip_locked': 0,
              'skip_own_data': 0, 'missing_days': 0, 'balance_restore_days': 0.0, 'balance_restore_leaves': 0,
              'balance_manual': 0, 'invalid': 0}
    lt_cache: dict = {}
    now = datetime.now(timezone.utc)
    for lv in leaves:
        try:
            d_from = date.fromisoformat(str(lv['from_date'])[:10])
            d_to = date.fromisoformat(str(lv.get('to_date') or lv['from_date'])[:10])
        except (KeyError, ValueError):
            totals['invalid'] += 1
            continue
        lt_id = lv.get('leave_type_id')
        if lt_id not in lt_cache:
            lt_cache[lt_id] = await db.rahaza_leave_types.find_one({'id': lt_id}, {'_id': 0}) or {}
        hol = await workdays.holiday_set(db, d_from, d_to)
        working = {d.isoformat() for d in workdays.working_days_between(d_from, d_to, cal['off_weekdays'], hol)}
        rows = await db.rahaza_attendance_events.find(
            {'employee_id': lv.get('employee_id'), 'leave_request_id': lv['id']}, {'_id': 0}).to_list(400)
        locked = await _locked_dates(db, lv.get('employee_id'), sorted({str(r.get('date'))[:10] for r in rows}))
        plan = plan_leave(lv, lt_cache[lt_id], rows, working, locked)
        for k in ('to_libur', 'to_kind', 'filled', 'skip_locked', 'skip_own_data', 'missing_days', 'balance_manual'):
            totals[k] += plan[k]
        if plan['balance_restore']:
            totals['balance_restore_days'] += plan['balance_restore']
            totals['balance_restore_leaves'] += 1
        if not apply:
            continue
        for r in plan['rows']:
            await db.rahaza_attendance_events.update_one(
                {'id': r['id']}, {'$set': {**r['set'], 'updated_at': now, 'updated_by_name': MARK}})
        if plan['balance_restore']:
            bal = await db.rahaza_leave_balances.find_one(
                {'employee_id': lv.get('employee_id'), 'leave_type_id': lt_id, 'year': d_from.year}, {'_id': 0})
            if bal:
                await db.rahaza_leave_balances.update_one({'id': bal['id']}, {'$set': {
                    'used': max(0.0, float(bal.get('used') or 0) - plan['balance_restore']), 'updated_at': now}})
        await db.rahaza_leave_requests.update_one({'id': lv['id']}, {'$set': {
            **plan['leave_set'],
            MARK: {'at': now, 'balance_restored_days': plan['balance_restore'],
                   'rows_changed': len(plan['rows']), 'balance_manual': bool(plan['balance_manual'])}}})
    totals['balance_restore_days'] = round(totals['balance_restore_days'], 2)
    verb = 'diubah' if apply else 'akan diubah'
    print(f"  cuti disetujui diperiksa: {totals['leaves']} (tanggal tidak valid: {totals['invalid']})")
    print(f"  record hari libur/Minggu → 'libur' ({verb}): {totals['to_libur']}")
    print(f"  record 'cuti' → sakit/izin sesuai pengajuan ({verb}): {totals['to_kind']}")
    print(f"  record dilengkapi kolom kontrak payroll ({verb}): {totals['filled']}")
    print(f"  saldo dikembalikan ({verb}): {totals['balance_restore_days']:g} hari dari {totals['balance_restore_leaves']} pengajuan")
    print("  DILAPORKAN, tidak diubah:")
    print(f"    · record di tanggal yang sudah masuk gaji final: {totals['skip_locked']}")
    print(f"    · record hari libur yang berisi jam absen sungguhan: {totals['skip_own_data']}")
    print(f"    · hari kerja cuti tanpa record absensi: {totals['missing_days']}")
    print(f"    · pengajuan disetujui lewat persetujuan massal/kotak masuk (saldo belum pernah dipotong): "
          f"{totals['balance_manual']}")
    return totals


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    asyncio.run(run(ap.parse_args().apply))
    sys.exit(0)
