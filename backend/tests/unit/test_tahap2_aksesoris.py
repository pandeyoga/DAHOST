"""Tahap 2 Portal Aksesoris (2026-11-06) — keputusan owner.

  1. Akun beban per divisi pemohon lewat profil posting `inventory_issue` (peran baru, bawaan:
     Kantor/SDM/Gudang 6-2400 · Marketing 6-1130 · Lainnya 6-2900 · produksi 1-1403); satu daftar divisi.
  2. Pengeluaran ber-PO mengikuti jenis PO: maklon 5-4100 (K42), internal WIP; po_id ikut ke kartu stok.
  3. Satu keluar per kebutuhan PO: Kirim Material CMT mengurangkan pengeluaran lewat permintaan, dan
     sebaliknya; kelebihan dari kebutuhan PO wajib beralasan.
  4. "Buat Permintaan (N kurang)" → Permintaan Pengadaan untuk kekurangan aksesoris MILIK DA saja.
  5. Sampel R&D / tambahan / pengganti vendor memotong stok + berjurnal.
  6. PR aksesoris lewat Pengadaan; "Terima Barang" tidak menambah stok; migrasi PR terbuka.
  7. Harga Terima Stok manual hanya diubah Keuangan; lainnya harga PO terakhir / HPP master.
  8. Kolom Kategori = nama kategori (bukan UUID); id mentah lain diganti nama.
  9. PUT permintaan mempertahankan material_id.

Angka (hitung tangan) ada di tiap uji.
"""
import asyncio
import importlib.util
import json
import os
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
from core import accessory_issue as ai  # noqa: E402
from core import accessory_procurement as ap  # noqa: E402
from core import coa_bindings as cb  # noqa: E402
from core import material_issue_engine as mie  # noqa: E402
from core import stock_service  # noqa: E402
import routes.dewi_accessories_items as items_mod  # noqa: E402
import routes.dewi_accessories_purchase as pur  # noqa: E402
import routes.dewi_accessories_stock as stk  # noqa: E402
import routes.dewi_accessory_requests as req_mod  # noqa: E402
import routes.dewi_procurement as dp  # noqa: E402
import routes.rahaza_inventory_shared as ris  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402

T0 = datetime(2026, 11, 6, 2, 0, tzinfo=timezone.utc)
DEFAULT_MAP = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}
ADMIN_ACC = {"id": "u-acc", "name": "Admin Aksesoris", "role": "admin_aksesoris"}
FIN = {"id": "u-fin", "name": "Keuangan", "role": "accounting"}
STAF = {"id": "u-staf", "name": "Staf", "role": "staff"}


def run(coro):
    return asyncio.run(coro)


class QRequest(FakeRequest):
    def __init__(self, body=None, params=None):
        super().__init__(body)
        self.query_params = dict(params or {})


# ───────────────────────── perlengkapan bersama ─────────────────────────
@pytest.fixture
def posting(monkeypatch):
    """Mesin posting palsu dengan profil BAWAAN — baris jurnal dicatat."""
    jes = []

    async def mapping(db, key):
        return dict(DEFAULT_MAP.get(key, {}))

    async def none(*a, **k):
        return None

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        jes.append({"memo": memo, "ref": ref, "lines": lines})
        return {"ok": True, "je_id": f"je-{len(jes)}", "je_number": f"JE-{len(jes)}"}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)

    class P:
        pass
    p = P()
    p.jes = jes
    p.lines = lambda i=-1: [(ln["account_code"], round(ln["debit"], 2), round(ln["credit"], 2))
                            for ln in jes[i]["lines"]]
    return p


def _mat(mid="ACC1", code="KCG", cost=2000.0):
    return {"id": mid, "code": code, "name": f"Aksesoris {code}", "type": "accessory", "active": True,
            "unit": "pcs", "unit_cost": cost}


@pytest.fixture
def stock(monkeypatch):
    """Stok aksesoris palsu {material_id: qty} untuk mesin pengeluaran aksesoris (E1)."""
    qty = {}

    async def usable(db, mid):
        return float(qty.get(mid, 0))

    async def add(db, mid, loc, q):
        qty[mid] = float(qty.get(mid, 0)) + q

    async def loc(db):
        return "LOC-ACC"
    monkeypatch.setattr(ai, "_usable_qty", usable)
    monkeypatch.setattr(ai, "_stock_qty", usable)
    monkeypatch.setattr(ai, "_add_stock", add)
    monkeypatch.setattr(ai, "_get_accessory_location_id", loc)
    monkeypatch.setattr(stk, "_get_accessory_location_id", loc)
    return qty


def _issue_db(**po):
    db = FakeDB()
    db.rahaza_materials.docs = [_mat()]
    if po:
        db.production_pos.docs = [{"id": "PO1", "po_number": "PO-001", **po}]
    return db


# ═════════════════════════ 1. akun per divisi ═════════════════════════
def test_profil_inventory_issue_punya_peran_per_divisi_dengan_bawaan_owner():
    m = DEFAULT_MAP["inventory_issue"]
    assert m["debit_wip"] == "1-1403" and m["debit_maklon_material"] == "5-4100"
    assert m["debit_accessory_office"] == "6-2400"
    assert m["debit_accessory_marketing"] == "6-1130"
    assert m["debit_accessory_other"] == "6-2900"
    assert m["debit_accessory_rnd_sample"] == "6-2900"
    for role in ai.PROFILE_ROLES["inventory_issue"].values():
        assert role in m and role in pp.ROLE_LABELS
    cons = cb.role_consumers()
    assert cons["inventory_issue.debit_accessory_office"][0]["reads_profile"] is True
    assert cons["inventory_issue.debit_accessory_office"][0]["code"] == "6-2400"


