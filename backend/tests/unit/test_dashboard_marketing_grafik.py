"""Dashboard Marketing — grafik iklan, anggaran, target, live (owner 13 Nov 2026).

Keluhan owner: "untuk dashboard marketing saya lihat grafik hanya sales saja padahal bisa ada ads,
anggaran realisasi dll." Aturan owner yang dijaga uji ini: grafik yang menyesatkan lebih buruk
daripada tidak ada, jadi angka setiap grafik HARUS sama dengan angka layar sumbernya untuk
periode & toko yang sama:

* tren omzet/live  = kartu Dashboard (`/dashboard/overview` summary);
* batang iklan     = kartu Laporan Marketing › Performa iklan (`/ads/summary`);
* anggaran bulanan = Target & Anggaran › Siklus (baris per toko di `/cycle/overview`);
* anggaran mingguan semua toko = jumlah layar Anggaran tiap toko (`/budget/summary?account_id=`).

Semua data di sini SINTETIS.
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from _mkt_uji import DB, PIC, Req, acc, patch_route, rekap_doc, run  # noqa: E402

TTK, SHP = "TTK-01", "SHP-01"


@pytest.fixture
def db():
    d = DB()
    d.marketing_platform_accounts.docs += [acc(TTK, pic_user_id=PIC["id"]), acc(SHP, platform="shopee")]
    # Bulan Marketing Agustus 2026 = 26 Jul – 25 Agt
    d.marketing_sales_data.docs += [
        rekap_doc(TTK, "2026-07-28", 2_000_000, 20, live=500_000),
        rekap_doc(TTK, "2026-08-01", 6_855_287, 72, live=289_427),
        rekap_doc(SHP, "2026-08-05", 1_071_855, 20),
        rekap_doc(SHP, "2026-08-11", 3_800_000, 30),
        # catatan kerja sinkron shift host — BUKAN omzet live resmi (Q-2)
        rekap_doc(TTK, "2026-08-01", 578_854, 10, rtype="live", source="livehost_creator_auto"),
        # data contoh tidak boleh ikut
        rekap_doc(SHP, "2026-08-12", 9_999_999, 99, _seed_origin=True, id="contoh"),
    ]
    d.marketing_ads_data.docs += [
        # laporan CPC Shopee berperiode → dibagi rata per hari (Q-3)
        {"id": "cpc", "account_id": SHP, "campaign_name": "CPC Agustus", "source_report": "shopee_ads_cpc",
         "period_start": "2026-08-01", "period_end": "2026-08-31", "date": "2026-08-01",
         "spend": 310_000, "revenue": 930_000},
        # entri harian bertanggal datetime
        {"id": "a1", "account_id": SHP, "campaign_name": "Flash", "ad_platform": "meta_ads",
         "date": datetime(2026, 8, 11, tzinfo=timezone.utc), "spend": 100_000, "revenue": 250_000},
        {"id": "a2", "account_id": TTK, "campaign_name": "Live boost", "ad_platform": "tiktok_ads",
         "date": "2026-08-12", "spend": 40_000, "revenue": 0},
        {"id": "contoh", "account_id": TTK, "campaign_name": "Contoh", "date": "2026-08-12",
         "spend": 5_000_000, "revenue": 1, "_seed_origin": True},
    ]
    d.marketing_account_targets.docs.append({"id": "t1", "account_id": TTK, "year": 2026, "month": 8,
                                             "revenue_target": 10_000_000, "orders_target": 100})
    return d


def _jumlah(rows, key):
    return sum(float(r.get(key) or 0) for r in rows)


# ── 1. tren omzet & live = kartu ─────────────────────────────────────────────────────────────
def test_overview_harian_dan_per_toko_sama_dengan_kartu(db, monkeypatch):
    import routes.marketing_dashboard as md
    patch_route(monkeypatch, md, db)
    ov = run(md.get_dashboard_overview(Req(), date_from="2026-07-26", date_to="2026-08-25", account_id=None))
    s = ov["summary"]
    assert s["total_revenue"] == 2_000_000 + 6_855_287 + 1_071_855 + 3_800_000
    assert s["total_revenue_live"] == 500_000 + 289_427                 # bukan 578.854 catatan shift
    assert _jumlah(ov["daily"], "revenue") == s["total_revenue"]
    assert _jumlah(ov["daily"], "revenue_live") == s["total_revenue_live"]
    assert sum(int(d["orders"]) for d in ov["daily"]) == s["total_orders"]
    assert _jumlah(ov["per_account"], "revenue") == s["total_revenue"]
    assert _jumlah(ov["per_account"], "revenue_live") == s["total_revenue_live"]
    assert [d["date"] for d in ov["daily"]] == sorted(d["date"] for d in ov["daily"])
    per = {a["account_id"]: a for a in ov["per_account"]}
    assert per[TTK]["revenue"] == 8_855_287 and per[SHP]["revenue"] == 4_871_855
    assert ov["live"]["definition"]                                       # definisi resmi ikut dikirim


def test_overview_satu_toko(db, monkeypatch):
    import routes.marketing_dashboard as md
    patch_route(monkeypatch, md, db)
    ov = run(md.get_dashboard_overview(Req(), date_from="2026-07-26", date_to="2026-08-25", account_id=SHP))
    assert ov["summary"]["total_revenue"] == 4_871_855
    assert ov["summary"]["active_accounts"] == 1
    assert [a["account_id"] for a in ov["per_account"]] == [SHP]
    assert _jumlah(ov["daily"], "revenue") == 4_871_855


def test_overview_toko_di_luar_lingkup_ditolak(db, monkeypatch):
    import routes.marketing_dashboard as md
    patch_route(monkeypatch, md, db, user=PIC)
    ov = run(md.get_dashboard_overview(Req(PIC), date_from="2026-07-26", date_to="2026-08-25", account_id=None))
    assert [a["account_id"] for a in ov["per_account"]] == [TTK]          # staf hanya tokonya
    with pytest.raises(HTTPException) as e:
        run(md.get_dashboard_overview(Req(PIC), date_from="2026-07-26", date_to="2026-08-25", account_id=SHP))
    assert e.value.status_code == 403


# ── 2. batang iklan harian = kartu Performa iklan ───────────────────────────────────────────
@pytest.mark.parametrize("toko", [None, SHP, TTK])
@pytest.mark.parametrize("rentang", [("2026-07-26", "2026-08-25"), ("2026-08-10", "2026-08-16")])
def test_tren_iklan_sama_dengan_ringkasan(db, monkeypatch, toko, rentang):
    import routes.marketing_ads_routes as ma
    patch_route(monkeypatch, ma, db)
    d0, d1 = rentang
    ring = run(ma.ads_summary(Req(), account_id=toko, date_from=d0, date_to=d1))["data"]
    tren = run(ma.performance_trend(Req(), days=30, date_from=d0, date_to=d1, account_id=toko))["data"]["trend"]
    assert round(_jumlah(tren, "spend")) == round(ring["total_spend"])
    assert round(_jumlah(tren, "revenue")) == round(ring["total_revenue"])
    assert all(d0 <= t["date"] <= d1 for t in tren)
    assert ring["total_spend"] < 5_000_000                                # data contoh tidak ikut


def test_tren_iklan_minggu_senin_dibagi_rata(db, monkeypatch):
    import routes.marketing_ads_routes as ma
    patch_route(monkeypatch, ma, db)
    tren = run(ma.performance_trend(Req(), days=30, date_from="2026-08-10", date_to="2026-08-16",
                                    account_id=SHP))["data"]["trend"]
    assert len(tren) == 7                                                 # CPC dibagi rata 7 hari
    hari11 = next(t for t in tren if t["date"] == "2026-08-11")
    assert round(hari11["spend"]) == 10_000 + 100_000                     # 310.000/31 + entri harian
    assert round(_jumlah(tren, "spend")) == 70_000 + 100_000


def test_tren_iklan_tanpa_rentang_tetap_n_hari(db, monkeypatch):
    import routes.marketing_ads_routes as ma
    patch_route(monkeypatch, ma, db)
    out = run(ma.performance_trend(Req(), days=30, date_from=None, date_to=None, account_id=None))
    assert out["metadata"]["days"] == 30


def test_tren_iklan_toko_di_luar_lingkup_kosong(db, monkeypatch):
    import routes.marketing_ads_routes as ma
    patch_route(monkeypatch, ma, db, user=PIC)
    tren = run(ma.performance_trend(Req(PIC), days=30, date_from="2026-07-26", date_to="2026-08-25",
                                    account_id=SHP))["data"]["trend"]
    assert tren == []


# ── 3. anggaran per kategori = jumlah tabel per toko (Siklus) ───────────────────────────────
def test_siklus_total_anggaran_per_kategori_sama_dengan_jumlah_toko(db):
    from core import marketing_cycle as C
    db.marketing_budgets.docs += [
        {"id": "b1", "account_id": TTK, "period": "2026-08",
         "budget_by_category": {"ads": 50_000, "kol": 1_000_000, "sample": 200_000}},
        {"id": "b2", "account_id": SHP, "period": "2026-08", "budget_by_category": {"ads": 300_000}},
    ]
    db.marketing_spend_entries.docs.append({"id": "s1", "account_id": SHP, "period": "2026-08",
                                            "category": "sample", "amount": 75_000})
    ov = run(C.cycle_overview(db, "2026-08", today=datetime(2026, 9, 2, tzinfo=timezone.utc)))
    tot = {c["category"]: c for c in ov["totals"]["budget_categories"]}
    assert [c["category"] for c in ov["totals"]["budget_categories"]] == list(C.CATEGORIES)
    for k in C.CATEGORIES:
        rows = [next(c for c in r["budget"]["categories"] if c["category"] == k) for r in ov["rows"]]
        assert tot[k]["plan"] == round(_jumlah(rows, "plan"), 2)
        assert tot[k]["spend"] == round(_jumlah(rows, "spend"), 2)
    assert round(_jumlah(tot.values(), "plan"), 2) == ov["totals"]["total_plan"]
    assert round(_jumlah(tot.values(), "spend"), 2) == ov["totals"]["total_spend"]
    assert tot["ads"]["plan"] == 350_000 and tot["ads"]["mode"] == "auto"
    assert tot["sample"]["spend"] == 75_000 and tot["sample"]["mode"] == "manual"
    # iklan 26 Jul–25 Agt: CPC 25/31 × 310.000 + 100.000 + 40.000
    assert round(tot["ads"]["spend"]) == round(310_000 * 25 / 31 + 140_000)


def test_jumlah_kategori_tanpa_rencana_dan_lewat_rencana():
    from core.marketing_cycle import sum_budget_categories
    out = {c["category"]: c for c in sum_budget_categories([
        [{"category": "ads", "plan": 100, "spend": 150}, {"category": "kol", "plan": 0, "spend": 0}],
        [{"category": "ads", "plan": 100, "spend": 0}, {"category": "diskon", "plan": 0, "spend": 20},
         {"category": "bukan_kategori", "plan": 999, "spend": 999}],
    ])}
    assert out["ads"]["plan"] == 200 and out["ads"]["used_pct"] == 75.0 and out["ads"]["status"] == "under"
    assert out["kol"]["used_pct"] == 0.0
    assert out["diskon"]["used_pct"] == 100.0 and out["diskon"]["status"] == "over"
    assert "bukan_kategori" not in out


# ── 4. anggaran mingguan semua toko = jumlah layar Anggaran per toko ────────────────────────
def test_anggaran_mingguan_semua_toko_sama_dengan_jumlah_per_toko(db, monkeypatch):
    import routes.marketing_budget as mb
    patch_route(monkeypatch, mb, db)
    minggu = "2026-08-10"                                                 # Senin
    db.marketing_budgets.docs += [
        {"id": "w1", "account_id": TTK, "period": minggu, "budget_by_category": {"ads": 20_000}},
        {"id": "w2", "account_id": SHP, "period": minggu, "budget_by_category": {"ads": 90_000, "sample": 10_000}},
    ]
    semua = run(mb.budget_summary(Req(), account_id=None, period=minggu))
    satu = [run(mb.budget_summary(Req(), account_id=a, period=minggu)) for a in (TTK, SHP)]
    assert semua["accounts"] == 2 and semua["budget_exists"] == 2
    assert semua["date_from"] == "2026-08-10" and semua["date_to"] == "2026-08-16"
    for c in semua["categories"]:
        per = [next(x for x in s["categories"] if x["category"] == c["category"]) for s in satu]
        assert c["budget"] == round(_jumlah(per, "budget"), 2)
        assert c["spend"] == round(_jumlah(per, "spend"), 2)
    assert semua["total_budget"] == round(sum(s["total_budget"] for s in satu), 2) == 120_000
    assert semua["total_spend"] == round(sum(s["total_spend"] for s in satu), 2)
    ads = next(c for c in semua["categories"] if c["category"] == "ads")
    assert round(ads["spend"]) == 70_000 + 100_000 + 40_000              # CPC 7/31 + harian SHP + TTK


def test_anggaran_semua_toko_hanya_toko_staf(db, monkeypatch):
    import routes.marketing_budget as mb
    patch_route(monkeypatch, mb, db, user=PIC)
    out = run(mb.budget_summary(Req(PIC), account_id=None, period="2026-08-10"))
    assert out["accounts"] == 1
    ads = next(c for c in out["categories"] if c["category"] == "ads")
    assert ads["spend"] == 40_000                                         # hanya iklan TTK
