"""Migrasi 2026-11-07 — Struktur Organisasi diisi SEKALI dari departemen & jabatan yang dipakai karyawan.

KENAPA (keputusan owner OR1, Tahap 6): Struktur Organisasi (`dewi_org_units` + `dewi_org_positions`)
kini satu-satunya daftar departemen & jabatan — dipakai Data Karyawan, OKR, Permintaan Pembelian
(persetujuan tahap departemen), aset, dan anggaran. Isinya hampir kosong, sedangkan departemen dan
jabatan yang benar sudah tercatat di data karyawan (`rahaza_employees.department` / `job_title`).

Yang dilakukan:
  1. Departemen karyawan AKTIF dikelompokkan dengan kunci banding `core.departments.department_key`
     (huruf besar/kecil, spasi, dan tanda baca diabaikan). Satu kelompok = satu departemen.
  2. Kelompok yang sudah punya unit (kunci sama) DILEWATI; yang belum → unit baru (tipe Departemen,
     di bawah unit Perusahaan bila strukturnya punya tepat satu unit Perusahaan).
  3. Ejaan yang PASTI sama (hanya beda huruf besar/spasi/tanda baca) diseragamkan ke nama unit di data
     karyawan (aktif & nonaktif) supaya bagan, headcount, dan saringan menghitung satu departemen.
  4. Jabatan karyawan per departemen → jabatan di unit itu (dilewati bila sudah ada dengan kunci sama
     di unit itu, atau sebagai jabatan umum tanpa unit). Jabatan karyawan tanpa departemen → jabatan
     umum (tanpa unit) bila belum ada di mana pun. Ejaan jabatan yang pasti sama diseragamkan juga.
  5. Yang TIDAK pasti hanya DILAPORKAN, tidak diubah:
       * departemen yang mirip tetapi beda kata (sinonim/urutan kata `core.reference_dedup.ref_key`,
         atau ejaan berselisih sedikit, mis. salah ketik);
       * jabatan pengganti ("Lainnya", "-") — tidak dibuat sebagai jabatan;
       * departemen yang hanya dipakai karyawan nonaktif — tidak dibuat.

Sifat: idempoten (jalan kedua = 0 perubahan), tanpa hapus. Bawaan PRATINJAU; tulis dengan --apply.
Yang dicetak: jumlah + nama departemen/jabatan (data organisasi, bukan data pribadi).

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_struktur_dari_karyawan.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_07_struktur_dari_karyawan.py --apply
"""
import argparse
import asyncio
import difflib
import os
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.departments import department_key  # noqa: E402
from core.reference_dedup import ref_key  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
SOURCE = 'migrasi_2026_11_07_struktur_dari_karyawan'
ACTOR = 'Migrasi 2026-11-07 (data karyawan)'
#: Isian jabatan yang bukan jabatan (pengganti) — tidak dibuat sebagai jabatan, hanya dilaporkan.
PLACEHOLDER_TITLES = {'lainnya', 'tidak ada', 'belum ada', 'kosong', 'na', 'n a', 'none'}
#: Ambang "ejaan mirip" untuk laporan salah ketik (difflib ratio atas kunci banding).
SIMILAR_RATIO = 0.85


def _now():
    return datetime.now(timezone.utc)


def _active(e: dict) -> bool:
    return e.get('active') is not False


def _spelling_rank(s: str) -> int:
    """Ejaan yang lebih rapi lebih dulu: "Produksi" / singkatan pendek "HRD" < campuran < "PRODUKSI" < "produksi"."""
    s = s.strip()
    if s == s.title() or (s.isupper() and len(s) <= 5):
        return 0
    if s.isupper():
        return 2
    if s.islower():
        return 3
    return 1


