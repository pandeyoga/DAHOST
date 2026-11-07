"""Uji unit HERMETIK penjaga router di server.py (P1, 2026-11-02) — tanpa Mongo, tanpa impor server.

Regresi audit No.57:
  · dashboard_router, rahaza_reports_router, dewi_phase7_reports_router tanpa penjaga peran eksternal
    → vendor CMT membaca piutang per pelanggan & ringkasan payroll.
  · HR AI, AI Business, dan /api/dashboard (Dashboard Eksekutif) terbuka untuk SEMUA peran internal.

`server.py` mengimpor seluruh router (butuh paket yang tidak dipasang job CI unit), jadi uji ini
membaca `app.include_router(<router>, dependencies=...)` APA ADANYA dari server.py lewat AST, lalu
menjalankan dependency itu (fungsi asli core.authz / routes.shared) dengan `auth.require_auth` asli
dan loader DB yang dipalsukan.

Jalankan:  cd /app/backend && python -m pytest tests/unit -n 0 -q
"""
import ast
import asyncio
import os
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

import auth  # noqa: E402

with open(os.path.join(BACKEND, "server.py"), encoding="utf-8") as _f:
    _TREE = ast.parse(_f.read())

# Nama di server.py yang dipakai ekspresi `dependencies=` router-router di bawah.
_GUARD_NAMES = {"_DENY_EXTERNAL", "_DENY_EXTERNAL_AND_MKT", "_DENY_MKT", "_on_paths", "_DASHBOARD_GUARD",
                "_REPORTS_GUARD", "_PAYSLIPS_GUARD", "_KASBON_GUARD"}
_IMPORT_MODULES = {"fastapi", "core.authz", "routes.shared"}


def _namespace():
    ns = {}
    for node in _TREE.body:
        if isinstance(node, ast.ImportFrom) and node.module in _IMPORT_MODULES:
            pass
        elif isinstance(node, ast.FunctionDef) and node.name in _GUARD_NAMES:
            pass
        elif isinstance(node, ast.Assign) and {getattr(t, "id", None) for t in node.targets} & _GUARD_NAMES:
            pass
        else:
            continue
        exec(compile(ast.Module(body=[node], type_ignores=[]), "server.py", "exec"), ns)
    return ns


_NS = _namespace()


def _include_calls(router_name):
    out = []
    for node in ast.walk(_TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "app" and node.args and isinstance(node.args[0], ast.Name)
                and node.args[0].id == router_name):
            out.append(node)
    return out


def _router_deps(router_name):
    calls = _include_calls(router_name)
    assert len(calls) == 1, f"{router_name} harus dipasang tepat sekali (ketemu {len(calls)})"
    expr = {k.arg: k.value for k in calls[0].keywords}.get("dependencies")
    if expr is None:
        return []
    return [d.dependency for d in eval(compile(ast.Expression(expr), "server.py", "eval"), _NS)]


