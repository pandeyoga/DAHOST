"""MKT-INTI · tautan barang pesanan impor (audit Gudang × Pesanan 9 Nov 2026, G2–G4).

  G2  Ekspor Shopee ASLI: "Nomor Referensi SKU" → SKU Penjual, "SKU Induk" TIDAK ke SKU ID
      Platform; ingatan pemetaan lama yang salah dibuang (RETIRED_MAPPINGS). TikTok asli tetap.
  G3  Tautan lewat nama hanya bila nama + variasi menunjuk tepat satu item katalog toko
      (UJI-T4 "Kulot Rayon Panjang / Maroon,M" dulu tertaut ke DA-5504-MRN-XL).
  G4  Baris tanpa SKU platform muncul di Jembatan SKU/Pemetaan SKU dengan kunci nama+variasi;
      memetakannya menautkan pesanan & retur lama, dan impor berikutnya ikut tertaut.
"""
import pytest

from _mkt_uji import DB, SAMPLES, acc, csv_bytes, import_file, patch_import, run  # noqa: E402
from core import sku_kunci as K
from core import marketing_import_engine as eng
from core.marketing_import_schema import get_source_type, is_retired_mapping

SHOPEE = SAMPLES / "order_pesanan_shopee.xlsx"
TIKTOK = SAMPLES / "pesanan_tiktok.xlsx"


def _map(path):
    st = get_source_type("marketplace_orders")
    h, _rows = eng.parse_table(path.read_bytes(), path.name, st)
    return {m["column"]: m["field"] for m in eng.auto_map(h, st)}


# ── G2 ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not SHOPEE.exists(), reason="berkas contoh Shopee tidak ada")
def test_g2_kolom_sku_shopee_asli_dipetakan_benar():
    m = _map(SHOPEE)
    assert m["Nomor Referensi SKU"] == "seller_sku"
    assert m["SKU Induk"] == "parent_sku"
    assert "platform_sku_id" not in m.values()
    assert m["Paket Diskon (Diskon dari Penjual)"] == "bundle_discount_seller"   # Q-1
    assert m["Voucher Ditanggung Penjual"] == "voucher_seller"


@pytest.mark.skipif(not TIKTOK.exists(), reason="berkas contoh TikTok tidak ada")
def test_g2_kolom_sku_tiktok_asli_tidak_berubah():
    m = _map(TIKTOK)
    assert m["SKU ID"] == "platform_sku_id" and m["Seller SKU"] == "seller_sku"


def test_g2_ingatan_pemetaan_lama_yang_salah_dibuang():
    assert is_retired_mapping("marketplace_orders", "sku induk", "platform_sku_id")
    assert is_retired_mapping("marketplace_orders", "nomor referensi sku", "platform_sku_id")
    assert not is_retired_mapping("marketplace_orders", "nomor referensi sku", "seller_sku")


# ── G3 ─────────────────────────────────────────────────────────────────────────────────────────
KULOT = [
    {"id": "it-m", "name": "Kulot Rayon Panjang", "sku": "DA-5503-MRN-M", "fg_color": "Maroon",
     "fg_size": "M", "fg_material_id": "fg-m"},
    {"id": "it-xl", "name": "Kulot Rayon Panjang", "sku": "DA-5504-MRN-XL", "fg_color": "Maroon",
     "fg_size": "XL", "fg_material_id": "fg-xl"},
    {"id": "it-hm", "name": "Kulot Rayon Panjang", "sku": "DA-5503-HTM-M", "fg_color": "Hitam",
     "fg_size": "M", "fg_material_id": "fg-hm"},
]


def test_g3_nama_plus_variasi_memilih_varian_yang_benar():
    idx = K.indeks_nama(KULOT)
    it, why = K.pilih_lewat_nama(idx, "KULOT RAYON PANJANG", "Maroon,M")
    assert it["sku"] == "DA-5503-MRN-M" and why == ""
    it, _ = K.pilih_lewat_nama(idx, "Kulot Rayon Panjang", "Maroon, XL")
    assert it["sku"] == "DA-5504-MRN-XL"


def test_g3_variasi_kosong_atau_asing_dibiarkan_tak_tertaut_dengan_alasan():
    idx = K.indeks_nama(KULOT)
    for var in ("", "Navy,L", "Maroon"):
        it, why = K.pilih_lewat_nama(idx, "Kulot Rayon Panjang", var)
        assert it is None and "Jembatan SKU" in why and "Pemetaan SKU" not in why
    # nama unik tanpa atribut varian = boleh
    it, why = K.pilih_lewat_nama(K.indeks_nama([{"id": "x", "name": "Tas Kanvas"}]), "tas kanvas", "")
    assert it["id"] == "x"
    # berkas tanpa kolom variasi (rincian live): nama harus unik
    it, why = K.pilih_lewat_nama(idx, "Kulot Rayon Panjang", punya_variasi=False)
    assert it is None and "3 item" in why


def _catalog(db, aid, items):
    db.marketing_catalogs.docs.append({"id": f"cat-{aid}", "account_id": aid, "name": "Katalog"})
    for it in items:
        db.marketing_catalog_items.docs.append({**it, "catalog_id": f"cat-{aid}", "account_id": aid,
                                                "is_active": True})


SHP_HDR = ["No. Pesanan", "Status Pesanan", "Waktu Pesanan Dibuat", "Waktu Pembayaran Dilakukan",
           "SKU Induk", "Nama Produk", "Nomor Referensi SKU", "Nama Variasi", "Harga Awal",
           "Harga Setelah Diskon", "Jumlah", "Subtotal Pesanan", "Total Pembayaran"]


