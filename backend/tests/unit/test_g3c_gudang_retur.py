"""Uji unit HERMETIK paket 3c Gudang (2026-11-02) — keputusan owner K10, K11, K12 (audit g.md No.20–23, 28).

Angka harapan DIHITUNG TANGAN (skenario uji runtime audit T1/T2):
  * K11 WAC GR tanpa reject karantina: (90 × 50.000 + 100 × 60.000) / 190 = 55.263,1579 (dulu 55.000).
  * K11 lepas reject 4 @ harga PO 50.000 = penerimaan susulan: Dr 1-1401 / Cr 2-1150 200.000;
    WAC (190 × 55.263,1579 + 4 × 50.000) / 194 = 10.700.000 / 194 = 55.154,6392. Sisa 6 di-scrap → 0 jurnal.
  * K11 Retur Pembelian barang bernilai 6 (H 50.000, W 55.000): kirim Dr 1-1620 300.000 / Dr 5-1900 30.000 /
    Cr 1-1401 330.000; ND sebelum faktur Dr 2-1150 / Cr 1-1620 300.000 → tagihan GR 90 → 84 = 4.200.000.
  * K11 sesudah faktur: Dr Hutang (sub-ledger faktur) / Cr klaim 300.000; saldo hutang 4.500.000 − 300.000 = 4.200.000.
  * K11 reject GR 10 (belum bernilai) tukar barang: kirim 0 jurnal; pengganti Dr 1-1401 / Cr 2-1150 500.000, bisa ditagih.
  * K11 musnah tanggungan DA atas reject 10: Dr 6-4300 / Cr 2-1150 500.000 (bisa ditagih).
  * K11 diterima dg diskon 45.000: reject 10 → Dr 1-1401 / Cr 2-1150 450.000; stok bernilai 6 → potongan 30.000
    Dr 2-1150 / Cr 1-1401, HPP (100 × 55.000 − 30.000) / 100 = 54.700.
  * K10 retur material 20 kg @55.000 + 10 pcs aksesoris @1.200: Dr 1-1401 1.100.000 + Dr 1-1402 12.000 /
    Cr 1-1403 1.112.000; MI qty_returned 20/10 → return_status 'partial'.
  * K12 Set HPP 200 m 17.500 → 18.000: Dr 1-1402 / Cr 5-1950 100.000; GL 1-1402 3.500.000 + 100.000 = 3.600.000 = 200 × 18.000.

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_g3c_gudang_retur.py -q
"""
import asyncio
import copy
import os
import sys
import types

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
from core import accessory_valuation as av  # noqa: E402
from core import coa_bindings as cb  # noqa: E402
from core import purchase_returns as pr  # noqa: E402
from core import quarantine as qmod  # noqa: E402
from core import stock_service  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402

DEFAULT_MAP = {p["event_type"]: dict(p["mapping"]) for p in pp.DEFAULT_PROFILES}
FIN = {"id": "u-fin", "name": "Keuangan Uji", "email": "fin@x", "role": "accounting"}
WH = {"id": "u-gd", "name": "Gudang Uji", "email": "gd@x", "role": "admin_gudang"}
SA = {"id": "u-sa", "name": "Super", "email": "sa@x", "role": "superadmin"}


def run(coro):
    return asyncio.run(coro)


class Req:
    def __init__(self, body=None):
        self._b = body or {}

        class _S:
            pass
        self.state = _S()

    async def json(self):
        return copy.deepcopy(self._b)

    async def body(self):
        return b"{}" if self._b else b""


@pytest.fixture
def posting(monkeypatch):
    jes = []

    async def mapping(db, key):
        return dict(DEFAULT_MAP.get(key, {}))

    async def none(*a, **k):
        return None

    async def create(db, d, memo, mod, ref, lines, user, **kw):
        assert round(sum(ln["debit"] for ln in lines), 2) == round(sum(ln["credit"] for ln in lines), 2), lines
        je = {"id": f"je-{len(jes) + 1}", "je_number": f"JE-{len(jes) + 1}", "source_module": mod,
              "source_ref": ref, "lines": [dict(ln) for ln in lines]}
        jes.append(je)
        return {"ok": True, "je_id": je["id"], "je_number": je["je_number"]}
    monkeypatch.setattr(rp, "get_mapping", mapping)
    monkeypatch.setattr(pp, "get_mapping", mapping)
    monkeypatch.setattr(rp, "_find_existing_je", none)
    monkeypatch.setattr(rp, "_create_posted_je", create)

    def gl(code):
        return round(sum(ln["debit"] - ln["credit"] for je in jes for ln in je["lines"]
                         if ln["account_code"] == code), 2)

    def lines(i=-1):
        return sorted((ln["account_code"], round(ln["debit"], 2), round(ln["credit"], 2)) for ln in jes[i]["lines"])
    return types.SimpleNamespace(jes=jes, gl=gl, lines=lines)


@pytest.fixture
def stock(monkeypatch):
    """stock_service palsu: mencatat mutasi; on-hand dari `state['onhand']`."""
    st = {"onhand": {}, "ops": []}

    def rec(op):
        async def f(*a, **k):
            st["ops"].append((op, a[:4]))
            return {}
        return f

    async def onhand(mid, db=None):
        return st["onhand"].get(mid, 0.0)
    for op in ("add", "issue", "move", "release", "reserve"):
        monkeypatch.setattr(stock_service, op, rec(op))
    monkeypatch.setattr(stock_service, "get_onhand", onhand)

    async def qloc(db):
        return "LOC-Q"
    monkeypatch.setattr(qmod, "get_quarantine_location_id", qloc)
    return st


