"""Tahap 1 (6 Nov 2026) — perbaikan cacat jelas PRODUKSI / MAKLON / HPP / CUTTING.

Satu uji (atau lebih) per butir:
  1. Selesai QC Terima FG atomik/idempoten per baris (stok, lapisan HPP, AP sekali).
  2. Angka "HPP aktual" karangan dihapus (estimasi ×0,95 / = pendapatan / bahan +30% +15%).
  3. Detail PO maklon 360°: qty terkirim dari SSOT, biaya BOM dari `materials`.
  4. Dashboard Cutting & Produksi: kain per satuan, order batal tidak dihitung.
  5. Ongkos permak dibebankan SEKALI.
  6. Qty aksesoris PO desimal.
  7. Hapus baris penerimaan dijaga status.
  8. Kiriman vendor tidak bisa diterima selama PO masih Draf.
  9. Label formulir PO berbahasa Indonesia.
 10. HPP WO memakai biaya saat bahan keluar.
"""
import asyncio
import copy
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

from _fake_mongo import FakeDB, FakeRequest, match  # noqa: E402
import routes.dewi_cmt_packing as dcp  # noqa: E402
import routes.shared as shared  # noqa: E402
import routes.production_maklon_bridge as bridge  # noqa: E402
import routes.rahaza_posting as rposting  # noqa: E402
import routes.rahaza_hpp as rhpp  # noqa: E402
import routes.dewi_production_reports as reports  # noqa: E402
import routes.dewi_maklon_po_360 as po360  # noqa: E402
import routes.cutting as cutting  # noqa: E402
import routes.production_pos as ppos  # noqa: E402
import routes.vendor_shipment as vs  # noqa: E402
import routes.production_internal_adapter as pia  # noqa: E402
from core import production_qty_ledger as qled  # noqa: E402
from core import fg_cost_layers as fcl  # noqa: E402
from core import wo_reader  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
USER = {"id": "u1", "name": "Admin Uji", "role": "admin"}


def run(c):
    return asyncio.run(c)


async def _user(*_a, **_k):
    return dict(USER)


# ══════════════════════════════════════════════════════════════════════════════
# 1 · Selesai QC Terima FG — tidak mencatat stok dua kali saat diulang
# ══════════════════════════════════════════════════════════════════════════════
def _receipt_db(status="on_qc", posted_line=False):
    db = FakeDB()
    db.cmt_receipts.docs = [{"id": "r1", "receipt_code": "RCV-1", "status": status, "po_id": "po1",
                             "po_number": "PO-1", "cmt_name": "CMT A", "cmt_vendor_id": "v1"}]
    db.production_pos.docs = [{"id": "po1", "business_type": "internal"}]
    l1 = {"id": "l1", "receipt_id": "r1", "sku_code": "SKU-A", "qty_actual": 45, "reject_qty": 0,
          "qty_shipped_by_cmt": 45, "po_item_id": "pi1"}
    if posted_line:
        l1.update({"fg_stock_posted_at": "2026-11-06T00:00:00", "fg_stock_posted_qty": 45,
                   "fg_material_id": "fg-a", "fg_movement_id": "mv0"})
    db.cmt_receipt_lines.docs = [
        l1,
        {"id": "l2", "receipt_id": "r1", "sku_code": "SKU-B", "qty_actual": 5, "reject_qty": 0,
         "qty_shipped_by_cmt": 5, "po_item_id": "pi2"},
    ]
    return db


def _patch_finish(monkeypatch, db, *, fg_for=None, fail_once_on=None):
    calls = {"post": [], "ap": 0}
    fg_for = fg_for if fg_for is not None else {"SKU-A": "fg-a", "SKU-B": "fg-b"}
    failed = set()

    async def ensure_fg(_db, ln, *_a, **_k):
        mid = fg_for.get(ln.get("sku_code"))
        return {"id": mid, "code": ln.get("sku_code")} if mid else None

    async def post(_db, *, material_id, qty, ref, **_k):
        if fail_once_on and ref["receipt_line_id"] == fail_once_on and fail_once_on not in failed:
            failed.add(fail_once_on)
            raise RuntimeError("koneksi stok putus")
        calls["post"].append((ref["receipt_line_id"], material_id, qty))
        return {"location_id": "loc-fg", "cost_layer": {"id": f"ly-{ref['receipt_line_id']}"}}

    async def loc(_db):
        return "loc-fg"

    async def ledger(*_a, **_k):
        return {"applied": True}

    async def ap(*_a, **_k):
        calls["ap"] += 1
        return {"ok": True}

    async def wip(*_a, **_k):
        return {"ok": True}

    monkeypatch.setattr(shared, "require_perm", _user)
    monkeypatch.setattr(dcp, "require_auth", _user)
    monkeypatch.setattr(dcp, "get_db", lambda: db)
    monkeypatch.setattr(dcp, "_ensure_fg_for_cmt_line", ensure_fg)
    monkeypatch.setattr(qled, "post_fg_accepted", post)
    monkeypatch.setattr(qled, "resolve_fg_location_id", loc)
    monkeypatch.setattr(qled, "apply_receipt_result", ledger)
    monkeypatch.setattr(bridge, "mature_ap_from_cmt_receipt", ap)
    monkeypatch.setattr(rposting, "post_wip_to_fg_on_cmt_receipt", wip)
    return calls


