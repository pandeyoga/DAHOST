"""Portal Saya › Jadwal Shift — jadwal sendiri, ganti/tukar shift, jawaban rekan, persetujuan atasan (Tahap C audit HR).

Prefix /api/portal/shift (Portal Saya terbuka untuk semua karyawan internal; kepemilikan dijaga di sini dan di
`core/shift_permintaan.py`, sama seperti endpoint swalayan Portal Saya lainnya):
  GET  /jadwal-saya?hari=14                 shift berlaku per hari mulai hari ini (+ libur/cuti)
  GET  /rekan?tanggal=                      rekan SEDEPARTEMEN + shift mereka pada tanggal itu (untuk tukar)
  GET  /permintaan                          {milik_saya, sebagai_rekan, perlu_persetujuan_saya}
  POST /permintaan {jenis, tanggal, shift_id?, rekan_employee_id?, alasan}
  POST /permintaan/{id}/batalkan            pemohon, selama belum diputus
  POST /permintaan/{id}/rekan {setuju, catatan}
  POST /permintaan/{id}/atasan {setujui, catatan}   hanya akun atasan langsung pemohon
Tahap SDM: `routes/dewi_shift_scheduler.py` (POST /api/hr/shift-scheduler/permintaan/{id}/putuskan).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auth import require_auth
from core import shift_permintaan as sp
from core import shift_roster as sr
from database import get_db
from utils.waktu import today_wib

router = APIRouter(prefix="/api/portal/shift", tags=["portal-shift"])


class PermintaanModel(BaseModel):
    jenis: str
    tanggal: str
    alasan: str
    shift_id: Optional[str] = None
    rekan_employee_id: Optional[str] = None


class JawabanModel(BaseModel):
    setuju: Optional[bool] = None
    setujui: Optional[bool] = None
    catatan: str = ""

    @property
    def ya(self) -> bool:
        return bool(self.setuju if self.setuju is not None else self.setujui)


def _galat(e: Exception) -> HTTPException:
    return HTTPException(getattr(e, "status", 400), getattr(e, "pesan", str(e)))


def _shift_publik(s: Optional[dict]) -> Optional[dict]:
    if not s:
        return None
    return {"id": s["id"], "kode": s["kode"], "nama": s["nama"], "mulai": s["mulai"], "selesai": s["selesai"],
            "warna": s["warna"]}


@router.get("/jadwal-saya")
async def jadwal_saya(request: Request, hari: int = 14):
    user = await require_auth(request)
    db = get_db()
    try:
        emp = await sp._karyawan_saya(db, user)
    except sp.GalatPermintaan as e:
        raise _galat(e)
    n = max(1, min(int(hari or 14), 42))
    mulai = today_wib()
    tanggal = [(mulai + timedelta(days=i)).isoformat() for i in range(n)]
    shifts = await sr.muat_shift(db)
    sel = (await sr.sel_berlaku(db, [emp], tanggal, shifts)).get(emp["id"]) or {}
    kunci = await sr.kunci_hari(db, [emp["id"]], tanggal)
    rows = []
    for iso in tanggal:
        c = sel.get(iso) or {}
        s = shifts.get(str(c.get("shift_id"))) if c.get("shift_id") else None
        ck = kunci["cuti"].get((emp["id"], iso))
        lib = sr.libur_hari(kunci, iso)
        if ck and not ck["setengah"]:
            s = None
        elif lib and not (s and c.get("sumber") in ("jadwal", "draf")):
            s = None
        rows.append({"date": iso, "label": sr.label_tgl(iso), "hari_ini": iso == tanggal[0],
                     "shift": _shift_publik(s), "sumber": c.get("sumber") if s else None,
                     "keterangan": (ck or {}).get("label") or (lib if not s else None) or
                     ("Libur menurut jadwal" if c.get("libur_jadwal") else None)})
    return {"employee_id": emp["id"], "nama": emp.get("name"), "departemen": emp.get("department"), "hari": rows}


@router.get("/rekan")
async def rekan_tukar(request: Request, tanggal: str):
    """Rekan satu departemen (aktif, punya akun, tidak cuti) dan shift mereka pada `tanggal` — pilihan tukar."""
    user = await require_auth(request)
    db = get_db()
    try:
        emp = await sp._karyawan_saya(db, user)
        iso = sr.tgl(tanggal).isoformat()
    except (sp.GalatPermintaan, sr.GalatRoster) as e:
        raise _galat(e)
    if not emp.get("department"):
        return {"tanggal": iso, "rekan": [], "catatan": "Departemen Anda belum diisi di Data Karyawan."}
    rekan = [r for r in await sr.karyawan_lingkup(db, departemen=emp["department"]) if r["id"] != emp["id"]]
    shifts = await sr.muat_shift(db)
    sel = await sr.sel_berlaku(db, rekan, [iso], shifts)
    kunci = await sr.kunci_hari(db, [r["id"] for r in rekan], [iso])
    out = []
    for r in rekan:
        ck = kunci["cuti"].get((r["id"], iso))
        if ck and not ck["setengah"]:
            continue
        sid = ((sel.get(r["id"]) or {}).get(iso) or {}).get("shift_id")
        out.append({"employee_id": r["id"], "nama": r.get("name") or r.get("employee_code"),
                    "shift": _shift_publik(shifts.get(str(sid)) if sid else None)})
    return {"tanggal": iso, "rekan": out}


@router.get("/permintaan")
async def permintaan_saya(request: Request):
    user = await require_auth(request)
    return await sp.daftar_saya(get_db(), user)


@router.post("/permintaan")
async def ajukan(request: Request, body: PermintaanModel):
    user = await require_auth(request)
    try:
        out = await sp.buat(get_db(), user, body.dict(), today=today_wib())
    except (sp.GalatPermintaan, sr.GalatRoster) as e:
        raise _galat(e)
    tahap = sp.LABEL_STATUS.get(out["status"], out["status"]).lower()
    return {"success": True, "data": out, "message": f"Permintaan terkirim ({tahap})."}


@router.post("/permintaan/{permintaan_id}/batalkan")
async def batalkan(request: Request, permintaan_id: str):
    user = await require_auth(request)
    try:
        out = await sp.batalkan(get_db(), user, permintaan_id)
    except sp.GalatPermintaan as e:
        raise _galat(e)
    return {"success": True, "data": out, "message": "Permintaan dibatalkan."}


@router.post("/permintaan/{permintaan_id}/rekan")
async def jawab_rekan(request: Request, permintaan_id: str, body: JawabanModel):
    user = await require_auth(request)
    try:
        out = await sp.tanggapi_rekan(get_db(), user, permintaan_id, body.ya, body.catatan)
    except sp.GalatPermintaan as e:
        raise _galat(e)
    return {"success": True, "data": out, "message": "Jawaban terkirim."}


@router.post("/permintaan/{permintaan_id}/atasan")
async def putus_atasan(request: Request, permintaan_id: str, body: JawabanModel):
    user = await require_auth(request)
    try:
        out = await sp.putuskan_atasan(get_db(), user, permintaan_id, body.ya, body.catatan)
    except sp.GalatPermintaan as e:
        raise _galat(e)
    return {"success": True, "data": out,
            "message": "Disetujui, diteruskan ke SDM." if body.ya else "Permintaan ditolak."}
