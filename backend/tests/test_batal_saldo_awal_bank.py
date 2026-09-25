"""Regression: batal_saldo_awal_bank_20260924.py + double-post guard on cash sync-gl.

Scope:
  1. Setup: post `saldo_awal_bank_20260924.py` — creates JE Rp 585,418,930.
  2. Reversal preview (no `--terapkan`) — writes nothing.
  3. Reversal `--terapkan` — posts pembalik, GL balances return to pre-script value.
  4. Reversal `--terapkan` again — idempotent (prints 'SUDAH ADA').
  5. Re-run saldo_awal — skipped (existing_opening still returns original).
  6. POST /api/rahaza/cash-accounts/sync-gl → no cash_opening_balance JE for
     accounts touched by the opening_balance JE.
  7. Regression: new cash-account with opening_balance>0 → its
     cash_opening_balance JE is still posted (account NOT in opening JE lines).
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if "REACT_APP_BACKEND_URL" in os.environ else \
    open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0].strip()
API = f"{BASE_URL}/api"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "test_database"

SOURCE_REF = "saldo_erp.xlsx (owner, 2026-09-24)"
BANK_CODES = ["1-1211", "1-1212", "1-1213", "1-1214", "1-1219",
              "1-1222", "1-1223", "1-1224", "1-1225"]
RE_CODE = "3-2000"


# ─── fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": "admin@garment.com", "password": "Admin@123"},
                      timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _run_script(path: str, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # backend/.env supplies MONGO_URL/DB_NAME when scripts source it themselves.
    env.setdefault("MONGO_URL", MONGO_URL)
    env.setdefault("DB_NAME", DB_NAME)
    return subprocess.run(
        [sys.executable, path, *args],
        capture_output=True, text=True, cwd="/", env=env, timeout=90,
    )


def _gl_bal(db, codes):
    rows = db.rahaza_journal_lines.aggregate([
        {"$match": {"account_code": {"$in": codes}}},
        {"$group": {"_id": "$account_code",
                    "d": {"$sum": "$debit"}, "c": {"$sum": "$credit"}}},
    ])
    return {r["_id"]: round(r["d"] - r["c"]) for r in rows}


# ─── setup: clean state ──────────────────────────────────────────────────────
@pytest.fixture(scope="module", autouse=True)
def _clean_and_post_setup(db):
    """Remove any prior opening_balance / reversal from earlier runs so we
    exercise the full flow from scratch. `seed_golive_restore.sh` will
    restore the canonical preview seed afterwards (called manually)."""
    for mod in ("opening_balance", "opening_balance_reversal"):
        jes = list(db.rahaza_journal_entries.find({"source_module": mod}, {"_id": 0, "id": 1}))
        for je in jes:
            db.rahaza_journal_lines.delete_many({"je_id": je["id"]})
        db.rahaza_journal_entries.delete_many({"source_module": mod})
    # clear reversed flag markers (idempotent noop when field absent)
    db.rahaza_journal_entries.update_many({"flags.reversed": True},
                                          {"$unset": {"flags.reversed": "",
                                                      "reversed_by_je_id": "",
                                                      "reversed_by_je_number": ""}})
    yield


# ─── tests ───────────────────────────────────────────────────────────────────
class TestBatalSaldoAwal:
    """End-to-end: post → preview reversal → apply reversal → idempotency."""

    def test_01_setup_post_saldo_awal(self, db):
        cp = _run_script("/app/scripts/saldo_awal_bank_20260924.py")
        assert cp.returncode == 0, cp.stderr or cp.stdout
        je = db.rahaza_journal_entries.find_one({"source_module": "opening_balance",
                                                 "source_ref": SOURCE_REF})
        assert je is not None, "opening_balance JE not created"
        assert je["status"] == "posted"
        assert round(je["total_debit"]) == 585_418_930
        assert round(je["total_credit"]) == 585_418_930

    def test_02_reversal_preview_writes_nothing(self, db):
        before = db.rahaza_journal_entries.count_documents({})
        cp = _run_script("/app/scripts/batal_saldo_awal_bank_20260924.py")
        assert cp.returncode == 0, cp.stderr or cp.stdout
        assert "PRATINJAU" in cp.stdout, cp.stdout
        after = db.rahaza_journal_entries.count_documents({})
        assert before == after, f"preview changed JE count {before}→{after}"
        # no reversal JE yet
        assert db.rahaza_journal_entries.count_documents(
            {"source_module": "opening_balance_reversal"}) == 0

    def test_03_reversal_apply_posts_and_zeroes_gl(self, db):
        pre = _gl_bal(db, BANK_CODES + [RE_CODE])
        # after step 1 each bank should have positive balance, RE should have neg
        for c in BANK_CODES:
            assert pre.get(c, 0) > 0, f"pre-reversal {c} not positive: {pre.get(c)}"
        assert pre.get(RE_CODE, 0) <= -585_418_930

        cp = _run_script("/app/scripts/batal_saldo_awal_bank_20260924.py", "--terapkan")
        assert cp.returncode == 0, cp.stderr or cp.stdout
        assert "terposting" in cp.stdout.lower() or "✓" in cp.stdout, cp.stdout

        rev = db.rahaza_journal_entries.find_one(
            {"source_module": "opening_balance_reversal"})
        assert rev is not None
        assert rev["status"] == "posted"
        assert round(rev["total_debit"]) == 585_418_930
        assert round(rev["total_credit"]) == 585_418_930
        # amounts match, D/K swapped
        orig = db.rahaza_journal_entries.find_one(
            {"source_module": "opening_balance", "source_ref": SOURCE_REF})
        orig_map = {ln["account_code"]: (round(ln["debit"]), round(ln["credit"])) for ln in orig["lines"]}
        rev_map = {ln["account_code"]: (round(ln["debit"]), round(ln["credit"])) for ln in rev["lines"]}
        for code, (d, c) in orig_map.items():
            assert rev_map[code] == (c, d), f"{code} not swapped: orig=({d},{c}) rev={rev_map[code]}"

        # flags on original
        assert orig.get("flags", {}).get("reversed") is True
        assert orig.get("reversed_by_je_number") == rev["je_number"]

        # GL balances back to pre-script (before opening JE)
        post = _gl_bal(db, BANK_CODES + [RE_CODE])
        for c in BANK_CODES:
            expected = pre[c] - round(next(ln["debit"] for ln in orig["lines"] if ln["account_code"] == c))
            assert post.get(c, 0) == expected, f"{c} not reset: {post.get(c)} vs {expected}"
        re_orig_credit = round(next(ln["credit"] for ln in orig["lines"] if ln["account_code"] == RE_CODE))
        assert post.get(RE_CODE, 0) == pre[RE_CODE] + re_orig_credit

    def test_04_reversal_apply_idempotent(self, db):
        cnt_before = db.rahaza_journal_entries.count_documents(
            {"source_module": "opening_balance_reversal"})
        cp = _run_script("/app/scripts/batal_saldo_awal_bank_20260924.py", "--terapkan")
        assert cp.returncode == 0, cp.stderr or cp.stdout
        assert "SUDAH ADA" in cp.stdout, cp.stdout
        cnt_after = db.rahaza_journal_entries.count_documents(
            {"source_module": "opening_balance_reversal"})
        assert cnt_before == cnt_after == 1

    def test_05_rerun_saldo_awal_skips(self, db):
        cnt_before = db.rahaza_journal_entries.count_documents(
            {"source_module": "opening_balance"})
        cp = _run_script("/app/scripts/saldo_awal_bank_20260924.py")
        assert cp.returncode == 0, cp.stderr or cp.stdout
        assert "SUDAH ADA" in cp.stdout, cp.stdout
        cnt_after = db.rahaza_journal_entries.count_documents(
            {"source_module": "opening_balance"})
        assert cnt_before == cnt_after == 1


class TestSyncGlGuard:
    """cash-accounts/sync-gl must NOT double-post for accounts already in the
    opening_balance JE (even after reversal)."""

    def test_06_sync_gl_skips_opening_balance_accounts(self, db, auth_headers):
        # Sanity: opening_balance JE still present with the bank codes
        ob = db.rahaza_journal_entries.find_one(
            {"source_module": "opening_balance", "status": {"$ne": "voided"}})
        assert ob is not None
        opening_codes = {ln["account_code"] for ln in ob["lines"]}
        assert set(BANK_CODES).issubset(opening_codes)

        r = requests.post(f"{API}/rahaza/cash-accounts/sync-gl",
                          headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "report" in data

        # Verify no cash_opening_balance JE was created for these accounts
        cob = list(db.rahaza_journal_entries.find(
            {"source_module": "cash_opening_balance", "status": {"$ne": "voided"}},
            {"_id": 0, "je_number": 1, "lines.account_code": 1}))
        offending = [je["je_number"] for je in cob
                     if any(ln["account_code"] in opening_codes for ln in je["lines"])]
        assert not offending, f"double-post: cash_opening_balance JEs {offending} touch opening accounts"


class TestCashOpeningRegression:
    """New cash account with opening_balance > 0 whose GL code is NOT in the
    opening_balance JE must still post its own cash_opening_balance JE."""

    def test_07_new_cash_account_opening_still_posts(self, db, auth_headers):
        # Pick a GL code definitely not in the opening JE. Use fresh cash sub.
        code = f"TEST_{uuid.uuid4().hex[:6].upper()}"
        payload = {
            "code": code,
            "name": "TEST Petty Cash Regression",
            "type": "cash",
            "bank_name": "",
            "account_number": "",
            "opening_balance": 123456,
            "notes": "TEST_regression_iter133",
        }
        r = requests.post(f"{API}/rahaza/cash-accounts", headers=auth_headers,
                          json=payload, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        opening_post = body.get("_opening_post") or {}
        # Should be posted, not skipped by opening_balance-guard
        assert opening_post.get("ok") is True, opening_post
        # If gl_account_code lands in an existing opening_balance JE (extreme
        # coincidence with 1-11xx auto-code) it may skip; assert either je_number
        # created OR skipped-with-reason opening_balance.
        if opening_post.get("skipped"):
            # Accept only if reason cites opening_balance
            assert "jurnal pembuka" in (opening_post.get("reason") or "").lower(), opening_post
        else:
            assert opening_post.get("je_number"), opening_post
            # Verify JE exists in DB with correct amount
            je = db.rahaza_journal_entries.find_one(
                {"je_number": opening_post["je_number"]}, {"_id": 0})
            assert je is not None
            assert je["source_module"] == "cash_opening_balance"
            assert round(je["total_debit"]) == 123456

        # cleanup: delete cash account + its opening JE lines
        try:
            requests.delete(f"{API}/rahaza/cash-accounts/{body['id']}",
                            headers=auth_headers, timeout=15)
        except Exception:
            pass
        if opening_post.get("je_id"):
            db.rahaza_journal_lines.delete_many({"je_id": opening_post["je_id"]})
            db.rahaza_journal_entries.delete_one({"id": opening_post["je_id"]})
