"""
Bank Transfer Antar Rekening — Phase 6C
CV. Dewi Aditya ERP

Transfer dana internal antar rekening bank dengan auto-posting GL:
  Dr Bank Tujuan / Cr Bank Sumber

Collection: rahaza_bank_transfers
Prefix: /api/finance/bank-transfers
"""
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone, date
from database import get_db
from auth import require_auth, serialize_doc, log_activity
from core.authz import izin_atau_peran_lama  # 14 Nov 2026: centang owner = penentu
from routes.rahaza_posting import _create_posted_je, _find_existing_je, get_mapping
from core import entities as ent_mod
import logging
import uuid
from utils.waktu import today_wib

log = logging.getLogger(__name__)
router = APIRouter(prefix='/api/finance/bank-transfers', tags=['Bank-Transfer'])

# RC-FLOW-kasbank-1 FIX: role Finance kanonik = 'accounting'/'staff_keuangan' (bukan 'finance').
# Akun finance@dewiaditya.id (role 'accounting') sebelumnya DITOLAK 403 saat membuat transfer bank.
from core.roles import FINANCE_ROLES, FINANCE_CASH_PERMS  # FIN-02: satu sumber peran keuangan


def _is_cash_officer(user: dict) -> bool:
    """2026-11-08: kode peran Keuangan ATAU izin kas & bank (`FINANCE_CASH_PERMS`) — peran buatan owner
    ("Accounting & Finance") dulu 403. Cermin layar: BankTransferModule.jsx (canManage)."""
    return izin_atau_peran_lama(user, FINANCE_ROLES, FINANCE_CASH_PERMS)


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc).isoformat()


def _ser(doc: dict) -> dict:
    return serialize_doc(doc) if doc else {}


async def _post_bank_transfer(db, transfer: dict, user: dict) -> dict:
    """
    Post GL entry untuk bank transfer.
    Dr Bank Tujuan / Cr Bank Sumber.
    Idempotent via source_ref = transfer.id
    """
    tf_id = transfer['id']
    source_ref = f'bt:{tf_id}'

    existing = await _find_existing_je(db, 'bank_transfer', source_ref)
    if existing:
        return {'ok': True, 'je_id': existing['id'], 'je_number': existing['je_number'], 'already_posted': True}

    # Ambil account codes dari dokumen transfer
    from_code = transfer.get('from_account_code')
    to_code   = transfer.get('to_account_code')
    amount    = float(transfer.get('amount', 0))

    # Fallback ke posting profile jika tidak ada di dokumen
    if not from_code or not to_code:
        mapping = await get_mapping(db, 'bank_transfer')
        from_code = from_code or mapping.get('credit_bank_source', '1-1201')
        to_code   = to_code   or mapping.get('debit_bank_target', '1-1202')

    try:
        je_date = date.fromisoformat((transfer.get('transfer_date') or str(today_wib()))[:10])
    except Exception:
        je_date = today_wib()

    memo = f"Transfer Bank: {transfer.get('ref_number', tf_id[:8])} | {transfer.get('memo') or transfer.get('from_account_name','?')} → {transfer.get('to_account_name','?')}"
    lines = [
        {'account_code': to_code,   'debit': round(amount, 2), 'credit': 0,
         'description': f"Terima dari {transfer.get('from_account_name', from_code)}"},
        {'account_code': from_code, 'debit': 0, 'credit': round(amount, 2),
         'description': f"Kirim ke {transfer.get('to_account_name', to_code)}"},
    ]

    result = await _create_posted_je(db, je_date, memo, 'bank_transfer', source_ref, lines, user,
                                     entity=await _transfer_entity(db, transfer))   # Tahap 8
    # Persist result
    if result.get('ok'):
        upd = {'gl_posted': True, 'gl_je_id': result.get('je_id'), 'gl_je_number': result.get('je_number'), 'gl_error': None}
    else:
        upd = {'gl_posted': False, 'gl_je_id': None, 'gl_error': result.get('error')}
    await db.rahaza_bank_transfers.update_one({'id': tf_id}, {'$set': upd})
    return result


async def _transfer_entity(db, transfer: dict) -> str:
    """CV transfer: field dokumen, atau pemilik rekening sumber (dokumen lama)."""
    if transfer.get('entity'):
        return ent_mod.entity_of_value(transfer['entity'])
    return (await ent_mod.cash_account_entity(db, gl_code=transfer.get('from_account_code'))) or ent_mod.DA


