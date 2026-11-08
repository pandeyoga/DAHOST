"""
Dashboard, Global Search, Vendor Dashboard
Extracted from server.py monolith.
"""
# ruff: noqa: E741
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import (require_auth, serialize_doc)
from routes.shared import now, parse_date, to_end_of_day, get_pagination_params, paginated_response
from core import product_master as pm  # T1: SATU definisi "model masih hidup"
import logging
from datetime import datetime, timezone, timedelta, date
import re
from utils.waktu import today_wib

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dashboard"])


# ─── HELPERS ─────────────────────────────────────────────────────────────────
async def _sum_field(db, collection, query: dict, field: str) -> float:
    agg = await db[collection].aggregate([
        {'$match': query},
        {'$group': {'_id': None, 'total': {'$sum': f'${field}'}}}
    ]).to_list(2)
    return agg[0]['total'] if agg else 0.0


# 2026-11-02 (audit No.50): status yang BUKAN faktur/tagihan nyata — draft belum terbit, batal/void
# tidak pernah terjadi. Dulu dashboard menjumlah semua dokumen (pendapatan 3,4× faktur terbit).
NOT_REAL_STATUSES = ('draft', 'cancelled', 'void')
AR_OPEN_STATUSES = ('issued', 'sent', 'partial_paid', 'overdue')


def ar_aging_buckets_from_canonical(aging: dict) -> dict:
    """Bucket /api/rahaza/ar-aging (SATU sumber) → kunci yang dibaca layar Dashboard Eksekutif."""
    b = (aging or {}).get('buckets') or {}
    return {
        'current': round(float(b.get('current') or 0) + float(b.get('tanpa_jatuh_tempo') or 0), 2),
        'd30': round(float(b.get('1_30') or 0), 2),
        'd60': round(float(b.get('31_60') or 0), 2),
        'd90': round(float(b.get('61_90') or 0), 2),
        'd90plus': round(float(b.get('90_plus') or 0), 2),
        'noDueDate': round(float(b.get('tanpa_jatuh_tempo') or 0), 2),
        'total': round(float((aging or {}).get('total') or 0), 2),
    }


async def _ar_aging(db) -> dict:
    """2026-11-02: aging dari faktur nyata lewat fungsi yang SAMA dengan /api/rahaza/ar-aging
    (status kanonik issued/partial_paid/overdue). Dulu memakai status 'sent'/'partial' yang
    tidak lagi ditulis → selalu 0."""
    from routes.rahaza_ar_canonical import compute_ar_aging
    return ar_aging_buckets_from_canonical(await compute_ar_aging(db))


def revenue_windows(ar_invoices: list, today: date) -> dict:
    """Pendapatan hari ini / MTD / YTD per TANGGAL FAKTUR (`issue_date`, hari WIB) — bukan
    `created_at` (tanggal input, batas hari UTC). Hanya faktur nyata."""
    t = today.isoformat()
    m0 = today.replace(day=1).isoformat()
    y0 = today.replace(month=1, day=1).isoformat()
    out = {'today': 0.0, 'mtd': 0.0, 'ytd': 0.0}
    for i in ar_invoices:
        if (i.get('status') or 'draft') in NOT_REAL_STATUSES:
            continue
        d = str(i.get('issue_date') or '')[:10]
        if not d:
            continue
        v = float(i.get('total') or 0)
        if d == t:
            out['today'] += v
        if m0 <= d <= t:
            out['mtd'] += v
        if y0 <= d <= t:
            out['ytd'] += v
    return {k: round(v, 2) for k, v in out.items()}


_BULAN = ('Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des')


