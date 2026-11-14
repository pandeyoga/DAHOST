"""middleware.marketing_scope_guard — JARING PENGAMAN LINGKUP TOKO (F6.6).

MASALAH YANG DITUTUP (diukur, bukan dugaan)
-------------------------------------------
`core/marketing_account_scope.py` sudah menyediakan aturan "siapa boleh melihat
toko yang mana" sejak F6, tetapi pada awal sesi #9 hanya **7 dari 54** berkas
`routes/marketing_*.py` yang benar-benar memanggilnya. Artinya staf yang hanya
memegang satu toko masih bisa membuka angka toko rekan kerjanya hanya dengan
menukar `account_id` di URL — omzet, biaya iklan, komplain, sesi live, bahkan
menulis rekap harian toko orang lain. Tidak ada satu pun galat yang muncul.

Menambal 54 berkas satu per satu bisa (dan tetap dikerjakan untuk endpoint
DAFTAR yang tidak menyebut toko), tetapi tambalan per berkas punya kelemahan
mendasar: **berkas ke-55 tidak akan tahu aturan ini**. Middleware ini menutup
kelas masalahnya di satu tempat:

    Tidak ada endpoint `/api/marketing/*` yang boleh melayani permintaan yang
    MENYEBUT toko di luar lingkup pemakai — dari path, query, atau body.

BATAS YANG JUJUR (jangan salah paham)
-------------------------------------
* Ini **jaring pengaman**, bukan pengganti `scope_filter`. Endpoint yang TIDAK
  menyebut toko (mis. daftar "semua toko") tetap harus menyaring sendiri di
  route-nya — middleware tidak tahu apa isi jawabannya.
* Hanya dijalankan untuk pemakai berperan **berlingkup toko**
  (`SCOPED_ROLES`); admin/SPV/manager (dan token tak sah, yang akan ditolak
  route-nya sendiri dengan 401) dilewati tanpa biaya query.
* `account_id` yang tidak dikenal DB (mis. teks ngawur) tidak dijadikan 403 di
  sini — biarkan route-nya membalas 404 dengan pesannya sendiri. Yang ditolak
  hanyalah toko yang ADA tetapi bukan tanggung jawab pemakai (itu IDOR).
* Body JSON dibaca lalu **ditanam ulang** (`request._body`) supaya route tetap
  bisa membacanya. Body non-JSON (unggahan berkas/multipart) DILEWATI: ukurannya
  bisa besar dan `account_id`-nya sudah dijaga route impor.

PERLUASAN 14 NOV 2026 (owner: "penerapan filtering berdasarkan toko di marketing belum sepenuhnya")
-------------------------------------------------------------------------------------------------
* Peran dibaca TERKINI dari DB lalu dinormalkan lewat `marketing_account_scope._role()` — dulu
  `role.lower()` sehingga peran buatan owner bernama "PIC Toko" / "Host Live" lolos tanpa penjagaan.
  Izin pemakai (`marketing.report.view_all`, `*`) ikut dihitung, sama dengan handler.
* Rute `/api/v1/marketing/*` (alias yang diterjemahkan middleware v1 SESUDAH penjaga ini) dinilai
  memakai path terjemahannya — dulu alias itu melewati penjaga.
* `/api/dewi/kreator-requests/*` ikut dijaga.
* **Rekaman per id**: pola rute yang cocok dinilai lewat SATU tabel `core.marketing_record_scope.ATURAN`
  (pesanan, komplain, kreator, host, sesi live, tugas, katalog, …). Rekaman toko lain → 404.
* id kreator/host di body (`creator_id`, `kreator_id`, `host_id`, `host_ids`) ikut diperiksa.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional, Set

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

PREFIX = "/api/marketing/"
# Path yang TIDAK boleh dijaga di sini karena memang bertugas mengubah kewenangan
# atau membaca daftar toko untuk pemilihan; route-nya punya penjaga peran sendiri.
SKIP_SUFFIXES = ("/account-assign/candidates", "/account-assign/overview")
MAX_BODY_BYTES = 512_000       # body lebih besar dari ini dilewati (bukan JSON kecil)


def _ids_from_path(path: str) -> Set[str]:
    """Ambil id sesudah segmen `/accounts/` (pola `/accounts/{id}/...`)."""
    out: Set[str] = set()
    parts = [p for p in path.split("/") if p]
    for i, p in enumerate(parts):
        if p == "accounts" and i + 1 < len(parts):
            cand = parts[i + 1]
            # hanya bentuk yang MUNGKIN id (uuid/kode), bukan sub-path kata biasa
            if len(cand) >= 8 and cand not in ("health", "options", "review", "bulk"):
                out.add(cand)
    return out


def _path_kanonik(path: str) -> str:
    """`/api/v1/marketing/x` → `/api/marketing/x` (aturan yang SAMA dengan middleware v1)."""
    try:
        from middleware.api_v1 import rewrite_v1_path
        return rewrite_v1_path(path)
    except Exception:  # noqa: BLE001
        return path


async def pemakai_berlingkup(request) -> Optional[dict]:
    """Pemakai token ini bila ia BERLINGKUP toko (peran & izin terkini); None = tidak perlu dijaga.

    Token tak sah / akun tak dikenal / akun diblokir → None: route-nya sendiri yang menjawab 401.
    """
    import auth
    from core import marketing_account_scope as scope
    jwt_user = auth.verify_token(request)
    if not jwt_user or not jwt_user.get("id"):
        return None
    live = await auth._load_live_user(jwt_user.get("id"))
    if live is None or live.get("blocked"):
        return None
    role = live.get("role") or jwt_user.get("role") or ""
    user = {**jwt_user, "role": role}
    if scope._role(user) not in scope.SCOPED_ROLES:
        return None                                   # lihat semua toko / bukan peran marketing toko
    user["_permissions"] = await auth.compute_permissions(role, user["id"])
    if scope.sees_all_accounts(user):
        return None                                   # mis. izin marketing.report.view_all
    return user


def _jawab(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail, "status": status, "scope_guard": True}, status_code=status)


class MarketingScopeGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        from core import marketing_record_scope as rekaman
        path = _path_kanonik(request.url.path)
        if not rekaman.dijaga(path) or any(path.endswith(s) for s in SKIP_SUFFIXES):
            return await call_next(request)

        # ── 1. hanya pemakai berlingkup toko yang perlu dijaga ────────────────
        try:
            user = await pemakai_berlingkup(request)
        except Exception as exc:                          # noqa: BLE001
            logger.warning("[scope-guard] gagal menilai pemakai: %s", exc)
            return await call_next(request)
        if user is None:
            return await call_next(request)

        # ── 2. kumpulkan toko yang DISEBUT permintaan ────────────────────────
        named: Set[str] = set(_ids_from_path(path))
        qp = request.query_params
        for key in ("account_id", "account", "toko_id"):
            v = qp.get(key)
            if v:
                named.add(v)
        multi = qp.get("accounts") or qp.get("account_ids")
        if multi:
            named.update(x.strip() for x in multi.split(",") if x.strip())

        data = None
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            ctype = (request.headers.get("content-type") or "").lower()
            try:
                clen = int(request.headers.get("content-length") or 0)
            except ValueError:
                clen = 0
            if "application/json" in ctype and 0 < clen <= MAX_BODY_BYTES:
                try:
                    raw = await request.body()
                    request._body = raw                   # tanam ulang untuk route
                    data = json.loads(raw or b"{}")
                    if isinstance(data, dict):
                        for key in ("account_id", "toko_id"):
                            if data.get(key):
                                named.add(str(data[key]))
                        for key in ("account_ids", "accounts"):
                            v = data.get(key)
                            if isinstance(v, list):
                                named.update(str(x) for x in v if x)
                except Exception:                         # noqa: BLE001
                    data = None                           # body aneh = urusan route

        try:
            from core import marketing_account_scope as scope
            from database import get_db
            db = get_db()
            visible: List[str] | None = await scope.visible_account_ids(db, user)
            if visible is None:
                return await call_next(request)

            # ── 3. tolak toko yang ADA tetapi bukan lingkup pemakai ──────────
            unknown = [a for a in named if a not in visible]
            if unknown:
                exists = await db[scope.ACCOUNTS].find(
                    {"id": {"$in": unknown}}, {"_id": 0, "id": 1, "account_name": 1}
                ).to_list(20)
                if exists:
                    names = ", ".join(e.get("account_name") or e["id"] for e in exists)
                    logger.info("[scope-guard] TOLAK %s %s untuk %s (toko: %s)",
                                request.method, path, user.get("email"), names)
                    return _jawab(403, f"Toko berikut tidak di-assign ke Anda, jadi datanya "
                                       f"tidak bisa dibuka atau diubah: {names}. " + scope.NO_ACCOUNT_HINT)

            # ── 4. rekaman yang disebut di path: tabel `marketing_record_scope.ATURAN` ──
            hit = rekaman.cocokkan_rute(request.scope.get("app"), path, request.method)
            if hit:
                tolak = await rekaman.periksa_rute(db, visible, request.method, hit[0], hit[1])
                if tolak:
                    logger.info("[scope-guard] TOLAK rekaman %s %s untuk %s (%s)",
                                request.method, path, user.get("email"), tolak.status)
                    return _jawab(tolak.status, tolak.detail)

            # ── 5. kreator/host yang dirujuk body ────────────────────────────
            tolak = await rekaman.periksa_rujukan(db, visible, data, path)
            if tolak:
                return _jawab(tolak.status, tolak.detail)
        except Exception as exc:                          # noqa: BLE001
            # GAGAL-TERBUKA disengaja: jaring pengaman tidak boleh mematikan
            # aplikasi kalau DB sedang bermasalah — tetapi kegagalannya DICATAT,
            # tidak senyap (route tetap punya penjaganya sendiri).
            logger.warning("[scope-guard] gagal memeriksa lingkup (fail-open): %s", exc)
        return await call_next(request)
