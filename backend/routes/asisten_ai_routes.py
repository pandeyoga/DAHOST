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
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from auth import require_auth
from core.asisten_ai import ingatan as ing
from core.asisten_ai import lampiran as lmp
from core.asisten_ai import mesin, proaktif, saran, simpan
from core.asisten_ai import tindakan as tdk
from database import get_db
from routes.shared import require_portal_dep
from utils.waktu import today_wib

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/asisten-ai", tags=["asisten-ai"],
                   dependencies=[Depends(require_portal_dep("management"))])

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


@router.get("/status")
async def status(request: Request):
    user = await require_auth(request)
    out = await mesin.status_siap()
    try:
        out["tindakan_hari_ini"] = await tdk.jumlah_hari_ini(get_db(), user["id"])
    except Exception:  # noqa: BLE001 — status tetap tampil walau hitungan gagal
        out["tindakan_hari_ini"] = None
    return out


@router.get("/saran")
async def daftar_saran(request: Request, peran: Optional[str] = None):
    user = await require_auth(request)
    return saran.saran_untuk(peran or user.get("role"))


@router.get("/sessions")
async def daftar_sesi(request: Request):
    user = await require_auth(request)
    db = get_db()
    rows = await simpan.daftar_sesi(db, user["id"])
    menunggu = await tdk.sesi_menunggu(db, user["id"])
    for r in rows:
        r["ada_tindakan_menunggu"] = r["id"] in menunggu
    return rows


@router.post("/sessions")
async def buat_sesi(request: Request):
    user = await require_auth(request)
    body = await _body(request)
    return await simpan.buat_sesi(get_db(), user["id"], body.get("judul"))


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
    try:
        lampiran = await lmp.periksa_untuk_pesan(db, user["id"], body.get("lampiran"))
    except lmp.GalatLampiran as e:
        raise HTTPException(e.status, e.pesan) from None

    jalan, galat = await mesin.siapkan_jalan(db=db, user=user, sesi=sesi, teks=teks, cv=cv, periode=periode,
                                             today=today, token=_token(request), app=request.app,
                                             lampiran=lampiran)
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
    try:
        jalan = await mesin.siapkan_putusan(db=get_db(), user=user, tindakan_id=tindakan_id, keputusan=keputusan,
                                            ubahan=ubahan, alasan=alasan or "", cv=cv, today=today_wib(),
                                            token=_token(request), app=request.app)
    except tdk.GalatTindakan as e:
        raise _galat_http(e) from None
    mesin.mulai(jalan)
    return StreamingResponse(mesin.aliran_sse(jalan, request), media_type="text/event-stream",
                             headers=_SSE_HEADERS)


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