def last_months(today: date, n: int = 6) -> list:
    """`n` bulan terakhir (termasuk bulan ini) → [(ym 'YYYY-MM', label 'Nov 26')] urut lama → baru."""
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append((f'{y:04d}-{m:02d}', f'{_BULAN[m - 1]} {y % 100:02d}'))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def po_deadline_rows(pos: list, today: date) -> dict:
    """PO produksi terbuka (bukan draf/selesai/batal) yang lewat tenggat & yang tenggatnya < 3 hari lagi.

    8 Nov 2026: dulu dari koleksi pesanan lama `rahaza_orders` (kosong). Tenggat = `deadline` atau
    `delivery_deadline` PO; lewat tenggat = tenggat SEBELUM hari ini (WIB)."""
    from services.mgmt_analytics import PO_CANCELLED, PO_DONE, PO_DRAFT, as_iso_date
    t = today.isoformat()
    soon = (today + timedelta(days=3)).isoformat()
    overdue, near = [], []
    for p in pos:
        s = (p.get('status') or '').strip().lower()
        if s in PO_DRAFT or s in PO_DONE or s in PO_CANCELLED:
            continue
        due = as_iso_date(p.get('deadline') or p.get('delivery_deadline'))
        if not due:
            continue
        row = {'id': p.get('id'), 'po_number': p.get('po_number', ''), 'customer_name': p.get('customer_name', ''),
               'vendor_name': p.get('vendor_name', ''), 'status': p.get('status', ''),
               'business_type': p.get('business_type', ''), 'deadline': due, 'due_date': due}
        if due < t:
            overdue.append(row)
        elif due < soon:
            near.append(row)
    overdue.sort(key=lambda r: r['deadline'])
    near.sort(key=lambda r: r['deadline'])
    return {'overdue': overdue, 'near': near}


