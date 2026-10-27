"""Access sync / live-role-change tests — iteration 237.

Covers:
- Live role & status read: role change / rename / deactivation take effect on same token.
- Portal gate denies cross-portal writes but allows reads.
- Admin /api/admin/access-sync/{audit,fix,user/{uid}} endpoints.
"""
import os
import time

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL missing"

ADMIN_EMAIL = "admin@garment.com"
ADMIN_PASS = "Admin@123"
USER_EMAIL = "test_sync@example.com"
USER_PASS = "Test@1234"

ROLE_A = "TEST_sync_a"
ROLE_B2 = "TEST_sync_b2"
ROLE_B3 = "TEST_sync_b3"


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:300]}"
    return r.json()


@pytest.fixture(scope="session")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASS)["token"]


def _find_role(admin_tok, name):
    r = requests.get(f"{BASE_URL}/api/roles", headers=_h(admin_tok), timeout=20)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    items = data if isinstance(data, list) else data.get("items", [])
    for role in items:
        if role.get("name") == name:
            return role
    return None


def _delete_role_by_name(admin_tok, name):
    role = _find_role(admin_tok, name)
    if role:
        requests.delete(f"{BASE_URL}/api/roles/{role['id']}",
                        headers=_h(admin_tok), timeout=20)


def _find_user(admin_tok, email):
    r = requests.get(f"{BASE_URL}/api/users", headers=_h(admin_tok), timeout=30)
    assert r.status_code == 200
    for u in r.json():
        if (u.get("email") or "").lower() == email.lower():
            return u
    return None


def _delete_user_by_email(admin_tok, email):
    u = _find_user(admin_tok, email)
    if u:
        requests.delete(f"{BASE_URL}/api/users/{u['id']}",
                        headers=_h(admin_tok), timeout=20)


def _create_role(admin_tok, name, portals, perms):
    _delete_role_by_name(admin_tok, name)
    r = requests.post(f"{BASE_URL}/api/roles", headers=_h(admin_tok), timeout=20,
                      json={"name": name, "description": "autotest access-sync",
                            "portals": portals, "permissions": perms})
    assert r.status_code in (200, 201), f"create role {name}: {r.status_code} {r.text[:300]}"
    return r.json()


@pytest.fixture(scope="module")
def seeded(admin_token):
    """Create roles TEST_sync_a + TEST_sync_b2 and user test_sync@example.com."""
    # Clean leftovers first (any)
    _delete_user_by_email(admin_token, USER_EMAIL)
    for n in (ROLE_A, ROLE_B2, ROLE_B3):
        _delete_role_by_name(admin_token, n)

    role_a = _create_role(admin_token, ROLE_A, ["hr"],
                          ["mod.hr_employees.view", "mod.hr_attendance.view"])
    role_b2 = _create_role(admin_token, ROLE_B2, ["finance"],
                           ["mod.fin_expenses.view"])

    # Create user via POST /api/users
    r = requests.post(f"{BASE_URL}/api/users", headers=_h(admin_token), timeout=20,
                     json={"email": USER_EMAIL, "name": "Sync Tester",
                           "password": USER_PASS, "role": ROLE_A})
    assert r.status_code in (200, 201), f"create user: {r.status_code} {r.text[:300]}"
    user_doc = r.json()
    assert user_doc.get("role") == ROLE_A
    assert user_doc.get("role_id") == role_a["id"], \
        f"role_id not synced on create: user.role_id={user_doc.get('role_id')} vs role.id={role_a['id']}"

    data = {"role_a": role_a, "role_b2": role_b2, "user_id": user_doc["id"]}
    yield data

    # Teardown
    _delete_user_by_email(admin_token, USER_EMAIL)
    for n in (ROLE_A, ROLE_B2, ROLE_B3):
        _delete_role_by_name(admin_token, n)


@pytest.fixture(scope="module")
def user_token(seeded):
    return _login(USER_EMAIL, USER_PASS)["token"]


