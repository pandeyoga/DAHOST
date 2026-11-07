"""Berkas unggahan yang memuat data pribadi karyawan — SSOT (2026-11-07).

`GET /api/uploads/{path}` (`routes/uploads_serve.py`) melayani berkas TANPA login supaya foto produk,
logo perusahaan, foto aset, dan lampiran chat tetap tampil seperti biasa. Berkas di bawah ini memuat
data pribadi (selfie absen, surat dokter, foto profil, KTP/KK/BPJS karyawan), jadi WAJIB membawa token:
header `Authorization: Bearer <token>` atau `?auth=<token>` (tag <img>/<a> tidak bisa mengirim header),
diperiksa dengan `auth.verify_download_token` — jalur yang SAMA dengan `GET /api/files/{path}`.

Dua cara sebuah berkas dianggap sensitif:
  1. path diawali salah satu `SENSITIVE_UPLOAD_PREFIXES` (ditulis oleh
     `utils/attendance_policy.save_selfie`, `routes/rahaza_leave.py`, `routes/dewi_portal_saya_hr.py`);
  2. path terdaftar di `db.attachments` dengan `entity_type` di `SENSITIVE_ATTACHMENT_TYPES` (diunggah lewat
     `POST /api/upload?entity_type=...`) — termasuk yang sudah dihapus, karena berkasnya masih tersimpan.

Layar memasang token lewat SATU helper: `frontend/src/lib/fileUrl.js` → `withFileAuth(url)`.
"""
from __future__ import annotations

import posixpath
from typing import Optional

# Folder unggahan berisi data pribadi.
SENSITIVE_UPLOAD_PREFIXES: tuple = (
    "attendance/",   # selfie absen masuk/pulang — utils/attendance_policy.save_selfie
    "leave_docs/",   # lampiran cuti (surat dokter, dsb.) — routes/rahaza_leave.py
    "profile/",      # foto profil Portal Saya — routes/dewi_portal_saya_hr.py
    # Asisten AI (laporan): PDF/Excel buatan Asisten AI (angka keuangan/SDM). Unduhan resminya lewat
    # GET /api/asisten-ai/laporan/{id} (cek pembuat); di sini minimal wajib login — core/laporan_ai.py.
    "ai_reports/",
)

# `entity_type` lampiran (`db.attachments`) yang memuat data pribadi/HR.
# Dipakai kode & data saat ini: `employee` (dokumen & foto karyawan, HREmployeeModule).
# Sisanya jenis HR/pribadi yang dijaga sejak awal: `POST /api/upload` menerima `entity_type` bebas dari
# layar, jadi lampiran HR baru otomatis terlindungi tanpa mengubah daftar ini lagi.
SENSITIVE_ATTACHMENT_TYPES: frozenset = frozenset({
    "employee",
    "employee_document",
    "employee_photo",
    "attendance",
    "attendance_correction",
    "leave",
    "leave_request",
    "medical",
    "payroll",
    "payslip",
    "kasbon",
    "expense_claim",
    "travel_request",
    "travel_settlement",
})


def normalize_upload_path(path: Optional[str]) -> str:
    """Path relatif yang sama dengan yang dibaca penyimpanan (`./x`, `//x`, `a/./b` diseragamkan),
    supaya pemeriksaan awalan tidak bisa dilewati dengan penulisan path yang berbeda."""
    p = (path or "").replace("\\", "/").lstrip("/")
    if not p:
        return ""
    p = posixpath.normpath(p)
    return "" if p == "." else p.lstrip("/")


def has_sensitive_prefix(path: Optional[str]) -> bool:
    return normalize_upload_path(path).startswith(SENSITIVE_UPLOAD_PREFIXES)


def is_sensitive_attachment_type(entity_type: Optional[str]) -> bool:
    return (entity_type or "").strip().lower() in SENSITIVE_ATTACHMENT_TYPES


async def is_sensitive_upload(db, path: Optional[str]) -> bool:
    """True bila berkas di `path` hanya boleh dibuka dengan token."""
    norm = normalize_upload_path(path)
    if norm.startswith(SENSITIVE_UPLOAD_PREFIXES):
        return True
    candidates = list({norm, (path or "").lstrip("/")} - {""})
    if not candidates:
        return False
    # Lampiran yang sudah dihapus (soft delete) TETAP dijaga: berkasnya masih ada di penyimpanan.
    rec = await db.attachments.find_one(
        {"storage_path": {"$in": candidates}, "entity_type": {"$in": sorted(SENSITIVE_ATTACHMENT_TYPES)}},
        {"_id": 0, "entity_type": 1},
    )
    return rec is not None


def request_file_token(request, auth_query: Optional[str]) -> str:
    """Token dari header `Authorization: Bearer ...` atau dari `?auth=` (untuk <img src>/<a href>)."""
    header = request.headers.get("Authorization", "") if request is not None else ""
    if header.startswith("Bearer "):
        return header.split(" ", 1)[1].strip()
    return (auth_query or "").strip()


def file_request_user(request, auth_query: Optional[str]):
    """Payload token yang sah (`auth.verify_download_token`), atau None."""
    from auth import verify_download_token
    raw = request_file_token(request, auth_query)
    return verify_download_token(raw) if raw else None
