"""core.po_lock — PO produksi yang SUDAH DITUTUP dikunci (Tahap 2, 6 Nov 2026).

Keputusan owner: PO yang ditutup (Selesai / Ditutup / Ditutup kurang) tidak boleh lagi mendapat
kiriman material ke CMT, penerimaan barang, kiriman ke klien, permak, permintaan komponen, atau
perubahan PO. Berlaku untuk PO maklon DAN PO internal. Satu pintu supaya semua layar memakai
aturan dan pesan yang sama (HTTP 409).
"""
from __future__ import annotations

from fastapi import HTTPException

from core.maklon_ledger import CLOSED_PO_STATUSES

STATUS_LABEL = {'Completed': 'Selesai', 'Closed': 'Ditutup', 'Closed Short': 'Ditutup kurang'}


def closed_message(po: dict, action: str) -> str:
    st = STATUS_LABEL.get(po.get('status'), po.get('status'))
    return (f"PO {po.get('po_number') or ''} sudah ditutup ({st}) — {action} tidak bisa dicatat lagi. "
            "PO yang sudah ditutup terkunci.")


async def assert_po_open(db, po_id: str | None, action: str) -> None:
    """409 bila PO sudah ditutup. PO tidak ditemukan / kosong = biarkan pemanggil memutuskan."""
    if not po_id:
        return
    po = await db.production_pos.find_one({'id': po_id}, {'_id': 0, 'status': 1, 'po_number': 1})
    if po and po.get('status') in CLOSED_PO_STATUSES:
        raise HTTPException(409, closed_message(po, action))


async def assert_pos_open(db, po_ids, action: str) -> None:
    for pid in dict.fromkeys(p for p in (po_ids or []) if p):
        await assert_po_open(db, pid, action)


async def po_ids_of_items(db, items: list) -> list:
    """po_id dari baris (langsung, atau lewat po_item_id)."""
    pids = [it.get('po_id') for it in items or [] if it.get('po_id')]
    poi = [it.get('po_item_id') for it in items or [] if it.get('po_item_id') and not it.get('po_id')]
    if poi:
        async for d in db.po_items.find({'id': {'$in': poi}}, {'_id': 0, 'po_id': 1}):
            if d.get('po_id'):
                pids.append(d['po_id'])
    return list(dict.fromkeys(pids))
