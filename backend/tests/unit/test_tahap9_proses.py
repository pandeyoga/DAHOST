"""Tahap 9 (7 Nov 2026) — layar proses Portal Produksi & Maklon: Terima & QC, Perbaikan, Kirim hasil,
Bahan, Tutup PO (agen "proses").

  1. Keputusan 2 — setiap endpoint layar proses menyaring per portal (`?business_type=`):
     internal = PO ``business_type == 'internal'``; maklon = PO ``business_type != 'internal'``
     (aturan tunggal `core.po_portal_scope`, sama dengan daftar PO).
  2. Bahan › Kebutuhan memakai SATU hitungan: PO internal lewat
     `material_issue_engine.bom_need_for_lines`, PO maklon lewat rencana PO (`po_accessories`).
  3. Keputusan 11 — kalkulator AQL bisa dibuka dari Terima & QC (uji impor berkas frontend).
Data uji fiktif (UJI-T9-proses), tanpa data klien.
"""
import asyncio
import copy
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ERP = ROOT / "frontend" / "src" / "components" / "erp"
ADMIN = {"id": "u1", "name": "Admin Uji", "role": "admin"}


def run(c):
    return asyncio.run(c)


class Req:
    """Request palsu: query_params + headers + state (FakeRequest bawaan tidak punya query_params)."""

    def __init__(self, params=None, body=None):
        self.query_params = dict(params or {})
        self.headers = {}
        self._b = body or {}

        class _S:
            pass
        self.state = _S()

    async def json(self):
        return copy.deepcopy(self._b)


async def _admin(*_a, **_k):
    return ADMIN


def _pos():
    return [
        {"id": "po-int", "po_number": "UJI-T9-proses-INT", "business_type": "internal", "status": "In Production"},
        {"id": "po-mkl", "po_number": "UJI-T9-proses-MKL", "business_type": "maklon", "status": "In Production",
         "customer_name": "Klien Uji"},
    ]


# ══════════════════════════════════════════════════════════════════════════════
# 0 · aturan tunggal saringan portal
# ══════════════════════════════════════════════════════════════════════════════
def test_aturan_saringan_portal():
    from core import po_portal_scope as ps
    db = FakeDB()
    db.production_pos.docs = _pos() + [{"id": "po-tanpa", "po_number": "UJI-T9-proses-X"}]
    assert run(ps.portal_po_ids(db, "internal")) == {"po-int"}
    assert run(ps.portal_po_ids(db, "maklon")) == {"po-mkl", "po-tanpa"}      # sama dengan daftar PO maklon
    assert run(ps.portal_po_ids(db, "")) is None and run(ps.portal_po_ids(db, "gudang")) is None
    ids = {"po-int"}
    assert ps.in_portal({"po_id": "po-int"}, ids, "internal")
    assert not ps.in_portal({"po_id": "po-mkl"}, ids, "internal")
    # dokumen tanpa PO: jenis dokumennya sendiri, tanpa jenis = internal
    assert ps.in_portal({"po_id": ""}, ids, "internal")
    assert not ps.in_portal({"po_id": "", "business_type": "maklon"}, ids, "internal")
    assert ps.in_portal({"po_id": None, "business_type": "maklon"}, {"po-mkl"}, "maklon")
    assert ps.in_portal({"po_id": "po-mkl"}, None, None)                     # tanpa saringan = semua
    # filter Mongo setara dengan versi baris
    coll = FakeDB().x
    coll.docs = [{"id": "a", "po_id": "po-int"}, {"id": "b", "po_id": "po-mkl"}, {"id": "c", "po_id": ""},
                 {"id": "d", "business_type": "maklon"}]
    got = {d["id"] for d in run(coll.find(ps.portal_query(ids, "internal")).to_list(None))}
    assert got == {"a", "c"}
    got = {d["id"] for d in run(coll.find(ps.portal_query({"po-mkl"}, "maklon")).to_list(None))}
    assert got == {"b", "d"}
    q = ps.merge_query({"$or": [{"x": 1}]}, ps.portal_query(ids, "internal"))
    assert "$and" in q and q["$or"] == [{"x": 1}]


