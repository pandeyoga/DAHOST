"""core.nota_aksesoris_cmt — NOTA JUAL AKSESORIS ke vendor CMT (permintaan owner 10–11 Nov 2026).

Kata owner: "aksesoris yang dikirimkan ke CMT itu dibeli oleh cmt, jadi tolong buatkan nota invoicenya. untuk
nominalnya harganya berapa bisa diinputkan saja langsung di portal produksi dan maklon. pembayarannya bisa potong
hutang atau dibayar langsung."

KEPUTUSAN OWNER (11 Nov 2026)
  1. SEMUA aksesoris yang diserahkan ke CMT luar masuk nota. Harga jual per satuan serah DIKETIK setiap kiriman
     (bisa beda per CMT dan berubah setiap saat — bukan master harga jual); TIDAK terisi otomatis; 0 = gratis.
     Nilai stok (HPP) aksesoris ditampilkan sebagai acuan. Potongan & kain tidak pernah dijual.
  2. Penerbit nota SELALU CV Dewi Aditya (stok aksesoris milik DA), juga untuk PO maklon.
  3. Aksesoris TETAP dihitung di HPP PO (jurnal pengeluaran Kirim ke CMT tidak berubah). Seluruh nilai nota
     dicatat sebagai pendapatan lain-lain.
  Tim jahit CV sendiri (vendor ber-`owner_entity`, mis. tim Sukma) bukan CMT luar → tidak dibuatkan nota
  (aturan yang sama dengan denda ke CMT, `core.denda_po`).

DOKUMEN — piutang biasa, bukan modul kedua
  Nota = satu dokumen `rahaza_ar_invoices` (`source_module='cmt_accessory'`, nomor `NAC-#####`) sehingga langsung
  tampil di Keuangan › Piutang, umur piutang, dan "Bayar" (pembayaran tunai/transfer memakai jalur piutang yang sudah
  ada; jurnal Dr Kas/Bank / Cr akun piutang nota). Lawan transaksi = vendor CMT (`vendor_id`), bukan pelanggan.

JURNAL (buku CV Dewi Aditya)
  * Terbit : Dr Piutang Vendor CMT (sub-ledger per vendor 1-1307-<kode>, profil `cmt_accessory_note.debit_ar`)
             Cr Penjualan Aksesoris ke CMT (`credit_other_income`, bawaan 4-9400, pendapatan lain-lain).
  * Potong tagihan jahit (cara `potong_tagihan`) — SAMA dengan "potong bon" denda (`core.denda_po`): tagihan CMT
    vendor itu yang masih terbuka (PO kiriman ini dulu, lalu terlama), sisanya menunggu dan otomatis memotong tagihan
    berikutnya yang lahir saat penerimaan lolos QC (`potong_tagihan_baru`). Tagihan CMT berkurang
    (`potongan_nota_aksesoris`, `nota_aksesoris_dipotong`); jurnal per potongan:
      - tagihan di buku DA (PO internal): Dr Hutang vendor CMT / Cr Piutang Vendor CMT;
      - tagihan di buku CV Sukma (PO maklon): DA tidak berhutang ke CMT itu, jadi CV Sukma membayar sebagian
        tagihannya kepada DA — SMU: Dr Hutang vendor CMT / Cr Hutang ke CV DA; DA: Dr Piutang CV Sukma /
        Cr Piutang Vendor CMT (berlabel antar CV, dieliminasi di laporan gabungan; dilunasi lewat Transaksi antar CV).
  * Dibayar langsung: Keuangan › Piutang › Bayar (jalur `/ar-invoices/{id}/payment` yang sudah ada).
  * Batal (belum dibayar/dipotong): jurnal terbit dibalik.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from core.entities import DA, SMU

logger = logging.getLogger(__name__)

COLL = 'rahaza_ar_invoices'
SOURCE = 'cmt_accessory'                 # rahaza_ar_invoices.source_module
JE_MODULE = 'cmt_accessory_note'         # jurnal terbit (source_ref `nac:<id>`)
JE_OFFSET = 'cmt_accessory_offset'       # jurnal potong tagihan (source_ref `nacpot:<id potongan>`)
PROFILE = 'cmt_accessory_note'
ISSUER = DA
PREFIX = 'NAC-'
NUMBER_KEY = 'rahaza_ar_invoices.nota_aksesoris_cmt'
SUBLEDGER_TYPE = 'cmt_vendor_ar'         # routes.coa_auto: piutang per vendor CMT di bawah 1-1307
# Akun bawaan profil `cmt_accessory_note` (dicerminkan di routes/rahaza_posting_profiles.DEFAULT_PROFILES).
DEFAULT_MAPPING = {'debit_ar': '1-1307', 'credit_other_income': '4-9400'}
ACCOUNTS = (
    {'code': '1-1307', 'name': 'Piutang Vendor CMT', 'type': 'ASSET', 'parent_code': '1-1300',
     'normal_balance': 'DEBIT', 'flags': {'is_ar': True}, 'cash_flow_group': 'OPR'},
    {'code': '4-9400', 'name': 'Penjualan Aksesoris ke CMT', 'type': 'OTHER_INCOME', 'parent_code': '4-0000',
     'normal_balance': 'CREDIT', 'flags': {}, 'cash_flow_group': None},
)
CARA_BAYAR = {'potong_tagihan': 'Potong tagihan jahit', 'langsung': 'Dibayar langsung'}
CARA_BAWAAN = 'potong_tagihan'
OPEN = ('issued', 'partial_paid', 'overdue')
STATUS_LABEL = {'issued': 'Belum dibayar', 'partial_paid': 'Sebagian', 'overdue': 'Belum dibayar', 'paid': 'Lunas',
                'cancelled': 'Batal'}
KIND_OFFSET = 'cmt_accessory_offset'     # = core.intercompany.KIND_CMT_ACCESSORY_OFFSET (label antar CV)
_EPS = 0.004


def _uid() -> str:
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _rp0(v) -> float:
    """Piutang dicatat dalam rupiah bulat (sama dengan jalur pembayaran piutang)."""
    return float(round(_f(v)))


def fmt_rp(v) -> str:
    return 'Rp ' + f"{round(_f(v)):,.0f}".replace(',', '.')


def fmt_num(v) -> str:
    x = round(_f(v), 4)
    return (f"{x:,.0f}" if float(x).is_integer() else f"{x:,.4f}".rstrip('0').rstrip('.')).replace(',', '#') \
        .replace('.', ',').replace('#', '.')


# ══════════════════════════════ masukan (murni) ══════════════════════════════
def parse_input(raw) -> Optional[dict]:
    """`nota_aksesoris` dari form → {'cara_bayar', 'harga': {kunci: harga}} (kunci = `key` baris & `material_id`).
    None bila form tidak mengirim isian nota (klien lama / jalur lain). Harga tidak sah → 400 berkalimat staf."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HTTPException(400, 'Isian nota aksesoris tidak dikenali.')
    cara = str(raw.get('cara_bayar') or CARA_BAWAAN).strip()
    if cara not in CARA_BAYAR:
        raise HTTPException(400, 'Cara bayar nota aksesoris harus "Potong tagihan jahit" atau "Dibayar langsung".')
    rows = raw.get('harga') or []
    if isinstance(rows, dict):
        rows = [{'key': k, 'harga': v} for k, v in rows.items()]
    harga: dict = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = r.get('harga')
        if v is None or str(v).strip() == '':
            continue                                    # kosong = belum diisi (diperiksa per baris)
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Harga jual aksesoris '{r.get('nama') or r.get('material_id') or ''}' harus angka.")
        if x < 0:
            raise HTTPException(400, 'Harga jual aksesoris tidak boleh minus (isi 0 bila gratis).')
        for k in (r.get('key'), r.get('material_id')):
            if k:
                harga[str(k)] = round(x, 2)
    return {'cara_bayar': cara, 'harga': harga}


