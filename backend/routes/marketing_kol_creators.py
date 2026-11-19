"""marketing_kol — Admin: KOL Creator CRUD."""
from typing import Optional
from fastapi import Request, HTTPException
from pydantic import BaseModel, Field
from fastapi.params import Query
from database import get_db
from auth import hash_password, require_auth, serialize_doc, log_activity
from routes.shared import require_perm  # T-01 2.3
from routes.marketing_kol_shared import router, _uid, _now, _get_user, CreatorCreate, CreatorUpdate
from collections import defaultdict as _dd
from core import marketing_account_scope as _scope
from core import akun_kreator as _ak
from core import kreator_per_toko as _kt   # 19 Nov 2026: data kerja sama per toko

# 14 Nov 2026 (owner: filter toko menyeluruh) — kreator dipegang per toko lewat `assigned_account_ids`.
# Pemakai berlingkup toko hanya melihat kreator yang bertugas di tokonya, hanya melihat tautan ke tokonya
# sendiri, dan hanya boleh menautkan/melepas tokonya sendiri (tautan toko rekan kerja dipertahankan).
TANPA_TOKO_KREATOR = ("Pilih minimal satu toko yang Anda pegang untuk kreator ini, supaya kreatornya tetap "
                      "tampil di daftar Anda.")


def _samarkan_toko(creator: dict, visible) -> dict:
    """Tampilkan hanya tautan toko yang boleh dilihat pemakai (tautan lain tetap tersimpan)."""
    if visible is not None and creator is not None:
        creator['assigned_account_ids'] = _scope.saring_toko_terlihat(creator.get('assigned_account_ids'), visible)
    return creator


async def _toko_valid(db) -> set:
    return {a['id'] async for a in db.marketing_platform_accounts.find({}, {'_id': 0, 'id': 1})}


@router.post('/kol/creators')
async def create_creator(data: CreatorCreate, request: Request):
    user = await require_auth(request)
    db = get_db()
    assigned = await _scope.gabung_toko_terlihat(db, user, data.assigned_account_ids or [], [], apa='kreator ini')
    if not assigned and await _scope.toko_lingkup(db, user) is not None:
        raise HTTPException(400, TANPA_TOKO_KREATOR)
    email = (data.login_email or '').lower().strip()
    if data.creator_type not in ('new', 'kontrak', 'continue'):
        raise HTTPException(400, "creator_type harus new | kontrak | continue")
    if email and await db.marketing_kol_creators.find_one({'login_email': email}):
        raise HTTPException(400, f"Email '{data.login_email}' sudah terdaftar")
    if email and not data.login_password:
        raise HTTPException(400, "Email diisi tetapi password kosong — akun portal tidak "
                                 "akan bisa dipakai login. Isi password minimal 6 karakter.")
    if await db.marketing_kol_creators.find_one({'creator_code': data.creator_code}):
        raise HTTPException(400, f"Kode creator '{data.creator_code}' sudah ada")
    # 18 Nov 2026 — banyak akun per kreator; tanpa `accounts` (layar lama) akun dibaca dari `platforms`.
    akun = _ak.normalisasi(data.accounts if data.accounts is not None else _ak.dari_platforms(data.platforms),
                           await _toko_valid(db))
    await _ak.cek_bentrok(db, akun, None)
    creator = {
        'id': _uid(), 'creator_code': data.creator_code, 'name': data.name,
        'login_email': email,
        'login_password_hash': hash_password(data.login_password) if data.login_password else '',
        'portal_account_ready': bool(email and data.login_password),
        'creator_type': data.creator_type,
        'domicile': (data.domicile or '').strip(),
        'domicile_detail': (data.domicile_detail or '').strip(),
        'phone': data.phone or '', 'platforms': _ak.platforms_dari(akun, data.platforms or {}),
        'accounts': akun,
        'assigned_account_ids': assigned,
        'kpi_targets': data.kpi_targets or {'monthly_revenue': 0, 'monthly_sessions': 0, 'monthly_viewers': 0},
        'notes': data.notes or '', 'status': 'active', 'last_login_at': None,
        'created_at': _now(), 'created_by': _get_user(request).get('email', 'system'), 'updated_at': _now(),
    }
    await db.marketing_kol_creators.insert_one(creator)
    creator.pop('login_password_hash', None)
    user = _get_user(request)
    await log_activity(user.get('id', 'system'), user.get('name') or user.get('email', 'system'),
                       'create', 'marketing_kol_creator', f"Created creator: {data.name} ({data.creator_code})")
    return serialize_doc({'message': 'Creator berhasil dibuat', 'creator': creator})


