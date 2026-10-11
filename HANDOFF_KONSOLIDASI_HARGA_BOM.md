# HANDOFF — Sesi berikutnya: KONSOLIDASI HARGA MATERIAL & BOM (owner sudah mengisi berkas)

> **Bahasa:** balas owner dalam Bahasa Indonesia. Baca ini dulu, lalu `memory/PRD.md` (3 entri teratas, 2026-09-23) dan
> `memory/LAPORAN_KEKOSONGAN_BOM_2026-09-23.md`. Jangan mulai dari nol — semua alat sudah ada.

## 1. Situasi
Owner (CV. Dewi Aditya) sedang membenahi master data sebelum go-live: **(a) harga material yang salah input** membengkakkan HPP,
**(b) BOM aksesoris 42 model belum lengkap**. Sesi 2026-09-23 menghasilkan dua berkas Excel untuk diisi owner, dan owner
menyatakan **"saya sudah isi beberapa data, di sesi berikutnya ingin saya konsolidasikan"**. Tugas sesi berikutnya = menerima
berkas yang sudah diisi owner, memeriksa, menerapkan ke DB, lalu membuktikan HPP & kelengkapan BOM membaik.

## 2. Berkas yang dikirim ke owner (owner mengunggah balik salah satu/keduanya)
| Berkas | Dibuat oleh | Isi yang diisi owner | Cara menerapkan |
|---|---|---|---|
| `REVIEW_HARGA_MATERIAL_DA.xlsx` | `GET /api/rahaza/master/harga-review` (`core/harga_review.py`) | sheet **MATERIAL** kolom `satuan_beli`, `isi_per_satuan_beli`, `harga_per_satuan_beli` (kolom F/G/H). Kolom bantu di kanan (L–T) diabaikan importir | `POST /api/rahaza/master/fill-preview` → `POST /api/rahaza/master/fill-apply?scope=all` |
| `DATA_YANG_PERLU_DIISI_DA_FOKUS_dari_DA3.xlsx` | `POST /api/rahaza/master/gap-fokus` dengan berkas klien DA (3) (`core/gap_fokus.py`) | sel KUNING di **VARIAN_BARU** (kolom `ukuran`, 20 model tanpa SKU), **BOM_AKSESORIS** (kolom `varian`, 42 kelompok; qty/satuan), **MATERIAL**. Sheet **BOM_OTOMATIS** (tebakan biru) ikut diterapkan bila dibiarkan | `fill-preview` → `fill-apply?scope=bom` (hanya VARIAN_BARU+BOM) atau `scope=all` |
Owner juga bisa mengunggah lewat UI: Portal Keuangan → Akuntansi → Master Akuntansi → tab **Impor Harga · Rekening · BOM**
(`RahazaMasterFillModule.jsx`; tombol `fill-download-harga-review`, `fill-download-fokus`, `fill-file`, `fill-apply`, `fill-apply-all`).
Berkas sumber owner (gitignored, ada di pod ini saja): `private/golive/DATA_YANG_PERLU_DIISI_DA_3.xlsx`, `private/golive/REVIEW_HARGA_MATERIAL_DA.xlsx`.
Salinan publik: `frontend/public/downloads/` (juga `frontend/build/downloads/`).

## 3. Kondisi DB — SESUDAH KONSOLIDASI 2026-09-23 (lihat `memory/LAPORAN_KONSOLIDASI_2026-09-23.md`)
- 104 model aktif · 807 varian (777 aktif) · 807 BOM (777 aktif, semua versi 1) · 807 potongan CUT-* · 0 model kurang BOM (98 lengkap · 6 dihentikan).
- Harga 515 material sudah = isian owner (`revisihargaaksesoris.xlsx`); 251 ganti satuan dasar (kancing pcs, bisban/karet cm, benang kg). Sisa: A-TLK-0001 harga 0; 25 kain `KN-TBD-*` Rp 0.
- HPP 21 model belum terbit (potongan baru belum bernilai — menunggu Portal Cutting). Skrip ulang: `scripts/konsolidasi/konsolidasi.py` (dry-run / `--apply`, idempoten untuk BOM).
- Backup sebelum: `private/pre_konsolidasi_20260923.archive.gz`.

### 3-lama. Kondisi DB SEBELUM konsolidasi (angka acuan lama)
- 104 model aktif · 645 varian (615 aktif) · 634 BOM (604 aktif) · 515 material aksesoris/kain (+596 potongan CUT-*).
- **BOM:** 56 lengkap · 6 dihentikan · **42 harus diisi** (20 tanpa SKU · Ona nol BOM · Hanny/Hanni · 18 BOM tanpa aksesoris · Lyora 1 varian).
  Cek ulang kapan saja: `cd /app/backend && set -a && . .env && set +a && python ../scripts/laporan_kekosongan_bom.py`.
- **Harga MERAH (4):** A-REN-0004 Renda Rajut Rp 328.900/m (Ochi DA-4104 HPP 515.151) · A-KRT-0007 Karet Sepul Rp 33.000/m (Onella DA-1505–1508, Fella DA-4501–4504 HPP 87–143 rb) ·
  A-BIS-0001/0002 Bisban Rp 15.400/m (Lyora). Pola: **harga 1 ROLL ditulis sebagai harga per METER**. 154 KUNING = harga 0 / isi kemasan roll·pack·gross belum diisi (benang dsb.).
