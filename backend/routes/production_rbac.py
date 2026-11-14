"""Shared RBAC + master-data resolution helpers for the ported SOMMERVILLE
production engine (Fase 2 adopsi — lihat /app/memory/SOMMERVILLE_ADOPTION_PLAN.md).

RBAC-1 = B (locked): SOMMERVILLE role strings are remapped to DA roles:
  admin  → admin, admin_maklon            (superadmin always bypasses via check_role)
  vendor → vendor, cmt_vendor             (identity via vendor_id ATAU cmt_vendor_id)
  buyer  → klien_maklon (read-only, HANYA lewat /api/maklon-client/*)

Master data resolution (F-2 = Option A, satu engine):
  vendor_id → `garments` (SOMMERVILLE master) ATAU `vendor_partners` (CMT vendor DA)
  buyer_id  → `buyers` (SOMMERVILLE master) ATAU `dewi_maklon_clients` (klien maklon DA)
"""
from fastapi import HTTPException, Request

PROD_ADMIN_ROLES = [
    'admin', 'admin_maklon', 'admin_produksi',
    'supervisor_produksi', 'owner', 'manager', 'ppic',
]
# Catatan: `superadmin` selalu bypass via check_role().
# Perluasan ini memperbaiki inkonsistensi: GET /production-pos terbuka utk semua user
# login, tetapi CREATE/UPDATE dulu hanya admin/admin_maklon → role manajemen produksi
# (owner/admin_produksi/supervisor_produksi) kena 403 "Forbidden" saat simpan PO.
PROD_VENDOR_ROLES = ['vendor', 'cmt_vendor']

# 2026-11-07 (Tahap 8, permintaan owner): "di Portal Produksi & Maklon hanya superadmin yang bisa membuat
# draf PO". Layar dulu memakai aturannya sendiri (`production_po.create` — kunci yang tidak ada di katalog —
# atau `po.create` = PO PEMBELIAN), server memakai PROD_ADMIN_ROLES. Sekarang SATU aturan untuk tombol dan
# server: peran bawaan di bawah ATAU izin granular yang dicentang owner di Peran & Hak Akses
# (`mod.prod_po.<aksi>` = "PO Produksi Internal", `mod.mak_po.<aksi>` = "PO Maklon & Detail PO" —
# kunci yang SUDAH ada di data/module_catalog.py, tidak dibuat kunci kedua).
# Hapus PO = hapus beruntun (job, kiriman, progres) → bawaannya tetap sempit: superadmin/admin/owner, peran
# lain hanya bila owner mencentang izin Hapus.
PO_ROLE_DEFAULTS = {
    'create': PROD_ADMIN_ROLES,
    'edit': PROD_ADMIN_ROLES,
    'delete': ['admin', 'owner'],
}
PO_ACTIONS = tuple(PO_ROLE_DEFAULTS)


def po_module_id(business_type) -> str:
    return 'mak_po' if (business_type or '') == 'maklon' else 'prod_po'


def po_perm_key(business_type, action: str) -> str:
    from data.module_catalog import perm_key
    return perm_key(po_module_id(business_type), action)


def can_po_action(user: dict, action: str, business_type) -> bool:
    """Boleh membuat/mengubah/menghapus PO jenis ini? Centang modulnya (`mod.prod_po.*` / `mod.mak_po.*`).

    14 Nov 2026: peran bawaan (`PO_ROLE_DEFAULTS`) hanya berlaku selama owner belum mengatur centang peran itu —
    dulu kode peran meloloskan walau owner tidak mencentang (centang kalah oleh daftar di kode).
    """
    from routes.shared import can_act
    return can_act(user, po_perm_key(business_type, action), legacy_roles=PO_ROLE_DEFAULTS[action])


def assert_po_action(user: dict, action: str, business_type) -> None:
    if not can_po_action(user, action, business_type):
        jenis = 'maklon' if (business_type or '') == 'maklon' else 'produksi internal'
        verb = {'create': 'membuat', 'edit': 'mengubah', 'delete': 'menghapus'}[action]
        # 14 Nov 2026: sebut kotak centang & letaknya, tanpa kunci izin program.
        from data.module_catalog import ACTION_LABELS, MODULE_BY_ID
        modul = MODULE_BY_ID[po_module_id(business_type)]['label']
        raise HTTPException(403, f"Akses ditolak: peran Anda tidak boleh {verb} PO {jenis}. Minta owner mencentang "
                                 f"\"{ACTION_LABELS[action]}\" pada modul \"{modul}\" di Administrasi Sistem › Kontrol "
                                 "Akses › Peran & Hak Akses.")


