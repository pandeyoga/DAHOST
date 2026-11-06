"""core.margin — SATU rumus margin untuk seluruh aplikasi.

2026-11-06 (Tahap 2, keputusan owner): **margin = (harga jual − HPP) ÷ harga jual**, di mana pun
(kalkulator R&D, katalog, HPP per potong, viewer produk, laporan, estimasi AI). Dulu ada dua arti:
"margin atas harga jual" dan "markup atas HPP" (HPP × persen) — angka 30% di dua layar berarti
dua hal berbeda. Semua pemanggil memakai fungsi di sini; jangan menulis rumus margin sendiri.

Fungsi murni (tanpa DB), diuji di `tests/unit/test_tahap2_hpp.py`.
"""
from __future__ import annotations


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def margin_pct(price, hpp, nd: int = 2):
    """Persen margin atas harga jual; None bila harga jual atau HPP belum diketahui (bukan 0/100)."""
    p, h = _f(price), _f(hpp)
    if p <= 0 or h <= 0:
        return None
    return round((p - h) / p * 100.0, nd)


def margin_of(price, hpp, nd: int = 2) -> dict:
    """Rincian margin: nilai rupiah, persen atas harga jual, dan apakah bisa diukur."""
    p, h = _f(price), _f(hpp)
    if p <= 0:
        return {"margin": 0.0, "margin_pct": 0.0, "has_price": False, "margin_known": False}
    if h <= 0:
        return {"margin": 0.0, "margin_pct": 0.0, "has_price": True, "margin_known": False}
    return {"margin": round(p - h, 2), "margin_pct": round((p - h) / p * 100.0, nd),
            "has_price": True, "margin_known": True}


def price_for_margin(hpp, target_pct) -> float:
    """Harga jual agar margin (atas harga jual) = target: HPP ÷ (1 − target)."""
    h, t = _f(hpp), _f(target_pct)
    if h <= 0:
        return 0.0
    if t <= 0 or t >= 100:
        return round(h, 2)
    return round(h / (1.0 - t / 100.0), 2)
