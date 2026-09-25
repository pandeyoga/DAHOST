"""
Iter 231 — Verify ChunkLoadError fix code + API regression + DB read-only assertions
- lazyRetry usage across all lazy imports
- ErrorBoundary auto-reload behavior for ChunkLoadError
- rebuild_frontend.sh keeps OLD_STATIC chunks
- API regressions (admin token)
- DB read-only: harga potongan, models, boms
"""
import os
import re
import time
import gzip
import subprocess
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient
from dotenv import dotenv_values

BE_ENV = dotenv_values("/app/backend/.env")
FE_ENV = dotenv_values("/app/frontend/.env")
BASE_URL = FE_ENV["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = BE_ENV["MONGO_URL"].strip('"')
DB_NAME = BE_ENV["DB_NAME"].strip('"')

_TOKEN = None


@pytest.fixture(scope="session")
def admin_token():
    global _TOKEN
    if _TOKEN:
        return _TOKEN
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@garment.com", "password": "Admin@123"},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    _TOKEN = r.json().get("access_token") or r.json().get("token")
    assert _TOKEN
    return _TOKEN


@pytest.fixture(scope="session")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def mongo_db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


# ---------------- Frontend code checks (static, no rebuild) ----------------

SRC = Path("/app/frontend/src")


def test_lazy_imports_all_use_lazy_retry():
    """grep 'lazy(() => import(' only present inside lazyRetry.js"""
    offenders = []
    for p in SRC.rglob("*.js*"):
        text = p.read_text(errors="ignore")
        if re.search(r"\blazy\(\(\)\s*=>\s*import\(", text):
            if p.name != "lazyRetry.js":
                offenders.append(str(p))
    assert not offenders, f"Found bare React.lazy() outside lazyRetry.js: {offenders}"


def test_error_boundary_auto_reload_for_chunk_load():
    text = (SRC / "components/ErrorBoundary.jsx").read_text()
    assert "isChunkLoadError" in text
    assert "reloadOnceForNewBuild" in text
    # getDerivedStateFromError must call reload for chunk load error
    m = re.search(r"static\s+getDerivedStateFromError.*?\}\s*\n", text, re.DOTALL)
    assert m and "isChunkLoadError" in m.group(0) and "reloadOnceForNewBuild" in m.group(0), \
        "getDerivedStateFromError must invoke isChunkLoadError + reloadOnceForNewBuild"


def test_lazy_retry_uses_isChunkLoadError_and_reload():
    text = (SRC / "lib/lazyRetry.js").read_text()
    assert "isChunkLoadError" in text
    assert "reloadOnceForNewBuild" in text


def test_rebuild_script_preserves_old_chunks():
    sh = Path("/app/scripts/rebuild_frontend.sh").read_text()
    assert "OLD_STATIC" in sh
    assert "mktemp -d" in sh
    # copies old file to build/static if not present in new build
    assert "cp -p" in sh
    assert "build/static" in sh


# ---------------- API regression ----------------

def test_health():
    r = requests.get(f"{BASE_URL}/api/health", timeout=15)
    assert r.status_code == 200, r.text[:200]


def test_audit_findings_total_30(auth_headers):
    r = requests.get(f"{BASE_URL}/api/rahaza/admin/audit-findings", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    total = data.get("total") if isinstance(data, dict) else None
    if total is None and isinstance(data, dict) and "items" in data:
        total = len(data["items"])
    if total is None and isinstance(data, list):
        total = len(data)
    assert total == 30, f"expected 30 audit findings, got {total}"


def test_rnd_completeness(auth_headers):
    r = requests.get(f"{BASE_URL}/api/dewi/rnd/completeness", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text[:200]


def test_financial_recap(auth_headers):
    r = requests.get(f"{BASE_URL}/api/financial-recap", headers=auth_headers, timeout=25)
    assert r.status_code == 200, r.text[:200]


def test_download_konsolidasi_gzip():
    r = requests.get(f"{BASE_URL}/downloads/konsolidasi_master_20260923.json.gz", timeout=30)
    assert r.status_code == 200, r.text[:200]
    # gzip magic
    assert r.content[:2] == b"\x1f\x8b", "expected gzip magic header"
    try:
        gzip.decompress(r.content[:65536] + b"")
    except Exception:
        # decompress full
        gzip.decompress(r.content)


def test_maklon_production_detail_cutting(auth_headers):
    oid = "5f29f37f-18a0-425f-a978-214e7615c530"
    r = requests.get(f"{BASE_URL}/api/dewi/maklon/orders/{oid}/production-detail", headers=auth_headers, timeout=25)
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    ci = d.get("stage_qty", {}).get("cutting_input")
    assert ci == 123, f"cutting_input expected 123, got {ci}"


# ---------------- DB read-only assertions ----------------

def test_cut_panel_materials_zero_priced(mongo_db):
    col = mongo_db["rahaza_materials"]
    cuts = list(col.find({"is_cut_panel": True}, {"unit_cost": 1, "value_status": 1}))
    assert len(cuts) == 807, f"cut panel count {len(cuts)} != 807"
    bad = [c for c in cuts if (c.get("unit_cost") or 0) != 0 or c.get("value_status") != "unvalued"]
    assert not bad, f"{len(bad)} cut panels have non-zero cost or wrong value_status"


def test_active_boms_cut_panel_lines_zero(mongo_db):
    col = mongo_db["rahaza_boms"]
    active = list(col.find({"is_active": True}))
    offenders = []
    for bom in active:
        for line in bom.get("lines", []) or []:
            if line.get("is_cut_panel") and (line.get("unit_cost_base") or 0) != 0:
                offenders.append((bom.get("id"), line.get("material_id"), line.get("unit_cost_base")))
    assert not offenders, f"cut panel BOM lines with non-zero unit_cost_base: {offenders[:5]} (total {len(offenders)})"


def test_active_models_hpp_menunggu_cutting(mongo_db):
    col = mongo_db["rahaza_models"]
    # 'active' flag = True; exclude models tagged 'dihentikan' (discontinued still keep old HPP).
    active = list(col.find({"active": True}))
    live = [m for m in active if (m.get("hpp_validation") or {}).get("status") != "dihentikan"]
    assert len(live) == 98, f"live active models count {len(live)} != 98"
    bad = []
    for m in live:
        hpp = m.get("hpp")
        src = m.get("hpp_source")
        v = (m.get("hpp_validation") or {}).get("status")
        if (hpp or 0) != 0 or src != "menunggu_cutting" or v != "menunggu_cutting":
            bad.append((m.get("id"), hpp, src, v))
    assert not bad, f"models with unexpected hpp state: {bad[:3]} (total {len(bad)})"


def test_master_fill_recalc_gated(mongo_db):
    """Verify master_fill.recalc_standard_costs is guarded by _standard_cost_enabled flag."""
    text = Path("/app/backend/core/master_fill.py").read_text()
    assert "_standard_cost_enabled" in text, "flag _standard_cost_enabled missing"
    # Ensure recalc bail-outs when flag is False
    assert re.search(r"_standard_cost_enabled.*?(return|False)", text, re.DOTALL), \
        "recalc must short-circuit when _standard_cost_enabled is False"


# ---------------- Uji owner harness (mongomock) ----------------

UJI_DIR = "/app/memory/uji_finance_owner/UJI_FINANCE"


def _run_uji(script):
    env = os.environ.copy()
    env["DAHOST_REPO"] = "/app"
    p = subprocess.run(
        ["python3", script],
        cwd=UJI_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return p.returncode, (p.stdout + "\n" + p.stderr)


@pytest.mark.skipif(not Path(f"{UJI_DIR}/t5_reports.py").exists(), reason="t5_reports.py missing")
def test_uji_t5_reports():
    rc, out = _run_uji("t5_reports.py")
    assert "hasil: 6 lulus dari 6" in out or "6 lulus dari 6" in out, out[-800:]


@pytest.mark.skipif(not Path(f"{UJI_DIR}/t1_recap.py").exists(), reason="t1_recap.py missing")
def test_uji_t1_recap():
    rc, out = _run_uji("t1_recap.py")
    assert "7 lulus dari 7" in out, out[-800:]


@pytest.mark.skipif(not Path(f"{UJI_DIR}/t9_control.py").exists(), reason="t9_control.py missing")
def test_uji_t9_control():
    rc, out = _run_uji("t9_control.py")
    assert "5 lulus dari 5" in out, out[-800:]
