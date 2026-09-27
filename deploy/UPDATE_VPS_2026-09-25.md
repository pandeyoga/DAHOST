# UPDATE VPS — 2026-09-25

Isi update ini:
1. Penarikan saldo platform → semua rekening bank terbaca, menu pindah ke Finance.
2. Pembalik saldo awal kas/bank yang tercatat 2x (`batal_saldo_awal_bank_20260924.py`).
3. Form Marketing wajib memilih dari master (kreator, toko, produk, warna, ukuran).
4. BOM baru sheet `2-BOM` (9 model · 115 SKU) — `import_bom_baru_20260925.py`.
5. Ekspor daftar master untuk stock opname — `export_stock_opname.py`.

Sebelum mulai: tekan **Save to GitHub** di chat (branch `main`).

## Perintah (salin berurutan)
```bash
ssh root@<IP-VPS>
cd /opt/dahost

# 1) backup database
bash deploy/backup.sh

# 2) ambil kode terbaru + build ulang (aman walau riwayat GitHub ditulis ulang)
bash deploy/update.sh
git log -1 --oneline

cd /opt/dahost/deploy

# 3) SALDO AWAL GANDA → jurnal pembalik (nominal sama, D/K ditukar). Idempoten.
docker compose --env-file .env exec -T backend python /app/scripts/batal_saldo_awal_bank_20260924.py             # pratinjau
docker compose --env-file .env exec -T backend python /app/scripts/batal_saldo_awal_bank_20260924.py --terapkan   # posting

# 4) BOM BARU (2-BOM). Baris potongan (CUT-…) di Excel diabaikan — potongan dibuat otomatis, 1 per BOM.
docker compose --env-file .env exec -T backend python /app/scripts/import_bom_baru_20260925.py             # pratinjau
docker compose --env-file .env exec -T backend python /app/scripts/import_bom_baru_20260925.py --terapkan   # tulis

# 5) cek rekening pencairan yang terbaca
docker compose --env-file .env exec -T backend python /app/scripts/cek_rekening_pencairan.py

# 6) ekspor daftar stock opname → salin ke folder deploy, lalu unduh ke laptop
docker compose --env-file .env exec -T backend python /app/scripts/export_stock_opname.py
docker compose --env-file .env cp backend:/app/backups/STOCK_OPNAME_$(date -u +%F).xlsx ./
# di laptop:  scp root@<IP-VPS>:/opt/dahost/deploy/STOCK_OPNAME_*.xlsx .

# 7) cek sehat
docker compose --env-file .env ps
docker compose --env-file .env logs --tail=30 backend
```

## Catatan
- Langkah 3: bila tertulis "TIDAK ditemukan" → skrip saldo awal memang belum pernah jalan di VPS; tidak ada yang dibalik.
- Langkah 4: 20 baris kancing model **DA-1511 (Lika)** qty-nya kosong di Excel → dilewati. Isi qty-nya di BOM editor
  (R&D → BOM) atau kirim Excel revisi lalu jalankan ulang langkah 4 (idempoten, BOM ditimpa dengan isi terbaru).
- Hangtag A-HTG-0003 + Pin A-PIN-0001 (1 pcs) ditambahkan ke BOM yang belum punya (aturan owner semua SKU aktif).
- Kembali bila bermasalah: `bash deploy/backup.sh restore deploy/backups/<berkas-langkah-1>.archive.gz`
