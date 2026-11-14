"""middleware.module_permission_gate — penegakan izin granular per modul.

Satu gerbang untuk semua endpoint yang prefix-nya terdaftar di `data/module_catalog.py`:
  method + kata kunci path -> aksi (view/create/edit/delete/approve/export) -> `mod.<modul>.<aksi>`.

13 Nov 2026: gerbang aktif untuk SEMUA modul katalog (tanpa aturan lama per portal) — centang owner
satu-satunya penentu. Super role (superadmin/admin/owner),
izin "*", peran eksternal (punya penjaga portal sendiri), dan endpoint swalayan Portal Saya
(`module_catalog.SELF_SERVICE`) selalu dilewati.
"""
from __future__ import annotations

import json
import logging

from auth import _load_live_user, _load_portal_config, _load_rbac, verify_download_token, verify_token_str
from core.authz import EXTERNAL_ROLES
from data.module_catalog import (
    ACTION_LABELS, PORTAL_LABELS, is_self_service, modul_setara, putuskan, resolve,
)

logger = logging.getLogger(__name__)

SUPER_ROLES = {"superadmin", "admin", "owner"}


def _token_payload(scope) -> dict | None:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
    auth = headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return verify_token_str(auth.split(" ", 1)[1])
    qs = scope.get("query_string", b"").decode()
    for part in qs.split("&"):
        k, _, v = part.partition("=")
        if k in ("token", "auth") and v:
            return verify_download_token(v)
    return None


async def evaluate(method: str, path: str, payload: dict | None):
    """Return (module, action, reason) bila DITOLAK, else None.

    13 Nov 2026 (owner: "bisa semuanya, jangan setengah-setengah"): centang = SATU-SATUNYA penentu. Aturan lama
    "portal yang belum punya satu pun centang `mod.*` memakai aturan lama" dihapus — setiap modul wajib dicentang.
    Peran yang dulu memakai aturan lama sudah dicentangkan setara aksesnya lewat migrasi
    `2026_11_13_centang_akses_penuh`.
    """
    mod, action = resolve(method, path)
    if not mod or not payload:
        return None
    # Swalayan Portal Saya (absen, cuti, lembur, kasbon, slip sendiri): kepemilikan dijaga handler. Dicek sebelum
    # memuat pengguna supaya tidak ada baca DB (aturannya sendiri ada di `putuskan` / `is_self_service`).
    if is_self_service(method, path):
        return None
    live = await _load_live_user(payload.get("id"))
    role = ((live or {}).get("role") or payload.get("role") or "").lower()
    if role in SUPER_ROLES or role in EXTERNAL_ROLES:
        return None
    role_perms, extra = await _load_rbac(role, payload.get("id"))
    perms = set(role_perms) | set(extra)
    # Portal peran hanya dibutuhkan untuk aksi tulis/approve/export (baca lintas-portal tetap untuk layar pintasan).
    allowed = None
    if action != "view" and not (mod["lookup"] and action == "view") and "*" not in perms:
        role_portals, extra_portals = await _load_portal_config(role, payload.get("id"))
        if role_portals or extra_portals:
            from routes.shared import effective_portals
            allowed = set(effective_portals(role, role_portals, extra_portals))
    # 14 Nov 2026: keputusan = SATU fungsi inti tanpa DB (`module_catalog.putuskan`), sama dengan Pemeriksaan
    # otomatis di Kontrol Akses (core/cek_akses.py). Termasuk modul setara manual + layanan ikut-otomatis.
    return putuskan(method, path, perms, allowed)


def _catat_aktivitas(scope, payload: dict, status: int) -> None:
    """Monitoring Staf (10 Nov 2026, Tahap 1): satu catatan aktivitas per permintaan yang lolos — di latar,
    sesudah respons. Pemetaan modul+aksi SAMA dengan gerbang ini (satu katalog), aturan catat di `core.pantau_staf.meter`."""
    try:
        from core.pantau_staf import meter
        method, path = scope.get("method", "GET"), scope.get("path", "")
        mod, action = resolve(method, path)
        meter.catat_latar(user_id=payload.get("id"), role=payload.get("role"), method=method, status=status,
                          module=mod, action=action)
    except Exception:  # noqa: BLE001 — pencatatan tidak boleh mengganggu permintaan
        logger.debug("[module-gate] catat aktivitas gagal", exc_info=True)


class ModulePermissionGateMiddleware:
    def __init__(self, app):
        self.app = app

    async def _teruskan(self, scope, receive, send, payload):
        if not payload or not payload.get("id"):
            return await self.app(scope, receive, send)
        status = {"v": None}

        async def kirim(msg):
            if msg.get("type") == "http.response.start":
                status["v"] = msg.get("status")
            await send(msg)

        try:
            await self.app(scope, receive, kirim)
        finally:
            if status["v"] is not None:
                _catat_aktivitas(scope, payload, status["v"])

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        payload = None
        try:
            payload = _token_payload(scope)
            denied = await evaluate(scope.get("method", "GET"), scope["path"], payload)
        except Exception:  # noqa: BLE001 — gerbang tidak boleh menjatuhkan request
            logger.exception("[module-gate] evaluasi gagal untuk %s", scope.get("path"))
            denied = None
        if not denied:
            return await self._teruskan(scope, receive, send, payload)
        mod, action, reason = denied
        portal_label = PORTAL_LABELS.get(mod['portal'], mod['portal'])
        # 14 Nov 2026: pesan tanpa kunci program; sebut tempat centangnya (AGENTS.md aturan teks No.5).
        tempat = "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses"
        if reason == "portal":
            detail = (f"Akses ditolak: peran Anda tidak diberi akses Portal {portal_label} "
                      f"(modul '{mod['label']}'). Minta owner mencentang portal ini di {tempat}.")
        else:
            alts = modul_setara(scope.get("method", "GET"), scope["path"])
            pilihan = [f"'{mod['label']}' (Portal {portal_label})"] + [
                f"'{alt['label']}' (Portal {PORTAL_LABELS.get(alt['portal'], alt['portal'])})" for alt in alts[:2]]
            lain = " atau modul lain yang layarnya memakai layanan ini" if len(alts) > 2 else ""
            detail = (f"Akses ditolak: peran Anda tidak punya izin '{ACTION_LABELS[action]}' pada modul "
                      f"{' atau '.join(pilihan)}{lain}. Minta owner mencentang '{ACTION_LABELS[action]}' pada modul "
                      f"itu di {tempat}.")
        body = json.dumps({"detail": detail, "code": "RBAC_PORTAL_DENIED" if reason == "portal" else "RBAC_MODULE_DENIED",
                           "module": mod["id"], "action": action}).encode()
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"), (b"x-rbac-denied", b"1"),
            (b"access-control-expose-headers", b"x-rbac-denied")]})
        await send({"type": "http.response.body", "body": body})
