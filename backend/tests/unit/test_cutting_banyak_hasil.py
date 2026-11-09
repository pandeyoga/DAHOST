"""Uji unit HERMETIK — ORDER CUTTING BANYAK KAIN × BANYAK GULUNGAN × BANYAK HASIL (keputusan owner 10 Nov 2026).

Angka harapan DIHITUNG TANGAN:
  * Order: kain K-01 (Rp30.000/kg, stok 50 kg, gulungan R-0001 20 kg + R-0003 25 kg) dan K-02 (Rp20.000/kg,
    stok 30 kg, gulungan R-0004 15 kg) → 3 baris hasil beda model: MDL Merah M 40 pcs (gulungan R-0001),
    MD2 Merah M 30 pcs (R-0003), MD3 Biru L 20 pcs (R-0003 + R-0004).
  * Progres: K-01 diambil 24 kg; K-02 diambil 6 kg, sisa 1 kg kembali → terpakai 24 kg + 5 kg.
    Stok K-01 50 → 26, K-02 30 → 25. Gulungan FIFO: R-0001 20 → 0, R-0003 25 → 21, R-0004 15 → 10.
    Stok potongan: 40 / 30 / 20 pcs.
  * HPP potongan per pcs = (24 × 30.000 + 5 × 20.000) ÷ (40 + 30 + 20) = 820.000 ÷ 90 = 9.111,11 — SAMA di 3 baris.
  * Kain untuk PO (baris 1 tertaut PO1): 40/90 pcs → K-01 24 × 40/90 = 10,6667 kg; K-02 5 × 40/90 = 2,2222 kg.
  * Order LAMA satu baris (field tingkat atas): diambil 10, sisa 2, limbah 500 gram → stok 50 → 42, gulungan
    20 → 12, nilai 8 × 30.000 = 240.000 → HPP 240.000 ÷ 20 = 12.000/pcs (rumus lama = rumus baru).

Jalankan (serial):  cd backend && python -m pytest tests/unit/test_cutting_banyak_hasil.py -n 0 -q
"""
import asyncio
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

# Mongo palsu ber-pipeline milik paket Gudang Tahap 2 (stock_service butuh update ber-pipeline & `$expr`).
from test_tahap2_gudang import Req, _cut_db, _cut_env, _noop, _row  # noqa: E402
from core import cutting_lines  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _db():
    db = _cut_db()
    db.rahaza_materials.docs.append({"id": "M3", "code": "K-02", "name": "Kain Rib", "type": "fabric", "unit": "kg",
                                     "unit_cost": 20000.0, "active": True})
    from core import stock_service
    db[stock_service.STOCK].docs.append({"id": "s3", "material_id": "M3", "location_id": "L1", "qty": 30.0})
    db.wh_fabric_rolls.docs += [
        {"id": "R3", "roll_no": "R-0003", "material_id": "M1", "uom": "kg", "weight_kg": 25.0, "remaining_kg": 25.0,
         "status": "in_stock", "location_id": "L1", "location_name": "Gudang A", "color_lot": "LOT-A2"},
        {"id": "R4", "roll_no": "R-0004", "material_id": "M3", "uom": "kg", "weight_kg": 15.0, "remaining_kg": 15.0,
         "status": "in_stock", "location_id": "L1", "location_name": "Gudang A", "color_lot": "LOT-B1"}]
    db.wh_fabric_rolls.docs[0]["color_lot"] = "LOT-A1"
    db.rahaza_models.docs.append({"id": "MOD3", "code": "MD3", "name": "Model 3", "active": True})
    db.rahaza_sizes.docs.append({"id": "S2", "code": "L"})
    db.rahaza_model_variants.docs += [
        {"id": "V2", "model_id": "MOD2", "size_id": "S1", "size_code": "M", "color_name": "Merah",
         "color_code": "RED", "sku": "MD2-RED-M"},
        {"id": "V3", "model_id": "MOD3", "size_id": "S2", "size_code": "L", "color_name": "Biru",
         "color_code": "BLU", "sku": "MD3-BLU-L"}]
    return db