def _counter(monkeypatch, *mods):
    n = {"i": 0}

    async def gen(db, coll, field, prefix, width=4, **kw):
        n["i"] += 1
        return f"{prefix}{n['i']:0{width}d}"
    for m in mods:
        monkeypatch.setattr(m, "gen_prefixed_number", gen)


# ══════════════════════════════ K11: reject & WAC ═════════════════════════════
def test_split_reject_qty_physical_vs_document():
    from routes.rahaza_grn_qc import REJECT_CATEGORIES, reject_kind, split_reject_qty
    assert all(c["kind"] in ("fisik", "dokumen") for c in REJECT_CATEGORIES)
    assert {c["code"] for c in REJECT_CATEGORIES if c["kind"] == "dokumen"} == {
        "QUANTITY_SHORT", "LATE_DELIVERY", "MISSING_DOCS", "ACCESSORY_MISSING"}
    assert split_reject_qty([{"code": "FABRIC_DEFECT", "qty": 6}, {"code": "QUANTITY_SHORT", "qty": 4}], 10) == (6, 4)
    assert split_reject_qty([{"code": "LATE_DELIVERY"}], 10) == (0, 10)       # satu alasan tanpa qty = semua
    assert split_reject_qty([], 10) == (10, 0)                                  # perilaku lama: fisik
    assert reject_kind("TIDAK_DIKENAL") == "fisik"


def test_valued_onhand_excludes_unvalued_quarantine(stock):
    db = fm.FakeDB()
    db.wh_quarantine_items.docs += [
        {"id": "q1", "material_id": "X", "status": "open", "remaining_qty": 10, "valued": False},   # reject GR
        {"id": "q2", "material_id": "X", "status": "open", "remaining_qty": 5, "valued_qty": 5},    # bernilai
        {"id": "q3", "material_id": "X", "status": "closed", "remaining_qty": 0, "valued": False}]
    stock["onhand"]["X"] = 200.0
    assert run(qmod.unvalued_qty(db, "X")) == 10
    assert run(qmod.valued_onhand(db, "X")) == 190.0
    # WAC GR2 dengan qty bernilai 90 (bukan on-hand 100): uji T1
    assert av.moving_average(90, 50000, 100, 60000) == pytest.approx(55263.1579)


def _gr_env(monkeypatch, db, cap):
    import routes.warehouse as wh

    async def auth(_r):
        return WH

    async def noop(*a, **k):
        return None

    async def vonhand(db_, mid):
        return 90.0

    async def qin(db_, **kw):
        cap["q_in"] = kw
        return {"id": "qi-new"}

    async def qinfo(db_):
        return {"id": "LOC-Q", "code": "ZNA-KARANTINA", "name": "Karantina"}

    async def apply_cost(db_, mid, q, cost, **kw):
        cap["wac"] = av.moving_average(kw["qty_before"], 50000.0, q, cost)
        return {"old_unit_cost": 50000.0, "new_unit_cost": cap["wac"]}
    monkeypatch.setattr(wh, "require_auth", auth)
    monkeypatch.setattr(wh, "get_db", lambda: db)
    monkeypatch.setattr(wh, "log_activity", noop)
    monkeypatch.setattr(wh.stock_service, "add", noop)
    monkeypatch.setattr(wh.quarantine, "valued_onhand", vonhand)
    monkeypatch.setattr(wh.quarantine, "quarantine_in", qin)
    monkeypatch.setattr(wh.quarantine, "get_quarantine_location_info", qinfo)
    monkeypatch.setattr(wh.accessory_valuation, "apply_receipt_cost", apply_cost)
    return wh


def test_gr_without_po_requires_price_and_document_reject_not_quarantined(monkeypatch, posting):
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "X", "code": "KN-K20-TRC", "type": "fabric", "unit": "pcs", "unit_cost": 50000.0})
    item = {"id": "L1", "material_id": "X", "sku": "KN-K20-TRC", "received_qty": 110, "rejected_qty": 10, "unit": "pcs",
            "reject_reasons": [{"code": "FABRIC_DEFECT", "qty": 6}, {"code": "QUANTITY_SHORT", "qty": 4}]}
    db.warehouse_receiving.docs.append({"id": "GR1", "receipt_number": "GR-00001", "status": "draft",
                                        "location_id": "GD-L2", "supplier_name": "PT Uji", "items": [item]})
    cap = {}
    wh = _gr_env(monkeypatch, db, cap)
    with pytest.raises(HTTPException) as e:                      # tanpa PO & tanpa harga → ditolak
        run(wh.update_receiving("GR1", Req({"status": "received"})))
    assert e.value.status_code == 400 and "Harga satuan wajib" in e.value.detail
    assert db.warehouse_receiving.docs[0]["status"] == "draft"
    # 2026-11-06 (Tahap 2, keputusan owner): harga GR tanpa PO hanya diisi Keuangan
    fin = {"id": "u-fin", "name": "Keuangan", "role": "accounting"}

    async def fin_auth(_r):
        return fin
    monkeypatch.setattr(wh, "require_auth", fin_auth)
    out = run(wh.update_receiving("GR1", Req({"status": "received", "items": [{**item, "unit_price": 60000}]})))
    assert cap["q_in"]["qty"] == 6                               # hanya alasan FISIK ke karantina
    assert cap["q_in"]["unit_cost"] == 60000                     # harga GR = bawaan lepas reject / retur
    line = out["items"][0]
    assert line["rejected_doc_qty"] == 4 and "tidak masuk stok" in line["reject_doc_note"]
    assert out["reject_doc_summary"]["total_qty"] == 4
    assert cap["wac"] == pytest.approx(55263.1579)               # (90 × 50.000 + 100 × 60.000) / 190
    assert posting.lines() == [("1-1401", 6000000.0, 0), ("2-1150", 0, 6000000.0)]   # bersih 100 × 60.000


