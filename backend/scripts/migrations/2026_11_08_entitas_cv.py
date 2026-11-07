"""Migrasi 2026-11-08 (Tahap 8 fase 1) — dua buku: CV Dewi Aditya (DA) & CV Sukma (SMU).

KENAPA: sampai Tahap 7 aplikasi berbuku SATU perusahaan; tidak ada penanda CV di jurnal, periode, rekening,
bagan akun, maupun pengaturan perusahaan. Owner (7 Nov 2026) memutuskan buku terpisah per CV di satu
aplikasi. Kode baru menulis `entity` di setiap jurnal; migrasi ini memberi CV pada data LAMA.

LANGKAH (semua aturan ada di kode, `core.entities` — tidak membaca berkas privat):
  1. Rekening kas/bank: pemilik `entity`. GL 1-1213 / 2-2103, atau nama memuat "Sukma Mitra" → SMU; lainnya DA.
  2. Bagan akun: `entities` ("berlaku untuk") menurut aturan kode (`code_rule_entities`, pohon lewat
     `parent_code`); akun GL rekening kas/bank = pemilik rekening.
  3. Jurnal + baris cermin: SMU bila modul sumber maklon ATAU baris menyentuh akun khusus SMU; lainnya DA.
     Jurnal yang menyentuh akun khusus DA DAN khusus SMU = "campur": dimasukkan ke buku DA (buku lama;
     mis. jurnal saldo awal yang memuat beberapa akun Sukma) kecuali modulnya maklon, dan ditandai
     `entity_warning` supaya muncul di laporan cek CV (Perawatan Data Keuangan) untuk dipisah manual.
  4. Periode: dokumen lama = DA; tiap periode DA disalin ke SMU dengan status yang SAMA. Indeks unik lama
     `period_code_1` diganti (CV, kode) — kalau tidak, salinan SMU bertabrakan.
     Indeks idempotensi jurnal diganti (modul, ref, CV).
  5. Pengaturan perusahaan: dokumen lama (`type: general`) = DA; profil SMU dibuat ("CV Sukma Mitra Utama",
     NPWP kosong, non-PKP).
  6. Faktur piutang/hutang lama: `entity` (penanda maklon → SMU, lainnya DA) supaya daftar per CV cepat.

Sifat: idempoten (hanya mengisi yang kosong; aman diulang), tanpa hapus data, hanya mencetak JUMLAH.
Bawaan PRATINJAU; tulis dengan --apply.

Runbook (VPS) — sesudah deploy kode Tahap 8:
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_entitas_cv.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_08_entitas_cv.py --apply
"""
import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.entities import (  # noqa: E402
    BOTH, DA, MAKLON_SOURCE_MODULES, PROFILE_TYPE, SMU, code_rule_entities, entity_of_doc, normalize_entities,
)

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
SMU_CASH_GL = ('1-1213', '2-2103')
SMU_NAME_HINT = 'sukma mitra'
CHUNK = 500
MIXED_WARNING = ("Jurnal lama menyentuh akun khusus CV Dewi Aditya dan akun khusus CV Sukma (migrasi Tahap 8). "
                 "Dimasukkan ke buku ini; pisahkan bagian CV lain lewat jurnal manual bila perlu.")


def _now():
    return datetime.now(timezone.utc)


# ── aturan murni (diuji unit) ────────────────────────────────────────────────
def cash_owner_rule(acc: dict) -> str:
    """Pemilik rekening kas/bank lama menurut aturan owner."""
    if (acc.get('gl_account_code') or '') in SMU_CASH_GL:
        return SMU
    if SMU_NAME_HINT in str(acc.get('name') or '').lower():
        return SMU
    return DA


def ancestors_of(code: str, parent_by_code: dict, limit: int = 10) -> list:
    out, cur, seen = [], parent_by_code.get(code), {code}
    while cur and cur not in seen and len(out) < limit:
        out.append(cur)
        seen.add(cur)
        cur = parent_by_code.get(cur)
    return out


def coa_entities_for(code: str, parent_by_code: dict, cash_owner_by_gl: dict) -> list:
    """`entities` akun: akun GL rekening = pemilik rekening; selain itu aturan kode (dengan pohon induk)."""
    if code in cash_owner_by_gl:
        return [cash_owner_by_gl[code]]
    return code_rule_entities(code, ancestors_of(code, parent_by_code))


