"""Kirim Sample banyak produk + alur gudang + PO "Sampel R&D" (keputusan owner 14 Nov 2026) — uji HERMETIK.

  K1  Satu kiriman banyak produk, SATU ongkir; HPP per baris dari katalog; dokumen lama dibaca sebagai satu baris.
  K2  Status kirim & tindak lanjut bebas maju-mundur (PUT /status), nilai asing ditolak, riwayat tercatat.
  K3  Stok cukup ⇒ "Menunggu gudang"; Keluarkan stok (alasan Sampel) tertaut ke baris: produk sama, jumlah ≤ sisa,
      lalu baris ditandai keluar. Antrean gudang mengikuti sisanya.
  K4  Stok kurang ⇒ SATU draf PO berlabel sampel_rnd untuk kekurangannya (tidak dobel); penomoran manual ⇒ catatan.
      R&D: setujui + varian ⇒ PO; style belum ber-model ⇒ catatan; "Buat draf PO sampel" aman diulang.
  K5  Anggaran: kategori sampel otomatis = Σ (HPP + ongkir) kiriman toko itu di periodenya.
  K6  Lingkup toko: kiriman toko lain = 404 untuk GET/PUT/status/DELETE.
"""
import asyncio
import itertools
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _mkt_uji as mu  # noqa: E402

ADMIN = {"id": "u-adm", "name": "Admin Uji", "email": "adm@uji.test", "role": "admin"}
PIC_A = {"id": "u-pic-a", "name": "PIC A", "email": "pica@uji.test", "role": "pic_toko"}


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Lingkungan uji
# ══════════════════════════════════════════════════════════════════════════════
def _seed(db, stok1=5, stok2=10):
    db.marketing_platform_accounts.docs = [mu.acc("A", pic_user_id=PIC_A["id"]), mu.acc("B")]
    db.marketing_kol_creators.docs = [
        {"id": "CR1", "name": "Ayu", "platforms": {"tiktok": "@ayu"}, "assigned_account_ids": ["A"]},
        {"id": "CR2", "name": "Budi", "platforms": {"tiktok": "@budi"}, "assigned_account_ids": ["B"]}]
    db.marketing_catalog_items.docs = [
        {"id": "CI1", "account_id": "A", "sku": "KAOS-HTM-M", "variant_sku": "KAOS-HTM-M", "name": "Kaos Uji",
         "hpp": 50000, "fg_size": "M", "fg_color": "Hitam"},
        {"id": "CI2", "account_id": "A", "sku": "ROK-NVY-L", "variant_sku": "ROK-NVY-L", "name": "Rok Uji",
         "hpp": 70000, "fg_size": "L", "fg_color": "Navy"},
        {"id": "CIB", "account_id": "B", "sku": "KAOS-HTM-M", "variant_sku": "KAOS-HTM-M", "name": "Kaos B",
         "hpp": 50000}]
    db.rahaza_materials.docs = [{"id": "FG1", "type": "fg", "code": "KAOS-HTM-M", "name": "Kaos Hitam M"},
                                {"id": "FG2", "type": "fg", "code": "ROK-NVY-L", "name": "Rok Navy L"}]
    db.rahaza_locations.docs = [{"id": "L1", "code": "GD-1", "name": "Gudang 1"}]
    db.rahaza_material_stock.docs = [{"material_id": "FG1", "location_id": "L1", "qty": stok1},
                                     {"material_id": "FG2", "location_id": "L1", "qty": stok2}]
    db.rahaza_models.docs = [{"id": "M1", "code": "KAOS", "name": "Kaos", "active": True}]
    db.rahaza_sizes.docs = [{"id": "S-M", "code": "M", "active": True}]
    db.rahaza_model_variants.docs = [{"id": "V1", "model_id": "M1", "size_id": "S-M", "size_code": "M",
                                      "color_name": "Hitam", "color_code": "HTM", "sku": "KAOS-HTM-M",
                                      "active": True}]


@pytest.fixture
def env(monkeypatch):
    import core.doc_number_policy as dnp
    import routes.marketing_samples_routes as ms
    import routes.production_internal_adapter as pia
    import routes.production_pos as pp
    db = mu.DB()
    _seed(db)
    seq = itertools.count(1)

    async def number(_db, key, **_k):
        return f"{'PO-INT' if 'production_pos' in key else 'FGI'}-UJI-{next(seq):04d}"
    monkeypatch.setattr(dnp, "issue_number", number)
    monkeypatch.setattr(pp, "log_activity", _noop)
    monkeypatch.setattr(pia, "explode_po_accessories_from_bom", _noop)
    cur = {"user": dict(ADMIN)}

    async def _auth(req=None, *a, **k):
        if req is not None and getattr(req, "state", None) is not None:
            req.state.user = dict(cur["user"])
        return dict(cur["user"])
    monkeypatch.setattr(ms, "get_db", lambda: db)
    monkeypatch.setattr(ms, "require_auth", _auth)

    class E:
        pass
    e = E()
    e.db, e.ms, e.cur = db, ms, cur
    return e


