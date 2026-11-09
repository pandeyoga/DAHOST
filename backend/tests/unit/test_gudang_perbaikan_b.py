"""Uji unit HERMETIK perbaikan Gudang (9 Nov 2026) — Tahap B: stok awal yang aman + G13.

Angka harapan DIHITUNG TANGAN:
  * Opname stok awal lokasi GD-L2: kain KN-CND-01 dihitung 125 kg (sistem 125 → selisih 0) dan KN-NEW 50 kg
    @ 40.000 (sistem 0) → Dr 1-1401 2.000.000 / Cr 3-2000 2.000.000 (BUKAN 5-1950).
  * FG stok awal tanpa WAC, HPP standar 30.000 (bahan 22.000 + CMT 8.000), dihitung 4 di GD-L1-RAK →
    Dr 1-1404 120.000 / Cr 3-2000 120.000; WAC FG = 30.000, komponen bahan 22.000 + upah 8.000.
  * Excel STOK_AWAL_FG: DA-FG-2 10 pcs @ hpp_satuan_sistem 45.000 → nilai 450.000 vs Saldo Awal 1-1404
    400.000 → selisih 50.000 (laporan, tanpa jurnal).
  * Impor roll: KN-CND-01 3 roll × 24,5 kg + 2 roll rata-rata (2 × 25) = 123,5 kg; KN-YRD 1 roll rata-rata 115 yard.

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_gudang_perbaikan_b.py -q
"""
import asyncio
import io
import os
import sys

import openpyxl
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from core import fabric_roll_import as fri  # noqa: E402
from core import gap_workbook as gw  # noqa: E402
from core import opening_balance as ob  # noqa: E402
from core import opname_engine as eng  # noqa: E402
from core import stock_service  # noqa: E402
from test_k9_opname_engine import USER, _count, env, seed  # noqa: E402,F401  (fixture `env` dipakai ulang)

FIN = {"id": "u-fin", "name": "Keuangan", "email": "fin@x", "role": "accounting"}
WH = {"id": "u-gd", "name": "Gudang", "email": "gd@x", "role": "admin_gudang"}


def run(coro):
    return asyncio.run(coro)


def _opening_je(db, lines, je_id="JE-OB"):
    db.rahaza_journal_entries.docs.append({"id": je_id, "je_number": "JE-DA-OB-1", "source_module": "opening_balance",
                                           "status": "posted", "entity": "DA", "lines": lines})


# ═════════════════════════ B1 — fungsi murni opname stok awal ═════════════════════════
def test_opening_problems_classifies_rows():
    lines = [{"material_id": "A", "material_code": "A", "variance_qty": 5, "unit_cost": 0},
             {"material_id": "B", "material_code": "B", "variance_qty": -2, "unit_cost": 10},
             {"material_id": "C", "material_code": "C", "variance_qty": 3, "unit_cost": 10},
             {"material_id": "D", "material_code": "D", "variance_qty": 1, "unit_cost": 10},
             {"material_id": "E", "material_code": "E", "variance_qty": 0, "unit_cost": 0},
             {"material_id": "F", "material_code": "F", "variance_qty": 2, "unit_cost": 99}]
    p = eng.opening_problems(lines, opened={"C"}, client_ids={"D"})
    assert {k: [x["material_code"] for x in v] for k, v in p.items()} == {
        "tanpa_harga": ["A"], "berkurang": ["B"], "sudah_ada_stok_awal": ["C"], "barang_klien": ["D"]}
    assert eng.opening_problems([lines[-1]], opened=set(), client_ids=set()) == {}


def test_opening_unit_cost_fg_wac_then_standard_hpp(env):
    db = env.db
    seed(db)
    db.rahaza_materials.docs += [
        {"id": "FG2", "code": "DA-FG-2", "type": "fg", "unit": "pcs", "hpp": 30000.0,
         "hpp_breakdown": {"material": 22000, "cmt": 8000, "internal_labor": 0, "overhead": 0}},
        {"id": "FG3", "code": "DA-FG-3", "type": "fg", "unit": "pcs"}]
    m = {d["id"]: d for d in db.rahaza_materials.docs}
    assert run(eng.opening_unit_cost(db, m["FG1"]))[:2] == (50000.0, "wac")
    assert run(eng.opening_unit_cost(db, m["FG2"])) == (30000.0, "hpp_standar",
                                                       {"material": 22000.0, "labor": 8000.0, "overhead": 0.0})
    assert run(eng.opening_unit_cost(db, m["FG3"])) == (0.0, "", None)
    assert run(eng.opening_unit_cost(db, m["KN1"])) == (55000.0, "harga_master", None)


