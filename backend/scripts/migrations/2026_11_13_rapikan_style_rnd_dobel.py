"""Migrasi 2026-11-13 (laporan R&D "ganti kode produk jadi dobel", owner: dibenarkan) — rapikan style R&D kembar.

KENAPA: sampai rilis ini sinkron master (`core.master_sync`, jalan tiap start backend + tombol Sinkron master)
mencari style R&D HANYA lewat kode produk. Bila kode style diubah di Style & Desain, kode produk diubah di Master
Produk, atau produk dipromosikan dengan kode lain, pencarian meleset dan sinkron membuat STYLE KEDUA (+ varian R&D
kedua) untuk produk yang sama; `rahaza_models.rnd_style_id` pindah ke style baru. Kode baru mencari lewat tautan,
jadi kembaran tidak bertambah — skrip ini merapikan yang SUDAH terlanjur ada.

Yang dilakukan per produk (`rahaza_models`) yang punya >1 style tertaut (`promoted_to_model_id` / `rnd_style_id`):
  * pilih SATU style yang dipertahankan (`pilih_yang_dipertahankan`): paling banyak data R&D sendiri (tech pack, HPP,
    sampel, pola, revisi manual, permintaan aksesoris/kreator, peluncuran) → paling lama dibuat;
  * data R&D milik kembaran (lihat KOLEKSI_STYLE) dipindah ke style itu (`style_id`); varian R&D per warna dipindah
    bila warna itu belum ada di style yang dipertahankan, selain itu diarsipkan; foto desain digabung;
  * kembaran: status Diarsipkan, tautan produk dilepas, `merged_into_style_id` = style yang dipertahankan (sinkron
    master melewatinya). Kodenya diberi akhiran `-DOBEL` HANYA bila kode itu dibutuhkan style yang dipertahankan
    (kode style unik);
  * style yang dipertahankan: kode & nama = master; `rahaza_models.rnd_style_id` menunjuk ke sana.
Juga: style tertaut tunggal yang kodenya ≠ kode master → kode disamakan (bila kode itu bebas).
Hanya DILAPORKAN (keputusan manual): style tertaut ke produk yang sudah tidak ada, satu style dipakai >1 produk,
produk yang SKU variannya tidak berawalan kode produk (kode pernah diganti tanpa SKU — butuh keputusan owner),
dan kode yang pernah diketik R&D di kembaran (bila staf ingin mengganti kode produk, lakukan lagi lewat Style &
Desain / Master Produk — sekarang SKU ikut berganti atau ditolak bila sudah dipakai).

Sifat: idempoten. Bawaan PRATINJAU. `--db` WAJIB sama dengan DB_NAME lingkungan (pengaman salah sasaran).
`--apply` menulis cadangan JSON (semua dokumen yang akan diubah) ke `--cadangan` lebih dulu, baru menulis.

Runbook (VPS, sesudah kode baru terpasang dan pratinjau disetujui owner):
    docker exec dahost-backend-1 sh -c 'python scripts/migrations/2026_11_13_rapikan_style_rnd_dobel.py --db "$DB_NAME"'
    docker exec dahost-backend-1 sh -c 'python scripts/migrations/2026_11_13_rapikan_style_rnd_dobel.py --db "$DB_NAME" --apply --cadangan /app/backups'
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

STYLES, MODELS, RND_VARIANTS = 'dewi_rnd_styles', 'rahaza_models', 'dewi_rnd_variants'
# Dokumen R&D yang menaut style lewat `style_id` (sama dengan `routes.dewi_rnd_styles.style_usage`)
KOLEKSI_STYLE = ('dewi_rnd_tech_packs', 'dewi_rnd_patterns', 'dewi_rnd_hpp', 'dewi_rnd_sample_requests',
                 'dewi_rnd_sample_costing', 'dewi_rnd_revisions', 'dewi_accessory_requests', 'dewi_kreator_requests',
                 'marketing_product_launches')
PELAKU = 'migrasi 2026-11-13 rapikan style R&D dobel'


def _u(v) -> str:
    return str(v or '').strip().upper()


def _now():
    return datetime.now(timezone.utc)


def kelompok_tertaut(models: dict, styles: list) -> dict:
    """{model_id: [style, …]} style yang tertaut ke tiap model (`promoted_to_model_id` atau `rnd_style_id`), tanpa
    kembaran yang sudah digabung. Fungsi murni."""
    by_id = {s['id']: s for s in styles}
    out: dict = {}
    for s in styles:
        if s.get('merged_into_style_id') or not s.get('promoted_to_model_id'):
            continue
        out.setdefault(s['promoted_to_model_id'], []).append(s)
    for mid, m in models.items():
        s = by_id.get(m.get('rnd_style_id'))
        if s and not s.get('merged_into_style_id') and s.get('promoted_to_model_id') in (None, '', mid) \
                and s not in out.get(mid, []):
            out.setdefault(mid, []).append(s)
    return out


def pilih_yang_dipertahankan(model: dict, grup: list, skor_data: dict) -> dict:
    """Style yang dipertahankan: data R&D sendiri terbanyak → kode = kode master → paling lama dibuat → id."""
    kode = _u(model.get('code'))
    return sorted(grup, key=lambda s: (-int(skor_data.get(s['id'], 0)), _u(s.get('style_code')) != kode,
                                       str(s.get('created_at') or ''), str(s['id'])))[0]


def kode_bebas(dasar: str, terpakai: set) -> str:
    """`DASAR-DOBEL`, `DASAR-DOBEL2`, … yang belum dipakai (fungsi murni)."""
    n, kode = 1, f'{dasar}-DOBEL'
    while kode in terpakai:
        n += 1
        kode = f'{dasar}-DOBEL{n}'
    return kode


async def _skor_data(db, style_ids: list) -> dict:
    skor = {sid: 0 for sid in style_ids}
    for coll in KOLEKSI_STYLE:
        q = {'style_id': {'$in': style_ids}}
        if coll == 'dewi_rnd_revisions':
            q['source'] = {'$ne': 'auto'}          # revisi otomatis tercatat di semua style; yang manual = kerja R&D
        async for d in db[coll].find(q, {'_id': 0, 'style_id': 1}):
            skor[d['style_id']] = skor.get(d['style_id'], 0) + 1
    return skor


async def rencana(db) -> dict:
    models = {m['id']: m for m in await db[MODELS].find({}, {'_id': 0, 'id': 1, 'code': 1, 'name': 1, 'active': 1,
                                                                  'rnd_style_id': 1, 'rnd_style_code': 1}).to_list(10000)}
    styles = await db[STYLES].find({}, {'_id': 0}).to_list(20000)
    grup = kelompok_tertaut(models, styles)
    terpakai = {_u(s.get('style_code')) for s in styles}
    res = {'gabung': [], 'samakan_kode': [], 'konflik': [], 'yatim': [], 'style_dipakai_banyak_produk': [],
           'sku_tidak_berawalan_kode': []}
    for s in styles:
        pm_id = s.get('promoted_to_model_id')
        if pm_id and pm_id not in models and not s.get('merged_into_style_id'):
            res['yatim'].append({'style_id': s['id'], 'style_code': s.get('style_code'), 'model_id': pm_id})
    pakai: dict = {}
    for m in models.values():
        if m.get('rnd_style_id'):
            pakai.setdefault(m['rnd_style_id'], []).append(m.get('code'))
    res['style_dipakai_banyak_produk'] = [{'style_id': k, 'produk': v} for k, v in pakai.items() if len(v) > 1]
    for mid, lst in grup.items():
        m = models.get(mid)
        if not m:
            continue
        kode = _u(m.get('code'))
        if len(lst) == 1:
            s = lst[0]
            if kode and _u(s.get('style_code')) != kode:
                if kode in terpakai:
                    res['konflik'].append({'model': m.get('code'), 'style_id': s['id'], 'style_code': s.get('style_code'),
                                           'alasan': 'kode master dipegang style lain'})
                else:
                    res['samakan_kode'].append({'model_id': mid, 'model': m.get('code'), 'style_id': s['id'],
                                                'dari': s.get('style_code'), 'ke': kode})
                    terpakai.discard(_u(s.get('style_code')))
                    terpakai.add(kode)
            continue
        skor = await _skor_data(db, [s['id'] for s in lst])
        tetap = pilih_yang_dipertahankan(m, lst, skor)
        kembar = [s for s in lst if s['id'] != tetap['id']]
        ganti_kode = {}
        for d in kembar:
            if _u(d.get('style_code')) == kode:
                baru = kode_bebas(kode, terpakai)
                terpakai.add(baru)
                ganti_kode[d['id']] = baru
        pemegang_lain = kode in terpakai and _u(tetap.get('style_code')) != kode and \
            not any(_u(d.get('style_code')) == kode for d in kembar)
        res['gabung'].append({
            'model_id': mid, 'model': m.get('code'), 'nama': m.get('name'), 'aktif': m.get('active') is not False,
            'tetap': {'id': tetap['id'], 'kode': tetap.get('style_code'), 'data_rnd': skor.get(tetap['id'], 0)},
            'kembar': [{'id': d['id'], 'kode': d.get('style_code'), 'nama': d.get('style_name'),
                        'data_rnd': skor.get(d['id'], 0), 'kode_arsip': ganti_kode.get(d['id'], d.get('style_code'))}
                       for d in kembar],
            'kode_tetap_baru': None if pemegang_lain else kode,
            'kode_pernah_diketik': sorted({_u(s.get('style_code')) for s in lst} - {kode}),
        })
        if pemegang_lain:
            res['konflik'].append({'model': m.get('code'), 'style_id': tetap['id'], 'style_code': tetap.get('style_code'),
                                   'alasan': 'kode master dipegang style lain (bukan kembaran) — kode tidak disamakan'})
        elif _u(tetap.get('style_code')) != kode:
            terpakai.discard(_u(tetap.get('style_code')))
            terpakai.add(kode)
    # info: SKU varian yang tidak berawalan kode produk (kode pernah diganti tanpa ikut mengganti SKU)
    async for v in db.rahaza_model_variants.find({'active': {'$ne': False}}, {'_id': 0, 'model_id': 1, 'sku': 1}):
        m = models.get(v.get('model_id'))
        if m and m.get('code') and not _u(v.get('sku')).startswith(_u(m['code']) + '-'):
            res['sku_tidak_berawalan_kode'].append({'model': m.get('code'), 'sku': v.get('sku')})
    return res


async def _cadangan(db, r: dict, folder: str) -> str:
    sids = {g['tetap']['id'] for g in r['gabung']} | {d['id'] for g in r['gabung'] for d in g['kembar']} | \
        {x['style_id'] for x in r['samakan_kode']}
    dup = [d['id'] for g in r['gabung'] for d in g['kembar']]
    data = {STYLES: await db[STYLES].find({'id': {'$in': list(sids)}}, {'_id': 0}).to_list(20000),
            MODELS: await db[MODELS].find({'id': {'$in': [g['model_id'] for g in r['gabung']] +
                                                     [x['model_id'] for x in r['samakan_kode']]}},
                                          {'_id': 0, 'sop_steps': 0}).to_list(20000),
            RND_VARIANTS: await db[RND_VARIANTS].find({'style_id': {'$in': list(sids)}}, {'_id': 0}).to_list(50000)}
    for coll in KOLEKSI_STYLE:
        data[coll] = await db[coll].find({'style_id': {'$in': dup}}, {'_id': 0}).to_list(50000)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'cadangan_style_rnd_dobel_{_now():%Y%m%d_%H%M%S}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, default=str, ensure_ascii=False, indent=1)
    return path


async def terapkan(db, r: dict) -> dict:
    now, n = _now(), {'kembar_diarsip': 0, 'varian_dipindah': 0, 'varian_diarsip': 0, 'dokumen_dipindah': 0,
                      'kode_disamakan': 0}
    for g in r['gabung']:
        tetap = await db[STYLES].find_one({'id': g['tetap']['id']}, {'_id': 0})
        model = await db[MODELS].find_one({'id': g['model_id']}, {'_id': 0, 'id': 1, 'code': 1, 'name': 1})
        if not tetap or not model:
            continue
        warna_tetap = set()
        async for v in db[RND_VARIANTS].find({'style_id': tetap['id']}, {'_id': 0, 'color_code': 1, 'color_id': 1}):
            warna_tetap |= {x for x in (_u(v.get('color_code')), v.get('color_id')) if x}
        foto = list(tetap.get('design_images') or [])
        for k in g['kembar']:
            d = await db[STYLES].find_one({'id': k['id']}, {'_id': 0})
            if not d:
                continue
            async for v in db[RND_VARIANTS].find({'style_id': d['id']}, {'_id': 0}):
                kunci = {x for x in (_u(v.get('color_code')), v.get('color_id')) if x}
                if kunci & warna_tetap:
                    await db[RND_VARIANTS].update_one({'id': v['id']}, {'$set': {
                        'status': 'archived', 'merged_into_style_id': tetap['id'], 'updated_at': now}})
                    n['varian_diarsip'] += 1
                else:
                    await db[RND_VARIANTS].update_one({'id': v['id']}, {'$set': {
                        'style_id': tetap['id'], 'style_code': model['code'], 'style_name': model['name'],
                        'updated_at': now}})
                    warna_tetap |= kunci
                    n['varian_dipindah'] += 1
            ada_terbaru = bool(await db.dewi_rnd_tech_packs.find_one({'style_id': tetap['id'], 'is_latest': True}))
            for coll in KOLEKSI_STYLE:
                patch = {'style_id': tetap['id']}
                if coll == 'dewi_rnd_tech_packs' and ada_terbaru:
                    patch['is_latest'] = False
                res = await db[coll].update_many({'style_id': d['id']}, {'$set': patch})
                n['dokumen_dipindah'] += int(res.modified_count or 0)
            for img in d.get('design_images') or []:
                if img not in foto:
                    foto.append(img)
            arsip = {'status': 'archived', 'promoted_to_model_id': None, 'merged_into_style_id': tetap['id'],
                     'merged_at': now, 'merged_by': PELAKU, 'master_sync': False,
                     'merged_note': f"Kembaran style untuk produk {model['code']} (dobel karena ganti kode) — "
                                    f"data dipindah ke style {tetap.get('style_code')}", 'updated_at': now}
            if k['kode_arsip'] != d.get('style_code'):
                arsip['style_code'] = k['kode_arsip']
            await db[STYLES].update_one({'id': d['id']}, {'$set': arsip})
            n['kembar_diarsip'] += 1
        patch = {'promoted_to_model_id': model['id'], 'style_name': model['name'], 'design_images': foto,
                 'updated_at': now}
        if g['kode_tetap_baru']:
            patch['style_code'] = g['kode_tetap_baru']
        await db[STYLES].update_one({'id': tetap['id']}, {'$set': patch})
        kode_st = patch.get('style_code') or tetap.get('style_code')
        await db[RND_VARIANTS].update_many({'style_id': tetap['id']},
                                           {'$set': {'style_code': kode_st, 'style_name': model['name']}})
        await db[MODELS].update_one({'id': model['id']}, {'$set': {'rnd_style_id': tetap['id'], 'rnd_style_code': kode_st}})
    for x in r['samakan_kode']:
        await db[STYLES].update_one({'id': x['style_id']}, {'$set': {'style_code': x['ke'], 'updated_at': now}})
        await db[RND_VARIANTS].update_many({'style_id': x['style_id']}, {'$set': {'style_code': x['ke']}})
        await db[MODELS].update_one({'id': x['model_id']}, {'$set': {'rnd_style_id': x['style_id'], 'rnd_style_code': x['ke']}})
        n['kode_disamakan'] += 1
    return n


def cetak(r: dict) -> None:
    print(f"  produk dengan style kembar: {len(r['gabung'])} · style tunggal beda kode: {len(r['samakan_kode'])} "
          f"· konflik: {len(r['konflik'])}")
    for g in r['gabung'][:200]:
        kem = ', '.join(f"{k['kode']} (data R&D {k['data_rnd']}){' → ' + k['kode_arsip'] if k['kode_arsip'] != k['kode'] else ''}"
                        for k in g['kembar'])
        print(f"    {g['model']} {g['nama'] or ''}{'' if g['aktif'] else ' [nonaktif]'}: pertahankan {g['tetap']['kode']} "
              f"(data R&D {g['tetap']['data_rnd']}) · arsipkan {kem}")
        if g['kode_pernah_diketik']:
            print(f"      kode yang pernah diketik R&D: {', '.join(g['kode_pernah_diketik'])}")
    for x in r['samakan_kode'][:200]:
        print(f"    samakan kode style {x['dari']} → {x['ke']}")
    for x in r['konflik'][:200]:
        print(f"    KONFLIK {x['model']}: style {x['style_code']} — {x['alasan']}")
    if r['yatim']:
        print(f"  style tertaut ke produk yang tidak ada (dibiarkan): {len(r['yatim'])}")
    if r['style_dipakai_banyak_produk']:
        print(f"  satu style dipakai >1 produk (dibiarkan): {len(r['style_dipakai_banyak_produk'])}")
    if r['sku_tidak_berawalan_kode']:
        models = sorted({x['model'] for x in r['sku_tidak_berawalan_kode']})
        print(f"  INFO: {len(r['sku_tidak_berawalan_kode'])} SKU aktif tidak berawalan kode produknya "
              f"({len(models)} produk: {', '.join(models[:30])}{' …' if len(models) > 30 else ''}) — keputusan owner")


async def run(db, apply: bool, cadangan: str) -> dict:
    r = await rencana(db)
    cetak(r)
    out = {'rencana': r, 'hasil': None, 'cadangan': None}
    if not apply or not (r['gabung'] or r['samakan_kode']):
        if not apply:
            print('  PRATINJAU — tidak ada yang ditulis. Tambah --apply untuk menerapkan.')
        return out
    out['cadangan'] = await _cadangan(db, r, cadangan)
    print(f"  cadangan ditulis: {out['cadangan']}")
    out['hasil'] = await terapkan(db, r)
    print(f"  diterapkan: {out['hasil']}")
    return out


async def main(args) -> int:
    if args.db != DB_NAME:
        print(f"--db {args.db!r} tidak sama dengan DB_NAME lingkungan {DB_NAME!r} — dibatalkan.")
        return 2
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f"DB {DB_NAME} — {'TERAPKAN' if args.apply else 'pratinjau'}")
    await run(db, args.apply, args.cadangan)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--db', required=True, help='nama database sasaran; wajib sama dengan DB_NAME lingkungan')
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    ap.add_argument('--cadangan', default='.', help='folder cadangan JSON (dibuat bila belum ada)')
    sys.exit(asyncio.run(main(ap.parse_args())))
