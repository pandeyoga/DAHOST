"""Uji unit HERMETIK integrasi tahap 3 (2026-11-02) — sisa paket gudang, opname & scan keluar,
dan keputusan barcode owner (butir 1–15).

Angka harapan DIHITUNG TANGAN:
  * Retur Material (butir 3): MI keluar K 120, sudah diretur 20, retur lain submitted 80 → sisa 20.
  * HPP (butir 4): MI keluar 120 kg @ 50.000, diretur 20 → pemakaian 100 kg = 5.000.000 (dulu 6.000.000).
  * Hangtag (butir 12): SKU 19 karakter → Code128 11×(19+3)+2 = 244 modul + quiet 2×10 = 264 modul;
    kotak 68 mm / 264 = 0,2576 mm ≥ 0,25 → X = 0,25 mm (2 titik @203 dpi).
  * Kode bin (butir 13): GD-L1/ZN-FG/RK-01, 4×6 → `L1FG-RK01-S01-P01` = 17 karakter (≤ 18).

Jalankan:  cd /app/backend && python -m pytest tests/unit/test_s3_integrasi.py -q
"""
import asyncio
import copy
import json
import os
import re
import sys

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
from core import label_render as lr  # noqa: E402
from core import scan_resolver as sr  # noqa: E402

SA = {"id": "u-sa", "name": "Super", "email": "sa@x", "role": "superadmin"}
FE = os.path.join(ROOT, "frontend", "src", "components", "erp")
SKU19 = "DA-2101-MHG-ALLSIZE"


def run(coro):
    return asyncio.run(coro)


def fe(rel):
    with open(os.path.join(FE, rel), encoding="utf-8") as f:
        return f.read()


class DB(fm.FakeDB):
    """FakeDB + `list_collection_names` (dipakai skrip yang memindai semua koleksi)."""

    async def list_collection_names(self):
        return sorted(self._cols)


class Req:
    def __init__(self, body=None):
        self._b = body or {}

        class _S:
            pass
        self.state = _S()

    async def json(self):
        return copy.deepcopy(self._b)


async def _sa(*_a, **_k):
    return SA


async def _noop(*_a, **_k):
    return None


# ═══════════════════ butir 1 & 6: katalog modul + registry FE ═══════════════════
def test_01_06_katalog_modul_baru_dan_registry_fe():
    from data import module_catalog as mc
    assert mc.match_module("/api/rahaza/purchase-returns/x/send")["id"] == "proc_purchase_returns"
    assert mc.match_module("/api/rahaza/debit-notes/supplier-balances")["id"] == "fin_debit_notes"
    assert mc.match_module("/api/wh/scan-out/scan")["id"] == "wh_scan_out"
    assert mc.MODULE_BY_ID["wh_scan_out"]["portal"] == "warehouse"
    assert mc.MODULE_BY_ID["wh_scan_out"]["menus"] == ["wh-scan-out"]
    assert mc.MODULE_BY_ID["proc_purchase_returns"]["menus"] == ["proc-purchase-returns"]
    assert mc.MODULE_BY_ID["fin_debit_notes"]["menus"] == ["fin-debit-notes"]
    # Karantina (Gudang) membuat RTP & layar Nota Debit (Keuangan) mencatat refund → lintas-portal
    assert set(mc.MODULE_BY_ID["proc_purchase_returns"]["also_portals"]) == {"warehouse", "finance"}
    assert "prod-material-returns" in mc.MODULE_BY_ID["prod_material_req"]["menus"]
    assert "warehouse" in mc.MODULE_BY_ID["prod_material_req"]["also_portals"]
    # aksi: tutup lembar = approve; scan = create
    assert mc.detect_action("POST", "/api/wh/scan-out/sheets/s1/close", mc.MODULE_BY_ID["wh_scan_out"]) == "approve"
    assert mc.detect_action("POST", "/api/wh/scan-out/scan", mc.MODULE_BY_ID["wh_scan_out"]) == "create"
    reg = fe("moduleRegistry.js")
    for mid, comp in (("proc-purchase-returns", "PurchaseReturnModule"), ("fin-debit-notes", "DebitNoteModule"),
                      ("wh-scan-out", "WHScanOutModule"), ("prod-material-returns", "RahazaMaterialReturnModule"),
                      ("prod-buyer-returns", "EngineReturnModule")):
        assert re.search(rf"'{mid}':\s+{comp},", reg), mid
    assert "import('./procurement/PurchaseReturnModule')" in reg and "import('./finance/DebitNoteModule')" in reg
    nav = fe("portal-shell/portalNav.js")
    # menu yang dulu NAV-GHOST kini punya layar; tiap id menu yang tampil ada di registry
    for mid in re.findall(r"\{ id: '([a-z0-9-]+)'", nav):
        assert f"'{mid}':" in reg, f"menu {mid} tanpa layar"


