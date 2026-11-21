"""Uji unit HERMETIK — kain tech pack R&D SINKRON master kain (owner 21 Nov 2026, permintaan Ega R&D).

Jalankan:  cd backend && python -m pytest tests/unit/test_kain_master_21nov.py -q
"""
import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB  # noqa: E402
from core import bom_techpack as bt  # noqa: E402
from core import kain_master as km  # noqa: E402
from utils.fabric_costing import compute_fabric_cost  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _db():
    db = FakeDB()
    db.rahaza_materials.docs = [
        {"id": "F1", "code": "KN-RMT-LLG", "name": "RAYON TWILL MOTIF", "type": "fabric", "unit": "yard",
         "base_uom": "yard", "color": "Ling ling", "unit_cost": 40000, "active": True, "category": "C1",
         "category_code": "FABRIC"},
        {"id": "F2", "code": "KN-KTN-BLK", "name": "KATUN KNIT", "type": "fabric", "unit": "kg", "base_uom": "kg",
         "color": "Black", "unit_cost": 100000, "active": True, "gsm": 180, "width_cm": 180},
        {"id": "F3", "code": "KN-TBD-XXX", "name": "KAIN BELUM DITENTUKAN", "type": "fabric", "unit": "yard",
         "active": True},
        {"id": "C1", "code": "CUT-DA-0001-LLG-M", "name": "Potongan", "type": "fabric", "unit": "pcs",
         "is_cut_panel": True, "active": True},
    ]
    db.dewi_rnd_materials.docs = [
        {"id": "R1", "material_code": "KN-RMT", "material_name": "RAYON TWILL MOTIF", "unit": "yard"},
        {"id": "R2", "material_code": "KN-SFN", "material_name": "SIFON", "unit": "m", "price_unit": "m",
         "price_per_unit": 25000},
    ]
    db.rahaza_colors.docs = [{"id": "W1", "code": "SKB", "name": "Sakura Blush"},
                             {"id": "W2", "code": "LLG", "name": "Ling ling"}]
    return db


def test_daftar_keluarga_gabungan_master_dan_riset():
    fam = {f["kode"]: f for f in run(km.daftar_keluarga(_db()))}
    assert set(fam) == {"KN-RMT", "KN-KTN", "KN-SFN", "KN-TBD"}  # potongan CUT- tidak ikut
    assert fam["KN-TBD"]["penanda"] and not fam["KN-RMT"]["penanda"]
    assert fam["KN-RMT"]["satuan"] == "yard" and fam["KN-RMT"]["satuan_pakai"] == "cm"
    assert fam["KN-KTN"]["satuan"] == "kg" and fam["KN-KTN"]["satuan_pakai"] == "kg"
    assert [w["kode"] for w in fam["KN-RMT"]["warna"]] == ["KN-RMT-LLG"] and fam["KN-RMT"]["riset_id"] == "R1"


def test_normalisasi_kain_ikut_master_dan_tolak_kain_tak_dikenal():
    db = _db()
    rows = run(km.normalisasi_kain(db, [
        {"name": "Rayon twill motif ", "role": "main", "color_code": "LLG"},     # ejaan lama → KN-RMT
        {"kode": "KN-KTN", "name": "apa saja", "role": "combination", "color_code": "RED"},
        {"name": "", "role": "main"},                                              # baris kosong dibuang
    ]))
    assert [(r["kode"], r["name"], r["satuan"], r["satuan_pakai"]) for r in rows] == [
        ("KN-RMT", "RAYON TWILL MOTIF", "yard", "cm"), ("KN-KTN", "KATUN KNIT", "kg", "kg")]
    assert rows[0]["master_code"] == "KN-RMT-LLG" and rows[1]["master_code"] == ""   # RED belum punya master
    with pytest.raises(HTTPException) as e:
        run(km.normalisasi_kain(db, [{"name": "Knit salur", "role": "main"}]))
    assert e.value.status_code == 400 and "belum ada di master kain" in e.value.detail
    cons = km.satuan_pemakaian([{"fabric_role": "main"}, {"fabric_role": "combination"}], rows)
    assert [c["satuan"] for c in cons] == ["cm", "kg"]


def test_buat_master_warna_dari_keluarga_dan_kabari_pemegang_roll(monkeypatch):
    db = _db()
    kabar = []

    async def _kabari(db_, judul, isi, user, ref):
        kabar.append((judul, isi))
    monkeypatch.setattr(km, "_kabari_pemegang_roll", _kabari)
    out = run(km.pastikan_master_warna(db, "KN-RMT", "SKB", {"id": "u1", "name": "Ega"}))
    m = out["material"]
    assert out["dibuat"] and m["code"] == "KN-RMT-SKB" and m["unit"] == "yard" and m["base_uom"] == "yard"
    assert m["color"] == "Sakura Blush" and m["unit_cost"] == 40000 and m["category_code"] == "FABRIC"
    assert any(d["code"] == "KN-RMT-SKB" for d in db.rahaza_materials.docs)
    assert len(kabar) == 1 and "KN-RMT-SKB" in kabar[0][0]
    lagi = run(km.pastikan_master_warna(db, "KN-RMT", "SKB"))                       # sudah ada → tidak dobel
    assert not lagi["dibuat"] and len(kabar) == 1
    with pytest.raises(HTTPException):
        run(km.pastikan_master_warna(db, "KN-RMT", "ZZZ"))                          # warna tak ada di master warna
    with pytest.raises(HTTPException) as e:
        run(km.pastikan_master_warna(db, "KN-TBD", "SKB"))                          # penanda: tidak dibuatkan master
    assert "belum ditentukan" in e.value.detail


