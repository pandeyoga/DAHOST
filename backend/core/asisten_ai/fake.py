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

Tahap B (8 Nov 2026) — alat tindakan (kartu konfirmasi):
  "pengingat" → `buat_pengingat` (tindakan; milik agen operasi) bila terpasang, isian dari skemanya
  "target"    → `skenario_target` (baca; milik agen pemasaran) bila terpasang → `tampilkan_tabel` →
                `pasang_target_toko` (tindakan) dengan isian dari skenario "realistis"
  Alat yang belum terpasang dilewati dan dikatakan. Sesudah kartu diputuskan, tiruan melanjutkan dengan
  teks pendek sesuai tool_result ("Disetujui dan dijalankan" / "Dibatalkan" / "Tidak diputuskan" / "Gagal").

Tahap D (8 Nov 2026, agen proaktif):
  "briefing" / "laporan mingguan" → skrip "briefing": alat baca briefing yang terpasang SEKALIGUS (penjualan,
                target, kas, piutang, stok, PO produksi, persetujuan) → `tampilkan_grafik` → (laporan mingguan:
                `buat_laporan`) → teks ringkasan. Dicek PALING AWAL karena teks permintaan otomatis memuat kata
                kunci lain (omzet, target, laporan).
  "ingat …" / "lupakan …" → `simpan_ingatan` (isi = kalimat sesudah kata "ingat") / `lupakan_ingatan` (id dari
                daftar ingatan di blok konteks) bila alatnya ditawarkan. "pengingat"/"ingatkan" TIDAK memicu skrip ini.

Tahap E (9 Nov 2026) — hitung dengan kode + lampiran:
  "dengan kode" / "pakai kode" / "hitung kode" → skrip "kode": `server_tool_use` code_execution + DUA panggilan alat
                `kode=True` (prioritas `cari_data`) ber-`caller` code_execution_20260120 (stop tool_use, `container`
                baru) → sesudah tool_result: `code_execution_tool_result` + `bash_code_execution` dengan berkas keluaran
                (`bash_code_execution_output.file_id`, bisa diunduh lewat `files`) → teks. Tanpa alat kode: langsung
                ke bagian bash + berkas.
  giliran pertanyaan berisi blok document/image/container_upload → skrip "lampiran": teks yang menyebut lampiran.
  `klien.files` (dan `klien.beta.files`) = Files API tiruan: upload / retrieve_metadata / download / delete.
  Kontainer: id baru bila respons memakai ruang hitung; `container` di permintaan harus dikenal & belum kedaluwarsa
  (`kedaluwarsakan_kontainer`) → selain itu 400 yang menyebut "container".

Tiruan ini juga memeriksa aturan API yang penting bagi loop: tool_choice paksa ditolak, thinking
harus adaptive, tidak boleh prefill asisten, setiap tool_use wajib dibalas tool_result pada pesan
berikutnya, dan tanda tangan blok thinking yang diputar ulang harus utuh (riwayat append-only).
Tahap E: balasan untuk panggilan dari kode berisi HANYA tool_result (isi teks), wajib membawa `container` yang
sama, tanpa `tool_choice: none`; file_id lampiran harus ada di Files API tiruan; `container_upload` butuh alat
code_execution; `allowed_callers` hanya nilai yang sah.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

MODEL_TIRUAN = "claude-opus-5-5"
_BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
          "Oktober", "November", "Desember")


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
            and not str(b.get("text", "")).lstrip().startswith(("<konteks_sistem>", "<lampiran>"))]
    return " ".join(teks) if teks else None


class Keadaan:
    def __init__(self, kw: dict):
        msgs = kw.get("messages") or []
        self.kw = kw
        self.tools = {t["name"]: t.get("input_schema") or {} for t in (kw.get("tools") or [])
                      if "input_schema" in t}
        # Tahap E: alat klien yang boleh dipanggil dari kode + induk tiruan (Files API untuk berkas keluaran).
        self.alat_kode = [t["name"] for t in (kw.get("tools") or []) if "input_schema" in t
                          and CALLER_KODE in (t.get("allowed_callers") or [])]
        self.induk: Optional["FakeAsyncAnthropic"] = None
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
        isi_q = msgs[self.idx].get("content") if msgs else None
        self.lampiran = [b for b in (isi_q if isinstance(isi_q, list) else [])
                         if isinstance(b, dict) and b.get("type") in ("document", "image", "container_upload")]
        self.peran_terakhir = msgs[-1].get("role") if msgs else None
        self.periode = "2026-11"
        self.hari_ini: Optional[date] = None
        for b in (msgs[self.idx].get("content") if isinstance(msgs[self.idx].get("content"), list) else []):
            m = re.search(r"Periode bawaan layar:.*\((\d{4}-\d{2})\)", str(b.get("text", "")))
            if m:
                self.periode = m.group(1)
            h = re.search(r"Hari ini: \w+, (\d{1,2}) (\w+) (\d{4})", str(b.get("text", "")))
            if h and h.group(2) in _BULAN:
                try:
                    self.hari_ini = date(int(h.group(3)), _BULAN.index(h.group(2)) + 1, int(h.group(1)))
                except ValueError:
                    pass
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


