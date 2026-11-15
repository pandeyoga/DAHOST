"""Uji unit HERMETIK tab Pantau Produksi › Per produk (owner 16 Nov 2026: pengganti lembar "SISA POTONGAN").

Skenario (angka DIHITUNG TANGAN, data uji tanpa nama/angka klien):

PO internal PO-A (CMT Satu, berjalan):
  I1 Gamis uji Hitam M, kode KP-01 · saldo awal cutoff 100 pcs (surat jalan `opening`, 20 hari lalu)
     · setoran selesai QC: lolos 60 + reject 5 · setoran sedang QC 10 ⇒ sisa di CMT 100 − 65 − 10 = 25, umur 20 hari
  I2 Gamis uji Hitam L, kode KP-02 · kirim 50 (10 hari lalu), belum setor ⇒ sisa 50, umur 10 hari
  I3 Tunik uji Putih M, kode KP-03 · kirim 30 (3 hari lalu), setor lolos 30 ⇒ sisa 0 (sudah selesai)
  I4 Tunik uji Putih L, kode KP-04 · kirim 20, setor lolos 25 ⇒ sisa 0 + LEBIH SETOR 5
  I5 Gamis uji Hitam S · belum pernah dikirim ke CMT ⇒ tidak tampil
PO internal PO-BATAL (dibatalkan) dan PO-TUTUP (selesai): potongan 70 & 40 di CMT ⇒ tidak ikut.
PO maklon PO-M1 (Klien satu, CMT Dua): MK1 Kemeja klien Biru M, kode KPM-1 · kirim 40 (5 hari lalu) ⇒ sisa 40
PO maklon PO-M2 (Klien dua, CMT Dua):  MK2 Celana klien Abu L, kode KPM-2 · kirim 15 (15 hari lalu) ⇒ sisa 15

Jalankan:  cd backend && python -m pytest tests/unit/test_pantau_per_produk.py -n 0 -q
"""
import asyncio
import os
import re
import sys
from datetime import timedelta

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
FE = os.path.join(os.path.dirname(BACKEND), "frontend", "src", "components", "erp")
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from p3_fakes import FakeColl, FakeDB  # noqa: E402
from core import pantau_produksi as pp  # noqa: E402
from utils.waktu import today_wib  # noqa: E402

TODAY = today_wib()


def ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def run(coro):
    return asyncio.run(coro)


class DB(FakeDB):
    def __init__(self, **colls):
        self._c = {k: FakeColl(v) for k, v in colls.items()}

    def __getitem__(self, name):
        return self._c.setdefault(name, FakeColl())


def _po(pid, number, bt, status="In Production", vendor=("V1", "CMT Satu"), **kw):
    return {"id": pid, "po_number": number, "business_type": bt, "status": status, "vendor_id": vendor[0],
            "vendor_name": vendor[1], "created_at": ago(30), **kw}


def _item(iid, po, qty, serial, color, size, *, model_id="", catalog_item_id="", name="Produk uji"):
    return {"id": iid, "po_id": po["id"], "po_number": po["po_number"], "qty": qty, "serial_number": serial,
            "color": color, "size": size, "sku": f"SKU-{iid}", "product_name": name, "model_id": model_id,
            "catalog_item_id": catalog_item_id, "cmt_price_snapshot": 0}


