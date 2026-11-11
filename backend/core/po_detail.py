"""Rincian satu PO — SATU sumber untuk PO Internal dan PO Maklon (Tahap 9, keputusan 8).

Keputusan owner 7 Nov 2026: menu "Detail PO" dihapus; isinya menjadi rincian di bawah tabel PO yang sama di
kedua portal (Ringkasan · Barang · Bahan & aksesoris · Kirim & terima · Tagihan & HPP · Sampel · Riwayat).
SEMUA angka dibaca dari data PO utama (`production_pos`, `po_items`, kiriman, penerimaan, permak, tagihan),
bukan dari salinan `dewi_maklon_pos`. Dulu layar Detail PO memilih PO dari salinan (draf tidak ada) dan
QC/bahan klien dibaca dari koleksi yang tidak lagi ditulis siapa pun.

Pembaca:
  - GET /api/production-pos/{id}/detail      → `build_po_detail()`
  - GET /api/production-pos/{id}/timeline    → `build_timeline()`
  - GET /api/dewi/maklon/pos/{id}/timeline   → meneruskan ke `build_timeline()` (tautan lama)
Angka qty per baris tetap dari `core.dispatch_capacity.po_item_quantities` (K17) lewat endpoint
`/production-pos/{id}/quantity-summary` yang sudah ada — tidak ada rumus kedua di sini.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

logger = logging.getLogger(__name__)

SHIP_TYPE_LABEL = {'NORMAL': 'Utama', 'ADDITIONAL': 'Tambahan', 'REPLACEMENT': 'Pengganti', 'REWORK': 'Permak'}
VENDOR_SHIP_STATUS = {'Sent': 'Dikirim', 'Received': 'Diterima CMT', 'Cancelled': 'Dibatalkan'}
PERMAK_STATUS = {'open': 'Terbuka', 'in_progress': 'Dikerjakan', 'selesai_berhasil': 'Selesai',
                 'gagal_buang': 'Gagal, dibuang'}
BILL_STATUS = {'draft': 'Draf', 'submitted': 'Diajukan', 'approved': 'Disetujui', 'pending': 'Menunggu',
               'posted': 'Terjurnal', 'partial_paid': 'Dibayar sebagian', 'paid': 'Lunas',
               'cancelled': 'Dibatalkan'}
BUYER_SHIP_STATUS = {'Draft': 'Draf', 'Shipped': 'Dikirim', 'Delivered': 'Diterima', 'Received': 'Diterima',
                     'Partially Received': 'Diterima sebagian', 'Cancelled': 'Dibatalkan'}
BOM_TYPE_LABEL = {'yarn': 'Bahan (berat)', 'fabric': 'Kain', 'accessory': 'Aksesoris', 'accessories': 'Aksesoris',
                  'potongan': 'Kain potongan', 'cut_piece': 'Kain potongan', 'packaging': 'Kemasan',
                  'other': 'Lainnya'}
ACC_SOURCE_LABEL = {'bom': 'BOM', 'bom_auto': 'BOM', 'bom_maklon_auto': 'BOM', 'maklon_bom_template': 'BOM',
                    'tambahan': 'Tambahan',
                    'manual': 'Tambahan'}

_LIM = 2000


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _iso(dt):
    if dt is None or dt == '':
        return None
    if isinstance(dt, datetime):
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()
    return str(dt)


def _clean(doc: dict | None) -> dict:
    from auth import serialize_doc
    d = dict(doc or {})
    d.pop('_id', None)
    return serialize_doc(d)


async def get_po_or_404(db, po_id: str) -> dict:
    po = await db.production_pos.find_one({'id': po_id}, {'_id': 0})
    if not po:
        raise HTTPException(404, 'PO tidak ditemukan')
    return po


# ─────────────────────────────────────────────────────────────────────────────
# Rencana aksesoris (po_accessories) — kolom satuan serah ditulis agen kirim; layar membaca bila ada.
# ─────────────────────────────────────────────────────────────────────────────
def accessory_plan_row(a: dict) -> dict:
    """Murni: satu baris `po_accessories` → baris tampilan. Tanpa kolom satuan serah = cadangan qty_needed/unit."""
    src = str(a.get('source') or '').strip().lower()
    unit = a.get('usage_unit') or a.get('unit') or 'pcs'
    has_handover = a.get('handover_uom') not in (None, '')
    return {
        'id': a.get('id'),
        'accessory_id': a.get('accessory_id'),
        'name': a.get('accessory_name') or a.get('material_name') or '-',
        'code': a.get('accessory_code') or a.get('material_code') or '',
        # Tahap 9 (kirim): baris mesin BOM kini source='bom' + bom_origin; baris lama bom_auto/bom_maklon_auto
        'source': ('bom' if src in ('bom', 'bom_auto', 'bom_maklon_auto', 'maklon_bom_template') or a.get('bom_origin')
                   else ('tambahan' if src else '')),
        'source_label': ACC_SOURCE_LABEL.get(src, 'Tambahan' if src else '-'),
        'usage_unit': unit,
        'bom_qty_base': _f(a.get('bom_qty_base')) if a.get('bom_qty_base') is not None else _f(a.get('qty_needed')),
        'has_handover': has_handover,
        'handover_uom': a.get('handover_uom') or '',
        'handover_factor': _f(a.get('handover_factor')) if has_handover else None,
        'bom_qty_handover': _f(a.get('bom_qty_handover')) if a.get('bom_qty_handover') is not None else None,
        'plan_qty_handover': _f(a.get('plan_qty_handover')) if a.get('plan_qty_handover') is not None else None,
        # owner 11 Nov 2026: harga jual ke CMT per satuan serah (diisi di PO; nota terbit saat Kirim ke CMT)
        'harga_jual_cmt': (round(_f(a.get('harga_jual_cmt_dasar')) * (_f(a.get('handover_factor')) or 1.0), 2)
                           if a.get('harga_jual_cmt_dasar') not in (None, '') else None),
        'notes': a.get('notes') or '',
    }


# ─────────────────────────────────────────────────────────────────────────────
# Potongan data per bagian
# ─────────────────────────────────────────────────────────────────────────────
async def _vendor_shipments(db, item_ids: list) -> tuple[list, dict]:
    """Kiriman DA → CMT untuk baris PO ini + qty dikirim per po_item (bukan dibatalkan)."""
    if not item_ids:
        return [], {}
    vsi = await db.vendor_shipment_items.find({'po_item_id': {'$in': item_ids}}, {'_id': 0}).to_list(_LIM)
    by_ship: dict = {}
    for it in vsi:
        by_ship.setdefault(it.get('shipment_id'), []).append(it)
    out, sent_by_item = [], {}
    if by_ship:
        async for s in db.vendor_shipments.find({'id': {'$in': [k for k in by_ship if k]}}, {'_id': 0}):
            rows = by_ship.get(s['id']) or []
            qty = sum(_i(r.get('qty_sent')) for r in rows)
            if str(s.get('status') or '') != 'Cancelled':
                for r in rows:
                    sent_by_item[r.get('po_item_id')] = sent_by_item.get(r.get('po_item_id'), 0) + _i(r.get('qty_sent'))
            st = str(s.get('shipment_type') or 'NORMAL').upper()
            out.append({'id': s['id'], 'number': s.get('shipment_number') or '',
                        'date': _iso(s.get('shipment_date') or s.get('created_at')),
                        'vendor_name': s.get('vendor_name') or '', 'type': st,
                        'type_label': SHIP_TYPE_LABEL.get(st, 'Lainnya'), 'qty': qty, 'lines': len(rows),
                        'status': s.get('status') or '',
                        'status_label': VENDOR_SHIP_STATUS.get(s.get('status'), s.get('status') or '-'),
                        'received_at': _iso(s.get('received_at')), 'created_by': s.get('created_by') or ''})
    out.sort(key=lambda r: r.get('date') or '', reverse=True)
    return out, sent_by_item


async def _receipts(db, po_id: str, item_ids: list) -> list:
    """Penerimaan CMT → DA (+ hasil QC) — dari `cmt_receipts`/`cmt_receipt_lines` (pengganti QC lama)."""
    from core.cmt_receipt_status import STATUS_LABEL, canon_status
    rec_ids = set()
    lines_by_rec: dict = {}
    if item_ids:
        for ln in await db.cmt_receipt_lines.find({'po_item_id': {'$in': item_ids}}, {'_id': 0}).to_list(_LIM):
            rec_ids.add(ln.get('receipt_id'))
            lines_by_rec.setdefault(ln.get('receipt_id'), []).append(ln)
    q = {'$or': [{'po_id': po_id}, {'id': {'$in': [r for r in rec_ids if r]}}]}
    out = []
    async for rc in db.cmt_receipts.find(q, {'_id': 0}):
        lines = lines_by_rec.get(rc['id']) or []
        good = sum(_i(ln.get('qty_actual')) for ln in lines) if lines else _i(rc.get('total_actual'))
        rej = sum(_i(ln.get('reject_qty')) for ln in lines) if lines else _i(rc.get('total_rejected'))
        claimed = (sum(_i(ln.get('qty_shipped_by_cmt')) or (_i(ln.get('qty_actual')) + _i(ln.get('reject_qty')))
                       for ln in lines) if lines else _i(rc.get('total_shipped_by_cmt')))
        canon = canon_status(rc.get('status'))
        out.append({'id': rc['id'], 'number': rc.get('receipt_code') or '',
                    'date': _iso(rc.get('receipt_date') or rc.get('created_at')),
                    'vendor_name': rc.get('cmt_name') or '', 'qty_claimed': claimed, 'qty_good': good,
                    'qty_reject': rej, 'status': canon, 'status_label': STATUS_LABEL.get(canon, canon or '-'),
                    'qc_done_at': _iso(rc.get('qc_completed_at') or rc.get('approved_at')),
                    'created_by': rc.get('created_by') or ''})
    out.sort(key=lambda r: r.get('date') or '', reverse=True)
    return out


async def _permak(db, po_id: str) -> list:
    out = []
    async for p in db.dewi_cmt_permak.find({'po_id': po_id}, {'_id': 0}):
        st = str(p.get('status') or 'open')
        out.append({'id': p.get('id'), 'number': p.get('permak_number') or '', 'sku': p.get('sku') or '',
                    'size': p.get('size') or '', 'qty': _i(p.get('qty')), 'qty_fixed': _i(p.get('qty_fixed')),
                    'qty_scrap': _i(p.get('qty_scrap')),
                    'where_label': 'Kembali ke CMT' if p.get('permak_type') == 'retur_ke_cmt' else 'Permak di DA',
                    'status': st, 'status_label': PERMAK_STATUS.get(st, st),
                    'cost': _f(p.get('cost') or p.get('total_cost')),
                    'date': _iso(p.get('created_at'))})
    out.sort(key=lambda r: r.get('date') or '', reverse=True)
    return out


async def _buyer_shipments(db, item_ids: list) -> list:
    """Kiriman hasil: ke klien (maklon) / ke gudang DA (internal) — saringan penerima SSOT (K17)."""
    from core import dispatch_capacity as dcap
    if not item_ids:
        return []
    rows = await dcap.buyer_dispatch_items(db, po_item_ids=item_ids)
    by_ship: dict = {}
    for it in rows:
        by_ship.setdefault(it.get('shipment_id'), 0)
        by_ship[it.get('shipment_id')] += dcap.item_dispatched(it)
    out = []
    if by_ship:
        async for s in db.buyer_shipments.find({'id': {'$in': [k for k in by_ship if k]}}, {'_id': 0}):
            st = s.get('ship_status') or s.get('status') or ''
            out.append({'id': s['id'], 'number': s.get('shipment_number') or '',
                        'date': _iso(s.get('shipment_date') or s.get('created_at')), 'qty': by_ship[s['id']],
                        'status': st, 'status_label': BUYER_SHIP_STATUS.get(st, st or '-'),
                        'created_by': s.get('created_by') or ''})
    out.sort(key=lambda r: r.get('date') or '', reverse=True)
    return out


async def _cmt_bills(db, po_id: str) -> tuple[list, dict]:
    from core.maklon_ledger import cmt_bill_payable
    out = []
    for p in await db.dewi_cmt_payments.find({'po_id': po_id}, {'_id': 0}).to_list(500):
        amount = next((_f(p.get(k)) for k in ('net_amount', 'total_amount', 'subtotal') if p.get(k) not in (None, '')), 0.0)
        paid = _f(p.get('paid_amount'))
        st = str(p.get('status') or 'draft')
        out.append({'id': p.get('id'), 'number': p.get('payment_code') or '', 'vendor_name': p.get('cmt_name') or '',
                    'receipt_code': p.get('source_receipt_code') or '', 'amount': round(amount, 2),
                    'paid': round(paid, 2), 'outstanding': round(max(0.0, amount - paid), 2),
                    'payable': round(_f(cmt_bill_payable(p)), 2), 'status': st,
                    'status_label': BILL_STATUS.get(st, st), 'date': _iso(p.get('created_at'))})
    out.sort(key=lambda r: r.get('date') or '', reverse=True)
    live = [b for b in out if b['status'] != 'cancelled']
    tot = {k: round(sum(b[k] for b in live), 2) for k in ('amount', 'paid', 'outstanding')}
    return out, tot


async def _client_ar(db, po_id: str) -> dict | None:
    """Piutang klien PO maklon (satu dokumen terjadwal per PO — core.maklon_ledger)."""
    from core import maklon_ledger as ml
    ar = await ml.find_ar(db, po_id)
    if not ar:
        return None
    payments = await ml._payments(db, ar['id'])  # noqa: SLF001 — pembaca resmi riwayat bayar piutang
    amt = ml.ar_amounts(ar, payments) if ml.is_schedule(ar) else {
        'billed_total': _f(ar.get('total_amount')), 'paid_total': _f(ar.get('amount_paid')),
        'amount_due': _f(ar.get('amount_due') if ar.get('amount_due') is not None
                         else _f(ar.get('total_amount')) - _f(ar.get('amount_paid'))),
        'advance_balance': 0.0}
    return {'id': ar['id'], 'number': ar.get('invoice_number') or '', 'status': ar.get('status') or '',
            'scheduled_total': round(_f(ar.get('scheduled_total') or ar.get('total_amount')), 2),
            'billed_total': round(_f(amt.get('billed_total')), 2), 'paid_total': round(_f(amt.get('paid_total')), 2),
            'amount_due': round(_f(amt.get('amount_due')), 2),
            'advance_balance': round(_f(amt.get('advance_balance')), 2),
            'payments': [{'date': _iso(p.get('date') or p.get('created_at')), 'amount': _f(p.get('amount')),
                          'number': p.get('payment_number') or p.get('receipt_number') or ''} for p in payments]}


async def _bom(db, po: dict, items: list, is_maklon: bool) -> dict:
    """BOM PO: maklon = BOM per-PO (`dewi_maklon_bom`, dari template); internal = kebutuhan dari BOM model."""
    if is_maklon:
        bom = await db.dewi_maklon_bom.find_one({'po_id': po['id']}, {'_id': 0})
        lines = []
        for ln in ((bom or {}).get('materials') or (bom or {}).get('lines') or []):
            cat = str(ln.get('material_category') or ln.get('category') or '').lower()
            own = ln.get('ownership') or 'client_provided'
            lines.append({'name': ln.get('material_name') or ln.get('name') or '-', 'code': ln.get('material_code') or '',
                          'type_label': BOM_TYPE_LABEL.get(cat, 'Lainnya'),
                          'qty_per_pcs': _f(ln.get('qty_per_pcs')),
                          'qty_total': _f(ln.get('qty_estimated') if ln.get('qty_estimated') is not None
                                          else ln.get('qty_total_est')),
                          'unit': ln.get('unit') or '',
                          'supplied_by': 'Klien' if own == 'client_provided' else 'CV Dewi Aditya'})
        return {'kind': 'maklon', 'exists': bool(bom), 'lines': lines,
                'locked': (bom or {}).get('source') == 'template_manual',
                'source_templates': [{'version': t.get('version'), 'label': t.get('label') or t.get('version_label') or ''}
                                     for t in ((bom or {}).get('source_templates') or [])],
                'total_qty': _i((bom or {}).get('total_qty')), 'warnings': (bom or {}).get('warnings') or []}
    lines, notes = [], []
    try:
        from core import material_issue_engine as mie
        res = await mie.bom_need_for_lines(db, [{'po_item_id': i['id'], 'qty': _i(i.get('qty'))} for i in items])
        need = res[0] if isinstance(res, (tuple, list)) else res
        notes = list(res[1]) if isinstance(res, (tuple, list)) and len(res) > 1 else []
        for code, e in sorted((need or {}).items()):
            t = str(e.get('type') or '').lower()
            lines.append({'name': e.get('name') or code, 'code': code, 'type_label': BOM_TYPE_LABEL.get(t, 'Lainnya'),
                          'qty_per_pcs': None, 'qty_total': round(_f(e.get('qty')), 4), 'unit': e.get('unit') or '',
                          'supplied_by': 'CV Dewi Aditya'})
    except Exception:  # noqa: BLE001 — rincian tetap tampil walau BOM gagal dibaca
        logger.exception('kebutuhan BOM PO %s gagal dihitung', po.get('id'))
        notes.append('Kebutuhan BOM belum bisa dihitung — periksa BOM model di Master Produk.')
    return {'kind': 'internal', 'exists': bool(lines), 'lines': lines, 'locked': False,
            'source_templates': [], 'total_qty': sum(_i(i.get('qty')) for i in items), 'warnings': notes}


async def _samples(db, po_id: str) -> list:
    from core import sample_status as smp
    rows = await db.dewi_maklon_samples.find(smp.sample_query_for_po(po_id), {'_id': 0}).sort('created_at', -1).to_list(200)
    ids = [s['id'] for s in rows if s.get('id')]
    revs: dict = {}
    if ids:
        for r in await db.dewi_maklon_sample_revisions.find({'sample_id': {'$in': ids}}, {'_id': 0}).sort(
                'created_at', -1).to_list(_LIM):
            revs.setdefault(r.get('sample_id'), []).append(_clean(r))
    out = []
    for s in rows:
        d = _clean(s)
        st = s.get('status') or 'draft'
        d.update({'status_label': smp.status_label(st), 'revisions': revs.get(s.get('id'), []),
                  'can': {a: smp.can(a, st) for a in ('edit', 'submit', 'approve', 'reject', 'revision', 'delete')}})
        out.append(d)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Rincian lengkap
# ─────────────────────────────────────────────────────────────────────────────
async def build_po_detail(db, po_id: str) -> dict:
    from core import dispatch_capacity as dcap
    from core import sample_status as smp
    from core.entities import is_maklon_po
    po = await get_po_or_404(db, po_id)
    is_maklon = is_maklon_po(po)
    items = await db.po_items.find({'po_id': po_id}, {'_id': 0}).sort('created_at', 1).to_list(_LIM)
    item_ids = [i['id'] for i in items if i.get('id')]

    qmap = await dcap.po_item_quantities(db, item_ids) if item_ids else {}
    qt = dcap.sum_quantities(list(qmap.values()))
    vendor_ships, sent_by_item = await _vendor_shipments(db, item_ids)
    receipts = await _receipts(db, po_id, item_ids)

    progress: dict = {}
    try:
        from services.maklon_progress import compute_po_progress
        prog = await compute_po_progress(db, po_id)
        if prog:
            progress = {'breakdown': prog.get('breakdown', {}), 'progress_pct': prog.get('progress_pct', 0),
                        'good_pct': prog.get('good_pct', 0), 'dispatch_pct': prog.get('dispatch_pct', 0)}
    except Exception:  # noqa: BLE001
        logger.exception('progres PO %s gagal dihitung', po_id)

    ordered = sum(_i(i.get('qty')) for i in items)
    totals = {
        'ordered': ordered, 'sent_to_cmt': sum(sent_by_item.values()), 'produced': _i(qt.get('produced_main')),
        'accepted': _i(qt.get('accepted_total')), 'reject': _i(qt.get('reject')),
        'rework_open': _i(qt.get('rework_open_da')) + _i(qt.get('rework_open_cmt')),
        'repaired': _i(qt.get('repaired')), 'dispatched': _i(qt.get('dispatched')),
        'remaining_to_ship': max(0, ordered - _i(qt.get('dispatched'))),
        'value_cmt': round(sum(_i(i.get('qty')) * _f(i.get('cmt_price_snapshot')) for i in items), 2),
        'value_selling': round(sum(_i(i.get('qty')) * _f(i.get('selling_price_snapshot')) for i in items), 2)
        if is_maklon else 0.0,
    }
    accs = await db.po_accessories.find({'po_id': po_id}, {'_id': 0}).sort('created_at', 1).to_list(_LIM)
    bills, bill_tot = await _cmt_bills(db, po_id)
    flag = (await smp.sample_flags(db, [po])).get(po_id) if is_maklon else None
    return {
        'po_id': po_id, 'po_number': po.get('po_number') or '', 'status': po.get('status') or 'Draft',
        'business_type': 'maklon' if is_maklon else 'internal',
        'totals': totals, 'progress': progress, 'sample_flag': flag,
        'accessory_plan': [accessory_plan_row(a) for a in accs],
        'bom': await _bom(db, po, items, is_maklon),
        'vendor_shipments': vendor_ships, 'receipts': receipts, 'permak': await _permak(db, po_id),
        'result_shipments': await _buyer_shipments(db, item_ids),
        'cmt_bills': bills, 'cmt_bill_totals': bill_tot,
        'client_ar': await _client_ar(db, po_id) if is_maklon else None,
        'samples': await _samples(db, po_id) if is_maklon else [],
        'over_qty_events': [_clean(e) for e in (po.get('over_qty_events') or [])],
    }


# Catatan aktivitas lama ditulis dalam bahasa Inggris oleh modul lain — diterjemahkan untuk layar.
PO_STATUS_ID = {'Draft': 'Draf', 'Confirmed': 'Dikonfirmasi', 'Distributed': 'Didistribusikan',
                'In Production': 'Sedang produksi', 'Production Complete': 'Produksi selesai',
                'Variance Review': 'Tinjau selisih', 'Return Review': 'Tinjau retur', 'Ready to Close': 'Siap ditutup',
                'Closed Short': 'Ditutup kurang', 'Closed': 'Ditutup', 'Completed': 'Selesai', 'Cancelled': 'Dibatalkan'}


def humanize_log(details: str) -> str | None:
    """Murni: teks catatan aktivitas → kalimat Indonesia; None = lewati (sudah ada kejadian setara)."""
    import re
    t = str(details or '').strip()
    if not t or re.match(r'^(Created|Cascade deleted) PO:', t):
        return None
    m = re.match(r'^PO (\S+): (.+?) → (.+)$', t)
    if m:
        return f"Status PO diubah: {PO_STATUS_ID.get(m.group(2), m.group(2))} → {PO_STATUS_ID.get(m.group(3), m.group(3))}"
    m = re.match(r'^Updated PO: (\S+)', t)
    if m:
        return f'PO {m.group(1)} diubah'
    m = re.match(r'^Closed PO: (\S+)', t)
    if m:
        return None  # sudah ada kejadian "PO ditutup"
    m = re.match(r'^Added (\d+) accessories to PO', t)
    if m:
        return f'{m.group(1)} aksesoris ditambahkan ke PO'
    t = t.replace('Quick Complete PO', 'Selesaikan cepat PO')
    for en, idn in sorted(PO_STATUS_ID.items(), key=lambda kv: -len(kv[0])):
        t = t.replace(f'→ {en}', f'→ {idn}')
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Riwayat (timeline) — dari data PO utama + dokumen turunannya
# ─────────────────────────────────────────────────────────────────────────────
def _ev(events: list, kind: str, label: str, when, actor='', note='', amount=None):
    if not when:
        return
    events.append({'type': kind, 'label': label, 'when': _iso(when), 'actor': actor or '',
                   'note': note or '', 'amount': amount})


async def build_timeline(db, po_id: str, *, po: dict | None = None) -> dict:
    from core import sample_status as smp
    po = po or await get_po_or_404(db, po_id)
    num = po.get('po_number') or ''
    events: list = []
    _ev(events, 'po', f'PO {num} dibuat', po.get('created_at'), po.get('created_by_name') or po.get('created_by'))
    _ev(events, 'po', f'PO {num} dikonfirmasi', po.get('confirmed_at'), po.get('confirmed_by'))
    if po.get('closed_at'):
        _ev(events, 'po', 'PO ditutup' + (' kurang' if po.get('status') == 'Closed Short' else ''),
            po.get('closed_at'), po.get('closed_by'), po.get('close_notes') or po.get('closed_reason') or '')
    for ev in po.get('over_qty_events') or []:
        _ev(events, 'qty', f"{ev.get('step_label') or 'Kelebihan qty'}: {ev.get('label') or ''} {ev.get('qty')} pcs "
                           f"(batas {ev.get('limit')}, lebih {ev.get('over')})",
            ev.get('at'), ev.get('by'), f"Alasan: {ev.get('reason') or '-'}")

    items = await db.po_items.find({'po_id': po_id}, {'_id': 0, 'id': 1}).to_list(_LIM)
    item_ids = [i['id'] for i in items if i.get('id')]
    ships, _ = await _vendor_shipments(db, item_ids)
    for s in ships:
        _ev(events, 'kirim', f"Kiriman ke CMT {s['number']} ({s['type_label'].lower()}, {s['qty']} pcs)",
            s['date'], s.get('created_by'), s['vendor_name'])
        _ev(events, 'kirim', f"Kiriman {s['number']} diterima CMT", s.get('received_at'), '', s['vendor_name'])
    for r in await _receipts(db, po_id, item_ids):
        _ev(events, 'terima', f"Penerimaan dari CMT {r['number']} ({r['qty_claimed']} pcs)", r['date'],
            r.get('created_by'), r['vendor_name'])
        _ev(events, 'qc', f"QC {r['number']} selesai: lolos {r['qty_good']}, tolak {r['qty_reject']}",
            r.get('qc_done_at'))
    for p in await _permak(db, po_id):
        _ev(events, 'permak', f"Permak {p['number'] or p['sku']} ({p['qty']} pcs, {p['where_label'].lower()})",
            p['date'], '', p['status_label'])
    for s in await _buyer_shipments(db, item_ids):
        _ev(events, 'hasil', f"Kiriman hasil {s['number']} ({s['qty']} pcs)", s['date'], s.get('created_by'),
            s['status_label'])
    for b in (await _cmt_bills(db, po_id))[0]:
        _ev(events, 'tagihan', f"Tagihan CMT {b['number']} dibuat", b['date'], '', b['vendor_name'], b['amount'])
    samples = await db.dewi_maklon_samples.find(smp.sample_query_for_po(po_id), {'_id': 0}).to_list(200)
    for s in samples:
        code = s.get('sample_code') or ''
        _ev(events, 'sampel', f'Sampel {code} dibuat', s.get('created_at'), s.get('created_by'))
        _ev(events, 'sampel', f'Sampel {code} dikirim ke klien', s.get('submitted_at'), s.get('submitted_by'))
        _ev(events, 'sampel', f'Sampel {code} disetujui', s.get('approved_at'), s.get('approved_by_name'),
            s.get('approval_feedback') or '')
        _ev(events, 'sampel', f'Sampel {code} ditolak', s.get('rejected_at'), s.get('rejected_by_name'),
            s.get('rejection_reason') or '')
    sample_ids = [s.get('id') for s in samples if s.get('id')]
    revisions = await db.dewi_maklon_sample_revisions.find(
        {'sample_id': {'$in': sample_ids}}, {'_id': 0}).to_list(500) if sample_ids else []
    for r in revisions:
        _ev(events, 'sampel', f"Revisi sampel #{r.get('revision_number')}", r.get('created_at'),
            r.get('requested_by'), r.get('reason') or '')
    if po.get('business_type') == 'maklon':
        try:
            ar = await _client_ar(db, po_id)
            for p in (ar or {}).get('payments') or []:
                _ev(events, 'bayar', 'Pembayaran klien diterima', p['date'], '', p.get('number') or '', p['amount'])
        except Exception:  # noqa: BLE001
            logger.exception('riwayat bayar klien PO %s gagal dibaca', po_id)
    # catatan aktivitas yang menyebut nomor PO (perubahan status, ubah PO, dll.)
    if num:
        import re
        seen = {(e['label'], e['when']) for e in events}
        async for log in db.activity_logs.find({'details': {'$regex': re.escape(num), '$options': 'i'}},
                                               {'_id': 0}).sort('timestamp', -1).limit(50):
            when = _iso(log.get('timestamp'))
            label = humanize_log(log.get('details'))
            if not label or (label, when) in seen:
                continue
            _ev(events, 'catatan', label, log.get('timestamp'), log.get('user_name') or '')
    events.sort(key=lambda e: e.get('when') or '', reverse=True)
    return {'po_id': po_id, 'po_number': num, 'total_events': len(events), 'events': events}
