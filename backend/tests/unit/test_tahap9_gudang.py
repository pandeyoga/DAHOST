"""Tahap 9C (7 Nov 2026) — gudang: barang jadi klien maklon = STOK TITIPAN KLIEN (hermetik, FakeDB).

Keputusan owner: CV Dewi Aditya memiliki semua bahan & stok, CV Sukma (maklon) tidak punya stok, barang jadi maklon
milik klien (di luar neraca DA). Yang dikunci di sini:
  1. Terima & QC barang PO maklon → stok titipan klien (identitas artikel Katalog Buyer), TIDAK membuat barang di
     master produk DA, tidak menyentuh stok/karantina DA walau SKU klien sama dengan SKU DA.
  2. Kirim hasil ke klien → stok titipan berkurang; stok kurang = ditolak; hapus surat jalan = kembali.
  3. Stok titipan tanpa nilai & tanpa jurnal.
  4. Saringan Kepemilikan (dua pilihan + sub-saringan klien) termasuk kasus "stok 0".
  5. Migrasi 2026_11_07_titipan_klien: pencocokan tanpa menebak, pratinjau baca-saja, tulis idempoten.
"""
import asyncio
import importlib.util
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
import routes.dewi_cmt_packing as dcp  # noqa: E402
import routes.buyer_shipment as bsh  # noqa: E402
import routes.shared as shared  # noqa: E402
import routes.production_maklon_bridge as bridge  # noqa: E402
import routes.unified_inventory as ui  # noqa: E402
from core import client_goods as cg  # noqa: E402
from core import production_qty_ledger as qled  # noqa: E402
from core import short_shipment as shortmod  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]
FE = BACKEND.parent / "frontend" / "src"
USER = {"id": "u1", "name": "Admin Uji", "role": "admin"}
CL_A, CL_B = "kl-uji-a", "kl-uji-b"


def run(c):
    return asyncio.run(c)


async def _user(*_a, **_k):
    return dict(USER)


def _catalog(cid="cat-1", client=CL_A, code="ART-UJI-1", variants=None, status="active"):
    return {"id": cid, "client_id": client, "client_name": "Klien Uji A" if client == CL_A else "Klien Uji B",
            "artikel_code": code, "product_name": "Kemeja Uji", "category": "Kemeja", "status": status,
            "variants": variants if variants is not None else [
                {"id": f"{cid}-v1", "sku": f"{code}-HTM-M", "color": "Hitam", "size": "M", "active": True},
                {"id": f"{cid}-v2", "sku": f"{code}-HTM-L", "color": "Hitam", "size": "L", "active": True}]}


def _base_db():
    db = FakeDB()
    db.dewi_maklon_clients.docs = [{"id": CL_A, "name": "Klien Uji A", "code": "KUA", "active": True},
                                   {"id": CL_B, "name": "Klien Uji B", "code": "KUB", "active": True}]
    db.dewi_maklon_buyer_catalog.docs = [_catalog()]
    db.production_pos.docs = [{"id": "po-m", "po_number": "PO-MKL-UJI", "business_type": "maklon",
                               "buyer_id": CL_A, "customer_name": "Klien Uji A", "status": "In Production"}]
    db.po_items.docs = [{"id": "pi-1", "po_id": "po-m", "sku": "ART-UJI-1-HTM-M", "color": "Hitam", "size": "M",
                         "catalog_item_id": "cat-1", "maklon_variant_id": "cat-1-v1", "qty": 50}]
    # barang DA dengan SKU SAMA (risiko salah tempel lama)
    db.rahaza_materials.docs = [{"id": "fg-da", "type": "fg", "code": "ART-UJI-1-HTM-M", "name": "Barang DA",
                                 "active": True}]
    db.rahaza_material_stock.docs = [{"id": "st-da", "material_id": "fg-da", "location_id": "loc-fg", "qty": 7,
                                      "quantity": 7, "ownership": "cv_da", "inventory_category": "fg_internal"}]
    return db