# ═══════════════════════ butir 2: faktur manual → peringatan GR ═══════════════════
def test_02_faktur_manual_kembalikan_peringatan_tagihan_dari_gr(monkeypatch):
    import routes.rahaza_finance as rf
    db = fm.FakeDB()
    db.warehouse_receiving.docs.append({"id": "GR9", "receipt_number": "GR-9", "status": "received",
                                        "supplier_name": "PT Uji", "items": [
                                            {"id": "L", "received_qty": 10, "unit_price": 1000}]})

    async def num(*_a, **_k):
        return "AP-0001"
    monkeypatch.setattr(rf, "_require_fin", _sa)
    monkeypatch.setattr(rf, "get_db", lambda: db)
    monkeypatch.setattr(rf, "_gen_number", num)
    out = run(rf.create_ap(Req({"vendor_name": "pt uji", "items": [{"description": "x", "qty": 1, "price": 500}]})))
    assert out["invoice_number"] == "AP-0001" and db.rahaza_ap_invoices.docs     # faktur tetap tersimpan
    assert "tagihan dari gr" in out["warning"].lower() and out["uninvoiced_grs"][0]["receipt_number"] == "GR-9"
    out2 = run(rf.create_ap(Req({"vendor_name": "PT Lain", "items": [{"description": "x", "qty": 1, "price": 1}]})))
    assert out2["warning"] is None


# ═══════════════════════ butir 3: layar Retur Material ═══════════════════════════
def _pmr(monkeypatch, db):
    import routes.production_material_returns as pmr
    monkeypatch.setattr(pmr, "require_auth", _sa)
    monkeypatch.setattr(pmr, "get_db", lambda: db)
    monkeypatch.setattr(pmr, "log_activity", _noop)

    async def gen(*_a, **_k):
        return "PMR/2026/11/0001"

    async def nxt(*_a, **_k):
        return 99
    monkeypatch.setattr(pmr, "gen_prefixed_number", gen)
    monkeypatch.setattr(pmr, "next_counter", nxt)
    return pmr


def _mi_db():
    db = fm.FakeDB()
    db.rahaza_materials.docs += [{"id": "K", "code": "KN-1", "name": "Kain", "unit": "kg"},
                                 {"id": "A", "code": "A-LBL", "name": "Label", "unit": "pcs"}]
    db.rahaza_material_issues.docs += [
        {"id": "MI1", "mi_number": "MI-001", "status": "issued", "vendor_shipment_id": "S1",
         "vendor_shipment_number": "SHP-1", "vendor_name": "CMT A", "return_status": "partial",
         "items": [{"material_id": "K", "qty_issued": 120, "qty_returned": 20},
                   {"material_id": "A", "qty_issued": 50}]},
        {"id": "MI2", "mi_number": "MI-002", "status": "issued", "return_status": "full",
         "items": [{"material_id": "K", "qty_issued": 5, "qty_returned": 5}]},
        {"id": "MI3", "mi_number": "MI-003", "status": "pending_approval", "items": []}]
    db.production_material_returns.docs.append(
        {"id": 8, "status": "submitted", "material_issue_id": "MI1", "items": [{"material_id": "K", "qty_returned": 80}]})
    return db


def test_03_retur_material_sumber_sisa_dan_penjaga_qty(monkeypatch):
    db = _mi_db()
    pmr = _pmr(monkeypatch, db)
    src = run(pmr.list_return_sources(Req(), q="", limit=30))["data"]
    assert [s["mi_number"] for s in src] == ["MI-001"]                  # MI penuh/belum keluar tidak tampil
    one = run(pmr.get_return_source(Req(), vendor_shipment_id="S1"))["data"]
    lines = {ln["material_code"]: ln for ln in one["lines"]}
    assert lines["KN-1"]["returnable"] == 20 and lines["KN-1"]["qty_returned"] == 20   # 120 − 20 − 80
    assert lines["A-LBL"]["returnable"] == 50 and one["mi_number"] == "MI-001"
    body = pmr.ReturnCreateModel(material_issue_id="MI1", items=[
        pmr.ReturnItem(material_id="K", material_code="KN-1", qty_returned=25)])
    with pytest.raises(HTTPException) as e:
        run(pmr.create_return(Req(), body))
    assert e.value.status_code == 400 and "sisa 20" in e.value.detail
    ok = pmr.ReturnCreateModel(material_issue_id="MI1", items=[
        pmr.ReturnItem(material_id="K", material_code="KN-1", qty_returned=20)])
    doc = run(pmr.create_return(Req(), ok))["data"]
    assert doc["mi_number"] == "MI-001" and doc["status"] == "draft"
    assert pmr.qty_errors([{"material_id": "K", "qty_returned": 1}], {"K": 0.0}) == ["'K': retur 1 > sisa 0"]


