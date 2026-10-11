# LAPORAN KONSOLIDASI MASTER DATA — 2026-09-23 (harga material · varian · BOM · potongan · R&D)

Sumber: 4 berkas owner (`revisihargaaksesoris.xlsx`, `revisiBOMDA.xlsx`, `revisirndda.xlsx`, `revisiawal.xlsx`) → skrip
`scripts/konsolidasi/konsolidasi.py --apply` (log `private/golive/konsolidasi_apply_20260923_1451.json`).
Backup sebelum konsolidasi: `private/pre_konsolidasi_20260923.archive.gz` (`mongorestore --gzip --archive=… --drop`).

## Prioritas sumber (tidak tumpang tindih)
| Data | Sumber tunggal | Catatan |
|---|---|---|
| Harga & satuan material (515) | `revisihargaaksesoris` / MATERIAL | satuan dasar = isian owner (kancing→pcs, bisban/karet→cm, benang kiloan→kg); 251 material ganti satuan dasar; `isi_per_satuan_beli` = isi kemasan → uoms |
| BOM per SKU | `revisiBOMDA` / DETAIL_BOM (579 SKU) | Hanny DA-1509 baris bergeser → disusun ulang dari pola Hanni DA-1510 (11 SKU) |
| BOM SKU yang kosong di revisiBOMDA | `revisirndda` BOM_OTOMATIS/BOM_AKSESORIS | kelompok per warna (40) · satu kelompok model (89) · gabungan kelompok (9) · tebakan dari nama bahan berwarna (16) · baris umum tanpa aksesoris warna (33) |
| Varian baru (173 SKU) | `revisirndda` / VARIAN_BARU | DA-3306→DA-3302; ALLSIZE Victoria/Nagita = typo (dilewati); 5 model dihentikan tetap nonaktif; duplikat DA-2113 LIM dibuang |
| `revisiawal` | rujukan saja | tidak ada isian baru (harga kosong, varian kosong) |

## Hasil (DB sesudah)
- 104 model · **807 varian (777 aktif)** · **807 BOM (777 aktif, semua versi 1, tidak ada kunci ganda)** · 807 FG · 807 potongan CUT-*.
- `laporan_kekosongan_bom.py`: **98 E_LENGKAP · 6 F_DIHENTIKAN · 0 harus diisi** (sebelumnya 42 kurang).
- Papan R&D `/api/dewi/rnd/completeness`: missing bom 0 · accessories 0 · techpack 0 (sisa di luar lingkup: photo 88 · weight 98 · sop 98 · hpp 22).
- Setiap BOM aktif: 1 potongan + aksesoris + Hangtag A-HTG-0003 + Pin A-PIN-0001 (keputusan owner #3).
- HPP: Ochi DA-4104 **515.151 → 10.572** · Lyora DA-1101 91.396 → 37.228 · Onella DA-1508 143.382 → 22.052 · Hanny 21.546. Median biaya BOM Rp 20.368, maks Rp 61.733 (kain).
- Kancing kini dihitung benar: sebelumnya base `gross` dengan harga per pcs → 3 kancing = Rp 0,96; kini `pcs` Rp 46 → Rp 138.
- R&D: **104 Tech Pack v1 (draft)** per style (bom_items dari BOM, kain per warna, colorways, size list) · **12 material R&D** (per keluarga kain, daftar warna) · 806 varian R&D · 104 style tersinkron.
- Material baru: `A-TLK-0001 Tali Kancing` (cm, harga 0 — owner belum isi) · kain warna baru `KN-RMT-BNN/STB/LPC/BLE/LPP/DGP`, `KN-RTW-HTM/PTH` · **25 kain `KN-TBD-<warna>` "KAIN BELUM DITENTUKAN" (Rp 0)**.
- Isi kemasan jawaban owner: Label DA 1 roll = 1000 pcs · Pin 1 pack = 5000 pcs · Babud 1 pcs = 100 cm.

## YANG MASIH PERLU OWNER (data setengah yang jujur ditandai, bukan ditebak diam-diam)
1. **HPP 21 model belum terbit** (Ona, Lunara 1209–1211, Azkia, Cleo, Rasha, Aro, Inner jersey, Jolie, Heidi, Riana, Aruna, Arka, Irana, Jenifer): potongan baru belum bernilai (aturan sistem: biaya potongan lahir dari Portal Cutting). Levi/Keiko/Lunara 1201 memakai HPP lama sampai cutting.
2. **Kain sumber KN-TBD** (Rp 0) untuk: Lunara 1209–1211, Ona 2201, Azkia 2506/2507, Cleo 4106/4107, Rasha 3701/3702 (RTW ditebak dari model se-nama? → cek), Aro 6401, Inner jersey 6901, Irana 4307, Lunara 1201 — ganti ke kain nyata (kode `KN-<FAM>-<WARNA>`) di Master Material / Portal Cutting.
3. **Kain ditebak dari palet warna** (harga 0, hanya label sumber): Levi 2502/2503 & Keiko 2504/2505 & Jenifer 3512 → KN-RMT; Arka 4305, Irana 4306, Jolie 7101, Heidi 2112, Riana 2113, Aruna 3301/3302 → KN-K24.
4. **Aksesoris berwarna belum ada** (BOM hanya baris umum: label/karet/hangtag/pin) — 33 SKU: Hanny/Hanni DGP·PMR·BNN·STB·LPC·BLE·LPP·DGN, Nagita MCA (4201/4202), Heidi 12 warna (BTA WRD MCA OLV JBL LVD BRG AVC KBS LIM SLV PST), Vonny PTH, Mecca MVE·PTH → tambah kancing warnanya.
5. **Ditebak dari nama bahan berwarna** (16 SKU: Aro HTM/PTH, Heidi 13 warna, Vonny HTM) dan **gabungan kelompok** (Rasha, Jolie) — cek sekilas.
6. Harga 0 tersisa: A-TLK-0001. Review harga baru: 4 MERAH tersisa adalah heuristik (potongan Rp 0 membuat porsi aksesoris 100%) + `A-GUN-0001 Gunting Kodok Rp 64.900/pcs` (alat, bukan BOM).
7. Kode varian Lunara 1209/1210/1211 = S/M/L sesuai kolom `ukuran` (keputusan owner #1: SKU lama tidak ditulis ulang).

## Berkas
- Ekspor terbaru: `frontend/public/downloads/EXPORT_SKU_BOM_DA.xlsx` (807 SKU · 4.746 baris) — `https://<REACT_APP_BACKEND_URL>/downloads/EXPORT_SKU_BOM_DA.xlsx`
- Skrip: `scripts/konsolidasi/konsolidasi.py` (dry-run tanpa flag, `--apply`), `scripts/konsolidasi/analisis_harga.py`, `scripts/export_sku_bom.py`.
