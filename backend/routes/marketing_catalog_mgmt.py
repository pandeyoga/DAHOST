"""
Marketing Catalog - Management
Catalog CRUD + dashboard + utilities
"""
import uuid
import html
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field
# F6 (sesi #10) — endpoint DAFTAR/RINGKAS wajib menyaring sendiri (middleware
# hanya menolak permintaan yang MENYEBUT toko, ia tidak tahu isi jawaban).
from core import marketing_account_scope as _scope
from database import get_db
from auth import require_auth, log_activity
from routes.shared import require_perm  # T-01 2.3
from core import catalog_stock as _cstock   # F7: SSOT satu rumus stok jual
from core import product_master as _pm      # F3–F6: SSOT kategori/HPP/harga resmi
from core import product_status as _pstatus  # status produk SKU: Stop tidak diusulkan restock
from core import catalog_tools as _tools     # 2026-11-09: status produk per SKU + item tersembunyi

router = APIRouter(prefix='/api/marketing/catalogs', tags=['Marketing-Catalog-mgmt'])

# Photo upload settings
PRODUCT_UPLOAD_ROOT = Path('/app/uploads/products')
PRODUCT_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
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
    return out

def _stock_status(qty: float, threshold: float) -> str:
    if qty <= 0:
        return 'out_of_stock'
    elif qty <= threshold:
        return 'low_stock'
    else:
        return 'in_stock'

async def _refresh_catalog_stats(db, catalog_id: str):
    # 2026-11-06 (pola P7): satu rumus di core.catalog_stock (dulu to_list(500) → katalog besar terpotong)
    await _cstock.refresh_catalog_stats(db, catalog_id)


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
    price: Optional[float] = Field(default=0, ge=0)          # selling price
    original_price: Optional[float] = Field(default=0, ge=0) # HPP / base price
    platform_price: Optional[float] = 0 # actual listed price on platform (can differ)
    stock_quantity: Optional[float] = Field(default=0, ge=0)
    stock_alert_threshold: Optional[float] = Field(default=10, ge=0)
    material_id: Optional[str] = None   # optional link to WMS material (rahaza_materials)
    platform_url: Optional[str] = ''
    images: Optional[List[str]] = []
    tags: Optional[List[str]] = []
    weight_gram: Optional[float] = Field(default=0, ge=0)
    category: Optional[str] = ''
    variant_info: Optional[str] = ''    # e.g. "Warna: Merah, Size: L"
    is_active: Optional[bool] = True


class CatalogItemUpdate(BaseModel):
    sku: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = Field(default=None, ge=0)
    original_price: Optional[float] = Field(default=None, ge=0)
    platform_price: Optional[float] = None
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


class StockUpdateBody(BaseModel):
    stock_quantity: float = Field(ge=0)
    notes: Optional[str] = ''


class CatalogItemFromFG(BaseModel):
    """Create catalog item by picking from FG master (rahaza_materials, type='fg').
    Backend auto-fills SKU/name/color/category from FG; user only sets selling price + URL.
    """
    fg_material_id: str  # UUID dari rahaza_materials
    price: float = Field(ge=0)                              # selling price (required)
    original_price: Optional[float] = Field(default=0, ge=0)       # HPP/coret price (optional)
    platform_price: Optional[float] = 0       # actual listed price
    platform_url: Optional[str] = ''
    images: Optional[List[str]] = []
    tags: Optional[List[str]] = []
    stock_alert_threshold: Optional[float] = Field(default=10, ge=0)
    description_override: Optional[str] = ''  # custom description (optional)


class BulkStockUpdate(BaseModel):
    updates: List[dict]   # [{ item_id, stock_quantity, notes }]


# ═══════════════════════════════════════════════════════════════════════════════

@router.post('')
async def create_catalog(data: CatalogCreate, request: Request):
    """Buat catalog baru untuk satu akun platform."""
    user = await require_auth(request)
    db = get_db()

    account = await db.marketing_platform_accounts.find_one({'id': data.account_id}, {'_id': 0})
    if not account:
        raise HTTPException(404, 'Akun platform tidak ditemukan.')

    # Use platform from account if not provided
    platform = data.platform or account.get('platform', '')

    doc = {
        'id': _uid(),
        'account_id': data.account_id,
        # BUG DITUTUP 2026-08-12 — dulu `account.get('name')`, padahal master toko
        # memakai field `account_name`. Akibatnya SETIAP katalog lahir dengan
        # `account_name: ''` dan layar katalog menampilkan kolom toko kosong.
        'account_name': account.get('account_name') or account.get('name') or '',
        'platform': platform,
        'name': _san(data.name, 200),
        'description': _san(data.description or '', 1000),
        'is_active': data.is_active,
        'item_count': 0,
        'total_stock': 0.0,
        'low_stock_count': 0,
        'out_of_stock_count': 0,
        'created_at': _now(),
        'updated_at': _now(),
        'created_by': user.get('id', ''),
    }
    await db.marketing_catalogs.insert_one(doc)
    return {'ok': True, 'catalog': _s(doc)}


