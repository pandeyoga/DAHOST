"""Aksi cepat Manajemen Katalog + harga jual resmi per SKU (klarifikasi owner 9 Nov 2026 §B & §D).

  B1  harga resmi = per SKU (`rahaza_materials.retail_price_master`) → cadangan harga model → 0; dipakai saat item
      dibuat, saat disegarkan, dan saat master model diubah (tanpa menimpa harga per SKU).
  B2  layar harga per SKU: daftar per model, simpan banyak sekaligus + riwayat; harga jual toko TIDAK berubah.
  D1  isi harga dari master (kosong saja / timpa) — pratinjau, riwayat harga, bisa dibatalkan.
  D2  rapikan item tersembunyi: kembar → salin harga/URL bila kosong → tayang bila URL sah → kembar diarsipkan;
      tunggal → dipasangkan ke katalog tokonya; pratinjau wajib sama dengan saat dijalankan; bisa dibatalkan.
  D3  tayangkan massal HANYA item yang punya URL sah sendiri.
  D4  unggah harga & URL dari Excel (pratinjau → terapkan).
  D5  status produk varian di baris katalog + penyaring.
  D6  kembalikan (restore) massal; aksi tanpa perubahan dilewati dengan alasan.
  D7  isi dari master: lewati Stop/Dead (bisa dimatikan), item tersembunyi dihitung "sudah ada".

Semua data SINTETIS (toko/SKU karangan).
"""
import asyncio
import io
import os
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
import auth  # noqa: E402
from core import catalog_runs as runs  # noqa: E402
from core import catalog_tools as tools  # noqa: E402
from core import product_master as pm  # noqa: E402
import routes.marketing_catalog_items as mci  # noqa: E402
import routes.marketing_catalog_tools as mct  # noqa: E402
import routes.rahaza_sku_prices as rsp  # noqa: E402

MGR = {"id": "u-mgr", "name": "Manajer Uji", "email": "mgr@uji", "role": "manager_marketing", "_role_perms": []}
STAF = {"id": "u-staf", "name": "Staf Uji", "email": "staf@uji", "role": "staff_marketing", "_role_perms": []}
VENDOR = {"id": "u-v", "name": "Vendor", "role": "cmt_vendor", "_role_perms": []}
PIC = {"id": "u-pic", "name": "PIC", "role": "pic_toko", "_role_perms": []}


def run(c):
    return asyncio.run(c)


def _import_mgmt():
    """Modul katalog membuat folder unggahan /app saat diimpor — pola uji lain (tanpa hak tulis /app)."""
    import pathlib
    orig = pathlib.Path.mkdir

    def _mkdir(self, *a, **k):
        try:
            return orig(self, *a, **k)
        except OSError:
            return None
    pathlib.Path.mkdir = _mkdir
    try:
        import routes.marketing_catalog_mgmt as cm
    finally:
        pathlib.Path.mkdir = orig
    return cm


