"""dewi_rnd — Sample Requests + Revisions.

14 Nov 2026 (keputusan owner): sample R&D = style baru. Bila style sudah dijadikan model (`promoted_to_model_id`),
request boleh memilih varian/ukuran (`rahaza_variant_id`). Saat DISETUJUI dan variannya diketahui ⇒ draf PO
produksi "Sampel R&D" dibuat otomatis (qty = jumlah request, `core.po_sampel`) supaya kain & aksesorisnya keluar
lewat alur produksi biasa. Style belum ber-model ⇒ tidak ada PO; request menampilkan catatan dan aksi
"Buat draf PO sampel" (POST /sample-requests/{id}/po-sampel, aman diulang).
"""
from fastapi import Depends, HTTPException, Query
from database import get_db
from auth import require_auth
from routes.dewi_rnd_shared import router, now_utc, sid, serialize
from routes.shared import assert_can_act
from utils.waktu import fmt_wib

# Yang boleh memutus dokumen RnD (di luar admin/owner yang selalu boleh).
RND_APPROVER_ROLES = ('rnd_staff', 'manager_produksi', 'supervisor_produksi',
                      'manager', 'owner', 'admin', 'superadmin')

# ──────────────────────────────────────────────────────────────────────────────
# 2026-11-07 (Tahap 6, keputusan owner HR4): PIC / pembuat sample
# ──────────────────────────────────────────────────────────────────────────────
# Dulu teks bebas. Sekarang DIPILIH dari karyawan (`rahaza_employees`, karyawan bagian sample ditawarkan
# paling atas di layar) → `sample_pic_employee_id` + `sample_pic` (nama dari master). Penjahit LUAR tetap
# bisa diketik lewat pilihan eksplisit "Penjahit luar" → `sample_pic` + `sample_pic_external: true`.
# Ketikan tanpa penanda ditolak; nilai lama yang tidak diubah tetap boleh.
PIC_KEYS = ('sample_pic', 'sample_pic_employee_id', 'sample_pic_external')


async def resolve_sample_pic(db, body: dict, before: dict = None) -> dict:
    """PIC sample dari body → field tersimpan. {} bila body tidak menyentuh PIC. 400 bila tidak sah."""
    if not any(k in body for k in PIC_KEYS):
        return {}
    before = before or {}
    eid = str(body.get('sample_pic_employee_id') or '').strip()
    name = str(body.get('sample_pic') or '').strip()
    if eid:
        emp = await db.rahaza_employees.find_one({'id': eid}, {'_id': 0, 'id': 1, 'name': 1, 'active': 1})
        if not emp:
            raise HTTPException(400, 'Karyawan PIC sample tidak ada di data karyawan — pilih dari daftar.')
        if emp.get('active') is False and before.get('sample_pic_employee_id') != eid:
            raise HTTPException(400, f"Karyawan {emp.get('name')} sudah nonaktif — pilih karyawan lain.")
        return {'sample_pic_employee_id': eid, 'sample_pic': emp.get('name') or '', 'sample_pic_external': False}
    if not name:
        return {'sample_pic_employee_id': '', 'sample_pic': '', 'sample_pic_external': False}
    if body.get('sample_pic_external'):
        return {'sample_pic_employee_id': '', 'sample_pic': name, 'sample_pic_external': True}
    if name == str(before.get('sample_pic') or '').strip() and not before.get('sample_pic_employee_id'):
        return {'sample_pic_employee_id': '', 'sample_pic': name,
                'sample_pic_external': bool(before.get('sample_pic_external'))}   # nilai lama
    raise HTTPException(400, "Pilih karyawan sebagai PIC sample, atau pilih 'Penjahit luar' lalu ketik namanya.")


# ──────────────────────────────────────────────────────────────────────────────
# 14 Nov 2026 — varian sample & draf PO "Sampel R&D"
# ──────────────────────────────────────────────────────────────────────────────
CATATAN_TANPA_MODEL = 'Style belum dijadikan model — PO sampel dibuat setelah model ada'
CATATAN_TANPA_VARIAN = 'Pilih varian/ukuran lalu buat draf PO sampel'
JENIS_PO = 'sample_request'


