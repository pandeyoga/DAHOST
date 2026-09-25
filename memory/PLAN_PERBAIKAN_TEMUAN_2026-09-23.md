# PLAN PERBAIKAN TEMUAN AUDIT — 2026-09-23 (Finance · Produksi/Maklon · R&D)

Referensi (disimpan apa adanya di `memory/temuan_2026-09-23/`): `TEMUAN_PORTAL_FINANCE_1.md` (21 temuan) ·
`TEMUAN_PORTAL_PRODUKSI_MAKLON.md` (5) · `TEMUAN_BUG_PORTAL_RND.md` (4). Setiap temuan **divalidasi di kode repo ini**
sebelum diperbaiki; yang belum divalidasi ditandai ⏳ dan dikerjakan sesuai fase.

## Status
| ID | Validasi | Status | Perbaikan (berkas) |
|---|---|---|---|
| RND-01 promosi style tanpa tombol | ✅ 0 pemanggil FE | **SELESAI** | tombol "Promosikan ke Produksi" `RnDStylesTab.jsx` (`promote-style-{id}`) → `POST /styles/{id}/promote-to-production` |
| RND-02 stok Produk Final selalu 0 | ✅ `rahaza_stock` 1 pembaca/0 penulis | **SELESAI** | `rnd_product_viewer.py` baca `rahaza_material_stock` + `read_qty` |
| RND-03 36 endpoint tulis R&D tanpa peran | ✅ router tanpa dependency | **SELESAI** | `dewi_rnd_shared.py` `rnd_write_guard`: POST/PUT/PATCH/DELETE wajib `rnd.manage` (fallback peran portal R&D + admin/owner); GET tetap terbuka |
| RND-04 2 endpoint HPP tanpa tombol | ✅ | **SELESAI** | `compute-from-bom` & `{id}/propagate` → 410 Gone (propagasi otomatis sudah ada) |
| MAK-01 angka per tahap hilang | ✅ `stage_qty`→`legacy_stage_qty` tidak dibaca | **SELESAI + UJI NYATA** | `_maklon_adapter.py`: gabungkan `legacy_stage_qty` ke `stage_qty`. PO contoh `MKL-KOHTRI-00001-2026-0001` (klien SnBM, artikel UJI-MAK01, 100 pcs) → cutting_input 123 tetap ada setelah dimuat ulang |
| PROD-02 Komponen Kurang tanpa peran | ✅ 3 endpoint `require_auth` | **SELESAI** | `dewi_cmt_component_requests.py` `only(PRODUCTION_ROLES+admin_maklon/ppic/manager_produksi)` pada POST/PUT/set-status |
| PROD-01 tombol legacy MI lewati persetujuan | ✅ dua tombol di MI draft | **SELESAI** | tombol legacy → 'Ajukan Approval' (`mi-submit-approval-btn`); `POST /material-issues/{id}/confirm` → 410 Gone |
| PROD-03 gerbang internal vs eksternal | ✅ (desain) | **DITERIMA** | pemindaian: 0 endpoint tulis tanpa penjaga setelah PROD-02; staf internal boleh membaca lintas portal produksi/maklon (keputusan desain) — gerbang per-portal tidak dipasang |
| MAK-02 satu nama menu dua layar | ✅ (UX) | **SELESAI** | menu Maklon 'Tracking Produksi' → 'Tracking Order' (`portalNav.js`) |
| FIN-03 kasbon tanpa pagar peran (KRITIS) | ✅ hr-review/disburse/seed `require_auth`; `employee_id` dari body | **SELESAI** | `dewi_kasbon.py`: hr-review `only(HR_ROLES)`, disburse `only(FINANCE_ROLES)`, seed admin/owner, pengajuan atas nama orang lain hanya HR/Keuangan (403) |
| FIN-10 impor CSV 100× | ✅ `_parse_idr` buang titik desimal EN | **SELESAI** | `dewi_bank_reconciliation.py`: `1,500,000.50`/`1500000.50` → 1.500.000,50 |
| FIN-16 potongan kasbon 2× per periode | ✅ dua jalur tak saling kenal | **SELESAI** | `dewi_kasbon.py` dedupe (kasbon, periode, payroll_deduction) di semua jalur + record_repayment tolak periode ganda; `rahaza_payroll_shared.py` lewati kasbon yang sudah dipotong Keuangan periode itu |
| FIN-01 Rekap Keuangan 7/7 salah | ✅ kolom `payment_date`/`total_amount`/`outstanding_amount` tak pernah ditulis | **SELESAI** | `server.py financial_recap` + `core/recap_finance.py`: baca `date`/`total`/`balance`, status kanonik, tanpa draft/void/written_off, "Semua" = seluruh periode; `FinancialRecapModule.jsx` tanggal lokal |
| FIN-02 peran resmi ditolak di portalnya | ✅ 11 daftar peran lokal | **SELESAI** | semua `_require_fin` & daftar lokal → `core.roles.FINANCE_ROLES` (manager generik keluar); FE `lib/financeRoles.js` dipakai 7 modul (Kas Kecil, Transfer Bank, Klaim, Dinas, Kategori) |
| FIN-04 pintu samping jurnal | ✅ router akrual/aset/anggaran/laporan tanpa dependency | **SELESAI** | `require_portal_dep("finance")` di router `rahaza_accruals/fixed_assets/budget/fin_reports`; kas kecil create_txn peran; snapshot HPP `_require_fin` |
| FIN-05 Kas Kecil | ✅ `1-110`, saldo berubah walau jurnal gagal, penutupan terbalik | **SELESAI** | akun dari Profil Posting (`1-1101`); jurnal dulu → saldo atomik (`$gte`) hanya bila jurnal OK; `close_return` Dr Bank/Cr Kas Kecil; `return` ≤ uang muka terbuka |
| FIN-06 Aset Tetap | ✅ `post_journal` tak ada, DDB /12 dobel, akumulasi diabaikan | **SELESAI** | post-depr pakai `rahaza_posting.post_depreciation` (gagal → tidak posted); DDB tarif bulanan + tutup residu; disposal tulis `accumulated_depr_at_disposal` dari jadwal posted, kredit akun aset milik aset |
| FIN-07 diskon PO diabaikan | ✅ `discount_amount` tak dibaca | **SELESAI** | `record_ap_payment`: hutang berkurang bruto (amount+diskon), `post_ap_payment(..., discount_taken)` |
| FIN-08 realisasi anggaran 0 | ✅ `journal_date`/`account_id` tak ditulis | **SELESAI** | agregasi `rahaza_journal_lines` via `account_code`+`period_code`; jalur `rahaza_expenses` dihapus |
| FIN-09 laporan turunan | ✅ status non-kanonik | **SELESAI** | AR 360 pakai `OPEN_STATUSES` (draft/written_off keluar, tanpa hidupkan balance 0); Laporan Eksekutif & Prediksi Kas status `issued/partial_paid`, `customer_name`, `total_net` |
| FIN-11 edit total AP hapus jurnal | ✅ | **SELESAI** | skala subtotal/pajak saat total berubah; cek seimbang SEBELUM void (`invoice_edit_requests.py`) |
| FIN-12 penyelesaian dinas uang muka belum dibayar | ✅ | **SELESAI** | advance = `cash_advance_paid`; advance-paid ≤ disetujui; inbox pakai `cash_advance_requested` |
| FIN-13 transfer bank tanpa jurnal / void | ✅ | **SELESAI** | `pending_posting` bila jurnal gagal; void tanpa jurnal bila belum posted; rekening dari `rahaza_cash_accounts` (FE) |
| FIN-14 akrual berulang ganda | ✅ | **SELESAI** | anak `is_recurring=False` + `recurring_template_id` akar; templat hanya dokumen asli |
| FIN-15 nilai tak hingga | ✅ | **SELESAI** | `math.isfinite` di `_validate_lines` & `_create_posted_je` |
| FIN-17 posting draf tidak atomik | ✅ | **SELESAI** | `update_one({'status':'draft'})` → 409 bila kalah (3 lokasi) |
| FIN-18 rekonsiliasi bank ganda | ✅ | **SELESAI** | 1 penyesuaian/mutasi; Lepas void jurnal penyesuaian; sidik jari impor manual/bulk/CSV |
| FIN-19 lingkup toko pencairan | ✅ | **SELESAI** | settlement/account di luar `vis` → 403 |
| FIN-20 catatan kecil a–f | ✅ | **SELESAI** | akun klaim dari Pemetaan GL · Post GL Selected via `_create_posted_je` · write-off tolak draft · batal tutup tahun cek terkunci · 400 tidak jadi 500 · kunci klik ganda + galat posting tampil + rekening 'tidak link' ditolak |
| FIN-21 seed & pemetaan GL bawaan | ✅ | **SELESAI** | seed kategori dengan user eksplisit; pemetaan GL → akun yang ada (6-3400/6-3500/6-2xxx) |

