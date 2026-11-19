"""Uji unit HERMETIK — kendala Packing 19 Nov 2026 (Retur Fisik, keputusan owner "perbaiki semua").

  · Impor Retur & Refund: dua pengajuan retur untuk dua variasi produk yang sama dalam satu pesanan tidak lagi
    dianggap dobel (pesanan 586634543225210426: MELA Scarlet XL + MELA Leopard Pink XL).
  · Retur fisik membawa resi paket retur dari berkas retur (dulu selalu kosong).
  · Pesanan dua barang: retur tertaut otomatis lewat SKU platform / variasi.
  · Keputusan "Sudah masuk stok awal": selesai tanpa stok, hanya untuk retur yang diajukan ≤ cutoff, dan dihitung
    sebagai retur yang diputuskan (mengurangi omzet Marketing, K36).

Jalankan:  cd backend && python -m pytest tests/unit/test_retur_packing_19nov.py -q
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

from _fake_mongo import FakeDB  # noqa: E402
from core import marketing_returns as mret  # noqa: E402
from core import returns_bridge as rb  # noqa: E402

ORDER = "586634543225210426"
PROD = "MELA ONE SET RAYON WANITA | One Set Baju Celana Pendek"


def run(coro):
    return asyncio.run(coro)


def test_dua_variasi_satu_pesanan_tidak_dianggap_dobel():
    db = FakeDB()
    db.marketing_returns.docs = [{"id": "r1", "account_id": "a", "order_id": ORDER, "product": PROD,
                                  "variation": "Scarlet, XL / JUMBO", "return_id": "R-1"}]
    leopard = {"order_id": ORDER, "product": PROD, "variation": "Leopard Pink, XL / JUMBO", "return_id": "R-2"}
    scarlet = {"order_id": ORDER, "product": PROD, "variation": "Scarlet, XL / JUMBO", "return_id": "R-1"}
    assert run(db.marketing_returns.find_one(mret.kunci_dedupe_retur(leopard, "a"))) is None
    assert run(db.marketing_returns.find_one(mret.kunci_dedupe_retur(scarlet, "a")))["id"] == "r1"
    # pengajuan lain (No. Pengembalian beda) untuk variasi yang sama juga bukan dobel
    assert run(db.marketing_returns.find_one(mret.kunci_dedupe_retur({**scarlet, "return_id": "R-9"}, "a"))) is None
    # retur dari form refund (tanpa No. Pengembalian) tetap dikenali → impor tidak menggandakan
    db.marketing_returns.docs.append({"id": "manual", "account_id": "a", "order_id": "X1", "product": "Gamis",
                                      "variation": ""})
    hit = run(db.marketing_returns.find_one(mret.kunci_dedupe_retur(
        {"order_id": "X1", "product": "Gamis", "variation": "Hitam, M", "return_id": "R-5"}, "a")))
    assert hit["id"] == "manual"
    assert mret.kunci_dedupe_retur({"order_id": "", "product": PROD}, "a") is None


def test_baris_pesanan_dipilih_lewat_sku_platform_atau_variasi():
    lines = [{"platform_sku_id": "1737546016757286771", "variation_raw": "Scarlet, XL / JUMBO", "fg_material_id": "F-SCR"},
             {"platform_sku_id": "1737546016757286999", "variation_raw": "Leopard Pink, XL / JUMBO", "fg_material_id": "F-LPP"}]
    assert [x["fg_material_id"] for x in rb.cocok_baris_retur(lines, {"sku": "1737546016757286771"})] == ["F-SCR"]
    assert [x["fg_material_id"] for x in rb.cocok_baris_retur(lines, {"variation": "leopard pink , xl/jumbo"})] == ["F-LPP"]
    assert rb.cocok_baris_retur(lines, {"product": PROD}) == []


def test_resi_paket_retur_diisi_dari_berkas_retur():
    db = FakeDB()
    db.marketing_orders.docs = [{"id": "o1", "order_id": ORDER, "tracking_number": "JY2021500230"}]
    db.wh_returns.docs = [{"id": "w1", "return_code": "WH-RET-00165", "resi_number": "", "order_number": ORDER}]
    ret = {"id": "r1", "order_id": ORDER, "tracking_number": "JX4525944934"}
    assert run(rb.resi_retur(db, ret)) == ("JX4525944934", "JY2021500230")
    out = run(rb.isi_resi(db, dict(db.wh_returns.docs[0]), ret))
    assert out["resi_number"] == "JX4525944934" and out["resi_pesanan"] == "JY2021500230"
    assert db.wh_returns.docs[0]["resi_number"] == "JX4525944934"


def _db_stok_awal(tgl):
    db = FakeDB()
    db.marketing_returns.docs = [{"id": "r1", "date": tgl, "order_id": ORDER, "status": "completed",
                                  "refund_amount": 65684}]
    db.wh_returns.docs = [{"id": "w1", "return_code": "WH-RET-00146", "status": "Pending", "qty": 1,
                           "source_marketing_return_id": "r1", "order_number": ORDER, "timeline": []}]
    return db


def test_keputusan_sudah_masuk_stok_awal():
    db = _db_stok_awal("2026-10-28")
    res = run(rb.putuskan_stok_awal(db, "w1", actor={"name": "Yani"}, note="diterima 31 Okt"))
    w = db.wh_returns.docs[0]
    assert w["status"] == rb.STATUS_RESOLVED and w["action_taken"] == rb.ACTION_STOK_AWAL
    assert not w.get("restocked") and w["restock_qty"] == 0          # stok tidak bergerak
    assert "stok tidak berubah" in res["message"]
    m = db.marketing_returns.docs[0]
    assert m["wh_return_status"] == "Resolved" and m["wh_action_taken"] == rb.ACTION_STOK_AWAL
    assert mret.is_module_return_counted(m)                           # refund tetap mengurangi omzet (K36)
    with pytest.raises(rb.ReturnBridgeError):                         # tidak bisa diputuskan dua kali
        run(rb.putuskan_stok_awal(db, "w1", actor={"name": "Yani"}))


def test_retur_sesudah_cutoff_ditolak():
    db = _db_stok_awal("2026-11-12")
    with pytest.raises(rb.ReturnBridgeError) as e:
        run(rb.putuskan_stok_awal(db, "w1", actor={"name": "Yani"}))
    assert "sesudah cutoff" in str(e.value)
    assert db.wh_returns.docs[0]["status"] == "Pending"
