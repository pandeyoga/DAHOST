"""Tahap 2 · paket marketing (6 Nov 2026) — impor Seller Center + kartu stok katalog.

Semua baris di sini SINTETIS (meniru bentuk kolom ekspor, bukan isi berkas pelanggan).

Impor Seller Center:
  · Order.all: "Harga Setelah Diskon" = harga SATUAN (bukan subtotal), "Subtotal Pesanan" = subtotal
    setelah diskon, "Total Diskon" = diskon per BARIS; status "Telah Dikirim" dan "Pesanan diterima,
    namun … hingga <tgl>" = diterima pembeli; waktu bayar "-" = kosong.
  · Statistik Toko: rincian per hari juga diawali "Tanggal" (versi baru).
  · Penghasilan "sudah dilepas": sheet "Penghasilan", 3 baris kepala, baris Order saja.
  · Wizard: arti NILAI bisa dipilih; berkas yang ditolak penormal tetap sampai ke pemetaan.
Kartu stok katalog: tanpa batas 500, isi katalog yang terlihat (lingkup PIC), status stok LIVE.
"""
import asyncio
import copy
import csv
import importlib.util
import io
import os
import pathlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import openpyxl  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from starlette.datastructures import UploadFile  # noqa: E402

from _fake_mongo import FakeCollection, FakeCursor, FakeDB, FakeRequest, match  # noqa: E402
from core import marketing_import_engine as eng  # noqa: E402
from core import marketing_import_prenorm as prenorm  # noqa: E402
from core import settlement_import as si  # noqa: E402
from core.marketing_import_schema import (  # noqa: E402
    get_source_type, is_retired_mapping, source_type_catalog,
)
import routes.marketing_data_import as md  # noqa: E402
import routes.marketing_settlements as ms  # noqa: E402

MO = get_source_type("marketplace_orders")
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)

# ── Order.all sintetis (nama kolom seperti ekspor Shopee; isinya karangan) ────
ORDER_HEADERS = [
    "No. Pesanan", "Status Pesanan", "Waktu Pesanan Dibuat", "Waktu Pembayaran Dilakukan",
    "Nama Produk", "Nama Variasi", "Harga Awal", "Harga Setelah Diskon", "Jumlah",
    "Subtotal Pesanan", "Total Diskon", "Diskon Dari Penjual", "Diskon Dari Shopee",
    "Voucher Ditanggung Penjual", "Total Pembayaran",
]
ORDER_ROWS = [
    # pesanan A: dua baris SKU, qty 2 + 1
    ["UJI-A", "Telah Dikirim", "2026-10-01 10:00", "2026-10-01 10:05", "Kaos Uji", "M",
     "100.000", "80.000", "2", "160.000", "40.000", "40.000", "0", "5.000", "170.000"],
    ["UJI-A", "Telah Dikirim", "2026-10-01 10:00", "2026-10-01 10:05", "Celana Uji", "L",
     "50.000", "45.000", "1", "45.000", "5.000", "5.000", "0", "5.000", "170.000"],
    # pesanan B: status bertanggal
    ["UJI-B", "Pesanan diterima, namun Pembeli masih dapat mengajukan pengembalian hingga 2026-10-12.",
     "2026-10-02 09:00", "2026-10-02 09:01", "Kaos Uji", "S",
     "100.000", "100.000", "3", "300.000", "0", "0", "0", "0", "310.000"],
    # pesanan C: batal sebelum dibayar — waktu bayar "-"
    ["UJI-C", "Batal", "2026-10-03 08:00", "-", "Kaos Uji", "M",
     "100.000", "90.000", "1", "90.000", "10.000", "10.000", "0", "0", "0"],
]


def _csv(headers, rows, delim=","):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delim)
    w.writerow(headers)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def _order_table(rows=None):
    raw = _csv(ORDER_HEADERS, rows or ORDER_ROWS)
    return eng.parse_table(raw, "Order.all.uji.csv", MO)


def _build(rows=None, mapping=None):
    headers, table = _order_table(rows)
    mapping = mapping or eng.auto_map(headers, MO)
    return headers, table, mapping, eng.build_rows(table, mapping, MO)


def _by_order(built):
    return {b["data"]["order_id"]: b for b in built}


