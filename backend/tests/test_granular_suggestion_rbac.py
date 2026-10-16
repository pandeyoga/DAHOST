# RBAC granular: /api/roles/granular-suggestion + PUT /api/roles permission_keys >500 (iteration 238)
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
API = f"{BASE_URL}/api"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    if r.status_code != 200:
        return None
    d = r.json()
    return d.get('token') or d.get('access_token')


@pytest.fixture(scope="module")
def admin():
    t = _login("admin@garment.com", "Admin@123")
    if not t:
        pytest.skip("admin login failed")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {t}"})
    return s


@pytest.fixture(scope="module")
def roles(admin):
    r = admin.get(f"{API}/roles", timeout=30)
    assert r.status_code == 200
    return r.json()


def _role(roles, name):
    for r in roles:
        if r.get('name') == name:
            return r
    pytest.skip(f"role {name} not found")


# Suggestion endpoint: accounting role
def test_suggestion_accounting(admin, roles):
    acc = _role(roles, 'accounting')
    before = admin.get(f"{API}/roles", timeout=30).json()
    before_keys = sorted(_role(before, 'accounting')['permission_keys'])
    r = admin.post(f"{API}/roles/granular-suggestion", json={
        "role_name": "accounting", "portals": acc.get('portals') or [],
        "permissions": acc.get('permission_keys') or []}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert isinstance(d['portals'], list) and isinstance(d['keys'], list)
    print("portals:", [(p['portal'], p['portal_access'], p['modules'], len(p['keys'])) for p in d['portals']])
    pids = {p['portal']: p for p in d['portals']}
    for need in ('finance', 'toko', 'assets'):
        assert need in pids, f"{need} missing; got {list(pids)}"
        assert pids[need]['portal_access'] is True
    for p in d['portals']:
        assert set(p.keys()) >= {'portal', 'portal_label', 'portal_access', 'keys', 'modules'}
        assert all(k.startswith('mod.') for k in p['keys'])
        assert p['modules'] == len({k.split('.')[1] for k in p['keys']})
    assert len(d['keys']) == sum(len(p['keys']) for p in d['portals'])
    # does not save
    after = admin.get(f"{API}/roles", timeout=30).json()
    assert sorted(_role(after, 'accounting')['permission_keys']) == before_keys


# Single portal filter
def test_suggestion_single_portal(admin, roles):
    acc = _role(roles, 'accounting')
    r = admin.post(f"{API}/roles/granular-suggestion", json={
        "role_name": "accounting", "portals": acc.get('portals') or [],
        "permissions": acc.get('permission_keys') or [], "portal": "finance"}, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert [p['portal'] for p in d['portals']] == ['finance']


# Invalid portal -> 400
def test_suggestion_invalid_portal(admin):
    r = admin.post(f"{API}/roles/granular-suggestion", json={
        "role_name": "x", "portals": [], "permissions": [], "portal": "maklon"}, timeout=30)
    assert r.status_code == 400


# Non-superadmin -> 403, no auth -> 401
def test_suggestion_forbidden_non_super():
    t = _login("uji.accounting@dewiaditya.id", "Dewi@123")
    if not t:
        pytest.skip("uji.accounting login failed")
    r = requests.post(f"{API}/roles/granular-suggestion", headers={"Authorization": f"Bearer {t}"},
                      json={"role_name": "accounting", "portals": [], "permissions": []}, timeout=30)
    assert r.status_code == 403


def test_suggestion_unauth():
    r = requests.post(f"{API}/roles/granular-suggestion", json={}, timeout=30)
    assert r.status_code in (401, 403)


# Empty portals -> fall back to PORTAL_ACCESS of role_name
def test_suggestion_fallback_portal_access(admin):
    r = admin.post(f"{API}/roles/granular-suggestion", json={
        "role_name": "accounting", "portals": [], "permissions": []}, timeout=30)
    assert r.status_code == 200
    d = r.json()
    print("fallback portals:", [p['portal'] for p in d['portals']])
    assert any(p['portal'] == 'finance' for p in d['portals'])


# PUT role with >500 keys returns all
def test_put_role_many_keys(admin):
    cat = admin.get(f"{API}/permissions", timeout=30).json()
    keys = []
    if isinstance(cat, dict) and 'permissions' in cat:
        keys = [p.get('key') or p.get('permission_key') for p in cat['permissions']]
    elif isinstance(cat, list):
        keys = [p.get('key') or p.get('permission_key') for p in cat]
    keys = [k for k in keys if k]
    # also all mod.* from suggestion over all portals with full access
    sug = admin.post(f"{API}/roles/granular-suggestion", json={
        "role_name": "superadmin", "portals": ["management", "production", "cutting", "procurement",
                                               "warehouse", "accessories", "finance", "sales", "hr",
                                               "toko", "rnd", "assets"],
        "permissions": keys}, timeout=30).json()
    allk = sorted(set(keys) | set(sug['keys']))
    print("total keys available:", len(allk))
    if len(allk) <= 500:
        pytest.skip(f"only {len(allk)} keys available")
    cr = admin.post(f"{API}/roles", json={"name": "TEST_many_keys_role", "permissions": []}, timeout=30)
    assert cr.status_code in (200, 201), cr.text
    rid = cr.json()['id']
    try:
        up = admin.put(f"{API}/roles/{rid}", json={"permissions": allk}, timeout=60)
        assert up.status_code == 200, up.text
        got = up.json()['permission_keys']
        print("returned:", len(got))
        assert len(got) == len(allk)
        g = [r for r in admin.get(f"{API}/roles", timeout=30).json() if r['id'] == rid][0]
        assert len(g['permission_keys']) == len(allk)
    finally:
        admin.delete(f"{API}/roles/{rid}", timeout=30)
