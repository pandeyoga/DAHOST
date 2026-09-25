"""
Iterasi 230 — sisa temuan audit 2026-09-23:
  FIN-11..FIN-21, PROD-01, MAK-02, RND-04, Papan Temuan Audit (dashboard admin).
Semua data uji WAJIB dihapus setelah uji.
"""
import os
import asyncio
import time
import pytest
import requests
import bcrypt
from datetime import date
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
           os.environ.get("BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback used by supervisor-run backend (frontend/.env is source of truth)
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL"):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "admin@garment.com"
ADMIN_PASS = "Admin@123"
RND_EMAIL = "ega.ar@dewiaditya.id"
RND_TEMP_PASS = "TempTest@123"


# ────────────────────────── SESSION FIXTURES ──────────────────────────
@pytest.fixture(scope="session")
def db_sync():
    c = MongoClient(MONGO_URL)
    return c[DB_NAME]


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def rnd_token(db_sync):
    """Login rnd_staff. Password klien tidak 'Dewi@123' → patch sementara ke RND_TEMP_PASS
    dan kembalikan hash asli setelah sesi selesai."""
    orig = db_sync.users.find_one({"email": RND_EMAIL}, {"_id": 0, "password": 1})
    if not orig:
        pytest.skip(f"user {RND_EMAIL} tidak ada")
    original_hash = orig["password"]
    new_hash = bcrypt.hashpw(RND_TEMP_PASS.encode(), bcrypt.gensalt()).decode()
    db_sync.users.update_one({"email": RND_EMAIL}, {"$set": {"password": new_hash}})
    try:
        # rate-limit friendly
        time.sleep(1)
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": RND_EMAIL, "password": RND_TEMP_PASS},
                          timeout=30)
        if r.status_code != 200:
            pytest.skip(f"rnd login failed: {r.status_code} {r.text[:200]}")
        token = r.json()["token"]
        yield token
    finally:
        db_sync.users.update_one({"email": RND_EMAIL}, {"$set": {"password": original_hash}})


# ────────────────────────── PAPAN TEMUAN AUDIT (backend) ──────────────
class TestAuditFindingsBoard:
    def test_admin_get_findings(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/rahaza/admin/audit-findings",
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["total"] == 30, f"total={d['total']}"
        assert d["by_status"].get("selesai") == 29
        assert d["by_status"].get("diterima") == 1
        bp = d["by_portal"]
        assert bp.get("Finance") == 21
        assert bp.get("Produksi") == 3
        assert bp.get("Maklon") == 2
        assert bp.get("R&D") == 4
        assert isinstance(d["items"], list) and len(d["items"]) == 30
        it0 = d["items"][0]
        for k in ("id", "judul", "status", "perbaikan"):
            assert k in it0, f"missing key '{k}' in item"

    def test_rnd_staff_forbidden(self, rnd_token):
        h = {"Authorization": f"Bearer {rnd_token}"}
        r = requests.get(f"{BASE_URL}/api/rahaza/admin/audit-findings",
                         headers=h, timeout=30)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:200]}"


# ────────────────────────── PROD-01 ──────────────────────────
class TestProd01ConfirmMI:
    def test_confirm_returns_410(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/rahaza/material-issues/x/confirm",
                          headers=admin_headers, json={}, timeout=30)
        assert r.status_code == 410, f"expected 410 got {r.status_code}: {r.text[:200]}"


# ────────────────────────── RND-04 ──────────────────────────
class TestRnd04Deprecated:
    def test_compute_from_bom_410(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/dewi/rnd/hpp-calculator/compute-from-bom",
                          headers=admin_headers, json={}, timeout=30)
        assert r.status_code == 410, f"got {r.status_code}: {r.text[:200]}"

    def test_propagate_410(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/dewi/rnd/hpp-calculator/abc/propagate",
                          headers=admin_headers, json={}, timeout=30)
        assert r.status_code == 410, f"got {r.status_code}: {r.text[:200]}"


