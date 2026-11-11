"""Impor ekspor Shopee & TikTok toko sendiri (owner 11 Nov 2026, "Ya, semua rekomendasi").

Berkas asli toko (Shopee GHS, TikTok Rayona) membuktikan dua cacat:

  1. Ekspor TikTok berbahasa Indonesia menulis kolom "Purchase Channel" = "Aplikasi TikTok".
     Penjaga platform hanya mengenal "TikTok" ⇒ SELURUH berkas toko TikTok yang benar ditolak.
  2. SKU penjual = NOMOR MODEL tanpa awalan CV ("1512" = DA-1512), variasi = warna + ukuran.
     Mesin usulan menebak model dari judul ("celana" di judul MELA → "Stela celana") dan warna
     lewat kamus umum ("Red Elegant" → "Pita merah"); "Petakan otomatis" menulis ±25 dari 39
     tautan salah. Aturan sekarang: tautan OTOMATIS hanya bila SKU penjual menunjuk tepat satu
     model DAN warna + ukuran menunjuk tepat satu varian; tebakan judul = usulan saja.
  3. Item katalog hasil impor master 12 Sep tidak punya `catalog_id` ⇒ impor ulang (ekspor
     7 hari sesudah 28 hari) menimpa tautan yang sudah benar menjadi "tak tertaut".

Semua data di sini SINTETIS (tidak ada data pembeli).
"""
import pytest

from _mkt_uji import DB, acc, csv_bytes, import_file, patch_import, run  # noqa: E402
from core import marketing_import_engine as eng
from core import sku_bridge as sb
from core.marketing_import_schema import get_source_type

MO = get_source_type("marketplace_orders")


# ── master sintetis yang meniru bentuk master DA ────────────────────────────────────────────────
def _v(mc, name, color, size, cc):
    return {"id": f"v-{mc}-{cc}-{size}", "sku": f"{mc}-{cc}-{size}", "model_id": f"m-{mc}",
            "model_code": mc, "model_name": name, "color_name": color, "size_code": size,
            "active": True}


VARIANTS = [
    _v("DA-1512", "MELA", "Red Elegant", "M", "RDE"),
    _v("DA-1512", "MELA", "Pita merah", "M", "PMR"),
    _v("DA-1512", "MELA", "Blue Elegan", "M", "BLE"),
    _v("DA-1512", "MELA", "Digital Bunga Emas", "M", "DGB"),
    _v("DA-1502", "Stela set", "Digital Bunga Emas", "XL", "DGB"),
    _v("DA-1502", "Stela set", "Asflow", "XL", "ASF"),
    _v("DA-1201", "Lunara", "MOCA", "ALLSIZE", "MCA"),
    _v("DA-1201", "Lunara", "DUSTY", "ALLSIZE", "DST"),
    _v("DA-4301", "Mave", "PUTIH", "M", "PTH"),
    _v("DA-4301", "Mave", "HITAM", "M", "HTM"),
    _v("DA-4302", "Mave", "PUTIH", "XL", "PTH"),
    _v("DA-5501", "Stela celana", "Digital Paint abstrak", "M", "DGP"),
    _v("DA-5501", "Stela celana", "Brown Abstrak", "M", "BRB"),
    _v("DA-5501", "Stela celana", "Pita merah", "M", "PMR"),
    _v("DA-3501", "Jennifer Blouse", "polkadot hitam", "M", "PHT"),
    _v("DA-3501", "Jennifer Blouse", "HITAM", "M", "HTM"),
    _v("DA-3501", "Jennifer Blouse", "HITAM", "XL", "HTM"),
]


def _pool(variants=VARIANTS):
    db = DB()
    db.rahaza_model_variants.docs.extend([dict(v) for v in variants])
    return run(sb.kode_pool(db))


# ── 1. "Aplikasi TikTok" ─────────────────────────────────────────────────────────────────────────
def test_kanal_aplikasi_tiktok_dibaca_tiktok():
    assert eng.kanal_platform("Aplikasi TikTok") == "tiktok"
    assert eng.kanal_platform("TikTok") == "tiktok"
    assert eng.kanal_platform("Tokopedia") == "tokopedia"
    assert eng.kanal_platform("") == ""