async def _owners_or_reject(db, from_code: str, to_code: str, chosen) -> str:
    """Tahap 8: transfer hanya antar rekening SATU CV. Rekening beda CV DITOLAK dan diarahkan ke menu
    Keuangan › Transaksi antar CV (fase 2: pinjaman / pelunasan) — di sana dua jurnal berlabel dibuat sekaligus
    dengan hutang/piutang antar CV, bukan satu jurnal transfer yang menyeberang buku."""
    src = await ent_mod.cash_account_entity(db, gl_code=from_code) or ent_mod.DA
    dst = await ent_mod.cash_account_entity(db, gl_code=to_code) or ent_mod.DA
    if src != dst:
        raise HTTPException(400, f"Transfer ditolak: rekening sumber milik {ent_mod.entity_short(src)}, rekening "
                                 f"tujuan milik {ent_mod.entity_short(dst)}. Catat pemindahan uang antar CV di menu Keuangan › "
                                 f"Transaksi antar CV (jenis Pinjaman atau Pelunasan) — jurnal di dua buku dibuat "
                                 f"otomatis.")
    if chosen and chosen != src:
        raise HTTPException(400, f"Transfer ditolak: kedua rekening milik {ent_mod.entity_short(src)}, bukan "
                                 f"{ent_mod.entity_short(chosen)}. Ganti pilihan CV atau rekeningnya.")
    return src


# ── Pydantic Models ─────────────────────────────────────────────────────────

class TransferCreate(BaseModel):
    from_account_code: str = Field(..., description='Kode akun bank sumber (mis. 1-1201)')
    from_account_name: Optional[str] = None
    to_account_code: str   = Field(..., description='Kode akun bank tujuan (mis. 1-1202)')
    to_account_name: Optional[str] = None
    amount: float = Field(..., gt=0)
    transfer_date: Optional[str] = None  # ISO date
    memo: Optional[str] = None
    ref_external: Optional[str] = None  # Nomor referensi bank
    # SESI #27 — nomor dokumen ketikan staf (HANYA dipakai bila kebijakan = MANUAL).
    # Berbeda dari `ref_external` (nomor milik BANK, bukan nomor dokumen kita).
    ref_number: Optional[str] = ''


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get('')
async def list_transfers(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    user: dict = Depends(require_auth),
    request: Request = None,
):
    db = get_db()
    q = dict(ent_mod.entity_match(ent_mod.entity_from_request(request, allow_all=True)))   # Tahap 8
    if status:
        q['status'] = status
    total = await db.rahaza_bank_transfers.count_documents(q)
    items = await db.rahaza_bank_transfers.find(q, {'_id': 0}).sort('transfer_date', -1).skip(skip).limit(limit).to_list(limit)
    return {'items': [_ser(i) for i in items], 'total': total}


@router.post('')
async def create_transfer(body: TransferCreate, user: dict = Depends(require_auth), request: Request = None):
    if not _is_cash_officer(user):
        raise HTTPException(403, 'Hanya Finance/Admin yang bisa membuat transfer bank.')
    if body.from_account_code == body.to_account_code:
        raise HTTPException(400, 'Akun sumber dan tujuan tidak boleh sama.')

    db = get_db()
    # 2026-11-02 (audit No.44c): transfer bank hanya antar rekening kas/bank/e-wallet aktif (SSOT
    # core.payout_banks). Dulu akun apa pun diterima → transfer 4-1100 → 1-1201 menambah pendapatan,
    # 1-1201 → 6-2900 menambah beban, berstatus 'completed'.
    from core.payout_banks import is_bank_code
    for _label, _code in (('sumber', body.from_account_code), ('tujuan', body.to_account_code)):
        if not await is_bank_code(db, (_code or '').strip()):
            raise HTTPException(400, f"Akun {_label} '{_code}' bukan rekening kas/bank aktif. Transfer bank "
                                     f"hanya antar rekening kas/bank milik sendiri (daftar Kas & Bank).")
    entity = await _owners_or_reject(db, (body.from_account_code or '').strip(), (body.to_account_code or '').strip(),
                                     ent_mod.explicit_entity(request))   # Tahap 8
    now = _now()
    tf_id = _uid()
    # Nomor referensi — SATU PINTU kebijakan penomoran (SESI #27, batch-3 Fase G).
    # Transfer bank sering disalin dari bukti transfer bank sungguhan, jadi mode
    # MANUAL bukan kemewahan: tanpa penegakan ini, nomor yang diketik staf
    # DIABAIKAN diam-diam dan dokumen dapat nomor lain.
    from core.doc_number_policy import issue_number
    ref_number = await issue_number(db, "rahaza_bank_transfers.ref_number",
                                    requested=(body.ref_number or "").strip())

    doc = {
        'id': tf_id,
        'entity': entity,
        'ref_number': ref_number,
        'from_account_code': body.from_account_code,
        'from_account_name': body.from_account_name or body.from_account_code,
        'to_account_code':   body.to_account_code,
        'to_account_name':   body.to_account_name or body.to_account_code,
        'amount': body.amount,
        'transfer_date': body.transfer_date or str(today_wib()),
        'memo': body.memo or '',
        'ref_external': body.ref_external or '',
        'status': 'completed',
        'gl_posted': False, 'gl_je_id': None, 'gl_je_number': None, 'gl_error': None,
        'created_at': now,
        'created_by': user['id'],
        'created_by_name': user.get('name', user.get('email', '')),
    }
    await db.rahaza_bank_transfers.insert_one(doc)

    posting_result = await _post_bank_transfer(db, doc, user)
    if posting_result.get('ok'):
        log.info(f"[BankTransfer] {ref_number} posted OK: JE {posting_result.get('je_number')}")
    else:
        log.warning(f"[BankTransfer] {ref_number} posting failed: {posting_result.get('error')}")
        # FIN-13: tanpa jurnal → bukan 'completed'
        await db.rahaza_bank_transfers.update_one({'id': doc['id']}, {'$set': {'status': 'pending_posting'}})
        doc['status'] = 'pending_posting'

    await log_activity(user['id'], user.get('name', ''), 'CREATE_BANK_TRANSFER', 'bank_transfer', tf_id)

    refreshed = await db.rahaza_bank_transfers.find_one({'id': tf_id}, {'_id': 0})
    return {
        'transfer': _ser(refreshed),
        'gl_posting': posting_result,
    }


