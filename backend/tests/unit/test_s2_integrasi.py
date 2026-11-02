"""Uji unit HERMETIK tindak lanjut integrasi tahap 2 (2026-11-02) — butir 1–18.

Angka harapan DIHITUNG TANGAN:
  * Balik keputusan retur (butir 2): stok 10 @100 → restock retur 2 @WAC 100 → terima 8 @150
      WAC = (12 × 100 + 8 × 150) / 20 = 120 ; batal restock 2 @100 (biaya asal):
      nilai 20 × 120 − 2 × 100 = 2.200 → WAC 2.200 / 18 = 122,2222 ; GL 1-1404 = 1.000 + 200 + 1.200 − 200
      = 2.200 = 18 × 122,2222 (selisih 0).
  * Retur "Dibuang" (butir 1): 1 pcs × WAC 50.000 → Dr 6-1300 / Cr 5-1000 50.000.
  * Penyesuaian FG ±1 (butir 4): WAC 50.000 → Dr/Cr 1-1404 vs 5-1950 50.000; aksesoris → 1-1402.
  * Keluarkan Stok FG 2 pcs sampel (butir 18): 2 × WAC 50.000 = 100.000 → Dr 6-1130 / Cr 1-1404.
  * MI maklon (butir 16): BOM 0,5 kancing DA/pcs × 40 pcs = 20; MI lain sudah 12 → MI 8.

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_s2_integrasi.py -q
"""
import asyncio
import importlib.util
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from p3_fakes import FakeDB as P3DB, FakeRequest as P3Req  # noqa: E402
from core import coa_bindings as cb  # noqa: E402
from core import fg_cost_layers as fcl  # noqa: E402
from core import returns_bridge as rb  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402
from utils import notif_unified as nu  # noqa: E402

DEFAULT_MAP = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}
USER = {"id": "u-fin", "name": "Finance Uji", "email": "fin@x", "role": "superadmin"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def posting(monkeypatch):
    """Mesin posting palsu memakai profil BAWAAN (DEFAULT_PROFILES) — jurnal dicatat & disimpan ke DB."""
    jes = []
    state = {"map": {k: dict(v) for k, v in DEFAULT_MAP.items()}}

    async def mapping(db, key):
        return dict(state["map"].get(key, {}))

    async def none(*a, **k):
        return None

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2), lines
        je = {"id": f"je-{len(jes) + 1}", "je_number": f"JE-{len(jes) + 1}", "status": "posted",
              "source_module": mod, "source_ref": ref, "memo": memo, "lines": lines}
        jes.append(je)
        await db.rahaza_journal_entries.insert_one(dict(je))
        return {"ok": True, "je_id": je["id"], "je_number": je["je_number"]}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)

    def gl(code):
        return round(sum(ln["debit"] - ln["credit"] for je in jes for ln in je["lines"]
                         if ln["account_code"] == code), 2)

    def lines(i=-1):
        return [(ln["account_code"], round(ln["debit"], 2), round(ln["credit"], 2)) for ln in jes[i]["lines"]]
    return types.SimpleNamespace(jes=jes, gl=gl, lines=lines, state=state)


def _wac_db(**extra):
    return P3DB(
        rahaza_materials=[{"id": "FG1", "code": "DA-FG-1", "type": "fg", "hpp": 30000.0}],
        rahaza_material_stock=[{"id": "st1", "material_id": "FG1", "location_id": "LOC-FG", "qty": 0.0,
                                "inventory_category": "fg_internal", "ownership": "cv_da"}],
        rahaza_locations=[{"id": "LOC-FG", "code": "ZNA-FG"},
                          {"id": "LOC-Q", "code": "ZNA-KARANTINA", "storage_role": "karantina"}],
        **extra)


def _stock(db, delta, mid="FG1", loc="LOC-FG"):
    row = next(r for r in db.rahaza_material_stock.docs if r["material_id"] == mid and r["location_id"] == loc)
    row["qty"] = round(row["qty"] + delta, 4)


def _wac_fg(**kw):
    return {"id": "FG1", "code": "DA-FG-1", "type": "fg", "unit": "pcs", "unit_cost": 50000.0,
            "wac_components": {"material": 40000.0, "labor": 10000.0, "overhead": 0.0}, **kw}


# ══════════════════════════════ A. WAC barang jadi ════════════════════════════
def test_01_dispose_books_wac_loss_and_reversal_reverses_it(posting, monkeypatch):
    import routes.dewi_wh_returns as wr
    db = P3DB(rahaza_materials=[_wac_fg()],
              wh_returns=[{"id": "W1", "return_code": "RET-1", "status": "Inspected", "qty": 2, "received_qty": 2,
                           "material_id": "FG1", "fg_material_id": "FG1", "timeline": []}])

    async def auth(_r):
        return {"id": "u-gd", "name": "Gudang", "role": "admin_gudang"}
    monkeypatch.setattr(wr, "require_auth", auth)
    monkeypatch.setattr(wr, "get_db", lambda: db)
    out = run(wr.resolve_return("W1", P3Req({"action_taken": rb.ACTION_DISPOSE, "restock_qty": 1})))
    doc = db.wh_returns.docs[0]
    assert doc["status"] == "Resolved" and doc["loss_je_id"] == "je-1" and doc["loss_kind"] == "disposed"
    assert doc["loss_amount"] == 50000.0 and doc["disposed_qty"] == 1 and not doc.get("restocked")
    assert posting.lines() == [("6-1300", 50000.0, 0), ("5-1000", 0, 50000.0)]
    assert posting.jes[-1]["source_ref"] == "whret_disposed:W1"
    assert "beban Rp 50,000" in doc["timeline"][-1]["note"] and out["action_taken"] == rb.ACTION_DISPOSE
    # qty dibuang dibatasi qty diterima
    db.wh_returns.docs.append({"id": "W9", "return_code": "RET-9", "status": "Inspected", "received_qty": 1,
                               "material_id": "FG1"})
    with pytest.raises(HTTPException) as e:
        run(wr.resolve_return("W9", P3Req({"action_taken": rb.ACTION_DISPOSE, "restock_qty": 3})))
    assert e.value.status_code == 400
    # Balik Keputusan → jurnal pembalik kerugian, tanpa stok keluar
    res = run(rb.reverse_decision(db, "W1", actor={"name": "g"}, reason="salah putus", reopen=False))
    assert res["stock_out"] is None and res["journals"][0]["ok"] and res["wac"] is None
    assert posting.lines() == [("6-1300", 0, 50000.0), ("5-1000", 50000.0, 0)]


