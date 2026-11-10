"""Tahap 6 · keputusan owner 7 Nov — Pengadaan / Gudang / Aksesoris (uji unit HERMETIK).

  PG1  barang jadi (tipe fg) tidak ada di daftar pembelian: layar PO/PR/Penerimaan memuat
       `/api/rahaza/materials?exclude_type=fg`; server menolak baris barang jadi di PO (semua jalur),
       PR yang diketik, dan Penerimaan Barang manual.
  PG2  form PO: barang berdaftar-harga supplier terpilih (berlaku hari ini) tampil paling atas, bertanda harga.
  PG3  Penerimaan Barang manual BARU bersumber produksi/pindahan ditolak (pindahan lewat Transfer); tidak ada
       jalur otomatis yang menulis GR bersumber itu.
  PG4  Retur Pembelian: lokasi asal = lokasi yang memegang stok barang baris GR (endpoint stok yang sama
       dengan Transfer).
  PG5  supplier aksesoris & PR aksesoris disimpan sebagai `supplier_id` (nama dari master) + migrasi
       2026_11_07_supplier_id_aksesoris (tautan bila nama cocok tepat satu supplier).
  HR3  pemohon Request Internal = karyawan dari master (bawaan: karyawan akun login).

Jalankan:  cd backend && python -m pytest tests/unit/test_tahap6_pengadaan.py -q
"""
import asyncio
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

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
from core import procurement_guards as pg  # noqa: E402

ROOT = Path(BACKEND).parent
ERP = ROOT / "frontend" / "src" / "components" / "erp"
USER = {"id": "u-uji", "name": "Pengguna Uji", "email": "uji@x", "role": "admin"}
NATIVE_SELECT = "<" + "select"


def run(coro):
    return asyncio.run(coro)


def src(rel: str) -> str:
    p = ERP / rel
    if not p.exists():
        pytest.skip("frontend tidak ada di lingkungan ini")
    return p.read_text(encoding="utf-8")


def _mats(db):
    db.rahaza_materials.docs += [
        {"id": "KAIN", "code": "KN-UJI", "name": "Kain Uji", "type": "fabric", "unit": "kg", "active": True},
        {"id": "ACC", "code": "ACC-UJI", "name": "Kancing Uji", "type": "accessory", "unit": "pcs", "active": True},
        {"id": "FG", "code": "DA-UJI-01", "name": "Barang Jadi Uji", "type": "fg", "unit": "pcs", "active": True},
    ]
    return db


# ══════════════════════════════ PG1 · barang jadi ══════════════════════════════
def test_pesan_barang_jadi_murni():
    assert pg.finished_goods_error([{"type": "fabric"}, {"type": "accessory"}], "PO") is None
    msg = pg.finished_goods_error([{"type": "fg", "code": "DA-1"}, {"type": "fabric", "code": "K"}], "PO pembelian")
    assert msg and "DA-1" in msg and "PO pembelian" in msg and "K," not in msg
    assert pg.finished_goods_error([], "PO") is None


def test_po_menolak_barang_jadi_di_semua_jalur():
    import routes.rahaza_po as po
    db = _mats(fm.FakeDB())
    with pytest.raises(HTTPException) as e:
        run(po._norm_po_items(db, [{"material_id": "KAIN", "qty_input": 1, "unit_cost_input": 10},
                                   {"material_id": "FG", "qty_input": 1, "unit_cost_input": 10}]))
    assert e.value.status_code == 400 and "Barang jadi" in e.value.detail and "DA-UJI-01" in e.value.detail
    ok = run(po._norm_po_items(db, [{"material_id": "KAIN", "qty_input": 2, "unit_cost_input": 10},
                                    {"description": "Jasa kirim", "qty_input": 1, "unit_cost_input": 5}]))
    assert [i["material_id"] for i in ok] == ["KAIN", None]


def test_pr_ketikan_menolak_barang_jadi_pr_otomatis_tidak_berubah():
    import routes.dewi_procurement as proc
    db = _mats(fm.FakeDB())
    items = [{"material_id": "FG", "name": "Barang Jadi Uji", "qty": 1}]
    with pytest.raises(HTTPException) as e:
        run(proc._norm_pr_items(db, items, reject_fg=True))
    assert e.value.status_code == 400 and "Permintaan Pengadaan" in e.value.detail
    assert len(run(proc._norm_pr_items(db, items))) == 1          # jalur otomatis (belanja mingguan) tetap
    s = Path(proc.__file__).read_text(encoding="utf-8")
    assert "reject_fg=not origin" in s and "reject_fg=not req.get(\"origin\")" in s


