"""
Marketing Catalog - Items
Item CRUD + photos + FG integration
"""
import logging
import os
import re
import uuid
import html
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field
from database import get_db
from auth import require_auth, log_activity
from routes.shared import require_perm  # T-01 2.3
from core import material_fields as _mf  # FASE 6.6-B: SSOT nama field + alias legacy yarn_*
from core import catalog_stock as _cstock  # F7: SSOT SATU rumus stok jual (K-6a/K-7a)
from core import product_master as _pm     # F3–F6: SSOT kategori/HPP/harga resmi
from core import catalog_status as _cstatus  # F4: SSOT SATU rumus status katalog
from core import catalog_margin as _cmargin  # sesi #37: SSOT margin + "belum bisa diukur"
from core import product_status as _pstatus  # 2026-11-09 (D5): status produk varian di baris katalog
from core import catalog_runs as _runs       # 2026-11-09: jejak + batalkan aksi massal katalog
from core import catalog_tools as _tools     # 2026-11-09: aksi cepat katalog (status produk, item tersembunyi)

router = APIRouter(prefix='/api/marketing/catalogs', tags=['Marketing-Catalog-items'])

# 2026-11-08 (Asisten AI Tahap B, celah izin) — siapa boleh MENGUBAH item katalog (termasuk harga jual):
# daftar peran yang sama dengan hapus item katalog (T-01 2.3) + `spv_marketing` (SPV Marketing F6.1,
# yang memang menetapkan harga) supaya SPV tidak kehilangan akses yang dulu dimilikinya.
CATALOG_WRITER_ROLES = ('manager_marketing', 'spv_marketing', 'pic_marketing', 'staff_marketing', 'pic_toko',
                        'marketing_kol', 'cs_staff', 'manager', 'owner', 'admin', 'superadmin')
CATALOG_WRITE_DENIED = ('Akses ditolak: hanya tim Marketing yang boleh mengubah item katalog '
                        '(termasuk harga jual).')

# Photo upload settings (disimpan di Emergent Object Storage, URL tetap /api/uploads/products/...)
from object_storage import put_object as _put_object
MAX_PHOTO_BYTES = 5 * 1024 * 1024
ALLOWED_MIMES = {'image/jpeg', 'image/png', 'image/webp'}
ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'webp'}

# Helper functions
def _uid():
    return str(uuid.uuid4())

def _now():
    return datetime.now(timezone.utc)

def _san(value: str, max_len: int = 500) -> str:
    if not isinstance(value, str):
        return value
    return html.escape(value.strip())[:max_len]

def _s(doc: dict) -> dict:
    if doc is None:
        return {}
    out = dict(doc)
    out.pop('_id', None)
    for k, v in out.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return _normalize_pricing_read(out)


def _normalize_pricing_read(out: dict) -> dict:
    """Pastikan field harga kanonik selalu ada saat dibaca (KEPUTUSAN #2).

    Kanonik: harga_jual (final ke customer), harga_coret (promo dicoret),
    harga_original (list resmi), hpp (biaya, internal — dari RnD).
    Backward-compat: item lama hanya punya `price` (=jual) & `original_price`
    (dulu dipakai ganda utk HPP/coret) → dipetakan ke harga_jual/harga_coret.
    Legacy `price`/`original_price` tetap disinkron agar konsumen lama tak rusak.
    """
    legacy_price = float(out.get('price') or 0)
    legacy_original = float(out.get('original_price') or 0)

    harga_jual = out.get('harga_jual')
    harga_jual = float(harga_jual) if harga_jual is not None else legacy_price

    harga_coret = out.get('harga_coret')
    harga_coret = float(harga_coret) if harga_coret is not None else legacy_original

    harga_original = float(out.get('harga_original') or 0)
    hpp = float(out.get('hpp') or 0)

    out['harga_jual'] = harga_jual
    out['harga_coret'] = harga_coret
    out['harga_original'] = harga_original
    out['hpp'] = hpp
    # sinkron legacy (jual→price, coret→original_price)
    out['price'] = harga_jual
    out['original_price'] = harga_coret
    return out


def _pricing_write_fields(data: dict, existing: dict = None) -> dict:
    """Bangun set-field harga untuk WRITE (create/update).

    Menerima input harga baru (harga_jual/harga_coret/harga_original/hpp) DAN/ATAU
    legacy (price/original_price). Menormalkan → simpan field kanonik + legacy sinkron.
    Hanya field yang benar-benar diberikan yang di-set (agar update parsial aman).
    """
    existing = existing or {}
    fields = {}

    def _pick(new_key, legacy_key=None):
        if data.get(new_key) is not None:
            return float(data.get(new_key) or 0)
        if legacy_key and data.get(legacy_key) is not None:
            return float(data.get(legacy_key) or 0)
        return None

    hj = _pick('harga_jual', 'price')
    hc = _pick('harga_coret', 'original_price')
    ho = _pick('harga_original')
    hp = _pick('hpp')

    if hj is not None:
        fields['harga_jual'] = hj
        fields['price'] = hj  # legacy sync
    if hc is not None:
        fields['harga_coret'] = hc
        fields['original_price'] = hc  # legacy sync
    if ho is not None:
        fields['harga_original'] = ho
    if hp is not None:
        fields['hpp'] = hp
    return fields

def _stock_status(qty: float, threshold: float) -> str:
    if qty <= 0:
        return 'out_of_stock'
    elif qty <= threshold:
        return 'low_stock'
    else:
        return 'in_stock'


def variant_identity_fields(row: dict, fg: Optional[dict]) -> dict:
    """Warna & ukuran varian sebuah item katalog, dibaca dari master FG tautannya.

    2026-11-07 (Tahap 5, audit form) — pemilih produk di form Marketing (Kirim Sample,
    Retur, Ulasan, Live) hanya bisa menampilkan "SKU · nama model" karena daftar item
    tidak membawa ukuran sama sekali; ukuran/warna di form Sample lalu jatuh ke isian
    tetap "All Size" / "-". Satu item katalog = satu varian FG, jadi warna & ukurannya
    milik master, bukan diketik ulang.
    """
    fg = fg or {}
    color = (row.get('fg_color') or fg.get('color') or '').strip()
    size = (fg.get('size_code') or row.get('fg_size') or '').strip()
    return {'fg_color': color, 'fg_size': size}


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 3b / F7 — Jembatan stok Toko ↔ Finished Goods
# Konvensi: rahaza_model_variants.sku == kode FG (rahaza_materials.code, type='fg').
#
# 2026-08-10 (F7) — RUMUS stok jual dipindahkan SELURUHNYA ke `core/catalog_stock`.
# Dulu ada TIGA rumus berbeda di tiga pintu (`from-fg` 1 lokasi & qty mentah ·
# `sync-fg-stock` on-hand−reserved semua lokasi · `sync-from-wms` qty mentah semua
# lokasi) ⇒ item baru selalu lahir stok 0 (M2) dan `sync-from-wms` menaikkan stok
# di atas yang tersedia ⇒ OVERSELLING (M3). Fungsi di bawah tinggal delegasi
# supaya pemanggil lama tidak patah, tetapi angkanya kini SATU.
# ═══════════════════════════════════════════════════════════════════════════════
async def resolve_fg_stock_by_sku(db, sku: str) -> dict:
    """Resolve stok jual FG untuk sebuah SKU varian (delegasi SSOT).

    Return: { found, fg_material_id, fg_code, onhand, reserved, available }
    `available` sudah mengecualikan lokasi karantina/blokir (K-6a).
    """
    fg = await _cstock.find_fg_by_sku(db, sku)
    if not fg:
        return {'found': False, 'fg_material_id': None, 'fg_code': '',
                'onhand': 0.0, 'reserved': 0.0, 'available': 0.0}
    res = await _cstock.sellable_stock(db, fg.get('id'))
    return {**res, 'found': True, 'fg_material_id': fg.get('id'),
            'fg_code': fg.get('code') or fg.get('sku') or ''}


async def resolve_item_fg_stock(db, item: dict) -> dict:
    """Stok jual LIVE untuk sebuah catalog item + jenis tautannya (delegasi SSOT)."""
    res = await _cstock.item_sellable(db, item)
    # `found` = master FG-nya ditemukan (bukan "ada baris stok") — dipakai UI
    # untuk membedakan "belum tertaut" dari "tertaut tapi stok 0".
    res['found'] = bool(res.get('fg_material_id'))
    return res


async def _apply_fg_stock_sync(db, item: dict) -> dict:
    """Sinkronkan CACHE stok item Toko dari FG (K-7a).

    `stock_quantity` = stok jual (on-hand − reserved) pada lokasi yang boleh
    dijual. Raise HTTPException bila item tidak tertaut / master FG belum ada.
    """
    res = await _cstock.item_sellable(db, item)
    if res['link_type'] == 'none':
        raise HTTPException(400, 'Item tidak tertaut ke varian/FG. Tautkan varian (variant_id) atau FG dulu.')
    if not res['fg_material_id']:
        if res['link_type'] == 'variant_sku':
            raise HTTPException(404, f"Master FG untuk SKU varian '{res.get('variant_sku','')}' belum ada di inventory (rahaza_materials type='fg').")
        raise HTTPException(404, 'Master FG tidak ditemukan / belum ada stok di WMS.')
    await db.marketing_catalog_items.update_one(
        {'id': item['id']},
        {'$set': _cstock.cache_patch(res, item.get('stock_alert_threshold', 10))})
    new_stock = float(res['available'])
    return {**res, 'found': True, 'new_stock': new_stock,
            'stock_status': _cstock.stock_status(
                new_stock, float(item.get('stock_alert_threshold', 10) or 10))}


async def _refresh_catalog_stats(db, catalog_id: str):
    # 2026-11-06 (pola P7): satu rumus di core.catalog_stock (dulu to_list(500) → katalog besar terpotong)
    await _cstock.refresh_catalog_stats(db, catalog_id)


# 2026-11-09 — item TERSEMBUNYI = item impor lama tanpa `catalog_id` (tidak tampil di layar mana pun yang
# membaca per katalog). Aturan & status produk per baris: SATU tempat di core.catalog_tools.
HIDDEN_ITEM_FILTER = _tools.HIDDEN_ITEM_FILTER
product_status_map = _tools.product_status_map


async def find_hidden_twin(db, account_id: str, fg_material_id: str) -> Optional[dict]:
    """Item tersembunyi yang masih hidup untuk toko + barang jadi ini (atau None).

    Yang sudah diarsipkan oleh "Rapikan item tersembunyi" (`merged_into`) tidak dihitung.
    """
    if not account_id or not fg_material_id:
        return None
    return await db.marketing_catalog_items.find_one({'$and': [
        _tools.LIVE_HIDDEN, {'account_id': account_id},
        {'$or': [{'fg_material_id': fg_material_id}, {'material_id': fg_material_id}]},
    ]}, {'_id': 0, 'id': 1, 'sku': 1})


def _parse_product_status_filter(value: Optional[str]):
    """`stop,dead` / `belum_diisi` → set kode (None = belum diisi); kosong → None (tanpa penyaring)."""
    if value is None or not str(value).strip():
        return None
    out = set()
    for part in str(value).split(','):
        p = part.strip()
        if not p:
            continue
        if p.lower() in (_pstatus.UNSET_FILTER, _pstatus.UNSET_LABEL.lower()):
            out.add(None)
            continue
        try:
            out.add(_pstatus.parse(p))
        except _pstatus.ProductStatusError as e:
            raise HTTPException(400, str(e))
    return out or None


