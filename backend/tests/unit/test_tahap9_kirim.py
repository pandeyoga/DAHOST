"""Tahap 9 — Kirim ke CMT, SPP, surat jalan (keputusan owner 7 Nov 2026 no. 3, 4, 10, 12 + aturan cutting/BOM).

  1. Potongan dipisah dari aksesoris (satu definisi `core.kirim_cmt.kind_of`), di hitungan, explode BOM, dan MI.
  2. Kiriman DIBLOKIR bila stok potongan kurang (juga saat "stok boleh minus" ON) dan bila BOM warna tidak ada
     (`_active_bom` tidak lagi jatuh ke BOM warna lain).
  3. Stok potongan diambil dari BEBERAPA lokasi; tiap baris MI membawa `unit_cost_applied`, `kind`, `po_item_id`.
  4. Aksesoris: stok berkurang = qty serah × isi kemasan (satuan dasar); surat jalan mencatat angka yang sama.
  5. Kiriman tambahan/pengganti (permintaan disetujui) MENGURANGI STOK.
  6. Draf MI dobel (GDG-2 / draf massal) dimatikan untuk PO yang dijahit CMT; pembatalan draf lama.
  7. Satuan serah, rencana aksesoris PO (kontrak field), peringatan sampel, SPP maklon.

Data uji fiktif (UJI-T9). Angka hitung tangan ada di tiap uji.
"""
import asyncio
import importlib.util
import os
import sys
import types
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

from _fake_mongo import FakeDB  # noqa: E402
from core import kirim_cmt as kc  # noqa: E402
from core import material_issue_engine as mie  # noqa: E402
from core import satuan_serah as ss  # noqa: E402
from core import stock_service  # noqa: E402

USER = {"id": "u-t9", "name": "Admin UJI-T9", "role": "admin"}


def run(c):
    return asyncio.run(c)


# ── data uji ──────────────────────────────────────────────────────────────────────────────────────────────────────
CUT = {"id": "CUT1", "code": "CUT-UJI-HTM-L", "name": "Potongan UJI Hitam L", "type": "fabric", "unit": "pcs",
       "is_cut_panel": True, "color_code": "HTM", "unit_cost": 20000.0, "active": True}
KCG = {"id": "KCG1", "code": "A-KCG-UJI", "name": "Kancing UJI", "type": "accessory", "unit": "pcs",
       "unit_cost": 100.0, "active": True}
RENDA = {"id": "REN1", "code": "A-REN-UJI", "name": "Renda UJI", "type": "accessory", "unit": "cm", "base_uom": "cm",
         "unit_cost": 10.0, "active": True,
         "uoms": [{"code": "cm", "name": "CM", "factor": 1, "is_base": True},
                  {"code": "roll", "name": "Roll", "factor": 2240}]}
KAIN = {"id": "KAIN1", "code": "KN-UJI", "name": "Kain roll UJI", "type": "fabric", "unit": "kg", "active": True}


def _bom(color="Hitam", code="HTM", extra=()):
    return {"id": f"bom-{code}", "model_id": "m1", "size_id": "s1", "color": color, "color_code": code,
            "is_active": True, "active": True, "materials": [
                {"material_id": "CUT1", "code": CUT["code"], "name": CUT["name"], "qty": 1, "unit": "pcs",
                 "qty_base": 1, "unit_base": "pcs", "is_cut_panel": True, "material_type": "fabric"},
                {"material_id": "KCG1", "code": KCG["code"], "name": KCG["name"], "qty": 5, "unit": "pcs",
                 "qty_base": 5, "unit_base": "pcs"},
                {"material_id": "REN1", "code": RENDA["code"], "name": RENDA["name"], "qty": 315, "unit": "cm",
                 "qty_base": 315, "unit_base": "cm"},
                *extra]}


