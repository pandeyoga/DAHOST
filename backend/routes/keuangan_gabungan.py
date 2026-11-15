"""Keuangan › Hutang & Piutang — posisi per CMT / per klien maklon, bayar & terima GABUNGAN, tagihan klien gabungan.

16 Nov 2026 (owner, "berapa pencairannya"): yang boleh DIBAYAR ke CMT = yang sudah disetor lolos QC; yang boleh
DITAGIH ke klien = yang sudah dikirim; nilai PO tetap tampil sebagai komitmen. Pintu tipis — hitungan & aturan ada
di `core.posisi_cmt`, `core.tagihan_klien`, `core.alokasi_bayar`. Tidak ada jurnal baru: hutang CMT tetap lahir saat
setoran lolos QC, pendapatan klien saat barang dikirim; bayar/terima memakai logika pembayaran yang sudah ada.

Izin (satu katalog, `data/module_catalog.py`):
  * baca posisi, bukti, PDF → gerbang modul Maklon › Piutang Klien (Lihat / Unduh); dari menu Keuangan › Hutang dan
    Keuangan › Piutang ikut terbuka otomatis (peta menu → layanan);
  * bayar CMT gabungan     → Keuangan › Pembayaran & Pencairan Uang › Setujui (ENDPOINT_RULES — sama dengan Bayar satu
    tagihan CMT);
  * buat / batal tagihan klien, terima pembayaran klien gabungan → Tambah pada Maklon › Piutang Klien atau
    Keuangan › Piutang (sama dengan catat pembayaran klien per PO).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import require_auth, serialize_doc
from core import alokasi_bayar as ab
from database import get_db
from routes.production_rbac import deny_external_dep

router = APIRouter(prefix='/api/dewi/maklon/finance', tags=['Keuangan-Gabungan'],
                   dependencies=[Depends(deny_external_dep)])

CENTANG_BAYAR = 'mod.fin_pencairan.approve'


class BarisAlokasi(BaseModel):
    id: str
    jumlah: float = Field(..., ge=0)


class BayarCmtGabunganIn(BaseModel):
    vendor_id: str
    amount: float = Field(..., gt=0)
    cash_account_id: str
    payment_date: Optional[str] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    counter_cash_account_id: Optional[str] = None
    alokasi: List[BarisAlokasi] = Field(default_factory=list)


class TagihanKlienIn(BaseModel):
    client_id: str
    keys: List[str] = Field(default_factory=list)
    bill_date: Optional[str] = None
    notes: Optional[str] = None


class BatalIn(BaseModel):
    reason: str = Field(..., min_length=3)


class TerimaKlienGabunganIn(BaseModel):
    client_id: str
    amount: float = Field(..., gt=0)
    cash_account_id: str
    payment_date: Optional[str] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None
    alokasi: List[BarisAlokasi] = Field(default_factory=list)


def _wajib_bayar(user: dict) -> None:
    from core.authz import wajib_centang
    wajib_centang(user, CENTANG_BAYAR, apa='membayar tagihan CMT')


def _wajib_piutang(user: dict) -> None:
    from routes.dewi_maklon_billing import _require_payment_role
    _require_payment_role(user, 'create')


def _alokasi(rows) -> list:
    return [{'id': r.id, 'jumlah': r.jumlah} for r in rows or []]


async def _rekening_sesuai_cv(db, request: Request, account_id: str) -> None:
    """Rekening yang dipilih harus milik CV yang sedang dipilih layar (bila layar mengirim pilihan CV)."""
    from core.entities import ALL, explicit_entity, validate_cash_account_owner
    ent = explicit_entity(request) if request is not None else None
    if ent and ent != ALL:
        await validate_cash_account_owner(db, account_id, ent, what='Pembayaran')


async def _pdf_ctx(db, entity: str):
    from core import pdf_template
    return await pdf_template.resolve(db, 'sales-note'), await pdf_template.company_profile(db, entity)


def _pdf(content: bytes, fname: str) -> Response:
    return Response(content=content, media_type='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="{fname}"'})


async def _bukti(db, bid: str, jenis: str) -> dict:
    d = await db[ab.COLL].find_one({'id': bid, 'jenis': jenis}, {'_id': 0})
    if not d:
        raise HTTPException(404, 'Bukti pembayaran tidak ditemukan.')
    return d


# ══════════════════════════════════════════════════════════════════════════════
# CMT
# ══════════════════════════════════════════════════════════════════════════════
@router.get('/cmt-posisi')
async def cmt_posisi(request: Request, vendor_id: Optional[str] = None):
    """Posisi per CMT & per PO: komitmen (nilai PO × upah), sudah setor lolos QC, dibayar, ditahan, boleh dibayar."""
    await require_auth(request)
    from core import posisi_cmt
    from core.entities import entity_from_request
    db = get_db()
    ent = entity_from_request(request, allow_all=True, default=None)
    return serialize_doc(await posisi_cmt.posisi_cmt(db, entity=ent, vendor_id=vendor_id))


@router.post('/cmt-bayar-gabungan')
async def cmt_bayar_gabungan(payload: BayarCmtGabunganIn, request: Request):
    """Satu pembayaran ke SATU CMT untuk beberapa tagihannya (satu nomor bukti)."""
    user = await require_auth(request)
    _wajib_bayar(user)
    from core import posisi_cmt
    db = get_db()
    await _rekening_sesuai_cv(db, request, payload.cash_account_id)
    try:
        out = await posisi_cmt.bayar_gabungan(
            db, vendor_id=payload.vendor_id, amount=payload.amount, cash_account_id=payload.cash_account_id,
            payment_date=payload.payment_date, alokasi=_alokasi(payload.alokasi), user=user,
            notes=payload.notes or '', reference_no=payload.reference_no or '',
            counter_cash_account_id=payload.counter_cash_account_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return serialize_doc(out)


@router.get('/cmt-bayar-gabungan')
async def cmt_bayar_gabungan_daftar(request: Request, vendor_id: Optional[str] = None):
    await require_auth(request)
    from core import posisi_cmt
    db = get_db()
    return {'items': serialize_doc(await posisi_cmt.daftar_bukti(db, ab.JENIS_BAYAR_CMT, vendor_id))}


@router.get('/cmt-bayar-gabungan/{bid}')
async def cmt_bayar_gabungan_rincian(bid: str, request: Request):
    await require_auth(request)
    return serialize_doc(await _bukti(get_db(), bid, ab.JENIS_BAYAR_CMT))


@router.get('/cmt-bayar-gabungan/{bid}/pdf')
async def cmt_bayar_gabungan_pdf(bid: str, request: Request):
    user = await require_auth(request)
    from utils.bukti_gabungan_pdf import _rp, _tgl, build_bukti_pdf
    db = get_db()
    d = await _bukti(db, bid, ab.JENIS_BAYAR_CMT)
    rows = [[str(i), a.get('nomor') or '-', a.get('po_number') or '-', _tgl(a.get('tanggal_tagihan')),
             _rp(a.get('nilai_tagihan')), _rp(a.get('jumlah')), _rp(a.get('sisa_tagihan')), a.get('je_number') or '-']
            for i, a in enumerate(d.get('alokasi') or [], start=1)]
    rows.append(['', 'Jumlah', '', '', '', _rp(d.get('amount')), '', ''])
    template, profile = await _pdf_ctx(db, d.get('entity') or 'DA')
    pdf = build_bukti_pdf(judul='BUKTI PEMBAYARAN CMT', doc=d, pihak_label='Dibayar kepada',
                          kolom=['No', 'Tagihan', 'PO', 'Tgl tagihan', 'Nilai tagihan', 'Dibayar', 'Sisa', 'Jurnal'],
                          baris=rows, kanan=[4, 5, 6],
                          ringkas=[('Untuk', f"{len(d.get('alokasi') or [])} tagihan jasa jahit")],
                          template=template, profile=profile, printed_by=user.get('name') or '')
    return _pdf(pdf, f"Bukti_{d.get('bukti_number')}.pdf")


# ══════════════════════════════════════════════════════════════════════════════
# KLIEN MAKLON
# ══════════════════════════════════════════════════════════════════════════════
@router.get('/klien-posisi')
async def klien_posisi(request: Request, client_id: Optional[str] = None):
    """Posisi per klien maklon & per PO: komitmen, sudah dikirim, sudah ditagih, dibayar, boleh ditagih, sisa piutang,
    uang muka; kiriman yang belum ditagih; tagihan gabungan beserta status bayarnya."""
    await require_auth(request)
    from core import tagihan_klien
    from core.entities import entity_from_request
    db = get_db()
    ent = entity_from_request(request, allow_all=True, default=None)
    return serialize_doc(await tagihan_klien.posisi_klien(db, client_id=client_id, entity=ent))


@router.post('/tagihan-klien')
async def tagihan_klien_buat(payload: TagihanKlienIn, request: Request):
    """Satu tagihan bernomor untuk kiriman pilihan (boleh lintas PO satu klien). Dokumen saja — tanpa jurnal."""
    user = await require_auth(request)
    _wajib_piutang(user)
    from core import tagihan_klien
    try:
        out = await tagihan_klien.buat_tagihan(get_db(), client_id=payload.client_id, keys=payload.keys,
                                               bill_date=payload.bill_date, notes=payload.notes or '', user=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return serialize_doc(out)


@router.get('/tagihan-klien/{bid}')
async def tagihan_klien_rincian(bid: str, request: Request):
    await require_auth(request)
    from core import tagihan_klien
    try:
        return serialize_doc(await tagihan_klien.rincian_tagihan(get_db(), bid))
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.post('/tagihan-klien/{bid}/batal')
async def tagihan_klien_batal(bid: str, payload: BatalIn, request: Request):
    """Batalkan tagihan yang belum ada pembayarannya (kirimannya bisa ditagih ulang)."""
    user = await require_auth(request)
    _wajib_piutang(user)
    from core import tagihan_klien
    try:
        return serialize_doc(await tagihan_klien.batal_tagihan(get_db(), bid, reason=payload.reason, user=user))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get('/tagihan-klien/{bid}/pdf')
async def tagihan_klien_pdf(bid: str, request: Request):
    """Faktur CETAK tagihan gabungan — gaya faktur piutang maklon yang sama, tidak menulis apa pun."""
    await require_auth(request)
    from core import tagihan_klien
    from core.entities import SMU, company_settings_doc
    from utils.invoice_pdf import build_invoice_pdf
    from utils.pdf_common import get_company_profile, get_doc_settings
    db = get_db()
    try:
        t = await tagihan_klien.rincian_tagihan(db, bid)
    except LookupError as e:
        raise HTTPException(404, str(e))
    inv = tagihan_klien.isi_pdf_tagihan(t)
    cl = await db.dewi_maklon_clients.find_one({'id': t.get('client_id')}, {'_id': 0}) or {'name': t.get('client_name')}
    co = await company_settings_doc(db, SMU)
    ds = await get_doc_settings(db, 'invoice-maklon')
    pdf = build_invoice_pdf(invoice=inv, client=cl, company=co, template=(ds or {}).get('_template'),
                            profile=await get_company_profile(db, SMU))
    return _pdf(pdf, f"Tagihan_{t.get('bill_number')}.pdf")


@router.post('/klien-terima-gabungan')
async def klien_terima_gabungan(payload: TerimaKlienGabunganIn, request: Request):
    """Satu penerimaan dari SATU klien untuk beberapa PO (satu nomor bukti); kelebihan = uang muka klien."""
    user = await require_auth(request)
    _wajib_piutang(user)
    from core import tagihan_klien
    db = get_db()
    await _rekening_sesuai_cv(db, request, payload.cash_account_id)
    try:
        out = await tagihan_klien.terima_gabungan(
            db, client_id=payload.client_id, amount=payload.amount, cash_account_id=payload.cash_account_id,
            payment_date=payload.payment_date, alokasi=_alokasi(payload.alokasi), user=user,
            notes=payload.notes or '', reference_no=payload.reference_no or '')
    except ValueError as e:
        raise HTTPException(400, str(e))
    return serialize_doc(out)


@router.get('/klien-terima-gabungan')
async def klien_terima_gabungan_daftar(request: Request, client_id: Optional[str] = None):
    await require_auth(request)
    from core import posisi_cmt
    return {'items': serialize_doc(await posisi_cmt.daftar_bukti(get_db(), ab.JENIS_TERIMA_KLIEN, client_id))}


@router.get('/klien-terima-gabungan/{bid}')
async def klien_terima_gabungan_rincian(bid: str, request: Request):
    await require_auth(request)
    return serialize_doc(await _bukti(get_db(), bid, ab.JENIS_TERIMA_KLIEN))


@router.get('/klien-terima-gabungan/{bid}/pdf')
async def klien_terima_gabungan_pdf(bid: str, request: Request):
    user = await require_auth(request)
    from utils.bukti_gabungan_pdf import _rp, build_bukti_pdf
    db = get_db()
    d = await _bukti(db, bid, ab.JENIS_TERIMA_KLIEN)
    rows = [[str(i), a.get('po_number') or '-', ', '.join(a.get('tagihan') or []) or '-', _rp(a.get('ke_piutang')),
             _rp(a.get('ke_uang_muka')), _rp(a.get('jumlah')), a.get('je_number') or '-']
            for i, a in enumerate(d.get('alokasi') or [], start=1)]
    rows.append(['', 'Jumlah', '', _rp(d.get('ke_piutang')), _rp(d.get('ke_uang_muka')), _rp(d.get('amount')), ''])
    ringkas = [('Untuk', f"{len(d.get('alokasi') or [])} PO maklon")]
    if float(d.get('ke_uang_muka') or 0) > 0.5:
        ringkas.append(('Uang muka', f"{_rp(d.get('ke_uang_muka'))} — dipakai otomatis saat PO-nya mengirim barang"))
    template, profile = await _pdf_ctx(db, d.get('entity') or 'SMU')
    pdf = build_bukti_pdf(judul='BUKTI PENERIMAAN', doc=d, pihak_label='Diterima dari',
                          kolom=['No', 'PO', 'Tagihan', 'Ke piutang', 'Uang muka', 'Jumlah', 'Jurnal'],
                          baris=rows, kanan=[3, 4, 5], ringkas=ringkas, template=template, profile=profile,
                          printed_by=user.get('name') or '')
    return _pdf(pdf, f"Bukti_{d.get('bukti_number')}.pdf")