@router.get("/dashboard")
async def get_dashboard(request: Request):
    """Dashboard Eksekutif — KPI ringkasan dengan data today/MTD/YTD."""
    await require_auth(request)
    db = get_db()
    today = today_wib()

    # ── PO produksi — 8 Nov 2026 (keputusan owner): sumber SAMA dengan Ringkasan Bisnis / layar PO produksi
    # (`production_pos` lewat `services.mgmt_analytics.domain_scope`). Dulu koleksi pesanan lama `rahaza_orders`
    # (pra-migrasi, 0 dokumen) → PO, PO berjalan, ketepatan kirim, PO terlambat & tren selalu 0.
    from services.mgmt_analytics import (as_iso_date, domain_scope, on_time_stats, output_in_period,
                                         output_sources, po_buckets)
    sc = await domain_scope(db, 'all')
    buckets = po_buckets(sc['pos'])
    total_orders = buckets['total']
    active_orders = buckets['running']
    completed_orders = buckets['done']
    deadline_rows = po_deadline_rows(sc['pos'], today)

    # Work Orders — T-03 (FASE 3): SSOT production_jobs via core.wo_reader
    from core.wo_reader import status_counts
    _wo_counts = await status_counts(db)
    active_wos = _wo_counts.get('released', 0) + _wo_counts.get('in_progress', 0)
    wo_status_agg = [{'_id': k, 'count': v} for k, v in _wo_counts.items()]

    # ── AR / AP (Rahaza finance) ──
    # 2026-11-02 (audit No.50): hanya faktur nyata (tanpa draft/batal/void).
    _real = {'status': {'$nin': list(NOT_REAL_STATUSES)}}
    ar_invoices = await db.rahaza_ar_invoices.find(_real, {'_id': 0}).to_list(500)
    ap_invoices = await db.rahaza_ap_invoices.find(_real, {'_id': 0}).to_list(500)
    total_revenue = sum(i.get('total', 0) for i in ar_invoices)
    total_paid_ar = sum(i.get('paid_amount', 0) for i in ar_invoices)
    outstanding_ar = sum(i.get('balance', 0) for i in ar_invoices if i.get('status') not in ('paid', 'written_off'))
    total_vendor_cost = sum(i.get('total', 0) for i in ap_invoices)
    total_paid_ap = sum(i.get('paid_amount', 0) for i in ap_invoices)
    outstanding_ap = sum(i.get('balance', 0) for i in ap_invoices if i.get('status') != 'paid')
    gross_margin = total_revenue - total_vendor_cost

    # ── Shipments — RC-03/RC-DASH-DECISION: pengiriman pelanggan = wh_delivery_notes
    # (rahaza_shipments = koleksi dorman/kosong, self-consistent tapi tak dipakai flow)
    pending_shipments = await db.wh_delivery_notes.count_documents({'status': {'$in': ['draft', 'issued']}})

    # ── PO terlambat (tenggat lewat, belum selesai) ──
    today_iso = today.isoformat()
    delayed_orders = len(deadline_rows['overdue'])

    # ── Revenue Today / MTD / YTD (from rahaza AR invoices — SSOT) ──
    # NOTE: legacy `invoices` collection was DROPPED in Session #11.16 Phase B.
    # Revenue now reads exclusively from rahaza_ar_invoices (SSOT).
    # See FORENSIC_04 Cluster 5 + FORENSIC_12 GAP-01.
    # 2026-11-02 (audit No.50): per tanggal faktur & hari WIB (dulu created_at, batas UTC).
    _rev = revenue_windows(ar_invoices, today_wib())
    revenue_today, revenue_mtd, revenue_ytd = _rev['today'], _rev['mtd'], _rev['ytd']

    # ── Karyawan aktif — 8 Nov 2026: data karyawan memakai `active: true` (sama dengan Ringkasan Bisnis
    # `hr.employees_active`). Dulu `status: active` (tidak dipakai) lalu jatuh ke jumlah AKUN pengguna (48 vs 24).
    active_employees = await db.rahaza_employees.count_documents({'active': True})

    # ── Attendance today — RC-01/RC-03: SSOT live rahaza_attendance_events
    # (fallback dewi_attendance dihapus: phantom tanpa writer)
    att_today_ids = await db.rahaza_attendance_events.distinct(
        'employee_id', {'date': today_iso, 'status': {'$in': ['hadir', 'present']}})
    att_today = len(att_today_ids)
    attendance_today_pct = min(100, round((att_today / active_employees * 100) if active_employees else 0))

    # ── AR aging ──
    ar_aging = await _ar_aging(db)

    # ── OEE — FASE 4 (E10 DELETE): engine rahaza_oee/line diarsip → metrik OEE null
    avg_oee = None

    # ── Ketepatan kirim (90 hari) — SAMA dengan /api/rahaza/management/on-time-delivery ──
    on_time_rate = round((await on_time_stats(db, sc, 90))['rate_pct'])

    # ── Data 6 bulan: PO dibuat (production_pos) + output produksi (SAMA dengan Ringkasan Bisnis:
    # progres internal + penerimaan dari CMT, `services.mgmt_analytics.output_sources`) ──
    out_src = await output_sources(db, sc)
    monthly_data = []
    for ym, label in last_months(today, 6):
        monthly_data.append({
            'month': label,
            'pos': sum(1 for p in sc['pos'] if as_iso_date(p.get('created_at') or p.get('po_date'))[:7] == ym),
            'production': output_in_period(out_src, f'{ym}-01', f'{ym}-31')['total'],
        })

    # ── User count ──
    total_users = await db.users.count_documents({'status': 'active'})

    # ── Alerts: PO lewat tenggat, mendekati tenggat (production_pos), faktur belum dibayar ──
    overdue_orders = deadline_rows['overdue'][:5]
    near_deadline_orders = deadline_rows['near'][:5]
    unpaid_ars = await db.rahaza_ar_invoices.find(
        {'status': {'$in': list(AR_OPEN_STATUSES)}, 'balance': {'$gt': 0}}, {'_id': 0}
    ).sort('due_date', 1).limit(5).to_list(500)  # 2026-11-02: status kanonik

    return {
        'totalPOs': total_orders, 'activePOs': active_orders,
        'garments': await db.rahaza_models.count_documents(pm.LIVE_MODEL_FILTER),
        # T1 — hitungan produk BERHENTI bergantung `active: True` semata. Dokumen
        # hasil promosi R&D lama hanya punya `status: 'active'`; dulu tidak ikut
        # terhitung ⇒ dashboard bilang 1, daftar model bilang 2.
        'products': await db.rahaza_models.count_documents(pm.LIVE_MODEL_FILTER),
        'totalInvoiced': total_revenue + total_vendor_cost,
        'totalPaid': total_paid_ar + total_paid_ap,
        'outstanding': outstanding_ar + outstanding_ap,
        'totalVendorCost': total_vendor_cost,
        'totalRevenue': total_revenue,
        'grossMargin': gross_margin,
        'totalInvoicedAR': total_revenue, 'totalInvoicedAP': total_vendor_cost,
        'outstandingAR': outstanding_ar, 'outstandingAP': outstanding_ap,
        'totalPaidAR': total_paid_ar, 'totalPaidAP': total_paid_ap,
        'activeJobs': active_wos,
        'pendingShipments': pending_shipments,
        'pendingAdditionalRequests': 0,
        'pendingReplacementRequests': 0,
        'pendingReturns': 0,
        'totalBuyerShipments': await db.wh_delivery_notes.count_documents({'status': {'$in': ['issued', 'received']}}),
        'totalVendorShipments': 0,
        'totalProducedGlobal': 0,
        'totalAvailableGlobal': 0,
        'globalProgressPct': round((completed_orders / total_orders * 100) if total_orders else 0),
        'totalAccessories': await db.rahaza_materials.count_documents({'type': 'accessory', 'active': True}),
        'totalAccShipments': 0,
        'pendingAccInspections': 0,
        'pendingAccRequests': 0,
        # 2026-11-02: status kanonik (dulu 'sent'/'partial' yang tidak lagi ditulis → selalu 0)
        'unpaidInvoices': sum(1 for i in ar_invoices if i.get('status') in ('issued', 'sent', 'overdue')
                              and float(i.get('balance') or 0) > 0),
        'partialInvoices': sum(1 for i in ar_invoices if i.get('status') == 'partial_paid'),
        'delayedPOs': delayed_orders,
        'monthlyData': monthly_data,
        'woStatus': wo_status_agg,
        'topGarments': [],
        'pendingReminders': 0,
        'onTimeRate': on_time_rate,
        'totalUsers': total_users,
        # ── NEW: Real-time Executive KPIs ──
        'revenueToday': revenue_today,
        'revenueMTD': revenue_mtd,
        'revenueYTD': revenue_ytd,
        'activeEmployees': active_employees,
        'attendanceTodayCount': att_today,
        'attendanceTodayPct': attendance_today_pct,
        'avgOEE': avg_oee,
        'arAging': ar_aging,
        'alerts': {
            'overduePos': serialize_doc(overdue_orders),
            'nearDeadlinePos': serialize_doc(near_deadline_orders),
            'unpaidInvoices': serialize_doc(unpaid_ars),
        },
    }