def _db(*, cut_stock=(("GD-A", 500),), color="Hitam", color_code="HTM", po_extra=None):
    d = FakeDB()
    d.rahaza_materials.docs = [dict(CUT), dict(KCG), dict(RENDA), dict(KAIN)]
    d.rahaza_material_stock.docs = [{"material_id": "CUT1", "location_id": loc, "qty": q} for loc, q in cut_stock] + [
        {"material_id": "KCG1", "location_id": "GD-ACC", "qty": 5000},
        {"material_id": "REN1", "location_id": "GD-ACC", "qty": 100000}]
    d.rahaza_locations.docs = [{"id": "GD-A", "code": "GD-A"}, {"id": "GD-B", "code": "GD-B"},
                               {"id": "GD-ACC", "code": "GD-ACC", "storage_role": "aksesoris"},
                               {"id": "GD-QC", "code": "GD-QC", "storage_role": "karantina"}]
    d.production_pos.docs = [{"id": "PO1", "po_number": "PO-UJI-T9-1", "business_type": "internal", "vendor_id": "v1",
                              "vendor_name": "CMT UJI", "status": "Confirmed", **(po_extra or {})}]
    d.po_items.docs = [{"id": "pi1", "po_id": "PO1", "qty": 100, "model_id": "m1", "size_id": "s1",
                        "sku": "UJI-HTM-L", "size": "L", "color": color, "color_code": color_code}]
    d.rahaza_boms.docs = [_bom()]
    d.vendor_partners.docs = [{"id": "v1", "name": "CMT UJI", "active": True}]
    return d


@pytest.fixture
def env(monkeypatch):
    """stock_service palsu yang benar-benar mengubah baris stok FakeDB (supaya 'stok berkurang' bisa dibaca)."""
    from core import negative_stock
    import routes.rahaza_inventory_shared as ris
    import routes.rahaza_posting as rp
    st = types.SimpleNamespace(db=None, neg=False, issues=[], posts=[])

    async def issue(mid, loc, qty, *, allow_negative=False, db=None, **kw):
        row = next((r for r in db.rahaza_material_stock.docs
                    if r["material_id"] == mid and r["location_id"] == loc), None)
        have = float((row or {}).get("qty") or 0)
        if have + 1e-9 < qty and not allow_negative:
            raise stock_service.InsufficientStock(mid, loc, qty, have)
        if row is None:
            row = {"material_id": mid, "location_id": loc, "qty": 0.0}
            db.rahaza_material_stock.docs.append(row)
        row["qty"] = round(have - qty, 6)
        st.issues.append((mid, loc, round(qty, 6)))
        return row

    async def add(mid, loc, qty, *, db=None, **kw):
        row = next(r for r in db.rahaza_material_stock.docs if r["material_id"] == mid and r["location_id"] == loc)
        row["qty"] = round(float(row["qty"]) + qty, 6)
        return row

    async def allowed(_db):
        return st.neg

    async def post(_db, mi, user):
        st.posts.append(mi["id"])
        return {"ok": True, "je_number": f"JE-UJI-{len(st.posts)}"}

    seq = {"mi": 0, "sj": 0}

    async def mi_no(_db, *a, **k):
        seq["mi"] += 1
        return f"MI-UJI-T9-{seq['mi']:03d}"

    async def sj_no(_db, key, **k):
        seq["sj"] += 1
        return f"SHP-UJI-T9-{seq['sj']:03d}"
    from core import doc_number_policy as dnp
    monkeypatch.setattr(stock_service, "issue", issue)
    monkeypatch.setattr(stock_service, "add", add)
    monkeypatch.setattr(negative_stock, "allowed", allowed)
    monkeypatch.setattr(rp, "post_inventory_issue", post)
    monkeypatch.setattr(ris, "_gen_mi_number", mi_no)
    monkeypatch.setattr(dnp, "issue_number", sj_no)

    async def _no_release(*_a, **_k):
        return True
    monkeypatch.setattr(dnp, "release_number", _no_release)
    return st


def _stock(d, mid):
    return round(sum(float(r["qty"]) for r in d.rahaza_material_stock.docs if r["material_id"] == mid), 6)


def _ship(d, sid="SJ1", qty=100, acc=None):
    d.vendor_shipments.docs.append({"id": sid, "shipment_number": sid, "po_id": "PO1", "shipment_type": "NORMAL",
                                    "vendor_id": "v1", "vendor_name": "CMT UJI"})
    items = [{"po_item_id": "pi1", "po_id": "PO1", "qty_sent": qty}]
    d.vendor_shipment_items.docs.append({"shipment_id": sid, **items[0]})
    return run(mie.issue_for_vendor_shipment(d, d.vendor_shipments.docs[-1], items, USER, accessory_input=acc))


# ══════════════════════════════ 1. potongan vs aksesoris ══════════════════════════════
def test_jenis_potongan_vs_aksesoris_satu_definisi():
    assert kc.kind_of(CUT) == "potongan"
    assert kc.kind_of(None, {"code": "CUT-DA-1101-BRG-ALLSIZE"}) == "potongan"           # baris BOM tanpa master
    assert kc.kind_of(KCG) == "aksesoris" and kc.kind_of(RENDA) == "aksesoris"
    assert kc.kind_of(KAIN) == "kiloan"
    assert kc.kind_of({"type": "accessory", "unit": "kg", "code": "A-KRT"}) == "aksesoris"   # karet berkg tetap aksesoris
    assert kc.kind_of({"type": "fabric", "category_code": "CUT_PANEL", "code": "X"}) == "potongan"


