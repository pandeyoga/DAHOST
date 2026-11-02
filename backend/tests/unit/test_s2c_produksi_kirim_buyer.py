"""Uji unit HERMETIK paket S2-C (2026-11-02) — produksi, maklon & pengiriman buyer.

Angka harapan dihitung tangan dari skenario audit w3 (PO-MKL 100 pcs, tarif CMT 12.000,
harga jasa 20.000; PO-INT 10 pcs) — lihat docstring tiap uji.

Jalankan:  cd backend && python -m pytest tests/unit/test_s2c_produksi_kirim_buyer.py -q
"""
import asyncio
import inspect
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402
from p3_fakes import FakeDB  # noqa: E402
from core import dispatch_capacity as dcap  # noqa: E402
from core import production_qty_ledger as qled  # noqa: E402
from core import short_shipment as sm  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    sent = []

    async def notify(db, **kw):
        sent.append(kw)
    counter = {"n": 0}

    async def number(db, collection, prefix):
        counter["n"] += 1
        return f"{prefix}{counter['n']:05d}"
    monkeypatch.setattr(sm, "_notify", notify)
    monkeypatch.setattr(sm, "_number", number)
    return sent


# ─── data skenario w3 (maklon 100 pcs) ───────────────────────────────────────
def _maklon_db(*, buyer_items=(), receipts=None, lines=None, permaks=(), shorts=(), jobs=None, jis=None):
    po = {"id": "po-m", "po_number": "PO-MKL-1", "business_type": "maklon", "customer_name": "PT Buyer"}
    poi = {"id": "poi-m", "po_id": "po-m", "qty": 100, "sku": "KLN-A", "cmt_price_snapshot": 12000,
           "selling_price_snapshot": 20000}
    return FakeDB(
        production_pos=[po], po_items=[poi],
        production_jobs=jobs if jobs is not None else [
            {"id": "job-1", "shipment_type": "NORMAL", "vendor_id": "v-1", "vendor_shipment_id": "vs-1"}],
        production_job_items=jis if jis is not None else [
            {"id": "ji-1", "job_id": "job-1", "po_item_id": "poi-m", "produced_qty": 100,
             "created_at": "2026-11-01"}],
        cmt_receipts=receipts or [], cmt_receipt_lines=lines or [],
        buyer_shipments=[{"id": "decl-1", "receiver_type": "da"}, {"id": "sj-1", "receiver_type": "buyer"},
                         {"id": "sj-2", "receiver_type": "buyer"}],
        buyer_shipment_items=list(buyer_items), dewi_cmt_permak=list(permaks),
        cmt_short_shipments=list(shorts), buyer_short_records=[])


R1 = {"id": "r1", "status": "completed_qc"}
R2 = {"id": "r2", "status": "completed_qc"}
L1 = {"id": "l1", "receipt_id": "r1", "po_item_id": "poi-m", "qty_actual": 55, "reject_qty": 5,
      "qty_claimed_by_cmt": 60, "qty_shipped_by_cmt": 60}
L2 = {"id": "l2", "receipt_id": "r2", "po_item_id": "poi-m", "qty_actual": 40, "reject_qty": 0,
      "qty_claimed_by_cmt": 40, "qty_shipped_by_cmt": 40}
DECL = {"id": "d1", "shipment_id": "decl-1", "po_item_id": "poi-m", "po_id": "po-m", "qty_shipped": 60}


# ── Butir 1 — K17 SSOT: deklarasi CMT→DA TIDAK dihitung "dikirim ke buyer" ──
def test_s1_deklarasi_cmt_tidak_dihitung_dikirim():
    """S1: CMT→DA 60 (lolos 55, reject 5), belum ada SJ buyer ⇒ dikirim 0, sisa 55, sisa order 100."""
    db = _maklon_db(buyer_items=[DECL], receipts=[R1], lines=[L1])
    q = run(dcap.po_item_quantities(db, ["poi-m"]))["poi-m"]
    assert (q["dispatched"], q["shippable"], q["remaining_vs_order"]) == (0, 55, 100)
    assert (q["accepted_total"], q["reject"], q["reject_open"]) == (55, 5, 5)


