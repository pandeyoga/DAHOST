"""Uji unit HERMETIK paket 3b-2 (2026-11-02) — K15 "Scan Keluar Penjualan" harian.

Angka harapan DIHITUNG TANGAN:
  * FG1 stok 10 @WAC 111.396,10 (bahan 91.396,10 + upah 20.000,00 — skenario WAC paket S2-W).
  * scan 3 × 1 pcs + 1 karton ×2  → stok 10 − 3 − 2 = 5
      nilai = 5 × 111.396,10 = 556.980,50 → bahan 5 × 91.396,10 = 456.980,50 · upah 5 × 20.000 = 100.000,00
  * scan tambahan 1 lalu DIBATALKAN → stok 4 → 5 kembali; WAC tetap (4 × W + 1 × W) / 5 = W.
  * Tutup Hari → SATU jurnal: Dr 5-1000 456.980,50 · Dr 5-2000 100.000,00 / Cr 1-1404 556.980,50.
  * FG2 tanpa baris stok (stok 0) @WAC 50.000 → scan 1 DITERIMA, stok −1, merah, nilai 50.000.
  * Kontrol: impor 4 (kirim) + 2 (basis pesanan) = 6 pcs vs scan 5 → selisih 1;
             kumulatif 7 hari: impor 6 + 1 (kemarin) = 7 vs scan 5 → selisih 2.
"""
import asyncio
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from p3_fakes import FakeDB  # noqa: E402
from core import scan_out as so  # noqa: E402

DAY = "2026-11-02"
USER = {"id": "u-pack", "name": "Tim Packing", "role": "tim_packing"}
SPV = {"id": "u-spv", "name": "SPV Packing", "role": "spv_packing"}
W = 111396.10
MAP = {
    "cogs_marketplace_scan": {"debit_cogs_material": "5-1000", "debit_cogs_labor": "5-2000",
                              "debit_cogs_overhead": "5-3500", "credit_fg_inventory": "1-1404"},
    "cogs_shipment": {"debit_cogs_material": "5-1000", "debit_cogs_labor": "5-2000",
                      "debit_cogs_overhead": "5-3500", "credit_fg_inventory": "1-1404"},
    "inventory_adjust": {"inventory_rm": "1-1401", "adjustment_expense": "5-1950"},
}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def env(monkeypatch):
    """DB palsu + stok palsu (stock_service tanpa pipeline) + mesin posting palsu + tanggal tetap."""
    from core import stock_service as ss
    from routes import rahaza_posting as rp
    db = FakeDB(
        rahaza_materials=[
            {"id": "FG1", "code": "DA-1101-CRL", "name": "Kaos CRL", "type": "fg",
             "unit_cost": W, "wac_components": {"material": 91396.10, "labor": 20000.0, "overhead": 0.0}},
            {"id": "FG2", "code": "DA-2202-NVY", "name": "Kaos NVY", "type": "fg",
             "unit_cost": 50000.0, "wac_components": {"material": 50000.0, "labor": 0.0, "overhead": 0.0}},
            {"id": "FGM", "code": "MK-CLIENT-01", "name": "Kaos klien", "type": "fg",
             "owner_type": "client", "owner_client_id": "CL1"},
        ],
        rahaza_locations=[{"id": "LOC-FG", "code": "GD-L1-RAK", "name": "Rak FG", "storage_role": "fg", "active": True},
                          {"id": "LOC-Q", "code": "GD-L1-KARANTINA", "name": "Karantina", "storage_role": "karantina",
                           "active": True}],
        rahaza_material_stock=[{"id": "st1", "material_id": "FG1", "location_id": "LOC-FG", "qty": 10.0,
                                "inventory_category": "fg_internal", "ownership": "cv_da"}],
        marketing_platform_accounts=[{"id": "ACC1", "account_name": "Toko Shopee DA", "platform": "shopee",
                                      "status": "active"}],
    )

    def _row(mid, loc, meta):
        row = next((d for d in db.rahaza_material_stock.docs
                    if d["material_id"] == mid and d["location_id"] == loc), None)
        if row is None:
            row = {"id": str(uuid.uuid4()), "material_id": mid, "location_id": loc, "qty": 0.0,
                   **{k: v for k, v in (meta or {}).items() if k in ("inventory_category", "ownership")}}
            db.rahaza_material_stock.docs.append(row)
        return row

    async def issue(mid, loc, qty, *, ref=None, actor=None, allow_negative=False, db=None, input_uom=None, meta=None):
        row = _row(mid, loc, meta)
        if not allow_negative and row["qty"] < qty:
            raise ss.InsufficientStock(mid, loc, qty, row["qty"])
        row["qty"] = round(row["qty"] - qty, 4)
        db.rahaza_stock_ledger.docs.append({"id": str(uuid.uuid4()), "op": "issue", "material_id": mid,
                                            "location_id": loc, "delta": -qty, "qty_after": row["qty"],
                                            "ref": ref or {}})
        return dict(row)

    async def add(mid, loc, qty, *, meta=None, ref=None, actor=None, db=None, input_uom=None):
        row = _row(mid, loc, meta)
        row["qty"] = round(row["qty"] + qty, 4)
        db.rahaza_stock_ledger.docs.append({"id": str(uuid.uuid4()), "op": "add", "material_id": mid,
                                            "location_id": loc, "delta": qty, "qty_after": row["qty"],
                                            "ref": ref or {}})
        return dict(row)

    jes = []

    async def mapping(_db, key):
        return dict(MAP.get(key, {}))

    async def existing(_db, mod, ref):
        return next((j for j in jes if j["source_module"] == mod and j["source_ref"] == ref), None)

    async def create(_db, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2)
        je = {"id": f"je-{len(jes) + 1}", "je_number": f"JE-{len(jes) + 1}", "date": d.isoformat(),
              "source_module": mod, "source_ref": ref, "memo": memo, "lines": lines}
        jes.append(je)
        return {"ok": True, "je_id": je["id"], "je_number": je["je_number"]}

    monkeypatch.setattr(ss, "issue", issue)
    monkeypatch.setattr(ss, "add", add)
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", existing)
    monkeypatch.setattr(rp, "_create_posted_je", create)
    monkeypatch.setattr(so, "today_str", lambda: DAY)

    def stock(mid="FG1", loc="LOC-FG"):
        row = next((d for d in db.rahaza_material_stock.docs
                    if d["material_id"] == mid and d["location_id"] == loc), None)
        return row["qty"] if row else None
    return {"db": db, "jes": jes, "stock": stock, "map": MAP}