# ── Tahap B: isian alat tindakan milik agen lain (dari skemanya) ─────────────
def _cocok(p: dict, v: str) -> bool:
    if "pattern" in p and not re.search(p["pattern"], v):
        return False
    return len(v) >= int(p.get("minLength", 0))


def _teks_contoh(nama: str, p: dict, k: "Keadaan", petunjuk: dict) -> str:
    n = nama.lower()
    besok = (k.hari_ini or date(2026, 11, 7)) + timedelta(days=1)
    calon = []
    if "periode" in n or "bulan" in n:
        calon.append(str(petunjuk.get("periode") or k.periode))
    if p.get("format") == "date-time" or any(x in n for x in ("waktu", "jam", "remind", "pada", "_at")):
        calon.append(f"{besok.isoformat()}T09:00")
    if p.get("format") == "date" or "tanggal" in n or "date" in n:
        calon.append(besok.isoformat())
    if any(x in n for x in ("judul", "title", "nama", "teks", "pesan", "isi", "catatan", "deskripsi")):
        calon.append("Pengingat dari Asisten AI (mode uji)" if "pengingat" in str(petunjuk.get("_jenis")) else
                     "Dari Asisten AI (mode uji)")
    calon += [str(petunjuk.get("periode") or k.periode), besok.isoformat(), f"{besok.isoformat()}T09:00", "09:00",
              "contoh mode uji"]
    for c in calon:
        if _cocok(p, c):
            return c[: int(p["maxLength"])] if "maxLength" in p else c
    return calon[0]


def _angka_dari(baris: dict) -> Optional[float]:
    v = baris.get("realistis")
    if isinstance(v, dict):
        v = next((x for x in v.values() if isinstance(x, (int, float)) and not isinstance(x, bool)), None)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    return next((x for x in baris.values() if isinstance(x, (int, float)) and not isinstance(x, bool)), None)


def _nilai_contoh(nama: str, p: dict, k: "Keadaan", petunjuk: dict, baris: Optional[list] = None):
    if nama in petunjuk:
        return petunjuk[nama]
    t = p.get("type")
    t = t[0] if isinstance(t, list) else t
    if "enum" in p:
        return "realistis" if "realistis" in p["enum"] else p["enum"][0]
    if "const" in p:
        return p["const"]
    if t in ("integer", "number"):
        v = max(1, p.get("minimum", 1))
        return int(v) if t == "integer" else float(v)
    if t == "boolean":
        return False
    if t == "array":
        it = p.get("items") or {}
        if it.get("type") == "object" and baris:
            return [_item_dari_baris(it, r, k) for r in baris[:10]]
        n = int(p.get("minItems", 0))
        return [_nilai_contoh(nama, it, k, petunjuk) for _ in range(n)]
    if t == "object":
        return _isi_tindakan(p, k, {}, None)
    return _teks_contoh(nama, p, k, petunjuk)


def _item_dari_baris(skema: dict, r: dict, k: "Keadaan") -> dict:
    props = skema.get("properties") or {}
    out = {}
    for q, pq in props.items():
        tq = pq.get("type")
        tq = tq[0] if isinstance(tq, list) else tq
        if q in r and not isinstance(r[q], (dict, list)):
            out[q] = r[q]
        elif "id" in q.lower():
            kid = next((x for x in r if "id" in x.lower() and isinstance(r[x], str)), None)
            if kid:
                out[q] = r[kid]
        elif tq in ("integer", "number"):
            v = _angka_dari(r)
            if v is not None:
                out[q] = int(round(v)) if tq == "integer" else v
        elif tq == "string":
            v = next((r[x] for x in ("nama", "toko", "label", "akun") if isinstance(r.get(x), str)), None)
            if v:
                out[q] = v
        if q not in out and q in (skema.get("required") or []):
            out[q] = _nilai_contoh(q, pq, k, {})
    return out


