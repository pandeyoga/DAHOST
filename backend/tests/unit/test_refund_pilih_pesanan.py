"""Uji unit HERMETIK — "Buat refund" wajib pesanan + Usulan AI Jembatan SKU (14 Nov 2026).

A. Form "Buat refund" (Portal Marketing › Komplain & Retur) = "Catat retur" gudang (keputusan owner 10 Nov):
   * pesanan WAJIB dipilih dari `marketing_orders` (lingkup toko pemakai) — tanpa pesanan ⇒ 400;
   * toko, nomor pesanan, barang, harga satuan, qty maksimum turunan baris pesanan;
   * baris belum tertaut / baru tertaut MODEL wajib varian pilihan staf → disimpan lewat
     `sku_bridge.apply_mapping` (method `retur`) — jalur resmi Jembatan SKU;
   * satu baris pesanan tidak boleh direfund dua kali (409), qty ≤ qty baris;
   * Retur Fisik gudang otomatis menunjuk pesanan + BARIS yang sama (dan menautkan retur manual yang ada).
B. Usulan AI Jembatan SKU (`core/sku_usulan.py`):
   * pencocokan pasti bersinonim (POLKA BLACK = Polkadot Hitam, Bunga Mas = Digital Bunga Emas, Mocca = Moca,
     WHITE = Putih, LD 120 CM = XL dari pesanan lain model itu);
   * tidak bisa dipetakan (SKU kosong, Reject Sale, Default) dengan saran;
   * AI hanya mengusulkan dari daftar varian model; nomor di luar daftar ditolak; saklar/batas per pengguna dihormati;
   * persetujuan staf → `apply_mapping` (method `usulan_ai` / `usulan_pasti`).

Jalankan:  cd backend && python -m pytest tests/unit/test_refund_pilih_pesanan.py -n 0 -q
"""
import asyncio
import json
import os
import sys

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
from core import returns_bridge as rb  # noqa: E402
from core import sku_bridge as sb  # noqa: E402
from core import sku_kunci as skk  # noqa: E402
from core import sku_usulan as su  # noqa: E402

SA = {"id": "u-sa", "name": "Super", "email": "sa@x", "role": "superadmin"}
PIC_B = {"id": "u-pic-b", "name": "PIC B", "email": "b@x", "role": "pic_toko"}


def run(coro):
    return asyncio.run(coro)


