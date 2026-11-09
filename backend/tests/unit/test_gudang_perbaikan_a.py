"""Uji unit HERMETIK perbaikan audit Gudang × Pesanan (9 Nov 2026) — Tahap A (G1, G5, G6, G8–G14, G16).

Angka harapan DIHITUNG TANGAN:
  * G14 retur 2 pcs basis scan @ 60.000 (bahan 45.000 + upah 15.000) = 120.000 → Cr 5-1000 90.000 · Cr 5-2000 30.000.
  * G14 pembulatan: 3 pcs × 33.333,33 (bahan 22.222,22 + upah 11.111,11) = 99.999,99 → 66.666,66 + 33.333,33.
  * G10 dua pesanan: (A×2, B×1) + (A×1, tanpa SKU "Kulot / M"×1) → A 3 pcs / 2 pesanan, B 1, tak tertaut 1.
  * G12 pesanan 'paid' tanpa tanggal kirim/siap kirim → tidak dihitung; 'paid' ber-`rts_at` 2026-11-09 23:10 →
    tanggal 2026-11-09 basis siap kirim.

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_gudang_perbaikan_a.py -q
"""
import asyncio
import os
import sys

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
from core import returns_bridge as rb  # noqa: E402
from core import scan_out as so  # noqa: E402
from core import stock_service as ss  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402

WH = {"id": "u-gd", "name": "Gudang Uji", "email": "gd@x", "role": "admin_gudang"}
SCAN_MAP = {"debit_cogs_material": "5-1000", "debit_cogs_labor": "5-2000", "debit_cogs_overhead": "5-3500",
            "credit_fg_inventory": "1-1404"}


def run(coro):
    return asyncio.run(coro)


def _db():
    db = fm.FakeDB()
    db.rahaza_locations.docs += [
        {"id": "L-FG", "code": "GD-L1-RAK", "name": "Area Rak Stok", "storage_role": "fg", "active": True},
        {"id": "L-FG2", "code": "GD-L1-RAK2", "name": "Rak 2", "storage_role": "fg", "active": True},
        {"id": "L-Q", "code": "GD-L1-QC", "name": "Area QC", "storage_role": "karantina", "active": True},
        {"id": "L-ACC", "code": "GD-L1-ACC", "name": "Ruang Aksesoris", "storage_role": "aksesoris", "active": True}]
    db.rahaza_materials.docs += [
        {"id": "FG1", "code": "DA-1-A", "name": "Kaos A", "type": "fg", "active": True, "unit": "pcs"},
        {"id": "FG-OFF", "code": "DA-1-OFF", "name": "Kaos lama", "type": "fg", "active": False},
        {"id": "FG-CL", "code": "MK-1", "name": "Kaos klien", "type": "fg", "owner_type": "client",
         "owner_client_id": "CL1"},
        {"id": "KN1", "code": "KN-1", "name": "Kain", "type": "fabric", "unit": "kg"}]
    return db


# ═════════════════════════════ G1 — portal FE = bawaan ∪ konfigurasi ═════════════════════════════
def test_g1_portals_union_default_and_configured():
    from routes.shared import check_portal_access, get_user_portals
    u = {"role": "spv_packing", "_portals": ["production", "maklon"]}
    got = set(get_user_portals(u))
    assert {"production", "maklon", "warehouse", "procurement", "self", "collaboration"} <= got
    assert all(check_portal_access(u, p) for p in got)          # FE tidak menampilkan yang ditolak BE
    assert "warehouse" in get_user_portals({"role": "tim_packing", "_portals": ["production"]})
    # peran kustom tanpa bawaan → hanya yang dicentang (+ portal semua orang)
    assert set(get_user_portals({"role": "tim return", "_portals": ["maklon"]})) == {"maklon", "self", "collaboration"}
    assert "warehouse" in get_user_portals({"role": "superadmin"})


# ═════════════════════════════ G6 — PUT retur hanya info dasar ═════════════════════════════
def test_g6_put_whitelist_and_pending_only():
    from routes.dewi_wh_returns import editable_info_patch
    assert editable_info_patch({"status": "Pending"}, {"notes": " cek ", "resi_number": "JX1"}) == \
        {"notes": "cek", "resi_number": "JX1"}
    for bad in ({"qty": 50}, {"received_qty": 5}, {"restocked": True}, {"material_id": "FG1"},
                {"link_status": "linked"}, {"notes": "x", "status": "Resolved"}):
        with pytest.raises(HTTPException) as e:
            editable_info_patch({"status": "Pending"}, bad)
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        editable_info_patch({"status": "Received"}, {"notes": "x"})
    assert "Menunggu paket" in e.value.detail