def weekly_output(src: dict, today: date, weeks: int = 8) -> list:
    """Output produksi `weeks` minggu terakhir (7 hari per minggu, minggu terakhir berakhir hari ini WIB)."""
    from services.mgmt_analytics import output_in_period
    out = []
    for w in range(weeks - 1, -1, -1):
        end = today - timedelta(days=w * 7)
        start = end - timedelta(days=6)
        out.append({'week': f"W{weeks - w}", 'label': start.strftime('%d/%m'),
                    'qty': output_in_period(src, start.isoformat(), end.isoformat())['total']})
    return out


def _in_range(val, start: datetime, end: datetime) -> bool:
    """Check if a datetime value (or ISO string) is in [start, end)."""
    if isinstance(val, datetime):
        dt = val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    else:
        try:
            s = str(val).replace('Z', '+00:00')
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return False
    return start <= dt < end


@router.get("/dashboard/analytics")
async def get_dashboard_analytics(request: Request):
    """Enhanced analytics with date range filter"""
    await require_auth(request)
    db = get_db()
    sp = request.query_params
    date_from = parse_date(sp.get('from'))
    date_to = to_end_of_day(sp.get('to'))
    date_filter = {}
    if date_from:
        date_filter['$gte'] = date_from
    if date_to:
        date_filter['$lte'] = date_to
    date_q = {'created_at': date_filter} if date_filter else {}
    # Vendor lead times — RC-04: SSOT warehouse_receiving (join rahaza_purchase_orders
    # by po_number; lead = tanggal terima - po_date). vendor_shipments = subsistem legacy kosong.
    vendor_lead_times = []
    recvs = await db.warehouse_receiving.find(
        {**date_q, 'status': {'$in': ['received', 'accepted', 'partial_received']}},
        {'_id': 0, 'supplier_name': 1, 'po_number': 1, 'created_at': 1}).to_list(500)
    po_numbers = [r['po_number'] for r in recvs if r.get('po_number')]
    pos_map = {}
    if po_numbers:
        async for p in db.rahaza_purchase_orders.find(
                {'po_number': {'$in': po_numbers}}, {'_id': 0, 'po_number': 1, 'po_date': 1}):
            pos_map[p['po_number']] = p.get('po_date')
    vendor_lt_map = {}
    for r in recvs:
        vn = r.get('supplier_name', 'Unknown')
        po_date = pos_map.get(r.get('po_number'))
        recv_at = r.get('created_at')
        if not po_date or not recv_at:
            continue
        try:
            recv_d = recv_at.date() if isinstance(recv_at, datetime) else date.fromisoformat(str(recv_at)[:10])
            delta = (recv_d - date.fromisoformat(str(po_date)[:10])).days
        except Exception:
            continue
        if delta >= 0:
            vendor_lt_map.setdefault(vn, []).append(delta)
    for vn, days_list in sorted(vendor_lt_map.items()):
        avg_lt = round(sum(days_list) / len(days_list), 1) if days_list else 0
        vendor_lead_times.append({'vendor': vn, 'avg_days': avg_lt, 'shipment_count': len(days_list)})
    # Missing/defect rates by vendor — RC-04: SSOT rahaza_grn_inspections
    # (field: supplier_name/total_received_qty/total_rejected_qty)
    all_inspections = await db.rahaza_grn_inspections.find(date_q, {'_id': 0}).to_list(500)
    vendor_defect_map = {}
    for insp in all_inspections:
        vn = insp.get('supplier_name', 'Unknown')
        if vn not in vendor_defect_map:
            vendor_defect_map[vn] = {'received': 0, 'missing': 0}
        vendor_defect_map[vn]['received'] += insp.get('total_received_qty', 0) or 0
        vendor_defect_map[vn]['missing'] += insp.get('total_rejected_qty', 0) or 0
    defect_rates = []
    for vn, vals in sorted(vendor_defect_map.items()):
        total = vals['received'] + vals['missing']
        rate = round((vals['missing'] / total * 100) if total > 0 else 0, 1)
        defect_rates.append({'vendor': vn, 'missing_rate': rate, 'total_received': vals['received'], 'total_missing': vals['missing']})
    # Output produksi per minggu — 8 Nov 2026 (keputusan owner): sumber SAMA dengan Ringkasan Bisnis
    # (`services.mgmt_analytics.output_sources`: progres internal + penerimaan dari CMT). Dulu `rahaza_wip_events`.
    from services.mgmt_analytics import domain_scope, output_sources
    weekly_throughput = weekly_output(await output_sources(db, await domain_scope(db, 'all')), today_wib())
    n = now()
    # Production completion rate by product — T-03 (FASE 3): SSOT production_jobs via core.wo_reader
    from core.wo_reader import load_wos
    _all_wos = await load_wos(db)
    _by_model: dict = {}
    for w in _all_wos:
        b = _by_model.setdefault(w.get('model_name') or 'Unknown', {'a': 0, 'p': 0})
        b['a'] += w.get('qty') or 0
        b['p'] += w.get('completed_qty') or 0
    product_comp = sorted([{'product': k, 'available': v['a'], 'produced': v['p'],
                            'rate': round((v['p'] / v['a'] * 100) if v['a'] > 0 else 0, 1)}
                           for k, v in _by_model.items()], key=lambda x: -x['available'])[:10]
    # Shipment/receiving status breakdown — RC-04: SSOT warehouse_receiving
    ship_status_agg = await db.warehouse_receiving.aggregate([
        {'$group': {'_id': '$status', 'count': {'$sum': 1}}}
    ]).to_list(20)
    # WO deadline distribution — T-03: due_date dari job/PO (string ISO)
    all_pos = [{'due_date': w.get('due_date'), 'wo_number': w.get('wo_number')}
               for w in _all_wos if w['status'] not in ('completed', 'cancelled')]
    overdue_count = 0
    this_week_count = 0
    next_week_count = 0
    later_count = 0
    for p in all_pos:
        dl = p.get('due_date')
        if not dl:
            continue
        if isinstance(dl, str):
            dl = parse_date(dl)
        if not isinstance(dl, datetime):
            continue
        # Ensure timezone-aware comparison
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)
        if dl < n:
            overdue_count += 1
        elif dl < n + timedelta(days=7):
            this_week_count += 1
        elif dl < n + timedelta(days=14):
            next_week_count += 1
        else:
            later_count += 1
    return {
        'vendorLeadTimes': vendor_lead_times,
        'defectRates': defect_rates,
        'weeklyThroughput': weekly_throughput,
        'productCompletion': product_comp,
        'shipmentStatus': [{'status': s['_id'] or 'Unknown', 'count': s['count']} for s in ship_status_agg],
        'deadlineDistribution': {
            'overdue': overdue_count, 'thisWeek': this_week_count,
            'nextWeek': next_week_count, 'later': later_count
        }
    }


