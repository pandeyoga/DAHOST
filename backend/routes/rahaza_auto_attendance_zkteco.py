"""
Rahaza Auto-Attendance - ZKTeco Devices
Physical Fingerprint Device Sync (ZKTeco/Fingerspot)
"""
import hashlib
import logging
import uuid
import json
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from database import get_db
from auth import require_auth, serialize_doc, log_activity, check_role
from dotenv import load_dotenv
from utils.waktu import today_wib

load_dotenv()

# WebAuthn imports (graceful fallback)
WEBAUTHN_AVAILABLE = False
try:
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
    from webauthn.helpers.exceptions import (
        InvalidRegistrationResponse,
        InvalidAuthenticationResponse,
    )
    WEBAUTHN_AVAILABLE = True
except Exception:
    def base64url_to_bytes(s): return b""
    def bytes_to_base64url(b): return ""
    class InvalidRegistrationResponse(Exception):
        pass
    class InvalidAuthenticationResponse(Exception):
        pass

# AI Face Compare

router = APIRouter(tags=["rahaza-auto-attendance-zkteco"])
log = logging.getLogger(__name__)

# Config
RP_ID = os.environ.get("WEBAUTHN_RP_ID", "analytics-builds.preview.emergentagent.com")
RP_NAME = os.environ.get("WEBAUTHN_RP_NAME", "Dewi Aditya ERP")
ORIGIN = os.environ.get("WEBAUTHN_ORIGIN", "https://fresh-context-1.preview.emergentagent.com")


def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)
def _today_iso(): return today_wib().isoformat()




@router.get("/devices/zkteco")
async def list_zkteco_devices(request: Request):
    """List semua device ZKTeco yang terkonfigurasi."""
    await require_auth(request)
    db = get_db()
    rows = await db.rahaza_zkteco_devices.find({}, {"_id": 0}).to_list(500)
    return serialize_doc(rows)


