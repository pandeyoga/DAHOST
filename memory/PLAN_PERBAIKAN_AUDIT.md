# PLAN PERBAIKAN — hasil validasi `AUDIT_DAHOST.md` terhadap repo `mzkkajsbd/DA`

Tanggal validasi: 2026-09-19 (sesi lanjutan). Metode: setiap temuan dibuka berkasnya di `/app/backend` & `/app/frontend`
(grep + baca kode), bukan mempercayai dokumen audit. Angka audit dibuat pada repo `pandeyoga/DAHOST@df6fb5c`; repo ini
adalah turunannya, jadi sebagian angka berbeda sedikit tetapi **polanya sama**.

## 0. KONTEKS WAJIB UNTUK AGENT BERIKUTNYA (baca dulu, 2 menit)

**Aplikasi:** ERP CV. Dewi Aditya (garmen): FastAPI (`/app/backend`, entry `server.py`, 293 router) + React CRA/craco
(`/app/frontend`) + MongoDB. Bahasa UI, dokumen, dan komunikasi ke user: **Indonesia**. Dokumen induk: `/app/memory/PRD.md`
(log per sesi, terbaru di atas), `/app/HANDOFF.md`, `/app/ARCHITECTURE.md` (SSOT koleksi), `/app/AGENT_DEVELOPMENT_RULES.md`.

**Lingkungan (jebakan yang sudah ditemui):**
- `backend/.env` wajib punya `JWT_SECRET` (auth.py menolak boot bila kosong). `MONGO_URL`, `DB_NAME=test_database`, `CORS_ORIGINS`.
- `pip install -r requirements.txt` gagal pada pin `emergentintegrations==0.2.0` vs `litellm 1.80.0` → keduanya sudah ada di image;
  install sisanya dengan `grep -v "^emergentintegrations\|^litellm\|^ast_serialize" requirements.txt > /tmp/req.txt && pip install -r /tmp/req.txt`.
- **Frontend dilayani sebagai STATIC BUNDLE** (`yarn start` = `node static_server.js` → `frontend/build`). Perubahan `frontend/src`
  TIDAK hot-reload: jalankan `bash /app/scripts/rebuild_frontend.sh` (atau `cd /app/frontend && yarn build`, ±3 menit, jalankan di background).
- Backend hot-reload aktif tetapi startup ±15 detik (router banyak). Log: `tail -n 100 /var/log/supervisor/backend.err.log`.
- **Data uji = data klien nyata** dari `seed/DA_SEED_GOLIVE.archive.gz` (104 model · 645 varian · 1.756 material · 634 BOM · 38 user).
  Restore: `mongorestore --gzip --archive=/app/seed/DA_SEED_GOLIVE.archive.gz --nsFrom='dahost_erp.*' --nsTo='test_database.*' --drop`
  (atau `bash /app/scripts/seed_golive_restore.sh --force`). **Jangan pakai seeder demo** (`ALLOW_DEMO_SEED`). Setelah uji yang
  mengubah data (apply, delete, posting) → restore lagi.
- Kredensial: `/app/memory/test_credentials.md` (admin `admin@garment.com` / `Admin@123`; peran lain `{role}@dewiaditya.id` / `Dewi@123`).
  Login rate-limit 10 percobaan/60 dtk per akun → login sekali, simpan token.
- Pytest: `backend/pytest.ini` memaksa `-n 2 --dist loadscope`; serial = `-n 0` (BUKAN `-p no:xdist`). Kebanyakan test butuh
  `REACT_APP_BACKEND_URL` di env (`export REACT_APP_BACKEND_URL=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)`)
  dan `set -a && . backend/.env && set +a`. Test `test_iter218_gap_fokus.py` sebagian butuh `/app/private/` (tidak ada di repo) → wajar error.
- Gate resmi: `bash /app/scripts/gate.sh`; invarian data: `python /app/scripts/verify_data_integrity.py`.
- Konvensi kode: rute wajib prefix `/api`; helper `get_db()` dari `database.py`; auth via `Depends(require_auth)` atau
  `await require_auth(request)`; gerbang keuangan yang sudah ada: `routes/rahaza_coa._require_fin`, `routes/shared.assert_can_act`;
  jurnal via `routes/rahaza_posting._create_posted_je` / `_find_existing_je` / `_void_je_by_source`; ID dokumen = `uuid4` string di field `id`.

**Status pekerjaan sebelum plan ini:** semua fitur importir Excel BOM (FOKUS/SISA/BOM_OTOMATIS) selesai & teruji (PRD sesi 2026-09-19 a–b).
Plan di bawah adalah pekerjaan BERIKUTNYA; belum ada satu pun langkahnya yang dikerjakan.

## A. HASIL VALIDASI