# path template route → nama router di server.py
ROUTER_OF = {
    "/api/dashboard": "dashboard_router",
    "/api/dashboard/analytics": "dashboard_router",
    "/api/vendor/dashboard": "dashboard_router",
    "/api/global-search": "dashboard_router",
    "/api/attachments": "dashboard_router",
    "/api/rahaza/management/overview": "rahaza_reports_router",
    "/api/rahaza/management/payroll-summary": "rahaza_reports_router",
    "/api/rahaza/reports/{report_type}": "rahaza_reports_router",
    "/api/rahaza/reports-hub/summary": "rahaza_reports_router",
    "/api/dewi/reports/daily": "dewi_phase7_reports_router",
    "/api/dewi/reports/monthly": "dewi_phase7_reports_router",
    "/api/hr/ai/employees/list": "dewi_hr_ai_router",
    "/api/hr/ai/attrition/dashboard": "dewi_hr_ai_router",
    "/api/hr/ai/coaching/history": "dewi_hr_ai_router",
    "/api/hr/ai/resume-screen/history": "dewi_hr_ai_router",
    "/api/hr/ai/coaching/{employee_id}": "dewi_hr_ai_router",
    "/api/ai-business/daily-summary/history": "dewi_ai_business_router",
    "/api/reports/executive/summary": "executive_report_router",
    "/api/rahaza/payslips": "rahaza_payroll_payslips_router",
    "/api/rahaza/payslips/{pid}": "rahaza_payroll_payslips_router",
    "/api/rahaza/payslips/{pid}/pdf": "rahaza_payroll_payslips_router",
    "/api/rahaza/payroll-runs/{run_id}/pdf": "rahaza_payroll_payslips_router",
    # Tahap 7 (2026-11-07): kasbon milik sendiri juga untuk peran marketing
    "/api/dewi/kasbon/requests": "dewi_kasbon_router",
    "/api/dewi/kasbon/my-requests": "dewi_kasbon_router",
    "/api/dewi/kasbon/requests/{req_id}": "dewi_kasbon_router",
    "/api/dewi/kasbon/stats": "dewi_kasbon_router",
    "/api/dewi/kasbon/employee/{emp_id}/deductions": "dewi_kasbon_router",
}

# `roles.portals` peran nyata di seed go-live; peran lain memakai PORTAL_ACCESS bawaan.
ROLE_PORTALS = {
    "hr": ["sysadmin", "production", "cutting", "procurement", "warehouse", "accessories", "finance", "hr",
           "rnd", "self", "maklon", "toko", "collaboration", "sales", "assets"],
    "accounting": ["finance", "assets", "self", "collaboration", "toko"],
    "tim_packing": ["production", "self", "maklon", "collaboration"],
    "pic_toko": ["toko", "self", "collaboration", "rnd"],
    "rnd_staff": ["rnd", "self", "collaboration"],
}


class _Route:
    def __init__(self, path):
        self.path = path


@pytest.fixture
def call(monkeypatch):
    state = {}

    async def live(uid):
        return {"id": uid, "role": state["role"]}

    async def rbac(role, uid):
        return [], []

    async def portals(role, uid):
        return list(ROLE_PORTALS.get(role, []))

    monkeypatch.setattr(auth, "_load_live_user", live)
    monkeypatch.setattr(auth, "_load_rbac", rbac)
    monkeypatch.setattr(auth, "_load_portals", portals)

    def _call(role, path, method="GET"):
        """Status dari dependency router: 200 = lolos semua penjaga, selain itu kode HTTPException."""
        deps = _router_deps(ROUTER_OF[path])
        state["role"] = role
        tok = auth.create_token({"id": f"u-{role}", "email": f"{role}@x.test", "role": role, "name": role})
        req = Request({"type": "http", "method": method, "path": path, "query_string": b"",
                       "route": _Route(path), "headers": [(b"authorization", f"Bearer {tok}".encode())]})

        async def _run():
            for dep in deps:
                await dep(req)
        try:
            asyncio.run(_run())
            return 200
        except HTTPException as e:
            return e.status_code
    return _call


# ── Butir 3: tolak peran eksternal pada tiga router ──────────────────────────
EXTERNAL_BLOCKED = [
    "/api/dashboard", "/api/dashboard/analytics", "/api/global-search", "/api/attachments",
    "/api/rahaza/management/overview", "/api/rahaza/management/payroll-summary",
    "/api/rahaza/reports/{report_type}", "/api/rahaza/reports-hub/summary",
    "/api/dewi/reports/daily", "/api/dewi/reports/monthly",
]


@pytest.mark.parametrize("role", ["cmt_vendor", "vendor", "buyer", "klien_maklon"])
@pytest.mark.parametrize("path", EXTERNAL_BLOCKED)
def test_peran_eksternal_ditolak_di_router_laporan_dan_dashboard(call, role, path):
    assert call(role, path) == 403


@pytest.mark.parametrize("role", ["cmt_vendor", "tim_packing", "superadmin"])
def test_dashboard_vendor_cmt_tidak_ikut_digerbang(call, role):
    # Portal vendor CMT (VendorDashboard.jsx) SAH memakai endpoint ini; handler menjaga dirinya sendiri.
    assert call(role, "/api/vendor/dashboard") == 200