def test_gr_with_po_takes_price_from_po_line(monkeypatch, posting):
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "X", "code": "KN", "type": "fabric", "unit": "pcs"})
    db.rahaza_purchase_orders.docs.append({"id": "PO1", "items": [{"id": "pi1", "material_id": "X", "unit_cost": 50000.0,
                                                                   "qty_ordered": 100, "qty_received": 0}]})
    db.warehouse_receiving.docs.append({"id": "GR2", "receipt_number": "GR-2", "status": "draft", "po_id": "PO1",
                                        "location_id": "GD-L2", "items": [{"id": "L", "material_id": "X",
                                                                            "po_item_id": "pi1", "received_qty": 10}]})
    cap = {}
    wh = _gr_env(monkeypatch, db, cap)
    import routes.rahaza_po as rpo

    async def po_upd(*a, **k):
        return None
    monkeypatch.setattr(rpo, "update_po_received_qty", po_upd)
    out = run(wh.update_receiving("GR2", Req({"status": "received"})))
    assert out["items"][0]["unit_cost"] == 50000.0
    assert posting.lines() == [("1-1401", 500000.0, 0), ("2-1150", 0, 500000.0)]


# ══════════════════════ K11: lepas reject = penerimaan susulan ═════════════════
def _t1_db():
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "X", "code": "KN-K20-TRC", "name": "Kain", "type": "fabric",
                                     "unit": "kg", "unit_cost": 55263.1579})
    db.warehouse_receiving.docs.append({
        "id": "GR1", "receipt_number": "GR-00001", "status": "received", "supplier_name": "PT Uji",
        "items": [{"id": "L1", "material_id": "X", "received_qty": 100, "rejected_qty": 10, "unit_price": 50000.0,
                   "unit": "kg"}]})
    db.wh_quarantine_items.docs.append({
        "id": "q1", "material_id": "X", "material_code": "KN-K20-TRC", "unit": "kg", "unit_cost": 50000.0,
        "qty": 10, "remaining_qty": 10, "valued": False, "status": "open", "location_id": "LOC-Q",
        "source": {"type": "goods_receipt", "id": "GR1", "number": "GR-00001", "line_id": "L1"}, "dispositions": []})
    return db


def _wq_env(monkeypatch, db, user):
    import routes.wms_quarantine as wq

    async def auth(_r):
        return user

    async def yes(db_, lid):
        return True

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(wq, "require_auth", auth)
    monkeypatch.setattr(wq, "get_db", lambda: db)
    monkeypatch.setattr(wq, "log_activity", noop)
    monkeypatch.setattr(wq.location_resolver, "location_exists", yes)
    return wq


def test_release_gr_reject_is_late_receipt_to_grni(monkeypatch, posting, stock):
    db = _t1_db()
    stock["onhand"]["X"] = 200.0            # 90 + 100 bernilai + 10 karantina
    wq = _wq_env(monkeypatch, db, WH)
    out = run(wq.release_item("q1", Req({"qty": 4, "to_location_id": "GD-L2"})))
    assert out["unit_price"] == 50000.0 and out["late_receipt"]["qty"] == 4
    assert posting.lines() == [("1-1401", 200000.0, 0), ("2-1150", 0, 200000.0)]   # dulu Cr beban 220.000
    assert posting.jes[-1]["source_module"] == "inventory_receive"
    mat = db.rahaza_materials.docs[0]
    assert mat["unit_cost"] == pytest.approx(55154.6392, abs=1e-3)                 # 10.700.000 / 194
    gl = db.warehouse_receiving.docs[0]
    assert gl["has_unbilled_lines"] is True
    assert gl["items"][0]["late_receipts"][0]["amount"] == 200000.0
    q = db.wh_quarantine_items.docs[0]
    assert q["remaining_qty"] == 6 and q["valued_qty"] == 0                        # sisa TETAP belum bernilai
    n_je = len(posting.jes)
    run(wq.scrap_item("q1", Req({"qty": 6})))                                       # sisa 6 → tanpa jurnal
    assert len(posting.jes) == n_je


def test_release_discount_price_only_finance(monkeypatch, posting, stock):
    db = _t1_db()
    stock["onhand"]["X"] = 200.0
    wq = _wq_env(monkeypatch, db, WH)
    with pytest.raises(HTTPException) as e:
        run(wq.release_item("q1", Req({"qty": 4, "to_location_id": "GD-L2", "unit_price": 45000})))
    assert e.value.status_code == 403 and "Keuangan" in e.value.detail
    wq = _wq_env(monkeypatch, db, FIN)
    out = run(wq.release_item("q1", Req({"qty": 4, "to_location_id": "GD-L2", "unit_price": 45000})))
    assert out["unit_price"] == 45000 and posting.lines() == [("1-1401", 180000.0, 0), ("2-1150", 0, 180000.0)]