async def require_catalog_writer(request: Request, catalog_id: Optional[str] = None, *,
                                 account_id: Optional[str] = None) -> dict:
    """Gerbang SATU pintu untuk aksi TULIS katalog: ubah harga, penayangan (tayang/draf/arsip/...), aksi massal.

    2026-11-09 — dulu aksi penayangan (dan aksi massal) cukup login, sedangkan ubah harga sudah dijaga peran
    Marketing. Kini sama: izin `toko.manage`/`pricing.approve` (atau peran Marketing selama izin peran belum
    diatur owner), dan staf berlingkup toko hanya untuk katalog tokonya.
    """
    user = await require_perm(request, 'toko.manage', 'pricing.approve',
                              legacy_roles=CATALOG_WRITER_ROLES, message=CATALOG_WRITE_DENIED)
    db = get_db()
    if account_id is None and catalog_id:
        cat = await db.marketing_catalogs.find_one({'id': catalog_id}, {'_id': 0, 'account_id': 1})
        account_id = (cat or {}).get('account_id')
    from core import marketing_account_scope as _scope
    await _scope.assert_account_visible(db, user, account_id)
    return user


# Pydantic models
# ─── Pydantic Models ──────────────────────────────────────────────────────────

class CatalogCreate(BaseModel):
    account_id: str
    name: str
    description: Optional[str] = ''
    platform: Optional[str] = ''     # inherited from account, stored for quick filter
    is_active: Optional[bool] = True


class CatalogUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class CatalogItemCreate(BaseModel):
    sku: str
    name: str
    description: Optional[str] = ''
    price: Optional[float] = Field(default=0, ge=0)          # legacy selling price (=harga_jual)
    original_price: Optional[float] = Field(default=0, ge=0) # legacy (=harga_coret)
    platform_price: Optional[float] = 0 # actual listed price on platform (can differ)
    # KEPUTUSAN #2 — field harga terpisah (kanonik)
    harga_jual: Optional[float] = Field(default=None, ge=0)     # harga final ke customer
    harga_coret: Optional[float] = Field(default=None, ge=0)    # harga dicoret (promo, >= jual)
    harga_original: Optional[float] = Field(default=None, ge=0) # harga normal/list resmi
    hpp: Optional[float] = Field(default=None, ge=0)            # biaya pokok (internal, dari RnD)
    stock_quantity: Optional[float] = Field(default=0, ge=0)
    stock_alert_threshold: Optional[float] = Field(default=10, ge=0)
    material_id: Optional[str] = None   # optional link to WMS material (rahaza_materials)
    model_id: Optional[str] = None      # MKT-2: FK ke rahaza_models (divalidasi bila diisi)
    variant_id: Optional[str] = None    # Fase 3b: FK ke rahaza_model_variants (link stok Toko<->FG)
    platform_url: Optional[str] = ''
    images: Optional[List[str]] = []
    tags: Optional[List[str]] = []
    weight_gram: Optional[float] = Field(default=0, ge=0)
    category: Optional[str] = ''
    category_id: Optional[str] = None   # F6: kategori dari MASTER (divalidasi; menang atas teks)
    variant_info: Optional[str] = ''    # e.g. "Warna: Merah, Size: L"
    is_active: Optional[bool] = True


class CatalogItemUpdate(BaseModel):
    model_id: Optional[str] = None      # MKT-2: FK ke rahaza_models
    variant_id: Optional[str] = None    # Fase 3b: FK ke rahaza_model_variants
    sku: Optional[str] = None
    name: Optional[str] = None
    category_id: Optional[str] = None   # F3: kategori dari MASTER (bukan teks bebas)
    description: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)
    original_price: Optional[float] = Field(default=None, ge=0)
    platform_price: Optional[float] = None
    harga_jual: Optional[float] = Field(default=None, ge=0)
    harga_coret: Optional[float] = Field(default=None, ge=0)
    harga_original: Optional[float] = Field(default=None, ge=0)
    hpp: Optional[float] = Field(default=None, ge=0)
    stock_quantity: Optional[float] = Field(default=None, ge=0)
    stock_alert_threshold: Optional[float] = Field(default=None, ge=0)
    material_id: Optional[str] = None
    platform_url: Optional[str] = None
    images: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    weight_gram: Optional[float] = Field(default=None, ge=0)
    category: Optional[str] = None
    variant_info: Optional[str] = None
    is_active: Optional[bool] = None
    # 2026-11-08 — ALASAN perubahan harga (opsional; dicatat di riwayat harga `marketing_change_log`,
    # tidak disimpan di item). Dipakai juga oleh "Terapkan usulan harga" (K28).
    reason: Optional[str] = Field(default=None, max_length=500)


class StockUpdateBody(BaseModel):
    stock_quantity: float = Field(ge=0)
    notes: Optional[str] = ''


class CatalogItemFromFG(BaseModel):
    """Create catalog item by picking from FG master (rahaza_materials, type='fg').
    Backend auto-fills SKU/name/color/category from FG; user only sets selling price + URL.
    """
    fg_material_id: str  # UUID dari rahaza_materials
    price: float = Field(ge=0)                              # legacy selling price (=harga_jual)
    original_price: Optional[float] = Field(default=0, ge=0)       # legacy (=harga_coret)
    platform_price: Optional[float] = 0       # actual listed price
    harga_jual: Optional[float] = Field(default=None, ge=0)
    harga_coret: Optional[float] = Field(default=None, ge=0)
    harga_original: Optional[float] = Field(default=None, ge=0)
    platform_url: Optional[str] = ''
    images: Optional[List[str]] = []
    tags: Optional[List[str]] = []
    stock_alert_threshold: Optional[float] = Field(default=10, ge=0)
    description_override: Optional[str] = ''  # custom description (optional)
    # F4 — penayangan bisa langsung diisi saat item dibuat (mis. produk pre-order
    # yang memang dijual tanpa stok). Tanpa dua field ini, staf harus membuat item
    # dulu lalu menekan tombol lain — dan langkah kedua itulah yang sering terlupa.
    is_preorder: Optional[bool] = False
    preorder_note: Optional[str] = ''


class BulkStockUpdate(BaseModel):
    updates: List[dict]   # [{ item_id, stock_quantity, notes }]


# ═══════════════════════════════════════════════════════════════════════════════

@router.post('/{catalog_id}/items', status_code=201)
async def add_catalog_item(catalog_id: str, data: CatalogItemCreate, request: Request):
    """Tambah item/produk ke dalam katalog.
    
    NOTE (Legacy mode): Untuk produk baru, prefer endpoint POST /items/from-fg
    yang link langsung ke master FG (rahaza_materials) untuk konsistensi data.
    """
    user = await require_auth(request)
    db = get_db()

    catalog = await db.marketing_catalogs.find_one({'id': catalog_id}, {'_id': 0})
    if not catalog:
        raise HTTPException(404, 'Katalog tidak ditemukan.')

    # Check SKU uniqueness within catalog
    existing_sku = await db.marketing_catalog_items.find_one({
        'catalog_id': catalog_id, 'sku': data.sku.strip().upper()
    })
    if existing_sku:
        raise HTTPException(409, f'SKU {data.sku} sudah ada dalam katalog ini.')

    stock_qty = float(data.stock_quantity or 0)
    threshold = float(data.stock_alert_threshold or 10)

    # MKT-2: validasi FK model RnD bila diisi
    if data.model_id:
        _mdl = await db.rahaza_models.find_one({'id': data.model_id, 'active': {'$ne': False}})
        if not _mdl:
            raise HTTPException(400, f"model_id '{data.model_id}' tidak valid (rahaza_models — MKT-2)")

    # Fase 3b: link ke varian produksi internal (rahaza_model_variants)
    variant_sku = ''
    variant_info_auto = ''
    _model_doc = {}
    if data.variant_id:
        _rv = await db.rahaza_model_variants.find_one({'id': data.variant_id, 'active': {'$ne': False}}, {'_id': 0})
        if not _rv:
            raise HTTPException(400, f"variant_id '{data.variant_id}' tidak valid (rahaza_model_variants — Fase 3b)")
        variant_sku = _rv.get('sku', '')
        variant_info_auto = f"Warna: {_rv.get('color_name', '')}, Size: {_rv.get('size_code', '')}"
        # auto-isi model_id & sku dari varian bila belum di-set manual
        if not data.model_id:
            data.model_id = _rv.get('model_id')
        if not (data.sku and data.sku.strip()):
            data.sku = variant_sku
    if data.model_id:
        _model_doc = await db.rahaza_models.find_one({'id': data.model_id}, {'_id': 0}) or {}
        # M8/K-9a — produk yang sudah dihentikan tidak boleh ditawarkan
        if _model_doc and not _pm.model_is_live(_model_doc):
            raise HTTPException(
                400, f"Produk '{_model_doc.get('name') or _model_doc.get('code')}' sudah "
                     'DIHENTIKAN (non-aktif) — tidak boleh ditambahkan ke katalog.')

    doc = {
        'id': _uid(),
        'catalog_id': catalog_id,
        'account_id': catalog.get('account_id', ''),
        'platform': catalog.get('platform', ''),
        'sku': _san(data.sku, 100).upper(),
        'name': _san(data.name, 200),
        'description': _san(data.description or '', 2000),
        'price': float(data.price or 0),
        'original_price': float(data.original_price or 0),
        'platform_price': float(data.platform_price or 0),
        'stock_quantity': stock_qty,
        'stock_alert_threshold': threshold,
        'stock_status': _stock_status(stock_qty, threshold),
        'material_id': data.material_id,
        'model_id': data.model_id,             # MKT-2: FK rahaza_models
        'variant_id': data.variant_id,         # Fase 3b: FK rahaza_model_variants
        'variant_sku': variant_sku,            # Fase 3b: SKU varian produksi (link stok FG)
        'fg_material_id': None,                # mark as legacy (no master link)
        'source': 'manual',                    # manual entry vs from_fg
        'platform_url': (data.platform_url or '').strip(),
        'images': data.images or [],
        'tags': data.tags or [],
        'weight_gram': float(data.weight_gram or 0),
        'variant_info': _san(data.variant_info or variant_info_auto or '', 200),
        'is_active': data.is_active,
        'last_stock_sync': None,
        'created_at': _now(),
        'updated_at': _now(),
        'created_by': user.get('id', ''),
    }
    # F3/F6 — kategori item MENGIKUTI MASTER (T3: berhenti menerima teks bebas).
    # Item manual tanpa tautan master masih boleh memakai `category_id` pilihan staf.
    if _model_doc:
        _master = _pm.master_display_fields(_model_doc)
        doc.update({k: v for k, v in _master.items() if k != 'retail_price_master'})
        # 2026-11-09 (B1) — harga resmi per SKU dulu (FG varian), cadangan harga model
        _fg_v = await _cstock.find_fg_by_sku(db, variant_sku) if variant_sku else {}
        doc['retail_price_master'], doc['retail_price_source'] = _pm.official_price(_fg_v, _model_doc)
        if not doc.get('weight_gram'):
            doc['weight_gram'] = _master['weight_gram']
    else:
        # F6 (2026-08-10) — layar katalog sekarang MEMILIH kategori dari master,
        # jadi `category_id` yang tervalidasi selalu menang atas teks bebas.
        # Dulu satu-satunya jalan adalah mencocokkan `category` (teks) ke master;
        # kalau teksnya tidak cocok, kategorinya diam-diam kosong — staf mengira
        # sudah tersimpan padahal hilang. Sekarang teks salah tak mungkin lolos.
        if data.category_id:
            _cat = await _pm.get_category(db, data.category_id)
            if not _cat or _cat.get('active') is False:
                raise HTTPException(
                    400, f"category_id '{data.category_id}' tidak dikenal/non-aktif. "
                         'Pilih kategori dari Master Kategori Produk.')
        else:
            _cat = await _pm.resolve_category_by_text(db, data.category or '', allow_create=False)
        _pm.apply_category(doc, _cat)
        doc['retail_price_master'] = 0.0
        doc['retail_price_source'] = 'none'
        doc.setdefault('hpp_source', 'none')
    # KEPUTUSAN #2 — normalisasi & simpan field harga terpisah (+ legacy sync)
    doc.update(_pricing_write_fields(data.dict()))
    doc.setdefault('harga_original', float(data.harga_original or 0) if data.harga_original is not None else 0.0)
    doc.setdefault('hpp', float(data.hpp or 0) if data.hpp is not None else 0.0)

    await db.marketing_catalog_items.insert_one(doc)
    # F7/K-7a — kalau item ini tertaut ke master, stok bukan input manusia:
    # langsung diselaraskan dengan stok jual sebenarnya (mustahil lahir 0 palsu).
    if doc.get('variant_sku') or doc.get('fg_material_id') or doc.get('material_id'):
        try:
            await _cstock.sync_item_cache(db, doc)
            doc = await db.marketing_catalog_items.find_one({'id': doc['id']}, {'_id': 0}) or doc
        except Exception:
            logging.getLogger(__name__).exception(
                'sync stok awal gagal untuk item katalog %s', doc.get('sku'))
    await _refresh_catalog_stats(db, catalog_id)
    return {'ok': True, 'item': _s(doc)}


