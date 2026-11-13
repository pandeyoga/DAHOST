"""
Marketing Catalog — AKSI CEPAT (klarifikasi owner 9 Nov 2026 §B & §D).

Prefix sendiri (`/api/marketing/catalog-tools`) supaya tidak tertutup rute `/api/marketing/catalogs/{catalog_id}`.
Logika ada di `core.catalog_tools` + `core.catalog_runs`; berkas ini hanya gerbang izin, lingkup toko, dan bentuk
jawaban. Semua aksi yang menulis: **pratinjau dulu** (`dry_run` / `apply=false`) → konfirmasi di layar → jalankan
→ tercatat di Riwayat aksi massal → bisa **dibatalkan**.

  POST /{catalog_id}/fill-price          Isi harga jual dari harga resmi master (kosong saja / timpa)      (D1)
  GET  /hidden/preview                   Pratinjau rapikan item tersembunyi                                (D2)
  POST /hidden/apply                     Jalankan rapikan (angka pratinjau wajib dikirim ulang)            (D2)
  GET  /runs                             Riwayat aksi massal
  POST /runs/{run_id}/undo               Batalkan satu aksi massal
  GET  /price-url/template               Unduh daftar harga & URL (Excel)                                  (D4)
  POST /price-url/upload                 Unggah daftar: pratinjau (apply=false) / terapkan (apply=true)    (D4)
"""
import io
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth import log_activity, require_auth
from core import catalog_runs as _runs
from core import catalog_status as _cstatus
from core import catalog_stock as _cstock
from core import catalog_tools as _tools
from core import marketing_account_scope as _scope
from core import product_master as _pm
from core import product_status as _pstatus
from database import get_db
from routes.marketing_catalog_items import require_catalog_writer
from routes.shared import has_perm

router = APIRouter(prefix='/api/marketing/catalog-tools', tags=['Marketing-Catalog-tools'])

_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
# "Rapikan item tersembunyi" menyentuh SEMUA toko sekaligus → hanya admin / pimpinan Marketing (klarifikasi D).
CLEANUP_ROLES = ('manager_marketing', 'spv_marketing', 'manager', 'owner', 'admin', 'superadmin')
CLEANUP_DENIED = ('Hanya admin, owner, atau SPV/manager Marketing yang boleh merapikan item tersembunyi '
                  '(aksi ini menyentuh katalog semua toko).')
FILL_MAX = 2000


async def _require_cleanup(request: Request) -> dict:
    user = await require_auth(request)
    from routes.shared import lolos_centang
    if lolos_centang(user):  # 14 Nov 2026 (tahap 2): centang owner dihormati
        return user
    role = str(user.get('role') or '').lower()
    if role in CLEANUP_ROLES or has_perm(user, 'katalog.rapikan'):
        return user
    raise HTTPException(403, CLEANUP_DENIED)


async def _catalog_or_404(db, catalog_id: str) -> dict:
    cat = await db.marketing_catalogs.find_one({'id': catalog_id}, {'_id': 0})
    if not cat:
        raise HTTPException(404, 'Katalog tidak ditemukan.')
    return cat


def _skip_summary(skipped: list) -> dict:
    out: dict = {}
    for s in skipped:
        out[s['why']] = out.get(s['why'], 0) + 1
    return out


# ══════════════════════════════════════════════════════════════════════════════
# D1 — Isi harga dari master
# ══════════════════════════════════════════════════════════════════════════════
class FillPriceBody(BaseModel):
    item_ids: List[str] = Field(min_length=1)
    mode: str = 'kosong'            # kosong = hanya harga jual 0 · timpa = samakan dengan harga resmi
    dry_run: bool = False
    reason: Optional[str] = Field(default='', max_length=300)


