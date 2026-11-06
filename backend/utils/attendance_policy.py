"""attendance_policy.py — SSOT KEBIJAKAN ABSEN (selfie wajib · geofence wajib · bukti foto).

═══════════════════════════════════════════════════════════════════════════════
KENAPA MODUL INI ADA (keputusan user 2026-07-26: "selfie + lokasi WAJIB")
═══════════════════════════════════════════════════════════════════════════════
Tiga penyakit nyata yang ditutup di akarnya:

1. **Selfie tidak pernah benar-benar disimpan.** `rahaza_auto_attendance_selfie.py`
   menulis::

       "photo_selfie_url": f"data:image/jpeg;base64,{photo_b64[:20]}..."

   yaitu **20 karakter pertama** base64 + "...". Tidak bisa dibuka, tidak bisa
   diaudit — jadi "bukti selfie" selama ini fiktif. Endpoint clock-out bahkan
   membuang `photo_base64` tanpa dipakai sama sekali
   (`body.get("photo_base64", "")` tanpa assignment).

2. **Kebijakan "wajib" tidak ditegakkan.** `_determine_approval()` memperlakukan
   geofence `not_verified` (kantor BELUM dikonfigurasi, atau GPS tidak dikirim)
   sebagai **lolos** ⇒ absen dari mana saja auto-approved. Sama untuk wajah:
   `no_reference` dan `error` dianggap lolos.

3. **Rumus haversine disalin 3 kali** (`rahaza_attendance.py` inline,
   `rahaza_auto_attendance_config.py`, `rahaza_auto_attendance_selfie.py`) —
   salah satunya (`rahaza_attendance.py`) bahkan meledak `TypeError` bila
   `office.lat` masih None karena langsung `math.radians(float(office["lat"]))`.

Modul ini adalah SATU-SATUNYA tempat aturan tersebut hidup. Jangan menyalin
ulang haversine / aturan wajib di modul lain — `scripts/verify_fase16_absen.py`
bagian S menjaganya lewat pemindaian statik.

═══════════════════════════════════════════════════════════════════════════════
KONFIGURASI (koleksi `rahaza_office_locations`, dokumen `is_primary: True`)
═══════════════════════════════════════════════════════════════════════════════
| field                | default | arti                                        |
|----------------------|---------|---------------------------------------------|
| `lat` / `lng`        | None    | titik kantor; WAJIB diisi bila geofence aktif|
| `geofence_radius_m`  | 300     | radius toleransi (meter)                     |
| `require_selfie`     | True    | absen tanpa foto ditolak                     |
| `require_geofence`   | True    | absen di luar radius / tanpa GPS ditolak     |
| `face_match_threshold`| 0.65   | ambang kemiripan wajah AI                    |
| `gps_max_age_s`      | 60      | umur maksimum posisi GPS saat tombol ditekan (Tahap 2) |
| `gps_max_accuracy_m` | 100     | akurasi GPS terburuk yang masih diterima (Tahap 2) |
| `clock_out_window_hours` | 6   | absen pulang lewat tengah malam: jendela sesudah jam pulang shift |

Semua nilai bisa diubah HR lewat `PUT /api/rahaza/attendance/office-location`.
"""
from __future__ import annotations

import base64
import binascii
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

import storage
from utils.waktu import today_wib

DEFAULT_GEOFENCE_RADIUS_M = 300
DEFAULT_FACE_THRESHOLD = 0.65
MAX_SELFIE_BYTES = 4 * 1024 * 1024  # 4 MB — cukup untuk JPEG 480–1080p
MIN_SELFIE_BYTES = 1024             # < 1 KB pasti bukan foto wajah