# ═══════════════════════════════════════════════════════════════════════════════
# PHOTO UPLOAD — Catalog item photos (Phase B Toko Cutover)
# ═══════════════════════════════════════════════════════════════════════════════

class RemovePhotoIn(BaseModel):
    url: str


@router.post('/{catalog_id}/items/{item_id}/photos')
async def upload_catalog_item_photo(
    catalog_id: str,
    item_id: str,
    file: UploadFile = File(...),
    request: Request = None,
):
    """Upload a photo for a catalog item. Saves under /app/uploads/products/{item_id}/
    and appends URL to both `images[]` (marketing native) and `photos[]` (legacy)
    arrays for backwards compatibility.
    """
    await require_auth(request)
    db = get_db()
    item = await db.marketing_catalog_items.find_one(
        {'id': item_id, 'catalog_id': catalog_id}, {'_id': 0}
    )
    if not item:
        raise HTTPException(404, 'Item tidak ditemukan dalam katalog ini.')

    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(415, f'Hanya {sorted(ALLOWED_MIMES)} diizinkan')
    data = await file.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, 'Ukuran file > 5MB')
    if len(data) < 50:
        raise HTTPException(400, 'File terlalu kecil (min 50 bytes)')

    ext = 'jpg'
    if file.filename and '.' in file.filename:
        candidate = file.filename.rsplit('.', 1)[-1].lower()
        candidate = re.sub(r'[^a-z0-9]', '', candidate)
        if candidate in ALLOWED_EXT:
            ext = candidate
    fname = f'{uuid.uuid4().hex}.{ext}'
    try:
        url = _put_object(f'products/{item_id}/{fname}', data, file.content_type or 'image/jpeg')['url']
    except Exception as e:
        raise HTTPException(503, f'Penyimpanan berkas tidak tersedia: {e}')

    # Dual-write to images[] (marketing native) and photos[] (legacy back-compat)
    await db.marketing_catalog_items.update_one(
        {'id': item_id, 'catalog_id': catalog_id},
        {
            '$addToSet': {'images': url, 'photos': url},
            '$set': {'updated_at': _now()},
        },
    )
    return {'ok': True, 'url': url, 'size': len(data)}


@router.post('/{catalog_id}/items/{item_id}/photos/remove')
async def remove_catalog_item_photo(
    catalog_id: str,
    item_id: str,
    payload: RemovePhotoIn,
    request: Request,
):
    """Remove a photo URL from a catalog item. Pulls from both `images[]` and
    `photos[]` arrays and best-effort deletes the underlying file.
    """
    await require_auth(request)
    db = get_db()
    item = await db.marketing_catalog_items.find_one(
        {'id': item_id, 'catalog_id': catalog_id}, {'_id': 0}
    )
    if not item:
        raise HTTPException(404, 'Item tidak ditemukan.')

    await db.marketing_catalog_items.update_one(
        {'id': item_id, 'catalog_id': catalog_id},
        {
            '$pull': {'images': payload.url, 'photos': payload.url},
            '$set': {'updated_at': _now()},
        },
    )

    # Object storage tidak punya API hapus — cukup lepas referensinya dari dokumen (di atas).
    # Berkas lama di pod (sebelum migrasi) dibersihkan best-effort.
    try:
        if payload.url.startswith('/api/uploads/products/'):
            rel = payload.url.replace('/api/uploads/products/', '')
            fp = Path('/app/uploads/products') / rel
            if fp.exists() and fp.is_file():
                os.unlink(fp)
    except Exception:
        logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

    return {'ok': True, 'message': 'Foto dihapus'}


# ═══════════════════════════════════════════════════════════════════════════════
# FG MASTER INTEGRATION — Item creation from FG (catalog-scoped routes)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post('/{catalog_id}/items/from-fg', status_code=201)
async def add_catalog_item_from_fg(catalog_id: str, data: CatalogItemFromFG, request: Request):
    """Tambah SATU catalog item dari master FG produk.

    Isi dokumennya dibangun oleh :func:`create_item_from_fg` supaya jalur satuan
    (layar Katalog) dan jalur **massal multi-toko**
    (`POST /api/marketing/catalogs/assign-from-master`) tidak mungkin melahirkan
    dua bentuk item yang berbeda untuk hal yang sama.
    """
    user = await require_auth(request)
    db = get_db()

    catalog = await db.marketing_catalogs.find_one({'id': catalog_id}, {'_id': 0})
    if not catalog:
        raise HTTPException(404, 'Katalog tidak ditemukan.')

    doc, err = await create_item_from_fg(db, catalog, data.fg_material_id,
                                        data.dict(), user)
    if err:
        raise HTTPException(err[0], err[1])

    await _refresh_catalog_stats(db, catalog_id)
    return {'ok': True, 'item': _s(doc),
            'message': f"Produk '{doc.get('name')}' berhasil ditambahkan ke katalog dari "
                       f"master FG (stok jual {doc.get('stock_quantity', 0):g})"}


async def create_item_from_fg(db, catalog: dict, fg_material_id: str,
                              opts: dict, user: dict):
    """Bangun + simpan satu item katalog dari master FG.

    → ``(doc, None)`` kalau berhasil · ``(None, (status, pesan))`` kalau DITOLAK.

    Sengaja **tidak** melempar `HTTPException`: pemanggil massal perlu melanjutkan
    ke produk berikutnya sambil mencatat alasan penolakan per produk (kalau satu
    produk non-aktif membatalkan seluruh permintaan, staf harus menebak produk
    mana yang bermasalah dari 10 pilihan).

    Auto-fill SKU, nama, berat, **kategori (dari master, bukan teks bebas)**,
    warna, info varian, HPP + sumbernya, dan **harga jual awal dari harga resmi
    master** (`retail_price` — keputusan K-3a). Staf hanya perlu menyesuaikan
    harga platform bila berbeda.

    Yang diperbaiki 2026-08-10:
      * **M1/M2** stok tidak lagi dibaca dari "lokasi default" dengan `qty` mentah
        (itu sebabnya item baru SELALU lahir stok 0) — sekarang lewat SSOT
        `core/catalog_stock.sellable_stock()`.
      * **M8/KT-7** FG milik produk **non-aktif** ditolak 400 (dulu hanya `type=='fg'`
        yang diperiksa, sehingga produk yang sudah dihentikan tetap bisa dijual).
      * Item ikut menyimpan `variant_id`/`variant_sku` bila FG-nya punya varian,
        supaya sinkron massal tidak melewatinya (M5).
    """
    catalog_id = catalog['id']
    opts = opts or {}

    # Validate FG material exists & is type='fg'
    fg = await db.rahaza_materials.find_one({'id': fg_material_id}, {'_id': 0})
    if not fg:
        return None, (404, 'FG produk tidak ditemukan di master inventory.')
    if fg.get('type') != 'fg':
        return None, (400, f"Material bukan tipe FG (tipe: {fg.get('type')}). "
                           'Hanya Finished Goods yang bisa di-link ke catalog.')
    if fg.get('active') is False:
        return None, (400, f"FG '{fg.get('code')}' sudah non-aktif — barang yang "
                           'dihentikan tidak boleh ditawarkan di katalog.')

    # M8/KT-7 — produk (model) induknya harus masih hidup
    model = {}
    if fg.get('model_id'):
        model = await db.rahaza_models.find_one({'id': fg['model_id']}, {'_id': 0}) or {}
        if model and not _pm.model_is_live(model):
            return None, (
                400, f"Produk '{model.get('name') or model.get('code')}' sudah DIHENTIKAN "
                     '(non-aktif) — tidak boleh ditambahkan ke katalog. '
                     'Aktifkan kembali produknya dulu di Master Produk.')

    # Check if FG already in this catalog (prevent duplicate)
    existing = await db.marketing_catalog_items.find_one({
        'catalog_id': catalog_id,
        'fg_material_id': fg_material_id,
    })
    if existing:
        return None, (409, f"Produk '{fg.get('name')}' sudah ada di katalog ini.")
    # 2026-11-09 (klarifikasi D7) — item impor lama TANPA katalog ("tersembunyi") untuk toko & barang jadi
    # yang sama juga dihitung "sudah ada": dulu Isi dari Master membuat kembarannya (451 kembar di VPS).
    hidden = await find_hidden_twin(db, catalog.get('account_id'), fg_material_id)
    if hidden:
        return None, (409, f"Produk '{fg.get('name')}' sudah ada sebagai item tersembunyi toko ini "
                           f"(impor lama tanpa katalog). Rapikan dulu lewat Alat katalog › Rapikan item tersembunyi.")

    # F7 — stok jual SEBENARNYA lewat SSOT (semua lokasi kecuali karantina/blokir)
    stock_res = await _cstock.sellable_stock(db, fg['id'])
    stock_qty = float(stock_res['available'])
    threshold = float(opts.get('stock_alert_threshold') or 10)

    # Auto-fill from FG record
    fg_code = fg.get('code') or ''
    fg_name = fg.get('name') or ''
    fg_color = fg.get('color') or ''
    # FASE 6.6-B: baca kanonik `composition` dulu, fallback legacy `yarn_type`
    fg_yarn = _mf.read_field(fg, 'composition', '') or ''
    fg_unit = fg.get('unit') or 'pcs'

    # Build variant info from FG attributes
    variant_parts = []
    fg_size = (fg.get('size_code') or '').strip()
    if fg_color:
        variant_parts.append(f"Warna: {fg_color}")
    if fg_size:
        variant_parts.append(f"Size: {fg_size}")
    if fg_yarn:
        variant_parts.append(f"Material: {fg_yarn}")
    variant_info = ' | '.join(variant_parts)

    description = (opts.get('description_override') or '').strip()
    if not description:
        description = f"FG: {fg_name}"
        if variant_info:
            description += f" ({variant_info})"

    # tautan varian (kalau FG ini lahir dari varian master) — menutup M5
    variant_id = fg.get('variant_id')
    variant_sku = fg.get('sku') or fg_code

    doc = {
        'id': _uid(),
        'catalog_id': catalog_id,
        'account_id': catalog.get('account_id', ''),
        'platform': catalog.get('platform', ''),
        # Master FG references
        'fg_material_id': fg.get('id'),
        'material_id': fg.get('id'),       # legacy alias for backward compat
        'fg_code': fg_code,
        'fg_name': fg_name,
        'fg_color': fg_color,
        'fg_size': fg_size,
        'model_id': fg.get('model_id'),
        'variant_id': variant_id,
        'variant_sku': variant_sku,
        'source': 'from_fg',
        # Display fields (denormalized dari MASTER — punya penyegar, lihat refresh-from-master)
        'sku': fg_code.upper(),
        'name': fg_name,
        'description': _san(description, 2000),
        'variant_info': variant_info,
        'unit': fg_unit,
        # Pricing
        'platform_price': float(opts.get('platform_price') or 0),
        # Stock (cache tampilan — sumber kebenaran tetap FG, K-7a)
        'stock_quantity': stock_qty,
        'stock_alert_threshold': threshold,
        'stock_status': _cstock.stock_status(stock_qty, threshold),
        'stock_source': 'variant_sku' if variant_sku else 'fg_material',
        'stock_in_sync': True,
        'fg_onhand': stock_res['onhand'],
        'fg_reserved': stock_res['reserved'],
        'fg_available': stock_res['available'],
        'fg_excluded_onhand': stock_res['excluded_onhand'],
        'last_stock_sync': _now(),
        # Marketing fields
        'platform_url': (opts.get('platform_url') or '').strip(),
        'images': opts.get('images') or [],
        'tags': opts.get('tags') or [],
        'is_active': True,
        # F4 — penayangan: item baru SELALU lahir 'draft'. Tidak ada jalan otomatis
        # menjadi 'published': tayang butuh BUKTI (URL produk di marketplace), dan
        # bukti tidak boleh dikarang oleh sistem.
        'publish_state': 'published' if (opts.get('platform_url') or '').strip() else 'draft',
        'published_at': _now() if (opts.get('platform_url') or '').strip() else None,
        'rejected_reason': '',
        'is_preorder': bool(opts.get('is_preorder') or False),
        'preorder_note': _san(opts.get('preorder_note') or '', 300),
        'status_history': [],
        'created_at': _now(),
        'updated_at': _now(),
        'created_by': (user or {}).get('id', ''),
    }

    # F3/F5/F6 — kategori, berat, HPP+sumber, harga resmi: SEMUA dari master.
    # Kalau FG belum punya stempel master (dokumen lama), pakai model induknya.
    master = _pm.master_display_fields(model) if model else {}
    doc['category_id'] = fg.get('category_id') or master.get('category_id')
    doc['category_code'] = fg.get('category_code') or master.get('category_code') or ''
    doc['category_name'] = fg.get('category_name') or master.get('category_name') or \
        fg.get('category') or ''
    doc['category'] = doc['category_name']
    doc['weight_gram'] = float(fg.get('weight_gram') or master.get('weight_gram') or 0)
    # HPP + sumbernya. 2026-11-06 (Tahap 2): urutan yang SAMA dengan tombol segarkan
    # (`core.catalog_margin.resolve_catalog_hpp`: WAC aktual → HPP standar FG → model → 0);
    # dulu tambah-dari-FG mendahulukan rata-rata model sehingga HPP per warna hilang.
    doc['hpp'], doc['hpp_source'] = _cmargin.resolve_catalog_hpp(fg, model)
    doc['hpp_updated_at'] = _now()
    # 2026-11-09 (klarifikasi B1) — harga resmi PER SKU (FG) dulu, cadangan harga model. Dulu hanya harga
    # model yang dibaca (0 dari 138 terisi) sehingga semua item lahir Rp 0 walau 583 SKU berharga.
    doc['retail_price_master'], doc['retail_price_source'] = _pm.official_price(fg, model)
    # F4.3 — foto MASTER ikut terbawa (D13). Marketing tidak lagi memulai dari nol foto.
    doc['master_images'] = _pm.master_images(model) if model else []

    # K-3a — harga jual RESMI dari master jadi nilai AWAL; boleh ditimpa per platform
    price_in = _pricing_write_fields(opts)
    # `price_mode='kosong'` (Isi dari master → "Kosongkan") = sengaja 0, jangan diisi harga resmi.
    if not price_in.get('harga_jual') and opts.get('price_mode') != 'kosong':
        official = doc['retail_price_master']
        if official:
            price_in['harga_jual'] = official
            price_in['price'] = official
    doc['harga_original'] = (float(opts.get('harga_original') or 0)
                             if opts.get('harga_original') is not None else 0.0)
    doc.setdefault('harga_coret', 0.0)
    doc.setdefault('original_price', 0.0)
    doc.setdefault('harga_jual', 0.0)
    doc.setdefault('price', 0.0)
    doc.update(price_in)

    # F4 — cache status turunan supaya filter/indeks bisa memakainya (nilai
    # sebenarnya SELALU dihitung ulang saat dibaca).
    doc.update(_cstatus.cache_patch(doc, stock_qty))

    await db.marketing_catalog_items.insert_one(dict(doc))
    doc.pop('_id', None)
    return doc, None


