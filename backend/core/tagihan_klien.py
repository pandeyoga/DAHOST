"""core.tagihan_klien — POSISI piutang per klien maklon, TAGIHAN klien gabungan, TERIMA pembayaran gabungan.

16 Nov 2026 (owner): klien sering memesan beberapa PO sekaligus, barang dikirim penuh atau sebagian, dan klien
MEMBAYAR GABUNGAN, bukan per PO. Yang boleh ditagih hanya yang sudah dikirim; nilai PO tetap terlihat sebagai
komitmen. Keputusan owner (rekomendasi):
  1. Jurnal tetap seperti sekarang — pendapatan dibukukan saat barang dikirim (`maklon_ledger.sync_ar_schedule`).
     Tagihan di sini DOKUMEN saja (nomor + PDF), tanpa jurnal baru.
  2. Pembayaran gabungan dibagi otomatis ke yang terlama dulu (`core.alokasi_bayar`), Keuangan boleh mengubah
     pembagiannya; kelebihan bayar = uang muka klien lewat jalur uang muka yang sudah ada (bagian uang muka pada
     pembayaran PO, otomatis dipakai saat PO itu mengirim barang).
  3. Tagihan: Keuangan memilih kiriman (boleh lintas PO satu klien) → SATU tagihan bernomor + PDF; batasnya =
     nilai kiriman yang belum ditagih. Batal hanya bila belum ada pembayaran.

Satuan "kiriman" = satu kelompok pendapatan PO per surat jalan + urutan kirim (`maklon_ledger.dispatch_groups`),
kunci `<id piutang PO>|<id surat jalan>|<urutan>`. Surat jalan gabungan beberapa PO = beberapa kiriman.
Status bayar tagihan DIHITUNG saat dibaca dari pembayaran per PO (urutan kiriman tertua dulu, sama dengan rincian
piutang PO), jadi benar apa pun jalur pembayarannya (per PO maupun gabungan).

Penerimaan gabungan memakai logika terima pembayaran yang SAMA (`maklon_ledger.record_client_payment`) per PO,
dengan batas per PO = sudah dikirim − sudah dibayar (bukan nilai PO); satu nomor bukti (`dewi_pembayaran_gabungan`)
dicap ke setiap pembayaran; gagal di tengah → pembayaran yang sempat tercatat dibatalkan kembali.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from core import alokasi_bayar as ab
from core import maklon_ledger as ml

logger = logging.getLogger(__name__)

COLL = 'dewi_tagihan_klien'
NOMOR_TAGIHAN = 'dewi_tagihan_klien.bill_number'
AKTIF, BATAL = 'aktif', 'dibatalkan'


def _now():
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _r2(v) -> float:
    return round(_f(v), 2)


def kunci_kiriman(ar_id: str, shipment_id, dispatch_seq) -> str:
    return f"{ar_id}|{shipment_id or ''}|{int(_f(dispatch_seq))}"


# ══════════════════════════════════════════════════════════════════════════════
# HITUNGAN MURNI
# ══════════════════════════════════════════════════════════════════════════════
def kiriman_po(ar: dict) -> list:
    """Kiriman PO yang sudah menjadi pendapatan (nilai > 0), dengan bagian yang sudah terbayar (FIFO PO)."""
    out = []
    for g in ml.dispatch_groups(ar):
        if _f(g.get('total')) <= 0.005:
            continue
        out.append({'key': kunci_kiriman(ar['id'], g.get('shipment_id'), g.get('dispatch_seq')), 'ar_id': ar['id'],
                    'ar_number': ar.get('invoice_number') or '', 'po_id': ar.get('linked_maklon_po_id') or '',
                    'po_number': ar.get('linked_maklon_po_number') or '', 'shipment_id': g.get('shipment_id') or '',
                    'shipment_number': g.get('shipment_number') or '', 'dispatch_seq': int(_f(g.get('dispatch_seq'))),
                    'tanggal': str(g.get('date') or '')[:10], 'subtotal': _r2(g.get('subtotal')),
                    'tax': _r2(g.get('tax')), 'total': _r2(g.get('total')), 'dibayar': _r2(g.get('paid')),
                    'items': [{'sku': ln.get('sku') or '', 'size': ln.get('size') or '', 'qty': int(_f(ln.get('qty'))),
                               'unit_price': _r2(ln.get('unit_price')), 'amount': _r2(ln.get('amount'))}
                              for ln in g.get('lines') or []]})
    return out


def tertagih_per_kiriman(tagihan: list) -> dict:
    """{kunci kiriman: jumlah yang sudah ditagih di tagihan AKTIF}."""
    out: dict = {}
    for t in tagihan or []:
        if t.get('status') != AKTIF:
            continue
        for ln in t.get('lines') or []:
            out[ln['key']] = _r2(out.get(ln['key'], 0) + _f(ln.get('amount')))
    return out


def bayar_per_baris(kiriman: dict, tagihan: list) -> dict:
    """{(id tagihan, kunci kiriman): terbayar}: bagian terbayar tiap kiriman (FIFO PO) dibagi ke baris tagihan aktif
    yang memuat kiriman itu, tagihan terlama dulu."""
    sisa = {k: _f(g.get('dibayar')) for k, g in (kiriman or {}).items()}
    out = {}
    for t in sorted([t for t in tagihan or [] if t.get('status') == AKTIF],
                    key=lambda t: (str(t.get('bill_date') or ''), str(t.get('bill_number') or ''))):
        for ln in t.get('lines') or []:
            k = ln['key']
            ambil = _r2(min(max(sisa.get(k, 0.0), 0.0), _f(ln.get('amount'))))
            out[(t['id'], k)] = ambil
            sisa[k] = sisa.get(k, 0.0) - ambil
    return out


def status_bayar_tagihan(t: dict, bayar: dict) -> dict:
    """Angka bayar satu tagihan dari `bayar_per_baris`."""
    if t.get('status') != AKTIF:
        return {'dibayar': 0.0, 'sisa': 0.0, 'status_bayar': BATAL}
    dibayar = _r2(sum(bayar.get((t['id'], ln['key']), 0.0) for ln in t.get('lines') or []))
    sisa = _r2(max(0.0, _f(t.get('total')) - dibayar))
    st = 'lunas' if sisa <= 0.5 else 'sebagian' if dibayar > 0.5 else 'belum_dibayar'
    return {'dibayar': dibayar, 'sisa': sisa, 'status_bayar': st}


def boleh_tagih_kiriman(k: dict, tertagih: dict) -> float:
    """Yang boleh ditagih dari satu kiriman = nilai kiriman − yang sudah ditagih. Kiriman yang SUDAH LUNAS sebelum
    pernah ditagih (uang muka terpakai / dibayar per PO) tidak perlu ditagih lagi → 0. Kiriman yang baru dibayar
    sebagian tetap ditagih utuh; tagihannya menampilkan bagian yang sudah dibayar."""
    sudah = _f(tertagih.get(k['key'], 0.0))
    if sudah <= 0.005 and _f(k.get('dibayar')) >= _f(k.get('total')) - 0.5:
        return 0.0
    return _r2(max(0.0, _f(k.get('total')) - sudah))


def baris_po(ar: dict, kiriman: list, tertagih: dict, tagihan: list) -> dict:
    """Posisi satu PO maklon: komitmen, dikirim, ditagih, dibayar, boleh ditagih, sisa piutang, uang muka."""
    ditagih = _r2(sum(_f(ln.get('amount')) for t in tagihan if t.get('status') == AKTIF
                      for ln in t.get('lines') or [] if ln.get('ar_id') == ar['id']))
    boleh = _r2(sum(boleh_tagih_kiriman(k, tertagih) for k in kiriman))
    belum_lunas = [k['tanggal'] for k in kiriman if k['total'] - k['dibayar'] > 0.5]
    tagih_terbuka = sorted(str(t.get('bill_date') or '') for t in tagihan if t.get('status') == AKTIF
                           and any(ln.get('ar_id') == ar['id'] for ln in t.get('lines') or []))
    sisa_piutang = _r2(ar.get('amount_due'))
    return {
        'ar_id': ar['id'], 'invoice_number': ar.get('invoice_number') or '', 'po_id': ar.get('linked_maklon_po_id'),
        'po_number': ar.get('linked_maklon_po_number') or '', 'po_status': ar.get('po_status') or '',
        'status': ar.get('status') or '', 'komitmen': _r2(ar.get('scheduled_total')),
        'dikirim': _r2(ar.get('billed_total')), 'ditagih': ditagih, 'boleh_ditagih': boleh,
        'dibayar': _r2(ar.get('amount_paid')), 'uang_muka': _r2(max(0.0, _f(ar.get('advance_balance')))),
        'denda': _r2(ar.get('denda_credit')), 'sisa_piutang': sisa_piutang,
        'belum_dikirim': _r2(ar.get('scheduled_remaining')), 'due_date': ar.get('due_date'),
        # batas terima pembayaran PO (jalur uang muka lama): sisa nilai PO yang belum dibayar
        'batas_terima': _r2(max(_f(ar.get('scheduled_total')), _f(ar.get('billed_total')))
                            - _f(ar.get('amount_paid')) - _f(ar.get('denda_credit'))),
        # urutan bayar: tagihan tertua yang memuat PO ini → kiriman tertua yang belum lunas
        'urut': (tagih_terbuka[0] if tagih_terbuka and sisa_piutang > 0.005 else
                 (belum_lunas[0] if belum_lunas else '')) or '',
    }


def po_masih_berjalan(r: dict) -> bool:
    return any(r[k] > 0.5 for k in ('belum_dikirim', 'sisa_piutang', 'boleh_ditagih', 'uang_muka'))


def alokasi_terima(jumlah: float, pos: list) -> tuple[list, float]:
    """Usulan pembagian penerimaan klien: per PO terlama dulu, batas = sudah dikirim − sudah dibayar."""
    return ab.alokasi_terlama(jumlah, [{'id': r['ar_id'], 'batas': r['sisa_piutang'], 'urut': r['urut'],
                                        'nomor': r['po_number']} for r in pos])


def tempatkan_uang_muka(kelebihan: float, pos: list, alokasi: dict) -> tuple[dict, float]:
    """Kelebihan bayar → uang muka di PO klien yang masih menunggu kiriman (terlama dulu), sampai batas terima PO
    itu (jalur uang muka yang sudah ada). → ({ar_id: tambahan}, sisa yang tidak bisa ditempatkan)."""
    out, sisa = {}, _r2(kelebihan)
    for r in ab.urutkan([{**r, 'nomor': r['po_number']} for r in pos if r['belum_dikirim'] > 0.5]):
        if sisa <= 0.005:
            break
        ruang = _r2(r['batas_terima'] - alokasi.get(r['ar_id'], 0.0))
        if ruang <= 0.005:
            continue
        ambil = _r2(min(ruang, sisa))
        out[r['ar_id']] = ambil
        sisa = _r2(sisa - ambil)
    return out, max(0.0, sisa)


# ══════════════════════════════════════════════════════════════════════════════
# POSISI PER KLIEN
# ══════════════════════════════════════════════════════════════════════════════
async def _muat(db, client_id: str | None):
    """Tagihan klien + piutang PO yang masih terbuka (belum lunas) atau dimuat tagihan aktif. Piutang PO yang sudah
    lunas dan tidak ada di tagihan mana pun tidak dimuat (tidak ada yang ditagih/dibayar lagi)."""
    tq: dict = {}
    if client_id:
        tq['client_id'] = client_id
    tagihan = [t async for t in db[COLL].find(tq, {'_id': 0}).sort('bill_date', -1).limit(3000)]
    ar_ids = sorted({ln.get('ar_id') for t in tagihan if t.get('status') == AKTIF for ln in t.get('lines') or []
                     if ln.get('ar_id')})
    q: dict = {'source_module': 'maklon_po', 'schedule_mode': ml.SCHEDULE_MODE,
               '$or': [{'status': {'$nin': ['cancelled', 'paid']}}, {'id': {'$in': ar_ids}}]}
    if client_id:
        q['customer_id'] = client_id
    ars = [a async for a in db.rahaza_ar_invoices.find(q, {'_id': 0}).sort('created_at', 1).limit(3000)]
    return ars, tagihan


async def posisi_klien(db, *, client_id: str | None = None, entity: str | None = None) -> dict:
    """Posisi piutang per klien maklon dan per PO + kiriman belum ditagih + tagihan (baca saja).
    Piutang klien maklon = buku CV Sukma; CV Dewi Aditya → kosong."""
    from core.entities import ALL, DA
    if entity == DA:
        return {'clients': [], 'totals': {}, 'entity': DA}
    ars, tagihan = await _muat(db, client_id)
    tertagih = tertagih_per_kiriman(tagihan)
    per_ar = {a['id']: kiriman_po(a) for a in ars}
    semua_kiriman = {k['key']: k for ks in per_ar.values() for k in ks}
    bayar = bayar_per_baris(semua_kiriman, tagihan)
    ids = sorted({a.get('customer_id') for a in ars if a.get('customer_id')} |
                 {t.get('client_id') for t in tagihan if t.get('client_id')})
    master = {c['id']: c async for c in db.dewi_maklon_clients.find(
        {'id': {'$in': ids}}, {'_id': 0, 'id': 1, 'name': 1, 'code': 1})} if ids else {}
    clients: dict = {}

    def klien(cid, nama):
        m = master.get(cid) or {}
        return clients.setdefault(cid, {'client_id': cid, 'client_name': m.get('name') or nama or '(tanpa nama)',
                                        'client_code': m.get('code') or '', 'pos': [], 'kiriman': [],
                                        'tagihan': []})
    tagihan_klien: dict = {}
    for t in tagihan:
        tagihan_klien.setdefault(t.get('client_id'), []).append(t)
    for a in ars:
        r = baris_po(a, per_ar[a['id']], tertagih, tagihan_klien.get(a.get('customer_id')) or [])
        c = klien(a.get('customer_id'), a.get('customer_name'))
        if po_masih_berjalan(r):
            c['pos'].append(r)
        for k in per_ar[a['id']]:
            boleh = boleh_tagih_kiriman(k, tertagih)
            if boleh > 0.005:
                c['kiriman'].append({**{x: k[x] for x in k if x != 'dibayar'},
                                     'sudah_ditagih': _r2(tertagih.get(k['key'], 0.0)), 'boleh_ditagih': boleh})
    for t in tagihan:
        c = klien(t.get('client_id'), t.get('client_name'))
        c['tagihan'].append({**t, **status_bayar_tagihan(t, bayar)})
    hasil = []
    for c in clients.values():
        c['pos'].sort(key=lambda r: (str(r['urut'] or '9999'), str(r['po_number'])))
        c['kiriman'].sort(key=lambda k: (k['tanggal'], k['shipment_number'], k['po_number']))
        c['tagihan'].sort(key=lambda t: (str(t.get('bill_date') or ''), str(t.get('bill_number') or '')), reverse=True)
        for k in ('komitmen', 'dikirim', 'ditagih', 'boleh_ditagih', 'dibayar', 'uang_muka', 'sisa_piutang',
                  'belum_dikirim', 'denda'):
            c[k] = _r2(sum(r[k] for r in c['pos']))
        c['tagihan_terbuka'] = _r2(sum(t['sisa'] for t in c['tagihan'] if t['status_bayar'] in ('belum_dibayar', 'sebagian')))
        if c['pos'] or c['kiriman'] or c['tagihan_terbuka'] > 0.5:
            hasil.append(c)
    hasil.sort(key=lambda c: (-c['sisa_piutang'], -c['boleh_ditagih'], str(c['client_name']).lower()))
    tot = {k: _r2(sum(c[k] for c in hasil)) for k in
           ('komitmen', 'dikirim', 'ditagih', 'boleh_ditagih', 'dibayar', 'uang_muka', 'sisa_piutang', 'belum_dikirim')}
    return {'clients': hasil, 'totals': tot, 'entity': entity or ALL}


async def _satu_klien(db, client_id: str) -> dict:
    out = await posisi_klien(db, client_id=client_id)
    return next((c for c in out['clients'] if c['client_id'] == client_id), None) or {
        'client_id': client_id, 'client_name': '', 'pos': [], 'kiriman': [], 'tagihan': []}


# ══════════════════════════════════════════════════════════════════════════════
# TAGIHAN KLIEN GABUNGAN (dokumen saja, tanpa jurnal)
# ══════════════════════════════════════════════════════════════════════════════
async def _kunci_klien(db, client_id: str, field: str, user: dict, busy: str) -> str:
    from core import doc_lock
    return await doc_lock.claim(db, 'dewi_maklon_clients', client_id, field=field, actor=user, busy=busy,
                                not_found='Klien maklon tidak ditemukan di master klien.')


async def buat_tagihan(db, *, client_id: str, keys: list, bill_date: str | None, user: dict, notes: str = '') -> dict:
    """Satu tagihan bernomor untuk kiriman pilihan (boleh lintas PO satu klien). Batas tiap baris = nilai kiriman
    yang belum ditagih. ValueError = ditolak."""
    from core import doc_lock
    from routes.dewi_system_config import get_config_value
    from utils.waktu import today_wib
    keys = [str(k) for k in dict.fromkeys(keys or []) if k]
    if not client_id:
        raise ValueError('Pilih klien maklon.')
    if not keys:
        raise ValueError('Pilih minimal satu kiriman yang ditagih.')
    token = await _kunci_klien(db, client_id, 'tagihan_lock', user,
                               'Tagihan klien ini sedang dibuat pengguna lain. Muat ulang lalu periksa kirimannya.')
    try:
        c = await _satu_klien(db, client_id)
        boleh = {k['key']: k for k in c['kiriman']}
        for key in keys:
            if key in boleh:
                continue
            ar = await db.rahaza_ar_invoices.find_one({'id': key.split('|')[0]}, {'_id': 0, 'customer_id': 1,
                                                                                   'customer_name': 1})
            if ar and ar.get('customer_id') != client_id:
                raise ValueError(f"Kiriman yang dipilih milik klien lain ({ar.get('customer_name') or '-'}) — satu "
                                 "tagihan hanya untuk satu klien.")
            raise ValueError('Kiriman yang dipilih sudah ditagih penuh atau belum dikirim — muat ulang lalu ulangi.')
        bdate = (bill_date or today_wib().isoformat())[:10]
        try:
            d = date.fromisoformat(bdate)
        except ValueError:
            raise ValueError('Tanggal tagihan tidak sah.')
        lines = []
        for key in keys:
            k = boleh[key]
            amt = _r2(k['boleh_ditagih'])
            rasio = amt / k['total'] if k['total'] else 0.0
            penuh = abs(amt - k['total']) <= 0.01
            lines.append({'key': key, 'ar_id': k['ar_id'], 'ar_number': k['ar_number'], 'po_id': k['po_id'],
                          'po_number': k['po_number'], 'shipment_id': k['shipment_id'],
                          'shipment_number': k['shipment_number'], 'dispatch_seq': k['dispatch_seq'],
                          'ship_date': k['tanggal'], 'amount': amt,
                          'subtotal': k['subtotal'] if penuh else _r2(k['subtotal'] * rasio),
                          'tax': k['tax'] if penuh else _r2(amt - _r2(k['subtotal'] * rasio)),
                          'items': k['items'] if penuh else []})
        term = await get_config_value(db, 'maklon_payment_terms_default', 'net_30') or 'net_30'
        first_ar = await db.rahaza_ar_invoices.find_one({'id': lines[0]['ar_id']}, {'_id': 0, 'payment_terms': 1,
                                                                                     'tax_pct': 1})
        term = (first_ar or {}).get('payment_terms') or term
        nomor = await ab.terbitkan_nomor(db, NOMOR_TAGIHAN)
        doc = {'id': str(uuid.uuid4()), 'bill_number': nomor, 'client_id': client_id,
               'client_name': c.get('client_name') or '', 'client_code': c.get('client_code') or '', 'entity': 'SMU',
               'bill_date': bdate, 'payment_terms': term,
               'due_date': (d + timedelta(days=ml.TERM_DAYS.get(term, 30))).isoformat(),
               'tax_pct': _f((first_ar or {}).get('tax_pct')), 'lines': lines,
               'subtotal': _r2(sum(x['subtotal'] for x in lines)), 'tax_amount': _r2(sum(x['tax'] for x in lines)),
               'total': _r2(sum(x['amount'] for x in lines)),
               'po_numbers': sorted({x['po_number'] for x in lines if x['po_number']}),
               'notes': notes or '', 'status': AKTIF, 'created_at': _now(), 'created_by': user.get('id'),
               'created_by_name': user.get('name', '')}
        await db[COLL].insert_one(dict(doc))
        from auth import log_activity
        await log_activity(user.get('id', ''), user.get('name', ''), 'buat_tagihan_klien', COLL,
                           f"{nomor}: {doc['client_name']} {ab._rp(doc['total'])} untuk {len(lines)} kiriman "
                           f"(PO {', '.join(doc['po_numbers'])})")
        return doc
    finally:
        await doc_lock.release(db, 'dewi_maklon_clients', client_id, token, field='tagihan_lock')


async def rincian_tagihan(db, bill_id: str) -> dict:
    t = await db[COLL].find_one({'id': bill_id}, {'_id': 0})
    if not t:
        raise LookupError('Tagihan klien tidak ditemukan.')
    c = await _satu_klien(db, t['client_id'])
    hit = next((x for x in c['tagihan'] if x['id'] == bill_id), None)
    return hit or {**t, **status_bayar_tagihan(t, {})}


async def batal_tagihan(db, bill_id: str, *, reason: str, user: dict) -> dict:
    """Batalkan tagihan yang BELUM ada pembayarannya (kiriman di dalamnya bisa ditagih ulang)."""
    if len((reason or '').strip()) < 3:
        raise ValueError('Tulis alasan pembatalan (minimal 3 huruf).')
    t = await rincian_tagihan(db, bill_id)
    if t.get('status') != AKTIF:
        raise ValueError(f"Tagihan {t.get('bill_number')} sudah dibatalkan.")
    if _f(t.get('dibayar')) > 0.5:
        raise ValueError(f"Tagihan {t['bill_number']} sudah dibayar {ab._rp(t['dibayar'])} — tidak bisa dibatalkan.")
    res = await db[COLL].update_one({'id': bill_id, 'status': AKTIF}, {'$set': {
        'status': BATAL, 'cancel_reason': reason.strip(), 'cancelled_at': _now(), 'cancelled_by': user.get('name', ''),
        'cancelled_by_id': user.get('id')}})
    if not getattr(res, 'matched_count', 1):
        raise ValueError('Tagihan ini baru saja diubah pengguna lain — muat ulang.')
    from auth import log_activity
    await log_activity(user.get('id', ''), user.get('name', ''), 'batal_tagihan_klien', COLL,
                       f"{t['bill_number']} dibatalkan: {reason.strip()}")
    return await db[COLL].find_one({'id': bill_id}, {'_id': 0})


def isi_pdf_tagihan(t: dict) -> dict:
    """Isi faktur CETAK tagihan gabungan (gaya faktur piutang maklon yang sama, `utils.invoice_pdf`)."""
    lines = []
    for ln in t.get('lines') or []:
        head = f"PO {ln.get('po_number')} · SJ {ln.get('shipment_number')} kirim ke-{ln.get('dispatch_seq')}"
        if ln.get('items'):
            for it in ln['items']:
                lines.append({'description': f"{head} — jasa maklon {it.get('size') or ''}".strip(),
                              'sku': it.get('sku'), 'qty': it.get('qty'), 'unit': 'pcs',
                              'unit_price': it.get('unit_price'), 'line_total': it.get('amount')})
        else:
            lines.append({'description': f"{head} — sisa kiriman yang belum ditagih", 'sku': '', 'qty': 1,
                          'unit': 'kiriman', 'unit_price': ln.get('subtotal'), 'line_total': ln.get('subtotal')})
    status = {'lunas': 'lunas', 'sebagian': 'dibayar sebagian', 'dibatalkan': 'dibatalkan'}.get(
        t.get('status_bayar'), 'belum lunas')
    return {'invoice_number': t.get('bill_number'), 'issue_date': t.get('bill_date'), 'due_date': t.get('due_date'),
            'payment_terms': t.get('payment_terms') or 'net_30', 'status': status, 'lines': lines,
            'subtotal': t.get('subtotal'), 'tax_pct': t.get('tax_pct') or 0, 'tax_amount': t.get('tax_amount'),
            'total_amount': t.get('total'), 'paid_amount': t.get('dibayar') or 0,
            'balance_amount': t.get('sisa') if t.get('sisa') is not None else t.get('total'),
            'notes': (f"Tagihan gabungan {len(t.get('lines') or [])} kiriman dari PO "
                      f"{', '.join(t.get('po_numbers') or [])}." + (f" {t['notes']}" if t.get('notes') else ''))}


# ══════════════════════════════════════════════════════════════════════════════
# TERIMA PEMBAYARAN KLIEN GABUNGAN
# ══════════════════════════════════════════════════════════════════════════════
async def terima_gabungan(db, *, client_id: str, amount: float, cash_account_id: str, payment_date: str | None,
                          alokasi: list | None, user: dict, notes: str = '', reference_no: str = '') -> dict:
    """Satu penerimaan dari SATU klien untuk beberapa PO. Batas per PO = sudah dikirim − sudah dibayar; kelebihan
    = uang muka di PO yang masih menunggu kiriman. ValueError = ditolak."""
    from fastapi import HTTPException
    from core import doc_lock
    from core.entities import SMU, entity_of_value, entity_short
    from utils.waktu import today_wib
    if not client_id:
        raise ValueError('Pilih klien maklon.')
    amount = _r2(amount)
    if amount <= 0:
        raise ValueError('Jumlah diterima harus lebih dari 0.')
    acc = await db.rahaza_cash_accounts.find_one({'id': cash_account_id, 'active': {'$ne': False}}, {'_id': 0}) \
        if cash_account_id else None
    if not acc:
        raise ValueError('Pilih rekening kas/bank penerima yang aktif.')
    if entity_of_value(acc.get('entity')) != SMU:
        raise ValueError(f"Rekening {acc.get('name') or ''} milik {entity_short(entity_of_value(acc.get('entity')))}"
                         " — pembayaran klien maklon masuk rekening CV Sukma.")
    token = await _kunci_klien(db, client_id, 'pay_lock', user,
                               'Pembayaran klien ini sedang dicatat pengguna lain. Muat ulang lalu periksa sisanya.')
    try:
        c = await _satu_klien(db, client_id)
        pos = c['pos']
        by_ar = {r['ar_id']: r for r in pos}
        caps = {r['ar_id']: r['sisa_piutang'] for r in pos if r['sisa_piutang'] > 0.005}
        label = {r['ar_id']: f"PO {r['po_number']}" for r in pos}
        if not alokasi:
            lines, _ = alokasi_terima(amount, pos)
        else:
            for a in alokasi:
                aid = str((a or {}).get('id') or '')
                if not aid or aid in caps or _f((a or {}).get('jumlah')) <= 0.005:
                    continue
                if aid in by_ar:
                    raise ValueError(f"{label[aid]} belum punya piutang dari kiriman (sudah dibayar penuh atau belum "
                                     "dikirim) — sisakan sebagai uang muka.")
                ar = await db.rahaza_ar_invoices.find_one({'id': aid}, {'_id': 0, 'customer_name': 1,
                                                                        'linked_maklon_po_number': 1})
                if ar:
                    raise ValueError(f"PO {ar.get('linked_maklon_po_number') or '-'} milik klien lain "
                                     f"({ar.get('customer_name') or '-'}) — satu penerimaan hanya untuk satu klien.")
                raise ValueError('PO di pembagian tidak ditemukan — muat ulang lalu ulangi.')
            lines = ab.periksa_alokasi(alokasi, caps, label=label, apa='PO')
        dibagi = _r2(sum(x['jumlah'] for x in lines))
        if dibagi > amount + ab.TOLERANSI:
            raise ValueError(f"Pembagian {ab._rp(dibagi)} melebihi jumlah diterima {ab._rp(amount)}.")
        kelebihan = _r2(max(0.0, amount - dibagi))
        alloc = {x['id']: x['jumlah'] for x in lines}
        tambah, tersisa = tempatkan_uang_muka(kelebihan, pos, alloc) if kelebihan > ab.TOLERANSI else ({}, 0.0)
        if tersisa > ab.TOLERANSI:
            raise ValueError(f"Kelebihan {ab._rp(tersisa)} tidak bisa dicatat sebagai uang muka: tidak ada PO "
                             f"{c.get('client_name') or 'klien ini'} yang masih menunggu kiriman dengan sisa nilai "
                             "cukup. Kurangi jumlah diterima atau catat sisanya terpisah.")
        urutan = [x['id'] for x in lines] + [i for i in tambah if i not in alloc]
        pdate = (payment_date or today_wib().isoformat())[:10]
        bid = str(uuid.uuid4())
        nomor = await ab.terbitkan_nomor(db, ab.NOMOR_TERIMA_KLIEN)
        batch = {'batch_id': bid, 'bukti_number': nomor}
        doc = {'id': bid, 'jenis': ab.JENIS_TERIMA_KLIEN, 'bukti_number': nomor, 'pihak_id': client_id,
               'pihak_name': c.get('client_name') or '', 'entity': SMU, 'tanggal': pdate, 'amount': amount,
               'cash_account_id': acc['id'], 'cash_account_name': acc.get('name', ''),
               'reference_no': reference_no or '', 'notes': notes or '', 'status': 'proses', 'alokasi': [],
               'created_at': _now(), 'created_by': user.get('id'), 'created_by_name': user.get('name', '')}
        await db[ab.COLL].insert_one(dict(doc))
        tagihan_po = {}
        for t in c['tagihan']:
            if t['status_bayar'] in ('belum_dibayar', 'sebagian'):
                for ln in t.get('lines') or []:
                    tagihan_po.setdefault(ln['ar_id'], set()).add(t['bill_number'])
        done = []
        try:
            for aid in urutan:
                jml = _r2(alloc.get(aid, 0.0) + tambah.get(aid, 0.0))
                pay = await ml.record_client_payment(
                    db, aid, amount=jml, cash_account_id=acc['id'], payment_date=pdate,
                    notes=f"{nomor}" + (f" · {notes}" if notes else ''), reference_no=reference_no or nomor,
                    user=user, batch=batch)
                done.append((aid, pay))
        except (HTTPException, ValueError) as e:
            pesan = e.detail if isinstance(e, HTTPException) else str(e)
            for aid, pay in reversed(done):
                try:
                    await ml.void_client_payment(db, aid, pay['id'], user, reason=f'Bukti {nomor} gagal dicatat')
                except Exception:  # noqa: BLE001 — lanjut menggulung yang lain; dicatat untuk Keuangan
                    logger.exception('gulung balik pembayaran klien %s piutang %s gagal', pay.get('id'), aid)
            await db[ab.COLL].update_one({'id': bid}, {'$set': {'status': 'gagal', 'error': pesan, 'updated_at': _now()}})
            raise ValueError(f"Penerimaan {nomor} tidak dicatat: {pesan}"
                             + (f" {len(done)} pembayaran yang sempat tercatat sudah dibatalkan kembali." if done else ''))
        rincian = []
        for aid, pay in done:
            r = by_ar.get(aid) or {}
            rincian.append({'ar_id': aid, 'invoice_number': pay.get('invoice_number'), 'po_id': pay.get('po_id'),
                            'po_number': pay.get('po_number') or r.get('po_number'), 'jumlah': _r2(pay.get('amount')),
                            'ke_piutang': _r2(pay.get('ar_portion')), 'ke_uang_muka': _r2(pay.get('advance_portion')),
                            'payment_id': pay.get('id'), 'je_number': pay.get('gl_je_number'),
                            'tagihan': sorted(tagihan_po.get(aid, set()))})
        upd = {'status': 'tercatat', 'alokasi': rincian, 'updated_at': _now(),
               'ke_piutang': _r2(sum(x['ke_piutang'] for x in rincian)),
               'ke_uang_muka': _r2(sum(x['ke_uang_muka'] for x in rincian))}
        await db[ab.COLL].update_one({'id': bid}, {'$set': upd})
        from auth import log_activity
        await log_activity(user.get('id', ''), user.get('name', ''), 'terima_klien_gabungan', ab.COLL,
                           f"{nomor}: terima dari {doc['pihak_name']} {ab._rp(amount)} untuk {len(rincian)} PO "
                           f"(uang muka {ab._rp(upd['ke_uang_muka'])})")
        return {**doc, **upd}
    finally:
        await doc_lock.release(db, 'dewi_maklon_clients', client_id, token, field='pay_lock')