@router.post('/{catalog_id}/fill-price')
async def fill_price_from_master(catalog_id: str, data: FillPriceBody, request: Request):
    """Isi HARGA JUAL toko dari harga resmi master (per SKU dulu, cadangan harga model).

    Kenapa: 1.340 item tampil lahir Rp 0 karena katalog dulu hanya membaca harga model. Riwayat harga tetap
    tercatat per item (`marketing_change_log`, sama dengan "Ubah item"), dan aksinya bisa dibatalkan.
    """
    user = await require_catalog_writer(request, catalog_id)
    db = get_db()
    await _catalog_or_404(db, catalog_id)
    if data.mode not in _tools.FILL_MODES:
        raise HTTPException(400, "Pilihan isi harga harus 'kosong' (hanya yang belum berharga) atau 'timpa'.")
    ids = list(dict.fromkeys(data.item_ids))
    if len(ids) > FILL_MAX:
        raise HTTPException(400, f'Paling banyak {FILL_MAX} item sekali isi ({len(ids)} dipilih).')
    items = await db.marketing_catalog_items.find(
        {'catalog_id': catalog_id, 'id': {'$in': ids}}, {'_id': 0}).to_list(len(ids))
    res = await _tools.fill_price_plan(db, items, mode=data.mode)
    plan, skipped = res['plan'], res['skipped']
    found = {it['id'] for it in items}
    skipped.extend({'item_id': i, 'sku': '', 'why': 'tidak ditemukan di katalog ini'} for i in ids if i not in found)
    sample = [info for _it, _p, info in plan[:15]]
    mode_label = 'hanya yang belum berharga' if data.mode == 'kosong' else 'timpa harga yang berbeda'
    if data.dry_run:
        return {'ok': True, 'dry_run': True, 'mode': data.mode, 'would_change': len(plan),
                'skipped': len(skipped), 'skip_summary': _skip_summary(skipped), 'sample': sample,
                'coret_below': sum(1 for _i, _p, info in plan if info['coret_below']),
                'by_source': {s: sum(1 for _i, _p, info in plan if info['source'] == s) for s in ('sku', 'model')},
                'message': f'{len(plan)} item akan diisi harga resmi master ({mode_label})'
                           + (f' · {len(skipped)} dilewati' if skipped else '')}

    now = datetime.now(timezone.utc)
    who = user.get('email') or user.get('id', '')
    reason = ('Isi harga dari master' + (f' — {data.reason.strip()}' if (data.reason or '').strip() else ''))
    changes = []
    for it, patch, _info in plan:
        before = _runs.snapshot(it, patch.keys())
        await db.marketing_catalog_items.update_one(
            {'id': it['id']}, {'$set': {**patch, 'updated_at': now, 'updated_by': who}})
        await _runs.log_price_change(db, it, patch, user=user, reason=reason)
        changes.append({'item_id': it['id'], 'catalog_id': catalog_id, 'sku': it.get('sku'),
                        'before': before, 'after': dict(patch)})
    run = None
    if changes:
        run = await _runs.record(db, kind='isi_harga', user=user, changes=changes, catalog_ids=[catalog_id],
                                 summary={'changed': len(changes), 'mode': data.mode,
                                          'skip_summary': _skip_summary(skipped)})
        await log_activity(user.get('id', ''), user.get('name') or user.get('email', 'system'),
                           'catalog_fill_price', 'marketing_catalog_items',
                           f'Isi harga dari master: {len(changes)} item ({mode_label})')
    return {'ok': True, 'mode': data.mode, 'changed': len(changes), 'skipped': len(skipped),
            'skip_summary': _skip_summary(skipped), 'sample': sample, 'run_id': (run or {}).get('id'),
            'message': f'{len(changes)} item diisi harga resmi master'
                       + (f' · {len(skipped)} dilewati' if skipped else '')}


# ══════════════════════════════════════════════════════════════════════════════
# D2 — Rapikan item tersembunyi
# ══════════════════════════════════════════════════════════════════════════════
class HiddenApplyBody(BaseModel):
    # angka dari pratinjau — bila data berubah sejak pratinjau, aksi ditolak (lihat pratinjau baru dulu)
    expect_twins: int = Field(ge=0)
    expect_singles: int = Field(ge=0)


