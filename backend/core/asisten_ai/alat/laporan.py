"""Alat Asisten AI: buat_laporan — laporan PDF/Excel berkop CV dari hasil analisis (Kontrak A).

Model mengirim SPESIFIKASI laporan (judul, format, bagian berisi teks markdown sederhana, tabel, grafik).
Angka di laporan harus berasal dari alat baca yang sudah dipanggil di percakapan; alat ini tidak membaca
data sendiri. Pembuatan berkas, penyimpanan, dan unduhan: `core/laporan_ai.py` +
`GET /api/asisten-ai/laporan/{id}` (hanya pembuat, owner, dan superadmin yang bisa mengunduh).
"""
from __future__ import annotations

from core.asisten_ai.alat_base import AlatError, alat
from core import laporan_ai as la

_SKEMA_GRAFIK = {
    "type": "object",
    "description": "Grafik (bentuk sama dengan tampilkan_grafik). Paling banyak 4 seri dan 31 titik x; pai tepat 1 seri.",
    "properties": {
        "jenis": {"type": "string", "enum": list(la.JENIS_GRAFIK)},
        "judul": {"type": "string"},
        "satuan": {"type": "string", "description": "Rp, pcs, %, dll."},
        "x": {"type": "array", "items": {"type": "string"}, "maxItems": la.BATAS["titik"]},
        "seri": {"type": "array", "maxItems": la.BATAS["seri"], "items": {
            "type": "object",
            "properties": {"nama": {"type": "string"},
                           "nilai": {"type": "array", "items": {"type": ["number", "null"]}}},
            "required": ["nama", "nilai"], "additionalProperties": False}},
        "catatan": {"type": "string"},
    },
    "required": ["jenis", "x", "seri"],
    "additionalProperties": False,
}

_SKEMA_TABEL = {
    "type": "object",
    "properties": {
        "kolom": {"type": "array", "items": {"type": "string"}, "maxItems": la.BATAS["kolom"]},
        "baris": {"type": "array", "maxItems": la.BATAS["baris"],
                  "items": {"type": "array", "items": {"type": ["string", "number", "null"]}}},
        "satuan": {"type": "array", "items": {"type": "string"},
                   "description": "Opsional, satu per kolom: \"Rp\" (uang), \"%\", \"pcs\", atau \"\" (teks)."},
        "catatan": {"type": "string"},
    },
    "required": ["kolom", "baris"],
    "additionalProperties": False,
}

SKEMA = {
    "type": "object",
    "properties": {
        "judul": {"type": "string", "maxLength": la.BATAS["judul"]},
        "subjudul": {"type": "string", "maxLength": la.BATAS["subjudul"]},
        "periode_label": {"type": "string", "description": "Mis. \"Oktober 2026\" atau \"1–31 Okt 2026\"."},
        "format": {"type": "array", "items": {"type": "string", "enum": list(la.FORMAT_SAH)},
                   "minItems": 1, "maxItems": 2},
        "bagian": {"type": "array", "minItems": 1, "maxItems": la.BATAS["bagian"], "items": {
            "type": "object",
            "properties": {
                "judul": {"type": "string"},
                "teks": {"type": "string", "description": "Markdown sederhana: judul (##), **tebal**, *miring*, "
                                                          "daftar berpoin (-) dan bernomor (1.)."},
                "tabel": _SKEMA_TABEL,
                "grafik": _SKEMA_GRAFIK,
            },
            "additionalProperties": False}},
    },
    "required": ["judul", "format", "bagian"],
    "additionalProperties": False,
}

DESKRIPSI = (
    "Membuat berkas laporan yang bisa diunduh pengguna: PDF A4 berkop CV aktif (kop gabungan dua CV bila "
    "Gabungan) dan/atau Excel (lembar Ringkasan + satu lembar per tabel, kolom uang berformat Rp). "
    "Pakai HANYA angka yang sudah didapat dari alat baca di percakapan ini; jangan mengarang angka. "
    "Isi: judul, format [\"pdf\"] / [\"xlsx\"] / [\"pdf\",\"xlsx\"], dan bagian (maks 30) yang masing-masing "
    "berisi teks markdown sederhana, tabel {kolom, baris (maks 300), satuan?, catatan?}, dan/atau grafik "
    "(bentuk sama dengan tampilkan_grafik). Nilai uang ditulis sebagai angka rupiah utuh (bukan teks). "
    "Mengembalikan laporan_id, judul, dan daftar berkas; tombol unduh tampil otomatis di chat, jadi "
    "jangan menulis tautan unduhan sendiri."
)


@alat(name="buat_laporan", kind="read", label="Menyusun laporan PDF/Excel", description=DESKRIPSI,
      input_schema=SKEMA, domain="laporan")
async def buat_laporan(ctx, args: dict) -> dict:
    db = getattr(ctx, "db", None)
    if db is None:
        from database import get_db
        db = get_db()
    try:
        doc = await la.buat_dan_simpan(db, args or {}, user=ctx.user or {}, cv=getattr(ctx, "cv", "DA") or "DA",
                                       sesi_id=getattr(ctx, "sesi_id", None) or getattr(ctx, "session_id", None))
    except la.SpekLaporanError as e:
        raise AlatError(400, f"Isi laporan belum benar: {e.pesan}") from None
    berkas = [{"format": b["format"], "nama_berkas": b["nama_berkas"], "ukuran_kb": round(b["ukuran"] / 1024, 1)}
              for b in doc["berkas"]]
    return {
        "laporan_id": doc["id"],
        "judul": doc["judul"],
        "berkas": berkas,
        "cv": la.label_cv(doc["cv"]),
        "_sumber": "Laporan Asisten AI",
        "_ui_events": [{"event": "laporan", "data": d} for d in la.ringkas_untuk_ui(doc)],
    }
