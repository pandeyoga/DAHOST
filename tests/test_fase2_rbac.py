"""Uji FASE 2.2 - gerbang peran level router.

Login sekali per akun (rate-limit 5). Simpan token. Jalankan:
  cd /app/backend && set -a && . .env && set +a && python ../tests/test_fase2_rbac.py
"""
import os
import sys
import requests

API = os.environ.get("API_URL") or "http://localhost:8001"
FAILS = []
_TOKENS = {}


def login(email, pw):
    if email in _TOKENS:
        return _TOKENS[email]
    r = requests.post(f"{API}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    _TOKENS[email] = h
    return h


def check(name, cond, info=""):
    print(("PASS" if cond else "FAIL"), name, info if not cond else "")
    if not cond:
        FAILS.append(name)


def get(path, headers):
    return requests.get(f"{API}{path}", headers=headers, timeout=30)


def post(path, headers, body):
    return requests.post(f"{API}{path}", headers=headers, json=body, timeout=30)


# ---- Login sekali per peran ----
H_ADMIN = login("admin@garment.com", "Admin@123")
H_ACC = login("uji.accounting@dewiaditya.id", "Dewi@123")
H_OP = login("uji.operator@dewiaditya.id", "Dewi@123")

# eksternal
H_CMT = login("uji.cmt_vendor@dewiaditya.id", "Dewi@123")
H_VEN = login("uji.vendor@dewiaditya.id", "Dewi@123")
H_BUY = login("uji.buyer@dewiaditya.id", "Dewi@123")
H_KLIEN = login("uji.klien_maklon@dewiaditya.id", "Dewi@123")

# marketing portal
H_TOKO = login("uji.pic_toko@dewiaditya.id", "Dewi@123")
H_KOL = login("uji.marketing_kol@dewiaditya.id", "Dewi@123")
H_CS = login("uji.cs_staff@dewiaditya.id", "Dewi@123")


# ================================================================
# 1) EKSTERNAL harus 403 pada endpoint internal
# ================================================================
INTERNAL_GET = [
    "/api/rahaza/journals",
    "/api/wms/positions",
    "/api/dewi/maklon/pos",
    "/api/rahaza/employees",
]

for role_name, H in [("cmt_vendor", H_CMT), ("vendor", H_VEN), ("buyer", H_BUY), ("klien_maklon", H_KLIEN)]:
    for p in INTERNAL_GET:
        r = get(p, H)
        check(f"EXT {role_name} GET {p} → 403", r.status_code == 403, f"got {r.status_code}")
    r = post("/api/rahaza/journals", H, {"date": "2026-01-01", "description": "x", "lines": []})
    check(f"EXT {role_name} POST /api/rahaza/journals → 403", r.status_code == 403, f"got {r.status_code}")

# Internal tetap tidak 403 pada endpoint tsb (200/4xx-selain-403 diterima)
for role_name, H in [("superadmin", H_ADMIN), ("accounting", H_ACC)]:
    for p in INTERNAL_GET:
        r = get(p, H)
        check(f"INT {role_name} GET {p} → BUKAN 403", r.status_code != 403, f"got {r.status_code}")


# ================================================================
# 2) Vendor/buyer tetap bisa akses portal & endpoint kerjanya
# ================================================================
VENDOR_OK = [
    ("cmt_vendor", H_CMT, "/api/production-jobs"),
    ("cmt_vendor", H_CMT, "/api/vendor-portal/me"),
    ("cmt_vendor", H_CMT, "/api/prod/short-shipments"),
    ("cmt_vendor", H_CMT, "/api/notifications"),
    ("buyer", H_BUY, "/api/production-pos"),
    ("buyer", H_BUY, "/api/buyer-shipments"),
]
for role_name, H, p in VENDOR_OK:
    r = get(p, H)
    check(f"{role_name} GET {p} → 200", r.status_code == 200, f"got {r.status_code} {r.text[:150]}")


# ================================================================
# 3) Peran portal marketing (pic_toko, marketing_kol, cs_staff)
#    - 403 pada domain keuangan/produksi/gudang
#    - 200 pada modul mereka & HR self-service
# ================================================================
MKT_DENY = [
    "/api/rahaza/journals",
    "/api/production-jobs",
    "/api/production-pos",
    "/api/wms/positions",
    "/api/dewi/kasbon/requests",
]
for role_name, H in [("pic_toko", H_TOKO), ("marketing_kol", H_KOL), ("cs_staff", H_CS)]:
    for p in MKT_DENY:
        r = get(p, H)
        check(f"MKT {role_name} GET {p} → 403", r.status_code == 403, f"got {r.status_code}")

# HR self-service & modul marketing/portal — harus BUKAN 403 (200 diharapkan; 404/422 diterima tidak-403)
MKT_ALLOW_PATHS = [
    "/api/rahaza/variants",
    "/api/rahaza/leaves",
    "/api/wh/returns",
]
for role_name, H in [("pic_toko", H_TOKO), ("marketing_kol", H_KOL), ("cs_staff", H_CS)]:
    for p in MKT_ALLOW_PATHS:
        r = get(p, H)
        check(f"MKT {role_name} GET {p} → BUKAN 403", r.status_code != 403, f"got {r.status_code} {r.text[:150]}")


# ================================================================
# 4) T-08 bulk-approve
# ================================================================
r = post("/api/hr/expenses/claims/bulk-approve", H_ACC, {"claim_ids": ["x"]})
check("T-08 acc bulk-approve klaim → 200", r.status_code == 200, f"got {r.status_code}")
r = post("/api/hr/travel/requests/bulk-approve", H_ACC, {"request_ids": ["x"]})
check("T-08 acc bulk-approve travel → BUKAN 403", r.status_code != 403, f"got {r.status_code}")

H_SK = login("uji.staff_keuangan@dewiaditya.id", "Dewi@123")
r = post("/api/hr/expenses/claims/bulk-approve", H_SK, {"claim_ids": ["x"]})
check("T-08 staff_keuangan bulk-approve klaim → BUKAN 403", r.status_code != 403, f"got {r.status_code}")

r = post("/api/hr/expenses/claims/bulk-approve", H_OP, {"claim_ids": ["x"]})
check("T-08 operator bulk-approve klaim → 403", r.status_code == 403, f"got {r.status_code}")


print("\nGAGAL:", FAILS if FAILS else "tidak ada")
sys.exit(1 if FAILS else 0)
