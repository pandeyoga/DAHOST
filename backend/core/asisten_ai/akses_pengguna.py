"""Asisten AI per pengguna — saklar aktif/mati + batas harian per akun (keputusan owner 10 Nov 2026).

Satu tempat aturan "boleh memakai Asisten AI?" untuk SATU akun. Tidak ada sistem izin kedua: data disimpan di dokumen
pengguna yang sudah ada (`users.asisten_ai`), bawaan di `ai_config` (Monitor AI › Pengaturan), dan ruang yang boleh
dibuka tetap mengikuti portal (`routes.asisten_ai_routes.ruang_diizinkan`) serta centang "Asisten AI" di Peran.
Saklar per akun hanya bisa MENUTUP; tidak membuka portal baru.

  users.asisten_ai = {aktif: bool | None, batas_pertanyaan_harian: int | None, batas_tindakan_harian: int | None,
                      diubah_oleh, diubah_at}
      aktif None / tidak ada = ikut bawaan; batas None = ikut batas bawaan.
  ai_config (global):
      asisten_pengguna_bawaan_aktif   akun yang belum diatur (bawaan MATI — keputusan owner 10 Nov)
      asisten_batas_pertanyaan_harian batas pertanyaan per pengguna per hari (0 = tanpa batas)
      asisten_batas_tindakan_harian   sudah ada sejak Tahap B (batas tindakan per pengguna per hari)

Owner dan superadmin SELALU aktif (tidak bisa dimatikan, supaya tidak ada yang terkunci di luar). Batas harian berlaku
untuk semua akun yang punya angka batas. Satu saklar menutup ketiga ruang: chat Portal Manajemen, AI SDM, Tanya Asisten.

Pertanyaan dihitung dari `ai_chat_messages` (pesan peran `user` hari ini WIB, tanpa permintaan otomatis briefing) —
satu pertanyaan = satu kali kirim, walau jawabannya memanggil API beberapa kali.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import ai_cost_tracker as tracker
from core.asisten_ai.tindakan import BATAS_BAWAAN as BATAS_TINDAKAN_BAWAAN
from utils.waktu import today_wib, wib_day_bounds_utc

KOLOM = "asisten_ai"
PERAN_SELALU_AKTIF = frozenset({"owner", "superadmin"})
MAKS_BATAS = 1000
BAWAAN_AKTIF = False            # keputusan owner 10 Nov 2026: staf mati sampai dinyalakan per orang
BATAS_PERTANYAAN_BAWAAN = 0     # 0 = tanpa batas

KODE_NONAKTIF = "pengguna_nonaktif"
KODE_BATAS_PERTANYAAN = "batas_pertanyaan"
PESAN_NONAKTIF = ("Asisten AI belum diaktifkan untuk akun Anda. Minta owner menyalakannya di Monitor AI › "
                  "Pengaturan › Asisten AI per pengguna.")
PESAN_BATAS_PERTANYAAN = ("Batas pertanyaan Asisten AI untuk akun Anda hari ini sudah tercapai ({batas} pertanyaan). "
                          "Coba lagi besok atau minta owner menaikkan batas.")
PESAN_SETUJUI_NONAKTIF = ("Asisten AI tidak aktif untuk akun Anda, jadi kartu ini tidak bisa disetujui. Kartu masih "
                          "bisa dibatalkan.")


def bilangan_batas(v) -> Optional[int]:
    """Nilai batas tersimpan → int 0..MAKS_BATAS, atau None bila kosong/tidak sah."""
    if v is None or isinstance(v, bool):
        return None
    try:
        iv = int(v)
    except (TypeError, ValueError):
        return None
    if isinstance(v, float) and not v.is_integer():
        return None
    return iv if 0 <= iv <= MAKS_BATAS else None


def bawaan_dari(settings: dict) -> dict:
    """Bawaan efektif dari `ai_config` (setelan Monitor AI → nilai bawaan program)."""
    s = settings or {}
    bp = bilangan_batas(s.get("asisten_batas_pertanyaan_harian"))
    bt = bilangan_batas(s.get("asisten_batas_tindakan_harian"))
    return {"aktif": s.get("asisten_pengguna_bawaan_aktif", BAWAAN_AKTIF) is True,
            "batas_pertanyaan": BATAS_PERTANYAAN_BAWAAN if bp is None else bp,
            "batas_tindakan": BATAS_TINDAKAN_BAWAAN if bt is None else bt}


def aturan_dari(udoc: Optional[dict], role: Optional[str], settings: dict) -> dict:
    """Aturan efektif satu akun (fungsi murni). `sumber` = peran | akun | bawaan."""
    cfg = (udoc or {}).get(KOLOM)
    cfg = cfg if isinstance(cfg, dict) else {}
    bawaan = bawaan_dari(settings)
    peran = str(role or (udoc or {}).get("role") or "").strip().lower()
    if peran in PERAN_SELALU_AKTIF:
        aktif, sumber = True, "peran"
    elif isinstance(cfg.get("aktif"), bool):
        aktif, sumber = cfg["aktif"], "akun"
    else:
        aktif, sumber = bawaan["aktif"], "bawaan"
    bp, bt = bilangan_batas(cfg.get("batas_pertanyaan_harian")), bilangan_batas(cfg.get("batas_tindakan_harian"))
    return {"aktif": aktif, "sumber": sumber, "selalu_aktif": peran in PERAN_SELALU_AKTIF,
            "batas_pertanyaan": bawaan["batas_pertanyaan"] if bp is None else bp,
            "batas_pertanyaan_sumber": "bawaan" if bp is None else "akun",
            "batas_tindakan": bawaan["batas_tindakan"] if bt is None else bt,
            "batas_tindakan_sumber": "bawaan" if bt is None else "akun"}


async def aturan(db, user: dict) -> dict:
    """Aturan efektif akun yang login (dibaca LANGSUNG dari DB — perubahan owner berlaku di pesan berikutnya)."""
    uid = (user or {}).get("id")
    udoc = await db.users.find_one({"id": uid}, {"_id": 0, "role": 1, KOLOM: 1}) if uid else None
    return aturan_dari(udoc, (user or {}).get("role"), await tracker.get_ai_settings())


def awal_hari_iso(tanggal: Optional[date] = None) -> str:
    """Awal hari WIB dalam UTC, format sama dengan `ai_chat_messages.dibuat` (isoformat UTC)."""
    mulai, _ = wib_day_bounds_utc(tanggal or today_wib())
    return mulai.astimezone(timezone.utc).isoformat()


def _kueri_pertanyaan(tanggal: Optional[date] = None) -> dict:
    return {"peran": "user", "otomatis": {"$ne": True}, "dibuat": {"$gte": awal_hari_iso(tanggal)}}


async def jumlah_pertanyaan_hari_ini(db, user_id: str, tanggal: Optional[date] = None) -> int:
    if not user_id:
        return 0
    return await db.ai_chat_messages.count_documents({"user_id": user_id, **_kueri_pertanyaan(tanggal)})


async def pertanyaan_per_pengguna(db, tanggal: Optional[date] = None) -> dict:
    """{user_id: jumlah pertanyaan hari ini} untuk tabel Monitor AI."""
    out: dict = {}
    async for r in db.ai_chat_messages.find(_kueri_pertanyaan(tanggal), {"_id": 0, "user_id": 1}):
        uid = r.get("user_id")
        if uid:
            out[uid] = out.get(uid, 0) + 1
    return out


async def periksa(db, user: dict, *, kirim: bool = False) -> tuple[dict, Optional[dict]]:
    """(aturan, galat {kode, pesan} | None). `kirim=True` juga memeriksa batas pertanyaan hari ini."""
    a = await aturan(db, user)
    if not a["aktif"]:
        return a, {"kode": KODE_NONAKTIF, "pesan": PESAN_NONAKTIF}
    if kirim and a["batas_pertanyaan"] > 0:
        if await jumlah_pertanyaan_hari_ini(db, user.get("id")) >= a["batas_pertanyaan"]:
            return a, {"kode": KODE_BATAS_PERTANYAAN, "pesan": PESAN_BATAS_PERTANYAAN.format(batas=a["batas_pertanyaan"])}
    return a, None


def rapikan_masukan(body: dict, *, peran_target: str) -> dict:
    """Isian layar → nilai tersimpan. ValueError (pesan layar) bila tidak sah."""
    out: dict = {}
    if "aktif" in body:
        v = body.get("aktif")
        if v is not None and not isinstance(v, bool):
            raise ValueError("Status Asisten AI harus Ikut bawaan, Aktif, atau Mati.")
        if v is False and str(peran_target or "").lower() in PERAN_SELALU_AKTIF:
            raise ValueError("Owner dan superadmin selalu aktif; Asisten AI tidak bisa dimatikan untuk akun ini.")
        out["aktif"] = v
    for k, label in (("batas_pertanyaan_harian", "Batas pertanyaan per hari"),
                     ("batas_tindakan_harian", "Batas tindakan per hari")):
        if k not in body:
            continue
        v = body.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            out[k] = None
            continue
        iv = bilangan_batas(v.strip() if isinstance(v, str) else v)
        if iv is None:
            raise ValueError(f"{label} harus bilangan bulat 0–{MAKS_BATAS} (kosongkan untuk ikut bawaan).")
        out[k] = iv
    if not out:
        raise ValueError("Tidak ada isian yang diubah.")
    return out


async def simpan(db, uid: str, isian: dict, *, oleh: str) -> dict:
    """Gabungkan isian ke `users.asisten_ai` (kunci yang tidak dikirim tetap). Return nilai tersimpan."""
    lama = await db.users.find_one({"id": uid}, {"_id": 0, KOLOM: 1})
    cfg = (lama or {}).get(KOLOM)
    cfg = dict(cfg) if isinstance(cfg, dict) else {}
    cfg.update(isian)
    cfg.update({"diubah_oleh": oleh, "diubah_at": datetime.now(timezone.utc).isoformat()})
    await db.users.update_one({"id": uid}, {"$set": {KOLOM: cfg}})
    return cfg
