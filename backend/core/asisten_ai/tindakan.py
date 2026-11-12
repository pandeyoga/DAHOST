"""Tindakan Asisten AI (Tahap B, 8 Nov 2026) — kartu konfirmasi, keputusan, kedaluwarsa, pembatalan.

Kontrak D/E (brief Tahap B). Alur:
  1. model memanggil alat tindakan → inti menjalankan `siapkan` (BACA SAJA) → dokumen `ai_actions`
     berstatus `menunggu` + event SSE `tindakan`; loop agen berhenti (pesan `menunggu_konfirmasi`);
  2. pemilik sesi menekan Setujui/Batal (`POST /tindakan/{id}/putuskan`) → klaim atomik (doc_lock +
     status `menunggu` di filter) → `jalankan` SEKALI lewat `ctx.api` dengan token pengguna sendiri;
  3. setelah SEMUA kartu giliran itu diputuskan → giliran pengguna berisi seluruh tool_result
     (hasil alat baca yang disimpan + hasil tiap tindakan) → loop dilanjutkan (jawaban baru);
  4. pesan baru dikirim padahal masih ada kartu menunggu → kartu itu `kedaluwarsa`, tool_result-nya
     ("Tidak diputuskan; tindakan tidak dijalankan.") ditaruh di DEPAN giliran pengguna baru;
  5. kartu menunggu > 24 jam → `kedaluwarsa` (diperiksa malas saat dibaca/diputuskan).
Riwayat API tetap append-only dan sah: setiap tool_use dibalas tepat satu tool_result.

Koleksi `ai_actions` (jenis `log`, core/collection_registry.py):
  {id, user_id, pengguna{id,nama}, sesi_id, pesan_id, tool_use_id, nama, label, risiko, menu,
   args, args_awal, rencana, keadaan, cv, periode, tanggal (WIB), dibuat, diperbarui, kedaluwarsa_pada,
   keputusan, diputuskan_pada, diputuskan_oleh, alasan, ubahan, dijalankan_pada, tanggal_jalan, selesai_pada,
   ringkas, pesan, hasil, sebelum, sesudah, pembatalan, bisa_dibalikkan,
   dibalikkan_pada, dibalikkan_oleh{id,nama}, alasan_balik, hasil_balik, balik_gagal, dikabarkan_balik,
   kunci_proses, kunci_proses_at, kunci_proses_by}
Keadaan: menunggu → disetujui (sedang dijalankan) → dijalankan | gagal;
         menunggu → dibatalkan | kedaluwarsa;  dijalankan → dibalikkan.
Satu-satunya tulisan DB langsung milik tindakan adalah dokumen `ai_actions` ini; tulisan data bisnis
selalu lewat endpoint aplikasi (`ctx.api`).
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

import ai_cost_tracker as tracker
from core import doc_lock
from core.asisten_ai import alat_base as ab
from core.asisten_ai import simpan

log = logging.getLogger(__name__)

KOLEKSI = "ai_actions"
KUNCI = "kunci_proses"
KEADAAN = ("menunggu", "disetujui", "dijalankan", "dibatalkan", "gagal", "kedaluwarsa", "dibalikkan",
           "menunggu_kedua")   # 12 Nov 2026 (K4): kartu uang di atas batas → menunggu persetujuan kedua owner
KEADAAN_TERBUKA = ("menunggu", "disetujui")
KEADAAN_TERHITUNG = ("disetujui", "dijalankan", "dibalikkan")   # dihitung ke batas harian
PERAN_SEMUA = frozenset({"owner", "superadmin"})               # boleh melihat tindakan semua pengguna

MASA_BERLAKU = timedelta(hours=24)
MASA_KEDUA = timedelta(days=3)      # kartu `menunggu_kedua` kedaluwarsa bila owner tidak memutuskan
BATAS_DETIK_TINDAKAN = 60.0
MAKS_KARTU_GILIRAN = 5
BATAS_RENCANA = 16000   # 12 Nov 2026 (K10): kartu kelompok sampai 50 baris
BATAS_PEMBATALAN = 20000
BATAS_HASIL_SIMPAN = 4000
BATAS_BAWAAN = 100   # 12 Nov 2026 (K10, dulu 30)
MIN_ALASAN_MENENGAH = 10
PERAN_KEDUA = frozenset({"owner", "superadmin"})   # penyetuju kedua kartu uang (K4)
JENIS_UBAH = ("rupiah", "angka", "teks", "tanggal", "pilihan")
PER_HALAMAN = 25

# ── Teks tool_result untuk MODEL (prompt sistem merujuk frasa awalnya) ──────
HASIL_DIJALANKAN = "Disetujui dan dijalankan: {ringkas}"
HASIL_DIBATALKAN = "Dibatalkan pengguna. Tidak ada data yang diubah."
HASIL_GAGAL = "Gagal: {pesan}"
HASIL_KEDALUWARSA = "Tidak diputuskan; tindakan tidak dijalankan."
HASIL_TIDAK_DIJALANKAN = "Tidak dijalankan."
HASIL_MASIH_PROSES = ("Tindakan ini masih diproses saat pesan baru dikirim; hasil akhirnya terlihat di kartu dan di "
                      "layar Tindakan AI. Jangan menganggapnya sudah berhasil.")
MODEL_MATI = ("Tindakan AI sedang dimatikan admin, jadi perubahan tidak bisa disiapkan. Jelaskan ke pengguna bahwa "
              "perubahan ini dilakukan langsung di layar terkait dan sebut menunya.")
MODEL_BATAS = ("Batas tindakan Asisten AI untuk pengguna ini hari ini sudah tercapai ({batas} tindakan), jadi kartu "
               "tidak disiapkan. Sampaikan bahwa perubahan bisa dilakukan langsung di layar terkait atau besok.")
MODEL_KARTU_BANYAK = ("Terlalu banyak tindakan dalam satu giliran (maksimal {n}). Gabungkan perubahan sejenis ke satu "
                      "panggilan alat tindakan.")

# ── Pesan untuk LAYAR (HTTP 4xx) ─────────────────────────────────────────────
LAYAR_TIDAK_ADA = "Tindakan tidak ditemukan."
LAYAR_MATI = "Tindakan AI sedang dimatikan admin, jadi kartu ini tidak bisa disetujui. Kartu masih bisa dibatalkan."
LAYAR_BATAS = ("Batas tindakan Asisten AI hari ini sudah tercapai ({batas} tindakan per pengguna). Lakukan "
               "perubahan langsung di layar terkait atau coba lagi besok.")
LAYAR_ALASAN = f"Tindakan berisiko menengah wajib diberi alasan (minimal {MIN_ALASAN_MENENGAH} karakter)."
LAYAR_ALASAN_TINGGI = f"Tindakan berisiko tinggi wajib diberi alasan (minimal {MIN_ALASAN_MENENGAH} karakter)."
LAYAR_KONFIRMASI = "Ketik ulang sesuai petunjuk di kartu untuk menyetujui tindakan berisiko tinggi."
LAYAR_KONFIRMASI_SALAH = "Teks yang diketik tidak sama dengan petunjuk di kartu. Periksa lagi lalu setujui."
HASIL_MENUNGGU_KEDUA = ("Disetujui pengguna, tetapi BELUM dijalankan: menunggu persetujuan kedua owner di layar "
                        "Tindakan AI ({alasan}). Sampaikan ini ke pengguna; jangan menganggapnya sudah berhasil.")
PESAN_MENUNGGU_KEDUA = "Menunggu persetujuan kedua owner sebelum dijalankan."
PESAN_KEDUA_KEDALUWARSA = "Persetujuan kedua tidak diberikan dalam 3 hari, jadi tindakan tidak dijalankan."
LAYAR_SUDAH = {
    "disetujui": "Tindakan ini sedang dijalankan. Tunggu sebentar lalu muat ulang.",
    "dijalankan": "Tindakan ini sudah disetujui dan dijalankan.",
    "dibatalkan": "Tindakan ini sudah dibatalkan.",
    "gagal": "Tindakan ini sudah diputuskan dan gagal dijalankan.",
    "kedaluwarsa": "Kartu tindakan ini sudah kedaluwarsa. Minta Asisten AI menyiapkannya lagi bila masih perlu.",
    "dibalikkan": "Tindakan ini sudah dijalankan lalu dibalikkan.",
}
LAYAR_SIBUK = "Tindakan ini sedang diproses. Tunggu sebentar lalu muat ulang."
PESAN_KEDALUWARSA_WAKTU = "Kartu tidak diputuskan dalam 24 jam, jadi tindakan tidak dijalankan."
PESAN_KEDALUWARSA_PESAN = "Tidak diputuskan karena ada pesan baru, jadi tindakan tidak dijalankan."
PESAN_KEDALUWARSA_HENTI = "Jawaban dihentikan sebelum kartu selesai disiapkan, jadi tindakan tidak dijalankan."
PESAN_PROSES_TERHENTI = ("Proses berhenti sebelum selesai, sehingga hasilnya tidak pasti. Periksa layar terkait "
                         "sebelum mencoba lagi.")


class GalatTindakan(Exception):
    """Galat keputusan/pembatalan dengan kode HTTP + pesan ramah (diteruskan route sebagai HTTPException)."""

    def __init__(self, status: int, pesan: str):
        super().__init__(pesan)
        self.status = int(status)
        self.pesan = str(pesan)


# ── Pembantu umum ────────────────────────────────────────────────────────────
def _sekarang() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _sekarang()).isoformat()


def id_baru() -> str:
    return str(uuid.uuid4())


def tanggal_wib(dt: Optional[datetime] = None) -> str:
    from utils.waktu import wib_date_str
    return wib_date_str(dt)


def _teks(v: Any, batas: int = 600) -> str:
    if v is None:
        return ""
    s = " ".join(str(v).split()) if not isinstance(v, str) else v.strip()
    return s[:batas]


def _tampil(v: Any) -> str:
    """Nilai tampilan kartu (string sudah berformat; kosong = '—')."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return "—"
    if isinstance(v, bool):
        return "Ya" if v else "Tidak"
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    if isinstance(v, float) and math.isfinite(v):
        return f"{v:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".").rstrip("0").rstrip(",")
    return _teks(v, 300)