def _pick_spelling(counter: Counter) -> str:
    """Ejaan yang paling banyak dipakai; seri → yang paling rapi (`_spelling_rank`), lalu urut abjad."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], _spelling_rank(kv[0]), kv[0].strip()))[0][0].strip()


def _is_placeholder(title: str) -> bool:
    k = department_key(title)
    return not k or k in PLACEHOLDER_TITLES or ref_key(title) == 'lainnya'


def similar_groups(keys_to_name: dict) -> list:
    """Pasangan departemen yang MIRIP tetapi tidak pasti sama (dilaporkan, tidak digabung)."""
    items = sorted(keys_to_name.items())
    out = []
    for i, (ka, na) in enumerate(items):
        for kb, nb in items[i + 1:]:
            same_words = ref_key(na) and ref_key(na) == ref_key(nb)
            close = difflib.SequenceMatcher(None, ka, kb).ratio() >= SIMILAR_RATIO
            if same_words or close:
                out.append((na, nb))
    return out


async def build_plan(db) -> dict:
    units = await db.dewi_org_units.find({}, {'_id': 0}).to_list(None)
    positions = await db.dewi_org_positions.find({}, {'_id': 0}).to_list(None)
    emps = await db.rahaza_employees.find({}, {'_id': 0, 'id': 1, 'active': 1, 'department': 1,
                                               'job_title': 1}).to_list(None)

    unit_by_key = {}
    for u in units:
        k = department_key(u.get('name'))
        if k and (k not in unit_by_key or (u.get('is_active') is not False
                                            and unit_by_key[k].get('is_active') is False)):
            unit_by_key[k] = u
    roots = [u for u in units if u.get('type') == 'company' and not u.get('parent_id')
             and u.get('is_active') is not False]
    parent = roots[0] if len(roots) == 1 else None

    # departemen yang dipakai karyawan AKTIF (dan semua ejaannya)
    spell_active = defaultdict(Counter)
    spell_inactive = defaultdict(Counter)
    for e in emps:
        d = (e.get('department') or '').strip()
        k = department_key(d)
        if not k:
            continue
        (spell_active if _active(e) else spell_inactive)[k][e.get('department')] += 1

    new_units, existing_units, canon_dept = [], [], {}
    for k, counter in sorted(spell_active.items()):
        if k in unit_by_key:
            canon_dept[k] = unit_by_key[k]['name']
            existing_units.append(unit_by_key[k]['name'])
            continue
        name = _pick_spelling(counter)
        canon_dept[k] = name
        new_units.append({'key': k, 'name': name, 'count': sum(counter.values())})
    # karyawan nonaktif: ejaannya ikut diseragamkan bila kuncinya sudah punya unit (tanpa membuat unit)
    inactive_only = sorted(k for k in spell_inactive if k not in spell_active and k not in unit_by_key)
    for k in spell_inactive:
        if k in unit_by_key and k not in canon_dept:
            canon_dept[k] = unit_by_key[k]['name']

    dept_renames = []   # (employee_id, lama, baru) — ejaan pasti sama
    for e in emps:
        d = e.get('department')
        k = department_key(d)
        if k in canon_dept and d != canon_dept[k]:
            dept_renames.append((e['id'], d, canon_dept[k]))

    # jabatan per departemen (karyawan aktif)
    pos_by_unit_key = defaultdict(dict)   # unit_id|'' → {kunci jabatan: dok}
    for p in positions:
        k = department_key(p.get('title'))
        if k:
            pos_by_unit_key[p.get('unit_id') or ''].setdefault(k, p)
    any_pos_keys = {k for d in pos_by_unit_key.values() for k in d}
    titles = defaultdict(Counter)           # (kunci dept|'', kunci jabatan) → ejaan
    placeholders = Counter()
    for e in emps:
        if not _active(e):
            continue
        t = (e.get('job_title') or '').strip()
        if not t:
            continue
        if _is_placeholder(t):
            placeholders[t] += 1
            continue
        titles[(department_key(e.get('department')), department_key(t))][e.get('job_title')] += 1

    new_positions, skipped_positions, canon_title = [], 0, {}
    for (dk, tk), counter in sorted(titles.items()):
        unit = unit_by_key.get(dk) if dk else None
        unit_id = (unit or {}).get('unit_id') or ''
        existing = (pos_by_unit_key.get(unit_id, {}).get(tk) if unit_id else None) or pos_by_unit_key[''].get(tk)
        if not dk and not existing and tk in any_pos_keys:
            existing = next(d[tk] for d in pos_by_unit_key.values() if tk in d)
        if existing:
            canon_title[(dk, tk)] = existing['title']
            skipped_positions += 1
            continue
        title = _pick_spelling(counter)
        canon_title[(dk, tk)] = title
        new_positions.append({'dept_key': dk, 'unit_name': canon_dept.get(dk, ''), 'title': title,
                              'count': sum(counter.values())})
        if not dk:
            pos_by_unit_key[''][tk] = {'title': title}

    title_renames = []
    for e in emps:
        if not _active(e):
            continue
        t = e.get('job_title')
        key = (department_key(e.get('department')), department_key(t))
        if key in canon_title and t != canon_title[key]:
            title_renames.append((e['id'], t, canon_title[key]))

    return {
        'active_depts': len(spell_active), 'parent': parent, 'new_units': new_units,
        'existing_units': sorted(set(existing_units)),
        'canon_dept': canon_dept, 'dept_renames': dept_renames, 'title_renames': title_renames,
        'new_positions': new_positions, 'skipped_positions': skipped_positions,
        'placeholders': placeholders, 'inactive_only': inactive_only,
        'similar': similar_groups({k: canon_dept[k] for k in canon_dept}
                                  | {department_key(u.get('name')): u.get('name') for u in units
                                     if department_key(u.get('name'))}),
        'unit_by_key': unit_by_key,
    }


async def apply_plan(db, plan: dict) -> dict:
    now = _now()
    parent = plan['parent']
    unit_ids = {k: u['unit_id'] for k, u in plan['unit_by_key'].items()}
    made_units = made_pos = 0
    for nu in plan['new_units']:
        # idempoten terhadap dua jalan bersamaan: periksa lagi tepat sebelum menulis
        again = await db.dewi_org_units.find({}, {'_id': 0, 'unit_id': 1, 'name': 1}).to_list(None)
        hit = next((u for u in again if department_key(u.get('name')) == nu['key']), None)
        if hit:
            unit_ids[nu['key']] = hit['unit_id']
            continue
        uid = str(uuid.uuid4())
        await db.dewi_org_units.insert_one({
            'unit_id': uid, 'name': nu['name'], 'code': '', 'type': 'department',
            'parent_id': parent['unit_id'] if parent else None,
            'level': (int(parent.get('level') or 0) + 1) if parent else 0,
            'head_employee_id': None, 'head_employee_name': '',
            'headcount_actual': nu['count'], 'headcount_target': nu['count'], 'color': '',
            'description': 'Dibuat dari departemen yang dipakai data karyawan (migrasi 2026-11-07).',
            'is_active': True, 'created_by': ACTOR, 'created_at': now, 'updated_at': now, 'source': SOURCE})
        unit_ids[nu['key']] = uid
        made_units += 1
    for np_ in plan['new_positions']:
        unit_id = unit_ids.get(np_['dept_key'], '') if np_['dept_key'] else ''
        again = await db.dewi_org_positions.find({'unit_id': unit_id}, {'_id': 0, 'title': 1}).to_list(None)
        if any(department_key(p.get('title')) == department_key(np_['title']) for p in again):
            continue
        await db.dewi_org_positions.insert_one({
            'position_id': str(uuid.uuid4()), 'title': np_['title'], 'unit_id': unit_id,
            'unit_name': np_['unit_name'] if unit_id else '', 'grade': 1,
            'reports_to_position_id': None, 'reports_to_title': '',
            'headcount_target': max(1, np_['count']), 'headcount_actual': np_['count'], 'salary_grade': '',
            'is_active': True, 'created_by': ACTOR, 'created_at': now, 'updated_at': now, 'source': SOURCE})
        made_pos += 1
    renamed = 0
    for eid, old, new in plan['dept_renames']:
        res = await db.rahaza_employees.update_one({'id': eid, 'department': old},
                                                   {'$set': {'department': new, 'updated_at': now}})
        renamed += res.matched_count
    retitled = 0
    for eid, old, new in plan['title_renames']:
        res = await db.rahaza_employees.update_one({'id': eid, 'job_title': old},
                                                   {'$set': {'job_title': new, 'updated_at': now}})
        retitled += res.matched_count
    return {'units': made_units, 'positions': made_pos, 'dept_renamed': renamed, 'title_renamed': retitled}


async def run_all(db, apply: bool, out=print) -> dict:
    out(f"[struktur-dari-karyawan] DB={getattr(db, 'name', DB_NAME)} · "
        f"{'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    plan = await build_plan(db)
    verb = 'dibuat' if apply else 'akan dibuat'
    out(f"  Departemen dipakai karyawan aktif: {plan['active_depts']} · sudah ada di Struktur: "
        f"{len(plan['existing_units'])} · unit {verb}: {len(plan['new_units'])}")
    for nu in plan['new_units']:
        out(f"    + unit '{nu['name']}' ({nu['count']} karyawan aktif)")
    out(f"  Jabatan unit {verb}: {len(plan['new_positions'])} · sudah ada (dilewati): {plan['skipped_positions']}")
    for np_ in plan['new_positions']:
        out(f"    + jabatan '{np_['title']}'" + (f" · {np_['unit_name']}" if np_['unit_name'] else ' · (umum, tanpa unit)'))
    out(f"  Ejaan departemen karyawan diseragamkan: {len(plan['dept_renames'])} · "
        f"ejaan jabatan diseragamkan: {len(plan['title_renames'])}")
    if plan['similar']:
        out(f"  ▲ Departemen MIRIP (tidak digabung — putuskan di Struktur Organisasi): {len(plan['similar'])}")
        for a, b in plan['similar']:
            out(f"      · '{a}' ~ '{b}'")
    if plan['placeholders']:
        out(f"  ▲ Isian jabatan pengganti tidak dibuat sebagai jabatan: "
            f"{', '.join(repr(t) for t in sorted(plan['placeholders']))} ({sum(plan['placeholders'].values())} karyawan)")
    if plan['inactive_only']:
        out(f"  ▲ Departemen yang hanya dipakai karyawan nonaktif (tidak dibuat): {len(plan['inactive_only'])}")
    res = {'units': len(plan['new_units']), 'positions': len(plan['new_positions']),
           'dept_renamed': len(plan['dept_renames']), 'title_renamed': len(plan['title_renames'])}
    if apply:
        res = await apply_plan(db, plan)
        out(f"\n  ditulis: unit {res['units']} · jabatan {res['positions']} · "
            f"ejaan departemen {res['dept_renamed']} · ejaan jabatan {res['title_renamed']}")
    res.update({'existing_units': len(plan['existing_units']), 'skipped_positions': plan['skipped_positions'],
                'similar': len(plan['similar']), 'placeholders': sum(plan['placeholders'].values()),
                'inactive_only': len(plan['inactive_only'])})
    return res


async def run(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    await run_all(db, apply)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    sys.exit(asyncio.run(run(ap.parse_args().apply)))