def scenario() -> DB:
    pa = _po("po-a", "PO-A", "internal", customer_name="Gudang DA")
    pbatal = _po("po-batal", "PO-BATAL", "internal", status="Cancelled")
    ptutup = _po("po-tutup", "PO-TUTUP", "internal", status="Completed")
    pm1 = _po("po-m1", "PO-M1", "maklon", vendor=("V2", "CMT Dua"), buyer_id="K1", customer_name="Klien satu")
    pm2 = _po("po-m2", "PO-M2", "maklon", vendor=("V2", "CMT Dua"), buyer_id="K2", customer_name="Klien dua")
    items = [
        _item("I1", pa, 100, "KP-01", "Hitam", "M", model_id="M1", name="Gamis lama"),
        _item("I2", pa, 50, "KP-02", "Hitam", "L", model_id="M1", name="Gamis lama"),
        _item("I3", pa, 30, "KP-03", "Putih", "M", model_id="M2"),
        _item("I4", pa, 20, "KP-04", "Putih", "L", model_id="M2"),
        _item("I5", pa, 40, "KP-05", "Hitam", "S", model_id="M1"),
        _item("IB", pbatal, 70, "KP-B", "Hitam", "M", model_id="M1"),
        _item("IT", ptutup, 40, "KP-T", "Hitam", "M", model_id="M1"),
        _item("MK1", pm1, 40, "KPM-1", "Biru", "M", catalog_item_id="C1", name="Kemeja"),
        _item("MK2", pm2, 15, "KPM-2", "Abu", "L", catalog_item_id="C2", name="Celana"),
    ]
    vs = [
        {"id": "VS-OPEN", "po_id": "po-a", "vendor_id": "V1", "shipment_type": "NORMAL", "opening": True,
         "status": "Received", "shipment_date": ago(20), "created_at": TODAY.isoformat()},
        {"id": "VS-A2", "po_id": "po-a", "vendor_id": "V1", "shipment_type": "NORMAL", "status": "Sent",
         "shipment_date": ago(10)},
        {"id": "VS-A3", "po_id": "po-a", "vendor_id": "V1", "shipment_type": "NORMAL", "status": "Sent",
         "shipment_date": ago(3)},
        {"id": "VS-B", "po_id": "po-batal", "vendor_id": "V1", "shipment_type": "NORMAL", "shipment_date": ago(40)},
        {"id": "VS-T", "po_id": "po-tutup", "vendor_id": "V1", "shipment_type": "NORMAL", "shipment_date": ago(40)},
        {"id": "VS-M1", "po_id": "po-m1", "vendor_id": "V2", "shipment_type": "NORMAL", "shipment_date": ago(5)},
        {"id": "VS-M2", "po_id": "po-m2", "vendor_id": "V2", "shipment_type": "NORMAL", "shipment_date": ago(15)},
    ]
    vsi = [{"id": "S1", "shipment_id": "VS-OPEN", "po_item_id": "I1", "qty_sent": 100, "opening": True},
           {"id": "S2", "shipment_id": "VS-A2", "po_item_id": "I2", "qty_sent": 50},
           {"id": "S3", "shipment_id": "VS-A3", "po_item_id": "I3", "qty_sent": 30},
           {"id": "S4", "shipment_id": "VS-A3", "po_item_id": "I4", "qty_sent": 20},
           {"id": "SB", "shipment_id": "VS-B", "po_item_id": "IB", "qty_sent": 70},
           {"id": "ST", "shipment_id": "VS-T", "po_item_id": "IT", "qty_sent": 40},
           {"id": "SM1", "shipment_id": "VS-M1", "po_item_id": "MK1", "qty_sent": 40},
           {"id": "SM2", "shipment_id": "VS-M2", "po_item_id": "MK2", "qty_sent": 15}]
    rec = [{"id": "R-DONE", "po_id": "po-a", "status": "completed_qc"},
           {"id": "R-QC", "po_id": "po-a", "status": "on_qc"},
           {"id": "R-BATAL", "po_id": "po-a", "status": "cancelled"}]
    lines = [{"id": "L1", "receipt_id": "R-DONE", "po_item_id": "I1", "qty_actual": 60, "reject_qty": 5},
             {"id": "L2", "receipt_id": "R-QC", "po_item_id": "I1", "qty_claimed_by_cmt": 10},
             {"id": "L3", "receipt_id": "R-DONE", "po_item_id": "I3", "qty_actual": 30, "reject_qty": 0},
             {"id": "L4", "receipt_id": "R-DONE", "po_item_id": "I4", "qty_actual": 25, "reject_qty": 0},
             # penerimaan yang dibatalkan tidak mengurangi apa pun
             {"id": "L5", "receipt_id": "R-BATAL", "po_item_id": "I2", "qty_actual": 50, "reject_qty": 0}]
    return DB(production_pos=[pa, pbatal, ptutup, pm1, pm2], po_items=items, vendor_shipments=vs,
              vendor_shipment_items=vsi, cmt_receipts=rec, cmt_receipt_lines=lines,
              rahaza_models=[{"id": "M1", "name": "Gamis uji", "code": "GMU"},
                             {"id": "M2", "name": "Tunik uji", "code": "TNU"}],
              dewi_maklon_buyer_catalog=[{"id": "C1", "product_name": "Kemeja klien", "artikel_code": "KK-01"},
                                         {"id": "C2", "product_name": "Celana klien", "artikel_code": "CK-02"}])


def produk(db, bt="internal", **kw):
    return run(pp.per_produk(db, bt, today=TODAY, **kw))


def rows_of(res) -> dict:
    return {r["po_item_id"]: r for p in res["rows"] for r in p["rows"]}


# ══════════════════════ fungsi murni ══════════════════════
def test_pita_umur_sesuai_sop_lembar():
    assert [pp.umur_bucket(d) for d in (None, 0, 7, 8, 14, 15, 90)] == ["", "0-7", "0-7", "8-14", "8-14",
                                                                         "lebih14", "lebih14"]


