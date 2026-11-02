"""
P3 TD-010 Part B — Unified Notifications Helper (Session #11.12)
================================================================
Single SSOT helper for the `notifications` collection.

After Session #11.12 (TD-010 Phase B), ALL legacy notification writers
(dewi_notifications, rahaza_notifications, collab_notifications,
marketing_livehost_notifications) have been refactored to call
`notif_insert()` directly. The 4 legacy collections are now empty
and scheduled for removal after a 1-week monitor period via
`migrations/drop_legacy_notif_collections.py`.

This module also exposes BACKWARD-COMPAT reshape helpers used by
the 4 legacy routers to keep their public response schema unchanged
while reading from the SSOT.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, Any, List
import uuid


VALID_TYPES = {'dewi', 'rahaza', 'collab', 'marketing_livehost'}
VALID_SEVERITIES = {'info', 'success', 'warning', 'error'}
VALID_CHANNELS = {'in_app', 'whatsapp', 'email', 'sse'}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# WAKTU KE KLIEN — SELALU DENGAN ZONA (2026-11-02)
#
# Motor dibuka tanpa `tz_aware` (database.py), jadi `created_at` kembali sebagai
# datetime NAIF bernilai UTC dan dulu dikirim "2026-11-01T21:33:43.861000".
# Browser menafsirkan string tanpa offset sebagai waktu LOKAL ⇒ di WIB setiap
# notifikasi tampil 7 jam lebih tua ("7 jam lalu" untuk notifikasi 1 menit) dan
# Portal Saya menampilkan jam UTC mentah. Semua pembaca notifikasi kini memakai
# `iso_utc` → "2026-11-01T21:33:43.861Z" (milidetik, aman untuk semua browser).
# ─────────────────────────────────────────────────────────────────────────────

def iso_utc(v: Any) -> Any:
    """datetime → ISO UTC ber-'Z' (naif dianggap UTC, sesuai cara penyimpanan)."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    return v


_TIME_FIELDS = ('created_at', 'read_at', 'sent_at', 'updated_at')


def notif_times_iso(doc: dict) -> dict:
    """Salinan dokumen dengan field waktu notifikasi sudah ber-zona (lihat `iso_utc`)."""
    out = dict(doc or {})
    for k in _TIME_FIELDS:
        if k in out:
            out[k] = iso_utc(out[k])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# TAUTAN MODUL — id yang tidak ada di registry frontend (2026-11-02)
#
# Audit 2026-11-02: 7 id `link_module` yang ditulis backend TIDAK ada di
# MODULE_REGISTRY frontend, sehingga tombol "Buka" diam (ditandai dibaca, layar
# tidak berubah). 258 notifikasi stok kritis (30% isi DB) terdampak. Peta ini
# dipakai SAAT TULIS (`notif_insert`) dan SAAT BACA (bel/Portal Saya), jadi
# notifikasi lama ikut sembuh dan penulis di berkas lain yang belum diperbaiki
# tetap mendarat di layar yang hidup. Uji kontrak: tests/unit/test_notif_p7.py
# memastikan setiap tujuan di peta ini ADA di frontend moduleRegistry.js.
# ─────────────────────────────────────────────────────────────────────────────
LINK_MODULE_ALIASES = {
    # stok kritis (mesin alert) — penulis kembar `rahaza_inventory_shared` sudah memakai wh-stock
    'prod-materials': 'wh-stock',
    # klaim biaya / perjalanan dinas / settlement → tab "Approval Klaim & Dinas"
    'hr-approval-inbox': 'hr-expense-approval',
    # salah ejaan garis bawah vs tanda hubung
    'hr_salary_adjustments': 'hr-salary-adjustments',
    'kpi_portal': 'kpi-portal',
    'hr_kpi': 'hr-kpi',
    'hris_employees': 'hr-employees',
    'my_profile': 'portal-profile',
}


def normalize_link_module(mod: Optional[str]) -> Optional[str]:
    if not mod:
        return mod
    return LINK_MODULE_ALIASES.get(str(mod), mod)