def _isi_tindakan(schema: dict, k: "Keadaan", petunjuk: Optional[dict] = None, baris: Optional[list] = None) -> dict:
    """Isian contoh yang memenuhi skema alat tindakan agen lain (wajib diisi + petunjuk dari hasil alat baca)."""
    petunjuk = petunjuk or {}
    props = (schema or {}).get("properties") or {}
    out = {}
    for nama in list((schema or {}).get("required") or []) + [n for n in petunjuk if n in props]:
        if nama not in out:
            out[nama] = _nilai_contoh(nama, props.get(nama) or {}, k, petunjuk, baris)
    return out


def _baris_skenario(isi: Any) -> tuple[list, dict]:
    """(daftar baris per toko, petunjuk {periode}) dari hasil `skenario_target`."""
    try:
        data = json.loads(isi) if isinstance(isi, str) else isi
    except (TypeError, ValueError):
        return [], {}
    petunjuk = {}
    if isinstance(data, dict):
        hasil = data.get("hasil")
        per = data.get("periode") or (hasil.get("periode") if isinstance(hasil, dict) else None)
        if isinstance(per, str):
            petunjuk["periode"] = per
    found = []

    def _cari(v, d=0):
        if d > 4 or found:
            return
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            found.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                _cari(x, d + 1)
    _cari(data)
    return (found[0] if found else []), petunjuk


_TABEL_SKENARIO_CONTOH = {
    "judul": "Skenario target per toko (contoh mode uji)", "kolom": ["Toko", "Konservatif", "Realistis", "Agresif"],
    "baris": [["Toko A", "Rp 130 jt", "Rp 145 jt", "Rp 160 jt"], ["Toko B", "Rp 90 jt", "Rp 100 jt", "Rp 112 jt"]],
    "catatan": "Angka contoh mode uji, bukan data asli."}


def _tabel_skenario(baris: list) -> Optional[dict]:
    rows = []
    for r in baris[:20]:
        nama = next((r[x] for x in ("nama", "toko", "label", "akun") if isinstance(r.get(x), str)), None)
        nilai = [r.get(s) for s in ("konservatif", "realistis", "agresif")]
        nilai = [next((x for x in v.values() if isinstance(x, (int, float))), None) if isinstance(v, dict) else v
                 for v in nilai]
        if nama and all(isinstance(v, (int, float)) for v in nilai):
            rows.append([nama[:40]] + nilai)
    if not rows:
        return None
    return {"judul": "Skenario target per toko", "kolom": ["Toko", "Konservatif", "Realistis", "Agresif"],
            "baris": rows, "catatan": "Dari alat skenario target (mode uji)."}


def _teks_sesudah_kartu(d: tuple, teks_ok: str) -> str:
    _n, _i, isi, err = d
    s = isi if isinstance(isi, str) else json.dumps(isi, ensure_ascii=False)
    s = s or ""
    if s.startswith("Disetujui dan dijalankan"):
        rinci = s.split(":", 1)[1].split("\n")[0].strip() if ":" in s else ""
        return f"{teks_ok} {rinci} *(mode uji)*".replace("  ", " ")
    if s.startswith("Dibatalkan"):
        return "Baik, tidak jadi. Tidak ada data yang diubah *(mode uji)*."
    if s.startswith("Tidak diputuskan"):
        return "Kartu tadi tidak diputuskan, jadi tidak ada yang berubah *(mode uji)*."
    if s.startswith("Gagal"):
        return f"Tindakan belum berhasil. {s} *(mode uji)*"
    if err:
        return f"Kartu belum bisa disiapkan: {s} *(mode uji)*"
    return f"Hasil tindakan: {s} *(mode uji)*"


def _skrip_pengingat(k: "Keadaan") -> tuple[list[dict], str, dict]:
    nama = "buat_pengingat"
    d = k.terakhir(nama)
    if d is not None:
        return [_teks(_teks_sesudah_kartu(d, "Pengingat sudah dibuat."))], "end_turn", {}
    if nama not in k.tools:
        return ([_pikir("Pengguna minta pengingat."),
                 _teks("*(Mode uji: alat `buat_pengingat` belum terpasang di sistem ini, jadi kartu pengingat belum "
                       "bisa disiapkan.)*\n\nPengingat bisa dibuat langsung di Portal Saya › Pengingat.")],
                "end_turn", {})
    return ([_pikir("Pengguna minta pengingat; siapkan kartu konfirmasi."),
             _teks("Saya siapkan kartu pengingatnya. Periksa isinya lalu tekan **Setujui** bila sudah sesuai."),
             _alat(nama, _isi_tindakan(k.tools[nama], k, {"_jenis": "pengingat"}))], "tool_use", {})


