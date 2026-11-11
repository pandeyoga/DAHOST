"""core/sku_bridge.py — SSOT **jembatan SKU platform ⇄ master gudang** (Sesi #20).

═══════════════════════════════════════════════════════════════════════════════
MASALAH NYATA YANG DITUTUP BERKAS INI  (diukur `tests/poc_sync_forensic.py`)
═══════════════════════════════════════════════════════════════════════════════
Marketing dan Gudang memakai **dua semesta identitas** yang tidak pernah
bertemu:

| Pihak     | Identitas barang                        | Contoh                        |
|-----------|-----------------------------------------|-------------------------------|
| Marketing | ``platform_sku_id`` (angka milik TikTok/Shopee) | ``1736289266674467878`` |
| Gudang    | ``material_id`` (UUID) + ``code`` FG    | ``KAO-0001-PTH-M``            |

Hasil pengukuran pada data hidup **sebelum** berkas ini ada:
  * **0 dari 601** baris pesanan marketing menunjuk master gudang (0%).
  * **83 SKU platform** dipesan pembeli tanpa dikenal master.
  * Tabel jembatan ``marketing_catalog_items.platform_sku_ids[]`` **kosong**.

Jembatannya sebetulnya SUDAH ADA di kode — tetapi pintunya hanya satu:
``POST /api/marketing/import/sessions/{session_id}/sku-map``. Artinya pemetaan
**menempel pada sesi impor**. Sesi dihapus ⇒ SKU itu mustahil dipetakan lagi;
dan pesanan yang masuk lewat jalur lain (webhook, input manual) tidak punya sesi
sama sekali. Pemetaan identitas barang adalah **data master**, bukan lampiran
sebuah unggahan berkas.

KEPUTUSAN (Sesi #20)
--------------------
* **B-1** Pemetaan pindah ke koleksi mandiri :data:`BRIDGE`
  (``marketing_sku_bridge``) — hidup selamanya, lepas dari sesi impor.
* **B-2** ``marketing_catalog_items.platform_sku_ids[]`` TETAP ditulis (impor
  lama membacanya) — jadi jembatan baru tidak mematikan jalur yang sudah jalan.
* **B-3** Satu pemetaan menautkan **SELURUH** pesanan yang memakai SKU itu
  (semua toko, semua sesi, yang sudah masuk maupun yang akan masuk) — idempoten.
* **B-4** Sasaran pemetaan boleh **item katalog** ATAU **varian model internal**.
  Bila menunjuk varian dan toko itu belum punya item katalog, item katalog
  DIBUATKAN lewat SSOT `create_item_from_fg` (bukan tulisan dokumen mentah).
  Inilah P0 roadmap "tautkan variant_id ke mapping stok Toko / Finished Goods".
* **B-5** Mesin usulan **melaporkan keyakinannya** dan menolak menebak. Tidak
  ada pemetaan otomatis di bawah ambang; SKU yang tidak punya kandidat dikatakan
  terang-terangan ("belum ada master yang mirip") supaya pemilik tahu langkah
  berikutnya adalah membuat masternya, bukan menunggu.

ATURAN KERAS
------------
1. Semua penulisan tautan pesanan (``items[].fg_material_id``) lewat
   :func:`apply_mapping` / :func:`relink_orders`. Jangan `update_many` sendiri.
2. Stok TIDAK disentuh di sini. Menautkan identitas ≠ memesan barang.
3. ``platform_sku_id`` disimpan sebagai STRING apa adanya (angka 19 digit tidak
   boleh mampir ke float — presisinya hilang dan SKU-nya berubah).
"""
from __future__ import annotations

import difflib
import logging
import re
import uuid
from typing import Optional

from core import sku_kunci as _skuk   # G4: kunci nama+variasi untuk baris tanpa SKU platform
from collections import defaultdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BRIDGE = 'marketing_sku_bridge'
ORDERS = 'marketing_orders'
ITEMS = 'marketing_catalog_items'
CATALOGS = 'marketing_catalogs'
VARIANTS = 'rahaza_model_variants'
MATERIALS = 'rahaza_materials'
ACCOUNTS = 'marketing_platform_accounts'

#: Ambang keyakinan minimum untuk pemetaan OTOMATIS. Di bawah ini wajib manusia.
AUTO_MIN_CONFIDENCE = 0.82


def _now():
    return datetime.now(timezone.utc)


def _uid():
    return str(uuid.uuid4())


def _f(v, d=0.0):
    try:
        return float(v if v is not None else d)
    except (TypeError, ValueError):
        return d


# ══════════════════════════════════════════════════════════════════════════════
# Normalisasi teks & pembacaan variasi platform
# ══════════════════════════════════════════════════════════════════════════════
_PUNCT = re.compile(r'[^a-z0-9]+')

#: Kata yang tidak membedakan produk (muncul di hampir semua judul marketplace).
STOPWORDS = frozenset("""
    the dan and untuk wanita pria unisex premium terbaru terbaik murah grosir
    original import kekinian korean style elegan cantik lucu adem nyaman bahan
    kaos baju atasan bawahan set setelan pakaian fashion size all jumbo big
    ready stock stok promo diskon best seller free gratis new arrival
    lengan panjang pendek model motif polos warna cm ld pb
""".split())

#: Kosakata ukuran → kode master (`rahaza_sizes.code`).
SIZE_ALIASES = {
    's': 'S', 'small': 'S',
    'm': 'M', 'medium': 'M',
    'l': 'L', 'large': 'L',
    'xl': 'XL', 'extralarge': 'XL', 'extra large': 'XL',
    'xxl': 'XXL', '2xl': 'XXL',
    'xxxl': 'XXL', '3xl': 'XXL',
    'allsize': 'ALLSIZE', 'all size': 'ALLSIZE', 'all-size': 'ALLSIZE',
    'fitl': 'ALLSIZE', 'fit l': 'ALLSIZE', 'onesize': 'ALLSIZE',
    'standar': 'STD', 'standard': 'STD', 'std': 'STD', 'reguler': 'STD',
    'jumbo': 'JMB', 'jmb': 'JMB', 'big size': 'JMB', 'bigsize': 'JMB',
}

#: Kosakata warna Indonesia/Inggris → nama warna master (`rahaza_colors.name`).
COLOR_ALIASES = {
    'putih': 'putih', 'white': 'putih', 'broken white': 'putih', 'off white': 'putih',
    'hitam': 'hitam', 'black': 'hitam',
    'abu': 'abu-abu', 'abu abu': 'abu-abu', 'abu-abu': 'abu-abu', 'grey': 'abu-abu',
    'gray': 'abu-abu', 'silver': 'abu-abu',
    'navy': 'navy', 'dongker': 'navy', 'navy blue': 'navy',
    'biru': 'biru', 'blue': 'biru',
    'merah': 'merah', 'red': 'merah', 'maroon': 'maroon', 'marun': 'maroon',
    'hijau': 'hijau', 'green': 'hijau', 'army': 'hijau', 'olive': 'hijau',
    'kuning': 'kuning', 'yellow': 'kuning', 'butter yellow': 'kuning', 'mustard': 'kuning',
    'coklat': 'coklat', 'brown': 'coklat', 'mocca': 'coklat', 'mocha': 'coklat',
    'krem': 'krem', 'cream': 'krem', 'beige': 'krem', 'khaki': 'krem',
    'pink': 'pink', 'rose': 'pink', 'dusty pink': 'pink', 'peach': 'pink',
    'ungu': 'ungu', 'purple': 'ungu', 'lilac': 'ungu', 'lavender': 'ungu',
    'orange': 'orange', 'oren': 'orange',
    'tosca': 'tosca', 'teal': 'tosca', 'mint': 'tosca',
}


def norm(s) -> str:
    """Turunkan teks ke bentuk banding: huruf kecil, tanpa tanda baca."""
    return _PUNCT.sub(' ', str(s or '').lower()).strip()


def tokens(s, *, drop_stopwords: bool = True) -> set:
    out = {t for t in norm(s).split() if len(t) > 1}
    if drop_stopwords:
        out -= STOPWORDS
    return out


#: Token yang menyatakan ATRIBUT (warna/ukuran), bukan identitas produk.
#: Wajib dibuang dari perbandingan NAMA karena warna & ukuran sudah dinilai
#: terpisah. Kalau tidak: variasi "POLKA WHITE, XL" akan "mirip nama" dengan
#: SETIAP varian ber-ukuran XL di master — keyakinan naik tanpa alasan, dan
#: mesin mengusulkan barang yang sama sekali berbeda dengan percaya diri.
_ATTR_TOKENS = (
    {t for k in SIZE_ALIASES for t in k.split()}
    | {v.lower() for v in SIZE_ALIASES.values()}
    | {t for k in COLOR_ALIASES for t in k.split()}
    | {v.lower() for v in COLOR_ALIASES.values()}
)


def identity_tokens(s) -> set:
    """Token yang benar-benar membedakan PRODUK (tanpa warna/ukuran/kata umum)."""
    return {t for t in tokens(s) if t not in _ATTR_TOKENS and not t.isdigit()}


def parse_variation(text) -> dict:
    """Baca variasi platform → ``{'color', 'size', 'raw_parts'}``.

    Contoh nyata dari ekspor TikTok:
      * ``'POLKA WHITE, XL'``                        → color='putih', size='XL'
      * ``'BLACK, XL (LD 120 CM), PAKAI KARET'``     → color='hitam', size='XL'
      * ``'BUTTER YELLOW'``                          → color='kuning', size=None

    Yang TIDAK dilakukan: menebak ukuran dari angka bebas (``LD 110cm`` adalah
    lingkar dada, bukan ukuran) — menebak di sini berarti barang salah dikirim.
    """
    raw = str(text or '')
    parts = [p.strip() for p in re.split(r'[,;/|]+', raw) if p.strip()]
    color = None
    size = None
    for p in parts:
        base = re.sub(r'\(.*?\)', ' ', p)          # buang keterangan dalam kurung
        n = norm(base)
        if size is None:
            for tok in (n, n.replace(' ', '')):
                if tok in SIZE_ALIASES:
                    size = SIZE_ALIASES[tok]
                    break
            if size is None:
                for w in n.split():
                    if w in SIZE_ALIASES:
                        size = SIZE_ALIASES[w]
                        break
        if color is None:
            if n in COLOR_ALIASES:
                color = COLOR_ALIASES[n]
            else:
                for alias, canon_name in COLOR_ALIASES.items():
                    if alias in n and len(alias) > 2:
                        color = canon_name
                        break
    return {'color': color, 'size': size, 'raw_parts': parts}