@router.get('')
async def list_catalogs(
    request: Request,
    account_id: Optional[str] = None,
    platform: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
):
    """List semua katalog dengan filter opsional."""
    user = await require_auth(request)
    db = get_db()
    # 2026-11-02 — dulu (F14) katalog demo dibuat di sini bila koleksi kosong; seeder
    # demo tidak lagi dipanggil saat GET (data fiktif terus muncul di data go-live).

    q = await _scope.scope_filter(db, user, {})
    if account_id:
        q['account_id'] = account_id
    if platform:
        q['platform'] = platform
    if is_active is not None:
        q['is_active'] = is_active
    if search:
        q['name'] = {'$regex': search, '$options': 'i'}

    docs = await db.marketing_catalogs.find(q, {'_id': 0}).sort('created_at', -1).to_list(500)
    return {'ok': True, 'catalogs': [_s(d) for d in docs], 'total': len(docs)}


@router.get('/stock-dashboard')
async def stock_dashboard(
    request: Request,
    account_id: Optional[str] = None,
    platform: Optional[str] = None,
):
    """
    Ringkasan stok lintas semua katalog (atau filter per account/platform).
    Returns: total_items, in_stock, low_stock, out_of_stock, unlinked, catalogs summary.

    2026-11-06 (Tahap 2) — angka "Total Item" dulu berbeda antara super admin dan
    PIC karena TIGA sebab, semuanya ditutup di sini:
      1. hanya 500 item pertama yang dibaca ⇒ sekarang dihitung lewat AGREGASI
         (tanpa batas, tanpa memuat semua dokumen);
      2. yang dihitung semua item toko menurut `account_id` item (item impor sering
         tanpa/berbeda `account_id`) ⇒ sekarang ISI KATALOG yang boleh dilihat
         pemakai (lingkup PIC lewat `visible_account_ids`, sama dengan daftar katalog);
      3. status dari cache `stock_status` (kosong untuk item impor) ⇒ sekarang dari
         stok jual LIVE (K-7a, `core.catalog_stock`), seperti daftar item katalog.
    Item yang belum tertaut ke Master Produk tidak punya stok live — dihitung
    terpisah sebagai `unlinked`, tidak ditebak masuk "Tersedia".
    """
    user = await require_auth(request)
    db = get_db()

    # ── 1. katalog AKTIF yang boleh dilihat pemakai (lingkup = daftar katalog) ──
    cq: dict = {'is_active': {'$ne': False}}
    if account_id:
        cq['account_id'] = account_id
    if platform:
        cq['platform'] = platform
    cq = await _scope.scope_filter(db, user, cq)
    cat_platform: dict = {}
    async for c in db.marketing_catalogs.find(cq, {'_id': 0, 'id': 1, 'platform': 1}):
        if c.get('id'):
            cat_platform[c['id']] = c.get('platform') or 'Other'

    # ── 2. item aktif per KUNCI TAUTAN (agregasi; satu baris per kombinasi) ────
    groups: list = []
    if cat_platform:
        pipeline = [
            {'$match': {'catalog_id': {'$in': list(cat_platform)}, 'is_active': {'$ne': False}}},
            {'$group': {'_id': {k: f'${k}' for k in _DASH_GROUP_KEYS}, 'n': {'$sum': 1}}},
        ]
        async for g in db.marketing_catalog_items.aggregate(pipeline):
            groups.append(g)

    # ── 3. stok jual LIVE per kunci tautan (query konstan, bukan N+1) ───────────
    pseudo = [{'id': f'g{i}', **{k: (g.get('_id') or {}).get(k) for k in _DASH_LINK_KEYS}}
              for i, g in enumerate(groups)]
    blocked = await _cstock.blocked_location_ids(db)
    links = await _cstock.resolve_links_bulk(db, pseudo)
    mids = [v['fg_material_id'] for v in links.values() if v.get('fg_material_id')]
    smap = await _cstock.sellable_map(db, mids, blocked_locs=blocked)

    counts = {'in_stock': 0, 'low_stock': 0, 'out_of_stock': 0, 'unlinked': 0}
    platform_summary: dict = {}
    # 2026-11-08 (Standar UI/UX v2) — jumlah PER KATALOG dihitung langsung di sini (stok jual LIVE).
    # Tabel katalog dulu memakai `low_stock_count/out_of_stock_count` TERSIMPAN di `marketing_catalogs`
    # (cache yang tidak ikut diperbarui saat stok FG berubah) → "100% sehat" padahal 640 item habis.
    per_catalog: dict = {cid: {'total': 0, 'in_stock': 0, 'low_stock': 0, 'out_of_stock': 0, 'unlinked': 0}
                         for cid in cat_platform}
    low_groups: list = []          # (available, indeks grup, status)
    for i, g in enumerate(groups):
        key = g.get('_id') or {}
        n = int(g.get('n') or 0)
        lk = links.get(f'g{i}') or {}
        if lk.get('fg_material_id'):
            res = smap.get(lk['fg_material_id']) or dict(_cstock.EMPTY)
            avail = float(res.get('available') or 0)
            st = _cstock.stock_status(avail, _threshold(key.get('stock_alert_threshold')))
        else:
            avail, st = None, 'unlinked'
        counts[st] += n
        pc = per_catalog.setdefault(key.get('catalog_id'), {'total': 0, 'in_stock': 0, 'low_stock': 0,
                                                            'out_of_stock': 0, 'unlinked': 0})
        pc['total'] += n
        pc[st] += n
        p = cat_platform.get(key.get('catalog_id'), 'Other')
        ps = platform_summary.setdefault(p, {'platform': p, 'total': 0, 'in_stock': 0,
                                             'low_stock': 0, 'out_of_stock': 0, 'unlinked': 0})
        ps['total'] += n
        ps[st] += n
        if st in ('low_stock', 'out_of_stock'):
            low_groups.append((avail, i, st))
    total = sum(counts.values())

    # ── 4. daftar "perlu restock": 20 item dengan stok live terendah ────────────
    # Status produk Stop (keputusan owner 6 Nov 2026): SKU yang tidak lagi direncanakan cutting TIDAK
    # diusulkan restock. Angka stok di atas tetap jujur (ikut dihitung); alasannya dikembalikan.
    low_sku = {i: (links.get(f'g{i}') or {}).get('fg_code') or '' for _a, i, _st in low_groups}
    stopped = await _pstatus.stop_skus(db, low_sku.values())
    excluded_n, excluded_skus = 0, set()
    if stopped:
        kept = []
        for row in low_groups:
            sku = low_sku.get(row[1])
            if sku and sku in stopped:
                excluded_n += int(groups[row[1]].get('n') or 0)
                excluded_skus.add(sku)
            else:
                kept.append(row)
        low_groups = kept
    low_groups.sort(key=lambda x: x[0])
    low_items: list = []
    seen: set = set()
    for avail, i, st in low_groups:
        if len(low_items) >= 20:
            break
        key = groups[i].get('_id') or {}
        iq: dict = {'is_active': {'$ne': False}}
        for k in _DASH_GROUP_KEYS:
            iq[k] = key.get(k)              # None = kosong / tidak ada (sama di Mongo)
        need = 20 - len(low_items)
        docs = await db.marketing_catalog_items.find(iq, {'_id': 0,
            'id': 1, 'catalog_id': 1, 'stock_alert_threshold': 1, 'name': 1, 'sku': 1,
            'price': 1, 'platform': 1, 'account_id': 1}).limit(need).to_list(need)
        for d in docs:
            if d.get('id') in seen:
                continue
            seen.add(d.get('id'))
            d['platform'] = d.get('platform') or cat_platform.get(d.get('catalog_id'), 'Other')
            d['stock_status'] = st                    # status LIVE, bukan cache
            d['stock_quantity'] = avail               # stok jual live
            d['available'] = avail
            low_items.append(d)

    # Get last sync info
    sq: dict = await _scope.scope_filter(db, user, {'account_id': account_id} if account_id else {})
    if platform:
        sq['platform'] = platform
    last_sync = await db.marketing_stock_syncs.find_one(
        sq, {'_id': 0}, sort=[('synced_at', -1)]
    )

    return {
        'ok': True,
        'summary': {
            'total_items': total,
            'in_stock': counts['in_stock'],
            'low_stock': counts['low_stock'],
            'out_of_stock': counts['out_of_stock'],
            'unlinked': counts['unlinked'],
            'catalogs': len(cat_platform),
            'health_pct': round(counts['in_stock'] / total * 100, 1) if total else 0,
            'live_source': 'core.catalog_stock (K-6a/K-7a)',
        },
        'low_stock_items': [_s(i) for i in low_items],
        'restock_excluded': {'count': excluded_n, 'skus': sorted(excluded_skus)[:20],
                             'reason': _pstatus.STOP_REASON},
        'platform_breakdown': list(platform_summary.values()),
        # {catalog_id: {total, in_stock, low_stock, out_of_stock, unlinked}} — item AKTIF, stok LIVE.
        # Hanya katalog aktif yang terlihat pemakai (katalog nonaktif tidak dihitung → tabel menampilkan "—").
        'catalog_breakdown': per_catalog,
        'last_sync': _s(last_sync) if last_sync else None,
    }


