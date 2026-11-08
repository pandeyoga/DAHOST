"""core.authz — gerbang peran level router (T-01, FASE 2.2).

`deny_roles(...)`  : dependency; peran yang disebut → 403 (tanpa query DB, baca peran dari JWT).
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


def _role_of(request: Request) -> str:
    payload = verify_token(request)
    if not payload:
        # FASE 4 (T-22): unduhan window.open/<a href>/<img> tidak bisa mengirim header —
        # token unduh (aud=download) datang lewat query `token`/`auth`.
        qp = request.query_params
        payload = verify_download_token(qp.get("token") or qp.get("auth") or "")
    if not payload:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return (payload.get("role") or "").lower()


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
        role = _role_of(request)
        if role in denied:
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
    Tanpa `perm` perilakunya persis seperti dulu.
    """
    allowed = {r.lower() for r in roles} | {"superadmin", "admin"}
    keys = (perm,) if isinstance(perm, str) else tuple(perm or ())

    async def _dep(request: Request):
        role = _role_of(request)
        if role in allowed:
            return
        if keys:
            try:
                user = await _auth.require_auth(request)
            except HTTPException:
                user = None
            if user and _auth.check_role(user, sorted(allowed), keys):
                return
        raise HTTPException(403, f"Akses ditolak: butuh peran {', '.join(sorted(roles))}.")
    _dep.__name__ = f"require_roles[{','.join(sorted(allowed))}{'|' + ','.join(keys) if keys else ''}]"
    return _dep


def only(*roles: str, perm=None) -> list:
    """Gerbang eksplisit per endpoint (FASE 2.3): `@router.delete(path, dependencies=only(*HR_ROLES))`.

    `perm=` (opsional): izin yang juga meloloskan peran buatan owner — lihat `require_roles`.
    """
    return [Depends(require_roles(*roles, perm=perm))]
