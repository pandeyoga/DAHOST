"""Isi kemasan SATUAN SERAH aksesoris dari Excel isian gudang (2026-11-07, Tahap 9 lanjutan, keputusan owner).

KENAPA: aksesoris diserahkan ke CMT dalam satuan serah (kemasan dari daftar satuan material) dan stok berkurang
qty serah × isi kemasan. Laporan `2026_11_07_cek_satuan_serah` menemukan aksesoris tanpa kemasan dan kemasan
"gross" yang isinya bukan 144. Gudang mengisi Excel (kolom "Kemasan serah" + "Isi per kemasan"); skrip ini
memasukkannya ke master LEWAT ATURAN YANG SAMA dengan layar master (`core.uom.apply_payload`: validasi daftar
satuan + cermin field lama).

Yang diubah per baris yang diisi:
  · kemasan dengan kode itu sudah ada → isinya diganti angka gudang;
  · belum ada → ditambahkan sebagai kemasan baru;
  · kemasan itu dijadikan SATUAN PAKAI (satuan serah) barang tersebut.
TIDAK PERNAH mengubah satuan dasar, angka stok, atau harga (INV-UOM-1/2/5). Baris yang tidak bisa dimasukkan
(kode tidak ada, kemasan = satuan dasar, isian tidak lengkap, daftar satuan penuh) DILAPORKAN, tidak ditebak.

Pakai:
    python scripts/migrations/2026_11_07_isi_kemasan_aksesoris.py --file /tmp/isian.xlsx            # pratinjau
    python scripts/migrations/2026_11_07_isi_kemasan_aksesoris.py --file /tmp/isian.xlsx --apply    # tulis
Berkas: .xlsx (lembar "Isian") atau .csv, kolom: Kode · Kemasan serah · Isi per kemasan · Catatan gudang.
Idempoten: baris yang sudah sesuai dilewati.
"""
import argparse
import asyncio
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

COL_CODE = ('kode',)
COL_PACK = ('kemasan serah', 'kemasan')
COL_QTY = ('isi per kemasan', 'isi')
COL_NOTE = ('catatan gudang', 'catatan')

STATUS_LABEL = {
    'akan_diubah': 'akan diubah',
    'sudah_sesuai': 'sudah sesuai (dilewati)',
    'kosong': 'tidak diisi (dilewati)',
    'kode_tidak_ada': 'kode tidak ditemukan di master',
    'isian_tidak_lengkap': 'isian tidak lengkap / isi bukan angka > 0',
    'sama_dengan_dasar': 'kemasan sama dengan satuan dasar',
    'tidak_valid': 'daftar satuan tidak valid',
}
ERRORS = ('kode_tidak_ada', 'isian_tidak_lengkap', 'sama_dengan_dasar', 'tidak_valid')


