"""
CV. Dewi Aditya — Maklon PO 360° View Aggregator
Phase 25 — P2 Workflow Consolidation #1

Provides single-call aggregator for ALL data related to one Maklon PO:
- PO detail (header + items + dispatches + receives + bom)
- Samples (sampling/revisions)
- QC checks
- Invoices + Payments
- HPP snapshot
- Timeline / activity log (cross-module chronological feed)

Non-breaking: existing per-module endpoints are unchanged.
"""

from fastapi import APIRouter, HTTPException, Depends
from routes.production_rbac import deny_external_dep
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from database import get_db
from auth import require_auth, serialize_doc
from services.maklon_progress import compute_po_progress
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/dewi/maklon', tags=['Dewi-Maklon-360'], dependencies=[Depends(deny_external_dep)])
# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _safe_serialize(doc):
    if not doc:
        return None
    return serialize_doc(doc)


def _serialize_list(docs):
    return [serialize_doc(d) for d in (docs or [])]


def _to_iso(dt):
    """Best-effort ISO formatting for timeline ordering."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def _push_event(events: List[Dict[str, Any]], event_type: str, label: str, when, **extra):
    """Append a single timeline event with normalized timestamp."""
    iso = _to_iso(when)
    events.append({
        'type': event_type,
        'label': label,
        'when': iso,
        **extra,
    })


async def _po_or_404(db, po_id: str) -> Dict[str, Any]:
    """Ambil PO maklon: cermin legacy `dewi_maklon_pos` dulu, lalu SSOT.

    DIPERBAIKI 2026-08-01: PO maklon yang dibuat lewat engine SSOT tersimpan di
    `production_pos` + `po_items` dan BELUM tentu punya cermin di
    `dewi_maklon_pos` (cermin hanya dibuat pada event tertentu). Akibatnya Detail
    PO 360° — termasuk tab BOM — selalu 404 "PO Maklon tidak ditemukan" untuk
    PO-PO tersebut. Sekarang jatuh-balik ke SSOT dan item-nya dinormalkan agar
    bentuknya sama seperti versi legacy (items ter-embed).
    """
    po = await db.dewi_maklon_pos.find_one({'id': po_id}, {'_id': 0})
    if po:
        return po

    ssot = await db.production_pos.find_one({'id': po_id, 'business_type': 'maklon'}, {'_id': 0})
    if not ssot:
        raise HTTPException(404, 'PO Maklon tidak ditemukan')

    items = await db.po_items.find({'po_id': po_id}, {'_id': 0}).to_list(None)
    ssot['items'] = [{
        **it,
        'buyer_catalog_id': it.get('catalog_item_id') or it.get('buyer_catalog_id'),
        'catalog_item_id': it.get('catalog_item_id') or it.get('buyer_catalog_id'),
        'qty': int(it.get('qty') or it.get('qty_ordered') or 0),
    } for it in items]
    ssot['_source_collection'] = 'production_pos'
    return ssot


DA_OWNERSHIP = ('cv_da_stock', 'cv_da', 'da_provided')


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def bom_costs(bom: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Total biaya BOM per-PO (murni) — rumus yang sama dengan tab BOM di layar:
    estimasi = `estimated_cost` atau qty estimasi × `cost_per_unit`; aktual = `actual_cost`
    atau qty aktual × `cost_per_unit`. Baris dibaca dari `materials` (skema kanonik) dengan
    cadangan `lines` (bentuk lama). `*_da` = hanya baris milik DA (K14: bahan klien bukan
    biaya DA)."""
    out = {'estimated': 0.0, 'actual': 0.0, 'estimated_da': 0.0, 'actual_da': 0.0}
    for ln in ((bom or {}).get('materials') or (bom or {}).get('lines') or []):
        cpu = _f(ln.get('cost_per_unit'))
        qty_est = _f(ln.get('qty_estimated') if ln.get('qty_estimated') is not None else ln.get('qty_total_est'))
        est = _f(ln.get('estimated_cost')) if ln.get('estimated_cost') is not None else qty_est * cpu
        act = _f(ln.get('actual_cost')) if ln.get('actual_cost') is not None else _f(ln.get('qty_actual')) * cpu
        out['estimated'] += est
        out['actual'] += act
        if (ln.get('ownership') or 'client_provided') in DA_OWNERSHIP:
            out['estimated_da'] += est
            out['actual_da'] += act
    return {k: round(v, 2) for k, v in out.items()}