# 2026-11-06 (Tahap 2) — kunci pengelompokan item untuk ringkasan stok: katalog +
# semua field yang menentukan tautan ke FG (lihat `core.catalog_stock.resolve_link`)
# + ambang stok rendah. Item dengan kunci sama PASTI punya status stok yang sama.
_DASH_LINK_KEYS = ('fg_material_id', 'material_id', 'variant_sku', 'variant_id')
_DASH_GROUP_KEYS = ('catalog_id',) + _DASH_LINK_KEYS + ('stock_alert_threshold',)


def _threshold(v) -> float:
    """Ambang stok rendah — rumus SAMA dengan `stock_live_status` di daftar item
    (`marketing_catalog_items.list_catalog_items`: kosong/0 ⇒ 10)."""
    try:
        return float(v or 10)
    except (TypeError, ValueError):
        return 10.0


# ═══════════════════════════════════════════════════════════════════════════════
# FG MASTER INTEGRATION — REGISTERED HERE (BEFORE /{catalog_id}) for route precedence
# ═══════════════════════════════════════════════════════════════════════════════

@router.get('/fg-products')
async def search_fg_products(
    request: Request,
    q: Optional[str] = Query(None, description="Search by FG code or name"),
    limit: int = Query(50, ge=1, le=200),
):
    """Search FG (Finished Goods) products dari master inventory (rahaza_materials, type='fg').
    
    Used by Catalog Item creation flow untuk pick produk dari master, bukan input manual.
    Returns: List of FG with current stock from rahaza_material_stock.
    """
    await require_auth(request)
    db = get_db()
    
    query = {'type': 'fg', '$or': [{'active': True}, {'active': {'$exists': False}}]}
    if q and q.strip():
        # 2026-11-07 (Tahap 5, audit form) — teks cari di-escape (dulu "(" → 500) dan
        # ikut mencari WARNA & UKURAN: staf mencari "Aisar hitam M", bukan kode FG.
        # Setiap kata harus cocok di salah satu kolom (nama/kode/warna/ukuran).
        words = [w for w in q.strip().split() if w][:5]
        query = {
            'type': 'fg',
            '$or': [{'active': True}, {'active': {'$exists': False}}],
            '$and': [
                {'$or': [{k: {'$regex': re.escape(w), '$options': 'i'}}
                         for k in ('name', 'code', 'color', 'size_code')]}
                for w in words
            ],
        }
    
    materials = await db.rahaza_materials.find(query, {'_id': 0}).sort('name', 1).limit(limit).to_list(length=limit)
    
    # Get default active location
    default_loc = await db.rahaza_locations.find_one({'active': True}, {'_id': 0})
    loc_id = default_loc['id'] if default_loc else None
    
    # Attach stock info
    for mat in materials:
        if loc_id:
            stock_doc = await db.rahaza_material_stock.find_one(
                {'material_id': mat.get('id'), 'location_id': loc_id}, {'_id': 0}
            )
            mat['stock_qty'] = float(stock_doc.get('qty', 0)) if stock_doc else 0.0
        else:
            mat['stock_qty'] = 0.0
        mat['location_id'] = loc_id
    
    return {'ok': True, 'data': [_s(m) for m in materials], 'total': len(materials)}