# ─── VENDOR DASHBOARD ────────────────────────────────────────────────────────
@router.get("/vendor/dashboard")
async def get_vendor_dashboard(request: Request):
    """Dashboard vendor CMT (modul 1 dari 11).

    ── Portal CMT Override (2026-08-08) ─────────────────────────────────────
    Dulu endpoint ini melempar 403 KERAS untuk semua non-vendor, sehingga staf
    DA yang mengisi atas nama vendor "tidak pakai sistem" mentok di pintu
    pertama. Sekarang staf berhak (lihat core/cmt_override.OVERRIDE_ROLES) boleh
    membacanya dengan header `X-CMT-Override-Vendor`, dan HANYA untuk vendor itu.

    `recentProgress` & `alerts` dulu dikembalikan KOSONG PERMANEN (list hard-code)
    padahal frontend VendorDashboard.jsx merendernya — jadi dua panel di layar
    vendor selalu kosong tanpa alasan. Sekarang diisi dari data sungguhan.
    """
    user = await require_auth(request)
    from routes.production_rbac import is_vendor, vendor_identity
    from core.cmt_override import resolve_override
    db = get_db()
    ctx = await resolve_override(request, user, db)
    if is_vendor(user):
        vendor_id = vendor_identity(user)
    else:
        if not ctx:
            raise HTTPException(
                403,
                'Dashboard vendor hanya untuk akun vendor CMT, atau staf DA yang '
                'membuka Portal CMT Override (pilih vendor dulu).')
        vendor_id = ctx['vendor_id']
    jobs = await db.production_jobs.find({'vendor_id': vendor_id}, {'_id': 0}).sort('created_at', -1).to_list(500)
    active_jobs = len([j for j in jobs if j.get('status') == 'In Progress' and not j.get('parent_job_id')])
    completed_jobs = len([j for j in jobs if j.get('status') == 'Completed'])
    incoming = await db.vendor_shipments.count_documents({'vendor_id': vendor_id, 'status': 'Sent'})
    all_job_ids = [j['id'] for j in jobs]
    all_job_items = await db.production_job_items.find({'job_id': {'$in': all_job_ids}}).to_list(500) if all_job_ids else []
    total_produced = sum(i.get('produced_qty', 0) for i in all_job_items)
    total_available = sum(i.get('available_qty', i.get('shipment_qty', 0)) for i in all_job_items)

    # ── recentProgress: 10 setoran progress terakhir milik vendor ini ────────
    recent_progress = []
    if all_job_ids:
        job_num_map = {j['id']: j.get('job_number', '') for j in jobs}
        rows = await db.production_progress.find(
            {'job_id': {'$in': all_job_ids}}, {'_id': 0}
        ).sort('progress_date', -1).to_list(10)
        for r in rows:
            recent_progress.append({
                'id': r.get('id'),
                'job_number': job_num_map.get(r.get('job_id'), ''),
                'sku': r.get('sku', ''),
                'product_name': r.get('product_name', ''),
                'completed_quantity': r.get('completed_quantity', 0),
                'progress_date': serialize_doc(r.get('progress_date')),
                'recorded_by': r.get('recorded_by', ''),
                # keputusan 3a — badge "diinput staf DA" juga di dashboard vendor
                'entered_by_staff': r.get('entered_by_staff') is True,
                'entered_by': r.get('entered_by', ''),
            })

    # ── alerts: job telat & job mendekati tenggat (7 hari) ───────────────────
    _now = datetime.now(timezone.utc)
    overdue_jobs, near_jobs = [], []
    for j in jobs:
        if j.get('status') == 'Completed':
            continue
        dl = j.get('deadline') or j.get('delivery_deadline')
        if isinstance(dl, str):
            try:
                dl = datetime.fromisoformat(dl.replace('Z', '+00:00'))
            except Exception:
                dl = None
        if not isinstance(dl, datetime):
            continue
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)
        days = (dl - _now).days
        row = {'id': j.get('id'), 'job_number': j.get('job_number', ''),
               'po_number': j.get('po_number', ''),
               'deadline': serialize_doc(dl), 'days_left': days}
        if days < 0:
            overdue_jobs.append(row)
        elif days <= 7:
            near_jobs.append(row)

    return {
        'activeJobs': active_jobs, 'completedJobs': completed_jobs,
        'incomingShipments': incoming,
        'totalProduced': total_produced, 'totalAvailable': total_available,
        'progressPct': round((total_produced / total_available * 100) if total_available > 0 else 0),
        'recentProgress': recent_progress,
        'alerts': {'overdueJobs': overdue_jobs, 'nearDeadlineJobs': near_jobs},
        'vendorId': vendor_id,
    }


