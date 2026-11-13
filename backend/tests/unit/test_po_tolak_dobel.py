"""PO produksi dobel DITOLAK (keputusan owner 14 Nov 2026) — core.po_tolak_dobel + routes.production_pos.

Kejadian 13 Nov 2026: dua pasang PO kembar dari klik ganda (selisih 1,1 detik dan 0,09 detik), dan lima PO
memasukkan lagi kode potongan yang sudah ada di PO lain (layar hanya memberi peringatan).
"""
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402
from core import po_tolak_dobel as ptd  # noqa: E402
from core.helpers import now  # noqa: E402

USER = {"id": "u-fatih", "name": "Admin Produksi", "role": "admin"}


def run(c):
    return asyncio.run(c)


class _Req:
    def __init__(self, body):
        self._body = body
        self.headers = {}
        self.query_params = {}
        self.cookies = {}

    async def json(self):
        return dict(self._body)


@pytest.fixture
def db():
    d = FakeDB()
    d.production_pos.docs = [
        {"id": "po-cut", "po_number": "PO-INT-0003", "vendor_name": "P Bambang", "status": "In Production",
         "business_type": "internal", "customer_name": "Gudang FG Sendiri"},
        {"id": "po-batal", "po_number": "PO-INT-0099", "vendor_name": "B Uji", "status": "Cancelled",
         "business_type": "internal"},
    ]
    d.po_items.docs = [
        {"id": "a1", "po_id": "po-cut", "po_number": "PO-INT-0003", "serial_number": "DA-1869", "sku": "DA-2204-DST",
         "qty": 52},
        {"id": "a2", "po_id": "po-batal", "po_number": "PO-INT-0099", "serial_number": "DA-1777", "sku": "X", "qty": 1},
    ]
    return d


def _baris(kode, sku, qty=10, **kw):
    return {"serial_number": kode, "sku": sku, "qty": qty, **kw}


# ── aturan inti ────────────────────────────────────────────────────────────────

def test_satu_kode_banyak_warna_boleh_tapi_kode_dan_varian_sama_ditolak():
    assert ptd.baris_kembar([_baris("DA-1896", "DA-1501-SCR-M"), _baris("da-1896 ", "DA-1501-STB-M")]) == []
    kembar = ptd.baris_kembar([_baris("DA-1891", "DA-1519-DGO", rahaza_variant_id="v1"),
                               _baris("DA-1891", "DA-1519-DGO", qty=26, rahaza_variant_id="v1")])
    assert len(kembar) == 1 and kembar[0].startswith("DA-1891")


def test_kode_dipakai_po_lain_ditolak_dengan_nomor_po_dan_cmt(db):
    with pytest.raises(HTTPException) as e:
        run(ptd.periksa_kode(db, [_baris(" da-1869", "DA-2204-DST")]))
    assert e.value.status_code == 409
    assert "DA-1869" in e.value.detail and "PO-INT-0003 (P Bambang)" in e.value.detail
    # PO yang sama (ubah), kode lama, PO batal, dan kode baru → lolos
    run(ptd.periksa_kode(db, [_baris("DA-1869", "DA-2204-DST")], kecuali_po_id="po-cut"))
    run(ptd.periksa_kode(db, [_baris("DA-1869", "DA-2204-DST")], kode_lama=["DA-1869"]))
    run(ptd.periksa_kode(db, [_baris("DA-1777", "X")]))
    run(ptd.periksa_kode(db, [_baris("DA-1896", "DA-1501-SCR-M"), _baris("", "tanpa-kode")]))


def test_baris_cutoff_berisi_beberapa_kode_ikut_diperiksa(db):
    # baris PO saldo awal (1 PO per CMT) menggabungkan beberapa batch: "DA-1725, DA-1869"
    db.po_items.docs.append({"id": "c1", "po_id": "po-cut", "po_number": "PO-INT-0003",
                             "serial_number": "DA-1725, da-1855 ;DA-1868", "sku": "DA-2204-DST", "qty": 69})
    for kode in ("DA-1855", "da-1868", "DA-1868 / DA-9999"):
        with pytest.raises(HTTPException) as e:
            run(ptd.periksa_kode(db, [_baris(kode, "DA-2204-DST")]))
        assert "PO-INT-0003" in e.value.detail
    run(ptd.periksa_kode(db, [_baris("DA-172", "DA-2204-DST")]))          # bukan potongan kode lain