def _gr_route(monkeypatch, db):
    import routes.warehouse as wh

    async def auth(_req):
        return dict(USER)
    monkeypatch.setattr(wh, "require_auth", auth)
    monkeypatch.setattr(wh, "get_db", lambda: db)
    return wh


def test_gr_manual_menolak_barang_jadi(monkeypatch):
    db = _mats(fm.FakeDB())
    wh = _gr_route(monkeypatch, db)
    body = {"source_type": "supplier", "supplier_name": "PT Uji", "items": [
        {"material_id": "FG", "product_name": "Barang Jadi Uji", "received_qty": 1, "unit": "pcs"}]}
    with pytest.raises(HTTPException) as e:
        run(wh.create_receiving(fm.FakeRequest(body)))
    assert e.value.status_code == 400 and "Penerimaan Barang" in e.value.detail
    assert db.warehouse_receiving.docs == []


def test_layar_pembelian_memuat_material_tanpa_barang_jadi():
    for rel in ("PurchaseOrderModule.jsx", "ProcurementRequestModule.jsx", "ReceivingModule.jsx"):
        s = src(rel)
        assert "/api/rahaza/materials?exclude_type=fg" in s, rel
        assert "fetch('/api/rahaza/materials'," not in s and "/api/rahaza/materials?limit=500" not in s, rel
        assert NATIVE_SELECT not in s, rel


def test_endpoint_material_mendukung_exclude_type():
    s = (Path(BACKEND) / "routes" / "rahaza_inventory_materials.py").read_text(encoding="utf-8")
    assert "exclude_type" in s and '{"$nin": ex}' in s


# ══════════════════════════════ PG2 · daftar harga supplier di atas ══════════════════════════════
def test_daftar_harga_current_hanya_yang_berlaku_hari_ini(monkeypatch):
    import routes.procurement_suppliers as ps
    from datetime import date
    db = fm.FakeDB()
    base = {"supplier_id": "S1", "is_active": True, "uom": "kg", "price": 10, "price_base": 10}
    db.rahaza_supplier_price_lists.docs += [
        {**base, "id": "a", "material_id": "KAIN", "material_code": "A", "valid_from": "2026-11-01", "valid_to": None},
        {**base, "id": "b", "material_id": "ACC", "material_code": "B", "valid_from": "2026-11-01", "valid_to": "2026-11-05"},
        {**base, "id": "c", "material_id": "X", "material_code": "C", "valid_from": "2026-12-01", "valid_to": None},
        {**base, "id": "d", "material_id": "Y", "material_code": "D", "valid_from": "2026-11-01", "is_active": False},
    ]

    async def ok(_req):
        return dict(USER)
    monkeypatch.setattr(ps, "_require_procurement_read", ok)
    monkeypatch.setattr(ps, "get_db", lambda: db)
    monkeypatch.setattr(ps, "today_wib", lambda: date(2026, 11, 7))
    cur = run(ps.list_price_list("S1", fm.FakeRequest(), material_id=None, active_only=True, current=True))
    assert [r["id"] for r in cur["items"]] == ["a"]
    allr = run(ps.list_price_list("S1", fm.FakeRequest(), material_id=None, active_only=True, current=False))
    assert sorted(r["id"] for r in allr["items"]) == ["a", "b", "c"]


def test_form_po_barang_berdaftar_harga_di_atas():
    s = src("PurchaseOrderModule.jsx")
    assert "/price-list?current=true" in s
    i_priced = s.index("materialChoices.priced.map(")
    i_sep = s.index('value="__lain" disabled')
    i_other = s.index("materialChoices.others.map(")
    assert i_priced < i_sep < i_other
    assert "daftar harga" in s and "pricedLabel(m)" in s
    assert 'data-testid="po-form-supplier-pricelist-info"' in s


# ══════════════════════════════ PG3 · GR manual hanya dari pemasok ══════════════════════════════
def test_sumber_gr_manual_murni():
    assert pg.manual_gr_source_error("supplier") is None
    assert pg.manual_gr_source_error(None) is None
    for st in ("production", "transfer", " Production "):
        msg = pg.manual_gr_source_error(st)
        assert msg and "Transfer" in msg and "pemasok" in msg


@pytest.mark.parametrize("source", ["production", "transfer"])
def test_gr_manual_baru_bersumber_produksi_pindahan_ditolak(monkeypatch, source):
    db = _mats(fm.FakeDB())
    wh = _gr_route(monkeypatch, db)
    body = {"source_type": source, "supplier_name": "Line jahit uji", "items": [
        {"material_id": "KAIN", "product_name": "Kain Uji", "received_qty": 1, "unit": "kg"}]}
    with pytest.raises(HTTPException) as e:
        run(wh.create_receiving(fm.FakeRequest(body)))
    assert e.value.status_code == 400 and "Transfer" in e.value.detail
    assert db.warehouse_receiving.docs == []