def test_penjaga_platform_menerima_aplikasi_tiktok_hanya_untuk_toko_tiktok():
    import routes.marketing_data_import as md
    assert md._platform_matches("tiktok", "Aplikasi TikTok")
    assert md._platform_matches("tiktok", "TikTok")
    assert not md._platform_matches("shopee", "Aplikasi TikTok")


HDR = ["Order ID", "Order Status", "SKU ID", "Seller SKU", "Product Name", "Variation", "Quantity",
       "SKU Unit Original Price", "SKU Subtotal Before Discount", "SKU Seller Discount",
       "SKU Platform Discount", "SKU Subtotal After Discount", "Order Amount", "Created Time",
       "Paid Time", "Purchase Channel", "Order Channel"]


def _tiktok(rows, kanal="Aplikasi TikTok"):
    out = [HDR]
    for oid, psid, ss, var, qty in rows:
        out.append([oid, "Selesai", psid, ss, "MELA ONE SET RAYON WANITA | One Set Baju Celana Pendek",
                    var, qty, "119999", str(119999 * qty), str(60000 * qty), "0",
                    str(59999 * qty), str(59999 * qty + 8000), "03/11/2026 10:00:00",
                    "03/11/2026 10:05:00", kanal, "Videos"])
    return csv_bytes(out)


def test_baris_aplikasi_tiktok_menjadi_kanal_tiktok_dengan_nilai_asli_tersimpan():
    raw = _tiktok([("T1", "P1", "1512", "Red Elegant, M / STANDAR", 1)])
    headers, rows = eng.parse_table(raw, "harian.csv", MO)
    built = eng.build_rows(rows, eng.auto_map(headers, MO), MO)
    d = built[0]["data"]
    assert built[0]["status"] != "error", built[0]["errors"]
    assert d["purchase_channel"] == "TikTok" and d["sales_channel"] == "tiktok"
    assert d["purchase_channel_raw"] == "Aplikasi TikTok"


# ── 2. kode model + warna + ukuran ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ss, var, pname, sku, cara", [
    ("1512", "Red Elegant, M / STANDAR", "", "DA-1512-RDE-M", "sama"),
    ("1512", "Blue Elegant, M / STANDAR", "", "DA-1512-BLE-M", "mirip"),        # salah ketik master
    ("1502", "Bunga Emas", "", "DA-1502-DGB-XL", "termuat"),                   # model 1 ukuran
    ("1201", "LUNARA - MOCA", "LUNARA ONE SET X HAFIZA", "DA-1201-MCA-ALLSIZE", "sama"),
    ("4301", "WHITE, M / STANDAR", "MAVE VEST - Atasan", "DA-4301-PTH-M", "terjemahan"),
    ("DA-1512-PMR-M", "apa saja", "", "DA-1512-PMR-M", "sku_varian"),
])
def test_kode_model_menunjuk_varian_pasti(ss, var, pname, sku, cara):
    km = sb.cocok_kode_model(_pool(), ss, var, pname)
    assert km["variant"] and km["variant"]["sku"] == sku, km
    assert km["cara"] == cara


@pytest.mark.parametrize("ss, var, model, alasan", [
    ("1512", "Reject Sale, M / STANDAR", "DA-1512", "tidak ada di model"),   # warna baru
    ("5501", "Abstrak", "DA-5501", "lebih dari satu"),                        # ragu → manusia
    ("3501", "HITAM", "DA-3501", "ukuran tidak terbaca"),                      # 2 ukuran, tak tertulis
    ("10202", "AISAR - CARAMEL", "", "bukan kode model"),                     # SKU Shopee ≠ master
    ("", "Red Elegant, M", "", "kosong"),
])
def test_kode_model_tidak_menebak(ss, var, model, alasan):
    km = sb.cocok_kode_model(_pool(), ss, var)
    assert km["variant"] is None
    assert km["model_code"] == model
    assert alasan in km["alasan"]