def test_02_reverse_restock_restores_wac_with_zero_difference(posting, monkeypatch):
    db = _wac_db()
    _stock(db, 10)
    run(fcl.push_layer(db, material_id="FG1", qty=10, unit_cost=100.0, ref={"type": "cmt_receipt"}))
    _stock(db, 2)
    v = run(rb._value_restock(db, {"id": "W2", "return_code": "RET-2"}, "FG1", 2, {"name": "g"}))
    assert v["hpp_unit_cost"] == 100.0 and v["cogs_je_id"]
    _stock(db, 8)
    run(fcl.push_layer(db, material_id="FG1", qty=8, unit_cost=150.0, ref={"type": "cmt_receipt"}))
    assert run(fcl.wac_state(db, "FG1"))["unit_cost"] == 120.0
    db.wh_returns.docs.append({"id": "W2", "return_code": "RET-2", "status": "Resolved", "restocked": True,
                               "restock_qty": 2, "restock_location_id": "LOC-FG", "restock_location_code": "ZNA-FG",
                               "stock_effect": "sellable", "material_id": "FG1", "action_taken": rb.ACTION_RESTOCK,
                               **v})

    async def issue(mid, loc, qty, **kw):
        _stock(db, -qty, mid, loc)
        return {"qty": next(r["qty"] for r in db.rahaza_material_stock.docs if r["location_id"] == loc)}
    monkeypatch.setattr(rb.stock_service, "issue", issue)
    res = run(rb.reverse_decision(db, "W2", actor={"name": "g"}, reason="Marketing menolak", reopen=False))
    assert res["wac"]["unit_cost"] == 122.2222 and res["wac"]["adjustment_fg"] == 0
    assert res["wac"]["adjustment_je_id"] is None
    mat = run(db.rahaza_materials.find_one({"id": "FG1"}))
    assert mat["unit_cost"] == 122.2222
    gl = 10 * 100 + 8 * 150 + posting.gl("1-1404")                      # WIP→FG di luar mesin palsu
    assert gl == 2200.0 and round(18 * mat["unit_cost"], 2) == 2200.0
    assert posting.lines() == [("1-1404", 0, 200.0), ("5-1000", 200.0, 0)]


def test_03_apply_model_cost_keeps_catalog_wac(monkeypatch):
    from core import product_costing as pc
    db = P3DB(rahaza_materials=[_wac_fg(id="FGW"), {"id": "FGN", "type": "fg", "hpp": 1.0}],
              rahaza_models=[{"id": "M1", "code": "M1", "name": "Model"}],
              marketing_catalog_items=[{"id": "CW", "fg_material_id": "FGW", "hpp": 50000.0, "hpp_source": "wac"},
                                       {"id": "CN", "fg_material_id": "FGN", "hpp": 1.0, "hpp_source": "bom"}])
    color = dict(bom_id="B1", hpp_unit=47000.0, computable=True, material_cost=30000.0, fabric_cost=25000.0,
                 accessory_cost=5000.0, other_cost=0.0, confidence="ok", unvalued_count=0, bom_version=1,
                 bad_line_statuses=[], bom_color="Hitam", bom_color_match=True, color="Hitam")
    d = {"sizes": [{"size_id": "S", "size_code": "S", "cmt_cost": 15000.0, "internal_labor_cost": 2000.0,
                    "overhead_cost": 0.0, "fg_variants": [],
                    "colors": [{**color, "fg_id": "FGW", "code": "W"}, {**color, "fg_id": "FGN", "code": "N"}]}],
         "model": {"code": "M1", "name": "Model"}, "cmt": {"rate": 15000, "source": "x"},
         "internal_labor": {"rate": 2000, "source": "x"}, "overhead": {"rate": 0, "included": False},
         "gaps": [], "gap_count": 0}

    async def compute(*a, **k):
        return d
    monkeypatch.setattr(pc, "compute_model_cost", compute)
    out = run(pc.apply_model_cost(db, "M1", {"id": "u", "name": "u"}))
    items = {c["id"]: c for c in db.marketing_catalog_items.docs}
    assert items["CW"]["hpp"] == 50000.0 and items["CW"]["hpp_source"] == "wac"      # WAC tidak ditimpa
    assert items["CN"]["hpp"] == 47000.0 and items["CN"]["hpp_source"] == pc.HPP_SOURCE_BOM
    assert [a["catalog_kept_wac"] for a in out["applied"]] == [1, 0]
    fg = {m["id"]: m for m in db.rahaza_materials.docs}
    assert fg["FGW"]["hpp"] == 47000.0 and fg["FGW"]["unit_cost"] == 50000.0       # hpp = estimasi; WAC utuh


def _inv_db():
    return P3DB(rahaza_materials=[_wac_fg(), {"id": "ACC1", "code": "KCG", "type": "accessory", "unit_cost": 2000.0},
                                  {"id": "FAB1", "code": "KAIN", "type": "fabric", "unit_cost": 30000.0}])