# ═════════════════════════════ G5 — Pilih barang + tolak restock tak tertaut ═════════════════════════════
def _ret(db, **kw):
    doc = {"id": "W1", "return_code": "RET-1", "status": "Received", "qty": 2, "received_qty": 2,
           "material_id": None, "fg_material_id": None, "link_status": rb.LINK_NONE, "restocked": False,
           "timeline": [], "link_candidates": [{"fg_material_id": "FG1", "product_name": "Kaos A"}], **kw}
    db.wh_returns.docs.append(doc)
    return doc


def test_g5_set_material_links_fg_and_validates():
    db = _db()
    _ret(db)
    res = run(rb.set_material(db, "W1", "FG1", actor=WH, note="label paket"))
    w = db.wh_returns.docs[0]
    assert (w["material_id"], w["fg_material_id"], w["link_status"], w["link_source"]) == \
        ("FG1", "FG1", rb.LINK_OK, "manual_pick_wh")
    assert w["sku_code"] == "DA-1-A" and "sesuai kandidat" in res["message"] and "label paket" in res["message"]
    assert w["timeline"][-1]["note"].startswith("Barang dipilih gudang: DA-1-A")
    for mid, why in (("FG-OFF", "nonaktif"), ("FG-CL", "klien maklon"), ("KN1", "bukan master barang jadi"),
                     ("", "Pilih barang")):
        with pytest.raises(rb.ReturnBridgeError) as e:
            run(rb.set_material(db, "W1", mid, actor=WH))
        assert why in str(e.value)
    db.wh_returns.docs[0]["status"] = "Resolved"
    with pytest.raises(rb.ReturnBridgeError) as e:
        run(rb.set_material(db, "W1", "FG1", actor=WH))
    assert "sudah diputuskan" in str(e.value)


def test_g5_resolve_restock_unlinked_rejected_and_stays_inspected(monkeypatch):
    from routes import dewi_wh_returns as wr
    db = _db()
    _ret(db, status="Inspected")

    async def auth(_r):
        return WH
    monkeypatch.setattr(wr, "require_auth", auth)
    monkeypatch.setattr(wr, "get_db", lambda: db)
    for action in (rb.ACTION_RESTOCK, rb.ACTION_QUARANTINE):
        with pytest.raises(HTTPException) as e:
            run(wr.resolve_return("W1", fm.FakeRequest({"action_taken": action})))
        assert e.value.status_code == 400 and "Pilih barang" in e.value.detail
    assert db.wh_returns.docs[0]["status"] == "Inspected" and not db.rahaza_material_stock.docs


def test_g5_quick_process_validates_before_writing_status():
    db = _db()
    _ret(db, status="Pending")
    with pytest.raises(rb.ReturnBridgeError):
        run(rb.auto_process(db, "W1", condition="Baik", actor=WH))
    assert db.wh_returns.docs[0]["status"] == "Pending"
    db.wh_returns.docs[0].update(material_id="FG1", fg_material_id="FG1", link_status=rb.LINK_OK)
    with pytest.raises(rb.ReturnBridgeError) as e:                    # lokasi pilihan = karantina
        run(rb.auto_process(db, "W1", condition="Baik", actor=WH, location_id="L-Q"))
    assert "karantina" in str(e.value) and db.wh_returns.docs[0]["status"] == "Pending"


# ═════════════════════════════ G16 — lokasi pilihan saat Terima ═════════════════════════════
def test_g16_restock_location_choice():
    db = _db()
    loc = run(rb.restock_location(db, "Baik", "L-FG2"))
    assert (loc["id"], loc["sellable"]) == ("L-FG2", True)
    assert run(rb.restock_location(db, "Baik", None))["id"] == "L-FG"           # bawaan peran fg
    assert run(rb.restock_location(db, "Rusak", "L-FG2"))["id"] == "L-Q"        # rusak tetap karantina
    for bad in ("L-Q", "NOPE"):
        with pytest.raises(rb.ReturnBridgeError):
            run(rb.restock_location(db, "Baik", bad))