# ═══ 1. Order.all → marketplace_orders ═══════════════════════════════════════
def test_kamus_kolom_harga_satuan_dan_subtotal_benar():
    m = {x["column"]: x["field"] for x in eng.auto_map(ORDER_HEADERS, MO)}
    assert m["Harga Setelah Diskon"] == "sku_unit_deal_price"
    # 2026-11-09 (riset G5) — "Subtotal Pesanan" = subtotal PLATFORM (sesudah semua diskon);
    # dasar omzet (`sku_subtotal_after_discount`) diturunkan mesin: sebelum − diskon penjual.
    assert m["Subtotal Pesanan"] == "sku_subtotal_after_all_discount"
    assert m["Harga Awal"] == "sku_unit_original_price"
    assert m["Total Diskon"] == "total_discount"
    assert "total_discount" in MO.item_fields and "total_discount" not in MO.per_order_money


def test_status_telah_dikirim_dan_diterima_bertanggal_jadi_delivered():
    _, _, _, built = _build()
    o = _by_order(built)
    assert all(b["status"] != "error" for b in built), [b["errors"] for b in built]
    assert o["UJI-A"]["data"]["status"] == "delivered"
    assert o["UJI-B"]["data"]["status"] == "delivered"
    assert o["UJI-B"]["data"]["status_raw"].startswith("Pesanan diterima")
    assert o["UJI-C"]["data"]["status"] == "cancelled"


def test_waktu_bayar_strip_berarti_kosong():
    assert eng.parse_date("-") == (None, None)
    _, _, _, built = _build()
    c = _by_order(built)["UJI-C"]
    assert c["status"] != "error" and "paid_at" not in c["data"]


def test_status_tak_dikenal_tetap_ditolak_dengan_petunjuk_pemetaan_nilai():
    rows = copy.deepcopy(ORDER_ROWS[:1])
    rows[0][1] = "Status Karangan"
    _, _, _, built = _build(rows)
    assert built[0]["status"] == "error"
    assert "Arti nilai di berkas" in " ".join(built[0]["errors"])


def _finish(built_row, account=None):
    doc, warn = md._finish(MO, built_row["data"], {"account_id": "acc-1"}, {}, account=account)
    return doc


def test_omzet_pesanan_dari_subtotal_baris_bukan_harga_satuan():
    _, _, _, built = _build()
    a = _finish(_by_order(built)["UJI-A"])
    # 80.000 × 2 + 45.000 × 1 = 205.000 (dulu 80.000 + 45.000 = 125.000)
    assert a["revenue_product"] == 205000 and a["revenue"] == 205000
    assert a["revenue_gross"] == 100000 * 2 + 50000      # Harga Awal × Jumlah
    assert a["total_discount"] == 45000                   # 40.000 + 5.000 (per baris, dijumlah)
    assert [it["total_discount"] for it in a["items"]] == [40000, 5000]
    assert a["seller_discount_total"] == 45000
    # Shopee tidak punya "Order Amount": total bayar diambil dari "Total Pembayaran"
    assert a["total_payment"] == 170000


def test_subtotal_dihitung_dari_harga_satuan_bila_kolom_subtotal_tidak_ada():
    headers, table = _order_table()
    mapping = [dict(m, field=None) if m["column"] == "Subtotal Pesanan" else m
               for m in eng.auto_map(headers, MO)]
    built = eng.build_rows(table, mapping, MO)
    a = _finish(_by_order(built)["UJI-A"])
    assert a["revenue_product"] == 205000


def test_pilihan_arti_nilai_staf_dipakai_dan_dilaporkan():
    rows = copy.deepcopy(ORDER_ROWS)
    rows[3][1] = "Status Karangan 7"
    headers, table, mapping, built = _build(rows)
    assert _by_order(built)["UJI-C"]["status"] == "error"
    vr = {v["field"]: v for v in eng.value_report(table, mapping, MO)}["status"]
    unknown = [v for v in vr["values"] if v["auto"] is None]
    assert vr["unknown"] == 1 and unknown[0]["count"] == 1
    assert {c["value"] for c in vr["choices"]} >= {"delivered", "cancelled"}
    assert all(c["label"] and "_" not in c["label"] for c in vr["choices"])   # tanpa kode program
    # staf memilih: nilai itu = Dibatalkan (kunci menyamakan angka: "status_karangan_0")
    key = eng.value_key("Status Karangan 9")
    assert key == unknown[0]["key"]
    mapping2 = [dict(m, value_map={key: "cancelled"}) if m["field"] == "status" else m for m in mapping]
    built2 = eng.build_rows(table, mapping2, MO)
    c = _by_order(built2)["UJI-C"]
    assert c["status"] != "error" and c["data"]["status"] == "cancelled"
    assert c["data"]["status_raw"] == "Status Karangan 7"
    vr2 = {v["field"]: v for v in eng.value_report(table, mapping2, MO)}["status"]
    assert vr2["unknown"] == 0
    # status bertanggal: satu kunci untuk semua variasi tanggal
    assert eng.value_key("hingga 2026-10-12.") == eng.value_key("hingga 2026-10-19.")