def _scan(db, code="DA-1101-CRL", mult=1, kind=so.KIND_SCAN, csid=None, user=USER, loc="LOC-FG", account=""):
    return run(so.scan(db, location_id=loc, raw_code=code, client_scan_id=csid or str(uuid.uuid4()),
                       multiplier=mult, kind=kind, account_id=account, user=user))


# ══════════════════════════ 1. rumus murni ════════════════════════════════════
def test_build_cogs_lines_balanced_both_directions():
    codes = {"material": "5-1000", "labor": "5-2000", "overhead": "5-3500", "fg": "1-1404"}
    t = {"material": 456980.50, "labor": 100000.0, "overhead": 0.0}
    lines = so.build_cogs_lines(t, codes, "m")
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in lines] == [
        ("5-1000", 456980.50, 0), ("5-2000", 100000.0, 0), ("1-1404", 0, 556980.50)]
    neg = so.build_cogs_lines({"material": -91396.10, "labor": -20000.0, "overhead": 0}, codes, "m")
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in neg] == [
        ("5-1000", 0, 91396.10), ("5-2000", 0, 20000.0), ("1-1404", 111396.10, 0)]


def test_sum_lines_nets_cancel_and_ignores_voided():
    ln = lambda kind, q, m, lab, st="active", neg=False: {  # noqa: E731
        "kind": kind, "qty": q, "status": st, "material_id": "FG1", "negative_stock": neg,
        "components": {"material": m, "labor": lab, "overhead": 0}}
    t = so.sum_lines([ln("scan", 3, 274188.30, 60000), ln("scan", 2, 182792.20, 40000, neg=True),
                      ln("scan", 1, 91396.10, 20000, st="voided"), ln("batal_kirim", 1, 91396.10, 20000)])
    assert (t["pcs_out"], t["pcs_cancel"], t["pcs"]) == (5, 1, 4)
    assert (t["material"], t["labor"], t["value"]) == (365584.40, 80000.0, 445584.40)   # 4 × W
    assert t["negative_lines"] == 1 and t["lines"] == 3


