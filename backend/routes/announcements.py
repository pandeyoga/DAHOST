"""
Papan pengumuman — endpoint pengumuman yang tampil di halaman pilih portal.
Kelola (buat/ubah/hapus) di Portal SDM › Papan Pengumuman.

2026-11-08 (uji ketajaman UI/UX, temuan data):
  • Tanggal dikirim BERZONA WAKTU (+00:00). Dulu dikirim tanpa zona ("2026-11-30T17:00:00"), sehingga peramban
    membacanya sebagai jam setempat: tanggal tampil mundur sehari dan setiap kali diubah-simpan bergeser lagi.
  • Ubah boleh MENGOSONGKAN tanggal mulai/berakhir (dulu nilai null dibuang → tanggal tak bisa dikosongkan).
  • Hapus = benar-benar hilang dari daftar (dicatat `deleted_at` untuk jejak). Dulu "hapus" hanya
    menonaktifkan, lalu pengumuman muncul lagi sebagai "Nonaktif" padahal pesan "berhasil dihapus".
  • Nama pembuat disimpan saat dibuat (dulu hanya dicari di data karyawan → kosong untuk akun non-karyawan).
  • Tanggal berakhir tidak boleh sebelum tanggal mulai; jenis harus salah satu yang dikenal.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from database import get_db
from auth import require_auth
import uuid

router = APIRouter(prefix="/api/announcements", tags=["announcements"])

PERAN_KELOLA = ["superadmin", "admin", "owner", "hr", "hr_manager", "staff_hr"]
JENIS = ("info", "success", "warning", "urgent")
TIDAK_DIHAPUS = {"deleted_at": None}

# ─── MODELS ──────────────────────────────────────────────────────────────────

class AnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    type: str = Field(default="info")  # info, success, warning, urgent
    priority: int = Field(default=0, ge=0, le=10)  # 0 = biasa, 10 = paling atas
    target_portals: List[str] = Field(default_factory=lambda: ["all"])  # ["all"] atau ["production", "hr", ...]
    is_active: bool = Field(default=True)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    created_by: Optional[str] = None

class AnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    type: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=0, le=10)
    target_portals: Optional[List[str]] = None
    is_active: Optional[bool] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

class AnnouncementResponse(BaseModel):
    id: str
    title: str
    content: str
    type: str
    priority: int
    target_portals: List[str]
    is_active: bool
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# ─── BANTUAN ─────────────────────────────────────────────────────────────────

def _utc(v):
    """Datetime dari Mongo (naif, sebenarnya UTC) → berzona UTC, supaya JSON membawa +00:00.
    8 Nov 2026: memakai helper bersama `utils.waktu.mongo_utc` (juga dipakai log aktivitas, pengguna, dll.)."""
    from utils.waktu import mongo_utc
    return mongo_utc(v)


def _require_kelola(user: dict):
    if (user.get("role") or "").lower() not in PERAN_KELOLA:
        raise HTTPException(status_code=403, detail="Hanya tim SDM yang boleh mengelola pengumuman.")


def _cek_isi(jenis, mulai, akhir, target):
    if jenis is not None and jenis not in JENIS:
        raise HTTPException(status_code=400, detail="Jenis pengumuman tidak dikenal.")
    if mulai and akhir and _utc(akhir) < _utc(mulai):
        raise HTTPException(status_code=400, detail="Tanggal berakhir tidak boleh sebelum tanggal mulai.")
    if target is not None and len(target) == 0:
        raise HTTPException(status_code=400, detail="Pilih minimal satu portal tujuan.")


async def _nama_pembuat(db, doc: dict) -> Optional[str]:
    if doc.get("created_by_name"):
        return doc["created_by_name"]
    uid = doc.get("created_by")
    if not uid:
        return None
    emp = await db.rahaza_employees.find_one({"id": uid}, {"_id": 0, "name": 1})
    if emp and emp.get("name"):
        return emp["name"]
    usr = await db.users.find_one({"$or": [{"id": uid}, {"email": uid}]}, {"_id": 0, "name": 1})
    return (usr or {}).get("name")


async def _rapikan(db, doc: dict) -> dict:
    doc = {k: v for k, v in doc.items() if k != "_id"}
    for k in ("start_date", "end_date", "created_at", "updated_at"):
        doc[k] = _utc(doc.get(k))
    doc["created_by_name"] = await _nama_pembuat(db, doc)
    return doc


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@router.get("/active", response_model=List[AnnouncementResponse])
async def get_active_announcements(
    request: Request,
    portal: Optional[str] = Query(None, description="Saring per portal (opsional)"),
    db=Depends(get_db),
    current_user: dict = Depends(require_auth)
):
    """Pengumuman yang sedang tampil: aktif, belum dihapus, dan hari ini di dalam periode (bila diisi).
    `portal` → hanya yang ditujukan ke semua portal atau ke portal itu."""
    now = datetime.now(timezone.utc)
    date_filter = {
        "$or": [
            {"start_date": None, "end_date": None},
            {"start_date": {"$lte": now}, "end_date": None},
            {"start_date": None, "end_date": {"$gte": now}},
            {"start_date": {"$lte": now}, "end_date": {"$gte": now}},
        ]
    }
    rows = await db.announcements.find({"is_active": True, **TIDAK_DIHAPUS, **date_filter}) \
        .sort("priority", -1).to_list(length=100)
    if portal:
        rows = [a for a in rows
                if "all" in a.get("target_portals", ["all"]) or portal in a.get("target_portals", [])]
    return [await _rapikan(db, a) for a in rows]


@router.get("/all", response_model=List[AnnouncementResponse])
async def get_all_announcements(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    is_active: Optional[bool] = Query(None),
    db=Depends(get_db),
    current_user: dict = Depends(require_auth)
):
    """Semua pengumuman yang belum dihapus (untuk Portal SDM), terbaru dulu."""
    _require_kelola(current_user)
    query = dict(TIDAK_DIHAPUS)
    if is_active is not None:
        query["is_active"] = is_active
    rows = await db.announcements.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
    return [await _rapikan(db, a) for a in rows]


@router.get("/{announcement_id}", response_model=AnnouncementResponse)
async def get_announcement(
    request: Request,
    announcement_id: str,
    db=Depends(get_db),
    current_user: dict = Depends(require_auth)
):
    doc = await db.announcements.find_one({"id": announcement_id, **TIDAK_DIHAPUS}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Pengumuman tidak ditemukan.")
    return await _rapikan(db, doc)


@router.post("/", response_model=AnnouncementResponse, status_code=201)
async def create_announcement(
    request: Request,
    data: AnnouncementCreate,
    db=Depends(get_db),
    current_user: dict = Depends(require_auth)
):
    _require_kelola(current_user)
    _cek_isi(data.type, data.start_date, data.end_date, data.target_portals)
    now = datetime.now(timezone.utc)
    doc = {
        "id": str(uuid.uuid4()),
        "title": data.title.strip(),
        "content": data.content.strip(),
        "type": data.type,
        "priority": data.priority,
        "target_portals": data.target_portals,
        "is_active": data.is_active,
        "start_date": data.start_date,
        "end_date": data.end_date,
        "created_by": (current_user.get("employee_id") or current_user.get("id")
                       or current_user.get("email") or "system"),
        "created_by_name": current_user.get("name") or current_user.get("full_name"),
        "created_at": now,
        "updated_at": None,
        "deleted_at": None,
    }
    await db.announcements.insert_one(dict(doc))
    return await _rapikan(db, doc)


@router.put("/{announcement_id}", response_model=AnnouncementResponse)
async def update_announcement(
    request: Request,
    announcement_id: str,
    data: AnnouncementUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(require_auth)
):
    _require_kelola(current_user)
    existing = await db.announcements.find_one({"id": announcement_id, **TIDAK_DIHAPUS})
    if not existing:
        raise HTTPException(status_code=404, detail="Pengumuman tidak ditemukan.")
    dikirim = data.model_dump(exclude_unset=True)
    # Tanggal boleh dikosongkan (null = tanpa batas); isian lain yang null diabaikan.
    update_data = {k: v for k, v in dikirim.items() if v is not None or k in ("start_date", "end_date")}
    mulai = update_data.get("start_date", existing.get("start_date"))
    akhir = update_data.get("end_date", existing.get("end_date"))
    _cek_isi(update_data.get("type"), mulai, akhir, update_data.get("target_portals"))
    if update_data:
        update_data["updated_at"] = datetime.now(timezone.utc)
        await db.announcements.update_one({"id": announcement_id}, {"$set": update_data})
    updated = await db.announcements.find_one({"id": announcement_id}, {"_id": 0})
    return await _rapikan(db, updated)


@router.delete("/{announcement_id}", status_code=204)
async def delete_announcement(
    request: Request,
    announcement_id: str,
    db=Depends(get_db),
    current_user: dict = Depends(require_auth)
):
    """Hapus pengumuman: hilang dari daftar dan dari papan (jejak `deleted_at` tetap tersimpan)."""
    _require_kelola(current_user)
    now = datetime.now(timezone.utc)
    result = await db.announcements.update_one(
        {"id": announcement_id, **TIDAK_DIHAPUS},
        {"$set": {"is_active": False, "deleted_at": now, "deleted_by": current_user.get("id"), "updated_at": now}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pengumuman tidak ditemukan.")
    return None


@router.post("/{announcement_id}/toggle", response_model=AnnouncementResponse)
async def toggle_announcement_status(
    request: Request,
    announcement_id: str,
    db=Depends(get_db),
    current_user: dict = Depends(require_auth)
):
    """Aktifkan / nonaktifkan pengumuman tanpa menghapusnya."""
    _require_kelola(current_user)
    existing = await db.announcements.find_one({"id": announcement_id, **TIDAK_DIHAPUS})
    if not existing:
        raise HTTPException(status_code=404, detail="Pengumuman tidak ditemukan.")
    await db.announcements.update_one(
        {"id": announcement_id},
        {"$set": {"is_active": not existing.get("is_active", True), "updated_at": datetime.now(timezone.utc)}}
    )
    updated = await db.announcements.find_one({"id": announcement_id}, {"_id": 0})
    return await _rapikan(db, updated)
