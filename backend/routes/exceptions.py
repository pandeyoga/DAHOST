"""Exception & Variance domain: Material Requests, Material Defect Reports,
Production Returns, Production Variances (over/under-production).

Moved out of server.py during Backend Refactor Phase 7
(see /app/BACKEND_REFACTOR_PLAN.md). Pure move — behavior is byte-for-byte
identical to the original definitions in server.py. Medium risk phase per
the plan (recently revised heavily in PRD Phase 16-19, still "hangat") —
every line below is an exact cut-paste from server.py, no logic was altered.
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from database import get_db
from auth import require_auth, check_role, log_activity, serialize_doc
from core.authz import wajib_centang
from routes.production_rbac import (assert_prod_admin, is_vendor, vendor_identity, deny_klien, require_write_actor)
from core.helpers import new_id, now, parse_date, to_end_of_day
from core.pagination import LEGACY_DEFAULT_CAP, _paginate_params, _paginated_envelope, _sort_params
from core.cmt_override import (apply_scope, effective_vendor_id, resolve_override,
                               stamp as ov_stamp)

logger = __import__('logging').getLogger(__name__)
router = APIRouter(prefix="/api", tags=["exceptions"])

# ── DA BUG-FIX: state machine exceptions di-enforce (referensi SOMMERVILLE
# menerima nilai/lompatan status bebas). Forward-only.
VARIANCE_STATUS_TRANSITIONS = {
    'Reported': ['Acknowledged', 'Resolved'],
    'Acknowledged': ['Resolved'],
    'Resolved': [],
}
# Urutan status retur (STATUS_OPTIONS referensi ProductionReturnModule).
RETURN_STATUS_FLOW = ['Repair Needed', 'In Repair', 'Completed', 'Shipped Back']


def _return_allowed_next(status):
    if status not in RETURN_STATUS_FLOW:
        return []
    return RETURN_STATUS_FLOW[RETURN_STATUS_FLOW.index(status) + 1:]

# ─── MATERIAL REQUESTS ──────────────────────────────────────────────────────
@router.get("/material-requests")
async def get_material_requests(request: Request):
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    query = {}
    sp = request.query_params
    await apply_scope(request, user, db, query, param_vendor_id=sp.get('vendor_id'))
    if sp.get('request_type'): query['request_type'] = sp['request_type']
    if sp.get('status'): query['status'] = sp['status']
    # Pagination (Phase 10A)
    page, per_page, skip, wants = _paginate_params(sp)
    sort = _sort_params(sp, 'created_at', 'desc',
                        allowed={'created_at', 'request_type', 'status', 'po_number'})
    total = await db.material_requests.count_documents(query) if wants else None
    limit = per_page if wants else LEGACY_DEFAULT_CAP
    docs = await db.material_requests.find(query, {'_id': 0}).sort(sort).skip(skip if wants else 0).limit(limit).to_list(limit)
    for d in docs:
        d['allowed_next'] = ['Approved', 'Rejected'] if d.get('status') == 'Pending' else []
    # ── PELACAKAN RANTAI PENGGANTI (keluhan pemilik 2026-06, INV-F28) ──────────
    # Persetujuan sudah menerbitkan surat jalan anak sejak lama, tetapi layar
    # hanya melihat nomornya — tidak ada kabar apakah surat jalan itu sudah
    # diterima vendor atau sudah diinspeksi, sehingga permintaan pengganti
    # "hilang" setelah disetujui. Status anak + jejak inspeksinya diambil batch
    # (2 query) supaya layar bisa menggambar pelacaknya.
    child_ids = [d.get('child_shipment_id') for d in docs if d.get('child_shipment_id')]
    if child_ids:
        ships = {s['id']: s for s in await db.vendor_shipments.find(
            {'id': {'$in': child_ids}},
            {'_id': 0, 'id': 1, 'status': 1, 'received_at': 1, 'shipment_number': 1}
        ).to_list(None)}
        insp_by_ship = {i['shipment_id']: i for i in await db.vendor_material_inspections.find(
            {'shipment_id': {'$in': child_ids}},
            {'_id': 0, 'id': 1, 'shipment_id': 1, 'created_at': 1}
        ).to_list(None)}
        for d in docs:
            cid = d.get('child_shipment_id')
            if not cid:
                continue
            cs = ships.get(cid) or {}
            insp = insp_by_ship.get(cid) or {}
            d['child_shipment_status'] = cs.get('status') or 'Missing'
            d['child_received_at'] = cs.get('received_at')
            d['child_inspection_id'] = insp.get('id') or ''
            d['child_inspected'] = bool(insp.get('id'))
            d['child_inspected_at'] = insp.get('created_at')
    # 2026-09-24 — aksesoris KURANG dari inspeksi asal ikut dibawa (dulu hilang: hanya material
    # yang tampil di form persetujuan dan child shipment tidak membawa aksesoris).
    for d in docs:
        if d.get('status') == 'Pending' and d.get('request_type') == 'ADDITIONAL':
            d['accessory_shortages'] = await _accessory_shortages_for_request(db, d)
    if wants:
        return _paginated_envelope(serialize_doc(docs), total, page, per_page)
    return serialize_doc(docs)


async def _accessory_shortages_for_request(db, req: dict) -> list:
    """Aksesoris yang masih KURANG untuk shipment asal permintaan ini.

    Sumber = baris inspeksi aksesoris (`vendor_material_inspection_items`, missing_qty>0)
    pada inspeksi yang melahirkan permintaan (atau inspeksi terakhir shipment asal),
    DIKURANGI aksesoris yang sudah dikirim lewat child shipment sebelumnya.
    """
    insp_id = req.get('inspection_id')
    if not insp_id:
        insp = await db.vendor_material_inspections.find_one(
            {'shipment_id': req.get('original_shipment_id')}, {'_id': 0, 'id': 1},
            sort=[('created_at', -1)])
        insp_id = (insp or {}).get('id')
    if not insp_id:
        return []
    rows = await db.vendor_material_inspection_items.find(
        {'inspection_id': insp_id, 'item_type': 'accessory', 'missing_qty': {'$gt': 0}},
        {'_id': 0}).to_list(None)
    if not rows:
        return []
    sent = {}
    async for a in db.accessory_shipment_items.find(
            {'parent_shipment_id': req.get('original_shipment_id')}, {'_id': 0}):
        k = a.get('accessory_id') or a.get('accessory_code')
        sent[k] = sent.get(k, 0) + int(a.get('qty_sent', 0) or 0)
    out = []
    for r in rows:
        k = r.get('accessory_id') or r.get('accessory_code')
        remaining = int(r.get('missing_qty', 0) or 0) - sent.get(k, 0)
        if remaining > 0:
            out.append({'accessory_id': r.get('accessory_id', ''), 'accessory_code': r.get('accessory_code', ''),
                        'accessory_name': r.get('accessory_name', ''), 'unit': r.get('unit', 'pcs'),
                        'missing_qty': remaining, 'qty_sent': remaining,
                        'notes': r.get('condition_notes', '')})
    return out

@router.post("/material-requests")
async def create_material_request(request: Request):
    user = await require_auth(request)
    deny_klien(user)
    require_write_actor(user, check_role)
    db = get_db()
    body = await request.json()
    _ov = await resolve_override(request, user, db)
    vendor_id = await effective_vendor_id(request, user, db, body.get('vendor_id'))
    if not vendor_id: raise HTTPException(400, 'vendor_id diperlukan')
    if body.get('request_type') not in ['ADDITIONAL', 'REPLACEMENT']: raise HTTPException(400, 'request_type harus ADDITIONAL atau REPLACEMENT')
    orig = await db.vendor_shipments.find_one({'id': body.get('original_shipment_id')}) if body.get('original_shipment_id') else None
    if not orig: raise HTTPException(404, 'Shipment asal tidak ditemukan')
    if _ov and orig.get('vendor_id') != _ov['vendor_id']:
        raise HTTPException(403, f"Pengiriman asal bukan milik {_ov['vendor_name']}")
    # Get PO number for request numbering
    po_number = body.get('po_number', '')
    po_id = body.get('po_id', '')
    if not po_number and po_id:
        po_doc = await db.production_pos.find_one({'id': po_id})
        if po_doc: po_number = po_doc.get('po_number', '')
    if not po_number:
        # Try to get from shipment items
        first_si = await db.vendor_shipment_items.find_one({'shipment_id': orig['id']})
        if first_si:
            po_number = first_si.get('po_number', '')
            if not po_id: po_id = first_si.get('po_id', '')
    # Count existing requests for THIS PO (not global)
    po_req_count = await db.material_requests.count_documents({'po_number': po_number, 'request_type': body['request_type']}) if po_number else await db.material_requests.count_documents({'request_type': body['request_type']})
    prefix = 'REQ-ADD' if body['request_type'] == 'ADDITIONAL' else 'REQ-RPL'
    req_number = f"{prefix}-{po_req_count + 1}-{po_number}" if po_number else f"{prefix}-{str(po_req_count + 1).zfill(4)}"
    items = body.get('items', [])
    # Phase 16: Defensive serial_number lookup
    # Jika item tidak punya serial_number (mis. resubmit dari request lama / data legacy),
    # auto-lookup dari vendor_shipment_items berdasarkan shipment_item_id atau matching sku+size+color
    if items and orig.get('id'):
        # Build lookup maps dari shipment items (sekali fetch, hindari N+1)
        ship_items_list = await db.vendor_shipment_items.find({'shipment_id': orig['id']}).to_list(None)
        si_by_id = {si['id']: si for si in ship_items_list if si.get('id')}
        si_by_sku_size_color = {}
        for si in ship_items_list:
            key = (si.get('sku', ''), si.get('size', ''), si.get('color', ''))
            # Simpan yang punya serial_number (prioritas), kalau tidak ada simpan apa adanya
            if key not in si_by_sku_size_color or (si.get('serial_number') and not si_by_sku_size_color[key].get('serial_number')):
                si_by_sku_size_color[key] = si
        for it in items:
            if it.get('serial_number'):
                continue  # sudah ada, skip
            matched_si = None
            sid = it.get('shipment_item_id')
            if sid and sid in si_by_id:
                matched_si = si_by_id[sid]
            else:
                key = (it.get('sku', ''), it.get('size', ''), it.get('color', ''))
                matched_si = si_by_sku_size_color.get(key)
            if matched_si:
                if not it.get('serial_number'):
                    it['serial_number'] = matched_si.get('serial_number', '')
                if not it.get('po_item_id'):
                    it['po_item_id'] = matched_si.get('po_item_id', '')
                if not it.get('shipment_item_id'):
                    it['shipment_item_id'] = matched_si.get('id', '')
    # Use vendor notes as reason (adopt notes from form)
    reason = body.get('reason', '') or body.get('notes', '') or body.get('vendor_notes', '')
    # Phase 16: support resubmit from a rejected request
    previous_request_id = body.get('previous_request_id', '')
    previous_request_number = ''
    if previous_request_id:
        prev = await db.material_requests.find_one({'id': previous_request_id}, {'_id': 0})
        if prev:
            previous_request_number = prev.get('request_number', '')
    req_doc = {
        'id': new_id(), 'request_number': req_number, 'request_type': body['request_type'],
        'vendor_id': vendor_id, 'vendor_name': orig.get('vendor_name', ''),
        'original_shipment_id': body['original_shipment_id'],
        'original_shipment_number': orig.get('shipment_number', ''),
        'po_id': po_id, 'po_number': po_number,
        'items': items,
        'total_requested_qty': sum(int(i.get('requested_qty', 0) or 0) for i in items),
        'reason': reason, 'vendor_notes': body.get('notes', ''), 'status': 'Pending',
        'inspection_id': body.get('inspection_id', ''),
        'defect_report_id': body.get('defect_report_id', ''),
        'previous_request_id': previous_request_id,
        'previous_request_number': previous_request_number,
        'business_type': orig.get('business_type', 'internal'),
        'created_by': user['name'], 'created_at': now(), 'updated_at': now(),
        **ov_stamp(_ov),
    }
    await db.material_requests.insert_one(req_doc)
    # Mark previous request as resubmitted (defensive: avoid endless resubmit chain spamming)
    if previous_request_id:
        await db.material_requests.update_one(
            {'id': previous_request_id},
            {'$set': {'resubmitted_as_id': req_doc['id'], 'resubmitted_as_number': req_number, 'updated_at': now()}}
        )
    return JSONResponse(serialize_doc(req_doc), status_code=201)

@router.put("/material-requests/{req_id}")
async def update_material_request(req_id: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    assert_prod_admin(user)
    db = get_db()
    body = await request.json()
    # 2026-11-06 (pola P9): permintaan DIKUNCI selama diputuskan. Dulu Setuju ganda membuat DUA kiriman
    # pengganti (shipment anak + baris aksesoris) untuk satu permintaan.
    from core import doc_lock
    token = await doc_lock.claim(db, 'material_requests', req_id, field='decide_lock', actor=user,
                                 not_found='Request tidak ditemukan',
                                 busy='Permintaan ini sedang diputuskan pengguna lain — muat ulang.')
    try:
        return await _update_material_request_locked(db, req_id, body, user)
    finally:
        await doc_lock.release(db, 'material_requests', req_id, token, field='decide_lock')


async def _update_material_request_locked(db, req_id: str, body: dict, user: dict):
    req = await db.material_requests.find_one({'id': req_id})
    if not req: raise HTTPException(404, 'Request tidak ditemukan')
    new_status = body.get('status')
    if new_status is not None and new_status != req.get('status'):
        if new_status not in ('Approved', 'Rejected'):
            raise HTTPException(400, "Status permintaan hanya 'Approved' atau 'Rejected'")
        if req.get('status') != 'Pending':
            raise HTTPException(400,
                f"Permintaan sudah '{req.get('status')}' — keputusan hanya bisa diambil saat 'Pending'")
    if new_status == 'Approved' and req.get('status') == 'Pending':
        # Tahap 9 (7 Nov 2026, keputusan 12): persetujuan = KIRIMAN TAMBAHAN/PENGGANTI yang MENGURANGI STOK lewat
        # hitungan yang sama dengan kiriman biasa (`core.kirim_cmt`). Dulu surat jalan anak dibuat tanpa memotong
        # stok (contoh SHP-202609-0002-A1, 16 pcs). Gagal (potongan kurang, BOM warna tidak ada) → tidak ada yang dibuat.
        from core import kirim_permintaan
        return await kirim_permintaan.approve_material_request(db, req, body, user)
    elif new_status == 'Rejected':
        # Phase 16: admin_notes WAJIB diisi saat reject (agar vendor tahu alasan penolakan)
        admin_notes = (body.get('admin_notes', '') or '').strip()
        if not admin_notes:
            raise HTTPException(400, 'Catatan admin wajib diisi saat menolak permintaan.')
        await db.material_requests.update_one({'id': req_id}, {'$set': {
            'status': 'Rejected', 'admin_notes': admin_notes,
            'rejected_by': user['name'], 'rejected_at': now(),
            'updated_at': now()
        }})
        return serialize_doc(await db.material_requests.find_one({'id': req_id}, {'_id': 0}))
    body.pop('_id', None); body.pop('id', None); body.pop('status', None)
    await db.material_requests.update_one({'id': req_id}, {'$set': {**body, 'updated_at': now()}})
    return serialize_doc(await db.material_requests.find_one({'id': req_id}, {'_id': 0}))

# ─── MATERIAL DEFECT REPORTS ─────────────────────────────────────────────────
@router.get("/material-defect-reports")
async def get_defect_reports(request: Request):
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    sp = request.query_params
    query = {}
    await apply_scope(request, user, db, query, param_vendor_id=sp.get('vendor_id'))
    if sp.get('status'): query['status'] = sp['status']
    if sp.get('defect_type'): query['defect_type'] = sp['defect_type']
    # Pagination (Phase 10A)
    page, per_page, skip, wants = _paginate_params(sp)
    sort = _sort_params(sp, 'created_at', 'desc',
                        allowed={'created_at', 'report_date', 'status', 'defect_type'})
    total = await db.material_defect_reports.count_documents(query) if wants else None
    limit = per_page if wants else LEGACY_DEFAULT_CAP
    docs = await db.material_defect_reports.find(query, {'_id': 0}).sort(sort).skip(skip if wants else 0).limit(limit).to_list(limit)
    if wants:
        return _paginated_envelope(serialize_doc(docs), total, page, per_page)
    return serialize_doc(docs)

@router.post("/material-defect-reports")
async def create_defect_report(request: Request):
    # ─── K5 (Phase C) DEPRECATION ─────────────────────────────────────────
    # material_defect_reports is no longer a production gate. FG defects are now
    # captured at DA CMT-receipt inspection (Phase B: qty_actual + reject_qty in
    # the "Terima FG dari CMT" module). Writing new defect reports is disabled;
    # GET stays for legacy read-only reporting.
    raise HTTPException(410,
        'Endpoint di-deprekasi per K5 (Phase C). Laporan defect material tidak lagi '
        'menjadi gate produksi — catat reject FG saat DA menerima kiriman CMT '
        '(modul "Terima FG dari CMT").')
    user = await require_auth(request)
    deny_klien(user)
    require_write_actor(user, check_role)
    db = get_db()
    body = await request.json()
    # ─── M-3 FIX: Derive vendor_id from job/job_item when admin calls without it ───
    # Vendor role: always uses user.vendor_id.
    # Admin role: accepts explicit vendor_id in body, OR derives from referenced job/job_item.
    vendor_id = vendor_identity(user) if is_vendor(user) else body.get('vendor_id')
    job_item = None
    if body.get('job_item_id'):
        job_item = await db.production_job_items.find_one({'id': body['job_item_id']})
    job_doc = None
    if body.get('job_id'):
        job_doc = await db.production_jobs.find_one({'id': body['job_id']})
    elif job_item and job_item.get('job_id'):
        job_doc = await db.production_jobs.find_one({'id': job_item['job_id']})
    if not vendor_id and job_doc:
        vendor_id = job_doc.get('vendor_id')
    if not vendor_id:
        raise HTTPException(400, 'vendor_id diperlukan (atau kirim job_id / job_item_id yang valid)')
    defect = {
        'id': new_id(), 'vendor_id': vendor_id,
        'job_id': body.get('job_id') or (job_item or {}).get('job_id'),
        'job_item_id': body.get('job_item_id'),
        'po_id': body.get('po_id'), 'po_item_id': body.get('po_item_id'),
        'sku': body.get('sku', (job_item or {}).get('sku', '')),
        'product_name': body.get('product_name', (job_item or {}).get('product_name', '')),
        'size': body.get('size', (job_item or {}).get('size', '')),
        'color': body.get('color', (job_item or {}).get('color', '')),
        'defect_qty': int(body.get('defect_qty', 0) or 0),
        'defect_type': body.get('defect_type', 'Material Cacat'),
        'description': body.get('description', ''),
        'shipment_id': body.get('shipment_id'),
        'report_date': parse_date(body.get('report_date')) or now(),
        'business_type': (job_doc or {}).get('business_type', 'internal'),
        'status': 'Reported', 'reported_by': user['name'],
        'created_at': now(), 'updated_at': now()
    }
    await db.material_defect_reports.insert_one(defect)
    return JSONResponse(serialize_doc(defect), status_code=201)

# ─── PRODUCTION RETURNS ──────────────────────────────────────────────────────
@router.get("/production-returns")
async def get_returns(request: Request):
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    sp = request.query_params
    query = {}
    if sp.get('status'): query['status'] = sp['status']
    if sp.get('po_id'): query['reference_po_id'] = sp['po_id']
    search = sp.get('search')
    if search:
        query['$or'] = [
            {'return_number': {'$regex': search, '$options': 'i'}},
            {'vendor_name': {'$regex': search, '$options': 'i'}},
        ]
    # Pagination (Phase 10A)
    page, per_page, skip, wants = _paginate_params(sp)
    sort = _sort_params(sp, 'created_at', 'desc',
                        allowed={'created_at', 'return_number', 'status'})
    total = await db.production_returns.count_documents(query) if wants else None
    limit = per_page if wants else LEGACY_DEFAULT_CAP
    returns = await db.production_returns.find(query, {'_id': 0}).sort(sort).skip(skip if wants else 0).limit(limit).to_list(limit)

    # ── Phase 10B: batch-fetch items ──
    ret_ids = [r['id'] for r in returns]
    if ret_ids:
        items_all = await db.production_return_items.find({'return_id': {'$in': ret_ids}}, {'_id': 0}).to_list(None)
    else:
        items_all = []
    items_by_ret = {}
    for it in items_all:
        items_by_ret.setdefault(it['return_id'], []).append(it)

    result = [{**serialize_doc(r), 'items': serialize_doc(items_by_ret.get(r['id'], []))} for r in returns]
    if wants:
        return _paginated_envelope(result, total, page, per_page)
    return result

@router.get("/production-returns/{ret_id}")
async def get_return(ret_id: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    ret = await db.production_returns.find_one({'id': ret_id}, {'_id': 0})
    if not ret: raise HTTPException(404, 'Not found')
    items = await db.production_return_items.find({'return_id': ret_id}, {'_id': 0}).to_list(None)
    result = serialize_doc(ret)
    result['items'] = serialize_doc(items)
    result['allowed_next'] = _return_allowed_next(ret.get('status', 'Repair Needed'))
    return result

@router.post("/production-returns")
async def create_return(request: Request):
    user = await require_auth(request)
    deny_klien(user)
    assert_prod_admin(user)
    db = get_db()
    body = await request.json()
    return_id = new_id()
    # SESI #27 — SATU PINTU kebijakan penomoran (Otomatis/Manual). Retur produksi
    # dari buyer sering disalin dari nomor surat retur pihak buyer, jadi mode MANUAL
    # bukan kemewahan. Sebelum ini jenis dokumen ini bahkan TIDAK ADA di katalog
    # Penomoran Dokumen — owner tak bisa melihat, apalagi mengatur, formatnya.
    from core.doc_number_policy import issue_number
    return_number = await issue_number(
        db, "production_returns.return_number",
        requested=(body.get("return_number") or "").strip())
    ref_po = await db.production_pos.find_one({'id': body.get('reference_po_id')}) if body.get('reference_po_id') else None
    items_data = body.get('items', [])

    # ─── VALIDATION GUARDRAILS (Phase A — C-2 & H-4) ──────────────────────
    # Reject empty/negative returns and returns that exceed max_returnable
    if not items_data:
        raise HTTPException(400, 'Retur harus memiliki minimal 1 item')
    for item in items_data:
        try:
            qty = int(item.get('return_qty', 0) or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, 'return_qty harus bilangan bulat')
        if qty < 1:
            raise HTTPException(400, f'return_qty harus minimal 1 (diterima: {qty})')
        po_item_id = item.get('po_item_id')
        if po_item_id:
            # max_returnable = total_shipped - total_already_returned
            buyer_items = await db.buyer_shipment_items.find({'po_item_id': po_item_id}).to_list(None)
            total_shipped = sum(int(bi.get('qty_shipped', 0) or 0) for bi in buyer_items)
            prev_return_items = await db.production_return_items.find({'po_item_id': po_item_id}).to_list(None)
            total_already_returned = sum(int(ri.get('return_qty', 0) or 0) for ri in prev_return_items)
            max_returnable = max(0, total_shipped - total_already_returned)
            if qty > max_returnable:
                sku = item.get('sku') or (await db.po_items.find_one({'id': po_item_id}) or {}).get('sku', '')
                raise HTTPException(400,
                    f'Retur {sku}: qty {qty} melebihi maks yang bisa diretur ({max_returnable} pcs). '
                    f'Total dikirim ke buyer: {total_shipped}, sudah diretur: {total_already_returned}.')

    total_qty = sum(int(i.get('return_qty', 0) or 0) for i in items_data)
    return_doc = {
        'id': return_id, 'return_number': return_number,
        'reference_po_id': body.get('reference_po_id'),
        'reference_po_number': (ref_po or {}).get('po_number', body.get('reference_po_number', '')),
        'customer_name': body.get('customer_name', (ref_po or {}).get('customer_name', '')),
        'buyer_name': body.get('buyer_name', body.get('customer_name', '')),
        'return_date': parse_date(body.get('return_date')) or now(),
        'return_reason': body.get('return_reason', ''), 'notes': body.get('notes', ''),
        'business_type': (ref_po or {}).get('business_type', 'internal'),
        'status': 'Repair Needed', 'total_return_qty': total_qty,
        'created_by': user['name'], 'created_at': now(), 'updated_at': now()
    }
    await db.production_returns.insert_one(return_doc)
    inserted_items = []
    for item in items_data:
        ri = {
            'id': new_id(), 'return_id': return_id,
            'po_item_id': item.get('po_item_id'),
            'sku': item.get('sku', ''), 'product_name': item.get('product_name', ''),
            'serial_number': item.get('serial_number', ''),
            'size': item.get('size', ''), 'color': item.get('color', ''),
            'return_qty': int(item.get('return_qty', 0) or 0),
            'defect_type': item.get('defect_type', ''),
            'repair_notes': item.get('repair_notes', ''), 'repaired_qty': 0,
            'created_at': now()
        }
        await db.production_return_items.insert_one(ri)
        inserted_items.append(ri)
    result = serialize_doc(return_doc)
    result['items'] = serialize_doc(inserted_items)
    return JSONResponse(result, status_code=201)

@router.put("/production-returns/{ret_id}")
async def update_return(ret_id: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    assert_prod_admin(user)
    db = get_db()
    body = await request.json()
    body.pop('_id', None); body.pop('id', None); body.pop('items', None)
    if body.get('return_date'): body['return_date'] = parse_date(body['return_date'])
    if 'status' in body:
        ret_doc = await db.production_returns.find_one({'id': ret_id})
        if not ret_doc: raise HTTPException(404, 'Return not found')
        new_ret_status = body['status']
        if new_ret_status not in RETURN_STATUS_FLOW:
            raise HTTPException(400, f"Status retur tidak dikenal. Valid: {RETURN_STATUS_FLOW}")
        cur = ret_doc.get('status', 'Repair Needed')
        cur_idx = RETURN_STATUS_FLOW.index(cur) if cur in RETURN_STATUS_FLOW else 0
        if new_ret_status != cur and RETURN_STATUS_FLOW.index(new_ret_status) < cur_idx:
            raise HTTPException(400,
                f"Transisi status retur ilegal: '{cur}' → '{new_ret_status}' (hanya boleh maju: {RETURN_STATUS_FLOW})")
    await db.production_returns.update_one({'id': ret_id}, {'$set': {**body, 'updated_at': now()}})
    return serialize_doc(await db.production_returns.find_one({'id': ret_id}, {'_id': 0}))

@router.delete("/production-returns/{ret_id}")
async def delete_return(ret_id: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    wajib_centang(user, apa='menghapus data ini')   # 14 Nov 2026: centang Hapus modulnya (dulu khusus superadmin)
    db = get_db()
    doc = await db.production_returns.find_one({'id': ret_id})
    if not doc: raise HTTPException(404, 'Not found')
    await db.production_return_items.delete_many({'return_id': ret_id})
    await db.production_returns.delete_one({'id': ret_id})
    return {'success': True}

# ─── PRODUCTION VARIANCES (OVERPRODUCTION/UNDERPRODUCTION) ──────────────────
async def system_variance_items(db, job_id: str, variance_type: str, picked_ids=None) -> list:
    """Baris variance dari BUKU KUANTITAS job (2026-11-06, Tahap 2).

    variance = |diproduksi − dipesan| per baris job, hanya baris yang arahnya sesuai jenis laporan
    (lebih untuk OVERPRODUCTION, kurang untuk UNDERPRODUCTION). `picked_ids` kosong = semua baris."""
    job_items = await db.production_job_items.find({'job_id': job_id}, {'_id': 0}).to_list(500)
    by_id = {ji.get('id'): ji for ji in job_items}
    picked = [str(x) for x in (picked_ids or []) if x] or list(by_id)
    unknown = [x for x in picked if x not in by_id]
    if unknown:
        raise HTTPException(400, 'Baris job yang dipilih tidak ditemukan di job ini.')
    out = []
    for jid in picked:
        ji = by_id[jid]
        ordered = int(ji.get('ordered_qty') or 0)
        produced = int(ji.get('produced_qty') or 0)
        diff = produced - ordered
        if (variance_type == 'OVERPRODUCTION' and diff <= 0) or (variance_type == 'UNDERPRODUCTION' and diff >= 0):
            continue
        out.append({'job_item_id': jid, 'product_name': ji.get('product_name', ''), 'sku': ji.get('sku', ''),
                    'size': ji.get('size', ''), 'color': ji.get('color', ''), 'ordered_qty': ordered,
                    'produced_qty': produced, 'variance_qty': abs(diff)})
    if not out:
        arah = 'lebih' if variance_type == 'OVERPRODUCTION' else 'kurang'
        raise HTTPException(400, f'Menurut catatan produksi job ini tidak ada baris yang produksinya {arah} '
                                 'dari pesanan — laporan variance tidak dibuat.')
    return out


async def variance_gl_value(db, variance: dict) -> dict:
    """Nilai GL variance = qty variance SISTEM × HPP rata-rata (WAC) barang jadi SKU itu.

    2026-11-06 (Tahap 2): dulu harga dibaca dari `rahaza_models.cost_per_unit` (tidak pernah diisi
    → nilai selalu 0) atau diketik di badan permintaan. WAC = nilai yang dipakai persediaan FG di
    buku besar, jadi jurnalnya konsisten dengan stok. Return {value, items, missing}."""
    from core import fg_cost_layers as fcl
    total, rows, missing = 0.0, [], []
    for it in variance.get('items') or []:
        qty = abs(int(it.get('variance_qty', 0) or 0))
        sku = (it.get('sku') or '').strip()
        mat = await db.rahaza_materials.find_one({'type': 'fg', 'code': sku}, {'_id': 0, 'id': 1}) if sku else None
        uc = float((await fcl.wac_state(db, mat['id']))['unit_cost']) if mat else 0.0
        if qty and uc <= 0:
            missing.append(sku or it.get('product_name') or '-')
        rows.append({**it, 'unit_cost': round(uc, 4), 'value': round(qty * uc, 2)})
        total += qty * uc
    return {'value': round(total, 2), 'items': rows, 'missing': missing}


@router.post("/production-variances")
async def create_variance(request: Request):
    """Vendor reports overproduction or underproduction for a job/item"""
    user = await require_auth(request)
    deny_klien(user)
    require_write_actor(user, check_role)
    db = get_db()
    body = await request.json()
    
    # Get vendor_id from user context if vendor role
    _ov = await resolve_override(request, user, db)
    vendor_id = await effective_vendor_id(request, user, db, body.get('vendor_id'))
    if not vendor_id: raise HTTPException(400, 'vendor_id required')
    
    # Validate job exists
    job_id = body.get('job_id')
    if not job_id: raise HTTPException(400, 'job_id required')
    job = await db.production_jobs.find_one({'id': job_id})
    if not job: raise HTTPException(404, 'Job not found')
    if job.get('vendor_id') != vendor_id: raise HTTPException(403, 'Job does not belong to this vendor')
    
    # Get PO info
    po_id = job.get('po_id') or body.get('po_id')
    po = await db.production_pos.find_one({'id': po_id}) if po_id else None
    po_number = po.get('po_number', '') if po else ''
    
    variance_type = body.get('variance_type')  # 'OVERPRODUCTION' or 'UNDERPRODUCTION'
    if variance_type not in ['OVERPRODUCTION', 'UNDERPRODUCTION']:
        raise HTTPException(400, 'variance_type must be OVERPRODUCTION or UNDERPRODUCTION')
    # 2026-11-06 (Tahap 2): qty variance dari SISTEM (dipesan vs diproduksi di buku kuantitas job),
    # bukan angka ketikan. Pelapor hanya memilih baris job; angka yang diketik diabaikan.
    items = await system_variance_items(db, job_id, variance_type,
                                        [i.get('job_item_id') for i in (body.get('items') or [])])

    # Create variance record
    variance = {
        'id': new_id(),
        'vendor_id': vendor_id,
        'vendor_name': job.get('vendor_name', ''),
        'job_id': job_id,
        'job_number': job.get('job_number', ''),
        'po_id': po_id,
        'po_number': po_number,
        'variance_type': variance_type,
        'business_type': job.get('business_type', 'internal'),
        'reason': body.get('reason', ''),
        'notes': body.get('notes', ''),
        'items': items,  # {job_item_id, product_name, sku, size, color, ordered_qty, produced_qty, variance_qty}
        'total_variance_qty': sum(int(item.get('variance_qty', 0) or 0) for item in items),
        'qty_source': 'system',
        'reported_by': user['name'],
        'status': 'Reported',  # Reported, Acknowledged, Resolved
        'created_at': now(),
        'updated_at': now(),
        **ov_stamp(_ov),
    }
    
    await db.production_variances.insert_one(variance)
    await log_activity(user['id'], user['name'], 'Create', 'Production Variance',
                      f"Reported {variance_type} for job {job.get('job_number')}: {variance['total_variance_qty']} pcs")
    
    return JSONResponse(serialize_doc(variance), status_code=201)

@router.get("/production-variances")
async def get_variances(request: Request):
    """List production variances with filters"""
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    sp = request.query_params
    
    query = {}
    
    # Vendor filter (auto for vendor role, override untuk staf DA, opsional utk admin)
    await apply_scope(request, user, db, query, param_vendor_id=sp.get('vendor_id'))
    
    # Type filter
    if sp.get('variance_type'):
        query['variance_type'] = sp['variance_type']
    
    # Status filter
    if sp.get('status'):
        query['status'] = sp['status']

    # FASE IA-1 (2026-07-26) — pemisahan data per domain (Portal Produksi = internal,
    # Portal Maklon = maklon). Field `business_type` SUDAH ditulis saat create
    # (lihat create_variance), jadi ini murni filter baca.
    bt = sp.get('business_type')
    if bt == 'internal':
        query['business_type'] = 'internal'
    elif bt == 'maklon':
        query['business_type'] = {'$ne': 'internal'}
    
    # Date range filter
    date_from = parse_date(sp.get('from'))
    date_to = to_end_of_day(sp.get('to'))
    if date_from or date_to:
        date_filter = {}
        if date_from: date_filter['$gte'] = date_from
        if date_to: date_filter['$lte'] = date_to
        if date_filter: query['created_at'] = date_filter
    
    # Search
    search = sp.get('search')
    if search:
        query['$or'] = [
            {'job_number': {'$regex': search, '$options': 'i'}},
            {'po_number': {'$regex': search, '$options': 'i'}},
            {'vendor_name': {'$regex': search, '$options': 'i'}},
            {'reason': {'$regex': search, '$options': 'i'}}
        ]
    
    # FASE 4 (T-21): daftar dibatasi (`?limit=`, bawaan 2000 terbaru)
    _limit = min(int(sp.get('limit') or 2000), 10000)
    variances = await db.production_variances.find(query, {'_id': 0}).sort('created_at', -1).to_list(_limit)
    for v in variances:
        v['allowed_next'] = VARIANCE_STATUS_TRANSITIONS.get(v.get('status', 'Reported'), [])
    return serialize_doc(variances)

@router.get("/production-variances/stats")
async def get_variance_stats(request: Request):
    """Get summary statistics for production variances"""
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    sp = request.query_params
    
    query = {}
    
    # Vendor filter
    await apply_scope(request, user, db, query, param_vendor_id=sp.get('vendor_id'))
    
    # Date range filter
    date_from = parse_date(sp.get('from'))
    date_to = to_end_of_day(sp.get('to'))
    if date_from or date_to:
        date_filter = {}
        if date_from: date_filter['$gte'] = date_from
        if date_to: date_filter['$lte'] = date_to
        if date_filter: query['created_at'] = date_filter
    
    # FASE IA-1 — pemisahan data per domain (samakan dgn list endpoint di atas)
    bt = sp.get('business_type')
    if bt == 'internal':
        query['business_type'] = 'internal'
    elif bt == 'maklon':
        query['business_type'] = {'$ne': 'internal'}

    # Aggregate stats — FASE 4 (T-21): agregasi di DB, bukan memuat semua dokumen ke memori
    _proj = {'_id': 0, 'variance_type': 1, 'status': 1, 'vendor_name': 1, 'total_variance_qty': 1}
    all_variances = await db.production_variances.find(query, _proj).to_list(50000)
    
    overproduction = [v for v in all_variances if v.get('variance_type') == 'OVERPRODUCTION']
    underproduction = [v for v in all_variances if v.get('variance_type') == 'UNDERPRODUCTION']
    
    stats = {
        'total_records': len(all_variances),
        'overproduction': {
            'count': len(overproduction),
            'total_qty': sum(v.get('total_variance_qty', 0) for v in overproduction)
        },
        'underproduction': {
            'count': len(underproduction),
            'total_qty': sum(v.get('total_variance_qty', 0) for v in underproduction)
        },
        'by_status': {},
        'by_vendor': {}
    }
    
    # Group by status
    for v in all_variances:
        status = v.get('status', 'Unknown')
        if status not in stats['by_status']:
            stats['by_status'][status] = 0
        stats['by_status'][status] += 1
    
    # Group by vendor
    for v in all_variances:
        vname = v.get('vendor_name', 'Unknown')
        if vname not in stats['by_vendor']:
            stats['by_vendor'][vname] = {'overproduction': 0, 'underproduction': 0, 'total_qty': 0}
        stats['by_vendor'][vname][v.get('variance_type', '').lower()] += 1
        stats['by_vendor'][vname]['total_qty'] += v.get('total_variance_qty', 0)
    
    return stats

@router.put("/production-variances/{vid}")
async def update_variance_status(vid: str, request: Request):
    """Admin updates variance status (Acknowledged/Resolved)"""
    user = await require_auth(request)
    deny_klien(user)
    assert_prod_admin(user)
    db = get_db()
    body = await request.json()
    
    variance = await db.production_variances.find_one({'id': vid})
    if not variance: raise HTTPException(404, 'Variance not found')
    new_var_status = body.get('status')
    if new_var_status is not None and new_var_status != variance.get('status'):
        allowed = VARIANCE_STATUS_TRANSITIONS.get(variance.get('status', 'Reported'), [])
        if new_var_status not in allowed:
            raise HTTPException(400,
                f"Transisi status variance ilegal: '{variance.get('status')}' → '{new_var_status}'. "
                f"Valid: {allowed if allowed else 'tidak ada (status final)'}")
    await db.production_variances.update_one({'id': vid}, {'$set': {
        'status': body.get('status', variance.get('status')),
        'admin_notes': body.get('admin_notes', ''),
        'updated_by': user['name'],
        'updated_at': now()
    }})
    
    await log_activity(user['id'], user['name'], 'Update', 'Production Variance',
                      f"Updated variance status to {body.get('status')} for {variance.get('job_number')}")
    
    return {'success': True}

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 7C (DA): PRODUCTION VARIANCE → GL AUTO-POSTING — DIPENSIUNKAN Tahap 9 (7 Nov 2026)
# ══════════════════════════════════════════════════════════════════════════════
# Dulu: OVERPRODUCTION = Dr Persediaan FG (1-1404) / Cr Pendapatan selisih; UNDERPRODUCTION = Dr Rugi selisih /
# Cr WIP (1-1403), bernilai qty × HPP rata-rata FG. Keduanya membuat NILAI BUKU BERBEDA DARI STOK:
#   · OVER mendebit persediaan TANPA gerakan stok — barang lebihnya sendiri sudah masuk stok DAN buku lewat
#     Terima & QC (lapisan biaya FG), jadi jurnal ini menghitungnya dua kali.
#   · UNDER mengkredit WIP sebesar biaya FG (sudah termasuk upah jahit yang tidak pernah terjadi), dan sisa
#     WIP PO yang sama DITUTUP LAGI otomatis saat Tutup PO (`core.po_wip` → Selisih produksi 5-1960).
# Sekarang selisih jumlah hanya DILAPORKAN (Laporan Selisih otomatis per baris PO); satu-satunya jurnal selisih
# produksi adalah penutupan sisa WIP saat Tutup PO. Endpoint tetap ada (tautan lama) dan menjawab 410.
# Jurnal lama yang terlanjur diposting dibalik oleh migrasi `2026_11_07_jurnal_selisih_produksi.py`.
VARIANCE_GL_RETIRED = (
    "Laporan selisih tidak lagi dijurnal (Tahap 9). Kelebihan barang sudah masuk stok dan buku lewat Terima & QC "
    "dengan nilainya sendiri, dan sisa barang dalam proses PO ditutup otomatis ke Selisih produksi saat Tutup PO. "
    "Jurnal dari laporan ini membuat nilai buku berbeda dari stok.")


@router.post("/production-variances/{vid}/post-gl")
async def post_variance_to_gl(vid: str, request: Request):
    """DIPENSIUNKAN (Tahap 9) — selalu HTTP 410 dengan penjelasan; tidak ada jurnal yang dibuat."""
    user = await require_auth(request)
    deny_klien(user)
    assert_prod_admin(user)
    db = get_db()
    if not await db.production_variances.find_one({'id': vid}, {'_id': 0, 'id': 1}):
        raise HTTPException(404, 'Variance not found')
    raise HTTPException(410, VARIANCE_GL_RETIRED)


@router.post("/production-variances/{vid}/retry-posting")
async def retry_variance_posting(vid: str, request: Request):
    """DIPENSIUNKAN (Tahap 9) — sama dengan post-gl: HTTP 410, tidak ada jurnal yang dibuat."""
    user = await require_auth(request)
    deny_klien(user)
    assert_prod_admin(user)
    db = get_db()
    if not await db.production_variances.find_one({'id': vid}, {'_id': 0, 'id': 1}):
        raise HTTPException(404, 'Variance not found')
    raise HTTPException(410, VARIANCE_GL_RETIRED)