def _skrip_target(k: "Keadaan") -> tuple[list[dict], str, dict]:
    d = k.terakhir("pasang_target_toko")
    if d is not None:
        return [_teks(_teks_sesudah_kartu(d, "Target sudah terpasang."))], "end_turn", {}
    if "skenario_target" in k.tools and not k.sudah("skenario_target"):
        return ([_pikir("Hitung tiga skenario target per toko dulu."), _teks("Saya hitung skenario targetnya dulu."),
                 _alat("skenario_target", _isi_contoh(k.tools["skenario_target"], k.periode))], "tool_use", {})
    sk = k.terakhir("skenario_target")
    baris, petunjuk = _baris_skenario(sk[2]) if sk and not sk[3] else ([], {})
    if not k.sudah("tampilkan_tabel"):
        pre = []
        if "skenario_target" not in k.tools:
            pre.append(_teks("*(Mode uji: alat `skenario_target` belum terpasang, jadi tabel di bawah memakai angka "
                             "contoh.)*\n\n"))
        return pre + [_alat("tampilkan_tabel", _tabel_skenario(baris) or copy.deepcopy(_TABEL_SKENARIO_CONTOH))], \
            "tool_use", {}
    if "pasang_target_toko" not in k.tools:
        return ([_teks("*(Mode uji: alat `pasang_target_toko` belum terpasang, jadi kartu target belum bisa "
                       "disiapkan.)* Target bisa dipasang langsung di Portal Marketing › Target.")], "end_turn", {})
    args = _isi_tindakan(k.tools["pasang_target_toko"], k, {**petunjuk, "skenario": "realistis"}, baris)
    return ([_teks("Rekomendasi: skenario **realistis**. Saya siapkan kartu targetnya; periksa lalu tekan "
                   "**Setujui** bila sudah sesuai."), _alat("pasang_target_toko", args)], "tool_use", {})


# ── Tahap D: skrip "briefing" (briefing pagi & laporan mingguan otomatis) dan ingatan ──
ALAT_BRIEFING = ("ringkasan_penjualan", "target_toko", "posisi_kas_bank", "umur_piutang", "stok_menipis",
                 "pantau_produksi_ringkas", "daftar_persetujuan_menunggu")
ALAT_MINGGUAN = ("ringkasan_penjualan", "target_toko", "posisi_kas_bank", "umur_piutang", "stok_menipis",
                 "pantau_produksi_ringkas")
_RX_INGAT = re.compile(r"\bingat(lah)?\b\s*:?\s*(bahwa\s+)?(.*)$", re.IGNORECASE | re.DOTALL)
_RX_LUPA = re.compile(r"\blupakan\b", re.IGNORECASE)
_RX_ID_INGATAN = re.compile(r"\[(ing-[0-9a-f]{6,})\]")


def _laporan_mingguan_contoh(periode: str) -> dict:
    lap = _laporan_contoh(periode)
    lap["judul"] = "Laporan mingguan (mode uji)"
    lap["periode_label"] = "Pekan lalu"
    return lap


def _skrip_briefing(k: "Keadaan") -> tuple[list[dict], str, dict]:
    q = (k.pertanyaan or "").lower()
    mingguan = "laporan mingguan" in q
    if not k.dipanggil:
        nama = [n for n in (ALAT_MINGGUAN if mingguan else ALAT_BRIEFING) if n in k.tools]
        if nama:
            return ([_pikir("Kumpulkan data briefing dengan alat baca sekaligus."),
                     _teks("Saya kumpulkan datanya dulu.")]
                    + [_alat(n, _isi_contoh(k.tools[n], k.periode)) for n in nama], "tool_use", {})
    if "tampilkan_grafik" in k.tools and not k.sudah("tampilkan_grafik"):
        d = k.terakhir("ringkasan_penjualan")
        spec = (_grafik_dari_hasil(d[2]) if d and not d[3] else None) or copy.deepcopy(_GRAFIK_CONTOH)
        return [_alat("tampilkan_grafik", spec)], "tool_use", {}
    if mingguan and "buat_laporan" in k.tools and not k.sudah("buat_laporan"):
        return ([_teks("Saya susun berkas laporannya."), _alat("buat_laporan", _laporan_mingguan_contoh(k.periode))],
                "tool_use", {})
    baris = []
    for nama, _inp, isi, err in k.dipanggil:
        if nama in ("tampilkan_grafik", "buat_laporan"):
            continue
        baris.append(f"- {nama.replace('_', ' ')}: " + (f"belum terbaca ({str(isi)[:120]})" if err else "terbaca"))
    lap = k.terakhir("buat_laporan")
    judul = "Laporan mingguan" if mingguan else "Briefing pagi"
    teks = (f"### {judul} (mode uji)\n\n" + ("\n".join(baris) if baris else "- Tidak ada alat data yang terpasang.")
            + "\n\n**Yang perlu diperhatikan:** ini jawaban mode uji; angkanya tidak dianalisis sungguhan.")
    if mingguan:
        teks += ("\n\nBerkas laporan sudah dibuat; tautan unduhan ada di bawah." if lap and not lap[3] else
                 "\n\nBerkas laporan belum bisa dibuat di mode ini.")
    return [_teks(teks)], "end_turn", {}


