"""Rantai persetujuan cuti & lembur: ATASAN LANGSUNG → HR — 2026-11-09 (Q6 + H6, keputusan owner).

Masalah (audit HR H6/M9/M14): siapa pun berperan penyetuju bisa memutus cuti/lembur siapa pun; tingkat 1 "atasan"
tidak pernah dicek terhadap atasan karyawan; kabar ke atasan dikirim ke ID KARYAWAN (`manager_id`) padahal
notifikasi butuh ID AKUN → atasan tidak pernah dikabari. Struktur atasan di data karyawan tidak dipakai.

Aturan sekarang (satu tempat untuk `core.leave_engine` dan `routes.rahaza_overtime`):
  · Tingkat 1 = atasan langsung (`rahaza_employees.manager_id`, lewat AKUN yang tertaut — `employee_user_ids`).
  · Tingkat 2 = HR (peran/izin penyetuju SDM).
  · Atasan kosong / belum punya akun / nonaktif → langsung HR (satu tingkat).
  · owner/superadmin/admin boleh memutus tingkat mana pun (cadangan bila atasan berhalangan).
  · Pengajuan lama (sebelum aturan ini, tanpa `approval_route`) mengikuti aturan lamanya.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

SUPER_APPROVER_ROLES = ("superadmin", "owner", "admin")
STAGE_MANAGER = "atasan"
STAGE_HR = "hr"


def is_super_approver(user: Optional[dict]) -> bool:
    return ((user or {}).get("role") or "").lower() in SUPER_APPROVER_ROLES


async def manager_route(db, emp: Optional[dict]) -> dict:
    """Atasan langsung karyawan + akun login aktifnya. `levels` = 2 (atasan → HR) atau 1 (langsung HR)."""
    from utils.employee_identity import employee_user_ids
    e = emp or {}
    out = {"level_1": STAGE_HR, "manager_employee_id": None, "manager_name": "", "manager_user_ids": [], "levels": 1}
    mid = e.get("manager_id") or e.get("supervisor_id")
    if not mid or mid == e.get("id"):
        return out
    mgr = await db.rahaza_employees.find_one({"id": mid}, {"_id": 0, "id": 1, "name": 1, "active": 1})
    if not mgr or mgr.get("active") is False:
        return out
    uids = await employee_user_ids(db, mid)
    if not uids:
        return {**out, "manager_employee_id": mid, "manager_name": mgr.get("name") or "",
                "note": "atasan belum punya akun login — langsung HR"}
    return {"level_1": STAGE_MANAGER, "manager_employee_id": mid, "manager_name": mgr.get("name") or "",
            "manager_user_ids": uids, "levels": 2}


async def is_route_manager(db, user: dict, doc: dict) -> bool:
    """Akun `user` = atasan langsung pada rute dokumen ini (dibaca ulang — tautan akun bisa berubah)."""
    from utils.employee_identity import employee_user_ids
    mid = (doc.get("approval_route") or {}).get("manager_employee_id")
    if not mid or not user.get("id"):
        return False
    return user["id"] in await employee_user_ids(db, mid)


def waiting_manager(doc: dict) -> bool:
    """Dokumen ini sedang menunggu ATASAN (tingkat 1 dari 2, rute baru)?"""
    route = doc.get("approval_route") or {}
    return (route.get("level_1") == STAGE_MANAGER and int(doc.get("approval_level_required") or 1) > 1
            and int(doc.get("current_approval_level") or 1) == 1)


async def decision_stage(db, doc: dict, user: dict, *, is_hr_approver: bool, action: str = "approve",
                         what: str = "pengajuan") -> str:
    """Tahap yang diputus `user` ('atasan' | 'hr'); 403 bila tidak berhak.

    · Menunggu atasan: hanya atasan langsung (atau owner/superadmin/admin). HR boleh MENOLAK (tidak
      menguntungkan siapa pun), tidak boleh menyetujui melompati atasan.
    · Tahap HR (atau rute satu tingkat / data lama): hanya penyetuju HR."""
    if waiting_manager(doc):
        if is_super_approver(user) or await is_route_manager(db, user, doc):
            return STAGE_MANAGER
        if action == "reject" and is_hr_approver:
            return STAGE_HR
        name = (doc.get("approval_route") or {}).get("manager_name") or "atasan langsung"
        raise HTTPException(403, f"{what.capitalize()} ini menunggu persetujuan atasan langsung ({name}). "
                                 "HR memutus sesudah atasan menyetujui.")
    if is_hr_approver or is_super_approver(user):
        return STAGE_HR
    raise HTTPException(403, f"Persetujuan {what} tahap HR hanya untuk HR.")


async def team_member_ids(db, user: dict) -> list:
    """Id karyawan yang atasan langsungnya = karyawan milik akun `user` (untuk daftar Persetujuan tim)."""
    from utils.employee_identity import resolve_my_employee
    me = await resolve_my_employee(db, user)
    if not me:
        return []
    rows = await db.rahaza_employees.find({"$or": [{"manager_id": me["id"]}, {"supervisor_id": me["id"]}],
                                           "active": {"$ne": False}}, {"_id": 0, "id": 1}).to_list(500)
    return [r["id"] for r in rows if r.get("id")]