@router.get('/{catalog_id}/items/{item_id}/fg-stock')
async def peek_item_fg_stock(catalog_id: str, item_id: str, request: Request):
    """Fase 3b: Intip stok FG live untuk item Toko (read-only, tanpa mengubah stok).

    Dipakai UI untuk menampilkan 'Stok FG tersedia' di samping item yang tertaut varian.
    """
    await require_auth(request)
    db = get_db()
    item = await db.marketing_catalog_items.find_one({'id': item_id, 'catalog_id': catalog_id}, {'_id': 0})
    if not item:
        raise HTTPException(404, 'Item tidak ditemukan.')
    res = await resolve_item_fg_stock(db, item)
    return {
        'ok': True,
        'item_id': item_id,
        'variant_id': item.get('variant_id'),
        'variant_sku': item.get('variant_sku') or '',
        'link_type': res['link_type'],
        'found': res['found'],
        'fg_material_id': res['fg_material_id'],
        'fg_code': res['fg_code'],
        'onhand': res['onhand'],
        'reserved': res['reserved'],
        'available': res['available'],
        'catalog_stock_quantity': float(item.get('stock_quantity', 0) or 0),
        'in_sync': res['found'] and abs(float(item.get('stock_quantity', 0) or 0) - res['available']) < 0.001,
    }


@router.put('/{catalog_id}/items/{item_id}/sync-fg-stock')
async def sync_item_stock_from_fg(catalog_id: str, item_id: str, request: Request):
    """Manual sync stok single catalog item dari master FG (auto-override, KEPUTUSAN 2b).

    Prioritas tautan (Fase 3b):
      1. variant_sku  → cocokkan by SKU ke master FG (jalur varian internal).
      2. fg_material_id / material_id → langsung by material FG.
    stock_quantity item Toko di-set = available FG (onhand - reserved).
    """
    await require_auth(request)
    db = get_db()

    item = await db.marketing_catalog_items.find_one({'id': item_id, 'catalog_id': catalog_id}, {'_id': 0})
    if not item:
        raise HTTPException(404, 'Item tidak ditemukan.')

    res = await _apply_fg_stock_sync(db, item)
    await _refresh_catalog_stats(db, catalog_id)

    return {
        'ok': True,
        'stock_quantity': res['new_stock'],
        'stock_status': res['stock_status'],
        'link_type': res['link_type'],
        'fg_material_id': res['fg_material_id'],
        'fg_code': res['fg_code'],
        'fg_onhand': res['onhand'],
        'fg_reserved': res['reserved'],
        'fg_available': res['available'],
    }



async def _resolve_rnd_hpp(db, item: dict):
    """HPP terkini untuk sebuah item katalog + SUMBERNYA.

    Urutan resolusi (SSOT `core.product_master.resolve_hpp`):
      1. `item.model_id` → `rahaza_models.hpp` (R&D) → `base_hpp` (manual)
      2. `item.fg_material_id`/`material_id` → `rahaza_materials.hpp`
         (lalu model induknya bila FG-nya masih 0)

    2026-08-10 (P1b) — dulu berhenti di `rahaza_models.hpp`. Produk yang dibuat
    MANUAL tidak punya HPP R&D, jadi katalog selalu `hpp = 0` dan margin mustahil
    dihitung. Sekarang `base_hpp` manual ikut dipakai dan sumbernya dilaporkan.

    2026-08-23 — bila FG-nya sudah punya HPP bersumber **'bom'** (hasil
    `core/product_costing`: BOM × harga pembelian + upah), FG DIDAHULUKAN atas
    model. Alasannya: HPP BOM disimpan **per ukuran** di FG, sedangkan
    `rahaza_models.hpp` hanya satu angka rata-rata; mengambil model akan
    menghapus perbedaan antar size (S lebih murah dari XL).

    Return: (hpp: float|None, source: str, origin: str)
    """
    model = None
    if item.get('model_id'):
        model = await db.rahaza_models.find_one({'id': item['model_id']}, {'_id': 0})
    fg = None
    fg_id = item.get('fg_material_id') or item.get('material_id')
    if fg_id:
        fg = await db.rahaza_materials.find_one({'id': fg_id}, {'_id': 0})
        if not model and (fg or {}).get('model_id'):
            model = await db.rahaza_models.find_one({'id': fg['model_id']}, {'_id': 0})

    # 2026-11-06 (Tahap 2): SATU urutan untuk tambah-dari-FG DAN segarkan
    # (`core.catalog_margin.resolve_catalog_hpp`: WAC aktual → HPP standar FG → model → 0).
    if not (model or fg):
        return None, 'no_source', 'no_source'
    hpp, src = _cmargin.resolve_catalog_hpp(fg, model)
    fg_used = bool(fg) and bool(_cmargin.effective_fg_cost(fg)['source'])
    return hpp, src, ('rahaza_materials' if fg_used or not model else 'rahaza_models')


@router.post('/{catalog_id}/items/{item_id}/refresh-hpp')
async def refresh_item_hpp(catalog_id: str, item_id: str, request: Request):
    """Tarik-ulang HPP satu item katalog dari master (per-item)."""
    await require_auth(request)
    db = get_db()
    item = await db.marketing_catalog_items.find_one({'id': item_id, 'catalog_id': catalog_id}, {'_id': 0})
    if not item:
        raise HTTPException(404, 'Item tidak ditemukan.')
    hpp, source, origin = await _resolve_rnd_hpp(db, item)
    if hpp is None:
        raise HTTPException(400, 'Item belum tertaut ke Model/FG — HPP tidak bisa di-refresh otomatis.')
    await db.marketing_catalog_items.update_one(
        {'id': item_id},
        {'$set': {'hpp': hpp, 'hpp_source': source, 'hpp_updated_at': _now(),
                  'updated_at': _now()}},
    )
    item['hpp'] = hpp
    item['hpp_source'] = source
    return {'ok': True, 'hpp': hpp, 'source': source, 'origin': origin, 'item': _s(item)}


@router.post('/{catalog_id}/refresh-hpp')
async def refresh_catalog_hpp_bulk(catalog_id: str, request: Request):
    """Tarik-ulang HPP SEMUA item katalog yang tertaut ke master (bulk)."""
    await require_auth(request)
    db = get_db()
    catalog = await db.marketing_catalogs.find_one({'id': catalog_id}, {'_id': 0, 'id': 1})
    if not catalog:
        raise HTTPException(404, 'Katalog tidak ditemukan.')
    items = await db.marketing_catalog_items.find({'catalog_id': catalog_id}, {'_id': 0}).to_list(5000)
    updated, skipped = 0, 0
    now = _now()
    for it in items:
        hpp, source, _origin = await _resolve_rnd_hpp(db, it)
        if hpp is None:
            skipped += 1
            continue
        await db.marketing_catalog_items.update_one(
            {'id': it['id']},
            {'$set': {'hpp': hpp, 'hpp_source': source, 'hpp_updated_at': now,
                      'updated_at': now}},
        )
        updated += 1
    return {'ok': True, 'updated': updated, 'skipped_no_source': skipped, 'total': len(items)}