# ═════════════════════════ B1 — alur opname stok awal ═════════════════════════
def test_opening_session_journals_to_equity_and_marks_opening(env):
    db = env.db
    seed(db)
    db.rahaza_materials.docs.append({"id": "KN3", "code": "KN-NEW", "name": "Kain baru", "type": "fabric",
                                     "unit": "kg", "unit_cost": 40000.0})
    sess = run(eng.create_session(db, USER, location_id="L2", opening=True))
    assert sess["mode"] == eng.MODE_OPENING and sess["scope_label"].startswith("Stok awal")
    with pytest.raises(HTTPException):
        run(eng.create_session(db, USER, location_id="L2", sub_type="rack", sub_id="R1", opening=True))
    run(_count(db, sess["id"], "KN1", 125))
    run(_count(db, sess["id"], "KN2", 100))
    run(_count(db, sess["id"], "KN3", 50))
    s = run(eng.submit(db, USER, run(eng.get_session(db, sess["id"]))))
    out = run(eng.approve(db, FIN, s))
    assert out["status"] == "approved"
    assert env.jes[-1]["source_module"] == eng.OPENING_EVENT
    assert env.je_lines() == [("1-1401", 2000000.0, 0), ("3-2000", 0, 2000000.0)]
    assert env.stock("KN3", "L2") == 50.0
    mv = [m for m in db.rahaza_material_movements.docs if m.get("material_id") == "KN3"]
    assert mv and mv[0]["type"] == "opening" and mv[0]["to_location_id"] == "L2"
    # sekali per barang×lokasi: sesi stok awal kedua untuk KN3 ditolak (daftar dikembalikan)
    s2 = run(eng.create_session(db, USER, location_id="L2", opening=True, material_ids=["KN3"]))
    run(_count(db, s2["id"], "KN3", 60))
    s2 = run(eng.submit(db, USER, run(eng.get_session(db, s2["id"]))))
    with pytest.raises(HTTPException) as e:
        run(eng.approve(db, FIN, s2))
    assert e.value.status_code == 409 and "sudah_ada_stok_awal" in e.value.detail["problems"]


def test_opening_rejects_zero_price_and_less_than_system(env):
    db = env.db
    seed(db)
    db.rahaza_materials.docs.append({"id": "KN0", "code": "KN-0", "name": "Kain tanpa harga", "type": "fabric",
                                     "unit": "kg", "unit_cost": 0})
    sess = run(eng.create_session(db, USER, location_id="L2", opening=True))
    run(_count(db, sess["id"], "KN0", 10))
    run(_count(db, sess["id"], "KN1", 100))           # sistem 125 → berkurang
    run(_count(db, sess["id"], "KN2", 100))
    s = run(eng.submit(db, USER, run(eng.get_session(db, sess["id"]))))
    with pytest.raises(HTTPException) as e:
        run(eng.approve(db, FIN, s))
    probs = e.value.detail["problems"]
    assert [x["material_code"] for x in probs["tanpa_harga"]] == ["KN-0"]
    assert [x["material_code"] for x in probs["berkurang"]] == ["KN-CND-01"]
    assert env.jes == [] and env.stock("KN0", "L2") == 0                   # stok TIDAK berubah
    assert run(eng.get_session(db, sess["id"]))["status"] == "submitted"


def test_opening_rejected_when_saldo_awal_fills_inventory_account(env):
    db = env.db
    seed(db)
    db.rahaza_materials.docs.append({"id": "KN3", "code": "KN-NEW", "type": "fabric", "unit": "kg", "unit_cost": 40000.0})
    _opening_je(db, [{"account_code": "1-1401", "debit": 5000000, "credit": 0},
                     {"account_code": "3-2000", "debit": 0, "credit": 5000000}])
    sess = run(eng.create_session(db, USER, location_id="L2", opening=True, material_ids=["KN3"]))
    run(_count(db, sess["id"], "KN3", 50))
    s = run(eng.submit(db, USER, run(eng.get_session(db, sess["id"]))))
    with pytest.raises(HTTPException) as e:
        run(eng.approve(db, FIN, s))
    assert e.value.detail["code"] == "bentrok_saldo_awal" and "DOBEL" in e.value.detail["message"]


