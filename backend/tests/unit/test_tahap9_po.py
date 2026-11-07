"""Tahap 9 (7 Nov 2026) — agen po: satu rincian PO di dua portal + sampel di dalam PO maklon.

  K8   Rincian PO membaca data PO UTAMA (`production_pos`): draf terlihat, angka kirim dari surat jalan
       buyer (bukan koleksi lama / cermin), QC dari penerimaan CMT. Endpoint lama `/360` ikut SSOT.
  K9   Sampel dibuat dari PO utama (id `production_pos`) dan lewat jalur lama `order_id` (cermin) → PO yang
       sama. Alur status: kirim ke klien, setujui, tolak, revisi HANYA dari "menunggu persetujuan",
       ubah diblokir setelah disetujui.
  K10  Satu helper tanda "Sampel belum disetujui" (`core.sample_status`) — peringatan saja.
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

from _fake_mongo import FakeDB  # noqa: E402
from core import po_detail  # noqa: E402
from core import sample_status as smp  # noqa: E402
import routes.dewi_maklon_po_360 as po360  # noqa: E402
import routes.dewi_maklon_samples as samples  # noqa: E402
import routes.dewi_maklon_pos as mkpos  # noqa: E402
import services.maklon_progress as mprog  # noqa: E402

USER = {"id": "u1", "name": "Admin Uji", "role": "admin", "_permissions": []}
FE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "erp"


def run(c):
    return asyncio.run(c)


async def _no_progress(*_a, **_k):
    return None


def _maklon_db(status="Draft"):
    """PO maklon UJI-T9-po yang HANYA ada di data utama (draf belum bercermin) + kiriman ke buyer 30 pcs."""
    db = FakeDB()
    db.production_pos.docs = [{"id": "po1", "po_number": "UJI-T9-po-001", "business_type": "maklon",
                               "status": status, "buyer_id": "cl1", "customer_name": "Klien Uji",
                               "created_at": "2026-11-01T01:00:00+00:00", "created_by": "Admin Uji"}]
    db.po_items.docs = [{"id": "pi1", "po_id": "po1", "qty": 100, "sku": "UJI-A-M", "product_name": "Artikel Uji",
                         "cmt_price_snapshot": 10000, "selling_price_snapshot": 15000,
                         "created_at": "2026-11-01T01:00:00+00:00"}]
    db.buyer_shipments.docs = [{"id": "bs1", "shipment_number": "SJ-UJI-1", "po_id": "po1",
                                "receiver_type": "buyer", "ship_status": "Shipped",
                                "created_at": "2026-11-03T01:00:00+00:00"}]
    db.buyer_shipment_items.docs = [{"id": "bsi1", "shipment_id": "bs1", "po_item_id": "pi1", "qty_shipped": 30}]
    db.vendor_shipments.docs = [{"id": "vs1", "shipment_number": "VS-UJI-1", "status": "Received",
                                 "shipment_type": "NORMAL", "vendor_name": "CMT Uji",
                                 "shipment_date": "2026-11-02"}]
    db.vendor_shipment_items.docs = [{"id": "vsi1", "shipment_id": "vs1", "po_item_id": "pi1", "qty_sent": 100}]
    db.cmt_receipts.docs = [{"id": "rc1", "receipt_code": "RCV-UJI-1", "po_id": "po1", "status": "completed_qc",
                             "cmt_name": "CMT Uji", "receipt_date": "2026-11-03"}]
    db.cmt_receipt_lines.docs = [{"id": "rl1", "receipt_id": "rc1", "po_item_id": "pi1", "qty_actual": 95,
                                  "reject_qty": 5, "qty_shipped_by_cmt": 100}]
    # salinan basi + koleksi lama: TIDAK boleh menjadi sumber angka
    db.dewi_maklon_dispatches.docs = [{"id": "old1", "po_id": "po1", "status": "confirmed",
                                       "items": [{"item_id": "pi1", "qty_dispatched": 99}]}]
    db.dewi_maklon_qc_checks.docs = [{"id": "qcold", "po_id": "po1", "result": "fail"}]
    return db


# ══════════════════════════════════════════════════════════════════════════════
# K8 · rincian PO dari data utama
# ══════════════════════════════════════════════════════════════════════════════
def test_rincian_po_draf_dibaca_dari_production_pos(monkeypatch):
    db = _maklon_db("Draft")
    monkeypatch.setattr(mprog, "compute_po_progress", _no_progress)
    out = run(po_detail.build_po_detail(db, "po1"))
    assert out["po_number"] == "UJI-T9-po-001" and out["status"] == "Draft"   # draf tanpa cermin terlihat
    assert out["business_type"] == "maklon"
    t = out["totals"]
    assert t["ordered"] == 100 and t["dispatched"] == 30 and t["remaining_to_ship"] == 70
    assert t["sent_to_cmt"] == 100 and t["accepted"] == 95 and t["reject"] == 5
    assert out["vendor_shipments"][0]["type_label"] == "Utama"
    assert out["receipts"][0]["qty_good"] == 95 and out["receipts"][0]["status_label"] == "Selesai QC"
    assert out["result_shipments"][0]["number"] == "SJ-UJI-1" and out["result_shipments"][0]["qty"] == 30
    assert out["sample_flag"]["warning"] is True and out["sample_flag"]["label"] == "Sampel belum disetujui"
    assert t["value_selling"] == 1_500_000 and t["value_cmt"] == 1_000_000


def test_rincian_po_tidak_ada_404():
    with pytest.raises(HTTPException) as e:
        run(po_detail.build_po_detail(FakeDB(), "tidak-ada"))
    assert e.value.status_code == 404


def test_endpoint_360_lama_membaca_production_pos_bukan_cermin(monkeypatch):
    db = _maklon_db("In Production")
    # cermin basi dengan angka lain — dulu dibaca duluan
    db.dewi_maklon_pos.docs = [{"id": "po1", "po_number": "UJI-T9-po-001", "status": "draft", "qty_dispatched": 0,
                                "items": [{"item_id": "pi1", "qty": 1}]}]
    monkeypatch.setattr(po360, "get_db", lambda: db)
    monkeypatch.setattr(po360, "compute_po_progress", _no_progress)
    out = run(po360.maklon_po_360("po1", user=dict(USER)))
    assert out["po"]["_source_collection"] == "production_pos"
    assert out["po"]["items"][0]["qty"] == 100 and out["po"]["items"][0]["qty_dispatched"] == 30
    assert out["kpis"]["total_dispatched"] == 30 and out["kpis"]["dispatch_pct"] == 30.0
    assert all(d.get("source") == "buyer_shipment" for d in out["dispatches"])   # koleksi kiriman lama diabaikan
    assert out["material_receives"] == []
    assert out["kpis"]["qc_pass"] == 0 and out["kpis"]["qc_fail"] == 1          # dari penerimaan CMT (5 tolak)
    assert out["qc_checks"][0]["number"] == "RCV-UJI-1"


def test_riwayat_po_dari_data_utama(monkeypatch):
    db = _maklon_db("Confirmed")
    db.production_pos.docs[0]["confirmed_at"] = "2026-11-01T02:00:00+00:00"
    tl = run(po_detail.build_timeline(db, "po1"))
    labels = [e["label"] for e in tl["events"]]
    assert any("dikonfirmasi" in x for x in labels)
    assert any("VS-UJI-1" in x for x in labels) and any("RCV-UJI-1" in x for x in labels)
    assert any("SJ-UJI-1" in x for x in labels)
    assert all("dispatch" not in x.lower() for x in labels)                    # tidak ada istilah program
    # tautan lama /timeline meneruskan ke riwayat yang sama
    monkeypatch.setattr(po360, "get_db", lambda: db)
    old = run(po360.maklon_po_timeline("po1", user=dict(USER)))
    assert old["total_events"] == tl["total_events"]


def test_riwayat_catatan_aktivitas_diterjemahkan():
    assert po_detail.humanize_log("Created PO: UJI-1 with 1 items") is None          # sudah ada "PO dibuat"
    assert po_detail.humanize_log("PO UJI-1: Draft → Confirmed") == "Status PO diubah: Draf → Dikonfirmasi"
    assert po_detail.humanize_log("Updated PO: UJI-1") == "PO UJI-1 diubah"
    assert po_detail.humanize_log("Added 2 accessories to PO") == "2 aksesoris ditambahkan ke PO"
    assert "Ditutup kurang" in po_detail.humanize_log("PO UJI-1 → Closed Short (deadline_expired). x")


def test_daftar_cermin_tidak_menimpa_angka_kirim_ssot(monkeypatch):
    db = FakeDB()
    db.dewi_maklon_pos.docs = [{"id": "po1", "po_number": "UJI-T9-po-001", "mirror_of": "production_pos",
                                "total_qty": 100, "qty_dispatched": 30, "created_at": "2026-11-01"}]
    db.dewi_maklon_dispatches.docs = []
    monkeypatch.setattr(mkpos, "get_db", lambda: db)
    rows = run(mkpos.list_maklon_pos(status=None, client_id=None, search=None, limit=100, user=dict(USER)))
    assert rows[0]["qty_dispatched"] == 30 and rows[0]["qty_remaining"] == 70


def test_rencana_aksesoris_satuan_serah_dan_cadangan():
    lama = po_detail.accessory_plan_row({"accessory_name": "Kancing", "qty_needed": 500, "unit": "pcs",
                                         "source": "bom_auto"})
    assert lama["has_handover"] is False and lama["bom_qty_base"] == 500 and lama["source_label"] == "BOM"
    baru = po_detail.accessory_plan_row({"accessory_name": "Renda", "usage_unit": "cm", "bom_qty_base": 31500,
                                         "handover_uom": "roll", "handover_factor": 2240, "bom_qty_handover": 14.06,
                                         "plan_qty_handover": 15, "source": "tambahan"})
    assert baru["has_handover"] and baru["plan_qty_handover"] == 15 and baru["handover_factor"] == 2240
    assert baru["source"] == "tambahan" and baru["usage_unit"] == "cm"


# ══════════════════════════════════════════════════════════════════════════════
# K9 · sampel di dalam PO maklon
# ══════════════════════════════════════════════════════════════════════════════
def _samples_db(monkeypatch):
    db = _maklon_db("Confirmed")
    db.dewi_maklon_buyer_catalog.docs = [
        {"id": "cat1", "client_id": "cl1", "product_name": "Artikel Uji", "artikel_code": "UJI-ART"},
        {"id": "cat2", "client_id": "klien-lain", "product_name": "Artikel Lain", "artikel_code": "UJI-LAIN"}]
    seq = {"n": 0}

    async def code(_db, order_code, requested=""):
        seq["n"] += 1
        return requested or f"SMP-{order_code}-{seq['n']:02d}"

    monkeypatch.setattr(samples, "get_db", lambda: db)
    monkeypatch.setattr(samples, "_generate_sample_code", code)
    return db


def test_sampel_dibuat_dengan_id_production_pos(monkeypatch):
    db = _samples_db(monkeypatch)
    res = run(samples.create_sample(samples.SampleIn(po_id="po1", buyer_catalog_id="cat1"), user=dict(USER)))
    doc = db.dewi_maklon_samples.docs[0]
    assert res["po_id"] == "po1" and doc["po_id"] == "po1" and doc["order_id"] == "po1"
    assert doc["client_id"] == "cl1" and doc["product_name"] == "Artikel Uji"       # isi dari katalog
    assert doc["sample_code"] == "SMP-UJI-T9-po-001-01" and doc["status"] == "draft"
    # artikel klien lain ditolak
    with pytest.raises(HTTPException) as e:
        run(samples.create_sample(samples.SampleIn(po_id="po1", buyer_catalog_id="cat2", product_name="X"),
                                  user=dict(USER)))
    assert e.value.status_code == 400
    # PO internal ditolak
    db.production_pos.docs.append({"id": "poi", "po_number": "UJI-T9-po-INT", "business_type": "internal"})
    with pytest.raises(HTTPException):
        run(samples.create_sample(samples.SampleIn(po_id="poi", product_name="X"), user=dict(USER)))


def test_sampel_jalur_lama_order_id_cermin_ke_po_utama(monkeypatch):
    db = _samples_db(monkeypatch)
    db.dewi_maklon_pos.docs = [{"id": "mir-lama", "po_number": "UJI-LAMA", "production_po_id": "po1",
                                "client_id": "cl1"}]
    run(samples.create_sample(samples.SampleIn(order_id="mir-lama", product_name="Sampel lama"), user=dict(USER)))
    run(samples.create_sample(samples.SampleIn(order_id="UJI-T9-po-001", product_name="Per nomor"), user=dict(USER)))
    assert [d["po_id"] for d in db.dewi_maklon_samples.docs] == ["po1", "po1"]
    with pytest.raises(HTTPException):
        run(samples.create_sample(samples.SampleIn(order_id="tidak-ada", product_name="X"), user=dict(USER)))
    # daftar per PO membaca po_id maupun order_id
    db.dewi_maklon_samples.docs.append({"id": "s-old", "order_id": "po1", "status": "approved",
                                        "created_at": "2026-10-01"})
    rows = run(samples.list_samples(po_id="po1", order_id=None, status=None, buyer_catalog_id=None, user=dict(USER)))
    assert len(rows) == 3 and rows[0]["status_label"]


def test_alur_status_sampel(monkeypatch):
    db = _samples_db(monkeypatch)
    sid = run(samples.create_sample(samples.SampleIn(po_id="po1", product_name="Sampel A"), user=dict(USER)))["id"]
    st = lambda: next(d for d in db.dewi_maklon_samples.docs if d["id"] == sid)["status"]  # noqa: E731

    # revisi dari draf ditolak (dulu tanpa pemeriksaan)
    with pytest.raises(HTTPException) as e:
        run(samples.request_revision(sid, samples.RevisionIn(reason="ganti kancing"), user=dict(USER)))
    assert e.value.status_code == 400 and "menunggu persetujuan" in e.value.detail
    run(samples.submit_sample(sid, user=dict(USER)))
    assert st() == "submitted"
    run(samples.request_revision(sid, samples.RevisionIn(reason="ganti kancing"), user=dict(USER)))
    assert st() == "revision_requested" and len(db.dewi_maklon_sample_revisions.docs) == 1
    with pytest.raises(HTTPException):   # revisi dari "perlu revisi" ditolak
        run(samples.request_revision(sid, samples.RevisionIn(reason="lagi"), user=dict(USER)))
    run(samples.update_sample(sid, samples.SampleIn(product_name="Sampel A v2"), user=dict(USER)))
    run(samples.submit_sample(sid, user=dict(USER)))
    run(samples.approve_sample(sid, samples.ApprovalIn(feedback="ok"), user=dict(USER)))
    assert st() == "approved"
    with pytest.raises(HTTPException):   # ubah setelah disetujui diblokir
        run(samples.update_sample(sid, samples.SampleIn(product_name="X"), user=dict(USER)))
    with pytest.raises(HTTPException):   # kirim ulang yang sudah disetujui ditolak
        run(samples.submit_sample(sid, user=dict(USER)))

    sid2 = run(samples.create_sample(samples.SampleIn(po_id="po1", product_name="Sampel B"), user=dict(USER)))["id"]
    with pytest.raises(HTTPException):   # tolak draf ditolak
        run(samples.reject_sample(sid2, samples.RejectionIn(reason="jahitan miring"), user=dict(USER)))
    run(samples.submit_sample(sid2, user=dict(USER)))
    run(samples.reject_sample(sid2, samples.RejectionIn(reason="jahitan miring"), user=dict(USER)))
    assert next(d for d in db.dewi_maklon_samples.docs if d["id"] == sid2)["status"] == "rejected"


def test_aturan_transisi_satu_tabel():
    assert smp.can("revision", "submitted") and not smp.can("revision", "draft")
    assert not smp.can("revision", "revision_requested")
    assert smp.can("submit", "revision_requested") and not smp.can("submit", "approved")
    assert not smp.can("edit", "approved") and smp.can("edit", "rejected")
    with pytest.raises(HTTPException):
        smp.assert_transition("approve", "draft")


# ══════════════════════════════════════════════════════════════════════════════
# K10 · tanda "Sampel belum disetujui"
# ══════════════════════════════════════════════════════════════════════════════
def test_helper_tanda_sampel():
    db = FakeDB()
    db.production_pos.docs = [
        {"id": "a", "business_type": "maklon", "status": "Confirmed"},      # tanpa sampel → peringatan
        {"id": "b", "business_type": "maklon", "status": "In Production"},  # sampel disetujui
        {"id": "c", "business_type": "maklon", "status": "Closed"},         # PO ditutup → tidak diingatkan
        {"id": "d", "business_type": "internal", "status": "Confirmed"},    # internal → tanpa tanda
        {"id": "e", "business_type": "maklon", "status": "Confirmed"},      # sampel lama via order_id
    ]
    db.dewi_maklon_samples.docs = [
        {"id": "s1", "po_id": "b", "status": "rejected", "created_at": "2026-11-01"},
        {"id": "s2", "po_id": "b", "status": "approved", "created_at": "2026-11-02"},
        {"id": "s3", "order_id": "e", "status": "submitted", "created_at": "2026-11-02"},
    ]
    f = run(smp.sample_flags(db, db.production_pos.docs))
    assert f["a"]["warning"] and f["a"]["count"] == 0 and f["a"]["label"] == smp.WARNING_LABEL
    assert not f["b"]["warning"] and f["b"]["has_approved"] and f["b"]["latest_status"] == "approved"
    assert not f["c"]["warning"]
    assert "d" not in f
    assert f["e"]["warning"] and f["e"]["pending"] == 1
    assert run(smp.po_sample_flag(db, "d")) is None
    assert run(smp.po_sample_flag(db, "a"))["warning"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Layar: menu lama diteruskan, tidak ada popup detail, satu rincian di kedua portal
# ══════════════════════════════════════════════════════════════════════════════
def _fe(name):
    p = FE / name
    if not p.exists():
        pytest.skip("frontend tidak tersedia")
    return p.read_text(encoding="utf-8")


def test_layar_po_memakai_rincian_di_halaman():
    po = _fe("engine/ProductionPOModule.jsx")
    assert "PODetailPanel" in po and "detail={" in po
    assert "Detail Modal" not in po and "maklon-po-360" not in po
    panel = _fe("engine/PODetailPanel.jsx")
    for label in ("Ringkasan", "Barang", "Bahan & aksesoris", "Kirim & terima", "Tagihan & HPP", "Sampel", "Riwayat"):
        assert label in panel
    assert "/production-pos/${poId}/detail" in panel


def test_menu_lama_diteruskan_ke_po_maklon():
    for name in ("MaklonPO360Module.jsx", "MaklonSampleManagement.jsx"):
        src = _fe(name)
        assert "maklon-pos-engine" in src and "open_po_id" in src
