"""Status sampel maklon — SATU tempat aturan & tanda "sampel belum disetujui" (Tahap 9, keputusan 9–10).

Keputusan owner 7 Nov 2026:
  9. Sampel dibuat SESUDAH PO ada: sampel menjadi tab di rincian PO maklon (bukan menu sendiri).
 10. Peringatan saja: PO maklon tanpa sampel yang disetujui diberi tanda "Sampel belum disetujui".
     Form Kirim ke CMT boleh menampilkan peringatan, tetapi kiriman TETAP bisa jalan (tidak ada blokir).

Pembaca:
  - daftar & rincian PO (`routes/production_pos.get_pos`, `core/po_detail`) → `sample_flags()`;
  - endpoint sampel staf (`routes/dewi_maklon_samples`) → `assert_transition()` dan `resolve_po_for_sample()`.
Form Kirim ke CMT (`core.kirim_cmt.sample_warning`) juga membaca lewat `sample_flags()` — satu penilai.

Sampel lama menyimpan id PO di `order_id` (id cermin = id `production_pos`), sampel baru di `po_id` DAN
`order_id`. Semua kueri per PO memakai `sample_query_for_po()` supaya keduanya terbaca.
"""
from __future__ import annotations

from fastapi import HTTPException

SAMPLE_STATUSES = ('draft', 'in_progress', 'submitted', 'approved', 'rejected', 'revision_requested')
APPROVED = 'approved'

STATUS_LABELS = {
    'draft': 'Draf',
    'in_progress': 'Sedang dibuat',
    'submitted': 'Menunggu persetujuan klien',
    'approved': 'Disetujui',
    'rejected': 'Ditolak',
    'revision_requested': 'Perlu revisi',
}

# Aksi → status asal yang sah. "Ubah" = semua status kecuali disetujui.
TRANSITIONS = {
    'submit': ('draft', 'in_progress', 'revision_requested'),
    # persetujuan/penolakan staf (mis. klien menyetujui lewat telepon) — sama dengan Portal Klien
    'approve': ('submitted', 'revision_requested'),
    'reject': ('submitted', 'revision_requested'),
    # revisi HANYA dari sampel yang sedang menunggu persetujuan (dulu tanpa pemeriksaan sama sekali)
    'revision': ('submitted',),
    'edit': ('draft', 'in_progress', 'submitted', 'rejected', 'revision_requested'),
    'delete': ('draft', 'in_progress', 'submitted', 'rejected', 'revision_requested'),
}

ACTION_LABELS = {
    'submit': 'dikirim ke klien', 'approve': 'disetujui', 'reject': 'ditolak',
    'revision': 'dimintakan revisi', 'edit': 'diubah', 'delete': 'dihapus',
}

WARNING_LABEL = 'Sampel belum disetujui'
# PO yang sudah ditutup tidak perlu diberi peringatan lagi.
_CLOSED_PO = ('Closed', 'Closed Short', 'Completed', 'Cancelled')


def status_label(status: str | None) -> str:
    return STATUS_LABELS.get(str(status or ''), str(status or '-'))


def can(action: str, status: str | None) -> bool:
    return str(status or 'draft') in TRANSITIONS.get(action, ())


def assert_transition(action: str, status: str | None) -> None:
    """Tolak aksi yang tidak sah dari status sekarang, dengan kalimat yang dipahami staf."""
    if can(action, status):
        return
    allowed = ', '.join(status_label(s).lower() for s in TRANSITIONS.get(action, ()))
    raise HTTPException(400, f"Sampel berstatus {status_label(status).lower()} tidak bisa "
                             f"{ACTION_LABELS.get(action, action)}. Hanya sampel {allowed}.")


def sample_query_for_po(po_id: str) -> dict:
    return {'$or': [{'po_id': po_id}, {'order_id': po_id}]}


def po_sample_state(samples: list, po_status: str | None = None) -> dict:
    """Murni: ringkasan sampel satu PO → {count, approved, pending, latest_status, warning, label}."""
    rows = sorted(samples or [], key=lambda s: str(s.get('created_at') or ''), reverse=True)
    approved = sum(1 for s in rows if s.get('status') == APPROVED)
    pending = sum(1 for s in rows if s.get('status') in ('submitted', 'revision_requested'))
    latest = rows[0].get('status') if rows else None
    warning = approved == 0 and str(po_status or '') not in _CLOSED_PO
    return {
        'count': len(rows), 'approved': approved, 'pending': pending,
        'latest_status': latest, 'latest_label': status_label(latest) if latest else '',
        'has_approved': approved > 0, 'warning': warning,
        'label': WARNING_LABEL if warning else ('Sampel disetujui' if approved else ''),
    }


async def sample_flags(db, pos: list) -> dict:
    """{po_id: state} untuk PO maklon di `pos` (dokumen production_pos). PO internal dilewati."""
    from core.entities import is_maklon_po
    mk = {p['id']: p for p in (pos or []) if p.get('id') and is_maklon_po(p)}
    if not mk:
        return {}
    ids = list(mk)
    by_po: dict = {pid: [] for pid in ids}
    async for s in db.dewi_maklon_samples.find(
            {'$or': [{'po_id': {'$in': ids}}, {'order_id': {'$in': ids}}]},
            {'_id': 0, 'id': 1, 'po_id': 1, 'order_id': 1, 'status': 1, 'created_at': 1}):
        pid = s.get('po_id') if s.get('po_id') in by_po else s.get('order_id')
        if pid in by_po:
            by_po[pid].append(s)
    return {pid: po_sample_state(rows, mk[pid].get('status')) for pid, rows in by_po.items()}


async def po_sample_flag(db, po_id: str) -> dict | None:
    """Tanda satu PO (None bila bukan PO maklon) — untuk form Kirim ke CMT dan rincian PO."""
    po = await db.production_pos.find_one({'id': po_id}, {'_id': 0, 'id': 1, 'business_type': 1, 'status': 1})
    if not po:
        return None
    return (await sample_flags(db, [po])).get(po_id)


async def resolve_po_for_sample(db, ref: str | None) -> dict | None:
    """Id/nomor PO (production_pos ATAU cermin lama dewi_maklon_pos) → data PO utama untuk sampel.

    Urutan: production_pos (id, lalu nomor) → cermin (id, lalu nomor; ikut `production_po_id` bila ada).
    Kembali {po_id, po_number, client_id, client_name, business_type, source} atau None."""
    ref = (ref or '').strip()
    if not ref:
        return None

    def _main(po: dict) -> dict:
        return {'po_id': po['id'], 'po_number': po.get('po_number') or '',
                'client_id': po.get('buyer_id') or '', 'client_name': po.get('customer_name') or '',
                'business_type': po.get('business_type') or 'internal', 'source': 'production_pos'}

    po = (await db.production_pos.find_one({'id': ref}, {'_id': 0})
          or await db.production_pos.find_one({'po_number': ref}, {'_id': 0}))
    if po:
        return _main(po)
    mirror = (await db.dewi_maklon_pos.find_one({'id': ref}, {'_id': 0})
              or await db.dewi_maklon_pos.find_one({'po_number': ref}, {'_id': 0}))
    if not mirror:
        return None
    if mirror.get('production_po_id'):
        main = await db.production_pos.find_one({'id': mirror['production_po_id']}, {'_id': 0})
        if main:
            return _main(main)
    return {'po_id': mirror.get('id'), 'po_number': mirror.get('po_number') or '',
            'client_id': mirror.get('client_id') or '', 'client_name': mirror.get('client_name') or '',
            'business_type': 'maklon', 'source': 'dewi_maklon_pos'}
