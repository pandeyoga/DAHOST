"""Migrasi 2026-11-06 (Tahap 2, paket HPP) — pulihkan HPP FG/katalog yang tertimpa.

KENAPA: sampai 6 Nov 2026 ada dua penulis lain selain "Terapkan HPP per Potong":
  * suntingan master produk (`propagate_master_changes` / `ensure_fg_material`) menimpa HPP SEMUA FG
    dan item katalog dengan RATA-RATA model (HPP per warna/ukuran hilang);
  * kalkulator R&D (simpan, bahkan draf) menimpa model + semua FG + katalog dengan satu angka R&D.
Kedua jalur itu sudah ditutup. Migrasi ini mengembalikan angka yang tertimpa.

ATURAN
  1. Kebenaran per FG = penerapan "Terapkan HPP per Potong" TERAKHIR (`product_cost_snapshots
     .applied_sizes[]`: per warna lewat `fg_id`, atau per ukuran untuk semua FG model+ukuran itu).
     FG yang tidak pernah diterapkan TIDAK disentuh.
  2. FG yang `hpp`-nya berbeda dari angka itu (atau sumbernya bukan 'bom') → dipulihkan, beserta
     rincian (`hpp_breakdown`) penerapan tersebut.
  3. Item katalog FG tersebut → `hpp` = urutan katalog yang SATU (`core.catalog_margin
     .resolve_catalog_hpp`: WAC aktual → HPP standar FG → model). Item ber-WAC tidak disentuh.
  4. Model yang punya `hpp_bom` tetapi `hpp` efektifnya ditimpa R&D → `hpp` = hasil `resolve_hpp`.
  5. Dokumen R&D TIDAK diubah: kalkulator R&D kini hanya menyimpan dokumennya sendiri dan HPP
     yang dibawa saat promosi dihitung ulang dengan aturan owner (`rnd_hpp_owner_rule`), jadi
     overhead 10% lama di riwayat R&D tidak lagi masuk HPP mana pun. Jumlahnya hanya dilaporkan.

Sifat: idempoten, tanpa hapus, mencetak JUMLAH saja. Bawaan PRATINJAU; tulis dengan --apply.

Runbook (VPS):
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_hpp_pulihkan.py
    docker compose --env-file .env exec -T backend python scripts/migrations/2026_11_06_hpp_pulihkan.py --apply
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import catalog_margin as cm  # noqa: E402
from core import product_master as pm  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
EPS = 0.005


# ── perencanaan (murni, tanpa DB — diuji unit) ───────────────────────────────
def _key(v) -> str:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return str(v or '')


def latest_applied(snapshots: list) -> tuple:
    """({fg_id: entri}, {(model_id, size_id): entri}) dari penerapan TERAKHIR per sasaran."""
    by_fg, by_size = {}, {}
    for s in sorted(snapshots or [], key=lambda d: _key(d.get('created_at'))):
        for a in s.get('applied_sizes') or []:
            hpp = float(a.get('hpp_unit') or 0)
            if hpp <= 0:
                continue
            entry = {'hpp': round(hpp, 2), 'breakdown': a.get('breakdown') or {}, 'at': s.get('created_at'),
                     'model_id': s.get('model_id'), 'size_id': a.get('size_id')}
            if a.get('fg_id'):
                by_fg[a['fg_id']] = entry
            elif a.get('size_id'):
                by_size[(s.get('model_id'), a['size_id'])] = entry
    return by_fg, by_size


def fg_target(fg: dict, by_fg: dict, by_size: dict):
    """Entri penerapan yang berlaku untuk satu FG (per warna menang atas per ukuran)."""
    return by_fg.get(fg.get('id')) or by_size.get((fg.get('model_id'), fg.get('size_id')))


def fg_needs_restore(fg: dict, target: dict | None) -> bool:
    if not target:
        return False
    return abs(float(fg.get('hpp') or 0) - target['hpp']) > EPS or (fg.get('hpp_source') or '') != 'bom'


def item_target(item: dict, fg_after: dict, model: dict | None):
    """(hpp, sumber) baru untuk item katalog, atau None bila tidak perlu diubah."""
    if (item.get('hpp_source') or '') == 'wac':
        return None
    hpp, src = cm.resolve_catalog_hpp(fg_after, model)
    if hpp <= 0:
        return None
    if abs(float(item.get('hpp') or 0) - hpp) <= EPS and (item.get('hpp_source') or '') == src:
        return None
    return hpp, src


def model_target(model: dict):
    """`hpp` efektif model yang benar (resolve_hpp) bila `hpp_bom` ada tetapi `hpp` tertimpa."""
    if float(model.get('hpp_bom') or 0) <= 0:
        return None
    hpp, src = pm.resolve_hpp({k: v for k, v in model.items() if k != 'hpp'})
    if abs(float(model.get('hpp') or 0) - hpp) <= EPS and (model.get('hpp_source') or '') == src:
        return None
    return hpp, src


# ── jalankan (DB) ────────────────────────────────────────────────────────────
async def plan_and_apply(db, apply: bool) -> dict:
    now = datetime.now(timezone.utc)
    snaps = await db.product_cost_snapshots.find(
        {}, {'_id': 0, 'model_id': 1, 'applied_sizes': 1, 'created_at': 1}).to_list(200000)
    by_fg, by_size = latest_applied(snaps)
    model_ids = sorted({e['model_id'] for e in list(by_fg.values()) + list(by_size.values()) if e.get('model_id')})
    fgs = await db.rahaza_materials.find(
        {'type': 'fg', '$or': [{'id': {'$in': list(by_fg)}}, {'model_id': {'$in': model_ids}}]},
        {'_id': 0}).to_list(200000)
    models = {m['id']: m for m in await db.rahaza_models.find({'id': {'$in': model_ids}}, {'_id': 0}).to_list(50000)}
    out = {'snapshots': len(snaps), 'fg_checked': 0, 'fg_restore': 0, 'items_restore': 0,
           'items_kept_wac': 0, 'models_restore': 0, 'rnd_docs_with_overhead': 0}
    for fg in fgs:
        tgt = fg_target(fg, by_fg, by_size)
        if not tgt:
            continue
        out['fg_checked'] += 1
        fg_after = dict(fg)
        if fg_needs_restore(fg, tgt):
            out['fg_restore'] += 1
            fg_after.update({'hpp': tgt['hpp'], 'hpp_source': 'bom'})
            if apply:
                await db.rahaza_materials.update_one({'id': fg['id']}, {'$set': {
                    'hpp': tgt['hpp'], 'hpp_source': 'bom', 'hpp_breakdown': tgt['breakdown'],
                    'hpp_restored_at': now, 'hpp_restored_by': 'migrasi 2026-11-06', 'updated_at': now}})
        items = await db.marketing_catalog_items.find(
            {'$or': [{'fg_material_id': fg['id']}, {'material_id': fg['id']}]}, {'_id': 0}).to_list(500)
        for it in items:
            if (it.get('hpp_source') or '') == 'wac':
                out['items_kept_wac'] += 1
                continue
            t = item_target(it, fg_after, models.get(fg.get('model_id')))
            if not t:
                continue
            out['items_restore'] += 1
            if apply:
                await db.marketing_catalog_items.update_one({'id': it['id']}, {'$set': {
                    'hpp': t[0], 'hpp_source': t[1], 'hpp_updated_at': now, 'updated_at': now}})
    for m in models.values():
        t = model_target(m)
        if not t:
            continue
        out['models_restore'] += 1
        if apply:
            await db.rahaza_models.update_one({'id': m['id']}, {'$set': {
                'hpp': t[0], 'hpp_source': t[1], 'hpp_updated_at': now, 'updated_at': now}})
    out['rnd_docs_with_overhead'] = await db.dewi_rnd_hpp.count_documents(
        {'$or': [{'overhead_pct': {'$gt': 0}}, {'cutting_cost_per_pcs': {'$gt': 0}}]})
    return out


async def run(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    print(f"[hpp-pulihkan] DB={DB_NAME} · {'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'}")
    r = await plan_and_apply(db, apply)
    verb = 'dipulihkan' if apply else 'akan dipulihkan'
    print(f"  penerapan HPP per Potong terbaca : {r['snapshots']}")
    print(f"  FG pernah diterapkan (diperiksa) : {r['fg_checked']}")
    print(f"  FG {verb}                 : {r['fg_restore']}")
    print(f"  item katalog {verb}       : {r['items_restore']} (ber-WAC tidak disentuh: {r['items_kept_wac']})")
    print(f"  model {verb} (hpp efektif): {r['models_restore']}")
    print(f"  dokumen R&D ber-overhead/cutting : {r['rnd_docs_with_overhead']} — riwayat TIDAK diubah "
          "(tidak lagi masuk HPP mana pun)")
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    sys.exit(asyncio.run(run(ap.parse_args().apply)))
