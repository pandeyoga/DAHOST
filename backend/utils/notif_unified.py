"""
P3 TD-010 Part B — Unified Notifications Helper (Session #11.12)
================================================================
Single SSOT helper for the `notifications` collection.

After Session #11.12 (TD-010 Phase B), ALL legacy notification writers
(dewi_notifications, rahaza_notifications, collab_notifications,
marketing_livehost_notifications) have been refactored to call
`notif_insert()` directly. The 4 legacy collections are now empty
and scheduled for removal after a 1-week monitor period via
`migrations/drop_legacy_notif_collections.py`.

This module also exposes BACKWARD-COMPAT reshape helpers used by
the 4 legacy routers to keep their public response schema unchanged
while reading from the SSOT.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Any, List
import logging
import uuid

_log = logging.getLogger(__name__)


VALID_TYPES = {'dewi', 'rahaza', 'collab', 'marketing_livehost'}
VALID_SEVERITIES = {'info', 'success', 'warning', 'error'}
VALID_CHANNELS = {'in_app', 'whatsapp', 'email', 'sse'}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# WAKTU KE KLIEN — SELALU DENGAN ZONA (2026-11-02)
#
# Motor dibuka tanpa `tz_aware` (database.py), jadi `created_at` kembali sebagai
# datetime NAIF bernilai UTC dan dulu dikirim "2026-11-01T21:33:43.861000".
# Browser menafsirkan string tanpa offset sebagai waktu LOKAL ⇒ di WIB setiap
# notifikasi tampil 7 jam lebih tua ("7 jam lalu" untuk notifikasi 1 menit) dan
# Portal Saya menampilkan jam UTC mentah. Semua pembaca notifikasi kini memakai
# `iso_utc` → "2026-11-01T21:33:43.861Z" (milidetik, aman untuk semua browser).
# ─────────────────────────────────────────────────────────────────────────────

def iso_utc(v: Any) -> Any:
    """datetime → ISO UTC ber-'Z' (naif dianggap UTC, sesuai cara penyimpanan)."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    return v


_TIME_FIELDS = ('created_at', 'read_at', 'sent_at', 'updated_at', 'resolved_at')


def notif_times_iso(doc: dict) -> dict:
    """Salinan dokumen dengan field waktu notifikasi sudah ber-zona (lihat `iso_utc`)."""
    out = dict(doc or {})
    for k in _TIME_FIELDS:
        if k in out:
            out[k] = iso_utc(out[k])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# TAUTAN MODUL — id yang tidak ada di registry frontend (2026-11-02)
#
# Audit 2026-11-02: 7 id `link_module` yang ditulis backend TIDAK ada di
# MODULE_REGISTRY frontend, sehingga tombol "Buka" diam (ditandai dibaca, layar
# tidak berubah). 258 notifikasi stok kritis (30% isi DB) terdampak. Peta ini
# dipakai SAAT TULIS (`notif_insert`) dan SAAT BACA (bel/Portal Saya), jadi
# notifikasi lama ikut sembuh dan penulis di berkas lain yang belum diperbaiki
# tetap mendarat di layar yang hidup. Uji kontrak: tests/unit/test_notif_p7.py
# memastikan setiap tujuan di peta ini ADA di frontend moduleRegistry.js.
# ─────────────────────────────────────────────────────────────────────────────
LINK_MODULE_ALIASES = {
    # stok kritis (mesin alert) — penulis kembar `rahaza_inventory_shared` sudah memakai wh-stock
    'prod-materials': 'wh-stock',
    # klaim biaya / perjalanan dinas / settlement → tab "Approval Klaim & Dinas"
    'hr-approval-inbox': 'hr-expense-approval',
    # salah ejaan garis bawah vs tanda hubung
    'hr_salary_adjustments': 'hr-salary-adjustments',
    'kpi_portal': 'kpi-portal',
    'hr_kpi': 'hr-kpi',
    'hris_employees': 'hr-employees',
    'my_profile': 'portal-profile',
}


def normalize_link_module(mod: Optional[str]) -> Optional[str]:
    if not mod:
        return mod
    return LINK_MODULE_ALIASES.get(str(mod), mod)


# K37 (keputusan owner 2026-11-02) — TUJUAN BERBEDA PER PERAN PENERIMA.
# Notifikasi klaim/dinas dikirim ke peran SDM & Keuangan sekaligus. SDM tetap
# ke layar persetujuan SDM; Keuangan ke Pengeluaran Keuangan tab "Klaim Karyawan
# (Disbursement)". Dipilih berdasarkan portal yang BENAR-BENAR bisa dibuka
# penerima (`routes.shared.resolve_role_access`), urut prioritas.
# Format: id_modul → ((portal, id_modul_tujuan, tab_hub|None), ...)
ROLE_LINK_ALIASES = {
    'hr-expense-approval': (('hr', 'hr-expense-approval', None),
                            ('finance', 'fin-expenses', 'settlement')),
}


def link_for_portals(mod: Optional[str], portals=None):
    """(id modul, tab hub) untuk penerima yang bisa membuka `portals`.

    `portals=None` = tanpa pemeriksaan peran (alias statis saja)."""
    mod = normalize_link_module(mod)
    opts = ROLE_LINK_ALIASES.get(mod or '')
    if not opts or portals is None:
        return mod, None
    have = set(portals)
    for portal, target, tab in opts:
        if portal in have:
            return target, tab
    return mod, None


# ─────────────────────────────────────────────────────────────────────────────
# K30 — "PERLU TINDAKAN" vs "PEMBERITAHUAN" (keputusan owner 2026-11-02)
#
# Audit 2026-11-02: tidak ada pembeda notifikasi yang menuntut tindakan dari
# yang sekadar kabar; notifikasi approval/stok yang sudah selesai tetap "belum
# dibaca" selamanya, sementara Approval Badge menghitung pekerjaan yang sama
# dari dokumen ⇒ dua angka berbeda untuk satu pekerjaan.
#
# MODEL (semua field opsional — penulis lama tetap sah):
#   kind              'action' (perlu tindakan) | 'info' (pemberitahuan)
#   action            {label, target_menu, record_id?, filter?}
#   source_collection koleksi dokumen sumber (+ `source_id` yang sudah ada)
#   resolve_rule      aturan selesai (lihat SOURCE_RULES)
#   resolved_at / resolved_reason / resolved_by   diisi resolver
#
# Notifikasi lama & penulis yang belum diubah DIKLASIFIKASIKAN dari `subtype`
# (ACTION_SUBTYPES). Subtype lain = pemberitahuan (kontrak berakhir dikecualikan,
# lihat catatan di ACTION_SUBTYPES).
# ─────────────────────────────────────────────────────────────────────────────
KIND_ACTION = 'action'
KIND_INFO = 'info'
VALID_KINDS = {KIND_ACTION, KIND_INFO}

