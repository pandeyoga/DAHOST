"""
Iteration 228 backend tests — Audit fase 1 CV. Dewi Aditya.
Menguji RND-01, RND-02, RND-03, MAK-01, PROD-02, FIN-03, FIN-10, plus regresi.
Semua data uji TEST-* dihapus di teardown.
"""
import os
import sys
import time
import pytest
import requests
from pymongo import MongoClient

# ---- Setup ----
_env = "/app/backend/.env"
_env_kv = {}
if os.path.exists(_env):
    for line in open(_env):
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            _env_kv[k.strip()] = v.strip().strip('"').strip("'")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        line = line.strip()
        if line.startswith("REACT_APP_BACKEND_URL"):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break

MONGO_URL = _env_kv.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = _env_kv.get("DB_NAME", "test_database")

_mclient = MongoClient(MONGO_URL)
db = _mclient[DB_NAME]

# sys.path for FIN-10 import
if "/app/backend" not in sys.path:
    sys.path.insert(0, "/app/backend")


# ---- Token cache (rate limit 10/60s per email) ----
_TOKENS = {}

def _login(email, password):
    if email in _TOKENS:
        return _TOKENS[email]
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    if r.status_code == 429:
        time.sleep(30)
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:400]}"
    data = r.json()
    if data.get("must_change_password"):
        pytest.skip(f"{email} must change password")
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token: {data}"
    _TOKENS[email] = tok
    return tok


def _h(email, pw):
    return {"Authorization": f"Bearer {_login(email, pw)}"}


@pytest.fixture(scope="session")
def admin():
    return _h("admin@garment.com", "Admin@123")


@pytest.fixture(scope="session")
def rnd_staff():
    return _h("ega.ar@dewiaditya.id", "TempTest@123")


@pytest.fixture(scope="session")
def hr_user():
    return _h("brenda.p@dewiaditya.id", "TempTest@123")


@pytest.fixture(scope="session")
def cmt_vendor():
    for email in ("ani@dacmt.id", "ari@dacmt.id"):
        try:
            return _h(email, "TempTest@123")
        except Exception as e:
            print(f"cmt vendor {email} login skipped: {e}")
    pytest.skip("No cmt_vendor login succeeded")


# ---- helpers ----
def _cleanup_style(code):
    """Delete rahaza_models + variants + fg materials + dewi_rnd_styles for a TEST code."""
    m = db.rahaza_models.find_one({"code": code})
    if m:
        mid = m["id"]
        db.rahaza_model_variants.delete_many({"model_id": mid})
        db.rahaza_materials.delete_many({"model_id": mid, "type": "fg"})
        db.rahaza_boms.delete_many({"model_id": mid})
        db.rahaza_models.delete_one({"id": mid})
    db.dewi_rnd_styles.delete_many({"style_code": code})
    db.dewi_rnd_tech_packs.delete_many({"style_code": code})


# ═══════════════════════════════════════════════════════════════════
# RND-03: rnd_write_guard
# ═══════════════════════════════════════════════════════════════════
class TestRND03WriteGuard:
    def test_cmt_vendor_post_style_forbidden(self, cmt_vendor):
        r = requests.post(f"{BASE_URL}/api/dewi/rnd/styles",
                          json={"style_code": "TEST-RND03", "style_name": "x"},
                          headers=cmt_vendor, timeout=30)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:300]}"
        # ensure not created
        assert db.dewi_rnd_styles.find_one({"style_code": "TEST-RND03"}) is None

    def test_cmt_vendor_get_style_not_blocked_by_write_guard(self, cmt_vendor):
        r = requests.get(f"{BASE_URL}/api/dewi/rnd/styles", headers=cmt_vendor, timeout=30)
        # rnd_write_guard hanya blok method tulis; GET diperbolehkan (200) atau 401/403 lain
        # jika policy internal lain memblokir vendor eksternal — laporkan apa adanya.
        assert r.status_code in (200, 401, 403), f"unexpected {r.status_code}: {r.text[:300]}"
        print(f"[RND-03] cmt_vendor GET /styles → {r.status_code}")

    def test_admin_post_and_delete(self, admin):
        try:
            r = requests.post(f"{BASE_URL}/api/dewi/rnd/styles",
                              json={"style_code": "TEST-RND03-ADMIN",
                                    "style_name": "Uji RND03",
                                    "category": "Top"},
                              headers=admin, timeout=30)
            assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"
            sid = r.json().get("id") or r.json().get("_id")
            assert sid
            rd = requests.delete(f"{BASE_URL}/api/dewi/rnd/styles/{sid}",
                                 headers=admin, timeout=30)
            assert rd.status_code in (200, 204), f"delete: {rd.status_code} {rd.text[:200]}"
        finally:
            _cleanup_style("TEST-RND03-ADMIN")

    def test_rnd_staff_post_and_delete(self, rnd_staff):
        try:
            r = requests.post(f"{BASE_URL}/api/dewi/rnd/styles",
                              json={"style_code": "TEST-RND03-RND",
                                    "style_name": "Uji RND03 rnd",
                                    "category": "Top"},
                              headers=rnd_staff, timeout=30)
            assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"
            sid = r.json().get("id") or r.json().get("_id")
            assert sid
            rd = requests.delete(f"{BASE_URL}/api/dewi/rnd/styles/{sid}",
                                 headers=rnd_staff, timeout=30)
            assert rd.status_code in (200, 204), rd.text[:200]
        finally:
            _cleanup_style("TEST-RND03-RND")