def _shopee(rows):
    out = [SHP_HDR]
    for oid, name, ref, var, qty in rows:
        out.append([oid, "Perlu Dikirim", "2026-08-05 10:00", "2026-08-05 10:05", "INDUK-1", name, ref,
                    var, "100.000", "80.000", qty, str(80000 * qty), str(80000 * qty + 8000)])
    return csv_bytes(out)


@pytest.fixture
def env(monkeypatch):
    db = DB()
    db.marketing_platform_accounts.docs.append(acc("SHP-01", platform="shopee"))
    _catalog(db, "SHP-01", KULOT)
    md = patch_import(monkeypatch, db)
    return db, md


def test_g2_g3_impor_shopee_nomor_referensi_sku_dan_nama_variasi(env):
    db, md = env
    raw = _shopee([("S1", "Kulot Rayon Panjang", "DA-5503-HTM-M", "Hitam,M", 1),     # lewat SKU
                   ("S2", "Kulot Rayon Panjang", "", "Maroon,M", 1),                # lewat nama+var
                   ("S3", "Kulot Rayon Panjang", "", "Navy,L", 2)])                 # tak tertaut
    _sid, res = run(import_file(md, raw, "Order.all.csv", "marketplace_orders", "SHP-01"))
    assert res["inserted"] == 3
    link = {d["order_id"]: (d["items"][0].get("catalog_item_id"), d["items"][0]["master_link_source"])
            for d in db.marketing_orders.docs}
    assert link["S1"] == ("it-hm", "sku_exact")
    assert link["S2"] == ("it-m", "name_match")                   # dulu varian XL yang salah
    assert link["S3"] == (None, "unlinked")
    assert any("Jembatan SKU" in " ".join(n.get("why") or []) for n in res["row_notes"])


# ── G4 ─────────────────────────────────────────────────────────────────────────────────────────
def test_g4_baris_tanpa_sku_bisa_dipetakan_dan_diterapkan_ke_pesanan_retur_lama(env):
    from core import sku_bridge as sb
    db, md = env
    raw = _shopee([("S3", "Kulot Rayon Panjang", "", "Navy,L", 2),
                   ("S4", "Kulot Rayon Panjang", "", "Navy,L", 1)])
    run(import_file(md, raw, "a.csv", "marketplace_orders", "SHP-01"))
    db.marketing_returns.docs.append({"id": "r1", "account_id": "SHP-01", "product": "Kulot Rayon Panjang",
                                      "variation": "Navy,L", "catalog_item_id": None})
    un = run(sb.list_unmapped(db, account_id="SHP-01"))
    assert un["total"] == 1                                      # dulu 0 (hanya membaca platform_sku_id)
    row = un["rows"][0]
    assert K.kunci_nama(row["platform_sku_id"]) and row["pcs"] == 3
    assert "Tanpa SKU platform" in row["sku_label"] and "nv:" not in row["sku_label"]
    db.marketing_catalog_items.docs.append({"id": "it-nv", "name": "Kulot Rayon Panjang", "sku": "DA-NVY-L",
                                            "fg_color": "Navy", "fg_size": "L", "fg_material_id": "fg-nv",
                                            "catalog_id": "cat-SHP-01", "account_id": "SHP-01"})
    res = run(sb.apply_mapping(db, row["platform_sku_id"], catalog_item_id="it-nv", user={"name": "uji"}))
    assert res["ok"] and res["orders_updated"] == 2
    assert all(d["items"][0]["fg_material_id"] == "fg-nv" for d in db.marketing_orders.docs)
    assert db.marketing_returns.docs[0]["catalog_item_id"] == "it-nv"
    item = next(i for i in db.marketing_catalog_items.docs if i["id"] == "it-nv")
    assert row["platform_sku_id"] in item["bridge_keys"]
    assert "platform_sku_ids" not in item                         # kunci nama ≠ SKU platform
    # impor BERIKUTNYA ikut tertaut lewat kunci yang disimpan
    run(import_file(md, _shopee([("S5", "Kulot Rayon Panjang", "", "Navy,L", 1)]), "b.csv",
                    "marketplace_orders", "SHP-01"))
    s5 = next(d for d in db.marketing_orders.docs if d["order_id"] == "S5")
    assert s5["items"][0]["catalog_item_id"] == "it-nv" and s5["items"][0]["master_link_source"] == "sku_map"
    # lepas pemetaan → pesanan kembali tak tertaut
    out = run(sb.remove_mapping(db, row["platform_sku_id"]))
    assert out["ok"] and out["orders_updated"] == 3


def test_g4_pemetaan_sku_wizard_mengelompokkan_baris_tanpa_sku(env):
    from _mkt_uji import request_for, SA
    db, md = env
    raw = _shopee([("S6", "Kulot Rayon Panjang", "", "Navy,L", 1)])
    sid, _ = run(import_file(md, raw, "c.csv", "marketplace_orders", "SHP-01"))
    out = run(md.sku_map_list(sid, request_for(SA), only_unlinked=True))
    assert out["unmapped_total"] == 1 and out["unmapped"][0]["key_kind"] == "nama_variasi"
    key = out["unmapped"][0]["platform_sku_id"]
    db.marketing_catalog_items.docs.append({"id": "it-nv", "name": "Kulot Rayon Panjang",
                                            "fg_material_id": "fg-nv", "catalog_id": "cat-SHP-01"})
    res = run(md.sku_map_save(sid, request_for(SA), [md.SkuMapIn(platform_sku_id=key,
                                                                  catalog_item_id="it-nv")]))
    assert res["mapped"] == 1 and res["orders_updated"] == 1