# ─────────────────────────────────────────────────────────────────────────────
# PERAN PENERIMA ALERT — HANYA PERAN NYATA (2026-11-02)
#
# Audit 2026-11-02 (N1): alert stok kritis/WO/kontrak ditarget ke peran yang
# tidak pernah ada (`warehouse_manager`, `manager_production`,
# `production_manager`) ⇒ hanya superadmin yang menerima; admin gudang tidak
# pernah tahu stoknya kritis. Peran pengganti DITURUNKAN dari PORTAL_ACCESS
# portal terkait (routes/shared.py), lalu dipersempit ke peran yang memegang
# kewenangan domain itu (core/roles.py) supaya alert tindakan tidak menyiram
# staf lini/operator. Keduanya SSOT repo — tidak ada daftar peran baru di sini.
# ─────────────────────────────────────────────────────────────────────────────
# Peran fiktif → portal asal tugasnya. `finance` = nama generik lama; peran
# keuangan yang benar-benar ada: accounting/staff_keuangan/manager_keuangan
# (core/roles.py). Dipakai `notif_insert` sehingga penulis di berkas LAIN yang
# masih menulis peran fiktif (stok rendah mutasi, rak kritis, shipment) ikut
# sampai ke orang nyata tanpa menunggu tiap berkas diperbaiki.
PHANTOM_ROLE_PORTAL = {
    'warehouse_manager': 'warehouse',
    'manager_production': 'production',
    'production_manager': 'production',
    'finance': 'finance',
}
PHANTOM_ROLES = set(PHANTOM_ROLE_PORTAL)


def _domain_roles(portal: str):
    from core import roles as _r
    return {
        'warehouse': _r.WAREHOUSE_ROLES,
        'production': _r.PRODUCTION_ROLES,
        'hr': _r.HR_ROLES,
        'finance': _r.FINANCE_ROLES,
    }.get(portal)


def alert_roles_for_portal(portal: str) -> List[str]:
    """Peran nyata portal `portal` (PORTAL_ACCESS ∩ peran domain core/roles)."""
    from routes.shared import PORTAL_ACCESS
    base = list(PORTAL_ACCESS.get(portal) or [])
    domain = _domain_roles(portal)
    return sorted({r for r in base if domain is None or r in domain})


def expand_phantom_roles(roles) -> List[str]:
    """Setiap peran fiktif diganti peran nyata portalnya; peran lain tetap."""
    out = set()
    for r in roles or []:
        r = str(r).lower()
        portal = PHANTOM_ROLE_PORTAL.get(r)
        if portal:
            out |= set(alert_roles_for_portal(portal))
        else:
            out.add(r)
    return sorted(out)


def real_target_roles(roles, portal: str, *, keep=('superadmin',)) -> List[str]:
    """Ganti peran fiktif di `roles` dengan peran nyata portal `portal`.

    Dipakai juga untuk pengaturan yang tersimpan di DB (mis.
    `rahaza_alert_settings.alert_target_roles` masih berisi `manager_production`).
    """
    roles = [str(r).lower() for r in (roles or [])]
    out = {r for r in roles if r not in PHANTOM_ROLES}
    if not roles or any(r in PHANTOM_ROLES for r in roles):
        out |= set(alert_roles_for_portal(portal))
    out |= set(keep or ())
    return sorted(out)


# ─────────────────────────────────────────────────────────────────────────────
# CORE INSERT
# ─────────────────────────────────────────────────────────────────────────────

