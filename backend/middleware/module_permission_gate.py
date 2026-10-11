"""middleware.module_permission_gate — penegakan izin granular per modul.

Satu gerbang untuk semua endpoint yang prefix-nya terdaftar di `data/module_catalog.py`:
  method + kata kunci path -> aksi (view/create/edit/delete/approve/export) -> `mod.<modul>.<aksi>`.

Model "fallback aman" (per portal): gerbang hanya aktif bila peran/pengguna sudah diberi
minimal satu izin `mod.*` pada portal modul tersebut. Super role (superadmin/admin/owner),
izin "*", dan peran eksternal (punya penjaga portal sendiri) selalu dilewati.
"""
from __future__ import annotations

import json
import logging

from auth import _load_rbac, verify_download_token, verify_token_str
from core.authz import EXTERNAL_ROLES
from data.module_catalog import (
    ACTION_LABELS, PORTAL_LABELS, detect_action, granular_portals, match_module, perm_key,
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
    """Return (module, action) bila DITOLAK, else None."""
    mod = match_module(path)
    if not mod or not payload:
        return None
    role = (payload.get("role") or "").lower()
    if role in SUPER_ROLES or role in EXTERNAL_ROLES:
        return None
    role_perms, extra = await _load_rbac(role, payload.get("id"))
    perms = set(role_perms) | set(extra)
    if "*" in perms or mod["portal"] not in granular_portals(perms):
        return None
    action = detect_action(method, path, mod)
    if action == "view" and mod["lookup"]:
        return None
    if perm_key(mod["id"], action) in perms:
        return None
    return mod, action


class ModulePermissionGateMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        try:
            denied = await evaluate(scope.get("method", "GET"), scope["path"], _token_payload(scope))
        except Exception:  # noqa: BLE001 — gerbang tidak boleh menjatuhkan request
            logger.exception("[module-gate] evaluasi gagal untuk %s", scope.get("path"))
            denied = None
        if not denied:
            return await self.app(scope, receive, send)
        mod, action = denied
        detail = (f"Akses ditolak: peran Anda tidak punya izin '{ACTION_LABELS[action]}' pada modul "
                  f"'{mod['label']}' (Portal {PORTAL_LABELS.get(mod['portal'], mod['portal'])}). "
                  f"Hubungi admin untuk menambahkan izin {perm_key(mod['id'], action)}.")
        body = json.dumps({"detail": detail, "code": "RBAC_MODULE_DENIED",
                           "module": mod["id"], "action": action}).encode()
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"), (b"x-rbac-denied", b"1"),
            (b"access-control-expose-headers", b"x-rbac-denied")]})
        await send({"type": "http.response.body", "body": body})
