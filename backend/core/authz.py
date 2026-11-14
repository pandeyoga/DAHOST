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
    perms = set(role_perms) | set(extra_perms)
    # 14 Nov 2026: centang apa pun pada modul ini (mis. Order Cutting › Tambah tanpa Lihat) = diberikan owner.
    if any(str(k).startswith(f"mod.{mod['id']}.") for k in perms):
        return True
    from routes.shared import ALL_ROLE_PORTALS
    granted = (set(role_portals) | set(extra_portals) | view_portals(perms)) - set(ALL_ROLE_PORTALS)
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
    """Gerbang endpoint: centang owner, lalu — hanya bila centang peran itu BELUM diatur — kode peran lama.

    2026-11-08: peran buatan owner ("HR Generalist", "Koordinator Packing", …) tidak ada di daftar kode
    peran. `perm` (satu kunci atau tuple, salah satu cukup) = izin yang mengatur area endpoint itu.
    13 Nov 2026: centang owner untuk aksi endpoint (katalog) juga meloloskan (`routes.shared.lolos_centang`).
    14 Nov 2026 (owner: "terakhir kalinya saya tidak ingin ada masalah lagi"): kode peran di daftar TIDAK lagi
    meloloskan peran yang centangnya sudah diatur owner (pola `routes.shared.can_act` legacy_roles) — dulu daftar
    di kode mengalahkan centang untuk endpoint di luar katalog modul. Peran super selalu boleh.
    """
    allowed = {r.lower() for r in roles} | {"superadmin", "admin", "owner"}   # peran super selalu boleh
    keys = (perm,) if isinstance(perm, str) else tuple(perm or ())

    async def _dep(request: Request):
        role = _role_of(request)
        if role in _SUPER:
            return
        try:
            user = await _auth.require_auth(request)
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 — basis data tidak terjangkau / request palsu: perilaku lama (kode peran JWT)
            user = None
        if user is None:
            if role in allowed:
                return
            raise HTTPException(403, pesan_centang(None, *keys))
        from routes.shared import can_act, lolos_centang
        if lolos_centang(user) or can_act(user, *keys, legacy_roles=sorted(allowed)):
            return
        raise HTTPException(403, pesan_centang(user, *keys))
    _dep.__name__ = f"require_roles[{','.join(sorted(allowed))}{'|' + ','.join(keys) if keys else ''}]"
    return _dep


_SUPER = ("superadmin", "admin", "owner")


# ─────────────────────────────────────────────────────────────────────────────
# 14 Nov 2026 (owner: "terakhir kalinya saya tidak ingin ada masalah lagi"): penjaga di dalam handler yang dulu
# berupa daftar kode peran memakai SATU pola: centang aksi endpoint (`routes.shared.lolos_centang`) ATAU kunci
# centang yang disebut (`can_act`; daftar peran lama hanya berlaku selama owner belum mengatur centang peran itu).
# ─────────────────────────────────────────────────────────────────────────────
TEMPAT_CENTANG = "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses"


def pesan_centang(user=None, *kunci, apa=None) -> str:
    """Pesan tolak untuk staf: aksi + modul yang perlu dicentang dan letak centangnya, tanpa kunci program.

    Modul & aksi diambil dari kunci `mod.<modul>.<aksi>` pertama di `kunci`, lalu dari aksi endpoint yang sedang
    diproses (`user["_aksi_request"]`). `apa` (mis. "menyetujui retur") dipakai bila tidak ada kunci katalog.
    """
    from data.module_catalog import ACTION_LABELS, MODULE_BY_ID, PORTAL_LABELS
    for k in (*kunci, (user or {}).get("_aksi_request")):
        parts = str(k or "").split(".")
        if len(parts) == 3 and parts[0] == "mod" and parts[1] in MODULE_BY_ID and parts[2] in ACTION_LABELS:
            mod = MODULE_BY_ID[parts[1]]
            portal = PORTAL_LABELS.get(mod["portal"], mod["portal"])
            return (f"Akses ditolak: peran Anda belum dicentang \"{ACTION_LABELS[parts[2]]}\" pada modul "
                    f"\"{mod['label']}\" (Portal {portal}). Minta owner mencentangnya di {TEMPAT_CENTANG}.")
    hal = f" untuk {apa}" if apa else " untuk aksi ini"
    return f"Akses ditolak: peran Anda belum dicentang{hal}. Minta owner mencentangnya di {TEMPAT_CENTANG}."


def boleh_centang(user, *kunci, peran_lama=(), legacy_any=False) -> bool:
    """True bila peran super, dicentang untuk aksi endpoint ini, atau memegang salah satu `kunci`.

    `peran_lama` = daftar kode peran yang dulu dipakai penjaga ini — hanya berlaku selama owner BELUM mengatur
    centang peran tersebut (pola `routes.shared.can_act`). Aturan bisnis (pemohon sendiri, status, saldo)
    tetap diperiksa pemanggil.
    """
    from routes.shared import can_act, lolos_centang
    user = user or {}
    return lolos_centang(user) or can_act(user, *kunci, legacy_roles=peran_lama, legacy_any=legacy_any)


def izin_atau_peran_lama(user, peran, izin=None) -> bool:
    """Pengganti `auth.check_role(user, peran, izin)` yang tidak mengalahkan centang owner.

    Izin (`izin`: satu kunci atau beberapa; kunci lama tersirat dari centang `mod.*`) memutuskan; kode peran di
    `peran` hanya berlaku selama owner belum mengatur centang peran itu. Tanpa kunci aksi endpoint — dipakai untuk
    hak lintas-aksi seperti "melihat data semua karyawan" (aturan bisnis yang ikut centang Setujui/Bayar).
    """
    from routes.shared import can_act
    keys = (izin,) if isinstance(izin, str) else tuple(izin or ())
    return can_act(user or {}, *keys, legacy_roles=tuple(peran or ()))


def wajib_centang(user, *kunci, peran_lama=(), apa=None):
    """`boleh_centang` atau HTTP 403 dengan :func:`pesan_centang`. Mengembalikan `user`."""
    if not boleh_centang(user, *kunci, peran_lama=peran_lama):
        raise HTTPException(403, pesan_centang(user, *kunci, apa=apa))
    return user


def only(*roles: str, perm=None) -> list:
    """Gerbang eksplisit per endpoint (FASE 2.3): `@router.delete(path, dependencies=only(*HR_ROLES))`.

    `perm=` (opsional): izin yang juga meloloskan peran buatan owner — lihat `require_roles`.
    """
    return [Depends(require_roles(*roles, perm=perm))]