def test_s2_sj_buyer_50_dan_status_po():
    """S2: SJ buyer 50 ⇒ dikirim 50, sisa bisa kirim 5, sisa order 50, status Partially."""
    db = _maklon_db(buyer_items=[DECL, {"id": "b1", "shipment_id": "sj-1", "po_item_id": "poi-m",
                                        "qty_shipped": 50}], receipts=[R1], lines=[L1])
    pq = run(dcap.po_quantities(db, ["po-m"]))["po-m"]
    assert pq["totals"]["dispatched"] == 50 and pq["totals"]["shippable"] == 5
    assert pq["ship_status"] == "Partially Shipped"


# ── Butir 2 — pagar kapasitas SELALU per po_item ──
def test_s5a_form_hanya_penerimaan_baru_tetap_per_po_item():
    """S5a: lolos 55+40=95, sudah dikirim 50 ⇒ form R2 saja = 45 (dulu 0)."""
    db = _maklon_db(buyer_items=[DECL, {"id": "b1", "shipment_id": "sj-1", "po_item_id": "poi-m",
                                        "qty_shipped": 50}], receipts=[R1, R2], lines=[L1, L2])
    rows = run(dcap.by_receipts(db, ["r2"]))
    assert len(rows) == 1 and rows[0]["shippable"] == 45
    board = run(dcap.by_po_items(db, ["poi-m"]))
    assert board[0]["shippable"] == rows[0]["shippable"]


def test_diterima_tidak_pernah_melebihi_dikirim_di_kapasitas():
    """S11b: diterima 7 untuk kirim 5 tidak boleh mengurangi kapasitas lebih dari 5."""
    assert dcap.item_dispatched({"qty_shipped": 5, "qty_received": 7}) == 5
    assert dcap.item_dispatched({"qty_shipped": 50, "qty_received": 47}) == 47
    assert dcap.item_dispatched({"qty_shipped": 10, "qty_received": None}) == 10


# ── Butir 7 — internal: serah terima maksimal = qty lolos ──
def _internal_db():
    return FakeDB(
        production_pos=[{"id": "po-i", "po_number": "PO-INT-1", "business_type": "internal"}],
        po_items=[{"id": "poi-i", "po_id": "po-i", "qty": 10, "sku": "DA-1101-CRL"}],
        production_jobs=[{"id": "j-main", "shipment_type": "NORMAL", "vendor_id": "v-1", "vendor_shipment_id": "vs"},
                         {"id": "j-rwk", "shipment_type": "REWORK", "vendor_id": "v-1", "vendor_shipment_id": "rw"}],
        production_job_items=[
            {"id": "ji-main", "job_id": "j-main", "po_item_id": "poi-i", "produced_qty": 10, "created_at": "2026-11-01"},
            {"id": "ji-rwk", "job_id": "j-rwk", "po_item_id": "poi-i", "produced_qty": 1, "created_at": "2026-11-02"}],
        cmt_receipts=[{"id": "ri1", "status": "completed_qc"}, {"id": "ri2", "status": "completed_qc"}],
        cmt_receipt_lines=[
            {"id": "li1", "receipt_id": "ri1", "po_item_id": "poi-i", "qty_actual": 9, "reject_qty": 1},
            {"id": "li2", "receipt_id": "ri2", "po_item_id": "poi-i", "qty_actual": 1, "reject_qty": 0}],
        dewi_cmt_permak=[{"id": "pm", "po_item_id": "poi-i", "source": "reject", "permak_type": "retur_ke_cmt",
                          "qty": 1, "qty_fixed": 1, "qty_scrap": 0, "status": "selesai_berhasil"}],
        buyer_shipments=[], buyer_shipment_items=[], cmt_short_shipments=[], buyer_short_records=[])


def test_s14_internal_maks_lolos_10_bukan_produksi_11():
    """S14: produksi 10 (+1 job rework), lolos 9+1=10 ⇒ produced_main 10, maks serah terima 10."""
    db = _internal_db()
    q = run(dcap.po_item_quantities(db, ["poi-i"]))["poi-i"]
    assert (q["produced_main"], q["rework_produced"], q["accepted_total"], q["shippable"]) == (10, 1, 10, 10)
    from routes.buyer_shipment import _validate_source_receipts_cap
    with pytest.raises(HTTPException) as e:
        run(_validate_source_receipts_cap(db, [], [{"po_item_id": "poi-i", "sku": "DA-1101-CRL",
                                                    "qty_shipped": 11}], {}, require_receipts=False))
    assert e.value.status_code == 400 and "sisa 10 pcs" in e.value.detail
    run(_validate_source_receipts_cap(db, [], [{"po_item_id": "poi-i", "qty_shipped": 10}], {},
                                      require_receipts=False))