# ══════════════════════════════════════════════════════════════════════════════
# KODE MODEL dari SKU penjual — keputusan owner 11 Nov 2026 ("Ya, semua rekomendasi")
# ══════════════════════════════════════════════════════════════════════════════
# Ekspor asli toko (Shopee GHS, TikTok Rayona): SKU penjual = NOMOR MODEL tanpa awalan CV
# ("1512" = model DA-1512), variasi = warna (+ ukuran): "Red Elegant, M / STANDAR".
# Mesin usulan nama (di bawah) mengabaikan SKU penjual: ia menebak model dari kemiripan kata
# judul ("celana" di judul MELA → model "Stela celana") dan warna lewat kamus warna umum
# ("Red Elegant" → merah → "Pita merah"). Pratinjau "Petakan otomatis" pada berkas asli menulis
# ±25 dari 39 tautan SALAH. Aturan sekarang:
#   * tautan OTOMATIS (impor, Petakan otomatis, Selesaikan massal) HANYA bila SKU penjual
#     menunjuk tepat SATU model master DAN warna + ukuran variasi menunjuk tepat SATU varian
#     model itu — warna dibandingkan dengan NAMA WARNA MODEL ITU SENDIRI, bukan kamus umum;
#   * tebakan dari judul tetap ditampilkan sebagai USULAN untuk dicek staf, tidak ditulis.
SUMBER_KODE = 'kode_model'
SUMBER_NAMA = 'nama'
METODE_KODE = 'kode_model'          # `marketing_sku_bridge.method` untuk tautan aturan ini

#: Keterangan ukuran yang BUKAN kode ukuran master ("M / STANDAR", "XL / JUMBO").
_KATA_UKURAN = frozenset({'standar', 'standard', 'std', 'reguler', 'regular', 'jumbo', 'jmb',
                          'big', 'bigsize', 'big size'})
_ALIAS_UKURAN = {'2xl': 'xxl', '3xl': 'xxxl', 'onesize': 'allsize', 'freesize': 'allsize',
                 'fitl': 'allsize'}
_AMBANG_MIRIP_WARNA = 0.9


async def kode_pool(db) -> dict:
    """Varian aktif per kode model + indeks kode tanpa awalan CV ("1512" → ["DA-1512"])."""
    models: dict = defaultdict(list)
    skus: dict = {}
    tails: dict = defaultdict(set)
    async for v in db[VARIANTS].find({'active': {'$ne': False}},
                                     {'_id': 0, 'id': 1, 'sku': 1, 'model_id': 1,
                                      'model_code': 1, 'model_name': 1, 'color_name': 1,
                                      'size_code': 1}):
        mc = str(v.get('model_code') or '').strip().upper()
        if not mc:
            continue
        models[mc].append(v)
        if v.get('sku'):
            skus[str(v['sku']).strip().upper()] = v
        tails[mc].add(mc)
        if '-' in mc:
            tails[mc.split('-', 1)[1]].add(mc)
    return {'models': dict(models), 'skus': skus,
            'tails': {k: sorted(s) for k, s in tails.items()}}


def _kode_ukuran(part_norm: str, sizes: dict) -> Optional[str]:
    """Kode ukuran MODEL INI yang disebut satu bagian variasi (``sizes``: norm → kode)."""
    k = part_norm.replace(' ', '')
    k = _ALIAS_UKURAN.get(k, k)
    if k in sizes:
        return sizes[k]
    if k.startswith('allsize') and 'allsize' in sizes:      # "All Size Fit to L"
        return sizes['allsize']
    return None


def _pilih_warna(warna: str, calon: list) -> tuple:
    """Satu varian yang warnanya = ``warna`` (sudah dinormalkan) → ``(varian|None, cara)``.

    Urutan: sama persis → frasa utuh termuat ("Bunga Emas" ⊂ "Digital Bunga Emas") → sangat
    mirip (salah ketik "Blue Elegan") → terjemahan kamus warna ("White" → "Putih"). Setiap
    langkah WAJIB menghasilkan tepat satu varian; lebih dari satu = ragu = tidak ditautkan.
    """
    nm = [(v, norm(v.get('color_name'))) for v in calon]
    nm = [(v, c) for v, c in nm if c]
    hit = [v for v, c in nm if c == warna]
    if len(hit) == 1:
        return hit[0], 'sama'
    if hit:
        return None, 'ganda'

    def _frasa(a: str, b: str) -> bool:
        return bool(re.search(r'(^| )' + re.escape(a) + r'($| )', b))

    hit = [v for v, c in nm if _frasa(warna, c) or _frasa(c, warna)]
    if len(hit) == 1:
        return hit[0], 'termuat'
    if hit:
        return None, 'ganda'
    skor = sorted(((difflib.SequenceMatcher(None, warna, c).ratio(), v) for v, c in nm),
                  key=lambda t: -t[0])
    if skor and skor[0][0] >= _AMBANG_MIRIP_WARNA and (
            len(skor) == 1 or skor[1][0] < _AMBANG_MIRIP_WARNA):
        return skor[0][1], 'mirip'
    kanon = COLOR_ALIASES.get(warna)
    if kanon:
        hit = [v for v, c in nm if c == norm(kanon)]
        if len(hit) == 1:
            return hit[0], 'terjemahan'
    return None, 'tidak_ada'


def cocok_kode_model(pool: dict, seller_sku, variation='', product_name='') -> dict:
    """SKU penjual + variasi → varian master PASTI, atau alasan kenapa tidak.

    Return ``{model_code, model_name, model_id, variant, warna, ukuran, cara, alasan}``.
    ``variant`` terisi hanya bila model DAN varian tunggal; ``model_code`` terisi bila SKU
    penjual menunjuk tepat satu model (meski variannya belum ada / ragu).
    """
    s_raw = str(seller_sku or '').strip()
    s = s_raw.upper()
    out = {'model_code': '', 'model_name': '', 'model_id': None, 'variant': None,
           'warna': '', 'ukuran': '', 'cara': '', 'alasan': ''}
    if not s:
        out['alasan'] = 'SKU penjual kosong'
        return out
    v = (pool.get('skus') or {}).get(s)
    if v:                                       # SKU penjual = SKU varian master lengkap
        out.update(model_code=str(v.get('model_code') or '').upper(),
                   model_name=v.get('model_name') or '', model_id=v.get('model_id'),
                   variant=v, warna=v.get('color_name') or '', ukuran=v.get('size_code') or '',
                   cara='sku_varian')
        return out
    codes = (pool.get('tails') or {}).get(s) or []
    if not codes:
        out['alasan'] = f"SKU penjual '{s_raw}' bukan kode model di master"
        return out
    if len(codes) > 1:
        out['alasan'] = f"SKU penjual '{s_raw}' cocok dengan beberapa model ({', '.join(codes)})"
        return out
    mc = codes[0]
    vs = pool['models'][mc]
    out.update(model_code=mc, model_name=vs[0].get('model_name') or '',
               model_id=vs[0].get('model_id'))
    sizes = {norm(x.get('size_code')).replace(' ', ''): x.get('size_code')
             for x in vs if x.get('size_code')}
    # "LUNARA - MOCA": nama model / kata pertama judul di depan warna bukan bagian warna
    awalan = [p for p in {norm(out['model_name']),
                          (norm(re.split(r'[-|(]', str(product_name or ''))[0]).split() or [''])[0]}
              if p]
    ukuran, warna = None, []
    for part in re.split(r'[,;/|]+', str(variation or '')):
        n = norm(re.sub(r'\(.*?\)', ' ', part))
        if not n:
            continue
        u = _kode_ukuran(n, sizes)
        if u:
            ukuran = ukuran or u
            continue
        if n in _KATA_UKURAN:
            continue
        for a in sorted(awalan, key=len, reverse=True):
            if n.startswith(a + ' '):
                n = n[len(a) + 1:].strip()
                break
        if n:
            warna.append(n)
    if ukuran is None:
        semua = sorted(set(sizes.values()))
        if len(semua) == 1:
            ukuran = semua[0]
        else:
            out['alasan'] = (f"ukuran tidak terbaca dari variasi '{variation}' "
                             f"(model {mc} punya {', '.join(semua)})")
            return out
    out['ukuran'] = ukuran
    calon = [x for x in vs if x.get('size_code') == ukuran]
    if not calon:
        out['alasan'] = f"model {mc} tidak punya ukuran {ukuran}"
        return out
    if not warna:
        if len(calon) == 1:
            out.update(variant=calon[0], warna=calon[0].get('color_name') or '', cara='satu_varian')
        else:
            out['alasan'] = f"warna tidak tertulis di variasi '{variation}'"
        return out
    out['warna'] = warna[0]
    hit, cara = _pilih_warna(warna[0], calon)
    if hit:
        out.update(variant=hit, cara=cara)
    elif cara == 'ganda':
        out['alasan'] = f"warna '{warna[0]}' cocok dengan lebih dari satu varian {mc} · {ukuran}"
    else:
        out['alasan'] = f"warna '{warna[0]}' tidak ada di model {mc} ({out['model_name']}) · {ukuran}"
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Daftar SKU platform yang BELUM tertaut master
# ══════════════════════════════════════════════════════════════════════════════
async def list_unmapped(db, *, account_id: str = None, q: str = None,
                        limit: int = 300) -> dict:
    """Kelompokkan SELURUH baris pesanan tak-tertaut per ``platform_sku_id``.

    Bukan per sesi impor: pertanyaan pemilik ("barang apa yang belum dikenal
    gudang?") menyangkut seluruh pesanan, bukan satu unggahan berkas.
    """
    query = {}
    if account_id:
        query['account_id'] = account_id
    groups: dict = {}
    async for o in db[ORDERS].find(query, {'_id': 0, 'items': 1, 'account_id': 1,
                                          'account_name': 1, 'order_date': 1,
                                          'purchase_channel': 1, 'status': 1,
                                          'order_id': 1, 'fg_material_id': 1,
                                          'sku_id': 1, 'quantity': 1}):
        for ln in (o.get('items') or []):
            if not isinstance(ln, dict) or ln.get('fg_material_id'):
                continue
            # G4 (audit Gudang 9 Nov 2026) — baris TANPA SKU platform (ekspor Shopee) dulu
            # dibuang di sini ⇒ "0 belum tertaut" padahal pesanannya tak tertaut. Sekarang
            # dikelompokkan per (toko, nama produk, variasi) dengan kunci `nv:…`.
            psid = _skuk.kunci_baris(ln, o.get('account_id'))
            if not psid:
                continue
            g = groups.setdefault(psid, {
                'platform_sku_id': psid, 'pcs': 0.0, 'orders': 0, 'value': 0.0,
                'sku_label': _skuk.label_kunci(psid) if _skuk.kunci_nama(psid) else psid,
                'key_kind': 'nama_variasi' if _skuk.kunci_nama(psid) else 'sku_platform',
                'product_name': ln.get('product_name_raw') or ln.get('product_name') or '',
                'variation': ln.get('variation_raw') or '',
                # 11 Nov 2026 — dasar tautan pasti "kode model" (lihat cocok_kode_model)
                'seller_sku': str(ln.get('seller_sku') or '').strip(),
                'account_id': o.get('account_id'), 'account_name': o.get('account_name') or '',
                'platform': o.get('purchase_channel') or '',
                'first_order_date': o.get('order_date'), 'last_order_date': o.get('order_date'),
                'sample_order_id': o.get('order_id'),
            })
            g['pcs'] += _f(ln.get('quantity') or ln.get('qty'))
            g['orders'] += 1
            g['value'] += _f(ln.get('sku_subtotal_after_discount') or ln.get('subtotal'))
            od = o.get('order_date')
            if od:
                if not g['first_order_date'] or str(od) < str(g['first_order_date']):
                    g['first_order_date'] = od
                if not g['last_order_date'] or str(od) > str(g['last_order_date']):
                    g['last_order_date'] = od

    rows = list(groups.values())
    if q:
        nq = norm(q)
        rows = [r for r in rows
                if nq in norm(r['product_name']) or nq in norm(r['variation'])
                or nq in r['platform_sku_id']]
    rows.sort(key=lambda r: -r['pcs'])
    total = len(rows)
    rows = rows[:max(1, int(limit or 300))]
    for r in rows:
        r['pcs'] = round(r['pcs'], 2)
        r['value'] = round(r['value'], 2)
    return {'rows': rows, 'total': total,
            'pcs_total': round(sum(r['pcs'] for r in rows), 2)}