@router.post('/{catalog_id}/refresh-from-master')
async def refresh_catalog_from_master(catalog_id: str, request: Request):
    """**F8/M7** — segarkan field tampilan item katalog dari MASTER.

    Pasangan `refresh-hpp` yang sudah ada. Menutup M7: `name`, `category*`,
    `weight_gram`, `variant_info` dulu disalin SEKALI saat item dibuat dan tidak
    pernah diperbarui ⇒ salinan tanpa penyegar = laporan yang berbohong dengan sopan.

    Yang **tidak** disentuh: harga platform, URL, foto, tag, deskripsi jualan —
    itu memang milik platform (prinsip "katalog adalah PENYAJIAN, bukan sumber
    kebenaran").
    """
    await require_auth(request)
    db = get_db()
    catalog = await db.marketing_catalogs.find_one({'id': catalog_id}, {'_id': 0, 'id': 1})
    if not catalog:
        raise HTTPException(404, 'Katalog tidak ditemukan.')

    items = await db.marketing_catalog_items.find({'catalog_id': catalog_id}, {'_id': 0}).to_list(5000)
    blocked = await _cstock.blocked_location_ids(db)
    updated, skipped, changes = 0, 0, []
    for it in items:
        link = await _cstock.resolve_link(db, it)
        fg = link.get('fg') or {}
        if not fg:
            skipped += 1
            continue
        model = {}
        if fg.get('model_id'):
            model = await db.rahaza_models.find_one({'id': fg['model_id']}, {'_id': 0}) or {}
        master = _pm.master_display_fields(model) if model else {}

        patch = {
            'name': fg.get('name') or it.get('name'),
            'sku': (fg.get('code') or it.get('sku') or '').upper(),
            'fg_code': fg.get('code') or '',
            'fg_name': fg.get('name') or '',
            'fg_color': fg.get('color') or '',
            'model_id': fg.get('model_id') or it.get('model_id'),
            'variant_id': fg.get('variant_id') or it.get('variant_id'),
            'variant_sku': fg.get('sku') or fg.get('code') or it.get('variant_sku') or '',
            'category_id': fg.get('category_id') or master.get('category_id'),
            'category_code': fg.get('category_code') or master.get('category_code') or '',
            'category_name': fg.get('category_name') or master.get('category_name') or '',
            'weight_gram': float(fg.get('weight_gram') or master.get('weight_gram') or 0),
            # 2026-11-09 (B1) — harga resmi per SKU dulu, cadangan harga model
            'retail_price_master': _pm.official_price(fg, model)[0],
            'retail_price_source': _pm.official_price(fg, model)[1],
            # F4.3 — foto master ikut disegarkan: R&D menambah foto sesudah item
            # dibuat adalah kejadian normal, dan salinan tanpa penyegar akan basi.
            'master_images': _pm.master_images(model) if model else (it.get('master_images') or []),
            'updated_at': _now(),
        }
        patch['category'] = patch['category_name']
        vparts = []
        if fg.get('color') or fg.get('color_name'):
            vparts.append(f"Warna: {fg.get('color_name') or fg.get('color')}")
        if fg.get('size_code'):
            vparts.append(f"Size: {fg.get('size_code')}")
        if vparts:
            patch['variant_info'] = ' | '.join(vparts)
        hpp, src, _o = await _resolve_rnd_hpp(db, {**it, **patch})
        if hpp is not None:
            patch['hpp'] = hpp
            patch['hpp_source'] = src
            patch['hpp_updated_at'] = _now()

        diff = {k: v for k, v in patch.items()
                if k not in ('updated_at', 'hpp_updated_at') and it.get(k) != v}
        await db.marketing_catalog_items.update_one({'id': it['id']}, {'$set': patch})
        # stok juga disegarkan supaya satu tombol = satu kebenaran (K-7a)
        await _cstock.sync_item_cache(db, {**it, **patch}, blocked_locs=blocked)
        updated += 1
        if diff:
            changes.append({'sku': patch['sku'], 'changed': sorted(diff.keys())})

    await _refresh_catalog_stats(db, catalog_id)
    return {
        'ok': True, 'updated': updated, 'skipped_not_linked': skipped,
        'total': len(items), 'changes': changes,
        'message': (f'{updated} item disegarkan dari master '
                    f'({len(changes)} benar-benar berubah, {skipped} belum tertaut).'),
    }


# ══════════════════════════════════════════════════════════════════════════════
# F4.2 — TRANSISI PENAYANGAN (K8)
#
# KENAPA INI ADA
# --------------
# Sebelum F4 tidak ada satu pun cara mencatat "produk ini sudah tayang di toko":
# `platform_url` bisa diisi lewat form edit, tetapi tidak ada waktu tayang, tidak ada
# alasan kalau ditolak platform, dan tidak ada jejak siapa yang mengubah apa. Akibatnya
# pertanyaan paling sering di rapat — *"dari 120 produk, yang benar-benar sudah tayang
# berapa?"* — hanya bisa dijawab dengan membuka satu per satu di aplikasi marketplace.
#
# Lima tombol di bawah adalah keputusan MANUSIA yang dicatat beserta buktinya. Status
# `catalog_status` tidak pernah diketik: ia dihitung dari keputusan ini + stok jual.
# ══════════════════════════════════════════════════════════════════════════════
class PublishBody(BaseModel):
    platform_url: str = Field(default='', max_length=1000)
    note: Optional[str] = Field(default='', max_length=300)


class ReasonBody(BaseModel):
    reason: str = Field(default='', max_length=500)


class PreorderBody(BaseModel):
    is_preorder: bool = True
    note: Optional[str] = Field(default='', max_length=300)


class PhotoReorderBody(BaseModel):
    urls: List[str] = Field(min_length=1)


class BulkTransitionBody(BaseModel):
    item_ids: List[str] = Field(min_length=1)
    # publish (HANYA item yang sudah punya URL sah sendiri) | unpublish | reject | preorder | unpreorder |
    # archive | restore
    action: str
    reason: Optional[str] = Field(default='', max_length=500)
    # 2026-11-09 — pratinjau: hitung yang akan berubah & yang dilewati (+ alasannya) tanpa menulis apa pun
    dry_run: bool = False


async def _get_item_or_404(db, catalog_id: str, item_id: str) -> dict:
    item = await db.marketing_catalog_items.find_one(
        {'id': item_id, 'catalog_id': catalog_id}, {'_id': 0})
    if not item:
        raise HTTPException(404, 'Item katalog tidak ditemukan di katalog ini.')
    return item


async def _apply_transition(db, item: dict, patch: dict, *, action: str,
                            note: str, user: dict) -> dict:
    """Simpan perubahan penayangan + jejaknya + segarkan cache status.

    Jejak ditulis ke `status_history[]` pada dokumen item (F6 nanti memindahkannya
    ke `marketing_change_log`; sampai itu ada, jejaknya tetap HARUS ada — perubahan
    penayangan tanpa jejak berarti "siapa yang mengarsipkan produk ini?" tidak
    pernah bisa dijawab).
    """
    merged = {**item, **patch}
    res = await _cstock.item_sellable(db, merged)
    available = res['available'] if res.get('link_type') != 'none' else None
    patch.update(_cstatus.cache_patch(merged, available))
    patch['updated_at'] = _now()
    patch['updated_by'] = (user or {}).get('email') or (user or {}).get('id', '')

    entry = {
        'at': _now(),
        'by': patch['updated_by'],
        'action': action,
        'from': _cstatus.publish_state_of(item),
        'to': patch.get('publish_state', _cstatus.publish_state_of(item)),
        'catalog_status': patch['catalog_status'],
        'note': _san(note or '', 300),
    }
    await db.marketing_catalog_items.update_one(
        {'id': item['id']},
        {'$set': patch, '$push': {'status_history': {'$each': [entry], '$slice': -50}}})
    await log_activity(
        (user or {}).get('id', ''), (user or {}).get('name') or (user or {}).get('email', 'system'),
        f'catalog_{action}', 'marketing_catalog_items',
        f"Item '{item.get('sku')}' ({item.get('name')}) → {patch['catalog_status']}"
        + (f" · {note}" if note else ''))
    fresh = await db.marketing_catalog_items.find_one({'id': item['id']}, {'_id': 0})
    return _cstatus.decorate(_s(fresh), available)


@router.post('/{catalog_id}/items/{item_id}/publish')
async def publish_catalog_item(catalog_id: str, item_id: str, data: PublishBody,
                               request: Request):
    """Tandai item **TAYANG** — wajib menyertakan URL produk sebagai bukti.

    URL-nya bukan formalitas: tanpa tautan, tidak ada cara memeriksa bahwa produk
    benar-benar ada di toko (dan tidak ada cara membuka produknya saat komplain
    pembeli masuk). URL kosong / bukan http(s) ⇒ **400**.
    """
    user = await require_catalog_writer(request, catalog_id)
    db = get_db()
    item = await _get_item_or_404(db, catalog_id, item_id)

    url = (data.platform_url or '').strip() or str(item.get('platform_url') or '').strip()
    if not url:
        raise HTTPException(400, "URL produk di marketplace wajib diisi sebagai bukti "
                                 "tayang — tanpa itu status 'tayang' tidak bisa diperiksa "
                                 "siapa pun.")
    if not _cstatus.is_valid_url(url):
        raise HTTPException(400, f"URL produk tidak sah: '{url}'. Harus dimulai dengan "
                                 f"http:// atau https:// (tempel tautan produk dari "
                                 f"aplikasi/website marketplace).")

    row = await _apply_transition(db, item, {
        'publish_state': 'published',
        'platform_url': url,
        'published_at': _now(),
        'rejected_reason': '',
        'is_active': True,
    }, action='publish', note=data.note or '', user=user)
    await _refresh_catalog_stats(db, catalog_id)
    return {'ok': True, 'item': row,
            'message': f"'{item.get('name')}' ditandai TAYANG · status sekarang: "
                       f"{row['catalog_status']} ({row['catalog_status_reason']})"}


@router.post('/{catalog_id}/items/{item_id}/unpublish')
async def unpublish_catalog_item(catalog_id: str, item_id: str, data: ReasonBody,
                                 request: Request):
    """Turunkan item dari tayang (kembali **draft**) — mis. mau revisi foto/harga."""
    user = await require_catalog_writer(request, catalog_id)
    db = get_db()
    item = await _get_item_or_404(db, catalog_id, item_id)
    row = await _apply_transition(db, item, {
        'publish_state': 'draft',
        'unpublished_at': _now(),
    }, action='unpublish', note=data.reason or '', user=user)
    await _refresh_catalog_stats(db, catalog_id)
    return {'ok': True, 'item': row,
            'message': f"'{item.get('name')}' diturunkan dari tayang → DRAFT."}


@router.post('/{catalog_id}/items/{item_id}/reject')
async def reject_catalog_item(catalog_id: str, item_id: str, data: ReasonBody,
                             request: Request):
    """Catat item **DITOLAK platform** — alasan WAJIB.

    Alasan penolakan adalah satu-satunya cara tim tahu apa yang harus diperbaiki
    (foto, klaim di deskripsi, kategori). "Ditolak" tanpa alasan hanya memindahkan
    kebingungan ke orang berikutnya.
    """
    user = await require_catalog_writer(request, catalog_id)
    db = get_db()
    item = await _get_item_or_404(db, catalog_id, item_id)
    why = (data.reason or '').strip()
    if not why:
        raise HTTPException(400, 'Alasan penolakan wajib diisi — tanpa alasan, tim '
                                 'tidak tahu apa yang harus diperbaiki.')
    row = await _apply_transition(db, item, {
        'publish_state': 'rejected',
        'rejected_reason': _san(why, 500),
        'rejected_at': _now(),
    }, action='reject', note=why, user=user)
    await _refresh_catalog_stats(db, catalog_id)
    return {'ok': True, 'item': row,
            'message': f"'{item.get('name')}' ditandai DITOLAK: {why}"}


@router.post('/{catalog_id}/items/{item_id}/preorder')
async def set_catalog_item_preorder(catalog_id: str, item_id: str, data: PreorderBody,
                                   request: Request):
    """Tandai / lepas tanda **pre-order**.

    Pre-order mengubah arti stok 0: produk tayang tanpa stok memang disengaja, jadi
    statusnya `PRE_ORDER`, bukan `HABIS`. Tanpa penanda ini, daftar "habis" penuh
    produk yang sebenarnya sedang dijual pre-order dan daftar itu berhenti dipakai.
    """
    user = await require_catalog_writer(request, catalog_id)
    db = get_db()
    item = await _get_item_or_404(db, catalog_id, item_id)
    row = await _apply_transition(db, item, {
        'is_preorder': bool(data.is_preorder),
        'preorder_note': _san(data.note or '', 300),
    }, action='preorder' if data.is_preorder else 'unpreorder',
        note=data.note or '', user=user)
    await _refresh_catalog_stats(db, catalog_id)
    return {'ok': True, 'item': row,
            'message': (f"'{item.get('name')}' ditandai PRE-ORDER."
                        if data.is_preorder else
                        f"Tanda pre-order '{item.get('name')}' dilepas.")}