def test_03b_retur_material_layar_dan_teks_hapus_surat_jalan():
    screen = fe("RahazaMaterialReturnModule.jsx")
    for frag in ("/api/production/material-returns", "/sources", "/source?", "/receive", "location_id",
                 "lokasi penerima (wajib)", "deepLinkParams"):
        assert frag in screen, frag
    # Tahap 9: rincian kiriman (hapus + arahan Retur Material) pindah ke engine/kirim/KirimanDetail.jsx
    vs = fe("engine/kirim/KirimanDetail.jsx")
    assert "tidak bisa dihapus — kembalikan dulu lewat Retur Material" in vs
    assert "onNavigate('prod-material-returns'" in vs


# ═══════════════════════ butir 4: HPP dikurangi qty retur MI ═══════════════════════
def test_04_hpp_pemakaian_bahan_dikurangi_qty_returned(monkeypatch):
    import routes.rahaza_hpp as hpp
    from core import wo_reader
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "K", "name": "Kain", "type": "fabric", "unit": "kg", "unit_cost": 50000})
    db.rahaza_material_issues.docs.append({"id": "MI1", "job_id": "J1", "status": "issued", "items": [
        {"material_id": "K", "qty_issued": 120, "qty_returned": 20}]})

    async def wo(_db, _id):
        return {"id": "J1", "qty": 100, "wo_number": "WO-1"}
    monkeypatch.setattr(wo_reader, "get_wo", wo)
    out = run(hpp._compute_hpp(db, "J1"))
    assert out["material_cost"] == 5000000 and out["material_breakdown"][0]["qty"] == 100
    assert hpp.mi_item_net_qty({"qty_issued": 5, "qty_returned": 7}) == 0.0
    assert hpp.mi_item_net_qty({"qty_required": 3}) == 3.0


# ═══════════════════════ butir 5: kunci penomoran RTP/ND/RVL/SKP/PMR ═══════════════
def test_05_katalog_penomoran_dokumen_baru():
    from data.doc_number_registry import REGISTRY_BY_KEY as K
    from utils.counters import validate_format
    expect = {"rahaza_purchase_returns.rtp_number": "RTP-", "rahaza_debit_notes.dn_number": "ND-",
              "rahaza_inventory_revaluations.reval_number": "RVL-", "wh_scan_out_sheets.number": "SKP-",
              "production_material_returns.ref_no": "PMR/"}
    for key, head in expect.items():
        e = K[key]
        assert e["auto_only"] and e["alasan_otomatis"]
        assert validate_format(e["default_format"], e.get("tokens"),
                               require_seq=e.get("sequenced", True)).startswith(head)
    assert K["wh_scan_out_sheets.number"]["sequenced"] is False
    # kode memakai koleksi/field yang sama dengan entri katalog
    from core import accessory_valuation as av, purchase_returns as pr, scan_out as so
    assert (pr.RTP_COLL, pr.DN_COLL, av.REVALUATION_COLL, so.SHEETS) == (
        "rahaza_purchase_returns", "rahaza_debit_notes", "rahaza_inventory_revaluations", "wh_scan_out_sheets")
    # G12: semua seri nomor literal di kode terdaftar (pengecualian tinggal pinjaman legacy)
    pola = re.compile(r"gen_prefixed_number\(\s*db\s*,\s*['\"]([a-z_0-9]+)['\"]\s*,\s*['\"]([a-z_0-9]+)['\"]")
    reg = {(e.get("collection") or k.split(".")[0], e.get("field") or k.split(".", 1)[1]) for k, e in K.items()}
    missing = set()
    for dirpath, _d, files in os.walk(BACKEND):
        if any(x in dirpath for x in ("_archive", "tests", "migrations", "scripts")):
            continue
        for f in files:
            if f.endswith(".py"):
                with open(os.path.join(dirpath, f), encoding="utf-8", errors="ignore") as fh:
                    missing |= {m for m in pola.findall(fh.read()) if m not in reg}
    assert missing <= {("rahaza_employee_loans", "loan_number")}, missing


def test_05b_nomor_lembar_scan_keluar_ikut_format_owner():
    from core import scan_out as so
    db = fm.FakeDB()
    assert run(so.sheet_number_for(db, "2026-11-02", "gd-l1", 1)) == "SKP-20261102-GD-L1"
    db.doc_number_configs.docs.append({"key": so.SHEET_NUMBER_KEY, "active": True,
                                       "format": "OUT/{YY}{MM}{DD}/{LOKASI}"})
    assert run(so.sheet_number_for(db, "2026-11-02", "GD-L1", 2)) == "OUT/261102/GD-L1-2"