def _receipt(db, *, qty=45, reject=0, po_item_id="pi-1", sku="ART-UJI-1-HTM-M"):
    db.cmt_receipts.docs = [{"id": "r1", "receipt_code": "RCV-UJI-1", "status": "on_qc", "po_id": "po-m",
                             "po_number": "PO-MKL-UJI", "cmt_name": "CMT Uji", "cmt_vendor_id": "v1"}]
    db.cmt_receipt_lines.docs = [{"id": "l1", "receipt_id": "r1", "sku_code": sku, "qty_actual": qty,
                                  "reject_qty": reject, "qty_shipped_by_cmt": qty + reject,
                                  "po_item_id": po_item_id, "color": "Hitam", "size": "M"}]


def _patch_finish(monkeypatch, db):
    seen = {"ledger_lines": None}

    async def loc(_db):
        return "loc-fg"

    async def no_da_stock(*_a, **_k):
        raise AssertionError("barang klien tidak boleh masuk stok/master DA")

    async def ledger(_db, _rc, lines, **_k):
        seen["ledger_lines"] = [dict(x) for x in lines]
        return {"applied": True}

    async def ap(*_a, **_k):
        return {"ok": True}

    monkeypatch.setattr(shared, "require_perm", _user)
    monkeypatch.setattr(dcp, "get_db", lambda: db)
    monkeypatch.setattr(qled, "resolve_fg_location_id", loc)
    monkeypatch.setattr(qled, "post_fg_accepted", no_da_stock)
    monkeypatch.setattr(dcp, "_ensure_fg_for_cmt_line", no_da_stock)
    monkeypatch.setattr(qled, "apply_receipt_result", ledger)
    monkeypatch.setattr(bridge, "mature_ap_from_cmt_receipt", ap)
    return seen


def _client_moves(db):
    return [m for m in db.dewi_maklon_inventory.docs if m.get("inventory_category") == cg.KATEGORI]


# ══════════════════════ 1. Terima & QC maklon → stok titipan, tanpa master DA ══════════════════════
def test_terima_qc_maklon_menambah_stok_titipan_tanpa_barang_master_da(monkeypatch):
    db = _base_db()
    _receipt(db, qty=45, reject=3)
    seen = _patch_finish(monkeypatch, db)
    n_master = len(db.rahaza_materials.docs)
    out = run(dcp._finish_receipt("r1", FakeRequest()))
    assert len(db.rahaza_materials.docs) == n_master                      # tidak ada barang DA baru
    assert db.rahaza_material_stock.docs[0]["qty"] == 7                   # stok DA (SKU sama) tidak berubah
    assert db.rahaza_fg_movements.docs == []                              # buku FG DA tidak disentuh
    moves = _client_moves(db)
    assert len(moves) == 1 and moves[0]["qty"] == 45 and moves[0]["movement_type"] == "masuk_terima_qc"
    assert moves[0]["stock_key"] == f"{CL_A}|cat-1|cat-1-v1" and moves[0]["buyer_catalog_id"] == "cat-1"
    ln = db.cmt_receipt_lines.docs[0]
    assert ln["client_stock_key"] == moves[0]["stock_key"] and ln.get("fg_stock_posted_at")
    assert not ln.get("fg_material_id")                                   # tidak bertaut ke master DA
    assert out["stock_posted"][0]["client_goods"] is True and out["stock_posted"][0]["cost_layer_id"] is None
    assert all(x.get("client_goods") for x in seen["ledger_lines"])      # reject klien: tanpa karantina DA
    assert run(cg.balance(db, moves[0]["stock_key"])) == 45.0