def test_import_order_rules_and_gap_flag():
    o = {"status": "shipped", "shipped_at": datetime(2026, 11, 2, 22, 30, tzinfo=timezone.utc),
         "order_date": datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc),
         "items": [{"quantity": 3, "fg_material_id": "FG1"}, {"quantity": 1, "fg_material_id": None}]}
    # jam dinding WIB: 22:30 tanggal 2 TETAP tanggal 2 (tidak digeser +7 jam)
    assert so.order_day(o) == ("2026-11-02", "kirim")
    assert so.order_day({"order_date": "2026-11-01 08:00"}) == ("2026-11-01", "pesanan")
    assert so.order_pcs(o) == (4, {"FG1": 3}, 1)
    assert so.order_counts({"status": "cancelled"}) is False
    assert so.order_counts({"status": "cancelled", "shipped_at": "2026-11-02 10:00"}) is True
    s = {"control_gap_pcs": 5, "control_gap_pct": 5}
    assert so.gap_flag(6, 5, s) is False and so.gap_flag(10, 5, s) is True
    assert so.gap_flag(1000, 960, s) is False and so.gap_flag(1000, 949, s) is True   # 5 % dari 1000 = 50


def test_row_problem_multiplier_number_and_langkah2_guard():
    assert so.row_problem(None, set()) is None
    assert so.row_problem({"ownership": "cv_da", "inventory_category": "fg_internal"}, set()) is None
    assert "karantina" in so.row_problem({"location_id": "Q"}, {"Q"})
    assert "maklon" in so.row_problem({"ownership": "CL1", "inventory_category": "maklon_fg"}, set())
    assert so.parse_multiplier("12") == 12
    for bad in (0, -1, 501, "x"):
        with pytest.raises(so.ScanOutError):
            so.parse_multiplier(bad)
    assert so.sheet_number("2026-11-02", "gd-l1-rak", 1) == "SKP-20261102-GD-L1-RAK"
    assert so.sheet_number("2026-11-02", "GD-L1-RAK", 2) == "SKP-20261102-GD-L1-RAK-2"
    assert so.langkah2_guard(so.LANGKAH2_CONFIG_KEY, True) == so.LANGKAH2_BLOCK_MSG
    assert so.langkah2_guard(so.LANGKAH2_CONFIG_KEY, "on") and not so.langkah2_guard(so.LANGKAH2_CONFIG_KEY, False)
    assert so.langkah2_guard("inventory_allow_negative", True) is None


# ══════════════════════════ 2. skenario owner (angka hitung tangan) ═══════════
def test_scenario_scan_void_close_journal(env):
    db, stock = env["db"], env["stock"]
    for _ in range(3):
        r = _scan(db)
        assert r["result"] == "accepted" and r["line"]["value"] == W
    k = _scan(db, mult=2, account="ACC1")                               # karton ×2, toko dipilih
    assert k["line"]["qty"] == 2 and k["line"]["value"] == 222792.20
    assert k["line"]["components"] == {"material": 182792.20, "labor": 40000.0, "overhead": 0.0}
    assert k["line"]["store"]["account_name"] == "Toko Shopee DA"
    assert stock() == 5.0
    # satu lembar per (tanggal, lokasi) dibuat otomatis saat scan pertama
    sheets = db.wh_scan_out_sheets.docs
    assert len(sheets) == 1 and sheets[0]["number"] == "SKP-20261102-GD-L1-RAK" and sheets[0]["status"] == "open"
    # salah scan → batal baris → stok & WAC kembali
    extra = _scan(db)
    assert stock() == 4.0
    out = run(so.void_line(db, extra["line"]["id"], user=USER, reason="salah scan"))
    assert out["line"]["status"] == "voided" and stock() == 5.0
    mat = run(db.rahaza_materials.find_one({"id": "FG1"}))
    assert mat["unit_cost"] == W
    # Tutup Hari → SATU jurnal 5 × WAC dipecah per komponen
    res = run(so.close_sheet(db, sheets[0]["id"], user=SPV))
    je = env["jes"][-1]
    assert len(env["jes"]) == 1 and je["source_module"] == "cogs_marketplace_scan"
    assert je["source_ref"] == f"skp:{sheets[0]['id']}" and je["date"] == DAY
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in je["lines"]] == [
        ("5-1000", 456980.50, 0), ("5-2000", 100000.0, 0), ("1-1404", 0, 556980.50)]
    assert res["sheet"]["totals"]["pcs"] == 5 and res["sheet"]["totals"]["value"] == 556980.50
    # idempoten: tutup lagi → tidak ada jurnal kedua
    again = run(so.close_sheet(db, sheets[0]["id"], user=SPV))
    assert again["already_closed"] and len(env["jes"]) == 1
    # setelah tutup: baris terkunci, tidak bisa dibatalkan
    first = next(ln for ln in db.wh_scan_out_lines.docs if ln["status"] == "active")
    with pytest.raises(so.ScanOutError) as e:
        run(so.void_line(db, first["id"], user=SPV, may_void_others=True))
    assert e.value.status == 409
    # scan setelah tutup membuka lembar ke-2 hari yang sama
    _scan(db)
    assert {s["number"] for s in db.wh_scan_out_sheets.docs} == {"SKP-20261102-GD-L1-RAK", "SKP-20261102-GD-L1-RAK-2"}


