# Cara mengaudit & merapikan UI satu portal

Dipakai untuk Portal Keuangan (4 Nov 2026). Langkahnya sama untuk portal lain: `hr`, `production`, `warehouse`, `sales`, `toko`, dst. Daftar portal: `python3 scripts/ui_audit/scan_ui.py --list-portals`.

Ada tiga lapis pemeriksaan. Setiap lapis menangkap hal yang tidak tertangkap lapis lain:

| Lapis | Alat | Menangkap | Tidak menangkap |
|---|---|---|---|
| 1. Kode | `scripts/ui_audit/scan_ui.py` | pola di kode: tombol ghost+border, `font-mono`, warna mentah, `<select>`/`type="month"`, `window.confirm`, kata Inggris, judul/tab buatan | hasil CSS akhir, isi data |
| 2. Layar | `scripts/ui_audit/dom_audit.js` | yang benar-benar tampil: tombol tanpa latar, kartu di dalam kartu, baris laporan jadi kartu, nol merah, tanggal mentah, kode mentah, format tabel berbeda, isi tertutup tombol chat, tinggi tombol berbeda | rasa/kepatutan (perlu mata manusia) |
| 3. Mata | daftar periksa di bawah | isi ganda antarmenu, urutan yang membingungkan, kata yang tidak dipahami pengguna | — |

Kode aturan sama di ketiganya dan di [PANDUAN_UI.md](PANDUAN_UI.md).

## Langkah 1 — pindai kode

```bash
python3 scripts/ui_audit/scan_ui.py --portal hr --md docs/design/audit_hr.md
```

Hasilnya laporan per aturan, lengkap dengan berkas dan nomor baris. Berkas yang diperiksa adalah layar yang dibuka dari menu portal itu, ditambah komponen yang diimpornya (sampai 2 tingkat).

## Langkah 2 — periksa layar

1. Jalankan app (lokal), masuk sebagai admin, lalu buka layar 1440×900.
2. Ambil daftar menu:
   ```bash
   python3 scripts/ui_audit/scan_ui.py --portal hr --ids
   ```
3. Buka DevTools › Console, tempel isi `scripts/ui_audit/dom_audit.js`, lalu:
   ```js
   await uiAuditMenus(["hr-employees", "hr-attendance-hub" /* … hasil langkah 2 */])
   copy(window.__uiAuditResult)   // salin hasil lengkap per layar
   ```
   `uiAuditMenus` membuka setiap menu **dan setiap tab hub-nya**, lalu memeriksa layar. Untuk satu layar saja: `await uiAudit()`.
   Kalau dijalankan lewat Claude, alat browser punya batas 45 detik per panggilan. Jalankan dengan `uiAuditMenus([...]).then(...)` lalu tunggu, atau bagi per 5–8 menu.
4. Baca `total` (jumlah per aturan) dan `per_layar[i].samples` (contoh elemen). `metrics.tabel` menunjukkan format tiap tabel; lebih dari satu format di portal yang sama = `TABEL-GAYA-BEDA`.

Bila ada layar gagal dimuat, audit mencatat `LAYAR-ERROR` (layar error menutupi semua temuan lain — perbaiki dulu).

Catatan salah tangkap yang wajar:
- `TEKS-INGGRIS` ikut menandai **data** ("Supplier Aksesoris…" adalah nama pemasok).
- `TERTUTUP-CHAT` tergantung posisi gulir.

Periksa contohnya sebelum memperbaiki.

## Langkah 3 — daftar periksa mata (per layar)

1. Apakah ada isi yang sama dengan menu/tab lain (angka, rekening koran, saldo per pemasok)?
2. Apakah tombol utama hanya satu dan jelas?
3. Apakah judul, tab, dan tombol semuanya bahasa Indonesia, dengan huruf besar hanya di awal?
4. Apakah kartu dipakai sesuai G5 (bukan untuk tiap baris atau satu angka)?
5. Apakah ada periode bawaan, dan tertulis rentangnya?
6. Apakah tampilan kosong memberi langkah berikutnya?
7. Apakah layar masih terbaca di tema gelap?

## Langkah 4 — perbaiki

Pertama kali di Portal Keuangan (4 Nov 2026), sesudah perbaikan, audit layar 46 layar turun dari ±1.700 temuan menjadi
tinggal temuan kecil dan salah tangkap data. Lihat laporan di artifact "Konsistensi UI Keuangan".

0. **Perbaikan tombol massal** (aman, bisa dipratinjau):
   ```bash
   python3 scripts/ui_audit/fix_buttons.py --portal hr          # pratinjau
   python3 scripts/ui_audit/fix_buttons.py --portal hr --apply  # tulis
   ```
   Mengubah ghost+garis → outline, muat ulang bertulisan → ikon, tinggi manual → prop `size`, label Inggris tombol.

1. **Komponen bersama dulu** (lihat "Yang harus dibersihkan" di PANDUAN_UI.md). Banyak temuan hilang sekaligus.
2. Lalu per layar, dari aturan yang paling terlihat:
   - `TOMBOL-TANPA-LATAR`, `BARIS-JADI-KARTU`, `KARTU-DI-DALAM-KARTU`;
   - `TAB-*`, `PERIODE-GANDA`, `FILTER-BERTUMPUK`;
   - `TANGGAL-MENTAH`, `KODE-MENTAH`, `TEKS-INGGRIS`;
   - `ANGKA-MONO`, `WARNA-MENTAH`.
3. Ulangi langkah 1–2. Setelah bersih, kunci angkanya supaya tidak memburuk:
   ```bash
   python3 scripts/ui_audit/scan_ui.py --portal hr --set-baseline
   ```
   Tambahkan `python3 scripts/ui_audit/scan_ui.py --portal hr --gate` ke langkah gate di `.github/workflows/ci.yml`.