@router.post('/{catalog_id}/items/{item_id}/archive')
async def archive_catalog_item(catalog_id: str, item_id: str, data: ReasonBody,
                              request: Request):
    """Arsipkan item (NONAKTIF) — tidak dihapus, supaya riwayat pesanannya tetap utuh."""
    user = await require_catalog_writer(request, catalog_id)
    db = get_db()
    item = await _get_item_or_404(db, catalog_id, item_id)
    row = await _apply_transition(db, item, {
        'publish_state': 'archived',
        'is_active': False,
        'archived_at': _now(),
        'archived_reason': _san(data.reason or '', 500),
    }, action='archive', note=data.reason or '', user=user)
    await _refresh_catalog_stats(db, catalog_id)
    return {'ok': True, 'item': row,
            'message': f"'{item.get('name')}' diarsipkan (NONAKTIF). Data & riwayat "
                       f"pesanannya tetap tersimpan."}


@router.post('/{catalog_id}/items/{item_id}/restore')
async def restore_catalog_item(catalog_id: str, item_id: str, data: ReasonBody,
                              request: Request):
    """Kembalikan item dari arsip ke **draft** (harus ditayangkan ulang dengan bukti)."""
    user = await require_catalog_writer(request, catalog_id)
    db = get_db()
    item = await _get_item_or_404(db, catalog_id, item_id)
    row = await _apply_transition(db, item, {
        'publish_state': 'draft',
        'is_active': True,
        'archived_at': None,
    }, action='restore', note=data.reason or '', user=user)
    await _refresh_catalog_stats(db, catalog_id)
    return {'ok': True, 'item': row,
            'message': f"'{item.get('name')}' dikembalikan dari arsip → DRAFT."}


BULK_ACTIONS = ('publish', 'unpublish', 'reject', 'preorder', 'unpreorder', 'archive', 'restore')
BULK_MAX_ITEMS = 2000


def bulk_patch(action: str, item: dict, reason: str = ''):
    """``(patch, None)`` bila item berubah, ``(None, alasan dilewati)`` bila tidak — SATU aturan untuk pratinjau
    dan untuk aksi sebenarnya (angka di popup konfirmasi = angka yang benar-benar berubah)."""
    state = _cstatus.publish_state_of(item)
    stored = str(item.get('publish_state') or '').strip().lower()
    now = _now()
    if action == 'publish':
        if state == 'archived':
            return None, 'diarsipkan — kembalikan dulu'
        if stored == 'published':
            return None, 'sudah tayang'
        url = str(item.get('platform_url') or '').strip()
        if not url:
            return None, 'belum ada URL produk'
        if not _cstatus.is_valid_url(url):
            return None, 'URL produk tidak sah'
        return {'publish_state': 'published', 'published_at': now, 'rejected_reason': '',
                'is_active': True}, None
    if action == 'unpublish':
        if state == 'archived':
            return None, 'diarsipkan — pakai Kembalikan'
        if state != 'published':
            return None, 'belum tayang'
        return {'publish_state': 'draft', 'unpublished_at': now}, None
    if action == 'reject':
        if state == 'archived':
            return None, 'diarsipkan'
        if state == 'rejected' and str(item.get('rejected_reason') or '') == _san(reason or '', 500):
            return None, 'sudah ditandai ditolak'
        return {'publish_state': 'rejected', 'rejected_reason': _san(reason or '', 500),
                'rejected_at': now}, None
    if action == 'preorder':
        if state == 'archived':
            return None, 'diarsipkan'
        if item.get('is_preorder'):
            return None, 'sudah pra-pesan'
        return {'is_preorder': True, 'preorder_note': _san(reason or '', 300)}, None
    if action == 'unpreorder':
        if not item.get('is_preorder'):
            return None, 'bukan pra-pesan'
        return {'is_preorder': False, 'preorder_note': ''}, None
    if action == 'archive':
        if state == 'archived':
            return None, 'sudah diarsipkan'
        return {'publish_state': 'archived', 'is_active': False, 'archived_at': now,
                'archived_reason': _san(reason or '', 500)}, None
    if action == 'restore':
        if state != 'archived':
            return None, 'tidak diarsipkan'
        return {'publish_state': 'draft', 'is_active': True, 'archived_at': None}, None
    return None, 'aksi tidak dikenal'


def skip_summary(skipped: list) -> dict:
    out: dict = {}
    for s in skipped:
        out[s['why']] = out.get(s['why'], 0) + 1
    return out


@router.post('/{catalog_id}/items/bulk-transition')
async def bulk_transition_items(catalog_id: str, data: BulkTransitionBody,
                                request: Request):
    """Aksi massal penayangan untuk baris terpilih — pratinjau (`dry_run`) lalu jalankan.

    2026-11-09 (klarifikasi D3/D6) — `publish` kini ADA, dengan satu syarat keras: hanya item yang SUDAH punya
    URL produk sah **miliknya sendiri** yang ditayangkan; item tanpa URL dilewati dan disebut alasannya. Tidak
    ada satu URL yang diisikan ke banyak produk — bukti tayang per item tetap terjaga. Item yang tidak berubah
    (mis. sudah diarsipkan) dilewati dengan alasan, bukan "diubah" diam-diam. Setiap aksi yang menulis dicatat
    (`core.catalog_runs`) dan bisa DIBATALKAN dari Alat katalog › Riwayat aksi massal.
    """
    user = await require_catalog_writer(request, catalog_id)
    db = get_db()
    action = (data.action or '').strip().lower()
    if action not in BULK_ACTIONS:
        raise HTTPException(400, f"Aksi massal tidak dikenal: '{action}'. Pilihan: "
                                 'tayangkan (yang ber-URL), jadikan draf, tandai ditolak, pra-pesan, '
                                 'lepas pra-pesan, arsipkan, kembalikan.')
    if action == 'reject' and not data.dry_run and not (data.reason or '').strip():
        raise HTTPException(400, 'Alasan penolakan wajib diisi.')
    ids = list(dict.fromkeys(data.item_ids))
    if len(ids) > BULK_MAX_ITEMS:
        raise HTTPException(400, f'Paling banyak {BULK_MAX_ITEMS} item per aksi massal ({len(ids)} dipilih).')

    found = {d['id']: d for d in await db.marketing_catalog_items.find(
        {'catalog_id': catalog_id, 'id': {'$in': ids}}, {'_id': 0}).to_list(len(ids))}
    plan, skipped = [], []
    for iid in ids:
        item = found.get(iid)
        if not item:
            skipped.append({'item_id': iid, 'sku': '', 'why': 'tidak ditemukan di katalog ini'})
            continue
        patch, why = bulk_patch(action, item, data.reason or '')
        if why:
            skipped.append({'item_id': iid, 'sku': item.get('sku'), 'name': item.get('name'), 'why': why})
        else:
            plan.append((item, patch))
    label = _runs.KIND_LABEL.get(f'transisi:{action}', action)
    if data.dry_run:
        return {'ok': True, 'dry_run': True, 'action': action, 'action_label': label,
                'would_change': len(plan), 'skipped': len(skipped),
                'skip_summary': skip_summary(skipped), 'skipped_items': skipped[:50],
                'sample': [{'sku': it.get('sku'), 'name': it.get('name')} for it, _p in plan[:10]],
                'message': f'{len(plan)} item akan diubah ({label})'
                           + (f' · {len(skipped)} dilewati' if skipped else '')}

    done, changes = [], []
    for item, patch in plan:
        before = _runs.snapshot(item, patch.keys())
        row = await _apply_transition(db, item, dict(patch), action=action,
                                      note=data.reason or '', user=user)
        changes.append({'item_id': item['id'], 'catalog_id': catalog_id, 'sku': item.get('sku'),
                        'before': before, 'after': dict(patch)})
        done.append({'item_id': item['id'], 'sku': item.get('sku'),
                     'catalog_status': row['catalog_status']})
    run = None
    if changes:
        run = await _runs.record(db, kind=f'transisi:{action}', user=user, changes=changes,
                                 catalog_ids=[catalog_id],
                                 summary={'changed': len(done), 'skipped': len(skipped),
                                          'skip_summary': skip_summary(skipped)})
    await _refresh_catalog_stats(db, catalog_id)
    return {'ok': True, 'action': action, 'action_label': label, 'changed': len(done),
            'failed': len(skipped), 'skipped': len(skipped), 'skip_summary': skip_summary(skipped),
            'results': done, 'errors': skipped[:200], 'run_id': (run or {}).get('id'),
            'message': f"{len(done)} item diperbarui ({label})"
                       + (f" · {len(skipped)} dilewati" if skipped else '')}


@router.post('/{catalog_id}/items/{item_id}/photos/reorder')
async def reorder_catalog_item_photos(catalog_id: str, item_id: str,
                                      data: PhotoReorderBody, request: Request):
    """Ubah urutan foto marketplace — foto pertama = **foto utama** (`primary_image`).

    Tanpa ini, foto utama adalah "yang diunggah paling awal" selamanya: satu foto
    percobaan yang diunggah lebih dulu akan mewakili produk di seluruh layar.
    """
    user = await require_auth(request)
    db = get_db()
    item = await _get_item_or_404(db, catalog_id, item_id)
    current = [u for u in (item.get('images') or []) if u]
    wanted = [str(u).strip() for u in data.urls if str(u or '').strip()]
    unknown = [u for u in wanted if u not in current]
    if unknown:
        raise HTTPException(400, f"{len(unknown)} foto tidak ada pada item ini — muat "
                                 f"ulang daftar foto lalu coba lagi.")
    # foto yang tidak disebut tetap dipertahankan di belakang (tidak pernah hilang)
    ordered = wanted + [u for u in current if u not in wanted]
    await db.marketing_catalog_items.update_one(
        {'id': item_id},
        {'$set': {'images': ordered, 'photos': ordered, 'updated_at': _now(),
                  'updated_by': (user or {}).get('email', '')}})
    return {'ok': True, 'images': ordered, 'primary_image': ordered[0] if ordered else None,
            'message': 'Urutan foto disimpan — foto pertama dipakai sebagai foto utama.'}


@router.post('/{catalog_id}/items/{item_id}/refresh-from-master')
async def refresh_item_from_master(catalog_id: str, item_id: str, request: Request):
    """Segarkan SATU item dari master (kategori, berat, HPP, harga resmi, **foto master**)."""
    await require_auth(request)
    db = get_db()
    item = await _get_item_or_404(db, catalog_id, item_id)
    link = await _cstock.resolve_link(db, item)
    fg = link.get('fg') or {}
    if not fg:
        raise HTTPException(400, 'Item ini belum tertaut ke Master Produk, jadi tidak ada '
                                 'yang bisa disegarkan. Tautkan dulu ke FG produk.')
    model = {}
    if fg.get('model_id'):
        model = await db.rahaza_models.find_one({'id': fg['model_id']}, {'_id': 0}) or {}
    master = _pm.master_display_fields(model) if model else {}
    patch = {
        'name': fg.get('name') or item.get('name'),
        'sku': (fg.get('code') or item.get('sku') or '').upper(),
        'fg_code': fg.get('code') or '',
        'fg_name': fg.get('name') or '',
        'fg_color': fg.get('color') or '',
        'model_id': fg.get('model_id') or item.get('model_id'),
        'category_id': fg.get('category_id') or master.get('category_id'),
        'category_code': fg.get('category_code') or master.get('category_code') or '',
        'category_name': fg.get('category_name') or master.get('category_name') or '',
        'weight_gram': float(fg.get('weight_gram') or master.get('weight_gram') or 0),
        'retail_price_master': _pm.official_price(fg, model)[0],   # 2026-11-09 (B1) per SKU dulu
        'retail_price_source': _pm.official_price(fg, model)[1],
        'master_images': _pm.master_images(model) if model else (item.get('master_images') or []),
        'updated_at': _now(),
    }
    patch['category'] = patch['category_name']
    hpp, src, _o = await _resolve_rnd_hpp(db, {**item, **patch})
    if hpp is not None:
        patch['hpp'] = hpp
        patch['hpp_source'] = src
        patch['hpp_updated_at'] = _now()
    await db.marketing_catalog_items.update_one({'id': item_id}, {'$set': patch})
    await _cstock.sync_item_cache(db, {**item, **patch})
    fresh = await db.marketing_catalog_items.find_one({'id': item_id}, {'_id': 0})
    res = await _cstock.item_sellable(db, fresh)
    return {'ok': True,
            'item': _cstatus.decorate(_s(fresh),
                                      res['available'] if res.get('link_type') != 'none' else None),
            'message': f"Item '{patch['sku']}' disegarkan dari master "
                       f"({len(patch['master_images'])} foto master)."}