# ── Butir 4 — rework retur-ke-CMT menaikkan repaired di job INDUK ──
def test_rework_retur_ke_cmt_menaikkan_repaired_job_induk():
    """S6: reject 5 = sendiri 3 + retur 2. Retur selesai fixed 2 ⇒ job INDUK repaired_cmt +2,
    rework_open 2→0; job anak REWORK (terbaru) tidak disentuh (dulu −2)."""
    db = _maklon_db(
        receipts=[R1], lines=[{**L1, "job_item_id": "ji-1"}],
        jobs=[{"id": "job-1", "shipment_type": "NORMAL", "vendor_id": "v"},
              {"id": "job-r", "shipment_type": "REWORK", "vendor_id": "v"}],
        jis=[{"id": "ji-1", "job_id": "job-1", "po_item_id": "poi-m", "produced_qty": 100,
              "qty_reject": 5, "qty_rework_open": 2, "qty_repaired": 3, "created_at": "2026-11-01"},
             {"id": "ji-r", "job_id": "job-r", "po_item_id": "poi-m", "produced_qty": 2,
              "created_at": "2026-11-02"}])
    permak = {"id": "pm-r", "po_item_id": "poi-m", "permak_type": "retur_ke_cmt",
              "source_receipt_line_id": "l1", "permak_number": "PMK-2"}
    out = run(qled.apply_rework_outcome(db, permak, qty_fixed=2, qty_scrap=0))
    main = next(d for d in db["production_job_items"].docs if d["id"] == "ji-1")
    child = next(d for d in db["production_job_items"].docs if d["id"] == "ji-r")
    assert (main["qty_repaired_cmt"], main["qty_rework_open"]) == (2, 0)
    assert child.get("qty_rework_open", 0) == 0
    v = out["ledger"]
    assert v["qty_repaired"] == 5 and v["qty_reject_undecided"] == 0   # INV-Q2: 5 = 0+5+0


def test_receipt_line_job_anak_rework_dialihkan_ke_induk():
    db = _maklon_db(jobs=[{"id": "job-1", "shipment_type": "NORMAL"}, {"id": "job-r", "shipment_type": "REWORK"}],
                    jis=[{"id": "ji-1", "job_id": "job-1", "po_item_id": "poi-m", "created_at": "1"},
                         {"id": "ji-r", "job_id": "job-r", "po_item_id": "poi-m", "created_at": "2"}])
    ji = run(qled.resolve_job_item_for_line(db, {"job_item_id": "ji-r", "po_item_id": "poi-m"}))
    assert ji["id"] == "ji-1"
    assert run(qled.resolve_job_item_for_line(db, {"po_item_id": "poi-m"}))["id"] == "ji-1"


def test_sj_rework_business_type_mengikuti_po(monkeypatch):
    from routes import dewi_cmt_permak as dp
    import utils.counters as uc

    async def gen(db, coll, field, prefix, width=4, **kw):
        return f"{prefix}00001"
    monkeypatch.setattr(uc, "gen_prefixed_number", gen)
    db = _internal_db()
    db["vendor_shipments"].docs = []
    permak = {"id": "pm", "po_id": "po-i", "po_item_id": "poi-i", "vendor_id": "v-1", "qty": 1,
              "permak_number": "PMK-1"}
    db["dewi_cmt_permak"].docs.append(dict(permak))
    res = run(dp._create_rework_shipment(db, permak, {"name": "uji"}))
    assert res["ok"] and db["vendor_shipments"].docs[0]["business_type"] == "internal"


