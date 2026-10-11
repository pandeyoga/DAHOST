# UPDATE VPS — Sinkron master data konsolidasi (2026-09-23)

## Prinsip (permintaan owner)
- **Tidak menghapus** data lain yang sudah diisi di VPS (stok, order, keuangan, user, foto/berat/SOP model).
- **Tidak menduplikasi**: dokumen dicari lewat kunci alami (kode material, SKU, model+warna+ukuran+versi BOM,
  kode style, kode warna/ukuran) — data awal yang belum lengkap di VPS **diperbarui**, bukan ditambah lagi.
- Harga potongan kain (CUT-*) = **Rp 0 / unvalued** sampai ada hasil Order Cutting nyata
  (harga = total kain terpakai ÷ jumlah potongan). Biaya standar (qty kain × harga kain) DIMATIKAN
  (`core/master_fill.py recalc_standard_costs`). HPP 98 model berstatus `menunggu_cutting` (jujur, bukan angka basi).

## Berkas
- Ekspor master: `private/konsolidasi_master_20260923.json.gz` (juga `/downloads/konsolidasi_master_20260923.json.gz`) —
  11 koleksi: colors 105 · sizes 8 · materials 2163 · models 104 · variants 807 · boms 807 · rnd_styles 104 ·
  rnd_variants 806 · tech_packs 104 · rnd_materials 12 · cost_history 311.
- Skrip: `scripts/vps/sync_konsolidasi.py` (export | import --dry-run | import).

## Langkah di VPS
1. Backup: `mongodump --uri "$MONGO_URL" --db "$DB_NAME" --gzip --archive=/backup/pre_sync_$(date +%F).archive.gz`
2. Salin repo terbaru (git pull) + berkas `.json.gz` ke VPS; `pip install -r backend/requirements.txt`.
3. Pratinjau: `cd backend && MONGO_URL=... DB_NAME=... python ../scripts/vps/sync_konsolidasi.py import --file /path/konsolidasi_master_20260923.json.gz --dry-run`
   → baca ringkasan per koleksi: `baru` (akan ditambah) · `ditimpa` (material/BOM/warna/ukuran) · `digabung`
   (model/varian/R&D: hanya kolom konsolidasi) · `DUPLIKAT_DI_VPS` (kunci alami ganda yang SUDAH ada di VPS — rapikan manual dulu).
4. Terapkan (tanpa `--dry-run`). Log tersimpan di koleksi `sync_log`.
5. Restart backend VPS; rebuild frontend (`bash scripts/rebuild_frontend.sh`).
6. Bukti: `python scripts/laporan_kekosongan_bom.py` → 0 model kurang; Papan Temuan Audit tampil; CUT-* semua Rp 0.

## Urutan bila owner masih mengisi data (kain TBD, kancing warna baru)
Isi di lingkungan ini (atau kirim berkas) → jalankan ulang `export` → `import` lagi di VPS. Kunci alami yang sama
membuat pengulangan aman (idempoten).