def test_return_supplier_endpoint_gone_and_legacy_flag(monkeypatch):
    import routes.wms_quarantine as wq
    db = fm.FakeDB()
    wq2 = _wq_env(monkeypatch, db, WH)
    with pytest.raises(HTTPException) as e:
        run(wq2.return_to_supplier("q1", Req({"qty": 1})))
    assert e.value.status_code == 410 and "Retur Pembelian" in e.value.detail
    item = {"source": {"type": "goods_receipt"},
            "dispositions": [{"action": "return_supplier", "qty": 6},
                             {"action": "return_supplier", "qty": 2, "purchase_return_id": "r"},
                             {"action": "release", "qty": 4}]}
    assert wq.legacy_return_qty(item) == 6
    assert wq.legacy_return_qty({**item, "source": {"type": "cmt_receipt"}}) == 0     # retur permak ke CMT


# ══════════════════════ K11: tagihan dari GR & 3-way match ════════════════════
def test_billable_lines_late_and_debit_note_deduction():
    gr_invoiced = {"ap_invoice_id": "AP1", "items": [
        {"id": "L1", "received_qty": 100, "rejected_qty": 10, "unit_price": 50000,
         "late_receipts": [{"id": "lr1", "qty": 4, "unit_price": 50000, "amount": 200000, "ap_invoice_id": None}]}]}
    b = pr.gr_billable_lines(gr_invoiced)
    assert [(x["type"], x["qty"], x["amount"]) for x in b] == [("late", 4, 200000)]
    gr_open = {"items": [{"id": "L1", "received_qty": 100, "rejected_qty": 10, "unit_price": 50000,
                          "billing_deductions": [{"qty": 6, "amount": 300000}],
                          "late_receipts": [{"id": "lr1", "qty": 4, "unit_price": 45000, "amount": 180000}]}]}
    b = pr.gr_billable_lines(gr_open)
    assert [(x["type"], x["qty"], x["amount"]) for x in b] == [("base", 84, 4200000), ("late", 4, 180000)]
    v = pr.line_values(gr_open["items"][0])
    assert v["received_value"] == 4500000 - 300000 + 180000 and v["received_qty_total"] == 94


def _ap_env(monkeypatch, db):
    import routes.rahaza_ap_from_gr as apg

    async def fin(_r):
        return FIN

    async def mapping(db_, key):
        return dict(DEFAULT_MAP.get(key, {}))

    async def noop(*a, **k):
        return None

    async def num(db_):
        num.i += 1
        return f"AP-T-{num.i}"
    num.i = 0
    monkeypatch.setattr(apg, "_require_finance", fin)
    monkeypatch.setattr(apg, "_require_finance_view", fin)
    monkeypatch.setattr(apg, "get_db", lambda: db)
    monkeypatch.setattr(apg, "get_mapping", mapping)
    monkeypatch.setattr(apg, "log_activity", noop)
    monkeypatch.setattr(apg, "_gen_ap_number", num)
    return apg


def test_ap_from_gr_bills_late_receipt_once(monkeypatch):
    db = fm.FakeDB()
    db.warehouse_receiving.docs.append({
        "id": "GR1", "receipt_number": "GR-00001", "status": "received", "supplier_name": "PT Uji",
        "ap_invoice_id": "AP-OLD", "ap_invoice_number": "AP-OLD",
        "items": [{"id": "L1", "material_id": "X", "received_qty": 100, "rejected_qty": 10, "unit_price": 50000,
                   "late_receipts": [{"id": "lr1", "qty": 4, "unit_price": 50000, "amount": 200000,
                                      "source": "quarantine_release", "ap_invoice_id": None}]}],
        "has_unbilled_lines": True})
    apg = _ap_env(monkeypatch, db)
    avail = run(apg.grs_available_for_invoice(request=Req()))
    assert avail["total"] == 1 and avail["items"][0]["receivable_amount"] == 200000
    inv = run(apg.create_ap_invoice_from_gr(apg.CreateAPFromGRPayload(gr_ids=["GR1"]), Req()))
    assert [(i["gr_line_type"], i["qty"], i["amount"]) for i in inv["items"]] == [("late", 4, 200000)]
    assert inv["gl_grni_amount"] == 200000 and inv["gl_price_variance"] == 0
    gr = db.warehouse_receiving.docs[0]
    assert gr["items"][0]["late_receipts"][0]["ap_invoice_id"] == inv["id"] and gr["has_unbilled_lines"] is False
    with pytest.raises(HTTPException) as e:
        run(apg.create_ap_invoice_from_gr(apg.CreateAPFromGRPayload(gr_ids=["GR1"]), Req()))
    assert "sudah ditagih seluruhnya" in e.value.detail


