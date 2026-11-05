"""core.shipment_accessories — aksesoris yang IKUT satu kiriman material ke CMT (2026-11-05).

Keluhan owner (Portal Maklon): "di katalog buyer ada BOM untuk nambah aksesoris dan di pengiriman
CMT tidak langsung terload". Sebabnya (dibuktikan dari kode):
  * kebutuhan aksesoris PO (`po_accessories`) hanya dihitung dari BOM SAAT PO DISIMPAN — BOM template
    yang diubah/ditambah aksesoris sesudahnya tidak pernah sampai ke PO;
  * form Kirim Material CMT hanya MENAMPILKAN kebutuhan seluruh PO (baca saja), dan kiriman NORMAL
    tidak mencatat aksesoris apa pun — Surat Jalan lalu mencetak kebutuhan SELURUH PO di setiap
    kiriman sebagian (aksesoris terhitung dobel di kertas).

Aturan di modul ini (satu tempat, dipakai endpoint pratinjau, pembuatan kiriman, dan uji):
  * PO maklon → BOM PO disegarkan dulu dari template AKTIF (`explode_maklon_bom_for_po`, tanpa
    menimpa BOM yang diatur manual), jadi aksesoris yang baru ditambahkan di Katalog Buyer langsung ikut;
  * jatah kiriman ini = kebutuhan PO × (qty garmen dikirim ÷ qty PO), dibulatkan ke atas untuk satuan
    hitungan (pcs/set/…), dibatasi sisa yang belum pernah dikirim;
  * yang tersimpan per kiriman: `accessory_shipment_items` (koleksi yang sudah dipakai kiriman
    tambahan), sehingga Surat Jalan & inspeksi vendor membaca jumlah kiriman itu sendiri.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import List, Optional

from core.helpers import new_id

logger = logging.getLogger(__name__)

COUNT_UNITS = {'pcs', 'pc', 'buah', 'biji', 'set', 'pair', 'pasang', 'lembar', 'unit', 'lusin', 'kodi'}


def acc_key(a: dict) -> str:
    return (a.get('accessory_id') or (a.get('accessory_code') or a.get('accessory_name') or '')
            .strip().lower())


def share_for_shipment(need: float, po_qty: int, ship_qty: int, before: float, unit: str) -> float:
    """Jatah satu kiriman (murni, diuji unit)."""
    remaining = max(0.0, float(need) - float(before))
    if po_qty <= 0 or ship_qty <= 0 or remaining <= 0:
        return 0.0
    share = float(need) * ship_qty / po_qty
    if (unit or 'pcs').strip().lower() in COUNT_UNITS:
        return float(min(math.ceil(share - 1e-9), math.floor(remaining + 1e-9)))
    return round(min(share, remaining), 3)


async def accessory_plan(db, po_id: str, lines: List[dict], *, refresh_bom: bool = True,
                         user: Optional[dict] = None) -> dict:
    """Usulan aksesoris untuk kiriman garmen `lines` ([{po_item_id, qty_sent}]) dari PO `po_id`."""
    po = await db.production_pos.find_one(
        {'id': po_id}, {'_id': 0, 'id': 1, 'po_number': 1, 'business_type': 1})
    if not po:
        return {'po_id': po_id, 'rows': [], 'warnings': ['PO tidak ditemukan.']}
    warnings: List[str] = []
    if refresh_bom and po.get('business_type') == 'maklon':
        try:
            from routes.dewi_maklon_bom_templates import explode_maklon_bom_for_po
            res = await explode_maklon_bom_for_po(db, po_id, user=user)
            warnings.extend(res.get('warnings') or [])
        except Exception as e:  # noqa: BLE001 — pratinjau tidak boleh gagal karena BOM
            logger.warning('[aksesoris kiriman] BOM PO %s gagal disegarkan: %s', po_id, e)
            warnings.append('BOM PO belum bisa disegarkan dari Katalog Buyer — angka memakai BOM terakhir.')

    items = await db.po_items.find({'po_id': po_id}, {'_id': 0, 'id': 1, 'qty': 1}).to_list(2000)
    po_qty = sum(int(i.get('qty') or 0) for i in items)
    ship_qty = sum(int(ln.get('qty_sent') or 0) for ln in (lines or []))
    needs = await db.po_accessories.find({'po_id': po_id}, {'_id': 0}).to_list(1000)
    sent = await db.accessory_shipment_items.find(
        {'po_id': po_id}, {'_id': 0, 'accessory_id': 1, 'accessory_code': 1, 'accessory_name': 1,
                           'qty_sent': 1}).to_list(10000)
    sent_by = defaultdict(float)
    for a in sent:
        sent_by[acc_key(a)] += float(a.get('qty_sent') or 0)

    rows = []
    for n in needs:
        need = float(n.get('qty_needed') or 0)
        if need <= 0:
            continue
        unit = n.get('unit') or 'pcs'
        before = round(sent_by.get(acc_key(n), 0.0), 3)
        rows.append({
            'accessory_id': n.get('accessory_id') or '',
            'accessory_code': n.get('accessory_code') or '',
            'accessory_name': n.get('accessory_name') or '',
            'unit': unit,
            'qty_needed': need,
            'qty_sent_before': before,
            'qty_remaining': round(max(0.0, need - before), 3),
            'qty_suggested': share_for_shipment(need, po_qty, ship_qty, before, unit),
            'ownership': n.get('ownership') or '',
            'unlinked': bool(n.get('unlinked')),
            'source': n.get('source') or '',
        })
    rows.sort(key=lambda r: (r['accessory_name'] or '').lower())
    return {'po_id': po_id, 'po_number': po.get('po_number'), 'po_qty': po_qty,
            'shipment_qty': ship_qty, 'rows': rows, 'warnings': warnings}


async def record_for_shipment(db, shipment: dict, rows: List[dict]) -> int:
    """Simpan aksesoris yang ikut kiriman ini (qty > 0) ke `accessory_shipment_items`."""
    n = 0
    for a in rows or []:
        q = float(a.get('qty_sent') or 0)
        if q <= 0:
            continue
        await db.accessory_shipment_items.insert_one({
            'id': new_id(), 'shipment_id': shipment['id'],
            'shipment_number': shipment.get('shipment_number'),
            'po_id': shipment.get('po_id'), 'po_number': shipment.get('po_number', ''),
            'accessory_id': a.get('accessory_id') or '', 'accessory_name': a.get('accessory_name') or '',
            'accessory_code': a.get('accessory_code') or '', 'unit': a.get('unit') or 'pcs',
            'qty_sent': int(q) if float(q).is_integer() else q,
            'shipment_type': shipment.get('shipment_type', 'NORMAL'),
            'parent_shipment_id': shipment.get('parent_shipment_id'),
            'source': 'bom_auto' if a.get('auto', True) else 'manual',
            'notes': a.get('notes') or 'Ikut kiriman material (dari BOM)',
            'created_at': shipment.get('created_at'),
        })
        n += 1
    return n