# ── Butir 3 — diterima ≤ dikirim, koreksi dua arah ──
def _buyer_item_db():
    return FakeDB(buyer_short_records=[], buyer_shipment_items=[
        {"id": "bi", "shipment_id": "sj-1", "po_item_id": "poi-m", "po_id": "po-m", "sku": "KLN-A",
         "qty_shipped": 10, "dispatch_seq": 3}], production_pos=[], users=[])


def test_s12_koreksi_qty_diterima_dua_arah():
    """S12a: terima 8 dari 10 ⇒ SEL-BYR 2 open, SJ 8. S12b: koreksi kembali 10 ⇒ selisih
    dibatalkan, SJ 10 (dulu qty_received 10 > qty_shipped 8, selisih tetap open)."""
    db = _buyer_item_db()
    ship = {"id": "sj-1", "shipment_number": "SJ-1", "receiver_type": "buyer"}
    item = db["buyer_shipment_items"].docs[0]
    run(sm.apply_buyer_receipt(db, shipment=ship, item=dict(item), new_received=8, reason="buyer 8"))
    item = db["buyer_shipment_items"].docs[0]
    s = db["buyer_short_records"].docs[0]
    assert (item["qty_shipped"], item["qty_shipped_claimed"], s["qty_short"], s["status"]) == (8, 10, 2, "open")
    run(sm.apply_buyer_receipt(db, shipment=ship, item=dict(item), new_received=10, reason="salah input"))
    item = db["buyer_shipment_items"].docs[0]
    s = db["buyer_short_records"].docs[0]
    assert item["qty_shipped"] == 10 and s["status"] == "cancelled" and s["qty_short"] == 0


def test_s11b_diterima_lebih_dari_dikirim_ditolak():
    db = _buyer_item_db()
    with pytest.raises(sm.BuyerReceiptError) as e:
        run(sm.apply_buyer_receipt(db, shipment={"id": "sj-1"}, item=dict(db["buyer_shipment_items"].docs[0]),
                                   new_received=12))
    assert "melebihi qty dikirim" in str(e.value)


def test_s10b_hapus_sj_kirim_ulang_membuka_kembali_selisih():
    """S9→S10: SEL-BYR 3 ditutup SJ-2 (5 pcs); SJ-2 dihapus ⇒ SEL-BYR kembali open 3."""
    db = FakeDB(buyer_short_records=[{"id": "s1", "short_number": "SEL-BYR-1", "po_item_id": "poi-m",
                                      "qty_short": 3, "qty_resolved": 0, "status": "open",
                                      "created_at": "2026-11-02"}])
    r = run(sm.resolve_buyer_shorts_on_dispatch(db, po_item_id="poi-m", qty=5,
                                                shipment={"id": "sj-2", "shipment_number": "SJ-2"},
                                                shipment_item_id="bi-2"))
    s = db["buyer_short_records"].docs[0]
    assert r["resolved"] == 3 and s["status"] == "resolved" and s["resolution_links"][0]["qty"] == 3
    rr = run(sm.reopen_buyer_shorts_for_item(db, shipment_item_id="bi-2"))
    s = db["buyer_short_records"].docs[0]
    assert rr["reopened"] == 3 and s["status"] == "open" and s["qty_resolved"] == 0


def test_completed_hanya_bila_semua_baris_tercatat():
    """S11: dispatch 100 penuh, satu baris belum dicatat ⇒ is_full tapi BELUM fully_confirmed."""
    from routes.production_maklon_bridge import compute_po_fulfillment
    items = [{"id": "b1", "shipment_id": "sj-1", "po_item_id": "poi-m", "qty_shipped": 50, "qty_received": 50},
             {"id": "b2", "shipment_id": "sj-1", "po_item_id": "poi-m", "qty_shipped": 50}]
    db = _maklon_db(buyer_items=items, receipts=[R1, R2], lines=[L1, L2])
    f = run(compute_po_fulfillment(db, "po-m"))
    assert f["is_full"] and not f["is_fully_confirmed"] and f["lines_unrecorded"] == 1
    db["buyer_shipment_items"].docs[1]["qty_received"] = 50
    assert run(compute_po_fulfillment(db, "po-m"))["is_fully_confirmed"]