async def _hidden_scope(db, user) -> Optional[list]:
    return await _scope.visible_account_ids(db, user)


@router.get('/hidden/preview')
async def preview_hidden_items(request: Request):
    """Pratinjau: berapa item tersembunyi, berapa kembar (dan apa yang disalin), berapa tunggal, apa yang dilewati."""
    user = await _require_cleanup(request)
    db = get_db()
    plan = await _tools.hidden_plan(db, account_ids=await _hidden_scope(db, user))
    out = _tools.plan_preview(plan)
    s = out['summary']
    out['message'] = (f"{s['hidden']} item tersembunyi: {s['twins']} kembar item tampil (diarsipkan setelah "
                      f"harga/URL disalin bila kosong), {s['singles']} tunggal (dipasangkan ke katalog tokonya)"
                      + (f", {s['skipped']} dilewati" if s['skipped'] else '') + '.')
    return {'ok': True, **out}


@router.post('/hidden/apply')
async def apply_hidden_items(data: HiddenApplyBody, request: Request):
    user = await _require_cleanup(request)
    db = get_db()
    plan = await _tools.hidden_plan(db, account_ids=await _hidden_scope(db, user))
    s = plan['summary']
    if s['twins'] != data.expect_twins or s['singles'] != data.expect_singles:
        raise HTTPException(409, f"Data berubah sejak pratinjau (kini {s['twins']} kembar, {s['singles']} tunggal). "
                                 'Buka pratinjau lagi lalu konfirmasi ulang.')
    res = await _tools.apply_hidden_plan(db, plan, user)
    await log_activity(user.get('id', ''), user.get('name') or user.get('email', 'system'),
                       'catalog_tidy_hidden', 'marketing_catalog_items',
                       f"Rapikan item tersembunyi: {s['twins']} kembar diarsipkan, {s['singles']} dipasangkan ke "
                       f"katalog, {res['summary'].get('created_catalogs', 0)} katalog baru")
    return {'ok': True, 'summary': res['summary'], 'run_id': (res['run'] or {}).get('id'),
            'touched_catalogs': res['touched_catalogs'],
            'message': (f"Rapikan selesai: {s['twins']} kembar diarsipkan ({s['twins_copy_price']} harga, "
                        f"{s['twins_copy_url']} URL disalin, {s['twins_publish']} item tampil ditayangkan), "
                        f"{s['singles']} item dipasangkan ke katalog tokonya. Bisa dibatalkan dari Riwayat aksi "
                        'massal.')}


# ══════════════════════════════════════════════════════════════════════════════
# Riwayat aksi massal + batalkan
# ══════════════════════════════════════════════════════════════════════════════
async def _visible_catalog_ids(db, user) -> Optional[list]:
    ids = await _scope.visible_account_ids(db, user)
    if ids is None:
        return None
    return [c['id'] for c in await db.marketing_catalogs.find(
        {'account_id': {'$in': ids}}, {'_id': 0, 'id': 1}).to_list(500)]


@router.get('/runs')
async def list_bulk_runs(request: Request, catalog_id: Optional[str] = None,
                         limit: int = Query(20, ge=1, le=100)):
    user = await require_auth(request)
    db = get_db()
    allowed = await _visible_catalog_ids(db, user)
    if catalog_id:
        if allowed is not None and catalog_id not in allowed:
            raise HTTPException(403, 'Katalog ini bukan milik toko Anda.')
        cids = [catalog_id]
    else:
        cids = allowed
    return {'ok': True, 'runs': await _runs.list_runs(db, catalog_ids=cids, limit=limit)}