def journal_entity(je: dict, entities_by_code: dict) -> tuple:
    """(CV, campur?) untuk jurnal lama tanpa `entity`.
    SMU bila modul maklon atau ada baris di akun khusus SMU; campur = menyentuh akun khusus DA dan khusus SMU
    → buku DA (kecuali modul maklon), ditandai untuk diperiksa."""
    codes = {str(ln.get('account_code') or '') for ln in (je.get('lines') or [])}
    ents = [entities_by_code.get(c) or code_rule_entities(c) for c in codes if c]
    smu_only = any(e == [SMU] for e in ents)
    da_only = any(e == [DA] for e in ents)
    maklon = (je.get('source_module') or '') in MAKLON_SOURCE_MODULES
    mixed = smu_only and da_only
    if maklon:
        return SMU, mixed
    return (DA if mixed else (SMU if smu_only else DA)), mixed


# ── langkah ──────────────────────────────────────────────────────────────────
async def step_cash_accounts(db, apply: bool) -> dict:
    out = {'total': 0, 'already': 0, 'to_DA': 0, 'to_SMU': 0}
    owner_by_gl = {}
    async for a in db.rahaza_cash_accounts.find({}, {'_id': 0, 'id': 1, 'gl_account_code': 1, 'name': 1, 'entity': 1}):
        out['total'] += 1
        if a.get('entity') in (DA, SMU):
            out['already'] += 1
            owner = a['entity']
        else:
            owner = cash_owner_rule(a)
            out[f'to_{owner}'] += 1
            if apply:
                await db.rahaza_cash_accounts.update_one({'id': a['id']}, {'$set': {'entity': owner}})
        if a.get('gl_account_code'):
            owner_by_gl[a['gl_account_code']] = owner
    out['_owner_by_gl'] = owner_by_gl
    return out


async def step_coa(db, apply: bool, owner_by_gl: dict) -> dict:
    accs = await db.rahaza_coa_accounts.find({}, {'_id': 0, 'code': 1, 'parent_code': 1, 'entities': 1}).to_list(None)
    parent = {a['code']: a.get('parent_code') for a in accs if a.get('code')}
    out = {'total': len(accs), 'already': 0, 'DA': 0, 'SMU': 0, 'both': 0, 'cash_fixed': 0}
    ents_by_code = {}
    for a in accs:
        code = a.get('code')
        if not code:
            continue
        want = coa_entities_for(code, parent, owner_by_gl)
        cur = None
        if a.get('entities'):
            try:
                cur = normalize_entities(a['entities'])
            except ValueError:
                cur = None
        if cur and not (code in owner_by_gl and cur != want):
            out['already'] += 1
            ents_by_code[code] = cur
            continue
        if cur and code in owner_by_gl:
            out['cash_fixed'] += 1          # akun rekening wajib = pemilik rekening
        key = 'both' if want == BOTH else want[0]
        out[key] += 1
        ents_by_code[code] = want
        if apply:
            await db.rahaza_coa_accounts.update_one({'code': code}, {'$set': {'entities': want}})
    out['_entities_by_code'] = ents_by_code
    return out


async def step_journals(db, apply: bool, ents_by_code: dict) -> dict:
    out = {'journals_without_cv': 0, 'to_DA': 0, 'to_SMU': 0, 'mixed': 0, 'by_reason_maklon_module': 0,
           'lines_set': 0, 'orphan_lines_to_DA': 0, 'mixed_modules': {}}
    ids = {DA: [], SMU: []}
    mixed_ids = []
    async for je in db.rahaza_journal_entries.find(
            {'entity': {'$exists': False}}, {'_id': 0, 'id': 1, 'source_module': 1, 'lines.account_code': 1}):
        out['journals_without_cv'] += 1
        ent, mixed = journal_entity(je, ents_by_code)
        out[f'to_{ent}'] += 1
        if (je.get('source_module') or '') in MAKLON_SOURCE_MODULES:
            out['by_reason_maklon_module'] += 1
        if mixed:
            out['mixed'] += 1
            m = je.get('source_module') or '-'
            out['mixed_modules'][m] = out['mixed_modules'].get(m, 0) + 1
            mixed_ids.append(je['id'])
        ids[ent].append(je['id'])
    if apply:
        for ent, lst in ids.items():
            for i in range(0, len(lst), CHUNK):
                part = lst[i:i + CHUNK]
                await db.rahaza_journal_entries.update_many(
                    {'id': {'$in': part}, 'entity': {'$exists': False}}, {'$set': {'entity': ent}})
        if mixed_ids:
            await db.rahaza_journal_entries.update_many(
                {'id': {'$in': mixed_ids}, 'entity_warning': {'$exists': False}},
                {'$set': {'entity_warning': MIXED_WARNING}})
    # Baris cermin: ikut kepala jurnalnya (juga baris dari kepala yang sudah ber-CV sebelumnya).
    heads = {}
    async for je in db.rahaza_journal_entries.find({'entity': {'$exists': True}}, {'_id': 0, 'id': 1, 'entity': 1}):
        heads[je['id']] = je['entity']
    planned = {**{j: DA for j in ids[DA]}, **{j: SMU for j in ids[SMU]}}
    lines_missing = 0
    by_ent = {DA: [], SMU: []}
    async for ln in db.rahaza_journal_lines.find({'entity': {'$exists': False}}, {'_id': 0, 'je_id': 1}):
        lines_missing += 1
        jid = ln.get('je_id')
        # kepala ber-CV → ikut; kepala belum ber-CV (pratinjau) → hasil aturan; kepala tidak ada → yatim = DA
        ent = heads.get(jid) or planned.get(jid)
        if ent is None:
            out['orphan_lines_to_DA'] += 1
            ent = DA
        by_ent[ent].append(jid)
    out['lines_without_cv'] = lines_missing
    if apply:
        for ent, jids in by_ent.items():
            uniq = sorted({j for j in jids if j})
            for i in range(0, len(uniq), CHUNK):
                r = await db.rahaza_journal_lines.update_many(
                    {'je_id': {'$in': uniq[i:i + CHUNK]}, 'entity': {'$exists': False}}, {'$set': {'entity': ent}})
                out['lines_set'] += r.modified_count
        r = await db.rahaza_journal_lines.update_many({'entity': {'$exists': False}}, {'$set': {'entity': DA}})
        out['lines_set'] += r.modified_count
    return out