async def _live_item_quantities(db, po_id: str, items: list) -> Optional[Dict[str, Any]]:
    """Angka qty per item dari SSOT (`core.dispatch_capacity.po_item_quantities`, K17) bila
    PO ini ada di `production_pos`; None untuk PO lama murni."""
    if not await db.production_pos.find_one({'id': po_id}, {'_id': 0, 'id': 1}):
        return None
    from core import dispatch_capacity as dcap
    ids = [i.get('item_id') or i.get('id') for i in (items or []) if i.get('item_id') or i.get('id')]
    if not ids:
        ids = [d['id'] async for d in db.po_items.find({'po_id': po_id}, {'_id': 0, 'id': 1})]
    return {'item_ids': ids, 'qty': await dcap.po_item_quantities(db, ids)}


async def _buyer_shipments_as_dispatches(db, po_item_ids: list) -> list:
    """Surat jalan DA → buyer PO ini dalam bentuk baris riwayat kirim layar 360°."""
    from core import dispatch_capacity as dcap
    rows = await dcap.buyer_dispatch_items(db, po_item_ids=po_item_ids)
    by_ship: Dict[str, list] = {}
    for it in rows:
        by_ship.setdefault(it.get('shipment_id'), []).append(
            {'item_id': it.get('po_item_id'), 'qty_dispatched': dcap.item_dispatched(it)})
    if not by_ship:
        return []
    out = []
    async for s in db.buyer_shipments.find({'id': {'$in': list(by_ship)}}, {'_id': 0}):
        out.append({'id': s['id'], 'dispatch_number': s.get('shipment_number', ''),
                    'status': s.get('ship_status', ''), 'created_at': s.get('created_at'),
                    'driver_name': s.get('driver_name'), 'vehicle_no': s.get('vehicle_no'),
                    'items': by_ship[s['id']], 'source': 'buyer_shipment'})
    out.sort(key=lambda d: _to_iso(d.get('created_at')) or '', reverse=True)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.get('/pos/{po_id}/360')
