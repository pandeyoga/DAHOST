"""Status produk per varian SKU (keputusan owner 6 Nov 2026) — `rahaza_model_variants.product_status`.

Kontrak tetap (diisi juga oleh skrip data): new · best_seller · slow · dead · stop; kosong = belum diisi.
  1. Validasi: kode & label diterima, kosong = None, nilai lain → 400 berbahasa Indonesia.
  2. Penyaring daftar varian (`product_status=`), termasuk `belum_diisi`.
  3. Ringkasan status model (dihitung saat dibaca): sama semua → status itu, berbeda → campuran.
  4. Impor Excel master (HARGA_JUAL_SKU · VARIAN_BARU): kolom `status_produk`, label atau kode.
  5. Stop: varian TIDAK dinonaktifkan; tidak diusulkan di daftar "perlu restock" (alasannya disebut).

Semua data SINTETIS (model/SKU karangan).
"""
import asyncio
import copy
import io
import os
import pathlib
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

from _fake_mongo import FakeCollection, FakeCursor, FakeDB, FakeRequest, match  # noqa: E402
from core import product_status as ps  # noqa: E402
from core import gap_sisa, gap_workbook  # noqa: E402
import routes.rahaza_variants as rv  # noqa: E402
import routes.rahaza_production as rprod  # noqa: E402

USER = {"id": "u-uji", "name": "Staf Uji", "role": "admin"}


def run(c):
    return asyncio.run(c)


async def _user(*_a, **_k):
    return dict(USER)


async def _noop(*_a, **_k):
    return None


def _variant(vid, model_id, sku, status=None, active=True, **kw):
    d = {"id": vid, "model_id": model_id, "model_code": sku.split("-")[0], "sku": sku,
         "color_code": sku.split("-")[1], "size_code": sku.split("-")[2], "active": active, **kw}
    if status is not None:
        d["product_status"] = status
    return d


def _db():
    db = FakeDB()
    db.rahaza_models.docs = [
        {"id": "m-a", "code": "UJA", "name": "Model Uji A", "active": True},
        {"id": "m-b", "code": "UJB", "name": "Model Uji B", "active": True},
        {"id": "m-c", "code": "UJC", "name": "Model Uji C", "active": True},
    ]
    db.rahaza_sizes.docs = [{"id": "s-m", "code": "M", "active": True}]
    db.rahaza_colors.docs = [{"id": "c-ht", "code": "HTM", "name": "Hitam", "hex": "#111111", "active": True}]
    db.rahaza_model_variants.docs = [
        _variant("v1", "m-a", "UJA-HTM-S", "best_seller"),
        _variant("v2", "m-a", "UJA-HTM-M", "best_seller"),
        _variant("v3", "m-a", "UJA-HTM-L"),                       # belum diisi → tidak dihitung "berbeda"
        _variant("v4", "m-b", "UJB-HTM-S", "best_seller"),
        _variant("v5", "m-b", "UJB-HTM-M", "slow"),
        _variant("v6", "m-b", "UJB-HTM-L", "slow"),
        _variant("v7", "m-b", "UJB-HTM-XL", "stop"),
        _variant("v8", "m-b", "UJB-HTM-XXL", "dead", active=False),  # nonaktif → tidak dihitung
    ]
    return db


@pytest.fixture
def db(monkeypatch):
    d = _db()
    for mod in (rv, rprod):
        monkeypatch.setattr(mod, "get_db", lambda: d)
        monkeypatch.setattr(mod, "require_auth", _user)
    monkeypatch.setattr(rv, "log_activity", _noop)
    monkeypatch.setattr(rv, "ensure_fg_material", _noop)

    async def _panel(*_a, **_k):
        return {"code": "CUT-UJI"}, False
    monkeypatch.setattr(rv, "ensure_panel_for_variant", _panel)
    monkeypatch.setattr(rv, "ensure_bom_for_variant", _noop)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# 1 · Validasi
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("raw,code", [
    ("new", "new"), ("Baru", "new"), ("best_seller", "best_seller"), ("Best Seller", "best_seller"),
    ("BEST SELLER", "best_seller"), ("best-seller", "best_seller"), (" slow ", "slow"), ("Dead", "dead"),
    ("STOP", "stop"), ("", None), ("   ", None), (None, None),
])
def test_parse_menerima_kode_dan_label(raw, code):
    assert ps.parse(raw) == code