# ══════════════════════════════════════════════════════════════════════════════
# Mesin usulan — melaporkan keyakinan, tidak menebak
# ══════════════════════════════════════════════════════════════════════════════
async def _candidate_pool(db, *, account_id: str = None) -> list:
    """Kumpulkan calon sasaran: item katalog (prioritas) + varian model internal."""
    pool = []
    iq = {'is_active': {'$ne': False}}
    if account_id:
        iq['account_id'] = account_id
    async for it in db[ITEMS].find(iq, {'_id': 0, 'id': 1, 'name': 1, 'sku': 1,
                                        'fg_material_id': 1, 'variant_id': 1,
                                        'model_id': 1, 'fg_color': 1, 'variant_sku': 1,
                                        'account_id': 1, 'category': 1,
                                        'stock_quantity': 1, 'platform_sku_ids': 1}):
        pool.append({
            'kind': 'catalog_item', 'target_id': it['id'],
            'label': it.get('name') or it.get('sku') or '',
            'sku': it.get('sku') or it.get('variant_sku') or '',
            'fg_material_id': it.get('fg_material_id'),
            'variant_id': it.get('variant_id'), 'model_id': it.get('model_id'),
            'color': it.get('fg_color') or '', 'stock': _f(it.get('stock_quantity')),
            'account_id': it.get('account_id'),
            'already_mapped': list(it.get('platform_sku_ids') or []),
        })
    async for v in db[VARIANTS].find({'active': {'$ne': False}},
                                     {'_id': 0, 'id': 1, 'sku': 1, 'model_name': 1,
                                      'model_id': 1, 'color_name': 1, 'size_code': 1}):
        pool.append({
            'kind': 'variant', 'target_id': v['id'],
            'label': f"{v.get('model_name') or ''} [{v.get('color_name') or ''} · {v.get('size_code') or ''}]".strip(),
            'sku': v.get('sku') or '', 'fg_material_id': None,
            'variant_id': v['id'], 'model_id': v.get('model_id'),
            'color': v.get('color_name') or '', 'size': v.get('size_code') or '',
            'stock': None, 'account_id': None, 'already_mapped': [],
        })
    return pool


def _score(cand: dict, name_toks: set, want_color: str, want_size: str) -> tuple:
    """Nilai kecocokan 0..1 + alasan yang bisa dibaca manusia.

    Bobot: kemiripan nama 0.60 · warna 0.25 · ukuran 0.15. Sengaja TIDAK ada
    bonus "asal ada": kandidat tanpa irisan nama sama sekali dinilai 0 supaya
    mesin tidak pernah mengusulkan barang acak dengan keyakinan tinggi.
    """
    cand_toks = identity_tokens(cand['label']) | identity_tokens(cand.get('sku'))
    if not cand_toks or not name_toks:
        return 0.0, []
    inter = name_toks & cand_toks
    name_sim = len(inter) / max(1, len(name_toks | cand_toks))
    if not inter:
        return 0.0, []

    reasons = [f"nama mirip ({len(inter)} kata: {', '.join(sorted(inter)[:4])})"]
    score = 0.60 * min(1.0, name_sim * 2.2)

    ccolor = norm(cand.get('color'))
    if want_color and ccolor:
        if want_color == ccolor or want_color in ccolor or ccolor in want_color:
            score += 0.25
            reasons.append(f"warna cocok ({cand.get('color')})")
        else:
            score -= 0.12
            reasons.append(f"warna BEDA (master: {cand.get('color')})")
    csize = str(cand.get('size') or '').upper()
    if not csize and cand.get('sku'):
        tail = str(cand['sku']).upper().rsplit('-', 1)
        if len(tail) == 2 and tail[1] in {'S', 'M', 'L', 'XL', 'XXL', 'ALLSIZE', 'STD', 'JMB'}:
            csize = tail[1]
    if want_size and csize:
        if want_size == csize:
            score += 0.15
            reasons.append(f"ukuran cocok ({csize})")
        else:
            score -= 0.10
            reasons.append(f"ukuran BEDA (master: {csize})")
    return max(0.0, min(1.0, round(score, 4))), reasons


async def _model_pool(db) -> list:
    """Daftar model master + token identitasnya (dihitung sekali per pemanggilan)."""
    out = []
    async for m in db.rahaza_models.find({'active': {'$ne': False}},
                                         {'_id': 0, 'id': 1, 'code': 1, 'name': 1,
                                          'category': 1}):
        out.append({'id': m['id'], 'code': m.get('code') or '', 'name': m.get('name') or '',
                    'category': m.get('category') or '', 'toks': identity_tokens(m.get('name'))})
    return out


async def _match_model(db, name_toks: set, *, models: list = None) -> dict:
    """Model master yang paling mirip nama produk platform (0 = tidak ada)."""
    models = models if models is not None else await _model_pool(db)
    best, best_s = None, 0.0
    for m in models:
        if not m['toks'] or not name_toks:
            continue
        inter = name_toks & m['toks']
        if not inter:
            continue
        s = len(inter) / max(1, len(name_toks | m['toks']))
        s = min(1.0, s * 1.6)
        if s > best_s:
            best, best_s = m, s
    if not best:
        return {}
    return {'model_id': best['id'], 'model_code': best['code'], 'model_name': best['name'],
            'category': best['category'], 'confidence': round(best_s, 4)}


def _usulan_kode(km: dict, seller_sku: str, parsed: dict) -> dict:
    """Hasil :func:`suggest` bila SKU penjual menunjuk satu model master (aturan 11 Nov)."""
    v = km.get('variant')
    mm = {'model_id': km.get('model_id'), 'model_code': km.get('model_code'),
          'model_name': km.get('model_name'), 'category': '', 'confidence': 1.0,
          'source': SUMBER_KODE, 'variant_exists': bool(v),
          'color_confirmed': bool(v), 'size_confirmed': bool(v),
          'match_confidence': 1.0 if v else 0.0, 'match_how': km.get('cara') or '',
          'color_text': km.get('warna') or '', 'size_code': km.get('ukuran') or ''}
    cands = []
    if v:
        mm['variant_id'] = v['id']
        mm['variant_sku'] = v.get('sku')
        cands.append({
            'kind': 'variant', 'target_id': v['id'],
            'label': (f"{v.get('model_name') or ''} [{v.get('color_name') or ''} · "
                      f"{v.get('size_code') or ''}]").strip(),
            'sku': v.get('sku') or '', 'fg_material_id': None, 'variant_id': v['id'],
            'model_id': v.get('model_id'), 'color': v.get('color_name') or '',
            'size': v.get('size_code') or '', 'stock': None, 'account_id': None,
            'already_mapped': [], 'confidence': 1.0,
            'reasons': [f"SKU penjual {seller_sku} = model {km.get('model_code')}",
                        f"warna {v.get('color_name')} ({km.get('cara')})",
                        f"ukuran {v.get('size_code')}"]})
        action = 'map'
        reason = (f"SKU penjual {seller_sku} = model {km.get('model_code')} "
                  f"({km.get('model_name')}); varian {v.get('sku')} cocok warna & ukurannya — "
                  'ditautkan pasti.')
    else:
        action = 'create_variant'
        reason = (f"SKU penjual {seller_sku} = model {km.get('model_code')} "
                  f"({km.get('model_name')}), tetapi {km.get('alasan')}. Buat variannya di model "
                  'itu atau petakan manual.')
    return {'parsed': {'color': parsed['color'], 'size': parsed['size']},
            'candidates': cands, 'best': cands[0] if cands else None,
            'model_match': mm, 'recommended_action': action, 'reason': reason,
            'auto_min_confidence': AUTO_MIN_CONFIDENCE}


