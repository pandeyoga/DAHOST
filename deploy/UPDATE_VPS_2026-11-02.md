# UPDATE VPS — 2026-11-02 (perbaikan audit gelombang 1–2 + tahap 3–4)

Isi update ini (5 commit, branch `fix/audit-2026-11-perbaikan-pasti` → `main`):
1. Gelombang 1: akses data, keuangan, persediaan, marketing, SDM, AI (Anthropic), notifikasi.
2. Gelombang 2: retur/marketplace (K1–K8), Bagan Akun ber-penanda wiring, WAC barang jadi,
   pengiriman buyer, notifikasi "Perlu Tindakan".
3. Tahap 3: barcode SSOT, satu mesin opname (K9), **Scan Keluar Penjualan harian (K15)**,
   Retur Pembelian + Nota Debit (K11), Retur Material (K10).
4. Tahap 4: input uang dengan titik ribuan otomatis (No.45), semua tanggal WIB (No.54a).

Tidak ada variabel `.env` baru yang WAJIB. `ANTHROPIC_API_KEY` opsional — boleh juga diisi admin di
**Adm. Sistem › Integrasi & API Keys** (diutamakan). Kosong = fitur AI nonaktif dengan pesan ramah.

## A. Update kode (salin berurutan)
```bash
ssh root@<IP-VPS>
cd /opt/dahost

# 0) pastikan VPS mengikuti branch main
git rev-parse --abbrev-ref HEAD          # harus: main

# 1) backup database (WAJIB — ada migrasi data di bagian B)
bash deploy/backup.sh
ls -lh deploy/backups | tail -3          # catat nama berkas backup terbaru

# 2) ambil kode terbaru + build ulang + indeks MongoDB
bash deploy/update.sh
git log -1 --oneline                     # harus: b72caf9 Tahap 4: input uang ... (atau merge commit-nya)

cd /opt/dahost/deploy

# 3) cek sehat
docker compose --env-file .env ps
docker compose --env-file .env logs --tail=40 backend
docker compose --env-file .env exec -T backend python -c "import anthropic; print('anthropic', anthropic.__version__)"
```

## B. Migrasi data — SEMUA pratinjau dulu, `--terapkan` hanya setelah hasilnya dibaca
Semua skrip **bawaan = pratinjau (tidak menulis apa pun)**. Jalankan berurutan; kirim keluaran
pratinjau ke Claude bila ada yang janggal sebelum `--terapkan`.

```bash
cd /opt/dahost/deploy
X="docker compose --env-file .env exec -T backend python /app/scripts"

# B1) K33 — izin Laporan Eksekutif untuk peran Manajemen/Keuangan (supaya akses tidak hilang). Idempoten.
$X/migrate_fin_exec_report_perm.py
$X/migrate_fin_exec_report_perm.py --terapkan

# B2) K6 — lepas reservasi stok order manual lama (stok jual yang "hilang").
$X/release_manual_order_reservations.py
$X/release_manual_order_reservations.py --terapkan

# B3) No.26a — WAC awal barang jadi. JALANKAN SEBELUM gudang memakai Scan Keluar Penjualan
#     (HPP per scan memakai WAC ini). Baca bagian "lapisan Rp 0" di pratinjau.
$X/migrate_fg_wac_init.py
$X/migrate_fg_wac_init.py --terapkan

# B4) Barcode barang jadi = SKU — audit kode FG (kosong, kembar, tidak bisa dicetak).
$X/check_fg_barcodes.py
$X/check_fg_barcodes.py --terapkan        # hanya mengisi kode FG yang KOSONG

# B5) Rapikan 3 kode kain berspasi (KN-RTW- TIDAK digabung: ternyata warna BEIGE, barang lain).
$X/tidy_material_codes.py
$X/tidy_material_codes.py --terapkan      # kode lama tetap terbaca scanner (alias)

# B6) Kode rak/bin > 18 karakter dipendekkan (label lama tetap terbaca lewat alias).
$X/shorten_bin_codes.py
$X/shorten_bin_codes.py --terapkan

# B7) K8 — isi catalog_id item katalog yang COCOK pasti (laporan CSV untuk sisanya).
$X/match_catalog_sku.py
$X/match_catalog_sku.py --terapkan

# B8) K18 — tautkan Portal Aset ke registri aset Keuangan (aset belum tertaut belum bisa dicetak labelnya).
$X/migrate_portal_aset_link_finance.py
$X/migrate_portal_aset_link_finance.py --terapkan
#     opsional, KEPUTUSAN OWNER: daftarkan aset tanpa pasangan sebagai saldo awal (tanpa jurnal perolehan)
# $X/migrate_portal_aset_link_finance.py --terapkan --buat-saldo-awal --golive YYYY-MM-DD

# B9) K7 — hapus data DEMO (backup JSON ditulis lebih dulu). Baca daftar "ragu" — itu TIDAK dihapus.
$X/cleanup_demo_data.py
$X/cleanup_demo_data.py --terapkan
```

## C. Cek setelah update
- **Gudang › Scan Keluar Penjualan › Kontrol**: "Langkah 2" (potong stok dari impor Seller Center) harus MATI.
  Menyalakan keduanya memotong stok & HPP dua kali.
- **Keuangan › Bagan Akun**: akun berpenanda "terhubung" jangan dihapus.
- Ketik nominal di form mana pun (mis. Transfer Bank): titik ribuan muncul sendiri.
- Tanggal bawaan form = hari ini WIB (juga pukul 00:00–06:59).

## Catatan
- Langkah B dapat dijalankan bertahap; tiap skrip idempoten (aman dijalankan ulang).
- Kembali bila bermasalah (kode + data sebelum update ini):
  ```bash
  cd /opt/dahost && git reset --hard 81d2b25
  cd deploy && docker compose --env-file .env build && docker compose --env-file .env up -d
  cd /opt/dahost && bash deploy/backup.sh restore deploy/backups/<berkas-langkah-1>.archive.gz
  ```
  (`update.sh` jangan dipakai untuk kembali — ia selalu menarik `origin/main` terbaru.)