def test_tidak_ada_jalur_otomatis_menulis_gr_produksi():
    """Penulis `warehouse_receiving` hanya dua: GR dari PO (sumber pemasok) dan form manual."""
    writers = set()
    for d in ("routes", "core"):
        for p in (Path(BACKEND) / d).rglob("*.py"):
            if "_archive" in p.parts:
                continue
            if re.search(r"warehouse_receiving\.insert_(one|many)", p.read_text(encoding="utf-8", errors="ignore")):
                writers.add(p.relative_to(BACKEND).as_posix())
    assert writers == {"routes/rahaza_po.py", "routes/warehouse.py"}
    po_src = (Path(BACKEND) / "routes" / "rahaza_po.py").read_text(encoding="utf-8")
    assert '"source_type": "supplier"' in po_src


def test_form_gr_tanpa_pilihan_produksi_pindahan():
    s = src("ReceivingModule.jsx")
    assert 'value="production"' not in s and 'value="transfer"' not in s
    assert 'data-testid="gr-source-type-select"' not in s and 'data-testid="gr-source-name"' not in s
    assert 'data-testid="gr-transfer-hint"' in s and "Transfer A↔B" in s
    assert "SOURCE_LABEL" in s                                  # GR lama tetap tampil dalam bahasa staf


# ══════════════════════════════ PG4 · retur dari lokasi yang memegang stok ══════════════════════════════
def test_retur_lokasi_asal_dari_stok_barang():
    s = src("procurement/PurchaseReturnModule.jsx")
    assert "/api/rahaza/material-stock?material_id=" in s           # endpoint yang sama dengan Transfer
    assert "(stockLocs || []).map(" in s and 'data-testid="rtp-location"' in s
    assert "setLocs(await apiGet(token, '/api/rahaza/storage-locations'))" not in s
    assert "s.quarantine || s.blocked" in s and "reserved_quantity" in s
    t = src("RahazaStockModule.jsx")
    assert "/api/rahaza/material-stock" in t


# ══════════════════════════════ PG5 · supplier aksesoris by id ══════════════════════════════
def _sups(db):
    db.rahaza_suppliers.docs += [
        {"id": "S1", "code": "SUP-9001", "name": "PT Uji Satu", "is_active": True},
        {"id": "S2", "code": "SUP-9002", "name": "CV Uji Kembar", "is_active": True},
        {"id": "S3", "code": "SUP-9003", "name": "cv  uji kembar", "is_active": True},
        {"id": "S4", "code": "SUP-9004", "name": "PT Uji Nonaktif", "is_active": False},
    ]
    return db


def test_tautan_supplier_dari_id_dan_nama():
    import routes.procurement_suppliers as ps
    db = _sups(fm.FakeDB())
    p = run(ps.supplier_link_patch(db, {"supplier_id": "S1", "supplier": "ketikan bebas"}))
    assert p == {"supplier_id": "S1", "supplier_code": "SUP-9001", "supplier": "PT Uji Satu"}
    for bad in ("TIDAK-ADA", "S4"):
        with pytest.raises(HTTPException) as e:
            run(ps.supplier_link_patch(db, {"supplier_id": bad}))
        assert e.value.status_code == 400
    # id sama dengan yang tersimpan → tidak diperiksa ulang (supplier kini nonaktif tidak menghalangi)
    assert run(ps.supplier_link_patch(db, {"supplier_id": "S4", "name": "x"}, {"supplier_id": "S4"})) == {}
    # nama saja (klien lama): cocok tepat satu (huruf/spasi diabaikan) → tertaut; kembar → tanpa tautan
    p = run(ps.supplier_link_patch(db, {"supplier": "  pt   UJI satu "}))
    assert p["supplier_id"] == "S1" and p["supplier"] == "pt   UJI satu".strip()
    p = run(ps.supplier_link_patch(db, {"supplier": "CV Uji Kembar"}))
    assert p["supplier_id"] is None and p["supplier"] == "CV Uji Kembar"
    assert run(ps.supplier_link_patch(db, {"name": "lain"})) == {}
    # dikosongkan
    assert run(ps.supplier_link_patch(db, {"supplier_id": "", "supplier": ""}, {"supplier_id": "S1"})) == \
        {"supplier_id": None, "supplier_code": None, "supplier": ""}