# SATU definisi "masih menunggu tindakan" per sumber. Dipakai resolver
# (menutup notifikasi) DAN butir Perlu Tindakan yang dihitung langsung dari
# dokumen (routes/approval_badge.py) — keduanya tidak boleh berbeda pendapat.
#   collection  koleksi sumber      field  field status (boleh bertitik)
#   open        nilai status yang berarti BELUM selesai (selain itu = selesai)
#   match       syarat tambahan agar tetap terbuka
#   array       dokumen sumber tertanam di array (id = elemen.id)
#   check       evaluator khusus untuk kondisi yang bukan status dokumen
SOURCE_RULES = {
    'procurement':       {'check': 'procurement_stage'},   # koleksi dari meta.link_module
    'expense_claim':     {'collection': 'rahaza_expense_claims', 'field': 'status', 'open': ['submitted']},
    'expense_disburse':  {'collection': 'rahaza_expense_claims', 'field': 'status', 'open': ['approved']},
    'travel_request':    {'collection': 'employee_travel_requests', 'field': 'status', 'open': ['submitted']},
    'travel_settlement': {'collection': 'employee_travel_settlements', 'field': 'status', 'open': ['submitted']},
    'leave_manager':     {'collection': 'rahaza_leave_requests', 'field': 'status', 'open': ['pending_approval']},
    'leave_hr':          {'collection': 'rahaza_leave_requests', 'field': 'status', 'open': ['pending_hr_approval']},
    'overtime':          {'collection': 'rahaza_overtime_requests', 'field': 'status', 'open': ['pending']},
    'salary_manager':    {'collection': 'rahaza_salary_adjustments', 'field': 'status', 'open': ['pending_manager']},
    'salary_hr':         {'collection': 'rahaza_salary_adjustments', 'field': 'status', 'open': ['pending_hr']},
    'attendance_permit': {'collection': 'rahaza_attendance_events', 'array': 'sessions',
                          'field': 'approval_status', 'open': ['pending']},
    'kasbon_review':     {'collection': 'dewi_kasbon_requests', 'field': 'status', 'open': ['submitted']},
    'kasbon_disburse':   {'collection': 'dewi_kasbon_requests', 'field': 'status', 'open': ['hr_approved']},
    'ap_invoice':        {'collection': 'rahaza_ap_invoices', 'field': 'status', 'open': ['sent', 'partial_paid']},
    'payroll_cancel':    {'collection': 'rahaza_payroll_runs', 'field': 'cancel_request.status', 'open': ['pending']},
    'wh_return':         {'collection': 'wh_returns', 'field': 'status',
                          'open': ['Pending', 'Received', 'Inspected']},
    # K17 — tagihan CMT bertanda selisih menunggu Keuangan (tidak diubah otomatis);
    # selesai begitu Keuangan memprosesnya (dibayar/dibatalkan).
    'cmt_variance':      {'collection': 'dewi_cmt_payments', 'field': 'status', 'open': ['draft', 'posted'],
                          'match': {'variance_flagged': True}},
    'low_stock':         {'collection': 'rahaza_materials', 'check': 'stock_low'},
    'negative_stock':    {'collection': 'rahaza_material_stock', 'check': 'stock_negative'},
    'contract_expiry':   {'collection': 'rahaza_employees', 'check': 'contract_expiring'},
}

# subtype → (kunci SOURCE_RULES, label tombol aksi). Subtype di luar daftar = info.
ACTION_SUBTYPES = {
    'procurement_approval':        ('procurement', 'Setujui / tolak'),
    'expense_claim_submitted':     ('expense_claim', 'Putuskan klaim'),
    'travel_request_submitted':    ('travel_request', 'Putuskan perjalanan dinas'),
    'travel_settlement_submitted': ('travel_settlement', 'Periksa settlement'),
    'leave_request_submitted':     ('leave_manager', 'Putuskan cuti'),
    'leave_hr_approval_needed':    ('leave_hr', 'Putuskan cuti'),
    'attendance_permit_request':   ('attendance_permit', 'Putuskan izin keluar'),
    'salary_raise_approval':       ('salary_manager', 'Putuskan kenaikan gaji'),
    'salary_raise_hr_approval':    ('salary_hr', 'Putuskan kenaikan gaji'),
    'low_stock':                   ('low_stock', 'Cek stok'),
    'negative_stock_daily':        ('negative_stock', 'Bereskan stok minus'),
    # Kontrak berakhir = ACTION untuk SDM: penerimanya hanya SDM/admin
    # (rahaza_alerts.check_expiring_contracts) dan menuntut keputusan
    # perpanjang/akhiri; tertutup sendiri saat kontrak diperpanjang di luar
    # jendela H-30, karyawan nonaktif, atau tanggal kontrak lewat.
    'contract_expiry':             ('contract_expiry', 'Tindak lanjuti kontrak'),
    # Kelas untuk penulis yang BELUM ada (pengajuan lembur/kasbon, pembatalan run
    # gaji, retur menunggu gudang, tagihan bertanda variance). Saat ini pekerjaan
    # itu masuk Perlu Tindakan lewat hitungan dokumen (routes/approval_badge.py).
    'overtime_request_submitted':  ('overtime', 'Putuskan lembur'),
    'kasbon_submitted':            ('kasbon_review', 'Putuskan kasbon'),
    # 2026-11-02 — tahap ke-2 kasbon: disetujui HR → menunggu pencairan Keuangan
    'kasbon_disburse_pending':     ('kasbon_disburse', 'Cairkan kasbon'),
    'payroll_cancel_requested':    ('payroll_cancel', 'Putuskan pembatalan run gaji'),
    'wh_return_pending':           ('wh_return', 'Putuskan retur'),
    'cmt_invoice_variance':        ('cmt_variance', 'Periksa tagihan'),
}

# Kode alasan penutupan → teks riwayat.
RESOLVED_LABELS = {
    'superseded': 'Digantikan notifikasi yang lebih baru',
    'source_missing': 'Dokumen sumber sudah tidak ada',
    'manual': 'Ditutup manual',
}


def resolved_label(reason: Optional[str]) -> str:
    if not reason:
        return ''
    if reason in RESOLVED_LABELS:
        return RESOLVED_LABELS[reason]
    code, _, val = str(reason).partition(':')
    if code == 'status':
        return f"Selesai — status sumber kini '{val}'"
    if code == 'stage':
        return f"Tahap ini sudah diputuskan (kini tahap '{val}')"
    if code == 'condition':
        return {'ok': 'Kondisi sudah normal kembali', 'no_threshold': 'Ambang stok dikosongkan',
                'renewed': 'Kontrak sudah diperpanjang', 'ended': 'Tanggal kontrak sudah lewat',
                'inactive': 'Karyawan sudah nonaktif'}.get(val, f'Kondisi berubah ({val})')
    return f'Selesai ({reason})'


def rule_open_filter(rule: dict) -> dict:
    """Filter Mongo "masih terbuka" untuk aturan status (bukan `check`/`array`)."""
    q = {rule.get('field') or 'status': {'$in': list(rule.get('open') or [])}}
    q.update(rule.get('match') or {})
    return q


def _procurement_collection(meta: dict) -> Optional[str]:
    from core.pr_approval import _MODULE_COLLECTION
    return _MODULE_COLLECTION.get(normalize_link_module((meta or {}).get('link_module')) or 'proc-requests')


def rule_of(doc: dict) -> Optional[dict]:
    """Aturan selesai notifikasi (tersimpan, atau turunan dari subtype)."""
    doc = doc or {}
    rule = doc.get('resolve_rule')
    if not rule:
        spec = ACTION_SUBTYPES.get(doc.get('subtype') or '')
        if not spec:
            return None
        rule = SOURCE_RULES.get(spec[0])
        if not rule:
            return None
    rule = dict(rule)
    if rule.get('check') == 'procurement_stage' and not rule.get('collection'):
        rule['collection'] = doc.get('source_collection') or _procurement_collection(doc.get('meta') or {})
    return rule


def source_collection_of(doc: dict) -> Optional[str]:
    rule = rule_of(doc) or {}
    return (doc or {}).get('source_collection') or rule.get('collection')


def _resolvable(doc: dict, rule: Optional[dict]) -> bool:
    """Action WAJIB bisa ditutup otomatis: punya aturan + sumber yang bisa dicek."""
    if not rule:
        return False
    if rule.get('check') == 'stock_negative':
        return True                      # kondisi global (tanpa id rekaman)
    return bool((doc or {}).get('source_id'))


def kind_of(doc: dict) -> str:
    """'action' | 'info' — field tersimpan, atau pemetaan subtype untuk dokumen lama."""
    k = (doc or {}).get('kind')
    if k in VALID_KINDS:
        return k
    return KIND_ACTION if _resolvable(doc, rule_of(doc)) else KIND_INFO


def is_open_action(doc: dict) -> bool:
    return kind_of(doc) == KIND_ACTION and not (doc or {}).get('resolved_at')