def harga_baris(row: dict, harga: dict) -> Optional[float]:
    for k in (row.get('key'), row.get('material_id')):
        if k and str(k) in (harga or {}):
            return harga[str(k)]
    return None


def belum_berharga(rows: list, harga: dict) -> list:
    """Nama aksesoris (qty serah > 0) yang harganya belum diisi. Murni."""
    out = []
    for r in rows or []:
        q = _f(r.get('qty_handover', r.get('qty_sent')))
        if q > 0 and harga_baris(r, harga) is None:
            out.append(r.get('name') or r.get('accessory_name') or r.get('code') or r.get('material_id') or '?')
    return out


def _baris(*, material_id, code, name, qty, satuan, harga, hpp_satuan, qty_base, usage_unit) -> dict:
    return {'material_id': material_id or '', 'sku': code or '', 'code': code or '', 'name': name or '',
            'qty': round(_f(qty), 4), 'unit': satuan or '', 'unit_label': satuan or '', 'harga': round(_f(harga), 2),
            'price': round(_f(harga), 2), 'jumlah': _rp0(_f(qty) * _f(harga)), 'amount': _rp0(_f(qty) * _f(harga)),
            'hpp_satuan': round(_f(hpp_satuan), 2), 'qty_base': round(_f(qty_base), 4), 'usage_unit': usage_unit or ''}


def baris_dari_hitungan(aksesoris: list, harga: dict) -> list:
    """Baris nota dari hitungan kiriman (`core.kirim_cmt.compute()['aksesoris']`). Murni.
    HPP per satuan serah = nilai stok per satuan dasar × isi satuan serah (acuan, tidak dijurnal)."""
    out = []
    for a in aksesoris or []:
        q = _f(a.get('qty_handover'))
        if q <= 0:
            continue
        h = harga_baris(a, harga)
        out.append(_baris(material_id=a.get('material_id'), code=a.get('code'), name=a.get('name'), qty=q,
                          satuan=a.get('handover_label') or a.get('handover_uom'), harga=h or 0,
                          hpp_satuan=_f(a.get('unit_cost')) * (_f(a.get('handover_factor')) or 1.0),
                          qty_base=a.get('qty_base'), usage_unit=a.get('usage_unit')))
    return out


