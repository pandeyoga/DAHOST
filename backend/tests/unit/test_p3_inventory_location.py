"""Uji unit HERMETIK paket P3 — stock_service, restock retur, karantina lepas sebagian,
lokasi wajib (No.18a), penilaian aksesoris/material, pengingat stok minus (No.29a).
2026-11-02. Angka harapan dihitung tangan dari uji runtime audit g.md §0.2.

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import asyncio
import os
import sys

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from p3_fakes import FakeDB, FakeRequest  # noqa: E402
from core import stock_service  # noqa: E402

USER = {"id": "u1", "name": "Uji", "email": "uji@x", "role": "superadmin"}


def run(coro):
    return asyncio.run(coro)


# ── 5. stock_service tidak menimpa identitas baris ───────────────────────────
def test_meta_set_keeps_identity_of_existing_row():
    st = stock_service._meta_set({"inventory_category": "finished_goods", "ownership": "own",
                                  "material_code": "DA-2101", "unit": "pcs"})
    # identitas: $ifNull → nilai baris lama menang; deskriptif: tetap ditimpa
    assert st["inventory_category"] == {"$ifNull": ["$inventory_category", {"$literal": "finished_goods"}]}
    assert st["ownership"] == {"$ifNull": ["$ownership", {"$literal": "own"}]}
    assert st["material_code"] == "DA-2101" and st["unit"] == "pcs"


def _ifnull_eval(expr, row):
    """Evaluasi kecil ekspresi $ifNull yang dibangun _meta_set (meniru Mongo)."""
    if isinstance(expr, dict) and "$ifNull" in expr:
        field, lit = expr["$ifNull"]
        cur = row.get(field[1:])
        return cur if cur is not None else lit["$literal"]
    return expr


def test_restock_on_existing_fg_row_keeps_fg_internal():
    row = {"qty": 34, "inventory_category": "fg_internal", "ownership": "cv_da"}
    st = stock_service._meta_set({"inventory_category": "fg_internal", "ownership": "cv_da"})
    after = {k: _ifnull_eval(v, row) for k, v in st.items()}
    assert after == {"inventory_category": "fg_internal", "ownership": "cv_da"}
    new_row = {}
    st2 = stock_service._meta_set({"inventory_category": "fg_internal", "ownership": "cv_da"})
    assert {k: _ifnull_eval(v, new_row) for k, v in st2.items()}["inventory_category"] == "fg_internal"


def _patch_returns(monkeypatch, cap):
    from core import returns_bridge as rb

    async def add(mid, loc, qty, **kw):
        cap["meta"] = kw.get("meta")
        return {"qty": qty}

    async def val(*a, **k):
        return {}

    async def cache(*a, **k):
        return 0
    monkeypatch.setattr(rb.stock_service, "add", add)
    monkeypatch.setattr(rb, "_value_restock", val)
    monkeypatch.setattr(rb, "_value_damaged", val)
    monkeypatch.setattr(rb, "refresh_catalog_cache", cache)
    return rb


@pytest.mark.parametrize("cond,expect_cat", [("Baik", "fg_internal"), ("Rusak", None)])
def test_restock_vocab_matches_sales_readers(monkeypatch, cond, expect_cat):
    cap = {}
    rb = _patch_returns(monkeypatch, cap)
    db = FakeDB(
        wh_returns=[{"id": "wr1", "return_code": "RTN-1", "material_id": "fg-z", "qty": 2}],
        rahaza_locations=[{"id": "rak", "code": "GD-L1-RAK", "storage_role": "fg", "active": True},
                          {"id": "qc", "code": "GD-L1-QC", "storage_role": "karantina", "active": True}],
        rahaza_materials=[{"id": "fg-z", "code": "DA-2101-MHG-ALLSIZE", "type": "fg"}])
    run(rb.restock(db, {"id": "wr1", "material_id": "fg-z", "qty": 2}, condition=cond, qty=2, actor=USER))
    assert cap["meta"]["ownership"] == "cv_da"                 # dulu "own"
    assert cap["meta"].get("inventory_category") == expect_cat  # dulu "finished_goods"


def test_restock_layer_linked_to_its_journal(monkeypatch):
    from core import returns_bridge as rb
    from core import fg_cost_layers as fcl
    import routes.rahaza_posting as rp

    async def unit_cost(db, mid, **kw):   # 2026-11-02 (S2-W, No.26a): nilai restock = WAC FG
        return {"unit_cost": 55497.25, "components": {"material": 55497.25, "labor": 0.0, "overhead": 0.0}}

    async def push(db, **kw):
        await db.fg_cost_layers.insert_one({"id": "ly-r", "gl_je_id": None})
        return {"id": "ly-r"}

    async def je(db, wh, qty, uc, actor, **kw):
        return {"ok": True, "je_id": "je-r", "je_number": "JE-R"}
    monkeypatch.setattr(fcl, "wac_state", unit_cost)
    monkeypatch.setattr(fcl, "push_layer", push)
    monkeypatch.setattr(rp, "post_marketplace_return_restock", je)
    db = FakeDB()
    out = run(rb._value_restock(db, {"id": "wr1"}, "fg-z", 2, USER))
    assert out["cogs_je_id"] == "je-r"
    assert db.fg_cost_layers.docs[0]["gl_je_id"] == "je-r"     # dulu kosong → "unposted" palsu 110.994,50


# ── 6. karantina: qty bernilai dilacak per qty ───────────────────────────────
def test_quarantine_partial_release_then_scrap_rest_has_no_inventory_je():
    from routes import wms_quarantine as wq
    item = {"id": "q1", "remaining_qty": 10, "valued": False}          # reject GR 10 kg
    vr = wq.valued_remaining_of(item)
    assert vr == 0
    v, u = wq.split_valued(4, vr)                                       # lepas 4
    assert (v, u) == (0, 4)                                             # JE kapitalisasi 4 × HPP
    after = {"id": "q1", "remaining_qty": 6, "valued": False, "valued_qty": vr - v}
    v2, u2 = wq.split_valued(6, wq.valued_remaining_of(after))         # scrap 6 sisa
    assert v2 == 0                                                      # dulu 6 × 55.000 = 330.000 ke 1-1401
    # item yang sejak awal bernilai (re-inspeksi) tetap ditulis-off penuh
    assert wq.split_valued(6, wq.valued_remaining_of({"remaining_qty": 6, "valued": True})) == (6, 0)
    # item lama yang bendera `valued`-nya dipasang bug lepas-sebagian → 0
    assert wq.valued_remaining_of({"remaining_qty": 6, "valued": True}, legacy_flipped=True) == 0


def test_quarantine_legacy_flip_detected_from_release_movement():
    from routes import wms_quarantine as wq
    db = FakeDB(rahaza_material_movements=[{"id": "mv", "reference_type": "quarantine", "reference_id": "q1",
                                             "adjustment_reason": "quarantine_release"}])
    assert run(wq._valued_remaining(db, {"id": "q1", "remaining_qty": 6, "valued": True})) == 0
    assert run(wq._valued_remaining(db, {"id": "q2", "remaining_qty": 6, "valued": True})) == 6


# ── 7. lokasi wajib (No.18a) ─────────────────────────────────────────────────
def test_fg_issue_requires_location(monkeypatch):
    import routes.rahaza_inventory_fg as fgr
    db = FakeDB(rahaza_materials=[{"id": "fg-z", "type": "fg", "code": "Z"}],
                rahaza_locations=[{"id": "ktr", "code": "KTR-PST", "active": True},
                                  {"id": "rak", "code": "GD-L1-RAK", "active": True}],
                rahaza_material_stock=[{"material_id": "fg-z", "location_id": "rak", "qty": 36}])

    async def auth(req):
        return USER
    monkeypatch.setattr(fgr, "require_auth", auth)
    monkeypatch.setattr(fgr, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(fgr.create_fg_issue(FakeRequest({"material_id": "fg-z", "qty": 1, "reason": "sample"})))
    assert e.value.status_code == 400 and "location_id" in e.value.detail
    with pytest.raises(HTTPException) as e2:   # stok 36 di rak, bukan di kantor
        run(fgr.create_fg_issue(FakeRequest({"material_id": "fg-z", "qty": 40, "reason": "sample",
                                             "location_id": "rak"})))
    assert "Tersedia: 36" in e2.value.detail


def test_scan_location_required_or_taken_from_movement():
    from routes import wms_receiving as wr
    db = FakeDB(rahaza_locations=[{"id": "gd2", "code": "GD-L2"}])
    with pytest.raises(HTTPException):
        run(wr._require_scan_location(db, None, {}, direction="in"))
    with pytest.raises(HTTPException):
        run(wr._require_scan_location(db, "tidak-ada", {}, direction="out"))
    assert run(wr._require_scan_location(db, "gd2", {}, direction="in")) == "gd2"
    assert run(wr._require_scan_location(db, None, {"location_id": "gd2"}, direction="out")) == "gd2"


def test_cutting_location_must_be_chosen():
    from routes import cutting
    db = FakeDB(rahaza_locations=[{"id": "gd1", "code": "GD-L1", "name": "Gudang Lantai 1", "active": True}])
    with pytest.raises(HTTPException):
        run(cutting._default_location(db, "", "kain-1"))       # dulu: stok terbanyak/'gudang'/aktif pertama
    assert run(cutting._default_location(db, "gd1", "kain-1")) == ("gd1", "Gudang Lantai 1")


def test_material_return_receive_requires_location(monkeypatch):
    import routes.production_material_returns as pmr
    db = FakeDB(production_material_returns=[{"id": "r1", "status": "approved", "items": [
        {"material_id": "m1", "qty_returned": 5, "condition": "good"}]}])

    async def auth(req):
        return USER
    monkeypatch.setattr(pmr, "require_auth", auth)
    monkeypatch.setattr(pmr, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(pmr.receive_return(FakeRequest(), "r1", pmr.ActionModel(note="x")))
    assert e.value.status_code == 400 and "location_id" in e.value.detail


def test_fg_demo_seed_uses_fg_role_location_not_first_active(monkeypatch):
    import routes.fg_matrix_seed as fms
    db = FakeDB(rahaza_locations=[{"id": "ktr", "code": "KTR-PST", "active": True}])
    monkeypatch.setattr(fms, "get_db", lambda: db)
    out = run(fms.seed_fg_matrix_demo())
    assert out["status"] == "error"                          # dulu: stok demo masuk KTR-PST
    db2 = FakeDB(rahaza_locations=[{"id": "ktr", "code": "KTR-PST", "active": True},
                                   {"id": "rak", "code": "GD-L1-RAK", "storage_role": "fg", "active": True}])
    monkeypatch.setattr(fms, "get_db", lambda: db2)
    out2 = run(fms.seed_fg_matrix_demo())
    assert out2["status"] == "seeded" and out2["location_id"] == "rak"
    assert {r["location_id"] for r in db2.rahaza_material_stock.docs} == {"rak"}


def test_setup_seed_rejects_unknown_location(monkeypatch):
    import routes.rahaza_setup as rs

    async def auth(req):
        return USER
    monkeypatch.setattr(rs, "require_auth", auth)
    monkeypatch.setattr(rs, "get_db", lambda: FakeDB())
    with pytest.raises(HTTPException) as e:
        run(rs.seed_sample_data(FakeRequest({"location_id": "tidak-ada"})))
    assert e.value.status_code == 400


def test_material_adjust_rejects_unknown_location(monkeypatch):
    import routes.rahaza_inventory_stock as ris

    async def admin(req):
        return USER
    db = FakeDB()
    monkeypatch.setattr(ris, "_require_admin", admin)
    monkeypatch.setattr(ris, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(ris.material_adjust(FakeRequest({"material_id": "m1", "location_id": "uuid-salah-ketik",
                                             "qty": 5, "reason": "koreksi hitung"})))
    assert e.value.status_code == 400


# ── 8. penilaian aksesoris & material ────────────────────────────────────────
def test_accessory_receive_journal_at_purchase_price(monkeypatch):
    import routes.dewi_accessories_stock as das
    db = FakeDB(rahaza_materials=[{"id": "bis", "type": "accessory", "active": True, "unit": "m",
                                   "code": "A-BIS-0001", "unit_cost": 15000.0}])
    cap = {}

    async def auth(req):
        return USER

    async def qty(db_, mid):
        return 100.0

    async def noop(*a, **k):
        return None

    async def loc(db_):
        return "acc"

    async def apply_cost(db_, mid, q, cost, **kw):
        return {"old_unit_cost": 15000.0, "new_unit_cost": 17500.0, "changed": True, "method": "moving_average"}

    async def log_mv(db_, user, **kw):
        cap["mv_unit_cost"] = kw["unit_cost"]
        return {"id": "mv1", "qty": kw["qty"], "unit_cost": kw["unit_cost"]}

    async def post(db_, mv, user):
        cap["je_amount"] = mv["qty"] * mv["unit_cost"]
        return {"ok": True, "je_id": "je", "je_number": "JE-8"}
    monkeypatch.setattr(das, "require_auth", auth)
    monkeypatch.setattr(das, "get_db", lambda: db)
    monkeypatch.setattr(das, "_stock_qty", qty)
    monkeypatch.setattr(das, "_add_stock", noop)
    monkeypatch.setattr(das, "_get_accessory_location_id", loc)
    monkeypatch.setattr(das.accessory_valuation, "apply_receipt_cost", apply_cost)
    monkeypatch.setattr(das, "_log_movement", log_mv)
    monkeypatch.setattr(das, "post_inventory_receive", post)
    out = run(das.receive_stock(FakeRequest({"acc_id": "bis", "qty": 100, "unit_cost": 20000})))
    assert cap["je_amount"] == pytest.approx(2_000_000)     # dulu 100 × 17.500 = 1.750.000
    assert out["unit_cost"] == pytest.approx(17500.0)       # HPP master tetap rata-rata bergerak
    assert out["value"] == pytest.approx(2_000_000)


def test_material_receive_updates_moving_average(monkeypatch):
    import routes.rahaza_inventory_stock as ris
    from core import accessory_valuation as av
    db = FakeDB(rahaza_materials=[{"id": "kn", "type": "fabric", "code": "KN-K20-TRC", "unit": "kg",
                                   "unit_cost": 55000.0}],
                rahaza_material_movements=[{"id": "mv1"}])
    cap = {}

    async def admin(req):
        return USER

    async def yes(db_, lid):
        return True

    async def onhand(mid, db=None):
        return 190.0

    async def add(*a, **k):
        return {}

    async def apply_cost(db_, mid, q, cost, **kw):
        cap["wac"] = av.moving_average(kw["qty_before"], 55000.0, q, cost)
        return {"new_unit_cost": cap["wac"]}

    async def log_mv(db_, user, **kw):
        return {"id": "mv1", **kw}

    async def noop(*a, **k):
        return {"ok": True}
    monkeypatch.setattr(ris, "_require_admin", admin)
    monkeypatch.setattr(ris, "get_db", lambda: db)
    monkeypatch.setattr(ris.location_resolver, "location_exists", yes)
    monkeypatch.setattr(ris.stock_service, "get_onhand", onhand)
    monkeypatch.setattr(ris.stock_service, "add", add)
    monkeypatch.setattr(av, "apply_receipt_cost", apply_cost)
    monkeypatch.setattr(ris, "_log_movement", log_mv)
    monkeypatch.setattr(ris, "log_activity", noop)
    monkeypatch.setattr(ris, "post_inventory_receive", noop)
    run(ris.material_receive(FakeRequest({"material_id": "kn", "location_id": "gd2", "qty": 10, "unit_cost": 70000})))
    # (190 × 55.000 + 10 × 70.000) / 200 = 55.750 — dulu HPP tetap 55.000
    assert cap["wac"] == pytest.approx(55750.0)


# ── 9. pengingat stok minus ──────────────────────────────────────────────────
def test_negative_digest_body_and_value():
    from core import negative_stock_reminder as nr
    d = nr.build_digest([
        {"material_id": "a", "code": "KN-K20-CRL", "name": "Kain", "unit": "kg", "location_code": "GD-L2",
         "qty": -20, "unit_cost": 47500},
        {"material_id": "b", "code": "A-LBL-0001", "name": "Label", "unit": "pcs", "location_code": "GD-L1-ACC",
         "qty": -5, "unit_cost": 0},
        {"material_id": "c", "code": "OK", "qty": 3, "unit_cost": 1}])
    assert d["count"] == 2 and d["materials"] == 2 and d["total_value"] == pytest.approx(950000)
    assert "KN-K20-CRL" in d["lines"][0] and "HPP 0" in d["lines"][1]


def test_negative_reminder_targets_warehouse_roles_dedup_per_day(monkeypatch):
    from core import negative_stock_reminder as nr
    import utils.notif_unified as nu
    sent = []

    async def fake_insert(db, **kw):
        sent.append(kw)
        await db.notifications.insert_one({"id": "n1", "source_ref": kw["source_ref"], "subtype": kw["subtype"]})
        return "n1"

    async def rows(db):
        return [{"material_id": "a", "code": "KN", "qty": -20, "unit_cost": 47500, "location_code": "GD-L2"}]
    monkeypatch.setattr(nu, "notif_insert", fake_insert)
    monkeypatch.setattr(nr, "negative_rows", rows)
    db = FakeDB(roles=[{"name": "hr", "portals": ["warehouse", "self"]}])   # akses baca ≠ penanggung jawab
    r1 = run(nr.send_daily_reminder(db, day="2026-11-02"))
    r2 = run(nr.send_daily_reminder(db, day="2026-11-02"))
    assert r1["sent"] and not r2["sent"] and len(sent) == 1               # 1× per hari
    roles = sent[0]["target_roles"]
    from routes.shared import PORTAL_ACCESS
    assert roles == sorted(PORTAL_ACCESS["warehouse"]) and "hr" not in roles
    assert sent[0]["source_url"] == "#wms-stock-hub=negative"
    assert sent[0]["meta"]["link_module"] == "wms-stock-hub" and sent[0]["meta"]["hub_tab"] == "negative"


def test_negative_reminder_registered_daily_job():
    from core import negative_stock_reminder as nr
    assert nr.register_scheduler_job() is True
    from utils.scheduler import JOB_REGISTRY
    assert JOB_REGISTRY[nr.JOB_ID]["cron"] == {"hour": 7, "minute": 15}