def action_of(doc: dict, portals=None) -> Optional[dict]:
    """Tombol aksi {label, target_menu, record_id?, filter?} untuk penerima ber-`portals`."""
    if kind_of(doc) != KIND_ACTION:
        return None
    meta = doc.get('meta') or {}
    stored = dict(doc.get('action') or {})
    spec = ACTION_SUBTYPES.get(doc.get('subtype') or '')
    label = stored.get('label') or (spec[1] if spec else 'Tindak lanjuti')
    target0 = stored.get('target_menu') or doc.get('link_module') or meta.get('link_module') or ''
    filt = dict(stored.get('filter') or doc.get('link_params') or meta.get('link_params') or {})
    if meta.get('hub_tab') and not filt.get('tab'):
        filt['tab'] = meta['hub_tab']
    target, tab = link_for_portals(target0, portals)
    if target != normalize_link_module(target0):
        filt.pop('tab', None)            # tab milik layar lama tidak berlaku di layar baru
        if tab:
            filt['tab'] = tab
    out = {'label': label, 'target_menu': target or None}
    rid = stored.get('record_id') or doc.get('source_id') or doc.get('link_id')
    if rid:
        out['record_id'] = rid
    if filt:
        out['filter'] = filt
    return out


def classify_for_insert(*, subtype=None, kind=None, action=None, source_collection=None,
                        resolve=None, source_id=None, meta=None) -> dict:
    """Field K30 untuk dokumen baru (dipakai `notif_insert`)."""
    probe = {'subtype': subtype, 'source_id': source_id, 'meta': meta or {},
             'resolve_rule': resolve, 'source_collection': source_collection, 'action': action}
    rule = rule_of(probe)
    if kind in VALID_KINDS:
        k = kind
        if k == KIND_ACTION and not _resolvable(probe, rule):
            # Action tanpa aturan selesai tidak akan pernah tertutup ⇒ jadikan info.
            _log.warning('[notif] kind=action tanpa aturan selesai/sumber (subtype=%s) → info', subtype)
            k = KIND_INFO
    else:
        k = kind_of(probe)
    if k != KIND_ACTION:
        return {'kind': KIND_INFO}
    probe['kind'] = KIND_ACTION
    return {
        'kind': KIND_ACTION,
        'action': action_of(probe),
        'source_collection': source_collection or rule.get('collection'),
        'resolve_rule': rule,
        'resolved_at': None,
        'resolved_reason': None,
    }


def _dig(doc, path):
    cur = doc
    for part in str(path).split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _procurement_open(doc: dict, coll: str, stage: Optional[str]):
    from core import pr_approval as pa
    status = doc.get('status')
    if coll == pa.ACC_PR_COLLECTION:
        cur = (doc.get('current_approver_stage') or pa.STAGE_DEPT) if status == pa.ACC_PR_STATUS_SUBMITTED else None
    elif coll == pa.PO_COLLECTION:
        cur = (doc.get('current_approver_stage') or pa.STAGE_DEPT) if status == pa.PO_PENDING_STATUS else None
    else:
        cur = pa.STATUS_TO_STAGE.get(status)
    if cur is None:
        return False, f'status:{status}'
    if stage and cur != stage:
        return False, f'stage:{cur}'
    return True, ''


def _contract_open(doc: dict, today: date):
    from routes.rahaza_alerts import CONTRACT_ALERT_DAYS, CONTRACT_ALERT_TYPES
    if doc.get('active') is False:
        return False, 'condition:inactive'
    if doc.get('contract_type') not in CONTRACT_ALERT_TYPES:
        return False, 'condition:contract_type'
    try:
        end = date.fromisoformat(str(doc.get('contract_end_date') or '')[:10])
    except ValueError:
        return False, 'condition:no_end_date'
    left = (end - today).days
    if left < 0:
        return False, 'condition:ended'
    if left > CONTRACT_ALERT_DAYS:
        return False, 'condition:renewed'
    return True, ''


def evaluate_open(notif: dict, *, docs: dict, fetched: set, stock: Optional[dict] = None,
                  negative: Optional[bool] = None, today: Optional[date] = None):
    """(masih_terbuka, alasan). `None` = tidak bisa dipastikan → biarkan terbuka.

    Fungsi murni: dokumen sumber sudah diambil `_evaluate_rows` ke `docs`
    {(koleksi, id): dok}; `fetched` = koleksi yang berhasil diambil."""
    rule = rule_of(notif)
    if not rule:
        return None, ''
    chk = rule.get('check')
    sid = notif.get('source_id')
    if chk == 'stock_low':
        if stock is None or not sid:
            return None, ''
        st = stock.get(sid)
        if st is None:
            return False, 'source_missing'          # material nonaktif/terhapus
        return (True, '') if st in ('low', 'critical') else (False, f'condition:{st}')
    if chk == 'stock_negative':
        if negative is None:
            return None, ''
        return (True, '') if negative else (False, 'condition:ok')
    coll = source_collection_of(notif)
    if not coll or not sid or coll not in fetched:
        return None, ''
    doc = docs.get((coll, sid))
    if doc is None:
        return False, 'source_missing'
    if chk == 'procurement_stage':
        return _procurement_open(doc, coll, (notif.get('meta') or {}).get('stage'))
    if chk == 'contract_expiring':
        if today is None:
            from utils.waktu import today_wib
            today = today_wib()
        return _contract_open(doc, today)
    if rule.get('array'):
        doc = next((s for s in (doc.get(rule['array']) or []) if s.get('id') == sid), None)
        if doc is None:
            return False, 'source_missing'
    for k, v in (rule.get('match') or {}).items():
        if _dig(doc, k) != v:
            return False, f'{k}:{_dig(doc, k)}'
    val = _dig(doc, rule.get('field') or 'status')
    return (True, '') if val in (rule.get('open') or []) else (False, f'status:{val}')


async def _evaluate_rows(db, rows: list, *, today: Optional[date] = None) -> list:
    """[(notif, alasan)] untuk notifikasi action yang SUDAH selesai."""
    need: dict = {}
    stock_ids: set = set()
    neg_needed = False
    for r in rows:
        rule = rule_of(r) or {}
        chk = rule.get('check')
        if chk == 'stock_low':
            if r.get('source_id'):
                stock_ids.add(r['source_id'])
            continue
        if chk == 'stock_negative':
            neg_needed = True
            continue
        coll = source_collection_of(r)
        if coll and r.get('source_id'):
            need.setdefault((coll, rule.get('array')), set()).add(r['source_id'])
    docs: dict = {}
    fetched: set = set()
    for (coll, arr), ids in need.items():
        try:
            q = ({arr: {'$elemMatch': {'id': {'$in': list(ids)}}}} if arr
                 else {'id': {'$in': list(ids)}})
            async for d in db[coll].find(q, {'_id': 0}):
                if arr:
                    for s in d.get(arr) or []:
                        if s.get('id') in ids:
                            docs[(coll, s['id'])] = d
                else:
                    docs[(coll, d.get('id'))] = d
            fetched.add(coll)
        except Exception:  # noqa: BLE001 — sumber gagal dibaca ⇒ biarkan terbuka
            _log.warning('[notif] resolver gagal membaca %s', coll, exc_info=True)
    stock = None
    if stock_ids:
        try:
            from core import stock_thresholds as _th
            rows_th = await _th.evaluate(db, material_ids=list(stock_ids), with_suggestion=False)
            stock = {x['material_id']: x['status'] for x in rows_th}
        except Exception:  # noqa: BLE001
            _log.warning('[notif] resolver gagal mengevaluasi stok', exc_info=True)
    negative = None
    if neg_needed:
        try:
            negative = await db.rahaza_material_stock.find_one({'qty': {'$lt': 0}}, {'_id': 0, 'id': 1}) is not None
        except Exception:  # noqa: BLE001
            negative = None
    out = []
    for r in rows:
        state, reason = evaluate_open(r, docs=docs, fetched=fetched, stock=stock,
                                      negative=negative, today=today)
        if state is False:
            out.append((r, reason))
    return out