def test_three_way_match_reads_late_and_returned_qty(monkeypatch):
    db = fm.FakeDB()
    db.rahaza_purchase_orders.docs.append({"id": "PO1", "po_number": "PO-1", "status": "approved", "vendor_name": "PT Uji",
                                           "items": [{"id": "pi1", "material_id": "X", "qty_ordered": 100, "unit_cost": 50000}]})
    db.warehouse_receiving.docs.append({"id": "GR1", "po_id": "PO1", "status": "received", "items": [
        {"id": "L1", "po_item_id": "pi1", "material_id": "X", "received_qty": 100, "rejected_qty": 10, "unit_price": 50000,
         "late_receipts": [{"id": "lr", "qty": 4, "unit_price": 50000, "amount": 200000}],
         "billing_deductions": [{"qty": 6, "amount": 300000}]}]})
    db[pr.RTP_COLL].docs += [
        {"id": "R1", "po_id": "PO1", "status": "settled", "lines": [{"po_item_id": "pi1", "material_id": "X", "qty": 6}]},
        {"id": "R2", "po_id": "PO1", "status": "cancelled", "lines": [{"po_item_id": "pi1", "material_id": "X", "qty": 9}]}]
    apg = _ap_env(monkeypatch, db)
    det = run(apg.three_way_match_detail("PO1", Req()))
    ln = det["lines"][0]
    # 90 bersih + 4 susulan − 6 diselesaikan nota debit = 88; nilai 4.500.000 + 200.000 − 300.000
    assert (ln["net_qty"], ln["late_qty"], ln["returned_qty"], ln["received_value"]) == (88, 4, 6, 4400000)
    dash = run(apg.three_way_match_dashboard(Req(), status=None, vendor_name=None, supplier_id=None, limit=100))
    row = dash["rows"][0]
    assert (row["total_received_qty"], row["total_late_qty"], row["total_returned_qty"]) == (88, 4, 6)
    assert row["total_received_value"] == 4400000 and row["match_status"] == "pending"


def test_uninvoiced_gr_warning_for_manual_invoice(monkeypatch):
    import routes.rahaza_ap_from_gr as apg
    db = fm.FakeDB()
    db.warehouse_receiving.docs.append({"id": "GR9", "receipt_number": "GR-9", "status": "received",
                                        "supplier_name": "PT Uji", "items": [
                                            {"id": "L", "received_qty": 10, "unit_price": 1000}]})
    w = run(apg.uninvoiced_gr_warning(db, vendor_name="pt uji"))
    assert w["amount"] == 10000 and "gunakan Tagihan dari GR".lower() in w["warning"].lower()
    assert run(apg.uninvoiced_gr_warning(db, vendor_name="PT Lain"))["warning"] is None


# ════════════════════════ K11: Retur Pembelian & Nota Debit ═══════════════════
def _rtp_env(monkeypatch, db, user=SA):
    import routes.rahaza_purchase_returns as rpr

    async def auth(_r):
        return user

    async def noop(*a, **k):
        return None

    async def yes(db_, lid):
        return True
    for f in ("_require_proc_wh", "_require_fin", "_require_view"):
        monkeypatch.setattr(rpr, f, auth)
    monkeypatch.setattr(rpr, "get_db", lambda: db)
    monkeypatch.setattr(rpr, "log_activity", noop)
    from core import location_resolver
    monkeypatch.setattr(location_resolver, "location_exists", yes)
    import routes.rahaza_inventory_shared as ris

    async def logmv(db_, user_, **kw):
        return kw
    monkeypatch.setattr(ris, "_log_movement", logmv)
    _counter(monkeypatch, rpr)
    return rpr


def _rtp_db(*, billed=False):
    db = _t1_db()
    db.rahaza_materials.docs[0]["unit_cost"] = 55000.0
    gr = db.warehouse_receiving.docs[0]
    if billed:
        gr.update({"ap_invoice_id": "AP1", "ap_invoice_number": "AP-0001"})
        db.rahaza_ap_invoices.docs.append({"id": "AP1", "invoice_number": "AP-0001", "vendor_name": "PT Uji",
                                           "status": "sent", "total": 4500000, "balance": 4500000,
                                           "gl_ap_account_code": "2-1100-SUP-1"})
    db.rahaza_material_stock.docs.append({"material_id": "X", "location_id": "GD-L2", "qty": 190, "reserved_quantity": 0})
    return db


def test_rtp_valued_debit_note_before_invoice_reduces_grni_and_billing(monkeypatch, posting, stock):
    db = _rtp_db()
    rpr = _rtp_env(monkeypatch, db)
    doc = run(rpr.create_purchase_return(Req({"settlement": "debit_note", "reason": "berlubang", "gr_id": "GR1",
                                              "lines": [{"material_id": "X", "location_id": "GD-L2", "qty": 6,
                                                         "gr_item_id": "L1"}]})))
    assert doc["rtp_number"].startswith("RTP-") and doc["total_amount"] == 300000 and doc["ppn_amount"] == 0
    sent = run(rpr.send_purchase_return(doc["id"], Req()))
    assert sent["status"] == "awaiting_settlement" and sent["lines"][0]["claim_amount"] == 300000
    assert posting.lines() == [("1-1401", 0, 330000.0), ("1-1620", 300000.0, 0), ("5-1900", 30000.0, 0)]
    assert ("issue", ("X", "GD-L2", 6)) in stock["ops"]
    dn = run(rpr.issue_debit_note(Req({"purchase_return_id": doc["id"]})))
    assert dn["dn_number"].startswith("ND-") and dn["grni_amount"] == 300000 and dn["ap_amount"] == 0
    assert posting.lines() == [("1-1620", 0, 300000.0), ("2-1150", 300000.0, 0)]
    assert posting.gl("1-1620") == 0 and posting.gl("1-1401") == -330000 and posting.gl("5-1900") == 30000
    base = pr.gr_billable_lines(db.warehouse_receiving.docs[0])[0]
    assert (base["qty"], base["amount"]) == (84, 4200000)              # tagihan dari GR membaca qty retur
    assert db[pr.RTP_COLL].docs[0]["status"] == "settled"


