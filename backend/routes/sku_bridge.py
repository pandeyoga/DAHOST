"""routes/sku_bridge.py — **Jembatan SKU** Marketing ⇄ Gudang (Sesi #20).

Semua aturannya ada di :mod:`core.sku_bridge`. Berkas ini hanya pintu HTTP-nya,
supaya satu pemetaan identitas barang tidak pernah punya dua kamus.

Endpoint (prefix ``/api/sku-bridge``):
  GET    /health                 — KPI kesehatan tautan marketing↔gudang
  GET    /unmapped               — SKU platform yang belum dikenal master
  GET    /suggest                — usulan sasaran + keyakinan (tidak menebak)
  GET    /targets                — cari sasaran (item katalog / varian) manual
  GET    /mappings               — daftar pemetaan yang sudah ada
  POST   /map                    — petakan 1 SKU → master (+ backfill pesanan)
  POST   /auto-map               — pemetaan massal (pratinjau dulu; `apply=true` utk menulis)
  POST   /relink                 — terapkan ulang seluruh pemetaan ke pesanan
  DELETE /mappings/{psid}        — lepas pemetaan
  GET    /usulan                 — 14 Nov 2026: usulan varian (pasti / AI / tidak bisa) per kombinasi SKU + variasi
  POST   /usulan/setujui         — setujui satu usulan (satu klik → semua pesanan kombinasi itu tertaut)
  POST   /usulan/setujui-pasti   — setujui semua usulan pasti sekaligus
  POST   /usulan/ai              — minta Asisten AI mengusulkan varian (≤ 20 kombinasi per permintaan)

14 Nov 2026 (owner: varian/master produk dibuat R&D): **Buat varian / Buat master** (`/create-master`, serta aksi
`create_variant`/`create_master` di `/bulk-resolve`) hanya untuk yang dicentang "Tambah" pada Master Produk (Model &
Varian) atau Master Produk RnD; peran super selalu boleh. Menautkan ke varian yang SUDAH ada tetap untuk semua yang
berhak membuka Jembatan SKU. Layar membaca haknya dari `/health` (`boleh_buat_master`) — aturan yang sama.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import log_activity, require_auth, serialize_doc
from core import sku_bridge as bridge
from core import sku_usulan as usulan
from database import get_db
from core.authz import only  # T-01 2.3
from core.roles import MARKETING_ROLES, WAREHOUSE_ROLES  # T-01 2.3
from routes.shared import has_perm

router = APIRouter(prefix='/api/sku-bridge', tags=['sku-bridge'])

# 14 Nov 2026 — membuat varian/master produk = pekerjaan R&D: centang "Tambah" salah satu modul master produk.
CENTANG_BUAT_MASTER = ('mod.prod_master_product.create', 'mod.rnd_master_product.create')
AKSI_BUAT_MASTER = frozenset({'create_variant', 'create_master'})
PESAN_BUAT_MASTER = 'Varian baru dibuat R&D di Master Produk. Minta R&D membuatnya, lalu tautkan di sini.'


def boleh_buat_master(user: dict) -> bool:
    """Boleh membuat varian/master dari Jembatan SKU? Peran super, izin "*", atau centang Tambah master produk."""
    return has_perm(user or {}, *CENTANG_BUAT_MASTER)


def wajib_boleh_buat_master(user: dict) -> None:
    if not boleh_buat_master(user):
        raise HTTPException(403, PESAN_BUAT_MASTER)


class MapIn(BaseModel):
    platform_sku_id: str = Field(..., description='SKU milik platform (angka, apa adanya)')
    catalog_item_id: Optional[str] = Field(None, description='Sasaran: item katalog jual')
    variant_id: Optional[str] = Field(None, description='Sasaran: varian model internal')
    fg_material_id: Optional[str] = Field(None, description='Sasaran: master FG langsung')
    account_id: Optional[str] = Field(None, description='Toko (wajib bila sasaran varian)')
    product_name: str = ''
    variation: str = ''
    confidence: Optional[float] = None


class AutoMapIn(BaseModel):
    min_confidence: float = Field(default=bridge.AUTO_MIN_CONFIDENCE, ge=0.5, le=1.0)
    limit: int = Field(default=100, ge=1, le=500)
    account_id: Optional[str] = None
    apply: bool = Field(default=False, description='False = pratinjau (tidak menulis apa pun)')


@router.get('/health')
async def bridge_health(account_id: Optional[str] = None, user: dict = Depends(require_auth)):
    """KPI kesehatan tautan — angka yang menjawab "apakah gudang bisa bekerja?".

    `boleh_buat_master`: hak pemakai ini memakai tombol Buat varian / Buat master (:func:`boleh_buat_master`)."""
    db = get_db()
    res = await bridge.health(db, account_id=account_id)
    return {**res, 'boleh_buat_master': boleh_buat_master(user)}


@router.get('/unmapped')
async def unmapped(account_id: Optional[str] = None, q: Optional[str] = None,
                   limit: int = Query(default=300, ge=1, le=1000),
                   with_suggestion: bool = Query(default=False),
                   user: dict = Depends(require_auth)):
    """SKU platform yang dipesan pembeli tetapi belum dikenal master gudang.

    `with_suggestion=true` menyertakan usulan terbaik per SKU (1 kali hitung pool,
    jadi tetap murah untuk ratusan baris).
    """
    db = get_db()
    res = await bridge.list_unmapped(db, account_id=account_id, q=q, limit=limit)
    if with_suggestion and res['rows']:
        pool = await bridge._candidate_pool(db, account_id=None)
        models = await bridge._model_pool(db)
        kpool = await bridge.kode_pool(db)
        for r in res['rows']:
            sg = await bridge.suggest(db, product_name=r['product_name'],
                                     variation=r['variation'],
                                     account_id=r.get('account_id'), limit=1,
                                     pool=pool, models=models,
                                     seller_sku=r.get('seller_sku') or '', kpool=kpool)
            best = sg.get('best')
            mm = sg.get('model_match') or {}
            r['parsed'] = sg.get('parsed')
            r['recommended_action'] = sg.get('recommended_action')
            r['action_reason'] = sg.get('reason')
            r['model_match'] = mm or None
            r['suggestion'] = ({'target_id': best['target_id'], 'kind': best['kind'],
                                'label': best['label'], 'sku': best.get('sku') or '',
                                'confidence': best['confidence'], 'reasons': best['reasons'],
                                # 11 Nov 2026 — hanya model yang dipastikan SKU penjual
                                'auto_ok': (sg.get('recommended_action') == 'map'
                                            and mm.get('source') == bridge.SUMBER_KODE
                                            and bridge._f(mm.get('match_confidence'))
                                            >= bridge.AUTO_MIN_CONFIDENCE)}
                               if best else None)
    return res


@router.get('/suggest')
async def suggest_targets(platform_sku_id: Optional[str] = None,
                          product_name: str = '', variation: str = '',
                          account_id: Optional[str] = None,
                          seller_sku: str = '',
                          limit: int = Query(default=8, ge=1, le=50),
                          user: dict = Depends(require_auth)):
    """Usulan sasaran untuk satu SKU. Daftar kosong = masternya belum ada."""
    db = get_db()
    if platform_sku_id and not (product_name or variation):
        o = await db[bridge.ORDERS].find_one(
            {'items.platform_sku_id': str(platform_sku_id).strip()},
            {'_id': 0, 'items': 1, 'account_id': 1})
        if o:
            account_id = account_id or o.get('account_id')
            for ln in (o.get('items') or []):
                if str(ln.get('platform_sku_id') or '') == str(platform_sku_id).strip():
                    product_name = ln.get('product_name_raw') or ln.get('product_name') or ''
                    variation = ln.get('variation_raw') or ''
                    seller_sku = seller_sku or str(ln.get('seller_sku') or '')
                    break
    if not (product_name or variation):
        raise HTTPException(400, 'Butuh product_name/variation, atau platform_sku_id yang ada di pesanan.')
    res = await bridge.suggest(db, product_name=product_name, variation=variation,
                              account_id=account_id, limit=limit, seller_sku=seller_sku)
    res['product_name'] = product_name
    res['variation'] = variation
    return res


@router.get('/targets')
async def search_targets(q: str = '', account_id: Optional[str] = None,
                         limit: int = Query(default=40, ge=1, le=200),
                         user: dict = Depends(require_auth)):
    """Cari sasaran pemetaan secara manual (item katalog + varian model)."""
    db = get_db()
    return await bridge.search_targets(db, q=q, account_id=account_id, limit=limit)


class BulkResolveIn(BaseModel):
    actions: list = Field(default=['map', 'create_variant'],
                          description="Pilihan: 'map' (tautkan varian yang sudah ada), "
                                      "'create_variant' (buat varian di model yang cocok), "
                                      "'create_master' (buat model BARU)")
    limit: int = Field(default=200, ge=1, le=1000)
    account_id: Optional[str] = None
    apply: bool = Field(default=False, description='False = pratinjau, tidak menulis apa pun')


@router.post('/bulk-resolve')
async def bulk_resolve(body: BulkResolveIn, user: dict = Depends(require_auth)):
    """Selesaikan banyak SKU sekaligus mengikuti aksi yang disarankan mesin.

    Bawaan **pratinjau** dan hanya aksi yang aman (`map` + `create_variant`).
    `create_master` harus dipilih sadar karena ia menambah master produk baru. `create_variant`/`create_master`
    (pratinjau maupun terapkan) hanya untuk yang boleh membuat master (:func:`boleh_buat_master`).
    """
    if AKSI_BUAT_MASTER & set(body.actions or ()):
        wajib_boleh_buat_master(user)
    db = get_db()
    res = await bridge.bulk_resolve(db, actions=tuple(body.actions or ()), limit=body.limit,
                                   account_id=body.account_id, user=user,
                                   dry_run=not body.apply)
    if body.apply:
        await log_activity(user.get('id', ''), user.get('name', ''),
                          f"Jembatan SKU massal: {res['applied_count']} SKU diselesaikan "
                          f"({res['created_models']} model + {res['created_variants']} varian baru, "
                          f"{res['orders_updated']} pesanan tertaut)", 'sku-bridge', '')
    return res


@router.get('/mappings')
async def list_mappings(q: Optional[str] = None,
                        limit: int = Query(default=300, ge=1, le=1000),
                        user: dict = Depends(require_auth)):
    db = get_db()
    res = await bridge.list_mappings(db, q=q, limit=limit)
    res['rows'] = [serialize_doc(r) for r in res['rows']]
    return res


@router.post('/map')
async def map_sku(body: MapIn, user: dict = Depends(require_auth)):
    """Petakan satu SKU platform ke master, lalu tautkan SEMUA pesanannya."""
    db = get_db()
    if not (body.catalog_item_id or body.variant_id or body.fg_material_id):
        raise HTTPException(400, 'Pilih sasaran: catalog_item_id, variant_id, atau fg_material_id.')
    psid = str(body.platform_sku_id or '').strip()
    lama = await db[bridge.BRIDGE].find_one({'platform_sku_id': psid}, {'_id': 0, 'catalog_item_id': 1})
    res = await bridge.apply_mapping(
        db, body.platform_sku_id, catalog_item_id=body.catalog_item_id,
        variant_id=body.variant_id, fg_material_id=body.fg_material_id,
        account_id=body.account_id, user=user, method='manual',
        confidence=body.confidence, product_name=body.product_name,
        variation=body.variation)
    if not res.get('ok'):
        raise HTTPException(res.get('status', 400), res.get('message', 'Pemetaan gagal.'))
    # 10 Nov 2026 — "Ganti barang gudang" (Ubah di tab Sudah dipetakan): SKU yang pindah ke item katalog lain
    # dilepas dari item LAMA-nya (jejak warisan `platform_sku_ids`/`bridge_keys`), sama seperti saat dilepas.
    old_item = (lama or {}).get('catalog_item_id')
    if old_item and old_item != (res.get('target') or {}).get('id'):
        await db.marketing_catalog_items.update_one(
            {'id': old_item}, {'$pull': {'platform_sku_ids': psid, 'bridge_keys': psid}})
    await log_activity(user.get('id', ''), user.get('name', ''),
                       f"Jembatan SKU: {body.platform_sku_id} → {res['target'].get('name')} "
                       f"({res['orders_updated']} pesanan tertaut)",
                       'sku-bridge', body.platform_sku_id)
    res['bridge'] = serialize_doc(res.get('bridge') or {})
    return res


@router.post('/auto-map')
async def auto_map(body: AutoMapIn, user: dict = Depends(require_auth)):
    """Pemetaan massal untuk yang keyakinannya tinggi. Bawaan = PRATINJAU."""
    db = get_db()
    res = await bridge.auto_map(db, min_confidence=body.min_confidence, limit=body.limit,
                               account_id=body.account_id, user=user,
                               dry_run=not body.apply)
    if body.apply:
        await log_activity(user.get('id', ''), user.get('name', ''),
                          f"Jembatan SKU otomatis: {res['applied_count']} SKU dipetakan "
                          f"(ambang {res['min_confidence']})", 'sku-bridge', '')
    return res


@router.post('/relink')
async def relink(platform_sku_id: Optional[str] = None, user: dict = Depends(require_auth)):
    """Terapkan ulang pemetaan ke pesanan (pemulihan; idempoten)."""
    db = get_db()
    return await bridge.relink_orders(db, platform_sku_id=platform_sku_id)


class CreateMasterIn(BaseModel):
    platform_sku_id: str
    product_name: str = ''
    variation: str = ''
    account_id: Optional[str] = None
    model_id: Optional[str] = Field(None, description='Pakai model yang SUDAH ada (opsional)')
    model_name: Optional[str] = Field(None, description='Timpa nama model yang diusulkan')
    category_text: Optional[str] = None
    color_name: Optional[str] = None
    size_code: Optional[str] = None
    retail_price: float = 0
    hpp: float = 0
    apply: bool = Field(default=False, description='False = pratinjau rencana, tidak menulis')


@router.post('/create-master')
async def create_master(body: CreateMasterIn, user: dict = Depends(require_auth)):
    """Buat master dari SKU platform yang belum dikenal, lalu tautkan.

    Ini jalan keluar untuk barang yang memang **belum pernah ada** di master
    (mesin usulan jujur mengembalikan daftar kosong untuk kasus itu). Rantainya:
    model → varian (warna×ukuran) → master FG → item katalog toko → pemetaan SKU
    → seluruh pesanan lama ikut tertaut.

    Bawaan **pratinjau**: kirim `apply: true` untuk benar-benar membuat. Pratinjau pun hanya untuk yang boleh
    membuat master (:func:`boleh_buat_master`); yang lain menautkan ke varian yang sudah dibuat R&D.
    """
    wajib_boleh_buat_master(user)
    db = get_db()
    res = await bridge.create_master_and_map(
        db, body.platform_sku_id, product_name=body.product_name, variation=body.variation,
        account_id=body.account_id, model_id=body.model_id, model_name=body.model_name,
        category_text=body.category_text, color_name=body.color_name,
        size_code=body.size_code, retail_price=body.retail_price, hpp=body.hpp,
        user=user, dry_run=not body.apply)
    if not res.get('ok'):
        raise HTTPException(res.get('status', 400), res.get('message', 'Gagal membuat master.'))
    if body.apply:
        await log_activity(user.get('id', ''), user.get('name', ''),
                          f"Jembatan SKU: master dibuat dari {body.platform_sku_id} "
                          f"→ {res.get('variant', {}).get('sku', '')}",
                          'sku-bridge', body.platform_sku_id)
        res['bridge'] = serialize_doc(res.get('bridge') or {})
    return res


@router.delete('/mappings/{platform_sku_id}', dependencies=only(*WAREHOUSE_ROLES, *MARKETING_ROLES, perm="mod.wh_sku_bridge.delete"))  # T-01 2.3
async def unmap(platform_sku_id: str, user: dict = Depends(require_auth)):
    db = get_db()
    res = await bridge.remove_mapping(db, platform_sku_id, user=user)
    if not res.get('ok'):
        raise HTTPException(res.get('status', 400), res.get('message', 'Gagal melepas pemetaan.'))
    await log_activity(user.get('id', ''), user.get('name', ''),
                       f'Jembatan SKU dilepas: {platform_sku_id}', 'sku-bridge', platform_sku_id)
    return res


# ══════════════════════════════════════════════════════════════════════════════
# 14 Nov 2026 — USULAN AI: varian master untuk baris yang belum tertaut / baru tertaut model
# ══════════════════════════════════════════════════════════════════════════════
@router.get('/usulan')
async def daftar_usulan(account_id: Optional[str] = None, q: Optional[str] = None, jenis: Optional[str] = None,
                        limit: int = Query(default=300, ge=1, le=1000), user: dict = Depends(require_auth)):
    """Kombinasi SKU + variasi yang belum tertaut varian, dengan usulan (pasti / AI) atau saran tindakan."""
    db = get_db()
    res = await usulan.daftar(db, account_id=account_id, q=q or '', jenis=jenis or '', limit=limit)
    res['rows'] = [serialize_doc(r) for r in res['rows']]
    res['ai'] = await usulan.status_ai(db, user)
    return res


class UsulanSetujuiIn(BaseModel):
    kunci: str = Field(..., description='Kunci jembatan kombinasi (SKU platform atau kunci nama+variasi)')
    variant_id: str
    sumber: str = Field(default='pasti', description="pasti | ai | manual")
    keyakinan: Optional[float] = None
    product_name: str = ''
    variation: str = ''
    account_id: Optional[str] = None


@router.post('/usulan/setujui')
async def setujui_usulan(body: UsulanSetujuiIn, user: dict = Depends(require_auth)):
    """Setujui satu usulan → tautkan lewat jalur resmi jembatan (semua pesanan kombinasi itu ikut)."""
    db = get_db()
    metode = {'pasti': usulan.METODE_PASTI, 'ai': usulan.METODE_AI}.get(body.sumber, 'manual')
    try:
        res = await usulan.setujui(db, kunci=body.kunci, variant_id=body.variant_id, user=user, metode=metode,
                                   keyakinan=body.keyakinan, product_name=body.product_name,
                                   variation=body.variation, account_id=body.account_id)
    except usulan.GalatUsulan as e:
        raise HTTPException(e.status, e.pesan) from None
    await log_activity(user.get('id', ''), user.get('name', ''),
                       f"Jembatan SKU (usulan {body.sumber}): {body.kunci} → {res['target'].get('name')} "
                       f"({res['orders_updated']} pesanan tertaut)", 'sku-bridge', body.kunci)
    res['bridge'] = serialize_doc(res.get('bridge') or {})
    return res


class UsulanPastiIn(BaseModel):
    account_id: Optional[str] = None
    kunci: list = Field(default_factory=list, description='Kosong = semua usulan pasti')


@router.post('/usulan/setujui-pasti')
async def setujui_usulan_pasti(body: UsulanPastiIn, user: dict = Depends(require_auth)):
    """Setujui semua usulan pasti (atau yang dipilih) sekaligus."""
    db = get_db()
    res = await usulan.setujui_pasti(db, user=user, account_id=body.account_id, kunci=list(body.kunci or []))
    await log_activity(user.get('id', ''), user.get('name', ''),
                       f"Jembatan SKU: {res['disetujui']} usulan pasti disetujui ({res['orders_updated']} pembaruan "
                       "pesanan)", 'sku-bridge', '')
    return res


class UsulanAiIn(BaseModel):
    account_id: Optional[str] = None
    kunci: list = Field(default_factory=list, description='Kosong = kombinasi yang belum pernah dijawab AI')
    maks: int = Field(default=usulan.MAKS_AI, ge=1, le=usulan.MAKS_AI)


@router.post('/usulan/ai')
async def minta_usulan_ai(body: UsulanAiIn, user: dict = Depends(require_auth)):
    """Minta Asisten AI mengusulkan varian (hanya usulan; penautan tetap lewat persetujuan staf)."""
    db = get_db()
    try:
        return await usulan.minta_ai(db, user, account_id=body.account_id, kunci=list(body.kunci or []),
                                     maks=body.maks)
    except usulan.GalatUsulan as e:
        raise HTTPException(e.status, e.pesan) from None