def _req(user=ADMIN, body=None):
    return mu.Req(user=user, body=body)


def _buat(env, lines, ongkir=15000, account="A", creator="CR1", date="2026-11-10", **kw):
    body = env.ms.SampleIn(account_id=account, creator_id=creator, date=date, sample_type="live", courier="jnt",
                           ongkir=ongkir, lines=[env.ms.BarisIn(**ln) for ln in lines], **kw)
    return run(env.ms.create_sample(body, _req(env.cur["user"])))["data"]


# ══════════════════════════════════════════════════════════════════════════════
# K1 · banyak produk, satu ongkir; dokumen lama
# ══════════════════════════════════════════════════════════════════════════════
def test_kiriman_banyak_produk_satu_ongkir(env):
    d = _buat(env, [{"catalog_item_id": "CI1", "quantity": 2, "hpp": 1}, {"catalog_item_id": "CI2", "quantity": 1}])
    assert len(d["lines"]) == 2 and d["ongkir"] == 15000
    l1, l2 = d["lines"]
    assert l1["hpp"] == 50000 and l1["total_hpp"] == 100000, "HPP ikut katalog, bukan yang dikirim layar"
    assert l2["total_hpp"] == 70000 and d["total_hpp"] == 170000 and d["biaya_total"] == 185000
    assert {l1["status_gudang"], l2["status_gudang"]} == {"menunggu_gudang"}
    assert l1["fg_material_id"] == "FG1" and l1["size"] == "M" and l1["color"] == "Hitam"
    saved = env.db.marketing_samples.docs[0]
    assert saved["quantity"] == 3 and saved["total_hpp"] == 170000 and saved["catalog_item_id"] == ["CI1", "CI2"]
    assert not any(k in saved["lines"][0] for k in ("status_gudang", "qty_keluar", "sisa_keluar"))
    assert env.db.production_pos.docs == [], "stok cukup ⇒ tidak ada PO"


def test_produk_dobel_dan_katalog_toko_lain_ditolak(env):
    with pytest.raises(HTTPException) as e:
        _buat(env, [{"catalog_item_id": "CI1", "quantity": 1}, {"catalog_item_id": "CI1", "quantity": 2}])
    assert e.value.status_code == 400 and "dua kali" in e.value.detail
    with pytest.raises(HTTPException) as e:
        _buat(env, [{"catalog_item_id": "CIB", "quantity": 1}])
    assert e.value.status_code == 400 and "toko lain" in e.value.detail
    with pytest.raises(HTTPException) as e:      # kreator toko B tidak boleh di kiriman toko A
        _buat(env, [{"catalog_item_id": "CI1", "quantity": 1}], creator="CR2")
    assert e.value.status_code == 400


def test_dokumen_lama_dibaca_satu_baris_dan_bisa_diubah(env):
    env.db.marketing_samples.docs.append({
        "id": "OLD1", "date": "2026-11-05", "account_id": "A", "account_name": "Toko A", "creator_id": "CR1",
        "username": "@ayu", "sample_type": "video", "product": "Gamis Lama", "sku": "GML-1", "size": "L",
        "color": "Hitam", "quantity": 2, "hpp": 40000, "total_hpp": 80000, "ongkir": 10000, "courier": "jnt",
        "catalog_item_id": None, "shipment_status": "shipped", "progress": "open"})
    d = run(env.ms.get_sample("OLD1", _req()))["data"]
    assert len(d["lines"]) == 1 and d["lines"][0]["product"] == "Gamis Lama" and d["total_hpp"] == 80000
    assert d["lines"][0]["status_gudang"] is None and d["biaya_total"] == 90000
    lst = run(env.ms.list_samples(_req(), page=1, page_size=20, account_id="", creator_id="", shipment_status="",
                                  progress="", platform="", sample_type="", date_from="", date_to="", search="Gamis"))
    assert lst["data"][0]["lines"][0]["sku"] == "GML-1"
    # ubah catatan saja: baris lama dipertahankan apa adanya, kini tersimpan sebagai `lines`
    out = run(env.ms.update_sample("OLD1", env.ms.SampleUpdate(notes="cek"), _req()))["data"]
    saved = next(x for x in env.db.marketing_samples.docs if x["id"] == "OLD1")
    assert out["notes"] == "cek" and saved["lines"][0]["product"] == "Gamis Lama" and saved["total_hpp"] == 80000
    assert env.db.production_pos.docs == []


