# TEMUAN — Portal Keuangan (Finance)

**Repo:** `github.com/pandeyoga/DAHOST` · **Commit acuan:** `4ce149a` (22 Sep 2026) · **Tanggal:** 23 September 2026 · **Versi:** 1.0
**Cakupan:** 24 menu Portal Keuangan beserta 28 tab di lima hub, dan ±40 berkas rute backend yang melayaninya.
**Berkas pendamping:** `MANUAL_PORTAL_FINANCE.pdf`, `UJI_FINANCE.zip` (skrip uji + log, untuk dijalankan ulang)

---

## Cara membaca berkas ini

Setiap temuan punya empat bagian: **gejala** (apa yang dialami pengguna), **bukti kode** (baris
yang bertanggung jawab), **pembuktian** (keluaran uji yang benar-benar dijalankan), dan **usulan perbaikan**.

Uji dijalankan pada **aplikasi utuh** — `server.py` diimpor apa adanya (2.507 endpoint, semua gerbang
dan middleware aktif) — dengan basis data tiruan (`mongomock_motor`) dan token JWT asli per peran.
Bagan akun dan profil posting diisi lewat endpoint resmi `POST /api/rahaza/admin/seed-all-accounting`.
Artinya setiap angka di bawah adalah jawaban server yang sama dengan yang akan diterima layar.

Sebagai kontrol, satu uji terpisah (T9) memeriksa bagian inti yang **seharusnya benar** — dan
semuanya lulus (5/5). Jadi kegagalan di uji lain bukan karena alat ujinya rusak.

---

## Ringkasan

| Kode | Judul singkat | Tingkat | Pembuktian |
|---|---|---|---|
| **FIN-03** | Kasbon tanpa pagar peran: bisa diajukan untuk orang lain, disetujui, dan dicairkan sendiri | **Kritis** | Eksekusi T2 |
| **FIN-01** | Rekap Keuangan: 7 dari 7 angka salah | **Tinggi** | Eksekusi T1 |
| **FIN-02** | Peran resmi portal ditolak di pintunya sendiri; tombol disembunyikan dari tim keuangan | **Tinggi** | Eksekusi T8 + kode |
| **FIN-04** | Pintu samping yang menulis jurnal & laporan keuangan terbuka bagi semua peran internal | **Tinggi** | Eksekusi T2, T3, T4 |
| **FIN-05** | Kas Kecil: kode akun salah, penutupan terjurnal terbalik, pengembalian tanpa batas | **Tinggi** | Eksekusi T3 |
| **FIN-06** | Aset Tetap: posting per baris tanpa jurnal, saldo menurun ganda 12× kecil, pelepasan tanpa akumulasi | **Tinggi** | Eksekusi T4 |
| **FIN-07** | Diskon pembelian diabaikan server | **Tinggi** | Eksekusi T5 |
| **FIN-08** | Realisasi anggaran selalu nol | **Tinggi** | Eksekusi T5 |
| **FIN-09** | AR 360, Laporan Eksekutif, Prediksi Kas membaca status/kolom yang tidak ditulis | **Tinggi** | Eksekusi T5 |
| **FIN-10** | Impor CSV rekening koran membaca angka 100× lipat | **Tinggi** | Eksekusi fungsi |
| **FIN-11** | Menyetujui edit total invoice AP menghapus jurnalnya | **Sedang–Tinggi** | Eksekusi T6c |
| **FIN-12** | Penyelesaian dinas atas uang muka yang belum dibayar membalik arah utang | **Sedang–Tinggi** | Eksekusi T6a |
| **FIN-13** | Transfer bank "Selesai" tanpa jurnal; void menulis pembalik tunggal | **Sedang** | Eksekusi T6d |
| **FIN-14** | Akrual berulang menggandakan diri | **Sedang** | Eksekusi T6b |
| **FIN-15** | Nilai tak hingga lolos validasi jurnal dan melumpuhkan laporan | **Sedang** | Eksekusi T7 |
| **FIN-16** | Potongan kasbon bisa terjadi dua kali pada periode yang sama | **Sedang** | Kode |
| **FIN-17** | Posting draf jurnal tidak atomik (klik ganda = baris ganda) | **Sedang** | Kode |
| **FIN-18** | Rekonsiliasi: penyesuaian bisa dijurnal dua kali; impor tanpa cek duplikat | **Sedang** | Kode |
| **FIN-19** | Rekonsiliasi pencairan marketplace melewati lingkup toko | **Sedang** | Kode |
| **FIN-20** | Enam catatan kecil (akun klaim dipilih klaimer, bulk-post selalu gagal, dll.) | **Rendah–Sedang** | Kode |
| **FIN-21** | Seed akuntansi & pemetaan GL bawaan yang keliru | **Rendah** | Eksekusi + kode |

**Gambaran besarnya:** mesin posting inti sehat. Setiap jurnal otomatis diperiksa seimbang, akunnya
aktif dan bukan header, periodenya terbuka, dan database menolak jurnal ganda untuk satu sumber.
Laporan inti (Neraca Saldo, Buku Besar, Laba Rugi, Neraca) membaca buku besar langsung dan bisa dipercaya.
Masalahnya ada di **tepi**: pintu yang memotong jalan di luar mesin itu, dan laporan turunan yang
menghitung ulang dari dokumen sumber dengan nama kolom/status yang meleset.

---

## FIN-03 — Kasbon tanpa pagar peran

**Tingkat:** Kritis · **Menu:** Kasbon & Pinjaman · **Berkas:** `backend/routes/dewi_kasbon.py`

### Gejala

Siapa pun yang login dengan peran internal (selain akun eksternal dan marketing) bisa menjalankan
seluruh siklus kasbon sendirian — termasuk atas nama karyawan lain.

### Bukti kode

Router didaftarkan dengan gerbang yang hanya menolak akun eksternal & marketing:

```python
# backend/server.py:1122
app.include_router(dewi_kasbon_router, dependencies=_DENY_EXTERNAL_AND_MKT)
```

Tidak ada satu pun handler yang memeriksa peran. Karyawan yang diajukan diambil dari isian:

```python
# dewi_kasbon.py:153 — submit_kasbon_request
employee_id = body.get("employee_id") or user.get("employee_id") or user.get("id")
```

```python
# dewi_kasbon.py:305–331 — hr_review_kasbon: hanya require_auth
async def hr_review_kasbon(req_id: str, request: Request,
                           db: AsyncIOMotorDatabase = Depends(get_db), user=Depends(require_auth)):
    ...
    if doc.get("status") != "submitted": ...
    new_status = "hr_approved" if action == "approve" else "hr_rejected"
```

```python
# dewi_kasbon.py:337–379 — finance_disburse: hanya require_auth, lalu jurnal Dr 1-1320 / Cr Bank
gl_result = await _post_kasbon_gl(db, "employee_loan_disbursement", f"kasbon-disburse-{req_id}", ...)
```