def _db():
    db = fm.FakeDB()
    db.marketing_platform_accounts.docs += [
        {"id": "A1", "account_name": "Toko Shopee Uji", "platform": "shopee", "status": "active"},
        {"id": "A2", "account_name": "Toko TikTok Uji", "platform": "tiktok", "status": "active",
         "pic_user_id": "u-pic-b"}]
    db.rahaza_models.docs += [
        {"id": "MD-3503", "code": "DA-3503", "name": "Gamis Polka", "active": True},
        {"id": "MD-1510", "code": "DA-1510", "name": "Tunik Bunga", "active": True},
        {"id": "MD-1208", "code": "DA-1208", "name": "Lunara", "active": True},
        {"id": "MD-1512", "code": "DA-1512", "name": "Kaftan", "active": True}]
    db.rahaza_model_variants.docs += [
        {"id": "V-PH-XL", "sku": "DA-3503-PHT-XL", "model_id": "MD-3503", "model_code": "DA-3503",
         "model_name": "Gamis Polka", "color_name": "Polkadot Hitam", "color_code": "PHT", "size_code": "XL"},
        {"id": "V-PH-XXL", "sku": "DA-3503-PHT-XXL", "model_id": "MD-3503", "model_code": "DA-3503",
         "model_name": "Gamis Polka", "color_name": "Polkadot Hitam", "color_code": "PHT", "size_code": "XXL"},
        {"id": "V-PP-XL", "sku": "DA-3503-PPT-XL", "model_id": "MD-3503", "model_code": "DA-3503",
         "model_name": "Gamis Polka", "color_name": "Polkadot Putih", "color_code": "PPT", "size_code": "XL"},
        {"id": "V-PP-XXL", "sku": "DA-3503-PPT-XXL", "model_id": "MD-3503", "model_code": "DA-3503",
         "model_name": "Gamis Polka", "color_name": "Polkadot Putih", "color_code": "PPT", "size_code": "XXL"},
        {"id": "V-BE", "sku": "DA-1510-DBE-ALLSIZE", "model_id": "MD-1510", "model_code": "DA-1510",
         "model_name": "Tunik Bunga", "color_name": "Digital Bunga Emas", "color_code": "DBE", "size_code": "ALLSIZE"},
        {"id": "V-BM", "sku": "DA-1510-DBM-ALLSIZE", "model_id": "MD-1510", "model_code": "DA-1510",
         "model_name": "Tunik Bunga", "color_name": "Digital Bunga Merah", "color_code": "DBM", "size_code": "ALLSIZE"},
        {"id": "V-MOCA", "sku": "DA-1208-MCA-ALLSIZE", "model_id": "MD-1208", "model_code": "DA-1208",
         "model_name": "Lunara", "color_name": "Moca", "color_code": "MCA", "size_code": "ALLSIZE"},
        {"id": "V-HITAM", "sku": "DA-1208-HTM-ALLSIZE", "model_id": "MD-1208", "model_code": "DA-1208",
         "model_name": "Lunara", "color_name": "Hitam", "color_code": "HTM", "size_code": "ALLSIZE"},
        {"id": "V-K-MRH", "sku": "DA-1512-MRH-M", "model_id": "MD-1512", "model_code": "DA-1512",
         "model_name": "Kaftan", "color_name": "Merah", "color_code": "MRH", "size_code": "M"},
        {"id": "V-K-NVY", "sku": "DA-1512-NVY-M", "model_id": "MD-1512", "model_code": "DA-1512",
         "model_name": "Kaftan", "color_name": "Navy", "color_code": "NVY", "size_code": "M"}]
    db.rahaza_materials.docs += [
        {"id": "FG-PH-XL", "code": "DA-3503-PHT-XL", "name": "Gamis Polka Polkadot Hitam XL", "type": "fg",
         "variant_id": "V-PH-XL", "model_id": "MD-3503", "unit": "pcs"},
        {"id": "FG-MOCA", "code": "DA-1208-MCA-ALLSIZE", "name": "Lunara Moca", "type": "fg",
         "variant_id": "V-MOCA", "model_id": "MD-1208", "unit": "pcs"},
        # barang jadi TINGKAT MODEL (tanpa varian) — baris yang menunjuknya "baru tertaut model"
        {"id": "FG-KAFTAN", "code": "DA-1512", "name": "Kaftan (model)", "type": "fg", "model_id": "MD-1512",
         "unit": "pcs"}]
    db.marketing_catalog_items.docs += [
        {"id": "CI-PH-XL", "name": "Gamis Polka Hitam XL", "sku": "DA-3503-PHT-XL", "fg_material_id": "FG-PH-XL",
         "variant_id": "V-PH-XL", "model_id": "MD-3503", "account_id": "A1"},
        {"id": "CI-KAFTAN", "name": "Kaftan", "sku": "1512", "fg_material_id": "FG-KAFTAN", "model_id": "MD-1512",
         "account_id": "A1"}]
    db.marketing_orders.docs += [
        # 1 baris tertaut varian
        {"id": "O1", "order_id": "2611140001", "tracking_number": "SPXID001", "platform": "shopee",
         "account_id": "A1", "account_name": "Toko Shopee Uji", "customer_name": "Budi", "status": "completed",
         "order_date": "2026-11-10",
         "items": [{"fg_material_id": "FG-PH-XL", "catalog_item_id": "CI-PH-XL", "variant_id": "V-PH-XL",
                    "model_id": "MD-3503", "quantity": 2, "product_name_raw": "Gamis Polka Premium",
                    "variation_raw": "POLKA BLACK, XL (LD 120 CM)", "seller_sku": "3503",
                    "sku_subtotal_after_discount": 250000}]},
        # 2 baris: baris 1 baru tertaut MODEL (item katalog tingkat model), baris 2 belum tertaut
        {"id": "O2", "order_id": "2611140002", "tracking_number": "SPXID002", "platform": "shopee",
         "account_id": "A1", "account_name": "Toko Shopee Uji", "customer_name": "Sari", "status": "completed",
         "order_date": "2026-11-11",
         "items": [{"fg_material_id": "FG-KAFTAN", "catalog_item_id": "CI-KAFTAN", "model_id": "MD-1512",
                    "quantity": 1, "product_name_raw": "Kaftan Rayon", "variation_raw": "Navy, M",
                    "seller_sku": "1512", "sku_subtotal_after_discount": 99000},
                   {"quantity": 3, "product_name_raw": "Lunara Set", "variation_raw": "Mocca, ALLSIZE",
                    "seller_sku": "1208", "sku_unit_original_price": 120000}]},
        # toko lain (A2) — staf A1 tidak boleh melihatnya
        {"id": "O3", "order_id": "2611140003", "tracking_number": "JX0003", "platform": "tiktok",
         "account_id": "A2", "account_name": "Toko TikTok Uji", "status": "delivered",
         "items": [{"platform_sku_id": "1729000000000000001", "quantity": 1, "product_name_raw": "Gamis Polka",
                    "variation_raw": "POLKA WHITE, XXL", "seller_sku": "3503"}]}]
    return db


