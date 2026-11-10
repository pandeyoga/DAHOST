"""middleware.module_permission_gate — penegakan izin granular per modul.

Satu gerbang untuk semua endpoint yang prefix-nya terdaftar di `data/module_catalog.py`:
  method + kata kunci path -> aksi (view/create/edit/delete/approve/export) -> `mod.<modul>.<aksi>`.

Model "fallback aman" (per portal): gerbang hanya aktif bila peran/pengguna sudah diberi
minimal satu izin `mod.*` pada portal modul tersebut. Super role (superadmin/admin/owner),
izin "*", peran eksternal (punya penjaga portal sendiri), dan endpoint swalayan Portal Saya
(`module_catalog.SELF_SERVICE`) selalu dilewati.
"""
from __future__ import annotations

import json
import logging

from auth import _load_live_user, _load_portals, _load_rbac, verify_download_token, verify_token_str
from core.authz import EXTERNAL_ROLES
from data.module_catalog import (
    ACTION_LABELS, PORTAL_LABELS, detect_action, granular_portals, is_self_service, match_module, perm_key,
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
    """Return (module, action, reason) bila DITOLAK, else None."""
    mod = match_module(path)
    if not mod or not payload:
        return None
    # Swalayan Portal Saya (absen, cuti, lembur, kasbon, slip sendiri): kepemilikan dijaga handler.
    if is_self_service(method, path):
        return None
    live = await _load_live_user(payload.get("id"))
    role = ((live or {}).get("role") or payload.get("role") or "").lower()
    if role in SUPER_ROLES or role in EXTERNAL_ROLES:
        return None
    role_perms, extra = await _load_rbac(role, payload.get("id"))
    perms = set(role_perms) | set(extra)
    if "*" in perms:
        return None
    action = detect_action(method, path, mod)
    if action == "view" and mod["lookup"]:
        return None
    # 1) Akses PORTAL (khusus aksi tulis/approve/export; baca lintas-portal tetap untuk layar pintasan):
    #    bila owner sudah mengatur daftar portal peran, modul di portal yang tidak dicentang ditolak.
    configured = await _load_portals(role, payload.get("id")) if action != "view" else None
    if configured:
        from routes.shared import PORTAL_ACCESS
        allowed = set(configured) | {p for p, roles in PORTAL_ACCESS.items() if role in roles}
        allowed |= granular_portals(perms)
        if not ({mod["portal"], *mod["also_portals"]} & allowed):
            return mod, action, "portal"
    # 2) Izin granular per modul (aktif per portal setelah owner mencentang izin mod.*).
    if mod["portal"] not in granular_portals(perms):
        return None
    if perm_key(mod["id"], action) in perms:
        return None
    return mod, action, "perm"


def _catat_aktivitas(scope, payload: dict, status: int) -> None:
    """Monitoring Staf (10 Nov 2026, Tahap 1): satu catatan aktivitas per permintaan yang lolos — di latar,
    sesudah respons. Pemetaan modul+aksi SAMA dengan gerbang ini (satu katalog), aturan catat di `core.pantau_staf.meter`."""
    try:
        from core.pantau_staf import meter
        method, path = scope.get("method", "GET"), scope.get("path", "")
        mod = match_module(path)
        action = detect_action(method, path, mod) if mod else None
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
        if reason == "portal":
            detail = (f"Akses ditolak: peran Anda tidak diberi akses Portal {portal_label} "
                      f"(modul '{mod['label']}'). Hubungi admin untuk mencentang portal ini di Peran & Hak Akses.")
        else:
            detail = (f"Akses ditolak: peran Anda tidak punya izin '{ACTION_LABELS[action]}' pada modul "
                      f"'{mod['label']}' (Portal {portal_label}). "
                      f"Hubungi admin untuk menambahkan izin {perm_key(mod['id'], action)}.")
        body = json.dumps({"detail": detail, "code": "RBAC_PORTAL_DENIED" if reason == "portal" else "RBAC_MODULE_DENIED",
                           "module": mod["id"], "action": action}).encode()
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"), (b"x-rbac-denied", b"1"),
            (b"access-control-expose-headers", b"x-rbac-denied")]})
        await send({"type": "http.response.body", "body": body})