def test_baris_lebih_setor_tidak_pernah_negatif():
    ln = {"po_item_id": "X", "po_id": "p", "sent_cmt": 10, "sent_extra": 0, "returned": 12, "in_qc": 1,
          "di_cmt": 0, "good_from_cmt": 12, "reject": 0, "first_sent": ago(3)}
    r = pp.produk_row(ln, TODAY)
    assert (r["sisa"], r["lebih_setor"], r["umur_hari"], r["umur"]) == (0, 3, None, "")
    # kiriman pengganti/tambahan menjelaskan kelebihan → bukan lebih setor
    assert pp.produk_row({**ln, "sent_extra": 5}, TODAY)["lebih_setor"] == 0


def test_kunci_produk_model_lalu_katalog_lalu_nama():
    assert pp.produk_key({"model_id": "M1", "catalog_item_id": "C1"}, "internal") == "model:M1"
    assert pp.produk_key({"model_id": "M1", "catalog_item_id": "C1"}, "maklon") == "katalog:C1"
    assert pp.produk_key({"product_name": "  Kaos   Polos "}, "maklon") == "nama:kaos polos"


# ══════════════════════ angka per produk (internal) ══════════════════════
def test_internal_sisa_di_cmt_per_produk():
    db = scenario()
    res = produk(db)
    assert [p["produk_nama"] for p in res["rows"]] == ["Gamis uji"]   # Tunik uji sudah habis di CMT
    g = res["rows"][0]
    assert (g["produk_kode"], g["sisa"], g["dikirim"], g["setor"], g["reject"], g["sedang_qc"]) == \
        ("GMU", 75, 150, 60, 5, 10)
    assert (g["cmt_count"], g["batch_count"], g["tanggal_kirim_tertua"], g["umur_hari"], g["umur"]) == \
        (1, 2, ago(20), 20, "lebih14")
    r = rows_of(res)
    # saldo awal cutoff dihitung sebagai dikirim, tanggalnya = tanggal surat jalan
    i1 = r["I1"]
    assert (i1["dikirim"], i1["setor"], i1["reject"], i1["sedang_qc"], i1["sisa"]) == (100, 60, 5, 10, 25)
    assert (i1["tanggal_kirim"], i1["umur_hari"], i1["umur"], i1["serial_number"], i1["po_number"],
            i1["vendor_name"], i1["color"], i1["size"]) == (ago(20), 20, "lebih14", "KP-01", "PO-A", "CMT Satu",
                                                           "Hitam", "M")
    # penerimaan yang dibatalkan tidak mengurangi sisa
    assert (r["I2"]["sisa"], r["I2"]["umur"]) == (50, "8-14")
    # urut tanggal kirim terlama dulu
    assert [x["po_item_id"] for x in g["rows"]] == ["I1", "I2"]
    s = res["summary"]
    assert (s["sisa"], s["produk"], s["cmt"], s["batch_lama"]) == (75, 1, 1, 1)


def test_po_batal_tutup_dan_belum_dikirim_tidak_ikut():
    db = scenario()
    ids = set(rows_of(produk(db, keadaan="semua")))
    assert ids == {"I1", "I2", "I3", "I4"}
    assert not ids & {"I5", "IB", "IT", "MK1", "MK2"}


def test_sama_dengan_di_cmt_tab_lain():
    """Satu sumber: total sisa = Σ di_cmt baris PO berjalan (angka Di CMT tab Per vendor / Kejar CMT)."""
    db = scenario()
    lines = run(pp.po_lines(db, run(pp.load_pos(db, "internal", running=True))))
    assert produk(db)["summary"]["sisa"] == pp.sum_lines(lines)["di_cmt"] == 75


def test_sudah_selesai_dan_lebih_setor():
    db = scenario()
    res = produk(db, keadaan="selesai")
    assert [p["produk_nama"] for p in res["rows"]] == ["Tunik uji"]
    r = rows_of(res)
    assert (r["I3"]["sisa"], r["I3"]["lebih_setor"]) == (0, 0)
    assert (r["I4"]["sisa"], r["I4"]["lebih_setor"], r["I4"]["setor"]) == (0, 5, 25)
    assert res["rows"][0]["baris_lebih_setor"] == 1
    # peringatan lebih setor tetap terbaca di tampilan bawaan (yang hanya menampilkan sisa > 0)
    s = produk(db)["summary"]
    assert (s["lebih_setor_baris"], s["lebih_setor_pcs"]) == (1, 5)
    assert produk(db)["keadaan_counts"] == {"di_cmt": 2, "selesai": 2, "semua": 4}
    assert len(produk(db, keadaan="semua")["rows"]) == 2