def _blok_ingatan_terakhir(k: "Keadaan") -> str:
    for m in reversed(k.kw.get("messages") or []):
        if m.get("role") != "user" or not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            t = str(b.get("text") or "") if isinstance(b, dict) else ""
            if t.startswith("<konteks_sistem>") and "Ingatan Asisten AI" in t[:120]:
                return t
    return ""


def _skrip_ingatan(k: "Keadaan") -> tuple[list[dict], str, dict]:
    q = k.pertanyaan or ""
    lupa = bool(_RX_LUPA.search(q))
    nama = "lupakan_ingatan" if lupa else "simpan_ingatan"
    d = k.terakhir(nama)
    if d is not None:
        _n, _i, isi, err = d
        if err:
            return [_teks(f"Ingatan belum bisa diubah: {isi} *(mode uji)*")], "end_turn", {}
        sudah = isinstance(isi, str) and "sudah_ada" in isi
        return [_teks("Baik, sudah saya lupakan *(mode uji)*." if lupa else
                      "Itu sudah saya ingat sebelumnya *(mode uji)*." if sudah else
                      "Baik, sudah saya ingat *(mode uji)*.")], "end_turn", {}
    if nama not in k.tools:
        return [_teks("*(Mode uji: alat ingatan sedang tidak tersedia, jadi tidak ada ingatan yang diubah.)*")], \
            "end_turn", {}
    if lupa:
        ids = _RX_ID_INGATAN.findall(q) or _RX_ID_INGATAN.findall(_blok_ingatan_terakhir(k))
        if not ids:
            return [_teks("Belum ada ingatan yang bisa dilupakan *(mode uji)*.")], "end_turn", {}
        return [_pikir("Pengguna minta ingatan dilupakan."), _alat("lupakan_ingatan", {"id": ids[0]})], "tool_use", {}
    m = _RX_INGAT.search(q)
    isi = " ".join((m.group(3) if m else q).split()).strip(" .") or q.strip()
    isi = (isi[:1].upper() + isi[1:])[:300]
    kat = "gaya" if re.search(r"\b(jawab|gaya|singkat|bahasa)\b", isi, re.IGNORECASE) else "preferensi"
    return ([_pikir("Pengguna minta preferensi diingat."), _teks("Saya simpan sebagai ingatan."),
             _alat("simpan_ingatan", {"isi": isi, "kategori": kat})], "tool_use", {})


# ── Tahap E: hitung dengan kode (programmatic tool calling) + lampiran ──────
CALLER_KODE = "code_execution_20260120"
_RX_KODE = re.compile(r"\b(dengan|pakai|lewat)\s+kode\b|\bhitung\s+kode\b", re.IGNORECASE)
NAMA_BERKAS_CONTOH = "Rekap_hitung_mode_uji.xlsx"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_contoh() -> bytes:
    try:
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Rekap"
        ws.append(["Kelompok", "Nilai"])
        for i, v in enumerate((120, 85, 64), 1):
            ws.append([f"Contoh {i}", v])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — openpyxl tidak terpasang
        return b"PK\x03\x04 berkas contoh mode uji"


