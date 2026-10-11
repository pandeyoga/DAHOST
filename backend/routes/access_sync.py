"""access_sync — audit & perbaikan sinkron akun <-> peran <-> hak akses (superadmin).

GET  /api/admin/access-sync/audit         : semua akun + masalah sinkron + akses efektif ringkas
POST /api/admin/access-sync/fix           : perbaiki tautan role/role_id (nama beda huruf, role_id basi)
GET  /api/admin/access-sync/user/{uid}    : akses efektif lengkap satu akun ("lihat sebagai")
"""
from fastapi import APIRouter, HTTPException, Request

from auth import FIXED_ROLE_PERMS, bump_rbac_cache, compute_permissions, require_auth, resolve_role_doc
from data.module_catalog import MODULE_BY_ID, PORTAL_LABELS, granular_portals
from database import get_db
from routes.shared import PORTAL_ACCESS, now, resolve_role_access

router = APIRouter(prefix="/api/admin/access-sync", tags=["access-sync"])

_USER_PROJ = {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1, "role_id": 1, "status": 1,
              "active": 1, "is_active": 1, "extra_permissions": 1, "extra_portals": 1, "hidden_modules": 1}


def _require_super(user):
    if user.get("role") != "superadmin":
        raise HTTPException(403, "Hanya superadmin.")


def _known_builtin(role: str) -> bool:
    return role in FIXED_ROLE_PERMS or any(role in rs for rs in PORTAL_ACCESS.values())


async def _diagnose(db, u: dict, roles_by_id: dict) -> dict:
    role = u.get("role") or ""
    issues = []
    doc = await resolve_role_doc(db, role, u.get("role_id"), {"_id": 0, "id": 1, "name": 1, "portals": 1})
    if u.get("role_id") and u["role_id"] not in roles_by_id:
        issues.append({"code": "role_id_dangling", "fixable": True,
                       "message": "role_id menunjuk peran yang sudah dihapus"})
    if u.get("role_id") in roles_by_id and roles_by_id[u["role_id"]] != role:
        issues.append({"code": "role_mismatch", "fixable": True, "severity": "info" if doc else None,
                       "message": f"role_id masih menunjuk '{roles_by_id[u['role_id']]}' (dipakai: '{role}')"})
    if doc and doc["name"] != role:
        issues.append({"code": "role_case", "fixable": True,
                       "message": f"Nama peran '{role}' beda huruf dengan '{doc['name']}'"})
    if not doc and not _known_builtin(role.lower()):
        issues.append({"code": "role_unknown", "fixable": False,
                       "message": f"Peran '{role}' tidak terdaftar — akun tidak punya hak akses apa pun"})
    if doc and not u.get("role_id"):
        issues.append({"code": "role_unlinked", "fixable": True, "severity": "info",
                       "message": "Akun belum tertaut role_id (dicocokkan lewat nama)"})
    blocked = u.get("is_active") is False or (u.get("status") not in (None, "active") and not u.get("active", True))
    perms = await compute_permissions(role, u["id"])
    acc = await resolve_role_access(db, {"id": u["id"], "role": role})
    return {
        "id": u["id"], "email": u.get("email"), "name": u.get("name"), "role": role,
        "role_id": u.get("role_id"), "role_doc": doc and doc["name"], "active": not blocked,
        "portals": acc["portals"], "hidden_count": len(acc["hidden_modules"]),
        "perm_count": len([p for p in perms if p != "*"]), "is_super": acc["is_super"] or "*" in perms,
        "granular_portals": sorted(granular_portals(perms)),
        "extra_permissions": len(u.get("extra_permissions") or []), "extra_portals": u.get("extra_portals") or [],
        "issues": issues,
        "status": "error" if any(i.get("severity") != "info" for i in issues) else "ok",
    }


@router.get("/audit")
async def audit(request: Request):
    _require_super(await require_auth(request))
    db = get_db()
    bump_rbac_cache()
    roles_by_id = {r["id"]: r["name"] async for r in db.roles.find({}, {"_id": 0, "id": 1, "name": 1})}
    rows = [await _diagnose(db, u, roles_by_id) async for u in db.users.find({}, _USER_PROJ).sort("email", 1)]
    return {
        "checked_at": now(),
        "summary": {"total": len(rows), "ok": sum(r["status"] == "ok" for r in rows),
                    "error": sum(r["status"] == "error" for r in rows),
                    "fixable": sum(any(i["fixable"] for i in r["issues"]) for r in rows)},
        "users": rows,
    }


@router.post("/fix")
async def fix(request: Request):
    _require_super(await require_auth(request))
    db = get_db()
    roles_by_id = {r["id"]: r["name"] async for r in db.roles.find({}, {"_id": 0, "id": 1, "name": 1})}
    fixed = []
    async for u in db.users.find({}, _USER_PROJ):
        role = u.get("role") or ""
        doc = await resolve_role_doc(db, role, u.get("role_id"), {"_id": 0, "id": 1, "name": 1})
        patch = {"role": doc["name"], "role_id": doc["id"]} if doc else ({"role_id": None} if u.get("role_id") else {})
        if patch and any(u.get(k) != v for k, v in patch.items()):
            await db.users.update_one({"id": u["id"]}, {"$set": {**patch, "updated_at": now()}})
            fixed.append({"email": u.get("email"), "before": {"role": role, "role_id": u.get("role_id")}, "after": patch})
    bump_rbac_cache()
    return {"fixed": len(fixed), "items": fixed}


@router.get("/user/{uid}")
async def user_detail(uid: str, request: Request):
    _require_super(await require_auth(request))
    db = get_db()
    u = await db.users.find_one({"id": uid}, _USER_PROJ)
    if not u:
        raise HTTPException(404, "Akun tidak ditemukan.")
    bump_rbac_cache()
    roles_by_id = {r["id"]: r["name"] async for r in db.roles.find({}, {"_id": 0, "id": 1, "name": 1})}
    diag = await _diagnose(db, u, roles_by_id)
    acc = await resolve_role_access(db, {"id": uid, "role": u.get("role")})
    perms = await compute_permissions(u.get("role") or "", uid)
    modules = []
    for key in sorted(p for p in perms if p.startswith("mod.")):
        _, mid, act = key.split(".")
        if mid in MODULE_BY_ID:
            modules.append({"module": mid, "label": MODULE_BY_ID[mid]["label"], "action": act,
                            "portal": PORTAL_LABELS.get(MODULE_BY_ID[mid]["portal"])})
    return {**diag, "hidden_modules": acc["hidden_modules"], "module_access": acc["module_access"],
            "permissions": perms, "granular": modules}
