"""core.employee_data_change — perubahan data kontak karyawan dari Portal Saya lewat persetujuan HR (HR1).

Keputusan owner HR1 (Tahap 6, 2026-11-07): ubahan No. HP, alamat, dan kontak darurat di Portal Saya ›
Profil dulu hanya tersimpan di AKUN LOGIN (`users.no_hp`, `users.alamat`, `users.kontak_darurat`) — data
karyawan (`rahaza_employees`) yang dibaca HR, slip, dan laporan tidak pernah berubah. Sekarang:

  1. Karyawan menyimpan profil → satu PENGAJUAN di `rahaza_employee_data_changes` berisi field yang
     berbeda dari data karyawan (lama → baru). Data karyawan BELUM berubah.
  2. HR memutus di Kotak Masuk SDM (`routes/hr_approval_inbox.py`, jenis `employee_data_change`):
       * Setujui → nilai baru ditulis ke data karyawan, dan akun login ikut diselaraskan;
       * Tolak (wajib alasan) → tidak ada yang berubah.
  3. Karyawan melihat status pengajuan (menunggu / ditolak + alasan) di Profil, dan boleh menariknya.

Klaim atomik (pola P9, `core.doc_lock`): keputusan ditulis bersyarat `status: pending` — Setujui ganda /
Setujui-Tolak bersamaan → 409, data karyawan tidak ditulis dua kali.

Bentuk dokumen `rahaza_employee_data_changes`:
  {id, employee_id, user_id, changes: [{field, label, old, new}], status: pending|deciding|approved|
   rejected|cancelled, created_at, created_by, created_by_name, decided_by, decided_by_name, decided_at,
   decision_note, applied: {field: nilai} (saat disetujui), updated_at}
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from core import doc_lock

COLL = "rahaza_employee_data_changes"
STATUSES = ("pending", "deciding", "approved", "rejected", "cancelled")

#: (kunci isian Profil, field data karyawan, label layar, batas panjang, jenis)
FIELDS = (
    ("no_hp", "phone", "No. HP", 20, "phone"),
    ("alamat", "current_address", "Alamat tinggal", 300, "text"),
    ("kontak_darurat.nama", "emergency_contact_name", "Nama kontak darurat", 100, "text"),
    ("kontak_darurat.hubungan", "emergency_relation", "Hubungan kontak darurat", 50, "text"),
    ("kontak_darurat.no_hp", "emergency_phone", "No. HP kontak darurat", 20, "phone"),
)
EMP_FIELDS = tuple(f[1] for f in FIELDS)
LABEL = {f[1]: f[2] for f in FIELDS}
_PHONE_RX = re.compile(r"^[0-9+()\-. ]*$")

MSG_PENDING = ("Masih ada perubahan data yang menunggu persetujuan HR. Tarik dulu pengajuan itu bila ingin "
               "mengubahnya lagi.")
MSG_RACE = "Pengajuan perubahan data ini baru saja diputuskan pengguna lain — muat ulang kotak masuk."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get(body: dict, dotted: str):
    cur = body
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _clean(v) -> str:
    return str(v if v is not None else "").strip()


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def requested_values(body: dict) -> dict:
    """Isian Profil → {field karyawan: nilai baru} hanya untuk isian yang DIKIRIM (divalidasi)."""
    out = {}
    for key, emp_field, label, max_len, kind in FIELDS:
        v = _get(body or {}, key)
        if v is None:
            continue
        v = _clean(v)
        if len(v) > max_len:
            raise HTTPException(400, f"{label} terlalu panjang (paling banyak {max_len} huruf).")
        if kind == "phone" and v:
            if not _PHONE_RX.match(v) or not (8 <= len(re.sub(r"\D", "", v)) <= 15):
                raise HTTPException(400, f"{label} tidak valid. Tulis nomor 8–15 angka, mis. 0812 3456 7890.")
        out[emp_field] = v
    return out


def diff_changes(emp: dict, requested: dict) -> list:
    """[{field, label, old, new}] untuk nilai yang BERBEDA dari data karyawan sekarang."""
    out = []
    for field in EMP_FIELDS:
        if field not in requested:
            continue
        old = _clean((emp or {}).get(field))
        if old != requested[field]:
            out.append({"field": field, "label": LABEL[field], "old": old, "new": requested[field]})
    return out


def profile_values(emp: dict | None, user: dict | None) -> tuple[dict, list]:
    """Nilai kontak untuk layar Profil dalam bentuk isian Profil, + daftar isian yang masih berasal
    dari akun login lama (data karyawan kosong) — tampil dan bisa diajukan ke HR."""
    u = user or {}
    kd_user = u.get("kontak_darurat") or {}
    legacy = {"no_hp": u.get("no_hp"), "alamat": u.get("alamat"), "kontak_darurat.nama": kd_user.get("nama"),
              "kontak_darurat.hubungan": kd_user.get("hubungan"), "kontak_darurat.no_hp": kd_user.get("no_hp")}
    vals, from_account = {}, []
    for key, emp_field, *_ in FIELDS:
        v = (emp or {}).get(emp_field) if emp else None
        if not v and legacy.get(key):
            v = legacy[key]
            if emp:
                from_account.append(key)
        vals[key] = v or ""
    return ({"no_hp": vals["no_hp"], "alamat": vals["alamat"],
             "kontak_darurat": {"nama": vals["kontak_darurat.nama"], "hubungan": vals["kontak_darurat.hubungan"],
                                "no_hp": vals["kontak_darurat.no_hp"]}}, from_account)


def account_patch(values: dict, account: dict | None = None) -> dict:
    """{field karyawan: nilai} → field akun login yang dibaca layar lama (diselaraskan saat disetujui).
    `kontak_darurat` ditulis utuh (gabungan isi lama + baru) — akun lama bisa menyimpan `null` di sana."""
    patch = {}
    if "phone" in values:
        patch["no_hp"] = values["phone"]
    if "current_address" in values:
        patch["alamat"] = values["current_address"]
    kd = dict((account or {}).get("kontak_darurat") or {})
    touched = False
    for emp_field, key in (("emergency_contact_name", "nama"), ("emergency_relation", "hubungan"),
                           ("emergency_phone", "no_hp")):
        if emp_field in values:
            kd[key] = values[emp_field]
            touched = True
    if touched:
        patch["kontak_darurat"] = kd
    return patch


async def latest_for_employee(db, emp_id: str) -> dict | None:
    """Pengajuan yang masih berjalan, atau keputusan terakhir (untuk ditampilkan di Profil)."""
    if not emp_id:
        return None
    rows = await db.rahaza_employee_data_changes.find({"employee_id": emp_id}, {"_id": 0}).sort(
        "created_at", -1).limit(1).to_list(1)
    return rows[0] if rows else None


async def submit_change(db, user: dict, emp: dict, body: dict) -> dict | None:
    """Ajukan perubahan. None bila tidak ada yang berbeda dari data karyawan."""
    changes = diff_changes(emp, requested_values(body))
    if not changes:
        return None
    if await db.rahaza_employee_data_changes.find_one(
            {"employee_id": emp["id"], "status": {"$in": ["pending", "deciding"]}}, {"_id": 0, "id": 1}):
        raise HTTPException(409, MSG_PENDING)
    now = _now()
    doc = {"id": str(uuid.uuid4()), "employee_id": emp["id"], "user_id": user.get("id"), "changes": changes,
           "status": "pending", "created_at": now, "created_by": user.get("id"),
           "created_by_name": user.get("name", ""), "updated_at": now}
    await db.rahaza_employee_data_changes.insert_one(dict(doc))
    await _notify_hr(db, doc, emp, user)
    return doc


async def _notify_hr(db, doc: dict, emp: dict, actor: dict) -> None:
    """Kabari HR (bel notifikasi → Kotak Masuk SDM). Best-effort."""
    try:
        from core.roles import HR_ROLES
        from utils.notif_unified import decider_roles, notif_insert
        await notif_insert(
            db, type="rahaza", subtype="employee_data_change_submitted", severity="info",
            title="Perubahan data karyawan menunggu persetujuan",
            body=f"{emp.get('name') or 'Karyawan'}: " + ", ".join(c["label"] for c in doc["changes"]),
            source_type="employee_data_change", source_id=doc["id"],
            target_roles=decider_roles("hr", HR_ROLES), exclude_user_ids=[x for x in [actor.get("id")] if x],
            status="sent", meta={"link_module": "hr-inbox"})
    except Exception:  # noqa: BLE001 — notifikasi tidak boleh menggagalkan pengajuan
        import logging
        logging.getLogger(__name__).warning("notifikasi pengajuan perubahan data gagal (%s)", doc.get("id"))


async def cancel_change(db, emp: dict) -> None:
    res = await db.rahaza_employee_data_changes.update_one(
        {"employee_id": emp["id"], "status": "pending"},
        {"$set": {"status": "cancelled", "cancelled_at": _now(), "updated_at": _now()}})
    doc_lock.require_matched(res, "Tidak ada pengajuan yang menunggu, atau HR baru saja memutuskannya.")


async def inbox_items(db, limit: int) -> list:
    """Bentuk item Kotak Masuk SDM. `old` = nilai di data karyawan SAAT INI (yang akan diganti)."""
    rows = await db.rahaza_employee_data_changes.find({"status": "pending"}, {"_id": 0}).sort(
        "created_at", -1).limit(limit).to_list(limit)
    if not rows:
        return []
    ids = list({r.get("employee_id") for r in rows if r.get("employee_id")})
    emps = await db.rahaza_employees.find({"id": {"$in": ids}}, {"_id": 0}).to_list(500) if ids else []
    m = {e["id"]: e for e in emps}
    out = []
    for r in rows:
        e = m.get(r.get("employee_id")) or {}
        changes = [{**c, "old": _clean(e.get(c["field"])) if e else c.get("old", "")}
                   for c in r.get("changes") or []]
        created = _iso(r.get("created_at"))
        out.append({
            "id": r["id"], "type": "employee_data_change", "type_label": "Perubahan data",
            "created_at": created, "submitted_at": created,
            "requester_id": r.get("employee_id"), "requester_name": e.get("name"),
            "requester_code": e.get("employee_code"), "requester_dept": e.get("department"),
            "title": "Perubahan data: " + ", ".join(c["label"] for c in changes),
            "period": "", "reason": "", "amount": None,
            "meta": {"changes": changes},
            "raw": {k: _iso(v) for k, v in r.items() if k != "_id"},
        })
    return out


async def decide(db, req_id: str, user: dict, *, approve: bool, note: str = "") -> dict:
    """SATU fungsi keputusan (Kotak Masuk SDM). Setujui → data karyawan + akun login diperbarui."""
    doc = await db.rahaza_employee_data_changes.find_one({"id": req_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Pengajuan perubahan data tidak ditemukan.")
    if doc.get("status") != "pending":
        raise HTTPException(409, "Pengajuan ini sudah diputuskan atau ditarik — muat ulang kotak masuk.")
    from utils.employee_identity import resolve_my_employee
    mine = await resolve_my_employee(db, user)
    if mine and mine.get("id") == doc.get("employee_id"):
        raise HTTPException(403, "Pemisahan tugas: perubahan data Anda sendiri harus diputus HR lain.")
    now = _now()
    decided = {"decided_by": user.get("id"), "decided_by_name": user.get("name", ""), "decided_at": now,
               "decision_note": note or "", "updated_at": now}
    if not approve:
        if not (note or "").strip():
            raise HTTPException(400, "Alasan penolakan wajib diisi.")
        res = await db.rahaza_employee_data_changes.update_one({"id": req_id, "status": "pending"},
                                                               {"$set": {"status": "rejected", **decided}})
        doc_lock.require_matched(res, MSG_RACE)
        await _notify(db, doc, approved=False, note=note)
        return {**doc, "status": "rejected", **decided}

    # klaim atomik pending → deciding SEBELUM data karyawan ditulis
    res = await db.rahaza_employee_data_changes.update_one({"id": req_id, "status": "pending"},
                                                           {"$set": {"status": "deciding", "updated_at": now}})
    doc_lock.require_matched(res, MSG_RACE)
    try:
        emp = await db.rahaza_employees.find_one({"id": doc["employee_id"]}, {"_id": 0})
        if not emp:
            raise HTTPException(404, "Data karyawan untuk pengajuan ini tidak ditemukan.")
        values = {c["field"]: c["new"] for c in doc.get("changes") or [] if c.get("field") in EMP_FIELDS}
        before = {f: emp.get(f) for f in values}
        if values:
            await db.rahaza_employees.update_one({"id": emp["id"]}, {"$set": {**values, "updated_at": now}})
            uid = doc.get("user_id") or emp.get("user_id")
            if uid:   # akun login diselaraskan (layar lama & profil akun tanpa tautan karyawan membacanya)
                acc = await db.users.find_one({"id": uid}, {"_id": 0, "kontak_darurat": 1}) or {}
                await db.users.update_one({"id": uid}, {"$set": {**account_patch(values, acc),
                                                                 "updated_at": now.isoformat()}})
        upd = {"status": "approved", "applied": values, "before_applied": before, **decided}
        await db.rahaza_employee_data_changes.update_one({"id": req_id, "status": "deciding"}, {"$set": upd})
    except BaseException:
        await db.rahaza_employee_data_changes.update_one({"id": req_id, "status": "deciding"},
                                                         {"$set": {"status": "pending"}})
        raise
    await _notify(db, doc, approved=True, note=note)
    return {**doc, **upd}


async def _notify(db, doc: dict, *, approved: bool, note: str = "") -> None:
    """Kabari karyawan di bel notifikasi (best-effort — keputusan tidak boleh gagal karena notifikasi)."""
    uid = doc.get("user_id")
    if not uid:
        return
    try:
        from utils.notif_unified import notif_insert
        labels = ", ".join(c.get("label", "") for c in doc.get("changes") or [])
        await notif_insert(
            db, type="rahaza", subtype="employee_data_change", severity="info" if approved else "warning",
            title="Perubahan data Anda disetujui HR" if approved else "Perubahan data Anda ditolak HR",
            body=labels + ("" if approved else f"\nAlasan: {note}"), user_id=uid,
            source_type="employee_data_change", source_id=doc.get("id"),
            meta={"link_module": "portal-profile"})
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("notifikasi perubahan data gagal (%s)", doc.get("id"))