# ═══════════════════════ butir 7: ledger scan membawa ref.effective_at ═════════════
def test_07_scan_out_ledger_membawa_jam_kejadian(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from core import opname_engine as eng
    from core import scan_out as so
    from core import stock_service
    t_scan = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
    t_void = t_scan + timedelta(hours=2)
    line = {"id": "L1", "sheet_id": "S", "qty": 2, "material_id": "fg1", "location_id": "LOC",
            "scanned_at": t_scan, "voided_at": t_void}
    assert so.effective_at_of(line, so.REF_SCAN) == t_scan
    assert so.effective_at_of(line, so.REF_CANCEL) == t_scan
    assert so.effective_at_of(line, so.REF_SCAN_VOID) == t_void
    seen = []

    async def issue(mid, loc, qty, **kw):
        seen.append(kw["ref"])
        return {"qty": 0}
    monkeypatch.setattr(stock_service, "issue", issue)
    run(so._stock_step(fm.FakeDB(), line, ref_type=so.REF_SCAN, out=True, actor={"id": "u"}))
    assert seen[0]["effective_at"] == t_scan and seen[0]["type"] == so.REF_SCAN
    # mesin opname: scan TERJADI 10:00 tetapi baru tercatat 12:00, baris dihitung 11:00 → ikut dihitung
    row = {"created_at": t_scan + timedelta(hours=9), "delta": -2, "ref": seen[0]}
    snap = t_scan - timedelta(hours=1)
    assert eng.system_qty_at(10, [row], snap, t_scan + timedelta(hours=1)) == (8.0, -2.0)
    assert eng.system_qty_at(10, [row], snap, t_scan - timedelta(minutes=1)) == (10.0, 0.0)


# ═══════════════════════ butir 8: zona ditautkan ke lokasi ═════════════════════════
def test_08_zona_tertaut_lokasi_dibaca_mesin_opname(monkeypatch):
    import routes.wms_structure as ws
    from core import opname_engine as eng
    db = fm.FakeDB()
    db.wh_buildings.docs.append({"id": "B1", "code": "GDT", "name": "Gudang", "active": True})
    db.rahaza_locations.docs += [{"id": "L1", "code": "GD-L1", "name": "Gudang L1", "active": True},
                                 {"id": "L2", "code": "GD-L2", "name": "Gudang L2", "active": True}]
    monkeypatch.setattr(ws, "require_auth", _sa)
    monkeypatch.setattr(ws, "get_db", lambda: db)
    monkeypatch.setattr(ws, "log_activity", _noop)
    z = run(ws.create_zone(ws.ZoneIn(building_id="B1", code="fg", name="Zona FG", location_id="L1"), Req()))["zone"]
    assert z["location_id"] == "L1" and z["location_code"] == "GD-L1"
    assert run(eng.location_scope(db, "L1"))["location_ids"] == ["L1", z["id"]]
    with pytest.raises(HTTPException):
        run(ws.create_zone(ws.ZoneIn(building_id="B1", code="X", name="X", location_id="NOPE"), Req()))
    run(ws.update_zone(z["id"], ws.ZoneIn(building_id="B1", code="FG", name="Zona FG", location_id="L2"), Req()))
    assert run(eng.location_scope(db, "L1"))["location_ids"] == ["L1"]
    run(ws.update_zone(z["id"], ws.ZoneIn(building_id="B1", code="FG", name="Zona FG 2"), Req()))   # None = tetap
    lst = run(ws.list_zones(Req(), building_id="B1"))
    assert lst[0]["location_code"] == "GD-L2" and lst[0]["name"] == "Zona FG 2"
    run(ws.update_zone(z["id"], ws.ZoneIn(building_id="B1", code="FG", name="Zona FG 2", location_id=""), Req()))
    assert db.wh_zones.docs[0]["location_id"] is None
    assert "zone-location-select" in fe("WMSModule.jsx") and "/api/rahaza/locations" in fe("WMSModule.jsx")


# ═══════════════════════ butir 9: Audit Trail membaca sesi K9 ══════════════════════
def test_09_audit_trail_membaca_sesi_opname_k9(monkeypatch):
    from datetime import datetime
    import routes.wms_audit as wa
    db = fm.FakeDB()
    db.rahaza_fg_movements.docs.append({"source": "opname_adjustment", "direction": "adjust_out", "qty": 1,
                                        "created_by": "lama@x", "timestamp": datetime(2026, 10, 1)})
    db.wh_opname3_sessions.docs += [
        {"id": "S1", "engine": "k9", "status": "approved", "session_no": "OPN-202611-0001",
         "location_code": "GD-L1", "approved_at": datetime(2026, 11, 2, 5), "approved_by_name": "SPV Gudang",
         "result": {"lines": [{"material_code": "KN-1", "variance_qty": -3, "variance_value": -150000,
                               "system_qty": 13, "counted_qty": 10},
                              {"material_code": "A-1", "variance_qty": 2, "system_qty": 0, "counted_qty": 2},
                              {"material_code": "Z", "variance_qty": 0}]}},
        {"id": "S0", "status": "approved", "session_no": "OPN-LAMA"},          # arsip lama → bukan sumber K9
        {"id": "S2", "engine": "k9", "status": "submitted", "session_no": "OPN-X"}]
    monkeypatch.setattr(wa, "require_auth", _sa)
    monkeypatch.setattr(wa, "get_db", lambda: db)
    out = run(wa.list_adjustments(Req(), limit=100, skip=0))
    assert out["total"] == 3
    assert [(r.get("session_ref"), r["direction"], r["qty"]) for r in out["items"][:2]] == [
        ("OPN-202611-0001", "adjust_out", 3.0), ("OPN-202611-0001", "adjust_in", 2.0)]
    assert out["items"][2]["created_by"] == "lama@x"

    class _Agg:          # agregasi sumber LAMA (1 baris adjust_out 1 oleh lama@x) — FakeDB tanpa aggregate
        def __init__(self, rows):
            self.rows = rows

        async def to_list(self, _n):
            return self.rows

    def agg(pipeline):
        key = pipeline[1]["$group"]["_id"]
        return _Agg({"$direction": [{"_id": "adjust_out", "count": 1, "total_qty": 1.0}],
                     "$created_by": [{"_id": "lama@x", "count": 1, "surplus_qty": 0, "shortage_qty": 1.0,
                                      "last_activity": datetime(2026, 10, 1)}]}.get(key, []))
    db.rahaza_fg_movements.aggregate = agg
    st = run(wa.adjustment_stats(Req()))
    assert (st["surplus_qty"], st["shortage_qty"], st["total_adjustments"]) == (2.0, 4.0, 3)
    assert any(o["operator"] == "SPV Gudang" and o["count"] == 2 for o in st["by_operator"])
    # saringan posisi/rak → selisih K9 (per lokasi) tidak ikut
    assert run(wa.list_adjustments(Req(), position_barcode="X", limit=100, skip=0))["total"] == 0
    assert run(wa.list_adjustments(Req(), direction="adjust_in", limit=100, skip=0))["total"] == 1


# ═══════════════════════ butir 10: kartu stok menampilkan mutasi opname ═════════════
def test_10_kartu_stok_bernilai_tetap_menampilkan_opname(monkeypatch):
    import routes.dewi_accessories_valuation as dav
    assert "opname" in dav._VALUED_TYPES
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "A", "type": "accessory", "code": "A-1"})
    db.rahaza_material_movements.docs.append({"id": "mv1", "material_id": "A", "movement_type": "opname",
                                              "type": "opname", "material_code": "A-1", "qty": -2,
                                              "qty_signed": -2, "unit_cost": 1500, "gl_je_number": "JE-9"})
    monkeypatch.setattr(dav, "require_auth", _sa)
    monkeypatch.setattr(dav, "get_db", lambda: db)
    rows = run(dav.get_valued_movements(Req(), acc_id=None, limit=100))
    assert rows[0]["movement_type"] == "opname" and rows[0]["material_code"] == "A-1"
    assert rows[0]["value"] == 3000 and rows[0]["je_number"] == "JE-9"
    assert "opname: { label: 'Opname'" in fe("accessory/AccessoryValuationLedger.jsx")
    assert "m.type === 'opname'" in fe("RahazaStockModule.jsx")