def test_ubah_satu_baris_kode_dipakai_po_lain_ditolak(db, monkeypatch):
    from routes import production_pos as pp
    import core.po_lock as pl

    async def _auth(_r):
        return dict(USER)

    async def _nop(*a, **k):
        return None
    monkeypatch.setattr(pp, "require_auth", _auth)
    monkeypatch.setattr(pp, "get_db", lambda: db)
    monkeypatch.setattr(pp, "check_role", lambda *a, **k: True)
    monkeypatch.setattr(pl, "assert_po_open", _nop)
    db.po_items.docs.append({"id": "b1", "po_id": "po-baru", "po_number": "PO-INT-0017", "serial_number": "",
                             "sku": "DA-2204-DST", "qty": 52})
    with pytest.raises(HTTPException) as e:
        run(pp.update_po_item("b1", _Req({"serial_number": "DA-1869"})))
    assert e.value.status_code == 409 and next(i for i in db.po_items.docs if i["id"] == "b1")["serial_number"] == ""
    run(pp.update_po_item("b1", _Req({"serial_number": "DA-1999"})))
    run(pp.update_po_item("b1", _Req({"qty": 50})))                      # tanpa ubah kode → tidak diperiksa
    assert next(i for i in db.po_items.docs if i["id"] == "b1")["serial_number"] == "DA-1999"


def test_sidik_sama_untuk_isi_sama_beda_bila_isi_beda():
    a = {"business_type": "internal", "vendor_id": "v", "items": [_baris("DA-1", "S1"), _baris("DA-1", "S2")]}
    b = {"business_type": "internal", "vendor_id": "v", "items": [_baris("da-1", "S2"), _baris("DA-1", "S1")]}
    c = {"business_type": "internal", "vendor_id": "v", "items": [_baris("DA-1", "S1", qty=11), _baris("DA-1", "S2")]}
    assert ptd.sidik_isi(a, USER) == ptd.sidik_isi(b, USER) != ptd.sidik_isi(c, USER)
    assert ptd.sidik_isi(a, USER) != ptd.sidik_isi(a, {"id": "orang-lain"})


# ── jalur layar: buat PO ──────────────────────────────────────────────────────

def _pasang_rute(db, monkeypatch):
    from routes import production_pos as pp

    async def _auth(_r):
        return dict(USER)

    async def _jaga(*a, **k):
        return [], ""

    async def _model(*a, **k):
        return {}

    async def _buat(_db, body, _u):
        await asyncio.sleep(0.02)          # jeda tulis: tanpa kunci, kiriman kedua lolos pemeriksaan
        pid = f"po{len(db.production_pos.docs) + 1}"
        doc = {"id": pid, "po_number": f"PO-INT-{pid}", "vendor_name": "P Bambang", "status": "Draft",
               "business_type": body.get("business_type", "internal"), "created_at": now()}
        db.production_pos.docs.append(dict(doc))
        for it in body.get("items") or []:
            db.po_items.docs.append({"id": f"{pid}-{len(db.po_items.docs)}", "po_id": pid,
                                     "po_number": doc["po_number"], **it})
        return {**doc, "created_at": doc["created_at"].isoformat()}     # seperti serialize_doc

    import core.merchandiser as mc
    monkeypatch.setattr(pp, "require_auth", _auth)
    monkeypatch.setattr(pp, "get_db", lambda: db)
    monkeypatch.setattr(pp, "assert_po_action", lambda *a, **k: None)
    monkeypatch.setattr(pp, "create_po_internal", _buat)
    monkeypatch.setattr(mc, "jaga", _jaga)
    monkeypatch.setattr(mc, "model_dari_item", _model)
    return pp


def _dua_sekaligus(pp, body):
    async def _go():
        return await asyncio.gather(pp.create_po(_Req(dict(body))), pp.create_po(_Req(dict(body))),
                                    return_exceptions=True)
    return run(_go())


