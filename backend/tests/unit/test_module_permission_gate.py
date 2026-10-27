"""Uji unit HERMETIK gerbang izin modul (middleware.module_permission_gate) — tanpa server, tanpa Mongo.

Regresi 2026-10-26: peran yang daftar portalnya diatur TANPA SDM/Keuangan (accounting, admin_gudang,
tim_packing, rnd_staff, …) ditolak 403 saat swalayan Portal Saya (cuti, lembur, absen, kasbon, slip) dan
saat layar pintasan lintas-portal menulis (penyelesaian dinas di Keuangan, Master Produk di RnD).

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import middleware.module_permission_gate as gate  # noqa: E402
from data.module_catalog import is_self_service  # noqa: E402

# `roles.portals` peran nyata di seed go-live (seed/DA_SEED_GOLIVE.archive.gz).
ROLE_PORTALS = {
    "accounting": ["finance", "assets", "self", "collaboration", "toko"],
    "admin_gudang": ["cutting", "warehouse", "accessories", "collaboration", "self"],
    "tim_packing": ["production", "self", "maklon", "collaboration"],
    "rnd_staff": ["rnd", "self", "collaboration"],
}

SELF_SERVICE_CALLS = [
    ("POST", "/api/rahaza/leaves/request"),
    ("POST", "/api/rahaza/leaves/upload-document"),
    ("POST", "/api/rahaza/leaves/lv-1/cancel"),
    ("POST", "/api/rahaza/overtime"),
    ("POST", "/api/rahaza/attendance/selfie/clock-in"),
    ("POST", "/api/rahaza/attendance/selfie/clock-out"),
    ("POST", "/api/rahaza/attendance/sessions/start"),
    ("POST", "/api/rahaza/attendance/sessions/end"),
    ("POST", "/api/rahaza/attendance/permits/ses-1/cancel"),
    ("GET", "/api/rahaza/payslips/ps-1/pdf"),
    ("POST", "/api/dewi/kasbon/requests"),
]


@pytest.fixture
def as_role(monkeypatch):
    """Login palsu: peran + izin `mod.*` (opsional); portal peran dari ROLE_PORTALS."""
    state = {}

    async def live(uid):
        return {"id": uid, "role": state["role"]}

    async def rbac(role, uid):
        return list(state["perms"]), []

    async def portals(role, uid):
        return list(ROLE_PORTALS.get(role, []))

    monkeypatch.setattr(gate, "_load_live_user", live)
    monkeypatch.setattr(gate, "_load_rbac", rbac)
    monkeypatch.setattr(gate, "_load_portals", portals)

    def _login(role, perms=()):
        state.update(role=role, perms=perms)
        return {"id": f"u-{role}", "role": role}
    return _login


def _denied(method, path, payload):
    return asyncio.run(gate.evaluate(method, path, payload))


@pytest.mark.parametrize("role", sorted(ROLE_PORTALS))
@pytest.mark.parametrize("method,path", SELF_SERVICE_CALLS)
def test_portal_saya_lolos_untuk_peran_tanpa_portal_sdm(as_role, role, method, path):
    assert _denied(method, path, as_role(role)) is None


def test_portal_saya_lolos_walau_portal_sdm_sudah_granular(as_role):
    # Peran diberi izin granular SDM tanpa `create` cuti → tetap boleh mengajukan cuti SENDIRI.
    payload = as_role("accounting", perms=["mod.hr_leave.view"])
    assert _denied("POST", "/api/rahaza/leaves/request", payload) is None
    assert _denied("POST", "/api/rahaza/overtime", payload) is None


@pytest.mark.parametrize("role,method,path", [
    ("accounting", "POST", "/api/rahaza/leaves/lv-1/approve"),
    ("accounting", "DELETE", "/api/rahaza/overtime"),
    ("accounting", "POST", "/api/rahaza/leaves/request/extra"),
    ("admin_gudang", "POST", "/api/dewi/kasbon/requests/kb-1/hr-review"),
    ("tim_packing", "GET", "/api/rahaza/payslips/export"),
])
def test_aksi_sdm_keuangan_bukan_swalayan_tetap_ditolak(as_role, role, method, path):
    denied = _denied(method, path, as_role(role))
    assert denied is not None and denied[2] == "portal"


@pytest.mark.parametrize("role,method,path", [
    # Keuangan → Penyelesaian Perjalanan Dinas, persetujuan/pencairan klaim
    ("accounting", "POST", "/api/hr/expenses/settlements/bulk-approve"),
    ("accounting", "POST", "/api/hr/expenses/settlements/bulk-post"),
    ("accounting", "GET", "/api/hr/expenses/settlements/export"),
    ("accounting", "POST", "/api/hr/expenses/claims/bulk-approve"),
    ("accounting", "POST", "/api/hr/expenses/claims/cl-1/disburse"),
    # RnD → Master Produk (model, SOP, varian, material baru)
    ("rnd_staff", "PUT", "/api/rahaza/models/m-1/sop"),
    ("rnd_staff", "POST", "/api/rahaza/models/m-1/variants/generate"),
    ("rnd_staff", "POST", "/api/rahaza/materials"),
    # Produksi → BOM di Master Produk
    ("tim_packing", "POST", "/api/rahaza/boms"),
])
def test_layar_pintasan_lintas_portal_boleh_menulis(as_role, role, method, path):
    assert _denied(method, path, as_role(role)) is None


@pytest.mark.parametrize("role,method,path", [
    ("accounting", "PUT", "/api/rahaza/models/m-1/sop"),
    ("rnd_staff", "POST", "/api/hr/expenses/claims/bulk-approve"),
    ("admin_gudang", "POST", "/api/hr/expenses/settlements/bulk-post"),
])
def test_portal_yang_tidak_menampilkan_layarnya_tetap_ditolak(as_role, role, method, path):
    denied = _denied(method, path, as_role(role))
    assert denied is not None and denied[2] == "portal"


def test_is_self_service_cocok_persis_method_dan_path():
    assert is_self_service("post", "/api/rahaza/leaves/request")
    assert is_self_service("GET", "/api/rahaza/payslips/ps-1/pdf/")
    assert not is_self_service("GET", "/api/rahaza/leaves/request")
    assert not is_self_service("POST", "/api/rahaza/leaves/lv-1/approve")
    assert not is_self_service("POST", "/api/rahaza/payslips/ps-1/pdf")
    assert not is_self_service("POST", "/api/dewi/kasbon/requests/kb-1/hr-review")
