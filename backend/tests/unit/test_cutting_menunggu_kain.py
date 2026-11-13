"""Uji unit HERMETIK — REQUEST CUTTING SAAT KAIN BELUM ADA ("Menunggu kain") + PENYARING DAFTAR (keputusan owner
14 Nov 2026: "jika cutting request namun kain belum ada maka bisa request pending jadi tetap bisa dilakukan namun
pending. dan tolong tambahkan seperti filter dll agar mempermudah").

Aturan yang diuji:
  * Order untuk kain tanpa stok / tanpa gulungan TIDAK ditolak — tersimpan sebagai draf dan tampil "Menunggu kain"
    beserta alasannya (kain apa, perlu berapa, stok berapa, kurang berapa).
  * Keadaan kain DIHITUNG dari stok saat dibaca: begitu stok + gulungan masuk, order yang sama tampil siap dimulai
    tanpa ada yang menulis ulang order.
  * Penyaring daftar: status tampilan, model, warna, kain, peminta, rentang tanggal (WIB), pencarian, dan hasil
    > 120% rencana (kasus 13 Nov: 93 dari 50).

Jalankan (serial):  cd backend && python -m pytest tests/unit/test_cutting_menunggu_kain.py -n 0 -q
"""
import asyncio
import os
import sys
from datetime import timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from test_tahap2_gudang import Req  # noqa: E402
from test_cutting_banyak_hasil import _db, _env, _multi_body  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _db_kain_kosong():
    db = _db()
    db.rahaza_materials.docs.append({"id": "M9", "code": "K-09", "name": "Kain Jersey Hitam", "type": "fabric",
                                     "unit": "kg", "unit_cost": 25000.0, "active": True})
    return db


def _request_body(**kw):
    """Peminta (PIC toko) tidak memilih gulungan — kainnya memang belum ada."""
    return {"location_id": "L1", "inputs": [{"input_material_id": "M9", "planned_input_qty": 30}],
            "outputs": [{"model_id": "MOD1", "variant_id": "V1", "planned_output_qty": 50}], **kw}


def _rows(cut, **kw):
    return run(cut.list_orders(Req(), **{"status": None, "q": None, "model_id": None, "color": None,
                                         "material_id": None, "created_by": None, "date_from": None,
                                         "date_to": None, "over": False, "limit": 200, "skip": 0, **kw}))


# ═════════════════════ 1 · request tetap tersimpan walau kain belum ada ═════════════════════
def test_request_kain_belum_ada_tersimpan_menunggu_kain(monkeypatch):
    db = _db_kain_kosong()
    cut = _env(monkeypatch, db)
    o = run(cut.create_order(Req(_request_body())))
    assert o["status"] == "draft" and o["display_status"] == "waiting_fabric" and o["fabric_waiting"] is True
    s = o["fabric_shortage"][0]
    assert (s["code"], s["need"], s["have"], s["short"]) == ("K-09", 30.0, 0.0, 30.0)
    assert "K-09 belum ada stoknya (perlu 30 kg)" in o["fabric_note"]
    assert o["inputs"][0]["roll_required"] is True and o["inputs"][0]["roll_ids"] == []
    stored = next(x for x in db.cutting_orders.docs if x["id"] == o["id"])
    assert stored["status"] == "draft" and "fabric_waiting" not in stored        # tidak disalin ke DB
    with pytest.raises(HTTPException) as e:                                       # mulai tetap dijaga stok
        run(cut.start_order(o["id"], Req()))
    assert "kosong di semua gudang" in e.value.detail


def test_stok_dan_gulungan_masuk_order_otomatis_siap_dimulai(monkeypatch):
    db = _db_kain_kosong()
    cut = _env(monkeypatch, db)
    o = run(cut.create_order(Req(_request_body())))
    from core import stock_service
    # stok sebagian: masih menunggu, alasannya menyebut kurangnya
    db[stock_service.STOCK].docs.append({"id": "s9", "material_id": "M9", "location_id": "L1", "qty": 12.0})
    db.wh_fabric_rolls.docs.append({"id": "R9", "roll_no": "R-0009", "material_id": "M9", "uom": "kg",
                                    "weight_kg": 12.0, "remaining_kg": 12.0, "status": "in_stock",
                                    "location_id": "L1", "location_name": "Gudang A"})
    d = run(cut.get_order(o["id"], Req()))
    assert d["display_status"] == "waiting_fabric"
    assert "K-09 perlu 30 kg, stok 12 kg — kurang 18 kg" in d["fabric_note"]
    # stok cukup → siap dimulai tanpa ada yang menyentuh order
    db[stock_service.STOCK].docs[-1]["qty"] = 40.0
    d = run(cut.get_order(o["id"], Req()))
    assert d["display_status"] == "draft" and d["fabric_waiting"] is False and d["fabric_shortage"] == []
    out = run(cut.start_order(o["id"], Req()))
    assert out["status"] == "in_progress" and out["display_status"] == "in_progress"