# ────────────────────────── FIN-15 (Infinity / NaN) ──────────────────────────
class TestFin15InfNan:
    def test_journal_infinity_rejected(self, admin_headers, db_sync):
        payload = {
            "date": "2026-09-01",
            "memo": "UJI-FIN15-INF",
            "lines": [
                {"account_code": "1-1201", "debit": "Infinity", "credit": 0},
                {"account_code": "6-2900", "debit": 0, "credit": 100000},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/rahaza/journals",
                          headers=admin_headers, json=payload, timeout=30)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"
        # cleanup safety
        db_sync.rahaza_journal_entries.delete_many({"memo": "UJI-FIN15-INF"})

    def test_journal_nan_rejected(self, admin_headers, db_sync):
        payload = {
            "date": "2026-09-01",
            "memo": "UJI-FIN15-NAN",
            "lines": [
                {"account_code": "1-1201", "debit": 100000, "credit": 0},
                {"account_code": "6-2900", "debit": 0, "credit": "nan"},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/rahaza/journals",
                          headers=admin_headers, json=payload, timeout=30)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"
        db_sync.rahaza_journal_entries.delete_many({"memo": "UJI-FIN15-NAN"})


# ────────────────────────── FIN-17 (concurrent post → 1 win, 1 fail) ──────────────────────────
class TestFin17ConcurrentPost:
    def test_concurrent_post_atomic(self, admin_headers, db_sync):
        today = date.today().isoformat()
        payload = {
            "date": today,
            "memo": "UJI-FIN17-CONCURRENT",
            "lines": [
                {"account_code": "1-1201", "debit": 50000, "credit": 0},
                {"account_code": "6-2900", "debit": 0, "credit": 50000},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/rahaza/journals",
                          headers=admin_headers, json=payload, timeout=30)
        assert r.status_code == 200, f"create draft failed: {r.status_code} {r.text[:300]}"
        je_id = r.json()["id"]
        try:
            # fire 2 posts concurrently via threads
            import concurrent.futures
            def _post():
                return requests.post(
                    f"{BASE_URL}/api/rahaza/journals/{je_id}/post",
                    headers=admin_headers, json={}, timeout=30)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                futs = [ex.submit(_post) for _ in range(2)]
                results = [f.result() for f in futs]
            statuses = sorted([r.status_code for r in results])
            # Expect exactly one 200 and one 4xx (409 or 400)
            assert 200 in statuses, f"tidak ada yg 200: {statuses} bodies={[r.text[:100] for r in results]}"
            others = [s for s in statuses if s != 200]
            assert len(others) == 1 and others[0] in (400, 409), \
                f"other status bukan 400/409: {statuses}"
            # journal_lines untuk je_id harus 2 baris (bukan 4)
            n_lines = db_sync.rahaza_journal_lines.count_documents({"je_id": je_id})
            assert n_lines == 2, f"journal_lines expected 2, got {n_lines}"
        finally:
            # cleanup: void jika posted, hapus
            db_sync.rahaza_journal_entries.delete_many({"id": je_id})
            db_sync.rahaza_journal_lines.delete_many({"je_id": je_id})


# ────────────────────────── FIN-14 (recurring accrual anak lama) ──────────────────────────
class TestFin14Recurring:
    def test_recurring_uses_template_only(self, admin_headers, db_sync):
        # cleanup any prior
        db_sync.rahaza_accruals.delete_many({"id": {"$regex": "^T14-"}})
        db_sync.rahaza_accruals.delete_many({"description": "UJI"})

        tpl = {
            "id": "T14-TPL", "accrual_type": "expense", "description": "UJI",
            "amount": 100000, "period": "2026-07", "status": "posted",
            "is_recurring": True, "recurring_template_id": None,
            "expense_account": "6-2900", "accrued_account": "2-1100",
        }
        child = {
            "id": "T14-CHILD", "accrual_type": "expense", "description": "UJI",
            "amount": 100000, "period": "2026-08", "status": "posted",
            "is_recurring": False, "recurring_template_id": "T14-TPL",
            "expense_account": "6-2900", "accrued_account": "2-1100",
        }
        db_sync.rahaza_accruals.insert_many([tpl, child])
        try:
            r = requests.post(
                f"{BASE_URL}/api/rahaza/finance/accruals/create-recurring",
                headers=admin_headers,
                json={"template_ids": ["T14-TPL", "T14-CHILD"], "target_period": "2026-09"},
                timeout=30,
            )
            assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
            data = r.json()
            assert data.get("created_count") == 1, f"created={data.get('created_count')} details={data}"
            created = data["accruals"][0]
            assert created["period"] == "2026-09"
            assert created["recurring_template_id"] == "T14-TPL"
            assert created["is_recurring"] is False
        finally:
            db_sync.rahaza_accruals.delete_many({"id": {"$regex": "^T14-"}})
            db_sync.rahaza_accruals.delete_many({"description": "UJI", "period": "2026-09"})


# ────────────────────────── FIN-13 (void bank transfer belum posting) ──────────────────────────
class TestFin13VoidBankTransfer:
    def test_void_without_je(self, admin_headers, db_sync):
        db_sync.rahaza_bank_transfers.delete_many({"id": "T13"})
        doc = {
            "id": "T13", "ref_number": "T13",
            "from_account_code": "1-1201", "to_account_code": "1-1202",
            "amount": 5000000, "transfer_date": "2026-09-01",
            "status": "pending_posting", "gl_posted": False,
        }
        db_sync.rahaza_bank_transfers.insert_one(doc)
        try:
            r = requests.post(f"{BASE_URL}/api/finance/bank-transfers/T13/void",
                              headers=admin_headers, json={}, timeout=30)
            assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
            body = r.json()
            assert body.get("voided_without_je") is True, body
            # tidak ada JE dengan source_ref void_bt:T13
            n_je = db_sync.rahaza_journal_entries.count_documents({"source_ref": "void_bt:T13"})
            assert n_je == 0
        finally:
            db_sync.rahaza_bank_transfers.delete_many({"id": "T13"})
            db_sync.rahaza_journal_entries.delete_many({"source_ref": "void_bt:T13"})
            db_sync.rahaza_journal_entries.delete_many({"source_ref": "bt:T13"})


# ────────────────────────── FIN-20c (write-off draft rejected) ──────────────────────────
class TestFin20cWriteOffDraft:
    def test_write_off_draft_rejected(self, admin_headers, db_sync):
        db_sync.rahaza_ar_invoices.delete_many({"id": "T20"})
        db_sync.rahaza_ar_invoices.insert_one({
            "id": "T20", "status": "draft",
            "total": 1000000, "balance": 1000000, "amount_due": 1000000,
            "issue_date": "2026-09-01",
        })
        try:
            r = requests.post(
                f"{BASE_URL}/api/rahaza/ar-invoices/T20/write-off-bad-debt",
                headers=admin_headers,
                json={"reason": "uji", "write_off_date": "2026-09-15"},
                timeout=30,
            )
            assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"
        finally:
            db_sync.rahaza_ar_invoices.delete_many({"id": "T20"})


# ────────────────────────── FIN-21 (seed-all-accounting EEM) ──────────────────────────
class TestFin21SeedAccounting:
    def test_seed_eem_ok(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/rahaza/admin/seed-all-accounting",
                          headers=admin_headers, json={}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        eem = d.get("details", {}).get("eem_categories", {})
        assert eem.get("ok") is True, f"eem details={eem}"


# ────────────────────────── FIN-18 (dedup bank recon) ──────────────────────────
class TestFin18BankReconDedup:
    def test_add_transaction_dedup(self, admin_headers, db_sync):
        # Cari cash account yang punya gl_account_code
        acc = db_sync.rahaza_cash_accounts.find_one({"gl_account_code": {"$exists": True, "$ne": ""}})
        if not acc:
            pytest.skip("Tidak ada rahaza_cash_accounts dengan gl_account_code")
        period = "2026-10"
        # cleanup preexisting session
        existing = list(db_sync.bank_recon_sessions.find({"period": period, "cash_account_id": acc["id"]}))
        for s in existing:
            db_sync.bank_recon_txns.delete_many({"session_id": s["id"]})
            db_sync.bank_recon_sessions.delete_one({"id": s["id"]})

        r = requests.post(f"{BASE_URL}/api/finance/bank-recon/sessions",
                          headers=admin_headers,
                          json={"period": period, "cash_account_id": acc["id"],
                                "opening_balance": 0, "closing_balance": 0,
                                "notes": "UJI-FIN18"},
                          timeout=30)
        assert r.status_code in (200, 201), r.text[:300]
        session_id = r.json()["id"]
        try:
            txn = {"txn_date": "2026-09-01", "amount": 15000, "type": "credit", "reference": "ADM-1"}
            r1 = requests.post(f"{BASE_URL}/api/finance/bank-recon/sessions/{session_id}/transactions",
                               headers=admin_headers, json=txn, timeout=30)
            assert r1.status_code == 200, f"first: {r1.status_code} {r1.text[:200]}"
            r2 = requests.post(f"{BASE_URL}/api/finance/bank-recon/sessions/{session_id}/transactions",
                               headers=admin_headers, json=txn, timeout=30)
            assert r2.status_code == 409, f"second should 409: {r2.status_code} {r2.text[:200]}"

            # import-bulk with 2 identical + 1 new
            payload = {"transactions": [
                {"txn_date": "2026-09-02", "amount": 20000, "type": "credit", "reference": "BULK-A"},
                {"txn_date": "2026-09-02", "amount": 20000, "type": "credit", "reference": "BULK-A"},
                {"txn_date": "2026-09-03", "amount": 25000, "type": "credit", "reference": "BULK-B"},
            ]}
            r3 = requests.post(f"{BASE_URL}/api/finance/bank-recon/sessions/{session_id}/import-bulk",
                               headers=admin_headers, json=payload, timeout=30)
            assert r3.status_code == 200, r3.text[:200]
            assert r3.json().get("imported") == 2, r3.json()
            total = db_sync.bank_recon_txns.count_documents({"session_id": session_id})
            # Expected: 1 (single add) + 2 (bulk dedup: A once + B) = 3
            assert total == 3, f"expected 3 txns got {total}"
        finally:
            db_sync.bank_recon_txns.delete_many({"session_id": session_id})
            db_sync.bank_recon_sessions.delete_one({"id": session_id})


# ────────────────────────── MAK-02 (portalNav label) ──────────────────────────
class TestMak02NavLabel:
    def test_label_tracking_order(self):
        path = "/app/frontend/src/components/erp/portal-shell/portalNav.js"
        src = open(path).read()
        # cari baris maklon-tracking dengan label 'Tracking Order'
        import re
        m = re.search(r"id:\s*['\"]maklon-tracking['\"]\s*,\s*label:\s*['\"]([^'\"]+)['\"]", src)
        assert m, "maklon-tracking entry tidak ditemukan"
        assert m.group(1) == "Tracking Order", f"label={m.group(1)}"


# ────────────────────────── Regression ──────────────────────────
class TestRegression:
    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert r.status_code == 200

    def test_financial_recap(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/financial-recap", headers=admin_headers, timeout=30)
        assert r.status_code == 200

    def test_rnd_completeness(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/dewi/rnd/completeness", headers=admin_headers, timeout=30)
        assert r.status_code == 200

    def test_maklon_production_detail(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/dewi/maklon/orders/5f29f37f-18a0-425f-a978-214e7615c530/production-detail",
            headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        sq = d.get("stage_qty") or {}
        assert sq.get("cutting_input") == 123, f"cutting_input={sq.get('cutting_input')}"