@router.get('/{tf_id}')
async def get_transfer(tf_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    doc = await db.rahaza_bank_transfers.find_one({'id': tf_id}, {'_id': 0})
    if not doc:
        raise HTTPException(404, 'Transfer tidak ditemukan.')
    return _ser(doc)


@router.post('/{tf_id}/retry-posting')
async def retry_posting(tf_id: str, user: dict = Depends(require_auth)):
    if not _is_cash_officer(user):
        raise HTTPException(403, 'Hanya Finance yang bisa retry posting.')
    db = get_db()
    doc = await db.rahaza_bank_transfers.find_one({'id': tf_id}, {'_id': 0})
    if not doc:
        raise HTTPException(404, 'Transfer tidak ditemukan.')
    result = await _post_bank_transfer(db, doc, user)
    return result


@router.post('/{tf_id}/void')
async def void_transfer(tf_id: str, user: dict = Depends(require_auth)):
    """Void transfer: buat reversal JE (Dr sumber / Cr tujuan)."""
    if not _is_cash_officer(user):
        raise HTTPException(403, 'Hanya Finance/Admin yang bisa void transfer.')
    db = get_db()
    original = await db.rahaza_bank_transfers.find_one({'id': tf_id}, {'_id': 0})
    if not original:
        raise HTTPException(404, 'Transfer tidak ditemukan.')
    if original.get('status') == 'voided':
        raise HTTPException(400, 'Transfer sudah divoid.')
    if not original.get('gl_posted'):  # FIN-13: tidak ada jurnal → void tanpa jurnal pembalik
        now = _now()
        await db.rahaza_bank_transfers.update_one(
            {'id': tf_id}, {'$set': {'status': 'voided', 'voided_at': now, 'voided_by': user['id'], 'void_note': 'void tanpa jurnal (transfer belum terposting)'}})
        return {'ok': True, 'je_id': None, 'voided_without_je': True}

    void_ref = f'void_bt:{tf_id}'
    existing_void = await _find_existing_je(db, 'bank_transfer', void_ref)
    if existing_void:
        return {'ok': True, 'je_id': existing_void['id'], 'je_number': existing_void['je_number'], 'already_voided': True}

    amount = float(original.get('amount', 0))
    from_code = original['from_account_code']
    to_code   = original['to_account_code']

    try:
        je_date = today_wib()
    except Exception:
        je_date = today_wib()

    memo = f"VOID {original.get('ref_number', tf_id[:8])}: Reversal Transfer Bank"
    lines = [
        {'account_code': from_code, 'debit': round(amount, 2), 'credit': 0,
         'description': f"Reversal: {memo}"},
        {'account_code': to_code,   'debit': 0, 'credit': round(amount, 2),
         'description': f"Reversal: {memo}"},
    ]
    result = await _create_posted_je(db, je_date, memo, 'bank_transfer', void_ref, lines, user,
                                     entity=await _transfer_entity(db, original))   # Tahap 8
    if result.get('ok'):
        await db.rahaza_bank_transfers.update_one(
            {'id': tf_id},
            {'$set': {'status': 'voided', 'voided_at': _now(), 'void_je_id': result.get('je_id')}}
        )
    return result