def _env(monkeypatch, db):
    cut = _cut_env(monkeypatch, db)

    async def boms(db_, model_id, size_id, color=None):
        panel = {"MOD1": "P1", "MOD2": "P2"}.get(model_id)       # MD3 belum punya potongan → lahir saat mulai
        return {"materials": [{"material_id": panel, "is_cut_panel": True}]} if panel else None
    monkeypatch.setattr(cut.product_costing, "find_active_bom", boms)
    return cut


def _multi_body():
    return {"location_id": "L1", "notes": "potong campur",
            "inputs": [{"input_material_id": "M1", "planned_input_qty": 30, "roll_ids": ["R1", "R3"]},
                       {"input_material_id": "M3", "planned_input_qty": 10, "roll_ids": ["R-0004"]}],
            "outputs": [{"model_id": "MOD1", "variant_id": "V1", "planned_output_qty": 40, "roll_ids": ["R1"]},
                        {"model_id": "MOD2", "variant_id": "V2", "planned_output_qty": 30, "roll_ids": ["R3"]},
                        {"model_id": "MOD3", "variant_id": "V3", "planned_output_qty": 20,
                         "roll_ids": ["R3", "R4"]}]}


def _progress_body():
    return {"inputs": [{"line_id": "in-1", "input_consumed": 24, "roll_ids": ["R1", "R3"]},
                       {"line_id": "in-2", "input_consumed": 6, "leftover_qty": 1, "roll_ids": ["R4"]}],
            "outputs": [{"line_id": "out-1", "output_qty": 40}, {"line_id": "out-2", "output_qty": 30},
                        {"line_id": "out-3", "output_qty": 20}],
            "note": "shift pagi"}


def _roll(db, rid):
    return next(r for r in db.wh_fabric_rolls.docs if r["id"] == rid)


def _order(db, oid):
    return next(o for o in db.cutting_orders.docs if o["id"] == oid)


def _mi_env(monkeypatch):
    """Dokumen Pengeluaran Material yang ASLI (bukan noop) dengan penomoran & pengayaan palsu."""
    import routes.rahaza_inventory_shared as ris
    seq = {"n": 0}

    async def num(db_, requested="", *, sistem=False):
        seq["n"] += 1
        return f"MI-UJI-{seq['n']:03d}"
    monkeypatch.setattr(ris, "_gen_mi_number", num)
    monkeypatch.setattr(ris, "_enrich_mi", _noop())


@pytest.fixture
def multi(monkeypatch):
    """Order 2 kain × 3 gulungan × 3 hasil yang SUDAH dimulai dan dilapor progres sekali."""
    db = _db()
    from core import cutting_material_issue as cmi
    real_doc = cmi.doc_for_progress
    cut = _env(monkeypatch, db)
    _mi_env(monkeypatch)
    monkeypatch.setattr(cmi, "doc_for_progress", real_doc)
    o = run(cut.create_order(Req(_multi_body())))
    run(cut.start_order(o["id"], Req()))
    res = run(cut.add_progress(o["id"], Req(_progress_body())))
    return db, cut, o["id"], res


# ═════════════════════ 1 · model data: inputs[] + outputs[] + field lama ═════════════════════
def test_buat_order_banyak_kain_banyak_hasil_menyimpan_baris_dan_tautan_gulungan(monkeypatch):
    db = _db()
    cut = _env(monkeypatch, db)
    o = run(cut.create_order(Req(_multi_body())))
    assert [i["input_material_id"] for i in o["inputs"]] == ["M1", "M3"]
    assert [r["roll_id"] for r in o["inputs"][0]["roll_ids"]] == ["R1", "R3"]
    assert [r["roll_id"] for r in o["inputs"][1]["roll_ids"]] == ["R4"]          # dipilih lewat nomor roll
    assert [x["model_id"] for x in o["outputs"]] == ["MOD1", "MOD2", "MOD3"]
    assert [x["roll_ids"] for x in o["outputs"]] == [["R1"], ["R3"], ["R3", "R4"]]   # tautan tersimpan
    assert [x["output_material_id"] for x in o["outputs"]][:2] == ["P1", "P2"]
    # field lama tingkat atas: satuan sama → jumlah; id beda → kosong (bukan baris pertama yang menyesatkan)
    assert o["input_material_id"] == "" and o["input_unit"] == "kg" and o["planned_input_qty"] == 40.0
    assert o["planned_output_qty"] == 90.0 and o["model_id"] == "" and o["multi"] is True
    assert o["style_name"] == "Model 1, Model 2, Model 3"
    assert o["unit_totals"] == [{"unit": "kg", "planned": 40.0, "consumed": 0.0, "waste": 0.0}]
    usage = {u["roll_no"]: [x["label"] for x in u["outputs"]] for u in o["roll_usage"]}
    assert usage == {"R-0001": ["Model 1 · Merah · M · MDL-RED-M"],
                     "R-0003": ["Model 2 · Merah · M · MD2-RED-M", "Model 3 · Biru · L · MD3-BLU-L"],
                     "R-0004": ["Model 3 · Biru · L · MD3-BLU-L"]}


