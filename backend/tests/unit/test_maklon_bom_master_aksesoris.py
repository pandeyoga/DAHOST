"""BOM Katalog Buyer dari master material + aksesoris ikut per kiriman CMT (owner, 5 Nov 2026).

Keluhan: "di katalog buyer ada BOM untuk nambah aksesoris dan di pengiriman cmt tidak langsung
terload" dan "BOM di katalog buyer tidak mengambil dari master data".
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
import routes.dewi_maklon_bom_templates as bt  # noqa: E402
from core import shipment_accessories as sa  # noqa: E402

MATS = [
    {"id": "m-zip", "code": "ACC-ZIP-20", "name": "Zipper YKK 20cm", "unit": "pcs", "type": "accessory",
     "unit_cost": 1500, "active": True},
    {"id": "m-label", "code": "ACC-LBL", "name": "Label Woven", "unit": "pcs", "type": "accessory",
     "unit_cost": 300, "active": True},
]


def _db():
    db = FakeDB()
    db.rahaza_materials.docs = [dict(m) for m in MATS]
    return db


def run(c):
    return asyncio.run(c)


# ── BOM template: master yang menang ───────────────────────────────────────
def test_baris_dipilih_dari_master_mengambil_nama_kode_satuan_harga():
    out = run(bt._resolve_template_materials(_db(), [
        {"material_id": "m-zip", "material_name": "ketikan lain", "unit": "", "qty_per_pcs": 1, "cost_per_unit": 0}]))
    m = out[0]
    assert (m["material_name"], m["material_code"], m["unit"], m["cost_per_unit"]) == \
        ("Zipper YKK 20cm", "ACC-ZIP-20", "pcs", 1500.0)
    assert m["unlinked"] is False


def test_baris_lama_ketikan_ditautkan_bila_namanya_sama_persis():
    out = run(bt._resolve_template_materials(_db(), [{"material_name": "label woven", "qty_per_pcs": 2}]))
    assert out[0]["material_id"] == "m-label" and out[0]["unlinked"] is False


def test_ketikan_bahan_klien_boleh_tetapi_ditandai_belum_tertaut():
    out = run(bt._resolve_template_materials(_db(), [{"material_name": "Kain klien rayon", "unit": "m",
                                                      "ownership": "client_provided"}]))
    assert out[0]["material_id"] is None and out[0]["unlinked"] is True


def test_bahan_stok_DA_wajib_dari_master():
    with pytest.raises(HTTPException) as e:
        run(bt._resolve_template_materials(_db(), [{"material_name": "Kancing entah", "ownership": "cv_da_stock"}]))
    assert e.value.status_code == 400 and "master material" in e.value.detail


def test_id_material_yang_tidak_ada_ditolak():
    with pytest.raises(HTTPException):
        run(bt._resolve_template_materials(_db(), [{"material_id": "m-hilang", "material_name": "x"}]))


def test_agregasi_template_membawa_id_master_dan_kepemilikan():
    tpl = {"id": "t1", "version": 2, "buyer_catalog_id": "c1", "materials": [
        {"material_id": "m-zip", "material_code": "ACC-ZIP-20", "material_name": "Zipper YKK 20cm",
         "unit": "pcs", "qty_per_pcs": 1, "ownership": "cv_da_stock", "category": "aksesoris"}]}
    agg, total, _w, _t = run(bt.aggregate_template_lines(_db(), [{"catalog_id": "c1", "qty": 100, "label": "A"}],
                                                         forced_template=tpl))
    row = next(iter(agg.values()))
    assert total == 100 and row["qty_estimated"] == 100
    assert (row["material_id"], row["ownership"]) == ("m-zip", "cv_da_stock")


# ── aksesoris per kiriman ──────────────────────────────────────────────────
@pytest.mark.parametrize("need,po,ship,before,unit,expect", [
    (200, 100, 60, 0, "pcs", 120),      # 2 pcs per garmen, kirim 60 dari 100
    (200, 100, 40, 120, "pcs", 80),     # kiriman terakhir mengambil sisa
    (100, 100, 33, 0, "pcs", 33),
    (101, 100, 50, 0, "pcs", 51),       # satuan hitungan dibulatkan ke atas
    (2.5, 100, 50, 0, "kg", 1.25),      # satuan timbang tidak dibulatkan
    (50, 100, 60, 45, "pcs", 5),        # tidak melebihi sisa
    (50, 0, 60, 0, "pcs", 0),
])
def test_jatah_kiriman(need, po, ship, before, unit, expect):
    assert sa.share_for_shipment(need, po, ship, before, unit) == expect


def test_rencana_aksesoris_kiriman_membaca_kebutuhan_dan_yang_sudah_dikirim():
    db = FakeDB()
    db.production_pos.docs = [{"id": "po1", "po_number": "PO-1", "business_type": "internal"}]
    db.po_items.docs = [{"id": "i1", "po_id": "po1", "qty": 60}, {"id": "i2", "po_id": "po1", "qty": 40}]
    db.po_accessories.docs = [
        {"po_id": "po1", "accessory_id": "m-zip", "accessory_code": "ACC-ZIP-20", "accessory_name": "Zipper",
         "qty_needed": 100, "unit": "pcs"},
        {"po_id": "po1", "accessory_id": "m-label", "accessory_name": "Label", "qty_needed": 200, "unit": "pcs"}]
    db.accessory_shipment_items.docs = [{"po_id": "po1", "accessory_id": "m-zip", "qty_sent": 30}]
    plan = run(sa.accessory_plan(db, "po1", [{"po_item_id": "i1", "qty_sent": 50}], refresh_bom=False))
    rows = {r["accessory_id"]: r for r in plan["rows"]}
    assert plan["po_qty"] == 100 and plan["shipment_qty"] == 50
    assert rows["m-zip"]["qty_sent_before"] == 30 and rows["m-zip"]["qty_suggested"] == 50
    assert rows["m-label"]["qty_suggested"] == 100


def test_aksesoris_tercatat_per_kiriman_hanya_yang_bernilai():
    db = FakeDB()
    ship = {"id": "s1", "shipment_number": "SJ-1", "po_id": "po1", "po_number": "PO-1", "shipment_type": "NORMAL"}
    n = run(sa.record_for_shipment(db, ship, [
        {"accessory_id": "m-zip", "accessory_name": "Zipper", "qty_sent": 50},
        {"accessory_id": "m-label", "accessory_name": "Label", "qty_sent": 0}]))
    assert n == 1 and db.accessory_shipment_items.docs[0]["qty_sent"] == 50
    assert db.accessory_shipment_items.docs[0]["shipment_id"] == "s1"
