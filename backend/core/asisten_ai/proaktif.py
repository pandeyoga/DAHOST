"""Asisten AI proaktif (Tahap D2, keputusan owner no. 12): briefing pagi, peringatan harian, laporan mingguan.

Mekanik
  * Penjadwal: SATU job `asisten_ai_proaktif` di `utils/scheduler.py` (APScheduler, Asia/Jakarta) berdetak
    tiap menit dan memanggil `detak()`. Jam & saklar dibaca dari pengaturan AI (Monitor AI › Pengaturan)
    pada setiap detak, jadi perubahan jam langsung berlaku di detak berikutnya tanpa mendaftar ulang job.
    Detak yang terlewat (server mati saat 07:00) masih dikejar selama 3 jam sesudah jamnya.
  * Idempoten per hari per jenis: setiap jalan mengklaim kunci `<jenis>:<tanggal>:<penerima>` di koleksi
    `ai_proaktif_runs` (`_id` = kunci → unik di MongoDB; ditambah kunci proses). Penjadwal yang restart
    atau terpicu dua kali tidak membuat briefing kedua.
  * Briefing & laporan mingguan = loop agen yang sama dengan chat (`mesin.Jalan`), dijalankan TANPA layar
    sebagai pengguna penerima: token internal dari `auth.create_token(user)` hanya hidup di memori proses
    selama jalan itu (tidak pernah dicatat/disimpan), sehingga alat membaca data dengan hak akses penerima.
    Sesi baru `{jenis: "briefing"|"laporan_mingguan"}`; alat tindakan TIDAK PERNAH ditawarkan; alat ingatan
    tidak ditawarkan (ingatan tetap disuntikkan sebagai acuan). Gerbang anggaran + log pemakaian memakai
    fitur `asisten-ai-proaktif`.
  * Sesudah selesai: notifikasi in-app ke penerima lewat `publish_notification`, tautan ke sesi:
    `link_module="asisten-ai"`, `link_id=<sesi>`, `link_params={"sesi": <sesi>}` (bel → navigasi modul
    dengan parameter `sesi`); bentuk URL-nya `?portal=management&module=asisten-ai&sesi=<id>`.
  * Penjaga: kunci kosong / AI dimatikan / anggaran habis → dilewati DIAM-DIAM (hanya log), dicoba lagi
    paling cepat 10 menit kemudian selama jendela 3 jam. Peringatan harian tanpa AI (lihat `peringatan.py`),
    hanya dilewati bila AI dimatikan admin.
  * Pemicu manual `POST /api/asisten-ai/proaktif/{jenis}/jalankan-sekarang` (owner/superadmin): briefing/
    laporan dibuat untuk PEMICU sendiri (berjalan di latar, jawab segera dengan id sesi); peringatan dijalankan
    langsung (tetap sekali per hari per kondisi). Pemicu manual tidak terhalang saklar jadwal.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
import uuid
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Optional

import ai_cost_tracker as tracker
from core.asisten_ai import ingatan as ing
from core.asisten_ai import mesin, simpan
from core.asisten_ai import peringatan as prg

log = logging.getLogger(__name__)

FITUR = "asisten-ai-proaktif"
KOLEKSI = "ai_proaktif_runs"
JENIS = ("briefing", "peringatan", "laporan_mingguan")
JENIS_SESI = ("briefing", "laporan_mingguan")
LABEL_JENIS = {"briefing": "Briefing pagi", "peringatan": "Peringatan harian", "laporan_mingguan": "Laporan mingguan"}
SETELAN = {  # jenis → (kunci saklar, kunci jam, jam bawaan)
    "briefing": ("asisten_briefing_aktif", "asisten_briefing_jam", "07:00"),
    "peringatan": ("asisten_peringatan_aktif", "asisten_peringatan_jam", "07:00"),
    "laporan_mingguan": ("asisten_laporan_mingguan_aktif", "asisten_laporan_mingguan_jam", "07:30"),
}
KUNCI_PENERIMA = "asisten_briefing_penerima"
PERAN_PEMICU = frozenset({"owner", "superadmin"})
JENDELA = timedelta(hours=3)          # detak yang terlewat dikejar sampai 3 jam sesudah jamnya
JEDA_ULANG = timedelta(minutes=10)    # sesudah dilewati penjaga (kunci/anggaran), coba lagi paling cepat 10 mnt
BATAS_DETIK_JALAN = 480.0
MAKS_PENERIMA = 20
CV_BAWAAN = "DA"                      # keputusan owner no. 8: bawaan DA (sama dengan chat)
_JAM_RX = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")
_HARI = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
_BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
          "Oktober", "November", "Desember")

# Keadaan proses (satu worker uvicorn; klaim DB tetap menjadi penjaga utama).
_KUNCI_KLAIM: dict = {}               # id event loop → asyncio.Lock (kunci proses untuk cek+tulis klaim)
_BERJALAN: set = set()                # (jenis, tanggal) jalan terjadwal yang sedang berjalan
_TUNTAS: set = set()                  # (jenis, tanggal) jalan terjadwal yang sudah tuntas hari itu
_TUNDA: dict = {}                     # (jenis, tanggal) → datetime: jangan dicoba sebelum waktu ini
_MANUAL: set = set()                  # (jenis, user_id) jalan manual yang sedang berjalan
_TUGAS: set = set()


class GalatProaktif(Exception):
    def __init__(self, status: int, pesan: str):
        super().__init__(pesan)
        self.status = int(status)
        self.pesan = str(pesan)


# ── Pembantu ─────────────────────────────────────────────────────────────────
def _wib():
    from utils.waktu import WIB
    return WIB


def sekarang_wib() -> datetime:
    return datetime.now(_wib())


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def jam_sah(v: Any) -> Optional[str]:
    """"HH:MM" (00:00–23:59) yang dinormalkan, atau None bila tidak sah."""
    if not isinstance(v, str):
        return None
    m = _JAM_RX.match(v)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _jam(v: Any, bawaan: str) -> dtime:
    j = jam_sah(v) or bawaan
    hh, mm = j.split(":")
    return dtime(int(hh), int(mm))


def pengguna_aktif(u: Optional[dict]) -> bool:
    """Aturan yang sama dengan `auth._load_live_user` (akun nonaktif/terblokir = tidak aktif)."""
    if not u:
        return False
    blocked = u.get("is_active") is False or (u.get("status") not in (None, "active") and not u.get("active", True))
    return not blocked


def tgl_singkat(d: date) -> str:
    return prg.tgl(d)


def tgl_panjang(d: date) -> str:
    return f"{_HARI[d.weekday()]}, {d.day} {_BULAN[d.month - 1]} {d.year}"


def minggu_lalu(d: date) -> tuple[date, date]:
    """(Senin, Minggu) pekan SEBELUM pekan tanggal `d`."""
    senin_ini = d - timedelta(days=d.weekday())
    return senin_ini - timedelta(days=7), senin_ini - timedelta(days=1)


def tautan_sesi(sesi_id: str) -> str:
    return f"?portal=management&module=asisten-ai&sesi={sesi_id}"


def _app():
    """Aplikasi FastAPI yang sedang berjalan (uvicorn memuat `server:app`) untuk panggilan ASGI dalam proses."""
    m = sys.modules.get("server")
    return getattr(m, "app", None) if m is not None else None


def _db():
    from database import get_db
    return get_db()


# ── Pengaturan ───────────────────────────────────────────────────────────────
async def pengaturan() -> dict:
    s = await tracker.get_ai_settings()
    out = {}
    for jenis, (k_aktif, k_jam, bawaan) in SETELAN.items():
        out[jenis] = {"aktif": s.get(k_aktif, True) is not False, "jam": jam_sah(s.get(k_jam)) or bawaan}
    pen = s.get(KUNCI_PENERIMA) or []
    out["penerima"] = [str(x) for x in pen if isinstance(x, str) and x.strip()] if isinstance(pen, list) else []
    out["ai_mati"] = (not s.get("ai_enabled", True)) or tracker._feature_disabled(mesin.FITUR,
                                                                                 s.get("disabled_features"))
    return out


def jatuh_tempo(jenis: str, cfg: dict, now: datetime) -> Optional[date]:
    """Tanggal (WIB) bila jalan terjadwal `jenis` jatuh tempo pada `now`, atau None."""
    c = cfg.get(jenis) or {}
    if not c.get("aktif"):
        return None
    hari = now.date()
    if jenis == "laporan_mingguan" and hari.weekday() != 0:
        return None
    mulai = datetime.combine(hari, _jam(c.get("jam"), SETELAN[jenis][2]), tzinfo=now.tzinfo)
    if not (mulai <= now < mulai + JENDELA):
        return None
    return hari


def jadwal_berikut(jenis: str, cfg: dict, now: Optional[datetime] = None) -> Optional[str]:
    """Waktu jalan terjadwal berikutnya (ISO WIB) — untuk layar pengaturan."""
    c = cfg.get(jenis) or {}
    if not c.get("aktif"):
        return None
    now = now or sekarang_wib()
    jam = _jam(c.get("jam"), SETELAN[jenis][2])
    for i in range(0, 8):
        d = now.date() + timedelta(days=i)
        if jenis == "laporan_mingguan" and d.weekday() != 0:
            continue
        t = datetime.combine(d, jam, tzinfo=now.tzinfo)
        if t > now:
            return t.isoformat()
    return None


# ── Klaim sekali-sehari ──────────────────────────────────────────────────────
def _kunci_proses() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    k = _KUNCI_KLAIM.get(id(loop))
    if k is None:
        _KUNCI_KLAIM.clear()          # loop lama (uji) tidak dipakai lagi
        k = _KUNCI_KLAIM[id(loop)] = asyncio.Lock()
    return k


async def klaim(db, kunci: str, data: dict) -> bool:
    """Klaim kunci jalan SEKALI. False = sudah diklaim (jalan lain / hari ini sudah).
    `_id` = kunci → MongoDB menolak klaim kedua (DuplicateKeyError) walau dua proses berlomba."""
    async with _kunci_proses():
        if await db.ai_proaktif_runs.find_one({"id": kunci}, {"_id": 0, "id": 1}):
            return False
        doc = {"_id": kunci, "id": kunci, **data, "dibuat": _iso(), "diperbarui": _iso()}
        try:
            await db.ai_proaktif_runs.insert_one(doc)
        except Exception as e:  # noqa: BLE001 — DuplicateKeyError (pymongo) = sudah diklaim proses lain
            if "duplicate" in type(e).__name__.lower() or "E11000" in str(e):
                return False
            raise
        return True


async def catat(db, kunci: str, **upd) -> None:
    upd["diperbarui"] = _iso()
    await db.ai_proaktif_runs.update_one({"id": kunci}, {"$set": upd})


async def riwayat(db, limit: int = 20) -> list[dict]:
    rows = await db.ai_proaktif_runs.find({}, {"_id": 0}).sort("dibuat", -1).to_list(max(1, min(limit, 100)))
    rows.sort(key=lambda r: str(r.get("dibuat") or ""), reverse=True)
    keep = ("id", "jenis", "tanggal", "user_id", "kondisi", "pemicu", "status", "alasan", "sesi_id", "jumlah",
            "notifikasi", "dibuat", "diperbarui")
    return [{k: r.get(k) for k in keep if k in r} for r in rows[:limit]]


# ── Penerima ─────────────────────────────────────────────────────────────────
_PROYEKSI_USER = {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1, "status": 1, "active": 1, "is_active": 1,
                  "vendor_id": 1, "buyer_id": 1, "customer_name": 1, "buyer_company": 1, "employee_id": 1,
                  "cmt_vendor_id": 1, "department": 1}


async def penerima(db, cfg: dict) -> list[dict]:
    """Penerima briefing/laporan: daftar di pengaturan, atau (kosong) semua owner aktif."""
    ids = cfg.get("penerima") or []
    q = {"id": {"$in": ids}} if ids else {"role": "owner"}
    rows = await db.users.find(q, dict(_PROYEKSI_USER)).to_list(MAKS_PENERIMA * 3)
    out, lihat = [], set()
    for u in rows:
        if u.get("id") and u["id"] not in lihat and pengguna_aktif(u) and (ids or u.get("role") == "owner"):
            lihat.add(u["id"])
            out.append(u)
    out.sort(key=lambda u: str(u.get("id")))
    return out[:MAKS_PENERIMA]


def _token_untuk(u: dict) -> str:
    """Token internal (24 jam) sebagai pengguna itu — HANYA di memori; jangan pernah dicatat atau disimpan."""
    from auth import create_token
    data = dict(u)
    data["email"] = data.get("email") or ""
    data["name"] = data.get("name") or data.get("email") or "Pengguna"
    data["role"] = data.get("role") or ""
    return create_token(data)


def _user_dari_token(token: str, u: dict) -> dict:
    from auth import verify_token_str
    payload = verify_token_str(token) or {}
    payload.pop("exp", None)
    payload["role"] = u.get("role") or payload.get("role") or ""
    return payload


# ── Teks permintaan otomatis (bahasa Indonesia, tetap) ───────────────────────
def prompt_briefing(hari: date) -> str:
    kemarin = hari - timedelta(days=1)
    return (
        f"Buatkan briefing pagi untuk hari ini, {tgl_panjang(hari)}. Ini pesan otomatis terjadwal. Tulis ringkas "
        "dan mudah dipindai, dengan subjudul per bagian dan urutan berikut:\n"
        f"1. Omzet kemarin ({tgl_singkat(kemarin)}) dan omzet bulan berjalan sampai kemarin dibanding target per "
        "toko; sebut toko yang tertinggal dari laju target.\n"
        "2. Posisi kas dan bank saat ini.\n"
        "3. Piutang yang jatuh tempo dalam 7 hari ke depan dan yang sudah lewat jatuh tempo.\n"
        "4. Peringatan stok: bahan di bawah titik pesan ulang atau stok minimum.\n"
        "5. PO produksi yang terlambat dari tenggat.\n"
        "6. Persetujuan yang menunggu keputusan saya, bila alatnya tersedia.\n"
        "7. Kepatuhan staf memakai sistem, bila alat pantau_staf tersedia: kewajiban yang terlambat (menunggu "
        "siapa, sejak kapan) dan staf yang hadir tetapi tidak membuka sistem.\n"
        "Pakai alat data untuk setiap angka. Bila data suatu bagian tidak bisa dibaca, sebut singkat lalu lanjut. "
        "Paling banyak dua grafik. Tutup dengan dua atau tiga hal yang paling perlu diperhatikan hari ini. "
        "Jangan mengubah atau menyiapkan perubahan data apa pun."
    )


def prompt_laporan_mingguan(senin: date, minggu: date) -> str:
    rentang = f"{tgl_singkat(senin)} – {tgl_singkat(minggu)}"
    return (
        f"Buat laporan mingguan untuk pekan {rentang} (Senin–Minggu). Ini pesan otomatis terjadwal. "
        "Kumpulkan dulu dengan alat baca: omzet dan pesanan pekan itu dibanding pekan sebelumnya per toko, capaian "
        "target bulan berjalan, posisi kas dan bank, piutang jatuh tempo, stok di bawah titik pesan ulang, dan PO "
        "produksi yang terlambat, serta kepatuhan staf memakai sistem bila alat pantau_staf tersedia (per staf dan "
        "langkah alur yang paling sering macet). Untuk bagian Marketing, bila alatnya tersedia panggil "
        "paket_laporan_marketing (jenis mingguan, pekan yang sama) dan pakai angkanya untuk per toko/kanal, iklan (ROAS, TACoS), batal/retur, "
        "biaya platform, dan anomali. Untuk bagian Merchandiser, bila alatnya tersedia panggil analisa_merchandiser "
        "(kelas mati,lambat untuk 10 model dengan nilai stok HPP terbesar; kelas laris,habis untuk model yang akan "
        "habis) dan jejak_pengaman_merchandiser (hari 7: PO/PR sepekan itu yang lolos pengaman dengan alasan); "
        "sebut cakupan datanya dan usulan tindakan per kelas. Lalu panggil buat_laporan dengan format PDF dan Excel, judul "
        f"\"Laporan mingguan {rentang}\", berisi ringkasan, tabel per bagian, dan paling banyak dua grafik. "
        "Sesudah laporan dibuat, tulis ringkasan singkat temuan utamanya di chat. Jangan mengubah atau menyiapkan "
        "perubahan data apa pun."
    )


def judul_sesi(jenis: str, hari: date) -> str:
    if jenis == "laporan_mingguan":
        senin, minggu = minggu_lalu(hari)
        return f"Laporan mingguan {tgl_singkat(senin)} – {tgl_singkat(minggu)}"
    return f"Briefing pagi {tgl_singkat(hari)}"


def teks_permintaan(jenis: str, hari: date) -> str:
    if jenis == "laporan_mingguan":
        return prompt_laporan_mingguan(*minggu_lalu(hari))
    return prompt_briefing(hari)


# ── Jalan tanpa layar (briefing / laporan mingguan) ──────────────────────────
class Siap:
    """Jalan yang sudah disiapkan (sesi dibuat, belum dimulai)."""

    def __init__(self, *, jalan: mesin.Jalan, jenis: str, hari: date, kunci: str, user: dict, db):
        self.jalan = jalan
        self.jenis = jenis
        self.hari = hari
        self.kunci = kunci
        self.user = user
        self.db = db

    @property
    def sesi_id(self) -> str:
        return self.jalan.sesi_id


async def siapkan_satu(db, u: dict, jenis: str, hari: date, *, kunci: str, pemicu: str, app=None, klien=None,
                       klien_api=None) -> tuple[Optional[Siap], dict]:
    """Klaim + token internal + cek akses + gerbang + sesi baru + `Jalan`. Return (Siap | None, info)."""
    uid = u.get("id")
    info = {"jenis": jenis, "tanggal": hari.isoformat(), "user_id": uid, "pemicu": pemicu}
    if not await klaim(db, kunci, {**info, "status": "berjalan"}):
        return None, {**info, "status": "sudah"}
    try:
        return await _siapkan_sesudah_klaim(db, u, jenis, hari, kunci=kunci, info=info, app=app, klien=klien,
                                            klien_api=klien_api)
    except BaseException:
        await catat(db, kunci, status="gagal", alasan="internal")
        raise


async def _siapkan_sesudah_klaim(db, u: dict, jenis: str, hari: date, *, kunci: str, info: dict, app, klien,
                                 klien_api) -> tuple[Optional[Siap], dict]:
    uid = u.get("id")
    token = _token_untuk(u)
    user = _user_dari_token(token, u)
    app = app if app is not None else _app()
    if app is None and klien_api is None:
        await catat(db, kunci, status="dilewati", alasan="aplikasi_tidak_tersedia")
        log.warning("Asisten AI proaktif: %s untuk %s dilewati (aplikasi tidak tersedia)", jenis, uid)
        return None, {**info, "status": "dilewati", "alasan": "aplikasi_tidak_tersedia"}
    # Akses Portal Manajemen = gerbang router Asisten AI yang SAMA (panggilan dalam proses dengan token penerima).
    from core.asisten_ai import alat_base as ab
    cek = ab.AlatContext(user=user, cv=CV_BAWAAN, today=hari, token=token, app=app, klien_api=klien_api,
                         baca_saja=True)
    try:
        await cek.api("GET", "/api/asisten-ai/status")
    except ab.AlatError as e:
        alasan = "tanpa_akses" if e.status in (401, 403) else "cek_gagal"
        await catat(db, kunci, status="dilewati", alasan=alasan)
        log.info("Asisten AI proaktif: %s untuk %s dilewati (akses %s)", jenis, uid, e.status)
        return None, {**info, "status": "dilewati", "alasan": alasan}
    finally:
        await cek.tutup()
    g = await mesin.gerbang(uid, fitur=FITUR)
    if not g.ok:
        kode = mesin.galat_dari_gerbang(g)["kode"]
        await catat(db, kunci, status="dilewati", alasan=kode)
        log.info("Asisten AI proaktif: %s untuk %s dilewati (%s)", jenis, uid, kode)
        return None, {**info, "status": "dilewati", "alasan": kode}
    sesi = await simpan.buat_sesi(db, uid, judul_sesi(jenis, hari), jenis=jenis)
    sesi_doc = await simpan.ambil_sesi(db, uid, sesi["id"])
    jalan = mesin.Jalan(db=db, user=user, sesi=sesi_doc, teks=teks_permintaan(jenis, hari), cv=CV_BAWAAN,
                        periode=f"{hari.year:04d}-{hari.month:02d}", today=hari, token=token, app=app,
                        klien=klien, klien_api=klien_api, api_key=g.api_key, peringatan=None,
                        batas_detik=BATAS_DETIK_JALAN, tindakan_aktif=False, ingatan_aktif=await ing.aktif(),
                        fitur=FITUR, otomatis=True)
    await catat(db, kunci, sesi_id=sesi["id"])
    return Siap(jalan=jalan, jenis=jenis, hari=hari, kunci=kunci, user=user, db=db), {**info, "status": "berjalan",
                                                                                       "sesi_id": sesi["id"]}


def _cuplikan(blok: list) -> str:
    """Awal blok teks TERAKHIR jawaban (ringkasan penutup), tanpa markdown, ≤ 160 karakter."""
    teks_blok = [b.get("isi") or "" for b in blok if b.get("jenis") == "teks" and (b.get("isi") or "").strip()]
    teks = teks_blok[-1] if teks_blok else ""
    teks = re.sub(r"[#*_`>|]+", " ", teks)
    teks = " ".join(teks.split())
    return (teks[:157] + "…") if len(teks) > 160 else teks


async def selesaikan(s: Siap) -> dict:
    """Jalankan loop agen sampai selesai, lalu kirim notifikasi bertautan sesi (hanya bila berhasil)."""
    j = s.jalan
    uid = s.user.get("id")
    try:
        task = mesin.mulai(j)
        await task
    except Exception:  # noqa: BLE001
        log.exception("Asisten AI proaktif: %s untuk %s gagal", s.jenis, uid)
    status = j.status if j.status in ("selesai", "gagal", "terhenti") else "gagal"
    laporan = [b for b in j.blok if b.get("jenis") == "laporan"]
    out = {"jenis": s.jenis, "tanggal": s.hari.isoformat(), "user_id": uid, "sesi_id": j.sesi_id,
           "status": status, "biaya_usd": j.pemakaian.get("biaya_usd")}
    if status != "selesai":
        await s.db.ai_proaktif_runs.update_one({"id": s.kunci}, {"$set": {
            "status": "gagal", "alasan": (j.galat or {}).get("kode") or status, "diperbarui": _iso()}})
        log.warning("Asisten AI proaktif: %s untuk %s berakhir %s", s.jenis, uid, status)
        return out
    if s.jenis == "laporan_mingguan":
        judul = "Laporan mingguan siap" if laporan else "Ringkasan mingguan siap"
        pesan = f"{judul_sesi(s.jenis, s.hari)}" + (" — berkas PDF/Excel ada di percakapan." if laporan else
                                                     " — berkas laporan belum terbentuk; ringkasan ada di percakapan.")
    else:
        judul = "Briefing pagi siap"
        pesan = f"Briefing pagi {tgl_panjang(s.hari)} sudah siap dibaca di Asisten AI."
    cup = _cuplikan(j.blok)
    if cup:
        pesan = f"{pesan} {cup}"
    nid = None
    try:
        from routes.rahaza_notifications import publish_notification
        doc = await publish_notification(
            s.db, type_=f"asisten_ai_{s.jenis}", severity="info", title=judul, message=pesan[:400],
            link_module="asisten-ai", link_id=j.sesi_id, target_user_ids=[uid],
            dedup_key=f"asisten_ai:{s.jenis}:{j.sesi_id}", dedup_minutes=1440,
            link_params={"sesi": j.sesi_id})
        nid = (doc or {}).get("id")
    except Exception:  # noqa: BLE001 — notifikasi gagal tidak membatalkan sesi yang sudah jadi
        log.exception("Asisten AI proaktif: notifikasi %s untuk %s gagal", s.jenis, uid)
    await s.db.ai_proaktif_runs.update_one({"id": s.kunci}, {"$set": {
        "status": "selesai", "notifikasi": nid, "laporan": bool(laporan), "diperbarui": _iso(),
        "biaya_usd": j.pemakaian.get("biaya_usd")}})
    out.update({"notifikasi": nid, "laporan": bool(laporan), "tautan": tautan_sesi(j.sesi_id)})
    return out


async def jalankan_untuk(db, u: dict, jenis: str, hari: date, *, kunci: str, pemicu: str = "jadwal", app=None,
                         klien=None, klien_api=None) -> dict:
    s, info = await siapkan_satu(db, u, jenis, hari, kunci=kunci, pemicu=pemicu, app=app, klien=klien,
                                 klien_api=klien_api)
    if s is None:
        return info
    return await selesaikan(s)


# ── Peringatan harian (tanpa AI) ─────────────────────────────────────────────
async def jalankan_peringatan(db, hari: date, *, pemicu: str = "jadwal") -> dict:
    """Periksa 4 kondisi lalu kirim notifikasi ringkas, paling banyak sekali per hari per kondisi & penerima."""
    from routes.rahaza_notifications import publish_notification
    kabar, status = await prg.periksa_semua(db, hari)
    out = {"jenis": "peringatan", "tanggal": hari.isoformat(), "pemicu": pemicu, "pemeriksa": status,
           "kondisi": [], "notifikasi": 0}
    for k in kabar:
        kunci = f"peringatan:{k.kondisi}:{hari.isoformat()}:{k.penerima}"
        row = {"kondisi": k.kondisi, "penerima": "owner" if k.penerima == "umum" else "pic", "jumlah": k.jumlah}
        if not await klaim(db, kunci, {"jenis": "peringatan", "tanggal": hari.isoformat(), "kondisi": k.kondisi,
                                       "pemicu": pemicu, "status": "berjalan", "jumlah": k.jumlah}):
            out["kondisi"].append({**row, "dikirim": False, "alasan": "sudah_dikirim_hari_ini"})
            continue
        try:
            doc = await publish_notification(
                db, type_=prg.SUBTYPE[k.kondisi], severity=k.severity, title=k.judul, message=k.isi,
                link_module=prg.MENU[k.kondisi], target_roles=k.target_roles or None,
                target_user_ids=k.target_user_ids or None,
                dedup_key=f"asisten_ai:peringatan:{k.kondisi}:{hari.isoformat()}:{k.penerima}", dedup_minutes=1440)
            await catat(db, kunci, status="terkirim", notifikasi=(doc or {}).get("id"))
            out["notifikasi"] += 1
            out["kondisi"].append({**row, "dikirim": True})
        except Exception:  # noqa: BLE001
            log.exception("Peringatan Asisten AI: kirim %s gagal", k.kondisi)
            await catat(db, kunci, status="gagal", alasan="kirim_gagal")
            out["kondisi"].append({**row, "dikirim": False, "alasan": "kirim_gagal"})
    log.info("Peringatan Asisten AI %s (%s): %s notifikasi, pemeriksa %s", hari, pemicu, out["notifikasi"], status)
    return out


# ── Penjadwal ────────────────────────────────────────────────────────────────
async def _jalan_terjadwal(db, jenis: str, hari: date, cfg: dict, *, now: Optional[datetime] = None, app=None,
                          klien=None, klien_api=None) -> dict:
    tkey = (jenis, hari)
    if jenis == "peringatan":
        if not await klaim(db, f"peringatan:{hari.isoformat()}", {"jenis": "peringatan", "tanggal": hari.isoformat(),
                                                                  "pemicu": "jadwal", "status": "berjalan"}):
            _TUNTAS.add(tkey)
            return {"jenis": jenis, "status": "sudah"}
        out = await jalankan_peringatan(db, hari, pemicu="jadwal")
        await catat(db, f"peringatan:{hari.isoformat()}", status="selesai", jumlah=out["notifikasi"])
        _TUNTAS.add(tkey)
        return out
    g = await mesin.gerbang(None, fitur=FITUR, log_blocked=False)
    if not g.ok:
        kode = mesin.galat_dari_gerbang(g)["kode"]
        if tkey not in _TUNDA:
            log.info("Asisten AI proaktif: %s %s dilewati (%s); dicoba lagi nanti selama jendela jadwal",
                     jenis, hari, kode)
        _TUNDA[tkey] = (now or sekarang_wib()) + JEDA_ULANG
        return {"jenis": jenis, "status": "dilewati", "alasan": kode}
    hasil = []
    for u in await penerima(db, cfg):
        kunci = f"{jenis}:{hari.isoformat()}:{u['id']}"
        try:
            hasil.append(await jalankan_untuk(db, u, jenis, hari, kunci=kunci, pemicu="jadwal", app=app,
                                              klien=klien, klien_api=klien_api))
        except Exception:  # noqa: BLE001 — satu penerima gagal tidak menghentikan penerima lain
            log.exception("Asisten AI proaktif: %s untuk %s gagal", jenis, u.get("id"))
            await catat(db, kunci, status="gagal", alasan="internal")
    _TUNTAS.add(tkey)
    return {"jenis": jenis, "status": "selesai", "hasil": hasil}


async def detak(now: Optional[datetime] = None, *, tunggu: bool = False, db=None, app=None, klien=None,
                klien_api=None) -> dict:
    """Detak penjadwal (tiap menit). Memulai jalan yang jatuh tempo di LATAR (job kembali cepat).
    `tunggu=True` (uji) menunggu jalan selesai dan mengembalikan hasilnya."""
    now = now or sekarang_wib()
    db = db if db is not None else _db()
    cfg = await pengaturan()
    if cfg.get("ai_mati"):
        return {"dimulai": [], "alasan": "ai_nonaktif"}
    dimulai, tugas = [], []
    for jenis in JENIS:
        hari = jatuh_tempo(jenis, cfg, now)
        if hari is None:
            continue
        tkey = (jenis, hari)
        if tkey in _TUNTAS or tkey in _BERJALAN:
            continue
        t_ulang = _TUNDA.get(tkey)
        if t_ulang is not None and now < t_ulang:
            continue
        _BERJALAN.add(tkey)

        async def _satu(jenis=jenis, hari=hari, tkey=tkey):
            try:
                return await _jalan_terjadwal(db, jenis, hari, cfg, now=now, app=app, klien=klien,
                                              klien_api=klien_api)
            except Exception:  # noqa: BLE001
                log.exception("Asisten AI proaktif: jalan terjadwal %s gagal", jenis)
                return {"jenis": jenis, "status": "gagal"}
            finally:
                _BERJALAN.discard(tkey)
        t = asyncio.ensure_future(_satu())
        _TUGAS.add(t)
        t.add_done_callback(_TUGAS.discard)
        tugas.append(t)
        dimulai.append(jenis)
    out = {"dimulai": dimulai}
    if tunggu and tugas:
        out["hasil"] = list(await asyncio.gather(*tugas))
    return out


# ── Pemicu manual (owner/superadmin) ─────────────────────────────────────────
async def jalankan_sekarang(db, user: dict, jenis: str, *, app=None, klien=None, klien_api=None,
                            tunggu: bool = False) -> dict:
    """`POST /proaktif/{jenis}/jalankan-sekarang`. Briefing/laporan untuk pemicu sendiri (di latar);
    peringatan dijalankan langsung. Galat → `GalatProaktif` (HTTP 4xx, pesan ramah)."""
    if jenis not in JENIS:
        raise GalatProaktif(404, "Jenis harus briefing, peringatan, atau laporan_mingguan.")
    if str(user.get("role") or "").lower() not in PERAN_PEMICU:
        raise GalatProaktif(403, "Hanya owner atau superadmin yang boleh menjalankan Asisten AI proaktif secara manual.")
    hari = sekarang_wib().date()
    cfg = await pengaturan()
    if cfg.get("ai_mati"):
        raise GalatProaktif(409, mesin.PESAN_GALAT["ai_nonaktif"])
    if jenis == "peringatan":
        return await jalankan_peringatan(db, hari, pemicu="manual")
    uid = user.get("id")
    kunci_proses = (jenis, uid)
    if kunci_proses in _MANUAL:
        raise GalatProaktif(409, f"{LABEL_JENIS[jenis]} untuk Anda sedang disusun. Tunggu notifikasinya.")
    g = await mesin.gerbang(uid, fitur=FITUR)
    if not g.ok:
        raise GalatProaktif(409, mesin.galat_dari_gerbang(g)["pesan"])
    u = await db.users.find_one({"id": uid}, dict(_PROYEKSI_USER))
    if not u or not pengguna_aktif(u):
        raise GalatProaktif(404, "Akun pengguna tidak ditemukan atau tidak aktif.")
    _MANUAL.add(kunci_proses)
    try:
        kunci = f"{jenis}:{hari.isoformat()}:{uid}:manual-{uuid.uuid4().hex[:8]}"
        s, info = await siapkan_satu(db, u, jenis, hari, kunci=kunci, pemicu="manual", app=app, klien=klien,
                                     klien_api=klien_api)
    except BaseException:
        _MANUAL.discard(kunci_proses)
        raise
    if s is None:
        _MANUAL.discard(kunci_proses)
        alasan = info.get("alasan")
        if alasan == "tanpa_akses":
            raise GalatProaktif(403, "Akun ini tidak punya akses ke Asisten AI.")
        raise GalatProaktif(409, mesin.PESAN_GALAT.get(alasan or "", None) or "Jalan ini tidak bisa dimulai sekarang.")

    async def _latar():
        try:
            return await selesaikan(s)
        finally:
            _MANUAL.discard(kunci_proses)
    t = asyncio.ensure_future(_latar())
    _TUGAS.add(t)
    t.add_done_callback(_TUGAS.discard)
    out = {"jenis": jenis, "status": "berjalan", "sesi_id": s.sesi_id, "tautan": tautan_sesi(s.sesi_id),
           "pesan": f"{LABEL_JENIS[jenis]} sedang disusun. Notifikasi dikirim bila sudah siap."}
    if tunggu:
        out = {**out, **(await t)}
    return out


async def ringkasan(db) -> dict:
    """Isi `GET /api/asisten-ai/proaktif`: pengaturan efektif + jadwal berikutnya + riwayat jalan terakhir."""
    cfg = await pengaturan()
    now = sekarang_wib()
    jadwal = {j: {"aktif": cfg[j]["aktif"], "jam": cfg[j]["jam"], "berikutnya": jadwal_berikut(j, cfg, now),
                  "label": LABEL_JENIS[j]} for j in JENIS}
    return {"jadwal": jadwal, "penerima": cfg["penerima"], "ai_aktif": not cfg["ai_mati"],
            "riwayat": await riwayat(db)}
