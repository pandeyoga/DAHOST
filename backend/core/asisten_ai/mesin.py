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
from core.asisten_ai import fake as fake_mod
from core.asisten_ai import ingatan as ing
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
MAKS_JEDA = 5
BATAS_DETIK = float(os.environ.get("ASISTEN_AI_BATAS_DETIK", "300"))
BETA_FALLBACK = "server-side-fallback-2026-07-01"
MAKS_RIWAYAT_KARAKTER = 2_500_000
MAKS_PIKIR_BLOK = 1500
MAKS_TEKS_PENGGUNA = 4000

_FALLBACK = {"aktif": True}
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
    "internal": "Terjadi kesalahan saat memproses jawaban. Silakan coba lagi.",
}

_JENIS_BLOK_DIKENAL = {"text", "thinking", "redacted_thinking", "tool_use", "server_tool_use",
                       "web_search_tool_result", "web_fetch_tool_result", "fallback"}


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
    hasil_ids = {b.get("tool_use_id") for b in sebelum if b.get("type") in ("web_search_tool_result",
                                                                         "web_fetch_tool_result")}
    keep = []
    for b in sebelum:
        t = b.get("type")
        if t in ("thinking", "redacted_thinking", "tool_use") or t not in _JENIS_BLOK_DIKENAL:
            continue
        if t == "server_tool_use" and b.get("id") not in hasil_ids:
            continue
        keep.append(b)
    return keep + konten[idx:]


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
    return out