def _acc_route(monkeypatch, db):
    import routes.dewi_accessories_items as items

    async def auth(_req):
        return dict(USER)
    monkeypatch.setattr(items, "require_auth", auth)
    monkeypatch.setattr(items, "get_db", lambda: db)
    return items


def test_master_aksesoris_simpan_supplier_id_nama_dari_master(monkeypatch):
    db = _sups(fm.FakeDB())
    items = _acc_route(monkeypatch, db)
    res = run(items.create_item(fm.FakeRequest({"code": "ACC-UJI-T6", "name": "Kancing Uji T6", "unit": "pcs",
                                                "supplier_id": "S1", "supplier": "nama ketikan"})))
    out = json.loads(res.body)
    doc = db.rahaza_materials.docs[-1]
    assert doc["supplier_id"] == "S1" and doc["supplier"] == "PT Uji Satu" and doc["supplier_code"] == "SUP-9001"
    assert out["supplier_id"] == "S1" and out["supplier"] == "PT Uji Satu"
    with pytest.raises(HTTPException):
        run(items.create_item(fm.FakeRequest({"code": "ACC-UJI-T6B", "name": "X", "unit": "pcs",
                                              "supplier_id": "TIDAK-ADA"})))
    # Ubah: ganti supplier → nama ikut master; kirim ulang id yang sama → tidak berubah
    run(items.update_item(doc["id"], fm.FakeRequest({"name": "Kancing Uji T6", "supplier_id": "S2"})))
    d2 = next(d for d in db.rahaza_materials.docs if d["id"] == doc["id"])
    assert d2["supplier_id"] == "S2" and d2["supplier"] == "CV Uji Kembar"
    run(items.update_item(doc["id"], fm.FakeRequest({"description": "x", "supplier_id": "S2"})))
    assert next(d for d in db.rahaza_materials.docs if d["id"] == doc["id"])["supplier_id"] == "S2"


def test_pr_aksesoris_memakai_tautan_supplier():
    s = (Path(BACKEND) / "routes" / "dewi_accessories_purchase.py").read_text(encoding="utf-8")
    assert s.count("supplier_link_patch") >= 3                    # import + buat + ubah
    assert '"supplier": body.get("supplier", "")' not in s
    from core.accessory_procurement import acc_pr_body
    body = acc_pr_body({"supplier": "PT Uji Satu", "supplier_id": "S1", "items": []})
    assert body["suggested_supplier_id"] == "S1" and "PT Uji Satu" in body["description"]


def test_form_aksesoris_supplier_bernilai_id():
    s = src("AccessoryModule.jsx")
    assert "function SupplierPick" in s and "<option key={s.id} value={s.id}>" in s
    assert 'data-testid="acc-supplier-select"' in s and 'data-testid="pr-supplier"' in s
    assert "value={s.name}>{`${s.code} — ${s.name}`}" not in s
    assert "supplier_id: it.supplier_id||''" in s