def baris_kiriman(aksesoris: list) -> list:
    """Aksesoris yang SUDAH diserahkan (isi kiriman, `kirim_cmt.shipment_lines()['aksesoris']`) → baris isian nota
    (tanpa harga) untuk layar "Buat nota" di rincian kiriman. Murni."""
    out = []
    for a in aksesoris or []:
        q = _f(a.get('qty_handover'))
        if q <= 0:
            continue
        out.append({'key': a.get('material_id') or a.get('code'), 'material_id': a.get('material_id') or '',
                    'code': a.get('code') or '', 'name': a.get('name') or '', 'qty_handover': round(q, 4),
                    'handover_label': a.get('handover_label') or '', 'qty_base': a.get('qty_base'),
                    'usage_unit': a.get('usage_unit') or '', 'hpp_satuan': round(_f(a.get('value')) / q, 2) if q else 0.0,
                    'value': round(_f(a.get('value')), 2)})
    return out


def baris_dari_kiriman(aksesoris: list, harga: dict) -> list:
    return [_baris(material_id=r['material_id'], code=r['code'], name=r['name'], qty=r['qty_handover'],
                   satuan=r['handover_label'], harga=harga_baris(r, harga) or 0, hpp_satuan=r['hpp_satuan'],
                   qty_base=r['qty_base'], usage_unit=r['usage_unit']) for r in baris_kiriman(aksesoris)]


def status_bayar(total: float, terbayar: float) -> str:
    if terbayar <= _EPS:
        return 'issued'
    return 'paid' if total - terbayar <= _EPS + 0.5 else 'partial_paid'


# ══════════════════════════════ vendor & akun ══════════════════════════════
async def vendor_doc(db, vendor_id: Optional[str]) -> dict:
    from core.cmt_vendor_master import canonical_id
    if not vendor_id:
        return {}
    vid = await canonical_id(db, vendor_id) or vendor_id
    return await db.vendor_partners.find_one({'id': vid}, {'_id': 0}) or {}


async def berlaku(db, *, vendor_id: Optional[str], shipment: Optional[dict] = None) -> dict:
    """Apakah kiriman/vendor ini dibuatkan nota? → {berlaku, alasan, vendor}."""
    s = shipment or {}
    if s.get('opening'):
        return {'berlaku': False, 'alasan': 'Kiriman saldo awal cutoff — aksesorisnya diserahkan sebelum cutoff.',
                'vendor': {}}
    v = await vendor_doc(db, vendor_id or s.get('vendor_id'))
    if not v:
        return {'berlaku': False, 'alasan': 'Vendor CMT tidak ditemukan di master Vendor CMT.', 'vendor': {}}
    if v.get('owner_entity'):
        return {'berlaku': False, 'vendor': v,
                'alasan': f"{v.get('name') or 'Vendor ini'} adalah tim jahit CV sendiri — aksesoris tidak dijual."}
    return {'berlaku': True, 'alasan': '', 'vendor': v}


async def ensure_accounts(db) -> None:
    """1-1307 Piutang Vendor CMT & 4-9400 Penjualan Aksesoris ke CMT — dibuat bila belum ada (buku DA)."""
    for a in ACCOUNTS:
        acc = await db.rahaza_coa_accounts.find_one({'code': a['code']}, {'_id': 0, 'code': 1, 'active': 1})
        if acc:
            if acc.get('active') is False:
                await db.rahaza_coa_accounts.update_one({'code': a['code']}, {'$set': {'active': True, 'updated_at': _now()}})
            continue
        parent = a['parent_code'] if await db.rahaza_coa_accounts.find_one({'code': a['parent_code']}, {'_id': 1}) else None
        await db.rahaza_coa_accounts.insert_one({
            'id': _uid(), 'code': a['code'], 'name': a['name'], 'type': a['type'], 'parent_code': parent,
            'is_group': False, 'normal_balance': a['normal_balance'], 'active': True, 'entities': [DA],
            'flags': dict(a['flags']), 'cash_flow_group': a['cash_flow_group'],
            'created_at': _now(), 'updated_at': _now(), 'created_by': 'system', 'created_by_name': 'Nota aksesoris CMT'})


async def mapping(db) -> dict:
    from routes.rahaza_posting_profiles import get_mapping
    m = dict(DEFAULT_MAPPING)
    m.update({k: v for k, v in ((await get_mapping(db, PROFILE)) or {}).items() if v})
    return m


async def piutang_account(db, vendor: dict, control: str, user: dict) -> str:
    """Sub-ledger piutang per vendor CMT (1-1307-<kode>); gagal → akun kontrol (sama dengan pola hutang CMT)."""
    try:
        from routes.coa_auto import resolve_subledger_account
        code = await resolve_subledger_account(db, SUBLEDGER_TYPE, entity_id=vendor.get('id'),
                                               entity_name=vendor.get('name', ''), user=user)
        if code:
            return code
    except Exception:  # noqa: BLE001 — jatuh ke akun kontrol
        logger.exception('sub-ledger piutang vendor CMT %s gagal', vendor.get('id'))
    return control