# ── Satu jawaban ─────────────────────────────────────────────────────────────
class Jalan:
    def __init__(self, *, db, user: dict, sesi: dict, teks: str, cv: str, periode: str, today,
                 token: Optional[str] = None, app=None, klien=None, klien_api=None, api_key: str = "",
                 peringatan: Optional[str] = None, maks_putaran: int = MAKS_PUTARAN_ALAT,
                 batas_detik: float = BATAS_DETIK, tindakan_aktif: bool = False,
                 batas_tindakan: int = tdk.BATAS_BAWAAN, putusan: Optional[tdk.Putusan] = None,
                 boleh_lanjut: bool = True, ingatan_aktif: bool = False, fitur: str = FITUR,
                 otomatis: bool = False):
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
        self.tools = ab.tools_untuk_api(tindakan=self.tindakan_aktif, kecuali=self.alat_ditahan)
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
            if len(json.dumps(riwayat, ensure_ascii=False, default=str)) > MAKS_RIWAYAT_KARAKTER:
                self._set_galat("terlalu_panjang")
                return
            # Kartu yang belum diputuskan → kedaluwarsa; SEMUA tool_use terbuka dibalas di depan giliran baru.
            awal, kabar = await tdk.tutup_terbuka(self.db, self.user_id, self.sesi_id, riwayat)
            catatan = await tdk.kabar_dibalikkan(self.db, self.user_id, self.sesi_id)
            konteks = pr.konteks_giliran(today=self.today, cv=self.cv, periode=self.periode,
                                         peran=str(self.user.get("role") or ""))
            isi = list(awal) + [{"type": "text", "text": konteks}]
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
            isi.append({"type": "text", "text": self.teks})
            api_user = {"role": "user", "content": isi}
            _pu, pa = await simpan.mulai_giliran(self.db, self.sesi, self.user_id, teks=self.teks, api_user=api_user,
                                                 cv=self.cv, periode=self.periode, otomatis=self.otomatis)
            status_awal = "Menganalisis pertanyaan…"
        self.pesan_id = pa["id"]
        self.kirim("mulai", {"pesan_id": self.pesan_id})
        for ev in kabar:
            self.kirim("tindakan_status", ev)
        if self.peringatan:
            self.kirim("status", {"teks": self.peringatan.replace("⚠️", "").strip()})
        self.kirim("status", {"teks": status_awal})
        if self.putusan is not None and \
                len(json.dumps(riwayat, ensure_ascii=False, default=str)) > MAKS_RIWAYAT_KARAKTER:
            self._set_galat("terlalu_panjang")
            return
        messages = list(riwayat) + [api_user]
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
                tool_choice = {"type": "none"} if self.putaran_alat >= self.maks_putaran else None
                h = await self._panggil(messages, tool_choice)
                if h is None:
                    break
                konten, stop = h
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
        kw = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": copy.deepcopy(list(pr.SISTEM_API)),
            "messages": tanpa_thinking(messages) if self._tanpa_thinking else messages,
            "tools": self.tools,
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": EFFORT},
            "cache_control": {"type": "ephemeral"},
        }
        if tool_choice:
            kw["tool_choice"] = tool_choice
        if _FALLBACK["aktif"]:
            kw["betas"] = [BETA_FALLBACK]
            kw["fallbacks"] = "default"
        return kw

    async def _panggil(self, messages: list[dict], tool_choice: Optional[dict]):
        """Satu panggilan streaming. Return (konten, stop_reason) atau None (galat/berhenti)."""
        self.panggilan_api += 1
        t0 = time.monotonic()
        for percobaan in range(3):
            kw = self._kwargs(messages, tool_choice)
            try:
                final, terputus, snap = await self._stream(kw)
                break
            except Exception as e:  # noqa: BLE001
                msg = _pesan_exception(e).lower()
                kode = _kode_exception(e)
                if kode == "bad_request" and percobaan < 2:
                    if _FALLBACK["aktif"] and "fallback" in msg:
                        log.warning("Asisten AI: parameter fallbacks ditolak API — dimatikan untuk proses ini")
                        _FALLBACK["aktif"] = False
                        continue
                    if not self._tanpa_thinking and ("signature" in msg or "different conversation" in msg):
                        log.warning("Asisten AI: blok thinking riwayat ditolak — ulang tanpa thinking (sekali)")
                        self._tanpa_thinking = True
                        continue
                log.warning("Asisten AI: panggilan gagal [%s] %s", kode, type(e).__name__)
                await self._log(None, t0, sukses=False, kode=kode, detail=f"{type(e).__name__}: {msg[:200]}")
                self._set_galat(KODE_GALAT.get(kode, "internal"))
                return None
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

    async def _jalankan_alat(self, tool_uses: list[dict]) -> list[ab.HasilAlat]:
        semua = [(b["id"], b.get("name") or "", b.get("input")) for b in tool_uses]
        # Tahap D: alat yang TIDAK ditawarkan di jalan ini (alat ingatan saat saklar mati / jalan otomatis) tidak
        # pernah dijalankan walau model memanggilnya (mis. dari riwayat lama).
        ditahan = {i: ab._gagal(tid, nama, "Alat ini tidak tersedia di percakapan ini; jawab tanpa alat ini.",
                                "Alat ini tidak tersedia di sini")
                   for i, (tid, nama, _a) in enumerate(semua) if nama in self.alat_ditahan}
        for h in ditahan.values():
            self.kirim("alat", {"id": h.tool_use_id, "nama": h.nama, "label": ab.label_alat(h.nama),
                                "keadaan": "gagal", "pesan": h.pesan})
        if ditahan:
            sisa = [c for i, c in enumerate(semua) if i not in ditahan]
            hasil_sisa = iter(await self._jalankan_alat_inti(sisa) if sisa else [])
            return [ditahan[i] if i in ditahan else next(hasil_sisa) for i in range(len(semua))]
        return await self._jalankan_alat_inti(semua)

    async def _jalankan_alat_inti(self, calls: list[tuple]) -> list[ab.HasilAlat]:
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

        task = asyncio.ensure_future(ab.jalankan_banyak(calls, self.ctx, saat_mulai=_mulai, saat_selesai=_selesai,
                                                        penangan_tindakan=self._siapkan_tindakan))
        while not task.done():
            await asyncio.wait({task}, timeout=0.25)
            if not task.done() and (self.berhenti or self._lewat_batas()):
                task.cancel()
                await asyncio.wait({task}, timeout=2.0)
                break
        if task.done() and not task.cancelled() and task.exception() is None:
            return task.result()
        return [ab.HasilAlat(tool_use_id=tid, nama=nama, is_error=True, pesan="Dihentikan",
                             isi="Dihentikan sebelum alat selesai.") for tid, nama, _a in calls]

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
                elif b.get("type") in ("web_search_tool_result", "web_fetch_tool_result"):
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
                        batas_detik: float = BATAS_DETIK) -> tuple[Optional[Jalan], Optional[dict]]:
    """Gerbang sebelum jawaban dimulai. Return (Jalan, None) atau (None, galat {kode, pesan}).

    Bila gerbang menolak (kunci kosong, AI dimatikan, anggaran habis) tidak ada pesan yang disimpan.
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
              batas_tindakan=aturan["batas"], ingatan_aktif=await ing.aktif())
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
