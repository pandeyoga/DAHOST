"""Uji unit HERMETIK — Retur Fisik tanpa dobel (keputusan owner 10 Nov 2026: "wajib referensi + tautkan").

  * "Catat retur" manual (Tipe 1 ekspedisi / Tipe 2 pembeli) WAJIB memilih pesanan yang ada di
    `marketing_orders` (sumber yang sama dengan jembatan) — tidak ada ⇒ 400 berkalimat staf.
  * Retur gudang AKTIF (bukan Batal) untuk pesanan/barang yang sama ⇒ 409 + nomor retur yang ada.
  * Jembatan Marketing → Gudang MENAUTKAN retur Marketing ke retur manual yang dicatat lebih dulu
    (tetap satu `wh_returns`, stok sekali); pesanan multi-baris hanya bila barangnya sama.
  * RTS (batal setelah kirim) tidak membuat pengajuan kedua untuk baris yang sudah dicatat manual.

Jalankan:  cd backend && python -m pytest tests/unit/test_retur_fisik_tanpa_dobel.py -n 0 -q
"""
import asyncio
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from core import marketing_returns as mret  # noqa: E402
from core import returns_bridge as rb  # noqa: E402
from core import stock_service as ss  # noqa: E402

WH = {"id": "u-gd", "name": "Gudang Uji", "email": "gd@x", "role": "admin_gudang"}


def run(coro):
    return asyncio.run(coro)


def _db():
    db = fm.FakeDB()
    db.rahaza_locations.docs += [
        {"id": "L-FG", "code": "GD-FG", "name": "Rak barang jadi", "storage_role": "fg", "active": True},
        {"id": "L-Q", "code": "GD-QC", "name": "Karantina", "storage_role": "karantina", "active": True}]
    db.rahaza_materials.docs += [
        {"id": "M1", "code": "DA-1-A", "name": "Kaos A", "type": "fg", "unit": "pcs", "active": True},
        {"id": "M2", "code": "DA-1-B", "name": "Kaos B", "type": "fg", "unit": "pcs", "active": True}]
    db.marketing_catalog_items.docs += [{"id": "CI1", "fg_material_id": "M1"}, {"id": "CI2", "fg_material_id": "M2"}]
    db.marketing_orders.docs += [
        {"id": "O1", "order_id": "5800001", "tracking_number": "SPX111", "platform": "shopee", "account_id": "A1",
         "account_name": "Toko DA", "customer_name": "Budi", "status": "completed",
         "items": [{"fg_material_id": "M1", "catalog_item_id": "CI1", "quantity": 2, "product_name_raw": "Kaos A",
                    "sku_subtotal_after_discount": 150000}]},
        {"id": "O2", "order_id": "5800002", "tracking_number": "SPX222", "platform": "tiktok", "account_id": "A1",
         "status": "delivered",
         "items": [{"fg_material_id": "M1", "catalog_item_id": "CI1", "quantity": 1, "product_name_raw": "Kaos A"},
                   {"fg_material_id": "M2", "catalog_item_id": "CI2", "quantity": 1, "product_name_raw": "Kaos B",
                    "seller_sku": "DA-1-B"}]},
        {"id": "O3", "order_id": "5800003", "tracking_number": "JNT333", "platform": "shopee", "status": "completed",
         "items": [{"quantity": 1, "product_name_raw": "Kulot", "seller_sku": "SKU-ASING"}]}]
    return db


@pytest.fixture
def env(monkeypatch):
    from routes import dewi_wh_returns as wr
    db = _db()
    n = {"i": 0}

    async def auth(_r):
        return WH

    async def kode_route(_db, requested=""):
        n["i"] += 1
        return f"WH-RET-{n['i']:03d}"

    async def kode_rb(_db):
        n["i"] += 1
        return f"WH-RET-{n['i']:03d}"

    async def no_notif(*a, **k):
        return None
    monkeypatch.setattr(wr, "require_auth", auth)
    monkeypatch.setattr(wr, "get_db", lambda: db)
    monkeypatch.setattr(wr, "_next_code", kode_route)
    monkeypatch.setattr(rb, "_next_code", kode_rb)
    monkeypatch.setattr(rb, "notify_pending", no_notif)
    return wr, db


def catat(wr, body):
    resp = run(wr.create_return(fm.FakeRequest(body)))
    assert resp.status_code == 201
    return json.loads(resp.body)


def tolak(wr, body):
    with pytest.raises(HTTPException) as e:
        run(wr.create_return(fm.FakeRequest(body)))
    return e.value