def test_rtp_after_invoice_hits_ap_and_supplier_balance(monkeypatch, posting, stock):
    db = _rtp_db(billed=True)
    rpr = _rtp_env(monkeypatch, db)
    doc = run(rpr.create_purchase_return(Req({"settlement": "debit_note", "reason": "salah warna", "gr_id": "GR1",
                                              "lines": [{"material_id": "X", "location_id": "GD-L2", "qty": 6}]})))
    run(rpr.send_purchase_return(doc["id"], Req()))
    dn = run(rpr.issue_debit_note(Req({"purchase_return_id": doc["id"]})))
    assert dn["ap_amount"] == 300000 and dn["grni_amount"] == 0
    assert posting.lines() == [("1-1620", 0, 300000.0), ("2-1100-SUP-1", 300000.0, 0)]
    bal = run(rpr.supplier_balances(Req()))
    row = bal["items"][0]
    assert (row["invoice_balance"], row["debit_note_ap"], row["net_payable"]) == (4500000, 300000, 4200000)


def test_rtp_unvalued_reject_exchange_then_replacement_is_billable(monkeypatch, posting, stock):
    db = _rtp_db()
    stock["onhand"]["X"] = 200.0
    rpr = _rtp_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:                      # refund atas reject GR → ditolak
        run(rpr.create_purchase_return(Req({"settlement": "refund", "reason": "x", "quarantine_item_id": "q1", "qty": 10})))
    assert "Refund hanya" in e.value.detail
    doc = run(rpr.create_purchase_return(Req({"settlement": "exchange", "reason": "cacat", "quarantine_item_id": "q1",
                                              "qty": 10})))
    assert doc["gr_id"] == "GR1" and doc["lines"][0]["unvalued_qty_est"] == 10
    n = len(posting.jes)
    sent = run(rpr.send_purchase_return(doc["id"], Req()))
    assert len(posting.jes) == n                                 # reject belum bernilai: kirim tanpa jurnal
    q = db.wh_quarantine_items.docs[0]
    assert q["status"] == "closed" and q["dispositions"][-1]["action"] == "purchase_return"
    assert q["dispositions"][-1]["rtp_number"] == sent["rtp_number"]
    run(rpr.receive_replacement(doc["id"], Req({"location_id": "GD-L2"})))
    assert posting.lines() == [("1-1401", 500000.0, 0), ("2-1150", 0, 500000.0)]
    late = db.warehouse_receiving.docs[0]["items"][0]["late_receipts"]
    assert [(x["qty"], x["amount"], x["source"]) for x in late] == [(10, 500000, "rtp_replacement")]
    assert db[pr.RTP_COLL].docs[0]["status"] == "settled"


def test_rtp_destroy_da_borne_reject_books_expense_and_billable(monkeypatch, posting, stock):
    db = _rtp_db()
    rpr = _rtp_env(monkeypatch, db)
    doc = run(rpr.create_purchase_return(Req({"settlement": "destroy", "destroy_borne_by": "da", "reason": "busuk",
                                              "quarantine_item_id": "q1", "qty": 10})))
    out = run(rpr.send_purchase_return(doc["id"], Req()))
    assert out["status"] == "settled"
    assert posting.lines() == [("2-1150", 0, 500000.0), ("6-4300", 500000.0, 0)]
    assert db.warehouse_receiving.docs[0]["items"][0]["late_receipts"][0]["source"] == "rtp_destroy_da"


def test_rtp_accept_discount_case_a_and_b(monkeypatch, posting, stock):
    db = _rtp_db()
    stock["onhand"]["X"] = 200.0
    db.wh_quarantine_items.docs.append({
        "id": "q2", "material_id": "X", "material_code": "KN", "unit": "kg", "qty": 6, "remaining_qty": 6,
        "valued_qty": 6, "status": "open", "location_id": "LOC-Q",
        "source": {"type": "grn_inspection", "id": "GR1", "line_id": "L1"}, "dispositions": []})
    rpr = _rtp_env(monkeypatch, db)
    doc = run(rpr.create_purchase_return(Req({"settlement": "accept_discount", "reason": "warna sedikit beda",
                                              "lines": [{"quarantine_item_id": "q1", "qty": 10},
                                                        {"quarantine_item_id": "q2", "qty": 6}]})))
    with pytest.raises(HTTPException):                            # tanpa kirim barang
        run(rpr.send_purchase_return(doc["id"], Req()))
    with pytest.raises(HTTPException):                            # harga diskon wajib diketik Keuangan
        run(rpr.issue_debit_note(Req({"purchase_return_id": doc["id"], "to_location_id": "GD-L2"})))
    # qty bernilai = 200 − 10 (reject belum bernilai) = 190; setelah lepas 10 @45.000 → 200
    dn = run(rpr.issue_debit_note(Req({"purchase_return_id": doc["id"], "disc_price": 45000, "to_location_id": "GD-L2"})))
    assert dn["total_amount"] == 16 * 5000 and dn["grni_amount"] == 30000 and dn["ap_amount"] == 0
    rel = next(je for je in posting.jes if je["source_module"] == "inventory_receive")
    assert sorted((ln["account_code"], ln["debit"], ln["credit"]) for ln in rel["lines"]) == [
        ("1-1401", 450000.0, 0), ("2-1150", 0, 450000.0)]
    assert posting.lines() == [("1-1401", 0, 30000.0), ("2-1150", 30000.0, 0)]
    # HPP: (190 × 55.000 + 10 × 45.000) / 200 = 54.500 → potongan 30.000 / 200 → 54.350
    assert db.rahaza_materials.docs[0]["unit_cost"] == pytest.approx(54350.0)
    ded = db.warehouse_receiving.docs[0]["items"][0]["billing_deductions"]
    assert [(d["qty"], d["amount"]) for d in ded] == [(0, 30000)]