def nama_pengguna(user: dict) -> str:
    return str(user.get("name") or user.get("full_name") or user.get("nama") or user.get("email")
               or user.get("id") or "-")[:120]


def boleh_semua(user: dict) -> bool:
    return str(user.get("role") or "").lower() in PERAN_SEMUA


def _json_aman(v: Any) -> Any:
    return json.loads(json.dumps(v, ensure_ascii=False, default=ab._json_default))


_HILANG = object()


def _bagian(kunci: str) -> list:
    return [int(p) if p.isdigit() else p for p in str(kunci).split(".") if p != ""]


def ambil_path(obj: Any, kunci: str) -> Any:
    cur = obj
    for p in _bagian(kunci):
        if isinstance(p, int) and isinstance(cur, list) and 0 <= p < len(cur):
            cur = cur[p]
        elif isinstance(cur, dict) and str(p) in cur:
            cur = cur[str(p)]
        else:
            return _HILANG
    return cur


def pasang_path(obj: Any, kunci: str, nilai: Any) -> None:
    parts = _bagian(kunci)
    cur = obj
    for p in parts[:-1]:
        cur = cur[p] if isinstance(p, int) else cur[str(p)]
    last = parts[-1]
    if isinstance(last, int):
        cur[last] = nilai
    else:
        cur[str(last)] = nilai


# ── Pengaturan (dok `ai_config` yang sama dengan Monitor AI) ─────────────────
def _rupiah_int(v) -> int:
    try:
        iv = int(v)
    except (TypeError, ValueError):
        return 0
    return max(0, iv) if not isinstance(v, bool) else 0


async def pengaturan() -> dict:
    """{"aktif", "batas", "batas_nominal_transaksi", "batas_nominal_harian"} — saklar "Tindakan AI aktif", batas
    tindakan per pengguna per hari, dan batas nominal kartu uang (K4; 0 = belum diisi → selalu persetujuan kedua)."""
    s = await tracker.get_ai_settings()
    aktif = s.get("asisten_tindakan_aktif", True)
    try:
        batas = int(s.get("asisten_batas_tindakan_harian", BATAS_BAWAAN))
    except (TypeError, ValueError):
        batas = BATAS_BAWAAN
    return {"aktif": aktif is not False, "batas": max(0, batas),
            "batas_nominal_transaksi": _rupiah_int(s.get("asisten_batas_nominal_transaksi")),
            "batas_nominal_harian": _rupiah_int(s.get("asisten_batas_nominal_harian"))}


async def nominal_hari_ini(db, user_id: str, tanggal: Optional[str] = None) -> float:
    """Jumlah nominal kartu uang (golongan C) pengguna ini yang sudah/sedang dijalankan hari ini (WIB)."""
    total = 0.0
    async for r in db.ai_actions.find({"user_id": user_id, "tanggal_jalan": tanggal or tanggal_wib(),
                                       "golongan": "C", "keadaan": {"$in": list(KEADAAN_TERHITUNG)}},
                                      {"_id": 0, "nominal": 1}):
        try:
            total += float(r.get("nominal") or 0)
        except (TypeError, ValueError):
            continue
    return total


async def jumlah_hari_ini(db, user_id: str, tanggal: Optional[str] = None) -> int:
    """Tindakan yang sudah (atau sedang) dijalankan pengguna ini hari ini (WIB)."""
    return await db.ai_actions.count_documents({"user_id": user_id, "tanggal_jalan": tanggal or tanggal_wib(),
                                                "keadaan": {"$in": list(KEADAAN_TERHITUNG)}})


# ── Rencana (isi kartu) ──────────────────────────────────────────────────────
def _rapikan_ubah(u: Any, args: dict) -> Optional[dict]:
    if not isinstance(u, dict):
        return None
    kunci = str(u.get("kunci") or "").strip()
    jenis = u.get("jenis")
    if not kunci or jenis not in JENIS_UBAH:
        log.warning("Rencana tindakan: isian ubah %r dilewati (kunci/jenis tidak sah)", kunci)
        return None
    sekarang = ambil_path(args, kunci)
    if sekarang is _HILANG:
        log.warning("Rencana tindakan: isian ubah %r tidak ada di isian alat (dilewati)", kunci)
        return None
    item = {"kunci": kunci, "label": _teks(u.get("label"), 120) or kunci, "jenis": jenis,
            "nilai": u.get("nilai", sekarang)}
    if jenis == "pilihan":
        pil = [{"nilai": p.get("nilai"), "label": _teks(p.get("label"), 120) or _tampil(p.get("nilai"))}
               for p in (u.get("pilihan") or []) if isinstance(p, dict) and "nilai" in p]
        if not pil:
            return None
        item["pilihan"] = pil
    return item


def rapikan_rencana(rencana: Any, args: dict, alat: ab.Alat) -> dict:
    """Validasi + normalisasi Rencana dari `siapkan`. AlatError → kembali ke model sebagai galat."""
    if not isinstance(rencana, dict):
        raise ab.AlatError(500, "Rencana tindakan tidak sah: alat tidak mengembalikan rencana perubahan.")
    perubahan = []
    for p in rencana.get("perubahan") or []:
        if isinstance(p, dict):
            perubahan.append({"label": _teks(p.get("label"), 160) or "—", "sebelum": _tampil(p.get("sebelum")),
                              "sesudah": _tampil(p.get("sesudah"))})
    out = {
        "judul": _teks(rencana.get("judul"), 160) or alat.label,
        "ringkas": _teks(rencana.get("ringkas"), 600),
        "perubahan": perubahan,
        "catatan": [t for t in (_teks(x, 400) for x in (rencana.get("catatan") or [])) if t],
        "peringatan": [t for t in (_teks(x, 400) for x in (rencana.get("peringatan") or [])) if t],
        "ubah": [u for u in (_rapikan_ubah(x, args) for x in (rencana.get("ubah") or [])) if u],
    }
    taut = rencana.get("tautan")
    if isinstance(taut, dict) and isinstance(taut.get("menu"), str) and ab._MENU_RX.match(taut["menu"]):
        out["tautan"] = {"label": _teks(taut.get("label"), 80) or "Buka layar terkait", "menu": taut["menu"]}
    elif alat.menu:
        out["tautan"] = {"label": "Buka layar terkait", "menu": alat.menu}
    # 12 Nov 2026 (katalog aksi, K3/K4): risiko per kartu, golongan, konfirmasi ketik ulang, persetujuan kedua,
    # sidik nilai lama (diperiksa ulang saat dijalankan), nominal kartu uang.
    if rencana.get("risiko") in ab.RISIKO:
        out["risiko"] = rencana["risiko"]
    if rencana.get("golongan") in ("A", "B", "C", "D"):
        out["golongan"] = rencana["golongan"]
        out["golongan_label"] = _teks(rencana.get("golongan_label"), 60)
    k = rencana.get("konfirmasi")
    if isinstance(k, dict) and _teks(k.get("teks"), 80):
        out["konfirmasi"] = {"teks": _teks(k.get("teks"), 80), "petunjuk": _teks(k.get("petunjuk"), 200)}
    pk = rencana.get("persetujuan_kedua")
    if isinstance(pk, dict) and pk.get("perlu"):
        out["persetujuan_kedua"] = {"perlu": True, "alasan": _teks(pk.get("alasan"), 300)}
    if isinstance(rencana.get("sidik"), str) and re.fullmatch(r"[0-9a-f]{8,64}", rencana["sidik"]):
        out["sidik"] = rencana["sidik"]
    nom = rencana.get("nominal")
    if isinstance(nom, (int, float)) and not isinstance(nom, bool) and math.isfinite(nom) and nom >= 0:
        out["nominal"] = nom
    out = _json_aman(out)
    if len(json.dumps(out, ensure_ascii=False)) > BATAS_RENCANA:
        raise ab.AlatError(400, "Rencana perubahan terlalu besar untuk satu kartu. Persempit perubahannya "
                                "(mis. per toko atau per periode) lalu siapkan lagi.")
    return out