async def suggest(db, *, product_name: str = '', variation: str = '',
                  account_id: str = None, limit: int = 8, pool: list = None,
                  models: list = None, seller_sku: str = '', kpool: dict = None) -> dict:
    """Usulkan sasaran pemetaan untuk satu SKU platform + **aksi yang disarankan**.

    Return::

        {parsed, candidates[], best, model_match, recommended_action, reason}

    `recommended_action` menjawab pertanyaan yang sebenarnya dihadapi pemakai:

    | Keadaan di master                        | Aksi            |
    |------------------------------------------|-----------------|
    | varian (model+warna+ukuran) SUDAH ada    | ``map``           |
    | model ada, varian warna/ukuran ini BELUM | ``create_variant``|
    | tidak ada yang mirip                     | ``create_master`` |

    Kandidat berkeyakinan 0 TIDAK dikembalikan — daftar kosong adalah jawaban
    yang sah, dan artinya "masternya belum ada, buat dulu" (bukan "coba tebak").

    11 Nov 2026 — bila ``seller_sku`` menunjuk tepat satu model master, model itu PASTI
    (``model_match.source = 'kode_model'``) dan tebakan nama tidak dipakai sama sekali.
    Tanpa itu, hasilnya tebakan nama (``source = 'nama'``): hanya usulan, tidak pernah
    ditautkan otomatis.
    """
    parsed = parse_variation(variation)
    if str(seller_sku or '').strip():
        kp = kpool if kpool is not None else await kode_pool(db)
        km = cocok_kode_model(kp, seller_sku, variation, product_name)
        if km['model_code']:
            return _usulan_kode(km, str(seller_sku).strip(), parsed)
    # Nama dibandingkan dengan token IDENTITAS saja (tanpa warna/ukuran) — atribut
    # sudah punya bobotnya sendiri di `_score`. Variasi TIDAK ikut ke token nama:
    # isinya memang atribut, dan memasukkannya membuat setiap varian ber-ukuran
    # sama terlihat "mirip".
    #
    # Judulnya dibersihkan lebih dulu (`clean_product_name`) karena setiap judul
    # marketplace diawali NAMA TOKO ("OUTFIT BOUTIQUE - ...") dan diakhiri kata
    # jualan. Kata-kata itu muncul di SEMUA produk toko tersebut, jadi kalau ikut
    # dihitung ia mengencerkan kemiripan: produk yang sebetulnya sama persis
    # dengan master jadi terlihat hanya 30% mirip.
    cleaned = clean_product_name(product_name) or product_name
    name_toks = identity_tokens(cleaned)
    want_color = norm(parsed['color']) if parsed['color'] else ''
    want_size = parsed['size'] or ''

    pool = pool if pool is not None else await _candidate_pool(db, account_id=None)
    scored = []
    for c in pool:
        s, reasons = _score(c, name_toks, want_color, want_size)
        if s <= 0:
            continue
        if account_id and c['kind'] == 'catalog_item' and c.get('account_id') != account_id:
            s = round(s * 0.85, 4)         # item toko lain masih boleh, tetapi turun
            reasons.append('item milik toko lain')
        scored.append({**c, 'confidence': s, 'reasons': reasons})
    scored.sort(key=lambda x: (-x['confidence'], x['kind'] != 'catalog_item'))
    top = scored[:max(1, int(limit or 8))]

    # ── Model mana yang cocok, dan apakah varian persisnya sudah ada? ──────────
    mm = await _match_model(db, name_toks, models=models)
    exact = None
    color_confirmed = size_confirmed = False
    if mm:
        vq = {'model_id': mm['model_id'], 'active': {'$ne': False}}
        if want_size:
            vq['size_code'] = want_size
        async for v in db[VARIANTS].find(vq, {'_id': 0, 'id': 1, 'sku': 1, 'color_name': 1,
                                              'size_code': 1}):
            vcolor = norm(v.get('color_name'))
            if want_color and vcolor:
                if not (want_color == vcolor or want_color in vcolor or vcolor in want_color):
                    continue
                color_confirmed = True
            exact = v
            size_confirmed = bool(want_size and str(v.get('size_code') or '').upper() == want_size)
            break
        mm['variant_exists'] = bool(exact)
        if exact:
            mm['variant_id'] = exact['id']
            mm['variant_sku'] = exact.get('sku')
        # Keyakinan pemetaan = nama-keluarga + warna + ukuran yang BENAR-BENAR
        # dikonfirmasi. Bila salah satunya tidak terbaca dari variasi platform,
        # keyakinannya turun — dan pemetaan otomatis menolak bekerja. Menebak
        # warna/ukuran di sini berarti barang salah kirim ke pembeli.
        base = 0.30 + 0.30 * mm.get('confidence', 0)
        if color_confirmed:
            base += 0.22
        if size_confirmed:
            base += 0.22
        mm['color_confirmed'] = color_confirmed
        mm['size_confirmed'] = size_confirmed
        mm['match_confidence'] = round(min(1.0, base), 4) if exact else 0.0
        mm['source'] = SUMBER_NAMA          # tebakan judul — usulan saja (keputusan 11 Nov)

    tebakan = (' Model ini DITEBAK dari judul produk (SKU penjual bukan kode model master) — '
               'periksa dulu sebelum menautkan.')
    if exact and mm.get('confidence', 0) >= 0.35:
        action, reason = 'map', (f"Varian {exact.get('sku')} sudah ada di master "
                                 f"({mm['model_name']}) — cukup ditautkan." + tebakan)
    elif mm and mm.get('confidence', 0) >= 0.35:
        action, reason = 'create_variant', (
            f"Model '{mm['model_name']}' sudah ada, tetapi varian "
            f"{parsed['color'] or '(warna?)'} · {want_size or 'ALLSIZE'} belum. "
            'Buat variannya lalu tautkan.' + tebakan)
    else:
        action, reason = 'create_master', ('Belum ada master yang mirip — buat model + '
                                           'varian baru dari SKU ini, lalu tautkan.')

    return {'parsed': {'color': parsed['color'], 'size': parsed['size']},
            'candidates': top, 'best': top[0] if top else None,
            'model_match': mm or None,
            'recommended_action': action, 'reason': reason,
            'auto_min_confidence': AUTO_MIN_CONFIDENCE}


# ══════════════════════════════════════════════════════════════════════════════
# Menautkan — satu pemetaan mengurus SEMUA pesanan
# ══════════════════════════════════════════════════════════════════════════════
async def ensure_catalog(db, account_id: str, user: dict = None) -> dict:
    """Ambil (atau buatkan) katalog jual milik satu toko. Idempoten."""
    cat = await db[CATALOGS].find_one({'account_id': account_id, 'is_active': {'$ne': False}},
                                      {'_id': 0})
    if cat:
        return cat
    acc = await db[ACCOUNTS].find_one({'id': account_id}, {'_id': 0}) or {}
    doc = {
        'id': _uid(), 'account_id': account_id,
        'account_name': acc.get('account_name') or acc.get('shop_name') or '',
        'platform': acc.get('platform') or '',
        'name': f"Katalog {acc.get('account_name') or 'Toko'}",
        'description': 'Dibuat otomatis oleh Jembatan SKU saat pemetaan pertama.',
        'is_active': True, 'item_count': 0, 'total_stock': 0.0,
        'low_stock_count': 0, 'out_of_stock_count': 0,
        'created_at': _now(), 'updated_at': _now(),
        'created_by': (user or {}).get('id', 'system'),
        'created_via': 'sku_bridge',
    }
    await db[CATALOGS].insert_one(doc)
    doc.pop('_id', None)
    return doc


async def ensure_catalog_item_for_variant(db, *, account_id: str, variant_id: str,
                                          user: dict = None) -> tuple:
    """Pastikan varian internal punya item katalog di toko ini → ``(item, err)``.

    Rantainya memakai SSOT yang sudah ada, bukan tulisan dokumen mentah:
    ``ensure_fg_material`` (varian → master FG) lalu ``create_item_from_fg``
    (master FG → item katalog, lengkap kategori/HPP/harga resmi/stok jual).
    """
    from utils.variant_ssot import ensure_fg_material
    from routes.marketing_catalog_items import create_item_from_fg

    variant = await db[VARIANTS].find_one({'id': variant_id}, {'_id': 0})
    if not variant:
        return None, (404, f"Varian '{variant_id}' tidak ditemukan.")
    try:
        fg = await ensure_fg_material(db, variant, user=user)
    except Exception as e:  # noqa: BLE001
        logger.exception('[sku-bridge] ensure_fg_material gagal varian=%s', variant_id)
        return None, (400, f'Master FG untuk varian ini gagal disiapkan: {e}')
    if not fg or not fg.get('id'):
        return None, (400, 'Master FG untuk varian ini tidak bisa disiapkan.')

    existing = await db[ITEMS].find_one({'account_id': account_id,
                                        'fg_material_id': fg['id']}, {'_id': 0})
    if existing:
        return existing, None

    catalog = await ensure_catalog(db, account_id, user=user)
    doc, err = await create_item_from_fg(db, catalog, fg['id'], {}, user or {})
    if err:
        # sudah ada di katalog itu (409) → ambil dokumennya, bukan gagal
        found = await db[ITEMS].find_one({'catalog_id': catalog['id'],
                                         'fg_material_id': fg['id']}, {'_id': 0})
        if found:
            return found, None
        return None, err
    return doc, None


async def _resolve_target(db, *, catalog_item_id: str = None, variant_id: str = None,
                          fg_material_id: str = None, account_id: str = None,
                          user: dict = None) -> tuple:
    """Jadikan sasaran apa pun menjadi satu item katalog + FG → ``(target, err)``."""
    if catalog_item_id:
        it = await db[ITEMS].find_one({'id': catalog_item_id}, {'_id': 0})
        if not it:
            return None, (404, f"Item katalog '{catalog_item_id}' tidak ditemukan.")
        if not it.get('fg_material_id'):
            return None, (400, f"Item katalog '{it.get('name')}' belum tertaut master FG — "
                               'perbaiki tautannya dulu di Manajemen Katalog.')
        return it, None

    if variant_id:
        if not account_id:
            return None, (400, 'account_id (toko) wajib saat memetakan ke varian internal.')
        it, err = await ensure_catalog_item_for_variant(
            db, account_id=account_id, variant_id=variant_id, user=user)
        return (it, None) if it else (None, err)

    if fg_material_id:
        fg = await db[MATERIALS].find_one({'id': fg_material_id}, {'_id': 0})
        if not fg:
            return None, (404, f"Master FG '{fg_material_id}' tidak ditemukan.")
        if fg.get('variant_id') and account_id:
            it, err = await ensure_catalog_item_for_variant(
                db, account_id=account_id, variant_id=fg['variant_id'], user=user)
            if it:
                return it, None
        return {'id': None, 'fg_material_id': fg['id'], 'name': fg.get('name'),
                'sku': fg.get('code'), 'variant_id': fg.get('variant_id'),
                'model_id': fg.get('model_id'), 'hpp': _f(fg.get('hpp'))}, None

    return None, (400, 'Pilih sasaran: catalog_item_id, variant_id, atau fg_material_id.')