@pytest.mark.parametrize("divisi,target", [
    ("Produksi", "wip"), ("cutting", "wip"), ("CMT", "wip"), ("QC", "wip"), ("Packing", "wip"),
    ("Kantor", "kantor"), ("SDM", "kantor"), ("Gudang", "kantor"),
    ("Marketing", "pemasaran"), ("Lainnya", "lainnya"),
])
def test_divisi_menentukan_tujuan_biaya(divisi, target):
    assert ai.division_cost_target(divisi) == target
    assert run(ai.resolve_cost_target(FakeDB(), divisi=divisi))["cost_target"] == target


def test_divisi_tidak_dikenal_ditolak_bukan_diam_diam_wip():
    with pytest.raises(ai.IssueError) as e:
        run(ai.resolve_cost_target(FakeDB(), divisi="Gudang Belakang"))
    assert "Pilih divisi" in str(e.value)


@pytest.mark.parametrize("target,code", [("kantor", "6-2400"), ("pemasaran", "6-1130"), ("lainnya", "6-2900"),
                                         ("sampel_rnd", "6-2900"), ("wip", "1-1403"), ("maklon", "5-4100"),
                                         (None, "1-1403")])
def test_jurnal_pengeluaran_aksesoris_per_tujuan_biaya(posting, target, code):
    db = _issue_db()
    mv = {"id": "mv1", "material_id": "ACC1", "qty": -3, "unit_cost": 2000, "divisi": "Kantor"}
    if target:
        mv["cost_target"] = target
    res = run(rp.post_accessory_issue(db, mv, FIN))
    assert res["ok"] is True
    assert posting.lines() == [(code, 6000.0, 0), ("1-1402", 0, 6000.0)]   # 3 × 2.000


def test_peran_kosong_menolak_jurnal_dengan_pesan_jelas(monkeypatch):
    async def mapping(db, key):
        m = dict(DEFAULT_MAP.get(key, {}))
        m.pop("debit_accessory_marketing")
        return m
    monkeypatch.setattr(rp, "get_mapping", mapping)
    res = run(rp.post_accessory_issue(_issue_db(), {"id": "mv1", "material_id": "ACC1", "qty": -1,
                                                    "unit_cost": 100, "cost_target": "pemasaran"}, FIN))
    assert res["ok"] is False and "debit_accessory_marketing" in res["error"]


def test_daftar_divisi_satu_sumber_dengan_akun(monkeypatch):
    db = FakeDB()
    db.rahaza_coa_accounts.docs = [{"code": "6-2400", "name": "ATK & Supplies", "active": True}]

    async def auth(_r):
        return ADMIN_ACC
    monkeypatch.setattr(stk, "require_auth", auth)
    monkeypatch.setattr(stk, "get_db", lambda: db)
    rows = run(stk.list_divisions(QRequest()))
    assert [r["value"] for r in rows] == list(ai.DIVISION_NAMES)
    kantor = next(r for r in rows if r["value"] == "Kantor")
    assert kantor["account_code"] == "6-2400" and kantor["account_name"] == "ATK & Supplies"
    assert stk.DIVISI_OPTIONS == list(ai.DIVISION_NAMES)


