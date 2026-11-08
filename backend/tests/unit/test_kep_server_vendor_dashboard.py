"""Keputusan owner 8 Nov 2026 (butir 4): `GET /api/vendor/dashboard` mengirim 8 angka yang dulu dibaca layar
tetapi tidak pernah dikirim server (Material diterima / kurang / cacat, permintaan tambahan & pengganti, kiriman ke
DA, inspeksi menunggu, job lewat tenggat). Definisi = layar vendor yang memuat datanya. Hermetik: Mongo palsu.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402

import core.cmt_override as ov  # noqa: E402
import routes.dashboard_routes as dr  # noqa: E402

V, LAIN = "v1", "v2"


def _db():
    db = FakeDB()
    db.production_jobs.docs = [
        {"id": "j1", "vendor_id": V, "status": "In Progress", "deadline": "2020-01-01T00:00:00", "job_number": "J1",
         "created_at": "2026-11-01"},
        {"id": "j2", "vendor_id": V, "status": "Completed", "deadline": "2020-01-01T00:00:00", "created_at": "2026-11-02"},
        {"id": "j3", "vendor_id": LAIN, "status": "In Progress", "deadline": "2020-01-01T00:00:00", "created_at": "2026-11-03"},
    ]
    db.vendor_material_inspections.docs = [
        {"id": "i1", "vendor_id": V, "shipment_id": "s1", "total_received": 95, "total_missing": 5},
        {"id": "i2", "vendor_id": V, "shipment_id": "s2", "total_received": 40, "total_missing": 0},
        {"id": "i3", "vendor_id": LAIN, "shipment_id": "s9", "total_received": 1000, "total_missing": 100},
    ]
    db.material_defect_reports.docs = [
        {"id": "d1", "vendor_id": V, "defect_qty": 3}, {"id": "d2", "vendor_id": V, "defect_qty": 2},
        {"id": "d3", "vendor_id": LAIN, "defect_qty": 50},
    ]
    db.material_requests.docs = [
        {"id": "r1", "vendor_id": V, "request_type": "ADDITIONAL", "status": "Pending"},
        {"id": "r2", "vendor_id": V, "request_type": "ADDITIONAL", "status": "Approved"},
        {"id": "r3", "vendor_id": V, "request_type": "REPLACEMENT", "status": "Pending"},
        {"id": "r4", "vendor_id": V, "request_type": "REPLACEMENT", "status": "Pending"},
        {"id": "r5", "vendor_id": LAIN, "request_type": "ADDITIONAL", "status": "Pending"},
    ]
    db.buyer_shipments.docs = [{"id": "b1", "vendor_id": V}, {"id": "b2", "vendor_id": V}, {"id": "b3", "vendor_id": LAIN}]
    db.vendor_shipments.docs = [
        {"id": "s1", "vendor_id": V, "status": "Received", "inspection_status": "Inspected"},
        {"id": "s2", "vendor_id": V, "status": "Received", "inspection_status": "Inspected"},
        {"id": "s3", "vendor_id": V, "status": "Received", "inspection_status": "Pending"},
        {"id": "s4", "vendor_id": V, "status": "Received"},
        {"id": "s5", "vendor_id": V, "status": "Sent"},
        {"id": "s6", "vendor_id": LAIN, "status": "Received"},
    ]
    return db


def _run(monkeypatch, user, ctx=None):
    db = _db()

    async def _auth(_req):
        return user

    async def _ov(_req, _user, _db):
        return ctx
    monkeypatch.setattr(dr, "require_auth", _auth)
    monkeypatch.setattr(dr, "get_db", lambda: db)
    monkeypatch.setattr(ov, "resolve_override", _ov)
    return asyncio.run(dr.get_vendor_dashboard(object()))


EXPECTED = {
    "totalReceived": 135, "totalMissing": 5, "totalDefect": 5,
    "pendingAdditional": 1, "pendingReplacement": 2,
    "pendingBuyerShipments": 2, "pendingInspections": 2, "overdueJobs": 1,
}


def test_vendor_menerima_8_angka_miliknya_sendiri(monkeypatch):
    out = _run(monkeypatch, {"id": "u", "role": "cmt_vendor", "cmt_vendor_id": V})
    for k, v in EXPECTED.items():
        assert out[k] == v, k
    assert out["incomingShipments"] == 1 and out["activeJobs"] == 1
    assert out["overdueJobs"] == len(out["alerts"]["overdueJobs"])


def test_staf_atas_nama_vendor_melihat_angka_yang_sama(monkeypatch):
    out = _run(monkeypatch, {"id": "s", "role": "admin_produksi"},
               ctx={"vendor_id": V, "vendor_name": "Vendor Satu"})
    for k, v in EXPECTED.items():
        assert out[k] == v, k


def test_vendor_tanpa_data_semua_nol(monkeypatch):
    out = _run(monkeypatch, {"id": "u", "role": "cmt_vendor", "cmt_vendor_id": "v-kosong"})
    for k in EXPECTED:
        assert out[k] == 0, k
