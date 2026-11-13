"""
Master Produk — HARGA JUAL RESMI PER SKU (klarifikasi owner 9 Nov 2026 §B2).

Harga resmi per SKU disimpan di master barang jadi (`rahaza_materials(type fg).retail_price_master`). Sebelum ini
TIDAK ADA layar untuk mengubahnya — hanya impor berkas "Isi kekurangan master" (sheet HARGA_JUAL_SKU). Layar baru
menampilkan tabel per model dengan isian per SKU (+ "isi sama untuk semua ukuran/warna").

  GET  /api/rahaza/sku-prices            daftar model → SKU (warna, ukuran, status produk, harga resmi)
  POST /api/rahaza/sku-prices            simpan banyak harga sekaligus (riwayat per SKU tercatat)
  GET  /api/rahaza/sku-prices/history    riwayat perubahan harga resmi per SKU

Hak ubah = peran yang sudah boleh mengubah master produk & harga model (`PUT /api/rahaza/models/{id}`): staf
internal, kecuali peran eksternal (vendor/klien) dan peran portal marketing (pic_toko, marketing_kol, cs_staff).
Mengubah harga resmi TIDAK mengubah harga jual toko — hanya kolom pembanding "harga resmi master" di item
katalog. Harga toko diisi lewat Manajemen katalog › "Isi harga dari master".
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import log_activity, require_auth
from core import product_master as pm
from core import product_status as ps
from core.authz import EXTERNAL_ROLES, MARKETING_PORTAL_ROLES
from database import get_db

router = APIRouter(prefix='/api/rahaza', tags=['rahaza-sku-prices'])

HISTORY = 'rahaza_sku_price_history'
MAX_CHANGES = 3000


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _require_master_writer(request: Request) -> dict:
    """Sama dengan penjaga master produk (`rahaza_production._require_admin`) + peran portal marketing ditolak
    (router master produk dipasang dengan `_DENY_MKT` di server.py)."""
    user = await require_auth(request)
    from routes.shared import lolos_centang
    if lolos_centang(user):  # 14 Nov 2026 (tahap 2): centang owner dihormati
        return user
    role = (user.get('role') or '').lower()
    if role in EXTERNAL_ROLES or role in MARKETING_PORTAL_ROLES:
        raise HTTPException(403, 'Harga jual resmi per SKU hanya bisa diubah staf internal yang mengelola master '
                                 'produk.')
    return user


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


@router.get('/sku-prices')
async def list_sku_prices(
    request: Request,
    q: Optional[str] = None,
    harga: Optional[str] = Query(None, description="kosong = belum berharga · terisi = sudah berharga"),
    product_status: Optional[str] = None,
    model_id: Optional[str] = None,
):
    """Model → SKU (barang jadi aktif) dengan harga resmi per SKU, harga model (cadangan), dan status produk."""
    await require_auth(request)
    db = get_db()
    mq = pm.live_model_filter({'id': model_id} if model_id else None)
    models = await db.rahaza_models.find(mq, {'_id': 0, 'id': 1, 'code': 1, 'name': 1, 'category_name': 1,
                                              'category': 1, 'retail_price': 1}).sort('code', 1).to_list(2000)
    mids = [m['id'] for m in models]
    fgs = await db.rahaza_materials.find(
        {'type': 'fg', 'model_id': {'$in': mids}, 'active': {'$ne': False}},
        {'_id': 0, 'id': 1, 'code': 1, 'model_id': 1, 'color': 1, 'color_name': 1, 'color_code': 1, 'size_code': 1,
         'retail_price_master': 1, 'hpp': 1, 'variant_id': 1, 'retail_price_updated_at': 1,
         'retail_price_updated_by': 1}).to_list(30000) if mids else []
    sizes = {s.get('code'): (s.get('order_seq') if s.get('order_seq') is not None else 999)
             for s in await db.rahaza_sizes.find({}, {'_id': 0, 'code': 1, 'order_seq': 1}).to_list(500)}
    st_rows = await db.rahaza_model_variants.find(
        {'sku': {'$in': [f.get('code') for f in fgs if f.get('code')]}},
        {'_id': 0, 'sku': 1, 'active': 1, ps.FIELD: 1}).to_list(60000) if fgs else []
    st_by_sku: dict = {}
    for v in st_rows:
        if v.get('sku') not in st_by_sku or v.get('active') is not False:
            st_by_sku[v.get('sku')] = v.get(ps.FIELD) or None
    try:
        want_ps = ps.filter_query(product_status).get(ps.FIELD, {}).get('$in') if product_status else None
    except ps.ProductStatusError as e:
        raise HTTPException(400, str(e))
    want_harga = (harga or '').strip().lower()
    if want_harga not in ('', 'kosong', 'terisi'):
        raise HTTPException(400, "Penyaring harga harus 'kosong' atau 'terisi'.")
    term = (q or '').strip().lower()

    by_model: dict = {}
    for f in fgs:
        price = _f(f.get('retail_price_master'))
        st = st_by_sku.get(f.get('code'))
        if want_ps is not None and st not in want_ps and not (st is None and '' in want_ps):
            continue
        if want_harga == 'kosong' and price > 0:
            continue
        if want_harga == 'terisi' and price <= 0:
            continue
        by_model.setdefault(f['model_id'], []).append({
            'fg_id': f['id'], 'sku': f.get('code') or '', 'color': f.get('color_name') or f.get('color') or '',
            'color_code': f.get('color_code') or '', 'size_code': f.get('size_code') or '',
            'retail_price_master': price, 'hpp': _f(f.get('hpp')),
            'product_status': st, 'product_status_label': ps.label(st),
            'updated_at': f.get('retail_price_updated_at').isoformat()
            if isinstance(f.get('retail_price_updated_at'), datetime) else f.get('retail_price_updated_at'),
            'updated_by': f.get('retail_price_updated_by') or '',
        })
    out = []
    totals = {'models': 0, 'skus': 0, 'priced': 0, 'empty': 0}
    for m in models:
        rows = by_model.get(m['id']) or []
        if term and term not in f"{m.get('code', '')} {m.get('name', '')}".lower():
            rows = [r for r in rows if term in r['sku'].lower()]
        if not rows:
            continue
        rows.sort(key=lambda r: (r['color'].lower(), sizes.get(r['size_code'], 999), r['size_code']))
        prices = [r['retail_price_master'] for r in rows if r['retail_price_master'] > 0]
        priced = len(prices)
        out.append({
            'model_id': m['id'], 'code': m.get('code') or '', 'name': m.get('name') or '',
            'category_name': m.get('category_name') or m.get('category') or '',
            'model_retail_price': _f(m.get('retail_price')),
            'sku_count': len(rows), 'priced_count': priced,
            'price_min': min(prices) if prices else 0.0, 'price_max': max(prices) if prices else 0.0,
            'variants': rows,
        })
        totals['models'] += 1
        totals['skus'] += len(rows)
        totals['priced'] += priced
        totals['empty'] += len(rows) - priced
    return {'ok': True, 'models': out, 'totals': totals,
            'status_options': [{'value': c, 'label': ps.LABELS[c]} for c in ps.CODES]
            + [{'value': ps.UNSET_FILTER, 'label': ps.UNSET_LABEL}]}


class SkuPriceChange(BaseModel):
    fg_id: str
    harga: float = Field(ge=0)       # 0 = kosongkan (katalog memakai harga model sebagai cadangan)


class SkuPriceSaveBody(BaseModel):
    changes: List[SkuPriceChange] = Field(min_length=1)
    reason: Optional[str] = Field(default='', max_length=300)


@router.post('/sku-prices')
async def save_sku_prices(data: SkuPriceSaveBody, request: Request):
    """Simpan harga resmi banyak SKU sekaligus. Hanya yang berubah yang ditulis + riwayatnya."""
    user = await _require_master_writer(request)
    db = get_db()
    if len(data.changes) > MAX_CHANGES:
        raise HTTPException(400, f'Paling banyak {MAX_CHANGES} SKU sekali simpan.')
    wanted = {c.fg_id: round(float(c.harga), 2) for c in data.changes}
    fgs = {f['id']: f for f in await db.rahaza_materials.find(
        {'id': {'$in': list(wanted)}, 'type': 'fg'},
        {'_id': 0, 'id': 1, 'code': 1, 'model_id': 1, 'retail_price_master': 1}).to_list(len(wanted))}
    unknown = [fid for fid in wanted if fid not in fgs]
    if unknown:
        raise HTTPException(400, f'{len(unknown)} SKU tidak ditemukan di master barang jadi — muat ulang layar.')
    models = {m['id']: m for m in await db.rahaza_models.find(
        {'id': {'$in': sorted({f.get('model_id') for f in fgs.values() if f.get('model_id')})}},
        {'_id': 0, 'id': 1, 'retail_price': 1}).to_list(len(fgs))}
    now = _now()
    who = user.get('name') or user.get('email') or user.get('id', '')
    reason = (data.reason or '').strip()
    changed, unchanged, items = [], 0, 0
    for fid, harga in wanted.items():
        fg = fgs[fid]
        old = round(_f(fg.get('retail_price_master')), 2)
        if abs(old - harga) < 0.005:
            unchanged += 1
            continue
        await db.rahaza_materials.update_one({'id': fid}, {'$set': {
            'retail_price_master': harga, 'retail_price_updated_at': now, 'retail_price_updated_by': who,
            'updated_at': now}})
        await db[HISTORY].insert_one({
            'id': str(uuid.uuid4()), 'fg_id': fid, 'sku': fg.get('code') or '', 'model_id': fg.get('model_id'),
            'before': old, 'after': harga, 'reason': reason[:300], 'source': 'layar_harga_sku',
            'actor_id': user.get('id', ''), 'actor_name': who, 'at': now})
        # kolom pembanding di item katalog ikut (harga jual toko TIDAK disentuh)
        price, src = pm.official_price({'retail_price_master': harga}, models.get(fg.get('model_id')))
        res = await db.marketing_catalog_items.update_many(
            {'$or': [{'fg_material_id': fid}, {'material_id': fid}]},
            {'$set': {'retail_price_master': price, 'retail_price_source': src}})
        items += getattr(res, 'modified_count', 0) or 0
        changed.append({'sku': fg.get('code'), 'before': old, 'after': harga})
    if changed:
        await log_activity(user.get('id', ''), who, 'update', 'rahaza.sku_price',
                           f'Harga jual resmi per SKU diubah: {len(changed)} SKU'
                           + (f' — {reason}' if reason else ''))
    return {'ok': True, 'changed': len(changed), 'unchanged': unchanged, 'catalog_items_updated': items,
            'changes': changed[:100],
            'message': (f'{len(changed)} harga SKU disimpan' + (f' · {unchanged} tidak berubah' if unchanged else '')
                        + '. Harga jual toko tidak berubah — pakai "Isi harga dari master" di Manajemen katalog.')
            if changed else 'Tidak ada harga yang berubah.'}


@router.get('/sku-prices/history')
async def sku_price_history(request: Request, model_id: Optional[str] = None, sku: Optional[str] = None,
                            limit: int = Query(50, ge=1, le=200)):
    await require_auth(request)
    db = get_db()
    q: dict = {}
    if model_id:
        q['model_id'] = model_id
    if sku:
        q['sku'] = sku.strip().upper()
    rows = await db[HISTORY].find(q, {'_id': 0}).sort('at', -1).limit(limit).to_list(limit)
    for r in rows:
        if isinstance(r.get('at'), datetime):
            r['at'] = r['at'].isoformat()
    return {'ok': True, 'history': rows}
