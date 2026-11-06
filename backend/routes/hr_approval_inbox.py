"""
CV. Dewi Aditya — HR Approval Inbox (Aggregator)
Phase 26 — P2 Workflow Consolidation #2

Unified inbox for managers/HR to approve multiple types of HR requests in one place:
- Cuti (Leave) — rahaza_leave_requests (status=pending_approval)
- Lembur (Overtime) — rahaza_overtime_requests (status=pending)
- Penyesuaian Gaji (Salary Adjustment) — rahaza_salary_adjustments (status in
  draft/pending_manager/pending_hr)
- Resignasi — rahaza_employees (resignation flow with status=submitted)

Endpoints:
- GET  /api/hr/inbox                        — aggregate all pending approvals
- GET  /api/hr/inbox/summary                — count summary per category
- POST /api/hr/inbox/{type}/{id}/approve    — generic approve
- POST /api/hr/inbox/{type}/{id}/reject     — generic reject

Implementation note: this is an AGGREGATOR. Approve/reject endpoints delegate
to existing per-module endpoints to keep business logic centralized.
"""
# ruff: noqa: E741
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from database import get_db
from auth import require_auth, serialize_doc, log_activity
from utils.employee_identity import job_title_of
from core import doc_lock
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/hr/inbox', tags=['HR-Inbox'])


# ─────────────────────────────────────────────────────────────────────────────
# Allowed request types & validation
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_TYPES = ('leave', 'overtime', 'salary_adjustment', 'resignation', 'attendance', 'expense_claim', 'travel_request',
                 'attendance_correction')
# Tahap 2 (2026-11-06): cuti tingkat 1 (atasan) DAN tingkat 2 (HR) tampil di kotak masuk; dulu hanya tingkat 1
# dan persetujuannya melompati tingkat 2.
LEAVE_PENDING = ['pending_approval', 'pending_hr_approval']


def _to_iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


async def _enrich_employee(db, emp_id: str) -> Dict[str, Any]:
    """Fetch employee snapshot (name, code, dept)."""
    if not emp_id:
        return {}
    emp = await db.rahaza_employees.find_one({'id': emp_id}, {'_id': 0})
    if not emp:
        return {}
    return {
        'employee_id': emp.get('id'),
        'employee_code': emp.get('employee_code'),
        'employee_name': emp.get('name'),
        'employee_dept': emp.get('department'),
        'employee_position': job_title_of(emp),  # 2026-11-06 (pola P3)
        'manager_id': emp.get('manager_id'),
    }