def _db():
    db = FakeDB()
    db.marketing_platform_accounts.docs = [
        {"id": "acc-a", "account_code": "SHP-UJ1", "account_name": "Toko Uji Satu", "platform": "shopee"},
        {"id": "acc-b", "account_code": "TTK-UJ2", "account_name": "Toko Uji Dua", "platform": "tiktok"},
        {"id": "acc-c", "account_code": "SHP-UJ3", "account_name": "Toko Uji Tiga", "platform": "shopee"},
    ]
    db.marketing_catalogs.docs = [
        {"id": "cat-a", "account_id": "acc-a", "name": "Katalog Uji Satu", "platform": "shopee", "is_active": True},
        {"id": "cat-b", "account_id": "acc-b", "name": "Katalog Uji Dua", "platform": "tiktok", "is_active": True},
    ]
    db.rahaza_models.docs = [
        {"id": "m-1", "code": "UJA", "name": "Blus Uji", "active": True, "retail_price": 0},
        {"id": "m-2", "code": "UJB", "name": "Rok Uji", "active": True, "retail_price": 120000},
    ]
    db.rahaza_sizes.docs = [{"id": "s-s", "code": "S", "order_seq": 1}, {"id": "s-m", "code": "M", "order_seq": 2},
                            {"id": "s-l", "code": "L", "order_seq": 3}]
    db.rahaza_materials.docs = [
        {"id": "fg-1", "type": "fg", "code": "UJA-HTM-M", "model_id": "m-1", "color": "Hitam", "size_code": "M",
         "retail_price_master": 89000, "active": True, "name": "Blus Uji [Hitam · M]"},
        {"id": "fg-2", "type": "fg", "code": "UJA-HTM-S", "model_id": "m-1", "color": "Hitam", "size_code": "S",
         "retail_price_master": 85000, "active": True, "name": "Blus Uji [Hitam · S]"},
        {"id": "fg-3", "type": "fg", "code": "UJB-PTH-L", "model_id": "m-2", "color": "Putih", "size_code": "L",
         "retail_price_master": 0, "active": True, "name": "Rok Uji [Putih · L]"},
        {"id": "fg-4", "type": "fg", "code": "UJA-PTH-M", "model_id": "m-1", "color": "Putih", "size_code": "M",
         "active": True, "name": "Blus Uji [Putih · M]"},
    ]
    db.rahaza_model_variants.docs = [
        {"id": "v1", "model_id": "m-1", "sku": "UJA-HTM-M", "active": True, "product_status": "best_seller"},
        {"id": "v2", "model_id": "m-1", "sku": "UJA-HTM-S", "active": True, "product_status": "stop"},
        {"id": "v3", "model_id": "m-2", "sku": "UJB-PTH-L", "active": True, "product_status": "dead"},
        {"id": "v4", "model_id": "m-1", "sku": "UJA-PTH-M", "active": True},
    ]
    return db


@pytest.fixture
def env(monkeypatch):
    cm = _import_mgmt()
    db = _db()
    for m in (mci, mct, cm, rsp):
        monkeypatch.setattr(m, "get_db", lambda: db)

    async def _diam(*a, **k):
        return None
    for m in (mci, mct, cm, rsp):
        if hasattr(m, "log_activity"):
            monkeypatch.setattr(m, "log_activity", _diam)
    peran = {"u": MGR}

    def pakai(user):
        peran["u"] = user

        async def _f(request=None, *a, **k):
            return dict(user)
        for m in (mci, mct, cm, rsp, auth):
            if hasattr(m, "require_auth"):
                monkeypatch.setattr(m, "require_auth", _f)
    pakai(MGR)
    return {"db": db, "cm": cm, "pakai": pakai}


def _item(iid, cat, fg, sku, **kw):
    d = {"id": iid, "catalog_id": cat, "account_id": {"cat-a": "acc-a", "cat-b": "acc-b"}.get(cat, kw.pop("acc", None)),
         "fg_material_id": fg, "material_id": fg, "sku": sku, "name": f"Item {sku}", "is_active": True,
         "harga_jual": 0.0, "price": 0.0, "harga_coret": 0.0, "platform_url": "", "publish_state": "draft"}
    d.update(kw)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# B1 — harga resmi per SKU
# ══════════════════════════════════════════════════════════════════════════════
def test_urutan_harga_resmi_sku_lalu_model():
    assert pm.official_price({"retail_price_master": 89000}, {"retail_price": 100000}) == (89000.0, "sku")
    assert pm.official_price({"retail_price_master": 0}, {"retail_price": 100000}) == (100000.0, "model")
    assert pm.official_price({}, {}) == (0.0, "none")


def test_item_baru_dari_master_memakai_harga_per_sku(env):
    db = env["db"]
    cat = db.marketing_catalogs.docs[0]
    doc, err = run(mci.create_item_from_fg(db, cat, "fg-1", {}, MGR))
    assert err is None and doc["harga_jual"] == 89000 and doc["retail_price_source"] == "sku"
    doc, err = run(mci.create_item_from_fg(db, cat, "fg-3", {}, MGR))          # SKU kosong → harga model
    assert doc["harga_jual"] == 120000 and doc["retail_price_source"] == "model"
    doc, err = run(mci.create_item_from_fg(db, cat, "fg-2", {"harga_jual": 0, "price_mode": "kosong"}, MGR))
    assert doc["harga_jual"] == 0 and doc["retail_price_master"] == 85000     # "Kosongkan" tetap 0


