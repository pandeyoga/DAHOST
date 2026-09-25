# UPDATE VPS — 2026-09-23 (nomor otomatis Produksi/Maklon · stok boleh minus · master data terbaru)

Repo: `pandeyoga/DAHOST` (push lewat tombol **Save to GitHub** di chat, branch `main`).
Direktori VPS: `/opt/dahost` (docker compose di `/opt/dahost/deploy`).

## Yang masuk di update ini
- **(2026-09-24 b)** Dropdown pilihan (lokasi, dll.) tidak lagi terpotong modal — membuka ke atas bila ruang kurang. Permintaan material
  tambahan dari vendor CMT: aksesoris KURANG hasil inspeksi ikut tampil di form persetujuan (qty bisa diubah) dan ikut dikirim di child
  shipment → inspeksi child oleh vendor menampilkan aksesorisnya.
- **(2026-09-24)** Pengeluaran Material: lokasi ambil terisi OTOMATIS (stok terbanyak → gudang bawaan; karantina/QC tidak pernah dipilih),
  submit tidak lagi ditolak karena lokasi kosong. Toggle **Progress Produksi Wajib MI issued (GDG-2)** di Konfigurasi Sistem → tab
  *Produksi* — bawaan **OFF** sementara (progress job internal boleh diinput tanpa Material Issue). Nyalakan bila alur gudang sudah rapi.
- Kode: semua nomor PO Produksi/Maklon, Shipment Vendor, Permak, Retur otomatis + pratinjau di form;
  mode sementara **Stok Boleh Minus** (`inventory_allow_negative`, bawaan ON) untuk Kirim Material CMT,
  Pengeluaran Material, Cutting; tab **Stok Minus** di Gudang → Stok & Akurasi; 30 temuan audit selesai;
  Papan Temuan Audit; anti-ChunkLoadError.
- Data: `scripts/vps/data/konsolidasi_master_latest.json.gz` (ekspor 2026-09-23 18:11 UTC) — 11 koleksi master:
  warna 105 · ukuran 8 · material 2163 (CUT-* harga 0) · model 104 · varian 807 · BOM 807 · R&D style 104 ·
  varian R&D 806 · tech pack 104 · material R&D 12 · riwayat harga 311.
  Sinkron memakai **kunci alami** → tidak menghapus stok/order/keuangan/user, tidak menduplikasi.

## Saldo awal kas & bank (2026-09-24, dari saldo_erp.xlsx) — jalankan SEKALI setelah update kode
```bash
cd /opt/dahost/deploy
docker compose --env-file .env exec -T backend python /app/scripts/saldo_awal_bank_20260924.py --dry-run   # pratinjau
docker compose --env-file .env exec -T backend python /app/scripts/saldo_awal_bank_20260924.py             # terapkan
```
Isi: ganti nama 1-1219 → Bank BCA – CV Dewi Aditya Official; nonaktifkan 1-1215 (Dewi Ratnasari, catatan owner);
4 rekening baru saldo 0 (Imam Sudha, Dhira Arkhani, Tutut Nurul F, Basah Purba K); no. rekening & atas nama per akun;
SATU jurnal pembuka Rp 585.418.930 (Debit 9 bank, Kredit 3-2000 Laba Ditahan). Idempoten — bila jurnal pembuka sudah ada, dilewati.
Pencatatan harian selanjutnya: Portal Keuangan → Akuntansi → Jurnal → tab **Impor Jurnal (Excel)** (unduh template di sana).

## Perintah di terminal VPS (urut, salin-tempel)
```bash
ssh root@<IP-VPS>
cd /opt/dahost

# 1. backup penuh (deploy/backups/<db>-<tanggal>.archive.gz, disimpan 14 hari)
bash deploy/backup.sh

# 2. tarik kode terbaru dari GitHub, build ulang image, restart, pasang indeks
bash deploy/update.sh

# 3. pratinjau sinkron master data (tidak menulis apa pun) — baca ringkasan per koleksi:
#    baru / ditimpa / digabung / DUPLIKAT_DI_VPS (kalau ada DUPLIKAT_DI_VPS, rapikan dulu sebelum langkah 4)
bash deploy/sync_master.sh --dry-run

# 4. terapkan (backup otomatis lagi → import → restart backend)
bash deploy/sync_master.sh

# 5. cek sehat
docker compose -f deploy/docker-compose.yml --env-file deploy/.env ps
docker compose -f deploy/docker-compose.yml --env-file deploy/.env logs --tail=50 backend
curl -fsS https://<DOMAIN>/api/health && echo " OK"
```

## Verifikasi di aplikasi (login superadmin)
1. Administrasi Sistem → Penomoran Dokumen: *PO Produksi Internal (SPP)* dan *Shipment Vendor* bermode **Otomatis**.
2. Portal Produksi → Kirim Material CMT → Buat Shipment Normal: kolom nomor menampilkan `SHP-YYYYMM-0001`;
   panel material berwarna kuning "akan MINUS" (stok belum opname) — surat jalan tetap bisa dibuat.
3. Gudang → Stok & Akurasi → tab **Stok Minus**: banner "Mode AKTIF"; baris minus muncul setelah pengeluaran pertama.
4. Portal Maklon → Konfigurasi → tab **Gudang & Stok**: toggle *Stok Boleh Minus* — **matikan setelah stock opname selesai**.
5. R&D → Papan Kelengkapan: 0 model kurang BOM; Administrasi → Papan Temuan Audit: 30 temuan (29 selesai · 1 diterima).

## Kembali bila ada masalah
```bash
cd /opt/dahost && bash deploy/backup.sh restore deploy/backups/<nama-berkas-backup-langkah-1>.archive.gz
git -C /opt/dahost checkout <commit-sebelumnya> && bash deploy/update.sh
```

## Catatan
- Sinkron idempoten: menjalankan `sync_master.sh` dua kali aman (ditimpa dengan isi yang sama).
- Bila owner masih menambah data master di lingkungan pengembangan: jalankan ulang
  `python scripts/vps/sync_konsolidasi.py export --file scripts/vps/data/konsolidasi_master_latest.json.gz`,
  Save to GitHub, lalu ulangi langkah 2–4 di VPS.
- Menghapus surat jalan material TIDAK mengembalikan stok/MI (perilaku lama) — betulkan lewat opname/penyesuaian.