def test_04_inventory_account_follows_item_kind(posting):
    db = _inv_db()
    run(rp.post_inventory_adjust(db, {"id": "a1", "material_id": "FG1", "qty": 1}, USER))
    assert posting.lines() == [("1-1404", 50000.0, 0), ("5-1950", 0, 50000.0)]
    run(rp.post_inventory_adjust(db, {"id": "a2", "material_id": "FG1", "qty": -1}, USER))
    assert posting.lines() == [("5-1950", 50000.0, 0), ("1-1404", 0, 50000.0)]
    run(rp.post_inventory_adjust(db, {"id": "a3", "material_id": "ACC1", "qty": -1}, USER))
    assert posting.lines() == [("5-1950", 2000.0, 0), ("1-1402", 0, 2000.0)]
    run(rp.post_inventory_adjust(db, {"id": "a4", "material_id": "ACC1", "qty": -2, "adjustment_reason": "scrap"}, USER))
    assert posting.lines() == [("6-4300", 4000.0, 0), ("1-1402", 0, 4000.0)]
    run(rp.post_inventory_adjust(db, {"id": "a5", "material_id": "FG1", "qty": -1, "adjustment_reason": "rusak"}, USER))
    assert posting.lines() == [("6-4300", 50000.0, 0), ("1-1404", 0, 50000.0)]
    run(rp.post_inventory_adjust(db, {"id": "a6", "material_id": "FAB1", "qty": 1}, USER))
    assert posting.lines() == [("1-1401", 30000.0, 0), ("5-1950", 0, 30000.0)]


def test_04b_accessory_receipt_and_usage_use_1_1402(posting):
    db = _inv_db()
    run(rp.post_inventory_receive(db, {"id": "r1", "material_id": "ACC1", "qty": 10, "unit_cost": 2000}, USER))
    assert posting.lines() == [("1-1402", 20000.0, 0), ("2-1150", 0, 20000.0)]
    run(rp.post_inventory_receive(db, {"id": "r2", "material_id": "FAB1", "qty": 2, "unit_cost": 30000}, USER))
    assert posting.lines()[0] == ("1-1401", 60000.0, 0)
    run(rp.post_accessory_issue(db, {"id": "m1", "material_id": "ACC1", "qty": -3, "unit_cost": 2000}, USER))
    assert posting.lines() == [("1-1403", 6000.0, 0), ("1-1402", 0, 6000.0)]
    mi = {"id": "MI1", "mi_number": "MI-1", "items": [{"material_id": "FAB1", "qty_issued": 2},
                                                       {"material_id": "ACC1", "qty_issued": 5}]}
    db.rahaza_material_issues.docs.append(dict(mi))
    run(rp.post_inventory_issue(db, mi, USER))
    assert posting.lines() == [("1-1403", 70000.0, 0), ("1-1401", 0, 60000.0), ("1-1402", 0, 10000.0)]


def test_04c_missing_kind_role_is_refused_and_roles_registered(posting):
    db = _inv_db()
    posting.state["map"]["inventory_adjust"].pop("inventory_accessory")
    r = run(rp.post_inventory_adjust(db, {"id": "x1", "material_id": "ACC1", "qty": 1}, USER))
    assert r["ok"] is False and "inventory_adjust.inventory_accessory" in r["error"] and not posting.jes
    assert DEFAULT_MAP["inventory_receive"]["debit_inventory_accessory"] == "1-1402"
    assert DEFAULT_MAP["inventory_issue"]["credit_inventory_accessory"] == "1-1402"
    assert DEFAULT_MAP["inventory_scrap"]["credit_inventory_fg"] == "1-1404"
    cons = cb.role_consumers()
    assert cons["inventory_adjust.inventory_fg"][0]["reads_profile"] is True
    assert cons["inventory_adjust.inventory_fg"][0]["code"] == "1-1404"
    assert cons["fg_issue.debit_sample"][0]["code"] == "6-1130"
    # registri keterikatan: 1-1402 kini terikat lewat profil posting
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs.append({"id": "a", "code": "1-1402", "name": "Persediaan Aksesoris", "type": "ASSET",
                                       "is_group": False, "active": True, "flags": {}})
    for p in pp.DEFAULT_PROFILES:
        d.rahaza_posting_profiles.docs.append({"event_type": p["event_type"], "active": True,
                                               "mapping": dict(p["mapping"])})
    bl = run(cb.collect_bindings(d, ["1-1402"]))["1-1402"]
    srcs = {b["source"] for b in bl if b["kind"] == "profil"}
    assert {"rahaza_posting_profiles.inventory_adjust.inventory_accessory",
            "rahaza_posting_profiles.inventory_receive.debit_inventory_accessory"} <= srcs


def test_05_fe_labels_wac():
    fe = os.path.join(ROOT, "frontend", "src", "components", "erp")
    if not os.path.isdir(fe):
        pytest.skip("frontend/src tidak tersedia")
    cat = open(os.path.join(fe, "marketing", "CatalogItemsView.jsx"), encoding="utf-8").read()
    assert "r.hpp_source_label" in cat and "'batch FIFO'" not in cat
    ds = open(os.path.join(fe, "sales", "DirectSalesModule.jsx"), encoding="utf-8").read()
    assert "['wac', 'fifo_batch', 'mixed'].includes(r.cogs_basis)" in ds
    fv = open(os.path.join(fe, "RahazaFGValuationModule.jsx"), encoding="utf-8").read()
    assert "Nilai WAC" in fv and "Nilai Lapisan FIFO" not in fv


def test_06_integration_tests_expect_wac():
    tests = os.path.dirname(HERE)
    for name in ("test_iter96_cogs_fifo_journal.py", "test_iter110_bank_recon.py",
                 "test_iter118_sales_returns_report.py"):
        src = open(os.path.join(tests, name), encoding="utf-8").read()
        assert '== "fifo_batch"' not in src, name
        assert '"wac"' in src, name


