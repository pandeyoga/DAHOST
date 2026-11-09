"""core.catalog_tools — aksi cepat Manajemen Katalog (klarifikasi owner 9 Nov 2026, §B & §D).

Isi berkas ini (semua tanpa HTTP; route tipis ada di `routes/marketing_catalog_tools.py`):

  * **Status produk per baris** (D5) — `product_status_map()` menempelkan status varian master
    (Baru · Best Seller · Slow · Dead · Stop) ke item katalog, satu kueri untuk seluruh katalog.
  * **Isi harga dari master** (D1/B3) — `fill_price_plan()`: harga jual toko diisi harga resmi PER SKU
    (`rahaza_materials.retail_price_master`), cadangan harga model. Mode "kosong saja" atau "timpa".
  * **Unggah harga & URL dari Excel** (D4) — `build_price_url_workbook()` / `parse_price_url_workbook()` /
    `plan_price_url_rows()`: unduh daftar → isi harga/URL per SKU per toko → unggah dengan pratinjau.
  * **Rapikan item tersembunyi** (D2) — `hidden_plan()` / `apply_hidden_plan()`: item impor lama tanpa
    `catalog_id` (tidak tampil di layar mana pun). Kembaran item tampil → harga/harga coret/URL disalin ke item
    tampil bila kosong, item tampil yang URL-nya sah ditayangkan, kembaran DIARSIPKAN (bukan dihapus). Item
    tunggal → dipasangkan ke katalog toko yang sama.

Setiap aksi yang menulis dicatat lewat `core.catalog_runs` (pratinjau → konfirmasi → bisa dibatalkan).
Aturan penting yang tidak berubah: "tayang" hanya dengan URL produk sah MILIK ITEM ITU SENDIRI.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Iterable, Optional

from core import catalog_status as _cstatus
from core import catalog_stock as _cstock
from core import product_master as _pm
from core import product_status as _pstatus

HIDDEN_ITEM_FILTER = {'$or': [{'catalog_id': None}, {'catalog_id': ''}, {'catalog_id': {'$exists': False}}]}
LIVE_HIDDEN = {'$and': [HIDDEN_ITEM_FILTER, {'publish_state': {'$ne': 'archived'}},
                        {'merged_into': {'$in': [None, '']}}]}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def harga_jual_of(item: dict) -> float:
    v = item.get('harga_jual')
    return _f(v if v is not None else item.get('price'))


def harga_coret_of(item: dict) -> float:
    v = item.get('harga_coret')
    return _f(v if v is not None else item.get('original_price'))


def norm(s) -> str:
    return re.sub(r'\s+', ' ', str(s or '').strip().lower())


# ══════════════════════════════════════════════════════════════════════════════
# D5 — status produk varian per item katalog
# ══════════════════════════════════════════════════════════════════════════════
def link_sku(link: dict) -> str:
    """SKU varian sebuah tautan item → FG (kode FG = SKU varian, konvensi Fase 3b)."""
    return str((link or {}).get('fg_code') or (link or {}).get('variant_sku') or '').strip()


async def status_by_sku(db, skus: Iterable[str]) -> dict:
    """{SKU (huruf besar): kode status | None}; varian aktif menang atas yang nonaktif."""
    wanted = sorted({str(s).strip() for s in skus if s and str(s).strip()})
    if not wanted:
        return {}
    out: dict = {}
    rows = await db.rahaza_model_variants.find(
        {'sku': {'$in': wanted}}, {'_id': 0, 'sku': 1, 'active': 1, _pstatus.FIELD: 1}).to_list(len(wanted) * 4)
    for v in rows:
        key = str(v.get('sku') or '').strip().upper()
        if key and (key not in out or v.get('active') is not False):
            out[key] = v.get(_pstatus.FIELD) or None
    return out


async def product_status_map(db, links: dict) -> dict:
    """{item_id: kode status produk | None} — item yang belum tertaut master → None ("belum diisi")."""
    st = await status_by_sku(db, (link_sku(lk) for lk in (links or {}).values()))
    return {iid: st.get(link_sku(lk).upper()) for iid, lk in (links or {}).items()}


# ══════════════════════════════════════════════════════════════════════════════
# D1 — isi harga jual dari harga resmi master
# ══════════════════════════════════════════════════════════════════════════════
FILL_MODES = ('kosong', 'timpa')


async def fill_price_plan(db, items: list, *, mode: str) -> dict:
    """→ ``{'plan': [(item, patch, info)], 'skipped': [{item_id, sku, why}]}``.

    `kosong` = hanya item yang harga jualnya 0; `timpa` = semua item yang harganya berbeda dari harga resmi.
    Sumber harga = harga resmi PER SKU (FG), cadangan harga model (`core.product_master.official_price`).
    """
    if mode not in FILL_MODES:
        raise ValueError("mode harus 'kosong' atau 'timpa'")
    links = await _cstock.resolve_links_bulk(db, items)
    pmap = await _pm.official_price_map(db, [lk.get('fg_material_id') for lk in links.values()])
    plan, skipped = [], []
    for it in items:
        lk = links.get(it['id']) or {}
        fid = lk.get('fg_material_id')
        base = {'item_id': it['id'], 'sku': it.get('sku'), 'name': it.get('name')}
        if not fid:
            skipped.append({**base, 'why': 'belum tertaut master'})
            continue
        price, src = pmap.get(fid, (0.0, 'none'))
        if price <= 0:
            skipped.append({**base, 'why': 'harga resmi belum ada di master'})
            continue
        cur = harga_jual_of(it)
        if mode == 'kosong' and cur > 0:
            skipped.append({**base, 'why': 'harga jual sudah terisi'})
            continue
        if abs(cur - price) < 0.005:
            skipped.append({**base, 'why': 'sudah sama dengan harga resmi'})
            continue
        coret = harga_coret_of(it)
        patch = {'harga_jual': price, 'price': price, 'retail_price_master': price, 'retail_price_source': src}
        info = {**base, 'old': cur, 'new': price, 'source': src,
                'source_label': _pm.OFFICIAL_PRICE_SOURCE_LABEL.get(src, src),
                'coret_below': bool(coret and coret < price)}
        plan.append((it, patch, info))
    return {'plan': plan, 'skipped': skipped}


# ══════════════════════════════════════════════════════════════════════════════
# D4 — unggah harga & URL dari Excel
# ══════════════════════════════════════════════════════════════════════════════
SHEET = 'Harga dan URL'
COLUMNS = [
    ('id_item', 'ID item (jangan diubah)'),
    ('toko', 'Toko'),
    ('katalog', 'Katalog'),
    ('sku', 'SKU'),
    ('nama', 'Nama produk'),
    ('varian', 'Varian'),
    ('status_produk', 'Status produk'),
    ('penayangan', 'Penayangan'),
    ('harga_resmi', 'Harga resmi master'),
    ('harga_jual', 'Harga jual'),
    ('harga_coret', 'Harga coret'),
    ('url_produk', 'URL produk'),
]
EDITABLE = ('harga_jual', 'harga_coret', 'url_produk')
_HEADER_ALIASES = {
    'id item': 'id_item', 'id': 'id_item', 'item id': 'id_item',
    'toko': 'toko', 'kode toko': 'toko', 'akun': 'toko',
    'katalog': 'katalog', 'sku': 'sku', 'kode sku': 'sku',
    'harga jual': 'harga_jual', 'harga': 'harga_jual',
    'harga coret': 'harga_coret',
    'url produk': 'url_produk', 'url': 'url_produk', 'tautan produk': 'url_produk', 'link produk': 'url_produk',
}
MAX_ROWS = 5000


def _header_key(v) -> str:
    t = re.sub(r'\(.*?\)', '', str(v or '')).replace('_', ' ')
    return _HEADER_ALIASES.get(norm(t), '')


def parse_money(v) -> Optional[float]:
    """Sel harga → angka; kosong → None. Menerima 89000, "89.000", "Rp 89.000", "89,000", "89.000,50"."""
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError('bukan angka')
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s in ('-', '—'):
        return None
    s = re.sub(r'(?i)rp', '', s)
    s = re.sub(r'[^\d,.\-]', '', s)
    if not s or s in ('-', '.', ','):
        raise ValueError('bukan angka')
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '') if re.fullmatch(r'-?\d{1,3}(,\d{3})+', s) else s.replace(',', '.')
    elif re.fullmatch(r'-?\d{1,3}(\.\d{3})+', s):
        s = s.replace('.', '')
    return float(s)


def build_price_url_workbook(rows: list) -> bytes:
    """`rows` = dict ber-kunci COLUMNS → berkas .xlsx satu lembar (kolom yang boleh diisi diberi tanda)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append([label for _k, label in COLUMNS])
    bold = Font(bold=True)
    fill = PatternFill('solid', fgColor='FFF2CC')
    for i, (key, _label) in enumerate(COLUMNS, start=1):
        c = ws.cell(row=1, column=i)
        c.font = bold
        if key in EDITABLE:
            c.fill = fill
    for r in rows:
        ws.append([r.get(k) for k, _l in COLUMNS])
    widths = {'id_item': 38, 'toko': 22, 'katalog': 24, 'sku': 22, 'nama': 40, 'varian': 26, 'status_produk': 14,
              'penayangan': 14, 'harga_resmi': 16, 'harga_jual': 14, 'harga_coret': 14, 'url_produk': 50}
    for i, (key, _l) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = widths.get(key, 16)
    ws.freeze_panes = 'E2'
    info = wb.create_sheet('Petunjuk')
    for line in (
        'Isi hanya kolom berwarna: Harga jual, Harga coret, URL produk. Sel kosong = tidak diubah.',
        'Jangan mengubah kolom "ID item" — dipakai untuk mencocokkan baris dengan item katalog.',
        'Harga ditulis angka (89000 atau 89.000). Harga coret = harga SEBELUM diskon (≥ harga jual).',
        'URL produk = tautan produk di marketplace, diawali https://. Item dengan URL sah bisa langsung '
        'ditandai tayang saat diunggah (pilihan di layar).',
        'Unggah kembali di Manajemen katalog › Item › Unggah harga & URL — layar menampilkan pratinjau dulu.',
    ):
        info.append([line])
    info.column_dimensions['A'].width = 110
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def parse_price_url_workbook(data: bytes) -> tuple:
    """→ (baris: [{row, id_item, toko, katalog, sku, harga_jual?, harga_coret?, url_produk?}], galat: [str])."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 — berkas rusak / bukan xlsx
        return [], ['Berkas tidak bisa dibaca. Unggah berkas Excel (.xlsx) hasil "Unduh daftar".']
    ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    header = next(it, None) or ()
    cols = {}
    for i, h in enumerate(header):
        k = _header_key(h)
        if k and k not in cols:
            cols[k] = i
    if 'sku' not in cols and 'id_item' not in cols:
        return [], ['Kolom "SKU" atau "ID item" tidak ditemukan di baris pertama. Pakai berkas dari "Unduh daftar".']
    if not any(k in cols for k in EDITABLE):
        return [], ['Kolom "Harga jual", "Harga coret", atau "URL produk" tidak ditemukan di baris pertama.']
    rows, errors = [], []
    for n, r in enumerate(it, start=2):
        if n - 1 > MAX_ROWS:
            errors.append(f'Berkas lebih dari {MAX_ROWS} baris — sisanya tidak dibaca. Pecah per toko.')
            break
        get = (lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else None)
        rec = {'row': n, 'id_item': str(get('id_item') or '').strip(), 'toko': str(get('toko') or '').strip(),
               'katalog': str(get('katalog') or '').strip(), 'sku': str(get('sku') or '').strip().upper()}
        if not (rec['id_item'] or rec['sku']):
            continue
        bad = False
        for k in ('harga_jual', 'harga_coret'):
            try:
                v = parse_money(get(k))
            except ValueError:
                errors.append(f"Baris {n} ({rec['sku'] or rec['id_item']}): {k.replace('_', ' ')} bukan angka "
                              f"('{get(k)}').")
                bad = True
                continue
            if v is not None:
                if v < 0:
                    errors.append(f"Baris {n} ({rec['sku']}): {k.replace('_', ' ')} tidak boleh negatif.")
                    bad = True
                    continue
                rec[k] = v
        url = str(get('url_produk') or '').strip()
        if url:
            if not _cstatus.is_valid_url(url):
                errors.append(f"Baris {n} ({rec['sku']}): URL produk tidak sah — harus diawali http:// atau "
                              'https://.')
                bad = True
            else:
                rec['url_produk'] = url
        if not bad and any(k in rec for k in EDITABLE):
            rows.append(rec)
    return rows, errors


def price_url_patch(item: dict, rec: dict, *, publish: bool) -> tuple:
    """(patch | None, galat | None) untuk satu baris unggahan — sel kosong = tidak diubah."""
    patch: dict = {}
    jual = rec.get('harga_jual')
    coret = rec.get('harga_coret')
    if jual is not None and abs(jual - harga_jual_of(item)) >= 0.005:
        patch.update({'harga_jual': jual, 'price': jual})
    if coret is not None and abs(coret - harga_coret_of(item)) >= 0.005:
        patch.update({'harga_coret': coret, 'original_price': coret})
    fin_jual = jual if jual is not None else harga_jual_of(item)
    fin_coret = coret if coret is not None else harga_coret_of(item)
    if fin_coret and fin_jual and fin_coret < fin_jual:
        return None, (f'harga coret ({fin_coret:,.0f}) lebih kecil dari harga jual ({fin_jual:,.0f}) — '
                      'harga coret = harga SEBELUM diskon').replace(',', '.')
    url = rec.get('url_produk')
    if url and url != str(item.get('platform_url') or '').strip():
        patch['platform_url'] = url
    fin_url = url or str(item.get('platform_url') or '').strip()
    stored = str(item.get('publish_state') or '').strip().lower()
    state = _cstatus.publish_state_of(item)
    if publish and fin_url and _cstatus.is_valid_url(fin_url) and stored != 'published' \
            and state != 'archived' and item.get('is_active') is not False:
        patch.update({'publish_state': 'published', 'published_at': _now(), 'rejected_reason': ''})
    return (patch or None), None


# ══════════════════════════════════════════════════════════════════════════════
# D2 — rapikan item tersembunyi (impor lama tanpa katalog)
# ══════════════════════════════════════════════════════════════════════════════
HIDDEN_SCAN_CAP = 20000


async def hidden_plan(db, *, account_ids: Optional[list] = None) -> dict:
    """Rencana perapian (tanpa menulis). `account_ids` None = semua toko."""
    hq = dict(LIVE_HIDDEN)
    if account_ids is not None:
        hq = {'$and': [LIVE_HIDDEN, {'account_id': {'$in': list(account_ids)}}]}
    hidden = await db.marketing_catalog_items.find(hq, {'_id': 0}).sort('sku', 1).to_list(HIDDEN_SCAN_CAP)
    cats = await db.marketing_catalogs.find({}, {'_id': 0, 'id': 1, 'account_id': 1, 'is_active': 1,
                                                 'name': 1}).to_list(2000)
    cat_acc = {c['id']: c.get('account_id') for c in cats}
    active_by_acc: dict = {}
    for c in cats:
        if c.get('is_active') is not False and c.get('account_id'):
            active_by_acc.setdefault(c['account_id'], []).append(c)
    accounts = {a['id']: a for a in await db.marketing_platform_accounts.find(
        {}, {'_id': 0, 'id': 1, 'account_code': 1, 'account_name': 1, 'platform': 1}).to_list(1000)}
    vis = await db.marketing_catalog_items.find(
        {'catalog_id': {'$in': list(cat_acc)}}, {'_id': 0}).to_list(HIDDEN_SCAN_CAP * 2) if cat_acc else []
    by_fg: dict = {}
    by_sku: dict = {}
    for v in vis:
        acc = cat_acc.get(v.get('catalog_id')) or v.get('account_id')
        fid = v.get('fg_material_id') or v.get('material_id')
        if acc and fid:
            by_fg.setdefault((acc, fid), v)
        if acc and v.get('sku'):
            by_sku.setdefault((acc, str(v['sku']).upper()), v)

    twins, singles, skipped, new_catalogs = [], [], [], {}
    claimed: dict = {}      # (catalog_id/akun, fg) tunggal yang sudah dipasang di rencana ini
    for h in hidden:
        acc = h.get('account_id')
        fid = h.get('fg_material_id') or h.get('material_id')
        base = {'hidden_id': h['id'], 'sku': h.get('sku'), 'name': h.get('name'), 'account_id': acc,
                'account_label': _acc_label(accounts.get(acc), acc)}
        if h.get('source') == 'seed_demo':
            skipped.append({**base, 'why': 'item contoh (data demo) — dibiarkan'})
            continue
        twin = by_fg.get((acc, fid)) if fid else None
        twin = twin or by_sku.get((acc, str(h.get('sku') or '').upper()))
        if twin:
            twins.append(_twin_plan(h, twin, base))
            continue
        if acc not in accounts:
            skipped.append({**base, 'why': 'toko tidak ditemukan di master toko'})
            continue
        act = active_by_acc.get(acc) or []
        if len(act) > 1:
            skipped.append({**base, 'why': f'toko punya {len(act)} katalog aktif — pilih katalognya manual'})
            continue
        key = (acc, fid or str(h.get('sku') or '').upper())
        if key in claimed:
            skipped.append({**base, 'why': f"kembar sesama item tersembunyi ({claimed[key]}) — dibiarkan"})
            continue
        claimed[key] = h.get('sku')
        if act:
            target = {'catalog_id': act[0]['id'], 'catalog_name': act[0].get('name'), 'new_catalog': False}
        else:
            new_catalogs.setdefault(acc, f"Katalog {(accounts.get(acc) or {}).get('account_name') or 'Toko'}")
            target = {'catalog_id': None, 'catalog_name': new_catalogs[acc], 'new_catalog': True}
        url = str(h.get('platform_url') or '').strip()
        publish = bool(url) and _cstatus.is_valid_url(url) and h.get('is_active') is not False
        singles.append({**base, **target, 'publish': publish,
                        'url_invalid': bool(url) and not _cstatus.is_valid_url(url),
                        'harga_jual': harga_jual_of(h)})

    summary = {
        'hidden': len(hidden),
        'twins': len(twins),
        'twins_copy_price': sum(1 for t in twins if 'harga_jual' in t['visible_patch']),
        'twins_copy_coret': sum(1 for t in twins if 'harga_coret' in t['visible_patch']),
        'twins_copy_url': sum(1 for t in twins if 'platform_url' in t['visible_patch']),
        'twins_publish': sum(1 for t in twins if t['publish']),
        'twins_conflict': sum(1 for t in twins if t['conflicts']),
        'singles': len(singles),
        'singles_publish': sum(1 for s in singles if s['publish']),
        'singles_new_catalog': sum(1 for s in singles if s['new_catalog']),
        'new_catalogs': len(new_catalogs),
        'skipped': len(skipped),
        'truncated': len(hidden) >= HIDDEN_SCAN_CAP,
    }
    return {'summary': summary, 'twins': twins, 'singles': singles, 'skipped': skipped,
            'new_catalogs': [{'account_id': a, 'name': n} for a, n in new_catalogs.items()]}


def _acc_label(acc: Optional[dict], acc_id) -> str:
    if not acc:
        return str(acc_id or '(tanpa toko)')
    return ' · '.join([x for x in (acc.get('account_code'), acc.get('account_name')) if x]) or str(acc_id)


def _twin_plan(h: dict, v: dict, base: dict) -> dict:
    """Kembaran: salin harga/harga coret/URL ke item tampil BILA kosong; tayangkan bila URL sah; arsipkan kembaran."""
    vp: dict = {}
    conflicts: list = []
    hj, vj = harga_jual_of(h), harga_jual_of(v)
    if hj > 0 and vj <= 0:
        vp.update({'harga_jual': hj, 'price': hj})
        if _f(v.get('platform_price')) <= 0:
            vp['platform_price'] = hj
    elif hj > 0 and abs(hj - vj) >= 0.005:
        conflicts.append(f'harga jual beda (tampil {vj:,.0f}, tersembunyi {hj:,.0f}) — harga tampil dipakai'
                         .replace(',', '.'))
    hc, vc = harga_coret_of(h), harga_coret_of(v)
    if hc > 0 and vc <= 0:
        vp.update({'harga_coret': hc, 'original_price': hc})
    hu, vu = str(h.get('platform_url') or '').strip(), str(v.get('platform_url') or '').strip()
    if hu and not vu:
        if _cstatus.is_valid_url(hu):
            vp['platform_url'] = hu
        else:
            conflicts.append('URL item tersembunyi tidak sah — tidak disalin')
    elif hu and vu and hu != vu:
        conflicts.append('URL beda — URL item tampil dipakai')
    psku = [p for p in (h.get('platform_sku_ids') or []) if p and p not in (v.get('platform_sku_ids') or [])]
    if psku:
        vp['platform_sku_ids'] = list(v.get('platform_sku_ids') or []) + psku
    fin_url = vp.get('platform_url') or vu
    stored = str(v.get('publish_state') or '').strip().lower()
    vstate = _cstatus.publish_state_of(v)
    publish = (bool(fin_url) and _cstatus.is_valid_url(fin_url) and stored != 'published'
               and vstate != 'archived' and v.get('is_active') is not False and h.get('is_active') is not False)
    if publish:
        vp.update({'publish_state': 'published', 'published_at': _now(), 'rejected_reason': '', 'is_active': True})
    hp = {'publish_state': 'archived', 'is_active': False, 'archived_at': _now(),
          'archived_reason': f"Kembar item tampil {v.get('sku') or ''} — dirapikan (harga/URL disalin bila kosong)",
          'merged_into': v['id']}
    return {**base, 'visible_id': v['id'], 'catalog_id': v.get('catalog_id'), 'visible_patch': vp,
            'hidden_patch': hp, 'publish': publish, 'conflicts': conflicts,
            'harga_tersembunyi': hj, 'harga_tampil': vj}


def plan_preview(plan: dict, *, sample: int = 30) -> dict:
    """Ringkasan untuk layar (popup konfirmasi): angka + contoh, tanpa ribuan baris."""
    def _tw(t):
        return {'sku': t['sku'], 'name': t['name'], 'toko': t['account_label'],
                'salin': sorted(k for k in t['visible_patch'] if k in ('harga_jual', 'harga_coret', 'platform_url')),
                'tayang': t['publish'], 'catatan': '; '.join(t['conflicts'])}

    def _sg(s):
        return {'sku': s['sku'], 'name': s['name'], 'toko': s['account_label'], 'katalog': s['catalog_name'],
                'katalog_baru': s['new_catalog'], 'tayang': s['publish']}
    return {'summary': plan['summary'],
            'twins_sample': [_tw(t) for t in plan['twins'][:sample]],
            'conflicts_sample': [_tw(t) for t in plan['twins'] if t['conflicts']][:sample],
            'singles_sample': [_sg(s) for s in plan['singles'][:sample]],
            'skipped': plan['skipped'][:sample],
            'new_catalogs': plan['new_catalogs']}


async def apply_hidden_plan(db, plan: dict, user: Optional[dict]) -> dict:
    """Jalankan rencana `hidden_plan` → jejak `core.catalog_runs` (bisa dibatalkan)."""
    from core import catalog_runs as _runs
    from core.sku_bridge import ensure_catalog

    now = _now()
    who = (user or {}).get('email') or (user or {}).get('id', '')
    changes: list = []
    created_catalogs: list = []
    touched: set = set()

    def _hist(action: str, note: str) -> dict:
        return {'$each': [{'at': now, 'by': who, 'action': action, 'note': note}], '$slice': -50}

    async def _write(item: dict, patch: dict, action: str, note: str):
        before = _runs.snapshot(item, patch.keys())
        await db.marketing_catalog_items.update_one(
            {'id': item['id']},
            {'$set': {**patch, 'updated_at': now, 'updated_by': who},
             '$push': {'status_history': _hist(action, note)}})
        changes.append({'item_id': item['id'], 'catalog_id': patch.get('catalog_id') or item.get('catalog_id'),
                        'sku': item.get('sku'), 'before': before, 'after': dict(patch)})
        await _runs.log_price_change(db, item, patch, user=user, reason='Rapikan item tersembunyi')

    for t in plan.get('twins') or []:
        h = await db.marketing_catalog_items.find_one({'id': t['hidden_id']}, {'_id': 0})
        v = await db.marketing_catalog_items.find_one({'id': t['visible_id']}, {'_id': 0})
        if not h or not v:
            continue
        if t['visible_patch']:
            await _write(v, t['visible_patch'], 'publish' if t['publish'] else 'rapikan',
                         f"Disalin dari item tersembunyi {h.get('sku') or ''} (rapikan)")
        await _write(h, t['hidden_patch'], 'archive', f"Kembar item tampil {v.get('sku') or ''} — diarsipkan")
        if v.get('catalog_id'):
            touched.add(v['catalog_id'])

    new_cat: dict = {}
    for s in plan.get('singles') or []:
        h = await db.marketing_catalog_items.find_one({'id': s['hidden_id']}, {'_id': 0})
        if not h:
            continue
        cid = s.get('catalog_id')
        if not cid:
            acc = s['account_id']
            if acc not in new_cat:
                before_ids = {c['id'] for c in await db.marketing_catalogs.find(
                    {'account_id': acc}, {'_id': 0, 'id': 1}).to_list(50)}
                cat = await ensure_catalog(db, acc, user=user)
                new_cat[acc] = cat['id']
                if cat['id'] not in before_ids:
                    created_catalogs.append(cat['id'])
            cid = new_cat[acc]
        patch = {'catalog_id': cid,
                 'publish_state': 'published' if s['publish'] else 'draft'}
        if s['publish'] and not h.get('published_at'):
            patch['published_at'] = now
        await _write(h, patch, 'publish' if s['publish'] else 'rapikan',
                     'Dipasangkan ke katalog tokonya (rapikan item tersembunyi)')
        touched.add(cid)

    summary = {**plan.get('summary', {}), 'changed_items': len(changes),
               'created_catalogs': len(created_catalogs)}
    run = None
    if changes:
        run = await _runs.record(db, kind='rapikan_tersembunyi', user=user, changes=changes,
                                 catalog_ids=touched, summary=summary,
                                 extra={'created_catalog_ids': created_catalogs})
    for cid in touched:
        await _cstock.refresh_catalog_stats(db, cid)
    return {'summary': summary, 'run': run, 'touched_catalogs': sorted(touched)}