def test_g16_restock_goes_to_chosen_location(monkeypatch):
    db = _db()
    _ret(db, status="Resolved", material_id="FG1", fg_material_id="FG1", link_status=rb.LINK_OK)
    added = []

    async def add(mid, loc, qty, *, meta=None, ref=None, actor=None, db=None, input_uom=None):
        added.append((mid, loc, qty, meta.get("inventory_category"), meta.get("ownership")))
        return {"qty": qty}

    async def no_value(*a, **k):
        return {}

    async def no_cache(*a, **k):
        return 0
    monkeypatch.setattr(ss, "add", add)
    monkeypatch.setattr(rb, "_value_restock", no_value)
    monkeypatch.setattr(rb, "refresh_catalog_cache", no_cache)
    res = run(rb.restock(db, db.wh_returns.docs[0], condition="Baik", qty=1, actor=WH, location_id="L-FG2"))
    assert res["restocked"] and added == [("FG1", "L-FG2", 1, "fg_internal", "cv_da")]
    assert db.wh_returns.docs[0]["restock_location_code"] == "GD-L1-RAK2"


# ═════════════════════════════ G14 — balik HPP per komponen ═════════════════════════════
def test_g14_split_by_components_exact_and_rounding():
    assert rp.split_by_components(120000, {"material": 45000, "labor": 15000, "overhead": 0}) == \
        {"material": 90000.0, "labor": 30000.0}
    parts = rp.split_by_components(99999.99, {"material": 22222.22, "labor": 11111.11})
    assert parts == {"material": 66666.66, "labor": 33333.33} and round(sum(parts.values()), 2) == 99999.99
    assert rp.split_by_components(100, None) == {} and rp.split_by_components(0, {"material": 1}) == {}


def test_g14_restock_and_damaged_journals_per_component(monkeypatch):
    jes = []

    async def mapping(_db, key):
        return {"cogs_marketplace_scan": SCAN_MAP,
                "cogs_marketplace_return": {"debit_fg_inventory": "1-1404", "credit_cogs": "5-1000"},
                "return_damaged_loss": {"debit_return_loss": "6-1300", "credit_cogs": "5-1000"}}.get(key, {})

    async def none(*a, **k):
        return None

    async def create(_db, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2)
        jes.append(lines)
        return {"ok": True, "je_id": f"j{len(jes)}", "je_number": f"JE-{len(jes)}"}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)
    comps = {"material": 45000.0, "labor": 15000.0, "overhead": 0.0}
    run(rp.post_marketplace_return_restock(None, {"id": "W1", "return_code": "RET-1"}, 2, 60000, WH, components=comps))
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in jes[0]] == [
        ("1-1404", 120000.0, 0), ("5-1000", 0, 90000.0), ("5-2000", 0, 30000.0)]
    run(rp.post_return_damaged_loss(None, {"id": "W1", "return_code": "RET-1"}, 2, 60000, WH, components=comps))
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in jes[1]] == [
        ("6-1300", 120000.0, 0), ("5-1000", 0, 90000.0), ("5-2000", 0, 30000.0)]
    run(rp.post_marketplace_return_restock(None, {"id": "W2", "return_code": "RET-2"}, 1, 50000, WH))   # tanpa komponen
    assert [(ln["account_code"], ln["credit"]) for ln in jes[2]][1:] == [("5-1000", 50000.0)]


# ═════════════════════════════ G8 — identitas baris tujuan & satu aturan stok jual ═════════════════════════════
def test_g8_derive_identity():
    fg, mat, cl = {"type": "fg", "code": "DA-1"}, {"type": "fabric"}, {"type": "fg", "owner_type": "client",
                                                                       "owner_client_id": "CL1"}
    assert ss.derive_identity(fg, {"ownership": "cv_da", "inventory_category": "fg_internal", "unit": "pcs"}) == \
        {"unit": "pcs", "ownership": "cv_da", "inventory_category": "fg_internal"}
    i = ss.derive_identity(fg, {"ownership": "cv_da"})            # baris karantina/retur rusak: tanpa kategori
    assert (i["ownership"], i["inventory_category"], i["material_code"]) == ("cv_da", "fg_internal", "DA-1")
    assert ss.derive_identity(fg, None)["inventory_category"] == "fg_internal"
    assert ss.derive_identity(cl, None)[("ownership")] == "CL1" and \
        ss.derive_identity(cl, None)["inventory_category"] == "maklon_fg"
    assert ss.derive_identity(mat, None)["inventory_category"] == "raw_material"
    assert ss.derive_identity(fg, {"ownership": "CL9", "inventory_category": "maklon_fg"})["ownership"] == "CL9"