# ══════════════════════════════ B. Bagan Akun ═════════════════════════════════
def _acc(code, active=True, group=False, type_="EXPENSE"):
    return {"id": f"id-{code}", "code": code, "name": f"Akun {code}", "type": type_, "is_group": group,
            "active": active, "flags": {}}


def test_07_settlement_travel_yearend_opening_read_profile_roles(monkeypatch):
    import routes.marketing_settlements as ms
    import routes.employee_travel_settlements as ets
    import routes.rahaza_year_end as ye
    from core import opening_balance as ob
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs += [_acc("1-1303-SHP", type_="ASSET"), _acc("4-1111", type_="REVENUE"),
                                   _acc("6-1119"), _acc("3-2100", type_="EQUITY")]
    d.rahaza_posting_profiles.docs += [
        {"event_type": "marketplace_settlement", "active": True,
         "mapping": {"debit_platform_fee": "4-1499", "debit_ads_shopee": "6-1119"}},
        {"event_type": "employee_travel", "active": True, "mapping": {"debit_travel_expense": "6-3499"}},
        {"event_type": "year_end_close", "active": True, "mapping": {"credit_retained_earnings": "3-2100"}},
        {"event_type": "subledger_opening_balance", "active": True,
         "mapping": {"control_ar_customer": "1-1309", "credit_retained_earnings_balancing": "3-2100"}}]
    out = run(ms._resolve_coa(d, {"platform": "shopee", "account_name": "T", "ar_account_code": "1-1303-SHP",
                                  "coa_revenue_code": "4-1111"}))
    assert out["codes"]["platform_fee"] == "4-1499" and out["sources"]["platform_fee"] == "profil"
    assert out["codes"]["ads"] == "6-1119" and out["sources"]["ads"] == "platform"
    assert out["codes"]["returns"] == ms.COA["returns"] and out["sources"]["returns"] == "global"
    gl = run(ets._travel_codes(d))
    assert gl == {"expense": "6-3499", "advance": ets.GL_EMPLOYEE_ADVANCE, "bank": ets.GL_BANK_DEFAULT}

    async def agg(*a, **k):
        return {}
    monkeypatch.setattr(ye, "_aggregate_by_account", agg)
    pv = run(ye._preview(d, 2025))
    assert pv["retained_earnings_account"] == "3-2100" and pv["retained_earnings_ok"] is True
    rs = run(ob.relation_sheets(d))
    assert rs[0][:2] == ("PIUTANG_PELANGGAN", "1-1309") and rs[1][1] == "1-1305"
    assert run(ob.retained_earnings_code(d)) == "3-2100"
    for src in cb.CONSTANT_SOURCES:
        if src["module"] in ("routes.marketing_settlements", "routes.employee_travel_requests",
                             "routes.employee_travel_settlements", "routes.rahaza_year_end", "core.opening_balance") \
                and src.get("role"):
            assert src.get("reads_profile") is True, src


def _settle_env(monkeypatch, d):
    import routes.marketing_settlements as ms
    import routes.rahaza_journals as rj

    async def fin(_r):
        return USER

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(ms, "_require_finance", fin)
    monkeypatch.setattr(ms, "get_db", lambda: d)
    monkeypatch.setattr(ms, "assert_linked_je_owned", noop)
    monkeypatch.setattr(rj, "_check_period_open", noop)
    return ms


def test_08_settlement_and_withdrawal_drafts_revalidated(monkeypatch):
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs += [_acc("4-1400", active=False), _acc("1-1303-SHP", type_="ASSET")]
    lines = [{"account_code": "4-1400", "account_name": "lama", "debit": 1000, "credit": 0},
             {"account_code": "1-1303-SHP", "debit": 0, "credit": 1000}]
    d.rahaza_journal_entries.docs += [{"id": "je-s", "je_number": "JE-S", "status": "draft", "date": "2026-11-02",
                                       "lines": lines},
                                      {"id": "je-w", "je_number": "JE-W", "status": "draft", "date": "2026-11-02",
                                       "lines": lines}]
    d.marketing_settlements.docs.append({"id": "S1", "je_id": "je-s", "account_id": "A1"})
    ms = _settle_env(monkeypatch, d)
    with pytest.raises(HTTPException) as e:
        run(ms.post_settlement_journal("S1", fm.FakeRequest()))
    assert e.value.status_code == 400 and "JE-S" in e.value.detail and "4-1400" in e.value.detail
    assert d.rahaza_journal_entries.docs[0]["status"] == "draft" and d.rahaza_journal_lines.docs == []
    d.rahaza_coa_accounts.docs[0]["active"] = True
    out = run(ms.post_settlement_journal("S1", fm.FakeRequest()))
    assert out["ok"] and {ln["account_name"] for ln in d.rahaza_journal_lines.docs} == {"Akun 4-1400", "Akun 1-1303-SHP"}
    # penarikan: aturan yang sama (draf yang akunnya dinonaktifkan ditolak)
    src = open(os.path.join(BACKEND, "routes", "marketing_withdrawals.py"), encoding="utf-8").read()
    body = src[src.index("async def post_withdrawal_journal"):]
    assert "revalidate_draft_lines(db, je)" in body.split("_mirror_lines(db, je)")[0]


