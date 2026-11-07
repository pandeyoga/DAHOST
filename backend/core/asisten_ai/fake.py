"""Klien Anthropic TIRUAN untuk Asisten AI (Kontrak C) — uji & lokal, TANPA API sungguhan.

Aktif bila env `ASISTEN_AI_FAKE=1`. Meniru bentuk event streaming SDK `anthropic` 2.3.0 yang
dibaca loop (`client.beta.messages.stream(...)`): `message_start`, `content_block_start`,
`content_block_delta` (text/thinking/signature/input_json/citations), `content_block_stop`,
`message_delta`, `message_stop`, ditambah event bantu SDK (`text`, `thinking`, `input_json`,
`signature`, `citation`) yang harus DIABAIKAN loop. `get_final_message()` dan
`current_message_snapshot` sama seperti SDK; blok punya `.to_dict()`.

Skrip dipilih dari kata kunci pertanyaan pengguna:
  "omzet"   → `ringkasan_penjualan` (bila terpasang; bila tidak, dilewati dan dikatakan) →
              `tampilkan_grafik` → teks
  "laporan" → `buat_laporan` (bila terpasang; bila tidak, dikatakan) → teks
  "web"     → blok web_search + hasil 2 sumber + teks bersitasi
  lainnya   → teks markdown + `tampilkan_tabel` → teks penutup
Kata kunci uji tambahan: "putaran" (selalu memanggil alat), "tolak" (refusal), "panjang"
(max_tokens lalu lanjut), "panjang2" (selalu max_tokens), "jeda" (pause_turn), "lambat" (aliran
lambat, untuk uji tombol Hentikan).

Tiruan ini juga memeriksa aturan API yang penting bagi loop: tool_choice paksa ditolak, thinking
harus adaptive, tidak boleh prefill asisten, setiap tool_use wajib dibalas tool_result pada pesan
berikutnya, dan tanda tangan blok thinking yang diputar ulang harus utuh (riwayat append-only).
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import uuid
from typing import Any, Callable, Optional

MODEL_TIRUAN = "claude-opus-5-5"


def aktif() -> bool:
    return str(os.environ.get("ASISTEN_AI_FAKE", "")).strip().lower() in ("1", "true", "ya", "yes", "on")


class FakeAPIError(Exception):
    """Galat API tiruan (bentuk mirip `anthropic.APIStatusError`: punya `status_code`, `message`)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ── Objek atribut ala model SDK ──────────────────────────────────────────────
class _O:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def to_dict(self, mode: str = "python", **_kw) -> dict:
        return _ke_dict(self.__dict__)

    def model_dump(self, **_kw) -> dict:
        return _ke_dict(self.__dict__)

    def __repr__(self) -> str:  # pragma: no cover
        return f"_O({self.__dict__!r})"