# ═══════════════════════ butir 11: skrip rapikan kode bahan ════════════════════════
def _tidy_db():
    db = DB()
    base = {"type": "fabric", "name": "RAYON TWILL POLOS", "unit": "yard", "unit_cost": 20000.0,
            "category_id": "cat-fab", "active": True}
    db.rahaza_materials.docs += [
        {"id": "m-cnd2", "code": "KN-CND-DST 2", "type": "fabric", "name": "Condru", "unit": "kg", "color": "Dusty 2"},
        {"id": "m-htm3", "code": "KN-RTW-HTM 3", **base, "color": "HITAM 3"},
        {"id": "m-rtw", "code": "KN-RTW-", **base, "color": "BEIGE"}]
    db.bom_lines.docs.append({"id": "b1", "material_code": "KN-CND-DST 2", "material_id": "m-cnd2",
                              "meta": {"code": "kn-cnd-dst 2"}})
    db.rahaza_purchase_orders.docs.append({"id": "po1", "material_id": "m-rtw", "material_code": "KN-RTW-"})
    db.activity_logs.docs.append({"id": "log1", "material_code": "KN-RTW-HTM 3"})
    return db


def test_11_tidy_material_codes_rename_alias_dan_gabung_hanya_bila_terbukti(tmp_path):
    import tidy_material_codes as tm
    assert tm.find_refs({"a": [{"x": " kn-rtw- "}], "id": "ID1"}, {"KN-RTW-": "L"}, {"ID1": "L"}) == [
        ("a.0.x", " kn-rtw- ", "kode", "L"), ("id", "ID1", "id", "L")]
    ok, why = tm.merge_verdict({"name": "A", "color": "BEIGE"}, {"name": "a", "color": "HITAM 3"})
    assert not ok and "color" in why[0]
    assert tm.merge_verdict({"name": "A", "color": ""}, {"name": "A", "color": "X"}) == (True, [])
    db = _tidy_db()
    p = run(tm.plan(db))
    assert [r.get("skip") for r in p["renames"]] == [None, None]
    m = p["merges"][0]
    assert not m["akan_digabung"] and any("color bertentangan" in a for a in m["alasan"])    # BEIGE ≠ HITAM 3
    ring = p["ringkasan_rujukan"]
    assert ring["rename:KN-CND-DST 2"]["bom_lines"] == {"material_code (kode)": 1, "meta.code (kode)": 1,
                                                         "material_id (id)": 1}
    assert ring["merge:KN-RTW-"]["rahaza_purchase_orders"]["material_id (id)"] == 1
    assert "activity_logs" in ring["rename:KN-RTW-HTM 3"]
    before = copy.deepcopy(db.rahaza_materials.docs)
    done = run(tm.apply(db, p, tmp_path))
    assert done["master"] == 2 and done["digabung"] == 0
    mats = {d["id"]: d for d in db.rahaza_materials.docs}
    assert mats["m-cnd2"]["code"] == "KN-CND-DST-2" and mats["m-cnd2"]["code_aliases"] == ["KN-CND-DST 2"]
    assert mats["m-htm3"]["code"] == "KN-RTW-HTM-3" and mats["m-rtw"]["code"] == "KN-RTW-"     # tidak digabung
    bom = db.bom_lines.docs[0]
    assert (bom["material_code"], bom["meta"]["code"], bom["material_id"]) == ("KN-CND-DST-2", "KN-CND-DST-2", "m-cnd2")
    assert db.rahaza_purchase_orders.docs[0]["material_code"] == "KN-RTW-"                     # rujukan gabung tetap
    assert db.activity_logs.docs[0]["material_code"] == "KN-RTW-HTM 3"                         # log tidak diubah
    backup = json.loads(open(done["backup"], encoding="utf-8").read())
    assert {m_["code"] for m_ in backup["materials"]} >= {m_["code"] for m_ in before}
    assert "bom_lines" in backup["documents"]
    # label lama tetap terbaca lewat alias
    res = run(sr.resolve(db, "KN-CND-DST 2", expect=("material",)))
    assert res["kode"] == "KN-CND-DST-2" and res["via"] == "kode_lama"
    # dijalankan ulang = tidak ada yang diubah lagi
    assert [r.get("skip") for r in run(tm.plan(db))["renames"]] == [
        "kode lama tidak ditemukan (sudah dirapikan?)"] * 2