def _mret_ret(rid, order_id, **kw):
    return {"id": rid, "order_id": order_id, "status": "pending", "account_id": "A1", "date": "2026-11-10",
            "platform": "shopee", "qty": 1, **kw}


# ═════════════════════════════ 1. wajib pesanan yang ada → 400 ═════════════════════════════
def test_catat_tanpa_pesanan_sah_ditolak_400(env):
    wr, db = env
    cases = [
        ({"return_type": "expedition_return"}, "Pilih pesanan"),
        ({"order_number": "SPX-00001", "material_id": "M1"}, "tidak ada di data pesanan Marketing"),
        ({"resi_number": "JNE-123456"}, "minta tim Marketing mengimpor"),
        ({"order_doc_id": "HILANG"}, "cari ulang"),
        ({"order_doc_id": "O2"}, "berisi 2 barang"),                          # multi-baris tanpa pilih barang
        ({"order_doc_id": "O2", "order_line": 3}, "tidak ada di pesanan ini"),
        ({"order_doc_id": "O1", "qty": 3}, "melebihi qty barang ini di pesanan (2 pcs)"),
        ({"order_doc_id": "O1", "qty": 0}, "minimal 1"),
        ({"order_doc_id": "O1", "return_type": "lain"}, "Tipe retur"),
    ]
    for body, why in cases:
        err = tolak(wr, body)
        assert err.status_code == 400 and why in err.detail, (body, err.detail)
    assert db.wh_returns.docs == []


def test_catat_dari_pesanan_mengisi_info_dan_barang_dari_baris(env):
    wr, db = env
    doc = catat(wr, {"return_type": "expedition_return", "order_number": "5800001", "qty": 1,
                     "order_value": 999, "initial_reason": "Gagal kirim"})
    assert (doc["order_number"], doc["resi_number"], doc["channel"], doc["customer_name"]) == \
        ("5800001", "SPX111", "shopee", "Budi")
    assert (doc["material_id"], doc["sku_code"], doc["link_status"], doc["link_source"]) == \
        ("M1", "DA-1-A", rb.LINK_OK, "order_item")
    assert (doc["source_order_doc_id"], doc["source_order_line"], doc["qty"], doc["order_value"]) == \
        ("O1", 1, 1, 150000.0)                                               # nilai dari baris, bukan ketikan
    assert doc["source"] == "manual" and not doc.get("source_marketing_return_id")
    assert "otomatis tertaut" in doc["timeline"][0]["note"]
    # cari lewat RESI juga sah; baris tak tertaut master → barang dari master FG (W4)
    d3 = catat(wr, {"resi_number": "JNT333", "material_id": "M2"})
    assert (d3["order_number"], d3["material_id"], d3["link_source"]) == ("5800003", "M2", "manual_master_pick")
    assert d3["order_line_label"] == "Kulot"


def test_baris_tak_tertaut_tanpa_pilihan_master_tetap_tercatat_tanpa_tautan(env):
    wr, db = env
    d = catat(wr, {"order_doc_id": "O3"})
    assert d["material_id"] is None and d["link_status"] == rb.LINK_NONE and "Pilih barang" in d["link_reason"]
    assert d["sku_code"] == "SKU-ASING" and d["product_name"] == "Kulot"


# ═════════════════════════════ 2. retur ganda → 409 ═════════════════════════════
def test_catat_ganda_ditolak_409_dengan_nomor_retur(env):
    wr, db = env
    first = catat(wr, {"order_doc_id": "O1"})
    for body in ({"order_doc_id": "O1"}, {"order_number": "5800001"}, {"resi_number": "SPX111"}):
        err = tolak(wr, body)
        assert err.status_code == 409, body
        assert err.detail["code"] == "RETUR_SUDAH_ADA" and first["return_code"] in err.detail["message"]
        assert [x["return_code"] for x in err.detail["existing"]] == [first["return_code"]]
        assert err.detail["existing"][0]["id"] == first["id"]
    assert len(db.wh_returns.docs) == 1
    # retur yang DIBATALKAN tidak menghalangi
    db.wh_returns.docs[0]["status"] = "Cancelled"
    again = catat(wr, {"order_doc_id": "O1"})
    assert again["id"] != first["id"] and len(db.wh_returns.docs) == 2