def test_saringan_umur_cari_dan_cmt():
    db = scenario()
    assert produk(db)["umur_counts"] == {"0-7": 0, "8-14": 1, "lebih14": 1}
    assert set(rows_of(produk(db, umur="8-14"))) == {"I2"}
    assert set(rows_of(produk(db, umur="lebih14"))) == {"I1"}
    assert set(rows_of(produk(db, search="kp-02"))) == {"I2"}
    assert set(rows_of(produk(db, search="gmu"))) == {"I1", "I2"}
    assert produk(db, vendor_id="V9")["rows"] == []
    assert produk(db, vendor_id="V9")["vendors"] == [{"id": "V1", "name": "CMT Satu"}]   # pilihan tidak hilang


# ══════════════════════ maklon: artikel katalog + saringan klien ══════════════════════
def test_maklon_per_artikel_dan_saringan_klien():
    db = scenario()
    res = produk(db, "maklon")
    assert [(p["produk_nama"], p["produk_kode"], p["sisa"]) for p in res["rows"]] == \
        [("Kemeja klien", "KK-01", 40), ("Celana klien", "CK-02", 15)]
    assert set(rows_of(res)) == {"MK1", "MK2"}             # PO internal tidak ikut
    assert res["klien"] == [{"id": "K2", "name": "Klien dua"}, {"id": "K1", "name": "Klien satu"}]
    assert res["rows"][0]["klien"] == ["Klien satu"]
    one = produk(db, "maklon", klien_id="K1")
    assert [p["produk_nama"] for p in one["rows"]] == ["Kemeja klien"]
    assert (one["summary"]["sisa"], one["summary"]["batch_lama"]) == (40, 0)
    assert produk(db, "maklon")["summary"]["batch_lama"] == 1   # MK2 sudah 15 hari
    # PO internal tidak punya daftar klien
    assert produk(db)["klien"] == []


# ══════════════════════ endpoint: aturan akses sama dengan tab saudara ══════════════════════
@pytest.fixture
def api(monkeypatch):
    import routes.pantau_produksi as rp
    db = scenario()
    user = {"id": "u1", "name": "Staf uji", "role": "admin"}

    async def auth(_r):
        return user
    monkeypatch.setattr(rp, "get_db", lambda: db)
    monkeypatch.setattr(rp, "require_auth", auth)
    return rp, user


class Req:
    query_params: dict = {}
    headers: dict = {}


def _call(rp, bt, **kw):
    args = {"search": "", "vendor_id": "", "klien_id": "", "umur": "", "keadaan": "di_cmt", **kw}
    return run(rp.get_per_produk(Req(), business_type=bt, **args))


def test_endpoint_saringan_portal_dan_klien(api):
    rp, _ = api
    internal, maklon = _call(rp, "internal"), _call(rp, "maklon")
    assert {r["po_number"] for r in rows_of(internal).values()} == {"PO-A"}
    assert {r["po_number"] for r in rows_of(maklon).values()} == {"PO-M1", "PO-M2"}
    # saringan klien hanya berlaku di Portal Maklon
    assert set(rows_of(_call(rp, "internal", klien_id="K1"))) == {"I1", "I2"}
    assert set(rows_of(_call(rp, "maklon", klien_id="K2"))) == {"MK2"}


@pytest.mark.parametrize("role", ["klien_maklon", "vendor", "cmt_vendor"])
def test_endpoint_menolak_klien_dan_vendor(api, role):
    rp, user = api
    user["role"] = role
    with pytest.raises(HTTPException) as e:
        _call(rp, "internal")
    assert e.value.status_code == 403


# ══════════════════════ layar ══════════════════════
def _src(*p):
    return open(os.path.join(FE, *p), encoding="utf-8").read()


def test_layar_per_produk_terdaftar_dan_memakai_cetakan():
    hub = _src("pantau", "PantauProduksiModule.jsx")
    keys = re.findall(r"key: '([a-z]+)'", hub)
    assert keys[:2] == ["ringkasan", "produk"]                 # tepat setelah Ringkasan
    s = _src("pantau", "PerProdukTab.jsx")
    assert "/pantau/produk?business_type=${bt}" in s
    assert "<PageLayout" in s and "<RowDetail" in s and "<EmptyState" in s and "<TombolUnduh" in s
    assert "<SmartNativeSelect" in s and "<FilterChips" in s and "<StatTile" in s
    assert not re.search(r"<(select|table|button|h1)\b", s)
    assert not re.search(r"window\.confirm|\balert\(", s)