```python
# dewi_kasbon.py:666–672 — data demo, tanpa gerbang lingkungan
@router.post("/seed")
async def seed_demo(db = Depends(get_db), user=Depends(require_auth)):
    existing = await db.dewi_kasbon_requests.count_documents({})
    if existing > 0: return {...}
    emps = await db.rahaza_employees.find({"active": True}, ...).limit(5).to_list(5)
```

Tidak ada pemeriksaan pemohon ≠ penyetuju ≠ pencair.

### Pembuktian (T2)

```
ajukan kasbon atas nama E2  200   (login sebagai operator E1)
setujui sendiri (hr-review) 200
cairkan sendiri             200   {'ok': True, 'je_number': 'JE-20260923-0002'}
dokumen kasbon: {'employee_id': 'E2', 'employee_name': 'Sari (rekan kerja)', 'status': 'disbursed',
                 'hr_reviewed_by': 'operator', 'disbursed_by': 'operator'}
POST /api/dewi/kasbon/seed -> 200 | dokumen kasbon tercipta: 5
```

Penggajian berikutnya akan memotong gaji Sari (`rahaza_payroll_shared.py:494–520` mengambil semua kasbon
`disbursed` milik karyawan itu). Data demo membuat kasbon `disbursed` atas karyawan sungguhan tanpa jurnal.

### Usulan perbaikan

1. Batasi tiap tindakan ke perannya:
   `hr-review` → `HR_ROLES`; `disburse`, `repay`, `apply-payroll-deductions` → `FINANCE_ROLES`
   (`core/roles.py`), dengan `dependencies=only(...)` seperti pola yang sudah dipakai di tempat lain.
2. Pemohon hanya boleh mengajukan untuk dirinya sendiri; isian `employee_id` hanya dihormati bila pemanggil HR/admin.
3. Tolak `hr-review` dan `disburse` bila `user.id` sama dengan pemohon atau penyetuju sebelumnya.
4. Hapus `/seed`, atau pagari dengan `ENV != production` **dan** `superadmin`.

---

## FIN-01 — Rekap Keuangan: 7 dari 7 angka salah

**Tingkat:** Tinggi · **Menu:** Rekap Keuangan · **Berkas:** `backend/server.py:1435–1565`

### Gejala

Kas masuk, kas keluar, piutang beredar, hutang beredar, dan biaya vendor selalu **Rp 0**; draf invoice
ikut dihitung sebagai penjualan; margin kotor tampil **100%**. Tabel "garment summary" selalu kosong.

### Bukti kode — pembaca vs penulis

| Angka di layar | Rekap membaca | Yang sebenarnya ditulis |
|---|---|---|
| Kas masuk/keluar | `rahaza_ar_payments.payment_date`, `.amount` (`server.py:1478–1488`) | `_record_payment_doc` menulis **`date`**, bukan `payment_date` (`rahaza_finance.py:123–127`) |
| Biaya vendor | `rahaza_ap_invoices.total_amount` (`server.py:1469–1472`) | `create_ap` & AP dari GR hanya menulis **`total`** (`rahaza_finance.py:695–704`, `rahaza_ap_from_gr.py:355–357`) |
| Piutang/hutang beredar | status `unpaid/partial/overdue`, kolom `outstanding_amount` (`server.py:1492–1505`) | status `issued/partial_paid/overdue`; kolom `balance`/`amount_due`. Tidak ada penulis `outstanding_amount` di kedua koleksi |
| Penjualan | `status != cancelled` (`server.py:1461`) | ikut menghitung `draft`, `void`, `written_off` |

```python
# server.py:1478–1481 — kas masuk
ci_pipeline = [
    {"$match": {"payment_date": date_filter}},          # ← field ini tidak pernah ditulis
    {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
]
```

```python
# rahaza_finance.py:123–127 — penulis pembayaran
await db[coll].insert_one({
    "id": pay_id, "invoice_id": inv.get("id"), "invoice_number": inv.get("invoice_number"),
    "amount": round(amount), "date": payment_date, ...   # ← "date"
})
```

### Pembuktian (T1)

Skenario: AR 10 jt dikirim dan dibayar 4 jt; AR draf 5 jt; AP 6 jt dikirim dan dibayar 1 jt.

```
field pembayaran yang ditulis: [... 'date', ...]            ← bukan payment_date
field AP yang ditulis        : ['total', 'balance']          ← tidak ada total_amount
GAGAL Penjualan (AR terbit, draft tidak dihitung): dapat=15000000 harap=10000000
GAGAL Biaya vendor (AP 6 jt):                       dapat=0        harap=6000000
GAGAL Kas masuk (bayar AR 4 jt):                   dapat=0        harap=4000000
GAGAL Kas keluar (bayar AP 1 jt):                  dapat=0        harap=1000000
GAGAL Piutang beredar (10 − 4 = 6 jt):             dapat=0        harap=6000000
GAGAL Hutang beredar (6 − 1 = 5 jt):               dapat=0        harap=5000000
GAGAL Margin kotor % (10−6)/10:                     dapat=100.0    harap=40.0
hasil: 0 lulus dari 7
```

Selain itu (dibaca dari kode): layar mengirim tanpa tanggal saat filter "Semua", lalu server memakai
30 hari terakhir (`server.py:1451–1452`); dan `getDateRange` di `FinancialRecapModule.jsx:20–24` memakai
`toISOString()` pada tengah malam waktu lokal, sehingga di WIB setiap rentang bergeser mundur sehari.

### Usulan perbaikan

Jangan menghitung ulang dari dokumen. Rekap sebaiknya membaca **buku besar** yang sudah benar:
penjualan = kredit akun pendapatan, biaya = debit HPP/beban, kas = mutasi akun kas/bank, piutang/hutang
= saldo akun kontrol `1-1301`/`2-1100` — fungsi-fungsi di `core/fin_statements.py` sudah menyediakannya.
Bila tetap dari dokumen: gunakan `date`, `total`/`balance`, status kanonik dari `rahaza_ar_canonical.OPEN_STATUSES`,
dan kecualikan `draft/void/written_off`.

---

## FIN-02 — Peran resmi portal ditolak di pintunya sendiri

**Tingkat:** Tinggi · **Menu:** hampir semua · **Jenis:** daftar peran tidak seragam antara portal, server, dan layar

### Gejala

Portal Keuangan dibuka untuk tiga peran (`portalAccess.js:29`):
`accounting`, `staff_keuangan`, `manager_keuangan`. Tetapi:

- **Server:** penjaga inti di `rahaza_finance.py`, `rahaza_journals.py`, `rahaza_periods.py`,
  `rahaza_coa.py`, `rahaza_posting_profiles.py`, `rahaza_hpp.py` hanya mengenal `accounting`
  (plus peran generik `finance` dan `manager` yang **bukan** peran keuangan).
- **Layar:** Kas Kecil, Transfer Bank, Klaim (tombol Bayar), dan Perjalanan Dinas (Post GL) menampilkan
  tombolnya hanya untuk peran bernama `finance` — peran yang tidak pernah di-seed (`auth.py` hanya
  membuat `accounting` dan `staff_keuangan`; `core/roles.py:3–4` menegaskan hal yang sama).

