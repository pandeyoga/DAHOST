"""core.posisi_cmt — POSISI hutang per CMT + BAYAR GABUNGAN satu CMT (16 Nov 2026, owner).

Owner: "berapa pencairannya" — yang boleh dibayar ke CMT hanya yang sudah disetor dan lolos QC; nilai PO tetap
terlihat sebagai komitmen. Tiap CMT dibayar terpisah (tidak pernah satu pembayaran lintas CMT), tetapi SATU
pembayaran ke satu CMT boleh menutup beberapa PO / tagihannya.

Angka (satu hitungan, tanpa rumus kedua):
  * komitmen per (PO, CMT) = qty × upah CMT — `maklon_ledger.ap_schedule_rows` (PO maklon: jadwal tersimpan di
    `dewi_cmt_ap_schedules`; PO DA: `maklon_ledger.perkiraan_internal`, dihitung saat dibaca, termasuk PO yang
    sudah ditutup tetapi tagihannya masih terbuka);
  * setor lolos QC / dibayar / ditahan / boleh dibayar = tagihan `dewi_cmt_payments` yang hidup lewat
    `maklon_ledger._bill_amount`, `cmt_bill_blocked`, `cmt_bill_payable` (sama dengan gerbang tombol Bayar).
Jurnal tidak berubah: hutang CMT tetap lahir saat setoran lolos QC; komitmen tidak dijurnal.

Bayar gabungan: pembagian (bawaan terlama dulu, `core.alokasi_bayar`) → semua tagihan dikunci → tiap baris dibayar
lewat logika bayar tagihan yang SAMA (`routes.dewi_maklon_finance.pay_cmt_bill_locked`) dengan satu nomor bukti
(`dewi_pembayaran_gabungan`) dicap ke setiap pembayaran. Gagal di tengah → pembayaran yang sudah tercatat dibatalkan
kembali (jurnal di-void) dan bukti ditandai gagal, jadi tidak ada bukti setengah jadi.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from core import alokasi_bayar as ab
from core import maklon_ledger as ml

logger = logging.getLogger(__name__)

_MATI = ('cancelled', 'void', 'voided')


def _now():
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _r2(v) -> float:
    return round(_f(v), 2)


def tanggal_tagihan(b: dict) -> str:
    """Tanggal acuan tagihan CMT (urutan terlama dulu): tanggal tagihan → akhir periode → tanggal dibuat."""
    from utils.waktu import wib_date_of
    for k in ('invoice_date', 'period_to', 'issue_date', 'period_end'):
        if b.get(k):
            return str(b[k])[:10]
    return wib_date_of(b.get('created_at')) or ''


def entitas_tagihan(b: dict, business_type: str | None) -> str:
    """CV tagihan CMT — aturan yang sama dengan `production_cmt_billing.bill_entity` / `cmt_bill_entity`."""
    from core.entities import DA, SMU
    if b.get('entity') in (DA, SMU):
        return b['entity']
    return SMU if business_type == 'maklon' else DA


def baris_tagihan(b: dict, vendor_id: str, entity: str) -> dict:
    """Murni: satu tagihan CMT untuk posisi & formulir bayar gabungan."""
    nilai = _r2(ml._bill_amount(b))
    dibayar = _r2(b.get('paid_amount'))
    return {'id': b['id'], 'nomor': b.get('payment_code') or b.get('payment_number') or b['id'][:8],
            'po_id': b.get('po_id') or '', 'po_number': b.get('po_number') or '', 'tanggal': tanggal_tagihan(b),
            'vendor_id': vendor_id, 'vendor_name': b.get('cmt_name') or '', 'entity': entity,
            'antar_cv': bool(b.get('intercompany')), 'nilai': nilai, 'dibayar': dibayar,
            'ditahan': ml.cmt_bill_blocked(b), 'boleh_dibayar': ml.cmt_bill_payable(b),
            'sisa': _r2(max(0.0, nilai - dibayar)), 'pcs': int(_f(b.get('total_pcs'))),
            'status': str(b.get('status') or '').lower(), 'terjurnal': bool(b.get('gl_je_id'))}


def susun_posisi(jadwal: list, tagihan: list, pos: dict, master: dict) -> list:
    """Murni: baris posisi per (PO, CMT) dari komitmen (`jadwal` = baris `ap_schedule_rows`) + tagihan hidup.

    `tagihan` = hasil `baris_tagihan`; `pos` = {po_id: PO}; `master` = {vendor_id: nama}. → daftar CMT, tiap CMT
    membawa baris per PO, tagihan terbuka (terlama dulu), dan jumlahnya."""
    from core.entities import DA, SMU
    rows: dict = {}
    for s in jadwal:
        key = (s.get('po_id') or '', s.get('vendor_id') or '')
        po = pos.get(key[0]) or {}
        bt = s.get('business_type') or ('maklon' if po.get('business_type') == 'maklon' else 'internal')
        rows[key] = {'po_id': key[0], 'po_number': s.get('po_number') or po.get('po_number') or '',
                     'vendor_id': key[1], 'vendor_name': s.get('vendor_name') or '', 'business_type': bt,
                     'entity': SMU if bt == 'maklon' else DA, 'jenis': s.get('jenis') or 'jadwal',
                     'komitmen': _r2(s.get('scheduled_amount')), 'qty_komitmen': int(_f(s.get('scheduled_qty'))),
                     'po_status': po.get('status') or s.get('po_status') or ''}
    per_baris: dict = {}
    for t in tagihan:
        per_baris.setdefault((t['po_id'], t['vendor_id']), []).append(t)
    for key, tl in per_baris.items():
        r = rows.get(key)
        if r is None:
            po = pos.get(key[0]) or {}
            r = rows[key] = {'po_id': key[0], 'po_number': tl[0]['po_number'] or po.get('po_number') or '',
                             'vendor_id': key[1], 'vendor_name': tl[0]['vendor_name'],
                             'business_type': 'maklon' if tl[0]['entity'] == SMU else 'internal',
                             'entity': tl[0]['entity'], 'jenis': 'tagihan', 'komitmen': 0.0, 'qty_komitmen': 0,
                             'po_status': po.get('status') or ''}
        r['tagihan_ids'] = [t['id'] for t in tl]
    out: dict = {}
    for key, r in rows.items():
        tl = per_baris.get(key) or []
        r['setor_qc'] = _r2(sum(t['nilai'] for t in tl))
        r['pcs_setor'] = sum(t['pcs'] for t in tl)
        r['dibayar'] = _r2(sum(t['dibayar'] for t in tl))
        r['ditahan'] = _r2(sum(t['ditahan'] for t in tl))
        r['boleh_dibayar'] = _r2(sum(t['boleh_dibayar'] for t in tl))
        r['belum_setor'] = _r2(max(0.0, r['komitmen'] - r['setor_qc']))
        r['sisa'] = _r2(max(0.0, max(r['komitmen'], r['setor_qc']) - r['dibayar']))
        r.setdefault('tagihan_ids', [])
        if r['sisa'] <= 0.5 and r['boleh_dibayar'] <= 0.005:
            continue                      # sudah selesai: tidak ada yang akan disetor maupun dibayar
        v = out.setdefault(key[1], {'vendor_id': key[1], 'vendor_name': master.get(key[1]) or r['vendor_name']
                                    or ('Vendor belum ditentukan' if not key[1] else key[1]),
                                    'pos': [], 'tagihan': []})
        v['pos'].append(r)
    for t in tagihan:
        v = out.get(t['vendor_id'])
        if v is not None and (t['boleh_dibayar'] > 0.005 or t['sisa'] > 0.5):
            v['tagihan'].append(t)
    hasil = []
    for v in out.values():
        v['pos'].sort(key=lambda r: (-r['boleh_dibayar'], str(r['po_number'])))
        v['tagihan'] = ab.urutkan([{**t, 'urut': t['tanggal']} for t in v['tagihan']])
        for k in ('komitmen', 'setor_qc', 'dibayar', 'ditahan', 'boleh_dibayar', 'belum_setor', 'sisa'):
            v[k] = _r2(sum(r[k] for r in v['pos']))
        v['antar_cv'] = any(t['antar_cv'] for t in v['tagihan'])
        v['cv'] = sorted({r['entity'] for r in v['pos']})
        hasil.append(v)
    hasil.sort(key=lambda v: (-v['boleh_dibayar'], -v['sisa'], str(v['vendor_name']).lower()))
    return hasil


async def _tagihan_hidup(db, vendor_id: str | None = None, *, lunas_po_ids=None) -> tuple[list, dict]:
    """Tagihan CMT yang BELUM lunas (+ peta PO-nya); `lunas_po_ids` → tambah tagihan lunas PO itu (angka "sudah
    dibayar" per PO). `vendor_id` → hanya vendor itu (semua id aliasnya). Tagihan lunas PO lain tidak dimuat, jadi
    layar tidak makin berat seiring riwayat tagihan."""
    from core import cmt_vendor_master
    syarat = [{'status': {'$nin': list(_MATI) + ['paid']}}]
    if lunas_po_ids:
        syarat.append({'status': 'paid', 'po_id': {'$in': list(lunas_po_ids)}})
    q: dict = {'$or': syarat}
    if vendor_id:
        q = {'$and': [q, await cmt_vendor_master.payment_filter(db, vendor_id)]}
    bills = [b async for b in db.dewi_cmt_payments.find(q, {'_id': 0}).sort('created_at', 1).limit(5000)]
    canon = await cmt_vendor_master.canonical_map(db, bills)
    po_ids = sorted({b['po_id'] for b in bills if b.get('po_id')})
    pos = {p['id']: p async for p in db.production_pos.find(
        {'id': {'$in': po_ids}}, {'_id': 0, 'id': 1, 'po_number': 1, 'status': 1, 'business_type': 1})} \
        if po_ids else {}
    from core import intercompany as ic
    from core.entities import DA
    tim = (await ic.own_team_vendor(db) or {}).get('id') if bills else None
    rows = []
    for b in bills:
        vid = canon.get(b['id']) or b.get('vendor_id') or ''
        po = pos.get(b.get('po_id')) or {}
        bt = 'maklon' if po.get('business_type') == 'maklon' else 'internal'
        row = baris_tagihan(b, vid, entitas_tagihan(b, bt))
        # tagihan DA kepada tim jahit CV Sukma = hutang antar CV (aturan `intercompany.sewing_bill_is_ic`)
        row['antar_cv'] = row['antar_cv'] or bool(tim and vid == tim and row['entity'] == DA)
        rows.append(row)
    return rows, pos


async def posisi_cmt(db, *, entity: str | None = None, vendor_id: str | None = None) -> dict:
    """Posisi hutang per CMT dan per PO (baca saja). `entity` DA/SMU menyaring buku; None/ALL = kedua CV."""
    from core import cmt_vendor_master
    from core.entities import ALL, DA, SMU
    vid = (await cmt_vendor_master.canonical_id(db, vendor_id) or vendor_id) if vendor_id else None
    terbuka_rows, _ = await _tagihan_hidup(db, vid)
    q: dict = {'status': {'$nin': ['cancelled', 'lunas']}}
    if vid:
        q['vendor_id'] = vid
    jadwal = [s async for s in db.dewi_cmt_ap_schedules.find(q, {'_id': 0}).sort('updated_at', -1).limit(5000)]
    terbuka = sorted({t['po_id'] for t in terbuka_rows if t['po_id']})
    jadwal += await ml.perkiraan_internal(db, vendor_id=vid, tambahan_po_ids=terbuka)
    # tagihan lunas hanya untuk PO yang masih tampil (angka "sudah dibayar" per PO)
    tagihan, pos = await _tagihan_hidup(db, vid, lunas_po_ids=sorted(set(terbuka) | {s.get('po_id') for s in jadwal
                                                                                     if s.get('po_id')}))
    lain = sorted({s.get('po_id') for s in jadwal if s.get('po_id')} - set(pos))
    if lain:
        async for p in db.production_pos.find({'id': {'$in': lain}},
                                              {'_id': 0, 'id': 1, 'po_number': 1, 'status': 1, 'business_type': 1}):
            pos[p['id']] = p
    if entity in (DA, SMU):
        def cv_jadwal(s):
            bt = s.get('business_type') or (pos.get(s.get('po_id')) or {}).get('business_type')
            return SMU if bt == 'maklon' else DA
        tagihan = [t for t in tagihan if t['entity'] == entity]
        jadwal = [s for s in jadwal if cv_jadwal(s) == entity]
    vids = sorted({t['vendor_id'] for t in tagihan if t['vendor_id']} | {s.get('vendor_id') for s in jadwal
                                                                          if s.get('vendor_id')})
    master = {v['id']: v.get('name') or '' async for v in db.vendor_partners.find(
        {'id': {'$in': vids}}, {'_id': 0, 'id': 1, 'name': 1})} if vids else {}
    vendors = susun_posisi(jadwal, tagihan, pos, master)
    tot = {k: _r2(sum(v[k] for v in vendors)) for k in
           ('komitmen', 'setor_qc', 'dibayar', 'ditahan', 'boleh_dibayar', 'belum_setor', 'sisa')}
    return {'vendors': vendors, 'totals': tot, 'entity': entity or ALL}


# ══════════════════════════════════════════════════════════════════════════════
# BAYAR GABUNGAN (satu CMT, beberapa tagihan, satu bukti)
# ══════════════════════════════════════════════════════════════════════════════
async def bayar_gabungan(db, *, vendor_id: str, amount: float, cash_account_id: str, payment_date: str | None,
                         alokasi: list | None, user: dict, notes: str = '', reference_no: str = '',
                         counter_cash_account_id: str | None = None) -> dict:
    """Satu pembayaran ke SATU CMT untuk beberapa tagihannya. ValueError = ditolak (pesan untuk staf);
    HTTPException 409 dari kunci tagihan diteruskan apa adanya.

    Aturan: rekening aktif; hanya tagihan CMT ini yang CV-nya sama dengan pemilik rekening; tiap baris ≤ boleh
    dibayar tagihannya; jumlah = Σ pembagian (tanpa pembagian → terlama dulu). Lihat docstring berkas."""
    from fastapi import HTTPException
    from core import cmt_vendor_master, doc_lock
    from core.entities import entity_of_value, entity_short
    from routes.dewi_maklon_finance import (CmtPayIn, pay_cmt_bill_locked, post_cmt_ap_invoice,
                                            void_cmt_disbursement_locked)
    from utils.waktu import today_wib

    vid = (await cmt_vendor_master.canonical_id(db, vendor_id) or vendor_id or '').strip()
    if not vid:
        raise ValueError('Pilih vendor CMT yang dibayar.')
    amount = _r2(amount)
    if amount <= 0:
        raise ValueError('Jumlah dibayar harus lebih dari 0.')
    acc = await db.rahaza_cash_accounts.find_one({'id': cash_account_id, 'active': {'$ne': False}}, {'_id': 0}) \
        if cash_account_id else None
    if not acc:
        raise ValueError('Pilih rekening kas/bank pembayar yang aktif.')
    ent = entity_of_value(acc.get('entity'))
    tagihan, _ = await _tagihan_hidup(db, vid)
    milik = {t['id']: t for t in tagihan}
    sah = {t['id']: t['boleh_dibayar'] for t in tagihan if t['entity'] == ent and t['boleh_dibayar'] > 0.005}
    label = {t['id']: f"tagihan {t['nomor']}" + (f" (PO {t['po_number']})" if t['po_number'] else '')
             for t in tagihan}
    vname = (tagihan[0]['vendor_name'] if tagihan else '') or vid
    vp = await db.vendor_partners.find_one({'id': vid}, {'_id': 0, 'name': 1})
    vname = (vp or {}).get('name') or vname
    if not alokasi:
        baris, sisa = ab.alokasi_terlama(amount, [{'id': i, 'batas': b, 'urut': milik[i]['tanggal'],
                                                    'nomor': milik[i]['nomor']} for i, b in sah.items()])
        if sisa > ab.TOLERANSI:
            raise ValueError(f"Jumlah {ab._rp(amount)} melebihi yang boleh dibayar ke {vname} di "
                             f"{entity_short(ent)} ({ab._rp(sum(sah.values()))}).")
        alokasi = baris
    for a in alokasi:
        aid = str((a or {}).get('id') or '')
        if not aid or aid in sah or _f((a or {}).get('jumlah')) <= 0.005:
            continue
        if aid in milik:
            t = milik[aid]
            if t['entity'] != ent:
                raise ValueError(f"{ab.awal(label[aid])} dibukukan di {entity_short(t['entity'])}, rekening yang "
                                 f"dipilih milik {entity_short(ent)} — bayar dari rekening {entity_short(t['entity'])} "
                                 "secara terpisah.")
            raise ValueError(f"{ab.awal(label[aid])} belum bisa dibayar (boleh dibayar Rp 0"
                             + (f", {ab._rp(t['ditahan'])} tertahan selisih tagihan" if t['ditahan'] > 0 else '')
                             + ").")
        lain = await db.dewi_cmt_payments.find_one({'id': aid}, {'_id': 0})
        if not lain:
            raise ValueError('Tagihan CMT di pembagian tidak ditemukan — muat ulang lalu ulangi.')
        if ((await cmt_vendor_master.canonical_map(db, [lain])).get(aid) or lain.get('vendor_id')) == vid:
            raise ValueError(f"Tagihan {lain.get('payment_code') or aid} sudah lunas atau dibatalkan — muat ulang.")
        raise ValueError(f"Tagihan {lain.get('payment_code') or aid} milik {lain.get('cmt_name') or 'CMT lain'}, "
                         f"bukan {vname} — satu pembayaran hanya untuk satu CMT.")
    lines = ab.periksa_alokasi(alokasi, sah, label=label, apa='tagihan')
    total = _r2(sum(x['jumlah'] for x in lines))
    if abs(total - amount) > ab.TOLERANSI:
        raise ValueError(f"Jumlah dibayar {ab._rp(amount)} tidak sama dengan jumlah pembagian {ab._rp(total)}.")
    if any(milik[x['id']]['antar_cv'] for x in lines) and not counter_cash_account_id:
        raise ValueError('Tagihan tim jahit CV Sukma = hutang antar CV: pilih rekening CV Sukma yang menerima.')

    tokens: dict = {}
    try:
        for pid in sorted(x['id'] for x in lines):
            tokens[pid] = await doc_lock.claim(
                db, 'dewi_cmt_payments', pid, field='pay_lock', actor=user, not_found='Tagihan CMT tidak ditemukan',
                busy=f"{ab.awal(label.get(pid, 'tagihan'))} sedang dibayar pengguna lain. Muat ulang lalu ulangi.")
        segar = {b['id']: b async for b in db.dewi_cmt_payments.find({'id': {'$in': list(tokens)}}, {'_id': 0})}
        for x in lines:
            bisa = ml.cmt_bill_payable(segar.get(x['id']) or {})
            if x['jumlah'] > bisa + 0.01:
                raise ValueError(f"{ab.awal(label[x['id']])} kini hanya boleh dibayar {ab._rp(bisa)} — muat ulang "
                                 "lalu ulangi.")
        # tagihan yang belum dijurnal dijurnal dulu, SEBELUM uang dicatat (supaya gagal jurnal tidak setengah jalan)
        for x in lines:
            b = segar[x['id']]
            if not b.get('gl_je_id'):
                ap = await post_cmt_ap_invoice(db, b, user)
                if not ap.get('ok'):
                    raise ValueError(f"{ab.awal(label[x['id']])} belum bisa dijurnal: {ap.get('error')}")

        pay_date = (payment_date or today_wib().isoformat())[:10]
        bid = str(uuid.uuid4())
        nomor = await ab.terbitkan_nomor(db, ab.NOMOR_BAYAR_CMT)
        batch = {'batch_id': bid, 'bukti_number': nomor}
        doc = {'id': bid, 'jenis': ab.JENIS_BAYAR_CMT, 'bukti_number': nomor, 'pihak_id': vid, 'pihak_name': vname,
               'entity': ent, 'tanggal': pay_date, 'amount': total, 'cash_account_id': acc['id'],
               'cash_account_name': acc.get('name', ''), 'counter_cash_account_id': counter_cash_account_id or None,
               'reference_no': reference_no or '', 'notes': notes or '', 'status': 'proses', 'alokasi': [],
               'created_at': _now(), 'created_by': user.get('id'), 'created_by_name': user.get('name', '')}
        await db[ab.COLL].insert_one(dict(doc))
        done = []
        try:
            for x in lines:
                memo = f"{nomor}" + (f" · {notes}" if notes else '')
                out = await pay_cmt_bill_locked(
                    db, x['id'], CmtPayIn(cash_account_id=acc['id'], amount=x['jumlah'], payment_date=pay_date,
                                          reference_no=reference_no or nomor, notes=memo,
                                          counter_cash_account_id=counter_cash_account_id), user, batch=batch)
                done.append((x, out))
        except (HTTPException, ValueError) as e:
            pesan = e.detail if isinstance(e, HTTPException) else str(e)
            for x, out in reversed(done):
                try:
                    await void_cmt_disbursement_locked(db, x['id'], out.get('id'), user,
                                                       reason=f'Bukti {nomor} gagal dicatat — dibatalkan kembali')
                except Exception:  # noqa: BLE001 — tetap lanjut menggulung yang lain; dicatat untuk Keuangan
                    logger.exception('gulung balik pembayaran %s tagihan %s gagal', out.get('id'), x['id'])
            await db[ab.COLL].update_one({'id': bid}, {'$set': {'status': 'gagal', 'error': pesan, 'updated_at': _now()}})
            raise ValueError(f"Pembayaran {nomor} tidak dicatat: {pesan}"
                             + (f" {len(done)} pembayaran yang sempat tercatat sudah dibatalkan kembali." if done else ''))
        rincian = []
        for x, out in done:
            t = milik[x['id']]
            rincian.append({'payment_id': x['id'], 'nomor': t['nomor'], 'po_id': t['po_id'], 'po_number': t['po_number'],
                            'tanggal_tagihan': t['tanggal'], 'nilai_tagihan': t['nilai'], 'jumlah': x['jumlah'],
                            'disbursement_id': out.get('id'), 'je_number': out.get('gl_je_number'),
                            'post_error': out.get('post_error'),
                            'sisa_tagihan': _r2(out.get('outstanding_amount'))})
        upd = {'status': 'tercatat', 'alokasi': rincian, 'updated_at': _now(),
               'jurnal_gagal': [r['nomor'] for r in rincian if r.get('post_error')]}
        await db[ab.COLL].update_one({'id': bid}, {'$set': upd})
        from auth import log_activity
        await log_activity(user.get('id', ''), user.get('name', ''), 'pay_cmt_batch', ab.COLL,
                           f"{nomor}: bayar {vname} {ab._rp(total)} untuk {len(rincian)} tagihan via {acc.get('name')}")
        return {**doc, **upd}
    finally:
        for pid, tok in tokens.items():
            await doc_lock.release(db, 'dewi_cmt_payments', pid, tok, field='pay_lock')


async def daftar_bukti(db, jenis: str, pihak_id: str | None = None, limit: int = 50) -> list:
    """Bukti pembayaran gabungan terbaru (CMT atau klien), terbaru dulu."""
    q: dict = {'jenis': jenis, 'status': {'$ne': 'gagal'}}
    if pihak_id:
        q['pihak_id'] = pihak_id
    return [d async for d in db[ab.COLL].find(q, {'_id': 0}).sort('created_at', -1).limit(limit)]
