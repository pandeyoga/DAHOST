"""middleware.cv_readonly_guard — mode Gabungan (dua CV) hanya untuk DILIHAT (Tahap 8 fase 1) + akses CV per
pengguna (Tahap 8 fase 3, opsional).

Portal Keuangan mengirim pilihan CV lewat header ``X-CV`` (DA | SMU | ALL). Dengan ``ALL`` (Gabungan) laporan
menjumlah dua buku; menulis apa pun tidak boleh, karena tidak jelas buku mana yang dituju. Tombol tambah/ubah
di layar sudah dimatikan (``PageLayout``), tetapi tombol di baris tabel atau panggilan API langsung tetap bisa
lolos. Jaring pengaman ini menolak SEMUA permintaan tulis (POST/PUT/PATCH/DELETE) berlabel Gabungan ke rute
keuangan dengan 400 dan pesan Indonesia yang sama dengan backend (``core.entities.READONLY_ALL_MSG``).

Akses CV per pengguna: ``users.allowed_entities`` (kosong = kedua CV, bawaan). Untuk endpoint modul Portal
Keuangan (``data.module_catalog``) CV yang diminta (query ``entity`` → header ``X-CV`` → bawaan DA) harus termasuk
yang diizinkan; Gabungan hanya untuk pengguna yang boleh kedua CV. Ditolak 403 dengan pesan Indonesia.

Header tidak ada / DA / SMU dan pengguna tanpa batasan → dilewati tanpa biaya tambahan selain satu baca cache.
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.entities import ENTITY_HEADER, READONLY_ALL_MSG

log = logging.getLogger(__name__)

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
GUARDED_PREFIXES = ("/api/rahaza/", "/api/finance", "/api/company-settings", "/api/dewi/maklon/finance",
                    "/api/v1/rahaza/", "/api/v1/finance")
# Rute keuangan yang selalu diperiksa akses CV-nya walau modul katalognya milik portal lain (mis. faktur pemasok
# di katalog Pengadaan, pembayaran tagihan CMT di katalog Maklon) — semuanya dipakai layar Portal Keuangan.
CV_SCOPED_EXTRA = ("/api/rahaza/intercompany", "/api/rahaza/finance", "/api/rahaza/ap-invoices",
                   "/api/rahaza/ap-aging", "/api/dewi/maklon/finance", "/api/finance")
_ALL = ("ALL", "GABUNGAN", "SEMUA")


def is_blocked(method: str, path: str, header_cv: str | None, query_cv: str | None) -> bool:
    if (method or "").upper() not in WRITE_METHODS:
        return False
    cv = str(query_cv or header_cv or "").strip().upper()
    return cv in _ALL and (path or "").startswith(GUARDED_PREFIXES)


def is_cv_scoped(path: str) -> bool:
    """Endpoint yang tunduk pada akses CV per pengguna: modul Portal Keuangan + rute keuangan khusus CV."""
    p = path or ""
    if p.startswith(CV_SCOPED_EXTRA):
        return True
    try:
        from data.module_catalog import match_module
        mod = match_module(p)
    except Exception:  # noqa: BLE001 — katalog rusak tidak boleh menjatuhkan request
        return False
    return bool(mod) and mod.get("portal") == "finance"


async def cv_access_denial(scope, path: str, header_cv, query_cv, method: str = "GET"):
    """Pesan 403 bila pengguna dibatasi CV dan meminta CV lain; None bila boleh / bukan rute keuangan.
    Swalayan Portal Saya (kasbon, slip sendiri) tidak pernah dibatasi CV."""
    if not is_cv_scoped(path):
        return None
    from data.module_catalog import is_self_service
    if is_self_service(method, path):
        return None
    from middleware.module_permission_gate import _token_payload
    payload = _token_payload(scope)
    if not payload or not payload.get("id"):
        return None
    from auth import _load_live_user
    live = await _load_live_user(payload.get("id"))
    if not live or not live.get("allowed_entities"):
        return None
    from core.entities import allowed_of_user, cv_access_problem
    return cv_access_problem(allowed_of_user(live), query_cv or header_cv)


class CvReadOnlyGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        header_cv = request.headers.get(ENTITY_HEADER)
        query_cv = request.query_params.get("entity")
        if is_blocked(request.method, request.url.path, header_cv, query_cv):
            return JSONResponse({"detail": READONLY_ALL_MSG}, status_code=400)
        try:
            denied = await cv_access_denial(request.scope, request.url.path, header_cv, query_cv, request.method)
        except Exception:  # noqa: BLE001
            log.exception("[cv-guard] pemeriksaan akses CV gagal untuk %s", request.url.path)
            denied = None
        if denied:
            return JSONResponse({"detail": denied, "code": "CV_ACCESS_DENIED"}, status_code=403)
        return await call_next(request)