def test_kode_model_ganda_antar_cv_tidak_ditautkan():
    pool = _pool(VARIANTS + [_v("SMU-1512", "MELA SMU", "Red Elegant", "M", "RDE")])
    km = sb.cocok_kode_model(pool, "1512", "Red Elegant, M")
    assert km["variant"] is None and "beberapa model" in km["alasan"]


def test_usulan_kode_model_mengalahkan_tebakan_judul():
    db = DB()
    db.rahaza_model_variants.docs.extend([dict(v) for v in VARIANTS])
    db.rahaza_models.docs.extend([{"id": f"m-{c}", "code": c, "name": n, "active": True} for c, n in
                                  {(v["model_code"], v["model_name"]) for v in VARIANTS}])
    # judul MELA memuat "celana": tanpa SKU penjual tebakan judul ≠ MELA
    sg = run(sb.suggest(db, product_name="MELA ONE SET RAYON | Baju Celana Pendek Stela",
                        variation="Red Elegant, M / STANDAR", seller_sku="1512"))
    mm = sg["model_match"]
    assert mm["source"] == sb.SUMBER_KODE and mm["variant_sku"] == "DA-1512-RDE-M"
    assert sg["recommended_action"] == "map" and mm["match_confidence"] == 1.0
    tebak = run(sb.suggest(db, product_name="Stela celana Brown Abstrak", variation="Brown Abstrak, M"))
    assert (tebak["model_match"] or {}).get("source") == sb.SUMBER_NAMA


def _db_toko(catalog_id: bool):
    """Toko TikTok + master + FG + item katalog (opsional TANPA catalog_id, seperti data 12 Sep)."""
    db = DB()
    db.marketing_platform_accounts.docs.append(acc("TTK-03", platform="tiktok"))
    db.marketing_catalogs.docs.append({"id": "cat-TTK-03", "account_id": "TTK-03", "name": "Katalog"})
    db.rahaza_model_variants.docs.extend([dict(v) for v in VARIANTS])
    db.rahaza_models.docs.extend([{"id": f"m-{c}", "code": c, "name": n, "active": True} for c, n in
                                  {(v["model_code"], v["model_name"]) for v in VARIANTS}])
    for v in VARIANTS:
        if not v["sku"].startswith("DA-1512"):
            continue
        fg = {"id": f"fg-{v['sku']}", "code": v["sku"], "sku": v["sku"], "type": "fg",
              "variant_id": v["id"], "model_id": v["model_id"], "name": v["model_name"], "hpp": 30000}
        db.rahaza_materials.docs.append(fg)
        it = {"id": f"it-{v['sku']}", "account_id": "TTK-03", "sku": v["sku"], "name": v["model_name"],
              "fg_material_id": fg["id"], "variant_id": v["id"], "model_id": v["model_id"],
              "hpp": 30000, "is_active": True}
        if catalog_id:
            it["catalog_id"] = "cat-TTK-03"
        db.marketing_catalog_items.docs.append(it)
    return db


def _lines(db, oid):
    d = next(o for o in db.marketing_orders.docs if o["order_id"] == oid)
    return {it.get("variation_raw"): it for it in d["items"]}