def _num(v):
    """Angka isian gudang: sel angka Excel apa adanya; teks memakai gaya Indonesia (1.440 = seribu empat ratus
    empat puluh, 2,5 = dua koma lima)."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or '').strip().replace(' ', '')
    if not s:
        return None
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    elif s.count('.') > 1 or (s.count('.') == 1 and len(s.split('.')[1]) == 3):
        s = s.replace('.', '')
    try:
        return float(s)
    except ValueError:
        return None


def plan_entry(mat: dict | None, entry: dict) -> dict:
    """Fungsi murni (diuji): rencana perubahan satu baris isian → {status, before, after, payload}."""
    from core import uom as uom_core
    code = (entry.get('code') or '').strip()
    pack_raw = (entry.get('pack') or '').strip()
    qty_raw = entry.get('qty')
    if not pack_raw and (qty_raw in (None, '')):
        return {'code': code, 'status': 'kosong'}
    if not mat:
        return {'code': code, 'status': 'kode_tidak_ada'}
    qty = _num(qty_raw)
    pack = uom_core.normalize_code(pack_raw)
    if not pack or not qty or qty <= 0:
        return {'code': code, 'status': 'isian_tidak_lengkap'}
    base = uom_core.base_uom_of(mat)
    if pack == base:
        return {'code': code, 'status': 'sama_dengan_dasar'}
    rows = [dict(r) for r in uom_core.resolve_uoms(mat)]
    before = '; '.join(f"{r['code']}={r['factor']:g}" for r in rows)
    current = next((r for r in rows if r['code'] == pack), None)
    if current and abs(float(current['factor']) - qty) < 1e-9 and uom_core.issue_uom_of(mat) == pack:
        return {'code': code, 'status': 'sudah_sesuai', 'before': before}
    for r in rows:
        r.pop('is_issue_default', None)
    if current:
        current['factor'] = qty
        current['name'] = current.get('name') or pack_raw
        current['is_issue_default'] = True
    else:
        rows.append({'code': pack, 'name': pack_raw, 'factor': qty, 'parent': base, 'is_issue_default': True,
                     'notes': f"1 {pack} = {qty:g} {base} (isian gudang)"})
    try:
        payload = uom_core.apply_payload({'uoms': rows, 'issue_uom': pack}, mat)
    except uom_core.UomError as e:
        return {'code': code, 'status': 'tidak_valid', 'before': before, 'error': str(e)}
    if pack not in {r['code'] for r in payload['uoms']}:
        return {'code': code, 'status': 'tidak_valid', 'before': before,
                'error': 'kemasan tidak bisa ditambahkan (daftar satuan penuh)'}
    payload['issue_uom'] = pack
    after = '; '.join(f"{r['code']}={r['factor']:g}" for r in payload['uoms'])
    return {'code': code, 'status': 'akan_diubah', 'before': before, 'after': after, 'payload': payload}


def _norm_header(h) -> str:
    return str(h or '').strip().lower()


def _pick(row: dict, names) -> str:
    for k, v in row.items():
        if _norm_header(k) in names:
            return '' if v is None else str(v).strip()
    return ''


def read_entries(path: str) -> list:
    rows = []
    if path.lower().endswith('.csv'):
        with open(path, encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb['Isian'] if 'Isian' in wb.sheetnames else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = None
        for vals in it:
            if header is None:
                if any(_norm_header(v) in COL_CODE for v in vals):
                    header = [str(v or '') for v in vals]
                continue
            rows.append(dict(zip(header, vals)))
    out = []
    for r in rows:
        code = _pick(r, COL_CODE)
        if not code:
            continue
        out.append({'code': code, 'pack': _pick(r, COL_PACK), 'qty': _pick(r, COL_QTY), 'note': _pick(r, COL_NOTE)})
    return out


async def run(path: str, apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    entries = read_entries(path)
    print(f"[isi-kemasan-aksesoris] DB={DB_NAME} · {'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    print(f"  baris berkode di berkas: {len(entries)}")
    codes = [e['code'] for e in entries]
    mats = {m['code']: m async for m in db.rahaza_materials.find(
        {'code': {'$in': codes}, 'active': {'$ne': False}}, {'_id': 0})}
    plans = [plan_entry(mats.get(e['code']), e) for e in entries]
    counts: dict = {}
    for p in plans:
        counts[p['status']] = counts.get(p['status'], 0) + 1
    for st in STATUS_LABEL:
        if counts.get(st):
            print(f"  {STATUS_LABEL[st]:42s}: {counts[st]}")
    for p in plans:
        if p['status'] in ERRORS:
            print(f"    ! {p['code']}: {STATUS_LABEL[p['status']]}" + (f" — {p['error']}" if p.get('error') else ''))
    changed = 0
    for p in plans:
        if p['status'] != 'akan_diubah':
            continue
        print(f"    {p['code']}: {p['before']}  →  {p['after']} (satuan serah {p['payload']['issue_uom']})")
        if apply:
            await db.rahaza_materials.update_one({'code': p['code'], 'active': {'$ne': False}}, {'$set': {
                **p['payload'], 'updated_at': datetime.now(timezone.utc),
                'uom_updated_by': 'skrip isi_kemasan_aksesoris (isian gudang)'}})
            changed += 1
    if apply:
        print(f"  ditulis: {changed}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    sys.exit(asyncio.run(run(a.file, a.apply)))


if __name__ == '__main__':
    main()
