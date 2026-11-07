"""Uji agen DATA Asisten AI (Tahap A, 7 Nov 2026).

Satu definisi omzet (`core.ukuran_penjualan`), perbaikan bug angka Marketing audit §3.C
(1–11, 13, 15), privasi usulan AI impor, endpoint `/api/marketing/analitik/*`, dan alat AI
(kontrak A). Hermetik: Mongo palsu in-memory, tanpa jaringan, tanpa API Anthropic.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import csv
import importlib
import importlib.util
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import _fake_mongo as fm  # noqa: E402
from _fake_mongo import FakeCollection, FakeDB, FakeRequest  # noqa: E402

from core import marketing_daily_rollup as rollup  # noqa: E402
from core import marketing_import_engine as eng  # noqa: E402
from core import marketing_returns as mret  # noqa: E402
from core import ukuran_penjualan as U  # noqa: E402
from core.marketing_import_schema import get_source_type, source_type_catalog  # noqa: E402
from utils.waktu import today_wib  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════════
# Mongo palsu + agregasi secukupnya ($match/$group/$sort/$limit)
# ══════════════════════════════════════════════════════════════════════════════
def _val(doc, expr):
    if isinstance(expr, str) and expr.startswith("$"):
        v = fm._get(doc, expr[1:])
        return None if v is fm._MISSING else v
    if isinstance(expr, dict) and "$ifNull" in expr:
        a, b = expr["$ifNull"]
        v = _val(doc, a)
        return v if v is not None else _val(doc, b)
    return expr


def _pipeline(docs, pipeline):
    docs = [copy.deepcopy(d) for d in docs]
    for stage in pipeline:
        if "$match" in stage:
            docs = [d for d in docs if fm.match(d, stage["$match"])]
        elif "$group" in stage:
            g = stage["$group"]
            idx = g["_id"]
            groups: dict = {}
            for d in docs:
                if idx is None:
                    key = None
                elif isinstance(idx, dict):
                    key = tuple((k, _val(d, v)) for k, v in idx.items())
                else:
                    key = _val(d, idx)
                acc = groups.setdefault(key, {"_id": dict(key) if isinstance(idx, dict) else key})
                for f, op in g.items():
                    if f == "_id":
                        continue
                    (o, e), = op.items()
                    if o == "$sum":
                        acc[f] = acc.get(f, 0) + (e if isinstance(e, (int, float)) else (_val(d, e) or 0))
                    elif o == "$push":
                        acc.setdefault(f, []).append(_val(d, e))
            docs = list(groups.values())
        elif "$sort" in stage:
            for k, direction in reversed(list(stage["$sort"].items())):
                docs.sort(key=lambda d: (d.get(k) is None, d.get(k)), reverse=direction == -1)
        elif "$limit" in stage:
            docs = docs[:stage["$limit"]]
    return docs


class _AggCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs if not length else self._docs[:length]

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class AggCollection(FakeCollection):
    def aggregate(self, pipeline, **_kw):
        return _AggCursor(_pipeline(self.docs, pipeline))

    async def index_information(self):
        return {}


class AggDB(FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = AggCollection(name)
        return self._cols[name]


ADMIN = {"id": "u-admin", "role": "admin", "email": "admin@uji"}
STAF_A1 = {"id": "u-staf", "role": "staff_marketing", "email": "staf@uji"}


def _auth(user):
    async def _f(_req=None, *a, **k):
        return user
    return _f


def _acc(aid, platform="shopee", **kw):
    return {"id": aid, "account_name": f"Toko {aid}", "account_code": aid, "platform": platform,
            "status": "active", "revenue_basis": "produk_setelah_diskon", **kw}


def _daily(aid, date, revenue, orders, *, rtype="total", returned=0.0, cancelled=0, seed=False,
           updated="2026-10-31T00:00:00"):
    d = {"id": f"sd-{aid}-{date}-{rtype}-{revenue}", "account_id": aid, "date": date, "revenue_type": rtype,
         "metrics": {"revenue": revenue, "revenue_product": revenue, "orders": orders, "units": orders * 2,
                     "buyers": orders},
         "fulfillment": {"returned_revenue_product": returned, "returned_value": returned,
                         "returned_orders": 1 if returned else 0, "cancelled_orders": cancelled},
         "revenue_basis": "produk_setelah_diskon", "source": "orders_auto", "updated_at": updated}
    if seed:
        d["_seed_origin"] = True
    return d


def _order(oid, status, rev, *, acc="A1", date="2026-10-05", **kw):
    return {"id": f"doc-{oid}", "order_id": oid, "account_id": acc, "status": status,
            "order_date": datetime.fromisoformat(f"{date}T10:00:00+00:00"),
            "revenue_product": rev, "quantity": 1, **kw}


# ══════════════════════════════════════════════════════════════════════════════
# 1. DEFINISI OMZET (keputusan owner no. 7)
# ══════════════════════════════════════════════════════════════════════════════
SAMPEL_PESANAN = [
    _order("P1", "paid", 100),
    _order("P2", "cancelled", 100),
    _order("P3", "new", 100),                                         # belum dibayar
    _order("P4", "new", 100, paid_at="2026-10-05T10:05:00"),           # sudah dibayar
    _order("P5", "new", 100, _source_type="manual_input"),             # input staf
    _order("P6", "new", 100, status_assumed=True),                     # impor lama tanpa status
    _order("P7", "new", 100, platform_status="payment_verified"),      # webhook sudah bayar
    _order("P8", "returned", 100),                                     # retur: tetap omzet bruto
    _order("P9", "completed", 100, _seed_origin=True),                 # data contoh
    _order("P10", "canceled", 100),
    {"id": "doc-P11", "account_id": "A1", "revenue_product": 100},     # tanpa status
]


def test_definisi_omzet_batal_belum_bayar_contoh_keluar_retur_tetap():
    ikut = [o["order_id"] if "order_id" in o else o["id"] for o in SAMPEL_PESANAN if U.dihitung_omzet(o)]
    assert ikut == ["P1", "P4", "P5", "P6", "P7", "P8", "doc-P11"]
    assert U.belum_dibayar(SAMPEL_PESANAN[2]) and not U.belum_dibayar(SAMPEL_PESANAN[3])


def test_saringan_mongo_setara_dengan_predikat_python():
    q = U.filter_dihitung_omzet()
    for o in SAMPEL_PESANAN:
        assert fm.match(o, q) == U.dihitung_omzet(o), o.get("order_id")


def test_rekap_harian_tidak_menghitung_pesanan_belum_dibayar_bug8():
    orders = [_order("A", "paid", 100000), _order("B", "new", 50000), _order("C", "cancelled", 70000),
              _order("D", "returned", 30000)]
    s = rollup.summarize_orders(orders)
    assert s["revenue_product"] == 130000 and s["orders"] == 2           # paid + returned
    assert s["fulfillment"]["unpaid_orders"] == 1 and s["fulfillment"]["unpaid_value"] == 50000
    assert s["fulfillment"]["cancelled_orders"] == 1
    assert s["fulfillment"]["cancellation_rate"] == round(1 / 3 * 100, 2)  # penyebut tanpa belum bayar
    split = mret.split_from_orders(orders)
    assert split["gross_revenue_product"] == 130000 and split["returned_revenue_product"] == 30000


def test_retur_dilaporkan_terpisah_dan_contoh_dibuang():
    db = FakeDB()
    db.marketing_sales_data.docs += [_daily("A1", "2026-10-01", 1000.0, 10, returned=200.0, cancelled=2),
                                     _daily("A1", "2026-10-02", 500.0, 5),
                                     _daily("A1", "2026-10-03", 9999.0, 99, seed=True)]
    t = run(U.ringkas_omzet(db, [_acc("A1")], "2026-10-01", "2026-10-31"))["total"]
    assert t["omzet"] == 1500 and t["pesanan"] == 15 and t["retur_nilai"] == 200
    assert t["omzet_setelah_retur"] == 1300 and t["batal_pesanan"] == 2 and t["aov"] == 100


def test_rekap_kembar_dipakai_yang_terbaru_dan_disebut():
    db = FakeDB()
    db.marketing_sales_data.docs += [_daily("A1", "2026-10-01", 1000.0, 10, updated="2026-10-01T01:00:00"),
                                     _daily("A1", "2026-10-01", 1200.0, 12, updated="2026-10-02T01:00:00")]
    rows, dup = run(U.baca_rekap(db, ["A1"], "2026-10-01", "2026-10-01"))
    assert dup == 1 and len(rows) == 1 and rows[0]["omzet"] == 1200


# ══════════════════════════════════════════════════════════════════════════════
# 2. BUG #1 / #9 — tanpa batas 500 baris; semua layar sepakat dengan /analitik
# ══════════════════════════════════════════════════════════════════════════════
def _sembilan_toko_sebulan():
    db = AggDB()
    accs = [_acc(f"T{i}", "shopee" if i < 5 else "tiktok") for i in range(9)]
    db.marketing_platform_accounts.docs += accs
    total = 0.0
    for i, a in enumerate(accs):
        for d in range(1, 32):
            date = f"2026-10-{d:02d}"
            rev = 100000.0 + i * 1000 + d
            total += rev
            db.marketing_sales_data.docs.append(_daily(a["id"], date, rev, 3))
            db.marketing_sales_data.docs.append(_daily(a["id"], date, rev / 4, 1, rtype="live"))
    return db, total


def test_dashboard_laporan_performa_target_dan_analitik_sepakat_tanpa_batas_500(monkeypatch):
    from routes import marketing_analitik as ma
    from routes import marketing_dashboard as dash
    from routes import marketing_reports as rep
    from routes import marketing_sales_performance_routes as perf
    from routes import marketing_targets as tgt
    db, total = _sembilan_toko_sebulan()
    assert len(db.marketing_sales_data.docs) == 558          # > 500: dulu terpotong
    for mod in (dash, rep, perf, ma, tgt):
        monkeypatch.setattr(mod, "get_db", lambda: db)
        if hasattr(mod, "require_auth"):
            monkeypatch.setattr(mod, "require_auth", _auth(ADMIN))
    req = FakeRequest()
    req.state.user = ADMIN
    d = run(dash.get_dashboard_overview(req, date_from="2026-10-01", date_to="2026-10-31"))
    p = run(perf.performance_overview(req, start_date="2026-10-01", end_date="2026-10-31", date_from=None,
                                      date_to=None, platform=None, account=None, account_id=None))
    m = run(rep.monthly_report(req, year=2026, month=10))
    t = run(tgt.monthly_summary(req, year=2026, month=10))
    a = run(ma.analitik_penjualan(req, dari="2026-10-01", sampai="2026-10-31", kelompok="toko",
                                  bandingkan="tidak", toko_id=None, limit=None))
    assert d["summary"]["total_revenue"] == round(total)
    assert d["summary"]["total_orders"] == 9 * 31 * 3
    assert round(p["data"]["total_revenue"]) == round(total) == round(a["total"]["omzet"])
    assert round(m["summary"]["rev_actual"]) == round(total) == round(t["summary"]["rev_actual"])
    assert p["data"]["total_orders"] == a["total"]["pesanan"] == m["summary"]["ord_actual"]
    assert sum(r["omzet"] for r in a["kelompok"]["baris"]) == pytest.approx(a["total"]["omzet"], abs=9)


# ══════════════════════════════════════════════════════════════════════════════
# 3. BUG #2 — produk terlaris per item katalog, bukan omzet pesanan per baris
# ══════════════════════════════════════════════════════════════════════════════
def _db_produk():
    db = FakeDB()
    db.marketing_platform_accounts.docs += [_acc("A1")]
    db.marketing_catalog_items.docs += [
        {"id": "IT-1", "name": "Gamis Uji", "sku": "GU-01", "model_id": "M1", "fg_material_id": "FG1", "hpp": 40000},
        {"id": "IT-2", "name": "Gamis Uji", "sku": "GU-02", "model_id": "M1", "fg_material_id": "FG2", "hpp": 0},
        {"id": "IT-3", "name": "Khimar Uji", "sku": "KU-01", "model_id": "M2", "fg_material_id": "FG3", "hpp": 20000}]
    # pesanan MANUAL 3 baris (bentuk layar Order Terpadu: qty/price, tanpa subtotal SKU)
    db.marketing_orders.docs.append({
        **_order("M-1", "delivered", 0, _source_type="manual_input"), "revenue_product": 350000,
        "items": [{"catalog_item_id": "IT-1", "qty": 2, "price": 100000, "sku_code": "GU-01"},
                  {"catalog_item_id": "IT-2", "qty": 1, "price": 100000, "sku_code": "GU-02"},
                  {"catalog_item_id": "IT-3", "qty": 1, "price": 50000, "sku_code": "KU-01"}]})
    db.marketing_orders.docs.append({
        **_order("I-1", "completed", 80000), "items": [
            {"catalog_item_id": "IT-1", "quantity": 1, "sku_subtotal_after_discount": 80000,
             "hpp_snapshot": 38000, "seller_sku": "GU-01"}]})
    db.marketing_orders.docs.append({**_order("I-2", "new", 99999), "items": [
        {"catalog_item_id": "IT-3", "quantity": 9, "sku_subtotal_after_discount": 99999}]})  # belum bayar
    return db


def test_produk_terlaris_per_item_katalog_tanpa_dobel_bug2(monkeypatch):
    from routes import marketing_sales_performance_routes as perf
    db = _db_produk()
    monkeypatch.setattr(perf, "get_db", lambda: db)
    monkeypatch.setattr(perf, "require_auth", _auth(ADMIN))
    monkeypatch.setattr(perf, "today_wib", lambda: datetime(2026, 10, 20).date())
    out = run(perf.top_products(FakeRequest(), days=30, limit=10, account_id=None, platform=None))
    rows = {r["catalog_item_id"]: r for r in out["data"]["products"]}
    assert rows["IT-1"]["total_revenue"] == 280000 and rows["IT-1"]["total_qty"] == 3   # 200.000 + 80.000
    assert rows["IT-2"]["total_revenue"] == 100000 and rows["IT-3"]["total_revenue"] == 50000
    assert sum(r["total_revenue"] for r in out["data"]["products"]) == 430000          # dulu 3 × 350.000 + …
    assert rows["IT-1"]["order_count"] == 2


def test_analitik_produk_marjin_dari_hpp_snapshot_dan_cakupan():
    db = _db_produk()
    out = run(U.analitik_produk(db, [_acc("A1")], "2026-10-01", "2026-10-31", cara="katalog"))
    r = {x["kunci"]: x for x in out["baris"]}
    # IT-1: 2 unit HPP katalog 40.000 + 1 unit snapshot 38.000 = 118.000; omzet 280.000
    assert r["item:IT-1"]["hpp"] == 118000 and r["item:IT-1"]["laba_kotor"] == 162000
    assert r["item:IT-2"]["hpp"] is None and r["item:IT-2"]["hpp_cakupan_persen"] == 0.0
    assert out["total"]["hpp_cakupan_persen"] == 80.0                                  # 4 dari 5 unit
    model = run(U.analitik_produk(db, [_acc("A1")], "2026-10-01", "2026-10-31", cara="produk"))
    assert [x["label"] for x in model["baris"]] == ["Gamis Uji", "Khimar Uji"]


# ══════════════════════════════════════════════════════════════════════════════
# 4. BUG #3 — konteks AI marketing memakai tanggal pesanan & lingkup toko
# ══════════════════════════════════════════════════════════════════════════════
def test_konteks_ai_marketing_pakai_rekap_dan_lingkup_toko_bug3():
    from routes import marketing_ai_insights_routes as mi
    db = AggDB()
    db.marketing_platform_accounts.docs += [_acc("A1", assigned_staff=["u-staf"]), _acc("A2")]
    d = (today_wib() - timedelta(days=2)).isoformat()
    db.marketing_sales_data.docs += [_daily("A1", d, 700000.0, 7), _daily("A2", d, 900000.0, 9)]
    db.marketing_orders.docs += [_order("X1", "paid", 1, acc="A1"), _order("X2", "paid", 1, acc="A2")]
    sq = run(mi._scope.scope_filter(db, STAF_A1, {}))
    ctx = run(mi._get_orders_context(db, STAF_A1, sq))
    assert ctx["revenue_30d"] == 700000 and ctx["recent_30d"] == 7
    assert ctx["daily_trend"] == [{"date": d, "orders": 7, "revenue": 700000.0}]
    assert ctx["status_counts"] == {"paid": 1} and ctx["total"] == 1
    src = Path(BACKEND, "routes", "marketing_ai_insights_routes.py").read_text(encoding="utf-8")
    assert '"$total_amount"' not in src and '"$created_at"' not in src
    assert src.count("_get_orders_context(db, user, sq)") == 3


# ══════════════════════════════════════════════════════════════════════════════
# 5. BUG #4 — data contoh tidak lahir di produksi + migrasi pembersih
# ══════════════════════════════════════════════════════════════════════════════
def test_seeder_iklan_live_kesehatan_mati_tanpa_flag_demo(monkeypatch):
    from routes import marketing_account_health_routes as mh
    from routes import marketing_ads_routes as ads
    from routes import marketing_live_sessions_routes as ml
    monkeypatch.delenv("ALLOW_DEMO_SEED", raising=False)
    db = FakeDB()
    for mod in (ads, ml, mh):
        monkeypatch.setattr(mod, "get_db", lambda: db)
    run(ads.seed_ads_if_empty())
    run(ml.seed_live_if_empty())
    run(mh.seed_health_if_empty())
    assert db.marketing_ads_data.docs == [] and db.marketing_live_sessions.docs == []
    assert db.marketing_account_health.docs == []
    assert '"_seed_origin": True' in Path(BACKEND, "routes", "marketing_account_health_routes.py").read_text(
        encoding="utf-8")


def test_handler_iklan_tidak_memanggil_seeder():
    tree = ast.parse(Path(BACKEND, "routes", "marketing_ads_routes.py").read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.AsyncFunctionDef) and fn.name != "seed_ads_if_empty":
            called = {getattr(n.func, "id", getattr(n.func, "attr", "")) for n in ast.walk(fn)
                      if isinstance(n, ast.Call)}
            assert "seed_ads_if_empty" not in called, fn.name


def _mig(name):
    p = BACKEND / "scripts" / "migrations" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mig_{name}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migrasi_hapus_data_contoh_pratinjau_lalu_tulis(capsys):
    mig = _mig("2026_11_08_hapus_data_contoh_marketing")
    db = FakeDB()
    db.marketing_ads_data.docs += [{"id": "ad1", "_seed_origin": True}, {"id": "ad2", "spend": 5}]
    db.marketing_live_sessions.docs += [{"id": "ls1", "_seed_origin": True}]
    db.marketing_catalog_items.docs += [{"id": "ci1", "_seed_origin": True}]
    t = datetime(2026, 7, 6, tzinfo=timezone.utc)
    health_seed = {k: None for k in mig._HEALTH_SEED_KEYS} | {"id": "h1", "notes": [], "created_at": t,
                                                              "snapshot_date": t}
    db.marketing_account_health.docs += [health_seed, {"id": "h2", "snapshot_date": t, "_import_session_id": "s"}]
    pre = run(mig.run(db, apply=False))
    assert pre["transaksi"]["marketing_ads_data"]["contoh"] == 1 and pre["dihapus"] == 0
    assert pre["kesehatan_mirip_contoh"] == 1 and len(db.marketing_ads_data.docs) == 2
    out = run(mig.run(db, apply=True))
    assert out["dihapus"] == 2 and [d["id"] for d in db.marketing_ads_data.docs] == ["ad2"]
    assert len(db.marketing_catalog_items.docs) == 1 and len(db.marketing_account_health.docs) == 2
    run(mig.run(db, apply=True, health_unmarked=True))
    assert [d["id"] for d in db.marketing_account_health.docs] == ["h2"]
    again = run(mig.run(db, apply=False))
    assert again["transaksi"]["marketing_ads_data"]["contoh"] == 0                 # idempoten


# ══════════════════════════════════════════════════════════════════════════════
# 6. BUG #5 / #6 — ringkasan iklan bersaring tanggal & toko; tanggal campur terbaca
# ══════════════════════════════════════════════════════════════════════════════
def _ads_db():
    db = AggDB()
    db.marketing_platform_accounts.docs += [_acc("A1", assigned_staff=["u-staf"]), _acc("A2", "tiktok")]
    dt = lambda s: datetime.fromisoformat(f"{s}T08:00:00+00:00")  # noqa: E731
    db.marketing_ads_data.docs += [
        {"id": "a1", "account_id": "A1", "platform": "shopee", "date": dt("2026-10-03"), "spend": 100.0,
         "revenue": 400.0, "impressions": 1000, "clicks": 10, "conversions": 2},
        {"id": "a2", "account_id": "A1", "platform": "shopee", "date": "2026-10-04", "spend": 50.0,   # teks (CPC)
         "revenue": 100.0, "impressions": 500, "clicks": 5, "conversions": 1, "period_end": "2026-10-04"},
        {"id": "a3", "account_id": "A1", "platform": "shopee", "date": "2026-09-30", "spend": 999.0},
        {"id": "a4", "account_id": "A2", "platform": "tiktok", "date": dt("2026-10-05"), "spend": 777.0},
        {"id": "a5", "account_id": "A1", "platform": "shopee", "date": dt("2026-10-06"), "spend": 888.0,
         "_seed_origin": True}]
    return db


def test_ringkasan_iklan_bersaring_tanggal_toko_dan_tanpa_contoh_bug5(monkeypatch):
    from routes import marketing_ads_routes as ads
    db = _ads_db()
    monkeypatch.setattr(ads, "get_db", lambda: db)
    monkeypatch.setattr(ads, "require_auth", _auth(STAF_A1))
    out = run(ads.ads_summary(FakeRequest(), account_id=None, date_from="2026-10-01", date_to="2026-10-31"))
    assert out["data"]["total_spend"] == 150.0 and out["data"]["total_campaigns"] == 2
    assert out["data"]["by_platform"] == {"shopee": {"spend": 150.0, "revenue": 500.0, "campaigns": 2,
                                                     "roas": 3.33}}
    monkeypatch.setattr(ads, "require_auth", _auth(ADMIN))
    semua = run(ads.ads_summary(FakeRequest(), account_id=None, date_from=None, date_to=None))
    assert semua["data"]["total_spend"] == 150.0 + 999.0 + 777.0                     # contoh tetap keluar


def test_tanggal_iklan_campur_dinormalkan_saat_dibaca_bug6():
    db = _ads_db()
    rows = run(U.baca_iklan(db, ["A1"], "2026-10-01", "2026-10-31"))
    assert sorted(r["_tanggal"] for r in rows) == ["2026-10-03", "2026-10-04"]
    out = run(U.analitik_iklan(db, [_acc("A1")], "2026-10-01", "2026-10-31", kelompok="hari"))
    assert [b["kunci"] for b in out["baris"]] == ["2026-10-03", "2026-10-04"]
    assert out["total"]["roas"] == round(500 / 150, 2)


def test_tren_iklan_tidak_membuang_baris_bertanggal_teks(monkeypatch):
    from routes import marketing_ads_routes as ads
    db = AggDB()
    db.marketing_platform_accounts.docs.append(_acc("A1"))
    d1 = (today_wib() - timedelta(days=3)).isoformat()
    d2 = (today_wib() - timedelta(days=2)).isoformat()
    db.marketing_ads_data.docs += [
        {"id": "t1", "account_id": "A1", "date": datetime.fromisoformat(f"{d1}T05:00:00+00:00"), "spend": 10.0,
         "revenue": 30.0, "conversions": 1},
        {"id": "t2", "account_id": "A1", "date": d2, "spend": 20.0, "revenue": 20.0, "conversions": 2}]
    monkeypatch.setattr(ads, "get_db", lambda: db)
    monkeypatch.setattr(ads, "require_auth", _auth(ADMIN))
    out = run(ads.performance_trend(FakeRequest(), days=30))
    assert [t["date"] for t in out["data"]["trend"]] == [d1, d2]


# ══════════════════════════════════════════════════════════════════════════════
# 7. BUG #7 — rekonsiliasi: Shopee tanpa order_amount; pencairan menurut periode pesanan
# ══════════════════════════════════════════════════════════════════════════════
def test_rekonsiliasi_shopee_tanpa_order_amount_dan_periode_pesanan_bug7(monkeypatch):
    from routes import marketing_settlements as ms
    db = AggDB()
    db.marketing_platform_accounts.docs.append(_acc("A1"))
    db.marketing_settlements.docs += [
        {"id": "S1", "settlement_id": "S1", "account_id": "A1", "settlement_date": "2026-10-03",
         "period_from": "2026-09-24", "period_to": "2026-09-30", "gross_sales": 500.0},
        {"id": "S2", "settlement_id": "S2", "account_id": "A1", "settlement_date": "2026-10-10",
         "period_from": "2026-10-01", "period_to": "2026-10-07", "gross_sales": 100000.0},
        {"id": "S3", "settlement_id": "S3", "account_id": "A1", "settlement_date": "2026-11-06",
         "period_from": "2026-10-29", "period_to": "2026-11-04", "gross_sales": 50000.0}]
    db.marketing_orders.docs += [
        # ekspor Shopee: TIDAK punya order_amount, hanya total_payment
        {**_order("SH-1", "completed", 100000.0), "total_payment": 112000.0},
        {"id": "doc-SH-2", "order_id": "SH-2", "account_id": "A1", "status": "paid",
         "order_date": "2026-10-30 21:00:00", "revenue_product": 40000.0, "total_payment": 45000.0},
        _order("SH-3", "new", 9000.0),                         # belum dibayar
        _order("SH-4", "cancelled", 8000.0)]
    monkeypatch.setattr(ms, "get_db", lambda: db)
    monkeypatch.setattr(ms, "require_auth", _auth(ADMIN))
    out = run(ms.reconcile(FakeRequest(), account_id="A1", date_from="2026-10-01", date_to="2026-10-31",
                           settlement_id=""))
    assert out["settlement"]["count"] == 2 and out["settlement"]["gross_sales"] == 150000.0   # S2 + S3, bukan S1
    assert out["marketing"]["order_amount"] == 157000.0 and out["marketing"]["order_count"] == 2
    names = {n["name"] for n in out["gap"]["named"]}
    assert {"pesanan_belum_dibayar_dikecualikan", "periode_pencairan_melewati_rentang",
            "pesanan_batal_dikecualikan"} <= names


# ══════════════════════════════════════════════════════════════════════════════
# 8. MIGRASI #8 — rekap lama yang masih menghitung pesanan belum dibayar
# ══════════════════════════════════════════════════════════════════════════════
def test_migrasi_rekap_belum_bayar_pratinjau_lalu_hitung_ulang():
    mig = _mig("2026_11_08_rekap_tanpa_belum_bayar")
    db = FakeDB()
    db.marketing_platform_accounts.docs.append(_acc("A1"))
    db.marketing_orders.docs += [_order("A", "paid", 100000.0), _order("B", "new", 50000.0)]
    stale = _daily("A1", "2026-10-05", 150000.0, 2)
    stale["fulfillment"] = {}
    db.marketing_sales_data.docs.append(stale)
    pre = run(mig.run(db, apply=False))
    assert pre["pairs"] == 1 and pre["stale"] == 1 and pre["omzet_berlebih"] == 50000.0
    assert db.marketing_sales_data.docs[0]["metrics"]["revenue"] == 150000.0
    run(mig.run(db, apply=True))
    doc = db.marketing_sales_data.docs[0]
    assert doc["metrics"]["revenue"] == 100000.0 and doc["metrics"]["orders"] == 1
    assert doc["fulfillment"]["unpaid_orders"] == 1
    assert run(mig.run(db, apply=False))["stale"] == 0                           # idempoten


# ══════════════════════════════════════════════════════════════════════════════
# 9. BUG #10 — lebih dari 20.000 baris ditolak dengan pesan, tidak dipotong diam-diam
# ══════════════════════════════════════════════════════════════════════════════
def _csv(headers, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def test_berkas_lebih_dari_batas_baris_ditolak_bug10(monkeypatch):
    monkeypatch.setattr(eng, "MAX_ROWS", 5)
    ok = _csv(["a", "b"], [[i, i] for i in range(5)])
    assert len(eng.parse_table(ok, "x.csv")[1]) == 5
    big = _csv(["a", "b"], [[i, i] for i in range(6)])
    with pytest.raises(eng.TooManyRows) as e:
        eng.parse_table(big, "x.csv")
    assert "Pecah berkasnya" in str(e.value) and "lebih dari" in str(e.value)
    with pytest.raises(eng.TooManyRows):
        eng.parse_table_lenient(big, "x.csv", get_source_type("marketplace_orders"))
    from core import marketing_import_prenorm as prenorm
    monkeypatch.setattr(prenorm, "MAX_ROWS", 1)
    with pytest.raises(eng.TooManyRows):                      # penormal KPI juga tidak memotong diam-diam
        prenorm._cells(_csv(["a"], [[i] for i in range(60)]))


# ══════════════════════════════════════════════════════════════════════════════
# 10. BUG #11 — indeks unik kunci dedup + daftar kembar sebelum dipasang
# ══════════════════════════════════════════════════════════════════════════════
def test_indeks_unik_untuk_setiap_jenis_impor_bug11():
    from core import marketing_import_indexes as mii
    specs = {s["source_type"]: s for s in mii.unique_import_specs()}
    for t in source_type_catalog():
        st = get_source_type(t["key"])
        if st.update_only or st.key in mii.SUDAH_DIPAGARI:
            continue
        s = specs[st.key]
        assert [k for k, _ in s["keys"]] == list(st.dedupe)
        assert s["partial"]["_import_source_type"] == st.key
        assert all(k in s["partial"] for k in st.dedupe)                       # kunci kosong tidak dipagari
    assert specs["ads"]["partial"]["date"] == {"$type": "date"}
    assert specs["returns"]["partial"]["order_id"] == {"$gt": ""}
    src = Path(BACKEND, "migrations", "ensure_indexes.py").read_text(encoding="utf-8")
    assert "unique_import_specs" in src and "_ensure_unique_index(db, _spec[\"collection\"]" in src


def test_migrasi_cek_duplikat_melapor_kembar_dan_hanya_memasang_yang_bersih(monkeypatch):
    mig = _mig("2026_11_08_cek_duplikat_impor_marketing")
    db = AggDB()
    db.marketing_returns.docs += [
        {"id": "r1", "_import_source_type": "returns", "account_id": "A1", "order_id": "O1", "product": "X"},
        {"id": "r2", "_import_source_type": "returns", "account_id": "A1", "order_id": "O1", "product": "X"},
        {"id": "r3", "account_id": "A1", "order_id": "O1", "product": "X"}]           # entri modul: bukan impor
    pre = run(mig.run(db, apply=False))
    ret = next(r for r in pre["indeks"] if r["indeks"] == "uniq_impor_returns")
    assert ret["kelompok_kembar"] == 1 and ret["dokumen_berlebih"] == 1
    assert sorted(ret["contoh"][0]["id"]) == ["r1", "r2"]
    dibuat = []

    async def _fake_ensure(_db, coll, keys, *, name, partial=None, drop_conflicting=None):
        dibuat.append(name)
        return True
    import migrations.ensure_indexes as ei
    monkeypatch.setattr(ei, "_ensure_unique_index", _fake_ensure)
    out = run(mig.run(db, apply=True))
    assert "uniq_impor_returns" not in dibuat and "uniq_impor_ads" in dibuat     # terhalang kembar
    assert out["terhalang"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 11. BUG #13 — impor pesanan format lama: nama uang kanonik + rekap dihitung ulang
# ══════════════════════════════════════════════════════════════════════════════
def test_impor_pesanan_lama_menulis_omzet_produk_dan_memicu_rekap_bug13():
    import routes.marketing_data_import as md
    st = get_source_type("orders")
    data = {"order_id": "L-1", "order_date": datetime(2026, 10, 5, tzinfo=timezone.utc), "quantity": 2,
            "price_final": 50000.0, "discount_seller": 10000.0, "shipping_cost": 9000.0}
    doc, _w = md._finish(st, dict(data), {"account_id": "A1"}, {}, account=_acc("A1"))
    assert doc["revenue_product"] == 90000.0 and doc["order_amount"] == 99000.0
    assert doc["status"] == "new" and doc["status_assumed"] is True
    assert rollup.order_revenue_product(doc) == 90000.0 and U.dihitung_omzet(doc)    # dulu 100.000
    doc2, _ = md._finish(st, {**data, "status": "new"}, {"account_id": "A1"}, {}, account=_acc("A1"))
    assert "status_assumed" not in doc2 and U.belum_dibayar(doc2)                 # "Belum dibayar" dari berkas
    src = Path(BACKEND, "routes", "marketing_data_import.py").read_text(encoding="utf-8")
    assert md.ROLLUP_ORDER_TYPES == ("marketplace_orders", "orders")
    assert "if st.key in ROLLUP_ORDER_TYPES and (inserted or updated):" in src
    assert "    if st.key in ROLLUP_ORDER_TYPES:\n" in src                          # rollback


# ══════════════════════════════════════════════════════════════════════════════
# 12. BUG #15 — berkas ditolak tidak tertinggal; hapus lewat API penyimpanan
# ══════════════════════════════════════════════════════════════════════════════
def test_hapus_berkas_lewat_api_penyimpanan(monkeypatch, tmp_path):
    import object_storage as obj
    monkeypatch.setattr(obj, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setenv("FILE_STORAGE", "local")
    obj.put_object("marketing-data-import/x.csv", b"a,b\n1,2\n")
    assert (tmp_path / "marketing-data-import" / "x.csv").exists()
    assert obj.delete_object("marketing-data-import/x.csv") is True
    assert not (tmp_path / "marketing-data-import" / "x.csv").exists()
    assert obj.delete_object("marketing-data-import/x.csv") is False
    assert obj.delete_object("../../etc/passwd") is False


ORDER_HEADERS = ["No. Pesanan", "Status Pesanan", "Waktu Pesanan Dibuat", "Nama Produk", "Jumlah",
                 "Subtotal Pesanan", "Total Pembayaran", "Warehouse Name"]
ORDER_ROWS = [["UJI-A", "Selesai", "2026-10-01 10:00", "Kaos Uji", "2", "160.000", "170.000", "Gudang Lain"]]


def _patch_upload(monkeypatch, db, stored, account):
    import routes.marketing_data_import as md

    async def _ctx(_db, st, account_id, ctx):
        return {"account": account}

    async def _same(_db, _st, _s, built):
        return built

    async def _nodup(*_a, **_k):
        return {}

    monkeypatch.setattr(md, "require_auth", _auth({"id": "u-spv", "email": "spv@uji", "role": "spv_marketing"}))
    monkeypatch.setattr(md, "get_db", lambda: db)
    monkeypatch.setattr(md, "_validate_context", _ctx)
    monkeypatch.setattr(md, "_annotate_master_links", _same)
    monkeypatch.setattr(md, "_annotate_existing", _nodup)
    monkeypatch.setattr(md, "_put_object", lambda path, raw, _ct: stored.__setitem__(path, raw))
    monkeypatch.setattr(md, "_read_session_file", lambda p: stored.get(p))
    return md


def _upload(md, raw, fname, st="marketplace_orders"):
    req = FakeRequest()
    req.state.user = {"id": "u-spv", "email": "spv@uji", "role": "spv_marketing"}
    f = UploadFile(file=io.BytesIO(raw), filename=fname)
    return run(md.upload(req, file=f, source_type=st, account_id="acc-1", host_id=None, creator_id=None,
                         catalog_id=None, live_session_id=None))


def test_unggahan_ditolak_penjaga_toko_tidak_menyimpan_berkas_bug15(monkeypatch):
    stored: dict = {}
    acc = {"id": "acc-1", "account_name": "Toko Uji", "account_code": "UJI-01", "platform": "shopee",
           "platform_warehouse_name": "Gudang Toko Uji"}
    md = _patch_upload(monkeypatch, FakeDB(), stored, acc)
    with pytest.raises(HTTPException) as e:
        _upload(md, _csv(ORDER_HEADERS, ORDER_ROWS), "Order.all.csv")
    assert e.value.status_code == 400 and "Gudang Lain" in e.value.detail
    assert stored == {}                                         # tidak ada berkas yatim
    src = Path(BACKEND, "routes", "marketing_data_import.py").read_text(encoding="utf-8")
    up = src[src.index("async def upload("):src.index("def _clean_value_map")]
    assert "os.remove(" not in up


def test_unggahan_terlalu_banyak_baris_ditolak_lewat_route(monkeypatch):
    monkeypatch.setattr(eng, "MAX_ROWS", 3)
    stored: dict = {}
    md = _patch_upload(monkeypatch, FakeDB(), stored, {"id": "acc-1", "account_name": "Toko Uji",
                                                         "platform": "shopee"})
    rows = [[f"UJI-{i}", "Selesai", "2026-10-01 10:00", "Kaos", "1", "1.000", "1.000", ""] for i in range(4)]
    with pytest.raises(HTTPException) as e:
        _upload(md, _csv(ORDER_HEADERS, rows), "Order.all.csv")
    assert e.value.status_code == 400 and "tidak memotong" in e.value.detail and stored == {}


# ══════════════════════════════════════════════════════════════════════════════
# 13. PRIVASI — usulan AI pemetaan impor tanpa data pribadi pembeli
# ══════════════════════════════════════════════════════════════════════════════
NAMA_PEMBELI = "Probelia Ratnasari"
HP_PEMBELI = "0812-3456-7890"


def test_contoh_baris_disamarkan():
    import routes.marketing_data_import as md
    mapping = [{"column": "Nama Penerima", "field": "customer_name"}, {"column": "Kolom Misteri", "field": None},
               {"column": "Nama Produk", "field": "product_name_raw"}, {"column": "No. Telepon", "field": None},
               {"column": "Alamat Pengiriman", "field": "address_detail"}]
    rows = [{"Nama Penerima": NAMA_PEMBELI, "Kolom Misteri": f"hubungi {HP_PEMBELI}",
             "Nama Produk": "Gamis Uji", "No. Telepon": HP_PEMBELI, "Alamat Pengiriman": "Jl. Mawar 3"}]
    out = md.mask_sample_rows(rows, mapping)[0]
    assert out["Nama Penerima"].startswith("PLG-") and out["Alamat Pengiriman"] == "[DISAMARKAN]"
    assert out["No. Telepon"] == "[DISAMARKAN]" and HP_PEMBELI not in out["Kolom Misteri"]
    assert out["Nama Produk"] == "Gamis Uji"
    assert NAMA_PEMBELI not in json.dumps(out) and "Mawar" not in json.dumps(out)


def test_usulan_ai_impor_mengirim_contoh_tersamar_dan_terbungkus(monkeypatch):
    import services.ai as sai
    stored: dict = {}
    md = _patch_upload(monkeypatch, FakeDB(), stored, {})
    headers = ["No. Pesanan", "Nama Penerima", "No. Telepon", "Alamat Pengiriman", "Kolom Misteri"]
    raw = _csv(headers, [["UJI-1", NAMA_PEMBELI, HP_PEMBELI, "Jl. Mawar 3", "x"]])
    stored["f.csv"] = raw
    db = md.get_db()
    db.marketing_data_import_sessions.docs.append({
        "id": "S-1", "source_type": "marketplace_orders", "file_path": "f.csv", "filename": "f.csv",
        "mapping": [{"column": "No. Pesanan", "field": "order_id", "method": "exact"},
                    {"column": "Nama Penerima", "field": "customer_name", "method": "exact"},
                    {"column": "No. Telepon", "field": None, "method": "none"},
                    {"column": "Alamat Pengiriman", "field": None, "method": "none"},
                    {"column": "Kolom Misteri", "field": None, "method": "none"}]})
    sent = {}

    async def _status(_db):
        return {"available": True}

    async def _text(feature, system, prompt, **kw):
        sent.update(system=system, prompt=prompt)
        return "[]"
    monkeypatch.setattr(sai, "ai_status", _status)
    monkeypatch.setattr(sai, "ai_text", _text)
    out = run(md.ai_assist("S-1", FakeRequest()))
    assert out["ok"] is True
    assert NAMA_PEMBELI not in sent["prompt"] and "3456" not in sent["prompt"] and "Mawar" not in sent["prompt"]
    assert '<data_pihak_luar jenis="contoh_baris_berkas">' in sent["prompt"]
    from services.ai.privacy import UNTRUSTED_RULE
    assert UNTRUSTED_RULE in sent["system"]


# ══════════════════════════════════════════════════════════════════════════════
# 14. ENDPOINT ANALITIK — lingkup toko, CV, kelompok, pembanding
# ══════════════════════════════════════════════════════════════════════════════
def _db_analitik():
    db = FakeDB()
    db.marketing_platform_accounts.docs += [_acc("A1", assigned_staff=["u-staf"]), _acc("A2", "tiktok"),
                                            _acc("S1", entity="SMU")]
    for aid, base in (("A1", 1000.0), ("A2", 5000.0), ("S1", 7.0)):
        for d in ("2026-09-01", "2026-09-02", "2026-10-01", "2026-10-02"):
            db.marketing_sales_data.docs.append(_daily(aid, d, base + (100 if d.startswith("2026-10") else 0), 2))
    db.marketing_orders.docs += [
        {**_order("O1", "paid", 600.0, date="2026-10-01", order_channel="live", buyer_username="b1",
                  customer_name=NAMA_PEMBELI), "items": [{"catalog_item_id": "IT-1", "quantity": 1,
                                                          "sku_subtotal_after_discount": 600.0}]},
        {**_order("O2", "paid", 500.0, date="2026-10-02", order_channel="video", buyer_username="b1"),
         "items": [{"catalog_item_id": "IT-1", "quantity": 1, "sku_subtotal_after_discount": 500.0}]}]
    return db


def test_endpoint_analitik_menghormati_lingkup_toko(monkeypatch):
    from routes import marketing_analitik as ma
    db = _db_analitik()
    monkeypatch.setattr(ma, "get_db", lambda: db)
    monkeypatch.setattr(ma, "require_auth", _auth(STAF_A1))
    out = run(ma.analitik_penjualan(FakeRequest(), dari="2026-10-01", sampai="2026-10-02", kelompok="toko",
                                    bandingkan="tidak", toko_id=None, limit=None))
    assert out["total"]["omzet"] == 2200 and [b["kunci"] for b in out["kelompok"]["baris"]] == ["A1"]
    with pytest.raises(HTTPException) as e:
        run(ma.analitik_penjualan(FakeRequest(), dari="2026-10-01", sampai="2026-10-02", kelompok="toko",
                                  bandingkan="tidak", toko_id="A2", limit=None))
    assert e.value.status_code == 403
    for fn, kw in ((ma.analitik_iklan, {"kelompok": "toko", "limit": 20}),
                   (ma.analitik_live, {"kelompok": "host", "limit": 20}),
                   (ma.analitik_setoran, {"kelompok": "toko", "limit": 20}),
                   (ma.analitik_produk, {"urut": "teratas", "cara": "produk", "limit": 10})):
        with pytest.raises(HTTPException) as e2:
            run(fn(FakeRequest(), dari="2026-10-01", sampai="2026-10-02", toko_id="A2", **kw))
        assert e2.value.status_code == 403
    with pytest.raises(HTTPException) as e3:
        run(ma.analitik_target(FakeRequest(), dari_bulan="2026-10", sampai_bulan=None, toko_id="A2"))
    assert e3.value.status_code == 403


def test_toko_mengikuti_pilihan_cv():
    db = _db_analitik()
    da = run(U.toko_terlihat(db, ADMIN, cv="DA"))
    smu = run(U.toko_terlihat(db, ADMIN, cv="SMU"))
    semua = run(U.toko_terlihat(db, ADMIN, cv="ALL"))
    assert [a["id"] for a in da] == ["A1", "A2"] and [a["id"] for a in smu] == ["S1"] and len(semua) == 3


def test_analitik_penjualan_kanal_pembanding_dan_tanpa_data_pembeli():
    db = _db_analitik()
    accs = run(U.toko_terlihat(db, ADMIN, cv="DA"))
    out = run(U.analitik_penjualan(db, accs, "2026-10-01", "2026-10-02", kelompok="kanal",
                                   bandingkan="periode_sebelumnya"))
    assert out["pembanding"]["periode"] == {"dari": "2026-09-29", "sampai": "2026-09-30"}
    assert {b["kunci"]: b["omzet"] for b in out["kelompok"]["baris"]} == {"live": 600, "video": 500}
    assert out["total"]["pembeli"] == 1 and out["cakupan_rincian"]["pesanan_terbaca"] == 2
    ly = run(U.analitik_penjualan(db, accs, "2026-10-01", "2026-10-02", kelompok="bulan", bandingkan="tahun_lalu"))
    assert ly["pembanding"]["periode"]["dari"] == "2025-10-01"
    prev = run(U.analitik_penjualan(db, accs, "2026-10-01", "2026-10-02", kelompok="toko"))
    assert prev["total"]["omzet"] == 12400
    teks = json.dumps(out, default=str)
    assert NAMA_PEMBELI not in teks and "b1" not in teks


def test_analitik_target_proyeksi_bulan_berjalan():
    db = _db_analitik()
    db.marketing_account_targets.docs.append({"account_id": "A1", "year": 2026, "month": 10,
                                              "revenue_target": 10000.0, "orders_target": 10})
    out = run(U.analitik_target(db, [_acc("A1")], ["2026-10"], hari_ini=datetime(2026, 10, 2).date()))
    r = out["baris"][0]
    assert r["aktual_omzet"] == 2200 and r["capaian_omzet_persen"] == 22.0 and r["bulan_berjalan"]
    assert r["proyeksi_omzet_akhir_bulan"] == 34100 and r["status"] == "sesuai_jalur"


def test_analitik_setoran_per_tanggal_dana_dilepas_dan_biaya_per_jenis():
    db = FakeDB()
    db.marketing_settlements.docs += [
        {"id": "s1", "account_id": "A1", "platform": "shopee", "settlement_date": "2026-10-03",
         "gross_sales": 1000.0, "platform_commission": 50.0, "ads_deduction": 20.0, "net_payout": 930.0},
        {"id": "s2", "account_id": "A1", "settlement_date": "2026-11-01", "gross_sales": 9.0},
        {"id": "s3", "account_id": "A1", "settlement_date": "2026-10-05", "gross_sales": 7.0, "_seed_origin": True}]
    out = run(U.analitik_setoran(db, [_acc("A1")], "2026-10-01", "2026-10-31"))
    t = out["total"]
    assert t["setoran"] == 1 and t["bruto"] == 1000 and t["total_biaya"] == 70 and t["neto_diterima"] == 930
    assert t["biaya"]["Komisi platform"] == 50 and t["biaya_persen_dari_bruto"] == 7.0


def test_peta_izin_endpoint_analitik_ke_modul_baca_yang_ada():
    from data import module_catalog as mc
    assert mc.match_module("/api/marketing/analitik/penjualan")["id"] == "mkt_dashboard"
    assert mc.match_module("/api/marketing/analitik/produk")["id"] == "mkt_dashboard"
    assert mc.match_module("/api/marketing/analitik/target")["id"] == "mkt_targets"
    assert mc.match_module("/api/marketing/analitik/iklan")["id"] == "mkt_content"
    assert mc.match_module("/api/marketing/analitik/live")["id"] == "mkt_live"
    assert mc.match_module("/api/marketing/analitik/setoran")["id"] == "fin_marketplace"


# ══════════════════════════════════════════════════════════════════════════════
# 15. ALAT AI (kontrak A) — skema sah, keluaran kecil, ringkasan_penjualan tersambung
# ══════════════════════════════════════════════════════════════════════════════
MODUL_ALAT = ("penjualan", "produk", "target_marketing", "iklan", "live", "setoran")


def _registry():
    """Daftar alat — `REGISTRY` (stub agen data) atau `_DAFTAR` (kerangka agen inti)."""
    for m in MODUL_ALAT:
        importlib.import_module(f"core.asisten_ai.alat.{m}")
    from core.asisten_ai import alat_base
    reg = getattr(alat_base, "REGISTRY", None)
    return reg if reg is not None else alat_base._DAFTAR


def _f(entry, key):
    return entry[key] if isinstance(entry, dict) else getattr(entry, key)


NAMA_ALAT = ("ringkasan_penjualan", "analisis_produk", "target_toko", "kinerja_iklan", "kinerja_live",
             "setoran_marketplace")


def test_skema_alat_sah():
    reg = _registry()
    for name in NAMA_ALAT:
        e = reg[name]
        sch = _f(e, "input_schema")
        assert _f(e, "kind") == "read" and _f(e, "name") == name
        assert sch["type"] == "object" and sch["additionalProperties"] is False
        assert isinstance(sch["required"], list) and set(sch["required"]) <= set(sch["properties"])
        for p in sch["properties"].values():
            assert p.get("type") in ("string", "integer") and p.get("description")
        desc = _f(e, "description")
        assert len(desc) > 300 and "Rp" in desc and _f(e, "label")
        assert _f(e, "domain") in ("penjualan", "iklan", "live", "setoran")
    assert "kanal" in _f(reg["ringkasan_penjualan"], "description").lower()
    assert "belum dibayar" in _f(reg["ringkasan_penjualan"], "description")


class FakeCtx:
    def __init__(self, handler, user=ADMIN, cv="DA", today="2026-10-02"):
        self.user, self.cv, self.today = user, cv, datetime.fromisoformat(today).date()
        self._handler = handler
        self.calls = []

    async def api(self, method, path, params=None, json=None):
        self.calls.append((method, path, dict(params or {})))
        return await self._handler(path, dict(params or {}))


def test_ringkasan_penjualan_tersambung_ke_endpoint_dengan_bawaan_periode(monkeypatch):
    from routes import marketing_analitik as ma
    db = _db_analitik()
    monkeypatch.setattr(ma, "get_db", lambda: db)
    monkeypatch.setattr(ma, "require_auth", _auth(ADMIN))
    fungsi = {"penjualan": ma.analitik_penjualan}

    async def handler(path, params):
        fn = fungsi[path.rsplit("/", 1)[1]]
        base = {"dari": None, "sampai": None, "kelompok": "toko", "bandingkan": "tidak", "toko_id": None,
                "limit": None}
        return await fn(FakeRequest(), **{**base, **params})
    ctx = FakeCtx(handler)
    out = run(_f(_registry()["ringkasan_penjualan"], "handler")(ctx, {}))
    assert ctx.calls[0][1] == "/api/marketing/analitik/penjualan"
    assert ctx.calls[0][2]["dari"] == "2026-10-01" and ctx.calls[0][2]["sampai"] == "2026-10-02"
    assert out["hasil"]["total"]["omzet"] == 2200 + 10200 and out["_sumber"]
    assert len(json.dumps(out, ensure_ascii=False, default=str)) <= 15000


def test_keluaran_semua_alat_dipadatkan_di_bawah_15rb_karakter():
    reg = _registry()
    besar = {"ok": True, "definisi": "x" * 900, "total": {"omzet": 1.0},
             "toko": {"jumlah": 40, "daftar": [{"id": f"t{i}", "nama": "Toko " * 5} for i in range(40)]},
             "kelompok": {"baris": [{"kunci": f"k{i}", "label": "Label panjang sekali " * 4, "omzet": i}
                                    for i in range(500)]},
             "baris": [{"kunci": f"k{i}", "label": "Label panjang sekali " * 4, "omzet": i} for i in range(500)]}

    async def handler(path, params):
        return copy.deepcopy(besar)
    for name in NAMA_ALAT:
        out = run(_f(reg[name], "handler")(FakeCtx(handler), {}))
        teks = json.dumps(out, ensure_ascii=False, default=str)
        assert len(teks) <= 15000, (name, len(teks))
        assert out["hasil"].get("dipotong_untuk_ai")
