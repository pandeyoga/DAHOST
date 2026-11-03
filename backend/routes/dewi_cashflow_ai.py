"""
AI Cash Flow Prediction — CV. Dewi Aditya ERP
Endpoint: GET /api/finance/ai-cashflow

Aggregates AR aging + AP aging (pemasok + CMT) + saldo & arus kas 60 hari dari buku besar, then calls Claude
(lewat lapisan tunggal `services.ai`, 2026-11-02) to generate a short-term
cash flow prediction with risks & recommendations.
"""
from fastapi import APIRouter, Request
from database import get_db
from auth import require_auth, serialize_doc
from datetime import date, timedelta
import logging

from services.ai import AIError, Pseudonymizer, ai_http_error, ai_text, require_ai
from utils.waktu import today_wib
from core.payables import bucket_of

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["AI-CashFlow"])

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _fmt(n: float) -> str:
    """Format number as Rp X juta / miliar."""
    if n >= 1_000_000_000:
        return f"Rp {n/1_000_000_000:.2f} miliar"
    if n >= 1_000_000:
        return f"Rp {n/1_000_000:.1f} juta"
    return f"Rp {n:,.0f}"


AR_OPEN = ['sent', 'issued', 'partial', 'partial_paid', 'overdue']   # FIN-09
_BUCKET_KEY = {'current': 'current', '1_30': '1-30', '31_60': '31-60', '61_90': '61-90', '90_plus': '90+'}


async def _build_context(db) -> dict:
    """Fetch & aggregate data for the LLM prompt.

    2026-11-04 (owner, audit Keuangan — Prediksi Kas jadi tab "Perkiraan" di Arus Kas):
      · saldo kas & arus kas 60 hari dari BUKU BESAR (`core.cash_position`) — dulu dari
        `rahaza_cash_movements` (tanpa jurnal manual/impor/gaji) dan tanpa saldo kas sama sekali;
      · hutang dari SSOT `core.payables` — tagihan pemasok + tagihan CMT (dulu CMT tidak ikut);
      · tanpa batas 500 faktur.
    """
    from core.cash_position import cash_position
    from core.payables import aging, open_payable_rows
    today = today_wib()
    sixty_ago = (today - timedelta(days=60)).isoformat()
    today_iso = today.isoformat()
    next_30 = (today + timedelta(days=30)).isoformat()

    # ── AR aging ──
    ar_invs = [i async for i in db.rahaza_ar_invoices.find(
        {'status': {'$in': AR_OPEN}},
        {'_id': 0, 'balance': 1, 'due_date': 1, 'buyer_name': 1, 'customer_name': 1, 'customer_id': 1, 'total': 1})]
    ar_buckets = {'current': 0, '1-30': 0, '31-60': 0, '61-90': 0, '90+': 0}
    for inv in ar_invs:
        bal = float(inv.get('balance', 0) or 0)
        try:
            diff = (today - date.fromisoformat(str(inv.get('due_date') or '')[:10])).days
        except ValueError:
            diff = 0
        ar_buckets[_BUCKET_KEY[bucket_of(diff)]] += bal
    total_ar = sum(ar_buckets.values())
    overdue_ar = total_ar - ar_buckets['current']

    # ── AP aging (pemasok + CMT, yang sudah dijurnal — sama dengan buku besar) ──
    ap = aging(await open_payable_rows(db), today)
    ap_buckets = {_BUCKET_KEY[k]: v for k, v in ap['buckets'].items()}
    total_ap = ap['total']

    # ── Posisi & arus kas 60 hari dari buku besar ──
    cash = await cash_position(db, sixty_ago, today_iso)

    # ── Kewajiban & tagihan 30 hari ke depan ──
    upcoming_ap = sorted(
        [{'vendor_name': r['vendor_name'], 'balance': r['balance'], 'due_date': r['due_date'], 'kind': r['kind']}
         for r in ap['details'] if today_iso <= r['due_date'] <= next_30],
        key=lambda r: r['due_date'])[:10]
    upcoming_ar = await db.rahaza_ar_invoices.find(
        {'status': {'$in': AR_OPEN}, 'due_date': {'$gte': today_iso, '$lte': next_30}},
        {'_id': 0, 'buyer_name': 1, 'customer_name': 1, 'customer_id': 1, 'balance': 1, 'due_date': 1}
    ).sort('due_date', 1).to_list(10)
    cids = list({i.get('customer_id') for i in upcoming_ar if i.get('customer_id') and not i.get('customer_name')})
    if cids:
        names = {c['id']: c.get('name') async for c in db.rahaza_customers.find(
            {'id': {'$in': cids}}, {'_id': 0, 'id': 1, 'name': 1})}
        for i in upcoming_ar:
            i.setdefault('customer_name', names.get(i.get('customer_id')))

    # ── Active production orders (cash commitment) ──
    active_orders = await db.rahaza_orders.count_documents({'status': {'$in': ['confirmed', 'in_production']}})

    return {
        'today': today_iso,
        'cash_balance': cash['balance'],
        'ar_buckets': ar_buckets, 'total_ar': total_ar, 'overdue_ar': overdue_ar,
        'ap_buckets': ap_buckets, 'total_ap': total_ap, 'ap_unposted': ap['unposted_total'],
        'cash_in_60': cash['cash_in'], 'cash_out_60': cash['cash_out'],
        'upcoming_ar': upcoming_ar, 'upcoming_ap': upcoming_ap,
        'active_orders': active_orders,
    }