@pytest.mark.parametrize("role", ["tim_packing", "operator", "admin_produksi", "accounting", "cs_staff", "rnd_staff"])
@pytest.mark.parametrize("path", ["/api/rahaza/management/overview", "/api/rahaza/reports/{report_type}",
                                  "/api/rahaza/reports-hub/summary", "/api/dewi/reports/daily",
                                  "/api/dashboard/analytics", "/api/global-search"])
def test_peran_internal_tetap_lolos_router_laporan(call, role, path):
    assert call(role, path) == 200


# ── Butir 4: data sensitif hanya untuk portal pemiliknya ─────────────────────
MGMT_ONLY = ["/api/dashboard", "/api/ai-business/daily-summary/history"]
HR_ONLY = ["/api/hr/ai/employees/list", "/api/hr/ai/attrition/dashboard", "/api/hr/ai/coaching/history",
           "/api/hr/ai/resume-screen/history"]


@pytest.mark.parametrize("role", ["superadmin", "admin", "owner", "hr_manager", "manager_produksi",
                                  "manager_keuangan", "manager_hr", "manager_marketing"])
@pytest.mark.parametrize("path", MGMT_ONLY)
def test_portal_manajemen_lolos(call, role, path):
    assert call(role, path) == 200


@pytest.mark.parametrize("role", ["hr", "accounting", "staff_keuangan", "tim_packing", "operator", "admin_produksi",
                                  "rnd_staff"])
@pytest.mark.parametrize("path", MGMT_ONLY)
def test_bukan_portal_manajemen_ditolak(call, role, path):
    assert call(role, path) == 403


@pytest.mark.parametrize("role", ["superadmin", "admin", "owner", "hr", "hr_manager", "staff_hr"])
@pytest.mark.parametrize("path", HR_ONLY)
def test_portal_sdm_lolos_hr_ai(call, role, path):
    assert call(role, path) == 200


@pytest.mark.parametrize("role", ["accounting", "staff_keuangan", "manager_produksi", "tim_packing", "operator",
                                  "cs_staff", "pic_toko", "rnd_staff", "cmt_vendor"])
@pytest.mark.parametrize("path", HR_ONLY)
def test_bukan_portal_sdm_ditolak_hr_ai(call, role, path):
    assert call(role, path) == 403


@pytest.mark.parametrize("role", ["operator", "cs_staff"])
def test_aksi_tulis_coaching_hr_ai_ditolak_tanpa_portal_sdm(call, role):
    # Audit: POST coaching oleh operator/cs_staff lolos semua penjaga (berhenti di 500 kunci LLM).
    assert call(role, "/api/hr/ai/coaching/{employee_id}", method="POST") == 403


@pytest.mark.parametrize("role", ["accounting", "tim_packing"])
def test_laporan_eksekutif_belum_diubah_menunggu_owner(call, role):
    # Layar "Laporan Eksekutif" ada di Portal Keuangan (portalNav finance) → tidak dibatasi
    # ke Portal Manajemen tanpa keputusan owner. Hanya penjaga eksternal lama yang berlaku.
    assert call(role, "/api/reports/executive/summary") == 200
    assert call("cmt_vendor", "/api/reports/executive/summary") == 403


# ── Lanjutan: ringkasan payroll manajemen & PDF slip sendiri peran marketing ──
@pytest.mark.parametrize("role", ["superadmin", "owner", "hr", "hr_manager", "staff_hr", "manager_produksi",
                                  "accounting", "staff_keuangan", "manager_keuangan"])
def test_payroll_summary_untuk_portal_manajemen_sdm_keuangan(call, role):
    assert call(role, "/api/rahaza/management/payroll-summary") == 200


@pytest.mark.parametrize("role", ["tim_packing", "operator", "admin_produksi", "rnd_staff", "cs_staff", "pic_toko",
                                  "cmt_vendor"])