async def _backfill_by_name_key(db, key: str, target: Optional[dict]) -> int:
    """G4 — terapkan pemetaan berkunci nama+variasi ke pesanan LAMA (dan retur Marketing
    yang belum tertaut). ``target=None`` = lepas tautan. Idempoten."""
    acc = _skuk.akun_kunci(key)
    q = {'account_id': acc} if acc else {}
    touched = 0
    async for o in db[ORDERS].find(q, {'_id': 0, 'id': 1, 'items': 1, 'account_id': 1}):
        items = o.get('items') or []
        changed = False
        for ln in items:
            if not isinstance(ln, dict) or str(ln.get('platform_sku_id') or '').strip():
                continue
            if _skuk.kunci_baris(ln, o.get('account_id')) != key:
                continue
            if target is None:
                if ln.get('master_link_source') not in ('sku_bridge', 'sku_map'):
                    continue
                ln.update({'catalog_item_id': None, 'fg_material_id': None, 'variant_id': None,
                           'master_link_source': 'unlinked'})
            else:
                if ln.get('fg_material_id') == target.get('fg_material_id') and ln.get(
                        'catalog_item_id') == target.get('id'):
                    continue
                ln.update({'catalog_item_id': target.get('id'),
                           'fg_material_id': target.get('fg_material_id'),
                           'variant_id': target.get('variant_id'),
                           'model_id': target.get('model_id'),
                           'master_link_source': 'sku_bridge', 'linked_at': _now()})
                if ln.get('hpp_snapshot') is None and _f(target.get('hpp')) > 0:
                    ln['hpp_snapshot'] = _f(target.get('hpp'))
            changed = True
        if changed:
            await db[ORDERS].update_one({'id': o['id']},
                                        {'$set': {'items': items, 'updated_at': _now()}})
            touched += 1
    # retur Marketing yang menunggu tautan barang (nama+variasi sama, toko sama)
    if target is not None and target.get('id'):
        async for r in db['marketing_returns'].find(
                {**q, 'catalog_item_id': {'$in': [None, '']}},
                {'_id': 0, 'id': 1, 'product': 1, 'product_name': 1, 'variation': 1,
                 'account_id': 1}):
            if _skuk.kunci_baris({'product_name': r.get('product') or r.get('product_name'),
                                  'variation': r.get('variation')},
                                 r.get('account_id')) != key:
                continue
            await db['marketing_returns'].update_one({'id': r['id']}, {'$set': {
                'catalog_item_id': target.get('id'), 'link_source': 'sku_bridge',
                'updated_at': _now()}})
    return touched


async def _backfill_orders(db, psid: str, target: dict) -> int:
    """Tautkan SEMUA baris pesanan ber-``platform_sku_id`` ini. Idempoten."""
    if _skuk.kunci_nama(psid):
        return await _backfill_by_name_key(db, psid, target)
    res = await db[ORDERS].update_many(
        {'items.platform_sku_id': psid},
        {'$set': {
            'items.$[it].catalog_item_id': target.get('id'),
            'items.$[it].fg_material_id': target.get('fg_material_id'),
            'items.$[it].variant_id': target.get('variant_id'),
            'items.$[it].model_id': target.get('model_id'),
            'items.$[it].master_link_source': 'sku_bridge',
            'items.$[it].linked_at': _now(),
            'updated_at': _now(),
        }},
        array_filters=[{'it.platform_sku_id': psid}],
    )
    # 2026-11-06 (Tahap 2, paket HPP): HPP baris pesanan = biaya yang DIBEKUKAN saat pesanan masuk.
    # Memetakan ulang SKU dulu menimpa snapshot dengan HPP katalog HARI INI (marjin bulan lalu ikut
    # berubah). Sekarang snapshot hanya diisi bila baris itu belum punya.
    if _f(target.get('hpp')) > 0:
        await db[ORDERS].update_many(
            {'items.platform_sku_id': psid},
            {'$set': {'items.$[it].hpp_snapshot': _f(target.get('hpp'))}},
            array_filters=[{'it.platform_sku_id': psid, 'it.hpp_snapshot': None}],
        )
    return int(res.modified_count or 0)


async def apply_mapping(db, platform_sku_id: str, *, catalog_item_id: str = None,
                        variant_id: str = None, fg_material_id: str = None,
                        account_id: str = None, user: dict = None,
                        method: str = 'manual', confidence: float = None,
                        product_name: str = '', variation: str = '') -> dict:
    """Petakan satu SKU platform → master, lalu tautkan SEMUA pesanannya.

    Idempoten: memanggil dua kali tidak menggandakan apa pun.
    """
    psid = str(platform_sku_id or '').strip()
    if not psid:
        raise ValueError('platform_sku_id wajib diisi.')

    if not account_id and _skuk.kunci_nama(psid):
        account_id = _skuk.akun_kunci(psid)
    if not account_id:
        o = await db[ORDERS].find_one({'items.platform_sku_id': psid},
                                      {'_id': 0, 'account_id': 1})
        account_id = (o or {}).get('account_id')

    target, err = await _resolve_target(
        db, catalog_item_id=catalog_item_id, variant_id=variant_id,
        fg_material_id=fg_material_id, account_id=account_id, user=user)
    if err:
        return {'ok': False, 'status': err[0], 'message': err[1]}

    bridge = {
        'platform_sku_id': psid,
        'account_id': account_id,
        'catalog_item_id': target.get('id'),
        'fg_material_id': target.get('fg_material_id'),
        'variant_id': target.get('variant_id'),
        'model_id': target.get('model_id'),
        'fg_code': target.get('sku') or target.get('fg_code') or '',
        'target_name': target.get('name') or '',
        'product_name_sample': product_name or '',
        'variation_sample': variation or '',
        'method': method,
        'confidence': None if confidence is None else round(_f(confidence), 4),
        'active': True,
        'updated_at': _now(),
        'mapped_by': (user or {}).get('name') or (user or {}).get('email') or 'system',
    }
    await db[BRIDGE].update_one(
        {'platform_sku_id': psid},
        {'$set': bridge, '$setOnInsert': {'id': _uid(), 'created_at': _now()}},
        upsert=True)

    # B-2 — jalur warisan tetap dihidupi supaya impor berikutnya ikut tertaut.
    # G4 — kunci nama+variasi disimpan di `bridge_keys` (bukan SKU platform).
    if target.get('id'):
        _fld = 'bridge_keys' if _skuk.kunci_nama(psid) else 'platform_sku_ids'
        await db[ITEMS].update_one({'id': target['id']},
                                   {'$addToSet': {_fld: psid},
                                    '$set': {'updated_at': _now()}})

    orders_updated = await _backfill_orders(db, psid, target)
    saved = await db[BRIDGE].find_one({'platform_sku_id': psid}, {'_id': 0})
    return {'ok': True, 'bridge': saved, 'orders_updated': orders_updated,
            'target': {'kind': 'catalog_item' if target.get('id') else 'fg_material',
                       'id': target.get('id'), 'name': target.get('name'),
                       'sku': target.get('sku'),
                       'fg_material_id': target.get('fg_material_id')},
            'message': (f"SKU {psid} ditautkan ke '{target.get('name')}' — "
                        f"{orders_updated} pesanan ikut diperbarui.")}


async def remove_mapping(db, platform_sku_id: str, *, user: dict = None) -> dict:
    """Lepas pemetaan + kosongkan tautan pada baris pesanannya (jejak tetap)."""
    psid = str(platform_sku_id or '').strip()
    b = await db[BRIDGE].find_one({'platform_sku_id': psid}, {'_id': 0})
    if not b:
        return {'ok': False, 'status': 404, 'message': f'Pemetaan {psid} tidak ada.'}
    if _skuk.kunci_nama(psid):
        if b.get('catalog_item_id'):
            await db[ITEMS].update_one({'id': b['catalog_item_id']},
                                       {'$pull': {'bridge_keys': psid}})
        n = await _backfill_by_name_key(db, psid, None)
        await db[BRIDGE].delete_one({'platform_sku_id': psid})
        return {'ok': True, 'orders_updated': n,
                'message': f'Pemetaan dilepas; {n} pesanan dikembalikan ke tak-tertaut.'}
    if b.get('catalog_item_id'):
        await db[ITEMS].update_one({'id': b['catalog_item_id']},
                                   {'$pull': {'platform_sku_ids': psid}})
    res = await db[ORDERS].update_many(
        {'items.platform_sku_id': psid},
        {'$set': {'items.$[it].catalog_item_id': None,
                  'items.$[it].fg_material_id': None,
                  'items.$[it].variant_id': None,
                  'items.$[it].master_link_source': 'unlinked',
                  'updated_at': _now()}},
        array_filters=[{'it.platform_sku_id': psid}])
    await db[BRIDGE].delete_one({'platform_sku_id': psid})
    return {'ok': True, 'orders_updated': int(res.modified_count or 0),
            'message': f'Pemetaan {psid} dilepas; {res.modified_count} pesanan dikembalikan ke tak-tertaut.'}


