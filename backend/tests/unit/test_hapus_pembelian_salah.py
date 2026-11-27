"""Skrip hapus pembelian salah input (owner 27 Nov 2026) — fungsi murninya.

Kasus nyata VPS: PO-20261126-001 Alvino Tex 1.000 yard Rayon Twill @18.000 menurunkan HPP kain 21.000 → 19.037,2915;
cutting CUT-2026-0114 sesudahnya memakai 64,3 yard pada HPP turunan itu. Menghapus penerimaan harus menilai ulang
cutting itu dengan HPP 21.000.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "hapus_pembelian_salah", ROOT / "scripts" / "migrations" / "2026_11_27_hapus_pembelian_salah.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

KAIN = "kain-1"


def _progres(**kw):
    p = {
        "cutting_number": "CUT-2026-0114", "fabric_unit_cost": 19037.2915, "value_out": 1224097.8434,
        "cost_per_pcs_in": 20401.630723, "panel_unit_cost_after": 18536.2967,
        "inputs": [{"line_id": "in-1", "input_material_id": KAIN, "fabric_unit_cost": 19037.2915,
                    "value_out": 1224097.8434, "input_consumed": 64.3}],
        "outputs": [{"line_id": "out-1", "output_material_id": "pot-1", "output_material_code": "CUT-DA-1512-BLE-M",
                     "output_qty": 60, "panel_qty_before": 108, "panel_unit_cost_before": 17500,
                     "panel_unit_cost_after": 18536.2967, "cost_per_pcs_in": 20401.630723}],
    }
    p.update(kw)
    return p


def test_nilai_ulang_cutting_dengan_hpp_kain_yang_benar():
    h = mod.nilai_ulang_progres(_progres(), KAIN, 19037.2915, 21000)
    assert h["value_baru"] == pytest.approx(64.3 * 21000, abs=0.05)          # 1.350.300
    pn = h["panel"][0]
    assert pn["cost_in_baru"] == pytest.approx(1350300 / 60, abs=0.01)       # 22.505/pcs
    assert pn["after_baru"] == pytest.approx((108 * 17500 + 1350300) / 168, abs=0.001)   # 19.287,5
    s = h["set"]
    assert s["fabric_unit_cost"] == 21000 and s["inputs"][0]["fabric_unit_cost"] == 21000
    assert s["outputs"][0]["panel_unit_cost_after"] == pn["after_baru"]
    assert "Dinilai ulang 27 Nov 2026" in s["value_note"]


def test_nilai_ulang_menolak_progres_banyak_kain_atau_hpp_lain():
    dua = _progres(inputs=[{"input_material_id": KAIN}, {"input_material_id": "kain-2"}])
    with pytest.raises(mod.Tolak):
        mod.nilai_ulang_progres(dua, KAIN, 19037.2915, 21000)
    with pytest.raises(mod.Tolak):
        mod.nilai_ulang_progres(_progres(), KAIN, 18000, 21000)


def test_tagihan_hanya_boleh_dihapus_saat_draf_belum_dibayar():
    draf = {"invoice_number": "AP-2611-0001", "status": "draft", "paid_amount": 0}
    assert mod.alasan_tolak_tagihan(draf, je_aktif=False) == ""
    assert "bukan draf" in mod.alasan_tolak_tagihan({**draf, "status": "sent"}, je_aktif=False)
    assert "dibayar" in mod.alasan_tolak_tagihan({**draf, "paid_amount": 5000}, je_aktif=False)
    assert "nota debit" in mod.alasan_tolak_tagihan({**draf, "debit_note_amount": 1}, je_aktif=False)
    assert "jurnal" in mod.alasan_tolak_tagihan(draf, je_aktif=True)


def test_penerimaan_dengan_roll_atau_karantina_ditolak():
    gr = {"receipt_number": "GR-00003", "items": [{"material_name": "RAYON"}]}
    assert mod.alasan_tolak_penerimaan(gr) == ""
    assert "roll" in mod.alasan_tolak_penerimaan({**gr, "rolls_created": ["RL-1"]})
    assert "karantina" in mod.alasan_tolak_penerimaan({**gr, "items": [{"material_name": "R", "quarantined_qty": 2}]})
    assert "selisih" in mod.alasan_tolak_penerimaan({**gr, "items": [{"material_name": "R", "wac_gap_je_number": "J"}]})