### Bukti kode

```python
# rahaza_finance.py:132–140 (pola yang sama di rahaza_journals.py:34–42, rahaza_coa.py:35)
async def _require_fin(request: Request):
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role in ("superadmin", "admin", "owner", "accounting", "finance", "manager"):
        return user
    perms = user.get("_permissions") or []
    if "*" in perms or "finance.manage" in perms:
        return user
    raise HTTPException(403, "Forbidden: butuh permission finance.")
```

```jsx
// PettyCashModule.jsx:37 · BankTransferModule.jsx:45
const FINANCE_ROLES = ['superadmin', 'admin', 'owner', 'finance'];
// EmployeeExpenseApprovalModule.jsx:222 · EmployeeTravelSettlementModule.jsx:318, 558
const isFinance = ['superadmin','admin','owner','finance'].includes(role.toLowerCase());
```

```python
# employee_travel_settlements.py:602 — Post GL penyelesaian dinas
if role not in ('superadmin', 'admin', 'owner', 'hr', 'finance'):
    raise HTTPException(403, 'Hanya Finance yang dapat melakukan posting GL')
```

Pemindaian daftar peran di ±40 berkas rute keuangan menemukan **25** daftar yang tidak memuat salah satu
dari tiga peran portal (mis. `rahaza_petty_cash.py:35` dan `rahaza_bank_transfers.py:26` tanpa
`manager_keuangan`; `rahaza_budget.py:155` tanpa `staff_keuangan`).

### Pembuktian (T8) — panggilan nyata ke server

```
Tindakan                                  accounting     staff_keuangan   manager_keuangan
Jurnal Umum: simpan & posting            boleh (200)        DITOLAK 403        DITOLAK 403
Terima pembayaran piutang (AR)           boleh (200)        DITOLAK 403        DITOLAK 403
Bayar hutang (AP)                        boleh (200)        DITOLAK 403        DITOLAK 403
Tambah rekening kas/bank                 boleh (400*)       DITOLAK 403        DITOLAK 403
Pengeluaran umum                         boleh (200)        DITOLAK 403        DITOLAK 403
Kas Kecil: buat dana                     boleh (200)        boleh (200)        DITOLAK 403
Transfer Bank                            boleh (200)        boleh (200)        DITOLAK 403
Perjalanan Dinas: Post GL                DITOLAK 403        DITOLAK 403        DITOLAK 403
Klaim karyawan: Bayar & Post GL          boleh (200)        boleh (400*)       DITOLAK 403
Tutup periode                            boleh (200)        DITOLAK 403        DITOLAK 403
jumlah pintu yang MENOLAK peran portalnya sendiri: accounting 1 · staff_keuangan 7 · manager_keuangan 10 (dari 10)
```

\* 400 = lolos pemeriksaan peran, ditolak oleh validasi data uji — bukan karena peran.

Ironisnya, peran generik `manager` (dari departemen mana pun) **lolos** `_require_fin`, sementara
`manager_keuangan` ditolak.

### Usulan perbaikan

1. Satu sumber daftar peran: ganti semua daftar lokal dengan `core.roles.FINANCE_ROLES` (sudah memuat
   ketiga peran), dan keluarkan `manager` generik dari penjaga keuangan.
2. Di frontend, satu konstanta bersama (mis. `lib/roles.js`) yang dicerminkan dari `core/roles.py`,
   dipakai oleh `PettyCashModule`, `BankTransferModule`, `EmployeeExpenseApprovalModule`, `EmployeeTravelSettlementModule`.
3. Uji gerbang otomatis: untuk setiap endpoint tulis keuangan, pastikan ketiga peran portal tidak mendapat 403
   dan peran non-keuangan mendapat 403 (T8 bisa dijadikan dasar).

Sementara: admin dapat memberi izin `finance.manage` pada peran `staff_keuangan`/`manager_keuangan`
lewat layar Peran & Hak Akses — penjaga server menerimanya. Itu tidak memperbaiki tombol yang disembunyikan.

---

## FIN-04 — Pintu samping yang menulis jurnal terbuka bagi semua peran internal

**Tingkat:** Tinggi · **Jenis:** otorisasi hilang pada endpoint yang menulis buku besar

### Gejala

Pintu utama Jurnal Umum dikunci ke portal keuangan (`rahaza_journals.py:22–23`). Tetapi pintu lain yang
**juga** menulis jurnal hanya memeriksa login. Semua router ini didaftarkan dengan
`_DENY_EXTERNAL_AND_MKT` atau `_DENY_EXTERNAL` (`server.py:644–647`), yang hanya menolak
`vendor, cmt_vendor, buyer, klien_maklon` (+ `pic_toko, marketing_kol, cs_staff`). Operator produksi,
HR, gudang, R&D, sales — semuanya lolos.

| Berkas | Endpoint tulis hanya `require_auth` | Akibat |
|---|---|---|
| `rahaza_accruals.py` | create `:77`, update `:159`, **post `:214`**, **reverse `:267`**, create-recurring `:318` | Jurnal bebas dengan akun dari isian (`:104–105`) |
| `rahaza_fixed_assets.py` | create `:146`, update `:310`, **post-depr `:339`**, **dispose `:391`**, **run-batch `:442`** | Jurnal penyusutan & pelepasan |
| `rahaza_budget.py` | create `:67`, update `:114`, **lock `:173`**, **reopen `:190`**, items `:231, :267`, import `:401` | Anggaran terkunci bisa dibuka siapa pun |
| `rahaza_petty_cash.py` | create_txn `:304` | Transaksi kas kecil (lihat FIN-05) |
| `rahaza_hpp.py` | snapshot maklon `:230`, snapshot PO `:262` | Membekukan HPP |
| `rahaza_fin_reports.py` | semua baca (`:35, :107, :206, :306, :481` …) | Neraca saldo, buku besar, L/R, neraca terbaca siapa pun |

Yang sudah dikunci baru **DELETE** (`rahaza_budget.py:136, :295`, `rahaza_accruals.py:192` — penanda `# T-01 2.3`).

### Pembuktian (T2, T3, T4)

```
buat akrual (operator)       200
posting akrual (operator)    200     ← jurnal posted di buku besar
GAGAL operator BERHASIL memposting jurnal akrual (seharusnya ditolak): dapat=True harap=False
buat aset oleh OPERATOR -> 200
pengeluaran kas kecil 300rb oleh OPERATOR -> 200
neraca saldo dibaca operator -> 200
```

### Usulan perbaikan

Pasang `dependencies=only(*FINANCE_ROLES)` pada setiap endpoint tulis di tabel, dan
`dependencies=[Depends(require_portal_dep("finance"))]` pada router `rahaza_fin_reports`,
`rahaza_accruals`, `rahaza_fixed_assets`, `rahaza_budget` — pola yang sama dengan `rahaza_journals.py:22–23`.
Endpoint `ai-narrative?refresh=true` dan `/finance/ai-cashflow` (pemanggilan AI berbayar) juga perlu pagar portal.

---

## FIN-05 — Kas Kecil

