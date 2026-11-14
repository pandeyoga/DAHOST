"""core.authz — gerbang peran level router (T-01, FASE 2.2).

`deny_roles(...)`  : dependency; peran yang disebut → 403 (peran dari JWT). Peran portal marketing lolos untuk
                    modul yang portalnya diberikan owner (12 Nov 2026, `_portal_diberikan_owner`).
`require_roles(...)`: dependency; hanya peran yang disebut (+ superadmin/admin) yang lolos.

Dipasang di `server.py` lewat `dependencies=[...]` pada `include_router` supaya satu perubahan
menutup lintas-portal (vendor/klien/buyer menembak endpoint internal) untuk ratusan endpoint.
"""
import re

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request

import auth as _auth
from auth import verify_download_token, verify_token

# Peran EKSTERNAL: bukan karyawan DA. Boleh masuk hanya ke portal masing-masing.
EXTERNAL_ROLES = ("vendor", "cmt_vendor", "buyer", "klien_maklon")
# Peran portal marketing (karyawan): tidak boleh menyentuh domain keuangan/produksi/gudang/R&D/admin.
MARKETING_PORTAL_ROLES = ("pic_toko", "marketing_kol", "cs_staff")


def _payload_of(request: Request) -> dict:
    payload = verify_token(request)
    if not payload:
        # FASE 4 (T-22): unduhan window.open/<a href>/<img> tidak bisa mengirim header —
        # token unduh (aud=download) datang lewat query `token`/`auth`.
        qp = request.query_params
        payload = verify_download_token(qp.get("token") or qp.get("auth") or "")
    if not payload:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return payload


def _role_of(request: Request) -> str:
    return (_payload_of(request).get("role") or "").lower()


async def _portal_diberikan_owner(payload: dict, role: str, path: str) -> bool:
    """Peran portal marketing boleh memakai modul internal yang portalnya DIBERIKAN owner (12 Nov 2026).

    Keputusan owner 10 Nov: portal yang dicentang di Manajemen Role = final. Larangan tetap untuk
    pic_toko/marketing_kol/cs_staff tetap berlaku, KECUALI untuk modul (katalog `data/module_catalog`) yang
    portal pemiliknya — atau portal pintasannya — diberikan owner secara eksplisit: dicentang di peran,
    ditambahkan per orang, atau lewat izin Lihat per modul. Bawaan kode (`PORTAL_ACCESS`) tidak dihitung,
    dan path di luar katalog tetap ditolak. Penjaga berikutnya (gerbang modul, izin aksi) tetap berjalan.
    """
    from data.module_catalog import match_module, view_portals
    mod = match_module(path)
    if not mod:
        return False
    uid = payload.get("id")
    if not uid:
        return False
    live = await _auth._load_live_user(uid)
    if live is None or live.get("blocked"):
        return False
    role = str(live.get("role") or role).lower()
    if role not in MARKETING_PORTAL_ROLES:
        return False  # peran sudah diganti: penjaga lain (require_auth dsb.) yang memutuskan
    role_portals, extra_portals = await _auth._load_portal_config(role, uid)
    role_perms, extra_perms = await _auth._load_rbac(role, uid)
    from routes.shared import ALL_ROLE_PORTALS
    granted = (set(role_portals) | set(extra_portals) | view_portals(set(role_perms) | set(extra_perms))) \
        - set(ALL_ROLE_PORTALS)
    return bool({mod["portal"], *mod["also_portals"]} & granted)


# 2026-11-04 — portal EKSTERNAL ber-token sendiri (Kreator `aud=creator-portal`, Livehost
# `aud=livehost-portal`). Rutenya menjaga dirinya sendiri (`require_creator_auth` /
# `require_livehost_auth`). Dulu gerbang router ini hanya mengenal JWT karyawan, jadi SEMUA
# panggilan portal — termasuk login — dijawab 401 "Unauthorized" dan kedua portal mati.
PORTAL_PATH_PREFIXES = ("/api/marketing/creator-portal/", "/api/marketing/livehost/portal/")
# Rute campuran: dipakai staf (JWT karyawan, tetap digerbang) DAN portal Livehost (token portal).
PORTAL_SHARED_ROUTES = {
    re.compile(r"^/api/marketing/livehost/shifts/[^/]+/performance$"): "livehost-portal",
}


