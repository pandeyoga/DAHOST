"""Ganti nama / kode produk tanpa produk kembar (laporan R&D 13 Nov 2026, owner: "dibenarkan") — hermetik (FakeDB).

Laporan: di Portal RnD › Style & Desain, ganti nama produk "tidak berubah" dan ganti kode produk/SKU "malah menambah
produk baru (dobel)". Akar: `core.master_sync` mencari style R&D lewat KODE dan menimpa nama dari master.

Yang dikunci:
  1. sinkron master mencocokkan style lewat TAUTAN dulu — ganti nama/kode (di master, di R&D, data lama, promosi
     dengan kode lain) tidak pernah membuat style kedua; isi style mengikuti master;
  2. ubah style yang sudah jadi produk = ubah Master Produk lewat jalur resmi (`ubah_model`) → tidak dibalik sinkron;
  3. ganti kode produk ikut mengganti SKU varian, kode barang jadi & potongan, baris BOM, SKU varian R&D (tertaut id,
     kode lama jadi alias); DITOLAK 409 bila SKU sudah dipakai / kode baru bentrok — tidak ada yang tertulis;
  4. ganti nama menyegarkan nama turunan bentukan otomatis saja;
  5. skrip rapikan style kembar: pratinjau tidak menulis, gabung + arsip, idempoten, sinkron sesudahnya tidak dobel;
  6. pengaman tambahan: impor VARIAN_BARU tidak membuat varian kembar, scanner membaca SKU lama, audit SKU R&D ikut master.
"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402

ADMIN = {"id": "u-adm", "name": "Admin Uji", "role": "admin"}
RND = {"id": "u-rnd", "name": "Staf R&D", "role": "rnd_staff"}


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


def _db():
    db = fm.FakeDB()
    db.rahaza_models.docs = [{"id": "m1", "code": "DA-2101", "name": "Mela Dress", "active": True,
                              "category_name": "Dress", "category": "Dress", "rnd_style_id": "st1",
                              "rnd_style_code": "DA-2101", "created_at": "2026-11-01"},
                             {"id": "m2", "code": "DA-3000", "name": "Produk Lain", "active": True}]
    db.rahaza_sizes.docs = [{"id": "s1", "code": "M", "order_seq": 2}, {"id": "s2", "code": "L", "order_seq": 3}]
    db.rahaza_colors.docs = [{"id": "w1", "code": "MRN", "name": "Maroon", "hex": "#7F1D1D"}]
    var = lambda vid, sid, sc: {"id": vid, "model_id": "m1", "model_code": "DA-2101", "model_name": "Mela Dress",  # noqa: E731
                                "size_id": sid, "size_code": sc, "color_id": "w1", "color_code": "MRN",
                                "color_name": "Maroon", "sku": f"DA-2101-MRN-{sc}", "active": True}
    db.rahaza_model_variants.docs = [var("v1", "s1", "M"), var("v2", "s2", "L"),
                                     {"id": "v9", "model_id": "m2", "size_id": "s1", "size_code": "M",
                                      "color_code": "MRN", "sku": "DA-3000-MRN-M", "active": True}]
    fg = lambda fid, vid, sc: {"id": fid, "type": "fg", "code": f"DA-2101-MRN-{sc}", "sku": f"DA-2101-MRN-{sc}",  # noqa: E731
                               "model_id": "m1", "variant_id": vid, "model_code": "DA-2101", "model_name": "Mela Dress",
                               "color_name": "Maroon", "color_code": "MRN", "size_code": sc, "category_id": "c1",
                               "name": f"Mela Dress [Maroon · {sc}]", "active": True}
    db.rahaza_materials.docs = [
        fg("f1", "v1", "M"), fg("f2", "v2", "L"),
        {"id": "p1", "type": "fabric", "is_cut_panel": True, "code": "CUT-DA-2101-MRN-M", "model_id": "m1",
         "model_code": "DA-2101", "style_sku": "DA-2101", "color_code": "MRN", "color": "Maroon", "size_code": "M",
         "name": "Potongan Mela Dress · Maroon · M", "style_name": "Mela Dress", "active": True},
        {"id": "f9", "type": "fg", "code": "DA-3000-MRN-M", "model_id": "m2", "variant_id": "v9", "active": True},
    ]
    db.rahaza_boms.docs = [
        {"id": "b1", "model_id": "m1", "size_id": "s1", "color_code": "MRN", "active": True,
         "materials": [{"material_id": "p1", "code": "CUT-DA-2101-MRN-M", "is_cut_panel": True},
                       {"material_id": "acc1", "code": "KNC-01"}]},
        {"id": "b2", "model_id": "m1", "size_id": "s2", "color_code": "MRN", "active": True,
         "materials": [{"material_id": "acc1", "code": "KNC-01"}]},
    ]
    db.dewi_rnd_styles.docs = [{"id": "st1", "style_code": "DA-2101", "style_name": "Mela Dress", "status": "promoted",
                                "promoted_to_model_id": "m1", "master_sync": True, "category": "Dress",
                                "created_at": "2026-11-01"},
                               {"id": "st9", "style_code": "DA-3000", "style_name": "Produk Lain", "status": "promoted",
                                "promoted_to_model_id": "m2", "master_sync": True, "created_at": "2026-10-01"}]
    db.dewi_rnd_variants.docs = [{"id": "rv1", "style_id": "st1", "style_code": "DA-2101", "style_name": "Mela Dress",
                                  "color_code": "MRN", "color": "Maroon",
                                  "sizes": [{"size": "M", "sku": "DA-2101-MRN-M", "variant_id": "v1"},
                                            {"size": "L", "sku": "DA-2101-MRN-L", "variant_id": "v2"}]}]
    return db


async def _sinkron(db):
    from core import master_sync as ms
    rep = {}
    by_key, bom_keys = await ms._sync_variants(db, rep, None)
    await ms._sync_rnd_styles(db, rep, by_key, bom_keys, None)
    return rep


def _styles_m1(db):
    return [s for s in db.dewi_rnd_styles.docs if s.get("promoted_to_model_id") == "m1" and not s.get("merged_into_style_id")]


def _snapshot(db):
    import copy
    return {n: copy.deepcopy(c.docs) for n, c in db._cols.items() if c.docs}


@pytest.fixture
def env(monkeypatch):
    import routes.dewi_rnd_styles as st
    import routes.rahaza_production as rp
    db = _db()
    monkeypatch.setattr(st, "get_db", lambda: db)
    monkeypatch.setattr(st, "log_activity", _noop)
    monkeypatch.setattr(rp, "log_activity", _noop)
    return st, rp, db


# ══════════════════════════════ 1 · sinkron master: tautan dulu ══════════════════════════════
def test_sinkron_idempoten_tanpa_style_baru(env):
    _st, _rp, db = env
    rep = run(_sinkron(db))
    assert rep["rnd"]["styles_created"] == 0 and len(db.dewi_rnd_styles.docs) == 2
    assert len(db.dewi_rnd_variants.docs) == 2       # rv1 + varian R&D baru untuk m2 (warna MRN)
    rep = run(_sinkron(db))
    assert rep["rnd"]["styles_created"] == 0 and rep["rnd"]["rnd_variants_created"] == 0


def test_sinkron_nama_ikut_master(env):
    _st, _rp, db = env
    db.rahaza_models.docs[0]["name"] = "Mela Dress Premium"
    run(_sinkron(db))
    assert [s["style_name"] for s in _styles_m1(db)] == ["Mela Dress Premium"]
    assert db.dewi_rnd_variants.docs[0]["style_name"] == "Mela Dress Premium"


def test_sinkron_data_lama_kode_master_diganti_tanpa_style_kembar(env):
    """Keadaan sebelum perbaikan: kode model diganti langsung (Master Produk lama) — sinkron dulu membuat style baru."""
    _st, _rp, db = env
    db.rahaza_models.docs[0]["code"] = "DA-2102"
    rep = run(_sinkron(db))
    assert rep["rnd"]["styles_created"] == 0 and rep["rnd"]["styles_code_fixed"] == 1
    assert [(s["id"], s["style_code"]) for s in _styles_m1(db)] == [("st1", "DA-2102")]
    assert len(db.dewi_rnd_styles.docs) == 2
    assert db.rahaza_models.docs[0]["rnd_style_code"] == "DA-2102"
    assert [v["style_code"] for v in db.dewi_rnd_variants.docs if v["style_id"] == "st1"] == ["DA-2102"]


def test_sinkron_data_lama_kode_style_diganti_r_and_d_tanpa_kembar(env):
    """Keadaan sebelum perbaikan: kode style diubah di R&D — sinkron dulu membuat style KEDUA berkode master."""
    _st, _rp, db = env
    db.dewi_rnd_styles.docs[0]["style_code"] = "DA-2101X"
    db.dewi_rnd_styles.docs[0]["style_name"] = "Nama R&D"
    run(_sinkron(db))
    assert [(s["id"], s["style_code"], s["style_name"]) for s in _styles_m1(db)] == [("st1", "DA-2101", "Mela Dress")]
    assert len(db.dewi_rnd_styles.docs) == 2


def test_sinkron_tanpa_rnd_style_id_tetap_lewat_promoted_to(env):
    _st, _rp, db = env
    db.rahaza_models.docs[0].pop("rnd_style_id")
    db.rahaza_models.docs[0]["code"] = "DA-2109"
    run(_sinkron(db))
    assert [(s["id"], s["style_code"]) for s in _styles_m1(db)] == [("st1", "DA-2109")]
    assert len(db.dewi_rnd_styles.docs) == 2 and db.rahaza_models.docs[0]["rnd_style_id"] == "st1"


def test_sinkron_kode_dipegang_style_lain_dilaporkan_bukan_dobel(env):
    _st, _rp, db = env
    db.rahaza_models.docs[0]["code"] = "RND-DRAF"
    db.dewi_rnd_styles.docs.append({"id": "draf", "style_code": "RND-DRAF", "style_name": "Draf R&D lain",
                                    "status": "draft", "promoted_to_model_id": "m-lain-hidup"})
    db.rahaza_models.docs.append({"id": "m-lain-hidup", "code": "ZZ-1", "name": "Z", "active": False})
    rep = run(_sinkron(db))
    assert any("RND-DRAF" in k for k in rep["rnd"]["konflik"])
    assert {s["id"] for s in db.dewi_rnd_styles.docs if s.get("promoted_to_model_id") == "m1"} == {"st1"}
    assert len(db.dewi_rnd_styles.docs) == 3       # st1 + st9 + draf — tidak ada kembaran m1


def test_sinkron_model_baru_tetap_dapat_style(env):
    _st, _rp, db = env
    db.dewi_rnd_styles.docs = [s for s in db.dewi_rnd_styles.docs if s["id"] != "st9"]
    rep = run(_sinkron(db))
    st_m2 = [s for s in db.dewi_rnd_styles.docs if s.get("promoted_to_model_id") == "m2"]
    assert len(st_m2) == 1 and st_m2[0]["style_code"] == "DA-3000" and rep["rnd"]["styles_created"] == 1
    run(_sinkron(db))
    assert len([s for s in db.dewi_rnd_styles.docs if s.get("promoted_to_model_id") == "m2"]) == 1


def test_pilih_style_utama_murni():
    from core.ganti_kode_produk import pilih_style_utama
    m = {"id": "m1", "code": "A", "rnd_style_id": "x"}
    a = {"id": "a", "style_code": "A", "promoted_to_model_id": "m1", "created_at": "2026-11-02"}
    b = {"id": "b", "style_code": "B", "promoted_to_model_id": "m1", "created_at": "2026-11-01"}
    x = {"id": "x", "style_code": "X", "promoted_to_model_id": "m9"}         # tertaut model lain → bukan
    assert pilih_style_utama(m, [a, b, x])["id"] == "a"                       # kode sama didahulukan
    assert pilih_style_utama({**m, "rnd_style_id": "b"}, [a, b])["id"] == "b"  # tautan model didahulukan
    assert pilih_style_utama(m, [{**a, "merged_into_style_id": "b"}, b])["id"] == "b"
    assert pilih_style_utama(m, [x]) is None


# ══════════════════════════════ 2 · ganti kode di Master Produk ══════════════════════════════
def test_master_ganti_kode_ikut_ganti_sku_tanpa_dobel(env):
    _st, rp, db = env
    db.rahaza_material_stock.docs = [{"id": "sk1", "material_id": "f1", "material_code": "DA-2101-MRN-M", "qty": 0}]
    out = run(rp.ubah_model(db, "m1", {"code": "da-2102"}, ADMIN))
    assert db.rahaza_material_stock.docs[0]["material_code"] == "DA-2102-MRN-M"   # baris stok bersaldo 0 ikut
    assert out["code"] == "DA-2102"
    assert out["kode_diganti"] == {"kode_lama": "DA-2101", "kode_baru": "DA-2102", "varian": 2, "barang_jadi": 2,
                                   "potongan": 1, "bom": 1, "varian_rnd": 1}
    v = {x["id"]: x for x in db.rahaza_model_variants.docs}
    assert v["v1"]["sku"] == "DA-2102-MRN-M" and v["v1"]["model_code"] == "DA-2102"
    assert v["v1"]["sku_aliases"] == ["DA-2101-MRN-M"] and v["v9"]["sku"] == "DA-3000-MRN-M"
    mat = {x["id"]: x for x in db.rahaza_materials.docs}
    assert mat["f1"]["code"] == mat["f1"]["sku"] == "DA-2102-MRN-M" and mat["f1"]["code_aliases"] == ["DA-2101-MRN-M"]
    assert mat["p1"]["code"] == "CUT-DA-2102-MRN-M" and mat["p1"]["model_code"] == "DA-2102"
    assert db.rahaza_boms.docs[0]["materials"][0]["code"] == "CUT-DA-2102-MRN-M"
    assert db.rahaza_boms.docs[0]["materials"][1]["code"] == "KNC-01"
    assert [r["sku"] for r in db.dewi_rnd_variants.docs[0]["sizes"]] == ["DA-2102-MRN-M", "DA-2102-MRN-L"]
    assert [(s["id"], s["style_code"]) for s in _styles_m1(db)] == [("st1", "DA-2102")]
    n_var, n_mat = len(db.rahaza_model_variants.docs), len(db.rahaza_materials.docs)
    rep = run(_sinkron(db))
    assert rep["rnd"]["styles_created"] == 0
    assert [s["id"] for s in _styles_m1(db)] == ["st1"] and len(db.dewi_rnd_styles.docs) == 2
    assert len(db.rahaza_model_variants.docs) == n_var and len(db.rahaza_materials.docs) == n_mat


def test_master_ganti_kode_ditolak_bila_sku_sudah_dipakai(env):
    _st, rp, db = env
    db.rahaza_stock_ledger.docs = [{"id": "l1", "material_id": "f1", "qty": 5}]
    db.marketing_catalog_items.docs = [{"id": "c1", "fg_material_id": "f2", "sku": "DA-2101-MRN-L"}]
    sebelum = _snapshot(db)
    with pytest.raises(HTTPException) as e:
        run(rp.ubah_model(db, "m1", {"code": "DA-2102", "name": "Nama Baru"}, ADMIN))
    assert e.value.status_code == 409
    assert "kartu stok" in e.value.detail and "item katalog marketing" in e.value.detail
    assert "owner" in e.value.detail
    assert _snapshot(db) == sebelum                               # tidak ada yang tertulis (nama juga tidak)


@pytest.mark.parametrize("koleksi,doc", [
    ("po_items", {"id": "x", "sku": "DA-2101-MRN-M"}),
    ("cutting_orders", {"id": "x", "model_id": "m1"}),
    ("marketing_sku_bridge", {"id": "x", "variant_id": "v2"}),
    ("marketing_orders", {"id": "x", "items": [{"variant_id": "v1"}]}),
])
def test_master_ganti_kode_ditolak_untuk_tiap_pemakaian(env, koleksi, doc):
    _st, rp, db = env
    getattr(db, koleksi).docs.append(doc)
    with pytest.raises(HTTPException) as e:
        run(rp.ubah_model(db, "m1", {"code": "DA-2102"}, ADMIN))
    assert e.value.status_code == 409 and db.rahaza_models.docs[0]["code"] == "DA-2101"


def test_master_ganti_kode_ditolak_bila_sku_baru_bentrok(env):
    _st, rp, db = env
    db.rahaza_model_variants.docs.append({"id": "vx", "model_id": "mx", "sku": "DA-2102-MRN-M", "active": False})
    with pytest.raises(HTTPException) as e:
        run(rp.ubah_model(db, "m1", {"code": "DA-2102"}, ADMIN))
    assert e.value.status_code == 409 and "DA-2102-MRN-M" in e.value.detail
    assert db.rahaza_models.docs[0]["code"] == "DA-2101"


def test_master_ganti_kode_ditolak_bila_kode_dipegang_style_lain(env):
    _st, rp, db = env
    db.dewi_rnd_styles.docs.append({"id": "lain", "style_code": "DA-2102", "style_name": "Style draf"})
    with pytest.raises(HTTPException) as e:
        run(rp.ubah_model(db, "m1", {"code": "DA-2102"}, ADMIN))
    assert e.value.status_code == 409 and "style R&D lain" in e.value.detail


def test_master_ubah_tanpa_ganti_kode_tetap_seperti_dulu(env):
    _st, rp, db = env
    out = run(rp.ubah_model(db, "m1", {"code": "DA-2101", "retail_price": 150000}, ADMIN))
    assert out["kode_diganti"] is None and out["retail_price"] == 150000
    assert db.rahaza_model_variants.docs[0]["sku"] == "DA-2101-MRN-M"


# ══════════════════════════════ 3 · ganti nama ══════════════════════════════
def test_master_ganti_nama_segarkan_nama_turunan_otomatis_saja(env):
    _st, rp, db = env
    db.rahaza_materials.docs[1]["name"] = "Nama Ketikan Gudang"
    db.rahaza_material_stock.docs = [{"id": "sk1", "material_id": "f1", "material_name": "Mela Dress [Maroon · M]", "qty": 7}]
    out = run(rp.ubah_model(db, "m1", {"name": "Mela Dress Premium"}, ADMIN))   # ganti NAMA tetap boleh walau ada stok
    assert db.rahaza_material_stock.docs[0]["material_name"] == "Mela Dress Premium [Maroon · M]"
    assert out["nama_disegarkan"]["varian"] == 2
    mat = {x["id"]: x for x in db.rahaza_materials.docs}
    assert mat["f1"]["name"] == "Mela Dress Premium [Maroon · M]" and mat["f1"]["model_name"] == "Mela Dress Premium"
    assert mat["f2"]["name"] == "Nama Ketikan Gudang"             # nama khusus tidak disentuh
    assert mat["p1"]["name"] == "Potongan Mela Dress Premium · Maroon · M"
    assert db.dewi_rnd_styles.docs[0]["style_name"] == "Mela Dress Premium"


def test_nama_turunan_awalan_impor_excel():
    from core.ganti_kode_produk import nama_baru_turunan
    assert nama_baru_turunan("Mela Dress MAROON M", "x", "y", "Mela Dress", "Mela") == "Mela MAROON M"
    assert nama_baru_turunan("Gamis Mela", "x", "y", "Mela Dress", "Mela") is None
    assert nama_baru_turunan("Mela Dress [M]", "Mela Dress [M]", "Mela [M]", "Mela Dress", "Mela") == "Mela [M]"


# ══════════════════════════════ 4 · ubah di Style & Desain R&D ══════════════════════════════
def test_rnd_ganti_nama_style_produk_tidak_dibalik_sinkron(env):
    st, _rp, db = env
    out = run(st.update_style("st1", {"style_name": "Mela Dress Baru", "status": "promoted"}, user=RND))
    assert out["style_name"] == "Mela Dress Baru" and out["master_produk"]["diubah"] == ["name"]
    assert db.rahaza_models.docs[0]["name"] == "Mela Dress Baru"
    run(_sinkron(db))
    assert [s["style_name"] for s in _styles_m1(db)] == ["Mela Dress Baru"]


def test_rnd_ganti_kode_style_produk_tanpa_dobel(env):
    st, _rp, db = env
    out = run(st.update_style("st1", {"style_code": "da-2102", "style_name": "Mela Dress"}, user=RND))
    assert out["style_code"] == "DA-2102" and out["master_produk"]["kode_diganti"]["varian"] == 2
    assert db.rahaza_models.docs[0]["code"] == "DA-2102"
    assert db.rahaza_model_variants.docs[0]["sku"] == "DA-2102-MRN-M"
    assert any(r.get("revision_name", "").startswith("Ubah Kode Style") for r in db.dewi_rnd_revisions.docs)
    run(_sinkron(db))
    assert [(s["id"], s["style_code"]) for s in _styles_m1(db)] == [("st1", "DA-2102")]


def test_rnd_ganti_kode_ditolak_bila_sku_dipakai_tanpa_menulis(env):
    st, _rp, db = env
    db.po_items.docs = [{"id": "x", "rahaza_variant_id": "v1"}]
    with pytest.raises(HTTPException) as e:
        run(st.update_style("st1", {"style_code": "DA-2102"}, user=RND))
    assert e.value.status_code == 409 and "baris PO produksi" in e.value.detail
    assert db.dewi_rnd_styles.docs[0]["style_code"] == "DA-2101" and db.rahaza_models.docs[0]["code"] == "DA-2101"


def test_rnd_kirim_isian_sama_tidak_menyentuh_master(env):
    st, rp, db = env
    async def _jangan(*_a, **_k):
        raise AssertionError("master tidak boleh diubah")
    import pytest as _pt
    with _pt.MonkeyPatch.context() as mp:
        mp.setattr(rp, "ubah_model", _jangan)
        out = run(st.update_style("st1", {"style_code": "DA-2101", "style_name": "Mela Dress", "category": "Dress",
                                          "season": "Lebaran"}, user=RND))
    assert out["season"] == "Lebaran" and "master_produk" not in out


def test_rnd_peran_eksternal_tidak_bisa_mengubah_master(env):
    st, _rp, db = env
    with pytest.raises(HTTPException) as e:
        run(st.update_style("st1", {"style_name": "X"}, user={"id": "v", "role": "vendor"}))
    assert e.value.status_code == 403 and db.rahaza_models.docs[0]["name"] == "Mela Dress"


def test_rnd_style_kembar_tidak_bisa_mengubah_master(env):
    st, _rp, db = env
    db.dewi_rnd_styles.docs.append({"id": "st2", "style_code": "DA-2101X", "style_name": "Kembar",
                                    "promoted_to_model_id": "m1", "status": "promoted", "created_at": "2026-11-05"})
    with pytest.raises(HTTPException) as e:
        run(st.update_style("st2", {"style_name": "Ubah dari kembaran"}, user=RND))
    assert e.value.status_code == 409 and "DA-2101" in e.value.detail
    assert db.rahaza_models.docs[0]["name"] == "Mela Dress"


@pytest.mark.parametrize("kode,pesan", [("DA-4000", "Master Produk"), ("DA-2101", "style lain")])
def test_rnd_style_belum_produk_tidak_boleh_pakai_kode_produk_atau_style_lain(env, kode, pesan):
    st, _rp, db = env
    db.rahaza_models.docs.append({"id": "m4", "code": "DA-4000", "name": "Produk tanpa style", "active": True})
    db.dewi_rnd_styles.docs.append({"id": "draf", "style_code": "RND-01", "style_name": "Draf", "status": "draft"})
    with pytest.raises(HTTPException) as e:
        run(st.update_style("draf", {"style_code": kode}, user=RND))
    assert e.value.status_code == 409 and pesan in e.value.detail
    with pytest.raises(HTTPException) as e2:
        run(st.create_style({"style_code": kode, "style_name": "Baru"}, user=RND))
    assert e2.value.status_code == 409


def test_promosi_dengan_kode_lain_tidak_membuat_style_kedua(env):
    st, _rp, db = env
    db.dewi_rnd_styles.docs.append({"id": "st5", "style_code": "RND-05", "style_name": "Tunik Uji", "status": "approved_for_launch",
                                    "rnd_type": "internal_product", "promoted_to_model_id": None, "design_images": [],
                                    "category": "", "created_at": "2026-11-10"})
    out = run(st.promote_style_to_production("st5", {"model_code": "DA-5000"}, user=ADMIN))
    assert out["model_code"] == "DA-5000"
    s5 = next(s for s in db.dewi_rnd_styles.docs if s["id"] == "st5")
    assert s5["style_code"] == "DA-5000"
    run(_sinkron(db))
    mid = out["model_id"]
    assert [s["id"] for s in db.dewi_rnd_styles.docs if s.get("promoted_to_model_id") == mid] == ["st5"]


# ══════════════════════════════ 5 · skrip rapikan style kembar ══════════════════════════════
def _mig():
    p = BACKEND / "scripts" / "migrations" / "2026_11_13_rapikan_style_rnd_dobel.py"
    spec = importlib.util.spec_from_file_location("mig_style_dobel", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _db_dobel():
    """Hasil bug lama: R&D mengganti kode st1 → DA-2101X; sinkron membuat st2 berkode master + varian R&D kedua."""
    db = _db()
    db.dewi_rnd_styles.docs[0].update({"style_code": "DA-2101X", "style_name": "Mela R&D", "design_images": ["a.jpg"]})
    db.dewi_rnd_styles.docs.append({"id": "st2", "style_code": "DA-2101", "style_name": "Mela Dress", "status": "promoted",
                                    "promoted_to_model_id": "m1", "master_sync": True, "design_images": ["b.jpg"],
                                    "created_at": "2026-11-05"})
    db.rahaza_models.docs[0]["rnd_style_id"] = "st2"
    db.dewi_rnd_variants.docs.append({"id": "rv2", "style_id": "st2", "style_code": "DA-2101", "color_code": "MRN",
                                      "sizes": [{"size": "M", "sku": "DA-2101-MRN-M", "variant_id": "v1"}]})
    db.dewi_rnd_variants.docs.append({"id": "rv3", "style_id": "st2", "style_code": "DA-2101", "color_code": "HTM",
                                      "sizes": []})
    db.dewi_rnd_tech_packs.docs = [{"id": "tp1", "style_id": "st1", "is_latest": True}]
    db.dewi_rnd_hpp.docs = [{"id": "h1", "style_id": "st1"}]
    db.dewi_rnd_sample_requests.docs = [{"id": "sr2", "style_id": "st2"}]
    return db


def test_migrasi_pratinjau_tidak_menulis(tmp_path):
    mig, db = _mig(), _db_dobel()
    sebelum = _snapshot(db)
    out = run(mig.run(db, False, str(tmp_path)))
    g = out["rencana"]["gabung"]
    assert len(g) == 1 and g[0]["tetap"]["id"] == "st1" and [k["id"] for k in g[0]["kembar"]] == ["st2"]
    assert g[0]["kembar"][0]["kode_arsip"] == "DA-2101-DOBEL" and g[0]["kode_pernah_diketik"] == ["DA-2101X"]
    assert _snapshot(db) == sebelum and not list(tmp_path.iterdir())


def test_migrasi_gabung_arsip_idempoten_lalu_sinkron_tanpa_dobel(tmp_path):
    mig, db = _mig(), _db_dobel()
    out = run(mig.run(db, True, str(tmp_path)))
    assert out["cadangan"] and Path(out["cadangan"]).exists()
    s = {x["id"]: x for x in db.dewi_rnd_styles.docs}
    assert s["st1"]["style_code"] == "DA-2101" and s["st1"]["style_name"] == "Mela Dress"
    assert s["st1"]["design_images"] == ["a.jpg", "b.jpg"]
    assert s["st2"]["status"] == "archived" and s["st2"]["merged_into_style_id"] == "st1"
    assert s["st2"]["promoted_to_model_id"] is None and s["st2"]["style_code"] == "DA-2101-DOBEL"
    assert db.rahaza_models.docs[0]["rnd_style_id"] == "st1"
    rv = {x["id"]: x for x in db.dewi_rnd_variants.docs}
    assert rv["rv2"]["status"] == "archived" and rv["rv2"]["style_id"] == "st2"     # warna sudah ada di st1
    assert rv["rv3"]["style_id"] == "st1" and rv["rv3"]["style_code"] == "DA-2101"    # warna baru dipindah
    assert db.dewi_rnd_sample_requests.docs[0]["style_id"] == "st1"
    assert db.dewi_rnd_tech_packs.docs[0]["style_id"] == "st1"
    # idempoten
    out2 = run(mig.run(db, True, str(tmp_path)))
    assert out2["rencana"]["gabung"] == [] and out2["hasil"] is None
    # sinkron sesudahnya: tidak membuat style baru untuk m1 dan tidak mengambil kembaran yang diarsip
    run(_sinkron(db))
    assert [x["id"] for x in _styles_m1(db)] == ["st1"]
    assert next(x for x in db.dewi_rnd_styles.docs if x["id"] == "st2")["promoted_to_model_id"] is None


def test_migrasi_db_wajib_sama(monkeypatch):
    mig = _mig()

    class A:
        db, apply, cadangan = "db-lain", False, "."
    assert run(mig.main(A())) == 2


def test_migrasi_tunggal_beda_kode_disamakan(tmp_path):
    mig, db = _mig(), _db()
    db.dewi_rnd_styles.docs[0]["style_code"] = "DA-2101X"
    out = run(mig.run(db, True, str(tmp_path)))
    assert out["rencana"]["samakan_kode"][0]["ke"] == "DA-2101"
    assert db.dewi_rnd_styles.docs[0]["style_code"] == "DA-2101"
    assert db.dewi_rnd_variants.docs[0]["style_code"] == "DA-2101"


def test_migrasi_laporkan_sku_tidak_berawalan_kode(tmp_path):
    mig, db = _mig(), _db()
    db.rahaza_models.docs[0]["code"] = "DA-2109"
    out = run(mig.run(db, False, str(tmp_path)))
    assert {x["sku"] for x in out["rencana"]["sku_tidak_berawalan_kode"]} == {"DA-2101-MRN-M", "DA-2101-MRN-L"}


# ══════════════════════════════ 6 · pengaman tambahan ══════════════════════════════
def test_impor_varian_baru_tidak_membuat_kembar_warna_ukuran_sama():
    import openpyxl
    from core import gap_sisa
    from core import gap_workbook as gw
    db = _db()
    db.rahaza_models.docs[0]["code"] = "DA-2109"     # kode pernah diganti tanpa SKU (data lama)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "VARIAN_BARU"
    ws.append(gap_sisa.VARIAN_BARU_COLS)
    ws.append(["DA-2109", "Mela Dress", "Maroon", "MRN", "M", 0])
    out = run(gw.parse_extra_sheets(db, wb, []))
    assert out["new_variants"] == []
    assert any("sudah ada dengan SKU DA-2101-MRN-M" in w for w in out["warnings"])


def test_scanner_membaca_sku_lama_sesudah_ganti_kode(env):
    from core import scan_resolver as sr
    _st, rp, db = env
    run(rp.ubah_model(db, "m1", {"code": "DA-2102"}, ADMIN))
    hit = run(sr.resolve_fg(db, "da-2101-mrn-m"))
    assert hit and hit["kode"] == "DA-2102-MRN-M" and hit["via"] == "kode_lama"


def test_audit_sku_rnd_ikut_master(env, monkeypatch):
    import routes.dewi_rnd_colors as rc
    _st, _rp, db = env
    monkeypatch.setattr(rc, "get_db", lambda: db)
    db.dewi_rnd_styles.docs[0]["style_code"] = "LAIN"
    db.dewi_rnd_variants.docs[0]["style_code"] = "LAIN"
    out = run(rc.variants_sku_audit(style_id="st1", limit=50, user=RND))
    assert out["drift_rows"] == 0                    # baris tertaut master = benar bila sama dengan SKU master
    res = run(rc.fix_variant_sku("rv1", user=RND))
    assert res["changed_count"] == 0
    assert [r["sku"] for r in db.dewi_rnd_variants.docs[0]["sizes"]] == ["DA-2101-MRN-M", "DA-2101-MRN-L"]
