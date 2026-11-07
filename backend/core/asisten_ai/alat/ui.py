"""Alat tampilan Asisten AI (jenis `ui`): grafik dan tabel di dalam jawaban chat.

Spesifikasi = Kontrak B. Handler memvalidasi, memancarkan event `grafik`/`tabel`, lalu mengembalikan
`{"ok": true}` ke model. Isian yang tidak sah → `AlatError` berpesan jelas sehingga model bisa
memperbaiki dan memanggil ulang.
"""
from __future__ import annotations

import math

from core.asisten_ai.alat_base import AlatError, alat, id_pendek

JENIS_GRAFIK = ("batang", "batang_horizontal", "garis", "area", "pai")
MAKS_SERI = 4
MAKS_TITIK = 31
MAKS_KOLOM = 12
MAKS_BARIS = 100
MAKS_IRISAN_PAI = 12


def _angka_sah(v) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v))


def _teks(v, nama: str, wajib: bool = True, maks: int = 160) -> str:
    if v is None or (isinstance(v, str) and not v.strip()):
        if wajib:
            raise AlatError(400, f"Grafik/tabel tidak valid: {nama} wajib diisi.")
        return ""
    if not isinstance(v, str):
        raise AlatError(400, f"Grafik/tabel tidak valid: {nama} harus teks.")
    return v.strip()[:maks]


def validasi_grafik(args: dict) -> dict:
    """Spesifikasi grafik yang sudah bersih (Kontrak B) atau AlatError(400, alasan)."""
    jenis = args.get("jenis")
    if jenis not in JENIS_GRAFIK:
        raise AlatError(400, f"Grafik tidak valid: jenis harus salah satu dari {', '.join(JENIS_GRAFIK)}.")
    judul = _teks(args.get("judul"), "judul")
    satuan = _teks(args.get("satuan"), "satuan", wajib=False, maks=24)
    x = args.get("x")
    if not isinstance(x, list) or not x:
        raise AlatError(400, "Grafik tidak valid: x wajib berisi daftar label (minimal 1).")
    if len(x) > MAKS_TITIK:
        raise AlatError(400, f"Grafik tidak valid: paling banyak {MAKS_TITIK} titik pada sumbu x "
                             f"(ada {len(x)}). Kelompokkan datanya (mis. per minggu) atau pakai tabel.")
    x = [str(v)[:60] for v in x]
    seri = args.get("seri")
    if not isinstance(seri, list) or not seri:
        raise AlatError(400, "Grafik tidak valid: seri wajib berisi minimal 1 seri.")
    if len(seri) > MAKS_SERI:
        raise AlatError(400, f"Grafik tidak valid: paling banyak {MAKS_SERI} seri (ada {len(seri)}).")
    if jenis == "pai":
        if len(seri) != 1:
            raise AlatError(400, "Grafik pai tidak valid: pai harus tepat 1 seri.")
        if len(x) > MAKS_IRISAN_PAI:
            raise AlatError(400, f"Grafik pai tidak valid: paling banyak {MAKS_IRISAN_PAI} irisan; "
                                 "gabungkan sisanya menjadi 'Lainnya' atau pakai batang.")
    bersih = []
    for i, s in enumerate(seri):
        if not isinstance(s, dict):
            raise AlatError(400, f"Grafik tidak valid: seri ke-{i + 1} harus objek {{nama, nilai}}.")
        nama = _teks(s.get("nama"), f"nama seri ke-{i + 1}", maks=60)
        nilai = s.get("nilai")
        if not isinstance(nilai, list) or len(nilai) != len(x):
            raise AlatError(400, f"Grafik tidak valid: nilai seri '{nama}' harus {len(x)} angka "
                                 "(sama dengan jumlah label x).")
        if not all(_angka_sah(v) for v in nilai):
            raise AlatError(400, f"Grafik tidak valid: nilai seri '{nama}' harus angka (atau null).")
        if jenis == "pai" and any(v is not None and v < 0 for v in nilai):
            raise AlatError(400, "Grafik pai tidak valid: nilai tidak boleh negatif.")
        bersih.append({"nama": nama, "nilai": nilai})
    spec = {"jenis": jenis, "judul": judul, "satuan": satuan, "x": x, "seri": bersih}
    catatan = _teks(args.get("catatan"), "catatan", wajib=False, maks=300)
    if catatan:
        spec["catatan"] = catatan
    return spec


