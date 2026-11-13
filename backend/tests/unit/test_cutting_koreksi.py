"""Uji unit HERMETIK — UBAH ORDER CUTTING BERJALAN/SELESAI & KOREKSI CATATAN PROGRES (keputusan owner 14 Nov 2026:
"di cutting yang sedang berjalan, tolong bisa dilakukan EDIT karena tadi ada kesalahan penginputan"; "yang sudah
selesai juga bisa").

Angka harapan DIHITUNG TANGAN (kain K-01 Rp30.000/kg, stok 50 kg di Gudang A, gulungan R-0001 20 kg):
  * Catatan SALAH: diambil 20 kg → 93 pcs. Stok kain 50 → 30, R-0001 20 → 0 (habis), potongan 93 pcs,
    nilai 20 × 30.000 = 600.000 → HPP masuk 600.000 ÷ 93 = 6.451,61/pcs.
  * KOREKSI ke 15 kg → 50 pcs: stok kain +5 (30 → 35), potongan −43 (93 → 50), R-0001 dikembalikan 20 lalu dipakai 15
    (sisa 5), nilai baru 15 × 30.000 = 450.000 → 9.000/pcs; penerimaan lama di rata-rata bergerak DIGANTI (bukan
    dirata-rata dengan angka salah) → HPP potongan 9.000. Dokumen MI lama dibatalkan, pengganti 15 kg.
  * Bila 60 pcs sudah dikirim ke CMT (stok potongan tinggal 33): koreksi ke 50 (−43) DITOLAK sebelum apa pun bergerak;
    ke 60 (−33) boleh.
  * Order banyak baris (berkas test_cutting_banyak_hasil): K-01 24 → 20 kg, hasil 40/30/20 → 40/30/10 pcs:
    nilai baru 20 × 30.000 + 5 × 20.000 = 700.000 ÷ 80 pcs = 8.750/pcs untuk semua baris; stok K-01 26 → 30;
    gulungan R-0003 kembali utuh 25 (FIFO: R-0001 cukup untuk 20 kg).

Jalankan (serial):  cd backend && python -m pytest tests/unit/test_cutting_koreksi.py -n 0 -q
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

from test_tahap2_gudang import Req, _row  # noqa: E402
from test_cutting_banyak_hasil import (  # noqa: E402
    _db, _env, _mi_env, _multi_body, _progress_body, _roll, _order)


def run(coro):
    return asyncio.run(coro)


def _real_mi(monkeypatch):
    from core import cutting_material_issue as cmi
    real = cmi.doc_for_progress
    _mi_env(monkeypatch)
    return lambda: monkeypatch.setattr(cmi, "doc_for_progress", real)


@pytest.fixture
def salah(monkeypatch):
    """Order satu kain × satu hasil, catatan progres SALAH: 20 kg → 93 pcs (seharusnya 15 kg → 50 pcs)."""
    db = _db()
    restore = _real_mi(monkeypatch)
    cut = _env(monkeypatch, db)
    restore()
    o = run(cut.create_order(Req({"input_material_id": "M1", "location_id": "L1", "planned_input_qty": 15,
                                  "planned_output_qty": 50, "model_id": "MOD1", "variant_id": "V1",
                                  "roll_ids": ["R1"]})))
    run(cut.start_order(o["id"], Req()))
    run(cut.add_progress(o["id"], Req({"input_consumed": 20, "output_qty": 93, "roll_ids": ["R1"]})))
    pid = db.cutting_progress.docs[0]["id"]
    return db, cut, o["id"], pid


def _panel(db, pid="P1"):
    return next(m for m in db.rahaza_materials.docs if m["id"] == pid)


def _koreksi(**kw):
    return {"input_consumed": 15, "output_qty": 50, "roll_ids": ["R1"], "reason": "salah ketik 93, benar 50", **kw}


# ═════════════════════ 1 · koreksi angka: stok, gulungan, nilai, dokumen ═════════════════════
def test_catatan_salah_awal_sesuai_hitungan(salah):
    db, cut, oid, pid = salah
    assert _row(db, "M1", "L1")["qty"] == 30.0 and _row(db, "P1", "L1")["qty"] == 93.0
    assert _roll(db, "R1")["remaining_kg"] == 0.0 and _roll(db, "R1")["status"] == "fully_issued"
    assert abs(_panel(db)["unit_cost"] - 6451.6129) < 0.001


def test_koreksi_membalik_catatan_lama_lalu_menerapkan_angka_baru(salah):
    db, cut, oid, pid = salah
    out = run(cut.correct_progress(oid, pid, Req(_koreksi())))
    # stok bergerak sebesar SELISIH lewat stock_service (buku besar bertanda koreksi)
    assert _row(db, "M1", "L1")["qty"] == 35.0                         # 30 + 5 kg kembali
    assert _row(db, "P1", "L1")["qty"] == 50.0                         # 93 − 43 pcs
    from core import stock_service
    led = [(x["material_id"], x["delta"]) for x in db[stock_service.LEDGER].docs
           if (x.get("ref") or {}).get("type") == "cutting_correction"]
    assert sorted(led) == [("M1", 5.0), ("P1", -43.0)]
    # gulungan: pemakaian lama dikembalikan (20) lalu angka baru dipotong FIFO (15)
    r1 = _roll(db, "R1")
    assert r1["remaining_kg"] == 5.0 and r1["status"] == "partly_issued"
    moves = [(m["movement_type"], m["qty"]) for m in db.wh_fabric_roll_movements.docs if m["roll_id"] == "R1"]
    assert moves[-3:] == [("issue", 20.0), ("return", 20.0), ("issue", 15.0)]
    # nilai: penerimaan potongan lama DIGANTI, bukan dirata-rata dengan angka salah
    assert _panel(db)["unit_cost"] == 9000.0
    assert next(m for m in db.rahaza_materials.docs if m["id"] == "M1")["unit_cost"] == 30000.0
    prog = db.cutting_progress.docs[0]
    assert (prog["input_consumed"], prog["output_qty"], prog["value_out"], prog["cost_per_pcs_in"]) \
        == (15.0, 50.0, 450000.0, 9000.0)
    # jejak audit: siapa, kapan, alasan, angka lama
    c = prog["corrections"][0]
    assert c["reason"] == "salah ketik 93, benar 50" and c["before"]["output_qty"] == 93.0
    assert c["before"]["input_consumed"] == 20.0 and c["after"]["output_qty"] == 50.0 and c["by"]
    assert prog["correction_count"] == 1 and prog["corrected_by_name"] is not None
    assert prog["created_at"] and prog["id"] == pid                    # catatan yang SAMA, tidak dihapus
    # baris order
    o = _order(db, oid)
    assert o["produced_qty"] == 50.0 and o["consumed_input_qty"] == 15.0
    assert o["roll_ids"][0]["consumed_qty"] == 15.0 and o["roll_ids"][0]["remaining"] == 5.0
    assert "dikoreksi" in out["notice"] and "potongan" in out["notice"]


def test_koreksi_membatalkan_dokumen_mi_lama_dan_menerbitkan_pengganti(salah):
    db, cut, oid, pid = salah
    run(cut.correct_progress(oid, pid, Req(_koreksi())))
    old, new = db.rahaza_material_issues.docs
    assert old["mi_number"] == "MI-UJI-001" and old["status"] == "cancelled"
    assert "cutting_progress_id" not in old and old["voided_cutting_progress_id"] == pid
    assert "salah ketik" in old["cancel_reason"]
    assert new["cutting_progress_id"] == pid and new["status"] == "issued"
    assert new["items"][0]["qty_issued"] == 15.0 and new["replaces_mi_number"] == "MI-UJI-001"
    # kartu stok: keluar 20, batal (masuk) 20, keluar 15 → bersih 15
    cards = [(m["type"], m["qty"]) for m in db.rahaza_material_movements.docs if m["material_id"] == "M1"]
    assert cards == [("issue", 20.0), ("receive", 20.0), ("issue", 15.0)]
    prog = db.cutting_progress.docs[0]
    assert prog["material_issue_number"] == "MI-UJI-002"
    assert _order(db, oid)["material_issue_numbers"] == ["MI-UJI-002"] or \
        "MI-UJI-001" not in (_order(db, oid).get("material_issue_numbers") or [])


def test_alasan_wajib_dan_status_dibatalkan_ditolak(salah):
    db, cut, oid, pid = salah
    with pytest.raises(HTTPException) as e:
        run(cut.correct_progress(oid, pid, Req(_koreksi(reason=" "))))
    assert "Alasan koreksi wajib" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(cut.correct_progress(oid, "tidak-ada", Req(_koreksi())))
    assert e.value.status_code == 404
    assert _row(db, "P1", "L1")["qty"] == 93.0                         # tidak ada yang bergerak


# ═════════════════════ 2 · penjaga: potongan yang sudah keluar ke CMT tidak bisa ditarik ═════════════════════
def _kirim_cmt(db, qty):
    from core import stock_service
    run(stock_service.issue("P1", "L1", qty, ref={"type": "vendor_shipment"}, db=db))
    db.rahaza_material_issues.docs.append({
        "id": "mi-cmt", "mi_number": "MI-CMT-1", "source": "vendor_shipment", "status": "issued",
        "items": [{"material_id": "P1", "qty_issued": qty, "kind": "potongan"}]})


def test_koreksi_ditolak_bila_potongan_sudah_dikirim_ke_cmt_melebihi_angka_koreksi(salah):
    db, cut, oid, pid = salah
    _kirim_cmt(db, 60)                                                  # 93 − 60 = 33 pcs masih di gudang
    with pytest.raises(HTTPException) as e:
        run(cut.correct_progress(oid, pid, Req(_koreksi())))            # −43 > 33
    msg = e.value.detail
    assert "tinggal 33 pcs" in msg and "MI-CMT-1" in msg and "angka terkecil yang bisa dicatat untuk catatan ini 60 pcs" in msg
    # tidak ada yang bergerak
    assert _row(db, "M1", "L1")["qty"] == 30.0 and _row(db, "P1", "L1")["qty"] == 33.0
    assert _roll(db, "R1")["remaining_kg"] == 0.0
    assert db.cutting_progress.docs[0]["output_qty"] == 93.0 and not db.cutting_progress.docs[0].get("corrections")
    assert db.rahaza_material_issues.docs[0]["status"] == "issued"
    # sampai batas stok yang masih ada: boleh
    run(cut.correct_progress(oid, pid, Req(_koreksi(output_qty=60))))
    assert _row(db, "P1", "L1")["qty"] == 0.0 and _order(db, oid)["produced_qty"] == 60.0


# ═════════════════════ 3 · order Selesai juga bisa dikoreksi; kosongkan catatan ═════════════════════
def test_order_selesai_bisa_dikoreksi_dan_hpp_order_dihitung_ulang(salah):
    db, cut, oid, pid = salah
    done = run(cut.complete_order(oid, Req()))
    assert done["output_unit_cost"] == round(600000 / 93, 2)
    out = run(cut.correct_progress(oid, pid, Req(_koreksi())))
    assert out["status"] == "completed"
    assert out["output_unit_cost"] == 9000.0 and out["total_input_cost"] == 450000.0
    assert out["outputs"][0]["output_unit_cost"] == 9000.0
    with pytest.raises(HTTPException) as e:                             # order Selesai tidak boleh tanpa hasil
        run(cut.correct_progress(oid, pid, Req({"void": True, "reason": "catatan dobel"})))
    assert "Selesai" in e.value.detail


def test_kosongkan_catatan_mengembalikan_semua_lalu_order_boleh_dibatalkan(salah):
    db, cut, oid, pid = salah
    with pytest.raises(HTTPException):
        run(cut.cancel_order(oid, Req({"reason": "x"})))                # masih ada progres yang menggerakkan stok
    out = run(cut.correct_progress(oid, pid, Req({"void": True, "reason": "catatan dobel, belum dipotong"})))
    assert "dikosongkan" in out["notice"]
    assert _row(db, "M1", "L1")["qty"] == 50.0 and _row(db, "P1", "L1")["qty"] == 0.0
    assert _roll(db, "R1")["remaining_kg"] == 20.0 and _roll(db, "R1")["status"] == "in_stock"
    prog = db.cutting_progress.docs[0]
    assert prog["voided"] is True and prog["input_consumed"] == 0.0 and prog["output_qty"] == 0.0
    assert db.rahaza_material_issues.docs[0]["status"] == "cancelled" and len(db.rahaza_material_issues.docs) == 1
    assert prog["material_issue_id"] is None
    o = _order(db, oid)
    assert o["produced_qty"] == 0.0 and o["consumed_input_qty"] == 0.0
    from core import cutting_material_issue as cmi
    assert run(cmi.progress_without_doc(db))["count"] == 0              # catatan kosong tidak dituduh kurang dokumen
    assert run(cut.cancel_order(oid, Req({"reason": "salah order"})))["status"] == "cancelled"


def test_daftar_gulungan_koreksi_menampilkan_sisa_plus_pemakaian_catatan(salah):
    db, cut, oid, pid = salah
    plain = run(cut.list_rolls(Req(), material_id="M1", location_id="L1"))
    assert [r["roll_no"] for r in plain["items"]] == ["R-0003"]         # R-0001 habis dipakai catatan ini
    fix = run(cut.list_rolls(Req(), material_id="M1", location_id="L1", progress_id=pid))
    assert [(r["roll_no"], r["remaining"]) for r in fix["items"]] == [("R-0001", 20.0), ("R-0003", 25.0)]


# ═════════════════════ 4 · order banyak kain × banyak hasil ═════════════════════
def test_koreksi_order_banyak_baris_hpp_sama_semua_baris(monkeypatch):
    db = _db()
    restore = _real_mi(monkeypatch)
    cut = _env(monkeypatch, db)
    restore()
    o = run(cut.create_order(Req(_multi_body())))
    run(cut.start_order(o["id"], Req()))
    run(cut.add_progress(o["id"], Req(_progress_body())))
    pid = db.cutting_progress.docs[0]["id"]
    body = _progress_body()
    body["inputs"][0]["input_consumed"] = 20
    body["outputs"][2]["output_qty"] = 10
    body["reason"] = "kain K-01 salah timbang"
    run(cut.correct_progress(o["id"], pid, Req(body)))
    doc = _order(db, o["id"])
    panels = [x["output_material_id"] for x in doc["outputs"]]
    assert _row(db, "M1", "L1")["qty"] == 30.0 and _row(db, "M3", "L1")["qty"] == 25.0
    assert [_row(db, p, "L1")["qty"] for p in panels] == [40.0, 30.0, 10.0]
    assert (_roll(db, "R1")["remaining_kg"], _roll(db, "R3")["remaining_kg"], _roll(db, "R4")["remaining_kg"]) \
        == (0.0, 25.0, 10.0)
    assert _roll(db, "R3")["status"] == "in_stock"
    prog = db.cutting_progress.docs[0]
    assert prog["value_out"] == 700000.0 and prog["cost_per_pcs_in"] == 8750.0
    for p in panels:
        assert next(m for m in db.rahaza_materials.docs if m["id"] == p)["unit_cost"] == 8750.0
    assert [i["consumed_input_qty"] for i in doc["inputs"]] == [20.0, 5.0]
    assert [x["produced_qty"] for x in doc["outputs"]] == [40.0, 30.0, 10.0]
    assert {r["roll_id"]: r["consumed_qty"] for r in doc["inputs"][0]["roll_ids"]} == {"R1": 20.0, "R3": 0.0}
    d = run(cut.get_order(o["id"], Req()))
    assert d["hpp_summary"]["value_total"] == 700000.0 and d["hpp_summary"]["per_pcs"] == 8750.0


# ═════════════════════ 5 · ubah isian kepala order berjalan / selesai ═════════════════════
def _partial(monkeypatch):
    db = _db()
    cut = _env(monkeypatch, db)
    o = run(cut.create_order(Req(_multi_body())))
    run(cut.start_order(o["id"], Req()))
    run(cut.add_progress(o["id"], Req({
        "inputs": [{"line_id": "in-2", "input_consumed": 3, "roll_ids": ["R4"]}],
        "outputs": [{"line_id": "out-1", "output_qty": 10, "roll_ids": ["R4"]}]})))
    return db, cut, o["id"]


def _lines_body(o):
    return {"inputs": [{"line_id": i["line_id"], "input_material_id": i["input_material_id"],
                        "planned_input_qty": i["planned_input_qty"],
                        "roll_ids": [r["roll_id"] for r in i["roll_ids"]]} for i in o["inputs"]],
            "outputs": [{"line_id": x["line_id"], "model_id": x["model_id"], "variant_id": x["variant_id"],
                         "size_id": x["size_id"], "po_item_id": x.get("po_item_id") or "",
                         "planned_output_qty": x["planned_output_qty"], "roll_ids": x.get("roll_ids") or []}
                        for x in o["outputs"]]}


def test_ubah_order_berjalan_target_catatan_dan_baris_yang_belum_dipotong(monkeypatch):
    db, cut, oid = _partial(monkeypatch)
    o = run(cut.get_order(oid, Req()))
    p3 = o["outputs"][2]["output_material_id"]
    body = _lines_body(o)
    body["outputs"][0]["planned_output_qty"] = 45                      # sudah dipotong: target boleh diganti
    body["outputs"][1]["planned_output_qty"] = 25                      # belum dipotong
    body["outputs"] = body["outputs"][:2]                              # baris 3 belum dipotong → boleh dihapus
    body["inputs"][0]["planned_input_qty"] = 35
    body["notes"] = "target dikoreksi owner"
    out = run(cut.update_order(oid, Req(body)))
    assert out["status"] == "in_progress" and out["notes"] == "target dikoreksi owner"
    assert [x["planned_output_qty"] for x in out["outputs"]] == [45.0, 25.0]
    assert [x["produced_qty"] for x in out["outputs"]] == [10.0, 0.0]          # angka potong tidak tersentuh
    assert [x["line_id"] for x in out["outputs"]] == ["out-1", "out-2"]
    assert [i["line_id"] for i in out["inputs"]] == ["in-1", "in-2"]
    assert out["inputs"][0]["planned_input_qty"] == 35.0 and out["inputs"][1]["consumed_input_qty"] == 3.0
    assert not any(m["id"] == p3 for m in db.rahaza_materials.docs)          # master potongan belum bergerak → dibuang
    assert "dibersihkan" in out.get("notice", "")


def test_ubah_order_berjalan_menolak_yang_sudah_dipotong(monkeypatch):
    db, cut, oid = _partial(monkeypatch)
    o = run(cut.get_order(oid, Req()))
    body = _lines_body(o)
    body["outputs"][0].update({"model_id": "MOD2", "variant_id": "V2"})     # out-1 sudah 10 pcs
    with pytest.raises(HTTPException) as e:
        run(cut.update_order(oid, Req(body)))
    assert "sudah dipotong 10 pcs" in e.value.detail and "Koreksi" in e.value.detail
    body = _lines_body(o)
    body["outputs"] = body["outputs"][1:]                                    # hapus out-1 yang sudah dipotong
    with pytest.raises(HTTPException) as e:
        run(cut.update_order(oid, Req(body)))
    assert "tidak bisa dihapus" in e.value.detail
    body = _lines_body(o)
    body["inputs"][1]["input_material_id"] = "M1"                            # kain K-02 sudah dipotong 3 kg
    body["inputs"] = body["inputs"][1:]
    with pytest.raises(HTTPException) as e:
        run(cut.update_order(oid, Req(body)))
    assert "sudah dipotong" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(cut.update_order(oid, Req({"location_id": "L2"})))
    assert "Gudang sumber kain tidak bisa diganti" in e.value.detail
    assert _order(db, oid)["outputs"][0]["model_id"] == "MOD1"               # tidak ada yang tertulis


def test_ubah_order_selesai_dan_order_batal_ditolak(salah):
    db, cut, oid, pid = salah
    run(cut.complete_order(oid, Req()))
    out = run(cut.update_order(oid, Req({"notes": "diperiksa owner", "planned_output_qty": 55})))
    assert out["status"] == "completed" and out["notes"] == "diperiksa owner" and out["planned_output_qty"] == 55.0
    assert out["produced_qty"] == 93.0
    o2 = run(cut.create_order(Req({"input_material_id": "M1", "location_id": "L1", "planned_input_qty": 5,
                                   "planned_output_qty": 10, "model_id": "MOD1", "variant_id": "V1"})))
    db.cutting_orders.docs[-1]["status"] = "cancelled"
    with pytest.raises(HTTPException) as e:
        run(cut.update_order(o2["id"], Req({"notes": "x"})))
    assert "dibatalkan" in e.value.detail


# ═════════════════════ 6 · rumus murni & hak akses ═════════════════════
def test_rata_rata_bergerak_ganti_penerimaan_lama():
    from core.accessory_valuation import replaced_average
    assert replaced_average(93, 6451.6129, 93, 6451.612903, 50, 9000) == (9000.0, False)
    # stok lain 100 pcs @ 10.000 + catatan 20 @ 12.000 → koreksi 10 @ 12.000: (1.000.000 + 240.000 − 240.000 + 120.000) ÷ 110
    assert replaced_average(120, (1000000 + 240000) / 120, 20, 12000, 10, 12000) == (round(1120000 / 110, 4), False)
    assert replaced_average(20, 9000, 20, 9000, 0, 0) == (9000.0, False)        # stok habis → HPP lama dipertahankan
    assert replaced_average(30, 1000, 20, 5000, 20, 0)[1] is True              # nilai negatif dipotong & dilaporkan


def test_hak_koreksi_dan_ubah_mengikuti_centang_order_cutting_ubah():
    from data import module_catalog as mc
    assert mc.request_key("PUT", "/api/cutting/orders/o1/progress/p1") == "mod.cut_orders.edit"
    assert mc.request_key("PUT", "/api/cutting/orders/o1") == "mod.cut_orders.edit"