def _hasil_kode_selesai(k: "Keadaan") -> tuple[Optional[str], bool]:
    """(id server_tool_use code_execution yang masih terbuka, ada hasil kode yang sudah selesai)."""
    srv, tutup = [], set()
    for m in k.kw.get("messages", [])[k.idx + 1:]:
        if m.get("role") != "assistant" or not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            if b.get("type") == "server_tool_use" and b.get("name") == "code_execution":
                srv.append(b.get("id"))
            elif b.get("type") == "code_execution_tool_result":
                tutup.add(b.get("tool_use_id"))
    terbuka = [x for x in srv if x not in tutup]
    return (terbuka[-1] if terbuka else None), bool(tutup)


def _akhir_kode(k: "Keadaan", srv_id: Optional[str]) -> tuple[list[dict], str, dict]:
    blok: list[dict] = []
    n = sum(1 for d in k.dipanggil if d[0] in k.alat_kode and not d[3])
    if srv_id:
        blok.append({"type": "code_execution_tool_result", "tool_use_id": srv_id,
                     "content": {"type": "code_execution_result", "stdout": f"Panggilan data berhasil: {n}\n",
                                 "stderr": "", "return_code": 0, "content": []}})
    fid = k.induk.files.tambah_keluaran(NAMA_BERKAS_CONTOH, _xlsx_contoh(), MIME_XLSX) if k.induk else "file_tiruan"
    bid = _bid("srvtoolu")
    blok += [{"type": "server_tool_use", "id": bid, "name": "bash_code_execution",
              "input": {"command": 'python buat_rekap.py && ls "$OUTPUT_DIR"'}, "caller": {"type": "direct"}},
             {"type": "bash_code_execution_tool_result", "tool_use_id": bid,
              "content": {"type": "bash_code_execution_result", "stdout": NAMA_BERKAS_CONTOH + "\n", "stderr": "",
                          "return_code": 0, "content": [{"type": "bash_code_execution_output", "file_id": fid}]}},
             _teks(f"Perhitungan selesai ({n} panggilan data dari kode). Berkas **{NAMA_BERKAS_CONTOH}** siap "
                   "diunduh *(mode uji)*.")]
    return blok, "end_turn", {"kontainer": True}


def _skrip_kode(k: "Keadaan") -> tuple[list[dict], str, dict]:
    if not any(str(t.get("type", "")).startswith("code_execution") for t in k.kw.get("tools") or []):
        return ([_teks("*(Mode uji: ruang hitung sedang tidak tersedia, jadi perhitungan dengan kode dilewati.)*")],
                "end_turn", {})
    terbuka, selesai = _hasil_kode_selesai(k)
    if terbuka:
        return _akhir_kode(k, terbuka)
    if selesai or k.giliran_asisten:
        return [_teks("Perhitungan dengan kode sudah selesai *(mode uji)*.")], "end_turn", {}
    nama = "cari_data" if "cari_data" in k.alat_kode else (k.alat_kode[0] if k.alat_kode else None)
    if not nama:
        return _akhir_kode(k, None)
    sid = _bid("srvtoolu")
    caller = {"type": CALLER_KODE, "tool_id": sid}
    args = _isi_contoh(k.tools[nama], k.periode)
    kode = (f"import json, asyncio\nhasil = await asyncio.gather({nama}({json.dumps(args)}), "
            f"{nama}({json.dumps(args)}))\nprint('Panggilan data berhasil:', len(hasil))")
    return ([_pikir("Hitung dengan kode di ruang hitung; ambil data dari kode."),
             _teks("Saya hitung dengan kode di ruang hitung."),
             {"type": "server_tool_use", "id": sid, "name": "code_execution", "input": {"code": kode},
              "caller": {"type": "direct"}},
             {**_alat(nama, args), "caller": dict(caller)}, {**_alat(nama, copy.deepcopy(args)), "caller": dict(caller)}],
            "tool_use", {"kontainer": True})


def _skrip_lampiran(k: "Keadaan") -> tuple[list[dict], str, dict]:
    jenis = {"document": 0, "image": 0, "container_upload": 0}
    for b in k.lampiran:
        jenis[b["type"]] += 1
    bagian = [f"{jenis['document']} dokumen", f"{jenis['image']} gambar", f"{jenis['container_upload']} berkas data"]
    return ([_pikir("Baca lampiran pengguna."),
             _teks(f"Lampiran sudah saya terima: {', '.join(bagian)} *(mode uji)*.")], "end_turn",
            {"kontainer": bool(jenis["container_upload"])})


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
    # Tahap D: permintaan otomatis memuat banyak kata kunci lain → dicek paling awal.
    if "briefing" in q or "laporan mingguan" in q:
        return _skrip_briefing(k)
    if "pengingat" not in q and (_RX_LUPA.search(q) or _RX_INGAT.search(q)):
        return _skrip_ingatan(k)
    # Tahap E
    if _RX_KODE.search(q):
        return _skrip_kode(k)
    if k.lampiran:
        return _skrip_lampiran(k)
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
    if "pengingat" in q:
        return _skrip_pengingat(k)
    if "target" in q:
        return _skrip_target(k)
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
            if getattr(ev.delta, "container", None) is not None:
                self._snap.container = ev.delta.container

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