def test_hitungan_memisah_potongan_dan_aksesoris(env):
    d = _db()
    d.rahaza_boms.docs = [_bom(extra=[{"material_id": "KAIN1", "code": "KN-UJI", "name": "Kain", "qty": 0.5,
                                        "unit": "kg", "qty_base": 0.5, "unit_base": "kg", "material_type": "fabric"}])]
    # rencana lama (cacat "9 dari 26 baris"): potongan ikut tercatat sebagai aksesoris PO
    d.po_accessories.docs = [{"id": "x", "po_id": "PO1", "accessory_id": "CUT1", "accessory_code": CUT["code"],
                              "qty_needed": 100, "unit": "pcs", "source": "bom_auto"},
                             {"id": "y", "po_id": "PO1", "accessory_id": "KCG1", "accessory_code": KCG["code"],
                              "qty_needed": 500, "unit": "pcs", "source": "bom_auto"}]
    calc = run(kc.compute(d, po_id="PO1", lines=[{"po_item_id": "pi1", "qty": 100}]))
    assert [(p["code"], p["qty"]) for p in calc["potongan"]] == [(CUT["code"], 100.0)]
    assert sorted(a["code"] for a in calc["aksesoris"]) == [KCG["code"], RENDA["code"]]
    assert all(a["code"] != CUT["code"] for a in calc["aksesoris"])
    assert any("potongan" in w for w in calc["warnings"]) and any("kiloan" in w for w in calc["warnings"])
    assert not calc["blocking"]


def test_explode_bom_tidak_menulis_potongan_dan_membawa_kontrak_satuan_serah(env, monkeypatch):
    import routes.production_internal_adapter as pia
    d = _db()
    run(pia.explode_po_accessories_from_bom(d, "PO1"))
    rows = {r["accessory_code"]: r for r in d.po_accessories.docs}
    assert CUT["code"] not in rows and set(rows) == {KCG["code"], RENDA["code"]}
    ren = rows[RENDA["code"]]
    # 315 cm × 100 pcs = 31.500 cm = 14,06 roll → perkiraan dibulatkan ke atas 15 roll; rencana bawaan = perkiraan
    assert (ren["usage_unit"], ren["bom_qty_base"], ren["handover_uom"], ren["handover_factor"]) == ("cm", 31500.0,
                                                                                                    "roll", 2240.0)
    assert (ren["bom_qty_handover"], ren["plan_qty_handover"], ren["source"]) == (15, 15, "bom")
    assert ren["qty_needed"] == 15 * 2240 and ren["bom_origin"] == "bom_auto"
    # user mengubah rencana → dipertahankan saat BOM dihitung ulang (qty PO sama)
    for r in d.po_accessories.docs:
        if r["accessory_code"] == RENDA["code"]:
            r["plan_qty_handover"] = 14
    run(pia.explode_po_accessories_from_bom(d, "PO1"))
    ren2 = next(r for r in d.po_accessories.docs if r["accessory_code"] == RENDA["code"])
    assert ren2["plan_qty_handover"] == 14 and ren2["bom_qty_handover"] == 15 and len(d.po_accessories.docs) == 2


def test_bom_need_for_lines_tidak_menyebut_potongan_aksesoris(env):
    d = _db()
    need, _notes, pcs = run(mie.bom_need_for_lines(d, [{"po_item_id": "pi1", "qty": 10}]))
    assert need[CUT["code"]]["kind"] == "potongan" and need[CUT["code"]]["type"] == "cut_panel"
    assert need[KCG["code"]]["type"] == "accessory" and pcs == 10


# ══════════════════════════════ 2. blokir ══════════════════════════════
def test_potongan_kurang_diblokir_walau_stok_boleh_minus(env):
    env.neg = True                                       # setelan "stok boleh minus" ON
    d = _db(cut_stock=(("GD-A", 40), ("GD-QC", 500)))  # stok karantina tidak dihitung
    with pytest.raises(kc.KirimBlocked) as e:
        _ship(d, qty=100)
    assert "Catat hasil cutting" in str(e.value) and CUT["code"] in str(e.value)
    assert _stock(d, "CUT1") == 540 and env.issues == []                  # tidak ada yang dipotong
    assert all(m["status"] != "issued" for m in d.rahaza_material_issues.docs)