def _migrasi():
    p = Path(BACKEND) / "scripts" / "migrations" / "2026_11_07_supplier_id_aksesoris.py"
    spec = importlib.util.spec_from_file_location("mig_supplier_id_aksesoris", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_rencana_tautan_murni():
    mig = _migrasi()
    sups = [{"id": "S1", "name": "PT Uji Satu"}, {"id": "S2", "name": "CV Kembar"}, {"id": "S3", "name": "cv  kembar"}]
    rows = [{"id": "a", "supplier": " pt uji  SATU"}, {"id": "b", "supplier": "CV Kembar"},
            {"id": "c", "supplier": "Toko Lain"}, {"id": "d", "supplier": ""}, {"id": "e"}]
    plan = mig.plan_links(rows, sups)
    assert [(i, s["id"]) for i, s in plan["link"]] == [("a", "S1")]
    assert (plan["ambiguous"], plan["no_match"], plan["empty"]) == (1, 1, 2)


def test_migrasi_pratinjau_tulis_idempoten():
    mig = _migrasi()
    db = _sups(fm.FakeDB())
    db.rahaza_materials.docs += [
        {"id": "m1", "type": "accessory", "supplier": "PT UJI SATU"},
        {"id": "m2", "type": "accessory", "supplier": "CV Uji Kembar"},
        {"id": "m3", "type": "accessory", "supplier": "Tidak Dikenal"},
        {"id": "m4", "type": "accessory", "supplier": "PT Uji Satu", "supplier_id": "S9"},   # sudah tertaut
        {"id": "m5", "type": "fabric", "supplier": "PT Uji Satu"},                          # bukan aksesoris
    ]
    db.acc_purchase_requests.docs += [{"id": "p1", "supplier": "pt uji satu", "supplier_id": None}]
    pre = run(mig.run(db, apply=False))
    assert pre["rahaza_materials"] == {"unlinked": 3, "to_link": 1, "ambiguous": 1, "no_match": 1,
                                       "no_name": 0, "linked": 0}
    assert "supplier_id" not in db.rahaza_materials.docs[0]                                  # pratinjau tidak menulis
    res = run(mig.run(db, apply=True))
    assert res["rahaza_materials"]["linked"] == 1 and res["acc_purchase_requests"]["linked"] == 1
    m1 = db.rahaza_materials.docs[0]
    assert m1["supplier_id"] == "S1" and m1["supplier_code"] == "SUP-9001" and m1["supplier"] == "PT UJI SATU"
    assert db.rahaza_materials.docs[3]["supplier_id"] == "S9" and "supplier_id" not in db.rahaza_materials.docs[4]
    again = run(mig.run(db, apply=True))
    assert again["rahaza_materials"]["linked"] == 0 and again["acc_purchase_requests"]["linked"] == 0


# ══════════════════════════════ HR3 · pemohon = karyawan ══════════════════════════════
def _emp_db():
    db = fm.FakeDB()
    db.rahaza_employees.docs += [
        {"id": "E1", "employee_code": "UJI-001", "name": "Karyawan Uji Satu", "active": True, "user_id": "u-uji"},
        {"id": "E2", "employee_code": "UJI-002", "name": "Karyawan Uji Dua", "active": True},
        {"id": "E3", "employee_code": "UJI-003", "name": "Karyawan Uji Keluar", "active": False},
    ]
    return db


def test_pemohon_dari_master_karyawan():
    import routes.dewi_accessory_requests as dar
    db = _emp_db()
    f = run(dar._requester_fields(db, USER, "E2"))
    assert f == {"requester_employee_id": "E2", "requester_employee_code": "UJI-002",
                 "requester_name": "Karyawan Uji Dua"}
    for bad in ("E3", "TIDAK-ADA"):
        with pytest.raises(HTTPException) as e:
            run(dar._requester_fields(db, USER, bad))
        assert e.value.status_code == 400
    assert run(dar._requester_fields(db, USER, ""))["requester_employee_id"] == "E1"     # akun tertaut
    lone = run(dar._requester_fields(db, {"id": "u-lain", "name": "Akun Tanpa Karyawan"}, None))
    assert lone == {"requester_employee_id": None, "requester_employee_code": "", "requester_name": "Akun Tanpa Karyawan"}


def test_request_internal_simpan_pemohon_karyawan(monkeypatch):
    import routes.dewi_accessory_requests as dar
    import core.doc_number_policy as dnp
    db = _emp_db()
    db.rahaza_materials.docs = [{"id": "ACC", "code": "ACC", "name": "Aksesoris", "type": "accessory",
                                 "active": True, "unit": "pcs"}]   # 2026-11-10: baris wajib master aktif
    monkeypatch.setattr(dar, "get_db", lambda: db)

    async def num(*a, **k):
        return "INT-REQ-UJI-0001"
    monkeypatch.setattr(dnp, "issue_number", num)
    out = run(dar.create_request({"request_type": "internal_issuance", "status": "submitted",
                                  "requester_employee_id": "E2", "requester_name": "nama ketikan",
                                  "items": [{"material_id": "ACC", "qty": 1}]}, user=dict(USER)))
    assert out["requester_employee_id"] == "E2" and out["requester_name"] == "Karyawan Uji Dua"
    assert out["requester_id"] == "u-uji" and out["created_by_name"] == "Pengguna Uji"
    # Ubah: nama pemohon tidak bisa diketik lewat PUT; ganti lewat id karyawan
    run(dar.update_request(out["id"], {"requester_name": "ketikan lain"}, user=dict(USER)))
    assert db.dewi_accessory_requests.docs[0]["requester_name"] == "Karyawan Uji Dua"
    run(dar.update_request(out["id"], {"requester_employee_id": "E1"}, user=dict(USER)))
    assert db.dewi_accessory_requests.docs[0]["requester_name"] == "Karyawan Uji Satu"


def test_form_request_internal_pemilih_karyawan():
    s = src("AccessoryModule.jsx")
    assert "EmployeeSelect" in s and "useActiveEmployees" in s and "from './hr/hrPickers'" in s
    assert "requester_employee_id: form.requester_employee_id" in s
    assert "/api/portal-saya/me/employee" in s
    assert "Pemohon: ${form.requester_name}" not in s and 'placeholder="Nama..."' not in s
    assert NATIVE_SELECT not in s