async def _accounts(db, vendor: dict, user: dict) -> tuple:
    await ensure_accounts(db)
    m = await mapping(db)
    if not m.get('debit_ar') or not m.get('credit_other_income'):
        raise HTTPException(400, 'Akun piutang vendor CMT atau akun penjualan aksesoris belum diatur — '
                                 'lengkapi di Keuangan › Pemetaan akun otomatis (Nota aksesoris CMT).')
    return await piutang_account(db, vendor, m['debit_ar'], user), m['credit_other_income']


# ══════════════════════════════ baca ══════════════════════════════
async def nota_kiriman(db, shipment_id: str) -> Optional[dict]:
    return await db[COLL].find_one({'source_module': SOURCE, 'shipment_id': shipment_id,
                                    'status': {'$ne': 'cancelled'}}, {'_id': 0})


async def daftar(db, *, vendor_id: Optional[str] = None, status: Optional[str] = None, po_id: Optional[str] = None,
                 shipment_id: Optional[str] = None, limit: int = 500) -> list:
    q: dict = {'source_module': SOURCE}
    if vendor_id:
        q['vendor_id'] = vendor_id
    if po_id:
        q['po_id'] = po_id
    if shipment_id:
        q['shipment_id'] = shipment_id
    if status == 'terbuka':
        q['status'] = {'$in': list(OPEN)}
    elif status:
        q['status'] = status
    return await db[COLL].find(q, {'_id': 0}).sort('created_at', -1).limit(limit).to_list(limit)


def ringkas(doc: Optional[dict]) -> Optional[dict]:
    """Bentuk ringkas untuk rincian kiriman & portal vendor."""
    if not doc:
        return None
    return {k: doc.get(k) for k in (
        'id', 'invoice_number', 'issue_date', 'vendor_id', 'vendor_name', 'po_id', 'po_number', 'shipment_id',
        'shipment_number', 'items', 'total', 'paid_amount', 'balance', 'jumlah_dipotong', 'potongan', 'status',
        'cara_bayar', 'gl_je_number', 'potong_error', 'cancel_reason', 'created_by_name')} | {
        'status_label': STATUS_LABEL.get(doc.get('status'), doc.get('status') or ''),
        'cara_bayar_label': CARA_BAYAR.get(doc.get('cara_bayar'), ''),
        'dibayar_langsung': _rp0(_f(doc.get('paid_amount')) - _f(doc.get('jumlah_dipotong')))}


