"""Tahap 8 (7 Nov 2026) — K12 form PO seragam + upah jahit per baris, dan hak Buat/Ubah/Hapus PO (sisi server).

  K12-a  `core.sewing_rate.parse_rate`: upah ≥ 0, kosong = 0, negatif / bukan angka ditolak.
  K12-b  Usulan upah: tarif terakhir model sama + penjahit sama → bawaan model/katalog → (tanpa penjahit) tarif
         terakhir model → kosong. PO batal, PO jenis lain, dan PO yang sedang diubah tidak dipakai.
  K12-c  Buat PO internal menyimpan upah dari form (+ jejak); upah negatif ditolak sebelum PO ditulis.
  K12-d  Ubah PO: upah berubah setelah tagihan CMT ada → 409 (penjaga yang sama dengan Biaya Jahit).
  K12-e  Kirim Material CMT: penjahit dipilih saat kirim + baris tanpa upah → 400, tidak ada yang ditulis.
  K12-f  Biaya Jahit memakai usulan & penjaga yang SAMA (tidak ada hitungan kedua).
  PO-hak Tombol & server satu aturan: peran bawaan atau izin granular mod.prod_po.* / mod.mak_po.*.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
from core import sewing_rate as sr  # noqa: E402

ADMIN = {"id": "u1", "name": "Admin Uji", "role": "admin_produksi", "_permissions": []}
FE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "erp"


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


def _dt(day):
    return datetime(2026, 10, day, tzinfo=timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# K12-a · parse_rate
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("raw,want", [(None, 0.0), ("", 0.0), ("  ", 0.0), (0, 0.0), ("12500", 12500.0),
                                      (9000.5, 9000.5), ("7,5", 7.5)])
def test_upah_sah(raw, want):
    assert sr.parse_rate(raw, "baris 1") == want


@pytest.mark.parametrize("raw,msg", [(-1, "negatif"), ("-500", "negatif"), ("abc", "bukan angka"),
                                     (float("nan"), "negatif")])
def test_upah_tidak_sah(raw, msg):
    with pytest.raises(ValueError) as e:
        sr.parse_rate(raw, "baris 2 (KAOS-M)")
    assert msg in str(e.value) and "baris 2 (KAOS-M)" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════════
# K12-b · usulan upah
# ══════════════════════════════════════════════════════════════════════════════
def _history_db():
    db = FakeDB()
    db.vendor_partners.docs = [{"id": "vA", "name": "CMT Alpha"}, {"id": "vB", "name": "CMT Beta"},
                               {"id": "vC", "name": "CMT Gamma"}]
    db.production_pos.docs = [
        {"id": "P1", "po_number": "PO-INT-1", "vendor_id": "vA", "vendor_name": "CMT Alpha", "status": "Closed",
         "business_type": "internal"},
        {"id": "P2", "po_number": "PO-INT-2", "vendor_id": "vB", "vendor_name": "CMT Beta", "status": "Confirmed",
         "business_type": "internal"},
        {"id": "P3", "po_number": "PO-INT-3", "vendor_id": "vA", "vendor_name": "CMT Alpha", "status": "Cancelled",
         "business_type": "internal"},
        {"id": "P4", "po_number": "PO-MKL-4", "vendor_id": "vA", "vendor_name": "CMT Alpha", "status": "Confirmed",
         "business_type": "maklon"},
        {"id": "P5", "po_number": "PO-INT-5", "vendor_id": "vA", "vendor_name": "CMT Alpha", "status": "Draft",
         "business_type": "internal"},
    ]
    db.po_items.docs = [
        {"id": "a", "po_id": "P1", "model_id": "M1", "sku": "M1-HTM-M", "cmt_price_snapshot": 9000, "created_at": _dt(1)},
        {"id": "b", "po_id": "P2", "model_id": "M1", "sku": "M1-HTM-M", "cmt_price_snapshot": 11000, "created_at": _dt(5)},
        # PO batal tidak dipakai walau paling baru
        {"id": "c", "po_id": "P3", "model_id": "M1", "sku": "M1-HTM-M", "cmt_price_snapshot": 99000, "created_at": _dt(9)},
        # PO maklon tidak dipakai untuk usulan internal
        {"id": "d", "po_id": "P4", "model_id": "M1", "catalog_item_id": "K1", "cmt_price_snapshot": 50000,
         "created_at": _dt(9)},
        # PO yang sedang diubah tidak mengusulkan dirinya sendiri
        {"id": "e", "po_id": "P5", "model_id": "M1", "sku": "M1-HTM-M", "cmt_price_snapshot": 77000, "created_at": _dt(8)},
    ]
    db.rahaza_model_costing.docs = [{"model_id": "M2", "cmt_rate_per_pcs": 6500}]
    db.dewi_maklon_buyer_catalog.docs = [{"id": "K1", "artikel_code": "ART-1", "default_cmt_price": 15000},
                                         {"id": "K2", "artikel_code": "ART-2", "default_cmt_price": 0}]
    return db


def test_usulan_tarif_terakhir_penjahit_sama():
    db = _history_db()
    out = run(sr.suggest_rates(db, [{"key": "x", "model_id": "M1", "sku": "M1-HTM-M"}], vendor_id="vA",
                               exclude_po_id="P5"))
    s = out["x"]
    # P3 batal & P5 sedang diubah → P1 (9.000) walau P2 lebih baru (penjahit lain)
    assert s["rate"] == 9000 and s["source"] == "vendor_last" and s["po_number"] == "PO-INT-1"
    assert "CMT Alpha" in s["note"] and "PO-INT-1" in s["note"]
    out = run(sr.suggest_rates(db, [{"key": "x", "model_id": "M1"}], vendor_id="vB"))
    assert out["x"]["rate"] == 11000 and out["x"]["po_number"] == "PO-INT-2"


def test_usulan_cadangan_bawaan_model_lalu_kosong():
    db = _history_db()
    out = run(sr.suggest_rates(db, [{"key": "m1", "model_id": "M1"}, {"key": "m2", "model_id": "M2"},
                                    {"key": "m3", "model_id": "M3"}], vendor_id="vC"))
    # penjahit vC belum pernah menjahit M1, M1 tidak punya tarif bawaan → kosong (bukan tarif penjahit lain)
    assert out["m1"]["rate"] == 0 and out["m1"]["source"] == "none" and "CMT Gamma" in out["m1"]["note"]
    assert out["m2"]["rate"] == 6500 and out["m2"]["source"] == "model_default"
    assert out["m3"]["rate"] == 0 and out["m3"]["source"] == "none"


def test_usulan_tanpa_penjahit_tarif_terakhir_model():
    db = _history_db()
    out = run(sr.suggest_rates(db, [{"key": "x", "model_id": "M1"}], vendor_id=None, exclude_po_id="P5"))
    assert out["x"]["rate"] == 11000 and out["x"]["source"] == "last_any" and "CMT Beta" in out["x"]["note"]


def test_usulan_maklon_per_artikel_katalog():
    db = _history_db()
    out = run(sr.suggest_rates(db, [{"key": "k1", "catalog_item_id": "K1"}, {"key": "k2", "catalog_item_id": "K2"}],
                               vendor_id="vA", business_type="maklon"))
    assert out["k1"]["rate"] == 50000 and out["k1"]["source"] == "vendor_last"
    out = run(sr.suggest_rates(db, [{"key": "k1", "catalog_item_id": "K1"}], vendor_id="vB", business_type="maklon"))
    assert out["k1"]["rate"] == 15000 and out["k1"]["source"] == "catalog_default" and "ART-1" in out["k1"]["note"]
    out = run(sr.suggest_rates(db, [{"key": "k2", "catalog_item_id": "K2"}], vendor_id="vB", business_type="maklon"))
    assert out["k2"]["rate"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# K12-c · buat PO internal menyimpan upah dari form
# ══════════════════════════════════════════════════════════════════════════════
def _po_env(monkeypatch):
    import core.doc_number_policy as dnp
    import routes.production_pos as pp
    import routes.production_internal_adapter as pia
    db = FakeDB()
    db.rahaza_models.docs = [{"id": "M1", "code": "KAOS", "name": "Kaos Uji", "active": True}]
    db.rahaza_sizes.docs = [{"id": "S-M", "code": "M", "active": True}]
    db.rahaza_model_variants.docs = [{"id": "V1", "model_id": "M1", "size_id": "S-M", "size_code": "M",
                                      "color_name": "Hitam", "color_code": "HTM", "sku": "KAOS-HTM-M",
                                      "active": True}]
    db.vendor_partners.docs = [{"id": "vA", "name": "CMT Alpha"}]

    async def number(*_a, **_k):
        return "PO-INT-UJI-1"

    async def explode(*_a, **_k):
        return {}
    monkeypatch.setattr(dnp, "issue_number", number)
    monkeypatch.setattr(pp, "log_activity", _noop)
    monkeypatch.setattr(pp, "get_db", lambda: db)
    monkeypatch.setattr(pia, "explode_po_accessories_from_bom", explode)

    async def auth(_req):
        return dict(ADMIN)
    monkeypatch.setattr(pp, "require_auth", auth)
    return pp, db


def _po_body(rate):
    return {"business_type": "internal", "customer_name": "Gudang FG Sendiri", "vendor_id": "vA",
            "items": [{"model_id": "M1", "rahaza_variant_id": "V1", "qty": 10, "serial_number": "SN-1",
                       "cmt_price_snapshot": rate}]}


def test_buat_po_internal_menyimpan_upah_dari_form(monkeypatch):
    pp, db = _po_env(monkeypatch)
    out = run(pp.create_po_internal(db, _po_body(12500), ADMIN))
    it = db.po_items.docs[0]
    assert out["business_type"] == "internal" and it["cmt_price_snapshot"] == 12500
    assert it["cmt_price_set_by"] == "Admin Uji" and it["sku"] == "KAOS-HTM-M"


def test_buat_po_upah_negatif_ditolak_sebelum_ditulis(monkeypatch):
    pp, db = _po_env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(pp.create_po_internal(db, _po_body(-100), ADMIN))
    assert e.value.status_code == 400 and "negatif" in e.value.detail
    assert db.production_pos.docs == [] and db.po_items.docs == []


def test_buat_po_upah_kosong_tetap_boleh(monkeypatch):
    pp, db = _po_env(monkeypatch)
    run(pp.create_po_internal(db, _po_body(""), ADMIN))
    it = db.po_items.docs[0]
    assert it["cmt_price_snapshot"] == 0 and "cmt_price_set_by" not in it


# ══════════════════════════════════════════════════════════════════════════════
# K12-d · ubah PO: upah terkunci setelah tagihan CMT
# ══════════════════════════════════════════════════════════════════════════════
def _edit_env(monkeypatch, *, bill=None):
    pp, db = _po_env(monkeypatch)
    db.production_pos.docs = [{"id": "P1", "po_number": "PO-INT-1", "status": "Confirmed", "business_type": "internal",
                               "vendor_id": "vA", "vendor_name": "CMT Alpha"}]
    db.po_items.docs = [{"id": "i1", "po_id": "P1", "model_id": "M1", "size_id": "S-M", "rahaza_variant_id": "V1",
                         "sku": "KAOS-HTM-M", "size": "M", "color": "Hitam", "qty": 10, "cmt_price_snapshot": 9000,
                         "product_name": "Kaos Uji"}]
    if bill:
        db.dewi_cmt_payments.docs = [bill]
    return pp, db


def _edit_body(rate):
    return {"notes": "ubah", "items": [{"id": "i1", "rahaza_variant_id": "V1", "qty": 10, "cmt_price_snapshot": rate}]}


def test_ubah_upah_sebelum_tagihan_boleh_dan_berjejak(monkeypatch):
    pp, db = _edit_env(monkeypatch)
    run(pp.update_po("P1", FakeRequest(_edit_body("10500"))))
    it = db.po_items.docs[0]
    assert it["cmt_price_snapshot"] == 10500 and it["cmt_price_set_by"] == "Admin Uji"


def test_ubah_upah_setelah_tagihan_cmt_ditolak(monkeypatch):
    pp, db = _edit_env(monkeypatch, bill={"id": "b1", "po_id": "P1", "payment_code": "PAY-CMT-00007",
                                          "status": "draft"})
    with pytest.raises(HTTPException) as e:
        run(pp.update_po("P1", FakeRequest(_edit_body(10500))))
    assert e.value.status_code == 409 and "PAY-CMT-00007" in e.value.detail and "terkunci" in e.value.detail
    assert db.po_items.docs[0]["cmt_price_snapshot"] == 9000
    assert "notes" not in db.production_pos.docs[0]          # ditolak SEBELUM kepala PO ditulis
    # upah tidak berubah (simpan ulang form) tetap boleh walau tagihan ada
    run(pp.update_po("P1", FakeRequest(_edit_body(9000))))
    assert db.production_pos.docs[0]["notes"] == "ubah"
    # tagihan dibatalkan → boleh lagi
    db.dewi_cmt_payments.docs[0]["status"] = "cancelled"
    run(pp.update_po("P1", FakeRequest(_edit_body(10500))))
    assert db.po_items.docs[0]["cmt_price_snapshot"] == 10500


def test_ubah_upah_negatif_ditolak(monkeypatch):
    pp, db = _edit_env(monkeypatch)
    with pytest.raises(HTTPException) as e:
        run(pp.update_po("P1", FakeRequest(_edit_body(-1))))
    assert e.value.status_code == 400 and db.po_items.docs[0]["cmt_price_snapshot"] == 9000


def test_ubah_baris_po_langsung_ikut_terkunci(monkeypatch):
    pp, db = _edit_env(monkeypatch, bill={"id": "b1", "po_id": "P1", "payment_code": "PAY-CMT-00008",
                                          "status": "posted"})
    with pytest.raises(HTTPException) as e:
        run(pp.update_po_item("i1", FakeRequest({"cmt_price_snapshot": 1})))
    assert e.value.status_code == 409 and db.po_items.docs[0]["cmt_price_snapshot"] == 9000


def test_detail_po_membawa_kunci_upah(monkeypatch):
    pp, db = _edit_env(monkeypatch, bill={"id": "b1", "po_id": "P1", "payment_code": "PAY-CMT-00009",
                                          "status": "draft"})

    async def photos(items, _db):
        return items
    monkeypatch.setattr(pp, "enrich_with_product_photos", photos)
    out = run(pp.get_po("P1", FakeRequest()))
    assert out["rate_lock"]["bill_ref"] == "PAY-CMT-00009"


# ══════════════════════════════════════════════════════════════════════════════
# K12-e · Kirim Material CMT: penjahit dipilih saat kirim → upah wajib ada (diblokir, tautan ke PO)
# ══════════════════════════════════════════════════════════════════════════════
def test_kirim_po_tanpa_vendor_dan_tanpa_upah_ditolak():
    import routes.vendor_shipment as vs
    db = FakeDB()
    db.production_pos.docs = [{"id": "p1", "po_number": "PO-UJI-1", "status": "Confirmed", "business_type": "internal"},
                              {"id": "p2", "po_number": "PO-UJI-2", "status": "Confirmed", "business_type": "internal",
                               "vendor_id": "v1"}]
    db.po_items.docs = [{"id": "i1", "po_id": "p1", "qty": 10, "sku": "S1", "cmt_price_snapshot": 0},
                        {"id": "i2", "po_id": "p1", "qty": 5, "sku": "S2", "cmt_price_snapshot": 8000},
                        {"id": "i3", "po_id": "p2", "qty": 5, "sku": "S3", "cmt_price_snapshot": 0}]
    with pytest.raises(HTTPException) as e:
        run(vs.assert_rates_for_vendorless_pos(db, {"p1"}, [{"po_item_id": "i1"}, {"po_item_id": "i2"}]))
    assert e.value.status_code == 400 and "S1" in e.value.detail and "PO-UJI-1" in e.value.detail
    assert "S2" not in e.value.detail and "form PO" in e.value.detail
    # baris berupah saja → boleh; PO yang SUDAH ber-vendor tidak diperiksa di sini (upah 0 boleh, mis. tim sendiri)
    run(vs.assert_rates_for_vendorless_pos(db, {"p1"}, [{"po_item_id": "i2"}]))
    run(vs.assert_rates_for_vendorless_pos(db, {"p2"}, [{"po_item_id": "i3"}]))


def test_kirim_surat_jalan_tanpa_upah_tidak_menulis_apa_pun(monkeypatch):
    import routes.vendor_shipment as vs
    import core.doc_number_policy as dnp
    db = FakeDB()
    db.vendor_partners.docs = [{"id": "v1", "code": "CMT-01", "name": "CMT Alpha", "active": True}]
    db.production_pos.docs = [{"id": "p1", "po_number": "PO-UJI-1", "status": "Confirmed", "business_type": "internal"}]
    db.po_items.docs = [{"id": "i1", "po_id": "p1", "qty": 10, "product_name": "Kaos Uji", "sku": "S1"}]
    issued = []

    async def number(*_a, **_k):
        issued.append(1)
        return "SJ-UJI-1"
    monkeypatch.setattr(dnp, "issue_number", number)
    body = {"vendor_id": "v1", "shipment_type": "NORMAL", "accessory_items": [],
            "items": [{"po_id": "p1", "po_number": "PO-UJI-1", "po_item_id": "i1", "qty_sent": 4}]}
    with pytest.raises(HTTPException) as e:
        run(vs.create_vendor_shipment_internal(db, body, {"id": "u1", "name": "Uji", "role": "admin"}))
    assert e.value.status_code == 400 and "Upah jahit" in e.value.detail
    assert issued == [] and db.vendor_shipments.docs == [] and not db.production_pos.docs[0].get("vendor_id")


# ══════════════════════════════════════════════════════════════════════════════
# K12-f · Biaya Jahit = rekap; usulan & penjaga dari pintu yang sama
# ══════════════════════════════════════════════════════════════════════════════
def test_biaya_jahit_memakai_usulan_bersama():
    import routes.production_sewing_cost as sc
    db = _history_db()
    po = {"id": "P5", "vendor_id": "vA", "business_type": "internal"}
    out = run(sc._suggestions(db, [{"id": "e", "model_id": "M1", "sku": "M1-HTM-M"}], po))
    assert out["e"]["rate"] == 9000 and out["e"]["source"] == "vendor_last"     # bukan tarif PO-nya sendiri
    assert sc.cmt_rate_lock is sr.rate_lock
    src = Path(sc.__file__).read_text(encoding="utf-8")
    assert "dewi_cmt_partners" not in src           # usulan "tarif termurah partner CMT" (penjahit mana pun) dihapus


def test_po_tanpa_jenis_dianggap_internal():
    from core import product_costing as pc
    assert pc.po_business_type({"vendor_id": "vA"}) == "internal"
    assert pc.po_business_type({"business_type": "maklon"}) == "maklon"


# ══════════════════════════════════════════════════════════════════════════════
# PO-hak · tombol & server satu aturan
# ══════════════════════════════════════════════════════════════════════════════
def _u(role, perms=()):
    return {"id": "u-" + role, "name": role, "role": role, "_permissions": list(perms)}


@pytest.mark.parametrize("role,perms,bt,action,want", [
    ("admin_produksi", (), "internal", "create", True),
    ("admin_maklon", (), "maklon", "create", True),
    ("supervisor_produksi", (), "internal", "edit", True),
    ("owner", (), "maklon", "delete", True),
    ("admin_produksi", (), "internal", "delete", False),          # hapus beruntun: bawaan sempit
    ("spv_cuting", (), "internal", "create", False),
    ("spv_cuting", ("mod.prod_po.create",), "internal", "create", True),
    ("spv_cuting", ("mod.prod_po.create",), "maklon", "create", False),   # izin per jenis PO
    ("spv_cuting", ("mod.mak_po.create",), "maklon", "create", True),
    ("spv_cuting", ("mod.prod_po.delete",), "internal", "delete", True),
    ("spv_cuting", ("po.create",), "internal", "create", False),          # po.create = PO PEMBELIAN
    ("staff", ("*",), "internal", "delete", True),
])
def test_hak_po_per_peran(role, perms, bt, action, want):
    from routes.production_rbac import can_po_action
    assert can_po_action(_u(role, perms), action, bt) is want


def test_server_menolak_buat_po_tanpa_hak(monkeypatch):
    pp, db = _po_env(monkeypatch)

    async def auth(_req):
        return _u("spv_cuting")
    monkeypatch.setattr(pp, "require_auth", auth)
    with pytest.raises(HTTPException) as e:
        run(pp.create_po(FakeRequest(_po_body(9000))))
    # 14 Nov 2026: pesan menyebut kotak centang & letaknya, tanpa kunci izin program (mod.prod_po.create)
    assert e.value.status_code == 403 and "\"Tambah\" pada modul \"PO Internal & Tutup PO\"" in e.value.detail
    assert "Kontrol Akses › Peran & Hak Akses" in e.value.detail and "mod." not in e.value.detail
    assert db.production_pos.docs == []

    async def auth2(_req):
        return _u("spv_cuting", ("mod.prod_po.create",))
    monkeypatch.setattr(pp, "require_auth", auth2)
    res = run(pp.create_po(FakeRequest(_po_body(9000))))
    assert res.status_code == 201 and len(db.production_pos.docs) == 1


def test_flag_hak_mengikuti_gerbang_modul(monkeypatch):
    import middleware.module_permission_gate as gate
    from routes.production_rbac import po_action_flags
    calls = []

    async def evaluate(method, path, payload):
        calls.append((method, path))
        return ({"id": "prod_po"}, "edit", "perm") if method == "PUT" else None
    monkeypatch.setattr(gate, "evaluate", evaluate)
    out = run(po_action_flags(_u("admin_produksi"), "internal"))
    assert out == {"can_create": True, "can_edit": False, "can_delete": False}
    assert ("POST", "/api/production-pos") in calls and ("DELETE", "/api/production-pos/_") not in calls


def test_endpoint_hak_terdaftar_sebelum_detail_po():
    import routes.production_pos as pp
    paths = [(r.path, sorted(r.methods)) for r in pp.router.routes]
    assert paths.index(("/api/production-pos/permissions", ["GET"])) < paths.index(("/api/production-pos/{po_id}", ["GET"]))


# ══════════════════════════════════════════════════════════════════════════════
# Layar (statis)
# ══════════════════════════════════════════════════════════════════════════════
def test_layar_po_satu_bentuk_dan_hak_dari_server():
    src = (FE / "engine" / "ProductionPOModule.jsx").read_text(encoding="utf-8")
    assert "hasPerm(" not in src                          # hak dari server, bukan aturan layar sendiri
    assert "/production-pos/permissions" in src and "/production-pos/rate-suggest" in src
    # kotak upah jahit tampil untuk KEDUA jenis (tidak dibungkus kondisi maklon)
    i = src.index('data-testid={`po-item-${idx}-rate`}')
    assert "{!isInternal && (" not in src[src.rfind("<Field", 0, i) - 60:i]
    for sec in ("po-form-header", "po-form-lines", "po-form-accessories", "po-form-totals"):
        assert f'data-testid="{sec}"' in src
    assert "SKU terpilih: " not in src and "sku-ok" not in src   # SKU tidak lagi tampil tiga kali
    assert "<" + "select" not in src


def test_layar_kirim_material_menautkan_ke_po():
    src = (FE / "engine" / "kirim" / "KirimanForm.jsx").read_text(encoding="utf-8")   # Tahap 9: form kiriman
    assert "edit_po_id: po.id" in src and 'testId="kirim-no-rate"' in src