def test_daftar_kain_baru_wajib_satuan_dan_kode_unik(monkeypatch):
    db = _db()
    kabar = []

    async def _kabari(db_, judul, isi, user, ref):
        kabar.append(judul)
    monkeypatch.setattr(km, "_kabari_pemegang_roll", _kabari)
    with pytest.raises(HTTPException) as e:
        run(km.daftar_keluarga_baru(db, nama="Knit salur", kode="KN-KSL", satuan=""))
    assert "Satuan kain wajib" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(km.daftar_keluarga_baru(db, nama="Rayon baru", kode="KN-RMT", satuan="yard"))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        run(km.daftar_keluarga_baru(db, nama="sifon", kode="KN-SF2", satuan="m"))
    assert e.value.status_code == 409 and "KN-SFN" in e.value.detail                   # nama sama → pilih dari daftar
    doc = run(km.daftar_keluarga_baru(db, nama="Knit salur", kode="kn-ksl", satuan="kg", gsm="200", lebar_cm=""))
    assert doc["material_code"] == "KN-KSL" and doc["unit"] == "kg" and doc["gsm"] == 200.0 and kabar


def test_biaya_kain_kg_dan_harga_master_dulu():
    db = _db()
    tp = {"fabrics": [{"name": "KATUN KNIT", "kode": "KN-KTN", "master_code": "KN-KTN-BLK", "role": "main",
                       "satuan_pakai": "kg"},
                      {"name": "RAYON TWILL MOTIF", "kode": "KN-RMT", "master_code": "KN-RMT-LLG",
                       "role": "combination", "satuan_pakai": "cm"}],
          "fabric_consumption": [
              {"size": "M", "fabric_role": "main", "satuan": "kg", "weight_kg": "1,2".replace(",", "."), "yield_pcs": 4},
              {"size": "L", "fabric_role": "main", "satuan": "kg", "weight_kg": 1.5, "yield_pcs": 5},
              {"size": "L", "fabric_role": "combination", "satuan": "cm", "length_cm": 100, "yield_pcs": 2}]}
    res = run(compute_fabric_cost(db, tp, "M"))
    m = res["selected"]
    assert m["size"] == "M" and m["kg_per_pcs"] == 0.3 and m["fabric_cost_per_pcs"] == 30000.0
    assert m["pakai"] == {"qty": 0.3, "satuan": "kg", "harga": 100000.0}
    e = m["entries"][0]
    assert e["satuan"] == "kg" and e["price_source"] == "master_warna" and e["meters_per_pcs"] == 0.0
    big = next(s for s in res["sizes"] if s["size"] == "L")
    rayon = next(x for x in big["entries"] if x["satuan"] == "m")
    assert rayon["qty_per_pcs"] == 0.5 and round(rayon["price_per_unit"], 2) == round(40000 / 0.9144, 2)
    assert big["pakai"]["satuan"] == "set"                                              # campuran kg + meter
    assert round(big["fabric_cost_per_pcs"], 2) == round(0.3 * 100000 + 0.5 * 40000 / 0.9144, 2)


def test_bom_techpack_kode_master_dan_pakai_kg():
    cons = [{"size": "M", "fabric_role": "main", "satuan": "kg", "weight_kg": 1.2, "yield_pcs": 4}]
    qty, satuan, note = bt.pakai_per_pcs(cons, "main", "M")
    assert round(qty, 4) == 0.3 and satuan == "kg" and note == ""
    assert bt.meter_per_pcs(cons, "main", "M")[0] is None                               # baris kg bukan meter
    assert bt.qty_satuan_kain(0.3, {"unit": "kg", "base_uom": "kg"}, "kg") == 0.3
    yard = {"unit": "yard", "base_uom": "yard", "gsm": 200, "width_cm": 150}             # 1 m = 0,3 kg
    assert bt.qty_satuan_kain(0.3, yard, "kg") == round(1 / 0.9144, 4)
    db = _db()
    assert run(bt.master_kain(db, "", "BLK", "KN-KTN"))["id"] == "F2"


def test_satuan_kain_hpp_mode_lama():
    from routes.dewi_rnd_hpp import _satuan_kain_lama
    assert [_satuan_kain_lama(u) for u in ("kg", "meter", "yard", "set", "roll", None)] == [
        "kg", "m", "yard", "set", "m", "m"]


def test_impor_excel_kain_longgar_dan_kategori_style_dari_master():
    db = _db()
    rows, asing = run(km.cocokkan_kain_longgar(db, [{"name": "rayon twill motif", "role": "main"},
                                                    {"name": "Knit salur", "role": "combination"}]))
    assert rows[0]["kode"] == "KN-RMT" and rows[1]["kode"] == "" and asing == ["Knit salur"]
    from routes.dewi_rnd_styles import kategori_master
    db.rahaza_product_categories.docs = [{"id": "c1", "code": "DRESS", "name": "Dress"}]
    assert run(kategori_master(db, "dress")) == "Dress"
    assert run(kategori_master(db, "Gamis lama", "Gamis lama")) == "Gamis lama"        # nilai lama tak diubah
    with pytest.raises(HTTPException):
        run(kategori_master(db, "Kategori ngarang"))