def test_g8_move_carries_identity_to_destination(monkeypatch):
    db = _db()
    db.rahaza_material_stock.docs.append({"material_id": "FG1", "location_id": "L-FG", "qty": 6,
                                          "ownership": "cv_da", "inventory_category": "fg_internal"})
    calls = []

    async def issue(mid, loc, qty, **k):
        calls.append(("issue", loc, qty))
        return {}

    async def add(mid, loc, qty, *, meta=None, **k):
        calls.append(("add", loc, qty, (meta or {}).get("inventory_category"), (meta or {}).get("ownership")))
        return {}
    monkeypatch.setattr(ss, "issue", issue)
    monkeypatch.setattr(ss, "add", add)
    run(ss.move("FG1", "L-FG", "L-FG2", 3, db=db))
    assert calls == [("issue", "L-FG", 3.0), ("add", "L-FG2", 3.0, "fg_internal", "cv_da")]
    calls.clear()
    run(ss.move("FG1", "L-FG", "L-Q", 1, meta={"quarantine": True}, db=db, carry_identity=False))
    assert calls[-1] == ("add", "L-Q", 1.0, None, None)              # masuk karantina: tanpa kategori jual


def test_g8_sellable_row_match_equals_row_problem():
    blocked = {"L-Q"}
    rows = [{"location_id": "L-FG"}, {"location_id": "L-FG", "inventory_category": "fg_internal", "ownership": "cv_da"},
            {"location_id": "L-FG", "inventory_category": None, "ownership": None},
            {"location_id": "L-Q", "inventory_category": "fg_internal"},
            {"location_id": "L-FG", "ownership": "CL1", "inventory_category": "maklon_fg"},
            {"location_id": "L-FG", "inventory_category": "raw_material"},
            {"location_id": "L-FG", "blocked": True}, {"location_id": "L-FG", "quarantine": True},
            {"location_id": "L-FG", "inventory_category": "finished_goods", "ownership": "own"}]
    q = so.sellable_row_match(blocked)
    assert [fm.match(r, q) for r in rows] == [so.row_problem(r, blocked) is None for r in rows]
    assert [fm.match(r, q) for r in rows] == [True, True, True, False, False, False, False, False, True]


def test_g8_fg_material_ids_excludes_client_goods():
    db = _db()
    assert sorted(run(so.fg_material_ids(db))) == ["FG-OFF", "FG1"]
    assert run(so.fg_material_ids(db, ["FG1", "FG-CL", "KN1"])) == ["FG1"]


def test_g8_issue_fg_uses_sellable_rows_only(monkeypatch):
    from core import production_qty_ledger as qled
    db = _db()
    db.rahaza_material_stock.docs += [
        {"material_id": "FG1", "location_id": "L-ACC", "qty": 5, "ownership": "CL1", "inventory_category": "maklon_fg"},
        {"material_id": "FG1", "location_id": "L-FG2", "qty": 2},                       # hasil pindah lama, tanpa kategori
        {"material_id": "FG1", "location_id": "L-FG", "qty": 1, "ownership": "cv_da", "inventory_category": "fg_internal"}]
    out = []

    async def issue(mid, loc, qty, **k):
        out.append((loc, qty))

    async def qloc(_db):
        return "L-Q"

    async def nocost(*a, **k):
        return {"cogs": 0.0, "layers_used": [], "uncosted_qty": 0}
    from core import fg_cost_layers as fcl
    from core import quarantine as qmod
    monkeypatch.setattr(ss, "issue", issue)
    monkeypatch.setattr(qmod, "get_quarantine_location_id", qloc)
    monkeypatch.setattr(fcl, "consume_fifo", nocost)
    with pytest.raises(qled.FGStockShortfall):                       # titipan klien (5) tidak boleh dipakai
        run(qled.issue_fg(db, material_id="FG1", qty=4, ref={}, actor=WH))
    run(qled.issue_fg(db, material_id="FG1", qty=3, ref={}, actor=WH))
    assert out == [("L-FG", 1), ("L-FG2", 2)]


# ═════════════════════════════ G9 — peringatan stok ada di lokasi lain ═════════════════════════════
def test_g9_stock_elsewhere_and_warning_text():
    db = _db()
    db.rahaza_material_stock.docs += [
        {"material_id": "FG1", "location_id": "L-FG", "qty": -2},
        {"material_id": "FG1", "location_id": "L-FG2", "qty": 3, "inventory_category": "fg_internal", "ownership": "cv_da"},
        {"material_id": "FG1", "location_id": "L-Q", "qty": 9}]
    rows = run(so.stock_elsewhere(db, "FG1", "L-FG"))
    assert [(r["location_id"], r["qty"]) for r in rows] == [("L-FG2", 3.0)]
    txt = so.elsewhere_warning({"sku": "DA-1-A"}, [{"code": "GD-L1-RAK2", "qty": 3.0}])
    assert "GD-L1-RAK2 (3 pcs)" in txt and "tetap dicatat" in txt


