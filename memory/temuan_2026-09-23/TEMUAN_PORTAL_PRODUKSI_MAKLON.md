# TEMUAN — Portal Produksi & Portal Maklon

**Repo:** `github.com/pandeyoga/DAHOST` · **Commit acuan:** `077772e` · **Tanggal:** 23 September 2026
**Cakupan:** seluruh pintu Portal Produksi (24 menu) dan Portal Maklon (23 menu), termasuk sembilan
pintu yang dipakai bersama kedua portal.
**Berkas pendamping:** `MANUAL_PORTAL_PRODUKSI.pdf`, `MANUAL_PORTAL_MAKLON.pdf`

---

## Ringkasan

| Kode | Judul singkat | Tingkat | Portal | Status pembuktian |
|---|---|---|---|---|
| **MAK-01** | Angka per tahap di *Tracking Produksi* hilang saat dibaca ulang | **Tinggi** | Maklon | Dibuktikan dengan eksekusi kode |
| **PROD-01** | Tombol legacy pada MI melewati persetujuan **dan** memakai jalur potong stok kedua | **Tinggi** | Produksi (+Gudang) | Dibaca dari kode, dua jalur dibandingkan |
| **PROD-02** | Tiga endpoint tulis *Komponen Kurang* tanpa cek peran & tanpa scoping vendor | **Sedang–Tinggi** | Maklon (+Produksi) | Pemindaian AST + pembacaan handler |
| **PROD-03** | Gerbang hanya memisahkan internal vs eksternal, tidak antar-peran internal | **Sedang (desain)** | Keduanya | Pembacaan dependency router |
| **MAK-02** | Satu nama menu, dua layar berbeda antar-portal | **Rendah (UX)** | Keduanya | Pembacaan `portalNav.js` |