def test_ubah_master_model_tidak_menimpa_harga_per_sku_di_katalog(env):
    db = env["db"]
    db.marketing_catalog_items.docs = [_item("i1", "cat-a", "fg-1", "UJA-HTM-M", model_id="m-1"),
                                       _item("i4", "cat-a", "fg-4", "UJA-PTH-M", model_id="m-1")]
    model = dict(db.rahaza_models.docs[0], retail_price=99000)
    run(pm.propagate_master_changes(db, model))
    it = {d["id"]: d for d in db.marketing_catalog_items.docs}
    assert it["i1"]["retail_price_master"] == 89000 and it["i1"]["retail_price_source"] == "sku"
    assert it["i4"]["retail_price_master"] == 99000 and it["i4"]["retail_price_source"] == "model"
    assert it["i1"]["harga_jual"] == 0                                          # harga toko tidak disentuh


# ══════════════════════════════════════════════════════════════════════════════
# D5 — status produk di baris katalog
# ══════════════════════════════════════════════════════════════════════════════
def test_daftar_item_membawa_status_produk_dan_bisa_disaring(env):
    db = env["db"]
    db.marketing_catalog_items.docs = [_item("i1", "cat-a", "fg-1", "UJA-HTM-M"), _item("i2", "cat-a", "fg-2", "UJA-HTM-S"),
                                       _item("i4", "cat-a", "fg-4", "UJA-PTH-M")]
    req = FakeRequest()
    out = run(mci.list_catalog_items("cat-a", req, limit=100))
    st = {r["sku"]: (r["product_status"], r["product_status_label"]) for r in out["items"]}
    assert st == {"UJA-HTM-M": ("best_seller", "Best Seller"), "UJA-HTM-S": ("stop", "Stop"),
                  "UJA-PTH-M": (None, "Belum diisi")}
    assert out["stock_summary"]["by_product_status"]["stop"] == 1
    # harga resmi master di baris = LIVE dari master per SKU (bukan salinan Rp 0 saat item dibuat)
    harga = {r["sku"]: (r["retail_price_master"], r["retail_price_source"]) for r in out["items"]}
    assert harga["UJA-HTM-M"] == (89000.0, "sku") and harga["UJA-PTH-M"] == (0.0, "none")
    assert out["stock_summary"]["by_product_status"]["belum_diisi"] == 1
    out = run(mci.list_catalog_items("cat-a", req, limit=100, product_status="stop,dead"))
    assert [r["sku"] for r in out["items"]] == ["UJA-HTM-S"]
    out = run(mci.list_catalog_items("cat-a", req, limit=100, product_status="belum_diisi"))
    assert [r["sku"] for r in out["items"]] == ["UJA-PTH-M"]
    with pytest.raises(HTTPException) as e:
        run(mci.list_catalog_items("cat-a", req, limit=100, product_status="laris"))
    assert e.value.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# D3/D6 — aksi massal penayangan
# ══════════════════════════════════════════════════════════════════════════════
def _bulk(action, ids, **kw):
    return mci.BulkTransitionBody(item_ids=ids, action=action, **kw)


def test_tayangkan_massal_hanya_yang_punya_url_sah_sendiri(env):
    db = env["db"]
    db.marketing_catalog_items.docs = [
        _item("i1", "cat-a", "fg-1", "UJA-HTM-M", platform_url="https://shopee.co.id/uji-1"),
        _item("i2", "cat-a", "fg-2", "UJA-HTM-S"),
        _item("i3", "cat-a", "fg-4", "UJA-PTH-M", platform_url="sudah tayang"),
        _item("i4", "cat-a", "fg-3", "UJB-PTH-L", platform_url="https://shopee.co.id/uji-4", publish_state="archived",
              is_active=False),
    ]
    req = FakeRequest()
    pv = run(mci.bulk_transition_items("cat-a", _bulk("publish", ["i1", "i2", "i3", "i4"], dry_run=True), req))
    assert pv["would_change"] == 1 and pv["skipped"] == 3
    assert pv["skip_summary"] == {"belum ada URL produk": 1, "URL produk tidak sah": 1,
                                  "diarsipkan — kembalikan dulu": 1}
    assert all(d["publish_state"] in ("draft", "archived") for d in db.marketing_catalog_items.docs)  # pratinjau
    out = run(mci.bulk_transition_items("cat-a", _bulk("publish", ["i1", "i2", "i3", "i4"]), req))
    it = {d["id"]: d for d in db.marketing_catalog_items.docs}
    assert out["changed"] == 1 and it["i1"]["publish_state"] == "published" and it["i2"]["publish_state"] == "draft"
    assert out["run_id"]
    # batalkan → kembali draf
    res = run(runs.undo(db, out["run_id"], MGR))
    assert res["restored"] == 1 and {d["id"]: d for d in db.marketing_catalog_items.docs}["i1"]["publish_state"] == "draft"
    with pytest.raises(runs.RunError):
        run(runs.undo(db, out["run_id"], MGR))                                  # tidak bisa dua kali