def test_payroll_summary_ditolak_untuk_peran_lain(call, role):
    assert call(role, "/api/rahaza/management/payroll-summary") == 403


@pytest.mark.parametrize("role", ["cs_staff", "pic_toko", "marketing_kol"])
def test_peran_marketing_boleh_jalur_pdf_slip_sendiri(call, role):
    # Kepemilikan slip diperiksa handler export_payslip_pdf (bukan oleh penjaga router).
    assert call(role, "/api/rahaza/payslips/{pid}/pdf") == 200


@pytest.mark.parametrize("role", ["cs_staff", "pic_toko", "marketing_kol"])
@pytest.mark.parametrize("path", ["/api/rahaza/payslips", "/api/rahaza/payslips/{pid}",
                                  "/api/rahaza/payroll-runs/{run_id}/pdf"])
def test_peran_marketing_tetap_ditolak_daftar_detail_bundel_slip(call, role, path):
    assert call(role, path) == 403


@pytest.mark.parametrize("path", ["/api/rahaza/payslips", "/api/rahaza/payslips/{pid}/pdf",
                                  "/api/rahaza/payroll-runs/{run_id}/pdf"])
def test_router_slip_tetap_menolak_eksternal(call, path):
    assert call("cmt_vendor", path) == 403


def test_on_paths_hanya_menjalankan_dependency_di_path_terpilih():
    hits = []

    async def dep(request):
        hits.append(request.scope["route"].path)

    only = _NS["_on_paths"](dep, only=("/a",))
    skip = _NS["_on_paths"](dep, skip=("/a",))
    for wrapped in (only, skip):
        for p in ("/a", "/b"):
            asyncio.run(wrapped(Request({"type": "http", "method": "GET", "path": p, "query_string": b"",
                                         "headers": [], "route": _Route(p)})))
    assert hits == ["/a", "/b"]


def test_dependency_terpasang_di_app_asli_bila_server_bisa_diimpor():
    """Pastikan FastAPI benar-benar menempelkan dependency include_router ke route (lingkungan lengkap)."""
    try:
        import server
    except Exception as e:  # job CI unit tidak memasang semua paket server
        pytest.skip(f"server tidak bisa diimpor di lingkungan ini: {type(e).__name__}")
    from fastapi.routing import APIRoute
    by_path = {(r.path, tuple(sorted(r.methods))): r for r in server.app.routes if isinstance(r, APIRoute)}
    for path, router_name in ROUTER_OF.items():
        method = "POST" if path == "/api/hr/ai/coaching/{employee_id}" else "GET"
        route = by_path[(path, (method,))]
        names = [getattr(d.dependency, "__name__", "") for d in route.dependencies]
        assert names == [getattr(d, "__name__", "") for d in _router_deps(router_name)], path


# ── Tahap 7 (keputusan owner 2026-11-07): Kasbon Portal Saya untuk peran marketing ─────────────
@pytest.mark.parametrize("role", ["pic_toko", "marketing_kol", "cs_staff"])
@pytest.mark.parametrize("path", ["/api/dewi/kasbon/requests", "/api/dewi/kasbon/my-requests",
                                  "/api/dewi/kasbon/requests/{req_id}"])
def test_kasbon_sendiri_lolos_untuk_peran_marketing(call, role, path):
    assert call(role, path) == 200


@pytest.mark.parametrize("role", ["pic_toko", "marketing_kol", "cs_staff"])
@pytest.mark.parametrize("path", ["/api/dewi/kasbon/stats", "/api/dewi/kasbon/employee/{emp_id}/deductions"])
def test_kasbon_selain_milik_sendiri_tetap_ditolak_untuk_peran_marketing(call, role, path):
    assert call(role, path) == 403


@pytest.mark.parametrize("role", ["cmt_vendor", "vendor", "buyer", "klien_maklon"])
def test_kasbon_tetap_ditolak_untuk_peran_eksternal(call, role):
    assert call(role, "/api/dewi/kasbon/my-requests") == 403
