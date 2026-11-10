"""Session 27 — GAP-R3 Accessory Request Workflow

★ SSOT (P3 TD-009 — Session #11.10): canonical store for ALL accessory
  request flows across CV. Dewi Aditya. Absorbs:
  - `acc_internal_requests` (deprecated, see `dewi_accessories_full.py`
    `/api/dewi/accessories/internal-requests/*`) — `request_type='internal_issuance'`
  - `accessory_requests` (deprecated, see `operations.py`
    `/api/operations/accessory-requests/*`) — `request_type='vendor_additional'|
    'vendor_replacement'`
  - Native RnD sample requests — `request_type='rnd_sample'` (legacy docs
    without `request_type` are treated as rnd_sample).

Status workflow (normalized across all request_types):
  draft → submitted → allocated → delivered (or rejected/cancelled)

2026-11-10 (alur R&D, keputusan owner):
  * baris yang menyebut master wajib master aksesoris aktif — kode, nama, satuan dari master;
    ketikan bebas tetap boleh sebagai cadangan (baris tanpa `material_id` = "belum tertaut");
  * `/cancel` — peminta / tim R&D / manajemen membatalkan selama barang belum diserahkan;
  * notifikasi lewat bel yang ada (`utils.notif_unified.notif_insert`): tim aksesoris saat permintaan
    masuk (Perlu Tindakan, tertutup sendiri begitu disiapkan-lalu-diserahkan/ditolak/dibatalkan),
    peminta saat disiapkan / diserahkan / ditolak / dibatalkan orang lain;
  * `/purchase-draft` — stok kurang saat serah → draf Request Pembelian Aksesoris berisi kekurangannya;
  * `/stats/summary?request_type=` — ringkasan per jenis (layar R&D hanya sampel R&D).

Migration script: /app/backend/migrations/migrate_acc_requests_consolidation.py
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from database import get_db
from auth import require_auth
from datetime import datetime, timezone
from typing import Optional
import logging
import uuid
import re
from core.authz import only  # T-01 2.3
from core.roles import MGMT_ROLES, WAREHOUSE_ROLES  # T-01 2.3
from utils.waktu import fmt_wib

router = APIRouter(prefix="/api/dewi/accessory-requests", tags=["RnD-Accessory-Requests"])
logger = logging.getLogger(__name__)
COLL = 'dewi_accessory_requests'


def now_utc():
    return datetime.now(timezone.utc)


def sid():
    return str(uuid.uuid4())


def serialize(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop('_id', None)
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


VALID_STATUSES = {'draft', 'submitted', 'allocated', 'delivered', 'rejected', 'cancelled'}

# 2026-11-06 (Tahap 1) — status hanya berpindah lewat endpoint transisi (/submit, /allocate,
# /deliver, /reject). Dulu POST & PUT menerima status apa pun, sehingga `PUT status=delivered`
# menandai permintaan "terkirim" TANPA stok keluar. Saat dibuat, status boleh draf atau langsung
# diajukan (Request Internal & sampel R&D mengirim 'submitted').
CREATE_STATUSES = ('draft', 'submitted')
# Field alur kerja yang hanya boleh ditulis endpoint transisi — bukan lewat PUT ubah detail.
# `request_type` ikut dikunci: ia menentukan apakah /deliver memotong stok.
WORKFLOW_FIELDS = (
    'status', 'request_type', 'submitted_at',
    'allocated_by', 'allocated_at', 'allocation_notes',
    'delivered_by', 'delivered_at', 'delivery_notes',
    'rejection_reason', 'rejected_by', 'rejected_at',
    'stock_issued', 'stock_issue_results', 'stock_issued_at',
    # 2026-11-06 (Tahap 2): jejak pengeluaran (tujuan biaya, kelebihan dari kebutuhan PO, kunci serah)
    'issue_linked_po', 'cost_target', 'over_issue_reason', 'over_issue_lines', 'delivering',
    'stock_issue_partial',
    # 2026-11-10: pembatalan & draf pembelian kekurangan
    'cancel_reason', 'cancelled_by', 'cancelled_by_id', 'cancelled_at',
    'purchase_draft_id', 'purchase_draft_number', 'purchase_draft_at',
)
# Belum diserahkan dan masih bisa dibatalkan peminta.
CANCELLABLE_STATUSES = ('draft', 'submitted', 'allocated')
# Satu definisi "menunggu" untuk Inbox Approval DAN kartu "Request Pending" di dashboard:
# status diajukan, semua jenis permintaan (inbox Portal Aksesoris membuka semua jenis).
INBOX_PENDING_FILTER = {'status': 'submitted'}


def _assert_can_fulfil(user: dict, *keys: str, what: str):
    """Gerbang alokasi / serah / tolak: tim Portal Aksesoris (termasuk admin gudang) +
    manajemen. Satu daftar peran untuk ketiga aksi — dulu hanya /reject yang dijaga."""
    from routes.shared import assert_can_act
    assert_can_act(user, *keys, portal='accessories', legacy_roles=MGMT_ROLES, what=what)

# P3 TD-009: known request_type discriminators
VALID_REQUEST_TYPES = {
    'rnd_sample',          # Native — RnD requesting accessories for sample/style production
    'internal_issuance',   # Migrated from acc_internal_requests — internal divisions requesting stock
    'vendor_additional',   # Migrated from accessory_requests — vendor ADDITIONAL shipment request
    'vendor_replacement',  # Migrated from accessory_requests — vendor REPLACEMENT shipment request
}


def _normalize_request_type(rt: Optional[str]) -> str:
    """Map legacy 'sample' or empty values to 'rnd_sample'; pass-through known types."""
    if not rt or rt in ('sample', 'rnd', 'rnd_sample'):
        return 'rnd_sample'
    return rt if rt in VALID_REQUEST_TYPES else 'rnd_sample'


def _norm_item(it: dict) -> dict:
    """Satu baris item permintaan — SATU bentuk untuk buat (POST) dan ubah (PUT).

    2026-11-06 (Tahap 2): PUT dulu menyusun ulang baris tanpa `material_id`, sehingga permintaan
    yang diubah kehilangan tautan ke master (lalu gagal diserahkan / dicocokkan per nama)."""
    return {
        # ACC-1/ACC-2: `material_id` dibawa agar permintaan bisa dipenuhi dari
        # stok kanonik (rahaza_material_stock) tanpa cocok-cocokan nama/kode.
        'material_id': it.get('material_id') or it.get('acc_id') or it.get('accessory_id') or '',
        'material_code': it.get('material_code', '') or it.get('acc_code', '') or it.get('accessory_code', ''),
        'material_name': it.get('material_name', '') or it.get('acc_name', '') or it.get('accessory_name', ''),
        'qty': float(it.get('qty', 0) or it.get('qty_requested', 0) or it.get('requested_qty', 0) or 0),
        'unit': it.get('unit', 'pcs'),
        'notes': it.get('notes', ''),
    }


async def _link_master_items(db, items: list, *, keep_ids=frozenset()) -> list:
    """2026-11-10: baris ber-`material_id` wajib master aksesoris AKTIF; kode, nama, dan satuan
    diambil dari master (stok dipotong dalam satuan master — satuan ketikan diabaikan).

    Baris tanpa `material_id` = ketikan bebas ("belum tertaut"), tetap diterima; masternya
    dipilih tim aksesoris saat serah (`item_links`). `keep_ids` = tautan lama yang sudah
    tersimpan (PUT) — tidak ditolak walau masternya kini nonaktif."""
    from core.accessory_issue import resolve_material
    out = []
    for idx, row in enumerate(items):
        mid = (row.get('material_id') or '').strip()
        if not mid:
            out.append(row)
            continue
        mat = await resolve_material(db, acc_id=mid)
        if not mat:
            if mid in keep_ids:
                out.append(row)
                continue
            raise HTTPException(400, f"Baris {idx + 1}: aksesoris yang dipilih tidak ada di master atau sudah "
                                     f"nonaktif. Pilih ulang dari daftar.")
        out.append({**row, 'material_id': mat['id'], 'material_code': mat.get('code') or row.get('material_code', ''),
                    'material_name': mat.get('name') or row.get('material_name', ''),
                    'unit': mat.get('unit') or row.get('unit') or 'pcs'})
    return out


# ─── NOTIFIKASI (bel SSOT `notifications`, lewat `notif_insert`) ─────────────
TYPE_LABELS = {'rnd_sample': 'Sampel R&D', 'internal_issuance': 'Pemakaian divisi',
               'vendor_additional': 'Tambahan vendor', 'vendor_replacement': 'Pengganti vendor'}
# Layar peminta per jenis (id modul frontend `moduleRegistry.js`); selain ini → Inbox Portal Aksesoris.
REQUESTER_MODULE = {'rnd_sample': 'rnd-accessory-requests', 'internal_issuance': 'accessories-internal-request'}
TEAM_MODULE = 'accessories-inbox'


def _team_roles() -> list:
    """Penerima "Perlu Tindakan": peran nyata Portal Aksesoris (PORTAL_ACCESS) + superadmin."""
    from utils.notif_unified import decider_roles
    return decider_roles('accessories')


def _context(doc: dict) -> str:
    rt = doc.get('request_type') or 'rnd_sample'
    if rt == 'internal_issuance':
        return f"divisi {doc.get('divisi') or '-'}"
    if rt in ('vendor_additional', 'vendor_replacement'):
        return f"PO {doc.get('po_number') or '-'}"
    ctx = f"style {doc.get('style_code') or '-'}"
    if doc.get('sample_code'):
        ctx += f", sampel {doc['sample_code']}"
    return ctx


def _items_text(doc: dict, limit: int = 3) -> str:
    items = doc.get('items') or []
    parts = []
    for it in items[:limit]:
        qty = float(it.get('qty') or 0)
        parts.append(f"{it.get('material_name') or it.get('material_code') or 'barang'} {qty:g} {it.get('unit') or ''}".strip())
    more = len(items) - limit
    return '; '.join(parts) + (f"; dan {more} barang lain" if more > 0 else '')


async def _notify_team(db, doc: dict, actor: dict, *, event: str, reason: str = '') -> None:
    """Kabari tim aksesoris. `submitted` = Perlu Tindakan (ditutup resolver begitu status keluar
    dari submitted/allocated); `cancelled` = pemberitahuan. Pelaku tidak menerima."""
    try:
        from utils.notif_unified import notif_insert
        code = doc.get('request_code') or ''
        who = (actor or {}).get('id')
        kind = TYPE_LABELS.get(doc.get('request_type') or 'rnd_sample', 'Permintaan')
        if event == 'submitted':
            title = f"Permintaan aksesoris {code} menunggu disiapkan" + (" (mendesak)" if doc.get('urgent') else '')
            body = (f"{kind} dari {doc.get('requester_name') or 'peminta'} untuk {_context(doc)}: "
                    f"{_items_text(doc)}.")
            subtype, severity = 'acc_request_submitted', ('warning' if doc.get('urgent') else 'info')
        else:
            title = f"Permintaan aksesoris {code} dibatalkan peminta"
            body = (f"{kind} untuk {_context(doc)} dibatalkan oleh {(actor or {}).get('name') or 'peminta'}. "
                    f"Alasan: {reason or '-'}. Barang yang sudah disiapkan bisa dikembalikan ke rak.")
            subtype, severity = 'acc_request_cancelled', 'warning'
        await notif_insert(
            db, type='rahaza', subtype=subtype, severity=severity, title=title, body=body,
            source_type='accessory_request', source_id=doc.get('id'), source_ref=code,
            target_roles=_team_roles(), exclude_user_ids=[who] if who else None, status='sent',
            meta={'link_module': TEAM_MODULE})
    except Exception:  # noqa: BLE001 — notifikasi tidak boleh menggagalkan permintaan
        logger.warning('[permintaan aksesoris] notifikasi tim gagal untuk %s', doc.get('request_code'), exc_info=True)


async def _notify_requester(db, doc: dict, actor: dict, *, event: str, reason: str = '') -> None:
    """Kabari peminta (akun pembuat) saat disiapkan / diserahkan / ditolak / dibatalkan orang lain."""
    uid = doc.get('requester_id')
    if not uid or uid == (actor or {}).get('id'):
        return
    try:
        from utils.notif_unified import notif_insert
        code = doc.get('request_code') or ''
        name = (actor or {}).get('name') or 'tim aksesoris'
        ctx = _context(doc)
        title, body, severity = {
            'allocated': (f"Permintaan aksesoris {code} sedang disiapkan",
                          f"{name} sedang menyiapkan barang untuk {ctx}.", 'info'),
            'delivered': (f"Permintaan aksesoris {code} sudah diserahkan",
                          f"Barang untuk {ctx} sudah diserahkan oleh {name}: {_items_text(doc)}.", 'success'),
            'rejected': (f"Permintaan aksesoris {code} ditolak",
                         f"Ditolak oleh {name}. Alasan: {reason or '-'}.", 'warning'),
            'cancelled': (f"Permintaan aksesoris {code} dibatalkan",
                          f"Dibatalkan oleh {name}. Alasan: {reason or '-'}.", 'warning'),
        }[event]
        await notif_insert(
            db, type='rahaza', subtype='acc_request_status', severity=severity, title=title, body=body,
            user_id=uid, source_type='accessory_request', source_id=doc.get('id'), source_ref=code,
            status='sent', meta={'link_module': REQUESTER_MODULE.get(doc.get('request_type') or 'rnd_sample',
                                                                     TEAM_MODULE), 'event': event})
    except Exception:  # noqa: BLE001
        logger.warning('[permintaan aksesoris] notifikasi peminta gagal untuk %s', doc.get('request_code'),
                       exc_info=True)


async def _close_team_action(db, request_id: str) -> None:
    """Periksa ulang notifikasi Perlu Tindakan permintaan ini sesudah statusnya berubah."""
    try:
        from utils.notif_unified import resolve_for_source
        await resolve_for_source(db, COLL, request_id)
    except Exception:  # noqa: BLE001
        logger.warning('[permintaan aksesoris] penutupan notifikasi gagal untuk %s', request_id, exc_info=True)


async def _requester_fields(db, user: dict, employee_id: Optional[str]) -> dict:
    """2026-11-07 (Tahap 6, keputusan owner HR3): PEMOHON = karyawan dari master karyawan.

    `employee_id` dikirim → wajib karyawan aktif; id + kode + nama diambil dari master (bukan ketikan).
    Tidak dikirim → karyawan yang tertaut ke akun login (SSOT `utils.employee_identity`); bila akun belum
    tertaut, nama akun dipakai seperti dulu. `requester_id` tetap id AKUN pembuat (jejak audit)."""
    eid = str(employee_id or '').strip()
    if eid:
        emp = await db.rahaza_employees.find_one({'id': eid}, {'_id': 0, 'id': 1, 'name': 1, 'employee_code': 1,
                                                              'active': 1})
        if not emp or emp.get('active') is False:
            raise HTTPException(400, 'Pemohon harus karyawan aktif dari Data Karyawan.')
    else:
        from utils.employee_identity import resolve_my_employee
        emp = await resolve_my_employee(db, user)
    if not emp:
        return {'requester_employee_id': None, 'requester_employee_code': '',
                'requester_name': user.get('name', '')}
    return {'requester_employee_id': emp['id'], 'requester_employee_code': emp.get('employee_code') or '',
            'requester_name': emp.get('name') or user.get('name', '')}


async def _enrich_labels(db, docs: list) -> list:
    """2026-11-06 (Tahap 2): nama vendor, nomor surat jalan asal & kode sampel untuk layar — dulu
    layar menampilkan id mentah (UUID) vendor / surat jalan / permintaan sampel."""
    vids = {d.get('vendor_id') for d in docs if d.get('vendor_id')}
    sids = {d.get('original_shipment_id') for d in docs if d.get('original_shipment_id')}
    rids = {d.get('sample_request_id') for d in docs if d.get('sample_request_id')}
    vendors, ships, samples = {}, {}, {}
    if vids:
        from routes.production_rbac import resolve_vendor_doc
        for vid in vids:
            v = await resolve_vendor_doc(db, vid)
            if v:
                vendors[vid] = v.get('garment_name') or v.get('name') or ''
    if sids:
        async for s in db.vendor_shipments.find({'id': {'$in': list(sids)}},
                                                {'_id': 0, 'id': 1, 'shipment_number': 1}):
            ships[s['id']] = s.get('shipment_number') or ''
    if rids:
        async for s in db.dewi_rnd_sample_requests.find({'id': {'$in': list(rids)}},
                                                        {'_id': 0, 'id': 1, 'sample_code': 1}):
            samples[s['id']] = s.get('sample_code') or ''
    for d in docs:
        d['vendor_name'] = d.get('vendor_name') or vendors.get(d.get('vendor_id'), '')
        d['original_shipment_number'] = ships.get(d.get('original_shipment_id'), '')
        d['sample_code'] = d.get('sample_code') or samples.get(d.get('sample_request_id'), '')
    return docs


# ─── LIST ────────────────────────────────────────────────────────────────────
@router.get('')
async def list_requests(
    status:            Optional[str] = None,
    request_type:      Optional[str] = Query(None, description="Filter by SSOT discriminator: rnd_sample|internal_issuance|vendor_additional|vendor_replacement"),
    sample_request_id: Optional[str] = None,
    style_id:          Optional[str] = None,
    divisi:            Optional[str] = None,
    vendor_id:         Optional[str] = None,
    urgent_only:       Optional[bool] = False,
    search:            Optional[str] = None,
    limit:             int = Query(200, ge=1, le=1000),
    user: dict = Depends(require_auth),
):
    db = get_db()
    q: dict = {}
    if status:
        q['status'] = status
    if request_type:
        q['request_type'] = request_type
    if sample_request_id:
        q['sample_request_id'] = sample_request_id
    if style_id:
        q['style_id'] = style_id
    if divisi:
        q['divisi'] = divisi
    if vendor_id:
        q['vendor_id'] = vendor_id
    if urgent_only:
        q['urgent'] = True
    if search:
        rx = re.escape(search)
        q['$or'] = [
            {'request_code':   {'$regex': rx, '$options': 'i'}},
            {'style_code':     {'$regex': rx, '$options': 'i'}},
            {'style_name':     {'$regex': rx, '$options': 'i'}},
            {'requester_name': {'$regex': rx, '$options': 'i'}},
            {'divisi':         {'$regex': rx, '$options': 'i'}},
        ]
    items = await db.dewi_accessory_requests.find(q).sort('created_at', -1).limit(limit).to_list(length=limit)
    return [serialize(it) for it in await _enrich_labels(db, items)]


# ─── DETAIL ──────────────────────────────────────────────────────────────────
@router.get('/{request_id}')
async def get_request(request_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    doc = await db.dewi_accessory_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    return serialize((await _enrich_labels(db, [doc]))[0])


# ─── CREATE ──────────────────────────────────────────────────────────────────
@router.post('')
async def create_request(body: dict, user: dict = Depends(require_auth)):
    """Create accessory request. Supports all SSOT request_types:
       rnd_sample | internal_issuance | vendor_additional | vendor_replacement.

       Defaults to 'rnd_sample' when `request_type` is omitted (backward compat).
    """
    db = get_db()

    items = body.get('items') or []
    if not items:
        raise HTTPException(400, 'Minimal 1 item aksesoris harus diisi')
    status = str(body.get('status') or 'draft').strip().lower()
    if status not in CREATE_STATUSES:
        raise HTTPException(400, 'Permintaan baru hanya bisa disimpan sebagai draf atau langsung diajukan. '
                                 'Menyiapkan, menyerahkan, dan menolak dilakukan dari Inbox Approval.')

    rt = _normalize_request_type(body.get('request_type'))
    # 2026-11-10: baris yang memilih master diambil kode/nama/satuannya dari master (sebelum nomor dibuat)
    norm_items = await _link_master_items(db, [_norm_item(it) for it in items])
    # 2026-11-06 (Tahap 2): divisi dari daftar tunggal (menentukan akun beban saat diserahkan)
    from core.accessory_issue import DIVISION_NAMES, normalize_division
    divisi_raw = (body.get('divisi') or '').strip()
    divisi = normalize_division(divisi_raw)
    if divisi_raw and not divisi:
        raise HTTPException(400, f"Divisi '{divisi_raw}' tidak dikenal. Pilih salah satu: "
                                 f"{', '.join(DIVISION_NAMES)}.")
    sample_id = body.get('sample_request_id') or ''
    style_id  = body.get('style_id') or ''

    style_code = body.get('style_code') or ''
    style_name = body.get('style_name') or ''

    # Auto-resolve style info if not provided (rnd_sample type only)
    if rt == 'rnd_sample' and style_id and not (style_code and style_name):
        st = await db.dewi_rnd_styles.find_one({'id': style_id})
        if st:
            style_code = style_code or st.get('style_code', '')
            style_name = style_name or st.get('style_name', '')

    # Generate code with type-specific prefix when none supplied
    today = fmt_wib('%y%m%d')
    prefix_map = {
        'rnd_sample':         'REQ-AKS',
        'internal_issuance':  'INT-REQ',
        'vendor_additional':  'ACC-ADD',
        'vendor_replacement': 'ACC-RPL',
    }
    prefix = prefix_map.get(rt, 'REQ-AKS')
    # SESI #27 — SATU PINTU kebijakan penomoran (dulu: nomor ketikan diterima apa pun
    # bentuknya, tanpa pemeriksaan pola maupun nomor kembar). `{TIPE}` menjaga empat
    # seri (sampel R&D · pengeluaran internal · tambahan vendor · pengganti vendor)
    # tetap terpisah seperti sekarang.
    from core.doc_number_policy import issue_number
    code = await issue_number(db, "dewi_accessory_requests.request_code",
                              ctx={"TIPE": prefix},
                              requested=(body.get('request_code') or '').strip())

    doc = {
        'id': sid(),
        'request_code': code,
        'request_type': rt,
        # rnd_sample fields
        'sample_request_id': sample_id,
        'style_id': style_id,
        'style_code': style_code,
        'style_name': style_name,
        # internal_issuance fields
        'divisi':       divisi,
        'purpose':      body.get('purpose', ''),
        'admin_notes':  body.get('admin_notes', ''),
        # vendor_*  fields
        'vendor_id':              body.get('vendor_id', ''),
        'original_shipment_id':   body.get('original_shipment_id'),
        'po_id':                  body.get('po_id'),
        'po_number':              body.get('po_number', ''),
        'total_requested_qty':    body.get('total_requested_qty'),
        # common
        'items': norm_items,
        'urgent': bool(body.get('urgent', False)),
        'needed_by_date': body.get('needed_by_date', '') or body.get('needed_by', ''),
        'notes': body.get('notes', '') or body.get('reason', ''),
        'status': status,
        'submitted_at': now_utc() if status == 'submitted' else None,
        'requester_id': user['id'],
        # HR3: pemohon = karyawan (master); akun pembuat dicatat terpisah
        **(await _requester_fields(db, user, body.get('requester_employee_id'))),
        'created_by_name': user.get('name', ''),
        'allocated_by': None,
        'allocated_at': None,
        'delivered_by': None,
        'delivered_at': None,
        'rejection_reason': None,
        'created_at': now_utc(),
        'updated_at': now_utc(),
    }
    await db.dewi_accessory_requests.insert_one(doc)
    if status == 'submitted':
        await _notify_team(db, {**doc, 'sample_code': await _sample_code(db, sample_id)}, user, event='submitted')
    return serialize(doc)


async def _sample_code(db, sample_id: str) -> str:
    if not sample_id:
        return ''
    s = await db.dewi_rnd_sample_requests.find_one({'id': sample_id}, {'_id': 0, 'sample_code': 1})
    return (s or {}).get('sample_code') or ''


# ─── UPDATE (edit details — only if still draft/submitted) ───────────────────
@router.put('/{request_id}')
async def update_request(request_id: str, body: dict, user: dict = Depends(require_auth)):
    db = get_db()
    doc = await db.dewi_accessory_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    if doc['status'] in ('delivered', 'rejected', 'cancelled'):
        raise HTTPException(400, f"Tidak bisa edit request dengan status {doc['status']}")
    if 'status' in body and body.get('status') != doc.get('status'):
        raise HTTPException(400, 'Status permintaan tidak bisa diubah dari sini. Gunakan tombol Ajukan, '
                                 'Siapkan, Tandai Kirim, atau Tolak supaya stok dan jejak auditnya tercatat.')

    upd = {k: v for k, v in body.items()
           if k not in ('id', '_id', 'created_at', 'created_by', 'requester_id', 'request_code',
                        # HR3: pemohon hanya lewat master karyawan (di bawah), bukan nama ketikan
                        'requester_name', 'requester_employee_id', 'requester_employee_code', 'created_by_name')
           and k not in WORKFLOW_FIELDS}
    if body.get('requester_employee_id') and body['requester_employee_id'] != doc.get('requester_employee_id'):
        upd.update(await _requester_fields(db, user, body['requester_employee_id']))
    if 'items' in upd:
        # 2026-11-06 (Tahap 2): baris disusun ulang dengan bentuk yang SAMA seperti saat dibuat, dan
        # tautan baris lama (material_id + field tautan lain) dipertahankan bila klien tidak
        # mengirimnya — dicocokkan per kode barang, lalu per posisi bila nama/kodenya sama.
        old_items = list(doc.get('items') or [])
        new_items = []
        for idx, it in enumerate(upd['items'] or []):
            row = _norm_item(it)
            prev = None
            if row['material_code']:
                prev = next((o for o in old_items if (o.get('material_code') or '') == row['material_code']), None)
            if prev is None and idx < len(old_items):
                o = old_items[idx]
                if ((o.get('material_name') or '') == row['material_name']
                        or (o.get('material_code') or '') == row['material_code']):
                    prev = o
            if prev:
                extra = {k: v for k, v in prev.items() if k not in row}
                if not row['material_id']:
                    row['material_id'] = prev.get('material_id') or ''
                row = {**extra, **row}
            new_items.append(row)
        # 2026-11-10: tautan baru wajib master aktif; tautan lama yang tersimpan tidak ditolak ulang
        keep = {o.get('material_id') for o in old_items if o.get('material_id')}
        upd['items'] = await _link_master_items(db, new_items, keep_ids=keep)
    if 'divisi' in upd:
        from core.accessory_issue import DIVISION_NAMES, normalize_division
        dv = normalize_division(upd['divisi'])
        if (upd['divisi'] or '').strip() and not dv:
            raise HTTPException(400, f"Divisi '{upd['divisi']}' tidak dikenal. Pilih salah satu: "
                                     f"{', '.join(DIVISION_NAMES)}.")
        upd['divisi'] = dv
    upd['updated_at'] = now_utc()
    await db.dewi_accessory_requests.update_one({'id': request_id}, {'$set': upd})
    return {'ok': True}


# ─── SUBMIT (draft → submitted) ──────────────────────────────────────────────
@router.post('/{request_id}/submit')
async def submit_request(request_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    doc = await db.dewi_accessory_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    if doc['status'] != 'draft':
        raise HTTPException(400, 'Hanya request berstatus draft yang bisa disubmit')
    await db.dewi_accessory_requests.update_one(
        {'id': request_id},
        {'$set': {
            'status': 'submitted',
            'submitted_at': now_utc(),
            'updated_at': now_utc(),
        }}
    )
    await _notify_team(db, {**doc, 'status': 'submitted',
                            'sample_code': await _sample_code(db, doc.get('sample_request_id') or '')},
                       user, event='submitted')
    return {'ok': True}


# ─── ALLOCATE (submitted → allocated, by Admin Aksesoris) ────────────────────
@router.post('/{request_id}/allocate')
async def allocate_request(request_id: str, body: dict = None, user: dict = Depends(require_auth)):
    _assert_can_fulfil(user, 'accessories.approve', what='menyiapkan permintaan aksesoris')
    db = get_db()
    body = body or {}
    doc = await db.dewi_accessory_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    if doc['status'] != 'submitted':
        raise HTTPException(400, 'Hanya request berstatus submitted yang bisa di-allocate')
    await db.dewi_accessory_requests.update_one(
        {'id': request_id},
        {'$set': {
            'status': 'allocated',
            'allocated_by': user.get('name', ''),
            'allocated_at': now_utc(),
            'allocation_notes': body.get('notes', ''),
            'updated_at': now_utc(),
        }}
    )
    await _notify_requester(db, doc, user, event='allocated')
    return {'ok': True}


async def _apply_item_links(db, doc: dict, links) -> tuple[list, bool]:
    """Baris tanpa master (ketikan bebas sampel R&D) dipilihkan master oleh tim aksesoris:
    `links = [{index, material_id}]`. Dipakai serah (/deliver) dan draf pembelian (/purchase-draft)."""
    from core.accessory_issue import resolve_material
    items = [dict(it) for it in (doc.get('items') or [])]
    changed = False
    for ln in links or []:
        try:
            idx = int(ln.get('index'))
        except (TypeError, ValueError):
            continue
        mid = (ln.get('material_id') or '').strip()
        if 0 <= idx < len(items) and mid and not items[idx].get('material_id'):
            mat = await resolve_material(db, acc_id=mid)
            if not mat:
                raise HTTPException(400, f"Baris {idx + 1}: master aksesoris yang dipilih tidak ditemukan/nonaktif.")
            items[idx].update(material_id=mat['id'], material_code=items[idx].get('material_code') or mat.get('code', ''))
            changed = True
    return items, changed


# ─── DELIVER (allocated → delivered) ─────────────────────────────────────────
@router.post('/{request_id}/deliver')
async def deliver_request(request_id: str, body: dict = None, user: dict = Depends(require_auth)):
    """Serahkan barang ke pemohon.

    FASE 10 — untuk `request_type='internal_issuance'` endpoint ini SEKARANG
    MEMOTONG STOK (kartu stok bernilai + jurnal pemakaian), persis seperti jalur
    legacy `PUT /api/acc/internal-requests/{id}` status `Issued`. Tanpa ini, migrasi
    UI ke SSOT akan membuat stok tidak pernah berkurang — dan koleksi legacy
    `acc_internal_requests` tidak akan pernah bisa di-drop.

    Prinsip aman:
      * SEMUA baris divalidasi dulu (`check_availability`) — kalau satu baris kurang
        stok, tidak ada satu pun yang dipotong (tidak ada penyerahan separuh).
      * IDEMPOTEN: dokumen ditandai `stock_issued` sehingga klik ganda tidak memotong
        stok dua kali.

    2026-11-06 (Tahap 2) — SEMUA jenis permintaan memotong stok + berjurnal (dulu sampel R&D dan
    tambahan/pengganti vendor "terkirim" tanpa stok keluar). Akun beban: PO (maklon/internal) →
    sampel R&D → divisi pemohon (`core.accessory_issue.resolve_cost_target`). Permintaan ber-PO yang
    melebihi kebutuhan PO (dihitung bersama Kirim Material CMT) wajib beralasan
    (`over_issue_reason`). Baris tanpa master (sampel R&D diketik bebas) dipilihkan masternya lewat
    `item_links: [{index, material_id}]`.
    """
    _assert_can_fulfil(user, 'accessories.approve', 'wh.accessory.manage',
                       what='menyerahkan permintaan aksesoris')
    db = get_db()
    body = body or {}
    doc = await db.dewi_accessory_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    if doc['status'] != 'allocated':
        raise HTTPException(400, 'Hanya request berstatus allocated yang bisa di-deliver')

    from core import accessory_issue

    def _err(e):
        if getattr(e, 'code', ''):
            return HTTPException(getattr(e, 'status', 400), {'code': e.code, 'message': str(e), **(e.data or {})})
        return HTTPException(getattr(e, 'status', 400), str(e))

    items, links_changed = await _apply_item_links(db, doc, body.get('item_links'))

    issue_results: list[dict] = []
    over_lines: list = []
    reason = (body.get('over_issue_reason') or '').strip()
    target: dict = {}
    if not doc.get('stock_issued'):
        try:
            rows = await accessory_issue.check_availability(db, items)
            target = await accessory_issue.resolve_cost_target(
                db, divisi=doc.get('divisi', ''), po_id=doc.get('po_id') or '',
                request_type=doc.get('request_type') or 'rnd_sample')
            if not reason and doc.get('request_type') in accessory_issue.VENDOR_REQUEST_TYPES:
                # tambahan/pengganti vendor: alasan permintaannya sendiri = alasan kelebihan
                reason = (doc.get('notes') or '').strip()
            over_lines = await accessory_issue.guard_po_over_issue(db, target, rows, reason)
        except accessory_issue.IssueError as e:
            short = (e.data or {}).get('short_lines') if not getattr(e, 'code', '') else None
            if short:
                # 2026-11-10 (keputusan owner): layar serah menawarkan draf pembelian untuk kekurangannya
                raise HTTPException(400, {'code': 'stock_short', 'message': str(e), 'lines': short,
                                          'other_problems': (e.data or {}).get('other_problems', 0),
                                          'purchase_draft_number': doc.get('purchase_draft_number') or ''})
            raise _err(e)
        # kunci serah atomik: klik ganda / dua admin tidak memotong stok dua kali
        claim = await db.dewi_accessory_requests.update_one(
            {'id': request_id, 'status': 'allocated', 'stock_issued': {'$ne': True},
             'delivering': {'$ne': True}},
            {'$set': {'delivering': True, 'updated_at': now_utc()}})
        if not claim.matched_count:
            raise HTTPException(409, 'Permintaan ini sedang/sudah diserahkan pengguna lain — muat ulang daftar.')
        kind = {'rnd_sample': 'Sampel R&D', 'vendor_additional': 'Tambahan vendor',
                'vendor_replacement': 'Pengganti vendor'}.get(doc.get('request_type'), 'Permintaan internal')
        note = (f"{kind} {doc.get('request_code', '')}"
                f"{' · PO ' + target['po_number'] if target.get('po_number') else ''}"
                f"{' · ' + target['divisi'] if target.get('divisi') and not target.get('po_id') else ''}")
        try:
            for row in rows:
                try:
                    res = await accessory_issue.issue_accessory(
                        db, user, acc_id=row['material']['id'], qty=row['qty'],
                        notes=note, ref_type='accessory_request', ref_id=request_id,
                        target=target, over_issue_reason=reason if over_lines else '',
                    )
                except accessory_issue.IssueError as e:
                    # Sudah lolos pra-validasi; kalau tetap gagal (mis. balapan), laporkan
                    # apa yang SUDAH terpotong supaya operator bisa menelusuri.
                    raise HTTPException(
                        400, f"{str(e)} — {len(issue_results)} baris sudah terlanjur dikeluarkan; "
                             f"periksa kartu stok aksesoris.")
                issue_results.append({
                    'material_id': res['material_id'], 'material_code': res['material_code'],
                    'material_name': res['material_name'], 'qty': res['qty_issued'],
                    'unit': res['unit'], 'unit_cost': res['unit_cost'], 'value': res['value'],
                    'movement_id': res.get('movement_id', ''),
                    'je_number': (res.get('je') or {}).get('je_number', ''),
                    'je_posted': bool((res.get('je') or {}).get('posted')),
                    'je_error': '' if (res.get('je') or {}).get('posted') else (res.get('je') or {}).get('error', ''),
                })
        except BaseException:
            if not issue_results:
                await db.dewi_accessory_requests.update_one({'id': request_id}, {'$set': {'delivering': False}})
            else:
                # sebagian sudah terpotong: simpan jejaknya & biarkan terkunci (serah ulang = potong dobel)
                await db.dewi_accessory_requests.update_one({'id': request_id}, {'$set': {
                    'stock_issue_results': issue_results, 'stock_issue_partial': True,
                    'issue_linked_po': True, 'updated_at': now_utc()}})
            raise

    update = {
        'status': 'delivered',
        'delivered_by': user.get('name', ''),
        'delivered_at': now_utc(),
        'delivery_notes': body.get('notes', ''),
        'delivering': False,
        'updated_at': now_utc(),
    }
    if links_changed:
        update['items'] = items
    if issue_results:
        update['stock_issued'] = True
        update['stock_issue_results'] = issue_results
        update['stock_issued_at'] = now_utc()
        update['cost_target'] = target.get('cost_target', '')
        # baris kartu stok sudah membawa po_id → tidak dihitung ulang dari dokumen ini
        update['issue_linked_po'] = True
        if over_lines:
            update['over_issue_reason'] = reason
            update['over_issue_lines'] = over_lines
    await db.dewi_accessory_requests.update_one({'id': request_id}, {'$set': update})
    await _close_team_action(db, request_id)
    await _notify_requester(db, {**doc, 'items': items}, user, event='delivered')
    return {
        'ok': True,
        'stock_issued': bool(issue_results),
        'issued_items': issue_results,
        'cost_target': target.get('cost_target', ''),
        'over_issue_lines': over_lines,
        'total_value': round(sum(x['value'] for x in issue_results), 2),
    }


# ─── REJECT ──────────────────────────────────────────────────────────────────
@router.post('/{request_id}/reject')
async def reject_request(request_id: str, body: dict = None, user: dict = Depends(require_auth)):
    _assert_can_fulfil(user, 'accessories.approve', 'accessories.manage',
                       what='menolak permintaan aksesoris')
    db = get_db()
    body = body or {}
    doc = await db.dewi_accessory_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    if doc['status'] in ('delivered', 'cancelled'):
        raise HTTPException(400, f"Tidak bisa reject request dengan status {doc['status']}")
    if doc.get('stock_issued') or doc.get('stock_issue_partial'):
        # 2026-11-06 (Tahap 2): stok sudah (sebagian) keluar — menolak tidak mengembalikan stok
        raise HTTPException(400, 'Stok permintaan ini sudah (sebagian) dikeluarkan, jadi tidak bisa ditolak. '
                                 'Periksa kartu stok aksesoris.')
    # 2026-11-06 (pola P9): kunci serah (Tahap 1) ikut dihormati — dulu "tolak" bisa menimpa permintaan
    # yang sedang/baru saja diserahkan (stok sudah terpotong, status tampak ditolak).
    res = await db.dewi_accessory_requests.update_one(
        {'id': request_id, 'status': doc['status'], 'stock_issued': {'$ne': True},
         'delivering': {'$ne': True}},
        {'$set': {
            'status': 'rejected',
            'rejection_reason': body.get('reason', ''),
            'rejected_by': user.get('name', ''),
            'rejected_at': now_utc(),
            'updated_at': now_utc(),
        }}
    )
    if not res.matched_count:
        raise HTTPException(409, 'Permintaan ini sedang/baru saja diproses pengguna lain — muat ulang daftar.')
    await _close_team_action(db, request_id)
    await _notify_requester(db, doc, user, event='rejected', reason=body.get('reason', ''))
    return {'ok': True}


# ─── CANCEL (peminta menarik permintaan yang belum diserahkan) ───────────────
def _assert_can_cancel(user: dict, doc: dict):
    """2026-11-10: peminta sendiri, tim R&D (untuk sampel R&D), atau manajemen.

    Tim aksesoris memakai Tolak (beralasan), bukan Batalkan."""
    from routes.shared import PORTAL_ACCESS, can_act, has_perm
    if doc.get('requester_id') and doc.get('requester_id') == user.get('id'):
        return
    if (doc.get('request_type') or 'rnd_sample') == 'rnd_sample' and can_act(
            user, 'rnd.manage', legacy_roles=PORTAL_ACCESS.get('rnd', ())):
        return
    if has_perm(user) or (user.get('role') or '').lower() in MGMT_ROLES:
        return
    raise HTTPException(403, 'Hanya peminta, tim R&D (untuk sampel R&D), atau manajemen yang bisa '
                             'membatalkan permintaan ini.')


@router.post('/{request_id}/cancel')
async def cancel_request(request_id: str, body: dict = None, user: dict = Depends(require_auth)):
    db = get_db()
    body = body or {}
    doc = await db.dewi_accessory_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    _assert_can_cancel(user, doc)
    if doc['status'] not in CANCELLABLE_STATUSES:
        label = {'delivered': 'sudah diserahkan', 'rejected': 'sudah ditolak',
                 'cancelled': 'sudah dibatalkan'}.get(doc['status'], doc['status'])
        raise HTTPException(400, f"Permintaan ini {label}, jadi tidak bisa dibatalkan.")
    if doc.get('stock_issued') or doc.get('stock_issue_partial'):
        raise HTTPException(400, 'Stok permintaan ini sudah (sebagian) dikeluarkan, jadi tidak bisa dibatalkan. '
                                 'Periksa kartu stok aksesoris.')
    reason = str(body.get('reason') or '').strip()
    if not reason:
        raise HTTPException(400, 'Alasan pembatalan wajib diisi supaya tim aksesoris tahu.')
    # kunci serah dihormati — sama dengan /reject
    res = await db.dewi_accessory_requests.update_one(
        {'id': request_id, 'status': doc['status'], 'stock_issued': {'$ne': True},
         'delivering': {'$ne': True}},
        {'$set': {
            'status': 'cancelled',
            'cancel_reason': reason,
            'cancelled_by': user.get('name', ''),
            'cancelled_by_id': user.get('id'),
            'cancelled_at': now_utc(),
            'updated_at': now_utc(),
        }}
    )
    if not res.matched_count:
        raise HTTPException(409, 'Permintaan ini sedang/baru saja diproses tim aksesoris — muat ulang daftar.')
    await _close_team_action(db, request_id)
    if doc['status'] in ('submitted', 'allocated'):
        await _notify_team(db, doc, user, event='cancelled', reason=reason)
    await _notify_requester(db, doc, user, event='cancelled', reason=reason)
    return {'ok': True}


# ─── DRAF PEMBELIAN UNTUK KEKURANGAN STOK (keputusan owner 2026-11-10) ───────
PR_DEAD_STATUSES = ('Rejected', 'Cancelled')


@router.post('/{request_id}/purchase-draft')
async def create_purchase_draft(request_id: str, body: dict = None, user: dict = Depends(require_auth)):
    """Stok kurang saat serah → SATU draf Request Pembelian Aksesoris berisi kekurangannya.

    Tidak memotong / memesan stok apa pun. Draf diperiksa lalu diajukan lewat menu Pembelian
    Aksesoris (diteruskan ke Permintaan Pengadaan — persetujuan pembelian biasa). Idempoten: selama
    draf sebelumnya masih hidup, nomor yang sama dikembalikan."""
    _assert_can_fulfil(user, 'accessories.approve', 'wh.accessory.manage',
                       what='membuat draf pembelian untuk kekurangan aksesoris')
    db = get_db()
    doc = await db.dewi_accessory_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    if doc['status'] not in ('submitted', 'allocated'):
        raise HTTPException(400, 'Draf pembelian hanya untuk permintaan yang belum diserahkan.')
    if doc.get('purchase_draft_id'):
        old = await db.acc_purchase_requests.find_one({'id': doc['purchase_draft_id']},
                                                      {'_id': 0, 'id': 1, 'pr_number': 1, 'status': 1})
        if old and old.get('status') not in PR_DEAD_STATUSES:
            return {'ok': True, 'already': True, 'pr_id': old['id'], 'pr_number': old.get('pr_number', ''),
                    'pr_status': old.get('status', '')}

    from core import accessory_issue
    # master yang dipilih di form serah ikut dihitung — dan disimpan, supaya serah berikutnya tidak memilih ulang
    items, links_changed = await _apply_item_links(db, doc, (body or {}).get('item_links'))
    if links_changed:
        await db.dewi_accessory_requests.update_one({'id': request_id, 'status': doc['status']},
                                                    {'$set': {'items': items, 'updated_at': now_utc()}})
    short = await accessory_issue.shortage_lines(db, items)
    if not short['lines']:
        msg = 'Stok semua barang yang sudah tertaut ke master cukup — tidak ada yang perlu dibeli.'
        if short['unlinked']:
            msg += f" {short['unlinked']} baris belum tertaut; pilih masternya dulu di form serah."
        raise HTTPException(400, msg)
    code = doc.get('request_code') or ''
    kind = TYPE_LABELS.get(doc.get('request_type') or 'rnd_sample', 'Permintaan')
    from routes.dewi_accessories_purchase import new_purchase_request
    pr = await new_purchase_request(db, user, {
        'priority': 'Urgent' if doc.get('urgent') else 'Normal',
        'purpose': f"Kekurangan stok untuk permintaan {code}",
        'notes': (f"Dibuat dari permintaan aksesoris {code} ({kind}, {_context(doc)}). "
                  "Periksa jumlah, harga, dan pemasok, lalu ajukan."),
        'items': [{
            'acc_id': ln['material_id'], 'acc_code': ln['material_code'], 'acc_name': ln['material_name'],
            'qty_requested': ln['short'], 'unit': ln['unit'], 'estimated_price': ln['unit_cost'],
            'notes': f"Untuk {code}: butuh {ln['needed']:g}, stok bisa dipakai {ln['usable']:g}",
        } for ln in short['lines']],
        'source_type': 'accessory_request', 'source_id': doc['id'], 'source_ref': code,
    })
    await db.dewi_accessory_requests.update_one({'id': request_id}, {'$set': {
        'purchase_draft_id': pr['id'], 'purchase_draft_number': pr.get('pr_number', ''),
        'purchase_draft_at': now_utc(), 'updated_at': now_utc()}})
    return {'ok': True, 'already': False, 'pr_id': pr['id'], 'pr_number': pr.get('pr_number', ''),
            'pr_status': pr.get('status', ''), 'lines': short['lines'], 'unlinked': short['unlinked']}


# ─── DELETE ──────────────────────────────────────────────────────────────────
@router.delete('/{request_id}', dependencies=only(*WAREHOUSE_ROLES, perm="wh.accessory.manage"))  # T-01 2.3
async def delete_request(request_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    doc = await db.dewi_accessory_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    if doc['status'] not in ('draft', 'rejected', 'cancelled'):
        raise HTTPException(400, 'Hanya request berstatus draft/rejected/cancelled yang bisa dihapus')
    await db.dewi_accessory_requests.delete_one({'id': request_id})
    return {'ok': True}


# ─── STATS / DASHBOARD ───────────────────────────────────────────────────────
@router.get('/stats/summary')
async def stats_summary(request_type: Optional[str] = Query(None, description="Batasi ke satu jenis (layar R&D: rnd_sample)"),
                        user: dict = Depends(require_auth)):
    """Ringkasan per status. 2026-11-10: `request_type` membatasi hitungan ke satu jenis — kartu
    ringkasan R&D dulu menghitung SEMUA jenis permintaan (divisi & vendor ikut) padahal daftarnya
    hanya sampel R&D. Filter jenis sama persis dengan daftar (`list_requests`)."""
    db = get_db()
    q = {'request_type': request_type} if request_type else {}
    by_status: dict = {}
    raw_by_type: dict = {}
    urgent_pending = 0
    async for row in db.dewi_accessory_requests.find(q, {'_id': 0, 'status': 1, 'request_type': 1, 'urgent': 1}):
        st = row.get('status')
        by_status[st] = by_status.get(st, 0) + 1
        rt = row.get('request_type') or 'rnd_sample'     # dokumen lama tanpa jenis = sampel R&D
        raw_by_type[rt] = raw_by_type.get(rt, 0) + 1
        if row.get('urgent') is True and st in ('submitted', 'allocated'):
            urgent_pending += 1
    by_request_type = {k: raw_by_type.get(k, 0) for k in
                       ('rnd_sample', 'internal_issuance', 'vendor_additional', 'vendor_replacement')}
    total = sum(by_status.values())
    return {
        'total': total,
        'draft':     by_status.get('draft', 0),
        'submitted': by_status.get('submitted', 0),
        'allocated': by_status.get('allocated', 0),
        'delivered': by_status.get('delivered', 0),
        'rejected':  by_status.get('rejected', 0),
        'cancelled': by_status.get('cancelled', 0),
        'urgent_pending': urgent_pending,
        'by_request_type': by_request_type,
    }


# ─── STATUS AKSESORIS PER SAMPEL (daftar Sample Request, keputusan owner 2026-11-10) ───
# Status sample TIDAK berubah karena aksesoris; daftar sample hanya diberi keterangan
# "Aksesoris: menunggu / disiapkan / terkirim / ditolak". Permintaan yang dibatalkan diabaikan.
async def accessory_status_by_sample(db, sample_ids) -> dict:
    """{sample_id: {state, total, delivered, open, rejected}} untuk sampel yang punya permintaan aktif.

    state: 'submitted' (ada yang menunggu/draf) → 'allocated' (ada yang disiapkan) → 'delivered'
    (semua yang tidak ditolak sudah diserahkan) → 'rejected' (semuanya ditolak)."""
    ids = [s for s in {*(sample_ids or [])} if s]
    if not ids:
        return {}
    counts: dict = {}
    async for r in db.dewi_accessory_requests.find({'sample_request_id': {'$in': ids}},
                                                   {'_id': 0, 'sample_request_id': 1, 'status': 1}):
        st = r.get('status') or 'draft'
        if st == 'cancelled':
            continue
        c = counts.setdefault(r['sample_request_id'], {})
        c[st] = c.get(st, 0) + 1
    out = {}
    for sid_, c in counts.items():
        waiting = c.get('draft', 0) + c.get('submitted', 0)
        state = ('submitted' if waiting else 'allocated' if c.get('allocated') else
                 'delivered' if c.get('delivered') else 'rejected')
        out[sid_] = {'state': state, 'total': sum(c.values()), 'delivered': c.get('delivered', 0),
                     'open': waiting + c.get('allocated', 0), 'rejected': c.get('rejected', 0)}
    return out