**Tingkat:** Tinggi · **Berkas:** `backend/routes/rahaza_petty_cash.py`

### (a) Kode akun kas kecil salah — semua jurnal gagal, saldo dana tetap berubah

```python
# rahaza_petty_cash.py:108
petty_cash_code = '1-110'
```

Bagan akun standar memakai `1-1101` "Kas Kecil"; Profil Posting bawaan pun berkata
`credit_petty_cash: '1-1101'`. Kode 3-digit `1-110` adalah akun lama (`data/coa_unified.py:123`:
`"1-110": "1-1101"`) yang dinonaktifkan lalu **dihapus** saat server menyala bila belum pernah dipakai
(`rahaza_coa.py:655–684`, dipanggil dari `server.py:288`). Pada instalasi baru ia tidak pernah ada.

Saldo dana diubah **sebelum** dan **terlepas dari** hasil jurnal:

```python
# rahaza_petty_cash.py:335–342 — create_txn
delta = -body.amount if body.txn_type in ('expense', 'advance') else body.amount
await db.rahaza_petty_cash_funds.update_one({'id': body.fund_id},
    {'$inc': {'current_balance': delta}, ...})
posting_result = await _post_petty_cash_txn(db, txn_doc, user)   # ← boleh gagal, saldo sudah berubah
```

### (b) Menutup dana menjurnal terbalik

Penutupan mencatat sisa saldo sebagai transaksi `return` (`:280–291`), dan cabang `return` menjurnal
Dr Kas Kecil / Cr Beban (`:134–142`). `bank_account_code` yang disimpan di dokumen tidak pernah dipakai.
Lalu `current_balance` di-`$set` 0 (`:295`).

### (c) "Pengembalian" tanpa batas dan tanpa gerbang peran

`create_txn` (`:303–304`) hanya `require_auth`; `return` tidak dibandingkan dengan uang muka yang pernah keluar.
Pemeriksaan saldo untuk pengeluaran adalah baca-lalu-tulis (`:314` lalu `$inc` di `:337`), tanpa penjaga atomik.

### Pembuktian (T3)

```
GAGAL 1-110 (kode kas kecil yang dipakai kode) ada di bagan akun: dapat=False
pengeluaran 300rb oleh OPERATOR -> 200 | posting: {'ok': False, 'error': "Baris #2: akun '1-110' tidak ditemukan/aktif."}
GAGAL saldo dana TIDAK berubah bila jurnalnya gagal (dana = GL): dapat=700000.0 harap=1000000
"return" 50 jt tanpa uang muka -> 200 | saldo dana sekarang 50700000.0
tutup dana (sisa 700rb) -> jurnal:
     1-110    Kas Kecil (legacy)         Dr    700,000  Cr          0
     6-2400   ATK & Supplies             Dr          0  Cr    700,000
GAGAL penutupan mendebit BANK (uang kembali ke bank)
GAGAL penutupan mengkredit KAS KECIL
```

(Untuk menguji arah jurnal penutupan, akun `1-110` sengaja ditambahkan dulu ke bagan akun uji.)

### Usulan perbaikan

1. Ambil akun dari Profil Posting (`get_mapping(db, 'petty_cash_replenish')['debit_petty_cash']`), bukan konstanta.
2. Penutupan: buat jenis transaksi sendiri (`close_return`) dengan jurnal Dr `bank_account_code` / Cr Kas Kecil.
3. Ubah saldo dana dengan filter atomik (`{'id': fid, 'status': 'active', 'current_balance': {'$gte': amount}}`)
   dan **hanya setelah** jurnal berhasil — atau batalkan perubahan saldo bila jurnal gagal.
4. `create_txn`: `dependencies=only(*FINANCE_ROLES)`; `return` dibatasi sisa uang muka terbuka.

---

## FIN-06 — Aset Tetap

**Tingkat:** Tinggi · **Berkas:** `backend/routes/rahaza_fixed_assets.py`, `backend/routes/rahaza_posting.py`

### (a) Tombol "Posting" per baris menandai posted tanpa pernah membuat jurnal

```python
# rahaza_fixed_assets.py:365–386
if acc_exp and acc_accum:
    try:
        from routes.rahaza_posting import post_journal    # ← fungsi ini tidak ada di rahaza_posting
        ...
        je_id_resp = await post_journal(db, je_body, user)
    except Exception as e:
        logger.warning(f"[fixed_assets] Gagal buat jurnal depresiasi: {e}")
await db.rahaza_depr_schedules.update_one({...}, {"$set": {
    "posted": True, "posted_at": _now(), "journal_entry_id": je_id }})   # ← je_id = None
```

`post_journal` hanya ada sebagai handler rute di `rahaza_journals.py:258` dengan tanda tangan berbeda.
Setelah itu batch menganggap periode tersebut sudah diposting (`:524–544`).

### (b) Saldo menurun ganda dibagi 12 dua kali

```python
# rahaza_fixed_assets.py:77–83
rate = 2 / useful_life if useful_life > 0 else 0       # useful_life dalam BULAN → sudah tarif bulanan
...
depr_amt = round(book_value * rate / 12, 2)            # ← dibagi 12 lagi
```

### (c) Pelepasan mengabaikan akumulasi penyusutan

```python
# rahaza_posting.py:1835–1838 — post_asset_disposal
original_cost = float(asset.get("purchase_cost") or 0)
accumulated_depr = float(asset.get("accumulated_depr_at_disposal") or 0)   # ← tidak ada penulisnya
nbv = original_cost - accumulated_depr
```

`dispose_asset` menulis `nbv_at_disposal` dan `disposal_gain_loss` (`rahaza_fixed_assets.py:408–416`),
bukan `accumulated_depr_at_disposal`. Akun aset yang dikredit berasal dari profil `asset_disposal`
(`1-2500` Inventaris Kantor), bukan `account_id_asset` milik aset.

### Pembuktian (T4)

```
tombol "Posting" periode 2026-03 -> 200 {'ok': True, 'depr_amount': 1000000.0, 'journal_entry_id': None}
OK    jadwal ditandai posted
GAGAL ...dan ADA jurnalnya
batch periode 2026-03 -> ['already_posted']
GAGAL batch memperbaiki periode yang "posted" tanpa jurnal

saldo menurun ganda, 60 bln, harga 60 jt: tahun-1 = 1,969,726; nilai buku akhir bulan ke-60 = 50,777,126

akumulasi depresiasi di GL untuk Mesin Obras sebelum dilepas: -6,000,000   (batch benar: 6 × 1 jt)
dispose -> layar: NBV 54000000.0 laba/rugi -4000000.0
     1-1201   Bank BCA                       Dr   50,000,000
     6-4200   Kerugian Penjualan Aset Tetap  Dr   10,000,000
     1-2500   Inventaris Kantor                                Cr   60,000,000
GAGAL jurnal mendebit Akumulasi Depresiasi
GAGAL laba/rugi di jurnal = laba/rugi di layar: dapat=-10000000 harap=-4000000
```

### Usulan perbaikan

