"""Tahap 6 (7 Nov 2026) — keputusan owner atas audit form portal Produksi · Maklon · RnD (sisi server).

  PR1  Permak: vendor/workshop dari master Vendor CMT + pilihan tetap "Workshop DA sendiri".
  PR2  Komponen Kurang: bahan BOM produk terpilih tampil paling atas (layar — dicek statis).
  PR3  RnD Style: buyer dari master Klien maklon (id + nama), jenis kain dari master kain; nilai lama tetap.
  PR4  Kirim Material CMT: PO tanpa vendor boleh dikirimi; vendor surat jalan ikut dicatat di PO.
  PR5  Katalog buyer: warna/ukuran hanya dari master; opsi lama artikel tetap boleh.
  PR6  Riset Material: kategori daftar tetap (kategori Master Material), vendor dari master supplier.
  PR7  PO Maklon: tanpa kotak "ketik nama pelanggan"; server menolak PO maklon tanpa buyer.
  HR4  Sample RnD: PIC = karyawan (id + nama) atau penjahit luar (nama + penanda).
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402

USER = {"id": "u1", "name": "Admin Uji", "role": "admin"}
FE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "erp"


def run(c):
    return asyncio.run(c)


async def _user(*_a, **_k):
    return USER


async def _noop(*_a, **_k):
    return None


# ══════════════════════════════════════════════════════════════════════════════
# PR1 · Permak — vendor/workshop dari master
# ══════════════════════════════════════════════════════════════════════════════
def _permak_env(monkeypatch):
    import routes.dewi_cmt_permak as pmk
    import core.doc_number_policy as dnp
    db = FakeDB()
    db.vendor_partners.docs = [
        {"id": "v1", "code": "CMT-01", "name": "CMT Sejahtera", "active": True},
        {"id": "v2", "code": "CMT-02", "name": "CMT Lama", "is_active": False},
    ]
    db.production_pos.docs = [{"id": "p1", "po_number": "PO-INT-1", "status": "In Production",
                               "business_type": "internal"}]
    db.po_items.docs = [{"id": "i1", "po_id": "p1", "sku": "DA-1-HTM-M", "product_name": "Kaos Uji",
                         "size": "M", "color": "Hitam"}]
    monkeypatch.setattr(pmk, "require_auth", _user)
    monkeypatch.setattr(pmk, "get_db", lambda: db)
    monkeypatch.setattr(pmk, "_require_admin", lambda u: None)
    monkeypatch.setattr(pmk, "log_activity", _noop)

    async def number(*_a, **_k):
        return "PMK/UJI/0001"
    monkeypatch.setattr(dnp, "issue_number", number)
    return pmk, db


def test_permak_workshop_da_sendiri(monkeypatch):
    pmk, _db = _permak_env(monkeypatch)
    out = run(pmk.resolve_permak_workshop(_db, "workshop_da"))
    assert out == {"vendor_permak_kind": "workshop_da", "vendor_permak_id": "workshop_da",
                   "vendor_permak_name": "Workshop DA sendiri", "vendor_permak": "Workshop DA sendiri"}


def test_permak_vendor_dari_master_nama_ikut_master(monkeypatch):
    pmk, db = _permak_env(monkeypatch)
    out = run(pmk.create_permak(pmk.PermakCreate(po_id="p1", po_item_id="i1", qty=2, source="good",
                                                 vendor_permak_id="v1", vendor_permak="ketikan salah"),
                                FakeRequest()))
    assert out["vendor_permak_id"] == "v1" and out["vendor_permak_kind"] == "vendor_cmt"
    assert out["vendor_permak_name"] == "CMT Sejahtera" and out["vendor_permak"] == "CMT Sejahtera"
    saved = db.dewi_cmt_permak.docs[0]
    assert saved["vendor_permak_id"] == "v1" and saved["vendor_permak_name"] == "CMT Sejahtera"


@pytest.mark.parametrize("vid,typed,msg", [
    ("hantu", "", "master Vendor CMT"),          # id tidak dikenal
    ("v2", "", "nonaktif"),                      # vendor nonaktif
    ("", "Tukang permak pasar", "ketik bebas"),  # ketikan tanpa id
])
def test_permak_vendor_tidak_sah_ditolak(monkeypatch, vid, typed, msg):
    pmk, db = _permak_env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(pmk.create_permak(pmk.PermakCreate(po_id="p1", po_item_id="i1", qty=1, source="good",
                                               vendor_permak_id=vid, vendor_permak=typed), FakeRequest()))
    assert e.value.status_code == 400 and msg in e.value.detail
    assert db.dewi_cmt_permak.docs == []


def test_permak_tanpa_vendor_boleh(monkeypatch):
    pmk, db = _permak_env(monkeypatch)
    out = run(pmk.create_permak(pmk.PermakCreate(po_id="p1", po_item_id="i1", qty=1, source="good"),
                                FakeRequest()))
    assert out["vendor_permak_id"] == "" and out["vendor_permak"] == ""


def test_permak_ubah_vendor_dan_teks_lama(monkeypatch):
    pmk, db = _permak_env(monkeypatch)
    db.dewi_cmt_permak.docs = [{"id": "k1", "status": "open", "qty": 1, "cost_per_pcs": 0,
                                "vendor_permak": "Tukang lama"}]           # dokumen lama: teks bebas
    # teks lama dikirim balik apa adanya → bukan perubahan, tidak ditolak
    run(pmk.update_permak("k1", pmk.PermakUpdate(vendor_permak="Tukang lama", reason="cek"), FakeRequest()))
    assert db.dewi_cmt_permak.docs[0]["vendor_permak"] == "Tukang lama"
    # ketikan baru → ditolak
    with pytest.raises(HTTPException):
        run(pmk.update_permak("k1", pmk.PermakUpdate(vendor_permak="Tukang baru"), FakeRequest()))
    # pilih Workshop DA → tersimpan dengan penanda
    run(pmk.update_permak("k1", pmk.PermakUpdate(vendor_permak_id="workshop_da"), FakeRequest()))
    d = db.dewi_cmt_permak.docs[0]
    assert d["vendor_permak_kind"] == "workshop_da" and d["vendor_permak"] == "Workshop DA sendiri"
    # vendor tak dikenal → ditolak
    with pytest.raises(HTTPException):
        run(pmk.update_permak("k1", pmk.PermakUpdate(vendor_permak_id="hantu"), FakeRequest()))


def test_permak_vendor_lama_nonaktif_tetap_boleh_saat_ubah(monkeypatch):
    pmk, db = _permak_env(monkeypatch)
    out = run(pmk.resolve_permak_workshop(db, "v2", current={"vendor_permak_id": "v2"}))
    assert out["vendor_permak_name"] == "CMT Lama"


def test_permak_layar_pilih_dari_master():
    src = (FE / "CMTPermakModule.jsx").read_text(encoding="utf-8")
    assert "select-permak-workshop" in src and "vendor_permak_id" in src
    assert "input-permak-vendor" not in src            # kotak teks bebas sudah hilang


# ══════════════════════════════════════════════════════════════════════════════
# PR2 · Komponen Kurang — bahan BOM di atas (layar)
# ══════════════════════════════════════════════════════════════════════════════
def test_komponen_bahan_bom_di_atas_layar():
    # Tahap 9 (keputusan 12): input staf di tab "Permintaan tambahan" — pcs per SKU → potongan dari BOM otomatis,
    # pilihan aksesoris menampilkan rencana aksesoris PO (dari BOM) paling atas.
    src = (FE / "engine" / "kirim" / "PermintaanTab.jsx").read_text(encoding="utf-8")
    assert "/accessory-plan" in src and "(rencana PO)" in src
    assert "matChoices.map" in src


# ══════════════════════════════════════════════════════════════════════════════
# PR3 · RnD Style — buyer & jenis kain dari master
# ══════════════════════════════════════════════════════════════════════════════
def _style_env(monkeypatch):
    import routes.dewi_rnd_styles as st
    db = FakeDB()
    db.dewi_maklon_clients.docs = [
        {"id": "c1", "code": "KL-01", "name": "Klien Satu", "status": "active"},
        {"id": "c2", "code": "KL-02", "name": "Klien Nonaktif", "status": "inactive"},
    ]
    db.rahaza_materials.docs = [
        {"id": "m1", "code": "KN-A-HTM", "name": "RIB KNIT 20\"", "type": "fabric", "active": True},
        {"id": "m2", "code": "KN-A-PTH", "name": "RIB KNIT 20\"", "type": "fabric", "active": True},
        {"id": "m3", "code": "KN-B", "name": "Condru", "type": "fabric", "active": True},
        {"id": "m4", "code": "PT-1", "name": "Potongan Uji", "type": "fabric", "active": True, "is_cut_panel": True},
        {"id": "m5", "code": "KN-OLD", "name": "Kain Lama", "type": "fabric", "active": False},
        {"id": "m6", "code": "KCG-1", "name": "Kancing", "type": "accessory", "active": True},
    ]
    monkeypatch.setattr(st, "get_db", lambda: db)
    return st, db


def test_style_form_options(monkeypatch):
    st, _db = _style_env(monkeypatch)
    out = run(st.style_form_options(user=USER))
    assert out["fabric_types"] == ["Condru", "RIB KNIT 20\""]      # unik, tanpa potongan/nonaktif/aksesoris
    assert [b["id"] for b in out["buyers"]] == ["c1"]              # klien nonaktif tidak ditawarkan


def test_style_buyer_dan_kain_dari_master(monkeypatch):
    st, db = _style_env(monkeypatch)
    out = run(st.create_style({"style_code": "uji-1", "style_name": "Style Uji", "client_id": "c1",
                               "buyer": "ketikan", "fabric_type": "condru"}, user=USER))
    assert out["client_id"] == "c1" and out["client_name"] == "Klien Satu" and out["buyer"] == "Klien Satu"
    assert out["fabric_type"] == "Condru"                          # ditulis persis seperti master
    out2 = run(st.create_style({"style_code": "uji-2", "style_name": "Internal"}, user=USER))
    assert out2["client_id"] is None and out2["buyer"] == "" and out2["fabric_type"] == ""


@pytest.mark.parametrize("body,msg", [
    ({"buyer": "Zara"}, "Klien maklon"),               # ketik bebas
    ({"client_id": "hantu"}, "Klien maklon"),
    ({"client_id": "c2"}, "nonaktif"),
    ({"fabric_type": "Cotton Combed 30s"}, "master kain"),
])
def test_style_nilai_di_luar_master_ditolak(monkeypatch, body, msg):
    st, db = _style_env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(st.create_style({"style_code": "uji-x", "style_name": "X", **body}, user=USER))
    assert e.value.status_code == 400 and msg in e.value.detail
    assert db.dewi_rnd_styles.docs == []


def test_style_nilai_lama_tetap_saat_ubah(monkeypatch):
    st, db = _style_env(monkeypatch)
    db.dewi_rnd_styles.docs = [{"id": "s1", "style_code": "LAMA-1", "style_name": "Lama", "status": "draft",
                                "buyer": "Zara", "client_id": None, "fabric_type": "Cotton Combed 30s"}]
    # formulir mengirim nilai lama apa adanya + ubah nama → diterima, nilai lama tetap
    out = run(st.update_style("s1", {"style_name": "Lama 2", "client_id": "", "buyer": "Zara",
                                     "fabric_type": "Cotton Combed 30s"}, user=USER))
    assert out["buyer"] == "Zara" and out["fabric_type"] == "Cotton Combed 30s" and out["style_name"] == "Lama 2"
    # mengganti ke ketikan baru → ditolak
    with pytest.raises(HTTPException):
        run(st.update_style("s1", {"buyer": "Mango"}, user=USER))
    # pilih dari master → id + nama
    out = run(st.update_style("s1", {"client_id": "c1", "buyer": "Zara", "fabric_type": "RIB KNIT 20\""},
                              user=USER))
    assert out["client_id"] == "c1" and out["buyer"] == "Klien Satu" and out["fabric_type"] == "RIB KNIT 20\""
    # kosongkan buyer = produk internal
    out = run(st.update_style("s1", {"client_id": "", "buyer": ""}, user=USER))
    assert out["client_id"] is None and out["buyer"] == "" and out["client_name"] == ""


# ══════════════════════════════════════════════════════════════════════════════
# PR4 · Kirim Material CMT — PO tanpa vendor
# ══════════════════════════════════════════════════════════════════════════════
def _ship_env(monkeypatch, *, po_vendor=None, business_type="internal", status="Confirmed"):
    import routes.vendor_shipment as vs
    import core.doc_number_policy as dnp
    import core.material_issue_engine as mie
    import core.shipment_accessories as sa
    import routes.production_maklon_bridge as bridge
    db = FakeDB()
    db.vendor_partners.docs = [{"id": "v1", "code": "CMT-01", "name": "CMT Sejahtera", "active": True},
                               {"id": "v2", "code": "CMT-02", "name": "CMT Makmur", "active": True}]
    po = {"id": "p1", "po_number": "PO-UJI-1", "status": status, "business_type": business_type}
    if po_vendor is not None:
        po.update({"vendor_id": po_vendor, "vendor_name": "x"})
    db.production_pos.docs = [po]
    # Tahap 8 (K12): penjahit yang dipilih saat kirim butuh upah jahit di baris PO — baris uji diberi upah.
    db.po_items.docs = [{"id": "i1", "po_id": "p1", "qty": 10, "product_name": "Kaos Uji", "sku": "S1",
                         "cmt_price_snapshot": 9000}]
    calls = {"released": [], "sync": []}

    async def number(*_a, **_k):
        return "SJ-UJI-1"

    async def release(_db, _k, n):
        calls["released"].append(n)
        return True

    async def mi_ok(*_a, **_k):
        return {}

    async def acc(*_a, **_k):
        return 0

    async def sync(_db, pid, _u):
        calls["sync"].append(pid)
    monkeypatch.setattr(dnp, "issue_number", number)
    monkeypatch.setattr(dnp, "release_number", release)
    monkeypatch.setattr(mie, "issue_for_vendor_shipment", mi_ok)
    monkeypatch.setattr(mie, "issue_for_maklon_shipment", mi_ok)
    monkeypatch.setattr(sa, "record_for_shipment", acc)
    monkeypatch.setattr(bridge, "try_sync_maklon_finance", sync)
    monkeypatch.setattr(vs, "log_activity", _noop)
    return vs, db, mie, calls


def _ship_body(vendor="v1"):
    return {"vendor_id": vendor, "shipment_type": "NORMAL", "accessory_items": [],
            "items": [{"po_id": "p1", "po_number": "PO-UJI-1", "po_item_id": "i1", "qty_sent": 4}]}


def test_kirim_po_tanpa_vendor_mengisi_vendor_po(monkeypatch):
    vs, db, _mie, calls = _ship_env(monkeypatch)
    out = run(vs.create_vendor_shipment_internal(db, _ship_body(), USER))
    assert out["vendor_id"] == "v1" and out["vendor_name"] == "CMT Sejahtera"
    assert out["po_vendor_assigned"] == ["PO-UJI-1"]
    po = db.production_pos.docs[0]
    assert po["vendor_id"] == "v1" and po["vendor_name"] == "CMT Sejahtera"
    assert po["vendor_assigned_via"] == "kirim_material" and po["vendor_assigned_shipment_number"] == "SJ-UJI-1"
    assert calls["sync"] == []                          # PO internal: tidak ada jadwal hutang maklon


def test_kirim_po_maklon_tanpa_vendor_menyegarkan_keuangan(monkeypatch):
    vs, db, _mie, calls = _ship_env(monkeypatch, business_type="maklon")
    run(vs.create_vendor_shipment_internal(db, _ship_body(), USER))
    assert calls["sync"] == ["p1"]                      # jadwal hutang CMT dibagi ulang ke vendor baru


def test_kirim_po_bervendor_tidak_diubah(monkeypatch):
    vs, db, _mie, calls = _ship_env(monkeypatch, po_vendor="v1")
    out = run(vs.create_vendor_shipment_internal(db, _ship_body(), USER))
    assert out["po_vendor_assigned"] == [] and "vendor_assigned_via" not in db.production_pos.docs[0]
    with pytest.raises(HTTPException) as e:             # vendor lain tetap ditolak seperti dulu
        run(vs.create_vendor_shipment_internal(db, _ship_body("v2"), USER))
    assert "vendor lain" in e.value.detail


def test_kirim_gagal_stok_mengembalikan_vendor_po(monkeypatch):
    vs, db, mie, calls = _ship_env(monkeypatch)

    async def short(*_a, **_k):
        raise mie.MaterialShortage([{"material_code": "KN-1", "required": 5, "available": 1, "unit": "kg"}])
    monkeypatch.setattr(mie, "issue_for_vendor_shipment", short)
    with pytest.raises(HTTPException):
        run(vs.create_vendor_shipment_internal(db, _ship_body(), USER))
    po = db.production_pos.docs[0]
    assert not po.get("vendor_id") and "vendor_assigned_via" not in po      # isian vendor dibatalkan
    assert db.vendor_shipments.docs == []


def test_isi_vendor_balapan_ditolak(monkeypatch):
    """Dua kiriman bersamaan: yang kalah (PO sudah diisi vendor lain) ditolak, isiannya sendiri dibatalkan."""
    vs, db, _mie, _calls = _ship_env(monkeypatch)
    db.production_pos.docs.append({"id": "p2", "po_number": "PO-UJI-2", "status": "Confirmed",
                                   "vendor_id": "v2"})
    with pytest.raises(HTTPException):
        run(vs.assign_vendor_to_vendorless_pos(db, ["p1", "p2"], "v1", "CMT Sejahtera", "SJ-X", USER))
    assert not db.production_pos.docs[0].get("vendor_id")


def test_kirim_layar_po_tanpa_vendor_tampil():
    src = (FE / "engine" / "kirim" / "KirimanForm.jsx").read_text(encoding="utf-8")   # Tahap 9: form kiriman
    assert "!form.vendor_id || !p.vendor_id || p.vendor_id === form.vendor_id" in src


# ══════════════════════════════════════════════════════════════════════════════
# PR5 · Katalog buyer — warna/ukuran hanya dari master
# ══════════════════════════════════════════════════════════════════════════════
def _cat_env(monkeypatch):
    import routes.dewi_maklon_buyer_catalog as bc
    db = FakeDB()
    db.rahaza_colors.docs = [{"id": "w1", "code": "HTM", "name": "Hitam", "active": True},
                             {"id": "w2", "code": "PTH", "name": "Putih", "active": True},
                             {"id": "w3", "code": "OLD", "name": "Coklat Tua", "active": False}]
    db.rahaza_sizes.docs = [{"id": "z1", "code": "M", "active": True}, {"id": "z2", "code": "XL", "active": True}]
    db.dewi_maklon_clients.docs = [{"id": "c1", "code": "KL-01", "name": "Klien Satu"}]
    monkeypatch.setattr(bc, "get_db", lambda: db)
    monkeypatch.setattr(bc, "log_activity", _noop)
    return bc, db


def test_katalog_opsi_dari_master_dinormalkan(monkeypatch):
    bc, db = _cat_env(monkeypatch)
    out = run(bc.create_buyer_catalog(bc.BuyerCatalogIn(
        client_id="c1", artikel_code="UJI-1", product_name="Kaos", color_options=["hitam", "Putih", "HITAM"],
        size_options=["m", "XL"]), user=USER))
    assert out["item"]["color_options"] == ["Hitam", "Putih"] and out["item"]["size_options"] == ["M", "XL"]


@pytest.mark.parametrize("colors,sizes,msg", [
    (["Merah Cabe"], ["M"], "Warna Merah Cabe"),
    (["Hitam"], ["XXXL"], "Ukuran XXXL"),
    (["Coklat Tua"], ["M"], "Warna Coklat Tua"),        # warna nonaktif = bukan pilihan
])
def test_katalog_opsi_luar_master_ditolak(monkeypatch, colors, sizes, msg):
    bc, db = _cat_env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(bc.create_buyer_catalog(bc.BuyerCatalogIn(client_id="c1", artikel_code="UJI-2", product_name="X",
                                                      color_options=colors, size_options=sizes), user=USER))
    assert e.value.status_code == 400 and msg in e.value.detail and "Master Data" in e.value.detail
    assert db.dewi_maklon_buyer_catalog.docs == []


def test_katalog_artikel_lama_tetap_bisa_diubah(monkeypatch):
    bc, db = _cat_env(monkeypatch)
    db.dewi_maklon_buyer_catalog.docs = [{"id": "a1", "client_id": "c1", "artikel_code": "LAMA",
                                          "color_options": ["Biru Dongker Khusus"], "size_options": ["XXXL"],
                                          "default_cmt_price": 0, "default_selling_price": 0}]
    out = run(bc.update_buyer_catalog("a1", bc.BuyerCatalogUpdate(
        product_name="Ganti nama", color_options=["Biru Dongker Khusus", "hitam"], size_options=["XXXL"]),
        user=USER))
    assert out["item"]["color_options"] == ["Biru Dongker Khusus", "Hitam"]
    with pytest.raises(HTTPException):                   # opsi BARU di luar master tetap ditolak
        run(bc.update_buyer_catalog("a1", bc.BuyerCatalogUpdate(color_options=["Ungu Baru"]), user=USER))


def test_katalog_layar_tanpa_kotak_lain():
    src = (FE / "maklon" / "KatalogArtikelForm.jsx").read_text(encoding="utf-8")   # Tahap 9: form di halaman
    assert "bc-form-color-custom" not in src and "bc-form-size-custom" not in src
    assert "bc-form-master-hint" in src


# ══════════════════════════════════════════════════════════════════════════════
# PR6 · Riset Material — kategori tetap + vendor master supplier
# ══════════════════════════════════════════════════════════════════════════════
def _riset_env(monkeypatch):
    import routes.dewi_rnd_materials as rm
    db = FakeDB()
    db.rahaza_material_categories.docs = [
        {"code": "FABRIC", "name": "Kain/Fabric", "order_seq": 1, "active": True},
        {"code": "ACCESSORY", "name": "Aksesoris", "order_seq": 3, "active": True},
        {"code": "CUT_PANEL", "name": "Potongan / Kain Pola", "order_seq": 7, "active": True},
        {"code": "OLD", "name": "Kategori Mati", "order_seq": 8, "active": False},
    ]
    db.rahaza_suppliers.docs = [{"id": "s1", "code": "SUP-0001", "name": "Supplier Satu", "is_active": True,
                                 "bank_account": "rahasia"},
                                {"id": "s2", "code": "SUP-0002", "name": "Supplier Nonaktif", "is_active": False}]
    monkeypatch.setattr(rm, "get_db", lambda: db)
    return rm, db


def test_riset_form_options(monkeypatch):
    rm, db = _riset_env(monkeypatch)
    out = run(rm.material_form_options(user=USER))
    assert [c["code"] for c in out["categories"]] == ["FABRIC", "ACCESSORY"]     # tanpa potongan & nonaktif
    assert out["suppliers"] == [{"id": "s1", "code": "SUP-0001", "name": "Supplier Satu"}]   # tanpa data rahasia
    db.rahaza_material_categories.docs = []                                       # master kosong → daftar bawaan
    codes = [c["code"] for c in run(rm.riset_categories(db))]
    assert "FABRIC" in codes and "CUT_PANEL" not in codes


def test_riset_buat_dengan_master(monkeypatch):
    rm, db = _riset_env(monkeypatch)
    out = run(rm.create_material({"material_code": "rm-1", "material_name": "Kain Riset", "category": "kain/fabric",
                                  "vendor_id": "s1", "vendor": "ketikan"}, user=USER))
    assert out["category"] == "Kain/Fabric" and out["category_code"] == "FABRIC"
    assert out["vendor_id"] == "s1" and out["vendor"] == "Supplier Satu" and out["vendor_is_prospect"] is False
    out = run(rm.create_material({"material_code": "rm-2", "material_name": "Kain Calon", "category_code": "FABRIC",
                                  "vendor": "Toko Kain Baru", "vendor_is_prospect": True}, user=USER))
    assert out["vendor_id"] == "" and out["vendor"] == "Toko Kain Baru" and out["vendor_is_prospect"] is True


@pytest.mark.parametrize("body,msg", [
    ({"category": "Bahan Rahasia"}, "Kategori"),
    ({"category_code": "CUT_PANEL"}, "Kategori"),
    ({"vendor": "Toko Ketikan"}, "Calon supplier"),       # ketikan tanpa penanda
    ({"vendor_id": "hantu"}, "master supplier"),
    ({"vendor_id": "s2"}, "nonaktif"),
])
def test_riset_nilai_tidak_sah_ditolak(monkeypatch, body, msg):
    rm, db = _riset_env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(rm.create_material({"material_code": "rm-x", "material_name": "X", **body}, user=USER))
    assert e.value.status_code == 400 and msg in e.value.detail
    assert db.dewi_rnd_materials.docs == []


def test_riset_nilai_lama_tetap_saat_ubah(monkeypatch):
    rm, db = _riset_env(monkeypatch)
    db.dewi_rnd_materials.docs = [{"id": "r1", "material_code": "LAMA", "category": "Fleece Impor",
                                   "vendor": "Toko Lama"}]
    out = run(rm.update_material("r1", {"category": "Fleece Impor", "category_code": "", "vendor": "Toko Lama",
                                        "vendor_id": "", "notes": "ubah catatan"}, user=USER))
    assert out["category"] == "Fleece Impor" and out["vendor"] == "Toko Lama" and out["notes"] == "ubah catatan"
    with pytest.raises(HTTPException):
        run(rm.update_material("r1", {"vendor": "Toko Lain"}, user=USER))


# ══════════════════════════════════════════════════════════════════════════════
# PR7 · PO Maklon — buyer wajib, tanpa ketik nama pelanggan
# ══════════════════════════════════════════════════════════════════════════════
def test_po_maklon_wajib_buyer():
    from routes.production_pos import assert_maklon_buyer
    with pytest.raises(HTTPException) as e:
        assert_maklon_buyer({"business_type": "maklon", "customer_name": "Ketikan Pelanggan"})
    assert e.value.status_code == 400 and "buyer" in e.value.detail
    assert_maklon_buyer({"business_type": "maklon", "buyer_id": "c1"})
    assert_maklon_buyer({"business_type": "internal", "customer_name": "Gudang FG Sendiri"})
    assert_maklon_buyer({})                                     # bawaan internal


def test_po_maklon_layar_tanpa_kotak_ketik():
    src = (FE / "engine" / "ProductionPOModule.jsx").read_text(encoding="utf-8")
    assert 'placeholder="Atau ketik nama pelanggan"' not in src


# ══════════════════════════════════════════════════════════════════════════════
# HR4 · Sample RnD — PIC karyawan / penjahit luar
# ══════════════════════════════════════════════════════════════════════════════
def _sample_env(monkeypatch):
    import routes.dewi_rnd_samples as smp
    db = FakeDB()
    db.dewi_rnd_styles.docs = [{"id": "st1", "style_code": "UJI-1", "style_name": "Style Uji"}]
    db.rahaza_employees.docs = [{"id": "e1", "employee_code": "K-001", "name": "Penjahit Sample", "active": True,
                                 "department": "Sample"},
                                {"id": "e2", "employee_code": "K-002", "name": "Karyawan Keluar", "active": False}]
    monkeypatch.setattr(smp, "get_db", lambda: db)
    return smp, db


def test_sample_pic_karyawan(monkeypatch):
    smp, db = _sample_env(monkeypatch)
    out = run(smp.create_sample_request({"style_id": "st1", "sample_pic_employee_id": "e1",
                                         "sample_pic": "ketikan"}, user=USER))
    assert out["sample_pic_employee_id"] == "e1" and out["sample_pic"] == "Penjahit Sample"
    assert out["sample_pic_external"] is False


def test_sample_pic_penjahit_luar(monkeypatch):
    smp, db = _sample_env(monkeypatch)
    out = run(smp.create_sample_request({"style_id": "st1", "sample_pic": "Bu Penjahit Luar",
                                         "sample_pic_external": True}, user=USER))
    assert out["sample_pic_employee_id"] == "" and out["sample_pic"] == "Bu Penjahit Luar"
    assert out["sample_pic_external"] is True


@pytest.mark.parametrize("body,msg", [
    ({"sample_pic": "Ketik Tanpa Penanda"}, "Penjahit luar"),
    ({"sample_pic_employee_id": "hantu"}, "karyawan"),
    ({"sample_pic_employee_id": "e2"}, "nonaktif"),
])
def test_sample_pic_tidak_sah_ditolak(monkeypatch, body, msg):
    smp, db = _sample_env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(smp.create_sample_request({"style_id": "st1", **body}, user=USER))
    assert e.value.status_code == 400 and msg in e.value.detail
    assert db.dewi_rnd_sample_requests.docs == []


def test_sample_pic_ubah(monkeypatch):
    smp, db = _sample_env(monkeypatch)
    db.dewi_rnd_sample_requests.docs = [{"id": "r1", "sample_pic": "Nama Lama"}]
    run(smp.update_sample_request("r1", {"sample_pic": "Nama Lama", "notes": "x"}, user=USER))   # lama tetap
    assert db.dewi_rnd_sample_requests.docs[0]["sample_pic"] == "Nama Lama"
    with pytest.raises(HTTPException):
        run(smp.update_sample_request("r1", {"sample_pic": "Nama Baru"}, user=USER))
    run(smp.update_sample_request("r1", {"sample_pic_employee_id": "e1"}, user=USER))
    d = db.dewi_rnd_sample_requests.docs[0]
    assert d["sample_pic_employee_id"] == "e1" and d["sample_pic"] == "Penjahit Sample"