@router.post("/devices/zkteco")
async def add_zkteco_device(request: Request):
    """Tambah konfigurasi device ZKTeco/Fingerspot."""
    user = await require_auth(request)
    _require_fp(user)
    db = get_db()
    body = await request.json()
    name = body.get("name", "").strip()
    ip = body.get("ip", "").strip()
    port = int(body.get("port") or 4370)
    if not name or not ip:
        raise HTTPException(400, "name dan ip wajib diisi.")

    doc = {
        "id": _uid(),
        "name": name,
        "ip": ip,
        "port": port,
        "password": int(body.get("password") or 0),
        "timezone": int(body.get("timezone") or 8),  # UTC+8 WIB
        "enabled": bool(body.get("enabled", True)),
        "last_sync_at": None,
        "last_sync_status": None,
        "last_sync_records": 0,
        "last_error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.rahaza_zkteco_devices.insert_one(doc)
    return serialize_doc(doc)


@router.put("/devices/zkteco/{device_id}")
async def update_zkteco_device(device_id: str, request: Request):
    """Update konfigurasi device ZKTeco."""
    user = await require_auth(request)
    _require_fp(user)
    db = get_db()
    body = await request.json()
    updates = {k: v for k, v in {
        "name": body.get("name"), "ip": body.get("ip"),
        "port": body.get("port"), "password": body.get("password"),
        "enabled": body.get("enabled"), "timezone": body.get("timezone"),
        "updated_at": _now(),
    }.items() if v is not None}
    result = await db.rahaza_zkteco_devices.update_one({"id": device_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Device tidak ditemukan.")
    return {"ok": True}


@router.delete("/devices/zkteco/{device_id}")
async def delete_zkteco_device(device_id: str, request: Request):
    """Hapus device ZKTeco."""
    user = await require_auth(request)
    _require_fp(user)
    db = get_db()
    result = await db.rahaza_zkteco_devices.delete_one({"id": device_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Device tidak ditemukan.")
    return {"ok": True}


@router.post("/devices/zkteco/{device_id}/sync")
async def sync_zkteco_device(device_id: str, request: Request):
    """
    Sync attendance logs dari device ZKTeco ke sistem.
    Butuh hardware nyata; simulator mode tersedia untuk testing.
    """
    user = await require_auth(request)
    _require_fp(user)
    db = get_db()
    device = await db.rahaza_zkteco_devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan.")

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    simulator_mode = (await request.json() if request.headers.get("content-type","").startswith("application/json") else {}).get("simulator", False) if False else False

    try:
        body_raw = await request.body()
        if body_raw:
            body = json.loads(body_raw)
        simulator_mode = body.get("simulator", False)
    except Exception:
        logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

    if simulator_mode:
        # Simulator mode: generate fake attendance logs for testing
        emps = await db.rahaza_employees.find({"active": True}, {"_id": 0, "id": 1, "name": 1}).limit(5).to_list(500)
        synced = 0
        today = _today_iso()
        for i, emp in enumerate(emps):
            # Check for ANY existing attendance record for this employee today (not just device_zkteco)
            existing = await db.rahaza_attendance_events.find_one(
                {"employee_id": emp["id"], "date": today}
            )
            if existing:
                continue
            clock_in_time = _now().replace(hour=7 + i % 2, minute=30 + i * 5, second=0, microsecond=0)
            doc = {
                "id": _uid(), "employee_id": emp["id"], "date": today,
                "clock_in": clock_in_time, "clock_out": None,
                "hours_worked": 0, "overtime_hours": 0, "status": "hadir",
                "attendance_method": "device_zkteco", "geo_status": "not_verified",
                "face_match_status": "biometric_verified", "face_match_score": 1.0,
                "approval_status": "auto_approved", "source": "device_zkteco",
                "device_source": device["name"], "device_event_id": f"{device_id}-sim-{today}-{i}",
                "notes": f"Sync dari device: {device['name']} (simulator)",
                "created_by": user["id"], "created_by_name": user.get("name", ""),
                "created_at": _now(), "updated_at": _now(),
                "updated_by": user["id"], "updated_by_name": user.get("name", ""),
            }
            await db.rahaza_attendance_events.insert_one(doc)
            synced += 1

        await db.rahaza_zkteco_devices.update_one({"id": device_id}, {"$set": {
            "last_sync_at": _now(), "last_sync_status": "success_simulator",
            "last_sync_records": synced, "last_error": None,
        }})
        return {"ok": True, "synced": synced, "mode": "simulator",
                "message": f"Simulator: {synced} record kehadiran berhasil disinkronkan."}

    # Real device sync via pyzk.
    # Tahap 2 (2026-11-06): dulu SETIAP ketukan disisipkan sebagai dokumen baru → bentrok indeks unik
    # (employee_id, date) pada ketukan kedua hari itu, lalu SEMUA error dilaporkan "Gagal terhubung ke device".
    # Sekarang ketukan digabung lewat mesin yang sama dengan unggah file ekspor (core.fingerprint_import), dan
    # pesan error membedakan pustaka belum terpasang vs mesin tidak terjangkau.
    async def _fail(code: str, msg: str):
        await db.rahaza_zkteco_devices.update_one({"id": device_id}, {"$set": {
            "last_sync_at": _now(), "last_sync_status": "error", "last_sync_records": 0, "last_error": msg,
            "last_error_code": code}})
        raise HTTPException(503, msg)

    try:
        from zk import ZK
    except ImportError:
        await _fail("pyzk_missing", "Sinkron langsung belum bisa dipakai: pustaka mesin sidik jari (pyzk) belum "
                                    "terpasang di server. Gunakan Unggah file ekspor mesin di bawah.")
    conn = None
    try:
        zk = ZK(device["ip"], port=int(device.get("port") or 4370), timeout=10,
                password=int(device.get("password") or 0), ommit_ping=False)
        conn = zk.connect()
        conn.disable_device()
        attendances = conn.get_attendance()
        conn.enable_device()
    except Exception as e:  # noqa: BLE001 — jaringan / mesin
        log.warning("[zkteco] %s:%s tidak terjangkau: %s", device.get("ip"), device.get("port"), e)
        await _fail("unreachable", f"Server tidak bisa menjangkau mesin di {device.get('ip')}:{device.get('port', 4370)}. "
                                   "Mesin berada di jaringan lokal kantor, sedangkan server ada di internet, jadi "
                                   "sinkron langsung biasanya tidak bisa. Gunakan Unggah file ekspor mesin.")
    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                log.debug("disconnect gagal", exc_info=True)

    from core.fingerprint_import import merge_punches
    punch_dir = {0: "in", 4: "in", 1: "out", 5: "out"}
    punches = [{"code": str(att.user_id).strip().upper(), "at": att.timestamp.replace(tzinfo=None, microsecond=0),
                "direction": punch_dir.get(getattr(att, "punch", None))}
               for att in (attendances or []) if getattr(att, "timestamp", None)]
    stats = await merge_punches(db, punches, user=user, apply=True, source_label=f"sinkron {device['name']}",
                                utc_offset_hours=float(device.get("utc_offset_hours") or 7))
    synced = stats["new"] + stats["updated"]
    await db.rahaza_zkteco_devices.update_one({"id": device_id}, {"$set": {
        "last_sync_at": _now(), "last_sync_status": "success",
        "last_sync_records": synced, "last_error": None, "last_error_code": None,
    }})
    return {"ok": True, "synced": synced, "skipped": stats["unchanged"] + stats["locked"], "mode": "live",
            "stats": stats, "message": f"{synced} hari absensi diperbarui dari mesin ({stats['punches']} ketukan)."}


@router.get("/devices/zkteco/{device_id}/last-sync")
async def get_zkteco_last_sync(device_id: str, request: Request):
    await require_auth(request)
    db = get_db()
    device = await db.rahaza_zkteco_devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(404, "Device tidak ditemukan.")
    return serialize_doc(device)


# ═══════════════════════════════════════════════════════════════════════════════
# 4) HR APPROVAL QUEUE
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# 5) UNGGAH FILE EKSPOR MESIN SIDIK JARI (Tahap 2, 2026-11-06)
# ═══════════════════════════════════════════════════════════════════════════════
# Mesin tidak bisa mengirim lewat https → HR mengunggah file ekspor (CSV/XLSX), memetakan kolom, melihat
# pratinjau, lalu mengimpor. Pemetaan bisa disimpan sebagai profil untuk dipakai lagi.
MAX_EXPORT_BYTES = 10 * 1024 * 1024
FP_ROLES = ("superadmin", "admin", "owner", "hr")
# 2026-11-08: kode peran lama ATAU izin `hr.attendance.manage` (modul Absensi: perangkat & impor sidik jari).
FP_PERM = "hr.attendance.manage"
_AUTO = {
    "code": ("pin", "ac-no", "ac no", "acno", "no. id", "user id", "userid", "id karyawan", "nik", "kode",
             "enroll", "badgenumber", "no id", "id"),
    "datetime": ("date time", "datetime", "waktu", "tanggal jam", "timestamp", "checktime", "check time", "scan"),
    "date": ("date", "tanggal", "tgl"),
    "time": ("time", "jam"),
    "direction": ("state", "status", "in/out", "check type", "checktype", "keterangan", "tipe", "type"),
}


def _require_fp(user: dict) -> None:
    if not check_role(user, FP_ROLES, FP_PERM):
        raise HTTPException(403, "Hanya admin/HR.")


def suggest_mapping(header: list) -> dict:
    low = {h: h.strip().lower() for h in header}
    out: dict = {}
    for key in ("datetime", "code", "date", "time", "direction"):
        for h, lh in low.items():
            if h in out.values():
                continue
            if any(lh == w or (len(w) > 3 and w in lh) for w in _AUTO[key]):
                out[key] = h
                break
    if out.get("datetime"):
        out.pop("date", None)
        out.pop("time", None)
    return out


async def _parse_upload(db, file: UploadFile, mapping: str, profile_id: str, date_order: str,
                        header_row: int) -> dict:
    from core import fingerprint_import as fi
    data = await file.read()
    if len(data) > MAX_EXPORT_BYTES:
        raise HTTPException(413, "Ukuran file melebihi 10 MB. Ekspor per bulan lalu unggah satu per satu.")
    if not data:
        raise HTTPException(400, "File kosong.")
    profile = None
    if profile_id:
        profile = await db.rahaza_fingerprint_profiles.find_one({"id": profile_id}, {"_id": 0})
        if not profile:
            raise HTTPException(404, "Profil pemetaan tidak ditemukan.")
    rows = fi.read_table(file.filename or "", data)
    hdr_row = int(header_row if header_row is not None else (profile or {}).get("header_row") or 0)
    header, body = fi.split_header(rows, hdr_row)
    try:
        m = json.loads(mapping) if mapping else None
    except ValueError:
        raise HTTPException(400, "Pemetaan kolom tidak terbaca.")
    m = m or (profile or {}).get("mapping") or suggest_mapping(header)
    order = (date_order or (profile or {}).get("date_order") or "dmy").lower()
    if order not in ("dmy", "mdy", "ymd"):
        raise HTTPException(400, "Urutan tanggal tidak dikenal.")
    return {"data": data, "header": header, "rows": body, "mapping": m, "date_order": order,
            "header_row": hdr_row, "profile": profile,
            "in_values": (profile or {}).get("in_values") or list(fi.DEFAULT_IN_VALUES),
            "out_values": (profile or {}).get("out_values") or list(fi.DEFAULT_OUT_VALUES)}


async def _run_fingerprint(request: Request, file: UploadFile, mapping: str, profile_id: str, date_order: str,
                           header_row: int, apply: bool) -> dict:
    user = await require_auth(request)
    _require_fp(user)
    db = get_db()
    from core import fingerprint_import as fi
    up = await _parse_upload(db, file, mapping, profile_id, date_order, header_row)
    sample = [[("" if c is None else str(c)) for c in r[:len(up["header"])]] for r in up["rows"][:5]]
    base = {"filename": file.filename, "header": up["header"], "sample_rows": sample,
            "mapping": up["mapping"], "suggested_mapping": suggest_mapping(up["header"]),
            "date_order": up["date_order"], "header_row": up["header_row"], "total_rows": len(up["rows"])}
    try:
        punches, bad = fi.extract_punches(up["header"], up["rows"], up["mapping"], date_order=up["date_order"],
                                          in_values=up["in_values"], out_values=up["out_values"])
    except HTTPException as e:
        if apply:
            raise
        return {**base, "ready": False, "mapping_error": e.detail}
    sha = hashlib.sha256(up["data"]).hexdigest()
    prev = await db.rahaza_fingerprint_imports.find_one({"sha256": sha, "applied": True}, {"_id": 0})
    import_id = str(uuid.uuid4())
    stats = await fi.merge_punches(db, punches, user=user, apply=apply, import_id=import_id if apply else None,
                                   source_label=f"file {file.filename or ''}".strip())
    stats["invalid_rows"] = bad
    out = {**base, "ready": True, "stats": stats,
           "previous_import_at": (prev or {}).get("created_at")}
    if apply:
        await db.rahaza_fingerprint_imports.insert_one({
            "id": import_id, "filename": file.filename, "sha256": sha, "applied": True,
            "mapping": up["mapping"], "date_order": up["date_order"], "profile_id": profile_id or None,
            "stats": {k: v for k, v in stats.items() if k != "samples"},
            "created_by": user["id"], "created_by_name": user.get("name", ""), "created_at": _now()})
        await log_activity(user["id"], user.get("name", ""), "import", "attendance.fingerprint",
                           f"{file.filename}: {stats['new']} baru, {stats['updated']} dilengkapi")
        out["import_id"] = import_id
    return serialize_doc(out)


@router.post("/devices/fingerprint/preview")
async def fingerprint_preview(request: Request, file: UploadFile = File(...), mapping: str = Form(""),
                              profile_id: str = Form(""), date_order: str = Form(""),
                              header_row: Optional[int] = Form(None)):
    """Pratinjau unggahan: kepala kolom, contoh baris, usulan pemetaan, dan hitungan (tanpa menulis)."""
    return await _run_fingerprint(request, file, mapping, profile_id, date_order, header_row, apply=False)


@router.post("/devices/fingerprint/import")
async def fingerprint_import(request: Request, file: UploadFile = File(...), mapping: str = Form(""),
                             profile_id: str = Form(""), date_order: str = Form(""),
                             header_row: Optional[int] = Form(None)):
    """Impor sungguhan. Aman diulang: file yang sama tidak mengubah apa pun untuk kedua kalinya."""
    return await _run_fingerprint(request, file, mapping, profile_id, date_order, header_row, apply=True)


@router.get("/devices/fingerprint/imports")
async def fingerprint_import_history(request: Request, limit: int = 20):
    user = await require_auth(request)
    _require_fp(user)
    rows = await get_db().rahaza_fingerprint_imports.find({}, {"_id": 0}).sort("created_at", -1).limit(
        min(max(limit, 1), 100)).to_list(100)
    return {"items": serialize_doc(rows)}


@router.get("/devices/fingerprint/profiles")
async def list_fingerprint_profiles(request: Request):
    user = await require_auth(request)
    _require_fp(user)
    rows = await get_db().rahaza_fingerprint_profiles.find({}, {"_id": 0}).sort("name", 1).to_list(100)
    return {"items": serialize_doc(rows)}


@router.post("/devices/fingerprint/profiles")
async def save_fingerprint_profile(request: Request):
    """Simpan pemetaan kolom sebagai profil (nama sama = diperbarui)."""
    user = await require_auth(request)
    _require_fp(user)
    db = get_db()
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nama profil wajib diisi.")
    mapping = {k: v for k, v in (body.get("mapping") or {}).items()
               if k in ("code", "datetime", "date", "time", "direction") and isinstance(v, str) and v}
    if not mapping.get("code") or not (mapping.get("datetime") or (mapping.get("date") and mapping.get("time"))):
        raise HTTPException(400, "Profil butuh kolom kode karyawan dan kolom tanggal-jam (atau tanggal + jam).")
    order = (body.get("date_order") or "dmy").lower()
    if order not in ("dmy", "mdy", "ymd"):
        raise HTTPException(400, "Urutan tanggal tidak dikenal.")
    doc = {"name": name, "mapping": mapping, "date_order": order, "header_row": int(body.get("header_row") or 0),
           "in_values": [str(x) for x in (body.get("in_values") or []) if str(x).strip()] or None,
           "out_values": [str(x) for x in (body.get("out_values") or []) if str(x).strip()] or None,
           "updated_by": user["id"], "updated_by_name": user.get("name", ""), "updated_at": _now()}
    existing = await db.rahaza_fingerprint_profiles.find_one({"name": name}, {"_id": 0, "id": 1})
    if existing:
        await db.rahaza_fingerprint_profiles.update_one({"id": existing["id"]}, {"$set": doc})
        doc["id"] = existing["id"]
    else:
        doc.update({"id": str(uuid.uuid4()), "created_at": _now()})
        await db.rahaza_fingerprint_profiles.insert_one(dict(doc))
    return {"ok": True, "profile": serialize_doc(doc)}


@router.delete("/devices/fingerprint/profiles/{profile_id}")
async def delete_fingerprint_profile(profile_id: str, request: Request):
    user = await require_auth(request)
    _require_fp(user)
    res = await get_db().rahaza_fingerprint_profiles.delete_one({"id": profile_id})
    if not res.deleted_count:
        raise HTTPException(404, "Profil tidak ditemukan.")
    return {"ok": True}

