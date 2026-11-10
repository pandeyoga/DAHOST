"""core.denda_po — DENDA saat Tutup PO, dua arah (permintaan owner 9–10 Nov 2026).

Kata owner:
  * "denda … saya ingin tambahkan ketika tutup po, untuk jumlah dendanya sendiri dihitung per qty dari pesanan PO
    dikalikan nominal denda per pcs. denda bisa memotong bon yang ada atau menerbitkan baru jika tidak ada bon";
  * "client juga bisa memberikan denda, misal klien retur klien mendenda dan da mendenda juga cmt namun nominal atau
    qty nya bisa berbeda".

Jadi satu PO bisa punya DUA denda yang berdiri sendiri, masing-masing qty (bawaan = qty pesanan PO, boleh diubah)
× nominal per pcs + alasan:

  * **klien → DA** (hanya PO maklon, CV Sukma): klien memotong tagihan jasa maklon.
      Jurnal  Dr Retur/Potongan Maklon (profil `po_denda.debit_denda_klien`, bawaan 4-1590)
              Cr Piutang klien (sub-ledger 1-1305-<KODE>, sama dengan piutang PO).
      Dokumen piutang PO (`rahaza_ar_invoices`, jadwal v2) mencatatnya di `denda_postings`; `core.maklon_ledger`
      mengurangkannya dari sisa tagihan. Bila piutang PO sudah lunas/lebih kecil dari denda, kelebihannya menjadi
      saldo kredit klien (uang muka klien 2-1700) lewat rekonsiliasi uang muka yang sudah ada — tidak ada uang hilang.

  * **DA → CMT** (PO internal & maklon, vendor CMT luar): DA memotong upah jahit vendor.
      Jurnal  Dr Hutang vendor CMT (sub-ledger 2-1110-<vendor>, sama dengan tagihan CMT)
              Cr biaya CMT — PO maklon: `po_denda.credit_denda_cmt_maklon` (bawaan 5-4200 Biaya vendor CMT maklon);
                             PO internal: `po_denda.credit_denda_cmt_internal` (bawaan 5-1960 Selisih produksi —
                             upah jahit PO internal sudah masuk WIP dan sisanya ditutup ke akun ini saat PO ditutup).
      Mengikuti keputusan owner M-04 (penalti CMT mengurangi biaya & hutang CMT, bukan pendapatan lain).
      Dokumen: denda **memotong tagihan (bon) CMT yang masih terbuka** — tagihan PO ini dulu, lalu tagihan lain vendor
      itu di CV yang sama, terlama dulu. Bila tidak ada / kurang, sisanya tetap terbuka di nota denda dan **otomatis
      memotong tagihan berikutnya** vendor itu (`potong_tagihan_baru`, dipanggil saat tagihan lolos QC lahir).

Vendor tim jahit CV Sukma sendiri (`vendor_partners.owner_entity`) tidak bisa didenda dari sini: PO maklon ke tim
Sukma tidak punya tagihan, dan tagihan PO internal ke tim Sukma adalah transaksi antar CV (perlu keputusan owner).

Satu koleksi `dewi_po_denda` (satu dokumen per denda), nomor `DND-KLN-#####` / `DND-CMT-#####`. Satu jurnal per denda
(`source_module='po_denda'`, `source_ref='po_denda:<id>'`); potongan ke tagihan hanya penyesuaian dokumen (jurnal
hutang sudah turun oleh jurnal denda itu sendiri).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

logger = logging.getLogger(__name__)

COLL = 'dewi_po_denda'
PROFILE = 'po_denda'
SOURCE_MODULE = 'po_denda'
PIHAK = ('klien', 'cmt')
PIHAK_LABEL = {'klien': 'Denda dari klien', 'cmt': 'Denda ke CMT'}
PREFIX = {'klien': 'DND-KLN-', 'cmt': 'DND-CMT-'}
NUMBER_KEY = {'klien': 'dewi_po_denda.nomor_klien', 'cmt': 'dewi_po_denda.nomor_cmt'}
# Akun bawaan profil `po_denda` (dicerminkan di routes/rahaza_posting_profiles.DEFAULT_PROFILES).
DEFAULT_MAPPING = {
    'debit_denda_klien': '4-1590',
    'credit_denda_cmt_maklon': '5-4200',
    'credit_denda_cmt_internal': '5-1960',
}
BILL_CLOSED = ('cancelled', 'void', 'voided', 'paid')


def _uid() -> str:
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _r2(v) -> float:
    return round(_f(v) + 0.0, 2)


def fmt_rp(v) -> str:
    return 'Rp ' + f"{round(_f(v)):,.0f}".replace(',', '.')


# ══════════════════════════════ masukan ══════════════════════════════
def parse_input(body: dict | None) -> dict:
    """`body['denda'] = {'klien': {qty, per_pcs, alasan}, 'cmt': {...}}` → {pihak: {qty, per_pcs, jumlah, alasan}}.
    Bagian dengan nominal 0/kosong diabaikan. Masukan tidak sah → 400 berkalimat staf. Murni."""
    raw = (body or {}).get('denda') or {}
    if not isinstance(raw, dict):
        raise HTTPException(400, 'Isian denda tidak dikenali.')
    out = {}
    for pihak in PIHAK:
        d = raw.get(pihak)
        if not d:
            continue
        per_pcs = _f(d.get('per_pcs'))
        if per_pcs <= 0:
            continue
        label = PIHAK_LABEL[pihak]
        try:
            qty = int(float(d.get('qty') or 0))
        except (TypeError, ValueError):
            raise HTTPException(400, f'{label}: qty harus angka.')
        if qty <= 0:
            raise HTTPException(400, f'{label}: qty harus lebih dari 0.')
        alasan = str(d.get('alasan') or '').strip()
        if len(alasan) < 3:
            raise HTTPException(400, f'{label}: alasan wajib diisi (mis. retur klien 20 pcs jahitan lepas).')
        out[pihak] = {'qty': qty, 'per_pcs': _r2(per_pcs), 'jumlah': _r2(qty * per_pcs), 'alasan': alasan}
    return out


def qty_pesanan(items: list) -> int:
    """Qty pesanan PO (bawaan qty denda). Murni."""
    return sum(max(0, int(_f(i.get('qty')))) for i in items or [])


def alokasi(jumlah: float, tagihan: list) -> list:
    """Murni: bagi `jumlah` ke tagihan berurutan sebatas `bisa` masing-masing → [(id, potong)]."""
    sisa = _r2(jumlah)
    out = []
    for t in tagihan:
        if sisa <= 0.004:
            break
        x = _r2(min(sisa, _f(t.get('bisa'))))
        if x > 0.004:
            out.append((t['id'], x))
            sisa = _r2(sisa - x)
    return out


# ══════════════════════════════ akun ══════════════════════════════
async def _mapping(db) -> dict:
    from routes.rahaza_posting_profiles import get_mapping
    m = dict(DEFAULT_MAPPING)
    m.update({k: v for k, v in ((await get_mapping(db, PROFILE)) or {}).items() if v})
    return m


async def _vendor(db, vendor_id: str) -> dict:
    from core.cmt_vendor_master import canonical_id
    vid = await canonical_id(db, vendor_id) or vendor_id
    return await db.vendor_partners.find_one({'id': vid}, {'_id': 0}) or {}


async def _ap_account(db, vendor: dict, user: dict) -> str | None:
    from routes.coa_auto import resolve_ap_account_for_cmt
    from routes.rahaza_posting_profiles import get_mapping
    code = None
    try:
        code = await resolve_ap_account_for_cmt(db, vendor.get('id'), vendor.get('name', ''), user)
    except Exception:  # noqa: BLE001 — jatuh ke akun kontrol, sama dengan posting tagihan CMT
        logger.exception('akun hutang vendor CMT %s gagal', vendor.get('id'))
    return code or ((await get_mapping(db, 'cmt_ap_invoice')) or {}).get('credit_ap')


# ══════════════════════════════ rencana (validasi tanpa menulis) ══════════════════════════════
async def rencana(db, po: dict, masukan: dict, user: dict) -> dict:
    """Periksa semua syarat SEBELUM PO ditutup (supaya denda yang ditolak tidak meninggalkan PO setengah tertutup).
    → {pihak: {..., akun_debit, akun_kredit, entity, ...}}. Melempar 400 berkalimat staf."""
    from core.entities import entity_of_po_id, po_business_type
    if not masukan:
        return {}
    plan = {}
    bt = po_business_type(po)
    ent = await entity_of_po_id(db, po['id'])
    mp = await _mapping(db)
    for pihak, d in masukan.items():
        if await db[COLL].find_one({'po_id': po['id'], 'pihak': pihak, 'status': {'$ne': 'batal'}}, {'_id': 0, 'nomor': 1}):
            raise HTTPException(400, f'{PIHAK_LABEL[pihak]} untuk PO ini sudah tercatat — tidak dibuat dua kali.')
        p = dict(d, entity=ent, business_type=bt)
        if pihak == 'klien':
            if bt != 'maklon':
                raise HTTPException(400, 'Denda dari klien hanya untuk PO maklon.')
            from core import maklon_ledger as ml
            ar = await ml.find_ar(db, po['id'])
            if not ar or not ml.is_schedule(ar) or ar.get('status') == 'cancelled':
                raise HTTPException(400, 'Denda dari klien tidak bisa dicatat: piutang PO ini tidak ada / dibatalkan / '
                                         'masih memakai faktur alur lama. Catat lewat Keuangan.')
            ar_code = ar.get('gl_ar_account_code') or (await ml.client_accounts(db, po.get('buyer_id'), user)).get('ar')
            if not ar_code or not mp.get('debit_denda_klien'):
                raise HTTPException(400, 'Akun piutang klien atau akun potongan maklon belum ada — atur di Master Akuntansi.')
            p.update(pihak_id=po.get('buyer_id') or '', pihak_nama=po.get('customer_name') or '', ar_id=ar['id'],
                     ar_nomor=ar.get('invoice_number') or '', akun_debit=mp['debit_denda_klien'], akun_kredit=ar_code)
        else:
            if not po.get('vendor_id'):
                raise HTTPException(400, 'PO ini belum punya vendor CMT — denda ke CMT tidak bisa dicatat.')
            v = await _vendor(db, po['vendor_id'])
            if not v:
                raise HTTPException(400, 'Vendor CMT PO ini tidak ditemukan di master Vendor CMT.')
            if v.get('owner_entity'):
                raise HTTPException(400, f"Vendor {v.get('name', '')} adalah tim jahit CV sendiri, bukan CMT luar — "
                                         'denda ke CMT hanya untuk vendor luar.')
            ap = await _ap_account(db, v, user)
            kredit = mp.get('credit_denda_cmt_maklon' if bt == 'maklon' else 'credit_denda_cmt_internal')
            if not ap or not kredit:
                raise HTTPException(400, 'Akun hutang vendor CMT atau akun denda CMT belum ada — atur di Master Akuntansi.')
            p.update(pihak_id=v['id'], pihak_nama=v.get('name') or '', akun_debit=ap, akun_kredit=kredit)
        plan[pihak] = p
    return plan


# ══════════════════════════════ terapkan ══════════════════════════════
async def terapkan(db, po: dict, plan: dict, user: dict) -> list:
    """Buat dokumen + jurnal tiap denda, lalu potong piutang / tagihan. Dipanggil sesudah `rencana` lolos."""
    out = []
    for pihak in PIHAK:
        if pihak in plan:
            out.append(await _buat(db, po, pihak, plan[pihak], user))
    return out


async def _buat(db, po: dict, pihak: str, p: dict, user: dict) -> dict:
    from routes.rahaza_posting import _create_posted_je
    from utils.counters import gen_prefixed_number
    from utils.waktu import today_wib
    did = _uid()
    nomor = await gen_prefixed_number(db, COLL, 'nomor', PREFIX[pihak], 5, config_key=NUMBER_KEY[pihak])
    memo = (f"{PIHAK_LABEL[pihak]} {nomor} · PO {po.get('po_number', '')} · {p.get('pihak_nama', '')} · "
            f"{p['qty']} pcs × {fmt_rp(p['per_pcs'])} · {p['alasan']}")
    je = await _create_posted_je(
        db, je_date=today_wib(), memo=memo, source_module=SOURCE_MODULE, source_ref=f'po_denda:{did}',
        user=user, entity=p['entity'],
        lines_raw=[{'account_code': p['akun_debit'], 'debit': p['jumlah'], 'credit': 0, 'description': memo},
                   {'account_code': p['akun_kredit'], 'debit': 0, 'credit': p['jumlah'], 'description': memo}])
    if not je.get('ok'):
        raise HTTPException(400, f"{PIHAK_LABEL[pihak]} tidak dicatat — jurnal gagal: {je.get('error')}")
    doc = {
        'id': did, 'nomor': nomor, 'pihak': pihak, 'po_id': po['id'], 'po_number': po.get('po_number', ''),
        'business_type': p['business_type'], 'entity': p['entity'],
        'pihak_id': p.get('pihak_id', ''), 'pihak_nama': p.get('pihak_nama', ''),
        'qty': p['qty'], 'per_pcs': p['per_pcs'], 'jumlah': p['jumlah'], 'alasan': p['alasan'],
        'je_id': je.get('je_id'), 'je_number': je.get('je_number'),
        'akun_debit': p['akun_debit'], 'akun_kredit': p['akun_kredit'],
        'potongan': [], 'jumlah_dipotong': 0.0, 'sisa': p['jumlah'], 'status': 'terbuka',
        'created_at': _now(), 'updated_at': _now(),
        'created_by': user.get('id', ''), 'created_by_name': user.get('name', ''),
    }
    await db[COLL].insert_one(dict(doc))
    if pihak == 'klien':
        doc = await _potong_piutang(db, doc, p, user)
    else:
        doc = await _potong_tagihan(db, doc, user, po_first=po['id'])
    try:
        from auth import log_activity
        await log_activity(user.get('id', ''), user.get('name', ''), 'po_denda.create', 'Production PO',
                           f"{nomor} PO {po.get('po_number')}: {PIHAK_LABEL[pihak]} {fmt_rp(doc['jumlah'])} "
                           f"(dipotong {fmt_rp(doc['jumlah_dipotong'])}, sisa {fmt_rp(doc['sisa'])})")
    except Exception:  # noqa: BLE001 — jejak aktivitas tidak boleh menggagalkan denda yang sudah dijurnal
        logger.exception('jejak aktivitas denda %s gagal', nomor)
    return doc


def _status(jumlah: float, dipotong: float) -> str:
    if dipotong <= 0.004:
        return 'terbuka'
    return 'lunas' if jumlah - dipotong <= 0.004 else 'sebagian'


async def _potong_piutang(db, doc: dict, p: dict, user: dict) -> dict:
    """Denda klien → `denda_postings` piutang PO; sisa tagihan & uang muka dihitung ulang oleh `sync_ar_schedule`."""
    from core import maklon_ledger as ml
    ar = await db.rahaza_ar_invoices.find_one({'id': p['ar_id']}, {'_id': 0}) or {}
    payments = await ml._payments(db, ar['id']) if ar else []
    a = ml.ar_amounts(ar, payments) if ar else {}
    # bagian yang memotong tagihan klien = tertagih (barang terkirim; PO ditutup → jadwal menyusut ke tertagih) yang
    # belum dibayar; kelebihannya menjadi kredit klien (uang muka) lewat rekonsiliasi uang muka maklon_ledger.
    belum_bayar = _r2(max(0.0, _f(a.get('billed_total')) - _f(a.get('paid_total')) - _f(a.get('denda_credit'))))
    dipotong = _r2(min(doc['jumlah'], belum_bayar))
    await db.rahaza_ar_invoices.update_one({'id': p['ar_id']}, {'$push': {'denda_postings': {
        'denda_id': doc['id'], 'nomor': doc['nomor'], 'amount': doc['jumlah'], 'date': str(_now().date()),
        'je_id': doc['je_id'], 'je_number': doc['je_number'], 'alasan': doc['alasan'], 'at': _now()}},
        '$set': {'updated_at': _now()}})
    pot = [{'dokumen': 'piutang_klien', 'id': p['ar_id'], 'nomor': p.get('ar_nomor', ''), 'jumlah': dipotong,
            'at': _now(), 'saat': 'tutup_po'}] if dipotong > 0 else []
    kredit = _r2(doc['jumlah'] - dipotong)
    # sisa denda klien tidak menunggu apa pun: langsung menjadi saldo kredit klien (uang muka) di piutang PO
    upd = {'potongan': pot, 'jumlah_dipotong': dipotong, 'sisa': 0.0, 'kredit_klien': kredit,
           'status': 'kredit_klien' if kredit > 0.004 else 'lunas', 'updated_at': _now()}
    await db[COLL].update_one({'id': doc['id']}, {'$set': upd})
    try:
        await ml.sync_ar_schedule(db, doc['po_id'], user)
    except Exception:  # noqa: BLE001 — PO ditutup juga menyegarkan piutang
        logger.exception('segarkan piutang PO %s sesudah denda gagal', doc.get('po_number'))
    return {**doc, **upd}


async def _tagihan_terbuka(db, vendor_id: str, entity: str | None, po_first: str | None = None) -> list:
    """Tagihan CMT vendor ini yang masih bisa dipotong: PO `po_first` dulu, lalu terlama. `entity` = hanya CV itu
    (denda); None = kedua CV (nota aksesoris CMT, `core.nota_aksesoris_cmt`)."""
    from core.maklon_ledger import cmt_bill_payable
    from routes.dewi_maklon_finance import cmt_bill_entity
    rows = []
    async for b in db.dewi_cmt_payments.find({'vendor_id': vendor_id, 'status': {'$nin': list(BILL_CLOSED)}},
                                             {'_id': 0}).sort('created_at', 1).limit(500):
        if entity is not None and await cmt_bill_entity(db, b) != entity:
            continue
        bisa = cmt_bill_payable(b)
        if bisa > 0.004:
            rows.append({**b, 'bisa': bisa})
    rows.sort(key=lambda b: 0 if po_first and b.get('po_id') == po_first else 1)  # stabil: urutan terlama tetap
    return rows


# Jenis potongan pada tagihan CMT → (field total, field jejak). Denda (Tutup PO) dan nota aksesoris CMT
# (`core.nota_aksesoris_cmt`, 11 Nov 2026) memakai SATU cara "potong bon" ini.
JENIS_DENDA = 'denda'
JENIS_NOTA_AKSESORIS = 'nota_aksesoris'
_JEJAK = {JENIS_DENDA: ('denda_dipotong', 'potongan_denda'),
          JENIS_NOTA_AKSESORIS: ('nota_aksesoris_dipotong', 'potongan_nota_aksesoris')}


async def _kurangi_tagihan(db, bill: dict, x: float, doc: dict, saat: str, user: dict, *,
                           jenis: str = JENIS_DENDA) -> None:
    from core.maklon_ledger import _bill_amount
    f_total, f_jejak = _JEJAK[jenis]
    net = _r2(_bill_amount(bill) - x)
    jejak = {'nomor': doc['nomor'], 'jumlah': x, 'saat': saat, 'po_number': doc.get('po_number', ''), 'at': _now()}
    jejak['denda_id' if jenis == JENIS_DENDA else 'nota_id'] = doc['id']
    await db.dewi_cmt_payments.update_one({'id': bill['id']}, {
        '$set': {'net_amount': net, 'total_amount': net, 'outstanding_amount': _r2(net - _f(bill.get('paid_amount'))),
                 f_total: _r2(_f(bill.get(f_total)) + x), 'updated_at': _now()},
        '$push': {f_jejak: jejak}})
    try:
        from routes.dewi_maklon_finance import _refresh_ap_schedule_safe
        await _refresh_ap_schedule_safe(db, bill.get('po_id'), user)
    except Exception:  # noqa: BLE001
        logger.exception('jadwal hutang CMT PO %s gagal disegarkan', bill.get('po_id'))


async def _potong_tagihan(db, doc: dict, user: dict, *, po_first: str | None = None, hanya: list | None = None,
                          saat: str = 'tutup_po') -> dict:
    tagihan = hanya if hanya is not None else await _tagihan_terbuka(db, doc['pihak_id'], doc['entity'], po_first)
    by_id = {t['id']: t for t in tagihan}
    pot = list(doc.get('potongan') or [])
    dipotong = _f(doc.get('jumlah_dipotong'))
    for bid, x in alokasi(_f(doc.get('sisa')), tagihan):
        b = by_id[bid]
        await _kurangi_tagihan(db, b, x, doc, saat, user)
        pot.append({'dokumen': 'tagihan_cmt', 'id': bid, 'nomor': b.get('payment_code', ''), 'po_number': b.get('po_number', ''),
                    'jumlah': x, 'at': _now(), 'saat': saat})
        dipotong = _r2(dipotong + x)
    upd = {'potongan': pot, 'jumlah_dipotong': dipotong, 'sisa': _r2(doc['jumlah'] - dipotong),
           'status': _status(doc['jumlah'], dipotong), 'updated_at': _now()}
    await db[COLL].update_one({'id': doc['id']}, {'$set': upd})
    return {**doc, **upd}


async def potong_tagihan_baru(db, bill_id: str, user: dict) -> list:
    """Tagihan CMT baru lahir (lolos QC) → sisa nota denda CMT vendor itu (CV sama, terlama dulu) memotongnya.
    Tidak pernah menggagalkan pematangan tagihan (pemanggil membungkus try)."""
    from core.maklon_ledger import cmt_bill_payable
    from routes.dewi_maklon_finance import cmt_bill_entity
    bill = await db.dewi_cmt_payments.find_one({'id': bill_id}, {'_id': 0})
    if not bill or not bill.get('vendor_id') or bill.get('status') in BILL_CLOSED:
        return []
    ent = await cmt_bill_entity(db, bill)
    hasil = []
    async for d in db[COLL].find({'pihak': 'cmt', 'pihak_id': bill['vendor_id'], 'entity': ent,
                                  'status': {'$in': ['terbuka', 'sebagian']}}, {'_id': 0}).sort('created_at', 1).limit(100):
        bill = await db.dewi_cmt_payments.find_one({'id': bill_id}, {'_id': 0})
        bisa = cmt_bill_payable(bill)
        if bisa <= 0.004:
            break
        d2 = await _potong_tagihan(db, d, user, hanya=[{**bill, 'bisa': bisa}], saat='tagihan_baru')
        hasil.append({'nomor': d2['nomor'], 'dipotong': _r2(d2['jumlah_dipotong'] - _f(d.get('jumlah_dipotong')))})
    return hasil


# ══════════════════════════════ baca ══════════════════════════════
async def daftar(db, *, po_id: str | None = None, pihak: str | None = None, status: str | None = None,
                 business_type: str | None = None, limit: int = 500) -> list:
    q: dict = {}
    if po_id:
        q['po_id'] = po_id
    if pihak in PIHAK:
        q['pihak'] = pihak
    if status:
        q['status'] = status
    if business_type in ('maklon', 'internal'):
        q['business_type'] = business_type
    return await db[COLL].find(q, {'_id': 0}).sort('created_at', -1).limit(limit).to_list(limit)