# ══════════════════════════════════════════════════════════════════════════════
# K2 · status maju-mundur
# ══════════════════════════════════════════════════════════════════════════════
def test_status_kirim_dan_tindak_lanjut_maju_mundur(env):
    d = _buat(env, [{"catalog_item_id": "CI1", "quantity": 1}])
    sid = d["id"]
    for st in ("shipped", "pending", "delivered", "shipped"):
        out = run(env.ms.set_status(sid, env.ms.StatusIn(shipment_status=st), _req()))["data"]
        assert out["shipment_status"] == st
    out = run(env.ms.set_status(sid, env.ms.StatusIn(progress="sold", sales_update="5 pcs"), _req()))["data"]
    assert out["progress"] == "sold" and out["sales_update"] == "5 pcs"
    out = run(env.ms.set_status(sid, env.ms.StatusIn(progress="open"), _req()))["data"]
    assert out["progress"] == "open" and out["tindak_lanjut_label"] == "Terbuka"
    saved = env.db.marketing_samples.docs[0]
    assert [r["ke"] for r in saved["riwayat_status"]] == ["shipped", "pending", "delivered", "shipped", "sold", "open"]
    with pytest.raises(HTTPException) as e:
        run(env.ms.set_status(sid, env.ms.StatusIn(shipment_status="hilang"), _req()))
    assert e.value.status_code == 400
    run(env.ms.deliver_sample(sid, _req()))          # pintu lama tetap jalan
    assert env.db.marketing_samples.docs[0]["shipment_status"] == "delivered"


# ══════════════════════════════════════════════════════════════════════════════
# K3 · gudang mengeluarkan lewat Keluarkan stok (alasan Sampel)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def fg(env, monkeypatch):
    import core.stock_service as ss
    import routes.rahaza_inventory_fg as fgm
    import routes.rahaza_posting as rp

    async def issue(material_id, location_id, qty, **_k):
        row = next(r for r in env.db.rahaza_material_stock.docs
                   if r["material_id"] == material_id and r["location_id"] == location_id)
        row["qty"] -= qty

    async def cogs(*_a, **_k):
        return {"ok": True, "je_number": "JE-UJI"}

    async def _auth(req=None, *a, **k):
        return dict(ADMIN)
    monkeypatch.setattr(ss, "issue", issue)
    monkeypatch.setattr(rp, "post_fg_issue_cogs", cogs)
    monkeypatch.setattr(fgm, "log_activity", _noop)
    monkeypatch.setattr(fgm, "get_db", lambda: env.db)
    monkeypatch.setattr(fgm, "require_auth", _auth)
    return fgm


def _keluar(fgm, items, reason="sample", bid=None):
    body = {"reason": reason, "items": items, "client_batch_id": bid or f"b-{len(items)}-{items[0]['qty']}-{reason}"}
    return run(fgm.create_fg_issue_batch(mu.Req(user=ADMIN, body=body)))