class _FakeBiner:
    """Pengganti `AsyncBinaryAPIResponse` (hanya `await .read()`)."""

    def __init__(self, data: bytes):
        self._data = data

    async def read(self) -> bytes:
        return self._data


class FakeFiles:
    """Files API tiruan (`upload`, `retrieve_metadata`, `download`, `delete`) — tanda tangan sama dengan SDK 2.3.0."""

    def __init__(self):
        self.berkas: dict[str, dict] = {}
        self.diunggah: list[str] = []
        self.dihapus: list[str] = []
        self.gagal_unggah = False
        self.gagal_hapus = False

    def _meta(self, fid: str) -> "_O":
        b = self.berkas[fid]
        return _O(id=fid, type="file", filename=b["filename"], mime_type=b["mime_type"], size_bytes=len(b["data"]),
                  downloadable=b["downloadable"], created_at=b["created_at"])

    async def upload(self, *, file, **_kw):
        if self.gagal_unggah:
            raise FakeAPIError(500, "upload failed (fake)")
        nama, data, mime = file
        data = data.read() if hasattr(data, "read") else bytes(data)
        fid = _bid("file")
        self.berkas[fid] = {"filename": nama, "data": data, "mime_type": mime, "downloadable": False,
                            "created_at": datetime.now(timezone.utc).isoformat()}
        self.diunggah.append(fid)
        return self._meta(fid)

    def tambah_keluaran(self, nama: str, data: bytes, mime: str) -> str:
        """Berkas yang 'dibuat kode' di ruang hitung (bisa diunduh)."""
        fid = _bid("file")
        self.berkas[fid] = {"filename": nama, "data": data, "mime_type": mime, "downloadable": True,
                            "created_at": datetime.now(timezone.utc).isoformat()}
        return fid

    async def retrieve_metadata(self, file_id: str, **_kw):
        if file_id not in self.berkas:
            raise FakeAPIError(404, f"File not found: {file_id}")
        return self._meta(file_id)

    async def download(self, file_id: str, **_kw):
        if file_id not in self.berkas:
            raise FakeAPIError(404, f"File not found: {file_id}")
        if not self.berkas[file_id]["downloadable"]:
            raise FakeAPIError(400, "This file is not downloadable.")
        return _FakeBiner(self.berkas[file_id]["data"])

    async def delete(self, file_id: str, **_kw):
        if self.gagal_hapus:
            raise FakeAPIError(500, "delete failed (fake)")
        if file_id not in self.berkas:
            raise FakeAPIError(404, f"File not found: {file_id}")
        del self.berkas[file_id]
        self.dihapus.append(file_id)
        return _O(id=file_id, type="file_deleted")


