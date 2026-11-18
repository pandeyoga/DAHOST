"""Uji unit HERMETIK — RESEP KAIN potongan (owner 18 Nov 2026: "ada bom atau product yang lebih dari 1 kain … tambahkan
mekanisme cuttingnya … bomnya harus ada dua kain atau lebih otomatis menyesuaikan roll kainnya").

Skenario nyata (SPEK PRODUK): Ona = badan Rib Salur + kerah/paspol Knit 24; Rasha = badan Hornet + lengan Shakila.
  · resep dirapikan (peran bawaan, kain dobel, perkiraan kosong ≠ nol) dan divalidasi ke master kain roll;
  · order cutting wajib memuat semua kain resep, dan pcs hasil hanya boleh dilaporkan bila semua kainnya terpakai;
  · rencana kain = Σ perkiraan/pcs × target per kain;
  · HPP: nilai tiap kain dibagi ke hasil yang memakainya — order tanpa resep = aturan 10 Nov persis.

Jalankan:  cd backend && python -m pytest tests/unit/test_resep_kain.py -q
"""
import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402
import _fake_mongo as fm  # noqa: E402
from core import resep_kain as rk  # noqa: E402
from core.cut_panel_value import _per_line_cpp  # noqa: E402

SLR = {"material_id": "f-slr", "code": "KN-SLR-CRM", "role": "Utama", "qty_per_pcs": 0.35, "unit": "kg"}
K24 = {"material_id": "f-k24", "code": "KN-K24-CRM", "role": "Kerah", "qty_per_pcs": 0.05, "unit": "kg"}


def run(coro):
    return asyncio.run(coro)


def test_normalisasi_peran_bawaan_kain_dobel_dan_perkiraan_kosong():
    rows = rk.normalisasi([{"code": "kn-slr-crm"}, {"code": "KN-K24-CRM", "qty_per_pcs": ""},
                           {"code": "KN-SLR-CRM", "role": "Kerah"}, {"name": "tanpa kode"}, "bukan dict"])
    assert [r["code"] for r in rows] == ["KN-SLR-CRM", "KN-K24-CRM"]
    assert [r["role"] for r in rows] == ["Utama", "Kombinasi"]
    assert rows[1]["qty_per_pcs"] is None            # kosong = belum diisi, bukan nol yang seolah benar
    assert rk.normalisasi([{"code": "X", "qty_per_pcs": "0"}])[0]["qty_per_pcs"] is None


def _db_master():
    db = fm.FakeDB()
    db.rahaza_materials.docs += [
        {"id": "f-slr", "code": "KN-SLR-CRM", "name": "RIB SALUR FNS 135 CM", "unit": "kg", "type": "fabric", "active": True},
        {"id": "f-k24", "code": "KN-K24-CRM", "name": 'RIB KNIT 24"', "unit": "kg", "type": "fabric", "active": True},
        {"id": "cut1", "code": "CUT-DA-2201-CRM-ALLSIZE", "name": "Potongan Ona", "unit": "pcs", "type": "fabric",
         "is_cut_panel": True, "active": True},
        {"id": "acc", "code": "A-KRT-0003", "name": "Karet 3 cm", "unit": "cm", "type": "accessory", "active": True},
    ]
    return db


def test_lengkapi_menyelaraskan_ke_master_dan_mengisi_kain_asal_tbd():
    db = _db_master()
    line = {"code": "CUT-DA-2201-CRM-ALLSIZE", "is_cut_panel": True, "source_material_code": "KN-TBD-CRM",
            "fabric_recipe": [{"code": "KN-SLR-CRM"}, {"material_id": "f-k24", "role": "Kerah", "qty_per_pcs": 0.05}]}
    out = run(rk.lengkapi(db, [line, {"code": "A-KRT-0003", "name": "Karet"}]))
    rec = out[0]["fabric_recipe"]
    assert [(r["material_id"], r["code"], r["unit"], r["role"]) for r in rec] == [
        ("f-slr", "KN-SLR-CRM", "kg", "Utama"), ("f-k24", "KN-K24-CRM", "kg", "Kerah")]
    assert out[0]["source_material_code"] == "KN-SLR-CRM"      # KN-TBD (belum ditentukan) diganti kain utama
    assert "fabric_recipe" not in out[1]


@pytest.mark.parametrize("kode,pesan", [("A-KRT-0003", "bukan kain roll"), ("CUT-DA-2201-CRM-ALLSIZE", "potongan"),
                                        ("KN-TIDAK-ADA", "tidak ada di master")])
def test_lengkapi_menolak_bukan_kain_roll(kode, pesan):
    db = _db_master()
    with pytest.raises(HTTPException) as e:
        run(rk.lengkapi(db, [{"code": "CUT-DA-2201-CRM-ALLSIZE", "is_cut_panel": True,
                              "fabric_recipe": [{"code": kode}]}]))
    assert e.value.status_code == 400 and pesan in e.value.detail


def test_resep_hanya_di_baris_potongan():
    with pytest.raises(HTTPException) as e:
        run(rk.lengkapi(_db_master(), [{"code": "A-KRT-0003", "fabric_recipe": [{"code": "KN-SLR-CRM"}]}]))
    assert "hanya untuk baris potongan" in e.value.detail


def test_rencana_kain_menjumlah_per_kain_dan_menandai_perkiraan_kosong():
    outs = [{"label": "Ona CRM", "planned_output_qty": 100, "fabric_recipe": [SLR, K24]},
            {"label": "Kazara CRM", "planned_output_qty": 50, "fabric_recipe": [SLR, {**K24, "qty_per_pcs": None}]},
            {"label": "Lavina", "planned_output_qty": 30}]
    rows = {r["code"]: r for r in rk.rencana_kain(outs)}
    assert rows["KN-SLR-CRM"]["planned"] == pytest.approx(52.5) and not rows["KN-SLR-CRM"]["unknown"]
    assert rows["KN-K24-CRM"]["planned"] == pytest.approx(5.0) and rows["KN-K24-CRM"]["unknown"]
    assert rows["KN-SLR-CRM"]["used_by"] == ["Ona CRM", "Kazara CRM"]