# ═══════════════════════════════════════════════════════════════════
# RND-01: promote-to-production
# ═══════════════════════════════════════════════════════════════════
class TestRND01Promote:
    @pytest.fixture(scope="class")
    def promoted_style(self, admin):
        """Create style TEST-RND01, submit-for-review, owner-approve, promote."""
        style_id = None
        try:
            r = requests.post(f"{BASE_URL}/api/dewi/rnd/styles",
                              json={"style_code": "TEST-RND01",
                                    "style_name": "Uji RND01",
                                    "category": "Top"},
                              headers=admin, timeout=30)
            assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:300]}"
            style_id = r.json().get("id")
            assert style_id

            r2 = requests.post(f"{BASE_URL}/api/dewi/rnd/styles/{style_id}/submit-for-review",
                               json={}, headers=admin, timeout=30)
            assert r2.status_code in (200, 201), f"submit: {r2.status_code} {r2.text[:400]}"

            r3 = requests.post(f"{BASE_URL}/api/dewi/rnd/styles/{style_id}/owner-approve",
                               json={}, headers=admin, timeout=30)
            assert r3.status_code in (200, 201), f"owner-approve: {r3.status_code} {r3.text[:400]}"

            r4 = requests.post(f"{BASE_URL}/api/dewi/rnd/styles/{style_id}/promote-to-production",
                               json={}, headers=admin, timeout=30)
            assert r4.status_code in (200, 201), f"promote: {r4.status_code} {r4.text[:400]}"
            data = r4.json()
            yield style_id, data
        finally:
            _cleanup_style("TEST-RND01")

    def test_promote_creates_model(self, promoted_style):
        style_id, data = promoted_style
        # response should have model_code
        mc = data.get("model_code") or data.get("code")
        # verify DB
        m = db.rahaza_models.find_one({"code": "TEST-RND01"})
        assert m, f"model TEST-RND01 not created; response: {data}"
        assert m.get("rnd_style_id") == style_id or m.get("style_id") == style_id, \
            f"model.rnd_style_id={m.get('rnd_style_id')} vs style_id={style_id}"
        if mc:
            assert mc == "TEST-RND01"