async def notif_insert(
    db,
    *,
    type: str,
    body: str,
    id: Optional[str] = None,
    subtype: Optional[str] = None,
    severity: str = 'info',
    user_id: Optional[str] = None,
    title: Optional[str] = None,
    channel: str = 'in_app',
    recipient: Optional[str] = None,
    target_roles: Optional[List[str]] = None,
    target_user_ids: Optional[List[str]] = None,
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    source_ref: Optional[str] = None,
    client_id: Optional[str] = None,
    host_id: Optional[str] = None,
    meta: Optional[dict] = None,
    status: str = 'queued',
    sent_at: Optional[datetime] = None,
    read: bool = False,
    failed_reason: Optional[str] = None,
) -> str:
    """Insert a notification into the SSOT `notifications` collection.

    Returns the new notification id (UUID).

    Arguments:
        type:        Domain discriminator. Must be one of VALID_TYPES.
        body:        Main message body. Required.
        id:          Optional pre-allocated UUID (else generated).
        subtype:     Optional sub-classification (event_type, notif_type, etc.)
        severity:    info|success|warning|error
        user_id:     Recipient user id (None for broadcast)
        title:       Optional title/subject
        channel:     Delivery channel: in_app|whatsapp|email|sse
        recipient:   Phone/email when external delivery (whatsapp/email)
        source_*:    Linking info to originating resource
        client_id:   For dewi external client notifs
        host_id:     For marketing_livehost SSE
        meta:        Free-form metadata dict
        status:      queued|sent|failed|read
        sent_at:     Timestamp the notification was actually sent (channel ack)
        read:        Initial read state (default False)
        failed_reason: Error string when status='failed'
    """
    if type not in VALID_TYPES:
        raise ValueError(f'Invalid notification type {type!r}; must be one of {VALID_TYPES}')
    if severity not in VALID_SEVERITIES:
        severity = 'info'
    if channel not in VALID_CHANNELS:
        channel = 'in_app'

    # Target penerima kanonik di `meta` (dibaca `notif_audience_query`). Penulis
    # boleh mengirim lewat argumen ini ATAU lewat meta — keduanya digabung.
    meta = dict(meta or {})
    # 2026-11-02 — id modul mati dipetakan ke id hidup (lihat LINK_MODULE_ALIASES).
    if meta.get('link_module'):
        meta['link_module'] = normalize_link_module(meta['link_module'])
    if target_roles:
        meta['target_roles'] = sorted({str(r).lower() for r in
                                       (list(meta.get('target_roles') or []) + list(target_roles))})
    elif meta.get('target_roles'):
        meta['target_roles'] = sorted({str(r).lower() for r in meta['target_roles']})
    # 2026-11-02 — peran fiktif tidak punya user ⇒ ganti peran nyata portalnya.
    if meta.get('target_roles') and PHANTOM_ROLES & set(meta['target_roles']):
        meta['target_roles'] = expand_phantom_roles(meta['target_roles'])
    if target_user_ids:
        meta['target_user_ids'] = sorted({str(u) for u in
                                          (list(meta.get('target_user_ids') or [])
                                           + list(target_user_ids))})
    doc = {
        'id':            id or str(uuid.uuid4()),
        'type':          type,
        'subtype':       subtype,
        'severity':      severity,
        'user_id':       user_id,
        'title':         title,
        'body':          body,
        'channel':       channel,
        'recipient':     recipient,
        'source_type':   source_type,
        'source_id':     source_id,
        'source_url':    source_url,
        'source_ref':    source_ref,
        'client_id':     client_id,
        'host_id':       host_id,
        'meta':          meta,
        'status':        status,
        'read':          read,
        'read_at':       None,
        'created_at':    _now(),
        'sent_at':       sent_at,
        'failed_reason': failed_reason,
    }
    await db.notifications.insert_one(doc)
    return doc['id']


