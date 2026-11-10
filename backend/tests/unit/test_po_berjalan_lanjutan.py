"""PO berjalan lanjutan (11 Nov 2026, keputusan owner) — empat temuan owner setelah impor PO berjalan cutoff.

1 · Tutup PO: kekurangan DIJUMLAH per ukuran (dulu satu entri per baris PO: "M kurang 2, M kurang 12, …").
3 · Keuangan › Hutang Pemasok & CMT: tagihan CMT membawa CV dari server (PO maklon = CV Sukma) dan disaring pilihan
    CV; tab "Hutang CMT terjadwal" = jadwal PO maklon (CV Sukma) + PERKIRAAN PO DA (CV Dewi Aditya, tidak disimpan).
4 · Barang jadi PO internal yang dijahit CMT masuk stok & jurnal HANYA lewat Terima FG dari CMT → QC: progres job CMT
    tidak membuat penerimaan gudang, job selesai tidak membukukan WIP→Persediaan (uji ujung-ke-ujung lokal sebelumnya:
    stok 78 untuk 38 pcs lolos, persediaan dua kali, WIP minus). Bahan PO saldo awal cutoff dianggap 0.
(Butir 2 — impor membuat job, Tujuan, tenggat — ada di test_tahap4_cutoff.py.)
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

from _fake_mongo import FakeDB  # noqa: E402

ADMIN = {"id": "u1", "name": "Admin Uji", "role": "admin"}


def run(c):
    return asyncio.run(c)


class Req:
    """Request tiruan dengan header (X-CV) dan query string."""

    def __init__(self, body=None, headers=None, query=None):
        self._body = body or {}
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.query_params = dict(query or {})

        class _S:
            pass
        self.state = _S()
        self.cookies = {}

    async def json(self):
        return dict(self._body)


class _Headers(dict):
    def get(self, k, d=None):
        return super().get(str(k).lower(), d)


def req(body=None, headers=None, query=None):
    r = Req(body, headers, query)
    r.headers = _Headers(r.headers)
    return r


# ══════════════════════════════════════════════════════════════════════════════
# 1 · Tutup PO
# ══════════════════════════════════════════════════════════════════════════════
def test_kekurangan_dijumlah_per_ukuran():
    from routes.production_pos import short_by_size, short_lines_text
    lines = [{"size": "M", "short": 2}, {"size": "M", "short": 12}, {"size": "XL", "short": 30},
             {"size": "M", "short": 19}, {"size": "L", "short": 0}, {"size": "", "sku": "SKU-X", "short": 1}]
    assert short_by_size(lines) == [("M", 33), ("XL", 30), ("SKU-X", 1)]
    assert short_lines_text(lines) == "M kurang 33, XL kurang 30, SKU-X kurang 1"
    assert short_lines_text([]) == ""


# ══════════════════════════════════════════════════════════════════════════════
# 4 · Barang jadi PO internal yang dijahit CMT
# ══════════════════════════════════════════════════════════════════════════════
def test_job_cmt_dikenali():
    from core.production_job_lifecycle import sewn_by_cmt
    assert sewn_by_cmt({"vendor_shipment_id": "s1"}) and sewn_by_cmt({"vendor_id": "vp1"})
    assert not sewn_by_cmt({"vendor_id": None, "vendor_shipment_id": None}) and not sewn_by_cmt(None)


def _progress_env(monkeypatch, job: dict):
    import routes.production_execution as pe
    import routes.production_internal_adapter as pia
    db = FakeDB()
    db.production_jobs.docs = [dict(job)]
    db.production_job_items.docs = [{"id": "ji1", "job_id": job["id"], "job_number": job["job_number"], "sku": "DA-1-HTM-M",
                                     "rahaza_variant_id": "v1", "shipment_qty": 40, "available_qty": 40, "produced_qty": 0}]
    calls = {"pending": 0, "hook": 0}

    async def auth(_r):
        return dict(ADMIN)

    async def none(*_a, **_k):
        return None

    async def variant(*_a, **_k):
        return {"id": "v1", "sku": "DA-1-HTM-M"}

    async def pending(*_a, **_k):
        calls["pending"] += 1
        return {}

    async def hook(_db, j, _u):
        calls["hook"] += 1
        return {"wip_to_fg": {"ok": True}}
    monkeypatch.setattr(pe, "get_db", lambda: db)
    monkeypatch.setattr(pe, "require_auth", auth)
    monkeypatch.setattr(pe, "require_write_actor", lambda *_a, **_k: None)
    monkeypatch.setattr(pe, "log_activity", none)
    monkeypatch.setattr(pe, "resolve_variant", variant)
    monkeypatch.setattr(pe, "create_fg_pending_inbound_for_variant", pending)
    monkeypatch.setattr(pia, "on_job_completed_internal", hook)
    import core.cmt_override as ov
    monkeypatch.setattr(ov, "resolve_override", none)
    return pe, db, calls


def test_progres_job_cmt_tidak_membuat_penerimaan_barang_jadi(monkeypatch):
    pe, db, calls = _progress_env(monkeypatch, {"id": "j1", "job_number": "JOB-1", "business_type": "internal",
                                                "vendor_id": "vp1", "vendor_shipment_id": "s1", "status": "In Progress"})
    res = run(pe.create_progress(req({"job_item_id": "ji1", "completed_quantity": 40})))
    assert res.status_code == 201
    assert calls["pending"] == 0                       # barang jadi masuk lewat Terima FG dari CMT → QC
    assert calls["hook"] == 1                          # job tetap ditutup (snapshot HPP; jurnalnya dilewati — uji di bawah)
    assert db.production_jobs.docs[0]["status"] == "Completed"
    assert db.production_job_items.docs[0]["produced_qty"] == 40   # progres tetap dasar tagihan CMT


def test_progres_job_jahit_sendiri_tetap_membuat_penerimaan_barang_jadi(monkeypatch):
    pe, _db, calls = _progress_env(monkeypatch, {"id": "j2", "job_number": "JOB-2", "business_type": "internal",
                                                 "vendor_id": None, "vendor_shipment_id": None, "status": "In Progress"})
    run(pe.create_progress(req({"job_item_id": "ji1", "completed_quantity": 10})))
    assert calls["pending"] == 1 and calls["hook"] == 0


def test_jurnal_wip_ke_persediaan_saat_job_cmt_selesai_dilewati(monkeypatch):
    import routes.rahaza_posting as rp
    db = FakeDB()
    db.production_jobs.docs = [{"id": "j1", "job_number": "JOB-1", "vendor_shipment_id": "s1", "vendor_id": "vp1"},
                               {"id": "j2", "job_number": "JOB-2", "vendor_id": None}]
    db.rahaza_hpp_snapshots.docs = [{"job_id": "j1", "total_cost": 480000}, {"job_id": "j2", "total_cost": 100000}]
    jes = []

    async def mapping(_db, _et):
        return {"debit_fg_inventory": "1-1404", "credit_wip": "1-1403"}

    async def create_je(_db, _d, memo, _st, ref, lines, _u, *a, **k):
        jes.append((ref, lines))
        return {"ok": True, "je_id": f"je{len(jes)}", "je_number": f"JE-{len(jes)}"}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_create_posted_je", create_je)
    out = run(rp.post_wip_to_fg_on_job_complete(db, db.production_jobs.docs[0], ADMIN))
    assert out["ok"] and out["skipped"] == "job_cmt" and jes == []
    assert db.production_jobs.docs[0]["wip_skipped"] == "job_cmt" and db.production_jobs.docs[0]["wip_posted"] is False
    # job jahit sendiri tidak berubah: cadangan HPP snapshot tetap dibukukan
    out2 = run(rp.post_wip_to_fg_on_job_complete(db, db.production_jobs.docs[1], ADMIN))
    assert out2["ok"] and out2["basis"] == "hpp_snapshot" and len(jes) == 1 and jes[0][0] == "wip_fg_job:j2"


@pytest.fixture
def biaya_env(monkeypatch):
    from core import hpp_aktual
    from core import product_costing as pc
    state = {"actual": None}

    async def actual(_db, *, po_item, qty):
        return state["actual"]

    async def bom(_db, model_id, size_id, **_k):
        return {"bom_id": "b1", "material_cost": 5000.0}
    monkeypatch.setattr(hpp_aktual, "layer_material_for", actual)
    monkeypatch.setattr(pc, "compute_material_cost", bom)
    return state


def test_lapisan_po_saldo_awal_bahan_dianggap_nol(biaya_env):
    from core.fg_cost_layers import compute_batch_unit_cost
    item = {"id": "pi1", "po_id": "po1", "model_id": "m1", "size_id": "s1", "cmt_price_snapshot": 12000,
            "opening_import": True}
    out = run(compute_batch_unit_cost(FakeDB(), po_item=item, qty=38))
    assert out["material_cost"] == 0 and out["material_source"] == "saldo_awal_nol"
    assert out["sewing_cost"] == 12000 and not any("BOM standar" in g for g in out["gaps"])
    # PO biasa tanpa penyerahan bahan: tetap BOM standar (tidak berubah)
    biasa = run(compute_batch_unit_cost(FakeDB(), po_item={**item, "opening_import": False}, qty=38))
    assert biasa["material_cost"] == 5000 and biasa["material_source"] == "bom"
    # bahan yang dikirim SESUDAH cutoff tetap dihitung sebagai bahan aktual
    biaya_env["actual"] = {"material_value": 38 * 700.0, "cut_value": 0.0, "accessory_value": 38 * 700.0,
                           "cut_per_pcs": 0, "accessory_per_pcs": 700, "sent_item": 40, "sent_total": 40,
                           "sent_basis": "x", "capped": False, "gaps": []}
    akt = run(compute_batch_unit_cost(FakeDB(), po_item=item, qty=38))
    assert akt["material_cost"] == 700 and akt["material_source"] == "aktual"
    # pembanding "HPP standar" tetap BOM
    std = run(compute_batch_unit_cost(FakeDB(), po_item=item, qty=38, basis="standard"))
    assert std["material_cost"] == 5000


# ══════════════════════════════════════════════════════════════════════════════
# 3 · Keuangan: CV tagihan CMT + hutang CMT terjadwal
# ══════════════════════════════════════════════════════════════════════════════
def _billing_db():
    db = FakeDB()
    db.vendor_partners.docs = [{"id": "vp1", "code": "CMT-A", "name": "Penjahit Satu"},
                               {"id": "vp2", "code": "CMT-B", "name": "Penjahit Dua"}]
    db.production_pos.docs = [
        {"id": "po-da", "po_number": "PO-INT-1", "business_type": "internal", "status": "In Production", "vendor_id": "vp1"},
        {"id": "po-mk", "po_number": "PO-MKL-1", "business_type": "maklon", "status": "In Production", "vendor_id": "vp2"},
        {"id": "po-tutup", "po_number": "PO-INT-2", "business_type": "internal", "status": "Closed", "vendor_id": "vp1"},
    ]
    db.po_items.docs = [
        {"id": "pi1", "po_id": "po-da", "sku": "DA-1-HTM-M", "product_name": "Kemeja", "size": "M", "color": "Hitam",
         "qty": 40, "cmt_price_snapshot": 12000},
        {"id": "pi2", "po_id": "po-tutup", "sku": "DA-1-HTM-L", "qty": 10, "cmt_price_snapshot": 12000},
    ]
    db.vendor_shipments.docs = [{"id": "s1", "vendor_id": "vp1", "shipment_type": "NORMAL", "po_id": "po-da"}]
    db.vendor_shipment_items.docs = [{"id": "si1", "shipment_id": "s1", "po_item_id": "pi1", "qty_sent": 40}]
    db.dewi_cmt_payments.docs = [
        {"id": "b-da", "payment_code": "PAY-CMT-1", "po_id": "po-da", "vendor_id": "vp1", "cmt_name": "Penjahit Satu",
         "net_amount": 120000, "total_pcs": 10, "status": "posted", "created_at": "2026-11-10"},
        {"id": "b-mk", "payment_code": "PAY-CMT-2", "po_id": "po-mk", "vendor_id": "vp2", "cmt_name": "Penjahit Dua",
         "net_amount": 85000, "total_pcs": 10, "status": "posted", "created_at": "2026-11-09"},
    ]
    db.dewi_cmt_ap_schedules.docs = [
        {"id": "sch-mk", "po_id": "po-mk", "po_number": "PO-MKL-1", "business_type": "maklon", "vendor_id": "vp2",
         "vendor_name": "Penjahit Dua", "scheduled_qty": 40, "scheduled_amount": 340000, "matured_amount": 85000,
         "matured_pcs": 10, "paid_amount": 0, "blocked_amount": 0, "payable_amount": 85000, "status": "berjalan",
         "updated_at": "2026-11-10"}]
    return db


@pytest.fixture
def billing(monkeypatch):
    import routes.production_cmt_billing as cb
    db = _billing_db()

    async def auth(_r):
        return dict(ADMIN)
    monkeypatch.setattr(cb, "get_db", lambda: db)
    monkeypatch.setattr(cb, "require_auth", auth)
    return cb, db


def test_tagihan_cmt_membawa_cv_dan_disaring_pilihan_cv(billing):
    cb, _db = billing
    semua = run(cb.list_cmt_billing(req(query={"business_type": "all"})))["items"]
    assert {r["payment_code"]: r["entity"] for r in semua} == {"PAY-CMT-1": "DA", "PAY-CMT-2": "SMU"}
    smu = run(cb.list_cmt_billing(req(headers={"X-CV": "SMU"}, query={"business_type": "all"})))["items"]
    assert [r["payment_code"] for r in smu] == ["PAY-CMT-2"]
    da = run(cb.list_cmt_billing(req(headers={"X-CV": "DA"}, query={"business_type": "all"})))["items"]
    assert [r["payment_code"] for r in da] == ["PAY-CMT-1"]
    gab = run(cb.list_cmt_billing(req(headers={"X-CV": "ALL"}, query={"business_type": "all"})))["items"]
    assert len(gab) == 2


def test_hutang_cmt_terjadwal_keuangan_per_cv(billing):
    cb, db = billing
    q = {"perkiraan_internal": "1"}
    # CV Dewi Aditya → PERKIRAAN PO DA: 40 pcs terkirim × 12.000, sudah lolos QC 10 pcs (tagihan 120.000)
    da = run(cb.list_cmt_ap_schedules(req(headers={"X-CV": "DA"}, query=q)))
    assert [(r["po_number"], r["jenis"], r["entity"]) for r in da["items"]] == [("PO-INT-1", "perkiraan", "DA")]
    r = da["items"][0]
    assert r["vendor_id"] == "vp1" and r["scheduled_amount"] == 480000 and r["matured_amount"] == 120000
    assert r["remaining_amount"] == 360000 and r["remaining_qty"] == 30 and r["lines"][0]["cmt_rate"] == 12000
    assert da["own_team_pos"] == []                                    # PO tertutup & PO maklon tidak ikut
    # CV Sukma → jadwal PO maklon (tersimpan)
    smu = run(cb.list_cmt_ap_schedules(req(headers={"X-CV": "SMU"}, query=q)))
    assert [(r["po_number"], r["jenis"], r["entity"], r["remaining_amount"]) for r in smu["items"]] == [
        ("PO-MKL-1", "jadwal", "SMU", 255000)]
    # Gabungan → keduanya
    gab = run(cb.list_cmt_ap_schedules(req(headers={"X-CV": "ALL"}, query=q)))
    assert len(gab["items"]) == 2 and gab["totals"]["remaining_by_entity"] == {"DA": 360000, "SMU": 255000}
    # Portal Maklon (tanpa CV, tanpa perkiraan) → perilaku lama: jadwal PO maklon saja
    mk = run(cb.list_cmt_ap_schedules(req()))
    assert [r["po_number"] for r in mk["items"]] == ["PO-MKL-1"]
    # perkiraan TIDAK disimpan
    assert [s["id"] for s in db.dewi_cmt_ap_schedules.docs] == ["sch-mk"]


def test_jadwal_maklon_tetap_disimpan_dengan_rumus_yang_sama():
    from core import maklon_ledger
    db = _billing_db()
    db.po_items.docs.append({"id": "pi3", "po_id": "po-mk", "sku": "BJ-1", "qty": 40, "cmt_price_snapshot": 8500})
    out = run(maklon_ledger.refresh_ap_schedules(db, "po-mk", ADMIN))
    assert len(out) == 1 and out[0]["scheduled_amount"] == 340000 and out[0]["business_type"] == "maklon"
    assert out[0]["matured_amount"] == 85000 and out[0]["bill_ids"] == ["b-mk"]
    saved = next(s for s in db.dewi_cmt_ap_schedules.docs if s["po_id"] == "po-mk" and s.get("vendor_id") == "vp2")
    assert saved["scheduled_amount"] == 340000
    assert db.dewi_cmt_payments.docs[1]["ap_schedule_id"] == saved["id"]
    assert run(maklon_ledger.refresh_ap_schedules(db, "po-da", ADMIN)) == []   # PO internal tidak pernah disimpan