def test_keluar_manual_wajib_divisi_dan_dijurnal_ke_akun_divisi(monkeypatch, posting, stock):
    db = _issue_db()
    stock["ACC1"] = 10

    async def auth(_r):
        return ADMIN_ACC
    monkeypatch.setattr(stk, "require_auth", auth)
    monkeypatch.setattr(stk, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(stk.issue_stock(FakeRequest({"acc_id": "ACC1", "qty": 2})))
    assert e.value.status_code == 400 and stock["ACC1"] == 10
    out = json.loads(run(stk.issue_stock(FakeRequest({"acc_id": "ACC1", "qty": 2, "divisi": "Marketing"}))).body)
    assert out["cost_target"] == "pemasaran" and stock["ACC1"] == 8
    assert posting.lines() == [("6-1130", 4000.0, 0), ("1-1402", 0, 4000.0)]
    mv = db.rahaza_material_movements.docs[-1]
    assert mv["divisi"] == "Marketing" and mv["cost_target"] == "pemasaran"


# ═════════════════════════ 2. ber-PO mengikuti jenis PO ═════════════════════════
@pytest.mark.parametrize("bt,code", [("maklon", "5-4100"), ("internal", "1-1403")])
def test_pengeluaran_ber_po_mengikuti_jenis_po_dan_membawa_po(posting, stock, bt, code):
    db = _issue_db(business_type=bt)
    db.po_accessories.docs = [{"po_id": "PO1", "accessory_id": "ACC1", "qty_needed": 50,
                               "ownership": "cv_da_stock"}]
    stock["ACC1"] = 20
    tgt = run(ai.resolve_cost_target(db, divisi="Marketing", po_id="PO1"))   # PO menang atas divisi
    res = run(ai.issue_accessory(db, ADMIN_ACC, acc_id="ACC1", qty=5, target=tgt, guard_po=True))
    assert res["cost_target"] == ("maklon" if bt == "maklon" else "wip")
    mv = db.rahaza_material_movements.docs[-1]
    assert mv["po_id"] == "PO1" and mv["po_number"] == "PO-001"
    assert posting.lines() == [(code, 10000.0, 0), ("1-1402", 0, 10000.0)]   # 5 × 2.000
    assert "PO PO-001" in posting.jes[-1]["memo"]


# ═════════════════════════ 3. satu keluar per kebutuhan PO ═════════════════════════
def test_maklon_kirim_material_mengurangkan_pengeluaran_lewat_permintaan(monkeypatch):
    d = FakeDB()
    d.rahaza_materials.docs = [_mat()]
    d.rahaza_material_stock.docs = [{"material_id": "ACC1", "location_id": "LOC-A", "qty": 500}]
    d.dewi_maklon_bom.docs = [{"po_id": "PO-M", "materials": [
        {"material_name": "Kancing", "ownership": "cv_da_stock", "material_id": "ACC1", "qty_per_pcs": 1,
         "unit": "pcs"}]}]
    d.vendor_shipments.docs = [{"id": "SJ1", "po_id": "PO-M"}]
    d.vendor_shipment_items.docs = [{"shipment_id": "SJ1", "qty_sent": 100}]
    # permintaan aksesoris ber-PO sudah mengeluarkan 60 kancing
    d.rahaza_material_movements.docs = [{"id": "e1", "material_id": "ACC1", "movement_type": "issue",
                                         "qty_signed": -60, "qty": -60, "po_id": "PO-M"}]

    async def fake_issue(db, mi, user, **kw):
        mi = {**mi, "status": "issued", "items": [{**it, "qty_issued": it["qty_required"]} for it in mi["items"]]}
        await db.rahaza_material_issues.update_one({"id": mi["id"]}, {"$set": mi})
        return mi

    async def mino(db, *a, **k):
        return "MI-1"
    monkeypatch.setattr(mie, "issue_material_issue", fake_issue)
    monkeypatch.setattr(ris, "_gen_mi_number", mino)
    res = run(mie.issue_for_maklon_shipment(d, {"id": "SJ1", "po_id": "PO-M", "shipment_number": "SJ-1"},
                                            [{"qty_sent": 100}], ADMIN_ACC))
    # butuh 1 × 100 = 100, sudah keluar lewat permintaan 60 → MI 40 (dulu 100 → total keluar 160)
    assert [(it["material_id"], it["qty_required"]) for it in res["mi"]["items"]] == [("ACC1", 40.0)]


def _internal_ship_db(monkeypatch, credit_qty):
    d = FakeDB()
    d.rahaza_materials.docs = [_mat()]
    d.rahaza_material_stock.docs = [{"material_id": "ACC1", "location_id": "LOC-A", "qty": 500}]
    d.rahaza_material_movements.docs = [{"id": "e1", "material_id": "ACC1", "movement_type": "issue",
                                         "qty_signed": -credit_qty, "po_id": "PO-I"}]
    calls = []

    async def need(db, lines):
        q = sum(float(x["qty"]) for x in lines)
        return {"KCG": {"name": "Kancing", "unit": "pcs", "type": "accessory", "qty": q}}, [], int(q)

    async def neg(db):
        return False

    async def fake_issue(db, mi, user, **kw):
        calls.append(mi["items"])
        return {**mi, "status": "issued"}

    async def mino(db, *a, **k):
        return f"MI-{len(calls) + 1}"
    from core import negative_stock
    monkeypatch.setattr(mie, "bom_need_for_lines", need)
    monkeypatch.setattr(negative_stock, "allowed", neg)
    monkeypatch.setattr(mie, "issue_material_issue", fake_issue)
    monkeypatch.setattr(ris, "_gen_mi_number", mino)
    return d, calls


def _ship(d, sid, qty):
    d.vendor_shipments.docs.append({"id": sid, "po_id": "PO-I"})
    return run(mie.issue_for_vendor_shipment(d, {"id": sid, "po_id": "PO-I", "shipment_number": sid},
                                             [{"po_item_id": "pi1", "qty_sent": qty}], ADMIN_ACC))


def test_internal_kirim_material_memakai_pengeluaran_permintaan_sekali_saja(monkeypatch):
    d, calls = _internal_ship_db(monkeypatch, 60)
    _ship(d, "SJ1", 100)                     # butuh 100, sudah keluar 60 → 40
    assert [(i["material_id"], i["qty_required"], i["offset_request_qty"]) for i in calls[0]] == [("ACC1", 40.0, 60.0)]
    _ship(d, "SJ2", 100)                     # jatah permintaan sudah terpakai → 100 penuh
    assert [(i["material_id"], i["qty_required"]) for i in calls[1]] == [("ACC1", 100.0)]
    sj1 = next(s for s in d.vendor_shipments.docs if s["id"] == "SJ1")
    assert sj1["accessory_request_offsets"] == [{"material_id": "ACC1", "qty": 60.0}]


def test_internal_kirim_material_tanpa_mi_bila_seluruhnya_sudah_keluar(monkeypatch):
    d, calls = _internal_ship_db(monkeypatch, 150)
    res = _ship(d, "SJ1", 100)
    assert res["skipped"] is True and res["mi"] is None and calls == []
    again = run(mie.issue_for_vendor_shipment(d, {"id": "SJ1", "po_id": "PO-I"}, [{"po_item_id": "pi1",
                                                                                  "qty_sent": 100}], ADMIN_ACC))
    assert again["already"] is True and calls == []                       # idempoten
    _ship(d, "SJ2", 100)                                                  # sisa jatah 50 → MI 50
    assert [(i["material_id"], i["qty_required"]) for i in calls[0]] == [("ACC1", 50.0)]


@pytest.fixture
def req_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(req_mod, "get_db", lambda: db)
    return db


def _po_req(rid="r1", rtype="internal_issuance", qty=40, **kw):
    return {"id": rid, "request_code": f"INT-{rid}", "request_type": rtype, "status": "allocated",
            "po_id": "PO1", "po_number": "PO-001", "divisi": "Produksi", "created_at": T0,
            "items": [{"material_id": "ACC1", "material_code": "KCG", "qty": qty, "unit": "pcs"}], **kw}


def test_permintaan_ber_po_melebihi_kebutuhan_wajib_alasan(req_db, posting, stock):
    req_db.rahaza_materials.docs = [_mat()]
    req_db.production_pos.docs = [{"id": "PO1", "po_number": "PO-001", "business_type": "internal"}]
    req_db.po_accessories.docs = [{"po_id": "PO1", "accessory_id": "ACC1", "qty_needed": 100}]
    # Kirim Material CMT sudah mengeluarkan seluruh kebutuhan (100)
    req_db.rahaza_material_issues.docs = [{"id": "MI1", "production_po_id": "PO1", "status": "issued",
                                           "items": [{"material_id": "ACC1", "qty_issued": 100}]}]
    req_db.dewi_accessory_requests.docs = [_po_req()]
    stock["ACC1"] = 200
    with pytest.raises(HTTPException) as e:
        run(req_mod.deliver_request("r1", {}, ADMIN_ACC))
    assert e.value.status_code == 400 and e.value.detail["code"] == "over_issue"
    assert e.value.detail["lines"][0]["need"] == 100 and e.value.detail["lines"][0]["over"] == 40
    assert stock["ACC1"] == 200 and not req_db.dewi_accessory_requests.docs[0].get("delivering")
    out = run(req_mod.deliver_request("r1", {"over_issue_reason": "Ganti kancing cacat"}, ADMIN_ACC))
    assert out["stock_issued"] is True and stock["ACC1"] == 160
    doc = req_db.dewi_accessory_requests.docs[0]
    assert doc["over_issue_reason"] == "Ganti kancing cacat" and doc["issue_linked_po"] is True
    mv = req_db.rahaza_material_movements.docs[-1]
    assert mv["po_id"] == "PO1" and mv["over_issue_reason"] == "Ganti kancing cacat"
    # total keluar untuk PO = 100 (MI) + 40 (permintaan) — dihitung SEKALI (tanpa dobel dokumen lama)
    assert run(ai.po_issued_by_material(req_db, "PO1")) == {"ACC1": 140.0}


def test_permintaan_ber_po_dalam_kebutuhan_tidak_butuh_alasan(req_db, posting, stock):
    req_db.rahaza_materials.docs = [_mat()]
    req_db.production_pos.docs = [{"id": "PO1", "po_number": "PO-001", "business_type": "maklon"}]
    req_db.po_accessories.docs = [{"po_id": "PO1", "accessory_id": "ACC1", "qty_needed": 100,
                                   "ownership": "cv_da_stock"}]
    req_db.dewi_accessory_requests.docs = [_po_req(qty=30)]
    stock["ACC1"] = 50
    out = run(req_mod.deliver_request("r1", {}, ADMIN_ACC))
    assert out["cost_target"] == "maklon" and out["over_issue_lines"] == []
    assert posting.lines() == [("5-4100", 60000.0, 0), ("1-1402", 0, 60000.0)]   # 30 × 2.000


def test_permintaan_lama_ber_po_tetap_dihitung_sudah_keluar():
    db = FakeDB()
    db.dewi_accessory_requests.docs = [{"id": "old", "po_id": "PO1", "stock_issued": True,
                                        "stock_issue_results": [{"material_id": "ACC1", "qty": 25}]}]
    assert run(ai.request_issued_for_po(db, "PO1")) == {"ACC1": 25.0}


# ═════════════════════════ 4. kekurangan PO → Permintaan Pengadaan ═════════════════════════
@pytest.fixture
def pr_numbers(monkeypatch):
    n = {"i": 0}

    async def number(db_, key, *, ctx=None, requested=""):
        n["i"] += 1
        return f"PR-UJI-{n['i']:03d}"
    monkeypatch.setattr(dp, "issue_number", number)
    return n


def _shortage_db():
    db = FakeDB()
    db.rahaza_materials.docs = [_mat("ACC1", "KCG", 2000), _mat("ACC2", "LBL", 500), _mat("ACC3", "RSL", 300)]
    db.production_pos.docs = [{"id": "PO1", "po_number": "PO-M01", "business_type": "maklon"}]
    db.po_accessories.docs = [
        {"po_id": "PO1", "accessory_id": "ACC1", "qty_needed": 100, "ownership": "cv_da_stock"},
        {"po_id": "PO1", "accessory_id": "ACC2", "qty_needed": 80, "ownership": "client_provided"},
        {"po_id": "PO1", "accessory_id": "ACC3", "qty_needed": 10, "ownership": "cv_da_stock"},
    ]
    db[stock_service.STOCK].docs = [
        {"material_id": "ACC1", "location_id": "L", "qty": 30.0},
        {"material_id": "ACC3", "location_id": "L", "qty": 50.0},
    ]
    db.rahaza_material_issues.docs = [{"id": "MI1", "production_po_id": "PO1", "status": "issued",
                                       "items": [{"material_id": "ACC1", "qty_issued": 20}]}]
    return db


def test_kebutuhan_po_hanya_aksesoris_milik_da_yang_dihitung_kurang():
    db = _shortage_db()
    req = run(ap.po_requirements(db, db.production_pos.docs[0]))
    by = {r["material_id"]: r for r in req["rows"]}
    # ACC1: butuh 100 − sudah keluar 20 = 80, tersedia 30 → kurang 50
    assert (by["ACC1"]["issued"], by["ACC1"]["remaining"], by["ACC1"]["shortage"]) == (20.0, 80.0, 50.0)
    assert by["ACC2"]["status"] == "client" and by["ACC2"]["shortage"] == 0     # disediakan klien
    assert by["ACC3"]["status"] == "ok"
    assert req["summary"]["shortage_lines"] == 1 and req["summary"]["client_lines"] == 1


def test_ajukan_pembelian_membuat_pr_pengadaan_tanpa_memotong_stok(pr_numbers):
    db = _shortage_db()
    res = run(ap.create_po_shortage_pr(db, db.production_pos.docs[0], ADMIN_ACC, {}))
    pr = db.dewi_procurement_requests.docs[0]
    assert pr["origin"] == ap.ORIGIN_PO_SHORTAGE and pr["production_po_id"] == "PO1"
    assert pr["status"] == "submitted" and pr["approval_steps"][0]["action"] == "submitted"
    assert [(i["material_id"], i["qty"], i["estimated_price"]) for i in pr["items"]] == [("ACC1", 50.0, 2000.0)]
    assert res["lines"] == 1 and res["lines_skipped_client"] == 1
    assert db.dewi_accessory_requests.docs == [] and db.rahaza_material_movements.docs == []
    with pytest.raises(ValueError) as e:                                   # tidak dobel
        run(ap.create_po_shortage_pr(db, db.production_pos.docs[0], ADMIN_ACC, {}))
    assert "PR-UJI-001" in str(e.value)


def test_endpoint_buat_permintaan_tidak_lagi_membuat_pengeluaran():
    src = (BACKEND / "routes" / "production_pos.py").read_text(encoding="utf-8")
    blk = src[src.index('accessory-requirements/create-request")'):src.index('@router.post("/production-pos/{po_id}/close")')]
    assert "create_po_shortage_pr" in blk and "dewi_accessory_requests.insert_one" not in blk


# ═════════════════════════ 5. sampel R&D / vendor memotong stok ═════════════════════════
@pytest.mark.parametrize("rtype,po,code", [
    ("rnd_sample", None, "6-2900"),
    ("vendor_additional", "maklon", "5-4100"),
    ("vendor_replacement", "internal", "1-1403"),
])
def test_serah_sampel_dan_vendor_memotong_stok_dan_berjurnal(req_db, posting, stock, rtype, po, code):
    req_db.rahaza_materials.docs = [_mat()]
    doc = {"id": "r1", "request_code": "R-1", "request_type": rtype, "status": "allocated", "created_at": T0,
           "notes": "Pengganti barang cacat",
           "items": [{"material_id": "ACC1", "material_code": "KCG", "qty": 4, "unit": "pcs"}]}
    if po:
        req_db.production_pos.docs = [{"id": "PO1", "po_number": "PO-001", "business_type": po}]
        doc.update(po_id="PO1", po_number="PO-001")
    req_db.dewi_accessory_requests.docs = [doc]
    stock["ACC1"] = 10
    out = run(req_mod.deliver_request("r1", {}, ADMIN_ACC))
    assert out["stock_issued"] is True and stock["ACC1"] == 6
    assert posting.lines() == [(code, 8000.0, 0), ("1-1402", 0, 8000.0)]      # 4 × 2.000
    if po:   # vendor tanpa kebutuhan PO → kelebihan, alasan = alasan permintaannya
        assert req_db.dewi_accessory_requests.docs[0]["over_issue_reason"] == "Pengganti barang cacat"


def test_sampel_rnd_tanpa_master_dipilihkan_saat_serah(req_db, posting, stock):
    req_db.rahaza_materials.docs = [_mat()]
    req_db.dewi_accessory_requests.docs = [{
        "id": "r1", "request_code": "R-1", "request_type": "rnd_sample", "status": "allocated",
        "items": [{"material_id": "", "material_code": "", "material_name": "kancing kayu", "qty": 2}]}]
    stock["ACC1"] = 5
    with pytest.raises(HTTPException) as e:
        run(req_mod.deliver_request("r1", {}, ADMIN_ACC))
    assert e.value.status_code == 400 and stock["ACC1"] == 5
    out = run(req_mod.deliver_request("r1", {"item_links": [{"index": 0, "material_id": "ACC1"}]}, ADMIN_ACC))
    assert out["stock_issued"] is True and stock["ACC1"] == 3
    assert req_db.dewi_accessory_requests.docs[0]["items"][0]["material_id"] == "ACC1"


def test_serah_ganda_tidak_memotong_dua_kali(req_db, posting, stock):
    req_db.rahaza_materials.docs = [_mat()]
    req_db.dewi_accessory_requests.docs = [{
        "id": "r1", "request_code": "R-1", "request_type": "internal_issuance", "divisi": "Kantor",
        "status": "allocated", "delivering": True,
        "items": [{"material_id": "ACC1", "qty": 2}]}]
    stock["ACC1"] = 5
    with pytest.raises(HTTPException) as e:
        run(req_mod.deliver_request("r1", {}, ADMIN_ACC))
    assert e.value.status_code == 409 and stock["ACC1"] == 5


# ═════════════════════════ 6. PR aksesoris lewat Pengadaan ═════════════════════════
@pytest.fixture
def pur_db(monkeypatch, pr_numbers):
    db = FakeDB()
    db.rahaza_materials.docs = [_mat()]
    state = {"user": ADMIN_ACC}

    async def auth(_r):
        return state["user"]
    monkeypatch.setattr(pur, "require_auth", auth)
    monkeypatch.setattr(pur, "get_db", lambda: db)
    db.state = state
    return db


def _acc_pr(pid="p1", status="Draft", **kw):
    return {"id": pid, "pr_number": f"PRA-{pid}", "status": status, "priority": "Urgent", "purpose": "Stok kancing",
            "supplier": "CV Kancing", "requested_by": ADMIN_ACC["id"], "requested_by_name": ADMIN_ACC["name"],
            "department": "Aksesoris", "total_estimated": 20000, "created_at": "2026-11-01T00:00:00+00:00",
            "items": [{"acc_id": "ACC1", "acc_name": "Kancing", "qty_requested": 10, "estimated_price": 2000}], **kw}


def test_ajukan_pr_aksesoris_diteruskan_ke_permintaan_pengadaan(pur_db):
    pur_db.acc_purchase_requests.docs = [_acc_pr()]
    out = run(pur.submit_purchase_request("p1", FakeRequest()))
    assert out["new_status"] == "Forwarded" and out["procurement_pr_number"] == "PR-UJI-001"
    pr = pur_db.dewi_procurement_requests.docs[0]
    assert pr["origin"] == ap.ORIGIN_ACC_PR and pr["acc_pr_id"] == "p1" and pr["status"] == "submitted"
    assert pr["priority"] == "urgent" and pr["requested_by"] == ADMIN_ACC["id"]
    assert [(i["material_id"], i["qty"], i["estimated_price"]) for i in pr["items"]] == [("ACC1", 10.0, 2000.0)]
    acc = pur_db.acc_purchase_requests.docs[0]
    assert acc["status"] == "Forwarded" and acc["procurement_pr_id"] == pr["id"]
    rows = run(pur.list_purchase_requests(QRequest()))
    assert rows[0]["procurement"]["pr_number"] == "PR-UJI-001" and rows[0]["can_approve"] is False


@pytest.mark.parametrize("status", ["Received", "Ordered"])
def test_terima_barang_lewat_pr_aksesoris_ditolak_tanpa_menambah_stok(pur_db, status):
    pur_db.acc_purchase_requests.docs = [_acc_pr(status="Ordered")]
    with pytest.raises(HTTPException) as e:
        run(pur.update_purchase_request("p1", FakeRequest({"status": status})))
    assert e.value.status_code == 400 and "Penerimaan Barang" in e.value.detail
    assert pur_db.rahaza_material_stock.docs == [] and pur_db.rahaza_material_movements.docs == []


def test_pr_lama_disetujui_diteruskan_membawa_status(pur_db):
    pur_db.acc_purchase_requests.docs = [_acc_pr(status="Approved", approval_chain=["dept"],
                                                 approval_steps=[{"action": "approved", "actor_id": "u-mgr"}])]
    pur_db.state["user"] = {"id": "u-proc", "name": "Pengadaan", "role": "admin_pengadaan"}
    out = run(pur.forward_purchase_request("p1", FakeRequest()))
    assert out["procurement_status"] == "approved"
    pr = pur_db.dewi_procurement_requests.docs[0]
    assert pr["approval_steps"][0]["actor_id"] == "u-mgr" and pr["approval_chain"] == ["dept"]


def _load_migration():
    p = BACKEND / "scripts" / "migrations" / "2026_11_06_aksesoris_pr_pengadaan.py"
    spec = importlib.util.spec_from_file_location("mig_acc_pr", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_pr_aksesoris_pratinjau_lalu_tulis_idempoten(pr_numbers):
    mig = _load_migration()
    db = FakeDB()
    db.rahaza_materials.docs = [_mat()]
    db.acc_purchase_requests.docs = [
        _acc_pr("a", "Draft"), _acc_pr("b", "Submitted", current_approver_stage="finance",
                                       approval_chain=["dept", "finance"]),
        _acc_pr("c", "Rejected"), _acc_pr("d", "Received"),
        _acc_pr("e", "Draft", items=[]),
    ]
    pre = run(mig.migrate(db, apply=False))
    assert pre["found"] == 3 and pre["skipped_empty"] == 1 and db.dewi_procurement_requests.docs == []
    res = run(mig.migrate(db, apply=True))
    assert res["moved"] == 2 and res["failed"] == 0
    st = {p["acc_pr_id"]: p["status"] for p in db.dewi_procurement_requests.docs}
    assert st == {"a": "draft", "b": "dept_approved"}        # tahap keuangan menunggu = dept sudah setuju
    again = run(mig.migrate(db, apply=True))
    assert again["found"] == 1 and again["moved"] == 0      # hanya PR tanpa barang yang tersisa
    assert len(db.dewi_procurement_requests.docs) == 2


# ═════════════════════════ 7. harga Terima Stok manual ═════════════════════════
def _recv_db():
    db = FakeDB()
    db.rahaza_locations.docs = [{"id": "acc", "code": "ZNA-AKSESORIS", "name": "Area Aksesoris",
                                 "storage_role": "aksesoris"}]
    db.rahaza_materials.docs = [{**_mat("m1", "ACC-1", 1000.0)}]
    db[stock_service.STOCK].docs = [{"id": "s1", "material_id": "m1", "location_id": "acc", "qty": 100.0}]
    return db


@pytest.fixture
def recv(monkeypatch):
    db = _recv_db()
    state = {"user": ADMIN_ACC}
    cap = {}

    async def auth(_r):
        return state["user"]

    async def add(*a, **k):
        return None

    async def post(db_, mv, user):
        cap["unit_cost"] = mv["unit_cost"]
        return {"ok": True, "je_id": "je1", "je_number": "JE-1"}
    monkeypatch.setattr(stk, "require_auth", auth)
    monkeypatch.setattr(stk, "get_db", lambda: db)
    monkeypatch.setattr(stock_service, "add", add)
    monkeypatch.setattr(stk, "post_inventory_receive", post)
    db.state, db.cap = state, cap
    return db


def test_non_keuangan_tidak_boleh_mengetik_harga(recv):
    with pytest.raises(HTTPException) as e:
        run(stk.receive_stock(FakeRequest({"acc_id": "m1", "qty": 10, "unit_cost": 2000})))
    assert e.value.status_code == 403 and "Keuangan" in e.value.detail
    assert recv.rahaza_materials.docs[0]["unit_cost"] == 1000.0


def test_non_keuangan_memakai_harga_po_terakhir_dan_tetap_berjurnal(recv):
    recv.rahaza_purchase_orders.docs = [
        {"id": "po0", "po_number": "PO-LAMA", "status": "fully_received", "created_at": "2026-10-01",
         "items": [{"material_id": "m1", "unit_cost": 900}]},
        {"id": "po1", "po_number": "PO-BARU", "status": "approved", "created_at": "2026-11-01",
         "items": [{"material_id": "m1", "unit_cost": 1200}]},
        {"id": "po2", "po_number": "PO-DRAF", "status": "draft", "created_at": "2026-11-05",
         "items": [{"material_id": "m1", "unit_cost": 5000}]},
    ]
    out = run(stk.receive_stock(FakeRequest({"acc_id": "m1", "qty": 100})))
    assert out["price_source"] == "po" and recv.cap["unit_cost"] == 1200          # jurnal = 100 × 1.200
    assert out["unit_cost"] == pytest.approx(1100.0)   # (100×1.000 + 100×1.200) / 200
    info = run(stk.receive_price("m1", QRequest()))
    assert info["can_set_price"] is False and info["po_number"] == "PO-BARU"


def test_non_keuangan_tanpa_po_memakai_hpp_master(recv):
    out = run(stk.receive_stock(FakeRequest({"acc_id": "m1", "qty": 10, "unit_cost": 1000})))  # = master: boleh
    assert out["price_source"] == "master" and recv.cap["unit_cost"] == 1000


def test_keuangan_boleh_mengetik_harga(recv):
    recv.state["user"] = FIN
    out = run(stk.receive_stock(FakeRequest({"acc_id": "m1", "qty": 100, "unit_cost": 3000})))
    assert out["price_source"] == "input" and recv.cap["unit_cost"] == 3000
    assert run(stk.receive_price("m1", QRequest()))["can_set_price"] is True


# ═════════════════════════ 8. nama kategori, bukan ID ═════════════════════════
CAT_ID = "5f0c9a52-1d2e-4a3b-9c4d-111122223333"


@pytest.fixture
def items_db(monkeypatch):
    db = FakeDB()
    db.rahaza_material_categories.docs = [{"id": CAT_ID, "code": "ACCESSORY", "name": "Aksesoris"},
                                          {"id": "cat-pkg", "code": "PACKAGING", "name": "Packaging"}]

    async def auth(_r):
        return ADMIN_ACC
    monkeypatch.setattr(items_mod, "require_auth", auth)
    monkeypatch.setattr(items_mod, "get_db", lambda: db)
    return db


def test_kolom_kategori_menampilkan_nama(items_db):
    items_db.rahaza_materials.docs = [
        {**_mat("a"), "name": "A", "category": CAT_ID, "category_id": CAT_ID, "sub_category": "Trimming"},
        {**_mat("b"), "name": "B", "category": CAT_ID},                                       # tanpa category_name
        {**_mat("c"), "name": "C", "category": "Umum"},                                       # teks lama
        {**_mat("d"), "name": "D", "category": "9a9a9a9a-0000-4000-8000-000000000000"},       # ID tanpa padanan
    ]
    rows = {r["id"]: r for r in run(items_mod.list_items(QRequest()))}
    assert (rows["a"]["category"], rows["a"]["category_id"], rows["a"]["sub_category"]) == ("Aksesoris", CAT_ID, "Trimming")
    assert rows["b"]["category"] == "Aksesoris" and rows["c"]["category"] == "Umum"
    assert rows["d"]["category"] == ""                                                    # ID tidak pernah tampil
    stk_rows = {r["id"]: r for r in run(_overview(items_db))}
    assert stk_rows["b"]["category"] == "Aksesoris"


def _overview(db):
    import routes.dewi_accessories_stock as s

    async def go():
        async def auth(_r):
            return ADMIN_ACC
        old_auth, old_db = s.require_auth, s.get_db
        s.require_auth, s.get_db = auth, (lambda: db)
        try:
            return await s.get_stock_overview(QRequest())
        finally:
            s.require_auth, s.get_db = old_auth, old_db
    return go()


def test_ubah_item_mengirim_ulang_nama_kategori_tidak_menimpa_id(items_db):
    items_db.rahaza_materials.docs = [{**_mat("a"), "category": CAT_ID, "category_id": CAT_ID,
                                       "category_name": "Aksesoris"}]
    out = run(items_mod.update_item("a", FakeRequest({"name": "Kancing 12", "category": "Aksesoris"})))
    assert items_db.rahaza_materials.docs[0]["category"] == CAT_ID and out["category"] == "Aksesoris"
    run(items_mod.update_item("a", FakeRequest({"category_id": "cat-pkg", "sub_category": "Plastik"})))
    m = items_db.rahaza_materials.docs[0]
    assert (m["category_id"], m["category_name"], m["sub_category"]) == ("cat-pkg", "Packaging", "Plastik")
    with pytest.raises(HTTPException):
        run(items_mod.update_item("a", FakeRequest({"category_id": "tidak-ada"})))


def test_inbox_menampilkan_nama_vendor_dan_nomor_surat_jalan(req_db):
    req_db.vendor_partners.docs = [{"id": "v1", "name": "CMT Sejahtera"}]
    req_db.vendor_shipments.docs = [{"id": "s1", "shipment_number": "SJ-0001"}]
    req_db.dewi_rnd_sample_requests.docs = [{"id": "smp", "sample_code": "SMP-07"}]
    req_db.dewi_accessory_requests.docs = [
        {"id": "r1", "request_type": "vendor_additional", "vendor_id": "v1", "original_shipment_id": "s1",
         "status": "submitted", "created_at": T0, "items": []},
        {"id": "r2", "request_type": "rnd_sample", "sample_request_id": "smp", "status": "submitted",
         "created_at": T0, "items": []},
    ]
    rows = {r["id"]: r for r in run(req_mod.list_requests(
        status=None, request_type=None, sample_request_id=None, style_id=None, divisi=None, vendor_id=None,
        urgent_only=False, search=None, limit=200, user=ADMIN_ACC))}
    assert rows["r1"]["vendor_name"] == "CMT Sejahtera" and rows["r1"]["original_shipment_number"] == "SJ-0001"
    assert rows["r2"]["sample_code"] == "SMP-07"


# ═════════════════════════ 9. PUT mempertahankan tautan ═════════════════════════
def test_ubah_permintaan_mempertahankan_material_id(req_db):
    req_db.dewi_accessory_requests.docs = [{
        "id": "r1", "status": "submitted", "request_type": "internal_issuance",
        "items": [{"material_id": "ACC1", "material_code": "KCG", "material_name": "Kancing", "qty": 2,
                   "unit": "pcs", "po_accessory_id": "pa1"},
                  {"material_id": "ACC2", "material_code": "", "material_name": "Label", "qty": 1}]}]
    run(req_mod.update_request("r1", {"items": [
        {"material_code": "KCG", "material_name": "Kancing", "qty": 5},           # klien lama tanpa id
        {"material_name": "Label", "qty": 3},
        {"material_id": "ACC9", "material_name": "Baru", "qty": 1},
    ]}, ADMIN_ACC))
    items = req_db.dewi_accessory_requests.docs[0]["items"]
    assert [(i["material_id"], i["qty"]) for i in items] == [("ACC1", 5.0), ("ACC2", 3.0), ("ACC9", 1.0)]
    assert items[0]["po_accessory_id"] == "pa1"


def test_buat_permintaan_menolak_divisi_di_luar_daftar(req_db, monkeypatch):
    import core.doc_number_policy as dnp

    async def number(db_, key, *, ctx=None, requested=""):
        return "INT-REQ-1"
    monkeypatch.setattr(dnp, "issue_number", number)
    with pytest.raises(HTTPException) as e:
        run(req_mod.create_request({"request_type": "internal_issuance", "divisi": "Dapur",
                                    "items": [{"material_id": "ACC1", "qty": 1}]}, ADMIN_ACC))
    assert e.value.status_code == 400
    out = run(req_mod.create_request({"request_type": "internal_issuance", "divisi": "marketing",
                                      "items": [{"material_id": "ACC1", "qty": 1}]}, ADMIN_ACC))
    assert out["divisi"] == "Marketing"


# ═════════════════════════ layar ═════════════════════════
FE = BACKEND.parent / "frontend" / "src" / "components" / "erp"


@pytest.mark.skipif(not FE.is_dir(), reason="frontend tidak tersedia")
def test_layar_memakai_daftar_divisi_backend_dan_tanpa_terima_barang():
    src = (FE / "AccessoryModule.jsx").read_text(encoding="utf-8")
    assert "/api/acc/divisions" in src and "const DIVISI = [" not in src
    assert "'Received')" not in src and "receive-pr-" not in src
    assert "/api/acc/stock/receive-price/" in src
    po = (FE / "engine" / "ProductionPOModule.jsx").read_text(encoding="utf-8")
    assert "Ajukan Pembelian (" in po and "Buat Permintaan (" not in po
    inbox = (FE / "AccessoryRequestInbox.jsx").read_text(encoding="utf-8")
    assert "dewi_accessory_requests" not in inbox and "r.vendor_id ||" not in inbox