# ─────────────────────────────────────────────────────────────────────────────
# AUDIENS / RBAC NOTIFIKASI — SATU MESIN untuk semua pembaca (2026-08-07)
#
# MASALAH YANG DIPERBAIKI (audit atas pertanyaan owner "jangan sampai role A
# menerima notifikasi role B"):
#   1. Dua konvensi penerima hidup bersama: penulis lama menaruh
#      `target_roles` / `target_user_ids` di akar dokumen, `publish_notification`
#      menaruhnya di `meta`, dan `notif_insert` memakai `user_id` per orang.
#      Setiap pembaca memakai aturannya sendiri ⇒ ada notifikasi yang tidak
#      pernah tampil, dan ada yang tampil ke orang yang tidak berhak.
#   2. Dokumen TANPA target dianggap "siaran untuk semua" ⇒ satu penulis yang
#      lupa mengisi target langsung membocorkan info lintas role.
#
# ATURAN SEKARANG (dipakai bel, inbox, hitungan belum dibaca, tandai dibaca):
#   penerima  = `user_id` == saya  ATAU  target_user_ids memuat saya
#               ATAU target_roles memuat role saya
#   tanpa target sama sekali = HANYA admin/owner/superadmin
#   status baca: dokumen personal → field `read`; dokumen banyak penerima →
#               `meta.read_by` (per orang, tidak saling menandai)
# ─────────────────────────────────────────────────────────────────────────────

NOTIF_SUPER_ROLES = {'superadmin', 'admin', 'owner'}
_EMPTY = {'$in': [None, []]}


def notif_user_id(user: dict) -> Optional[str]:
    return (user.get('id') or user.get('user_id') or user.get('sub')
            or user.get('email'))


def notif_recipient_or(user: dict) -> list:
    """Klausa $or Mongo: dokumen mana yang ditujukan kepada `user`."""
    uid = notif_user_id(user)
    role = (user.get('role') or '').lower()
    ors: list = [
        {'user_id': uid},
        {'target_user_ids': uid},
        {'meta.target_user_ids': uid},
    ]
    if role:
        ors += [{'target_roles': role}, {'meta.target_roles': role}]
    if role in NOTIF_SUPER_ROLES:
        ors.append({'user_id': None, 'target_user_ids': _EMPTY,
                    'target_roles': _EMPTY, 'meta.target_user_ids': _EMPTY,
                    'meta.target_roles': _EMPTY})
    return ors


def notif_audience_query(user: dict, extra: Optional[dict] = None) -> dict:
    """Query lengkap (audiens + belum dibuang) untuk daftar notifikasi user."""
    q: dict = {
        '$or': notif_recipient_or(user),
        'dismissed': {'$ne': True},
        'meta.dismissed': {'$ne': True},
    }
    if extra:
        q.update(extra)
    return q


def notif_visible_to(doc: dict, user: dict) -> bool:
    """Versi Python dari aturan audiens (untuk filter setelah query)."""
    if not doc:
        return False
    uid = notif_user_id(user)
    role = (user.get('role') or '').lower()
    meta = doc.get('meta') or {}
    if doc.get('user_id'):
        return doc.get('user_id') == uid
    users = list(doc.get('target_user_ids') or []) + list(meta.get('target_user_ids') or [])
    roles = [str(r).lower() for r in
             (list(doc.get('target_roles') or []) + list(meta.get('target_roles') or []))]
    if uid in users or role in roles:
        return True
    if not users and not roles:
        return role in NOTIF_SUPER_ROLES
    return False


def notif_is_unread_for(doc: dict, user: dict) -> bool:
    """Belum dibaca oleh user ini (personal: `read`; bersama: `meta.read_by`)."""
    uid = notif_user_id(user)
    meta = doc.get('meta') or {}
    if doc.get('user_id'):
        return not doc.get('read')
    read_by = list(meta.get('read_by') or []) + list(doc.get('read_by') or [])
    return uid not in read_by


async def notif_mark_read_for(db, notif_id: str, user: dict) -> bool:
    """Tandai dibaca HANYA untuk user ini (tidak menandai penerima lain)."""
    uid = notif_user_id(user)
    doc = await db.notifications.find_one({'id': notif_id}, {'_id': 0})
    if not doc or not notif_visible_to(doc, user):
        return False
    if doc.get('user_id'):
        res = await db.notifications.update_one(
            {'id': notif_id, 'user_id': uid},
            {'$set': {'read': True, 'read_at': _now()}})
        return res.matched_count > 0
    res = await db.notifications.update_one(
        {'id': notif_id}, {'$addToSet': {'meta.read_by': uid}})
    return res.matched_count > 0