## Fase
1. **Keamanan & uang (P0)** — SELESAI: FIN-03, FIN-10, RND-03, PROD-02, MAK-01, RND-01, RND-02, FIN-16, FIN-01, FIN-02, FIN-04.
2. **Kebenaran akuntansi (P1)** — SELESAI: FIN-05…FIN-09, FIN-11…FIN-19, PROD-01.
3. **Kebersihan (P2/P3)** — SELESAI: RND-04, MAK-02, FIN-20, FIN-21; PROD-03 diterima (mitigasi).

**Papan Temuan** (status 30 temuan, dipantau owner): Portal Administrasi Sistem → AKSES & AUDIT → *Papan Temuan Audit* (`GET /api/rahaza/admin/audit-findings`, data `backend/data/audit_findings_2026_09_23.py`). Sesi 2026-09-23 #9 = iteration_230.

## Aturan kerja
- Validasi dulu di kode & DB (`grep`, eksekusi T-case), baru perbaiki; tulis ID temuan di komentar kode (`# FIN-03 …`).
- Gerbang peran memakai pola repo: `only(*ROLES)` (peran eksplisit) atau `require_perm`/`assert_can_act` (izin + fallback aman). Vendor/buyer tidak boleh menulis data internal.
- Setelah ubah `frontend/src`: `bash scripts/rebuild_frontend.sh`. Uji: testing agent (iteration_228 = fase 1 sesi ini).