1. `post-depr`: panggil fungsi yang sama dengan batch (`routes.rahaza_posting.post_depreciation` / jalur
   yang dipakai `run_batch_depreciation`), dan **jangan** menandai posted bila jurnal gagal.
   Skrip koreksi: cari `rahaza_depr_schedules` dengan `posted=True, journal_entry_id=None` dan posting ulang.
2. DDB: `rate = 2 / useful_life` tanpa `/ 12` (atau `rate_tahunan = 2 / (useful_life/12)` lalu `/12`), dan tutup selisih di bulan terakhir ke nilai residu.
3. Disposal: tulis `accumulated_depr_at_disposal` (jumlah jadwal posted s.d. tanggal pelepasan) dan kredit
   akun aset milik aset itu. Hitung NBV per tanggal pelepasan, bukan hari ini (`:405–407`).

---

## FIN-07 — Diskon pembelian diabaikan server

**Tingkat:** Tinggi · **Menu:** Penyesuaian Akhir Periode → Diskon Pembelian (AP)

Layar mengirim `amount` (sudah dikurangi diskon) **dan** `discount_amount`:

```jsx
// PurchaseDiscountModule.jsx:62–68
body: JSON.stringify({
  amount: Number(paymentForm.amount),
  discount_amount: Number(paymentForm.discount_amount) || 0,
  account_id: paymentForm.account_id, ...
```

`record_ap_payment` (`rahaza_finance.py:711–795`) tidak membaca `discount_amount` sama sekali, dan
memanggil `post_ap_payment(...)` tanpa `discount_taken` — padahal fungsinya sudah mendukung
(`rahaza_posting.py:784`: `discount_taken: float = 0`, dengan Cr Purchase Discount).

**Pembuktian (T5):**

```
bayar AP 10 jt dengan diskon 2% (bayar 9,8 jt + diskon 200 rb) -> 200 partial_paid sisa 200000.0
GAGAL invoice AP lunas setelah bayar + diskon: dapat='partial_paid' harap='paid'
GAGAL diskon pembelian tercatat di GL: dapat=False
```

Layar menampilkan "Pembayaran berhasil. Hemat: Rp 200.000", lalu invoice hilang dari daftar tab itu
(daftar hanya status `sent`).

**Usulan:** baca `discount_amount`, validasi `0 ≤ diskon ≤ sisa`, perlakukan `amount + diskon` sebagai
pengurang hutang di filter atomik, dan teruskan `discount_taken`. Perhatikan `post_ap_payment` menganggap
`amount` sebagai bruto (`rahaza_posting.py:836–839`) — samakan konvensinya dengan yang dikirim layar.

---

## FIN-08 — Realisasi anggaran selalu nol

**Tingkat:** Tinggi · **Menu:** Anggaran → Variance

```python
# rahaza_budget.py:334–339
jl_rows = await db.rahaza_journal_lines.find(
    {"account_id": {"$in": acc_ids}, "journal_date": {"$gte": from_m, "$lte": to_m}}, ...)
```

Baris buku besar menulis `account_code`, `date`, `period_code` (`rahaza_posting.py:226–236`,
`rahaza_journals.py:196–205`). Tidak ada penulis `journal_date` di seluruh backend. Jalur cadangan membaca
`rahaza_expenses.account_id` (`:350–357`), yang berisi **id rekening kas**, bukan id akun COA
(`rahaza_finance.py:1110`) — dan bila keduanya diperbaiki, pengeluaran akan terhitung dua kali karena
sudah dijurnal.

**Pembuktian (T5):** anggaran 5 jt di `6-2900`; jurnal beban 3 jt ke `6-2900` (saldo GL 3 jt) →
`GAGAL realisasi anggaran = 3 jt: dapat=0.0`.

**Usulan:** petakan `account_id` item anggaran ke `code`, lalu agregasi `rahaza_journal_lines` dengan
`account_code` dan `period_code`. Hapus jalur cadangan `rahaza_expenses`.

---

## FIN-09 — Laporan turunan membaca status/kolom yang tidak ditulis

**Tingkat:** Tinggi · **Menu:** Aging Piutang, Laporan Eksekutif, Prediksi Kas

Status AR kanonik: `draft, issued, partial_paid, paid, overdue, written_off, cancelled`
(`rahaza_ar_canonical.py:1–9`; `sent` diubah menjadi `issued` di `rahaza_finance.py:299–300, :332`).

| Pembaca | Yang salah |
|---|---|
| `rahaza_ar_360.py:31, :98–118` | `TERMINAL_AR_STATUSES = ('paid','cancelled','void')` → `draft` dan `written_off` dianggap terbuka; untuk `written_off` (`balance=0`), cadangan `total − paid_amount` **menghidupkan kembali** nilai penuh. `OPEN_AR_STATUSES` (`:30`) ada tetapi tidak dipakai. |
| `dewi_executive_report.py:60–67, :84–88` | pendapatan hanya status `paid/partial/sent/overdue` → `issued` dan `partial_paid` tidak terhitung; AR maklon memakai `invoice_date`, bukan `issue_date`. Gaji menjumlah `total_net_pay` (penulis: `total_net`). |
| `dewi_cashflow_ai.py:40–42, :66–68` | piutang & hutang hanya `sent/partial` → hampir selalu 0; membaca `buyer_name` yang tidak ada. |

**Pembuktian (T5):** AR terbit 4 jt; draf 2 jt; dihapus buku 1 jt; terbit 3 jt dibayar 1 jt
→ piutang sebenarnya 6 jt; pendapatan bulan ini 8 jt.

```
GAGAL AR 360: total piutang = 6 jt:                dapat=9000000.0 harap=6000000
GAGAL Laporan Eksekutif: pendapatan bulan ini = 8 jt: dapat=0.0 harap=8000000
GAGAL Prediksi Kas: total piutang dibaca = 6 jt:    dapat=0.0 harap=6000000
```

**Usulan:** satu pembaca kanonik — `rahaza_ar_canonical.canon()` + `OPEN_STATUSES` — dipakai oleh ketiga
modul (sudah dipakai benar oleh `/api/rahaza/ar-aging`). Untuk pendapatan, baca kredit akun pendapatan di
buku besar.

---

## FIN-10 — Impor CSV rekening koran membaca angka 100× lipat

**Tingkat:** Tinggi · **Menu:** Rekonsiliasi Bank → Impor Mutasi

```python
# dewi_bank_reconciliation.py:698–712
def _parse_idr(val: str) -> float:
    ...
    if re.search(r",\d{1,2}$", val):
        val = val.replace(".", "").replace(",", ".")
    else:
        val = val.replace(".", "").replace(",", "")    # ← titik desimal ikut dibuang
    try:
        result = float(val)
    except ValueError:
        result = 0.0                                    # ← gagal parse = 0, diam-diam
```

**Pembuktian (fungsi dijalankan langsung):**

```
'1.500.000'        -> 1500000.0
'1.500.000,00'     -> 1500000.0
'1,500,000.00'     -> 150000000.0      ← 100×
'1500000.50'       -> 150000050.0      ← 100×
'250.000 CR'       -> 0.0              ← hilang
'Rp 1.500.000'     -> 1500000.0
'-75.000'          -> -75000.0
```