def test_validasi_baris_kain_dan_hasil(monkeypatch):
    db = _db()
    cut = _env(monkeypatch, db)
    body = _multi_body()
    body["inputs"][1]["input_material_id"] = "M1"
    with pytest.raises(HTTPException) as e:
        run(cut.create_order(Req(body)))
    assert "dipilih dua kali" in e.value.detail
    body = _multi_body()
    body["outputs"][2]["roll_ids"] = ["R2"]                           # gulungan yang tidak dipilih di baris kain
    with pytest.raises(HTTPException) as e:
        run(cut.create_order(Req(body)))
    assert e.value.detail.startswith("Hasil baris 3: ") and "R2" in e.value.detail
    body = _multi_body()
    body["outputs"][1] = dict(body["outputs"][0])                      # hasil kembar
    with pytest.raises(HTTPException) as e:
        run(cut.create_order(Req(body)))
    assert "sudah ada di baris lain" in e.value.detail
    body = _multi_body()
    body["outputs"][1].pop("variant_id")
    with pytest.raises(HTTPException) as e:
        run(cut.create_order(Req(body)))
    assert e.value.detail.startswith("Hasil baris 2: Ukuran wajib")
    body = _multi_body()
    body["inputs"][1]["roll_ids"] = ["R2"]                             # gulungan K-01 di gudang lain, bukan K-02
    with pytest.raises(HTTPException) as e:
        run(cut.create_order(Req(body)))
    assert e.value.detail.startswith("Kain baris 2: Gulungan R2 bukan milik kain K-02")


# ═════════════════════ 2 · mulai → master potongan per hasil; progres → stok, gulungan, HPP ═════════════════════
def test_progres_memotong_tiap_kain_sekali_mengurangi_gulungan_dan_menambah_stok_tiap_hasil(multi):
    db, cut, oid, res = multi
    o = _order(db, oid)
    assert o["status"] == "in_progress"
    panels = [x["output_material_id"] for x in o["outputs"]]
    assert panels[:2] == ["P1", "P2"] and panels[2] and len(set(panels)) == 3
    p3 = next(m for m in db.rahaza_materials.docs if m["id"] == panels[2])
    assert p3["is_cut_panel"] and p3["model_id"] == "MOD3" and p3["code"].startswith("CUT-MD3")
    assert p3["source_material_id"] == "M1"                    # gulungan pertama hasil ini (R-0003) = kain K-01
    # stok kain dipotong SEKALI per kain (terpakai = diambil − sisa)
    assert _row(db, "M1", "L1")["qty"] == 26.0 and _row(db, "M3", "L1")["qty"] == 25.0
    # gulungan FIFO per kain
    assert (_roll(db, "R1")["remaining_kg"], _roll(db, "R3")["remaining_kg"], _roll(db, "R4")["remaining_kg"]) \
        == (0.0, 21.0, 10.0)
    assert _roll(db, "R2")["remaining_kg"] == 30.0               # gudang lain tidak tersentuh
    # stok potongan per hasil
    assert [_row(db, pid, "L1")["qty"] for pid in panels] == [40.0, 30.0, 20.0]
    # akumulasi per baris + total
    assert [i["consumed_input_qty"] for i in o["inputs"]] == [24.0, 5.0]
    assert o["inputs"][1]["leftover_qty"] == 1.0
    assert [x["produced_qty"] for x in o["outputs"]] == [40.0, 30.0, 20.0] and o["produced_qty"] == 90.0
    assert o["consumed_input_qty"] == 29.0 and o["unit_totals"][0]["consumed"] == 29.0
    # jejak per gulungan di baris kain
    assert {r["roll_id"]: r["consumed_qty"] for r in o["inputs"][0]["roll_ids"]} == {"R1": 20.0, "R3": 4.0}
    assert {r["roll_id"]: r["consumed_qty"] for r in o["inputs"][1]["roll_ids"]} == {"R4": 5.0}