@pytest.mark.parametrize("catalog_id", [True, False])
def test_impor_menautkan_pasti_dan_impor_ulang_tidak_melepas_tautan(monkeypatch, catalog_id):
    db = _db_toko(catalog_id)
    md = patch_import(monkeypatch, db)
    rows = [("T1", "P-RDE", "1512", "Red Elegant, M / STANDAR", 1),
            ("T2", "P-RJ", "1512", "Reject Sale, M / STANDAR", 1),   # warna baru → tetap menunggu
            ("T3", "P-X", "", "Red Elegant, M / STANDAR", 1)]       # tanpa SKU penjual → menunggu
    _sid, res = run(import_file(md, _tiktok(rows), "28hari.csv", "marketplace_orders", "TTK-03"))
    assert res["inserted"] == 3
    tk = res["tautan_kode_model"]
    assert tk["ditautkan"] == 1 and tk["pesanan_diperbarui"] == 1
    assert "lewat kode model" in res["message"]
    assert _lines(db, "T1")["Red Elegant, M / STANDAR"]["fg_material_id"] == "fg-DA-1512-RDE-M"
    assert not _lines(db, "T2")["Reject Sale, M / STANDAR"].get("fg_material_id")
    assert not _lines(db, "T3")["Red Elegant, M / STANDAR"].get("fg_material_id")
    br = next(b for b in db.marketing_sku_bridge.docs if b["platform_sku_id"] == "P-RDE")
    assert br["method"] == sb.METODE_KODE
    # ekspor 7 hari berisi pesanan yang sama: tautan TIDAK boleh lepas (dulu lepas bila item
    # katalog tidak punya catalog_id)
    _sid2, res2 = run(import_file(md, _tiktok(rows[:1]), "7hari.csv", "marketplace_orders", "TTK-03",
                                  on_duplicate="update"))
    assert res2["updated"] == 1
    assert _lines(db, "T1")["Red Elegant, M / STANDAR"]["fg_material_id"] == "fg-DA-1512-RDE-M"


def test_tautan_buatan_manusia_tidak_ditimpa(monkeypatch):
    db = _db_toko(True)
    db.marketing_sku_bridge.docs.append({"platform_sku_id": "P-RDE", "active": True, "method": "manual",
                                         "catalog_item_id": "it-DA-1512-PMR-M",
                                         "fg_material_id": "fg-DA-1512-PMR-M"})
    db.marketing_catalog_items.docs[1].setdefault("platform_sku_ids", []).append("P-RDE")
    md = patch_import(monkeypatch, db)
    _sid, res = run(import_file(md, _tiktok([("T1", "P-RDE", "1512", "Red Elegant, M / STANDAR", 1)]),
                                "a.csv", "marketplace_orders", "TTK-03"))
    # baris tertaut lewat pemetaan manusia saat impor; aturan kode model tidak menyentuhnya
    assert _lines(db, "T1")["Red Elegant, M / STANDAR"]["fg_material_id"] == "fg-DA-1512-PMR-M"
    assert (res["tautan_kode_model"] or {}).get("ditautkan", 0) == 0
    assert next(b for b in db.marketing_sku_bridge.docs if b["platform_sku_id"] == "P-RDE")["method"] == "manual"


def test_petakan_otomatis_dan_selesaikan_massal_tidak_menulis_tebakan_judul(monkeypatch):
    db = _db_toko(True)
    # baris tanpa SKU penjual yang judul+warna+ukurannya PERSIS satu varian (tebakan "yakin"
    # 100% — dulu ditulis otomatis)
    db.marketing_orders.docs.append({
        "id": "o1", "order_id": "X1", "account_id": "TTK-03", "items": [
            {"platform_sku_id": "P-TEBAK", "seller_sku": "", "quantity": 2,
             "product_name_raw": "Jennifer Blouse", "variation_raw": "HITAM, M"},
            {"platform_sku_id": "P-KODE", "seller_sku": "1512", "quantity": 1,
             "product_name_raw": "MELA ONE SET", "variation_raw": "Pita Merah, M / STANDAR"}]})
    am = run(sb.auto_map(db, account_id="TTK-03", dry_run=True))
    assert [a["platform_sku_id"] for a in am["applied"]] == ["P-KODE"]
    assert am["applied"][0]["target_sku"] == "DA-1512-PMR-M"
    bulk = run(sb.bulk_resolve(db, actions=("map", "create_variant"), account_id="TTK-03", dry_run=True))
    assert [a["platform_sku_id"] for a in bulk["applied"]] == ["P-KODE"]
    sisa = next(s for s in bulk["skipped"] if s["platform_sku_id"] == "P-TEBAK")
    assert "ditebak dari judul" in sisa["reason"]