async def _drop_index_if(db, coll: str, name: str, cond) -> bool:
    try:
        info = (await db[coll].index_information()).get(name)
    except Exception:  # noqa: BLE001
        return False
    if info is None or not cond(info):
        return False
    await db[coll].drop_index(name)
    return True


async def step_indexes(db, apply: bool) -> dict:
    out = {'period_unique_old': False, 'je_source_unique_old': False}
    try:
        pinfo = await db.rahaza_periods.index_information()
        jinfo = await db.rahaza_journal_entries.index_information()
    except Exception:  # noqa: BLE001
        pinfo, jinfo = {}, {}
    out['period_unique_old'] = bool((pinfo.get('period_code_1') or {}).get('unique'))
    out['je_source_unique_old'] = 'uniq_active_source_ref' in jinfo
    if apply:
        await _drop_index_if(db, 'rahaza_periods', 'period_code_1', lambda i: i.get('unique'))
        await db.rahaza_periods.create_index([('entity', 1), ('period_code', 1)], unique=True, name='uniq_entity_period')
        await _drop_index_if(db, 'rahaza_journal_entries', 'uniq_active_source_ref', lambda i: True)
        await db.rahaza_journal_entries.create_index(
            [('source_module', 1), ('source_ref', 1), ('entity', 1)], unique=True, name='uniq_active_source_ref_entity',
            partialFilterExpression={'status': {'$in': ['posted', 'draft']}, 'source_ref': {'$type': 'string'}})
    return out


async def step_periods(db, apply: bool) -> dict:
    out = {'total_before': 0, 'set_DA': 0, 'copied_to_SMU': 0, 'smu_already': 0}
    rows = await db.rahaza_periods.find({}, {'_id': 0}).to_list(None)
    out['total_before'] = len(rows)
    smu_codes = {r['period_code'] for r in rows if r.get('entity') == SMU}
    for r in rows:
        if r.get('entity') == SMU:
            continue
        if r.get('entity') != DA:
            out['set_DA'] += 1
            if apply:
                await db.rahaza_periods.update_one({'id': r['id']} if r.get('id') else {'period_code': r['period_code'],
                                                                                      'entity': {'$exists': False}},
                                                   {'$set': {'entity': DA}})
        if r['period_code'] in smu_codes:
            out['smu_already'] += 1
            continue
        out['copied_to_SMU'] += 1
        smu_codes.add(r['period_code'])
        if apply:
            copy = {k: v for k, v in r.items() if k not in ('_id',)}
            copy.update({'id': str(uuid.uuid4()), 'entity': SMU, 'copied_from_period_id': r.get('id'),
                         'created_at': _now(), 'copied_by': 'migrasi 2026-11-08'})
            await db.rahaza_periods.insert_one(copy)
    return out


