# LAPORAN JUJUR — Model yang BOM/aksesorisnya BENAR-BENAR kosong (2026-09-23)

Sumber: **langsung dari database** (seed go-live = backup VPS + berkas DA (2) diterapkan), dihitung ulang dengan
`scripts/laporan_kekosongan_bom.py` — bukan dari Excel. Kelengkapan dinilai **per varian/BOM**, bukan per model.

## Angka inti (104 model aktif)
| Kondisi | Jumlah | Model |
|---|---|---|
| Lengkap (semua varian punya BOM ber-aksesoris) | **56** | — |
| Dihentikan (semua SKU nonaktif) → tidak perlu BOM | **6** | DA-2104 GIA, DA-2107 Luvia, DA-2108 Maudy, DA-2501 Erlyna, DA-3601 Airyn, DA-3602 Jeslyn |
| **HARUS DIISI** | **42** | rincian di bawah |

### Rincian 42 model yang harus diisi
1. **20 model belum punya SKU (warna+ukuran) sama sekali** → BOM tidak mungkin dibuat sebelum ukuran diisi di VARIAN_BARU:
   DA-1209/1210/1211 Lunara · DA-2112 Heidi · DA-2113 Riana · DA-2506/2507 Azkia · DA-3301/3302 Aruna · DA-3512 0,5 Jenifer ·
   DA-3701/3702 Rasha · DA-4106/4107 Cleo · DA-4305 Arka · DA-4306/4307 Irana · DA-6401 Aro · DA-6901 Inner jersey · DA-7101 Jolie Tunik
2. **1 model punya SKU tapi NOL BOM**: DA-2201 Ona (7 varian)
3. **2 model: semua BOM tanpa aksesoris + 2 dari 13 varian belum punya BOM**: DA-1509 Hanny, DA-1510 Hanni
4. **18 model: BOM ada (hanya potongan kain hasil impor), aksesoris kosong di SEMUA varian**:
   DA-1401 Rachel set · DA-2102/2103 Anna · DA-2202 Freya · DA-2401 Brigitta · DA-3401 Vonny · DA-3504/3505/3506/3507 Thea ·
   DA-3603 Mecca · DA-3604/3605 Victoria · DA-4101/4102 Liana · DA-4201/4202 Nagita top · DA-4203 Ziva
5. **1 model sebagian**: DA-1101 Lyora — varian BURGUNDY BOM-nya tanpa aksesoris (5 varian lain sudah ada).
   **Model ini TERLEWAT di semua laporan sebelumnya** karena logika lama menilai "aksesoris ada" per model, bukan per varian.

## Berkas klien `DATA_YANG_PERLU_DIISI_DA (3).xlsx` — kenapa tidak menutup kekurangan
Berkas itu memuat daftar aksesoris untuk **semua 104 model**, tetapi bila diunggah apa adanya hasilnya **0 perubahan**
(84 kelompok yang diterapkan semuanya milik 57 model yang sudah lengkap → tidak ada yang baru). Untuk 42 model kurang:
- 20 model tanpa SKU → 41 kelompok aksesoris **menunggu** kolom `ukuran` di VARIAN_BARU (kode_warna sudah disarankan).
- 21 model punya >1 kelompok aksesoris tanpa kolom `varian` → sistem tidak tahu kelompok mana untuk warna mana (105 kelompok).
  Sistem menebak warna dari nama kancing ("Kancing … warna Moca") → **tebakan (biru) hanya menutup 2 model penuh (Ona, Freya)**
  dan sebagian 13 model lain; 42 kelompok tetap harus diisi tangan (warna tidak bisa ditebak / typo "Maron", "Grey" bukan varian model itu).
- 1 kelompok Lyora memakai warna "maroon" yang tidak ada di model (BURGUNDY) → dilewati.
- 21 baris satuan tak valid (mis. qty "3 pcs" untuk bahan bersatuan roll tanpa isi/kemasan) + 4 qty kosong.

**Simulasi (DB dipulihkan setelahnya):** unggah DA (3) → tetap 42 kurang. Unggah berkas FOKUS dengan SEMUA tebakan biru diterima →
**masih 40 model kurang** (20 tanpa SKU · 2 Hanny/Hanni · 5 tanpa aksesoris sama sekali · 13 sebagian varian).
Jadi yang **benar-benar harus dikerjakan klien**: 20 model isi ukuran, lalu isi/konfirmasi kolom `varian` untuk 42 kelompok kuning di BOM_AKSESORIS.

## Kesalahan laporan sebelumnya yang sudah diperbaiki di kode (sesi ini)
1. `core/bom_gap.py` + papan `GET /api/dewi/rnd/completeness`: flag aksesoris kini **per varian** (`acc_keys`) → Lyora & 13 model
   "sebagian" tidak lagi tampil ✓. Status baru: "N dari M varian BOM-nya belum punya aksesoris".
2. Berkas FOKUS: varian yang BOM-nya tanpa aksesoris mendapat kelompok sendiri (aksesoris disalin biru dari varian saudara);
   model yang TAK SATU PUN BOM-nya ber-aksesoris → satu kelompok untuk semua varian (varian tanpa BOM dibuat otomatis saat unggah)
   — sebelumnya Hanny/Hanni hanya diberi 2 kelompok untuk 2 varian tanpa BOM padahal 13 varian semuanya tanpa aksesoris.
3. RINGKASAN_MODEL: kolom baru `varian_tanpa_aksesoris`; kolom `di_berkas_anda` untuk model tanpa SKU tidak lagi menulis
   "varian ditebak otomatis" (menyesatkan) melainkan "N kelompok ada di berkas, menunggu ukuran di VARIAN_BARU".

Berkas hasil: `private/golive/DATA_YANG_PERLU_DIISI_DA_FOKUS_dari_DA3.xlsx` (sisa dari berkas klien), `frontend/public/downloads/DATA_YANG_PERLU_DIISI_DA_FOKUS.xlsx` (tanpa berkas).
JSON per model: `private/golive/laporan_step{0,1,2}_*.json`.