# ══════════════════════════════ terbitkan ══════════════════════════════
async def buat(db, *, shipment: dict, lines: list, cara_bayar: str, user: dict,
               tanggal: Optional[date] = None) -> Optional[dict]:
    """Terbitkan nota untuk satu kiriman (satu nota aktif per kiriman). Total 0 (semua gratis) → None.
    Jurnal: Dr Piutang Vendor CMT / Cr Penjualan Aksesoris ke CMT (buku DA). Cara potong → langsung memotong
    tagihan CMT yang terbuka; sisanya menunggu tagihan berikutnya."""
    from routes.rahaza_posting import _create_posted_je
    from utils.counters import gen_prefixed_number
    from utils.waktu import today_wib
    if cara_bayar not in CARA_BAYAR:
        raise HTTPException(400, 'Cara bayar nota aksesoris tidak dikenal.')
    ok = await berlaku(db, vendor_id=shipment.get('vendor_id'), shipment=shipment)
    if not ok['berlaku']:
        raise HTTPException(400, ok['alasan'])
    if await nota_kiriman(db, shipment['id']):
        raise HTTPException(400, f"Kiriman {shipment.get('shipment_number', '')} sudah punya nota aksesoris.")
    lines = [ln for ln in lines or [] if _f(ln.get('qty')) > 0]
    if not lines:
        return None                                     # kiriman tanpa aksesoris dari gudang
    total = _rp0(sum(_f(ln.get('jumlah')) for ln in lines))
    if total <= 0:
        await db.vendor_shipments.update_one({'id': shipment['id']}, {'$set': {
            'nota_aksesoris_status': 'gratis', 'updated_at': _now()}})
        return None
    vendor = ok['vendor']
    ar_code, rev_code = await _accounts(db, vendor, user)
    po = await db.production_pos.find_one({'id': shipment.get('po_id')}, {'_id': 0, 'po_number': 1, 'business_type': 1}) \
        if shipment.get('po_id') else None
    d = tanggal or today_wib()
    nid = _uid()
    nomor = await gen_prefixed_number(db, COLL, 'invoice_number', PREFIX, 5, config_key=NUMBER_KEY)
    po_number = shipment.get('po_number') or (po or {}).get('po_number') or ''
    memo = (f"Nota aksesoris {nomor} · {vendor.get('name', '')} · kiriman {shipment.get('shipment_number', '')}"
            f"{' · PO ' + po_number if po_number else ''}")
    je = await _create_posted_je(
        db, je_date=d, memo=memo, source_module=JE_MODULE, source_ref=f'nac:{nid}', user=user, entity=ISSUER,
        lines_raw=[{'account_code': ar_code, 'debit': total, 'credit': 0, 'description': memo},
                   {'account_code': rev_code, 'debit': 0, 'credit': total, 'description': memo}])
    if not je.get('ok'):
        raise HTTPException(400, f"Nota aksesoris tidak dibuat — jurnal gagal: {je.get('error')}")
    doc = {
        'id': nid, 'invoice_number': nomor, 'entity': ISSUER, 'source_module': SOURCE,
        'vendor_id': vendor['id'], 'vendor_name': vendor.get('name') or shipment.get('vendor_name') or '',
        'customer_id': None, 'customer_name': vendor.get('name') or shipment.get('vendor_name') or '',
        'shipment_id': shipment['id'], 'shipment_number': shipment.get('shipment_number') or '',
        'po_id': shipment.get('po_id') or '', 'po_number': po_number,
        'po_business_type': (po or {}).get('business_type') or shipment.get('business_type') or 'internal',
        # jatuh tempo 30 hari (sama dengan nota aksesoris antar CV): potong tagihan menunggu tagihan jahit lahir
        'issue_date': d.isoformat(), 'invoice_date': d.isoformat(), 'due_date': (d + timedelta(days=30)).isoformat(),
        'items': lines, 'subtotal': total, 'tax_pct': 0, 'tax_amount': 0, 'discount_amount': 0,
        'total': total, 'paid_amount': 0.0, 'balance': total, 'credited_amount': 0.0,
        'total_amount': total, 'amount_paid': 0.0, 'amount_due': total,
        'status': 'issued', 'cara_bayar': cara_bayar, 'potongan': [], 'jumlah_dipotong': 0.0,
        'gl_je_id': je.get('je_id'), 'gl_je_number': je.get('je_number'), 'gl_posted_at': _now(),
        'gl_ar_account_code': ar_code, 'revenue_account_code': rev_code,
        'notes': f"Nota aksesoris untuk kiriman {shipment.get('shipment_number', '')}"
                 f"{' · PO ' + po_number if po_number else ''} — {CARA_BAYAR[cara_bayar].lower()}.",
        'created_at': _now(), 'updated_at': _now(),
        'created_by': user.get('id', ''), 'created_by_name': user.get('name', ''),
    }
    await db[COLL].insert_one(dict(doc))
    await db.vendor_shipments.update_one({'id': shipment['id']}, {'$set': {
        'nota_aksesoris_id': nid, 'nota_aksesoris_number': nomor, 'nota_aksesoris_status': 'terbit',
        'updated_at': _now()}})
    if cara_bayar == 'potong_tagihan':
        try:
            doc = await potong(db, doc, user, po_first=shipment.get('po_id'), saat='terbit')
        except Exception:  # noqa: BLE001 — nota tetap sah; potongan dicoba lagi saat tagihan berikutnya lahir
            logger.exception('potong tagihan nota %s gagal', nomor)
    try:
        from auth import log_activity
        await log_activity(user.get('id', ''), user.get('name', ''), 'nota_aksesoris_cmt.create', 'Vendor Shipment',
                           f"{nomor} {vendor.get('name', '')} {fmt_rp(total)} ({CARA_BAYAR[cara_bayar]})")
    except Exception:  # noqa: BLE001 — jejak aktivitas tidak boleh menggagalkan nota yang sudah dijurnal
        logger.exception('jejak aktivitas nota %s gagal', nomor)
    return doc