def test_selesai_qc_memeriksa_semua_baris_sebelum_menulis_stok(monkeypatch):
    db = _receipt_db()
    calls = _patch_finish(monkeypatch, db, fg_for={"SKU-A": "fg-a"})  # SKU-B tanpa master
    with pytest.raises(HTTPException) as e:
        run(dcp._finish_receipt("r1", FakeRequest()))
    assert e.value.status_code == 400 and "SKU-B" in e.value.detail
    assert calls["post"] == [] and db.rahaza_fg_movements.docs == []
    assert not any(ln.get("fg_stock_posted_at") for ln in db.cmt_receipt_lines.docs)


def test_selesai_qc_diulang_tidak_mencatat_stok_baris_lama_dua_kali(monkeypatch):
    db = _receipt_db()
    calls = _patch_finish(monkeypatch, db, fail_once_on="l2")
    with pytest.raises(HTTPException) as e:
        run(dcp._finish_receipt("r1", FakeRequest()))
    assert e.value.status_code == 500
    assert db.cmt_receipts.docs[0]["status"] == "on_qc"          # belum selesai
    assert calls["ap"] == 0
    out = run(dcp._finish_receipt("r1", FakeRequest()))       # diulang
    posted_lines = [c[0] for c in calls["post"]]
    assert posted_lines.count("l1") == 1 and posted_lines.count("l2") == 1
    assert calls["ap"] == 1
    assert len(db.rahaza_fg_movements.docs) == 2
    assert db.cmt_receipts.docs[0]["status"] == "completed_qc"
    assert {s["cost_layer_id"] for s in out["stock_posted"]} == {"ly-l1", "ly-l2"}