# ── Butir 5 — status SJ dihitung ──
def test_s7_status_sj_fully_shipped_dihitung():
    items = [{"po_item_id": "p", "ordered_qty": 100, "qty_shipped": q} for q in (50, 40, 10)]
    p = dcap.shipment_progress(items)
    assert (p["ship_status"], p["progress_pct"], p["total_received"]) == ("Fully Shipped", 100, 100)
    assert dcap.shipment_progress(items[:2])["ship_status"] == "Partially Shipped"


# ── Butir 6 — tagihan CMT ditandai, tidak diubah; tagihan ≤ produksi ──
def test_s13_koreksi_qc_menandai_tagihan_dan_notifikasi_keuangan(_quiet):
    """S13: tagihan 40 × 12.000 = 480.000; lolos dikoreksi 40→39 ⇒ nilai TETAP 480.000,
    lebih tagih 1 pcs = 12.000, variance_flagged, notifikasi ke accounting & staff_keuangan."""
    db = FakeDB(dewi_cmt_payments=[{"id": "pay", "payment_code": "PAY-CMT-4", "source_receipt_id": "r2",
                                    "subtotal": 480000.0, "total_pcs": 40,
                                    "breakdown": [{"line_id": "l2", "qty_actual": 40, "cmt_rate_per_pcs": 12000}]}],
                cmt_receipt_lines=[{**L2, "qty_actual": 39}], cmt_short_shipments=[])
    pay = run(sm.flag_cmt_payment_variance(db, "r2", reason="koreksi 40→39", event_type="koreksi_hasil_qc", qty=-1))
    assert pay["subtotal"] == 480000.0 and pay["variance_flagged"] and pay["needs_finance_review"]
    assert (pay["overbilled_pcs"], pay["overbilled_amount"], pay["variance_unresolved_qty"]) == (1, 12000.0, 1)
    assert _quiet and set(_quiet[-1]["target_roles"]) == {"accounting", "staff_keuangan"}


def test_kiriman_susulan_tidak_menagih_melebihi_produksi(monkeypatch):
    """p.md No.33: produksi 10, tagihan pertama 10 pcs (150.000) lalu dikoreksi 10→8, vendor
    kirim 2 pcs susulan ⇒ tagihan kedua 0 pcs (Σ tetap 150.000, bukan 180.000), ditandai."""
    from routes import production_maklon_bridge as br
    import utils.counters as uc
    import routes.dewi_maklon_finance as fin

    async def gen(db, coll, field, prefix, width=4, **kw):
        return f"{prefix}00002"

    async def post(db, doc, user):
        raise AssertionError("tagihan 0 tidak boleh diposting")

    async def log(*a, **k):
        return None
    monkeypatch.setattr(uc, "gen_prefixed_number", gen)
    monkeypatch.setattr(fin, "post_cmt_ap_invoice", post)
    monkeypatch.setattr(br, "log_activity", log)
    db = FakeDB(
        cmt_receipts=[{"id": "rx", "po_id": "po-i", "receipt_code": "CMT-RCV-2", "status": "completed_qc",
                       "total_shipped_by_cmt": 2}],
        cmt_receipt_lines=[{"id": "lx", "receipt_id": "rx", "po_item_id": "poi-i", "qty_actual": 2, "reject_qty": 0}],
        po_items=[{"id": "poi-i", "po_id": "po-i", "qty": 10, "cmt_price_snapshot": 15000}],
        production_pos=[{"id": "po-i", "business_type": "internal"}],
        production_jobs=[{"id": "j", "shipment_type": "NORMAL", "vendor_id": "v"}],
        production_job_items=[{"id": "ji", "job_id": "j", "po_item_id": "poi-i", "produced_qty": 10}],
        dewi_cmt_payments=[{"id": "p1", "po_id": "po-i", "status": "posted", "subtotal": 150000.0,
                            "breakdown": [{"po_item_id": "poi-i", "qty_actual": 10}]}],
        vendor_partners=[], dewi_cmt_partners=[], cmt_short_shipments=[], buyer_shipments=[],
        buyer_shipment_items=[], buyer_short_records=[], dewi_cmt_permak=[])
    res = run(br.mature_ap_from_cmt_receipt(db, "rx", {"id": "u", "name": "uji"}))
    pay2 = next(p for p in db["dewi_cmt_payments"].docs if p["id"] == res["payment_id"])
    assert res["amount"] == 0 and pay2["capped_pcs"] == 2 and pay2["variance_flagged"]
    assert sum(p["subtotal"] for p in db["dewi_cmt_payments"].docs) == 150000.0