Format dengan pemisah ribuan koma, desimal titik, dan akhiran `CR`/`DB` lazim pada ekspor rekening koran
berbahasa Inggris. Penyesuaian yang dibuat dari baris seperti itu menjurnal angka yang sudah membengkak.

**Usulan:** deteksi pemisah desimal dari posisi terakhir `.`/`,` (bila diikuti tepat 2 digit), tangani
akhiran `CR/DB/K/D` sebagai arah, dan **tolak** baris yang gagal dibaca (jangan jadikan 0) dengan laporan
nomor baris ke pengguna. Tambahkan pratinjau sebelum impor.

---

## FIN-11 — Menyetujui edit total invoice AP menghapus jurnalnya

**Tingkat:** Sedang–Tinggi · **Menu:** Persetujuan Perubahan Invoice

Jurnal AP disusun dari `subtotal` dan `tax` melawan `total`:

```python
# rahaza_posting.py:749–761 (+ baris PPN :774–775)
total = float(invoice.get("total") or 0)
subtotal = float(invoice.get("subtotal") or 0)
lines = [
    {"account_code": exp_default, "debit": subtotal, "credit": 0, ...},
    {"account_code": ap_code, "debit": 0, "credit": total, ...},
]
```

Persetujuan yang mengubah `total` saja (`invoice_edit_requests.py:194–202`) langsung menerapkannya,
**mem-void** jurnal lama, lalu mencoba memposting ulang (`:235–250`). Jurnal baru tidak seimbang dan ditolak.

**Pembuktian (T6c):**

```
AP 1 jt + PPN 11% = 1110000 | jurnal: True
setujui edit total → 1.332.000 -> 200 {'message': 'Request approved', ...}
setelah disetujui: {'total': 1332000, 'gl_je_id': '2b6510cf-…',
                    'post_error': 'Jurnal tidak seimbang. Dr 1110000.0 ≠ Cr 1332000.0.'} | jurnal AP aktif: 0
```

Invoice tidak punya jurnal aktif lagi, `gl_je_id` masih menunjuk jurnal yang sudah di-void, dan hasil
`_gl_resync` tidak dikembalikan ke layar. Invoice AR tidak terkena (jurnal AR diturunkan dari total/PPN/diskon
dan selalu seimbang). Kolom `status`/`balance` juga tidak dihitung ulang terhadap pembayaran yang sudah ada.

**Usulan:** jalankan posting baru **lebih dulu** dalam mode uji (validasi saja), baru void jurnal lama bila
berhasil; untuk AP, turunkan jurnal dari `total − tax` seperti AR; kembalikan `_gl_resync` ke layar dan tolak
persetujuan bila gagal. Tambahkan pemeriksaan pemohon ≠ penyetuju.

---

## FIN-12 — Penyelesaian dinas atas uang muka yang belum dibayar

**Tingkat:** Sedang–Tinggi · **Menu:** Penyelesaian Perjalanan Dinas

```python
# employee_travel_settlements.py:166 — status 'approved' diterima
if tr.get('status') not in ('advance_paid', 'on_trip', 'completed', 'approved'): ...
# :187 — uang muka yang BELUM dibayar dianggap diterima
advance = float(tr.get('cash_advance_paid', 0) or tr.get('cash_advance_approved', 0) or 0)
```

**Pembuktian (T6a):** disetujui 2 jt, belum dibayar; karyawan memakai uang sendiri 1,5 jt →

```
{'advance_received': 2000000.0, 'total_actual': 1500000.0, 'difference': 500000.0, 'settlement_type': 'return'}
GAGAL jenis penyelesaian = kurang bayar: dapat='return' harap='additional'
```

Sistem menyimpulkan karyawan mengembalikan 0,5 jt; kenyataannya perusahaan berutang 1,5 jt, dan akun
Uang Muka Karyawan `1-1610` akan dikredit 2 jt yang tidak pernah didebit.

Terkait: menyetujui perjalanan dari inbox mengisi `cash_advance_approved` dengan **seluruh anggaran
perjalanan** (`EmployeeExpenseApprovalModule.jsx:155` → `item.amount` = `total_budget`,
`employee_expense_summary.py:137`), dan `advance-paid` tidak membatasi jumlah bayar ke angka yang disetujui.

**Usulan:** `advance = cash_advance_paid` saja; izinkan penyelesaian dari `approved` hanya bila `advance = 0`
secara eksplisit (jenis `additional` penuh). Di inbox, kirim uang muka yang diminta, bukan anggaran total.

---

## FIN-13 — Transfer bank: "Selesai" tanpa jurnal, void menulis pembalik tunggal

**Tingkat:** Sedang · **Menu:** Transfer Bank

- Transfer disimpan `status: 'completed'` walau posting gagal (`rahaza_bank_transfers.py:147`).
- Void (`:196–224`) hanya memeriksa `status == 'voided'`, tidak memeriksa `gl_posted`, lalu memposting
  Dr asal / Cr tujuan bertanggal hari ini.
- Daftar rekening di layar (`BankTransferModule.jsx:50–54`) memuat `1-1203`–`1-1205` (BRI/BNI/BSI) yang
  tidak ada di bagan akun standar.

**Pembuktian (T6d):** transfer BCA→Mandiri 5 jt bertanggal periode tertutup →

```
dokumen: {'status': 'completed', 'gl_posted': False, 'gl_error': 'Periode 2026-08 sudah closed. Posting ditolak.'}
void -> 200 {'ok': True, ...} | GL (1-1201, 1-1202) sebelum (0, 0) sesudah (5000000.0, -5000000.0)
```

**Usulan:** status `pending_posting` bila jurnal gagal; void tanpa jurnal bila `gl_posted` salah; daftar
rekening diambil dari `rahaza_cash_accounts` aktif, bukan konstanta.

---

## FIN-14 — Akrual berulang menggandakan diri

**Tingkat:** Sedang · **Berkas:** `rahaza_accruals.py:343–366`

```python
query = {"is_recurring": True, "status": {"$ne": "draft"}}   # ← anak yang sudah diposting ikut jadi "templat"
...
existing = await db.rahaza_accruals.find_one({
    "period": target_period, ..., "recurring_template_id": template.get("id")})   # ← dicek per templat
```

Anak akrual dibuat dengan `is_recurring: True` (`:382`), jadi setelah diposting ia menjadi templat baru.

**Pembuktian (T6b):** templat Juli → anak Agustus (posted) → buat untuk September: **2 draf**.

**Usulan:** anak diberi `is_recurring: False` + `recurring_template_id`; templat hanya dokumen tanpa
`recurring_template_id`; cek duplikat per `(period, recurring_root_id)`.

---

## FIN-15 — Nilai tak hingga lolos validasi jurnal

**Tingkat:** Sedang · **Berkas:** `rahaza_journals.py:81–100`, `rahaza_posting.py:170–193`

