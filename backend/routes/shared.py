"""
Shared utilities for all route modules.
Common helpers, constants, and imports.
"""
import uuid
from datetime import datetime, timezone
from fastapi import Request  # untuk anotasi dependency require_portal_dep

# Valid PO statuses (staged lifecycle)
PO_STATUSES = [
    "Draft", "Confirmed", "Distributed", "In Production", 
    "Production Complete", "Variance Review", "Return Review",
    "Ready to Close", "Closed"
]

def new_id():
    return str(uuid.uuid4())

def now():
    return datetime.now(timezone.utc)

def parse_date(d):
    if not d:
        return None
    if isinstance(d, datetime):
        return d
    try:
        return datetime.fromisoformat(str(d).replace('Z', '+00:00'))
    except Exception:
        return None

def to_end_of_day(d):
    if isinstance(d, str):
        d = parse_date(d)
    if d:
        return d.replace(hour=23, minute=59, second=59, microsecond=999999)
    return None

async def enrich_with_product_photos(items, db):
    """Add product photo_url to items that have a product_name. Single batch query."""
    if not items:
        return items
    pnames = list({(it.get('product_name') or '').strip() for it in items if it.get('product_name')})
    photos = {}
    if pnames:
        async for prod in db.products.find(
            {'product_name': {'$in': pnames}}, {'_id': 0, 'product_name': 1, 'photo_url': 1}
        ):
            photos[prod['product_name']] = prod.get('photo_url', '')
    for item in items:
        pname = item.get('product_name', '')
        if pname:
            item['product_photo'] = photos.get(pname, '')
    return items

def _fmt_date(v):
    if not v:
        return '-'
    s = str(v)[:10]
    return s if s != 'None' else '-'

def _fmt_num(v):
    try:
        return f"{int(v):,}".replace(',', '.')
    except (ValueError, TypeError):
        return str(v or 0)

def _fmt_money(v):
    try:
        return f"Rp {int(v):,}".replace(',', '.')
    except (ValueError, TypeError):
        return 'Rp 0'


# ═══════════════════════════════════════════════════════════════════════════════
# PAGINATION HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def get_pagination_params(request, default_limit=50, max_limit=200):
    """Extract pagination parameters from query string."""
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        limit = min(max_limit, max(1, int(request.query_params.get("limit", default_limit))))
    except (ValueError, TypeError):
        page = 1
        limit = default_limit
    skip = (page - 1) * limit
    return page, limit, skip

