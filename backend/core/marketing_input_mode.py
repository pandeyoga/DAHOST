"""core.marketing_input_mode — CARA INPUT OMZET per toko (keputusan owner Q-5, 9 Nov 2026).

Masalah (audit Marketing §4 & M-17): toko yang omzetnya diimpor dari pesanan Seller Center tetap
mendapat tugas harian "Input Sales" dan tetap boleh mengetik rekap manual. Saat pesanan hari itu
diimpor, angka ketikan diganti turunan pesanan — kerja dobel, dan angka lamanya hilang.

Aturan sekarang (satu tempat):
  * ``impor_pesanan`` — omzet harian HANYA dari pesanan yang diimpor. Rekap total manual ditolak
    (SPV tetap bisa mengganti angka lewat jalur override yang beralasan). Tidak ada tugas input
    manual; bila pesanan H-1 belum diimpor, PIC mendapat pengingat impor.
  * ``rekap_manual`` — toko tanpa ekspor pesanan (WA/offline/platform tanpa ekspor): rekap harian
    diketik/diimpor sebagai rekap, tugas input harian tetap dibuat.

Toko yang belum memilih: dianggap ``impor_pesanan`` bila PERNAH punya pesanan hasil impor,
selain itu ``rekap_manual`` (perilaku lama untuk toko manual tidak berubah).
"""
from __future__ import annotations

from typing import Optional

IMPOR = "impor_pesanan"
MANUAL = "rekap_manual"
MODES = (IMPOR, MANUAL)
LABEL = {IMPOR: "Impor pesanan (omzet dari pesanan Seller Center)",
         MANUAL: "Rekap manual (omzet harian diketik / impor rekap)"}
OPTIONS = [{"value": k, "label": LABEL[k]} for k in MODES]
IMPORT_TYPES = ("marketplace_orders", "orders")


def valid(mode: Optional[str]) -> bool:
    return mode in MODES


async def mode_toko(db, account: Optional[dict]) -> str:
    """Mode efektif satu toko (pilihan tersimpan, kalau tidak diturunkan dari data)."""
    acc = account or {}
    m = acc.get("sales_input_mode")
    if valid(m):
        return m
    if not acc.get("id"):
        return MANUAL
    hit = await db.marketing_orders.find_one(
        {"account_id": acc["id"], "_import_source_type": {"$in": list(IMPORT_TYPES)}},
        {"_id": 0, "id": 1})
    return IMPOR if hit else MANUAL


def pesan_tolak_manual(account: dict, date: str) -> str:
    return (f"Toko '{account.get('account_name') or ''}' memakai cara input 'Impor pesanan': omzet "
            f"{date} dihitung dari pesanan yang diimpor, bukan diketik. Impor ekspor pesanan Seller "
            "Center hari itu (menu Impor Data). Kalau toko ini memang tidak punya ekspor pesanan, "
            "minta SPV mengganti cara input toko menjadi 'Rekap manual' di Kelola Akun; untuk "
            "membetulkan satu hari, SPV memakai 'Ganti Angka (Override)' dengan alasan.")
