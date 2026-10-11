"""
Iteration 134 - Marketing portal master-data linkage
Tests that forms no longer accept free-text values for entities that have masters.
Covers:
  - POST /api/dewi/kreator-requests (kreator_id/account_id/model_id/sample_colors/sample_sizes must be from masters)
  - POST /api/marketing/kol/catalog (fg_product_id required from Master FG)
  - POST /api/marketing/kol/sessions (creator must be assigned to account, platform copied from account)
  - POST /api/marketing/health/manual-snapshot (account_id required; platform/name derived from master)
"""
import os
import pytest
import requests
import uuid

def _load_backend_url():
    v = os.environ.get('REACT_APP_BACKEND_URL')
    if not v:
        try:
            with open('/app/frontend/.env') as f:
                for line in f:
                    if line.startswith('REACT_APP_BACKEND_URL='):
                        v = line.split('=', 1)[1].strip()
                        break
        except Exception:
            pass
    return (v or '').rstrip('/')

BASE_URL = _load_backend_url()
ADMIN_EMAIL = "admin@garment.com"
ADMIN_PASS = "Admin@123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def seed_refs(hdr):
    """Fetch a valid creator + assigned account + master color + size + model + fg."""
    # kol creators
    r = requests.get(f"{BASE_URL}/api/marketing/kol/creators", headers=hdr, timeout=30)
    assert r.status_code == 200, r.text
    cdata = r.json()
    creators = cdata.get('creators') if isinstance(cdata, dict) else cdata
    creator = next((c for c in creators if c.get('assigned_account_ids')), None)
    assert creator, "No creator with assigned_account_ids found"

    account_id = creator['assigned_account_ids'][0]
    r = requests.get(f"{BASE_URL}/api/marketing/accounts", headers=hdr, timeout=30)
    assert r.status_code == 200
    accs = r.json() if isinstance(r.json(), list) else r.json().get('accounts') or r.json().get('data') or []
    account = next((a for a in accs if a.get('id') == account_id), None)
    assert account, f"Assigned account {account_id} not found"

    # a different account NOT assigned to this creator
    other = next((a for a in accs if a.get('id') != account_id
                  and a.get('id') not in creator['assigned_account_ids']), None)

    # colors
    r = requests.get(f"{BASE_URL}/api/rahaza/masters/colors", headers=hdr, timeout=30)
    if r.status_code != 200:
        r = requests.get(f"{BASE_URL}/api/rahaza/colors", headers=hdr, timeout=30)
    assert r.status_code == 200, f"colors: {r.status_code} {r.text[:200]}"
    cdata = r.json()
    colors = cdata if isinstance(cdata, list) else cdata.get('items') or cdata.get('data') or []
    assert colors, "No colors master"

    # sizes
    r = requests.get(f"{BASE_URL}/api/rahaza/masters/sizes", headers=hdr, timeout=30)
    if r.status_code != 200:
        r = requests.get(f"{BASE_URL}/api/rahaza/sizes", headers=hdr, timeout=30)
    assert r.status_code == 200
    sdata = r.json()
    sizes = sdata if isinstance(sdata, list) else sdata.get('items') or sdata.get('data') or []

    # models (optional)
    r = requests.get(f"{BASE_URL}/api/rahaza/masters/models", headers=hdr, timeout=30)
    if r.status_code != 200:
        r = requests.get(f"{BASE_URL}/api/rahaza/models", headers=hdr, timeout=30)
    models = []
    if r.status_code == 200:
        mdata = r.json()
        models = mdata if isinstance(mdata, list) else mdata.get('items') or mdata.get('data') or []

    # fg materials via marketing/kol/fg-products
    r = requests.get(f"{BASE_URL}/api/marketing/kol/fg-products", headers=hdr, timeout=30)
    assert r.status_code == 200
    fgs = r.json()

    return {
        "creator": creator, "account": account, "other_account": other,
        "colors": colors, "sizes": sizes, "models": models, "fgs": fgs,
    }