# ══════════════════════════════════════════════════════════════════════════════
# 1 · Terima & QC — penerimaan, antrean ditolak, selisih kirim
# ══════════════════════════════════════════════════════════════════════════════
def _packing_env(monkeypatch):
    import routes.dewi_cmt_packing as pk
    db = FakeDB()
    db.production_pos.docs = _pos()
    db.cmt_receipts.docs = [
        {"id": "r-int", "receipt_code": "UJI-T9-RC-INT", "po_id": "po-int", "cmt_name": "CMT Uji", "status": "on_qc",
         "created_at": "2026-11-07T01:00:00"},
        {"id": "r-mkl", "receipt_code": "UJI-T9-RC-MKL", "po_id": "po-mkl", "cmt_name": "CMT Uji", "status": "on_qc",
         "created_at": "2026-11-07T02:00:00"},
    ]
    db.cmt_receipt_lines.docs = [
        {"id": "l-int", "receipt_id": "r-int", "sku_code": "SKU-INT", "qty_shipped_by_cmt": 10, "qty_actual": 8,
         "reject_qty": 2, "created_at": "2026-11-07T01:00:00"},
        {"id": "l-mkl", "receipt_id": "r-mkl", "sku_code": "SKU-MKL", "qty_shipped_by_cmt": 10, "qty_actual": 7,
         "reject_qty": 3, "created_at": "2026-11-07T02:00:00"},
    ]
    db.cmt_short_shipments.docs = [
        {"id": "s-int", "short_number": "UJI-T9-SEL-INT", "po_id": "po-int", "qty_short": 4, "status": "open",
         "created_at": "2026-11-07T01:00:00"},
        {"id": "s-mkl", "short_number": "UJI-T9-SEL-MKL", "po_id": "po-mkl", "qty_short": 5, "status": "open",
         "created_at": "2026-11-07T02:00:00"},
    ]
    monkeypatch.setattr(pk, "require_auth", _admin)
    monkeypatch.setattr(pk, "get_db", lambda: db)
    return pk, db


def test_terima_qc_daftar_penerimaan_per_portal(monkeypatch):
    pk, _ = _packing_env(monkeypatch)
    codes = lambda rows: {r["receipt_code"] for r in rows}  # noqa: E731
    assert codes(run(pk.list_receipts(Req({"business_type": "internal"})))) == {"UJI-T9-RC-INT"}
    assert codes(run(pk.list_receipts(Req({"business_type": "maklon"})))) == {"UJI-T9-RC-MKL"}
    assert codes(run(pk.list_receipts(Req()))) == {"UJI-T9-RC-INT", "UJI-T9-RC-MKL"}     # tanpa portal = semua
    # saringan status tetap bekerja bersama saringan portal
    assert codes(run(pk.list_receipts(Req({"business_type": "maklon", "status": "on_qc"})))) == {"UJI-T9-RC-MKL"}


def test_terima_qc_antrean_ditolak_per_portal(monkeypatch):
    pk, _ = _packing_env(monkeypatch)
    out = run(pk.cmt_reject_queue(Req({"business_type": "internal"})))
    assert [r["sku"] for r in out["items"]] == ["SKU-INT"] and out["total_qty_undecided"] == 2
    out = run(pk.cmt_reject_queue(Req({"business_type": "maklon"})))
    assert [r["sku"] for r in out["items"]] == ["SKU-MKL"] and out["total_qty_undecided"] == 3
    assert run(pk.cmt_reject_queue(Req()))["total"] == 2


def test_terima_qc_selisih_kirim_per_portal(monkeypatch):
    pk, _ = _packing_env(monkeypatch)
    out = run(pk.list_short_shipments(Req({"business_type": "maklon", "status": "open"})))
    assert [s["short_number"] for s in out["items"]] == ["UJI-T9-SEL-MKL"]
    assert (out["total"], out["total_qty_open"]) == (1, 5)
    out = run(pk.list_short_shipments(Req({"business_type": "internal", "status": "open"})))
    assert [s["short_number"] for s in out["items"]] == ["UJI-T9-SEL-INT"] and out["total_qty_open"] == 4
    assert run(pk.list_short_shipments(Req({"status": "open"})))["total"] == 2


