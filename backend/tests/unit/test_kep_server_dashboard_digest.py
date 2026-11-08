"""Keputusan owner 8 Nov 2026 (butir 3): Digest Mingguan & Dashboard Eksekutif membaca sumber resmi.

* Digest: "material di bawah stok minimum" = pembaca stok resmi `core.stock_thresholds` (sama dengan Dashboard
  Gudang & Alert & Reorder) — dulu kolom tersimpan `total_qty < min_stock` (1.111 vs 43).
* `/api/dashboard`: karyawan aktif = `rahaza_employees.active` (bukan akun pengguna); PO dari `production_pos`
  (bukan koleksi lama `rahaza_orders`); output produksi dari sumber Ringkasan Bisnis (progres internal +
  penerimaan dari CMT), juga untuk grafik per minggu `/api/dashboard/analytics`.
Hermetik: Mongo palsu.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import _fake_mongo as fm  # noqa: E402
from _fake_mongo import FakeCollection, FakeCursor, FakeDB  # noqa: E402

import routes.dashboard_routes as dr  # noqa: E402
import routes.dewi_management_tools as mt  # noqa: E402
import routes.rahaza_reports as rr  # noqa: E402
from core import stock_service, stock_thresholds  # noqa: E402
from services import mgmt_analytics as ma  # noqa: E402

TODAY = date(2026, 11, 8)


class _Col(FakeCollection):
    """Tambahan secukupnya untuk endpoint dashboard (tanpa mengubah `_fake_mongo`)."""

    async def distinct(self, field, q=None):
        return sorted({d.get(field) for d in self.docs if fm.match(d, q) and d.get(field) is not None})

    def aggregate(self, pipeline):
        return FakeCursor([])


class _DB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _Col(name)
        return self._cols[name]


async def _auth(_req):
    return {"id": "u1", "name": "Uji", "role": "owner"}


# ── Digest: stok menipis dari pembaca resmi ────────────────────────────────────
def _stock_db():
    db = _DB()
    db.rahaza_materials.docs = [
        # kolom tersimpan total_qty/min_stock (lama) sengaja menyesatkan
        {"id": "m1", "code": "K1", "name": "Kain 1", "active": True, "min_stock_qty": 10, "total_qty": 999, "min_stock": 1},
        {"id": "m2", "code": "K2", "name": "Kain 2", "active": True, "min_stock_qty": 10, "total_qty": 0, "min_stock": 50},
        {"id": "m3", "code": "K3", "name": "Kain 3", "active": True, "total_qty": None, "min_stock": None},
        {"id": "m4", "code": "K4", "name": "Kain 4", "active": True, "reorder_point": 20, "total_qty": 0},
        {"id": "m5", "code": "K5", "name": "Kain 5", "active": False, "min_stock_qty": 10},
    ]
    db.rahaza_material_stock.docs = [
        {"material_id": "m1", "qty": 5},     # di bawah minimum → kritis
        {"material_id": "m2", "qty": 50},    # aman
        {"material_id": "m4", "qty": 15},    # ≤ titik pesan ulang → rendah
    ]
    return db


def test_digest_stok_menipis_sama_dengan_pembaca_resmi(monkeypatch):
    db = _stock_db()
    monkeypatch.setattr(mt, "require_auth", _auth)
    monkeypatch.setattr(mt, "get_db", lambda: db)
    resmi = asyncio.run(stock_thresholds.summary(db))["alerts"]
    alerts = asyncio.run(stock_thresholds.low_stock_alerts(db))   # layar Alert & Reorder
    out = asyncio.run(mt.get_weekly_digest(object(), days=7))["data"]
    assert resmi == 2 == len(alerts)
    assert out["alerts"]["low_stock_materials"] == 2
    assert out["alert_count"] == 2 and out["health"] == "warning"


def test_digest_tidak_lagi_membaca_kolom_tersimpan():
    src = inspect.getsource(mt.get_weekly_digest)
    assert "$total_qty" not in src and "stock_thresholds" in src


# ── /api/dashboard ────────────────────────────────────────────────────────────
def _dash_db():
    db = _DB()
    db.users.docs = [{"id": f"u{n}", "status": "active"} for n in range(10)]
    db.rahaza_employees.docs = [{"id": f"e{n}", "active": True} for n in range(3)] + [
        {"id": "e9", "active": False}, {"id": "e8", "status": "active"}]
    db.rahaza_orders.docs = [{"id": f"o{n}", "status": "confirmed", "due_date": "2026-01-01"} for n in range(5)]
    db.production_pos.docs = [
        {"id": "p1", "po_number": "PO-1", "status": "Draft", "deadline": "2026-11-01", "created_at": "2026-11-01T02:00:00"},
        {"id": "p2", "po_number": "PO-2", "status": "In Production", "deadline": "2026-11-07",
         "created_at": "2026-10-15T02:00:00", "business_type": "maklon"},
        {"id": "p3", "po_number": "PO-3", "status": "Confirmed", "deadline": "2026-11-09",
         "created_at": "2026-11-02T02:00:00"},
        {"id": "p4", "po_number": "PO-4", "status": "Closed", "deadline": "2026-10-01", "created_at": "2026-09-01"},
    ]
    db.production_jobs.docs = [{"id": "j2", "po_id": "p2", "status": "in_progress"}]
    db.production_progress.docs = [
        {"id": "g1", "job_id": "j2", "completed_quantity": 30, "progress_date": "2026-11-05"},
        {"id": "g2", "job_id": "j2", "completed_quantity": 7, "progress_date": "2026-10-20"},
    ]
    db.cmt_receipts.docs = [{"id": "r1", "po_id": "p2", "receipt_date": "2026-11-06", "total_actual": 12}]
    db.rahaza_wip_events.docs = [{"event_type": "output", "event_date": "2026-11-05", "qty": 9999}]
    return db


def _dashboard(monkeypatch, db):
    monkeypatch.setattr(dr, "require_auth", _auth)
    monkeypatch.setattr(dr, "get_db", lambda: db)
    monkeypatch.setattr(dr, "today_wib", lambda: TODAY)
    monkeypatch.setattr(ma, "today_wib", lambda: TODAY)
    return asyncio.run(dr.get_dashboard(object()))


def test_dashboard_karyawan_aktif_bukan_akun(monkeypatch):
    out = _dashboard(monkeypatch, _dash_db())
    assert out["activeEmployees"] == 3


def test_dashboard_po_dari_production_pos(monkeypatch):
    out = _dashboard(monkeypatch, _dash_db())
    assert out["totalPOs"] == 4                       # bukan 5 pesanan lama
    assert out["activePOs"] == 1                      # PO-2 (berjalan), sama dengan Ringkasan Bisnis orders.running
    assert out["delayedPOs"] == 1
    assert [p["po_number"] for p in out["alerts"]["overduePos"]] == ["PO-2"]
    assert [p["po_number"] for p in out["alerts"]["nearDeadlinePos"]] == ["PO-3"]
    assert out["globalProgressPct"] == 25             # 1 selesai dari 4
    assert ma.po_buckets(_dash_db().production_pos.docs)["running"] == out["activePOs"]


def test_dashboard_output_sama_dengan_ringkasan_bisnis(monkeypatch):
    db = _dash_db()
    out = _dashboard(monkeypatch, db)
    months = {m["month"]: m for m in out["monthlyData"]}
    assert list(months)[-1] == "Nov 26" and len(months) == 6
    assert months["Nov 26"]["production"] == 30 + 12  # progres + diterima dari CMT; wip_events (9999) diabaikan
    assert months["Okt 26"]["production"] == 7
    assert months["Nov 26"]["pos"] == 2 and months["Okt 26"]["pos"] == 1
    # rumus yang SAMA dipakai Ringkasan Bisnis
    sc = asyncio.run(ma.domain_scope(db, "all"))
    src = asyncio.run(ma.output_sources(db, sc))
    assert ma.output_in_period(src, "2026-11-01", "2026-11-30") == {"progress": 30, "received": 12, "total": 42}
    assert "output_sources(db, sc)" in inspect.getsource(rr.overview)


def test_analytics_output_per_minggu_sumber_sama(monkeypatch):
    db = _dash_db()
    monkeypatch.setattr(dr, "require_auth", _auth)
    monkeypatch.setattr(dr, "get_db", lambda: db)
    monkeypatch.setattr(dr, "today_wib", lambda: TODAY)

    class _Req:
        query_params = {}
    out = asyncio.run(dr.get_dashboard_analytics(_Req()))
    weeks = out["weeklyThroughput"]
    assert len(weeks) == 8 and weeks[-1]["label"] == (TODAY - timedelta(days=6)).strftime("%d/%m")
    assert weeks[-1]["qty"] == 42                       # 2–8 Nov: 30 progres + 12 diterima
    assert sum(w["qty"] for w in weeks) == 49


def test_ketepatan_kirim_satu_rumus(monkeypatch):
    db = _dash_db()
    db.buyer_shipments.docs = [{"id": "s1", "po_id": "p3"}, {"id": "s2", "po_id": "p2"}]
    db.buyer_shipment_items.docs = [{"shipment_id": "s1", "dispatch_date": "2026-11-08", "qty_shipped": 5},
                                    {"shipment_id": "s2", "dispatch_date": "2026-11-08", "qty_shipped": 5}]
    out = _dashboard(monkeypatch, db)
    st = asyncio.run(ma.on_time_stats(db, asyncio.run(ma.domain_scope(db, "all")), 90))
    assert st["total_po"] == 2 and st["on_time"] == 1
    assert out["onTimeRate"] == round(st["rate_pct"]) == 50
    assert "on_time_stats(db, sc, days)" in inspect.getsource(rr.on_time_delivery)


def test_onhand_dipakai_bukan_kolom_tersimpan():
    db = _stock_db()
    assert asyncio.run(stock_service.onhand_map(["m1"], db=db)) == {"m1": 5}