| ID | Putusan | Bukti di repo ini |
|---|---|---|
| T-01 | **VALID** | `require_auth` hanya memuat `_permissions`, tidak menegakkan. Contoh persis ada: `dewi_rnd_hpp.py:779 delete_hpp`, `dewi_hris_performance.py:456 submit_review` (hanya `Depends(require_auth)`), `marketing_scope_guard.py:80` melewatkan peran non-toko. Hitung kasar saya (pola sederhana, 12 baris pertama): **580 dari 999** endpoint tulis tanpa kata kunci peran, **79 DELETE**. Urutan besaran sama dengan audit (651/1.323). |
| T-02 | **VALID** | `auth.py:182,193` seed `admin@garment.com / Admin@123`; `deploy/README_DEPLOY.md:10` mencetaknya. Tidak ada `BOOTSTRAP_ADMIN_*`. Repo publik. |
| T-03 | **VALID** | Penulis `rahaza_work_orders` (insert/update/delete) di luar tests/scripts: **0**. Pembaca: **23 berkas** di routes/services/core (lebih banyak dari 17 di audit). `ARCHITECTURE.md` menetapkan `production_jobs` sebagai SSOT internal. |
| T-04 | **VALID** | `product_costing.py:660` `computable = bool(bom_id) and unvalued_count == 0`; status `unlinked` (baris 323) hanya menambah gap, tidak menaikkan penghitung; `apply_model_cost` (baris 851) hanya menyaring `not bom_id or hpp_unit <= 0`. |
| T-05 | **VALID** | Dua berkas ada (4.626 vs 3.964 byte). Salinan `utils/` tidak memuat `po_accessories`/`production_variances`/`rahaza_ar_invoices` (0 hit vs 3). `master_data.py:21` masih mengimpor salinan lama; `production_pos.py:18` & `maklon_seed.py:20` memakai salinan baru. |
| T-06 | **VALID** | `dewi_maklon_pos.py:557 PUT /pos/{po_id}` tidak memeriksa `mirror_of` (mirror ditulis di baris 451); `production_maklon_bridge.py:182` `$set` ulang `mirror_fields`. Pola penjaga sudah ada di `dewi_maklon_billing.py:319`. |
| T-07 | **VALID** | `production_execution.py:717 delete_job` hanya `delete_many` 3 koleksi; tidak memanggil `_void_je_by_source` (ada di `rahaza_posting.py:254`), tidak membersihkan `fg_cost_layers`/`rahaza_hpp_snapshots` — padahal `maklon_seed.py:428` melakukannya. |
| T-14 | **VALID (dipersempit)** | `dewi_cmt_partners.rate_per_pcs` tidak punya penulis di luar demo seed; `TEMPLATE_MASTER_DA.xlsx` sheet `11_VENDOR_CMT` = `kode·nama·nama_kontak·telepon·alamat·kapasitas_pcs·keterangan` (tanpa tarif); `variance_flag` (`production_maklon_bridge.py:396`) hanya cek kuantitas; teks gap `product_costing.py:435` menunjuk sumber yang tak bisa diisi. Catatan: layar **Biaya Jahit SPK** (`production_sewing_cost.py`) memang ada dan menulis `cmt_price_snapshot` — jadi mekanisme benar, hanya pintu lahirnya sempit. |
| T-08 | **VALID sebagian** | 3× `APPROVER_ROLES` identik tanpa `accounting` (`employee_expense_claims:53`, `employee_travel_requests:60`, `employee_travel_settlements:52`), `ADMIN_ROLES` di `employee_expense_gl_mapping:40` & `employee_expense_category_master:35`, `rahaza_ar_360:87`, `rahaza_channel_gl_mapping:38`, `employee_expense_summary:31,99`. Peran yang di-seed: `accounting`, `staff_keuangan` (tidak ada `finance`). **Koreksi audit:** `core/pr_approval.py:75 FINANCE_APPROVER_ROLES` SUDAH memuat `accounting`/`staff_keuangan` → bukan 19 gerbang, melainkan **±13 gerbang di 8 berkas**. |
| T-09 | **VALID** | `start_session`/`with_transaction`: 0 (satu hit `start_session` adalah nama endpoint absensi). `utils/saga` dipakai 5 berkas (payroll). `verify_data_integrity.py` hanya INV-JL-1 (arah baris yatim). Jurnal ditulis 2× (`rahaza_posting.py:222` lalu `:249`). |
| T-10 | **VALID** | `server.py:577` indeks `(source_module, source_ref, status)` **tidak unique**. `_find_existing_je` menyaring `status != voided` (read-then-write). `dewi_kasbon._post_kasbon_gl` memanggil `_create_posted_je` tanpa cek existing sendiri. |
| T-11 | **VALID sebagian (turun ke P2)** | Sumber memang terbelah: `dewi_bank_reconciliation._gl_balance_until` = baris tertanam + filter posted; `gl_balances_by_code` & `fin_statements._sum_by_account` (neraca saldo) = cermin tanpa filter status. **TETAPI** `_void_je_by_source` `delete_many` cermin saat void (`rahaza_posting.py:272`), jadi cermin = posted-only by design. Risiko nyata hanya bila ada jalur void/edit lain yang tidak menghapus cermin → perlu detektor (INV-JL-2), bukan refactor besar. |
| T-12 | **VALID** | `create_index` di `server.py` untuk `vendor_shipment_items`, `buyer_shipments`, `vendor_shipments`, `cmt_receipts`, `wh_positions`, `wh_pending_movements`: **0 semua**. |
| T-13 | **VALID** | Tidak ada `.github/`. Repo hanya 1 commit "Auto-generated changes" (bahkan lebih parah dari 7 di audit). `scripts/gate.sh` ada tetapi manual. |
| T-15 | **VALID** | `frontend/src/**/*.test.*` = **0**; README baris 122 mengklaim 204 uji Jest. 217 berkas Python menembak `localhost:8001`. |
| T-16 | **VALID sebagian** | `deploy/Dockerfile.frontend:12` `yarn install` tanpa `--frozen-lockfile`; `react-beautiful-dnd@13` + React 19. **Catatan:** `frontend/yarn.lock` di repo ini ADA (dipakai bring-up sesi ini) — tinggal `--frozen-lockfile`. |
| T-17 | **VALID** | `hris_cycles/hris_reviews/hris_assignments/hris_kpi_assignments`, `rahaza_qc_events`, `rahaza_attendance`, `capacity_config`, `rahaza_material_reservations`: penulis **0**, pembaca ≥1. `dewi_maklon_inventory`, `invoice_change_history`, `workspace_shares`: ditulis, tak dibaca. `td011_cleanup_orphan_collections.py:32-35` mendaftar `dewi_perf_*` (yang berisi data) sebagai yatim — **berbahaya bila dijalankan**. `fg_cost_consumptions` dibaca hanya oleh test. |
| T-18 | **VALID** | `services/stock_service.py` ada; importir **0**; membaca `rahaza_stock_ledger` & `rahaza_material_reservations` (tanpa penulis). |
| T-19 | **VALID** | `core/collection_registry.py` (472 baris) tidak diimpor siapa pun; `data/collection_registry.py` yang dipakai `admin_backup.py`. |
| T-20 | **VALID** | 3 `bulk_approve_*` identik di 3 berkas `employee_*`, masing-masing dengan `APPROVER_ROLES` sendiri (akar T-08). |
| T-21 | **VALID** | `to_list(None)` di `routes/`: **172** dari 1.656 pemanggilan (audit: 248/1.614). |
| T-22 | **VALID** | `verify_token_str` (token di query string) di **9 berkas** routes; `deploy/Caddyfile:36-37` log akses ke `/data/access.log`. |
| T-23 | **VALID** | `server.py:2435` default `'*'` + `allow_credentials=True`; compose menimpanya. |
| T-24 | **VALID** | 416 `create_index`, 293 `include_router` di `server.py`; `def _now` didefinisikan ulang di 239 berkas. |
| T-25 | **Tidak diverifikasi ulang** (butuh pemetaan FE↔BE penuh; bukan bug, hanya permukaan). Diterima sebagai P2 rawat. |
| T-26 | **VALID** | `mobile/` 36 berkas, **0** panggilan `/api`. |
| T-27 | **Tidak diverifikasi ulang** (butuh AST penuh). Diterima sebagai P3. |
| T-28 | **VALID** | `routes/dewi_kpi.py.old`, `routes/dewi_kpi.py.pre-refactor-backup`; 60 `test_*.py` di akar; 197 skrip; 273 berkas .md; `test_result.md` 484 KB. |