async def model_style(db, style_id: str):
    """Model Master Produk milik style ini (tautan `promoted_to_model_id`, cadangan `model.rnd_style_id`)."""
    style = await db.dewi_rnd_styles.find_one({'id': style_id}, {'_id': 0, 'id': 1, 'promoted_to_model_id': 1}) or {}
    mid = style.get('promoted_to_model_id')
    model = await db.rahaza_models.find_one({'id': mid, 'active': {'$ne': False}}, {'_id': 0}) if mid else None
    if not model and style_id:
        model = await db.rahaza_models.find_one({'rnd_style_id': style_id, 'active': {'$ne': False}}, {'_id': 0})
    return model


async def varian_style(db, style_id: str, variant_id: str) -> dict:
    """Varian yang dipilih HARUS varian aktif model style itu. → field tersimpan (kosong bila tidak dipilih)."""
    if not variant_id:
        return {'rahaza_variant_id': '', 'variant_sku': '', 'variant_label': ''}
    model = await model_style(db, style_id)
    if not model:
        raise HTTPException(400, CATATAN_TANPA_MODEL + '.')
    v = await db.rahaza_model_variants.find_one(
        {'id': variant_id, 'model_id': model['id'], 'active': {'$ne': False}}, {'_id': 0})
    if not v:
        raise HTTPException(400, 'Varian ini bukan varian aktif model style tersebut — pilih dari daftar.')
    label = ' · '.join(str(x) for x in (v.get('color_name'), v.get('size_code')) if x)
    return {'rahaza_variant_id': v['id'], 'variant_sku': v.get('sku') or '', 'variant_label': label}


async def buat_po_sampel(db, req: dict, user: dict, variant_id: str = '') -> dict:
    """Draf PO "Sampel R&D" untuk satu request (sekali saja). → {po_id, po_number, …} atau {po_catatan}."""
    from core import po_sampel
    if req.get('po_id') and await db.production_pos.find_one({'id': req['po_id']}, {'_id': 0, 'id': 1}):
        return {'po_id': req['po_id'], 'po_number': req.get('po_number')}
    vid = variant_id or req.get('rahaza_variant_id') or ''
    model = await model_style(db, req.get('style_id'))
    if not model:
        return {'po_catatan': CATATAN_TANPA_MODEL}
    if not vid:
        return {'po_catatan': CATATAN_TANPA_VARIAN}
    try:
        v = await varian_style(db, req.get('style_id'), vid)
    except HTTPException as e:   # varian lama sudah dinonaktifkan / pindah model: catatan, bukan galat persetujuan
        return {'po_catatan': e.detail}
    hasil = await po_sampel.buat_draf(
        db, jenis=JENIS_PO, sumber_id=req['id'], nomor=req.get('sample_code') or req['id'],
        qty=int(float(req.get('quantity') or 0)), user=user, variant_id=v['rahaza_variant_id'],
        catatan=f"Sample request {req.get('style_code') or ''} {req.get('style_name') or ''}".strip() + '.')
    return {**v, **{k: hv for k, hv in hasil.items() if k in ('po_id', 'po_number', 'po_catatan')}}


async def _with_po_info(db, rows: list) -> list:
    """Request disetujui tanpa PO sampel → catatan TERKINI (style bisa saja dijadikan model sesudahnya)."""
    for r in rows:
        if r.get('status') != 'approved' or r.get('po_id'):
            continue
        if not await model_style(db, r.get('style_id')):
            r['po_sampel_catatan'], r['po_sampel_bisa_buat'] = CATATAN_TANPA_MODEL, False
        else:
            catatan = r.get('po_catatan')
            r['po_sampel_catatan'] = catatan if catatan and catatan != CATATAN_TANPA_MODEL else CATATAN_TANPA_VARIAN
            r['po_sampel_bisa_buat'] = True
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# SAMPLE REQUESTS
# ──────────────────────────────────────────────────────────────────────────────

