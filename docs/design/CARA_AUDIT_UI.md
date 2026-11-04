# Cara mengaudit & merapikan UI satu portal

Berlaku untuk semua portal: `finance`, `hr`, `production`, `warehouse`, `sales`, `toko`, dst.
Daftar portal: `python3 scripts/ui_audit/scan_ui.py --list-portals`. Aturan: [PANDUAN_UI.md](PANDUAN_UI.md).

Ada empat alat. Masing-masing menangkap hal yang tidak tertangkap alat lain:

| Alat | Menangkap | Tidak menangkap |
|---|---|---|
| 1. **Pemindai kode** `scripts/ui_audit/scan_ui.py` | layar tanpa cetakan `PageLayout`, popup berisi daftar, jarak besar, tombol buatan, `<select>`/tanggal polos, warna mentah, `window.confirm`, judul/tab buatan, kata Inggris | hasil tampilan akhir, isi data |
| 2. **Audit layar** `scripts/ui_audit/dom_audit.js` | pita kosong > 28 px, baris berisi satu tombol, penyaring menempel di kanan, istilah program di layar, kartu di dalam kartu, nol merah, tanggal/kode mentah, format tabel berbeda, tinggi tombol berbeda, isi tertutup tombol chat | rasa/kepatutan |
| 3. **Galeri layar** `scripts/ui_audit/galeri.py` | **semua layar portal berdampingan** di satu halaman + temuan audit per layar + galat API; pembanding **sebelum/sesudah** | — (dilihat dengan mata) |
| 4. **Mata** — daftar periksa di bawah | isi ganda antarmenu, urutan membingungkan, kata yang tidak dipahami | — |

## Langkah 1 — pindai kode

```bash
python3 scripts/ui_audit/scan_ui.py --portal hr --md docs/design/audit_hr.md
```

Hasilnya laporan per aturan, lengkap dengan berkas dan nomor baris. `CETAKAN-TIDAK-DIPAKAI` menunjukkan layar yang
masih menyusun kepala/toolbar sendiri — mulai perbaikan dari sini.

## Langkah 2 — galeri layar (sebelum)

Jalankan di app **lokal** (data dari cadangan VPS bila perlu). Butuh Docker; image Playwright diunduh sekali.

```bash
# token sementara dari backend LOKAL — dialihkan ke berkas, jangan ditampilkan; hapus setelah dipakai
docker exec -i dahost-local-backend-1 python - < scripts/ui_audit/buat_token_lokal.py > "$TEMP/galeri_token.json"

MSYS_NO_PATHCONV=1 docker run --rm --network dahost-local_default -v "$PWD:/repo:ro" -v "$TEMP:/work" \
  mcr.microsoft.com/playwright/python:v1.49.1-noble sh -c \
  "pip install -q --break-system-packages playwright==1.49.1 >/dev/null 2>&1; \
   python3 /repo/scripts/ui_audit/galeri.py --portal hr --token-file /work/galeri_token.json \
   --base http://localhost:8080 --via http://caddy:80 --out /work/galeri_hr_sebelum"
```

- `--network dahost-local_default` + `--via http://caddy:80`: container galeri masuk jaringan app lokal (port 8080 app
  hanya terbuka untuk 127.0.0.1, jadi tidak terjangkau dari container lewat `host.docker.internal`). Halaman tetap
  beralamat `--base` (sama dengan alamat yang tertanam di bundel), permintaannya diambil dari `--via`.
- Image Playwright tidak membawa paket Python-nya — `pip install playwright==1.49.1` (versi sama dengan image) dulu.
- Lama: ±5 detik per layar (Keuangan ±46 layar ≈ 4–5 menit).