def test_hpp_per_pcs_sama_untuk_semua_baris_total_biaya_dibagi_total_pcs(multi):
    db, cut, oid, res = multi
    prog = db.cutting_progress.docs[0]
    assert prog["value_out"] == 820000.0                                  # 24 × 30.000 + 5 × 20.000
    assert prog["cost_per_pcs_in"] == round(820000 / 90, 6)
    assert [x["value_out"] for x in prog["inputs"]] == [720000.0, 100000.0]
    assert [x["output_qty"] for x in prog["outputs"]] == [40.0, 30.0, 20.0]
    after = [x["panel_unit_cost_after"] for x in prog["outputs"]]
    assert all(abs(a - 9111.11) < 0.01 for a in after), after         # stok lama 0 ⇒ HPP = HPP masuk
    done = run(cut.complete_order(oid, Req()))
    assert done["status"] == "completed" and done["output_unit_cost"] == 9111.11
    assert done["total_input_cost"] == 820000.0 and done["value_source"] == "progress_trace"
    assert [x["output_unit_cost"] for x in done["outputs"]] == [9111.11] * 3
    assert cutting_lines.cost_per_pcs(820000, 90) == 9111.11


def test_dokumen_pengeluaran_material_satu_baris_per_kain(multi):
    db, cut, oid, res = multi
    assert res["last_progress"]["material_issue_number"] == "MI-UJI-001"
    mi = db.rahaza_material_issues.docs[0]
    assert [(it["material_id"], it["qty_issued"]) for it in mi["items"]] == [("M1", 24.0), ("M3", 5.0)]
    assert "R-0001" in mi["items"][0]["notes"] and "R-0004" in mi["items"][1]["notes"]
    cards = [(m["material_id"], m["qty"]) for m in db.rahaza_material_movements.docs]
    assert cards == [("M1", 24.0), ("M3", 5.0)]


def test_tautan_gulungan_ke_hasil_tampil_di_rincian_dan_endpoint_gulungan(multi):
    db, cut, oid, res = multi
    d = run(cut.get_order(oid, Req()))
    usage = {u["roll_no"]: [(x["label"].split(" · ")[0], x["produced_qty"]) for x in u["outputs"]]
             for u in d["roll_usage"]}
    assert usage == {"R-0001": [("Model 1", 40.0)], "R-0003": [("Model 2", 30.0), ("Model 3", 20.0)],
                     "R-0004": [("Model 3", 20.0)]}
    lots = {u["roll_no"]: u["color_lot"] for u in d["roll_usage"]}
    assert lots == {"R-0001": "LOT-A1", "R-0003": "LOT-A2", "R-0004": "LOT-B1"}
    assert d["hpp_summary"]["value_total"] == 820000.0 and d["hpp_summary"]["per_pcs"] == 9111.11
    assert [x["output_stock"] for x in d["outputs"]] == [40.0, 30.0, 20.0]
    r3 = run(cut.roll_usage("R3", Req()))
    assert r3["total"] == 1 and "Model 2 · Merah · M · MD2-RED-M (30 pcs)" in r3["dipakai_untuk"]
    assert "Model 3 · Biru · L · MD3-BLU-L (20 pcs)" in r3["dipakai_untuk"]
    # catatan gerak gulungan menyebut hasil yang memakainya
    notes = [m["notes"] for m in db.wh_fabric_roll_movements.docs if m["roll_id"] == "R4"]
    assert notes and "Model 3" in notes[0] and "Model 1" not in notes[0]