def test_09_petty_cash_has_no_6_2200_fallback(monkeypatch):
    import routes.rahaza_petty_cash as pcm
    jes = []
    maps = {"petty_cash_replenish": {"debit_petty_cash": "1-1101"}, "petty_cash_expense": {}}

    async def gm(db, et):
        return dict(maps.get(et, {}))

    async def none(*a, **k):
        return None

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        jes.append(lines)
        return {"ok": True, "je_id": "je", "je_number": "JE"}
    monkeypatch.setattr(pcm, "get_mapping", gm)
    monkeypatch.setattr(pcm, "_find_existing_je", none)
    monkeypatch.setattr(pcm, "_create_posted_je", create)
    d = fm.FakeDB()
    r = run(pcm._post_petty_cash_txn(d, {"id": "t1", "txn_type": "expense", "amount": 5000, "category": "Lain"}, USER))
    assert r["ok"] is False and "debit_expense_default" in r["error"] and not jes
    r = run(pcm._post_petty_cash_txn(d, {"id": "t2", "txn_type": "return", "amount": 5000}, USER))
    assert r["ok"] is False and "debit_expense_default" in r["error"]
    d.employee_expense_gl_mappings.docs.append({"category": "Lain", "gl_account_code": "6-2950", "is_active": True})
    assert run(pcm._post_petty_cash_txn(d, {"id": "t3", "txn_type": "expense", "amount": 5000,
                                            "category": "Lain"}, USER))["ok"]
    assert jes[-1][0]["account_code"] == "6-2950"
    assert not any(c == "6-2200" for _f, c, *_ in cb.INLINE_CODES)


