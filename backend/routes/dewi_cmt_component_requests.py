"""Session 27 — GAP-P2 CMT Component Shortage Request
CMT (Contract Manufacturing partner) mengajukan permintaan komponen yang kurang
(misal: lengan, kerah, saku, lining) ke internal team via Admin Packing → SPV Cutting.

Status workflow:
  pending → cutting → ready → delivered
                            └─→ rejected/cancelled

Request type:
  - component  (cutting/sewing parts)
  - accessory  (button, zipper, label) — GAP-P3 dicover di module ini juga
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from database import get_db
from auth import require_auth
from datetime import datetime, timezone
from typing import Optional
import uuid
import re
from core.authz import only  # T-01 2.3
from core.roles import PRODUCTION_ROLES  # T-01 2.3
from utils.waktu import fmt_wib
# PROD-02 (temuan 2026-09-23): tiga endpoint tulis hanya require_auth → gerbang peran produksi + maklon
_WRITE_ROLES = tuple(dict.fromkeys(PRODUCTION_ROLES + ("admin_maklon", "ppic", "manager_produksi")))

router = APIRouter(prefix="/api/dewi/cmt-component-requests", tags=["Production-CMT-Shortage-Requests"])


def now_utc():
    return datetime.now(timezone.utc)


def sid():
    return str(uuid.uuid4())


async def _resolve_product_from_master(db, body: dict) -> dict:
    """F14b — identitas produk permintaan komponen: MASTER menang atas ketikan.

    Kenapa dipisah jadi fungsi: supaya ada SATU tempat yang memutuskan. Kalau
    setiap endpoint menyalin logikanya, suatu hari salah satunya lupa dan
    dokumen dengan nama ketikan bocor masuk lagi tanpa terlihat.

    `model_id` sengaja TIDAK diwajibkan di sini (berbeda dengan Launching):
    permintaan komponen kadang lahir dari inspeksi vendor sebelum produknya
    ditentukan. Yang dijamin: kalau `model_id` DIISI, ia harus benar-benar ada
    di master, dan nama produk mengikuti master — bukan campuran keduanya.
    """
    model_id = (body.get('model_id') or '').strip()
    if not model_id:
        return {
            'model_id': '',
            'model_code': '',
            'product_name': body.get('product_name', ''),
        }
    m = await db.rahaza_models.find_one({'id': model_id}, {'_id': 0})
    if not m:
        raise HTTPException(
            400, f"Produk '{model_id}' tidak ada di Master Produk. Pilih dari "
                 f"daftar master, atau kosongkan kalau permintaan ini memang "
                 f"belum menempel pada satu produk.")
    return {
        'model_id': model_id,
        'model_code': m.get('code') or '',
        'product_name': m.get('name') or '',
    }


async def _resolve_partner_from_master(db, body: dict) -> dict:
    """2026-11-07 (Tahap 5): vendor CMT permintaan = master `vendor_partners`, nama mengikuti master.

    Form dulu mengetik nama vendor bebas ⇒ `cmt_partner_id`/`vendor_id` selalu kosong, sehingga penyaring
    per vendor dan rekap tagihan vendor tidak pernah cocok. Kalau `cmt_partner_id` dikirim, ia WAJIB ada di
    master dan nama ketikan diabaikan. Tanpa id (dokumen lama / lahir dari inspeksi) = apa adanya."""
    pid = (body.get('cmt_partner_id') or '').strip()
    if not pid:
        return {}
    v = await db.vendor_partners.find_one({'id': pid}, {'_id': 0, 'id': 1, 'name': 1, 'garment_name': 1})
    if not v:
        raise HTTPException(400, 'Vendor CMT yang dipilih tidak ada di master Vendor CMT — pilih dari daftar.')
    name = v.get('name') or v.get('garment_name') or ''
    out = {'cmt_partner_id': pid, 'cmt_partner_name': name}
    if not (body.get('vendor_id') or '').strip() or body.get('vendor_id') == pid:
        out.update({'vendor_id': pid, 'vendor_name': name})
    return out


def serialize(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop('_id', None)
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


VALID_TYPES = {'component', 'accessory'}
VALID_STATUSES = {'pending', 'cutting', 'ready', 'delivered', 'rejected', 'cancelled'}
# 2026-11-06 (Tahap 2): barang yang diminta WAJIB dari master material dengan jenis yang benar —
# komponen = bahan (kain/benang/interlining), aksesoris = aksesoris/kemasan. Produk jadi (FG)
# DA tidak boleh diminta lewat sini. Ketikan bebas tidak diterima lagi.
CATEGORY_FOR_TYPE = {'component': 'bahan', 'accessory': 'aksesoris'}
CATEGORY_LABEL = {'bahan': 'bahan (kain/benang)', 'aksesoris': 'aksesoris'}


async def _resolve_items_from_master(db, req_type: str, items: list) -> list:
    """Baris permintaan → baris bertaut master material. 400 bila ada yang tidak sah."""
    from core.material_fields import category_of
    want = CATEGORY_FOR_TYPE.get(req_type, 'bahan')
    ids = [str(it.get('material_id') or '').strip() for it in items or []]
    if not ids or any(not i for i in ids):
        raise HTTPException(400, 'Setiap baris wajib memilih barang dari Master Material '
                                 f"({CATEGORY_LABEL[want]}) — ketik bebas tidak diterima.")
    mats = {m['id']: m async for m in db.rahaza_materials.find({'id': {'$in': ids}}, {'_id': 0})}
    out = []
    for it, mid in zip(items, ids):
        m = mats.get(mid)
        if not m or m.get('active') is False:
            raise HTTPException(400, f"Barang '{mid}' tidak ada / nonaktif di Master Material.")
        cat = category_of(m.get('type'))
        if cat == 'fg':
            raise HTTPException(400, f"{m.get('code')} adalah produk jadi DA — tidak boleh diminta sebagai komponen.")
        if cat != want:
            raise HTTPException(400, f"{m.get('code')} bukan {CATEGORY_LABEL[want]} — pilih barang dengan jenis "
                                     "yang sesuai jenis permintaan.")
        qty = float(it.get('qty', 0) or 0)
        if qty <= 0:
            raise HTTPException(400, f"Qty {m.get('code')} harus lebih dari 0.")
        out.append({'material_id': mid, 'material_code': m.get('code', ''), 'material_name': m.get('name', ''),
                    'component_type': it.get('component_type') or m.get('name', ''),
                    'size': it.get('size', ''), 'color': it.get('color', ''), 'qty': qty,
                    'unit': m.get('unit') or it.get('unit', 'pcs'), 'notes': it.get('notes', '')})
    return out


async def _issue_on_delivery(db, doc: dict, user: dict) -> dict | None:
    """2026-11-06 (Tahap 2): "Terkirim" = barang KELUAR dari gudang lewat mesin pengeluaran material
    yang sama (`core.material_issue_engine.issue_material_issue`): stok berkurang + jurnal biaya.
    PO maklon → biaya bahan klien maklon (5-4100); PO internal → WIP. Idempoten per permintaan."""
    from core import material_issue_engine as mie
    from routes.rahaza_inventory_shared import _gen_mi_number, _now as _mi_now, _uid as _mi_uid
    if doc.get('material_issue_id'):
        return None
    items = doc.get('items') or []
    if not items or any(not it.get('material_id') for it in items):
        raise HTTPException(400, 'Permintaan ini punya baris tanpa barang dari Master Material — ubah permintaan '
                                 'dan pilih barangnya dulu sebelum ditandai terkirim.')
    po = await db.production_pos.find_one({'id': doc.get('po_id')}, {'_id': 0}) if doc.get('po_id') else None
    maklon = (po or {}).get('business_type') == 'maklon'
    mi_items, locs = [], {}
    for it in items:
        loc, _avail = await mie.best_location_for(db, it['material_id'], float(it.get('qty') or 0))
        if not loc:
            raise HTTPException(400, f"{it.get('material_code') or it['material_id']} belum punya stok di gudang "
                                     "mana pun — catat penerimaan/opname dulu.")
        locs[it['material_id']] = loc
        mi_items.append({'id': _mi_uid(), 'material_id': it['material_id'], 'qty_required': float(it.get('qty') or 0),
                         'qty_issued': 0, 'location_id': loc,
                         'notes': f"Komponen kurang {doc.get('request_code', '')}"})
    mi = {'id': _mi_uid(), 'mi_number': await _gen_mi_number(db), 'work_order_id': None, 'wo_number_snapshot': '',
          'job_id': None, 'production_po_id': doc.get('po_id') or None,
          'po_number_snapshot': doc.get('po_number', ''), 'vendor_id': doc.get('vendor_id', ''),
          'vendor_name': doc.get('vendor_name', ''),
          'business_type': (po or {}).get('business_type') or '', 'cost_target': 'maklon' if maklon else None,
          'component_request_id': doc['id'], 'items': mi_items, 'status': 'pending_approval',
          'source': 'cmt_component_request',
          'notes': f"Otomatis dari permintaan komponen kurang {doc.get('request_code', '')}",
          'created_by': user.get('id'), 'created_by_name': user.get('name', ''),
          'created_at': _mi_now(), 'updated_at': _mi_now()}
    await db.rahaza_material_issues.insert_one(dict(mi))
    try:
        fresh = await mie.issue_material_issue(db, mi, user, loc_overrides=locs, ref_type='cmt_component_request')
    except mie.MaterialShortage as e:
        await db.rahaza_material_issues.update_one({'id': mi['id']}, {'$set': {'status': 'rejected',
                                                                               'reject_reason': str(e)}})
        raise HTTPException(400, f"{e} — permintaan belum bisa ditandai terkirim.")
    except mie.BomMissing as e:
        await db.rahaza_material_issues.update_one({'id': mi['id']}, {'$set': {'status': 'rejected',
                                                                               'reject_reason': str(e)}})
        raise HTTPException(400, str(e))
    posting = fresh.get('_posting_result') or {}
    return {'material_issue_id': mi['id'], 'material_issue_number': mi['mi_number'],
            'gl_je_number': posting.get('je_number'), 'gl_error': None if posting.get('ok') else posting.get('error')}


# ─── LIST ────────────────────────────────────────────────────────────────────
@router.get('')
async def list_requests(
    status:       Optional[str] = None,
    cmt_partner:  Optional[str] = None,
    work_order:   Optional[str] = None,
    request_type: Optional[str] = None,
    search:       Optional[str] = None,
    limit:        int = Query(200, ge=1, le=1000),
    user: dict = Depends(require_auth),
):
    db = get_db()
    q: dict = {}
    if status:
        q['status'] = status
    if cmt_partner:
        q['cmt_partner_id'] = cmt_partner
    if work_order:
        q['work_order_id'] = work_order
    if request_type:
        q['request_type'] = request_type
    if search:
        rx = re.escape(search)
        q['$or'] = [
            {'request_code':    {'$regex': rx, '$options': 'i'}},
            {'cmt_partner_name':{'$regex': rx, '$options': 'i'}},
            {'product_name':    {'$regex': rx, '$options': 'i'}},
            {'work_order_code': {'$regex': rx, '$options': 'i'}},
        ]
    items = await db.dewi_cmt_component_requests.find(q).sort('created_at', -1).limit(limit).to_list(length=limit)
    return [serialize(it) for it in items]


# ─── DETAIL ──────────────────────────────────────────────────────────────────
@router.get('/{request_id}')
async def get_request(request_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    doc = await db.dewi_cmt_component_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    return serialize(doc)


# ─── CREATE ──────────────────────────────────────────────────────────────────
@router.post('', dependencies=only(*_WRITE_ROLES))  # PROD-02
async def create_request(body: dict, user: dict = Depends(require_auth)):
    db = get_db()

    req_type = body.get('request_type', 'component')
    if req_type not in VALID_TYPES:
        raise HTTPException(400, f'request_type harus salah satu dari: {VALID_TYPES}')

    items = body.get('items') or []
    if not items:
        raise HTTPException(400, 'Minimal 1 item harus diisi')
    # 2026-11-06 (Tahap 2): PO tertutup terkunci + barang wajib dari master material
    from core.po_lock import assert_po_open
    await assert_po_open(db, body.get('po_id'), 'permintaan komponen')
    items = await _resolve_items_from_master(db, req_type, items)

    today = fmt_wib('%y%m%d')
    prefix = 'REQ-CMP' if req_type == 'component' else 'REQ-AKS-CMT'
    # SESI #27 — SATU PINTU kebijakan penomoran. SEBELUM ini baris ini berbunyi
    # `body.get('request_code') or gen_prefixed_number(...)`: nomor ketikan staf
    # diterima APA PUN bentuknya, TANPA pemeriksaan pola dan TANPA pemeriksaan
    # kembar — dua permintaan bisa bernomor sama dan arsipnya tak bisa diurutkan.
    # `{TIPE}` menjaga dua seri (komponen vs aksesoris dari CMT) tetap terpisah.
    from core.doc_number_policy import issue_number
    code = await issue_number(db, "dewi_cmt_component_requests.request_code",
                              ctx={"TIPE": prefix},
                              requested=(body.get('request_code') or '').strip())

    doc = {
        'id': sid(),
        'request_code': code,
        'request_type': req_type,
        'cmt_partner_id':   body.get('cmt_partner_id', ''),
        'cmt_partner_name': body.get('cmt_partner_name', ''),
        'work_order_id':    body.get('work_order_id', ''),
        'work_order_code':  body.get('work_order_code', ''),
        # ── F14b — produk dari MASTER, bukan ketikan ─────────────────────────
        # Kalau `model_id` diberikan, nama & kode produk DIRESOLUSI dari
        # `rahaza_models` dan kiriman browser diabaikan. Alasannya: rekap
        # "komponen apa saja yang diminta untuk produk X" memecah diri sendiri
        # begitu satu produk punya dua ejaan ("Kemeja Pria Lengan Panjang" vs
        # "Kemeja Pria LP"), dan pecahnya tidak terlihat sebagai galat.
        **(await _resolve_product_from_master(db, body)),
        # ── FASE 5 (cacat MAT-1/MAT-3, audit 2026-07-31) ─────────────────────
        # Dulu ada LIMA permukaan untuk kebutuhan yang sama (Komponen Kurang,
        # Kirim Material ke CMT, material_requests dari inspeksi, Permintaan
        # Tambahan, retur material) dan 3 collection-nya bahkan tidak ada di DB.
        # Sekarang collection INI adalah SSOT permintaan komponen/material ke
        # CMT, dan WAJIB menunjuk PO + vendor + (bila lahir dari inspeksi)
        # inspection_id — supaya temuan kurang-kirim punya tindak lanjut yang
        # bisa dilacak, bukan angka mati.
        'po_id':            body.get('po_id', ''),
        'po_number':        body.get('po_number', ''),
        'vendor_id':        body.get('vendor_id') or body.get('cmt_partner_id', ''),
        'vendor_name':      body.get('vendor_name') or body.get('cmt_partner_name', ''),
        'inspection_id':    body.get('inspection_id', ''),
        'source_shipment_id': body.get('source_shipment_id', ''),
        'source_shipment_number': body.get('source_shipment_number', ''),
        'origin':           body.get('origin', 'manual'),   # manual | vendor_inspection
        'fulfilled_shipment_id': None,
        'fulfilled_shipment_number': None,
        # baris bertaut master material (lihat _resolve_items_from_master)
        'items': items,
        'material_issue_id': None,
        'material_issue_number': None,
        'urgent':         bool(body.get('urgent', False)),
        'needed_by_date': body.get('needed_by_date', ''),
        'notes':          body.get('notes', ''),
        # "Terkirim" hanya lewat set-status (memotong stok) — tidak boleh lahir langsung terkirim
        'status':         body.get('status') if body.get('status') in ('pending', 'cutting', 'ready') else 'pending',
        # Workflow tracking
        'requester_id':   user['id'],
        'requester_name': user.get('name', ''),
        'cutting_started_by': None,
        'cutting_started_at': None,
        'ready_by': None,
        'ready_at': None,
        'delivered_by': None,
        'delivered_at': None,
        'delivery_order_number': None,
        'rejection_reason': None,
        'created_at': now_utc(),
        'updated_at': now_utc(),
    }
    doc.update(await _resolve_partner_from_master(db, body))
    await db.dewi_cmt_component_requests.insert_one(doc)
    return serialize(doc)


# ─── UPDATE ──────────────────────────────────────────────────────────────────
@router.put('/{request_id}', dependencies=only(*_WRITE_ROLES))  # PROD-02
async def update_request(request_id: str, body: dict, user: dict = Depends(require_auth)):
    db = get_db()
    doc = await db.dewi_cmt_component_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    if doc['status'] in ('delivered', 'rejected', 'cancelled'):
        raise HTTPException(400, f"Tidak bisa edit status {doc['status']}")
    upd = {k: v for k, v in body.items() if k not in ('id', '_id', 'created_at', 'requester_id', 'request_code',
                                                      'status', 'material_issue_id', 'material_issue_number')}
    # F14b — identitas produk tidak boleh ditulis browser. Kalau `model_id`
    # dikirim, ia diresolusi ulang lewat SATU fungsi yang sama dengan create;
    # kalau tidak, nama produk yang tersimpan DIPERTAHANKAN apa adanya (bukan
    # ditimpa ketikan baru yang bisa berbeda ejaan).
    if 'cmt_partner_id' in body:
        upd.update(await _resolve_partner_from_master(db, body))
    if 'model_id' in body:
        upd.update(await _resolve_product_from_master(db, body))
    else:
        upd.pop('product_name', None)
        upd.pop('model_code', None)
    if 'items' in upd:
        # 2026-11-06 (Tahap 2): sama dengan create — barang wajib dari master, jenis sesuai
        upd['items'] = await _resolve_items_from_master(db, upd.get('request_type') or doc.get('request_type', 'component'),
                                                        upd['items'] or [])
    if 'request_type' in upd and upd['request_type'] not in VALID_TYPES:
        raise HTTPException(400, f'request_type harus salah satu dari: {VALID_TYPES}')
    upd['updated_at'] = now_utc()
    await db.dewi_cmt_component_requests.update_one({'id': request_id}, {'$set': upd})
    return {'ok': True}


# ─── SET STATUS (generic transition) ─────────────────────────────────────────
@router.post('/{request_id}/set-status', dependencies=only(*_WRITE_ROLES))  # PROD-02
async def set_status(request_id: str, body: dict, user: dict = Depends(require_auth)):
    db = get_db()
    new_status = (body or {}).get('status', '')
    if new_status not in VALID_STATUSES:
        raise HTTPException(400, f'status harus salah satu dari: {VALID_STATUSES}')
    doc = await db.dewi_cmt_component_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')

    # Transition validation (linear forward, allow rejection from non-final)
    cur = doc['status']
    order = ['pending', 'cutting', 'ready', 'delivered']
    if new_status in ('rejected', 'cancelled'):
        if cur in ('delivered',):
            raise HTTPException(400, 'Tidak bisa reject request yang sudah delivered')
    elif new_status in order and cur in order:
        if order.index(new_status) < order.index(cur):
            raise HTTPException(400, f'Transisi tidak diijinkan: {cur} → {new_status}')

    upd = {'status': new_status, 'updated_at': now_utc()}
    # 2026-11-06 (pola P1): isian "Catatan" di popup ubah status dulu dikirim layar tetapi tidak disimpan
    note = str((body or {}).get('notes') or '').strip()
    if note:
        upd['status_note'] = note[:1000]
    if new_status == 'cutting':
        upd['cutting_started_by'] = user.get('name', '')
        upd['cutting_started_at'] = now_utc()
    elif new_status == 'ready':
        upd['ready_by'] = user.get('name', '')
        upd['ready_at'] = now_utc()
    elif new_status == 'delivered':
        upd['delivered_by'] = user.get('name', '')
        upd['delivered_at'] = now_utc()
        if (body or {}).get('delivery_order_number'):
            upd['delivery_order_number'] = body['delivery_order_number']
    elif new_status == 'rejected':
        upd['rejection_reason'] = (body or {}).get('reason', '')

    issue = None
    if new_status == 'delivered' and cur != 'delivered':
        # 2026-11-06 (Tahap 2): PO tertutup terkunci; "Terkirim" memotong stok + membukukan biaya
        from core.po_lock import assert_po_open
        await assert_po_open(db, doc.get('po_id'), 'pengiriman komponen')
        issue = await _issue_on_delivery(db, doc, user)
        if issue:
            upd.update({'material_issue_id': issue['material_issue_id'],
                        'material_issue_number': issue['material_issue_number']})
    await db.dewi_cmt_component_requests.update_one({'id': request_id}, {'$set': upd})
    return {'ok': True, **({'material_issue': issue} if issue else {})}


# ─── DELETE ──────────────────────────────────────────────────────────────────
@router.delete('/{request_id}', dependencies=only(*PRODUCTION_ROLES))  # T-01 2.3
async def delete_request(request_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    doc = await db.dewi_cmt_component_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    if doc['status'] not in ('pending', 'rejected', 'cancelled'):
        raise HTTPException(400, 'Hanya pending/rejected/cancelled yang bisa dihapus')
    await db.dewi_cmt_component_requests.delete_one({'id': request_id})
    return {'ok': True}


# ─── STATS ───────────────────────────────────────────────────────────────────
@router.get('/stats/summary')
async def stats_summary(user: dict = Depends(require_auth)):
    db = get_db()
    by_status = {}
    async for row in db.dewi_cmt_component_requests.aggregate([{'$group': {'_id': '$status', 'count': {'$sum': 1}}}]):
        by_status[row['_id']] = row['count']

    urgent_pending = await db.dewi_cmt_component_requests.count_documents({
        'urgent': True,
        'status': {'$in': ['pending', 'cutting']}
    })
    return {
        'total': sum(by_status.values()),
        'pending':   by_status.get('pending', 0),
        'cutting':   by_status.get('cutting', 0),
        'ready':     by_status.get('ready', 0),
        'delivered': by_status.get('delivered', 0),
        'rejected':  by_status.get('rejected', 0),
        'urgent_pending': urgent_pending,
    }