Parser JSON Python menerima `1e999` (dan `Infinity`) sebagai `float('inf')`. Tidak ada `math.isfinite`;
`round(inf, 2) == round(inf, 2)` bernilai benar, sehingga jurnal dianggap seimbang.

**Pembuktian (T7):**

```
POST jurnal 1e999 -> 500
jurnal tersimpan: [{'je_number': 'JE-20260923-0001', 'status': 'posted', 'total_debit': inf}]
baris buku besar: [{'account_code': '6-2900', 'debit': inf}, {'account_code': '1-1201', 'credit': inf}]
neraca saldo -> 500 · laba rugi -> 500 · neraca -> 500
```

Pengguna melihat galat 500 (dan mungkin mencoba lagi), padahal jurnalnya sudah tersimpan. Lewat akrual
(FIN-04), operator produksi bisa melakukan hal yang sama; jurnal akrual bertanggal akhir bulan, dan sejak
tanggal itu ketiga laporan gagal dimuat (diuji: `trial-balance?to=2026-09-30 -> 500`).

**Usulan:** tolak angka yang tidak `math.isfinite` di `_validate_lines` dan `_create_posted_je`, serta
batasi nilai maksimum wajar (mis. 10¹⁵).

---

## FIN-16 — Potongan kasbon bisa dua kali pada periode yang sama

**Tingkat:** Sedang · **Berkas:** `dewi_kasbon.py:584–587`

```python
if run_id:
    already = any(r.get("run_id") == run_id for r in reps)
else:
    already = any(r.get("period") == period and r.get("method") == "payroll_deduction" for r in reps)
```

Pencatatan dari Keuangan ("Catat bayar → Potong Gaji", bawaan layar di `FinanceKasbonModule.jsx:123`) atau
endpoint batch tidak membawa `run_id`; finalisasi payroll membawa `run_id`. Keduanya tidak saling mengenali.
Payroll juga menyusun potongan tanpa melihat repayment yang sudah ada (`rahaza_payroll_shared.py:503–507`).
Untuk pinjaman bercicilan, gaji bulan itu terpotong dua kali. Kunci jurnalnya berbeda (`:626` vs `:439`),
jadi keduanya terjurnal. Pembaruan saldo juga baca-lalu-`$set` (`:401–404`).

**Usulan:** dedupe pada `(kasbon_id, period, method='payroll_deduction')` di semua jalur, dan saat
payroll menyusun potongan, kurangi yang sudah tercatat untuk periode itu.

---

## FIN-17 — Posting draf jurnal tidak atomik

**Tingkat:** Sedang · **Berkas:** `rahaza_journals.py:256–275`

```python
if je["status"] != "draft": raise ...
await db.rahaza_journal_entries.update_one({"id": je_id}, {"$set": {"status": "posted", ...}})  # ← tanpa filter status
je["status"] = "posted"
await _mirror_lines(db, je)
```

Dua permintaan hampir bersamaan sama-sama lolos pemeriksaan, sama-sama menyalin baris ke buku besar —
neraca saldo menghitung jurnal itu dua kali. Pola sama di `marketing_settlements.py:1006–1011` dan
`marketing_withdrawals.py:341–346`.

**Usulan:** `find_one_and_update({"id": je_id, "status": "draft"}, ...)` dan salin baris hanya bila ada
dokumen yang berubah.

---

## FIN-18 — Rekonsiliasi bank: penyesuaian ganda, impor tanpa cek duplikat

**Tingkat:** Sedang · **Berkas:** `dewi_bank_reconciliation.py`

- `adjust` (`:543`) hanya menolak baris yang sedang `is_matched`. `Lepas` (`_release_txn`, `:394–403`)
  menghapus tautan tetapi tidak membatalkan jurnal penyesuaian. Penyesuaian kedua memakai id baru, sehingga
  kunci idempotensi `bank_adj:{id}` tidak bertabrakan: jurnal biaya bank dan mutasinya (`:575`) tercatat dua kali.
- Impor CSV (`:808–809`), bulk (`:369–370`), dan manual (`:351`) tidak memeriksa baris kembar
  (tanggal + jumlah + referensi). Mengunggah berkas yang sama dua kali menggandakan mutasi.
- Pencocokan manual memeriksa `is_matched` lewat pembacaan terpisah (`:438`) tanpa indeks unik pada
  `bank_recon_matches`.

**Usulan:** satu penyesuaian per `txn_id` (cek sebelum membuat; `Lepas` atas baris penyesuaian mem-void
jurnalnya), sidik jari baris impor + indeks unik per sesi, dan indeks unik `(session_id, target_key)`.

---

## FIN-19 — Rekonsiliasi pencairan marketplace melewati lingkup toko

**Tingkat:** Sedang · **Berkas:** `marketing_settlements.py:786–813`

```python
if settlement_id:
    focus = await db[COLL].find_one({"$or": [{"id": settlement_id}, {"settlement_id": settlement_id}]}, ...)
    account_id = focus.get("account_id") or account_id      # ← toko diambil dari dokumen, tanpa cek visibilitas
...
vis = await _scope.visible_account_ids(db, user)
if vis is not None: sq["account_id"] = {"$in": vis}
if account_id:      sq["account_id"] = account_id          # ← menimpa pembatas lingkup
if focus:           sq = {"id": focus["id"]}
```

Middleware lingkup toko hanya memeriksa `account_id`/`account`/`toko_id` pada permintaan
(`middleware/marketing_scope_guard.py:89`), sedangkan di mode `settlement_id` toko tidak disebut di
permintaan. Pengguna `pic_toko` dapat membaca pencairan dan omzet toko lain. `oq["account_id"] = account_id`
(pesanan) punya pola yang sama.

**Usulan:** setelah `focus` ditemukan, tolak bila `vis is not None and focus.account_id not in vis`
(pola `get_settlement` yang sudah benar), dan jangan biarkan `account_id` menimpa `$in vis`.

---

## FIN-20 — Catatan kecil

| # | Catatan | Baris |
|---|---|---|
| a | Akun beban klaim ditentukan klaimer sendiri (`gl_debit_code` dari isian), bukan dari Pemetaan GL | `employee_expense_claims.py:181, :501` |
| b | "Post GL Selected" penyelesaian dinas selalu gagal: mengimpor `_generate_je_number, _create_journal_entry` yang tidak ada | `employee_travel_settlements.py:878` |
| c | Hapus buku menerima invoice `draft` (piutang belum pernah didebit) | `rahaza_finance.py:514–516` |
| d | Pembatalan tutup tahun mem-void jurnal penutupan tanpa cek periode terkunci | `rahaza_year_end.py:105–114` |
| e | `post_accrual` membungkus `HTTPException(400)` di dalam `try` → pengguna menerima 500 dengan detail "400: …" | `rahaza_accruals.py:228–236` |
| f | Pengeluaran umum: tombol Simpan tanpa kunci (klik ganda = dua jurnal); galat posting tidak ditampilkan; "Tidak link" tetap mengkredit `1-1201` | `RahazaExpensesModule.jsx:120`, `rahaza_posting.py:863–865` |