# ══════════════════════════════ potong tagihan jahit ══════════════════════════════
async def _jurnal_potong(db, doc: dict, bill: dict, ent: str, x: float, pot_id: str, user: dict) -> dict:
    """Jurnal satu potongan. Tagihan di buku DA → satu jurnal; di buku CV Sukma → pasangan antar CV."""
    from core import denda_po
    from core import intercompany as ic
    from routes.rahaza_posting import _create_posted_je, _void_je_by_source
    from utils.waktu import today_wib
    d = today_wib()
    vendor = await vendor_doc(db, doc.get('vendor_id'))
    ap = await denda_po._ap_account(db, vendor or {'id': doc.get('vendor_id'), 'name': doc.get('vendor_name', '')}, user)
    if not ap:
        return {'ok': False, 'error': 'akun hutang vendor CMT belum ada'}
    ref = f'nacpot:{pot_id}'
    memo = (f"Potong tagihan {bill.get('payment_code', '')} dengan nota aksesoris {doc['invoice_number']} · "
            f"{doc.get('vendor_name', '')}")
    if ent == DA:
        r = await _create_posted_je(db, je_date=d, memo=memo, source_module=JE_OFFSET, source_ref=ref, user=user,
                                    entity=DA, lines_raw=[
                                        {'account_code': ap, 'debit': x, 'credit': 0, 'description': memo},
                                        {'account_code': doc['gl_ar_account_code'], 'debit': 0, 'credit': x,
                                         'description': memo}])
        return {'ok': bool(r.get('ok')), 'error': r.get('error'), 'je_numbers': [r.get('je_number')]}
    accs = await ic.ic_accounts(db, user)
    miss = ic.missing_accounts_message(accs, [(DA, 'ar'), (SMU, 'ap')])
    if miss:
        return {'ok': False, 'error': miss}
    for e in (DA, SMU):
        err = await ic.precheck_period(db, d, e)
        if err:
            return {'ok': False, 'error': err}
    memo_ic = f"{memo} · {ic.IC_LABEL}"
    r1 = await _create_posted_je(db, je_date=d, memo=memo_ic, source_module=JE_OFFSET, source_ref=ref, user=user,
                                 entity=SMU, labels=ic.ic_labels(DA, KIND_OFFSET, pot_id), lines_raw=[
                                     {'account_code': ap, 'debit': x, 'credit': 0, 'description': memo_ic},
                                     {'account_code': accs[SMU]['ap'], 'debit': 0, 'credit': x, 'description': memo_ic}])
    if not r1.get('ok'):
        return {'ok': False, 'error': f"jurnal CV Sukma: {r1.get('error')}"}
    r2 = await _create_posted_je(db, je_date=d, memo=memo_ic, source_module=JE_OFFSET, source_ref=ref, user=user,
                                 entity=DA, labels=ic.ic_labels(SMU, KIND_OFFSET, pot_id), lines_raw=[
                                     {'account_code': accs[DA]['ar'], 'debit': x, 'credit': 0, 'description': memo_ic},
                                     {'account_code': doc['gl_ar_account_code'], 'debit': 0, 'credit': x,
                                      'description': memo_ic}])
    if not r2.get('ok'):
        await _void_je_by_source(db, JE_OFFSET, ref, user, 'pasangan antar CV gagal', entity=SMU)
        return {'ok': False, 'error': f"jurnal CV Dewi Aditya: {r2.get('error')}"}
    return {'ok': True, 'je_numbers': [r1.get('je_number'), r2.get('je_number')], 'antar_cv': True}


async def _catat_bayar(db, nid: str, x: float, entry: dict) -> dict:
    """Tambah `paid_amount` nota sebesar potongan (penjaga konkurensi: nilai lama ikut di filter)."""
    for _ in range(3):
        cur = await db[COLL].find_one({'id': nid}, {'_id': 0})
        paid = _f(cur.get('paid_amount'))
        owed = _f(cur.get('total')) - _f(cur.get('credited_amount'))
        new_paid = _rp0(paid + x)
        bal = _rp0(max(0.0, owed - new_paid))
        res = await db[COLL].update_one({'id': nid, 'paid_amount': cur.get('paid_amount')}, {
            '$set': {'paid_amount': new_paid, 'balance': bal, 'amount_paid': new_paid, 'amount_due': bal,
                     'status': status_bayar(owed, new_paid), 'updated_at': _now(),
                     'jumlah_dipotong': _rp0(_f(cur.get('jumlah_dipotong')) + x)},
            '$push': {'potongan': entry}})
        if res.matched_count:
            return await db[COLL].find_one({'id': nid}, {'_id': 0})
    raise RuntimeError('nota berubah bersamaan — potongan dicatat ulang nanti')


async def potong(db, doc: dict, user: dict, *, po_first: Optional[str] = None, hanya: Optional[list] = None,
                 saat: str = 'terbit') -> dict:
    """Sisa nota memotong tagihan CMT vendor itu yang terbuka (PO kiriman dulu, lalu terlama; DA & CV Sukma).
    Alokasi & pengurangan tagihan memakai mesin denda (`core.denda_po`) — satu cara "potong bon"."""
    from core import denda_po
    from routes.dewi_maklon_finance import cmt_bill_entity
    doc = await db[COLL].find_one({'id': doc['id']}, {'_id': 0}) or doc
    if doc.get('status') not in OPEN:
        return doc
    sisa = _rp0(_f(doc.get('total')) - _f(doc.get('credited_amount')) - _f(doc.get('paid_amount')))
    if sisa <= _EPS:
        return doc
    tagihan = hanya if hanya is not None else await denda_po._tagihan_terbuka(db, doc['vendor_id'], None, po_first)
    by_id = {t['id']: t for t in tagihan}
    for bid, x in denda_po.alokasi(sisa, tagihan):
        x = _rp0(x)
        if x <= 0:
            continue
        bill = by_id[bid]
        ent = await cmt_bill_entity(db, bill)
        pot_id = _uid()
        j = await _jurnal_potong(db, doc, bill, ent, x, pot_id, user)
        if not j.get('ok'):
            await db[COLL].update_one({'id': doc['id']}, {'$set': {
                'potong_error': f"Tagihan {bill.get('payment_code', '')}: {j.get('error')}", 'updated_at': _now()}})
            logger.warning('potong tagihan %s dengan nota %s gagal: %s', bill.get('payment_code'),
                           doc.get('invoice_number'), j.get('error'))
            break
        await denda_po._kurangi_tagihan(db, bill, x, {'id': doc['id'], 'nomor': doc['invoice_number'],
                                                      'po_number': doc.get('po_number', '')},
                                        saat, user, jenis=denda_po.JENIS_NOTA_AKSESORIS)
        doc = await _catat_bayar(db, doc['id'], x, {
            'id': pot_id, 'dokumen': 'tagihan_cmt', 'tagihan_id': bid, 'nomor': bill.get('payment_code', ''),
            'po_number': bill.get('po_number', ''), 'entity': ent, 'jumlah': x, 'saat': saat,
            'je_numbers': [n for n in j.get('je_numbers') or [] if n], 'antar_cv': bool(j.get('antar_cv')),
            'at': _now(), 'by': user.get('name', '')})
        if doc.get('potong_error'):
            await db[COLL].update_one({'id': doc['id']}, {'$unset': {'potong_error': ''}})
            doc.pop('potong_error', None)
    return doc


