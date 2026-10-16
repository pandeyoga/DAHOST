"""Granular RBAC per module — iteration 236 test."""
import os
import time

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "https://fresh-context-1.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "admin@garment.com"
ADMIN_PASS = "Admin@123"
HR_EMAIL = "test_granular_hr@example.com"
HR_PASS = "Test@1234"
HR_ROLE_NAME = "test_hr_granular"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:200]}"
    return r.json()


@pytest.fixture(scope="session")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASS)["token"]


@pytest.fixture(scope="session")
def hr_login_payload():
    return _login(HR_EMAIL, HR_PASS)


@pytest.fixture(scope="session")
def hr_token(hr_login_payload):
    return hr_login_payload["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _get_role(admin_token, name):
    r = requests.get(f"{BASE_URL}/api/roles", headers=_h(admin_token), timeout=20)
    assert r.status_code == 200
    data = r.json()
    for role in data if isinstance(data, list) else data.get("items", []):
        if role.get("name") == name:
            return role
    return None


# ────────────────────────── Permission catalog ──────────────────────────
class TestPermissionsCatalog:
    def test_grouped_catalog_shape(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/permissions?grouped=1",
                         headers=_h(admin_token), timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "groups" in data and isinstance(data["groups"], list)
        granular_portals = ("management", "production", "cutting", "procurement",
                            "warehouse", "accessories", "finance", "sales", "hr",
                            "toko", "rnd", "assets")
        by_portal = {g["portal"]: g for g in data["groups"]}
        for p in granular_portals:
            assert p in by_portal, f"portal {p} missing"
            assert by_portal[p]["granular"] is True, f"{p} should be granular"
            # legacy_modules key must exist (may be empty list)
            assert "legacy_modules" in by_portal[p]
        # maklon/sysadmin/collaboration must NOT be granular
        for p in ("maklon", "sysadmin", "collaboration"):
            if p in by_portal:
                assert by_portal[p]["granular"] is False, f"{p} must remain non-granular"

    def test_hr_portal_has_granular_modules(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/permissions?grouped=1",
                         headers=_h(admin_token), timeout=20)
        hr = next(g for g in r.json()["groups"] if g["portal"] == "hr")
        ids = {m["id"]: m for m in hr["modules"]}
        for mid in ("hr_employees", "hr_payroll", "hr_attendance", "hr_recruitment"):
            assert mid in ids, f"module {mid} missing"
            assert ids[mid].get("granular") is True
            # perms may be named "permissions" per shape; try both
            perms = ids[mid].get("perms") or ids[mid].get("permissions") or []
            keys = {p.get("key") for p in perms}
            for a in ("view", "create", "edit", "delete", "approve", "export"):
                assert f"mod.{mid}.{a}" in keys, (
                    f"missing key mod.{mid}.{a}; got sample={sorted(keys)[:8]}")


# ────────────────────────── Role CRUD mod.* persistence ──────────────────────────
class TestRolesModKeys:
    def test_create_update_delete_mod_role(self, admin_token):
        role_name = f"TEST_mod_role_{int(time.time())}"
        keys = ["mod.hr_employees.view", "mod.hr_payroll.view"]
        r = requests.post(f"{BASE_URL}/api/roles", headers=_h(admin_token), timeout=20,
                          json={"name": role_name, "description": "autotest",
                                "permissions": keys})
        assert r.status_code in (200, 201), f"create: {r.status_code} {r.text[:300]}"
        rid = r.json().get("id")
        assert rid, r.text[:300]
        got = r.json().get("permission_keys") or []
        for k in keys:
            assert k in got, f"mod key not persisted in create response: {got}"

        try:
            # Verify via list
            role = _get_role(admin_token, role_name)
            assert role is not None
            pk = set(role.get("permission_keys") or [])
            for k in keys:
                assert k in pk, f"persisted key missing after list GET: {k}"

            # PUT update: add delete key
            new_keys = keys + ["mod.hr_employees.delete"]
            u = requests.put(f"{BASE_URL}/api/roles/{rid}", headers=_h(admin_token), timeout=20,
                             json={"permissions": new_keys})
            assert u.status_code == 200, f"PUT: {u.status_code} {u.text[:300]}"
            pk2 = set(u.json().get("permission_keys") or [])
            assert "mod.hr_employees.delete" in pk2, f"PUT response missing new key: {pk2}"
        finally:
            d = requests.delete(f"{BASE_URL}/api/roles/{rid}", headers=_h(admin_token), timeout=20)
            assert d.status_code in (200, 204), f"delete: {d.status_code}"


# ────────────────────────── Login payload + /auth/me ──────────────────────────
class TestLoginAndMe:
    def test_login_payload_includes_module_access(self, hr_login_payload):
        p = hr_login_payload
        assert "module_access" in p
        ma = p["module_access"]
        assert set(ma.get("hr-employees", [])) >= {"view", "create"}, ma.get("hr-employees")
        assert "view" in ma.get("hr-payroll-hub", []), ma.get("hr-payroll-hub")
        hidden = set(p.get("hidden_modules") or [])
        for menu in ("hr-attendance-hub", "hr-recruitment"):
            assert menu in hidden, f"menu {menu} must be hidden"
        perms = set(p.get("user", {}).get("permissions") or [])
        for legacy in ("hr.employee.view", "hr.employee.manage", "hr.payroll.view"):
            assert legacy in perms, f"legacy implied key {legacy} missing; got={sorted(perms)}"

    def test_auth_me_matches(self, hr_token):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_h(hr_token), timeout=20)
        assert r.status_code == 200
        d = r.json()
        ma = d.get("module_access") or d.get("user", {}).get("module_access") or {}
        assert set(ma.get("hr-employees", [])) >= {"view", "create"}
        hidden = set(d.get("hidden_modules") or d.get("user", {}).get("hidden_modules") or [])
        assert "hr-attendance-hub" in hidden


# ────────────────────────── Middleware gate ──────────────────────────
class TestModuleGate:
    def test_hr_employees_view_ok(self, hr_token):
        r = requests.get(f"{BASE_URL}/api/rahaza/employees?limit=1",
                         headers=_h(hr_token), timeout=20)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"

    def test_hr_employees_create_passes_gate(self, hr_token):
        r = requests.post(f"{BASE_URL}/api/rahaza/employees", headers=_h(hr_token),
                          json={}, timeout=20)
        assert r.status_code != 403, f"gate should allow create; got {r.status_code}"
        assert r.headers.get("x-rbac-denied") != "1"

    def test_hr_employees_delete_denied(self, hr_token):
        r = requests.delete(f"{BASE_URL}/api/rahaza/employees/xyz",
                            headers=_h(hr_token), timeout=20)
        assert r.status_code == 403
        assert r.headers.get("x-rbac-denied") == "1"
        assert "Hapus" in r.json().get("detail", "")

    def test_payroll_view_ok(self, hr_token):
        r = requests.get(f"{BASE_URL}/api/rahaza/payroll-runs?limit=1",
                         headers=_h(hr_token), timeout=20)
        assert r.status_code == 200

    def test_payroll_approve_denied(self, hr_token):
        r = requests.post(f"{BASE_URL}/api/rahaza/payroll-runs/x/approve",
                          headers=_h(hr_token), json={}, timeout=20)
        assert r.status_code == 403
        assert r.headers.get("x-rbac-denied") == "1"

    def test_attendance_denied(self, hr_token):
        r = requests.get(f"{BASE_URL}/api/rahaza/attendance",
                         headers=_h(hr_token), timeout=20)
        assert r.status_code == 403
        assert r.headers.get("x-rbac-denied") == "1"

    def test_recruitment_denied(self, hr_token):
        r = requests.get(f"{BASE_URL}/api/dewi/recruitment/jobs",
                         headers=_h(hr_token), timeout=20)
        assert r.status_code == 403
        assert r.headers.get("x-rbac-denied") == "1"

    def test_shift_lookup_allowed(self, hr_token):
        r = requests.get(f"{BASE_URL}/api/hr/shifts",
                         headers=_h(hr_token), timeout=20)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"

    def test_superadmin_not_blocked(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/rahaza/attendance",
                         headers=_h(admin_token), timeout=20)
        assert r.status_code == 200


# ────────────────────────── Cache invalidation ──────────────────────────
class TestCacheInvalidation:
    def test_add_attendance_perm_takes_effect(self, admin_token, hr_token):
        r0 = requests.get(f"{BASE_URL}/api/rahaza/attendance",
                          headers=_h(hr_token), timeout=20)
        assert r0.status_code == 403, f"precondition: {r0.status_code}"
        role = _get_role(admin_token, HR_ROLE_NAME)
        assert role, f"role {HR_ROLE_NAME} missing"
        rid = role["id"]
        cur = set(role.get("permission_keys") or [])
        original = sorted(cur)
        new_keys = sorted(cur | {"mod.hr_attendance.view"})
        try:
            u = requests.put(f"{BASE_URL}/api/roles/{rid}", headers=_h(admin_token), timeout=20,
                             json={"permissions": new_keys})
            assert u.status_code == 200, u.text[:300]
            assert "mod.hr_attendance.view" in (u.json().get("permission_keys") or [])
            ok = False
            r2 = None
            for _ in range(15):
                time.sleep(2)
                r2 = requests.get(f"{BASE_URL}/api/rahaza/attendance",
                                  headers=_h(hr_token), timeout=20)
                if r2.status_code == 200:
                    ok = True
                    break
            assert ok, f"still denied after wait: {r2.status_code if r2 else 'n/a'}"
        finally:
            requests.put(f"{BASE_URL}/api/roles/{rid}", headers=_h(admin_token), timeout=20,
                         json={"permissions": original})