async def _mark_resolved(db, pairs, *, now=None, by: str = 'system') -> int:
    now = now or _now()
    n = 0
    for r, reason in pairs:
        res = await db.notifications.update_one(
            {'id': r['id'], 'resolved_at': None},
            {'$set': {'kind': KIND_ACTION, 'resolved_at': now, 'resolved_reason': reason,
                      'resolved_by': by}})
        n += res.modified_count
    return n


def _open_action_query(extra: Optional[dict] = None) -> dict:
    """Action terbuka — termasuk dokumen lama yang belum di-backfill `kind`-nya."""
    q = {'resolved_at': None,
         '$or': [{'kind': KIND_ACTION},
                 {'kind': {'$exists': False}, 'subtype': {'$in': list(ACTION_SUBTYPES)}}]}
    q.update(extra or {})
    return q


_RESOLVE_PROJECTION = {'_id': 0, 'id': 1, 'kind': 1, 'subtype': 1, 'source_id': 1,
                       'source_type': 1, 'source_collection': 1, 'resolve_rule': 1,
                       'resolved_at': 1, 'meta.link_module': 1, 'meta.stage': 1}


async def resolve_rows(db, rows: list, *, now=None, today: Optional[date] = None) -> int:
    """Tutup notifikasi action di `rows` yang tindakannya sudah selesai."""
    rows = [r for r in rows if is_open_action(r)]
    if not rows:
        return 0
    return await _mark_resolved(db, await _evaluate_rows(db, rows, today=today), now=now)


async def resolve_for_source(db, source_collection: Optional[str] = None,
                             source_id: Optional[str] = None, *, skip_ids=(),
                             now=None, today: Optional[date] = None) -> int:
    """SATU resolver generik: periksa ulang notifikasi action untuk satu sumber.

    Boleh dipanggil langsung dari kode domain sesudah status berubah. Tanpa
    perubahan berkas domain pun ia sudah dipanggil otomatis oleh `notif_insert`
    setiap kali notifikasi ber-`source_id` yang sama ditulis (kabar keputusan
    ke pemohon, tahap persetujuan berikutnya) — dan oleh job terjadwal."""
    if not source_id and not source_collection:
        return 0
    extra: dict = {}
    if source_id:
        extra['source_id'] = source_id
    if source_collection:
        extra['source_collection'] = source_collection
    rows = await db.notifications.find(_open_action_query(extra), _RESOLVE_PROJECTION).to_list(500)
    rows = [r for r in rows if r.get('id') not in set(skip_ids or ())]
    return await resolve_rows(db, rows, now=now, today=today)


async def supersede_older_actions(db, doc: dict, *, now=None) -> int:
    """Action baru untuk sumber yang sama menutup salinan terbuka yang lebih lama
    (mis. kontrak berakhir harian, stok kritis → stok menipis, tahap PR berikut)."""
    if doc.get('kind') != KIND_ACTION or not doc.get('subtype'):
        return 0
    q = _open_action_query({'subtype': doc['subtype'], 'id': {'$ne': doc['id']},
                            'source_id': doc.get('source_id')})
    if not doc.get('source_id'):
        q['source_type'] = doc.get('source_type')
    res = await db.notifications.update_many(q, {'$set': {
        'kind': KIND_ACTION, 'resolved_at': now or _now(), 'resolved_reason': 'superseded',
        'resolved_by': 'system'}})
    return res.modified_count


async def backfill_kinds(db) -> dict:
    """Isi `kind` (+ sumber) pada notifikasi lama dari pemetaan subtype. Idempoten."""
    out = {'action': 0, 'info': 0}
    missing = {'kind': {'$exists': False}}
    for subtype, (key, _label) in ACTION_SUBTYPES.items():
        rule = SOURCE_RULES.get(key) or {}
        q = {**missing, 'subtype': subtype}
        if rule.get('check') != 'stock_negative':
            q['source_id'] = {'$nin': [None, '']}
        if rule.get('check') == 'procurement_stage':
            from core.pr_approval import _MODULE_COLLECTION
            for mod, coll in _MODULE_COLLECTION.items():
                res = await db.notifications.update_many(
                    {**q, 'meta.link_module': mod},
                    {'$set': {'kind': KIND_ACTION, 'source_collection': coll, 'resolved_at': None}})
                out['action'] += res.modified_count
            continue
        res = await db.notifications.update_many(
            q, {'$set': {'kind': KIND_ACTION, 'source_collection': rule.get('collection'),
                         'resolved_at': None}})
        out['action'] += res.modified_count
    res = await db.notifications.update_many(missing, {'$set': {'kind': KIND_INFO}})
    out['info'] += res.modified_count
    return out


async def ensure_notif_indexes(db) -> None:
    """Indeks untuk resolver & retensi (idempoten; aman bila gagal)."""
    try:
        await db.notifications.create_index([('kind', 1), ('resolved_at', 1)])
        await db.notifications.create_index('source_id')
    except Exception:  # noqa: BLE001 — indeks hanya optimasi
        _log.debug('[notif] create_index gagal', exc_info=True)


async def run_action_resolver(db, *, now=None, today: Optional[date] = None,
                              limit: int = 20000) -> dict:
    """Job terjadwal ringan: backfill `kind` lalu tutup semua action yang selesai."""
    await ensure_notif_indexes(db)
    backfilled = await backfill_kinds(db)
    rows = await db.notifications.find(_open_action_query(), _RESOLVE_PROJECTION).to_list(limit)
    resolved = await resolve_rows(db, rows, now=now, today=today)
    return {'backfilled': backfilled, 'checked': len(rows), 'resolved': resolved}


# ─────────────────────────────────────────────────────────────────────────────
# K31 — RETENSI (keputusan owner 2026-11-02)
#
# Dihapus setelah `retention_days` (bawaan 90, diatur di Aturan Notifikasi /
# `notif_category_config.retention_days`):
#   · pemberitahuan (info) yang SUDAH DIBACA — personal: `read`; bersama: dibaca
#     SEMUA penerima aktif (umur dihitung dari `created_at`);
#   · action yang SUDAH TERTUTUP (umur dihitung dari `resolved_at`).
# Action yang masih terbuka TIDAK PERNAH dihapus. Hanya kanal in-app: outbox
# WA/email klien maklon & notifikasi portal host live tidak disentuh.
# ─────────────────────────────────────────────────────────────────────────────
# 2026-11-06 (pola P2): koleksi dibaca lewat konstanta penulisnya (satu nama, tidak ada koleksi hantu)
CATEGORY_CONFIG = "notif_category_config"
RETENTION_DEFAULT_DAYS = 90
RETENTION_MIN_DAYS = 7
RETENTION_MAX_DAYS = 3650
RETENTION_TYPES = ('rahaza', 'collab', 'dewi')


def clamp_retention_days(v) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return RETENTION_DEFAULT_DAYS
    return max(RETENTION_MIN_DAYS, min(RETENTION_MAX_DAYS, n))


async def retention_days(db) -> int:
    doc = await db[CATEGORY_CONFIG].find_one({'id': 'default'}, {'_id': 0, 'retention_days': 1}) or {}
    return clamp_retention_days(doc.get('retention_days') or RETENTION_DEFAULT_DAYS)


async def _recipient_index(db) -> dict:
    from utils.notif_recipients import ACTIVE_USER_FILTER
    rows = await db.users.find(ACTIVE_USER_FILTER, {'_id': 0, 'id': 1, 'role': 1}).to_list(None)
    by_role: dict = {}
    for u in rows:
        if u.get('id'):
            by_role.setdefault((u.get('role') or '').lower(), set()).add(u['id'])
    return {'ids': {u['id'] for u in rows if u.get('id')}, 'by_role': by_role}