@router.get('/sample-requests')
async def list_sample_requests(
    style_id: str = None,
    status: str = None,
    limit: int = Query(200, ge=1, le=1000),
    user: dict = Depends(require_auth),
):
    """List sample requests"""
    db = get_db()
    q = {}
    if style_id:
        q['style_id'] = style_id
    if status:
        q['status'] = status

    items = await db.dewi_rnd_sample_requests.find(q).sort('created_at', -1).limit(limit).to_list(length=limit)
    return await _with_po_info(db, await _with_accessory_status(db, [serialize(it) for it in items]))


@router.get('/sample-requests/pilihan-varian')
async def sample_variant_options(style_id: str = Query(...), user: dict = Depends(require_auth)):
    """Varian/ukuran yang bisa dipilih untuk sample style ini (kosong + catatan bila style belum ber-model).
    Didaftarkan SEBELUM `/sample-requests/{request_id}` supaya 'pilihan-varian' tidak terbaca sebagai id."""
    db = get_db()
    model = await model_style(db, style_id)
    if not model:
        return {'style_id': style_id, 'model_id': None, 'variants': [], 'catatan': CATATAN_TANPA_MODEL}
    vs = await db.rahaza_model_variants.find(
        {'model_id': model['id'], 'active': {'$ne': False}}, {'_id': 0}).sort('sku', 1).to_list(500)
    return {'style_id': style_id, 'model_id': model['id'], 'model_code': model.get('code') or '',
            'model_name': model.get('name') or '', 'catatan': '' if vs else 'Model ini belum punya varian aktif.',
            'variants': [{'id': v.get('id'), 'sku': v.get('sku') or '', 'color_name': v.get('color_name') or '',
                          'size_code': v.get('size_code') or ''} for v in vs]}


async def _with_accessory_status(db, rows: list) -> list:
    """2026-11-10 (keputusan owner): status sample tidak berubah karena aksesoris; daftar sample
    diberi `accessory_status` (menunggu / disiapkan / terkirim / ditolak) dari permintaan aksesorisnya."""
    from routes.dewi_accessory_requests import accessory_status_by_sample
    st = await accessory_status_by_sample(db, [r.get('id') for r in rows])
    for r in rows:
        r['accessory_status'] = st.get(r.get('id'))
    return rows


@router.post('/sample-requests')
async def create_sample_request(body: dict, user: dict = Depends(require_auth)):
    """Create new sample request"""
    db = get_db()
    style_id = body.get('style_id')
    if not style_id:
        raise HTTPException(400, 'style_id wajib diisi')

    style = await db.dewi_rnd_styles.find_one({'id': style_id})
    if not style:
        raise HTTPException(404, 'Style tidak ditemukan')
    pic = await resolve_sample_pic(db, {k: body.get(k) for k in PIC_KEYS})
    varian = await varian_style(db, style_id, str(body.get('rahaza_variant_id') or '').strip())

    doc = {
        'id': sid(),
        'sample_code': f"SR-{fmt_wib('%Y%m%d')}-{sid()[:6].upper()}",
        'style_id': style_id,
        'style_code': style.get('style_code', ''),
        'style_name': style.get('style_name', ''),
        'quantity': body.get('quantity', 1),
        'priority': body.get('priority', 'normal'),
        # PIC / pembuat sample (2026-08-07) — Tahap 6 (HR4): karyawan (id + nama) atau penjahit luar (nama + penanda)
        **pic,
        **varian,      # 14 Nov 2026: varian/ukuran (opsional; hanya bila style sudah dijadikan model)
        'due_date': body.get('due_date'),
        'notes': body.get('notes', ''),
        'status': 'draft',
        'approval_status': None,
        'approved_by': None,
        'approved_by_name': None,
        'approved_at': None,
        'approval_notes': None,
        'created_by': user['id'],
        'created_by_name': user.get('name', ''),
        'created_at': now_utc(),
        'updated_at': now_utc(),
    }
    await db.dewi_rnd_sample_requests.insert_one(doc)
    return serialize(doc)


