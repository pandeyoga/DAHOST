"""Penyimpanan percakapan Asisten AI.

Koleksi (jenis `log` di core/collection_registry.py — boleh dihapus saat cutoff):

  ai_chat_sessions  {id, user_id, judul, created_at, updated_at, jumlah_pesan, dihapus, dihapus_at,
                     ada_tindakan_menunggu}
  ai_chat_messages  {id, sesi_id, user_id, urutan, peran: "user"|"asisten", dibuat, diperbarui,
                     status: "selesai"|"berjalan"|"terhenti"|"gagal", blok: [...], api: [...],
                     cv, periode, pemakaian, galat}

* `blok` = tampilan yang dirender ulang layar (Kontrak B). `api` = isi MENTAH Messages API
  (giliran {role, content} persis seperti dikirim/diterima, termasuk blok thinking bertanda
  tangan) — dipisah dari `blok` dan TIDAK PERNAH dikirim ke layar.
* Riwayat untuk API = gabungan `api` semua pesan sesi menurut `urutan`. Append-only: pesan lama
  tidak pernah diubah isinya; pesan asisten hanya ditulis sekali saat jawabannya berakhir.
* Hanya pemilik: setiap kueri memakai `user_id` pengguna yang login. Superadmin pun tidak bisa
  membuka percakapan orang lain (sesi orang lain = "tidak ditemukan").
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

SESI = "ai_chat_sessions"
PESAN = "ai_chat_messages"
JUDUL_BAWAAN = "Percakapan baru"
MAKS_JUDUL = 120
MAKS_SESI_DAFTAR = 200
MAKS_PESAN_SESI = 2000
# Pesan "berjalan" yang lebih tua dari ini dianggap terhenti (proses mati di tengah jawaban).
BATAS_BERJALAN = timedelta(minutes=15)


def _sekarang() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return str(uuid.uuid4())


def judul_dari_teks(teks: str) -> str:
    t = " ".join(str(teks or "").split())
    return (t[:57] + "…") if len(t) > 60 else (t or JUDUL_BAWAAN)


def _sesi_publik(d: dict) -> dict:
    return {"id": d.get("id"), "judul": d.get("judul") or JUDUL_BAWAAN, "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at") or d.get("created_at"),
            "jumlah_pesan": int(d.get("jumlah_pesan") or 0),
            "ada_tindakan_menunggu": bool(d.get("ada_tindakan_menunggu", False))}


async def buat_sesi(db, user_id: str, judul: Optional[str] = None) -> dict:
    now = _sekarang()
    judul = (str(judul).strip()[:MAKS_JUDUL] if judul and str(judul).strip() else JUDUL_BAWAAN)
    doc = {"id": _id(), "user_id": user_id, "judul": judul, "judul_otomatis": judul == JUDUL_BAWAAN,
           "created_at": now, "updated_at": now, "jumlah_pesan": 0, "dihapus": False,
           "ada_tindakan_menunggu": False}
    await db.ai_chat_sessions.insert_one(dict(doc))
    return _sesi_publik(doc)


async def daftar_sesi(db, user_id: str) -> list[dict]:
    rows = await db.ai_chat_sessions.find(
        {"user_id": user_id, "dihapus": {"$ne": True}}, {"_id": 0},
    ).sort("updated_at", -1).limit(MAKS_SESI_DAFTAR).to_list(MAKS_SESI_DAFTAR)
    rows.sort(key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)
    return [_sesi_publik(r) for r in rows]


async def ambil_sesi(db, user_id: str, sesi_id: str) -> Optional[dict]:
    if not sesi_id or not user_id:
        return None
    d = await db.ai_chat_sessions.find_one({"id": sesi_id, "user_id": user_id, "dihapus": {"$ne": True}},
                                           {"_id": 0})
    if not d or d.get("user_id") != user_id or d.get("dihapus"):
        return None
    return d


async def ubah_judul(db, user_id: str, sesi_id: str, judul: str) -> Optional[dict]:
    judul = str(judul or "").strip()[:MAKS_JUDUL]
    if not judul:
        raise ValueError("Judul percakapan wajib diisi.")
    sesi = await ambil_sesi(db, user_id, sesi_id)
    if not sesi:
        return None
    now = _sekarang()
    await db.ai_chat_sessions.update_one({"id": sesi_id, "user_id": user_id},
                                         {"$set": {"judul": judul, "judul_otomatis": False, "updated_at": now}})
    sesi.update({"judul": judul, "updated_at": now})
    return _sesi_publik(sesi)


async def hapus_sesi(db, user_id: str, sesi_id: str) -> bool:
    """Hapus LUNAK: sesi disembunyikan (log tetap ada sampai cutoff)."""
    sesi = await ambil_sesi(db, user_id, sesi_id)
    if not sesi:
        return False
    await db.ai_chat_sessions.update_one({"id": sesi_id, "user_id": user_id},
                                         {"$set": {"dihapus": True, "dihapus_at": _sekarang()}})
    return True


async def _pesan_sesi(db, user_id: str, sesi_id: str) -> list[dict]:
    rows = await db.ai_chat_messages.find({"sesi_id": sesi_id, "user_id": user_id}, {"_id": 0}) \
        .sort("urutan", 1).to_list(MAKS_PESAN_SESI)
    rows = [r for r in rows if r.get("user_id") == user_id]
    rows.sort(key=lambda r: int(r.get("urutan") or 0))
    return rows


def _status_tampil(r: dict) -> str:
    st = r.get("status") or "selesai"
    if st == "berjalan":
        try:
            t = datetime.fromisoformat(str(r.get("diperbarui") or r.get("dibuat")))
            if datetime.now(timezone.utc) - t > BATAS_BERJALAN:
                return "terhenti"
        except ValueError:
            return "terhenti"
    return st


async def ambil_pesan(db, user_id: str, sesi_id: str) -> list[dict]:
    """Pesan untuk layar (tanpa isi mentah API)."""
    out = []
    for r in await _pesan_sesi(db, user_id, sesi_id):
        item = {"id": r.get("id"), "peran": r.get("peran"), "dibuat": r.get("dibuat"),
                "blok": r.get("blok") or [], "status": _status_tampil(r)}
        if r.get("peran") == "asisten" and r.get("pemakaian"):
            item["pemakaian"] = r["pemakaian"]
        if r.get("cv"):
            item["cv"] = r["cv"]
        if r.get("periode"):
            item["periode"] = r["periode"]
        out.append(item)
    return out


async def muat_riwayat_api(db, user_id: str, sesi_id: str) -> list[dict]:
    """Riwayat mentah untuk Messages API, PERSIS seperti tersimpan (append-only)."""
    out: list[dict] = []
    for r in await _pesan_sesi(db, user_id, sesi_id):
        for turn in r.get("api") or []:
            if isinstance(turn, dict) and turn.get("role") in ("user", "assistant") and turn.get("content"):
                out.append(turn)
    return out


async def _urutan_berikut(db, sesi: dict, n: int) -> int:
    """Pesan bernomor berurutan per sesi (satu jawaban per sesi berjalan pada satu waktu)."""
    awal = int(sesi.get("jumlah_pesan") or 0)
    sesi["jumlah_pesan"] = awal + n
    return awal + 1


async def mulai_giliran(db, sesi: dict, user_id: str, *, teks: str, api_user: dict, cv: str,
                        periode: str) -> tuple[dict, dict]:
    """Simpan pesan pengguna + pesan asisten berstatus `berjalan`. Return (pesan_user, pesan_asisten)."""
    now = _sekarang()
    nomor = await _urutan_berikut(db, sesi, 2)
    p_user = {"id": _id(), "sesi_id": sesi["id"], "user_id": user_id, "urutan": nomor, "peran": "user",
              "dibuat": now, "diperbarui": now, "status": "selesai", "blok": [{"jenis": "teks", "isi": teks}],
              "api": [api_user], "cv": cv, "periode": periode}
    p_asisten = {"id": _id(), "sesi_id": sesi["id"], "user_id": user_id, "urutan": nomor + 1,
                 "peran": "asisten", "dibuat": now, "diperbarui": now, "status": "berjalan", "blok": [],
                 "api": [], "cv": cv, "periode": periode}
    await db.ai_chat_messages.insert_one(dict(p_user))
    await db.ai_chat_messages.insert_one(dict(p_asisten))
    upd = {"updated_at": now}
    if sesi.get("judul_otomatis", True) and (sesi.get("judul") or JUDUL_BAWAAN) == JUDUL_BAWAAN:
        upd["judul"] = judul_dari_teks(teks)
    await db.ai_chat_sessions.update_one({"id": sesi["id"], "user_id": user_id},
                                         {"$set": upd, "$inc": {"jumlah_pesan": 2}})
    return p_user, p_asisten


async def akhiri_giliran(db, user_id: str, pesan_id: str, *, blok: list, api: list, status: str,
                         pemakaian: Optional[dict] = None, galat: Optional[dict] = None) -> None:
    """Tulis hasil akhir pesan asisten SEKALI (status selesai/terhenti/gagal)."""
    now = _sekarang()
    upd = {"blok": blok, "api": api, "status": status, "diperbarui": now}
    if pemakaian is not None:
        upd["pemakaian"] = pemakaian
    if galat is not None:
        upd["galat"] = galat
    await db.ai_chat_messages.update_one({"id": pesan_id, "user_id": user_id, "status": "berjalan"},
                                         {"$set": upd})