def test_pilihan_arti_di_luar_daftar_diabaikan_mesin():
    f = MO.field("status")
    val, err, _ = eng.coerce(f, "Status Karangan", {eng.value_key("Status Karangan"): "terbang"})
    assert val is None and err


def test_pemetaan_lama_yang_salah_ditandai_pensiun():
    assert is_retired_mapping("marketplace_orders", "harga setelah diskon", "sku_subtotal_after_discount")
    assert is_retired_mapping("marketplace_orders", "subtotal pesanan", "sku_subtotal_before_discount")
    assert not is_retired_mapping("marketplace_orders", "subtotal pesanan", "sku_subtotal_after_all_discount")


# ── upload / update_mapping lewat route (fake DB, penyimpanan berkas palsu) ──
def _patch_route(monkeypatch, db, raw_by_path, user=None):
    user = user or {"id": "u-spv", "email": "spv@uji", "role": "spv_marketing"}

    async def _auth(_req):
        return user

    async def _ctx(_db, st, account_id, ctx):
        return {"account": {"id": "acc-1", "account_name": "Toko Uji", "account_code": "UJI-01",
                            "platform": "shopee"}}

    async def _same(_db, _st, _s, built):
        return built

    async def _nodup(*_a, **_k):
        return {}

    def _put(path, raw, _ct):
        raw_by_path[path] = raw

    monkeypatch.setattr(md, "require_auth", _auth)
    monkeypatch.setattr(md, "get_db", lambda: db)
    monkeypatch.setattr(md, "_validate_context", _ctx)
    monkeypatch.setattr(md, "_annotate_master_links", _same)
    monkeypatch.setattr(md, "_annotate_existing", _nodup)
    monkeypatch.setattr(md, "_put_object", _put)
    monkeypatch.setattr(md, "_read_session_file", lambda p: raw_by_path.get(p))
    req = FakeRequest()
    req.state.user = user
    return req


def _upload(md_mod, req, raw, fname, source_type):
    f = UploadFile(file=io.BytesIO(raw), filename=fname)
    return asyncio.run(md_mod.upload(req, file=f, source_type=source_type, account_id="acc-1",
                                     host_id=None, creator_id=None, catalog_id=None,
                                     live_session_id=None))


def test_ingatan_pemetaan_yang_salah_tidak_dipasang_lagi(monkeypatch):
    db = FakeDB()
    headers = eng.parse_table(_csv(ORDER_HEADERS, ORDER_ROWS), "x.csv", MO)[0]
    old = [dict(m) for m in eng.auto_map(headers, MO)]
    for m in old:   # ingatan dari kamus LAMA
        if m["column"] == "Harga Setelah Diskon":
            m["field"] = "sku_subtotal_after_discount"
        if m["column"] == "Subtotal Pesanan":
            m["field"] = "sku_subtotal_before_discount"
    db.marketing_data_import_formats.docs.append({
        "source_type": "marketplace_orders", "fingerprint": eng.format_fingerprint(headers),
        "headers": headers, "mapping": old, "use_count": 3, "created_at": T0})
    req = _patch_route(monkeypatch, db, {})
    res = _upload(md, req, _csv(ORDER_HEADERS, ORDER_ROWS), "Order.all.csv", "marketplace_orders")
    got = {m["column"]: m["field"] for m in res["session"]["mapping"]}
    assert got["Harga Setelah Diskon"] == "sku_unit_deal_price"
    assert got["Subtotal Pesanan"] == "sku_subtotal_after_all_discount"     # riset G5 (9 Nov)
    dropped = res["session"]["format_memory"]["dropped"]
    assert {d["column"] for d in dropped} == {"Harga Setelah Diskon", "Subtotal Pesanan"}
    assert all("kamus kolom diperbaiki" in d["reason"] for d in dropped)
    assert res["summary"]["error"] == 0
    assert any(v["field"] == "status" for v in res["value_report"])


