"""Jadwal shift — roster kalender, pola rotasi, salin minggu, deteksi bentrok, permintaan shift (SDM).

Tahap C audit HR (9 Nov 2026) — menggantikan "Jadwal otomatis" Session 17 yang tidak pernah bisa jalan (H7: filter
`status: active`, jam mingguan tidak pernah direset, istirahat dihitung dari tengah malam, cuti/libur diabaikan,
entri tanpa `shift_id`) dan "Pola jadwal" (`rahaza_shift_templates`, master shift KEDUA yang menduplikasi Daftar
shift — dipensiunkan). Aturan jadwal ada di `core/shift_roster.py`; permintaan ganti/tukar di
`core/shift_permintaan.py`.

Prefix /api/hr/shift-scheduler (modul "Shift & Penjadwalan", `data/module_catalog.py`):
  Pola rotasi   GET /pola · POST /pola · PUT /pola/{id} · DELETE /pola/{id} (nonaktif)
  Jadwal        GET /schedules · GET /schedules/pratinjau (susun TANPA menyimpan) · POST /schedules (draf)
                GET /schedules/{id} · GET /schedules/{id}/bentrok · PATCH /schedules/{id}/sel (ubah sel massal)
                POST /schedules/{id}/salin-minggu · PATCH /schedules/{id}/publish {paksa?}
                POST /schedules/{id}/batalkan (terbit, seluruhnya di masa depan) · DELETE /schedules/{id} (draf)
  Roster        GET /roster (baris karyawan × kolom tanggal; sel cuti/libur terkunci; bentrok)
  Permintaan    GET /permintaan · POST /permintaan/{id}/putuskan (tahap SDM)
  Dipensiunkan  GET /templates (baca saja) · POST /templates & POST /generate → 410 dengan arahan

Izin: menulis = `routes.hr_shifts._require_shift_writer` (HR + manajemen + izin Shift & Penjadwalan); membaca
jadwal/roster karyawan lain = `can_view_all_employees` (audit P1 — dulu cukup login).
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import log_activity, require_auth
from core import shift_permintaan as sp
from core import shift_roster as sr
from core.authz import only  # T-01 2.3
from core.roles import HR_ROLES  # T-01 2.3
from database import get_db
# 2026-11-08 (Asisten AI Tahap B — celah izin): membuat & menerbitkan jadwal = penugasan shift karyawan
# (dibaca aturan absen). Gerbang penulis SATU dengan `routes.hr_shifts._require_shift_writer`.
from routes.hr_shifts import _require_shift_writer, _require_view_all
from utils.waktu import today_wib

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/hr/shift-scheduler", tags=["shift-scheduler"])

PESAN_PENSIUN = ("Pola jadwal lama sudah dipensiunkan karena menduplikasi Daftar shift. Atur jam shift di "
                 "Shift › Daftar shift, lalu susun jadwal dari Shift › Pola rotasi atau Roster.")
STATUS_JADWAL = ("draft", "published", "dibatalkan")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _galat(e: Exception) -> HTTPException:
    if isinstance(e, (sr.GalatRoster, sp.GalatPermintaan)):
        return HTTPException(e.status, e.pesan)
    return HTTPException(400, str(e))


def _nama(user: dict) -> str:
    return user.get("full_name") or user.get("name") or user.get("email") or ""


# ── Model ───────────────────────────────────────────────────────────────────
class PolaModel(BaseModel):
    nama: str = Field(..., min_length=2, max_length=80)
    keterangan: str = ""
    urutan: List[Optional[str]]          # per hari: id shift atau null/"LIBUR"; kelipatan 7


class JadwalBaruModel(BaseModel):
    judul: str = ""
    start_date: str
    end_date: str
    department: Optional[str] = None
    location_id: Optional[str] = None
    employee_ids: Optional[List[str]] = None
    cara: str = "pola"                   # pola | shift | berlaku | salin
    pola_id: Optional[str] = None
    mulai_pola: Optional[str] = None
    shift_id: Optional[str] = None
    salin_dari: Optional[str] = None
    isi_libur: bool = False


class UbahSel(BaseModel):
    employee_id: str
    date: str
    shift_id: Optional[str] = None       # null / "LIBUR" = libur


class UbahSelModel(BaseModel):
    perubahan: List[UbahSel]
    isi_libur: bool = False


class SalinMingguModel(BaseModel):
    dari: str                            # tanggal di minggu sumber
    ke: str                              # tanggal di minggu tujuan
    employee_ids: Optional[List[str]] = None
    isi_libur: bool = False


class TerbitModel(BaseModel):
    paksa: bool = False


class PutusanModel(BaseModel):
    setujui: bool
    catatan: str = ""


# ── Pola rotasi ─────────────────────────────────────────────────────────────
def _pola_publik(doc: dict, shifts: dict) -> dict:
    d = {k: v for k, v in doc.items() if k != "_id"}
    d["minggu"] = len(d.get("urutan") or []) // 7
    d["ringkas"] = [{"hari": i, "shift_id": sid, "kode": (shifts.get(str(sid)) or {}).get("kode") if sid else None}
                    for i, sid in enumerate(d.get("urutan") or [])]
    return d


@router.get("/pola")
async def daftar_pola(request: Request, semua: bool = False):
    await require_auth(request)
    db = get_db()
    q = {} if semua else {"aktif": {"$ne": False}}
    shifts = await sr.muat_shift(db)
    rows = await db.hr_shift_pola.find(q, {"_id": 0}).sort("nama", 1).to_list(200)
    return {"success": True, "data": [_pola_publik(r, shifts) for r in rows]}


@router.post("/pola")
async def buat_pola(request: Request, body: PolaModel):
    user = await require_auth(request)
    _require_shift_writer(user)
    db = get_db()
    shifts = await sr.muat_shift(db)
    try:
        urutan = sr.periksa_urutan(body.urutan, shifts)
    except sr.GalatRoster as e:
        raise _galat(e)
    nama = " ".join(body.nama.split())
    if await db.hr_shift_pola.find_one({"nama": nama, "aktif": {"$ne": False}}, {"_id": 0, "id": 1}):
        raise HTTPException(400, f"Pola '{nama}' sudah ada.")
    doc = {"id": str(uuid.uuid4()), "nama": nama, "keterangan": body.keterangan.strip()[:300], "urutan": urutan,
           "aktif": True, "created_at": _now(), "created_by": user.get("id"), "updated_at": _now()}
    await db.hr_shift_pola.insert_one(dict(doc))
    await log_activity(str(user.get("id") or ""), _nama(user), "create_shift_pola", "hr_shift_pola", nama)
    return {"success": True, "data": _pola_publik(doc, shifts), "message": f"Pola {nama} dibuat."}


@router.put("/pola/{pola_id}")
async def ubah_pola(request: Request, pola_id: str, body: PolaModel):
    user = await require_auth(request)
    _require_shift_writer(user)
    db = get_db()
    lama = await db.hr_shift_pola.find_one({"id": pola_id}, {"_id": 0})
    if not lama:
        raise HTTPException(404, "Pola tidak ditemukan.")
    shifts = await sr.muat_shift(db)
    try:
        urutan = sr.periksa_urutan(body.urutan, shifts)
    except sr.GalatRoster as e:
        raise _galat(e)
    upd = {"nama": " ".join(body.nama.split()), "keterangan": body.keterangan.strip()[:300], "urutan": urutan,
           "updated_at": _now(), "updated_by": user.get("id")}
    await db.hr_shift_pola.update_one({"id": pola_id}, {"$set": upd})
    return {"success": True, "data": _pola_publik({**lama, **upd}, shifts), "message": "Pola disimpan."}


@router.delete("/pola/{pola_id}")
async def hapus_pola(request: Request, pola_id: str, hard: bool = False):
    """Tanpa `hard`: nonaktifkan (perilaku lama). `?hard=true` (10 Nov 2026, owner "master data bisa dihapus"):
    hapus permanen bila belum ada jadwal yang disusun dari pola ini; selain itu 409 (layar menawarkan Nonaktifkan)."""
    user = await require_auth(request)
    _require_shift_writer(user)
    db = get_db()
    if hard:
        from core.hapus_master import hitung_pemakaian, tolak_bila_dipakai
        pola = await db.hr_shift_pola.find_one({"id": pola_id}, {"_id": 0})
        if not pola:
            raise HTTPException(404, "Pola tidak ditemukan.")
        tolak_bila_dipakai("Pola rotasi", pola.get("nama") or "", await hitung_pemakaian(db, [
            ("jadwal shift", "rahaza_schedules", {"pola_id": pola_id}),
        ]))
        await db.hr_shift_pola.delete_one({"id": pola_id})
        await log_activity(str(user.get("id") or ""), _nama(user), "delete_shift_pola", "hr_shift_pola", pola.get("nama") or pola_id)
        return {"success": True, "deleted": True, "message": f"Pola {pola.get('nama') or ''} dihapus."}
    r = await db.hr_shift_pola.update_one({"id": pola_id}, {"$set": {"aktif": False, "updated_at": _now()}})
    if not r.matched_count:
        raise HTTPException(404, "Pola tidak ditemukan.")
    return {"success": True, "message": "Pola dinonaktifkan. Jadwal yang sudah dibuat dari pola ini tidak berubah."}


# ── Pola jadwal lama (dipensiunkan) ─────────────────────────────────────────
@router.get("/templates")
async def list_shift_templates(request: Request):
    """Baca saja (riwayat). Pola jadwal lama dipensiunkan — lihat PESAN_PENSIUN."""
    await require_auth(request)
    db = get_db()
    templates = await db.rahaza_shift_templates.find({}, {"_id": 0}).to_list(length=100)
    return {"success": True, "data": templates, "dipensiunkan": True, "message": PESAN_PENSIUN}


@router.post("/templates")
async def create_shift_template(request: Request):
    await require_auth(request)
    raise HTTPException(410, PESAN_PENSIUN)


@router.delete("/templates/{template_id}", dependencies=only(*HR_ROLES, perm=("hr.attendance.manage", "hr.manage")))  # T-01 2.3
async def delete_shift_template(request: Request, template_id: str):
    await require_auth(request)
    db = get_db()
    result = await db.rahaza_shift_templates.delete_one({"id": template_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Pola jadwal lama tidak ditemukan.")
    return {"success": True, "message": "Pola jadwal lama dihapus."}


@router.post("/generate")
async def generate_schedule(request: Request):
    """Dipensiunkan (H7). Penggantinya: POST /schedules (cara pola/shift/berlaku/salin)."""
    _require_shift_writer(await require_auth(request))
    raise HTTPException(410, "Jadwal otomatis lama dipensiunkan. Pakai Shift › Roster › Susun jadwal "
                             "(dari pola rotasi, satu shift, shift yang berlaku, atau salin minggu).")


# ── Jadwal ──────────────────────────────────────────────────────────────────
async def _susun(db, body: JadwalBaruModel) -> dict:
    """Susun entri draf (tanpa menulis). Return {tanggal, emps, shifts, entri, dilewati, bentrok, pola}."""
    tanggal = sr.rentang(body.start_date, body.end_date)
    emps = await sr.karyawan_lingkup(db, departemen=body.department or None, lokasi=body.location_id or None,
                                     employee_ids=body.employee_ids)
    if not emps:
        raise sr.GalatRoster(400, "Tidak ada karyawan aktif yang cocok dengan pilihan ini.")
    shifts = await sr.muat_shift(db)
    pola = None
    if body.cara == "pola":
        pola = await db.hr_shift_pola.find_one({"id": body.pola_id or "", "aktif": {"$ne": False}}, {"_id": 0})
        if not pola:
            raise sr.GalatRoster(400, "Pilih pola rotasi yang masih aktif.")
    hasil = await sr.susun_entri(db, emps=emps, tanggal=tanggal, shifts=shifts, cara=body.cara, pola=pola,
                                 mulai_pola=body.mulai_pola or body.start_date, shift_id=body.shift_id,
                                 salin_dari=body.salin_dari, isi_libur=body.isi_libur)
    draf = {"id": "__pratinjau__", "shifts": hasil["entri"]}
    sel = await sr.sel_berlaku(db, emps, tanggal, shifts, draf=draf)
    kunci = await sr.kunci_hari(db, [e["id"] for e in emps], tanggal)
    bentrok = sr.cari_bentrok(sel, emps, tanggal, shifts, kunci)
    return {"tanggal": tanggal, "emps": emps, "shifts": shifts, "entri": hasil["entri"], "dilewati": hasil["dilewati"],
            "bentrok": bentrok, "pola": pola}


def _judul_bawaan(body: JadwalBaruModel, pola: Optional[dict]) -> str:
    asal = {"pola": f"pola {pola.get('nama')}" if pola else "pola", "shift": "satu shift",
            "berlaku": "shift yang berlaku", "salin": "salinan minggu"}.get(body.cara, body.cara)
    lingkup = body.department or ("pilihan karyawan" if body.employee_ids else "semua karyawan")
    return f"Jadwal {sr.label_tgl(body.start_date)} – {sr.label_tgl(body.end_date)} · {lingkup} · {asal}"


def _jadwal_ringkas(doc: dict) -> dict:
    d = {k: v for k, v in doc.items() if k not in ("_id", "shifts")}
    d["jumlah_entri"] = len(doc.get("shifts") or [])
    return d


@router.get("/schedules")
async def list_schedules(request: Request, status: Optional[str] = None, jenis: Optional[str] = None,
                         limit: int = Query(100, ge=1, le=500)):
    _require_view_all(await require_auth(request))
    db = get_db()
    query: dict = {}
    if status:
        query["status"] = status
    if jenis:
        query["jenis"] = jenis
    rows = await db.rahaza_schedules.find(query, {"_id": 0}).sort("generated_at", -1).limit(limit).to_list(length=limit)
    return {"success": True, "data": [_jadwal_ringkas(r) for r in rows]}


@router.get("/schedules/pratinjau")
async def pratinjau_jadwal(request: Request, start_date: str, end_date: str, cara: str = "pola",
                           department: Optional[str] = None, location_id: Optional[str] = None,
                           employee_ids: Optional[str] = None, pola_id: Optional[str] = None,
                           mulai_pola: Optional[str] = None, shift_id: Optional[str] = None,
                           salin_dari: Optional[str] = None, isi_libur: bool = False):
    """Susun jadwal TANPA menyimpan: cakupan per tanggal per shift, sel yang dilewati (cuti), dan bentrok.
    Dipakai Asisten AI ("bantu susun draf shift") sebelum kartu konfirmasi, dan bisa dipakai layar."""
    _require_view_all(await require_auth(request))
    db = get_db()
    body = JadwalBaruModel(start_date=start_date, end_date=end_date, cara=cara, department=department,
                           location_id=location_id, pola_id=pola_id, mulai_pola=mulai_pola, shift_id=shift_id,
                           salin_dari=salin_dari, isi_libur=isi_libur,
                           employee_ids=[x for x in (employee_ids or "").split(",") if x] if employee_ids else None)
    try:
        h = await _susun(db, body)
    except sr.GalatRoster as e:
        raise _galat(e)
    cakupan: dict = {}
    for e in h["entri"]:
        if e.get("libur"):
            continue
        cakupan.setdefault(e["date"], {}).setdefault(e.get("shift_code") or "?", 0)
        cakupan[e["date"]][e.get("shift_code") or "?"] += 1
    return {"success": True, "data": {
        "judul": _judul_bawaan(body, h["pola"]), "start_date": h["tanggal"][0], "end_date": h["tanggal"][-1],
        "karyawan": len(h["emps"]), "metadata": sr.ringkas_jadwal(h["entri"]),
        "cakupan": [{"date": t, "tanggal": sr.label_tgl(t), "per_shift": cakupan.get(t, {})} for t in h["tanggal"]],
        "dilewati": h["dilewati"][:200], "bentrok": h["bentrok"][:200], "jumlah_bentrok": sr.hitung_bentrok(h["bentrok"]),
    }}


@router.post("/schedules")
async def buat_jadwal(request: Request, body: JadwalBaruModel):
    """Buat DRAF jadwal (belum berlaku untuk absen sampai diterbitkan)."""
    user = await require_auth(request)
    _require_shift_writer(user)
    db = get_db()
    try:
        h = await _susun(db, body)
    except sr.GalatRoster as e:
        raise _galat(e)
    now = _now()
    doc = {"id": str(uuid.uuid4()), "judul": (body.judul or "").strip()[:160] or _judul_bawaan(body, h["pola"]),
           "jenis": "roster", "start_date": h["tanggal"][0], "end_date": h["tanggal"][-1],
           "department": body.department or None, "location_id": body.location_id or None,
           "employee_ids": [e["id"] for e in h["emps"]], "cara": body.cara, "pola_id": body.pola_id,
           "shifts": h["entri"], "metadata": sr.ringkas_jadwal(h["entri"]), "status": "draft",
           "generated_at": now, "generated_by": user.get("id"), "generated_by_name": _nama(user), "updated_at": now}
    await db.rahaza_schedules.insert_one(dict(doc))   # dibaca core.attendance_rules setelah TERBIT
    await log_activity(str(user.get("id") or ""), _nama(user), "create_schedule", "rahaza_schedules", doc["judul"])
    return {"success": True, "data": {**_jadwal_ringkas(doc), "bentrok": h["bentrok"][:200],
                                      "jumlah_bentrok": sr.hitung_bentrok(h["bentrok"]), "dilewati": h["dilewati"][:200]},
            "message": "Jadwal dibuat sebagai draf. Periksa roster dan bentrok, lalu terbitkan."}


async def _jadwal(db, schedule_id: str) -> dict:
    doc = await db.rahaza_schedules.find_one({"id": schedule_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Jadwal tidak ditemukan.")
    return doc


async def _bentrok_jadwal(db, doc: dict) -> dict:
    if not (doc.get("start_date") and doc.get("end_date")):     # jadwal lama tanpa rentang
        return {"bentrok": [], "jumlah": sr.hitung_bentrok([])}
    tanggal = sr.rentang(doc["start_date"], doc["end_date"], maks=sr.MAKS_HARI * 2)
    ids = doc.get("employee_ids") or sorted({e.get("employee_id") for e in doc.get("shifts") or []})
    emps = await sr.karyawan_lingkup(db, employee_ids=ids)
    shifts = await sr.muat_shift(db)
    sel = await sr.sel_berlaku(db, emps, tanggal, shifts, draf=doc if doc.get("status") == "draft" else None)
    kunci = await sr.kunci_hari(db, [e["id"] for e in emps], tanggal)
    # hanya sel MILIK jadwal ini yang dinilai (sel lain di roster bukan tanggung jawab jadwal ini)
    milik = {(e.get("employee_id"), e.get("date")) for e in doc.get("shifts") or []}
    semua = sr.cari_bentrok(sel, emps, tanggal, shifts, kunci)
    bentrok = [b for b in semua if (b["employee_id"], b["date"]) in milik]
    return {"bentrok": bentrok, "jumlah": sr.hitung_bentrok(bentrok)}


@router.get("/schedules/{schedule_id}")
async def get_schedule(request: Request, schedule_id: str):
    _require_view_all(await require_auth(request))
    db = get_db()
    return {"success": True, "data": await _jadwal(db, schedule_id)}


@router.get("/schedules/{schedule_id}/bentrok")
async def bentrok_jadwal(request: Request, schedule_id: str):
    _require_view_all(await require_auth(request))
    db = get_db()
    return {"success": True, "data": await _bentrok_jadwal(db, await _jadwal(db, schedule_id))}


def _boleh_ubah_tanggal(doc: dict, iso: str, today: str) -> Optional[str]:
    """None bila sel boleh diubah; selain itu alasannya. Draf: semua tanggal. Terbit: hanya hari ini ke depan."""
    if doc.get("status") == "draft":
        return None
    if doc.get("status") == "published":
        return None if iso >= today else "tanggal sudah lewat (jadwal terbit hanya bisa diubah untuk hari ini ke depan)"
    return "jadwal sudah dibatalkan"


@router.patch("/schedules/{schedule_id}/sel")
async def ubah_sel(request: Request, schedule_id: str, body: UbahSelModel):
    """Ubah banyak sel sekaligus (penugasan massal di roster: pilih baris × tanggal → shift). Sel cuti disetujui
    dan (kecuali `isi_libur`) hari libur kalender dilewati dengan alasan."""
    user = await require_auth(request)
    _require_shift_writer(user)
    db = get_db()
    doc = await _jadwal(db, schedule_id)
    if doc.get("jenis") == "perubahan":
        raise HTTPException(409, "Jadwal perubahan dari permintaan shift tidak diubah langsung.")
    if not body.perubahan:
        raise HTTPException(400, "Tidak ada sel yang diubah.")
    if len(body.perubahan) > 5000:
        raise HTTPException(400, "Paling banyak 5.000 sel sekali ubah.")
    today = today_wib().isoformat()
    shifts = await sr.muat_shift(db)
    ids = sorted({p.employee_id for p in body.perubahan})
    emps = {e["id"]: e for e in await sr.karyawan_lingkup(db, employee_ids=ids)}
    tanggal = sorted({p.date[:10] for p in body.perubahan})
    try:
        kunci = await sr.kunci_hari(db, ids, sr.rentang(tanggal[0], tanggal[-1], maks=400))
    except sr.GalatRoster as e:
        raise _galat(e)
    peta = {(e.get("employee_id"), e.get("date")): i for i, e in enumerate(doc.get("shifts") or [])}
    entri = list(doc.get("shifts") or [])
    dilewati, diubah = [], 0
    for p in body.perubahan:
        iso = p.date[:10]
        alasan = None
        emp = emps.get(p.employee_id)
        if not emp:
            alasan = "karyawan tidak aktif"
        elif not (doc["start_date"] <= iso <= doc["end_date"]):
            alasan = "di luar rentang jadwal"
        else:
            alasan = _boleh_ubah_tanggal(doc, iso, today)
        s = None
        if not alasan and p.shift_id not in (None, "", sr.LIBUR):
            s = shifts.get(str(p.shift_id))
            if not s or not s["aktif"]:
                alasan = "shift tidak aktif"
        if not alasan and s:
            ck = kunci["cuti"].get((p.employee_id, iso))
            if ck and not ck["setengah"]:
                alasan = ck["label"].lower() + " disetujui"
            elif iso in kunci["libur"] and not body.isi_libur:
                alasan = f"hari libur ({kunci['libur'][iso]})"
        if alasan:
            dilewati.append({"employee_id": p.employee_id, "date": iso, "alasan": alasan})
            continue
        e = sr.entri_jadwal(emp, iso, s)
        if (p.employee_id, iso) in peta:
            entri[peta[(p.employee_id, iso)]] = e
        else:
            peta[(p.employee_id, iso)] = len(entri)
            entri.append(e)
        diubah += 1
    if diubah:
        ids_doc = sorted(set(doc.get("employee_ids") or []) | {p.employee_id for p in body.perubahan if p.employee_id in emps})
        await db.rahaza_schedules.update_one({"id": schedule_id}, {"$set": {
            "shifts": entri, "metadata": sr.ringkas_jadwal(entri), "employee_ids": ids_doc, "updated_at": _now(),
            "updated_by": user.get("id")}})
    pesan = f"{diubah} sel diubah." + (f" {len(dilewati)} sel dilewati." if dilewati else "")
    return {"success": True, "data": {"diubah": diubah, "dilewati": dilewati[:200]}, "message": pesan}


@router.post("/schedules/{schedule_id}/salin-minggu")
async def salin_minggu(request: Request, schedule_id: str, body: SalinMingguModel):
    """Salin isi satu minggu (Senin–Minggu) ke minggu lain di jadwal yang sama; rentang jadwal diperpanjang bila
    minggu tujuan di luar rentang. Sumber = shift yang BERLAKU di roster (draf ini, jadwal terbit, penugasan)."""
    user = await require_auth(request)
    _require_shift_writer(user)
    db = get_db()
    doc = await _jadwal(db, schedule_id)
    if doc.get("status") != "draft":
        raise HTTPException(409, "Salin minggu hanya untuk jadwal draf. Buat jadwal baru dengan cara Salin minggu "
                                 "untuk mengubah jadwal yang sudah terbit.")
    try:
        src, dst = sr.senin(body.dari), sr.senin(body.ke)
    except sr.GalatRoster as e:
        raise _galat(e)
    if src == dst:
        raise HTTPException(400, "Minggu sumber dan tujuan sama.")
    ids = body.employee_ids or doc.get("employee_ids") or sorted({e.get("employee_id") for e in doc.get("shifts") or []})
    emps = await sr.karyawan_lingkup(db, employee_ids=ids)
    shifts = await sr.muat_shift(db)
    src_tgl = [(src + timedelta(days=i)).isoformat() for i in range(7)]
    dst_tgl = [(dst + timedelta(days=i)).isoformat() for i in range(7)]
    mulai, akhir = min(doc["start_date"], dst_tgl[0]), max(doc["end_date"], dst_tgl[-1])
    try:
        sr.rentang(mulai, akhir)
    except sr.GalatRoster as e:
        raise _galat(e)
    sel = await sr.sel_berlaku(db, emps, src_tgl, shifts, draf=doc)
    kunci = await sr.kunci_hari(db, [e["id"] for e in emps], dst_tgl)
    peta = {(e.get("employee_id"), e.get("date")): i for i, e in enumerate(doc.get("shifts") or [])}
    entri = list(doc.get("shifts") or [])
    dilewati, disalin = [], 0
    for emp in emps:
        for i, iso in enumerate(dst_tgl):
            c = (sel.get(emp["id"]) or {}).get(src_tgl[i]) or {}
            s = shifts.get(str(c.get("shift_id"))) if c.get("shift_id") and not c.get("libur_jadwal") else None
            ck = kunci["cuti"].get((emp["id"], iso))
            if s and ck and not ck["setengah"]:
                dilewati.append({"employee_id": emp["id"], "date": iso, "alasan": ck["label"].lower() + " disetujui"})
                continue
            if s and iso in kunci["libur"] and not body.isi_libur:
                dilewati.append({"employee_id": emp["id"], "date": iso, "alasan": f"hari libur ({kunci['libur'][iso]})"})
                s = None
            e = sr.entri_jadwal(emp, iso, s)
            if (emp["id"], iso) in peta:
                entri[peta[(emp["id"], iso)]] = e
            else:
                peta[(emp["id"], iso)] = len(entri)
                entri.append(e)
            disalin += 1
    await db.rahaza_schedules.update_one({"id": schedule_id}, {"$set": {
        "shifts": entri, "metadata": sr.ringkas_jadwal(entri), "start_date": mulai, "end_date": akhir,
        "employee_ids": sorted(set(doc.get("employee_ids") or []) | {e["id"] for e in emps}),
        "updated_at": _now(), "updated_by": user.get("id")}})
    return {"success": True, "data": {"disalin": disalin, "dilewati": dilewati[:200], "start_date": mulai, "end_date": akhir},
            "message": f"Minggu {sr.label_tgl(src.isoformat())} disalin ke minggu {sr.label_tgl(dst.isoformat())}."}


@router.patch("/schedules/{schedule_id}/publish")
async def publish_schedule(request: Request, schedule_id: str, body: Optional[TerbitModel] = None):
    """Terbitkan jadwal (mulai berlaku untuk absen & terlambat). Bentrok BERAT (dijadwalkan saat cuti disetujui)
    menahan penerbitan kecuali `paksa: true`; peringatan tidak menahan."""
    user = await require_auth(request)
    _require_shift_writer(user)
    db = get_db()
    doc = await _jadwal(db, schedule_id)
    if doc.get("status") != "draft":
        raise HTTPException(409, "Hanya jadwal draf yang bisa diterbitkan.")
    b = await _bentrok_jadwal(db, doc)
    if b["jumlah"].get("berat") and not (body and body.paksa):
        raise HTTPException(409, {"message": f"Ada {b['jumlah']['berat']} jadwal yang jatuh pada cuti/izin yang sudah "
                                             "disetujui. Ubah selnya, atau terbitkan tetap (sel itu tidak berlaku).",
                                  "bentrok": b["bentrok"][:100], "jumlah": b["jumlah"]})
    now = _now()
    await db.rahaza_schedules.update_one({"id": schedule_id, "status": "draft"}, {"$set": {
        "status": "published", "published_at": now, "published_by": user.get("id"),
        "published_by_name": _nama(user), "bentrok_saat_terbit": b["jumlah"]}})
    await log_activity(str(user.get("id") or ""), _nama(user), "publish_schedule", "rahaza_schedules", schedule_id)
    return {"success": True, "message": "Jadwal diterbitkan dan mulai dipakai absensi.", "data": {"jumlah_bentrok": b["jumlah"]}}


@router.post("/schedules/{schedule_id}/batalkan")
async def batalkan_jadwal(request: Request, schedule_id: str):
    """Tarik jadwal TERBIT yang seluruhnya masih di masa depan (belum ada absen yang memakainya)."""
    user = await require_auth(request)
    _require_shift_writer(user)
    db = get_db()
    doc = await _jadwal(db, schedule_id)
    if doc.get("status") != "published":
        raise HTTPException(409, "Hanya jadwal terbit yang bisa ditarik.")
    if doc["start_date"] <= today_wib().isoformat():
        raise HTTPException(409, "Jadwal ini sudah mulai berlaku. Ubah sel hari ini ke depan, atau buat jadwal baru.")
    await db.rahaza_schedules.update_one({"id": schedule_id}, {"$set": {
        "status": "dibatalkan", "dibatalkan_at": _now(), "dibatalkan_by": user.get("id")}})
    return {"success": True, "message": "Jadwal ditarik dan tidak berlaku lagi."}


@router.delete("/schedules/{schedule_id}", dependencies=only(*HR_ROLES, perm=("hr.attendance.manage", "hr.manage")))  # T-01 2.3
async def delete_schedule(request: Request, schedule_id: str):
    await require_auth(request)
    db = get_db()
    doc = await _jadwal(db, schedule_id)
    if doc.get("status") != "draft":
        raise HTTPException(409, "Jadwal terbit tidak dihapus. Tarik jadwal yang belum berlaku, atau ubah selnya.")
    await db.rahaza_schedules.delete_one({"id": schedule_id, "status": "draft"})
    return {"success": True, "message": "Draf jadwal dihapus."}


# ── Roster kalender ─────────────────────────────────────────────────────────
@router.get("/roster")
async def roster(request: Request, dari: str, sampai: str, department: Optional[str] = None,
                 location_id: Optional[str] = None, jadwal_id: Optional[str] = None, q: Optional[str] = None):
    """Roster: baris karyawan × kolom tanggal. Sel = shift yang berlaku (draf `jadwal_id` bila dipilih → jadwal
    terbit → penugasan → shift utama), dengan kunci cuti disetujui / hari libur dan daftar bentrok."""
    _require_view_all(await require_auth(request))
    db = get_db()
    try:
        tanggal = sr.rentang(dari, sampai)
    except sr.GalatRoster as e:
        raise _galat(e)
    draf = None
    if jadwal_id:
        draf = await _jadwal(db, jadwal_id)
        if draf.get("status") != "draft":
            draf = None
    emps = await sr.karyawan_lingkup(db, departemen=department or None, lokasi=location_id or None, cari=q)
    shifts = await sr.muat_shift(db)
    sel = await sr.sel_berlaku(db, emps, tanggal, shifts, draf=draf)
    kunci = await sr.kunci_hari(db, [e["id"] for e in emps], tanggal)
    bentrok = sr.cari_bentrok(sel, emps, tanggal, shifts, kunci)
    if draf:
        milik = {(e.get("employee_id"), e.get("date")) for e in draf.get("shifts") or []}
        bentrok = [b for b in bentrok if (b["employee_id"], b["date"]) in milik]
    tanda = {}
    for b in bentrok:
        k = (b["employee_id"], b["date"])
        if k not in tanda or sr.TINGKAT.index(b["tingkat"]) < sr.TINGKAT.index(tanda[k]):
            tanda[k] = b["tingkat"]
    baris = []
    for e in emps:
        cells = []
        for iso in tanggal:
            c = (sel.get(e["id"]) or {}).get(iso) or {}
            ck = kunci["cuti"].get((e["id"], iso))
            lib = sr.libur_hari(kunci, iso)
            cells.append({
                "t": iso, "s": c.get("shift_id"), "src": c.get("sumber"), "lj": bool(c.get("libur_jadwal")),
                "kunci": "cuti" if ck and not ck["setengah"] else ("libur" if iso in kunci["libur"] else None),
                "ket": (ck or {}).get("label") or lib, "setengah": bool(ck and ck["setengah"]),
                "bentrok": tanda.get((e["id"], iso)),
            })
        baris.append({"id": e["id"], "kode": e.get("employee_code") or "", "nama": e.get("name") or "",
                      "departemen": e.get("department") or "", "lokasi_id": e.get("location_id"), "sel": cells})
    return {"success": True, "data": {
        "tanggal": [{"t": t, "label": sr.label_tgl(t), "libur": sr.libur_hari(kunci, t)} for t in tanggal],
        "shift": [s for s in shifts.values() if s["aktif"]], "karyawan": baris,
        "bentrok": bentrok[:300], "jumlah_bentrok": sr.hitung_bentrok(bentrok),
        "jadwal": _jadwal_ringkas(draf) if draf else None,
    }}


# ── Permintaan ganti/tukar shift — tahap SDM ────────────────────────────────
@router.get("/permintaan")
async def daftar_permintaan(request: Request, status: Optional[str] = "menunggu_hr"):
    _require_view_all(await require_auth(request))
    try:
        return {"success": True, "data": await sp.daftar_hr(get_db(), status)}
    except sp.GalatPermintaan as e:
        raise _galat(e)


@router.post("/permintaan/{permintaan_id}/putuskan")
async def putuskan_permintaan(request: Request, permintaan_id: str, body: PutusanModel):
    user = await require_auth(request)
    _require_shift_writer(user)
    try:
        out = await sp.putuskan_hr(get_db(), user, permintaan_id, body.setujui, body.catatan)
    except sp.GalatPermintaan as e:
        raise _galat(e)
    return {"success": True, "data": out,
            "message": "Permintaan disetujui; jadwal hari itu sudah diubah." if body.setujui else "Permintaan ditolak."}
