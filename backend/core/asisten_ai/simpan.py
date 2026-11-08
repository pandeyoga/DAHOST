"""Penyimpanan percakapan Asisten AI.

Koleksi (jenis `log` di core/collection_registry.py — boleh dihapus saat cutoff):

  ai_chat_sessions  {id, user_id, judul, created_at, updated_at, jumlah_pesan, dihapus, dihapus_at,
                     ada_tindakan_menunggu}
  ai_chat_messages  {id, sesi_id, user_id, urutan, peran: "user"|"asisten", dibuat, diperbarui,
                     status: "selesai"|"berjalan"|"terhenti"|"gagal"|"menunggu_konfirmasi", blok: [...], api: [...],
                     cv, periode, pemakaian, galat, tunda?, lanjutan_dari?}

Tahap B (8 Nov 2026): pesan asisten yang berhenti menunggu kartu tindakan berstatus `menunggu_konfirmasi`
dan menyimpan `tunda` = {keadaan: "menunggu"|"selesai", urutan: [id tool_use giliran terakhir], hasil:
[tool_result alat baca/ui/tindakan-gagal giliran itu], tindakan: [id ai_actions], putaran_alat}. `api`-nya
berakhir dengan giliran asisten ber-tool_use; tool_result-nya ditulis di pesan BERIKUTNYA (jawaban lanjutan
`lanjutan_dari` = id pesan ini, `api` diawali giliran pengguna berisi tool_result; atau pesan pengguna baru
yang diawali tool_result kartu kedaluwarsa). Yang berubah pada pesan lama hanya `status` + `tunda.keadaan`.

* `blok` = tampilan yang dirender ulang layar (Kontrak B). `api` = isi MENTAH Messages API
  (giliran {role, content} persis seperti dikirim/diterima, termasuk blok thinking bertanda
  tangan) — dipisah dari `blok` dan TIDAK PERNAH dikirim ke layar.
* Riwayat untuk API = gabungan `api` semua pesan sesi menurut `urutan`. Append-only: pesan lama
  tidak pernah diubah isinya; pesan asisten hanya ditulis sekali saat jawabannya berakhir.
* Hanya pemilik: setiap kueri memakai `user_id` pengguna yang login. Superadmin pun tidak bisa
  membuka percakapan orang lain (sesi orang lain = "tidak ditemukan").

Tahap D (8 Nov 2026, agen proaktif): sesi punya `jenis` = "chat" (bawaan) | "briefing" | "laporan_mingguan"
(dibuat otomatis oleh `core/asisten_ai/proaktif.py`); pesan pengguna buatan sistem (permintaan briefing
otomatis) bertanda `otomatis: true`.

Tahap E (9 Nov 2026):
  * sesi menyimpan ruang hitung (kontainer code execution) yang dipakai percakapan: `container_id`,
    `container_kedaluwarsa` (nilai `expires_at` terakhir dari API — nilai bergulir), `container_dibuat` (pertama kali
    id itu terlihat; kontainer hidup ≤ 30 hari sejak dibuat). Dikirim balik selama umurnya < `UMUR_KONTAINER`;
  * pesan pengguna membawa `lampiran: [{id, nama, jenis, ukuran_kb}]` (Kontrak K2) bila ada berkas terlampir.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

SESI = "ai_chat_sessions"
PESAN = "ai_chat_messages"
JUDUL_BAWAAN = "Percakapan baru"
MAKS_JUDUL = 120
JENIS_SESI = ("chat", "briefing", "laporan_mingguan")
MAKS_SESI_DAFTAR = 200
MAKS_PESAN_SESI = 2000
# Pesan "berjalan" yang lebih tua dari ini dianggap terhenti (proses mati di tengah jawaban).
BATAS_BERJALAN = timedelta(minutes=15)
# Tahap E: kontainer code execution kedaluwarsa 30 hari sesudah dibuat (dok resmi); sisakan satu hari pengaman.
UMUR_KONTAINER = timedelta(days=29)


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
            "ada_tindakan_menunggu": bool(d.get("ada_tindakan_menunggu", False)),
            "jenis": d.get("jenis") if d.get("jenis") in JENIS_SESI else "chat"}


async def buat_sesi(db, user_id: str, judul: Optional[str] = None, *, jenis: str = "chat") -> dict:
    now = _sekarang()
    judul = (str(judul).strip()[:MAKS_JUDUL] if judul and str(judul).strip() else JUDUL_BAWAAN)
    doc = {"id": _id(), "user_id": user_id, "judul": judul, "judul_otomatis": judul == JUDUL_BAWAAN,
           "created_at": now, "updated_at": now, "jumlah_pesan": 0, "dihapus": False,
           "ada_tindakan_menunggu": False, "jenis": jenis if jenis in JENIS_SESI else "chat"}
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
        if r.get("otomatis"):
            item["otomatis"] = True
        if r.get("peran") == "user" and r.get("lampiran"):
            item["lampiran"] = [dict(x) for x in r["lampiran"] if isinstance(x, dict)]
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
                        periode: str, otomatis: bool = False,
                        lampiran: Optional[list] = None) -> tuple[dict, dict]:
    """Simpan pesan pengguna + pesan asisten berstatus `berjalan`. Return (pesan_user, pesan_asisten).
    `otomatis=True` (Tahap D): pesan pengguna ditulis sistem (permintaan briefing/laporan otomatis).
    `lampiran` (Tahap E): [{id, nama, jenis, ukuran_kb}] berkas yang dilampirkan pada pesan ini."""
    now = _sekarang()
    nomor = await _urutan_berikut(db, sesi, 2)
    p_user = {"id": _id(), "sesi_id": sesi["id"], "user_id": user_id, "urutan": nomor, "peran": "user",
              "dibuat": now, "diperbarui": now, "status": "selesai", "blok": [{"jenis": "teks", "isi": teks}],
              "api": [api_user], "cv": cv, "periode": periode}
    if otomatis:
        p_user["otomatis"] = True
    if lampiran:
        p_user["lampiran"] = [dict(x) for x in lampiran]
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
                         pemakaian: Optional[dict] = None, galat: Optional[dict] = None,
                         tunda: Optional[dict] = None) -> None:
    """Tulis hasil akhir pesan asisten SEKALI (status selesai/terhenti/gagal/menunggu_konfirmasi)."""
    now = _sekarang()
    upd = {"blok": blok, "api": api, "status": status, "diperbarui": now}
    if pemakaian is not None:
        upd["pemakaian"] = pemakaian
    if galat is not None:
        upd["galat"] = galat
    if tunda is not None:
        upd["tunda"] = tunda
    await db.ai_chat_messages.update_one({"id": pesan_id, "user_id": user_id, "status": "berjalan"},
                                         {"$set": upd})


# ── Tahap B: giliran yang berhenti menunggu kartu tindakan ──────────────────
async def mulai_lanjutan(db, sesi: dict, user_id: str, *, api_user: dict, cv: str, periode: str,
                         lanjutan_dari: str) -> dict:
    """Pesan asisten LANJUTAN sesudah semua kartu satu giliran diputuskan. Giliran pengguna berisi
    tool_result langsung disimpan di `api` (riwayat tetap sah walau proses mati di tengah jawaban)."""
    now = _sekarang()
    nomor = await _urutan_berikut(db, sesi, 1)
    p = {"id": _id(), "sesi_id": sesi["id"], "user_id": user_id, "urutan": nomor, "peran": "asisten",
         "dibuat": now, "diperbarui": now, "status": "berjalan", "blok": [], "api": [api_user], "cv": cv,
         "periode": periode, "lanjutan_dari": lanjutan_dari}
    await db.ai_chat_messages.insert_one(dict(p))
    await db.ai_chat_sessions.update_one({"id": sesi["id"], "user_id": user_id},
                                         {"$set": {"updated_at": now}, "$inc": {"jumlah_pesan": 1}})
    return p


async def pesan_tunda(db, user_id: str, sesi_id: str) -> Optional[dict]:
    """Pesan asisten TERAKHIR sesi ini yang pernah berhenti menunggu kartu (keadaan tunda apa pun)."""
    rows = await db.ai_chat_messages.find({"sesi_id": sesi_id, "user_id": user_id, "tunda": {"$exists": True}},
                                          {"_id": 0, "api": 0, "blok": 0}).sort("urutan", -1).limit(1).to_list(1)
    return rows[0] if rows else None


async def tutup_tunda(db, user_id: str, pesan_id: str, cara: str) -> bool:
    """Tutup giliran tertunda SEKALI (atomik). False = sudah ditutup proses lain."""
    now = _sekarang()
    res = await db.ai_chat_messages.update_one(
        {"id": pesan_id, "user_id": user_id, "tunda.keadaan": "menunggu"},
        {"$set": {"tunda.keadaan": "selesai", "tunda.ditutup": cara, "tunda.ditutup_pada": now,
                  "status": "selesai", "diperbarui": now}})
    return bool(getattr(res, "matched_count", 0))


# ── Tahap E: ruang hitung (kontainer code execution) per percakapan ─────────
def _waktu(v) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def kontainer_sah(sesi: Optional[dict], sekarang: Optional[datetime] = None) -> Optional[str]:
    """Id kontainer sesi yang masih boleh dikirim balik (umur < UMUR_KONTAINER sejak pertama terlihat)."""
    cid = (sesi or {}).get("container_id")
    if not cid or not isinstance(cid, str):
        return None
    dibuat = _waktu((sesi or {}).get("container_dibuat"))
    if dibuat is None:
        return None
    if (sekarang or datetime.now(timezone.utc)) - dibuat >= UMUR_KONTAINER:
        return None
    return cid


async def simpan_kontainer(db, user_id: str, sesi_id: str, container_id: str, kedaluwarsa: Optional[str], *,
                           baru: bool) -> None:
    """Catat kontainer terakhir percakapan (`baru=True` = id berbeda dari sebelumnya → umur dihitung ulang)."""
    upd = {"container_id": str(container_id), "container_kedaluwarsa": kedaluwarsa}
    if baru:
        upd["container_dibuat"] = _sekarang()
    await db.ai_chat_sessions.update_one({"id": sesi_id, "user_id": user_id}, {"$set": upd})


async def lupakan_kontainer(db, user_id: str, sesi_id: str) -> None:
    """Kontainer ditolak API (kedaluwarsa) → percakapan memakai kontainer baru pada permintaan berikutnya."""
    await db.ai_chat_sessions.update_one(
        {"id": sesi_id, "user_id": user_id},
        {"$unset": {"container_id": "", "container_kedaluwarsa": "", "container_dibuat": ""}})