def test_update_mapping_menyimpan_arti_nilai_dan_menolak_pilihan_asing(monkeypatch):
    db = FakeDB()
    store: dict = {}
    req = _patch_route(monkeypatch, db, store)
    rows = copy.deepcopy(ORDER_ROWS)
    rows[3][1] = "Status Karangan"
    res = _upload(md, req, _csv(ORDER_HEADERS, rows), "Order.all.csv", "marketplace_orders")
    sid = res["session"]["id"]
    assert res["summary"]["error"] == 1
    mapping = res["session"]["mapping"]
    key = eng.value_key("Status Karangan")
    bad = [dict(m, value_map={key: "terbang"}) if m["field"] == "status" else m for m in mapping]
    with pytest.raises(HTTPException) as e:
        asyncio.run(md.update_mapping(sid, md.MappingIn(mapping=bad), req))
    assert e.value.status_code == 400 and "tidak tersedia" in e.value.detail
    good = [dict(m, value_map={key: "cancelled"}) if m["field"] == "status" else m for m in mapping]
    out = asyncio.run(md.update_mapping(sid, md.MappingIn(mapping=good), req))
    assert out["summary"]["error"] == 0
    saved = db.marketing_data_import_sessions.docs[0]["mapping"]
    assert next(m for m in saved if m["field"] == "status")["value_map"] == {key: "cancelled"}
    # layar lama (tanpa value_map) tidak menghapus pilihan selama field kolom sama
    plain = [{"column": m["column"], "field": m["field"]} for m in mapping]
    out2 = asyncio.run(md.update_mapping(sid, md.MappingIn(mapping=plain), req))
    assert out2["summary"]["error"] == 0


# ═══ 2. Statistik Toko → shopee_shop_stats ═══════════════════════════════════
STATS_HEAD = ["Tanggal", "Total Penjualan (IDR)", "Total Pesanan", "Penjualan per Pesanan",
              "Produk Diklik", "Total Pengunjung", "Tingkat Konversi Pesanan"]


def _shop_stats_xlsx(detail_first_cell="Tanggal", days=3, broken=False):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, mult in (("Pesanan Dibuat", 1), ("Pesanan Siap Dikirim", 2), ("Pesanan Dibayar", 3)):
        # `broken`: nama sheet tidak dikenal penormal (bentuk ekspor yang belum pernah dilihat)
        ws = wb.create_sheet(f"Lembar {mult}" if broken else title)
        ws.append(["Tanggal"] + STATS_HEAD[1:])
        ws.append([f"01-10-2026-0{days}-10-2026", "9.000", "9", "1.000", "90", "30", "3,00%"])
        ws.append([])
        ws.append([detail_first_cell] + STATS_HEAD[1:])
        for d in range(1, days + 1):
            ws.append([f"0{d}-10-2026", f"{d * mult}.000", str(d), "1.000", str(10 * d), str(5 * d), "1,50%"])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


@pytest.mark.parametrize("first_cell", ["Tanggal", "Waktu"])
def test_statistik_toko_rincian_per_hari_terbaca(first_cell):
    headers, rows = prenorm.prenormalize(_shop_stats_xlsx(first_cell), "uji.xlsx", "shopee_shop_stats")
    assert [r["date"] for r in rows] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    r2 = rows[1]
    assert r2["gmv_created"] == "2.000" and r2["gmv_ready"] == "4.000" and r2["gmv_paid"] == "6.000"
    assert r2["visitors"] == "10" and r2["product_clicks"] == "20"
    st = get_source_type("shopee_shop_kpi")
    built = eng.build_rows(rows, eng.auto_map(headers, st), st)
    assert all(b["status"] == "valid" for b in built)


def test_deteksi_statistik_toko_menyarankan_jenis_yang_benar():
    cat = [get_source_type(t["key"]) for t in source_type_catalog()]
    res = eng.detect_source_type(_shop_stats_xlsx(), "uji.xlsx", cat)
    assert res["best"]["source_type"] == "shopee_shop_kpi"


def test_berkas_ditolak_penormal_tetap_sampai_ke_pemetaan(monkeypatch):
    raw = _shop_stats_xlsx(broken=True)
    st = get_source_type("shopee_shop_kpi")
    with pytest.raises(ValueError):
        eng.parse_table(raw, "uji.xlsx", st)
    headers, rows, warn = eng.parse_table_lenient(raw, "uji.xlsx", st)
    assert warn and "apa adanya" in warn
    assert "channel" in headers and all(r["channel"] == "shop" for r in rows)
    # lewat route: sesi dibuat (status pemetaan), alasan disimpan, pembacaan ulang konsisten
    db = FakeDB()
    store: dict = {}
    req = _patch_route(monkeypatch, db, store)
    res = _upload(md, req, raw, "uji.xlsx", "shopee_shop_kpi")
    s = res["session"]
    assert s["prenorm_fallback"] is True and s["parse_warning"]
    assert len(md._reparse(db.marketing_data_import_sessions.docs[0])) == s["total_rows"]


def test_berkas_rusak_tetap_ditolak():
    # berkas yang memang tidak bisa dibaca (bukan Excel) tidak diubah menjadi peringatan
    with pytest.raises(Exception):
        eng.parse_table_lenient(b"bukan excel", "rusak.xlsx", get_source_type("shopee_shop_kpi"))
    with pytest.raises(Exception):
        eng.parse_table_lenient(b"bukan excel", "rusak.xlsx", MO)