# ═══════════════════════ butir 12 & 14: hangtag & QR = SKU polos ════════════════════
class _Rec:
    drawn: list = []
    qr: list = []


def _record(monkeypatch):
    _Rec.drawn, _Rec.qr = [], []
    real = lr._RLCode128

    class Rec(real):
        def drawOn(self, canvas, x, y, *a, **k):
            _Rec.drawn.append((self.value, self.barWidth))
            return super().drawOn(canvas, x, y, *a, **k)
    monkeypatch.setattr(lr, "_RLCode128", Rec)
    real_qr = lr.qr_png

    def qr(payload):
        _Rec.qr.append(payload)
        return real_qr(payload)
    monkeypatch.setattr(lr, "qr_png", qr)


def test_12_14_hangtag_70x40_sku19_x025_dan_qr_sku_polos(monkeypatch):
    _record(monkeypatch)
    assert lr.label_size("fg_hangtag") == (70.0, 40.0)
    fg = {"id": "fg1", "code": SKU19, "name": "Aisar", "color_name": "MAHOGANY", "size_code": "ALLSIZE"}
    pdf = lr.single_label_pdf("fg_hangtag", fg).getvalue()
    assert pdf.startswith(b"%PDF")
    value, bw = _Rec.drawn[0]
    assert value == SKU19 and abs(bw / lr.mm - 0.25) < 1e-9 and lr.code128_modules(SKU19) == 244
    assert _Rec.qr == [SKU19]                                       # QR = SKU polos
    lr.single_label_pdf("fg", fg)
    assert _Rec.qr[-1] == SKU19 and not _Rec.qr[-1].startswith("{")
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "fg1", "code": SKU19, "type": "fg", "name": "Aisar"})
    assert run(sr.resolve(db, SKU19))["id"] == "fg1"
    legacy = json.dumps({"type": "fg", "sku": SKU19, "name": "Aisar", "at": "2026-01-01"})
    assert run(sr.resolve(db, legacy))["via"] == "qr_sku"           # QR JSON lama tetap diterima