@router.get('/{catalog_id}/items')
async def list_catalog_items(
    catalog_id: str,
    request: Request,
    search: Optional[str] = None,
    status: Optional[str] = None,  # in_stock | low_stock | out_of_stock
    category: Optional[str] = None,
    category_id: Optional[str] = None,
    is_active: Optional[bool] = None,
    attention: Optional[str] = None,  # F11: unlinked | stale | all
    catalog_status: Optional[str] = None,   # F4: DRAFT,PRE_ORDER,ACTIVE,HABIS,... (koma)
    publish_state: Optional[str] = None,    # F4: draft|published|rejected|archived
    has_photo: Optional[bool] = None,       # F4: true = punya foto (master/marketplace)
    sort: Optional[str] = None,             # F4: name|price|margin|stock|status|updated
    order: Optional[str] = None,            # asc|desc
    skip: int = 0,
    limit: int = 100,
    product_status: Optional[str] = None,   # 2026-11-09 (D5): stop,dead,slow,best_seller,new,belum_diisi (koma)
):
    """List item dalam katalog dengan filter.

    **K-7a** — setiap baris menyertakan `available` yang **DIHITUNG LIVE** dari FG
    (bukan angka simpanan) plus penanda `in_sync`. `stock_quantity` tetap ada
    sebagai cache tampilan, tetapi layar tidak perlu mempercayainya lagi:
    kalau berbeda, `in_sync=false` dan UI menandainya "stok basi".

    **F6** — filter memakai `category_id` (master), bukan `$regex` teks bebas,
    dan setiap baris melaporkan `margin`, `margin_pct`, `retail_price_master`
    serta `price_delta_vs_master` (selisih harga platform vs harga resmi — K-3a).

    **F11 — `attention`** = `unlinked` | `stale` | `all`: hanya item yang
    BERMASALAH. Filternya WAJIB di server, bukan di layar: item bermasalah bisa
    berada di halaman ke-2 (paginasi 10/hal) sehingga banner "1 item belum
    tertaut ke master" dulu memberi tahu ada masalah **tanpa satu pun cara
    menemukannya** — satu sesi pengujian penuh habis karena ini.

    Perbaikan kejujuran yang menyertainya: `stock_summary.stale/unlinked` sekarang
    dihitung untuk **SELURUH katalog**, bukan hanya baris pada halaman yang
    sedang tampil (dulu katalog 300 item hanya melaporkan masalah dari 100
    pertama, dan tak ada yang tahu).

    **F4** — setiap baris juga membawa `catalog_status` (TURUNAN, satu rumus di
    `core/catalog_status.py`), `catalog_status_reason` (alasan yang bisa dibaca
    staf), `publish_state`, `primary_image`, dan `image_count`.
    `stock_summary.by_status` menghitung SELURUH katalog per status supaya angka
    ringkas tidak berubah hanya karena pindah halaman.
    """
    await require_auth(request)
    db = get_db()

    q: dict = {'catalog_id': catalog_id}
    if search:
        # 2026-11-07 (Tahap 5) — teks cari di-escape: "(" atau "+" dulu membuat 500.
        rx = re.escape(search.strip())
        q['$or'] = [
            {'name': {'$regex': rx, '$options': 'i'}},
            {'sku': {'$regex': rx, '$options': 'i'}},
            {'tags': {'$regex': rx, '$options': 'i'}},
        ]
    if status:
        q['stock_status'] = status
    if category_id:
        q['category_id'] = category_id
    elif category:
        # kompatibilitas layar lama (teks) — master tetap yang benar
        q['category'] = {'$regex': category, '$options': 'i'}
    if is_active is not None:
        q['is_active'] = is_active

    # Seluruh katalog (sesuai filter) dibaca supaya hitungan kesehatan data jujur
    # dan filter `attention` bekerja lintas halaman. Batas 5000 = pagar mutu, dan
    # kalau tersentuh dilaporkan apa adanya lewat `counts_truncated`.
    HARD_CAP = 5000
    all_docs = await db.marketing_catalog_items.find(q, {'_id': 0}).sort(
        'name', 1).limit(HARD_CAP).to_list(HARD_CAP)

    # ── stok LIVE untuk semua baris sekaligus (query KONSTAN, bukan N+1) ───────
    blocked = await _cstock.blocked_location_ids(db)
    links = await _cstock.resolve_links_bulk(db, all_docs)
    mids = [v['fg_material_id'] for v in links.values() if v.get('fg_material_id')]
    smap = await _cstock.sellable_map(db, mids, blocked_locs=blocked)
    # Sesi #37 — biaya FG untuk margin: `hpp_fifo_avg` → `hpp` FG → `hpp` katalog.
    # Satu kueri untuk seluruh katalog (bukan N+1), sama pola dengan `smap`.
    fgcost = await _cmargin.fg_cost_map(db, mids)
    # 2026-11-09 (D5) — status produk varian (Baru · Best Seller · Slow · Dead · Stop), satu kueri.
    pstat = await product_status_map(db, links)
    # 2026-11-09 (B1) — kolom "harga resmi master" dihitung LIVE dari master (per SKU → model), bukan salinan
    # yang lahir Rp 0 saat item dibuat dan baru benar setelah "Segarkan dari master".
    pmap = await _pm.official_price_map(db, mids)
    want_ps = _parse_product_status_filter(product_status)
    by_pstatus = {c: 0 for c in _pstatus.CODES}
    by_pstatus[_pstatus.UNSET_FILTER] = 0

    rows = []
    stale = unlinked = 0
    by_status = _cstatus.empty_by_status()   # F4 — ringkas per status, SELURUH katalog
    stale_status: list = []                 # cache status yang perlu dirapikan
    for d in all_docs:
        row = _s(d)
        lk = links.get(d['id']) or {}
        res = smap.get(lk.get('fg_material_id')) or dict(_cstock.EMPTY)
        cache = float(row.get('stock_quantity') or 0)
        linked = bool(lk.get('fg_material_id'))
        row['link_type'] = lk.get('link_type')
        row['fg_material_id'] = lk.get('fg_material_id')
        row['fg_code'] = lk.get('fg_code') or row.get('fg_code') or ''
        row.update(variant_identity_fields(row, lk.get('fg')))
        row['available'] = res['available'] if linked else None
        row['fg_onhand'] = res['onhand']
        row['fg_reserved'] = res['reserved']
        row['fg_excluded_onhand'] = res['excluded_onhand']
        row['in_sync'] = (abs(cache - res['available']) < 0.001) if linked else False
        row['stock_live_status'] = (
            _cstock.stock_status(res['available'],
                                 float(row.get('stock_alert_threshold') or 10))
            if linked else 'unlinked')
        # F11 — kenapa baris ini "perlu perhatian" (ditulis, bukan disimpulkan UI)
        row['needs_attention'] = (not linked) or (not row['in_sync'])
        row['attention_reason'] = (
            'Belum tertaut ke Master Produk — stoknya tidak bisa dihitung otomatis '
            'dan tidak bisa dijual lewat alur order.' if not linked
            else ('Angka simpanan stok berbeda dari stok jual sebenarnya '
                  '(klik "Sinkron Stok FG" untuk merapikan).' if not row['in_sync'] else ''))
        if not linked:
            unlinked += 1
        elif not row['in_sync']:
            stale += 1

        # F6 — margin & selisih harga vs harga resmi master
        # Sesi #37: rumus margin dipindah ke `core.catalog_margin`. Dulu di sini
        # `hpp = 0` melahirkan margin 100% (dan `harga_jual = 0` melahirkan 0%) —
        # dua angka yang terlihat sah padahal artinya "tidak diketahui".
        hj = float(row.get('harga_jual') or 0)
        if lk.get('fg_material_id') in pmap:
            official, row['retail_price_source'] = pmap[lk['fg_material_id']]
        else:
            official = float(row.get('retail_price_master') or 0)
        _cmargin.decorate(row, fgcost.get(lk.get('fg_material_id')))
        row['retail_price_master'] = official
        row['price_delta_vs_master'] = round(hj - official, 2) if official else 0.0

        # ── F4 — STATUS TURUNAN + FOTO ────────────────────────────────────────
        row = _cstatus.decorate(row, row['available'])
        mimgs = row.get('master_images') or []
        imgs = [u for u in (row.get('images') or []) if u]
        row['primary_image'] = (imgs[0] if imgs
                                else ((mimgs[0] or {}).get('url') if mimgs else None))
        row['image_count'] = len(imgs) + len(mimgs)
        row['has_photo'] = row['image_count'] > 0
        ps_code = pstat.get(d['id'])
        row['product_status'] = ps_code
        row['product_status_label'] = _pstatus.label(ps_code)
        by_pstatus[ps_code or _pstatus.UNSET_FILTER] += 1
        by_status[row['catalog_status']] = by_status.get(row['catalog_status'], 0) + 1
        # cache status disegarkan hanya bila BERBEDA — hasil hitung yang benar,
        # cache mengikuti (bukan sebaliknya).
        if d.get('catalog_status') != row['catalog_status']:
            stale_status.append((d['id'], row['catalog_status'],
                                 row['catalog_status_reason']))
        rows.append(row)

    # Cache status yang basi dirapikan sekali jalan (maks 500 per permintaan supaya
    # halaman tidak pernah lambat karena pekerjaan latar belakang).
    for _id, _st, _why in stale_status[:500]:
        await db.marketing_catalog_items.update_one(
            {'id': _id},
            {'$set': {'catalog_status': _st, 'catalog_status_reason': _why,
                      'catalog_status_at': _now()}})

    # ── F11 — saring "perlu perhatian" SETELAH klasifikasi, SEBELUM paginasi ───
    # Ringkasan margin dihitung atas SELURUH katalog (sebelum saringan/paginasi):
    # kalau dihitung per halaman, "berapa item yang belum bisa diukur" berubah
    # setiap kali orang pindah halaman dan tidak ada angka yang bisa dipercaya.
    margin_summary = _cmargin.summarize(rows)
    att = (attention or '').strip().lower()
    if att in ('unlinked', 'stale', 'all', 'any'):
        if att == 'unlinked':
            rows = [r for r in rows if r['link_type'] == 'none' or not r['fg_material_id']]
        elif att == 'stale':
            rows = [r for r in rows if r['fg_material_id'] and not r['in_sync']]
        else:
            rows = [r for r in rows if r['needs_attention']]

    # ── F4 — saring status penayangan (juga SETELAH klasifikasi: statusnya turunan,
    #        jadi tidak mungkin disaring lewat query Mongo tanpa mempercayai cache) ─
    want_status = [s.strip().upper() for s in (catalog_status or '').split(',') if s.strip()]
    if want_status:
        bad = [s for s in want_status if s not in _cstatus.CATALOG_STATUSES]
        if bad:
            raise HTTPException(400, f"catalog_status tidak dikenal: {', '.join(bad)}. "
                                     f"Pilihan: {', '.join(_cstatus.CATALOG_STATUSES)}")
        rows = [r for r in rows if r['catalog_status'] in want_status]
    if publish_state:
        ps = publish_state.strip().lower()
        if ps not in _cstatus.PUBLISH_STATES:
            raise HTTPException(400, f"publish_state tidak dikenal: {ps}. "
                                     f"Pilihan: {', '.join(_cstatus.PUBLISH_STATES)}")
        rows = [r for r in rows if r['publish_state'] == ps]
    if has_photo is not None:
        rows = [r for r in rows if bool(r['has_photo']) is bool(has_photo)]
    if want_ps is not None:
        rows = [r for r in rows if (r.get('product_status') or None) in want_ps]

    # ── F4 — urutan bisa dipilih (default nama) ────────────────────────────────
    SORTERS = {
        'name': lambda r: str(r.get('name') or '').lower(),
        'price': lambda r: float(r.get('harga_jual') or 0),
        'margin': lambda r: float(r.get('margin') or 0),
        'stock': lambda r: (r.get('available') if r.get('available') is not None else -1),
        'status': lambda r: _cstatus.CATALOG_STATUSES.index(r['catalog_status']),
        'updated': lambda r: str(r.get('updated_at') or ''),
    }
    sk = (sort or 'name').strip().lower()
    if sk not in SORTERS:
        raise HTTPException(400, f"sort tidak dikenal: {sk}. "
                                 f"Pilihan: {', '.join(SORTERS)}")
    rows.sort(key=SORTERS[sk], reverse=(str(order or 'asc').lower() == 'desc'))

    total = len(rows)
    out = rows[skip:skip + limit] if (skip or limit) else rows

    return {'ok': True, 'items': out, 'total': total,
            'filters_applied': {'catalog_status': want_status,
                                'publish_state': (publish_state or '').lower() or None,
                                'has_photo': has_photo, 'attention': att or None,
                                'product_status': sorted(c or _pstatus.UNSET_FILTER for c in want_ps)
                                if want_ps is not None else None,
                                'sort': sk, 'order': (order or 'asc').lower()},
            'margin_summary': margin_summary,
            'status_options': [{'value': s, 'label': _cstatus.STATUS_LABEL[s]}
                               for s in _cstatus.CATALOG_STATUSES],
            'product_status_options': [{'value': c, 'label': _pstatus.LABELS[c]} for c in _pstatus.CODES]
            + [{'value': _pstatus.UNSET_FILTER, 'label': _pstatus.UNSET_LABEL}],
            'stock_summary': {'stale': stale, 'unlinked': unlinked,
                              'attention': stale + unlinked,
                              'scanned': len(all_docs),
                              'by_status': by_status,
                              'by_product_status': by_pstatus,
                              'counts_truncated': len(all_docs) >= HARD_CAP,
                              'live_source': 'core.catalog_stock (K-6a/K-7a)',
                              'status_source': 'core.catalog_status (F4.1)'}}