def test_kembalikan_dan_arsip_massal_melewati_yang_tidak_berubah(env):
    db = env["db"]
    db.marketing_catalog_items.docs = [
        _item("i1", "cat-a", "fg-1", "UJA-HTM-M", publish_state="archived", is_active=False),
        _item("i2", "cat-a", "fg-2", "UJA-HTM-S"),
    ]
    req = FakeRequest()
    out = run(mci.bulk_transition_items("cat-a", _bulk("restore", ["i1", "i2"]), req))
    assert out["changed"] == 1 and out["skip_summary"] == {"tidak diarsipkan": 1}
    it = {d["id"]: d for d in db.marketing_catalog_items.docs}
    assert it["i1"]["publish_state"] == "draft" and it["i1"]["is_active"] is True
    out = run(mci.bulk_transition_items("cat-a", _bulk("archive", ["i1", "i2"], reason="Stop"), req))
    assert out["changed"] == 2
    out = run(mci.bulk_transition_items("cat-a", _bulk("archive", ["i1"]), req))
    assert out["changed"] == 0 and out["skip_summary"] == {"sudah diarsipkan": 1} and out["run_id"] is None


def test_aksi_massal_dijaga_peran_dan_lingkup_toko(env):
    db = env["db"]
    db.marketing_catalog_items.docs = [_item("i1", "cat-a", "fg-1", "UJA-HTM-M")]
    env["pakai"](VENDOR)
    with pytest.raises(HTTPException) as e:
        run(mci.bulk_transition_items("cat-a", _bulk("archive", ["i1"]), FakeRequest()))
    assert e.value.status_code == 403
    env["pakai"](STAF)                                  # staf berlingkup toko, tidak di-assign ke toko ini
    with pytest.raises(HTTPException) as e:
        run(mci.archive_catalog_item("cat-a", "i1", mci.ReasonBody(reason=""), FakeRequest()))
    assert e.value.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# D1 — isi harga dari master
# ══════════════════════════════════════════════════════════════════════════════
def test_isi_harga_dari_master_kosong_saja_lalu_timpa_dan_batalkan(env):
    db = env["db"]
    db.marketing_catalog_items.docs = [
        _item("i1", "cat-a", "fg-1", "UJA-HTM-M"),                                  # kosong → 89.000 (SKU)
        _item("i2", "cat-a", "fg-2", "UJA-HTM-S", harga_jual=80000, price=80000),   # terisi
        _item("i3", "cat-a", "fg-3", "UJB-PTH-L"),                                  # SKU kosong → model 120.000
        _item("i5", "cat-a", None, "MANUAL-1"),                                     # belum tertaut
    ]
    db.marketing_catalog_items.docs[3]["material_id"] = None
    req = FakeRequest()
    body = mct.FillPriceBody(item_ids=["i1", "i2", "i3", "i5"], mode="kosong", dry_run=True)
    pv = run(mct.fill_price_from_master("cat-a", body, req))
    assert pv["would_change"] == 2 and pv["by_source"] == {"sku": 1, "model": 1}
    assert pv["skip_summary"] == {"harga jual sudah terisi": 1, "belum tertaut master": 1}
    assert db.marketing_catalog_items.docs[0]["harga_jual"] == 0                  # pratinjau tidak menulis
    out = run(mct.fill_price_from_master("cat-a", mct.FillPriceBody(item_ids=["i1", "i2", "i3", "i5"]), req))
    it = {d["id"]: d for d in db.marketing_catalog_items.docs}
    assert out["changed"] == 2 and it["i1"]["harga_jual"] == 89000 and it["i3"]["harga_jual"] == 120000
    assert it["i2"]["harga_jual"] == 80000
    log = [r for r in db.marketing_change_log.docs if r["action"] == "price_change"]
    assert {r["entity_id"] for r in log} == {"i1", "i3"} and "Isi harga dari master" in log[0]["reason"]
    out2 = run(mct.fill_price_from_master("cat-a", mct.FillPriceBody(item_ids=["i2"], mode="timpa"), req))
    assert out2["changed"] == 1 and {d["id"]: d for d in db.marketing_catalog_items.docs}["i2"]["harga_jual"] == 85000
    # batalkan aksi pertama: i1 & i3 kembali 0, riwayat harga mencatat pembatalan
    res = run(runs.undo(db, out["run_id"], MGR))
    it = {d["id"]: d for d in db.marketing_catalog_items.docs}
    assert res["restored"] == 2 and it["i1"]["harga_jual"] == 0 and it["i3"]["harga_jual"] == 0
    assert any(r["reason"].startswith("Batalkan") for r in db.marketing_change_log.docs)