def test_terima_qc_ringkasan_menerima_saringan_portal():
    """Ringkasan memakai agregasi Mongo (tidak didukung Mongo palsu) — dijaga lewat sumbernya: setiap
    hitungan & tahap $match melewati `_with_scope`, dan antrean ditolaknya versi per portal."""
    import inspect
    import routes.dewi_cmt_packing as pk
    src = inspect.getsource(pk.receipt_summary)
    assert 'request.query_params.get("business_type")' in src
    assert src.count("_with_scope(scope") >= 7
    assert "_reject_queue_in_portal(db, _bt" in src
    assert pk._with_scope({}, {"a": 1}) == {"a": 1}
    assert pk._with_scope({"$or": []}, {"a": 1}) == {"$and": [{"$or": []}, {"a": 1}]}


# ══════════════════════════════════════════════════════════════════════════════
# 2 · Perbaikan (permak) — daftar, ringkasan, pilihan PO
# ══════════════════════════════════════════════════════════════════════════════
def _permak_env(monkeypatch):
    import routes.dewi_cmt_permak as pm
    db = FakeDB()
    db.production_pos.docs = _pos()
    db.dewi_cmt_permak.docs = [
        {"id": "p-int", "permak_number": "UJI-T9-PMK-INT", "po_id": "po-int", "qty": 2, "status": "open",
         "total_cost": 1000, "created_at": "2026-11-07T01:00:00"},
        {"id": "p-mkl", "permak_number": "UJI-T9-PMK-MKL", "po_id": "po-mkl", "qty": 3, "status": "in_progress",
         "total_cost": 3000, "created_at": "2026-11-07T02:00:00"},
    ]
    monkeypatch.setattr(pm, "require_auth", _admin)
    monkeypatch.setattr(pm, "get_db", lambda: db)
    return pm


def _list_permak(pm, **kw):
    base = dict(po_id=None, po_item_id=None, status=None, source=None, q=None, page=1, limit=100, business_type=None)
    base.update(kw)
    return run(pm.list_permak(Req(), **base))


def test_permak_daftar_dan_ringkasan_per_portal(monkeypatch):
    pm = _permak_env(monkeypatch)
    nums = lambda out: [r["permak_number"] for r in out["items"]]  # noqa: E731
    assert nums(_list_permak(pm, business_type="internal")) == ["UJI-T9-PMK-INT"]
    assert nums(_list_permak(pm, business_type="maklon")) == ["UJI-T9-PMK-MKL"]
    assert len(nums(_list_permak(pm))) == 2
    # pencarian (`$or`) dan saringan portal (`$or`) digabung, tidak saling menimpa
    assert nums(_list_permak(pm, business_type="maklon", q="UJI-T9")) == ["UJI-T9-PMK-MKL"]
    assert _list_permak(pm, business_type="internal", q="MKL")["items"] == []
    s = run(pm.permak_summary(Req(), business_type="maklon"))
    assert (s["total_records"], s["in_progress"], s["open"], s["total_cost"]) == (1, 1, 0, 3000.0)
    s = run(pm.permak_summary(Req(), business_type="internal"))
    assert (s["total_records"], s["open"], s["qty_open"]) == (1, 1, 2)


def test_permak_layar_mengirim_jenis_portal_ke_pilihan_po():
    src = (ERP / "CMTPermakModule.jsx").read_text(encoding="utf-8")
    assert "/dewi/cmt-permak/po-options${portalQuery(businessType)}" in src
    assert "/dewi/cmt-permak/summary${portalQuery(businessType)}" in src
    assert "engine/Modal" not in src and "engine/ConfirmDialog" not in src