@router.put('/{catalog_id}/items/{item_id}')
async def update_catalog_item(catalog_id: str, item_id: str, data: CatalogItemUpdate, request: Request):
    """Update item data (termasuk harga, stok, dll).

    2026-11-08 (Asisten AI Tahap B, celah izin — keputusan owner no. 11): dulu cukup login, jadi
    siapa pun bisa mengubah harga jual toko mana pun tanpa jejak. Kini penjaganya sama dengan
    menghapus item katalog (izin `toko.manage`/`pricing.approve`, atau peran Marketing selama izin
    peran belum diatur owner), staf berlingkup toko hanya untuk katalog tokonya, dan setiap
    perubahan harga jual/harga coret dicatat sebagai RIWAYAT HARGA (siapa, kapan, lama → baru,
    alasan) di `marketing_change_log` — entitas/aksi yang sama dengan "Terapkan usulan harga".
    """
    user = await require_perm(request, 'toko.manage', 'pricing.approve',
                              legacy_roles=CATALOG_WRITER_ROLES, message=CATALOG_WRITE_DENIED)
    db = get_db()

    item = await db.marketing_catalog_items.find_one(
        {'id': item_id, 'catalog_id': catalog_id}, {'_id': 0}
    )
    if not item:
        raise HTTPException(404, 'Item tidak ditemukan.')
    account_id = item.get('account_id')
    if not account_id:
        cat = await db.marketing_catalogs.find_one({'id': catalog_id}, {'_id': 0, 'account_id': 1})
        account_id = (cat or {}).get('account_id')
    from core import marketing_account_scope as _scope
    await _scope.assert_account_visible(db, user, account_id)

    reason = (data.reason or '').strip()
    patch = {k: v for k, v in data.dict().items() if v is not None}
    patch.pop('reason', None)
    # ── T3 — kategori item katalog TIDAK BOLEH lagi ditimpa teks bebas ────────
    # Dulu `CatalogManagementModule.jsx` mengirim `category` sebagai input teks,
    # sehingga staf bisa menimpanya dengan apa saja ⇒ grouping katalog tidak bisa
    # dipercaya. Kategori sekarang MILIK MASTER: diambil dari FG/model lewat
    # `refresh-from-master`/propagasi. `category_id` boleh diubah hanya kalau
    # item BELUM tertaut ke master (item legacy manual).
    patch.pop('category', None)
    if data.category_id is not None:
        linked = item.get('fg_material_id') or item.get('material_id') or item.get('variant_id')
        if linked:
            raise HTTPException(
                400, 'Kategori item ini mengikuti Master Produk (tidak bisa diubah manual). '
                     'Ubah kategori di Master Produk — perubahannya otomatis turun ke katalog.')
        cat = await _pm.get_category(db, data.category_id)
        if not cat or cat.get('active') is False:
            raise HTTPException(400, f"category_id '{data.category_id}' tidak dikenal/non-aktif.")
        patch.update(_pm.category_patch(cat))
    else:
        patch.pop('category_id', None)
    # KEPUTUSAN #2 — normalisasi harga (kanonik + legacy sync)
    patch.update(_pricing_write_fields(data.dict()))
    if patch.get('model_id'):
        _mdl = await db.rahaza_models.find_one({'id': patch['model_id'], 'active': {'$ne': False}})
        if not _mdl:
            raise HTTPException(400, f"model_id '{patch['model_id']}' tidak valid (rahaza_models — MKT-2)")
    # Fase 3b: validasi & auto-fill dari varian produksi internal
    if patch.get('variant_id'):
        _rv = await db.rahaza_model_variants.find_one({'id': patch['variant_id'], 'active': {'$ne': False}}, {'_id': 0})
        if not _rv:
            raise HTTPException(400, f"variant_id '{patch['variant_id']}' tidak valid (rahaza_model_variants — Fase 3b)")
        patch['variant_sku'] = _rv.get('sku', '')
        patch.setdefault('model_id', _rv.get('model_id'))
        patch.setdefault('variant_info', f"Warna: {_rv.get('color_name', '')}, Size: {_rv.get('size_code', '')}")
        if not patch.get('sku'):
            patch['sku'] = _rv.get('sku', '')
    if 'sku' in patch:
        patch['sku'] = patch['sku'].strip().upper()
    if 'name' in patch:
        patch['name'] = patch['name'].strip()

    # Recompute stock_status if stock fields changed
    new_qty = patch.get('stock_quantity', item.get('stock_quantity', 0))
    new_thresh = patch.get('stock_alert_threshold', item.get('stock_alert_threshold', 10))
    patch['stock_status'] = _stock_status(float(new_qty), float(new_thresh))
    patch['updated_at'] = _now()
    patch['updated_by'] = user.get('id', '')

    await db.marketing_catalog_items.update_one({'id': item_id}, {'$set': patch})
    await _refresh_catalog_stats(db, catalog_id)
    await _log_price_change(db, item, patch, account_id=account_id, user=user, reason=reason)

    updated = await db.marketing_catalog_items.find_one({'id': item_id}, {'_id': 0})
    return {'ok': True, 'item': _s(updated)}


# 2026-11-08 — riwayat harga katalog (harga jual & harga coret). Satu-satunya jalan MENGUBAH harga item
# yang sudah ada adalah PUT di atas (harga awal saat item dibuat bukan "perubahan").
PRICE_HISTORY_FIELDS = ('harga_jual', 'harga_coret')


async def _log_price_change(db, item: dict, patch: dict, *, account_id, user: dict, reason: str) -> None:
    # 2026-11-09 — satu penulis riwayat harga (dipakai juga aksi massal & pembatalannya): core.catalog_runs
    from core import catalog_runs as _runs
    await _runs.log_price_change(db, item, patch, account_id=account_id, user=user, reason=reason)


def item_usage_checks(item_ids) -> list:
    """Daftar cek (label staf, koleksi, filter) "item katalog ini sudah dipakai di mana" — 10 Nov 2026.

    SATU daftar untuk hapus item (di bawah) dan hapus katalog (`routes.marketing_catalog_mgmt.delete_catalog`),
    supaya keduanya tidak pernah berbeda. Isinya = semua dokumen yang menyimpan `catalog_item_id` item katalog
    jual (dicari dengan grep `catalog_item_id` di backend): pesanan (baris + baris pemenuhan), produk & sesi live,
    sampel, retur, ulasan, komplain, jadwal konten, permintaan produk kreator, dan pemetaan Jembatan SKU.
    Koleksi jejak/log (riwayat harga, aksi massal, sinkron stok) bukan pemakaian.
    """
    ids = [i for i in (item_ids or []) if i]
    if not ids:
        return []
    q = {'$in': ids}
    return [
        ('pesanan', 'marketing_orders', {'$or': [{'catalog_item_id': q}, {'items.catalog_item_id': q},
                                                 {'fulfillment_items.catalog_item_id': q}]}),
        ('produk sesi live', 'marketing_live_session_products', {'catalog_item_id': q}),
        ('sesi live', 'marketing_live_sessions', {'products.catalog_item_id': q}),
        ('kiriman sampel', 'marketing_samples', {'catalog_item_id': q}),
        ('retur', 'marketing_returns', {'catalog_item_id': q}),
        ('ulasan', 'marketing_reviews', {'catalog_item_id': q}),
        ('komplain', 'marketing_complaints', {'catalog_item_id': q}),
        ('jadwal konten', 'marketing_content_calendar', {'catalog_item_id': q}),
        ('permintaan produk kreator', 'marketing_creator_item_requests', {'catalog_item_id': q}),
        ('pemetaan SKU marketplace', 'marketing_sku_bridge', {'catalog_item_id': q}),
    ]


@router.delete('/{catalog_id}/items/{item_id}')
async def delete_catalog_item(catalog_id: str, item_id: str, request: Request):
    """Hapus PERMANEN item dari katalog — hanya bila item itu belum dipakai.

    10 Nov 2026 (owner: "pastikan tabel master data bisa dihapus"): dulu item langsung dihapus tanpa cek apa pun,
    sehingga pesanan/retur/sesi live yang menunjuk item itu kehilangan tautannya. Kini bila item sudah dipakai
    (`item_usage_checks`) server menjawab 409 dengan kalimat "… sudah dipakai di 3 pesanan …" dan layar
    menawarkan Nonaktifkan = Arsipkan (`POST …/archive`, item nonaktif, riwayat tetap utuh).
    """
    user = await require_perm(request, 'toko.manage', legacy_roles=('manager_marketing', 'pic_marketing', 'staff_marketing', 'pic_toko', 'marketing_kol', 'cs_staff', 'manager', 'owner', 'admin', 'superadmin'),
                              message='Akses ditolak: Anda tidak berhak menghapus item katalog.')  # T-01 2.3
    db = get_db()

    item = await db.marketing_catalog_items.find_one({'id': item_id, 'catalog_id': catalog_id}, {'_id': 0})
    if not item:
        raise HTTPException(404, 'Item tidak ditemukan.')
    from core.hapus_master import hitung_pemakaian, tolak_bila_dipakai
    pakai = await hitung_pemakaian(db, item_usage_checks([item_id]))
    tolak_bila_dipakai('Item katalog', item.get('name') or item.get('sku') or '', pakai)

    await db.marketing_catalog_items.delete_one({'id': item_id, 'catalog_id': catalog_id})
    await _refresh_catalog_stats(db, catalog_id)
    await log_activity(user.get('id', ''), user.get('name', ''),
                       f"delete_catalog_item:{item.get('sku') or ''}", 'marketing_catalog', item_id)
    return {'ok': True, 'deleted': True, 'message': 'Item dihapus.'}


# ═══════════════════════════════════════════════════════════════════════════════
# STOCK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

