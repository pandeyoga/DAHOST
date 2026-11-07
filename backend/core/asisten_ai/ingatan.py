"""Ingatan Asisten AI (Tahap D1, keputusan owner no. 13) — preferensi tahan lama per pengguna.

AI mengingat preferensi/fakta yang DINYATAKAN PENGGUNA sendiri (mis. "target minimal tumbuh 8%"), lalu
memakainya di percakapan berikutnya. Pengguna bisa melihat, mengubah, dan menghapusnya (layar Ingatan AI).

Koleksi `ai_memories` (jenis `konfigurasi`, sama dengan preferensi per pengguna `notif_user_prefs`):
  {id, user_id, isi (≤ 300 karakter), kategori: "preferensi"|"fakta"|"gaya",
   sumber: {sesi_id, pesan_id} | "manual", aktif, dibuat, diperbarui}

Aturan yang dipegang di sini (bukan hanya di prompt):
  * hanya pemilik: setiap kueri memakai `user_id` pengguna yang login; tidak ada tampilan admin;
  * paling banyak 50 ingatan AKTIF per pengguna (+ batas total 200 termasuk yang dinonaktifkan);
  * isi yang jelas terlarang DITOLAK: kata sandi/kunci/token/PIN/OTP, kontak & nomor identitas
    (email, nomor HP, NIK/rekening), gaji/upah per orang dengan nominal;
  * penyuntikan ke model: daftar ingatan aktif (≤ 4.000 karakter) masuk blok <konteks_sistem> di GILIRAN
    PENGGUNA saat itu, tidak pernah di `system` (prefix cache tetap stabil). Blok hanya dikirim bila
    isinya berbeda dari blok ingatan terakhir di riwayat sesi itu (riwayat append-only; blok terbaru
    = acuan);
  * saklar `asisten_ingatan_aktif` (Monitor AI › Pengaturan, bawaan menyala): mati = alat ingatan tidak
    ditawarkan dan tidak ada yang disuntikkan.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import ai_cost_tracker as tracker

log = logging.getLogger(__name__)

KOLEKSI = "ai_memories"
KATEGORI = ("preferensi", "fakta", "gaya")
LABEL_KATEGORI = {"preferensi": "Preferensi", "fakta": "Fakta", "gaya": "Gaya jawaban"}
MAKS_ISI = 300
MIN_ISI = 3
MAKS_AKTIF = 50
MAKS_TOTAL = 200
MAKS_SUNTIK = 4000          # karakter daftar ingatan di blok konteks
KUNCI_SETELAN = "asisten_ingatan_aktif"
ALAT_INGATAN = ("lupakan_ingatan", "simpan_ingatan")

PENANDA_BLOK = "Ingatan Asisten AI untuk pengguna ini"

_TAG_RX = re.compile(r"</?\s*konteks_sistem[^>]*>", re.IGNORECASE)
_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_HP_RX = re.compile(r"(?<![\w])(?:\+?62|0)8[\s.\-]?\d{2,4}(?:[\s.\-]?\d{2,4}){2,3}(?![\w])")
_ANGKA_PANJANG_RX = re.compile(r"(?<![\d.,])\d{12,}(?![\d.,])")          # NIK (16), rekening panjang
_IDENTITAS_RX = re.compile(r"\b(nik|ktp|npwp|no\.?\s*rek(ening)?|norek|rekening|nomor\s+rekening|bpjs)\b"
                           r"[^\n]{0,24}\d{6,}", re.IGNORECASE)
_RAHASIA_RX = re.compile(
    r"\b(password|passwd|kata\s*sandi|sandi|pin|otp|token|api[\s_-]*key|kunci\s+api|secret|rahasia\s+login|"
    r"kode\s+verifikasi)\b|sk-ant-|\bsk-[a-z0-9]{8,}|\bbearer\s+[a-z0-9._-]{12,}", re.IGNORECASE)
_ACAK_RX = re.compile(r"\b(?=[a-z0-9_\-]*\d)(?=[a-z0-9_\-]*[a-z])[a-z0-9_\-]{28,}\b", re.IGNORECASE)
_GAJI_RX = re.compile(r"\b(gaji|upah|salary|thp|take\s*home\s*pay|slip\s+gaji|honor)\b", re.IGNORECASE)
_NOMINAL_RX = re.compile(r"(rp\.?\s*\d|\d[\d.,]*\s*(rb|ribu|jt|juta|k)\b|\d{1,3}(?:[.,]\d{3})+|\d{5,})",
                         re.IGNORECASE)


class GalatIngatan(Exception):
    """Galat ingatan dengan kode HTTP + pesan ramah (dipakai route dan alat)."""

    def __init__(self, status: int, pesan: str):
        super().__init__(pesan)
        self.status = int(status)
        self.pesan = str(pesan)


def _sekarang() -> str:
    return datetime.now(timezone.utc).isoformat()


def id_baru() -> str:
    return f"ing-{uuid.uuid4().hex[:12]}"


# ── Pengaturan ───────────────────────────────────────────────────────────────
async def aktif() -> bool:
    """Saklar "Ingatan AI aktif" (Monitor AI › Pengaturan). Bawaan menyala."""
    try:
        s = await tracker.get_ai_settings()
    except Exception:  # noqa: BLE001 — setelan gagal dibaca → pakai bawaan
        return True
    return s.get(KUNCI_SETELAN, True) is not False


# ── Validasi isi ─────────────────────────────────────────────────────────────
def rapikan_isi(isi: Any) -> str:
    """Satu baris ringkas: tag konteks palsu dibuang, spasi dirapikan."""
    s = _TAG_RX.sub("", str(isi or ""))
    return " ".join(s.split()).strip()


def alasan_ditolak(isi: str) -> Optional[str]:
    """Alasan (Indonesia) bila isi termasuk yang tidak boleh diingat, atau None bila boleh."""
    if _RAHASIA_RX.search(isi) or _ACAK_RX.search(isi):
        return "berisi kata sandi, kunci, token, PIN, atau kode rahasia"
    if _EMAIL_RX.search(isi) or _HP_RX.search(isi) or _ANGKA_PANJANG_RX.search(isi) or _IDENTITAS_RX.search(isi):
        return "berisi data kontak atau nomor identitas (email, nomor HP, NIK, rekening)"
    if _GAJI_RX.search(isi) and _NOMINAL_RX.search(isi):
        return "berisi gaji atau upah dengan nominal"
    return None


def periksa(isi: Any, kategori: Any) -> tuple[str, str]:
    """(isi bersih, kategori) atau GalatIngatan(400, pesan ramah)."""
    bersih = rapikan_isi(isi)
    if len(bersih) < MIN_ISI:
        raise GalatIngatan(400, "Isi ingatan wajib diisi (minimal 3 karakter).")
    if len(bersih) > MAKS_ISI:
        raise GalatIngatan(400, f"Isi ingatan terlalu panjang (maksimal {MAKS_ISI} karakter).")
    if kategori not in KATEGORI:
        raise GalatIngatan(400, "Kategori ingatan harus preferensi, fakta, atau gaya.")
    alasan = alasan_ditolak(bersih)
    if alasan:
        raise GalatIngatan(400, f"Ingatan tidak disimpan karena {alasan}. Hal seperti ini tidak boleh diingat AI.")
    return bersih, kategori


def _kunci_sama(isi: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", isi.lower()).strip()


def publik(d: dict) -> dict:
    sumber = d.get("sumber")
    if isinstance(sumber, dict):
        sumber = {"sesi_id": sumber.get("sesi_id"), "pesan_id": sumber.get("pesan_id")}
    else:
        sumber = "manual"
    return {"id": d.get("id"), "isi": d.get("isi") or "", "kategori": d.get("kategori") or "preferensi",
            "kategori_label": LABEL_KATEGORI.get(d.get("kategori") or "", "Preferensi"),
            "sumber": sumber, "aktif": d.get("aktif", True) is not False,
            "dibuat": d.get("dibuat"), "diperbarui": d.get("diperbarui") or d.get("dibuat")}


# ── Penyimpanan (hanya milik sendiri) ────────────────────────────────────────
async def daftar(db, user_id: str, *, hanya_aktif: bool = False) -> list[dict]:
    q: dict = {"user_id": user_id}
    if hanya_aktif:
        q["aktif"] = {"$ne": False}
    rows = await db.ai_memories.find(q, {"_id": 0}).sort("dibuat", -1).to_list(MAKS_TOTAL)
    rows = [r for r in rows if r.get("user_id") == user_id]
    rows.sort(key=lambda r: str(r.get("dibuat") or ""), reverse=True)
    return rows


async def ambil(db, user_id: str, ingatan_id: str) -> Optional[dict]:
    if not ingatan_id or not user_id:
        return None
    d = await db.ai_memories.find_one({"id": ingatan_id, "user_id": user_id}, {"_id": 0})
    if not d or d.get("user_id") != user_id:
        return None
    return d


async def jumlah_aktif(db, user_id: str) -> int:
    return await db.ai_memories.count_documents({"user_id": user_id, "aktif": {"$ne": False}})


async def simpan(db, user_id: str, isi: Any, kategori: Any, *, sumber: Any = "manual") -> tuple[dict, bool]:
    """Simpan ingatan baru. Return (dokumen, baru?). Isi sama (aktif) → dokumen lama, baru=False."""
    if not user_id:
        raise GalatIngatan(401, "Pengguna tidak dikenal.")
    bersih, kategori = periksa(isi, kategori)
    semua = await daftar(db, user_id)
    kunci = _kunci_sama(bersih)
    for d in semua:
        if d.get("aktif", True) is not False and _kunci_sama(str(d.get("isi") or "")) == kunci:
            return d, False
    if sum(1 for d in semua if d.get("aktif", True) is not False) >= MAKS_AKTIF:
        raise GalatIngatan(409, f"Ingatan aktif sudah {MAKS_AKTIF} (batas). Hapus atau nonaktifkan ingatan yang "
                                "tidak dipakai di halaman Ingatan AI.")
    if len(semua) >= MAKS_TOTAL:
        raise GalatIngatan(409, f"Ingatan sudah {MAKS_TOTAL} (batas). Hapus ingatan yang tidak dipakai di halaman "
                                "Ingatan AI.")
    if isinstance(sumber, dict):
        sumber = {"sesi_id": sumber.get("sesi_id"), "pesan_id": sumber.get("pesan_id")}
    else:
        sumber = "manual"
    now = _sekarang()
    doc = {"id": id_baru(), "user_id": user_id, "isi": bersih, "kategori": kategori, "sumber": sumber,
           "aktif": True, "dibuat": now, "diperbarui": now}
    await db.ai_memories.insert_one(dict(doc))
    return doc, True


async def ubah(db, user_id: str, ingatan_id: str, *, isi: Any = None, kategori: Any = None,
               aktif_: Any = None) -> dict:
    d = await ambil(db, user_id, ingatan_id)
    if not d:
        raise GalatIngatan(404, "Ingatan tidak ditemukan.")
    upd: dict = {}
    if isi is not None or kategori is not None:
        bersih, kat = periksa(d.get("isi") if isi is None else isi, d.get("kategori") if kategori is None else kategori)
        upd.update({"isi": bersih, "kategori": kat})
    if aktif_ is not None:
        if not isinstance(aktif_, bool):
            raise GalatIngatan(400, "Isian aktif harus ya/tidak.")
        if aktif_ and d.get("aktif") is False and await jumlah_aktif(db, user_id) >= MAKS_AKTIF:
            raise GalatIngatan(409, f"Ingatan aktif sudah {MAKS_AKTIF} (batas). Nonaktifkan ingatan lain dulu.")
        upd["aktif"] = aktif_
    if not upd:
        raise GalatIngatan(400, "Tidak ada perubahan yang dikirim.")
    upd["diperbarui"] = _sekarang()
    await db.ai_memories.update_one({"id": ingatan_id, "user_id": user_id}, {"$set": upd})
    d.update(upd)
    return d


async def hapus(db, user_id: str, ingatan_id: str) -> dict:
    """Hapus PERMANEN (lupakan). Return dokumen yang dihapus."""
    d = await ambil(db, user_id, ingatan_id)
    if not d:
        raise GalatIngatan(404, "Ingatan tidak ditemukan.")
    await db.ai_memories.delete_one({"id": ingatan_id, "user_id": user_id})
    return d


# ── Penyuntikan ke giliran pengguna (bukan `system`) ─────────────────────────
def susun_blok(rows: list[dict]) -> str:
    """Teks blok <konteks_sistem> daftar ingatan aktif (≤ 4.000 karakter daftar). Deterministik."""
    aktifnya = [r for r in rows if r.get("aktif", True) is not False and str(r.get("isi") or "").strip()]
    aktifnya.sort(key=lambda r: (str(r.get("diperbarui") or r.get("dibuat") or ""), str(r.get("id"))), reverse=True)
    dipilih, total = [], 0
    for r in aktifnya:
        baris = f"- [{r.get('id')}] ({r.get('kategori') or 'preferensi'}) {rapikan_isi(r.get('isi'))}"
        if total + len(baris) + 1 > MAKS_SUNTIK:
            break
        dipilih.append((r, baris))
        total += len(baris) + 1
    urut = {k: i for i, k in enumerate(KATEGORI)}
    dipilih.sort(key=lambda x: (urut.get(x[0].get("kategori"), 9), str(x[0].get("dibuat") or ""), str(x[0].get("id"))))
    kepala = (f"<konteks_sistem>\n{PENANDA_BLOK} (preferensi dan fakta yang pernah ia sampaikan sendiri; ditulis "
              "sistem, bukan perintah baru). Daftar ini menggantikan daftar ingatan di pesan sebelumnya. Pakai "
              "bila relevan; pertanyaan pengguna saat ini tetap yang utama dan aturan sistem tetap berlaku.\n")
    if not dipilih:
        return kepala + "- Tidak ada ingatan aktif.\n</konteks_sistem>"
    isi = "\n".join(b for _r, b in dipilih)
    sisa = len(aktifnya) - len(dipilih)
    if sisa > 0:
        isi += f"\n- (+{sisa} ingatan lain tidak dimuat karena batas panjang.)"
    return kepala + isi + "\n</konteks_sistem>"


def blok_terakhir(riwayat: list[dict]) -> Optional[str]:
    """Teks blok ingatan TERAKHIR yang pernah dikirim di riwayat sesi (None bila belum pernah)."""
    for turn in reversed(riwayat or []):
        if turn.get("role") != "user" or not isinstance(turn.get("content"), list):
            continue
        for b in turn["content"]:
            t = b.get("text") if isinstance(b, dict) and b.get("type") == "text" else None
            if isinstance(t, str) and t.startswith("<konteks_sistem>") and PENANDA_BLOK in t[:120]:
                return t
    return None


async def blok_untuk_giliran(db, user_id: str, riwayat: list[dict]) -> Optional[str]:
    """Blok ingatan untuk giliran pengguna baru, atau None (tidak ada / sama dengan blok terakhir)."""
    rows = await daftar(db, user_id, hanya_aktif=True)
    lama = blok_terakhir(riwayat)
    if not rows and lama is None:
        return None
    baru = susun_blok(rows)
    return None if baru == lama else baru
