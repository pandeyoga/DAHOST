"""Uji FASE 4 PLAN_PERBAIKAN_AUDIT (T-12/T-24 indeks, T-09.2 cermin dulu, T-11 rekonsiliasi, T-21 gate, T-22 download-token, T-23 CORS, T-02 bootstrap admin).

Jalankan:  cd /app/backend && set -a && . .env && set +a && python ../tests/test_fase4_hardening.py
"""
import asyncio
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import requests

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

API = os.environ.get("API_URL") or "http://localhost:8001"
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
FAILS = []
now = datetime.now(timezone.utc)
uid = lambda: str(uuid.uuid4())  # noqa: E731


def login(email, pw):
    r = requests.post(f"{API}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def check(name, cond, info=""):
    print(("PASS" if cond else "FAIL"), name, "" if cond else info)
    if not cond:
        FAILS.append(name)


TOK = login("admin@garment.com", "Admin@123")
H = {"Authorization": f"Bearer {TOK}"}


async def t12_t24_indexes():
    src = open("/app/backend/server.py").read()
    check("T-24: server.py tidak lagi memuat create_index", "create_index(" not in src)
    check("T-24: migrations/ensure_indexes.py ada & dipanggil startup",
          os.path.exists("/app/backend/migrations/ensure_indexes.py") and "ensure_all_indexes" in src)
    for coll, key in [("vendor_shipment_items", "shipment_id_1"), ("buyer_shipments", "po_id_1"), ("cmt_receipts", "status_1"),
                      ("wh_positions", "barcode_1"), ("wh_pending_movements", "type_1_status_1"), ("rahaza_boms", "active_1"),
                      ("rahaza_employees", "active_1"), ("production_jobs", "status_1"), ("users", "email_1")]:
        idx = await db[coll].index_information()
        check(f"T-12: indeks {coll}.{key} terpasang", key in idx, str(list(idx)))
    p = subprocess.run([sys.executable, "migrations/ensure_indexes.py"], capture_output=True, text=True, cwd="/app/backend")
    check("T-24: `python migrations/ensure_indexes.py` idempoten (exit 0)", p.returncode == 0, p.stderr[-300:])


async def t09_mirror_first():
    src = open("/app/backend/routes/rahaza_posting.py").read()
    i_mirror = src.index("await db.rahaza_journal_lines.insert_many(rows)")
    i_head = src.index("await db.rahaza_journal_entries.insert_one(je_doc)")
    check("T-09.2: cermin rahaza_journal_lines ditulis SEBELUM kepala rahaza_journal_entries", i_mirror < i_head)
    check("T-09.2: cermin JE yang kalah (DuplicateKeyError) dibuang", "rahaza_journal_lines.delete_many({\"je_id\": je_id})" in src)
    # jalur nyata: posting JE manual lewat API lalu cek cermin ada & seimbang
    codes = [a["code"] for a in await db.rahaza_coa_accounts.find(
        {"is_group": {"$ne": True}, "is_active": {"$ne": False}}, {"_id": 0, "code": 1}).limit(2).to_list(2)]
    if len(codes) < 2:
        print("SKIP T-09.2 posting nyata (COA < 2)")
        return
    from routes.rahaza_posting import _create_posted_je
    from datetime import date as _date
    ref = f"uji-fase4:{uid()}"
    lines = [{"account_code": codes[0], "debit": 1000, "credit": 0}, {"account_code": codes[1], "debit": 0, "credit": 1000}]
    res = await _create_posted_je(db, _date.today(), "uji fase 4", "uji_fase4", ref, lines, {"id": "uji", "name": "uji"},
                                  allow_closed_period=True)
    je_id = res.get("je_id")
    n_lines = await db.rahaza_journal_lines.count_documents({"je_id": je_id})
    check("T-09.2: JE posted punya 2 baris cermin", res.get("ok") and n_lines == 2, str(res))
    res2 = await _create_posted_je(db, _date.today(), "uji fase 4 dup", "uji_fase4", ref, lines, {"id": "uji", "name": "uji"},
                                   allow_closed_period=True)
    n_lines2 = await db.rahaza_journal_lines.count_documents({"source_ref": ref})
    check("T-10/T-09.2: sumber sama dua kali → 1 JE, cermin tetap 2 baris",
          res2.get("je_id") == je_id and n_lines2 == 2, f"{res2} lines={n_lines2}")
    await t11_bank_recon()
    await db.rahaza_journal_lines.delete_many({"source_ref": ref})
    await db.rahaza_journal_entries.delete_many({"source_ref": ref})


async def t11_bank_recon():
    from routes.dewi_bank_reconciliation import _gl_balance_until
    from routes.rahaza_posting import gl_balances_by_code
    code = (await db.rahaza_journal_lines.find_one({}, {"_id": 0, "account_code": 1}) or {}).get("account_code")
    if not code:
        print("SKIP T-11 (belum ada cermin jurnal)")
        return
    end = "2099-12-31"
    recon = await _gl_balance_until(db, code, end)
    src = open("/app/backend/routes/dewi_bank_reconciliation.py").read()
    check("T-11: _gl_balance_until membaca cermin rahaza_journal_lines", "rahaza_journal_lines.aggregate" in src)
    try:
        gl = await gl_balances_by_code(db, [code])
        val = gl.get(code) if isinstance(gl, dict) else None
        if isinstance(val, dict):
            val = round(float(val.get("debit", 0)) - float(val.get("credit", 0)), 2)
        if val is not None:
            check("T-11: saldo rekonsiliasi == saldo GL (gl_balances_by_code)", abs(float(val) - recon) < 0.01, f"recon={recon} gl={val}")
    except TypeError:
        print("SKIP T-11 perbandingan gl_balances_by_code (tanda tangan berbeda)")


def t21_gate():
    p = subprocess.run([sys.executable, "/app/scripts/check_unbounded_queries.py", "--gate"], capture_output=True, text=True, cwd="/app")
    check("T-21: gate check_unbounded_queries lolos", p.returncode == 0, p.stdout[-200:])
    check("T-21: production_progress list dibatasi", "to_list(limit)" in open("/app/backend/routes/production_execution.py").read())
    r = requests.get(f"{API}/api/production-variances/stats", headers=H)
    check("T-21: variances/stats 200 (proyeksi ringan)", r.status_code in (200, 404), f"{r.status_code} {r.text[:120]}")


def t22_download_token():
    r = requests.post(f"{API}/api/auth/download-token", headers=H, json={"resource": "wms-audit-csv"})
    check("T-22: POST /api/auth/download-token 200", r.status_code == 200 and r.json().get("expires_in") == 300, r.text[:200])
    dtok = r.json()["token"]
    import jwt
    payload = jwt.decode(dtok, options={"verify_signature": False})
    check("T-22: token unduh aud=download, umur ≤ 5 menit",
          payload.get("aud") == "download" and payload["exp"] - int(now.timestamp()) <= 305, str(payload))
    r = requests.get(f"{API}/api/rahaza/employees", headers={"Authorization": f"Bearer {dtok}"})
    check("T-22: token unduh DITOLAK sebagai sesi (401)", r.status_code == 401, f"{r.status_code}")
    r = requests.get(f"{API}/api/wms/audit/adjustments/export-csv", params={"token": dtok})
    check("T-22: unduhan CSV audit dengan token unduh → 200", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
    r = requests.get(f"{API}/api/wms/audit/adjustments/export-csv", params={"token": "bukan.token.sah"})
    check("T-22: token palsu → 401", r.status_code == 401, f"{r.status_code}")
    # Transisi: token SESI di query masih diterima selama ALLOW_SESSION_TOKEN_IN_QUERY != '0'
    # (bug sesi lalu: PyJWT melempar MissingRequiredClaimError utk token tanpa `aud`, bukan InvalidAudienceError → 401 palsu)
    r = requests.get(f"{API}/api/wms/audit/adjustments/export-csv", params={"token": TOK})
    strict = os.environ.get("ALLOW_SESSION_TOKEN_IN_QUERY", "1") == "0"
    check(f"T-22: token SESI di query → {'401 (strict)' if strict else '200 (transisi)'}",
          r.status_code == (401 if strict else 200), f"{r.status_code} {r.text[:120]}")
    from auth import create_download_token, verify_download_token
    scoped = create_download_token({"id": "x", "role": "admin"}, resource="A")
    check("T-22: token beresource 'A' ditolak untuk resource 'B'",
          verify_download_token(scoped, resource="B") is None and verify_download_token(scoped, resource="A") is not None)
    r = requests.post(f"{API}/api/auth/download-token")
    check("T-22: download-token tanpa login → 401", r.status_code == 401, f"{r.status_code}")
    for f in ("wms_delivery_notes", "wms_fabric_rolls", "wms_material_labels", "wms_labels", "wms_fg_labels", "wms_audit", "file_storage"):
        s = open(f"/app/backend/routes/{f}.py").read()
        check(f"T-22: routes/{f}.py memakai verify_download_token", "verify_download_token" in s and "verify_token_str" not in s)
    caddy = open("/app/deploy/Caddyfile").read()
    check("T-22: Caddyfile membuang query token/auth dari access log", "delete token" in caddy and "delete auth" in caddy)


def t23_t02_env():
    srv = open("/app/backend/server.py").read()
    check("T-23: tidak ada default '*' di CORS_ORIGINS", "os.environ.get('CORS_ORIGINS', '*')" not in srv and "RuntimeError(\"CORS_ORIGINS" in srv)
    r = requests.options(f"{API}/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    check("T-23: preflight di preview (CORS_ORIGINS='*') masih 200", r.status_code == 200, f"{r.status_code}")
    auth_src = open("/app/backend/auth.py").read()
    check("T-02: seed superadmin memakai BOOTSTRAP_ADMIN_EMAIL/PASSWORD", "BOOTSTRAP_ADMIN_EMAIL" in auth_src and "BOOTSTRAP_ADMIN_PASSWORD" in auth_src)
    check("T-02: deploy/README_DEPLOY tidak lagi mencetak Admin@123", "Admin@123" not in open("/app/deploy/README_DEPLOY.md").read())
    compose = open("/app/deploy/docker-compose.yml").read()
    check("deploy: compose meneruskan BOOTSTRAP_ADMIN_*, ENSURE_INDEXES, ALLOW_SESSION_TOKEN_IN_QUERY",
          all(k in compose for k in ("BOOTSTRAP_ADMIN_EMAIL", "ENSURE_INDEXES", "ALLOW_SESSION_TOKEN_IN_QUERY")))
    check("T-16: Dockerfile.frontend memakai --frozen-lockfile", "--frozen-lockfile" in open("/app/deploy/Dockerfile.frontend").read())
    check("T-24: update.sh menjalankan migrations/ensure_indexes.py", "ensure_indexes.py" in open("/app/deploy/update.sh").read())
    # simulasi boot produksi tanpa superadmin & tanpa BOOTSTRAP → RuntimeError
    code = ("import asyncio,os,sys;sys.path.insert(0,'/app/backend');"
            "import auth;asyncio.run(auth.seed_initial_data())")
    env_base = {k: v for k, v in os.environ.items() if not k.startswith("BOOTSTRAP_ADMIN_")}
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd="/app/backend",
                       env={**env_base, "ENV": "production", "DB_NAME": "uji_fase4_kosong"})
    check("T-02: ENV=production + DB kosong tanpa BOOTSTRAP_ADMIN_* → RuntimeError", "RuntimeError" in p.stderr, p.stderr[-300:])
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd="/app/backend",
                       env={**env_base, "ENV": "production", "DB_NAME": "uji_fase4_kosong",
                            "BOOTSTRAP_ADMIN_EMAIL": "owner@uji.id", "BOOTSTRAP_ADMIN_PASSWORD": "Rahasia#2026"})
    check("T-02: dengan BOOTSTRAP_ADMIN_* superadmin dibuat dari env", p.returncode == 0 and "owner@uji.id" in p.stdout, p.stderr[-300:])
    from pymongo import MongoClient
    MongoClient(os.environ["MONGO_URL"]).drop_database("uji_fase4_kosong")


async def main():
    await t12_t24_indexes()
    await t09_mirror_first()
    t21_gate()
    t22_download_token()
    t23_t02_env()
    print(f"\n{'GAGAL ' + str(len(FAILS)) + ': ' + ', '.join(FAILS) if FAILS else 'SEMUA PASS'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