def _fake_apply(db, calls):
    """Pengganti `sku_bridge.apply_mapping` (FakeDB tidak punya array_filters): catat panggilan + tautkan baris."""
    async def apply(_db, key, *, variant_id=None, account_id=None, user=None, method="manual", confidence=None,
                    product_name="", variation="", **kw):
        calls.append({"key": key, "variant_id": variant_id, "account_id": account_id, "method": method,
                      "confidence": confidence})
        v = next(x for x in db.rahaza_model_variants.docs if x["id"] == variant_id)
        fg = next((m for m in db.rahaza_materials.docs if m.get("variant_id") == variant_id), None)
        if not fg:
            fg = {"id": f"FG-{variant_id}", "code": v["sku"], "name": f"{v['model_name']} {v['color_name']}",
                  "type": "fg", "variant_id": variant_id, "model_id": v["model_id"], "unit": "pcs"}
            db.rahaza_materials.docs.append(fg)
        n = 0
        for o in db.marketing_orders.docs:
            for ln in o.get("items") or []:
                if skk.kunci_baris(ln, o.get("account_id")) == key:
                    ln.update({"fg_material_id": fg["id"], "variant_id": variant_id, "model_id": v["model_id"],
                               "catalog_item_id": f"CI-{variant_id}", "master_link_source": "sku_bridge"})
                    n += 1
        return {"ok": True, "orders_updated": n, "bridge": {"platform_sku_id": key},
                "target": {"name": fg["name"], "id": f"CI-{variant_id}"},
                "message": f"SKU {key} ditautkan — {n} pesanan ikut diperbarui."}
    return apply


@pytest.fixture
def env(monkeypatch):
    from routes import marketing_returns_routes as mr
    db = _db()
    calls = []
    who = {"user": SA}
    n = {"i": 0}

    async def auth(_r):
        return who["user"]

    async def kode_rb(_db):
        n["i"] += 1
        return f"WH-RET-{n['i']:03d}"

    async def no_notif(*a, **k):
        return None
    monkeypatch.setattr(mr, "require_auth", auth)
    monkeypatch.setattr(mr, "_get_user", lambda _r: who["user"])
    monkeypatch.setattr(mr, "get_db", lambda: db)
    monkeypatch.setattr(rb, "_next_code", kode_rb)
    monkeypatch.setattr(rb, "notify_pending", no_notif)
    monkeypatch.setattr(sb, "apply_mapping", _fake_apply(db, calls))
    return mr, db, calls, who


def _body(**kw):
    b = {"date": "2026-11-14", "reason": "ukuran_salah", "reason_detail": "Kebesaran", "refund_type": "full_refund"}
    b.update(kw)
    return b


def buat(mr, **kw):
    return run(mr.create_return(mr.ReturnIn(**_body(**kw)), fm.FakeRequest()))


def gagal(mr, **kw):
    with pytest.raises(HTTPException) as e:
        buat(mr, **kw)
    return e.value


