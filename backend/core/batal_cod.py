"""core/batal_cod.py — mengenali pesanan COD yang batal dari data impor Seller Center (fungsi murni).

18 Nov 2026 (owner: "tambahkan berkas batal cod … nanti muncul ke data mana saya ikuti rekomendasi anda").
Data batal COD TIDAK butuh berkas baru: ekspor pesanan Seller Center (Pesanan Marketplace / Status Pengiriman-
Pembatalan) sudah membawa metode bayar ("Bayar di tempat", "COD (Bayar di Tempat)"), status batal, dan alasan
batal ("Pengiriman paket gagal", "Dibatalkan secara otomatis oleh sistem Shopee. Alasan: Pengiriman gagal").
Di VPS 18 Nov: 22.953 pesanan, 17.883 COD. Yang belum ada hanya TAMPILANNYA — Monitoring kirim › Batal COD.

Jenis batal COD:
  · gagal_kirim   — paket gagal diantar / ditolak pembeli (ongkir pulang, barang kembali ke gudang);
  · batal_pembeli — pembeli membatalkan sebelum dikirim (ubah alamat/ukuran, tidak perlu lagi, ongkir mahal …);
  · lainnya       — alasan lain / kosong.
"""
from __future__ import annotations

import re

_COD = re.compile(r"\bcod\b|bayar di tempat|cash on delivery|bayar ditempat", re.I)
_GAGAL = ("gagal", "ditolak", "tidak berhasil", "failed", "reject", "tidak dapat dihubungi",
          "tidak bisa dihubungi", "alamat tidak ditemukan", "paket kembali", "dikembalikan ke penjual",
          "return to sender", "rts")
_PEMBELI = ("pembeli", "buyer", "tidak perlu", "perlu mengubah", "ubah", "ongkir", "harga", "terjangkau",
            "berubah pikiran", "salah pesan", "terlalu lama", "lama dikirim", "duplikat")

JENIS_LABEL = {"gagal_kirim": "Gagal kirim / ditolak", "batal_pembeli": "Dibatalkan pembeli", "lainnya": "Lainnya"}


def is_cod(order: dict | None) -> bool:
    """Pesanan dibayar di tempat (COD) menurut metode bayar hasil impor."""
    return bool(_COD.search(str((order or {}).get("payment_method") or "")))


def alasan_batal(order: dict | None) -> str:
    o = order or {}
    return str(o.get("cancel_reason") or o.get("cancelation_return_type") or o.get("return_type_raw") or "").strip()


def jenis_batal_cod(order: dict | None) -> str:
    """gagal_kirim | batal_pembeli | lainnya — dari alasan batal (gagal kirim diperiksa lebih dulu)."""
    a = alasan_batal(order).lower()
    if not a:
        return "lainnya"
    if any(k in a for k in _GAGAL):
        return "gagal_kirim"
    if any(k in a for k in _PEMBELI):
        return "batal_pembeli"
    return "lainnya"


def persen(bagian: int, total: int) -> float:
    return round(bagian / total * 100, 1) if total else 0.0