def test_12b_buat_barcode_pilihan_ukuran_hangtag(monkeypatch):
    import routes.wms_barcode as wb
    db = fm.FakeDB()
    db.rahaza_materials.docs.append({"id": "fg1", "code": SKU19, "type": "fg", "name": "Aisar"})
    kinds = []

    def grid(kind, docs, **kw):
        kinds.append((kind, len(docs)))
        import io
        return io.BytesIO(b"%PDF-uji")

    async def gen(*_a, **_k):
        return "BC-1"
    monkeypatch.setattr(wb, "require_auth", _sa)
    monkeypatch.setattr(wb, "get_db", lambda: db)
    monkeypatch.setattr(wb, "log_activity", _noop)
    monkeypatch.setattr(wb, "gen_prefixed_number", gen)
    monkeypatch.setattr(wb.lr, "grid_labels_pdf", grid)
    run(wb.barcode_batch_pdf(wb.BarcodeBatchIn(kind="fg", size="hangtag", rows=[{"code": SKU19, "copies": 3}]), Req()))
    assert kinds == [("fg_hangtag", 3)] and db.wh_barcode_print_jobs.docs[0]["size"] == "hangtag"
    with pytest.raises(HTTPException):
        run(wb.barcode_batch_pdf(wb.BarcodeBatchIn(kind="fg", size="a3", rows=[{"code": SKU19}]), Req()))
    assert "barcode-fg-size" in fe("WMSBarcodeModule.jsx") and "size: kind === 'fg' ? fgSize" in fe("WMSBarcodeModule.jsx")


# ═══════════════════════ butir 13: kode bin ≤ 18 + alias + migrasi ══════════════════
def test_13_kode_bin_pendek_unik_dan_label_lama_tetap_dikenali(monkeypatch, tmp_path):
    import routes.wms_structure as ws
    assert ws.bin_prefix_candidates("GDT", "FG", "R01", 4, 6)[0] == "GDT-FG-R01"           # format lama muat
    cands = ws.bin_prefix_candidates("GD-L1", "ZN-FG", "RK-01", 4, 6)
    assert cands[0] == "L1FG-RK01" and ws.bin_code(cands[0], 1, 1) == "L1FG-RK01-S01-P01"
    for b, z, r, sh, sl in (("GUDANGUTAMA", "ZONABAHANBAKU", "RAKNOMOR123", 50, 100), ("A", "B", "C", 1, 1)):
        for c in ws.bin_prefix_candidates(b, z, r, sh, sl):
            assert len(ws.bin_code(c, sh, sl)) <= ws.BIN_CODE_MAX, c
    db = DB()
    monkeypatch.setattr(ws, "require_auth", _sa)
    monkeypatch.setattr(ws, "get_db", lambda: db)
    monkeypatch.setattr(ws, "log_activity", _noop)
    db.wh_zones.docs.append({"id": "Z1", "building_id": "B1", "code": "ZN-FG", "name": "FG", "active": True})
    db.wh_buildings.docs.append({"id": "B1", "code": "GD-L1", "name": "Gudang", "active": True})
    r1 = run(ws.create_rack(ws.RackIn(zone_id="Z1", code="RK-01", name="Rak 1", num_shelves=2, slots_per_shelf=2),
                            Req()))["rack"]
    r2 = run(ws.create_rack(ws.RackIn(zone_id="Z1", code="RK01", name="Rak 1b", num_shelves=1, slots_per_shelf=1),
                            Req()))["rack"]
    assert r1["bin_prefix"] == "L1FG-RK01" and r2["bin_prefix"] != r1["bin_prefix"]          # bentrok → pembeda
    codes = [p["barcode"] for p in db.wh_positions.docs]
    assert len(set(codes)) == len(codes) and max(map(len, codes)) <= 18
    # migrasi kode lama > 18 karakter (dry-run → terapkan) + alias
    import shorten_bin_codes as sb
    db.wh_racks.docs.append({"id": "R9", "zone_id": "Z1", "building_code": "GD-L1", "zone_code": "ZN-FG",
                             "code": "RK-09", "num_shelves": 1, "slots_per_shelf": 1})
    old = "GD-L1-ZN-FG-RK-09-S01-P01"
    db.wh_positions.docs.append({"id": "P9", "rack_id": "R9", "zone_id": "Z1", "shelf_no": 1, "slot_no": 1,
                                 "barcode": old, "rack_code": "RK-09"})
    db.wh_positions.docs.append({"id": "PX", "barcode": "TANPA-RAK-YANG-PANJANG-S01"})
    p = run(sb.plan(db))
    assert p["total_long"] == 2 and p["orphans"][0]["id"] == "PX"
    new = p["racks"][0]["changes"][0]["new"]
    assert new == "L1FG-RK09-S01-P01" and db.wh_positions.docs[-2]["barcode"] == old          # dry-run: belum berubah
    done = run(sb.apply(db, p, tmp_path))
    pos = next(x for x in db.wh_positions.docs if x["id"] == "P9")
    assert done["positions"] == 1 and pos["barcode"] == new and pos["barcode_aliases"] == [old]
    res = run(sr.resolve(db, old.lower(), expect=("bin",)))
    assert res["id"] == "P9" and res["kode"] == new and res["via"] == "barcode_posisi_lama"
    assert run(sr.position_by_barcode(db, new))["id"] == "P9"