def _require_approver_role(user: dict):
    # 2026-08-06 — gerbang izin terpusat (routes.shared.can_act, fallback aman).
    from routes.shared import can_act as _can_act
    if not _can_act(user, 'hr.approve', 'hr.manage',
                    legacy_roles=('hr', 'manager', 'hr_manager')):
        raise HTTPException(403, 'Akses ditolak: butuh izin approval SDM (hr.approve).')


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — build inbox items from raw docs
# ─────────────────────────────────────────────────────────────────────────────
async def _fetch_leaves(db, type_filter: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Pending leave requests."""
    if type_filter and type_filter != 'leave':
        return []
    rows = await db.rahaza_leave_requests.find(
        {'status': {'$in': LEAVE_PENDING}}, {'_id': 0}
    ).sort('created_at', -1).limit(limit).to_list(length=limit)

    if not rows:
        return []
    from core.leave_engine import leave_kind, suggest_pay_decision
    from utils.leave_types import is_paid

    emp_ids = list({r.get('employee_id') for r in rows if r.get('employee_id')})
    lt_ids  = list({r.get('leave_type_id') for r in rows if r.get('leave_type_id')})
    emps = await db.rahaza_employees.find({'id': {'$in': emp_ids}}, {'_id': 0}).to_list(length=500) if emp_ids else []
    lts  = await db.rahaza_leave_types.find({'id': {'$in': lt_ids}}, {'_id': 0}).to_list(length=500) if lt_ids else []
    emp_map = {e['id']: e for e in emps}
    lt_map  = {l['id']: l for l in lts}

    items = []
    for r in rows:
        e = emp_map.get(r.get('employee_id')) or {}
        lt = lt_map.get(r.get('leave_type_id')) or {}
        # Leave duration field varies — newer docs use duration_days / duration_working_days
        total_days = (
            r.get('duration_working_days')
            or r.get('duration_days')
            or r.get('total_days')
            or 0
        )
        items.append({
            'id': r['id'],
            'type': 'leave',
            'type_label': 'Cuti / Izin',
            'created_at': _to_iso(r.get('created_at')),
            'submitted_at': _to_iso(r.get('submitted_at') or r.get('created_at')),
            'requester_id': r.get('employee_id'),
            'requester_name': e.get('name'),
            'requester_code': e.get('employee_code'),
            'requester_dept': e.get('department'),
            'title': f"{lt.get('name', 'Cuti')} — {total_days} hari",
            'period': f"{r.get('from_date', '')} → {r.get('to_date', '')}",
            'reason': r.get('reason', ''),
            'amount': None,
            'meta': {
                'leave_type': lt.get('name'),
                'leave_type_code': lt.get('code'),
                'total_days': total_days,
                'is_paid': is_paid(lt),
                'request_type': leave_kind(r, lt),
                'leave_kind': leave_kind(r, lt),
                'approval_level': f"{r.get('current_approval_level') or 1}/{r.get('approval_level_required') or 1}",
                'pay_decision_suggestion': suggest_pay_decision(r, lt),
                'from_date': r.get('from_date'),
                'to_date': r.get('to_date'),
                'half_day': r.get('half_day') or r.get('is_half_day'),
                'attachment_url': r.get('attachment_url'),
            },
            'raw': serialize_doc(r),
        })
    return items


async def _fetch_overtime(db, type_filter: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Pending overtime requests."""
    if type_filter and type_filter != 'overtime':
        return []
    rows = await db.rahaza_overtime_requests.find(
        {'status': 'pending'}, {'_id': 0}
    ).sort('created_at', -1).limit(limit).to_list(length=limit)
    if not rows:
        return []
    emp_ids = list({r.get('employee_id') for r in rows if r.get('employee_id')})
    emps = await db.rahaza_employees.find({'id': {'$in': emp_ids}}, {'_id': 0}).to_list(length=500) if emp_ids else []
    emp_map = {e['id']: e for e in emps}
    items = []
    for r in rows:
        e = emp_map.get(r.get('employee_id')) or {}
        items.append({
            'id': r['id'],
            'type': 'overtime',
            'type_label': 'Lembur',
            'created_at': _to_iso(r.get('created_at')),
            'submitted_at': _to_iso(r.get('created_at')),
            'requester_id': r.get('employee_id'),
            'requester_name': e.get('name'),
            'requester_code': e.get('employee_code'),
            'requester_dept': e.get('department'),
            'title': f"Lembur {r.get('hours', 0)} jam — {r.get('date', '')}",
            'period': f"{r.get('start_time', '')} - {r.get('end_time', '')}",
            'reason': r.get('reason', ''),
            'amount': None,
            'meta': {
                'date': r.get('date'),
                'start_time': r.get('start_time'),
                'end_time': r.get('end_time'),
                'hours': r.get('hours'),
                'rate_multiplier': r.get('rate_multiplier', 1.5),
            },
            'raw': serialize_doc(r),
        })
    return items


async def _fetch_salary_adjustments(db, type_filter: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Salary adjustments pending manager/HR approval."""
    if type_filter and type_filter != 'salary_adjustment':
        return []
    rows = await db.rahaza_salary_adjustments.find(
        {'status': {'$in': ['draft', 'pending_manager', 'pending_hr']}},
        {'_id': 0}
    ).sort('created_at', -1).limit(limit).to_list(length=limit)
    if not rows:
        return []
    emp_ids = list({r.get('employee_id') for r in rows if r.get('employee_id')})
    emps = await db.rahaza_employees.find({'id': {'$in': emp_ids}}, {'_id': 0}).to_list(length=500) if emp_ids else []
    emp_map = {e['id']: e for e in emps}
    items = []
    for r in rows:
        e = emp_map.get(r.get('employee_id')) or {}
        old_v = float(r.get('old_value', 0) or 0)
        new_v = float(r.get('new_value', 0) or 0)
        delta = new_v - old_v
        items.append({
            'id': r['id'],
            'type': 'salary_adjustment',
            'type_label': 'Penyesuaian Gaji',
            'created_at': _to_iso(r.get('created_at')),
            'submitted_at': _to_iso(r.get('submitted_at') or r.get('created_at')),
            'requester_id': r.get('employee_id'),
            'requester_name': e.get('name'),
            'requester_code': e.get('employee_code'),
            'requester_dept': e.get('department'),
            'title': f"{r.get('adjustment_type', 'Penyesuaian')} — Rp {int(delta):+,}",
            'period': r.get('effective_date', ''),
            'reason': r.get('reason', ''),
            'amount': delta,
            'meta': {
                'adjustment_type': r.get('adjustment_type'),
                'old_value': old_v,
                'new_value': new_v,
                'delta': delta,
                'effective_date': r.get('effective_date'),
                'sub_status': r.get('status'),
            },
            'raw': serialize_doc(r),
        })
    return items


async def _fetch_resignations(db, type_filter: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Resignations awaiting acceptance."""
    if type_filter and type_filter != 'resignation':
        return []
    # 2026-11-06 (pola P3): pengajuan resignasi ditulis `routes.rahaza_resignation` sebagai
    # `employee_status='resigning'` + resignation_date/last_working_date/reason_for_leaving. Dulu inbox
    # menyaring `resignation_status='submitted'` (tak pernah ditulis) → resignasi tidak pernah muncul.
    from routes.rahaza_resignation import RESIGNING
    rows = await db.rahaza_employees.find(
        {'employee_status': RESIGNING}, {'_id': 0}
    ).sort('resignation_submitted_at', -1).limit(limit).to_list(length=limit)
    items = []
    for r in rows:
        eff = r.get('resignation_date') or ''
        reason = r.get('reason_for_leaving') or r.get('resignation_notes') or ''
        items.append({
            'id': r['id'],
            'type': 'resignation',
            'type_label': 'Resignasi',
            'created_at': _to_iso(r.get('resignation_submitted_at') or r.get('updated_at')),
            'submitted_at': _to_iso(r.get('resignation_submitted_at')),
            'requester_id': r.get('id'),
            'requester_name': r.get('name'),
            'requester_code': r.get('employee_code'),
            'requester_dept': r.get('department'),
            'title': f"Resignasi efektif {eff or '—'}",
            'period': eff,
            'reason': reason,
            'amount': None,
            'meta': {
                'resignation_reason': reason,
                'resignation_effective_date': eff,
                'last_working_date': r.get('last_working_date') or eff,
                'position': job_title_of(r),
            },
            'raw': serialize_doc(r),
        })
    return items


# Label metode absen untuk layar (sama dengan layar Persetujuan Absen) — bukan kode program.
METODE_ABSEN = {'selfie_geo_ai': 'Selfie', 'webauthn': 'Biometrik HP', 'device_zkteco': 'Mesin sidik jari',
                'manual': 'Manual HR'}


def _jam_wib(v) -> str:
    """'HH:MM' WIB dari instan tersimpan (datetime / string ISO); '' bila kosong/tak terbaca."""
    from utils.waktu import fmt_wib
    if isinstance(v, str) and v:
        try:
            v = datetime.fromisoformat(v.replace('Z', '+00:00'))
        except ValueError:
            return v[11:16] if len(v) >= 16 else ''
    return fmt_wib('%H:%M', v) if isinstance(v, datetime) else ''


async def _fetch_attendance(db, type_filter: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Pending attendance approvals (rahaza_attendance_events with approval_status='pending').

    Source: rahaza_auto_attendance module's queue. Items here typically come from
    auto-attendance flow (face-recognition / geo-check failed / outside-window absen).
    """
    if type_filter and type_filter != 'attendance':
        return []
    rows = await db.rahaza_attendance_events.find(
        {'approval_status': 'pending'}, {'_id': 0}
    ).sort('date', -1).limit(limit).to_list(length=limit)

    if not rows:
        return []

    emp_ids = list({r.get('employee_id') for r in rows if r.get('employee_id')})
    emps = await db.rahaza_employees.find(
        {'id': {'$in': emp_ids}}, {'_id': 0}
    ).to_list(length=500) if emp_ids else []
    emp_map = {e['id']: e for e in emps}

    items = []
    for r in rows:
        e = emp_map.get(r.get('employee_id')) or {}
        date_str = r.get('date', '')
        # 2026-11-06 (pola P3): mesin absen menulis `clock_in`/`clock_out` (instan UTC), `hours_worked`,
        # `clock_in_geo`, `notes`, `attendance_method` — dulu dibaca check_in_time/work_hours/location/
        # note/attendance_type (tak pernah ditulis) → judul "— → —" & detail kosong.
        check_in = _jam_wib(r.get('clock_in')) or r.get('check_in_time') or '—'
        check_out = _jam_wib(r.get('clock_out')) or r.get('check_out_time') or '—'
        geo = r.get('clock_in_geo') if isinstance(r.get('clock_in_geo'), dict) else {}
        items.append({
            'id': r['id'],
            'type': 'attendance',
            'type_label': 'Approval Absensi',
            'created_at': _to_iso(r.get('created_at')),
            'submitted_at': _to_iso(r.get('updated_at') or r.get('created_at')),
            'requester_id': r.get('employee_id'),
            'requester_name': e.get('name'),
            'requester_code': e.get('employee_code'),
            'requester_dept': e.get('department'),
            'title': f"Absen {date_str} — {check_in} → {check_out}",
            'period': date_str,
            'reason': r.get('notes') or r.get('approval_reason') or '',
            'amount': None,
            'meta': {
                'date': date_str,
                'check_in_time': check_in,
                'check_out_time': check_out,
                'work_hours': r.get('hours_worked'),
                'location': (f"{geo.get('lat')}, {geo.get('lng')}" if geo.get('lat') is not None else None),
                'face_match': r.get('face_match_score'),
                'geo_distance_m': r.get('geo_distance_m') if r.get('geo_distance_m') is not None else geo.get('distance_m'),
                'note': r.get('notes') or r.get('approval_reason'),
                'attendance_type': METODE_ABSEN.get(r.get('attendance_method'), r.get('attendance_method')),
                # Tahap 2: selfie disimpan di photo_selfie_url / photo_selfie_out_url (dulu dibaca nama lain → kosong)
                'photo_url': r.get('photo_selfie_url') or r.get('clock_in_photo_url') or r.get('photo_url'),
                'photo_out_url': r.get('photo_selfie_out_url'),
            },
            'raw': serialize_doc(r),
        })
    return items


async def _fetch_corrections(db, type_filter: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Pengajuan koreksi absen dari Portal Saya (Tahap 2, 2026-11-06)."""
    if type_filter and type_filter != 'attendance_correction':
        return []
    from routes.rahaza_attendance_corrections import inbox_items
    return await inbox_items(db, limit)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.get('')
async def list_inbox(
    type_filter: Optional[str] = Query(None, alias='type', description='Filter: leave|overtime|salary_adjustment|resignation|attendance'),
    limit_per_type: int = Query(50, le=200),
    user: dict = Depends(require_auth),
):
    """
    Aggregated inbox of pending HR approvals.

    Returns items from 5 sources combined and sorted desc by submission/creation time.
    Use `?type=leave` etc. to filter to one category.
    """
    _require_approver_role(user)
    if type_filter and type_filter not in ALLOWED_TYPES:
        raise HTTPException(400, f'Type harus salah satu: {list(ALLOWED_TYPES)}')

    db = get_db()
    leaves      = await _fetch_leaves(db, type_filter, limit_per_type)
    overtime    = await _fetch_overtime(db, type_filter, limit_per_type)
    salary_adj  = await _fetch_salary_adjustments(db, type_filter, limit_per_type)
    resignation = await _fetch_resignations(db, type_filter, limit_per_type)
    attendance  = await _fetch_attendance(db, type_filter, limit_per_type)
    corrections = await _fetch_corrections(db, type_filter, limit_per_type)

    all_items = leaves + overtime + salary_adj + resignation + attendance + corrections
    # Sort by submitted_at desc, fallback created_at
    all_items.sort(key=lambda x: (x.get('submitted_at') or x.get('created_at') or ''), reverse=True)

    return {
        'total': len(all_items),
        'counts': {
            'leave': len(leaves),
            'overtime': len(overtime),
            'salary_adjustment': len(salary_adj),
            'resignation': len(resignation),
            'attendance': len(attendance),
            'attendance_correction': len(corrections),
        },
        'items': all_items,
    }


@router.get('/summary')
async def inbox_summary(user: dict = Depends(require_auth)):
    """Count of pending approvals per category (for badge/notification)."""
    _require_approver_role(user)
    db = get_db()
    leaves_c = await db.rahaza_leave_requests.count_documents({'status': {'$in': LEAVE_PENDING}})
    overtime_c = await db.rahaza_overtime_requests.count_documents({'status': 'pending'})
    sal_c = await db.rahaza_salary_adjustments.count_documents(
        {'status': {'$in': ['draft', 'pending_manager', 'pending_hr']}}
    )
    from routes.rahaza_resignation import RESIGNING  # 2026-11-06 (pola P3)
    resig_c = await db.rahaza_employees.count_documents({'employee_status': RESIGNING})
    att_c = await db.rahaza_attendance_events.count_documents({'approval_status': 'pending'})
    corr_c = await db.rahaza_attendance_corrections.count_documents({'status': 'pending'})
    total = leaves_c + overtime_c + sal_c + resig_c + att_c + corr_c
    return {
        'total_pending': total,
        'leave': leaves_c,
        'overtime': overtime_c,
        'salary_adjustment': sal_c,
        'resignation': resig_c,
        'attendance': att_c,
        'attendance_correction': corr_c,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Approve / Reject — delegates to per-domain endpoints internally
# ─────────────────────────────────────────────────────────────────────────────
class ActionPayload(BaseModel):
    note: Optional[str] = None
    reason: Optional[str] = None
    pay_decision: Optional[str] = None   # cuti: 'paid' | 'unpaid' (dipilih HR, Tahap 2)


def _tolak_ajuan_sendiri(doc: dict, user: dict, what: str) -> None:
    """K25 (keputusan owner 2026-11-02): kotak masuk HR ikut aturan pengaju ≠ penyetuju
    yang sama dengan layar klaim & dinas (dulu inbox melewatinya)."""
    from routes.rahaza_payroll_shared import ensure_not_self_approval
    ensure_not_self_approval(doc, user, what=what)


async def _kabari_pemohon(req_type: str, doc: dict, *, approved: bool, note: str = '') -> None:
    """2026-11-02: keputusan lewat kotak masuk HR juga mengabari pemohon — memakai helper
    notifikasi yang sama dengan layar asal tiap jenis ajuan (dulu inbox diam)."""
    db = get_db()
    fresh = None
    try:
        if req_type == 'leave':
            from routes.rahaza_leave import notify_leave_decision
            fresh = await db.rahaza_leave_requests.find_one({'id': doc.get('id')}, {'_id': 0}) or doc
            await notify_leave_decision(db, fresh, approved=approved, reason=note)
        elif req_type == 'overtime':
            from routes.rahaza_overtime import notify_overtime_decision
            fresh = await db.rahaza_overtime_requests.find_one({'id': doc.get('id')}, {'_id': 0}) or doc
            await notify_overtime_decision(db, fresh, approved=approved, reason=note)
        elif req_type == 'expense_claim':
            from routes.employee_expense_claims import _notify_claim_decision
            fresh = await db.rahaza_expense_claims.find_one({'id': doc.get('id')}, {'_id': 0}) or doc
            await _notify_claim_decision(db, fresh, approved=approved, note=note)
        elif req_type == 'travel_request':
            from routes.employee_travel_requests import _notify_travel_decision
            fresh = await db.employee_travel_requests.find_one({'id': doc.get('id')}, {'_id': 0}) or doc
            await _notify_travel_decision(db, fresh, approved=approved, note=note,
                                          advance=float(fresh.get('cash_advance_approved') or 0))
    except Exception:  # noqa: BLE001 — notifikasi tidak boleh menggagalkan keputusan
        logger.exception('notifikasi pemohon gagal (%s %s)', req_type, doc.get('id'))


@router.post('/{req_type}/{req_id}/approve')
async def approve_request(req_type: str, req_id: str, payload: Optional[ActionPayload] = None,
                          user: dict = Depends(require_auth)):
    """Approve a pending HR request (leave/overtime/salary_adjustment/resignation)."""
    _require_approver_role(user)
    if req_type not in ALLOWED_TYPES:
        raise HTTPException(400, f'Type harus salah satu: {list(ALLOWED_TYPES)}')

    db = get_db()
    now = datetime.now(timezone.utc)
    note = (payload.note if payload else None) or ''
    actor_id = user.get('id', '')
    actor_name = user.get('name', '')

    if req_type == 'leave':
        # Tahap 2 (2026-11-06): SATU mesin persetujuan (saldo hari kerja, absensi per hari kerja, tingkat 2,
        # keputusan bayar HR). Dulu jalur ini hanya mengganti status — saldo & absensi tidak tersentuh.
        from core.leave_engine import approve_leave_request
        res = await approve_leave_request(db, req_id, user, pay_decision=(payload.pay_decision if payload else None),
                                          notes=note, via='kotak_masuk')
        await log_activity(actor_id, actor_name, 'approve', 'hr_inbox',
                           f'Approve cuti {req_id} via HR Inbox' + ('' if res['final'] else ' (tingkat 1)'))
        return {'ok': True, 'type': 'leave', 'id': req_id,
                'new_status': (res.get('leave') or {}).get('status', 'approved')}

    if req_type == 'overtime':
        # Tahap 2: fungsi persetujuan lembur yang sama dengan layar Lembur (K25: bukan lembur sendiri).
        from routes.rahaza_overtime import approve_overtime_request
        await approve_overtime_request(db, req_id, user, note)
        await log_activity(actor_id, actor_name, 'approve', 'hr_inbox',
                           f'Approve lembur {req_id} via HR Inbox')
        return {'ok': True, 'type': 'overtime', 'id': req_id, 'new_status': 'approved'}

    if req_type == 'salary_adjustment':
        adj = await db.rahaza_salary_adjustments.find_one({'id': req_id})
        if not adj:
            raise HTTPException(404, 'Salary adjustment tidak ditemukan')
        cur_status = adj.get('status')
        role = (user.get('role') or '').lower()
        # Manager → moves to pending_hr; HR/admin → moves to approved
        if cur_status in ('draft', 'pending_manager'):
            new_status = 'pending_hr' if role in ('manager',) else 'approved'
            upd = {'status': new_status, 'manager_approved_by': actor_id, 'manager_approved_at': now}
            if new_status == 'approved':
                upd['hr_approved_by'] = actor_id
                upd['hr_approved_at'] = now
        elif cur_status == 'pending_hr':
            new_status = 'approved'
            upd = {'status': new_status, 'hr_approved_by': actor_id, 'hr_approved_at': now}
        else:
            raise HTTPException(400, f'Status sudah {cur_status}, tidak bisa di-approve.')
        if note:
            upd['approval_note'] = note
        # 2026-11-06 (pola P9): status ditulis bersyarat DULU (klik ganda / tolak bersamaan → 409), baru
        # Profil Gaji diubah; bila profil gagal, status dikembalikan.
        res = await db.rahaza_salary_adjustments.update_one({'id': req_id, 'status': cur_status}, {'$set': upd})
        doc_lock.require_matched(res, 'Penyesuaian gaji ini baru saja diputuskan pengguna lain — muat ulang kotak masuk.')
        if new_status == 'approved':
            # 2026-11-06 (Tahap 2): dulu persetujuan di sini TIDAK pernah sampai ke payroll. Sekarang memakai
            # fungsi yang sama dengan layar Penyesuaian: versi tarif baru di Profil Gaji mulai effective_date.
            from routes.rahaza_payroll_profiles import apply_salary_adjustment_to_profile
            try:
                applied = await apply_salary_adjustment_to_profile(db, adj, user)
            except BaseException:
                await db.rahaza_salary_adjustments.update_one({'id': req_id, 'status': new_status},
                                                              {'$set': {'status': cur_status}})
                raise
            await db.rahaza_salary_adjustments.update_one({'id': req_id}, {'$set': {
                'applied_at': now, 'applied_effective_from': applied.get('effective_from')}})
        await log_activity(actor_id, actor_name, 'approve', 'hr_inbox',
                           f'Approve penyesuaian gaji {req_id} → {new_status} via HR Inbox')
        return {'ok': True, 'type': 'salary_adjustment', 'id': req_id, 'new_status': new_status}

    if req_type == 'resignation':
        # 2026-11-06 (pola P3): status pengajuan = `employee_status`; menyetujui di inbox = efek yang SAMA
        # dengan tombol Terima di layar Resignasi (karyawan nonaktif), bukan hanya menandai.
        from routes.rahaza_resignation import RESIGNING, accept_update
        emp = await db.rahaza_employees.find_one({'id': req_id})
        if not emp:
            raise HTTPException(404, 'Employee tidak ditemukan')
        if emp.get('employee_status') != RESIGNING:
            raise HTTPException(400, f"Status resignasi saat ini: {emp.get('employee_status') or '-'}")
        res = await db.rahaza_employees.update_one(
            {'id': req_id, 'employee_status': RESIGNING},
            {'$set': {**accept_update(actor_id), 'resignation_status': 'accepted',
                      'resignation_acceptance_note': note}}
        )
        if not res.matched_count:
            raise HTTPException(409, 'Resignasi ini baru saja diproses pengguna lain.')
        await log_activity(actor_id, actor_name, 'approve', 'hr_inbox',
                           f'Accept resignasi karyawan {req_id} via HR Inbox')
        return {'ok': True, 'type': 'resignation', 'id': req_id, 'new_status': 'accepted'}

    if req_type == 'attendance':
        ev = await db.rahaza_attendance_events.find_one({'id': req_id})
        if not ev:
            raise HTTPException(404, 'Record absen tidak ditemukan')
        if ev.get('approval_status') != 'pending':
            raise HTTPException(400, f"Status absen saat ini: {ev.get('approval_status')}. Harus pending.")
        # Tahap 2: keputusan selfie lewat fungsi yang sama dengan layar Approval Absen (jejak + kunci payroll)
        from routes.rahaza_auto_attendance_approvals import decide_selfie
        await decide_selfie(db, req_id, user, approve=True, notes=note)
        await log_activity(actor_id, actor_name, 'approve', 'hr_inbox',
                           f'Approve absen {req_id} via HR Inbox')
        return {'ok': True, 'type': 'attendance', 'id': req_id, 'new_status': 'approved'}

    if req_type == 'attendance_correction':
        from routes.rahaza_attendance_corrections import decide_correction
        out = await decide_correction(db, req_id, user, approve=True, note=note)
        await log_activity(actor_id, actor_name, 'approve', 'hr_inbox',
                           f'Setujui koreksi absen {req_id} via HR Inbox')
        return {'ok': True, 'type': 'attendance_correction', 'id': req_id, 'new_status': out.get('status')}

    if req_type == 'expense_claim':
        claim = await db.rahaza_expense_claims.find_one({'id': req_id})
        if not claim:
            raise HTTPException(404, 'Klaim biaya tidak ditemukan')
        if claim.get('status') != 'submitted':
            raise HTTPException(400, f"Status klaim saat ini: {claim.get('status')}. Harus submitted.")
        _tolak_ajuan_sendiri(claim, user, 'klaim biaya')
        res = await db.rahaza_expense_claims.update_one(
            {'id': req_id, 'status': 'submitted'},   # 2026-11-06 (pola P9)
            {'$set': {
                'status': 'approved',
                'approved_by': actor_id,
                'approved_by_name': actor_name,
                'approved_at': now,
                'approval_note': note,
                'updated_at': now,
            }}
        )
        doc_lock.require_matched(res, 'Klaim biaya ini baru saja diputuskan pengguna lain — muat ulang kotak masuk.')
        await log_activity(actor_id, actor_name, 'approve', 'hr_inbox',
                           f'Approve klaim biaya {req_id} via HR Inbox')
        await _kabari_pemohon('expense_claim', claim, approved=True, note=note)
        return {'ok': True, 'type': 'expense_claim', 'id': req_id, 'new_status': 'approved'}

    if req_type == 'travel_request':
        tr = await db.employee_travel_requests.find_one({'id': req_id})
        if not tr:
            raise HTTPException(404, 'Travel request tidak ditemukan')
        if tr.get('status') != 'submitted':
            raise HTTPException(400, f"Status travel request saat ini: {tr.get('status')}. Harus submitted.")
        _tolak_ajuan_sendiri(tr, user, 'perjalanan dinas')
        res = await db.employee_travel_requests.update_one(
            {'id': req_id, 'status': 'submitted'},   # 2026-11-06 (pola P9)
            {'$set': {
                'status': 'approved',
                'approved_by': actor_id,
                'approved_by_name': actor_name,
                'approved_at': now,
                'approval_note': note,
                'cash_advance_approved': tr.get('cash_advance_requested', 0),
                'updated_at': now,
            }}
        )
        doc_lock.require_matched(res, 'Perjalanan dinas ini baru saja diputuskan pengguna lain — muat ulang kotak masuk.')
        await log_activity(actor_id, actor_name, 'approve', 'hr_inbox',
                           f'Approve travel request {req_id} via HR Inbox')
        await _kabari_pemohon('travel_request', tr, approved=True, note=note)
        return {'ok': True, 'type': 'travel_request', 'id': req_id, 'new_status': 'approved'}

    raise HTTPException(400, 'Unhandled type')


@router.post('/{req_type}/{req_id}/reject')
async def reject_request(req_type: str, req_id: str, payload: ActionPayload,
                         user: dict = Depends(require_auth)):
    """Reject a pending HR request with required reason."""
    _require_approver_role(user)
    if req_type not in ALLOWED_TYPES:
        raise HTTPException(400, f'Type harus salah satu: {list(ALLOWED_TYPES)}')
    if not payload.reason and not payload.note:
        raise HTTPException(400, 'Alasan reject wajib diisi.')

    db = get_db()
    now = datetime.now(timezone.utc)
    reason = payload.reason or payload.note or ''
    actor_id = user.get('id', '')
    actor_name = user.get('name', '')

    if req_type == 'leave':
        from core.leave_engine import reject_leave_request
        await reject_leave_request(db, req_id, user, reason, via='kotak_masuk')
        await log_activity(actor_id, actor_name, 'reject', 'hr_inbox',
                           f'Reject cuti {req_id}: {reason}')
        return {'ok': True, 'type': 'leave', 'id': req_id, 'new_status': 'rejected'}

    if req_type == 'overtime':
        from routes.rahaza_overtime import reject_overtime_request
        await reject_overtime_request(db, req_id, user, reason)
        await log_activity(actor_id, actor_name, 'reject', 'hr_inbox',
                           f'Reject lembur {req_id}: {reason}')
        return {'ok': True, 'type': 'overtime', 'id': req_id, 'new_status': 'rejected'}

    if req_type == 'salary_adjustment':
        adj = await db.rahaza_salary_adjustments.find_one({'id': req_id})
        if not adj:
            raise HTTPException(404, 'Salary adjustment tidak ditemukan')
        # 2026-11-06 (pola P9): dulu TANPA pemeriksaan status — penyesuaian yang sudah disetujui (Profil Gaji
        # sudah berubah) bisa "ditolak" dari kotak masuk. Sekarang hanya yang masih menunggu.
        res = await db.rahaza_salary_adjustments.update_one(
            {'id': req_id, 'status': {'$in': ['draft', 'pending_manager', 'pending_hr']}},
            {'$set': {
                'status': 'rejected',
                'rejected_by': actor_id,
                'rejected_at': now,
                'reject_reason': reason,
            }}
        )
        doc_lock.require_matched(res, 'Penyesuaian gaji ini sudah diputuskan — muat ulang kotak masuk.')
        await log_activity(actor_id, actor_name, 'reject', 'hr_inbox',
                           f'Reject penyesuaian gaji {req_id}: {reason}')
        return {'ok': True, 'type': 'salary_adjustment', 'id': req_id, 'new_status': 'rejected'}

    if req_type == 'resignation':
        # Soft-reject = withdraw resignation submission
        from routes.rahaza_resignation import RESIGNING
        emp = await db.rahaza_employees.find_one({'id': req_id})
        if not emp:
            raise HTTPException(404, 'Employee tidak ditemukan')
        # 2026-11-06 (pola P3): pengajuan ditarik → karyawan kembali aktif (status pengajuan = employee_status)
        res = await db.rahaza_employees.update_one(
            {'id': req_id, 'employee_status': RESIGNING},
            {'$set': {
                'employee_status': 'active',
                'resignation_status': 'rejected',
                'resignation_rejected_by': actor_id,
                'resignation_rejected_at': now,
                'resignation_reject_reason': reason,
            }}
        )
        if not res.matched_count:   # 2026-11-06 (pola P9): sudah diputuskan pengguna lain
            raise HTTPException(409, 'Pengunduran diri ini sudah diputuskan — muat ulang kotak masuk.')
        await log_activity(actor_id, actor_name, 'reject', 'hr_inbox',
                           f'Reject resignasi karyawan {req_id}: {reason}')
        return {'ok': True, 'type': 'resignation', 'id': req_id, 'new_status': 'rejected'}

    if req_type == 'attendance':
        ev = await db.rahaza_attendance_events.find_one({'id': req_id})
        if not ev:
            raise HTTPException(404, 'Record absen tidak ditemukan')
        from routes.rahaza_auto_attendance_approvals import decide_selfie
        await decide_selfie(db, req_id, user, approve=False, notes=reason)
        await log_activity(actor_id, actor_name, 'reject', 'hr_inbox',
                           f'Reject absen {req_id}: {reason}')
        return {'ok': True, 'type': 'attendance', 'id': req_id, 'new_status': 'rejected'}

    if req_type == 'attendance_correction':
        from routes.rahaza_attendance_corrections import decide_correction
        await decide_correction(db, req_id, user, approve=False, note=reason)
        await log_activity(actor_id, actor_name, 'reject', 'hr_inbox',
                           f'Tolak koreksi absen {req_id}: {reason}')
        return {'ok': True, 'type': 'attendance_correction', 'id': req_id, 'new_status': 'rejected'}

    if req_type == 'expense_claim':
        claim = await db.rahaza_expense_claims.find_one({'id': req_id})
        if not claim:
            raise HTTPException(404, 'Klaim biaya tidak ditemukan')
        # 2026-11-06 (pola P9): aturan yang sama dengan layar Klaim — dulu klaim yang SUDAH dicairkan
        # (jurnal bayar ada) bisa "ditolak" dari kotak masuk.
        res = await db.rahaza_expense_claims.update_one(
            {'id': req_id, 'status': {'$in': ['submitted', 'approved']}, **doc_lock.lock_free('disburse_lock')},
            {'$set': {
                'status': 'rejected',
                'reject_reason': reason,
                'rejected_by': actor_id,
                'rejected_by_name': actor_name,
                'rejected_at': now,
                'updated_at': now,
            }}
        )
        doc_lock.require_matched(res, 'Klaim biaya ini sudah diproses (dicairkan/diputuskan) — muat ulang kotak masuk.')
        await log_activity(actor_id, actor_name, 'reject', 'hr_inbox',
                           f'Reject klaim biaya {req_id}: {reason}')
        await _kabari_pemohon('expense_claim', claim, approved=False, note=reason)
        return {'ok': True, 'type': 'expense_claim', 'id': req_id, 'new_status': 'rejected'}

    if req_type == 'travel_request':
        tr = await db.employee_travel_requests.find_one({'id': req_id})
        if not tr:
            raise HTTPException(404, 'Travel request tidak ditemukan')
        # 2026-11-06 (pola P9): aturan yang sama dengan layar Dinas — dinas yang uang mukanya sudah
        # dibayar tidak bisa "ditolak" dari kotak masuk.
        res = await db.employee_travel_requests.update_one(
            {'id': req_id, 'status': {'$in': ['submitted', 'approved']}, **doc_lock.lock_free('advance_lock')},
            {'$set': {
                'status': 'rejected',
                'reject_reason': reason,
                'rejected_by': actor_id,
                'rejected_by_name': actor_name,
                'rejected_at': now,
                'updated_at': now,
            }}
        )
        doc_lock.require_matched(res, 'Perjalanan dinas ini sudah diproses (uang muka dibayar/diputuskan) — '
                                      'muat ulang kotak masuk.')
        await log_activity(actor_id, actor_name, 'reject', 'hr_inbox',
                           f'Reject travel request {req_id}: {reason}')
        await _kabari_pemohon('travel_request', tr, approved=False, note=reason)
        return {'ok': True, 'type': 'travel_request', 'id': req_id, 'new_status': 'rejected'}

    raise HTTPException(400, 'Unhandled type')