**Kesimpulan:** 24 temuan valid (3 dengan koreksi kecil: T-08 jumlah gerbang, T-11 prioritas, T-16 yarn.lock sudah ada), 2 tidak
diuji ulang (T-25, T-27), 0 gugur. Lampiran B audit (koreksi diri) konsisten dengan kode.

---

## B. PLAN PERBAIKAN (dieksekusi sesi berikutnya)

Prinsip: (1) uang & keamanan dulu, (2) perbaikan kecil ber-dampak besar sebelum refactor, (3) setiap langkah punya
pemeriksaan otomatis agar tidak kambuh (gate). Setiap fase = 1 sesi kerja + testing agent.

### FASE 0 — Tindakan segera di VPS (tanpa kode, hari ini)
| # | Langkah | Cara | Verifikasi |
|---|---|---|---|
| 0.1 | Ganti sandi superadmin produksi (**T-02**) | Login → Profil → ganti sandi; atau `PUT /api/auth/change-password`. | Login dengan `Admin@123` → 401. |
| 0.2 | Pastikan `CORS_ORIGINS` & `ALLOW_DEMO_SEED=false` terset di compose (**T-23**) | Sudah ada di `deploy/docker-compose.yml`; cek `.env` VPS. | `curl -H "Origin: https://evil" …` → tanpa `Access-Control-Allow-Origin`. |

### FASE 1 — P0 uang & data (perubahan kecil, risiko rendah) — target 1 sesi
| # | Temuan | Perubahan | Berkas | Verifikasi |
|---|---|---|---|---|
| 1.1 | **T-04** | `computable = bool(bom_id) and all(l["status"]=="ok" for l in lines)`; `apply_model_cost` menolak size `computable=False` (tidak menulis `hpp_bom`/FG `hpp`/katalog) dan mencatat gap. | `core/product_costing.py:660,851` | Uji unit: BOM 2 baris, 1 `unlinked` → `computable=False`, master tidak berubah. Regresi `test_mrp_cost_stock.py`, `tests/test_iter*hpp*`. |
| 1.2 | **T-05** | Hapus `utils/cascade_delete.py`; `master_data.py` impor `from cascade_delete import cascade_delete_po`. Skrip sekali-jalan: cari AR `status=draft` dengan `linked_maklon_po_id` tanpa PO → laporkan (hapus setelah konfirmasi owner). | `backend/utils/cascade_delete.py`, `routes/master_data.py:21`, `scripts/find_orphan_draft_ar.py` (baru) | Hapus PO via `master_data` → `po_accessories`, `production_variances`, mirror `dewi_maklon_pos`, AR draft ikut bersih. |
| 1.3 | **T-06** | Di `PUT /api/dewi/maklon/pos/{id}`: bila `mirror_of=='production_pos'` → 409 `"PO ini cermin PO produksi — ubah di Portal Produksi"`. Frontend: tampilkan pesan & tombol ke layar PO produksi. | `routes/dewi_maklon_pos.py:557`, UI maklon PO edit | PUT pada mirror → 409; PUT pada PO asli → 200. |
| 1.4 | **T-07** | Sebelum hapus job: cek periode terkunci → 409; `_void_je_by_source(db,"production_job",f"wip_fg_job:{jid}")`; `fg_cost_layers.delete_many({gl_job_id})`; `rahaza_hpp_snapshots.delete_many({job_id})`; `rahaza_wip_events.delete_many({job_id})`. Terapkan juga di `vendor_shipment.py:563`. Ekstrak ke `core/production_job_delete.py` agar 2 jalur pakai 1 fungsi. | `routes/production_execution.py:717`, `routes/vendor_shipment.py:563` | Job selesai (ada JE `wip_fg_job:*`) dihapus → JE `voided`, cermin hilang, layer & snapshot 0; job di periode terkunci → 409. |
| 1.5 | **T-08** | Satu konstanta `core/roles.py: FINANCE_ROLES = ("superadmin","admin","owner","accounting","staff_keuangan","manager_keuangan","finance","accountant")`, `APPROVER_ROLES = FINANCE_ROLES + ("hr","hr_manager","manager")`. Ganti ±13 gerbang di 8 berkas. | `employee_expense_claims`, `employee_travel_requests`, `employee_travel_settlements`, `employee_expense_gl_mapping`, `employee_expense_category_master`, `employee_expense_summary`, `rahaza_ar_360`, `rahaza_channel_gl_mapping` | Login `accounting@…` → approve klaim biaya 200 (bukan 403). Tambah uji RBAC ke `backend_test_f6_rbac.py`. |
| 1.6 | **T-14 (a,b)** | (a) `mature_ap_from_cmt_receipt`: baris `rate==0 & qty_actual>0` → `variance_flagged=True`, `variance_reasons+=["tarif CMT 0 untuk N pcs"]`, tampil di dokumen tagihan. (b) Teks gap `cmt_rate_missing` → "Isi Biaya Jahit per SKU di layar **Biaya Jahit SPK**" dengan `target` layar tsb. | `routes/production_maklon_bridge.py:326-430`, `core/product_costing.py:435` | Penerimaan CMT tanpa tarif → tagihan draft berbendera variance + alasan; gap HPP menunjuk layar yang bisa diisi. |
| 1.7 | **T-09 (1)** | Invarian **INV-JL-2**: setiap JE `posted` punya cermin dengan Σdebit = Σkredit = kepala; laporkan JE tanpa cermin. Tambah ke `verify_data_integrity.py` (pola INV-JL-1 di baris 134-141) + `gate.sh`. | `scripts/verify_data_integrity.py` | Jalankan pada seed go-live → 0 pelanggaran (atau daftar untuk diperbaiki). |
| 1.8 | **T-10** | Indeks unique parsial `(source_module, source_ref)` dengan `partialFilterExpression: {status: {$ne: "voided"}}`; migrasi: deteksi duplikat aktif dulu (laporkan, jangan hapus otomatis). `_create_posted_je` (`rahaza_posting.py:132`, insert kepala baris 222, cermin baris 249) tangkap `DuplicateKeyError` → kembalikan JE existing via `_find_existing_je` (baris 125). Kasbon: `_post_kasbon_gl` (`dewi_kasbon.py:44`) dipanggil di baris 362, 426, 609 — naikkan `gl_result.ok=false` ke respons (`ok:false` + pesan) agar layar tidak "berhasil". | `server.py:577`, `routes/rahaza_posting.py:125-249`, `routes/dewi_kasbon.py:44,362,426,609` | Dua POST paralel sumber sama → 1 JE. Kasbon dengan profil posting hilang → respons error terlihat. |