def fully_read(doc: dict, idx: dict) -> bool:
    """Sudah dibaca semua penerima aktif (personal: field `read`)."""
    if doc.get('user_id'):
        return bool(doc.get('read'))
    meta = doc.get('meta') or {}
    users = set(doc.get('target_user_ids') or []) | set(meta.get('target_user_ids') or [])
    roles = {str(r).lower() for r in (list(doc.get('target_roles') or []) + list(meta.get('target_roles') or []))}
    if not users and not roles:
        roles = set(NOTIF_SUPER_ROLES)
    recipients = (users & idx['ids'])
    for r in roles:
        recipients |= idx['by_role'].get(r, set())
    read_by = set(meta.get('read_by') or []) | set(doc.get('read_by') or [])
    return recipients <= read_by


async def purge_notifications(db, *, days: Optional[int] = None, dry_run: bool = False,
                              now=None) -> dict:
    """Hapus notifikasi kedaluwarsa menurut K31. `dry_run` = hanya hitung."""
    days = clamp_retention_days(days) if days else await retention_days(db)
    now = now or _now()
    cutoff = now - timedelta(days=days)
    base = {'type': {'$in': list(RETENTION_TYPES)}, 'channel': {'$in': ['in_app', None]}}
    act = await db.notifications.find(
        {**base, 'kind': KIND_ACTION, 'resolved_at': {'$lt': cutoff}}, {'_id': 0, 'id': 1}).to_list(None)
    act_ids = [r['id'] for r in act if r.get('id')]
    info_q = {**base, 'created_at': {'$lt': cutoff}, 'resolved_at': None,
              '$or': [{'kind': KIND_INFO},
                      {'kind': {'$exists': False}, 'subtype': {'$nin': list(ACTION_SUBTYPES)}}]}
    idx = await _recipient_index(db)
    info_ids, kept_unread = [], 0
    async for r in db.notifications.find(info_q, {'_id': 0, 'id': 1, 'user_id': 1, 'read': 1, 'read_by': 1,
                                                  'target_user_ids': 1, 'target_roles': 1, 'meta': 1}):
        if fully_read(r, idx):
            info_ids.append(r['id'])
        else:
            kept_unread += 1
    deleted = 0
    if not dry_run:
        ids = act_ids + info_ids
        for i in range(0, len(ids), 1000):
            res = await db.notifications.delete_many({'id': {'$in': ids[i:i + 1000]}})
            deleted += res.deleted_count
    return {'retention_days': days, 'cutoff': iso_utc(cutoff), 'dry_run': dry_run,
            'action_resolved': len(act_ids), 'info_read': len(info_ids),
            'info_unread_kept': kept_unread, 'deleted': deleted}


# Pembersihan SEKALI-JALAN salinan duplikat lama: penjadwal dulu menerbitkan
# ulang notifikasi berkunci sama tiap 10 menit (kontrak) / 30 menit (SLA).
# Satu salinan TERBARU per (subtype, dedup_key) dipertahankan; status baca
# semua salinan digabung ke salinan itu supaya tidak ada yang "muncul lagi".
LEGACY_DUP_SUBTYPES = ('contract_expiry', 'sla_breach')


async def dedupe_legacy_copies(db, *, subtypes=LEGACY_DUP_SUBTYPES, dry_run: bool = True) -> dict:
    rows = await db.notifications.find(
        {'subtype': {'$in': list(subtypes)}, 'meta.dedup_key': {'$nin': [None, '']}, 'user_id': None},
        {'_id': 0, 'id': 1, 'subtype': 1, 'created_at': 1, 'meta': 1, 'read_by': 1}).to_list(None)
    groups: dict = {}
    for r in rows:
        groups.setdefault((r.get('subtype'), (r.get('meta') or {}).get('dedup_key')), []).append(r)
    per_subtype: dict = {}
    drop, merges = [], []
    for (st, _key), docs in groups.items():
        if len(docs) < 2:
            continue
        docs.sort(key=lambda d: str(iso_utc(d.get('created_at')) or ''), reverse=True)
        keep, rest = docs[0], docs[1:]
        read_by = set()
        for d in docs:
            read_by |= set((d.get('meta') or {}).get('read_by') or []) | set(d.get('read_by') or [])
        merges.append((keep['id'], sorted(read_by)))
        drop += [d['id'] for d in rest]
        per_subtype[st] = per_subtype.get(st, 0) + len(rest)
    deleted = 0
    if not dry_run:
        for nid, read_by in merges:
            await db.notifications.update_one({'id': nid}, {'$set': {'meta.read_by': read_by}})
        for i in range(0, len(drop), 1000):
            res = await db.notifications.delete_many({'id': {'$in': drop[i:i + 1000]}})
            deleted += res.deleted_count
    return {'dry_run': dry_run, 'subtypes': list(subtypes), 'groups': len(merges),
            'duplicates': len(drop), 'per_subtype': per_subtype, 'deleted': deleted}


# ─────────────────────────────────────────────────────────────────────────────
# PERAN PENERIMA ALERT — HANYA PERAN NYATA (2026-11-02)
#
# Audit 2026-11-02 (N1): alert stok kritis/WO/kontrak ditarget ke peran yang
# tidak pernah ada (`warehouse_manager`, `manager_production`,
# `production_manager`) ⇒ hanya superadmin yang menerima; admin gudang tidak
# pernah tahu stoknya kritis. Peran pengganti DITURUNKAN dari PORTAL_ACCESS
# portal terkait (routes/shared.py), lalu dipersempit ke peran yang memegang
# kewenangan domain itu (core/roles.py) supaya alert tindakan tidak menyiram
# staf lini/operator. Keduanya SSOT repo — tidak ada daftar peran baru di sini.
# ─────────────────────────────────────────────────────────────────────────────
# Peran fiktif → portal asal tugasnya. `finance` = nama generik lama; peran
# keuangan yang benar-benar ada: accounting/staff_keuangan/manager_keuangan
# (core/roles.py). Dipakai `notif_insert` sehingga penulis di berkas LAIN yang
# masih menulis peran fiktif (stok rendah mutasi, rak kritis, shipment) ikut
# sampai ke orang nyata tanpa menunggu tiap berkas diperbaiki.
PHANTOM_ROLE_PORTAL = {
    'warehouse_manager': 'warehouse',
    'manager_production': 'production',
    'production_manager': 'production',
    'finance': 'finance',
}
PHANTOM_ROLES = set(PHANTOM_ROLE_PORTAL)


def _domain_roles(portal: str):
    from core import roles as _r
    return {
        'warehouse': _r.WAREHOUSE_ROLES,
        'production': _r.PRODUCTION_ROLES,
        'hr': _r.HR_ROLES,
        'finance': _r.FINANCE_ROLES,
    }.get(portal)


def alert_roles_for_portal(portal: str) -> List[str]:
    """Peran nyata portal `portal` (PORTAL_ACCESS ∩ peran domain core/roles)."""
    from routes.shared import PORTAL_ACCESS
    base = list(PORTAL_ACCESS.get(portal) or [])
    domain = _domain_roles(portal)
    return sorted({r for r in base if domain is None or r in domain})


def expand_phantom_roles(roles) -> List[str]:
    """Setiap peran fiktif diganti peran nyata portalnya; peran lain tetap."""
    out = set()
    for r in roles or []:
        r = str(r).lower()
        portal = PHANTOM_ROLE_PORTAL.get(r)
        if portal:
            out |= set(alert_roles_for_portal(portal))
        else:
            out.add(r)
    return sorted(out)