# ═════════════════════════════ G10 — daftar ambil per items[] ═════════════════════════════
def test_g10_picking_groups_by_order_items():
    from routes.marketing_orders_routes import group_picking
    orders = [
        {"order_id": "O1", "platform": "shopee", "items": [
            {"fg_material_id": "FG1", "quantity": 2, "seller_sku": "toko-a"},
            {"fg_material_id": "FG2", "quantity": 1}]},
        {"order_id": "O2", "platform": "tiktok", "items": [
            {"fg_material_id": "FG1", "quantity": 1},
            {"fg_material_id": None, "quantity": 1, "product_name_raw": "Kulot", "variation_raw": "M"}]},
        {"order_id": "O3", "platform": "manual", "sku_id": "", "product_name": "Lama", "quantity": 2}]
    rows = group_picking(orders, {"FG1": "DA-1-A", "FG2": "DA-1-B"})
    by = {r["sku_id"] or r["product_name"]: r for r in rows}
    assert (by["DA-1-A"]["total_qty"], by["DA-1-A"]["order_count"], by["DA-1-A"]["linked"]) == (3, 2, True)
    assert by["DA-1-A"]["platforms"] == ["shopee", "tiktok"] and by["DA-1-B"]["total_qty"] == 1
    assert (by["Kulot"]["total_qty"], by["Kulot"]["variation"], by["Kulot"]["linked"]) == (1, "M", False)
    assert by["Lama"]["total_qty"] == 2
    assert [r["linked"] for r in rows] == [True, True, False, False]        # tertaut didahulukan


# ═════════════════════════════ G11 — Fulfillment tidak memotong stok lagi ═════════════════════════════
def test_g11_manual_orders_not_required_and_allocate_dispatch_rejected():
    from routes import fulfillment as ff
    src = open(os.path.join(BACKEND, "routes", "marketing_orders_routes.py"), encoding="utf-8").read()
    assert '"fulfillment_status": "not_required",' in src and '"pending_fulfillment"' not in src
    assert ff.FULFILLMENT_STOCK_ENABLED is False and "Scan Keluar Penjualan" in ff.K15_FULFILLMENT_MSG
    db = _db()
    db.marketing_orders.docs.append({"id": "M1", "order_id": "WA-1", "fulfillment_status": "pending_fulfillment",
                                     "_source_type": "manual_input"})
    ff_get_db = ff.get_db
    try:
        ff.get_db = lambda: db
        payload = ff.AllocateInventoryIn(items=[ff.FulfillmentItemIn(material_id="FG1", qty_allocated=1)])
        with pytest.raises(HTTPException) as e:
            run(ff.allocate_inventory("M1", payload, user=WH))
        assert e.value.status_code == 400 and "K15" in e.value.detail
        with pytest.raises(HTTPException) as e:
            run(ff.dispatch_order("M1", ff.DispatchIn(tracking_number="R1"), user=WH))
        assert "K15" in e.value.detail
    finally:
        ff.get_db = ff_get_db


# ═════════════════════════════ G12 — basis tanggal kontrol ═════════════════════════════
def test_g12_order_day_basis_and_not_arranged_excluded():
    from datetime import datetime, timezone
    rts = datetime(2026, 11, 9, 23, 10, tzinfo=timezone.utc)      # jam dinding WIB platform
    assert so.order_day({"shipped_at": "2026-11-10 08:00", "rts_at": rts, "order_date": "2026-11-08"}) == \
        ("2026-11-10", "kirim")
    assert so.order_day({"rts_at": rts, "order_date": "2026-11-08 21:00"}) == ("2026-11-09", "siap_kirim")
    assert so.order_day({"order_date": "2026-11-08 21:00"}) == ("2026-11-08", "pesanan")
    assert so.order_counts({"status": "paid"}) is False
    assert so.order_counts({"status": "new"}) is False
    assert so.order_counts({"status": "paid", "rts_at": rts}) is True
    assert so.order_counts({"status": "packed"}) is True and so.order_counts({"status": "shipped"}) is True
    assert so.order_counts({"status": "cancelled", "shipped_at": "2026-11-09"}) is True
    assert so.is_manual_order({"_source_type": "manual_input"}) and not so.is_manual_order({"_import_session_id": "s"})
