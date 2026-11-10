"""Master Produk & RnD bisa diubah & dihapus (permintaan owner 10 Nov 2026) — hermetik (FakeDB, tanpa server).

Kata owner: "… pastikan table table master data bisa dihapus". Pola bersama: `core.hapus_master` (409 + kalimat
"sudah dipakai di …") dan layar `lib/hapusMaster` (dialog kedua menawarkan Nonaktifkan/Arsipkan).

Yang dikunci per master — belum dipakai → terhapus permanen (+ konfigurasi miliknya sendiri); sudah dipakai → 409
dengan label pemakaian; tanpa `hard` → perilaku lama (nonaktifkan); gerbang peran jalur hapus permanen (jalur
nonaktifkan TIDAK diperketat); layar punya Ubah + Hapus yang memanggil `hapusMaster` / `?hard=true`:
  * model produk (ikut terhapus: varian, barang jadi & potongan stok 0, BOM, SOP, costing model);
  * varian / SKU (ikut terhapus: barang jadi miliknya); dulu tombol "Hapus varian" hanya menonaktifkan;
  * warna (dulu hanya nonaktif; rujukan lewat kode/nama dihitung bila kodenya tidak kembar);
  * ukuran, kategori produk (tanpa saringan aktif), versi BOM (dasar HPP = dipakai);
  * style, varian, dan bahan riset R&D — dulu terhapus permanen TANPA cek, kini 409 bila sudah dipakai.
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
PERAN_RND = {"id": "u-rnd", "name": "Peran Buatan Owner", "role": "desainer_custom", "_permissions": ["rnd.manage"]}
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


def _status(coro):
    with pytest.raises(HTTPException) as e:
        run(coro)
    return e.value.status_code


# ══════════════════════════════ model & varian ══════════════════════════════
@pytest.fixture
def produk(monkeypatch):
    import routes.rahaza_production as rp
    import routes.rahaza_variants as rv
    db = fm.FakeDB()
    db.rahaza_models.docs = [{"id": "m1", "code": "VST-0001", "name": "Vest Uji", "active": True},
                             {"id": "m2", "code": "VST-0002", "name": "Vest Lain", "active": True}]
    db.rahaza_model_variants.docs = [
        {"id": "v1", "model_id": "m1", "sku": "VST-0001-HTM-S", "color_id": "w1", "size_id": "s1", "active": True},
        {"id": "v2", "model_id": "m1", "sku": "VST-0001-HTM-M", "color_id": "w1", "size_id": "s2", "active": True},
        {"id": "v9", "model_id": "m2", "sku": "VST-0002-HTM-S", "color_id": "w1", "size_id": "s1", "active": True},
    ]
    db.rahaza_materials.docs = [
        {"id": "f1", "type": "fg", "code": "VST-0001-HTM-S", "model_id": "m1", "variant_id": "v1"},
        {"id": "f2", "type": "fg", "code": "VST-0001-HTM-M", "model_id": "m1", "variant_id": "v2"},
        {"id": "p1", "type": "fabric", "is_cut_panel": True, "code": "PT-VST1-HTM-S", "model_id": "m1"},
        {"id": "f9", "type": "fg", "code": "VST-0002-HTM-S", "model_id": "m2", "variant_id": "v9"},
    ]
    db.rahaza_material_stock.docs = [{"id": "st1", "material_id": "f1", "qty": 0}]
    db.rahaza_boms.docs = [{"id": "b1", "model_id": "m1", "size_id": "s1", "color_code": "HTM", "active": True},
                           {"id": "b9", "model_id": "m2", "size_id": "s1", "color_code": "HTM", "active": True}]
    db.rahaza_model_process_sop.docs = [{"id": "sop1", "model_id": "m1"}]
    db.rahaza_model_costing.docs = [{"id": "c1", "model_id": "m1"}]
    for mod in (rp, rv):
        monkeypatch.setattr(mod, "get_db", lambda: db)
        monkeypatch.setattr(mod, "log_activity", _noop)
        monkeypatch.setattr(mod, "_require_admin", _kembalikan(ADMIN))
    return rp, rv, db


def test_model_belum_dipakai_dihapus_beserta_konfigurasinya(produk):
    rp, _rv, db = produk
    out = run(rp.deactivate_model("m1", REQ, hard=True))
    assert out["deleted"] is True and out["removed"] == {"barang": 3, "varian": 2, "bom": 1, "sop": 1, "costing": 1}
    assert [m["id"] for m in db.rahaza_models.docs] == ["m2"]
    assert [v["id"] for v in db.rahaza_model_variants.docs] == ["v9"]
    assert [m["id"] for m in db.rahaza_materials.docs] == ["f9"]          # barang jadi & potongan m1 ikut hilang
    assert [b["id"] for b in db.rahaza_boms.docs] == ["b9"]
    assert db.rahaza_material_stock.docs == [] and db.rahaza_model_process_sop.docs == []
    assert db.rahaza_model_costing.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("po_items", {"id": "x", "model_id": "m1"}, "baris PO produksi"),
    ("po_items", {"id": "x", "rahaza_variant_id": "v2"}, "baris PO produksi"),          # varian model ini
    ("po_items", {"id": "x", "sku": "VST-0001-HTM-M"}, "baris PO produksi"),            # baris lama: teks SKU saja
    ("rahaza_orders", {"id": "x", "items": [{"model_id": "mX"}, {"model_id": "m1"}]}, "order produksi"),
    ("cutting_orders", {"id": "x", "model_id": "m1"}, "order cutting"),
    ("rahaza_wip_events", {"id": "x", "model_id": "m1"}, "catatan WIP"),
    ("marketing_catalog_items", {"id": "x", "fg_material_id": "f1"}, "item katalog marketing"),
    ("marketing_orders", {"id": "x", "items": [{"variant_id": "v1"}]}, "pesanan marketing"),
    ("marketing_sku_bridge", {"id": "x", "variant_id": "v2"}, "pemetaan SKU marketplace"),
    ("rahaza_stock_ledger", {"id": "x", "material_id": "p1"}, "kartu stok"),            # potongan milik model
    ("product_cost_snapshots", {"id": "x", "model_id": "m1"}, "riwayat penerapan HPP"),
    ("dewi_rnd_styles", {"id": "x", "promoted_to_model_id": "m1"}, "style R&D asal produk"),
])
def test_model_sudah_dipakai_ditolak_409(produk, koleksi, doc, label):
    rp, _rv, db = produk
    getattr(db, koleksi).docs.append(doc)
    _tolak(rp.deactivate_model("m1", REQ, hard=True), label, 'Model "VST-0001 Vest Uji"', "Nonaktifkan")
    assert len(db.rahaza_models.docs) == 2 and len(db.rahaza_model_variants.docs) == 3
    assert len(db.rahaza_materials.docs) == 4 and len(db.rahaza_boms.docs) == 2


def test_model_stok_bersaldo_ditolak(produk):
    rp, _rv, db = produk
    db.rahaza_material_stock.docs = [{"id": "st1", "material_id": "f2", "qty": 7}]
    _tolak(rp.deactivate_model("m1", REQ, hard=True), "lokasi stok bersaldo")
    assert len(db.rahaza_models.docs) == 2


def test_model_tanpa_hard_tetap_nonaktifkan(produk):
    rp, _rv, db = produk
    out = run(rp.deactivate_model("m1", REQ, hard=False))
    assert out["status"] == "deactivated"
    assert db.rahaza_models.docs[0]["active"] is False and len(db.rahaza_model_variants.docs) == 3


def test_varian_belum_dipakai_dihapus_beserta_barang_jadi(produk):
    _rp, rv, db = produk
    out = run(rv.deactivate_variant("v1", REQ, hard=True))
    assert out["deleted"] is True and out["fg_deleted"] == 1
    assert [v["id"] for v in db.rahaza_model_variants.docs] == ["v2", "v9"]
    assert {m["id"] for m in db.rahaza_materials.docs} == {"f2", "p1", "f9"}
    assert db.rahaza_material_stock.docs == []                     # baris stok bersaldo 0 milik f1 ikut hilang
    assert len(db.rahaza_boms.docs) == 2                           # BOM per model-ukuran-warna tidak disentuh


@pytest.mark.parametrize("koleksi,doc,label", [
    ("po_items", {"id": "x", "rahaza_variant_id": "v1"}, "baris PO produksi"),
    ("production_job_items", {"id": "x", "rahaza_variant_id": "v1"}, "job produksi"),
    ("cutting_orders", {"id": "x", "variant_id": "v1"}, "order cutting"),
    ("marketing_catalog_items", {"id": "x", "variant_sku": "VST-0001-HTM-S"}, "item katalog marketing"),
    ("wh_returns", {"id": "x", "material_id": "f1"}, "retur gudang"),
    ("sales_direct_notes", {"id": "x", "items": [{"material_id": "f1"}]}, "nota penjualan langsung"),
    ("rahaza_fg_movements", {"id": "x", "material_id": "f1"}, "mutasi barang jadi"),
    ("dewi_rnd_variants", {"id": "x", "sizes": [{"size": "S", "variant_id": "v1"}]}, "varian R&D asal SKU"),
])
def test_varian_sudah_dipakai_ditolak_409(produk, koleksi, doc, label):
    _rp, rv, db = produk
    getattr(db, koleksi).docs.append(doc)
    _tolak(rv.deactivate_variant("v1", REQ, hard=True), label, 'Varian "VST-0001-HTM-S"')
    assert len(db.rahaza_model_variants.docs) == 3 and len(db.rahaza_materials.docs) == 4


def test_varian_tanpa_hard_tetap_nonaktifkan(produk):
    _rp, rv, db = produk
    out = run(rv.deactivate_variant("v1", REQ, hard=False))
    assert out["status"] == "deactivated" and db.rahaza_model_variants.docs[0]["active"] is False
    assert len(db.rahaza_materials.docs) == 4


def test_pemakaian_varian_dipakai_model_lain_tidak_menghalangi(produk):
    """PO milik model LAIN tidak menghalangi model ini dihapus."""
    rp, _rv, db = produk
    db.po_items.docs = [{"id": "x", "model_id": "m2", "rahaza_variant_id": "v9", "sku": "VST-0002-HTM-S"}]
    assert run(rp.deactivate_model("m1", REQ, hard=True))["deleted"] is True


# ══════════════════════════════ warna ══════════════════════════════
@pytest.fixture
def warna(monkeypatch):
    import routes.rahaza_variants as rv
    db = fm.FakeDB()
    db.rahaza_colors.docs = [{"id": "w1", "code": "MRN", "name": "Maroon", "active": True},
                             {"id": "w2", "code": "HTM", "name": "Hitam", "active": True}]
    monkeypatch.setattr(rv, "get_db", lambda: db)
    monkeypatch.setattr(rv, "log_activity", _noop)
    monkeypatch.setattr(rv, "_require_admin", _kembalikan(ADMIN))
    return rv, db


def test_warna_belum_dipakai_dihapus(warna):
    rv, db = warna
    db.rahaza_boms.docs = [{"id": "b1", "color_code": "HTM"}]          # milik warna lain
    assert run(rv.deactivate_color("w1", REQ, hard=True))["deleted"] is True
    assert [c["id"] for c in db.rahaza_colors.docs] == ["w2"]


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_model_variants", {"id": "x", "color_id": "w1", "active": False}, "varian produk"),
    ("rahaza_boms", {"id": "x", "color_code": "MRN"}, "BOM"),
    ("po_items", {"id": "x", "color_code": "MRN"}, "baris PO produksi"),
    ("dewi_rnd_tech_packs", {"id": "x", "colorways": [{"color_id": "w1"}]}, "tech pack"),
    ("dewi_rnd_materials", {"id": "x", "colors": [{"color_id": "w1"}]}, "riset material"),
    ("dewi_maklon_buyer_catalog", {"id": "x", "color_options": ["Maroon"]}, "artikel katalog maklon"),
])
def test_warna_sudah_dipakai_ditolak_409(warna, koleksi, doc, label):
    rv, db = warna
    getattr(db, koleksi).docs.append(doc)
    _tolak(rv.deactivate_color("w1", REQ, hard=True), label, 'Warna "Maroon (MRN)"')
    assert len(db.rahaza_colors.docs) == 2


def test_warna_kode_kembar_rujukan_kode_milik_kembarannya(warna):
    rv, db = warna
    db.rahaza_colors.docs.append({"id": "w3", "code": "MRN", "name": "Maroon Tua", "active": False})
    db.rahaza_boms.docs = [{"id": "b1", "color_code": "MRN"}]
    assert run(rv.deactivate_color("w3", REQ, hard=True))["deleted"] is True


def test_warna_tanpa_hard_perilaku_lama(warna):
    rv, db = warna
    db.rahaza_model_variants.docs = [{"id": "x", "color_id": "w1", "active": True}]
    assert _status(rv.deactivate_color("w1", REQ, hard=False)) == 400    # guard lama (varian aktif) tetap
    db.rahaza_model_variants.docs = []
    assert run(rv.deactivate_color("w1", REQ, hard=False))["status"] == "deactivated"
    assert db.rahaza_colors.docs[0]["active"] is False


# ══════════════════════════════ ukuran ══════════════════════════════
@pytest.fixture
def ukuran(monkeypatch):
    import routes.rahaza_production as rp
    db = fm.FakeDB()
    db.rahaza_sizes.docs = [{"id": "s1", "code": "XXL", "name": "XXL", "active": True}]
    monkeypatch.setattr(rp, "get_db", lambda: db)
    monkeypatch.setattr(rp, "log_activity", _noop)
    monkeypatch.setattr(rp, "_require_admin", _kembalikan(ADMIN))
    return rp, db


def test_ukuran_belum_dipakai_dihapus(ukuran):
    rp, db = ukuran
    assert run(rp.deactivate_size("s1", REQ, hard=True))["deleted"] is True
    assert db.rahaza_sizes.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_model_variants", {"id": "x", "size_id": "s1"}, "varian produk"),
    ("rahaza_boms", {"id": "x", "size_id": "s1"}, "BOM"),
    ("rahaza_orders", {"id": "x", "items": [{"size_id": "s1"}]}, "order produksi"),
    ("rahaza_models", {"id": "x", "hpp_bom_by_size": {"s1": 12000}}, "HPP per ukuran produk"),
    ("product_cost_snapshots", {"id": "x", "applied_sizes": [{"size_id": "s1"}]}, "riwayat penerapan HPP"),
    ("dewi_maklon_buyer_catalog", {"id": "x", "variants": [{"size": "XXL"}]}, "artikel katalog maklon"),
])
def test_ukuran_sudah_dipakai_ditolak_409(ukuran, koleksi, doc, label):
    rp, db = ukuran
    getattr(db, koleksi).docs.append(doc)
    _tolak(rp.deactivate_size("s1", REQ, hard=True), label, 'Ukuran "XXL"')
    assert len(db.rahaza_sizes.docs) == 1


def test_ukuran_tanpa_hard_tetap_nonaktifkan(ukuran):
    rp, db = ukuran
    assert run(rp.deactivate_size("s1", REQ, hard=False)) == {"status": "deactivated"}
    assert db.rahaza_sizes.docs[0]["active"] is False


# ══════════════════════════════ kategori produk ══════════════════════════════
@pytest.fixture
def kategori(monkeypatch):
    import routes.rahaza_product_categories as pc
    db = fm.FakeDB()
    db.rahaza_product_categories.docs = [{"id": "k1", "code": "VEST", "name": "Vest", "sku_prefix": "VST",
                                          "active": True}]
    monkeypatch.setattr(pc, "get_db", lambda: db)
    monkeypatch.setattr(pc, "log_activity", _noop)
    monkeypatch.setattr(pc, "_require_internal", _kembalikan(ADMIN))
    return pc, db


def test_kategori_belum_dipakai_dihapus(kategori):
    pc, db = kategori
    assert run(pc.deactivate_category("k1", REQ, hard=True))["deleted"] is True
    assert db.rahaza_product_categories.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_models", {"id": "x", "category_id": "k1", "active": False, "status": "inactive"}, "produk"),
    ("rahaza_materials", {"id": "x", "type": "fg", "category_id": "k1"}, "barang jadi"),
    ("marketing_catalog_items", {"id": "x", "category_id": "k1", "is_active": False}, "item katalog marketing"),
])
def test_kategori_dipakai_walau_nonaktif_ditolak_409(kategori, koleksi, doc, label):
    pc, db = kategori
    getattr(db, koleksi).docs.append(doc)
    _tolak(pc.deactivate_category("k1", REQ, hard=True), label, 'Kategori "Vest"')
    assert len(db.rahaza_product_categories.docs) == 1


def test_kategori_tanpa_hard_perilaku_lama(kategori):
    pc, db = kategori
    db.rahaza_models.docs = [{"id": "x", "category_id": "k1", "active": False, "status": "inactive"}]
    out = run(pc.deactivate_category("k1", REQ, hard=False))   # produk nonaktif tidak menghalangi NONAKTIFKAN
    assert out["status"] == "deactivated" and db.rahaza_product_categories.docs[0]["active"] is False


# ══════════════════════════════ BOM ══════════════════════════════
@pytest.fixture
def bom(monkeypatch):
    import routes.rahaza_bom as rb
    db = fm.FakeDB()
    db.rahaza_models.docs = [{"id": "m1", "code": "VST-0001"}]
    db.rahaza_sizes.docs = [{"id": "s1", "code": "M"}]
    db.rahaza_boms.docs = [{"id": "b1", "model_id": "m1", "size_id": "s1", "color_code": "HTM", "version": 2,
                            "active": True, "is_active": True, "materials": []},
                           {"id": "b0", "model_id": "m1", "size_id": "s1", "color_code": "HTM", "version": 1,
                            "active": True, "is_active": False, "materials": []}]
    monkeypatch.setattr(rb, "get_db", lambda: db)
    monkeypatch.setattr(rb, "log_activity", _noop)
    monkeypatch.setattr(rb, "_require_admin", _kembalikan(ADMIN))
    return rb, db


def test_bom_belum_dasar_hpp_dihapus_versi_lain_utuh(bom):
    rb, db = bom
    assert run(rb.delete_bom("b1", REQ, hard=True))["deleted"] is True
    assert [b["id"] for b in db.rahaza_boms.docs] == ["b0"]


@pytest.mark.parametrize("koleksi,doc,label", [
    ("rahaza_materials", {"id": "f1", "type": "fg", "hpp_breakdown": {"bom_id": "b1"}}, "HPP barang jadi"),
    ("product_cost_snapshots", {"id": "x", "applied_sizes": [{"size_id": "s1", "breakdown": {"bom_id": "b1"}}]},
     "riwayat penerapan HPP"),
])
def test_bom_dasar_hpp_ditolak_409(bom, koleksi, doc, label):
    rb, db = bom
    getattr(db, koleksi).docs.append(doc)
    _tolak(rb.delete_bom("b1", REQ, hard=True), label, 'BOM "VST-0001 M HTM v2"')
    assert len(db.rahaza_boms.docs) == 2


def test_bom_tanpa_hard_tetap_nonaktifkan(bom):
    rb, db = bom
    assert run(rb.delete_bom("b1", REQ, hard=False)) == {"status": "deactivated"}
    assert db.rahaza_boms.docs[0]["active"] is False and len(db.rahaza_boms.docs) == 2


# ══════════════════════════════ gerbang peran (jalur hapus permanen saja) ══════════════════════════════
def _panggil_hard(nama, mod):
    return {
        "model": lambda: mod.deactivate_model("m1", REQ, hard=True),
        "varian": lambda: mod.deactivate_variant("v1", REQ, hard=True),
        "warna": lambda: mod.deactivate_color("w1", REQ, hard=True),
        "ukuran": lambda: mod.deactivate_size("s1", REQ, hard=True),
        "kategori": lambda: mod.deactivate_category("k1", REQ, hard=True),
        "bom": lambda: mod.delete_bom("b1", REQ, hard=True),
    }[nama]()


@pytest.mark.parametrize("nama,modname,guard,koleksi,doc", [
    ("model", "routes.rahaza_production", "_require_admin", "rahaza_models", {"id": "m1", "code": "A"}),
    ("varian", "routes.rahaza_variants", "_require_admin", "rahaza_model_variants", {"id": "v1", "sku": "A"}),
    ("warna", "routes.rahaza_variants", "_require_admin", "rahaza_colors", {"id": "w1", "code": "A", "name": "A"}),
    ("ukuran", "routes.rahaza_production", "_require_admin", "rahaza_sizes", {"id": "s1", "code": "A"}),
    ("kategori", "routes.rahaza_product_categories", "_require_internal", "rahaza_product_categories",
     {"id": "k1", "name": "A"}),
    ("bom", "routes.rahaza_bom", "_require_admin", "rahaza_boms", {"id": "b1", "model_id": "m1"}),
])
def test_hapus_permanen_dijaga_peran(monkeypatch, nama, modname, guard, koleksi, doc):
    import importlib
    mod = importlib.import_module(modname)
    db = fm.FakeDB()
    getattr(db, koleksi).docs = [dict(doc)]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    monkeypatch.setattr(mod, guard, _kembalikan(STAF))
    assert _status(_panggil_hard(nama, mod)) == 403
    assert len(getattr(db, koleksi).docs) == 1
    # peran buatan owner yang punya izin R&D boleh
    monkeypatch.setattr(mod, guard, _kembalikan(PERAN_RND))
    run(_panggil_hard(nama, mod))
    assert getattr(db, koleksi).docs == []


def test_jalur_nonaktifkan_tidak_diperketat(monkeypatch):
    import routes.rahaza_production as rp
    db = fm.FakeDB()
    db.rahaza_sizes.docs = [{"id": "s1", "code": "XXL", "active": True}]
    monkeypatch.setattr(rp, "get_db", lambda: db)
    monkeypatch.setattr(rp, "_require_admin", _kembalikan(STAF))
    assert run(rp.deactivate_size("s1", REQ)) == {"status": "deactivated"}   # tanpa `hard` = perilaku lama


# ══════════════════════════════ R&D: style ══════════════════════════════
@pytest.fixture
def style(monkeypatch):
    import routes.dewi_rnd_styles as st
    db = fm.FakeDB()
    db.dewi_rnd_styles.docs = [{"id": "st1", "style_code": "RND-01", "style_name": "Kemeja Uji", "status": "draft",
                                "promoted_to_model_id": None}]
    db.dewi_rnd_variants.docs = [{"id": "rv1", "style_id": "st1", "color": "Hitam",
                                  "sizes": [{"size": "S", "sku": ""}]},
                                 {"id": "rv9", "style_id": "st9", "color": "Putih"}]
    db.dewi_rnd_revisions.docs = [{"id": "r1", "style_id": "st1"}]
    monkeypatch.setattr(st, "get_db", lambda: db)
    monkeypatch.setattr(st, "log_activity", _noop)
    return st, db


def test_style_belum_dipakai_dihapus_beserta_varian_dan_revisi(style):
    st, db = style
    out = run(st.delete_style("st1", user=ADMIN))
    assert out["deleted"] is True and out["variants_deleted"] == 1 and out["revisions_deleted"] == 1
    assert db.dewi_rnd_styles.docs == [] and db.dewi_rnd_revisions.docs == []
    assert [v["id"] for v in db.dewi_rnd_variants.docs] == ["rv9"]


@pytest.mark.parametrize("koleksi,doc,label", [
    ("dewi_rnd_tech_packs", {"id": "x", "style_id": "st1"}, "tech pack"),
    ("dewi_rnd_hpp", {"id": "x", "style_id": "st1"}, "hitungan HPP"),
    ("dewi_rnd_sample_requests", {"id": "x", "style_id": "st1"}, "permintaan sampel"),
    ("dewi_rnd_patterns", {"id": "x", "style_id": "st1"}, "pola & marker"),
    ("rahaza_models", {"id": "m1", "rnd_style_id": "st1"}, "produk master (hasil promosi)"),
    ("dewi_rnd_variants", {"id": "rv2", "style_id": "st1", "sizes": [{"size": "M", "variant_id": "mv1"}]},
     "varian yang sudah jadi SKU"),
])
def test_style_sudah_dipakai_ditolak_409(style, koleksi, doc, label):
    st, db = style
    getattr(db, koleksi).docs.append(doc)
    detail = _tolak(st.delete_style("st1", user=ADMIN), label, 'Style "RND-01 Kemeja Uji"')
    assert "Nonaktifkan" in detail
    assert len(db.dewi_rnd_styles.docs) == 1 and len(db.dewi_rnd_revisions.docs) == 1


@pytest.mark.parametrize("status", ["pending_owner_review", "approved_for_launch"])
def test_style_keputusan_owner_tidak_bisa_dihapus(style, status):
    st, db = style
    db.dewi_rnd_styles.docs[0]["status"] = status
    _tolak(st.delete_style("st1", user=ADMIN), "owner")
    assert len(db.dewi_rnd_styles.docs) == 1


def test_style_hapus_dijaga_izin_rnd(style):
    st, db = style
    assert _status(st.delete_style("st1", user=STAF)) == 403
    assert len(db.dewi_rnd_styles.docs) == 1


# ══════════════════════════════ R&D: varian ══════════════════════════════
@pytest.fixture
def varian_rnd(monkeypatch):
    import routes.dewi_rnd_design as rd
    db = fm.FakeDB()
    db.dewi_rnd_styles.docs = [{"id": "st1", "style_code": "RND-01", "promoted_to_model_id": None}]
    db.dewi_rnd_variants.docs = [{"id": "rv1", "style_id": "st1", "style_code": "RND-01", "color": "Hitam",
                                  "color_id": "w1", "sizes": [{"size": "S", "sku": "RND-01-HTM-S"}]}]
    db.rahaza_model_variants.docs = [{"id": "mv1", "model_id": "m1", "color_id": "w1", "sku": "VST-1-HTM-S"}]
    monkeypatch.setattr(rd, "get_db", lambda: db)
    monkeypatch.setattr(rd, "log_activity", _noop)
    return rd, db


def test_varian_rnd_belum_jadi_sku_dihapus(varian_rnd):
    rd, db = varian_rnd
    assert run(rd.delete_variant("rv1", user=ADMIN))["deleted"] is True
    assert db.dewi_rnd_variants.docs == []


def test_varian_rnd_tertaut_sku_master_ditolak(varian_rnd):
    rd, db = varian_rnd
    db.dewi_rnd_variants.docs[0]["sizes"][0]["variant_id"] = "mv1"
    _tolak(rd.delete_variant("rv1", user=ADMIN), "SKU master produk", 'Varian "RND-01 Hitam"', "Nonaktifkan")
    assert len(db.dewi_rnd_variants.docs) == 1


def test_varian_rnd_style_dipromosikan_warna_sama_ditolak(varian_rnd):
    rd, db = varian_rnd
    db.dewi_rnd_styles.docs[0]["promoted_to_model_id"] = "m1"
    _tolak(rd.delete_variant("rv1", user=ADMIN), "SKU master produk")
    db.rahaza_model_variants.docs[0]["color_id"] = "w-lain"          # model hasil promosi tanpa warna ini
    assert run(rd.delete_variant("rv1", user=ADMIN))["deleted"] is True


# ══════════════════════════════ R&D: bahan riset ══════════════════════════════
@pytest.fixture
def bahan_rnd(monkeypatch):
    import routes.dewi_rnd_materials as rm
    db = fm.FakeDB()
    db.dewi_rnd_materials.docs = [{"id": "r1", "material_code": "FLC-01", "material_name": "Fleece Premium",
                                   "status": "active"}]
    monkeypatch.setattr(rm, "get_db", lambda: db)
    monkeypatch.setattr(rm, "log_activity", _noop)
    return rm, db


def test_bahan_rnd_belum_dipakai_dihapus(bahan_rnd):
    rm, db = bahan_rnd
    db.dewi_rnd_hpp.docs = [{"id": "h1", "cost_lines": [{"material_code": "FLC-02", "material_name": "Fleece Premium X"}]}]
    assert run(rm.delete_material("r1", user=ADMIN))["deleted"] is True
    assert db.dewi_rnd_materials.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("dewi_rnd_hpp", {"id": "x", "cost_lines": [{"material_code": "flc-01"}]}, "hitungan HPP"),
    ("dewi_rnd_hpp", {"id": "x", "bom_breakdown": [{"material_name": "fleece premium"}]}, "hitungan HPP"),
    ("dewi_rnd_sample_costing", {"id": "x", "trim_items": [{"name": "Kancing"}, {"name": "FLEECE PREMIUM"}]},
     "costing sampel"),
    ("dewi_rnd_tech_packs", {"id": "x", "bom_items": [{"material": "Fleece Premium"}]}, "tech pack"),
    ("dewi_rnd_tech_packs", {"id": "x", "fabrics": [{"name": "Fleece Premium"}]}, "tech pack"),
])
def test_bahan_rnd_dipakai_ditolak_409(bahan_rnd, koleksi, doc, label):
    rm, db = bahan_rnd
    getattr(db, koleksi).docs.append(doc)
    _tolak(rm.delete_material("r1", user=ADMIN), label, 'Bahan riset "FLC-01 Fleece Premium"', "Nonaktifkan")
    assert len(db.dewi_rnd_materials.docs) == 1


def test_bahan_rnd_hapus_dijaga_izin_rnd(bahan_rnd):
    rm, db = bahan_rnd
    assert _status(rm.delete_material("r1", user=STAF)) == 403
    assert len(db.dewi_rnd_materials.docs) == 1


# ══════════════════════════════ layar ══════════════════════════════
@pytest.mark.parametrize("berkas,potongan", [
    ("components/erp/RahazaModelsModule.jsx",
     ("hapusMaster", "models/${row.id}?hard=true", "model-delete-", "model-edit-", "model-deactivate-", "<Pencil",
      "label: 'Aksi'")),
    ("components/erp/RahazaVariantsModule.jsx",
     ("hapusMaster", "variants/${v.id}?hard=true", "variant-delete-", "variant-edit-",
      '<TableHead className="text-right">Aksi</TableHead>')),
    ("components/erp/RahazaColorsModule.jsx",
     ("hapusMaster", "colors/${row.id}?hard=true", "color-delete-", "color-edit-", "color-deactivate-",
      "label: 'Aksi'")),
    ("components/erp/RahazaProductCategoriesModule.jsx",
     ("hapusMaster", "product-categories/${row.id}?hard=true", "cat-delete-", "cat-edit-", "label: 'Aksi'")),
    ("components/erp/RahazaBOMModuleV2.jsx",
     ("hapusMaster", "boms/${row.bom_id}?hard=true", "bom-delete-", "bom-open-",
      '<TableHead className="text-right">Aksi</TableHead>')),
    ("components/erp/RahazaSizesModule.jsx", ("hapusPermanen", 'jenis="ukuran"')),
    ("components/erp/RnDStylesTab.jsx",
     ("hapusMaster", "status: 'archived'", "delete-style-", "edit-style-", "label: 'Aksi'")),
    ("components/erp/RnDVariantModule.jsx",
     ("hapusMaster", "e.status = res.status", "status: 'archived'", "rnd-variant-del-", "rnd-variant-edit-",
      "label: 'Aksi'")),
    ("components/erp/RnDMaterialsTab.jsx",
     ("hapusMaster", "status: 'inactive'", "delete-material-", "edit-material-", "label: 'Aksi'")),
])
def test_layar_master_punya_ubah_dan_hapus(berkas, potongan):
    src = fe(berkas)
    for frag in potongan:
        assert frag in src, (berkas, frag)
    assert "window.confirm" not in src


def test_label_hapus_tidak_lagi_bohong():
    """Tombol berlabel "Hapus varian" dulu hanya menonaktifkan; tombol "Nonaktifkan" dulu berikon tempat sampah."""
    var = fe("components/erp/RahazaVariantsModule.jsx")
    assert "Varian dinonaktifkan; item katalog" not in var
    for berkas in ("components/erp/RahazaModelsModule.jsx", "components/erp/RahazaColorsModule.jsx"):
        src = fe(berkas)
        i = src.index('title="Nonaktifkan"')
        assert "<Ban" in src[i:i + 300] and "<Trash2" not in src[i:i + 300], berkas