def test_aksesoris_kurang_ikut_setelan_stok_boleh_minus(env):
    d = _db()
    for r in d.rahaza_material_stock.docs:
        if r["material_id"] == "KCG1":
            r["qty"] = 100                               # butuh 500
    env.neg = False
    calc = run(kc.compute(d, po_id="PO1", lines=[{"po_item_id": "pi1", "qty": 100}]))
    assert calc["blocking"] and any(KCG["code"] in b for b in calc["blocking_reasons"])
    env.neg = True
    calc = run(kc.compute(d, po_id="PO1", lines=[{"po_item_id": "pi1", "qty": 100}]))
    kcg = next(a for a in calc["aksesoris"] if a["code"] == KCG["code"])
    assert not calc["blocking"] and kcg["negative"] and "minus" in kcg["problem"]


def test_bom_warna_tidak_ada_diblokir_tidak_memakai_warna_lain(env):
    import routes.production_internal_adapter as pia
    d = _db(color="Merah", color_code="MRH")             # hanya ada BOM warna Hitam
    assert run(pia._active_bom(d, "m1", "s1", "Merah", color_code="MRH")) is None
    calc = run(kc.compute(d, po_id="PO1", lines=[{"po_item_id": "pi1", "qty": 10}]))
    assert calc["blocking"] and "warna Merah" in calc["blocking_reasons"][0] and calc["potongan"] == []
    with pytest.raises(kc.KirimBlocked):
        _ship(d, qty=10)
    # BOM umum (tanpa warna) boleh dipakai; BOM warna yang benar menang
    d.rahaza_boms.docs.append({**_bom(), "id": "bom-umum", "color": "", "color_code": ""})
    assert run(pia._active_bom(d, "m1", "s1", "Merah", color_code="MRH"))["id"] == "bom-umum"
    assert run(pia._active_bom(d, "m1", "s1", "Hitam", color_code="HTM"))["id"] == "bom-HTM"


# ══════════════════════════════ 3. banyak lokasi + kontrak MI ══════════════════════════════
def test_potongan_diambil_dari_beberapa_lokasi_dan_mi_membawa_kontrak(env):
    d = _db(cut_stock=(("GD-A", 60), ("GD-B", 50)))
    res = _ship(d, qty=100)
    mi = next(m for m in d.rahaza_material_issues.docs if m["id"] == res["mi"]["id"])
    pot = [i for i in mi["items"] if i["kind"] == "potongan"]
    assert sorted((i["location_id"], i["qty_issued"]) for i in pot) == [("GD-A", 60.0), ("GD-B", 40.0)]
    assert all(i["po_item_id"] == "pi1" and i["unit_cost_applied"] == 20000.0 for i in pot)
    assert all("unit_cost_applied" in i and i["kind"] in ("potongan", "aksesoris") for i in mi["items"])
    assert (mi["po_id"], mi["shipment_id"], mi["status"]) == ("PO1", "SJ1", "issued")
    assert _stock(d, "CUT1") == 10.0
    assert "cost_target" not in mi                       # PO internal → WIP


# ══════════════════════════════ 4. stok berkurang = qty serah × isi ══════════════════════════════
def test_stok_aksesoris_berkurang_qty_serah_kali_isi_kemasan(env):
    d = _db()
    run(__import__("routes.production_internal_adapter", fromlist=["x"]).explode_po_accessories_from_bom(d, "PO1"))
    before = _stock(d, "REN1")
    calc = run(kc.compute(d, po_id="PO1", lines=[{"po_item_id": "pi1", "qty": 100}]))
    ren = next(a for a in calc["aksesoris"] if a["code"] == RENDA["code"])
    assert ren["estimate_base"] == 31500.0 and ren["estimate_handover"] == 15 and ren["default_handover"] == 15
    assert ren["handover_label"] == "roll isi 2.240 cm"
    # user menyerahkan 14 roll → stok turun 14 × 2.240 = 31.360 cm (bukan 31.500 angka BOM)
    res = _ship(d, qty=100, acc=[{"material_id": "REN1", "qty_handover": 14}])
    assert round(before - _stock(d, "REN1"), 6) == 31360.0
    asi = next(a for a in d.accessory_shipment_items.docs if a["accessory_id"] == "REN1")
    assert (asi["qty_sent"], asi["unit"], asi["qty_base"], asi["unit_label"]) == (14, "roll", 31360.0,
                                                                                  "roll isi 2.240 cm")
    mi_ren = [i for i in res["mi"]["items"] if i["material_id"] == "REN1"]
    assert sum(i["qty_required"] for i in mi_ren) == 31360.0 and mi_ren[0]["qty_handover"] == 14
    # surat jalan & rincian membaca angka yang SAMA dengan stok yang berkurang
    lines = run(kc.shipment_lines(d, d.vendor_shipments.docs[0]))
    ren_sj = next(a for a in lines["aksesoris"] if a["material_id"] == "REN1")
    assert (ren_sj["qty_handover"], ren_sj["qty_base"]) == (14, 31360.0)
    assert [(p["code"], p["qty"]) for p in lines["potongan"]] == [(CUT["code"], 100.0)]