async def auto_map(db, *, min_confidence: float = AUTO_MIN_CONFIDENCE,
                   limit: int = 100, account_id: str = None,
                   user: dict = None, dry_run: bool = True) -> dict:
    """Petakan otomatis HANYA yang keyakinannya ≥ ambang. Sisanya dilaporkan.

    `dry_run=True` (bawaan) tidak menulis apa pun — pemilik melihat dulu apa yang
    akan terjadi. Menebak diam-diam di sini = barang salah kirim.
    """
    min_confidence = max(0.5, min(1.0, _f(min_confidence, AUTO_MIN_CONFIDENCE)))
    un = await list_unmapped(db, account_id=account_id, limit=max(1, int(limit or 100)))
    pool = await _candidate_pool(db, account_id=None)
    models = await _model_pool(db)
    kpool = await kode_pool(db)

    applied, skipped = [], []
    for row in un['rows']:
        sg = await suggest(db, product_name=row['product_name'], variation=row['variation'],
                          account_id=row.get('account_id'), limit=1, pool=pool, models=models,
                          seller_sku=row.get('seller_sku') or '', kpool=kpool)
        mm = sg.get('model_match') or {}
        # Pemetaan OTOMATIS hanya untuk varian yang PERSIS ada DAN modelnya dipastikan
        # SKU penjual (keputusan owner 11 Nov 2026). Tebakan dari judul — seyakin apa pun
        # angkanya — hanya usulan bagi manusia: pada berkas asli ±25 dari 39 tebakan salah.
        conf = _f(mm.get('match_confidence'))
        if sg.get('recommended_action') != 'map' or not mm.get('variant_id') \
                or conf < min_confidence or mm.get('source') != SUMBER_KODE:
            best = sg.get('best')
            skipped.append({'platform_sku_id': row['platform_sku_id'],
                            'product_name': row['product_name'],
                            'variation': row['variation'], 'pcs': row['pcs'],
                            'best_confidence': round(conf, 3),
                            'best_label': mm.get('variant_sku') or (best['label'] if best else ''),
                            'recommended_action': sg.get('recommended_action'),
                            'reason': sg.get('reason')})
            continue
        entry = {'platform_sku_id': row['platform_sku_id'],
                 'product_name': row['product_name'], 'variation': row['variation'],
                 'pcs': row['pcs'], 'confidence': round(conf, 3),
                 'target_kind': 'variant', 'target_label': mm.get('model_name', ''),
                 'target_sku': mm.get('variant_sku') or ''}
        if not dry_run:
            res = await apply_mapping(
                db, row['platform_sku_id'], variant_id=mm['variant_id'],
                account_id=row.get('account_id'), user=user, method=METODE_KODE,
                confidence=conf, product_name=row['product_name'],
                variation=row['variation'])
            entry['ok'] = res.get('ok', False)
            entry['orders_updated'] = res.get('orders_updated', 0)
            entry['message'] = res.get('message', '')
            if not res.get('ok'):
                skipped.append({**entry, 'reason': res.get('message', 'gagal')})
                continue
        applied.append(entry)

    return {'ok': True, 'dry_run': dry_run, 'min_confidence': min_confidence,
            'candidates_examined': len(un['rows']), 'unmapped_total': un['total'],
            'applied': applied, 'applied_count': len(applied),
            'skipped': skipped[:80], 'skipped_count': len(skipped),
            'orders_updated': sum(_f(a.get('orders_updated')) for a in applied),
            'message': (('PRATINJAU — ' if dry_run else '')
                        + f'{len(applied)} SKU bisa dipetakan otomatis, '
                          f'{len(skipped)} perlu keputusan manusia.')}


async def tautkan_kode_model(db, *, account_id: str, order_query: dict = None,
                             user: dict = None) -> dict:
    """Tautkan PASTI baris pesanan yang belum tertaut lewat aturan kode model (11 Nov 2026).

    Dipanggil sesudah impor pesanan disimpan. Hanya baris ber-SKU penjual yang menunjuk tepat
    satu model + satu varian (:func:`cocok_kode_model`). Satu tautan = satu pemetaan jembatan,
    jadi pesanan lama & impor berikutnya ikut tertaut. Pemetaan yang sudah ada (keputusan
    manusia) TIDAK pernah ditimpa. Stok tidak disentuh (aturan keras no. 2).
    """
    q = {'account_id': account_id, **(order_query or {})}
    kunci: dict = {}
    async for o in db[ORDERS].find(q, {'_id': 0, 'items': 1}):
        for ln in (o.get('items') or []):
            if not isinstance(ln, dict) or ln.get('fg_material_id'):
                continue
            psid = _skuk.kunci_baris(ln, account_id)
            ss = str(ln.get('seller_sku') or '').strip()
            if not psid or not ss or psid in kunci:
                continue
            kunci[psid] = (ss, ln.get('variation_raw') or '',
                           ln.get('product_name_raw') or ln.get('product_name') or '')
    # `pesanan_diperbarui` = jumlah pembaruan per pemetaan (pesanan ber-2 SKU tertaut terhitung 2×)
    out = {'diperiksa': len(kunci), 'ditautkan': 0, 'pesanan_diperbarui': 0,
           'sudah_dipetakan': 0, 'gagal': 0}
    if not kunci:
        return out
    kp = await kode_pool(db)
    for psid, (ss, var, pname) in kunci.items():
        km = cocok_kode_model(kp, ss, var, pname)
        v = km.get('variant')
        if not v:
            continue
        if await db[BRIDGE].find_one({'platform_sku_id': psid, 'active': {'$ne': False}},
                                     {'_id': 0, 'platform_sku_id': 1}):
            out['sudah_dipetakan'] += 1
            continue
        res = await apply_mapping(db, psid, variant_id=v['id'], account_id=account_id,
                                  user=user, method=METODE_KODE, confidence=1.0,
                                  product_name=pname, variation=var)
        if res.get('ok'):
            out['ditautkan'] += 1
            out['pesanan_diperbarui'] += int(res.get('orders_updated') or 0)
        else:
            out['gagal'] += 1
            logger.warning('[sku-bridge] tautan kode model gagal %s → %s: %s',
                           psid, v.get('sku'), res.get('message'))
    return out


async def relink_orders(db, *, platform_sku_id: str = None) -> dict:
    """Terapkan ulang SEMUA pemetaan ke pesanan (pemulihan). Idempoten.

    Dipakai kalau pesanan lama masuk lagi lewat impor, atau tautan sempat
    terhapus: jembatan adalah sumber kebenaran, pesanan hanya cerminannya.
    """
    q = {'active': {'$ne': False}}
    if platform_sku_id:
        q['platform_sku_id'] = str(platform_sku_id).strip()
    touched = 0
    n_bridge = 0
    async for b in db[BRIDGE].find(q, {'_id': 0}):
        n_bridge += 1
        target = {'id': b.get('catalog_item_id'), 'fg_material_id': b.get('fg_material_id'),
                  'variant_id': b.get('variant_id'), 'model_id': b.get('model_id'),
                  'hpp': None}
        if b.get('catalog_item_id'):
            it = await db[ITEMS].find_one({'id': b['catalog_item_id']},
                                          {'_id': 0, 'hpp': 1, 'fg_material_id': 1,
                                           'variant_id': 1, 'model_id': 1})
            if it:
                target.update({'hpp': it.get('hpp'),
                               'fg_material_id': it.get('fg_material_id') or target['fg_material_id'],
                               'variant_id': it.get('variant_id') or target['variant_id'],
                               'model_id': it.get('model_id') or target['model_id']})
        if not target['fg_material_id']:
            continue
        touched += await _backfill_orders(db, b['platform_sku_id'], target)
    return {'ok': True, 'bridges': n_bridge, 'orders_updated': touched,
            'message': f'{n_bridge} pemetaan diterapkan ulang; {touched} pesanan disegarkan.'}


# ══════════════════════════════════════════════════════════════════════════════
# Kesehatan tautan — angka yang bisa dipertanggungjawabkan
# ══════════════════════════════════════════════════════════════════════════════
async def health(db, *, account_id: str = None) -> dict:
    from core.fulfillment_status import order_linkage, in_queue

    q = {'account_id': account_id} if account_id else {}
    lines = linked = 0
    pcs = pcs_linked = 0.0
    orders = ready = partial = blocked = 0
    queue = queue_ready = 0
    per_account: dict = defaultdict(lambda: {'orders': 0, 'lines': 0, 'linked': 0})
    unmapped_skus = set()

    async for o in db[ORDERS].find(q, {'_id': 0, 'items': 1, 'account_id': 1,
                                       'account_name': 1, 'fulfillment_status': 1,
                                       'fg_material_id': 1, 'quantity': 1, 'sku_id': 1}):
        orders += 1
        lk = order_linkage(o)
        lines += lk['lines']
        linked += lk['linked']
        pcs += lk['pcs']
        pcs_linked += lk['pcs_linked']
        if lk['ready']:
            ready += 1
        elif lk['linked']:
            partial += 1
        else:
            blocked += 1
        unmapped_skus.update(lk['unmapped_skus'])
        if in_queue(o.get('fulfillment_status')):
            queue += 1
            if lk['ready']:
                queue_ready += 1
        a = per_account[o.get('account_id') or '(tanpa toko)']
        a['orders'] += 1
        a['lines'] += lk['lines']
        a['linked'] += lk['linked']
        a['name'] = o.get('account_name') or ''

    bridges = await db[BRIDGE].count_documents({'active': {'$ne': False}})
    return {
        'orders': orders, 'lines': lines, 'lines_linked': linked,
        'lines_linked_pct': 0.0 if not lines else round(100.0 * linked / lines, 1),
        'pcs': round(pcs, 2), 'pcs_linked': round(pcs_linked, 2),
        'pcs_linked_pct': 0.0 if not pcs else round(100.0 * pcs_linked / pcs, 1),
        'orders_ready': ready, 'orders_partial': partial, 'orders_blocked': blocked,
        'queue_orders': queue, 'queue_ready': queue_ready,
        'queue_blocked': queue - queue_ready,
        'unmapped_sku_count': len(unmapped_skus),
        'bridge_mappings': bridges,
        'per_account': [{'account_id': k, **v} for k, v in
                        sorted(per_account.items(), key=lambda kv: -kv[1]['orders'])][:20],
    }


async def list_mappings(db, *, q: str = None, limit: int = 300) -> dict:
    rows = []
    async for b in db[BRIDGE].find({}, {'_id': 0}).sort('updated_at', -1).limit(int(limit or 300)):
        if q:
            nq = norm(q)
            if nq not in norm(b.get('target_name')) and nq not in b.get('platform_sku_id', '') \
                    and nq not in norm(b.get('product_name_sample')):
                continue
        if _skuk.kunci_nama(b['platform_sku_id']):
            cnt = None                     # dihitung saat diterapkan (kunci nama+variasi)
        else:
            cnt = await db[ORDERS].count_documents({'items.platform_sku_id': b['platform_sku_id']})
        rows.append({**b, 'orders_using': cnt,
                     'sku_label': _skuk.label_kunci(b['platform_sku_id'])})
    total = await db[BRIDGE].count_documents({})
    return {'rows': rows, 'total': total}


async def search_targets(db, *, q: str = '', account_id: str = None, limit: int = 40) -> dict:
    """Cari sasaran pemetaan (item katalog + varian) untuk pemilihan manual."""
    pool = await _candidate_pool(db, account_id=None)
    nq = norm(q)
    out = []
    for c in pool:
        if nq and nq not in norm(c['label']) and nq not in norm(c.get('sku')):
            continue
        out.append(c)
    out.sort(key=lambda c: (c['kind'] != 'catalog_item', norm(c['label'])))
    return {'rows': out[:max(1, int(limit or 40))], 'total': len(out)}




