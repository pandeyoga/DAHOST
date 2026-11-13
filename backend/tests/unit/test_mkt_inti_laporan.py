"""MKT-INTI · angka laporan Marketing (audit Marketing 9 Nov 2026) — uji regresi skenario s3.

Data uji = angka audit §1 (hitungan tangan): Agustus TTK-01 Rp6.855.287 (bertarget Rp10 jt) dan
SHP-01 Rp4.871.855 (tanpa target) → gabungan Rp11.727.142. Omzet RESMI per toko & total TIDAK
boleh berubah; yang diperbaiki adalah persen gabungan, anggaran mingguan, diskon, iklan, live.
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from _mkt_uji import (DB, SA, Req, acc, patch_route, rekap_doc, run)  # noqa: E402,F401

TTK, SHP = "TTK-01", "SHP-01"
TTK_AUG, SHP_AUG = 6_855_287, 4_871_855


@pytest.fixture
def db():
    d = DB()
    d.marketing_platform_accounts.docs += [acc(TTK), acc(SHP, platform="shopee")]
    # TTK-01: seluruh omzet 1 Agt (seperti berkas TikTok asli); live = pesanan kanal LIVE
    d.marketing_sales_data.docs.append(rekap_doc(TTK, "2026-08-01", TTK_AUG, 72, live=289_427))
    # SHP-01: tersebar 11–17 Agt + sisa di 5 Agt
    week = [520_000, 610_000, 480_000, 700_000, 530_000, 491_889, 470_000]       # Σ 3.801.889
    for i, v in enumerate(week):
        d.marketing_sales_data.docs.append(rekap_doc(SHP, f"2026-08-{11 + i:02d}", v, 6))
    d.marketing_sales_data.docs.append(rekap_doc(SHP, "2026-08-05", SHP_AUG - sum(week), 20))
    d.marketing_account_targets.docs.append({"id": "t1", "account_id": TTK, "year": 2026, "month": 8,
                                             "revenue_target": 10_000_000, "orders_target": 100,
                                             "health_score_target": 80, "notes": ""})
    return d


# ── M-04 persen gabungan ──────────────────────────────────────────────────────────────────────
def test_m04_laporan_bulanan_persen_gabungan_hanya_toko_bertarget(db, monkeypatch):
    import routes.marketing_reports as mr
    patch_route(monkeypatch, mr, db)
    out = run(mr.monthly_report(Req(), year=2026, month=8))
    s = out["summary"]
    assert s["rev_actual"] == TTK_AUG + SHP_AUG == 11_727_142          # omzet resmi tidak berubah
    assert s["rev_pct"] == 68.6                                           # dulu 117,3
    assert s["rev_actual_untargeted"] == SHP_AUG and s["accounts_without_target"] == 1
    per = {a["account_code"]: a for a in out["accounts"]}
    assert per[TTK]["actual"]["revenue"] == TTK_AUG and per[SHP]["actual"]["revenue"] == SHP_AUG


def test_m04_ringkasan_target_dan_analitik_target_dan_siklus(db, monkeypatch):
    import routes.marketing_targets as mt
    from core import ukuran_penjualan as U
    from core import marketing_cycle as C
    patch_route(monkeypatch, mt, db)
    s = run(mt.monthly_summary(Req(), year=2026, month=8))["summary"]
    assert s["rev_actual"] == 11_727_142 and s["rev_pct"] == 68.6
    t = run(U.analitik_target(db, db.marketing_platform_accounts.docs, ["2026-08"]))["total"]
    assert t["aktual_omzet"] == 11_727_142 and t["capaian_omzet_persen"] == 68.6
    ov = run(C.cycle_overview(db, "2026-08", today=datetime(2026, 9, 2, tzinfo=timezone.utc)))
    assert ov["totals"]["revenue"] == 11_727_142 and ov["totals"]["revenue_pct"] == 68.6


def test_m04_capaian_gabungan_murni():
    from core.ukuran_penjualan import capaian_gabungan
    c = capaian_gabungan([{"t": 100, "a": 50}, {"t": 0, "a": 900}, {"t": None, "a": 10}],
                         lambda r: r["t"], lambda r: r["a"])
    assert c["persen"] == 50.0 and c["aktual_tanpa_target"] == 910 and c["toko_tanpa_target"] == 2
    assert capaian_gabungan([{"t": 0, "a": 5}], lambda r: r["t"], lambda r: r["a"])["persen"] is None


def test_m04_m21_rapat_mingguan_prorata_bulan_bertarget_dan_retur_dari_rekap(db):
    from core import marketing_weekly_report as W
    # Bulan Marketing 26–25 (owner 11 Nov 2026): minggu 24–30 Agt memotong dua bulan —
    # 24–25 Agt = bulan Agustus (bertarget, 2 hari), 26–30 Agt = bulan September (TANPA target).
    db.marketing_sales_data.docs.append(rekap_doc(TTK, "2026-08-25", 1_000_000, 10))
    db.marketing_sales_data.docs.append(rekap_doc(TTK, "2026-08-27", 3_000_000, 30, retur=150_000))
    rep = run(W.build_weekly_report(db, "2026-08-24"))
    ttk = next(s for s in rep["per_toko"] if s["account_code"] == TTK)
    assert ttk["omzet"] == 4_000_000                                     # omzet minggu itu tetap
    assert ttk["omzet_bertarget"] == 1_000_000                           # hanya hari bulan Agustus
    tgt = round(10_000_000 * 2 / 31)                                     # Agustus = 26 Jul–25 Agt (31 hari)
    assert ttk["target"]["revenue"] == tgt
    assert ttk["pencapaian_target_persen"] == round(1_000_000 / tgt * 100, 1)
    assert ttk["nilai_retur"] == 150_000                                 # M-21: dari rekap (K36)
    g = rep["gabungan"]
    assert g["pencapaian_target_persen"] == ttk["pencapaian_target_persen"]


def test_m04_rapat_mingguan_roas_gabungan_hanya_toko_beriklan(db):
    from core import marketing_weekly_report as W
    db.marketing_ads_data.docs.append({"id": "ad1", "account_id": SHP, "campaign_name": "A",
                                       "date": "2026-08-11", "spend": 100_000, "revenue": 300_000})
    g = run(W.build_weekly_report(db, "2026-08-10"))["gabungan"]
    shp_week = sum(d["metrics"]["revenue"] for d in db.marketing_sales_data.docs
                   if d["account_id"] == SHP and "2026-08-10" <= d["date"] <= "2026-08-16")
    assert g["roas"] == round(shp_week / 100_000, 2)            # dulu omzet SEMUA toko ÷ biaya SHP


# ── M-05 anggaran mingguan · Q-1 diskon · Q-3 iklan dibagi rata ───────────────────────────────
def test_m05_q3_anggaran_mingguan_membaca_rentang_7_hari(db, monkeypatch):
    import routes.marketing_budget as mb
    patch_route(monkeypatch, mb, db)
    db.marketing_ads_data.docs.append({
        "id": "cpc1", "account_id": SHP, "campaign_name": "Iklan A", "source_report": "shopee_ads_cpc",
        "date": "2026-08-01", "period_start": "2026-08-01", "period_end": "2026-08-31",
        "spend": 310_000, "revenue": 900_000})
    out = run(mb.budget_summary(Req(), account_id=SHP, period="2026-08-11"))
    assert out["sales"] == 3_801_889                                       # dulu Rp1.474.957 (1 hari)
    ads = next(c for c in out["categories"] if c["category"] == "ads")
    assert ads["spend"] == 70_000                                         # 7/31 × 310.000 (dibagi rata)
    assert (out["date_from"], out["date_to"]) == ("2026-08-11", "2026-08-17")
    month = run(mb.budget_summary(Req(), account_id=SHP, period="2026-08"))
    assert month["sales"] == SHP_AUG                                      # bulanan tidak berubah
    # bulan Marketing Agustus = 26 Jul–25 Agt: laporan iklan 1–31 Agt masuk 25/31 bagian
    assert next(c for c in month["categories"] if c["category"] == "ads")["spend"] == 250_000


def test_q1_diskon_hanya_voucher_paket_dan_subsidi_ongkir_penjual(db):
    from core import marketing_cycle as C
    db.marketing_orders.docs.append({
        "id": "o1", "account_id": SHP, "order_id": "X1", "status": "completed",
        "order_date": datetime(2026, 8, 12, 10, tzinfo=timezone.utc), "paid_at": "2026-08-12",
        "voucher_seller": 5_000, "bundle_discount_seller": 2_000, "shipping_fee_seller_discount": 3_000,
        "seller_discount_total": 41_001,                                  # selisih harga coret
        "items": [{"sku_seller_discount": 41_001, "sku_subtotal_after_discount": 58_999}]})
    r = run(C._auto_diskon(db, SHP, "2026-08"))
    assert r["amount"] == 10_000                                          # dulu 41.001 (+ongkir)
    assert r["breakdown"]["price_markdown_excluded"] == 41_001


def test_q3_analitik_iklan_dibagi_rata_per_minggu(db):
    from core import ukuran_penjualan as U
    db.marketing_ads_data.docs.append({
        "id": "cpc1", "account_id": SHP, "campaign_name": "Iklan A", "source_report": "shopee_ads_cpc",
        "date": "2026-08-01", "period_start": "2026-08-01", "period_end": "2026-08-31",
        "spend": 310_000, "revenue": 620_000})
    out = run(U.analitik_iklan(db, db.marketing_platform_accounts.docs, "2026-08-01", "2026-08-31",
                               kelompok="minggu"))
    assert out["total"]["belanja"] == 310_000
    weeks = {r["kunci"]: r["belanja"] for r in out["baris"]}
    # 1 Agt 2026 = Sabtu ⇒ minggu ISO W31 hanya memuat 2 hari Agustus
    assert weeks["2026-W31"] == 20_000 and weeks["2026-W32"] == 70_000 and len(weeks) == 6
    part = run(U.analitik_iklan(db, db.marketing_platform_accounts.docs, "2026-08-11", "2026-08-17"))
    assert part["total"]["belanja"] == 70_000 and part["total"]["roas"] == 2.0


# ── M-09 iklan dobel lintas jalur · M-23 saluran iklan ────────────────────────────────────────
def test_m09_entri_manual_iklan_kampanye_hari_sama_dengan_impor_cpc_ditolak(db, monkeypatch):
    import routes.marketing_ads_routes as ma
    patch_route(monkeypatch, ma, db)
    db.marketing_ads_data.docs.append({
        "id": "cpc1", "account_id": SHP, "campaign_name": "Iklan A", "source_report": "shopee_ads_cpc",
        "_import_session_id": "s1", "date": "2026-08-01", "period_start": "2026-08-01",
        "period_end": "2026-08-31", "spend": 452_122})
    with pytest.raises(HTTPException) as e:
        run(ma.create_ads_entry(ma.AdsEntryIn(account_id=SHP, date="2026-08-15", campaign_name="iklan a",
                                              spend=8_693), Req()))
    assert e.value.status_code == 409 and "dua kali" in e.value.detail
    run(ma.create_ads_entry(ma.AdsEntryIn(account_id=SHP, date="2026-08-15", campaign_name="Iklan B",
                                          spend=8_693), Req()))
    assert len(db.marketing_ads_data.docs) == 2


def test_m23_ringkasan_iklan_per_saluran_iklan_bukan_platform_toko(db, monkeypatch):
    import routes.marketing_ads_routes as ma
    patch_route(monkeypatch, ma, db)
    db.marketing_ads_data.docs += [
        {"id": "a1", "account_id": SHP, "platform": "shopee", "ad_platform": "meta_ads",
         "campaign_name": "M", "date": "2026-08-02", "spend": 100.0, "revenue": 300.0},
        {"id": "a2", "account_id": SHP, "platform": "shopee", "source_report": "shopee_ads_cpc",
         "campaign_name": "C", "date": "2026-08-01", "period_start": "2026-08-01",
         "period_end": "2026-08-31", "spend": 310.0, "revenue": 310.0}]
    out = run(ma.ads_summary(Req(), account_id=SHP, date_from=None, date_to=None))["data"]
    assert set(out["by_platform"]) == {"meta_ads", "shopee_ads_cpc"}
    part = run(ma.ads_summary(Req(), account_id=SHP, date_from="2026-08-01", date_to="2026-08-07"))["data"]
    assert part["total_spend"] == 100.0 + 70.0                            # CPC dibagi rata


# ── M-07 / Q-2 satu definisi omzet live ───────────────────────────────────────────────────────
def test_q2_dashboard_live_dari_pesanan_kanal_live_tidak_dobel(db, monkeypatch):
    import routes.marketing_dashboard as md
    patch_route(monkeypatch, md, db)
    # sinkron lama: shift host + sesi kreator untuk siaran yang sama = 2 × 289.427
    db.marketing_sales_data.docs.append(rekap_doc(TTK, "2026-08-01", 578_854, 10, rtype="live",
                                                  source="livehost_creator_auto"))
    ov = run(md.get_marketing_dashboard_overview(Req(), date_from="2026-08-01", date_to="2026-08-31")) \
        if hasattr(md, "get_marketing_dashboard_overview") else None
    if ov is None:
        fn = next(getattr(md, n) for n in dir(md) if n.endswith("overview") and callable(getattr(md, n)))
        ov = run(fn(Req(), date_from="2026-08-01", date_to="2026-08-31"))
    assert ov["summary"]["total_revenue_live"] == 289_427                 # dulu 578.854
    assert ov["summary"]["total_revenue"] == 11_727_142
    acc_d = run(md.get_account_dashboard(TTK, Req(), date_from="2026-08-01", date_to="2026-08-31"))
    assert acc_d["live_revenue_stream"]["revenue"] == 289_427
    assert acc_d["total_revenue_stream"]["revenue"] == TTK_AUG


def test_q2_ringkas_live_rekap_manual_dipakai_untuk_toko_tanpa_pesanan(db):
    from core import ukuran_penjualan as U
    db.marketing_platform_accounts.docs.append(acc("WA-01", platform="whatsapp"))
    db.marketing_sales_data.docs += [rekap_doc("WA-01", "2026-08-03", 500_000, 5, source="manual"),
                                     rekap_doc("WA-01", "2026-08-03", 120_000, 2, rtype="live",
                                               source="manual")]
    out = run(U.ringkas_live(db, db.marketing_platform_accounts.docs, "2026-08-01", "2026-08-31"))
    assert out["omzet"] == 289_427 + 120_000


def test_m07_sesi_live_batal_tidak_dijumlah_dan_hapus_sesi_kreator_menyinkron(db, monkeypatch):
    import routes.marketing_live_sessions_routes as ml
    import routes.marketing_kol_ops as ko
    patch_route(monkeypatch, ml, db)
    db.marketing_live_sessions.docs += [
        {"id": "l1", "account_id": TTK, "session_date": "2026-08-01", "revenue": 289_427, "status": "completed"},
        {"id": "l2", "account_id": TTK, "session_date": "2026-08-01", "revenue": 500_000, "status": "cancelled"}]
    out = run(ml.live_summary(Req(), account_id=None))["data"]
    assert out["total_revenue"] == 289_427                                # dulu 789.427
    # hapus sesi kreator → rekap catatan live dihitung ulang
    patch_route(monkeypatch, ko, db)

    async def _perm(*_a, **_k):
        return dict(SA)
    monkeypatch.setattr(ko, "require_perm", _perm)
    db.marketing_creator_sessions.docs.append({"id": "k1", "account_id": TTK, "date": "2026-08-01",
                                               "revenue": 289_427, "orders": 5})
    db.marketing_sales_data.docs.append(rekap_doc(TTK, "2026-08-01", 289_427, 5, rtype="live",
                                                  source="livehost_creator_auto"))
    run(ko.delete_session("k1", Req()))
    live_doc = next(d for d in db.marketing_sales_data.docs
                    if d["account_id"] == TTK and d["revenue_type"] == "live")
    assert live_doc["metrics"]["revenue"] == 0                            # dulu tetap 289.427


# ── M-08 detail toko · M-12 Pusat Laporan · M-13 laporan eksekutif ────────────────────────────
def test_m08_riwayat_sales_toko_menghormati_limit_dan_membuang_data_contoh(db, monkeypatch):
    import routes.marketing_sales as ms
    patch_route(monkeypatch, ms, db)
    db.marketing_sales_data.docs.append(rekap_doc(SHP, "2026-08-20", 9_999_999, _seed_origin=True))
    rows = run(ms.get_account_sales_data(SHP, Req(), date_from="2026-08-01", date_to=None,
                                         revenue_type="total", limit=3))
    assert len(rows) == 3 and all(r.get("_seed_origin") is not True for r in rows)


def test_m12_pusat_laporan_marketing_memakai_definisi_omzet_resmi(db, monkeypatch):
    import routes.rahaza_reports as rr
    patch_route(monkeypatch, rr, db)
    db.marketing_orders.docs += [
        {"id": "b1", "account_id": TTK, "order_id": "B1", "status": "cancelled", "revenue": 1_000_000,
         "order_date": datetime(2026, 8, 1, tzinfo=timezone.utc)},
        {"id": "b2", "account_id": TTK, "order_id": "B2", "status": "new", "revenue": 2_000_000,
         "order_date": datetime(2026, 8, 1, tzinfo=timezone.utc)}]
    out = run(rr.reports_hub_summary(Req(query={"category": "marketing", "date_from": "2026-08-01",
                                                 "date_to": "2026-08-31"})))
    omzet = next(k for k in out["kpis"] if k["label"] == "Omzet Periode")["value"]
    assert omzet == 11_727_142                                            # dulu Σ semua pesanan


def test_m13_laporan_eksekutif_omzet_live_dari_pesanan(db):
    import routes.dewi_executive_report as ex
    out = run(ex._marketing_kpis(db, 2026, 8))
    assert out["live_revenue_rp"] == 289_427                              # dulu 0 (field mati)


def test_m19_ai_harga_tidak_membaca_field_mati():
    from pathlib import Path
    src = Path(__file__).resolve().parents[2].joinpath(
        "routes", "marketing_advanced_ai_routes.py").read_text(encoding="utf-8")
    assert '"$total_amount"' not in src and "baca_pesanan" in src and "rincian_item" in src


# ── layar ─────────────────────────────────────────────────────────────────────────────────────
def _fe(rel):
    from pathlib import Path
    return Path(__file__).resolve().parents[3].joinpath("frontend", "src", *rel.split("/")).read_text(
        encoding="utf-8")


def test_m14_form_ubah_target_membaca_field_ringkasan():
    src = _fe("components/erp/marketing/AccountTargetsModule.jsx")
    assert "existingTarget?.revenue ?? existingTarget?.revenue_target" in src


def test_m22_unduh_semua_pesanan_page_size_maks_100():
    src = _fe("components/erp/marketing/UnifiedOrdersDashboard.jsx")
    assert "page_size: 200" not in src and "page_size: 100" in src


def test_m08_detail_toko_kpi_bulan_berjalan():
    src = _fe("components/erp/marketing/AccountDetailPage.jsx")
    assert "sales?limit=60" not in src and "r.date >= awalBulan" in src


def test_m26_rentang_30_hari_termasuk_hari_ini():
    # 14 Nov 2026: argumen kedua `now` (uji tanggal tetap) — rumusnya tetap N hari termasuk hari ini.
    assert "daysAgoWIB(days - 1" in _fe("components/erp/PeriodSelector.jsx")


def test_pola_omzet_kreator_memakai_definisi_baku(db):
    """Audit §8 — omzet kreator dulu hanya membuang status "cancelled" (ejaan "canceled",
    pesanan belum dibayar, dan data contoh ikut)."""
    from core import creator_weekly_report as cw
    d0 = datetime(2026, 8, 3, 10, tzinfo=timezone.utc)
    db.marketing_orders.docs += [
        {"id": "c1", "creator_id": "K1", "status": "completed", "order_date": d0, "revenue_product": 100.0},
        {"id": "c2", "creator_id": "K1", "status": "canceled", "order_date": d0, "revenue_product": 900.0},
        {"id": "c3", "creator_id": "K1", "status": "new", "order_date": d0, "revenue_product": 900.0},
        {"id": "c4", "creator_id": "K1", "status": "completed", "order_date": d0, "revenue_product": 900.0,
         "_seed_origin": True}]
    out = run(cw._order_revenue(db, ["K1"], {"start": "2026-08-01", "end": "2026-08-07"}))
    assert out["K1"] == {"orders": 1, "revenue": 100.0}


def test_q3_tren_iklan_harian_dibagi_rata(db, monkeypatch):
    import routes.marketing_ads_routes as ma
    import utils.waktu as wk
    from datetime import date
    patch_route(monkeypatch, ma, db)
    monkeypatch.setattr(wk, "today_wib", lambda: date(2026, 8, 31))
    db.marketing_ads_data.docs.append({
        "id": "cpc1", "account_id": SHP, "campaign_name": "Iklan A", "source_report": "shopee_ads_cpc",
        "date": "2026-08-01", "period_start": "2026-08-01", "period_end": "2026-08-31",
        "spend": 310_000, "revenue": 620_000})
    trend = run(ma.performance_trend(Req(), days=30))["data"]["trend"]
    assert len(trend) == 30 and {t["spend"] for t in trend} == {10_000.0}   # dulu 310.000 di 1 Agt
