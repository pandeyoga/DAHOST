# Temuan Bug — Portal R&D

> Berkas ini adalah lampiran dari **Manual Portal R&D** (`MANUAL_PORTAL_RND.pdf`).
> Semua temuan di sini ditemukan **sambil menelusuri alur untuk menulis manual itu** —
> yaitu saat mencoba mendokumentasikan langkah demi langkah dan menemukan langkah yang
> tidak bisa diselesaikan dari layar.

| | |
|---|---|
| **Repositori** | `github.com/pandeyoga/DAHOST` |
| **Commit** | `077772e` (22 Sep 2026) |
| **Lingkup** | Portal R&D saja — 11 menu, 16 berkas layar, 71 endpoint `/api/dewi/rnd/*` |
| **Tanggal** | 23 September 2026 |
| **Jumlah temuan** | 4 (1 alur buntu · 1 data salah · 1 izin · 1 endpoint mati) |

---

## Ringkasan

| ID | Prioritas | Judul | Dampak bagi pengguna |
|---|---|---|---|
| [RND-01](#rnd-01) | **P1** | Style yang sudah disetujui tidak bisa dipromosikan ke Produksi | Alur desain buntu di langkah terakhir |
| [RND-02](#rnd-02) | **P2** | Kolom stok di layar Produk Final selalu 0 | Angka salah di layar, bisa menyesatkan keputusan |
| [RND-03](#rnd-03) | **P1** | 36 endpoint tulis R&D tanpa pemeriksaan peran | Vendor/buyer yang login bisa mengubah data R&D |
| [RND-04](#rnd-04) | **P3** | Dua perintah HPP tanpa tombol | Nyaris tanpa dampak — fungsinya sudah berjalan otomatis |

---

<a id="rnd-01"></a>
## RND-01 · P1 · Style yang sudah disetujui tidak bisa dipromosikan ke Produksi

### Gejalanya

Alur desain R&D berakhir begini:

```
draft / active  →  pending_owner_review  →  approved_for_launch  →  ???
                   (tombol Ajukan)          (tombol Setujui)        tidak ada tombol
```

Setelah owner menekan **Setujui** dan style berstatus `approved_for_launch`, langkah
berikutnya seharusnya **mempromosikan style menjadi Model DA** di Portal Produksi —
sehingga bisa dibuatkan SPK, job produksi, dan masuk ke jalur manufaktur.

Endpoint untuk itu **ada**:

```python
# backend/routes/dewi_rnd_styles.py:393-394
393 | @router.post('/styles/{style_id}/promote-to-production')
394 | async def promote_style_to_production(style_id: str, body: dict = None, user: dict = Depends(require_auth)):
```

Endpoint itu bekerja dengan benar. Ia memeriksa syarat dengan rapi:

```python
# backend/routes/dewi_rnd_styles.py (badan promote_style_to_production)
    if style.get('rnd_type') == 'maklon_product':
        raise HTTPException(400, 'Style maklon tidak di-promote ke Production Model (produk milik buyer)')
    if style.get('status') != 'approved_for_launch':
        raise HTTPException(
            400,
            f"Style harus berstatus approved_for_launch untuk di-promote "
            f"(saat ini: {style.get('status')})",
        )
    if style.get('promoted_to_model_id'):
        raise HTTPException(400, 'Style sudah pernah di-promote ke Production Model')
```

Ia juga membawa serta isi tech pack (`bom_items`) dan HPP R&D ke Model DA yang baru dibuat.

### Buktinya

**Tidak ada satu pun berkas frontend yang memanggilnya.**

```bash
$ grep -rl 'promote-to-production' frontend/src | wc -l
0
```

Dan tidak ada jalur lain yang menulis `rnd_style_id` ke `rahaza_models`:

```bash
$ grep -rn "rnd_style_id" backend/routes/*.py | grep -E "insert|update_one"
(kosong — selain di dalam promote_style_to_production itu sendiri)
```

Jadi satu-satunya cara style menjadi Model DA adalah lewat endpoint ini, dan endpoint ini
tidak punya tombol.

### Dampak

- Alur R&D **tidak bisa diselesaikan dari layar**. Style menumpuk di status `approved_for_launch`.
- Checklist kelengkapan produk (`GET /api/dewi/rnd/completeness`) memeriksa syarat **Tech Pack**
  lewat field `rahaza_models.rnd_style_id`. Karena field itu hanya diisi saat promosi, semua
  model yang dibuat manual akan **selamanya dinilai "Tech Pack: belum ada"** walaupun tech pack-nya
  sudah disetujui:

```python
# backend/routes/dewi_rnd_styles.py:821
821 |             'techpack': bool(m.get('rnd_style_id')) and m['rnd_style_id'] in tp_styles,
```

### Perbaikan yang disarankan

Tambahkan tombol **"Promosikan ke Produksi"** pada kartu style di
`frontend/src/components/erp/RnDStylesTab.jsx`, muncul hanya bila:

- `style.status === 'approved_for_launch'`, **dan**
- `style.rnd_type !== 'maklon_product'`, **dan**
- `!style.promoted_to_model_id`

Tombol memanggil `POST /api/dewi/rnd/styles/{id}/promote-to-production`, dengan field
opsional `model_code` di dialog (karena endpoint menolak dengan 409 bila kode produk
sudah terpakai di Master Produk).

### Cara kerja sementara

Minta tim teknis menjalankan perintah promosi, atau buat Model DA manual di Portal
Produksi lalu isi field `rnd_style_id`-nya agar checklist kelengkapan terbaca benar.

---

<a id="rnd-02"></a>
## RND-02 · P2 · Kolom stok di layar Produk Final selalu 0

### Gejalanya

Menu **Produk Final** (`rnd-product-viewer`) menampilkan kolom stok untuk setiap produk.
Angkanya selalu **0**, berapa pun stok fisik yang ada di gudang.

### Buktinya

Layar itu membaca koleksi `rahaza_stock`:

```python
# backend/routes/rnd_product_viewer.py:119-123
119 |     stock = await db.rahaza_stock.find({"material_id": {"$in": ids}},
120 |                                        {"_id": 0, "material_id": 1, "qty": 1}).to_list(5000)
121 |     stock_by_mat: dict = {}
122 |     for s in stock:
123 |         stock_by_mat[s["material_id"]] = stock_by_mat.get(s["material_id"], 0.0) + _f(s.get("qty"))
```

lalu memakainya di baris keluaran:

```python
# backend/routes/rnd_product_viewer.py:179
179 |             "stock_qty": int(stock_by_mat.get(m["id"], 0)),
```

Tetapi **koleksi `rahaza_stock` tidak pernah ditulis oleh siapa pun**:

```bash
$ grep -rn "db\.rahaza_stock\." backend --include=*.py | grep -vE "/tests/|test_" | grep -cE "insert|update|replace"
0

$ grep -rn "db\.rahaza_stock\." backend --include=*.py | grep -vE "/tests/|test_"
backend/routes/rnd_product_viewer.py:119:    stock = await db.rahaza_stock.find(...)
```

Satu pembaca, nol penulis. Baris 119 adalah **satu-satunya** rujukan ke koleksi itu di
seluruh backend.

Koleksi stok yang sebenarnya dipakai sistem adalah `rahaza_material_stock`:

```python
# backend/core/catalog_stock.py:39
 39 | STOCK = 'rahaza_material_stock'
```

### Dampak

- Kolom stok di Produk Final menyesatkan: menampilkan 0 untuk produk yang stoknya ada.
- Karena angkanya selalu 0, tidak ada yang "berubah salah" — ia hanya **tidak pernah benar**.
  Ini jenis kesalahan yang sulit disadari karena tidak menimbulkan galat.

### Perbaikan yang disarankan

Ganti pembacaan ke SSOT stok, dan pakai pembaca skema resminya karena
`rahaza_material_stock` punya tiga skema historis (`qty` / `total_qty` / `quantity`):

```python
from core.stock_schema import read_qty

stock = await db.rahaza_material_stock.find(
    {"material_id": {"$in": ids}}, {"_id": 0, "material_id": 1,
                                    "qty": 1, "total_qty": 1, "quantity": 1}).to_list(5000)
for s in stock:
    stock_by_mat[s["material_id"]] = stock_by_mat.get(s["material_id"], 0.0) + read_qty(s)
```

Kalau yang dimaksud adalah "stok yang boleh dijual" (tanpa karantina dan lokasi
diblokir), pakai `core.catalog_stock.sellable_map()` yang sudah menangani aturan itu.

### Cara kerja sementara

Jangan memakai kolom stok di layar Produk Final untuk mengambil keputusan.
Buka Portal Gudang → Stok untuk angka yang benar. Sudah ditulis di manual, halaman Alur 12.

---

<a id="rnd-03"></a>
## RND-03 · P1 · 36 endpoint tulis R&D tanpa pemeriksaan peran

### Gejalanya

Router R&D tidak punya dependensi izin di tingkat router:

```python
# backend/routes/dewi_rnd_shared.py:9
  9 | router = APIRouter(prefix="/api/dewi/rnd", tags=["RnD"])
```

Sehingga izin harus diperiksa satu per satu di tiap endpoint. Sebagian sudah
(`assert_can_act`), sebagian belum. Dari **46 endpoint tulis** di seluruh modul R&D,
**36 hanya memakai `Depends(require_auth)`** — yang artinya cukup "sudah login",
tanpa memeriksa perannya apa.

### Buktinya

Contoh membuat style — tidak ada pemeriksaan peran sama sekali:

```python
# backend/routes/dewi_rnd_styles.py:76-79
 76 | @router.post('/styles')
 77 | async def create_style(body: dict, user: dict = Depends(require_auth)):
 78 |     """Create new style"""
 79 |     db = get_db()
```

Contoh yang paling perlu dijaga — promosi ke produksi, yang **membuat Model DA baru**:

```python
# backend/routes/dewi_rnd_styles.py:393-394
393 | @router.post('/styles/{style_id}/promote-to-production')
394 | async def promote_style_to_production(style_id: str, body: dict = None, user: dict = Depends(require_auth)):
```

Contoh yang bisa menghapus data — seeder demo:

```python
# backend/routes/dewi_rnd_overview.py:105-116
105 | @router.post('/seed')
106 | async def seed_rnd_data(
107 |     reset: bool = Query(True, description='Hapus data demo lama sebelum seed'),
108 |     user: dict = Depends(require_auth),
109 | ):
110 |     """Seed demo RnD data — kaya & idempotent."""
111 |     db = get_db()
...
115 |     if reset:
116 |         await db.dewi_rnd_styles.delete_many({'is_demo': True})
```

### Daftar lengkap 36 endpoint

| Metode | Path | Berkas:baris | Fungsi |
|---|---|---|---|
| POST | `/styles` | `dewi_rnd_styles.py:77` | `create_style` |
| POST | `/styles/{id}/submit-for-review` | `dewi_rnd_styles.py:318` | `submit_style_for_review` |
| POST | `/styles/{id}/promote-to-production` | `dewi_rnd_styles.py:394` | `promote_style_to_production` |
| POST | `/styles/{id}/images` | `dewi_rnd_styles.py:593` | `upload_style_design_image` |
| PUT | `/styles/{id}/size-list` | `dewi_rnd_sizes.py:143` | `put_style_size_list` |
| POST | `/variants` | `dewi_rnd_design.py:106` | `create_variant` |
| PUT | `/variants/{id}` | `dewi_rnd_design.py:174` | `update_variant` |
| POST | `/variants/bulk` | `dewi_rnd_colors.py:258` | `create_variants_bulk` |
| POST | `/variants/{id}/fix-sku` | `dewi_rnd_colors.py:448` | `fix_variant_sku` |
| POST | `/patterns` | `dewi_rnd_design.py:258` | `create_pattern` |
| PUT | `/patterns/{id}` | `dewi_rnd_design.py:288` | `update_pattern` |
| POST | `/patterns/{id}/attach-media` | `dewi_rnd_design.py:330` | `attach_pattern_media` |
| POST | `/tech-packs` | `dewi_rnd_hpp.py:1010` | `create_tech_pack` |
| PUT | `/tech-packs/{id}` | `dewi_rnd_hpp.py:1071` | `update_tech_pack` |
| POST | `/techpack/import/preview` | `dewi_rnd_techpack_import.py:37` | `techpack_import_preview` |
| POST | `/techpack/import/commit` | `dewi_rnd_techpack_import.py:50` | `techpack_import_commit` |
| POST | `/hpp-calculator` | `dewi_rnd_hpp.py:672` | `create_hpp` |
| PUT | `/hpp-calculator/{id}` | `dewi_rnd_hpp.py:735` | `update_hpp` |
| POST | `/hpp-calculator/preview` | `dewi_rnd_hpp.py:791` | `preview_hpp` |
| POST | `/hpp-calculator/cost-lines/from-techpack` | `dewi_rnd_hpp.py:815` | `cost_lines_from_techpack` |
| POST | `/hpp-calculator/compute-from-bom` | `dewi_rnd_hpp.py:949` | `compute_hpp_from_bom` |
| POST | `/hpp-calculator/{id}/propagate` | `dewi_rnd_hpp.py:975` | `propagate_hpp_endpoint` |
| POST | `/materials` | `dewi_rnd_materials.py:252` | `create_material` |
| PUT | `/materials/{id}` | `dewi_rnd_materials.py:304` | `update_material` |
| POST | `/sample-costing` | `dewi_rnd_materials.py:363` | `create_sample_costing` |
| PUT | `/sample-costing/{id}` | `dewi_rnd_materials.py:406` | `update_sample_costing` |
| POST | `/sample-costing/preview` | `dewi_rnd_materials.py:356` | `preview_sample_costing` |
| POST | `/sample-requests` | `dewi_rnd_samples.py:36` | `create_sample_request` |
| PUT | `/sample-requests/{id}` | `dewi_rnd_samples.py:84` | `update_sample_request` |
| POST | `/sample-requests/{id}/submit` | `dewi_rnd_samples.py:100` | `submit_sample_request` |
| POST | `/revisions` | `dewi_rnd_samples.py:200` | `create_revision` |
| PUT | `/revisions/{id}` | `dewi_rnd_samples.py:240` | `update_revision` |
| POST | `/size-mapping/apply` | `dewi_rnd_size_mapping.py:320` | `size_mapping_apply` |
| POST | `/size-mapping/auto` | `dewi_rnd_size_mapping.py:353` | `size_mapping_auto` |
| POST | `/reports/weekly-decisions/send` | `dewi_rnd_design.py:785` | `send_weekly_rnd_report` |
| POST | `/seed` | `dewi_rnd_overview.py:106` | `seed_rnd_data` |

### Yang sudah benar

Endpoint persetujuan **sudah** dijaga dengan baik — pola ini yang perlu ditiru:

```python
# backend/routes/dewi_rnd_styles.py:362
362 |     assert_can_act(user, 'management.manage', 'rnd.approve',
```

```python
# backend/routes/dewi_rnd_samples.py:118
118 |     assert_can_act(user, 'rnd.approve', portal='rnd', legacy_roles=RND_APPROVER_ROLES,
```

Jadi **menyetujui** style dan sample sudah aman. Yang terbuka adalah **membuat dan
menyunting**.

### Dampak

Semua akun yang login lewat `/api/auth/login` — termasuk peran portal internal
`vendor`, `cmt_vendor`, dan `buyer` — dapat membuat style, menyunting BOM varian,
mengubah perhitungan HPP, dan menjalankan seeder. Tidak ada galat, tidak ada jejak
peringatan.

Portal eksternal (klien maklon, live host, kreator) **tidak** termasuk, karena mereka
memakai JWT dengan `aud` terpisah yang ditolak jalur otentikasi internal.

### Perbaikan yang disarankan

Cara paling murah dan menyeluruh: pasang dependensi izin di tingkat router, lalu
longgarkan per endpoint bila ada yang memang perlu lebih terbuka.

```python
# backend/routes/dewi_rnd_shared.py
from routes.shared import require_perm_dep

router = APIRouter(
    prefix="/api/dewi/rnd",
    tags=["RnD"],
    dependencies=[Depends(require_perm_dep('rnd.manage', legacy_roles=RND_ROLES))],
)
```

Urutan pengerjaan yang disarankan: mulai dari empat endpoint yang paling mahal bila
disalahgunakan — `/seed`, `/promote-to-production`, `/techpack/import/commit`, dan
`/size-mapping/apply` — lalu sisanya.

---

<a id="rnd-04"></a>
## RND-04 · P3 · Dua perintah HPP tanpa tombol

### Gejalanya

Dua endpoint kalkulator HPP tidak punya pemanggil di frontend:

```python
# backend/routes/dewi_rnd_hpp.py:948
948 | @router.post('/hpp-calculator/compute-from-bom')

# backend/routes/dewi_rnd_hpp.py:974
974 | @router.post('/hpp-calculator/{calc_id}/propagate')
```

```bash
$ grep -rl 'compute-from-bom' frontend/src | wc -l
0
```

### Kenapa dampaknya kecil

Untuk `/propagate`, fungsinya **sudah berjalan otomatis**. Helper internal
`_propagate_hpp` dipanggil setiap kali HPP disimpan atau disunting:

```python
# backend/routes/dewi_rnd_hpp.py
728 |     propagation = await _propagate_hpp(db, style_id, doc['hpp_total'], doc.get('selling_price_proposal'))   # saat create
774 |     propagation = await _propagate_hpp(db, style_id, doc.get('hpp_total'), doc.get('selling_price_proposal'))  # saat update
981 |     result = await _propagate_hpp(db, doc.get('style_id', ''), doc.get('hpp_total'), ...)                    # endpoint manual
```

Jadi HPP tetap mengalir ke Model DA, Barang Jadi, dan Katalog Marketing tanpa
pengguna perlu menekan apa pun. Endpoint manualnya hanya **berlebih**.

Untuk `/compute-from-bom`, fungsinya tumpang tindih dengan tombol
**"Tarik dari Techpack BOM"** yang memang ada di layar dan memakai endpoint
`/hpp-calculator/cost-lines/from-techpack`.

### Perbaikan yang disarankan

Dua pilihan, keduanya sah:

1. **Pensiunkan** keduanya dengan balasan `410 Gone` — sejalan dengan rencana
   "matikan bertahap endpoint tanpa pemanggil" yang sudah ada di daftar tindak lanjut repo.
2. **Pasang tombolnya** kalau memang diinginkan: `/compute-from-bom` berguna untuk
   menghitung HPP langsung dari BOM Master Produk (bukan dari tech pack), yang
   bisa jadi lebih akurat karena BOM adalah SSOT resep produk.

Tidak ada tindakan mendesak. Yang penting: **jangan dihapus tanpa memeriksa**
`_propagate_hpp` — helper internalnya tetap dipakai tiga tempat dan harus tetap ada.

---

## Catatan metode

Temuan di berkas ini diperoleh dengan cara yang sama seperti audit sebelumnya:

1. **Peta layar** dibangun dari `portalNav.js` (definisi menu) dan `moduleRegistry.js`
   (pemetaan id menu → komponen), lalu tiap berkas layar dibaca untuk mengambil
   tombol, field, dan panggilan API-nya.
2. **Peta endpoint** dibangun dari seluruh dekorator `@router.*` pada berkas
   `dewi_rnd*.py` dan `rnd_product_viewer.py`.
3. **Kontrak layar ↔ endpoint** dibandingkan setelah komentar JavaScript dibuang —
   tanpa langkah itu, komentar yang mendokumentasikan bug lama terbaca sebagai bug baru.
4. **Cakupan izin** dihitung per fungsi lewat AST, dengan resolusi pembantu lokal
   (`assert_can_act`, `require_perm`, `_require_*`) dan pemeriksaan dependensi
   tingkat router.

Setiap temuan sudah dibuka berkasnya dan dibaca manual sebelum ditulis di sini.
Kandidat yang gugur saat diperiksa tidak dimasukkan — antara lain dugaan bahwa
`/propagate` tidak berjalan (ternyata berjalan otomatis, lihat RND-04) dan dugaan
bahwa endpoint persetujuan tidak dijaga (ternyata sudah, lihat RND-03).

---

*Lampiran untuk `MANUAL_PORTAL_RND.pdf` · disusun 23 September 2026 dari commit `077772e`.*