**Catatan Fase 1 lain:** 1.3 pola penjaga mirror yang bisa disalin: `dewi_maklon_billing.py:319` (`if po.get('mirror_of') == 'production_pos'`).
1.6(a) fungsi target `mature_ap_from_cmt_receipt` di `production_maklon_bridge.py:294` (loop baris 338-342 menghitung `rate`, `variance_flag` baris 396,
disimpan baris 430 & 471). 1.4 fungsi `_void_je_by_source(db, source_module, source_ref, user, reason)` di `rahaza_posting.py:254`; `source_ref`
job = `f"wip_fg_job:{job_id}"` (baris 1984); contoh pembersihan layer/snapshot di `routes/maklon_seed.py:427-428`.

### FASE 2 — Otorisasi (T-01) — target 1–2 sesi, bertahap
Titik kunci: `backend/auth.py:86 require_auth` (memuat `_permissions`, tidak menegakkan); peran di-seed di `auth.py:238 _seed_default_roles`;
`middleware/marketing_scope_guard.py:79-81` melewatkan peran non-toko; gerbang yang sudah ada dan bisa ditiru: `routes/shared.assert_can_act`,
`routes/rahaza_coa._require_fin`, `production_execution.py:720-721` (`deny_klien` + cek superadmin).
| # | Langkah | Detail |
|---|---|---|
| 2.1 | Inventaris otomatis | Skrip baru `scripts/audit_authz.py` (AST atas `backend/routes/**`): daftar endpoint tulis tanpa gerbang peran → CSV per router (`router, method, path, fungsi, baris`). Baseline sesi ini (pola kasar): 580/999 tulis, 79 DELETE. Pasang di `gate.sh` sebagai "angka tidak boleh naik". |
| 2.2 | Dependensi router-level | Buat `core/authz.py`: `require_roles(*roles)`, `deny_roles(*roles)`. Di `server.py` (semua `include_router`, baris ±1700-2400) tambahkan `dependencies=[Depends(deny_roles("vendor","cmt_vendor","buyer","klien_maklon","pic_toko","marketing_kol","cs_staff"))]` pada router internal (semua kecuali router portal eksternal: `vendor_portal`, `dewi_client_*`, `creator_*`, `live_host_*`, `marketing_*` yang memang untuk `pic_toko`). Ini menutup lintas-portal dalam 1 perubahan. |
| 2.3 | 79 DELETE | Dari CSV 2.1: tambah gerbang eksplisit per endpoint (admin/owner/spv domain). Mulai berkas terbanyak: `production_execution.py`, `production_pos.py`, `master_data.py`, `warehouse.py`, `operations.py`. |
| 2.4 | SDM & Biaya/HPP | `dewi_hris_performance.py:456 submit_review` → `actor=="manager"` hanya bila `user` = reviewer/atasan (`review.reviewer_id`) atau peran `hr`/`hr_manager`; `dewi_rnd_hpp.py:779 delete_hpp` → `rnd_staff`/finance/admin; `dewi_client_admin.py:139 DELETE portal-accounts` → admin/owner/`admin_maklon`. |
| 2.5 | Sisanya per domain | Marketing 168 (sudah ada scope guard; tambah gerbang peran), Gudang 92, SDM 45, R&D 37, Workspace 21, LMS 16, Keuangan 14. |
| Verifikasi | Matriks RBAC testing agent: tiap peran × endpoint contoh (200/403); pakai akun `{role}@dewiaditya.id`. `audit_authz.py` di gate: jumlah tanpa gerbang menurun monoton. Regresi `backend_test_f6_rbac.py`, `backend_test_procurement_rbac.py`. |