def test_opening_fg_sets_wac_from_standard_hpp(env):
    db = env.db
    seed(db)
    db.rahaza_materials.docs.append({"id": "FG2", "code": "DA-FG-2", "name": "Gamis 2", "type": "fg", "unit": "pcs",
                                     "hpp": 30000.0,
                                     "hpp_breakdown": {"material": 22000, "cmt": 8000, "overhead": 0}})
    sess = run(eng.create_session(db, USER, location_id="LRAK", opening=True, material_ids=["FG2"]))
    run(_count(db, sess["id"], "FG2", 4))
    s = run(eng.submit(db, USER, run(eng.get_session(db, sess["id"]))))
    run(eng.approve(db, FIN, s))
    assert env.je_lines() == [("1-1404", 120000.0, 0), ("3-2000", 0, 120000.0)]
    fg = next(m for m in db.rahaza_materials.docs if m["id"] == "FG2")
    assert fg["unit_cost"] == 30000.0 and fg["wac_components"]["labor"] == 8000.0
    row = next(r for r in db[stock_service.STOCK].docs if r["material_id"] == "FG2")
    assert (row["inventory_category"], row["ownership"], row["qty"]) == ("fg_internal", "cv_da", 4.0)
    layer = db.fg_cost_layers.docs[-1]
    assert layer["gl_basis"] == "opname_stok_awal" and layer["gl_je_id"] == env.jes[-1]["id"]


def test_opening_approve_gate_is_finance_only():
    from routes.wms_opname3 import assert_can_approve
    opening = {"mode": eng.MODE_OPENING}
    with pytest.raises(HTTPException) as e:
        assert_can_approve({"role": "admin_gudang", "_permissions": []}, "approve opname", opening)
    assert e.value.status_code == 403 and "Keuangan" in e.value.detail
    assert_can_approve({"role": "accounting"}, "approve opname", opening)
    assert_can_approve({"role": "owner"}, "approve opname", opening)
    assert_can_approve({"role": "admin_gudang"}, "approve opname", {"mode": "full"})   # opname biasa tetap gudang


# ═════════════════════════ Saldo Awal ⇄ opname stok awal ═════════════════════════
def test_saldo_awal_blocks_inventory_already_from_opening_count(monkeypatch):
    import routes.rahaza_posting as rp

    async def mapping(_db, key):
        return {"inventory_rm": "1-1401", "inventory_accessory": "1-1402", "inventory_fg": "1-1404"} \
            if key == "inventory_adjust" else {}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    db = fm.FakeDB()
    db.rahaza_journal_entries.docs.append({"id": "j1", "source_module": ob.OPENING_COUNT_MODULE, "status": "posted",
                                           "lines": [{"account_code": "1-1401", "debit": 2000000, "credit": 0},
                                                     {"account_code": "3-2000", "debit": 0, "credit": 2000000}]})
    errors = []
    lines = [{"account_code": "1-1401", "debit": 2000000, "credit": 0},
             {"account_code": "1-1404", "debit": 400000, "credit": 0}, {"account_code": "1-1101", "debit": 9, "credit": 0}]
    warn = run(ob.inventory_overlap_check(db, lines, errors))
    assert len(errors) == 1 and errors[0].startswith("1-1401") and "dobel" in errors[0]
    assert len(warn) == 1 and warn[0].startswith("1-1404")


# ═════════════════════════ B2 — Excel STOK_AWAL ═════════════════════════
def _gw_db():
    db = fm.FakeDB()
    db.rahaza_locations.docs += [
        {"id": "LRAK", "code": "GD-L1-RAK", "name": "Rak", "storage_role": "fg", "active": True},
        {"id": "L2", "code": "GD-L2", "name": "Lt 2", "storage_role": "bahan", "active": True},
        {"id": "LQC", "code": "GD-L1-QC", "name": "QC", "storage_role": "karantina", "active": True}]
    db.rahaza_materials.docs += [
        {"id": "FG2", "code": "DA-FG-2", "name": "Gamis 2", "type": "fg", "unit": "pcs", "hpp": 30000.0,
         "active": True},
        {"id": "FG3", "code": "DA-FG-3", "name": "Tanpa HPP", "type": "fg", "unit": "pcs", "active": True},
        {"id": "FG4", "code": "DA-FG-4", "name": "Nonaktif", "type": "fg", "unit": "pcs", "hpp": 1, "active": False},
        {"id": "KN1", "code": "KN-CND-01", "name": "Kain", "type": "fabric", "unit": "kg", "unit_cost": 55000.0,
         "code_aliases": ["KN-CND 01"], "active": True},
        {"id": "KN9", "code": "KN-ZERO", "name": "Kain 0", "type": "fabric", "unit": "kg", "unit_cost": 0, "active": True}]
    return db