def test_purchase_return_profile_and_role_registration():
    m = DEFAULT_MAP["purchase_return"]
    assert m == {"inventory_rm": "1-1401", "inventory_accessory": "1-1402", "supplier_claim": "1-1620",
                 "grni": "2-1150", "ap": "2-1100", "price_variance": "5-1900", "scrap_expense": "6-4300"}
    cons = cb.role_consumers()
    for role in ("supplier_claim", "grni", "ap", "price_variance", "scrap_expense", "inventory_rm", "inventory_accessory"):
        assert f"purchase_return.{role}" in cons, role
    plan = pr.plan_send(settlement="debit_note", borne_by=None, valued_qty=6, unvalued_qty=4, gr_price=50000,
                        wac=45000, kind="aksesoris")
    assert sorted((ln["role"], ln["debit"], ln["credit"]) for ln in plan["lines"]) == [
        ("inventory", 0, 270000), ("price_variance", 0, 30000), ("supplier_claim", 300000, 0)]
    assert plan["lines"][1]["kind"] == "aksesoris"


# ═══════════════════════ K10: hapus SJ material & Retur Material ═════════════
def _vs_env(monkeypatch, db):
    import routes.vendor_shipment as vs

    async def auth(_r):
        return SA

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(vs, "require_auth", auth)
    monkeypatch.setattr(vs, "get_db", lambda: db)
    monkeypatch.setattr(vs, "log_activity", noop)
    monkeypatch.setattr(vs, "deny_klien", lambda u: None)
    return vs


