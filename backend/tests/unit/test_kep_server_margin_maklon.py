"""Keputusan owner 8 Nov 2026 (butir 5): margin maklon terealisasi pada dasar yang SEPADAN.

Pendapatan = pcs yang sudah dikirim ke klien × harga jasa, tetapi total HPP memuat bahan untuk SEMUA pcs yang sudah
dikirim ke CMT → PO berjalan tampak bermargin kecil/minus. Margin terealisasi = pendapatan − biaya pcs yang sudah
dikirim (bahan per pcs dikirim ke CMT × pcs terkirim + upah CMT & permak pro-rata pcs terkirim ÷ pcs lolos QC).
Angka ini hanya tampilan/laporan (tidak ada jurnal yang membacanya); `margin` lama tetap = pendapatan − total biaya.
Angka harapan dihitung tangan di komentar. Hermetik: Mongo palsu.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from p3_fakes import FakeDB  # noqa: E402
from core import dispatch_capacity as dcap  # noqa: E402
from core import hpp_aktual as ha  # noqa: E402
import routes.rahaza_hpp as rh  # noqa: E402


def _db():
    return FakeDB(
        production_pos=[{"id": "PM1", "po_number": "PO-UJI-MRG", "business_type": "maklon", "status": "In Production",
                         "customer_name": "Klien Uji", "buyer_id": "cl-uji"}],
        po_items=[{"id": "pm-1", "po_id": "PM1", "qty": 100, "sku": "UJI-MRG", "cmt_price_snapshot": 12000,
                   "selling_price_snapshot": 20000}],
        vendor_shipment_items=[{"shipment_id": "SJM", "po_item_id": "pm-1", "qty_sent": 100}],
        vendor_shipments=[{"id": "SJM", "status": "sent"}],
        rahaza_materials=[{"id": "kcg", "code": "KCG-01", "type": "accessory", "unit_cost": 1000}],
        rahaza_material_issues=[{"id": "MIM", "mi_number": "MI-UJI-M", "po_id": "PM1", "shipment_id": "SJM",
                                 "cost_target": "maklon", "status": "issued",
                                 "items": [{"material_id": "kcg", "qty_issued": 100, "unit_cost_applied": 1000,
                                            "kind": "aksesoris"}]}],
        dewi_cmt_payments=[{"id": "BM", "po_id": "PM1", "subtotal": 1080000, "total_pcs": 90, "status": "posted"}],
        dewi_cmt_permak=[{"id": "PK", "po_id": "PM1", "po_item_id": "pm-1", "total_cost": 9000}],
    )


def _fig(monkeypatch, accepted, dispatched):
    async def fake(db, ids):
        return {i: {"accepted_total": accepted, "dispatched": dispatched, "shipped": dispatched} for i in ids or []}
    monkeypatch.setattr(dcap, "po_item_quantities", fake)
    db = _db()
    return asyncio.run(ha.po_hpp_many(db, db.production_pos.docs, with_overhead=False))[0]


def test_margin_terealisasi_dasar_sepadan(monkeypatch):
    f = _fig(monkeypatch, accepted=90, dispatched=80)
    # total biaya s.d. kini = aksesoris 100.000 + CMT 1.080.000 + permak 9.000
    assert f["total_hpp"] == 1189000.0
    # pendapatan 80 × 20.000; margin lama = 1.600.000 − 1.189.000
    assert f["revenue"] == 1600000.0 and f["margin"] == 411000.0
    # biaya pcs terkirim = aksesoris 1.000 × 80 + (1.080.000 + 9.000) × 80/90 = 80.000 + 968.000 = 1.048.000
    assert f["realized_cost"] == 1048000.0
    assert f["realized_cost"] == round(f["hpp_per_pcs"] * 80, 2)        # = HPP per pcs lolos QC × pcs terkirim
    assert f["margin_realized"] == 552000.0 and f["margin_realized_pct"] == 34.5
    assert f["cost_not_shipped"] == 141000.0                           # biaya pcs yang belum dikirim ke klien


def test_po_berjalan_belum_kirim_tidak_tampak_rugi(monkeypatch):
    f = _fig(monkeypatch, accepted=0, dispatched=0)
    assert f["margin"] == -1189000.0                                   # rumus lama: tampak rugi seluruh biaya
    assert f["realized_cost"] == 0.0 and f["margin_realized"] == 0.0 and f["margin_realized_pct"] is None
    assert f["cost_not_shipped"] == 1189000.0


def test_semua_terkirim_margin_sama_dengan_total(monkeypatch):
    f = _fig(monkeypatch, accepted=100, dispatched=100)
    assert f["realized_cost"] == f["total_hpp"] and f["margin_realized"] == f["margin"]


def test_ringkasan_daftar_hpp(monkeypatch):
    f = _fig(monkeypatch, accepted=90, dispatched=80)
    internal = {"total_hpp": 500.0, "qty_accepted": 0, "absorbed_cost": 0, "unabsorbed_cost": 0,
                "business_type": "internal", "realized_cost": None}
    s = rh._summary([f, internal], "")
    assert s["revenue"] == 1600000.0 and s["cost_to_date"] == 1189000.0
    assert s["realized_cost"] == 1048000.0 and s["margin_realized"] == 552000.0 and s["margin_realized_pct"] == 34.5
    assert s["margin"] == 411000.0                                      # kunci lama tetap untuk pemanggil lama


def test_margin_tidak_dibaca_jurnal():
    """Syarat keputusan: rumus boleh ditambah karena margin hanya tampilan — tidak ada poster jurnal yang membacanya."""
    for rel in ("routes/rahaza_posting.py", "core/maklon_ledger.py", "core/po_wip.py"):
        src = Path(BACKEND, rel).read_text(encoding="utf-8")
        assert "margin_realized" not in src and "maklon_actual_costs" not in src and '["margin"]' not in src, rel
