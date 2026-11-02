"""Unduh backup lewat tautan tab baru (2026-11-02).

Bug: tombol Download di Backup Data selalu gagal 401 untuk superadmin. Router backup dipasang di
belakang penjaga peran `_DENY_EXTERNAL_AND_MKT` (core.authz.deny_roles) yang hanya mengenal header
Bearer atau token unduh SSOT (`?token=`, aud=download); tautan memakai tiket buatan modul sendiri
(`?ticket=`) sehingga ditolak sebelum sampai ke handler. Sekarang tautan memakai token unduh SSOT
yang dikunci ke backup itu.
"""
import asyncio
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import auth  # noqa: E402
import core.authz as authz  # noqa: E402
import routes.admin_backup as ab  # noqa: E402

SUPER = {"id": "u-super", "email": "s@x", "role": "superadmin", "name": "Super"}
STAFF = {"id": "u-staff", "email": "f@x", "role": "finance_staff", "name": "Staf"}


class _Req:
    """Request minimal: header + query string (yang dibaca penjaga router & handler)."""

    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}
        self.state = types.SimpleNamespace()


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def env(tmp_path, monkeypatch):
    bdir = tmp_path / "backups"
    (bdir / "manual_20261102_233000" / "dahost_erp").mkdir(parents=True)
    (bdir / "manual_20261102_233000" / "dahost_erp" / "contoh.bson").write_bytes(b"uji")
    (bdir / "manual_20261102_220000").mkdir()
    monkeypatch.setattr(ab, "BACKUP_DIR", bdir)
    monkeypatch.setattr(ab, "DOWNLOAD_TMP_DIR", tmp_path / "dl")
    live = {"u-super": {"role": "superadmin", "blocked": False},
            "u-staff": {"role": "finance_staff", "blocked": False}}

    async def fake_live(uid):
        return live.get(uid)

    monkeypatch.setattr(ab, "_load_live_user", fake_live)

    async def fake_require_auth(request):
        hdr = request.headers.get("Authorization", "")
        if hdr == "Bearer super":
            return dict(SUPER)
        if hdr == "Bearer staff":
            return dict(STAFF)
        raise HTTPException(401, "Unauthorized")

    monkeypatch.setattr(ab, "require_auth", fake_require_auth)
    return live


def _guard():
    # penjaga yang SAMA dengan server.py `_DENY_EXTERNAL_AND_MKT`
    return authz.deny_roles(*authz.EXTERNAL_ROLES, *authz.MARKETING_PORTAL_ROLES)


def _ticket_url(as_header="Bearer super", backup_id="manual_20261102_233000"):
    res = _run(ab.create_download_ticket(_Req({"Authorization": as_header}), backup_id))
    return res


def test_tautan_memakai_token_unduh_ssot_bukan_tiket_sendiri(env):
    res = _ticket_url()
    assert res["url"].startswith("/api/admin/backup/download/manual_20261102_233000?token=")
    assert res["expires_in"] == auth.DOWNLOAD_TOKEN_TTL_SEC
    assert not hasattr(ab, "_DOWNLOAD_TICKETS") and not hasattr(ab, "_resolve_ticket")


def test_penjaga_router_meloloskan_tautan_tab_baru(env):
    """Dulu: penjaga router melempar 401 karena tautan tidak membawa Bearer maupun ?token=."""
    token = _ticket_url()["ticket"]
    _run(_guard()(_Req(query={"token": token})))           # tidak melempar
    with pytest.raises(HTTPException) as e:
        _run(_guard()(_Req(query={"ticket": token})))       # bentuk lama memang ditolak
    assert e.value.status_code == 401


def test_unduh_dengan_token_menghasilkan_zip(env):
    token = _ticket_url()["ticket"]
    resp = _run(ab.download_backup(_Req(query={"token": token}), "manual_20261102_233000", token=token))
    assert resp.media_type == "application/zip"
    assert Path(resp.path).exists() and Path(resp.path).stat().st_size > 0


def test_token_terkunci_ke_satu_backup(env):
    token = _ticket_url()["ticket"]
    with pytest.raises(HTTPException) as e:
        _run(ab.download_backup(_Req(), "manual_20261102_220000", token=token))
    assert e.value.status_code == 403


def test_token_ditolak_bila_pemilik_bukan_lagi_superadmin(env):
    token = _ticket_url()["ticket"]
    env["u-super"] = {"role": "finance_staff", "blocked": False}
    with pytest.raises(HTTPException) as e:
        _run(ab.download_backup(_Req(), "manual_20261102_233000", token=token))
    assert e.value.status_code == 403


def test_hanya_superadmin_yang_bisa_meminta_tautan(env):
    with pytest.raises(HTTPException) as e:
        _ticket_url(as_header="Bearer staff")
    assert e.value.status_code == 403


def test_token_sampah_ditolak(env):
    with pytest.raises(HTTPException) as e:
        _run(ab.download_backup(_Req(), "manual_20261102_233000", token="bukan-token"))
    assert e.value.status_code == 403