def _wb(fg_rows=(), mat_rows=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "STOK_AWAL_FG"
    ws.append(gw.STOK_FG_COLS)
    for r in fg_rows:
        ws.append(list(r))
    ws = wb.create_sheet("STOK_AWAL_MATERIAL")
    ws.append(gw.STOK_MAT_COLS)
    for r in mat_rows:
        ws.append(list(r))
    return wb


def _imap(monkeypatch):
    import routes.rahaza_posting as rp

    async def mapping(_db, key):
        return {"inventory_rm": "1-1401", "inventory_accessory": "1-1402", "inventory_fg": "1-1404"} \
            if key == "inventory_adjust" else {}
    monkeypatch.setattr(rp, "get_mapping", mapping)


def test_stok_awal_parse_aliases_inactive_zero_cost_and_recon(monkeypatch):
    _imap(monkeypatch)
    db = _gw_db()
    _opening_je(db, [{"account_code": "1-1404", "debit": 400000, "credit": 0}])
    wb = _wb(fg_rows=[("DA-FG-2", "", "", "", "", "GD-L1-RAK", 10, 45000, ""),
                      ("DA-FG-3", "", "", "", "", "GD-L1-RAK", 2, None, ""),
                      ("DA-FG-4", "", "", "", "", "GD-L1-RAK", 1, 10, ""),
                      ("DA-FG-2", "", "", "", "", "GD-L1-QC", 1, 45000, ""),
                      ("DA-FG-2", "", "", "", "", "GD-L1-RAK", 1, 45000, "")],
             mat_rows=[("KN-CND 01", "", "", "", "GD-L2", 125, None, ""),
                       ("KN-ZERO", "", "", "", "GD-L2", 5, None, "")])
    errors = []
    out = {"stock_fg": [], "stock_mat": [], "warnings": []}
    run(gw.parse_opening_stock(db, wb, errors, out, {}))
    txt = " | ".join(errors)
    assert "DA-FG-3 belum punya HPP" in txt and "DA-FG-4 NONAKTIF" in txt and "karantina" in txt
    assert "lebih dari sekali" in txt and "KN-ZERO belum berharga" in txt
    fg = out["stock_fg"]
    assert [(r["code"], r["qty"], r["unit_cost"], r["cost_source"]) for r in fg] == [("DA-FG-2", 10, 45000.0, "excel")]
    assert [(r["code"], r["unit_cost"]) for r in out["stock_mat"]] == [("KN-CND-01", 55000.0)]
    assert any("dibaca sebagai KN-CND-01" in w for w in out["warnings"])
    rec = {r["akun"]: r for r in out["opening_stock_recon"]}
    assert rec["1-1404"]["nilai_stok_awal"] == 450000.0 and rec["1-1404"]["selisih"] == 50000.0
    assert rec["1-1401"]["saldo_awal"] == 0.0
    # harga dari sheet MATERIAL di berkas yang sama dihormati
    errors2, out2 = [], {"stock_fg": [], "stock_mat": [], "warnings": []}
    run(gw.parse_opening_stock(db, _wb(mat_rows=[("KN-ZERO", "", "", "", "GD-L2", 5, None, "")]), errors2, out2, {},
                               pending_costs={"KN-ZERO": 12000.0}))
    assert errors2 == [] and out2["stock_mat"][0]["unit_cost"] == 12000.0


def test_stok_awal_apply_writes_identity_wac_and_once(monkeypatch):
    _imap(monkeypatch)
    from core import fg_cost_layers as fcl
    db = _gw_db()
    added, layers = [], []

    async def add(mid, loc, qty, *, meta=None, **k):
        added.append((mid, loc, qty, meta.get("inventory_category"), meta.get("ownership")))
        return {}

    async def push(db_, **kw):
        layers.append(kw)
        await db_.fg_cost_layers.insert_one({"id": "ly1"})
        return {"id": "ly1"}

    async def onhand(*a, **k):
        return 0.0
    monkeypatch.setattr(stock_service, "add", add)
    monkeypatch.setattr(stock_service, "get_onhand", onhand)
    monkeypatch.setattr(fcl, "push_layer", push)
    parsed = {"stock_fg": [{"code": "DA-FG-2", "material_id": "FG2", "location_id": "LRAK", "location_code": "GD-L1-RAK",
                            "qty": 10, "kind": "fg", "unit_cost": 45000.0, "cost_source": "excel", "components": None}],
              "stock_mat": [{"code": "KN-ZERO", "material_id": "KN9", "location_id": "L2", "location_code": "GD-L2",
                             "qty": 5, "kind": "bahan", "unit_cost": 12000.0, "cost_source": "excel",
                             "set_unit_cost": True}]}
    res = run(gw.apply_opening_stock(db, parsed, USER, {"id": "u1"}))
    assert res["rows"] == 2 and res["value"] == 450000.0 + 60000.0
    assert added == [("FG2", "LRAK", 10, "fg_internal", "cv_da"), ("KN9", "L2", 5, "raw_material", "cv_da")]
    assert layers[0]["unit_cost"] == 45000.0 and layers[0]["qty"] == 10
    assert db.fg_cost_layers.docs[0]["gl_basis"] == "saldo_awal"
    assert next(m for m in db.rahaza_materials.docs if m["id"] == "KN9")["unit_cost"] == 12000.0
    again = run(gw.apply_opening_stock(db, parsed, USER, {"id": "u1"}))
    assert again["rows"] == 0 and again["skipped"] == ["DA-FG-2", "KN-ZERO"] and len(added) == 2


# ═════════════════════════ B3 — impor roll kain ═════════════════════════
def test_per_roll_qty_average_and_validation():
    assert fri.per_roll_qty(None, "kg") == (25.0, True)
    assert fri.per_roll_qty("", "yard") == (115.0, True)
    assert fri.per_roll_qty(None, "meter") == (105.16, True)
    assert fri.per_roll_qty("24,5", "kg") == (24.5, False)
    for bad, uom in ((0, "kg"), (-1, "kg"), (None, "rol")):
        with pytest.raises(ValueError):
            fri.per_roll_qty(bad, uom)


def _roll_wb(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = fri.SHEET
    ws.append(fri.COLS)
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _roll_db():
    db = _gw_db()
    db.rahaza_materials.docs += [
        {"id": "KY", "code": "KN-YRD", "name": "Kain yard", "type": "fabric", "unit": "yard", "unit_cost": 20000.0,
         "active": True},
        {"id": "AC", "code": "A-KCG", "name": "Kancing", "type": "accessory", "unit": "pcs", "unit_cost": 100,
         "active": True}]
    return db


def test_roll_import_parse_groups_average_and_guards():
    db = _roll_db()
    data = _roll_wb([("KN-CND-01", "", "", "GD-L2", "LOT1", 3, 24.5, ""),
                     ("KN-CND-01", "", "", "GD-L2", "LOT2", 2, None, ""),
                     ("KN-YRD", "", "", "GD-L2", "", 1, None, ""),
                     ("KN-ZERO", "", "", "GD-L2", "", 1, 20, ""),
                     ("A-KCG", "", "", "GD-L2", "", 1, 5, ""),
                     ("KN-CND-01", "", "", "GD-L1-QC", "", 1, 20, ""),
                     ("KN-YRD", "", "", "GD-L2", "", 1.5, None, ""),
                     ("KN-YRD", "", "", "GD-L2", "", None, None, "")])
    res = run(fri.parse(db, data))
    txt = " | ".join(res["errors"])
    assert "KN-ZERO belum berharga" in txt and "A-KCG bukan kain" in txt and "karantina" in txt
    assert "bilangan bulat" in txt and not res["ok"]
    g = {x["code"]: x for x in res["groups"]}
    assert (g["KN-CND-01"]["rolls"], g["KN-CND-01"]["qty"], g["KN-CND-01"]["average_rolls"]) == (5, 123.5, 2)
    assert (g["KN-YRD"]["qty"], g["KN-YRD"]["uom"], g["KN-YRD"]["average_rolls"]) == (115.0, "yard", 1)
    assert res["totals"]["average_rolls"] == 3 and any("rata-rata" in w for w in res["warnings"])
    clean = _roll_wb([("KN-CND-01", "", "", "GD-L2", "LOT1", 3, 24.5, "")])
    a, b = run(fri.parse(db, clean)), run(fri.parse(db, clean))
    assert a["ok"] and a["batch_key"] == b["batch_key"]                  # kunci idempoten stabil
    # kain×lokasi yang sudah berstok / sudah stok awal ditolak
    db.rahaza_material_stock.docs.append({"material_id": "KN1", "location_id": "L2", "qty": 10})
    assert "sudah ada stok" in " ".join(run(fri.parse(db, clean))["errors"])
    db.rahaza_material_stock.docs.clear()
    db.rahaza_material_movements.docs.append({"type": "opening", "material_id": "KN1", "to_location_id": "L2"})
    assert "sudah punya stok awal" in " ".join(run(fri.parse(db, clean))["errors"])


def test_roll_import_session_final_activates_or_cancels_rolls():
    db = fm.FakeDB()
    db[fri.IMPORTS].docs.append({"id": "I1", "status": fri.ST_AWAITING, "session_ids": ["S1", "S2"]})
    db[fri.fre.ROLLS].docs += [{"id": "r1", "opening_session_id": "S1", "status": fri.PENDING, "remaining_kg": 25},
                               {"id": "r2", "opening_session_id": "S2", "status": fri.PENDING, "remaining_kg": 25}]
    run(fri.on_session_final(db, {"id": "S1", "roll_import_id": "I1"}, "approved"))
    assert db[fri.fre.ROLLS].docs[0]["status"] == "in_stock" and db[fri.IMPORTS].docs[0]["status"] == fri.ST_AWAITING
    run(fri.on_session_final(db, {"id": "S2", "roll_import_id": "I1"}, "rejected"))
    r2 = db[fri.fre.ROLLS].docs[1]
    assert (r2["status"], r2["remaining_kg"]) == ("cancelled", 0.0) and db[fri.IMPORTS].docs[0]["status"] == fri.ST_PARTIAL
    assert run(fri.on_session_final(db, {"id": "S9"}, "approved")) == {}


def test_locked_roll_cannot_be_issued():
    from routes.wms_fabric_rolls import _assert_usable
    with pytest.raises(HTTPException) as e:
        _assert_usable({"roll_no": "RL-1", "status": "pending_opening"})
    assert "persetujuan stok awal" in e.value.detail
    _assert_usable({"roll_no": "RL-2", "status": "in_stock"})


# ═════════════════════════ G13 — skrip hapus retur demo ═════════════════════════
def test_g13_retur_demo_script_preview_apply_and_guards(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "hapus_retur_demo", os.path.join(BACKEND, "scripts", "migrations", "2026_11_09_hapus_retur_demo.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    db = fm.FakeDB()
    db.marketing_returns.docs += [
        {"id": "R1", "created_by": "system", "order_id": "X-1", "date": "2026-08-20"},
        {"id": "R2", "created_by": "system", "order_id": "X-2", "catalog_item_id": "C1"},
        {"id": "R3", "created_by": "pic@toko", "order_id": "X-3"},
        {"id": "R4", "created_by": "system", "order_id": "ADA"},
        {"id": "R5", "created_by": "system", "order_id": "X-5"},
        {"id": "R6", "created_by": "system", "order_id": "X-6"}]
    db.marketing_orders.docs.append({"order_id": "ADA"})
    db.rahaza_credit_notes.docs.append({"return_id": "R5"})
    db.wh_returns.docs += [{"id": "W1", "source_marketing_return_id": "R1", "status": "Pending"},
                           {"id": "W6", "source_marketing_return_id": "R6", "status": "Resolved", "restocked": True}]
    prev = run(mod.run(db, apply=False))
    assert (prev["demo"], prev["kept"], prev["wh_jobs"]) == (1, 4, 1) and len(db.marketing_returns.docs) == 6
    res = run(mod.run(db, apply=True, cadangan=str(tmp_path)))
    assert res["deleted"] == 1 and res["deleted_wh"] == 1 and os.path.exists(res["backup"])
    assert sorted(d["id"] for d in db.marketing_returns.docs) == ["R2", "R3", "R4", "R5", "R6"]
    assert [d["id"] for d in db.wh_returns.docs] == ["W6"]
    assert run(mod.run(db, apply=True, cadangan=str(tmp_path)))["deleted"] == 0           # idempoten
