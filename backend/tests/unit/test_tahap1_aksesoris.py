"""Tahap 1 Portal Aksesoris (2026-11-06) — cacat yang disetujui owner sebagai bug jelas.

  1. Alur permintaan: /allocate & /deliver dijaga peran (tim aksesoris/gudang + manajemen);
     status hanya berpindah lewat endpoint transisi (POST tidak menerima status sembarang,
     PUT tidak bisa mengubah status — dulu `PUT status=delivered` = "terkirim" tanpa stok keluar).
  3. Dashboard: "Request Pending" = definisi Inbox Approval; "Opname berjalan" dari mesin opname tunggal.
  4. Satuan Master Aksesoris = MATERIAL_UNITS backend (= lib/uom.js), satuan tak dikenal ditolak.
  5. Stok karantina tidak ikut dikeluarkan; HPP rata-rata bergerak tidak dibobot reject belum bernilai.
     Angka (hitung tangan): stok 100 @1.000 + 50 reject karantina belum bernilai, terima 100 @2.000
     → (100×1.000 + 100×2.000) / 200 = 1.500  (dulu (150×1.000 + 100×2.000) / 250 = 1.400).
  6. HPP tidak bisa diubah lewat "Ubah aksesoris" (K12: lewat Set HPP berjurnal); item baru boleh harga awal.
  8. Kartu stok membaca baris mutasi nyata, bukan hanya hasil migrasi.
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
from core import accessory_issue, accessory_stock, accessory_valuation, stock_service  # noqa: E402
import core.doc_number_policy as dnp  # noqa: E402
import routes.dewi_accessory_requests as req_mod  # noqa: E402
import routes.dewi_accessories_dashboard as dash  # noqa: E402
import routes.dewi_accessories_items as items_mod  # noqa: E402
import routes.dewi_accessories_stock as stk  # noqa: E402
from routes.rahaza_inventory_shared import MATERIAL_UNITS  # noqa: E402

T0 = datetime(2026, 11, 6, 2, 0, tzinfo=timezone.utc)
ADMIN_ACC = {"id": "u-acc", "name": "Admin Aksesoris", "role": "admin_aksesoris"}
MANAGER = {"id": "u-mgr", "name": "Manajer", "role": "manager"}
RND = {"id": "u-rnd", "name": "Staf RnD", "role": "rnd_staff"}
OPERATOR = {"id": "u-op", "name": "Operator", "role": "operator"}


def run(coro):
    return asyncio.run(coro)


class QRequest(FakeRequest):
    """FakeRequest + query_params (untuk endpoint yang membaca `request.query_params`)."""

    def __init__(self, body=None, params=None):
        super().__init__(body)
        self.query_params = dict(params or {})


def _req(rid, status, rtype="rnd_sample", **kw):
    return {"id": rid, "request_code": f"REQ-{rid}", "request_type": rtype, "status": status,
            "items": [{"material_id": "m1", "material_code": "ACC-1", "qty": 2, "unit": "pcs"}],
            "created_at": T0, **kw}


# ═════════════════════════ 1. alur permintaan ═════════════════════════
@pytest.fixture
def req_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(req_mod, "get_db", lambda: db)

    async def number(db_, key, *, ctx=None, requested=""):
        return "INT-REQ-UJI-0001"
    monkeypatch.setattr(dnp, "issue_number", number)
    return db


@pytest.mark.parametrize("user", [RND, OPERATOR])
def test_allocate_dan_deliver_ditolak_untuk_peran_di_luar_aksesoris(req_db, user):
    req_db.dewi_accessory_requests.docs = [_req("r1", "submitted"), _req("r2", "allocated")]
    with pytest.raises(HTTPException) as e:
        run(req_mod.allocate_request("r1", {}, user))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        run(req_mod.deliver_request("r2", {}, user))
    assert e.value.status_code == 403
    st = {d["id"]: d["status"] for d in req_db.dewi_accessory_requests.docs}
    assert st == {"r1": "submitted", "r2": "allocated"}


@pytest.mark.parametrize("user", [ADMIN_ACC, MANAGER])
def test_allocate_dan_deliver_boleh_untuk_tim_aksesoris_dan_manajemen(req_db, user, monkeypatch):
    req_db.dewi_accessory_requests.docs = [_req("r1", "submitted")]
    req_db.rahaza_materials.docs = [{"id": "m1", "code": "ACC-1", "name": "Kancing", "type": "accessory",
                                     "active": True, "unit": "pcs", "unit_cost": 100.0}]

    async def usable(db_, mid):
        return 10.0

    async def issue(db_, user_, **kw):     # 2026-11-06 (Tahap 2): sampel R&D kini memotong stok
        return {"material_id": kw["acc_id"], "material_code": "ACC-1", "material_name": "Kancing",
                "qty_issued": kw["qty"], "unit": "pcs", "unit_cost": 100.0, "value": 100.0 * kw["qty"],
                "je": {"posted": True, "je_number": "JE-1"}}
    monkeypatch.setattr(accessory_issue, "_usable_qty", usable)
    monkeypatch.setattr(accessory_issue, "issue_accessory", issue)
    assert run(req_mod.allocate_request("r1", {}, user))["ok"] is True
    out = run(req_mod.deliver_request("r1", {}, user))
    assert out["ok"] is True and out["stock_issued"] is True
    assert req_db.dewi_accessory_requests.docs[0]["status"] == "delivered"


def test_reject_memakai_gerbang_yang_sama(req_db):
    req_db.dewi_accessory_requests.docs = [_req("r1", "submitted")]
    with pytest.raises(HTTPException) as e:
        run(req_mod.reject_request("r1", {"reason": "x"}, RND))
    assert e.value.status_code == 403
    assert run(req_mod.reject_request("r1", {"reason": "x"}, ADMIN_ACC))["ok"] is True


def test_put_tidak_bisa_menandai_terkirim_tanpa_stok_keluar(req_db):
    req_db.dewi_accessory_requests.docs = [_req("r1", "allocated", rtype="internal_issuance")]
    with pytest.raises(HTTPException) as e:
        run(req_mod.update_request("r1", {"status": "delivered"}, ADMIN_ACC))
    assert e.value.status_code == 400
    doc = req_db.dewi_accessory_requests.docs[0]
    assert doc["status"] == "allocated" and not doc.get("stock_issued")


def test_put_mengabaikan_field_alur_kerja_tapi_menyimpan_detail(req_db):
    req_db.dewi_accessory_requests.docs = [_req("r1", "allocated", rtype="internal_issuance")]
    run(req_mod.update_request("r1", {"status": "allocated", "stock_issued": True,
                                      "request_type": "rnd_sample", "delivered_by": "x",
                                      "notes": "ganti catatan"}, ADMIN_ACC))
    doc = req_db.dewi_accessory_requests.docs[0]
    assert doc["notes"] == "ganti catatan"
    assert doc["status"] == "allocated" and doc["request_type"] == "internal_issuance"
    assert "stock_issued" not in doc and "delivered_by" not in doc


@pytest.mark.parametrize("status", ["allocated", "delivered", "rejected", "ngawur"])
def test_buat_permintaan_tidak_bisa_langsung_lewat_tahap(req_db, status):
    with pytest.raises(HTTPException) as e:
        run(req_mod.create_request({"request_type": "internal_issuance", "status": status,
                                    "items": [{"material_id": "m1", "qty": 1}]}, ADMIN_ACC))
    assert e.value.status_code == 400
    assert req_db.dewi_accessory_requests.docs == []


@pytest.mark.parametrize("status,expected", [(None, "draft"), ("submitted", "submitted")])
def test_buat_permintaan_draf_atau_diajukan_tetap_jalan(req_db, status, expected):
    body = {"request_type": "internal_issuance", "items": [{"material_id": "m1", "qty": 1}]}
    if status:
        body["status"] = status
    out = run(req_mod.create_request(body, RND))
    assert out["status"] == expected


# ═════════════════════════ 3. dashboard ═════════════════════════
@pytest.fixture
def dash_db(monkeypatch):
    db = FakeDB()

    async def auth(_req):
        return ADMIN_ACC
    monkeypatch.setattr(dash, "require_auth", auth)
    monkeypatch.setattr(dash, "get_db", lambda: db)
    monkeypatch.setattr(req_mod, "get_db", lambda: db)
    return db


def test_request_pending_sama_dengan_inbox(dash_db):
    dash_db.dewi_accessory_requests.docs = [
        _req("a", "submitted", rtype="internal_issuance"),
        _req("b", "submitted", rtype="rnd_sample"),
        _req("c", "allocated", rtype="internal_issuance"),   # sudah disiapkan → "Perlu Diserahkan"
        _req("d", "draft", rtype="internal_issuance"),
    ]
    out = run(dash.get_dashboard(QRequest()))
    inbox = run(req_mod.list_requests(status="submitted", request_type=None, sample_request_id=None,
                                      style_id=None, divisi=None, vendor_id=None, urgent_only=False,
                                      search=None, limit=200, user=ADMIN_ACC))
    assert out["pending_requests"] == len(inbox) == 2
    assert out["ready_to_deliver"] == 1


def test_opname_berjalan_dari_mesin_opname_tunggal(dash_db):
    from core import opname_engine as eng
    dash_db[eng.LEGACY_ACC].docs = [{"id": "old", "session_no": "OPNAME-0001", "domain": "accessory",
                                     "status": "open", "created_at": T0}]
    assert run(dash.get_dashboard(QRequest()))["active_opname"] is None   # arsip tidak dihitung
    dash_db[eng.SESS].docs = [
        {"id": "s-fg", "session_no": "OPN-202611-0001", "engine": eng.ENGINE, "status": "counting",
         "kinds": ["fg"], "source": "gudang", "created_at": T0},
        {"id": "s-acc", "session_no": "OPN-202611-0002", "engine": eng.ENGINE, "status": "counting",
         "kinds": ["aksesoris"], "source": "aksesoris", "created_at": T0},
    ]
    assert run(dash.get_dashboard(QRequest()))["active_opname"] == "OPN-202611-0002"


# ═════════════════════════ 4. satuan ═════════════════════════
FE = BACKEND.parent / "frontend" / "src"


@pytest.mark.skipif(not FE.is_dir(), reason="frontend tidak tersedia")
def test_daftar_satuan_frontend_sama_dengan_backend():
    src = (FE / "lib" / "uom.js").read_text(encoding="utf-8")
    block = re.search(r"export const MATERIAL_UNITS = \[(.*?)\];", src, re.S).group(1)
    assert re.findall(r"'([^']+)'", block) == list(MATERIAL_UNITS)
    acc_src = (FE / "components" / "erp" / "AccessoryModule.jsx").read_text(encoding="utf-8")
    assert "'lembar'" not in acc_src and "MATERIAL_UNITS" in acc_src


@pytest.fixture
def items_db(monkeypatch):
    db = FakeDB()

    async def auth(_req):
        return ADMIN_ACC
    monkeypatch.setattr(items_mod, "require_auth", auth)
    monkeypatch.setattr(items_mod, "get_db", lambda: db)
    return db


def _body(resp):
    return json.loads(resp.body) if hasattr(resp, "body") else resp


# 2026-11-06 (pola P8): ejaan resmi = data master material ("roll"/"pack"); dulu "roll" → "rol".
@pytest.mark.parametrize("unit,saved", [("gross", "gross"), ("pak", "pack"), ("roll", "roll"), ("rol", "roll"),
                                        ("Buah", "pcs")])
def test_satuan_sah_tersimpan(items_db, unit, saved):
    out = _body(run(items_mod.create_item(FakeRequest({"code": "ACC-U1", "name": "Kancing", "unit": unit}))))
    assert out["unit"] == saved


def test_satuan_tak_dikenal_ditolak_bukan_jadi_pcs(items_db):
    with pytest.raises(HTTPException) as e:
        run(items_mod.create_item(FakeRequest({"code": "ACC-U2", "name": "Kain keras", "unit": "lembar"})))
    assert e.value.status_code == 400 and "lembar" in e.value.detail
    assert items_db.rahaza_materials.docs == []


def test_satuan_lama_yang_tidak_diubah_tetap(items_db):
    items_db.rahaza_materials.docs = [{"id": "i1", "code": "ACC-9", "name": "Lama", "type": "accessory",
                                       "active": True, "unit": "lembar", "unit_cost": 500.0}]
    out = run(items_mod.update_item("i1", FakeRequest({"name": "Lama baru", "unit": "lembar"})))
    assert out["unit"] == "lembar" and out["name"] == "Lama baru"


# ═════════════════════════ 6. HPP lewat Set HPP saja ═════════════════════════
def test_ubah_item_tidak_bisa_mengubah_hpp(items_db):
    items_db.rahaza_materials.docs = [{"id": "i1", "code": "ACC-1", "name": "Kancing", "type": "accessory",
                                       "active": True, "unit": "pcs", "unit_cost": 1000.0}]
    with pytest.raises(HTTPException) as e:
        run(items_mod.update_item("i1", FakeRequest({"unit_cost": 1500})))
    assert e.value.status_code == 400 and "Set HPP" in e.value.detail
    with pytest.raises(HTTPException):
        run(items_mod.update_item("i1", FakeRequest({"hpp": 0})))
    assert items_db.rahaza_materials.docs[0]["unit_cost"] == 1000.0
    assert items_db.rahaza_material_cost_history.docs == []


def test_ubah_item_dengan_hpp_sama_tetap_tersimpan(items_db):
    items_db.rahaza_materials.docs = [{"id": "i1", "code": "ACC-1", "name": "Kancing", "type": "accessory",
                                       "active": True, "unit": "pcs", "unit_cost": 1000.0}]
    out = run(items_mod.update_item("i1", FakeRequest({"name": "Kancing 12 mm", "unit_cost": 1000})))
    assert out["name"] == "Kancing 12 mm" and out["unit_cost"] == 1000.0


def test_item_baru_boleh_harga_awal(items_db):
    out = _body(run(items_mod.create_item(FakeRequest({"code": "ACC-N1", "name": "Label", "unit": "pcs",
                                                       "unit_cost": 750}))))
    assert out["unit_cost"] == 750.0


# ═════════════════════════ 5. karantina ═════════════════════════
def _qdb():
    db = FakeDB()
    db.rahaza_locations.docs = [
        {"id": "acc", "code": "ZNA-AKSESORIS", "name": "Area Aksesoris", "storage_role": "aksesoris"},
        {"id": "qrt", "code": "ZNA-KARANTINA", "name": "Area Karantina QC", "role": "karantina",
         "blocked": True},
    ]
    db.rahaza_materials.docs = [{"id": "m1", "code": "ACC-1", "name": "Kancing", "type": "accessory",
                                 "active": True, "unit": "pcs", "unit_cost": 1000.0}]
    db[stock_service.STOCK].docs = [
        {"id": "s-acc", "material_id": "m1", "location_id": "acc", "qty": 5.0},
        {"id": "s-qrt", "material_id": "m1", "location_id": "qrt", "qty": 10.0, "reserved_quantity": 10.0,
         "quarantine": True, "blocked": True},
    ]
    return db


def test_stok_karantina_tidak_dihitung_bisa_dipakai():
    db = _qdb()
    assert run(accessory_stock.stock_qty(db, "m1")) == 15.0          # on-hand fisik tetap utuh
    assert run(accessory_stock.usable_qty(db, "m1")) == 5.0
    with pytest.raises(accessory_issue.IssueError) as e:
        run(accessory_issue.check_availability(db, [{"material_id": "m1", "qty": 8}]))
    assert "bisa dipakai 5" in str(e.value)


def test_pengeluaran_tidak_memotong_lokasi_karantina(monkeypatch):
    db = _qdb()
    cut = []

    async def issue(mid, loc, qty, **kw):
        cut.append((loc, qty))

    async def issue_row(stock_id, qty, **kw):
        cut.append((stock_id, qty))
    monkeypatch.setattr(stock_service, "issue", issue)
    monkeypatch.setattr(stock_service, "issue_row", issue_row)
    plan = run(accessory_stock.issue_across_locations(db, "m1", 5, preferred_location_id="qrt"))
    assert plan == [{"location_id": "acc", "qty": 5.0}] and cut == [("acc", 5.0)]
    with pytest.raises(stock_service.InsufficientStock):
        run(accessory_stock.issue_across_locations(db, "m1", 6))


def test_baris_karantina_dikenali_dari_penanda_baris_walau_lokasinya_tanpa_penanda():
    db = _qdb()
    db.rahaza_locations.docs = [db.rahaza_locations.docs[0]]           # zona karantina kanonik tanpa dok lokasi
    db[stock_service.STOCK].docs[1]["location_id"] = "zn-qrt"
    assert run(accessory_stock.usable_qty(db, "m1")) == 5.0


def _wac_db():
    db = _qdb()
    db[stock_service.STOCK].docs = [
        {"id": "s-acc", "material_id": "m1", "location_id": "acc", "qty": 100.0},
        {"id": "s-qrt", "material_id": "m1", "location_id": "qrt", "qty": 50.0, "reserved_quantity": 50.0,
         "quarantine": True, "blocked": True},
    ]
    db.wh_quarantine_items.docs = [{"id": "q1", "material_id": "m1", "status": "open", "remaining_qty": 50.0,
                                    "valued": False, "valued_qty": 0.0}]
    return db


def test_rata_rata_bergerak_tanpa_reject_karantina_belum_bernilai():
    db = _wac_db()
    res = run(accessory_valuation.apply_receipt_cost(db, "m1", 100, 2000))
    assert res["qty_before"] == 100.0
    assert res["new_unit_cost"] == pytest.approx(1500.0)              # dulu 1.400


def test_terima_aksesoris_memakai_qty_bernilai(monkeypatch):
    db = _wac_db()

    async def auth(_req):
        # 2026-11-06 (Tahap 2): hanya Keuangan yang boleh mengetik harga penerimaan
        return {"id": "u-fin", "name": "Keuangan", "role": "accounting"}

    async def add(*a, **k):
        return None

    async def post(db_, mv, user):
        return {"ok": True, "je_id": "je1", "je_number": "JE-UJI"}
    monkeypatch.setattr(stk, "require_auth", auth)
    monkeypatch.setattr(stk, "get_db", lambda: db)
    monkeypatch.setattr(stock_service, "add", add)
    monkeypatch.setattr(stk, "post_inventory_receive", post)
    out = run(stk.receive_stock(FakeRequest({"acc_id": "m1", "qty": 100, "unit_cost": 2000})))
    assert out["unit_cost"] == pytest.approx(1500.0)
    assert db.rahaza_materials.docs[0]["unit_cost"] == pytest.approx(1500.0)


# ═════════════════════════ 8. kartu stok ═════════════════════════
def test_kartu_stok_membaca_mutasi_nyata(monkeypatch):
    db = FakeDB()
    db.rahaza_materials.docs = [{"id": "m1", "type": "accessory", "code": "ACC-1"},
                                {"id": "kain", "type": "fabric", "code": "KN-1"}]
    db.dewi_accessory_requests.docs = [{"id": "r1", "request_code": "INT-REQ-1", "divisi": "QC"}]
    db.rahaza_material_movements.docs = [
        {"id": "mig", "material_id": "m1", "type": "receive", "legacy_movement_type": "IN",
         "domain": "accessory", "created_at": "2026-08-01T00:00:00+00:00"},
        {"id": "real", "material_id": "m1", "movement_type": "issue", "qty_signed": -2,
         "reference_type": "accessory_request", "reference_id": "r1", "created_at": "2026-11-05T00:00:00+00:00"},
        {"id": "gr", "material_id": "m1", "type": "receive", "created_at": "2026-11-04T00:00:00+00:00"},
        {"id": "fab", "material_id": "kain", "type": "receive", "created_at": "2026-11-04T00:00:00+00:00"},
    ]

    async def auth(_req):
        return ADMIN_ACC
    monkeypatch.setattr(stk, "require_auth", auth)
    monkeypatch.setattr(stk, "get_db", lambda: db)
    rows = run(stk.get_movements(QRequest()))
    assert [r["id"] for r in rows] == ["real", "gr", "mig"]            # kain tidak ikut
    assert rows[0]["related_request"]["request_number"] == "INT-REQ-1"
    issues = run(stk.get_movements(QRequest(params={"movement_type": "issue"})))
    assert [r["id"] for r in issues] == ["real"]
    one = run(stk.get_movements(QRequest(params={"acc_id": "m1", "movement_type": "receive"})))
    assert sorted(r["id"] for r in one) == ["gr", "mig"]
