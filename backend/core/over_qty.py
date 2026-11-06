"""core.over_qty — kelebihan qty BOLEH, asal alasan jelas tersimpan (Tahap 2, 6 Nov 2026).

Keputusan owner: di setiap langkah (deklarasi kirim CMT ke DA, terima & QC dari CMT, kirim ke klien,
tagihan) qty boleh melebihi batasnya hanya dengan ALASAN WAJIB yang jelas. Di bawah batas tidak perlu
alasan. Alasan + pengguna + waktu disimpan di PO (`production_pos.over_qty_events`) dan tampil di
riwayat PO 360.

Kontrak API: permintaan yang melebihi batas tanpa alasan dijawab **HTTP 428** (Precondition Required)
dengan pesan yang bisa dibaca staf; layar lalu meminta alasan dan mengirim ulang dengan
`over_qty_reason`. Layar lama yang belum menangani 428 tetap menampilkan pesannya apa adanya.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

logger = logging.getLogger(__name__)

STEP_LABELS = {
    'deklarasi_cmt': 'Deklarasi kirim CMT ke DA',
    'terima_qc': 'Terima & QC dari CMT',
    'kirim_klien': 'Kirim ke klien',
    'tagihan': 'Tagihan klien',
}
MIN_REASON_LEN = 5
OVER_QTY_STATUS = 428


def over_lines(rows: list) -> list:
    """Murni: baris yang qty-nya melebihi batas. rows = [{label, limit, qty, po_item_id?}]."""
    out = []
    for r in rows or []:
        qty, limit = int(r.get('qty') or 0), max(0, int(r.get('limit') or 0))
        if qty > limit:
            out.append({**r, 'qty': qty, 'limit': limit, 'over': qty - limit})
    return out


def describe(over: list) -> str:
    return '; '.join(f"{o.get('label') or o.get('po_item_id') or 'item'}: {o['qty']} pcs, batas {o['limit']} pcs "
                     f"(lebih {o['over']} pcs)" for o in over)


def require_reason(over: list, reason: str | None, step: str) -> str:
    """Kembalikan alasan yang sudah dirapikan; 428 bila ada kelebihan tanpa alasan yang cukup."""
    text = (reason or '').strip()
    if over and len(text) < MIN_REASON_LEN:
        raise HTTPException(OVER_QTY_STATUS, (
            f"{STEP_LABELS.get(step, step)} melebihi batas — {describe(over)}. Isi alasan kelebihan qty "
            f"(minimal {MIN_REASON_LEN} huruf) untuk melanjutkan."))
    return text


async def record(db, po_id: str, step: str, over: list, reason: str, user: dict, ref: dict | None = None) -> list:
    """Simpan kejadian kelebihan qty di PO + jejak aktivitas (muncul di riwayat PO 360)."""
    if not over or not po_id:
        return []
    from auth import log_activity
    now = datetime.now(timezone.utc)
    events = [{'step': step, 'step_label': STEP_LABELS.get(step, step), 'po_item_id': o.get('po_item_id'),
               'label': o.get('label') or '', 'limit': o['limit'], 'qty': o['qty'], 'over': o['over'],
               'reason': reason, 'by': (user or {}).get('name', ''), 'by_id': (user or {}).get('id', ''),
               'at': now, 'ref': ref or {}} for o in over]
    for ev in events:
        await db.production_pos.update_one({'id': po_id}, {'$push': {'over_qty_events': ev}})
    po = await db.production_pos.find_one({'id': po_id}, {'_id': 0, 'po_number': 1}) or {}
    try:
        await log_activity((user or {}).get('id', ''), (user or {}).get('name', ''), 'Kelebihan Qty',
                           'Production PO', f"PO {po.get('po_number', '')} — {STEP_LABELS.get(step, step)}: "
                                            f"{describe(over)}. Alasan: {reason}")
    except Exception as e:  # noqa: BLE001 — alasan sudah tersimpan di PO; jejak aktivitas pelengkap
        logger.warning('[over-qty] jejak aktivitas PO %s gagal dicatat: %s', po_id, e)
    return events