async def maklon_po_360(po_id: str, user: dict = Depends(require_auth)):
    """
    Aggregator endpoint for Maklon PO 360° View.
    
    Returns single response with ALL cross-module data for one PO:
    - po: header + items
    - dispatches: dispatch history
    - material_receives: client-supplied material intake
    - bom: BOM (estimate + actual)
    - samples: sample records + revisions
    - qc_checks: QC records
    - invoices: AR invoices linked to PO
    - payments: payments per invoice
    - hpp: HPP snapshot (computed from PO + dispatches + material_receives)
    - kpis: top-line KPIs for header strip
    """
    db = get_db()
    po = await _po_or_404(db, po_id)
    po_data = serialize_doc(po)

    # ── Dispatches ──────────────────────────────────────────────────────────
    dispatches_raw = await db.dewi_maklon_dispatches.find(
        {'po_id': po_id}
    ).sort('created_at', -1).to_list(length=None)
    dispatches = _serialize_list(dispatches_raw)

    # Tahap 1 (6 Nov 2026): qty dikirim/diproduksi dibaca dari SSOT (`po_items` + surat
    # jalan buyer lewat `core.dispatch_capacity`, K17). Dulu hanya dari koleksi lama
    # `dewi_maklon_dispatches` dengan kunci `item_id` — PO maklon sekarang selalu 0 terkirim.
    live = await _live_item_quantities(db, po_id, po_data.get('items', []))
    if live is not None:
        dispatches = _serialize_list(await _buyer_shipments_as_dispatches(db, live['item_ids'])) + dispatches
        for item in po_data.get('items', []):
            q = live['qty'].get(item.get('item_id') or item.get('id')) or {}
            item['qty_dispatched'] = int(q.get('dispatched', 0) or 0)
            item['qty_produced'] = int(q.get('produced_main', 0) or 0)
            item['qty_remaining'] = max(0, int(item.get('qty', 0) or 0) - item['qty_dispatched'])
        total_dispatched = sum(int(i.get('qty_dispatched', 0) or 0) for i in po_data.get('items', []))
    else:
        # PO lama murni (tanpa production_pos): kiriman lama yang tidak dibatalkan
        item_dispatch_map: Dict[str, int] = {}
        for d in dispatches_raw:
            if d.get('status') == 'cancelled':
                continue
            for di in d.get('items', []):
                iid = di.get('item_id')
                if iid:
                    item_dispatch_map[iid] = item_dispatch_map.get(iid, 0) + di.get('qty_dispatched', 0)
        total_dispatched = sum(item_dispatch_map.values())
        for item in po_data.get('items', []):
            iid = item.get('item_id')
            item['qty_dispatched'] = item_dispatch_map.get(iid, 0)
            item['qty_remaining'] = max(0, item.get('qty', 0) - item['qty_dispatched'])

    # ── Material Receives ───────────────────────────────────────────────────
    receives_raw = await db.dewi_maklon_material_receive.find(
        {'po_id': po_id}
    ).sort('created_at', -1).to_list(length=None)
    material_receives = _serialize_list(receives_raw)

    # ── BOM ─────────────────────────────────────────────────────────────────
    bom = await db.dewi_maklon_bom.find_one({'po_id': po_id})
    bom_data = _safe_serialize(bom)

    # ── Samples (linked via order_id == po_id pattern) ──────────────────────
    # The samples collection stores both order_id and po_id (per P1.B migration),
    # query with $or to catch both old and new docs.
    samples_raw = await db.dewi_maklon_samples.find({
        '$or': [{'order_id': po_id}, {'po_id': po_id}]
    }).sort('created_at', -1).to_list(length=None)
    samples = _serialize_list(samples_raw)

    sample_ids = [s.get('id') for s in samples if s.get('id')]
    revisions_raw = []
    if sample_ids:
        revisions_raw = await db.dewi_maklon_sample_revisions.find(
            {'sample_id': {'$in': sample_ids}}
        ).sort('created_at', -1).to_list(length=None)
    sample_revisions = _serialize_list(revisions_raw)

    # ── QC Checks ───────────────────────────────────────────────────────────
    qc_raw = await db.dewi_maklon_qc_checks.find({
        '$or': [{'order_id': po_id}, {'po_id': po_id}]
    }).sort('created_at', -1).to_list(length=None)
    qc_checks = _serialize_list(qc_raw)

    # ── Invoices (AR) — Maklon billing creates dewi_maklon_invoices ─────────
    invoices_raw = await db.dewi_maklon_invoices.find({
        '$or': [{'order_id': po_id}, {'po_id': po_id}]
    }).sort('issue_date', -1).to_list(length=None)
    invoices = _serialize_list(invoices_raw)

    # Optionally pull rahaza_ar_invoices linked via po.ar_invoice_id
    ar_invoice = None
    if po_data.get('ar_invoice_id'):
        ar_doc = await db.rahaza_ar_invoices.find_one({'id': po_data['ar_invoice_id']})
        ar_invoice = _safe_serialize(ar_doc)

    invoice_ids = [inv.get('id') for inv in invoices if inv.get('id')]
    payments_raw = []
    if invoice_ids:
        payments_raw = await db.dewi_maklon_payments.find(
            {'invoice_id': {'$in': invoice_ids}}
        ).sort('payment_date', -1).to_list(length=None)
    payments = _serialize_list(payments_raw)

    # ── HPP Snapshot (computed) ─────────────────────────────────────────────
    # Tahap 1 (6 Nov 2026): BOM per-PO menyimpan barisnya di `materials` (penulis kanonik
    # `explode_maklon_bom_for_po` & endpoint manual), bukan `lines` — dulu biaya BOM selalu Rp 0.
    bom_cost = bom_costs(bom_data)
    bom_estimated_cost = bom_cost['estimated']
    bom_actual_cost = bom_cost['actual']

    material_received_value = 0.0
    for r in receives_raw:
        for li in r.get('items', []):
            material_received_value += float(li.get('unit_cost', 0) or 0) * float(li.get('qty', 0) or 0)

    total_value = float(po_data.get('total_value', 0) or 0)
    invoiced_amount = sum(float(inv.get('total_amount', 0) or 0) for inv in invoices_raw if inv.get('status') != 'cancelled')
    paid_amount = sum(float(p.get('amount', 0) or 0) for p in payments_raw if p.get('status') != 'cancelled')
    outstanding_amount = max(0, invoiced_amount - paid_amount)
    # 2026-11-06 (Tahap 2): piutang TERJADWAL (satu dokumen AR per PO) — tertagih = pendapatan yang
    # sudah dibukukan per kiriman; dibayar termasuk uang muka. Pembayaran dari riwayat piutang.
    if (ar_invoice or {}).get('schedule_mode') == 'v2':
        invoiced_amount = float(ar_invoice.get('billed_total') or 0)
        paid_amount = float(ar_invoice.get('amount_paid') or 0)
        outstanding_amount = float(ar_invoice.get('amount_due') or 0)
        payments = _serialize_list(await db.rahaza_ar_payments.find(
            {'invoice_id': ar_invoice['id'], 'status': {'$ne': 'voided'}}).sort('date', -1).to_list(500))

    hpp_snapshot = {
        'po_total_value': total_value,
        'bom_estimated_cost': bom_estimated_cost,
        'bom_actual_cost': bom_actual_cost,
        # biaya BOM milik DA saja — kain/aksesoris titipan klien bukan biaya DA (K14)
        'bom_estimated_cost_da': bom_cost['estimated_da'],
        'bom_actual_cost_da': bom_cost['actual_da'],
        'material_received_value': material_received_value,
        'invoiced_amount': invoiced_amount,
        'paid_amount': paid_amount,
        'outstanding_amount': outstanding_amount,
        'gross_margin_estimate': (total_value - bom_cost['estimated_da']
                                  if bom_cost['estimated_da'] > 0 else None),
        'gross_margin_actual': (total_value - bom_cost['actual_da']
                                if bom_cost['actual_da'] > 0 else None),
    }

    # ── KPIs for 360° header strip ──────────────────────────────────────────
    total_qty = int(po_data.get('total_qty', 0) or 0) or sum(
        int(it.get('qty', 0) or 0) for it in po_data.get('items', []))
    total_produced = sum(int(it.get('qty_produced', 0) or 0) for it in po_data.get('items', []))
    progress_pct = round((total_produced / total_qty) * 100, 1) if total_qty > 0 else 0.0
    dispatch_pct = round((total_dispatched / total_qty) * 100, 1) if total_qty > 0 else 0.0

    sample_pending = sum(1 for s in samples_raw if s.get('status') in ('draft', 'submitted', 'in_progress', 'revision_requested'))
    sample_approved = sum(1 for s in samples_raw if s.get('status') == 'approved')
    qc_pass = sum(1 for q in qc_raw if q.get('result') in ('pass', 'passed'))
    qc_fail = sum(1 for q in qc_raw if q.get('result') in ('fail', 'failed'))

    kpis = {
        'status': po_data.get('status', 'draft'),
        'po_number': po_data.get('po_number', ''),
        'client_name': po_data.get('client_name', ''),
        'total_qty': total_qty,
        'total_produced': total_produced,
        'total_dispatched': total_dispatched,
        'total_remaining': max(0, total_qty - total_dispatched),
        'progress_pct': progress_pct,
        'dispatch_pct': dispatch_pct,
        'total_value': total_value,
        'invoiced_amount': invoiced_amount,
        'paid_amount': paid_amount,
        'outstanding_amount': outstanding_amount,
        'scheduled_amount': float((ar_invoice or {}).get('scheduled_total') or 0),
        'advance_balance': float((ar_invoice or {}).get('advance_balance') or 0),
        'deadline': po_data.get('deadline'),
        'sample_pending': sample_pending,
        'sample_approved': sample_approved,
        'qc_pass': qc_pass,
        'qc_fail': qc_fail,
        'dispatch_count': len([d for d in dispatches if str(d.get('status') or '').lower() != 'cancelled']),
        'invoice_count': len([i for i in invoices_raw if i.get('status') != 'cancelled']),
    }

    # ── Canonical multi-state progress breakdown (SSOT: production_pos) ─────
    # id dewi_maklon_pos == production_pos.id (mirror), jadi po_id valid utk service.
    # None untuk PO legacy murni tanpa production_pos → kirim {} agar UI aman.
    progress_breakdown: Dict[str, Any] = {}
    try:
        _prog = await compute_po_progress(db, po_id)
        if _prog is not None:
            progress_breakdown = {
                'breakdown': _prog.get('breakdown', {}),
                'items': _prog.get('items', []),
                'progress_pct': _prog.get('progress_pct', 0),
                'good_pct': _prog.get('good_pct', 0),
                'dispatch_pct': _prog.get('dispatch_pct', 0),
                'delivery_pct': _prog.get('delivery_pct', 0),
            }
    except Exception:
        logger.exception('po_360: gagal hitung progress_breakdown untuk %s', po_id)

    return {
        'po': po_data,
        'dispatches': dispatches,
        'material_receives': material_receives,
        'bom': bom_data,
        'samples': samples,
        'sample_revisions': sample_revisions,
        'qc_checks': qc_checks,
        'invoices': invoices,
        'ar_invoice': ar_invoice,
        'payments': payments,
        'hpp': hpp_snapshot,
        'kpis': kpis,
        'progress_breakdown': progress_breakdown,
    }