def test_stok_ada_tetapi_gulungan_belum_terbit_masih_menunggu(monkeypatch):
    db = _db_kain_kosong()
    cut = _env(monkeypatch, db)
    from core import stock_service
    db[stock_service.STOCK].docs.append({"id": "s9", "material_id": "M9", "location_id": "L1", "qty": 40.0})
    o = run(cut.create_order(Req(_request_body())))
    assert o["display_status"] == "waiting_fabric"
    assert "gulungannya belum diterbitkan" in o["fabric_note"]


# ═════════════════════ 2 · penyaring daftar ═════════════════════
@pytest.fixture
def daftar(monkeypatch):
    """Tiga order: menunggu kain (K-09, MOD1 Merah), siap dimulai (K-01 multi), berjalan 93 dari 50 (K-01, MOD1)."""
    db = _db_kain_kosong()
    cut = _env(monkeypatch, db)
    seq = iter(range(11, 50))

    async def number(*a, **k):
        return f"CUT-2026-{next(seq):04d}"
    monkeypatch.setattr(cut, "gen_prefixed_number", number)
    w = run(cut.create_order(Req(_request_body())))
    ready = run(cut.create_order(Req(_multi_body())))
    over = run(cut.create_order(Req({"input_material_id": "M1", "location_id": "L1", "planned_input_qty": 15,
                                     "planned_output_qty": 50, "model_id": "MOD1", "variant_id": "V1",
                                     "roll_ids": ["R1"]})))
    run(cut.start_order(over["id"], Req()))
    run(cut.add_progress(over["id"], Req({"input_consumed": 20, "output_qty": 93, "roll_ids": ["R1"]})))
    doc = next(x for x in db.cutting_orders.docs if x["id"] == ready["id"])
    doc["created_by"], doc["created_by_name"] = "u-toko", "Sari (PIC toko)"
    return db, cut, {"waiting": w["id"], "ready": ready["id"], "over": over["id"]}


def test_penyaring_status_tampilan(daftar):
    db, cut, ids = daftar
    ids_of = lambda rows: {r["id"] for r in rows}  # noqa: E731
    assert ids_of(_rows(cut, status="waiting_fabric")) == {ids["waiting"]}
    # draf yang kainnya cukup (order banyak kain K-01 + K-02) dan order lama O1? O1 berjalan → tidak ikut
    assert ids_of(_rows(cut, status="draft")) == {ids["ready"]}
    assert ids["over"] in ids_of(_rows(cut, status="in_progress"))


def test_penyaring_model_warna_kain_peminta_tanggal_cari_dan_di_atas_rencana(daftar):
    db, cut, ids = daftar
    ids_of = lambda rows: {r["id"] for r in rows}  # noqa: E731
    assert ids_of(_rows(cut, model_id="MOD3")) == {ids["ready"]}                       # baris hasil ke-3
    assert ids_of(_rows(cut, color="biru")) == {ids["ready"]}                          # tanpa beda huruf
    assert ids_of(_rows(cut, material_id="M9")) == {ids["waiting"]}
    assert ids_of(_rows(cut, material_id="M3")) == {ids["ready"]}                      # kain baris ke-2
    assert ids_of(_rows(cut, created_by="u-toko")) == {ids["ready"]}
    over = _rows(cut, over=True)
    assert ids_of(over) == {ids["over"]} and over[0]["over_plan"] is True
    assert over[0]["outputs"][0]["over_plan"] is True
    assert ids_of(_rows(cut, q="CUT-2026-0011")) == {ids["waiting"]}
    assert _rows(cut, q="(") == []                                                     # tanda regex aman
    from utils.waktu import today_wib
    today = today_wib()
    assert ids["waiting"] in ids_of(_rows(cut, date_from=today.isoformat(), date_to=today.isoformat()))
    assert _rows(cut, date_from=(today + timedelta(days=1)).isoformat()) == []
    with pytest.raises(HTTPException) as e:
        _rows(cut, date_from="14-11-2026")
    assert "Tanggal penyaring" in e.value.detail


def test_pilihan_penyaring_dan_jumlah_per_status(daftar):
    db, cut, ids = daftar
    f = run(cut.order_facets(Req()))
    assert f["counts"]["waiting_fabric"] == 1 and f["counts"]["draft"] == 1
    assert f["counts"]["in_progress"] == 2 and f["counts"]["over_plan"] == 1          # + order lama O1
    assert {x["value"] for x in f["fabrics"]} >= {"M1", "M3", "M9"}
    assert {x["label"] for x in f["colors"]} >= {"Merah", "Biru"}
    assert {"value": "u-toko", "label": "Sari (PIC toko)"} in f["requesters"]
    assert any(x["value"] == "MOD3" and "MD3" in x["label"] for x in f["models"])