def _is_portal_path(path: str) -> bool:
    return any(path.startswith(p) for p in PORTAL_PATH_PREFIXES)


def _portal_token_ok(request: Request, audience: str) -> bool:
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer ") or not _auth.JWT_SECRET:
        return False
    try:
        pyjwt.decode(h.split(" ", 1)[1], _auth.JWT_SECRET, algorithms=["HS256"], audience=audience)
        return True
    except pyjwt.PyJWTError:
        return False


def deny_roles(*roles: str):
    denied = {r.lower() for r in roles}

    async def _dep(request: Request):
        path = getattr(getattr(request, 'url', None), 'path', '') or ''
        if _is_portal_path(path):
            return
        aud = next((a for rx, a in PORTAL_SHARED_ROUTES.items() if rx.match(path)), None)
        if aud and _portal_token_ok(request, aud):
            return
        payload = _payload_of(request)
        role = (payload.get("role") or "").lower()
        if role in denied:
            if role in MARKETING_PORTAL_ROLES and await _portal_diberikan_owner(payload, role, path):
                return
            raise HTTPException(
                403, f"Akses ditolak: peran '{role}' tidak berhak memakai modul ini "
                     f"(khusus staf internal). Gunakan portal Anda sendiri.")
    _dep.__name__ = f"deny_roles[{','.join(sorted(denied))}]"
    return _dep


def require_roles(*roles: str, perm=None):
    """Kode peran (dari JWT, tanpa query DB) ATAU — bila `perm` diisi — izin peran yang dibaca LIVE.

    2026-11-08: peran buatan owner ("HR Generalist", "Koordinator Packing", …) tidak ada di daftar kode
    peran. `perm` (satu kunci atau tuple, salah satu cukup) = izin yang mengatur area endpoint itu; aturannya
    sama dengan `auth.check_role` (superadmin, kode peran di daftar, izin "*", atau izin yang diminta).
    13 Nov 2026: centang owner untuk aksi endpoint (katalog) juga meloloskan (`routes.shared.lolos_centang`).
    """
    allowed = {r.lower() for r in roles} | {"superadmin", "admin"}
    keys = (perm,) if isinstance(perm, str) else tuple(perm or ())

    async def _dep(request: Request):
        role = _role_of(request)
        if role in allowed:
            return
        from data.module_catalog import request_key
        try:
            kunci_aksi = request_key(request.method, request.url.path)
        except AttributeError:  # request palsu tanpa method/url
            kunci_aksi = None
        user = None
        if keys or kunci_aksi:  # tanpa izin & di luar katalog: cukup kode peran (tanpa query DB, seperti dulu)
            try:
                user = await _auth.require_auth(request)
            except HTTPException:
                user = None
        if user and keys and _auth.check_role(user, sorted(allowed), keys):
            return
        # 13 Nov 2026: centang owner untuk aksi endpoint ini (katalog) juga meloloskan — daftar peran di kode tidak
        # boleh mengalahkan centang (routes.shared.lolos_centang).
        from routes.shared import lolos_centang
        if user and lolos_centang(user):
            return
        raise HTTPException(403, "Akses ditolak: peran Anda belum dicentang untuk aksi ini. Minta owner mencentangnya di "
                                 "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses.")
    _dep.__name__ = f"require_roles[{','.join(sorted(allowed))}{'|' + ','.join(keys) if keys else ''}]"
    return _dep


def only(*roles: str, perm=None) -> list:
    """Gerbang eksplisit per endpoint (FASE 2.3): `@router.delete(path, dependencies=only(*HR_ROLES))`.

    `perm=` (opsional): izin yang juga meloloskan peran buatan owner — lihat `require_roles`.
    """
    return [Depends(require_roles(*roles, perm=perm))]