**Yang diperiksa dan ternyata bersih** — lihat bagian [Hasil negatif](#hasil-negatif-yang-diperiksa-dan-ternyata-bersih)
di bawah. Dibandingkan Portal R&D, dua portal ini jauh lebih rapi: tidak ada koleksi hantu,
tidak ada endpoint tulis tanpa pemanggil, dan rantai transisi statusnya konsisten.

---

## MAK-01 — Angka per tahap di *Tracking Produksi* tidak pernah kembali

**Tingkat:** Tinggi · **Pintu:** Portal Maklon → `maklon-tracking` ("Tracking Produksi")
**Jenis:** data hilang diam-diam (write-only field) + gerbang alur yang macet sebagai akibatnya

### Gejala yang dialami pengguna

1. Staf mengisi *Cutting Input = 500*, menyimpan, layar menampilkan "berhasil".
2. Halaman dimuat ulang → kolom itu kosong lagi.
3. Saat menekan **Maju ke tahap berikutnya** menuju *packing*, sistem menolak dengan
   "QC Pass belum diinput (0/qty)" — **selalu**, berapa pun yang sudah diketik.
4. Satu-satunya jalan maju adalah **Lanjutkan paksa (override)**, sehingga gerbang mutu
   yang dirancang justru tidak pernah benar-benar dipakai.

### Sebab

`PUT /api/dewi/maklon/orders/{id}/stage-qty` menulis lewat adapter legacy, dan adapter itu
**menerjemahkan nama field** `stage_qty` → `legacy_stage_qty`, sementara **pembacaannya
menurunkan ulang** `stage_qty` dari `items[*]` dan tidak pernah melihat `legacy_stage_qty`.

**Penulis** — `backend/routes/dewi_maklon.py:390–440`

```python
@router.put('/orders/{order_id}/stage-qty', deprecated=True)
async def update_stage_qty(order_id: str, payload: StageQtyIn,
                           user: dict = Depends(require_auth)):
    db = get_db()
    order = await _lmo(db).find_one({'id': order_id})      # ← proyeksi adapter
    ...
    stage_qty = order.get('stage_qty') or {}               # ← isinya HANYA {qty_produced, qty_dispatched}
    if stage == 'cutting':
        if payload.qty_in is not None:
            stage_qty['cutting_input'] = max(0, payload.qty_in)
    ...
    await _lmo(db).update_one(
        {'id': order_id},
        {'$set': {
            'stage_qty': stage_qty,                        # ← akan diterjemahkan
            'progress_percentage': progress,               # ← ikut diterjemahkan
            'updated_at': _now(),
        }}
    )
    return {'message': f'Stage qty {stage} diperbarui', 'stage_qty': stage_qty, ...}
```

Perhatikan: respons mengembalikan `stage_qty` **versi memori**, jadi layar langsung terlihat benar.
Kesalahan baru muncul pada pembacaan berikutnya.

**Kamus penerjemah** — `backend/routes/_maklon_adapter.py:83`

```python
LEGACY_TO_PO_ORDER_FIELDS: Dict[str, str] = {
    "order_code": "po_number",
    "order_date": "po_date",
    ...
    "stage_qty": "legacy_stage_qty",          # ← di sinilah datanya dibelokkan
    "progress_percentage": "legacy_progress_pct",
}
```

**Penerjemah update** — `backend/routes/_maklon_adapter.py:93–113`

```python
def translate_legacy_order_update(update: Any) -> Any:
    out: Dict[str, Any] = {}
    for op, val in update.items():
        if op.startswith("$") and isinstance(val, dict):
            translated = {}
            for k, v in val.items():
                new_k = LEGACY_TO_PO_ORDER_FIELDS.get(k, k)   # stage_qty → legacy_stage_qty
                ...
                translated[new_k] = v
            out[op] = translated
```

**Pembaca** — `backend/routes/_maklon_adapter.py:249–252`

```python
        'stage_qty': {
            'qty_produced':   total_qty_produced,      # diturunkan dari items[*]
            'qty_dispatched': total_qty_dispatched,
        },
```

Tidak ada satu baris pun pada `po_to_legacy_order` yang membaca `legacy_stage_qty`.

**Endpoint yang dipakai layar** — `backend/routes/dewi_maklon.py:492`

```python
    return {
        'order': serialize_doc(order),
        'linked_wos': serialize_doc(wos),
        'stage_qty': order.get('stage_qty') or {},     # = {qty_produced, qty_dispatched}
        ...
    }
```

**Konsumen di layar** — `frontend/src/components/erp/MaklonProductionTracking.jsx`

```jsx
// baris 66–72 — mengisi form dari data yang tidak pernah ada
const sq = order.stage_qty || {};
  qty_in:   sq.cutting_input  || '',
  qty_pass: sq.qc_pass  || '',

// baris 188 — gerbang yang karenanya selalu menahan
if (toStage === 'packing' && !(sq.qc_pass > 0)) return `QC Pass belum diinput (0/${qty})`;

// baris 364–371 — kartu tahap yang selalu kosong
{ key: 'cutting_input',  label: 'Input',  val: sq.cutting_input },
{ key: 'qc_pass',        label: 'Pass',   val: sq.qc_pass, ... },
```

### Pembuktian (dijalankan, bukan dibaca saja)

```python
from routes._maklon_adapter import translate_legacy_order_update, po_to_legacy_order

u = translate_legacy_order_update({'$set': {
        'stage_qty': {'cutting_input': 500, 'cutting_output': 480, 'qc_pass': 470},
        'progress_percentage': 45}})

po = {'id':'po1','po_number':'MK-1','total_qty':500,
      'items':[{'qty_produced':0,'qty_dispatched':0}],'status':'in_production'}
po.update(u['$set'])
back = po_to_legacy_order(po)
```

Keluaran:

```
UPDATE DITERJEMAHKAN -> {'$set': {'legacy_stage_qty': {'cutting_input': 500,
                                  'cutting_output': 480, 'qc_pass': 470},
                                  'legacy_progress_pct': 45}}
BACA KEMBALI stage_qty -> {'qty_produced': 0, 'qty_dispatched': 0}
legacy_stage_qty tersimpan di PO -> {'cutting_input': 500, 'cutting_output': 480, 'qc_pass': 470}
apakah cutting_input kembali? -> False
```

Data **tersimpan** (tidak hilang dari database), tetapi **tidak pernah terbaca** oleh layar mana pun.
Hal yang sama berlaku untuk `progress_percentage` hasil `_calc_progress_from_stage_qty`.

### Catatan tambahan

Karena `stage_qty` yang dibaca setiap kali hanya berisi dua kunci turunan, setiap penyimpanan
berikutnya **menimpa** `legacy_stage_qty` dengan dict baru yang hanya memuat satu tahap yang
baru saja diketik — bahkan seandainya pembacaannya diperbaiki, riwayat tahap sebelumnya
sudah hilang di setiap langkah.

`update_order_status` (`dewi_maklon.py:304`) **tidak** terkena masalah ini: `status` punya
pemetaan nilai tersendiri dan tersimpan dengan benar. Jadi *maju tahap* berfungsi; *angka per
tahap* tidak.

### Usulan perbaikan

Tiga pilihan, berurutan dari yang paling kecil risikonya:

1. **Perbaiki pembacaannya** (paling ringan): pada `po_to_legacy_order`, gabungkan
   `legacy_stage_qty` ke dalam `stage_qty` sehingga kunci turunan dan kunci hasil input
   hidup berdampingan:
   ```python
   'stage_qty': {**(po.get('legacy_stage_qty') or {}),
                 'qty_produced': total_qty_produced,
                 'qty_dispatched': total_qty_dispatched},
   ```
   Satu baris, dan gerbang `qc_pass` langsung berfungsi kembali.

2. **Hapus penerjemahan untuk field ini**: keluarkan `stage_qty` dan `progress_percentage`
   dari `LEGACY_TO_PO_ORDER_FIELDS` bila memang dimaksudkan tersimpan apa adanya.
   Risikonya: perlu dipastikan tidak ada konsumen lain yang bergantung pada nama lama.

3. **Pensiunkan layar ini** (paling bersih, paling besar): kedua endpoint sudah ditandai
   `deprecated=True`. Kalau kebenaran angka produksi memang sudah pindah ke `production_jobs`
   dan dokumen penerimaan/pengiriman, layar *Tracking Produksi* maklon sebaiknya menjadi
   layar **baca saja** yang menampilkan angka kanonik — dan kolom isiannya dihapus, bukan
   dibiarkan menerima ketikan yang tidak berakibat apa-apa.

Apa pun pilihannya, **jangan biarkan keadaan sekarang**: sebuah kolom yang menerima ketikan
tetapi tidak menyimpannya adalah bentuk kesalahan yang paling mahal — pengguna percaya
datanya ada, dan keputusan diambil di atas kepercayaan itu.

---

## PROD-01 — Tombol legacy pada MI melewati persetujuan dan memakai jalur potong stok kedua

**Tingkat:** Tinggi · **Pintu:** Portal Produksi → `wh-material-issue` ("Pengeluaran Material")
**Jenis:** kontrol internal terlewati + duplikasi logika pemotongan stok

### Gejala

Pada satu dokumen MI berstatus `draft`, layar menampilkan **dua tombol bersebelahan**:

| Tombol | Jalur | Persetujuan | Mesin pemotong stok |
|---|---|---|---|
| **Ajukan Approval** | `submit` → `approve` | Ya, oleh peran penyetuju MI | `core.material_issue_engine` → `core/stock_service` |
| **Konfirmasi & Kurangi Stok** | `confirm` | **Tidak ada** | Kode inline di `rahaza_inventory_workflow.py` |

Satu orang dengan peran admin dapat mengeluarkan material dari gudang tanpa persetujuan
siapa pun, hanya dengan memilih tombol yang salah.

### Bukti kode

**Layar masih memunculkannya** — `frontend/src/components/erp/RahazaMaterialIssueModule.jsx:925–929`

```jsx
{detail.status === 'draft' && (
  <>
    <Button variant="ghost" onClick={() => cancelMI(detail)} ...>Cancel</Button>
    <Button onClick={() => confirmMI(detail)} data-testid="mi-confirm-btn">
      <CheckCircle2 className="w-4 h-4 mr-1.5" /> Konfirmasi &amp; Kurangi Stok
    </Button>
```

`frontend/.../RahazaMaterialIssueModule.jsx:145–154`

```jsx
const confirmMI = async (mi) => {
  // DEPRECATED: Legacy direct confirm (kept for old draft MIs)
  // New flow: submit → approve
  ...
  if (!window.confirm(`[LEGACY] Konfirmasi issue MI ${mi.mi_number}? Stok akan dikurangi langsung tanpa approval.`)) return;
  const r = await fetch(`/api/rahaza/material-issues/${mi.id}/confirm`, { method: 'POST', ... });
```

Peringatannya ada, tetapi hanya berupa teks pada dialog `window.confirm` — bukan gerbang.

**Jalur resmi memakai satu mesin** — `backend/routes/rahaza_inventory_issues.py:192–227`

```python
@router.post("/material-issues/{mid}/approve")
async def approve_mi(mid: str, request: Request):
    user = await _require_mi_approver(request)          # ← gerbang peran penyetuju
    ...
    if mi.get("status") != "pending_approval":
        raise HTTPException(400, f"Hanya MI Pending Approval yang bisa di-approve. ...")
    ...
    # ── FASE H-1 (2026-08-15) — INTI PENGELUARAN DIPINDAH KE SATU MESIN ───────
    # ... "Kirim Material CMT" kini menerbitkan MI otomatis, dan kalau ia
    # menyalin logikanya sendiri kita akan punya DUA cara memotong stok yang
    # bisa berbeda diam-diam ...
    from core import material_issue_engine as mie
    out = await mie.issue_material_issue(db, mi, user, loc_overrides=...)
```

Komentar di kode itu menjelaskan persis alasan aturan ini ada — dan jalur `confirm`
adalah cacat yang diperingatkannya.

**Jalur legacy memotong stok sendiri** — `backend/routes/rahaza_inventory_workflow.py:17–75`

```python
@router.post("/material-issues/{mid}/confirm")
async def confirm_mi(mid: str, request: Request):
    """DEPRECATED: Legacy direct confirm (draft → issued without approval)."""
    user = await _require_admin(request)                 # ← gerbang berbeda, lebih longgar
    ...
    for it in raw_items:                                 # ── cek stok: BACA ──
        stock = stock_map.get((it["material_id"], loc))
        avail = float((stock or {}).get("qty") or 0)
        if avail < qty:
            shortages.append({...})
        plan.append({...})
    if shortages:
        raise HTTPException(400, {"message": "Stok tidak cukup untuk issue.", ...})
    for p in plan:                                       # ── potong stok: TULIS ──
        await _add_stock(db, p["material_id"], p["location_id"], -p["qty"])
```

**`_add_stock` tidak punya penjaga atomik** — `backend/routes/rahaza_inventory_shared.py:92–97`

```python
async def _add_stock(db, material_id: str, location_id: str, delta: float):
    await _ensure_stock_row(db, material_id, location_id)
    await db.rahaza_material_stock.update_one(
        {"material_id": material_id, "location_id": location_id},
        {"$inc": {"qty": float(delta)}, "$set": {"updated_at": _now()}},
    )
```

`$inc` polos. Bandingkan dengan `core/stock_service.py:336–345` yang memakai
*compare-and-set* (`$expr`) — dan yang pada pengujian sesi sebelumnya terbukti menahan
dua reservasi bersamaan sehingga hanya satu yang berhasil.

### Akibat yang mungkin

1. **Kontrol internal terlewati.** Pemisahan "yang meminta" dan "yang menyetujui"
   pengeluaran barang adalah kontrol dasar. Di sini ia bisa dilewati dengan satu klik.
2. **Stok bisa minus di bawah beban bersamaan.** Pola *baca-lalu-tulis* pada jalur legacy
   tidak terlindung: dua permintaan yang berjalan bersamaan sama-sama membaca stok cukup,
   lalu keduanya memotong. MongoDB di sistem ini berjalan *standalone*, jadi tidak ada
   transaksi yang bisa menyelamatkan.
3. **Dua definisi "mengeluarkan material".** Jalur resmi memanggil
   `material_issue_engine` (validasi + `stock_service` + movement + jurnal). Jalur legacy
   menyusun ulang langkah-langkahnya sendiri. Setiap perbaikan pada mesin resmi tidak
   otomatis berlaku pada jalur ini.

### Usulan perbaikan

1. **Hapus tombolnya dari layar** (`RahazaMaterialIssueModule.jsx:928`). Ini langkah paling
   cepat dan menutup 99% risikonya, karena endpoint-nya tidak punya pemanggil lain.
2. **Matikan endpoint-nya**, atau arahkan `confirm` untuk memanggil
   `material_issue_engine.issue_material_issue()` yang sama — jangan dua implementasi.
3. Bila MI draft peninggalan lama memang masih perlu diselesaikan, sediakan
   **satu perintah migrasi** yang menaikkannya ke `pending_approval`, bukan tombol permanen
   di layar operasional.
4. Untuk pertahanan berlapis: ganti `_add_stock` dengan pemanggilan `stock_service`
   di seluruh jalur yang memotong stok, sehingga penjaga atomiknya berlaku di mana-mana.

---

## PROD-02 — Tiga endpoint tulis *Komponen Kurang* tanpa cek peran dan tanpa scoping vendor

**Tingkat:** Sedang–Tinggi · **Pintu:** Portal Maklon → `cmt-component-requests`
**Jenis:** otorisasi hilang + kemungkinan akses lintas-vendor (IDOR)

### Bukti kode

**Router tanpa dependency** — `backend/routes/dewi_cmt_component_requests.py:23`

```python
router = APIRouter(prefix="/api/dewi/cmt-component-requests", tags=["Production-CMT-Shortage-Requests"])
```

Bandingkan dengan router sejenis yang memakainya:

```python
# dewi_cmt_packing.py:103
router = APIRouter(prefix="/api/prod", tags=["cmt-packing"], dependencies=[Depends(deny_external_dep)])
# dewi_maklon.py:33
router = APIRouter(prefix='/api/dewi/maklon', tags=['Dewi-Maklon'], dependencies=[Depends(deny_external_dep)])
```

**Empat endpoint tulis, tiga di antaranya tanpa gerbang:**

| Baris | Endpoint | Gerbang |
|---|---|---|
| `:125–126` | `POST ''` → `create_request` | hanya `require_auth` |
| `:215–216` | `PUT /{request_id}` → `update_request` | hanya `require_auth` |
| `:250–251` | `POST /{request_id}/set-status` → `set_status` | hanya `require_auth` |
| `:290–291` | `DELETE /{request_id}` → `delete_request` | ✅ `dependencies=only(*PRODUCTION_ROLES)` |

`DELETE` sudah diperbaiki (tanda `# T-01 2.3` pada barisnya). Tiga sisanya belum.

**Handler paling berisiko** — `backend/routes/dewi_cmt_component_requests.py:250–286`

```python
@router.post('/{request_id}/set-status')
async def set_status(request_id: str, body: dict, user: dict = Depends(require_auth)):
    db = get_db()
    new_status = (body or {}).get('status', '')
    if new_status not in VALID_STATUSES:
        raise HTTPException(400, f'status harus salah satu dari: {VALID_STATUSES}')
    doc = await db.dewi_cmt_component_requests.find_one({'id': request_id})
    if not doc:
        raise HTTPException(404, 'Request tidak ditemukan')
    # ── tidak ada pemeriksaan: doc['vendor_id'] vs vendor milik user ──
    ...
    elif new_status == 'delivered':
        upd['delivered_by'] = user.get('name', '')
        upd['delivered_at'] = now_utc()
        if (body or {}).get('delivery_order_number'):
            upd['delivery_order_number'] = body['delivery_order_number']
    await db.dewi_cmt_component_requests.update_one({'id': request_id}, {'$set': upd})
    return {'ok': True}
```

Validasi yang ada hanya soal **nilai status** dan **urutan transisi** — bukan soal
**siapa** yang berhak mengubah, dan bukan soal **request milik vendor mana**.

### Akibat yang mungkin

- Akun internal apa pun (termasuk dari departemen yang tidak berkaitan) bisa membuat,
  mengubah, dan menaikkan status permintaan komponen.
- Karena router ini juga tidak memasang `deny_external_dep`, akun eksternal yang memegang
  token internal biasa — vendor CMT dan buyer memakai token internal, bukan token berscope
  `aud` seperti klien/livehost/creator — secara teknis dapat menandai permintaan
  **vendor lain** sebagai `delivered`, lengkap dengan nomor surat jalan karangan.
- Permintaan yang salah ditandai `delivered` tidak bisa dikembalikan: transisi hanya maju,
  dan `rejected` ditolak untuk dokumen yang sudah `delivered` (`:264–266`).

### Usulan perbaikan

```python
# satu baris pada router — menutup akses eksternal:
router = APIRouter(prefix="/api/dewi/cmt-component-requests",
                   tags=["Production-CMT-Shortage-Requests"],
                   dependencies=[Depends(deny_external_dep)])

# dan pada tiga endpoint tulis, samakan dengan DELETE yang sudah diperbaiki:
@router.post('', dependencies=only(*PRODUCTION_ROLES))
@router.put('/{request_id}', dependencies=only(*PRODUCTION_ROLES))
@router.post('/{request_id}/set-status', dependencies=only(*PRODUCTION_ROLES))
```

Bila kelak vendor diizinkan menaikkan status permintaannya sendiri, tambahkan pemeriksaan
kepemilikan di dalam handler: `doc['vendor_id']` harus sama dengan vendor pada token,
dengan pola yang sama seperti yang sudah dipakai engine vendor lain yang ter-scope
`vendor_id` (lihat catatan audit M-01/M-02 pada `production_rbac.py:42–44`).

---

## PROD-03 — Gerbang memisahkan internal vs eksternal, bukan antar-peran internal

**Tingkat:** Sedang (keputusan desain, bukan kerusakan) · **Pintu:** keduanya

Sebagian besar router produksi dan maklon memasang satu dependency yang sama:

`backend/routes/production_rbac.py:41–54`

```python
async def deny_external_dep(request: Request):
    """Dependency router: klien maklon & vendor CMT TIDAK boleh menyentuh endpoint admin
    maklon (`/api/dewi/maklon/*`, `/api/prod/cmt-receipts*`, tagihan CMT). ..."""
    from auth import require_auth
    user = await require_auth(request)
    role = user.get('role') or ''
    if role in EXTERNAL_ROLES:
        if role in PROD_VENDOR_ROLES and request.method == 'GET' \
                and request.url.path.rstrip('/') in _VENDOR_ALLOWED_PATHS:
            return user
        raise HTTPException(403, 'Akses ditolak: endpoint ini khusus staf DA. ...')
    return user
```

Ia menolak `EXTERNAL_ROLES` dan **meloloskan seluruh peran internal**. Hasil pemindaian
otorisasi pada berkas rute yang menopang kedua portal:

```
production_pos.py                router_dep=False  write=12  tanpa penjaga=0
vendor_shipment.py               router_dep=False  write=5   tanpa penjaga=0
dewi_cmt_packing.py              router_dep=True   write=13  tanpa penjaga=0
dewi_cmt_permak.py               router_dep=False  write=5   tanpa penjaga=0
dewi_cmt_component_requests.py   router_dep=False  write=4   tanpa penjaga=3   ← PROD-02
dewi_maklon.py                   router_dep=True   write=8   tanpa penjaga=0
exceptions.py (variance)         router_dep=False  write=10  tanpa penjaga=0
rahaza_inventory_issues.py       router_dep=False  write=5   tanpa penjaga=0
rahaza_inventory_workflow.py     router_dep=False  write=5   tanpa penjaga=0
```

Angka `router_dep=True` di atas berarti "terlindung dari akun eksternal", **bukan**
"terbatas pada peran produksi". Endpoint yang benar-benar membedakan peran internal
adalah yang memanggil `require_perm` / `assert_can_act` / `only(...)` di dalamnya —
misalnya `_finish_receipt` pada `dewi_cmt_packing.py:951–958` yang menuntut izin
`cmt.approve` / `cmt.manage` / `production.approve`.

**Artinya:** seorang staf HR atau marketing dengan akun internal yang sah, bila mengetahui
alamat endpoint-nya, secara teknis masih dapat menyentuh sebagian data produksi dan maklon.
Ini konsisten dengan model "satu perusahaan, satu tim internal" — tetapi perlu diputuskan
secara sadar, bukan diasumsikan.

**Usulan:** kalau pemisahan antar-departemen memang diinginkan, langkah paling murah
adalah menambahkan `dependencies=only(*PRODUCTION_ROLES)` pada router-router di atas
(pola yang sudah dipakai `delete_request`), lalu memperlebar daftar perannya hanya di
tempat yang memang perlu. Kalau tidak diinginkan, catat keputusan ini di dokumen arsitektur
agar tidak berulang kali ditemukan sebagai "temuan".

---

## MAK-02 — Satu nama menu, dua layar berbeda

**Tingkat:** Rendah (UX, tapi memicu salah baca data) · **Pintu:** keduanya

`frontend/src/components/erp/portal-shell/portalNav.js`

| Baris | Portal | Label menu | Modul yang dibuka |
|---|---|---|---|
| `:241` | Produksi | **Tracking Produksi** | `prod-monitoring` → `ProductionMonitoringModule` (per **vendor**) |
| `:685` | Maklon | **Tracking Produksi** | `maklon-tracking` → `MaklonProductionTracking` (per **order**) |
| `:692` | Maklon | **Tracking Vendor** | `prod-monitoring` → `ProductionMonitoringModule` (per **vendor**) |

Nama yang sama menunjuk dua layar yang berbeda; dan layar yang sama punya dua nama
tergantung portalnya. Hal serupa terjadi pada `prod-shipments-buyer`
(`:232` "Serah Terima FG" vs `:675` "Dispatch ke Buyer") — tetapi di sana penamaannya
memang beralasan karena penerimanya berbeda (buyer DA vs klien maklon), dan tidak ada
tabrakan nama di dalam satu portal.

**Akibat:** seorang staf yang terbiasa di Portal Produksi lalu membuka Portal Maklon akan
mengklik "Tracking Produksi" dan mendapat layar yang sama sekali lain — lalu menyimpulkan
"datanya hilang".

**Usulan:** ubah label pada `portalNav.js:685` menjadi sesuatu yang menyebut objeknya,
misalnya **"Tracking Order"** atau **"Progress per Order"**, sehingga ketiga pintu
punya nama yang berbeda dan menyebutkan apa yang dikelompokkannya.

---

## Hasil negatif (yang diperiksa dan ternyata bersih)

Bagian ini sengaja dicantumkan: temuan yang tidak ada sama pentingnya dengan yang ada,
supaya pemeriksaan berikutnya tidak mengulang pekerjaan yang sama.

### 1. Tidak ada endpoint tulis tanpa pemanggil (dead endpoint)

Pemindaian dengan normalisasi path (`{param}` → `*` pada backend, `${...}` → `*` pada
template literal frontend):

```
### ENDPOINT TULIS TANPA PEMANGGIL FRONTEND (setelah normalisasi path)
   total endpoint tulis: 102 | tanpa pemanggil: 0
```

Catatan metodologis: pemindaian pertama (tanpa normalisasi) melaporkan ±22 "endpoint mati"
yang seluruhnya palsu — needle "dua segmen terakhir" seperti `/close`, `/status`, `/submit`,
`/toggle` tidak pernah muncul apa adanya pada string frontend yang berisi parameter.
Angka 0 di atas berasal dari pemindaian yang sudah diperbaiki.

### 2. Tidak ada koleksi hantu

Seluruh koleksi yang dibaca modul-modul kedua portal punya penulis yang jelas.
`wh_quarantine_items` sempat tampak sebagai koleksi tanpa penulis, tetapi ternyata ditulis
lewat konstanta: `db[QUARANTINE_COLL].insert_one` pada `core/quarantine.py:218`, serta
`.update_one` pada `:303`, `:421`, dan `:442`. Ini positif palsu dari pemindai, bukan cacat.

### 3. Seluruh menu menunjuk modul yang ada

24 menu Portal Produksi dan 23 menu Portal Maklon diresolusi terhadap `moduleRegistry.js`:
tidak ada satu pun yang menunjuk modul tidak terdaftar, dan tidak ada dua menu dalam satu
portal yang menunjuk modul persis sama secara tidak sengaja. Dua rangkap yang ada memang
disengaja dan berbeda tab: `maklon-dashboard` dan `maklon-alur-produksi`
(`makeModuleWithTab(MaklonDashboard, 'alur')`).

### 4. Rantai kuantitas CMT benar

Diverifikasi lewat eksekusi pada sesi audit sebelumnya (18/18 assertion lulus) dan dibaca
ulang pada sesi ini. Aturan pemiliknya — **"reject ≠ selisih kirim"** — memang diterapkan:

- `qty_claimed_by_cmt` (klaim vendor) dan `qty_actual` (hitung fisik DA) disimpan terpisah;
- `qty_short = max(0, claimed − arrived)` menjadi dokumen kewajiban vendor
  (`dewi_cmt_packing.py:649–655`);
- reject masuk karantina dan buku kuantitas (`qty_reject`, `qty_rework_open`) **tanpa**
  mengurangi `produced_qty` vendor (`dewi_cmt_packing.py:938–940`);
- pematangan AP vendor bersifat idempoten (`:941`).

### 5. Transisi status dijaga di sisi server

`PO_STATUS_TRANSITIONS` (`production_pos.py:39–55`), transisi shipment
(`vendor_shipment.py:519–526`, hanya `Sent → Received`), status penerimaan
(`dewi_cmt_packing.py:904`), dan transisi permak (`dewi_cmt_permak.py:39–47`) semuanya
divalidasi di backend, bukan hanya disembunyikan di layar.

### 6. Pembatasan menu *Input Vendor CMT* konsisten dengan backend

`portalNav.js:213` mencantumkan lima peran, dan komentarnya menyatakan daftar itu **wajib**
sama dengan `core/cmt_override.OVERRIDE_ROLES`. Keduanya cocok. Ini contoh yang baik:
penyembunyian menu didampingi gerbang server, bukan menggantikannya.

---

## Urutan pengerjaan yang disarankan

| # | Tindakan | Perkiraan usaha | Dampak |
|---|---|---|---|
| 1 | Hapus tombol **Konfirmasi & Kurangi Stok** dari layar MI (PROD-01, langkah 1) | menit | Menutup celah kontrol internal terbesar |
| 2 | Gabungkan `legacy_stage_qty` pada pembacaan adapter (MAK-01, opsi 1) | menit | Mengembalikan fungsi layar Tracking Produksi maklon |
| 3 | Pasang `deny_external_dep` + `only(*PRODUCTION_ROLES)` pada router Komponen Kurang (PROD-02) | menit | Menutup akses lintas-vendor |
| 4 | Ubah label menu `portalNav.js:685` (MAK-02) | menit | Menghilangkan salah baca antar-portal |
| 5 | Satukan `confirm` ke `material_issue_engine`, atau matikan endpoint-nya (PROD-01, langkah 2) | jam | Menghapus definisi kedua "mengeluarkan material" |
| 6 | Ganti `_add_stock` dengan `stock_service` pada seluruh jalur potong stok (PROD-01, langkah 4) | jam–hari | Penjaga atomik berlaku menyeluruh |
| 7 | Putuskan sikap terhadap pemisahan peran internal (PROD-03) | diskusi | Menghentikan temuan berulang |
| 8 | Pensiunkan layar stage-qty maklon bila angka kanonik sudah cukup (MAK-01, opsi 3) | hari | Menghapus sumber kebingungan permanen |

---

## Metode dan batasnya

**Yang dikerjakan:**
- Pemetaan seluruh menu kedua portal dari `portalNav.js` → `moduleRegistry.js` → berkas komponen.
- Pemindaian AST atas berkas rute yang menopang kedua portal untuk mendeteksi endpoint tulis
  tanpa gerbang (dependency router, `dependencies=` per-route, atau panggilan penjaga di dalam badan fungsi).
- Pemetaan pemanggilan frontend → backend dengan normalisasi path di kedua sisi.
- Pembacaan berurutan seluruh mesin status (PO, shipment, penerimaan, permak, sampel, komponen).
- **Eksekusi kode** untuk membuktikan MAK-01 (adapter maklon), memakai fungsi murni tanpa database.

**Yang tidak dikerjakan:**
- Tidak ada pengujian ujung-ke-ujung terhadap sistem yang berjalan; tidak ada data produksi
  yang disentuh.
- PROD-01 dibuktikan dengan membandingkan dua jalur kode, bukan dengan uji balapan (*race test*)
  yang dijalankan — uji semacam itu sudah dilakukan pada `core/stock_service` di audit
  sebelumnya dan **lulus**; yang belum diuji adalah jalur legacy yang tidak memakainya.
- Menu analitik (Analitik Produksi, Estimasi AI, Perawatan Mesin, Pusat Kendali) diperiksa
  sebatas pintu dan sumber datanya, bukan kebenaran modelnya.

---

*Disusun bersamaan dengan penyusunan `MANUAL_PORTAL_PRODUKSI.pdf` dan `MANUAL_PORTAL_MAKLON.pdf`.
Setiap temuan di atas sengaja **tidak** diajarkan sebagai cara kerja di dalam kedua manual;
yang dicantumkan di sana hanyalah peringatan singkat beserta rujukan ke berkas ini.*