def test_baris_yang_stoknya_sudah_tercatat_tidak_bisa_diubah_qty(monkeypatch):
    db = _receipt_db(posted_line=True)
    _patch_finish(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(dcp.update_line("r1", "l1", FakeRequest({"qty_actual": 50})))
    assert e.value.status_code == 409
    # catatan (bukan qty) tetap boleh diubah
    run(dcp.update_line("r1", "l1", FakeRequest({"notes": "dus penyok"})))


# ══════════════════════════════════════════════════════════════════════════════
# 7 · Hapus baris penerimaan dijaga status
# ══════════════════════════════════════════════════════════════════════════════
def test_hapus_baris_ditolak_setelah_qc_selesai(monkeypatch):
    db = _receipt_db(status="completed_qc")
    _patch_finish(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(dcp.delete_line("r1", "l2", FakeRequest()))
    assert e.value.status_code == 409 and "sudah selesai" in e.value.detail
    assert len(db.cmt_receipt_lines.docs) == 2


def test_hapus_baris_ditolak_bila_stoknya_sudah_tercatat(monkeypatch):
    db = _receipt_db(posted_line=True)
    _patch_finish(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(dcp.delete_line("r1", "l1", FakeRequest()))
    assert e.value.status_code == 409
    run(dcp.delete_line("r1", "l2", FakeRequest()))           # baris lain masih boleh
    assert [ln["id"] for ln in db.cmt_receipt_lines.docs] == ["l1"]
    assert db.cmt_receipts.docs[0]["total_actual"] == 45      # total header ikut dihitung ulang


# ══════════════════════════════════════════════════════════════════════════════
# 5 · Ongkos permak dibebankan sekali
# ══════════════════════════════════════════════════════════════════════════════
def test_permak_to_absorb_hanya_sisa_yang_belum_diserap():
    rows = [{"id": "a", "total_cost": 20000, "permak_absorbed_cost": 20000},
            {"id": "b", "total_cost": 0, "cost_per_pcs": 1000, "qty": 3},
            {"id": "c", "total_cost": 15000, "permak_absorbed_cost": 10000}]
    assert fcl.permak_to_absorb(rows) == [{"id": "b", "amount": 3000.0}, {"id": "c", "amount": 5000.0}]


def _patch_wac(monkeypatch):
    async def state(*_a, **_k):
        return {"unit_cost": 0.0, "components": {"material": 0.0, "labor": 0.0, "overhead": 0.0}}

    async def onhand(*_a, **_k):
        return 0.0

    async def save(_db, *, res, **_k):
        return res

    monkeypatch.setattr(fcl, "wac_state", state)
    monkeypatch.setattr(fcl, "valued_onhand", onhand)
    monkeypatch.setattr(fcl, "_save_wac", save)


def test_permak_tidak_dibebankan_ulang_pada_penerimaan_berikutnya(monkeypatch):
    _patch_wac(monkeypatch)
    db = FakeDB()
    db.dewi_cmt_permak.docs = [{"id": "pm1", "po_item_id": "pi1", "total_cost": 20000, "qty": 4}]
    poi = {"id": "pi1", "cmt_price_snapshot": 10000}
    ly1 = run(fcl.push_layer(db, material_id="fg-a", qty=45, po_item=poi))
    ly2 = run(fcl.push_layer(db, material_id="fg-a", qty=5, po_item=poi))
    assert ly1["breakdown"]["permak_cost"] == round(20000 / 45, 2)
    assert ly2["breakdown"]["permak_cost"] == 0.0
    charged = ly1["breakdown"]["permak_cost"] * 45 + ly2["breakdown"]["permak_cost"] * 5
    assert abs(charged - 20000) < 1                          # dulu Rp40.000
    pm = db.dewi_cmt_permak.docs[0]
    assert pm["permak_absorbed_cost"] == 20000 and pm["permak_absorbed_layer_ids"] == [ly1["id"]]


def test_kenaikan_ongkos_permak_setelah_diserap_hanya_selisihnya(monkeypatch):
    _patch_wac(monkeypatch)
    db = FakeDB()
    db.dewi_cmt_permak.docs = [{"id": "pm1", "po_item_id": "pi1", "total_cost": 20000}]
    poi = {"id": "pi1", "cmt_price_snapshot": 10000}
    run(fcl.push_layer(db, material_id="fg-a", qty=10, po_item=poi))
    db.dewi_cmt_permak.docs[0]["total_cost"] = 25000
    ly = run(fcl.push_layer(db, material_id="fg-a", qty=10, po_item=poi))
    assert ly["breakdown"]["permak_cost"] == 500.0
    assert db.dewi_cmt_permak.docs[0]["permak_absorbed_cost"] == 25000


def test_pratinjau_biaya_batch_tidak_menandai_permak(monkeypatch):
    db = FakeDB()
    db.dewi_cmt_permak.docs = [{"id": "pm1", "po_item_id": "pi1", "total_cost": 20000}]
    run(fcl.compute_batch_unit_cost(db, po_item={"id": "pi1"}, qty=10))
    assert "permak_absorbed_cost" not in db.dewi_cmt_permak.docs[0]


# ══════════════════════════════════════════════════════════════════════════════
# 10 · HPP WO memakai biaya saat bahan keluar
# ══════════════════════════════════════════════════════════════════════════════
def test_harga_bahan_dari_saat_keluar_lalu_master_lalu_bawaan():
    mat = {"unit_cost": 12000, "type": "accessory"}
    assert rhpp.mi_item_unit_cost({"unit_cost_applied": 9000}, mat, 50000, 300) == 9000
    assert rhpp.mi_item_unit_cost({}, mat, 50000, 300) == 12000
    assert rhpp.mi_item_unit_cost({}, {"type": "accessory"}, 50000, 300) == 300


def _mi_db():
    db = FakeDB()
    db.rahaza_materials.docs = [{"id": "m1", "name": "Kain", "unit_cost": 70000, "unit": "kg", "type": "fabric"}]
    db.rahaza_material_issues.docs = [{"id": "mi1", "job_id": "j1", "work_order_id": "j1", "status": "issued",
                                       "items": [{"material_id": "m1", "qty_issued": 10,
                                                  "unit_cost_applied": 50000}]}]
    return db


def test_hpp_wo_memakai_unit_cost_applied_bukan_harga_master_hari_ini(monkeypatch):
    db = _mi_db()

    async def get_wo(_db, wo_id):
        return {"id": wo_id, "wo_number": "JOB-1", "qty": 10}

    monkeypatch.setattr(wo_reader, "get_wo", get_wo)
    out = run(rhpp._compute_hpp(db, "j1"))
    assert out["material_cost"] == 500000                    # 10 × 50.000, bukan 70.000
    assert out["material_breakdown"][0]["unit_cost"] == 50000


def test_hpp_job_internal_memakai_unit_cost_applied():
    db = _mi_db()
    db.production_jobs.docs = [{"id": "j1", "job_number": "JOB-1"}]
    db.production_job_items.docs = [{"job_id": "j1", "ordered_qty": 10, "produced_qty": 10}]
    out = run(pia.compute_hpp_job(db, "j1"))
    assert out["material_cost"] == 500000


# ══════════════════════════════════════════════════════════════════════════════
# 2 · Angka HPP karangan dihapus
# ══════════════════════════════════════════════════════════════════════════════
def test_angka_order_maklon_hanya_yang_tercatat():
    db = FakeDB()
    db.dewi_maklon_material_issues.docs = [{"order_id": "o1", "qty": 10, "unit_cost": 2000}]
    fig = run(rhpp.maklon_order_figures(db, {"id": "o1", "qty_ordered": 100, "price_per_pcs": 15000}))
    # Tahap 9 (keputusan No. 13): angka order = HPP per PO (core.hpp_aktual). Koleksi lama
    # `dewi_maklon_material_issues` (tidak ditulis lagi) tidak dibaca; order tanpa PO = belum ada data.
    assert fig["qty"] == 100 and fig["material_cost"] == 0.0 and fig["revenue"] == 0.0
    # dulu: hpp_actual = 20000 × 1,3 × 1,15 dan hpp_estimated = pendapatan
    assert fig["hpp_actual"] is None and fig["hpp_estimated"] is None and fig["margin"] is None


def test_hpp_po_tidak_lagi_menyamakan_estimasi_dengan_aktual(monkeypatch):
    db = FakeDB()
    db.production_pos.docs = [{"id": "po1", "po_number": "PO-1"}]

    async def load_wos(_db, **_k):
        return [{"id": "j1", "wo_number": "JOB-1"}]

    async def compute(_db, _wid):
        return {"total_cost": 750000, "material_cost": 500000, "labor_cost": 250000, "overhead_cost": 0}

    monkeypatch.setattr(wo_reader, "load_wos", load_wos)
    monkeypatch.setattr(rhpp, "_compute_hpp", compute)
    monkeypatch.setattr(rhpp, "require_auth", _user)
    monkeypatch.setattr(rhpp, "get_db", lambda: db)
    out = run(rhpp.hpp_for_production_po("po1", FakeRequest()))
    # Tahap 9: endpoint lama = HPP per PO (satu hitungan), bukan Σ HPP job; estimasi tetap "belum ada data"
    assert out["source"] == "hpp_per_po" and out["total_cost_actual"] == 0.0
    assert out["total_cost_estimated"] is None and out["delta_pct"] is None and out["wo_breakdown"] == []


def test_unduhan_laporan_po_memakai_mesin_hpp_bukan_tarif_karangan(monkeypatch):
    db = FakeDB()

    async def compute(_db, _wid):
        return {"material_cost": 500000, "labor_cost": 120000, "overhead_cost": 30000, "total_cost": 650000}

    monkeypatch.setattr(rhpp, "_compute_hpp", compute)
    row = run(reports._wo_cost_row(db, {"id": "j1", "completed_qty": 8}))
    assert (row["labor_cost"], row["overhead_cost"], row["total_cost"]) == (120000, 30000, 650000)
    assert row["completed_qty"] == 8


def test_tidak_ada_pengali_hpp_karangan_di_kode():
    src = (Path(rhpp.__file__).read_text(encoding="utf-8")
           + Path(reports.__file__).read_text(encoding="utf-8"))
    for bad in ("* 0.3", "* 0.15", "* 5000", "estimated = actual"):
        assert bad not in src, bad
    fe = REPO / "frontend/src/components/erp/RahazaHPPModule.jsx"
    if not fe.exists():
        pytest.skip("frontend tidak tersedia")
    assert "* 0.95" not in fe.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# 3 · Detail PO maklon 360°
# ══════════════════════════════════════════════════════════════════════════════
def test_biaya_bom_dibaca_dari_materials_dan_dipisah_milik_da():
    bom = {"materials": [
        {"material_name": "Kain klien", "ownership": "client_provided", "qty_estimated": 100,
         "cost_per_unit": 30000},
        {"material_name": "Zipper", "ownership": "cv_da_stock", "qty_estimated": 200, "cost_per_unit": 1500,
         "estimated_cost": 300000, "qty_actual": 180},
    ]}
    c = po360.bom_costs(bom)
    assert c["estimated"] == 3_300_000 and c["estimated_da"] == 300_000
    assert c["actual"] == 270_000 and c["actual_da"] == 270_000
    assert po360.bom_costs(None)["estimated"] == 0


def test_po_360_qty_terkirim_dari_surat_jalan_buyer(monkeypatch):
    db = FakeDB()
    db.production_pos.docs = [{"id": "po1", "po_number": "PO-MK-1", "business_type": "maklon",
                               "status": "In Production"}]
    db.po_items.docs = [{"id": "pi1", "po_id": "po1", "qty": 100, "sku": "A"}]
    db.buyer_shipments.docs = [{"id": "bs1", "shipment_number": "SJ-BYR-1", "po_id": "po1",
                                "receiver_type": "buyer", "ship_status": "Shipped"}]
    db.buyer_shipment_items.docs = [{"id": "bsi1", "shipment_id": "bs1", "po_item_id": "pi1",
                                     "qty_shipped": 30}]
    db.dewi_maklon_bom.docs = [{"po_id": "po1", "materials": [
        {"material_name": "Label", "ownership": "cv_da_stock", "qty_estimated": 100, "cost_per_unit": 500}]}]

    async def no_progress(*_a, **_k):
        return None

    monkeypatch.setattr(po360, "get_db", lambda: db)
    monkeypatch.setattr(po360, "compute_po_progress", no_progress)
    out = run(po360.maklon_po_360("po1", user=dict(USER)))
    assert out["kpis"]["total_dispatched"] == 30 and out["kpis"]["total_qty"] == 100
    assert out["po"]["items"][0]["qty_dispatched"] == 30
    assert out["dispatches"][0]["dispatch_number"] == "SJ-BYR-1"
    assert out["hpp"]["bom_estimated_cost"] == 50000
    assert out["hpp"]["gross_margin_estimate"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# 4 · Dashboard Cutting & Produksi
# ══════════════════════════════════════════════════════════════════════════════
def test_kain_kg_dan_yard_tidak_dijumlah():
    rows = [{"_id": "kg", "n": 2, "planned": 200, "produced": 150, "consumed": 30, "waste": 1.5},
            {"_id": "yard", "n": 1, "planned": 100, "produced": 80, "consumed": 120, "waste": 4},
            {"_id": "KG", "n": 1, "planned": 50, "produced": 50, "consumed": 10, "waste": 0.5}]
    s = cutting.summarize_cutting_units(rows)
    by = {u["unit"]: u for u in s["by_unit"]}
    assert set(by) == {"kg", "yard"}
    assert by["kg"]["consumed"] == 40 and by["kg"]["waste"] == 2 and by["kg"]["yield"] == 5.0
    assert by["yard"]["yield"] == round(80 / 120, 3)
    assert s["consumed"] is None and s["waste"] is None and s["yield"] is None   # dua satuan
    assert s["produced"] == 280 and s["planned_output"] == 350
    one = cutting.summarize_cutting_units(rows[:1])
    assert one["consumed"] == 30 and one["yield"] == 5.0


class _AggCollection:
    """Koleksi palsu dengan `aggregate` $match + $group sederhana (khusus uji ini)."""

    def __init__(self, docs):
        self.docs = docs
        self.pipelines = []

    def aggregate(self, pipeline):
        self.pipelines.append(copy.deepcopy(pipeline))
        docs = [d for d in self.docs if match(d, pipeline[0].get("$match", {}))]
        grp = pipeline[-1]["$group"]
        key = grp["_id"].lstrip("$")
        out: dict = {}
        for d in docs:
            r = out.setdefault(d.get(key), {"_id": d.get(key)})
            for f, spec in grp.items():
                if f == "_id":
                    continue
                v = spec["$sum"]
                r[f] = r.get(f, 0) + (v if isinstance(v, (int, float)) else (d.get(v.lstrip("$")) or 0))
        rows = list(out.values())

        class _Cur:
            async def to_list(self, _n=None):
                return rows
        return _Cur()


class _AggDB:
    def __init__(self, orders):
        self.orders = _AggCollection(orders)

    def __getitem__(self, name):
        assert name == cutting.ORDERS
        return self.orders


def test_order_cutting_batal_tidak_masuk_rencana():
    db = _AggDB([
        {"status": "in_progress", "input_unit": "kg", "planned_output_qty": 100, "produced_qty": 40,
         "consumed_input_qty": 8, "waste_qty": 0.2},
        {"status": "cancelled", "input_unit": "kg", "planned_output_qty": 500, "produced_qty": 0,
         "consumed_input_qty": 0, "waste_qty": 0},
    ])
    tot = run(cutting.cutting_unit_totals(db))
    assert tot["planned_output"] == 100 and tot["produced"] == 40
    assert db.orders.pipelines[0][0] == {"$match": {"status": {"$ne": cutting.STATUS_CANCELLED}}}


# ══════════════════════════════════════════════════════════════════════════════
# 6 · Qty aksesoris PO desimal
# ══════════════════════════════════════════════════════════════════════════════
def test_qty_aksesoris_mempertahankan_desimal():
    assert ppos.accessory_qty("2.5") == 2.5
    assert ppos.accessory_qty("2,75") == 2.75
    assert ppos.accessory_qty(12.125) == 12.125
    assert ppos.accessory_qty(None) == 0.0 and ppos.accessory_qty("") == 0.0
    for bad in ("-1", "dua"):
        with pytest.raises(HTTPException) as e:
            ppos.accessory_qty(bad)
        assert e.value.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# 8 · Kiriman vendor tidak bisa diterima selama PO Draf
# ══════════════════════════════════════════════════════════════════════════════
def _vs_db(po_status):
    db = FakeDB()
    db.production_pos.docs = [{"id": "po1", "po_number": "PO-1", "status": po_status}]
    db.vendor_shipments.docs = [{"id": "s1", "status": "Sent", "po_id": "", "vendor_id": "v1"}]
    db.vendor_shipment_items.docs = [{"id": "si1", "shipment_id": "s1", "po_id": "po1"}]
    return db


def _patch_vs(monkeypatch, db):
    async def no_override(*_a, **_k):
        return None

    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(vs, "require_auth", _user)
    monkeypatch.setattr(vs, "get_db", lambda: db)
    monkeypatch.setattr(vs, "resolve_override", no_override)
    monkeypatch.setattr(vs, "log_activity", noop)


def test_kiriman_vendor_ditolak_selama_po_draf(monkeypatch):
    db = _vs_db("Draft")
    _patch_vs(monkeypatch, db)
    assert run(vs.draft_pos_of_shipment(db, "s1")) == ["PO-1"]
    with pytest.raises(HTTPException) as e:
        run(vs.update_vendor_shipment("s1", FakeRequest({"status": "Received"})))
    assert e.value.status_code == 400 and "PO-1" in e.value.detail and "Draf" in e.value.detail
    assert db.vendor_shipments.docs[0]["status"] == "Sent"


def test_kiriman_vendor_diterima_setelah_po_dikonfirmasi(monkeypatch):
    db = _vs_db("Confirmed")
    _patch_vs(monkeypatch, db)
    out = run(vs.update_vendor_shipment("s1", FakeRequest({"status": "Received"})))
    assert out["status"] == "Received"


def test_buat_kiriman_tidak_lagi_melompatkan_po_draf_ke_distributed():
    src = Path(vs.__file__).read_text(encoding="utf-8")
    assert "{'$set': {'status': 'Distributed'" not in src


# ══════════════════════════════════════════════════════════════════════════════
# 9 · Label formulir PO berbahasa Indonesia
# ══════════════════════════════════════════════════════════════════════════════
def test_label_harga_formulir_po_bahasa_indonesia():
    fe = REPO / "frontend/src/components/erp/engine/ProductionPOModule.jsx"
    if not fe.exists():
        pytest.skip("frontend tidak tersedia")
    src = fe.read_text(encoding="utf-8")
    assert "Selling Price (Rp)" not in src and "CMT Price (Rp)" not in src
    # Tahap 8 (K12, 7 Nov 2026): label upah diseragamkan untuk PO internal & maklon → "Upah jahit per pcs (Rp)"
    assert "Harga jasa ke klien (Rp)" in src and "Upah jahit per pcs (Rp)" in src
