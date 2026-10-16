"""Iter 240 — custom role auto-hide menus: Maklon granular catalog, view_portals, hidden_modules, RBAC enforcement."""
import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CUST = ("uji.custom_menu@dewiaditya.id", "Dewi@123")
ADMIN = ("admin@garment.com", "Admin@123")
ACCT = ("uji.accounting@dewiaditya.id", "Dewi@123")
MAKLON_MODS = ["mak_clients", "mak_buyer_catalog", "mak_po", "mak_samples", "mak_dashboard",
               "mak_billing", "mak_hpp", "mak_ai_quote"]


def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login {email} failed {r.status_code}")
    return r.json()


@pytest.fixture(scope="session")
def admin():
    return _login(*ADMIN)


@pytest.fixture(scope="session")
def cust():
    return _login(*CUST)


@pytest.fixture(scope="session")
def acct():
    return _login(*ACCT)


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# Permission catalog — Maklon granular group
class TestCatalog:
    def test_maklon_group_granular(self, admin):
        r = requests.get(f"{BASE_URL}/api/permissions?grouped=1", headers=H(admin["token"]), timeout=30)
        assert r.status_code == 200
        g = next(x for x in r.json()["groups"] if x["portal"] == "maklon")
        assert g["granular"] is True
        assert [m["id"] for m in g["modules"]] == MAKLON_MODS
        assert "maklon_ops" in [x["id"] if isinstance(x, dict) else x for x in g.get("legacy_modules", [])]


# Login payload for custom role — portals & hidden menus
class TestCustomLogin:
    def test_portals(self, cust):
        p = set(cust["portals"])
        assert {"maklon", "finance"} <= p
        biz = p - {"self", "collaboration", "maklon", "finance"}
        assert not biz, f"unexpected portals {biz}"

    def test_hidden_maklon(self, cust):
        hidden = set(cust["hidden_modules"])
        access = cust["module_access"]
        mak = {m for m in access if m.startswith("maklon-")}
        assert "maklon-pos-engine" not in hidden and "maklon-po-360" not in hidden
        assert mak - {"maklon-pos-engine", "maklon-po-360"} <= hidden
        assert "maklon-dashboard" in hidden and "maklon-billing" in hidden

    def test_hidden_finance(self, cust):
        hidden = set(cust["hidden_modules"])
        fin = {m for m in cust["module_access"] if m.startswith("fin")}
        assert "fin-hpp" not in hidden and "fin-hpp-produk" not in hidden
        assert fin - {"fin-hpp", "fin-hpp-produk"} <= hidden

    def test_me_consistent(self, cust):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=H(cust["token"]), timeout=30)
        assert r.status_code == 200
        d = r.json()
        hm = d.get("hidden_modules") or d.get("user", {}).get("hidden_modules")
        if hm is not None:
            assert set(hm) == set(cust["hidden_modules"])


# Backend enforcement for custom role
class TestEnforcement:
    def test_pos_allowed(self, cust):
        r = requests.get(f"{BASE_URL}/api/dewi/maklon/pos", headers=H(cust["token"]), timeout=30)
        assert r.status_code == 200, r.text[:200]

    def test_invoices_denied(self, cust):
        r = requests.get(f"{BASE_URL}/api/dewi/maklon/invoices", headers=H(cust["token"]), timeout=30)
        assert r.status_code == 403
        assert r.headers.get("x-rbac-denied") is not None

    def test_samples_post_denied(self, cust):
        r = requests.post(f"{BASE_URL}/api/dewi/maklon/samples", json={}, headers=H(cust["token"]), timeout=30)
        assert r.status_code == 403

    def test_clients_lookup_get_allowed_but_post_denied(self, cust):
        # mak_clients is lookup=True: GET allowed for internal staff (dropdowns); writes need perms
        r = requests.get(f"{BASE_URL}/api/dewi/maklon/clients", headers=H(cust["token"]), timeout=30)
        assert r.status_code == 200
        r = requests.post(f"{BASE_URL}/api/dewi/maklon/clients", json={}, headers=H(cust["token"]), timeout=30)
        assert r.status_code == 403


# Regression — superadmin & built-in role
class TestRegression:
    def test_admin_no_hidden(self, admin):
        assert not admin.get("hidden_modules")
        assert {"maklon", "finance"} <= set(admin["portals"])

    def test_admin_invoices_ok(self, admin):
        r = requests.get(f"{BASE_URL}/api/dewi/maklon/invoices", headers=H(admin["token"]), timeout=30)
        assert r.status_code == 200

    def test_accounting_legacy(self, acct):
        assert "finance" in acct["portals"]
        assert not [m for m in (acct.get("hidden_modules") or []) if m.startswith("fin")]