### FASE 3 — SSOT koleksi hantu (T-03, T-17, T-18, T-19) — target 1 sesi
| # | Langkah |
|---|---|
| 3.1 | Gate baru `scripts/check_collection_writers.py`: koleksi yang dibaca kode (`db.<nama>.find/count/aggregate`) wajib punya ≥1 penulis (`insert/update/replace/bulk`) di `routes/ core/ services/ utils/` (kecuali daftar putih untuk koleksi yang ditulis mesin impor deklaratif / migrasi). Pasang di `gate.sh`. |
| 3.2 | **T-03**: 22 pembaca `rahaza_work_orders` (+`core/collection_registry.py`): `routes/dashboard_routes.py:78,79,340,341,355,356,530`, `wms_capacity_planning.py:52,69`, `rahaza_next_actions.py:103,143,172,211,457`, `rahaza_hpp.py:91,510,519`, `dewi_production_reports`, `dewi_maklon_pos`, `production_control_tower`, `rahaza_shipments`, `rahaza_posting`, `rahaza_notifications`, `dewi_management_tools`, `rahaza_admin_shared`, `universal_scan`, `dewi_executive_report`, `production_maklon_bridge`, `rahaza_sprint22`, `dewi_maklon`, `production_stage_tracking`, `rahaza_shift_handover`, `analytics_ai`, `services/ai_aggregates/production_aggregates.py`, `services/ai_aggregates/rahaza_aggregates.py`. Buat adaptor `core/wo_reader.py` di atas `production_jobs` (peta: `quantity→qty`, `qty_completed→completed_qty`, `order_code→job_number`, `product_name→model_name`, `target_date→target_date||due_date`; status `in_progress/planned/released`) lalu 22 berkas cukup ganti pemanggilan. Cek dulu skema `production_jobs` nyata di seed (`mongosh test_database --eval 'db.production_jobs.findOne()'`). |
| 3.3 | **T-17 HRIS**: `routes/dewi_portal_saya_ext.py:167,173,179,185` baca `hris_*` → ganti ke `dewi_perf_assignments/dewi_perf_reviews/dewi_perf_cycles/dewi_perf_kpis` (penulis: `routes/dewi_hris_performance.py`). **Hapus baris 32-35 di `migrations/td011_cleanup_orphan_collections.py`** (mendaftar `dewi_perf_*` sebagai yatim — akan menghapus data nyata bila dijalankan). |
| 3.4 | **T-17 lain**: `services/ai_aggregates/hr_aggregates.py:9` & `routes/dewi_hr_ai.py:343,354` (`rahaza_attendance`) → `rahaza_attendance_events` (penulis `rahaza_auto_attendance_zkteco.py`, `rahaza_attendance_sessions.py`); `rahaza_qc_events` di `dewi_executive_report.py:147`, `analytics_ai.py:294`, `services/ai_aggregates/rahaza_aggregates.py:32,84` → sumber QC nyata (`cmt_receipts` reject / `production_progress`) atau hapus metriknya; `capacity_config` di `wms_capacity_planning.py:42` → endpoint GET/PUT + form kecil, atau ganti konstanta; koleksi ditulis-tak-dibaca (`fg_cost_consumptions` — `core/fg_cost_layers.py:238`, `invoice_change_history`, `dewi_maklon_inventory`, `workspace_shares`, `wh_rca_audit`, `wh_placement_movements`): putuskan tampilkan (endpoint GET + tab "Riwayat") atau berhenti menulis. |
| 3.5 | **T-18** hapus `backend/services/stock_service.py` (0 importir; yang benar `core/stock_service.py`). **T-19** hapus `backend/core/collection_registry.py` (0 importir) atau jadikan sumber `admin_backup.py:1280,1321` menggantikan `data/collection_registry.py` — pilih satu. |

### FASE 4 — Ketahanan & kinerja (T-12, T-09 (2,3), T-11, T-21, T-22, T-23, T-24) — target 1 sesi
| # | Langkah |
|---|---|
| 4.1 | **T-12** indeks (di `server.py` blok `create_index` ±baris 400-800, atau langsung di 4.2): `vendor_shipment_items(shipment_id)`, `(po_item_id)`; `buyer_shipments(po_id)`; `vendor_shipments(po_id)`; `cmt_receipts(status)`, `(po_id)`; `wh_positions(rack_id)`, `(status)`, `(barcode)`; `wh_pending_movements(type,status)`, `(source_type,source_id)`; plus `active` pada `rahaza_boms`, `rahaza_employees`, `rahaza_locations`, `rahaza_leave_types`. |
| 4.2 | **T-24** pindahkan 416 `create_index` dari `server.py` (startup) ke `migrations/ensure_indexes.py` (idempoten; dipanggil `deploy/update.sh` + opsional saat boot via env `ENSURE_INDEXES=1`). |
| 4.3 | **T-09 (2)** `rahaza_posting.py:222-249`: tulis cermin (`journal_lines.insert_many`) DULU, kepala (`journal_entries.insert_one`) TERAKHIR → kegagalan tengah = baris yatim yang sudah dideteksi INV-JL-1. **(3)** Opsional: Mongo replica set 1 node di `deploy/docker-compose.yml` (`--replSet rs0` + `rs.initiate()` sekali) → bungkus `_create_posted_je` dalam transaksi. |
| 4.4 | **T-11** `routes/dewi_bank_reconciliation.py:129 _gl_balance_until` → pakai cermin `rahaza_journal_lines` (konsisten dengan `rahaza_posting.py:531 gl_balances_by_code` & `core/fin_statements.py:74 _sum_by_account`); tambah uji "saldo rekonsiliasi == saldo kas&bank == neraca saldo" untuk 1 akun bank. Pastikan setiap jalur void/edit JE menghapus cermin (audit `grep -rn "status.*voided" routes/`). |
| 4.5 | **T-21** `to_list(None)` terbanyak: `production_execution.py` (38), `production_pos.py` (35), `buyer_shipment.py` (24), `vendor_shipment.py` (23), `exceptions.py` (10) — paginasi/`limit` + agregasi di DB; pakai `core/pagination.py`. Prioritaskan yang dipanggil layar daftar/laporan. |
| 4.6 | **T-23** `server.py:2433-2439`: hilangkan default `'*'`; bila `ENV=production` & `CORS_ORIGINS` kosong → `raise RuntimeError` saat boot. **T-02 (kode)** `auth.py:176 seed_initial_data`: di production baca `BOOTSTRAP_ADMIN_EMAIL/PASSWORD` dari env, tolak boot bila kosong & belum ada superadmin; hapus baris 10 `deploy/README_DEPLOY.md`. |
| 4.7 | **T-22** 9 berkas dengan `verify_token_str` (`auth.py:77`): `wms_fabric_rolls`, `wms_fg_labels` (`_auth_or_token` baris 39), `wms_audit`, `wms_material_labels`, `wms_labels`, `wms_delivery_notes`, `file_storage`, `websocket`, `communication/websocket`. Buat `POST /api/auth/download-token` (JWT 5 menit, claim `aud="download"`, `resource=`) + `verify_download_token`; ganti `_auth_or_token` untuk memakai itu. Sementara: `deploy/Caddyfile:36` tambahkan `format filter { request>uri query delete }`. |

