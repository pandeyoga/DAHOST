"""Master data bisa diubah & dihapus (permintaan owner 10 Nov 2026) — hermetik (FakeDB, tanpa server).

Kata owner: "klien tidak bisa di edit tidak bisa dihapus … pastikan table table master data bisa dihapus. lalu untuk
catalog saya tidak bisa expand, lalu bagaimana cara saya bisa menambah varian? harusnya di list ada tambah variannya".

Yang dikunci:
  * `core.hapus_master`: satu kalimat & kode (409) untuk "sudah dipakai di …";
  * Klien maklon: `DELETE …/clients/{id}?hard=true` menghapus bila belum dipakai (ikut: akun portal + akun GL otomatis
    yang belum dijurnal), menolak 409 bila sudah dipakai PO/katalog/piutang/jurnal; tanpa `hard` tetap menonaktifkan;
  * Artikel katalog: hapus permanen + templat BOM-nya bila belum dipakai PO/sampel; 409 bila sudah;
  * Varian: tambah warna × ukuran dari master (kombinasi lama dilewati, nonaktif diaktifkan lagi) dan hapus varian
    yang belum dipakai;
  * gerbang peran di endpoint hapus/tambah varian; layar punya kolom Aksi, baris bisa dibuka, dan tombol Tambah varian.
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


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


def fe(rel: str) -> str:
    return (FE / rel).read_text(encoding="utf-8")


# ══════════════════════════════ core.hapus_master ══════════════════════════════
def test_hapus_master_kalimat_dan_kode():
    from core import hapus_master as hm
    db = fm.FakeDB()
    db.dewi_maklon_pos.docs = [{"id": "p1", "client_id": "c1"}, {"id": "p2", "client_id": "c1"}]
    pakai = run(hm.hitung_pemakaian(db, [("PO maklon", "dewi_maklon_pos", {"client_id": "c1"}),
                                         ("sampel", "dewi_maklon_samples", {"client_id": "c1"})]))
    assert pakai == {"PO maklon": 2}
    with pytest.raises(HTTPException) as e:
        hm.tolak_bila_dipakai("Klien", "SnBM", pakai)
    assert e.value.status_code == 409
    assert e.value.detail.startswith('Klien "SnBM" tidak bisa dihapus karena sudah dipakai di 2 PO maklon.')
    assert "Nonaktifkan" in e.value.detail
    hm.tolak_bila_dipakai("Klien", "SnBM", {})  # kosong → tidak menolak


# ══════════════════════════════ Klien maklon ══════════════════════════════
@pytest.fixture
def klien(monkeypatch):
    import routes.dewi_maklon as mod
    db = fm.FakeDB()
    db.dewi_maklon_clients.docs = [{"id": "c1", "code": "SNBM", "name": "SnBM", "status": "active"}]
    db.dewi_client_users.docs = [{"id": "cu1", "client_id": "c1", "email": "klien@x.id"}]
    db.rahaza_coa_accounts.docs = [
        {"id": "a1", "code": "1-1305-SNBM", "flags": {"subledger_entity_type": "maklon_client", "subledger_entity_id": "c1"}},
        {"id": "a2", "code": "4-1500-SNBM", "flags": {"subledger_entity_type": "maklon_revenue", "subledger_entity_id": "c1"}},
        {"id": "a3", "code": "1-1100", "flags": {}},
    ]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    return mod, db


def test_klien_belum_dipakai_dihapus_permanen_beserta_akun(klien):
    mod, db = klien
    out = run(mod.delete_client("c1", hard=True, user=ADMIN))
    assert out["deleted"] is True
    assert db.dewi_maklon_clients.docs == []
    assert db.dewi_client_users.docs == []
    assert [a["code"] for a in db.rahaza_coa_accounts.docs] == ["1-1100"]  # akun lain tidak tersentuh


@pytest.mark.parametrize("koleksi,doc,label", [
    ("dewi_maklon_pos", {"id": "p1", "client_id": "c1"}, "PO maklon"),
    ("production_pos", {"id": "p1", "buyer_id": "c1"}, "PO produksi"),
    ("dewi_maklon_buyer_catalog", {"id": "k1", "client_id": "c1"}, "artikel katalog"),
    ("rahaza_ar_invoices", {"id": "i1", "customer_id": "c1"}, "faktur piutang"),
    ("rahaza_journal_lines", {"id": "j1", "account_code": "1-1305-SNBM"}, "baris jurnal"),
])
def test_klien_sudah_dipakai_ditolak_409(klien, koleksi, doc, label):
    mod, db = klien
    getattr(db, koleksi).docs = [doc]
    with pytest.raises(HTTPException) as e:
        run(mod.delete_client("c1", hard=True, user=ADMIN))
    assert e.value.status_code == 409 and label in e.value.detail and "SnBM" in e.value.detail
    assert len(db.dewi_maklon_clients.docs) == 1 and len(db.dewi_client_users.docs) == 1
    assert len(db.rahaza_coa_accounts.docs) == 3


def test_klien_tanpa_hard_tetap_nonaktifkan(klien):
    mod, db = klien
    run(mod.delete_client("c1", hard=False, user=ADMIN))
    assert db.dewi_maklon_clients.docs[0]["status"] == "inactive"


# ══════════════════════════════ Katalog buyer ══════════════════════════════
@pytest.fixture
def katalog(monkeypatch):
    import routes.dewi_maklon_buyer_catalog as mod
    db = fm.FakeDB()
    db.rahaza_colors.docs = [{"id": "w1", "name": "Hitam", "code": "HTM", "active": True},
                             {"id": "w2", "name": "Merah", "code": "MRH", "active": True}]
    db.rahaza_sizes.docs = [{"id": "s1", "code": "S", "active": True}, {"id": "s2", "code": "M", "active": True},
                            {"id": "s3", "code": "XL", "active": True}]
    db.dewi_maklon_buyer_catalog.docs = [{
        "id": "k1", "client_id": "c1", "artikel_code": "pym", "product_name": "PYM HP JAYNI", "status": "active",
        "buyer_ref_code": "BJ_4967", "color_options": ["Hitam"], "size_options": ["S"],
        "variants": [{"id": "v1", "sku": "PYM-HTM-S", "color": "Hitam", "color_code": "HTM", "size": "S", "active": True},
                     {"id": "v2", "sku": "PYM-HTM-M", "color": "Hitam", "color_code": "HTM", "size": "M", "active": False}],
    }]
    db.dewi_maklon_bom_templates.docs = [{"id": "b1", "buyer_catalog_id": "k1", "version": 1}]
    monkeypatch.setattr(mod, "get_db", lambda: db)
    monkeypatch.setattr(mod, "log_activity", _noop)
    return mod, db


def test_artikel_belum_dipakai_dihapus_beserta_templat_bom(katalog):
    mod, db = katalog
    out = run(mod.delete_buyer_catalog("k1", hard=True, user=ADMIN))
    assert out["deleted"] is True
    assert db.dewi_maklon_buyer_catalog.docs == [] and db.dewi_maklon_bom_templates.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("dewi_maklon_pos", {"id": "p1", "items": [{"buyer_catalog_id": "x"}, {"buyer_catalog_id": "k1"}]}, "PO maklon"),
    ("po_items", {"id": "pi1", "catalog_item_id": "k1"}, "baris PO produksi"),
    ("dewi_maklon_samples", {"id": "sp1", "buyer_catalog_id": "k1"}, "sampel"),
])
def test_artikel_sudah_dipakai_ditolak_409(katalog, koleksi, doc, label):
    mod, db = katalog
    getattr(db, koleksi).docs = [doc]
    with pytest.raises(HTTPException) as e:
        run(mod.delete_buyer_catalog("k1", hard=True, user=ADMIN))
    assert e.value.status_code == 409 and label in e.value.detail and "PYM HP JAYNI" in e.value.detail
    assert len(db.dewi_maklon_buyer_catalog.docs) == 1 and len(db.dewi_maklon_bom_templates.docs) == 1


def test_artikel_tanpa_hard_tetap_dihentikan(katalog):
    mod, db = katalog
    run(mod.delete_buyer_catalog("k1", hard=False, user=ADMIN))
    assert db.dewi_maklon_buyer_catalog.docs[0]["status"] == "discontinued"


def test_tambah_varian_warna_x_ukuran_dari_master(katalog):
    mod, db = katalog
    out = run(mod.add_maklon_variants("k1", mod.MaklonVariantAddIn(colors=["hitam", "Merah"], sizes=["M", "xl"]), user=ADMIN))
    # Hitam-M sudah ada tapi nonaktif → diaktifkan lagi; sisanya baru
    assert sorted(out["created"]) == ["PYM-HTM-XL", "PYM-MRH-M", "PYM-MRH-XL"]
    assert out["reactivated"] == ["PYM-HTM-M"] and out["skipped"] == []
    doc = db.dewi_maklon_buyer_catalog.docs[0]
    assert len(doc["variants"]) == 5
    assert next(v for v in doc["variants"] if v["id"] == "v2")["active"] is True
    assert doc["color_options"] == ["Hitam", "Merah"] and doc["size_options"] == ["S", "M", "XL"]
    baru = next(v for v in doc["variants"] if v["sku"] == "PYM-MRH-XL")
    assert baru["buyer_ref_code"] == "BJ_4967" and baru["color"] == "Merah" and baru["size"] == "XL"
    # kirim ulang → semua dilewati, tidak ada duplikat
    out2 = run(mod.add_maklon_variants("k1", mod.MaklonVariantAddIn(colors=["Merah"], sizes=["M"]), user=ADMIN))
    assert out2["created"] == [] and out2["skipped"] == ["PYM-MRH-M"]
    assert len(db.dewi_maklon_buyer_catalog.docs[0]["variants"]) == 5


def test_tambah_varian_ditolak_bila_bukan_master_atau_kosong(katalog):
    mod, _db = katalog
    with pytest.raises(HTTPException) as e:
        run(mod.add_maklon_variants("k1", mod.MaklonVariantAddIn(colors=["Ungu"], sizes=["S"]), user=ADMIN))
    assert e.value.status_code == 400 and "Ungu" in e.value.detail
    with pytest.raises(HTTPException) as e:
        run(mod.add_maklon_variants("k1", mod.MaklonVariantAddIn(colors=["Hitam"], sizes=[]), user=ADMIN))
    assert e.value.status_code == 400


def test_hapus_varian_dipakai_ditolak_belum_dipakai_dihapus(katalog):
    mod, db = katalog
    db.po_items.docs = [{"id": "pi1", "maklon_variant_id": "v1"}]
    with pytest.raises(HTTPException) as e:
        run(mod.delete_maklon_variant("k1", "v1", user=ADMIN))
    assert e.value.status_code == 409 and "PYM-HTM-S" in e.value.detail
    out = run(mod.delete_maklon_variant("k1", "v2", user=ADMIN))
    assert [v["id"] for v in out["variants"]] == ["v1"]
    assert [v["id"] for v in db.dewi_maklon_buyer_catalog.docs[0]["variants"]] == ["v1"]


# ══════════════════════════════ gerbang peran ══════════════════════════════
def _deps(router, method, path):
    for r in router.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return [getattr(getattr(d, "dependency", None) or getattr(d, "call", None), "__name__", "") for d in r.dependencies]
    raise AssertionError(f"rute {method} {path} tidak ada")


@pytest.mark.parametrize("modname,method,path", [
    ("routes.dewi_maklon", "DELETE", "/api/dewi/maklon/clients/{client_id}"),
    ("routes.dewi_maklon_buyer_catalog", "DELETE", "/api/dewi/maklon/buyer-catalog/{catalog_id}"),
    ("routes.dewi_maklon_buyer_catalog", "POST", "/api/dewi/maklon/buyer-catalog/{catalog_id}/variants"),
    ("routes.dewi_maklon_buyer_catalog", "DELETE", "/api/dewi/maklon/buyer-catalog/{catalog_id}/variants/{variant_id}"),
])
def test_endpoint_hapus_dijaga_peran(modname, method, path):
    import importlib
    mod = importlib.import_module(modname)
    assert any(n.startswith("require_roles[") and "maklon.manage" in n for n in _deps(mod.router, method, path))


# ══════════════════════════════ layar ══════════════════════════════
def test_layar_alur_hapus_menawarkan_nonaktifkan():
    lib = fe("lib/hapusMaster.js")
    assert "statusDari(e) === 409" in lib and "Nonaktifkan" in lib and "confirmDialog" in lib
    assert "e.status = res.status" in fe("lib/api.js")


def test_layar_katalog_bisa_dibuka_dan_punya_aksi():
    src = fe("components/erp/MaklonBuyerCatalogModule.jsx")
    for frag in ("RowToggle", "RowDetail", "KatalogArtikelRingkas", "TambahVarianForm", "buyer-catalog-add-variant-",
                 "buyer-catalog-row-edit-", "buyer-catalog-row-delete-", "?hard=true", "hapusMaster"):
        assert frag in src, frag
    detail = fe("components/erp/maklon/KatalogArtikelDetail.jsx")
    assert "bc-variant-delete-" in detail and "Tambah varian" in detail and "BomAktifSection" in detail
    form = fe("components/erp/maklon/TambahVarianForm.jsx")
    assert "/variants`" in form and "FormPopup" in form


def test_layar_klien_dan_vendor_punya_aksi_ubah_hapus():
    klien = fe("components/erp/MaklonClientManagement.jsx")
    assert "maklon-client-row-edit-" in klien and "maklon-client-row-delete-" in klien and "clients/${c.id}?hard=true" in klien
    vendor = fe("components/erp/VendorAccountsAdminModule.jsx")
    for frag in ("partner-row-edit-", "partner-row-delete-", "account-row-edit-", "account-row-delete-", "hapusMaster"):
        assert frag in vendor, frag
