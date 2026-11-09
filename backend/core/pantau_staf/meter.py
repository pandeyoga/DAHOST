"""Meter aktivitas harian per akun (lapis "Aktivitas") — Tahap 1 Monitoring Staf.

Dipanggil `middleware/module_permission_gate.py` SESUDAH respons terkirim, untuk setiap permintaan `/api/*`
yang membawa token akun internal. Gerbang itu sudah memetakan path → modul katalog (`data/module_catalog.py`)
+ aksi (Lihat/Tambah/Ubah/Hapus/Setujui/Unduh), jadi satu titik ini mencatat semua portal tanpa menyentuh
134 berkas rute.

Satu dokumen per akun per tanggal WIB (`pantau_aktivitas_harian`, unik `id = <user_id>:<YYYY-MM-DD>`):
    {id, user_id, tanggal, pertama, terakhir, jumlah, modul: {<modul>: {view, create, edit, delete, approve, export}}}

Yang TIDAK dicatat: isi data, path lengkap, respons gagal (>= 400), akun eksternal (vendor/klien), permintaan baca
di luar katalog (bel notifikasi, lencana, profil — dipanggil berkala oleh layar apa pun sehingga bukan tanda kerja),
dan baca modul `lookup` (data acuan dropdown lintas portal). "Lihat" dibatasi satu catatan per modul per menit per
akun (banyak layar memuat ulang otomatis tiap 60 detik). Gagal tulis TIDAK PERNAH menggagalkan permintaan.
"""
from __future__ import annotations

import asyncio
import logging
import time as _time

from utils.waktu import now_utc, wib_date_str

log = logging.getLogger(__name__)

KOLEKSI = "pantau_aktivitas_harian"
EKSTERNAL = {"vendor", "cmt_vendor", "buyer", "klien_maklon"}
JEDA_LIHAT_DETIK = 60
_TERAKHIR: dict = {}          # (user_id, modul, aksi) → detik monotonic catatan terakhir (khusus "view")
_MAKS_KUNCI = 20000
_TUGAS: set = set()           # referensi tugas latar supaya tidak dibuang pengumpul sampah sebelum selesai


def perlu_dicatat(*, user_id, role, method: str, status: int, module: dict | None, action: str | None) -> bool:
    """Aturan murni: apakah satu permintaan dicatat."""
    if not user_id or (role or "").lower() in EKSTERNAL:
        return False
    if status is None or int(status) >= 400:
        return False
    tulis = (method or "GET").upper() not in ("GET", "HEAD", "OPTIONS")
    if module is None:
        return tulis                 # tulisan di luar katalog (mis. Portal Saya) tetap tanda bekerja
    if not tulis and (action in (None, "view")) and module.get("lookup"):
        return False
    return True


def _lolos_jeda(user_id: str, modul: str, aksi: str) -> bool:
    if aksi != "view":
        return True
    kunci = (user_id, modul, aksi)
    kini = _time.monotonic()
    lalu = _TERAKHIR.get(kunci)
    if lalu is not None and kini - lalu < JEDA_LIHAT_DETIK:
        return False
    if len(_TERAKHIR) > _MAKS_KUNCI:
        _TERAKHIR.clear()
    _TERAKHIR[kunci] = kini
    return True


def ubahan(user_id: str, modul: str, aksi: str, kini=None) -> tuple[dict, dict]:
    """(kueri, ubahan upsert) untuk satu catatan — murni, diuji tersendiri."""
    kini = kini or now_utc()
    tanggal = wib_date_str(kini)
    did = f"{user_id}:{tanggal}"
    return ({"id": did}, {
        "$setOnInsert": {"id": did, "user_id": user_id, "tanggal": tanggal, "pertama": kini},
        "$max": {"terakhir": kini},
        "$inc": {f"modul.{modul}.{aksi}": 1, "jumlah": 1},
    })


async def catat(db, *, user_id, role, method, status, module, action) -> bool:
    """Catat satu permintaan. True bila tertulis. Tidak pernah melempar galat."""
    try:
        if not perlu_dicatat(user_id=user_id, role=role, method=method, status=status, module=module,
                             action=action):
            return False
        modul = (module or {}).get("id") or "_lain"
        aksi = action or ("view" if (method or "GET").upper() == "GET" else "edit")
        if not _lolos_jeda(str(user_id), modul, aksi):
            return False
        q, upd = ubahan(str(user_id), modul, aksi)
        await db[KOLEKSI].update_one(q, upd, upsert=True)
        return True
    except Exception:  # noqa: BLE001
        log.debug("[pantau-staf] meter gagal mencatat", exc_info=True)
        return False


def catat_latar(**kw) -> None:
    """Jadwalkan `catat` di latar (dipanggil middleware sesudah respons)."""
    try:
        from database import get_db
        t = asyncio.get_running_loop().create_task(catat(get_db(), **kw))
        _TUGAS.add(t)
        t.add_done_callback(_TUGAS.discard)
    except Exception:  # noqa: BLE001
        log.debug("[pantau-staf] meter tidak bisa dijadwalkan", exc_info=True)


async def aktivitas(db, user_ids: list | None, dari: str, sampai: str, limit: int = 20000) -> list[dict]:
    """Baris aktivitas harian (tanggal WIB 'YYYY-MM-DD' inklusif)."""
    q: dict = {"tanggal": {"$gte": dari, "$lte": sampai}}
    if user_ids is not None:
        q["user_id"] = {"$in": list(user_ids)}
    return await db[KOLEKSI].find(q, {"_id": 0}).sort("tanggal", 1).to_list(limit)