def _load_script(name):
    spec = importlib.util.spec_from_file_location(f"_uji_{name}", os.path.join(ROOT, "scripts", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_10_verify_data_integrity_runs_inv_coa_ref():
    vdi = _load_script("verify_data_integrity")
    fails, warns = vdi.coa_ref_violations({"dangling_refs": [{"code": "1-9999", "refs": ["Profil Posting: x"]}],
                                           "inactive_targets": [], "group_targets": [{"code": "6-1100", "refs": []}],
                                           "fallback_warnings": [{"role": "a.b", "code": "1-1101", "source": "s"}]})
    assert fails == ["tidak ada: 1-9999 ← Profil Posting: x", "grup: 6-1100 ← -"] and len(warns) == 1
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs.append(_acc("6-2900"))
    d.rahaza_posting_profiles.docs.append({"event_type": "expense", "active": True,
                                           "mapping": {"debit_expense_default": "6-2900", "credit_cash_default": "1-9999"}})
    before = dict(vdi.results)
    rep = run(vdi.check_coa_ref(d))
    assert "1-9999" in {r["code"] for r in rep["dangling_refs"]}
    assert vdi.results["fail"] == before["fail"] + 1


def test_11_admin_seed_uses_startup_seed_contra_normal_balance():
    from routes.rahaza_admin_helpers import _seed_coa
    d = fm.FakeDB()
    n = run(_seed_coa(d, {"id": "u", "name": "u"}))
    by = {a["code"]: a for a in d.rahaza_coa_accounts.docs}
    assert n == len(by) > 50
    assert by["1-2501"]["normal_balance"] == "CREDIT" and by["4-1200"]["normal_balance"] == "DEBIT"
    assert "5-4100" in by                                                # akun khas DA ikut (DA_UNIFIED_ACCOUNTS)


# ══════════════════════════════ C. Notifikasi ═════════════════════════════════
HR1 = {"id": "u-hr1", "role": "hr", "name": "HR Satu", "email": "hr1@x"}
HR2 = {"id": "u-hr2", "role": "hr", "name": "HR Dua", "email": "hr2@x"}
FIN = {"id": "u-fin2", "role": "staff_keuangan", "name": "Keu", "email": "keu@x"}
ACC = {"id": "u-acc", "role": "accounting", "name": "Akunting", "email": "acc@x"}
GUD = {"id": "u-gud", "role": "admin_gudang", "name": "Gudang", "email": "gud@x"}


def _actions(d, subtype):
    return [n for n in d.notifications.docs if n.get("subtype") == subtype]


def _sees(d, user, n):
    return nu.notif_visible_to(n, user) and any(
        x["id"] == n["id"] for x in d.notifications.docs if fm.match(x, nu.notif_audience_query(user)))


def test_12a_overtime_action_to_hr_without_submitter_and_auto_close(monkeypatch):
    import routes.rahaza_overtime as ot
    d = fm.FakeDB()
    d.rahaza_employees.docs.append({"id": "emp-h", "name": "HR Satu", "user_id": "u-hr1", "active": True})
    d.users.docs.append({"id": "u-hr1", "employee_id": "emp-h", "role": "hr"})
    who = {"u": HR1}

    async def auth(_r):
        return dict(who["u"])
    monkeypatch.setattr(ot, "require_auth", auth)
    monkeypatch.setattr(ot, "get_db", lambda: d)
    out = run(ot.create_request(fm.FakeRequest({"employee_id": "emp-h", "date": "2026-11-02",
                                                "start_time": "17:00", "end_time": "19:00"})))
    (n,) = _actions(d, "overtime_request_submitted")
    assert n["kind"] == "action" and n["source_collection"] == "rahaza_overtime_requests"
    assert n["meta"]["target_roles"] == ["hr", "hr_manager", "superadmin"]
    assert "u-hr1" in n["meta"]["exclude_user_ids"]
    assert not _sees(d, HR1, n) and _sees(d, HR2, n)                  # pengaju HR tidak menerima
    who["u"] = HR2
    run(ot.approve_request(out["overtime"]["id"], fm.FakeRequest()))
    assert _actions(d, "overtime_request_submitted")[0]["resolved_at"] is not None


def test_12b_kasbon_hr_then_finance_actions(monkeypatch):
    import routes.dewi_kasbon as kas
    d = fm.FakeDB()
    d.rahaza_employees.docs.append({"id": "emp-a", "name": "Ani", "user_id": "u-ani", "active": True})
    d.users.docs += [{"id": "u-ani", "email": "ani@x", "employee_id": "emp-a", "role": "tim_packing"}]
    ani = {"id": "u-ani", "role": "tim_packing", "name": "Ani", "email": "ani@x", "employee_id": "emp-a"}

    async def num(*a, **k):
        return "KSB-0001"
    monkeypatch.setattr(kas, "issue_number", num)
    out = run(kas.submit_kasbon_request(fm.FakeRequest({"type": "kasbon", "amount": 300000}), db=d, user=ani))
    rid = out["request"]["id"]
    (rev,) = _actions(d, "kasbon_submitted")
    assert rev["kind"] == "action" and rev["meta"]["target_roles"] == ["hr", "hr_manager", "staff_hr", "superadmin"]
    assert rev["meta"]["exclude_user_ids"] == ["u-ani"] and _sees(d, HR1, rev) and not _sees(d, ani, rev)
    run(kas.hr_review_kasbon(rid, fm.FakeRequest({"action": "approve"}), db=d, user=HR1))
    assert _actions(d, "kasbon_submitted")[0]["resolved_at"] is not None
    (dis,) = _actions(d, "kasbon_disburse_pending")
    assert dis["kind"] == "action" and dis["source_collection"] == "dewi_kasbon_requests"
    assert dis["meta"]["target_roles"] == ["accounting", "manager_keuangan", "staff_keuangan", "superadmin"]
    assert _sees(d, FIN, dis) and not _sees(d, HR1, dis)
    d.dewi_kasbon_requests.docs[0]["status"] = "disbursed"
    run(kas.close_kasbon_notifs(d, rid))
    assert _actions(d, "kasbon_disburse_pending")[0]["resolved_at"] is not None


def test_12c_payroll_cancel_request_to_finance_without_requester(monkeypatch):
    import routes.rahaza_payroll_runs as runs
    d = fm.FakeDB()
    d.rahaza_payroll_runs.docs.append({"id": "R1", "run_number": "PR-1", "status": "finalized", "period": "2026-10"})
    who = {"u": dict(HR1)}

    async def auth(_r):
        return dict(who["u"])

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(runs, "require_auth", auth)
    monkeypatch.setattr(runs, "get_db", lambda: d)
    monkeypatch.setattr(runs, "log_activity", noop)
    run(runs.cancel_run("R1", fm.FakeRequest({"action": "request", "reason": "salah tarif"})))
    (n,) = _actions(d, "payroll_cancel_requested")
    assert n["kind"] == "action" and n["meta"]["exclude_user_ids"] == ["u-hr1"]
    assert _sees(d, FIN, n) and _sees(d, ACC, n) and not _sees(d, HR1, n)
    who["u"] = dict(FIN)
    run(runs.cancel_run("R1", fm.FakeRequest({"action": "reject", "reason": "tidak perlu"})))
    assert _actions(d, "payroll_cancel_requested")[0]["resolved_at"] is not None


def test_12d_wh_return_pending_to_warehouse_and_closed_on_decision(monkeypatch):
    d = fm.FakeDB()
    seq = {"n": 0}

    async def code(_db):
        seq["n"] += 1
        return f"RET-{seq['n']}"
    monkeypatch.setattr(rb, "_next_code", code)
    run(rb.ensure_rts_returns(d, {"id": "O1", "order_id": "SO-1", "items": [{"sku_code": "X", "quantity": 1}]},
                              actor={"id": "u-mkt", "name": "Toko"}))
    (n,) = _actions(d, "wh_return_pending")
    assert n["kind"] == "action" and n["source_collection"] == "wh_returns"
    assert set(n["meta"]["target_roles"]) == {"admin_aksesoris", "admin_gudang", "spv_packing", "superadmin"}
    assert _sees(d, GUD, n) and not _sees(d, {"id": "u-tp", "role": "tim_packing"}, n)
    d.wh_returns.docs[0]["status"] = "Cancelled"
    run(rb.close_pending_notifs(d, d.wh_returns.docs[0]["id"]))
    assert _actions(d, "wh_return_pending")[0]["resolved_at"] is not None


def test_13_claim_requester_never_gets_own_action(monkeypatch):
    import routes.employee_expense_claims as eec
    d = fm.FakeDB()
    d.rahaza_expense_claims.docs.append({"id": "C1", "claim_number": "CL-1", "employee_id": "u-acc",
                                         "employee_name": "Akunting", "status": "draft", "total_amount": 50000,
                                         "items": [{"amount": 50000}]})

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(eec, "get_db", lambda: d)
    monkeypatch.setattr(eec, "log_activity", noop)
    run(eec.submit_claim("C1", user=dict(ACC)))
    (n,) = _actions(d, "expense_claim_submitted")
    assert "accounting" in n["meta"]["target_roles"] and n["meta"]["exclude_user_ids"] == ["u-acc"]
    other = {"id": "u-acc2", "role": "accounting"}
    assert _sees(d, other, n) and not _sees(d, ACC, n)
    assert nu.notif_audience_query(ACC)["meta.exclude_user_ids"] == {"$ne": "u-acc"}


def test_14_next_actions_filtered_per_role_and_portal(monkeypatch):
    import routes.rahaza_next_actions as na
    names = lambda role: {r.__name__ for r in na.rules_for_role(role)}  # noqa: E731
    assert "rule_setup_empty" in names("superadmin") and "rule_setup_empty" in names("owner")
    assert "rule_setup_empty" not in names("admin_gudang") and "rule_setup_empty" not in names("supervisor_produksi")
    assert names("tim_packing") == set() and names("operator") == set()
    assert {"rule_low_stock_materials", "rule_draft_mi_stale", "rule_wo_without_mi"} <= names("admin_gudang")
    assert "rule_orders_overdue" not in names("admin_gudang")
    assert {"rule_orders_overdue", "rule_qc_fail_rate_today"} <= names("manager_produksi")
    assert "rule_low_stock_materials" in names("supervisor_produksi")
    d = fm.FakeDB()
    acc = {"portals": ["warehouse"], "is_super": False, "role": "tim_packing"}

    async def auth(_r):
        return {"id": "u", "role": acc["role"], "name": "u"}

    async def access(_db, _u):
        return dict(acc)
    import routes.shared as sh
    monkeypatch.setattr(na, "require_auth", auth)
    monkeypatch.setattr(na, "get_db", lambda: d)
    monkeypatch.setattr(sh, "resolve_role_access", access)
    req = types.SimpleNamespace(query_params={"portal": "production"})
    out = run(na.get_next_actions(req))
    assert out["actions"] == [] and out["meta"]["portal_denied"] is True
    req = types.SimpleNamespace(query_params={"portal": "warehouse"})
    out = run(na.get_next_actions(req))
    assert out["actions"] == [] and out["meta"]["rule_count"] == 0     # tim_packing: tidak ada aturan
    acc.update(role="superadmin", is_super=True)
    out = run(na.get_next_actions(types.SimpleNamespace(query_params={"portal": "production"})))
    assert any(c["id"] == "setup-empty" for c in out["actions"])       # DB kosong → hanya super melihat setup


# ══════════════════════════════ 15–18 ═════════════════════════════════════════
def test_15_maklon_portal_may_write_cmt_billing(monkeypatch):
    import middleware.module_permission_gate as gate
    from data.module_catalog import ALSO_PORTALS
    assert "maklon" in ALSO_PORTALS["prod_cmt_billing"]

    async def live(uid):
        return {"id": uid, "role": "admin_maklon"}

    async def rbac(role, uid):
        return [], []

    async def portals(role, uid):
        return ["maklon", "self", "collaboration"]
    monkeypatch.setattr(gate, "_load_live_user", live)
    monkeypatch.setattr(gate, "_load_rbac", rbac)
    monkeypatch.setattr(gate, "_load_portals", portals)
    payload = {"id": "u-mk", "role": "admin_maklon"}
    for method, path in (("POST", "/api/production/cmt-billing/pay-1/post"),
                         ("POST", "/api/production/cmt-billing/pay-1/pay"), ("GET", "/api/production/cmt-billing")):
        assert run(gate.evaluate(method, path, payload)) is None, (method, path)


def test_16_maklon_shipment_issues_only_da_accessories_cumulatively(monkeypatch, posting):
    from core import material_issue_engine as mie
    import routes.rahaza_inventory_shared as ris
    need, notes = mie.maklon_da_need(
        [{"material_name": "Kain klien", "ownership": "client_provided", "material_id": "FAB1", "qty_per_pcs": 1.2},
         {"material_name": "Kancing", "ownership": "cv_da_stock", "material_id": "ACC1", "qty_per_pcs": 0.5, "unit": "pcs"},
         {"material_name": "Label", "ownership": "cv_da_stock", "qty_per_pcs": 1}], 40, {"ACC1": 12})
    assert need == [{"material_id": "ACC1", "qty": 8.0, "bom_unit": "pcs", "name": "Kancing"}]
    assert notes and "Label" in notes[0]
    d = fm.FakeDB()
    d.rahaza_materials.docs += [{"id": "ACC1", "code": "KCG", "type": "accessory", "unit": "pcs", "unit_cost": 2000.0,
                                 "active": True}]
    d.rahaza_material_stock.docs.append({"material_id": "ACC1", "location_id": "LOC-A", "qty": 100})
    d.dewi_maklon_bom.docs.append({"po_id": "PO-M", "materials": [
        {"material_name": "Kain klien", "ownership": "client_provided", "material_id": "FAB1", "qty_per_pcs": 1.2},
        {"material_name": "Kancing", "ownership": "cv_da_stock", "material_id": "ACC1", "qty_per_pcs": 0.5,
         "unit": "pcs"}]})
    d.vendor_shipments.docs += [{"id": "SJ1", "po_id": "PO-M"}, {"id": "SJ2", "po_id": "PO-M"}]
    d.vendor_shipment_items.docs += [{"shipment_id": "SJ1", "qty_sent": 20}, {"shipment_id": "SJ2", "qty_sent": 20}]
    calls = []

    async def fake_issue(db, mi, user, **kw):
        calls.append(kw.get("ref_type"))
        mi = {**mi, "status": "issued", "items": [{**it, "qty_issued": it["qty_required"]} for it in mi["items"]]}
        await db.rahaza_material_issues.update_one({"id": mi["id"]}, {"$set": mi})
        return mi

    async def mino(db, *a, **k):
        return f"MI-{len(d.rahaza_material_issues.docs) + 1}"
    monkeypatch.setattr(mie, "issue_material_issue", fake_issue)
    monkeypatch.setattr(ris, "_gen_mi_number", mino)
    # SJ1 (20 pcs) sudah punya MI lewat jalur lain sebesar 10 kancing
    d.rahaza_material_issues.docs.append({"id": "OLD", "production_po_id": "PO-M", "status": "issued",
                                          "items": [{"material_id": "ACC1", "qty_issued": 10}]})
    res = run(mie.issue_for_maklon_shipment(d, {"id": "SJ2", "po_id": "PO-M", "shipment_number": "SJ-2"},
                                            [{"qty_sent": 20}], USER))
    mi = res["mi"]
    assert calls == ["maklon_material_issue"] and mi["cost_target"] == "maklon"
    assert [(it["material_id"], it["qty_required"]) for it in mi["items"]] == [("ACC1", 10.0)]   # 0,5×40 − 10
    again = run(mie.issue_for_maklon_shipment(d, {"id": "SJ2", "po_id": "PO-M"}, [{"qty_sent": 20}], USER))
    assert again["already"] is True and len(calls) == 1                 # idempoten per surat jalan
    d.vendor_shipments.docs.append({"id": "SJ3", "po_id": "PO-M"})
    assert run(mie.issue_for_maklon_shipment(d, {"id": "SJ3", "po_id": "PO-M"}, [{"qty_sent": 0}], USER)) is None
    d.dewi_maklon_bom.docs[0]["materials"] = d.dewi_maklon_bom.docs[0]["materials"][:1]   # hanya kain klien
    d.vendor_shipments.docs.append({"id": "SJ4", "po_id": "PO-M"})
    assert run(mie.issue_for_maklon_shipment(d, {"id": "SJ4", "po_id": "PO-M"}, [{"qty_sent": 5}], USER)) is None
    # jurnal MI maklon: Dr biaya proyek maklon (5-4100) / Cr persediaan aksesoris (1-1402)
    db = _inv_db()
    m2 = {"id": "MIM", "mi_number": "MI-M", "cost_target": "maklon", "po_number_snapshot": "PO-M",
          "items": [{"material_id": "ACC1", "qty_issued": 10}]}
    db.rahaza_material_issues.docs.append(dict(m2))
    run(rp.post_inventory_issue(db, m2, USER))
    assert posting.lines() == [("5-4100", 20000.0, 0), ("1-1402", 0, 20000.0)]
    src = open(os.path.join(BACKEND, "routes", "vendor_shipment.py"), encoding="utf-8").read()
    assert "issue_for_maklon_shipment" in src and "shipment_business_type != 'maklon'" not in src


class _SyncColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, q=None, proj=None):
        return [dict(d) for d in self.docs if fm.match(d, q or {})]

    def update_one(self, q, upd):
        for d in self.docs:
            if fm.match(d, q):
                d.update(upd.get("$set") or {})
                return

    def count_documents(self, q):
        return len(self.find(q))


class _SyncDB:
    def __init__(self, **cols):
        self._c = {k: _SyncColl(v) for k, v in cols.items()}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, _SyncColl())

    def list_collection_names(self):
        return list(self._c)