async def potong_sekarang(db, nid: str, user: dict) -> dict:
    """Tombol "Potong dari tagihan jahit" (nota dibayar langsung yang ternyata dipotong, atau coba ulang)."""
    doc = await db[COLL].find_one({'id': nid, 'source_module': SOURCE}, {'_id': 0})
    if not doc:
        raise HTTPException(404, 'Nota aksesoris tidak ditemukan.')
    if doc.get('status') not in OPEN:
        raise HTTPException(400, 'Nota ini sudah lunas atau dibatalkan.')
    if doc.get('cara_bayar') != 'potong_tagihan':
        await db[COLL].update_one({'id': nid}, {'$set': {'cara_bayar': 'potong_tagihan', 'updated_at': _now()}})
        doc['cara_bayar'] = 'potong_tagihan'
    return await potong(db, doc, user, po_first=doc.get('po_id'), saat='manual')


async def potong_tagihan_baru(db, bill_id: str, user: dict) -> list:
    """Tagihan CMT baru lahir (lolos QC) → nota "potong tagihan" vendor itu yang masih bersisa memotongnya (terlama
    dulu, sesudah denda). Tidak pernah menggagalkan pematangan tagihan (pemanggil membungkus try)."""
    from core import denda_po
    from core.maklon_ledger import cmt_bill_payable
    bill = await db.dewi_cmt_payments.find_one({'id': bill_id}, {'_id': 0})
    if not bill or not bill.get('vendor_id') or bill.get('status') in denda_po.BILL_CLOSED:
        return []
    hasil = []
    async for n in db[COLL].find({'source_module': SOURCE, 'vendor_id': bill['vendor_id'], 'cara_bayar': 'potong_tagihan',
                                  'status': {'$in': list(OPEN)}}, {'_id': 0}).sort('created_at', 1).limit(100):
        bill = await db.dewi_cmt_payments.find_one({'id': bill_id}, {'_id': 0})
        bisa = cmt_bill_payable(bill)
        if bisa <= _EPS:
            break
        before = _f(n.get('paid_amount'))
        n2 = await potong(db, n, user, hanya=[{**bill, 'bisa': bisa}], saat='tagihan_baru')
        if _f(n2.get('paid_amount')) > before:
            hasil.append({'nomor': n2['invoice_number'], 'dipotong': _rp0(_f(n2.get('paid_amount')) - before)})
    return hasil


# ══════════════════════════════ batal ══════════════════════════════
async def batal(db, nid: str, user: dict, alasan: str = '') -> dict:
    from routes.rahaza_posting import _void_je_by_source
    doc = await db[COLL].find_one({'id': nid, 'source_module': SOURCE}, {'_id': 0})
    if not doc:
        raise HTTPException(404, 'Nota aksesoris tidak ditemukan.')
    if doc.get('status') == 'cancelled':
        return doc
    if _f(doc.get('paid_amount')) > 0 or doc.get('potongan'):
        raise HTTPException(400, 'Nota sudah dibayar atau sudah memotong tagihan CMT — tidak bisa dibatalkan.')
    alasan = str(alasan or '').strip()
    if len(alasan) < 3:
        raise HTTPException(400, 'Isi alasan pembatalan (mis. harga salah ketik).')
    res = await _void_je_by_source(db, JE_MODULE, f'nac:{nid}', user, f'Nota aksesoris dibatalkan: {alasan}', entity=ISSUER)
    if not res.get('ok'):
        raise HTTPException(400, f"Jurnal nota tidak bisa dibalik: {res.get('error') or res.get('reason')}")
    upd = {'status': 'cancelled', 'balance': 0.0, 'amount_due': 0.0, 'cancel_reason': alasan, 'cancelled_at': _now(),
           'cancelled_by': user.get('name', ''), 'updated_at': _now()}
    await db[COLL].update_one({'id': nid}, {'$set': upd})
    await db.vendor_shipments.update_one({'id': doc.get('shipment_id')}, {
        '$set': {'nota_aksesoris_status': 'batal', 'updated_at': _now()},
        '$unset': {'nota_aksesoris_id': '', 'nota_aksesoris_number': ''}})
    try:
        from auth import log_activity
        await log_activity(user.get('id', ''), user.get('name', ''), 'nota_aksesoris_cmt.cancel', 'Vendor Shipment',
                           f"{doc.get('invoice_number')} dibatalkan: {alasan}")
    except Exception:  # noqa: BLE001
        logger.exception('jejak aktivitas batal nota %s gagal', doc.get('invoice_number'))
    return {**doc, **upd}