@pytest.mark.parametrize("raw", ["Laris", "aktif", "best", 5])
def test_parse_menolak_nilai_lain(raw):
    with pytest.raises(ps.ProductStatusError) as e:
        ps.parse(raw)
    assert "Pilihan: Baru, Best Seller, Slow, Dead, Stop" in str(e.value)


def test_ubah_varian_status_valid_kosong_dan_tidak_dikenal(db):
    out = run(rv.update_variant("v3", FakeRequest({"product_status": "Best Seller"})))
    assert out["product_status"] == "best_seller"
    out = run(rv.update_variant("v3", FakeRequest({"product_status": ""})))
    assert out["product_status"] is None                     # kosong = belum diisi
    with pytest.raises(HTTPException) as e:
        run(rv.update_variant("v3", FakeRequest({"product_status": "laris manis"})))
    assert e.value.status_code == 400
    assert "tidak dikenal" in e.value.detail and "Best Seller" in e.value.detail
    # nilai lama tidak berubah setelah ditolak
    assert next(v for v in db.rahaza_model_variants.docs if v["id"] == "v3")["product_status"] is None


def test_stop_tidak_menonaktifkan_varian(db):
    out = run(rv.update_variant("v1", FakeRequest({"product_status": "stop"})))
    assert out["product_status"] == "stop" and out["active"] is True


def test_ubah_tanpa_field_status_tidak_menyentuh_status(db):
    out = run(rv.update_variant("v1", FakeRequest({"notes": "catatan uji"})))
    assert out["product_status"] == "best_seller" and out["notes"] == "catatan uji"


def test_buat_varian_menyimpan_dan_memvalidasi_status(db):
    body = {"model_id": "m-c", "size_id": "s-m", "color_id": "c-ht", "product_status": "Baru"}
    out = run(rv.create_variant(FakeRequest(body)))
    assert out["sku"] == "UJC-HTM-M" and out["product_status"] == "new"
    with pytest.raises(HTTPException) as e:
        run(rv.create_variant(FakeRequest({**body, "product_status": "hot"})))
    assert e.value.status_code == 400
    # tanpa status → tersimpan null (belum diisi), bukan ditolak
    db.rahaza_model_variants.docs = [v for v in db.rahaza_model_variants.docs if v["model_id"] != "m-c"]
    out = run(rv.create_variant(FakeRequest({k: v for k, v in body.items() if k != "product_status"})))
    assert out["product_status"] is None


def test_generate_varian_membawa_status(db):
    out = run(rv.generate_variants("m-c", FakeRequest({"color_ids": ["c-ht"], "size_ids": ["s-m"],
                                                       "product_status": "new"})))
    assert out["created_count"] == 1
    v = next(v for v in db.rahaza_model_variants.docs if v["sku"] == "UJC-HTM-M")
    assert v["product_status"] == "new"
    with pytest.raises(HTTPException):
        run(rv.generate_variants("m-c", FakeRequest({"color_ids": ["c-ht"], "product_status": "x"})))


# ══════════════════════════════════════════════════════════════════════════════
# 2 · Penyaring daftar varian
# ══════════════════════════════════════════════════════════════════════════════
def test_filter_query_bentuk():
    assert ps.filter_query(None) == {} and ps.filter_query("") == {}
    assert ps.filter_query("stop") == {"product_status": {"$in": ["stop"]}}
    assert ps.filter_query("Best Seller,dead") == {"product_status": {"$in": ["best_seller", "dead"]}}
    assert ps.filter_query("belum_diisi") == {"product_status": {"$in": [None, ""]}}
    with pytest.raises(ps.ProductStatusError):
        ps.filter_query("laris")