@pytest.mark.parametrize("kode", ["DA-1896", ""])
def test_klik_ganda_hanya_satu_po(db, monkeypatch, kode):
    pp = _pasang_rute(db, monkeypatch)
    body = {"business_type": "internal", "vendor_id": "v-bambang",
            "items": [_baris(kode, "DA-1201-MCA", 58), _baris(kode, "DA-2204-DST", 52)]}
    hasil = _dua_sekaligus(pp, body)
    galat = [h for h in hasil if isinstance(h, HTTPException)]
    assert len(galat) == 1 and galat[0].status_code == 409
    baru = [p for p in db.production_pos.docs if p["id"].startswith("po") and p["id"][2:].isdigit()]
    assert len(baru) == 1 and baru[0]["sidik_isi"] == ptd.sidik_isi(body, USER)


def test_po_sama_setelah_jendela_lewat_tanpa_kode_boleh(db, monkeypatch):
    pp = _pasang_rute(db, monkeypatch)
    body = {"business_type": "internal", "vendor_id": "v", "items": [_baris("", "S1", 5)]}
    run(pp.create_po(_Req(dict(body))))
    db.production_pos.docs[-1]["created_at"] = now() - timedelta(seconds=ptd.JENDELA_DETIK + 5)
    run(pp.create_po(_Req(dict(body))))
    assert sum(1 for p in db.production_pos.docs if p.get("sidik_isi")) == 2


def test_buat_po_dengan_kode_cutoff_ditolak_tanpa_menulis(db, monkeypatch):
    pp = _pasang_rute(db, monkeypatch)
    jumlah = len(db.production_pos.docs)
    with pytest.raises(HTTPException) as e:
        run(pp.create_po(_Req({"business_type": "internal", "vendor_id": "v",
                                "items": [_baris("DA-1869", "DA-2204-DST", 52)]})))
    assert e.value.status_code == 409 and "PO-INT-0003" in e.value.detail
    assert len(db.production_pos.docs) == jumlah


# ── jalur layar: ubah PO ──────────────────────────────────────────────────────

def test_ubah_po_hanya_kode_baru_yang_diperiksa(db, monkeypatch):
    from routes import production_pos as pp
    import core.po_lock as pl

    async def _auth(_r):
        return dict(USER)

    async def _nop(*a, **k):
        return None
    monkeypatch.setattr(pp, "require_auth", _auth)
    monkeypatch.setattr(pp, "get_db", lambda: db)
    monkeypatch.setattr(pp, "assert_po_action", lambda *a, **k: None)
    monkeypatch.setattr(pp, "log_activity", _nop)
    monkeypatch.setattr(pl, "assert_po_open", _nop)
    db.po_items.docs.append({"id": "a3", "po_id": "po-cut", "po_number": "PO-INT-0003", "serial_number": "DA-1876",
                             "sku": "DA-1201-MCA", "qty": 58})
    # PO lama yang kebetulan sudah bentrok (DA-1869 juga di PO-INT-0003) tetap bisa diubah
    db.production_pos.docs.append({"id": "po-x", "po_number": "PO-MKL-X", "business_type": "maklon",
                                   "status": "Draft"})
    db.po_items.docs.append({"id": "x1", "po_id": "po-x", "po_number": "PO-MKL-X", "serial_number": "DA-1869",
                             "sku": "M1", "qty": 5})
    x1 = {"id": "x1", "serial_number": "DA-1869", "sku": "M1"}     # layar selalu mengirim baris lengkap
    run(pp.update_po("po-x", _Req({"items": [{**x1, "qty": 6}]})))
    assert next(i for i in db.po_items.docs if i["id"] == "x1")["qty"] == 6
    # menambah kode yang sudah dipakai PO lain → ditolak, tidak ada yang tertulis
    jumlah = len(db.po_items.docs)
    with pytest.raises(HTTPException) as e:
        run(pp.update_po("po-x", _Req({"items": [{**x1, "qty": 7},
                                                 {"serial_number": "da-1876", "sku": "M2", "qty": 1}]})))
    assert e.value.status_code == 409 and "DA-1876" in e.value.detail and "PO-INT-0003" in e.value.detail
    assert len(db.po_items.docs) == jumlah and next(i for i in db.po_items.docs if i["id"] == "x1")["qty"] == 6
    # baris kembar (kode + varian sama) juga ditolak saat ubah
    with pytest.raises(HTTPException) as e:
        run(pp.update_po("po-x", _Req({"items": [{**x1, "qty": 6},
                                                 {"serial_number": "DA-1869", "sku": "M1", "qty": 2}]})))
    assert e.value.status_code == 409 and "Baris kembar" in e.value.detail
