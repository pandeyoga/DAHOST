"""core.catalog_runs — JEJAK + BATALKAN untuk aksi massal katalog (9 Nov 2026, klarifikasi owner §D).

Kenapa ada: aksi cepat Manajemen Katalog (isi harga dari master, tayangkan yang ber-URL, arsipkan, rapikan item
tersembunyi, unggah harga & URL dari Excel) mengubah ratusan item sekali klik. Owner minta setiap perapian massal
**pratinjau → konfirmasi → bisa dibatalkan & terlacak**. Satu mesin untuk semua aksi itu, bukan satu per tombol:

  * setiap aksi yang benar-benar menulis menyimpan SATU dokumen `marketing_catalog_bulk_runs`: siapa, kapan, aksi
    apa, ringkasan, dan per item nilai field SEBELUM & SESUDAH (hanya field yang disentuh);
  * **Batalkan** mengembalikan nilai sebelum — tetapi hanya untuk item yang sejak itu TIDAK diubah orang lain
    (nilai sekarang masih = nilai sesudah). Item yang sudah diubah dilewati dan disebut alasannya, supaya
    pembatalan tidak menimpa pekerjaan orang lain tanpa sepengetahuannya;
  * perubahan harga (dari aksi maupun pembatalannya) tetap tercatat sebagai RIWAYAT HARGA di
    `marketing_change_log` (entitas/aksi yang sama dengan "Ubah item").
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

RUNS = 'marketing_catalog_bulk_runs'
MAX_CHANGES = 5000
PRICE_HISTORY_FIELDS = ('harga_jual', 'harga_coret')
_LEGACY_PRICE = {'harga_jual': 'price', 'harga_coret': 'original_price'}

KIND_LABEL = {
    'isi_harga': 'Isi harga dari master',
    'transisi:publish': 'Tayangkan yang ber-URL',
    'transisi:unpublish': 'Jadikan draf',
    'transisi:archive': 'Arsipkan',
    'transisi:restore': 'Kembalikan dari arsip',
    'transisi:preorder': 'Tandai pra-pesan',
    'transisi:unpreorder': 'Lepas pra-pesan',
    'transisi:reject': 'Tandai ditolak platform',
    'rapikan_tersembunyi': 'Rapikan item tersembunyi',
    'unggah_harga_url': 'Unggah harga & URL dari Excel',
}

# Nama field untuk pesan "sudah diubah sesudah aksi ini" (bahasa staf, bukan nama field program).
FIELD_LABEL = {
    'harga_jual': 'harga jual', 'price': 'harga jual', 'harga_coret': 'harga coret', 'original_price': 'harga coret',
    'platform_price': 'harga di platform', 'platform_url': 'URL produk', 'publish_state': 'penayangan',
    'is_active': 'aktif/nonaktif', 'is_preorder': 'pra-pesan', 'catalog_id': 'katalog',
    'retail_price_master': 'harga resmi master', 'rejected_reason': 'alasan ditolak',
    'archived_reason': 'alasan arsip', 'merged_into': 'gabungan', 'platform_sku_ids': 'pemetaan SKU platform',
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def snapshot(item: dict, keys: Iterable[str]) -> dict:
    """Nilai field `keys` pada item (yang tidak ada → None)."""
    item = item or {}
    return {k: item.get(k) for k in keys}


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(float(a) - float(b)) < 1e-9
    if a in (None, '') and b in (None, ''):
        return True
    return a == b


def _actor(user: Optional[dict]) -> dict:
    u = user or {}
    return {'actor_id': u.get('id', ''), 'actor_name': u.get('name') or u.get('email') or '',
            'actor_role': u.get('role', '')}


async def log_price_change(db, item: dict, new_values: dict, *, account_id=None, user=None, reason: str = '',
                           action: str = 'price_change') -> None:
    """Riwayat harga katalog (harga jual & harga coret) — SATU penulis, dipakai "Ubah item" dan aksi massal."""
    def _old(k):
        v = item.get(k) if item.get(k) is not None else item.get(_LEGACY_PRICE[k])
        return float(v or 0)
    before, after = {}, {}
    for k in PRICE_HISTORY_FIELDS:
        if k in new_values and new_values[k] is not None and float(new_values[k] or 0) != _old(k):
            before[k], after[k] = _old(k), float(new_values[k] or 0)
    if not after:
        return
    from core.marketing_cycle import log_change
    await log_change(db, account_id=account_id or item.get('account_id'), entity='catalog_item',
                     entity_id=item.get('id'), action=action, before=before, after=after, reason=reason, user=user)


async def record(db, *, kind: str, user: Optional[dict], changes: list, summary: dict,
                 catalog_ids: Iterable[str] = (), extra: Optional[dict] = None) -> dict:
    """Simpan jejak satu aksi massal → dokumen ringkas (tanpa daftar perubahan)."""
    changes = list(changes or [])[:MAX_CHANGES]
    doc = {
        'id': str(uuid.uuid4()),
        'kind': kind,
        'kind_label': KIND_LABEL.get(kind, kind),
        'catalog_ids': sorted({c for c in catalog_ids if c} | {c.get('catalog_id') for c in changes
                                                                if c.get('catalog_id')}),
        **_actor(user),
        'at': _now(),
        'summary': summary or {},
        'n_changes': len(changes),
        'changes': changes,
        'extra': extra or {},
        'undone': False,
    }
    await db[RUNS].insert_one(dict(doc))
    doc.pop('_id', None)
    return public(doc)


def public(run: dict) -> dict:
    """Bentuk untuk layar: tanpa daftar perubahan per item (bisa ribuan)."""
    out = {k: v for k, v in (run or {}).items() if k not in ('changes', '_id')}
    for k in ('at', 'undone_at'):
        if isinstance(out.get(k), datetime):
            out[k] = out[k].isoformat()
    return out


async def list_runs(db, *, catalog_ids: Optional[list] = None, limit: int = 20) -> list:
    q: dict = {}
    if catalog_ids is not None:
        q['catalog_ids'] = {'$in': list(catalog_ids)}
    rows = await db[RUNS].find(q, {'_id': 0, 'changes': 0}).sort('at', -1).limit(limit).to_list(limit)
    return [public(r) for r in rows]


class RunError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


async def undo(db, run_id: str, user: Optional[dict]) -> dict:
    """Kembalikan nilai SEBELUM untuk setiap item yang belum diubah orang lain sejak aksi itu."""
    run = await db[RUNS].find_one({'id': run_id}, {'_id': 0})
    if not run:
        raise RunError(404, 'Riwayat aksi massal tidak ditemukan.')
    if run.get('undone'):
        raise RunError(409, 'Aksi ini sudah dibatalkan sebelumnya.')
    now = _now()
    who = (user or {}).get('email') or (user or {}).get('id', '')
    label = run.get('kind_label') or KIND_LABEL.get(run.get('kind'), run.get('kind'))
    restored, conflicts = [], []
    touched_catalogs: set = set()
    for ch in run.get('changes') or []:
        cur = await db.marketing_catalog_items.find_one({'id': ch.get('item_id')}, {'_id': 0})
        if not cur:
            conflicts.append({'item_id': ch.get('item_id'), 'sku': ch.get('sku'), 'why': 'item sudah dihapus'})
            continue
        after = ch.get('after') or {}
        changed = [k for k, v in after.items() if not isinstance(v, datetime) and not _same(cur.get(k), v)]
        if changed:
            what = ', '.join(sorted({FIELD_LABEL.get(k, 'data lain') for k in changed}))
            conflicts.append({'item_id': cur['id'], 'sku': cur.get('sku'),
                              'why': f'sudah diubah sesudah aksi ini ({what}) — tidak ditimpa'})
            continue
        before = ch.get('before') or {}
        set_ = {k: v for k, v in before.items() if v is not None}
        unset = {k: '' for k, v in before.items() if v is None}
        set_.update({'updated_at': now, 'updated_by': who})
        upd = {'$set': set_,
               '$push': {'status_history': {'$each': [{'at': now, 'by': who, 'action': 'undo',
                                                        'note': f'Batalkan: {label}'}], '$slice': -50}}}
        if unset:
            upd['$unset'] = unset
        await db.marketing_catalog_items.update_one({'id': cur['id']}, upd)
        if any(k in before for k in PRICE_HISTORY_FIELDS):
            await log_price_change(db, cur, {k: before.get(k) for k in PRICE_HISTORY_FIELDS if k in before},
                                   user=user, reason=f'Batalkan: {label}')
        restored.append({'item_id': cur['id'], 'sku': cur.get('sku')})
        for c in (cur.get('catalog_id'), before.get('catalog_id')):
            if c:
                touched_catalogs.add(c)
    removed_catalogs = []
    for cid in (run.get('extra') or {}).get('created_catalog_ids') or []:
        if await db.marketing_catalog_items.count_documents({'catalog_id': cid}) == 0:
            await db.marketing_catalogs.delete_one({'id': cid})
            removed_catalogs.append(cid)
            touched_catalogs.discard(cid)
    result = {'restored': len(restored), 'conflicts': conflicts[:200], 'n_conflicts': len(conflicts),
              'removed_catalogs': removed_catalogs}
    await db[RUNS].update_one({'id': run_id}, {'$set': {
        'undone': True, 'undone_at': now, 'undone_by': who, 'undo_result': result}})
    return {**result, 'touched_catalogs': sorted(touched_catalogs), 'kind_label': label}
