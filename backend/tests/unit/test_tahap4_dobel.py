"""Tahap 4 — pola P8 (2026-11-06): data referensi dobel & mesin/jalur dobel.

  1. Aturan "nama master setara" (`core.reference_dedup.ref_key`) + ejaan satuan (`core.uom.canonical_unit`).
  2. Migrasi `2026_11_07_gabung_data_referensi`: pilih yang dipertahankan, alihkan rujukan, nonaktifkan
     kembaran (tanpa hapus), pratinjau tidak menulis, idempoten; master bernilai hanya dilaporkan.
  3. Endpoint tambah/ubah master menolak nama setara; benih bawaan aman dijalankan bersamaan.
  4. Satuan: daftar resmi roll/pack (= data), rol/gulung/pak diterima lalu disimpan roll/pack.
  5. Mesin dobel: penyesuaian Viewer Stok lewat mesin Penyesuaian (kartu stok + jurnal); pembayaran
     nota penjualan langsung menulis `rahaza_ar_payments`; nota kredit lewat `post_credit_note`;
     kode aksesoris dicek di semua jenis material; potongan baru langsung berkategori master.
"""
import asyncio
import importlib.util
import inspect
import os
import sys
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
from pymongo.errors import DuplicateKeyError  # noqa: E402

from _fake_mongo import FakeCollection, FakeDB, FakeRequest  # noqa: E402
from core import reference_dedup as rd  # noqa: E402
from core.uom import canonical_unit  # noqa: E402

ADMIN = {"id": "u-adm", "name": "Admin", "role": "superadmin", "email": "a@x"}


def run(coro):
    return asyncio.run(coro)


