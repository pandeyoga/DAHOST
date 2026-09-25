"""core.authz — gerbang peran level router (T-01, FASE 2.2).

`deny_roles(...)`  : dependency; peran yang disebut → 403 (tanpa query DB, baca peran dari JWT).
`require_roles(...)`: dependency; hanya peran yang disebut (+ superadmin/admin) yang lolos.

Dipasang di `server.py` lewat `dependencies=[...]` pada `include_router` supaya satu perubahan
menutup lintas-portal (vendor/klien/buyer menembak endpoint internal) untuk ratusan endpoint.
"""
from fastapi import Depends, HTTPException, Request

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


def deny_roles(*roles: str):
    denied = {r.lower() for r in roles}

    async def _dep(request: Request):
        role = _role_of(request)
        if role in denied:
            raise HTTPException(
                403, f"Akses ditolak: peran '{role}' tidak berhak memakai modul ini "
                     f"(khusus staf internal). Gunakan portal Anda sendiri.")
    _dep.__name__ = f"deny_roles[{','.join(sorted(denied))}]"
    return _dep


def require_roles(*roles: str):
    allowed = {r.lower() for r in roles} | {"superadmin", "admin"}

    async def _dep(request: Request):
        role = _role_of(request)
        if role not in allowed:
            raise HTTPException(403, f"Akses ditolak: butuh peran {', '.join(sorted(roles))}.")
    _dep.__name__ = f"require_roles[{','.join(sorted(allowed))}]"
    return _dep


def only(*roles: str) -> list:
    """Gerbang eksplisit per endpoint (FASE 2.3): `@router.delete(path, dependencies=only(*HR_ROLES))`."""
    return [Depends(require_roles(*roles))]