def _paksa_nilai(nilai: Any, u: dict) -> Any:
    jenis, label = u["jenis"], u.get("label") or "Isian"
    if jenis in ("rupiah", "angka"):
        v = nilai
        if isinstance(v, str):
            s = v.strip()
            if jenis == "rupiah":
                s = re.sub(r"[^\d,\-]", "", s).split(",")[0]
            else:
                s = s.replace(" ", "")
                if "," in s:
                    s = s.replace(".", "").replace(",", ".")
            try:
                v = float(s) if s not in ("", "-") else None
            except ValueError:
                v = None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise GalatTindakan(400, f"{label}: isi dengan angka.")
        if jenis == "rupiah" and v < 0:
            raise GalatTindakan(400, f"{label}: tidak boleh negatif.")
        return int(v) if float(v).is_integer() else v
    if jenis == "teks":
        if not isinstance(nilai, (str, int, float)) or isinstance(nilai, bool):
            raise GalatTindakan(400, f"{label}: isi dengan teks.")
        s = str(nilai).strip()
        if not s:
            raise GalatTindakan(400, f"{label}: wajib diisi.")
        return s[:2000]
    if jenis == "tanggal":
        s = str(nilai or "").strip()[:10]
        try:
            date.fromisoformat(s)
        except ValueError:
            raise GalatTindakan(400, f"{label}: tanggal tidak sah.") from None
        return s
    # pilihan
    for p in u.get("pilihan") or []:
        if p.get("nilai") == nilai or str(p.get("nilai")) == str(nilai):
            return p.get("nilai")
    raise GalatTindakan(400, f"{label}: pilih salah satu pilihan yang tersedia.")


def terapkan_ubahan(args: dict, rencana: dict, ubahan: Any) -> tuple[dict, dict]:
    """Ubahan kartu {kunci: nilai} → (args baru, ubahan bersih). Hanya kunci di `rencana.ubah`."""
    if ubahan in (None, {}):
        return copy.deepcopy(args), {}
    if not isinstance(ubahan, dict):
        raise GalatTindakan(400, "Isian perubahan di kartu tidak sah.")
    izin = {u["kunci"]: u for u in (rencana.get("ubah") or [])}
    baru = copy.deepcopy(args)
    bersih = {}
    for kunci, nilai in ubahan.items():
        u = izin.get(str(kunci))
        if u is None:
            raise GalatTindakan(400, "Ada isian yang tidak boleh diubah di kartu ini. Muat ulang lalu coba lagi.")
        v = _paksa_nilai(nilai, u)
        pasang_path(baru, u["kunci"], v)
        bersih[u["kunci"]] = v
    return baru, bersih


# ── Dokumen & tampilan ───────────────────────────────────────────────────────
def _bisa_dibalikkan(doc: dict) -> bool:
    return doc.get("keadaan") == "dijalankan" and bool(doc.get("bisa_dibalikkan"))


def _ringkas_baris(doc: dict) -> str:
    k = doc.get("keadaan")
    if k in ("dijalankan", "dibalikkan") and doc.get("ringkas"):
        return doc["ringkas"] if k == "dijalankan" else f"{doc['ringkas']} (dibalikkan)"
    if k in ("gagal", "kedaluwarsa", "dibatalkan") and doc.get("pesan"):
        return doc["pesan"]
    return (doc.get("rencana") or {}).get("ringkas") or ""


def event_kartu(doc: dict) -> dict:
    """Data event SSE `tindakan` (Kontrak E)."""
    return {"id": doc["id"], "nama": doc["nama"], "label": doc["label"], "risiko": doc["risiko"],
            "keadaan": doc["keadaan"], "rencana": doc["rencana"], "kedaluwarsa_pada": doc["kedaluwarsa_pada"]}


def blok_kartu(doc: dict) -> dict:
    """Blok tersimpan `tindakan` dengan keadaan SAAT INI (Kontrak E)."""
    b = {"jenis": "tindakan", **event_kartu(doc), "bisa_dibalikkan": _bisa_dibalikkan(doc)}
    for k in ("ringkas", "pesan"):
        if doc.get(k):
            b[k] = doc[k]
    return b


async def buat(db, *, user: dict, sesi_id: str, pesan_id: Optional[str], tool_use_id: str, alat: ab.Alat,
               args: dict, rencana: dict, cv: str, periode: str, tindakan_id: Optional[str] = None,
               ruang: str = "umum") -> dict:
    """Simpan kartu baru berstatus `menunggu`."""
    now = _sekarang()
    doc = {
        "id": tindakan_id or id_baru(), "user_id": user.get("id"),
        "pengguna": {"id": user.get("id"), "nama": nama_pengguna(user)},
        "sesi_id": sesi_id, "pesan_id": pesan_id, "tool_use_id": tool_use_id,
        "nama": alat.name, "label": alat.label, "risiko": rencana.get("risiko") or alat.risiko or "rendah",
        "menu": alat.menu or (rencana.get("tautan") or {}).get("menu"),
        "golongan": rencana.get("golongan"), "nominal": rencana.get("nominal"),
        "args": _json_aman(args), "args_awal": _json_aman(args), "rencana": rencana, "keadaan": "menunggu",
        "cv": cv, "periode": periode, "ruang": ruang, "tanggal": tanggal_wib(now), "dibuat": _iso(now),
        "diperbarui": _iso(now),
        "kedaluwarsa_pada": _iso(now + MASA_BERLAKU), KUNCI: None, f"{KUNCI}_at": None,
    }
    await db.ai_actions.insert_one(dict(doc))
    return doc


async def rawat(db, filt: dict) -> None:
    """Pemeriksaan malas: kartu `menunggu` > 24 jam → `kedaluwarsa`; `disetujui` yang kuncinya basi
    (proses mati di tengah `jalankan`) → `gagal` dengan pesan "hasil tidak pasti"."""
    now = _sekarang()
    base = {k: v for k, v in (filt or {}).items()}
    await db.ai_actions.update_many(
        {**base, "keadaan": "menunggu", "kedaluwarsa_pada": {"$lt": _iso(now)}, **doc_lock.lock_free(KUNCI)},
        {"$set": {"keadaan": "kedaluwarsa", "pesan": PESAN_KEDALUWARSA_WAKTU, "selesai_pada": _iso(now),
                  "diperbarui": _iso(now)}})
    await db.ai_actions.update_many(
        {**base, "keadaan": "menunggu_kedua", "kedaluwarsa_pada": {"$lt": _iso(now)}, **doc_lock.lock_free(KUNCI)},
        {"$set": {"keadaan": "kedaluwarsa", "pesan": PESAN_KEDUA_KEDALUWARSA, "selesai_pada": _iso(now),
                  "diperbarui": _iso(now), "kedua_selesai": True}})
    await db.ai_actions.update_many(
        {**base, "keadaan": "disetujui", f"{KUNCI}_at": {"$lt": now - doc_lock.STALE}},
        {"$set": {"keadaan": "gagal", "pesan": PESAN_PROSES_TERHENTI, "selesai_pada": _iso(now),
                  "diperbarui": _iso(now), KUNCI: None, f"{KUNCI}_at": None}})


async def ambil(db, tindakan_id: str) -> Optional[dict]:
    if not tindakan_id or not isinstance(tindakan_id, str):
        return None
    await rawat(db, {"id": tindakan_id})
    return await db.ai_actions.find_one({"id": tindakan_id}, {"_id": 0})


