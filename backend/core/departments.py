"""core.departments — SATU daftar departemen dan SATU kunci banding departemen (OR1, 2026-11-07).

Keputusan owner OR1 (Tahap 6): Struktur Organisasi (`dewi_org_units`) adalah satu-satunya daftar
departemen. Data Karyawan, OKR, Permintaan Pembelian, aset, dan anggaran memilih dari daftar itu;
nilai yang DISIMPAN di dokumen = NAMA unit (sama dengan `rahaza_employees.department`, bagan
organisasi, dan headcount).

Persetujuan tahap departemen pada Permintaan Pembelian membandingkan departemen PR dengan departemen
penyetuju. Dua sisi itu dulu berasal dari sumber berbeda dan dibandingkan persis:
  * PR      : teks bebas yang diketik pemohon ("produksi ", "Produksi");
  * penyetuju: `users.department` (akun login) — kosong di hampir semua akun, padahal departemen
               karyawan tercatat di data karyawan.
Akibatnya batas departemen diam-diam tidak berjalan, atau typo membuat PR salah rute.

Sekarang:
  * `department_key()` — kunci banding (huruf kecil, spasi & tanda baca diabaikan) dipakai SEMUA
    pembanding departemen;
  * `user_department()` / `user_departments()` — departemen pengguna = departemen KARYAWAN yang
    ditautkan (`utils.employee_identity.resolve_my_employee`), cadangan `users.department`;
  * `canonical_department()` — nilai yang cocok (menurut kunci) dengan unit Struktur Organisasi
    disimpan memakai ejaan unit itu.
"""
from __future__ import annotations

from core.variant_identity import norm

ORG_UNITS = "dewi_org_units"


def department_key(value) -> str:
    """Kunci banding departemen ('' bila kosong). "Produksi " = "produksi" = "PRODUKSI"."""
    return norm(value)


def same_department(a, b) -> bool:
    """True bila dua nilai departemen menunjuk departemen yang sama (keduanya harus terisi)."""
    ka, kb = department_key(a), department_key(b)
    return bool(ka) and ka == kb


async def org_unit_names(db, *, active_only: bool = True) -> list[str]:
    """Nama unit Struktur Organisasi (urut level), tanpa duplikat menurut kunci."""
    flt = {"is_active": {"$ne": False}} if active_only else {}
    seen, out = set(), []
    async for u in db[ORG_UNITS].find(flt, {"_id": 0, "name": 1}).sort("level", 1):
        k = department_key(u.get("name"))
        if k and k not in seen:
            seen.add(k)
            out.append(u["name"])
    return out


async def canonical_department(db, value) -> str:
    """Ejaan resmi (nama unit) untuk `value` bila cocok dengan unit Struktur Organisasi; selain itu
    `value` apa adanya (dirapikan spasinya) supaya data lama/impor tidak hilang."""
    v = " ".join(str(value or "").split())
    k = department_key(v)
    if not k:
        return ""
    for name in await org_unit_names(db):
        if department_key(name) == k:
            return name
    return v


async def user_department(db, user: dict) -> str:
    """Departemen pengguna login = departemen karyawan yang ditautkan; cadangan `users.department`."""
    if not user:
        return ""
    from utils.employee_identity import resolve_my_employee
    try:
        emp = await resolve_my_employee(db, user)
    except Exception:  # noqa: BLE001 — departemen tidak boleh menggagalkan alur pemanggil
        emp = None
    dept = (emp or {}).get("department") or ""
    if dept:
        return dept
    if user.get("department"):
        return user["department"]
    u = await db.users.find_one({"id": user.get("id")}, {"_id": 0, "department": 1}) if user.get("id") else None
    return (u or {}).get("department") or ""


async def user_departments(db, users: list[dict]) -> dict[str, str]:
    """{user_id: departemen} untuk banyak pengguna sekaligus (aturan sama dengan `user_department`,
    tanpa cocok email): `users.employee_id` → `rahaza_employees.user_id` → `users.department`."""
    ids = [u.get("id") for u in users if u.get("id")]
    emp_ids = [u.get("employee_id") for u in users if u.get("employee_id")]
    if not ids:
        return {}
    flt = {"active": {"$ne": False}, "$or": [{"user_id": {"$in": ids}}] + (
        [{"id": {"$in": emp_ids}}] if emp_ids else [])}
    by_emp, by_user = {}, {}
    async for e in db.rahaza_employees.find(flt, {"_id": 0, "id": 1, "user_id": 1, "department": 1}):
        by_emp[e.get("id")] = e.get("department") or ""
        if e.get("user_id"):
            by_user.setdefault(e["user_id"], e.get("department") or "")
    out = {}
    for u in users:
        uid = u.get("id")
        if not uid:
            continue
        out[uid] = (by_emp.get(u.get("employee_id")) or by_user.get(uid) or u.get("department") or "")
    return out