def _load_migration():
    p = BACKEND / "scripts" / "migrations" / "2026_11_07_gabung_data_referensi.py"
    spec = importlib.util.spec_from_file_location("mig_gabung_ref", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _load_migration()


def _quiet(*_a, **_k):
    return None


# ═════════════════════════ 1. aturan nama ═════════════════════════
@pytest.mark.parametrize("a,b", [
    ("Peralatan IT", "peralatan  it"),
    ("Perabot & Mebel", "Mebel dan Perabot"),
    ("Lain-lain", "Lainnya"),
    ("Rework/Revisi", "Permak / Rework"),
    ("Set/Setelan", "One set"),
    ("Jacket", "Jaket"),
    ("Rol/Gulungan", "Roll"),
    ("operator_cuting", "Operator Cuting"),
])
def test_nama_setara(a, b):
    assert rd.ref_key(a) == rd.ref_key(b)


@pytest.mark.parametrize("a,b", [
    ("Benang", "Benang Jahit"),
    ("Kancing 22L", "Kancing 28L"),
    ("Gudang Lantai 1", "Gudang Lantai 2"),
    ("Jahit (CMT)", "Finishing"),
])
def test_nuansa_tidak_digabung(a, b):
    assert rd.ref_key(a) != rd.ref_key(b)


def test_kelas_kode_proses_dan_ejaan_satuan():
    assert rd.process_class("JAHIT") == rd.process_class("sewing") == "SEWING"
    assert rd.process_class("PERMAK") == "REWORK"
    assert rd.process_class("CUTTING") == "CUTTING"
    assert [canonical_unit(u) for u in ("rol", "Gulung", "ROLL", "pak", "Buah", "kg")] == \
        ["roll", "roll", "roll", "pack", "pcs", "kg"]


# ═════════════════════════ 2. migrasi ═════════════════════════
def _seed_db():
    db = FakeDB()
    db.dewi_asset_categories.docs = [
        {"id": "ac1", "code": "IT", "name": "Peralatan IT", "created_at": "2026-09-14T03:04:51.103"},
        {"id": "ac2", "code": "IT", "name": "Peralatan IT", "created_at": "2026-09-14T03:04:51.114"},
        {"id": "ac3", "code": "KD", "name": "Kendaraan", "created_at": "2026-09-14T03:04:51.103"},
    ]
    db.dewi_assets.docs = [{"id": "as1", "category_id": "ac2", "category_name": "Peralatan IT"}]
    db.rahaza_processes.docs = [
        {"id": "p-sew", "code": "SEWING", "name": "Jahit (CMT)", "active": True},
        {"id": "p-jht", "code": "JAHIT", "name": "Jahit / Sewing", "active": True},
        {"id": "p-rwk", "code": "REWORK", "name": "Rework/Revisi", "active": True},
        {"id": "p-pmk", "code": "PERMAK", "name": "Permak / Rework", "active": True},
        {"id": "p-cut", "code": "CUTTING", "name": "Cutting", "active": True},
    ]
    db.rahaza_wip_events.docs = [{"id": "w1", "process_id": "p-jht", "process_code": "JAHIT"}]
    db.rahaza_lines.docs = [{"id": f"ln{i}", "process_id": "p-sew"} for i in range(4)]  # SEWING lebih dirujuk
    db.rahaza_payroll_profiles.docs = [{"id": "pp1", "pcs_process_rates": [
        {"process_id": "p-jht", "process_code": "JAHIT", "rate": 1500},
        {"process_id": "p-cut", "process_code": "CUTTING", "rate": 300}]}]
    db.wh_unit_master.docs = [
        {"id": "u-rol", "code": "rol", "name": "Rol/Gulungan", "category": "roll", "is_base": True, "active": True},
        {"id": "u-glg", "code": "gulung", "name": "Gulung", "category": "roll", "active": True},
        {"id": "u-roll", "code": "roll", "name": "Roll", "category": "count", "is_base": False, "active": True,
         "notes": "ditambahkan otomatis: dipakai material (master_sync)"},
        {"id": "u-pak", "code": "pak", "name": "Pak", "category": "pack", "active": True},
        {"id": "u-pack", "code": "pack", "name": "Pack", "category": "count", "active": True,
         "notes": "ditambahkan otomatis: dipakai material (master_sync)"},
        {"id": "u-pcs", "code": "pcs", "name": "Pieces", "category": "count", "active": True},
    ]
    db.wh_unit_conversions.docs = [{"id": "cv1", "from_unit_id": "u-rol", "from_unit_code": "rol",
                                    "to_unit_id": "u-pcs", "to_unit_code": "pcs", "factor": 10}]
    db.rahaza_materials.docs = [
        {"id": "m1", "code": "BNG-1", "unit": "roll", "base_uom": "roll",
         "uoms": [{"code": "roll", "factor": 1, "is_base": True}]},
        {"id": "m2", "code": "LBL-1", "unit": "pcs", "base_uom": "pcs", "pack_unit": "pak", "purchase_uom": "pak",
         "uoms": [{"code": "pcs", "factor": 1, "is_base": True}, {"code": "pak", "factor": 100, "parent": "pcs"}]},
        {"id": "fg1", "code": "DA-1-BLK-S", "type": "fg", "category_id": "pc-set", "category": "Set/Setelan",
         "category_name": "Set/Setelan"},
    ]
    db.rahaza_product_categories.docs = [
        {"id": "pc-set", "code": "SET", "name": "Set/Setelan", "active": True},
        {"id": "pc-one", "code": "ONE_SET", "name": "One set", "active": True},
    ]
    db.rahaza_models.docs = [{"id": f"md{i}", "category_id": "pc-one", "category_name": "One set"}
                             for i in range(3)]
    db.dewi_rnd_styles.docs = [{"id": "st1", "category": "Set/Setelan"}]
    db.roles.docs = [{"id": "r1", "name": "Admin Aksesoris", "description": "Admin Aksesoris", "active": True},
                     {"id": "r2", "name": "admin_aksesoris", "description": "Admin Aksesoris", "active": True}]
    return db


def test_migrasi_pratinjau_tidak_menulis():
    db = _seed_db()
    before = {c: [dict(d) for d in db[c].docs] for c in list(db._cols)}
    out = run(MIG.run_all(db, apply=False, out=_quiet))
    assert out["groups"] == 6  # 1 kategori aset + 2 proses + 2 satuan + 1 kategori produk
    assert {c: db[c].docs for c in before} == before


def test_migrasi_gabung_alihkan_nonaktifkan_lalu_idempoten():
    db = _seed_db()
    out = run(MIG.run_all(db, apply=True, out=_quiet))
    cats = {d["id"]: d for d in db.dewi_asset_categories.docs}
    # aset: yang DIRUJUK menang (ac2, walau lebih baru); kembarannya nonaktif, tidak dihapus
    assert cats["ac2"].get("active") is not False and cats["ac1"]["active"] is False
    assert cats["ac1"]["duplicate_of"] == "ac2" and len(db.dewi_asset_categories.docs) == 3
    # proses: yang lebih dirujuk menang; rujukan id/kode + tarif borongan bersarang dialihkan
    procs = {d["code"]: d for d in db.rahaza_processes.docs}
    assert procs["JAHIT"]["active"] is False and procs["JAHIT"]["duplicate_of"] == "p-sew"
    assert procs["PERMAK"]["active"] is False and procs["REWORK"]["active"] is True
    assert db.rahaza_wip_events.docs[0]["process_id"] == "p-sew"
    assert db.rahaza_wip_events.docs[0]["process_code"] == "SEWING"
    rates = db.rahaza_payroll_profiles.docs[0]["pcs_process_rates"]
    assert rates[0] == {"process_id": "p-sew", "process_code": "SEWING", "rate": 1500}
    assert rates[1]["process_id"] == "p-cut"
    # satuan: ejaan resmi menang, mewarisi kategori benih; konversi & material dialihkan
    units = {d["code"]: d for d in db.wh_unit_master.docs}
    assert units["rol"]["active"] is False and units["gulung"]["active"] is False
    assert units["pak"]["active"] is False and units["roll"]["active"] is True
    assert units["roll"]["category"] == "roll" and units["roll"]["is_base"] is True
    assert db.wh_unit_conversions.docs[0]["from_unit_id"] == "u-roll"
    assert db.wh_unit_conversions.docs[0]["from_unit_code"] == "roll"
    m2 = next(d for d in db.rahaza_materials.docs if d["id"] == "m2")
    assert m2["pack_unit"] == "pack" and m2["purchase_uom"] == "pack"
    assert [r["code"] for r in m2["uoms"]] == ["pcs", "pack"]
    # kategori produk: yang paling dirujuk menang; id + nama di koleksi pemakai dialihkan
    pcs = {d["code"]: d for d in db.rahaza_product_categories.docs}
    assert pcs["SET"]["active"] is False and pcs["ONE_SET"]["active"] is True
    fg = next(d for d in db.rahaza_materials.docs if d["id"] == "fg1")
    assert fg["category_id"] == "pc-one" and fg["category_name"] == "One set" and fg["category"] == "One set"
    assert db.dewi_rnd_styles.docs[0]["category"] == "One set"
    # peran: hanya dilaporkan (akses) — tidak diubah
    assert all(r.get("active") is True for r in db.roles.docs)
    assert out["report_groups"] >= 1 and out["deactivated"] == 7
    again = run(MIG.run_all(db, apply=True, out=_quiet))
    assert again["groups"] == 0 and again["deactivated"] == 0 and again["repointed"] == 0


def test_pilih_yang_dipertahankan_murni():
    g = [{"id": "a", "code": "JAHIT", "created_at": "2026-01-01"},
         {"id": "b", "code": "SEWING", "created_at": "2026-02-01"}]
    assert MIG.choose_keeper(g, {}, seed={"SEWING"})["id"] == "b"           # seri → kode bawaan
    assert MIG.choose_keeper(g, {"a": 3}, seed={"SEWING"})["id"] == "a"     # dirujuk lebih banyak
    u = [{"id": "x", "code": "rol"}, {"id": "y", "code": "roll"}]
    assert MIG.choose_keeper(u, {"x": 99}, canonical_first=True)["id"] == "y"  # satuan: ejaan resmi


# ═════════════════════════ 3. benih & endpoint ═════════════════════════
class _UniqueIdCollection(FakeCollection):
    """Koleksi palsu yang menolak `_id` ganda (seperti indeks `_id` Mongo)."""

    async def insert_one(self, doc):
        if "_id" in doc and any(d.get("_id") == doc["_id"] for d in self.docs):
            raise DuplicateKeyError("dup _id")
        res = await super().insert_one(doc)  # cek + sisip atomik (seperti indeks `_id`)
        await asyncio.sleep(0)
        return res

    async def count_documents(self, q=None):
        n = await super().count_documents(q)
        await asyncio.sleep(0)  # beri giliran ke permintaan lain → keduanya melihat 0
        return n


def test_benih_kategori_aset_bersamaan_tidak_ganda():
    from routes.asset import _helpers as ah
    db = FakeDB()
    db._cols["dewi_asset_categories"] = _UniqueIdCollection("dewi_asset_categories")

    async def both():
        await asyncio.gather(ah._ensure_default_categories(db), ah._ensure_default_categories(db))
    run(both())
    codes = [d["code"] for d in db.dewi_asset_categories.docs]
    assert sorted(codes) == sorted(c["code"] for c in ah.DEFAULT_CATEGORIES)


@pytest.fixture
def patched(monkeypatch):
    db = FakeDB()

    async def auth(_req):
        return ADMIN

    async def noop(*_a, **_k):
        return None
    import routes.asset.categories as cats
    import routes.rahaza_inventory_materials as mats
    import routes.rahaza_product_categories as pcs
    import routes.wms_units as units
    import routes.rahaza_variants as var
    import routes.rahaza_master as master
    for mod in (cats, mats, pcs, units, var, master):
        monkeypatch.setattr(mod, "get_db", lambda: db)
        if hasattr(mod, "log_activity"):
            monkeypatch.setattr(mod, "log_activity", noop)
    monkeypatch.setattr(cats, "require_auth", auth)
    monkeypatch.setattr(units, "require_auth", auth)
    monkeypatch.setattr(mats, "_require_admin", auth)
    monkeypatch.setattr(var, "_require_admin", auth)
    monkeypatch.setattr(master, "_require_admin", auth)
    monkeypatch.setattr(pcs, "_require_internal", auth)
    return db


def _status(coro):
    with pytest.raises(HTTPException) as e:
        run(coro)
    return e.value.status_code, e.value.detail


def test_kategori_aset_nama_setara_ditolak_dan_daftar_tanpa_kembaran(patched):
    import routes.asset.categories as cats
    patched.dewi_asset_categories.docs = [
        {"id": "a1", "code": "PM", "name": "Perabot & Mebel"},
        {"id": "a2", "code": "PM", "name": "Perabot & Mebel", "active": False, "duplicate_of": "a1"}]
    code, msg = _status(cats.create_category(FakeRequest({"name": "mebel dan perabot", "code": "MB"})))
    assert code == 409 and "Perabot & Mebel" in msg
    code, _ = _status(cats.create_category(FakeRequest({"name": "Gudang", "code": "PM"})))
    assert code == 409
    assert [c["id"] for c in run(cats.list_categories(FakeRequest()))] == ["a1"]


def test_kategori_material_dan_produk_nama_setara_ditolak(patched):
    import routes.rahaza_inventory_materials as mats
    import routes.rahaza_product_categories as pcs
    patched.rahaza_material_categories.docs = [{"id": "c1", "code": "ACCESSORY", "name": "Aksesoris", "active": True}]
    code, _ = _status(mats.create_material_category(FakeRequest({"name": "Accessories", "code": "ACC2"})))
    assert code == 409
    patched.rahaza_product_categories.docs = [{"id": "p1", "code": "ONE_SET", "name": "One set", "active": True,
                                               "sku_prefix": "ONE"}]
    code, msg = _status(pcs.create_category(pcs.CategoryIn(name="Set/Setelan", code="SET", sku_prefix="SET"),
                                            FakeRequest()))
    assert code == 409 and "One set" in msg


def test_satuan_ejaan_lain_ditolak_dan_benih_resmi(patched):
    import routes.wms_units as units
    patched.wh_unit_master.docs = [{"id": "u1", "code": "roll", "name": "Roll", "active": True}]
    for code, name in (("rol", "Rol baru"), ("GULUNG", "Gulung")):
        st, _ = _status(units.create_unit(units.UnitIn(code=code, name=name, category="roll", symbol=code),
                                          FakeRequest()))
        assert st == 400
    seed_codes = {u["code"] for u in units.SEED_UNITS}
    assert {"roll", "pack"} <= seed_codes and not ({"rol", "gulung", "pak"} & seed_codes)
    assert "ensure_unit_master" in inspect.getsource(units.seed_units)


def test_warna_nama_setara_ditolak(patched):
    import routes.rahaza_variants as var
    patched.rahaza_colors.docs = [{"id": "k1", "code": "PTH", "name": "Putih", "active": True}]
    code, msg = _status(var.create_color(FakeRequest({"name": "White", "code": "WHT"})))
    assert code == 409 and "Putih" in msg


def test_proses_ganti_nama_ke_kembaran_ditolak(patched):
    import routes.rahaza_master as master
    patched.rahaza_processes.docs = [{"id": "p1", "code": "REWORK", "name": "Rework/Revisi", "active": True},
                                     {"id": "p2", "code": "QC", "name": "QC Final", "active": True}]
    code, _ = _status(master.update_process("p2", FakeRequest({"name": "Permak"})))
    assert code == 409
    out = run(master.update_process("p1", FakeRequest({"name": "Rework / Revisi"})))  # diri sendiri boleh
    assert out["name"] == "Rework / Revisi"


def test_impor_data_transfer_menolak_kembaran_dan_baris_tergabung():
    import routes.data_transfer as dt
    db = FakeDB()
    db.rahaza_processes.docs = [{"id": "p1", "code": "SEWING", "name": "Jahit (CMT)", "active": True}]
    msg = run(dt._ref_name_clash(db, "rahaza_processes", {"code": "JAHIT", "name": "Jahit / Sewing"}, {}))
    assert msg and "SEWING" in msg
    seen = {}
    assert run(dt._ref_name_clash(db, "rahaza_sizes", {"code": "AS", "name": "All Size"}, seen)) is None
    assert "berkas ini" in run(dt._ref_name_clash(db, "rahaza_sizes", {"code": "AS2", "name": "ALL  SIZE"}, seen))
    note = dt._merged_row_note("rahaza_processes", {"code": "JAHIT", "duplicate_of": "p1",
                                                    "duplicate_of_code": "SEWING"})
    assert "SEWING" in note
    assert dt._merged_row_note("rahaza_materials", {"duplicate_of": "x"}) is None


def test_shift_hr_dan_kategori_klaim_dan_peran(monkeypatch):
    from services import hr_shift_service as hs
    db = FakeDB()
    db.rahaza_shifts.docs = [{"id": "s1", "code": "REG", "name": "Reguler 08:00–16:00", "active": True}]
    with pytest.raises(ValueError):
        run(hs.create_shift(db, {"shift_code": "PAGI", "shift_name": "reguler 08:00-16:00",
                                 "start_time": "08:00", "end_time": "16:00"}))
    # kategori klaim: nama berisi tanda kurung tidak lagi membuat kueri regex galat
    import routes.employee_expense_category_master as eec
    monkeypatch.setattr(eec, "get_db", lambda: db)

    async def noop(*_a, **_k):
        return None
    monkeypatch.setattr(eec, "log_activity", noop)
    user = {"id": "u1", "role": "finance", "name": "Fin", "email": "f@x"}
    run(eec.create_master_category(eec.CategoryCreate(name="Bensin (motor)"), user))
    with pytest.raises(HTTPException) as e:
        run(eec.create_master_category(eec.CategoryCreate(name="bensin  motor"), user))
    assert e.value.status_code == 400
    # peran: nama setara ditolak
    import routes.admin as adm
    db.roles.docs = [{"id": "r1", "name": "operator_cuting", "active": True}]

    async def auth(_r):
        return ADMIN
    monkeypatch.setattr(adm, "require_auth", auth)
    monkeypatch.setattr(adm, "get_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        run(adm.create_role(FakeRequest({"name": "Operator Cuting"})))
    assert e.value.status_code == 400 and "operator_cuting" in e.value.detail


# ═════════════════════════ 4. satuan ═════════════════════════
def test_material_dan_aksesoris_satuan_resmi(monkeypatch):
    import routes.dewi_accessories_items as items
    from routes.rahaza_inventory_shared import MATERIAL_UNITS
    assert "roll" in MATERIAL_UNITS and "pack" in MATERIAL_UNITS
    assert not ({"rol", "gulung", "pak"} & set(MATERIAL_UNITS))
    db = FakeDB()

    async def auth(_r):
        return ADMIN
    monkeypatch.setattr(items, "require_auth", auth)
    monkeypatch.setattr(items, "get_db", lambda: db)
    db.rahaza_materials.docs = [{"id": "f1", "code": "KN-1", "name": "Kain", "type": "fabric", "active": True}]
    code, msg = _status(items.create_item(FakeRequest({"code": "KN-1", "name": "Kancing", "unit": "pcs"})))
    assert code == 409 and "Kain" in msg  # kode milik kain → 409 (dulu lolos lalu 500 di indeks unik)
    for mod in ("dewi_accessories_dashboard", "dewi_accessories_loans", "dewi_accessories_purchase",
                "dewi_accessories_requests", "dewi_accessories_stock"):
        src = (BACKEND / "routes" / f"{mod}.py").read_text(encoding="utf-8")
        assert "def _normalize_unit" not in src and '"roll": "rol"' not in src


# ═════════════════════════ 5. mesin dobel ═════════════════════════
def test_penyesuaian_viewer_stok_lewat_mesin_penyesuaian(monkeypatch):
    import routes.unified_inventory as ui
    import routes.rahaza_inventory_stock as ris
    from core import location_resolver, stock_service
    db = FakeDB()
    db.rahaza_material_stock.docs = [{"id": "s1", "material_id": "m1", "location_id": "L1", "qty": 10.0}]
    calls = {}

    async def auth(_r):
        return ADMIN

    async def loc_ok(_db, _loc):
        return True

    async def fake_issue(mid, loc, qty, **kw):
        calls["issue"] = (mid, loc, qty, kw.get("ref"))
        db.rahaza_material_stock.docs[0]["qty"] -= qty

    async def fake_post(_db, mv, _user):
        calls["post"] = mv["type"]
        return {"ok": True, "je_number": "JE-1"}

    async def noop(*_a, **_k):
        return None
    monkeypatch.setattr(ui, "_require_admin", auth)
    monkeypatch.setattr(ui, "get_db", lambda: db)
    monkeypatch.setattr(ui, "log_activity", noop)
    monkeypatch.setattr(location_resolver, "location_exists", loc_ok)
    monkeypatch.setattr(stock_service, "issue", fake_issue)
    monkeypatch.setattr(ris, "post_inventory_adjust", fake_post)
    out = run(ui.adjust_stock(ui.StockAdjustIn(material_id="m1", adjustment_type="damage", qty_delta=3,
                                               reason="rusak tikus"), FakeRequest()))
    assert calls["issue"][:3] == ("m1", "L1", 3.0) and calls["post"] == "adjust"
    assert out["qty_before"] == 10.0 and out["qty_after"] == 7.0 and out["delta"] == -3.0
    mv = db.rahaza_material_movements.docs[0]
    assert mv["type"] == "adjust" and mv["source_module"] == "unified-inventory"
    # material di dua lokasi tanpa pilihan lokasi → ditolak, bukan menebak baris pertama
    db.rahaza_material_stock.docs.append({"id": "s2", "material_id": "m1", "location_id": "L2", "qty": 5.0})
    code, _ = _status(ui.adjust_stock(ui.StockAdjustIn(material_id="m1", adjustment_type="correction",
                                                       qty_delta=1, reason="koreksi"), FakeRequest()))
    assert code == 400


def test_pembayaran_nota_penjualan_langsung_tercatat_di_riwayat(monkeypatch):
    import routes.sales_direct as sd
    import routes.rahaza_posting as rp
    db = FakeDB()
    db.rahaza_cash_accounts.docs = [{"id": "k1", "name": "Kas"}]
    db.rahaza_ar_invoices.docs = [{"id": "inv1", "invoice_number": "INV-1", "total_amount": 100000,
                                   "gl_je_id": "je0", "status": "unpaid"}]

    async def foau(q, _pipeline, return_document=None):
        doc = db.rahaza_ar_invoices.docs[0]
        doc["paid_amount"] = 100000
        doc["status"] = "paid"
        return dict(doc)
    db.rahaza_ar_invoices.find_one_and_update = foau

    async def fake_pay(*_a, **_k):
        return {"ok": True, "je_id": "je9", "je_number": "JE-9"}

    async def fake_inv(*_a, **_k):
        return {"ok": True}
    monkeypatch.setattr(rp, "post_ar_payment", fake_pay)
    monkeypatch.setattr(rp, "post_ar_invoice", fake_inv)
    res = run(sd._apply_ar_payment(db, "inv1", 100000.0, "k1", "2026-11-06", ADMIN, notes="lunas"))
    pays = db.rahaza_ar_payments.docs
    assert len(pays) == 1 and pays[0]["invoice_id"] == "inv1" and pays[0]["amount"] == 100000
    assert pays[0]["gl_je_number"] == "JE-9" and res["payment_id"] == pays[0]["id"]


def test_nota_kredit_penjualan_langsung_pakai_mesin_bersama():
    import routes.sales_direct as sd
    src = inspect.getsource(sd)
    assert "post_credit_note(db, cn, user)" in src
    assert 'lines[0]["debit"] = total' not in src  # PPN tidak lagi dibukukan diam-diam ke retur


def test_potongan_baru_langsung_berkategori_master():
    from core import cut_panel_master as cpm
    db = FakeDB()
    db.rahaza_material_categories.docs = [{"id": "cat-cut", "code": "CUT_PANEL", "name": "Potongan / Kain Pola",
                                           "active": True}]
    doc, created = run(cpm.ensure_panel(db, model={"id": "md1", "code": "DA-1", "name": "Mela"},
                                        color_code="BLK", color_name="Hitam", size_code="S"))
    assert created and doc["category_id"] == "cat-cut" and doc["category"] == "cat-cut"
    assert db.rahaza_materials.docs[0]["category_code"] == "CUT_PANEL"


def test_hari_kerja_kalender_produksi_ikut_aturan_payroll(monkeypatch):
    import routes.rahaza_production_calendar as cal
    db = FakeDB()
    db.rahaza_production_calendar.docs = [{"id": "h1", "date": "2026-11-04", "type": "holiday"}]

    async def auth(_r):
        return ADMIN
    monkeypatch.setattr(cal, "require_auth", auth)
    monkeypatch.setattr(cal, "get_db", lambda: db)
    week = dict(from_date="2026-11-02", to_date="2026-11-08")  # Senin–Minggu, Rabu libur nasional
    out = run(cal.get_working_days(FakeRequest(), include_saturday=None, **week))
    assert out["working_days"] == 5 and out["work_days_per_week"] == 6 and out["include_saturday"] is True
    db.rahaza_payroll_settings.docs = [{"key": "work_calendar", "work_days_per_week": 5}]
    assert run(cal.get_working_days(FakeRequest(), include_saturday=None, **week))["working_days"] == 4
    assert run(cal.get_working_days(FakeRequest(), include_saturday=True, **week))["working_days"] == 5


def test_hutang_dasbor_pengadaan_pakai_rumus_keuangan():
    import routes.procurement_dashboard as pdash
    src = inspect.getsource(pdash.procurement_overview)
    assert "open_payable_rows(db, include_cmt=False)" in src
    assert '"partially_paid"' not in src and "$total_amount" not in src
