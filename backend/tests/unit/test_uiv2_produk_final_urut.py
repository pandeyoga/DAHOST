"""Standar UI/UX v2 (8 Nov 2026): daftar Produk Final diambil per halaman (limit 200 + offset) oleh layar
untuk menghitung ringkasan atas SEMUA produk. Urutan harus punya pemutus unik (`id`) supaya tidak ada
baris yang muncul dua kali / terlewat di antara halaman."""
import os

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_urutan_produk_final_punya_pemutus_id():
    src = open(os.path.join(BACKEND, "routes", "rnd_product_viewer.py"), encoding="utf-8").read()
    assert '[("model_name", 1), ("size_code", 1), ("id", 1)]' in src