# ══════════════════════════════ 5. kiriman tambahan mengurangi stok ══════════════════════════════
def test_kiriman_tambahan_dari_permintaan_mengurangi_stok(env, monkeypatch):
    import routes.exceptions as exc
    d = _db()
    first = _ship(d, qty=50)
    assert first["mi"]["status"] == "issued"
    cut_before = _stock(d, "CUT1")
    d.material_requests.docs = [{"id": "mr1", "request_number": "REQ-ADD-1-UJI", "request_type": "ADDITIONAL",
                                 "status": "Pending", "original_shipment_id": "SJ1", "po_id": "PO1",
                                 "po_number": "PO-UJI-T9-1", "vendor_id": "v1", "business_type": "internal",
                                 "items": [{"po_item_id": "pi1", "sku": "UJI-HTM-L", "requested_qty": 16}]}]
    out = run(exc._update_material_request_locked(d, "mr1", {"status": "Approved", "admin_notes": "kurang 16",
                                                            "accessory_items": []}, USER))
    assert out["status"] == "Approved" and out["child_shipment_number"] == "SJ1-A1"
    assert cut_before - _stock(d, "CUT1") == 16.0                       # dulu: 0 (stok tidak berkurang)
    child = next(s for s in d.vendor_shipments.docs if s["id"] == out["child_shipment_id"])
    mi = next(m for m in d.rahaza_material_issues.docs if m["vendor_shipment_id"] == child["id"])
    assert mi["status"] == "issued" and [(i["kind"], i["qty_issued"]) for i in mi["items"]] == [("potongan", 16.0)]
    assert out["material_issue_number"] == mi["mi_number"]
    # potongan tidak cukup → permintaan tetap menunggu, tidak ada surat jalan anak
    d.material_requests.docs.append({**d.material_requests.docs[0], "id": "mr2", "status": "Pending",
                                     "items": [{"po_item_id": "pi1", "requested_qty": 9999}]})
    with pytest.raises(HTTPException) as e:
        run(exc._update_material_request_locked(d, "mr2", {"status": "Approved", "accessory_items": []}, USER))
    assert e.value.status_code == 400 and "cutting" in e.value.detail
    assert not any(s.get("material_request_id") == "mr2" for s in d.vendor_shipments.docs)
    assert d.material_requests.docs[1]["status"] == "Pending"


def test_daftar_permintaan_gabungan_disaring_per_portal(env):
    from core import kirim_permintaan as kp
    d = _db()
    d.production_pos.docs.append({"id": "PO2", "po_number": "PO-UJI-T9-MKL", "business_type": "maklon"})
    d.material_requests.docs = [{"id": "mr1", "request_number": "REQ-ADD-1", "request_type": "ADDITIONAL",
                                 "status": "Pending", "business_type": "internal", "items": [], "created_at": "2026-11-07"},
                                {"id": "mr2", "request_number": "REQ-ADD-2", "request_type": "REPLACEMENT",
                                 "status": "Rejected", "business_type": "maklon", "items": [], "created_at": "2026-11-06"}]
    d.dewi_cmt_component_requests.docs = [{"id": "k1", "request_code": "REQ-CMP-1", "po_id": "PO1", "status": "ready",
                                           "origin": "staf", "items": [], "created_at": "2026-11-05"},
                                          {"id": "k2", "request_code": "REQ-CMP-2", "po_id": "PO2", "status": "delivered",
                                           "origin": "vendor_inspection", "items": [], "created_at": "2026-11-04"}]
    internal = run(kp.list_requests(d, business_type="internal"))
    assert [r["number"] for r in internal] == ["REQ-ADD-1", "REQ-CMP-1"]
    assert [r["status"] for r in internal] == ["menunggu", "menunggu"] and internal[1]["sub_status"] == "Siap kirim"
    maklon = run(kp.list_requests(d, business_type="maklon"))
    assert [(r["number"], r["status"], r["source"]) for r in maklon] == [("REQ-ADD-2", "ditolak", "vendor"),
                                                                       ("REQ-CMP-2", "dikirim", "pemeriksaan")]