def test_progres_menolak_sebelum_stok_bergerak(monkeypatch):
    db = _db()
    cut = _env(monkeypatch, db)
    o = run(cut.create_order(Req(_multi_body())))
    run(cut.start_order(o["id"], Req()))
    with pytest.raises(HTTPException) as e:                           # body lama untuk order banyak kain
        run(cut.add_progress(o["id"], Req({"input_consumed": 5, "output_qty": 5, "roll_ids": ["R1"]})))
    assert "beberapa kain" in e.value.detail
    body = _progress_body()
    body["inputs"][1]["roll_ids"] = []                                 # K-02 dilacak per gulungan → wajib
    with pytest.raises(HTTPException) as e:
        run(cut.add_progress(o["id"], Req(body)))
    assert "Pilih gulungan" in e.value.detail and "K-02" in e.value.detail
    body = _progress_body()
    body["outputs"][0]["roll_ids"] = ["R2"]
    with pytest.raises(HTTPException) as e:
        run(cut.add_progress(o["id"], Req(body)))
    assert "R2" in e.value.detail
    assert _row(db, "M1", "L1")["qty"] == 50.0 and _row(db, "M3", "L1")["qty"] == 30.0
    assert _roll(db, "R1")["remaining_kg"] == 20.0 and not db.cutting_progress.docs


def test_progres_sebagian_kain_dan_sebagian_hasil(monkeypatch):
    """Satu progres boleh hanya memakai satu kain & menghasilkan sebagian baris; tautan baru tercatat."""
    db = _db()
    cut = _env(monkeypatch, db)
    o = run(cut.create_order(Req(_multi_body())))
    run(cut.start_order(o["id"], Req()))
    run(cut.add_progress(o["id"], Req({
        "inputs": [{"line_id": "in-2", "input_consumed": 3, "roll_ids": ["R4"]}],
        "outputs": [{"line_id": "out-1", "output_qty": 10, "roll_ids": ["R4"]}]})))
    doc = _order(db, o["id"])
    assert _row(db, "M1", "L1")["qty"] == 50.0 and _row(db, "M3", "L1")["qty"] == 27.0
    assert [x["produced_qty"] for x in doc["outputs"]] == [10.0, 0.0, 0.0]
    assert doc["outputs"][0]["roll_ids"] == ["R1", "R4"]                # tautan dari progres ikut tersimpan
    prog = db.cutting_progress.docs[0]
    assert prog["value_out"] == 60000.0 and prog["cost_per_pcs_in"] == 6000.0


# ═════════════════════ 3 · order LAMA satu baris tetap jalan, angkanya sama ═════════════════════
def test_order_lama_satu_baris_tetap_jalan_dan_angka_sama_dengan_rumus_lama(monkeypatch):
    db = _db()
    cut = _env(monkeypatch, db)
    assert "inputs" not in _order(db, "O1")                           # dokumen lama: tidak dimigrasi paksa
    view = run(cut.get_order("O1", Req()))
    assert [i["input_material_id"] for i in view["inputs"]] == ["M1"]
    assert [x["output_material_id"] for x in view["outputs"]] == ["P1"]
    run(cut.add_progress("O1", Req({"input_consumed": 10, "output_qty": 20, "leftover_qty": 2,
                                    "waste_qty": 500, "waste_uom": "gram", "roll_ids": ["R1"]})))
    assert _row(db, "M1", "L1")["qty"] == 42.0 and _roll(db, "R1")["remaining_kg"] == 12.0
    prog = db.cutting_progress.docs[0]
    assert (prog["input_taken"], prog["leftover_qty"], prog["input_consumed"], prog["waste_qty"]) == (10.0, 2.0, 8.0, 0.5)
    assert prog["value_out"] == 240000.0 and prog["cost_per_pcs_in"] == 12000.0
    assert prog["panel_unit_cost_after"] == 12000.0 and prog["fabric_unit_cost"] == 30000.0
    doc = _order(db, "O1")
    # field lama tetap terisi persis seperti dulu
    assert (doc["input_material_id"], doc["output_material_id"], doc["consumed_input_qty"], doc["produced_qty"],
            doc["waste_qty"], doc["leftover_qty"]) == ("M1", "P1", 8.0, 20.0, 0.5, 2.0)
    assert doc["roll_ids"][0]["roll_id"] == "R1" and doc["roll_ids"][0]["consumed_qty"] == 8.0
    done = run(cut.complete_order("O1", Req()))
    old_formula = round(240000.0 / 20.0, 2)                            # total biaya kain ÷ pcs (rumus lama)
    assert done["output_unit_cost"] == old_formula == 12000.0