# ═══════════════════════════════ A. tingkat tautan ═══════════════════════════════
def test_tingkat_tautan():
    assert skk.tingkat_tautan({"fg_material_id": "F", "variant_id": "V"}) == "varian"
    assert skk.tingkat_tautan({"fg_material_id": "F"}, {"variant_id": "V"}) == "varian"
    assert skk.tingkat_tautan({"fg_material_id": "F"}, {"model_id": "M"}) == "model"      # FG tingkat model
    assert skk.tingkat_tautan({"model_id": "M"}) == "model"
    assert skk.tingkat_tautan({"fg_material_id": "F"}, {}) == "varian"                    # FG berdiri sendiri
    assert skk.tingkat_tautan({}) == "belum"


# ═══════════════════════════════ A. cari pesanan ═══════════════════════════════
def test_cari_pesanan_membawa_tingkat_harga_dan_lingkup_toko(env):
    mr, db, _calls, who = env
    res = run(mr.cari_pesanan_refund(fm.FakeRequest(), q="26111400"))
    assert {o["order_id"] for o in res["data"]} == {"2611140001", "2611140002", "2611140003"}
    o2 = next(o for o in res["data"] if o["id"] == "O2")
    assert o2["account_id"] == "A1" and o2["account_name"] == "Toko Shopee Uji"
    b1, b2 = o2["items"]
    assert b1["link_level"] == "model" and b1["model_code"] == "DA-1512" and b1["unit_price"] == 99000
    assert b2["link_level"] == "belum" and b2["unit_price"] == 120000 and b2["bridge_key"].startswith("nv:A1:")
    # usulan varian pasti sebagai pilihan awal (staf tetap memeriksa)
    assert b1["usulan"]["variant_id"] == "V-K-NVY" and b2["usulan"]["variant_id"] == "V-MOCA"
    assert b2["model_code"] == "DA-1208"                         # model diketahui dari SKU penjual
    o1 = next(o for o in res["data"] if o["id"] == "O1")
    assert o1["items"][0]["link_level"] == "varian" and o1["items"][0]["unit_price"] == 125000
    # staf toko B hanya melihat pesanan tokonya
    who["user"] = PIC_B
    res = run(mr.cari_pesanan_refund(fm.FakeRequest(), q="26111400"))
    assert [o["id"] for o in res["data"]] == ["O3"]
    # pencarian lewat resi
    who["user"] = SA
    assert [o["id"] for o in run(mr.cari_pesanan_refund(fm.FakeRequest(), q="SPXID002"))["data"]] == ["O2"]


# ═══════════════════════════════ A. wajib pesanan ═══════════════════════════════
def test_refund_tanpa_pesanan_ditolak(env):
    mr, db, calls, _who = env
    e = gagal(mr, account_id="A1", order_id="KETIK-BEBAS", product="Gamis", price=10000)
    assert e.status_code == 400 and "Pilih pesanan" in e.detail and "diimpor" in e.detail
    e = gagal(mr, order_doc_id="HILANG")
    assert e.status_code == 404
    e = gagal(mr, order_doc_id="O2")                              # multi-baris tanpa pilih barang
    assert e.status_code == 400 and "berisi 2 barang" in e.detail
    assert not db.marketing_returns.docs and not calls


def test_refund_baris_tertaut_varian_mengisi_dari_pesanan_dan_retur_fisik_tertaut(env):
    mr, db, calls, _who = env
    res = buat(mr, order_doc_id="O1", qty=1, account_id="A2", price=1, product="ketikan diabaikan")
    ret = res["data"]
    assert ret["order_id"] == "2611140001" and ret["order_doc_id"] == "O1" and ret["order_line"] == 1
    assert ret["account_id"] == "A1" and ret["platform"] == "shopee"            # dari pesanan, bukan body
    assert ret["price"] == 125000 and ret["qty"] == 1 and ret["refund_amount"] == 125000
    assert ret["fg_material_id"] == "FG-PH-XL" and ret["variant_id"] == "V-PH-XL"
    assert ret["catalog_item_id"] == "CI-PH-XL" and ret["product"] == "Gamis Polka Hitam XL"
    assert res["sku_bridge"] is None and not calls                              # tidak perlu Jembatan SKU
    wh = db.wh_returns.docs[0]
    assert wh["source_marketing_return_id"] == ret["id"]
    assert wh["source_order_doc_id"] == "O1" and wh["source_order_line"] == 1
    assert wh["order_number"] == "2611140001" and wh["resi_number"] == "SPXID001" and wh["customer_name"] == "Budi"
    assert wh["material_id"] == "FG-PH-XL" and wh["link_status"] == rb.LINK_OK and wh["status"] == "Pending"
    assert res["warehouse"]["wh_return_code"] == wh["return_code"]