async def notif_mark_all_read_for(db, user: dict, *, type: Optional[str] = None) -> int:
    """Tandai semua notifikasi milik user (personal + bersama) sebagai dibaca."""
    uid = notif_user_id(user)
    extra = {'type': type} if type else None
    # 2026-11-02 — tanpa batas 2000: "tandai semua" harus benar-benar semua.
    rows = await db.notifications.find(
        notif_audience_query(user, extra), _UNREAD_PROJECTION).to_list(None)
    personal = [r['id'] for r in rows if r.get('user_id') and notif_is_unread_for(r, user)]
    shared = [r['id'] for r in rows if not r.get('user_id') and notif_is_unread_for(r, user)]
    n = 0
    if personal:
        res = await db.notifications.update_many(
            {'id': {'$in': personal}}, {'$set': {'read': True, 'read_at': _now()}})
        n += res.modified_count
    if shared:
        res = await db.notifications.update_many(
            {'id': {'$in': shared}}, {'$addToSet': {'meta.read_by': uid}})
        n += res.modified_count
    return n


# Proyeksi minimum untuk menghitung status baca (tanpa body/judul).
_UNREAD_PROJECTION = {'_id': 0, 'id': 1, 'user_id': 1, 'read': 1, 'read_by': 1,
                      'meta.read_by': 1}


async def notif_count_unread_for(db, user: dict, *, type: Optional[str] = None) -> int:
    """Jumlah belum dibaca yang SEBENARNYA.

    2026-11-02 — dulu `to_list(2000)` (dan bel memakai jendela 200 dokumen) ⇒
    angka terpotong. Sekarang seluruh dokumen audiens dihitung dengan proyeksi
    ringan, jadi angka bel = angka Portal Saya = jumlah nyata.
    """
    extra = {'type': type} if type else None
    n = 0
    async for r in db.notifications.find(notif_audience_query(user, extra), _UNREAD_PROJECTION):
        if notif_is_unread_for(r, user):
            n += 1
    return n


async def notif_list_for(db, user: dict, *, type: Optional[str] = None,
                         severity: Optional[str] = None, unread_only: bool = False,
                         limit: int = 50, skip: int = 0) -> list:
    """Daftar notifikasi yang BOLEH dilihat user (audiens ditegakkan di query)."""
    extra: dict = {}
    if type:
        extra['type'] = type
    if severity:
        extra['severity'] = severity
    rows = await (db.notifications.find(notif_audience_query(user, extra), {'_id': 0})
                  .sort('created_at', -1).skip(skip).limit(limit * 3 if unread_only else limit)
                  ).to_list(limit * 3 if unread_only else limit)
    if unread_only:
        rows = [r for r in rows if notif_is_unread_for(r, user)][:limit]
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# READ/COUNT/UPDATE
# ─────────────────────────────────────────────────────────────────────────────

async def notif_mark_read(db, notif_id: str, *, user_id: Optional[str] = None) -> bool:
    """Mark a notification as read. Returns True if a doc was updated.

    For single-recipient notifs (user_id-scoped), pass user_id for safety.
    For multi-recipient rahaza notifs, use update_meta to push to read_by[].
    """
    flt: dict = {'id': notif_id}
    if user_id:
        flt['user_id'] = user_id
    res = await db.notifications.update_one(
        flt,
        {'$set': {'read': True, 'read_at': _now()}},
    )
    return res.modified_count > 0


async def notif_count_unread(
    db, *, user_id: Optional[str] = None, type: Optional[str] = None,
) -> int:
    flt: dict = {'read': False}
    if user_id:
        flt['user_id'] = user_id
    if type:
        flt['type'] = type
    return await db.notifications.count_documents(flt)