def _ke_dict(v):
    if isinstance(v, _O):
        return {k: _ke_dict(x) for k, x in v.__dict__.items()}
    if isinstance(v, dict):
        return {k: _ke_dict(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_ke_dict(x) for x in v]
    return v


def _ke_obj(v):
    if isinstance(v, dict):
        return _O(**{k: _ke_obj(x) for k, x in v.items()})
    if isinstance(v, list):
        return [_ke_obj(x) for x in v]
    return v


def tanda_tangan(teks: str) -> str:
    return "fake-sig-" + hashlib.sha256((teks or "").encode("utf-8")).hexdigest()[:24]


def _bid(awalan: str) -> str:
    return f"{awalan}_{uuid.uuid4().hex[:20]}"


def _potong(teks: str, n: int = 14) -> list[str]:
    return [teks[i:i + n] for i in range(0, len(teks), n)] or [""]


# ── Pemeriksaan permintaan (meniru 400 API) ──────────────────────────────────
def _periksa_permintaan(kw: dict) -> None:
    tc = kw.get("tool_choice")
    if isinstance(tc, dict) and tc.get("type") in ("any", "tool"):
        raise FakeAPIError(400, 'tool_choice: type "tool" and "any" are not supported for this model.')
    th = kw.get("thinking")
    if th is not None and (not isinstance(th, dict) or th.get("type") != "adaptive"):
        raise FakeAPIError(400, '"thinking.type" must be "adaptive" for this model.')
    if "temperature" in kw or "top_p" in kw or "top_k" in kw:
        raise FakeAPIError(400, "sampling parameters are not supported for this model.")
    msgs = kw.get("messages") or []
    if not msgs or msgs[0].get("role") != "user":
        raise FakeAPIError(400, "messages: first message must use the \"user\" role")
    last = msgs[-1]
    if last.get("role") == "assistant":
        blocks = last.get("content") if isinstance(last.get("content"), list) else []
        if not blocks or blocks[-1].get("type") != "server_tool_use":
            raise FakeAPIError(400, "This model does not support assistant message prefill.")
    for i, m in enumerate(msgs):
        c = m.get("content")
        if not isinstance(c, list):
            continue
        if m.get("role") == "assistant":
            for b in c:
                if b.get("type") == "thinking" and b.get("signature") != tanda_tangan(b.get("thinking", "")):
                    raise FakeAPIError(400, f"messages.{i}.content: Invalid `signature` in `thinking` block.")
            ids = [b.get("id") for b in c if b.get("type") == "tool_use"]
            if ids and i + 1 < len(msgs):
                nxt = msgs[i + 1]
                got = {b.get("tool_use_id") for b in (nxt.get("content") or []) if isinstance(b, dict)
                       and b.get("type") == "tool_result"} if nxt.get("role") == "user" else set()
                hilang = [x for x in ids if x not in got]
                if hilang:
                    raise FakeAPIError(400, f"messages.{i + 1}: tool_use ids without tool_result: {hilang}")


# ── Keadaan percakapan untuk skrip ───────────────────────────────────────────
def _teks_pertanyaan(msg: dict) -> Optional[str]:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    teks = [b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text"
            and not str(b.get("text", "")).lstrip().startswith("<konteks_sistem>")]
    return " ".join(teks) if teks else None


class Keadaan:
    def __init__(self, kw: dict):
        msgs = kw.get("messages") or []
        self.kw = kw
        self.tools = {t["name"]: t.get("input_schema") or {} for t in (kw.get("tools") or [])
                      if "input_schema" in t}
        self.tool_choice = (kw.get("tool_choice") or {}).get("type")
        self.idx = 0
        self.pertanyaan = ""
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("role") == "user":
                t = _teks_pertanyaan(msgs[i])
                if t is not None:
                    self.idx, self.pertanyaan = i, t
                    break
        sesudah = msgs[self.idx + 1:]
        self.giliran_asisten = sum(1 for m in sesudah if m.get("role") == "assistant")
        self.peran_terakhir = msgs[-1].get("role") if msgs else None
        self.periode = "2026-11"
        for b in (msgs[self.idx].get("content") if isinstance(msgs[self.idx].get("content"), list) else []):
            m = re.search(r"Periode bawaan layar:.*\((\d{4}-\d{2})\)", str(b.get("text", "")))
            if m:
                self.periode = m.group(1)
        # alat yang sudah dipanggil sejak pertanyaan: [(nama, input, isi_hasil, is_error)]
        self.dipanggil: list[tuple] = []
        hasil = {}
        for m in sesudah:
            if m.get("role") == "user" and isinstance(m.get("content"), list):
                for b in m["content"]:
                    if b.get("type") == "tool_result":
                        hasil[b.get("tool_use_id")] = (b.get("content"), bool(b.get("is_error")))
        for m in sesudah:
            if m.get("role") == "assistant" and isinstance(m.get("content"), list):
                for b in m["content"]:
                    if b.get("type") == "tool_use":
                        isi, err = hasil.get(b.get("id"), (None, False))
                        self.dipanggil.append((b.get("name"), b.get("input"), isi, err))

    def sudah(self, nama: str) -> bool:
        return any(d[0] == nama for d in self.dipanggil)

    def terakhir(self, nama: str):
        for d in reversed(self.dipanggil):
            if d[0] == nama:
                return d
        return None


def _isi_contoh(schema: dict, periode: str) -> dict:
    """Isian contoh yang memenuhi `required` skema alat (untuk alat milik agen lain)."""
    out = {}
    props = (schema or {}).get("properties") or {}
    for k in (schema or {}).get("required") or []:
        p = props.get(k) or {}
        t = p.get("type")
        t = t[0] if isinstance(t, list) else t
        if "enum" in p:
            out[k] = p["enum"][0]
        elif k in ("periode", "bulan") or "periode" in k:
            out[k] = periode
        elif t == "integer":
            out[k] = max(1, int(p.get("minimum", 1)))
        elif t == "number":
            out[k] = float(p.get("minimum", 1))
        elif t == "boolean":
            out[k] = False
        elif t == "array":
            out[k] = []
        elif t == "object":
            out[k] = {}
        elif k in ("judul", "title"):
            out[k] = f"Laporan bulanan {periode}"
        else:
            out[k] = "ringkasan"
    return out


def _laporan_contoh(periode: str) -> dict:
    """Spesifikasi laporan contoh yang SAH untuk `buat_laporan` (PDF + Excel: teks, tabel, grafik)."""
    return {
        "judul": f"Laporan omzet {periode} (mode uji)",
        "periode_label": periode,
        "format": ["pdf", "xlsx"],
        "bagian": [
            {"judul": "Ringkasan", "teks": "Laporan **contoh mode uji**. Angka di bawah bukan analisis sungguhan.\n\n"
                                          "- Omzet dihitung dari pesanan yang sudah dibayar\n- Retur dilaporkan terpisah"},
            {"judul": "Omzet per toko", "tabel": {"kolom": ["Toko", "Omzet", "Pesanan"],
                                                  "baris": [["Toko A", 142300000, 512], ["Toko B", 98500000, 377],
                                                            ["Toko C", 61200000, 240]],
                                                  "satuan": ["", "Rp", ""]}},
            {"judul": "Grafik omzet", "grafik": {k: v for k, v in _GRAFIK_CONTOH.items()}},
        ],
    }


_GRAFIK_CONTOH = {"jenis": "batang", "judul": "Omzet per toko (contoh mode uji)", "satuan": "Rp",
                  "x": ["Toko A", "Toko B", "Toko C"],
                  "seri": [{"nama": "Omzet", "nilai": [142300000, 98500000, 61200000]}],
                  "catatan": "Angka contoh mode uji, bukan data asli."}


def _grafik_dari_hasil(isi: Any) -> Optional[dict]:
    """Coba bentuk grafik dari hasil alat: daftar objek dengan satu label teks + satu angka."""
    try:
        data = json.loads(isi) if isinstance(isi, str) else isi
    except (TypeError, ValueError):
        return None
    kandidat = []

    def _cari(v, kedalaman=0):
        if kedalaman > 4:
            return
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            kandidat.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                _cari(x, kedalaman + 1)
    _cari(data)
    for rows in kandidat:
        x, nilai = [], []
        for r in rows[:31]:
            lab = next((str(r[k]) for k in ("label", "nama", "name") if isinstance(r.get(k), str) and r[k].strip()),
                       None) or next((str(val) for val in r.values() if isinstance(val, str) and val.strip()), None)
            num = next((val for val in r.values() if isinstance(val, (int, float)) and not isinstance(val, bool)),
                       None)
            if lab is None or num is None:
                break
            x.append(lab[:40])
            nilai.append(num)
        else:
            if x:
                return {"jenis": "batang", "judul": "Ringkasan dari data (mode uji)", "satuan": "Rp",
                        "x": x, "seri": [{"nama": "Nilai", "nilai": nilai}]}
    return None


def _pikir(teks: str) -> dict:
    return {"type": "thinking", "thinking": teks, "signature": tanda_tangan(teks)}


def _teks(teks: str, citations=None) -> dict:
    return {"type": "text", "text": teks, "citations": citations}


def _alat(nama: str, inp: dict) -> dict:
    return {"type": "tool_use", "id": _bid("toolu"), "name": nama, "input": inp, "caller": {"type": "direct"}}


def skrip_bawaan(k: Keadaan) -> tuple[list[dict], str, dict]:
    """Return (blok, stop_reason, ekstra) — ekstra: {server_tool_use, stop_details, jeda}."""
    q = (k.pertanyaan or "").lower()
    if k.tool_choice == "none":
        return [_teks("Ringkasan akhir dengan data yang sudah terkumpul (mode uji).")], "end_turn", {}
    if "putaran" in q:
        return [_pikir("Cek tanggal lagi."), _alat("tanggal_dan_periode", {})], "tool_use", {}
    if "tolak" in q:
        return ([_teks("Sebentar, saya")], "refusal",
                {"stop_details": {"type": "refusal", "category": None, "explanation": None}})
    if "panjang2" in q:
        return [_teks("Jawaban yang sangat panjang terus terpotong")], "max_tokens", {}
    if "panjang" in q:
        if k.giliran_asisten == 0:
            return [_pikir("Jawaban akan panjang."), _teks("Bagian pertama jawaban yang panjang")], "max_tokens", {}
        return [_teks(", lalu bagian lanjutannya sampai selesai (mode uji).")], "end_turn", {}
    if "jeda" in q:
        if k.peran_terakhir != "assistant":
            return ([_pikir("Cari info pasar."),
                     {"type": "server_tool_use", "id": _bid("srvtoolu"), "name": "web_search",
                      "input": {"query": "tren garmen"}, "caller": {"type": "direct"}}],
                    "pause_turn", {"server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0}})
        last = k.kw["messages"][-1]["content"][-1]
        return ([{"type": "web_search_tool_result", "tool_use_id": last["id"], "caller": {"type": "direct"},
                  "content": [{"type": "web_search_result", "url": "https://contoh.test/tren", "title": "Tren contoh",
                               "encrypted_content": "enc-tiruan-3", "page_age": None}]},
                 _teks("Setelah jeda, pencarian selesai (mode uji).")], "end_turn", {})
    if "lambat" in q:
        return ([_teks("Jawaban lambat " + "kata demi kata " * 60)], "end_turn", {"jeda": 0.05})
    if "web" in q:
        srv = _bid("srvtoolu")
        hasil = [
            {"type": "web_search_result", "url": "https://contoh.test/berita-garmen", "title": "Tren pasar garmen 2026",
             "encrypted_content": "enc-tiruan-1", "page_age": "2 hari"},
            {"type": "web_search_result", "url": "https://contoh.test/kalender-promo", "title": "Kalender promo 12.12",
             "encrypted_content": "enc-tiruan-2", "page_age": "1 minggu"},
        ]
        cit = [{"type": "web_search_result_location", "url": hasil[0]["url"], "title": hasil[0]["title"],
                "cited_text": "Permintaan pakaian muslim naik menjelang akhir tahun.", "encrypted_index": "idx-1"}]
        return ([_pikir("Perlu info luar: cari di web."),
                 {"type": "server_tool_use", "id": srv, "name": "web_search",
                  "input": {"query": q[:80] or "tren garmen"}, "caller": {"type": "direct"}},
                 {"type": "web_search_tool_result", "tool_use_id": srv, "content": hasil, "caller": {"type": "direct"}},
                 _teks("Menurut sumber web, permintaan pakaian muslim naik menjelang akhir tahun.", citations=cit),
                 _teks(" Sumber lengkap ada di bawah (mode uji).")],
                "end_turn", {"server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0}})
    if "laporan" in q:
        if "buat_laporan" not in k.tools:
            return ([_pikir("Pengguna minta laporan."),
                     _teks("*(Mode uji: alat `buat_laporan` belum terpasang di sistem ini, jadi berkas laporan belum "
                           "bisa dibuat.)*\n\nRingkasan singkat bisa saya berikan di chat bila diminta.")],
                    "end_turn", {})
        if not k.sudah("buat_laporan"):
            return ([_pikir("Siapkan laporan bulanan."), _teks("Saya siapkan laporannya."),
                     _alat("buat_laporan", _laporan_contoh(k.periode))], "tool_use", {})
        _n, _i, isi, err = k.terakhir("buat_laporan")
        return ([_teks(f"Laporan gagal dibuat: {isi}" if err else "Laporan sudah dibuat; tautan unduhan ada di bawah.")],
                "end_turn", {})
    if "omzet" in q:
        if not k.dipanggil:
            if "ringkasan_penjualan" in k.tools:
                return ([_pikir("Pengguna menanyakan omzet; ambil ringkasan penjualan untuk CV dan periode di konteks."),
                         _teks("Saya cek rekap penjualan dulu."),
                         _alat("ringkasan_penjualan", _isi_contoh(k.tools["ringkasan_penjualan"], k.periode))],
                        "tool_use", {})
            return ([_pikir("Alat penjualan tidak tersedia."),
                     _teks("*(Mode uji: alat `ringkasan_penjualan` belum terpasang di sistem ini, jadi langkah membaca "
                           "data dilewati dan grafik di bawah memakai angka contoh.)*\n\n"),
                     _alat("tampilkan_grafik", copy.deepcopy(_GRAFIK_CONTOH))], "tool_use", {})
        if not k.sudah("tampilkan_grafik"):
            d = k.terakhir("ringkasan_penjualan")
            spec = (_grafik_dari_hasil(d[2]) if d and not d[3] else None) or copy.deepcopy(_GRAFIK_CONTOH)
            return [_alat("tampilkan_grafik", spec)], "tool_use", {}
        d = k.terakhir("ringkasan_penjualan")
        if d and d[3]:
            return [_teks(f"Data penjualan belum bisa dibaca: {d[2]}")], "end_turn", {}
        return ([_teks(f"### Omzet {k.periode}\n\nGrafik di atas merangkum omzet per toko. "
                       "**Catatan:** ini jawaban mode uji, angkanya tidak dianalisis sungguhan.")], "end_turn", {})
    # bawaan: teks markdown + tabel
    if not k.sudah("tampilkan_tabel"):
        return ([_pikir("Jawab dengan contoh teks dan tabel."),
                 _teks("Berikut **contoh jawaban** mode uji:\n\n- poin pertama\n- poin kedua\n\n"),
                 _alat("tampilkan_tabel", {"judul": "Contoh tabel mode uji", "kolom": ["Toko", "Pesanan", "Omzet"],
                                           "baris": [["Toko A", 120, "Rp 142,3 jt"], ["Toko B", 85, "Rp 98,5 jt"]],
                                           "catatan": "Angka contoh, bukan data asli."})], "tool_use", {})
    return [_teks("Tabel di atas hanya contoh untuk memeriksa tampilan.")], "end_turn", {}


# ── Aliran tiruan ────────────────────────────────────────────────────────────
class _Aliran:
    def __init__(self, events: list, final, jeda: float):
        self._events = events
        self._final = final
        self._jeda = jeda
        self._snap = None
        self._i = 0

    @property
    def current_message_snapshot(self):
        assert self._snap is not None
        return self._snap

    def _akumulasi(self, ev):
        t = ev.type
        if t == "message_start":
            self._snap = _ke_obj(_ke_dict(ev.message))
        elif t == "content_block_start":
            self._snap.content.append(_ke_obj(_ke_dict(ev.content_block)))
        elif t == "content_block_delta":
            b = self._snap.content[ev.index]
            d = ev.delta
            if d.type == "text_delta":
                b.text += d.text
            elif d.type == "thinking_delta":
                b.thinking += d.thinking
            elif d.type == "signature_delta":
                b.signature = d.signature
            elif d.type == "input_json_delta":
                b._json = getattr(b, "_json", "") + d.partial_json
                try:
                    b.input = json.loads(b._json)
                except ValueError:
                    pass
            elif d.type == "citations_delta":
                b.citations = (b.citations or []) + [d.citation]
        elif t == "content_block_stop":
            b = self._snap.content[ev.index]
            b.__dict__.pop("_json", None)
        elif t == "message_delta":
            self._snap.stop_reason = ev.delta.stop_reason
            self._snap.stop_details = ev.delta.stop_details
            self._snap.usage = ev.usage

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._events):
            raise StopAsyncIteration
        ev = self._events[self._i]
        self._i += 1
        if self._jeda and ev.type in ("content_block_delta", "content_block_start"):
            await asyncio.sleep(self._jeda)
        if ev.type in ("message_start", "content_block_start", "content_block_delta", "content_block_stop",
                       "message_delta"):
            self._akumulasi(ev)
        return ev

    async def get_final_message(self):
        while self._i < len(self._events):
            await self.__anext__()
        return self._final

    async def close(self):
        self._i = len(self._events)


class _Manajer:
    def __init__(self, induk: "FakeAsyncAnthropic", kw: dict):
        self._induk = induk
        self._kw = kw
        self._aliran = None

    async def __aenter__(self):
        self._aliran = self._induk._buat_aliran(self._kw)
        return self._aliran

    async def __aexit__(self, *exc):
        if self._aliran is not None:
            await self._aliran.close()
        return False


class _Messages:
    def __init__(self, induk):
        self._induk = induk

    def stream(self, **kw):
        self._induk.panggilan.append(copy.deepcopy(kw))
        return _Manajer(self._induk, kw)


class FakeAsyncAnthropic:
    """Pengganti `anthropic.AsyncAnthropic` untuk loop Asisten AI (hanya `.beta.messages.stream`)."""

    def __init__(self, skrip: Optional[Callable[[Keadaan], tuple]] = None, jeda: Optional[float] = None):
        self.skrip = skrip or skrip_bawaan
        self.jeda = float(os.environ.get("ASISTEN_AI_FAKE_JEDA", "0.01")) if jeda is None else jeda
        self.panggilan: list[dict] = []
        self._prefix_dilihat: set[str] = set()
        self.messages = _Messages(self)
        self.beta = _O(messages=self.messages)

    def _pemakaian(self, kw: dict, blok: list, ekstra: dict) -> dict:
        prefix = json.dumps([kw.get("tools"), kw.get("system")], sort_keys=True, ensure_ascii=False)
        total = max(1, (len(prefix) + len(json.dumps(kw.get("messages"), ensure_ascii=False))) // 4)
        ada_cache = bool(kw.get("cache_control")) or "cache_control" in prefix
        h = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
        baca = tulis = 0
        if ada_cache and h in self._prefix_dilihat:
            baca, tulis = int(total * 0.8), total // 10
        elif ada_cache:
            tulis = int(total * 0.9)
            self._prefix_dilihat.add(h)
        return {"input_tokens": max(1, total - baca - tulis), "cache_creation_input_tokens": tulis,
                "cache_read_input_tokens": baca,
                "output_tokens": max(1, len(json.dumps(blok, ensure_ascii=False)) // 4),
                "server_tool_use": ekstra.get("server_tool_use")}

    def _buat_aliran(self, kw: dict) -> _Aliran:
        _periksa_permintaan(kw)
        blok, stop, ekstra = self.skrip(Keadaan(kw))
        blok = [copy.deepcopy(b) for b in blok]
        u = self._pemakaian(kw, blok, ekstra)
        mid = _bid("msg")
        mulai_usage = {"input_tokens": u["input_tokens"], "cache_creation_input_tokens": u["cache_creation_input_tokens"],
                       "cache_read_input_tokens": u["cache_read_input_tokens"], "output_tokens": 1,
                       "server_tool_use": None}
        events = [_O(type="message_start", message=_ke_obj({
            "id": mid, "type": "message", "role": "assistant", "model": MODEL_TIRUAN, "content": [],
            "stop_reason": None, "stop_sequence": None, "stop_details": None, "usage": mulai_usage}))]
        for i, b in enumerate(blok):
            t = b["type"]
            if t == "thinking":
                awal = {"type": "thinking", "thinking": "", "signature": ""}
                deltas = [{"type": "thinking_delta", "thinking": s} for s in _potong(b["thinking"], 24)]
                deltas.append({"type": "signature_delta", "signature": b["signature"]})
            elif t == "text":
                awal = {"type": "text", "text": "", "citations": None}
                deltas = [{"type": "citations_delta", "citation": c} for c in (b.get("citations") or [])]
                deltas += [{"type": "text_delta", "text": s} for s in _potong(b["text"])]
            elif t in ("tool_use", "server_tool_use"):
                awal = {**b, "input": {}}
                js = json.dumps(b.get("input") or {}, ensure_ascii=False)
                deltas = [{"type": "input_json_delta", "partial_json": s} for s in _potong(js, max(1, len(js) // 2 + 1))]
            else:
                awal, deltas = b, []
            events.append(_O(type="content_block_start", index=i, content_block=_ke_obj(copy.deepcopy(awal))))
            for d in deltas:
                events.append(_O(type="content_block_delta", index=i, delta=_ke_obj(d)))
                bantu = {"text_delta": ("text", "text"), "thinking_delta": ("thinking", "thinking"),
                         "input_json_delta": ("input_json", "partial_json"),
                         "signature_delta": ("signature", "signature"),
                         "citations_delta": ("citation", "citation")}.get(d["type"])
                if bantu:
                    events.append(_O(type=bantu[0], **{bantu[1]: _ke_obj(d[bantu[1]])}))
            events.append(_O(type="content_block_stop", index=i, content_block=_ke_obj(copy.deepcopy(b))))
        usage = _ke_obj(u)
        events.append(_O(type="message_delta",
                         delta=_ke_obj({"stop_reason": stop, "stop_sequence": None,
                                        "stop_details": ekstra.get("stop_details")}),
                         usage=usage))
        final = _ke_obj({"id": mid, "type": "message", "role": "assistant", "model": MODEL_TIRUAN,
                         "content": blok, "stop_reason": stop, "stop_sequence": None,
                         "stop_details": ekstra.get("stop_details"), "usage": u})
        events.append(_O(type="message_stop", message=final))
        jeda = ekstra.get("jeda", self.jeda)
        return _Aliran(events, final, jeda)


_KLIEN: Optional[FakeAsyncAnthropic] = None


def klien() -> FakeAsyncAnthropic:
    """Satu klien tiruan per proses (cache prefix tiruan ikut terasa antar pesan)."""
    global _KLIEN
    if _KLIEN is None:
        _KLIEN = FakeAsyncAnthropic()
    return _KLIEN