# ══════════════════════════════════════════════════════════════════════════════
# 3 · Kirim hasil — kekurangan kirim & barang belum sampai
# ══════════════════════════════════════════════════════════════════════════════
def _buyer_env(monkeypatch):
    import routes.buyer_shipment as bs
    db = FakeDB()
    db.production_pos.docs = _pos()
    db.buyer_short_records.docs = [
        {"id": "b-int", "short_number": "UJI-T9-BYR-INT", "po_id": "po-int", "qty_short": 1, "status": "open",
         "created_at": "2026-11-07T01:00:00"},
        {"id": "b-mkl", "short_number": "UJI-T9-BYR-MKL", "po_id": "po-mkl", "qty_short": 6, "status": "open",
         "created_at": "2026-11-07T02:00:00"},
    ]
    monkeypatch.setattr(bs, "require_auth", _admin)
    monkeypatch.setattr(bs, "get_db", lambda: db)
    return bs


def test_kirim_hasil_kekurangan_kirim_per_portal(monkeypatch):
    bs = _buyer_env(monkeypatch)
    import core.dispatch_capacity as dcap

    async def outstanding(db, **kw):
        return [{"po_id": "po-int", "po_number": "UJI-T9-proses-INT", "buyer": "", "ordered": 10, "dispatched": 2, "shippable": 3},
                {"po_id": "po-mkl", "po_number": "UJI-T9-proses-MKL", "buyer": "Klien Uji", "ordered": 20, "dispatched": 5, "shippable": 4}]
    monkeypatch.setattr(dcap, "outstanding", outstanding)
    out = run(bs.buyer_dispatch_outstanding(Req({"business_type": "maklon"})))
    assert [r["po_id"] for r in out["items"]] == ["po-mkl"]
    assert out["totals"] == {"ordered": 20, "dispatched": 5, "shippable": 4, "items": 1}
    assert out["buyers"] == ["Klien Uji"]
    out = run(bs.buyer_dispatch_outstanding(Req({"business_type": "internal"})))
    assert [r["po_id"] for r in out["items"]] == ["po-int"]
    assert len(run(bs.buyer_dispatch_outstanding(Req()))["items"]) == 2


def test_kirim_hasil_belum_sampai_per_portal(monkeypatch):
    bs = _buyer_env(monkeypatch)
    out = run(bs.list_buyer_shorts(Req({"business_type": "maklon", "status": "open"})))
    assert [s["short_number"] for s in out["items"]] == ["UJI-T9-BYR-MKL"] and out["total_qty_open"] == 6
    out = run(bs.list_buyer_shorts(Req({"business_type": "internal", "status": "open"})))
    assert [s["short_number"] for s in out["items"]] == ["UJI-T9-BYR-INT"] and out["total_qty_open"] == 1
    assert run(bs.list_buyer_shorts(Req({"status": "open"})))["total"] == 2


def test_kirim_hasil_layar_menyaring_semua_tampilan():
    src = (ERP / "engine" / "BuyerShipmentModule.jsx").read_text(encoding="utf-8")
    for path in ("/buyer-shipments${portalQuery(businessType)}", "/buyer-shorts${portalQuery(businessType",
                 "/buyer-dispatch-outstanding${portalQuery(businessType", "/production-pos${portalQuery(businessType)}",
                 "/prod/cmt-receipts${portalQuery(businessType"):
        assert path in src, path
    assert "engine/Modal" not in src and "from './Modal'" not in src and "from './DataTable'" not in src


# ══════════════════════════════════════════════════════════════════════════════
# 4 · Bahan › Retur — daftar, sumber MI, ringkasan
# ══════════════════════════════════════════════════════════════════════════════
def _retur_env(monkeypatch):
    import routes.production_material_returns as pmr
    db = FakeDB()
    db.production_pos.docs = _pos()
    db.rahaza_material_issues.docs = [
        {"id": "mi-int", "mi_number": "UJI-T9-MI-INT", "production_po_id": "po-int", "status": "issued",
         "items": [{"material_id": "m1", "qty_issued": 5}], "issued_at": "2026-11-07T01:00:00"},
        {"id": "mi-mkl", "mi_number": "UJI-T9-MI-MKL", "production_po_id": "po-mkl", "business_type": "maklon",
         "status": "issued", "items": [{"material_id": "m2", "qty_issued": 4}], "issued_at": "2026-11-07T02:00:00"},
    ]
    db.production_material_returns.docs = [
        {"id": 1, "ref_no": "UJI-T9-RET-INT", "material_issue_id": "mi-int", "status": "submitted", "created_at": "1"},
        {"id": 2, "ref_no": "UJI-T9-RET-MKL", "material_issue_id": "mi-mkl", "status": "submitted", "created_at": "2"},
        {"id": 3, "ref_no": "UJI-T9-RET-WO", "material_issue_id": "", "status": "received", "created_at": "3"},
    ]
    monkeypatch.setattr(pmr, "require_auth", _admin)
    monkeypatch.setattr(pmr, "get_db", lambda: db)
    return pmr