def test_same_client_scan_id_counts_once(env):
    db, stock = env["db"], env["stock"]
    csid = "dev-1-uuid-0001"
    a = _scan(db, csid=csid)
    b = _scan(db, csid=csid)
    assert a["line"]["id"] == b["line"]["id"] and b["duplicate"] is True
    assert stock() == 9.0
    assert len(db.wh_scan_out_lines.docs) == 1 and len(db.rahaza_stock_ledger.docs) == 1
    assert len(db.fg_cost_consumptions.docs) == 1


def test_interrupted_scan_resumes_without_double_issue(env):
    """Proses mati SETELAH stok terpotong tetapi sebelum dinilai: kirim ulang melanjutkan dari jejak."""
    db, stock = env["db"], env["stock"]
    r = _scan(db, csid="cut-1")
    ln = db.wh_scan_out_lines.docs[0]
    # simulasikan: baris kembali 'pending' dengan klaim basi, konsumsi WAC belum ada
    ln.update({"status": "pending", "claim_at": datetime.now(timezone.utc) - timedelta(minutes=5)})
    db.fg_cost_consumptions.docs.clear()
    again = _scan(db, csid="cut-1")
    assert again["resumed"] and again["line"]["status"] == "active" and again["line"]["value"] == W
    assert stock() == 9.0 and len(db.rahaza_stock_ledger.docs) == 1      # stok TIDAK dipotong dua kali
    assert r["line"]["id"] == again["line"]["id"]


def test_zero_stock_scan_accepted_and_red(env):
    db, stock = env["db"], env["stock"]
    r = _scan(db, code="da-2202-nvy")                                  # huruf kecil tetap dikenali
    ln = r["line"]
    assert r["result"] == "accepted" and ln["negative_stock"] is True and "stok_kurang" in ln["flags"]
    assert stock("FG2") == -1.0 and ln["value"] == 50000.0
    row = next(d for d in db.rahaza_material_stock.docs if d["material_id"] == "FG2")
    assert row["inventory_category"] == "fg_internal" and row["ownership"] == "cv_da"


def test_rejects_unknown_maklon_and_quarantine_without_stock_effect(env):
    db, stock = env["db"], env["stock"]
    r = _scan(db, code="TIDAK-ADA-123", csid="rj-1")
    assert r["result"] == "rejected" and r["reject"]["reason_code"] == "unknown_code"
    again = _scan(db, code="TIDAK-ADA-123", csid="rj-1")
    assert again["duplicate"] and len(db.wh_scan_out_rejects.docs) == 1
    assert _scan(db, code="MK-CLIENT-01")["reject"]["reason_code"] == "maklon"
    with pytest.raises(so.ScanOutError) as e:
        _scan(db, loc="LOC-Q")
    assert e.value.status == 400 and "karantina" in e.value.message
    with pytest.raises(so.ScanOutError):
        _scan(db, loc="")
    assert stock() == 10.0 and not db.wh_scan_out_lines.docs and not db.rahaza_stock_ledger.docs