def test_keluar_gudang_tertaut_baris_dan_sisa(env, fg):
    d = _buat(env, [{"catalog_item_id": "CI1", "quantity": 3}])
    sid, lid = d["id"], d["lines"][0]["id"]
    q = run(fg.fg_issue_sample_queue(mu.Req(user=ADMIN), limit=300))["items"]
    assert [(r["sample_id"], r["line_id"], r["sisa"], r["stok_tersedia"]) for r in q] == [(sid, lid, 3, 5.0)]
    link = {"marketing_sample_id": sid, "sample_line_id": lid}
    with pytest.raises(HTTPException) as e:                         # alasan bukan Sampel
        _keluar(fg, [{"material_id": "FG1", "location_id": "L1", "qty": 1, **link}], reason="lainnya")
    assert "Sampel" in e.value.detail
    with pytest.raises(HTTPException) as e:                         # produk lain
        _keluar(fg, [{"material_id": "FG2", "location_id": "L1", "qty": 1, **link}])
    assert "produk berbeda" in e.value.detail
    with pytest.raises(HTTPException) as e:                         # melebihi sisa baris
        _keluar(fg, [{"material_id": "FG1", "location_id": "L1", "qty": 4, **link}])
    assert "sisa" in e.value.detail
    assert env.db.rahaza_fg_issues.docs == [], "galat ⇒ tidak ada yang dikeluarkan"

    out = _keluar(fg, [{"material_id": "FG1", "location_id": "L1", "qty": 2, **link}], bid="k1")
    assert out["ok"] and out["lines"][0]["marketing_sample_id"] == sid
    ln = run(env.ms.get_sample(sid, _req()))["data"]["lines"][0]
    assert ln["qty_keluar"] == 2 and ln["sisa_keluar"] == 1 and ln["status_gudang"] == "keluar_sebagian"
    assert ln["barang_keluar"][0]["issue_number"] == out["issue_number"]
    with pytest.raises(HTTPException):
        _keluar(fg, [{"material_id": "FG1", "location_id": "L1", "qty": 2, **link}], bid="k2")
    _keluar(fg, [{"material_id": "FG1", "location_id": "L1", "qty": 1, **link}], bid="k3")
    ln = run(env.ms.get_sample(sid, _req()))["data"]["lines"][0]
    assert ln["status_gudang"] == "sudah_keluar" and ln["status_gudang_label"] == "Sudah keluar gudang"
    assert run(fg.fg_issue_sample_queue(mu.Req(user=ADMIN), limit=300))["items"] == []
    # baris yang sudah keluar gudang terkunci: jumlah tidak bisa diubah, kiriman tidak bisa dihapus
    with pytest.raises(HTTPException) as e:
        run(env.ms.update_sample(sid, env.ms.SampleUpdate(
            lines=[env.ms.BarisIn(id=lid, catalog_item_id="CI1", quantity=5)]), _req()))
    assert "keluar gudang" in e.value.detail
    with pytest.raises(HTTPException):
        run(env.ms.delete_sample(sid, _req()))


def test_pengeluaran_tanpa_tautan_tidak_berubah(env, fg):
    out = _keluar(fg, [{"material_id": "FG1", "location_id": "L1", "qty": 1}], reason="lainnya", bid="polos")
    assert out["ok"] and "marketing_sample_id" not in out["lines"][0]


# ══════════════════════════════════════════════════════════════════════════════
# K4 · stok kurang ⇒ satu draf PO sampel_rnd
# ══════════════════════════════════════════════════════════════════════════════
def test_stok_kurang_satu_draf_po_sampel_rnd(env):
    env.db.rahaza_material_stock.docs[0]["qty"] = 1
    d = _buat(env, [{"catalog_item_id": "CI1", "quantity": 3}])
    ln = d["lines"][0]
    assert ln["qty_dari_stok"] == 1 and ln["qty_produksi"] == 2 and ln["status_gudang"] == "diproduksi"
    assert len(env.db.production_pos.docs) == 1
    po = env.db.production_pos.docs[0]
    assert po["label"] == "sampel_rnd" and po["status"] == "Draft" and po["business_type"] == "internal"
    assert po["sumber"] == {"jenis": "kirim_sampel", "id": d["id"], "nomor": d["sample_code"], "baris_id": ln["id"]}
    assert ln["po_number"] == po["po_number"] and ln["status_gudang_label"] == f"Diproduksi · {po['po_number']}"
    item = env.db.po_items.docs[0]
    assert item["qty"] == 2 and item["sku"] == "KAOS-HTM-M" and item["rahaza_variant_id"] == "V1"
    # rencana ulang baris yang sama (mis. klik ganda) tidak membuat PO kedua
    from core import kirim_sampel as ks
    saved = env.db.marketing_samples.docs[0]
    again = run(ks.rencanakan_baris(env.db, saved, saved["lines"][0], ADMIN))
    assert again["po_number"] == po["po_number"] and len(env.db.production_pos.docs) == 1
    # ubah catatan saja: tidak ada PO baru; ubah jumlah baris ber-PO ditolak
    run(env.ms.update_sample(d["id"], env.ms.SampleUpdate(notes="x"), _req()))
    assert len(env.db.production_pos.docs) == 1
    with pytest.raises(HTTPException) as e:
        run(env.ms.update_sample(d["id"], env.ms.SampleUpdate(
            lines=[env.ms.BarisIn(id=ln["id"], catalog_item_id="CI1", quantity=4)]), _req()))
    assert "draf PO sampel" in e.value.detail
    # baris baru yang ditambahkan saat diubah ikut direncanakan
    out = run(env.ms.update_sample(d["id"], env.ms.SampleUpdate(lines=[
        env.ms.BarisIn(id=ln["id"], catalog_item_id="CI1", quantity=3),
        env.ms.BarisIn(catalog_item_id="CI2", quantity=2)]), _req()))["data"]
    assert out["lines"][1]["status_gudang"] == "menunggu_gudang" and len(env.db.production_pos.docs) == 1