@router.get('/master-products')
async def list_master_products_for_catalog(
    request: Request,
    q: Optional[str] = Query(None, description="Cari kode/nama produk atau varian"),
    account_id: Optional[str] = Query(None, description="Tandai varian yang SUDAH ada di katalog toko ini"),
    only_sellable: bool = Query(False, description="Hanya varian yang stok jualnya > 0"),
    limit: int = Query(60, ge=1, le=1000),
    coverage: bool = False,
):
    """Master produk internal (model R&D) + varian FG-nya, siap dipilih untuk katalog toko.

    KENAPA endpoint ini ada (bukan memakai `/fg-products` yang sudah ada)
    ---------------------------------------------------------------------
    `/fg-products` mengembalikan daftar FG **datar** tanpa induk produknya, tanpa
    HPP/harga resmi master, dan stoknya dibaca dari "lokasi aktif pertama" dengan
    `qty` mentah — angka yang bukan stok jual (karantina/blokir/reservasi ikut).
    Untuk mengisi katalog **9 toko**, staf butuh melihat: produk apa, varian mana,
    HPP-nya berapa, harga resminya berapa, stok jual berapa, dan **varian mana yang
    sudah ada di katalog toko itu** — supaya tidak memilih ulang yang sudah ada.
    Semua dibaca dari SSOT (`core.product_master`, `core.catalog_stock`).

    2026-11-11 (owner: "saya tidak bisa lihat apa yang sudah ada di toko mana yang belum") — `coverage=true`
    menambahkan CAKUPAN PER TOKO untuk semua toko aktif yang boleh dilihat pemakai: tiap varian membawa
    `in_accounts` (toko yang katalognya sudah memuat varian itu, termasuk item impor lama tanpa katalog —
    aturan "sudah ada" yang sama dengan `create_item_from_fg`) dan `hidden_accounts` (yang hanya ada sebagai item
    lama). Batas model dinaikkan (layar meminta semua model; dulu 60 pertama saja). Stok jual dibaca sekaligus
    (`sellable_map`), bukan satu kueri per varian.
    """
    user = await require_auth(request)
    db = get_db()

    mq: dict = {'$or': [{'active': True}, {'active': {'$exists': False}}]}
    if q and q.strip():
        rx = {'$regex': re.escape(q.strip()), '$options': 'i'}
        mq['$and'] = [{'$or': [{'name': rx}, {'code': rx}, {'category_name': rx}]}]
    models = await db.rahaza_models.find(mq, {'_id': 0}).sort('name', 1).limit(limit).to_list(limit)

    # varian FG per model
    model_ids = [m['id'] for m in models]
    fgs = await db.rahaza_materials.find(
        {'type': 'fg', 'model_id': {'$in': model_ids},
         '$or': [{'active': True}, {'active': {'$exists': False}}]},
        {'_id': 0}).sort('code', 1).to_list(2000)

    in_catalog: set = set()
    in_hidden: set = set()
    catalog_id = None
    if account_id:
        cat = await db.marketing_catalogs.find_one(
            {'account_id': account_id}, {'_id': 0, 'id': 1})
        if cat:
            catalog_id = cat['id']
            async for it in db.marketing_catalog_items.find(
                    {'catalog_id': catalog_id}, {'_id': 0, 'fg_material_id': 1}):
                if it.get('fg_material_id'):
                    in_catalog.add(it['fg_material_id'])
        # 2026-11-09 (D7) — item impor lama TANPA katalog untuk toko ini juga dihitung "sudah ada"
        async for it in db.marketing_catalog_items.find(
                {'$and': [_tools.LIVE_HIDDEN, {'account_id': account_id}]},
                {'_id': 0, 'fg_material_id': 1, 'material_id': 1}):
            fid = it.get('fg_material_id') or it.get('material_id')
            if fid:
                in_hidden.add(fid)

    # 2026-11-09 (B1/D7) — status produk & harga resmi PER SKU ikut tampil supaya staf tidak memilih SKU Stop/Dead
    # tanpa sadar, dan tahu harga awal item yang akan dibuat.
    vstatus = await _tools.status_by_sku(db, (fg.get('code') for fg in fgs))
    model_by_id = {m['id']: m for m in models}

    # 2026-11-11 — cakupan per toko (lihat docstring)
    cov_accounts: list = []
    in_acc: dict = {}        # fg_id → {account_id} (katalog toko ATAU item lama tanpa katalog)
    hid_acc: dict = {}       # fg_id → {account_id} yang HANYA ada sebagai item lama tanpa katalog
    if coverage:
        cov_accounts, in_acc, hid_acc = await _catalog_coverage(db, user, [fg['id'] for fg in fgs])

    stock_by_fg = await _cstock.sellable_map(db, [fg['id'] for fg in fgs])
    by_model: dict = {}
    for fg in fgs:
        stock = stock_by_fg.get(fg['id']) or _cstock.EMPTY
        sellable = float(stock['available'])
        if only_sellable and sellable <= 0:
            continue
        price, price_src = _pm.official_price(fg, model_by_id.get(fg['model_id']))
        ps_code = vstatus.get(str(fg.get('code') or '').upper())
        by_model.setdefault(fg['model_id'], []).append({
            'retail_price_master': price,
            'retail_price_source': price_src,
            'product_status': ps_code,
            'product_status_label': _pstatus.label(ps_code),
            'in_catalog_hidden': fg['id'] in in_hidden,
            'fg_material_id': fg['id'],
            'code': fg.get('code') or '',
            'name': fg.get('name') or '',
            'color': fg.get('color') or '',
            'size_code': fg.get('size_code') or '',
            'unit': fg.get('unit') or 'pcs',
            'hpp': float(fg.get('hpp') or 0),
            # F14b — bahan dibawa ikut supaya layar yang memilih produk (mis.
            # Launching, Caption AI) tidak perlu menghitungnya sendiri. Kalau
            # tiap layar menghitung sendiri, suatu hari salah satunya memakai
            # aturan berbeda dan dua layar menyebut bahan berbeda untuk produk
            # yang sama.
            'composition': (fg.get('composition') or '').strip(),
            'sellable_stock': sellable,
            'onhand': float(stock['onhand']),
            'reserved': float(stock['reserved']),
            'in_catalog': fg['id'] in in_catalog or fg['id'] in in_hidden,
        })
        if coverage:
            by_model[fg['model_id']][-1].update({
                'in_accounts': sorted(in_acc.get(fg['id'], ())),
                'hidden_accounts': sorted(hid_acc.get(fg['id'], ())),
            })

    out = []
    for m in models:
        variants = by_model.get(m['id'], [])
        if only_sellable and not variants:
            continue
        master = _pm.master_display_fields(m)
        # Bahan tingkat produk = gabungan komposisi varian (unik, urut muncul).
        # Kosong kalau master memang belum mencatatnya — dikatakan apa adanya,
        # bukan ditebak (layar menampilkan "belum dicatat di master").
        _comps: list = []
        for v in variants:
            c = v.get('composition') or ''
            if c and c not in _comps:
                _comps.append(c)
        out.append({
            'model_id': m['id'],
            'code': m.get('code') or '',
            'name': m.get('name') or '',
            'category_name': master.get('category_name') or m.get('category_name') or '',
            'material': ' / '.join(_comps),
            'hpp': float(master.get('hpp') or m.get('hpp') or 0),
            'hpp_source': master.get('hpp_source') or 'none',
            'retail_price_master': float(master.get('retail_price_master')
                                         or m.get('retail_price') or 0),
            # 2026-11-09 (B1) — rentang harga resmi per SKU varian (cadangan harga model sudah termasuk)
            'retail_price_min': min([v['retail_price_master'] for v in variants if v['retail_price_master']] or [0]),
            'retail_price_max': max([v['retail_price_master'] for v in variants] or [0]),
            'priced_variant_count': sum(1 for v in variants if v['retail_price_source'] == 'sku'),
            'stop_dead_count': sum(1 for v in variants if v['product_status'] in SKIP_PRODUCT_STATUSES),
            'variant_count': len(variants),
            'in_catalog_count': sum(1 for v in variants if v['in_catalog']),
            'variants': variants,
        })

    res = {'ok': True, 'catalog_id': catalog_id,
           'products': out,
           'total_products': len(out),
           'total_variants': sum(p['variant_count'] for p in out),
           # True = masih ada model lain di luar batas `limit` (layar memberi tahu, tidak diam-diam terpotong)
           'more': len(models) >= limit}
    if coverage:
        res['accounts'] = cov_accounts
    return res


