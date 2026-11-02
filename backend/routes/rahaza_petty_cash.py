"""
Kas Kecil / Petty Cash (Imprest Fund) — Phase 6B
CV. Dewi Aditya ERP

Konsep:
  - Satu atau lebih fund (dana kas kecil) dengan saldo bergerak
  - Transaksi: expense, advance, return, replenish, close
  - Auto-posting GL untuk setiap transaksi
  - Hanya Finance/Admin yang bisa buat fund & replenish; Kasir input expense

Collections:
  rahaza_petty_cash_funds  — master fund
  rahaza_petty_cash_txns   — transaksi

Prefix: /api/finance/petty-cash

2026-11-02 (keputusan owner K26 — uang muka kas kecil):
  - Tipe "advance" = UANG MUKA atas nama KARYAWAN (wajib pilih karyawan, bukan teks bebas):
      Dr 1-1610 Uang Muka Karyawan (peran petty_cash_expense.debit_employee_advance) / Cr Kas Kecil.
  - Dokumen "Pertanggungjawaban" (txn_type 'advance_settlement', POST /advances/{id}/settle):
      nota per kategori → Dr beban kategori ; sisa uang kembali → Dr Kas Kecil ; Cr 1-1610.
  - Daftar uang muka terbuka per karyawan (GET /advances) + batas hari pertanggungjawaban per dana
    (`advance_settle_days`, 0 = belum diatur).
  - Akun beban pengeluaran kas kecil TIDAK lagi bawaan 6-2400 ATK: dari pemetaan kategori
    (employee_expense_gl_mappings); bila kategori tidak terpetakan, akun WAJIB dipilih.
  - Tipe "return" lama hanya untuk uang muka LAMA (tanpa karyawan, dulu langsung dibebankan).
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone, date, timedelta
from database import get_db
from auth import require_auth, serialize_doc, log_activity
from routes.rahaza_posting import (
    _create_posted_je, _find_existing_je, get_mapping
)
import logging
import uuid

log = logging.getLogger(__name__)
router = APIRouter(prefix='/api/finance/petty-cash', tags=['Petty-Cash'])

# RC-FLOW-kasbank-1 FIX: role Finance kanonik di sistem = 'accounting'/'staff_keuangan'
# (bukan 'finance'). Sebelumnya akun finance@dewiaditya.id (role 'accounting') DITOLAK 403
# saat membuat/replenish/close dana kas kecil. Selaraskan dgn employee_expense_claims.py.
from core.roles import FINANCE_ROLES  # FIN-02: satu sumber peran keuangan
from routes.rahaza_payroll_shared import _today_wib  # 2026-11-02: tanggal bisnis WIB
ALL_ROLES     = tuple(FINANCE_ROLES) + ('cashier', 'staff')

TXN_TYPES = ('expense', 'advance', 'return', 'replenish', 'opening')


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc).isoformat()


def _ser(doc: dict) -> dict:
    return serialize_doc(doc) if doc else {}


# ── Pydantic ────────────────────────────────────────────────────────────────

class FundCreate(BaseModel):
    name: str = Field(..., min_length=1)
    custodian_name: Optional[str] = None
    opening_balance: float = Field(0.0, ge=0)
    bank_account_code: Optional[str] = '1-1201'
    notes: Optional[str] = None


class TxnCreate(BaseModel):
    fund_id: str
    txn_type: str = Field(...)
    amount: float = Field(..., gt=0)
    txn_date: Optional[str] = None   # ISO date, default today
    category: Optional[str] = None   # expense category
    payee:    Optional[str] = None
    memo:     Optional[str] = None
    bank_account_code: Optional[str] = None  # untuk replenish: source bank
    employee_id: Optional[str] = None   # 2026-11-02 (K26): WAJIB untuk advance (uang muka atas nama karyawan)
    account_code: Optional[str] = None  # 2026-11-02 (K26): akun beban bila kategori tidak terpetakan


class SettleItem(BaseModel):
    category: Optional[str] = None
    account_code: Optional[str] = None
    amount: float = Field(..., gt=0)
    memo: Optional[str] = None


class AdvanceSettleIn(BaseModel):
    """Pertanggungjawaban uang muka: nota per kategori + sisa uang yang dikembalikan ke kas kecil."""
    items: List[SettleItem] = Field(default_factory=list)
    returned_amount: float = Field(0.0, ge=0)
    settle_date: Optional[str] = None
    memo: Optional[str] = None


class FundSettingsIn(BaseModel):
    advance_settle_days: int = Field(0, ge=0, le=365)   # 0 = belum diatur (tanpa tanda terlambat)


class ReplenishIn(BaseModel):
    amount: float = Field(..., gt=0)
    # 2026-11-02: kosong ⇒ rekening sumber dana itu sendiri (bukan 1-1201 tetap); tetap divalidasi.
    bank_account_code: Optional[str] = None
    memo: Optional[str] = None
    txn_date: Optional[str] = None


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get_fund_or_404(db, fund_id: str) -> dict:
    fund = await db.rahaza_petty_cash_funds.find_one({'id': fund_id}, {'_id': 0})
    if not fund:
        raise HTTPException(404, 'Dana kas kecil tidak ditemukan.')
    return fund


async def _petty_cash_account_code(db) -> str:
    """Akun GL dana kas kecil (Profil Posting `petty_cash_replenish.debit_petty_cash`, bawaan 1-1101)."""
    return (await get_mapping(db, 'petty_cash_replenish')).get('debit_petty_cash') or '1-1101'


async def _resolve_source_account(db, code: Optional[str]) -> str:
    """2026-11-02 (audit kas kecil): rekening SUMBER pengisian dana wajib akun kas/bank postable
    yang ada di bagan akun, dan BUKAN akun kas kecil itu sendiri. Dulu layar menawarkan
    'Bank BRI (1-1203)' (tidak ada di COA → jurnal gagal, saldo dana tetap naik) dan
    'Kas (1-1101)' (= kas kecil → jurnal Dr 1-1101 / Cr 1-1101, tidak ada uang yang pindah).
    Pemeriksaan kas/bank memakai satu pintu SDM↔Keuangan (`resolve_payment_account`)."""
    from routes.rahaza_payroll_shared import resolve_payment_account
    acc = await resolve_payment_account(db, gl_code=code, purpose='Kas kecil — rekening sumber')
    petty = await _petty_cash_account_code(db)
    if acc['gl_code'] == petty:
        raise HTTPException(400, f"Kas kecil — rekening sumber: akun '{petty}' adalah akun dana kas kecil "
                                 "itu sendiri. Pilih rekening bank/kas lain sebagai sumber dana.")
    return acc['gl_code']


EMPLOYEE_ADVANCE_DEFAULT = '1-1610'   # Uang Muka Karyawan (sama dgn uang muka dinas)


async def _employee_advance_code(db) -> str:
    """Akun uang muka karyawan (Profil Posting `petty_cash_expense.debit_employee_advance`, bawaan 1-1610)."""
    return (await get_mapping(db, 'petty_cash_expense')).get('debit_employee_advance') or EMPLOYEE_ADVANCE_DEFAULT


async def _resolve_expense_account(db, category: Optional[str], account_code: Optional[str],
                                   purpose: str = 'Kas kecil') -> dict:
    """2026-11-02 (K26): akun beban kas kecil = pemetaan kategori (employee_expense_gl_mappings);
    bila kategori tidak terpetakan → akun WAJIB dipilih pengguna. Tidak ada lagi bawaan 6-2400 ATK.
    Akun dipilih harus postable, aktif, dan BUKAN kas/bank/kas kecil/uang muka."""
    code, source = None, None
    cat = (category or '').strip()
    if cat:
        m = await db.employee_expense_gl_mappings.find_one({'category': cat, 'is_active': True},
                                                          {'_id': 0, 'gl_account_code': 1})
        if m and m.get('gl_account_code'):
            code, source = m['gl_account_code'], 'mapping'
    if not code and (account_code or '').strip():
        code, source = account_code.strip(), 'manual'
    if not code:
        raise HTTPException(400, (f"{purpose}: kategori '{cat or '-'}' belum dipetakan ke akun beban "
                                  "(Master Akuntansi › Pemetaan GL) — pilih akun beban."))
    coa = await db.rahaza_coa_accounts.find_one({'code': code, 'active': True}, {'_id': 0, 'name': 1, 'is_group': 1})
    if not coa:
        raise HTTPException(400, f"{purpose}: akun '{code}' tidak ditemukan atau tidak aktif.")
    if coa.get('is_group'):
        raise HTTPException(400, f"{purpose}: akun '{code}' adalah akun header — pilih akun rinci.")
    from core.fin_statements import cash_account_codes
    blocked = set(await cash_account_codes(db)) | {await _petty_cash_account_code(db), await _employee_advance_code(db)}
    if code in blocked:
        raise HTTPException(400, f"{purpose}: akun '{code} {coa.get('name', '')}' bukan akun beban.")
    return {'code': code, 'name': coa.get('name') or code, 'source': source}


async def _post_petty_cash_txn(db, txn: dict, user: dict) -> dict:
    """
    Auto-post JE untuk transaksi petty cash.
    - expense:            Dr beban (pemetaan kategori / akun dipilih) / Cr Petty Cash
    - advance (karyawan): Dr 1-1610 Uang Muka Karyawan / Cr Petty Cash            (K26, 2026-11-02)
    - advance_settlement: Dr beban per nota + Dr Petty Cash (sisa kembali) / Cr 1-1610   (K26)
    - replenish:          Dr Petty Cash / Cr Bank
    - return (lama):      Dr Petty Cash / Cr Expense reversal
    - opening:            Dr Petty Cash / Cr Bank (initial funding)
    """
    txn_id = txn['id']
    txn_type = txn['txn_type']
    amount = float(txn['amount'])
    source_ref = f'pctxn:{txn_id}'

    # 2026-11-02: cek idempoten memakai source_module yang BENAR-BENAR dipakai saat posting
    # (dulu 'petty_cash_advance'/'petty_cash_return' yang tidak pernah ditulis → cek tak berguna).
    _mod = 'petty_cash_replenish' if txn_type in ('replenish', 'opening', 'close_return') else 'petty_cash_expense'
    existing = await _find_existing_je(db, _mod, source_ref)
    if existing:
        return {'ok': True, 'je_id': existing['id'], 'je_number': existing['je_number'], 'already_posted': True}

    try:
        je_date = date.fromisoformat((txn.get('txn_date') or str(date.today()))[:10])
    except Exception:
        je_date = date.today()

    # FIN-05(a): akun kas kecil dari Profil Posting (bawaan 1-1101), bukan konstanta legacy '1-110'
    _pc_map = await get_mapping(db, 'petty_cash_replenish')
    petty_cash_code = _pc_map.get('debit_petty_cash') or '1-1101'

    if txn_type == 'advance' and txn.get('employee_id'):
        adv_code = txn.get('advance_account_code') or await _employee_advance_code(db)
        memo = f"Uang Muka Kas Kecil — {txn.get('employee_name') or txn.get('payee') or ''}: {txn.get('memo') or ''}".strip(': ')
        lines = [
            {'account_code': adv_code, 'debit': round(amount, 2), 'credit': 0, 'description': memo},
            {'account_code': petty_cash_code, 'debit': 0, 'credit': round(amount, 2), 'description': memo},
        ]
        event_type = 'petty_cash_expense'

    elif txn_type == 'advance_settlement':
        adv_code = txn.get('advance_account_code') or await _employee_advance_code(db)
        who = txn.get('employee_name') or ''
        memo = f"Pertanggungjawaban uang muka {txn.get('advance_ref') or ''} — {who}".strip()
        lines = [{'account_code': it['account_code'], 'debit': round(float(it['amount']), 2), 'credit': 0,
                  'description': f"{memo}: {it.get('category') or it.get('memo') or 'nota'}"}
                 for it in (txn.get('items') or [])]
        ret = round(float(txn.get('returned_amount') or 0), 2)
        if ret > 0:
            lines.append({'account_code': petty_cash_code, 'debit': ret, 'credit': 0, 'description': f"{memo}: sisa dikembalikan"})
        lines.append({'account_code': adv_code, 'debit': 0, 'credit': round(amount, 2), 'description': memo})
        event_type = 'petty_cash_expense'

    elif txn_type == 'expense' and txn.get('gl_debit_code'):
        memo = f"Kas Kecil Expense: {txn.get('memo') or txn.get('payee') or txn.get('category') or 'Pengeluaran'}"
        lines = [
            {'account_code': txn['gl_debit_code'], 'debit': round(amount, 2), 'credit': 0, 'description': memo},
            {'account_code': petty_cash_code, 'debit': 0, 'credit': round(amount, 2), 'description': memo},
        ]
        event_type = 'petty_cash_expense'

    elif txn_type in ('expense', 'advance'):
        # Transaksi LAMA (sebelum 2026-11-02) tanpa akun tersimpan — hanya untuk retry-posting data lama.
        # Ambil expense account dari GL mapping atau posting profile
        mapping = await get_mapping(db, 'petty_cash_expense')
        # 2026-11-02 (S2-H butir 9): cadangan 6-2200 (Listrik & Air — KELIRU) DIHAPUS. Akun dari
        # pemetaan kategori, lalu peran profil; keduanya kosong ⇒ ditolak dengan pesan jelas.
        expense_code = (mapping.get('debit_expense_default') or '').strip()
        # Cek apakah ada kategori yang dipetakan ke GL
        category = txn.get('category')
        if category:
            cat_map = await db.employee_expense_gl_mappings.find_one(
                {'category': category, 'is_active': True}, {'_id': 0, 'gl_account_code': 1}
            )
            if cat_map:
                expense_code = cat_map['gl_account_code']
        if not expense_code:
            return {'ok': False, 'error': (
                "Akun beban kas kecil belum ditentukan: kategori "
                f"'{category or '-'}' belum dipetakan di Pemetaan GL dan peran Profil Posting "
                "'petty_cash_expense.debit_expense_default' kosong. Isi salah satunya lalu posting ulang.")}
        memo = f"Kas Kecil {txn_type.capitalize()}: {txn.get('memo') or txn.get('payee') or category or 'Pengeluaran'}"
        lines = [
            {'account_code': expense_code, 'debit': round(amount, 2), 'credit': 0,
             'description': memo},
            {'account_code': petty_cash_code, 'debit': 0, 'credit': round(amount, 2),
             'description': memo},
        ]
        event_type = 'petty_cash_expense'

    elif txn_type == 'close_return':
        # FIN-05(b): penutupan dana → sisa kas kecil kembali ke bank: Dr Bank / Cr Kas Kecil
        mapping = await get_mapping(db, 'petty_cash_replenish')
        bank_code = txn.get('bank_account_code') or mapping.get('credit_bank_default', '1-1201')
        memo = txn.get('memo') or 'Penutupan Kas Kecil - sisa saldo ke bank'
        lines = [
            {'account_code': bank_code, 'debit': round(amount, 2), 'credit': 0, 'description': memo},
            {'account_code': petty_cash_code, 'debit': 0, 'credit': round(amount, 2), 'description': memo},
        ]
        event_type = 'petty_cash_replenish'

    elif txn_type == 'return':
        # Pengembalian uang muka → Dr Petty Cash / Cr Expense/Advance
        mapping = await get_mapping(db, 'petty_cash_expense')
        # 2026-11-02 (S2-H butir 9): tanpa cadangan 6-2200 — peran kosong ⇒ ditolak dengan pesan jelas
        expense_code = (mapping.get('debit_expense_default') or '').strip()
        if not expense_code:
            return {'ok': False, 'error': (
                "Peran Profil Posting 'petty_cash_expense.debit_expense_default' (beban kas kecil transaksi "
                "lama) kosong — isi di Profil Posting lalu posting ulang pengembalian ini.")}
        memo = f"Return Kas Kecil: {txn.get('memo') or 'Pengembalian'}"
        lines = [
            {'account_code': petty_cash_code, 'debit': round(amount, 2), 'credit': 0,
             'description': memo},
            {'account_code': expense_code, 'debit': 0, 'credit': round(amount, 2),
             'description': memo},
        ]
        event_type = 'petty_cash_expense'  # reuse event_type

    elif txn_type in ('replenish', 'opening'):
        mapping = await get_mapping(db, 'petty_cash_replenish')
        bank_code = txn.get('bank_account_code') or mapping.get('credit_bank_default', '1-1201')
        memo = txn.get('memo') or ('Pengisian Awal Kas Kecil' if txn_type == 'opening' else 'Replenishment Kas Kecil')
        lines = [
            {'account_code': petty_cash_code, 'debit': round(amount, 2), 'credit': 0,
             'description': memo},
            {'account_code': bank_code, 'debit': 0, 'credit': round(amount, 2),
             'description': memo},
        ]
        event_type = 'petty_cash_replenish'
    else:
        return {'ok': False, 'error': f'Tipe transaksi tidak dikenal: {txn_type}'}

    result = await _create_posted_je(db, je_date, memo, event_type, source_ref, lines, user)
    # Persist result on txn
    if result.get('ok'):
        upd = {'gl_posted': True, 'gl_je_id': result.get('je_id'), 'gl_je_number': result.get('je_number'), 'gl_error': None}
    else:
        upd = {'gl_posted': False, 'gl_je_id': None, 'gl_error': result.get('error')}
    await db.rahaza_petty_cash_txns.update_one({'id': txn_id}, {'$set': upd})
    return result


# ── Fund Endpoints ──────────────────────────────────────────────────────────

@router.get('/funds')
async def list_funds(user: dict = Depends(require_auth)):
    db = get_db()
    funds = await db.rahaza_petty_cash_funds.find({}, {'_id': 0}).sort('created_at', -1).to_list(100)
    # 2026-11-02: akun dana kas kecil dikirim agar layar tidak menawarkannya sebagai rekening sumber.
    return {'items': [_ser(f) for f in funds], 'total': len(funds),
            'petty_cash_account_code': await _petty_cash_account_code(db)}


@router.post('/funds')
async def create_fund(body: FundCreate, user: dict = Depends(require_auth)):
    if user.get('role') not in FINANCE_ROLES:
        raise HTTPException(403, 'Hanya Finance/Admin yang bisa membuat dana kas kecil.')
    db = get_db()
    source_code = await _resolve_source_account(db, body.bank_account_code)  # 2026-11-02
    fund_id = _uid()
    now = _now()
    doc = {
        'id': fund_id,
        'name': body.name.strip(),
        'custodian_name': body.custodian_name or '',
        'opening_balance': body.opening_balance,
        'current_balance': body.opening_balance,
        'bank_account_code': source_code,
        'notes': body.notes or '',
        'status': 'active',
        'created_at': now,
        'updated_at': now,
        'created_by': user['id'],
    }

    # 2026-11-02 (audit kas kecil): saldo awal DIJURNAL DULU, dana baru dibuat bila jurnal
    # berhasil. Dulu dana lahir dengan saldo penuh walau jurnal saldo awal gagal (saldo dana ≠ GL).
    if body.opening_balance > 0:
        txn_id = _uid()
        txn_doc = {
            'id': txn_id, 'fund_id': fund_id,
            'txn_type': 'opening',
            'amount': body.opening_balance,
            'txn_date': str(date.today()),
            'memo': f'Saldo awal dana {body.name}',
            'bank_account_code': source_code,
            'category': None, 'payee': None,
            'gl_posted': False, 'gl_je_id': None, 'gl_error': None,
            'created_at': now, 'created_by': user['id'],
        }
        await db.rahaza_petty_cash_txns.insert_one(txn_doc)
        posting_result = await _post_petty_cash_txn(db, txn_doc, user)
        if not posting_result.get('ok'):
            await db.rahaza_petty_cash_txns.delete_one({'id': txn_id})
            raise HTTPException(400, f"Dana tidak dibuat: jurnal saldo awal gagal ({posting_result.get('error')}).")

    await db.rahaza_petty_cash_funds.insert_one(doc)
    doc.pop('_id', None)
    await log_activity(user['id'], user.get('name', ''), 'CREATE_PETTY_CASH_FUND', 'petty_cash_fund', fund_id)
    return _ser(doc)


@router.get('/funds/{fund_id}')
async def get_fund(fund_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    fund = await _get_fund_or_404(db, fund_id)
    # Tambah ringkasan txn
    txns_count = await db.rahaza_petty_cash_txns.count_documents({'fund_id': fund_id})
    fund['txns_count'] = txns_count
    return _ser(fund)


@router.post('/funds/{fund_id}/replenish')
async def replenish_fund(fund_id: str, body: ReplenishIn, user: dict = Depends(require_auth)):
    if user.get('role') not in FINANCE_ROLES:
        raise HTTPException(403, 'Hanya Finance/Admin yang bisa replenish dana.')
    db = get_db()
    fund = await _get_fund_or_404(db, fund_id)
    if fund.get('status') != 'active':
        raise HTTPException(400, 'Dana kas kecil tidak aktif.')
    source_code = await _resolve_source_account(db, body.bank_account_code or fund.get('bank_account_code'))  # 2026-11-02
    now = _now()
    txn_doc = {
        'id': _uid(), 'fund_id': fund_id,
        'txn_type': 'replenish',
        'amount': body.amount,
        'txn_date': body.txn_date or str(date.today()),
        'memo': body.memo or 'Replenishment Kas Kecil',
        'bank_account_code': source_code,
        'category': None, 'payee': None,
        'gl_posted': False, 'gl_je_id': None, 'gl_error': None,
        'created_at': now, 'created_by': user['id'],
    }
    await db.rahaza_petty_cash_txns.insert_one(txn_doc)
    # 2026-11-02 (audit kas kecil): JURNAL DULU, saldo dana bertambah HANYA bila jurnal berhasil
    # (sama dengan create_txn/close_fund, FIN-05). Dulu saldo naik walau jurnal gagal → dana ≠ GL.
    posting_result = await _post_petty_cash_txn(db, txn_doc, user)
    if not posting_result.get('ok'):
        await db.rahaza_petty_cash_txns.delete_one({'id': txn_doc['id']})
        raise HTTPException(400, f"Pengisian dibatalkan: jurnal gagal ({posting_result.get('error')}).")
    await db.rahaza_petty_cash_funds.update_one(
        {'id': fund_id},
        {'$inc': {'current_balance': body.amount}, '$set': {'updated_at': now}}
    )
    fresh = await db.rahaza_petty_cash_funds.find_one({'id': fund_id}, {'_id': 0, 'current_balance': 1}) or {}
    await log_activity(user['id'], user.get('name', ''), 'REPLENISH_PETTY_CASH', 'petty_cash_fund', fund_id)
    return {
        'ok': True,
        'txn': _ser(txn_doc),
        'new_balance': float(fresh.get('current_balance', float(fund.get('current_balance') or 0) + body.amount)),
        'gl_posting': posting_result,
    }


@router.post('/funds/{fund_id}/close')
async def close_fund(fund_id: str, user: dict = Depends(require_auth)):
    if user.get('role') not in FINANCE_ROLES:
        raise HTTPException(403, 'Hanya Finance/Admin yang bisa menutup dana.')
    db = get_db()
    fund = await _get_fund_or_404(db, fund_id)
    if fund.get('status') == 'closed':
        raise HTTPException(400, 'Dana sudah ditutup.')
    now = _now()
    # Jika masih ada saldo, kembalikan ke bank
    remaining = float(fund.get('current_balance') or 0)
    posting_result = None
    if remaining > 0:
        txn_doc = {
            'id': _uid(), 'fund_id': fund_id,
            'txn_type': 'close_return',  # FIN-05(b)
            'amount': remaining,
            'txn_date': str(date.today()),
            'memo': f'Penutupan dana {fund["name"]} - sisa saldo dikembalikan ke bank',
            'bank_account_code': fund.get('bank_account_code', '1-1201'),
            'category': None, 'payee': None,
            'gl_posted': False, 'gl_je_id': None, 'gl_error': None,
            'created_at': now, 'created_by': user['id'],
        }
        await db.rahaza_petty_cash_txns.insert_one(txn_doc)
        posting_result = await _post_petty_cash_txn(db, txn_doc, user)
        if not posting_result.get('ok'):  # FIN-05: dana = GL — jangan tutup bila jurnal gagal
            await db.rahaza_petty_cash_txns.delete_one({'id': txn_doc['id']})
            raise HTTPException(400, f"Penutupan dibatalkan: jurnal gagal ({posting_result.get('error')}).")

    await db.rahaza_petty_cash_funds.update_one(
        {'id': fund_id},
        {'$set': {'status': 'closed', 'current_balance': 0, 'closed_at': now, 'updated_at': now}}
    )
    await log_activity(user['id'], user.get('name', ''), 'CLOSE_PETTY_CASH_FUND', 'petty_cash_fund', fund_id)
    return {'ok': True, 'returned_balance': remaining, 'gl_posting': posting_result}


# ── Transaction Endpoints ────────────────────────────────────────────────────

@router.post('/transactions')
async def create_txn(body: TxnCreate, user: dict = Depends(require_auth)):
    if user.get('role') not in ALL_ROLES:  # FIN-04: kas kecil hanya peran keuangan/kasir
        raise HTTPException(403, 'Hanya Finance/Kasir yang bisa mencatat transaksi kas kecil.')
    if body.txn_type not in ('expense', 'advance', 'return'):
        raise HTTPException(400, 'Hanya expense/advance/return yang bisa diinput via form. Replenish gunakan /funds/{id}/replenish.')
    db = get_db()
    fund = await _get_fund_or_404(db, body.fund_id)
    if fund.get('status') != 'active':
        raise HTTPException(400, 'Dana kas kecil tidak aktif.')

    # Cek saldo cukup untuk pengeluaran
    if body.txn_type in ('expense', 'advance'):
        if float(fund.get('current_balance', 0)) < body.amount:
            raise HTTPException(400, f'Saldo kas kecil tidak cukup. Saldo: {fund["current_balance"]:.2f}, Diminta: {body.amount:.2f}')
    if body.txn_type == 'return':
        # FIN-05(c) + 2026-11-02 (K26): 'return' HANYA untuk uang muka LAMA (tanpa karyawan, dulu langsung
        # dibebankan). Uang muka atas nama karyawan dikembalikan lewat Pertanggungjawaban.
        rows = await db.rahaza_petty_cash_txns.find(
            {'fund_id': body.fund_id, 'txn_type': {'$in': ['advance', 'return']}, 'gl_posted': True},
            {'_id': 0, 'txn_type': 1, 'amount': 1, 'employee_id': 1}).to_list(5000)
        legacy_adv = sum(float(r.get('amount') or 0) for r in rows if r['txn_type'] == 'advance' and not r.get('employee_id'))
        returned = sum(float(r.get('amount') or 0) for r in rows if r['txn_type'] == 'return')
        open_adv = legacy_adv - returned
        if body.amount > open_adv + 0.01:
            raise HTTPException(400, (f'Pengembalian melebihi uang muka LAMA yang terbuka ({open_adv:,.0f}). '
                                      'Sisa uang muka atas nama karyawan dikembalikan lewat Pertanggungjawaban.'))

    now = _now()
    txn_date = (body.txn_date or str(_today_wib()))[:10]
    extra: dict = {}
    if body.txn_type == 'advance':
        # 2026-11-02 (K26): uang muka WAJIB atas nama karyawan (pilih dari master), dicatat ke 1-1610.
        emp_id = (body.employee_id or '').strip()
        if not emp_id:
            raise HTTPException(400, 'Uang muka kas kecil wajib memilih karyawan penerima.')
        emp = await db.rahaza_employees.find_one({'id': emp_id}, {'_id': 0, 'id': 1, 'name': 1, 'employee_code': 1, 'active': 1})
        if not emp or emp.get('active') is False:
            raise HTTPException(400, 'Karyawan penerima uang muka tidak ditemukan atau nonaktif.')
        days = int(fund.get('advance_settle_days') or 0)
        try:
            due = (date.fromisoformat(txn_date) + timedelta(days=days)).isoformat() if days > 0 else None
        except ValueError:
            raise HTTPException(400, 'Format txn_date harus YYYY-MM-DD.')
        extra = {'employee_id': emp['id'], 'employee_name': emp.get('name') or '',
                 'employee_code': emp.get('employee_code') or '',
                 'advance_account_code': await _employee_advance_code(db),
                 'settled_amount': 0.0, 'open_amount': float(body.amount), 'advance_status': 'open',
                 'due_date': due, 'settlements': []}
    elif body.txn_type == 'expense':
        acc = await _resolve_expense_account(db, body.category, body.account_code, 'Pengeluaran kas kecil')
        extra = {'gl_debit_code': acc['code'], 'gl_debit_name': acc['name'], 'gl_debit_source': acc['source']}

    txn_doc = {
        'id': _uid(),
        'fund_id': body.fund_id,
        'txn_type': body.txn_type,
        'amount': body.amount,
        'txn_date': txn_date,
        'category': body.category or '',
        'payee':    (extra.get('employee_name') or body.payee or ''),
        'memo':     body.memo or '',
        'bank_account_code': body.bank_account_code or fund.get('bank_account_code', '1-1201'),
        'gl_posted': False, 'gl_je_id': None, 'gl_je_number': None, 'gl_error': None,
        'created_at': now,
        'created_by': user['id'],
        'created_by_name': user.get('name', user.get('email', '')),
        **extra,
    }
    await db.rahaza_petty_cash_txns.insert_one(txn_doc)

    # FIN-05: jurnal dulu; saldo dana berubah HANYA bila jurnal berhasil, dengan filter atomik (tidak boleh minus)
    posting_result = await _post_petty_cash_txn(db, txn_doc, user)
    if not posting_result.get('ok'):
        await db.rahaza_petty_cash_txns.delete_one({'id': txn_doc['id']})
        raise HTTPException(400, f"Transaksi dibatalkan: jurnal gagal ({posting_result.get('error')}).")
    delta = -body.amount if body.txn_type in ('expense', 'advance') else body.amount
    flt = {'id': body.fund_id, 'status': 'active'}
    if delta < 0:
        flt['current_balance'] = {'$gte': body.amount}
    upd = await db.rahaza_petty_cash_funds.update_one(flt, {'$inc': {'current_balance': delta}, '$set': {'updated_at': now}})
    if upd.matched_count == 0:
        await db.rahaza_petty_cash_txns.update_one({'id': txn_doc['id']}, {'$set': {'gl_error': 'saldo tidak cukup saat commit', 'void_needed': True}})
        raise HTTPException(409, 'Saldo kas kecil berubah saat diproses; transaksi tidak dicatat ke dana. Hubungi Keuangan untuk void jurnal.')
    await log_activity(user['id'], user.get('name', ''), f'PETTY_CASH_{body.txn_type.upper()}', 'petty_cash_txn', txn_doc['id'])
    return {
        'txn': _ser(txn_doc),
        'gl_posting': posting_result,
        'new_balance': float(fund.get('current_balance', 0)) + delta,
    }


@router.get('/transactions')
async def list_txns(
    fund_id: Optional[str] = Query(None),
    txn_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    user: dict = Depends(require_auth),
):
    db = get_db()
    q = {}
    if fund_id:
        q['fund_id'] = fund_id
    if txn_type:
        q['txn_type'] = txn_type
    total = await db.rahaza_petty_cash_txns.count_documents(q)
    txns = await db.rahaza_petty_cash_txns.find(q, {'_id': 0}).sort('txn_date', -1).skip(skip).limit(limit).to_list(limit)
    return {'items': [_ser(t) for t in txns], 'total': total}


# ── Uang muka karyawan: daftar terbuka + pertanggungjawaban (K26, 2026-11-02) ──

def _advance_view(t: dict, fund_days: dict, today: date) -> dict:
    try:
        age = (today - date.fromisoformat(str(t.get('txn_date'))[:10])).days
    except ValueError:
        age = None
    due = t.get('due_date')
    if not due and fund_days.get(t.get('fund_id')) and age is not None:
        due = (date.fromisoformat(str(t.get('txn_date'))[:10]) + timedelta(days=fund_days[t['fund_id']])).isoformat()
    return {
        'id': t['id'], 'fund_id': t.get('fund_id'), 'txn_date': t.get('txn_date'),
        'employee_id': t.get('employee_id'), 'employee_name': t.get('employee_name') or t.get('payee') or '',
        'employee_code': t.get('employee_code') or '', 'memo': t.get('memo') or '',
        'amount': float(t.get('amount') or 0), 'settled_amount': float(t.get('settled_amount') or 0),
        'open_amount': float(t.get('open_amount') if t.get('open_amount') is not None else t.get('amount') or 0),
        'advance_status': t.get('advance_status') or 'open', 'gl_je_number': t.get('gl_je_number'),
        'age_days': age, 'due_date': due, 'overdue': bool(due and today.isoformat() > due),
        'settlements': t.get('settlements') or [],
    }


@router.get('/advances')
async def list_advances(
    status: str = Query('open', description="open | all"),
    employee_id: Optional[str] = Query(None),
    fund_id: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
):
    """Daftar uang muka kas kecil atas nama karyawan, dikelompokkan per karyawan (K26)."""
    if user.get('role') not in ALL_ROLES:
        raise HTTPException(403, 'Hanya Finance/Kasir yang bisa melihat uang muka kas kecil.')
    db = get_db()
    q = {'txn_type': 'advance', 'gl_posted': True, 'employee_id': {'$exists': True, '$ne': None}}
    if employee_id:
        q['employee_id'] = employee_id
    if fund_id:
        q['fund_id'] = fund_id
    if status == 'open':
        q['open_amount'] = {'$gt': 0.009}
    rows = await db.rahaza_petty_cash_txns.find(q, {'_id': 0}).sort('txn_date', 1).to_list(2000)
    funds = await db.rahaza_petty_cash_funds.find({}, {'_id': 0, 'id': 1, 'advance_settle_days': 1}).to_list(200)
    fund_days = {f['id']: int(f.get('advance_settle_days') or 0) for f in funds}
    today = _today_wib()
    items = [_advance_view(t, fund_days, today) for t in rows]
    groups: dict = {}
    for it in items:
        g = groups.setdefault(it['employee_id'], {'employee_id': it['employee_id'], 'employee_name': it['employee_name'],
                                                  'employee_code': it['employee_code'], 'count': 0, 'total_open': 0.0,
                                                  'overdue_count': 0, 'oldest_date': it['txn_date']})
        g['count'] += 1
        g['total_open'] = round(g['total_open'] + it['open_amount'], 2)
        g['overdue_count'] += 1 if it['overdue'] else 0
    return {'items': items, 'by_employee': sorted(groups.values(), key=lambda g: -g['total_open']),
            'total_open': round(sum(i['open_amount'] for i in items), 2)}


@router.post('/advances/{txn_id}/settle')
async def settle_advance(txn_id: str, body: AdvanceSettleIn, user: dict = Depends(require_auth)):
    """Pertanggungjawaban uang muka (K26): nota per kategori → Dr beban; sisa kembali → Dr kas kecil; Cr 1-1610.
    Boleh bertahap (sebagian); total nota + sisa ≤ uang muka terbuka."""
    if user.get('role') not in ALL_ROLES:
        raise HTTPException(403, 'Hanya Finance/Kasir yang bisa mencatat pertanggungjawaban kas kecil.')
    db = get_db()
    adv = await db.rahaza_petty_cash_txns.find_one({'id': txn_id}, {'_id': 0})
    if not adv or adv.get('txn_type') != 'advance':
        raise HTTPException(404, 'Uang muka kas kecil tidak ditemukan.')
    if not adv.get('employee_id'):
        raise HTTPException(400, "Uang muka lama (tanpa karyawan) dibebankan langsung — kembalikan sisanya lewat tipe 'return'.")
    if not adv.get('gl_posted'):
        raise HTTPException(400, 'Jurnal uang muka ini belum terbentuk — posting ulang dulu.')
    open_amt = float(adv.get('open_amount') if adv.get('open_amount') is not None else adv.get('amount') or 0)
    returned = round(float(body.returned_amount or 0), 2)
    items = []
    for i, it in enumerate(body.items or []):
        acc = await _resolve_expense_account(db, it.category, it.account_code, f'Nota #{i + 1}')
        items.append({'category': it.category or '', 'account_code': acc['code'], 'account_name': acc['name'],
                      'account_source': acc['source'], 'amount': round(float(it.amount), 2), 'memo': it.memo or ''})
    total = round(sum(x['amount'] for x in items) + returned, 2)
    if total <= 0:
        raise HTTPException(400, 'Isi minimal satu nota atau sisa uang yang dikembalikan.')
    if total > open_amt + 0.01:
        raise HTTPException(400, f'Nota + sisa ({total:,.0f}) melebihi uang muka terbuka ({open_amt:,.0f}).')
    fund = await _get_fund_or_404(db, adv['fund_id'])
    if returned > 0 and fund.get('status') != 'active':
        raise HTTPException(400, 'Dana kas kecil sudah tidak aktif — sisa uang tidak bisa dikembalikan ke dana ini.')
    settle_date = (body.settle_date or str(_today_wib()))[:10]
    try:
        date.fromisoformat(settle_date)
    except ValueError:
        raise HTTPException(400, 'Format settle_date harus YYYY-MM-DD.')

    # Cadangkan dulu secara atomik (penjaga balapan dua pertanggungjawaban sekaligus).
    res = await db.rahaza_petty_cash_txns.update_one(
        {'id': txn_id, 'open_amount': {'$gte': total - 0.01}},
        {'$inc': {'open_amount': -total, 'settled_amount': total}})
    if not res.matched_count:
        raise HTTPException(409, 'Uang muka ini baru saja dipertanggungjawabkan pengguna lain — muat ulang.')
    now = _now()
    stl = {
        'id': _uid(), 'fund_id': adv['fund_id'], 'txn_type': 'advance_settlement', 'amount': total,
        'txn_date': settle_date, 'advance_txn_id': txn_id, 'advance_ref': adv.get('gl_je_number') or txn_id[:8],
        'advance_account_code': adv.get('advance_account_code') or await _employee_advance_code(db),
        'employee_id': adv.get('employee_id'), 'employee_name': adv.get('employee_name'),
        'payee': adv.get('employee_name') or '', 'items': items, 'returned_amount': returned,
        'category': '', 'memo': body.memo or '',
        'gl_posted': False, 'gl_je_id': None, 'gl_je_number': None, 'gl_error': None,
        'created_at': now, 'created_by': user['id'], 'created_by_name': user.get('name', user.get('email', '')),
    }
    await db.rahaza_petty_cash_txns.insert_one(stl)
    posting = await _post_petty_cash_txn(db, stl, user)
    if not posting.get('ok'):
        await db.rahaza_petty_cash_txns.delete_one({'id': stl['id']})
        await db.rahaza_petty_cash_txns.update_one({'id': txn_id}, {'$inc': {'open_amount': total, 'settled_amount': -total}})
        raise HTTPException(400, f"Pertanggungjawaban dibatalkan: jurnal gagal ({posting.get('error')}).")
    left = round(open_amt - total, 2)
    await db.rahaza_petty_cash_txns.update_one({'id': txn_id}, {
        '$set': {'advance_status': 'settled' if left <= 0.01 else 'partial', 'updated_at': now},
        '$push': {'settlements': {'txn_id': stl['id'], 'date': settle_date, 'amount': total, 'returned': returned,
                                  'je_number': posting.get('je_number')}}})
    if returned > 0:
        await db.rahaza_petty_cash_funds.update_one({'id': adv['fund_id']},
                                                    {'$inc': {'current_balance': returned}, '$set': {'updated_at': now}})
    await log_activity(user['id'], user.get('name', ''), 'PETTY_CASH_ADVANCE_SETTLE', 'petty_cash_txn', stl['id'])
    fresh = await db.rahaza_petty_cash_txns.find_one({'id': txn_id}, {'_id': 0})
    return {'ok': True, 'settlement': _ser(stl), 'advance': _ser(fresh), 'gl_posting': posting}


@router.patch('/funds/{fund_id}/settings')
async def update_fund_settings(fund_id: str, body: FundSettingsIn, user: dict = Depends(require_auth)):
    """Batas hari pertanggungjawaban uang muka per dana (K26). 0 = belum diatur."""
    if user.get('role') not in FINANCE_ROLES:
        raise HTTPException(403, 'Hanya Finance yang bisa mengubah pengaturan dana kas kecil.')
    db = get_db()
    await _get_fund_or_404(db, fund_id)
    await db.rahaza_petty_cash_funds.update_one({'id': fund_id}, {'$set': {
        'advance_settle_days': int(body.advance_settle_days), 'updated_at': _now()}})
    await log_activity(user['id'], user.get('name', ''), 'UPDATE_PETTY_CASH_FUND', 'petty_cash_fund',
                       f'{fund_id} advance_settle_days={body.advance_settle_days}')
    return _ser(await _get_fund_or_404(db, fund_id))


@router.post('/transactions/{txn_id}/retry-posting')
async def retry_txn_posting(txn_id: str, user: dict = Depends(require_auth)):
    if user.get('role') not in FINANCE_ROLES:
        raise HTTPException(403, 'Hanya Finance yang bisa retry posting.')
    db = get_db()
    txn = await db.rahaza_petty_cash_txns.find_one({'id': txn_id}, {'_id': 0})
    if not txn:
        raise HTTPException(404, 'Transaksi tidak ditemukan.')
    result = await _post_petty_cash_txn(db, txn, user)
    return result