# Pesan dipakai UI apa adanya (Bahasa Indonesia, menyebut LANGKAH PERBAIKAN).
MSG_OFFICE_UNSET = (
    "Lokasi kantor belum diatur, padahal kebijakan absen mewajibkan verifikasi "
    "lokasi. Minta Admin HR mengisinya di menu Absensi → Konfigurasi → Lokasi Kantor."
)
MSG_SELFIE_REQUIRED = (
    "Selfie wajib untuk absen. Izinkan akses kamera lalu ambil foto sebelum mengirim."
)
MSG_GPS_REQUIRED = (
    "Lokasi GPS wajib untuk absen. Aktifkan izin lokasi di browser/HP Anda, "
    "lalu coba lagi."
)
DEFAULT_GPS_MAX_AGE_S = 60
DEFAULT_GPS_MAX_ACCURACY_M = 100
MSG_GPS_FIX_MISSING = (
    "Lokasi harus dibaca ulang saat tombol absen ditekan. Muat ulang halaman, lalu tekan Coba lagi."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ═════════════════════════════════════════════════════════════════════════════
# JARAK — SATU-SATUNYA implementasi haversine di repo
# ═════════════════════════════════════════════════════════════════════════════
def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Jarak permukaan bumi (meter) antara dua koordinat desimal."""
    R = 6371000.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dlat = p2 - p1
    dlng = math.radians(float(lng2)) - math.radians(float(lng1))
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def check_geofence(lat, lng, office: Optional[dict]) -> dict:
    """Status geofence — TIDAK melempar exception (dipakai juga untuk laporan).

    Return: `{status, distance_m, in_range, radius_m}` dengan
    `status ∈ {not_verified, in_range, out_of_range}`.
    `not_verified` berarti **tidak bisa disimpulkan** (kantor/GPS tak lengkap) —
    penegakan "tolak atau tidak" ada di `enforce_attendance_policy`.
    """
    radius = float((office or {}).get("geofence_radius_m") or DEFAULT_GEOFENCE_RADIUS_M)
    if not office or office.get("lat") is None or office.get("lng") is None:
        return {"status": "not_verified", "distance_m": None,
                "in_range": None, "radius_m": radius}
    if lat is None or lng is None:
        return {"status": "not_verified", "distance_m": None,
                "in_range": None, "radius_m": radius}
    try:
        dist = haversine_m(office["lat"], office["lng"], float(lat), float(lng))
    except (TypeError, ValueError):
        return {"status": "not_verified", "distance_m": None,
                "in_range": None, "radius_m": radius}
    return {
        "status": "in_range" if dist <= radius else "out_of_range",
        "distance_m": round(dist),
        "in_range": dist <= radius,
        "radius_m": radius,
    }


# ═════════════════════════════════════════════════════════════════════════════
# KONFIGURASI
# ═════════════════════════════════════════════════════════════════════════════
async def get_office(db) -> dict:
    """Konfigurasi kantor utama + default yang eksplisit (tak pernah None)."""
    doc = await db.rahaza_office_locations.find_one({"is_primary": True}, {"_id": 0}) or {}
    return {
        "is_primary": True,
        "name": doc.get("name") or "Kantor Utama",
        "address": doc.get("address") or "",
        "lat": doc.get("lat"),
        "lng": doc.get("lng"),
        "geofence_radius_m": int(doc.get("geofence_radius_m") or DEFAULT_GEOFENCE_RADIUS_M),
        # Kebijakan user 2026-07-26: WAJIB by default (dulu longgar diam-diam).
        "require_selfie": bool(doc.get("require_selfie", True)),
        "require_geofence": bool(doc.get("require_geofence", True)),
        "face_match_threshold": float(doc.get("face_match_threshold") or DEFAULT_FACE_THRESHOLD),
        "gps_max_age_s": int(doc.get("gps_max_age_s") or DEFAULT_GPS_MAX_AGE_S),
        "gps_max_accuracy_m": int(doc.get("gps_max_accuracy_m") or DEFAULT_GPS_MAX_ACCURACY_M),
        "clock_out_window_hours": float(doc.get("clock_out_window_hours")
                                        if doc.get("clock_out_window_hours") is not None else 6),
        "configured": doc.get("lat") is not None and doc.get("lng") is not None,
        "updated_at": doc.get("updated_at"),
    }


# ═════════════════════════════════════════════════════════════════════════════
# PENEGAKAN
# ═════════════════════════════════════════════════════════════════════════════
def _decode_selfie(photo_b64: str) -> bytes:
    raw = (photo_b64 or "").strip()
    if raw.startswith("data:"):                      # buang prefix data-URL
        raw = raw.split(",", 1)[-1]
    try:
        blob = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Foto selfie tidak terbaca (base64 rusak). Ambil ulang foto.")
    if len(blob) < MIN_SELFIE_BYTES:
        raise HTTPException(400, "Foto selfie terlalu kecil/kosong. Ambil ulang foto.")
    if len(blob) > MAX_SELFIE_BYTES:
        raise HTTPException(413, "Ukuran foto selfie melebihi 4 MB. Turunkan resolusi kamera.")
    return blob


def save_selfie(employee_id: str, photo_b64: str, kind: str = "in") -> Optional[str]:
    """Simpan selfie ke penyimpanan lokal, kembalikan URL `/api/uploads/...`.

    Dipanggil SETELAH `enforce_attendance_policy` supaya file tidak ditulis untuk
    absen yang toh akan ditolak.
    """
    if not photo_b64:
        return None
    blob = _decode_selfie(photo_b64)
    path = (f"attendance/{employee_id}/{today_wib().isoformat()}_{kind}_"
            f"{uuid.uuid4().hex[:8]}.jpg")
    return storage.put_object(path, blob, "image/jpeg")["url"]


def gps_fix_from_body(body: Optional[dict]) -> dict:
    """Data kesegaran GPS yang dikirim layar absen: waktu posisi dibaca (`gps_at`, ms), waktu tombol ditekan
    (`gps_sent_at`, ms — jam HP yang sama, jadi selisih jam HP vs server tidak berpengaruh), dan `accuracy` (m)."""
    b = body or {}
    return {"gps_at": b.get("gps_at"), "sent_at": b.get("gps_sent_at"), "accuracy": b.get("accuracy")}


def check_gps_fix(fix: Optional[dict], office: dict) -> dict:
    """Tahap 2 (2026-11-06): GPS dibaca SAAT tombol ditekan. Dulu posisi dibaca sekali waktu halaman dibuka
    lalu dipakai ulang — buka halaman di kantor pagi hari, absen pulang dari rumah tetap lolos.
    Melempar 400 (pesan berakhir "Coba lagi") bila posisi basi atau kurang akurat."""
    f = fix or {}
    try:
        gps_at, sent_at = float(f.get("gps_at")), float(f.get("sent_at"))
    except (TypeError, ValueError):
        raise HTTPException(400, MSG_GPS_FIX_MISSING)
    max_age = int(office.get("gps_max_age_s") or DEFAULT_GPS_MAX_AGE_S)
    age_s = (sent_at - gps_at) / 1000.0
    if age_s > max_age:
        raise HTTPException(400, f"Lokasi GPS sudah basi (dibaca {int(age_s)} detik lalu, batas {max_age} detik). "
                                 "Tekan Coba lagi untuk membaca lokasi baru.")
    max_acc = int(office.get("gps_max_accuracy_m") or DEFAULT_GPS_MAX_ACCURACY_M)
    try:
        acc = float(f.get("accuracy"))
    except (TypeError, ValueError):
        acc = None
    if acc is None or acc > max_acc:
        txt = f"±{int(acc)} m" if acc is not None else "tidak diketahui"
        raise HTTPException(400, f"Lokasi GPS kurang akurat ({txt}, batas {max_acc} m). Nyalakan GPS/lokasi akurat, "
                                 "pindah ke dekat jendela atau tempat terbuka, lalu tekan Coba lagi.")
    return {"age_s": round(max(age_s, 0.0), 1), "accuracy_m": round(acc)}


async def enforce_attendance_policy(db, *, photo_b64: Optional[str],
                                    lat, lng, action: str = "masuk",
                                    selfie_required: Optional[bool] = None,
                                    fix: Optional[dict] = None) -> dict:
    """Tegakkan kebijakan sebelum absen dicatat. Melempar HTTPException bila gagal.

    `selfie_required=False` dipakai jalur BIOMETRIK (WebAuthn/fingerprint) yang
    sudah membuktikan identitas tanpa foto — lokasinya TETAP diperiksa.

    Return `{office, geo}` supaya pemanggil tidak perlu query ulang.
    """
    office = await get_office(db)

    need_selfie = office["require_selfie"] if selfie_required is None else bool(selfie_required)
    if need_selfie and not (photo_b64 or "").strip():
        raise HTTPException(400, MSG_SELFIE_REQUIRED)

    geo = check_geofence(lat, lng, office)
    if office["require_geofence"]:
        if not office["configured"]:
            raise HTTPException(409, MSG_OFFICE_UNSET)
        if lat is None or lng is None:
            raise HTTPException(400, MSG_GPS_REQUIRED)
        geo = {**geo, **check_gps_fix(fix, office)}
        if geo["status"] == "out_of_range":
            raise HTTPException(
                403,
                f"Absen {action} ditolak: Anda berada {geo['distance_m']} m dari "
                f"{office['name']} (batas {int(geo['radius_m'])} m). "
                "Absen hanya bisa dilakukan di area kantor. Bila Anda sudah di kantor, tekan Coba lagi.",
            )
        if geo["status"] == "not_verified":
            raise HTTPException(400, MSG_GPS_REQUIRED)
    return {"office": office, "geo": geo}


def leave_status_for_clock_in(existing: Optional[dict]) -> str:
    """Status yang ditulis saat absen MASUK (Tahap 2, 2026-11-06).

    Dulu absen masuk selalu menimpa status jadi 'hadir', termasuk di hari cuti yang sudah disetujui.
    · cuti/izin/sakit SETENGAH HARI disetujui → status cutinya tetap (payroll menghitung hadir 0,5);
    · cuti SEHARI PENUH disetujui → absen masuk ditolak (minta HR membatalkan cutinya dulu);
    · selain itu → 'hadir'."""
    r = existing or {}
    if r.get("leave_request_id"):
        kind = (r.get("leave_kind") or r.get("status") or "cuti").lower()
        if r.get("half_day"):
            return kind
        raise HTTPException(409, f"Hari ini Anda tercatat {kind} yang sudah disetujui. Bila Anda tetap masuk "
                                 "kerja, minta HR membatalkan pengajuan itu dulu, lalu absen lagi.")
    return "hadir"


def attendance_counts(rec: Optional[dict]) -> bool:
    """Apakah satu record absensi DIHITUNG oleh pembaca (payroll, rekap jam).

    Tahap 1 (2026-11-06, keputusan owner): selfie yang masih `pending` dihitung hadir sampai HR
    menolaknya. Selfie yang DITOLAK (`approval_status='rejected'`, status jadi 'alpa'/'alfa') bukan
    kehadiran: tidak dihitung hadir dan jam kerja/lembur/terlambatnya tidak dipakai — padahal jamnya
    masih tersimpan (penolakan tidak menghapus jam; absen pulang sesudah ditolak tetap mengisi jam).
    Pengecualian: HR kemudian menandainya Hadir lagi secara manual (status 'hadir').
    """
    r = rec or {}
    return not (r.get("approval_status") == "rejected" and (r.get("status") or "").lower() != "hadir")


def determine_approval(geo: dict, face: dict, office: dict) -> str:
    """`auto_approved` atau `pending` (menunggu HR).

    Perbedaan dengan versi lama: geofence `not_verified` TIDAK lagi dianggap
    lolos — kalau lokasi tak bisa dipastikan, HR yang memutuskan.
    """
    threshold = float((office or {}).get("face_match_threshold") or DEFAULT_FACE_THRESHOLD)
    geo_ok = geo.get("in_range") is True
    if not (office or {}).get("require_geofence", True):
        geo_ok = geo.get("in_range") is not False   # geofence dimatikan HR

    face_status = (face or {}).get("status", "not_checked")
    if face_status == "checked":
        face_ok = face.get("match") is True and float(face.get("confidence") or 0) >= threshold
    else:
        # not_checked / no_reference / error → tidak bisa disimpulkan.
        # Kalau selfie diwajibkan, ini HARUS jadi antrean HR, bukan lolos diam-diam.
        face_ok = not (office or {}).get("require_selfie", True)
    return "auto_approved" if (geo_ok and face_ok) else "pending"