def test_retur_material_per_portal(monkeypatch):
    pmr = _retur_env(monkeypatch)
    refs = lambda out: {r["ref_no"] for r in out["data"]}  # noqa: E731
    lst = lambda bt: run(pmr.list_returns(Req(), status=None, work_order_id=None, limit=50, skip=0, business_type=bt))  # noqa: E731
    assert refs(lst("internal")) == {"UJI-T9-RET-INT", "UJI-T9-RET-WO"}      # retur lantai produksi lama = internal
    assert refs(lst("maklon")) == {"UJI-T9-RET-MKL"}
    assert refs(lst(None)) == {"UJI-T9-RET-INT", "UJI-T9-RET-MKL", "UJI-T9-RET-WO"}   # Portal Gudang: semua
    src = run(pmr.list_return_sources(Req(), q="", limit=30, business_type="maklon"))
    assert [s["mi_number"] for s in src["data"]] == ["UJI-T9-MI-MKL"]
    src = run(pmr.list_return_sources(Req(), q="UJI", limit=30, business_type="internal"))
    assert [s["mi_number"] for s in src["data"]] == ["UJI-T9-MI-INT"]
    s = run(pmr.returns_summary(Req(), business_type="maklon"))["data"]
    assert (s["submitted"], s["received"]) == (1, 0)
    s = run(pmr.returns_summary(Req(), business_type="internal"))["data"]
    assert (s["submitted"], s["received"]) == (1, 1)


def test_retur_baru_menyimpan_jenis_po_asal(monkeypatch):
    pmr = _retur_env(monkeypatch)
    db = pmr.get_db()
    assert run(pmr._po_business_type_of_mi(db, db.rahaza_material_issues.docs[1])) == "maklon"
    assert run(pmr._po_business_type_of_mi(db, db.rahaza_material_issues.docs[0])) == "internal"
    assert run(pmr._po_business_type_of_mi(db, {"id": "x"})) == "internal"