def test_input_staf_menjadi_kiriman_tambahan_yang_mengurangi_stok(env):
    from core import kirim_permintaan as kp
    d = _db()
    doc = run(kp.create_staff_request(d, {"po_id": "PO1", "lines": [{"po_item_id": "pi1", "qty": 5}],
                                          "materials": [{"material_id": "REN1", "qty": 1, "uom": "roll"}],
                                          "reason": "UJI-T9 potongan rusak"}, USER))
    assert doc["origin"] == "staf" and doc["items"][0]["unit_label"] == "roll isi 2.240 cm"
    cut0, ren0 = _stock(d, "CUT1"), _stock(d, "REN1")
    res = run(kp.approve_component_request(d, {**doc}, USER))
    assert res["shipment_number"] == "SHP-UJI-T9-002"            # 001 = nomor permintaan (penomoran bersama palsu)
    assert (cut0 - _stock(d, "CUT1"), ren0 - _stock(d, "REN1")) == (5.0, 2240.0)
    saved = d.dewi_cmt_component_requests.docs[0]
    assert saved["status"] == "delivered" and saved["material_issue_number"]


# ══════════════════════════════ 6. draf dobel dimatikan ══════════════════════════════
def test_draf_dari_job_dimatikan_untuk_po_yang_dijahit_cmt(env):
    import routes.production_internal_adapter as pia
    d = _db()
    job = {"id": "j1", "po_id": "PO1", "job_number": "JOB-UJI", "vendor_id": "v1"}
    with pytest.raises(HTTPException) as e:
        run(pia.create_mi_draft_from_job(d, job, USER))
    assert e.value.status_code == 400 and "Kirim ke CMT" in e.value.detail
    assert d.rahaza_material_issues.docs == []


def test_draf_massal_melewati_po_yang_dijahit_cmt(env):
    import routes.rahaza_sprint22 as s22
    d = _db()
    assert run(s22._sewn_by_cmt(d, {"po_id": "PO1", "vendor_id": ""})) is True     # PO ber-vendor
    d.production_pos.docs[0]["vendor_id"] = None
    assert run(s22._sewn_by_cmt(d, {"po_id": "PO1"})) is False                     # dikerjakan sendiri
    d.vendor_shipments.docs.append({"id": "S", "po_id": "PO1"})
    assert run(s22._sewn_by_cmt(d, {"po_id": "PO1"})) is True                      # sudah ada kiriman ke CMT


def test_draf_lama_dibatalkan_dan_tidak_bisa_disetujui(env):
    d = _db()
    _ship(d, qty=10)
    d.production_jobs.docs = [{"id": "j1", "po_id": "PO1"}]
    d.rahaza_material_issues.docs += [
        {"id": "D1", "mi_number": "MI-UJI-DRAF", "status": "draft", "job_id": "j1", "production_po_id": "PO1",
         "items": []},
        {"id": "D2", "mi_number": "BMI-UJI", "status": "draft", "job_id": "j1", "work_order_id": "j1",
         "bulk_batch": True, "items": []},
        {"id": "D3", "mi_number": "MI-MANUAL", "status": "draft", "items": []}]   # manual tanpa PO: tidak disentuh
    rows = run(kc.double_drafts(d))
    assert [(r["mi_number"], r["po_number"]) for r in rows] == [("BMI-UJI", "PO-UJI-T9-1"), ("MI-UJI-DRAF", "PO-UJI-T9-1")]
    assert "sudah keluar lewat kiriman" in rows[0]["reason"]
    d1 = next(m for m in d.rahaza_material_issues.docs if m["id"] == "D1")
    with pytest.raises(HTTPException):
        run(kc.assert_not_double(d, d1))
    run(kc.cancel_double_drafts(d, actor="UJI-T9"))
    st = {m["id"]: m["status"] for m in d.rahaza_material_issues.docs}
    assert (st["D1"], st["D2"], st["D3"]) == ("cancelled", "cancelled", "draft")
    assert run(kc.double_drafts(d)) == []                                          # idempoten