Buka `$TEMP/galeri_hr_sebelum/index.html`:
- deret **pil di atas** = jumlah per aturan untuk seluruh portal; klik satu pil untuk menyaring layar yang melanggarnya;
- **"Beda gaya antarlayar"** = tampilan kosong atau format tabel yang tidak sama di portal itu;
- **galat API/JS** = layar yang memanggil API gagal (401/404/500) atau error JavaScript;
- tiap kartu = satu layar (menu › tab): potret penuh, temuan, judul, apakah memakai cetakan, dan tinggi tombol.

Untuk tema gelap tambahkan `--dark`. Untuk lebar HP tambahkan `--width 390 --height 844`. Untuk sebagian menu
saja: `--only hr-employees,hr-attendance-hub`.

Tanpa Docker, audit layar bisa dijalankan manual: buka app, DevTools › Console, tempel isi `dom_audit.js`, lalu
`await uiAuditMenus(<hasil scan_ui.py --portal hr --ids>)` dan `copy(window.__uiAuditResult)`.

## Langkah 3 — daftar periksa mata (per layar, sambil melihat galeri)

1. Apakah susunannya sama dengan layar lain: kepala → toolbar (penyaring kiri, alat kanan) → ringkasan → isi?
2. Ada ruang kosong besar, tombol sendirian di satu baris, atau tombol di tempat yang beda dari layar lain?
3. Apakah detail dibuka di halaman (panel di atas tabel / baris dibuka di bawah), bukan popup?
4. Ada isi yang sama dengan menu/tab lain (angka, daftar, rekening koran)?
5. Tombol utama hanya satu? Judul, tab, tombol bahasa Indonesia dengan huruf besar hanya di awal?
6. Ada istilah program yang tampil ke pengguna?
7. Periode bawaan ada dan rentangnya tertulis? Tampilan kosong memberi langkah berikutnya?
8. Masih terbaca di tema gelap?

## Langkah 4 — perbaiki

1. **Pindahkan layar ke cetakan `PageLayout`** (cara utama — menghapus banyak temuan sekaligus):
   kepala → `title`/`subtitle`/`actions`; cari/pilihan/periode/pil → `filters`; muat ulang/unduh/`ViewToggle` → `tools`;
   kartu angka → `summary`; popup daftar/detail → `detail` dengan `DetailPanel`; isi baris → `RowDetail`.
   Contoh lengkap: `erp/RahazaCashAccountsModule.jsx` (Rekening & Mutasi).
2. Perbaikan tombol massal (aman, bisa dipratinjau):
   ```bash
   python3 scripts/ui_audit/fix_buttons.py --portal hr          # pratinjau
   python3 scripts/ui_audit/fix_buttons.py --portal hr --apply  # tulis
   ```
3. Per layar, dari yang paling terlihat: `RUANG-KOSONG`, `BARIS-SATU-TOMBOL`, `PENYARING-KANAN`, `POPUP-DAFTAR`,
   `TEKS-TEKNIS`, `TOMBOL-TANPA-LATAR`, `KARTU-DI-DALAM-KARTU`, `TAB-*`, `TANGGAL-MENTAH`, `KODE-MENTAH`, `TEKS-INGGRIS`,
   lalu `ANGKA-MONO`, `WARNA-MENTAH`.
4. **Galeri sesudah** dengan pembanding — kartu tiap layar menampilkan potret sebelum & sesudah dan perubahan angkanya:
   ```bash
   ... galeri.py --portal hr ... --out /work/galeri_hr_sesudah --compare /work/galeri_hr_sebelum
   ```
   Tunjukkan `galeri_hr_sesudah/index.html` ke owner untuk ditinjau.
5. Kunci angkanya supaya tidak memburuk:
   ```bash
   python3 scripts/ui_audit/scan_ui.py --portal hr --set-baseline
   ```
   CI sudah menjalankan `scan_ui.py --portal all --gate` untuk semua portal.

Catatan salah tangkap yang wajar: `TEKS-INGGRIS` ikut menandai data (nama pemasok), `TERTUTUP-CHAT` tergantung posisi gulir.
Periksa contohnya di galeri sebelum memperbaiki.