def test_refund_baris_model_wajib_varian_lalu_disimpan_ke_jembatan(env):
    mr, db, calls, _who = env
    e = gagal(mr, order_doc_id="O2", order_line=1)
    assert e.status_code == 400 and "baru tertaut model" in e.detail and not calls
    e = gagal(mr, order_doc_id="O2", order_line=1, variant_id="TIDAK-ADA")
    assert e.status_code == 400 and "tidak aktif" in e.detail and not calls
    res = buat(mr, order_doc_id="O2", order_line=1, variant_id="V-K-NVY")
    assert calls == [{"key": skk.kunci_baris(db.marketing_orders.docs[1]["items"][0], "A1"), "variant_id": "V-K-NVY",
                      "account_id": "A1", "method": "retur", "confidence": None}]
    ret = res["data"]
    assert ret["variant_id"] == "V-K-NVY" and ret["fg_material_id"] == "FG-V-K-NVY" and ret["order_line"] == 1
    assert ret["link_source"] == "sku_bridge_retur" and res["sku_bridge"]["orders_updated"] == 1
    wh = db.wh_returns.docs[0]
    assert wh["material_id"] == "FG-V-K-NVY" and wh["source_order_line"] == 1 and wh["link_status"] == rb.LINK_OK


def test_refund_baris_belum_tertaut_dan_baris_tertaut_tidak_boleh_ganti_varian(env):
    mr, db, calls, _who = env
    res = buat(mr, order_doc_id="O2", order_line=2, variant_id="V-MOCA", qty=2)
    assert calls[0]["key"].startswith("nv:A1:lunara set|") and calls[0]["variant_id"] == "V-MOCA"
    assert res["data"]["price"] == 120000 and res["data"]["qty"] == 2 and res["data"]["fg_material_id"] == "FG-MOCA"
    e = gagal(mr, order_doc_id="O1", variant_id="V-PH-XXL")
    assert e.status_code == 400 and "Jembatan SKU" in e.detail


def test_refund_ganda_dan_qty_berlebih_ditolak(env):
    mr, db, calls, _who = env
    e = gagal(mr, order_doc_id="O1", qty=3)
    assert e.status_code == 400 and "melebihi" in e.detail
    buat(mr, order_doc_id="O1", qty=1)
    e = gagal(mr, order_doc_id="O1", qty=1)
    assert e.status_code == 409 and e.detail["code"] == "REFUND_SUDAH_ADA" and e.detail["existing"]
    # baris lain pesanan multi-baris tetap boleh; refund yang DITOLAK tidak menghalangi
    buat(mr, order_doc_id="O2", order_line=2, variant_id="V-MOCA")
    db.marketing_returns.docs[0]["status"] = "rejected"
    buat(mr, order_doc_id="O1", qty=1)
    # pencarian menandai baris yang sudah direfund
    o2 = next(o for o in run(mr.cari_pesanan_refund(fm.FakeRequest(), q="SPXID002"))["data"])
    assert not o2["items"][0]["refund_by"] and o2["items"][1]["refund_by"]


def test_refund_toko_lain_ditolak_sebelum_menulis(env):
    mr, db, calls, who = env
    who["user"] = PIC_B
    e = gagal(mr, order_doc_id="O2", order_line=2, variant_id="V-MOCA")
    assert e.status_code == 403 and not calls and not db.marketing_returns.docs


def test_retur_manual_gudang_lebih_dulu_ditautkan_ke_baris_yang_sama(env):
    mr, db, _calls, _who = env
    db.wh_returns.docs.append({"id": "W-MAN", "return_code": "WH-RET-MAN", "status": "Pending",
                               "order_number": "2611140002", "source_order_line": 2, "timeline": [],
                               "source_marketing_return_id": None, "qty": 1})
    res = buat(mr, order_doc_id="O2", order_line=1, variant_id="V-K-NVY")
    assert res["data"]["wh_return_id"] != "W-MAN"                                # baris 1 ≠ retur manual baris 2
    res2 = buat(mr, order_doc_id="O2", order_line=2, variant_id="V-MOCA")
    assert res2["data"]["wh_return_id"] == "W-MAN"                               # ditautkan, bukan dibuat baru
    assert len(db.wh_returns.docs) == 2