def test_migrasi_batal_mi_dobel_memakai_definisi_yang_sama():
    p = BACKEND / "scripts" / "migrations" / "2026_11_07_batal_mi_dobel.py"
    spec = importlib.util.spec_from_file_location("mig_batal", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = p.read_text(encoding="utf-8")
    assert "kirim_cmt.double_drafts" in src and "kirim_cmt.cancel_double_drafts" in src and "--apply" in src


# ══════════════════════════════ 7. satuan serah, rencana PO, sampel, SPP ══════════════════════════════
def test_satuan_serah_dan_laporan_cek():
    assert ss.handover_unit(RENDA)["uom"] == "roll" and ss.handover_unit(RENDA)["status"] == "ok"
    assert ss.handover_unit(KCG)["status"] == "dasar"
    assert ss.handover_unit({"unit": "cm", "code": "X"})["status"] == "tanpa_kemasan"
    gross = {"unit": "pcs", "uoms": [{"code": "pcs", "factor": 1, "is_base": True},
                                     {"code": "gross", "name": "Gross", "factor": 1440}]}
    hu = ss.handover_unit(gross)
    assert (hu["uom"], hu["factor"], hu["status"]) == ("gross", 1440.0, "gross_tidak_baku")
    ganda = {"unit": "pcs", "uoms": [{"code": "pcs", "factor": 1, "is_base": True}, {"code": "pack", "factor": 100},
                                     {"code": "karton", "factor": 1000}]}
    assert ss.handover_unit(ganda)["status"] == "kemasan_ganda" and ss.handover_unit(ganda)["uom"] == "pack"
    assert ss.handover_unit({**ganda, "issue_uom": "karton"})["status"] == "ok"
    assert ss.ceil_units(31500, 2240) == 15 and ss.ceil_units(0, 2240) == 0
    p = BACKEND / "scripts" / "migrations" / "2026_11_07_cek_satuan_serah.py"
    spec = importlib.util.spec_from_file_location("mig_cek", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.rows_from([{**gross, "id": "g", "code": "A-GRS"}, {**RENDA}, {"id": "c", "code": "A-CM", "unit": "cm"}],
                         frozenset({"g"}))
    assert [(r["code"], r["status"], r["dipakai_po"]) for r in rows] == [("A-GRS", "gross_tidak_baku", "ya"),
                                                                          ("A-CM", "tanpa_kemasan", "tidak")]


def test_rencana_tambahan_bersatuan_material_bukan_pcs(env):
    from core import rencana_aksesoris as ra
    import routes.production_internal_adapter as pia
    d = _db()
    run(pia.explode_po_accessories_from_bom(d, "PO1"))
    bom_kcg = next(r for r in d.po_accessories.docs if r["accessory_code"] == KCG["code"])
    out = run(ra.apply_rows(d, "PO1", [
        {"id": bom_kcg["id"], "source": "bom", "accessory_id": "KCG1", "plan_qty_handover": 450},
        {"accessory_id": "REN1", "accessory_name": "Renda", "plan_qty_handover": 2, "unit": "pcs"}]))
    assert out == {"bom_updated": 1, "tambahan_saved": 1, "tambahan_deleted": 0}
    kcg = next(r for r in d.po_accessories.docs if r["id"] == bom_kcg["id"])
    assert (kcg["plan_qty_handover"], kcg["bom_qty_handover"], kcg["bom_qty_base"]) == (450, 500, 500.0)
    tamb = next(r for r in d.po_accessories.docs if r.get("source") == "tambahan")
    assert (tamb["usage_unit"], tamb["handover_uom"], tamb["qty_needed"]) == ("cm", "roll", 4480.0)   # bukan "pcs"
    assert len([r for r in d.po_accessories.docs if r.get("source") == "bom"]) == 2                  # BOM tidak dihapus


def test_peringatan_sampel_maklon_tidak_memblokir(env):
    d = _db(po_extra={"business_type": "maklon"})
    w = run(kc.sample_warning(d, d.production_pos.docs[0]))
    assert w and w["code"] == "belum_ada"
    d.dewi_maklon_samples.docs = [{"id": "s1", "po_id": "PO1", "status": "submitted"}]
    assert run(kc.sample_warning(d, d.production_pos.docs[0]))["code"] == "belum_disetujui"
    d.dewi_maklon_samples.docs.append({"id": "s2", "order_id": "PO1", "status": "approved"})
    assert run(kc.sample_warning(d, d.production_pos.docs[0])) is None
    d.production_pos.docs[0]["business_type"] = "internal"
    assert run(kc.sample_warning(d, d.production_pos.docs[0])) is None


def test_spp_maklon_mencetak_aksesoris_satuan_serah_tanpa_potongan(env):
    d = _db(po_extra={"business_type": "maklon"})
    d.po_items.docs = [{"id": "pm1", "po_id": "PO1", "qty": 100, "sku": "KLN-1"}]   # artikel katalog klien
    d.po_accessories.docs = [{"id": "a", "po_id": "PO1", "accessory_id": "REN1", "accessory_code": RENDA["code"],
                              "ownership": "cv_da_stock", "source": "bom_maklon_auto", "qty_needed": 31500, "unit": "cm"},
                             {"id": "b", "po_id": "PO1", "accessory_name": "Label klien", "ownership": "client_provided",
                              "qty_needed": 100, "unit": "pcs", "source": "bom_maklon_auto"}]
    d.dewi_maklon_bom.docs = [{"po_id": "PO1", "materials": [{"material_name": "Kain klien", "line_type": "bulk",
                                                              "qty_estimated": 120, "unit": "m", "qty_per_pcs": 1.2}]}]
    spp = run(kc.spp_lines(d, d.production_pos.docs[0]))
    assert spp["potongan"] == [] and spp["bulk"][0]["owner"] == "Klien"
    ren = spp["aksesoris"][0]
    assert (ren["handover_label"], ren["qty_handover"], ren["qty_base"]) == ("roll isi 2.240 cm", 15, 33600.0)
    assert [c["accessory_name"] for c in spp["client_accessories"]] == ["Label klien"]


# ── Owner 11 Nov 2026: harga jual aksesoris ke CMT diisi di PO; nota baru terbit saat Kirim ke CMT ─────────────────
def test_harga_jual_cmt_murni():
    f = ss.harga_fields(RENDA, 22400, "roll")                      # 1 roll = 2.240 cm
    assert f == {"harga_jual_cmt": 22400.0, "harga_jual_cmt_uom": "roll", "harga_jual_cmt_dasar": 10.0}
    assert ss.harga_untuk(f, 2240) == 22400.0 and ss.harga_untuk(f, 1) == 10.0
    assert ss.harga_fields(RENDA, "", "roll") == {k: None for k in ss.HARGA_KEYS}
    assert ss.harga_untuk({}, 5) is None


def test_harga_jual_cmt_di_po_ikut_hitung_ulang_bom_dan_mengisi_kirim(env):
    from core import rencana_aksesoris as ra
    import routes.production_internal_adapter as pia
    d = _db()
    run(pia.explode_po_accessories_from_bom(d, "PO1"))
    bom_kcg = next(r for r in d.po_accessories.docs if r["accessory_code"] == KCG["code"])
    out = run(ra.apply_rows(d, "PO1", [
        # harga saja (rencana tidak diubah) — baris BOM tetap diperbarui
        {"id": bom_kcg["id"], "source": "bom", "accessory_id": "KCG1", "harga_jual_cmt": "150"},
        {"accessory_id": "REN1", "accessory_name": "Renda", "plan_qty_handover": 2, "handover_uom": "roll",
         "harga_jual_cmt": 33600}]))
    assert out["bom_updated"] == 1 and out["tambahan_saved"] == 1
    kcg = next(r for r in d.po_accessories.docs if r["id"] == bom_kcg["id"])
    assert (kcg["harga_jual_cmt"], kcg["harga_jual_cmt_dasar"]) == (150.0, 150.0)
    assert not kcg["plan_edited"]                                  # mengisi harga ≠ mengubah rencana serah
    # qty PO berubah → baris BOM ditulis ulang, harga tetap ikut
    d.po_items.docs[0]["qty"] = 120
    run(pia.explode_po_accessories_from_bom(d, "PO1"))
    kcg2 = next(r for r in d.po_accessories.docs if r["accessory_code"] == KCG["code"] and r.get("bom_origin"))
    assert kcg2["harga_jual_cmt_dasar"] == 150.0
    # Kirim ke CMT: isian nota terisi dari PO, per satuan serah kiriman
    calc = run(kc.compute(d, po_id="PO1", lines=[{"po_item_id": "pi1", "qty": 60}]))
    harga = {(a["code"], a["source"]): a["harga_jual_po"] for a in calc["aksesoris"]}
    assert harga[(KCG["code"], "bom")] == 150.0
    assert harga[(RENDA["code"], "tambahan")] == 33600.0           # 15 per cm × 2.240 cm per roll
    assert harga[(RENDA["code"], "bom")] is None                  # baris BOM Renda belum diberi harga di PO
    # rincian PO menampilkan harga per satuan serah baris
    from core import po_detail
    rows = {r["code"]: r for r in map(po_detail.accessory_plan_row, d.po_accessories.docs)}
    assert rows[KCG["code"]]["harga_jual_cmt"] == 150.0