# ══════════════════════════════ cetak ══════════════════════════════
def build_pdf(doc: dict, *, vendor: dict, profile: dict, template: dict, printed_by: str = '') -> bytes:
    """Nota aksesoris (PDF) — kop & tanda tangan dari template nota penjualan (Pengaturan › Dokumen)."""
    import io

    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    from core.pdf_template import footer_flowables, header_flowables, signature_flowables
    from routes.operations_pdf_helpers import CONTENT_W_PORTRAIT, _build_pdf
    from routes.rahaza_payment_receipt import terbilang
    from routes.sales_direct import _fmt_d

    styles = getSampleStyleSheet()
    body = ParagraphStyle('body', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#1f2937'))
    muted = ParagraphStyle('muted', parent=body, fontSize=8, leading=10, textColor=colors.HexColor('#64748b'))
    avail = CONTENT_W_PORTRAIT
    elems = header_flowables(template.get('header'), profile, 'NOTA AKSESORIS', avail=avail, info_pairs=[
        ('No. Nota', doc.get('invoice_number')), ('Tanggal', _fmt_d(doc.get('issue_date'))),
        ('Kiriman', doc.get('shipment_number') or '-'), ('PO', doc.get('po_number') or '-'),
        ('Pembayaran', f"{CARA_BAYAR.get(doc.get('cara_bayar'), '')} · {STATUS_LABEL.get(doc.get('status'), '')}")])
    addr = ' · '.join(x for x in (vendor.get('address'), vendor.get('phone')) if x)
    elems += [Paragraph(f"<b>Kepada:</b><br/>{vendor.get('name') or doc.get('vendor_name') or '-'}"
                        f"{'<br/><font size=8 color=#64748b>' + addr + '</font>' if addr else ''}", body), Spacer(1, 3 * mm)]
    rows = [['No', 'Aksesoris', 'Qty', 'Satuan', 'Harga', 'Jumlah']]
    for i, it in enumerate(doc.get('items') or [], start=1):
        rows.append([str(i), Paragraph(f"{it.get('name') or '-'}<br/><font size=7 color=#64748b>{it.get('code') or ''}</font>",
                                       body), fmt_num(it.get('qty')), it.get('unit_label') or '', fmt_rp(it.get('harga')),
                     fmt_rp(it.get('jumlah'))])
    rows.append(['', Paragraph('<b>Total</b>', body), '', '', '', fmt_rp(doc.get('total'))])
    t = Table(rows, colWidths=[avail * w for w in (0.06, 0.40, 0.10, 0.14, 0.14, 0.16)], repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')), ('FONTSIZE', (0, 0), (-1, -1), 8.5),
                           ('ALIGN', (2, 0), (2, -1), 'RIGHT'), ('ALIGN', (4, 0), (-1, -1), 'RIGHT'),
                           ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor('#e2e8f0')), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    elems += [t, Spacer(1, 3 * mm),
              Paragraph(f"<i>Terbilang: {terbilang(round(_f(doc.get('total')))).capitalize()} rupiah</i>", body)]
    dipotong, langsung = _f(doc.get('jumlah_dipotong')), _f(doc.get('paid_amount')) - _f(doc.get('jumlah_dipotong'))
    bayar = [f"dipotong dari tagihan jahit {fmt_rp(dipotong)}" if dipotong > 0 else '',
             f"dibayar langsung {fmt_rp(langsung)}" if langsung > 0 else '', f"sisa {fmt_rp(doc.get('balance'))}"]
    kalimat = ' · '.join(b for b in bayar if b)
    elems.append(Paragraph(kalimat[:1].upper() + kalimat[1:] + '.', body))
    for p in doc.get('potongan') or []:
        elems.append(Paragraph(f"• Tagihan {p.get('nomor') or ''}{' PO ' + p['po_number'] if p.get('po_number') else ''}: "
                               f"{fmt_rp(p.get('jumlah'))}", muted))
    if doc.get('status') == 'cancelled':
        elems.append(Paragraph(f"<b>DIBATALKAN</b> — {doc.get('cancel_reason') or ''}", body))
    elems.append(Spacer(1, 4 * mm))
    elems.extend(signature_flowables(template.get('signatures'), {
        'customer_name': vendor.get('name') or doc.get('vendor_name') or '', 'invoice_number': doc.get('invoice_number') or '',
        'note_number': doc.get('invoice_number') or '', 'printed_by': printed_by,
        'confirmed_by': doc.get('created_by_name') or ''}, avail=avail))
    elems.extend(footer_flowables(template.get('footer'), profile))
    return _build_pdf(io.BytesIO(), elems, page=template.get('page')).getvalue()