async def _catalog_coverage(db, user: dict, fg_ids: list) -> tuple:
    """Cakupan katalog per toko untuk varian `fg_ids` → ``(accounts, in_acc, hid_acc)``.

    * ``accounts`` — toko AKTIF yang boleh dilihat pemakai (`marketing_account_scope`, urut kode toko), masing-masing
      dengan ``catalog_id`` katalognya (None bila belum punya — katalog dibuat otomatis saat diisi).
    * ``in_acc[fg_id]`` — toko yang SUDAH memuat varian itu: item di katalog toko tersebut (aktif atau tidak — sama
      dengan pemeriksaan kembar `create_item_from_fg`) **atau** item impor lama tanpa katalog milik toko itu (D7).
    * ``hid_acc[fg_id]`` — toko yang memuatnya HANYA sebagai item lama tanpa katalog (layar menandai "perlu dirapikan").

    Katalog toko = katalog PERTAMA yang ditemukan untuk toko itu — sama dengan `assign_from_master`, supaya layar dan
    tombol "Tambahkan" tidak pernah berbeda pendapat tentang apa yang "sudah ada".
    """
    accounts = await _scope.visible_accounts(
        db, user, base={'status': 'active'},
        projection={'_id': 0, 'id': 1, 'account_code': 1, 'account_name': 1, 'name': 1, 'platform': 1},
        sort=[('account_code', 1)])
    acc_ids = [a['id'] for a in accounts if a.get('id')]
    cat_by_acc: dict = {}
    async for c in db.marketing_catalogs.find({'account_id': {'$in': acc_ids}}, {'_id': 0, 'id': 1, 'account_id': 1}):
        cat_by_acc.setdefault(c.get('account_id'), c.get('id'))
    acc_by_cat = {cid: aid for aid, cid in cat_by_acc.items() if cid}

    wanted = set(fg_ids or [])
    in_cat: dict = {}
    if acc_by_cat and wanted:
        async for it in db.marketing_catalog_items.find(
                {'catalog_id': {'$in': list(acc_by_cat)}, 'fg_material_id': {'$in': list(wanted)}},
                {'_id': 0, 'catalog_id': 1, 'fg_material_id': 1}):
            in_cat.setdefault(it['fg_material_id'], set()).add(acc_by_cat[it['catalog_id']])
    hidden: dict = {}
    if acc_ids and wanted:
        async for it in db.marketing_catalog_items.find(
                {'$and': [_tools.LIVE_HIDDEN, {'account_id': {'$in': acc_ids}}]},
                {'_id': 0, 'account_id': 1, 'fg_material_id': 1, 'material_id': 1}):
            # sama dengan `find_hidden_twin`: cocok lewat fg_material_id ATAU material_id
            for fid in {it.get('fg_material_id'), it.get('material_id')}:
                if fid in wanted:
                    hidden.setdefault(fid, set()).add(it['account_id'])

    in_acc = {fid: in_cat.get(fid, set()) | hidden.get(fid, set()) for fid in set(in_cat) | set(hidden)}
    hid_acc = {fid: accs - in_cat.get(fid, set()) for fid, accs in hidden.items()}
    out_accounts = [{
        'id': a['id'],
        'account_code': a.get('account_code') or '',
        'account_name': a.get('account_name') or a.get('name') or a.get('account_code') or '',
        'platform': a.get('platform') or '',
        'catalog_id': cat_by_acc.get(a['id']),
    } for a in accounts if a.get('id')]
    return out_accounts, in_acc, hid_acc


