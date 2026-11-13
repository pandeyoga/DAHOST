# Panduan UI DAHOST

> ## Revisi 3 — Standar UI/UX v2 (keputusan owner 8 Nov 2026) — BERLAKU DI ATAS ATURAN LAMA
> Sumber keputusan: `private/audit/rencana_perbaikan_uiux_2026-11-08.md` (17 butir, semua disetujui; #2 diubah owner).
> **Hanya tampilan yang diubah — fitur, alur, dan data tidak berubah.**
>
> | No | Aturan v2 | Komponen |
> |---|---|---|
> | 1 | **Detail dibuka sebagai POPUP**, bukan panel di atas tabel. Rincian kecil (mis. baris jurnal) boleh tetap di bawah barisnya (`RowDetail`). | `DetailPanel` (kini otomatis popup bila ada `onClose`), `ui/detail-popup` |
> | 2 | **Form SELALU popup** — tidak pernah halaman sendiri. Dua ukuran yang konsisten: pendek & panjang. Kaki: galat · Batal · Simpan (hijau). **Klik di luar popup tidak menutup formulir** (14 Nov 2026); tutup hanya lewat ×, Esc, atau Batal. Formulir yang isiannya mahal diulang (pilih banyak barang, banyak baris) memberi `adaIsian` → menutup meminta konfirmasi dulu, dan menyimpan isian sebagai draf bila layar ditutup (contoh: Gudang › Scan Keluar › Pilih tanpa scan). | `ui/form-popup` (`FormPopup`, `Isian`; form penolakan: `warnaSimpan="destructive"`; `adaIsian`, `konfirmasiTutup`) |
> | 3 | **Warna tombol**: utama ungu; Simpan/Setujui hijau (`variant="success"`); Hapus/Tolak merah (`variant="destructive"`); lainnya garis. Warna pada tombol aksi dan status itu boleh — hiasan (gradien, emoji) tidak. | `ui/button` |
> | 4 | **Kepala halaman tipis**: judul + 1 kalimat; tanpa ikon besar; di HP judul lebih kecil & keterangan disembunyikan. | `PageLayout` / `PageHeader` |
> | 5 | **Daftar > 6 data = tabel**, bukan kartu berulang. | `ui/tabel-data` (`TabelData`) atau `ui/table` |
> | 6 | **Penyaring satu baris** ringkas: kotak cari ± 16 rem, pilihan ± 10–15 rem — tidak pernah selebar layar. Pil status satu baris (di HP bisa digeser). | `FilterChips`, `SmartNativeSelect` |
> | 7 | **Satu pemilih tanggal**: tidak ada lagi `<input type="date|month|datetime-local">`. Satu tanggal → `DatePicker`; periode → `PeriodPicker`. | `ui/date-picker` |
> | 8 | **Satu gaya kartu angka** (`StatTile`), skala huruf tetap (12/14/16/20/24 px), satu latar halaman (tanpa kotak abu di dalam halaman). | `StatTile` |
> | 9 | **Kartu angka harus benar & jelas artinya**: ada keterangan (`hint`), dihitung dari sumber yang sama dengan daftar/rinciannya. Angka yang belum bisa dihitung → "—" + alasan, bukan 0. | `StatTile hint=` |
> | 10 | **Bahasa Indonesia**: tanpa istilah Inggris/program (Expense → Klaim biaya, Settlement → Penyelesaian, Approval → Persetujuan, Update → Simpan/Ubah, Export → Unduh, Bulk → Massal, Draft → Draf, Pre-order → Pra-pesan, Dashboard boleh). Singkatan umum boleh: PO, SKU, CMT, QC, HPP, PIC, BOM. Huruf besar hanya di awal kalimat. | — |
> | 11 | **Tabel di HP** menjadi kartu ringkas (tanpa geser samping). | `TabelData` |
> | 12 | **Gerbang**: portal selesai bila skrip `scripts/ui_audit/jelajah_layar.py` = 0 temuan untuk portal itu **dan** owner menyetujui galeri sebelum/sesudah. | `ukur_layar.py`, `jelajah_layar.py` |
> | 16 | **Semua tabel bisa diunduh** Excel & CSV (permintaan owner 8 Nov). | `ui/tombol-unduh` (`TombolUnduh`) di slot `tools` |
> | — | **Kontras teks ≥ 4.5**: teks status pakai token `--success-text/--warning-text/--info-text/--danger-text`; latar tombol hijau/merah pakai `--success-strong/--destructive-strong`. | `index.css`, `StatusBadge` |
>
> Contoh acuan yang sudah memakai semua aturan v2: **Portal SDM › Papan Pengumuman** (`erp/AnnouncementModule.jsx`).


Status: **disetujui owner 4 Nov 2026**. **Revisi 2 (4 Nov 2026):** cetakan halaman `PageLayout` wajib, detail dibuka di
halaman (bukan popup), aturan ruang kosong & posisi tombol, larangan teks teknis. Ini **satu-satunya** panduan UI;
`design_guidelines.md` dicabut. Agen AI membaca ringkasannya di [`AGENTS.md`](../../AGENTS.md).

Panduan ini **tidak mengganti tampilan**. Warna ungu, huruf Space Grotesk/Inter, sudut membulat, permukaan putih (tema terang) dan kaca (tema gelap) tetap. Yang diatur hanya: **satu cara** untuk setiap jenis elemen.

Setiap aturan punya kode (mis. `TOMBOL-TANPA-LATAR`). Kode yang sama dipakai oleh:
- pemindai kode `scripts/ui_audit/scan_ui.py`;
- audit layar `scripts/ui_audit/dom_audit.js`.

Cara memeriksa portal: [CARA_AUDIT_UI.md](CARA_AUDIT_UI.md).

---

## G1 · Tata letak halaman

**Setiap layar memakai cetakan `PageLayout`** (`erp/layout/PageLayout.jsx`). Layar hanya mengisi slot; urutan,
posisi tombol, dan jarak ditentukan cetakan. → `CETAKAN-TIDAK-DIPAKAI`

| Slot | Isi |
|---|---|
| `title`, `subtitle` | judul & satu kalimat penjelasan (di dalam hub disembunyikan) |
| `actions` | tombol halaman — paling banyak 1 tombol utama (di dalam hub pindah ke baris tab) |
| `filters` | cari, pilihan, periode, pil status — toolbar **kiri** |
| `tools` | muat ulang, unduh, `ViewToggle` — toolbar **kanan**; tanpa `filters` ikut kepala/baris tab |
| `summary` | kartu angka atau satu kalimat ringkasan |
| `detail` | `DetailPanel` — detail satu baris, di halaman (G13) |
| `footer` | paginasi, tautan "tampilkan …" |

Urutan isi satu layar, dari atas:
1. **Kepala halaman** (G2).
2. **Tab** bila ada (G4).
3. **Toolbar**: penyaring di kiri, aksi di kanan (G6).
4. **Ringkasan angka**, opsional, paling banyak 4 (G5).
5. **Isi**: tabel / laporan / formulir.
6. **Paginasi**.

Aturan:
- Isi memakai **lebar penuh** area kerja. Modul tidak membuat pembungkus sendiri (`max-w-* mx-auto`, `p-6`). → `BUNGKUS-SENDIRI`, `LEBAR-HALAMAN-BEDA`
- Jarak antarbagian 16 px (`space-y-4`), dari cetakan. Jarak besar buatan sendiri (`space-y-6+`, `py-10+`, `mb-8`)
  tidak dipakai → `JARAK-BESAR`. Di layar, pita kosong lebih dari 28 px di antara isi = `RUANG-KOSONG`.
- **Tidak ada baris yang hanya berisi satu tombol** (mis. tombol muat ulang sendirian) → `BARIS-SATU-TOMBOL`.
- Penyaring selalu mulai dari **kiri**; tidak ada baris penyaring yang menempel di kanan → `PENYARING-KANAN`.
- Sisakan ruang 96 px di bawah halaman. Jangan menaruh tombol di pojok kanan bawah, karena tertutup tombol chat. → `TERTUTUP-CHAT`

## G2 · Kepala halaman

- Satu komponen: `PageHeader`.
- **Judul**: 24 px, tebal, Space Grotesk.
- **Subjudul**: satu kalimat (paling banyak ±90 huruf), 14 px, abu.
- **Aksi**: di kanan, sejajar judul.
- Polos, **bukan kartu**: tanpa kotak, tanpa garis, tanpa cahaya di sudut. Ikon dan "eyebrow" tidak dipakai.
- Judul tidak dibuat sendiri dengan `<h1>`/`<h2>`. Hasilnya sekarang: ukuran judul 18, 20, dan 24 px bercampur. → `JUDUL-BUATAN`
- **Di dalam hub** (menu bertab): hanya judul hub yang tampil. Aksi milik tab pindah ke **baris tab, sisi kanan**. Tidak ada baris yang hanya berisi tombol.

## G3 · Tombol

Ada **4 jenis**, tidak lebih:

| Jenis | Komponen | Dipakai untuk | Aturan |
|---|---|---|---|
| **Utama** | `<Button>` | Aksi utama layar: "Pengeluaran baru", "Simpan" | **1 per layar**. Dialog boleh punya 1 sendiri. |
| **Kedua** | `<Button variant="outline">` | Unduh, Impor, Rekening koran, Batal | Latar putih (tema terang) atau kaca (tema gelap), garis tipis. |
| **Ikon** | `<Button variant="outline" size="icon">` + `title` | Muat ulang, Ubah, Hapus | Ukuran 36×36. Wajib `title` dan `aria-label`. |
| **Tautan** | `<Button variant="link">` | "Buka", "Lihat semua", tautan ke menu lain | Teks ungu, tanpa kotak. |

- `variant="ghost"` hanya untuk ikon di dalam baris tabel. Tidak dipakai untuk tombol bertulisan. → `TOMBOL-HANTU`
- Tombol **tidak boleh** tanpa latar tapi bergaris (`ghost` + `border`). → `TOMBOL-TANPA-LATAR`
- **Tinggi** ditentukan prop `size`, bukan className:
  - 36 px (`default`) di kepala dan toolbar;
  - 32 px (`sm`) di dalam tabel/kartu.

  Sekarang ada 9 tinggi berbeda (24–56 px). → `TOMBOL-UKURAN-MANUAL`, `TOMBOL-TINGGI-BEDA`
- **Warna** tidak ditulis langsung (`bg-teal-600`, `bg-blue-600`). → `TOMBOL-WARNA-MENTAH`
- `<button>` polos berkelas sendiri tidak dipakai untuk tombol aksi. → `TOMBOL-BUATAN`
- **Tombol muat ulang** = ikon saja. → `MUAT-ULANG-BERTEKS`
- **Label**: kata kerja + benda, huruf besar hanya di awal. Contoh: "Pengeluaran baru", "Unduh CSV", "Impor laporan".
- **Hapus** (`destructive`) hanya muncul di dialog konfirmasi.

## G4 · Tab

Ada **dua jenis**, dan keduanya rata kiri:

**1. Tab halaman** — memindah isi. Komponen `HubTabs`.
- Bentuk segmen abu-abu (sama dengan sekarang), tetapi **rata kiri dan selebar isinya**, bukan bar penuh dengan tab di tengah.
- Angka boleh ditambahkan: "Tagihan (5)".

**2. Penyaring status** — menyaring isi tabel. Komponen `FilterChips`.
- Pil kecil 32 px di toolbar kiri.
- Pil aktif: latar ungu muda, teks ungu.
- Selalu dengan angka: "Menunggu (3)".
- Bila semua angka 0, pil disembunyikan.

Aturan:
- **Tidak ada tab di dalam tab.** Tab dalam modul yang dibuka di hub diubah jadi penyaring, atau dinaikkan jadi tab hub. → `TAB-DI-DALAM-TAB`, `TAB-DALAM-MODUL`
- Tidak ada deret tombol buatan sendiri yang berlagak tab (garis bawah, pil hijau, kolom berikon). Sekarang ada 5 gaya berbeda. → `TAB-BUATAN`, `TAB-GAYA-BEDA`
- **Nama tab**: huruf besar hanya di awal ("Umur piutang"), bahasa Indonesia, dan tidak sama dengan nama menunya.

## G5 · Kartu

Kartu menandai **satu kelompok isi yang berdiri sendiri**: tabel, formulir, satu ringkasan. Kartu **bukan** hiasan.

- **Satu jenis kartu**: `GlassCard`.
  - Latar `--card-surface`, garis `--glass-border`, sudut `--radius-lg`.
  - `Card` (shadcn), `DataCard`, dan `<div rounded border bg>` buatan sendiri tidak dipakai di layar baru. → `KARTU-BUATAN`, `KARTU-DUA-JENIS`
- **Tidak boleh** dipakai untuk:
  - tiap **baris** daftar atau laporan, seperti Laba Rugi dan Arus Kas sekarang → `BARIS-JADI-KARTU`;
  - **satu angka** selebar halaman ("Total saldo semua rekening") — cukup ditaruh di kepala/toolbar → `KARTU-SATU-ANGKA-LEBAR`;
  - kepala halaman;
  - **kartu di dalam kartu** → `KARTU-DI-DALAM-KARTU`.
- **Kartu angka** (`StatTile`):
  - paling banyak 4 sebaris, semuanya putih/netral dan sama → `KARTU-WARNA-WARNI`;
  - warna hanya pada **angka** yang bermakna (G8);
  - **nol selalu abu**, bukan merah → `NOL-MERAH`;
  - tidak ditampilkan bila semua 0; pakai tampilan kosong → `KARTU-NOL-BERJEJER`;
  - tidak mengulang angka yang sudah ada di tab lain pada menu yang sama.
- **Daftar entitas** (rekening, pemasok, toko) = **tabel**, dikelompokkan bila perlu. Grid kartu hanya untuk paling banyak 6 pilihan yang masing-masing butuh gambar/visual.

## G6 · Toolbar, penyaring, periode

- **Satu baris toolbar** setinggi 36 px:

  `[Cari 240–320px] [Penyaring…] [Periode] ……… [Ikon] [Kedua] [Utama]`

  Kotak isian tidak boleh melebar penuh dan bertumpuk. → `FILTER-BERTUMPUK`
- **Periode** hanya lewat `PeriodPicker`:
  - pilihan: Bulan ini · Bulan lalu · 3 bulan · Tahun ini · 12 bulan · Pilih tanggal;
  - keterangan rentang ("01 Sep 2026 – 04 Nov 2026") ditampilkan;
  - **bawaan wajib ada** (biasanya Bulan ini);
  - tanpa `type="month"`, dan tanpa filter tanggal kedua di tabel. → `PERIODE-GANDA`, `BULAN-KOSONG`, `TANGGAL-POLOS`
- Laporan posisi (Neraca, Saldo akun) memakai satu pilihan **"Per tanggal"**.
- **Bentuk tampilan** (Tabel / Kartu) memakai `ViewToggle` (dua tombol ikon di `tools`), bukan pil penyaring.
  → `TOGGLE-SEPERTI-PENYARING`
- **Pilihan** memakai `SmartNativeSelect` (bisa dicari). Label pilihan dalam bahasa manusia, bukan kode (`bahan_pembantu` → "Bahan pembantu"). → `SELECT-POLOS`, `KODE-MENTAH`

## G7 · Tabel, laporan, angka

**Tabel daftar** (dokumen, mutasi, rekening):
- Pakai `DataTable` bila butuh cari/urut/unduh, atau `<Table>` (ui/table) untuk tabel sederhana.
- `<table>` mentah tidak dipakai lagi. → `TABEL-TIGA-CARA`
- **Format tetap**:
  - judul kolom 11 px HURUF BESAR abu, berlatar;
  - sel 13 px, padding 10/12 px;
  - baris ±44 px dengan garis pemisah.

  Sekarang ada beberapa format tabel dalam satu portal. → `TABEL-GAYA-BEDA`, `TABEL-TANPA-KEPALA`

**Laporan keuangan** (Laba Rugi, Neraca, Arus Kas, Neraca lajur) = **tabel laporan** dalam **satu** kartu:
- Baris kelompok bisa dilipat (▸), baris akun menjorok ke dalam.
- **Subtotal** tebal dengan garis atas. **Total akhir** tebal dengan garis ganda.
- Kolom angka rata kanan.
- Tidak ada kartu per kelompok, tidak ada pil per subtotal. Label: Laba kotor, Laba usaha, Laba bersih.

**Angka**:
- Rata kanan, `tabular-nums`, **huruf sama dengan teks** (bukan `font-mono`). `font-mono` hanya untuk kode/nomor dokumen yang kecil. → `ANGKA-MONO`, `ANGKA-TIDAK-RATA-KANAN`
- Uang: "Rp 1.234.567". Di kolom berjudul "(Rp)", tulis "1.234.567". Negatif: "−1.234.567" berwarna merah.
- Persen: "17,5%" (koma). → `DESIMAL-TITIK`
- Tanggal: "04 Nov 2026" (`formatDateID`), bukan "2026-11-04". → `TANGGAL-MENTAH`

**Paginasi**: `PaginationLite` di bawah tabel, 25 baris per halaman.

## G8 · Warna

- Hanya token: `primary` (ungu), `success`, `warning`, `destructive`, `muted`. Palet langsung (`text-emerald-300`, `bg-blue-100`) tidak dipakai. → `WARNA-MENTAH`, `LATAR-WARNA-MENTAH`
- **Arti warna tetap**:
  - **merah** = masalah (lewat jatuh tempo, minus, gagal);
  - **kuning** = perlu perhatian;
  - **hijau** = selesai/lunas;
  - **ungu** = aksi/tautan;
  - **abu** = netral/nol.
- Warna **tidak** dipakai untuk menghias kartu.
- **Status** memakai `StatusBadge` dengan label Indonesia (`lib/financeLabels.js`).

## G9 · Dialog & pesan

- Konfirmasi memakai dialog aplikasi (`AlertDialog`) dengan tombol "Batal" dan aksinya. `window.confirm`/`alert` tidak dipakai. → `DIALOG-BROWSER`
- Hasil aksi dikabarkan dengan `toast`, dalam kalimat jelas ("Pembayaran tercatat · JE-…").

## G10 · Kosong & memuat

- **Kosong** = `EmptyState`: ikon, judul, satu kalimat langkah berikutnya, dan tombol bila ada. → `KOSONG-BUATAN`
  Satu komponen saja (`erp/EmptyState.jsx` kini meneruskan ke `moduleAtoms.EmptyState`). → `KOSONG-GAYA-BEDA`
- **Tabel kosong tetap tampil** (keputusan owner 8 Nov 2026): kepala kolom tetap ada, dan `EmptyState` tampil
  sebagai satu baris di badan tabel — tabel tidak diganti satu pesan kosong, dan layar/dashboard tidak disembunyikan
  seluruhnya. `TabelData` melakukannya sendiri (prop `kosong`); `DataTable` lewat `emptyTitle`/`emptyDescription`;
  tabel `ui/table` buatan layar memakai satu `TableRow` berisi `TableCell colSpan` + `EmptyState`.
  Boleh tetap disembunyikan: bagian peringatan yang memang hanya muncul bila ada isinya (mis. "perlu perhatian").
- Saat kosong, **sembunyikan** kartu angka 0 dan penyaring berangka (0).
- **Memuat** = `Skeleton` sesuai bentuk isi.

## G11 · Bahasa

- **Bahasa Indonesia, huruf besar hanya di awal kalimat**. Kata Inggris tidak dipakai. → `TEKS-INGGRIS`
- **Glosarium**:

  | Pakai | Ganti |
  |---|---|
  | Unduh | Export |
  | Impor | Import |
  | Muat ulang | Refresh |
  | Simpan | Save |
  | Batal | Cancel |
  | Hapus | Delete |
  | Ubah | Edit |
  | Faktur | Invoice |
  | Tagihan | — |
  | Pemasok | Supplier |
  | Pelanggan | Customer |
  | Rekening koran | Statement |
  | Penyelesaian | Settlement |
  | Lewat jatuh tempo | Overdue |
  | Draf | Draft |
  | Terjurnal | Posted |
  | Sisa | Outstanding |
  | Laba kotor | Gross profit |
  | Laba usaha | Operating income |
  | Pusat biaya | Cost center |
  | Jurnal | GL |

- Penjelasan panjang dipindah ke panel bantuan. Di layar paling banyak satu baris.
- **Tidak ada istilah program di layar**: `snake_case` (`entity_types`), path modul (`routes.coa_auto.X`), nama koleksi,
  atau label teknis ("Induk Auto Akun (sub-ledger)"). Tulis kalimat yang dipahami staf, mis. "Akun induk rekening bank —
  rekening baru dibuat di bawah akun ini. Diatur di Pengaturan Keuangan › Pemetaan akun otomatis." → `TEKS-TEKNIS`

## G12 · Elemen mengambang

Tombol chat dan bantuan mengambang di kanan bawah. Halaman memberi ruang di bawahnya. Toolbar, tombol, dan baris terakhir tabel tidak boleh tertutup. → `TERTUTUP-CHAT`

## G13 · ~~Detail dibuka di halaman, bukan popup~~ — DICABUT 8 Nov 2026 (lihat Revisi 3 #1: detail = popup)

Arahan owner 4 Nov 2026: klik satu baris membuka detailnya **di halaman**.
- **Detail satu baris** (mutasi rekening, keterikatan akun, rincian dokumen) = `DetailPanel` di slot `detail`:
  lebar penuh, di atas tabel, tombol × dan Esc menutup.
- **Isi baris** (baris-baris jurnal, item faktur) = `RowDetail` tepat di bawah barisnya, dibuka dengan `RowToggle`
  (ikon panah) atau klik nomor dokumennya. Untuk jurnal: `finance/JournalLinesInline`.
- **Popup (`Dialog`)** hanya untuk formulir isian pendek dan konfirmasi. `Sheet` (panel samping) tidak dipakai
  untuk daftar/tabel. → `POPUP-DAFTAR`

---

## Komponen yang sudah tersedia (2026-11-04)

| Kebutuhan | Pakai |
|---|---|
| **Cetakan layar** | **`PageLayout`** (erp/layout/PageLayout.jsx) — kepala, toolbar kiri/kanan, ringkasan, detail, isi, kaki |
| Detail di halaman | `DetailPanel`, `RowDetail`, `RowToggle` (erp/layout/PageLayout.jsx) |
| Isi jurnal di bawah baris | `finance/JournalLinesInline` |
| Pilihan Tabel/Kartu | `@/components/ui/view-toggle` |
| Kotak pemberitahuan (peringatan/galat/berhasil/info) | `Notice` (moduleAtoms) — pengganti `<div>` berwarna buatan sendiri |
| Keterangan kecil di bawah angka kartu | `StatTile sub=… subTone=…` |
| Periode "Semua waktu" | `PeriodPicker presets={[ALL_TIME, ...PERIOD_PRESETS]}` |
| Memo jurnal berbahasa Inggris dari server | `humanMemo()` (lib/financeLabels) |
| Kepala halaman (di dalam PageLayout) | `PageHeader` (moduleAtoms) — di dalam hub aksinya otomatis pindah ke baris tab |
| Aksi modul buatan sendiri di dalam hub | `HubActions` (moduleAtoms) |
| Tab halaman | `HubTabs` — Tabs Radix di dalam tab hub otomatis tampil sebagai pil penyaring |
| Penyaring status/jenis | `@/components/ui/filter-chips` |
| Laporan keuangan | `erp/finance/StatementTable.jsx` |
| Periode | `erp/finance/PeriodPicker.jsx` (+ `monthOptions()` untuk formulir satu bulan) |
| Konfirmasi | `confirmDialog()` dari `@/components/ui/confirm-dialog` |
| Kartu angka | `StatTile` (nol otomatis abu) |
| Tampilan kosong | `EmptyState` (moduleAtoms) — `action` boleh elemen atau `{ label, onClick }` |
| Format tabel | otomatis lewat CSS `main[data-portal="…"] table` (index.css) — tambahkan portal setelah diaudit |
| Perbaikan tombol massal | `python3 scripts/ui_audit/fix_buttons.py --portal <p> --apply` |

## Yang harus dibersihkan (sumber masalah di komponen bersama)

Urutannya penting: perbaiki **komponen** dulu, lalu layar.

1. **`ui/button.jsx`**: varian `outline` tidak punya latar, dan hover tema terang memakai warna aksen hijau-limau. Tambahkan latar `--card-surface` dan hover `--card-surface-hover`.
2. **`moduleAtoms.PageHeader`**: dibuat polos (tanpa kartu/cahaya). Mode hub: aksi dikirim ke baris tab.
3. **`hubs/HubTabs.jsx`**:
   - daftar tab rata kiri dan selebar isi;
   - slot aksi di kanan;
   - kirim konteks "di dalam hub" supaya tab modul berubah jadi penyaring.
4. **Komponen baru `FilterChips`**: menggantikan 5 gaya tab buatan.
5. **Kartu**: GlassCard, Card, DataCard, dan div buatan disatukan. StatTile, KPICell, StatCard, dan kartu warna buatan → **StatTile** (netral, nol abu).
6. **Tabel**: `DataTable`/`<Table>` dengan format tetap. Komponen baru **`StatementTable`** untuk laporan keuangan.
7. **Toolbar**: ~~komponen `Toolbar`~~ → selesai lewat slot `filters`/`tools` di `PageLayout` (4 Nov 2026).
8. **CSS tambalan di `index.css`** (blok "LIGHT MODE READABILITY BASELINE" dan "LIGHT-BUTTON-BASELINE") memetakan warna mentah ke token dan mengubah semua pembungkus tabel jadi kartu otomatis. Tambalan ini menutupi masalah dan menyebabkan **kartu di dalam kartu**. Kurangi bertahap setelah modul bersih.
9. **Per layar**:
   - tanggal mentah, desimal titik, kode mentah;
   - kata Inggris;
   - `window.confirm`;
   - `font-mono` pada angka.