def test_daftar_varian_disaring_status(db):
    rows = run(rv.list_variants(FakeRequest(), product_status="slow"))
    assert sorted(r["sku"] for r in rows) == ["UJB-HTM-L", "UJB-HTM-M"]
    rows = run(rv.list_variants(FakeRequest(), product_status="belum_diisi"))
    assert [r["sku"] for r in rows] == ["UJA-HTM-L"] and rows[0]["product_status"] is None
    # tanpa penyaring: semua aktif, field selalu ada di setiap baris
    rows = run(rv.list_variants(FakeRequest()))
    assert len(rows) == 7 and all("product_status" in r for r in rows)
    # varian nonaktif ikut bila diminta
    rows = run(rv.list_variants(FakeRequest(), include_inactive=True, product_status="dead"))
    assert [r["sku"] for r in rows] == ["UJB-HTM-XXL"]
    with pytest.raises(HTTPException) as e:
        run(rv.list_variants(FakeRequest(), product_status="laris"))
    assert e.value.status_code == 400 and "tidak dikenal" in e.value.detail


def test_daftar_varian_per_model_disaring_dan_berringkasan(db):
    out = run(rv.list_model_variants("m-b", FakeRequest(), product_status="stop"))
    assert [v["sku"] for v in out["variants"]] == ["UJB-HTM-XL"] and out["count"] == 1
    # ringkasan model memakai SEMUA varian aktif, bukan hanya hasil saringan
    s = out["model"]["product_status_summary"]
    assert s["code"] == "campuran" and s["dominant"] == "slow"
    assert s["counts"] == {"best_seller": 1, "slow": 2, "stop": 1} and s["total"] == 4


# ══════════════════════════════════════════════════════════════════════════════
# 3 · Ringkasan status model
# ══════════════════════════════════════════════════════════════════════════════
def test_summarize_aturan():
    same = ps.summarize(["best_seller", "best_seller", None])
    assert same["code"] == "best_seller" and same["label"] == "Best Seller" and same["unset"] == 1
    mixed = ps.summarize(["slow", "dead", "slow"])
    assert mixed["code"] == "campuran" and mixed["label"] == "Campuran" and mixed["dominant"] == "slow"
    tie = ps.summarize(["stop", "new"])                      # seri → urutan kode (new lebih dulu)
    assert tie["code"] == "campuran" and tie["dominant"] == "new"
    empty = ps.summarize([None, ""])
    assert empty["code"] is None and empty["label"] == "Belum diisi" and empty["total"] == 2
    assert ps.summarize([])["code"] is None


def test_daftar_model_membawa_ringkasan_saat_dibaca(db):
    rows = {r["id"]: r for r in run(rprod.list_models(FakeRequest()))}
    assert rows["m-a"]["product_status_summary"]["code"] == "best_seller"
    assert rows["m-b"]["product_status_summary"]["code"] == "campuran"
    assert rows["m-c"]["product_status_summary"]["code"] is None         # belum punya varian
    # skrip data menulis langsung ke varian → ringkasan ikut berubah tanpa penyegar
    for v in db.rahaza_model_variants.docs:
        if v["model_id"] == "m-b" and v["active"]:
            v["product_status"] = "dead"
    rows = {r["id"]: r for r in run(rprod.list_models(FakeRequest()))}
    assert rows["m-b"]["product_status_summary"]["code"] == "dead"


# ══════════════════════════════════════════════════════════════════════════════
# 4 · Impor Excel master (kolom status_produk)
# ══════════════════════════════════════════════════════════════════════════════
def _wb(sheets: dict) -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, (head, rows) in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(head)
        for r in rows:
            ws.append(r)
    return openpyxl.load_workbook(io.BytesIO(_bytes(wb)))


def _bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _price_row(sku, status):
    r = [None] * len(gap_workbook.SKU_PRICE_COLS)
    r[0] = sku
    r[gap_workbook.SKU_PRICE_COLS.index("status_produk")] = status
    return r


def test_kolom_status_produk_di_paling_kanan():
    # posisi kolom lama tidak bergeser (berkas klien lama tetap terbaca)
    assert gap_workbook.SKU_PRICE_COLS[:8] == ["sku", "nama", "kode_model", "warna", "ukuran",
                                               "harga_saran_dari_saudara", "harga_jual", "keterangan"]
    assert gap_workbook.SKU_PRICE_COLS[-1] == "status_produk"
    assert gap_sisa.VARIAN_BARU_COLS[:9][-1] == "ukuran_tersedia" and gap_sisa.VARIAN_BARU_COLS[-1] == "status_produk"