def test_17_recompute_ledger_knows_qty_repaired_cmt():
    rq = _load_script("recompute_qty_ledger")
    assert "qty_repaired_cmt" in rq.FIELDS
    base = dict(cmt_receipts=[{"id": "R1", "status": "completed_qc"}],
                cmt_receipt_lines=[{"receipt_id": "R1", "po_item_id": "P1", "qty_actual": 90, "reject_qty": 10}],
                dewi_cmt_permak=[{"po_item_id": "P1", "status": "selesai_berhasil", "permak_type": "retur_ke_cmt",
                                  "qty_fixed": 6, "qty_scrap": 1}])
    ji = {"id": "J1", "po_item_id": "P1", "qty_declared": 100, "qty_accepted": 90, "qty_reject": 10,
          "qty_rework_open": 3, "qty_repaired": 0, "qty_scrap": 1, "qty_claimed_by_vendor": 100,
          "qty_short_open": 0, "qty_short_resolved": 0, "qty_repaired_cmt": 6}
    db = _SyncDB(production_job_items=[dict(ji)], **base)
    assert rq.audit_ledger(db, apply=False, verbose=False) == []           # konsisten → tidak ditimpa
    db = _SyncDB(production_job_items=[dict(ji, qty_repaired_cmt=0)], **base)
    f = rq.audit_ledger(db, apply=True, verbose=False)
    assert f[0]["diff"] == {"qty_repaired_cmt": (0, 6)}
    assert db.production_job_items.docs[0]["qty_repaired_cmt"] == 6


