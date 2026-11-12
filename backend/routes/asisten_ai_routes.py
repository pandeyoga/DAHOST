"""Asisten AI — chat analis Portal Manajemen (Tahap A, 7 Nov 2026). Kontrak B.

Prefix `/api/asisten-ai`. Semua endpoint: login + akses Portal Manajemen (`require_portal`,
aturan yang sama dengan portal itu). Data yang dibaca alat mengikuti hak akses PENGGUNA sendiri
(alat memanggil endpoint aplikasi dengan token pengguna, lihat core/asisten_ai/alat_base.py).

  GET    /status                   kesiapan AI (kunci terisi? AI aktif? sisa anggaran) — kunci tidak dikirim
  GET    /saran?peran=             tombol saran per peran
  GET    /sessions                 percakapan milik sendiri (terbaru dulu)
  POST   /sessions {judul?}        percakapan baru
  GET    /sessions/{id}            isi percakapan (blok tampilan; isi mentah API tidak dikirim)
  PATCH  /sessions/{id} {judul}    ganti judul
  DELETE /sessions/{id}            hapus lunak
  POST   /sessions/{id}/messages {teks, cv, periode?}  → text/event-stream (mulai, status, pikir, teks,
         alat, grafik, tabel, sumber, laporan, selesai, galat)

Hentikan: klien membatalkan fetch → server melihat koneksi putus, loop berhenti, jawaban parsial
disimpan berstatus `terhenti`.

Tahap B (8 Nov 2026, Kontrak E) — tindakan AI di balik kartu konfirmasi:
  POST   /tindakan/{id}/putuskan {keputusan: setujui|batal, ubahan?, alasan?, cv?} → text/event-stream
         (tindakan_status …, lalu mulai … selesai bila semua kartu giliran itu sudah diputuskan).
         Hanya pemilik sesi (lainnya 404); hanya selagi `menunggu` (lainnya 409).
  GET    /tindakan?status=&dari=&sampai=&halaman=&semua=   daftar (milik sendiri; owner/superadmin semua=1)
  GET    /tindakan/{id}                                     rincian (args disamarkan)
  POST   /tindakan/{id}/balikkan {alasan?}                  pembalikan (pengguna asal / owner / superadmin)
Event baru di aliran pesan: `tindakan` (kartu baru) dan `tindakan_status`.

Tahap D (8 Nov 2026, agen proaktif) — ingatan AI + briefing/peringatan/laporan mingguan:
  GET    /ingatan                       ingatan milik sendiri {items, total, aktif, batas_aktif, ...}
  POST   /ingatan {isi, kategori}       tambah manual (sumber "manual")
  PATCH  /ingatan/{id} {isi?, kategori?, aktif?}
  DELETE /ingatan/{id}                  hapus permanen
  GET    /proaktif                      jadwal efektif + riwayat jalan (owner/superadmin)
  POST   /proaktif/{jenis}/jalankan-sekarang   briefing | peringatan | laporan_mingguan (owner/superadmin)
Hanya pemilik: tidak ada tampilan admin untuk ingatan orang lain. Event baru di aliran pesan: `ingatan`.
`GET /sessions` + `GET /sessions/{id}` membawa `jenis` (chat | briefing | laporan_mingguan).

Tahap E (9 Nov 2026, Kontrak K2) — lampiran berkas:
  POST   /lampiran (multipart `berkas`)  → {id, nama, jenis, ukuran_kb, ringkas}; 400 jenis/isi salah, 413 > 20 MB
  DELETE /lampiran/{id}                  → {ok: true} (hanya pemilik, hanya bila belum terkirim)
  POST   /sessions/{id}/messages {teks, cv, periode?, lampiran?: [id…] (≤ 5)}
  `GET /sessions/{id}`: pesan pengguna membawa `lampiran: [{id, nama, jenis, ukuran_kb}]`.
  DELETE /sessions/{id} juga menghapus berkas Anthropic milik percakapan itu (upaya terbaik).
Berkas keluaran kode (K3) diunduh lewat `GET /api/asisten-ai/berkas/{id}` (routes/asisten_ai_berkas_routes.py).

Asisten AI per pengguna (10 Nov 2026, keputusan owner — core/asisten_ai/akses_pengguna.py): saklar per akun
(`users.asisten_ai.aktif`, bawaan MATI untuk staf; owner/superadmin selalu aktif) menutup KETIGA ruang. Akun yang
dimatikan masih bisa membaca riwayat & ingatannya sendiri dan membatalkan kartu, tetapi TIDAK bisa membuat percakapan,
mengirim pesan, melampirkan berkas, atau menyetujui kartu (403 / galat SSE `pengguna_nonaktif`). Batas pertanyaan per
hari → galat SSE `batas_pertanyaan`; batas tindakan per hari akun ini dipakai mesin & persetujuan kartu.
`GET /status` membawa `pengguna` = {aktif, sumber, batas_pertanyaan, batas_tindakan, pertanyaan_hari_ini} dan
`siap: false` + `alasan` pengguna_nonaktif | batas_pertanyaan bila akun ini tertahan.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from auth import require_auth
from core.asisten_ai import akses_pengguna as akp
from core.asisten_ai import ingatan as ing
from core.asisten_ai import lampiran as lmp
from core.asisten_ai import mesin, proaktif, saran, simpan
from core.asisten_ai import tindakan as tdk
from database import get_db
from routes.shared import require_portal_dep
from utils.waktu import today_wib

log = logging.getLogger(__name__)

# Audit HR Tahap D (9 Nov 2026): Asisten AI juga dibuka di Portal SDM (ruang `sdm`) dan Portal Saya (ruang `saya`,
# data milik sendiri). Gerbang router = salah satu portal itu (Portal Saya terbuka untuk semua staf internal);
# RUANG yang boleh dipakai diperiksa per percakapan (`ruang_diizinkan`): umum = Portal Manajemen, sdm = Portal
# SDM atau Manajemen, saya = semua. Alat di luar ruang tidak ditawarkan ke model (core.asisten_ai.alat_base.RUANG).
router = APIRouter(prefix="/api/asisten-ai", tags=["asisten-ai"],
                   dependencies=[Depends(require_portal_dep("management", "hr", "self"))])

PESAN_RUANG = {"umum": "Asisten AI Portal Manajemen hanya untuk akun yang punya akses Portal Manajemen.",
               "sdm": "Asisten AI Portal SDM hanya untuk akun yang punya akses Portal SDM.",
               "saya": "Ruang Asisten AI tidak dikenal."}


def _punya_portal(user: dict, portal: str) -> bool:
    """Sama dengan `routes.shared.require_portal` tetapi tanpa melempar galat."""
    from data.module_catalog import granular_portals
    from routes.shared import check_portal_access
    if check_portal_access(user, portal):
        return True
    perms = set(user.get("_permissions") or [])
    return "*" in perms or portal in granular_portals(perms) or bool({f"{portal}.manage", f"{portal}.view"} & perms)


def ruang_diizinkan(user: dict) -> list:
    out = []
    if _punya_portal(user, "management"):
        out.append("umum")
    if "umum" in out or _punya_portal(user, "hr"):
        out.append("sdm")
    out.append("saya")
    return out


def _ruang_dari(user: dict, nilai) -> str:
    """Ruang yang diminta (kosong = ruang paling luas yang diizinkan). 403 bila tidak diizinkan."""
    boleh = ruang_diizinkan(user)
    r = str(nilai or "").strip().lower() or boleh[0]
    if r not in ("umum", "sdm", "saya"):
        raise HTTPException(400, "Ruang Asisten AI harus umum, sdm, atau saya.")
    if r not in boleh:
        raise HTTPException(403, PESAN_RUANG[r])
    return r

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
_PERIODE_RX = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CV_SAH = ("DA", "SMU", "ALL")
BATAS_DETIK_HAPUS_BERKAS = 20.0


def _token(request: Request) -> Optional[str]:
    h = request.headers.get("Authorization") or ""
    return h.split(" ", 1)[1].strip() if h.startswith("Bearer ") and " " in h else None


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:  # noqa: BLE001 — badan kosong/bukan JSON
        return {}
    return b if isinstance(b, dict) else {}


def _galat_http(e: "tdk.GalatTindakan") -> HTTPException:
    return HTTPException(e.status, e.pesan)


async def _wajib_aktif(user: dict, pesan: str = akp.PESAN_NONAKTIF) -> dict:
    """Saklar Asisten AI per akun (10 Nov 2026). 403 bila akun ini dimatikan; return aturan efektif."""
    aturan, galat = await akp.periksa(get_db(), user)
    if galat:
        raise HTTPException(403, pesan)
    return aturan


@router.get("/status")
async def status(request: Request):
    user = await require_auth(request)
    db = get_db()
    out = await mesin.status_siap()
    out["ruang"] = ruang_diizinkan(user)
    try:
        out["tindakan_hari_ini"] = await tdk.jumlah_hari_ini(db, user["id"])
    except Exception:  # noqa: BLE001 — status tetap tampil walau hitungan gagal
        out["tindakan_hari_ini"] = None
    # Asisten AI per pengguna (10 Nov 2026): saklar + batas akun ini. Akun tertahan → siap: false + alasan sendiri.
    aturan = await akp.aturan(db, user)
    pertanyaan = await akp.jumlah_pertanyaan_hari_ini(db, user["id"])
    out["pengguna"] = {**aturan, "pertanyaan_hari_ini": pertanyaan}
    out["batas_tindakan_harian"] = aturan["batas_tindakan"]
    # Akun dimatikan selalu menang (apa pun keadaan AI); batas pertanyaan hanya bila AI-nya sendiri siap.
    if not aturan["aktif"]:
        out.update({"siap": False, "alasan": akp.KODE_NONAKTIF, "pesan": akp.PESAN_NONAKTIF})
    elif out.get("siap") and aturan["batas_pertanyaan"] > 0 and pertanyaan >= aturan["batas_pertanyaan"]:
        out.update({"siap": False, "alasan": akp.KODE_BATAS_PERTANYAAN,
                    "pesan": akp.PESAN_BATAS_PERTANYAAN.format(batas=aturan["batas_pertanyaan"])})
    return out


@router.get("/saran")
async def daftar_saran(request: Request, peran: Optional[str] = None, ruang: Optional[str] = None):
    user = await require_auth(request)
    return saran.saran_untuk(peran or user.get("role"), _ruang_dari(user, ruang) if ruang else None)


@router.get("/sessions")
async def daftar_sesi(request: Request, ruang: Optional[str] = None):
    user = await require_auth(request)
    db = get_db()
    rows = await simpan.daftar_sesi(db, user["id"])
    # Audit HR Tahap D: riwayat per ruang (Portal SDM / Portal Saya hanya menampilkan percakapannya sendiri)
    r = _ruang_dari(user, ruang)
    rows = [x for x in rows if (x.get("ruang") or "umum") == r]
    menunggu = await tdk.sesi_menunggu(db, user["id"])
    for r in rows:
        r["ada_tindakan_menunggu"] = r["id"] in menunggu
    return rows


@router.post("/sessions")
async def buat_sesi(request: Request):
    user = await require_auth(request)
    body = await _body(request)
    ruang = _ruang_dari(user, body.get("ruang"))
    await _wajib_aktif(user)
    return await simpan.buat_sesi(get_db(), user["id"], body.get("judul"), ruang=ruang)


@router.get("/sessions/{sesi_id}")
async def ambil_sesi(sesi_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    sesi = await simpan.ambil_sesi(db, user["id"], sesi_id)
    if not sesi:
        raise HTTPException(404, "Percakapan tidak ditemukan.")
    pesan = await simpan.ambil_pesan(db, user["id"], sesi_id)
    # Kartu tindakan = keadaan SAAT INI dari ai_actions (bukan keadaan saat aliran).
    menunggu = await tdk.segarkan_pesan(db, user["id"], sesi_id, pesan)
    return {"id": sesi["id"], "judul": sesi.get("judul") or simpan.JUDUL_BAWAAN,
            "jenis": sesi.get("jenis") if sesi.get("jenis") in simpan.JENIS_SESI else "chat",
            "created_at": sesi.get("created_at"), "updated_at": sesi.get("updated_at"),
            "sedang_berjalan": mesin.sedang_berjalan(sesi["id"]), "ada_tindakan_menunggu": menunggu,
            "pesan": pesan}


@router.patch("/sessions/{sesi_id}")
async def ubah_sesi(sesi_id: str, request: Request):
    user = await require_auth(request)
    body = await _body(request)
    try:
        out = await simpan.ubah_judul(get_db(), user["id"], sesi_id, body.get("judul"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not out:
        raise HTTPException(404, "Percakapan tidak ditemukan.")
    return out


@router.delete("/sessions/{sesi_id}")
async def hapus_sesi(sesi_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    if not await simpan.hapus_sesi(db, user["id"], sesi_id):
        raise HTTPException(404, "Percakapan tidak ditemukan.")
    # Kartu yang belum diputuskan di percakapan yang dihapus tidak bisa diputuskan lagi.
    await tdk.kedaluwarsakan_sesi(db, user["id"], sesi_id)
    # Tahap E: berkas di Anthropic (lampiran terkirim + berkas keluaran kode) ikut dihapus — upaya terbaik.
    try:
        klien = await mesin.klien_berkas()
        await asyncio.wait_for(lmp.hapus_berkas_sesi(db, user["id"], sesi_id, klien), timeout=BATAS_DETIK_HAPUS_BERKAS)
    except Exception:  # noqa: BLE001 — percakapan tetap terhapus walau berkas Anthropic gagal dihapus
        log.warning("Asisten AI: berkas Anthropic percakapan %s gagal dihapus", sesi_id, exc_info=True)
    return {"ok": True}


@router.post("/sessions/{sesi_id}/messages")
async def kirim_pesan(sesi_id: str, request: Request):
    user = await require_auth(request)
    db = get_db()
    body = await _body(request)
    teks = str(body.get("teks") or "").strip()
    if not teks:
        raise HTTPException(400, "Pertanyaan wajib diisi.")
    if len(teks) > mesin.MAKS_TEKS_PENGGUNA:
        raise HTTPException(400, f"Pertanyaan terlalu panjang (maksimal {mesin.MAKS_TEKS_PENGGUNA} karakter).")
    cv = str(body.get("cv") or "DA").strip().upper()
    if cv not in CV_SAH:
        raise HTTPException(400, "Pilihan CV harus DA, SMU, atau ALL.")
    today = today_wib()
    periode = str(body.get("periode") or "").strip() or today.strftime("%Y-%m")
    if not _PERIODE_RX.match(periode):
        raise HTTPException(400, "Periode harus berformat YYYY-MM, mis. 2026-11.")
    sesi = await simpan.ambil_sesi(db, user["id"], sesi_id)
    if not sesi:
        raise HTTPException(404, "Percakapan tidak ditemukan.")
    _ruang_dari(user, sesi.get("ruang") or "umum")   # akses portal dicabut sesudah percakapan dibuat → 403
    # Asisten AI per pengguna (10 Nov 2026): akun dimatikan / batas pertanyaan hari ini → galat lewat aliran yang
    # sama dengan gerbang AI (tidak ada pesan yang disimpan).
    aturan, galat = await akp.periksa(db, user, kirim=True)
    if galat:
        return StreamingResponse(mesin.aliran_galat(galat["kode"], galat["pesan"]),
                                 media_type="text/event-stream", headers=_SSE_HEADERS)
    try:
        lampiran = await lmp.periksa_untuk_pesan(db, user["id"], body.get("lampiran"))
    except lmp.GalatLampiran as e:
        raise HTTPException(e.status, e.pesan) from None

    jalan, galat = await mesin.siapkan_jalan(db=db, user=user, sesi=sesi, teks=teks, cv=cv, periode=periode,
                                             today=today, token=_token(request), app=request.app,
                                             lampiran=lampiran, batas_tindakan=aturan["batas_tindakan"])
    if galat:
        return StreamingResponse(mesin.aliran_galat(galat["kode"], galat["pesan"]),
                                 media_type="text/event-stream", headers=_SSE_HEADERS)
    mesin.mulai(jalan)
    return StreamingResponse(mesin.aliran_sse(jalan, request), media_type="text/event-stream",
                             headers=_SSE_HEADERS)


# ── Tahap E: lampiran berkas (Kontrak K2) ────────────────────────────────────
@router.post("/lampiran")
async def unggah_lampiran(request: Request, berkas: UploadFile = File(...)):
    """Unggah SATU berkas untuk dilampirkan di pesan berikutnya (belum dikirim ke AI sampai pesannya dikirim)."""
    user = await require_auth(request)
    try:
        await _wajib_aktif(user)
        data = await berkas.read(lmp.MAKS_UKURAN + 1)
    finally:
        await berkas.close()
    try:
        doc = await lmp.unggah(get_db(), user, berkas.filename or "", data)
    except lmp.GalatLampiran as e:
        raise HTTPException(e.status, e.pesan) from None
    return lmp.publik(doc)


@router.delete("/lampiran/{lampiran_id}")
async def hapus_lampiran(lampiran_id: str, request: Request):
    user = await require_auth(request)
    try:
        await lmp.hapus(get_db(), user["id"], lampiran_id, klien=await mesin.klien_berkas())
    except lmp.GalatLampiran as e:
        raise HTTPException(e.status, e.pesan) from None
    return {"ok": True}


# ── Tahap B: tindakan AI (Kontrak E) ─────────────────────────────────────────
@router.post("/tindakan/{tindakan_id}/putuskan")
async def putuskan_tindakan(tindakan_id: str, request: Request):
    """Setujui / Batal satu kartu → aliran SSE (`tindakan_status`, lalu jawaban lanjutan bila lengkap)."""
    user = await require_auth(request)
    body = await _body(request)
    keputusan = str(body.get("keputusan") or "").strip().lower()
    if keputusan not in ("setujui", "batal"):
        raise HTTPException(400, "Keputusan harus setujui atau batal.")
    cv = body.get("cv")
    if cv is not None:
        cv = str(cv).strip().upper()
        if cv not in CV_SAH:
            raise HTTPException(400, "Pilihan CV harus DA, SMU, atau ALL.")
    ubahan = body.get("ubahan")
    if ubahan is not None and not isinstance(ubahan, dict):
        raise HTTPException(400, "Isian perubahan di kartu tidak sah.")
    alasan = body.get("alasan")
    if alasan is not None and not isinstance(alasan, str):
        raise HTTPException(400, "Alasan harus berupa teks.")
    # 12 Nov 2026 (K4): risiko tinggi — teks ketik ulang (nominal / nomor dokumen) sesuai petunjuk kartu.
    konfirmasi = body.get("konfirmasi")
    if konfirmasi is not None and not isinstance(konfirmasi, (str, int)):
        raise HTTPException(400, "Teks konfirmasi harus berupa teks.")
    # Asisten AI per pengguna (10 Nov 2026): akun dimatikan tidak bisa MENYETUJUI kartu; membatalkan tetap boleh.
    aturan = await akp.aturan(get_db(), user)
    if keputusan == "setujui" and not aturan["aktif"]:
        raise HTTPException(403, akp.PESAN_SETUJUI_NONAKTIF)
    try:
        jalan = await mesin.siapkan_putusan(db=get_db(), user=user, tindakan_id=tindakan_id, keputusan=keputusan,
                                            ubahan=ubahan, alasan=alasan or "", cv=cv, today=today_wib(),
                                            token=_token(request), app=request.app,
                                            batas_tindakan=aturan["batas_tindakan"], konfirmasi=konfirmasi)
    except tdk.GalatTindakan as e:
        raise _galat_http(e) from None
    mesin.mulai(jalan)
    return StreamingResponse(mesin.aliran_sse(jalan, request), media_type="text/event-stream",
                             headers=_SSE_HEADERS)


@router.post("/tindakan/{tindakan_id}/putuskan-kedua")
async def putuskan_kedua_tindakan(tindakan_id: str, request: Request):
    """Persetujuan kedua kartu uang (12 Nov 2026, K4): owner/superadmin, bukan pembuat kartu.
    Body {keputusan: setujui|batal, alasan}. Setujui → dijalankan sebagai PEMBUAT kartu; respons JSON biasa."""
    user = await require_auth(request)
    body = await _body(request)
    keputusan = str(body.get("keputusan") or "").strip().lower()
    alasan = body.get("alasan")
    if alasan is not None and not isinstance(alasan, str):
        raise HTTPException(400, "Alasan harus berupa teks.")
    try:
        return await tdk.putuskan_kedua(get_db(), user, tindakan_id, keputusan=keputusan, alasan=alasan or "",
                                        app=request.app)
    except tdk.GalatTindakan as e:
        raise _galat_http(e) from None


@router.get("/tindakan")
async def daftar_tindakan(request: Request, status: Optional[str] = None, dari: Optional[str] = None,
                          sampai: Optional[str] = None, halaman: int = 1, semua: Optional[str] = None):
    user = await require_auth(request)
    try:
        return await tdk.daftar(get_db(), user, status=status, dari=dari, sampai=sampai, halaman=halaman,
                                semua=str(semua or "").strip().lower() in ("1", "true", "ya"))
    except tdk.GalatTindakan as e:
        raise _galat_http(e) from None


@router.get("/tindakan/{tindakan_id}")
async def detail_tindakan(tindakan_id: str, request: Request):
    user = await require_auth(request)
    try:
        return await tdk.detail(get_db(), user, tindakan_id)
    except tdk.GalatTindakan as e:
        raise _galat_http(e) from None


@router.post("/tindakan/{tindakan_id}/balikkan")
async def balikkan_tindakan(tindakan_id: str, request: Request):
    user = await require_auth(request)
    body = await _body(request)
    alasan = body.get("alasan")
    if alasan is not None and not isinstance(alasan, str):
        raise HTTPException(400, "Alasan harus berupa teks.")
    try:
        return await tdk.balikkan(get_db(), user, tindakan_id, alasan=alasan or "", token=_token(request),
                                  app=request.app)
    except tdk.GalatTindakan as e:
        raise _galat_http(e) from None


# ── Tahap D: ingatan AI (D1) — hanya milik sendiri ───────────────────────────
def _galat_ingatan(e: "ing.GalatIngatan") -> HTTPException:
    return HTTPException(e.status, e.pesan)


@router.get("/ingatan")
async def daftar_ingatan(request: Request):
    user = await require_auth(request)
    rows = await ing.daftar(get_db(), user["id"])
    items = [ing.publik(r) for r in rows]
    return {"items": items, "total": len(items), "aktif": sum(1 for x in items if x["aktif"]),
            "batas_aktif": ing.MAKS_AKTIF, "maks_isi": ing.MAKS_ISI,
            "kategori": [{"nilai": k, "label": ing.LABEL_KATEGORI[k]} for k in ing.KATEGORI],
            "ingatan_aktif": await ing.aktif()}


@router.post("/ingatan")
async def tambah_ingatan(request: Request):
    user = await require_auth(request)
    body = await _body(request)
    try:
        doc, baru = await ing.simpan(get_db(), user["id"], body.get("isi"), body.get("kategori"), sumber="manual")
    except ing.GalatIngatan as e:
        raise _galat_ingatan(e) from None
    return {**ing.publik(doc), "sudah_ada": not baru}


@router.patch("/ingatan/{ingatan_id}")
async def ubah_ingatan(ingatan_id: str, request: Request):
    user = await require_auth(request)
    body = await _body(request)
    try:
        doc = await ing.ubah(get_db(), user["id"], ingatan_id, isi=body.get("isi"), kategori=body.get("kategori"),
                             aktif_=body.get("aktif"))
    except ing.GalatIngatan as e:
        raise _galat_ingatan(e) from None
    return ing.publik(doc)


@router.delete("/ingatan/{ingatan_id}")
async def hapus_ingatan(ingatan_id: str, request: Request):
    user = await require_auth(request)
    try:
        await ing.hapus(get_db(), user["id"], ingatan_id)
    except ing.GalatIngatan as e:
        raise _galat_ingatan(e) from None
    return {"ok": True}


# ── Tahap D: Asisten AI proaktif (D2) — owner/superadmin ─────────────────────
def _boleh_proaktif(user: dict) -> None:
    if str(user.get("role") or "").lower() not in proaktif.PERAN_PEMICU:
        raise HTTPException(403, "Hanya owner atau superadmin yang boleh membuka pengaturan Asisten AI proaktif.")


@router.get("/proaktif")
async def ringkasan_proaktif(request: Request):
    user = await require_auth(request)
    _boleh_proaktif(user)
    return await proaktif.ringkasan(get_db())


@router.post("/proaktif/{jenis}/jalankan-sekarang")
async def jalankan_proaktif(jenis: str, request: Request):
    """Jalankan briefing / peringatan / laporan mingguan SEKARANG. Briefing & laporan dibuat untuk pemicu sendiri
    di latar (jawaban 202 berisi id sesi); peringatan dijalankan langsung (200 berisi hasil per kondisi)."""
    user = await require_auth(request)
    _boleh_proaktif(user)
    try:
        out = await proaktif.jalankan_sekarang(get_db(), user, jenis, app=request.app)
    except proaktif.GalatProaktif as e:
        raise HTTPException(e.status, e.pesan) from None
    return JSONResponse(out, status_code=202 if out.get("status") == "berjalan" else 200)
