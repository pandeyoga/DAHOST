"""Uji unit HERMETIK akses slip gaji (P1, 2026-11-02) — tanpa server, tanpa Mongo.

Regresi audit T3 / No.57:
  · GET /api/rahaza/payslips & /payslips/{pid} dulu hanya `require_auth` → akun tim_packing membaca
    50 slip milik 25 karyawan. Kini: HR/keuangan/manajemen/super → semua; selain itu hanya slip
    miliknya dari run final/dibayar, atau 403.
  · Portal Saya (/api/portal/payslips & /api/portal/dashboard) dulu menampilkan slip run DRAFT.

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

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

import auth  # noqa: E402
import utils.employee_identity as employee_identity  # noqa: E402
import routes.rahaza_payroll_payslips as payslips  # noqa: E402
import routes.dewi_portal_saya_ext as portal_ext  # noqa: E402
import routes.rahaza_self as rahaza_self  # noqa: E402

try:
    import routes.dewi_portal_saya_hr as portal_hr  # noqa: E402
except RuntimeError:
    # Job CI unit tidak memasang python-multipart; rute unggah foto (UploadFile) di modul ini
    # memeriksanya saat impor. Rute itu tidak diuji di sini → lewati pemeriksaan saat impor saja.
    import fastapi.dependencies.utils as _fdu
    _checks = {n: getattr(_fdu, n) for n in ("check_file_field", "ensure_multipart_is_installed") if hasattr(_fdu, n)}
    for _n in _checks:
        setattr(_fdu, _n, lambda *a, **k: None)
    try:
        import routes.dewi_portal_saya_hr as portal_hr  # noqa: E402
    finally:
        for _n, _fn in _checks.items():
            setattr(_fdu, _n, _fn)


# ── DB palsu minimal (find/find_one/sort/to_list; operator $in/$ne) ───────────
def _match(doc, q):
    for k, v in q.items():
        val = doc.get(k)
        if isinstance(v, dict):
            if "$in" in v and val not in v["$in"]:
                return False
            if "$ne" in v and val == v["$ne"]:
                return False
        elif val != v:
            return False
    return True


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction=1):
        self.rows = sorted(self.rows, key=lambda r: r.get(key) or "", reverse=direction == -1)
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    async def to_list(self, n):
        return [dict(r) for r in self.rows[:n]]


class _Coll:
    def __init__(self, rows):
        self.rows = rows

    def find(self, q=None, proj=None):
        return _Cursor([r for r in self.rows if _match(r, q or {})])

    async def find_one(self, q=None, proj=None, sort=None):
        rows = [r for r in self.rows if _match(r, q or {})]
        if sort:
            key, direction = sort[0]
            rows = sorted(rows, key=lambda r: r.get(key) or "", reverse=direction == -1)
        return dict(rows[0]) if rows else None

    async def count_documents(self, q=None):
        return len([r for r in self.rows if _match(r, q or {})])


class _DB:
    def __init__(self, **colls):
        for name, rows in colls.items():
            setattr(self, name, _Coll(rows))

    def __getattr__(self, name):  # koleksi lain → kosong
        return _Coll([])


RUNS = [
    {"id": "run-sep", "status": "finalized"},
    {"id": "run-okt", "status": "draft"},
    {"id": "run-batal", "status": "cancelled"},
]
SLIPS = [
    {"id": "s-totti-sep", "run_id": "run-sep", "employee_id": "e-totti", "employee_code": "E01", "period_from": "2026-09-01", "net_pay": 100, "created_at": "2026-10-01"},
    {"id": "s-totti-okt", "run_id": "run-okt", "employee_id": "e-totti", "employee_code": "E01", "period_from": "2026-10-01", "net_pay": 999, "created_at": "2026-11-01"},
    {"id": "s-totti-batal", "run_id": "run-batal", "employee_id": "e-totti", "employee_code": "E01", "period_from": "2026-08-01", "net_pay": 5, "created_at": "2026-09-01"},
    {"id": "s-tutut-sep", "run_id": "run-sep", "employee_id": "e-tutut", "employee_code": "E02", "period_from": "2026-09-01", "net_pay": 200},
    {"id": "s-tutut-okt", "run_id": "run-okt", "employee_id": "e-tutut", "employee_code": "E02", "period_from": "2026-10-01", "net_pay": 300},
]
EMPLOYEES = {"u-tim_packing": {"id": "e-totti", "employee_code": "E01", "name": "Totti"}}

# `roles.portals` peran nyata di seed go-live (sama dengan test_module_permission_gate.py).
ROLE_PORTALS = {
    "accounting": ["finance", "assets", "self", "collaboration", "toko"],
    "tim_packing": ["production", "self", "maklon", "collaboration"],
    "admin_gudang": ["cutting", "warehouse", "accessories", "collaboration", "self"],
}


@pytest.fixture
def env(monkeypatch):
    """Login palsu lewat `auth.require_auth` asli (JWT + loader dipalsukan) + DB palsu."""
    db = _DB(rahaza_payslips=SLIPS, rahaza_payroll_runs=RUNS)
    state = {}

    async def live(uid):
        return {"id": uid, "role": state["role"]}

    async def rbac(role, uid):
        return [], []

    async def portals(role, uid):
        return list(ROLE_PORTALS.get(role, [])), []

    async def resolve(_db, user):
        return EMPLOYEES.get(user.get("id"))

    async def linked(_db, uid):
        return {"id": uid}, EMPLOYEES.get(uid)

    monkeypatch.setattr(auth, "_load_live_user", live)
    monkeypatch.setattr(auth, "_load_rbac", rbac)
    monkeypatch.setattr(auth, "_load_portal_config", portals)
    monkeypatch.setattr(employee_identity, "resolve_my_employee", resolve)
    monkeypatch.setattr(payslips, "get_db", lambda: db)
    monkeypatch.setattr(portal_hr, "get_db", lambda: db)
    monkeypatch.setattr(portal_hr, "_get_linked_employee", linked)
    monkeypatch.setattr(portal_ext, "get_db", lambda: db)
    monkeypatch.setattr(rahaza_self, "get_db", lambda: db)
    monkeypatch.setattr(rahaza_self, "_get_employee_for_user", linked)

    def _req(role):
        state["role"] = role
        tok = auth.create_token({"id": f"u-{role}", "email": f"{role}@x.test", "role": role, "name": role})
        return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"",
                        "headers": [(b"authorization", f"Bearer {tok}".encode())]})
    return _req


def _run(coro):
    return asyncio.run(coro)


def _status(coro):
    try:
        _run(coro)
        return 200
    except HTTPException as e:
        return e.status_code


# ── Butir 1: daftar & detail slip ────────────────────────────────────────────
# 2026-11-09 (Q8, keputusan owner): slip SEMUA karyawan hanya peran penggajian (aturan `_require_hr`); Keuangan,
# HR Manager/Staf HR, dan manajer produksi tidak lagi lolos lewat portal (Keuangan: total & nilai transfer di run).
@pytest.mark.parametrize("role", ["superadmin", "owner", "hr", "manager", "admin"])
def test_peran_penggajian_melihat_semua_slip(env, role):
    rows = _run(payslips.list_payslips(env(role)))
    assert len(rows) == len(SLIPS)
    assert _run(payslips.get_payslip("s-tutut-okt", env(role)))["id"] == "s-tutut-okt"


@pytest.mark.parametrize("role", ["accounting", "staff_keuangan", "manager_keuangan", "hr_manager", "staff_hr",
                                  "manager_produksi"])
def test_keuangan_dan_staf_sdm_tidak_lagi_melihat_slip_orang_lain_q8(env, role):
    # akun tanpa karyawan tertaut → 403 (bukan daftar 19 slip seperti dulu)
    assert _status(payslips.list_payslips(env(role))) == 403
    assert _status(payslips.get_payslip("s-tutut-okt", env(role))) == 403


def test_karyawan_biasa_hanya_slip_sendiri_dari_run_final(env):
    rows = _run(payslips.list_payslips(env("tim_packing")))
    assert [r["id"] for r in rows] == ["s-totti-sep"]  # draft & cancelled tidak tampil


def test_karyawan_biasa_ditolak_membaca_slip_orang_lain(env):
    assert _status(payslips.get_payslip("s-tutut-sep", env("tim_packing"))) == 403
    assert _status(payslips.list_payslips(env("tim_packing"), employee_id="e-tutut")) == 403
    assert _status(payslips.list_payslips(env("tim_packing"), employee_code="E02")) == 403


def test_karyawan_biasa_detail_slip_sendiri(env):
    assert _run(payslips.get_payslip("s-totti-sep", env("tim_packing")))["net_pay"] == 100
    assert _status(payslips.get_payslip("s-totti-okt", env("tim_packing"))) == 404  # run draft


def test_akun_tanpa_karyawan_tertaut_403(env):
    assert _status(payslips.list_payslips(env("admin_gudang"))) == 403
    assert _status(payslips.get_payslip("s-totti-sep", env("admin_gudang"))) == 403


def test_slip_tidak_ada_tetap_404_untuk_hr(env):
    assert _status(payslips.get_payslip("tidak-ada", env("hr"))) == 404


def test_pdf_swalayan_aturan_sama_dengan_daftar_slip():
    # 2026-11-02 (P6 butir 8): PDF slip memakai gerbang yang SAMA dengan GET /payslips — dulu daftar
    # peran sendiri, dan slip run DRAFT tetap bisa diunduh karyawan.
    import inspect
    src = inspect.getsource(payslips.export_payslip_pdf)
    assert "_can_view_all_payslips(request, user)" in src and "only_published_slips(db, [slip])" in src
    assert set(payslips._PAYSLIP_ALL_ROLES) == {"superadmin", "admin", "owner", "hr", "manager"}


@pytest.fixture
def pdf_stub(monkeypatch):
    import io

    async def _none(*a, **k):
        return {}
    monkeypatch.setattr(payslips, "_build_payslip_pdf", lambda *a, **k: io.BytesIO(b"%PDF-uji"))
    monkeypatch.setattr(payslips, "get_company_profile", _none)
    monkeypatch.setattr(payslips, "get_doc_settings", _none)


def test_pdf_slip_sendiri_run_draft_404_untuk_karyawan(env, pdf_stub):
    assert _status(payslips.export_payslip_pdf("s-totti-okt", env("tim_packing"))) == 404   # run draft
    assert _status(payslips.export_payslip_pdf("s-totti-batal", env("tim_packing"))) == 404  # run batal
    assert _status(payslips.export_payslip_pdf("s-totti-sep", env("tim_packing"))) == 200    # run final
    assert _status(payslips.export_payslip_pdf("s-tutut-sep", env("tim_packing"))) == 403    # milik orang lain


@pytest.mark.parametrize("role", ["hr", "owner", "manager"])
def test_pdf_slip_draft_tetap_bisa_untuk_peran_penggajian(env, pdf_stub, role):
    assert _status(payslips.export_payslip_pdf("s-totti-okt", env(role))) == 200


@pytest.mark.parametrize("role", ["accounting", "staff_keuangan", "hr_manager"])
def test_pdf_slip_orang_lain_ditolak_untuk_keuangan_q8(env, pdf_stub, role):
    assert _status(payslips.export_payslip_pdf("s-totti-okt", env(role))) == 403


# ── Butir 2: Portal Saya hanya slip run final/dibayar ────────────────────────
def test_only_published_slips_status_final_dan_dibayar():
    db = _DB(rahaza_payroll_runs=[{"id": "a", "status": "finalized"}, {"id": "b", "status": "paid"},
                                  {"id": "c", "status": "draft"}, {"id": "d", "status": "cancelled"}])
    slips = [{"id": x, "run_id": x} for x in "abcd"] + [{"id": "tanpa-run"}]
    assert [s["id"] for s in _run(payslips.only_published_slips(db, slips))] == ["a", "b"]


def test_portal_saya_daftar_slip_tanpa_draft(env):
    out = _run(portal_hr.my_payslips(env("tim_packing")))
    assert [s["id"] for s in out["items"]] == ["s-totti-sep"]


def test_portal_saya_dashboard_slip_terakhir_bukan_draft(env):
    out = _run(portal_hr.get_dashboard(env("tim_packing")))
    assert out["last_payslip"] == {"period": "2026-09", "net_pay": 100, "gross_pay": 0}


# ── Lanjutan: jalur swalayan lain + PDF bundel run ───────────────────────────
def test_portal_saya_me_payslips_tanpa_draft(env):
    # Endpoint yang benar-benar dipakai layar slip Portal Saya (PortalSayaPayslip.jsx).
    out = _run(portal_ext.get_my_payslips(env("tim_packing"), limit=12))
    assert [s["id"] for s in out["payslips"]] == ["s-totti-sep"] and out["total"] == 1


def test_portal_saya_me_payslips_limit_berlaku_setelah_disaring(env):
    out = _run(portal_ext.get_my_payslips(env("tim_packing"), limit=1))
    assert [s["id"] for s in out["payslips"]] == ["s-totti-sep"]


def test_self_service_payslips_tanpa_draft(env):
    out = _run(rahaza_self.self_payslips(env("tim_packing"), from_=None, to=None))
    assert [s["id"] for s in out["slips"]] == ["s-totti-sep"] and out["total_slips"] == 1
    assert out["slips"][0]["run_status"] == "finalized"


def test_self_service_detail_slip_draft_404(env):
    assert _run(rahaza_self.self_payslip_detail("s-totti-sep", env("tim_packing")))["net_pay"] == 100
    assert _status(rahaza_self.self_payslip_detail("s-totti-okt", env("tim_packing"))) == 404
    assert _status(rahaza_self.self_payslip_detail("s-tutut-sep", env("tim_packing"))) == 404  # milik orang lain


@pytest.mark.parametrize("role", ["tim_packing", "operator", "admin_gudang", "cs_staff"])
def test_pdf_bundel_run_ditolak_untuk_karyawan_biasa(env, role):
    assert _status(payslips.export_run_pdf("run-sep", env(role))) == 403


@pytest.mark.parametrize("role", ["superadmin", "hr", "manager", "owner"])
def test_pdf_bundel_run_lolos_gerbang_untuk_peran_penggajian(env, role):
    # Run tidak ada → 404 SETELAH gerbang (membuktikan gerbang tidak menolak peran ini).
    assert _status(payslips.export_run_pdf("run-tidak-ada", env(role))) == 404


@pytest.mark.parametrize("role", ["accounting", "hr_manager", "manager_produksi"])
def test_pdf_bundel_run_ditolak_untuk_keuangan_dan_staf_sdm_q8(env, role):
    assert _status(payslips.export_run_pdf("run-tidak-ada", env(role))) == 403
