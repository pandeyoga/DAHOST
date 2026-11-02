"""SSOT KAPASITAS KIRIM DA → BUYER (Fase E, 2026-08-15) + SSOT ANGKA QTY PER ITEM PO (K17).

MENGAPA MODUL INI ADA
---------------------
Sebelum ini ada **TIGA** rumus berbeda untuk pertanyaan yang sama — "item ini
masih boleh dikirim berapa?" — dan ketiganya menjawab angka berbeda pada layar
yang sama:

  1. Layar (`BuyerShipmentModule.buildConsItems`)
       cap = Σ(qty_actual − reject_qty), TANPA mengurangi yang sudah dikirim.
     Ini SALAH DUA KALI:
       · `qty_actual` pada `cmt_receipt_lines` sudah berarti **qty LOLOS QC**
         (buktinya `dewi_cmt_packing.py`: `arrived = qty_actual + reject_qty`),
         jadi mengurangi `reject_qty` lagi = memotong reject DUA KALI.
         Inilah sebab keluhan pemilik "chip tertulis 90 kok jadi 80".
       · tidak mengurangi qty yang sudah didispatch ⇒ layar mem-prefill angka
         yang PASTI ditolak backend, dan pemakai baru tahu setelah klik Simpan.
  2. Pagar backend (`_validate_source_receipts_cap`)
       max = Σ(qty_actual) − sudah didispatch **dari receipt yang sama**.
  3. Pagar stok (`_fg_precheck_for_dispatch`) memakai stok FG gudang.

2026-11-02 — K17 (keputusan owner): SATU fungsi angka qty per item PO
---------------------------------------------------------------------
`po_item_quantities()` adalah SATU-SATUNYA tempat angka qty per item PO dihitung.
Daftar PO, ringkasan qty, Laporan Variance, laporan operasional, pagar & form
kapasitas kirim, papan Kekurangan Kirim, fulfillment, dan cermin maklon membaca
fungsi ini. Pembaca DILARANG menjumlah `buyer_shipment_items` sendiri: koleksi itu
juga menyimpan DEKLARASI CMT→DA (`receiver_type='da'`), sehingga pembaca tanpa
saringan menggandakan "dikirim ke buyer" (audit w3 S1–S14: daftar PO 202 untuk
100 pcs). Saringan wajib ada di `buyer_dispatch_items()`.

Rumus (dokumen sumber, bukan buku inkremental):
    accepted_total = Σ qty_actual (penerimaan SELESAI QC) + Σ qty_reworked_ok (permak sendiri)
                     — PO internal tanpa penerimaan CMT: hasil produksi SENDIRI (job tanpa vendor)
    dispatched     = Σ qty dikirim efektif SJ BUYER saja
                     (qty_received bila sudah dicatat — tidak pernah melebihi qty_shipped)
    shippable      = max(0, accepted_total − dispatched)          ← pagar & form & papan
    produced_main  = Σ produced_qty job item NON-rework (job anak rework = kerja ulang barang
                     yang SAMA, bukan produksi baru)

Pagar kapasitas SELALU per po_item (keputusan 2026-11-02 butir 2): penerimaan yang
dicentang di form hanya JEJAK sumber barang, bukan batas. Dulu form yang hanya
mencentang penerimaan baru menjawab "sisa 0" sementara papan menjawab 45 (S5a).
PO internal: batas serah terima = qty LOLOS QC, bukan produced (S14: lolos 10,
produksi 11 termasuk job rework ⇒ maksimal 10).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

RECEIVER_BUYER = 'buyer'
RECEIVER_DA = 'da'
REWORK_JOB_TYPE = 'REWORK'
PERMAK_ACTIVE = ('open', 'in_progress')
PERMAK_TERMINAL = ('selesai_berhasil', 'gagal_buang')


def _i(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def line_key(po_item_id, sku) -> str:
    """Kunci penggabungan. `po_item_id` diutamakan karena satu SKU bisa muncul di
    beberapa PO pada surat jalan konsolidasi."""
    poi = (po_item_id or '').strip()
    if poi:
        return f"poi:{poi}"
    return f"sku:{(sku or '').strip()}"


# ─────────────────────────────────────────────────────────────────────────────
# SURAT JALAN BUYER (saringan wajib receiver_type) — 2026-11-02 K17
# ─────────────────────────────────────────────────────────────────────────────
def is_buyer_receiver(doc: dict | None) -> bool:
    """Dokumen lama tanpa receiver_type = surat jalan ke BUYER (backward compat)."""
    return ((doc or {}).get('receiver_type') or RECEIVER_BUYER) == RECEIVER_BUYER


def item_dispatched(it: dict) -> int:
    """Qty dikirim efektif satu baris SJ buyer: `qty_received` bila sudah dicatat
    (tidak pernah melebihi `qty_shipped`), selain itu `qty_shipped`."""
    shipped = _i(it.get('qty_shipped'))
    rcv = it.get('qty_received')
    return min(shipped, _i(rcv)) if rcv is not None else shipped


async def buyer_shipment_ids(db, candidate_ids) -> set:
    """Dari kumpulan id `buyer_shipments`, kembalikan yang benar-benar SJ DA→buyer."""
    ids = [s for s in set(candidate_ids or []) if s]
    out: set = set()
    if not ids:
        return out
    async for s in db.buyer_shipments.find(
            {'id': {'$in': ids}}, {'_id': 0, 'id': 1, 'receiver_type': 1}):
        if is_buyer_receiver(s):
            out.add(s['id'])
    return out


async def buyer_dispatch_items(db, *, po_item_ids=None, po_ids=None, shipment_ids=None,
                               skus=None) -> list:
    """Baris SJ DA→buyer SAJA. Deklarasi CMT→DA (`receiver_type='da'`) dibuang.

    Pilih salah satu cakupan: `po_item_ids`, `po_ids` (header ATAU baris), `shipment_ids`,
    atau `skus` (baris warisan tanpa po_item_id).
    """
    q: dict = {}
    if po_item_ids is not None:
        q['po_item_id'] = {'$in': [p for p in po_item_ids if p]}
    elif shipment_ids is not None:
        q['shipment_id'] = {'$in': [s for s in shipment_ids if s]}
    elif skus is not None:
        q = {'sku': {'$in': [s for s in skus if s]},
             '$or': [{'po_item_id': None}, {'po_item_id': ''}, {'po_item_id': {'$exists': False}}]}
    elif po_ids is not None:
        pids = [p for p in po_ids if p]
        head = set()
        async for s in db.buyer_shipments.find({'po_id': {'$in': pids}}, {'_id': 0, 'id': 1}):
            head.add(s['id'])
        q = {'$or': [{'po_id': {'$in': pids}}, {'shipment_id': {'$in': list(head)}}]}
    items = await db.buyer_shipment_items.find(q, {'_id': 0}).to_list(None)
    ok = await buyer_shipment_ids(db, [it.get('shipment_id') for it in items])
    return [it for it in items if it.get('shipment_id') in ok]


def shipment_progress(items: list) -> dict:
    """Progres SATU surat jalan dari angka nyata (status DIHITUNG, bukan disimpan basi).

    Dipakai daftar, detail, dan penulis `ship_status` supaya ketiganya sama.
    """
    per: dict = {}
    for it in items or []:
        key = it.get('po_item_id') or it.get('id')
        p = per.setdefault(key, {'ordered': _i(it.get('ordered_qty')), 'shipped': 0, 'received': 0})
        if not p['ordered']:
            p['ordered'] = _i(it.get('ordered_qty'))
        p['shipped'] += _i(it.get('qty_shipped'))
        p['received'] += item_dispatched(it)
    ordered = sum(p['ordered'] for p in per.values())
    shipped = sum(p['shipped'] for p in per.values())
    received = sum(p['received'] for p in per.values())
    if shipped <= 0:
        status = 'Pending'
    elif ordered > 0 and all(p['received'] >= p['ordered'] for p in per.values() if p['ordered']):
        status = 'Fully Shipped'
    else:
        status = 'Partially Shipped'
    return {
        'total_ordered': ordered, 'total_shipped': shipped, 'total_received': received,
        'remaining': max(0, ordered - received),
        'progress_pct': round(received / ordered * 100) if ordered > 0 else 0,
        'ship_status': status,
        'lines_unrecorded': sum(1 for it in (items or [])
                                if it.get('qty_received') is None and _i(it.get('qty_shipped')) > 0),
    }


async def refresh_shipment_status(db, shipment_id: str) -> dict:
    """Tulis ulang `ship_status` sebuah SJ dari angka nyatanya (dipanggil setiap mutasi)."""
    if not shipment_id:
        return {}
    items = await db.buyer_shipment_items.find({'shipment_id': shipment_id}, {'_id': 0}).to_list(None)
    prog = shipment_progress(items)
    from datetime import datetime, timezone
    await db.buyer_shipments.update_one({'id': shipment_id}, {'$set': {
        'ship_status': prog['ship_status'], 'progress_pct': prog['progress_pct'],
        'updated_at': datetime.now(timezone.utc)}})
    return prog


# ─────────────────────────────────────────────────────────────────────────────
# SSOT ANGKA QTY PER ITEM PO (K17)
# ─────────────────────────────────────────────────────────────────────────────
_QTY_FIELDS = (
    'ordered', 'produced_main', 'rework_produced', 'self_made_produced',
    'good_from_cmt', 'reworked_ok', 'accepted_total', 'accepted_initial',
    'reject', 'repaired', 'repaired_da', 'repaired_cmt', 'scrap', 'reject_open',
    'rework_open_da', 'rework_open_cmt', 'reject_undecided',
    'claimed', 'arrived', 'arrived_fresh', 'in_qc', 'cmt_short_open',
    'shipped', 'dispatched', 'received_confirmed', 'pending_receipt', 'lines_unrecorded',
    'buyer_short_open', 'buyer_short_resolved', 'shippable', 'over_dispatched', 'remaining_vs_order',
)


def _blank_qty(po_item_id: str) -> dict:
    d = {f: 0 for f in _QTY_FIELDS}
    d.update({'po_item_id': po_item_id, 'po_id': '', 'po_number': '', 'business_type': '',
              'sku': '', 'product_name': '', 'size': '', 'color': '', 'serial_number': '',
              'buyer': '', 'source': 'cmt', 'has_receipts': False, 'receipt_ids': [],
              'ledger': {f: 0 for f in ('produced_main', 'declared', 'accepted', 'reject',
                                        'rework_open', 'repaired', 'repaired_cmt', 'scrap',
                                        'claimed_by_vendor', 'short_open')},
              'ledger_negative': []})
    return d


async def _job_kinds(db, job_ids) -> dict:
    """job_id → {'rework': bool, 'vendor': bool}. Job anak REWORK = kerja ulang barang reject."""
    out: dict = {}
    ids = [j for j in set(job_ids or []) if j]
    if not ids:
        return out
    async for j in db.production_jobs.find(
            {'id': {'$in': ids}},
            {'_id': 0, 'id': 1, 'shipment_type': 1, 'vendor_id': 1, 'vendor_shipment_id': 1}):
        out[j['id']] = {'rework': (j.get('shipment_type') or '').upper() == REWORK_JOB_TYPE,
                        'vendor': bool(j.get('vendor_id') or j.get('vendor_shipment_id'))}
    return out


def is_rework_job(job: dict | None) -> bool:
    return ((job or {}).get('shipment_type') or '').upper() == REWORK_JOB_TYPE


async def po_item_quantities(db, po_item_ids) -> dict:
    """SATU sumber angka qty per item PO — {po_item_id: {...}} (lihat docstring modul)."""
    from core.cmt_receipt_status import is_done as _done, canon_status, ST_CANCELLED
    ids = list(dict.fromkeys(p for p in (po_item_ids or []) if p))
    if not ids:
        return {}
    out = {pid: _blank_qty(pid) for pid in ids}

    poi_docs = await db.po_items.find({'id': {'$in': ids}}, {'_id': 0}).to_list(None)
    po_ids = list({d.get('po_id') for d in poi_docs if d.get('po_id')})
    po_meta: dict = {}
    if po_ids:
        async for p in db.production_pos.find(
                {'id': {'$in': po_ids}},
                {'_id': 0, 'id': 1, 'po_number': 1, 'customer_name': 1, 'business_type': 1}):
            po_meta[p['id']] = p
    for d in poi_docs:
        r = out.get(d['id'])
        if not r:
            continue
        meta = po_meta.get(d.get('po_id')) or {}
        r.update({'ordered': _i(d.get('qty')), 'po_id': d.get('po_id') or '',
                  'po_number': meta.get('po_number') or d.get('po_number') or '',
                  'business_type': meta.get('business_type') or 'internal',
                  'buyer': meta.get('customer_name') or '',
                  'serial_number': d.get('serial_number') or ''})
        for f in ('sku', 'product_name', 'size', 'color'):
            r[f] = d.get(f) or ''

    # ── produksi (job item) — job anak REWORK dipisah ──
    jis = await db.production_job_items.find({'po_item_id': {'$in': ids}}, {'_id': 0}).to_list(None)
    kinds = await _job_kinds(db, [ji.get('job_id') for ji in jis])
    for ji in jis:
        r = out.get(ji.get('po_item_id'))
        if not r:
            continue
        k = kinds.get(ji.get('job_id')) or {'rework': False, 'vendor': False}
        prod = _i(ji.get('produced_qty'))
        if k['rework']:
            r['rework_produced'] += prod
        else:
            r['produced_main'] += prod
            r['ledger']['produced_main'] += prod
            if not k['vendor']:
                r['self_made_produced'] += prod
        for fld, key in (('qty_declared', 'declared'), ('qty_accepted', 'accepted'),
                         ('qty_reject', 'reject'), ('qty_rework_open', 'rework_open'),
                         ('qty_repaired', 'repaired'), ('qty_repaired_cmt', 'repaired_cmt'),
                         ('qty_scrap', 'scrap'), ('qty_claimed_by_vendor', 'claimed_by_vendor'),
                         ('qty_short_open', 'short_open')):
            v = _i(ji.get(fld))
            r['ledger'][key] += v
            if v < 0:
                r['ledger_negative'].append({'job_item_id': ji.get('id'), 'field': fld, 'value': v})

    # ── penerimaan CMT (hanya yang SELESAI QC = lolos QC; yang sedang QC = in_qc) ──
    lines = await db.cmt_receipt_lines.find({'po_item_id': {'$in': ids}}, {'_id': 0}).to_list(None)
    rec_ids = list({ln.get('receipt_id') for ln in lines if ln.get('receipt_id')})
    rstat: dict = {}
    if rec_ids:
        async for rc in db.cmt_receipts.find({'id': {'$in': rec_ids}}, {'_id': 0, 'id': 1, 'status': 1}):
            rstat[rc['id']] = rc.get('status')
    for ln in lines:
        r = out.get(ln.get('po_item_id'))
        if not r:
            continue
        st = rstat.get(ln.get('receipt_id'))
        claim = (_i(ln.get('qty_claimed_by_cmt')) or _i(ln.get('qty_shipped_by_cmt'))
                 or (_i(ln.get('qty_actual')) + _i(ln.get('reject_qty'))))
        if _done(st):
            r['has_receipts'] = True
            r['good_from_cmt'] += _i(ln.get('qty_actual'))
            r['reject'] += _i(ln.get('reject_qty'))
            r['reworked_ok'] += _i(ln.get('qty_reworked_ok'))
            r['claimed'] += claim
            if ln.get('receipt_id') and ln['receipt_id'] not in r['receipt_ids']:
                r['receipt_ids'].append(ln['receipt_id'])
        elif st is not None and canon_status(st) != ST_CANCELLED:
            r['in_qc'] += claim

    # ── permak: reject = belum diputuskan + permak terbuka (DA/CMT) + diperbaiki + scrap ──
    permaked: dict = {}
    scrap_da: dict = {}
    async for p in db.dewi_cmt_permak.find({'po_item_id': {'$in': ids}}, {'_id': 0}):
        r = out.get(p.get('po_item_id'))
        if not r or (p.get('source') or 'reject') != 'reject':
            continue
        qty = _i(p.get('qty'))
        st = str(p.get('status') or '')
        is_cmt = p.get('permak_type') == 'retur_ke_cmt'
        permaked[r['po_item_id']] = permaked.get(r['po_item_id'], 0) + qty
        if st in PERMAK_ACTIVE:
            r['rework_open_cmt' if is_cmt else 'rework_open_da'] += qty
        elif st in PERMAK_TERMINAL:
            qf, qs = _i(p.get('qty_fixed')), _i(p.get('qty_scrap'))
            if is_cmt:
                r['repaired_cmt'] += qf
                r['scrap'] += qs
            else:
                r['repaired_da'] += qf
                scrap_da[r['po_item_id']] = scrap_da.get(r['po_item_id'], 0) + qs
                r['scrap'] += qs

    # ── selisih kirim CMT→DA terbuka ──
    async for s in db.cmt_short_shipments.find({'po_item_id': {'$in': ids}, 'status': 'open'}, {'_id': 0}):
        r = out.get(s.get('po_item_id'))
        if r:
            r['cmt_short_open'] += max(0, _i(s.get('qty_short')) - _i(s.get('qty_resolved')))

    # ── surat jalan BUYER saja ──
    for it in await buyer_dispatch_items(db, po_item_ids=ids):
        r = out.get(it.get('po_item_id'))
        if not r:
            continue
        shipped = _i(it.get('qty_shipped'))
        r['shipped'] += shipped
        r['dispatched'] += item_dispatched(it)
        if it.get('qty_received') is None:
            r['pending_receipt'] += shipped
            if shipped > 0:
                r['lines_unrecorded'] += 1
        else:
            r['received_confirmed'] += min(shipped, _i(it.get('qty_received')))

    async for b in db.buyer_short_records.find({'po_item_id': {'$in': ids}}, {'_id': 0}):
        r = out.get(b.get('po_item_id'))
        if not r:
            continue
        if b.get('status') == 'open':
            r['buyer_short_open'] += max(0, _i(b.get('qty_short')) - _i(b.get('qty_resolved')))
        if b.get('status') != 'cancelled':
            r['buyer_short_resolved'] += _i(b.get('qty_resolved'))

    for pid, r in out.items():
        # hasil permak sendiri sudah tercatat di baris penerimaan (`qty_reworked_ok`)
        r['repaired_da'] = max(r['repaired_da'], r['reworked_ok'])
        r['repaired'] = r['repaired_da'] + r['repaired_cmt']
        r['reject_undecided'] = max(0, r['reject'] - permaked.get(pid, 0))
        r['reject_open'] = max(0, r['reject'] - r['repaired'] - r['scrap'])
        r['arrived'] = r['good_from_cmt'] + r['reject']
        # barang hasil retur-ke-CMT kembali lewat penerimaan biasa → bukan barang "baru"
        r['accepted_initial'] = max(0, r['good_from_cmt'] - r['repaired_cmt'])
        r['arrived_fresh'] = max(0, r['arrived'] - r['repaired_cmt'])
        if r['has_receipts']:
            r['source'] = 'cmt'
            r['accepted_total'] = r['good_from_cmt'] + r['reworked_ok']
        elif r['business_type'] == 'internal':
            # PO internal yang dijahit SENDIRI (job tanpa vendor): hasil produksi = barang jadi.
            # Job CMT tanpa penerimaan = barang masih di vendor ⇒ belum boleh diserahkan.
            r['source'] = 'internal'
            r['accepted_total'] = r['self_made_produced']
        r['shippable'] = max(0, r['accepted_total'] - r['dispatched'])
        r['over_dispatched'] = max(0, r['dispatched'] - r['accepted_total'])
        r['remaining_vs_order'] = max(0, r['ordered'] - r['dispatched']) if r['ordered'] else 0
    return out


def sum_quantities(rows) -> dict:
    """Total beberapa item (mis. satu PO) — tanpa rumus kedua."""
    tot = {f: 0 for f in _QTY_FIELDS}
    for r in rows or []:
        for f in _QTY_FIELDS:
            tot[f] += _i(r.get(f))
    return tot


async def po_quantities(db, po_ids) -> dict:
    """{po_id: {'totals': {...}, 'items': {po_item_id: {...}}, 'ship_status': ...}}."""
    pids = [p for p in set(po_ids or []) if p]
    if not pids:
        return {}
    poi = await db.po_items.find({'po_id': {'$in': pids}}, {'_id': 0, 'id': 1, 'po_id': 1}).to_list(None)
    q = await po_item_quantities(db, [d['id'] for d in poi])
    out = {p: {'items': {}, 'totals': sum_quantities([])} for p in pids}
    for d in poi:
        if d['id'] in q:
            out[d['po_id']]['items'][d['id']] = q[d['id']]
    for p, v in out.items():
        v['totals'] = sum_quantities(v['items'].values())
        v['ship_status'] = po_ship_status(v['totals'])
    return out


def po_ship_status(t: dict) -> str:
    """Status kirim PO dihitung dari angka nyata (bukan disimpan)."""
    if _i(t.get('dispatched')) <= 0:
        return 'Belum Dikirim'
    if _i(t.get('ordered')) > 0 and _i(t.get('dispatched')) >= _i(t.get('ordered')):
        return 'Fully Shipped'
    return 'Partially Shipped'


# ─────────────────────────────────────────────────────────────────────────────
# BARIS KAPASITAS (form, pagar, papan) — dibangun dari SSOT di atas
# ─────────────────────────────────────────────────────────────────────────────
def _row_from_qty(q: dict) -> dict:
    return {
        'key': line_key(q['po_item_id'], ''), 'po_item_id': q['po_item_id'],
        'sku': q['sku'], 'product_name': q['product_name'], 'size': q['size'], 'color': q['color'],
        'serial_number': q['serial_number'], 'po_id': q['po_id'], 'po_number': q['po_number'],
        'buyer': q['buyer'], 'business_type': q['business_type'] or 'internal',
        'ordered': q['ordered'],
        'good_from_cmt': q['good_from_cmt'],
        'reject_open': q['reject_open'],
        'reworked_ok': q['reworked_ok'],
        # angka yang dipakai PO internal yang dijahit sendiri (tanpa penerimaan CMT)
        'internal_produced': q['self_made_produced'] if q['source'] == 'internal' else 0,
        'produced_main': q['produced_main'],
        'accepted_total': q['accepted_total'],
        'source': q['source'],
        'dispatched': q['dispatched'],
        'received_confirmed': q['received_confirmed'],
        'buyer_short_open': q['buyer_short_open'],
        'shippable': q['shippable'],
        'remaining_vs_order': q['remaining_vs_order'],
        'fg_stock': None,
        'receipt_ids': list(q['receipt_ids']),
    }


async def _legacy_sku_rows(db, query: dict) -> dict:
    """Baris warisan TANPA po_item_id (kunci SKU) — rumusnya sama, cakupannya SKU."""
    from core.cmt_receipt_status import is_done as _done
    rows: dict = {}
    lines = await db.cmt_receipt_lines.find(query, {'_id': 0}).to_list(None)
    lines = [ln for ln in lines if not (ln.get('po_item_id') or '').strip()]
    if not lines:
        return rows
    rec_ids = list({ln.get('receipt_id') for ln in lines if ln.get('receipt_id')})
    done = set()
    async for rc in db.cmt_receipts.find({'id': {'$in': rec_ids}}, {'_id': 0, 'id': 1, 'status': 1}):
        if _done(rc.get('status')):
            done.add(rc['id'])
    for ln in lines:
        if ln.get('receipt_id') not in done:
            continue
        k = line_key('', ln.get('sku_code'))
        r = rows.setdefault(k, {'key': k, 'po_item_id': '', 'sku': ln.get('sku_code') or '',
                                'product_name': '', 'size': '', 'color': '', 'serial_number': '',
                                'po_id': '', 'po_number': '', 'buyer': '', 'business_type': '',
                                'ordered': 0, 'good_from_cmt': 0, 'reject_open': 0, 'reworked_ok': 0,
                                'internal_produced': 0, 'produced_main': 0, 'accepted_total': 0,
                                'source': 'cmt', 'dispatched': 0, 'received_confirmed': 0,
                                'buyer_short_open': 0, 'shippable': 0, 'remaining_vs_order': 0,
                                'fg_stock': None, 'receipt_ids': []})
        r['good_from_cmt'] += _i(ln.get('qty_actual'))
        r['reworked_ok'] += _i(ln.get('qty_reworked_ok'))
        r['reject_open'] += max(0, _i(ln.get('reject_qty')) - _i(ln.get('qty_reworked_ok'))
                                - _i(ln.get('qty_reject_scrapped')))
        for src in ('product_name', 'size', 'color'):
            if not r[src] and ln.get(src):
                r[src] = ln[src]
        if ln.get('receipt_id') and ln['receipt_id'] not in r['receipt_ids']:
            r['receipt_ids'].append(ln['receipt_id'])
    skus = [r['sku'] for r in rows.values() if r['sku']]
    for it in await buyer_dispatch_items(db, skus=skus):
        r = rows.get(line_key('', it.get('sku')))
        if r:
            r['dispatched'] += item_dispatched(it)
            if not r['ordered']:
                r['ordered'] = _i(it.get('ordered_qty'))
    for r in rows.values():
        r['accepted_total'] = r['good_from_cmt'] + r['reworked_ok']
        r['shippable'] = max(0, r['accepted_total'] - r['dispatched'])
        r['remaining_vs_order'] = max(0, r['ordered'] - r['dispatched']) if r['ordered'] else 0
    return rows


async def _rows_for_po_items(db, po_item_ids) -> dict:
    q = await po_item_quantities(db, po_item_ids)
    return {line_key(pid, ''): _row_from_qty(v) for pid, v in q.items()}


async def _enrich_fg_stock(db, rows: dict) -> None:
    """Stok FG per SKU (informasi dini; pagar keras tetap di precheck dispatch)."""
    skus = list({r['sku'] for r in rows.values() if r.get('sku')})
    if not skus:
        return
    try:
        from core import production_qty_ledger as qled
        from core import stock_service
        from core import quarantine as qmod
    except Exception:  # noqa: BLE001
        return
    try:
        qloc = await qmod.get_quarantine_location_id(db)
    except Exception:  # noqa: BLE001
        qloc = None
    cache: dict = {}
    for sku in skus:
        try:
            mat = await qled.resolve_fg_material(db, sku=sku)
            if not mat:
                cache[sku] = None
                continue
            have = 0.0
            for row in await stock_service.list_rows(mat['id'], db=db):
                if qloc and row.get('location_id') == qloc:
                    continue
                try:
                    have += float(row.get('qty') or row.get('quantity') or 0)
                except (TypeError, ValueError):
                    continue
            cache[sku] = have
        except Exception:  # noqa: BLE001
            logger.exception('kapasitas kirim: gagal membaca stok FG %s', sku)
            cache[sku] = None
    for r in rows.values():
        if r.get('sku') in cache:
            r['fg_stock'] = cache[r['sku']]


def _finalize(rows: dict) -> list:
    out = list(rows.values())
    out.sort(key=lambda x: (x.get('po_number') or '', x.get('sku') or ''))
    return out


async def _po_items_of_receipts(db, receipt_ids: list) -> list:
    lines = await db.cmt_receipt_lines.find(
        {'receipt_id': {'$in': list(receipt_ids or [])}}, {'_id': 0, 'po_item_id': 1}).to_list(None)
    return list(dict.fromkeys(ln['po_item_id'] for ln in lines if (ln.get('po_item_id') or '').strip()))


async def by_receipts(db, receipt_ids: list, *, with_fg_stock: bool = False) -> list:
    """Kapasitas kirim untuk kumpulan `cmt_receipts` yang dipilih di form dispatch.

    2026-11-02 (butir 2): penerimaan terpilih hanya menentukan ITEM mana yang tampil;
    angkanya dihitung per po_item (semua penerimaan selesai QC − semua SJ buyer).
    """
    ids = [r for r in (receipt_ids or []) if r]
    if not ids:
        return []
    rows = await _rows_for_po_items(db, await _po_items_of_receipts(db, ids))
    rows.update(await _legacy_sku_rows(db, {'receipt_id': {'$in': ids}}))
    if with_fg_stock:
        await _enrich_fg_stock(db, rows)
    return _finalize(rows)


async def by_po_items(db, po_item_ids: list, *, with_fg_stock: bool = False) -> list:
    """Kapasitas kirim untuk daftar po_item (dipakai pagar backend & papan)."""
    ids = [p for p in (po_item_ids or []) if p]
    if not ids:
        return []
    rows = await _rows_for_po_items(db, ids)
    if with_fg_stock:
        await _enrich_fg_stock(db, rows)
    return _finalize(rows)


async def map_for_validation(db, *, receipt_ids: list, items_data: list) -> dict:
    """Peta kunci → baris kapasitas untuk pagar `POST /api/buyer-shipments` (per po_item)."""
    pois = [it.get('po_item_id') for it in (items_data or []) if it.get('po_item_id')]
    pois += await _po_items_of_receipts(db, receipt_ids or [])
    rows = await _rows_for_po_items(db, pois)
    if receipt_ids:
        rows.update(await _legacy_sku_rows(db, {'receipt_id': {'$in': list(receipt_ids)}}))
    return rows


async def outstanding(db, *, buyer: str = '', po_id: str = '',
                      include_settled: bool = False) -> list:
    """DAFTAR KEKURANGAN KIRIM — semua item yang masih punya sisa kirim ke buyer.

    Sumber item SENGAJA gabungan: penerimaan CMT, SJ buyer yang sudah ada (termasuk
    warisan), dan item PO internal yang sudah berproduksi. Angkanya dari SSOT.
    """
    pois: set = set()
    lq = {'po_item_id': {'$nin': [None, '']}}
    async for ln in db.cmt_receipt_lines.find(lq, {'_id': 0, 'po_item_id': 1}):
        pois.add(ln['po_item_id'])
    ship_ids = set()
    async for s in db.buyer_shipments.find({}, {'_id': 0, 'id': 1, 'receiver_type': 1}):
        if is_buyer_receiver(s):
            ship_ids.add(s['id'])
    legacy_skus = set()
    if ship_ids:
        async for it in db.buyer_shipment_items.find(
                {'shipment_id': {'$in': list(ship_ids)}}, {'_id': 0, 'po_item_id': 1, 'sku': 1}):
            if it.get('po_item_id'):
                pois.add(it['po_item_id'])
            elif it.get('sku'):
                legacy_skus.add(it['sku'])
    iq = {'business_type': 'internal'}
    if po_id:
        iq['id'] = po_id
    internal_pos = [p['id'] async for p in db.production_pos.find(iq, {'_id': 0, 'id': 1})]
    if internal_pos:
        async for d in db.po_items.find({'po_id': {'$in': internal_pos}}, {'_id': 0, 'id': 1}):
            pois.add(d['id'])
    if po_id:
        allowed = {d['id'] async for d in db.po_items.find({'po_id': po_id}, {'_id': 0, 'id': 1})}
        pois &= allowed
    rows = await _rows_for_po_items(db, list(pois))
    # item internal yang belum menghasilkan apa pun tidak masuk papan
    rows = {k: r for k, r in rows.items()
            if r['accepted_total'] > 0 or r['dispatched'] > 0 or r['good_from_cmt'] > 0
            or r['source'] != 'internal'}
    if not po_id and legacy_skus:
        rows.update(await _legacy_sku_rows(db, {}))
    await _enrich_fg_stock(db, rows)
    result = _finalize(rows)
    if buyer:
        b = buyer.strip().lower()
        result = [r for r in result if (r.get('buyer') or '').strip().lower() == b]
    if po_id:
        result = [r for r in result if r.get('po_id') == po_id]
    if not include_settled:
        result = [r for r in result
                  if r['shippable'] > 0 or r.get('remaining_vs_order', 0) > 0]
    return result


# ─────────────────────────────────────────────────────────────────────────────
# INVARIAN OTOMATIS INV-Q1..Q5 (audit w3 §6) — 2026-11-02 butir 11
# ─────────────────────────────────────────────────────────────────────────────
def evaluate_invariants(q: dict, buyer_lines: list | None = None, buyer_shorts: list | None = None) -> dict:
    """Periksa satu item PO (fungsi murni). `q` = hasil `po_item_quantities`.

    INV-Q1 produksi: produced_main ≥ yang sampai (baru) + selisih CMT terbuka, dan buku
           kuantitas (job item) = dokumen (deklarasi bersih rework, lolos QC).
    INV-Q2 reject   : reject = belum diputuskan + permak terbuka DA + permak terbuka CMT +
           diperbaiki + scrap — di dokumen DAN di buku kuantitas; tidak ada field negatif.
    INV-Q3 kirim    : dikirim ≤ lolos QC total (shippable ≥ 0) dan diterima ≤ dikirim.
    INV-Q4 per baris: qty_received ≤ qty_shipped; Σ(klaim − dikirim) = selisih buyer
           (terbuka + selesai).
    INV-Q5 neraca   : produced_main = dikirim + sisa bisa kirim + reject terbuka + scrap +
           sedang QC + belum dideklarasi + selisih CMT terbuka (− lebih produksi).
    """
    led = q.get('ledger') or {}
    res: dict = {}

    undeclared = max(0, q['produced_main'] - q['arrived_fresh'] - q['cmt_short_open'] - q['in_qc'])
    declared_main = led.get('declared', 0) - led.get('repaired_cmt', 0)
    q1_msgs = []
    if q['produced_main'] and q['arrived_fresh'] + q['cmt_short_open'] > q['produced_main']:
        q1_msgs.append(f"sampai {q['arrived_fresh']} + selisih CMT {q['cmt_short_open']} > produksi "
                       f"{q['produced_main']}")
    if q['has_receipts'] and declared_main != q['arrived_fresh']:
        q1_msgs.append(f"buku kuantitas deklarasi {declared_main} ≠ dokumen {q['arrived_fresh']}")
    if q['has_receipts'] and led.get('accepted', 0) != q['accepted_total']:
        q1_msgs.append(f"buku kuantitas lolos {led.get('accepted', 0)} ≠ dokumen {q['accepted_total']}")
    res['INV-Q1'] = {'ok': not q1_msgs, 'detail': q1_msgs,
                     'nilai': {'produced_main': q['produced_main'], 'accepted_initial': q['accepted_initial'],
                               'reject': q['reject'], 'belum_dideklarasi': undeclared,
                               'in_qc': q['in_qc'], 'cmt_short_open': q['cmt_short_open']}}

    q2_msgs = []
    doc_sum = (q['reject_undecided'] + q['rework_open_da'] + q['rework_open_cmt']
               + q['repaired'] + q['scrap'])
    if q['reject'] != doc_sum:
        q2_msgs.append(f"dokumen: reject {q['reject']} ≠ {q['reject_undecided']}+{q['rework_open_da']}+"
                       f"{q['rework_open_cmt']}+{q['repaired']}+{q['scrap']}")
    led_rep = led.get('repaired', 0) + led.get('repaired_cmt', 0)
    if q['has_receipts']:
        if led.get('reject', 0) != q['reject']:
            q2_msgs.append(f"buku kuantitas reject {led.get('reject', 0)} ≠ dokumen {q['reject']}")
        if led_rep != q['repaired']:
            q2_msgs.append(f"buku kuantitas diperbaiki {led_rep} ≠ dokumen {q['repaired']}")
        if led.get('scrap', 0) != q['scrap']:
            q2_msgs.append(f"buku kuantitas scrap {led.get('scrap', 0)} ≠ dokumen {q['scrap']}")
        if led.get('rework_open', 0) != q['reject_open']:
            q2_msgs.append(f"buku kuantitas permak terbuka {led.get('rework_open', 0)} ≠ dokumen {q['reject_open']}")
    for neg in q.get('ledger_negative') or []:
        q2_msgs.append(f"field {neg['field']} negatif ({neg['value']}) di job item {neg['job_item_id']}")
    res['INV-Q2'] = {'ok': not q2_msgs, 'detail': q2_msgs,
                     'nilai': {'reject': q['reject'], 'belum_diputuskan': q['reject_undecided'],
                               'permak_terbuka_da': q['rework_open_da'],
                               'permak_terbuka_cmt': q['rework_open_cmt'],
                               'diperbaiki': q['repaired'], 'scrap': q['scrap']}}

    q3_msgs = []
    if q['dispatched'] > q['accepted_total']:
        q3_msgs.append(f"dikirim {q['dispatched']} > lolos QC {q['accepted_total']}")
    if q['received_confirmed'] > q['dispatched']:
        q3_msgs.append(f"diterima {q['received_confirmed']} > dikirim {q['dispatched']}")
    res['INV-Q3'] = {'ok': not q3_msgs, 'detail': q3_msgs,
                     'nilai': {'accepted_total': q['accepted_total'], 'dispatched': q['dispatched'],
                               'shippable': q['shippable']}}

    q4_msgs = []
    gap = 0
    for it in buyer_lines or []:
        if it.get('qty_received') is not None and _i(it['qty_received']) > _i(it.get('qty_shipped')):
            q4_msgs.append(f"baris {it.get('id')}: diterima {_i(it['qty_received'])} > dikirim "
                           f"{_i(it.get('qty_shipped'))}")
        claimed = _i(it.get('qty_shipped_claimed')) or _i(it.get('qty_shipped'))
        gap += max(0, claimed - _i(it.get('qty_shipped')))
    short_sum = sum(max(0, _i(s.get('qty_short')) - _i(s.get('qty_resolved'))) + _i(s.get('qty_resolved'))
                    for s in (buyer_shorts or []) if s.get('status') != 'cancelled')
    if buyer_lines is not None and gap != short_sum:
        q4_msgs.append(f"Σ(klaim − dikirim) {gap} ≠ selisih buyer {short_sum}")
    res['INV-Q4'] = {'ok': not q4_msgs, 'detail': q4_msgs, 'nilai': {'gap': gap, 'short': short_sum}}

    balance = (q['dispatched'] + q['shippable'] + q['reject_open'] + q['scrap'] + q['in_qc']
               + undeclared + q['cmt_short_open'])
    over_prod = max(0, q['produced_main'] - q['ordered'])
    q5_msgs = []
    if q['has_receipts'] and q['produced_main'] and balance != q['produced_main']:
        q5_msgs.append(f"produksi {q['produced_main']} ≠ dikirim {q['dispatched']} + sisa {q['shippable']} + "
                       f"reject terbuka {q['reject_open']} + scrap {q['scrap']} + QC {q['in_qc']} + "
                       f"belum dideklarasi {undeclared} + selisih CMT {q['cmt_short_open']} = {balance}")
    res['INV-Q5'] = {'ok': not q5_msgs, 'detail': q5_msgs,
                     'nilai': {'ordered': q['ordered'], 'produced_main': q['produced_main'],
                               'balance': balance, 'lebih_produksi': over_prod}}
    return res


async def check_invariants(db, *, po_id: str = '', po_item_ids: list | None = None) -> dict:
    """Jalankan INV-Q1..Q5 untuk satu PO / daftar item (dipakai endpoint diagnosa)."""
    ids = list(po_item_ids or [])
    if po_id:
        ids += [d['id'] async for d in db.po_items.find({'po_id': po_id}, {'_id': 0, 'id': 1})]
    q = await po_item_quantities(db, ids)
    lines = await buyer_dispatch_items(db, po_item_ids=list(q.keys()))
    by_item: dict = {}
    for it in lines:
        by_item.setdefault(it.get('po_item_id'), []).append(it)
    shorts: dict = {}
    async for s in db.buyer_short_records.find({'po_item_id': {'$in': list(q.keys())}}, {'_id': 0}):
        shorts.setdefault(s.get('po_item_id'), []).append(s)
    items = []
    for pid, v in q.items():
        inv = evaluate_invariants(v, by_item.get(pid, []), shorts.get(pid, []))
        items.append({'po_item_id': pid, 'po_number': v['po_number'], 'sku': v['sku'],
                      'ok': all(x['ok'] for x in inv.values()), 'invariants': inv,
                      'quantities': {k: v[k] for k in _QTY_FIELDS}})
    return {'ok': all(i['ok'] for i in items), 'items': items,
            'failed': [{'po_item_id': i['po_item_id'], 'sku': i['sku'],
                        'gagal': [k for k, x in i['invariants'].items() if not x['ok']]}
                       for i in items if not i['ok']]}
