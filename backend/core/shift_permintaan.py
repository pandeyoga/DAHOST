"""Permintaan ganti / tukar shift dari Portal Saya (Tahap C audit HR, 9 Nov 2026).

Alur (keputusan Q6: tingkat 1 atasan langsung, lalu HR; atasan kosong → langsung HR):
  ganti  : pemohon memilih shift lain untuk satu tanggal      → menunggu_atasan → menunggu_hr → disetujui
  tukar  : pemohon bertukar shift dengan rekan pada tanggal itu → menunggu_rekan (rekan setuju) → menunggu_atasan
           → menunggu_hr → disetujui
  Ditolak di tahap mana pun → ditolak. Pemohon boleh membatalkan selama belum diputus HR.
Atasan = `rahaza_employees.manager_id` (ID KARYAWAN) → akun login lewat `employee_user_ids` (bukan ID karyawan
sebagai ID akun — kesalahan P4 di notifikasi cuti). Pemisahan tugas: pemohon/rekan tidak memutus permintaannya
sendiri di tahap atasan/HR.

Saat disetujui HR, perubahan ditulis sebagai JADWAL TERBIT baru berjenis `perubahan` (rentang satu tanggal) di
`rahaza_schedules` — jadwal terbit terbaru menang di aturan absen (`core.attendance_rules.resolve_day_shift`),
jadi tidak ada penyimpanan shift kedua. Sebelum ditulis, shift yang berlaku dibaca ulang; bila sudah berubah
sejak diajukan → 409 (tidak ada yang diubah).

Koleksi `hr_shift_requests`: {id, nomor, jenis, status, employee_id, employee_name, employee_code, department,
user_id, tanggal, shift_asal{id,kode,nama,mulai,selesai}, shift_diminta{…}, rekan_employee_id, rekan_name,
rekan_user_ids, rekan_shift_asal{…}, atasan_employee_id, atasan_user_ids, alasan, riwayat[{tahap, keputusan,
oleh, oleh_nama, catatan, waktu}], jadwal_id, created_at, updated_at}
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from core import shift_roster as sr

log = logging.getLogger(__name__)

STATUS = ("menunggu_rekan", "menunggu_atasan", "menunggu_hr", "disetujui", "ditolak", "dibatalkan")
MENUNGGU = ("menunggu_rekan", "menunggu_atasan", "menunggu_hr")
LABEL_STATUS = {"menunggu_rekan": "Menunggu rekan", "menunggu_atasan": "Menunggu atasan",
                "menunggu_hr": "Menunggu SDM", "disetujui": "Disetujui", "ditolak": "Ditolak",
                "dibatalkan": "Dibatalkan"}
LABEL_JENIS = {"ganti": "Ganti shift", "tukar": "Tukar shift"}
MAKS_HARI_DEPAN = 62
PERAN_SDM_KABAR = ("hr", "hr_manager", "manager_hr", "staff_hr")
MAKS_ALASAN = 500


class GalatPermintaan(Exception):
    def __init__(self, status: int, pesan: str):
        super().__init__(pesan)
        self.status = status
        self.pesan = pesan


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ringkas_shift(s: Optional[dict]) -> Optional[dict]:
    if not s:
        return None
    return {"id": s["id"], "kode": s["kode"], "nama": s["nama"], "mulai": s["mulai"], "selesai": s["selesai"],
            "warna": s["warna"]}


def label_shift(s: Optional[dict]) -> str:
    if not s:
        return "libur / belum ada shift"
    return f"{s.get('kode')} ({s.get('mulai')}–{s.get('selesai')})"


async def _karyawan_saya(db, user: dict) -> dict:
    from utils.employee_identity import resolve_my_employee
    emp = await resolve_my_employee(db, user)
    if not emp:
        raise GalatPermintaan(404, "Akun Anda belum ditautkan ke data karyawan. Minta Admin SDM menautkan lewat "
                                   "Data Karyawan › Tautkan akun.")
    return emp


async def _akun(db, employee_id: Optional[str]) -> list:
    from utils.employee_identity import employee_user_ids
    return await employee_user_ids(db, employee_id) if employee_id else []


async def shift_pada(db, emp: dict, iso: str, shifts: dict) -> Optional[dict]:
    sel = await sr.sel_berlaku(db, [emp], [iso], shifts)
    sid = ((sel.get(emp["id"]) or {}).get(iso) or {}).get("shift_id")
    return shifts.get(str(sid)) if sid else None


async def _notif(db, user_ids: list, judul: str, pesan: str, modul: str, rid: str) -> None:
    ids = [u for u in dict.fromkeys(user_ids or []) if u]
    if not ids:
        return
    try:
        from routes.rahaza_notifications import publish_notification
        await publish_notification(db, type_="shift_request", severity="info", title=judul, message=pesan,
                                   link_module=modul, link_id=rid, target_user_ids=ids)
    except Exception:  # noqa: BLE001 — kabar gagal tidak membatalkan permintaan
        log.warning("Kabar permintaan shift %s gagal dikirim", rid, exc_info=True)


async def _akun_hr(db) -> list:
    rows = await db.users.find({"role": {"$in": list(PERAN_SDM_KABAR)}, "is_active": {"$ne": False}},
                               {"_id": 0, "id": 1}).to_list(20)
    return [r["id"] for r in rows if r.get("id")]


def _riwayat(tahap: str, keputusan: str, user: dict, catatan: str = "") -> dict:
    return {"tahap": tahap, "keputusan": keputusan, "oleh": user.get("id"), "oleh_nama": user.get("name") or "",
            "catatan": str(catatan or "")[:MAKS_ALASAN], "waktu": _now().isoformat()}


def publik(doc: dict) -> dict:
    d = {k: v for k, v in (doc or {}).items() if k not in ("_id", "rekan_user_ids", "atasan_user_ids")}
    d["label_status"] = LABEL_STATUS.get(d.get("status"), d.get("status"))
    d["label_jenis"] = LABEL_JENIS.get(d.get("jenis"), d.get("jenis"))
    return d


async def _tahap_sesudah_rekan(db, doc: dict) -> tuple[str, list]:
    """Status sesudah tahap rekan (atau saat dibuat untuk `ganti`): atasan bila ada akun atasan yang bukan
    pemohon/rekan; selain itu langsung SDM."""
    atasan = [u for u in (doc.get("atasan_user_ids") or []) if u not in (doc.get("user_id"),
                                                                          *(doc.get("rekan_user_ids") or []))]
    if atasan:
        return "menunggu_atasan", atasan
    return "menunggu_hr", await _akun_hr(db)


# ── Buat ────────────────────────────────────────────────────────────────────
async def buat(db, user: dict, body: dict, *, today) -> dict:
    jenis = str(body.get("jenis") or "").strip().lower()
    if jenis not in LABEL_JENIS:
        raise GalatPermintaan(400, "Jenis permintaan harus ganti atau tukar shift.")
    alasan = " ".join(str(body.get("alasan") or "").split())
    if len(alasan) < 5:
        raise GalatPermintaan(400, "Tulis alasan permintaan (minimal 5 huruf).")
    try:
        hari = sr.tgl(body.get("tanggal"))
    except sr.GalatRoster as e:
        raise GalatPermintaan(e.status, e.pesan)
    if hari < today:
        raise GalatPermintaan(400, "Tanggal sudah lewat. Untuk hari yang sudah lewat, ajukan koreksi absen di "
                                   "Absen Saya.")
    if (hari - today).days > MAKS_HARI_DEPAN:
        raise GalatPermintaan(400, f"Permintaan paling jauh {MAKS_HARI_DEPAN} hari ke depan.")
    iso = hari.isoformat()
    emp = await _karyawan_saya(db, user)
    shifts = await sr.muat_shift(db)
    kunci = await sr.kunci_hari(db, [emp["id"]], [iso])
    ck = kunci["cuti"].get((emp["id"], iso))
    if ck and not ck["setengah"]:
        raise GalatPermintaan(409, f"Tanggal ini Anda sedang {ck['label'].lower()} yang sudah disetujui.")
    dup = await db.hr_shift_requests.find_one({"employee_id": emp["id"], "tanggal": iso,
                                               "status": {"$in": list(MENUNGGU)}}, {"_id": 0, "id": 1})
    if dup:
        raise GalatPermintaan(409, "Masih ada permintaan Anda untuk tanggal ini yang belum diputus.")
    asal = await shift_pada(db, emp, iso, shifts)
    atasan_emp = emp.get("manager_id") or emp.get("supervisor_id")
    doc = {
        "id": str(uuid.uuid4()), "nomor": f"SHF-{_now().strftime('%y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}",
        "jenis": jenis, "employee_id": emp["id"], "employee_name": emp.get("name") or "",
        "employee_code": emp.get("employee_code") or "", "department": emp.get("department") or "",
        "user_id": user.get("id"), "tanggal": iso, "shift_asal": _ringkas_shift(asal), "alasan": alasan[:MAKS_ALASAN],
        "atasan_employee_id": atasan_emp if atasan_emp and atasan_emp != emp["id"] else None,
        "riwayat": [_riwayat("pengajuan", "diajukan", user, alasan)],
        "created_at": _now().isoformat(), "updated_at": _now().isoformat(),
    }
    doc["atasan_user_ids"] = await _akun(db, doc["atasan_employee_id"])
    if jenis == "ganti":
        diminta = shifts.get(str(body.get("shift_id") or ""))
        if not diminta or not diminta["aktif"]:
            raise GalatPermintaan(400, "Pilih shift tujuan yang masih aktif.")
        if asal and diminta["id"] == asal["id"]:
            raise GalatPermintaan(400, f"Shift Anda pada tanggal itu sudah {diminta['kode']}.")
        doc["shift_diminta"] = _ringkas_shift(diminta)
        doc["status"], penerima = await _tahap_sesudah_rekan(db, doc)
    else:
        rid = str(body.get("rekan_employee_id") or "")
        if not rid or rid == emp["id"]:
            raise GalatPermintaan(400, "Pilih rekan yang akan diajak bertukar shift.")
        rekan = await db.rahaza_employees.find_one({"id": rid, "active": {"$ne": False}},
                                                   {"_id": 0, "id": 1, "name": 1, "employee_code": 1, "shift_id": 1,
                                                    "department": 1})
        if not rekan:
            raise GalatPermintaan(404, "Rekan tidak ditemukan atau sudah nonaktif.")
        rk = await sr.kunci_hari(db, [rid], [iso])
        if (rk["cuti"].get((rid, iso)) or {}).get("setengah") is False:
            raise GalatPermintaan(409, "Rekan sedang cuti/izin pada tanggal itu.")
        rekan_asal = await shift_pada(db, rekan, iso, shifts)
        if not asal and not rekan_asal:
            raise GalatPermintaan(400, "Anda dan rekan sama-sama tidak punya shift pada tanggal itu.")
        if asal and rekan_asal and asal["id"] == rekan_asal["id"]:
            raise GalatPermintaan(400, f"Anda dan rekan sudah sama-sama shift {asal['kode']} pada tanggal itu.")
        doc.update({"rekan_employee_id": rid, "rekan_name": rekan.get("name") or "",
                    "rekan_code": rekan.get("employee_code") or "", "rekan_shift_asal": _ringkas_shift(rekan_asal),
                    "rekan_user_ids": await _akun(db, rid)})
        if not doc["rekan_user_ids"]:
            raise GalatPermintaan(409, "Rekan ini belum punya akun Portal Saya, jadi tidak bisa menyetujui tukar "
                                       "shift. Minta SDM mengubah jadwal langsung.")
        doc["status"], penerima = "menunggu_rekan", doc["rekan_user_ids"]
    await db.hr_shift_requests.insert_one(dict(doc))
    await _kabari_tahap(db, doc, penerima)
    return publik(doc)


async def _kabari_tahap(db, doc: dict, penerima: list) -> None:
    jenis = LABEL_JENIS.get(doc["jenis"], "Permintaan shift")
    tgl = sr.label_tgl(doc["tanggal"])
    if doc["status"] == "menunggu_rekan":
        await _notif(db, penerima, f"{jenis}: {doc['employee_name']} mengajak Anda bertukar",
                     f"{doc['employee_name']} ingin bertukar shift dengan Anda pada {tgl}. Buka Portal Saya › "
                     "Jadwal Shift untuk menjawab.", "portal-shift", doc["id"])
    elif doc["status"] == "menunggu_atasan":
        await _notif(db, penerima, f"{jenis} menunggu persetujuan Anda",
                     f"{doc['employee_name']} mengajukan {jenis.lower()} untuk {tgl}.", "portal-shift", doc["id"])
    elif doc["status"] == "menunggu_hr":
        await _notif(db, penerima, f"{jenis} menunggu persetujuan SDM",
                     f"{doc['employee_name']} mengajukan {jenis.lower()} untuk {tgl}.", "hr-shift-hub", doc["id"])


async def _ambil(db, rid: str) -> dict:
    doc = await db.hr_shift_requests.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise GalatPermintaan(404, "Permintaan shift tidak ditemukan.")
    return doc


async def _pindah(db, doc: dict, dari: str, ke: dict, riwayat: dict) -> dict:
    """Klaim atomik: hanya bila status masih `dari` (dua orang memutus bersamaan → yang kedua 409)."""
    upd = {**ke, "updated_at": _now().isoformat()}
    r = await db.hr_shift_requests.update_one({"id": doc["id"], "status": dari},
                                              {"$set": upd, "$push": {"riwayat": riwayat}})
    if not getattr(r, "matched_count", 0):
        raise GalatPermintaan(409, "Permintaan ini sudah diputus atau dibatalkan orang lain. Muat ulang daftar.")
    doc = {**doc, **upd, "riwayat": [*(doc.get("riwayat") or []), riwayat]}
    return doc


# ── Tanggapan rekan, atasan, SDM ────────────────────────────────────────────
async def tanggapi_rekan(db, user: dict, rid: str, setuju: bool, catatan: str = "") -> dict:
    doc = await _ambil(db, rid)
    if user.get("id") not in (doc.get("rekan_user_ids") or []):
        raise GalatPermintaan(403, "Hanya rekan yang diajak bertukar yang bisa menjawab permintaan ini.")
    if doc.get("status") != "menunggu_rekan":
        raise GalatPermintaan(409, "Permintaan ini tidak lagi menunggu jawaban rekan.")
    if not setuju:
        doc = await _pindah(db, doc, "menunggu_rekan", {"status": "ditolak"},
                            _riwayat("rekan", "ditolak", user, catatan))
        await _notif(db, [doc.get("user_id")], "Tukar shift ditolak rekan",
                     f"{doc.get('rekan_name')} menolak bertukar shift pada {sr.label_tgl(doc['tanggal'])}.",
                     "portal-shift", doc["id"])
        return publik(doc)
    status, penerima = await _tahap_sesudah_rekan(db, doc)
    doc = await _pindah(db, doc, "menunggu_rekan", {"status": status}, _riwayat("rekan", "setuju", user, catatan))
    await _kabari_tahap(db, doc, penerima)
    return publik(doc)


async def putuskan_atasan(db, user: dict, rid: str, setujui: bool, catatan: str = "") -> dict:
    doc = await _ambil(db, rid)
    if user.get("id") not in (doc.get("atasan_user_ids") or []):
        raise GalatPermintaan(403, "Hanya atasan langsung pemohon yang bisa memutus tahap ini.")
    if user.get("id") in (doc.get("user_id"), *(doc.get("rekan_user_ids") or [])):
        raise GalatPermintaan(403, "Pemisahan tugas: Anda tidak boleh memutus permintaan yang melibatkan diri sendiri.")
    if doc.get("status") != "menunggu_atasan":
        raise GalatPermintaan(409, "Permintaan ini tidak lagi menunggu persetujuan atasan.")
    if not setujui:
        doc = await _pindah(db, doc, "menunggu_atasan", {"status": "ditolak"},
                            _riwayat("atasan", "ditolak", user, catatan))
        await _kabari_akhir(db, doc, False)
        return publik(doc)
    doc = await _pindah(db, doc, "menunggu_atasan", {"status": "menunggu_hr"},
                        _riwayat("atasan", "disetujui", user, catatan))
    await _kabari_tahap(db, doc, await _akun_hr(db))
    return publik(doc)


async def putuskan_hr(db, user: dict, rid: str, setujui: bool, catatan: str = "") -> dict:
    doc = await _ambil(db, rid)
    if user.get("id") in (doc.get("user_id"), *(doc.get("rekan_user_ids") or [])):
        raise GalatPermintaan(403, "Pemisahan tugas: permintaan shift yang melibatkan Anda harus diputus SDM lain.")
    if doc.get("status") != "menunggu_hr":
        raise GalatPermintaan(409, "Permintaan ini tidak sedang menunggu persetujuan SDM.")
    if not setujui:
        doc = await _pindah(db, doc, "menunggu_hr", {"status": "ditolak"}, _riwayat("sdm", "ditolak", user, catatan))
        await _kabari_akhir(db, doc, False)
        return publik(doc)
    jadwal = await _siapkan_jadwal(db, doc, user)
    doc = await _pindah(db, doc, "menunggu_hr", {"status": "disetujui", "jadwal_id": jadwal["id"]},
                        _riwayat("sdm", "disetujui", user, catatan))
    await db.rahaza_schedules.insert_one(dict(jadwal))
    await _kabari_akhir(db, doc, True)
    return publik(doc)


async def _siapkan_jadwal(db, doc: dict, user: dict) -> dict:
    """Jadwal terbit berjenis `perubahan` untuk tanggal permintaan. Shift yang berlaku dibaca ULANG: bila sudah
    berbeda dari saat diajukan → 409, tidak ada yang ditulis."""
    from core.attendance_rules import attendance_lock
    iso = doc["tanggal"]
    shifts = await sr.muat_shift(db)
    pemohon = await db.rahaza_employees.find_one({"id": doc["employee_id"]}, {"_id": 0})
    if not pemohon:
        raise GalatPermintaan(404, "Data karyawan pemohon tidak ditemukan.")
    for eid in (doc["employee_id"], doc.get("rekan_employee_id")):
        if eid and await attendance_lock(db, eid, iso):
            raise GalatPermintaan(409, "Tanggal ini sudah masuk penggajian final; jadwal tidak bisa diubah.")
    kini = await shift_pada(db, pemohon, iso, shifts)
    if (kini or {}).get("id") != (doc.get("shift_asal") or {}).get("id"):
        raise GalatPermintaan(409, f"Shift pemohon pada {sr.label_tgl(iso)} sudah berubah sejak diajukan "
                                   f"(sekarang {label_shift(kini)}). Tidak ada yang diubah; minta pemohon mengajukan ulang.")
    entri = []
    if doc["jenis"] == "ganti":
        entri.append(sr.entri_jadwal(pemohon, iso, shifts.get(str((doc.get("shift_diminta") or {}).get("id")))))
    else:
        rekan = await db.rahaza_employees.find_one({"id": doc["rekan_employee_id"]}, {"_id": 0})
        if not rekan:
            raise GalatPermintaan(404, "Data karyawan rekan tidak ditemukan.")
        rk = await shift_pada(db, rekan, iso, shifts)
        if (rk or {}).get("id") != (doc.get("rekan_shift_asal") or {}).get("id"):
            raise GalatPermintaan(409, f"Shift rekan pada {sr.label_tgl(iso)} sudah berubah sejak diajukan "
                                       f"(sekarang {label_shift(rk)}). Tidak ada yang diubah.")
        entri.append(sr.entri_jadwal(pemohon, iso, rk))
        entri.append(sr.entri_jadwal(rekan, iso, kini))
    now = _now().isoformat()
    judul = (f"Ganti shift {doc['employee_name']}" if doc["jenis"] == "ganti"
             else f"Tukar shift {doc['employee_name']} ↔ {doc.get('rekan_name')}")
    return {"id": str(uuid.uuid4()), "judul": f"{judul} ({sr.label_tgl(iso)})", "jenis": "perubahan",
            "permintaan_id": doc["id"], "start_date": iso, "end_date": iso, "department": None,
            "shifts": entri, "metadata": sr.ringkas_jadwal(entri), "status": "published",
            "generated_at": now, "generated_by": user.get("id"), "published_at": now, "published_by": user.get("id")}


async def _kabari_akhir(db, doc: dict, disetujui: bool) -> None:
    jenis = LABEL_JENIS.get(doc["jenis"], "Permintaan shift")
    hasil = "disetujui" if disetujui else "ditolak"
    tgl = sr.label_tgl(doc["tanggal"])
    await _notif(db, [doc.get("user_id"), *(doc.get("rekan_user_ids") or [])], f"{jenis} {hasil}",
                 f"{jenis} {doc.get('employee_name')} untuk {tgl} {hasil}.", "portal-shift", doc["id"])


async def batalkan(db, user: dict, rid: str) -> dict:
    doc = await _ambil(db, rid)
    if doc.get("user_id") != user.get("id"):
        raise GalatPermintaan(403, "Hanya pemohon yang bisa membatalkan permintaan ini.")
    if doc.get("status") not in MENUNGGU:
        raise GalatPermintaan(409, "Permintaan yang sudah diputus tidak bisa dibatalkan.")
    doc = await _pindah(db, doc, doc["status"], {"status": "dibatalkan"}, _riwayat("pemohon", "dibatalkan", user))
    return publik(doc)


# ── Daftar ──────────────────────────────────────────────────────────────────
async def daftar_saya(db, user: dict, batas: int = 100) -> dict:
    uid = user.get("id")
    milik = await db.hr_shift_requests.find({"user_id": uid}, {"_id": 0}).sort("created_at", -1).to_list(batas)
    rekan = await db.hr_shift_requests.find({"rekan_user_ids": uid}, {"_id": 0}).sort("created_at", -1).to_list(batas)
    atasan = await db.hr_shift_requests.find({"atasan_user_ids": uid, "status": "menunggu_atasan"},
                                             {"_id": 0}).sort("created_at", -1).to_list(batas)
    return {"milik_saya": [publik(d) for d in milik], "sebagai_rekan": [publik(d) for d in rekan],
            "perlu_persetujuan_saya": [publik(d) for d in atasan]}


async def daftar_hr(db, status: Optional[str] = None, batas: int = 300) -> list:
    q: dict = {}
    if status and status != "semua":
        if status not in STATUS:
            raise GalatPermintaan(400, "Status permintaan tidak dikenal.")
        q["status"] = status
    rows = await db.hr_shift_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(batas)
    return [publik(d) for d in rows]
