"""Definisi dataset katalog data Asisten AI (Tahap E, K1) — satu modul per domain.

Setiap modul mengekspor ``DATASET`` (tuple :class:`core.asisten_ai.katalog_data.Dataset`) dan dimuat otomatis oleh
``katalog_data.muat_katalog``. Aturan menulis dataset baru:

* nama koleksi & field WAJIB diverifikasi dari kode penulisnya (routes/core), sebutkan berkasnya di komentar;
* angka bisnis mengikuti pembaca resmi yang sudah ada dan definisinya ditulis di ``catatan`` supaya AI membacanya
  benar (mis. omzet = ``core.ukuran_penjualan``);
* data pribadi (pembeli, alamat, HP, NIK, rekening, kata sandi, token) TIDAK PERNAH masuk katalog; gaji hanya
  dengan ``rahasia="gaji"``; nama orang/vendor/pelanggan memakai ``samaran``;
* akses mengikuti portal/modul layar asal datanya.
"""