@router.get('/pos/{po_id}/timeline')
async def maklon_po_timeline(po_id: str, user: dict = Depends(require_auth)):
    """
    Chronological activity log for one PO — aggregates events from all related collections.
    Returns events sorted desc by timestamp.
    """
    db = get_db()
    po = await _po_or_404(db, po_id)

    events: List[Dict[str, Any]] = []

    # PO lifecycle events
    _push_event(events, 'po.created', f"PO {po.get('po_number', '')} dibuat",
                po.get('created_at'), actor=po.get('created_by'), icon='package')
    if po.get('confirmed_at'):
        _push_event(events, 'po.confirmed', f"PO {po.get('po_number', '')} dikonfirmasi",
                    po.get('confirmed_at'), actor=po.get('confirmed_by'), icon='check-circle')
    if po.get('cancelled_at'):
        _push_event(events, 'po.cancelled', "PO dibatalkan",
                    po.get('cancelled_at'), actor=po.get('cancelled_by'),
                    reason=po.get('cancel_reason'), icon='ban')
    if po.get('completed_at'):
        _push_event(events, 'po.completed', "PO selesai",
                    po.get('completed_at'), icon='trophy')

    # 2026-11-06 (Tahap 2): kelebihan qty (alasan wajib) di setiap langkah — dari SSOT production_pos
    ssot = await db.production_pos.find_one({'id': po_id}, {'_id': 0, 'over_qty_events': 1, 'confirmed_at': 1,
                                                            'confirmed_by': 1, 'closed_at': 1, 'closed_by': 1,
                                                            'status': 1, 'closed_reason': 1}) or {}
    for ev in ssot.get('over_qty_events') or []:
        _push_event(events, 'qty.over',
                    f"{ev.get('step_label') or ev.get('step')}: {ev.get('label') or ''} {ev.get('qty')} pcs "
                    f"(batas {ev.get('limit')}, lebih {ev.get('over')}) — alasan: {ev.get('reason')}",
                    ev.get('at'), actor=ev.get('by'), icon='alert-triangle', reason=ev.get('reason'),
                    step=ev.get('step'), qty=ev.get('qty'), limit=ev.get('limit'), over=ev.get('over'))
    if ssot.get('confirmed_at') and not po.get('confirmed_at'):
        _push_event(events, 'po.confirmed', f"PO {po.get('po_number', '')} dikonfirmasi",
                    ssot.get('confirmed_at'), actor=ssot.get('confirmed_by'), icon='check-circle')
    if ssot.get('closed_at'):
        _push_event(events, 'po.closed', f"PO ditutup ({ssot.get('status')})", ssot.get('closed_at'),
                    actor=ssot.get('closed_by'), reason=ssot.get('closed_reason'), icon='lock')

    # Dispatches
    dispatches = await db.dewi_maklon_dispatches.find({'po_id': po_id}).to_list(length=None)
    for d in dispatches:
        dnum = d.get('dispatch_number', '')
        _push_event(events, 'dispatch.created', f"Dispatch {dnum} dibuat",
                    d.get('created_at'), actor=d.get('created_by'), icon='truck',
                    dispatch_id=d.get('id'))
        if d.get('confirmed_at'):
            _push_event(events, 'dispatch.confirmed', f"Dispatch {dnum} dikonfirmasi",
                        d.get('confirmed_at'), actor=d.get('confirmed_by'), icon='check',
                        dispatch_id=d.get('id'))
        if d.get('cancelled_at'):
            _push_event(events, 'dispatch.cancelled', f"Dispatch {dnum} dibatalkan",
                        d.get('cancelled_at'), actor=d.get('cancelled_by'), icon='x-circle',
                        dispatch_id=d.get('id'))

    # Material Receives
    receives = await db.dewi_maklon_material_receive.find({'po_id': po_id}).to_list(length=None)
    for r in receives:
        rnum = r.get('receive_number', r.get('id', ''))
        _push_event(events, 'material.received',
                    f"Material klien diterima ({rnum})", r.get('created_at'),
                    actor=r.get('created_by'), icon='inbox', receive_id=r.get('id'))

    # Samples
    samples = await db.dewi_maklon_samples.find(
        {'$or': [{'order_id': po_id}, {'po_id': po_id}]}
    ).to_list(length=None)
    for s in samples:
        scode = s.get('sample_code', '')
        _push_event(events, 'sample.created', f"Sample {scode} dibuat",
                    s.get('created_at'), actor=s.get('created_by'), icon='clipboard',
                    sample_id=s.get('id'))
        if s.get('submitted_at'):
            _push_event(events, 'sample.submitted', f"Sample {scode} disubmit",
                        s.get('submitted_at'), icon='send', sample_id=s.get('id'))
        if s.get('approved_at'):
            _push_event(events, 'sample.approved', f"Sample {scode} disetujui",
                        s.get('approved_at'), actor=s.get('approved_by'),
                        icon='check-circle', sample_id=s.get('id'))
        if s.get('rejected_at'):
            _push_event(events, 'sample.rejected', f"Sample {scode} ditolak",
                        s.get('rejected_at'), actor=s.get('rejected_by'),
                        reason=s.get('reject_reason'), icon='x', sample_id=s.get('id'))

    # QC Checks
    qcs = await db.dewi_maklon_qc_checks.find(
        {'$or': [{'order_id': po_id}, {'po_id': po_id}]}
    ).to_list(length=None)
    for q in qcs:
        stage = q.get('stage', 'unknown')
        result = q.get('result', 'pending')
        _push_event(events, f'qc.{result}',
                    f"QC {stage}: {result.upper()}",
                    q.get('created_at'), actor=q.get('checked_by'),
                    icon='shield-check' if result in ('pass', 'passed') else 'shield-alert',
                    qc_id=q.get('id'), stage=stage, result=result)

    # Invoices
    invoices = await db.dewi_maklon_invoices.find(
        {'$or': [{'order_id': po_id}, {'po_id': po_id}]}
    ).to_list(length=None)
    for inv in invoices:
        inum = inv.get('invoice_number', '')
        _push_event(events, 'invoice.created', f"Invoice {inum} dibuat",
                    inv.get('created_at') or inv.get('issue_date'),
                    icon='file-text', invoice_id=inv.get('id'),
                    amount=inv.get('total_amount'))
        if inv.get('cancelled_at'):
            _push_event(events, 'invoice.cancelled', f"Invoice {inum} dibatalkan",
                        inv.get('cancelled_at'), icon='x-circle', invoice_id=inv.get('id'))

    # Payments
    invoice_ids = [i.get('id') for i in invoices if i.get('id')]
    if invoice_ids:
        payments = await db.dewi_maklon_payments.find(
            {'invoice_id': {'$in': invoice_ids}}
        ).to_list(length=None)
        for p in payments:
            _push_event(events, 'payment.received',
                        f"Pembayaran Rp {int(p.get('amount', 0) or 0):,} diterima",
                        p.get('payment_date') or p.get('created_at'),
                        actor=p.get('received_by'), icon='banknote',
                        invoice_id=p.get('invoice_id'), amount=p.get('amount'),
                        method=p.get('payment_method'))

    # Activity logs — pull any audit events that mention this PO number
    # (covers confirm/cancel/update flows that don't update timestamp fields directly)
    po_number = po.get('po_number', '')
    if po_number:
        activity_logs = await db.activity_logs.find({
            '$or': [
                {'details': {'$regex': po_number, '$options': 'i'}},
                {'module': 'dewi_maklon_pos', 'details': {'$regex': po_id, '$options': 'i'}},
            ]
        }).sort('timestamp', -1).limit(50).to_list(length=50)

        # Avoid duplicating PO-creation/confirmation events we already added
        seen_signatures = {(e.get('type'), e.get('when')) for e in events}
        for log in activity_logs:
            action = log.get('action', 'log')
            module = log.get('module', '')
            details = log.get('details', '')
            ts = log.get('timestamp')
            etype = f'log.{module}.{action}' if module else f'log.{action}'
            iso = _to_iso(ts)
            # Skip if we already have this exact (type, when) combination
            if (etype, iso) in seen_signatures:
                continue
            _push_event(events, etype, details, ts,
                        actor=log.get('user_id'), actor_name=log.get('user_name'),
                        icon='activity', source='audit_log')

    # Sort desc by `when` (nulls last)
    events.sort(key=lambda e: (e.get('when') or ''), reverse=True)

    return {
        'po_id': po_id,
        'po_number': po.get('po_number', ''),
        'total_events': len(events),
        'events': events,
    }
