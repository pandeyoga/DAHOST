"""Kanal penjualan pada input MANUAL Marketing (keputusan owner 11 Nov 2026).

Owner: "Ya, tambahkan" — omzet yang diinput tangan harus terpecah per kanal (Live, Video,
Kartu produk, Afiliasi, …), tidak semuanya jatuh ke "Lainnya". Keputusan yang diuji:

  G1  Hari TANPA pesanan: rincian ketikan dipakai; sisa omzet = "Lainnya"; rincian > omzet ditolak.
  G2  Hari DENGAN pesanan ("Isi bagian Lainnya"): kanal dari pesanan tetap; rincian ketikan hanya
      membagi bagian "Lainnya" pesanan (mis. Shopee tanpa kolom kanal). Lebih besar dari bagian itu
      ⇒ ditolak di layar, dan rollup tidak memakainya (alasannya disimpan).
  G3  Live pada rincian = BAGIAN omzet total (tidak dobel).
  P1  Pesanan manual: kanal WAJIB dipilih (kode atau label), akun kreator opsional.
  I1  Impor Sales Harian: kolom "Kanal … (Rp)" ikut ke rekap; hari turunan pesanan hanya membagi "Lainnya".
  L1  Laporan: omzet per kanal & per toko membaca pecahan kanal rekap (termasuk ketikan staf).

Semua data di sini SINTETIS.
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from _mkt_uji import (DB, SA, Req, acc, csv_bytes, import_file, patch_import,  # noqa: E402
                      patch_route, rekap, run)
from core import marketing_daily_rollup as rollup  # noqa: E402
from core import marketing_sales_shape as S  # noqa: E402

HARI = "2026-11-03"


def _order(oid, aid, amount, channel=None, status="completed"):
    o = {"id": oid, "order_id": oid, "account_id": aid, "status": status,
         "order_date": datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc),
         "revenue_product": float(amount), "order_amount": float(amount), "quantity": 1,
         "_import_source_type": "marketplace_orders"}
    if channel:
        o["order_channel"] = channel
    return o


@pytest.fixture
def db():
    d = DB()
    d.marketing_platform_accounts.docs += [acc("SHP-01", platform="shopee"), acc("TTK-01"),
                                           acc("WA-01", platform="whatsapp")]
    return d


# ── G1/G2/G3 — aturan gabung murni ──────────────────────────────────────────────────────────
def test_g1_tanpa_pesanan_sisa_jadi_lainnya_dan_rincian_lebih_besar_tidak_dipakai():
    t, st = S.merge_traffic(None, {"live": 3_000_000, "video": 1_000_000}, 10_000_000)
    assert t["live"] == 3_000_000 and t["video"] == 1_000_000 and t["other"] == 6_000_000
    assert sum(t.values()) == 10_000_000 and st["dipakai"] is True        # G3: tidak dobel
    t2, st2 = S.merge_traffic(None, {"live": 12_000_000}, 10_000_000)
    assert t2 == {} and st2["dipakai"] is False and "lebih besar" in st2["alasan"]
    assert S.merge_traffic(None, {}, 10_000_000) == ({}, {})


def test_g2_hari_berpesanan_hanya_membagi_bagian_lainnya():
    pesanan = {"live": 4_000_000, "video": 0.0, "other": 5_000_000}
    t, st = S.merge_traffic(pesanan, {"video": 2_000_000, "affiliate": 1_000_000}, 9_000_000)
    assert t["live"] == 4_000_000                                         # kanal pesanan tetap
    assert t["video"] == 2_000_000 and t["affiliate"] == 1_000_000 and t["other"] == 2_000_000
    assert st["dasar"] == S.DASAR_LAINNYA_PESANAN and st["dipakai"] is True
    t2, st2 = S.merge_traffic(pesanan, {"video": 6_000_000}, 9_000_000)
    assert t2["video"] == 0 and t2["other"] == 5_000_000 and st2["dipakai"] is False


def test_kanal_tidak_dikenal_atau_minus_ditolak_dengan_pesan_staf():
    with pytest.raises(S.KanalTidakSah) as e:
        S.clean_manual_traffic({"other": 5})
    assert "Lainnya" in str(e.value)
    with pytest.raises(S.KanalTidakSah):
        S.clean_manual_traffic({"live": -1})
    assert S.clean_manual_traffic({"live": "2500000", "video": 0, "ads": None}) == {"live": 2_500_000}


# ── rollup: rincian ketikan bertahan & hanya mengisi "Lainnya" ──────────────────────────────
def test_rollup_shopee_tanpa_kanal_rincian_manual_membagi_lainnya(db):
    db.marketing_orders.docs += [_order("s1", "SHP-01", 6_000_000), _order("s2", "SHP-01", 3_000_000)]
    run(rollup.recompute_daily(db, "SHP-01", HARI))
    doc = run(rekap(db, "SHP-01", HARI))["doc"]
    assert doc["traffic"]["other"] == 9_000_000 and doc["traffic_orders"]["other"] == 9_000_000
    # staf merinci (Shopee: live 2 jt, video 1 jt) lalu pesanan dihitung ulang — rincian TIDAK hilang
    run(db.marketing_sales_data.update_one({"account_id": "SHP-01", "date": HARI},
                                           {"$set": {"traffic_manual": {"live": 2_000_000, "video": 1_000_000}}}))
    run(rollup.recompute_daily(db, "SHP-01", HARI))
    doc = run(rekap(db, "SHP-01", HARI))["doc"]
    assert doc["traffic"]["live"] == 2_000_000 and doc["traffic"]["video"] == 1_000_000
    assert doc["traffic"]["other"] == 6_000_000 and doc["metrics"]["revenue"] == 9_000_000
    assert doc["traffic_manual_status"]["dipakai"] is True


def test_rollup_tiktok_berkanal_rincian_manual_lebih_besar_tidak_dipakai(db):
    db.marketing_orders.docs += [_order("t1", "TTK-01", 4_000_000, "live"),
                                 _order("t2", "TTK-01", 1_000_000, "video")]
    db.marketing_sales_data.docs.append({
        "id": "m1", "account_id": "TTK-01", "date": HARI, "revenue_type": "total", "source": "manual",
        "metrics": {"revenue": 5_000_000}, "traffic_manual": {"live": 3_000_000}})
    run(rollup.recompute_daily(db, "TTK-01", HARI))
    doc = run(rekap(db, "TTK-01", HARI))["doc"]
    assert doc["source"] == "orders_auto"
    assert doc["traffic"]["live"] == 4_000_000 and doc["traffic"]["video"] == 1_000_000
    assert doc["traffic_manual_status"]["dipakai"] is False      # pesanan menang, alasan tersimpan
    assert doc["traffic_manual"] == {"live": 3_000_000}          # ketikan tidak dibuang


# ── Input Sales (POST /sales-data dan PUT /sales-data/kanal) ─────────────────────────────────
def _sales(monkeypatch, db):
    import routes.marketing_sales as ms
    patch_route(monkeypatch, ms, db, user=SA)
    return ms


def test_input_sales_baru_dengan_rincian_kanal(db, monkeypatch):
    ms = _sales(monkeypatch, db)
    from routes.marketing_shared import SalesDataEntry
    run(ms.create_sales_data(SalesDataEntry(account_id="WA-01", date=HARI, revenue_type="total",
                                            revenue=10_000_000, orders=20,
                                            kanal={"live": 3_000_000, "affiliate": 2_000_000}),
                             Req(SA), override=False, override_reason=None))
    doc = run(rekap(db, "WA-01", HARI))["doc"]
    assert doc["traffic"]["live"] == 3_000_000 and doc["traffic"]["affiliate"] == 2_000_000
    assert doc["traffic"]["other"] == 5_000_000 and doc["traffic_manual"]["live"] == 3_000_000
    for kanal, rtype in (({"live": 11_000_000}, "total"), ({"live": 1}, "live")):
        with pytest.raises(HTTPException) as e:
            run(ms.create_sales_data(SalesDataEntry(account_id="WA-01", date="2026-11-04",
                                                    revenue_type=rtype, revenue=10_000_000,
                                                    kanal=kanal),
                                     Req(SA), override=False, override_reason=None))
        assert e.value.status_code == 400


def test_simpan_rincian_kanal_saja_pada_hari_turunan_pesanan(db, monkeypatch):
    ms = _sales(monkeypatch, db)
    from routes.marketing_shared import SalesKanalEntry
    db.marketing_orders.docs += [_order("s1", "SHP-01", 9_000_000)]
    run(rollup.recompute_daily(db, "SHP-01", HARI))
    with pytest.raises(HTTPException) as e:          # lebih besar dari bagian "Lainnya" pesanan
        run(ms.save_sales_kanal(SalesKanalEntry(account_id="SHP-01", date=HARI,
                                                kanal={"live": 9_500_000}), Req(SA)))
    assert e.value.status_code == 400 and "pesanan tanpa kanal" in e.value.detail
    out = run(ms.save_sales_kanal(SalesKanalEntry(account_id="SHP-01", date=HARI,
                                                  kanal={"live": 4_000_000}), Req(SA)))
    t = out["entry"]["traffic"]
    assert t["live"] == 4_000_000 and t["other"] == 5_000_000
    assert out["entry"]["metrics"]["revenue"] == 9_000_000 and out["entry"]["source"] == "orders_auto"
    out = run(ms.save_sales_kanal(SalesKanalEntry(account_id="SHP-01", date=HARI, kanal={}), Req(SA)))
    assert out["entry"]["traffic"]["live"] == 0 and out["entry"]["traffic"]["other"] == 9_000_000
    with pytest.raises(HTTPException) as e:          # belum ada rekap ⇒ 404 dengan jalan keluar
        run(ms.save_sales_kanal(SalesKanalEntry(account_id="SHP-01", date="2026-11-09",
                                                kanal={"live": 1}), Req(SA)))
    assert e.value.status_code == 404


def test_rekap_turunan_lama_tanpa_traffic_orders_tidak_terhitung_dua_kali(db, monkeypatch):
    """Dokumen turunan dari sebelum 11 Nov belum punya `traffic_orders`; dua kali simpan rincian
    tidak boleh membaca `traffic` hasil gabung sebagai angka pesanan."""
    ms = _sales(monkeypatch, db)
    from routes.marketing_shared import SalesKanalEntry
    db.marketing_sales_data.docs.append({
        "id": "lama", "account_id": "SHP-01", "date": HARI, "revenue_type": "total",
        "source": "orders_auto", "locked_source": True, "metrics": {"revenue": 9_000_000},
        "traffic": {"live": 0.0, "other": 9_000_000}})
    for _ in range(2):
        out = run(ms.save_sales_kanal(SalesKanalEntry(account_id="SHP-01", date=HARI,
                                                      kanal={"live": 3_000_000}), Req(SA)))
    t = out["entry"]["traffic"]
    assert t["live"] == 3_000_000 and t["other"] == 6_000_000
    assert out["entry"]["traffic_orders"]["other"] == 9_000_000


# ── P1 — pesanan manual ──────────────────────────────────────────────────────────────────────
def _order_env(db, monkeypatch):
    import routes.marketing_orders_routes as mo
    patch_route(monkeypatch, mo, db, user=SA)

    async def _link(_db, **_k):
        return {"catalog_item_id": "c1", "variant_id": None, "fg_material_id": "fg1", "variant_sku": "S1",
                "product_name": "Kaos", "variation": "", "model_id": None, "harga_jual": 100_000.0,
                "resolved_by": "catalog_item_id"}

    async def _noop(*_a, **_k):
        return {}
    monkeypatch.setattr(mo, "_resolve_order_link", _link)
    monkeypatch.setattr(rollup, "recompute_for_orders", _noop)
    return mo


def test_p1_pesanan_manual_wajib_kanal_dan_menyimpan_akun_kreator(db, monkeypatch):
    mo = _order_env(db, monkeypatch)
    base = dict(platform="whatsapp", account_id="WA-01", customer_name="Uji", catalog_item_id="c1",
                quantity=1, price_final=100_000)
    for salah in (None, "", "Facebook"):
        with pytest.raises(HTTPException) as e:
            run(mo.create_order(mo.OrderCreateBody(**base, order_channel=salah), Req()))
        assert e.value.status_code == 400 and "Kartu produk" in e.value.detail
    out = run(mo.create_order(mo.OrderCreateBody(**base, order_channel="Kartu produk",
                                                 creator_handle=" @kreator.uji "), Req()))
    assert out["order_channel"] == "product_card" and out["creator_handle"] == "@kreator.uji"
    out = run(mo.create_order(mo.OrderCreateBody(**base, order_channel="affiliate"), Req()))
    assert out["order_channel"] == "affiliate"


# ── I1 — impor Sales Harian dengan kolom kanal ───────────────────────────────────────────────
HDR = ["Tanggal", "Jenis Revenue", "Revenue (Rp)", "Jumlah Order", "Kanal Live (Rp)",
       "Kanal Video (Rp)", "Kanal Afiliasi (Rp)"]


def test_i1_impor_sales_harian_kolom_kanal_baru_dan_terlalu_besar(db, monkeypatch):
    md = patch_import(monkeypatch, db)
    raw = csv_bytes([HDR, [HARI, "total", 10_000_000, 30, 3_000_000, 2_000_000, 1_000_000],
                     ["2026-11-04", "total", 1_000_000, 3, 2_000_000, "", ""]])
    _sid, res = run(import_file(md, raw, "sales.csv", "sales_daily", "WA-01"))
    assert res["inserted"] == 1
    doc = run(rekap(db, "WA-01", HARI))["doc"]
    assert doc["traffic"]["live"] == 3_000_000 and doc["traffic"]["video"] == 2_000_000
    assert doc["traffic"]["affiliate"] == 1_000_000 and doc["traffic"]["other"] == 4_000_000
    assert "kanal_live" not in doc                                        # bukan field akar
    assert run(rekap(db, "WA-01", "2026-11-04")) is None                  # rincian > omzet ditolak


def test_i1_impor_pada_hari_turunan_hanya_membagi_lainnya(db, monkeypatch):
    md = patch_import(monkeypatch, db)
    db.marketing_orders.docs += [_order("s1", "SHP-01", 9_000_000)]
    run(rollup.recompute_daily(db, "SHP-01", HARI))
    # Revenue di berkas diabaikan (hari turunan); kanal tetap harus masuk akal terhadapnya
    raw = csv_bytes([HDR, [HARI, "total", 9_000_000, 1, 2_500_000, "", ""]])
    _sid, res = run(import_file(md, raw, "sales.csv", "sales_daily", "SHP-01"))
    doc = run(rekap(db, "SHP-01", HARI))["doc"]
    assert doc["metrics"]["revenue"] == 9_000_000                         # omzet tetap dari pesanan
    assert doc["traffic"]["live"] == 2_500_000 and doc["traffic"]["other"] == 6_500_000
    assert doc["source"] == "orders_auto"


# ── L1 — laporan membaca pecahan kanal rekap ─────────────────────────────────────────────────
def test_l1_rincian_kanal_dan_per_toko_memakai_rekap_berkanal():
    from core import ukuran_penjualan as U
    rows = [{"account_id": "WA-01", "date": HARI, "omzet": 10_000_000,
             "kanal": {"live": 3_000_000, "other": 7_000_000}},
            {"account_id": "TTK-01", "date": HARI, "omzet": 500.0, "kanal": {}}]
    orders = [{**_order("t1", "TTK-01", 500, "video"), "_tanggal": HARI}]
    k = {c["kunci"]: c for c in U.rincian_kanal(orders, rows)}
    assert k["live"]["omzet"] == 3_000_000 and k["other"]["omzet"] == 7_000_000
    assert k["video"]["omzet"] == 500 and k["video"]["pesanan"] == 1      # hari tanpa pecahan: pesanan
    per = {r["account_id"]: r for r in U.kanal_per_toko(rows, orders, {"WA-01": acc("WA-01")})}
    assert per["WA-01"]["kanal"]["live"] == 3_000_000 and per["WA-01"]["belum_dirinci"] == 0
    assert per["TTK-01"]["kanal"]["video"] == 500
