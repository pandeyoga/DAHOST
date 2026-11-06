"""
CV. Dewi Aditya — Portal Maklon Billing & Invoice
Phase 3C: Auto-generate invoice from orders, payment tracking, monthly reports, HPP

Collections:
- dewi_maklon_invoices: Invoice header + lines
- dewi_maklon_payments: Payment records against invoices
- dewi_maklon_hpp: HPP (Cost of Goods) breakdown per order
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from routes.production_rbac import deny_external_dep
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta, date
from database import get_db
from auth import require_auth
from routes.dewi_system_config import get_config_value
from routes._maklon_adapter import find_maklon_record, po_to_legacy_order
from utils.data_quality import SkipTracker
import uuid
from core.authz import only  # T-01 2.3
from core.roles import FINANCE_ROLES  # T-01 2.3
from utils.waktu import today_wib, wib_date_str, wib_year

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/dewi/maklon', tags=['Dewi-Maklon-Billing'], dependencies=[Depends(deny_external_dep)])
# ══════════════════════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════════════════════

INVOICE_STATUSES = ['draft', 'issued', 'partial_paid', 'paid', 'overdue', 'cancelled']
PAYMENT_METHODS = ['transfer', 'cash', 'check', 'giro', 'other']

class InvoiceGenerateIn(BaseModel):
    order_id: str
    tax_pct: Optional[float] = Field(default=None, ge=0)
    # 2026-11-03 (saklar PKP): PPN mengikuti Status Pajak perusahaan (core.tax_status).
    kena_ppn: Optional[bool] = None
    faktur_number: Optional[str] = None
    faktur_date: Optional[str] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    issue_date: Optional[str] = None  # YYYY-MM-DD
    # FASE G (sesi #18) — nomor invoice ketikan; hanya sah bila kebijakan penomoran
    # jenis dokumen ini disetel MANUAL (kalau OTOMATIS, nomor ketikan ditolak).
    invoice_number: Optional[str] = None

class InvoiceUpdateIn(BaseModel):
    notes: Optional[str] = None
    tax_pct: Optional[float] = Field(default=None, ge=0)
    kena_ppn: Optional[bool] = None
    faktur_number: Optional[str] = None
    faktur_date: Optional[str] = None
    discount_amount: Optional[float] = Field(default=None, ge=0)
    due_date: Optional[str] = None

class PaymentIn(BaseModel):
    invoice_id: str
    amount: float = Field(..., gt=0)
    method: str = Field(default='transfer')
    reference_no: Optional[str] = None
    payment_date: Optional[str] = None
    notes: Optional[str] = None
    cash_account_id: Optional[str] = None  # rahaza_cash_accounts.id → akun bank GL (Dr)

class HPPComponent(BaseModel):
    name: str
    category: str = Field(default='material', description="material | labor | overhead | packaging | other")
    qty: float = Field(ge=0, default=1)
    unit: Optional[str] = 'pcs'
    unit_cost: float = Field(ge=0, default=0)
    total: Optional[float] = Field(default=None, ge=0)  # auto-calc

class HPPIn(BaseModel):
    order_id: str
    components: List[HPPComponent] = Field(default_factory=list)
    overhead_pct: Optional[float] = None
    profit_margin_pct: Optional[float] = None
    notes: Optional[str] = None

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _clean(doc: dict) -> dict:
    if not doc:
        return doc
    doc.pop('_id', None)
    return doc

async def _next_invoice_number(db, prefix: str, requested: str = '') -> str:
    """Nomor invoice maklon manual — race-safe & formatnya bisa diatur owner
    (kunci `dewi_maklon_invoices.invoice_number`, token {PREFIX}).

    FASE G (sesi #18): lewat `issue_number` supaya mode OTOMATIS/MANUAL yang disetel
    System Admin benar-benar DITEGAKKAN (mode manual = nomor diketik tetapi wajib
    mengikuti polanya; mode otomatis MENOLAK nomor ketikan, bukan mengabaikannya).
    """
    from core.doc_number_policy import issue_number
    return await issue_number(db, 'dewi_maklon_invoices.invoice_number',
                              ctx={'PREFIX': prefix}, requested=requested)

def _payment_term_days(term: str) -> int:
    mapping = {'net_7': 7, 'net_14': 14, 'net_30': 30, 'net_60': 60}
    return mapping.get(term, 30)

async def _recalc_invoice(db, invoice_id: str) -> dict:
    """Recalculate subtotal, tax, total, paid, balance. Update status."""
    inv = await db.dewi_maklon_invoices.find_one({'id': invoice_id})
    if not inv:
        return {}
    subtotal = sum(float(ln.get('line_total', 0) or 0) for ln in inv.get('lines', []))
    discount = float(inv.get('discount_amount', 0) or 0)
    tax_pct = float(inv.get('tax_pct', 0) or 0)
    tax_base = max(subtotal - discount, 0)
    from core.tax_status import tax_for_stored
    tax_amount = tax_for_stored(inv, tax_base, round_to=2)
    total = round(tax_base + tax_amount, 2)

    payments = await db.dewi_maklon_payments.find({'invoice_id': invoice_id}).to_list(length=100)
    paid = round(sum(float(p.get('amount', 0) or 0) for p in payments), 2)
    balance = round(total - paid, 2)

    # Status resolution
    status = inv.get('status', 'draft')
    if status != 'cancelled':
        if paid <= 0:
            now = today_wib()
            due = inv.get('due_date')
            try:
                due_d = date.fromisoformat(due) if due else None
            except ValueError:
                due_d = None
            if due_d and due_d < now and status != 'draft':
                status = 'overdue'
            elif status == 'draft':
                status = 'draft'
            else:
                status = 'issued'
        elif paid < total:
            status = 'partial_paid'
        else:
            status = 'paid'

    update = {
        'subtotal': round(subtotal, 2),
        'tax_amount': tax_amount,
        'total_amount': total,
        'paid_amount': paid,
        'balance_amount': balance,
        'status': status,
        'updated_at': datetime.now(timezone.utc),
    }
    await db.dewi_maklon_invoices.update_one({'id': invoice_id}, {'$set': update})
    # SATU SUMBER INVOICE: dokumen layar Invoice adalah cermin AR otomatis (`rahaza_ar_invoices`,
    # id sama). Pembayaran/pajak/status dirambatkan supaya Finance & Maklon membaca angka yang sama.
    if inv.get('ar_invoice_id'):
        ar_status = {'paid': 'paid', 'cancelled': 'cancelled', 'draft': 'draft', 'partial_paid': 'partial_paid',
                     'overdue': 'overdue'}.get(status, 'issued')
        await db.rahaza_ar_invoices.update_one({'id': inv['ar_invoice_id']}, {'$set': {
            'tax_pct': tax_pct, 'tax_amount': tax_amount, 'discount_amount': discount,
            'subtotal': round(subtotal, 2), 'total_amount': total,
            'amount_paid': paid, 'amount_due': balance, 'status': ar_status,
            'total': total, 'paid_amount': paid, 'balance': balance,  # cermin lama (H-01)
            'updated_at': datetime.now(timezone.utc)}})
    return update


# 2026-11-06 (Tahap 2, keputusan owner): PO maklon engine TIDAK lagi punya langkah "terbitkan
# faktur" yang membukukan pendapatan sekaligus. Pendapatan lahir per kiriman ke klien dan piutangnya
# dikelola per PO (lihat bagian PIUTANG KLIEN di bawah + core.maklon_ledger). `_billable_preview` dan
# `_generate_from_engine_ar` (satu faktur per PO, dibukukan saat diterbitkan) DIHAPUS.
ENGINE_INVOICE_GONE = ("PO maklon tidak perlu diterbitkan fakturnya lagi: piutang klien terjadwal sejak PO "
                       "dikonfirmasi dan pendapatan dicatat otomatis setiap barang dikirim ke klien. Cetak faktur "
                       "per kiriman atau per PO dari menu Piutang klien maklon.")

# ══════════════════════════════════════════════════════════════════════════════
# INVOICE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get('/invoices')
async def list_invoices(
    status: Optional[str] = None,
    client_id: Optional[str] = None,
    order_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user: dict = Depends(require_auth)
):
    db = get_db()
    query = {}
    if status:
        query['status'] = status
    if client_id:
        query['client_id'] = client_id
    if order_id:
        query['order_id'] = order_id
    if from_date or to_date:
        rng = {}
        if from_date:
            rng['$gte'] = from_date
        if to_date:
            rng['$lte'] = to_date
        query['issue_date'] = rng
    items = await db.dewi_maklon_invoices.find(query).sort('issue_date', -1).to_list(length=500)
    return [_clean(i) for i in items]

@router.get('/invoices/eligible')
async def list_eligible_for_invoice(user: dict = Depends(require_auth)):
    """PO yang bisa ditagih: mirror engine (AR otomatis, qty diterima × harga jasa) + PO legacy
    tanpa mirror. Satu daftar untuk dialog Generate supaya angka pratinjau = angka dokumen."""
    db = get_db()
    invoiced = set(await db.dewi_maklon_invoices.distinct('order_id', {'status': {'$ne': 'cancelled'}}))
    out = []
    async for po in db.dewi_maklon_pos.find(
            {'status': {'$nin': ['draft', 'cancelled', 'invoiced']}}, {'_id': 0}).sort('created_at', -1):
        if po['id'] in invoiced:
            continue
        if po.get('mirror_of') == 'production_pos':
            continue   # 2026-11-06 (Tahap 2): PO engine ditagih otomatis per kiriman (Piutang klien)
        else:
            legacy = po_to_legacy_order(po)
            qty = int(legacy.get('qty_ordered', 0) or 0)
            price = float(legacy.get('price_per_pcs', 0) or 0)
            out.append({'id': po['id'], 'source': 'legacy', 'po_number': po.get('po_number'),
                        'order_code': legacy.get('order_code'), 'client_id': po.get('client_id'),
                        'client_name': po.get('client_name'), 'status': po.get('status'),
                        'ar_invoice_number': None, 'total_ordered': qty, 'total_received': qty,
                        'subtotal': round(qty * price, 2), 'line_count': 1, 'lines': [], 'billable': qty > 0})
    return out


@router.get('/invoices/{invoice_id}')
async def get_invoice(invoice_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    inv = await db.dewi_maklon_invoices.find_one({'id': invoice_id})
    if not inv:
        raise HTTPException(404, 'Invoice tidak ditemukan')
    payments = await db.dewi_maklon_payments.find({'invoice_id': invoice_id}).sort('payment_date', -1).to_list(length=100)
    inv = _clean(inv)
    inv['payments'] = [_clean(p) for p in payments]
    return inv


@router.get('/invoices/{invoice_id}/pdf')
async def get_invoice_pdf(invoice_id: str, user: dict = Depends(require_auth)):
    """Admin-side: download invoice PDF."""
    from fastapi.responses import Response
    from utils.invoice_pdf import build_invoice_pdf
    db = get_db()
    inv = await db.dewi_maklon_invoices.find_one({'id': invoice_id})
    if not inv:
        raise HTTPException(404, 'Invoice tidak ditemukan')
    cl = await db.dewi_maklon_clients.find_one({'id': inv.get('client_id')}) or {}
    co = await db.company_settings.find_one({}) or {}
    # SESI #19 — kop/kolom/tanda tangan/footer invoice mengikuti TEMPLATE PDF pemilik
    # (layar "PDF & Kop Surat"). Tanpa ini invoice tetap memakai kop tanam kode
    # tanpa logo/NPWP sementara dokumen lain sudah mengikuti setelan.
    from utils.pdf_common import get_company_profile, get_doc_settings
    _ds = await get_doc_settings(db, 'invoice-maklon')
    pdf = build_invoice_pdf(invoice=inv, client=cl, company=co,
                            template=(_ds or {}).get('_template'),
                            profile=await get_company_profile(db))
    return Response(
        content=pdf,
        media_type='application/pdf',
        headers={
            'Content-Disposition': f'inline; filename="Invoice_{inv.get("invoice_number")}.pdf"',
        },
    )

@router.post('/invoices/generate')
async def generate_invoice(payload: InvoiceGenerateIn, user: dict = Depends(require_auth)):
    """Auto-generate invoice from a maklon order/PO."""
    db = get_db()
    # P1.B: lookup in dewi_maklon_pos FIRST (SSOT), fallback to dewi_maklon_orders
    rec = await find_maklon_record(db, payload.order_id)
    if not rec:
        raise HTTPException(404, 'Order tidak ditemukan')
    is_po = rec.get('_collection') == 'dewi_maklon_pos'
    if is_po and rec.get('mirror_of') == 'production_pos':
        raise HTTPException(400, ENGINE_INVOICE_GONE)
    # Normalize to legacy order shape for the rest of the flow
    order = po_to_legacy_order(rec) if is_po else rec
    order_id_canonical = order.get('id')

    legacy_status = order.get('status', 'draft')
    if legacy_status in ['draft', 'cancelled']:
        raise HTTPException(400, f'Order dengan status {legacy_status} tidak bisa diinvoice')

    # Check existing non-cancelled invoice for this order
    existing = await db.dewi_maklon_invoices.find_one({
        'order_id': payload.order_id,
        'status': {'$ne': 'cancelled'}
    })
    if existing:
        raise HTTPException(400, f'Order sudah memiliki invoice {existing.get("invoice_number")}')

    # Resolve configs
    prefix = await get_config_value(db, 'maklon_invoice_prefix', 'INV-MKL')
    from core.tax_status import faktur_fields, get_tax_profile, output_tax, wants_output_tax
    tax_profile = await get_tax_profile(db)
    apply_tax = wants_output_tax(tax_profile, payload.tax_pct, payload.kena_ppn)
    tinfo = output_tax(tax_profile, 0, apply=apply_tax)   # nilai dihitung ulang di _recalc_invoice
    tax_pct = tinfo['tax_pct']
    tax_meta = {k: tinfo[k] for k in ('kena_ppn', 'ppn_rate', 'dpp_nilai_lain', 'kode_transaksi')}
    tax_meta.update(faktur_fields(payload.dict()) if tinfo['kena_ppn'] else {'faktur_number': '', 'faktur_date': ''})
    term_default = await get_config_value(db, 'maklon_payment_terms_default', 'net_30') or 'net_30'
    term = payload.payment_terms or term_default

    issue = payload.issue_date or wib_date_str()
    try:
        issue_d = date.fromisoformat(issue)
    except ValueError:
        raise HTTPException(400, 'issue_date tidak valid (YYYY-MM-DD)')
    due_d = issue_d + timedelta(days=_payment_term_days(term))

    line = {
        'description': f"{order.get('product_name')} ({order.get('product_category', '-')})",
        'qty': int(order.get('qty_ordered', 0) or 0),
        'unit': 'pcs',
        'unit_price': float(order.get('price_per_pcs', 0) or 0),
        'line_total': round(float(order.get('price_per_pcs', 0) or 0) * int(order.get('qty_ordered', 0) or 0), 2),
    }

    invoice_number = await _next_invoice_number(db, prefix,
                                                requested=(payload.invoice_number or ''))
    now = datetime.now(timezone.utc)
    doc = {
        'id': str(uuid.uuid4()),
        'invoice_number': invoice_number,
        'order_id': order.get('id'),
        'order_code': order.get('order_code'),
        'client_id': order.get('client_id'),
        'client_name': order.get('client_name'),
        'issue_date': issue_d.isoformat(),
        'due_date': due_d.isoformat(),
        'payment_terms': term,
        'tax_pct': tax_pct,
        **tax_meta,
        'discount_amount': 0.0,
        'lines': [line],
        'subtotal': line['line_total'],
        'tax_amount': 0.0,
        'total_amount': 0.0,
        'paid_amount': 0.0,
        'balance_amount': 0.0,
        'status': 'issued',
        'notes': payload.notes,
        'created_at': now,
        'updated_at': now,
        'created_by': user.get('name', 'System'),
    }
    await db.dewi_maklon_invoices.insert_one(doc)

    # Mark order as invoiced (post-P1.B cleanup: only dewi_maklon_pos exists as SSOT)
    if is_po:
        await db.dewi_maklon_pos.update_one(
            {'id': order_id_canonical},
            {'$set': {'status': 'invoiced', 'ar_invoice_id': doc['id'],
                      'ar_invoice_number': invoice_number, 'updated_at': now}}
        )

    await _recalc_invoice(db, doc['id'])
    # C-06: invoice maklon (jalur legacy) juga masuk GL — cermin dokumen invoice ini sendiri.
    from routes.dewi_maklon_finance import post_maklon_ar_invoice
    await post_maklon_ar_invoice(db, {
        'id': order_id_canonical if is_po else None, 'ar_invoice_id': doc['id'],
        'po_number': order.get('order_code'), 'client_id': order.get('client_id'),
        'client_name': order.get('client_name'), 'po_date': issue_d.isoformat()}, user)

    # Phase 4 P1: notify klien
    try:
        from routes.dewi_notifications import queue_for_client
        body = (
            f"Invoice baru {invoice_number} untuk order {order.get('order_code')} "
            f"telah diterbitkan. Total Rp {int(doc.get('total_amount') or 0):,}, "
            f"jatuh tempo {doc.get('due_date')}."
        ).replace(',', '.')
        await queue_for_client(
            db,
            client_id=order.get('client_id'),
            subject=f"Invoice baru — {invoice_number}",
            body=body,
            event_type='invoice_issued',
            source_ref=doc['id'],
            meta={'invoice_number': invoice_number, 'total': doc.get('total_amount')},
        )
    except Exception:
        logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

    refreshed = await db.dewi_maklon_invoices.find_one({'id': doc['id']})
    return _clean(refreshed)

@router.put('/invoices/{invoice_id}')
async def update_invoice(invoice_id: str, payload: InvoiceUpdateIn, user: dict = Depends(require_auth)):
    db = get_db()
    inv = await db.dewi_maklon_invoices.find_one({'id': invoice_id})
    if not inv:
        raise HTTPException(404, 'Invoice tidak ditemukan')
    if inv.get('status') == 'paid':
        raise HTTPException(400, 'Invoice sudah lunas, tidak dapat diubah')

    update = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if {'tax_pct', 'kena_ppn', 'faktur_number', 'faktur_date'} & set(update):
        # 2026-11-03 (saklar PKP): ubah PPN hanya lewat SSOT — non-PKP menolak PPN > 0.
        from core.tax_status import faktur_fields, get_tax_profile, output_tax, wants_output_tax
        tax_profile = await get_tax_profile(db)
        if 'tax_pct' in update or 'kena_ppn' in update:
            apply_tax = wants_output_tax(tax_profile, update.pop('tax_pct', None), update.pop('kena_ppn', None))
            tinfo = output_tax(tax_profile, 0, apply=apply_tax)
            update.update({k: tinfo[k] for k in ('tax_pct', 'kena_ppn', 'ppn_rate', 'kode_transaksi')})
        kena = update.get('kena_ppn', inv.get('kena_ppn', bool(inv.get('tax_pct'))))
        f = faktur_fields({'faktur_number': update.pop('faktur_number', inv.get('faktur_number')),
                           'faktur_date': update.pop('faktur_date', inv.get('faktur_date'))})
        update.update(f if kena else {'faktur_number': '', 'faktur_date': ''})
    if update:
        update['updated_at'] = datetime.now(timezone.utc)
        await db.dewi_maklon_invoices.update_one({'id': invoice_id}, {'$set': update})
    await _recalc_invoice(db, invoice_id)
    return {'message': 'Invoice diperbarui'}

@router.post('/invoices/{invoice_id}/cancel')
async def cancel_invoice(invoice_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    inv = await db.dewi_maklon_invoices.find_one({'id': invoice_id})
    if not inv:
        raise HTTPException(404, 'Invoice tidak ditemukan')
    if inv.get('paid_amount', 0) > 0:
        raise HTTPException(400, 'Invoice yang sudah dibayar tidak bisa dibatalkan')
    now_ts = datetime.now(timezone.utc)
    from routes.dewi_maklon_finance import void_maklon_ar_posting
    if inv.get('ar_invoice_id'):
        ar = await db.rahaza_ar_invoices.find_one({'id': inv['ar_invoice_id']}, {'_id': 0}) or {}
        # C-06: invoice belum dibayar → jurnal penerbitan di-VOID otomatis (periode harus terbuka).
        v = await void_maklon_ar_posting(db, inv['ar_invoice_id'], inv.get('order_id'), user,
                                         reason=f'Invoice {inv.get("invoice_number")} dibatalkan')
        if not v.get('ok'):
            raise HTTPException(400, f"Jurnal GL tidak bisa di-void: {v.get('error')}")
        # AR kembali menjadi draft supaya bisa diterbitkan ulang dengan qty terbaru.
        total = float(ar.get('total_amount') or 0)
        await db.rahaza_ar_invoices.update_one({'id': inv['ar_invoice_id']}, {'$set': {
            'status': 'draft', 'amount_paid': 0.0, 'amount_due': total,
            'issued_at': None, 'issued_by': None, 'updated_at': now_ts}})
    order_id = inv.get('order_id')
    if inv.get('source') == 'engine_ar':
        # SATU SUMBER: dokumen layar hanyalah cermin AR (id & nomor SAMA). Menyimpannya sebagai
        # 'cancelled' membuat unique index invoice_number menolak penerbitan ulang (iter 105).
        # AR draft-nya tetap hidup ⇒ cukup hapus cerminnya + pembayaran (pasti 0).
        await db.dewi_maklon_payments.delete_many({'invoice_id': invoice_id})
        await db.dewi_maklon_invoices.delete_one({'id': invoice_id})
        if order_id:
            from routes.production_maklon_bridge import try_sync_maklon_finance
            await db.dewi_maklon_pos.update_one(
                {'id': order_id, 'status': 'invoiced'},
                {'$set': {'status': 'completed', 'updated_at': now_ts}})
            await try_sync_maklon_finance(db, order_id, user)
        return {'message': 'Invoice dibatalkan', 'ar_status': 'draft'}
    if not inv.get('ar_invoice_id'):
        v = await void_maklon_ar_posting(db, invoice_id, order_id, user,
                                         reason=f'Invoice {inv.get("invoice_number")} dibatalkan')
        if not v.get('ok'):
            raise HTTPException(400, f"Jurnal GL tidak bisa di-void: {v.get('error')}")
    await db.dewi_maklon_invoices.update_one(
        {'id': invoice_id},
        {'$set': {'status': 'cancelled', 'updated_at': now_ts}}
    )
    # Revert order status (best-effort) to completed on dewi_maklon_pos (SSOT)
    if order_id:
        await db.dewi_maklon_pos.update_one(
            {'id': order_id, 'status': 'invoiced'},
            {'$set': {'status': 'completed', 'updated_at': now_ts}}
        )
    return {'message': 'Invoice dibatalkan'}

# ══════════════════════════════════════════════════════════════════════════════
# PAYMENT ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.post('/payments')
async def record_payment(payload: PaymentIn, user: dict = Depends(require_auth)):
    db = get_db()
    inv = await db.dewi_maklon_invoices.find_one({'id': payload.invoice_id})
    if not inv:
        # 2026-11-06 (Tahap 2): id piutang terjadwal PO maklon → pembayaran dicatat ke piutang itu
        ar = await db.rahaza_ar_invoices.find_one({'id': payload.invoice_id, 'schedule_mode': 'v2'}, {'_id': 0})
        if ar:
            _require_payment_role(user)
            return await _schedule_payment(db, ar, payload.amount, payload.cash_account_id, payload.payment_date,
                                           payload.notes or '', payload.reference_no or '', user)
        raise HTTPException(404, 'Invoice tidak ditemukan')
    if inv.get('status') == 'cancelled':
        raise HTTPException(400, 'Invoice dibatalkan')
    if payload.method not in PAYMENT_METHODS:
        raise HTTPException(400, f'Method tidak valid. Valid: {PAYMENT_METHODS}')

    # Prevent overpayment
    outstanding = float(inv.get('balance_amount', 0) or 0)
    if outstanding <= 0:
        outstanding = float(inv.get('total_amount', 0) or 0) - float(inv.get('paid_amount', 0) or 0)
    if payload.amount > outstanding + 0.01:
        raise HTTPException(400, f'Pembayaran melebihi saldo tagihan (Rp {outstanding:,.0f})')

    now = datetime.now(timezone.utc)
    pay_date = payload.payment_date or wib_date_str(now)
    doc = {
        'id': str(uuid.uuid4()),
        'invoice_id': payload.invoice_id,
        'invoice_number': inv.get('invoice_number'),
        'client_id': inv.get('client_id'),
        'client_name': inv.get('client_name'),
        'amount': float(payload.amount),
        'method': payload.method,
        'reference_no': payload.reference_no,
        'payment_date': pay_date,
        'notes': payload.notes,
        'cash_account_id': payload.cash_account_id,
        'created_at': now,
        'created_by': user.get('name', 'System'),
    }
    if payload.cash_account_id and not await db.rahaza_cash_accounts.find_one({'id': payload.cash_account_id}, {'_id': 1}):
        raise HTTPException(400, 'Rekening kas/bank tidak ditemukan')
    await db.dewi_maklon_payments.insert_one(doc)
    await _recalc_invoice(db, payload.invoice_id)
    # C-06: penerimaan kas maklon → Dr Bank / Cr AR (akun AR yang sama dgn jurnal penerbitan).
    from routes.dewi_maklon_finance import post_maklon_payment
    gl = await post_maklon_payment(db, inv, doc, user)
    return {'message': 'Pembayaran dicatat', 'id': doc['id'],
            'gl_je_number': gl.get('je_number'), 'gl_error': gl.get('error')}

@router.get('/payments')
async def list_payments(
    invoice_id: Optional[str] = None,
    client_id: Optional[str] = None,
    user: dict = Depends(require_auth)
):
    db = get_db()
    query = {}
    if invoice_id:
        query['invoice_id'] = invoice_id
    if client_id:
        query['client_id'] = client_id
    items = await db.dewi_maklon_payments.find(query).sort('payment_date', -1).to_list(length=500)
    return [_clean(p) for p in items]

@router.delete('/payments/{payment_id}', dependencies=only(*FINANCE_ROLES))  # T-01 2.3
async def delete_payment(payment_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    pay = await db.dewi_maklon_payments.find_one({'id': payment_id})
    if not pay:
        raise HTTPException(404, 'Payment tidak ditemukan')
    from routes.dewi_maklon_finance import void_maklon_payment
    v = await void_maklon_payment(db, pay, user, reason='Pembayaran maklon dihapus')
    if not v.get('ok'):
        raise HTTPException(400, f"Jurnal GL tidak bisa di-void: {v.get('error')}")
    await db.dewi_maklon_payments.delete_one({'id': payment_id})
    await _recalc_invoice(db, pay['invoice_id'])
    return {'message': 'Payment dihapus'}

# ══════════════════════════════════════════════════════════════════════════════
# HPP ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get('/hpp/{order_id}')
async def get_hpp(order_id: str, user: dict = Depends(require_auth)):
    """HPP Jahit maklon — 2026-11-02 (K16): dari ANGKA NYATA, bukan ketikan manual.

    Dulu `404 "HPP belum diinput"` untuk setiap PO baru karena komponen harus diketik
    ulang (tidak membaca tarif CMT PO/SPK maupun tagihan CMT). Sekarang komponen diambil
    dari `production_maklon_bridge.maklon_actual_costs`: tagihan CMT nyata + aksesoris DA
    (Material Issue) + permak. Margin = tagihan klien − biaya itu. Dokumen ketikan lama
    (bila ada) hanya dikembalikan sebagai `manual_snapshot` untuk pembanding.
    """
    db = get_db()
    manual = await db.dewi_maklon_hpp.find_one({'order_id': order_id})
    po = await db.production_pos.find_one({'id': order_id}, {'_id': 0, 'id': 1, 'business_type': 1})
    if not po:
        if not manual:
            raise HTTPException(404, 'Order maklon tidak ditemukan')
        return {**_clean(manual), 'source': 'manual'}
    from routes.production_maklon_bridge import maklon_actual_costs
    a = await maklon_actual_costs(db, order_id)
    items = await db.po_items.find({'po_id': order_id}, {'_id': 0}).to_list(None)
    qty_ordered = a['qty_ordered'] or 1
    rate_plan = (a['cmt_cost_plan'] / qty_ordered) if qty_ordered else 0
    cmt_qty = a['qty_billed_cmt']
    components = [
        {'name': 'Upah jahit CMT (tagihan nyata)' if cmt_qty else 'Upah jahit CMT (tarif PO/SPK, belum ditagih)',
         'category': 'labor', 'qty': cmt_qty or qty_ordered, 'unit': 'pcs',
         'unit_cost': round(a['cmt_cost'] / cmt_qty, 2) if cmt_qty else round(rate_plan, 2),
         'total': a['cmt_cost'] if cmt_qty else round(a['cmt_cost_plan'], 2), 'source': 'dewi_cmt_payments'},
        # 2026-11-06 (Tahap 2): aksesoris dibagi per pcs yang DIKIRIM ke CMT; HPP hanya memuat bagian
        # pcs lolos QC (dulu Σ aksesoris semua pcs dibagi pcs lolos ⇒ HPP per pcs membengkak).
        {'name': 'Aksesoris milik DA (bagian pcs lolos QC)', 'category': 'packaging',
         'qty': a['qty_basis'] or 1, 'unit': 'pcs',
         'unit_cost': a.get('accessory_cost_per_pcs', a['accessory_cost']),
         'total': a.get('accessory_cost_absorbed', a['accessory_cost']), 'source': 'rahaza_material_issues'},
        {'name': 'Permak / perbaikan', 'category': 'other', 'qty': 1, 'unit': 'lot',
         'unit_cost': a['permak_cost'], 'total': a['permak_cost'], 'source': 'dewi_cmt_permak'},
    ]
    direct = round(sum(c['total'] for c in components), 2)
    profit_pct = float((manual or {}).get('profit_margin_pct')
                       or await get_config_value(db, 'hpp_profit_margin_pct', 20.0) or 0)
    basis = a['qty_basis'] or qty_ordered
    hpp_pcs = round(direct / basis, 2) if basis else 0.0
    price = (sum(float(i.get('selling_price_snapshot', 0) or 0) * int(i.get('qty', 0) or 0) for i in items)
             / qty_ordered) if qty_ordered else 0.0
    return {
        'order_id': order_id, 'source': 'actual', 'po_number': a['po_number'],
        'qty_ordered': a['qty_ordered'], 'qty_basis': basis,
        'components': components, 'direct_cost': direct,
        'accessory_cost_unabsorbed': a.get('accessory_cost_unabsorbed', 0.0),
        # keputusan owner 6 Nov 2026: TIDAK ada overhead di HPP (tenaga & overhead pabrik = beban bulanan)
        'overhead_pct': 0.0, 'overhead_amount': 0.0,
        'total_hpp': direct, 'hpp_per_pcs': hpp_pcs,
        'profit_margin_pct': profit_pct,
        # margin = (harga − HPP) ÷ harga ⇒ harga saran = HPP ÷ (1 − margin)
        'suggested_price_per_pcs': (round(hpp_pcs / (1 - profit_pct / 100), 2) if profit_pct < 100 else 0.0),
        'current_price_per_pcs': round(price, 2),
        'actual_margin_pct': round((price - hpp_pcs) / price * 100, 2) if price > 0 else 0,
        'revenue': a['revenue'], 'margin': a['margin'], 'margin_pct': a['margin_pct'],
        'actual': a, 'gaps': a['gaps'],
        'notes': (manual or {}).get('notes', ''),
        'manual_snapshot': _clean(manual) if manual else None,
    }

@router.post('/hpp')
async def upsert_hpp(payload: HPPIn, user: dict = Depends(require_auth)):
    """Create or update HPP for an order."""
    db = get_db()
    # P1.B: SSOT is dewi_maklon_pos, fallback to legacy
    rec = await find_maklon_record(db, payload.order_id)
    if not rec:
        raise HTTPException(404, 'Order tidak ditemukan')

    # Normalize record shape (PO or legacy) to legacy-order view
    is_po = rec.get('_collection') == 'dewi_maklon_pos'
    order = po_to_legacy_order(rec) if is_po else rec

    # 2026-11-06 (Tahap 2, keputusan owner): TIDAK ada overhead di HPP. Dulu bawaan 15% ditambahkan
    # ke setiap HPP maklon ketikan; nilai overhead kiriman layar diabaikan.
    overhead_pct = 0.0
    profit_default = float(await get_config_value(db, 'hpp_profit_margin_pct', 20.0) or 0)
    profit_pct = payload.profit_margin_pct if payload.profit_margin_pct is not None else profit_default

    components = []
    for c in payload.components:
        cd = c.dict()
        cd['total'] = round(float(cd.get('qty', 0) or 0) * float(cd.get('unit_cost', 0) or 0), 2)
        components.append(cd)

    direct_cost = sum(c['total'] for c in components)
    overhead_amount = round(direct_cost * overhead_pct / 100, 2)
    qty_ordered = int(order.get('qty_ordered', 0) or 0) or 1
    total_hpp = round(direct_cost + overhead_amount, 2)
    hpp_per_pcs = round(total_hpp / qty_ordered, 2)
    # margin = (harga − HPP) ÷ harga (keputusan owner, berlaku di semua layar)
    suggested_price = round(hpp_per_pcs / (1 - profit_pct / 100), 2) if profit_pct < 100 else 0.0
    current_price = float(order.get('price_per_pcs', 0) or 0)
    actual_margin_pct = round(((current_price - hpp_per_pcs) / current_price) * 100, 2) if current_price > 0 else 0

    now = datetime.now(timezone.utc)
    doc = {
        'order_id': payload.order_id,
        'order_code': order.get('order_code'),
        'client_id': order.get('client_id'),
        'client_name': order.get('client_name'),
        'qty_ordered': qty_ordered,
        'components': components,
        'direct_cost': round(direct_cost, 2),
        'overhead_pct': overhead_pct,
        'overhead_amount': overhead_amount,
        'profit_margin_pct': profit_pct,
        'total_hpp': total_hpp,
        'hpp_per_pcs': hpp_per_pcs,
        'suggested_price_per_pcs': suggested_price,
        'current_price_per_pcs': current_price,
        'actual_margin_pct': actual_margin_pct,
        'notes': payload.notes,
        'updated_at': now,
        'updated_by': user.get('name', 'System'),
    }
    existing = await db.dewi_maklon_hpp.find_one({'order_id': payload.order_id})
    if existing:
        await db.dewi_maklon_hpp.update_one({'order_id': payload.order_id}, {'$set': doc})
        hpp_id = existing.get('id')
    else:
        doc['id'] = str(uuid.uuid4())
        doc['created_at'] = now
        doc['created_by'] = user.get('name', 'System')
        await db.dewi_maklon_hpp.insert_one(doc)
        hpp_id = doc['id']
    return {'message': 'HPP tersimpan', 'id': hpp_id, 'hpp_per_pcs': hpp_per_pcs, 'actual_margin_pct': actual_margin_pct}

# ══════════════════════════════════════════════════════════════════════════════
# REPORTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get('/reports/billing-summary')
async def billing_summary(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    client_id: Optional[str] = None,
    user: dict = Depends(require_auth)
):
    """Aggregate billing numbers (revenue, outstanding, overdue)."""
    db = get_db()
    query = {'status': {'$ne': 'cancelled'}}
    if client_id:
        query['client_id'] = client_id
    if from_date or to_date:
        rng = {}
        if from_date:
            rng['$gte'] = from_date
        if to_date:
            rng['$lte'] = to_date
        query['issue_date'] = rng

    invoices = await db.dewi_maklon_invoices.find(query).to_list(length=2000)
    total_invoices = len(invoices)
    total_billed = round(sum(float(i.get('total_amount', 0) or 0) for i in invoices), 2)
    total_paid = round(sum(float(i.get('paid_amount', 0) or 0) for i in invoices), 2)
    total_outstanding = round(total_billed - total_paid, 2)

    # Overdue
    #
    # 2026-08-07 — dua cacat di blok ini:
    #   1. invoice yang `due_date`-nya rusak di-`continue` DIAM-DIAM ⇒ hilang dari
    #      hitungan jatuh tempo; total tampak wajar dan tak ada yang menagih.
    #   2. `except ValueError` TIDAK menangkap `TypeError`. Bila `due_date` bernilai
    #      None (key ada, isinya null — bentuk yang nyata di data lama),
    #      `date.fromisoformat(None)` melempar TypeError ⇒ endpoint 500, BUKAN
    #      "cuma satu baris dilewati". Ekspektasinya diperlebar.
    today = today_wib()
    dq = SkipTracker("ringkasan tagihan maklon (jatuh tempo)")
    overdue_amount = 0.0
    overdue_count = 0
    for i in invoices:
        try:
            d = date.fromisoformat(i.get('due_date') or '2099-12-31')
        except (ValueError, TypeError) as e:
            dq.skip(doc_id=i.get('id'), label=i.get('invoice_number'),
                    field='due_date', value=i.get('due_date'), error=e)
            continue
        if d < today and i.get('status') in ('issued', 'partial_paid', 'overdue'):
            overdue_count += 1
            overdue_amount += float(i.get('balance_amount', 0) or 0)
    overdue_amount = round(overdue_amount, 2)
    dq.log(logger)

    # By status breakdown
    by_status = {}
    for s in INVOICE_STATUSES:
        by_status[s] = {
            'count': len([i for i in invoices if i.get('status') == s]),
            'amount': round(sum(float(i.get('total_amount', 0) or 0) for i in invoices if i.get('status') == s), 2),
        }

    return {
        'total_invoices': total_invoices,
        'total_billed': total_billed,
        'total_paid': total_paid,
        'total_outstanding': total_outstanding,
        'overdue_count': overdue_count,
        'overdue_amount': overdue_amount,
        'by_status': by_status,
    }

@router.get('/reports/monthly-billing')
async def monthly_billing(
    year: Optional[int] = None,
    client_id: Optional[str] = None,
    user: dict = Depends(require_auth)
):
    """Monthly billing aggregation per client."""
    db = get_db()
    target_year = year or wib_year()
    query = {
        'status': {'$ne': 'cancelled'},
        'issue_date': {'$gte': f'{target_year}-01-01', '$lte': f'{target_year}-12-31'},
    }
    if client_id:
        query['client_id'] = client_id

    invoices = await db.dewi_maklon_invoices.find(query).to_list(length=5000)

    # Bucket by month & client
    buckets: Dict[str, Dict[str, Any]] = {}
    for i in invoices:
        issue = i.get('issue_date', '')
        month_key = issue[:7] if len(issue) >= 7 else 'unknown'
        cid = i.get('client_id', 'unknown')
        key = f'{month_key}|{cid}'
        if key not in buckets:
            buckets[key] = {
                'month': month_key,
                'client_id': cid,
                'client_name': i.get('client_name'),
                'invoices_count': 0,
                'total_billed': 0.0,
                'total_paid': 0.0,
                'total_outstanding': 0.0,
            }
        b = buckets[key]
        b['invoices_count'] += 1
        b['total_billed'] += float(i.get('total_amount', 0) or 0)
        b['total_paid'] += float(i.get('paid_amount', 0) or 0)
        b['total_outstanding'] += float(i.get('balance_amount', 0) or 0)

    # Round
    rows = []
    for b in buckets.values():
        rows.append({
            **b,
            'total_billed': round(b['total_billed'], 2),
            'total_paid': round(b['total_paid'], 2),
            'total_outstanding': round(b['total_outstanding'], 2),
        })
    rows.sort(key=lambda x: (x['month'], x.get('client_name') or ''))
    return {'year': target_year, 'rows': rows}

@router.get('/reports/aging')
async def aging_report(user: dict = Depends(require_auth)):
    """Aging tagihan maklon — membaca sumber yang SAMA dgn /api/rahaza/ar-aging (H-01), filter source=maklon."""
    db = get_db()
    from routes.rahaza_ar_canonical import compute_ar_aging
    res = await compute_ar_aging(db, source='maklon')
    b = res['buckets']
    buckets = {'current': b['current'], '1_30': b['1_30'], '31_60': b['31_60'], '61_90': b['61_90'],
               'over_90': b['90_plus'], 'tanpa_jatuh_tempo': b['tanpa_jatuh_tempo']}
    rows = [{'invoice_number': r.get('invoice_number'), 'client_name': r.get('client_name'),
             'issue_date': r.get('invoice_date') or r.get('issue_date'), 'due_date': r.get('due_date'),
             'total_amount': r['total_amount'], 'balance_amount': r['amount_due'], 'status': r['status'],
             'days_overdue': r['days_overdue'], 'bucket': 'over_90' if r['bucket'] == '90_plus' else r['bucket'],
             'due_date_valid': r['due_date_valid']} for r in res['rows']]
    return {'buckets': buckets, 'rows': rows, 'total': res['total'], 'data_quality': res['data_quality']}


# ══════════════════════════════════════════════════════════════════════════════
# PIUTANG KLIEN MAKLON PER PO (2026-11-06, Tahap 2 — keputusan owner)
# ══════════════════════════════════════════════════════════════════════════════
# Layar "Invoice Klien" menjadi tampilan piutang PER PO: nilai terjadwal (qty pesan × harga jasa),
# tertagih (pendapatan per kiriman), dibayar, sisa, uang muka; faktur hanya DOKUMEN CETAK (per
# kiriman atau per PO); pembayaran dicatat terhadap piutang PO. Sumber data tetap satu:
# `rahaza_ar_invoices` (source_module='maklon_po') — lihat core.maklon_ledger.
_PAY_ROLES = tuple(dict.fromkeys(FINANCE_ROLES + ('admin_maklon', 'manager')))


def _require_payment_role(user: dict) -> None:
    if (user.get('role') or '').lower() not in _PAY_ROLES:
        raise HTTPException(403, 'Hanya Keuangan / admin maklon yang boleh mencatat pembayaran klien.')


class ReceivablePaymentIn(BaseModel):
    amount: float = Field(..., gt=0)
    cash_account_id: str
    payment_date: Optional[str] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _receivable_row(ar: dict) -> dict:
    """Satu baris daftar piutang per PO (dokumen terjadwal v2 maupun faktur lama)."""
    v2 = ar.get('schedule_mode') == 'v2'
    total = _num(ar.get('total_amount') if ar.get('total_amount') is not None else ar.get('total'))
    paid = _num(ar.get('amount_paid') if ar.get('amount_paid') is not None else ar.get('paid_amount'))
    due = _num(ar.get('amount_due') if ar.get('amount_due') is not None else ar.get('balance'))
    legacy_billed = total if (ar.get('status') or 'draft') not in ('draft', 'cancelled') else 0.0
    return {
        'id': ar['id'], 'invoice_number': ar.get('invoice_number'), 'mode': 'terjadwal' if v2 else 'lama',
        'po_id': ar.get('linked_maklon_po_id'), 'po_number': ar.get('linked_maklon_po_number'),
        'client_id': ar.get('customer_id'), 'client_name': ar.get('customer_name'),
        'status': ar.get('status') or 'draft', 'po_status': ar.get('po_status'),
        'scheduled_total': _num(ar.get('scheduled_total')) if v2 else total,
        'billed_total': _num(ar.get('billed_total')) if v2 else legacy_billed,
        'paid_total': paid, 'amount_due': due,
        'advance_balance': _num(ar.get('advance_balance')) if v2 else 0.0,
        'scheduled_remaining': _num(ar.get('scheduled_remaining')) if v2 else 0.0,
        'outstanding_total': _num(ar.get('outstanding_total')) if v2 else round(total - paid, 2),
        'due_date': ar.get('due_date'), 'issue_date': ar.get('issue_date') or ar.get('invoice_date'),
        'kena_ppn': bool(ar.get('kena_ppn')), 'post_error': ar.get('post_error'),
        'held_count': len(ar.get('revenue_held') or []),
    }


RECEIVABLE_GROUPS = {
    'terjadwal': lambda r: r['status'] == 'scheduled',
    'belum_lunas': lambda r: r['amount_due'] > 0.005,
    'lunas': lambda r: r['status'] == 'paid',
    'dibatalkan': lambda r: r['status'] == 'cancelled',
}


@router.get('/receivables')
async def list_receivables(status: Optional[str] = None, client_id: Optional[str] = None,
                           search: Optional[str] = None, user: dict = Depends(require_auth)):
    db = get_db()
    q: dict = {'source_module': 'maklon_po'}
    if client_id:
        q['customer_id'] = client_id
    docs = await db.rahaza_ar_invoices.find(q, {'_id': 0}).sort('created_at', -1).to_list(2000)
    rows = [r for r in (_receivable_row(d) for d in docs) if r['status'] != 'draft' or r['mode'] == 'terjadwal']
    if search:
        s = search.strip().lower()
        rows = [r for r in rows if s in (r.get('po_number') or '').lower()
                or s in (r.get('client_name') or '').lower() or s in (r.get('invoice_number') or '').lower()]
    counts = {k: sum(1 for r in rows if f(r)) for k, f in RECEIVABLE_GROUPS.items()}
    if status in RECEIVABLE_GROUPS:
        rows = [r for r in rows if RECEIVABLE_GROUPS[status](r)]
    live = [r for r in rows if r['status'] != 'cancelled']
    summary = {
        'scheduled_remaining': round(sum(r['scheduled_remaining'] for r in live), 2),
        'amount_due': round(sum(r['amount_due'] for r in live), 2),
        'advance_balance': round(sum(r['advance_balance'] for r in live), 2),
        'overdue': round(sum(r['amount_due'] for r in live if r['status'] == 'overdue'), 2),
        'count': len(rows),
    }
    return {'items': rows, 'counts': counts, 'summary': summary}


def dispatch_groups(ar: dict) -> list:
    """Kiriman yang sudah ditagih (neto per surat jalan + urutan kirim), dengan alokasi bayar FIFO."""
    groups: dict = {}
    for p in ar.get('revenue_postings') or []:
        key = (p.get('shipment_id'), p.get('dispatch_seq'))
        g = groups.setdefault(key, {'shipment_id': key[0], 'dispatch_seq': key[1],
                                    'shipment_number': p.get('shipment_number', ''), 'date': None,
                                    'subtotal': 0.0, 'tax': 0.0, 'total': 0.0, 'journals': [], 'lines': {}})
        sign = -1 if p.get('reverse') else 1
        g['subtotal'] = round(g['subtotal'] + sign * _num(p.get('subtotal')), 2)
        g['tax'] = round(g['tax'] + sign * _num(p.get('tax')), 2)
        g['total'] = round(g['subtotal'] + g['tax'], 2)
        if not p.get('reverse') and (not g['date'] or str(p.get('date')) < str(g['date'])):
            g['date'] = p.get('date')
        g['journals'].append({'je_number': p.get('je_number'), 'reverse': bool(p.get('reverse')),
                              'total': p.get('total'), 'date': p.get('date')})
        for ln in p.get('lines') or []:
            x = g['lines'].setdefault(ln.get('po_item_id'), {
                'po_item_id': ln.get('po_item_id'), 'sku': ln.get('sku'), 'size': ln.get('size'),
                'qty': 0, 'amount': 0.0, 'unit_price': ln.get('unit_price')})
            x['qty'] += int(ln.get('qty') or 0)
            x['amount'] = round(x['amount'] + _num(ln.get('amount')), 2)
    out = sorted(groups.values(),
                 key=lambda g: (str(g['date'] or ''), str(g['shipment_number']), g['dispatch_seq'] or 0))
    left = _num(ar.get('ar_credit'))
    for i, g in enumerate(out, start=1):
        g['seq_no'] = i
        g['lines'] = [ln for ln in g['lines'].values() if ln['qty']]
        g['paid'] = round(min(max(left, 0.0), max(g['total'], 0.0)), 2)
        left -= g['paid']
        g['balance'] = round(g['total'] - g['paid'], 2)
    return [g for g in out if g['total'] or g['lines']]


@router.get('/receivables/{ar_id}')
async def get_receivable(ar_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    ar = await db.rahaza_ar_invoices.find_one({'id': ar_id, 'source_module': 'maklon_po'}, {'_id': 0})
    if not ar:
        raise HTTPException(404, 'Piutang tidak ditemukan')
    pays = await db.rahaza_ar_payments.find({'invoice_id': ar_id}, {'_id': 0}).sort('created_at', 1).to_list(500)
    legacy_pays = await db.dewi_maklon_payments.find({'invoice_id': ar_id}, {'_id': 0}).to_list(500)
    acc_ids = list({p.get('account_id') for p in pays if p.get('account_id')})
    accs = {}
    async for a in db.rahaza_cash_accounts.find({'id': {'$in': acc_ids}}, {'_id': 0, 'id': 1, 'name': 1}):
        accs[a['id']] = a.get('name')
    po = await db.production_pos.find_one({'id': ar.get('linked_maklon_po_id')},
                                          {'_id': 0, 'over_qty_events': 1, 'status': 1}) or {}
    payments = [{'id': p['id'], 'date': p.get('date'), 'amount': p.get('amount'),
                 'ar_portion': p.get('ar_portion', p.get('amount')), 'advance_portion': p.get('advance_portion', 0),
                 'account_name': accs.get(p.get('account_id')) or '', 'reference_no': p.get('reference_no', ''),
                 'notes': p.get('notes', ''), 'status': p.get('status', 'posted'),
                 'je_number': p.get('gl_je_number'), 'source': 'piutang'} for p in pays]
    payments += [{'id': p['id'], 'date': p.get('payment_date'), 'amount': p.get('amount'),
                  'ar_portion': p.get('amount'), 'advance_portion': 0, 'account_name': '',
                  'reference_no': p.get('reference_no', ''), 'notes': p.get('notes', ''), 'status': 'posted',
                  'je_number': p.get('gl_je_number'), 'source': 'faktur_lama'} for p in legacy_pays]
    from auth import serialize_doc
    return serialize_doc({
        **_receivable_row(ar),
        'payment_terms': ar.get('payment_terms'), 'lines': ar.get('lines') or [],
        'dispatches': dispatch_groups(ar), 'payments': payments,
        'advance_postings': ar.get('advance_postings') or [], 'held': ar.get('revenue_held') or [],
        'over_qty_events': [e for e in po.get('over_qty_events') or []
                            if e.get('step') in ('kirim_klien', 'tagihan')],
        'scheduled_subtotal': ar.get('scheduled_subtotal'), 'scheduled_tax': ar.get('scheduled_tax'),
        'billed_subtotal': ar.get('billed_subtotal'), 'billed_tax': ar.get('billed_tax'),
        'ar_account_code': ar.get('gl_ar_account_code'), 'revenue_account_code': ar.get('revenue_account_code'),
    })


@router.post('/receivables/{ar_id}/sync')
async def sync_receivable(ar_id: str, user: dict = Depends(require_auth)):
    """Hitung ulang piutang PO dari kiriman & pembayaran (idempoten)."""
    _require_payment_role(user)
    db = get_db()
    ar = await db.rahaza_ar_invoices.find_one({'id': ar_id, 'schedule_mode': 'v2'}, {'_id': 0})
    if not ar:
        raise HTTPException(404, 'Piutang terjadwal tidak ditemukan')
    from core import maklon_ledger
    return await maklon_ledger.sync_ar_schedule(db, ar['linked_maklon_po_id'], user)


async def _schedule_payment(db, ar: dict, amount, cash_account_id, payment_date, notes, reference_no, user):
    from core import maklon_ledger
    try:
        doc = await maklon_ledger.record_client_payment(
            db, ar['id'], amount=amount, cash_account_id=cash_account_id, payment_date=payment_date,
            notes=notes, reference_no=reference_no, user=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    from auth import log_activity
    await log_activity(user.get('id', ''), user.get('name', ''), 'Pembayaran Klien', 'Maklon Finance',
                       f"Pembayaran PO {ar.get('linked_maklon_po_number')} Rp {float(amount):,.0f} "
                       f"(piutang Rp {doc['ar_portion']:,.0f}, uang muka Rp {doc['advance_portion']:,.0f})")
    return {'message': 'Pembayaran dicatat', 'id': doc['id'], 'gl_je_number': doc.get('gl_je_number'),
            'ar_portion': doc['ar_portion'], 'advance_portion': doc['advance_portion']}


@router.post('/receivables/{ar_id}/payments')
async def pay_receivable(ar_id: str, payload: ReceivablePaymentIn, user: dict = Depends(require_auth)):
    _require_payment_role(user)
    db = get_db()
    ar = await db.rahaza_ar_invoices.find_one({'id': ar_id, 'schedule_mode': 'v2'}, {'_id': 0})
    if not ar:
        raise HTTPException(404, 'Piutang terjadwal tidak ditemukan')
    return await _schedule_payment(db, ar, payload.amount, payload.cash_account_id, payload.payment_date,
                                   payload.notes or '', payload.reference_no or '', user)


@router.post('/receivables/{ar_id}/payments/{payment_id}/void', dependencies=only(*FINANCE_ROLES))
async def void_receivable_payment(ar_id: str, payment_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    from core import maklon_ledger
    try:
        return await maklon_ledger.void_client_payment(db, ar_id, payment_id, user, reason='Dibatalkan Keuangan')
    except ValueError as e:
        raise HTTPException(400, str(e))


def invoice_doc_for(ar: dict, shipment_id: Optional[str] = None, dispatch_seq: Optional[int] = None) -> dict:
    """Isi faktur CETAK (murni): per kiriman (shipment_id + dispatch_seq) atau seluruh PO."""
    term = ar.get('payment_terms') or 'net_30'
    if shipment_id:
        g = next((x for x in dispatch_groups(ar) if x['shipment_id'] == shipment_id
                  and (dispatch_seq is None or int(x['dispatch_seq'] or 0) == int(dispatch_seq))), None)
        if not g:
            raise HTTPException(404, 'Kiriman ini belum ditagih')
        d = date.fromisoformat(str(g['date'])[:10]) if g.get('date') else today_wib()
        return {
            'invoice_number': f"{ar.get('invoice_number')}/{g['seq_no']}", 'issue_date': d.isoformat(),
            'due_date': (d + timedelta(days=_payment_term_days(term))).isoformat(), 'payment_terms': term,
            'status': 'lunas' if g['balance'] <= 0.005 else 'belum lunas',
            'lines': [{'description': f"Jasa maklon {ln.get('sku') or ''} {ln.get('size') or ''}".strip(),
                       'sku': ln.get('sku'), 'qty': ln['qty'], 'unit': 'pcs', 'unit_price': ln.get('unit_price'),
                       'line_total': ln['amount']} for ln in g['lines']],
            'subtotal': g['subtotal'], 'tax_pct': ar.get('tax_pct') or 0, 'tax_amount': g['tax'],
            'total_amount': g['total'], 'paid_amount': g['paid'], 'balance_amount': g['balance'],
            'notes': (f"PO {ar.get('linked_maklon_po_number')} · surat jalan {g['shipment_number']} "
                      f"kirim ke-{g['dispatch_seq']}"),
            '_filename': f"Faktur_{ar.get('invoice_number')}_{g['seq_no']}.pdf"}
    return {
        'invoice_number': ar.get('invoice_number'), 'issue_date': ar.get('issue_date') or ar.get('invoice_date'),
        'due_date': ar.get('due_date'), 'payment_terms': term,
        'status': {'scheduled': 'terjadwal', 'paid': 'lunas', 'overdue': 'lewat jatuh tempo'}.get(
            ar.get('status'), 'belum lunas'),
        'lines': [{'description': ln.get('description'), 'sku': ln.get('sku'),
                   'qty': ln.get('qty_scheduled', ln.get('qty')), 'unit': 'pcs',
                   'unit_price': ln.get('unit_price'), 'line_total': ln.get('subtotal')}
                  for ln in ar.get('lines') or []],
        'subtotal': ar.get('scheduled_subtotal', ar.get('subtotal')), 'tax_pct': ar.get('tax_pct') or 0,
        'tax_amount': ar.get('scheduled_tax', ar.get('tax_amount')),
        'total_amount': ar.get('scheduled_total', ar.get('total_amount')),
        'paid_amount': ar.get('amount_paid'),
        'balance_amount': ar.get('outstanding_total', ar.get('amount_due')),
        'notes': (f"PO {ar.get('linked_maklon_po_number')} · sudah dikirim & ditagih "
                  + f"Rp {_num(ar.get('billed_total')):,.0f}".replace(',', '.')),
        '_filename': f"Faktur_{ar.get('invoice_number')}.pdf"}


@router.get('/receivables/{ar_id}/invoice.pdf')
async def receivable_invoice_pdf(ar_id: str, shipment_id: Optional[str] = None,
                                 dispatch_seq: Optional[int] = None, user: dict = Depends(require_auth)):
    """Faktur CETAK — dokumen saja, tidak menulis apa pun dan tidak membuat jurnal."""
    from fastapi.responses import Response
    from utils.invoice_pdf import build_invoice_pdf
    from utils.pdf_common import get_company_profile, get_doc_settings
    db = get_db()
    ar = await db.rahaza_ar_invoices.find_one({'id': ar_id, 'source_module': 'maklon_po'}, {'_id': 0})
    if not ar:
        raise HTTPException(404, 'Piutang tidak ditemukan')
    inv = invoice_doc_for(ar, shipment_id, dispatch_seq)
    fname = inv.pop('_filename')
    cl = await db.dewi_maklon_clients.find_one({'id': ar.get('customer_id')}, {'_id': 0}) or {'name': ar.get('customer_name')}
    co = await db.company_settings.find_one({}, {'_id': 0}) or {}
    _ds = await get_doc_settings(db, 'invoice-maklon')
    pdf = build_invoice_pdf(invoice=inv, client=cl, company=co, template=(_ds or {}).get('_template'),
                            profile=await get_company_profile(db))
    return Response(content=pdf, media_type='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="{fname}"'})