@router.get('/sample-requests/{request_id}')
async def get_sample_request(request_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    req = await db.dewi_rnd_sample_requests.find_one({'id': request_id})
    if not req:
        raise HTTPException(404, 'Sample request tidak ditemukan')
    return (await _with_po_info(db, await _with_accessory_status(db, [serialize(req)])))[0]


# 2026-11-10 (keputusan owner "tutup penuh"): status & data persetujuan hanya berubah lewat
# /submit, /approve, /reject (gerbang izin `rnd.approve`). Dulu PUT menerima `status: approved`
# dari siapa pun yang boleh mengubah data R&D — persetujuan bisa dilewati.
SAMPLE_WORKFLOW_FIELDS = ('status', 'approval_status', 'approved_by', 'approved_by_name', 'approved_at',
                          'approval_notes', 'created_by', 'created_by_name',
                          # 14 Nov 2026: PO sampel hanya lewat persetujuan / tombol "Buat draf PO sampel"
                          'po_id', 'po_number', 'po_catatan', 'variant_sku', 'variant_label')
# Sample yang sudah diputuskan tidak bisa diubah isinya lagi.
SAMPLE_LOCKED_STATUSES = ('approved', 'rejected')


@router.put('/sample-requests/{request_id}')
async def update_sample_request(request_id: str, body: dict, user: dict = Depends(require_auth)):
    db = get_db()
    body.pop('_id', None)
    body.pop('id', None)
    body.pop('created_at', None)
    before = await db.dewi_rnd_sample_requests.find_one({'id': request_id}, {'_id': 0})
    if not before:
        raise HTTPException(404, 'Sample request tidak ditemukan')
    if before.get('status') in SAMPLE_LOCKED_STATUSES:
        raise HTTPException(400, 'Sample yang sudah disetujui atau ditolak tidak bisa diubah lagi. '
                                 'Buat request sample baru bila perlu perubahan.')
    if 'status' in body and body.get('status') != before.get('status'):
        raise HTTPException(400, 'Status sample hanya berubah lewat tombol Ajukan, Setujui, atau Tolak.')
    for k in SAMPLE_WORKFLOW_FIELDS:
        body.pop(k, None)
    # Tahap 6 (HR4): PIC sample hanya karyawan dari master atau penjahit luar bertanda
    if any(k in body for k in PIC_KEYS):
        body.update(await resolve_sample_pic(db, body, before))
    if 'rahaza_variant_id' in body or ('style_id' in body and body.get('style_id') != before.get('style_id')):
        vid = body.get('rahaza_variant_id', before.get('rahaza_variant_id'))
        body.update(await varian_style(db, body.get('style_id') or before.get('style_id'), str(vid or '').strip()))
    body['updated_at'] = now_utc()

    res = await db.dewi_rnd_sample_requests.update_one({'id': request_id}, {'$set': body})
    if res.matched_count == 0:
        raise HTTPException(404, 'Sample request tidak ditemukan')

    updated = await db.dewi_rnd_sample_requests.find_one({'id': request_id})
    return serialize(updated)


@router.post('/sample-requests/{request_id}/submit')
async def submit_sample_request(request_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    req = await db.dewi_rnd_sample_requests.find_one({'id': request_id})
    if not req:
        raise HTTPException(404, 'Sample request tidak ditemukan')
    if req.get('status') != 'draft':
        raise HTTPException(400, 'Hanya draft yang bisa di-submit')

    await db.dewi_rnd_sample_requests.update_one(
        {'id': request_id},
        {'$set': {'status': 'submitted', 'updated_at': now_utc()}},
    )
    updated = await db.dewi_rnd_sample_requests.find_one({'id': request_id})
    return serialize(updated)


@router.post('/sample-requests/{request_id}/approve')
async def approve_sample_request(request_id: str, body: dict, user: dict = Depends(require_auth)):
    assert_can_act(user, 'rnd.approve', portal='rnd', legacy_roles=RND_APPROVER_ROLES,
                   what='menyetujui permintaan sample RnD')
    db = get_db()
    req = await db.dewi_rnd_sample_requests.find_one({'id': request_id})
    if not req:
        raise HTTPException(404, 'Sample request tidak ditemukan')
    if req.get('status') != 'submitted':
        raise HTTPException(400, 'Hanya submitted yang bisa di-approve')

    await db.dewi_rnd_sample_requests.update_one(
        {'id': request_id},
        {'$set': {
            'status': 'approved',
            'approval_status': 'approved',
            'approved_by': user['id'],
            'approved_by_name': user.get('name', ''),
            'approved_at': now_utc(),
            'approval_notes': body.get('notes', ''),
            'updated_at': now_utc(),
        }},
    )
    # 14 Nov 2026: varian diketahui ⇒ draf PO "Sampel R&D" otomatis. Gagal apa pun tidak membatalkan persetujuan.
    hasil = await buat_po_sampel(db, {**req, 'status': 'approved'}, user)
    await db.dewi_rnd_sample_requests.update_one(
        {'id': request_id}, {'$set': {k: hasil.get(k) for k in ('po_id', 'po_number', 'po_catatan')}})
    updated = await db.dewi_rnd_sample_requests.find_one({'id': request_id})
    return (await _with_po_info(db, [serialize(updated)]))[0]


@router.post('/sample-requests/{request_id}/po-sampel')
async def create_sample_request_po(request_id: str, body: dict, user: dict = Depends(require_auth)):
    """'Buat draf PO sampel' untuk request yang SUDAH disetujui (mis. style baru dijadikan model sesudahnya).
    Aman diulang: PO yang sudah ada dikembalikan, tidak dibuat dua kali."""
    assert_can_act(user, 'rnd.approve', 'rnd.manage', portal='rnd', legacy_roles=RND_APPROVER_ROLES,
                   what='membuat draf PO sampel R&D')
    db = get_db()
    req = await db.dewi_rnd_sample_requests.find_one({'id': request_id}, {'_id': 0})
    if not req:
        raise HTTPException(404, 'Sample request tidak ditemukan')
    if req.get('status') != 'approved':
        raise HTTPException(400, 'Draf PO sampel dibuat setelah sample disetujui.')
    hasil = await buat_po_sampel(db, req, user, variant_id=str((body or {}).get('rahaza_variant_id') or '').strip())
    if not hasil.get('po_id'):
        raise HTTPException(400, hasil.get('po_catatan') or 'Draf PO sampel belum bisa dibuat.')
    upd = {k: hasil[k] for k in ('po_id', 'po_number', 'rahaza_variant_id', 'variant_sku', 'variant_label')
           if hasil.get(k) is not None}
    await db.dewi_rnd_sample_requests.update_one({'id': request_id},
                                                 {'$set': {**upd, 'po_catatan': None, 'updated_at': now_utc()}})
    updated = await db.dewi_rnd_sample_requests.find_one({'id': request_id})
    return serialize(updated)


@router.post('/sample-requests/{request_id}/reject')
async def reject_sample_request(request_id: str, body: dict, user: dict = Depends(require_auth)):
    assert_can_act(user, 'rnd.approve', portal='rnd', legacy_roles=RND_APPROVER_ROLES,
                   what='menolak permintaan sample RnD')
    db = get_db()
    req = await db.dewi_rnd_sample_requests.find_one({'id': request_id})
    if not req:
        raise HTTPException(404, 'Sample request tidak ditemukan')
    if req.get('status') != 'submitted':
        raise HTTPException(400, 'Hanya submitted yang bisa di-reject')

    await db.dewi_rnd_sample_requests.update_one(
        {'id': request_id},
        {'$set': {
            'status': 'rejected',
            'approval_status': 'rejected',
            'approved_by': user['id'],
            'approved_by_name': user.get('name', ''),
            'approved_at': now_utc(),
            'approval_notes': body.get('notes', ''),
            'updated_at': now_utc(),
        }},
    )
    updated = await db.dewi_rnd_sample_requests.find_one({'id': request_id})
    return serialize(updated)


@router.delete('/sample-requests/{request_id}')
async def delete_sample_request(request_id: str, user: dict = Depends(require_auth)):
    assert_can_act(user, 'rnd.manage', portal='rnd', what='menghapus data R&D')  # T-01 2.3
    db = get_db()
    res = await db.dewi_rnd_sample_requests.delete_one({'id': request_id})
    if res.deleted_count == 0:
        raise HTTPException(404, 'Sample request tidak ditemukan')
    return {'success': True}


# ──────────────────────────────────────────────────────────────────────────────
# REVISIONS (Design Revision Tracking)
# ──────────────────────────────────────────────────────────────────────────────

@router.get('/revisions')
async def list_revisions(
    style_id: str = None,
    limit: int = Query(200, ge=1, le=1000),
    user: dict = Depends(require_auth),
):
    db = get_db()
    q = {}
    if style_id:
        q['style_id'] = style_id

    items = await db.dewi_rnd_revisions.find(q).sort('created_at', -1).limit(limit).to_list(length=limit)
    return [serialize(it) for it in items]


@router.post('/revisions')
async def create_revision(body: dict, user: dict = Depends(require_auth)):
    db = get_db()
    style_id = body.get('style_id')
    if not style_id:
        raise HTTPException(400, 'style_id wajib diisi')

    style = await db.dewi_rnd_styles.find_one({'id': style_id})
    if not style:
        raise HTTPException(404, 'Style tidak ditemukan')

    prev_revisions = await db.dewi_rnd_revisions.find({'style_id': style_id}).sort('revision_number', -1).to_list(length=1)
    revision_number = 1 if not prev_revisions else prev_revisions[0].get('revision_number', 0) + 1

    doc = {
        'id': sid(),
        'style_id': style_id,
        'style_code': style.get('style_code', ''),
        'revision_number': revision_number,
        'revision_name': body.get('revision_name', f'Rev {revision_number}'),
        'changes_summary': body.get('changes_summary', ''),
        'reason': body.get('reason', ''),
        'previous_revision_id': body.get('previous_revision_id'),
        'created_by': user['id'],
        'created_by_name': user.get('name', ''),
        'created_at': now_utc(),
    }
    await db.dewi_rnd_revisions.insert_one(doc)
    return serialize(doc)


@router.get('/revisions/{revision_id}')
async def get_revision(revision_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    rev = await db.dewi_rnd_revisions.find_one({'id': revision_id})
    if not rev:
        raise HTTPException(404, 'Revision tidak ditemukan')
    return serialize(rev)


@router.put('/revisions/{revision_id}')
async def update_revision(revision_id: str, body: dict, user: dict = Depends(require_auth)):
    db = get_db()
    upd = {k: v for k, v in body.items() if k not in ('id', '_id', 'created_at', 'created_by')}
    upd['updated_at'] = now_utc()
    res = await db.dewi_rnd_revisions.update_one({'id': revision_id}, {'$set': upd})
    if res.matched_count == 0:
        raise HTTPException(404, 'Revision tidak ditemukan')
    return {'ok': True}


@router.delete('/revisions/{revision_id}')
async def delete_revision(revision_id: str, user: dict = Depends(require_auth)):
    assert_can_act(user, 'rnd.manage', portal='rnd', what='menghapus data R&D')  # T-01 2.3
    db = get_db()
    res = await db.dewi_rnd_revisions.delete_one({'id': revision_id})
    if res.deleted_count == 0:
        raise HTTPException(404, 'Revision tidak ditemukan')
    return {'success': True}