# ─── GLOBAL SEARCH ───────────────────────────────────────────────────────────
@router.get("/global-search")
async def global_search(request: Request):
    """
    Global Search v2 — Rahaza-native.
    Mencari lintas entitas bisnis utama: Order, Work Order, Customer, Material,
    Employee, AR Invoice, AP Invoice, Line.

    Response: {results: [{type, id, label, sub, module}]}
    - `module` = moduleId yang dikenali moduleRegistry.js (untuk navigasi saat klik).
    """
    await require_auth(request)
    db = get_db()
    q = request.query_params.get('q', '').strip()
    if not q or len(q) < 2:
        return {'results': []}

    regex = {'$regex': re.escape(q), '$options': 'i'}
    limit_per_type = 5
    results = []

    # ── Orders ─────────────────────────────────────────────────────────────
    orders = await db.rahaza_orders.find(
        {'$or': [
            {'order_number': regex},
            {'customer_name_snapshot': regex},
            {'notes': regex},
        ]},
        {'_id': 0, 'id': 1, 'order_number': 1, 'customer_name_snapshot': 1, 'status': 1, 'order_date': 1}
    ).limit(limit_per_type).to_list(500)
    for o in orders:
        results.append({
            'type': 'Order',
            'id': o.get('id'),
            'label': o.get('order_number', ''),
            'sub': f"{o.get('customer_name_snapshot', '')} · {o.get('status', '')}",
            'module': 'prod-orders',
        })

    # ── Work Orders ── T-03 (FASE 3): SSOT production_jobs via core.wo_reader
    from core.wo_reader import search_wos
    wos = await search_wos(db, regex, limit=limit_per_type)
    for w in wos:
        results.append({
            'type': 'Work Order',
            'id': w.get('id'),
            'label': w.get('wo_number', ''),
            'sub': f"{w.get('model_code_snapshot', '')} · {w.get('qty', 0)} pcs · {w.get('status', '')}",
            'module': 'prod-work-orders',
        })

    # ── Customers ──────────────────────────────────────────────────────────
    customers = await db.rahaza_customers.find(
        {'$or': [{'code': regex}, {'name': regex}, {'phone': regex}, {'email': regex}]},
        {'_id': 0, 'id': 1, 'code': 1, 'name': 1, 'active': 1}
    ).limit(limit_per_type).to_list(500)
    for c in customers:
        results.append({
            'type': 'Pelanggan',
            'id': c.get('id'),
            'label': c.get('name', ''),
            'sub': c.get('code', ''),
            'module': 'mgmt-rahaza-customers',
        })

    # ── Materials ──────────────────────────────────────────────────────────
    materials = await db.rahaza_materials.find(
        {'$or': [{'code': regex}, {'name': regex}]},
        {'_id': 0, 'id': 1, 'code': 1, 'name': 1, 'type': 1, 'unit': 1}
    ).limit(limit_per_type).to_list(500)
    for m in materials:
        results.append({
            'type': 'Material',
            'id': m.get('id'),
            'label': m.get('name', ''),
            'sub': f"{m.get('code', '')} · {m.get('type', '')} ({m.get('unit', '')})",
            'module': 'wh-materials',
        })

    # ── Employees ──────────────────────────────────────────────────────────
    employees = await db.rahaza_employees.find(
        {'$or': [{'employee_code': regex}, {'name': regex}, {'phone': regex}]},
        {'_id': 0, 'id': 1, 'employee_code': 1, 'name': 1, 'role': 1, 'active': 1}
    ).limit(limit_per_type).to_list(500)
    for e in employees:
        results.append({
            'type': 'Karyawan',
            'id': e.get('id'),
            'label': e.get('name', ''),
            'sub': f"{e.get('employee_code', '')} · {e.get('role', '')}",
            'module': 'prod-employees',
        })

    # ── AR Invoices ────────────────────────────────────────────────────────
    ar = await db.rahaza_ar_invoices.find(
        {'$or': [{'invoice_number': regex}, {'customer_name': regex}]},
        {'_id': 0, 'id': 1, 'invoice_number': 1, 'customer_name': 1, 'total': 1, 'status': 1}
    ).limit(limit_per_type).to_list(500)
    for i in ar:
        results.append({
            'type': 'AR Invoice',
            'id': i.get('id'),
            'label': i.get('invoice_number', ''),
            'sub': f"{i.get('customer_name', '')} · {i.get('status', '')}",
            'module': 'fin-ar-invoices',
        })

    # ── AP Invoices ────────────────────────────────────────────────────────
    ap = await db.rahaza_ap_invoices.find(
        {'$or': [{'invoice_number': regex}, {'vendor_name': regex}]},
        {'_id': 0, 'id': 1, 'invoice_number': 1, 'vendor_name': 1, 'total': 1, 'status': 1}
    ).limit(limit_per_type).to_list(500)
    for i in ap:
        results.append({
            'type': 'AP Invoice',
            'id': i.get('id'),
            'label': i.get('invoice_number', ''),
            'sub': f"{i.get('vendor_name', '')} · {i.get('status', '')}",
            'module': 'fin-ap',  # routes to legacy AP module (Rahaza AP belum punya module dedicated)
        })

    # ── Lines ──────────────────────────────────────────────────────────────
    lines = await db.rahaza_lines.find(
        {'$or': [{'code': regex}, {'name': regex}]},
        {'_id': 0, 'id': 1, 'code': 1, 'name': 1, 'process_code': 1, 'active': 1}
    ).limit(limit_per_type).to_list(500)
    for l in lines:
        results.append({
            'type': 'Line Produksi',
            'id': l.get('id'),
            'label': l.get('code', ''),
            'sub': f"{l.get('name', '')} · {l.get('process_code', '')}",
            'module': 'prod-lines',
        })

    return {'results': results}