def test_multi_baris_hanya_barang_yang_sama_yang_ditolak(env):
    wr, db = env
    a = catat(wr, {"order_doc_id": "O2", "order_line": 1})
    b = catat(wr, {"order_doc_id": "O2", "order_line": 2})                # barang lain di pesanan sama: boleh
    assert (a["material_id"], b["material_id"]) == ("M1", "M2")
    err = tolak(wr, {"order_doc_id": "O2", "order_line": 2})
    assert err.status_code == 409 and b["return_code"] in err.detail["message"]


def test_retur_marketing_yang_sudah_ada_juga_menghalangi_catat_manual(env):
    wr, db = env
    ret = _mret_ret("R1", "5800001", catalog_item_id="CI1")
    db.marketing_returns.docs.append(dict(ret))
    out = run(rb.ensure_wh_return(db, ret, actor=WH))
    assert out["created"] is True
    err = tolak(wr, {"order_doc_id": "O1"})
    assert err.status_code == 409 and out["wh_return"]["return_code"] in err.detail["message"]


# ═════════════════════════════ 3. manual dulu → retur Marketing masuk → DITAUTKAN ═════════════════════════════
def test_manual_dulu_lalu_retur_marketing_ditautkan_satu_pekerjaan(env):
    wr, db = env
    manual = catat(wr, {"order_doc_id": "O1", "qty": 2})
    ret = _mret_ret("R1", "5800001", catalog_item_id="CI1", qty=2, reason_label="Ukuran tidak sesuai")
    db.marketing_returns.docs.append(dict(ret))
    out = run(rb.ensure_wh_return(db, ret, actor=WH))
    assert out["created"] is False and out["linked"] is True and "tidak dibuat pekerjaan kedua" in out["message"]
    assert len(db.wh_returns.docs) == 1
    w = db.wh_returns.docs[0]
    assert w["id"] == manual["id"] and w["source_marketing_return_id"] == "R1"
    assert w["source"] == "manual" and w["marketing_linked_by"] == "Gudang Uji"
    assert w["initial_reason"] == "Ukuran tidak sesuai" and "Ditautkan ke retur Marketing" in w["timeline"][-1]["note"]
    m = db.marketing_returns.docs[0]
    assert (m["wh_return_id"], m["wh_return_code"], m["wh_return_status"]) == (manual["id"], manual["return_code"],
                                                                              "Pending")
    # idempoten: jembatan, sinkron, dan impor ulang tidak membuat pekerjaan kedua
    again = run(rb.ensure_wh_return(db, dict(m), actor=WH))
    assert again["created"] is False and not again.get("linked")
    s = run(rb.sync_all(db, actor=WH))
    assert (s["created"], s["linked"], s["already"]) == (0, 0, 1) and len(db.wh_returns.docs) == 1


def test_retur_marketing_mengisi_barang_retur_manual_yang_belum_tertaut(env):
    wr, db = env
    manual = catat(wr, {"order_doc_id": "O3"})                          # baris tanpa master
    db.marketing_catalog_items.docs.append({"id": "CI9", "fg_material_id": "M2"})
    ret = _mret_ret("R3", "5800003", catalog_item_id="CI9")
    out = run(rb.ensure_wh_return(db, ret, actor=WH))
    assert out["linked"] and len(db.wh_returns.docs) == 1
    w = db.wh_returns.docs[0]
    assert w["id"] == manual["id"] and (w["material_id"], w["link_status"]) == ("M2", rb.LINK_OK)


def test_multi_baris_hanya_ditautkan_bila_barangnya_sama(env):
    wr, db = env
    manual_b = catat(wr, {"order_doc_id": "O2", "order_line": 2})         # paket berisi Kaos B
    r_a = _mret_ret("RA", "5800002", catalog_item_id="CI1")               # retur Marketing Kaos A
    out_a = run(rb.ensure_wh_return(db, r_a, actor=WH))
    assert out_a["created"] is True and not out_a.get("linked")
    assert out_a["wh_return"]["id"] != manual_b["id"] and len(db.wh_returns.docs) == 2
    r_b = _mret_ret("RB", "5800002", sku="DA-1-B")                        # retur Marketing Kaos B (lewat SKU)
    out_b = run(rb.ensure_wh_return(db, r_b, actor=WH))
    assert out_b["linked"] and out_b["wh_return"]["id"] == manual_b["id"] and len(db.wh_returns.docs) == 2
    # retur Marketing tanpa penunjuk barang di pesanan multi-baris: TIDAK menebak
    db.wh_returns.docs = [d for d in db.wh_returns.docs if d["id"] == manual_b["id"]]
    db.wh_returns.docs[0]["source_marketing_return_id"] = None
    r_x = _mret_ret("RX", "5800002", product="Tidak jelas")
    out_x = run(rb.ensure_wh_return(db, r_x, actor=WH))
    assert out_x["created"] is True and not out_x.get("linked")


