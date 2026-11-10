"""Master Gudang/Pengadaan/Aksesoris/Penjualan/Aset bisa diubah & dihapus (permintaan owner 10 Nov 2026) — hermetik.

Kata owner: "… pastikan table table master data bisa dihapus". Pola bersama: `core.hapus_master` (409 + kalimat
"sudah dipakai di …") dan layar `lib/hapusMaster` (dialog kedua menawarkan Nonaktifkan).

Yang dikunci per master — belum dipakai → terhapus permanen (+ anak konfigurasinya sendiri); sudah dipakai → 409
dengan label pemakaian; tanpa `hard` → perilaku lama (nonaktifkan); gerbang peran jalur hapus; layar punya kolom
Aksi dengan Ubah + Hapus yang memanggil `hapusMaster` / `?hard=true`:
  * bahan & aksesoris (`rahaza_materials`, dua rute: Master Item dan Master Aksesoris — satu aturan pemakaian);
  * gedung / zona / rak gudang (posisi, stok, riwayat, opname, gulungan; anak aktif harus dihapus dulu);
  * satuan & aturan konversi gudang;
  * supplier (daftar harga & akun hutang otomatis ikut terhapus);
  * pelanggan (dua rute kembar `sales_direct` & `rahaza_orders` — satu fungsi);
  * kategori aset (dulu 400 "ada {n} aset" → 409 lewat helper).
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
FE = REPO / "frontend" / "src"
ADMIN = {"id": "u-admin", "name": "Admin Uji", "role": "admin"}
STAF = {"id": "u-staf", "name": "Staf Uji", "role": "operator", "_permissions": []}
REQ = fm.FakeRequest()


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


def _kembalikan(user):
    async def _f(*_a, **_k):
        return user
    return _f


def fe(rel: str) -> str:
    p = FE / rel
    if not p.exists():
        pytest.skip("frontend tidak ada di lingkungan ini")
    return p.read_text(encoding="utf-8")


def _tolak(coro, *labels):
    with pytest.raises(HTTPException) as e:
        run(coro)
    assert e.value.status_code == 409, e.value.detail
    for lb in labels:
        assert lb in e.value.detail, (lb, e.value.detail)
    assert "tidak bisa dihapus" in e.value.detail
    return e.value.detail


def _deps(router, method, path):
    for r in router.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return [getattr(getattr(d, "dependency", None) or getattr(d, "call", None), "__name__", "") for d in r.dependencies]
    raise AssertionError(f"rute {method} {path} tidak ada")


# ══════════════════════════════ Bahan & aksesoris (rahaza_materials) ══════════════════════════════
@pytest.fixture
def bahan(monkeypatch):
    import routes.rahaza_inventory_materials as mod
    db = fm.FakeDB()
    db.rahaza_materials.docs = [
        {"id": "m1", "code": "KN-01", "name": "Kain Katun", "type": "fabric", "unit": "kg", "active": True},
        {"id": "m2", "code": "KN-02", "name": "Kain Lain", "type": "fabric", "unit": "kg", "active": True},
    ]
    db.rahaza_material_stock.docs = [{"material_id": "m1", "location_id": "L1", "qty": 0},
                                     {"material_id": "m2", "location_id": "L1", "qty": 7}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, "_require_admin", _kembalikan(ADMIN))
    return mod, db


def test_bahan_belum_dipakai_dihapus_permanen(bahan):
    mod, db = bahan
    out = run(mod.deactivate_material("m1", REQ, hard=True))
    assert out["deleted"] is True
    assert [m["id"] for m in db.rahaza_materials.docs] == ["m2"]
    # baris stok bersaldo 0 milik m1 ikut hilang; stok barang lain tidak tersentuh
    assert db.rahaza_material_stock.docs == [{"material_id": "m2", "location_id": "L1", "qty": 7}]


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_material_stock", {"material_id": "m1", "location_id": "L2", "quantity": 3}, "lokasi stok bersaldo"),
    ("rahaza_material_movements", {"id": "mv1", "material_id": "m1"}, "kartu stok"),
    ("rahaza_stock_ledger", {"id": "l1", "material_id": "m1"}, "buku besar stok"),
    ("rahaza_boms", {"id": "b1", "materials": [{"material_id": "x"}, {"material_id": "m1"}]}, "BOM produksi"),
    ("rahaza_boms", {"id": "b2", "accessory_materials": [{"material_id": "m1"}]}, "BOM produksi"),
    ("dewi_maklon_bom_templates", {"id": "t1", "materials": [{"material_id": "m1"}]}, "templat BOM maklon"),
    ("dewi_procurement_requests", {"id": "pr1", "items": [{"material_id": "m1"}]}, "permintaan pembelian"),
    ("acc_purchase_requests", {"id": "apr1", "items": [{"acc_id": "m1"}]}, "permintaan pembelian aksesoris"),
    ("rahaza_purchase_orders", {"id": "po1", "items": [{"material_id": "m1"}]}, "PO pembelian"),
    ("warehouse_receiving", {"id": "gr1", "items": [{"material_id": "m1"}]}, "penerimaan barang"),
    ("rahaza_purchase_returns", {"id": "rt1", "lines": [{"material_id": "m1"}]}, "retur pembelian"),
    ("rahaza_material_issues", {"id": "mi1", "items": [{"material_id": "m1"}]}, "pengeluaran material"),
    ("wh_opname3_sessions", {"id": "op1", "lines": [{"material_id": "m1", "bin_id": ""}]}, "opname stok"),
    ("wh_quarantine_items", {"id": "q1", "material_id": "m1"}, "karantina QC"),
    ("wh_fabric_rolls", {"id": "fr1", "material_id": "m1"}, "gulungan kain"),
    ("wh_positions", {"id": "p1", "material_id": "m1"}, "posisi rak"),
    ("cutting_orders", {"id": "co1", "input_material_id": "m1"}, "order cutting"),
    ("rahaza_materials", {"id": "pt1", "code": "PT-01", "source_material_id": "m1"}, "barang turunan"),
    ("marketing_catalog_items", {"id": "ci1", "fg_material_id": "m1"}, "produk katalog"),
])
def test_bahan_sudah_dipakai_ditolak_409(bahan, koleksi, doc, label):
    mod, db = bahan
    getattr(db, koleksi).docs.append(doc)
    _tolak(mod.deactivate_material("m1", REQ, hard=True), label, 'Material "Kain Katun"', "Nonaktifkan")
    assert any(m["id"] == "m1" for m in db.rahaza_materials.docs)


def test_bahan_tanpa_hard_tetap_nonaktifkan(bahan):
    mod, db = bahan
    assert run(mod.deactivate_material("m1", REQ, hard=False)) == {"status": "deactivated"}
    assert db.rahaza_materials.docs[0]["active"] is False


def test_bahan_hapus_dijaga_peran(monkeypatch):
    import routes.rahaza_inventory_materials as mod
    import routes.rahaza_inventory_shared as shared
    db = fm.FakeDB()
    db.rahaza_materials.docs = [{"id": "m1", "code": "KN-01", "name": "Kain", "type": "fabric", "active": True}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(shared, "require_auth", _kembalikan(STAF))
    with pytest.raises(HTTPException) as e:
        run(mod.deactivate_material("m1", REQ, hard=True))
    assert e.value.status_code == 403 and len(db.rahaza_materials.docs) == 1


# ── Master Aksesoris: rute sendiri, aturan pemakaian SAMA ──
@pytest.fixture
def aksesoris(monkeypatch):
    import routes.dewi_accessories_items as mod
    import routes.rahaza_inventory_materials as mat
    import routes.shared as shared
    db = fm.FakeDB()
    db.rahaza_materials.docs = [{"id": "a1", "code": "ACC-0001", "name": "Kancing", "type": "accessory", "active": True}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mat, "log_activity", _noop)
    monkeypatch.setattr(shared, "require_perm", _kembalikan(ADMIN))
    return mod, db


def test_aksesoris_belum_dipakai_dihapus_permanen(aksesoris):
    mod, db = aksesoris
    out = run(mod.delete_item("a1", REQ, hard=True))
    assert out["ok"] is True and out["deleted"] is True and db.rahaza_materials.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_material_stock", {"material_id": "a1", "location_id": "L1", "qty": 12}, "lokasi stok bersaldo"),
    ("rahaza_boms", {"id": "b1", "materials": [{"material_id": "a1"}]}, "BOM produksi"),
    ("dewi_maklon_bom_templates", {"id": "t1", "materials": [{"material_id": "a1"}]}, "templat BOM maklon"),
    ("rahaza_material_movements", {"id": "mv1", "material_id": "a1"}, "kartu stok"),
])
def test_aksesoris_berstok_atau_di_bom_ditolak_409(aksesoris, koleksi, doc, label):
    """Layar dulu berjanji "ditolak bila berstok / di BOM" padahal server tidak memeriksa apa pun."""
    mod, db = aksesoris
    getattr(db, koleksi).docs.append(doc)
    _tolak(mod.delete_item("a1", REQ, hard=True), label, 'Aksesoris "Kancing"')
    assert len(db.rahaza_materials.docs) == 1


def test_aksesoris_tanpa_hard_tetap_nonaktifkan(aksesoris):
    mod, db = aksesoris
    assert run(mod.delete_item("a1", REQ, hard=False)) == {"ok": True}
    assert db.rahaza_materials.docs[0]["active"] is False


def test_aksesoris_hapus_dijaga_peran(monkeypatch):
    import auth
    import routes.dewi_accessories_items as mod
    db = fm.FakeDB()
    db.rahaza_materials.docs = [{"id": "a1", "code": "ACC-0001", "name": "Kancing", "type": "accessory", "active": True}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(auth, "require_auth", _kembalikan(STAF))
    with pytest.raises(HTTPException) as e:
        run(mod.delete_item("a1", REQ, hard=True))
    assert e.value.status_code == 403 and len(db.rahaza_materials.docs) == 1


# ══════════════════════════════ Gedung / zona / rak ══════════════════════════════
@pytest.fixture
def gudang(monkeypatch):
    import routes.wms_structure as mod
    db = fm.FakeDB()
    db.wh_buildings.docs = [{"id": "b1", "code": "WH1", "name": "Gudang Utama", "active": True}]
    db.wh_zones.docs = [{"id": "z1", "building_id": "b1", "building_code": "WH1", "code": "RM", "name": "Bahan", "active": True}]
    db.wh_racks.docs = [{"id": "r1", "zone_id": "z1", "building_id": "b1", "code": "R01", "name": "Rak 1", "active": True}]
    db.wh_positions.docs = [{"id": "p1", "rack_id": "r1", "zone_id": "z1", "status": "empty"},
                            {"id": "p2", "rack_id": "r1", "zone_id": "z1", "status": "empty"}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, "require_auth", _kembalikan(ADMIN))
    return mod, db


def test_rak_belum_dipakai_dihapus_beserta_posisinya(gudang):
    mod, db = gudang
    out = run(mod.delete_rack("r1", REQ, hard=True))
    assert out["deleted"] is True and db.wh_racks.docs == [] and db.wh_positions.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("wh_positions", {"id": "p3", "rack_id": "r1", "status": "occupied"}, "posisi terisi"),
    ("rahaza_material_stock", {"material_id": "m1", "location_id": "p1", "qty": 2}, "lokasi stok bersaldo"),
    ("rahaza_stock_ledger", {"id": "l1", "location_id": "p2"}, "riwayat stok"),
    ("wh_placement_movements", {"id": "pm1", "position_id": "p1"}, "riwayat penempatan rak"),
    ("wh_opname3_sessions", {"id": "o1", "lines": [{"material_id": "m1", "bin_id": "p2"}]}, "opname stok"),
    ("wh_fabric_rolls", {"id": "fr1", "position_id": "p1"}, "gulungan kain"),
])
def test_rak_sudah_dipakai_ditolak_409(gudang, koleksi, doc, label):
    mod, db = gudang
    getattr(db, koleksi).docs.append(doc)
    _tolak(mod.delete_rack("r1", REQ, hard=True), label, 'Rak "R01 Rak 1"')
    assert len(db.wh_racks.docs) == 1 and len(db.wh_positions.docs) >= 2


def test_rak_tanpa_hard_perilaku_lama(gudang):
    mod, db = gudang
    db.wh_positions.docs[0]["status"] = "occupied"
    with pytest.raises(HTTPException) as e:          # penjaga nonaktifkan lama tetap 400
        run(mod.delete_rack("r1", REQ, hard=False))
    assert e.value.status_code == 400
    db.wh_positions.docs[0]["status"] = "empty"
    assert run(mod.delete_rack("r1", REQ, hard=False))["message"] == "Rak dinonaktifkan"
    assert db.wh_racks.docs[0]["active"] is False and len(db.wh_positions.docs) == 2


def test_zona_dengan_rak_aktif_ditolak_lalu_bersih_terhapus(gudang):
    mod, db = gudang
    detail = _tolak(mod.delete_zone("z1", REQ, hard=True), "1 rak aktif", 'Zona "RM Bahan"')
    assert "Hapus atau nonaktifkan rak" in detail
    db.wh_racks.docs[0]["active"] = False           # rak nonaktif yang bersih ikut terhapus bersama zona
    out = run(mod.delete_zone("z1", REQ, hard=True))
    assert out["deleted"] is True
    assert db.wh_zones.docs == [] and db.wh_racks.docs == [] and db.wh_positions.docs == []
    assert len(db.wh_buildings.docs) == 1


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_stock_ledger", {"id": "l1", "location_id": "p1"}, "riwayat stok"),          # riwayat di rak nonaktif
    ("rahaza_stock_ledger", {"id": "l2", "location_id": "z1"}, "riwayat stok"),          # riwayat di zona itu
    ("rahaza_material_stock", {"material_id": "m1", "location_id": "z1", "qty": 4}, "lokasi stok bersaldo"),
    ("wh_location_migration_map", {"rahaza_location_id": "loc1", "wh_zone_id": "z1"}, "tautan lokasi gudang lama"),
])
def test_zona_sudah_dipakai_ditolak_409(gudang, koleksi, doc, label):
    mod, db = gudang
    db.wh_racks.docs[0]["active"] = False
    getattr(db, koleksi).docs.append(doc)
    detail = _tolak(mod.delete_zone("z1", REQ, hard=True), label)
    assert "Nonaktifkan saja" in detail
    assert len(db.wh_zones.docs) == 1 and len(db.wh_racks.docs) == 1


def test_zona_tanpa_hard_perilaku_lama(gudang):
    mod, db = gudang
    with pytest.raises(HTTPException) as e:
        run(mod.delete_zone("z1", REQ, hard=False))
    assert e.value.status_code == 400
    db.wh_racks.docs[0]["active"] = False
    assert run(mod.delete_zone("z1", REQ, hard=False))["message"] == "Zona dinonaktifkan"
    assert db.wh_zones.docs[0]["active"] is False


def test_gedung_dengan_zona_aktif_ditolak_lalu_bersih_terhapus(gudang):
    mod, db = gudang
    detail = _tolak(mod.delete_building("b1", REQ, hard=True), "1 zona aktif", "1 rak aktif", 'Gedung "WH1 Gudang Utama"')
    assert "Hapus atau nonaktifkan zona" in detail
    db.wh_zones.docs[0]["active"] = False
    db.wh_racks.docs[0]["active"] = False
    db.rahaza_stock_ledger.docs = [{"id": "l1", "location_id": "b1"}]
    _tolak(mod.delete_building("b1", REQ, hard=True), "riwayat stok")
    db.rahaza_stock_ledger.docs = []
    out = run(mod.delete_building("b1", REQ, hard=True))
    assert out["deleted"] is True
    assert db.wh_buildings.docs == [] and db.wh_zones.docs == [] and db.wh_racks.docs == [] and db.wh_positions.docs == []


def test_gedung_tanpa_hard_perilaku_lama(gudang):
    mod, db = gudang
    with pytest.raises(HTTPException) as e:
        run(mod.delete_building("b1", REQ, hard=False))
    assert e.value.status_code == 400
    db.wh_racks.docs[0]["active"] = False
    assert run(mod.delete_building("b1", REQ, hard=False))["message"] == "Gedung dinonaktifkan"
    assert db.wh_buildings.docs[0]["active"] is False


# ══════════════════════════════ Satuan & konversi ══════════════════════════════
@pytest.fixture
def satuan(monkeypatch):
    import routes.wms_units as mod
    db = fm.FakeDB()
    db.wh_unit_master.docs = [{"id": "u1", "code": "gulung", "name": "Gulung", "category": "roll", "active": True},
                              {"id": "u2", "code": "m", "name": "Meter", "category": "length", "active": True}]
    db.wh_unit_conversions.docs = [{"id": "c1", "from_unit_id": "u1", "to_unit_id": "u2", "from_unit_code": "gulung",
                                    "to_unit_code": "m", "factor": 50, "active": False}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, "require_auth", _kembalikan(ADMIN))
    return mod, db


def test_satuan_belum_dipakai_dihapus_beserta_konversi_nonaktif(satuan):
    mod, db = satuan
    out = run(mod.delete_unit("u1", REQ, hard=True))
    assert out["deleted"] is True
    assert [u["id"] for u in db.wh_unit_master.docs] == ["u2"] and db.wh_unit_conversions.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_materials", {"id": "m1", "unit": "kg", "uoms": [{"code": "gulung", "factor": 25}]}, "barang"),
    ("rahaza_materials", {"id": "m2", "unit": "gulung"}, "barang"),
    ("wh_unit_conversions", {"id": "c2", "from_unit_id": "u2", "to_unit_id": "u1", "active": True}, "aturan konversi"),
])
def test_satuan_sudah_dipakai_ditolak_409(satuan, koleksi, doc, label):
    mod, db = satuan
    getattr(db, koleksi).docs.append(doc)
    _tolak(mod.delete_unit("u1", REQ, hard=True), label, 'Satuan "gulung"')
    assert len(db.wh_unit_master.docs) == 2


def test_satuan_dan_konversi_tanpa_hard_tetap_nonaktifkan(satuan):
    mod, db = satuan
    run(mod.delete_unit("u1", REQ, hard=False))
    assert db.wh_unit_master.docs[0]["active"] is False
    db.wh_unit_conversions.docs[0]["active"] = True
    run(mod.delete_conversion("c1", REQ, hard=False))
    assert db.wh_unit_conversions.docs[0]["active"] is False


def test_konversi_hapus_permanen(satuan):
    mod, db = satuan
    assert run(mod.delete_conversion("c1", REQ, hard=True))["deleted"] is True
    assert db.wh_unit_conversions.docs == []
    with pytest.raises(HTTPException) as e:
        run(mod.delete_conversion("c1", REQ, hard=True))
    assert e.value.status_code == 404


@pytest.mark.parametrize("modname,path", [
    ("routes.wms_structure", "/api/wms/buildings/{building_id}"),
    ("routes.wms_structure", "/api/wms/zones/{zone_id}"),
    ("routes.wms_structure", "/api/wms/racks/{rack_id}"),
    ("routes.wms_units", "/api/wms/units/{unit_id}"),
    ("routes.wms_units", "/api/wms/unit-conversions/{conv_id}"),
])
def test_endpoint_hapus_gudang_dijaga_peran(modname, path):
    import importlib
    mod = importlib.import_module(modname)
    assert any(n.startswith("require_roles[") and "wh.bin.manage" in n for n in _deps(mod.router, "DELETE", path))


# ══════════════════════════════ Supplier ══════════════════════════════
@pytest.fixture
def supplier(monkeypatch):
    import routes.procurement_suppliers as mod
    db = fm.FakeDB()
    db.rahaza_suppliers.docs = [{"id": "s1", "code": "SUP-001", "name": "PT Benang Jaya", "is_active": True}]
    db.rahaza_supplier_price_lists.docs = [{"id": "pl1", "supplier_id": "s1", "material_id": "m1"},
                                           {"id": "pl2", "supplier_id": "s2", "material_id": "m1"}]
    db.rahaza_coa_accounts.docs = [
        {"id": "a1", "code": "2-1100-001", "flags": {"subledger_entity_type": "supplier", "subledger_entity_id": "s1"}},
        {"id": "a2", "code": "2-1100", "flags": {}},
    ]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, "_require_procurement", _kembalikan(ADMIN))
    return mod, db


def test_supplier_belum_dipakai_dihapus_beserta_harga_dan_akun(supplier):
    mod, db = supplier
    out = run(mod.deactivate_supplier("s1", REQ, hard=True))
    assert out["deleted"] is True and db.rahaza_suppliers.docs == []
    assert [p["id"] for p in db.rahaza_supplier_price_lists.docs] == ["pl2"]   # harga supplier lain tetap
    assert [a["code"] for a in db.rahaza_coa_accounts.docs] == ["2-1100"]


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_purchase_orders", {"id": "po1", "supplier_id": "s1", "status": "closed"}, "PO pembelian"),
    ("warehouse_receiving", {"id": "gr1", "supplier_id": "s1"}, "penerimaan barang"),
    ("rahaza_ap_invoices", {"id": "ap1", "supplier_id": "s1"}, "faktur pemasok"),
    ("rahaza_purchase_returns", {"id": "rt1", "supplier_id": "s1"}, "retur pembelian"),
    ("dewi_procurement_requests", {"id": "pr1", "items": [{"suggested_supplier_id": "s1"}]}, "permintaan pembelian"),
    ("acc_purchase_requests", {"id": "apr1", "supplier_id": "s1"}, "permintaan pembelian aksesoris"),
    ("rahaza_fixed_assets", {"id": "fa1", "supplier_id": "s1"}, "aset tetap"),
    ("rahaza_journal_lines", {"id": "j1", "account_code": "2-1100-001"}, "baris jurnal"),
])
def test_supplier_sudah_dipakai_ditolak_409(supplier, koleksi, doc, label):
    mod, db = supplier
    getattr(db, koleksi).docs.append(doc)
    _tolak(mod.deactivate_supplier("s1", REQ, hard=True), label, 'Supplier "PT Benang Jaya"')
    assert len(db.rahaza_suppliers.docs) == 1 and len(db.rahaza_supplier_price_lists.docs) == 2
    assert len(db.rahaza_coa_accounts.docs) == 2


def test_supplier_tanpa_hard_perilaku_lama(supplier):
    mod, db = supplier
    db.rahaza_purchase_orders.docs = [{"id": "po1", "supplier_id": "s1", "status": "approved"}]
    with pytest.raises(HTTPException) as e:          # penjaga "PO berjalan" jalur nonaktifkan tetap 400
        run(mod.deactivate_supplier("s1", REQ, hard=False))
    assert e.value.status_code == 400
    db.rahaza_purchase_orders.docs = []
    assert run(mod.deactivate_supplier("s1", REQ, hard=False))["is_active"] is False
    assert db.rahaza_suppliers.docs[0]["is_active"] is False


def test_supplier_hapus_dijaga_peran(monkeypatch):
    import routes.procurement_suppliers as mod
    db = fm.FakeDB()
    db.rahaza_suppliers.docs = [{"id": "s1", "code": "SUP-001", "name": "PT Benang Jaya", "is_active": True}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "require_auth", _kembalikan(STAF))
    with pytest.raises(HTTPException) as e:
        run(mod.deactivate_supplier("s1", REQ, hard=True))
    assert e.value.status_code == 403 and len(db.rahaza_suppliers.docs) == 1


# ══════════════════════════════ Pelanggan (dua rute kembar) ══════════════════════════════
@pytest.fixture
def pelanggan(monkeypatch):
    import routes.sales_direct as sd
    import routes.rahaza_orders as ro
    db = fm.FakeDB()
    db.rahaza_customers.docs = [{"id": "c1", "code": "CUST-001", "name": "Toko Uji", "active": True}]
    db.rahaza_coa_accounts.docs = [
        {"id": "a1", "code": "1-1301-001", "flags": {"subledger_entity_type": "customer", "subledger_entity_id": "c1"}},
        {"id": "a2", "code": "1-1301", "flags": {}},
    ]
    for m in (sd, ro):
        monkeypatch.setattr(m, "get_db", lambda: db)
    monkeypatch.setattr(sd, "log_activity", _noop)
    monkeypatch.setattr(sd, "_require_write", _kembalikan(ADMIN))
    monkeypatch.setattr(ro, "_require_admin", _kembalikan(ADMIN))
    return {"penjualan": sd, "pesanan": ro}, db


RUTE_PELANGGAN = ["penjualan", "pesanan"]


@pytest.mark.parametrize("rute", RUTE_PELANGGAN)
def test_pelanggan_belum_dipakai_dihapus_beserta_akun_piutang(pelanggan, rute):
    mods, db = pelanggan
    out = run(mods[rute].deactivate_customer("c1", REQ, hard=True))
    assert out["deleted"] is True and db.rahaza_customers.docs == []
    assert [a["code"] for a in db.rahaza_coa_accounts.docs] == ["1-1301"]


@pytest.mark.parametrize("rute", RUTE_PELANGGAN)
@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_orders", {"id": "o1", "customer_id": "c1"}, "pesanan penjualan"),
    ("sales_direct_notes", {"id": "n1", "customer_id": "c1"}, "nota penjualan langsung"),
    ("sales_direct_returns", {"id": "r1", "customer_id": "c1"}, "retur penjualan langsung"),
    ("rahaza_shipments", {"id": "s1", "customer_id": "c1"}, "pengiriman"),
    ("rahaza_fg_issues", {"id": "f1", "customer_id": "c1"}, "pengeluaran barang jadi"),
    ("rahaza_ar_invoices", {"id": "i1", "customer_id": "c1"}, "faktur piutang"),
    ("rahaza_ar_payments", {"id": "p1", "customer_id": "c1"}, "pembayaran piutang"),
    ("rahaza_credit_notes", {"id": "cn1", "customer_id": "c1"}, "nota kredit"),
    ("rahaza_journal_lines", {"id": "j1", "account_code": "1-1301-001"}, "baris jurnal"),
])
def test_pelanggan_sudah_dipakai_ditolak_409(pelanggan, rute, koleksi, doc, label):
    mods, db = pelanggan
    getattr(db, koleksi).docs.append(doc)
    _tolak(mods[rute].deactivate_customer("c1", REQ, hard=True), label, 'Pelanggan "Toko Uji"')
    assert len(db.rahaza_customers.docs) == 1 and len(db.rahaza_coa_accounts.docs) == 2


@pytest.mark.parametrize("rute", RUTE_PELANGGAN)
def test_pelanggan_tanpa_hard_tetap_nonaktifkan(pelanggan, rute):
    mods, db = pelanggan
    assert run(mods[rute].deactivate_customer("c1", REQ, hard=False)) == {"status": "deactivated"}
    assert db.rahaza_customers.docs[0]["active"] is False


def test_pelanggan_dua_rute_satu_fungsi():
    import inspect
    import routes.rahaza_orders as ro
    assert "delete_customer_master" in inspect.getsource(ro.deactivate_customer)


@pytest.mark.parametrize("modname,user", [
    ("routes.sales_direct", STAF),
    ("routes.rahaza_orders", {"id": "u", "name": "Sales", "role": "sales", "_permissions": []}),
])
def test_pelanggan_hapus_dijaga_peran(monkeypatch, modname, user):
    import importlib
    mod = importlib.import_module(modname)
    db = fm.FakeDB()
    db.rahaza_customers.docs = [{"id": "c1", "code": "CUST-001", "name": "Toko Uji", "active": True}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "require_auth", _kembalikan(user))
    with pytest.raises(HTTPException) as e:
        run(mod.deactivate_customer("c1", REQ, hard=True))
    assert e.value.status_code == 403 and len(db.rahaza_customers.docs) == 1


# ══════════════════════════════ Kategori aset ══════════════════════════════
@pytest.fixture
def kategori(monkeypatch):
    import routes.asset.categories as mod
    import routes.shared as shared
    db = fm.FakeDB()
    db.dewi_asset_categories.docs = [{"id": "k1", "code": "MJ", "name": "Mesin jahit", "active": True}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(shared, "require_perm", _kembalikan(ADMIN))
    return mod, db


def test_kategori_aset_belum_dipakai_dihapus(kategori):
    mod, db = kategori
    assert run(mod.delete_category("k1", REQ)) == {"ok": True}
    assert db.dewi_asset_categories.docs == []


def test_kategori_aset_dipakai_ditolak_409_bukan_400(kategori):
    mod, db = kategori
    db.dewi_assets.docs = [{"id": "x1", "category_id": "k1"}, {"id": "x2", "category_id": "k1"}]
    detail = _tolak(mod.delete_category("k1", REQ), "2 aset", 'Kategori aset "Mesin jahit"')
    assert "Pindahkan aset itu ke kategori lain" in detail
    assert len(db.dewi_asset_categories.docs) == 1


def test_kategori_aset_hapus_dijaga_peran(monkeypatch):
    import auth
    import routes.asset.categories as mod
    db = fm.FakeDB()
    db.dewi_asset_categories.docs = [{"id": "k1", "code": "MJ", "name": "Mesin jahit"}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(auth, "require_auth", _kembalikan(STAF))
    with pytest.raises(HTTPException) as e:
        run(mod.delete_category("k1", REQ))
    assert e.value.status_code == 403 and len(db.dewi_asset_categories.docs) == 1


# ══════════════════════════════ layar ══════════════════════════════
@pytest.mark.parametrize("rel,frags", [
    ("components/erp/RahazaMaterialsModule.jsx",
     ("label: 'Aksi'", "mat-edit-", "mat-delete-", "hapusMaster", "?hard=true", "e.status = res.status")),
    ("components/erp/WMSModule.jsx",
     ("label: 'Aksi'", "building-edit-", "building-delete-", "zone-delete-", "rack-delete-", "unit-delete-",
      "conversion-delete-", "hapusMaster", "?hard=true", "e.status = r.status")),
    ("components/erp/procurement/SupplierMasterModule.jsx",
     ("label: 'Aksi'", "supplier-edit-", "supplier-delete-", "hapusMaster", "?hard=true", "e.status = res.status")),
    ("components/erp/AccessoryModule.jsx",
     ("label: 'Aksi'", "edit-acc-", "del-acc-", "hapusMaster", "?hard=true", "e.status = r.status")),
    ("components/erp/sales/SalesCustomersModule.jsx",
     ("label: 'Aksi'", "cust-edit-", "cust-delete-", "hapusMaster", "?hard=true")),
    ("components/erp/asset/tabs/CategoriesTab.jsx",
     ("label: 'Aksi'", "edit-cat-btn-", "delete-cat-btn-", "hapusMaster", "/assets/categories/")),
])
def test_layar_master_punya_ubah_dan_hapus(rel, frags):
    src = fe(rel)
    for frag in frags:
        assert frag in src, (rel, frag)
    assert "window.confirm(" not in src and "<button" not in src


def test_layar_aksesoris_tidak_lagi_berjanji_palsu():
    src = fe("components/erp/AccessoryModule.jsx")
    assert "akan ditolak sistem" not in src



# ══ 10 Nov 2026 (keputusan owner): pemasok utama & daftar harga bukan "sudah dipakai" ══
def test_bahan_dengan_daftar_harga_tetap_terhapus_beserta_hargannya(bahan):
    mod, db = bahan
    db.rahaza_supplier_price_lists.docs.append({"id": "plx", "material_id": "m1", "supplier_id": "s9"})
    out = run(mod.deactivate_material("m1", REQ, hard=True))
    assert out["deleted"] is True and not any(m["id"] == "m1" for m in db.rahaza_materials.docs)
    assert not any(p.get("material_id") == "m1" for p in db.rahaza_supplier_price_lists.docs)


def test_supplier_pemasok_utama_dilepas_saat_dihapus(supplier):
    mod, db = supplier
    db.rahaza_materials.docs.append({"id": "mx", "code": "KN-X", "supplier_id": "s1", "supplier_name": "PT Benang Jaya"})
    out = run(mod.deactivate_supplier("s1", REQ, hard=True))
    assert out["deleted"] is True and db.rahaza_suppliers.docs == []
    mx = next(m for m in db.rahaza_materials.docs if m["id"] == "mx")
    assert mx["supplier_id"] == "" and mx["supplier_name"] == ""