# ═══ 3. Penghasilan "sudah dilepas" → impor pencairan ═════════════════════════
INC_GROUP = ["Informasi Pesanan", "", "", "", "Rincian Jumlah Pelepasan Dana", "", "", "", "", "",
             "Buyer Info", "Informasi Referensi", ""]
INC_SUB = ["", "", "", "", "Total Penghasilan", "Subtotal Pesanan", "", "Voucher dan Potongan Harga", "",
           "Biaya Platform", "", "Pengiriman", "Rincian pengembalian barang/dana"]
INC_HEAD = ["No.", "Lihat berdasarkan", "No. Pesanan", "Tanggal Dana Dilepaskan", "Total Penghasilan",
            "Harga Produk", "Jumlah Pengembalian Dana ke Pembeli", "Voucher disponsor oleh Penjual",
            "Diskon Produk dari Shopee", "Biaya Administrasi", "Jumlah Dibayar Pembeli",
            "Promo Gratis Ongkir dari Penjual", "Pengembalian Dana ke Pembeli"]


def _income_xlsx():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Laporan Penghasilan"])
    ws.append(["Subtotal Pesanan", 999999])
    ws.append(["Biaya Platform", -1])
    ws2 = wb.create_sheet("Penghasilan")
    ws2.append(INC_GROUP)
    ws2.append(INC_SUB)
    ws2.append(INC_HEAD)
    # dua pesanan; tiap pesanan punya baris Order + baris Sku (pecahan yang SAMA)
    for no, (net, gross, ref, vch, shp, adm) in enumerate([(85000, 100000, 0, -5000, 2000, -12000),
                                                           (40000, 50000, -5000, 0, 0, -5000)], 1):
        ws2.append([no, "Order", f"UJI-{no}", "2026-10-05", net, gross, ref, vch, shp, adm, gross + 7000, 0, ref])
        ws2.append([no, "Sku", f"UJI-{no}", "2026-10-05", net, gross, ref, vch, shp, adm, None, None, None])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_penghasilan_dibaca_dari_sheet_dan_baris_order_saja():
    r = si.parse_settlement_report(_income_xlsx(), "Income.sudah_dilepas.uji.xlsx")
    assert r["row_count"] == 2
    v = r["values"]
    assert v["net_payout"] == 125000 and v["gross_sales"] == 150000
    assert v["refunds"] == 5000                       # tidak dobel dengan grup referensi
    assert v["seller_discount"] == 5000               # voucher penjual
    assert v["platform_commission"] == 17000
    assert "Diskon Produk dari Shopee" in r["unmapped_numeric_columns"]   # dibiayai platform
    assert "Pengembalian Dana ke Pembeli" not in r["numeric_columns"]
    assert "Jumlah Dibayar Pembeli" not in r["numeric_columns"]
    notes = " ".join(r["notes"])
    assert "Penghasilan" in notes and "Sku" in notes and "kolom informasi" in notes
    assert r["settlement_date"] == "2026-10-05"


def test_laporan_csv_lama_tetap_sama():
    rows = [["No. Pesanan", "Tanggal Dana Dilepaskan", "Waktu Pesanan Dibuat", "Harga Asli Produk",
             "Total Diskon Produk", "Voucher Ditanggung Penjual", "Biaya Administrasi", "Biaya Layanan",
             "Biaya Komisi AMS", "Pengembalian Dana ke Pembeli", "Ongkos Kirim Dibayar Pembeli",
             "Total Penghasilan", "Persentase Biaya Administrasi"],
            ["2608A1", "2026-08-15", "2026-08-02 10:00", "1.000.000", "-50.000", "-20.000", "-45.000",
             "-15.000", "-10.000", "0", "12.000", "860.000", "4,5%"],
            ["2608A2", "2026-08-15", "2026-08-05 12:00", "2.000.000", "-100.000", "0", "-90.000",
             "-30.000", "0", "-200.000", "15.000", "1.580.000", "4,5%"]]
    raw = _csv(rows[0], rows[1:], delim=";")
    r = si.parse_settlement_report(raw, "settlement.csv")
    v = r["values"]
    assert v["gross_sales"] == 3000000 and v["refunds"] == 200000 and v["net_payout"] == 2440000
    assert v["seller_discount"] == 170000 and v["platform_commission"] == 135000
    assert v["affiliate_commission"] == 10000 and v["platform_service_fee"] == 45000