def test_order_baru_satu_baris_lewat_body_lama_sama_dengan_dulu(monkeypatch):
    db = _db()
    cut = _env(monkeypatch, db)
    o = run(cut.create_order(Req({"input_material_id": "M1", "location_id": "L1", "planned_input_qty": 5,
                                  "planned_output_qty": 10, "model_id": "MOD1", "variant_id": "V1",
                                  "roll_ids": ["R1"]})))
    assert (o["input_material_id"], o["output_material_id"], o["size_id"], o["output_size"]) == ("M1", "P1", "S1", "M")
    assert o["planned_input_qty"] == 5.0 and o["planned_output_qty"] == 10.0 and o["multi"] is False
    assert o["roll_ids"][0]["roll_id"] == "R1" and o["outputs"][0]["roll_ids"] == ["R1"]   # satu hasil = semua gulungan
    run(cut.start_order(o["id"], Req()))
    run(cut.add_progress(o["id"], Req({"input_consumed": 4, "output_qty": 10, "roll_ids": ["R1"]})))
    prog = db.cutting_progress.docs[0]
    assert prog["value_out"] == 120000.0 and prog["cost_per_pcs_in"] == 12000.0
    upd_db = _order(db, o["id"])
    assert upd_db["produced_qty"] == 10.0 and upd_db["consumed_input_qty"] == 4.0


# ═════════════════════ 4 · pembaca hilir melihat SEMUA hasil ═════════════════════
def test_pembaca_hilir_melihat_semua_hasil(multi, monkeypatch):
    db, cut, oid, res = multi
    from core import cut_panel_health, cut_panel_master, kirim_cmt, stock_service
    o = _order(db, oid)
    for x in o["outputs"]:
        panel = next(m for m in db.rahaza_materials.docs if m["id"] == x["output_material_id"])
        # Kirim ke CMT mengenali hasil cutting sebagai POTONGAN dan membaca stok + HPP-nya dari master
        assert kirim_cmt.kind_of(panel) == kirim_cmt.KIND_POTONGAN
        assert cut_panel_master.is_panel_material(panel)
        assert run(stock_service.get_onhand(panel["id"], db=db)) == x["produced_qty"]
        assert abs(float(panel["unit_cost"]) - 9111.11) < 0.01
        # kesehatan potongan: order banyak hasil tetap dihitung sebagai pemilik (bukan yatim)
        row = run(cut_panel_health.inspect(db, panel))
        lama = 1 if panel["id"] == "P1" else 0                        # order lama O1 juga menunjuk P1
        assert row["orders_referencing"] == 1 + lama and "order_missing" not in row["reasons"]
    # kebutuhan material PO: kain dibagi menurut pcs hasil yang tertaut PO
    o["outputs"][0]["po_id"] = "PO1"
    assert cutting_lines.fabric_used_for_po(o, "PO1") == {"M1": round(24 * 40 / 90, 4), "M3": round(5 * 40 / 90, 4)}
    assert cutting_lines.fabric_used_for_po(o, "PO-LAIN") == {}
    # pemakaian master (hapus model/warna/ukuran/kain/potongan) menemukan order lewat barisnya
    from core import cutting_material_issue as cmi
    for q in ({"$or": [{"model_id": "MOD3"}, {"outputs.model_id": "MOD3"}]},
              {"$or": [{"size_id": "S2"}, {"outputs.size_id": "S2"}]},
              {"$or": [{"input_material_id": "M3"}, {"inputs.input_material_id": "M3"}]},
              {"$or": [{"output_material_id": o["outputs"][2]["output_material_id"]},
                       {"outputs.output_material_id": o["outputs"][2]["output_material_id"]}]}):
        assert run(db[cmi.ORDERS].count_documents(q)) == 1, q


def test_batal_membersihkan_semua_master_potongan_yang_belum_bergerak(monkeypatch):
    db = _db()
    cut = _env(monkeypatch, db)
    o = run(cut.create_order(Req(_multi_body())))
    run(cut.start_order(o["id"], Req()))
    p3 = _order(db, o["id"])["outputs"][2]["output_material_id"]
    out = run(cut.cancel_order(o["id"], Req({"reason": "uji"})))
    assert out["status"] == "cancelled"
    assert not any(m["id"] == p3 for m in db.rahaza_materials.docs)      # lahir dari order ini, belum bergerak
    assert any(m["id"] == "P1" for m in db.rahaza_materials.docs)        # milik BOM — tidak ikut dibuang
    assert _order(db, o["id"])["outputs"][2]["output_material_id"] == ""