async def ensure_indexes(db) -> None:
    try:
        await db[BRIDGE].create_index('platform_sku_id', unique=True)
        await db[BRIDGE].create_index('account_id')
        await db[BRIDGE].create_index('fg_material_id')
        await db[BRIDGE].create_index([('updated_at', -1)])
    except Exception as e:  # noqa: BLE001
        logger.warning('[sku-bridge] index gagal dibuat: %s', e)


# ══════════════════════════════════════════════════════════════════════════════
# Membuat master DARI SKU platform — jalan keluar untuk SKU yang benar-benar baru
# ══════════════════════════════════════════════════════════════════════════════
# Kenapa ini WAJIB ada: mesin usulan yang jujur akan mengembalikan DAFTAR KOSONG
# untuk barang yang memang belum pernah ada di master (pada data hidup: 83 SKU
# blouse/oneset, sementara master hanya berisi 5 model kaos/hoodie/celana).
# Tanpa pintu ini, layar Jembatan SKU cuma bisa berkata "tidak ada yang cocok"
# dan pemilik berhenti di situ — ketidaksinkronannya tetap utuh. Pintu ini
# menyelesaikan rantainya: model → varian → master FG → item katalog → pemetaan,
# semuanya lewat SSOT yang sudah ada (bukan tulisan dokumen mentah).
_SHOP_PREFIX = re.compile(r"^\s*[A-Z0-9][A-Z0-9\s&.'-]{2,28}\s*[-–|:]\s*")


def clean_product_name(raw: str, *, max_len: int = 70) -> str:
    """Bersihkan judul marketplace jadi nama produk yang layak jadi master.

    Judul marketplace ditulis untuk mesin pencari, bukan untuk master data:
    ``'OUTFIT BOUTIQUE - RACHEL ONESET - Setelan celana kulot | setelan rayon
    premium | One set wanita kekinian | setelan rayon LD 110cm'``. Yang diambil:
    bagian **pertama** setelah nama toko (itulah nama artikelnya), dipangkas dari
    kata jualan & ukuran badan. Kalau hasilnya kosong, judul aslinya dipakai apa
    adanya — lebih baik nama panjang daripada master tanpa nama.
    """
    s = str(raw or '').strip()
    if not s:
        return ''
    s = _SHOP_PREFIX.sub('', s, count=1)
    s = s.split('|')[0].strip()
    parts = [p.strip() for p in re.split(r'\s+[-–]\s+', s) if p.strip()]
    if parts:
        s = parts[0] if len(parts[0].split()) >= 2 else ' '.join(parts[:2])
    s = re.sub(r'\b(ld|pb|lp)\s*\d+\s*(cm)?\b', '', s, flags=re.I)
    s = re.sub(r'\s{2,}', ' ', s).strip(' -|,')
    words = [w for w in s.split() if norm(w) not in _ATTR_TOKENS]
    s = ' '.join(words) if words else s
    return (s[:max_len].strip() or str(raw or '').strip()[:max_len]).title()


async def _resolve_or_create_color(db, color_name: str, *, user: dict = None) -> dict:
    """Ambil warna master; buat kalau memang belum ada (kode 3 huruf unik)."""
    name = str(color_name or '').strip()
    if not name:
        return {}
    doc = await db.rahaza_colors.find_one(
        {'name': {'$regex': f'^{re.escape(name)}$', '$options': 'i'}}, {'_id': 0})
    if doc:
        return doc
    canon_name = COLOR_ALIASES.get(norm(name))
    if canon_name:
        doc = await db.rahaza_colors.find_one(
            {'name': {'$regex': f'^{re.escape(canon_name)}$', '$options': 'i'}}, {'_id': 0})
        if doc:
            return doc
        name = canon_name
    base = re.sub(r'[^A-Z]', '', name.upper())[:3] or 'WRN'
    code, i = base, 1
    while await db.rahaza_colors.find_one({'code': code}, {'_id': 0, 'id': 1}):
        i += 1
        code = f'{base[:2]}{i}'
    doc = {'id': _uid(), 'code': code, 'name': name.title(), 'hex': '',
           'active': True, 'created_at': _now(), 'updated_at': _now(),
           'created_via': 'sku_bridge',
           'notes': 'Dibuat otomatis dari variasi SKU platform (Jembatan SKU).'}
    await db.rahaza_colors.insert_one(doc)
    doc.pop('_id', None)
    return doc


async def _resolve_size(db, size_code: str) -> dict:
    """Ambil ukuran master.

    TIDAK pernah membuat ukuran baru dari teks bebas — kosakata ukuran adalah
    keputusan master, bukan tebakan judul iklan. Bila ukuran tidak terbaca,
    dipakai ALLSIZE/STD supaya varian tetap lahir dengan identitas yang jelas.
    """
    code = str(size_code or '').strip().upper()
    if code:
        doc = await db.rahaza_sizes.find_one({'code': code}, {'_id': 0})
        if doc:
            return doc
    for fallback in ('ALLSIZE', 'STD'):
        doc = await db.rahaza_sizes.find_one({'code': fallback}, {'_id': 0})
        if doc:
            return doc
    return await db.rahaza_sizes.find_one({}, {'_id': 0}) or {}


async def create_master_and_map(db, platform_sku_id: str, *, product_name: str = '',
                                variation: str = '', account_id: str = None,
                                model_id: str = None, model_name: str = None,
                                category_text: str = None, color_name: str = None,
                                size_code: str = None, retail_price: float = 0,
                                hpp: float = 0, user: dict = None,
                                dry_run: bool = False) -> dict:
    """Buat master (model → varian → FG → item katalog) dari satu SKU platform,
    lalu petakan SKU itu ke sana. Idempoten: yang sudah ada dipakai ulang.

    `dry_run=True` mengembalikan RENCANA-nya tanpa menulis apa pun — pemilik
    melihat nama model, warna, ukuran, dan SKU yang akan lahir sebelum setuju.
    """
    from core import product_master as pm
    from routes.rahaza_variants import _make_sku

    psid = str(platform_sku_id or '').strip()
    if not psid:
        return {'ok': False, 'status': 400, 'message': 'platform_sku_id wajib diisi.'}

    # Lengkapi konteks dari pesanan bila layar tidak mengirimkannya.
    if _skuk.kunci_nama(psid) and (not (product_name or variation) or not account_id):
        account_id = account_id or _skuk.akun_kunci(psid)
        async for o in db[ORDERS].find({'account_id': account_id},
                                       {'_id': 0, 'items': 1, 'account_id': 1}):
            ln = next((x for x in (o.get('items') or []) if isinstance(x, dict)
                       and _skuk.kunci_baris(x, o.get('account_id')) == psid), None)
            if ln:
                product_name = product_name or ln.get('product_name_raw') or ''
                variation = variation or ln.get('variation_raw') or ''
                break
    if not (product_name or variation) or not account_id:
        o = await db[ORDERS].find_one({'items.platform_sku_id': psid},
                                      {'_id': 0, 'items': 1, 'account_id': 1})
        if o:
            account_id = account_id or o.get('account_id')
            for ln in (o.get('items') or []):
                if str(ln.get('platform_sku_id') or '') == psid:
                    product_name = product_name or ln.get('product_name_raw') \
                        or ln.get('product_name') or ''
                    variation = variation or ln.get('variation_raw') or ''
                    break
    if not account_id:
        return {'ok': False, 'status': 400,
                'message': 'Toko (account_id) tidak diketahui — SKU ini tidak ada di pesanan mana pun.'}

    parsed = parse_variation(variation)
    color_name = color_name or parsed['color'] or 'Lainnya'
    size_code = size_code or parsed['size'] or ''
    name = (model_name or clean_product_name(product_name) or f'Produk {psid[:8]}')

    # ── Model: pakai yang diminta → yang namanya sama → buat baru ─────────────
    model = None
    if model_id:
        model = await db.rahaza_models.find_one({'id': model_id}, {'_id': 0})
        if not model:
            return {'ok': False, 'status': 404, 'message': f"Model '{model_id}' tidak ditemukan."}
    if model is None:
        model = await db.rahaza_models.find_one(
            {'name': {'$regex': f'^{re.escape(name)}$', '$options': 'i'}}, {'_id': 0})

    cat = await pm.resolve_category_by_text(db, category_text or product_name or name,
                                            allow_create=False)
    if not cat:
        cat = await pm.get_category_by_code(db, 'LAINNYA') or {}

    plan = {'model': {'exists': bool(model),
                      'name': (model or {}).get('name') or name,
                      'code': (model or {}).get('code') or f"{(cat.get('sku_prefix') or 'OTH')}-XXXX",
                      'category': cat.get('name') or 'Lainnya'},
            'color': color_name, 'size': size_code or 'ALLSIZE',
            'platform_sku_id': psid, 'account_id': account_id,
            'source_title': product_name, 'source_variation': variation}
    if dry_run:
        return {'ok': True, 'dry_run': True, 'plan': plan,
                'message': (f"PRATINJAU — akan dipakai/dibuat model '{plan['model']['name']}' "
                            f"({plan['model']['category']}), varian {color_name} · "
                            f"{size_code or 'ALLSIZE'}, lalu SKU {psid} ditautkan.")}

    created = {'model': False, 'variant': False, 'color': False}
    if model is None:
        code = await pm.next_model_code(db, cat)
        model = {'id': _uid(), 'code': code, 'name': name,
                 'description': f'Dibuat dari SKU platform {psid} (Jembatan SKU).',
                 'active': True, 'retail_price': _f(retail_price), 'base_hpp': _f(hpp),
                 'hpp': _f(hpp), 'weight_gram': 0.0,
                 'created_at': _now(), 'updated_at': _now(),
                 'created_by': (user or {}).get('id', 'system'),
                 'created_via': 'sku_bridge', 'source_platform_sku_id': psid}
        model = pm.apply_category(model, cat)
        await db.rahaza_models.insert_one(model)
        model.pop('_id', None)
        created['model'] = True

    color = await _resolve_or_create_color(db, color_name, user=user)
    if color.get('created_via') == 'sku_bridge':
        created['color'] = True
    size = await _resolve_size(db, size_code)
    if not color or not size:
        return {'ok': False, 'status': 400,
                'message': 'Master warna/ukuran tidak bisa disiapkan — lengkapi dulu di Master Data.'}

    variant = await db[VARIANTS].find_one(
        {'model_id': model['id'], 'color_id': color['id'], 'size_id': size['id']}, {'_id': 0})
    if not variant:
        sku = _make_sku(model.get('code'), color.get('code'), size.get('code'))
        clash = await db[VARIANTS].find_one({'sku': sku}, {'_id': 0})
        if clash:
            variant = clash
        else:
            variant = {'id': _uid(), 'model_id': model['id'], 'model_code': model.get('code'),
                       'model_name': model.get('name'),
                       'size_id': size['id'], 'size_code': size.get('code'),
                       'color_id': color['id'], 'color_code': color.get('code'),
                       'color_name': color.get('name'), 'color_hex': color.get('hex', ''),
                       'sku': sku, 'barcode': '',
                       'notes': f'Dibuat dari SKU platform {psid} (Jembatan SKU).',
                       'active': True, 'created_at': _now(), 'updated_at': _now(),
                       'created_via': 'sku_bridge'}
            await db[VARIANTS].insert_one(variant)
            variant.pop('_id', None)
            created['variant'] = True

    res = await apply_mapping(db, psid, variant_id=variant['id'], account_id=account_id,
                              user=user, method='create_master', confidence=1.0,
                              product_name=product_name, variation=variation)
    if not res.get('ok'):
        return res
    res.update({'created': created,
                'model': {'id': model['id'], 'code': model.get('code'), 'name': model.get('name')},
                'variant': {'id': variant['id'], 'sku': variant.get('sku')},
                'message': (f"Master siap: {model.get('name')} · {variant.get('sku')} — "
                            f"SKU {psid} ditautkan, "
                            f"{res.get('orders_updated', 0)} pesanan diperbarui.")})
    return res