def test_impor_harga_jual_sku_status_label_dan_kode():
    db = _db()
    db.rahaza_materials.docs = [{"id": "fg-1", "type": "fg", "code": "UJA-HTM-L", "active": True}]
    wb = _wb({"HARGA_JUAL_SKU": (gap_workbook.SKU_PRICE_COLS, [
        _price_row("UJA-HTM-L", "Best Seller"),   # label
        _price_row("UJA-HTM-S", "stop"),          # kode
        _price_row("UJA-HTM-M", "best_seller"),   # sudah sama → idempoten, tidak dicatat
        _price_row("UJB-HTM-S", None),            # kosong → status tidak diubah
        _price_row("UJB-HTM-M", "Laris"),         # tidak dikenal → galat
        _price_row("TIDAK-ADA-SKU", "Slow"),      # SKU tidak ada → galat
    ])})
    errors: list = []
    out = run(gap_workbook.parse_extra_sheets(db, wb, errors))
    got = {s["sku"]: s["product_status"] for s in out["sku_status"]}
    assert got == {"UJA-HTM-L": "best_seller", "UJA-HTM-S": "stop"}
    assert any("baris 6" in e and "Laris" in e and "tidak dikenal" in e for e in errors)
    assert any("baris 7" in e and "TIDAK-ADA-SKU" in e for e in errors)
    # diterapkan → field tersimpan, varian Stop TETAP aktif
    res = run(gap_workbook.apply_extra(db, out, USER))
    assert res["sku_status_updated"] == 2
    vs = {v["sku"]: v for v in db.rahaza_model_variants.docs}
    assert vs["UJA-HTM-L"]["product_status"] == "best_seller"
    assert vs["UJA-HTM-S"]["product_status"] == "stop" and vs["UJA-HTM-S"]["active"] is True
    assert vs["UJB-HTM-S"]["product_status"] == "best_seller"   # baris kosong tidak mengubah


def test_impor_berkas_lama_tanpa_kolom_status_tetap_terbaca():
    db = _db()
    db.rahaza_materials.docs = [{"id": "fg-1", "type": "fg", "code": "UJA-HTM-L", "active": True, "retail_price_master": 0}]
    old_cols = gap_workbook.SKU_PRICE_COLS[:8]
    wb = _wb({"HARGA_JUAL_SKU": (old_cols, [["UJA-HTM-L", "", "", "", "", None, 150000, ""]])})
    errors: list = []
    out = run(gap_workbook.parse_extra_sheets(db, wb, errors))
    assert errors == [] and out["sku_status"] == []
    assert out["sku_prices"] == [{"sku": "UJA-HTM-L", "id": "fg-1", "harga": 150000.0}]


def test_impor_varian_baru_membawa_status(monkeypatch):
    db = _db()
    cols = gap_sisa.VARIAN_BARU_COLS

    def row(model, size, status):
        r = [None] * len(cols)
        r[0], r[3], r[4], r[cols.index("status_produk")] = model, "HTM", size, status
        return r
    wb = _wb({
        "VARIAN_BARU": (cols, [row("UJC", "M", "Baru"), row("UJC", "S", "aneh")]),
        "HARGA_JUAL_SKU": (gap_workbook.SKU_PRICE_COLS, []),
    })
    db.rahaza_sizes.docs.append({"id": "s-s", "code": "S", "active": True})
    errors: list = []
    out = run(gap_workbook.parse_extra_sheets(db, wb, errors))
    assert [(n["sku"], n["product_status"]) for n in out["new_variants"]] == [("UJC-HTM-M", "new")]
    assert any("VARIAN_BARU baris 3" in e and "aneh" in e for e in errors)

    async def _fg(*_a, **_k):
        return None
    import utils.variant_ssot as vssot
    monkeypatch.setattr(vssot, "ensure_fg_material", _fg)
    run(gap_workbook.apply_new_variants(db, out["new_variants"], USER))
    v = next(v for v in db.rahaza_model_variants.docs if v["sku"] == "UJC-HTM-M")
    assert v["product_status"] == "new" and v["active"] is True


def test_status_di_harga_jual_untuk_sku_baru_di_unggahan_yang_sama():
    db = _db()
    cols = gap_sisa.VARIAN_BARU_COLS
    r = [None] * len(cols)
    r[0], r[3], r[4] = "UJC", "HTM", "M"
    wb = _wb({"VARIAN_BARU": (cols, [r]),
              "HARGA_JUAL_SKU": (gap_workbook.SKU_PRICE_COLS, [_price_row("UJC-HTM-M", "Dead")])})
    errors: list = []
    out = run(gap_workbook.parse_extra_sheets(db, wb, errors))
    assert errors == [] and out["sku_status"] == []
    assert out["new_variants"][0]["product_status"] == "dead"