def test_ubah_refund_dari_pesanan_mengunci_pesanan_dan_barang(env):
    mr, db, _calls, _who = env
    rid = buat(mr, order_doc_id="O1", qty=1)["data"]["id"]
    upd = mr.ReturnUpdate(order_id="LAIN", product="Lain", price=1, qty=2, reason_detail="Ukuran beda")
    out = run(mr.update_return(rid, upd, fm.FakeRequest()))["data"]
    assert out["order_id"] == "2611140001" and out["product"] == "Gamis Polka Hitam XL" and out["price"] == 125000
    assert out["qty"] == 2 and out["reason_detail"] == "Ukuran beda" and out["refund_amount"] == 250000
    with pytest.raises(HTTPException) as e:
        run(mr.update_return(rid, mr.ReturnUpdate(qty=5), fm.FakeRequest()))
    assert e.value.status_code == 400 and "melebihi" in e.value.detail


# ═══════════════════════════════ B. sinonim & pencocokan pasti ═══════════════════════════════
def test_kanon_sinonim():
    assert su.kanon("POLKA BLACK") == su.kanon("Polkadot Hitam") == ["polkadot", "hitam"]
    assert su.kanon("Polka Dot White") == su.kanon("Polkadot Putih")
    assert set(su.kanon("Bunga Mas")) <= set(su.kanon("Digital Bunga Emas"))
    assert su.kanon("Mocca") == su.kanon("Moca") == su.kanon("MOCHA")
    assert su.kanon("WHITE") == ["putih"]
    assert su.ld_dari("XL (LD 120 CM)") == 120 and su.ld_dari("LD120cm") == 120 and su.ld_dari("XL") is None


def _vs(db, model_id):
    return [v for v in db.rahaza_model_variants.docs if v["model_id"] == model_id]


def test_cocokkan_pasti_dengan_sinonim_dan_ld():
    db = _db()
    r = su.cocokkan({"variation": "POLKA BLACK, XL (LD 120 CM)", "seller_sku": "3503"}, _vs(db, "MD-3503"),
                    model_code="DA-3503", model_name="Gamis Polka")
    assert r["variant"]["id"] == "V-PH-XL" and r["keyakinan"] >= 0.9
    # ukuran hanya tertulis LD → dipelajari dari pesanan lain model yang sama
    r = su.cocokkan({"variation": "POLKA WHITE, LD 125 CM", "seller_sku": "3503"}, _vs(db, "MD-3503"),
                    ld_peta={"3503": {125: "XXL"}}, model_code="DA-3503")
    assert r["variant"]["id"] == "V-PP-XXL" and any("LD 125" in a for a in r["alasan"])
    r = su.cocokkan({"variation": "POLKA WHITE, LD 125 CM", "seller_sku": "3503"}, _vs(db, "MD-3503"),
                    model_code="DA-3503")
    assert r["variant"] is None and r["gagal"] == "ukuran_tidak_terbaca"
    r = su.cocokkan({"variation": "Bunga Mas"}, _vs(db, "MD-1510"), model_code="DA-1510")
    assert r["variant"]["id"] == "V-BE"
    r = su.cocokkan({"variation": "Mocca, ALLSIZE", "product_name": "LUNARA - MOCCA"}, _vs(db, "MD-1208"),
                    model_code="DA-1208", model_name="Lunara")
    assert r["variant"]["id"] == "V-MOCA"
    r = su.cocokkan({"variation": "Flower Blue"}, _vs(db, "MD-1510"), model_code="DA-1510")
    assert r["variant"] is None