# ══════════════════════════════════════════════════════════════════════════════
# 5 · Bahan › Kebutuhan — SATU hitungan (internal: BOM bersama; maklon: rencana PO)
# ══════════════════════════════════════════════════════════════════════════════
def _need_env(monkeypatch):
    import core.accessory_procurement as ap
    import core.material_issue_engine as mie
    import routes.rahaza_material_requirements as mr
    db = FakeDB()
    db.production_pos.docs = _pos()
    db.po_items.docs = [{"id": "pi-int", "po_id": "po-int", "qty": 10, "model_id": "MOD", "size_id": "S"},
                        {"id": "pi-mkl", "po_id": "po-mkl", "qty": 20}]
    db.rahaza_materials.docs = [{"id": "m-pot", "code": "POT-UJI", "name": "Potongan uji", "unit": "pcs", "unit_cost": 5000.0},
                                {"id": "m-kcg", "code": "KCG-UJI", "name": "Kancing uji", "unit": "pcs", "unit_cost": 100.0}]
    db.rahaza_material_stock.docs = [{"material_id": "m-kcg", "location_id": "L1", "qty": 30.0}]
    db.rahaza_material_issues.docs = [{"id": "mi1", "production_po_id": "po-int", "status": "issued",
                                       "items": [{"material_id": "m-kcg", "qty_issued": 15.0, "qty_returned": 0}]}]
    calls = []

    async def bom_need(db_, lines):
        calls.append(("bom", lines))
        need = {
            # `kind` = bidang tambahan dari agen kirim (pemisahan potongan/aksesoris) — harus ditoleransi
            "POT-UJI": {"name": "Potongan uji", "unit": "pcs", "type": "accessory", "kind": "potongan", "qty": 10.0},
            "KCG-UJI": {"name": "Kancing uji", "unit": "pcs", "type": "accessory", "qty": 50.0},
            # tanpa `kind` (mesin lama): potongan dikenali dari master/kode potongan (core.cut_panel_master)
            "CUT-UJI-M": {"name": "Potongan uji tanpa master", "unit": "pcs", "type": "accessory", "qty": 10.0},
        }
        return need, ["catatan BOM uji"], 10

    async def plan(db_, po):
        calls.append(("plan", po["id"]))
        return {"rows": [{"material_id": "m-kcg", "material_code": "KCG-UJI", "material_name": "Kancing uji", "unit": "pcs",
                          "qty_needed": 40.0, "issued": 10.0, "remaining": 30.0, "available": 30.0, "shortage": 0.0,
                          "da_owned": True, "unit_cost": 100.0, "status": "ok"},
                         {"material_id": None, "material_code": "", "material_name": "Label klien", "unit": "pcs",
                          "qty_needed": 20.0, "issued": 0, "remaining": 20.0, "available": 0, "shortage": 0,
                          "da_owned": False, "unit_cost": 0, "status": "client"}],
                "summary": {}}
    monkeypatch.setattr(mie, "bom_need_for_lines", bom_need)
    monkeypatch.setattr(ap, "po_requirements", plan)
    monkeypatch.setattr(mr, "require_auth", _admin)
    monkeypatch.setattr(mr, "get_db", lambda: db)
    return mr, db, calls


def test_kebutuhan_internal_memakai_hitungan_bom_bersama(monkeypatch):
    mr, db, calls = _need_env(monkeypatch)
    out = run(mr.material_need_for_po("po-int", Req()))
    assert calls == [("bom", [{"po_item_id": "pi-int", "qty": 10}])]          # SATU hitungan, dari baris PO
    assert out["source"] == "bom" and out["po"]["business_type"] == "internal"
    rows = {r["code"]: r for r in out["rows"]}
    assert rows["POT-UJI"]["kind_label"] == "Kain potongan" and out["rows"][0]["code"] == "POT-UJI"  # potongan di atas
    k = rows["KCG-UJI"]
    assert (k["qty_required"], k["issued"], k["remaining"], k["available"], k["shortage"], k["status"]) == \
        (50.0, 15.0, 35.0, 30.0, 5.0, "shortage")
    assert k["kind_label"] == "Aksesoris" and k["value_estimate"] == 5000.0
    assert rows["POT-UJI"]["shortage"] == 10.0                                  # potongan belum ada stok
    assert rows["CUT-UJI-M"]["kind_label"] == "Kain potongan" and rows["CUT-UJI-M"]["status"] == "unlinked"
    assert out["notes"] == ["catatan BOM uji"] and out["totals"]["shortage_lines"] == 2


def test_kebutuhan_maklon_memakai_rencana_po(monkeypatch):
    mr, db, calls = _need_env(monkeypatch)
    out = run(mr.material_need_for_po("po-mkl", Req()))
    assert calls == [("plan", "po-mkl")]                                       # BOM internal TIDAK dipakai
    assert out["source"] == "rencana_po" and out["po"]["business_type"] == "maklon"
    by = {r["name"]: r for r in out["rows"]}
    assert (by["Kancing uji"]["qty_required"], by["Kancing uji"]["remaining"], by["Kancing uji"]["status"]) == (40.0, 30.0, "ok")
    assert by["Label klien"]["kind_label"] == "Disediakan klien" and by["Label klien"]["shortage"] is None
    assert out["totals"]["client_lines"] == 1 and out["po"]["total_qty"] == 20