def test_ekspor_harga_jual_sku_berisi_label_status():
    db = _db()
    db.rahaza_materials.docs = [
        {"id": "fg-1", "type": "fg", "code": "UJB-HTM-XL", "name": "Model Uji B Hitam XL", "model_code": "UJB", "active": True},
        {"id": "fg-2", "type": "fg", "code": "UJA-HTM-L", "name": "Model Uji A Hitam L", "model_code": "UJA", "active": True},
    ]
    data, _stats = run(gap_workbook.build_gap_workbook(db))
    ws = openpyxl.load_workbook(io.BytesIO(data))["HARGA_JUAL_SKU"]
    head = [c.value for c in ws[1]]
    assert head == gap_workbook.SKU_PRICE_COLS
    i = head.index("status_produk")
    got = {r[0]: r[i] for r in ws.iter_rows(min_row=2, values_only=True) if r[0]}
    assert got == {"UJB-HTM-XL": "Stop", "UJA-HTM-L": None}      # label, bukan kode; kosong = belum diisi


# ══════════════════════════════════════════════════════════════════════════════
# 5 · Stop tidak diusulkan restock (daftar "Item perlu restock" katalog)
# ══════════════════════════════════════════════════════════════════════════════
class _AggCollection(FakeCollection):
    def aggregate(self, pipeline):
        docs = [copy.deepcopy(d) for d in self.docs]
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if match(d, stage["$match"])]
            elif "$group" in stage:
                spec, groups = stage["$group"], {}
                for d in docs:
                    key = {k: d[v[1:]] for k, v in spec["_id"].items() if v[1:] in d}
                    g = groups.setdefault(repr(sorted(key.items())), {"_id": key, "n": 0})
                    g["n"] += 1
                docs = list(groups.values())
        return FakeCursor(docs)


class _AggDB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _AggCollection(name)
        return self._cols[name]


def _import_catalog_mgmt():
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


def test_restock_melewati_sku_stop_dan_menyebut_alasan(monkeypatch):
    cm = _import_catalog_mgmt()
    db = _AggDB()
    db.marketing_catalogs.docs = [{"id": "cat-u", "account_id": "acc-u", "platform": "shopee", "is_active": True}]
    db.marketing_platform_accounts.docs = [{"id": "acc-u", "account_code": "UJI", "platform": "shopee", "status": "active"}]
    db.rahaza_materials.docs = [
        {"id": "fg-s", "type": "fg", "code": "UJB-HTM-XL"},   # varian Stop, stok 0
        {"id": "fg-b", "type": "fg", "code": "UJB-HTM-S"},    # varian Best Seller, stok 0
    ]
    db.rahaza_model_variants.docs = [_variant("v4", "m-b", "UJB-HTM-S", "best_seller"),
                                     _variant("v7", "m-b", "UJB-HTM-XL", "stop")]
    db.marketing_catalog_items.docs = [
        {"id": "i-s", "catalog_id": "cat-u", "fg_material_id": "fg-s", "is_active": True, "name": "Item stop", "sku": "S1"},
        {"id": "i-b", "catalog_id": "cat-u", "fg_material_id": "fg-b", "is_active": True, "name": "Item laris", "sku": "B1"},
    ]
    admin = {"id": "u-adm", "name": "Admin", "role": "superadmin"}

    async def _admin(_req):
        return dict(admin)
    monkeypatch.setattr(cm, "require_auth", _admin)
    monkeypatch.setattr(cm, "get_db", lambda: db)
    req = FakeRequest()
    req.state.user = admin
    out = run(cm.stock_dashboard(req, account_id=None, platform=None))
    assert [i["name"] for i in out["low_stock_items"]] == ["Item laris"]
    ex = out["restock_excluded"]
    assert ex["count"] == 1 and ex["skus"] == ["UJB-HTM-XL"] and "Stop" in ex["reason"]
    # angka stok tetap jujur: item Stop tetap dihitung habis
    assert out["summary"]["out_of_stock"] == 2