def test_klasifikasi_tidak_bisa_dan_saran():
    db = _db()
    kp = run(sb.kode_pool(db))
    _kp, per_model, info = run(su.muat_master(db))
    k = lambda **row: su.klasifikasi({"kunci": "x", "product_name": "Gamis", "model_id": None, **row},  # noqa: E731
                                     kp, per_model, info, {})
    r = k(seller_sku="", variation="Hitam")
    assert r["jenis"] == "tidak" and r["gagal"] == "sku_kosong" and "Seller Center" in r["saran"]
    r = k(seller_sku="1512", variation="Reject Sale")
    assert r["jenis"] == "tidak" and r["gagal"] == "reject" and "Reject" in r["saran"]
    r = k(seller_sku="1512", variation="Default")
    assert r["jenis"] == "tidak" and r["gagal"] == "default" and "2 varian" in r["saran"]
    r = k(seller_sku="AISAR 10202", variation="Hitam")
    assert r["jenis"] == "tidak" and r["gagal"] == "bukan_kode_model"
    r = k(seller_sku="3503", variation="POLKA BLACK, XXL (LD 130 CM)")
    assert r["jenis"] == "pasti" and r["usulan"]["variant_id"] == "V-PH-XXL" and r["model_code"] == "DA-3503"
    r = k(seller_sku="1510", variation="Flower Blue")
    assert r["jenis"] == "ai" and "Minta usulan AI" in r["saran"]
    # SKU kosong tetapi baris sudah tertaut MODEL → tetap bisa dicocokkan
    r = k(seller_sku="", variation="Navy, M", model_id="MD-1512")
    assert r["jenis"] == "pasti" and r["usulan"]["variant_id"] == "V-K-NVY" and r["sumber_model"] == "tautan_model"


def test_daftar_kombinasi_dan_angka_tingkat():
    db = _db()
    d = run(su.daftar(db))
    assert d["angka"] == {"baris": 4, "varian": 1, "model": 1, "belum": 2}
    kunci = {r["kunci"]: r for r in d["rows"]}
    assert "1729000000000000001" in kunci                                       # SKU platform TikTok
    kaftan = next(r for r in d["rows"] if r["product_name"] == "Kaftan Rayon")
    assert kaftan["baris_model"] == 1 and kaftan["jenis"] == "pasti" and kaftan["usulan"]["variant_id"] == "V-K-NVY"
    lunara = next(r for r in d["rows"] if r["product_name"] == "Lunara Set")
    assert lunara["jenis"] == "pasti" and lunara["usulan"]["variant_id"] == "V-MOCA"
    tiktok = kunci["1729000000000000001"]
    assert tiktok["jenis"] == "pasti" and tiktok["usulan"]["variant_id"] == "V-PP-XXL"
    assert d["ringkas"]["pasti"] == 3
    assert run(su.daftar(db, account_id="A2"))["angka"]["baris"] == 1


# ═══════════════════════════════ B. AI + persetujuan ═══════════════════════════════
@pytest.fixture
def ai_env(monkeypatch):
    db = _db()
    db.marketing_orders.docs.append(
        {"id": "O9", "order_id": "2611140009", "account_id": "A1", "account_name": "Toko Shopee Uji",
         "items": [{"quantity": 4, "product_name_raw": "Tunik Bunga", "variation_raw": "Flower Blue",
                    "seller_sku": "1510"}]})
    calls = []
    monkeypatch.setattr(sb, "apply_mapping", _fake_apply(db, calls))
    state = {"aktif": True, "batas": 0, "jawab": None}

    from core.asisten_ai import akses_pengguna as akses
    from core.asisten_ai import mesin

    async def periksa(_db, _user, **kw):
        if not state["aktif"]:
            return {}, {"kode": akses.KODE_NONAKTIF, "pesan": akses.PESAN_NONAKTIF}
        return {"aktif": True, "batas_pertanyaan": state["batas"]}, None

    async def jumlah(_db, _uid, *a):
        return 0

    class G:
        ok, api_key, code, message = True, "kunci-uji", None, None

    async def gerbang(*a, **k):
        return G()

    async def panggil(_klien, masukan):
        state["masukan"] = masukan
        return json.dumps(state["jawab"]), None

    async def catat(*a, **k):
        return 0.0
    monkeypatch.setattr(akses, "periksa", periksa)
    monkeypatch.setattr(akses, "jumlah_pertanyaan_hari_ini", jumlah)
    monkeypatch.setattr(mesin, "gerbang", gerbang)
    monkeypatch.setattr(mesin, "buat_klien", lambda _k: object())
    monkeypatch.setattr(su, "_panggil", panggil)
    monkeypatch.setattr(su, "_catat", catat)
    monkeypatch.delenv("ASISTEN_AI_FAKE", raising=False)
    return db, calls, state