def test_batalkan_tidak_menimpa_item_yang_sudah_diubah_orang_lain(env):
    db = env["db"]
    db.marketing_catalog_items.docs = [_item("i1", "cat-a", "fg-1", "UJA-HTM-M"), _item("i2", "cat-a", "fg-2", "UJA-HTM-S")]
    out = run(mct.fill_price_from_master("cat-a", mct.FillPriceBody(item_ids=["i1", "i2"]), FakeRequest()))
    db.marketing_catalog_items.docs[0]["harga_jual"] = 99000                       # diubah staf sesudahnya
    res = run(runs.undo(db, out["run_id"], MGR))
    it = {d["id"]: d for d in db.marketing_catalog_items.docs}
    assert res["restored"] == 1 and res["n_conflicts"] == 1 and "harga jual" in res["conflicts"][0]["why"]
    assert it["i1"]["harga_jual"] == 99000 and it["i2"]["harga_jual"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# D2 — rapikan item tersembunyi
# ══════════════════════════════════════════════════════════════════════════════
def _hidden(iid, acc, fg, sku, **kw):
    d = {"id": iid, "account_id": acc, "fg_material_id": fg, "material_id": fg, "sku": sku, "name": f"Impor {sku}",
         "source": "master_import", "harga_jual": 95000.0, "price": 95000.0, "harga_coret": 150000.0,
         "platform_url": f"https://shopee.co.id/{sku.lower()}", "is_active": True}
    d.update(kw)
    return d


def _seed_hidden(db):
    db.marketing_catalog_items.docs = [
        _item("v1", "cat-a", "fg-1", "UJA-HTM-M"),                                          # tampil, kosong
        _item("v2", "cat-a", "fg-2", "UJA-HTM-S", harga_jual=70000, price=70000,
              platform_url="https://shopee.co.id/punya-sendiri"),                            # tampil, terisi
        _hidden("h1", "acc-a", "fg-1", "UJA-HTM-M"),                                         # kembar v1
        _hidden("h2", "acc-a", "fg-2", "UJA-HTM-S"),                                         # kembar v2 (beda)
        _hidden("h3", "acc-b", "fg-3", "UJB-PTH-L"),                                         # tunggal → cat-b
        _hidden("h4", "acc-c", "fg-4", "UJA-PTH-M", platform_url=""),                        # tunggal, katalog baru
        _hidden("h5", "acc-a", "fg-4", "UJA-PTH-M", source="seed_demo"),                     # contoh → dibiarkan
    ]


def test_rapikan_item_tersembunyi_pratinjau_jalankan_batalkan(env):
    db = env["db"]
    _seed_hidden(db)
    req = FakeRequest()
    pv = run(mct.preview_hidden_items(req))
    s = pv["summary"]
    assert (s["hidden"], s["twins"], s["singles"], s["skipped"]) == (5, 2, 2, 1)
    assert (s["twins_copy_price"], s["twins_copy_url"], s["twins_publish"], s["twins_conflict"]) == (1, 1, 2, 1)
    assert s["singles_new_catalog"] == 1 and s["singles_publish"] == 1
    assert len(db.marketing_catalog_items.docs) == 7 and db.marketing_catalog_items.docs[0]["harga_jual"] == 0
    with pytest.raises(HTTPException) as e:                                              # pratinjau basi
        run(mct.apply_hidden_items(mct.HiddenApplyBody(expect_twins=1, expect_singles=2), req))
    assert e.value.status_code == 409
    out = run(mct.apply_hidden_items(mct.HiddenApplyBody(expect_twins=2, expect_singles=2), req))
    it = {d["id"]: d for d in db.marketing_catalog_items.docs}
    # kembar: harga/harga coret/URL disalin ke item tampil yang kosong → tayang; kembaran diarsipkan, tidak dihapus
    assert it["v1"]["harga_jual"] == 95000 and it["v1"]["harga_coret"] == 150000
    assert it["v1"]["platform_url"] == "https://shopee.co.id/uja-htm-m" and it["v1"]["publish_state"] == "published"
    assert it["v2"]["harga_jual"] == 70000 and it["v2"]["platform_url"] == "https://shopee.co.id/punya-sendiri"
    assert it["h1"]["publish_state"] == "archived" and it["h1"]["merged_into"] == "v1" and not it["h1"].get("catalog_id")
    # tunggal: dipasangkan ke katalog tokonya (atau katalog baru)
    assert it["h3"]["catalog_id"] == "cat-b" and it["h3"]["publish_state"] == "published"
    new_cat = it["h4"]["catalog_id"]
    assert new_cat and new_cat not in ("cat-a", "cat-b") and it["h4"]["publish_state"] == "draft"
    assert it["h5"].get("catalog_id") is None
    assert len(db.marketing_catalog_items.docs) == 7
    # batalkan: semua kembali, katalog baru yang kosong dihapus
    res = run(runs.undo(db, out["run_id"], MGR))
    it = {d["id"]: d for d in db.marketing_catalog_items.docs}
    assert res["n_conflicts"] == 0 and it["v1"]["harga_jual"] == 0 and it["v1"]["publish_state"] == "draft"
    assert it["h1"].get("publish_state") is None and it["h1"].get("merged_into") is None
    assert it["h3"].get("catalog_id") is None and res["removed_catalogs"] == [new_cat]
    assert not any(c["id"] == new_cat for c in db.marketing_catalogs.docs)
    pv2 = run(mct.preview_hidden_items(req))
    assert pv2["summary"]["twins"] == 2 and pv2["summary"]["singles"] == 2           # bisa diulang


def test_rapikan_hanya_untuk_pimpinan_marketing(env):
    env["pakai"](STAF)
    with pytest.raises(HTTPException) as e:
        run(mct.preview_hidden_items(FakeRequest()))
    assert e.value.status_code == 403


def test_isi_dari_master_menganggap_item_tersembunyi_sudah_ada(env):
    db = env["db"]
    db.marketing_catalog_items.docs = [_hidden("h1", "acc-a", "fg-1", "UJA-HTM-M")]
    doc, err = run(mci.create_item_from_fg(db, db.marketing_catalogs.docs[0], "fg-1", {}, MGR))
    assert doc is None and err[0] == 409 and "tersembunyi" in err[1]
    db.marketing_catalog_items.docs[0].update({"publish_state": "archived", "merged_into": "v-lain"})
    doc, err = run(mci.create_item_from_fg(db, db.marketing_catalogs.docs[0], "fg-1", {}, MGR))
    assert err is None                                                                  # kembar yang sudah dirapikan


# ══════════════════════════════════════════════════════════════════════════════
# D7 — isi dari master melewati Stop/Dead
# ══════════════════════════════════════════════════════════════════════════════
def test_isi_dari_master_melewati_stop_dead_kecuali_diminta(env):
    db, cm = env["db"], env["cm"]
    body = cm.AssignFromMasterBody(account_ids=["acc-a"], fg_material_ids=["fg-1", "fg-2", "fg-3"])
    out = run(cm.assign_from_master(body, FakeRequest()))
    assert out["summary"]["created"] == 1 and out["summary"]["skipped_status"] == 2
    notes = {n["fg_material_id"]: n for n in out["results"][0]["notes"]}
    assert "Stop" in notes["fg-2"]["why"] and "Dead" in notes["fg-3"]["why"]
    body = cm.AssignFromMasterBody(account_ids=["acc-a"], fg_material_ids=["fg-2"], include_stop_dead=True,
                                   price_mode="kosong")
    out = run(cm.assign_from_master(body, FakeRequest()))
    item = [d for d in db.marketing_catalog_items.docs if d.get("fg_material_id") == "fg-2"][0]
    assert out["summary"]["created"] == 1 and item["harga_jual"] == 0 and item["retail_price_master"] == 85000


def test_daftar_master_untuk_katalog_membawa_harga_sku_dan_status(env):
    db, cm = env["db"], env["cm"]
    db.marketing_catalog_items.docs = [_hidden("h1", "acc-a", "fg-1", "UJA-HTM-M")]
    out = run(cm.list_master_products_for_catalog(FakeRequest(), q=None, account_id="acc-a", only_sellable=False,
                                                  limit=60))
    p = {x["code"]: x for x in out["products"]}["UJA"]
    v = {x["code"]: x for x in p["variants"]}
    assert v["UJA-HTM-M"]["retail_price_master"] == 89000 and v["UJA-HTM-M"]["in_catalog"] is True
    assert v["UJA-HTM-M"]["in_catalog_hidden"] is True and v["UJA-HTM-S"]["product_status"] == "stop"
    assert p["retail_price_min"] == 85000 and p["retail_price_max"] == 89000 and p["stop_dead_count"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# D4 — unggah harga & URL dari Excel
# ══════════════════════════════════════════════════════════════════════════════
class _Up:
    def __init__(self, data, filename="harga.xlsx"):
        self._d, self.filename = data, filename

    async def read(self):
        return self._d


def _wb(rows, header=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = tools.SHEET
    ws.append(header or [lbl for _k, lbl in tools.COLUMNS])
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_angka_harga_dari_sel_excel():
    assert tools.parse_money(89000) == 89000 and tools.parse_money("89.000") == 89000
    assert tools.parse_money("Rp 89.000") == 89000 and tools.parse_money("89,000") == 89000
    assert tools.parse_money("89.000,50") == 89000.5 and tools.parse_money("") is None
    with pytest.raises(ValueError):
        tools.parse_money("gratis")


def test_unduh_lalu_unggah_harga_url(env):
    db = env["db"]
    db.marketing_catalog_items.docs = [
        _item("i1", "cat-a", "fg-1", "UJA-HTM-M"),
        _item("i2", "cat-a", "fg-2", "UJA-HTM-S"),
        _item("i3", "cat-b", "fg-3", "UJB-PTH-L", harga_jual=100000, price=100000),
    ]
    resp = run(mct.download_price_url_template(FakeRequest(), catalog_id=None))
    body = run(_body(resp))
    wb = openpyxl.load_workbook(io.BytesIO(body))
    rows = list(wb[tools.SHEET].iter_rows(values_only=True))
    head = list(rows[0])
    idx = {k: head.index(lbl) for k, lbl in tools.COLUMNS}
    by_sku = {r[idx["sku"]]: list(r) for r in rows[1:]}
    assert set(by_sku) == {"UJA-HTM-M", "UJA-HTM-S", "UJB-PTH-L"}
    assert by_sku["UJA-HTM-M"][idx["harga_resmi"]] == 89000 and by_sku["UJA-HTM-S"][idx["status_produk"]] == "Stop"
    # isi: i1 harga + URL sah (tayang), i2 URL tidak sah, i3 harga coret < harga jual
    by_sku["UJA-HTM-M"][idx["harga_jual"]] = "89.000"
    by_sku["UJA-HTM-M"][idx["url_produk"]] = "https://shopee.co.id/uji-m"
    by_sku["UJA-HTM-S"][idx["url_produk"]] = "toko kami"
    by_sku["UJB-PTH-L"][idx["harga_coret"]] = 90000
    data = _wb(by_sku.values(), header=head)
    pv = run(mct.upload_price_url(FakeRequest(), file=_Up(data), catalog_id=None, apply=False, publish=True))
    assert pv["summary"]["changes"] == 1 and pv["summary"]["publish"] == 1 and pv["summary"]["errors"] == 2
    assert any("URL produk tidak sah" in e for e in pv["errors"]) and any("harga coret" in e for e in pv["errors"])
    assert db.marketing_catalog_items.docs[0]["harga_jual"] == 0                       # pratinjau
    out = run(mct.upload_price_url(FakeRequest(), file=_Up(data), catalog_id=None, apply=True, publish=True))
    it = {d["id"]: d for d in db.marketing_catalog_items.docs}
    assert it["i1"]["harga_jual"] == 89000 and it["i1"]["publish_state"] == "published"
    assert it["i1"]["platform_url"] == "https://shopee.co.id/uji-m" and out["run_id"]
    # tanpa kolom ID: cocokkan Toko + SKU
    data2 = _wb([["", "TTK-UJ2", "", "UJB-PTH-L", "", "", "", "", "", 115000, "", ""]])
    out = run(mct.upload_price_url(FakeRequest(), file=_Up(data2), catalog_id=None, apply=True, publish=False))
    assert out["summary"]["changes"] == 1 and {d["id"]: d for d in db.marketing_catalog_items.docs}["i3"]["harga_jual"] == 115000


async def _body(resp):
    out = []
    async for c in resp.body_iterator:
        out.append(c if isinstance(c, bytes) else c.encode())
    return b"".join(out)


# ══════════════════════════════════════════════════════════════════════════════
# B2 — layar harga jual per SKU
# ══════════════════════════════════════════════════════════════════════════════
def test_daftar_harga_sku_per_model_dan_saringan(env):
    out = run(rsp.list_sku_prices(FakeRequest(), q=None, harga=None, product_status=None, model_id=None))
    m = {x["code"]: x for x in out["models"]}
    assert [v["sku"] for v in m["UJA"]["variants"]] == ["UJA-HTM-S", "UJA-HTM-M", "UJA-PTH-M"]   # warna, ukuran
    assert m["UJA"]["priced_count"] == 2 and m["UJA"]["price_min"] == 85000 and m["UJB"]["model_retail_price"] == 120000
    assert out["totals"] == {"models": 2, "skus": 4, "priced": 2, "empty": 2}
    out = run(rsp.list_sku_prices(FakeRequest(), q=None, harga="kosong", product_status=None, model_id=None))
    assert sorted(v["sku"] for x in out["models"] for v in x["variants"]) == ["UJA-PTH-M", "UJB-PTH-L"]
    out = run(rsp.list_sku_prices(FakeRequest(), q="htm-s", harga=None, product_status=None, model_id=None))
    assert [v["sku"] for x in out["models"] for v in x["variants"]] == ["UJA-HTM-S"]
    out = run(rsp.list_sku_prices(FakeRequest(), q=None, harga=None, product_status="belum_diisi", model_id=None))
    assert [v["sku"] for x in out["models"] for v in x["variants"]] == ["UJA-PTH-M"]


def test_simpan_harga_sku_mencatat_riwayat_dan_tidak_mengubah_harga_toko(env):
    db = env["db"]
    db.marketing_catalog_items.docs = [_item("i4", "cat-a", "fg-4", "UJA-PTH-M", harga_jual=50000, price=50000)]
    body = rsp.SkuPriceSaveBody(changes=[{"fg_id": "fg-4", "harga": 92000}, {"fg_id": "fg-1", "harga": 89000}],
                                reason="harga baru Nov")
    out = run(rsp.save_sku_prices(body, FakeRequest()))
    assert out["changed"] == 1 and out["unchanged"] == 1
    fg = {d["id"]: d for d in db.rahaza_materials.docs}
    assert fg["fg-4"]["retail_price_master"] == 92000 and fg["fg-4"]["retail_price_updated_by"] == "Manajer Uji"
    hist = db.rahaza_sku_price_history.docs
    assert len(hist) == 1 and hist[0]["before"] == 0 and hist[0]["after"] == 92000 and hist[0]["sku"] == "UJA-PTH-M"
    it = db.marketing_catalog_items.docs[0]
    assert it["retail_price_master"] == 92000 and it["retail_price_source"] == "sku" and it["harga_jual"] == 50000
    h = run(rsp.sku_price_history(FakeRequest(), model_id="m-1", sku=None, limit=50))
    assert h["history"][0]["after"] == 92000
    env["pakai"](PIC)
    with pytest.raises(HTTPException) as e:
        run(rsp.save_sku_prices(body, FakeRequest()))
    assert e.value.status_code == 403