- HPP model dihitung dari baris BOM: `qty_base × unit_cost_base` (kain lewat potongan CUT-* = qty kain × harga kain). `apply_materials` memperbarui master + BOM pemakai, `fill-apply` menghitung ulang HPP (`models_hpp_applied`).

## 4. Prosedur konsolidasi (urutan yang disarankan)
1. **Bring-up** (bila pod baru): ikuti `AGENT_QUICKSTART.md`; catatan: `pip install -r requirements.txt` gagal karena pin `litellm`/`emergentintegrations` →
   `grep -vE "^(emergentintegrations|litellm)" requirements.txt > /tmp/r.txt && pip install -r /tmp/r.txt`. DB kosong → `bash scripts/seed_golive_restore.sh`.
   Login `admin@garment.com` / `Admin@123` (rate limit 10/60 dtk). Frontend = static bundle: ubah `frontend/src` → `bash scripts/rebuild_frontend.sh` (±2 menit).
2. **Backup dulu**: `mongodump --db test_database --archive=/app/private/pre_konsolidasi.archive.gz --gzip` (restore cepat bila salah).
3. **Simpan berkas owner** ke `private/golive/` (unduh dari URL artifact yang diberikan owner dengan `curl -L`).
4. **Pratinjau dulu, jangan langsung apply:** `curl -F file=@BERKAS $API/api/rahaza/master/fill-preview` → periksa `ok`, `errors`, `totals`, `materials[]`
   (`unit_cost` baru vs `unit_cost_before`), `bom_issues`, `bom_groups`. Tunjukkan ringkasan ke owner **sebelum** apply bila ada perubahan harga besar (> 5×) atau error.
   Sanity harga: setelah isi, harga per meter bisban/karet/renda wajar Rp 300–3.000/m; benang per roll Rp 7–15 rb; kancing Rp 100–600/pcs; kain Rp 10–120 rb/kg, Rp 5–60 rb/yard.
5. **Terapkan:** harga → `fill-apply?scope=all`; BOM/varian → `fill-apply?scope=bom` (atau `all` bila MATERIAL juga diisi). Simpan response JSON ke `private/golive/apply_<tgl>.json`.
6. **Bukti sesudah:** (a) `scripts/laporan_kekosongan_bom.py` → berapa model masih kurang; (b) `GET /api/rahaza/master/harga-review` → berapa MERAH/KUNING tersisa;
   (c) HPP Ochi/Onella/Fella/Lyora turun ke kisaran wajar (`rahaza_models.hpp`); (d) `GET /api/dewi/rnd/completeness` (papan R&D) konsisten dengan (a).
7. **Berkas sisa untuk owner:** `POST gap-fokus` (dengan berkas owner terbaru) + `GET harga-review` → salin ke `frontend/public/downloads/` & `frontend/build/downloads/`, beri link
   `https://<REACT_APP_BACKEND_URL>/downloads/<nama>`. Perbarui `memory/PRD.md` (entri teratas), `memory/LAPORAN_KEKOSONGAN_BOM_*.md`, dan tabel §3 di berkas ini.
8. **Uji:** `python tests/test_fokus_cakupan_bom.py` (18 cek; mengubah lalu me-restore DB — **jalankan hanya bila DB masih = seed**, atau ubah agar tidak restore) dan testing agent.

## 5. Jebakan yang sudah ditemukan
- Kelengkapan aksesoris kini dinilai **per varian/BOM** (`core/bom_gap.py` `acc_keys`, `variants_without_acc`) — jangan kembali ke cek per model (itulah sebab laporan lama salah: Lyora dan 13 model "sebagian" tampil ✓).
- Berkas DA (3) owner diunggah apa adanya = **0 perubahan** (kelompok tanpa kolom `varian` dilewati; model tanpa SKU menunggu VARIAN_BARU). Tebakan biru (BOM_OTOMATIS) hanya menutup Ona & Freya penuh.
- Kode material di berkas owner kadang mengandung zero-width space (`\u200bA-K22-0014`) — `clean()` di `core/bom_fill.py` sudah menangani; jangan bandingkan string mentah.
- Lyora memakai warna "maroon" yang tidak ada (varian = BURGUNDY); Rachel set "Maron" → typo yang ditebak fuzzy.
- `MATERIAL` importir: bila `satuan_beli` = `satuan_dasar` kemasan (roll/pack/gross) dan `isi > 1` → isi dibaca **pcs per kemasan** dan harga = harga kemasan; bila `satuan_beli` ≠ dasar → `unit_cost = harga ÷ isi` (lihat `core/master_fill.py` baris ~240).
- Jangan jalankan seeder demo; `ALLOW_DEMO_SEED=false`. Setelah uji yang menulis: `bash scripts/seed_golive_restore.sh --force` (atau restore backup langkah 2).

## 6. File kunci
`backend/core/harga_review.py` · `backend/core/gap_fokus.py` · `backend/core/bom_gap.py` · `backend/core/master_fill.py` (parse/apply) · `backend/core/bom_fill.py` (importir BOM) ·
`backend/routes/master_fill.py` (endpoint) · `backend/routes/dewi_rnd_styles.py` (`/completeness`) · `frontend/src/components/erp/finance/RahazaMasterFillModule.jsx` ·
`scripts/laporan_kekosongan_bom.py` · `tests/test_fokus_cakupan_bom.py` · laporan uji `test_reports/iteration_224.json`, `iteration_225.json`.
