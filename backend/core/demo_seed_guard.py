"""Penjaga tombol "Muat Demo" (2026-11-07, Tahap 5).

Beberapa layar SDM (Struktur Organisasi, Rekrutmen, Onboarding, Pembelajaran) punya endpoint `/seed` yang
MENGHAPUS SELURUH isi koleksinya (`delete_many({})`) lalu mengisi data contoh — satu klik tanpa tanya, dan
endpoint-nya terbuka untuk semua pengguna yang login. Data nyata (mis. Struktur Organisasi yang kini menjadi
master departemen & jabatan Data Karyawan) bisa hilang. Aturannya sekarang satu: data contoh hanya boleh
dimuat ke koleksi yang masih KOSONG.
"""
from fastapi import HTTPException


async def ensure_empty_for_demo(db, collections, label: str) -> None:
    """Tolak (409) bila salah satu koleksi sudah berisi data."""
    for name in collections:
        if await db[name].count_documents({}):
            raise HTTPException(
                409, f"{label} sudah berisi data. Data contoh hanya bisa dimuat bila masih kosong — "
                     "data yang ada tidak dihapus.")


def demo_seed_enabled() -> bool:
    """2026-11-07 (Asisten AI, audit §3.C #4) — data contoh OTOMATIS hanya boleh ditulis
    bila lingkungan ini memang lingkungan demo (``ALLOW_DEMO_SEED=true``, aturan yang sama
    dengan ``auth.require_demo_seed_allowed``). Dulu iklan/live/kesehatan akun diisi data
    acak setiap kali koleksinya kosong — di produksi pun — dan angka acak itu terbaca
    sebagai biaya iklan & ROAS sungguhan oleh layar maupun AI."""
    import os
    return os.environ.get("ALLOW_DEMO_SEED", "false").strip().lower() in ("true", "1", "ya", "yes")
