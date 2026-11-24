"""core.batal_setuju_jenis — daftar SEMUA jenis persetujuan yang bisa dibatalkan (lihat `core.batal_setuju`).

Setiap entri meniru tombol Setujui jenis itu:
  · `status_setuju`  = status yang ditulis tombol Setujui;
  · `kembali_ke`     = status sebelum disetujui (menunggu keputusan), supaya bisa diputus ulang;
  · `izin`/`peran_lama` = gerbang yang sama dengan tombol Setujui;
  · `hambatan`       = langkah lanjutan yang sudah memakai persetujuan ini → pembatalan ditolak dengan kalimatnya;
  · `balikkan`       = efek yang muncul TEPAT saat disetujui dan harus dibalik (jurnal, saldo, dokumen turunan).
"""
from __future__ import annotations

from core.batal_setuju import Jenis, daftar


# ───────────────────────────── R&D ─────────────────────────────
async def _hambatan_style(db, d: dict) -> list:
    out = []
    mid = d.get("promoted_to_model_id")
    model = await db.rahaza_models.find_one(
        {"$or": [{"id": mid}] if mid else [{"rnd_style_id": d.get("id")}]}, {"_id": 0, "code": 1})
    if mid or model:
        kode = (model or {}).get("code") or d.get("style_code") or ""
        out.append(f"Style sudah dipromosikan menjadi produk {kode} di Master Produk. Untuk menghentikannya, "
                   "nonaktifkan produknya di Portal Produksi › Master Produk.")
    elif await db.marketing_product_launches.count_documents({"style_id": d.get("id")}):
        out.append("Style ini sudah dijadwalkan peluncurannya di Marketing. Batalkan jadwal peluncurannya dulu.")
    return out


daftar(Jenis(
    kode="rnd-style", label="Style R&D", portal="rnd", koleksi="dewi_rnd_styles", modul="rnd-design-hub",
    status_setuju=("approved_for_launch",), kembali_ke="pending_owner_review", label_kembali="menunggu keputusan owner",
    izin=("management.manage", "rnd.approve"), peran_lama=("owner", "admin", "superadmin"),
    hapus_field=("owner_review_result", "owner_reviewed_by", "owner_reviewed_by_id", "owner_reviewed_at",
                 "owner_review_notes"),
    nama=lambda d: f"{d.get('style_code') or ''} {d.get('style_name') or ''}".strip(),
    pemohon=lambda d: d.get("submitted_for_review_by_id") or d.get("created_by_id"),
    penyetuju=lambda d: d.get("owner_reviewed_by_id"),
    waktu_setuju="owner_reviewed_at",
    hambatan=_hambatan_style,
))


# Jenis lain per domain (masing-masing memanggil `daftar(...)` saat diimpor).
from core import batal_setuju_sdm  # noqa: E402,F401
from core import batal_setuju_operasi  # noqa: E402,F401
from core import batal_setuju_keuangan  # noqa: E402,F401
