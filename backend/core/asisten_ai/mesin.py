"""Loop agen Asisten AI (Tahap A) — Claude Opus 5.5 lewat SDK `anthropic` (beta messages stream).

Satu `Jalan` = satu jawaban asisten untuk satu pesan pengguna:

  1. riwayat mentah sesi dimuat APA ADANYA (append-only, blok thinking bertanda tangan ikut
     diputar ulang tanpa diubah) + giliran pengguna baru = [blok konteks (tanggal WIB, CV, periode,
     peran), teks pengguna]. Konteks yang berubah TIDAK masuk `system`;
  2. permintaan: `system` stabil dengan breakpoint cache + `cache_control` tingkat atas (cache
     otomatis ekor percakapan), daftar alat urut nama, thinking adaptive + ringkasan (`pikir`),
     effort `medium`, server tools web_search (≤5) & web_fetch (≤3), cadangan penolakan
     `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`; bila ditolak API → dimatikan);
  3. stop_reason diperiksa SEBELUM isi dipakai: `tool_use` → alat klien dijalankan (baca
     bersamaan) lalu hasilnya dikirim; `pause_turn` → giliran dikirim ulang tanpa pesan tambahan;
     `max_tokens` → lanjut SEKALI dengan giliran pengguna baru (bukan prefill), lalu dikatakan;
     `refusal` → pesan ramah;
  4. batas: 12 putaran alat per pesan (sesudahnya `tool_choice: none`), batas waktu keseluruhan,
     dan berhenti bila klien memutus aliran (sisa jawaban disimpan berstatus `terhenti`);
  5. setiap panggilan API = satu baris log pemakaian (token, token cache baca/tulis, pencarian web,
     biaya) lewat `ai_cost_tracker`; gerbang kunci/saklar/toggle/anggaran diperiksa sebelum setiap
     panggilan.

Event ke layar mengikuti Kontrak B (`mulai`, `status`, `pikir`, `teks`, `alat`, `grafik`, `tabel`,
`sumber`, `laporan`, `selesai`, `galat`).

Tahap B (8 Nov 2026, Kontrak D/E) — alat tindakan:
  * panggilan alat tindakan → `siapkan` (baca saja) → kartu `ai_actions` + event `tindakan`; alat baca/ui
    giliran yang sama tetap dijalankan dan hasilnya disimpan di `tunda` pesan; loop BERHENTI, pesan berstatus
    `menunggu_konfirmasi` (event `selesai` membawa `status: "menunggu_konfirmasi"`);
  * `POST /tindakan/{id}/putuskan` = `Jalan` mode putusan: klaim + `jalankan` sekali (event `tindakan_status`),
    lalu bila SEMUA kartu giliran itu sudah diputuskan → giliran pengguna berisi semua tool_result → loop
    dilanjutkan sebagai pesan asisten baru (`mulai` … `selesai`);
  * pesan baru saat kartu masih menunggu → kartu `kedaluwarsa`, tool_result-nya di DEPAN giliran pengguna baru.
  Riwayat tetap append-only; prefix `tools` + `system` tidak berubah selama saklar tindakan tidak diubah.

Tahap D (8 Nov 2026, agen proaktif):
  * ingatan: daftar ingatan aktif pengguna masuk blok <konteks_sistem> di GILIRAN PENGGUNA (sesudah blok
    konteks), hanya bila berbeda dari blok ingatan terakhir di riwayat; `system` tidak pernah berubah. Alat
    `simpan_ingatan`/`lupakan_ingatan` hanya ditawarkan bila saklar ingatan menyala dan bukan jalan otomatis;
    panggilan ke alat yang tidak ditawarkan dijawab galat tanpa dijalankan;
  * `fitur` per jalan (bawaan `asisten-ai`; briefing/laporan otomatis = `asisten-ai-proaktif`) untuk gerbang
    anggaran dan log pemakaian; `otomatis=True` menandai pesan pengguna buatan sistem (briefing).

Tahap E (9 Nov 2026, data fleksibel · lampiran · hitung dengan kode):
  * server tool `code_execution_20260120` selalu dikirim; alat baca `kode=True` boleh dipanggil dari kode
    (programmatic tool calling). `tool_use` ber-`caller.type` code_execution dijalankan dengan konteks salinan
    ber-`pemanggil="kode"` (batas hasil 2 juta karakter, bukan 15.000). Giliran yang menjawab panggilan dari kode
    berisi HANYA tool_result; batas putarannya terpisah (`MAKS_PUTARAN_KODE`); `tool_choice: none` tidak pernah
    dipakai selagi ada panggilan dari kode yang tertunda (kelebihan batas → tool_result `is_error`);
  * kontainer ruang hitung (`container` di respons) dicatat per sesi (`simpan.simpan_kontainer`) dan dikirim balik
    di setiap permintaan sesudahnya selama umurnya sah (WAJIB saat ada panggilan dari kode yang tertunda);
    kontainer ditolak API (kedaluwarsa) → permintaan diulang SEKALI tanpa kontainer (bila tidak ada yang tertunda);
  * blok hasil code execution (`code_execution_tool_result`, `bash_code_execution_tool_result`,
    `text_editor_code_execution_tool_result`) diperlakukan seperti hasil alat server lain (append-only, aturan
    fallback, pembersihan ekor riwayat) + event `alat` berlabel "Menghitung dengan kode";
  * berkas keluaran kode diunduh lewat Files API → event `berkas` + blok riwayat (core/asisten_ai/berkas_kode.py);
  * lampiran pesan (≤ 5) diklaim, diunggah ke Files API sekali, lalu masuk giliran pengguna sebagai teks ringkasan +
    blok document/image/container_upload (core/asisten_ai/lampiran.py);
  * jalur darurat (pola `_FALLBACK`): saklar proses `_KODE` + env `ASISTEN_AI_KODE_AKTIF` (bawaan "1"). Galat 400 yang
    menyebut ruang hitung (`KATA_GALAT_KODE`) saat tidak ada panggilan kode tertunda → `_KODE` mati untuk proses ini dan
    permintaan diulang SEKALI tanpa ruang hitung: alat tanpa code_execution/allowed_callers, tanpa `container`, dan
    salinan riwayat untuk permintaan itu (`tanpa_ruang_hitung`) tanpa container_upload (diganti ringkasan lampiran),
    tanpa blok code execution, tanpa `caller` kode. Selama mati: lampiran tabel/json dikirim sebagai ringkasan teks +
    catatan `pr.TEKS_KODE_MATI` di giliran pengguna (`system` tetap sama).
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from typing import Any, Optional

import ai_cost_tracker as tracker
from core.asisten_ai import alat_base as ab
from core.asisten_ai import berkas_kode as bk
from core.asisten_ai import fake as fake_mod
from core.asisten_ai import ingatan as ing
from core.asisten_ai import lampiran as lmp
from core.asisten_ai import prompt as pr
from core.asisten_ai import simpan
from core.asisten_ai import tindakan as tdk

log = logging.getLogger(__name__)

FITUR = "asisten-ai"
MODEL = "claude-opus-5-5"
NAMA_MODEL = "Claude Opus 5.5"
EFFORT = "medium"
MAX_TOKENS = int(os.environ.get("ASISTEN_AI_MAX_TOKENS", "32000"))
MAKS_PUTARAN_ALAT = 12
# Tahap E: putaran yang menjawab panggilan alat DARI KODE dihitung terpisah (satu skrip bisa memanggil berkali-kali).
MAKS_PUTARAN_KODE = int(os.environ.get("ASISTEN_AI_MAKS_PUTARAN_KODE", "40"))
MAKS_LEWAT_KODE = 3      # balasan galat sesudah batas kode sebelum loop dihentikan paksa
MAKS_JEDA = 5
BATAS_DETIK = float(os.environ.get("ASISTEN_AI_BATAS_DETIK", "300"))
BETA_FALLBACK = "server-side-fallback-2026-07-01"
MAKS_RIWAYAT_KARAKTER = 2_500_000
# Tahap E: hasil alat untuk KODE tidak masuk konteks model (tidak dihitung token) tetapi tetap ikut diputar ulang di
# riwayat → dihitung terpisah: batas seluruh muatan permintaan (di bawah batas 32 MB API) + jatah data kode per jawaban.
MAKS_MUATAN_KARAKTER = int(os.environ.get("ASISTEN_AI_MAKS_MUATAN_KARAKTER", "16000000"))
MAKS_DATA_KODE = int(os.environ.get("ASISTEN_AI_MAKS_DATA_KODE", "8000000"))
MAKS_PIKIR_BLOK = 1500
MAKS_TEKS_PENGGUNA = 4000

_FALLBACK = {"aktif": True}
# Tahap E — saklar proses ruang hitung (jalur darurat bila API menolak gabungan alat; lihat docstring modul).
_KODE = {"aktif": True}
KATA_GALAT_KODE = ("code_execution", "allowed_callers", "eager_input_streaming", "container_upload", "container",
                   "caller")
_KLIEN = {"key": None, "klien": None}
_AKTIF: dict[str, "Jalan"] = {}
_TUGAS: set = set()

KODE_GALAT = {
    "not_configured": "kunci_kosong", "sdk_missing": "ai_nonaktif", "disabled": "ai_nonaktif",
    "feature_disabled": "ai_nonaktif", "over_budget": "anggaran_habis", "auth": "kunci_ditolak",
    "rate_limited": "sibuk", "timeout": "waktu_habis", "connection": "koneksi", "bad_request": "permintaan_ditolak",
    "upstream": "layanan", "internal": "internal",
}
PESAN_GALAT = {
    "kunci_kosong": "Asisten AI belum aktif: kunci API Anthropic belum diisi admin di menu Integrasi.",
    "ai_nonaktif": "Asisten AI sedang dimatikan oleh admin.",
    "anggaran_habis": "Batas anggaran AI sudah tercapai. Coba lagi nanti atau minta admin menaikkan batas di Monitor AI.",
    "kunci_ditolak": tracker.friendly_error("auth"),
    "sibuk": tracker.friendly_error("rate_limited"),
    "waktu_habis": "Jawaban terlalu lama sehingga dihentikan. Coba pertanyaan yang lebih sempit.",
    "koneksi": tracker.friendly_error("connection"),
    "permintaan_ditolak": tracker.friendly_error("bad_request"),
    "layanan": tracker.friendly_error("upstream"),
    "sedang_berjalan": "Jawaban sebelumnya di percakapan ini masih berjalan. Tunggu sampai selesai atau hentikan dulu.",
    "terlalu_panjang": "Percakapan ini sudah terlalu panjang. Mulai percakapan baru.",
    "lampiran": "Lampiran belum bisa dikirim. Coba unggah ulang berkasnya.",
    "internal": "Terjadi kesalahan saat memproses jawaban. Silakan coba lagi.",
}

# Hasil alat server (dipasangkan dengan `server_tool_use` lewat `tool_use_id`).
JENIS_HASIL_SERVER = ("web_search_tool_result", "web_fetch_tool_result") + bk.JENIS_HASIL_KODE
_JENIS_BLOK_DIKENAL = {"text", "thinking", "redacted_thinking", "tool_use", "server_tool_use", "fallback",
                       "container_upload", *JENIS_HASIL_SERVER}


# ── Pembantu umum ────────────────────────────────────────────────────────────
def _attr(o: Any, name: str, default=None):
    if o is None:
        return default
    if isinstance(o, dict):
        return o.get(name, default)
    return getattr(o, name, default)


def _int(o: Any, name: str) -> int:
    try:
        return int(_attr(o, name, 0) or 0)
    except (TypeError, ValueError):
        return 0


def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def blok_ke_dict(b: Any) -> dict:
    """Blok konten respons → dict JSON PERSIS seperti diterima (dipakai untuk diputar ulang)."""
    if isinstance(b, dict):
        d = b
    elif hasattr(b, "to_dict"):
        try:
            d = b.to_dict(mode="json")
        except TypeError:
            d = b.to_dict()
    elif hasattr(b, "model_dump"):
        d = b.model_dump(mode="json", exclude_unset=True, by_alias=True)
    else:
        d = dict(vars(b))
    return json.loads(json.dumps(d, ensure_ascii=False, default=str))


def rapikan_fallback(konten: list[dict]) -> list[dict]:
    """Aturan gema giliran sesudah fallback di tengah keluaran (skill: model-migration › refusal):
    sebelum blok `fallback` TERAKHIR buang thinking/redacted_thinking/tool_use, server_tool_use
    tanpa hasil pasangannya, dan jenis blok yang tidak dikenal. Blok sesudahnya tetap."""
    idx = max((i for i, b in enumerate(konten) if b.get("type") == "fallback"), default=-1)
    if idx < 0:
        return konten
    sebelum = konten[:idx]
    hasil_ids = {b.get("tool_use_id") for b in sebelum if b.get("type") in JENIS_HASIL_SERVER}
    keep = []
    for b in sebelum:
        t = b.get("type")
        if t in ("thinking", "redacted_thinking", "tool_use") or t not in _JENIS_BLOK_DIKENAL:
            continue
        if t == "server_tool_use" and b.get("id") not in hasil_ids:
            continue
        keep.append(b)
    return keep + konten[idx:]


def dari_kode(b: Any) -> bool:
    """`tool_use` yang dipanggil kode di ruang hitung (programmatic tool calling), bukan langsung oleh model."""
    c = _attr(b, "caller")
    return str(_attr(c, "type") or "").startswith("code_execution")


def ukuran_riwayat(messages: list[dict]) -> tuple[int, int]:
    """(karakter yang dihitung untuk batas konteks, karakter seluruh muatan). Isi tool_result yang menjawab
    panggilan dari kode tidak dihitung ke batas konteks (tidak masuk konteks model), tetapi dihitung ke muatan."""
    total = len(json.dumps(messages, ensure_ascii=False, default=str))
    ids = {b.get("id") for m in messages if m.get("role") == "assistant" and isinstance(m.get("content"), list)
           for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use" and dari_kode(b)}
    if not ids:
        return total, total
    data = sum(len(json.dumps(b.get("content"), ensure_ascii=False, default=str))
               for m in messages if m.get("role") == "user" and isinstance(m.get("content"), list)
               for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"
               and b.get("tool_use_id") in ids)
    return total - data, total


def riwayat_terlalu_panjang(messages: list[dict]) -> bool:
    konteks, muatan = ukuran_riwayat(messages)
    return konteks > MAKS_RIWAYAT_KARAKTER or muatan > MAKS_MUATAN_KARAKTER


def _env_kode() -> bool:
    return str(os.environ.get("ASISTEN_AI_KODE_AKTIF", "1")).strip().lower() not in ("0", "false", "tidak", "no", "off")


def kode_aktif() -> bool:
    """Ruang hitung (code execution + programmatic tool calling) aktif untuk jawaban baru?"""
    return bool(_KODE["aktif"]) and _env_kode()


def file_id_container_upload(messages: list[dict]) -> list[str]:
    return [b.get("file_id") for m in messages if m.get("role") == "user" and isinstance(m.get("content"), list)
            for b in m["content"] if isinstance(b, dict) and b.get("type") == "container_upload"]


def _teks_hasil_kode(b: dict) -> str:
    if bk.galat_hasil(b):
        return "(Langkah perhitungan dengan kode sebelumnya gagal.)"
    c = b.get("content") if isinstance(b.get("content"), dict) else {}
    out = c.get("stdout") if isinstance(c.get("stdout"), str) else ""
    out = out.strip()
    if not out:
        return "(Langkah perhitungan dengan kode sebelumnya tidak dikirim ulang.)"
    return "(Keluaran perhitungan dengan kode sebelumnya: " + (out[:1500] + "…" if len(out) > 1500 else out) + ")"


def tanpa_ruang_hitung(messages: list[dict], peta: dict, *, sisip_catatan: Optional[int] = None
                       ) -> tuple[list[dict], bool]:
    """Salinan riwayat untuk SATU permintaan jalur darurat (TIDAK disimpan; riwayat tetap append-only):
    `container_upload` → teks ringkasan lampiran (`peta` = {file_id: dokumen ai_lampiran}), blok code execution →
    teks keluaran singkat, `caller` kode dibuang (panggilan jadi langsung), dan catatan `pr.TEKS_KODE_MATI` di akhir
    giliran pengguna ke-`sisip_catatan` (giliran jawaban ini). Return (pesan, ada giliran asisten yang berubah)."""
    out: list[dict] = []
    asisten_berubah = False
    for i, m in enumerate(messages):
        c = m.get("content")
        if m.get("role") == "assistant" and isinstance(c, list):
            baru, ubah = [], False
            for b in c:
                t = b.get("type") if isinstance(b, dict) else None
                if t == "server_tool_use" and b.get("name") in ab.NAMA_ALAT_KODE:
                    ubah = True
                    continue
                if t in bk.JENIS_HASIL_KODE:
                    ubah = True
                    baru.append({"type": "text", "text": _teks_hasil_kode(b)})
                    continue
                if isinstance(b, dict) and dari_kode(b):
                    b = {k: v for k, v in b.items() if k != "caller"}
                    ubah = True
                baru.append(b)
            if ubah:
                asisten_berubah = True
                if not any(x.get("type") not in ("thinking", "redacted_thinking") for x in baru):
                    baru.append({"type": "text", "text": "(Langkah perhitungan dengan kode dilewati.)"})
                m = {**m, "content": baru}
            out.append(m)
            continue
        if m.get("role") == "user" and (isinstance(c, list) or i == sisip_catatan):
            isi = c if isinstance(c, list) else [{"type": "text", "text": str(c or "")}]
            baru, ubah = [], not isinstance(c, list)
            for b in isi:
                if isinstance(b, dict) and b.get("type") == "container_upload":
                    baru.append({"type": "text", "text": lmp.teks_pengganti(peta.get(b.get("file_id")))})
                    ubah = True
                else:
                    baru.append(b)
            if i == sisip_catatan and not any(isinstance(b, dict) and b.get("text") == pr.TEKS_KODE_MATI for b in baru):
                baru.append({"type": "text", "text": pr.TEKS_KODE_MATI})
                ubah = True
            out.append({**m, "content": baru} if ubah else m)
            continue
        out.append(m)
    return out, asisten_berubah


def tanpa_thinking(messages: list[dict]) -> list[dict]:
    """Salinan riwayat tanpa blok thinking — HANYA untuk satu permintaan pemulihan (tidak disimpan)."""
    out = []
    for m in messages:
        c = m.get("content")
        if m.get("role") == "assistant" and isinstance(c, list):
            c2 = [b for b in c if b.get("type") not in ("thinking", "redacted_thinking")]
            if not c2:
                continue
            out.append({**m, "content": c2})
        else:
            out.append(m)
    return out


def baca_usage(usage: Any) -> dict:
    """Token dari `usage` (jumlah per percobaan `iterations` bila ada fallback)."""
    srv = _attr(usage, "server_tool_use")
    out = {"in": _int(usage, "input_tokens"), "out": _int(usage, "output_tokens"),
           "cache_read": _int(usage, "cache_read_input_tokens"),
           "cache_write": _int(usage, "cache_creation_input_tokens"),
           "web_search": _int(srv, "web_search_requests"), "web_fetch": _int(srv, "web_fetch_requests")}
    iters = _attr(usage, "iterations") or []
    try:
        iters = list(iters)
    except TypeError:
        iters = []
    if any(_attr(i, "type") == "fallback_message" for i in iters):
        sah = [i for i in iters if _attr(i, "type") in ("message", "fallback_message")]
        out.update({"in": sum(_int(i, "input_tokens") for i in sah),
                    "out": sum(_int(i, "output_tokens") for i in sah),
                    "cache_read": sum(_int(i, "cache_read_input_tokens") for i in sah),
                    "cache_write": sum(_int(i, "cache_creation_input_tokens") for i in sah)})
    return out


_GALAT_WEB = {
    "max_uses_exceeded": "Batas pencarian web untuk pertanyaan ini sudah tercapai.",
    "too_many_requests": "Layanan pencarian web sedang sibuk.",
    "url_not_accessible": "Halaman web tidak bisa dibuka.",
    "url_not_allowed": "Halaman web ini tidak boleh dibuka.",
    "unsupported_content_type": "Jenis halaman web ini tidak didukung.",
}


def sumber_web(b: Any) -> tuple[list[dict], Optional[str]]:
    """(daftar sumber web, pesan galat) dari blok web_search_tool_result / web_fetch_tool_result."""
    c = _attr(b, "content")
    items: list[dict] = []
    if isinstance(c, (list, tuple)):
        for r in c:
            if _attr(r, "type") == "web_search_result" and _attr(r, "url"):
                items.append({"jenis": "web", "label": str(_attr(r, "title") or _attr(r, "url"))[:160],
                              "url": str(_attr(r, "url"))})
        return items, None
    t = _attr(c, "type")
    if t == "web_fetch_result":
        url = _attr(c, "url")
        doc = _attr(c, "content")
        if url:
            items.append({"jenis": "web", "label": str(_attr(doc, "title") or url)[:160], "url": str(url)})
        return items, None
    if t and "error" in str(t):
        return [], _GALAT_WEB.get(str(_attr(c, "error_code") or ""), "Pencarian web gagal.")
    return [], None


def _kode_exception(e: Exception) -> str:
    k = tracker._classify_exception(e)
    if k == "internal":
        sc = getattr(e, "status_code", None)
        if isinstance(sc, int):
            k = ("auth" if sc in (401, 403) else "rate_limited" if sc == 429 else
                 "bad_request" if 400 <= sc < 500 else "upstream")
        elif isinstance(e, asyncio.TimeoutError):
            k = "timeout"
    return k


def _pesan_exception(e: Exception) -> str:
    return str(getattr(e, "message", None) or e or "")


# ── Klien & gerbang ──────────────────────────────────────────────────────────
def buat_klien(api_key: str):
    """Klien streaming (fake bila `ASISTEN_AI_FAKE=1`). Timeout baca 120 dtk per potongan aliran."""
    if fake_mod.aktif():
        return fake_mod.klien()
    if _KLIEN["klien"] is None or _KLIEN["key"] != api_key:
        import anthropic
        _KLIEN["klien"] = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=anthropic.Timeout(600.0, read=120.0, connect=10.0), max_retries=1)
        _KLIEN["key"] = api_key
    return _KLIEN["klien"]


def model_log() -> tuple[str, str]:
    return ("fake", MODEL) if fake_mod.aktif() else tracker.OPUS_MODEL


async def klien_berkas():
    """Klien untuk operasi Files API di luar jawaban (hapus berkas saat percakapan dihapus). None bila tanpa kunci."""
    if fake_mod.aktif():
        return fake_mod.klien()
    try:
        key, _src = await tracker.resolve_api_key(tracker.get_db())
    except Exception:  # noqa: BLE001
        log.warning("Asisten AI: kunci API tidak bisa dibaca untuk menghapus berkas", exc_info=True)
        return None
    return buat_klien(key) if key and tracker.sdk_available() else None


async def gerbang(user_id: Optional[str], *, log_blocked: bool = True, fitur: str = FITUR) -> tracker.GateResult:
    """Gerbang tracker (kunci, saklar utama, toggle fitur `asisten-ai`, anggaran). Mode uji tanpa kunci.
    `fitur` = label log/anggaran per fitur (Tahap D: `asisten-ai-proaktif`; toggle grupnya tetap `asisten-ai`)."""
    return await tracker.check_gate(fitur, user_id, model=model_log(), require_key=not fake_mod.aktif(),
                                    log_blocked=log_blocked)


def galat_dari_gerbang(g: tracker.GateResult) -> dict:
    kode = KODE_GALAT.get(g.code or "internal", "internal")
    pesan = PESAN_GALAT.get(kode) or g.message or PESAN_GALAT["internal"]
    if kode == "anggaran_habis" and g.message:
        if "bulanan" in g.message:
            pesan = "Batas anggaran AI bulan ini sudah tercapai. Minta admin menaikkan batas di Monitor AI."
        elif "fitur" in g.message:
            pesan = "Batas anggaran harian Asisten AI sudah tercapai. Coba lagi besok atau minta admin menaikkan batas."
        else:
            pesan = "Batas anggaran AI hari ini sudah tercapai. Coba lagi besok atau minta admin menaikkan batas."
    return {"kode": kode, "pesan": pesan}


async def status_siap() -> dict:
    """Isi `GET /api/asisten-ai/status` (kunci tidak pernah dikembalikan)."""
    uji = fake_mod.aktif()
    db = tracker.get_db()
    key, _src = await tracker.resolve_api_key(db)
    settings = await tracker.get_ai_settings(db)
    fitur_mati = tracker._feature_disabled(FITUR, settings.get("disabled_features"))
    ai_on = bool(settings.get("ai_enabled", True)) and not fitur_mati
    sdk = uji or tracker.sdk_available()
    try:
        snap = await tracker.budget_snapshot(db, FITUR)
    except Exception as e:  # noqa: BLE001
        log.warning("budget_snapshot gagal: %s", type(e).__name__)
        snap = {}
    habis = bool(snap) and (snap.get("sisa_hari_ini_usd", 1) <= 0 or snap.get("sisa_bulan_ini_usd", 1) <= 0
                            or snap.get("sisa_fitur_hari_ini_usd", 1) <= 0)
    alasan = None
    if not (key or uji):
        alasan = "kunci_kosong"
    elif not (sdk and ai_on):
        alasan = "ai_nonaktif"
    elif habis:
        alasan = "anggaran_habis"
    out = {"siap": alasan is None, "model": NAMA_MODEL, "kunci_terisi": bool(key), "ai_aktif": bool(sdk and ai_on),
           "mode_uji": uji, "anggaran": snap}
    if alasan:
        out["alasan"] = alasan
        out["pesan"] = PESAN_GALAT[alasan]
    # Tahap B: saklar "Tindakan AI aktif" + batas harian (Kontrak E).
    aturan = await tdk.pengaturan()
    out["tindakan_aktif"] = aturan["aktif"]
    out["batas_tindakan_harian"] = aturan["batas"]
    # Tahap D: saklar "Ingatan AI aktif" (layar menyembunyikan chip/ajakan ingatan bila mati).
    out["ingatan_aktif"] = await ing.aktif()
    # Tahap E: ruang hitung (hitung dengan kode) aktif? Mati = env ASISTEN_AI_KODE_AKTIF=0 atau ditolak API (darurat).
    out["kode_aktif"] = kode_aktif()
    return out


# ── Satu jawaban ─────────────────────────────────────────────────────────────
class Jalan:
    def __init__(self, *, db, user: dict, sesi: dict, teks: str, cv: str, periode: str, today,
                 token: Optional[str] = None, app=None, klien=None, klien_api=None, api_key: str = "",
                 peringatan: Optional[str] = None, maks_putaran: int = MAKS_PUTARAN_ALAT,
                 batas_detik: float = BATAS_DETIK, tindakan_aktif: bool = False,
                 batas_tindakan: int = tdk.BATAS_BAWAAN, putusan: Optional[tdk.Putusan] = None,
                 boleh_lanjut: bool = True, ingatan_aktif: bool = False, fitur: str = FITUR,
                 otomatis: bool = False, lampiran: Optional[list] = None,
                 maks_putaran_kode: int = MAKS_PUTARAN_KODE):
        self.db = db
        self.user = user or {}
        self.user_id = self.user.get("id")
        self.sesi = sesi
        self.sesi_id = sesi["id"]
        self.teks = pr.bersihkan_teks_pengguna(teks)
        self.cv = cv
        self.periode = periode
        self.today = today
        self.token = token
        self.app = app
        if klien is not None:
            self.klien = klien
        elif api_key or fake_mod.aktif():
            self.klien = buat_klien(api_key)
        else:
            self.klien = None    # mode putusan tanpa lanjutan (gerbang AI menolak): tidak ada panggilan API
        self.klien_api = klien_api
        self.peringatan = peringatan
        self.maks_putaran = maks_putaran
        self.batas_detik = batas_detik
        self.model_log = model_log()
        # Tahap B — alat tindakan hanya dikirim ke model bila saklar "Tindakan AI aktif" menyala.
        self.tindakan_aktif = bool(tindakan_aktif)
        self.batas_tindakan = int(batas_tindakan)
        self.putusan = putusan
        self.boleh_lanjut = bool(boleh_lanjut)
        self.tunda: Optional[dict] = None
        self.api_awal: list[dict] = []
        self.kartu_dibuat = 0
        # Tahap D — ingatan disuntikkan bila saklarnya menyala; alatnya hanya untuk percakapan biasa (bukan
        # jalan otomatis: briefing/laporan mingguan tidak menyimpan ingatan). Jalan otomatis TIDAK pernah
        # menawarkan alat tindakan (pemanggil wajib `tindakan_aktif=False`; dipaksa di sini juga).
        self.fitur = fitur or FITUR
        self.otomatis = bool(otomatis)
        if self.otomatis:
            self.tindakan_aktif = False
        self.ingatan_aktif = bool(ingatan_aktif)
        self.alat_ditahan = frozenset() if (self.ingatan_aktif and not self.otomatis) else frozenset(ing.ALAT_INGATAN)
        # Tahap E: ruang hitung bisa dimatikan (env `ASISTEN_AI_KODE_AKTIF=0`, atau ditolak API → `_KODE`).
        self.kode = kode_aktif()
        self.tools = ab.tools_untuk_api(tindakan=self.tindakan_aktif, kecuali=self.alat_ditahan, kode=self.kode)
        self.antrian: asyncio.Queue = asyncio.Queue()
        self.berhenti = False
        self.alasan_henti: Optional[str] = None
        self.selesai = False
        self.status = "berjalan"
        self.galat: Optional[dict] = None
        self.pesan_id: Optional[str] = None
        self.blok: list[dict] = []
        self._alat_blok: dict[str, dict] = {}
        self.sumber: list[dict] = []
        self.api_baru: list[dict] = []
        self.panggilan_api = 0
        self.putaran_alat = 0
        self._tanpa_thinking = False
        self._t0 = time.monotonic()
        self.ctx: Optional[ab.AlatContext] = None
        self.pemakaian = {"token_masuk": 0, "token_keluar": 0, "cache_baca": 0, "cache_tulis": 0,
                          "pencarian_web": 0, "biaya_usd": 0.0}
        # Tahap E — ruang hitung & lampiran.
        self.kontainer: Optional[str] = simpan.kontainer_sah(sesi) if self.kode else None
        self._peta_lampiran: Optional[dict] = None
        self._idx_giliran: Optional[int] = None
        self._catatan_kode_sisip = False
        self._kontainer_exp = (sesi or {}).get("container_kedaluwarsa")
        self.maks_putaran_kode = int(maks_putaran_kode)
        self.putaran_kode = 0
        self._kode_lewat = 0
        self._kode_tertunda = False
        self._berkas_dilihat: set = set()
        self._data_kode = 0
        self._berkas_gagal = False
        self.lampiran_ids = [str(x) for x in (lampiran or [])][:lmp.MAKS_LAMPIRAN_PESAN]
        self._klaim_lampiran: Optional[str] = None

    # — kendali —
    def hentikan(self, alasan: str = "putus") -> None:
        if not self.berhenti:
            self.berhenti = True
            self.alasan_henti = alasan

    def _lewat_batas(self) -> bool:
        return (time.monotonic() - self._t0) > self.batas_detik

    # — event & blok —
    def kirim(self, event: str, data: dict) -> None:
        self._catat(event, data)
        self.antrian.put_nowait((event, data))

    def _catat(self, event: str, data: dict) -> None:
        b = self.blok
        if event == "teks":
            d = str(data.get("delta") or "")
            if b and b[-1]["jenis"] == "teks":
                b[-1]["isi"] += d
            elif d:
                b.append({"jenis": "teks", "isi": d})
        elif event == "pikir":
            d = str(data.get("teks") or "")
            if b and b[-1]["jenis"] == "pikir_ringkas":
                if len(b[-1]["isi"]) < MAKS_PIKIR_BLOK:
                    b[-1]["isi"] = (b[-1]["isi"] + d)[:MAKS_PIKIR_BLOK]
            elif d:
                b.append({"jenis": "pikir_ringkas", "isi": d[:MAKS_PIKIR_BLOK]})
        elif event == "grafik":
            b.append({"jenis": "grafik", "id": data.get("id"), "spec": data.get("spec")})
        elif event == "tabel":
            b.append({"jenis": "tabel", **{k: v for k, v in data.items() if k != "jenis"}})
        elif event == "laporan":
            b.append({"jenis": "laporan", **{k: v for k, v in data.items() if k != "jenis"}})
        elif event == "tindakan":
            # Keadaan kartu di riwayat selalu dibaca ulang dari `ai_actions` saat GET sesi (Kontrak E).
            b.append({"jenis": "tindakan", **{k: v for k, v in data.items() if k != "jenis"}})
        elif event == "berkas":
            # Tahap E (Kontrak K3): berkas keluaran kode yang bisa diunduh.
            b.append({"jenis": "berkas", **{k: data.get(k) for k in ("id", "nama", "format", "ukuran_kb", "url")}})
        elif event == "ingatan":
            # Tahap D: chip "Diingat: …" / "Dilupakan: …" (keadaan saat itu; ingatan bisa diubah sesudahnya).
            b.append({"jenis": "ingatan", "id": data.get("id"), "isi": data.get("isi"),
                      "kategori": data.get("kategori"), "aksi": data.get("aksi")})
        elif event == "alat":
            aid = data.get("id")
            if data.get("keadaan") == "mulai" or aid not in self._alat_blok:
                item = {"jenis": "alat", "id": aid, "nama": data.get("nama"), "label": data.get("label"),
                        "keadaan": data.get("keadaan")}
                b.append(item)
                self._alat_blok[aid] = item
            else:
                self._alat_blok[aid]["keadaan"] = data.get("keadaan")
            if data.get("pesan"):
                self._alat_blok[aid]["pesan"] = data["pesan"]
        elif event == "sumber":
            ada = {(s.get("jenis"), s.get("label"), s.get("url")) for s in self.sumber}
            for s in data.get("item") or []:
                k = (s.get("jenis"), s.get("label"), s.get("url"))
                if k not in ada:
                    ada.add(k)
                    self.sumber.append(dict(s))

    def _emit_alat(self, event: str, data: dict) -> None:
        """Event dari handler alat (ctx.emit / `_ui_events`)."""
        if event in ("grafik", "tabel", "laporan") and not data.get("id"):
            data = {**data, "id": ab.id_pendek({"grafik": "grf", "tabel": "tbl", "laporan": "lap"}[event])}
        if event == "sumber":
            data = {"item": ab._sumber_dari(data.get("item") or [])}
        self.kirim(event, data)

    def _catatan(self, teks: str) -> None:
        ada_teks = any(x["jenis"] == "teks" and x["isi"].strip() for x in self.blok)
        self.kirim("teks", {"delta": ("\n\n" if ada_teks else "") + f"_{teks}_"})

    def _set_galat(self, kode: str, pesan: Optional[str] = None, *, status: str = "gagal") -> None:
        self.galat = {"kode": kode, "pesan": pesan or PESAN_GALAT.get(kode) or PESAN_GALAT["internal"]}
        if self.status == "berjalan":
            self.status = status
        self.blok.append({"jenis": "teks", "isi": f"_{self.galat['pesan']}_"})
        self.antrian.put_nowait(("galat", self.galat))

    # — siklus —
    async def jalankan(self) -> None:
        try:
            await self._inti()
        except asyncio.CancelledError:
            self.hentikan("dibatalkan")
            raise
        except Exception:  # noqa: BLE001
            log.exception("Asisten AI: loop gagal (sesi %s)", self.sesi_id)
            if self.galat is None:
                self._set_galat("internal")
        finally:
            try:
                await self._akhiri()
            except Exception:  # noqa: BLE001
                log.exception("Asisten AI: gagal menyimpan akhir jawaban (sesi %s)", self.sesi_id)
            self.selesai = True
            self.antrian.put_nowait(None)
            if _AKTIF.get(self.sesi_id) is self:
                _AKTIF.pop(self.sesi_id, None)

    async def _inti(self) -> None:
        kabar: list[dict] = []
        if self.putusan is not None:
            # Mode putusan: jalankan keputusan kartu, lalu lanjutkan jawaban bila giliran sudah lengkap.
            lanjut = await self._putuskan()
            if lanjut is None:
                return
            api_user, putaran = lanjut
            self.putaran_alat = min(int(putaran or 0), self.maks_putaran)
            riwayat = await simpan.muat_riwayat_api(self.db, self.user_id, self.sesi_id)
            pa = await simpan.mulai_lanjutan(self.db, self.sesi, self.user_id, api_user=api_user, cv=self.cv,
                                             periode=self.periode, lanjutan_dari=self.putusan.doc.get("pesan_id"))
            self.api_awal = [api_user]
            status_awal = "Melanjutkan jawaban…"
        else:
            riwayat = await simpan.muat_riwayat_api(self.db, self.user_id, self.sesi_id)
            if riwayat_terlalu_panjang(riwayat):
                self._set_galat("terlalu_panjang")
                return
            # Kartu yang belum diputuskan → kedaluwarsa; SEMUA tool_use terbuka dibalas di depan giliran baru.
            awal, kabar = await tdk.tutup_terbuka(self.db, self.user_id, self.sesi_id, riwayat)
            catatan = await tdk.kabar_dibalikkan(self.db, self.user_id, self.sesi_id)
            konteks = pr.konteks_giliran(today=self.today, cv=self.cv, periode=self.periode,
                                         peran=str(self.user.get("role") or ""))
            isi = list(awal) + [{"type": "text", "text": konteks}]
            if not self.kode:
                isi.append({"type": "text", "text": pr.TEKS_KODE_MATI})
            # Tahap D: ingatan pengguna = konteks yang berubah → giliran pengguna, BUKAN `system`.
            if self.ingatan_aktif:
                try:
                    blok_ing = await ing.blok_untuk_giliran(self.db, self.user_id, riwayat)
                except Exception:  # noqa: BLE001 — ingatan gagal dibaca tidak boleh menggagalkan jawaban
                    log.warning("Asisten AI: ingatan gagal dimuat (sesi %s)", self.sesi_id, exc_info=True)
                    blok_ing = None
                if blok_ing:
                    isi.append({"type": "text", "text": blok_ing})
            if catatan:
                isi.append({"type": "text", "text": catatan})
            # Tahap E: lampiran → klaim atomik + unggah ke Files API (sekali) SEBELUM pesan disimpan; gagal →
            # klaim dilepas, tidak ada pesan yang tersimpan, lampiran bisa dipakai lagi.
            lamp_docs = await self._siapkan_lampiran()
            if lamp_docs is None:
                return
            isi += lmp.blok_api(lamp_docs, kode=self.kode)
            isi.append({"type": "text", "text": self.teks})
            api_user = {"role": "user", "content": isi}
            try:
                pu, pa = await simpan.mulai_giliran(
                    self.db, self.sesi, self.user_id, teks=self.teks, api_user=api_user, cv=self.cv,
                    periode=self.periode, otomatis=self.otomatis,
                    lampiran=lmp.ringkas_pesan(lamp_docs) if lamp_docs else None)
            except BaseException:
                if self._klaim_lampiran:
                    await lmp.lepas_klaim(self.db, self.user_id, self._klaim_lampiran)
                raise
            if self._klaim_lampiran:
                await lmp.tandai_terkirim(self.db, self.user_id, self._klaim_lampiran, pesan_id=pu["id"])
            status_awal = "Menganalisis pertanyaan…"
        self.pesan_id = pa["id"]
        self.kirim("mulai", {"pesan_id": self.pesan_id})
        for ev in kabar:
            self.kirim("tindakan_status", ev)
        if self.peringatan:
            self.kirim("status", {"teks": self.peringatan.replace("⚠️", "").strip()})
        self.kirim("status", {"teks": status_awal})
        if self.putusan is not None and riwayat_terlalu_panjang(riwayat):
            self._set_galat("terlalu_panjang")
            return
        messages = list(riwayat) + [api_user]
        self._idx_giliran = len(riwayat)
        self.ctx = ab.AlatContext(user=self.user, cv=self.cv, today=self.today, token=self.token, app=self.app,
                                  emit=self._emit_alat, klien_api=self.klien_api,
                                  sesi_id=self.sesi_id, db=self.db, baca_saja=True, pesan_id=self.pesan_id)
        lanjut_max = 0
        jeda = 0
        try:
            while not self.berhenti:
                if self._lewat_batas():
                    self._set_galat("waktu_habis", status="terhenti")
                    break
                if self.panggilan_api > 0:
                    g = await gerbang(self.user_id, fitur=self.fitur)
                    if not g.ok:
                        gg = galat_dari_gerbang(g)
                        self._set_galat(gg["kode"], gg["pesan"])
                        break
                # Selagi kode di ruang hitung menunggu hasil alat, `tool_choice: none` TIDAK dipakai (kode harus
                # bisa selesai); kelebihan batas dijawab tool_result is_error.
                tool_choice = {"type": "none"} if (self.putaran_alat >= self.maks_putaran
                                                   and not self._kode_tertunda) else None
                h = await self._panggil(messages, tool_choice)
                if h is None:
                    break
                konten, stop = h
                self._kode_tertunda = any(b.get("type") == "tool_use" and dari_kode(b) for b in konten)
                turn = {"role": "assistant", "content": konten}
                if stop == "refusal":
                    # Seluruh rantai (termasuk cadangan) menolak: giliran tidak masuk riwayat.
                    self._catatan("Maaf, permintaan ini tidak bisa diproses AI karena ditolak filter keamanan. "
                                  "Coba ubah atau perjelas pertanyaannya.")
                    break
                if not konten:
                    break
                messages.append(turn)
                self.api_baru.append(turn)
                await self._berkas_dari(konten)
                if stop == "pause_turn":
                    jeda += 1
                    if jeda > MAKS_JEDA:
                        self._catatan("Pencarian web terlalu lama sehingga dihentikan.")
                        break
                    continue
                tool_uses = [b for b in konten if b.get("type") == "tool_use"]
                if stop == "max_tokens":
                    hasil = [{"type": "tool_result", "tool_use_id": b["id"], "is_error": True,
                              "content": "Isian alat terpotong karena batas panjang jawaban; alat tidak dijalankan."}
                             for b in tool_uses]
                    if self._kode_tertunda:
                        # Panggilan dari kode tertunda: balasan HANYA tool_result (tanpa teks lanjutan).
                        u = {"role": "user", "content": hasil}
                        messages.append(u)
                        self.api_baru.append(u)
                        lanjut_max += 1
                        if lanjut_max > 1:
                            self._catatan("Jawaban terpotong karena terlalu panjang. Minta bagian yang dibutuhkan "
                                          "saja, mis. per toko atau per minggu.")
                            break
                        continue
                    if lanjut_max == 0:
                        lanjut_max = 1
                        u = {"role": "user", "content": hasil + [{"type": "text", "text": pr.TEKS_LANJUTKAN}]}
                        messages.append(u)
                        self.api_baru.append(u)
                        continue
                    if hasil:
                        u = {"role": "user", "content": hasil}
                        messages.append(u)
                        self.api_baru.append(u)
                    self._catatan("Jawaban terpotong karena terlalu panjang. Minta bagian yang dibutuhkan saja, "
                                  "mis. per toko atau per minggu.")
                    break
                if stop == "tool_use" and tool_uses and self._kode_tertunda:
                    # Tahap E: kode di ruang hitung memanggil alat (programmatic tool calling). Giliran balasan
                    # berisi HANYA tool_result; batas putarannya terpisah dari batas alat langsung.
                    isi = await self._jawab_kode(tool_uses)
                    u = {"role": "user", "content": isi}
                    messages.append(u)
                    self.api_baru.append(u)
                    if self.berhenti:
                        break
                    if self._lewat_batas():
                        self._set_galat("waktu_habis", status="terhenti")
                        break
                    if self._kode_lewat > MAKS_LEWAT_KODE:
                        self._catatan("Perhitungan dengan kode dihentikan karena batas langkah tercapai.")
                        break
                    continue
                if stop == "tool_use" and tool_uses:
                    if self.putaran_alat >= self.maks_putaran:
                        u = {"role": "user", "content": [
                            {"type": "tool_result", "tool_use_id": b["id"], "is_error": True,
                             "content": "Batas langkah alat tercapai; alat tidak dijalankan."} for b in tool_uses]}
                        messages.append(u)
                        self.api_baru.append(u)
                        self._catatan("Analisis dihentikan karena batas langkah alat tercapai.")
                        break
                    self.putaran_alat += 1
                    hasil_alat = await self._jalankan_alat(tool_uses)
                    kartu = [x for x in hasil_alat if x.tindakan_id]
                    if kartu:
                        # Tahap B: berhenti menunggu keputusan. tool_result giliran ini baru dikirim setelah
                        # semua kartu diputuskan (atau di depan pesan pengguna berikutnya).
                        self.tunda = {"keadaan": "menunggu", "urutan": [b["id"] for b in tool_uses],
                                      "hasil": [x.untuk_api() for x in hasil_alat if not x.tindakan_id],
                                      "tindakan": [x.tindakan_id for x in kartu], "putaran_alat": self.putaran_alat}
                        self.status = "menunggu_konfirmasi"
                        break
                    isi = [x.untuk_api() for x in hasil_alat]
                    if self.putaran_alat >= self.maks_putaran:
                        isi.append({"type": "text", "text": pr.TEKS_BATAS_PUTARAN})
                    u = {"role": "user", "content": isi}
                    messages.append(u)
                    self.api_baru.append(u)
                    if self.berhenti:
                        break
                    if self._lewat_batas():
                        self._set_galat("waktu_habis", status="terhenti")
                        break
                    continue
                break  # end_turn / stop_sequence / lainnya
        finally:
            await self.ctx.tutup()

    def _kwargs(self, messages: list[dict], tool_choice: Optional[dict]) -> dict:
        msgs = messages
        if not self.kode:
            # Jalur darurat: salinan riwayat tanpa ruang hitung untuk permintaan ini saja.
            msgs, asisten_berubah = tanpa_ruang_hitung(
                msgs, self._peta_lampiran or {}, sisip_catatan=self._idx_giliran if self._catatan_kode_sisip else None)
            if asisten_berubah:
                msgs = tanpa_thinking(msgs)   # giliran asisten diubah → blok thinking-nya tidak sah lagi
        kw = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": copy.deepcopy(list(pr.SISTEM_API)),
            "messages": tanpa_thinking(msgs) if self._tanpa_thinking else msgs,
            "tools": self.tools,
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": EFFORT},
            "cache_control": {"type": "ephemeral"},
        }
        if tool_choice:
            kw["tool_choice"] = tool_choice
        if self.kontainer and self.kode:
            # Tahap E: ruang hitung yang sama (berkas & variabel kode tetap). WAJIB bila ada panggilan dari kode
            # yang tertunda.
            kw["container"] = self.kontainer
        if _FALLBACK["aktif"]:
            kw["betas"] = [BETA_FALLBACK]
            kw["fallbacks"] = "default"
        return kw

    async def _panggil(self, messages: list[dict], tool_choice: Optional[dict]):
        """Satu panggilan streaming. Return (konten, stop_reason) atau None (galat/berhenti)."""
        self.panggilan_api += 1
        t0 = time.monotonic()
        if not self.kode and self._peta_lampiran is None:
            await self._muat_peta_lampiran(messages)
        for percobaan in range(6):
            kw = self._kwargs(messages, tool_choice)
            try:
                final, terputus, snap = await self._stream(kw)
                break
            except Exception as e:  # noqa: BLE001
                msg = _pesan_exception(e).lower()
                kode = _kode_exception(e)
                if (kode == "bad_request" and percobaan < 5 and self.kontainer and self.kode and "container" in msg
                        and "container_upload" not in msg and not self._kode_tertunda):
                    # Kontainer kedaluwarsa tidak bisa dipakai lagi (dok resmi): ulangi tanpa `container`.
                    log.info("Asisten AI: kontainer ruang hitung ditolak API — memakai kontainer baru (sesi %s)",
                             self.sesi_id)
                    self.kontainer = None
                    self._kontainer_exp = None
                    try:
                        await simpan.lupakan_kontainer(self.db, self.user_id, self.sesi_id)
                    except Exception:  # noqa: BLE001
                        log.warning("Asisten AI: gagal melupakan kontainer (sesi %s)", self.sesi_id, exc_info=True)
                    continue
                if kode == "bad_request" and percobaan < 5:
                    if _FALLBACK["aktif"] and "fallback" in msg:
                        log.warning("Asisten AI: parameter fallbacks ditolak API — dimatikan untuk proses ini")
                        _FALLBACK["aktif"] = False
                        continue
                    if self.kode and not self._kode_tertunda and any(k in msg for k in KATA_GALAT_KODE):
                        # Jalur darurat Tahap E: ulang SEKALI tanpa ruang hitung; saklar proses ikut mati.
                        await self._matikan_kode(messages, msg)
                        continue
                    if not self._tanpa_thinking and ("signature" in msg or "different conversation" in msg):
                        log.warning("Asisten AI: blok thinking riwayat ditolak — ulang tanpa thinking (sekali)")
                        self._tanpa_thinking = True
                        continue
                log.warning("Asisten AI: panggilan gagal [%s] %s", kode, type(e).__name__)
                await self._log(None, t0, sukses=False, kode=kode, detail=f"{type(e).__name__}: {msg[:200]}")
                self._set_galat(KODE_GALAT.get(kode, "internal"))
                return None
        await self._catat_kontainer(_attr(snap if terputus else final, "container"))
        if terputus:
            await self._log(_attr(snap, "usage"), t0, sukses=False, kode="terhenti")
            if self.alasan_henti is None and self._lewat_batas():
                self._set_galat("waktu_habis", status="terhenti")
            teks = "".join(_attr(b, "text", "") or "" for b in (_attr(snap, "content") or [])
                           if _attr(b, "type") == "text").rstrip()
            if teks:
                part = {"role": "assistant", "content": [{"type": "text", "text": teks}]}
                self.api_baru.append(part)
            return None
        stop = _attr(final, "stop_reason")
        konten = rapikan_fallback([blok_ke_dict(b) for b in (_attr(final, "content") or [])])
        # Blok thinking tanpa tanda tangan (mis. terpotong max_tokens) tidak sah diputar ulang.
        konten = [b for b in konten if not (b.get("type") == "thinking" and not b.get("signature"))]
        await self._log(_attr(final, "usage"), t0, sukses=stop != "refusal", stop=stop,
                        kode="refusal" if stop == "refusal" else None)
        return konten, stop

    async def _stream(self, kw: dict):
        """Konsumsi aliran SDK; cek tombol Hentikan & batas waktu tiap 0,25 dtk."""
        async with self.klien.beta.messages.stream(**kw) as stream:
            it = stream.__aiter__()
            nxt = None
            terputus = False
            while True:
                if nxt is None:
                    nxt = asyncio.ensure_future(it.__anext__())
                done, _ = await asyncio.wait({nxt}, timeout=0.25)
                if done:
                    # Event yang sudah diterima selalu diolah dulu → teks tersimpan = teks yang tampil.
                    selesai_satu, nxt = nxt, None
                    try:
                        ev = selesai_satu.result()
                    except StopAsyncIteration:
                        break
                    self._olah_event(ev)
                if self.berhenti or self._lewat_batas():
                    if nxt is not None and not nxt.done():
                        nxt.cancel()
                        await asyncio.wait({nxt}, timeout=2.0)
                    terputus = True
                    break
            snap = None
            try:
                snap = stream.current_message_snapshot
            except Exception:  # noqa: BLE001 — belum ada message_start
                snap = None
            if terputus:
                return None, True, snap
            final = await stream.get_final_message()
            return final, False, snap

    def _olah_event(self, ev: Any) -> None:
        t = _attr(ev, "type")
        if t == "content_block_start":
            b = _attr(ev, "content_block")
            bt = _attr(b, "type")
            if bt == "server_tool_use":
                nama = str(_attr(b, "name") or "web_search")
                label = ab.label_alat(nama)
                self.kirim("status", {"teks": f"{label}…"})
                self.kirim("alat", {"id": _attr(b, "id"), "nama": nama, "label": label, "keadaan": "mulai"})
            elif bt in ("web_search_tool_result", "web_fetch_tool_result"):
                items, err = sumber_web(b)
                nama = "web_search" if bt == "web_search_tool_result" else "web_fetch"
                data = {"id": _attr(b, "tool_use_id"), "nama": nama, "label": ab.label_alat(nama),
                        "keadaan": "gagal" if err else "selesai"}
                if err:
                    data["pesan"] = err
                self.kirim("alat", data)
                if items:
                    self.kirim("sumber", {"item": items})
            elif bt in bk.JENIS_HASIL_KODE:
                err = bk.galat_hasil(b)
                nama = bk.nama_alat_hasil(bt)
                data = {"id": _attr(b, "tool_use_id"), "nama": nama, "label": ab.label_alat(nama),
                        "keadaan": "gagal" if err else "selesai"}
                if err:
                    data["pesan"] = err
                self.kirim("alat", data)
            elif bt == "fallback":
                self.kirim("status", {"teks": "Beralih ke model cadangan…"})
        elif t == "content_block_delta":
            d = _attr(ev, "delta")
            dt = _attr(d, "type")
            if dt == "text_delta":
                txt = _attr(d, "text") or ""
                if txt:
                    self.kirim("teks", {"delta": txt})
            elif dt == "thinking_delta":
                txt = _attr(d, "thinking") or ""
                if txt:
                    self.kirim("pikir", {"teks": txt})
            elif dt == "citations_delta":
                c = _attr(d, "citation")
                url = _attr(c, "url")
                if url:
                    self.kirim("sumber", {"item": [{"jenis": "web", "label": str(_attr(c, "title") or url)[:160],
                                                    "url": str(url)}]})

    async def _jalankan_alat(self, tool_uses: list[dict], *, tolak_tindakan: bool = False) -> list[ab.HasilAlat]:
        """Jalankan panggilan alat satu giliran. Tahap E: pemanggil per panggilan ("kode" bila `caller` code
        execution); `tolak_tindakan=True` (selagi kode tertunda) → alat tindakan tidak disiapkan (galat ramah)."""
        semua = [(b["id"], b.get("name") or "", b.get("input"), "kode" if dari_kode(b) else "langsung")
                 for b in tool_uses]
        # Tahap D: alat yang TIDAK ditawarkan di jalan ini (alat ingatan saat saklar mati / jalan otomatis) tidak
        # pernah dijalankan walau model memanggilnya (mis. dari riwayat lama).
        ditahan = {i: ab._gagal(tid, nama, "Alat ini tidak tersedia di percakapan ini; jawab tanpa alat ini.",
                                "Alat ini tidak tersedia di sini")
                   for i, (tid, nama, _a, _p) in enumerate(semua) if nama in self.alat_ditahan}
        for h in ditahan.values():
            self.kirim("alat", {"id": h.tool_use_id, "nama": h.nama, "label": ab.label_alat(h.nama),
                                "keadaan": "gagal", "pesan": h.pesan})
        if ditahan:
            sisa = [c for i, c in enumerate(semua) if i not in ditahan]
            hasil_sisa = iter(await self._jalankan_alat_inti(sisa, tolak_tindakan=tolak_tindakan) if sisa else [])
            return [ditahan[i] if i in ditahan else next(hasil_sisa) for i in range(len(semua))]
        return await self._jalankan_alat_inti(semua, tolak_tindakan=tolak_tindakan)

    async def _tolak_tindakan(self, tid: str, nama: str, _args: Any) -> ab.HasilAlat:
        return ab._gagal(tid, nama, "Tindakan tidak bisa disiapkan selagi perhitungan dengan kode masih berjalan. "
                                    "Selesaikan perhitungannya dulu, lalu siapkan tindakan di langkah berikutnya.",
                         "Tindakan belum bisa disiapkan")

    async def _jalankan_alat_inti(self, calls: list[tuple], *, tolak_tindakan: bool = False) -> list[ab.HasilAlat]:
        def _mulai(tid, nama):
            label = ab.label_alat(nama)
            self.kirim("status", {"teks": f"{label}…"})
            self.kirim("alat", {"id": tid, "nama": nama, "label": label, "keadaan": "mulai"})

        def _selesai(h: ab.HasilAlat):
            data = {"id": h.tool_use_id, "nama": h.nama, "label": ab.label_alat(h.nama),
                    "keadaan": "gagal" if h.is_error else "selesai"}
            if h.is_error and h.pesan:
                data["pesan"] = h.pesan
            self.kirim("alat", data)
            if h.kartu:
                self.kirim("tindakan", h.kartu)

        penangan = self._tolak_tindakan if tolak_tindakan else self._siapkan_tindakan
        task = asyncio.ensure_future(ab.jalankan_banyak(calls, self.ctx, saat_mulai=_mulai, saat_selesai=_selesai,
                                                        penangan_tindakan=penangan))
        while not task.done():
            await asyncio.wait({task}, timeout=0.25)
            if not task.done() and (self.berhenti or self._lewat_batas()):
                task.cancel()
                await asyncio.wait({task}, timeout=2.0)
                break
        if task.done() and not task.cancelled() and task.exception() is None:
            return task.result()
        return [ab.HasilAlat(tool_use_id=c[0], nama=c[1], is_error=True, pesan="Dihentikan",
                             isi="Dihentikan sebelum alat selesai.") for c in calls]

    # — Tahap E: hitung dengan kode, kontainer, berkas keluaran, lampiran —
    async def _jawab_kode(self, tool_uses: list[dict]) -> list[dict]:
        """tool_result untuk giliran yang dijeda kode di ruang hitung (HANYA tool_result, tanpa teks)."""
        self.putaran_kode += 1
        if self.putaran_kode > self.maks_putaran_kode:
            self._kode_lewat += 1
            pesan = ("Batas panggilan alat dari kode untuk pertanyaan ini sudah tercapai; alat tidak dijalankan. "
                     "Selesaikan perhitungan dengan data yang sudah ada dan sebutkan bila ada yang belum terbaca.")
            for b in tool_uses:
                self.kirim("alat", {"id": b["id"], "nama": b.get("name"), "label": ab.label_alat(b.get("name") or ""),
                                    "keadaan": "gagal", "pesan": "Batas langkah alat tercapai"})
            return [{"type": "tool_result", "tool_use_id": b["id"], "is_error": True, "content": pesan}
                    for b in tool_uses]
        hasil = await self._jalankan_alat(tool_uses, tolak_tindakan=True)
        out = []
        for b, x in zip(tool_uses, hasil):
            d = x.untuk_api()
            if dari_kode(b) and not x.is_error:
                if self._data_kode + len(x.isi) > MAKS_DATA_KODE:
                    d = {"type": "tool_result", "tool_use_id": x.tool_use_id, "is_error": True,
                         "content": "Total data yang diminta kode untuk pertanyaan ini sudah terlalu besar. Olah data "
                                    "yang sudah terbaca, atau minta data yang sudah dikelompokkan/diagregasi."}
                else:
                    self._data_kode += len(x.isi)
            out.append(d)
        return out

    async def _muat_peta_lampiran(self, messages: list[dict]) -> None:
        try:
            self._peta_lampiran = await lmp.peta_file(self.db, self.user_id, file_id_container_upload(messages))
        except Exception:  # noqa: BLE001 — tanpa peta, pengganti tetap berupa teks umum
            log.warning("Asisten AI: ringkasan lampiran gagal dimuat (sesi %s)", self.sesi_id, exc_info=True)
            self._peta_lampiran = {}

    async def _matikan_kode(self, messages: list[dict], pesan: str) -> None:
        """API menolak permintaan karena ruang hitung → matikan untuk proses ini + jawaban ini (diulang tanpa)."""
        if _KODE["aktif"]:
            _KODE["aktif"] = False
            log.warning("Asisten AI: permintaan dengan ruang hitung ditolak API (%s) — hitung dengan kode DIMATIKAN "
                        "untuk proses ini", pesan[:200])
        self.kode = False
        self.tools = ab.tools_untuk_api(tindakan=self.tindakan_aktif, kecuali=self.alat_ditahan, kode=False)
        self.kontainer = None
        self._catatan_kode_sisip = True
        await self._muat_peta_lampiran(messages)

    async def _catat_kontainer(self, c: Any) -> None:
        """Simpan kontainer ruang hitung terakhir di sesi (dikirim balik pada permintaan berikutnya)."""
        cid = _attr(c, "id")
        if not cid or not isinstance(cid, str):
            return
        exp = _attr(c, "expires_at")
        exp = exp.isoformat() if hasattr(exp, "isoformat") else (str(exp) if exp else None)
        if cid == self.kontainer and exp == self._kontainer_exp:
            return
        baru = cid != self.kontainer
        self.kontainer, self._kontainer_exp = cid, exp
        try:
            await simpan.simpan_kontainer(self.db, self.user_id, self.sesi_id, cid, exp, baru=baru)
        except Exception:  # noqa: BLE001 — gagal mencatat tidak boleh menggagalkan jawaban
            log.warning("Asisten AI: kontainer gagal dicatat (sesi %s)", self.sesi_id, exc_info=True)

    async def _berkas_dari(self, konten: list[dict]) -> None:
        """Berkas keluaran kode di giliran ini → unduh, simpan, event `berkas` (≤ MAKS_BERKAS_JAWABAN per jawaban)."""
        for fid in bk.file_id_keluaran(konten):
            if fid in self._berkas_dilihat:
                continue
            self._berkas_dilihat.add(fid)
            if len(self._berkas_dilihat) > bk.MAKS_BERKAS_JAWABAN:
                if not self._berkas_gagal:
                    self._berkas_gagal = True
                    self._catatan(f"Hanya {bk.MAKS_BERKAS_JAWABAN} berkas pertama yang disimpan untuk jawaban ini.")
                continue
            if self.klien is None or self.berhenti:
                continue
            try:
                doc = await asyncio.wait_for(
                    bk.unduh_dan_simpan(self.db, self.klien, fid, user=self.user, sesi_id=self.sesi_id,
                                        pesan_id=self.pesan_id), timeout=bk.BATAS_DETIK_UNDUH)
            except bk.GalatBerkas as e:
                self._catatan(e.pesan)
                continue
            except asyncio.TimeoutError:
                self._catatan("Berkas hasil hitung terlalu lama diambil sehingga dilewati. Minta AI membuatnya lagi.")
                continue
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Asisten AI: berkas keluaran gagal disimpan (sesi %s)", self.sesi_id)
                self._catatan("Berkas hasil hitung gagal disimpan. Minta AI membuatnya lagi.")
                continue
            self.kirim("berkas", bk.event_berkas(doc))

    async def _siapkan_lampiran(self) -> Optional[list]:
        """Klaim + unggah lampiran pesan ini. Return [] (tanpa lampiran), dokumen urut, atau None (galat dipancarkan;
        klaim sudah dilepas)."""
        if not self.lampiran_ids:
            return []
        try:
            token, docs = await lmp.klaim(self.db, self.user_id, self.lampiran_ids, self.sesi_id)
        except lmp.GalatLampiran as e:
            self._set_galat("lampiran", e.pesan)
            return None
        self._klaim_lampiran = token
        try:
            if self.klien is None:
                raise lmp.GalatLampiran(502, PESAN_GALAT["lampiran"])
            await lmp.siapkan_file(self.db, self.klien, docs, kode=self.kode)
        except lmp.GalatLampiran as e:
            await lmp.lepas_klaim(self.db, self.user_id, token)
            self._klaim_lampiran = None
            self._set_galat("lampiran", e.pesan)
            return None
        except BaseException:
            await lmp.lepas_klaim(self.db, self.user_id, token)
            self._klaim_lampiran = None
            raise
        return docs

    # — Tahap B: alat tindakan —
    async def _siapkan_tindakan(self, tid: str, nama: str, args: Any) -> ab.HasilAlat:
        """Panggilan model ke alat tindakan: `siapkan` (BACA SAJA) → kartu `menunggu`. TIDAK ada tulisan data."""
        a = ab.cari_tindakan(nama)
        if a is None:
            return ab._gagal(tid, nama, f"Alat '{nama}' belum tersedia di sistem ini.", "Alat ini belum tersedia")
        if not self.tindakan_aktif:
            return ab._gagal(tid, nama, tdk.MODEL_MATI, "Tindakan AI sedang dimatikan admin")
        if self.kartu_dibuat >= tdk.MAKS_KARTU_GILIRAN:
            return ab._gagal(tid, nama, tdk.MODEL_KARTU_BANYAK.format(n=tdk.MAKS_KARTU_GILIRAN),
                             "Terlalu banyak tindakan sekaligus")
        if await tdk.jumlah_hari_ini(self.db, self.user_id) >= self.batas_tindakan:
            return ab._gagal(tid, nama, tdk.MODEL_BATAS.format(batas=self.batas_tindakan),
                             "Batas tindakan hari ini tercapai")
        if not isinstance(args, dict):
            return ab._gagal(tid, nama, json.dumps({"INVALID_JSON": ab.serialisasi(args)}, ensure_ascii=False),
                             "Isian alat tidak sah")
        errs = ab.periksa_skema(a.input_schema, args)
        if errs:
            return ab._gagal(tid, nama, "Isian alat tidak sah: " + "; ".join(errs) + ". Perbaiki lalu coba lagi.",
                             "Isian alat tidak sah")
        kartu_id = tdk.id_baru()
        ctx = self.ctx.untuk_tindakan(kartu_id, tulis=False, alat_id=tid)
        try:
            rencana = await asyncio.wait_for(a.siapkan(ctx, copy.deepcopy(args)), timeout=ab.BATAS_DETIK_ALAT)
            rencana = tdk.rapikan_rencana(rencana, args, a)
        except ab.AlatError as e:
            return ab._gagal(tid, nama, e.pesan)
        except asyncio.TimeoutError:
            return ab._gagal(tid, nama, "Penyiapan tindakan terlalu lama dan dihentikan. Persempit perubahannya.",
                             "Penyiapan terlalu lama")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Asisten AI: siapkan tindakan %s gagal", nama)
            return ab._gagal(tid, nama, "Terjadi kesalahan saat menyiapkan tindakan ini.")
        doc = await tdk.buat(self.db, user=self.user, sesi_id=self.sesi_id, pesan_id=self.pesan_id, tool_use_id=tid,
                             alat=a, args=args, rencana=rencana, cv=self.cv, periode=self.periode,
                             tindakan_id=kartu_id)
        self.kartu_dibuat += 1
        return ab.HasilAlat(tool_use_id=tid, nama=nama, isi="", tindakan_id=doc["id"], kartu=tdk.event_kartu(doc))

    async def _putuskan(self) -> Optional[tuple[dict, int]]:
        """Mode putusan: jalankan keputusan (sudah diklaim), lalu siapkan giliran lanjutan bila lengkap."""
        p = self.putusan
        ctx = tdk.buat_ctx(user=self.user, doc=p.doc, token=self.token, app=self.app, klien_api=self.klien_api,
                           tulis=p.keputusan == "setujui", emit=self._emit_alat, today=self.today)
        try:
            await tdk.laksanakan(self.db, p, ctx, user=self.user,
                                 kirim=lambda d: self.kirim("tindakan_status", d))
        finally:
            await ctx.tutup()
        if not self.boleh_lanjut or self.berhenti:
            return None
        return await tdk.siap_lanjut(self.db, self.user_id, p.doc.get("pesan_id"))

    async def _log(self, usage: Any, t0: float, *, sukses: bool, kode: Optional[str] = None,
                   stop: Optional[str] = None, detail: Optional[str] = None) -> None:
        u = baca_usage(usage)
        biaya = tracker.calc_cost(self.model_log, u["in"], u["out"], cache_read=u["cache_read"],
                                  cache_write=u["cache_write"], web_search=u["web_search"])
        p = self.pemakaian
        p["token_masuk"] += u["in"]
        p["token_keluar"] += u["out"]
        p["cache_baca"] += u["cache_read"]
        p["cache_tulis"] += u["cache_write"]
        p["pencarian_web"] += u["web_search"]
        p["biaya_usd"] = round(p["biaya_usd"] + biaya, 6)
        err = None if sukses else (tracker.friendly_error(kode) if kode in tracker.AI_ERROR_MESSAGES else
                                   "Jawaban dihentikan." if kode == "terhenti" else None)
        await tracker.log_usage(
            self.fitur, self.user_id, self.model_log, u["in"], u["out"], biaya, (time.monotonic() - t0) * 1000,
            sukses, err, error_code=kode, error_detail=detail, stop_reason=stop,
            cache_read_tokens=u["cache_read"], cache_write_tokens=u["cache_write"],
            web_search_requests=u["web_search"], web_fetch_requests=u["web_fetch"], session_id=self.sesi_id)

    def _rapikan_riwayat_baru(self, *, jawab_terbuka: bool = True) -> None:
        """Riwayat yang disimpan harus sah untuk diputar ulang: tool_use terbuka dibalas galat,
        server_tool_use tanpa hasil (jeda yang terputus) dibuang dari ekor.
        `jawab_terbuka=False` (giliran menunggu kartu): tool_use terakhir SENGAJA dibiarkan terbuka —
        dibalas saat kartu diputuskan / pesan berikutnya."""
        a = self.api_baru
        srv, hasil = {}, set()
        for i, t in enumerate(a):
            for b in t.get("content") or []:
                if b.get("type") == "server_tool_use":
                    srv.setdefault(b.get("id"), i)
                elif b.get("type") in JENIS_HASIL_SERVER:
                    hasil.add(b.get("tool_use_id"))
        yatim = [i for sid, i in srv.items() if sid not in hasil]
        if yatim:
            del a[min(yatim):]
        if jawab_terbuka and a and a[-1].get("role") == "assistant":
            ids = [b["id"] for b in a[-1]["content"] if b.get("type") == "tool_use"]
            if ids:
                a.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": x, "is_error": True,
                     "content": "Dihentikan sebelum alat dijalankan."} for x in ids]})

    async def _akhiri(self) -> None:
        if self.pesan_id is None:
            return
        menunggu = self.status == "menunggu_konfirmasi"
        if self.status == "berjalan":
            self.status = "terhenti" if self.berhenti else "selesai"
        for b in self.blok:
            if b["jenis"] == "alat" and b.get("keadaan") == "mulai":
                b["keadaan"] = "gagal"
                b["pesan"] = "Dihentikan"
        if self.sumber:
            self.blok.append({"jenis": "sumber", "item": list(self.sumber)})
        self._rapikan_riwayat_baru(jawab_terbuka=not menunggu)
        if menunggu:
            ekor = self.api_baru[-1] if self.api_baru else {}
            ids = {b.get("id") for b in (ekor.get("content") or []) if b.get("type") == "tool_use"}
            if ekor.get("role") != "assistant" or not set(self.tunda.get("urutan") or []) <= ids:
                # Ekor giliran terpotong (sangat jarang): giliran tidak bisa ditunda dengan sah.
                log.warning("Asisten AI: giliran menunggu kartu tidak utuh (sesi %s) — kartu dikedaluwarsakan",
                            self.sesi_id)
                menunggu = False
                self.status = "selesai"
                self.tunda = None
                self._rapikan_riwayat_baru(jawab_terbuka=True)
        if not menunggu:
            # Kartu yang sempat dibuat tetapi gilirannya tidak berhenti (Hentikan/galat) → kedaluwarsa.
            await tdk.kedaluwarsakan_pesan(self.db, self.pesan_id)
        pemakaian = dict(self.pemakaian)
        await simpan.akhiri_giliran(self.db, self.user_id, self.pesan_id, blok=self.blok,
                                    api=self.api_awal + self.api_baru, status=self.status, pemakaian=pemakaian,
                                    galat=self.galat, tunda=self.tunda if menunggu else None)
        if self.status in ("selesai", "menunggu_konfirmasi"):
            data = {"pesan_id": self.pesan_id, "pemakaian": pemakaian}
            if menunggu:
                data.update({"status": "menunggu_konfirmasi", "tindakan_menunggu": list(self.tunda["tindakan"])})
            self.antrian.put_nowait(("selesai", data))


# ── Registri jalan aktif & aliran SSE ────────────────────────────────────────
def sedang_berjalan(sesi_id: str) -> bool:
    j = _AKTIF.get(sesi_id)
    return j is not None and not j.selesai


async def siapkan_jalan(*, db, user: dict, sesi: dict, teks: str, cv: str, periode: str, today,
                        token: Optional[str] = None, app=None, klien=None, klien_api=None,
                        maks_putaran: int = MAKS_PUTARAN_ALAT,
                        batas_detik: float = BATAS_DETIK, lampiran: Optional[list] = None,
                        maks_putaran_kode: int = MAKS_PUTARAN_KODE) -> tuple[Optional[Jalan], Optional[dict]]:
    """Gerbang sebelum jawaban dimulai. Return (Jalan, None) atau (None, galat {kode, pesan}).

    Bila gerbang menolak (kunci kosong, AI dimatikan, anggaran habis) tidak ada pesan yang disimpan.
    `lampiran` (Tahap E) = id lampiran yang SUDAH diperiksa rute (`lampiran.periksa_untuk_pesan`).
    """
    if sedang_berjalan(sesi["id"]):
        return None, {"kode": "sedang_berjalan", "pesan": PESAN_GALAT["sedang_berjalan"]}
    g = await gerbang(user.get("id"))
    if not g.ok:
        return None, galat_dari_gerbang(g)
    aturan = await tdk.pengaturan()
    j = Jalan(db=db, user=user, sesi=sesi, teks=teks, cv=cv, periode=periode, today=today, token=token, app=app,
              klien=klien, klien_api=klien_api, api_key=g.api_key, peringatan=g.warning,
              maks_putaran=maks_putaran, batas_detik=batas_detik, tindakan_aktif=aturan["aktif"],
              batas_tindakan=aturan["batas"], ingatan_aktif=await ing.aktif(), lampiran=lampiran,
              maks_putaran_kode=maks_putaran_kode)
    return j, None


class _Reservasi:
    """Penanda sesi sibuk selama pemeriksaan keputusan (sebelum `Jalan` putusan dimulai)."""

    selesai = False

    def hentikan(self, alasan: str = "") -> None:  # pragma: no cover — tidak ada yang dihentikan
        return None


async def siapkan_putusan(*, db, user: dict, tindakan_id: str, keputusan: str, ubahan=None, alasan: str = "",
                          cv: Optional[str] = None, today, token: Optional[str] = None, app=None, klien=None,
                          klien_api=None, batas_detik: float = BATAS_DETIK) -> Jalan:
    """Pemeriksaan + klaim keputusan kartu SEBELUM aliran dimulai. Galat → `tdk.GalatTindakan` (HTTP 4xx).

    Hanya pemilik sesi yang boleh memutuskan (orang lain, superadmin pun, mendapat 404). Return `Jalan` mode
    putusan yang tinggal di-`mulai()`: event `tindakan_status`, lalu jawaban lanjutan bila giliran lengkap."""
    doc = await tdk.ambil(db, tindakan_id)
    if not doc or doc.get("user_id") != user.get("id"):
        raise tdk.GalatTindakan(404, tdk.LAYAR_TIDAK_ADA)
    sesi = await simpan.ambil_sesi(db, user["id"], doc.get("sesi_id"))
    if not sesi:
        raise tdk.GalatTindakan(404, tdk.LAYAR_TIDAK_ADA)
    if sedang_berjalan(sesi["id"]):
        raise tdk.GalatTindakan(409, PESAN_GALAT["sedang_berjalan"])
    res = _Reservasi()
    _AKTIF[sesi["id"]] = res
    p = None
    try:
        g = await gerbang(user.get("id"), log_blocked=False)
        if keputusan == "setujui" and not g.ok:
            raise tdk.GalatTindakan(409, galat_dari_gerbang(g)["pesan"])
        aturan = await tdk.pengaturan()

        def _ctx_baca(d):
            return tdk.buat_ctx(user=user, doc=d, token=token, app=app, klien_api=klien_api, tulis=False,
                                today=today)
        p = await tdk.periksa_dan_kunci(db, user, doc, keputusan=keputusan, ubahan=ubahan, alasan=alasan,
                                        buat_ctx_baca=_ctx_baca)
        j = Jalan(db=db, user=user, sesi=sesi, teks="", cv=cv or doc.get("cv") or "DA",
                  periode=doc.get("periode") or today.strftime("%Y-%m"), today=today, token=token, app=app,
                  klien=klien, klien_api=klien_api, api_key=g.api_key if g.ok else "",
                  peringatan=g.warning if g.ok else None, batas_detik=batas_detik,
                  tindakan_aktif=aturan["aktif"], batas_tindakan=aturan["batas"], putusan=p, boleh_lanjut=g.ok,
                  ingatan_aktif=await ing.aktif())
    except BaseException:
        if p is not None:
            await tdk.lepas(db, p)
        if _AKTIF.get(sesi["id"]) is res:
            _AKTIF.pop(sesi["id"], None)
        raise
    _AKTIF[sesi["id"]] = j
    return j


def mulai(jalan: Jalan) -> asyncio.Task:
    """Jalankan di TUGAS TERPISAH (tidak ikut dibatalkan saat klien memutus aliran), sehingga
    jawaban parsial tetap tersimpan berstatus `terhenti`."""
    _AKTIF[jalan.sesi_id] = jalan
    task = asyncio.ensure_future(jalan.jalankan())
    _TUGAS.add(task)
    task.add_done_callback(_TUGAS.discard)
    return task


async def _terputus(request) -> bool:
    try:
        return bool(await request.is_disconnected())
    except Exception:  # noqa: BLE001
        return False


async def aliran_sse(jalan: Jalan, request=None):
    """Generator SSE untuk StreamingResponse. Klien memutus → `jalan.hentikan()`."""
    try:
        while True:
            try:
                item = await asyncio.wait_for(jalan.antrian.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if request is not None and await _terputus(request):
                    break
                continue
            if item is None:
                break
            yield format_sse(*item)
    finally:
        if not jalan.selesai:
            jalan.hentikan("putus")


async def aliran_galat(kode: str, pesan: str):
    yield format_sse("galat", {"kode": kode, "pesan": pesan})