# ══════════════════════════════════════════════════════════════════════════════
# Penyelesaian MASSAL — supaya 82 SKU tidak harus diklik satu per satu
# ══════════════════════════════════════════════════════════════════════════════
#: Ambang kemiripan NAMA MODEL untuk boleh membuat varian di model yang sudah ada.
#: Lebih longgar daripada `AUTO_MIN_CONFIDENCE` (yang mengatur penulisan tautan
#: ke varian yang SUDAH ada) karena di sini yang lahir adalah data BARU milik
#: model itu — kalau modelnya salah, akibatnya varian nyasar, bukan barang salah
#: kirim. Tetap tidak boleh ditebak: di bawah ambang ⇒ dilempar ke manusia.
VARIANT_MIN_MODEL_CONFIDENCE = 0.65

BULK_ACTIONS = ('map', 'create_variant', 'create_master')


async def bulk_resolve(db, *, actions: tuple = ('map', 'create_variant'),
                       limit: int = 200, account_id: str = None,
                       user: dict = None, dry_run: bool = True) -> dict:
    """Selesaikan banyak SKU sekaligus, mengikuti aksi yang disarankan mesin.

    Kenapa perlu: pada data hidup ada **82** SKU tak-tertaut; 47 di antaranya
    hanya butuh *varian baru di model yang sudah dikenali*. Menyuruh pemilik
    mengklik 47 kali adalah cara paling pasti membuat fitur sinkronisasi tidak
    dipakai — dan ketidaksinkronan yang tidak diperbaiki sama saja dengan tidak
    punya fiturnya.

    Aturan yang dijaga:
      * `map` → hanya varian yang PERSIS ada & keyakinan ≥ :data:`AUTO_MIN_CONFIDENCE`.
      * `create_variant` → hanya bila nama model cocok ≥ :data:`VARIANT_MIN_MODEL_CONFIDENCE`;
        `model_id`-nya DIKIRIM eksplisit (tidak mengandalkan pencocokan nama lagi).
      * `create_master` → membuat model BARU; sengaja bukan bawaan, karena ia
        menambah master produk dan pemilik harus sadar melakukannya.
      * `dry_run=True` (bawaan) tidak menulis apa pun.
    """
    actions = tuple(a for a in (actions or ()) if a in BULK_ACTIONS) or ('create_variant',)
    un = await list_unmapped(db, account_id=account_id, limit=max(1, int(limit or 200)))
    pool = await _candidate_pool(db, account_id=None)
    models = await _model_pool(db)
    kpool = await kode_pool(db)

    applied, skipped = [], []
    created_models = created_variants = orders_touched = 0

    for row in un['rows']:
        sg = await suggest(db, product_name=row['product_name'], variation=row['variation'],
                          account_id=row.get('account_id'), limit=1, pool=pool, models=models,
                          seller_sku=row.get('seller_sku') or '', kpool=kpool)
        act = sg.get('recommended_action')
        mm = sg.get('model_match') or {}
        parsed = sg.get('parsed') or {}
        dari_kode = mm.get('source') == SUMBER_KODE
        base = {'platform_sku_id': row['platform_sku_id'], 'pcs': row['pcs'],
                'product_name': row['product_name'], 'variation': row['variation'],
                'action': act,
                'color': (mm.get('color_text') or parsed.get('color')) if dari_kode else parsed.get('color'),
                'size': (mm.get('size_code') or parsed.get('size')) if dari_kode else parsed.get('size'),
                'model_name': mm.get('model_name') or '', 'reason': sg.get('reason')}

        if act not in actions:
            skipped.append({**base, 'reason': f"aksi '{act}' tidak dipilih pada permintaan ini"})
            continue

        # Keputusan owner 11 Nov 2026 — tautan & varian baru di model yang SUDAH ADA hanya bila
        # modelnya dipastikan SKU penjual. Model hasil tebakan judul pernah menautkan MELA ke
        # "Stela celana" dan akan membuat varian nyasar di model yang salah.
        if act in ('map', 'create_variant') and not dari_kode:
            skipped.append({**base, 'reason': (
                'Model ditebak dari judul produk (SKU penjual bukan kode model master) — '
                'hanya usulan; periksa & petakan manual di tab SKU belum dikenal.')})
            continue

        if act == 'map':
            conf = _f(mm.get('match_confidence'))
            if not mm.get('variant_id') or conf < AUTO_MIN_CONFIDENCE:
                skipped.append({**base, 'confidence': round(conf, 3),
                                'reason': 'keyakinan varian belum cukup untuk ditautkan otomatis'})
                continue
            base['target_sku'] = mm.get('variant_sku') or ''
            base['confidence'] = round(conf, 3)
            if not dry_run:
                res = await apply_mapping(db, row['platform_sku_id'], variant_id=mm['variant_id'],
                                         account_id=row.get('account_id'), user=user,
                                         method=METODE_KODE, confidence=conf,
                                         product_name=row['product_name'],
                                         variation=row['variation'])
                if not res.get('ok'):
                    skipped.append({**base, 'reason': res.get('message', 'gagal')})
                    continue
                orders_touched += int(res.get('orders_updated') or 0)
                base['orders_updated'] = res.get('orders_updated', 0)
            applied.append(base)
            continue

        if act == 'create_variant':
            conf = _f(mm.get('confidence'))
            if not mm.get('model_id') or conf < VARIANT_MIN_MODEL_CONFIDENCE:
                skipped.append({**base, 'confidence': round(conf, 3),
                                'reason': ('nama model belum cukup mirip untuk membuat varian '
                                           'di model itu — perlu keputusan manusia')})
                continue
            base['confidence'] = round(conf, 3)
            # model dari SKU penjual: warna ditulis APA ADANYA dari variasi ("Flower Blue", bukan
            # kamus umum "biru"); ukuran harus terbaca dulu, kalau tidak → manusia.
            warna_baru = str(mm.get('color_text') or '').strip().title() or None
            ukuran_baru = mm.get('size_code') or None
            if not ukuran_baru:
                skipped.append({**base, 'reason': (sg.get('reason') or '')
                                + ' Ukuran belum terbaca — tidak dibuat otomatis.'})
                continue
            if dry_run:
                base['will_create'] = f"varian {warna_baru or parsed.get('color') or 'Lainnya'} · " \
                                      f"{ukuran_baru} di {mm.get('model_name')}"
            else:
                res = await create_master_and_map(
                    db, row['platform_sku_id'], product_name=row['product_name'],
                    variation=row['variation'], account_id=row.get('account_id'),
                    model_id=mm['model_id'], color_name=warna_baru, size_code=ukuran_baru,
                    user=user)
                if not res.get('ok'):
                    skipped.append({**base, 'reason': res.get('message', 'gagal')})
                    continue
                created_variants += 1 if (res.get('created') or {}).get('variant') else 0
                orders_touched += int(res.get('orders_updated') or 0)
                base.update({'target_sku': (res.get('variant') or {}).get('sku', ''),
                             'orders_updated': res.get('orders_updated', 0)})
            applied.append(base)
            continue

        # act == 'create_master'
        if dry_run:
            plan = await create_master_and_map(
                db, row['platform_sku_id'], product_name=row['product_name'],
                variation=row['variation'], account_id=row.get('account_id'),
                user=user, dry_run=True)
            base['will_create'] = (f"model BARU '{(plan.get('plan') or {}).get('model', {}).get('name', '')}'"
                                   f" + varian {parsed.get('color') or 'Lainnya'} · "
                                   f"{parsed.get('size') or 'ALLSIZE'}")
        else:
            res = await create_master_and_map(
                db, row['platform_sku_id'], product_name=row['product_name'],
                variation=row['variation'], account_id=row.get('account_id'), user=user)
            if not res.get('ok'):
                skipped.append({**base, 'reason': res.get('message', 'gagal')})
                continue
            created_models += 1 if (res.get('created') or {}).get('model') else 0
            created_variants += 1 if (res.get('created') or {}).get('variant') else 0
            orders_touched += int(res.get('orders_updated') or 0)
            base.update({'target_sku': (res.get('variant') or {}).get('sku', ''),
                         'model_name': (res.get('model') or {}).get('name', ''),
                         'orders_updated': res.get('orders_updated', 0)})
            # model yang baru lahir harus ikut dipertimbangkan SKU berikutnya,
            # kalau tidak, 6 varian dari 1 produk melahirkan 6 model kembar.
            models = await _model_pool(db)
            pool = await _candidate_pool(db, account_id=None)
        applied.append(base)

    return {'ok': True, 'dry_run': dry_run, 'actions': list(actions),
            'examined': len(un['rows']), 'unmapped_total': un['total'],
            'applied': applied, 'applied_count': len(applied),
            'skipped': skipped[:100], 'skipped_count': len(skipped),
            'created_models': created_models, 'created_variants': created_variants,
            'orders_updated': orders_touched,
            'message': (('PRATINJAU — ' if dry_run else '')
                        + f'{len(applied)} SKU diselesaikan '
                          f'({", ".join(actions)}), {len(skipped)} disisakan untuk manusia'
                        + ('' if dry_run else f'; {orders_touched} pesanan ikut tertaut'))}