async def kedaluwarsakan_sesi(db, user_id: str, sesi_id: str) -> None:
    """Percakapan dihapus → kartu yang masih menunggu tidak bisa diputuskan lagi."""
    now = _iso()
    await db.ai_actions.update_many({"sesi_id": sesi_id, "user_id": user_id, "keadaan": "menunggu",
                                     **doc_lock.lock_free(KUNCI)},
                                    {"$set": {"keadaan": "kedaluwarsa", "selesai_pada": now, "diperbarui": now,
                                              "pesan": "Percakapan dihapus sebelum kartu diputuskan."}})


async def kedaluwarsakan_pesan(db, pesan_id: Optional[str], pesan: str = PESAN_KEDALUWARSA_HENTI) -> None:
    """Kartu yatim (jawaban dihentikan sebelum giliran berhenti untuk konfirmasi) → `kedaluwarsa`."""
    if not pesan_id:
        return
    await db.ai_actions.update_many({"pesan_id": pesan_id, "keadaan": "menunggu", **doc_lock.lock_free(KUNCI)},
                                    {"$set": {"keadaan": "kedaluwarsa", "pesan": pesan, "selesai_pada": _iso(),
                                              "diperbarui": _iso()}})


# ── Hasil untuk model ────────────────────────────────────────────────────────
def _label_ubahan(doc: dict) -> str:
    lab = {u["kunci"]: u.get("label") or u["kunci"] for u in ((doc.get("rencana") or {}).get("ubah") or [])}
    return "; ".join(f"{lab.get(k, k)} = {_tampil(v)}" for k, v in (doc.get("ubahan") or {}).items())


def teks_hasil(doc: dict) -> tuple[str, bool]:
    """(isi tool_result, is_error) untuk keadaan akhir sebuah kartu."""
    k = doc.get("keadaan")
    if k in ("dijalankan", "dibalikkan"):
        t = HASIL_DIJALANKAN.format(ringkas=doc.get("ringkas") or "tindakan selesai.")
        if doc.get("ubahan"):
            t += f"\nPengguna mengubah isian di kartu sebelum menyetujui: {_label_ubahan(doc)}."
        if doc.get("hasil"):
            t += "\nRincian hasil: " + ab.potong(ab.serialisasi(doc["hasil"]), 2000)
        if k == "dibalikkan":
            balik = (doc.get("hasil_balik") or {}).get("ringkas") or "nilai lama dipulihkan"
            t += f"\nSesudah itu pengguna MEMBALIKKAN tindakan ini: {balik}."
        return t, False
    if k == "dibatalkan":
        return HASIL_DIBATALKAN, False
    if k == "gagal":
        return HASIL_GAGAL.format(pesan=doc.get("pesan") or "tindakan tidak berhasil."), True
    if k == "kedaluwarsa":
        return HASIL_KEDALUWARSA, False
    if k == "menunggu_kedua":
        alasan = ((doc.get("rencana") or {}).get("persetujuan_kedua") or {}).get("alasan") or "kartu uang"
        return HASIL_MENUNGGU_KEDUA.format(alasan=alasan), False
    return HASIL_MASIH_PROSES, True


def hasil_untuk_model(doc: dict) -> dict:
    isi, err = teks_hasil(doc)
    b = {"type": "tool_result", "tool_use_id": doc["tool_use_id"], "content": isi}
    if err:
        b["is_error"] = True
    return b


def _hasil_umum(tool_use_id: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True, "content": HASIL_TIDAK_DIJALANKAN}