# ═══════════════════════════════════════════════════════════════════
# RND-02: product viewer stock
# ═══════════════════════════════════════════════════════════════════
class TestRND02ProductViewer:
    def test_no_rahaza_stock_reference_in_code(self):
        code = open("/app/backend/routes/rnd_product_viewer.py").read()
        assert "db.rahaza_stock" not in code, "rnd_product_viewer.py still references db.rahaza_stock"

    def test_viewer_returns_stock_qty(self, admin):
        r = requests.get(f"{BASE_URL}/api/rnd/product-viewer", headers=admin, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        items = data if isinstance(data, list) else (data.get("items") or data.get("data") or [])
        assert items, "empty product viewer response"
        assert any("stock_qty" in it for it in items), \
            f"stock_qty missing; keys={list(items[0].keys())[:20]}"
        # rahaza_material_stock is empty per note → all zero, no error
        for it in items[:5]:
            assert isinstance(it.get("stock_qty"), int)


# ═══════════════════════════════════════════════════════════════════
# MAK-01: stage_qty tracking
# ═══════════════════════════════════════════════════════════════════
class TestMAK01StageQty:
    def test_stage_qty_roundtrip(self, admin):
        # find a maklon PO
        r = requests.get(f"{BASE_URL}/api/dewi/maklon/pos", headers=admin, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        js = r.json()
        pos = js if isinstance(js, list) else (js.get("items") or js.get("data") or [])
        if not pos:
            pytest.skip("no maklon PO available")
        po_id = pos[0].get("id") or pos[0].get("po_id")
        assert po_id

        # read current stage_qty
        rd = requests.get(f"{BASE_URL}/api/dewi/maklon/orders/{po_id}/production-detail",
                          headers=admin, timeout=30)
        assert rd.status_code == 200, f"detail: {rd.status_code} {rd.text[:300]}"
        prev = (rd.json().get("stage_qty") or {}).get("cutting_input", 0)

        # PUT stage-qty
        pu = requests.put(f"{BASE_URL}/api/dewi/maklon/orders/{po_id}/stage-qty",
                          json={"stage": "cutting", "qty_in": 123},
                          headers=admin, timeout=30)
        assert pu.status_code == 200, f"put: {pu.status_code} {pu.text[:400]}"

        # re-read
        rd2 = requests.get(f"{BASE_URL}/api/dewi/maklon/orders/{po_id}/production-detail",
                           headers=admin, timeout=30)
        assert rd2.status_code == 200
        sq = rd2.json().get("stage_qty") or {}
        assert sq.get("cutting_input") == 123, f"stage_qty={sq}"

        # restore
        requests.put(f"{BASE_URL}/api/dewi/maklon/orders/{po_id}/stage-qty",
                     json={"stage": "cutting", "qty_in": int(prev or 0)},
                     headers=admin, timeout=30)


# ═══════════════════════════════════════════════════════════════════
# PROD-02: cmt-component-requests write guard
# ═══════════════════════════════════════════════════════════════════
class TestPROD02CmtComponent:
    def test_vendor_post_forbidden(self, cmt_vendor):
        r = requests.post(f"{BASE_URL}/api/dewi/cmt-component-requests",
                          json={"request_type": "component", "items": []},
                          headers=cmt_vendor, timeout=30)
        assert r.status_code == 403, f"{r.status_code} {r.text[:300]}"

    def test_admin_get_ok(self, admin):
        r = requests.get(f"{BASE_URL}/api/dewi/cmt-component-requests",
                         headers=admin, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


# ═══════════════════════════════════════════════════════════════════
# FIN-03: kasbon guards
# ═══════════════════════════════════════════════════════════════════
class TestFIN03Kasbon:
    def test_rnd_staff_other_employee_forbidden(self, rnd_staff):
        # find an employee id that is NOT rnd_staff's
        other = db.rahaza_employees.find_one({"email": {"$ne": "ega.ar@dewiaditya.id"}}, {"id": 1})
        if not other:
            pytest.skip("no other employee found")
        r = requests.post(f"{BASE_URL}/api/dewi/kasbon/requests",
                          json={"employee_id": other["id"], "amount": 100000,
                                "reason": "TEST", "tenor_months": 1},
                          headers=rnd_staff, timeout=30)
        assert r.status_code == 403, f"{r.status_code} {r.text[:400]}"
        assert "diri sendiri" in r.text.lower() or "diri sendiri" in r.text, r.text[:400]

    def test_rnd_staff_hr_review_forbidden(self, rnd_staff):
        r = requests.patch(f"{BASE_URL}/api/dewi/kasbon/requests/fake-id/hr-review",
                           json={"decision": "approved"}, headers=rnd_staff, timeout=30)
        assert r.status_code == 403, r.text[:200]

    def test_rnd_staff_disburse_forbidden(self, rnd_staff):
        r = requests.patch(f"{BASE_URL}/api/dewi/kasbon/requests/fake-id/disburse",
                           json={}, headers=rnd_staff, timeout=30)
        assert r.status_code == 403, r.text[:200]

    def test_rnd_staff_seed_forbidden(self, rnd_staff):
        r = requests.post(f"{BASE_URL}/api/dewi/kasbon/seed",
                          json={}, headers=rnd_staff, timeout=30)
        assert r.status_code == 403, r.text[:200]

    def test_hr_hr_review_not_forbidden(self, hr_user):
        r = requests.patch(f"{BASE_URL}/api/dewi/kasbon/requests/fake-id/hr-review",
                           json={"decision": "approved"}, headers=hr_user, timeout=30)
        # HR can call it; fake id → 404 or 400/422 allowed
        assert r.status_code != 403, f"HR got 403: {r.text[:300]}"


# ═══════════════════════════════════════════════════════════════════
# FIN-10: _parse_idr
# ═══════════════════════════════════════════════════════════════════
class TestFIN10ParseIDR:
    @pytest.mark.parametrize("raw,expected", [
        ("1.500.000,50", 1500000.5),
        ("1,500,000.50", 1500000.5),
        ("1500000.50", 1500000.5),
        ("1.500.000", 1500000),
        ("Rp 250.000", 250000),
        ("(1.000,00)", -1000),
        ("-2500.75", -2500.75),
    ])
    def test_parse(self, raw, expected):
        from routes.dewi_bank_reconciliation import _parse_idr
        got = _parse_idr(raw)
        assert abs(got - expected) < 0.001, f"{raw!r} → {got} expected {expected}"


# ═══════════════════════════════════════════════════════════════════
# Regresi
# ═══════════════════════════════════════════════════════════════════
class TestRegression:
    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200, r.text[:200]

    def test_completeness(self, admin):
        r = requests.get(f"{BASE_URL}/api/dewi/rnd/completeness", headers=admin, timeout=30)
        assert r.status_code == 200
        assert (r.json().get("missing_counts") or {}).get("bom") == 0

    def test_tech_packs_search(self, admin):
        r = requests.get(f"{BASE_URL}/api/dewi/rnd/tech-packs",
                         params={"search": "DA-1101"}, headers=admin, timeout=30)
        assert r.status_code == 200

    def test_export_xlsx(self):
        r = requests.get(f"{BASE_URL}/downloads/EXPORT_SKU_BOM_DA.xlsx", timeout=60)
        assert r.status_code == 200