class FakeAsyncAnthropic:
    """Pengganti `anthropic.AsyncAnthropic` untuk loop Asisten AI (`.beta.messages.stream` + Files API tiruan)."""

    def __init__(self, skrip: Optional[Callable[[Keadaan], tuple]] = None, jeda: Optional[float] = None,
                 tolak_kode: bool = False):
        self.skrip = skrip or skrip_bawaan
        # Uji jalur darurat: tiruan API yang MENOLAK semua bentuk ruang hitung (alat, allowed_callers, container,
        # container_upload, blok code execution, caller kode) dengan galat 400 yang menyebut istilahnya.
        self.tolak_kode = bool(tolak_kode)
        self.jeda = float(os.environ.get("ASISTEN_AI_FAKE_JEDA", "0.01")) if jeda is None else jeda
        self.panggilan: list[dict] = []
        self._prefix_dilihat: set[str] = set()
        self.messages = _Messages(self)
        self.files = FakeFiles()
        self.beta = _O(messages=self.messages, files=self.files)
        # Tahap E: kontainer ruang hitung {id: kedaluwarsa?}
        self.kontainer: dict[str, bool] = {}

    def kedaluwarsakan_kontainer(self, cid: str) -> None:
        self.kontainer[cid] = True

    def _periksa_tahap_e(self, kw: dict) -> None:
        """Aturan programmatic tool calling, kontainer, dan Files API (meniru 400 API)."""
        if self.tolak_kode:
            teks = json.dumps({"tools": kw.get("tools"), "messages": kw.get("messages")}, ensure_ascii=False)
            for kata in ("allowed_callers", "container_upload", "code_execution"):
                if kata in teks:
                    raise FakeAPIError(400, f"{kata}: Extra inputs are not permitted (fake)")
            if kw.get("container"):
                raise FakeAPIError(400, "container: Extra inputs are not permitted (fake)")
        tools = kw.get("tools") or []
        ada_kode = any(t.get("type", "").startswith("code_execution") for t in tools)
        for t in tools:
            for c in t.get("allowed_callers") or []:
                if c not in ("direct", "code_execution_20250825", CALLER_KODE, "code_execution_20260521"):
                    raise FakeAPIError(400, f"tools.{t.get('name')}.allowed_callers: invalid value {c!r}")
            if t.get("allowed_callers") and not ada_kode:
                raise FakeAPIError(400, "allowed_callers requires a code execution tool")
        cid = kw.get("container")
        if cid is not None and (not isinstance(cid, str) or cid not in self.kontainer or self.kontainer[cid]):
            raise FakeAPIError(400, f"container '{cid}' has expired or does not exist; send the request without "
                                    "the container parameter to get a new container")
        msgs = kw.get("messages") or []
        for i, m in enumerate(msgs):
            c = m.get("content")
            if m.get("role") != "user" or not isinstance(c, list):
                continue
            for b in c:
                t = b.get("type") if isinstance(b, dict) else None
                fid = None
                if t in ("document", "image") and (b.get("source") or {}).get("type") == "file":
                    fid = b["source"].get("file_id")
                elif t == "container_upload":
                    fid = b.get("file_id")
                    if not ada_kode:
                        raise FakeAPIError(400, "container_upload requires the code execution tool")
                if t in ("document", "image", "container_upload") and fid not in self.files.berkas:
                    raise FakeAPIError(400, f"messages.{i}: file {fid} not found")
        # Panggilan dari kode yang tertunda: giliran terakhir asisten berisi tool_use ber-caller code execution.
        if len(msgs) >= 2 and msgs[-2].get("role") == "assistant" and isinstance(msgs[-2].get("content"), list):
            tertunda = [b for b in msgs[-2]["content"] if b.get("type") == "tool_use"
                        and str((b.get("caller") or {}).get("type", "")).startswith("code_execution")]
            if tertunda:
                last = msgs[-1].get("content") if isinstance(msgs[-1].get("content"), list) else []
                if any(not isinstance(b, dict) or b.get("type") != "tool_result" for b in last):
                    raise FakeAPIError(400, "When responding to programmatic tool calls, the user message must "
                                            "contain only tool_result blocks.")
                for b in last:
                    isi = b.get("content")
                    if not (isinstance(isi, str) or (isinstance(isi, list) and all(
                            isinstance(x, dict) and x.get("type") == "text" for x in isi))):
                        raise FakeAPIError(400, "tool_result content for programmatic tool calls must be text")
                if not cid:
                    raise FakeAPIError(400, "container is required when responding to pending programmatic tool "
                                            "calls")
                if (kw.get("tool_choice") or {}).get("type") == "none":
                    raise FakeAPIError(400, "tool_choice none is not allowed while programmatic tool calls are "
                                            "pending (fake)")

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
        self._periksa_tahap_e(kw)
        k = Keadaan(kw)
        k.induk = self
        blok, stop, ekstra = self.skrip(k)
        blok = [copy.deepcopy(b) for b in blok]
        # Kontainer: dipakai ulang bila dikirim; dibuat baru bila respons memakai ruang hitung.
        cid = kw.get("container")
        if not cid and (ekstra.get("kontainer") or any(
                b.get("type") == "container_upload" for m in kw.get("messages") or []
                if isinstance(m.get("content"), list) for b in m["content"] if isinstance(b, dict))):
            cid = _bid("container")
            self.kontainer[cid] = False
        kontainer = None
        if cid:
            kontainer = {"id": cid, "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}
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
                                        "stop_details": ekstra.get("stop_details"), "container": kontainer}),
                         usage=usage))
        final = _ke_obj({"id": mid, "type": "message", "role": "assistant", "model": MODEL_TIRUAN,
                         "content": blok, "stop_reason": stop, "stop_sequence": None,
                         "stop_details": ekstra.get("stop_details"), "usage": u, "container": kontainer})
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
