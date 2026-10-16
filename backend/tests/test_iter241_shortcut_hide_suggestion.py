"""Iter 241 — retest: '<portal>::<menu>' shortcut hidden entries, granular-suggestion full keys / view fallback."""
import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CUST = ("uji.custom_menu@dewiaditya.id", "Dewi@123")
ADMIN = ("admin@garment.com", "Admin@123")
ACCT = ("uji.accounting@dewiaditya.id", "Dewi@123")


def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login {email} failed {r.status_code}")
    return r.json()


@pytest.fixture(scope="module")
def admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def cust():
    return _login(*CUST)


@pytest.fixture(scope="module")
def acct():
    return _login(*ACCT)


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# Shortcut ('::') hidden entries for custom role
class TestShortcutHidden:
    def test_maklon_shortcuts_hidden(self, cust):
        hm = cust["hidden_modules"]
        mk = [h for h in hm if h.startswith("maklon::")]
        print("maklon::", mk)
        assert len(mk) >= 5, mk

    def test_finance_shortcuts_hidden(self, cust):
        fin = [h for h in cust["hidden_modules"] if h.startswith("finance::")]
        print("finance::", fin)
        assert fin, "no finance:: shortcut hidden"

    def test_no_shortcut_entry_for_nongranular_portal(self, cust):
        prefixes = {h.split("::")[0] for h in cust["hidden_modules"] if "::" in h}
        assert prefixes <= {"maklon", "finance"}, prefixes

    def test_admin_and_acct_no_shortcut_hidden(self, admin, acct):
        assert not admin.get("hidden_modules")
        assert not [h for h in (acct.get("hidden_modules") or []) if "::" in h]

    def test_me_has_same(self, cust):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=H(cust["token"]), timeout=30)
        assert r.status_code == 200
        d = r.json()
        hm = d.get("hidden_modules") or d.get("user", {}).get("hidden_modules")
        if hm is not None:
            assert set(hm) == set(cust["hidden_modules"])


# Granular suggestion
class TestSuggestion:
    def test_admin_maklon_full(self, admin):
        r = requests.post(f"{BASE_URL}/api/roles/granular-suggestion", headers=H(admin["token"]), json={
            "permissions": [], "portals": [], "role_name": "admin_maklon", "portal": "maklon"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        keys = r.json()["keys"]
        print(len(keys), keys)
        assert "mod.mak_dashboard.view" in keys
        for a in ("view", "create", "edit", "delete", "approve"):
            assert f"mod.mak_po.{a}" in keys, a
        assert len(keys) == 39, len(keys)

    def test_view_fallback_with_portal_access(self, admin):
        r = requests.post(f"{BASE_URL}/api/roles/granular-suggestion", headers=H(admin["token"]), json={
            "permissions": [], "portals": ["maklon"], "role_name": "custom_x", "portal": "maklon"}, timeout=30)
        assert r.status_code == 200
        keys = r.json()["keys"]
        mods = {k.split(".")[1] for k in keys}
        views = {k.split(".")[1] for k in keys if k.endswith(".view")}
        print(keys)
        assert len(mods) == 8 and views == mods

    def test_no_access_no_keys(self, admin):
        r = requests.post(f"{BASE_URL}/api/roles/granular-suggestion", headers=H(admin["token"]), json={
            "permissions": [], "portals": ["finance"], "role_name": "custom_x", "portal": "maklon"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["keys"] == []

    def test_non_super_forbidden(self, cust):
        r = requests.post(f"{BASE_URL}/api/roles/granular-suggestion", headers=H(cust["token"]),
                          json={"portal": "maklon"}, timeout=30)
        assert r.status_code == 403

    def test_bad_portal(self, admin):
        r = requests.post(f"{BASE_URL}/api/roles/granular-suggestion", headers=H(admin["token"]),
                          json={"portal": "nope"}, timeout=30)
        assert r.status_code == 400
