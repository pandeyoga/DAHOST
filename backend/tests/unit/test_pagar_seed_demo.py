"""Pagar produksi seed demo (docs/GO_LIVE_RUNBOOK.md: endpoint seed demo menjawab 403 selama ALLOW_DEMO_SEED=false).

4 Nov 2026: `/api/marketing/kol/seed-demo` (tombol "Seed Demo" di layar KOL) masih hidup di produksi —
membuat 3 akun kreator dengan sandi tetap yang tertulis di repo publik + sesi live palsu beromzet ke toko
asli. Uji ini memastikan SEMUA endpoint seed DEMO/contoh berpagar `require_demo_seed_allowed()`.
(Seed konfigurasi bawaan — COA, profil posting, shift, kategori — bukan data demo, tidak termasuk.)
"""
import pathlib
import re

ROUTES = pathlib.Path(__file__).resolve().parents[2] / "routes"
DEMO_PATH = re.compile(r"seed-demo|seed-sample-data")


def _demo_routes():
    for p in sorted(ROUTES.rglob("*.py")):
        if "_archive" in p.parts:
            continue
        s = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"@router\.(?:post|put|get|delete)\(\s*['\"]([^'\"]+)['\"]", s):
            if not DEMO_PATH.search(m.group(1)):
                continue
            nxt = re.search(r"\n@router\.|\Z", s[m.end():])
            yield p.name, m.group(1), s[m.end(): m.end() + nxt.start()]


def test_ada_endpoint_demo_yang_diperiksa():
    names = {(f, path) for f, path, _ in _demo_routes()}
    assert ("marketing_kol_ops.py", "/kol/seed-demo") in names


def test_semua_endpoint_seed_demo_berpagar():
    tanpa = [f"{f} {path}" for f, path, body in _demo_routes() if "require_demo_seed_allowed()" not in body]
    assert not tanpa, "endpoint seed demo tanpa pagar ALLOW_DEMO_SEED: " + ", ".join(tanpa)


def test_pagar_menolak_bila_dimatikan(monkeypatch):
    import sys
    sys.path.insert(0, str(ROUTES.parent))
    import pytest
    from fastapi import HTTPException
    from auth import require_demo_seed_allowed
    monkeypatch.setenv("ALLOW_DEMO_SEED", "false")
    with pytest.raises(HTTPException) as e:
        require_demo_seed_allowed()
    assert e.value.status_code == 403