# ─── ATTACHMENTS ─────────────────────────────────────────────────────────────
@router.get("/attachments")
async def get_attachments(request: Request):
    await require_auth(request)
    db = get_db()
    sp = request.query_params
    entity_type = sp.get('entity_type')
    entity_id = sp.get('entity_id')
    if not entity_type or not entity_id:
        raise HTTPException(400, 'entity_type and entity_id required')
    # 2026-11-06 (pola P1): DELETE /attachments/{id} hanya menandai is_deleted — daftar wajib
    # menyaringnya, kalau tidak lampiran yang dihapus muncul lagi saat panel dibuka ulang.
    # Urutan memakai created_at (field yang ditulis /upload); `uploaded_at` tidak pernah ada.
    q = {'entity_type': entity_type, 'entity_id': entity_id, 'is_deleted': {'$ne': True}}
    # Dual-mode: paginated or full list
    if sp.get('page') or sp.get('limit'):
        page, limit, skip = get_pagination_params(request, default_limit=20)
        total = await db.attachments.count_documents(q)
        items = await db.attachments.find(q, {'_id': 0}).sort('created_at', -1).skip(skip).limit(limit).to_list(limit)
        return paginated_response(serialize_doc(items), total, page, limit)
    return serialize_doc(await db.attachments.find(q, {'_id': 0}).sort('created_at', -1).to_list(500))

