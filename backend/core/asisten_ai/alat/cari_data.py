"""Alat baca Asisten AI — data fleksibel (Tahap E, kontrak K1): `daftar_data` dan `cari_data`.

Mesin katalog, pembangun pipeline, dan cek akses ada di `core.asisten_ai.katalog_data`; definisi dataset di
`core/asisten_ai/katalog/`. Alat ini BACA SAJA dan langsung membaca basis data (`ctx.db`) dengan aturan akses,
CV, lingkup toko, dan privasi yang sama dengan layar.
"""
from __future__ import annotations

from core.asisten_ai import katalog_data as K
from core.asisten_ai.alat_base import alat

_SKALAR = [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]
_SKEMA_NILAI = {"anyOf": _SKALAR + [{"type": "null"}, {"type": "array", "maxItems": K.MAKS_DAFTAR_NILAI,
                                                       "items": {"anyOf": _SKALAR}}]}
_TGL = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
_NAMA = {"type": "string", "maxLength": 40}


@alat(
    name="daftar_data",
    kind="read",
    label="Melihat daftar data sistem",
    description=(
        "Daftar dataset sistem yang BOLEH dibaca pengguna ini lewat cari_data: id, label, keterangan, kolom (nama:tipe), "
        "kolom tanggal untuk periode, dan catatan cara membaca angka (mis. definisi omzet, biaya platform, status "
        "selesai). Panggil SEKALI sebelum cari_data bila belum tahu id dataset atau nama kolomnya. Isi `dataset` "
        "(satu id atau daftar ≤5 id) untuk rincian kolom: label, keterangan, nilai yang mungkin (untuk filter persis), "
        "dan kolom mana yang berupa kode samaran."),
    input_schema={
        "type": "object",
        "properties": {"dataset": {"anyOf": [{"type": "string"}, {"type": "array", "maxItems": 5,
                                                                   "items": {"type": "string"}}],
                                   "description": "Opsional: id dataset yang ingin dilihat rincian kolomnya."}},
        "additionalProperties": False,
    },
    domain="umum",
)
async def daftar_data(ctx, args: dict) -> dict:
    return await K.daftar(ctx, args or {})


@alat(
    name="cari_data",
    kind="read",
    label="Mencari data sistem",
    kode=True,
    description=(
        "Membaca data sistem (BACA SAJA) dari satu dataset katalog dengan filter, periode, pengelompokan, dan agregasi "
        "yang dihitung di server. Pakai untuk pertanyaan yang tidak terjawab alat ringkasan tetap dan untuk laporan "
        "custom (mis. omzet per SKU per minggu, tagihan CMT per vendor, absensi per departemen, stok per lokasi). "
        "Panggil daftar_data dulu bila belum tahu id dataset & nama kolomnya — hanya kolom katalog yang diterima.\n"
        "Isian: dataset (wajib); kolom (mode baris); filter [{kolom, op, nilai}] dengan op: = != > >= < <= in not_in "
        "berisi kosong tidak_kosong (in/not_in memakai daftar; berisi = potongan teks tanpa beda huruf; tanggal "
        "TTTT-BB-HH); periode {dari, sampai} TTTT-BB-HH (WIB) pada kolom tanggal dataset; kelompok [kolom] — termasuk "
        "kolom turunan <kolom_tanggal>_bulan/_minggu/_tahun untuk tren; agregasi [{fungsi, kolom?, nama?}] dengan "
        "fungsi jumlah rata min maks hitung hitung_unik; urut [{kolom, arah: naik|turun}] (mode kelompok: kolom "
        "kelompok atau nama agregasi); batas.\n"
        "Untuk data besar JANGAN menarik baris mentah: pakai kelompok + agregasi supaya server yang menghitung. "
        f"Panggilan langsung paling banyak {K.BATAS_LANGSUNG} baris; dari kode di ruang hitung (code execution) "
        f"paling banyak {K.BATAS_KODE} baris per panggilan — untuk pivot, tren, proyeksi, atau berkas Excel panggil "
        "alat ini dari kode: json.loads(await cari_data({...})).\n"
        "Hasil: {dataset, label, cv, kolom, baris, jumlah_baris, total_cocok, terpotong, catatan}. Data mengikuti hak "
        "akses pengguna, CV yang dipilih di layar, dan lingkup toko; nama vendor/pelanggan (dan karyawan bagi peran "
        "non-SDM) berupa kode samaran; baca `catatan` sebelum menyimpulkan angka."),
    input_schema={
        "type": "object",
        "required": ["dataset"],
        "additionalProperties": False,
        "properties": {
            "dataset": {"type": "string", "maxLength": 40, "description": "id dataset dari daftar_data"},
            "kolom": {"type": "array", "maxItems": K.MAKS_KOLOM, "items": _NAMA,
                      "description": "Kolom yang ditampilkan (mode baris). Kosong = kolom bawaan."},
            "filter": {"type": "array", "maxItems": K.MAKS_FILTER, "items": {
                "type": "object", "required": ["kolom", "op"], "additionalProperties": False,
                "properties": {"kolom": _NAMA, "op": {"type": "string", "enum": list(K.OPS)}, "nilai": _SKEMA_NILAI}}},
            "periode": {"type": "object", "additionalProperties": False,
                        "properties": {"dari": _TGL, "sampai": _TGL}},
            "kelompok": {"type": "array", "maxItems": K.MAKS_KELOMPOK, "items": _NAMA},
            "agregasi": {"type": "array", "maxItems": K.MAKS_AGREGASI, "items": {
                "type": "object", "required": ["fungsi"], "additionalProperties": False,
                "properties": {"fungsi": {"type": "string", "enum": list(K.FUNGSI)}, "kolom": _NAMA,
                               "nama": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{1,39}$"}}}},
            "urut": {"type": "array", "maxItems": K.MAKS_URUT, "items": {
                "type": "object", "required": ["kolom"], "additionalProperties": False,
                "properties": {"kolom": _NAMA, "arah": {"type": "string", "enum": list(K.ARAH)}}}},
            "batas": {"type": "integer", "minimum": 1, "maximum": K.BATAS_KODE},
        },
    },
    domain="umum",
)
async def cari_data(ctx, args: dict) -> dict:
    return await K.cari(ctx, args or {})