async def notif_list(
    db,
    *,
    user_id: Optional[str] = None,
    type: Optional[str] = None,
    severity: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 50,
    skip: int = 0,
) -> list:
    flt: dict = {}
    if user_id:
        flt['user_id'] = user_id
    if type:
        flt['type'] = type
    if severity:
        flt['severity'] = severity
    if unread_only:
        flt['read'] = False
    cursor = (
        db.notifications
        .find(flt, {'_id': 0})
        .sort('created_at', -1)
        .skip(skip)
        .limit(limit)
    )
    return [doc async for doc in cursor]


async def notif_find_one(db, flt: dict) -> Optional[dict]:
    """Get a single notif by arbitrary filter (excludes _id)."""
    return await db.notifications.find_one(flt, {'_id': 0})


async def notif_update_one(db, flt: dict, update: dict) -> int:
    """Apply a Mongo update operator on a single notif. Returns modified count."""
    res = await db.notifications.update_one(flt, update)
    return res.modified_count


async def notif_update_many(db, flt: dict, update: dict) -> int:
    """Apply a Mongo update on multiple notifs. Returns modified count."""
    res = await db.notifications.update_many(flt, update)
    return res.modified_count


async def notif_delete_one(db, flt: dict) -> int:
    """Delete a single notif. Returns delete count."""
    res = await db.notifications.delete_one(flt)
    return res.deleted_count


# ─────────────────────────────────────────────────────────────────────────────
# SERIALIZE
# ─────────────────────────────────────────────────────────────────────────────

def serialize_notif(doc: Any) -> dict:
    """Return a JSON-safe shallow copy (datetimes → ISO strings)."""
    if doc is None:
        return None  # type: ignore
    out = dict(doc)
    out.pop('_id', None)
    for k, v in out.items():
        if isinstance(v, datetime):
            out[k] = iso_utc(v)   # 2026-11-02 — selalu ber-zona (lihat iso_utc)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# BACKWARD-COMPAT RESHAPE HELPERS
# Each helper converts an SSOT doc back into the legacy router's response
# schema so frontend clients continue to receive the same shape.
# ─────────────────────────────────────────────────────────────────────────────

def reshape_as_dewi(doc: dict) -> dict:
    """Reshape SSOT doc → legacy `dewi_notifications` schema."""
    if not doc:
        return {}
    out = dict(doc)
    out.pop('_id', None)
    meta = out.get('meta') or {}
    # Legacy field projection
    return {
        'id':            out.get('id'),
        'channel':       out.get('channel'),
        'recipient':     out.get('recipient'),
        'subject':       out.get('title'),
        'body':          out.get('body'),
        'event_type':    out.get('subtype'),
        'source_ref':    out.get('source_ref'),
        'client_id':     out.get('client_id'),
        'status':        out.get('status'),
        'meta':          {k: v for k, v in meta.items() if k not in ('sent_real', 'sent_mock')},
        'sent_real':     meta.get('sent_real', False),
        'sent_mock':     meta.get('sent_mock', False),
        'created_at':    _to_iso(out.get('created_at')),
        'sent_at':       _to_iso(out.get('sent_at')),
        'failed_reason': out.get('failed_reason'),
    }


def reshape_as_rahaza(doc: dict, *, current_user_id: Optional[str] = None) -> dict:
    """Reshape SSOT doc → legacy `rahaza_notifications` schema.

    Multi-recipient fields (target_roles, target_user_ids, read_by, dismissed,
    dedup_key) are stored in `meta` and reprojected to top-level.
    """
    if not doc:
        return {}
    out = dict(doc)
    out.pop('_id', None)
    meta = out.get('meta') or {}
    read_by = meta.get('read_by') or []
    shaped = {
        'id':              out.get('id'),
        'type':            out.get('subtype'),
        'severity':        out.get('severity'),
        'title':           out.get('title'),
        'message':         out.get('body'),
        'link_module':     meta.get('link_module'),
        'link_id':         out.get('source_id'),
        'target_roles':    meta.get('target_roles') or [],
        'target_user_ids': meta.get('target_user_ids') or [],
        'dedup_key':       meta.get('dedup_key'),
        'read_by':         read_by,
        'dismissed':       bool(meta.get('dismissed', False)),
        'created_at':      _to_iso(out.get('created_at')),
    }
    if current_user_id is not None:
        shaped['read'] = current_user_id in read_by
    return shaped