# ═══════════════════════ butir 15: label aset = registri induk ═════════════════════
def test_15_label_aset_satu_generator_kode_registri_induk(monkeypatch):
    db = fm.FakeDB()
    db.rahaza_fixed_assets.docs.append({"id": "FA1", "code": "FA-00007", "name": "Mesin Jahit", "category": "mesin"})
    db.dewi_assets.docs += [{"id": "D1", "asset_number": "AST-IT-2026-0001", "name": "Mesin Jahit Juki",
                             "fixed_asset_id": "FA1", "location": "Lantai 2"},
                            {"id": "D2", "asset_number": "AST-IT-2026-0002", "name": "Helm"}]
    doc = run(lr.asset_label_doc(db, asset_id="D1"))
    assert doc["label_code"] == "FA-00007" and doc["name"] == "Mesin Jahit Juki"
    assert run(lr.asset_label_doc(db, fixed_asset_id="FA1"))["operational_id"] == "D1"
    with pytest.raises(lr.LabelCodeError):
        run(lr.asset_label_doc(db, asset_id="D2"))                     # belum tertaut → tidak ada kode karangan
    _record(monkeypatch)
    assert lr.single_label_pdf("asset", doc).getvalue().startswith(b"%PDF")
    assert _Rec.drawn[0][0] == "FA-00007" and _Rec.qr == ["FA-00007"]
    assert lr.single_label_pdf("asset_small", doc).getvalue().startswith(b"%PDF")
    # endpoint Portal Aset & Keuangan memakai fungsi yang sama
    from routes.asset import scan_label as sl
    resp = run(sl.asset_label_response(db, asset_id="D1", template="a4"))
    assert resp.media_type == "application/pdf" and resp.body.startswith(b"%PDF")
    with pytest.raises(HTTPException) as e:
        run(sl.asset_label_response(db, asset_id="D2"))
    assert e.value.status_code == 400
    import routes.rahaza_fixed_assets as rfa
    import inspect
    assert "asset_label_response" in inspect.getsource(rfa.fixed_asset_label_pdf)
    # resolver: kode registri → aset operasional tertaut; nomor Portal Aset lama tetap dikenali
    r = run(sr.resolve(db, "fa-00007"))
    assert (r["tipe"], r["id"], r["kode"], r["via"]) == ("aset", "D1", "FA-00007", "kode_aset_tetap")
    r2 = run(sr.resolve(db, "AST-IT-2026-0001", expect=("aset",)))
    assert r2["kode"] == "FA-00007" and r2["via"] == "nomor_aset"
    assert run(sr.resolve(db, "AST-IT-2026-0002", expect=("aset",)))["kode"] == "AST-IT-2026-0002"
    # generator kembar dihapus/dialihkan (410)
    monkeypatch.setattr(sl, "require_auth", _sa)
    for fn in (sl.get_asset_barcode, sl.get_asset_qrcode):
        with pytest.raises(HTTPException) as e:
            run(fn("D1", Req()))
        assert e.value.status_code == 410
    import routes.dewi_assets as da
    monkeypatch.setattr(da, "require_auth", _sa)
    with pytest.raises(HTTPException) as e:
        run(da.print_label("x", Req()))
    assert e.value.status_code == 410
    with pytest.raises(HTTPException) as e:
        run(da.print_bulk_labels(Req()))
    assert e.value.status_code == 410
    assert "api/dewi/assets/labels/bulk" not in fe("HRAssetModule.jsx")
    assert "/qrcode" not in fe("asset/drawers/AssetDetailDrawer.jsx")
    assert "/fixed-assets/${selected.id}/label-pdf" in fe("FixedAssetsModule.jsx")
