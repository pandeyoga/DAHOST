"""Berkas keluaran "hitung dengan kode" Asisten AI (Tahap E, 9 Nov 2026) — Kontrak K3 (backend).

Kode Python yang dijalankan Claude di ruang hitung (code execution) bisa membuat berkas (xlsx, docx, pptx, png, csv,
pdf, …). Berkas yang disalin ke `$OUTPUT_DIR` dikembalikan API sebagai blok:

    bash_code_execution_tool_result.content (bash_code_execution_result).content[] = {type: bash_code_execution_output,
                                                                                      file_id}
    code_execution_tool_result.content (code_execution_result | encrypted_code_execution_result).content[]
                                                                                    = {type: code_execution_output, file_id}

Di sini berkas itu:
  1. dibaca metadatanya (`files.retrieve_metadata`) + diunduh (`files.download`) lewat Files API — nama berkas SELALU
     `os.path.basename` + dirapikan (tidak pernah dipercaya mentah);
  2. dibatasi ukuran (`MAKS_UKURAN`) dan jumlah per jawaban (`MAKS_BERKAS_JAWABAN`);
  3. disimpan salinannya lewat `object_storage.put_object` di bawah awalan `ai_berkas/<id>/<acak>.<ext>` (awalan itu
     sensitif di `core/sensitive_files.py`: tidak terbuka tanpa login), metadata di koleksi `ai_berkas` (jenis log);
  4. dipancarkan sebagai event `berkas` {id, nama, format, ukuran_kb, url} + blok riwayat `{jenis: "berkas", …}`.

Unduhan hanya lewat `GET /api/asisten-ai/berkas/{id}` (`routes/asisten_ai_berkas_routes.py`): pembuat + owner/superadmin.
Berkas di Anthropic dibiarkan (dirujuk riwayat percakapan) dan dihapus saat percakapannya dihapus
(`core/asisten_ai/lampiran.hapus_berkas_sesi`).
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger(__name__)

COLL = "ai_berkas"
AWALAN_PATH = "ai_berkas"
PERAN_UNDUH_SEMUA = ("owner", "superadmin")
MAKS_UKURAN = int(os.environ.get("ASISTEN_AI_MAKS_BERKAS_MB", "30")) * 1024 * 1024
MAKS_BERKAS_JAWABAN = 10
BATAS_DETIK_UNDUH = 90.0
MAKS_NAMA = 120

JENIS_HASIL_KODE = ("code_execution_tool_result", "bash_code_execution_tool_result",
                    "text_editor_code_execution_tool_result")
_NAMA_DARI_HASIL = {"code_execution_tool_result": "code_execution",
                    "bash_code_execution_tool_result": "bash_code_execution",
                    "text_editor_code_execution_tool_result": "text_editor_code_execution"}
_JENIS_KELUARAN = ("bash_code_execution_output", "code_execution_output")

CONTENT_TYPE = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf", "csv": "text/csv; charset=utf-8", "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8", "json": "application/json",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "zip": "application/zip",
}
# Jenis yang bisa dieksekusi peramban bila dibuka langsung → selalu dikirim sebagai unduhan biner.
_BERISIKO = {"html", "htm", "xhtml", "svg", "xml", "js", "mjs"}

_GALAT_KODE = {
    "unavailable": "Ruang hitung sedang tidak tersedia.",
    "execution_time_exceeded": "Perhitungan terlalu lama sehingga dihentikan.",
    "too_many_requests": "Ruang hitung sedang sibuk.",
    "output_file_too_large": "Hasil perhitungan terlalu besar.",
    "invalid_tool_input": "Perintah perhitungan tidak sah.",
    "file_not_found": "Berkas di ruang hitung tidak ditemukan.",
}


class GalatBerkas(Exception):
    def __init__(self, pesan: str):
        super().__init__(pesan)
        self.pesan = pesan


def _attr(o: Any, name: str, default=None):
    if o is None:
        return default
    if isinstance(o, dict):
        return o.get(name, default)
    return getattr(o, name, default)


# ── Membaca blok hasil code execution ───────────────────────────────────────
def nama_alat_hasil(jenis_blok: str) -> str:
    return _NAMA_DARI_HASIL.get(jenis_blok, "code_execution")


def galat_hasil(blok: Any) -> Optional[str]:
    """Pesan ramah bila blok hasil code execution berupa galat alat (bukan galat kode Python)."""
    c = _attr(blok, "content")
    t = str(_attr(c, "type") or "")
    if t.endswith("_error"):
        return _GALAT_KODE.get(str(_attr(c, "error_code") or ""), "Perhitungan dengan kode gagal.")
    return None


def file_id_keluaran(konten: list) -> list[str]:
    """file_id berkas keluaran dari blok hasil code execution (urutan muncul, tanpa duplikat)."""
    out: list[str] = []
    for b in konten or []:
        if _attr(b, "type") not in ("code_execution_tool_result", "bash_code_execution_tool_result"):
            continue
        c = _attr(b, "content")
        isi = _attr(c, "content")
        if not isinstance(isi, (list, tuple)):
            continue
        for x in isi:
            fid = _attr(x, "file_id")
            if _attr(x, "type") in _JENIS_KELUARAN and isinstance(fid, str) and fid and fid not in out:
                out.append(fid)
    return out


# ── Nama & format ────────────────────────────────────────────────────────────
_NAMA_RX = re.compile(r"[^\w .,()+&@#%=-]+", re.UNICODE)


def nama_aman(nama: Any, cadangan: str = "hasil") -> str:
    """`os.path.basename` + buang karakter kendali/pemisah path + batasi panjang (ekstensi dipertahankan)."""
    n = os.path.basename(str(nama or "").replace("\\", "/")).strip()
    n = _NAMA_RX.sub("_", n).strip(" ._") if n else ""
    if not n or n in (".", ".."):
        n = cadangan
    if len(n) > MAKS_NAMA:
        dasar, ext = os.path.splitext(n)
        n = dasar[: MAKS_NAMA - len(ext)] + ext
    return n


def format_dari(nama: str) -> str:
    ext = os.path.splitext(nama)[1].lower().lstrip(".")
    return ext if re.fullmatch(r"[a-z0-9]{1,10}", ext or "") else "berkas"


def content_type_dari(fmt: str, mime: Optional[str] = None) -> str:
    if fmt in _BERISIKO:
        return "application/octet-stream"
    if fmt in CONTENT_TYPE:
        return CONTENT_TYPE[fmt]
    tebak = mimetypes.guess_type(f"x.{fmt}")[0] or (mime if isinstance(mime, str) else None)
    if not tebak or any(r in tebak for r in ("html", "svg", "xml", "javascript")):
        return "application/octet-stream"
    return tebak


def url_unduh(berkas_id: str) -> str:
    return f"/api/asisten-ai/berkas/{berkas_id}"


def ukuran_kb(n: int) -> float:
    return round(max(0, int(n or 0)) / 1024, 1)


def boleh_unduh(user: dict, doc: dict) -> bool:
    """Hanya pembuat berkas (pemilik percakapan), ditambah owner/superadmin."""
    role = str((user or {}).get("role") or "").lower()
    return bool(doc) and (role in PERAN_UNDUH_SEMUA or bool((user or {}).get("id")
                                                          and user.get("id") == doc.get("dibuat_oleh")))


def event_berkas(doc: dict) -> dict:
    """Data event SSE `berkas` (= blok riwayat tanpa `jenis`)."""
    return {"id": doc["id"], "nama": doc["nama"], "format": doc["format"], "ukuran_kb": ukuran_kb(doc["ukuran"]),
            "url": url_unduh(doc["id"])}


def files_api(klien):
    """Sumber daya Files API: stabil (`klien.files`) bila ada, selain itu `klien.beta.files` (SDK lama)."""
    f = getattr(klien, "files", None)
    if f is not None and hasattr(f, "retrieve_metadata"):
        return f
    return klien.beta.files


async def _baca_unduhan(resp: Any) -> bytes:
    if isinstance(resp, (bytes, bytearray)):
        return bytes(resp)
    baca = getattr(resp, "read", None)
    if baca is None:
        raise GalatBerkas("Berkas hasil hitung tidak bisa dibaca.")
    data = baca()
    if asyncio.iscoroutine(data):
        data = await data
    return bytes(data or b"")


async def unduh_dan_simpan(db, klien, file_id: str, *, user: dict, sesi_id: Optional[str], pesan_id: Optional[str],
                           put_object=None) -> dict:
    """Ambil SATU berkas keluaran dari Files API → simpan salinan + metadata. Return dokumen `ai_berkas`.
    Galat yang aman ditampilkan → `GalatBerkas`."""
    files = files_api(klien)
    try:
        meta = await files.retrieve_metadata(file_id)
    except Exception as e:  # noqa: BLE001
        log.warning("Asisten AI: metadata berkas keluaran gagal dibaca (%s)", type(e).__name__)
        raise GalatBerkas("Berkas hasil hitung tidak bisa diambil dari ruang hitung.") from e
    nama = nama_aman(_attr(meta, "filename"), cadangan="hasil_hitung")
    besar = _attr(meta, "size_bytes")
    if isinstance(besar, int) and besar > MAKS_UKURAN:
        raise GalatBerkas(f"Berkas \"{nama}\" terlalu besar untuk diunduh (maksimal {MAKS_UKURAN // (1024 * 1024)} MB).")
    try:
        data = await _baca_unduhan(await files.download(file_id))
    except GalatBerkas:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("Asisten AI: unduh berkas keluaran gagal (%s)", type(e).__name__)
        raise GalatBerkas(f"Berkas \"{nama}\" gagal diambil dari ruang hitung.") from e
    if not data:
        raise GalatBerkas(f"Berkas \"{nama}\" kosong.")
    if len(data) > MAKS_UKURAN:
        raise GalatBerkas(f"Berkas \"{nama}\" terlalu besar untuk diunduh (maksimal {MAKS_UKURAN // (1024 * 1024)} MB).")
    fmt = format_dari(nama)
    if put_object is None:
        from object_storage import put_object
    berkas_id = str(uuid.uuid4())
    path = f"ai_berkas/{berkas_id}/{secrets.token_hex(16)}" + (f".{fmt}" if fmt != "berkas" else "")
    res = await asyncio.to_thread(put_object, path, data, content_type_dari(fmt, _attr(meta, "mime_type")))
    doc = {"id": berkas_id, "dibuat_oleh": (user or {}).get("id"), "peran": (user or {}).get("role") or "",
           "sesi_id": sesi_id, "pesan_id": pesan_id, "nama": nama, "format": fmt, "ukuran": len(data),
           "mime": _attr(meta, "mime_type"), "path": (res or {}).get("path") or path, "file_id": file_id,
           "created_at": datetime.now(timezone.utc).isoformat()}
    await db[COLL].insert_one(dict(doc))
    doc.pop("_id", None)
    return doc