def test_stok_dipesan_kiriman_lain_ikut_dihitung(env):
    _buat(env, [{"catalog_item_id": "CI1", "quantity": 4}])          # 4 dari 5 pcs
    d2 = _buat(env, [{"catalog_item_id": "CI1", "quantity": 3}])     # sisa bebas 1 ⇒ PO 2 pcs
    assert d2["lines"][0]["qty_dari_stok"] == 1 and d2["lines"][0]["qty_produksi"] == 2
    assert env.db.po_items.docs[0]["qty"] == 2


def test_penomoran_manual_tidak_membuat_po(env):
    env.db.doc_number_configs.docs.append({"key": "production_pos.po_number", "mode": "manual"})
    env.db.rahaza_material_stock.docs[0]["qty"] = 0
    d = _buat(env, [{"catalog_item_id": "CI1", "quantity": 2}])
    ln = d["lines"][0]
    assert env.db.production_pos.docs == [] and ln["status_gudang"] == "perlu_po_manual"
    assert "PO sampel perlu dibuat manual oleh admin produksi" in ln["po_catatan"]


def test_varian_tidak_ada_di_master_jadi_catatan(env):
    env.db.rahaza_material_stock.docs[1]["qty"] = 0
    d = _buat(env, [{"catalog_item_id": "CI2", "quantity": 1}])      # ROK-NVY-L tidak ada di master varian
    assert env.db.production_pos.docs == [] and "Master Produk" in d["lines"][0]["po_catatan"]


# ── R&D Sample Request ─────────────────────────────────────────────────────────
@pytest.fixture
def rnd(env, monkeypatch):
    import routes.dewi_rnd_samples as smp
    monkeypatch.setattr(smp, "get_db", lambda: env.db)
    env.db.dewi_rnd_styles.docs = [{"id": "ST1", "style_code": "ST-1", "style_name": "Kaos baru",
                                    "promoted_to_model_id": "M1"},
                                   {"id": "ST2", "style_code": "ST-2", "style_name": "Gamis baru",
                                    "promoted_to_model_id": None}]
    return smp


def _sr(rnd, style, **kw):
    req = run(rnd.create_sample_request({"style_id": style, "quantity": 2, **kw}, user=ADMIN))
    run(rnd.submit_sample_request(req["id"], user=ADMIN))
    return req


def test_rnd_setujui_dengan_varian_membuat_po(env, rnd):
    opsi = run(rnd.sample_variant_options(style_id="ST1", user=ADMIN))
    assert opsi["model_id"] == "M1" and [v["sku"] for v in opsi["variants"]] == ["KAOS-HTM-M"]
    req = _sr(rnd, "ST1", rahaza_variant_id="V1")
    assert req["variant_sku"] == "KAOS-HTM-M"
    out = run(rnd.approve_sample_request(req["id"], {"notes": ""}, user=ADMIN))
    assert out["status"] == "approved" and out["po_number"]
    po = env.db.production_pos.docs[0]
    assert po["label"] == "sampel_rnd" and po["sumber"]["jenis"] == "sample_request" and po["sumber"]["id"] == req["id"]
    assert env.db.po_items.docs[0]["qty"] == 2
    again = run(rnd.create_sample_request_po(req["id"], {}, user=ADMIN))   # aman diulang
    assert again["po_id"] == po["id"] and len(env.db.production_pos.docs) == 1


