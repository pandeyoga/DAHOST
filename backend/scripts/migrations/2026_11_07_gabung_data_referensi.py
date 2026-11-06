"""Migrasi 2026-11-07 — data referensi (master pilihan) yang tercatat DUA KALI digabung.

KENAPA (pola P8, audit 6 Nov 2026): layar tambah master hanya mencocokkan kode persis, dan beberapa
benih otomatis bisa berjalan dua kali. Akibatnya pilihan di layar mendua:
  * kategori aset ×2 — benih `_ensure_default_categories` berjalan dua kali bersamaan (7 pasang);
  * proses produksi "Jahit (CMT)" (SEWING) + "Jahit / Sewing" (JAHIT), "Rework/Revisi" (REWORK) +
    "Permak / Rework" (PERMAK) — dua langkah urutan 2 di alur produksi;
  * satuan "rol" + "gulung" + "roll", dan "pak" + "pack";
  * kategori produk "Set/Setelan" (benih lama) + "One set" (dipakai 600+ item).

"Sama" memakai aturan yang SAMA dengan penolak dobel di layar (`core.reference_dedup.ref_key`:
huruf/spasi/tanda baca diabaikan, sinonim Indonesia/Inggris & ejaan satuan disatukan), ditambah
kelas kode proses (`process_class`) dan ejaan satuan (`core.uom.canonical_unit`).

Per kelompok dobel (master yang BOLEH digabung otomatis — hanya rujukan id/nama, tanpa angka):
  1. DIPERTAHANKAN = yang paling banyak dirujuk; bila sama, kode bawaan sistem; lalu yang paling
     lama. Satuan: ejaan resmi (`roll`, `pack`) selalu menang.
  2. Semua rujukan (id, kode, nama) di koleksi pemakainya dialihkan ke yang dipertahankan.
  3. Kembarannya DINONAKTIFKAN (`active: False`, `duplicate_of`, alasan) — tidak dihapus.

Master yang memuat angka/identitas (ukuran & warna di SKU, lokasi stok, saldo cuti, akses peran,
akun & rekening, mitra/klien/pelanggan, tunjangan) TIDAK digabung otomatis: kelompoknya hanya
dilaporkan untuk diputuskan owner. Warna dipratinjau lewat mesin yang sudah ada
(`core.variant_identity.merge_duplicate_colors`).

Riwayat transaksi (kartu stok, mutasi, riwayat harga) tidak ditulis ulang: teksnya sejarah.

Sifat: idempoten, tanpa hapus, hanya mencetak jumlah + nama master (bukan data pribadi).
Bawaan PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_gabung_data_referensi.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_gabung_data_referensi.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.reference_dedup import process_class, ref_key  # noqa: E402
from core.uom import canonical_unit  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
REASON = 'data referensi tercatat dua kali (migrasi 2026-11-07)'

UNIT_FIELDS = ('unit', 'base_uom', 'purchase_uom', 'issue_uom', 'display_uom', 'pack_unit')

# Kode bawaan sistem (benih) — pemenang seri. Disalin dari benih masing-masing supaya skrip ini
# tidak memuat modul route (FastAPI) saat dijalankan di VPS.
ASSET_CATEGORY_SEED = {'IT', 'MP', 'KD', 'BG', 'PM', 'AP', 'LN'}
PROCESS_SEED = {'CUTTING', 'SEWING', 'FINISHING', 'QC', 'PACKING', 'REWORK'}


def _now():
    return datetime.now(timezone.utc)


def _name_key(field='name'):
    return lambda d: [('n', ref_key(d.get(field)))]


def _process_keys(d):
    return [('n', ref_key(d.get('name'))), ('p', process_class(d.get('code')))]


def _unit_keys(d):
    return [('u', canonical_unit(d.get('code')))]


def _role_keys(d):
    return [('n', ref_key(d.get('name'))), ('d', ref_key(d.get('description')))]


def _unit_inherit(keep, dups):
    """Satuan yang ditambah otomatis oleh sinkron master (kategori 'count') mewarisi kategori &
    status satuan-dasar dari kembaran benih (mis. 'rol' → kategori 'roll', satuan dasar)."""
    if 'otomatis' not in str(keep.get('notes') or ''):
        return {}
    for d in dups:
        if d.get('category') and d.get('category') != keep.get('category'):
            return {'category': d['category'], 'is_base': bool(d.get('is_base'))}
    return {}


def _asset_inherit(keep, dups):
    out = {}
    for f in ('coa_asset_account', 'coa_depreciation_account'):
        if not keep.get(f):
            v = next((d.get(f) for d in dups if d.get(f)), None)
            if v:
                out[f] = v
    return out


def _category_patch(keep):
    from core import product_master as pm
    return pm.category_patch(keep)


def _material_category_patch(keep):
    return {'category': keep['id'], 'category_id': keep['id'], 'category_code': keep.get('code') or '',
            'category_name': keep.get('name') or ''}


# Jenis rujukan:
#   ('id', koleksi, field_id, fungsi_patch|None)  → {field_id: id_kembaran} dialihkan
#   ('code', koleksi, field_kode)                 → {field_kode: kode_kembaran}
#   ('name', koleksi, field_nama)                 → {field_nama: nama_kembaran} (hanya bila beda)
#   ('nested', koleksi, field_array, field_id, field_kode)
MERGE_SPECS = [
    {'coll': 'dewi_asset_categories', 'label': 'Kategori aset', 'keys': _name_key(),
     'seed': ASSET_CATEGORY_SEED, 'inherit': _asset_inherit,
     'refs': [('id', 'dewi_assets', 'category_id', lambda k: {'category_name': k.get('name') or ''}),
              ('name', 'dewi_assets', 'category_name'),
              ('name', 'dewi_asset_loans', 'category_name')]},
    {'coll': 'rahaza_processes', 'label': 'Proses produksi', 'keys': _process_keys, 'seed': PROCESS_SEED,
     'refs': [('id', 'rahaza_wip_events', 'process_id', lambda k: {'process_code': k.get('code')}),
              ('id', 'rahaza_line_assignments', 'process_id', lambda k: {'process_code': k.get('code')}),
              ('id', 'rahaza_model_process_sop', 'process_id', lambda k: {'process_code': k.get('code')}),
              ('id', 'rahaza_lines', 'process_id', None),
              ('code', 'rahaza_wip_events', 'process_code'),
              ('nested', 'rahaza_payroll_profiles', 'pcs_process_rates', 'process_id', 'process_code')]},
    {'coll': 'wh_unit_master', 'label': 'Satuan', 'keys': _unit_keys, 'canonical_first': True,
     'inherit': _unit_inherit,
     'refs': [('id', 'wh_unit_conversions', 'from_unit_id', lambda k: {'from_unit_code': k.get('code')}),
              ('id', 'wh_unit_conversions', 'to_unit_id', lambda k: {'to_unit_code': k.get('code')}),
              ('units',)]},
    {'coll': 'rahaza_product_categories', 'label': 'Kategori produk', 'keys': _name_key(),
     'refs': [('id', 'rahaza_models', 'category_id', _category_patch),
              ('id', 'rahaza_materials', 'category_id', _category_patch),
              ('id', 'marketing_catalog_items', 'category_id', _category_patch),
              ('name', 'dewi_rnd_styles', 'category'),
              ('name', 'dewi_maklon_buyer_catalog', 'category'),
              ('name', 'marketing_live_session_products', 'category'),
              ('name', 'marketing_product_launches', 'category_name')]},
    {'coll': 'rahaza_material_categories', 'label': 'Kategori material', 'keys': _name_key(),
     'refs': [('id', 'rahaza_materials', 'category_id', _material_category_patch),
              ('id', 'rahaza_materials', 'category', _material_category_patch)]},
]

# Hanya dilaporkan: menggabungkan mengubah angka, SKU, akses, atau buku — keputusan owner.
REPORT_SPECS = [
    {'coll': 'rahaza_sizes', 'label': 'Ukuran', 'why': 'kode ukuran ada di SKU varian'},
    {'coll': 'rahaza_shifts', 'label': 'Shift', 'why': 'jam kerja & absensi per shift'},
    {'coll': 'rahaza_locations', 'label': 'Lokasi', 'why': 'stok tercatat per lokasi'},
    {'coll': 'rahaza_leave_types', 'label': 'Jenis cuti', 'why': 'saldo cuti per jenis'},
    {'coll': 'rahaza_cost_centers', 'label': 'Pusat biaya', 'why': 'jurnal per pusat biaya'},
    {'coll': 'employee_expense_categories', 'label': 'Kategori klaim biaya', 'why': 'akun beban per kategori'},
    {'coll': 'dewi_org_units', 'label': 'Unit organisasi', 'id': 'unit_id', 'why': 'struktur & atasan'},
    {'coll': 'dewi_org_positions', 'label': 'Jabatan', 'id': 'position_id', 'name': 'title',
     'scope': 'unit_id', 'why': 'jabatan per unit'},
    {'coll': 'rahaza_salary_grades', 'label': 'Grade gaji', 'name': 'grade_name', 'why': 'rentang gaji'},
    {'coll': 'rahaza_lines', 'label': 'Lini produksi', 'why': 'penugasan & output per lini'},
    {'coll': 'rahaza_machines', 'label': 'Mesin', 'why': 'aset fisik berbeda'},
    {'coll': 'rahaza_variant_options', 'label': 'Opsi varian', 'why': 'kode opsi ada di SKU'},
    {'coll': 'roles', 'label': 'Peran pengguna', 'keys': _role_keys,
     'why': 'hak akses — menggabung peran mengubah siapa boleh apa'},
    {'coll': 'rahaza_coa_accounts', 'label': 'Akun (Bagan Akun)', 'why': 'keuangan/COA ditunda owner'},
    {'coll': 'rahaza_cash_accounts', 'label': 'Rekening kas/bank', 'why': 'saldo & mutasi per rekening'},
    {'coll': 'da_payroll_allowances', 'label': 'Tunjangan', 'why': 'nominal berbeda per karyawan'},
    {'coll': 'vendor_partners', 'label': 'Penjahit (CMT)', 'private': True, 'why': 'utang & PO per mitra'},
    {'coll': 'dewi_maklon_clients', 'label': 'Klien maklon', 'private': True, 'why': 'piutang per klien'},
    {'coll': 'rahaza_customers', 'label': 'Pelanggan', 'private': True, 'why': 'piutang per pelanggan'},
    {'coll': 'rahaza_suppliers', 'label': 'Supplier', 'private': True,
     'why': 'utang per supplier (dedup nama sudah ada: name_key)'},
    {'coll': 'doc_number_configs', 'label': 'Format nomor dokumen', 'id': 'key', 'name': 'key',
     'why': 'penomoran'},
    {'coll': 'rahaza_posting_profiles', 'label': 'Profil jurnal otomatis', 'name': 'event_type',
     'why': 'jurnal otomatis'},
    {'coll': 'rahaza_channel_gl_mapping', 'label': 'Pemetaan akun kanal', 'name': 'channel_key',
     'why': 'jurnal penjualan'},
]


# ── perencanaan (murni, tanpa DB — diuji unit) ───────────────────────────────
def is_active(d: dict) -> bool:
    return (d.get('active') is not False and d.get('is_active') is not False and not d.get('duplicate_of')
            and str(d.get('status') or '').lower() not in ('inactive', 'archived', 'nonaktif'))


def cluster(docs: list, keys_fn, id_field: str = 'id', scope: str | None = None) -> list:
    """Kelompok baris aktif yang kuncinya bertemu (union-find)."""
    rows = [d for d in docs if is_active(d) and d.get(id_field)]
    parent = {d[id_field]: d[id_field] for d in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner = {}
    for d in rows:
        for k in keys_fn(d):
            if not k or not k[1]:
                continue
            k = (k, d.get(scope)) if scope else k
            if k in owner:
                parent[find(d[id_field])] = find(owner[k])
            else:
                owner[k] = d[id_field]
    groups = {}
    for d in rows:
        groups.setdefault(find(d[id_field]), []).append(d)
    return [g for g in groups.values() if len(g) > 1]


_FAR = '9999'


def _created(d) -> str:
    c = d.get('created_at')
    if isinstance(c, datetime):
        return c.isoformat()
    return str(c) if c else _FAR


def choose_keeper(group: list, refs: dict, *, seed=(), canonical_first: bool = False) -> dict:
    """Paling banyak dirujuk → kode bawaan → paling lama → kode terpendek. Satuan: ejaan resmi dulu."""
    def canon(d):
        code = d.get('code')
        if canonical_first:
            return 0 if canonical_unit(code) == str(code or '').strip().lower() else 1
        return 0 if code in seed else 1

    def key(d):
        r, c = -refs.get(d['id'], 0), canon(d)
        head = (c, r) if canonical_first else (r, c)
        return head + (_created(d), len(str(d.get('code') or '')), str(d['id']))
    return min(group, key=key)


def rewrite_units(doc: dict, mapping: dict) -> dict:
    """Patch `$set` untuk satu material/BOM bila memakai kode satuan kembaran ({} bila tidak)."""
    patch = {}
    for f in UNIT_FIELDS:
        v = doc.get(f)
        if isinstance(v, str) and v.strip().lower() in mapping:
            patch[f] = mapping[v.strip().lower()]
    uoms = doc.get('uoms')
    if isinstance(uoms, list):
        new, changed = [], False
        for r in uoms:
            r = dict(r) if isinstance(r, dict) else r
            if isinstance(r, dict):
                for f in ('code', 'parent'):
                    v = r.get(f)
                    if isinstance(v, str) and v.strip().lower() in mapping:
                        r[f] = mapping[v.strip().lower()]
                        changed = True
            new.append(r)
        if changed:
            patch['uoms'] = new
    lines = doc.get('materials')
    if isinstance(lines, list):
        new, changed = [], False
        for ln in lines:
            ln = dict(ln) if isinstance(ln, dict) else ln
            if isinstance(ln, dict):
                for f in ('unit', 'unit_base'):
                    v = ln.get(f)
                    if isinstance(v, str) and v.strip().lower() in mapping:
                        ln[f] = mapping[v.strip().lower()]
                        changed = True
            new.append(ln)
        if changed:
            patch['materials'] = new
    return patch


# ── baca/tulis DB ────────────────────────────────────────────────────────────
async def _unit_usage(db) -> dict:
    """Jumlah dokumen material/BOM yang memakai setiap kode satuan."""
    use = {}
    for coll in ('rahaza_materials', 'rahaza_boms'):
        async for m in db[coll].find({}, {'_id': 0, 'uoms': 1, 'materials': 1, **{f: 1 for f in UNIT_FIELDS}}):
            codes = {str(m.get(f)).strip().lower() for f in UNIT_FIELDS if m.get(f)}
            codes |= {str(r.get('code')).strip().lower() for r in (m.get('uoms') or []) if isinstance(r, dict)}
            codes |= {str(ln.get(f)).strip().lower() for ln in (m.get('materials') or []) if isinstance(ln, dict)
                      for f in ('unit', 'unit_base') if ln.get(f)}
            for c in codes:
                use[c] = use.get(c, 0) + 1
    return use


async def _ref_count(db, spec: dict, d: dict, unit_use: dict) -> int:
    n = 0
    for ref in spec['refs']:
        kind = ref[0]
        if kind == 'id':
            n += await db[ref[1]].count_documents({ref[2]: d['id']})
        elif kind == 'code' and d.get('code'):
            n += await db[ref[1]].count_documents({ref[2]: d['code']})
        elif kind == 'name' and d.get('name'):
            n += await db[ref[1]].count_documents({ref[2]: d['name']})
        elif kind == 'nested':
            async for doc in db[ref[1]].find({}, {'_id': 0, ref[2]: 1}):
                n += sum(1 for r in (doc.get(ref[2]) or []) if isinstance(r, dict) and r.get(ref[3]) == d['id'])
        elif kind == 'units':
            n += unit_use.get(str(d.get('code') or '').strip().lower(), 0)
    return n


async def _repoint(db, spec: dict, keep: dict, dup: dict, apply: bool) -> int:
    """Alihkan semua rujukan `dup` → `keep`. Mengembalikan jumlah dokumen yang (akan) diubah."""
    moved = 0
    for ref in spec['refs']:
        kind = ref[0]
        if kind == 'id':
            coll, field, patch_fn = ref[1], ref[2], ref[3]
            q = {field: dup['id']}
            n = await db[coll].count_documents(q)
            if n and apply:
                patch = {field: keep['id'], **(patch_fn(keep) if patch_fn else {}), 'updated_at': _now()}
                await db[coll].update_many(q, {'$set': patch})
            moved += n
        elif kind in ('code', 'name'):
            coll, field = ref[1], ref[2]
            src, dst = (dup.get('code'), keep.get('code')) if kind == 'code' else (dup.get('name'), keep.get('name'))
            if not src or src == dst:
                continue
            q = {field: src}
            n = await db[coll].count_documents(q)
            if n and apply:
                await db[coll].update_many(q, {'$set': {field: dst}})
            moved += n
        elif kind == 'nested':
            coll, arr, fid, fcode = ref[1], ref[2], ref[3], ref[4]
            async for doc in db[coll].find({}, {'_id': 0}):
                rows = doc.get(arr) or []
                if not any(isinstance(r, dict) and r.get(fid) == dup['id'] for r in rows):
                    continue
                moved += 1
                if apply:
                    new = [{**r, fid: keep['id'], fcode: keep.get('code')}
                           if isinstance(r, dict) and r.get(fid) == dup['id'] else r for r in rows]
                    await db[coll].update_one({'id': doc.get('id')}, {'$set': {arr: new, 'updated_at': _now()}})
        elif kind == 'units':
            mapping = {str(dup.get('code') or '').strip().lower(): keep.get('code')}
            for coll in ('rahaza_materials', 'rahaza_boms'):
                async for doc in db[coll].find({}, {'_id': 0}):
                    patch = rewrite_units(doc, mapping)
                    if not patch:
                        continue
                    moved += 1
                    if apply:
                        patch['updated_at'] = _now()
                        await db[coll].update_one({'id': doc.get('id')}, {'$set': patch})
    return moved


async def merge_spec(db, spec: dict, apply: bool, out=print) -> dict:
    coll = spec['coll']
    docs = await db[coll].find({}, {'_id': 0}).to_list(None)
    groups = cluster(docs, spec['keys'])
    res = {'coll': coll, 'groups': len(groups), 'deactivated': 0, 'repointed': 0, 'detail': []}
    if not groups:
        out(f"  ■ {spec['label']} ({coll}): tidak ada yang dobel.")
        return res
    out(f"  ■ {spec['label']} ({coll}): {len(groups)} kelompok dobel")
    unit_use = await _unit_usage(db) if any(r[0] == 'units' for r in spec['refs']) else {}
    for g in groups:
        refs = {d['id']: await _ref_count(db, spec, d, unit_use) for d in g}
        keep = choose_keeper(g, refs, seed=spec.get('seed') or (), canonical_first=spec.get('canonical_first', False))
        dups = [d for d in g if d['id'] != keep['id']]
        out(f"    - '{keep.get('name')}' [{keep.get('code') or '-'}] DIPERTAHANKAN (dirujuk {refs[keep['id']]})"
            f" ⇐ " + ', '.join(f"'{d.get('name')}' [{d.get('code') or '-'}] dirujuk {refs[d['id']]}" for d in dups))
        inherit = spec.get('inherit')
        patch = inherit(keep, dups) if inherit else {}
        if patch:
            out(f"      dipertahankan mewarisi: {', '.join(f'{k}={v}' for k, v in patch.items())}")
            if apply:
                await db[coll].update_one({'id': keep['id']}, {'$set': {**patch, 'updated_at': _now()}})
        for d in dups:
            res['repointed'] += await _repoint(db, spec, keep, d, apply)
            res['deactivated'] += 1
            if apply:
                await db[coll].update_one({'id': d['id']}, {'$set': {
                    'active': False, 'duplicate_of': keep['id'], 'duplicate_of_code': keep.get('code'),
                    'deactivated_reason': REASON, 'deactivated_at': _now(), 'updated_at': _now()}})
        res['detail'].append({'keep': keep.get('code') or keep.get('name'),
                              'dups': [d.get('code') or d.get('name') for d in dups]})
    out(f"      {'dinonaktifkan' if apply else 'akan dinonaktifkan'}: {res['deactivated']} · "
        f"rujukan {'dialihkan' if apply else 'akan dialihkan'}: {res['repointed']} dokumen")
    return res


async def report_spec(db, spec: dict, out=print) -> dict:
    coll, idf, nf = spec['coll'], spec.get('id', 'id'), spec.get('name', 'name')
    docs = await db[coll].find({}, {'_id': 0}).to_list(None)
    keys = spec.get('keys') or _name_key(nf)
    groups = cluster(docs, keys, id_field=idf, scope=spec.get('scope'))
    if groups:
        out(f"  ▲ {spec['label']} ({coll}): {len(groups)} kelompok mirip — TIDAK digabung otomatis ({spec['why']})")
        for g in groups:
            shown = (', '.join(f"[{d.get('code') or d.get(idf)}]" for d in g) if spec.get('private')
                     else ', '.join(f"'{d.get(nf)}'" + (f" [{d['code']}]" if d.get('code') else '') for d in g))
            out(f"      · {shown}")
    return {'coll': coll, 'groups': len(groups)}


async def run_all(db, apply: bool, out=print) -> dict:
    out(f"[gabung-referensi] DB={getattr(db, 'name', DB_NAME)} · "
        f"{'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    out('Master yang digabung otomatis:')
    merged = [await merge_spec(db, s, apply, out) for s in MERGE_SPECS]
    out('Master yang hanya dilaporkan:')
    reported = [await report_spec(db, s, out) for s in REPORT_SPECS]
    try:
        from core.variant_identity import merge_duplicate_colors
        colors = await merge_duplicate_colors(db, dry_run=True)
        out(f"  ▲ Warna (rahaza_colors): {colors.get('message')} — pakai Perapian Palet Warna (keputusan 6a).")
    except Exception as e:  # noqa: BLE001 — pratinjau warna tidak boleh menggagalkan migrasi ini
        out(f"  ▲ Warna: pratinjau gagal ({e})")
        colors = {}
    total = {'groups': sum(m['groups'] for m in merged), 'deactivated': sum(m['deactivated'] for m in merged),
             'repointed': sum(m['repointed'] for m in merged),
             'report_groups': sum(r['groups'] for r in reported) + int(colors.get('groups_affected') or 0)}
    out(f"\n  ringkas: {total['groups']} kelompok digabung · "
        f"{'dinonaktifkan' if apply else 'akan dinonaktifkan'}: {total['deactivated']} · "
        f"rujukan: {total['repointed']} dokumen · kelompok untuk diputuskan owner: {total['report_groups']}")
    return {'merged': merged, 'reported': reported, **total}


async def run(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    await run_all(db, apply)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    sys.exit(asyncio.run(run(ap.parse_args().apply)))