def decider_roles(portal: str, can_decide=None, *, keep=('superadmin',)) -> List[str]:
    """2026-11-02 (K30) — penerima notifikasi "Perlu Tindakan": peran NYATA portal `portal`
    (:func:`alert_roles_for_portal`) yang juga lolos gerbang endpoint keputusannya (`can_decide`;
    None = semua peran nyata portal), plus `keep`. Pengaju dikecualikan per orang lewat
    `notif_insert(exclude_user_ids=...)`, bukan dengan membuang perannya."""
    real = set(alert_roles_for_portal(portal))
    if can_decide is not None:
        real &= {str(r).lower() for r in can_decide}
    return sorted(real | set(keep or ()))


def real_target_roles(roles, portal: str, *, keep=('superadmin',)) -> List[str]:
    """Ganti peran fiktif di `roles` dengan peran nyata portal `portal`.

    Dipakai juga untuk pengaturan yang tersimpan di DB (mis.
    `rahaza_alert_settings.alert_target_roles` masih berisi `manager_production`).
    """
    roles = [str(r).lower() for r in (roles or [])]
    out = {r for r in roles if r not in PHANTOM_ROLES}
    if not roles or any(r in PHANTOM_ROLES for r in roles):
        out |= set(alert_roles_for_portal(portal))
    out |= set(keep or ())
    return sorted(out)


# ─────────────────────────────────────────────────────────────────────────────
# CORE INSERT
# ─────────────────────────────────────────────────────────────────────────────

async def notif_insert(
    db,
    *,
    type: str,
    body: str,
    id: Optional[str] = None,
    subtype: Optional[str] = None,
    severity: str = 'info',
    user_id: Optional[str] = None,
    title: Optional[str] = None,
    channel: str = 'in_app',
    recipient: Optional[str] = None,
    target_roles: Optional[List[str]] = None,
    target_user_ids: Optional[List[str]] = None,
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    source_ref: Optional[str] = None,
    client_id: Optional[str] = None,
    host_id: Optional[str] = None,
    meta: Optional[dict] = None,
    status: str = 'queued',
    sent_at: Optional[datetime] = None,
    read: bool = False,
    failed_reason: Optional[str] = None,
    kind: Optional[str] = None,
    action: Optional[dict] = None,
    source_collection: Optional[str] = None,
    resolve: Optional[dict] = None,
    exclude_user_ids: Optional[List[str]] = None,
) -> str:
    """Insert a notification into the SSOT `notifications` collection.

    Returns the new notification id (UUID).

    K30 (2026-11-02): `kind`/`action`/`source_collection`/`resolve` opsional —
    bila kosong diturunkan dari `subtype` (ACTION_SUBTYPES). Sesudah ditulis:
    action lama untuk sumber yang sama ditutup ('superseded') dan action lain
    yang ber-`source_id` sama diperiksa ulang (`resolve_for_source`).

    2026-11-02: `exclude_user_ids` = user yang TIDAK menerima walau perannya ada di
    `target_roles` (pengaju tidak menerima "Perlu Tindakan" atas ajuannya sendiri).
    Disimpan di `meta.exclude_user_ids` dan dihormati aturan audiens tunggal.

    Arguments:
        type:        Domain discriminator. Must be one of VALID_TYPES.
        body:        Main message body. Required.
        id:          Optional pre-allocated UUID (else generated).
        subtype:     Optional sub-classification (event_type, notif_type, etc.)
        severity:    info|success|warning|error
        user_id:     Recipient user id (None for broadcast)
        title:       Optional title/subject
        channel:     Delivery channel: in_app|whatsapp|email|sse
        recipient:   Phone/email when external delivery (whatsapp/email)
        source_*:    Linking info to originating resource
        client_id:   For dewi external client notifs
        host_id:     For marketing_livehost SSE
        meta:        Free-form metadata dict
        status:      queued|sent|failed|read
        sent_at:     Timestamp the notification was actually sent (channel ack)
        read:        Initial read state (default False)
        failed_reason: Error string when status='failed'
    """
    if type not in VALID_TYPES:
        raise ValueError(f'Invalid notification type {type!r}; must be one of {VALID_TYPES}')
    if severity not in VALID_SEVERITIES:
        severity = 'info'
    if channel not in VALID_CHANNELS:
        channel = 'in_app'

    # Target penerima kanonik di `meta` (dibaca `notif_audience_query`). Penulis
    # boleh mengirim lewat argumen ini ATAU lewat meta — keduanya digabung.
    meta = dict(meta or {})
    # 2026-11-02 — id modul mati dipetakan ke id hidup (lihat LINK_MODULE_ALIASES).
    if meta.get('link_module'):
        meta['link_module'] = normalize_link_module(meta['link_module'])
    if target_roles:
        meta['target_roles'] = sorted({str(r).lower() for r in
                                       (list(meta.get('target_roles') or []) + list(target_roles))})
    elif meta.get('target_roles'):
        meta['target_roles'] = sorted({str(r).lower() for r in meta['target_roles']})
    # 2026-11-02 — peran fiktif tidak punya user ⇒ ganti peran nyata portalnya.
    if meta.get('target_roles') and PHANTOM_ROLES & set(meta['target_roles']):
        meta['target_roles'] = expand_phantom_roles(meta['target_roles'])
    if target_user_ids:
        meta['target_user_ids'] = sorted({str(u) for u in
                                          (list(meta.get('target_user_ids') or [])
                                           + list(target_user_ids))})
    if exclude_user_ids:
        meta['exclude_user_ids'] = sorted({str(u) for u in
                                           (list(meta.get('exclude_user_ids') or [])
                                            + [x for x in exclude_user_ids if x])})
    doc = {
        'id':            id or str(uuid.uuid4()),
        'type':          type,
        'subtype':       subtype,
        'severity':      severity,
        'user_id':       user_id,
        'title':         title,
        'body':          body,
        'channel':       channel,
        'recipient':     recipient,
        'source_type':   source_type,
        'source_id':     source_id,
        'source_url':    source_url,
        'source_ref':    source_ref,
        'client_id':     client_id,
        'host_id':       host_id,
        'meta':          meta,
        'status':        status,
        'read':          read,
        'read_at':       None,
        'created_at':    _now(),
        'sent_at':       sent_at,
        'failed_reason': failed_reason,
    }
    doc.update(classify_for_insert(subtype=subtype, kind=kind, action=action,
                                   source_collection=source_collection, resolve=resolve,
                                   source_id=source_id, meta=meta))
    await db.notifications.insert_one(doc)
    # 2026-11-02 (K30) — penutupan otomatis. Best-effort: kegagalan di sini tidak
    # boleh menggagalkan penulis notifikasi (dan transaksi domain di belakangnya).
    try:
        if doc['kind'] == KIND_ACTION:
            await supersede_older_actions(db, doc)
        if source_id:
            await resolve_for_source(db, source_id=source_id, skip_ids=(doc['id'],))
    except Exception:  # noqa: BLE001
        _log.warning('[notif] penutupan otomatis gagal untuk %s', doc['id'], exc_info=True)
    return doc['id']


# ─────────────────────────────────────────────────────────────────────────────
# AUDIENS / RBAC NOTIFIKASI — SATU MESIN untuk semua pembaca (2026-08-07)
#
# MASALAH YANG DIPERBAIKI (audit atas pertanyaan owner "jangan sampai role A
# menerima notifikasi role B"):
#   1. Dua konvensi penerima hidup bersama: penulis lama menaruh
#      `target_roles` / `target_user_ids` di akar dokumen, `publish_notification`
#      menaruhnya di `meta`, dan `notif_insert` memakai `user_id` per orang.
#      Setiap pembaca memakai aturannya sendiri ⇒ ada notifikasi yang tidak
#      pernah tampil, dan ada yang tampil ke orang yang tidak berhak.
#   2. Dokumen TANPA target dianggap "siaran untuk semua" ⇒ satu penulis yang
#      lupa mengisi target langsung membocorkan info lintas role.
#
# ATURAN SEKARANG (dipakai bel, inbox, hitungan belum dibaca, tandai dibaca):
#   penerima  = `user_id` == saya  ATAU  target_user_ids memuat saya
#               ATAU target_roles memuat role saya
#   tanpa target sama sekali = HANYA admin/owner/superadmin
#   status baca: dokumen personal → field `read`; dokumen banyak penerima →
#               `meta.read_by` (per orang, tidak saling menandai)
# ─────────────────────────────────────────────────────────────────────────────