class AssignFromMasterBody(BaseModel):
    """Isi katalog BANYAK toko sekaligus dari master produk internal."""
    account_ids: List[str] = Field(min_length=1)
    fg_material_ids: List[str] = Field(min_length=1)
    # 'master'  → harga jual awal = harga resmi master (K-3a)
    # 'kosong'  → harga jual 0, staf isi per toko nanti
    price_mode: str = 'master'
    stock_alert_threshold: Optional[float] = Field(default=10, ge=0)
    catalog_name: Optional[str] = None
    # 2026-11-09 (klarifikasi D7) — SKU berstatus produk Stop/Dead DILEWATI (bawaan); True = tetap ditambahkan
    include_stop_dead: bool = False


# Status produk yang bawaannya tidak ditambahkan ke katalog lewat "Isi dari master" (D7)
SKIP_PRODUCT_STATUSES = ('stop', 'dead')


@router.post('/assign-from-master')
async def assign_from_master(data: AssignFromMasterBody, request: Request):
    """Tambahkan produk master terpilih ke katalog BEBERAPA toko dalam satu aksi.

    KENAPA ini perlu ada
    --------------------
    Jalur yang sudah ada hanya bisa menambah **satu varian ke satu katalog** per
    permintaan. Untuk 9 toko × puluhan varian, itu ratusan klik — dan yang terjadi
    di lapangan bukan "staf sabar", melainkan **katalog dibiarkan kosong**. Katalog
    kosong berarti: item pesanan hasil impor tidak bisa ditautkan ke master ⇒ HPP
    dan **marjin per pesanan tidak bisa dihitung sama sekali**. Jadi tombol ini
    bukan kenyamanan, ia prasyarat angka marjin.

    Sifatnya:
      * **Idempoten** — varian yang sudah ada di katalog toko dilaporkan
        "sudah ada", bukan digandakan (kunci `catalog_id` + `fg_material_id`).
      * **Tidak gagal total** — satu varian bermasalah (non-aktif/produk
        dihentikan) hanya menolak varian itu, dengan alasan per baris.
      * Katalog toko **dibuatkan otomatis** kalau belum ada, memakai nama toko —
        supaya staf tidak harus tahu bahwa "katalog" adalah lapisan tersendiri.
      * HPP & harga resmi **selalu** dari master (bukan diketik), lewat
        `create_item_from_fg` yang sama dengan jalur satuan.
      * 2026-11-09 (D7) — SKU berstatus produk Stop/Dead dilewati (bisa dimatikan), item tersembunyi toko
        yang sama dihitung "sudah ada", dan harga awal = harga resmi PER SKU (cadangan harga model).
    """
    # 2026-11-09 — gerbang tulis katalog yang sama dengan "Ubah item" + lingkup toko per tujuan
    from routes.marketing_catalog_items import require_catalog_writer  # lazy: hindari impor siklik
    user = await require_catalog_writer(request)
    db = get_db()

    if data.price_mode not in ('master', 'kosong'):
        raise HTTPException(400, "price_mode harus 'master' atau 'kosong'")

    accounts = await db.marketing_platform_accounts.find(
        {'id': {'$in': data.account_ids}}, {'_id': 0}).to_list(200)
    found_ids = {a['id'] for a in accounts}
    missing = [a for a in data.account_ids if a not in found_ids]
    if missing:
        raise HTTPException(404, f"{len(missing)} toko tujuan tidak ditemukan — "
                                 'muat ulang daftar toko lalu coba lagi.')
    for a in accounts:
        await _scope.assert_account_visible(db, user, a['id'])

    from routes.marketing_catalog_items import (          # lazy: hindari impor siklik
        create_item_from_fg as _create_item, _refresh_catalog_stats as _refresh_stats,
    )

    # D7 — status produk per SKU (FG code = SKU varian). Dibaca sekali untuk semua pilihan.
    stopped: dict = {}
    if not data.include_stop_dead:
        fg_codes = {f['id']: f.get('code') for f in await db.rahaza_materials.find(
            {'id': {'$in': data.fg_material_ids}}, {'_id': 0, 'id': 1, 'code': 1}).to_list(len(data.fg_material_ids))}
        st_by_sku = await _tools.status_by_sku(db, fg_codes.values())
        stopped = {fid: st_by_sku.get(str(code or '').upper()) for fid, code in fg_codes.items()
                   if st_by_sku.get(str(code or '').upper()) in SKIP_PRODUCT_STATUSES}

    results = []
    tot_created = tot_skipped = tot_rejected = tot_status = 0
    for acc in accounts:
        catalog = await db.marketing_catalogs.find_one(
            {'account_id': acc['id']}, {'_id': 0})
        catalog_created = False
        if not catalog:
            catalog = {
                'id': _uid(),
                'account_id': acc['id'],
                'account_name': acc.get('account_name') or acc.get('name') or '',
                'platform': acc.get('platform', ''),
                'name': _san(data.catalog_name
                             or f"Katalog {acc.get('account_name') or acc.get('account_code')}", 200),
                'description': 'Dibuat otomatis saat mengisi katalog dari master produk.',
                'is_active': True,
                'item_count': 0,
                'total_stock': 0.0,
                'low_stock_count': 0,
                'out_of_stock_count': 0,
                'created_at': _now(),
                'updated_at': _now(),
                'created_by': user.get('id', ''),
            }
            await db.marketing_catalogs.insert_one(dict(catalog))
            catalog.pop('_id', None)
            catalog_created = True

        created = skipped = rejected = by_status = 0
        notes = []
        for fg_id in data.fg_material_ids:
            if fg_id in stopped:
                by_status += 1
                notes.append({'fg_material_id': fg_id, 'action': 'dilewati',
                              'why': f"status produk {_pstatus.label(stopped[fg_id])} — tidak ditambahkan "
                                     "(centang 'Tetap tambahkan SKU Stop/Dead' bila memang dijual)"})
                continue
            opts = {'stock_alert_threshold': data.stock_alert_threshold, 'price_mode': data.price_mode}
            if data.price_mode == 'kosong':
                opts['harga_jual'] = 0
            doc, err = await _create_item(db, catalog, fg_id, opts, user)
            if err:
                status, msg = err
                if status == 409:
                    skipped += 1
                    notes.append({'fg_material_id': fg_id, 'action': 'sudah ada', 'why': msg})
                else:
                    rejected += 1
                    notes.append({'fg_material_id': fg_id, 'action': 'ditolak', 'why': msg})
                continue
            created += 1
            notes.append({'fg_material_id': fg_id, 'action': 'ditambahkan',
                          'sku': doc.get('sku'), 'name': doc.get('name'),
                          'hpp': doc.get('hpp'), 'harga_jual': doc.get('harga_jual'),
                          'stok_jual': doc.get('stock_quantity')})
        if created:
            await _refresh_stats(db, catalog['id'])

        tot_created += created
        tot_skipped += skipped
        tot_rejected += rejected
        tot_status += by_status
        results.append({
            'account_id': acc['id'],
            'account_code': acc.get('account_code'),
            'account_name': acc.get('account_name') or acc.get('name'),
            'catalog_id': catalog['id'],
            'catalog_name': catalog.get('name'),
            'catalog_created': catalog_created,
            'created': created, 'skipped': skipped, 'rejected': rejected,
            'skipped_status': by_status,
            'notes': notes[:200],
        })

    await log_activity(
        user.get('id', ''), user.get('name') or user.get('email', 'system'),
        'assign_from_master', 'marketing_catalog_items',
        f"Isi katalog dari master produk: {len(accounts)} toko × "
        f"{len(data.fg_material_ids)} varian ⇒ {tot_created} item baru, "
        f"{tot_skipped} sudah ada, {tot_rejected} ditolak, {tot_status} dilewati (Stop/Dead)")

    return {
        'ok': True,
        'summary': {'accounts': len(accounts), 'products': len(data.fg_material_ids),
                    'created': tot_created, 'skipped': tot_skipped,
                    'rejected': tot_rejected, 'skipped_status': tot_status},
        'results': results,
        'message': (f"{tot_created} item katalog dibuat di {len(accounts)} toko"
                    + (f", {tot_skipped} sudah ada" if tot_skipped else '')
                    + (f", {tot_rejected} ditolak" if tot_rejected else '')
                    + (f", {tot_status} dilewati karena status produk Stop/Dead" if tot_status else '')
                    + '. HPP & harga resmi (per SKU) diambil dari master produk.'),
    }


