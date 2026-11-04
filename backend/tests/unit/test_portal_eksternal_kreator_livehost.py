"""Portal eksternal Kreator & Livehost (4 Nov 2026).

Dulu gerbang router `_DENY_EXTERNAL` (core.authz) hanya mengenal JWT karyawan, jadi SEMUA panggilan
portal — termasuk login — dijawab 401 "Unauthorized". Selain itu skrip/pelatihan Livehost tidak bisa
dibuat (model Pydantic tidak cocok dengan form) dan host bisa mengisi performa shift host lain.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

import auth  # noqa: E402
from core import authz  # noqa: E402

SECRET = "uji-rahasia-lokal"


def _req(path: str, token: str = "") -> Request:
    headers = [(b"authorization", f"Bearer {token}".encode())] if token else []
    return Request({"type": "http", "method": "GET", "path": path, "headers": headers, "query_string": b""})


def _tok(payload: dict) -> str:
    return pyjwt.encode({**payload, "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, SECRET, algorithm="HS256")


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET", SECRET)


def _gate(path, token=""):
    dep = authz.deny_roles(*authz.EXTERNAL_ROLES)
    return asyncio.run(dep(_req(path, token)))


def test_login_portal_tidak_dihadang_gerbang_karyawan():
    _gate("/api/marketing/creator-portal/auth/login")
    _gate("/api/marketing/livehost/portal/auth/login")
    _gate("/api/marketing/creator-portal/catalog", _tok({"creator_id": "c1", "aud": "creator-portal"}))


def test_rute_internal_tetap_digerbang():
    with pytest.raises(HTTPException) as e:
        _gate("/api/marketing/accounts")
    assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:
        _gate("/api/marketing/accounts", _tok({"id": "v", "role": "vendor"}))
    assert e.value.status_code == 403
    # token portal tidak membuka rute internal
    with pytest.raises(HTTPException):
        _gate("/api/marketing/accounts", _tok({"host_id": "h1", "aud": "livehost-portal"}))


def test_rute_campuran_performa_shift():
    path = "/api/marketing/livehost/shifts/abc/performance"
    _gate(path, _tok({"host_id": "h1", "aud": "livehost-portal"}))          # host lewat portal
    _gate(path, _tok({"id": "u", "role": "marketing_manager"}))            # staf
    with pytest.raises(HTTPException) as e:
        _gate(path, _tok({"id": "v", "role": "vendor"}))                   # peran eksternal lain
    assert e.value.status_code == 403
    with pytest.raises(HTTPException):
        _gate(path, _tok({"creator_id": "c1", "aud": "creator-portal"}))   # token kreator bukan untuk rute ini


def test_model_skrip_dan_pelatihan_cocok_dengan_form(monkeypatch):
    # modul ini membuat /app/uploads/livehost saat diimpor — di runner CI /app tidak bisa ditulis
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)
    from routes.marketing_livehost_shared import ScriptCreate, TrainingCreate, TrainingComplete
    s = ScriptCreate(title="Pembuka", category="opening", account_id=None, script_text="Halo kak",
                     language="indonesia", products_applicable=["Gamis"])
    assert s.script_text == "Halo kak" and s.products_applicable == ["Gamis"]
    t = TrainingCreate(title="Produk", category="product_knowledge", description="", content_type="video",
                       duration_minutes=30, is_required=True, expiry_months=None, passing_score=None)
    assert t.duration_minutes == 30 and t.is_required is True
    assert TrainingComplete().score is None


def test_performa_shift_dibatasi_pemilik_shift():
    src = open(os.path.join(os.path.dirname(authz.__file__), "..", "routes", "marketing_livehost_shifts.py"),
               encoding="utf-8").read()
    body = src[src.index("async def record_shift_performance"):]
    body = body[:body.index("update_one")]
    assert "shift.get('host_id') != host.get('id')" in body


def test_permintaan_kreator_membaca_fg_material_id():
    src = open(os.path.join(os.path.dirname(authz.__file__), "..", "routes", "marketing_kol_portal.py"),
               encoding="utf-8").read()
    body = src[src.index("async def creator_request_item"):]
    body = body[:body.index("@router.")]
    assert "catalog_item.get('fg_material_id')" in body
    assert "catalog_item.get('account_id') != data.account_id" in body