---

## FIN-21 — Seed akuntansi & pemetaan GL bawaan

**Tingkat:** Rendah

- **Seed semua gagal di bagian kategori expense.** `rahaza_admin.py:142–149` memanggil fungsi rute
  `seed_default_categories()` secara langsung; parameter `user = Depends(require_auth)` tidak terisi sehingga
  objek `Depends` dipakai sebagai user. Uji: `"eem_categories": {"ok": false, "error": "'Depends' object has no attribute 'get'"}`.
  Solusi: pisahkan logika seed ke fungsi biasa yang dipanggil oleh keduanya.
- **Pemetaan GL bawaan menunjuk akun yang salah.** `employee_expense_gl_mapping.py:253`
  `'Transportasi': ('6-3300', ...)`, padahal `6-3300` di bagan akun adalah "BPJS Ketenagakerjaan (Employer)"
  (`rahaza_coa.py:159`); `6-3600` ke atas tidak ada. Kas kecil memakai peta ini (`rahaza_petty_cash.py:117–121`).

---

## Hasil negatif — yang diperiksa dan terbukti benar

Dicantumkan supaya pemeriksaan berikutnya tidak mengulang pekerjaan yang sama.

**Uji kontrol T9 (5/5 lulus):**

```
AR 1.110.000: bayar 500rb -> 200 partial_paid | bayar lagi 900rb (lebih dari sisa) -> 400
OK    pembayaran melebihi sisa ditolak
OK    jurnal tak seimbang ditolak
OK    akun header (non-postable) ditolak
OK    neraca saldo menyatakan dirinya seimbang  (period_debit 1.610.000 = period_credit 1.610.000)
OK    garis lurus: 900rb/bln dan berhenti di nilai residu 6 jt
```

**Dari pembacaan kode (diverifikasi):**

- Mesin posting `_create_posted_je` (`rahaza_posting.py:156–199`): minimal dua baris bernilai, akun aktif &
  daun, tidak negatif, satu baris satu sisi, debit = kredit, periode terbuka/masa depan ≤ 31 hari.
- Idempotensi jurnal otomatis ditegakkan database: indeks unik parsial `uniq_active_source_ref`
  (`migrations/ensure_indexes.py:265–271`) + penanganan `DuplicateKeyError`.
- Pembayaran AR/AP atomik dengan penjaga kelebihan bayar di filter (`rahaza_finance.py:373–396`, `:726–747`).
- Periode: kunci final hanya admin/superadmin/owner (`rahaza_periods.py:135–140`), tidak ada endpoint buka-kunci;
  buka kembali hanya dari `closed`.
- Saldo awal tidak bisa diterapkan dua kali; batch depresiasi tidak bisa menjurnal dua kali; hapus buku ganda
  menghasilkan satu jurnal; pencairan kasbon tidak bisa dijurnal dua kali.
- Sesi rekonsiliasi terkunci setelah disetujui; persetujuan menuntut 0 baris sisa dan konfirmasi selisih.
- Laporan inti membaca hanya jurnal posted; Laba Rugi mengecualikan jurnal penutupan tahun; Neraca
  memasukkan laba berjalan sehingga seimbang; `/api/rahaza/ar-aging` memakai status kanonik.
- Pencairan marketplace menjurnal dari akun toko dan menolak toko tanpa tautan akun.

---

## Urutan pengerjaan yang disarankan

| # | Tindakan | Usaha | Dampak |
|---|---|---|---|
| 1 | Pagari kasbon per tahap + pemohon ≠ penyetuju + hapus `/seed` (FIN-03) | jam | Menutup satu-satunya jalur uang keluar tanpa kontrol |
| 2 | Satu daftar peran keuangan di server & layar (FIN-02) | jam | Tim keuangan bisa bekerja dengan akunnya sendiri |
| 3 | `only(*FINANCE_ROLES)` pada akrual, aset, anggaran, kas kecil; portal gate pada laporan (FIN-04) | jam | Buku besar hanya ditulis orang keuangan |
| 4 | Kas kecil: akun dari profil, penutupan benar, saldo atomik (FIN-05) | jam | Kas kecil bisa dipakai |
| 5 | `math.isfinite` di validasi jurnal (FIN-15) | menit | Laporan tidak bisa dilumpuhkan |
| 6 | Parser CSV rekon (FIN-10) | jam | Rekonsiliasi dari berkas bank aman |
| 7 | Aset: post-depr pakai jalur batch, DDB, pelepasan + skrip koreksi (FIN-06) | jam–hari | Neraca aset benar |
| 8 | Diskon pembelian (FIN-07) | jam | AP lunas dengan diskon |
| 9 | Rekap, AR 360, Eksekutif, Prediksi Kas, Anggaran membaca GL/pembaca kanonik (FIN-01, 08, 09) | hari | Laporan turunan bisa dipakai mengambil keputusan |
| 10 | Edit invoice AP: validasi dulu, void kemudian (FIN-11) | jam | Jurnal AP tidak hilang |
| 11 | FIN-12 s.d. FIN-21 | jam per butir | Sisa kebersihan |

---

## Metode dan batasnya

**Yang dikerjakan:**

- Pemetaan 24 menu → 5 hub → 47 layar → setiap panggilan API layar → handler backend (2.501 rute
  termasuk rute tingkat aplikasi di `server.py`).
- Pemindaian otorisasi AST pada ±40 berkas rute, **ditambah** gerbang yang dipasang saat `include_router` di
  `server.py` (pelajaran dari koreksi PROD-02 di berkas temuan Produksi/Maklon).
- Penelaahan kode per sub-domain (buku besar & periode; kas & bank; aset & anggaran; karyawan; laporan),
  lalu **setiap klaim diverifikasi ulang** terhadap baris kode sebelum dimasukkan. Klaim yang tidak bisa
  diverifikasi tidak dimasukkan.
- **Uji eksekusi** T1–T9 pada aplikasi utuh. Skrip dan log ada di `UJI_FINANCE.zip`; cara menjalankan
  ulang: `pip install mongomock-motor email-validator apscheduler python-barcode`, lalu
  `python3 t1_recap.py` dst. dari folder hasil ekstrak (sesuaikan jalur repo di `harness.py`).

**Yang tidak dikerjakan:**

- Tidak ada uji terhadap server produksi atau data nyata.
- Basis data tiruan tidak menegakkan indeks unik parsial; karena itu klaim idempotensi jurnal otomatis
  bersandar pada pembacaan indeks, bukan uji.
- FIN-16, 17, 18, 19 dibuktikan dari kode; uji balapan (*race*) tidak dijalankan.
- Paket `emergentintegrations` (AI) diganti tiruan kosong; keluaran AI tidak dinilai, hanya data yang
  diumpankan kepadanya.

---

*Disusun bersamaan dengan `MANUAL_PORTAL_FINANCE.pdf`. Setiap temuan sengaja **tidak** diajarkan sebagai cara
kerja di manual; di sana hanya ada peringatan singkat dan cara aman sementara.*