@router.post('/archive-legacy-items')
async def archive_legacy_items(request: Request):
    """Archive catalog items yang dibuat manual (tanpa fg_material_id link).
    
    Marks items as is_active=False dan tambah 'legacy_archived' tag untuk hidden filter.
    Admin only.
    """
    user = await require_auth(request)
    role = user.get('role', '')
    if role not in ['admin', 'owner', 'superadmin']:
        raise HTTPException(403, 'Hanya admin/owner yang bisa archive legacy data.')
    
    db = get_db()
    
    # Find items without fg_material_id (legacy manual entries)
    result = await db.marketing_catalog_items.update_many(
        {
            '$or': [
                {'fg_material_id': None},
                {'fg_material_id': {'$exists': False}},
            ],
            'source': {'$ne': 'from_fg'},
        },
        {
            '$set': {
                'is_active': False,
                'legacy_archived': True,
                'archived_at': _now(),
                'archived_by': user.get('id', ''),
            }
        }
    )
    
    # Refresh catalog stats for affected catalogs
    affected_catalogs = await db.marketing_catalog_items.distinct('catalog_id', {'legacy_archived': True})
    for cid in affected_catalogs:
        await _refresh_catalog_stats(db, cid)
    
    return {
        'ok': True,
        'archived_count': result.modified_count,
        'message': f'{result.modified_count} item legacy berhasil di-archive. Item baru harus pakai FG picker.',
    }