NOTIF_SUPER_ROLES = {'superadmin', 'admin', 'owner'}
_EMPTY = {'$in': [None, []]}


def notif_user_id(user: dict) -> Optional[str]:
    return (user.get('id') or user.get('user_id') or user.get('sub')
            or user.get('email'))


def notif_recipient_or(user: dict) -> list:
    """Klausa $or Mongo: dokumen mana yang ditujukan kepada `user`."""
    uid = notif_user_id(user)
    role = (user.get('role') or '').lower()
    ors: list = [
        {'user_id': uid},
        {'target_user_ids': uid},
        {'meta.target_user_ids': uid},
    ]
    if role:
        ors += [{'target_roles': role}, {'meta.target_roles': role}]
    if role in NOTIF_SUPER_ROLES:
        ors.append({'user_id': None, 'target_user_ids': _EMPTY,
                    'target_roles': _EMPTY, 'meta.target_user_ids': _EMPTY,
                    'meta.target_roles': _EMPTY})
    return ors


def notif_audience_query(user: dict, extra: Optional[dict] = None) -> dict:
    """Query lengkap (audiens + belum dibuang) untuk daftar notifikasi user."""
    q: dict = {
        '$or': notif_recipient_or(user),
        'dismissed': {'$ne': True},
        'meta.dismissed': {'$ne': True},
    }
    uid = notif_user_id(user)
    if uid:
        # 2026-11-02 — pengaju dikecualikan dari action atas ajuannya sendiri
        q['meta.exclude_user_ids'] = {'$ne': uid}
    if extra:
        q.update(extra)
    return q


def notif_visible_to(doc: dict, user: dict) -> bool:
    """Versi Python dari aturan audiens (untuk filter setelah query)."""
    if not doc:
        return False
    uid = notif_user_id(user)
    role = (user.get('role') or '').lower()
    meta = doc.get('meta') or {}
    if uid and uid in (meta.get('exclude_user_ids') or []):
        return False
    if doc.get('user_id'):
        return doc.get('user_id') == uid
    users = list(doc.get('target_user_ids') or []) + list(meta.get('target_user_ids') or [])
    roles = [str(r).lower() for r in
             (list(doc.get('target_roles') or []) + list(meta.get('target_roles') or []))]
    if uid in users or role in roles:
        return True
    if not users and not roles:
        return role in NOTIF_SUPER_ROLES
    return False


def notif_is_unread_for(doc: dict, user: dict) -> bool:
    """Belum dibaca oleh user ini (personal: `read`; bersama: `meta.read_by`)."""
    uid = notif_user_id(user)
    meta = doc.get('meta') or {}
    if doc.get('user_id'):
        return not doc.get('read')
    read_by = list(meta.get('read_by') or []) + list(doc.get('read_by') or [])
    return uid not in read_by


async def notif_mark_read_for(db, notif_id: str, user: dict) -> bool:
    """Tandai dibaca HANYA untuk user ini (tidak menandai penerima lain)."""
    uid = notif_user_id(user)
    doc = await db.notifications.find_one({'id': notif_id}, {'_id': 0})
    if not doc or not notif_visible_to(doc, user):
        return False
    if doc.get('user_id'):
        res = await db.notifications.update_one(
            {'id': notif_id, 'user_id': uid},
            {'$set': {'read': True, 'read_at': _now()}})
        return res.matched_count > 0
    res = await db.notifications.update_one(
        {'id': notif_id}, {'$addToSet': {'meta.read_by': uid}})
    return res.matched_count > 0


async def notif_mark_all_read_for(db, user: dict, *, type: Optional[str] = None) -> int:
    """Tandai semua notifikasi milik user (personal + bersama) sebagai dibaca."""
    uid = notif_user_id(user)
    extra = {'type': type} if type else None
    # 2026-11-02 — tanpa batas 2000: "tandai semua" harus benar-benar semua.
    rows = await db.notifications.find(
        notif_audience_query(user, extra), _UNREAD_PROJECTION).to_list(None)
    personal = [r['id'] for r in rows if r.get('user_id') and notif_is_unread_for(r, user)]
    shared = [r['id'] for r in rows if not r.get('user_id') and notif_is_unread_for(r, user)]
    n = 0
    if personal:
        res = await db.notifications.update_many(
            {'id': {'$in': personal}}, {'$set': {'read': True, 'read_at': _now()}})
        n += res.modified_count
    if shared:
        res = await db.notifications.update_many(
            {'id': {'$in': shared}}, {'$addToSet': {'meta.read_by': uid}})
        n += res.modified_count
    return n


# Proyeksi minimum untuk menghitung status baca (tanpa body/judul).
_UNREAD_PROJECTION = {'_id': 0, 'id': 1, 'user_id': 1, 'read': 1, 'read_by': 1,
                      'meta.read_by': 1}


async def notif_count_unread_for(db, user: dict, *, type: Optional[str] = None) -> int:
    """Jumlah belum dibaca yang SEBENARNYA.

    2026-11-02 — dulu `to_list(2000)` (dan bel memakai jendela 200 dokumen) ⇒
    angka terpotong. Sekarang seluruh dokumen audiens dihitung dengan proyeksi
    ringan, jadi angka bel = angka Portal Saya = jumlah nyata.
    """
    # 2026-11-02 (K30) — action yang sudah tertutup pindah ke riwayat: tidak dihitung.
    extra = {'resolved_at': None, **({'type': type} if type else {})}
    n = 0
    async for r in db.notifications.find(notif_audience_query(user, extra), _UNREAD_PROJECTION):
        if notif_is_unread_for(r, user):
            n += 1
    return n


async def notif_list_for(db, user: dict, *, type: Optional[str] = None,
                         severity: Optional[str] = None, unread_only: bool = False,
                         limit: int = 50, skip: int = 0) -> list:
    """Daftar notifikasi yang BOLEH dilihat user (audiens ditegakkan di query)."""
    extra: dict = {}
    if type:
        extra['type'] = type
    if severity:
        extra['severity'] = severity
    rows = await (db.notifications.find(notif_audience_query(user, extra), {'_id': 0})
                  .sort('created_at', -1).skip(skip).limit(limit * 3 if unread_only else limit)
                  ).to_list(limit * 3 if unread_only else limit)
    if unread_only:
        rows = [r for r in rows if notif_is_unread_for(r, user)][:limit]
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# READ/COUNT/UPDATE
# ─────────────────────────────────────────────────────────────────────────────

async def notif_mark_read(db, notif_id: str, *, user_id: Optional[str] = None) -> bool:
    """Mark a notification as read. Returns True if a doc was updated.

    For single-recipient notifs (user_id-scoped), pass user_id for safety.
    For multi-recipient rahaza notifs, use update_meta to push to read_by[].
    """
    flt: dict = {'id': notif_id}
    if user_id:
        flt['user_id'] = user_id
    res = await db.notifications.update_one(
        flt,
        {'$set': {'read': True, 'read_at': _now()}},
    )
    return res.modified_count > 0


async def notif_count_unread(
    db, *, user_id: Optional[str] = None, type: Optional[str] = None,
) -> int:
    flt: dict = {'read': False}
    if user_id:
        flt['user_id'] = user_id
    if type:
        flt['type'] = type
    return await db.notifications.count_documents(flt)


