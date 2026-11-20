"""Uji unit HERMETIK — BOM produksi dari BOM tech pack R&D (owner 20 Nov 2026, pertanyaan Ega R&D).

Jalankan:  cd backend && python -m pytest tests/unit/test_bom_techpack.py -q
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402
from core import bom_techpack as bt  # noqa: E402


def run(coro):
    return asyncio.run(coro)


ITEMS = [
    {"material_id": "A1", "material_code": "A-K18-0001", "material": "Kancing", "qty": 1, "unit": "pcs",
     "color_code": "LLG", "color_name": "Ling ling"},
    {"material_id": "A2", "material_code": "A-K18-0002", "material": "Kancing", "qty": 1, "unit": "pcs",
     "color_code": "", "color_name": "Sakura Blush"},
    {"material_id": "A3", "material_code": "A-KRT-0006", "material": "Karet", "qty": 4, "unit": "cm",
     "color_code": "", "color_name": ""},
    {"material_id": "A4", "material_code": "A-K18-0004", "material": "Kancing", "qty": 1, "unit": "pcs",
     "color_code": "", "color_name": "BROWN"},
]
VARIANTS = [{"color_code": "LLG", "color_name": "Ling ling"}, {"color_code": "SKB", "color_name": "Sakura Blush"},
            {"color_code": "BRB", "color_name": "Brown Abstrak"}]


def test_aksesoris_per_warna_dan_warna_tanpa_varian():
    assert [b["material_id"] for b in bt.baris_untuk_warna(ITEMS, "LLG", "Ling ling")] == ["A1", "A3"]
    assert [b["material_id"] for b in bt.baris_untuk_warna(ITEMS, "SKB", "Sakura Blush")] == ["A2", "A3"]
    assert bt.warna_tak_terpakai(ITEMS, VARIANTS) == ["BROWN"]          # Anya: 'BROWN' vs varian 'Brown Abstrak'


def test_kain_berpasangan_dan_tanpa_warna():
    # Queen: polos utama + motif kombinasi ditulis berpasangan per motif
    queen = [{"name": "Rayon twill polos", "role": "main", "color_code": "BTY"},
             {"name": "Rayon twill motif", "role": "combination", "color_code": "LLG"},
             {"name": "Rayon twill polos", "role": "main", "color_code": "DST"},
             {"name": "Rayon twill motif", "role": "combination", "color_code": "SKB"}]
    assert [(f["name"], w) for f, w in bt.kain_untuk_warna(queen, "LLG")] == [
        ("Rayon twill motif", "LLG"), ("Rayon twill polos", "BTY")]
    assert [w for _f, w in bt.kain_untuk_warna(queen, "SKB")] == ["SKB", "DST"]
    assert bt.kain_untuk_warna(queen, "XXX") == []
    # Anya: satu kain tanpa warna → warna varian
    anya = [{"name": "Rayon twill motif ", "role": "main", "color_code": ""}]
    assert [w for _f, w in bt.kain_untuk_warna(anya, "PHT")] == ["PHT"]


def test_meter_per_pcs_dan_satuan_yard():
    cons = [{"size": "", "fabric_role": "main", "length_cm": "330", "yield_pcs": "3"}]
    m, note = bt.meter_per_pcs(cons, "main", "M")
    assert round(m, 4) == 1.1 and note == ""
    m, note = bt.meter_per_pcs([{"size": "M", "fabric_role": "main", "length_cm": "450", "yield_pcs": "5"}], "main", "XL")
    assert round(m, 2) == 0.9 and "ukuran M" in note
    assert bt.qty_satuan_kain(1.1, {"unit": "yard", "base_uom": "yard"}) == round(1.1 / 0.9144, 4)
    assert bt.qty_satuan_kain(1.1, {"unit": "kg", "base_uom": "kg"}) is None      # tanpa gramasi/lebar: dikosongkan


def _db():
    db = FakeDB()
    db.rahaza_models.docs = [{"id": "M1", "code": "DA-9001", "name": "Anya Uji", "rnd_style_id": "S1"}]
    db.dewi_rnd_tech_packs.docs = [{"id": "T1", "style_id": "S1", "is_latest": True, "version": "v1",
                                    "bom_items": ITEMS,
                                    "fabrics": [{"name": "Rayon twill motif ", "role": "main", "color_code": ""}],
                                    "fabric_consumption": [{"size": "", "fabric_role": "main", "length_cm": "330",
                                                            "yield_pcs": "3"}]}]
    db.rahaza_model_variants.docs = [
        {"id": "V1", "model_id": "M1", "sku": "DA-9001-LLG-M", "color_code": "LLG", "color_name": "Ling ling",
         "size_code": "M", "size_id": "Z1", "active": True},
        {"id": "V2", "model_id": "M1", "sku": "DA-9001-SKB-M", "color_code": "SKB", "color_name": "Sakura Blush",
         "size_code": "M", "size_id": "Z1", "active": True},
        {"id": "V3", "model_id": "M1", "sku": "DA-9001--M", "color_code": "", "color_name": "",
         "size_code": "M", "size_id": "Z1", "active": True}]
    db.dewi_rnd_materials.docs = [{"material_code": "KN-RMT", "material_name": "RAYON TWILL MOTIF"}]
    db.rahaza_materials.docs = [
        {"id": "F1", "code": "KN-RMT-LLG", "name": "RAYON TWILL MOTIF", "type": "fabric", "unit": "yard",
         "base_uom": "yard", "active": True},
        {"id": "A1", "code": "A-K18-0001", "name": "Kancing LLG", "type": "accessory", "unit": "pcs", "active": True},
        {"id": "A2", "code": "A-K18-0002", "name": "Kancing SKB", "type": "accessory", "unit": "pcs", "active": True},
        {"id": "A3", "code": "A-KRT-0006", "name": "Karet", "type": "accessory", "unit": "cm", "active": True}]
    return db


def test_buat_bom_dari_techpack_pratinjau_lalu_terapkan():
    db = _db()
    pra = run(bt.buat_dari_techpack(db, "M1", {"id": "u"}, terapkan=False))
    assert pra["created"] == 2 and pra["pratinjau"] and db.rahaza_boms.docs == []      # pratinjau tidak menulis
    assert [s["alasan"][:17] for s in pra["skipped"]] == ["varian tanpa warn"]
    assert pra["warna_tak_terpakai"] == ["BROWN"]
    out = run(bt.buat_dari_techpack(db, "M1", {"id": "u"}))
    assert out["created"] == 2 and len(db.rahaza_boms.docs) == 2
    llg = next(b for b in db.rahaza_boms.docs if b["color_code"] == "LLG")
    potong = llg["materials"][0]
    assert potong["is_cut_panel"] and potong["code"].startswith("CUT-DA-9001")
    assert potong["fabric_recipe"][0]["code"] == "KN-RMT-LLG" and potong["fabric_recipe"][0]["role"] == "Utama"
    assert potong["fabric_recipe"][0]["qty_per_pcs"] == round(1.1 / 0.9144, 4)
    assert [m["code"] for m in llg["materials"][1:]] == ["A-K18-0001", "A-KRT-0006"]
    skb = next(b for b in db.rahaza_boms.docs if b["color_code"] == "SKB")
    assert "fabric_recipe" not in skb["materials"][0]                                   # KN-RMT-SKB belum ada
    assert "KN-RMT" not in skb["notes"] and "belum ada di master bahan" in skb["notes"]
    assert [m["code"] for m in skb["materials"][1:]] == ["A-K18-0002", "A-KRT-0006"]
    # dijalankan lagi: BOM yang sudah ada tidak disentuh / tidak dobel
    lagi = run(bt.buat_dari_techpack(db, "M1", {"id": "u"}))
    assert lagi["created"] == 0 and len(db.rahaza_boms.docs) == 2


def test_tanpa_techpack_ditolak_dengan_pesan():
    db = FakeDB()
    db.rahaza_models.docs = [{"id": "M2", "code": "DA-9002", "name": "Tanpa TP"}]
    out = run(bt.buat_dari_techpack(db, "M2"))
    assert not out["ok"] and "belum punya tech pack" in out["message"]