@router.get('/kol/creators')
async def list_creators(
    request: Request,
    status: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None, description="Filter by assigned account"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    user = await require_auth(request)
    db = get_db()
    # 2026-11-02 — dulu (F14) kreator demo dibuat di sini, dan kreator TANPA login
    # diberi kata sandi demo setiap daftar dibuka. Seeder demo tidak lagi dipanggil saat GET.
    query = {}
    # 14 Nov 2026 — lingkup toko: hanya kreator yang bertugas di toko yang dipegang pemakai.
    visible = await _scope.toko_lingkup(db, user)
    if visible is not None:
        query['assigned_account_ids'] = {'$in': visible}
    if account_id:
        query['assigned_account_ids'] = (account_id if visible is None or account_id in visible
                                         else '__tidak_boleh_dilihat__')
    if status:
        # 19 Nov 2026 — status kreator per toko: dibaca di toko penyaring / toko yang dipegang pemakai
        stores = [account_id] if account_id else visible
        if stores:
            query.update(_kt.saring_status(status, stores))
        else:
            query['status'] = status
    total = await db.marketing_kol_creators.count_documents(query)
    skip = (page - 1) * limit
    creators = await db.marketing_kol_creators.find(
        query, {'_id': 0, 'login_password_hash': 0}
    ).sort('created_at', -1).skip(skip).limit(limit).to_list(500)
    # "bulan ini" = bulan Marketing berjalan, tanggal 26–25 (owner 11 Nov 2026) — sama dengan Target KOL
    from core import bulan_marketing as _bulan
    date_from, date_to = _bulan.rentang(*_bulan.bulan_berjalan())
    creator_ids = [c['id'] for c in creators]
    # angka "bulan ini" hanya dari sesi di toko yang boleh dilihat (kreator bisa dipakai beberapa toko)
    all_sessions = await db.marketing_creator_sessions.find(
        await _scope.saring_lingkup(db, user, {'creator_id': {'$in': creator_ids},
                                             'date': {'$gte': date_from, '$lte': date_to}}),
        {'_id': 0, 'creator_id': 1, 'revenue': 1, 'viewers': 1}
    ).to_list(500)
    for c in creators:
        _kt.terapkan(c, visible, account_id)
        _samarkan_toko(c, visible)
        _ak.lengkapi(c)
    sessions_by_creator = _dd(list)
    for s in all_sessions:
        sessions_by_creator[s['creator_id']].append(s)
    for c in creators:
        sessions = sessions_by_creator.get(c['id'], [])
        c['this_month'] = {
            'sessions': len(sessions),
            'revenue': round(sum(s.get('revenue', 0) for s in sessions)),
            'viewers': sum(s.get('viewers', 0) for s in sessions),
        }
    return serialize_doc({
        'creators': creators,
        'pagination': {
            'total': total, 'page': page, 'limit': limit,
            'total_pages': (total + limit - 1) // limit if total > 0 else 1,
            'has_next': skip + limit < total, 'has_prev': page > 1,
        }
    })


@router.get('/kol/creators/{creator_id}')
async def get_creator(creator_id: str, request: Request, account_id: Optional[str] = Query(None)):
    user = await require_auth(request)
    db = get_db()
    creator = await db.marketing_kol_creators.find_one({'id': creator_id}, {'_id': 0, 'login_password_hash': 0})
    if not creator:
        raise HTTPException(404, 'Creator tidak ditemukan')
    # (toko rekaman dijaga core.marketing_record_scope; di sini hanya menyembunyikan toko rekan kerja)
    visible = await _scope.toko_lingkup(db, user)
    _kt.terapkan(creator, visible, account_id)
    _samarkan_toko(creator, visible)
    _ak.lengkapi(creator)
    assigned = await db.marketing_platform_accounts.find(
        {'id': {'$in': creator.get('assigned_account_ids', [])}}, {'_id': 0}
    ).to_list(500)
    creator['assigned_accounts'] = assigned
    return serialize_doc(creator)


@router.put('/kol/creators/{creator_id}')
async def update_creator(creator_id: str, data: CreatorUpdate, request: Request):
    user = await require_auth(request)
    db = get_db()
    creator = await db.marketing_kol_creators.find_one({'id': creator_id}, {'_id': 0})
    if not creator:
        raise HTTPException(404, 'Creator tidak ditemukan')
    update_data = {}
    if data.name is not None:
        update_data['name'] = data.name
    if data.domicile is not None:
        update_data['domicile'] = data.domicile.strip()
    if data.domicile_detail is not None:
        update_data['domicile_detail'] = data.domicile_detail.strip()
    if data.login_email is not None:
        em = data.login_email.lower().strip()
        if em:
            dup = await db.marketing_kol_creators.find_one(
                {'login_email': em, 'id': {'$ne': creator_id}}, {'_id': 0, 'id': 1})
            if dup:
                raise HTTPException(400, f"Email '{em}' sudah dipakai kreator lain")
        update_data['login_email'] = em
    if data.phone is not None:
        update_data['phone'] = data.phone
    if data.accounts is not None:
        akun = _ak.normalisasi(data.accounts, await _toko_valid(db))
        await _ak.cek_bentrok(db, akun, creator_id)
        update_data['accounts'] = akun
        update_data['platforms'] = _ak.platforms_dari(akun)
    elif data.platforms is not None:
        update_data['platforms'] = data.platforms
        update_data['accounts'] = _ak.normalisasi(_ak.dari_platforms(data.platforms), await _toko_valid(db))
    if data.assigned_account_ids is not None:
        # hanya toko yang dipegang pemakai yang boleh ditambah/dilepas; tautan toko lain dipertahankan
        update_data['assigned_account_ids'] = await _scope.gabung_toko_terlihat(
            db, user, data.assigned_account_ids, creator.get('assigned_account_ids'), apa='kreator ini')
    # 19 Nov 2026 (keputusan owner) — status, tipe, target, catatan = data kerja sama PER TOKO.
    visible = await _scope.toko_lingkup(db, user)
    toko_semua = update_data.get('assigned_account_ids', creator.get('assigned_account_ids') or [])
    lama = _kt.bersihkan({'status': data.status, 'creator_type': data.creator_type,
                          'kpi_targets': data.kpi_targets, 'notes': data.notes})
    ubah = {}
    for acc, isi in (data.per_toko or {}).items():
        if acc not in toko_semua:
            raise HTTPException(400, 'Data kerja sama hanya untuk toko yang ditugaskan ke kreator ini.')
        if visible is not None and acc not in visible:
            raise HTTPException(403, 'Anda hanya boleh mengubah data kerja sama untuk toko yang Anda pegang.')
        ubah[acc] = _kt.bersihkan(isi)
    if lama:
        if data.account_id and data.account_id in toko_semua and (visible is None or data.account_id in visible):
            ubah[data.account_id] = {**lama, **ubah.get(data.account_id, {})}
        elif visible is not None and toko_semua:
            for acc in toko_semua:
                if acc in visible:
                    ubah[acc] = {**lama, **ubah.get(acc, {})}
        else:
            update_data.update(lama)   # tanpa toko / pemakai semua toko tanpa toko pilihan: nilai awal
    if ubah:
        update_data.update(_kt.pecah(creator, ubah, toko_semua, user))
    if data.login_password:
        update_data['login_password_hash'] = hash_password(data.login_password)
        update_data['portal_account_ready'] = bool(
            update_data.get('login_email') or creator.get('login_email'))
    update_data['updated_at'] = _now()
    await db.marketing_kol_creators.update_one({'id': creator_id}, {'$set': update_data})
    await log_activity(user.get('id', 'system'), user.get('name') or user.get('email', 'system'),
                       'update', 'marketing_kol_creator', f"Updated creator: {creator['name']}")
    updated = await db.marketing_kol_creators.find_one({'id': creator_id}, {'_id': 0, 'login_password_hash': 0})
    _kt.terapkan(updated, visible, data.account_id)
    _samarkan_toko(updated, visible)
    _ak.lengkapi(updated)
    return serialize_doc({'message': 'Creator berhasil diupdate', 'creator': updated})


def creator_usage_checks(creator_id: str) -> list:
    """Riwayat kreator (10 Nov 2026): dokumen yang menunjuk kreator ini (grep `creator_id`/`kreator_id`)."""
    q = {'creator_id': creator_id}
    return [
        ('sesi live kreator', 'marketing_creator_sessions', q),
        ('sesi live', 'marketing_live_sessions', q),
        ('pesanan', 'marketing_orders', q),
        ('kiriman sampel', 'marketing_samples', q),
        ('permintaan produk', 'marketing_creator_item_requests', q),
        ('permintaan kreator', 'dewi_kreator_requests', {'kreator_id': creator_id}),
        ('jadwal konten', 'marketing_content_calendar', q),
        # 10 Nov 2026 (keputusan owner): target bulanan bukan riwayat — ikut terhapus bersama kreator.
        ('catatan insentif', 'marketing_creator_incentive_entries', q),
        ('rapor mingguan', 'marketing_creator_weekly_reports', q),
    ]


@router.delete('/kol/creators/{creator_id}')
async def deactivate_creator(creator_id: str, request: Request, hard: bool = Query(False)):
    """Tanpa `hard` = nonaktifkan (perilaku lama). `?hard=true` (10 Nov 2026) = hapus permanen bila kreator belum
    punya riwayat (`creator_usage_checks`); bila sudah → 409 dan layar menawarkan Nonaktifkan."""
    user = await require_perm(request, 'toko.manage', legacy_roles=('manager_marketing', 'pic_marketing', 'staff_marketing', 'pic_toko', 'marketing_kol', 'cs_staff', 'manager', 'owner', 'admin', 'superadmin'),
                              message='Akses ditolak: Anda tidak berhak menonaktifkan atau menghapus kreator.')  # T-01 2.3
    db = get_db()
    creator = await db.marketing_kol_creators.find_one({'id': creator_id}, {'_id': 0})
    if not creator:
        raise HTTPException(404, 'Creator tidak ditemukan')
    if hard:
        from core.hapus_master import hitung_pemakaian, tolak_bila_dipakai
        pakai = await hitung_pemakaian(db, creator_usage_checks(creator_id))
        tolak_bila_dipakai('Kreator', creator.get('name') or '', pakai)
        target = await db.marketing_creator_targets.delete_many({'creator_id': creator_id})
        await db.marketing_kol_creators.delete_one({'id': creator_id})
        await log_activity(user.get('id', 'system'), user.get('name') or user.get('email', 'system'),
                           'delete', 'marketing_kol_creator',
                           f"Hapus kreator {creator.get('name', '')} (target bulanan {target.deleted_count})")
        return {'ok': True, 'deleted': True, 'message': 'Kreator dihapus'}
    # 19 Nov 2026 — status per toko: staf toko menonaktifkan kreator untuk TOKONYA saja; pemakai semua toko
    # menonaktifkan di semua toko.
    visible = await _scope.toko_lingkup(db, user)
    toko_semua = creator.get('assigned_account_ids') or []
    milik = [a for a in toko_semua if visible is None or a in visible]
    upd = {'updated_at': _now()}
    if visible is None:
        upd['status'] = 'inactive'
    upd.update(_kt.pecah(creator, {a: {'status': 'inactive'} for a in milik}, toko_semua, user))
    await db.marketing_kol_creators.update_one({'id': creator_id}, {'$set': upd})
    user = _get_user(request)
    await log_activity(user.get('id', 'system'), user.get('name') or user.get('email', 'system'),
                       'deactivate', 'marketing_kol_creator', f"Deactivated creator: {creator['name']}")
    return serialize_doc({'message': 'Creator dinonaktifkan' if visible is None
                          else 'Kreator dinonaktifkan untuk toko Anda'})


class PortalAccountIn(BaseModel):
    login_email: str = Field(..., min_length=5)
    login_password: str = Field(..., min_length=6)


@router.post('/kol/creators/{creator_id}/portal-account')
async def set_portal_account(creator_id: str, data: PortalAccountIn, request: Request):
    """SESI #34 — **buat / setel ulang akun portal kreator**.

    Kenapa endpoint ini ada: 3 kreator demo di database lahir dari penyemai lama
    TANPA `login_email`/`login_password_hash` sama sekali. Akibatnya pemilik
    membuka Portal Kreator dan tidak bisa login — dan tidak ada satu pun layar
    yang bisa memperbaikinya (PUT hanya bisa mengganti password, bukan membuat
    email). Sekarang staf marketing bisa membuatkan akunnya, dan layar bisa
    mengatakan kreator mana yang BELUM punya akun (`portal_account_ready`).
    """
    await require_auth(request)
    db = get_db()
    creator = await db.marketing_kol_creators.find_one({'id': creator_id}, {'_id': 0})
    if not creator:
        raise HTTPException(404, 'Creator tidak ditemukan')
    email = data.login_email.lower().strip()
    dup = await db.marketing_kol_creators.find_one(
        {'login_email': email, 'id': {'$ne': creator_id}}, {'_id': 0, 'id': 1})
    if dup:
        raise HTTPException(400, f"Email '{email}' sudah dipakai kreator lain")
    await db.marketing_kol_creators.update_one({'id': creator_id}, {'$set': {
        'login_email': email,
        'login_password_hash': hash_password(data.login_password),
        'portal_account_ready': True,
        'status': creator.get('status') or 'active',
        'updated_at': _now(),
    }})
    user = _get_user(request)
    await log_activity(user.get('id', 'system'), user.get('name') or user.get('email', 'system'),
                       'update', 'marketing_kol_creator',
                       f"Akun portal kreator {creator.get('name')} disetel ({email})")
    return {'ok': True, 'message': f"Akun portal siap dipakai: {email}",
            'creator_id': creator_id, 'login_email': email}