def test_retur_dibatalkan_tidak_ditautkan(env):
    wr, db = env
    catat(wr, {"order_doc_id": "O1"})
    db.wh_returns.docs[0]["status"] = "Cancelled"
    out = run(rb.ensure_wh_return(db, _mret_ret("R1", "5800001", catalog_item_id="CI1"), actor=WH))
    assert out["created"] is True and len(db.wh_returns.docs) == 2
    assert not db.wh_returns.docs[0].get("source_marketing_return_id")


# ═════════════════════════════ 4. stok hanya sekali ═════════════════════════════
def test_stok_hanya_sekali_walau_retur_marketing_masuk_berulang(env, monkeypatch):
    wr, db = env
    added = []

    async def add(mid, loc, qty, *, meta=None, ref=None, actor=None, db=None, input_uom=None):
        added.append((mid, loc, qty))
        return {"qty": qty}

    async def no_value(*a, **k):
        return {}

    async def no_cache(*a, **k):
        return 0
    monkeypatch.setattr(ss, "add", add)
    monkeypatch.setattr(rb, "_value_restock", no_value)
    monkeypatch.setattr(rb, "refresh_catalog_cache", no_cache)
    manual = catat(wr, {"order_doc_id": "O1", "qty": 2})
    ret = _mret_ret("R1", "5800001", catalog_item_id="CI1", qty=2)
    db.marketing_returns.docs.append(dict(ret))
    run(rb.ensure_wh_return(db, ret, actor=WH))
    res = run(rb.auto_process(db, manual["id"], condition="Baik", qty=2, actor=WH))   # "Terima & putuskan"
    assert res["restocked"] and added == [("M1", "L-FG", 2)]
    # retur Marketing yang sama masuk lagi (approve / impor ulang / tarik) + klik ganda keputusan
    run(rb.ensure_wh_return(db, dict(db.marketing_returns.docs[0]), actor=WH))
    run(rb.sync_all(db, actor=WH))
    again = run(rb.restock(db, db.wh_returns.docs[0], condition="Baik", qty=2, actor=WH))
    assert again["already"] is True
    assert added == [("M1", "L-FG", 2)] and len(db.wh_returns.docs) == 1
    m = db.marketing_returns.docs[0]
    assert m["wh_return_status"] == "Resolved" and m["wh_restocked"] is True


def test_manual_sudah_diputuskan_lalu_retur_marketing_masuk_rekap_dihitung_ulang(env, monkeypatch):
    wr, db = env
    called = []

    async def rekap(_db, ids, actor="system"):
        called.append(list(ids))
        return {"pairs": 1}
    monkeypatch.setattr(mret, "refresh_rekap_for_return_ids", rekap)
    manual = catat(wr, {"order_doc_id": "O1"})
    db.wh_returns.docs[0].update(status="Resolved", restocked=True, restock_qty=1,
                                 action_taken=rb.ACTION_RESTOCK, resolved_at="2026-11-10T03:00:00+00:00")
    ret = _mret_ret("R1", "5800001", catalog_item_id="CI1")
    db.marketing_returns.docs.append(dict(ret))
    out = run(rb.ensure_wh_return(db, ret, actor=WH))
    assert out["linked"] and out["wh_return"]["id"] == manual["id"] and len(db.wh_returns.docs) == 1
    assert called == [["R1"]]                                           # K36: keputusan sudah ada ⇒ rekap ulang
    m = db.marketing_returns.docs[0]
    assert (m["wh_return_status"], m["wh_action_taken"], m["wh_restocked"]) == ("Resolved", rb.ACTION_RESTOCK, True)
    assert m["wh_decided_at"] == "2026-11-10T03:00:00+00:00"


# ═════════════════════════════ 5. sinkron, RTS, pemilih pesanan ═════════════════════════════
def test_sync_all_dry_run_melaporkan_tautan_tanpa_menulis(env):
    wr, db = env
    manual = catat(wr, {"order_doc_id": "O1"})
    db.marketing_returns.docs.append(_mret_ret("R1", "5800001", catalog_item_id="CI1"))
    dry = run(rb.sync_all(db, dry_run=True))
    assert (dry["linked"], dry["created"]) == (1, 0)
    assert dry["details"][0]["would_link_to"] == manual["return_code"]
    assert not db.wh_returns.docs[0].get("source_marketing_return_id")
    real = run(rb.sync_all(db, actor=WH))
    assert (real["linked"], real["created"]) == (1, 0) and len(db.wh_returns.docs) == 1