async def step_company(db, apply: bool) -> dict:
    out = {'da_tagged': 0, 'smu_created': 0, 'smu_exists': 0}
    da = await db.company_settings.find_one({'type': 'general'}, {'_id': 0, 'id': 1, 'entity': 1})
    if da and da.get('entity') != DA:
        out['da_tagged'] = 1
        if apply:
            await db.company_settings.update_one({'type': 'general'}, {'$set': {'entity': DA}})
    if await db.company_settings.find_one({'type': PROFILE_TYPE, 'entity': SMU}, {'_id': 1}):
        out['smu_exists'] = 1
    else:
        out['smu_created'] = 1
        if apply:
            await db.company_settings.insert_one({
                'id': str(uuid.uuid4()), 'type': PROFILE_TYPE, 'entity': SMU, 'company_name': 'CV Sukma Mitra Utama',
                'company_address': '', 'company_phone': '', 'company_email': '', 'company_website': '',
                'company_logo_url': '', 'npwp': '', 'pdf_header_line1': '', 'pdf_header_line2': '',
                'pdf_footer_text': '', 'tax_profile': {'pkp': False, 'pkp_since': ''},
                'created_at': _now(), 'updated_at': _now(), 'created_by': 'migrasi 2026-11-08'})
    return out


async def step_invoices(db, apply: bool) -> dict:
    out = {}
    for coll in ('rahaza_ar_invoices', 'rahaza_ap_invoices'):
        cnt = {DA: [], SMU: []}
        async for d in db[coll].find({'entity': {'$exists': False}},
                                     {'_id': 0, 'id': 1, 'source_module': 1, 'linked_maklon_po_id': 1, 'source': 1}):
            cnt[entity_of_doc(d)].append(d['id'])
        out[coll] = {DA: len(cnt[DA]), SMU: len(cnt[SMU])}
        if apply:
            for ent, lst in cnt.items():
                for i in range(0, len(lst), CHUNK):
                    await db[coll].update_many({'id': {'$in': lst[i:i + CHUNK]}, 'entity': {'$exists': False}},
                                               {'$set': {'entity': ent}})
    return out


async def run(db, apply: bool = False) -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[entitas-cv] {mode}")
    ca = await step_cash_accounts(db, apply)
    print(f"  1. rekening kas/bank: {ca['total']} · sudah ber-CV {ca['already']} · → DA {ca['to_DA']} · "
          f"→ SMU {ca['to_SMU']}")
    co = await step_coa(db, apply, ca.pop('_owner_by_gl'))
    print(f"  2. bagan akun: {co['total']} · sudah {co['already']} · khusus DA {co['DA']} · khusus SMU {co['SMU']} · "
          f"keduanya {co['both']} · akun rekening disamakan {co['cash_fixed']}")
    jr = await step_journals(db, apply, co.pop('_entities_by_code'))
    mixed = ", ".join(f"{k} {v}" for k, v in sorted(jr['mixed_modules'].items())) or "-"
    print(f"  3. jurnal tanpa CV: {jr['journals_without_cv']} · → DA {jr['to_DA']} · → SMU {jr['to_SMU']} "
          f"(modul maklon {jr['by_reason_maklon_module']}) · campur {jr['mixed']} [{mixed}]")
    print(f"     baris cermin tanpa CV: {jr['lines_without_cv']} · yatim → DA {jr['orphan_lines_to_DA']}"
          + (f" · ditulis {jr['lines_set']}" if apply else ''))
    ix = await step_indexes(db, apply)
    print(f"  4a. indeks unik lama: periode {'ada' if ix['period_unique_old'] else 'tidak ada'} · "
          f"idempotensi jurnal {'ada' if ix['je_source_unique_old'] else 'tidak ada'}"
          + (" → diganti kunci per CV" if apply else ''))
    pr = await step_periods(db, apply)
    print(f"  4b. periode: {pr['total_before']} · ditandai DA {pr['set_DA']} · disalin ke SMU {pr['copied_to_SMU']} · "
          f"SMU sudah ada {pr['smu_already']}")
    cs = await step_company(db, apply)
    print(f"  5. pengaturan perusahaan: DA ditandai {cs['da_tagged']} · profil SMU dibuat {cs['smu_created']} · "
          f"sudah ada {cs['smu_exists']}")
    iv = await step_invoices(db, apply)
    print("  6. faktur tanpa CV: " + " · ".join(f"{k} DA {v[DA]} / SMU {v[SMU]}" for k, v in iv.items()))
    return {'cash_accounts': ca, 'coa': co, 'journals': jr, 'indexes': ix, 'periods': pr, 'company': cs,
            'invoices': iv}


async def _main(apply: bool):
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        await run(client[DB_NAME], apply=apply)
    finally:
        client.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    asyncio.run(_main(ap.parse_args().apply))
