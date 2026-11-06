"""core.maklon_ledger — piutang klien & hutang CMT maklon TERJADWAL (Tahap 2, 6 Nov 2026).

Keputusan owner 6 Nov 2026 (mengikat):
  * Tidak ada langkah "terbitkan invoice" terpisah. Begitu PO maklon DIKONFIRMASI lahir:
      - piutang klien TERJADWAL = qty pesan × harga jasa ke klien (per baris/ukuran);
      - hutang CMT TERJADWAL per vendor = qty × upah CMT.
    Saat konfirmasi TIDAK ada jurnal.
  * Pendapatan dibukukan saat barang DIKIRIM ke klien (per kiriman, boleh sebagian):
      Dr Piutang klien (1-1305-<KODE>) / Cr Pendapatan klien (4-1500-<KODE>) (+ Cr PPN bila PKP).
  * Pembayaran klien sebelum pendapatan = uang muka (Dr Bank / Cr 2-1700) dan OTOMATIS dipakai
    menutup piutang saat pendapatan dibukukan (Dr 2-1700 / Cr Piutang).
  * Biaya CMT tetap lahir saat barang lolos QC (Dr 5-4200 / Cr 2-1110-vendor); tagihan itu
    ditempelkan ke jadwal hutang CMT PO. Hutang hanya bisa dibayar sampai nilai lolos QC
    dikurangi yang sudah dibayar; bagian selisih yang ditandai ditahan sampai Keuangan memutuskan.

SATU dokumen piutang per PO di `rahaza_ar_invoices` (SSOT piutang, `schedule_mode='v2'`) —
bukan koleksi piutang kedua. Jadwal hutang CMT per (PO, vendor) di `dewi_cmt_ap_schedules`.

Semua fungsi IDEMPOTEN: dipanggil ulang setiap kali PO/kiriman berubah (lewat
`production_maklon_bridge.sync_po_to_maklon_finance`) dan hanya membukukan SELISIH antara
yang seharusnya dan yang sudah dijurnal (rekonsiliasi), jadi tambah/ubah/hapus kiriman,
koreksi qty diterima, maupun penutupan PO selalu berakhir di angka yang sama.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SCHEDULE_MODE = 'v2'
# Status PO yang dianggap SUDAH DITUTUP (dikunci: tidak boleh kiriman/penerimaan/permak baru).
CLOSED_PO_STATUSES = ('Closed', 'Closed Short', 'Completed')
TERM_DAYS = {'net_7': 7, 'net_14': 14, 'net_30': 30, 'net_60': 60}


def _uid() -> str:
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _r2(v) -> float:
    return round(_f(v), 2)


def fmt_rp(v) -> str:
    return 'Rp ' + f"{_f(v):,.0f}".replace(',', '.')


def is_schedule(ar: dict | None) -> bool:
    return (ar or {}).get('schedule_mode') == SCHEDULE_MODE


def _tax(kena: bool, dpp: float) -> float:
    from core.tax_status import output_tax
    return float(output_tax({'pkp': bool(kena)}, dpp, apply=bool(kena))['tax_amount'] or 0)


def _iso(d) -> str:
    from utils.waktu import wib_date_of
    return wib_date_of(d) or ''


def _to_date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# AKUN PER KLIEN (Auto Akun: maklon_client → 1-1305-<KODE>, maklon_revenue → 4-1500-<KODE>)
# ══════════════════════════════════════════════════════════════════════════════
async def ensure_client_accounts(db, client: dict, user: dict | None = None) -> dict:
    """Buat (bila belum ada) sub-ledger piutang & akun pendapatan klien — dipanggil saat klien
    dibuat. Startup/backfill memakai mesin yang sama (`core.finance_sync._backfill_subledgers`)."""
    from routes.coa_auto import ensure_subledger_for_entity
    out = {}
    for etype in ('maklon_client', 'maklon_revenue'):
        res = await ensure_subledger_for_entity(db, etype, client, user)
        out[etype] = res.get('code') if res.get('ok') else None
        if not res.get('ok') and not res.get('skipped'):
            logger.error('[maklon] akun %s klien %s gagal dibuat: %s', etype, client.get('code') or client.get('id'),
                         res.get('error'))
    return out


async def client_accounts(db, client_id: str, user: dict | None = None) -> dict:
    """{'ar': kode piutang klien | None, 'revenue': kode pendapatan klien | None}."""
    if not client_id:
        return {'ar': None, 'revenue': None}
    from routes.coa_auto import resolve_subledger_account
    ar = await resolve_subledger_account(db, 'maklon_client', entity_id=client_id, user=user)
    rev = await resolve_subledger_account(db, 'maklon_revenue', entity_id=client_id, user=user)
    return {'ar': ar, 'revenue': rev}


# ══════════════════════════════════════════════════════════════════════════════
# PIUTANG KLIEN TERJADWAL
# ══════════════════════════════════════════════════════════════════════════════
async def find_ar(db, po_id: str) -> dict | None:
    """Dokumen piutang PO (aktif dulu, lalu yang terakhir dibatalkan)."""
    mirror = await db.dewi_maklon_pos.find_one({'id': po_id}, {'_id': 0, 'ar_invoice_id': 1})
    if (mirror or {}).get('ar_invoice_id'):
        ar = await db.rahaza_ar_invoices.find_one({'id': mirror['ar_invoice_id']}, {'_id': 0})
        if ar:
            return ar
    ar = await db.rahaza_ar_invoices.find_one(
        {'linked_maklon_po_id': po_id, 'source_module': 'maklon_po', 'status': {'$ne': 'cancelled'}}, {'_id': 0})
    return ar


async def _payments(db, ar_id: str) -> list:
    return [p async for p in db.rahaza_ar_payments.find(
        {'invoice_id': ar_id, 'source': 'maklon', 'status': {'$ne': 'voided'}}, {'_id': 0})]


def billable_targets(dispatch_lines: list, ordered: dict) -> tuple[dict, list]:
    """Murni: qty yang BOLEH ditagih per baris surat jalan buyer.

    Qty sampai batas pesanan (per item PO, urut tanggal kirim) selalu tertagih. Kelebihan di atas
    pesanan hanya ditagih bila baris kiriman itu membawa alasan kelebihan (`over_qty_reason`) —
    keputusan owner: lebih qty boleh, asal ada alasan jelas yang tersimpan.
    → ({shipment_item_id: qty_tagih}, [baris tertahan])."""
    from core import dispatch_capacity as dcap
    cum: dict = {}
    targets, held = {}, []
    rows = sorted(dispatch_lines or [], key=lambda x: (str(x.get('dispatch_date') or x.get('created_at') or ''),
                                                       _i(x.get('dispatch_seq')), str(x.get('id'))))
    for it in rows:
        poi = it.get('po_item_id')
        q = dcap.item_dispatched(it)
        room = max(0, _i(ordered.get(poi)) - cum.get(poi, 0))
        within = min(q, room)
        over = q - within
        reason = (it.get('over_qty_reason') or '').strip()
        bill = within + (over if reason else 0)
        if over and not reason:
            held.append({'shipment_item_id': it.get('id'), 'po_item_id': poi, 'qty': over,
                         'message': 'Kelebihan qty kirim tanpa alasan — tidak ditagih sampai alasannya diisi.'})
        cum[poi] = cum.get(poi, 0) + q
        targets[it['id']] = bill
    return targets, held


def ar_amounts(ar: dict, payments: list) -> dict:
    """Murni: angka piutang terjadwal dari status rekonsiliasi + pembayaran."""
    billed_sub = _r2(sum(_f(r.get('amount_posted')) for r in ar.get('revenue_lines') or []))
    billed_tax = _r2(sum(_f(p.get('tax')) * (-1 if p.get('reverse') else 1) for p in ar.get('revenue_postings') or []))
    billed_total = _r2(billed_sub + billed_tax)
    paid_total = _r2(sum(_f(p.get('amount')) for p in payments))
    ar_direct = _r2(sum(_f(p.get('ar_portion')) for p in payments))
    applied = _r2(sum(_f(a.get('amount')) for a in ar.get('advance_postings') or []))
    ar_credit = _r2(ar_direct + applied)
    return {'billed_subtotal': billed_sub, 'billed_tax': billed_tax, 'billed_total': billed_total,
            'paid_total': paid_total, 'ar_direct': ar_direct, 'advance_applied': applied,
            'ar_credit': ar_credit, 'advance_balance': _r2(paid_total - ar_credit),
            'amount_due': _r2(max(0.0, billed_total - ar_credit))}


def due_date_fifo(postings: list, ar_credit: float, term_days: int) -> str | None:
    """Murni: jatuh tempo = tanggal kiriman tertua yang belum tertutup pembayaran + termin."""
    left = _f(ar_credit)
    for p in sorted([p for p in postings or [] if not p.get('reverse')], key=lambda x: str(x.get('date') or '')):
        amt = _f(p.get('total'))
        if left + 0.005 >= amt:
            left -= amt
            continue
        d = _to_date(p.get('date'))
        return (d + timedelta(days=term_days)).isoformat() if d else None
    return None


def ar_status(*, amount_due: float, billed_total: float, scheduled_total: float, ar_credit: float,
              due_date: str | None, po_closed: bool, paid_total: float) -> str:
    """Murni: status piutang terjadwal.
    terjadwal (`scheduled`) = belum ada piutang jatuh tempo, masih ada qty yang akan dikirim."""
    from utils.waktu import today_wib
    if amount_due > 0.005:
        d = _to_date(due_date)
        if d and d < today_wib():
            return 'overdue'
        return 'partial_paid' if ar_credit > 0.005 else 'issued'
    if scheduled_total - billed_total > 0.005:
        return 'scheduled'
    if billed_total > 0.005:
        return 'paid'
    if po_closed and paid_total <= 0.005:
        return 'cancelled'
    return 'scheduled'


async def _create_ar_doc(db, po: dict, user: dict, accounts: dict) -> dict:
    from routes.dewi_maklon_pos import _next_ar_invoice_number
    from routes.dewi_system_config import get_config_value
    from utils.waktu import today_wib
    term = await get_config_value(db, 'maklon_payment_terms_default', 'net_30') or 'net_30'
    client = await db.dewi_maklon_clients.find_one({'id': po.get('buyer_id')}, {'_id': 0, 'code': 1}) or {}
    doc = {
        'id': _uid(), 'invoice_number': await _next_ar_invoice_number(db),
        'source_module': 'maklon_po', 'schedule_mode': SCHEDULE_MODE,
        'linked_maklon_po_id': po['id'], 'linked_maklon_po_number': po.get('po_number', ''),
        'customer_id': po.get('buyer_id'), 'customer_name': po.get('customer_name', ''),
        'client_code': client.get('code', ''),
        'invoice_date': today_wib().isoformat(), 'issue_date': today_wib().isoformat(),
        'scheduled_at': today_wib().isoformat(), 'due_date': None, 'payment_terms': term,
        'lines': [], 'revenue_lines': [], 'revenue_postings': [], 'advance_postings': [],
        'subtotal': 0.0, 'tax_pct': 0.0, 'tax_amount': 0.0, 'discount_amount': 0.0,
        'total_amount': 0.0, 'total': 0.0, 'amount_paid': 0.0, 'paid_amount': 0.0,
        'amount_due': 0.0, 'balance': 0.0, 'status': 'scheduled',
        'gl_ar_account_code': accounts.get('ar'), 'revenue_account_code': accounts.get('revenue'),
        'notes': f"Piutang terjadwal PO maklon {po.get('po_number', '')}",
        'gl_posted_at': None, 'gl_je_id': None, 'post_error': None,
        'created_at': _now(), 'updated_at': _now(), 'created_by': (user or {}).get('id', ''),
    }
    await db.rahaza_ar_invoices.insert_one(dict(doc))
    return doc


async def _revenue_reconcile(db, ar: dict, po: dict, items: list, accounts: dict, user: dict) -> dict:
    """Bukukan SELISIH pendapatan per kiriman (positif = pendapatan, negatif = pembalik)."""
    from core import dispatch_capacity as dcap
    from routes.dewi_maklon_finance import post_maklon_revenue
    from utils.waktu import today_wib

    item_ids = [i['id'] for i in items]
    price = {i['id']: _f(i.get('selling_price_snapshot')) for i in items}
    ordered = {i['id']: _i(i.get('qty')) for i in items}
    disp = await dcap.buyer_dispatch_items(db, po_item_ids=item_ids) if item_ids else []
    by_id = {d['id']: d for d in disp}
    targets, held = billable_targets(disp, ordered)
    state = {r['shipment_item_id']: dict(r) for r in ar.get('revenue_lines') or []}
    for sid in state:
        targets.setdefault(sid, 0)        # baris kiriman yang dihapus → dibalik ke 0
    ship_nums = {}
    sids = list({(by_id.get(s) or state.get(s) or {}).get('shipment_id') for s in targets} - {None})
    async for s in db.buyer_shipments.find({'id': {'$in': sids}}, {'_id': 0, 'id': 1, 'shipment_number': 1}):
        ship_nums[s['id']] = s.get('shipment_number', '')

    groups: dict = {}
    errors = []
    for sid, tq in targets.items():
        st = state.get(sid) or {}
        src = by_id.get(sid) or st
        poi = src.get('po_item_id')
        dq = _i(tq) - _i(st.get('qty_posted'))
        if dq == 0:
            continue
        unit = _f(st.get('unit_price')) if st.get('unit_price') else price.get(poi, 0.0)
        if unit <= 0:
            errors.append(f"Harga jasa baris {src.get('sku') or poi} kosong — pendapatan tidak bisa dicatat.")
            continue
        key = (src.get('shipment_id') or '', _i(src.get('dispatch_seq')), 1 if dq > 0 else -1)
        groups.setdefault(key, []).append({
            'shipment_item_id': sid, 'shipment_id': src.get('shipment_id'), 'dispatch_seq': _i(src.get('dispatch_seq')),
            'po_item_id': poi, 'sku': src.get('sku', ''), 'size': src.get('size', ''), 'qty': dq,
            'unit_price': unit, 'amount': round(dq * unit, 2),
            'dispatch_date': _iso(src.get('dispatch_date') or src.get('created_at'))})

    postings = list(ar.get('revenue_postings') or [])
    kena = bool(ar.get('kena_ppn'))
    billed_sub = _r2(sum(_f(r.get('amount_posted')) for r in state.values()))
    billed_tax = _r2(sum(_f(p.get('tax')) * (-1 if p.get('reverse') else 1) for p in postings))
    ar_code = ar.get('gl_ar_account_code') or accounts.get('ar')
    rev_code = ar.get('revenue_account_code') or accounts.get('revenue')
    if groups and not rev_code:
        errors.append('Akun pendapatan klien maklon (4-1500-<kode klien>) belum ada — pastikan PO memakai '
                      'Klien Maklon dari master, lalu sinkronkan ulang.')
        groups = {}
    if groups and not ar_code:
        mapping_ar = None
        try:
            from routes.rahaza_posting_profiles import get_mapping
            mapping_ar = (await get_mapping(db, 'maklon_ar_invoice') or {}).get('debit_ar')
        except Exception:  # noqa: BLE001
            mapping_ar = None
        ar_code = mapping_ar
    today = today_wib()
    for (ship_id, seq, sign), lines in sorted(groups.items(), key=lambda kv: (-kv[0][2], kv[0][0], kv[0][1])):
        amount = _r2(sum(abs(x['amount']) for x in lines))
        new_sub = _r2(billed_sub + sign * amount)
        tax_delta = _r2(abs(_tax(kena, new_sub) - billed_tax)) if kena else 0.0
        n = len([p for p in postings if p.get('shipment_id') == ship_id and p.get('dispatch_seq') == seq])
        first = sign > 0 and n == 0
        d_disp = _to_date(lines[0].get('dispatch_date')) if first else None
        je_date = d_disp if (d_disp and d_disp <= today) else today
        memo = (f"Pendapatan maklon {po.get('po_number', '')} · {po.get('customer_name', '')} · "
                f"SJ {ship_nums.get(ship_id, '')} kirim ke-{seq}" + ('' if sign > 0 else ' (koreksi turun)'))
        ref = f"mklrev:{ar['id']}:{ship_id}:{seq}:{n}"
        res = await post_maklon_revenue(db, ar_code=ar_code, rev_code=rev_code, amount=amount, tax=tax_delta,
                                        reverse=sign < 0, je_date=je_date, memo=memo, source_ref=ref, user=user)
        if not res.get('ok') and je_date != today:
            # periode tanggal kirim sudah ditutup → dibukukan hari ini (jurnal lama tidak diubah)
            res = await post_maklon_revenue(db, ar_code=ar_code, rev_code=rev_code, amount=amount, tax=tax_delta,
                                            reverse=sign < 0, je_date=today, memo=memo, source_ref=ref, user=user)
            je_date = today
        if not res.get('ok'):
            errors.append(res.get('error') or 'jurnal pendapatan gagal')
            continue
        for x in lines:
            st = state.setdefault(x['shipment_item_id'], {
                'shipment_item_id': x['shipment_item_id'], 'shipment_id': x['shipment_id'],
                'dispatch_seq': x['dispatch_seq'], 'po_item_id': x['po_item_id'], 'sku': x['sku'],
                'size': x['size'], 'qty_posted': 0, 'unit_price': x['unit_price'], 'amount_posted': 0.0,
                'dispatch_date': x['dispatch_date']})
            st['qty_posted'] = _i(st.get('qty_posted')) + x['qty']
            st['amount_posted'] = _r2(_f(st.get('amount_posted')) + x['amount'])
        billed_sub = new_sub
        billed_tax = _r2(billed_tax + sign * tax_delta)
        postings.append({'id': _uid(), 'shipment_id': ship_id, 'shipment_number': ship_nums.get(ship_id, ''),
                         'dispatch_seq': seq, 'n': n, 'reverse': sign < 0, 'date': je_date.isoformat(),
                         'subtotal': amount, 'tax': tax_delta, 'total': _r2(amount + tax_delta),
                         'je_id': res.get('je_id'), 'je_number': res.get('je_number'),
                         'lines': [{k: x[k] for k in ('shipment_item_id', 'po_item_id', 'sku', 'size', 'qty',
                                                      'unit_price', 'amount')} for x in lines],
                         'at': _now()})
    return {'revenue_lines': [v for v in state.values() if _i(v.get('qty_posted')) != 0 or _f(v.get('amount_posted'))],
            'revenue_postings': postings, 'revenue_held': held, 'errors': errors,
            'gl_ar_account_code': ar_code, 'revenue_account_code': rev_code,
            'dispatch_lines': disp}


async def _advance_reconcile(db, ar: dict, payments: list, user: dict) -> dict:
    """Uang muka otomatis menutup piutang: Σ kredit piutang = min(Σ dibayar, Σ tertagih)."""
    from routes.dewi_maklon_finance import maklon_advance_account, post_maklon_advance_apply
    from utils.waktu import today_wib
    a = ar_amounts(ar, payments)
    target = _r2(min(a['paid_total'], a['billed_total']))
    delta = _r2(target - a['ar_credit'])
    postings = list(ar.get('advance_postings') or [])
    if abs(delta) < 0.01:
        return {'advance_postings': postings, 'error': None}
    adv_code = await maklon_advance_account(db)
    n = len(postings)
    memo = (f"Uang muka klien maklon {'dipakai menutup' if delta > 0 else 'dikembalikan dari'} piutang "
            f"{ar.get('invoice_number', '')} ({ar.get('linked_maklon_po_number', '')})")
    res = await post_maklon_advance_apply(db, ar_code=ar.get('gl_ar_account_code'), adv_code=adv_code,
                                          amount=delta, je_date=today_wib(), memo=memo,
                                          source_ref=f"mkladv:{ar['id']}:{n}", user=user)
    if not res.get('ok'):
        return {'advance_postings': postings, 'error': res.get('error')}
    postings.append({'id': _uid(), 'n': n, 'amount': delta, 'date': today_wib().isoformat(),
                     'je_id': res.get('je_id'), 'je_number': res.get('je_number'), 'at': _now()})
    return {'advance_postings': postings, 'error': None}


async def sync_ar_schedule(db, po_id: str, user: dict | None = None) -> dict:
    """Buat/segarkan piutang terjadwal PO maklon + bukukan selisih pendapatan & pemakaian uang muka.

    Dokumen invoice LAMA yang sudah terbit (alur sebelum 6 Nov 2026) dibiarkan di alur lamanya
    (`legacy=True`) supaya tidak ada pendapatan ganda. Draft lama dikonversi."""
    from core import dispatch_capacity as dcap
    from core.tax_status import get_tax_profile, effective_pct
    user = user or {'id': 'system', 'name': 'sistem'}
    po = await db.production_pos.find_one({'id': po_id}, {'_id': 0})
    if not po or po.get('business_type') != 'maklon':
        return {'ok': False, 'skipped': 'bukan PO maklon'}
    if (po.get('status') or 'Draft') == 'Draft':
        return {'ok': True, 'skipped': 'draft'}
    ar = await find_ar(db, po_id)
    if ar and not is_schedule(ar):
        if (ar.get('status') or 'draft') == 'draft' and not ar.get('gl_je_id'):
            await db.rahaza_ar_invoices.update_one({'id': ar['id']}, {'$set': {
                'schedule_mode': SCHEDULE_MODE, 'converted_from_draft_at': _now(),
                'revenue_lines': [], 'revenue_postings': [], 'advance_postings': []}})
            ar = await db.rahaza_ar_invoices.find_one({'id': ar['id']}, {'_id': 0})
        else:
            return {'ok': True, 'legacy': True, 'ar_id': ar['id'], 'ar_invoice_number': ar.get('invoice_number')}
    accounts = await client_accounts(db, po.get('buyer_id'), user)
    if not ar:
        ar = await _create_ar_doc(db, po, user, accounts)
    if ar.get('status') == 'cancelled':
        return {'ok': True, 'cancelled': True, 'ar_id': ar['id']}

    items = await db.po_items.find({'po_id': po_id}, {'_id': 0}).sort('created_at', 1).to_list(None)
    # PPN: mengikuti Status Pajak perusahaan SELAMA belum ada pendapatan; sesudah itu DIBEKUKAN.
    if not ar.get('revenue_postings'):
        prof = await get_tax_profile(db)
        ar['kena_ppn'] = bool(prof.get('pkp'))
    if not ar.get('gl_ar_account_code') and accounts.get('ar'):
        ar['gl_ar_account_code'] = accounts['ar']
    if not ar.get('revenue_account_code') and accounts.get('revenue'):
        ar['revenue_account_code'] = accounts['revenue']

    rec = await _revenue_reconcile(db, ar, po, items, accounts, user)
    ar.update({k: rec[k] for k in ('revenue_lines', 'revenue_postings', 'gl_ar_account_code',
                                   'revenue_account_code')})
    payments = await _payments(db, ar['id'])
    adv = await _advance_reconcile(db, ar, payments, user)
    ar['advance_postings'] = adv['advance_postings']

    # ── baris jadwal per item: qty pesan (PO terbuka) / qty tertagih (PO ditutup) ──
    po_closed = po.get('status') in CLOSED_PO_STATUSES
    qmap = await dcap.po_item_quantities(db, [i['id'] for i in items]) if items else {}
    billed_q, billed_amt = {}, {}
    for r in ar['revenue_lines']:
        billed_q[r.get('po_item_id')] = billed_q.get(r.get('po_item_id'), 0) + _i(r.get('qty_posted'))
        billed_amt[r.get('po_item_id')] = _r2(billed_amt.get(r.get('po_item_id'), 0) + _f(r.get('amount_posted')))
    lines, sched_sub = [], 0.0
    for idx, pi in enumerate(items, start=1):
        qo = _i(pi.get('qty'))
        qb = billed_q.get(pi['id'], 0)
        qs = qb if po_closed else max(qo, qb)
        unit = _f(pi.get('selling_price_snapshot'))
        amt = _r2(billed_amt.get(pi['id'], 0) + max(0, qs - qb) * unit)
        sched_sub += amt
        lines.append({'line_id': pi['id'], 'item_id': pi['id'],
                      'description': (f"Jasa maklon — {pi.get('product_name', '')} {pi.get('color', '')} "
                                      f"{pi.get('size', '')} (Seri {pi.get('serial_number') or idx})").strip(),
                      'sku': pi.get('sku', ''), 'size': pi.get('size', ''), 'color': pi.get('color', ''),
                      'qty': qo, 'qty_ordered': qo, 'qty_scheduled': qs, 'unit': 'pcs', 'unit_price': unit,
                      'subtotal': amt, 'line_total': amt, 'qty_billed': qb,
                      'amount_billed': billed_amt.get(pi['id'], 0.0),
                      'qty_dispatched': _i((qmap.get(pi['id']) or {}).get('dispatched'))})
    sched_sub = _r2(sched_sub)
    kena = bool(ar.get('kena_ppn'))
    sched_tax = _r2(_tax(kena, sched_sub)) if kena else 0.0
    a = ar_amounts(ar, payments)
    term = ar.get('payment_terms') or 'net_30'
    due = due_date_fifo(ar['revenue_postings'], a['ar_credit'], TERM_DAYS.get(term, 30))
    sched_total = _r2(sched_sub + sched_tax)
    status = ar_status(amount_due=a['amount_due'], billed_total=a['billed_total'], scheduled_total=sched_total,
                       ar_credit=a['ar_credit'], due_date=due, po_closed=po_closed, paid_total=a['paid_total'])
    first = min([p.get('date') for p in ar['revenue_postings'] if not p.get('reverse')] or [None], key=lambda x: x or '')
    errors = list(rec['errors']) + ([adv['error']] if adv.get('error') else [])
    upd = {
        'lines': lines, 'revenue_lines': ar['revenue_lines'], 'revenue_postings': ar['revenue_postings'],
        'revenue_held': rec['revenue_held'], 'advance_postings': ar['advance_postings'],
        'kena_ppn': kena, 'ppn_rate': 12.0 if kena else 0.0, 'tax_pct': effective_pct() if kena else 0.0,
        'scheduled_subtotal': sched_sub, 'scheduled_tax': sched_tax, 'scheduled_total': sched_total,
        'billed_subtotal': a['billed_subtotal'], 'billed_tax': a['billed_tax'], 'billed_total': a['billed_total'],
        # kolom kanonik AR = yang SUDAH menjadi piutang (pendapatan dibukukan), supaya laporan penjualan,
        # umur piutang & neraca tidak menghitung jadwal yang barangnya belum dikirim.
        'subtotal': a['billed_subtotal'], 'tax_amount': a['billed_tax'],
        'total_amount': a['billed_total'], 'total': a['billed_total'],
        'amount_paid': a['paid_total'], 'paid_amount': a['paid_total'],
        'amount_due': a['amount_due'], 'balance': a['amount_due'],
        'ar_credit': a['ar_credit'], 'advance_received': _r2(a['paid_total'] - a['ar_direct']),
        'advance_applied': a['advance_applied'], 'advance_balance': a['advance_balance'],
        'outstanding_total': _r2(max(sched_total, a['billed_total']) - a['paid_total']),
        'scheduled_remaining': _r2(max(0.0, sched_total - a['billed_total'])),
        'due_date': due, 'status': status,
        'customer_id': po.get('buyer_id'), 'customer_name': po.get('customer_name', ''),
        'linked_maklon_po_number': po.get('po_number', ''), 'po_status': po.get('status'),
        'gl_ar_account_code': ar.get('gl_ar_account_code'), 'revenue_account_code': ar.get('revenue_account_code'),
        'post_error': '; '.join(e for e in errors if e) or None,
        'post_error_at': _now() if errors else None, 'updated_at': _now(),
    }
    if first:
        upd['invoice_date'] = upd['issue_date'] = first
    await db.rahaza_ar_invoices.update_one({'id': ar['id']}, {'$set': upd})
    return {'ok': True, 'ar_id': ar['id'], 'ar_invoice_number': ar.get('invoice_number'), 'status': status,
            'scheduled_total': sched_total, 'billed_total': a['billed_total'], 'errors': errors}


async def record_client_payment(db, ar_id: str, *, amount: float, cash_account_id: str, payment_date: str | None,
                                notes: str = '', reference_no: str = '', user: dict) -> dict:
    """Catat pembayaran klien terhadap piutang PO: tutup piutang yang sudah jatuh dulu, sisanya uang muka.
    Melempar ValueError (pesan untuk pengguna) bila ditolak."""
    from routes.dewi_maklon_finance import maklon_advance_account, post_maklon_client_payment
    from routes.rahaza_posting_profiles import get_mapping
    from utils.waktu import today_wib
    ar = await db.rahaza_ar_invoices.find_one({'id': ar_id}, {'_id': 0})
    if not ar or not is_schedule(ar):
        raise ValueError('Piutang maklon tidak ditemukan.')
    if ar.get('status') == 'cancelled':
        raise ValueError('Piutang PO ini sudah dibatalkan.')
    amount = _r2(amount)
    if amount <= 0:
        raise ValueError('Jumlah pembayaran harus lebih dari 0.')
    acc = await db.rahaza_cash_accounts.find_one({'id': cash_account_id, 'active': {'$ne': False}}, {'_id': 0}) \
        if cash_account_id else None
    if not acc:
        raise ValueError('Pilih rekening kas/bank penerima yang aktif.')
    # angka terbaru dulu (pendapatan kiriman terakhir)
    await sync_ar_schedule(db, ar['linked_maklon_po_id'], user)
    ar = await db.rahaza_ar_invoices.find_one({'id': ar_id}, {'_id': 0})
    cap = _r2(max(_f(ar.get('scheduled_total')), _f(ar.get('billed_total'))) - _f(ar.get('amount_paid')))
    if amount > cap + 0.5:
        raise ValueError(f"Pembayaran melebihi sisa tagihan PO ({fmt_rp(cap)}).")
    if not ar.get('gl_ar_account_code'):
        accounts = await client_accounts(db, ar.get('customer_id'), user)
        ar['gl_ar_account_code'] = accounts.get('ar') or (await get_mapping(db, 'maklon_ar_invoice') or {}).get('debit_ar')
    ar_portion = _r2(min(amount, _f(ar.get('amount_due'))))
    adv_portion = _r2(amount - ar_portion)
    cash_code = acc.get('gl_account_code') or (await get_mapping(db, 'maklon_advance_payment') or {}).get('debit_cash_default')
    pay_id = _uid()
    pdate = (payment_date or today_wib().isoformat())[:10]
    d = _to_date(pdate) or today_wib()
    memo = (f"Pembayaran klien maklon {ar.get('invoice_number', '')} · {ar.get('customer_name', '')} · "
            f"PO {ar.get('linked_maklon_po_number', '')}" + (f" · {reference_no}" if reference_no else ''))
    res = await post_maklon_client_payment(db, cash_code=cash_code, ar_code=ar.get('gl_ar_account_code'),
                                           adv_code=await maklon_advance_account(db), ar_portion=ar_portion,
                                           adv_portion=adv_portion, je_date=d, memo=memo,
                                           source_ref=f"mklpay:{pay_id}", user=user)
    if not res.get('ok'):
        raise ValueError(f"Pembayaran tidak dicatat — jurnal gagal: {res.get('error')}")
    await db.rahaza_cash_movements.insert_one({
        'id': pay_id, 'account_id': acc['id'], 'account_name': acc.get('name'), 'direction': 'in',
        'amount': round(amount), 'category': 'ar_payment', 'ref_id': ar_id, 'ref_label': ar.get('invoice_number'),
        'source_module': 'maklon_payment', 'date': pdate, 'notes': notes or memo, 'je_id': res.get('je_id'),
        'timestamp': _now(), 'created_by': user.get('id'), 'created_by_name': user.get('name', '')})
    doc = {'id': pay_id, 'invoice_id': ar_id, 'invoice_number': ar.get('invoice_number'), 'source': 'maklon',
           'po_id': ar.get('linked_maklon_po_id'), 'po_number': ar.get('linked_maklon_po_number'),
           'customer_id': ar.get('customer_id'), 'amount': amount, 'date': pdate,
           'ar_portion': ar_portion, 'advance_portion': adv_portion, 'account_id': acc['id'],
           'movement_id': pay_id, 'reference_no': reference_no or '', 'notes': notes or '', 'status': 'posted',
           'gl_je_id': res.get('je_id'), 'gl_je_number': res.get('je_number'),
           'created_at': _now(), 'created_by': user.get('id'), 'created_by_name': user.get('name', '')}
    await db.rahaza_ar_payments.insert_one(dict(doc))
    await sync_ar_schedule(db, ar['linked_maklon_po_id'], user)
    return doc


async def void_client_payment(db, ar_id: str, payment_id: str, user: dict, reason: str = '') -> dict:
    """Batalkan satu pembayaran klien (jurnal di-void, mutasi kas dihapus, jadwal disegarkan)."""
    from routes.dewi_maklon_finance import SRC_MAKLON_PAYMENT
    from routes.rahaza_posting import _void_je_by_source
    p = await db.rahaza_ar_payments.find_one({'id': payment_id, 'invoice_id': ar_id, 'source': 'maklon'}, {'_id': 0})
    if not p or p.get('status') == 'voided':
        raise ValueError('Pembayaran tidak ditemukan.')
    v = await _void_je_by_source(db, SRC_MAKLON_PAYMENT, f"mklpay:{payment_id}", user, reason or 'Pembayaran dibatalkan')
    if not v.get('ok'):
        raise ValueError(f"Jurnal tidak bisa dibatalkan: {v.get('error')}")
    await db.rahaza_cash_movements.delete_one({'id': payment_id})
    await db.rahaza_ar_payments.update_one({'id': payment_id}, {'$set': {
        'status': 'voided', 'voided_at': _now(), 'voided_by': user.get('id'), 'void_reason': reason}})
    await sync_ar_schedule(db, p.get('po_id'), user)
    return {'ok': True, 'voided_je': v.get('je_number')}


async def cancel_blockers(db, po_id: str) -> list:
    """Alasan PO maklon TIDAK boleh dibatalkan/dihapus: sudah ada jurnal (pendapatan, pembayaran,
    atau tagihan CMT lolos QC). Kosong = boleh, jadwal tinggal di-void."""
    out = []
    ar = await find_ar(db, po_id)
    if ar and is_schedule(ar):
        if any(_i(r.get('qty_posted')) for r in ar.get('revenue_lines') or []):
            out.append('pendapatan sudah dibukukan dari kiriman ke klien')
        if await db.rahaza_ar_payments.find_one({'invoice_id': ar['id'], 'source': 'maklon',
                                                 'status': {'$ne': 'voided'}}, {'_id': 1}):
            out.append('klien sudah membayar (uang muka/pelunasan)')
    elif ar and (ar.get('status') or 'draft') not in ('draft', 'cancelled'):
        out.append(f"faktur {ar.get('invoice_number')} sudah terbit")
    if await db.dewi_cmt_payments.find_one({'po_id': po_id, 'status': {'$nin': ['cancelled', 'void', 'voided']}},
                                           {'_id': 1}):
        out.append('tagihan CMT sudah lahir dari barang lolos QC')
    return out


async def void_schedules(db, po_id: str, user: dict, reason: str = '') -> dict:
    """PO dibatalkan sebelum ada jurnal: jadwal piutang & hutang CMT di-void (dokumen tetap ada)."""
    blockers = await cancel_blockers(db, po_id)
    if blockers:
        raise ValueError('PO tidak bisa dibatalkan karena ' + '; '.join(blockers) +
                         '. Tutup PO (tutup kurang) sebagai gantinya.')
    ar = await find_ar(db, po_id)
    if ar:
        await db.rahaza_ar_invoices.update_one({'id': ar['id']}, {'$set': {
            'status': 'cancelled', 'cancelled_at': _now(), 'cancelled_by': user.get('name', ''),
            'cancel_reason': reason, 'amount_due': 0.0, 'balance': 0.0, 'scheduled_remaining': 0.0,
            'updated_at': _now()}})
    await db.dewi_cmt_ap_schedules.update_many({'po_id': po_id}, {'$set': {
        'status': 'cancelled', 'payable_amount': 0.0, 'updated_at': _now()}})
    return {'ok': True, 'ar_id': (ar or {}).get('id')}


# ══════════════════════════════════════════════════════════════════════════════
# HUTANG CMT TERJADWAL + GERBANG BAYAR
# ══════════════════════════════════════════════════════════════════════════════
def _bill_amount(p: dict) -> float:
    for k in ('net_amount', 'total_amount', 'subtotal'):
        if p.get(k) not in (None, ''):
            return _f(p.get(k))
    return 0.0


def cmt_bill_blocked(p: dict) -> float:
    """Nilai tagihan CMT yang DITAHAN: lebih tagih (sudah ditagih tapi tidak lagi lolos QC) yang
    belum diputuskan Keuangan. Murni."""
    if (p or {}).get('variance_resolution'):
        return 0.0
    if not (p.get('needs_finance_review') or p.get('variance_flagged')):
        return 0.0
    return _r2(p.get('overbilled_amount'))


def cmt_bill_payable(p: dict) -> float:
    """Bisa dibayar = nilai lolos QC (tagihan) − sudah dibayar − bagian tertahan. Murni."""
    return _r2(max(0.0, _bill_amount(p) - _f(p.get('paid_amount')) - cmt_bill_blocked(p)))


def split_by_vendor(items: list, sent: list, header_vendor: str, po_closed: bool) -> dict:
    """Murni: qty jadwal hutang CMT per vendor per item PO.

    Qty yang SUDAH dikirim ke vendor (surat jalan NORMAL) milik vendor itu; sisa pesanan yang
    belum dikirim dijadwalkan ke vendor PO (header). PO ditutup → sisa tidak dijadwalkan lagi.
    `sent` = [{vendor_id, po_item_id, qty}]. → {vendor_id: {po_item_id: qty}}"""
    out: dict = {}
    sent_by_item: dict = {}
    for s in sent:
        v = s.get('vendor_id') or ''
        out.setdefault(v, {})
        out[v][s['po_item_id']] = out[v].get(s['po_item_id'], 0) + _i(s.get('qty'))
        sent_by_item[s['po_item_id']] = sent_by_item.get(s['po_item_id'], 0) + _i(s.get('qty'))
    if not po_closed:
        for it in items:
            rest = max(0, _i(it.get('qty')) - sent_by_item.get(it['id'], 0))
            if rest:
                out.setdefault(header_vendor or '', {})
                out[header_vendor or ''][it['id']] = out[header_vendor or ''].get(it['id'], 0) + rest
    return out


async def refresh_ap_schedules(db, po_id: str, user: dict | None = None) -> list:
    """Jadwal hutang CMT per (PO maklon, vendor): qty × upah CMT, ditambah angka nyata tagihan
    lolos QC (`dewi_cmt_payments`): matang / dibayar / tertahan / bisa dibayar."""
    from core import cmt_vendor_master
    po = await db.production_pos.find_one({'id': po_id}, {'_id': 0})
    if not po or po.get('business_type') != 'maklon' or (po.get('status') or 'Draft') == 'Draft':
        return []
    items = await db.po_items.find({'po_id': po_id}, {'_id': 0}).to_list(None)
    by_item = {i['id']: i for i in items}
    vsi = await db.vendor_shipment_items.find({'po_item_id': {'$in': list(by_item)}}, {'_id': 0}).to_list(None) \
        if by_item else []
    ship_ids = list({x.get('shipment_id') for x in vsi if x.get('shipment_id')})
    ships = {s['id']: s async for s in db.vendor_shipments.find({'id': {'$in': ship_ids}}, {'_id': 0})} if ship_ids else {}
    canon: dict = {}

    async def _canon(v):
        if v not in canon:
            canon[v] = (await cmt_vendor_master.canonical_id(db, v)) or v or ''
        return canon[v]
    sent = []
    for x in vsi:
        sh = ships.get(x.get('shipment_id')) or {}
        if (sh.get('shipment_type') or x.get('shipment_type') or 'NORMAL').upper() != 'NORMAL':
            continue
        sent.append({'vendor_id': await _canon(sh.get('vendor_id') or ''), 'po_item_id': x.get('po_item_id'),
                     'qty': _i(x.get('qty_sent'))})
    split = split_by_vendor(items, sent, await _canon(po.get('vendor_id') or ''),
                            po.get('status') in CLOSED_PO_STATUSES)
    bills = [p async for p in db.dewi_cmt_payments.find({'po_id': po_id}, {'_id': 0})
             if str(p.get('status') or '').lower() not in ('cancelled', 'void', 'voided')]
    bills_by_vendor: dict = {}
    for b in bills:
        v = b.get('vendor_id') or await _canon(b.get('cmt_partner_id') or '')
        bills_by_vendor.setdefault(v, []).append(b)
    vnames = {}
    vids = [v for v in set(split) | set(bills_by_vendor) if v]
    async for vp in db.vendor_partners.find({'id': {'$in': vids}}, {'_id': 0, 'id': 1, 'name': 1}):
        vnames[vp['id']] = vp.get('name', '')
    out = []
    for vid in sorted(set(split) | set(bills_by_vendor)):
        lines = []
        for poi, q in (split.get(vid) or {}).items():
            it = by_item.get(poi) or {}
            rate = _f(it.get('cmt_price_snapshot'))
            lines.append({'po_item_id': poi, 'sku': it.get('sku', ''), 'product_name': it.get('product_name', ''),
                          'size': it.get('size', ''), 'color': it.get('color', ''), 'qty': q, 'cmt_rate': rate,
                          'amount': _r2(q * rate)})
        vb = bills_by_vendor.get(vid) or []
        matured = _r2(sum(_bill_amount(b) for b in vb))
        paid = _r2(sum(_f(b.get('paid_amount')) for b in vb))
        blocked = _r2(sum(cmt_bill_blocked(b) for b in vb))
        payable = _r2(sum(cmt_bill_payable(b) for b in vb))
        sched = _r2(sum(x['amount'] for x in lines))
        existing = await db.dewi_cmt_ap_schedules.find_one({'po_id': po_id, 'vendor_id': vid}, {'_id': 0, 'id': 1})
        sid = (existing or {}).get('id') or _uid()
        status = ('lunas' if matured > 0 and paid >= max(matured, sched) - 0.01
                  else 'berjalan' if matured > 0 else 'terjadwal')
        doc = {'po_id': po_id, 'po_number': po.get('po_number', ''), 'business_type': 'maklon',
               'vendor_id': vid, 'vendor_name': vnames.get(vid) or (vb[0].get('cmt_name') if vb else '') or
               (po.get('vendor_name') if vid else 'Vendor belum ditentukan'),
               'lines': lines, 'scheduled_qty': sum(x['qty'] for x in lines), 'scheduled_amount': sched,
               'matured_amount': matured, 'matured_pcs': sum(_i(b.get('total_pcs')) for b in vb),
               'paid_amount': paid, 'blocked_amount': blocked, 'payable_amount': payable,
               'outstanding_amount': _r2(max(sched, matured) - paid),
               'bill_ids': [b['id'] for b in vb], 'status': status, 'updated_at': _now()}
        if existing:
            await db.dewi_cmt_ap_schedules.update_one({'id': sid}, {'$set': doc})
        else:
            await db.dewi_cmt_ap_schedules.insert_one({'id': sid, **doc, 'created_at': _now(),
                                                       'created_by': (user or {}).get('id', 'system')})
        for b in vb:
            if b.get('ap_schedule_id') != sid:
                await db.dewi_cmt_payments.update_one({'id': b['id']}, {'$set': {'ap_schedule_id': sid}})
        out.append({'id': sid, **doc})
    # vendor lama yang tidak lagi dijadwalkan & tanpa tagihan → dibatalkan
    keep = {o['vendor_id'] for o in out}
    async for s in db.dewi_cmt_ap_schedules.find({'po_id': po_id}, {'_id': 0, 'id': 1, 'vendor_id': 1}):
        if s.get('vendor_id') not in keep:
            await db.dewi_cmt_ap_schedules.update_one({'id': s['id']}, {'$set': {'status': 'cancelled',
                                                                                'updated_at': _now()}})
    return out
