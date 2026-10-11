"""Smoke iteration_223: T-22 transition, T-20 bulk-approve paths, T-21 progress, regresi ruff --fix."""
import os, sys, json, requests

BASE = os.environ.get("BASE_URL", "http://localhost:8001")

def login(email, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]

def ok(msg): print(f"PASS {msg}")
def fail(msg): print(f"FAIL {msg}"); sys.exit(1)

admin = login("admin@garment.com", "Admin@123")
acc = login("uji.accounting@dewiaditya.id", "Dewi@123")
op = login("uji.operator@dewiaditya.id", "Dewi@123")
ok("login admin/acc/op")

H_ADMIN = {"Authorization": f"Bearer {admin}"}

# T-22 transition: session token in query, no Authorization header
r = requests.get(f"{BASE}/api/wms/audit/adjustments/export-csv", params={"token": admin}, timeout=15)
if r.status_code == 200 and (r.headers.get("content-type","" ).startswith("text/csv") or "csv" in r.headers.get("content-type","").lower() or r.text.startswith("\ufeff") or "," in r.text[:200]):
    ok(f"T-22 transisi: session token in query → 200 (bytes={len(r.content)})")
else:
    fail(f"T-22 transisi: expected 200 CSV, got {r.status_code} body={r.text[:200]}")

# T-22 download-token flow
r = requests.post(f"{BASE}/api/auth/download-token", json={"resource":"x"}, headers=H_ADMIN, timeout=10)
if r.status_code != 200: fail(f"download-token 200 expected, got {r.status_code}")
dt = r.json().get("token"); exp = r.json().get("expires_in")
if not dt or exp != 300: fail(f"download-token payload invalid: {r.json()}")
ok("T-22 download-token OK expires_in=300")

# download token as session bearer → 401
r = requests.get(f"{BASE}/api/rahaza/employees", headers={"Authorization": f"Bearer {dt}"}, timeout=10)
if r.status_code != 401: fail(f"download token as session must be 401, got {r.status_code}")
ok("T-22 download token as session → 401")

# download token as query on CSV export → 200
r = requests.get(f"{BASE}/api/wms/audit/adjustments/export-csv", params={"token": dt}, timeout=15)
if r.status_code != 200: fail(f"download token in query expected 200, got {r.status_code}")
ok("T-22 download token in query → 200")

# garbage token → 401
r = requests.get(f"{BASE}/api/wms/audit/adjustments/export-csv", params={"token": "abc"}, timeout=10)
if r.status_code != 401: fail(f"garbage token expected 401, got {r.status_code}")
ok("T-22 garbage token → 401")

# download-token without login → 401
r = requests.post(f"{BASE}/api/auth/download-token", json={"resource":"x"}, timeout=10)
if r.status_code != 401: fail(f"download-token no-auth expected 401, got {r.status_code}")
ok("T-22 download-token tanpa login → 401")

# T-21 production-progress
r = requests.get(f"{BASE}/api/production-progress", params={"limit":10}, headers=H_ADMIN, timeout=15)
if r.status_code != 200: fail(f"T-21 production-progress expected 200, got {r.status_code} body={r.text[:200]}")
data = r.json()
if not isinstance(data, list) and not isinstance(data, dict): fail("T-21 shape unexpected")
ok(f"T-21 production-progress?limit=10 → 200 (type={type(data).__name__})")

# T-20 bulk approve as accounting
H_ACC = {"Authorization": f"Bearer {acc}"}
H_OP = {"Authorization": f"Bearer {op}"}
def check_bulk(url, key):
    body = {key: ["tidak-ada"], "approval_note": "uji"}
    r = requests.post(url, json=body, headers=H_ACC, timeout=15)
    if r.status_code != 200: fail(f"{url} expected 200, got {r.status_code} body={r.text[:200]}")
    j = r.json()
    if not (j.get("ok") is True and j.get("total")==1 and j.get("success_count")==0 and j.get("failed_count")==1):
        fail(f"{url} shape: {j}")
    failed = (j.get("results") or {}).get("failed") or []
    if not failed or "Tidak ditemukan" not in (failed[0].get("reason") or ""):
        fail(f"{url} reason: {j}")
    ok(f"T-20 accounting bulk-approve {url.split('/')[-1]} → 200 not-found")
    # operator forbidden
    r2 = requests.post(url, json=body, headers=H_OP, timeout=15)
    if r2.status_code != 403: fail(f"{url} operator expected 403, got {r2.status_code}")
    ok(f"T-20 operator bulk-approve {url.split('/')[-1]} → 403")

check_bulk(f"{BASE}/api/hr/expenses/claims/bulk-approve", "claim_ids")
check_bulk(f"{BASE}/api/hr/expenses/travel/bulk-approve", "travel_ids")
check_bulk(f"{BASE}/api/hr/expenses/settlements/bulk-approve", "settlement_ids")

# Regresi ruff --fix: sample endpoints must NOT be 500
sample = [
    "/api/health",
    "/api/rahaza/employees",
    "/api/capacity/config",
    "/api/production-variances/stats",
    "/api/production-variances?limit=5",
    "/api/wms/racks",
]
for path in sample:
    r = requests.get(f"{BASE}{path}", headers=H_ADMIN, timeout=15)
    if r.status_code >= 500: fail(f"REGRESI {path} → {r.status_code} body={r.text[:200]}")
    ok(f"regresi {path} → {r.status_code}")

print("\nSEMUA SMOKE PASS")