# ── Butir 8 — K14: FG maklon milik klien, tanpa lapisan biaya ──
def test_k14_fg_maklon_milik_klien_tanpa_lapisan(monkeypatch):
    from core import stock_service
    from core import fg_cost_layers as fcl
    captured = {}

    async def add(material_id, loc, qty, meta=None, ref=None, actor=None, db=None):
        captured["meta"] = meta
        return {"qty": qty}

    async def loc(db):
        return "loc-fg"

    async def no_layer(*a, **k):
        raise AssertionError("barang klien tidak boleh membentuk lapisan biaya")
    monkeypatch.setattr(stock_service, "add", add)
    monkeypatch.setattr(qled, "resolve_fg_location_id", loc)
    monkeypatch.setattr(fcl, "push_layer", no_layer)
    db = FakeDB(rahaza_materials=[{"id": "fg-k", "owner_type": "client", "owner_client_id": "klien-1"}])
    out = run(qled.post_fg_accepted(db, material_id="fg-k", qty=55, ref={}, meta={"material_code": "KLN-A"}))
    assert captured["meta"]["ownership"] == "klien-1" and captured["meta"]["inventory_category"] == "maklon_fg"
    assert out["cost_layer"] is None and out["client_goods"] == "klien-1"
    # SKU maklon bentrok dengan FG DA: stok tetap baris DA, tetapi TANPA lapisan Rp 0 bergap palsu
    db2 = FakeDB(rahaza_materials=[{"id": "fg-da", "type": "fg"}])
    out2 = run(qled.post_fg_accepted(db2, material_id="fg-da", qty=5, ref={}, skip_cost_layer=True))
    assert captured["meta"]["ownership"] == "cv_da" and out2["cost_layer"] is None


# ── Butir 9 — K16: biaya jahit maklon dari angka nyata ──
def test_k16_margin_maklon_dari_angka_nyata():
    """Tagihan CMT 660.000+480.000+24.000 = 1.164.000, permak 6.000, aksesoris DA 0 (belum MI);
    tagihan klien 100 diterima × 20.000 = 2.000.000 ⇒ margin 830.000 (bukan 800.000 statis)."""
    from routes.production_maklon_bridge import maklon_actual_costs
    items = [{"id": f"b{i}", "shipment_id": "sj-1", "po_item_id": "poi-m", "qty_shipped": q, "qty_received": q}
             for i, q in enumerate((47, 38, 10, 5))] + [
             {"id": "b9", "shipment_id": "sj-2", "po_item_id": "poi-m", "qty_shipped": 0}]
    db = _maklon_db(buyer_items=items, receipts=[R1, R2], lines=[L1, L2],
                    permaks=[{"id": "pm", "po_id": "po-m", "po_item_id": "poi-m", "total_cost": 6000.0,
                              "source": "reject", "permak_type": "permak_sendiri", "qty": 3,
                              "qty_fixed": 3, "status": "selesai_berhasil"}])
    db["dewi_cmt_payments"].docs = [{"po_id": "po-m", "subtotal": s, "total_pcs": p, "status": "posted"}
                                    for s, p in ((660000.0, 55), (480000.0, 40), (24000.0, 2))]
    db["rahaza_material_issues"].docs = []
    db["dewi_maklon_bom"].docs = []
    a = run(maklon_actual_costs(db, "po-m"))
    assert (a["cmt_cost"], a["permak_cost"], a["accessory_cost"]) == (1164000.0, 6000.0, 0.0)
    assert (a["revenue"], a["margin"]) == (2000000.0, 830000.0)