def test_18_fg_issue_route_journals_at_wac_per_reason(posting, monkeypatch):
    import routes.rahaza_inventory_fg as fgr
    from core import doc_number_policy, location_resolver, stock_service
    db = P3DB(rahaza_materials=[_wac_fg(name="Kaos")],
              rahaza_material_stock=[{"id": "st1", "material_id": "FG1", "location_id": "LOC-FG", "qty": 10.0,
                                      "inventory_category": "fg_internal", "ownership": "cv_da"}],
              rahaza_locations=[{"id": "LOC-FG", "code": "ZNA-FG"}])

    async def auth(_r):
        return {"id": "u-gd", "name": "Gudang", "role": "admin_gudang"}

    async def yes(*a, **k):
        return True

    async def num(*a, **k):
        return f"FGI-{len(db.rahaza_fg_issues.docs) + 1}"

    async def issue(mid, loc, qty, **kw):
        _stock(db, -qty, mid, loc)

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(fgr, "require_auth", auth)
    monkeypatch.setattr(fgr, "get_db", lambda: db)
    monkeypatch.setattr(fgr, "log_activity", noop)
    monkeypatch.setattr(location_resolver, "location_exists", yes)
    monkeypatch.setattr(doc_number_policy, "issue_number", num)
    monkeypatch.setattr(stock_service, "issue", issue)
    out = run(fgr.create_fg_issue(P3Req({"material_id": "FG1", "qty": 2, "reason": "sample", "location_id": "LOC-FG"})))
    assert out["gl_je_id"] and out["cogs"] == 100000.0 and out["gl_post_error"] is None
    assert posting.lines() == [("6-1130", 100000.0, 0), ("1-1404", 0, 100000.0)]   # 2 × WAC 50.000
    assert out["debit_mapping"] == "fg_issue.debit_sample"
    for reason in ("lainnya", "surat_jalan_internal"):
        o = run(fgr.create_fg_issue(P3Req({"material_id": "FG1", "qty": 1, "reason": reason, "location_id": "LOC-FG"})))
        assert o["debit_mapping"] == "fg_issue.debit_internal"
        assert posting.lines() == [("5-1000", 50000.0, 0), ("1-1404", 0, 50000.0)]
    assert DEFAULT_MAP["fg_issue"] == {"debit_sample": "6-1130", "debit_internal": "5-1000"}
    assert "fg_issue" in pp.EVENT_LABELS and pp.role_label("debit_sample").startswith("Sampel")
    # peran dikosongkan → jurnal ditolak & dicatat, stok tetap keluar (fisik sudah terjadi)
    posting.state["map"]["fg_issue"] = {}
    o = run(fgr.create_fg_issue(P3Req({"material_id": "FG1", "qty": 1, "reason": "sample", "location_id": "LOC-FG"})))
    assert o["gl_je_id"] is None and "fg_issue.debit_sample" in o["gl_post_error"]