def _build_prompt(ctx: dict, ps: Pseudonymizer | None = None) -> str:
    """K27 (2026-11-02): nama pelanggan/vendor → kode samaran PLG-xxx / VND-xxx.

    Pemetaan balik dilakukan di server (`ps.restore`) pada jawaban AI.
    """
    ps = ps or Pseudonymizer()
    ar = ctx['ar_buckets']
    ap = ctx['ap_buckets']
    upar = [{**i, '_ref': ps.code(i.get('customer_name') or i.get('buyer_name') or '?', 'pelanggan')}
            for i in ctx['upcoming_ar']]
    upap = [{**i, '_ref': ps.code(i.get('vendor_name') or '?', 'vendor')} for i in ctx['upcoming_ap']]
    prompt = f"""Anda adalah CFO digital untuk CV. Dewi Aditya, perusahaan garmen di Indonesia.
Tanggal hari ini: {ctx['today']}.

DATA KEUANGAN AKTUAL:

Piutang Usaha (AR) yang belum terbayar:
- Belum jatuh tempo : {_fmt(ar['current'])}
- Telat 1-30 hari   : {_fmt(ar['1-30'])}
- Telat 31-60 hari  : {_fmt(ar['31-60'])}
- Telat 61-90 hari  : {_fmt(ar['61-90'])}
- Telat >90 hari    : {_fmt(ar['90+'])}
- TOTAL AR Outstanding: {_fmt(ctx['total_ar'])}  |  Overdue: {_fmt(ctx['overdue_ar'])}

Hutang Usaha (pemasok + CMT) yang belum dibayar:
- Belum jatuh tempo : {_fmt(ap['current'])}
- Jatuh tempo 1-30 h: {_fmt(ap['1-30'])}
- Jatuh tempo 31-60h: {_fmt(ap['31-60'])}
- Jatuh tempo >60 h : {_fmt(ap['61-90'] + ap['90+'])}
- TOTAL AP Outstanding: {_fmt(ctx['total_ap'])}

Saldo kas & bank hari ini (buku besar): {_fmt(ctx['cash_balance'])}

Arus Kas 60 hari terakhir (buku besar, tanpa transfer antar rekening):
- Kas masuk: {_fmt(ctx['cash_in_60'])}
- Kas keluar: {_fmt(ctx['cash_out_60'])}
- Net 60 hari: {_fmt(ctx['cash_in_60'] - ctx['cash_out_60'])}

Tagihan AR yang jatuh tempo 30 hari ke depan:
{chr(10).join(f"- {i['_ref']}: {_fmt(float(i.get('balance',0)))} (due: {i.get('due_date','')})" for i in upar) or '- Tidak ada'}

Kewajiban AP yang jatuh tempo 30 hari ke depan:
{chr(10).join(f"- {i['_ref']}: {_fmt(float(i.get('balance',0)))} (due: {i.get('due_date','')})" for i in upap) or '- Tidak ada'}

(Nama pelanggan/vendor disamarkan dengan kode PLG-xxx / VND-xxx; pakai kode itu apa adanya.)

Order produksi aktif: {ctx['active_orders']} order

Berikan analisis arus kas dalam Bahasa Indonesia yang singkat dan actionable, mencakup:
1. **Ringkasan Posisi Kas** (2-3 kalimat)
2. **Risiko 30 Hari** (bullet poin, max 3 risiko utama)
3. **Risiko 60-90 Hari** (bullet poin, max 2 risiko)
4. **Rekomendasi Prioritas** (3 tindakan konkret)
5. **Estimasi Net Cash Flow** 30/60/90 hari berdasarkan tren

Format: ringkas, profesional, gunakan angka Rupiah. Jangan pakai disclaimer panjang."""
    return prompt


# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINT
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/ai-cashflow")
async def ai_cashflow_prediction(request: Request):
    """
    AI Cash Flow Prediction — analisis arus kas 30/60/90 hari ke depan.
    Menggunakan data AR/AP aging + arus kas historis untuk menghasilkan
    prediksi dan rekomendasi berbasis Claude (tier standard — K29: Opus khusus
    Laporan Eksekutif).
    """
    user = await require_auth(request)
    db = get_db()

    # 2026-11-02: gerbang tunggal (kunci Anthropic + SDK); pesan ramah, tanpa nama env.
    await require_ai("cashflow", user_id=user.get("id"), db=db, tier="standard")

    # ── Build context ──
    ctx = await _build_context(db)

    # ── Call LLM ── (K27: nama disamarkan, dipetakan balik di server)
    ps = Pseudonymizer()
    try:
        analysis = ps.restore(await ai_text(
            "cashflow",
            "Kamu adalah CFO digital yang ahli keuangan garmen Indonesia.",
            _build_prompt(ctx, ps),
            tier="standard",
            user_id=user.get("id"),
        ))
    except AIError as e:
        raise ai_http_error(e)

    return {
        'analysis': analysis,
        'context': {
            'today': ctx['today'],
            'cash_balance': ctx['cash_balance'],
            'ap_unposted': ctx['ap_unposted'],
            'total_ar': ctx['total_ar'],
            'overdue_ar': ctx['overdue_ar'],
            'total_ap': ctx['total_ap'],
            'cash_in_60': ctx['cash_in_60'],
            'cash_out_60': ctx['cash_out_60'],
            'net_60': ctx['cash_in_60'] - ctx['cash_out_60'],
            'ar_aging': ctx['ar_buckets'],
            'ap_aging': ctx['ap_buckets'],
            'active_orders': ctx['active_orders'],
            'upcoming_ar': serialize_doc(ctx['upcoming_ar']),
            'upcoming_ap': serialize_doc(ctx['upcoming_ap']),
        }
    }