@router.get('/{catalog_id}')
async def get_catalog(catalog_id: str, request: Request):
    """Get catalog detail."""
    await require_auth(request)
    db = get_db()

    doc = await db.marketing_catalogs.find_one({'id': catalog_id}, {'_id': 0})
    if not doc:
        raise HTTPException(404, 'Katalog tidak ditemukan.')
    return {'ok': True, 'catalog': _s(doc)}


@router.put('/{catalog_id}')
async def update_catalog(catalog_id: str, data: CatalogUpdate, request: Request):
    """Update catalog info."""
    user = await require_auth(request)
    db = get_db()

    patch = {k: v for k, v in data.dict().items() if v is not None}
    if not patch:
        raise HTTPException(400, 'Tidak ada perubahan.')
    patch['updated_at'] = _now()
    patch['updated_by'] = user.get('id', '')

    res = await db.marketing_catalogs.update_one({'id': catalog_id}, {'$set': patch})
    if res.matched_count == 0:
        raise HTTPException(404, 'Katalog tidak ditemukan.')

    doc = await db.marketing_catalogs.find_one({'id': catalog_id}, {'_id': 0})
    return {'ok': True, 'catalog': _s(doc)}


@router.delete('/{catalog_id}')
async def delete_catalog(catalog_id: str, request: Request):
    """Hapus PERMANEN katalog beserta item-nya — hanya bila belum ada satu item pun yang dipakai.

    10 Nov 2026: dulu katalog + SEMUA itemnya langsung dihapus tanpa cek apa pun (pesanan, retur, sesi live yang
    menunjuk item itu kehilangan tautannya). Kini item katalog dicek dengan daftar yang sama dengan hapus item
    (`routes.marketing_catalog_items.item_usage_checks`); bila ada yang dipakai → 409 dan layar menawarkan
    Nonaktifkan katalog (`PUT /{id}` `is_active: false`).
    """
    user = await require_perm(request, 'toko.manage', legacy_roles=('manager_marketing', 'pic_marketing', 'staff_marketing', 'pic_toko', 'marketing_kol', 'cs_staff', 'manager', 'owner', 'admin', 'superadmin'),
                              message='Akses ditolak: Anda tidak berhak menghapus katalog.')  # T-01 2.3
    db = get_db()

    cat = await db.marketing_catalogs.find_one({'id': catalog_id}, {'_id': 0, 'name': 1})
    if not cat:
        raise HTTPException(404, 'Katalog tidak ditemukan.')

    from core.hapus_master import hitung_pemakaian, tolak_bila_dipakai
    from routes.marketing_catalog_items import item_usage_checks
    item_ids = [d.get('id') async for d in db.marketing_catalog_items.find(
        {'catalog_id': catalog_id}, {'_id': 0, 'id': 1})]
    pakai = await hitung_pemakaian(db, item_usage_checks(item_ids))
    tolak_bila_dipakai('Katalog', cat.get('name') or '', pakai)

    item_count = len(item_ids)
    await db.marketing_catalog_items.delete_many({'catalog_id': catalog_id})
    await db.marketing_catalogs.delete_one({'id': catalog_id})
    await log_activity(user.get('id', ''), user.get('name', ''),
                       f"delete_catalog:{cat.get('name') or ''}", 'marketing_catalog', catalog_id)

    return {'ok': True, 'deleted': True, 'message': f"Katalog '{cat['name']}' dan {item_count} item dihapus."}
