"""Tahap 5 (7 Nov 2026) — audit form portal Produksi · Cutting · Maklon · RnD (sisi server).

  1. Order Cutting: pilihan "Gudang Sumber Kain" tidak memuat lokasi KANTOR.
  2. Permak: pilihan PO memuat PO INTERNAL dan maklon (dulu hanya maklon lewat pintu portal klien),
     tanpa PO yang sudah ditutup; item PO dari SSOT progres yang sama.
  3. Komponen Kurang: vendor CMT dari master `vendor_partners` — id wajib ada, nama mengikuti master.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402

USER = {"id": "u1", "name": "Admin Uji", "role": "admin"}


def run(c):
    return asyncio.run(c)


async def _user(*_a, **_k):
    return USER


# ══════════════════════════════════════════════════════════════════════════════
# 1 · Cutting — lokasi kantor tidak ditawarkan sebagai gudang sumber kain
# ══════════════════════════════════════════════════════════════════════════════
def test_cutting_lokasi_tanpa_kantor(monkeypatch):
    import routes.cutting as cut
    db = FakeDB()
    db.rahaza_locations.docs = [
        {"id": "l1", "code": "KTR-PST", "name": "Kantor Pusat", "type": "kantor", "active": True},
        {"id": "l2", "code": "GD-L1", "name": "Gudang Lantai 1", "type": "gudang", "active": True},
        {"id": "l3", "code": "GD-L2-CUT", "name": "Area Cutting", "type": "produksi", "active": True},
        {"id": "l4", "code": "GD-OLD", "name": "Gudang Lama", "type": "gudang", "active": False},
        {"id": "l5", "code": "X", "name": "Lokasi tanpa jenis", "active": True},
    ]
    monkeypatch.setattr(cut, "require_auth", _user)
    monkeypatch.setattr(cut, "get_db", lambda: db)
    rows = run(cut.list_locations(FakeRequest()))
    ids = {r["id"] for r in rows}
    assert ids == {"l2", "l3", "l5"}, ids


# ══════════════════════════════════════════════════════════════════════════════
# 2 · Permak — PO internal ikut bisa dipilih
# ══════════════════════════════════════════════════════════════════════════════
def _permak_env(monkeypatch):
    import routes.dewi_cmt_permak as pmk
    db = FakeDB()
    db.production_pos.docs = [
        {"id": "p1", "po_number": "PO-INT-1", "business_type": "internal", "status": "In Production",
         "customer_name": "Gudang FG", "created_at": "2026-11-01"},
        {"id": "p2", "po_number": "PO-MKL-1", "business_type": "maklon", "status": "Confirmed",
         "customer_name": "Klien A", "created_at": "2026-11-02"},
        {"id": "p3", "po_number": "PO-INT-2", "business_type": "internal", "status": "Closed",
         "created_at": "2026-11-03"},
        {"id": "p4", "po_number": "PO-LAMA", "status": "Draft", "created_at": "2026-10-01"},  # dokumen lama tanpa jenis
    ]
    monkeypatch.setattr(pmk, "require_auth", _user)
    monkeypatch.setattr(pmk, "get_db", lambda: db)
    monkeypatch.setattr(pmk, "_require_admin", lambda u: None)
    return pmk, db


def test_permak_po_options_internal_dan_maklon(monkeypatch):
    pmk, _db = _permak_env(monkeypatch)
    out = run(pmk.permak_po_options(FakeRequest()))
    nums = [o["po_number"] for o in out]
    assert set(nums) == {"PO-INT-1", "PO-MKL-1", "PO-LAMA"}, nums     # PO tertutup tidak ditawarkan
    by = {o["po_number"]: o for o in out}
    assert by["PO-INT-1"]["business_type_label"] == "Internal"
    assert by["PO-MKL-1"]["business_type_label"] == "Maklon"
    assert by["PO-LAMA"]["business_type"] == "internal"                # Tahap 8 §9: tanpa jenis = internal
    only_int = run(pmk.permak_po_options(FakeRequest(), business_type="internal"))
    assert {o["po_number"] for o in only_int} == {"PO-INT-1", "PO-LAMA"}
    only_mkl = run(pmk.permak_po_options(FakeRequest(), business_type="maklon"))
    assert {o["po_number"] for o in only_mkl} == {"PO-MKL-1"}


def test_permak_po_items_dari_ssot_progres(monkeypatch):
    pmk, _db = _permak_env(monkeypatch)
    import services.maklon_progress as mp

    async def prog(db, po_id):
        if po_id != "p1":
            return None
        return {"items": [{"po_item_id": "i1", "sku": "DA-1-HTM-M", "qty_good": 10, "qty_reject_qc": 2}]}
    monkeypatch.setattr(mp, "compute_po_progress", prog)
    out = run(pmk.permak_po_items("p1", FakeRequest()))
    assert out["items"][0]["po_item_id"] == "i1"
    with pytest.raises(HTTPException) as e:
        run(pmk.permak_po_items("tidak-ada", FakeRequest()))
    assert e.value.status_code == 404


def test_permak_po_options_butuh_izin(monkeypatch):
    pmk, _db = _permak_env(monkeypatch)

    def deny(_u):
        raise HTTPException(403, "Akses ditolak")
    monkeypatch.setattr(pmk, "_require_admin", deny)
    with pytest.raises(HTTPException) as e:
        run(pmk.permak_po_options(FakeRequest()))
    assert e.value.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 3 · Komponen Kurang — vendor CMT dari master
# ══════════════════════════════════════════════════════════════════════════════
def _ccr_env(monkeypatch):
    import routes.dewi_cmt_component_requests as ccr
    import core.doc_number_policy as dnp
    db = FakeDB()
    db.vendor_partners.docs = [{"id": "v1", "name": "CMT Sejahtera", "code": "CMT-01", "active": True}]
    db.rahaza_materials.docs = [{"id": "m1", "code": "KAIN-1", "name": "Kain Uji", "type": "fabric", "unit": "kg"}]
    monkeypatch.setattr(ccr, "get_db", lambda: db)

    async def number(*_a, **_k):
        return "REQ-CMP-UJI-1"
    monkeypatch.setattr(dnp, "issue_number", number)
    return ccr, db


def test_komponen_vendor_dari_master(monkeypatch):
    ccr, db = _ccr_env(monkeypatch)
    out = run(ccr.create_request({"request_type": "component", "cmt_partner_id": "v1",
                                  "cmt_partner_name": "ketikan salah",
                                  "items": [{"material_id": "m1", "qty": 2}]}, user=USER))
    assert out["cmt_partner_id"] == "v1"
    assert out["cmt_partner_name"] == "CMT Sejahtera"      # nama ikut master, ketikan diabaikan
    assert out["vendor_id"] == "v1" and out["vendor_name"] == "CMT Sejahtera"
    saved = db.dewi_cmt_component_requests.docs[0]
    assert saved["cmt_partner_name"] == "CMT Sejahtera"


def test_komponen_vendor_tidak_dikenal_ditolak(monkeypatch):
    ccr, _db = _ccr_env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(ccr.create_request({"request_type": "component", "cmt_partner_id": "hantu",
                                "items": [{"material_id": "m1", "qty": 2}]}, user=USER))
    assert e.value.status_code == 400 and "Vendor CMT" in e.value.detail


def test_komponen_tanpa_id_vendor_tetap_seperti_lama(monkeypatch):
    """Dokumen lahir dari inspeksi / data lama (tanpa id) tidak ikut divalidasi."""
    ccr, _db = _ccr_env(monkeypatch)
    out = run(ccr.create_request({"request_type": "component", "cmt_partner_name": "Vendor Lama",
                                  "vendor_id": "v9", "items": [{"material_id": "m1", "qty": 1}]}, user=USER))
    assert out["cmt_partner_name"] == "Vendor Lama" and out["vendor_id"] == "v9"


def test_komponen_ubah_vendor_lewat_master(monkeypatch):
    ccr, db = _ccr_env(monkeypatch)
    db.vendor_partners.docs.append({"id": "v2", "name": "CMT Makmur", "active": True})
    db.dewi_cmt_component_requests.docs = [{"id": "r1", "status": "pending", "request_type": "component",
                                            "cmt_partner_id": "v1", "cmt_partner_name": "CMT Sejahtera"}]
    run(ccr.update_request("r1", {"cmt_partner_id": "v2", "cmt_partner_name": "x"}, user=USER))
    doc = db.dewi_cmt_component_requests.docs[0]
    assert doc["cmt_partner_id"] == "v2" and doc["cmt_partner_name"] == "CMT Makmur"
    assert doc["vendor_id"] == "v2"
    with pytest.raises(HTTPException):
        run(ccr.update_request("r1", {"cmt_partner_id": "hantu"}, user=USER))