def validasi_tabel(args: dict) -> dict:
    judul = _teks(args.get("judul"), "judul")
    kolom = args.get("kolom")
    if not isinstance(kolom, list) or not kolom or len(kolom) > MAKS_KOLOM:
        raise AlatError(400, f"Tabel tidak valid: kolom wajib 1–{MAKS_KOLOM} judul kolom.")
    kolom = [_teks(k, f"judul kolom ke-{i + 1}", maks=60) for i, k in enumerate(kolom)]
    baris = args.get("baris")
    if not isinstance(baris, list):
        raise AlatError(400, "Tabel tidak valid: baris wajib berupa daftar.")
    if len(baris) > MAKS_BARIS:
        raise AlatError(400, f"Tabel tidak valid: paling banyak {MAKS_BARIS} baris (ada {len(baris)}). "
                             "Tampilkan ringkasan atau buat laporan Excel untuk rincian penuh.")
    bersih = []
    for i, b in enumerate(baris):
        if not isinstance(b, list) or len(b) != len(kolom):
            raise AlatError(400, f"Tabel tidak valid: baris ke-{i + 1} harus {len(kolom)} sel.")
        sel = []
        for v in b:
            if isinstance(v, str):
                sel.append(v[:200])
            elif _angka_sah(v):
                sel.append(v)
            else:
                raise AlatError(400, f"Tabel tidak valid: sel di baris ke-{i + 1} harus teks atau angka.")
        bersih.append(sel)
    out = {"judul": judul, "kolom": kolom, "baris": bersih}
    catatan = _teks(args.get("catatan"), "catatan", wajib=False, maks=300)
    if catatan:
        out["catatan"] = catatan
    return out


_SKEMA_GRAFIK = {
    "type": "object",
    "properties": {
        "jenis": {"type": "string", "enum": list(JENIS_GRAFIK),
                  "description": "batang/batang_horizontal = perbandingan antarkategori; garis/area = tren waktu; "
                                 "pai = komposisi (tepat 1 seri, ≤12 irisan)."},
        "judul": {"type": "string", "description": "Judul singkat, huruf besar hanya di awal."},
        "satuan": {"type": "string", "description": "Satuan nilai: Rp, pcs, %, pesanan, dll."},
        "x": {"type": "array", "items": {"type": "string"}, "maxItems": MAKS_TITIK,
              "description": "Label sumbu x (kategori atau tanggal), paling banyak 31."},
        "seri": {"type": "array", "maxItems": MAKS_SERI,
                 "items": {"type": "object",
                           "properties": {"nama": {"type": "string"},
                                          "nilai": {"type": "array", "items": {"type": ["number", "null"]}}},
                           "required": ["nama", "nilai"], "additionalProperties": False},
                 "description": "1–4 seri; panjang `nilai` tiap seri = panjang `x`. Nilai rupiah dalam rupiah penuh."},
        "catatan": {"type": "string", "description": "Opsional: sumber/asumsi singkat di bawah grafik."},
    },
    "required": ["jenis", "judul", "x", "seri"],
    "additionalProperties": False,
}

_SKEMA_TABEL = {
    "type": "object",
    "properties": {
        "judul": {"type": "string", "description": "Judul tabel singkat."},
        "kolom": {"type": "array", "items": {"type": "string"}, "maxItems": MAKS_KOLOM,
                  "description": "Judul kolom (1–12), bahasa Indonesia, tanpa istilah program."},
        "baris": {"type": "array", "maxItems": MAKS_BARIS,
                  "items": {"type": "array", "items": {"type": ["string", "number", "null"]}},
                  "description": "Isi tabel (≤100 baris); tiap baris sepanjang `kolom`. Angka uang boleh angka "
                                 "rupiah penuh atau teks berformat (mis. 'Rp 412,6 jt')."},
        "catatan": {"type": "string", "description": "Opsional: catatan/sumber singkat di bawah tabel."},
    },
    "required": ["judul", "kolom", "baris"],
    "additionalProperties": False,
}


@alat(
    name="tampilkan_grafik",
    kind="ui",
    label="Menggambar grafik",
    description=(
        "Menampilkan satu grafik di jawaban chat. Panggil bila visual membantu pengguna memahami angka: "
        "tren waktu (garis/area), perbandingan antar toko/produk/kategori (batang; batang_horizontal bila "
        "label panjang atau kategori banyak), atau komposisi dengan sedikit bagian (pai, tepat 1 seri). "
        "Batas: paling banyak 4 seri dan 31 label sumbu x. Semua angka WAJIB berasal dari hasil alat data "
        "pada percakapan ini. Mengembalikan {ok: true} bila grafik tampil; bila isian salah, mengembalikan "
        "pesan galat yang menjelaskan apa yang harus diperbaiki."
    ),
    input_schema=_SKEMA_GRAFIK,
    domain="ui",
)
async def tampilkan_grafik(ctx, args: dict) -> dict:
    spec = validasi_grafik(args)
    ctx.emit("grafik", {"id": id_pendek("grf"), "spec": spec})
    return {"ok": True}


@alat(
    name="tampilkan_tabel",
    kind="ui",
    label="Menyusun tabel",
    description=(
        "Menampilkan satu tabel di jawaban chat. Panggil untuk angka rinci yang perlu dibaca persis "
        "(mis. omzet per toko, daftar SKU teratas, piutang per klien) — biasanya ≥4 baris atau ≥3 kolom. "
        "Batas: 12 kolom, 100 baris. Semua angka WAJIB berasal dari hasil alat data. Mengembalikan "
        "{ok: true} bila tabel tampil; bila isian salah, mengembalikan pesan galat yang menjelaskan perbaikannya."
    ),
    input_schema=_SKEMA_TABEL,
    domain="ui",
)
async def tampilkan_tabel(ctx, args: dict) -> dict:
    tabel = validasi_tabel(args)
    ctx.emit("tabel", {"id": id_pendek("tbl"), **tabel})
    return {"ok": True}