def test_ubah_draf_lewat_daftar_baris(monkeypatch):
    db = _db()
    cut = _env(monkeypatch, db)
    o = run(cut.create_order(Req(_multi_body())))
    body = _multi_body()
    body["inputs"] = body["inputs"][:1]                                # kain K-02 dibuang
    body["outputs"] = [dict(body["outputs"][0], roll_ids=["R1"]), dict(body["outputs"][1], roll_ids=["R3"])]
    upd = run(cut.update_order(o["id"], Req({"inputs": body["inputs"], "outputs": body["outputs"]})))
    assert [i["input_material_id"] for i in upd["inputs"]] == ["M1"] and upd["input_material_id"] == "M1"
    assert [x["model_id"] for x in upd["outputs"]] == ["MOD1", "MOD2"] and upd["planned_output_qty"] == 70.0
    with pytest.raises(HTTPException) as e:                           # kunci lama ambigu untuk banyak hasil
        run(cut.update_order(o["id"], Req({"model_id": "MOD3"})))
    assert "beberapa baris hasil" in e.value.detail


def test_dashboard_kain_per_satuan_tidak_dobel():
    from routes.cutting import summarize_cutting_units
    rows = [{"_id": "kg", "n": 2, "produced": 120, "consumed": 30, "waste": 1},
            {"_id": "m", "n": 1, "produced": 20, "consumed": 10, "waste": 0}]   # order kg+m dihitung di dua satuan
    s = summarize_cutting_units(rows, totals={"planned": 150, "produced": 120})
    assert s["produced"] == 120 and s["planned_output"] == 150                  # total pcs tidak dobel
    assert {u["unit"]: u["yield"] for u in s["by_unit"]} == {"kg": 4.0, "m": 2.0}
    assert cutting_lines.unit_totals([{"input_unit": "KG", "consumed_input_qty": 2},
                                      {"input_unit": "m", "consumed_input_qty": 3},
                                      {"input_unit": "kg", "consumed_input_qty": 1}]) == [
        {"unit": "kg", "planned": 0.0, "consumed": 3.0, "waste": 0.0},
        {"unit": "m", "planned": 0.0, "consumed": 3.0, "waste": 0.0}]


# ═════════════════════ 5 · layar: struktur baru + tautan gulungan → hasil ═════════════════════
def _fe(rel):
    return open(os.path.join(ROOT, "frontend", "src", "components", "erp", "cutting", rel), encoding="utf-8").read()


def test_sumber_layar_form_banyak_kain_banyak_hasil():
    form = _fe("CuttingOrderForm.jsx")
    for frag in ("Kain & gulungan", "Hasil potongan", "Tambah kain", "Tambah baris", "Gulungan dipakai",
                 "cutting-input-row-", "cutting-output-row-", "cutting-add-input", "cutting-add-output",
                 "cutting-output-rolls-", "cutting-hpp-estimate", "inputs:", "outputs:", "roll_ids",
                 "FormPopup", "SmartNativeSelect", "Checkbox", "Isian", "EmptyState"):
        assert frag in form, frag
    assert "/api/rahaza/models/${id}/variants" in form and "d?.variants" in form
    prog = _fe("CuttingProgressForm.jsx")
    for frag in ("inputs:", "outputs:", "line_id", "cutting-progress-input-", "cutting-progress-output-",
                 "Gulungan dipakai", "cutting-progress-roll-matrix", "previewAllocation"):
        assert frag in prog, frag
    mod = _fe("CuttingOrdersModule.jsx")
    for frag in ("CuttingOrderForm", "CuttingProgressForm", "roll_usage", "cutting-roll-output-matrix",
                 "Dipakai untuk", "cutting-detail-inputs", "cutting-detail-outputs", "hpp_summary",
                 "cutting-edit-btn"):
        assert frag in mod, frag
    # aturan layar: tanpa <button>/<select>/<table> mentah, tanpa window.confirm
    for src in (form, prog, mod):
        assert not re.search(r"<(button|select|table)[\s>]", src)
        assert "window.confirm" not in src