### FASE 5 — Disiplin rekayasa (T-13, T-15, T-16, T-20, T-14c, T-28, T-26) — target 1 sesi
| # | Langkah |
|---|---|
| 5.1 | **T-13/T-16** buat `.github/workflows/ci.yml`: `ruff check backend`, `cd frontend && yarn install --frozen-lockfile && yarn lint && yarn build`, `pytest backend/tests/unit -n 0` (hermetik). `deploy/Dockerfile.frontend:12` → `yarn install --frozen-lockfile --network-timeout 600000`. Mulai commit per perubahan bermakna (repo kini 1 commit). |
| 5.2 | **T-15** folder baru `backend/tests/unit/` (tanpa server; `mongomock-motor` atau fixture DB terisolasi) untuk `core/*`: mulai `product_costing` (T-04), `bom_fill`, `uom`, `production_qty_ledger`, `catalog_stock`, `marketing_returns` — 6 alur yang audit sudah buktikan bisa diuji hermetik. Jest: kembalikan ≥1 suite smoke (infrastruktur `frontend/src/setupTests.js` + `craco.config.js` masih ada) ATAU hapus klaim "204 uji Jest" dari `README.md:122`. |
| 5.3 | **T-20** `core/bulk_approve.py: bulk_approve(db, user, ids, *, collection, number_field, module, allowed_roles, allowed_from_status=("submitted",))`; ganti isi `employee_expense_claims.py:566`, `employee_travel_requests.py:680`, `employee_travel_settlements.py:841`. |
| 5.4 | **T-14 (c)** kolom `tarif_jahit_per_pcs` di sheet `11_VENDOR_CMT` (`data_import/TEMPLATE_MASTER_DA.xlsx` & `CONTOH_TERISI_MASTER_DA.xlsx`; importir: cari `11_VENDOR_CMT` di `backend/routes/data_transfer.py`/`core/*import*`) → `dewi_cmt_partners.rate_per_pcs` (pembaca sudah ada: `production_sewing_cost.py:114` kandidat tarif, `dewi_cmt_lifecycle.py:219`). Tampilkan sebagai pembanding di layar Biaya Jahit SPK. |
| 5.5 | **T-28** pindahkan 60 `test_*.py`/`backend_test*.py` akar → `tests/legacy/`; hapus `backend/routes/dewi_kpi.py.old` & `dewi_kpi.py.pre-refactor-backup`; blok status `README.md` → `docs/CHANGELOG_SESI.md`; `test_result.md` (484 KB) → `docs/archive/`. **T-26** hapus `mobile/` (36 berkas, 0 panggilan API) atau beri `mobile/README.md` "kerangka Expo, belum dimulai". |

### Backlog rawat (tanpa jadwal): T-25 (307 endpoint tanpa pemanggil — matikan bertahap dengan 410), T-27 (`{items,total}` seragam + `asList()` di FE).

---

## C. URUTAN EKSEKUSI YANG DISARANKAN
1. **Fase 0** hari ini (owner, 10 menit).
2. **Fase 1** sesi berikutnya — 8 perbaikan kecil, semuanya bisa diuji unit + testing agent dalam 1 sesi; ini menutup semua P0 uang/data kecuali T-01/T-03.
3. **Fase 2** (T-01) — mulai dari langkah 2.1–2.2 (tolak peran eksternal di level router: dampak terbesar, perubahan terkecil), lalu DELETE.
4. **Fase 3** (koleksi hantu) — memulihkan dasbor/laporan yang selama ini nol.
5. **Fase 4–5** — ketahanan & disiplin.

## D. DEFINISI SELESAI per fase
- Semua perubahan lolos `bash scripts/gate.sh` + suite `pytest` terkait + testing agent (backend & UI untuk yang menyentuh layar).
- Gate baru (INV-JL-2, `check_collection_writers.py`, `audit_authz.py`) dipasang di `gate.sh` supaya kelas cacat tidak kambuh.
- `memory/PRD.md` diperbarui; DB uji dikembalikan ke `seed/DA_SEED_GOLIVE.archive.gz` setelah uji yang mengubah data.

## E. PROTOKOL PER LANGKAH (agar bisa diserahkan antar-sesi)
1. Sebelum menyentuh kode: `mongodump --gzip --archive=/tmp/pre.archive.gz --db test_database` (atau cukup andalkan restore seed).
2. Buka berkas:baris yang disebut di tabel; **konfirmasi kode masih sama** (nomor baris bisa bergeser bila ada perubahan lain — cari berdasarkan nama fungsi).
3. Tulis uji dulu bila memungkinkan (unit di `backend/tests/unit/`, atau skrip API di `/app/tests/` seperti `tests/test_bom_otomatis_roundtrip.py`).
4. Perubahan minimal sesuai kolom "Perubahan"; jangan refactor di luar lingkup.
5. Jika menyentuh `frontend/src`: `bash /app/scripts/rebuild_frontend.sh` sebelum screenshot/testing agent.
6. Testing agent dengan konteks lengkap (kredensial, endpoint, perintah restore DB, "frontend static bundle — jangan ubah src").
7. Catat di `memory/PRD.md` (bagian atas, format "SESI <tanggal> — …") + tandai langkah selesai di berkas ini (kolom Status di bawah).
8. Restore DB seed bila uji mengubah data.