def test_terima_qc_maklon_tanpa_artikel_katalog_ditolak_tanpa_menulis(monkeypatch):
    db = _base_db()
    db.po_items.docs[0].update({"catalog_item_id": None, "maklon_variant_id": None, "sku": "SKU-LEPAS"})
    _receipt(db, sku="SKU-LEPAS")
    _patch_finish(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(dcp._finish_receipt("r1", FakeRequest()))
    assert e.value.status_code == 400 and "Katalog Buyer" in e.value.detail
    assert _client_moves(db) == [] and not db.cmt_receipt_lines.docs[0].get("fg_stock_posted_at")


def test_identitas_dari_sku_katalog_klien_tanpa_menebak():
    db = _base_db()
    ident = run(cg.resolve_identity(db, client_id=CL_A, sku="art-uji-1-htm-l"))
    assert ident["ok"] and ident["match"] == "sku_katalog" and ident["maklon_variant_id"] == "cat-1-v2"
    # SKU yang sama di DUA artikel klien → tidak ditebak
    db.dewi_maklon_buyer_catalog.docs.append(_catalog("cat-2", code="ART-UJI-2", variants=[
        {"id": "cat-2-v1", "sku": "ART-UJI-1-HTM-L", "color": "Hitam", "size": "L"}]))
    assert not run(cg.resolve_identity(db, client_id=CL_A, sku="ART-UJI-1-HTM-L"))["ok"]
    # SKU DA tanpa artikel klien → tidak cocok (bukan master DA)
    assert not run(cg.resolve_identity(db, client_id=CL_A, sku="DA-LAIN-01"))["ok"]


def test_reject_klien_tidak_masuk_karantina_da(monkeypatch):
    from core import quarantine as qmod
    db = _base_db()

    async def no_q(*_a, **_k):
        raise AssertionError("reject barang klien tidak boleh ke karantina DA")

    async def none(*_a, **_k):
        return None

    async def empty(*_a, **_k):
        return {}
    monkeypatch.setattr(qmod, "quarantine_in", no_q)
    monkeypatch.setattr(qled, "resolve_job_item_for_line", none)
    monkeypatch.setattr(shortmod, "resolve_cmt_shorts_on_arrival", empty)
    rc = {"id": "r1", "receipt_code": "RCV-UJI-1"}
    db.cmt_receipts.docs = [dict(rc)]
    line = {"id": "l1", "sku_code": "ART-UJI-1-HTM-M", "qty_actual": 5, "reject_qty": 2, "client_goods": True}
    db.cmt_receipt_lines.docs = [dict(line)]
    out = run(qled.apply_receipt_result(db, rc, [line]))
    assert out["client_rejects"] == 2 and out["quarantined"] == 0


def test_permak_berhasil_barang_klien_masuk_stok_titipan(monkeypatch):
    db = _base_db()
    ident = run(cg.resolve_identity(db, po_item_id="pi-1"))
    run(cg.record(db, identity=ident, qty=10, jenis="masuk_terima_qc", source_type="cmt_receipt", source_key="x:1"))
    db.cmt_receipt_lines.docs = [{"id": "l1", "client_stock_key": ident["stock_key"], "client_goods": True}]

    async def none(*_a, **_k):
        return None
    monkeypatch.setattr(qled, "resolve_job_item_for_line", none)
    monkeypatch.setattr(qled, "main_job_item_for_po_item", none)
    permak = {"id": "pm-1", "permak_number": "PMK-UJI-1", "permak_type": "permak_sendiri",
              "source_receipt_line_id": "l1"}
    out = run(qled.apply_rework_outcome(db, permak, qty_fixed=3, qty_scrap=1))
    assert out["client_goods"] and run(cg.balance(db, ident["stock_key"])) == 13.0
    run(qled.apply_rework_outcome(db, permak, qty_fixed=3, qty_scrap=1))      # idempoten per permak
    assert run(cg.balance(db, ident["stock_key"])) == 13.0


# ══════════════════════ 2. Kirim hasil ke klien → stok titipan berkurang ══════════════════════
def _stock_in(db, qty=45):
    ident = run(cg.resolve_identity(db, po_item_id="pi-1"))
    run(cg.record(db, identity=ident, qty=qty, jenis="masuk_terima_qc", source_type="cmt_receipt",
                  source_key="cmt_receipt_line:l1:terima"))
    return ident


def test_kirim_hasil_maklon_mengurangi_stok_titipan(monkeypatch):
    db = _base_db()
    ident = _stock_in(db, 45)

    async def no_da(*_a, **_k):
        raise AssertionError("kiriman maklon tidak boleh mengurangi stok DA")
    monkeypatch.setattr(qled, "issue_fg", no_da)
    items = [{"id": "si-1", "po_id": "po-m", "po_item_id": "pi-1", "sku": "ART-UJI-1-HTM-M", "qty_shipped": 30,
              "dispatch_seq": 1}]
    db.buyer_shipment_items.docs = [dict(items[0])]
    warn = run(bsh._fg_precheck_for_dispatch(db, items, "maklon", {"po-m": db.production_pos.docs[0]}))
    assert warn == []
    ship = {"id": "bs-1", "shipment_number": "SJ-UJI-1", "business_type": "maklon", "po_id": "po-m",
            "customer_name": "Klien Uji A"}
    out = run(bsh._issue_fg_for_dispatch(db, ship, [dict(items[0])], USER))
    assert out["client_goods"] and out["issued"][0]["qty"] == 30 and not out["warnings"]
    assert run(cg.balance(db, ident["stock_key"])) == 15.0
    it = db.buyer_shipment_items.docs[0]
    assert it["client_stock_key"] == ident["stock_key"] and it["fg_issued_qty"] == 30 and it["fg_cogs"] == 0.0
    assert db.rahaza_material_stock.docs[0]["qty"] == 7 and db.rahaza_fg_movements.docs == []
    # diulang (idempoten per baris): tidak keluar dua kali
    run(bsh._issue_fg_for_dispatch(db, ship, [dict(items[0])], USER))
    assert run(cg.balance(db, ident["stock_key"])) == 15.0


def test_kirim_maklon_melebihi_stok_titipan_ditolak():
    db = _base_db()
    _stock_in(db, 10)
    items = [{"po_item_id": "pi-1", "sku": "ART-UJI-1-HTM-M", "qty_shipped": 11}]
    with pytest.raises(HTTPException) as e:
        run(bsh._fg_precheck_for_dispatch(db, items, "maklon", {}))
    assert e.value.status_code == 400 and "tidak cukup" in e.value.detail


def test_hapus_surat_jalan_maklon_mengembalikan_stok_titipan(monkeypatch):
    db = _base_db()
    ident = _stock_in(db, 20)
    run(cg.record(db, identity=ident, qty=-8, jenis="keluar_kirim_klien", source_type="buyer_shipment",
                  source_key="buyer_shipment_item:si-1:kirim"))
    db.buyer_shipments.docs = [{"id": "bs-1", "shipment_number": "SJ-UJI-1", "business_type": "maklon",
                                "receiver_type": "buyer"}]
    db.buyer_shipment_items.docs = [{"id": "si-1", "shipment_id": "bs-1", "fg_issued_at": "x", "fg_issued_qty": 8,
                                     "client_stock_key": ident["stock_key"], "po_id": "po-m"}]

    async def su(_r):
        return {**USER, "role": "superadmin"}

    async def noop(*_a, **_k):
        return {"reopened": 0, "shorts": []}
    monkeypatch.setattr(bsh, "require_auth", su)
    monkeypatch.setattr(bsh, "get_db", lambda: db)
    monkeypatch.setattr(bsh, "_sync_maklon_mirrors", noop)
    monkeypatch.setattr(shortmod, "reopen_buyer_shorts_for_item", noop)
    out = run(bsh.delete_buyer_shipment("bs-1", FakeRequest()))
    assert out["fg_stock_reverted"] == 8 and run(cg.balance(db, ident["stock_key"])) == 20.0
    assert db.rahaza_material_stock.docs[0]["qty"] == 7


def test_selisih_klien_dan_kapasitas_kirim_memakai_stok_titipan(monkeypatch):
    from core import dispatch_capacity as dcap
    db = _base_db()
    ident = _stock_in(db, 20)
    run(cg.record(db, identity=ident, qty=-8, jenis="keluar_kirim_klien", source_type="buyer_shipment"))
    item = {"id": "si-1", "fg_issued_at": "x", "fg_issued_qty": 8, "client_stock_key": ident["stock_key"]}
    db.buyer_shipment_items.docs = [dict(item)]

    async def no_da(*_a, **_k):
        raise AssertionError("barang klien tidak boleh kembali/keluar dari stok DA")
    monkeypatch.setattr(qled, "post_fg_accepted", no_da)
    monkeypatch.setattr(qled, "issue_fg", no_da)
    assert run(shortmod._stock_back(db, item, 3, {"source": "uji"}, USER)) == 3            # belum sampai → kembali
    assert run(cg.balance(db, ident["stock_key"])) == 15.0
    assert run(shortmod._stock_out_again(db, item, 3, {"source": "uji"}, USER)) == 3       # ternyata sampai → keluar lagi
    assert run(cg.balance(db, ident["stock_key"])) == 12.0
    rows = {"k": {"po_item_id": "pi-1", "sku": "ART-UJI-1-HTM-M", "business_type": "maklon", "fg_stock": None}}
    run(dcap._enrich_fg_stock(db, rows))
    assert rows["k"]["fg_stock"] == 12.0                                                   # bukan stok DA (7)


# ══════════════════════ 3. Tanpa nilai, tanpa jurnal ══════════════════════
def test_stok_titipan_tanpa_nilai_dan_tanpa_jurnal(monkeypatch):
    db = _base_db()
    _receipt(db, qty=12)
    _patch_finish(monkeypatch, db)
    run(dcp._finish_receipt("r1", FakeRequest()))
    mv = _client_moves(db)[0]
    for f in ("unit_cost", "value", "amount", "hpp", "cogs", "nilai", "price"):
        assert f not in mv
    assert db.rahaza_journal_entries.docs == [] and db.rahaza_journal_lines.docs == []
    assert db.fg_cost_layers.docs == []
    with pytest.raises(TypeError):
        run(cg.record(db, identity={"ok": True, "stock_key": "k"}, qty=1, jenis="masuk_terima_qc",
                      source_type="x", unit_cost=1000))                                    # tidak ada isian nilai
    src = (BACKEND / "core" / "client_goods.py").read_text(encoding="utf-8")
    for mod in ("rahaza_posting", "fg_cost_layers", "stock_service", "rahaza_journal"):
        assert mod not in src, mod                                                  # tidak menyentuh buku DA


# ══════════════════════ 4. Saringan Kepemilikan (termasuk stok 0) ══════════════════════
def _inv_db():
    db = _base_db()
    db.dewi_maklon_buyer_catalog.docs.append(_catalog("cat-b", client=CL_B, code="ART-UJI-B", variants=[
        {"id": "cat-b-v1", "sku": "ART-UJI-B-PTH-S", "color": "Putih", "size": "S", "active": True}]))
    db.rahaza_materials.docs += [
        {"id": "fg-da-2", "type": "fg", "code": "DA-UJI-2", "name": "Barang DA 2", "active": True},
        {"id": "fg-klien-lama", "type": "fg", "code": "KLIEN-LAMA-1", "name": "Barang klien lama", "active": True,
         "owner_type": "client", "owner_client_id": CL_A}]
    db.rahaza_material_stock.docs.append({"id": "st-kl", "material_id": "fg-klien-lama", "location_id": "loc-fg",
                                          "qty": 4, "ownership": CL_A, "inventory_category": "maklon_fg"})
    _stock_in(db, 45)
    return db


def _list(db, monkeypatch, **kw):
    monkeypatch.setattr(ui, "get_db", lambda: db)
    return run(ui.list_unified_stock(FakeRequest(), user=USER, **kw))


def test_kepemilikan_milik_da_hanya_barang_da(monkeypatch):
    db = _inv_db()
    out = _list(db, monkeypatch, ownership="cv_da", include_zero="1", limit=500)
    codes = {i["material_code"] for i in out["items"]}
    assert codes == {"ART-UJI-1-HTM-M", "DA-UJI-2"}                       # barang klien lama & titipan tidak ikut
    assert all(i["ownership_label"] == "Milik CV Dewi Aditya" for i in out["items"])
    assert {c["id"] for c in out["facets"]["clients"]} == {CL_A, CL_B}


def test_kepemilikan_titipan_stok_0_bukan_master_da(monkeypatch):
    db = _inv_db()
    out = _list(db, monkeypatch, ownership="titipan_klien", include_zero="1", limit=500)
    items = out["items"]
    # bug lama: "Maklon Clients" + stok 0 menampilkan seluruh master DA → sekarang varian Katalog Buyer klien
    assert not any(i["material_code"] in ("DA-UJI-2", "KLIEN-LAMA-1") for i in items)
    assert {i["stock_key"] for i in items} == {f"{CL_A}|cat-1|cat-1-v1", f"{CL_A}|cat-1|cat-1-v2",
                                               f"{CL_B}|cat-b|cat-b-v1"}
    have = {i["stock_key"]: i for i in items}
    assert have[f"{CL_A}|cat-1|cat-1-v1"]["quantity"] == 45 and have[f"{CL_A}|cat-1|cat-1-v2"]["no_stock_row"]
    assert all(i["ownership"] == "titipan_klien" and i["has_value"] is False for i in items)
    assert out["totals"]["quantity"] == 45 and out["totals"]["clients"] == 2
    # tanpa stok 0: hanya yang bersaldo
    out = _list(db, monkeypatch, ownership="titipan_klien", limit=500)
    assert [i["stock_key"] for i in out["items"]] == [f"{CL_A}|cat-1|cat-1-v1"]
    # nilai lama "maklon" diarahkan ke titipan (deep link lama)
    assert _list(db, monkeypatch, ownership="maklon", limit=500)["total"] == 1


def test_kepemilikan_titipan_sub_saringan_klien(monkeypatch):
    db = _inv_db()
    out = _list(db, monkeypatch, ownership="titipan_klien", include_zero="1", client_id=CL_B, limit=500)
    assert [i["stock_key"] for i in out["items"]] == [f"{CL_B}|cat-b|cat-b-v1"]
    assert out["items"][0]["owner_client_name"] == "Klien Uji B"


def test_riwayat_titipan_berlabel_indonesia(monkeypatch):
    db = _inv_db()
    monkeypatch.setattr(ui, "get_db", lambda: db)
    out = run(ui.titipan_klien_mutasi(f"{CL_A}|cat-1|cat-1-v1", user=USER))
    assert out["balance"] == 45 and out["items"][0]["jenis_label"].startswith("Masuk")


# ══════════════════════ 5. Migrasi 2026_11_07_titipan_klien ══════════════════════
def _mig():
    p = BACKEND / "scripts" / "migrations" / "2026_11_07_titipan_klien.py"
    spec = importlib.util.spec_from_file_location("mig_titipan_klien", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _mig_db():
    db = _base_db()
    db.dewi_maklon_buyer_catalog.docs.append(_catalog("cat-b", client=CL_B, code="ART-UJI-B", variants=[
        {"id": "cat-b-v1", "sku": "UJI-T9-ASING", "color": "Putih", "size": "S", "active": True}]))
    db.rahaza_materials.docs += [
        # A: cocok lewat tautan baris penerimaan → baris PO → artikel/varian katalog
        {"id": "m-a", "type": "fg", "code": "UJI-T9-gudang-A", "owner_type": "client", "owner_client_id": CL_A,
         "active": True},
        # B: cocok lewat SKU varian katalog klien pemiliknya
        {"id": "m-b", "type": "fg", "code": "ART-UJI-1-HTM-L", "owner_type": "client", "owner_client_id": CL_A,
         "active": True},
        # C: tidak ada artikel → dilaporkan
        {"id": "m-c", "type": "fg", "code": "UJI-T9-gudang-C", "owner_type": "client", "owner_client_id": CL_A,
         "active": True},
        # D: SKU cocok hanya di katalog klien LAIN → tidak ditebak
        {"id": "m-d", "type": "fg", "code": "UJI-T9-ASING", "owner_type": "client", "owner_client_id": CL_A,
         "active": True}]
    db.rahaza_material_stock.docs += [
        {"id": "s-a", "material_id": "m-a", "location_id": "loc-fg", "qty": 12, "ownership": CL_A,
         "inventory_category": "maklon_fg"},
        {"id": "s-b", "material_id": "m-b", "location_id": "loc-fg", "qty": 5, "ownership": CL_A,
         "inventory_category": "maklon_fg"},
        {"id": "s-c", "material_id": "m-c", "location_id": "loc-fg", "qty": 3, "ownership": CL_A,
         "inventory_category": "maklon_fg"}]
    db.cmt_receipt_lines.docs = [{"id": "l-a", "receipt_id": "r-a", "fg_material_id": "m-a", "po_item_id": "pi-1",
                                  "fg_stock_posted_at": "x", "fg_stock_posted_qty": 12}]
    db.buyer_shipment_items.docs = [{"id": "si-a", "fg_material_id": "m-a", "fg_issued_at": "x", "fg_issued_qty": 2}]
    return db


def test_migrasi_mencocokkan_tanpa_menebak():
    m = _mig()
    db = _mig_db()
    items = {x["id"]: x for x in db.rahaza_materials.docs}
    a = run(m.match_item(db, items["m-a"]))
    assert a["ok"] and a["stock_key"] == f"{CL_A}|cat-1|cat-1-v1" and a["match"] == "tautan_po"
    b = run(m.match_item(db, items["m-b"]))
    assert b["ok"] and b["stock_key"] == f"{CL_A}|cat-1|cat-1-v2" and b["match"] == "sku_katalog"
    assert not run(m.match_item(db, items["m-c"]))["ok"]
    assert not run(m.match_item(db, items["m-d"]))["ok"]


def test_migrasi_pratinjau_baca_saja_lalu_tulis_idempoten(capsys):
    m = _mig()
    db = _mig_db()
    before = {k: [dict(d) for d in v.docs] for k, v in db._cols.items()}
    out = run(m.run(db, apply=False))
    assert {k: v.docs for k, v in db._cols.items() if k in before} == before          # pratinjau tidak menulis
    assert out["candidates"] == 4 and out["matched"] == 2 and out["unmatched"] == 2
    assert {u["sku"] for u in out["unmatched_list"]} == {"UJI-T9-gudang-C", "UJI-T9-ASING"}
    with pytest.raises(m.ReadOnlyError):
        run(m.ReadOnlyDB(db).rahaza_materials.update_one({}, {"$set": {"x": 1}}))
    out = run(m.run(db, apply=True))
    assert out["moved"] == 2 and out["stock_qty"] == 17
    mats = {x["id"]: x for x in db.rahaza_materials.docs}
    assert mats["m-a"]["active"] is False and mats["m-b"]["active"] is False      # dinonaktifkan, tidak dihapus
    assert mats["m-c"]["active"] is True and mats["m-d"]["active"] is True        # tidak cocok → tidak diubah
    st = {x["id"]: x for x in db.rahaza_material_stock.docs}
    assert st["s-a"]["qty"] == 0 and st["s-b"]["qty"] == 0 and st["s-c"]["qty"] == 3
    assert run(cg.balance(db, f"{CL_A}|cat-1|cat-1-v1")) == 12 and run(cg.balance(db, f"{CL_A}|cat-1|cat-1-v2")) == 5
    assert db.cmt_receipt_lines.docs[0]["client_stock_key"] == f"{CL_A}|cat-1|cat-1-v1"
    assert db.buyer_shipment_items.docs[0]["client_stock_key"] == f"{CL_A}|cat-1|cat-1-v1"
    n = len(_client_moves(db))
    again = run(m.run(db, apply=True))
    assert again["already_moved"] == 2 and again["moved"] == 0 and len(_client_moves(db)) == n
    assert "Klien Uji" not in capsys.readouterr().out                              # ringkasan tanpa nama klien


# ══════════════════════ 6. layar & pendaftaran ══════════════════════
def test_layar_daftar_stok_kepemilikan_dan_bahasa():
    s = (FE / "components" / "erp" / "UnifiedInventoryModule.jsx").read_text(encoding="utf-8")
    assert "<" + "select" not in s and "<" + "table" not in s and "<" + "h1" not in s
    assert "PageLayout" in s and "DetailPanel" in s and "Dialog" not in s and "window.confirm" not in s
    assert "'Milik CV Dewi Aditya'" in s and "'Titipan klien maklon'" in s and "inv-filter-client" in s
    for bad in ("Maklon Clients", "Unified Inventory", "Semua Ownership", "Actions</", "Quantity</",
                "Available</", "Reserved</", "{item.inventory_category}", "{i.inventory_category}"):
        assert bad not in s, bad
    hub = (FE / "components" / "erp" / "hubs" / "WMSStockHub.jsx").read_text(encoding="utf-8")
    assert "Viewer Stok (Unified)" not in hub and "'Daftar stok'" in hub


def test_koleksi_titipan_memakai_koleksi_terdaftar():
    from core.collection_registry import KIND, REGISTRY
    assert REGISTRY.get(cg.COLL) == "maklon" and KIND.get(cg.COLL) == "transaksi"
    src = (BACKEND / "routes" / "dewi_cmt_packing.py").read_text(encoding="utf-8")
    assert '"owner_type": "client"' not in src                                      # master DA "milik klien" tidak lahir lagi