def test_cancel_dispatch_returns_stock_and_nets_journal(env):
    db, stock = env["db"], env["stock"]
    _scan(db, mult=2)
    c = _scan(db, kind=so.KIND_CANCEL)
    assert c["line"]["kind"] == "batal_kirim" and c["line"]["signed_value"] == -W
    assert stock() == 9.0 and "batal_tanpa_scan" not in c["line"]["flags"]
    lone = _scan(db, code="DA-2202-NVY", kind=so.KIND_CANCEL)            # tanpa scan keluar sebelumnya
    assert "batal_tanpa_scan" in lone["line"]["flags"]
    run(so.void_line(db, lone["line"]["id"], user=USER))                 # batalkan "batal kirim" → stok keluar lagi
    assert stock("FG2") == 0.0
    sheet = db.wh_scan_out_sheets.docs[0]
    run(so.close_sheet(db, sheet["id"], user=SPV))
    je = env["jes"][-1]
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in je["lines"]] == [
        ("5-1000", 91396.10, 0), ("5-2000", 20000.0, 0), ("1-1404", 0, W)]   # 2 − 1 = 1 pcs


def test_only_own_line_or_supervisor_can_void(env):
    db = env["db"]
    r = _scan(db, user=SPV)
    with pytest.raises(so.ScanOutError) as e:
        run(so.void_line(db, r["line"]["id"], user=USER))
    assert e.value.status == 403
    assert run(so.void_line(db, r["line"]["id"], user={"id": "boss"}, may_void_others=True))["ok"]


def test_failed_journal_reopens_sheet(env):
    db = env["db"]
    _scan(db)
    env["map"].pop("cogs_marketplace_scan")
    try:
        sheet = db.wh_scan_out_sheets.docs[0]
        with pytest.raises(so.ScanOutError) as e:
            run(so.close_sheet(db, sheet["id"], user=SPV))
        assert e.value.status == 409 and "cogs_marketplace_scan" in e.value.message
        assert sheet["status"] == "open" and sheet["post_error"]
        assert all(not ln.get("locked") for ln in db.wh_scan_out_lines.docs)
        assert not env["jes"]
    finally:
        env["map"]["cogs_marketplace_scan"] = dict(MAP["cogs_shipment"])


def test_line_landing_in_closed_sheet_is_rehomed(env):
    db = env["db"]
    _scan(db)
    sheet = db.wh_scan_out_sheets.docs[0]
    run(so.close_sheet(db, sheet["id"], user=SPV))
    stray = {"id": "late-1", "client_scan_id": "late-1", "sheet_id": sheet["id"], "date": DAY,
             "location_id": "LOC-FG", "location_code": "GD-L1-RAK", "status": "active", "kind": "scan",
             "qty": 1, "material_id": "FG1", "locked": False}
    db.wh_scan_out_lines.docs.append(stray)
    moved = run(so._rehome_if_closed(db, stray, {"id": "LOC-FG", "code": "GD-L1-RAK"}, so._actor(SPV)))
    assert moved["sheet_id"] != sheet["id"] and moved["sheet_number"].endswith("-2")
    assert moved["rehomed_from"] == sheet["id"]


# ══════════════════════════ 3. kontrol, laporan, nota tidak dobel ═════════════
def _orders():
    return [
        {"id": "o1", "status": "shipped", "shipped_at": datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
         "items": [{"quantity": 4, "fg_material_id": "FG1"}]},
        {"id": "o2", "status": "paid", "order_date": "2026-11-02 08:00",
         "items": [{"quantity": 2, "fg_material_id": None}]},
        {"id": "o3", "status": "cancelled", "order_date": "2026-11-02 09:00", "items": [{"quantity": 3}]},
        {"id": "o4", "status": "shipped", "shipped_at": "2026-11-01 15:00",
         "items": [{"quantity": 1, "fg_material_id": "FG1"}]},
    ]