# ── Butir 10 — BOM per warna di pemakai yang tersisa ──
def test_bom_warna_mrp_dan_adapter():
    from routes.rahaza_material_requirements import _find_active_bom
    from routes.production_internal_adapter import _active_bom
    brg = {"id": "bom-brg", "model_id": "m", "size_id": "s", "color": "BURGUNDY", "color_code": "BRG",
           "active": True, "is_active": True, "version": 1, "materials": []}
    crl = {**brg, "id": "bom-crl", "color": "CARAMEL", "color_code": "CRL"}
    db = FakeDB(rahaza_boms=[brg, crl])
    assert run(_find_active_bom(db, "m", "s", "CRL"))["id"] == "bom-crl"
    assert run(_find_active_bom(db, "m", "s"))["id"] == "bom-brg"          # tanpa warna: perilaku lama
    assert run(_active_bom(db, "m", "s", "CRL"))["id"] == "bom-crl"        # kode warna juga cocok


def test_cost_check_dan_biaya_jahit_memakai_warna_varian(monkeypatch):
    from core import fg_cost_layers as fcl
    from core import product_costing as pc
    from routes import production_po_cost_check as cc
    seen = []

    async def batch(db, *, po_item, qty):
        seen.append(pc._BOM_COLOR_HINT.get())
        return {"material_cost": 1.0, "material_source": "bom", "sewing_cost": 1.0, "unit_cost": 2.0, "gaps": []}

    async def auth(request):
        return {"role": "admin"}
    monkeypatch.setattr(fcl, "compute_batch_unit_cost", batch)
    monkeypatch.setattr(cc, "require_auth", auth)
    db = FakeDB(production_pos=[{"id": "po", "po_number": "PO"}],
                po_items=[{"id": "i", "po_id": "po", "qty": 10, "color_code": "CRL", "color": "CARAMEL"}])
    monkeypatch.setattr(cc, "get_db", lambda: db)
    run(cc.po_cost_check("po", object()))
    assert seen == ["CRL"]
    src = inspect.getsource(__import__("routes.production_sewing_cost", fromlist=["x"]))
    assert "bom_color_scope(pc.color_of(it))" in src


# ── Butir 11 — invarian INV-Q1..Q5 ──
def test_invarian_q2_merah_sebelum_hijau_sesudah():
    """S6 sebelum perbaikan: buku repaired 3 (retur 2 hilang) ⇒ INV-Q2 merah; sesudah: hijau."""
    base = dict(_blank := dcap._blank_qty("p"))
    base.update({"has_receipts": True, "produced_main": 100, "ordered": 100, "good_from_cmt": 97,
                 "reworked_ok": 3, "accepted_total": 100, "reject": 5, "repaired": 5, "repaired_da": 3,
                 "repaired_cmt": 2, "arrived": 102, "arrived_fresh": 100, "accepted_initial": 95,
                 "dispatched": 100, "shippable": 0})
    before = {**base, "ledger": {**_blank["ledger"], "declared": 102, "accepted": 100, "reject": 5,
                                 "rework_open": 0, "repaired": 3, "repaired_cmt": 0, "scrap": 0,
                                 "produced_main": 100}}
    after = {**before, "ledger": {**before["ledger"], "repaired_cmt": 2}}
    assert not dcap.evaluate_invariants(before)["INV-Q2"]["ok"]
    inv = dcap.evaluate_invariants(after, [], [])
    assert all(v["ok"] for v in inv.values()), {k: v["detail"] for k, v in inv.items()}


def test_invarian_q3_q4_menangkap_kirim_lebih_dan_terima_lebih():
    q = {**dcap._blank_qty("p"), "has_receipts": True, "accepted_total": 98, "dispatched": 100}
    inv = dcap.evaluate_invariants(q, [{"id": "x", "qty_shipped": 8, "qty_received": 10}], [])
    assert not inv["INV-Q3"]["ok"] and not inv["INV-Q4"]["ok"]


def test_inv_q6_statik_tidak_ada_pembaca_tanpa_saringan():
    """INV-Q6: pembaca "dikirim ke buyer" tidak lagi menjumlah buyer_shipment_items mentah."""
    import routes.production_pos as ppos
    import routes.operations_reports as orep
    src_pos = inspect.getsource(ppos.get_pos) + inspect.getsource(ppos.po_quantity_summary)
    assert "db.buyer_shipment_items" not in src_pos
    src_rep = inspect.getsource(orep.get_report)
    blok = src_rep[src_rep.index("report_type == 'production'"):src_rep.index("report_type == 'financial'")]
    assert "db.buyer_shipment_items" not in blok