def test_pratinjau_pencairan_tanpa_kolom_dikenal_tidak_buntu(monkeypatch):
    async def _fin(_req):
        return {"id": "u-fin", "role": "finance"}
    monkeypatch.setattr(ms, "_require_finance", _fin)
    monkeypatch.setattr(ms, "get_db", lambda: FakeDB())
    raw = _csv(["Kode", "Kolom Aneh A", "Kolom Aneh B"], [["X1", "1.000", "2.000"], ["X2", "3.000", "4.000"]])
    f = UploadFile(file=io.BytesIO(raw), filename="laporan_aneh.csv")
    out = asyncio.run(ms.import_preview(FakeRequest(), file=f, account_id=""))
    assert out["ok"] and out["mapping"] == {}
    assert out["numeric_columns"] == ["Kolom Aneh A", "Kolom Aneh B"]
    assert out["warnings"] and "Arahkan" in out["warnings"][0]
    # Excel yang kepalanya sama sekali tidak dikenali juga tetap sampai ke pemetaan
    wb = openpyxl.Workbook()
    wb.active.append(["Kode", "Kolom Aneh A"])
    wb.active.append(["X1", 1000])
    b = io.BytesIO()
    wb.save(b)
    f2 = UploadFile(file=io.BytesIO(b.getvalue()), filename="laporan_aneh.xlsx")
    out2 = asyncio.run(ms.import_preview(FakeRequest(), file=f2, account_id=""))
    assert out2["numeric_columns"] == ["Kolom Aneh A"] and out2["warnings"]


# ═══ 4. Kartu stok katalog (stock-dashboard) ═══════════════════════════════════
class _AggCollection(FakeCollection):
    """Koleksi palsu + `aggregate` ($match/$group-$sum) — khusus uji ini."""

    def aggregate(self, pipeline):
        docs = [copy.deepcopy(d) for d in self.docs]
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if match(d, stage["$match"])]
            elif "$group" in stage:
                spec, groups = stage["$group"], {}
                for d in docs:
                    # seperti Mongo: field yang TIDAK ADA tidak muncul di _id
                    key = {k: d[v[1:]] for k, v in spec["_id"].items() if v[1:] in d}
                    g = groups.setdefault(repr(sorted(key.items(), key=lambda kv: kv[0])),
                                          {"_id": key, **{a: 0 for a in spec if a != "_id"}})
                    for a, op in spec.items():
                        if a != "_id":
                            assert op == {"$sum": 1}
                            g[a] += 1
                docs = list(groups.values())
            else:
                raise NotImplementedError(stage)
        return FakeCursor(docs)


class _AggDB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _AggCollection(name)
        return self._cols[name]


def _import_catalog_mgmt():
    # modul membuat folder unggahan foto saat diimpor; di wadah uji folder itu tidak bisa dibuat
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


PIC = {"id": "u-pic", "name": "PIC", "role": "pic_toko"}
ADMIN = {"id": "u-adm", "name": "Admin", "role": "superadmin"}


def _catalog_db():
    db = _AggDB()
    db.marketing_platform_accounts.docs = [
        {"id": "acc-a", "account_code": "UJI-A", "platform": "shopee", "status": "active", "pic_user_id": "u-pic"},
        {"id": "acc-b", "account_code": "UJI-B", "platform": "tiktok", "status": "active"},
    ]
    db.marketing_catalogs.docs = [
        {"id": "cat-a", "account_id": "acc-a", "platform": "shopee", "is_active": True},
        {"id": "cat-b", "account_id": "acc-b", "platform": "tiktok", "is_active": True},
        {"id": "cat-a-off", "account_id": "acc-a", "platform": "shopee", "is_active": False},
    ]
    db.rahaza_materials.docs = [
        {"id": "fg-1", "type": "fg", "code": "FG-1"},   # stok 50 → tersedia
        {"id": "fg-2", "type": "fg", "code": "FG-2"},   # stok 3  → stok rendah
        {"id": "fg-3", "type": "fg", "code": "FG-3"},   # stok 0  → habis
    ]
    db.rahaza_material_stock.docs = [
        {"material_id": "fg-1", "location_id": "L1", "qty": 50},
        {"material_id": "fg-2", "location_id": "L1", "qty": 3},
    ]
    items = []
    # toko A: 600 item tertaut fg-1, TANPA account_id (seperti item hasil impor), cache kosong
    for i in range(600):
        items.append({"id": f"a{i}", "catalog_id": "cat-a", "fg_material_id": "fg-1", "is_active": True,
                      "stock_status": None, "name": f"Item A{i}", "sku": f"A{i}"})
    items += [
        {"id": "a-low", "catalog_id": "cat-a", "fg_material_id": "fg-2", "is_active": True,
         "stock_status": "in_stock", "stock_quantity": 99, "name": "Item rendah", "sku": "AL"},
        {"id": "a-out", "catalog_id": "cat-a", "fg_material_id": "fg-3", "is_active": True,
         "stock_status": "in_stock", "stock_quantity": 99, "name": "Item habis", "sku": "AO",
         "stock_alert_threshold": 5},
        {"id": "a-manual", "catalog_id": "cat-a", "is_active": True, "stock_status": "in_stock",
         "stock_quantity": 7, "name": "Item manual", "sku": "AM"},
        {"id": "a-nonaktif", "catalog_id": "cat-a", "fg_material_id": "fg-1", "is_active": False},
        {"id": "a-katalog-off", "catalog_id": "cat-a-off", "fg_material_id": "fg-1", "is_active": True},
        # item ber-account_id toko A tetapi di katalog toko B — dihitung menurut KATALOG-nya
        {"id": "b1", "catalog_id": "cat-b", "account_id": "acc-a", "fg_material_id": "fg-1", "is_active": True},
        {"id": "b2", "catalog_id": "cat-b", "account_id": "acc-b", "fg_material_id": "fg-2", "is_active": True,
         "name": "Item B rendah", "sku": "B2"},
    ]
    db.marketing_catalog_items.docs = items
    return db