def paginated_response(items, total, page, limit):
    """Create a standard paginated response."""
    total_pages = max(1, -(-total // limit))  # Ceiling division
    return {
        "items": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PORTAL RBAC HELPER
# ═══════════════════════════════════════════════════════════════════════════════

SUPER_ROLES = ("superadmin", "admin", "owner")
ALL_ROLE_PORTALS = ("self", "collaboration")

# Role → portal access (kept in sync with frontend portalAccess.js).
# Portal ids match portalNav.js keys. SUPER_ROLES get every portal.
PORTAL_ACCESS = {
    "management":     ["hr_manager", "manager_produksi", "manager_keuangan", "manager_hr", "manager_marketing"],
    "sysadmin":       [],   # super_admin + admin saja
    # 2026-08-08 — `ppic` DITAMBAHKAN. Owner memutuskan PPIC termasuk staf yang
    # berhak memakai pintu "Input Vendor CMT" (Portal CMT Override), tetapi PPIC
    # sama sekali TIDAK punya akses Portal Produksi/Maklon sehingga pintunya
    # tidak mungkin dijangkau — izin fitur ada, jalannya tidak. Cermin FE:
    # frontend/src/components/erp/portalAccess.js
    "production":     ["supervisor_produksi", "admin_produksi", "ppic", "operator", "spv_cuting", "operator_cuting", "supervisor"],
    "cutting":        ["spv_cuting", "operator_cuting", "supervisor_produksi", "admin_produksi", "admin_gudang"],
    # 2026-08-06 — Portal Pengadaan (procurement dilepas dari Gudang/Keuangan/
    # Aksesoris). Daftar peran SAMA dengan `_require_procurement` di
    # routes/procurement_suppliers.py + cermin FE portalAccess.js.
    # 2026-08-06 — `admin_aksesoris`/`spv_aksesoris` WAJIB ada: pintu "Request
    # Aksesoris" (pembelian) dipindah ke portal ini dan DIHAPUS dari Portal
    # Aksesoris, jadi tanpa mereka fitur itu hilang total bagi divisi aksesoris.
    # 2026-08-07 — APPROVER PR WAJIB BISA MASUK PORTAL INI. Temuan nyata: peran
    # yang berhak menyetujui PR (`supervisor_produksi`, `manager`, `dept_head`,
    # `manager_hr`, `manager_marketing`, `spv_packing`, `spv_cuting`) dan peran
    # tahap FINAL (`director`, `cfo`, `ceo`) tidak punya akses Portal Pengadaan,
    # sehingga mereka tidak bisa membuka layar "Permintaan Pengadaan" tempat
    # kotak persetujuan berada — rantai persetujuan mati sebelum dimulai.
    "procurement":    ["admin_pengadaan", "manager_pengadaan", "purchasing", "admin_gudang", "accounting", "staff_keuangan", "manager_keuangan", "manager_produksi", "supervisor", "admin_aksesoris", "spv_aksesoris",
                       "supervisor_produksi", "manager", "dept_head", "manager_hr", "manager_marketing", "spv_packing", "spv_cuting", "director", "cfo", "ceo"],
    "warehouse":      ["admin_gudang", "spv_packing", "tim_packing", "admin_aksesoris", "supervisor"],
    "accessories":    ["admin_aksesoris", "admin_gudang", "spv_aksesoris"],
    "finance":        ["accounting", "staff_keuangan", "manager_keuangan"],
    # 2026-09 — Portal Penjualan (penjualan langsung dari stok FG). Cermin FE portalAccess.js.
    "sales":          ["sales", "admin_sales", "accounting", "staff_keuangan", "manager_keuangan", "pic_toko", "cs_staff",
                       "manager_marketing", "admin_gudang"],
    "hr":             ["hr", "hr_manager", "staff_hr"],
    "maklon":         ["admin_maklon", "admin_produksi", "supervisor_produksi", "ppic", "accounting"],
    "toko":           ["pic_toko", "pic_marketing", "staff_marketing", "marketing_kol", "cs_staff", "manager_marketing"],
    "rnd":            ["rnd_staff", "manager_produksi", "supervisor_produksi"],
    "assets":         ["accounting", "manager_keuangan", "staff_keuangan", "admin_gudang"],
    "collaboration":  [],   # all roles
    "self":           [],   # all roles
}
def default_portals(role) -> list:
    """Portal BAWAAN kode untuk sebuah kode peran (`PORTAL_ACCESS`), tanpa Portal Saya/Kolaborasi.

    Hanya dipakai bila owner BELUM mencentang satu portal pun untuk peran itu (lihat
    :func:`effective_portals`). Layar Manajemen Role menampilkannya supaya owner tahu portal mana
    yang tidak lagi ikut terbuka begitu ia mengatur portalnya sendiri.
    """
    r = str(role or "").lower()
    return [pid for pid in PORTAL_ACCESS if pid not in ALL_ROLE_PORTALS and r in PORTAL_ACCESS[pid]]


def effective_portals(role, role_portals=None, extra_portals=None) -> list:
    """SATU aturan portal efektif (backend, gerbang modul, `/auth/me`; cermin FE `portalAccess.js`).

    10 Nov 2026 (keputusan owner): portal yang DICENTANG owner di Manajemen Role = FINAL.
      * peran super (superadmin/admin/owner) → semua portal;
      * peran yang daftar portalnya sudah diisi → hanya portal itu;
      * peran yang daftar portalnya masih kosong (belum pernah diatur) → bawaan `PORTAL_ACCESS`;
      * lalu ditambah portal per orang (`users.extra_portals`) serta Portal Saya & Kolaborasi (semua orang).
    Dulu (9 Nov, audit gudang G1) portal bawaan selalu DITAMBAHKAN ke centangan, sehingga portal bawaan
    tidak pernah bisa dimatikan (mis. Supervisor Cutting tetap melihat Portal Produksi).
    """
    r = str(role or "").lower()
    if r in SUPER_ROLES:
        return list(PORTAL_ACCESS.keys())
    base = {str(p) for p in (role_portals or []) if p} or set(default_portals(r))
    allowed = base | {str(p) for p in (extra_portals or []) if p} | set(ALL_ROLE_PORTALS)
    return [pid for pid in PORTAL_ACCESS if pid in allowed] + sorted(allowed - set(PORTAL_ACCESS))


def _portal_config(user) -> tuple[list, list]:
    """(portal peran, portal per orang) dari user yang sudah dimuat `require_auth`/`resolve_role_access`.

    Pemanggil lama yang hanya mengisi `_portals` dianggap mengisi portal peran (centangan = final).
    """
    if "_role_portals" in user:
        return list(user.get("_role_portals") or []), list(user.get("_extra_portals") or [])
    custom = user.get("_portals")
    return (list(custom) if isinstance(custom, list) else []), []


def check_portal_access(user, portal_id):
    """Apakah user boleh membuka portal `portal_id`? Aturan: :func:`effective_portals`."""
    role = (user.get("role", "") or "").lower()
    if role in SUPER_ROLES or portal_id in ALL_ROLE_PORTALS:
        return True
    return portal_id in effective_portals(role, *_portal_config(user))


def get_user_portals(user):
    """Daftar portal yang boleh dibuka user. Aturan: :func:`effective_portals`."""
    return effective_portals((user.get("role", "") or "").lower(), *_portal_config(user))


async def resolve_role_access(db, user: dict) -> dict:
    """Akses efektif user: portal + menu yang disembunyikan + izin aksi.

    Sumber (berlapis, tanpa duplikasi katalog):
      1. dokumen `roles` (field `portals`, `hidden_modules`) — diatur owner di
         Portal Administrasi Sistem → Manajemen Role.
      2. dokumen `users` (`extra_portals`, `hidden_modules`, `extra_permissions`)
         — kekecualian per orang.
      3. portal peran masih kosong → `PORTAL_ACCESS` bawaan di modul ini (:func:`effective_portals`).
    """
    role = (user.get("role") or "").lower()
    u = await db.users.find_one({"id": user.get("id")}, {"_id": 0, "extra_portals": 1,
                                                        "hidden_modules": 1,
                                                        "extra_permissions": 1,
                                                        "role_id": 1, "role": 1}) or {}
    if u.get("role"):
        role = str(u["role"]).lower()  # peran LIVE dari DB, bukan dari token
    from auth import resolve_role_doc
    role_doc = await resolve_role_doc(db, role, u.get("role_id"))
    role_portals = [str(p) for p in ((role_doc or {}).get("portals") or []) if p]
    extra_portals = [str(p) for p in (u.get("extra_portals") or []) if p]
    hidden = list((role_doc or {}).get("hidden_modules") or [])
    hidden += [m for m in (u.get("hidden_modules") or []) if m not in hidden]
    user["_role_portals"], user["_extra_portals"] = role_portals, extra_portals
    user["_portals"] = role_portals + [p for p in extra_portals if p not in role_portals]
    # Izin granular per modul: menu tanpa izin `view` ikut disembunyikan + peta aksi per menu.
    from data.module_catalog import menu_access, view_portals
    role_keys = []
    if role_doc and role_doc.get("id"):
        rows = await db.role_permissions.find({"role_id": role_doc["id"]}, {"_id": 0, "permission_key": 1}).to_list(5000)
        role_keys = [r.get("permission_key") for r in rows if r.get("permission_key")]
    all_keys = role_keys + list(u.get("extra_permissions") or [])
    perm_hidden, module_access = menu_access(all_keys, is_super=role in SUPER_ROLES)
    hidden += [m for m in perm_hidden if m not in hidden]
    # Portal yang diberi izin Lihat per modul ikut terbuka walau belum dicentang di "Akses Portal".
    eff_portals = sorted(set(get_user_portals({**user, "role": role}))
                         | (set() if role in SUPER_ROLES else view_portals(all_keys)))
    return {
        "role": role,
        "is_super": role in SUPER_ROLES,
        "portals": eff_portals,
        # "peran" = portal dicentang owner (final); "bawaan" = peran belum diatur, memakai PORTAL_ACCESS.
        "portal_source": "super" if role in SUPER_ROLES else ("peran" if role_portals else "bawaan"),
        "hidden_modules": [] if role in SUPER_ROLES else hidden,
        "module_access": module_access,
        "extra_permissions": list(u.get("extra_permissions") or []),
    }


async def user_has_portal(db, user: dict, portal_id: str) -> bool:
    """Apakah pengguna `user` (dokumen users: id + role) bisa membuka portal `portal_id`?

    2026-11-07 (Tahap 6, MK3): aturan yang SAMA dengan yang memberi portal saat login/`/auth/me`
    (`resolve_role_access`: peran super, `roles.portals`, `users.extra_portals`, izin Lihat per modul,
    lalu `PORTAL_ACCESS` bawaan) — bukan daftar peran tetap saja. Dipakai pemilih PIC toko.
    """
    if portal_id in ALL_ROLE_PORTALS:
        return True
    access = await resolve_role_access(db, {"id": (user or {}).get("id"), "role": (user or {}).get("role")})
    return portal_id in access["portals"]



# ─────────────────────────────────────────────────────────────────────────────
# RBAC read/write guard (SSOT: check_portal_access) — menutup BUG-RBAC-1.
# require_auth = autentikasi (login). require_portal = OTORISASI (akses portal).
# SUPER_ROLES otomatis lolos (via check_portal_access). Bypass izin eksplisit tetap
# dihormati (mis. "*", "<portal>.manage", "<portal>.view").
# ─────────────────────────────────────────────────────────────────────────────
async def require_portal(request, *portal_ids, allow_perms=()):
    """Tegakkan akses portal. Return user bila boleh, else HTTPException(403).

    portal_ids: satu atau lebih portal (lolos bila user punya akses SALAH SATU).
    """
    from fastapi import HTTPException  # lazy: hindari beban import saat modul dimuat
    from auth import require_auth       # lazy: hindari risiko circular import
    user = await require_auth(request)
    for pid in portal_ids:
        if check_portal_access(user, pid):
            return user
    perms = user.get("_permissions") or []
    if "*" in perms:
        return user
    # Izin granular `mod.*` pada portal tsb. = akses portal (diatur owner per modul).
    from data.module_catalog import granular_portals
    if set(portal_ids) & granular_portals(perms):
        return user
    wanted = set(allow_perms)
    for pid in portal_ids:
        wanted.update({f"{pid}.manage", f"{pid}.view"})
    if wanted & set(perms):
        return user
    raise HTTPException(403, f"Forbidden: butuh akses portal ({', '.join(portal_ids)}).")


def require_portal_dep(*portal_ids, allow_perms=()):
    """Factory dependency FastAPI untuk dipasang di APIRouter(dependencies=[...])
    ATAU per-endpoint (Depends). Menegakkan require_portal untuk SEMUA endpoint router."""
    async def _dep(request: Request):
        await require_portal(request, *portal_ids, allow_perms=allow_perms)
    return _dep


# ─────────────────────────────────────────────────────────────────────────────
# IZIN AKSI / APPROVAL (action-level RBAC) — SATU mesin untuk seluruh route.
#
# MODEL "FALLBACK AMAN" (keputusan owner 2026-08-06):
#   1. SUPER_ROLES atau izin "*"                 -> selalu lolos
#   2. role punya salah satu izin yang diminta   -> lolos
#   3. role BELUM dikonfigurasi izinnya (kosong) -> pakai daftar role legacy
#      (`legacy_roles`) supaya fitur lama TIDAK mati mendadak
#   4. selain itu                                -> 403
#
# Konsekuensi yang disengaja: begitu owner mencentang izin untuk sebuah role,
# daftar izin itulah yang berlaku (aturan legacy berhenti dipakai untuk role
# tersebut). UI Peran & Hak Akses memberi peringatan jelas soal ini.
# ─────────────────────────────────────────────────────────────────────────────
def user_permissions(user) -> set:
    """Izin efektif user: izin role + izin tambahan per orang."""
    perms = set(user.get("_permissions") or [])
    if not perms:
        perms = set(user.get("permissions") or [])
    perms |= set(user.get("_extra_permissions") or [])
    return {p for p in perms if p}


def perms_configured(user) -> bool:
    """True bila owner sudah mengatur izin untuk role user (bukan role kosong)."""
    if user.get("_role_perms") is not None:
        return bool(user.get("_role_perms"))
    # Fallback bila require_auth versi lama belum mengisi `_role_perms`.
    return bool(user.get("_permissions"))


def has_perm(user, *keys) -> bool:
    """Cek izin murni (tanpa fallback role legacy)."""
    role = (user.get("role") or "").lower()
    if role in SUPER_ROLES:
        return True
    perms = user_permissions(user)
    if "*" in perms:
        return True
    return bool(perms & {k for k in keys if k})


def lolos_centang(user) -> bool:
    """Penjaga di kode menghormati centang owner (13 Nov 2026, owner: "bisa semuanya, jangan setengah-setengah").

    True bila aksi endpoint yang sedang diproses (`user["_aksi_request"]`, dari katalog `module_catalog.resolve`,
    diisi `auth.require_auth`) DICENTANG untuk peran/pengguna ini — atau peran super. Dipakai penjaga yang
    melempar 403 di awal handler (peran tetap / izin lama), supaya centang tidak dikalahkan daftar di kode. Aturan
    pemisahan tugas (bukan pemohon sendiri, saldo, status dokumen) tetap dijaga handler masing-masing.
    """
    role = str(user.get("role") or "").lower()
    if role in SUPER_ROLES:
        return True
    key = user.get("_aksi_request")
    if not key:
        return False
    perms = user_permissions(user)
    # 14 Nov 2026: centang modul setara (module_catalog.MODUL_SETARA) juga meloloskan, mis. Master Produk RnD › varian.
    return key in perms or any(k in perms for k in user.get("_aksi_setara") or ())


def can_act(user, *keys, legacy_roles=(), legacy_any=False) -> bool:
    """Cek izin dengan fallback aman (lihat model di atas). Tidak melempar error.

    legacy_roles : daftar role lama yang tetap boleh SELAMA izin role belum diatur.
    legacy_any   : True bila endpoint ini dulunya terbuka untuk SEMUA user login
                   (mis. put-away gudang). Selama izin role belum diatur, perilaku
                   lama dipertahankan; begitu owner mengatur izin, gerbang aktif.
    """
    if has_perm(user, *keys):
        return True
    if perms_configured(user):
        return False
    if legacy_any:
        return True
    role = (user.get("role") or "").lower()
    return role in {str(r).lower() for r in legacy_roles}


def assert_can_act(user, *keys, portal=None, legacy_roles=(), legacy_any=False,
                   what="melakukan aksi ini"):
    """Gerbang keputusan (approve/reject/confirm) untuk handler ber-`Depends(require_auth)`.

    2026-08-07 — audit RBAC: puluhan endpoint keputusan hanya butuh "sudah login"
    sehingga staf mana pun bisa menyetujui dokumen orang lain. Helper ini memakai
    model aman `can_act`: admin/owner selalu lolos, dan selama izin sebuah role
    belum diatur owner, role lama tetap boleh (fitur tidak mati mendadak).
    """
    from fastapi import HTTPException  # lazy
    roles = tuple(legacy_roles) + (tuple(PORTAL_ACCESS.get(portal, ())) if portal else ())
    if not (can_act(user, *keys, legacy_roles=roles, legacy_any=legacy_any) or lolos_centang(user)):
        raise HTTPException(403, f"Akses ditolak: Anda tidak berhak {what}.")
    return user


async def require_perm(request, *keys, legacy_roles=(), legacy_any=False, message=None):
    """Gerbang aksi/approval. Return user bila boleh, else HTTPException(403)."""
    from fastapi import HTTPException  # lazy
    from auth import require_auth       # lazy: hindari circular import
    user = await require_auth(request)
    if can_act(user, *keys, legacy_roles=legacy_roles, legacy_any=legacy_any) or lolos_centang(user):
        return user
    label = ", ".join([k for k in keys if k]) or "izin khusus"
    raise HTTPException(403, message or f"Akses ditolak: butuh izin ({label}).")


def require_perm_dep(*keys, legacy_roles=(), legacy_any=False, message=None):
    """Factory dependency FastAPI untuk memasang require_perm di router/endpoint."""
    async def _dep(request: Request):
        return await require_perm(request, *keys, legacy_roles=legacy_roles,
                                  legacy_any=legacy_any, message=message)
    return _dep