def tool_use_terbuka(riwayat: list[dict]) -> list[str]:
    """Id tool_use di giliran asisten TERAKHIR yang belum dibalas (giliran berhenti menunggu kartu)."""
    if not riwayat or riwayat[-1].get("role") != "assistant":
        return []
    return [b.get("id") for b in (riwayat[-1].get("content") or [])
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")]


async def _tandai_dikabarkan(db, docs: list[dict]) -> None:
    ids = [d["id"] for d in docs if d.get("keadaan") == "dibalikkan" and not d.get("dikabarkan_balik")]
    if ids:
        await db.ai_actions.update_many({"id": {"$in": ids}}, {"$set": {"dikabarkan_balik": True}})


async def tutup_terbuka(db, user_id: str, sesi_id: str, riwayat: list[dict]) -> tuple[list[dict], list[dict]]:
    """Pesan baru dikirim: balas SEMUA tool_use yang masih terbuka di ekor riwayat.

    Kartu yang masih `menunggu` → `kedaluwarsa` (atomik). Return (blok tool_result berurutan untuk ditaruh di
    DEPAN giliran pengguna baru, event `tindakan_status` untuk layar)."""
    ids = tool_use_terbuka(riwayat)
    if not ids:
        return [], []
    p_tunda = await simpan.pesan_tunda(db, user_id, sesi_id)
    tunda = (p_tunda or {}).get("tunda") or {}
    tersimpan = {b.get("tool_use_id"): b for b in (tunda.get("hasil") or []) if isinstance(b, dict)}
    await rawat(db, {"sesi_id": sesi_id, "user_id": user_id})
    docs = {d["tool_use_id"]: d for d in await db.ai_actions.find(
        {"sesi_id": sesi_id, "user_id": user_id, "tool_use_id": {"$in": ids}}, {"_id": 0}).to_list(50)}
    blok, events, dipakai = [], [], []
    for tid in ids:
        if tid in tersimpan:
            blok.append(tersimpan[tid])
            continue
        d = docs.get(tid)
        if d is None:
            blok.append(_hasil_umum(tid))
            continue
        if d.get("keadaan") == "menunggu":
            now = _iso()
            res = await db.ai_actions.update_one(
                {"id": d["id"], "keadaan": "menunggu", **doc_lock.lock_free(KUNCI)},
                {"$set": {"keadaan": "kedaluwarsa", "pesan": PESAN_KEDALUWARSA_PESAN, "selesai_pada": now,
                          "diperbarui": now}})
            if getattr(res, "matched_count", 0):
                d.update(keadaan="kedaluwarsa", pesan=PESAN_KEDALUWARSA_PESAN)
                events.append({"id": d["id"], "keadaan": "kedaluwarsa", "pesan": PESAN_KEDALUWARSA_PESAN})
            else:
                d = await db.ai_actions.find_one({"id": d["id"]}, {"_id": 0}) or d
        blok.append(hasil_untuk_model(d))
        dipakai.append(d)
    await _tandai_dikabarkan(db, dipakai)
    if p_tunda and tunda.get("keadaan") == "menunggu":
        await simpan.tutup_tunda(db, user_id, p_tunda["id"], "pesan_baru")
    return blok, events


async def siap_lanjut(db, user_id: str, pesan_id: str) -> Optional[tuple[dict, int]]:
    """Semua kartu giliran `pesan_id` sudah diputuskan? → (giliran pengguna berisi SEMUA tool_result menurut
    urutan tool_use, jumlah putaran alat). None bila masih ada yang menunggu / sudah dilanjutkan pihak lain."""
    p = await db.ai_chat_messages.find_one({"id": pesan_id, "user_id": user_id}, {"_id": 0})
    tunda = (p or {}).get("tunda") or {}
    if tunda.get("keadaan") != "menunggu":
        return None
    ids = list(tunda.get("tindakan") or [])
    await rawat(db, {"id": {"$in": ids}})
    docs = await db.ai_actions.find({"id": {"$in": ids}, "user_id": user_id}, {"_id": 0}).to_list(50)
    if any(d.get("keadaan") in KEADAAN_TERBUKA for d in docs):
        return None
    if not await simpan.tutup_tunda(db, user_id, pesan_id, "putusan"):
        return None
    tersimpan = {b.get("tool_use_id"): b for b in (tunda.get("hasil") or []) if isinstance(b, dict)}
    per_tid = {d["tool_use_id"]: d for d in docs}
    isi = []
    for tid in tunda.get("urutan") or []:
        if tid in tersimpan:
            isi.append(tersimpan[tid])
        elif tid in per_tid:
            isi.append(hasil_untuk_model(per_tid[tid]))
        else:
            isi.append(_hasil_umum(tid))
    await _tandai_dikabarkan(db, docs)
    return {"role": "user", "content": isi}, int(tunda.get("putaran_alat") or 0)


async def kabar_dibalikkan(db, user_id: str, sesi_id: str) -> Optional[str]:
    """Blok konteks untuk giliran pengguna baru: tindakan di percakapan ini yang DIBALIKKAN sesudah
    hasilnya dikabarkan ke model (append-only: riwayat lama tidak diubah)."""
    rows = await db.ai_actions.find({"sesi_id": sesi_id, "user_id": user_id, "keadaan": "dibalikkan",
                                     "dikabarkan_balik": {"$ne": True}}, {"_id": 0}).to_list(20)
    # 12 Nov 2026 (K4): hasil persetujuan kedua yang belum dikabarkan ke model.
    kedua = await db.ai_actions.find({"sesi_id": sesi_id, "user_id": user_id, "kedua_selesai": True,
                                      "dikabarkan_kedua": False}, {"_id": 0}).to_list(20)
    if not rows and not kedua:
        return None
    if rows:
        await db.ai_actions.update_many({"id": {"$in": [r["id"] for r in rows]}}, {"$set": {"dikabarkan_balik": True}})
    if kedua:
        await db.ai_actions.update_many({"id": {"$in": [r["id"] for r in kedua]}},
                                        {"$set": {"dikabarkan_kedua": True}})
    baris = [f"- Tindakan \"{(r.get('rencana') or {}).get('judul') or r.get('label')}\" yang sebelumnya "
             "dijalankan sudah DIBALIKKAN pengguna (nilai lama dipulihkan)." for r in rows]
    for r in kedua:
        judul = (r.get("rencana") or {}).get("judul") or r.get("label")
        k = r.get("keadaan")
        if k == "dijalankan":
            baris.append(f"- Tindakan \"{judul}\" sudah mendapat persetujuan kedua dan DIJALANKAN: "
                         f"{r.get('ringkas') or 'selesai'}.")
        elif k == "gagal":
            baris.append(f"- Tindakan \"{judul}\" mendapat persetujuan kedua tetapi GAGAL: {r.get('pesan') or ''}")
        else:
            baris.append(f"- Tindakan \"{judul}\" TIDAK dijalankan: {r.get('pesan') or 'persetujuan kedua ditolak'}.")
    isi = "\n".join(baris)
    return f"<konteks_sistem>\nCatatan sistem sejak pesan terakhir:\n{isi}\n</konteks_sistem>"


# ── Konteks alat untuk siapkan / jalankan / batalkan ─────────────────────────
def buat_ctx(*, user: dict, doc: dict, token: Optional[str], app=None, klien_api=None, tulis: bool,
             emit: Optional[Callable[[str, dict], None]] = None, today=None) -> ab.AlatContext:
    from utils.waktu import today_wib
    return ab.AlatContext(user=user, cv=doc.get("cv") or "DA", today=today or today_wib(), token=token, app=app,
                          emit=emit, klien_api=klien_api, alat_id=doc.get("tool_use_id"),
                          sesi_id=doc.get("sesi_id"), db=None, baca_saja=not tulis, tindakan_id=doc["id"],
                          ruang=doc.get("ruang") or "umum")


# ── Keputusan ────────────────────────────────────────────────────────────────
@dataclass
class Putusan:
    doc: dict
    alat: Optional[ab.Alat]
    keputusan: str
    kunci: str
    alasan: str = ""
    ubahan: dict = field(default_factory=dict)
    args: dict = field(default_factory=dict)
    rencana: dict = field(default_factory=dict)


def _galat_keadaan(doc: dict) -> GalatTindakan:
    return GalatTindakan(409, LAYAR_SUDAH.get(doc.get("keadaan"), "Tindakan ini tidak lagi menunggu keputusan."))


def konfirmasi_cocok(diketik: Any, harus: str) -> bool:
    """Teks ketik ulang (risiko tinggi) sama dengan petunjuk kartu. Angka: dibandingkan digitnya saja (titik, koma,
    "Rp", spasi diabaikan); teks lain: tanpa beda huruf besar/kecil dan spasi tepi."""
    harus = str(harus or "").strip()
    d = str(diketik or "").strip()
    if not harus or not d:
        return False
    if re.fullmatch(r"\d+", harus):
        return re.sub(r"\D", "", d.split(",")[0]) == harus
    return " ".join(d.lower().split()) == " ".join(harus.lower().split())


async def periksa_dan_kunci(db, user: dict, doc: dict, *, keputusan: str, ubahan: Any, alasan: str,
                            buat_ctx_baca: Callable[[dict], ab.AlatContext], batas: Optional[int] = None,
                            konfirmasi: Any = None) -> Putusan:
    """Semua pemeriksaan SEBELUM aliran dimulai (galat → HTTP 4xx), lalu klaim atomik kartu.

    Setujui: saklar menyala, alat masih ada, alasan (risiko menengah), batas harian, ubahan sah → `siapkan`
    dijalankan ULANG dengan isian baru (validasi penuh lagi). Batal: selalu boleh selama masih menunggu.
    `batas` (10 Nov 2026) = batas tindakan per hari akun ini (`akses_pengguna`); None = batas bawaan."""
    if keputusan not in ("setujui", "batal"):
        raise GalatTindakan(400, "Keputusan harus setujui atau batal.")
    if doc.get("keadaan") != "menunggu":
        raise _galat_keadaan(doc)
    alasan = str(alasan or "").strip()[:500]
    alat = ab.cari_tindakan(doc.get("nama") or "")
    ubahan_bersih: dict = {}
    args = copy.deepcopy(doc.get("args") or {})
    if keputusan == "setujui":
        aturan = await pengaturan()
        if not aturan["aktif"]:
            raise GalatTindakan(409, LAYAR_MATI)
        if alat is None:
            raise GalatTindakan(409, "Alat untuk tindakan ini tidak tersedia lagi, jadi kartu tidak bisa disetujui. "
                                     "Kartu masih bisa dibatalkan.")
        risiko = doc.get("risiko") or alat.risiko
        if risiko == "menengah" and len(alasan) < MIN_ALASAN_MENENGAH:
            raise GalatTindakan(400, LAYAR_ALASAN)
        if risiko == "tinggi":
            # 12 Nov 2026 (K4): alasan + ketik ulang nominal / nomor dokumen sesuai petunjuk kartu.
            if len(alasan) < MIN_ALASAN_MENENGAH:
                raise GalatTindakan(400, LAYAR_ALASAN_TINGGI)
            harus = ((doc.get("rencana") or {}).get("konfirmasi") or {}).get("teks") or "SETUJU"
            if not str(konfirmasi or "").strip():
                raise GalatTindakan(400, LAYAR_KONFIRMASI)
            if not konfirmasi_cocok(konfirmasi, harus):
                raise GalatTindakan(400, LAYAR_KONFIRMASI_SALAH)
        batas = aturan["batas"] if batas is None else batas
        if await jumlah_hari_ini(db, doc["user_id"]) >= batas:
            raise GalatTindakan(409, LAYAR_BATAS.format(batas=batas))
        args, ubahan_bersih = terapkan_ubahan(args, doc.get("rencana") or {}, ubahan)
        if ubahan_bersih:
            errs = ab.periksa_skema(alat.input_schema, args)
            if errs:
                raise GalatTindakan(400, "Isian di kartu tidak sah: " + "; ".join(errs[:3]) + ".")
    elif ubahan not in (None, {}):
        raise GalatTindakan(400, "Kartu yang dibatalkan tidak perlu isian perubahan.")
    try:
        kunci = await doc_lock.claim(db, KOLEKSI, doc["id"], field=KUNCI,
                                     extra={"keadaan": "menunggu", "user_id": doc["user_id"]},
                                     busy=LAYAR_SIBUK, not_found=LAYAR_TIDAK_ADA, actor=user)
    except Exception as e:  # noqa: BLE001 — HTTPException dari doc_lock
        status = getattr(e, "status_code", 409)
        if status == 409:
            terbaru = await db.ai_actions.find_one({"id": doc["id"]}, {"_id": 0})
            if terbaru and terbaru.get("keadaan") != "menunggu":
                raise _galat_keadaan(terbaru) from None
        raise GalatTindakan(status, str(getattr(e, "detail", "") or LAYAR_SIBUK)) from None
    rencana = doc.get("rencana") or {}
    if ubahan_bersih:
        ctx = buat_ctx_baca(doc)
        try:
            baru = await asyncio.wait_for(alat.siapkan(ctx, copy.deepcopy(args)), timeout=ab.BATAS_DETIK_ALAT)
            rencana = rapikan_rencana(baru, args, alat)
        except ab.AlatError as e:
            await doc_lock.release(db, KOLEKSI, doc["id"], kunci, field=KUNCI)
            raise GalatTindakan(400, e.pesan) from None
        except asyncio.TimeoutError:
            await doc_lock.release(db, KOLEKSI, doc["id"], kunci, field=KUNCI)
            raise GalatTindakan(504, "Pemeriksaan ulang isian terlalu lama. Coba lagi.") from None
        except Exception:  # noqa: BLE001
            log.exception("siapkan ulang tindakan %s gagal", doc.get("nama"))
            await doc_lock.release(db, KOLEKSI, doc["id"], kunci, field=KUNCI)
            raise GalatTindakan(500, "Isian di kartu tidak bisa diperiksa ulang. Coba lagi atau batalkan kartu.") \
                from None
        finally:
            await ctx.tutup()
        await db.ai_actions.update_one({"id": doc["id"], KUNCI: kunci},
                                       {"$set": {"args": _json_aman(args), "rencana": rencana,
                                                 "ubahan": _json_aman(ubahan_bersih), "diperbarui": _iso()}})
    return Putusan(doc=doc, alat=alat, keputusan=keputusan, kunci=kunci, alasan=alasan, ubahan=ubahan_bersih,
                   args=args, rencana=rencana)


async def lepas(db, p: Putusan) -> None:
    await doc_lock.release(db, KOLEKSI, p.doc["id"], p.kunci, field=KUNCI)


def _rapikan_hasil(out: Any, p: Putusan) -> dict:
    out = out if isinstance(out, dict) else {}
    ringkas = _teks(out.get("ringkas"), 500) or f"{p.alat.label if p.alat else 'Tindakan'} selesai."
    hasil = out.get("hasil")
    try:
        hasil = _json_aman(hasil) if hasil is not None else None
    except (TypeError, ValueError):
        hasil = None
    if hasil is not None and len(json.dumps(hasil, ensure_ascii=False)) > BATAS_HASIL_SIMPAN:
        hasil = {"catatan": "Rincian hasil terlalu panjang untuk disimpan."}
    pembatalan = out.get("pembatalan")
    if pembatalan is not None:
        try:
            pembatalan = _json_aman(pembatalan)
        except (TypeError, ValueError):
            pembatalan = None
        if pembatalan is not None and len(json.dumps(pembatalan, ensure_ascii=False)) > BATAS_PEMBATALAN:
            log.warning("Tindakan %s: data pembatalan terlalu besar, tidak disimpan", p.doc.get("nama"))
            pembatalan = None
    perub = p.rencana.get("perubahan") or []
    sebelum = out.get("sebelum") if isinstance(out.get("sebelum"), (dict, list)) else \
        [{"label": x["label"], "nilai": x["sebelum"]} for x in perub]
    sesudah = out.get("sesudah") if isinstance(out.get("sesudah"), (dict, list)) else \
        [{"label": x["label"], "nilai": x["sesudah"]} for x in perub]
    bisa = bool(p.alat and p.alat.bisa_dibalikkan and pembatalan is not None)
    return {"ringkas": ringkas, "hasil": hasil, "pembatalan": pembatalan if bisa else None,
            "sebelum": _json_aman(sebelum), "sesudah": _json_aman(sesudah), "bisa_dibalikkan": bisa}


async def laksanakan(db, p: Putusan, ctx: ab.AlatContext, *, user: dict,
                     kirim: Callable[[dict], None]) -> dict:
    """Jalankan keputusan yang SUDAH diklaim (`periksa_dan_kunci`). Setujui → `jalankan` tepat sekali.
    Event `tindakan_status` dikirim lewat `kirim`. Return dokumen akhir."""
    tid = p.doc["id"]
    now = _iso()
    pemutus = {"id": user.get("id"), "nama": nama_pengguna(user)}
    if p.keputusan == "batal":
        upd = {"keadaan": "dibatalkan", "keputusan": "batal", "diputuskan_pada": now, "diputuskan_oleh": pemutus,
               "selesai_pada": now, "diperbarui": now, "pesan": "Dibatalkan pengguna. Tidak ada data yang diubah.",
               KUNCI: None, f"{KUNCI}_at": None}
        if p.alasan:
            upd["alasan"] = p.alasan
        await db.ai_actions.update_one({"id": tid, KUNCI: p.kunci}, {"$set": upd})
        kirim({"id": tid, "keadaan": "dibatalkan", "pesan": upd["pesan"]})
        return {**p.doc, **upd}
    pk = (p.rencana or {}).get("persetujuan_kedua") or {}
    if pk.get("perlu") and str(user.get("role") or "").lower() not in PERAN_KEDUA:
        # 12 Nov 2026 (K4): kartu uang di atas batas → disimpan menunggu persetujuan kedua owner; TIDAK dijalankan.
        upd = {"keadaan": "menunggu_kedua", "keputusan": "setujui", "diputuskan_pada": now,
               "diputuskan_oleh": pemutus, "diperbarui": now, "pesan": PESAN_MENUNGGU_KEDUA,
               "kedaluwarsa_pada": _iso(_sekarang() + MASA_KEDUA), KUNCI: None, f"{KUNCI}_at": None}
        if p.alasan:
            upd["alasan"] = p.alasan
        await db.ai_actions.update_one({"id": tid, KUNCI: p.kunci}, {"$set": upd})
        kirim({"id": tid, "keadaan": "menunggu_kedua", "pesan": PESAN_MENUNGGU_KEDUA})
        await _kabari_penyetuju_kedua(db, {**p.doc, **upd})
        return {**p.doc, **upd}
    upd0 = {"keadaan": "disetujui", "keputusan": "setujui", "diputuskan_pada": now, "diputuskan_oleh": pemutus,
            "dijalankan_pada": now, "tanggal_jalan": tanggal_wib(), "diperbarui": now}
    if p.alasan:
        upd0["alasan"] = p.alasan
    await db.ai_actions.update_one({"id": tid, KUNCI: p.kunci}, {"$set": upd0})
    kirim({"id": tid, "keadaan": "disetujui"})
    # ── Asisten AI (setuju) ── alasan keputusan dari kartu (wajib untuk risiko menengah) untuk alat yang
    # meneruskannya ke endpoint layar sebagai catatan/alasan, mis. alat/tindakan_persetujuan.py (cuti, lembur, PR, PO).
    ctx.alasan = p.alasan
    # ── /Asisten AI (setuju) ──
    try:
        out = await asyncio.wait_for(p.alat.jalankan(ctx, copy.deepcopy(p.args), copy.deepcopy(p.rencana)),
                                     timeout=BATAS_DETIK_TINDAKAN)
        h = _rapikan_hasil(out, p)
        upd = {"keadaan": "dijalankan", **h}
        ev = {"id": tid, "keadaan": "dijalankan", "ringkas": h["ringkas"]}
    except ab.AlatError as e:
        upd = {"keadaan": "gagal", "pesan": e.pesan}
        ev = {"id": tid, "keadaan": "gagal", "pesan": e.pesan}
    except asyncio.TimeoutError:
        msg = "Tindakan terlalu lama berjalan dan dihentikan. Periksa layar terkait untuk memastikan hasilnya."
        upd = {"keadaan": "gagal", "pesan": msg}
        ev = {"id": tid, "keadaan": "gagal", "pesan": msg}
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("Tindakan Asisten AI %s gagal dijalankan", p.doc.get("nama"))
        msg = "Terjadi kesalahan saat menjalankan tindakan. Periksa layar terkait sebelum mencoba lagi."
        upd = {"keadaan": "gagal", "pesan": msg}
        ev = {"id": tid, "keadaan": "gagal", "pesan": msg}
    selesai = _iso()
    upd.update({"selesai_pada": selesai, "diperbarui": selesai, KUNCI: None, f"{KUNCI}_at": None})
    await db.ai_actions.update_one({"id": tid, KUNCI: p.kunci}, {"$set": upd})
    kirim(ev)
    return {**p.doc, **upd0, **upd}


# ── Persetujuan kedua (12 Nov 2026, keputusan owner K4) ──────────────────────
async def _kabari_penyetuju_kedua(db, doc: dict) -> None:
    """Notifikasi ke owner/superadmin aktif (selain pembuat kartu) bahwa ada kartu menunggu persetujuan kedua."""
    try:
        from routes.notifications import create_notification
        judul = (doc.get("rencana") or {}).get("judul") or doc.get("label") or "Tindakan Asisten AI"
        nama = (doc.get("pengguna") or {}).get("nama") or "Pengguna"
        isi = f"{nama} menyetujui \"{judul}\" lewat Asisten AI. Perlu persetujuan kedua Anda di layar Tindakan AI."
        async for u in db.users.find({"role": {"$in": sorted(PERAN_KEDUA)}}, {"_id": 0, "id": 1, "is_active": 1,
                                                                             "status": 1, "active": 1}):
            if not u.get("id") or u["id"] == doc.get("user_id"):
                continue
            if u.get("is_active") is False or u.get("active") is False or str(u.get("status") or "").lower() in (
                    "inactive", "nonaktif", "disabled"):
                continue
            await create_notification(db, u["id"], "system", "Persetujuan kedua Asisten AI", isi,
                                      source_type="asisten_ai", source_id=doc.get("id") or "",
                                      source_url="tindakan-ai")
    except Exception:  # noqa: BLE001 — notifikasi tidak boleh menggagalkan keputusan
        log.exception("Notifikasi persetujuan kedua gagal dikirim")


def boleh_putuskan_kedua(user: dict, doc: dict) -> bool:
    return (doc.get("keadaan") == "menunggu_kedua" and str(user.get("role") or "").lower() in PERAN_KEDUA
            and doc.get("user_id") != user.get("id"))


async def _token_pembuat(db, user_id: str) -> tuple[str, dict]:
    """Token baru untuk PEMBUAT kartu: tindakan dijalankan sebagai dia (izin perannya sendiri), bukan sebagai
    penyetuju kedua. Akun harus masih ada dan aktif."""
    from auth import create_token
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password": 0, "password_hash": 0})
    if not u or u.get("is_active") is False or u.get("active") is False or \
            str(u.get("status") or "").lower() in ("inactive", "nonaktif", "disabled"):
        raise GalatTindakan(409, "Akun pembuat kartu sudah tidak aktif, jadi tindakan tidak bisa dijalankan.")
    if not u.get("email") or not u.get("role"):
        raise GalatTindakan(409, "Data akun pembuat kartu tidak lengkap, jadi tindakan tidak bisa dijalankan.")
    u.setdefault("name", u.get("email"))
    return create_token(u), u


async def putuskan_kedua(db, user: dict, tindakan_id: str, *, keputusan: str, alasan: str, app=None,
                         klien_api=None) -> dict:
    """Owner/superadmin (bukan pembuat kartu) menyetujui / menolak kartu `menunggu_kedua`.

    Setujui → `jalankan` alat SEKALI dengan token PEMBUAT kartu (izin & CV pembuat tetap berlaku), alasan kedua ikut
    dicatat. Tolak → `dibatalkan`. Hasil dikabarkan ke model di pesan berikutnya percakapan asal (`kabar_dibalikkan`)."""
    if keputusan not in ("setujui", "batal"):
        raise GalatTindakan(400, "Keputusan harus setujui atau batal.")
    doc = await ambil(db, tindakan_id)
    if not doc:
        raise GalatTindakan(404, LAYAR_TIDAK_ADA)
    if str(user.get("role") or "").lower() not in PERAN_KEDUA:
        raise GalatTindakan(403, "Hanya owner atau superadmin yang boleh memberi persetujuan kedua.")
    if doc.get("user_id") == user.get("id"):
        raise GalatTindakan(403, "Persetujuan kedua harus diberikan orang lain, bukan pembuat kartu.")
    if doc.get("keadaan") != "menunggu_kedua":
        raise _galat_keadaan(doc) if doc.get("keadaan") in LAYAR_SUDAH else \
            GalatTindakan(409, "Kartu ini tidak sedang menunggu persetujuan kedua.")
    alasan = str(alasan or "").strip()[:500]
    if len(alasan) < MIN_ALASAN_MENENGAH:
        raise GalatTindakan(400, f"Alasan persetujuan kedua wajib diisi (minimal {MIN_ALASAN_MENENGAH} karakter).")
    alat = ab.cari_tindakan(doc.get("nama") or "")
    if keputusan == "setujui":
        aturan = await pengaturan()
        if not aturan["aktif"]:
            raise GalatTindakan(409, LAYAR_MATI)
        if alat is None:
            raise GalatTindakan(409, "Alat untuk tindakan ini tidak tersedia lagi. Kartu masih bisa ditolak.")
    try:
        kunci = await doc_lock.claim(db, KOLEKSI, doc["id"], field=KUNCI, extra={"keadaan": "menunggu_kedua"},
                                     busy=LAYAR_SIBUK, not_found=LAYAR_TIDAK_ADA, actor=user)
    except Exception as e:  # noqa: BLE001
        raise GalatTindakan(getattr(e, "status_code", 409), str(getattr(e, "detail", "") or LAYAR_SIBUK)) from None
    now = _iso()
    oleh = {"id": user.get("id"), "nama": nama_pengguna(user)}
    dasar = {"kedua_oleh": oleh, "kedua_pada": now, "alasan_kedua": alasan, "kedua_selesai": True,
             "dikabarkan_kedua": False, "diperbarui": now}
    if keputusan == "batal":
        pesan = f"Ditolak pada persetujuan kedua oleh {oleh['nama']}: {alasan}"
        upd = {**dasar, "keadaan": "dibatalkan", "keputusan_kedua": "batal", "pesan": pesan, "selesai_pada": now,
               KUNCI: None, f"{KUNCI}_at": None}
        await db.ai_actions.update_one({"id": doc["id"], KUNCI: kunci}, {"$set": upd})
        return {"ok": True, "id": doc["id"], "keadaan": "dibatalkan", "pesan": pesan}
    try:
        token, pembuat = await _token_pembuat(db, doc["user_id"])
    except GalatTindakan:
        await doc_lock.release(db, KOLEKSI, doc["id"], kunci, field=KUNCI)
        raise
    await db.ai_actions.update_one({"id": doc["id"], KUNCI: kunci},
                                   {"$set": {**dasar, "keadaan": "disetujui", "keputusan_kedua": "setujui",
                                             "dijalankan_pada": now, "tanggal_jalan": tanggal_wib()}})
    ctx = buat_ctx(user=pembuat, doc=doc, token=token, app=app, klien_api=klien_api, tulis=True)
    ctx.alasan = "; ".join(x for x in (doc.get("alasan"), f"Persetujuan kedua {oleh['nama']}: {alasan}") if x)
    p = Putusan(doc=doc, alat=alat, keputusan="setujui", kunci=kunci, alasan=doc.get("alasan") or "",
                args=copy.deepcopy(doc.get("args") or {}), rencana=copy.deepcopy(doc.get("rencana") or {}))
    try:
        out = await asyncio.wait_for(alat.jalankan(ctx, copy.deepcopy(p.args), copy.deepcopy(p.rencana)),
                                     timeout=BATAS_DETIK_TINDAKAN)
        upd = {"keadaan": "dijalankan", **_rapikan_hasil(out, p)}
    except ab.AlatError as e:
        upd = {"keadaan": "gagal", "pesan": e.pesan}
    except asyncio.TimeoutError:
        upd = {"keadaan": "gagal", "pesan": "Tindakan terlalu lama berjalan dan dihentikan. Periksa layar terkait."}
    except Exception:  # noqa: BLE001
        log.exception("Persetujuan kedua: tindakan %s gagal dijalankan", doc.get("nama"))
        upd = {"keadaan": "gagal", "pesan": "Terjadi kesalahan saat menjalankan tindakan. Periksa layar terkait."}
    finally:
        await ctx.tutup()
    selesai = _iso()
    upd.update({"selesai_pada": selesai, "diperbarui": selesai, KUNCI: None, f"{KUNCI}_at": None})
    await db.ai_actions.update_one({"id": doc["id"], KUNCI: kunci}, {"$set": upd})
    return {"ok": True, "id": doc["id"], "keadaan": upd["keadaan"],
            **({"ringkas": upd["ringkas"]} if upd.get("ringkas") else {}),
            **({"pesan": upd["pesan"]} if upd.get("pesan") else {})}


# ── Pembalikan (undo) ────────────────────────────────────────────────────────
async def balikkan(db, user: dict, tindakan_id: str, *, alasan: str, token: Optional[str], app=None,
                   klien_api=None) -> dict:
    """Balikkan tindakan `dijalankan` lewat `batalkan` alatnya (pengguna asal, atau owner/superadmin)."""
    doc = await ambil(db, tindakan_id)
    if not doc or (doc.get("user_id") != user.get("id") and not boleh_semua(user)):
        raise GalatTindakan(404, LAYAR_TIDAK_ADA)
    if doc.get("keadaan") != "dijalankan":
        raise GalatTindakan(409, "Hanya tindakan yang sudah dijalankan yang bisa dibalikkan."
                            if doc.get("keadaan") != "dibalikkan" else LAYAR_SUDAH["dibalikkan"])
    alat = ab.cari_tindakan(doc.get("nama") or "")
    if not doc.get("bisa_dibalikkan") or doc.get("pembatalan") is None or alat is None or not alat.bisa_dibalikkan:
        raise GalatTindakan(409, "Tindakan ini tidak bisa dibalikkan otomatis. Kembalikan nilainya lewat layar terkait.")
    try:
        kunci = await doc_lock.claim(db, KOLEKSI, tindakan_id, field=KUNCI, extra={"keadaan": "dijalankan"},
                                     busy=LAYAR_SIBUK, not_found=LAYAR_TIDAK_ADA, actor=user)
    except Exception as e:  # noqa: BLE001
        raise GalatTindakan(getattr(e, "status_code", 409), str(getattr(e, "detail", "") or LAYAR_SIBUK)) from None
    ctx = buat_ctx(user=user, doc=doc, token=token, app=app, klien_api=klien_api, tulis=True)
    alasan = str(alasan or "").strip()[:500]
    try:
        out = await asyncio.wait_for(alat.batalkan(ctx, copy.deepcopy(doc["pembatalan"])),
                                     timeout=BATAS_DETIK_TINDAKAN)
    except Exception as e:  # noqa: BLE001 — AlatError, batas waktu, atau galat tak terduga
        pesan = e.pesan if isinstance(e, ab.AlatError) else (
            "Pembatalan terlalu lama berjalan." if isinstance(e, asyncio.TimeoutError) else
            "Terjadi kesalahan saat membalikkan tindakan.")
        if not isinstance(e, (ab.AlatError, asyncio.TimeoutError)):
            log.exception("Pembalikan tindakan %s gagal", doc.get("nama"))
        now = _iso()
        await db.ai_actions.update_one({"id": tindakan_id, KUNCI: kunci},
                                       {"$set": {"balik_gagal": {"pesan": pesan, "pada": now},
                                                 "diperbarui": now, KUNCI: None, f"{KUNCI}_at": None}})
        raise GalatTindakan(409, f"Pembalikan gagal: {pesan}") from None
    finally:
        await ctx.tutup()
    ringkas = _teks((out or {}).get("ringkas") if isinstance(out, dict) else None, 500) or "Nilai lama dipulihkan."
    now = _iso()
    upd = {"keadaan": "dibalikkan", "dibalikkan_pada": now,
           "dibalikkan_oleh": {"id": user.get("id"), "nama": nama_pengguna(user)},
           "hasil_balik": {"ringkas": ringkas}, "bisa_dibalikkan": False, "diperbarui": now,
           KUNCI: None, f"{KUNCI}_at": None}
    if alasan:
        upd["alasan_balik"] = alasan
    await db.ai_actions.update_one({"id": tindakan_id, KUNCI: kunci}, {"$set": upd})
    return {"ok": True, "id": tindakan_id, "keadaan": "dibalikkan", "ringkas": ringkas}


# ── Daftar, detail, sesi ─────────────────────────────────────────────────────
_TGL_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def baris(doc: dict) -> dict:
    return {"id": doc.get("id"), "dibuat": doc.get("dibuat"), "pengguna": doc.get("pengguna") or {},
            "sesi_id": doc.get("sesi_id"), "nama": doc.get("nama"), "label": doc.get("label"),
            "judul": (doc.get("rencana") or {}).get("judul") or doc.get("label"), "keadaan": doc.get("keadaan"),
            "risiko": doc.get("risiko"), "ringkas": _ringkas_baris(doc), "bisa_dibalikkan": _bisa_dibalikkan(doc),
            "golongan": doc.get("golongan"), "nominal": doc.get("nominal")}


async def daftar(db, user: dict, *, status: Optional[str] = None, dari: Optional[str] = None,
                 sampai: Optional[str] = None, halaman: int = 1, semua: bool = False,
                 per_halaman: int = PER_HALAMAN) -> dict:
    # 12 Nov 2026 (K4): penyetuju kedua melihat kartu `menunggu_kedua` semua pengguna.
    lihat_semua = (bool(semua) or str(status or "").strip() == "menunggu_kedua") and boleh_semua(user)
    q: dict = {} if lihat_semua else {"user_id": user.get("id")}
    await rawat(db, dict(q))
    if status:
        st = [s.strip() for s in str(status).split(",") if s.strip()]
        if any(s not in KEADAAN for s in st):
            raise GalatTindakan(400, "Pilihan status tidak dikenal.")
        q["keadaan"] = {"$in": st}
    rentang = {}
    for nama, v, op in (("dari", dari, "$gte"), ("sampai", sampai, "$lte")):
        if v:
            if not _TGL_RX.match(str(v)):
                raise GalatTindakan(400, "Tanggal harus berformat YYYY-MM-DD.")
            rentang[op] = str(v)
    if rentang:
        q["tanggal"] = rentang
    halaman = max(1, int(halaman or 1))
    total = await db.ai_actions.count_documents(q)
    rows = await db.ai_actions.find(q, {"_id": 0}).sort("dibuat", -1).skip((halaman - 1) * per_halaman) \
        .limit(per_halaman).to_list(per_halaman)
    return {"items": [{**baris(r), "boleh_putuskan_kedua": boleh_putuskan_kedua(user, r)} for r in rows],
            "total": total, "halaman": halaman, "per_halaman": per_halaman,
            "semua": lihat_semua}


async def detail(db, user: dict, tindakan_id: str) -> dict:
    doc = await ambil(db, tindakan_id)
    if not doc or (doc.get("user_id") != user.get("id") and not boleh_semua(user)):
        raise GalatTindakan(404, LAYAR_TIDAK_ADA)
    from utils.waktu import today_wib
    masker = ab.AlatContext(user=user, cv=doc.get("cv") or "DA", today=today_wib())
    out = baris(doc)
    out.update({
        "pesan_id": doc.get("pesan_id"), "menu": doc.get("menu"), "cv": doc.get("cv"), "periode": doc.get("periode"),
        "rencana": doc.get("rencana") or {}, "args": masker.mask(doc.get("args") or {}),
        "ubahan": masker.mask(doc.get("ubahan") or {}), "alasan": doc.get("alasan"),
        "sebelum": doc.get("sebelum"), "sesudah": doc.get("sesudah"), "hasil": doc.get("hasil"),
        "pesan": doc.get("pesan"), "hasil_ringkas": doc.get("ringkas"),
        "diperbarui": doc.get("diperbarui"), "kedaluwarsa_pada": doc.get("kedaluwarsa_pada"),
        "diputuskan_pada": doc.get("diputuskan_pada"), "diputuskan_oleh": doc.get("diputuskan_oleh"),
        "dijalankan_pada": doc.get("dijalankan_pada"), "selesai_pada": doc.get("selesai_pada"),
        "dibalikkan_pada": doc.get("dibalikkan_pada"), "dibalikkan_oleh": doc.get("dibalikkan_oleh"),
        "alasan_balik": doc.get("alasan_balik"), "hasil_balik": doc.get("hasil_balik"),
        "balik_gagal": doc.get("balik_gagal"), "milik_sendiri": doc.get("user_id") == user.get("id"),
        "boleh_putuskan_kedua": boleh_putuskan_kedua(user, doc), "kedua_oleh": doc.get("kedua_oleh"),
        "kedua_pada": doc.get("kedua_pada"), "alasan_kedua": doc.get("alasan_kedua"),
    })
    return out


async def sesi_menunggu(db, user_id: str) -> set:
    """Id sesi milik pengguna yang punya kartu `menunggu` (untuk `ada_tindakan_menunggu`)."""
    await rawat(db, {"user_id": user_id})
    rows = await db.ai_actions.find({"user_id": user_id, "keadaan": "menunggu"}, {"_id": 0, "sesi_id": 1}) \
        .to_list(500)
    return {r.get("sesi_id") for r in rows if r.get("sesi_id")}


async def segarkan_pesan(db, user_id: str, sesi_id: str, pesan: list[dict]) -> bool:
    """Blok `tindakan` di riwayat layar diganti keadaan SAAT INI dari `ai_actions`. Return ada yang menunggu."""
    await rawat(db, {"sesi_id": sesi_id, "user_id": user_id})
    docs = {d["id"]: d for d in await db.ai_actions.find({"sesi_id": sesi_id, "user_id": user_id},
                                                         {"_id": 0}).to_list(500)}
    for p in pesan:
        blok = p.get("blok") or []
        for i, b in enumerate(blok):
            if isinstance(b, dict) and b.get("jenis") == "tindakan" and b.get("id") in docs:
                blok[i] = blok_kartu(docs[b["id"]])
    return any(d.get("keadaan") == "menunggu" for d in docs.values())