## F. STATUS LANGKAH (perbarui setiap sesi)
| Langkah | Status | Sesi / bukti |
|---|---|---|
| 0.1–0.2 | belum (aksi owner di VPS) | — |
| 1.1 – 1.8 | **SELESAI** (sesi 2026-09-22, commit `616e387`) | `tests/test_fase1_audit.py` 22/22 PASS; testing agent iteration_219. Rincian: 1.1 `computable` = semua baris `ok` + `apply_model_cost` menolak size tidak computable; 1.2 `utils/cascade_delete.py` dihapus, `scripts/find_orphan_draft_ar.py`; 1.3 PUT mirror → 409 `PO_IS_MIRROR` (`target: maklon-pos-engine`; FE aktif tidak memanggil PUT ini, hanya `_archive/`); 1.4 `core/production_job_delete.py` dipakai 2 jalur; 1.5 `core/roles.py` (FINANCE_ROLES/APPROVER_ROLES) di 8 berkas; 1.6 `zero_rate_pcs`+`variance_reasons` di tagihan CMT (UI `ProductionCMTBillingModule`), gap `cmt_rate_missing` → `prod-sewing-cost`; 1.7 INV-JL-2 di `verify_data_integrity.py`; 1.8 indeks `uniq_active_source_ref` (partial: status∈{posted,draft} & source_ref string) + `DuplicateKeyError`→JE existing + kasbon `ok:false`+`message` (UI `FinanceKasbonModule` toast peringatan) + `scripts/find_duplicate_active_je.py` di gate. |
| 2.1 – 2.2 | **SELESAI** (sesi 2026-09-22, commit `161c712` + patch) | `scripts/audit_authz.py` (baseline 189 endpoint tulis tanpa gerbang; sebelum 2.2: 685) di `gate.sh`; `core/authz.py` `deny_roles`/`require_roles`; 259 `include_router` diberi `dependencies=` (`_DENY_EXTERNAL` 118, `_DENY_EXTERNAL_AND_MKT` 99 domain keuangan/produksi/gudang/R&D/admin, `_DENY_MKT` 42 router sadar-vendor). `production_rbac.EXTERNAL_ROLES` kini memuat `buyer`. Matriks: `tests/test_fase2_rbac.py` 58/58. **Keputusan:** peran portal marketing (`pic_toko`/`marketing_kol`/`cs_staff`) adalah KARYAWAN → tetap boleh HR self-service, notifikasi, `rahaza_variants`, `rahaza_product_categories`, `wh/returns`, `sku_bridge`, `dewi_scheduler`. |
| 2.3 – 2.5 | **SELESAI** (sesi 2026-09-22 #2) | 2.3: 77 dekorator DELETE diberi `dependencies=only(*ROLES)` (`core/authz.only`, konstanta domain `core/roles.py`: MGMT/HR/PRODUCTION/WAREHOUSE/RND/MAKLON/MARKETING[_CS]) lewat `scripts/_patch_fase23_delete_gates.py` (idempoten); kepemilikan: `DELETE /rahaza/leaves/{id}` hanya pemohon/HR, `DELETE /rahaza/delegations/{id}` hanya pendelegasi/HR. 2.4 sudah tertutup sesi lalu (`submit_review`, `delete_hpp`, portal-accounts). 2.5: server gate `_DENY_EXTERNAL` untuk `document_number_configs`, `comm` (chat internal), `universal_scan`, `marketing_orders`; gerbang fungsi `push/send` (HR/admin), `webhooks/manual` + `/events/{id}/reprocess` (MARKETING_ROLES), `notifications/trigger/wo-due-scan` (PRODUCTION_ROLES). `audit_authz.py` kini melihat `dependencies=` di dekorator, sub-router yang berbagi objek `router` (dewi_rnd_*, asset/*, communication/*), pola kepemilikan (`owner_id/created_by != user`, `_admin*(`), dan daftar `EXEMPT` (webhook platform bertanda tangan, login portal klien, ganti sandi, notifikasi self-service, lampiran) → **TANPA GERBANG SAMA SEKALI: 0 (baseline 0), DELETE tanpa gerbang fungsi: 0**. Bukti: `tests/test_fase23_delete_gates.py` 66/66; regresi `test_fase2_rbac.py` & `test_fase1_audit.py` hijau; `verify_rbac_idor.py` 806/0, `verify_adversarial_5xx.py`, `health_check.py` hijau. |
| 3.1 – 3.5 | **SELESAI** (sesi 2026-09-22 #3) | `tests/test_fase3_ssot.py` 41/41; testing agent iteration_221. 3.1 `check_collection_writers.py --gate` di `gate.sh` (baseline 21, dari 27). 3.2 `core/wo_reader.py` — 0 pembaca `rahaza_work_orders` tersisa. 3.3 annual-review → `dewi_perf_*` (KPI = tertanam di assignment); td011 tidak lagi mendaftar `dewi_perf_*`. 3.4 `core/qc_reader.py` (cmt_receipts) untuk analytics_ai/executive_report/rahaza_aggregates; `hr_aggregates` → `rahaza_attendance_events`; `active_alerts` → `notifications`; `GET/PUT /api/capacity/config` (PUT = PRODUCTION_ROLES; UI form belum). 3.5 `services/stock_service.py` dihapus; **`core/collection_registry.py` dipertahankan** (koreksi T-19: dipakai `scripts/gate_marketing_ssot.py`). |
| 4.1 – 4.7 | **SELESAI** (sesi 2026-09-22 #4, dokumentasi & 1 bug ditutup sesi #5) | `tests/test_fase4_hardening.py` (46 cek) SEMUA PASS; testing agent iteration_222 (+ retest sesi #5). 4.1/4.2 **T-12/T-24** 420 `create_index` pindah ke `migrations/ensure_indexes.py` (idempoten; `deploy/update.sh`; boot `ENSURE_INDEXES` bawaan 1, set 0 di produksi) + indeks baru `vendor_shipment_items(shipment_id, po_item_id)`, `buyer_shipments/vendor_shipments(po_id)`, `cmt_receipts(status, po_id)`, `wh_positions(rack_id,status,barcode)`, `wh_pending_movements`, `active` pada `rahaza_boms/employees/locations/leave_types`; `server.py` sisa 1 `create_index`. 4.3 **T-09.2** `rahaza_posting._create_posted_je`: cermin `rahaza_journal_lines` ditulis DULU, kepala TERAKHIR; duplikat sumber → cermin JE yang kalah dibuang. 4.4 **T-11** `dewi_bank_reconciliation._gl_balance_until` → cermin `rahaza_journal_lines` (= `gl_balances_by_code` & neraca saldo). 4.5 **T-21** `core/pagination.py` (`LEGACY_DEFAULT_CAP`), `?limit=` di layar daftar (`production_execution`, `production_pos`, `buyer_shipment`, `vendor_shipment`, `exceptions`, `production-variances`) + gate `scripts/check_unbounded_queries.py --gate` (baseline 191) di `gate.sh` & CI. 4.6 **T-23** `CORS_ORIGINS` tanpa default `'*'` di produksi (`RuntimeError` saat boot); **T-02** `BOOTSTRAP_ADMIN_EMAIL/PASSWORD` wajib di produksi bila belum ada superadmin. 4.7 **T-22** `POST /api/auth/download-token` (JWT 5 menit, `aud=download`, `resource`) + `auth.verify_download_token` dipakai 7 router unduhan (`wms_*`, `file_storage`); token unduh ditolak sebagai sesi; `deploy/Caddyfile` membuang `token`/`auth` dari access log; transisi `ALLOW_SESSION_TOKEN_IN_QUERY` (bawaan 1; set 0 setelah FE seluruhnya pakai download-token). **Bug sesi #5:** token sesi tanpa claim `aud` membuat PyJWT melempar `MissingRequiredClaimError` (bukan `InvalidAudienceError`) → 401 palsu meski flag=1; kini kedua kelas ditangkap (`backend/tests/unit/test_auth_download_token.py`). |
| 5.1 – 5.5 | **SELESAI** (sesi 2026-09-22 #4–#5) | 5.1 **T-13/T-16** `.github/workflows/ci.yml` (ruff F821/F811/F401/E9 · `pytest tests/unit -n 0` · 3 gate statis · `yarn install --frozen-lockfile && yarn build`); **sesi #5:** 124 F401 pre-existing di-`--fix` → ruff "All checks passed!" (lint CI hijau); `deploy/Dockerfile.frontend` `--frozen-lockfile --network-timeout 600000`. 5.2 **T-15** `backend/tests/unit/` hermetik (`test_core_pure.py` 7 + `test_auth_download_token.py` 4 = 11 passed); README: klaim "204 uji Jest" dikoreksi (suite tidak ada; uji FE = build CI). 5.3 **T-20** `core/bulk_approve.py` dipakai 3 endpoint: `POST /api/hr/expenses/claims/bulk-approve` (`claim_ids`), `/api/hr/expenses/travel/bulk-approve` (`travel_ids`), `/api/hr/expenses/settlements/bulk-approve` (`settlement_ids`) — peran `APPROVER_ROLES` (accounting 200, operator 403). 5.4 **T-14c** kolom `tarif_jahit_per_pcs` di sheet `11_VENDOR_CMT` (`scripts/master_template_spec.py`, `import_master_template.py` → `vendor_partners.rate_per_pcs` + `dewi_cmt_partners.rate_per_pcs`), dibaca `production_sewing_cost` sebagai kandidat tarif `master_partner_cmt`. 5.5 **T-28** `.old`/backup routes dihapus; `test_result.md` → `docs/archive/`; **sesi #5:** 19 `backend_test*.py`/`test_*.py` sisa di akar `backend/` → `tests/legacy/backend_root/`; blok status README (2026-05→09) → `docs/CHANGELOG_SESI.md`, README ditulis ulang ringkas. **T-26** `mobile/README.md` (kerangka Expo, belum dimulai). |
| Catatan runtime (sesi #5) | — | Temuan testing agent iteration_222 yang ternyata salah path, bukan bug: daftar progress = `GET /api/production-progress?limit=` (router `production_execution` prefix `/api`); bulk-approve prefix `/api/hr/expenses/...` (bukan `/api/hr/expense/claims`). `ALLOW_SESSION_TOKEN_IN_QUERY="1"` kini ada di `backend/.env` preview (`bootstrap.sh` `ensure_env`). |

**Catatan lingkungan sesi 2026-09-22:** akun `{role}@dewiaditya.id` tidak ada di seed go-live (karyawan nyata memakai sandi sendiri). Pakai `scripts/seed_test_accounts.py` → `uji.{role}@dewiaditya.id` / `Dewi@123` (lihat `memory/test_credentials.md`). Rate-limit login 5 gagal/akun.

**Perintah pembuka sesi berikutnya yang disarankan dari user:** FASE 1–5 SELESAI. Sisa: **FASE 0** (aksi owner di VPS: ganti sandi `Admin@123`, set `CORS_ORIGINS` eksplisit, `BOOTSTRAP_ADMIN_*`, `ENV=production`) dan **backlog rawat**: (a) FE unduhan → semua pakai `POST /api/auth/download-token` lalu set `ALLOW_SESSION_TOKEN_IN_QUERY=0`; (b) form UI kecil `GET/PUT /api/capacity/config`; (c) 21 koleksi hantu baseline `check_collection_writers.py`; (d) T-25 (307 endpoint tanpa pemanggil → 410 bertahap), T-27 (`{items,total}` seragam + `asList()`); (e) T-09.3 replica set + transaksi JE (opsional).
