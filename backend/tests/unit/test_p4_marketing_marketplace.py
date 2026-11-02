"""Uji unit HERMETIK paket P4 (2026-11-02) — Marketing & marketplace, tanpa server & tanpa Mongo.

Butir yang dijaga (keputusan owner, audit m.md):
  * No.14a — refund retur = NOMINAL AKTUAL (bukan 70% dipatok), refund penuh ikut qty.
  * No.16  — retur modul Retur mengurangi "omzet setelah retur" di rekap harian per
             tanggal retur & per toko, TANPA dobel dengan retur dari status impor.
  * No.10b — toko baru otomatis punya akun pendapatan sendiri; alias `tiktokshop`.
  * D3     — Peta Akun Channel: finance_sync tidak lagi menulis baris toko; endpoint
             tulis untuk toko marketplace menjawab 410; menu dilepas.
  * Seeder data demo tidak dipanggil di handler GET.
  * "Selesaikan & Terbitkan Nota Kredit" benar-benar menerbitkan nota (gl_mode settlement).

Bagian yang menyentuh DB memakai tiruan Mongo kecil di bawah (`FakeDB`); bukti
runtime terhadap Mongo sungguhan ada di laporan paket (backend uji dahost-fix-k4).

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import ast
import asyncio
import copy
import os
import re
import sys
from datetime import datetime

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from core import finance_sync as fs  # noqa: E402
from core import marketing_daily_rollup as rollup  # noqa: E402
from core import marketing_returns as mret  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════════
# Tiruan Mongo minimal (cukup untuk kueri yang dipakai kode yang diuji)
# ══════════════════════════════════════════════════════════════════════════════
_MISSING = object()


def _get(doc, path):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _set(doc, path, value):
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _unset(doc, path):
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.get(p) or {}
    cur.pop(parts[-1], None)


def _cmp_ok(a, b):
    return type(a) is type(b) or (isinstance(a, (int, float)) and isinstance(b, (int, float)))


def _match_value(val, cond):
    if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            v = None if val is _MISSING else val
            if op == "$in":
                if not (v in arg or (isinstance(v, list) and any(x in arg for x in v))):
                    return False
            elif op == "$nin":
                if v in arg:
                    return False
            elif op == "$ne":
                if v == arg:
                    return False
            elif op == "$exists":
                if (val is not _MISSING) != bool(arg):
                    return False
            elif op == "$regex":
                flags = re.I if "i" in (cond.get("$options") or "") else 0
                if not isinstance(v, str) or not re.search(arg, v, flags):
                    return False
            elif op == "$options":
                continue
            elif op in ("$gte", "$gt", "$lt", "$lte"):
                if v is None or not _cmp_ok(v, arg):
                    return False
                if op == "$gte" and not v >= arg:
                    return False
                if op == "$gt" and not v > arg:
                    return False
                if op == "$lt" and not v < arg:
                    return False
                if op == "$lte" and not v <= arg:
                    return False
            else:
                raise NotImplementedError(op)
        return True
    v = None if val is _MISSING else val
    return v == cond


def _match(doc, q):
    for k, cond in (q or {}).items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
        elif k == "$and":
            if not all(_match(doc, sub) for sub in cond):
                return False
        elif not _match_value(_get(doc, k), cond):
            return False
    return True


class _Res:
    def __init__(self, matched=0, modified=0, deleted=0):
        self.matched_count, self.modified_count, self.deleted_count = matched, modified, deleted


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *a, **k):
        return self

    def skip(self, n):
        self.docs = self.docs[n:]
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    async def to_list(self, n=None):
        return [copy.deepcopy(d) for d in self.docs[: n or None]]

    def __aiter__(self):
        self._it = iter([copy.deepcopy(d) for d in self.docs])
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeColl:
    def __init__(self, name, log):
        self.name, self.docs, self.log = name, [], log

    def find(self, q=None, proj=None, sort=None):
        return _Cursor([d for d in self.docs if _match(d, q)])

    async def find_one(self, q=None, proj=None, sort=None):
        for d in self.docs:
            if _match(d, q):
                return copy.deepcopy(d)
        return None

    async def insert_one(self, doc):
        self.log.append((self.name, "insert_one"))
        self.docs.append(copy.deepcopy({k: v for k, v in doc.items() if k != "_id"}))
        return _Res(1, 1)

    async def insert_many(self, docs):
        for d in docs:
            await self.insert_one(d)

    def _apply(self, d, upd):
        for k, v in (upd.get("$set") or {}).items():
            _set(d, k, v)
        for k in (upd.get("$unset") or {}):
            _unset(d, k)

    async def update_one(self, q, upd, upsert=False):
        self.log.append((self.name, "update_one"))
        for d in self.docs:
            if _match(d, q):
                self._apply(d, upd)
                return _Res(1, 1)
        if upsert:
            d = {k: v for k, v in q.items() if not k.startswith("$") and not isinstance(v, dict)}
            for k, v in (upd.get("$setOnInsert") or {}).items():
                _set(d, k, v)
            self._apply(d, upd)
            self.docs.append(d)
            return _Res(0, 0)
        return _Res(0, 0)

    async def update_many(self, q, upd):
        self.log.append((self.name, "update_many"))
        n = 0
        for d in self.docs:
            if _match(d, q):
                self._apply(d, upd)
                n += 1
        return _Res(n, n)

    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if _match(d, q):
                del self.docs[i]
                return _Res(deleted=1)
        return _Res()

    async def count_documents(self, q=None):
        return sum(1 for d in self.docs if _match(d, q))

    async def distinct(self, field, q=None):
        out = []
        for d in self.docs:
            if _match(d, q):
                v = _get(d, field)
                if v is not _MISSING and v not in out:
                    out.append(v)
        return out


class FakeDB:
    def __init__(self):
        self._c, self.log = {}, []

    def __getitem__(self, name):
        if name not in self._c:
            self._c[name] = FakeColl(name, self.log)
        return self._c[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


# ══════════════════════════════════════════════════════════════════════════════
# No.14a — refund nominal aktual
# ══════════════════════════════════════════════════════════════════════════════
from routes import marketing_returns_routes as rr  # noqa: E402


def test_refund_partial_requires_actual_amount_no_more_70_percent():
    with pytest.raises(HTTPException) as e:
        rr.compute_refund("partial_refund", 107999, 5, None)
    assert e.value.status_code == 400
    assert rr.compute_refund("partial_refund", 107999, 5, 150000) == (150000.0, "input")


def test_refund_full_multiplies_qty_and_accepts_actual():
    assert rr.compute_refund("full_refund", 107999, 2, None) == (215998.0, "harga_x_qty")
    assert rr.compute_refund("full_refund", 107999, 2, 200000) == (200000.0, "input")
    assert rr.compute_refund("full_refund", 107999, 2, 0) == (0.0, "input")


def test_refund_validation_negative_and_no_money_types():
    for bad in (-1, -0.01):
        with pytest.raises(HTTPException):
            rr.compute_refund("full_refund", 100, 1, bad)
    assert rr.compute_refund("exchange", 100, 3, None) == (0.0, "tanpa_refund")
    assert rr.compute_refund("no_refund", 100, 3, 0) == (0.0, "tanpa_refund")
    with pytest.raises(HTTPException):
        rr.compute_refund("exchange", 100, 1, 5000)
    with pytest.raises(HTTPException):
        rr.compute_refund("refund_70", 100, 1, None)


def test_return_models_validate_refund_and_order_optional():
    base = dict(account_id="a", date="2026-10-21", price=100, reason="lainnya",
                reason_detail="x", courier="jnt")
    m = rr.ReturnIn(**base)                     # tanpa nomor pesanan (No.4c)
    assert m.order_id == "" and m.refund_amount is None
    with pytest.raises(ValidationError):
        rr.ReturnIn(**base, refund_amount=-5)
    with pytest.raises(ValidationError):
        rr.ReturnUpdate(refund_amount=-1)


def test_no_hardcoded_70_percent_left_in_create_path():
    src = open(os.path.join(BACKEND, "routes", "marketing_returns_routes.py"), encoding="utf-8").read()
    body = src[src.index("async def create_return"):src.index("@router.put(")]
    assert "0.7" not in body


# ══════════════════════════════════════════════════════════════════════════════
# No.16 — retur modul mengurangi omzet setelah retur di rekap (tanpa dobel)
# ══════════════════════════════════════════════════════════════════════════════
def _order(oid, status, rev, amount, date="2026-10-15", qty=1, acc="A1"):
    return {"id": f"doc-{oid}", "order_id": oid, "account_id": acc, "status": status,
            "order_date": datetime.fromisoformat(f"{date}T09:00:00+00:00"),
            "revenue_product": rev, "order_amount": amount, "revenue_gross": rev, "quantity": qty}


def _ret(rid, date, refund, order_id="", status="pending", qty=1, acc="A1", ref=None):
    # 2026-11-02 (K36) — retur di uji No.16 ini dianggap SUDAH diputuskan gudang;
    # perilaku "belum diputuskan ⇒ tidak dihitung" diuji di test_w2a_retur_marketplace.py.
    d = {"id": rid, "account_id": acc, "date": date, "order_id": order_id, "status": status,
         "refund_amount": refund, "qty": qty,
         "wh_return_status": "Resolved", "wh_action_taken": "Restock ke Gudang"}
    if ref:
        d["order_ref_id"] = ref
    return d


def test_select_uncovered_skips_reflected_orders_and_rejected():
    rets = [_ret("r1", "2026-10-20", 107999, "IMP-A-3001"),            # order sudah returned
            _ret("r2", "2026-10-21", 107999, "IMP-A-3002"),            # order masih paid
            _ret("r3", "2026-10-21", 50000),                           # tanpa nomor (No.4c)
            _ret("r4", "2026-10-21", 9000, status="rejected"),         # ditolak
            _ret("r5", "2026-10-21", 7000, ref="doc-IMP-A-3009")]      # tautan impor ke order batal
    reflected = [{"order_id": "IMP-A-3001", "id": "doc-IMP-A-3001"},
                 {"order_id": "IMP-A-3009", "id": "doc-IMP-A-3009"}]
    kept = mret.select_uncovered_module_returns(rets, reflected)
    assert [r["id"] for r in kept] == ["r2", "r3"]
    s = mret.split_module_returns(kept)
    assert s == {"module_returns_count": 2, "module_returns_value": 157999.0, "module_returns_units": 2}


def test_summarize_orders_module_returns_reduce_net_not_gross():
    orders = [_order("IMP-A-3001", "returned", 215998, 225998, qty=2),
              _order("IMP-A-3002", "paid", 107999, 112999)]
    base = rollup.summarize_orders(orders)
    withmod = rollup.summarize_orders(orders, [_ret("r2", "2026-10-15", 107999, "X")])
    # bruto, jumlah pesanan & tingkat retur pesanan tidak bergeser (keputusan sesi #9)
    for k in ("revenue_product", "revenue_order_amount", "orders"):
        assert withmod[k] == base[k]
    assert withmod["fulfillment"]["return_rate"] == base["fulfillment"]["return_rate"]
    assert base["fulfillment"]["returned_revenue_product"] == 215998
    assert withmod["fulfillment"]["returned_revenue_product"] == 215998 + 107999
    assert withmod["fulfillment"]["returned_value"] == 225998 + 107999
    assert withmod["fulfillment"]["module_returns_count"] == 1
    assert withmod["fulfillment"]["module_returns_value"] == 107999


def _seed_rollup_db():
    db = FakeDB()
    db.marketing_platform_accounts.docs.append(
        {"id": "A1", "account_code": "SHP-01", "account_name": "Shopee GHS", "platform": "shopee",
         "revenue_basis": "produk_setelah_diskon"})
    db.marketing_orders.docs += [_order("IMP-A-3001", "returned", 215998, 225998, qty=2),
                                 _order("IMP-A-3002", "paid", 107999, 112999)]
    db.marketing_returns.docs += [
        _ret("dup", "2026-10-20", 107999, "IMP-A-3001", qty=2),   # sudah tercermin status impor
        _ret("new", "2026-10-21", 107999, "IMP-A-3002"),          # belum tercermin
        _ret("free", "2026-10-21", 50000),                        # tanpa nomor pesanan
        _ret("other_store", "2026-10-21", 99999, acc="A2"),       # toko lain
    ]
    return db


def _daily(db, date):
    return next((d for d in db.marketing_sales_data.docs if d["date"] == date), None)


def test_recompute_daily_counts_module_returns_per_return_date_without_double():
    db = _seed_rollup_db()
    for d in ("2026-10-15", "2026-10-20", "2026-10-21"):
        run(rollup.recompute_daily(db, "A1", d))
    d15, d20, d21 = _daily(db, "2026-10-15"), _daily(db, "2026-10-20"), _daily(db, "2026-10-21")
    assert d15["metrics"]["revenue"] == 323997 and d15["fulfillment"]["returned_revenue_product"] == 215998
    assert d15["fulfillment"]["module_returns_count"] == 0
    assert d20 is None                                   # retur dobel atas IMP-A-3001 tidak dihitung
    assert d21["metrics"]["revenue"] == 0 and d21["metrics"]["orders"] == 0
    assert d21["fulfillment"]["returned_revenue_product"] == 157999   # 107.999 + 50.000, toko A1 saja
    assert d21["fulfillment"]["module_returns_count"] == 2

    rows = list(db.marketing_sales_data.docs)
    split = mret.from_daily_rows(rows)
    res = mret.resolve("produk_setelah_diskon", 323997, split)
    assert res["returned_amount"] == 215998 + 157999
    assert res["revenue_net_returns"] == 0.0 and res["over_returned"] is True
    assert res["returned_module_count"] == 2

    # idempoten
    before = copy.deepcopy(db.marketing_sales_data.docs)
    run(rollup.recompute_daily(db, "A1", "2026-10-21"))
    assert [d["fulfillment"] for d in db.marketing_sales_data.docs] == [d["fulfillment"] for d in before]


def test_recompute_after_order_flips_to_returned_removes_module_double():
    db = _seed_rollup_db()
    run(rollup.recompute_daily(db, "A1", "2026-10-21"))
    assert _daily(db, "2026-10-21")["fulfillment"]["module_returns_count"] == 2
    # impor C kemudian menandai IMP-A-3002 retur → rekap tanggal pesanan dihitung ulang
    db.marketing_orders.docs[1]["status"] = "returned"
    run(rollup.recompute_daily(db, "A1", "2026-10-15"))
    d21 = _daily(db, "2026-10-21")
    assert d21["fulfillment"]["module_returns_count"] == 1          # hanya retur tanpa nomor
    assert d21["fulfillment"]["returned_revenue_product"] == 50000


def test_rejected_or_deleted_return_disappears_from_rekap():
    db = _seed_rollup_db()
    run(rollup.recompute_daily(db, "A1", "2026-10-21"))
    for r in db.marketing_returns.docs:
        if r["id"] in ("new", "free"):
            r["status"] = "rejected"
    res = run(rollup.recompute_daily(db, "A1", "2026-10-21"))
    assert res["action"] == "deleted" and _daily(db, "2026-10-21") is None


def test_flags_fire_for_module_only_returns():
    flags = mret.evaluate_flags({"returns_pct": 20.0, "returned_orders": 0, "returned_module_count": 3,
                                 "returned_amount": 200, "revenue_net_returns": 800})
    assert flags and "3 retur modul" in flags[0]["message"]


# ══════════════════════════════════════════════════════════════════════════════
# No.10b — toko baru → akun pendapatan sendiri; alias tiktokshop
# ══════════════════════════════════════════════════════════════════════════════
def _coa(code, name, active=True, group=False):
    return {"code": code, "name": name, "type": "REVENUE", "is_group": group, "active": active,
            "parent_code": code[:5] + "0" if not group else "4-1000", "flags": {"is_sales": True}}


def _seed_coa_db():
    db = FakeDB()
    db.rahaza_coa_accounts.docs += [
        _coa("4-1110", "Penjualan Online Shop – Shopee", group=True),
        _coa("4-1111", "Penjualan – Shopee Grosirhijabsragen"),
        _coa("4-1112", "Penjualan – Shopee Daluna", active=False),
        _coa("4-1114", "Penjualan – Shopee Lain-lain"),
        _coa("4-1117", "Penjualan – Shopee Sukma"),
        _coa("4-1120", "Penjualan Online Shop – TikTok", group=True),
        _coa("4-1121", "Penjualan – TikTok Daluna"),
        _coa("4-1126", "Penjualan – TikTok Lain-lain"),
    ]
    db.marketing_platform_accounts.docs += [
        {"id": "s1", "account_code": "SHP-01", "account_name": "Shopee GHS", "platform": "shopee",
         "coa_revenue_code": "4-1111", "ar_account_code": "1-1303-SHP-01"},
        {"id": "t1", "account_code": "TTK-01", "account_name": "TikTok Daluna", "platform": "tiktok",
         "coa_revenue_code": "4-1121", "ar_account_code": "1-1303-TTK-01"},
    ]
    return db


def test_platform_alias_tiktokshop_is_tiktok():
    assert fs.canonical_platform("tiktokshop") == "tiktok"
    assert fs.revenue_group_for("TikTokShop") == "4-1120"
    assert fs.revenue_group_for("tiktok") == "4-1120"
    assert fs.revenue_group_for("lazada") is None
    from routes import marketing_accounts as ma
    assert {"tiktok", "tiktokshop"} <= set(ma.VALID_PLATFORMS)
    assert ma.PLATFORM_TO_COA_CHANNEL["tiktok"] == ma.PLATFORM_TO_COA_CHANNEL["tiktokshop"] == "tiktok"


def test_new_store_gets_own_revenue_account_not_catchall():
    db = _seed_coa_db()
    res = run(fs.ensure_store_revenue_account(db, {"account_code": "SHP-99", "account_name": "Shopee Uji",
                                                   "platform": "shopee"}))
    assert res == {"code": "4-1118", "created": True}
    acc = run(db.rahaza_coa_accounts.find_one({"code": "4-1118"}))
    assert acc["parent_code"] == "4-1110" and acc["name"] == "Penjualan – Shopee Uji"
    assert acc["flags"] == {"store_account_code": "SHP-99", "is_sales": True, "channel": "shopee"}
    res2 = run(fs.ensure_store_revenue_account(db, {"account_code": "TTK-99", "account_name": "TikTok Uji",
                                                    "platform": "tiktokshop"}))
    assert res2 == {"code": "4-1127", "created": True}


def test_new_store_reuses_unused_same_name_account_and_never_catchall():
    db = _seed_coa_db()
    res = run(fs.ensure_store_revenue_account(db, {"account_code": "SHP-07", "account_name": "Shopee Daluna",
                                                   "platform": "shopee"}))
    assert res == {"code": "4-1112", "created": False}
    assert run(db.rahaza_coa_accounts.find_one({"code": "4-1112"}))["active"] is True
    res = run(fs.ensure_store_revenue_account(db, {"account_code": "SHP-08", "account_name": "Lain-lain",
                                                   "platform": "shopee"}))
    assert res["code"] not in ("4-1114",) and res["created"] is True


def test_full_group_raises_instead_of_falling_back():
    db = _seed_coa_db()
    for n in range(2, 10):
        db.rahaza_coa_accounts.docs.append(_coa(f"4-112{n}", f"Penjualan – TikTok X{n}"))
    with pytest.raises(ValueError):
        run(fs.ensure_store_revenue_account(db, {"account_code": "TTK-50", "account_name": "TikTok Baru",
                                                 "platform": "tiktok"}))


def test_sync_stores_handles_tiktokshop_and_writes_no_channel_map():
    db = _seed_coa_db()
    db.marketing_platform_accounts.docs.append(
        {"id": "t9", "account_code": "TTK-98", "account_name": "TikTok Shop Uji", "platform": "tiktokshop",
         "ar_account_code": "1-1303-TTK-98"})
    db.rahaza_channel_gl_mapping.docs.append(
        {"id": "m1", "channel_key": "SHP-01", "platform": "shopee", "credit_revenue": "4-1114",
         "debit_ar": "1-1303", "active": False})
    report = {}
    run(fs._sync_stores(db, report))
    t9 = run(db.marketing_platform_accounts.find_one({"id": "t9"}))
    assert t9["coa_revenue_code"] == "4-1127" and t9["coa_receivable_code"] == "1-1303-TTK-98"
    assert report["stores"]["revenue_created"] == ["4-1127"]
    # toko lama tidak diubah; peta channel tidak dibuat/dihidupkan/ditimpa
    assert run(db.marketing_platform_accounts.find_one({"id": "s1"}))["coa_revenue_code"] == "4-1111"
    assert ("rahaza_channel_gl_mapping", "insert_one") not in db.log
    assert ("rahaza_channel_gl_mapping", "update_one") not in db.log
    m1 = db.rahaza_channel_gl_mapping.docs[0]
    assert m1["active"] is False and m1["credit_revenue"] == "4-1114"


# ══════════════════════════════════════════════════════════════════════════════
# D3 — endpoint peta channel untuk toko marketplace = baca-saja / 410; menu dilepas
# ══════════════════════════════════════════════════════════════════════════════
def test_channel_map_rejects_marketplace_writes_with_410():
    from routes import rahaza_channel_gl_mapping as cgl
    db = FakeDB()
    db.marketing_platform_accounts.docs.append({"id": "s1", "account_code": "SHP-01"})
    for kw in ({"platform": "shopee"}, {"platform": "TikTokShop"}, {"channel_key": "shp-01"}):
        with pytest.raises(HTTPException) as e:
            run(cgl._reject_if_marketplace(db, **kw))
        assert e.value.status_code == 410 and "Kelola Akun" in e.value.detail
    run(cgl._reject_if_marketplace(db, platform="maklon", channel_key="maklon_snbm"))   # non-marketplace lolos


def test_channel_map_seed_endpoint_is_gone():
    src = open(os.path.join(BACKEND, "routes", "rahaza_channel_gl_mapping.py"), encoding="utf-8").read()
    seed = src[src.index("async def seed_da_channels"):]
    assert "raise HTTPException(410, GONE_MESSAGE)" in seed and "insert_one" not in seed


def test_portal_nav_hides_channel_gl_menu():
    nav = open(os.path.join(REPO, "frontend", "src", "components", "erp", "portal-shell", "portalNav.js"),
               encoding="utf-8").read()
    assert not re.search(r"id:\s*'fin-channel-gl'", nav)


# ══════════════════════════════════════════════════════════════════════════════
# Seeder data demo tidak dipanggil di handler GET
# ══════════════════════════════════════════════════════════════════════════════
SEEDER_CALL = re.compile(r"^(seed_\w*if_empty|ensure_demo_\w+|seed_demo_products)$")
GET_FILES = ["marketing_returns_routes.py", "marketing_account_health_routes.py", "marketing_complaints_routes.py",
             "marketing_content_calendar_routes.py", "marketing_discounts_routes.py",
             "marketing_live_sessions_routes.py", "marketing_live_analytics.py",
             "marketing_product_launches_routes.py", "marketing_reviews_routes.py", "marketing_samples_routes.py",
             "marketing_catalog_mgmt.py", "marketing_kol_creators.py", "marketing_livehost_hosts.py"]


def _called_names(fn):
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            out.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


def _is_get(fn):
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "get":
            return True
    return False


@pytest.mark.parametrize("fname", GET_FILES)
def test_get_handlers_do_not_seed_demo_data(fname):
    tree = ast.parse(open(os.path.join(BACKEND, "routes", fname), encoding="utf-8").read())
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
    for name, fn in fns.items():
        called = _called_names(fn)
        if _is_get(fn) or name == "_lp_ready":
            bad = sorted(c for c in called if SEEDER_CALL.match(c or ""))
            assert not bad, f"{fname}:{name} masih memanggil seeder {bad}"


# ══════════════════════════════════════════════════════════════════════════════
# Nota kredit benar-benar terbit (gl_mode settlement, tanpa jurnal) & idempoten
# ══════════════════════════════════════════════════════════════════════════════
def test_issue_credit_note_creates_links_and_is_idempotent(monkeypatch):
    async def fake_number(db, coll, field, prefix, width):
        return f"{prefix}001"
    monkeypatch.setattr(rr, "gen_prefixed_number", fake_number)
    db = FakeDB()
    ret = {"id": "R1", "status": "completed", "refund_amount": 215998.0, "qty": 2, "account_id": "A1",
           "account_name": "Shopee GHS", "platform": "shopee", "product": "Aisar", "reason_label": "Cacat",
           "date": "2026-10-23", "order_id": ""}
    db.marketing_returns.docs.append(dict(ret))
    out = run(rr._issue_credit_note(db, dict(ret), {"email": "uji@x"}))
    cn = out["credit_note"]
    assert out["created"] is True and cn["gl_mode"] == "settlement" and cn["total"] == 215998.0
    assert cn["return_id"] == "R1" and not cn.get("gl_je_id")
    linked = run(db.marketing_returns.find_one({"id": "R1"}))
    assert linked["credit_note_id"] == cn["id"] and linked["credit_note_number"] == cn["cn_number"]
    assert linked["credit_note_status"] == "issued"
    assert db.rahaza_journal_entries.docs == [] and db.rahaza_journal_lines.docs == []
    again = run(rr._issue_credit_note(db, linked, {"email": "uji@x"}))
    assert again["created"] is False and len(db.rahaza_credit_notes.docs) == 1


def test_issue_credit_note_relinks_orphan_and_rejects_zero_refund(monkeypatch):
    db = FakeDB()
    db.rahaza_credit_notes.docs.append({"id": "CN9", "cn_number": "CN-1", "return_id": "R2", "status": "issued"})
    db.marketing_returns.docs.append({"id": "R2", "refund_amount": 100})
    out = run(rr._issue_credit_note(db, {"id": "R2", "refund_amount": 100}, {}))
    assert out["created"] is False and run(db.marketing_returns.find_one({"id": "R2"}))["credit_note_id"] == "CN9"
    db.marketing_returns.docs.append({"id": "R3", "refund_amount": 0})
    with pytest.raises(HTTPException) as e:
        run(rr._issue_credit_note(db, {"id": "R3", "refund_amount": 0}, {}))
    assert e.value.status_code == 400 and db.rahaza_credit_notes.docs[-1]["id"] == "CN9"


def test_complete_endpoint_issues_credit_note_source():
    src = open(os.path.join(BACKEND, "routes", "marketing_returns_routes.py"), encoding="utf-8").read()
    body = src[src.index("async def complete_return"):src.index("@router.post(\"/sync-to-warehouse\")")]
    assert "_issue_credit_note(" in body and '"credit_note": credit_note' in body