def test_rnd_style_tanpa_model_catatan_lalu_buat_po(env, rnd):
    with pytest.raises(HTTPException):                                     # varian tanpa model ditolak
        run(rnd.create_sample_request({"style_id": "ST2", "rahaza_variant_id": "V1"}, user=ADMIN))
    req = _sr(rnd, "ST2")
    out = run(rnd.approve_sample_request(req["id"], {}, user=ADMIN))
    assert out["status"] == "approved" and not out.get("po_id") and env.db.production_pos.docs == []
    assert out["po_sampel_catatan"] == rnd.CATATAN_TANPA_MODEL and out["po_sampel_bisa_buat"] is False
    with pytest.raises(HTTPException) as e:
        run(rnd.create_sample_request_po(req["id"], {"rahaza_variant_id": "V1"}, user=ADMIN))
    assert "belum dijadikan model" in e.value.detail
    # style kemudian dijadikan model ⇒ catatan berubah dan PO bisa dibuat (sekali)
    env.db.dewi_rnd_styles.docs[1]["promoted_to_model_id"] = "M1"
    got = run(rnd.get_sample_request(req["id"], user=ADMIN))
    assert got["po_sampel_bisa_buat"] is True
    po1 = run(rnd.create_sample_request_po(req["id"], {"rahaza_variant_id": "V1"}, user=ADMIN))
    po2 = run(rnd.create_sample_request_po(req["id"], {"rahaza_variant_id": "V1"}, user=ADMIN))
    assert po1["po_id"] == po2["po_id"] and len(env.db.production_pos.docs) == 1


# ══════════════════════════════════════════════════════════════════════════════
# K5 · anggaran sampel otomatis
# ══════════════════════════════════════════════════════════════════════════════
def test_anggaran_sampel_otomatis_per_periode(env):
    from core import marketing_cycle as mc
    assert "sample" in mc.AUTO_CATEGORIES
    _buat(env, [{"catalog_item_id": "CI1", "quantity": 2}, {"catalog_item_id": "CI2", "quantity": 1}],
          ongkir=15000, date="2026-11-10")                                   # 170.000 + 15.000
    env.db.marketing_samples.docs.append({"id": "LAMA", "account_id": "A", "date": "2026-11-12", "total_hpp": 40000,
                                          "ongkir": 5000, "product": "x", "quantity": 1})   # dokumen lama ikut
    env.db.marketing_samples.docs.append({"id": "BATAL", "account_id": "A", "date": "2026-11-12", "total_hpp": 9e6,
                                          "ongkir": 0, "shipment_status": "cancelled"})
    env.db.marketing_samples.docs.append({"id": "LUAR", "account_id": "A", "date": "2026-12-01", "total_hpp": 9e6,
                                          "ongkir": 0})
    env.db.marketing_samples.docs.append({"id": "TOKOB", "account_id": "B", "date": "2026-11-12", "total_hpp": 9e6,
                                          "ongkir": 0})
    smp = run(mc._auto_sample(env.db, "A", "2026-11"))                     # bulan Marketing 26 Okt – 25 Nov
    assert smp["amount"] == 230000 and smp["docs"] == 2 and smp["breakdown"] == {"hpp": 210000, "ongkir": 20000}
    assert "2 kiriman sampel" in smp["evidence"]
    week = run(mc._auto_sample(env.db, "A", "2026-11-09", 7))             # 9–15 Nov
    assert week["amount"] == 230000
    assert run(mc._auto_sample(env.db, "A", "2026-11-13", 7))["amount"] == 0
    by_cat, sources = run(mc.auto_spend(env.db, "A", "2026-11", {}))
    assert by_cat["sample"] == 230000
    src = next(s for s in sources if s["category"] == "sample")
    assert src["source"] == "auto" and src["basis"] == "kirim_sample"


# ══════════════════════════════════════════════════════════════════════════════
# K6 · lingkup toko
# ══════════════════════════════════════════════════════════════════════════════
def test_kiriman_toko_lain_404(env):
    d_b = _buat(env, [{"catalog_item_id": "CIB", "quantity": 1}], account="B", creator="CR2")
    d_a = _buat(env, [{"catalog_item_id": "CI1", "quantity": 1}])
    env.cur["user"] = dict(PIC_A)
    req = _req(PIC_A)
    calls = [
        lambda: env.ms.get_sample(d_b["id"], req),
        lambda: env.ms.update_sample(d_b["id"], env.ms.SampleUpdate(notes="x"), req),
        lambda: env.ms.set_status(d_b["id"], env.ms.StatusIn(shipment_status="shipped"), req),
        lambda: env.ms.ship_sample(d_b["id"], req),
        lambda: env.ms.delete_sample(d_b["id"], req),
    ]
    for c in calls:
        with pytest.raises(HTTPException) as e:
            run(c())
        assert e.value.status_code == 404
    assert run(env.ms.get_sample(d_a["id"], req))["data"]["account_id"] == "A"
    # pindah kiriman sendiri ke toko yang tidak dipegang = ditolak
    with pytest.raises(HTTPException) as e:
        run(env.ms.update_sample(d_a["id"], env.ms.SampleUpdate(account_id="B"), req))
    assert e.value.status_code == 403