def test_delete_material_shipment_locked_after_issue(monkeypatch):
    db = fm.FakeDB()
    db.vendor_shipments.docs.append({"id": "S1", "shipment_number": "SJ-001"})
    db.rahaza_material_issues.docs.append({"id": "MI1", "mi_number": "MI-001", "vendor_shipment_id": "S1",
                                           "status": "issued"})
    vs = _vs_env(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(vs.delete_vendor_shipment("S1", Req()))
    assert e.value.status_code == 400 and "Retur Material" in e.value.detail and "MI-001" in e.value.detail
    assert db.vendor_shipments.docs                                   # tidak terhapus
    db.rahaza_material_issues.docs[0]["return_status"] = "full"       # semua bahan sudah diretur → boleh
    assert run(vs.delete_vendor_shipment("S1", Req())) == {"success": True}


def test_delete_shipment_before_issue_allowed_and_cancels_pending_mi(monkeypatch):
    db = fm.FakeDB()
    db.vendor_shipments.docs.append({"id": "S2", "shipment_number": "SJ-002"})
    db.rahaza_material_issues.docs.append({"id": "MI2", "vendor_shipment_id": "S2", "status": "pending_approval"})
    vs = _vs_env(monkeypatch, db)
    assert run(vs.delete_vendor_shipment("S2", Req())) == {"success": True}
    assert db.rahaza_material_issues.docs[0]["status"] == "cancelled"
    assert not db.vendor_shipments.docs


def _pmr_env(monkeypatch, db):
    import routes.production_material_returns as pmr

    async def auth(_r):
        return SA

    async def noop(*a, **k):
        return None

    async def yes(db_, lid):
        return True
    adds = []

    async def add(mid, loc, qty, **kw):
        adds.append((mid, loc, qty))
        return {}
    monkeypatch.setattr(pmr, "require_auth", auth)
    monkeypatch.setattr(pmr, "get_db", lambda: db)
    monkeypatch.setattr(pmr, "log_activity", noop)
    monkeypatch.setattr(pmr.stock_service, "add", add)
    from core import location_resolver
    monkeypatch.setattr(location_resolver, "location_exists", yes)
    return pmr, adds


def _mi_db(cost_target=None):
    db = fm.FakeDB()
    db.rahaza_materials.docs += [{"id": "K", "code": "KN-1", "type": "fabric", "unit_cost": 60000.0},
                                 {"id": "A", "code": "A-LBL", "type": "accessory", "unit_cost": 1500.0}]
    db.rahaza_material_issues.docs.append({
        "id": "MI1", "mi_number": "MI-001", "status": "issued", "vendor_shipment_id": "S1", "cost_target": cost_target,
        "items": [{"material_id": "K", "qty_issued": 120, "unit_cost_applied": 55000.0},
                  {"material_id": "A", "qty_issued": 50, "unit_cost_applied": 1200.0}]})
    db.production_material_returns.docs.append({
        "id": 7, "ref_no": "PMR/1", "status": "approved", "material_issue_id": "MI1", "mi_number": "MI-001",
        "items": [{"material_id": "K", "material_code": "KN-1", "qty_returned": 20, "condition": "good"},
                  {"material_id": "A", "material_code": "A-LBL", "qty_returned": 10, "condition": "good"},
                  {"material_id": "K", "material_code": "KN-1", "qty_returned": 2, "condition": "damaged"}]})
    return db


def test_material_return_reverses_wip_at_issue_cost_and_updates_mi(monkeypatch, posting):
    db = _mi_db()
    pmr, adds = _pmr_env(monkeypatch, db)
    out = run(pmr.receive_return(Req(), "7", pmr.ActionModel(note="salah kirim", location_id="GD-L2")))
    assert adds == [("K", "GD-L2", 20.0), ("A", "GD-L2", 10.0)]       # rusak tidak kembali ke stok
    assert posting.lines() == [("1-1401", 1100000.0, 0), ("1-1402", 12000.0, 0), ("1-1403", 0, 1112000.0)]
    assert posting.jes[-1]["source_module"] == "inventory_issue_return"
    mi = db.rahaza_material_issues.docs[0]
    assert [i["qty_returned"] for i in mi["items"]] == [20, 10] and mi["return_status"] == "partial"
    assert mi["status"] == "issued" and out["mi_return_status"] == "partial"
    assert db.production_material_returns.docs[0]["gl_je_number"] == posting.jes[-1]["je_number"]


def test_material_return_maklon_credits_project_cost_and_qty_guard(monkeypatch, posting):
    db = _mi_db(cost_target="maklon")
    pmr, _ = _pmr_env(monkeypatch, db)
    run(pmr.receive_return(Req(), "7", pmr.ActionModel(location_id="GD-L2")))
    assert ("5-4100", 0, 1112000.0) in posting.lines()
    # retur lain yang masih berjalan 100 + baru 30 > dikeluarkan 120 − sudah diretur 20 → ditolak
    db.production_material_returns.docs += [
        {"id": 8, "status": "submitted", "material_issue_id": "MI1", "items": [{"material_id": "K", "qty_returned": 80}]},
        {"id": 9, "status": "draft", "material_issue_id": "MI1", "items": [{"material_id": "K", "qty_returned": 30}]}]
    with pytest.raises(HTTPException) as e:
        run(pmr.submit_return(Req(), "9"))
    assert "melebihi sisa MI" in e.value.detail
    assert pmr.mi_after_return({"items": [{"material_id": "K", "qty_issued": 5}]}, {"K": 5})["return_status"] == "full"


# ═════════════════════════ K12: Set HPP = revaluasi ════════════════════════════
def test_set_hpp_posts_revaluation_and_gl_equals_stock_value(monkeypatch, posting, stock):
    import utils.counters as uc
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "BIS", "code": "A-BIS-0001", "type": "accessory", "unit": "m",
                                     "unit_cost": 17500.0})
    stock["onhand"]["BIS"] = 200.0
    _counter(monkeypatch, uc)
    # GL 1-1402 dari dua penerimaan: 100 × 15.000 + 100 × 20.000 = 3.500.000 = 200 × 17.500
    posting.jes.append({"lines": [{"account_code": "1-1402", "debit": 3500000.0, "credit": 0},
                                  {"account_code": "2-1150", "debit": 0, "credit": 3500000.0}]})
    bad = run(av.set_unit_cost(db, "BIS", 18000, actor=FIN, notes=""))
    assert bad["ok"] is False and "Alasan" in bad["error"] and db.rahaza_materials.docs[0]["unit_cost"] == 17500.0
    res = run(av.set_unit_cost(db, "BIS", 18000, actor=FIN, notes="audit harga beli"))
    assert res["ok"] and res["revaluation"]["delta_value"] == 100000 and res["revaluation"]["reval_number"].startswith("RVL-")
    assert posting.lines() == [("1-1402", 100000.0, 0), ("5-1950", 0, 100000.0)]
    assert posting.gl("1-1402") == 3600000.0 == 200 * db.rahaza_materials.docs[0]["unit_cost"]
    rv = db[av.REVALUATION_COLL].docs[0]
    assert rv["actor"]["name"] == "Keuangan Uji" and rv["reason"] == "audit harga beli" and rv["je_number"]
    hist = db[av.COST_HISTORY].docs[-1]
    assert hist["old_unit_cost"] == 17500 and hist["new_unit_cost"] == 18000 and "RVL-" in hist["notes"]
    # turun: Dr 5-1950 / Cr 1-1402 sebesar 200 × 500
    run(av.set_unit_cost(db, "BIS", 17500, actor=FIN, notes="koreksi balik"))
    assert posting.lines() == [("1-1402", 0, 100000.0), ("5-1950", 100000.0, 0)]
    assert posting.gl("1-1402") == 3500000.0


def test_set_hpp_journal_failure_keeps_cost(monkeypatch, stock):
    import utils.counters as uc
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "BIS", "code": "A", "type": "accessory", "unit_cost": 17500.0})
    stock["onhand"]["BIS"] = 10.0
    _counter(monkeypatch, uc)

    async def fail(db_, reval, user):
        return {"ok": False, "error": "periode tertutup"}
    monkeypatch.setattr(rp, "post_inventory_revaluation", fail)
    res = run(av.set_unit_cost(db, "BIS", 18000, actor=FIN, notes="x"))
    assert res["ok"] is False and "HPP TIDAK diubah" in res["error"]
    assert db.rahaza_materials.docs[0]["unit_cost"] == 17500.0 and not db[av.REVALUATION_COLL].docs
