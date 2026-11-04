# Aturan untuk agen AI (Claude, Emergent, Codex, Cursor, dll.)

Berkas ini dibaca otomatis di awal setiap sesi. Aturan teknik lengkap ada di
[`AGENT_DEVELOPMENT_RULES.md`](AGENT_DEVELOPMENT_RULES.md) dan [`AGENT_QUICKSTART.md`](AGENT_QUICKSTART.md).

## Dasar
- Bahasa layar dan pesan: **Indonesia**.
- **Repo ini publik.** Jangan commit data klien: arsip seed, `SEED_CREDENTIALS.md`, Excel pelanggan, folder `private/`.
- Jangan membuat fitur, menu, atau konfigurasi kedua untuk hal yang sudah ada. Cari dulu, lalu perbaiki yang ada.

## Layar (UI) — wajib

Satu-satunya panduan: [`docs/design/PANDUAN_UI.md`](docs/design/PANDUAN_UI.md).
`design_guidelines.md` sudah **dicabut**; jangan dipakai sebagai acuan.

1. **Setiap layar memakai cetakan `PageLayout`** (`frontend/src/components/erp/layout/PageLayout.jsx`).
   Jangan menyusun kepala halaman, baris toolbar, atau baris tombol sendiri.

   | Isi | Slot `PageLayout` |
   |---|---|
   | judul, satu kalimat penjelasan | `title`, `subtitle` |
   | tombol halaman (paling banyak 1 tombol utama) | `actions` |
   | cari, pilihan, periode, pil status | `filters` |
   | muat ulang, unduh, pilihan tampilan Tabel/Kartu | `tools` |
   | kartu angka / kalimat ringkasan | `summary` |
   | detail satu baris (mutasi, isi jurnal, keterikatan akun) | `detail` berisi `DetailPanel` |
   | paginasi | `footer` |

   Isi baris tabel yang dibuka/tutup memakai `RowDetail`, di bawah barisnya.
2. **Popup (`Dialog`/`Sheet`) hanya untuk formulir isian pendek dan konfirmasi.** Daftar, tabel, dan detail
   dibuka di halaman (`DetailPanel` / `RowDetail`).
3. **Komponen**: `Button` (utama · outline · ikon · link), `SmartNativeSelect`, `PeriodPicker`, `FilterChips`
   (hanya untuk penyaring), `ViewToggle` (Tabel/Kartu), `EmptyState`, `StatusBadge`, `StatTile`, `StatementTable`,
   `DataTable` / `ui/table`. Jangan memakai `<button>`, `<select>`, `<table>`, `<h1>` buatan sendiri, input
   `type="date|month"` untuk periode, atau `window.confirm`.
4. **Jarak** hanya dari cetakan (16 px antarbagian). Jangan menambah `p-6`, `py-12`, `mt-8`, atau `max-w-* mx-auto`.
5. **Teks**: bahasa Indonesia, huruf besar hanya di awal. Jangan menampilkan istilah program ke pengguna
   (`snake_case`, nama koleksi, path modul seperti `routes.x.y`). Terjemahkan ke kalimat yang dipahami staf.
6. **Warna** hanya token: `primary`, `success`, `warning`, `destructive`, `muted`.

## Sebelum menyatakan pekerjaan layar selesai
```bash
python3 scripts/ui_audit/scan_ui.py --portal <portal> --gate
```
Lalu buat galeri layar portal itu dan lihat hasilnya dengan mata. Langkahnya ada di
[`docs/design/CARA_AUDIT_UI.md`](docs/design/CARA_AUDIT_UI.md). CI menolak perubahan yang menambah pelanggaran.