def test_rts_tidak_membuat_pengajuan_kedua_untuk_baris_yang_sudah_dicatat(env):
    wr, db = env
    manual = catat(wr, {"order_doc_id": "O2", "order_line": 1})
    order = next(o for o in db.marketing_orders.docs if o["id"] == "O2")
    res = run(rb.ensure_rts_returns(db, order, reason="Gagal kirim"))
    assert res["existing"] == [manual["return_code"]] and len(res["created"]) == 1
    assert [d["source_order_line"] for d in db.wh_returns.docs] == [1, 2]
    # retur manual yang DIBATALKAN tidak menghalangi RTS
    db.wh_returns.docs = [d for d in db.wh_returns.docs if d["id"] == manual["id"]]
    db.wh_returns.docs[0]["status"] = "Cancelled"
    res2 = run(rb.ensure_rts_returns(db, order))
    assert len(res2["created"]) == 2


def test_pemilih_pesanan_mencari_no_pesanan_atau_resi_dan_menandai_retur_yang_ada(env):
    wr, db = env
    assert run(rb.order_lookup(db, "58")) == []                         # < 3 huruf
    by_no = run(rb.order_lookup(db, "5800002"))
    by_resi = run(rb.order_lookup(db, "spx222"))
    assert [o["id"] for o in by_no] == [o["id"] for o in by_resi] == ["O2"]
    it = by_no[0]["items"]
    assert [(i["line"], i["material_code"], i["quantity"]) for i in it] == [(1, "DA-1-A", 1), (2, "DA-1-B", 1)]
    assert all(i["blocked_by"] == [] for i in it) and by_no[0]["active_returns"] == []
    a = catat(wr, {"order_doc_id": "O2", "order_line": 1})
    o2 = run(rb.order_lookup(db, "SPX222"))[0]
    assert [x["return_code"] for x in o2["items"][0]["blocked_by"]] == [a["return_code"]]
    assert o2["items"][1]["blocked_by"] == [] and o2["active_returns"][0]["status_label"] == "menunggu paket"
    assert {o["id"] for o in run(rb.order_lookup(db, "58000"))} == {"O1", "O2", "O3"}


# ═════════════════════════════ 6. sumber layar & rute ═════════════════════════════
def test_sumber_layar_memakai_pemilih_pesanan_bukan_ketikan():
    p = os.path.join(REPO, "frontend", "src", "components", "erp", "WHReturnsModule.jsx")
    if not os.path.exists(p):
        pytest.skip("frontend tidak ada di lingkungan ini")
    s = open(p, encoding="utf-8").read()
    form = s[s.index("function CreateModal"):s.index("// ─── DETAIL (popup)")]
    assert "/api/wh/returns/order-lookup" in form and "order_doc_id: pesanan.id" in form
    assert "order_line: baris.line" in form
    assert 'data-testid="ret-order-pick"' in form and "<SmartNativeSelect" in form
    for lama in ('data-testid="ret-order-number"', 'data-testid="ret-resi-number"', "order_number:", "resi_number:",
                 'data-testid="ret-customer-name"', 'data-testid="ret-channel"'):
        assert lama not in form, lama
    # retur yang sudah ada: ditampilkan & ditawarkan dibuka (409 dan penanda dari pencarian)
    assert "e.status === 409" in form and "onOpenExisting(b.id)" in form and "blocked_by" in form
    assert "bisaSimpan={!penghalang.length}" in form
    assert "otomatis tertaut saat retur Marketing-nya masuk" in form
    assert "Retur pembeli dari Marketing masuk ke sini otomatis" in form
    assert "onOpenExisting={openExisting}" in s
    assert not re.search(r"<(select|button|table)\b", s)


def test_rute_cari_pesanan_sebelum_rute_id_dan_create_tanpa_teks_bebas():
    src = open(os.path.join(BACKEND, "routes", "dewi_wh_returns.py"), encoding="utf-8").read()
    assert src.index('"/returns/order-lookup"') < src.index('"/returns/{return_id}"')
    body = src[src.index("async def create_return"):src.index("async def get_return")]
    assert "prepare_manual_return" in body and "HTTPException(409" in body
    assert "order_number atau resi_number wajib diisi" not in body
    assert 'body.get("order_number", "")' not in body and 'body.get("channel", "")' not in body
