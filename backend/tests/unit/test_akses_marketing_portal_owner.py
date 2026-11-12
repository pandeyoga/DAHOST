"""Peran portal marketing + portal yang DIBERIKAN owner (laporan owner 12 Nov 2026).

Owner mencentang portal Cutting untuk peran `pic_toko` (beserta izin per modul Cutting), tetapi semua layar
Cutting dijawab 403 oleh larangan tetap router (`core.authz.deny_roles` dengan `MARKETING_PORTAL_ROLES`), yang
tidak membaca pengaturan owner. Aturan sesudah perbaikan:

  (a) modul yang portal pemiliknya / portal pintasannya diberikan owner (centang peran, portal per orang,
      izin Lihat per modul) → lolos larangan tetap;
  (b) modul di portal yang tidak diberikan, path di luar katalog, dan bawaan kode (`PORTAL_ACCESS`) → tetap 403;
  (c) peran eksternal tidak pernah ikut pengecualian ini.
Hermetik: tanpa Mongo (pemuat peran/portal/izin dipalsukan).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import auth  # noqa: E402
from core import authz  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _Req:
    def __init__(self, role, path, uid="u-uji"):
        tok = auth.create_token({"id": uid, "email": f"{uid}@contoh.test", "role": role, "name": "Uji"})
        self.headers = {"Authorization": f"Bearer {tok}"}
        self.query_params = {}

        class _U:
            pass
        self.url = _U()
        self.url.path = path


@pytest.fixture
def akun(monkeypatch):
    state = {"role": "pic_toko", "portals": [], "extra": [], "perms": [], "blocked": False}

    async def live(uid):
        return {"role": state["role"], "blocked": state["blocked"]}

    async def cfg(role, uid):
        return list(state["portals"]), list(state["extra"])

    async def rbac(role, uid):
        return list(state["perms"]), []
    monkeypatch.setattr(auth, "_load_live_user", live)
    monkeypatch.setattr(auth, "_load_portal_config", cfg)
    monkeypatch.setattr(auth, "_load_rbac", rbac)

    def _set(**kw):
        state.update(kw)
    return _set


DENY = authz.deny_roles(*authz.EXTERNAL_ROLES, *authz.MARKETING_PORTAL_ROLES)


def _lolos(role, path):
    try:
        run(DENY(_Req(role, path)))
        return True
    except HTTPException as e:
        assert e.status_code == 403
        return False


def test_portal_dicentang_owner_membuka_modulnya(akun):
    # Kasus owner: pic_toko dicentang Toko, RnD, Cutting → layar Cutting + master yang dipakainya lolos.
    akun(portals=["toko", "self", "collaboration", "rnd", "cutting"])
    for path in ("/api/cutting/orders", "/api/cutting/dashboard", "/api/cutting/locations",
                 "/api/cutting/input-materials", "/api/cutting/panels/health",
                 "/api/rahaza/sizes",        # master RnD
                 "/api/rahaza/models"):      # master Produksi, pintasan di RnD
        assert _lolos("pic_toko", path), path


def test_portal_yang_tidak_diberikan_tetap_ditolak(akun):
    akun(portals=["toko", "self", "collaboration", "rnd", "cutting"])
    assert not _lolos("pic_toko", "/api/rahaza/payslips/export")      # SDM (pintasan Keuangan)
    assert not _lolos("pic_toko", "/api/hr/expenses/claims")           # SDM (pintasan Keuangan)
    assert not _lolos("pic_toko", "/api/belum-ada-di-katalog")         # di luar katalog


def test_bawaan_kode_tidak_dihitung_hanya_pemberian_owner(akun):
    # Belum dicentang apa pun → bawaan kode (Toko + Penjualan) TIDAK membuka larangan tetap.
    akun(portals=[])
    assert not _lolos("pic_toko", "/api/cutting/orders")
    # Portal per orang dan izin Lihat per modul = pemberian owner.
    akun(portals=["toko"], extra=["cutting"])
    assert _lolos("pic_toko", "/api/cutting/orders")
    akun(portals=["toko"], extra=[], perms=["mod.cut_orders.view"])
    assert _lolos("pic_toko", "/api/cutting/orders")
    # Portal Saya / Kolaborasi tidak pernah dihitung sebagai pemberian.
    akun(portals=["self", "collaboration"], extra=[], perms=[])
    assert not _lolos("pic_toko", "/api/cutting/orders")


def test_akun_nonaktif_atau_peran_eksternal_tidak_ikut(akun):
    akun(portals=["cutting"], blocked=True)
    assert not _lolos("pic_toko", "/api/cutting/orders")
    akun(role="cmt_vendor", portals=["cutting"], blocked=False)
    assert not _lolos("cmt_vendor", "/api/cutting/orders")


def test_peran_lain_tidak_terpengaruh(akun):
    akun(role="spv_cuting")
    assert _lolos("spv_cuting", "/api/cutting/orders")      # bukan peran yang dilarang