def test_control_import_6_vs_scan_5_gap_1_and_nota_not_double_counted(env, monkeypatch):
    db = env["db"]

    async def fake_orders(_db, first, last):
        return _orders()
    monkeypatch.setattr(so, "_import_orders", fake_orders)
    for _ in range(3):
        _scan(db)
    _scan(db, mult=2)
    db.sales_direct_notes.docs.append({"id": "n1", "note_number": "SL-20261102-001", "sale_date": DAY,
                                       "status": "confirmed", "items": [{"material_id": "FG1", "sku": "DA-1101-CRL",
                                                                         "name": "Kaos CRL", "qty": 4}]})
    ctl = run(so.control(db, end_day=DAY))
    today = ctl["rows"][-1]
    assert (today["import_pcs"], today["import_pcs_ship"], today["import_pcs_order"]) == (6, 4, 2)
    assert (today["scan_pcs"], today["gap"], today["unlinked_pcs"]) == (5, 1, 2)
    assert ctl["cumulative"] == {"import_pcs": 7, "scan_pcs": 5, "gap": 2, "flag": False}
    assert next(r for r in ctl["per_sku"] if r["material_id"] == "FG1") == {
        "material_id": "FG1", "sku": "DA-1101-CRL", "name": "Kaos CRL", "import_pcs": 4, "scan_pcs": 5, "gap": -1}
    rep = run(so.daily_report(db, day=DAY))
    assert rep["summary"]["pcs"] == 5 and rep["summary"]["value"] == 556980.50     # nota 4 pcs TIDAK ikut
    assert rep["direct_sales"]["pcs"] == 4 and rep["direct_sales"]["overlap_with_scan"][0]["sku"] == "DA-1101-CRL"
    assert rep["control"]["today"]["gap"] == 1
    assert rep["per_store"][0]["account_name"] == "(tanpa toko)" and rep["per_operator"][0]["net"] == 5


def test_daily_check_notifies_open_sheet_and_large_gap_then_resolves(env, monkeypatch):
    db = env["db"]

    async def fake_orders(_db, first, last):
        return [{"id": "x", "status": "shipped", "shipped_at": "2026-11-01 10:00",
                 "items": [{"quantity": 20, "fg_material_id": "FG1"}]}]
    monkeypatch.setattr(so, "_import_orders", fake_orders)
    monkeypatch.setattr(so, "today_str", lambda: "2026-11-01")
    _scan(db)                                                            # lembar 1 Nov
    env["map"].pop("cogs_marketplace_scan")                              # tutup otomatis akan gagal
    try:
        out = run(so.daily_check(db, today=DAY))
    finally:
        env["map"]["cogs_marketplace_scan"] = dict(MAP["cogs_shipment"])
    assert out["auto_closed"]["failed"] and out["open_notified"] == ["SKP-20261101-GD-L1-RAK"]
    assert out["control"]["status"] == "gap" and out["control"]["gap"] == 19
    notes = {n["subtype"]: n for n in db.notifications.docs}
    op, gp = notes[so.SUBTYPE_OPEN], notes[so.SUBTYPE_GAP]
    assert op["kind"] == "action" and op["source_collection"] == so.SHEETS and op["resolved_at"] is None
    assert "spv_packing" in op["meta"]["target_roles"] and "tim_packing" not in op["meta"]["target_roles"]
    assert gp["kind"] == "action" and gp["resolve_rule"]["open"] == ["gap"]
    # pengecekan ulang tidak menggandakan notifikasi
    run(so.daily_check(db, today=DAY))
    assert len(db.notifications.docs) == 2
    # SPV menutup lembar & menandai selisih → kedua "Perlu Tindakan" tertutup
    run(so.close_sheet(db, db.wh_scan_out_sheets.docs[0]["id"], user=SPV))
    run(so.review_control(db, "2026-11-01", user=SPV, note="impor dobel dari toko"))
    notes = {n["subtype"]: n for n in db.notifications.docs}
    assert notes[so.SUBTYPE_OPEN]["resolved_at"] and notes[so.SUBTYPE_GAP]["resolved_at"]


def test_sheets_still_open_contract_for_opname(env):
    db = env["db"]
    _scan(db)
    rows = run(so.sheets_still_open(db, location_ids=["LOC-FG"], up_to_date=DAY))
    assert [(r["date"], r["location_id"], r["status"]) for r in rows] == [(DAY, "LOC-FG", "open")]
    run(so.close_sheet(db, rows[0]["id"], user=SPV))
    assert run(so.sheets_still_open(db, location_ids=["LOC-FG"], up_to_date=DAY)) == []


