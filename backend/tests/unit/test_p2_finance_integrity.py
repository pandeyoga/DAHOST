"""Uji unit HERMETIK paket P2 (2026-11-02) — integritas keuangan & akuntansi. Tanpa server, tanpa Mongo:
DB diganti `FakeDB` sederhana (filter $ne/$in/$nin/$gt/$regex/$or/$expr, update $set & pipeline,
aggregate $match+$group) supaya jalur kode ASLI endpoint ikut teruji, bukan salinannya.

Butir yang dijaga (audit 2026-11-01, f.md No.34–56 & m.md No.1–3):
  1 K-1/K-2 kunci jurnal pencairan/penarikan per dokumen · 2 restart tidak menimpa pilihan Finance ·
  3 COA grup · 4 periode · 5 nota kredit · 6 dashboard · 7 laporan eksekutif · 8 impor jurnal ·
  9 anggaran · 12/13 aset tetap · 14 guard API · 15 AR marketplace · 16 Selisih Persediaan.

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import asyncio
import copy
import io
import os
import re
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import routes.marketing_settlements as ms  # noqa: E402
import routes.marketing_withdrawals as mw  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402
import routes.rahaza_coa as coa  # noqa: E402
import routes.rahaza_periods as per  # noqa: E402
import routes.rahaza_year_end as ye  # noqa: E402
import routes.rahaza_finance as rf  # noqa: E402
import routes.sales_direct as sd  # noqa: E402
import routes.dashboard_routes as dash  # noqa: E402
import routes.dewi_executive_report as ex  # noqa: E402
import routes.rahaza_budget as bud  # noqa: E402
import routes.rahaza_bank_transfers as bt  # noqa: E402
import routes.warehouse as wh  # noqa: E402
import routes.rahaza_fixed_assets as fa  # noqa: E402
import routes.rahaza_journals as rj  # noqa: E402
import core.journal_import as ji  # noqa: E402
import core.payout_banks as payout_banks  # noqa: E402
import utils.waktu as waktu  # noqa: E402
from data.coa_unified import DA_UNIFIED_ACCOUNTS  # noqa: E402


# ══════════════════════════════ FAKE DB ═══════════════════════════════════════
def _get(doc, path):
    cur = doc
    for part in path.split("."):
        if isinstance(cur, list):
            return [x.get(part) if isinstance(x, dict) else None for x in cur]
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _eq(v, target):
    if isinstance(v, list) and not isinstance(target, list):
        return target in v
    return v == target


def _match_val(v, cond):
    if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            if op == "$ne" and _eq(v, arg):
                return False
            if op == "$in" and not any(_eq(v, a) for a in arg):
                return False
            if op == "$nin" and any(_eq(v, a) for a in arg):
                return False
            if op in ("$gt", "$gte", "$lt", "$lte"):
                if v is None or isinstance(v, list):
                    return False
                if op == "$gt" and not v > arg:
                    return False
                if op == "$gte" and not v >= arg:
                    return False
                if op == "$lt" and not v < arg:
                    return False
                if op == "$lte" and not v <= arg:
                    return False
            if op == "$regex" and not (isinstance(v, str) and re.search(arg, v)):
                return False
            if op == "$exists" and ((v is not None) != bool(arg)):
                return False
            if op == "$type" and arg == "string" and not isinstance(v, str):
                return False
        return True
    return _eq(v, cond)


def _ev(e, doc):
    if isinstance(e, str) and e.startswith("$"):
        return _get(doc, e[1:])
    if isinstance(e, dict) and len(e) == 1 and next(iter(e)).startswith("$"):
        op, a = next(iter(e.items()))
        if op == "$add":
            return sum(float(_ev(x, doc) or 0) for x in a)
        if op == "$subtract":
            return float(_ev(a[0], doc) or 0) - float(_ev(a[1], doc) or 0)
        if op == "$ifNull":
            v = _ev(a[0], doc)
            return v if v is not None else _ev(a[1], doc)
        if op == "$round":
            return round(float(_ev(a[0], doc) or 0), a[1])
        if op == "$max":
            return max(_ev(x, doc) for x in a)
        if op == "$cond":
            return _ev(a[1], doc) if _ev(a[0], doc) else _ev(a[2], doc)
        if op in ("$gte", "$lte", "$gt", "$lt", "$eq"):
            x, y = _ev(a[0], doc), _ev(a[1], doc)
            return {"$gte": x >= y, "$lte": x <= y, "$gt": x > y, "$lt": x < y, "$eq": x == y}[op]
    return e


def _matches(doc, filt):
    for k, cond in (filt or {}).items():
        if k == "$or":
            if not any(_matches(doc, f) for f in cond):
                return False
        elif k == "$and":
            if not all(_matches(doc, f) for f in cond):
                return False
        elif k == "$expr":
            if not _ev(cond, doc):
                return False
        elif not _match_val(_get(doc, k), cond):
            return False
    return True


def _set_path(doc, path, value):
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


class _Res:
    def __init__(self, matched=0, modified=0):
        self.matched_count, self.modified_count = matched, modified


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction=1):
        keys = key if isinstance(key, list) else [(key, direction)]
        for k, d in reversed(keys):
            self.rows.sort(key=lambda r: (_get(r, k) is None, _get(r, k) or ""), reverse=d == -1)
        return self

    def skip(self, n):
        self.rows = self.rows[n:]
        return self

    def limit(self, n):
        self.rows = self.rows[:n] if n else self.rows
        return self

    async def to_list(self, n=None):
        return list(self.rows if n is None else self.rows[:n])

    def __aiter__(self):
        self._it = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self):
        self.docs = []

    def _find(self, filt):
        return [d for d in self.docs if _matches(d, filt)]

    def find(self, filt=None, projection=None):
        return FakeCursor([copy.deepcopy(d) for d in self._find(filt)])

    async def find_one(self, filt=None, projection=None, sort=None):
        rows = [copy.deepcopy(d) for d in self._find(filt)]
        if sort:
            rows = FakeCursor(rows).sort(sort).rows
        return rows[0] if rows else None

    async def count_documents(self, filt=None):
        return len(self._find(filt))

    async def distinct(self, field, filt=None):
        return sorted({_get(d, field) for d in self._find(filt)} - {None})

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))
        return _Res(1, 1)

    async def insert_many(self, docs):
        for d in docs:
            await self.insert_one(d)

    def _apply(self, doc, update):
        if isinstance(update, list):
            for stage in update:
                vals = {k: _ev(v, doc) for k, v in stage["$set"].items()}
                doc.update(vals)
            return
        for k, v in (update.get("$set") or {}).items():
            _set_path(doc, k, v)
        for k, v in (update.get("$inc") or {}).items():
            _set_path(doc, k, float(_get(doc, k) or 0) + v)

    async def update_one(self, filt, update, upsert=False):
        rows = self._find(filt)
        if not rows:
            if upsert:
                d = {k: v for k, v in filt.items() if not k.startswith("$") and not isinstance(v, dict)}
                d.update(update.get("$setOnInsert") or {})
                self._apply(d, {"$set": update.get("$set") or {}})
                self.docs.append(d)
            return _Res(0, 0)
        before = copy.deepcopy(rows[0])
        self._apply(rows[0], update)
        return _Res(1, int(before != rows[0]))

    async def update_many(self, filt, update):
        rows = self._find(filt)
        for d in rows:
            self._apply(d, update)
        return _Res(len(rows), len(rows))

    async def find_one_and_update(self, filt, update, return_document=None, **_):
        rows = self._find(filt)
        if not rows:
            return None
        self._apply(rows[0], update)
        return copy.deepcopy(rows[0])

    async def delete_one(self, filt):
        rows = self._find(filt)
        if rows:
            self.docs.remove(rows[0])
        return _Res(len(rows[:1]), len(rows[:1]))

    async def delete_many(self, filt):
        rows = self._find(filt)
        for d in rows:
            self.docs.remove(d)
        return _Res(len(rows), len(rows))

    def aggregate(self, pipeline):
        rows = [copy.deepcopy(d) for d in self.docs]
        for st in pipeline:
            if "$match" in st:
                rows = [r for r in rows if _matches(r, st["$match"])]
            elif "$group" in st:
                spec = dict(st["$group"])
                gid = spec.pop("_id")
                groups = {}
                for r in rows:
                    if isinstance(gid, dict):
                        key = tuple((k, _ev(v, r)) for k, v in gid.items())
                        kid = dict(key)
                    else:
                        kid = _ev(gid, r) if gid is not None else None
                        key = kid
                    g = groups.setdefault(key, {"_id": kid, **{f: 0 for f in spec}})
                    for f, acc in spec.items():
                        g[f] += float(_ev(acc["$sum"], r) or 0)
                rows = list(groups.values())
        return FakeCursor(rows)


class FakeDB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, FakeCollection())

    __getitem__ = __getattr__


class FakeRequest:
    def __init__(self, body=None, query=None):
        self._body = body or {}
        self.query_params = query or {}
        self.state = type("S", (), {"user": {"email": "uji@x"}})()

    async def json(self):
        return copy.deepcopy(self._body)


USER = {"id": "u-fin", "name": "Finance Uji", "email": "fin@x", "role": "superadmin"}


async def _auth(*_a, **_k):
    return USER


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    for mod in (ms, mw, pp, coa, per, ye, rf, sd, dash, ex, bud, bt, wh, fa):
        if hasattr(mod, "get_db"):
            monkeypatch.setattr(mod, "get_db", lambda d=d: d)
    for mod, name in ((ms, "_require_finance"), (mw, "_require_finance"), (pp, "_require_fin"),
                      (coa, "_require_fin"), (per, "_require_fin_mgr"), (ye, "_require_fin_mgr"),
                      (rf, "_require_fin"), (rf, "require_auth"), (wh, "require_auth"), (fa, "require_auth"),
                      (per, "require_auth")):
        monkeypatch.setattr(mod, name, _auth)

    async def _nolog(*_a, **_k):
        return None
    for mod in (pp, coa, per, ye):
        monkeypatch.setattr(mod, "log_activity", _nolog)
    return d


@pytest.fixture
def je_sink(monkeypatch, db):
    """_create_posted_je palsu: menulis kepala JE (dengan baris) ke FakeDB, mencatat argumen."""
    calls = []

    async def fake_create(db_, je_date, memo, source_module, source_ref, lines_raw, user,
                          status="posted", allow_closed_period=False, **_kw):
        lines = [dict(ln) for ln in lines_raw if float(ln.get("debit") or 0) or float(ln.get("credit") or 0)]
        jid = f"je-{len(calls) + 1}"
        doc = {"id": jid, "je_number": f"JE-{len(calls) + 1:04d}", "date": je_date.isoformat(), "memo": memo,
               "source_module": source_module, "source_ref": source_ref, "status": status, "lines": lines}
        calls.append(doc)
        await db_.rahaza_journal_entries.insert_one(doc)
        if status == "posted":
            for ln in lines:
                await db_.rahaza_journal_lines.insert_one({**ln, "je_id": jid, "date": doc["date"],
                                                           "source_module": source_module, "source_ref": source_ref})
        return {"ok": True, "je_id": jid, "je_number": doc["je_number"]}

    monkeypatch.setattr(rp, "_create_posted_je", fake_create)
    return calls


# ══════════════════════ 1. K-1 / K-2 — kunci per dokumen ══════════════════════
STORE_A = {"id": "acc-A", "account_name": "Shopee A", "platform": "shopee", "account_code": "SHP-01",
           "ar_account_code": "1-1303-SHP-01", "coa_revenue_code": "4-1111", "coa_cash_code": "1-1201"}
STORE_B = {"id": "acc-B", "account_name": "Shopee B", "platform": "shopee", "account_code": "SHP-02",
           "ar_account_code": "1-1303-SHP-02", "coa_revenue_code": "4-1115", "coa_cash_code": "1-1201"}


def _stl(sid, acc, number, gross, net, **extra):
    d = {"id": sid, "account_id": acc["id"], "account_name": acc["account_name"], "platform": "shopee",
         "settlement_id": number, "settlement_date": "2026-10-15", "gross_sales": gross, "net_payout": net,
         "je_id": None, "je_number": None, "je_status": None}
    d.update(extra)
    return d


@pytest.fixture
def stores(db, monkeypatch):
    db.marketing_platform_accounts.docs = [copy.deepcopy(STORE_A), copy.deepcopy(STORE_B)]
    for code in ("1-1303-SHP-01", "1-1303-SHP-02", "1-1201"):
        db.rahaza_coa_accounts.docs.append({"code": code, "active": True, "is_group": False})

    async def fake_resolve(db_, account):
        return {"codes": {**ms.COA, "receivable": account["ar_account_code"],
                          "revenue": account["coa_revenue_code"]}, "sources": {}}
    monkeypatch.setattr(ms, "_resolve_coa", fake_resolve)
    return db


def test_k1_dua_toko_nomor_pencairan_sama_dua_jurnal_terpisah(stores, je_sink):
    db = stores
    db.marketing_settlements.docs = [
        _stl("s-A", STORE_A, "PCR-1001", 1_000_000, 890_000, seller_discount=50_000,
             platform_commission=45_000, platform_service_fee=15_000),
        _stl("s-B", STORE_B, "PCR-1001", 500_000, 475_000, platform_commission=25_000),
    ]
    ra = run(ms.create_draft_journal("s-A", FakeRequest()))
    rb = run(ms.create_draft_journal("s-B", FakeRequest()))
    assert not rb.get("already"), "toko B dulu menempel ke jurnal toko A (K-1)"
    assert ra["je_id"] != rb["je_id"] and len(je_sink) == 2
    assert {j["source_ref"] for j in je_sink} == {"PCR-1001@s-A", "PCR-1001@s-B"}
    jb = next(j for j in je_sink if j["source_ref"] == "PCR-1001@s-B")
    by = {(ln["account_code"], ln["debit"], ln["credit"]) for ln in jb["lines"]}
    assert ("1-1303-SHP-02", 475_000, 0) in by and ("4-1115", 0, 500_000) in by
    ja = next(j for j in je_sink if j["source_ref"] == "PCR-1001@s-A")
    assert any(ln["account_code"] == "1-1303-SHP-01" and ln["debit"] == 890_000 for ln in ja["lines"])
    # idempoten per dokumen
    again = run(ms.create_draft_journal("s-B", FakeRequest()))
    assert again["already"] and again["je_number"] == rb["je_number"] and len(je_sink) == 2


def test_k1_jurnal_lama_kunci_nomor_mentah_tetap_milik_dokumennya(stores, je_sink):
    db = stores
    legacy = {"id": "je-old", "je_number": "JE-OLD", "source_module": ms.SOURCE_MODULE, "source_ref": "PCR-1001",
              "status": "draft", "memo": "Dana dilepas shopee ke saldo toko — Shopee A (PCR-1001)",
              "lines": [{"account_code": "1-1303-SHP-01", "debit": 890_000, "credit": 0},
                        {"account_code": "4-1111", "debit": 0, "credit": 890_000}]}
    db.rahaza_journal_entries.docs.append(legacy)
    db.marketing_settlements.docs = [
        _stl("s-A", STORE_A, "PCR-1001", 890_000, 890_000, je_id="je-old", je_number="JE-OLD",
             je_status="draft", coa_used={"receivable": "1-1303-SHP-01"}),
        # warisan bug: dokumen toko B ikut ditautkan ke jurnal toko A
        _stl("s-B", STORE_B, "PCR-1001", 500_000, 475_000, platform_commission=25_000,
             je_id="je-old", je_number="JE-OLD", je_status="draft"),
    ]
    ra = run(ms.create_draft_journal("s-A", FakeRequest()))
    assert ra["already"] and ra["je_number"] == "JE-OLD"
    docB = run(db.marketing_settlements.find_one({"id": "s-B"}))
    assert run(ms._je_still_binding(db, docB)) is False, "tautan ke jurnal toko lain tidak boleh mengunci"
    assert run(ms._je_still_binding(db, run(db.marketing_settlements.find_one({"id": "s-A"})))) is True
    with pytest.raises(HTTPException) as e:
        run(ms.post_settlement_journal("s-B", FakeRequest()))
    assert e.value.status_code == 409
    assert run(db.marketing_settlements.find_one({"id": "s-B"}))["je_id"] is None
    rb = run(ms.create_draft_journal("s-B", FakeRequest()))
    assert not rb.get("already") and je_sink[-1]["source_ref"] == "PCR-1001@s-B"


def test_no1_edit_pencairan_dicek_duplikat_dan_stempel_toko(stores):
    db = stores
    db.marketing_settlements.docs = [_stl("s-1", STORE_A, "PCR-1001", 100, 100),
                                     _stl("s-2", STORE_A, "PCR-2000", 100, 100)]
    body = ms.SettlementIn(account_id="acc-A", platform="shopee", settlement_id="PCR-1001",
                           settlement_date="2026-10-15", gross_sales=100, net_payout=100)
    with pytest.raises(HTTPException) as e:
        run(ms.update_settlement("s-2", body, FakeRequest()))
    assert e.value.status_code == 409
    moved = ms.SettlementIn(account_id="acc-B", platform="tiktok", settlement_id="PCR-2000",
                            settlement_date="2026-10-15", gross_sales=100, net_payout=100)
    out = run(ms.update_settlement("s-2", moved, FakeRequest()))["data"]
    assert out["account_name"] == "Shopee B" and out["platform"] == "shopee"


def _wd(wid, acc, ref, amount):
    return {"id": wid, "account_id": acc["id"], "account_name": acc["account_name"], "platform": "shopee",
            "withdrawal_date": "2026-10-20", "amount": amount, "reference": ref, "cash_code": None,
            "je_id": None, "je_number": None, "je_status": None, "bank_txn_id": None}


def test_k2_penarikan_referensi_sama_dua_toko_dua_jurnal(stores, je_sink):
    db = stores
    db.marketing_platform_withdrawals.docs = [_wd("w-A", STORE_A, "WD-REF-777", 800_000),
                                              _wd("w-B", STORE_B, "WD-REF-777", 400_000)]
    run(mw.create_draft_journal("w-A", FakeRequest()))
    rb = run(mw.create_draft_journal("w-B", FakeRequest()))
    assert not rb.get("already") and len(je_sink) == 2
    jb = je_sink[1]
    assert jb["source_ref"] == "WD-REF-777@w-B"
    assert ("1-1303-SHP-02", 0, 400_000) in {(ln["account_code"], ln["debit"], ln["credit"]) for ln in jb["lines"]}


def test_no2_edit_penarikan_dan_impor_referensi_unik_per_toko(stores, monkeypatch):
    db = stores
    db.marketing_platform_withdrawals.docs = [_wd("w-1", STORE_A, "WD-REF-777", 10), _wd("w-2", STORE_A, "WD-C1", 10)]
    body = mw.WithdrawalIn(account_id="acc-A", withdrawal_date="2026-10-20", amount=10, reference="WD-REF-777")
    with pytest.raises(HTTPException) as e:
        run(mw.update_withdrawal("w-2", body, FakeRequest()))
    assert e.value.status_code == 409

    async def big(*_a, **_k):
        return 1e12
    monkeypatch.setattr(mw._bal, "available_balance", big)
    rows = [{"reference": "R-9", "amount": 5, "ok": True}, {"reference": "R-9", "amount": 5, "ok": True}]
    out = run(mw._annotate_rows(db, STORE_A, rows))
    assert out[0]["ok"] is True and out[1]["ok"] is False and out[1]["duplicate"] is True


# ══════════════════ 2. restart tidak menimpa pilihan Finance ═══════════════════
def test_upgrade_profil_menghormati_pilihan_pengguna_dan_memperbaiki_nilai_lama():
    defaults = {p["event_type"]: p["mapping"] for p in pp.DEFAULT_PROFILES}
    user_doc = {"updated_by": "u-fin", "user_roles": ["debit_cash_default"]}
    out = pp.upgrade_profile_mapping("ar_payment", {"debit_cash_default": "1-1202", "credit_ar": "1-1301"},
                                     user_doc, defaults["ar_payment"])
    assert out["debit_cash_default"] == "1-1202"
    # profil lama disentuh pengguna (tanpa penanda) → hanya nilai lama yang diketahui salah diperbaiki
    out = pp.upgrade_profile_mapping("ap_invoice", {"debit_expense_default": "6-2200"},
                                     {"updated_by": "u-lama"}, defaults["ap_invoice"])
    assert out["debit_expense_default"] == "6-2900"
    out = pp.upgrade_profile_mapping("ap_invoice", {"debit_expense_default": "6-2210"},
                                     {"updated_by": "u-lama"}, defaults["ap_invoice"])
    assert out["debit_expense_default"] == "6-2210"
    # belum pernah disentuh → bawaan dipasang
    out = pp.upgrade_profile_mapping("ap_invoice", {"debit_expense_default": "6-2210"},
                                     {"updated_by": "coa-canonical-migration"}, defaults["ap_invoice"])
    assert out["debit_expense_default"] == "6-2900"
    # peran yang sengaja dihapus tidak diisi ulang
    out = pp.upgrade_profile_mapping("ar_invoice", {"debit_ar": "1-1301"},
                                     {"updated_by": "u-fin", "user_removed_roles": ["credit_tax_output"]},
                                     defaults["ar_invoice"])
    assert "credit_tax_output" not in out


def test_profil_diubah_lalu_restart_tetap(db):
    for code in ("1-1202", "1-1301", "1-1201", "6-2730", "1-2501"):
        db.rahaza_coa_accounts.docs.append({"code": code, "active": True, "is_group": False})
    run(pp.seed_posting_profiles(db))
    ar_pay = run(db.rahaza_posting_profiles.find_one({"event_type": "ar_payment"}))
    mapping = dict(ar_pay["mapping"], debit_cash_default="1-1202")
    run(pp.update_profile("ar_payment", FakeRequest({"mapping": mapping})))
    ari = run(db.rahaza_posting_profiles.find_one({"event_type": "ar_invoice"}))
    m2 = {k: v for k, v in ari["mapping"].items() if k != "credit_tax_output"}
    for code in m2.values():
        if not any(a["code"] == code for a in db.rahaza_coa_accounts.docs):
            db.rahaza_coa_accounts.docs.append({"code": code, "active": True, "is_group": False})
    run(pp.update_profile("ar_invoice", FakeRequest({"mapping": m2})))
    run(pp.upgrade_posting_profiles(db))   # == restart
    assert run(db.rahaza_posting_profiles.find_one({"event_type": "ar_payment"}))["mapping"]["debit_cash_default"] == "1-1202"
    assert "credit_tax_output" not in run(db.rahaza_posting_profiles.find_one({"event_type": "ar_invoice"}))["mapping"]


# ══════════════════════════ 2/3. COA akun grup ════════════════════════════════
def test_coa_tolak_centang_grup_pada_akun_bertransaksi(db):
    db.rahaza_coa_accounts.docs = [{"id": "a1", "code": "6-2900", "name": "Beban", "type": "EXPENSE", "is_group": False},
                                   {"id": "a2", "code": "6-2950", "name": "Baru", "type": "EXPENSE", "is_group": False}]
    db.rahaza_journal_lines.docs = [{"account_code": "6-2900", "debit": 5_300_000, "credit": 0}]
    with pytest.raises(HTTPException) as e:
        run(coa.update_account("a1", FakeRequest({"is_group": True})))
    assert e.value.status_code == 400 and "1 baris jurnal" in e.value.detail
    out = run(coa.update_account("a2", FakeRequest({"is_group": True})))
    assert out["is_group"] is True


def test_seed_coa_tidak_mencentang_ulang_grup_akun_bertransaksi_atau_pilihan_pengguna(db):
    db.rahaza_coa_accounts.docs = [
        {"id": "g1", "code": "1-1600", "is_group": False, "type": "ASSET"},
        {"id": "g2", "code": "1-1300", "is_group": False, "type": "ASSET", "is_group_user_set": True},
        {"id": "g3", "code": "1-2000", "is_group": False, "type": "ASSET"},
    ]
    db.rahaza_journal_lines.docs = [{"account_code": "1-1600", "debit": 700_000, "credit": 0}]
    run(coa.seed_coa_accounts(db))
    by = {a["code"]: a for a in db.rahaza_coa_accounts.docs}
    assert by["1-1600"]["is_group"] is False      # punya jurnal
    assert by["1-1300"]["is_group"] is False      # sengaja di-uncheck pengguna
    assert by["1-2000"]["is_group"] is True       # belum disentuh & tanpa jurnal → tetap dirapikan
    # 16: akun Selisih Persediaan tercipta otomatis & idempoten
    assert by["5-1950"]["type"] == "COGS" and by["5-1950"]["parent_code"] == "5-0000" and not by["5-1950"]["is_group"]
    run(coa.seed_coa_accounts(db))
    assert sum(1 for a in db.rahaza_coa_accounts.docs if a["code"] == "5-1950") == 1


# ══════════════════════════════ 4. periode ═════════════════════════════════════
def test_periode_belum_berakhir_ditolak_murni():
    assert per.period_not_ended_error("2026-11", date(2026, 11, 2), "Tutup periode")
    assert per.period_not_ended_error("2026-12", date(2026, 11, 2), "Kunci")
    assert per.period_not_ended_error("2026-10", date(2026, 10, 31), "Tutup")   # hari terakhir = belum berakhir
    assert per.period_not_ended_error("2026-10", date(2026, 11, 2), "Tutup") is None
    assert ye.year_end_allowed(2026, date(2026, 12, 31)) is False
    assert ye.year_end_allowed(2026, date(2027, 1, 1)) is True


def test_endpoint_tutup_kunci_periode_dan_tutup_tahun(db, monkeypatch):
    monkeypatch.setattr(waktu, "today_wib", lambda: date(2026, 11, 2))
    db.rahaza_periods.docs = [{"period_code": "2026-11", "status": "open"},
                              {"period_code": "2026-10", "status": "open"},
                              {"period_code": "2026-12", "status": "closed"}]
    with pytest.raises(HTTPException) as e:
        run(per.close_period("2026-11", FakeRequest()))
    assert e.value.status_code == 400
    assert run(per.close_period("2026-10", FakeRequest()))["status"] == "closed"
    with pytest.raises(HTTPException) as e:   # data lama: Desember masa depan sudah closed → tetap tak bisa di-lock
        run(per.lock_period("2026-12", FakeRequest()))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        run(ye.close_year(FakeRequest({"year": 2026})))
    assert e.value.status_code == 400 and "belum berakhir" in e.value.detail


# ═════════════════════════ 5. nota kredit & pembayaran ═════════════════════════
def test_pembayaran_ar_memperhitungkan_nota_kredit_dan_tolak_lebih_bayar(db):
    db.rahaza_ar_invoices.docs = [{"id": "i1", "total": 1_110_000, "paid_amount": 0, "balance": 888_000,
                                   "credited_amount": 222_000, "status": "issued"}]

    async def pay(amount):
        g, p = rf.ar_payment_guard_and_update(amount)
        return await db.rahaza_ar_invoices.find_one_and_update(
            {"id": "i1", "status": {"$nin": ["cancelled", "void", "written_off"]}, "$expr": g}, p)
    inv = run(pay(888_000))
    assert inv["status"] == "paid" and inv["balance"] == 0 and inv["amount_due"] == 0   # dulu partial_paid, sisa 222.000
    assert run(pay(222_000)) is None   # dulu diterima → lebih bayar 222.000


def test_penjualan_langsung_bayar_melebihi_sisa_ditolak(db):
    db.rahaza_cash_accounts.docs = [{"id": "kas1", "name": "BCA"}]
    db.rahaza_ar_invoices.docs = [{"id": "i2", "total": 1_110_000, "paid_amount": 0, "credited_amount": 222_000,
                                   "balance": 888_000, "status": "issued"}]
    with pytest.raises(HTTPException) as e:
        run(sd._apply_ar_payment(db, "i2", 888_001, "kas1", "2026-10-26", USER))
    assert e.value.status_code == 400 and "888000" in e.value.detail


def test_statement_pelanggan_field_benar_tanpa_draft(db, monkeypatch):
    monkeypatch.setattr(rf, "require_auth", _auth)
    db.rahaza_customers.docs = [{"id": "c1", "name": "Toko X"}]
    db.rahaza_ar_invoices.docs = [
        {"id": "a", "customer_id": "c1", "issue_date": "2026-10-26", "status": "paid", "total": 1_110_000,
         "paid_amount": 888_000, "credited_amount": 222_000},
        {"id": "b", "customer_id": "c1", "issue_date": "2026-10-27", "status": "draft", "total": 700_000,
         "paid_amount": 0},
    ]
    out = run(rf.customer_statement("c1", FakeRequest()))
    s = out["summary"]
    assert s["count"] == 1 and s["total_paid"] == 888_000 and s["total_credited"] == 222_000 and s["outstanding"] == 0


# ════════════════════════════════ 6. dashboard ═════════════════════════════════
def test_dashboard_pendapatan_per_tanggal_faktur_dan_aging_kanonik(db):
    invs = [{"status": "issued", "issue_date": "2026-11-02", "total": 100},
            {"status": "draft", "issue_date": "2026-11-02", "total": 5_000},
            {"status": "cancelled", "issue_date": "2026-11-02", "total": 3_000},
            {"status": "paid", "issue_date": "2026-11-01", "total": 10},
            {"status": "issued", "issue_date": "2026-01-05", "total": 1},
            {"status": "issued", "issue_date": "2025-12-31", "total": 1_000}]
    assert dash.revenue_windows(invs, date(2026, 11, 2)) == {"today": 100, "mtd": 110, "ytd": 111}
    db.rahaza_ar_invoices.docs = [
        {"id": "x", "status": "issued", "total": 500, "balance": 500, "due_date": "2099-01-01"},
        {"id": "y", "status": "partial_paid", "total": 900, "balance": 400, "paid_amount": 500, "due_date": "2000-01-01"},
        {"id": "z", "status": "draft", "total": 9_999, "balance": 9_999, "due_date": "2000-01-01"},
    ]
    ag = run(dash._ar_aging(db))
    assert ag["current"] == 500 and ag["d90plus"] == 400 and ag["total"] == 900


# ═══════════════════════════ 7. laporan eksekutif ══════════════════════════════
def test_eksekutif_pendapatan_dari_akun_pendapatan_gl(db):
    db.rahaza_coa_accounts.docs = [{"code": c, "type": t, "is_group": False} for c, t in
                                   (("4-1100", "REVENUE"), ("4-1111", "REVENUE"), ("4-1400", "REVENUE"),
                                    ("2-1400", "LIABILITY"), ("1-1301", "ASSET"))]
    L = db.rahaza_journal_lines.docs
    L += [{"date": "2026-10-10", "account_code": "1-1301", "debit": 1_110_000, "credit": 0, "source_module": "ar_invoice"},
          {"date": "2026-10-10", "account_code": "4-1100", "debit": 0, "credit": 1_000_000, "source_module": "ar_invoice"},
          {"date": "2026-10-10", "account_code": "2-1400", "debit": 0, "credit": 110_000, "source_module": "ar_invoice"},
          {"date": "2026-10-15", "account_code": "4-1111", "debit": 0, "credit": 1_000_000, "source_module": "marketplace_settlement"},
          {"date": "2026-10-15", "account_code": "4-1400", "debit": 100_000, "credit": 0, "source_module": "marketplace_settlement"},
          {"date": "2026-10-31", "account_code": "4-1100", "debit": 1_000_000, "credit": 0, "source_module": "year_end_close"},
          {"date": "2026-11-01", "account_code": "4-1100", "debit": 0, "credit": 7, "source_module": "ar_invoice"}]
    assert run(ex._gl_revenue(db, "2026-10-01", "2026-10-31")) == 1_900_000   # DPP + marketplace neto, tanpa PPN


# ═══════════════════════════════ 8. impor jurnal ═══════════════════════════════
def _xlsx(rows, creator="a"):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "PETUNJUK"
    ws = wb.create_sheet(ji.SHEET_MUTASI)
    ws.append(ji.COLS_MUTASI)
    for r in rows:
        ws.append(r)
    wb.properties.creator = creator
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def imp_db(db, monkeypatch):
    db.rahaza_coa_accounts.docs = [{"code": c, "name": c, "type": "X", "active": True, "is_group": False}
                                   for c in ("1-1211", "4-1100", "6-2200")]
    n = {"i": 0}

    async def validate(db_, lines):
        return sum(ln["debit"] for ln in lines), sum(ln["credit"] for ln in lines)

    async def noop(*_a, **_k):
        return None

    async def gen(db_, d, *_a, **_k):
        n["i"] += 1
        return f"JE-{n['i']:04d}"
    monkeypatch.setattr(rj, "_validate_lines", validate)
    monkeypatch.setattr(rj, "_check_period_open", noop)
    monkeypatch.setattr(rj, "_mirror_lines", noop)
    monkeypatch.setattr(rj, "_gen_je_number", gen)
    return db


R1 = ["2026-10-01", "1-1211", "AUDIT impor terima", 1_000_000, None, "4-1100", "BKT-1"]
R2 = ["2026-10-02", "1-1211", "Token listrik", None, 350_000, "6-2200", ""]
R3 = ["2026-10-03", "1-1211", "Parkir", None, 5_000, "6-2200", ""]


def _import(db, data):
    res = run(ji.parse_workbook(db, data))
    assert res["ok"], res["errors"]
    out = run(ji.post_journals(db, USER, res["journals"], "f.xlsx"))
    return res, out


def test_impor_ulang_berkas_ditambah_satu_baris_hanya_baris_baru(imp_db):
    db = imp_db
    _, o1 = _import(db, _xlsx([R1, R2]))
    assert o1["posted_count"] == 2
    res, o2 = _import(db, _xlsx([R1, R2, R3]))
    assert o2["posted_count"] == 1 and res["skipped_existing"] == 2      # dulu 3 (2 dobel)
    res, o3 = _import(db, _xlsx([R1, R2, R3], creator="dibuka-disimpan-ulang"))
    assert o3["posted_count"] == 0 and res["skipped_existing"] == 3      # dulu dobel semua
    assert len(db.rahaza_journal_entries.docs) == 3


def test_impor_baris_kembar_sah_dihitung_per_kemunculan(imp_db):
    db = imp_db
    _, o = _import(db, _xlsx([R3, R3]))
    assert o["posted_count"] == 2
    _, o = _import(db, _xlsx([R3, R3]))
    assert o["posted_count"] == 0
    _, o = _import(db, _xlsx([R3, R3, R3]))
    assert o["posted_count"] == 1
    refs = [j["source_ref"] for j in db.rahaza_journal_entries.docs]
    assert len(set(refs)) == 3


def test_impor_mengenali_jurnal_kunci_lama(imp_db):
    db = imp_db
    db.rahaza_journal_entries.docs.append({
        "id": "old", "source_module": ji.SOURCE_MODULE, "source_ref": "import:abcd1234:mutasi:2", "status": "posted",
        "date": "2026-10-01", "memo": "AUDIT impor terima [BKT-1]",
        "lines": [{"account_code": "1-1211", "debit": 1_000_000, "credit": 0, "description": "AUDIT impor terima"},
                  {"account_code": "4-1100", "debit": 0, "credit": 1_000_000, "description": "AUDIT impor terima"}]})
    res, o = _import(db, _xlsx([R1, R2]))
    assert res["skipped_existing"] == 1 and o["posted_count"] == 1


# ═════════════════════════════════ 9. anggaran ═════════════════════════════════
def test_anggaran_pendapatan_bertanda_positif_dan_label_target():
    f = bud.budget_row_figures(10_000_000, 0, 11_000_000, "REVENUE")
    assert f["actual"] == 11_000_000 and f["variance"] == 1_000_000 and f["status"] == "above_target"
    f = bud.budget_row_figures(10_000_000, 0, 9_000_000, "REVENUE")
    assert f["status"] == "below_target" and f["variance"] == -1_000_000
    f = bud.budget_row_figures(6_000_000, 6_150_000, 0, "EXPENSE")
    assert f["actual"] == 6_150_000 and f["variance"] == -150_000 and f["status"] == "over"


# ═════════════════════════════ 12/13. aset tetap ═══════════════════════════════
@pytest.fixture
def asset_db(db, monkeypatch):
    db.rahaza_coa_accounts.docs = [{"id": f"id-{c}", "code": c, "active": True, "is_group": g} for c, g in
                                   (("1-2300", False), ("1-2301", False), ("6-2730", False), ("1-2000", True))]
    profiles = {"depreciation": {"debit_depr_expense": "6-2700", "credit_accum_depr": "1-2501"},
                "asset_disposal": {"credit_fixed_asset": "1-2500", "debit_accum_depr": "1-2501",
                                   "debit_cash": "1-1201", "debit_loss_on_disposal": "6-4200",
                                   "credit_gain_on_disposal": "4-2200"}}

    async def gm(db_, et):
        return dict(profiles.get(et, {}))
    monkeypatch.setattr(rp, "get_mapping", gm)
    return db


def test_penyusutan_memakai_akun_milik_aset_lalu_profil(asset_db, je_sink):
    sched = {"asset_id": "fa1", "period": "2026-01", "depr_amount": 1_000_000}
    own = {"id": "fa1", "code": "FA-1", "name": "Mesin", "account_id_depr_expense": "id-6-2730",
           "account_id_accum_depr": "id-1-2301"}
    run(rp.post_depreciation(asset_db, sched, own, USER))
    assert {(ln["account_code"], ln["debit"], ln["credit"]) for ln in je_sink[-1]["lines"]} == {
        ("6-2730", 1_000_000, 0), ("1-2301", 0, 1_000_000)}
    grp = dict(own, account_id_accum_depr="id-1-2000")   # akun induk tidak sah → profil
    run(rp.post_depreciation(asset_db, dict(sched, period="2026-02", asset_id="fa2"), dict(grp, id="fa2"), USER))
    assert ("1-2501", 0, 1_000_000) in {(ln["account_code"], ln["debit"], ln["credit"]) for ln in je_sink[-1]["lines"]}


def test_pelepasan_menghapus_akumulasi_di_akun_yang_dikredit_penyusutan(asset_db, je_sink):
    db = asset_db
    db.rahaza_journal_lines.docs = [
        {"source_module": "depreciation", "source_ref": "depreciation:fa1:2026-01", "account_code": "1-2501", "credit": 2_000_000, "debit": 0},
        {"source_module": "depreciation", "source_ref": "depreciation:fa1:2026-03", "account_code": "1-2301", "credit": 1_000_000, "debit": 0},
        {"source_module": "depreciation", "source_ref": "depreciation:fa9:2026-01", "account_code": "1-2301", "credit": 9, "debit": 0}]
    asset = {"id": "fa1", "code": "FA-1", "name": "Mesin", "purchase_cost": 12_000_000, "account_id_asset": "id-1-2300",
             "account_id_accum_depr": "id-1-2301", "accumulated_depr_at_disposal": 3_000_000,
             "disposal_value": 8_000_000, "disposal_date": "2026-03-31"}
    run(rp.post_asset_disposal(db, asset, USER))
    lines = {(ln["account_code"], ln["debit"], ln["credit"]) for ln in je_sink[-1]["lines"]}
    assert ("1-2501", 2_000_000, 0) in lines and ("1-2301", 1_000_000, 0) in lines and ("1-2300", 0, 12_000_000) in lines
    assert rp.split_accum_by_account(500, {}, "1-2301") == [("1-2301", 500)]


def test_pelepasan_sebelum_penyusutan_terakhir_ditolak(db, monkeypatch):
    db.rahaza_fixed_assets.docs = [{"id": "fa1", "status": "active", "purchase_cost": 12_000_000}]
    db.rahaza_depr_schedules.docs = [{"asset_id": "fa1", "period": f"2026-0{m}", "posted": True, "depr_amount": 1_000_000}
                                     for m in (1, 2, 3, 4)]
    with pytest.raises(HTTPException) as e:
        run(fa.dispose_asset("fa1", FakeRequest({"disposal_date": "2026-02-28", "disposal_value": 8_000_000})))
    assert e.value.status_code == 400 and "2026-04" in e.value.detail
    assert db.rahaza_fixed_assets.docs[0]["status"] == "active"

    async def ok(*_a, **_k):
        return {"ok": True}
    monkeypatch.setattr(rp, "post_asset_disposal", ok)
    out = run(fa.dispose_asset("fa1", FakeRequest({"disposal_date": "2026-04-30", "disposal_value": 8_000_000})))
    assert out["nbv_at_disposal"] == 8_000_000


# ═══════════════════════════════ 14. guard API ═════════════════════════════════
def test_batal_faktur_ap_yang_sudah_dibayar_ditolak(db):
    db.rahaza_ap_invoices.docs = [{"id": "ap1", "invoice_number": "AP-1", "status": "partial_paid",
                                   "total": 1_110_000, "paid_amount": 500_000, "gl_je_id": "je"}]
    with pytest.raises(HTTPException) as e:
        run(rf.change_ap_status("ap1", FakeRequest({"status": "cancelled"})))
    assert e.value.status_code == 400 and db.rahaza_ap_invoices.docs[0]["status"] == "partial_paid"


def test_gr_received_tidak_bisa_mundur_ke_draft(db):
    db.warehouse_receiving.docs = [{"id": "gr1", "receipt_number": "GR-00001", "status": "received", "items": []}]
    with pytest.raises(HTTPException) as e:
        run(wh.update_receiving("gr1", FakeRequest({"status": "draft"})))
    assert e.value.status_code == 400 and db.warehouse_receiving.docs[0]["status"] == "received"


def test_transfer_bank_hanya_antar_rekening_kas_bank(db, monkeypatch):
    async def is_bank(db_, code):
        return code in ("1-1201", "1-1211")
    monkeypatch.setattr(payout_banks, "is_bank_code", is_bank)
    fin = {"id": "u", "role": "finance", "name": "F"}
    for a, b in (("4-1100", "1-1201"), ("1-1201", "6-2900")):
        with pytest.raises(HTTPException) as e:
            run(bt.create_transfer(bt.TransferCreate(from_account_code=a, to_account_code=b, amount=5_000_000), fin))
        assert e.value.status_code == 400
    assert db.rahaza_bank_transfers.docs == []


# ════════════════════════════ 15. AR marketplace ═══════════════════════════════
def test_ar_channel_marketplace_ditolak(db, monkeypatch):
    assert rf.marketplace_channel_reason("SHP-01", None, {"platform": "shopee", "account_name": "A"})
    assert rf.marketplace_channel_reason("shopee_daluna", None, None)
    assert rf.marketplace_channel_reason("x", {"platform": "lain", "debit_ar": "1-1303-SHP-01"}, None)
    assert rf.marketplace_channel_reason("maklon_snbm", {"platform": "maklon", "debit_ar": "1-1301"}, None) is None
    assert rf.marketplace_channel_reason("", None, None) is None
    assert rf.marketplace_channel_reason("direct", None, None) is None
    db.rahaza_customers.docs = [{"id": "c1", "name": "X"}]
    db.marketing_platform_accounts.docs = [copy.deepcopy(STORE_A)]

    async def num(*_a, **_k):
        return "AR-1"
    monkeypatch.setattr(rf, "_gen_number", num)
    body = {"customer_id": "c1", "items": [{"description": "x", "qty": 1, "unit_price": 1000}], "sales_channel": "SHP-01"}
    with pytest.raises(HTTPException) as e:
        run(rf.create_ar(FakeRequest(body)))
    assert e.value.status_code == 400 and "pencairan" in e.value.detail
    out = run(rf.create_ar(FakeRequest(dict(body, sales_channel=""))))
    assert out["total"] == 1000


# ═════════════════════════ 16. Selisih Persediaan ══════════════════════════════
def test_selisih_persediaan_akun_dan_pemetaan(db, monkeypatch, je_sink):
    row = next(r for r in DA_UNIFIED_ACCOUNTS if r[0] == "5-1950")
    assert row[1] == "Selisih Persediaan" and row[2] == "COGS" and row[4] == "5-0000"
    prof = {p["event_type"]: p["mapping"] for p in pp.DEFAULT_PROFILES}
    assert prof["inventory_adjust"]["adjustment_expense"] == "5-1950"
    assert prof["inventory_scrap"]["debit_scrap_expense"] == "6-4300"
    # profil lama 6-2400 (ATK) → 5-1950; pilihan pengguna tetap
    up = pp.upgrade_profile_mapping("inventory_adjust", {"inventory_rm": "1-1401", "adjustment_expense": "6-2400"},
                                    {"updated_by": "u-lama"}, prof["inventory_adjust"])
    assert up["adjustment_expense"] == "5-1950"
    keep = pp.upgrade_profile_mapping("inventory_adjust", {"inventory_rm": "1-1401", "adjustment_expense": "6-2400"},
                                      {"updated_by": "u", "user_roles": ["adjustment_expense"]}, prof["inventory_adjust"])
    assert keep["adjustment_expense"] == "6-2400"

    async def gm(db_, et):
        return dict(prof[et])
    monkeypatch.setattr(rp, "get_mapping", gm)
    db.rahaza_materials.docs = [{"id": "m1", "unit_cost": 10_000}]
    run(rp.post_inventory_adjust(db, {"id": "mv1", "material_id": "m1", "qty": -5, "timestamp": "2026-10-10T00:00:00"}, USER))
    assert ("5-1950", 50_000, 0) in {(ln["account_code"], ln["debit"], ln["credit"]) for ln in je_sink[-1]["lines"]}
    run(rp.post_inventory_adjust(db, {"id": "mv2", "material_id": "m1", "qty": -1, "adjustment_reason": "scrap",
                                      "timestamp": "2026-10-10T00:00:00"}, USER))
    assert ("6-4300", 10_000, 0) in {(ln["account_code"], ln["debit"], ln["credit"]) for ln in je_sink[-1]["lines"]}