def test_order_wajib_memuat_semua_kain_resep():
    outs = [{"label": "Ona CRM", "fabric_recipe": [SLR, K24]}, {"label": "Lavina BLE"}]
    assert rk.kain_resep_hilang(outs, {"f-slr", "f-k24"}) == []
    msgs = rk.kain_resep_hilang(outs, {"f-slr"})
    assert msgs == ["Ona CRM memakai KN-K24-CRM (Kerah)"]


def test_pcs_hasil_ditolak_sebelum_semua_kain_resep_terpakai():
    ona = {"label": "Ona CRM", "fabric_recipe": [SLR, K24]}
    assert rk.kain_resep_belum_dipakai([(ona, 20)], {"f-slr": 7.0}) == ["Ona CRM: KN-K24-CRM (Kerah)"]
    assert rk.kain_resep_belum_dipakai([(ona, 20)], {"f-slr": 7.0, "f-k24": 1.0}) == []
    assert rk.kain_resep_belum_dipakai([(ona, 0)], {}) == []      # baris tanpa pcs di laporan ini tidak diperiksa


def test_alokasi_tanpa_resep_sama_dengan_aturan_10_nov():
    vals = rk.alokasi_nilai({"f-slr": 1000.0, "f-k24": 200.0}, [{"qty": 40}, {"qty": 20}], None)
    assert vals == [pytest.approx(800.0), pytest.approx(400.0)]       # 1200 ÷ 60 pcs = 20/pcs untuk semua


def test_alokasi_per_kain_ke_hasil_yang_memakainya():
    # Ona (Rib Salur + Knit 24) 40 pcs dan produk lain yang resepnya hanya Rib Salur 20 pcs dalam satu order.
    # Rib Salur dipakai keduanya → dibagi menurut pcs × perkiraan; Knit 24 hanya ke Ona.
    vals = rk.alokasi_nilai({"f-slr": 1200.0}, [{"qty": 40}, {"qty": 20}], [[SLR, K24], [SLR]])
    assert vals == [pytest.approx(800.0), pytest.approx(400.0)]
    vals = rk.alokasi_nilai({"f-k24": 300.0}, [{"qty": 40}, {"qty": 20}], [[SLR, K24], [SLR]])
    assert vals == [pytest.approx(300.0), pytest.approx(0.0)]        # Knit 24 tidak ada di resep produk kedua


def test_alokasi_berbobot_perkiraan_bila_semua_punya_angka():
    a = {**K24, "qty_per_pcs": 0.10}
    vals = rk.alokasi_nilai({"f-k24": 300.0}, [{"qty": 10}, {"qty": 10}], [[SLR, a], [SLR, K24]])
    assert vals == [pytest.approx(200.0), pytest.approx(100.0)]       # 0,10 vs 0,05 kg/pcs → 2 : 1
    tanpa = {**K24, "qty_per_pcs": None}
    vals = rk.alokasi_nilai({"f-k24": 300.0}, [{"qty": 10}, {"qty": 10}], [[SLR, a], [SLR, tanpa]])
    assert vals == [pytest.approx(150.0), pytest.approx(150.0)]       # satu tanpa angka → bobot pcs


def test_kain_di_luar_resep_tidak_hilang():
    vals = rk.alokasi_nilai({"f-lain": 90.0}, [{"qty": 10}, {"qty": 20}], [[SLR], [K24]])
    assert sum(vals) == pytest.approx(90.0) and vals == [pytest.approx(30.0), pytest.approx(60.0)]


def test_hpp_per_baris_dari_jejak_kain():
    fabrics = [{"fabric_id": "f-slr", "value_out": 1200.0}, {"fabric_id": "f-k24", "value_out": 300.0}]
    res = _per_line_cpp(fabrics, [{"qty": 40}, {"qty": 20}], [[SLR, K24], [SLR]], 25.0)
    assert res["by_recipe"] and res["cpp"] == [pytest.approx(27.5), pytest.approx(20.0)]
    flat = _per_line_cpp(fabrics, [{"qty": 40}, {"qty": 20}], [[], []], 25.0)
    assert not flat["by_recipe"] and flat["cpp"] == [25.0, 25.0]


def test_pagar_order_cutting_menolak_kain_resep_yang_kurang():
    import routes.cutting as ct
    outs = [{"model_name": "Ona", "output_color": "Cream", "output_size": "ALLSIZE", "fabric_recipe": [SLR, K24]}]
    with pytest.raises(HTTPException) as e:
        ct._cek_resep_di_order(outs, [{"input_material_id": "f-slr"}])
    assert e.value.status_code == 400 and "KN-K24-CRM (Kerah)" in e.value.detail
    ct._cek_resep_di_order(outs, [{"input_material_id": "f-slr"}, {"input_material_id": "f-k24"}])
    ins = [{"input_material_id": "f-slr", "consumed_input_qty": 5}, {"input_material_id": "f-k24", "consumed_input_qty": 0}]
    with pytest.raises(HTTPException) as e:
        ct._cek_resep_dipakai(ins, [(outs[0], {"output_qty": 10})], [{"line": ins[0], "used": 2}])
    assert "KN-K24-CRM" in e.value.detail
    ct._cek_resep_dipakai(ins, [(outs[0], {"output_qty": 10})], [{"line": ins[1], "used": 0.4}])