# ─────────────── Access sync admin endpoints auth ───────────────
class TestAccessSyncAuth:
    def test_audit_requires_superadmin(self, seeded, user_token):
        r = requests.get(f"{BASE_URL}/api/admin/access-sync/audit",
                         headers=_h(user_token), timeout=20)
        assert r.status_code == 403

    def test_fix_requires_superadmin(self, seeded, user_token):
        r = requests.post(f"{BASE_URL}/api/admin/access-sync/fix",
                          headers=_h(user_token), timeout=20)
        assert r.status_code == 403

    def test_user_detail_requires_superadmin(self, seeded, user_token):
        r = requests.get(f"{BASE_URL}/api/admin/access-sync/user/{seeded['user_id']}",
                         headers=_h(user_token), timeout=20)
        assert r.status_code == 403


class TestAccessSyncEndpoints:
    def test_audit_shape(self, admin_token, seeded):
        r = requests.get(f"{BASE_URL}/api/admin/access-sync/audit",
                         headers=_h(admin_token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        s = d["summary"]
        assert set(s.keys()) >= {"total", "ok", "error", "fixable"}
        emails = {u["email"] for u in d["users"]}
        assert USER_EMAIL in emails
        row = next(u for u in d["users"] if u["email"] == USER_EMAIL)
        assert "portals" in row and "perm_count" in row and "granular_portals" in row
        assert "hr" in row["granular_portals"]

    def test_fix_idempotent(self, admin_token, seeded):
        r1 = requests.post(f"{BASE_URL}/api/admin/access-sync/fix",
                           headers=_h(admin_token), timeout=30)
        assert r1.status_code == 200
        r2 = requests.post(f"{BASE_URL}/api/admin/access-sync/fix",
                           headers=_h(admin_token), timeout=30)
        assert r2.status_code == 200
        # Second call should fix 0 items (idempotent).
        assert r2.json()["fixed"] == 0, f"not idempotent: {r2.json()}"

    def test_user_detail(self, admin_token, seeded):
        uid = seeded["user_id"]
        r = requests.get(f"{BASE_URL}/api/admin/access-sync/user/{uid}",
                         headers=_h(admin_token), timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == USER_EMAIL
        assert "hr" in d.get("portals", [])
        assert "module_access" in d and "granular" in d
        gmods = {g["module"] for g in d["granular"]}
        assert "hr_employees" in gmods and "hr_attendance" in gmods


# ─────────────── Granular + portal gate for test_sync user ───────────────
class TestGateInitial:
    def test_hr_employees_view_ok(self, user_token):
        r = requests.get(f"{BASE_URL}/api/rahaza/employees?limit=1",
                         headers=_h(user_token), timeout=20)
        assert r.status_code == 200, r.text[:200]

    def test_hr_attendance_view_ok(self, user_token):
        r = requests.get(f"{BASE_URL}/api/rahaza/attendance",
                         headers=_h(user_token), timeout=20)
        assert r.status_code == 200, r.text[:200]

    def test_hr_employees_delete_denied(self, user_token):
        r = requests.delete(f"{BASE_URL}/api/rahaza/employees/does-not-exist",
                            headers=_h(user_token), timeout=20)
        assert r.status_code == 403
        assert r.headers.get("x-rbac-denied") == "1"

    def test_cross_portal_expenses_denied(self, user_token):
        # mod.fin_expenses.* not granted and portal 'finance' not in role portals -> 403.
        r = requests.post(f"{BASE_URL}/api/rahaza/expenses",
                          headers=_h(user_token), json={}, timeout=20)
        assert r.status_code == 403
        assert r.headers.get("x-rbac-denied") == "1"


# ─────────────── Live sync: perm change on same token ───────────────
class TestLivePermChange:
    def test_add_hr_leave_takes_effect(self, admin_token, user_token, seeded):
        rid = seeded["role_a"]["id"]
        new_perms = ["mod.hr_employees.view", "mod.hr_attendance.view", "mod.hr_leave.view"]
        u = requests.put(f"{BASE_URL}/api/roles/{rid}", headers=_h(admin_token), timeout=20,
                         json={"permissions": new_perms})
        assert u.status_code == 200, u.text[:300]
        ok = False
        for _ in range(10):
            time.sleep(1.5)
            r = requests.get(f"{BASE_URL}/api/rahaza/leaves?limit=1",
                             headers=_h(user_token), timeout=20)
            if r.status_code == 200:
                ok = True
                break
        assert ok, f"hr_leave.view not effective on same token (last={r.status_code})"


# ─────────────── Live sync: role switch on same token ───────────────
class TestLiveRoleSwitch:
    def test_switch_user_role_to_b2(self, admin_token, user_token, seeded):
        uid = seeded["user_id"]
        p = requests.put(f"{BASE_URL}/api/users/{uid}", headers=_h(admin_token), timeout=20,
                         json={"role": ROLE_B2})
        assert p.status_code == 200, p.text[:300]
        # role_id must be synced to role_b2.
        body = p.json()
        assert body.get("role") == ROLE_B2
        assert body.get("role_id") == seeded["role_b2"]["id"]
        # auth/me reflects new role & portals
        found = False
        for _ in range(10):
            time.sleep(1.0)
            me = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(user_token), timeout=20)
            if me.status_code == 200:
                md = me.json()
                role = md.get("role") or md.get("user", {}).get("role")
                portals = md.get("portals") or md.get("user", {}).get("portals") or md.get("allowed_portals") or []
                if role == ROLE_B2 and "finance" in portals:
                    found = True
                    break
        assert found, f"auth/me did not reflect new role; last={md}"

    def test_finance_expenses_view_ok(self, user_token):
        for _ in range(5):
            time.sleep(1.0)
            r = requests.get(f"{BASE_URL}/api/rahaza/expenses?limit=1",
                             headers=_h(user_token), timeout=20)
            if r.status_code == 200:
                break
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"

    def test_hr_attendance_no_longer_hr_granular_gated(self, user_token):
        # Spec: reads remain allowed cross-portal; HR granular gate no longer applies
        # since role_b2 has no mod.hr_* perms. So GET is 200 (not 403).
        r = requests.get(f"{BASE_URL}/api/rahaza/attendance",
                         headers=_h(user_token), timeout=20)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"


# ─────────────── Live sync: role rename cascades to user ───────────────
class TestRoleRenameCascade:
    def test_rename_b2_to_b3(self, admin_token, user_token, seeded):
        rid = seeded["role_b2"]["id"]
        r = requests.put(f"{BASE_URL}/api/roles/{rid}", headers=_h(admin_token), timeout=20,
                         json={"name": ROLE_B3})
        assert r.status_code == 200, r.text[:300]
        # same user token still works, auth/me shows new role name
        me_role = None
        for _ in range(10):
            time.sleep(1.0)
            me = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(user_token), timeout=20)
            if me.status_code == 200:
                me_role = me.json().get("role") or me.json().get("user", {}).get("role")
                if me_role == ROLE_B3:
                    break
        assert me_role == ROLE_B3, f"rename not cascaded; last={me_role}"
        # Permission still works
        r2 = requests.get(f"{BASE_URL}/api/rahaza/expenses?limit=1",
                          headers=_h(user_token), timeout=20)
        assert r2.status_code == 200, f"{r2.status_code} {r2.text[:200]}"


# ─────────────── Live sync: deactivation blocks token ───────────────
class TestDeactivation:
    @pytest.mark.parametrize("patch", [
        {"status": "inactive"},
        {"active": False},
        {"is_active": False},
    ])
    def test_deactivate_blocks_token(self, admin_token, user_token, seeded, patch):
        uid = seeded["user_id"]
        # Make sure user is active first
        requests.put(f"{BASE_URL}/api/users/{uid}", headers=_h(admin_token), timeout=20,
                     json={"status": "active", "active": True, "is_active": True})
        time.sleep(1.5)
        pre = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(user_token), timeout=20)
        assert pre.status_code == 200, f"pre-deactivation /auth/me not 200: {pre.status_code}"

        p = requests.put(f"{BASE_URL}/api/users/{uid}", headers=_h(admin_token), timeout=20,
                         json=patch)
        assert p.status_code == 200
        blocked = False
        last = None
        for _ in range(15):
            time.sleep(1.5)
            me = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(user_token), timeout=20)
            last = me.status_code
            if me.status_code == 401:
                blocked = True
                break
        # restore
        requests.put(f"{BASE_URL}/api/users/{uid}", headers=_h(admin_token), timeout=20,
                     json={"status": "active", "active": True, "is_active": True})
        assert blocked, f"deactivate via {patch} did not block token (last={last})"