def test_ai_hanya_mengusulkan_dari_daftar_varian_dan_disetujui_staf(ai_env):
    db, calls, state = ai_env
    d = run(su.daftar(db, jenis="ai"))
    assert [r["product_name"] for r in d["rows"]] == ["Tunik Bunga"] and d["rows"][0]["usulan"] is None
    state["jawab"] = [{"kombinasi": 1, "varian": 2, "keyakinan": 0.62, "alasan": "Biru paling dekat ke motif bunga"}]
    res = run(su.minta_ai(db, SA))
    assert res["diminta"] == 1 and res["diusulkan"] == 1 and not calls                 # AI tidak menautkan
    assert state["masukan"]["kombinasi"][0]["variasi"] == "Flower Blue"
    assert {v["warna"] for v in state["masukan"]["model"][0]["varian"]} == {"Digital Bunga Emas", "Digital Bunga Merah"}
    row = run(su.daftar(db, jenis="ai"))["rows"][0]
    assert row["usulan"]["sumber"] == "ai" and row["usulan"]["keyakinan"] == 0.62
    vid = row["usulan"]["variant_id"]
    # sudah dijawab → permintaan berikutnya tidak bertanya ulang
    assert run(su.minta_ai(db, SA))["diminta"] == 0
    run(su.setujui(db, kunci=row["kunci"], variant_id=vid, user=SA, metode=su.METODE_AI, keyakinan=0.62))
    assert calls[-1]["method"] == "usulan_ai" and calls[-1]["variant_id"] == vid
    doc = db.marketing_sku_usulan.docs[0]
    assert doc["ai_suggestion"]["status"] == "accepted" and doc["ai_suggestion"]["decided_by"] == "Super"
    assert not run(su.daftar(db, jenis="ai"))["rows"]                                   # sudah tertaut varian


def test_ai_nomor_di_luar_daftar_ditolak(ai_env):
    db, calls, state = ai_env
    state["jawab"] = [{"kombinasi": 1, "varian": 99, "keyakinan": 0.9, "alasan": "tebak"}]
    res = run(su.minta_ai(db, SA))
    assert res["diusulkan"] == 0
    u = run(su.daftar(db, jenis="ai"))["rows"][0]["usulan"]
    assert u["kosong"] and u["keyakinan"] == 0 and "di luar daftar" in u["alasan"][0]


def test_ai_menghormati_saklar_dan_batas_pengguna(ai_env):
    db, calls, state = ai_env
    state["aktif"] = False
    with pytest.raises(su.GalatUsulan) as e:
        run(su.minta_ai(db, PIC_B))
    assert e.value.status == 403 and "belum diaktifkan" in e.value.pesan
    assert run(su.status_ai(db, PIC_B))["boleh"] is False
    state.update(aktif=True, batas=1)
    db.rahaza_ai_usage_logs.docs.append({"feature": su.FITUR, "user_id": PIC_B["id"],
                                         "date": __import__("utils.waktu", fromlist=["x"]).today_wib().isoformat()})
    with pytest.raises(su.GalatUsulan) as e:
        run(su.minta_ai(db, PIC_B))
    assert e.value.status == 429


def test_setujui_semua_usulan_pasti(ai_env):
    db, calls, _state = ai_env
    res = run(su.setujui_pasti(db, user=SA))
    assert res["disetujui"] == 3 and not res["gagal"]
    assert {c["method"] for c in calls} == {"usulan_pasti"}
    assert {c["variant_id"] for c in calls} == {"V-K-NVY", "V-MOCA", "V-PP-XXL"}


def test_setujui_varian_tidak_aktif_ditolak(ai_env):
    db, calls, _state = ai_env
    with pytest.raises(su.GalatUsulan) as e:
        run(su.setujui(db, kunci="1729000000000000001", variant_id="HILANG", user=SA))
    assert e.value.status == 404 and not calls