# ══════════════════════════ 4. Langkah 2 & pemasangan ═════════════════════════
def test_langkah2_toggle_blocked_in_settings_api(monkeypatch):
    from fastapi import HTTPException
    from routes import dewi_system_config as dsc
    fdb = FakeDB(dewi_system_config=[{"key": so.LANGKAH2_CONFIG_KEY, "value": False, "data_type": "boolean"}])
    monkeypatch.setattr(dsc, "get_db", lambda: fdb)
    with pytest.raises(HTTPException) as e:
        run(dsc.update_config(so.LANGKAH2_CONFIG_KEY, dsc.ConfigUpdate(value=True), user={"name": "x"}))
    assert e.value.status_code == 409 and "dua kali" in e.value.detail
    out = run(dsc.bulk_update(dsc.BulkUpdateIn(**{so.LANGKAH2_CONFIG_KEY: "on"}), user={"name": "x"}))
    assert out["updated"] == 0 and "dua kali" in out["errors"][0]
    assert fdb.dewi_system_config.docs[0]["value"] is False
    # mematikan tetap boleh
    run(dsc.update_config(so.LANGKAH2_CONFIG_KEY, dsc.ConfigUpdate(value=False), user={"name": "x"}))


def test_import_still_never_cuts_stock():
    """Langkah 2 tidak ada: impor menandai stock_reserved=False dan Fulfillment menolak pesanan impor."""
    src = open(os.path.join(BACKEND, "routes", "marketing_data_import.py"), encoding="utf-8").read()
    assert 'd["stock_reserved"] = False' in src and "stock_service" not in src
    ful = open(os.path.join(BACKEND, "routes", "fulfillment.py"), encoding="utf-8").read()
    assert "if is_imported_order(order):" in ful


def test_profile_binding_and_no_literal_account_codes():
    from routes import rahaza_posting_profiles as pp
    from core import coa_bindings as cb
    prof = {p["event_type"]: p["mapping"] for p in pp.DEFAULT_PROFILES}
    assert prof["cogs_marketplace_scan"] == prof["cogs_shipment"]
    # Profil cukup terdaftar tepat sekali (paket lain boleh menambah profil sesudahnya).
    assert [p["event_type"] for p in pp.DEFAULT_PROFILES].count("cogs_marketplace_scan") == 1
    assert "cogs_marketplace_scan" in pp.EVENT_LABELS
    cons = cb.role_consumers()
    for role, code in prof["cogs_marketplace_scan"].items():
        c = cons[f"cogs_marketplace_scan.{role}"][0]
        assert c["reads_profile"] is True and c["code"] == code and c["source"] == "core.scan_out.PROFILE_ROLES"
    src = open(os.path.join(BACKEND, "core", "scan_out.py"), encoding="utf-8").read()
    assert not re.findall(r"""["'][1-9]-\d{4}["']""", src)            # akun hanya dari profil posting


def test_wiring_router_scheduler_and_screen():
    srv = open(os.path.join(BACKEND, "server.py"), encoding="utf-8").read()
    assert "app.include_router(wh_scan_out_router, dependencies=_DENY_EXTERNAL_AND_MKT)" in srv
    try:
        from utils.scheduler import JOB_REGISTRY
    except Exception:  # noqa: BLE001
        pytest.skip("apscheduler tidak tersedia")
    import routes.wh_scan_out  # noqa: F401 — mendaftarkan job saat dimuat
    assert JOB_REGISTRY[so.JOB_CLOSE]["cron"] == {"hour": 23, "minute": 55}
    assert JOB_REGISTRY[so.JOB_CHECK]["fn"] is so.job_daily_check
    fe = os.path.join(ROOT, "frontend", "src", "components", "erp")
    if not os.path.isdir(fe):
        pytest.skip("frontend/src tidak tersedia")
    nav = open(os.path.join(fe, "portal-shell", "portalNav.js"), encoding="utf-8").read()
    reg = open(os.path.join(fe, "moduleRegistry.js"), encoding="utf-8").read()
    mod = open(os.path.join(fe, "WHScanOutModule.jsx"), encoding="utf-8").read()
    assert "id: 'wh-scan-out'" in nav and "label: 'Scan Keluar Penjualan'" in nav
    assert "'wh-scan-out':   WHScanOutModule" in reg
    assert "UniversalScanner variant=\"inline\"" in mod and "continuous keepFocus" in mod
    assert "scanFeedback(" in mod and "client_scan_id: newScanId()" in mod