def _dashboard(cm, db, user, monkeypatch, **kw):
    async def _auth(_req):
        return user
    monkeypatch.setattr(cm, "require_auth", _auth)
    monkeypatch.setattr(cm, "get_db", lambda: db)
    req = FakeRequest()
    req.state.user = user
    return asyncio.run(cm.stock_dashboard(req, account_id=kw.get("account_id"), platform=kw.get("platform")))


def test_kartu_stok_tanpa_batas_500_dan_status_live(monkeypatch):
    cm = _import_catalog_mgmt()
    out = _dashboard(cm, _catalog_db(), ADMIN, monkeypatch)
    s = out["summary"]
    assert s["total_items"] == 600 + 3 + 2           # semua katalog AKTIF, tanpa batas 500
    assert s["in_stock"] == 600 + 1                   # fg-1 live 50 (cache kosong diabaikan)
    assert s["low_stock"] == 2 and s["out_of_stock"] == 1 and s["unlinked"] == 1
    assert s["catalogs"] == 2
    names = {i["name"]: i for i in out["low_stock_items"]}
    assert names["Item habis"]["stock_status"] == "out_of_stock" and names["Item habis"]["stock_quantity"] == 0
    assert names["Item rendah"]["stock_quantity"] == 3
    plat = {p["platform"]: p for p in out["platform_breakdown"]}
    assert plat["tiktok"]["total"] == 2 and plat["shopee"]["unlinked"] == 1


def test_kartu_stok_pic_menghitung_isi_katalog_yang_terlihat(monkeypatch):
    cm = _import_catalog_mgmt()
    out = _dashboard(cm, _catalog_db(), PIC, monkeypatch)
    s = out["summary"]
    # PIC toko A: isi katalog toko A (termasuk item tanpa account_id), bukan item ber-account_id A
    assert s["catalogs"] == 1 and s["total_items"] == 603
    assert s["in_stock"] == 600 and s["low_stock"] == 1 and s["out_of_stock"] == 1 and s["unlinked"] == 1
    # PIC meminta toko yang bukan miliknya → kosong, bukan angka toko lain
    out_b = _dashboard(cm, _catalog_db(), PIC, monkeypatch, account_id="acc-b")
    assert out_b["summary"]["total_items"] == 0


def test_kartu_stok_tanpa_to_list_none():
    src = (ROOT / "routes" / "marketing_catalog_mgmt.py").read_text(encoding="utf-8")
    block = src[src.index("async def stock_dashboard"):src.index("_DASH_LINK_KEYS = ")]
    assert ".to_list(500)" not in block and "to_list(None)" not in block
    assert ".aggregate(pipeline)" in block
    assert "await _scope.scope_filter(db, user, cq)" in block      # lingkup = visible_account_ids