@router.post('/runs/{run_id}/undo')
async def undo_bulk_run(run_id: str, request: Request):
    db = get_db()
    run = await db[_runs.RUNS].find_one({'id': run_id}, {'_id': 0, 'changes': 0})
    if not run:
        raise HTTPException(404, 'Riwayat aksi massal tidak ditemukan.')
    if run.get('kind') == 'rapikan_tersembunyi':
        user = await _require_cleanup(request)
    else:
        user = await require_catalog_writer(request)
    allowed = await _visible_catalog_ids(db, user)
    if allowed is not None and any(c not in allowed for c in run.get('catalog_ids') or []):
        raise HTTPException(403, 'Aksi ini menyentuh katalog toko lain — minta SPV/manager membatalkannya.')
    try:
        res = await _runs.undo(db, run_id, user)
    except _runs.RunError as e:
        raise HTTPException(e.status, e.message)
    for cid in res['touched_catalogs']:
        await _cstock.refresh_catalog_stats(db, cid)
    await log_activity(user.get('id', ''), user.get('name') or user.get('email', 'system'),
                       'catalog_bulk_undo', 'marketing_catalog_items',
                       f"Batalkan '{res['kind_label']}': {res['restored']} item dikembalikan, "
                       f"{res['n_conflicts']} dilewati")
    return {'ok': True, **res,
            'message': f"Dibatalkan: {res['restored']} item dikembalikan seperti sebelum '{res['kind_label']}'"
                       + (f" · {res['n_conflicts']} dilewati karena sudah diubah sesudahnya"
                          if res['n_conflicts'] else '')}


# ══════════════════════════════════════════════════════════════════════════════
# D4 — Unggah harga & URL dari Excel
# ══════════════════════════════════════════════════════════════════════════════
async def _catalogs_for(db, user, catalog_id: Optional[str]) -> list:
    if catalog_id:
        cat = await _catalog_or_404(db, catalog_id)
        await _scope.assert_account_visible(db, user, cat.get('account_id'))
        return [cat]
    q = await _scope.scope_filter(db, user, {'is_active': {'$ne': False}})
    return await db.marketing_catalogs.find(q, {'_id': 0}).sort('name', 1).to_list(200)


def _acc_label(acc: dict, cat: dict) -> str:
    return (acc or {}).get('account_code') or (acc or {}).get('account_name') or cat.get('account_name') or ''


@router.get('/price-url/template')
async def download_price_url_template(request: Request, catalog_id: Optional[str] = None):
    """Daftar item katalog (satu katalog, atau semua katalog yang boleh Anda lihat) untuk diisi harga & URL."""
    user = await require_catalog_writer(request)
    db = get_db()
    cats = await _catalogs_for(db, user, catalog_id)
    accs = {a['id']: a for a in await db.marketing_platform_accounts.find(
        {'id': {'$in': [c.get('account_id') for c in cats if c.get('account_id')]}},
        {'_id': 0, 'id': 1, 'account_code': 1, 'account_name': 1}).to_list(500)}
    rows = []
    for cat in cats:
        items = await db.marketing_catalog_items.find({'catalog_id': cat['id']}, {'_id': 0}).sort(
            'sku', 1).to_list(5000)
        links = await _cstock.resolve_links_bulk(db, items)
        pmap = await _pm.official_price_map(db, [lk.get('fg_material_id') for lk in links.values()])
        pst = await _tools.product_status_map(db, links)
        for it in items:
            fid = (links.get(it['id']) or {}).get('fg_material_id')
            rows.append({
                'id_item': it['id'], 'toko': _acc_label(accs.get(cat.get('account_id')), cat),
                'katalog': cat.get('name') or '', 'sku': it.get('sku') or '', 'nama': it.get('name') or '',
                'varian': it.get('variant_info') or '',
                'status_produk': _pstatus.label(pst.get(it['id'])) if pst.get(it['id']) else '',
                'penayangan': _cstatus.PUBLISH_LABEL.get(_cstatus.publish_state_of(it), ''),
                'harga_resmi': (pmap.get(fid) or (0.0, ''))[0] or None,
                'harga_jual': _tools.harga_jual_of(it) or None,
                'harga_coret': _tools.harga_coret_of(it) or None,
                'url_produk': it.get('platform_url') or '',
            })
    data = _tools.build_price_url_workbook(rows)
    name = 'harga-url-katalog.xlsx' if not catalog_id else f"harga-url-{(cats[0].get('name') or 'katalog')}.xlsx"
    safe = ''.join(ch if ch.isalnum() or ch in '-_.' else '-' for ch in name)
    return StreamingResponse(io.BytesIO(data), media_type=_XLSX,
                             headers={'Content-Disposition': f'attachment; filename="{safe}"'})