def test_kebutuhan_post_lama_dengan_po_lewat_hitungan_yang_sama(monkeypatch):
    mr, db, calls = _need_env(monkeypatch)
    out = run(mr.aggregate_material_requirements(Req(body={"po_id": "po-int", "include_cost": False})))
    assert calls and calls[0][0] == "bom"
    row = {r["code"]: r for r in out["aggregated"]}["KCG-UJI"]
    assert (row["total_required"], row["issued"], row["remaining_required"], row["shortfall"]) == (50.0, 15.0, 35.0, 5.0)
    import inspect
    src = inspect.getsource(mr.po_material_need)
    assert "bom_need_for_lines" in src and "qty_base_of" not in src          # tidak ada rumus BOM × qty kedua


def test_kebutuhan_po_tidak_ada_404(monkeypatch):
    import pytest
    from fastapi import HTTPException
    mr, _db, _c = _need_env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(mr.material_need_for_po("tidak-ada", Req()))
    assert e.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 6 · Layar: AQL di Terima & QC, hub Bahan terdaftar, cetakan standar
# ══════════════════════════════════════════════════════════════════════════════
def test_aql_bisa_dibuka_dari_terima_qc():
    src = (ERP / "engine" / "DAReceiveFromCMTModule.jsx").read_text(encoding="utf-8")
    assert re.search(r"import AqlSamplingTool from './AqlSamplingTool'", src)
    assert "Hitung sampel AQL" in src and "<AqlSamplingTool" in src
    assert "receipt-aql-open" in src and "receipt-aql-panel" in src
    tool = (ERP / "engine" / "AqlSamplingTool.jsx").read_text(encoding="utf-8")
    assert "/rahaza/aql/calculate" in tool                                     # rumus di server, bukan di layar
    old = (ERP / "RahazaAQLCalculatorModule.jsx").read_text(encoding="utf-8")
    assert "AqlSamplingTool" in old and "/rahaza/aql/calculate" not in old     # tautan lama = komponen yang sama


def test_hub_bahan_terdaftar_dan_menggantikan_layar_lama():
    reg = (ERP / "moduleRegistry.js").read_text(encoding="utf-8")
    assert "// Tahap 9 (proses)" in reg
    assert re.search(r"'bahan-produksi':\s+lazyRetry\(\(\) => import\('\./bahan/BahanHub'\)\)", reg)
    hub = (ERP / "bahan" / "BahanHub.jsx").read_text(encoding="utf-8")
    assert "label: 'Kebutuhan'" in hub and "label: 'Retur'" in hub
    old = (ERP / "RahazaMaterialRequirementsModule.jsx").read_text(encoding="utf-8")
    assert "export { default } from './bahan/KebutuhanBahan'" in old
    keb = (ERP / "bahan" / "KebutuhanBahan.jsx").read_text(encoding="utf-8")
    assert "/rahaza/material-requirements/po/" in keb and "portalQuery(businessType)" in keb
    ret = (ERP / "RahazaMaterialReturnModule.jsx").read_text(encoding="utf-8")
    assert "portalQuery(businessType" in ret


SCREENS = ["engine/DAReceiveFromCMTModule.jsx", "CMTPermakModule.jsx", "engine/BuyerShipmentModule.jsx",
           "bahan/KebutuhanBahan.jsx", "RahazaMaterialReturnModule.jsx", "engine/POClosureModule.jsx",
           "RahazaAQLCalculatorModule.jsx"]


def test_layar_proses_memakai_cetakan_standar():
    for rel in SCREENS:
        src = (ERP / rel).read_text(encoding="utf-8")
        assert "PageLayout" in src, rel
        for bad in ("<" + "select", "<table", "<h1", "<h2", "window.confirm", "alert(", "p-6", "py-12", "mt-8"):
            assert bad not in src, f"{rel}: {bad}"
        imports = " | ".join(ln for ln in src.splitlines() if ln.startswith("import "))
        # popup lama (engine/Modal, engine/ConfirmDialog, DataTable mesin) tidak dipakai lagi
        assert not re.search(r"import (Modal|ConfirmDialog|DataTable) from", imports), rel