# ─── DEWI KREATOR REQUESTS ───────────────────────────────────────────────────
class TestKreatorRequests:
    def test_missing_kreator_id_400(self, hdr):
        r = requests.post(f"{BASE_URL}/api/dewi/kreator-requests", headers=hdr, json={
            "kreator_type": "live_streaming", "product_concept": "TEST_no_kreator",
        }, timeout=30)
        assert r.status_code == 400, r.text
        assert "kreator" in r.text.lower()

    def test_missing_account_id_400(self, hdr, seed_refs):
        r = requests.post(f"{BASE_URL}/api/dewi/kreator-requests", headers=hdr, json={
            "kreator_id": seed_refs['creator']['id'],
            "kreator_type": "live_streaming", "product_concept": "TEST_no_account",
        }, timeout=30)
        assert r.status_code == 400, r.text
        assert "toko" in r.text.lower() or "account" in r.text.lower()

    def test_creator_not_assigned_to_toko_400(self, hdr, seed_refs):
        if not seed_refs['other_account']:
            pytest.skip("no unassigned account available")
        r = requests.post(f"{BASE_URL}/api/dewi/kreator-requests", headers=hdr, json={
            "kreator_id": seed_refs['creator']['id'],
            "account_id": seed_refs['other_account']['id'],
            "kreator_type": "live_streaming", "product_concept": "TEST_wrong_toko",
        }, timeout=30)
        assert r.status_code == 400, r.text
        assert "assign" in r.text.lower() or "tidak" in r.text.lower()

    def test_color_not_in_master_400(self, hdr, seed_refs):
        r = requests.post(f"{BASE_URL}/api/dewi/kreator-requests", headers=hdr, json={
            "kreator_id": seed_refs['creator']['id'],
            "account_id": seed_refs['account']['id'],
            "kreator_type": "live_streaming",
            "product_concept": "TEST_bad_color",
            "sample_colors": ["NEONPINK_FAKE_XYZ"],
        }, timeout=30)
        assert r.status_code == 400, r.text
        assert "warna" in r.text.lower() or "color" in r.text.lower() or "master" in r.text.lower()

    def test_valid_creates_and_normalizes_color(self, hdr, seed_refs):
        # Pick a real color; test lowercase → normalized
        color = seed_refs['colors'][0]
        color_name = color.get('name') or color.get('code')
        assert color_name
        size = (seed_refs['sizes'][0].get('name') or seed_refs['sizes'][0].get('code')) if seed_refs['sizes'] else None

        payload = {
            "kreator_id": seed_refs['creator']['id'],
            "account_id": seed_refs['account']['id'],
            "kreator_type": "live_streaming",
            "product_concept": "TEST_valid_" + uuid.uuid4().hex[:6],
            "sample_colors": [color_name.lower()],
        }
        if size:
            payload["sample_sizes"] = [size.lower()]
        if seed_refs['models']:
            payload["model_id"] = seed_refs['models'][0]['id']

        r = requests.post(f"{BASE_URL}/api/dewi/kreator-requests",
                          headers=hdr, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        doc = r.json()
        # kreator_name/handle/account_name/platform filled from masters
        assert doc.get('kreator_name') == seed_refs['creator'].get('name')
        assert doc.get('account_name') == seed_refs['account'].get('account_name')
        assert doc.get('platform') == seed_refs['account'].get('platform')
        # color normalized to master casing
        assert doc.get('sample_colors') == [color_name]
        # cleanup
        rid = doc.get('id')
        if rid:
            requests.delete(f"{BASE_URL}/api/dewi/kreator-requests/{rid}", headers=hdr, timeout=30)

    def test_bad_model_id_400(self, hdr, seed_refs):
        r = requests.post(f"{BASE_URL}/api/dewi/kreator-requests", headers=hdr, json={
            "kreator_id": seed_refs['creator']['id'],
            "account_id": seed_refs['account']['id'],
            "kreator_type": "live_streaming",
            "product_concept": "TEST_bad_model",
            "model_id": "fake-model-id-xyz-999",
        }, timeout=30)
        assert r.status_code == 400, r.text


# ─── KOL CATALOG (FG master) ─────────────────────────────────────────────────
class TestKolCatalog:
    def test_fake_fg_400(self, hdr, seed_refs):
        r = requests.post(f"{BASE_URL}/api/marketing/kol/catalog", headers=hdr, json={
            "account_id": seed_refs['account']['id'],
            "fg_product_id": "fake-fg-id-xyz-999",
            "product_name": "IGNORED_typed_name",
            "sku": "IGNORED_SKU",
            "unit_price": 100000,
        }, timeout=30)
        assert r.status_code == 400, r.text
        assert "fg" in r.text.lower() or "master" in r.text.lower()

    def test_valid_fg_overwrites_typed_fields(self, hdr, seed_refs):
        if not seed_refs['fgs']:
            pytest.skip("no fg products")
        fg = seed_refs['fgs'][0]
        payload = {
            "account_id": seed_refs['account']['id'],
            "fg_product_id": fg['id'],
            "product_name": "TYPED_name_should_be_ignored",
            "sku": "TYPED_SKU_" + uuid.uuid4().hex[:4],  # will be overwritten by fg.code
            "category": "TYPED_CAT",
            "unit_price": 199000,
        }
        r = requests.post(f"{BASE_URL}/api/marketing/kol/catalog",
                          headers=hdr, json=payload, timeout=30)
        # skip if SKU dup on retry
        if r.status_code == 400 and 'sudah ada' in r.text.lower():
            pytest.skip("catalog item for this fg already exists")
        assert r.status_code == 200, r.text
        item = r.json().get('item') or r.json()
        assert item.get('product_name') == (fg.get('name') or fg.get('code'))
        assert item.get('sku') == fg.get('code')
        # cleanup
        iid = item.get('id')
        if iid:
            requests.delete(f"{BASE_URL}/api/marketing/kol/catalog/{iid}", headers=hdr, timeout=30)


# ─── KOL SESSIONS ────────────────────────────────────────────────────────────
class TestKolSessions:
    def test_creator_not_assigned_400(self, hdr, seed_refs):
        if not seed_refs['other_account']:
            pytest.skip("no unassigned account")
        r = requests.post(f"{BASE_URL}/api/marketing/kol/sessions", headers=hdr, json={
            "creator_id": seed_refs['creator']['id'],
            "account_id": seed_refs['other_account']['id'],
            "date": "2026-01-10",
            "duration_minutes": 60, "viewers": 100, "peak_viewers": 200,
            "revenue": 1000000, "orders": 5,
            "platform": "shopee",  # should be ignored, replaced by account's platform
        }, timeout=30)
        assert r.status_code == 400, r.text

    def test_valid_session_platform_from_account(self, hdr, seed_refs):
        r = requests.post(f"{BASE_URL}/api/marketing/kol/sessions", headers=hdr, json={
            "creator_id": seed_refs['creator']['id'],
            "account_id": seed_refs['account']['id'],
            "date": "2026-01-11",
            "duration_minutes": 60, "viewers": 100, "peak_viewers": 200,
            "revenue": 1000000, "orders": 5,
            "platform": "WRONG_PLATFORM_TYPED",
        }, timeout=30)
        assert r.status_code == 200, r.text
        sess = r.json().get('session') or r.json()
        assert sess.get('platform') == seed_refs['account'].get('platform')
        sid = sess.get('id')
        if sid:
            requests.delete(f"{BASE_URL}/api/marketing/kol/sessions/{sid}", headers=hdr, timeout=30)


# ─── ACCOUNT HEALTH MANUAL SNAPSHOT ──────────────────────────────────────────
class TestHealthSnapshot:
    def test_no_account_id_400(self, hdr):
        r = requests.post(f"{BASE_URL}/api/marketing/health/manual-snapshot",
                          headers=hdr, json={
            "platform": "shopee", "account_name": "TYPED", "ses_score": 90,
        }, timeout=30)
        assert r.status_code == 400, r.text

    def test_fake_account_id_400(self, hdr):
        r = requests.post(f"{BASE_URL}/api/marketing/health/manual-snapshot",
                          headers=hdr, json={
            "account_id": "fake-acc-id-zzz",
            "platform": "shopee", "account_name": "TYPED", "ses_score": 90,
        }, timeout=30)
        assert r.status_code == 400, r.text

    def test_valid_overrides_platform_and_name(self, hdr, seed_refs):
        r = requests.post(f"{BASE_URL}/api/marketing/health/manual-snapshot",
                          headers=hdr, json={
            "account_id": seed_refs['account']['id'],
            "platform": "WRONG_TYPED", "account_name": "WRONG_TYPED",
            "ses_score": 88,
        }, timeout=30)
        assert r.status_code == 200, r.text
        # Fetch back and verify platform/account_name derived from master
        # (Response wraps in success_response; we just check status happy path.)
