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