# ═══ 5. Migrasi pemetaan lama ═════════════════════════════════════════════════
def _load_migration():
    p = ROOT / "scripts" / "migrations" / "2026_11_06_impor_pesanan_subtotal.py"
    spec = importlib.util.spec_from_file_location("mig_2026_11_06_impor", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _old_mapping():
    old = [dict(m) for m in eng.auto_map(ORDER_HEADERS, MO)]
    for m in old:
        if m["column"] == "Harga Setelah Diskon":
            m["field"] = "sku_subtotal_after_discount"
        if m["column"] == "Subtotal Pesanan":
            m["field"] = "sku_subtotal_before_discount"
    return old


def test_migrasi_membetulkan_pemetaan_murni():
    mig = _load_migration()
    new, changed = mig.fix_mapping("marketplace_orders", _old_mapping(), ORDER_HEADERS)
    got = {m["column"]: m["field"] for m in new}
    assert set(changed) == {"Harga Setelah Diskon", "Subtotal Pesanan"}
    assert got["Harga Setelah Diskon"] == "sku_unit_deal_price"
    assert got["Subtotal Pesanan"] == "sku_subtotal_after_all_discount"   # riset G5 (9 Nov)
    assert not mig.has_retired("marketplace_orders", new)


def test_migrasi_pratinjau_lalu_apply_hanya_draf_dan_ingatan(monkeypatch, capsys):
    mig = _load_migration()
    db = FakeDB()
    old = _old_mapping()
    db.marketing_data_import_formats.docs = [
        {"source_type": "marketplace_orders", "fingerprint": "fp1", "headers": ORDER_HEADERS, "mapping": old}]
    db.marketing_data_import_sessions.docs = [
        {"id": "s-draf", "source_type": "marketplace_orders", "status": "ready", "headers": ORDER_HEADERS,
         "mapping": copy.deepcopy(old), "account_code": "UJI-01"},
        {"id": "s-simpan", "source_type": "marketplace_orders", "status": "committed", "rolled_back_at": None,
         "headers": ORDER_HEADERS, "mapping": copy.deepcopy(old), "account_code": "UJI-01", "committed_at": T0},
        {"id": "s-batal", "source_type": "marketplace_orders", "status": "rolled_back", "rolled_back_at": T0,
         "headers": ORDER_HEADERS, "mapping": copy.deepcopy(old)},
    ]
    db.marketing_orders.docs = [{"id": f"o{i}", "_import_session_id": "s-simpan"} for i in range(4)]
    before = copy.deepcopy(db.marketing_data_import_sessions.docs)

    out = asyncio.run(mig.run(False, db=db))
    assert out == {"formats": 1, "drafts": 1, "committed": 1, "committed_orders": 4}
    assert db.marketing_data_import_sessions.docs == before            # pratinjau tidak menulis

    asyncio.run(mig.run(True, db=db))
    docs = {s["id"]: s for s in db.marketing_data_import_sessions.docs}
    assert not mig.has_retired("marketplace_orders", docs["s-draf"]["mapping"])
    assert docs["s-draf"]["mapping_report"]["ready"] is True
    assert docs["s-simpan"]["mapping"] == before[1]["mapping"]          # tersimpan TIDAK diubah
    assert not mig.has_retired("marketplace_orders", db.marketing_data_import_formats.docs[0]["mapping"])
    text = capsys.readouterr().out
    assert "Perbarui yang lama" in text

    again = asyncio.run(mig.run(True, db=db))                            # idempoten
    assert again["formats"] == 0 and again["drafts"] == 0 and again["committed"] == 1


# ═══ 6. Sambungan kecil yang lain ═════════════════════════════════════════════
def test_impor_ulang_perbarui_ikut_menghitung_ulang_rekap_harian():
    src = (ROOT / "routes" / "marketing_data_import.py").read_text(encoding="utf-8")
    block = src[src.index("async def commit("):src.index("def import_fulfillment_status")]
    assert "updated_ids.append(existing[\"id\"])" in block
    assert '{"id": {"$in": updated_ids}}' in block
    rb = src[src.index("async def rollback("):src.index('@router.get("/sessions/{session_id}/undo-report")')]
    assert rb.count('{"id": {"$in": updated_doc_ids}}') == 2      # sebelum & sesudah dipulihkan


def test_layar_wizard_mengirim_arti_nilai_dan_peringatan_berkas():
    p = ROOT.parent / "frontend" / "src" / "components" / "erp" / "marketing" / "DataImportWizard.jsx"
    if not p.exists():
        pytest.skip("frontend tidak ada di lingkungan ini")
    src = p.read_text(encoding="utf-8")
    assert "value_map: m.value_map" in src and "<ImportValueMapPanel" in src
    assert "session.parse_warning" in src and "setValueReport(r.data.value_report" in src
    panel = (p.parent / "ImportValueMapPanel.jsx").read_text(encoding="utf-8")
    assert 'data-testid="import-value-map"' in panel and "Belum dikenal" in panel


def test_layar_katalog_memakai_stattile_dan_menampilkan_belum_tertaut():
    p = ROOT.parent / "frontend" / "src" / "components" / "erp" / "CatalogManagementModule.jsx"
    if not p.exists():
        pytest.skip("frontend tidak ada di lingkungan ini")
    src = p.read_text(encoding="utf-8")
    assert "<StatTile" in src and "summary?.unlinked" in src