async def po_action_flags(user: dict, business_type) -> dict:
    """{can_create, can_edit, can_delete} untuk pengguna ini — aturan handler DAN gerbang modul
    (`middleware.module_permission_gate`, aktif bila portal peran sudah diatur granular)."""
    from middleware.module_permission_gate import evaluate
    payload = {'id': user.get('id'), 'role': user.get('role')}
    probes = {'create': ('POST', '/api/production-pos'), 'edit': ('PUT', '/api/production-pos/_'),
              'delete': ('DELETE', '/api/production-pos/_')}
    out = {}
    for action, (method, path) in probes.items():
        ok = can_po_action(user, action, business_type)
        if ok:
            try:
                ok = not await evaluate(method, path, payload)
            except Exception:  # noqa: BLE001 — gerbang gagal dievaluasi = jangan menyembunyikan tombol
                ok = True
        out[f'can_{action}'] = bool(ok)
    return out


def is_vendor(user: dict) -> bool:
    return (user.get('role') or '') in PROD_VENDOR_ROLES


def vendor_identity(user: dict):
    """Vendor entity id for the logged-in vendor user (SOMMERVILLE vendor_id
    or DA cmt_vendor_id → vendor_partners.id)."""
    return user.get('vendor_id') or user.get('cmt_vendor_id')


EXTERNAL_ROLES = ('klien_maklon', 'buyer') + tuple(PROD_VENDOR_ROLES)  # T-01: selaras core.authz.EXTERNAL_ROLES
# Vendor CMT masih boleh membaca daftar selisih kirim miliknya (endpoint sudah ter-scope vendor).
_VENDOR_ALLOWED_PATHS = ('/api/prod/short-shipments',)


async def deny_external_dep(request: Request):
    """Dependency router: klien maklon & vendor CMT TIDAK boleh menyentuh endpoint admin
    maklon (`/api/dewi/maklon/*`, `/api/prod/cmt-receipts*`, tagihan CMT). Klien memakai
    `/api/maklon-client/*`, vendor memakai engine yang ter-scope `vendor_id` (audit M-01/M-02)."""
    from auth import require_auth
    user = await require_auth(request)
    role = user.get('role') or ''
    if role in EXTERNAL_ROLES:
        if role in PROD_VENDOR_ROLES and request.method == 'GET' \
                and request.url.path.rstrip('/') in _VENDOR_ALLOWED_PATHS:
            return user
        raise HTTPException(403, 'Akses ditolak: endpoint ini khusus staf DA. Klien memakai '
                                 '/api/maklon-client/*, vendor CMT memakai portal vendor.')
    return user


def deny_klien(user: dict):
    """klien_maklon is read-only and may ONLY use /api/maklon-client/* endpoints."""
    if (user.get('role') or '') == 'klien_maklon':
        raise HTTPException(403, 'Akses klien maklon hanya melalui endpoint tracking (/api/maklon-client/*)')


def prod_admin_ok(user: dict) -> bool:
    """Penjaga staf produksi (dulu `check_role(user, PROD_ADMIN_ROLES)`): centang aksi endpoint ini, atau
    `PROD_ADMIN_ROLES` selama owner belum mengatur centang peran itu (14 Nov 2026: centang = penentu)."""
    from core.authz import boleh_centang
    return boleh_centang(user, peran_lama=PROD_ADMIN_ROLES)


def assert_prod_admin(user: dict, apa: str | None = None) -> dict:
    """:func:`prod_admin_ok` atau 403 yang menyebut centang yang dibutuhkan dan letaknya."""
    from core.authz import pesan_centang
    if not prod_admin_ok(user):
        raise HTTPException(403, pesan_centang(user, apa=apa))
    return user


def require_write_actor(user, check_role_fn=None):
    """Guard for endpoints that were open to any authenticated user in
    SOMMERVILLE (vendor OR admin submit paths). Staf DA: :func:`prod_admin_ok` (centang)."""
    if is_vendor(user):
        return
    assert_prod_admin(user)


async def resolve_vendor_doc(db, vendor_id):
    """Vendor master lookup: garments (SOMMERVILLE) → vendor_partners (DA CMT).
    Returns a doc that always carries `garment_name`/`garment_code` keys so the
    ported code keeps working unchanged."""
    if not vendor_id:
        return None
    doc = await db.garments.find_one({'id': vendor_id})
    if doc:
        return doc
    vp = await db.vendor_partners.find_one({'id': vendor_id})
    if vp:
        vp.setdefault('garment_name', vp.get('name', ''))
        vp.setdefault('garment_code', vp.get('code', ''))
        return vp
    return None


async def resolve_buyer_name(db, buyer_id, default=''):
    """Buyer/customer master lookup: buyers (SOMMERVILLE) → dewi_maklon_clients (DA)."""
    if not buyer_id:
        return default
    b = await db.buyers.find_one({'id': buyer_id})
    if b:
        return b.get('buyer_name', default)
    c = await db.dewi_maklon_clients.find_one({'id': buyer_id})
    if c:
        return c.get('name', default)
    return default
