"""Uji FASE 2.3–2.5 (T-01) — gerbang eksplisit endpoint DELETE + sisa endpoint tulis.

Prinsip: DELETE tanpa gerbang fungsi dulu bisa dipakai peran internal MANA PUN (mis. `operator`).
Kini setiap DELETE harus 403 untuk peran di luar domainnya dan TIDAK 403 (404/400/409/410/200)
untuk peran domain — dipakai id fiktif supaya tidak menghapus data nyata.

  cd /app/backend && set -a && . .env && set +a && python ../tests/test_fase23_delete_gates.py
"""
import os
import subprocess
import sys

import requests

API = os.environ.get("API_URL") or "http://localhost:8001"
FAILS = []
_TOKENS = {}
FAKE = "00000000-0000-4000-8000-000000000000"


def login(role):
    email = "admin@garment.com" if role == "admin" else f"uji.{role}@dewiaditya.id"
    pw = "Admin@123" if role == "admin" else "Dewi@123"
    if email in _TOKENS:
        return _TOKENS[email]
    r = requests.post(f"{API}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    _TOKENS[email] = {"Authorization": f"Bearer {r.json()['token']}"}
    return _TOKENS[email]


def check(name, cond, info=""):
    print(("PASS" if cond else "FAIL"), name, "" if cond else info)
    if not cond:
        FAILS.append(name)


def call(method, path, role, **kw):
    return requests.request(method, f"{API}{path}", headers=login(role), timeout=30, **kw)


# (path, peran yang DITOLAK, peran yang LOLOS gerbang)
DELETE_MATRIX = [
    (f"/api/dewi/onboarding/templates/{FAKE}", "operator", "hr"),
    (f"/api/dewi/org/positions/{FAKE}", "operator", "hr"),
    (f"/api/dewi/recruitment/candidates/{FAKE}", "rnd_staff", "hr"),
    (f"/api/dewi/lms/courses/{FAKE}", "operator", "hr"),
    (f"/api/rahaza/payroll-allowances/{FAKE}", "operator", "hr"),
    (f"/api/rahaza/finance/budgets/{FAKE}", "hr", "accounting"),
    (f"/api/rahaza/finance/accruals/{FAKE}", "operator", "accounting"),
    (f"/api/rahaza/downtime/{FAKE}", "hr", "supervisor_produksi"),
    (f"/api/rahaza/production-calendar/{FAKE}", "hr", "admin_produksi"),
    (f"/api/wms/racks/{FAKE}", "operator", "admin_gudang"),
    (f"/api/wms/units/{FAKE}", "rnd_staff", "admin_gudang"),
    (f"/api/wms/fabric-rolls/{FAKE}", "operator", "admin_gudang"),
    (f"/api/wms/picklist/{FAKE}", "hr", "admin_gudang"),
    (f"/api/wms/delivery-notes/{FAKE}", "operator", "admin_gudang"),
    (f"/api/maklon/ai-quote/{FAKE}", "operator", "admin_maklon"),
    (f"/api/dewi/maklon/qc/{FAKE}", "operator", "admin_maklon"),
    (f"/api/dewi/maklon/payments/{FAKE}", "admin_maklon", "accounting"),
    (f"/api/marketing/ads/campaigns/{FAKE}", "operator", "marketing_kol"),
    (f"/api/marketing/discounts/{FAKE}", "cs_staff", "pic_toko"),
    (f"/api/marketing/reviews/{FAKE}", "operator", "cs_staff"),
    (f"/api/marketing/accounts/{FAKE}", "pic_toko", "owner"),
    (f"/api/marketing/live/sessions/{FAKE}", "hr", "marketing_kol"),
    (f"/api/marketing/budget/spend/{FAKE}", "accounting", "marketing_kol"),
    (f"/api/pdf-export-configs/{FAKE}", "operator", "owner"),
]


def main():
    for path, denied, allowed in DELETE_MATRIX:
        rd = call("DELETE", path, denied)
        check(f"DELETE {path} ditolak untuk {denied}", rd.status_code == 403, f"HTTP {rd.status_code} {rd.text[:100]}")
        ra = call("DELETE", path, allowed)
        check(f"DELETE {path} lolos gerbang untuk {allowed} (bukan 403/405)", ra.status_code not in (403, 405),
              f"HTTP {ra.status_code} {ra.text[:100]}")

    # 2.3 kepemilikan: cuti orang lain tidak boleh dihapus operator; delegasi hanya pendelegasi/HR
    r = call("DELETE", f"/api/rahaza/leaves/{FAKE}", "operator")
    check("DELETE cuti fiktif oleh operator → 404 (bukan 500)", r.status_code in (403, 404), f"HTTP {r.status_code}")
    r = call("DELETE", f"/api/rahaza/delegations/{FAKE}", "operator")
    check("DELETE delegasi fiktif → 404", r.status_code == 404, f"HTTP {r.status_code} {r.text[:80]}")

    # 2.5 sisa endpoint tulis
    r = call("POST", "/api/marketing/webhooks/manual", "operator", json={"platform": "shopee", "event_type": "x", "payload": {}})
    check("POST webhooks/manual ditolak operator", r.status_code == 403, f"HTTP {r.status_code}")
    r = call("POST", "/api/push/send", "operator", json={"title": "x", "body": "y"})
    check("POST push/send ditolak operator", r.status_code in (403, 503), f"HTTP {r.status_code}")
    r = call("POST", "/api/notifications/trigger/wo-due-scan", "hr")
    check("POST wo-due-scan ditolak hr", r.status_code == 403, f"HTTP {r.status_code}")
    r = call("GET", "/api/marketing/orders", "cmt_vendor")
    check("GET marketing/orders ditolak cmt_vendor (server gate 2.5)", r.status_code == 403, f"HTTP {r.status_code}")
    r = call("GET", "/api/comm/channels", "vendor")
    check("GET comm/channels ditolak vendor", r.status_code in (403, 404), f"HTTP {r.status_code}")
    r = call("GET", "/api/marketing/orders", "pic_toko")
    check("GET marketing/orders tetap boleh pic_toko", r.status_code == 200, f"HTTP {r.status_code}")
    r = call("POST", "/api/auth/change-password", "operator", json={"old_password": "salah", "new_password": "Xx12345678!"})
    check("change-password tetap self-service (bukan 403)", r.status_code != 403, f"HTTP {r.status_code}")

    # audit statik: 0 endpoint tulis tanpa gerbang & 0 DELETE tanpa gerbang fungsi
    out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "..", "scripts", "audit_authz.py"), "--gate"],
                         capture_output=True, text=True)
    check("audit_authz --gate hijau", out.returncode == 0, out.stdout[-300:])
    check("audit: TANPA GERBANG SAMA SEKALI = 0", "SAMA SEKALI (fungsi/berkas/server): 0 " in out.stdout, out.stdout[:200])

    print(f"\n{'SEMUA LULUS' if not FAILS else 'GAGAL: ' + str(len(FAILS))}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