async def notif_list(
    db,
    *,
    user_id: Optional[str] = None,
    type: Optional[str] = None,
    severity: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 50,
    skip: int = 0,
) -> list:
    flt: dict = {}
    if user_id:
        flt['user_id'] = user_id
    if type:
        flt['type'] = type
    if severity:
        flt['severity'] = severity
    if unread_only:
        flt['read'] = False
    cursor = (
        db.notifications
        .find(flt, {'_id': 0})
        .sort('created_at', -1)
        .skip(skip)
        .limit(limit)
    )
    return [doc async for doc in cursor]


async def notif_find_one(db, flt: dict) -> Optional[dict]:
    """Get a single notif by arbitrary filter (excludes _id)."""
    return await db.notifications.find_one(flt, {'_id': 0})


async def notif_update_one(db, flt: dict, update: dict) -> int:
    """Apply a Mongo update operator on a single notif. Returns modified count."""
    res = await db.notifications.update_one(flt, update)
    return res.modified_count


async def notif_update_many(db, flt: dict, update: dict) -> int:
    """Apply a Mongo update on multiple notifs. Returns modified count."""
    res = await db.notifications.update_many(flt, update)
    return res.modified_count


async def notif_delete_one(db, flt: dict) -> int:
    """Delete a single notif. Returns delete count."""
    res = await db.notifications.delete_one(flt)
    return res.deleted_count


# ─────────────────────────────────────────────────────────────────────────────
# SERIALIZE
# ─────────────────────────────────────────────────────────────────────────────

def serialize_notif(doc: Any) -> dict:
    """Return a JSON-safe shallow copy (datetimes → ISO strings)."""
    if doc is None:
        return None  # type: ignore
    out = dict(doc)
    out.pop('_id', None)
    for k, v in out.items():
        if isinstance(v, datetime):
            out[k] = iso_utc(v)   # 2026-11-02 — selalu ber-zona (lihat iso_utc)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# BACKWARD-COMPAT RESHAPE HELPERS
# Each helper converts an SSOT doc back into the legacy router's response
# schema so frontend clients continue to receive the same shape.
# ─────────────────────────────────────────────────────────────────────────────

def reshape_as_dewi(doc: dict) -> dict:
    """Reshape SSOT doc → legacy `dewi_notifications` schema."""
    if not doc:
        return {}
    out = dict(doc)
    out.pop('_id', None)
    meta = out.get('meta') or {}
    # Legacy field projection
    return {
        'id':            out.get('id'),
        'channel':       out.get('channel'),
        'recipient':     out.get('recipient'),
        'subject':       out.get('title'),
        'body':          out.get('body'),
        'event_type':    out.get('subtype'),
        'source_ref':    out.get('source_ref'),
        'client_id':     out.get('client_id'),
        'status':        out.get('status'),
        'meta':          {k: v for k, v in meta.items() if k not in ('sent_real', 'sent_mock')},
        'sent_real':     meta.get('sent_real', False),
        'sent_mock':     meta.get('sent_mock', False),
        'created_at':    _to_iso(out.get('created_at')),
        'sent_at':       _to_iso(out.get('sent_at')),
        'failed_reason': out.get('failed_reason'),
    }


def reshape_as_rahaza(doc: dict, *, current_user_id: Optional[str] = None) -> dict:
    """Reshape SSOT doc → legacy `rahaza_notifications` schema.

    Multi-recipient fields (target_roles, target_user_ids, read_by, dismissed,
    dedup_key) are stored in `meta` and reprojected to top-level.
    """
    if not doc:
        return {}
    out = dict(doc)
    out.pop('_id', None)
    meta = out.get('meta') or {}
    read_by = meta.get('read_by') or []
    shaped = {
        'id':              out.get('id'),
        'type':            out.get('subtype'),
        'severity':        out.get('severity'),
        'title':           out.get('title'),
        'message':         out.get('body'),
        'link_module':     meta.get('link_module'),
        'link_id':         out.get('source_id'),
        'target_roles':    meta.get('target_roles') or [],
        'target_user_ids': meta.get('target_user_ids') or [],
        'dedup_key':       meta.get('dedup_key'),
        'read_by':         read_by,
        'dismissed':       bool(meta.get('dismissed', False)),
        'created_at':      _to_iso(out.get('created_at')),
    }
    if current_user_id is not None:
        shaped['read'] = current_user_id in read_by
    return shaped


def reshape_as_collab(doc: dict) -> dict:
    """Reshape SSOT doc → legacy `collab_notifications` schema."""
    if not doc:
        return {}
    out = dict(doc)
    out.pop('_id', None)
    meta = out.get('meta') or {}
    return {
        'notification_id': out.get('id'),
        'user_id':         out.get('user_id'),
        'type':            out.get('subtype'),
        'icon':            meta.get('icon'),
        'title':           out.get('title'),
        'content':         out.get('body'),
        'source_type':     out.get('source_type'),
        'source_id':       out.get('source_id'),
        'source_url':      out.get('source_url'),
        'metadata':        {k: v for k, v in meta.items() if k != 'icon'},
        'read':            bool(out.get('read', False)),
        'read_at':         _to_iso(out.get('read_at')),
        'created_at':      _to_iso(out.get('created_at')),
    }


def reshape_as_livehost(doc: dict) -> dict:
    """Reshape SSOT doc → legacy `marketing_livehost_notifications` schema."""
    if not doc:
        return {}
    out = dict(doc)
    out.pop('_id', None)
    return {
        'id':         out.get('id'),
        'host_id':    out.get('host_id'),
        'type':       out.get('subtype'),
        'severity':   out.get('severity'),
        'title':      out.get('title'),
        'message':    out.get('body'),
        'link':       out.get('source_url'),
        'read':       bool(out.get('read', False)),
        'read_at':    _to_iso(out.get('read_at')),
        'created_at': _to_iso(out.get('created_at')),
    }


def _to_iso(v: Any) -> Optional[str]:
    """Convert datetime → ISO string; pass-through strings/None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return iso_utc(v)   # 2026-11-02 — selalu ber-zona (lihat iso_utc)
    return v


# ─────────────────────────────────────────────────────────────────────────────
# RAHAZA — multi-recipient helpers (read_by[], dedup, target filtering)
# ─────────────────────────────────────────────────────────────────────────────

async def rahaza_check_dedup(
    db, *, dedup_key: str, within_minutes: int = 10,
) -> Optional[dict]:
    """Check if an active rahaza notif with same dedup_key was created recently."""
    from datetime import timedelta
    if not dedup_key:
        return None
    since = _now() - timedelta(minutes=within_minutes)
    return await db.notifications.find_one({
        'type': 'rahaza',
        'meta.dedup_key': dedup_key,
        'meta.dismissed': {'$ne': True},
        # 2026-11-02 (K30) — action yang sudah tertutup (mis. stok sempat normal)
        # tidak menahan kabar baru bila kondisinya terulang di hari yang sama.
        'resolved_at': None,
        'created_at': {'$gte': since},
    })


async def rahaza_mark_read_by(db, notif_id: str, user_id: str) -> int:
    """Add user_id to meta.read_by[] for a rahaza notif. Returns modified count."""
    res = await db.notifications.update_one(
        {'id': notif_id, 'type': 'rahaza'},
        {'$addToSet': {'meta.read_by': user_id}},
    )
    return res.modified_count


async def rahaza_mark_read_by_many(
    db, notif_ids: List[str], user_id: str,
) -> int:
    """Mark a batch of rahaza notifs as read by user."""
    if not notif_ids:
        return 0
    res = await db.notifications.update_many(
        {'id': {'$in': notif_ids}, 'type': 'rahaza'},
        {'$addToSet': {'meta.read_by': user_id}},
    )
    return res.modified_count


def rahaza_matches_user(notif: dict, user: dict) -> bool:
    """Return True if a rahaza notif (SSOT shape) is visible to user.

    2026-08-07: memakai aturan audiens tunggal (`notif_visible_to`). Dokumen
    tanpa target TIDAK lagi tampil ke semua role — hanya admin/owner.
    """
    return notif_visible_to(notif, user)