def reshape_as_collab(doc: dict) -> dict:
    """Reshape SSOT doc → legacy `collab_notifications` schema."""
    if not doc:
        return {}
    out = dict(doc)
    out.pop('_id', None)
    meta = out.get('meta') or {}
    return {
        'notification_id': out.get('id'),
        'user_id':         out.get('user_id'),
        'type':            out.get('subtype'),
        'icon':            meta.get('icon'),
        'title':           out.get('title'),
        'content':         out.get('body'),
        'source_type':     out.get('source_type'),
        'source_id':       out.get('source_id'),
        'source_url':      out.get('source_url'),
        'metadata':        {k: v for k, v in meta.items() if k != 'icon'},
        'read':            bool(out.get('read', False)),
        'read_at':         _to_iso(out.get('read_at')),
        'created_at':      _to_iso(out.get('created_at')),
    }


def reshape_as_livehost(doc: dict) -> dict:
    """Reshape SSOT doc → legacy `marketing_livehost_notifications` schema."""
    if not doc:
        return {}
    out = dict(doc)
    out.pop('_id', None)
    return {
        'id':         out.get('id'),
        'host_id':    out.get('host_id'),
        'type':       out.get('subtype'),
        'severity':   out.get('severity'),
        'title':      out.get('title'),
        'message':    out.get('body'),
        'link':       out.get('source_url'),
        'read':       bool(out.get('read', False)),
        'read_at':    _to_iso(out.get('read_at')),
        'created_at': _to_iso(out.get('created_at')),
    }


def _to_iso(v: Any) -> Optional[str]:
    """Convert datetime → ISO string; pass-through strings/None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return iso_utc(v)   # 2026-11-02 — selalu ber-zona (lihat iso_utc)
    return v


# ─────────────────────────────────────────────────────────────────────────────
# RAHAZA — multi-recipient helpers (read_by[], dedup, target filtering)
# ─────────────────────────────────────────────────────────────────────────────

async def rahaza_check_dedup(
    db, *, dedup_key: str, within_minutes: int = 10,
) -> Optional[dict]:
    """Check if an active rahaza notif with same dedup_key was created recently."""
    from datetime import timedelta
    if not dedup_key:
        return None
    since = _now() - timedelta(minutes=within_minutes)
    return await db.notifications.find_one({
        'type': 'rahaza',
        'meta.dedup_key': dedup_key,
        'meta.dismissed': {'$ne': True},
        'created_at': {'$gte': since},
    })


async def rahaza_mark_read_by(db, notif_id: str, user_id: str) -> int:
    """Add user_id to meta.read_by[] for a rahaza notif. Returns modified count."""
    res = await db.notifications.update_one(
        {'id': notif_id, 'type': 'rahaza'},
        {'$addToSet': {'meta.read_by': user_id}},
    )
    return res.modified_count


async def rahaza_mark_read_by_many(
    db, notif_ids: List[str], user_id: str,
) -> int:
    """Mark a batch of rahaza notifs as read by user."""
    if not notif_ids:
        return 0
    res = await db.notifications.update_many(
        {'id': {'$in': notif_ids}, 'type': 'rahaza'},
        {'$addToSet': {'meta.read_by': user_id}},
    )
    return res.modified_count


def rahaza_matches_user(notif: dict, user: dict) -> bool:
    """Return True if a rahaza notif (SSOT shape) is visible to user.

    2026-08-07: memakai aturan audiens tunggal (`notif_visible_to`). Dokumen
    tanpa target TIDAK lagi tampil ke semua role — hanya admin/owner.
    """
    return notif_visible_to(notif, user)