@router.post('/price-url/upload')
async def upload_price_url(request: Request, file: UploadFile = File(...), catalog_id: Optional[str] = None,
                           apply: bool = False, publish: bool = True):
    """Unggah daftar harga & URL. `apply=false` = pratinjau saja; `apply=true` = terapkan (bisa dibatalkan).

    Cocokkan baris: kolom "ID item" (dari Unduh daftar) → item; tanpa ID: Toko + SKU (atau SKU di katalog yang
    dipilih). Sel kosong = tidak diubah. `publish=true`: item yang URL produknya sah ditandai tayang (bukti tayang
    = URL milik item itu sendiri).
    """
    user = await require_catalog_writer(request)
    db = get_db()
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, 'Berkas lebih dari 10 MB.')
    rows, errors = _tools.parse_price_url_workbook(data)
    cats = await _catalogs_for(db, user, catalog_id)
    cat_by_id = {c['id']: c for c in cats}
    accs = {a['id']: a for a in await db.marketing_platform_accounts.find(
        {'id': {'$in': [c.get('account_id') for c in cats if c.get('account_id')]}},
        {'_id': 0, 'id': 1, 'account_code': 1, 'account_name': 1}).to_list(500)}
    cat_by_label: dict = {}
    for c in cats:
        acc = accs.get(c.get('account_id')) or {}
        for lbl in (acc.get('account_code'), acc.get('account_name'), c.get('name'), c.get('account_name')):
            if lbl:
                cat_by_label.setdefault(_tools.norm(lbl), c['id'])

    ids = [r['id_item'] for r in rows if r.get('id_item')]
    by_id = {d['id']: d for d in await db.marketing_catalog_items.find(
        {'id': {'$in': ids}, 'catalog_id': {'$in': list(cat_by_id)}}, {'_id': 0}).to_list(len(ids) or 1)} \
        if ids else {}
    need_sku = sorted({r['sku'] for r in rows if not r.get('id_item') and r.get('sku')})
    by_cat_sku: dict = {}
    if need_sku:
        for d in await db.marketing_catalog_items.find(
                {'catalog_id': {'$in': list(cat_by_id)}, 'sku': {'$in': need_sku}}, {'_id': 0}).to_list(20000):
            by_cat_sku.setdefault((d['catalog_id'], str(d.get('sku') or '').upper()), d)

    plan, unchanged, seen = [], 0, set()
    for r in rows:
        label = r['sku'] or r['id_item']
        item = by_id.get(r['id_item']) if r.get('id_item') else None
        if r.get('id_item') and not item:
            errors.append(f"Baris {r['row']} ({label}): ID item tidak ditemukan di katalog yang boleh Anda ubah.")
            continue
        if not item:
            cid = catalog_id or cat_by_label.get(_tools.norm(r.get('toko'))) or \
                cat_by_label.get(_tools.norm(r.get('katalog')))
            if not cid:
                errors.append(f"Baris {r['row']} ({label}): toko '{r.get('toko') or '—'}' tidak dikenali — isi kolom "
                              'Toko dengan kode/nama toko, atau unggah dari layar katalog tokonya.')
                continue
            item = by_cat_sku.get((cid, r['sku']))
            if not item:
                errors.append(f"Baris {r['row']} ({label}): SKU tidak ada di katalog toko itu.")
                continue
        if item['id'] in seen:
            errors.append(f"Baris {r['row']} ({label}): item yang sama muncul lebih dari sekali — baris ini diabaikan.")
            continue
        seen.add(item['id'])
        patch, err = _tools.price_url_patch(item, r, publish=publish)
        if err:
            errors.append(f"Baris {r['row']} ({label}): {err}.")
            continue
        if not patch:
            unchanged += 1
            continue
        plan.append((item, patch, r['row']))

    def _row(item, patch, n):
        return {'row': n, 'sku': item.get('sku'), 'name': item.get('name'),
                'katalog': (cat_by_id.get(item.get('catalog_id')) or {}).get('name'),
                'harga_jual': [_tools.harga_jual_of(item), patch['harga_jual']] if 'harga_jual' in patch else None,
                'harga_coret': [_tools.harga_coret_of(item), patch['harga_coret']] if 'harga_coret' in patch else None,
                'url': patch.get('platform_url'), 'tayang': patch.get('publish_state') == 'published'}

    summary = {'rows': len(rows), 'changes': len(plan), 'unchanged': unchanged, 'errors': len(errors),
               'price': sum(1 for _i, p, _n in plan if 'harga_jual' in p),
               'coret': sum(1 for _i, p, _n in plan if 'harga_coret' in p),
               'url': sum(1 for _i, p, _n in plan if 'platform_url' in p),
               'publish': sum(1 for _i, p, _n in plan if p.get('publish_state') == 'published')}
    if not apply:
        return {'ok': True, 'dry_run': True, 'summary': summary, 'errors': errors[:200],
                'sample': [_row(i, p, n) for i, p, n in plan[:50]],
                'message': f"{len(plan)} item akan diubah · {unchanged} tidak berubah"
                           + (f" · {len(errors)} baris bermasalah" if errors else '')}

    now = datetime.now(timezone.utc)
    who = user.get('email') or user.get('id', '')
    changes, touched = [], set()
    for item, patch, n in plan:
        before = _runs.snapshot(item, patch.keys())
        upd = {'$set': {**patch, 'updated_at': now, 'updated_by': who}}
        if patch.get('publish_state') == 'published':
            upd['$push'] = {'status_history': {'$each': [{'at': now, 'by': who, 'action': 'publish',
                                                          'note': 'Unggah harga & URL (Excel)'}], '$slice': -50}}
        await db.marketing_catalog_items.update_one({'id': item['id']}, upd)
        await _runs.log_price_change(db, item, patch, user=user, reason='Unggah harga & URL (Excel)')
        changes.append({'item_id': item['id'], 'catalog_id': item.get('catalog_id'), 'sku': item.get('sku'),
                        'before': before, 'after': dict(patch)})
        touched.add(item.get('catalog_id'))
    run = None
    if changes:
        run = await _runs.record(db, kind='unggah_harga_url', user=user, changes=changes, catalog_ids=touched,
                                 summary=summary, extra={'filename': (file.filename or '')[:200]})
        for cid in touched:
            await _cstock.refresh_catalog_stats(db, cid)
        await log_activity(user.get('id', ''), user.get('name') or user.get('email', 'system'),
                           'catalog_price_url_upload', 'marketing_catalog_items',
                           f"Unggah harga & URL: {len(changes)} item diubah ({summary['publish']} ditayangkan)")
    return {'ok': True, 'summary': summary, 'errors': errors[:200], 'run_id': (run or {}).get('id'),
            'message': f"{len(changes)} item diperbarui dari berkas"
                       + (f" ({summary['publish']} ditandai tayang)" if summary['publish'] else '')
                       + (f" · {len(errors)} baris bermasalah dilewati" if errors else '')}
