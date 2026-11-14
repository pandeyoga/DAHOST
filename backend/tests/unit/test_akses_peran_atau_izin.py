"""Gerbang "kode peran ATAU izin" (keputusan owner, 8 Nov 2026).

Staf nyata memakai peran buatan owner di layar Peran & Hak Akses ("HR Generalist", "Accounting & Finance",
"Koordinator Packing", …). Izinnya tersimpan di `role_permissions` dan dibaca `auth.require_auth`
(`user["_permissions"]`), tetapi banyak gerbang hanya membandingkan KODE peran sehingga mereka 403 walau
izinnya benar. Setiap gerbang yang diubah diuji tiga hal:

  (a) kode peran lama tetap lolos;
  (b) peran buatan owner YANG punya izinnya lolos;
  (c) peran buatan owner TANPA izin itu tetap 403 (tidak ada pelebaran akses).

Ditambah: pemisahan tugas K25 (izin modul SDM tidak pernah membuka pencairan uang) dan gerbang DELETE
`only(*ROLES, perm=...)` di seluruh router yang dipasangi izin.
Hermetik: Mongo palsu, tanpa jaringan.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import re
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import auth  # noqa: E402
from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
from core import authz  # noqa: E402

PERAN_BUATAN = "HR Generalist"          # nama peran buatan owner (bukan kode peran)
IZIN_LAIN = "dashboard.view"            # izin yang tidak membuka gerbang mana pun di sini


def U(role, *perms, uid="u-uji"):
    return {"id": uid, "name": "Uji", "email": f"{uid}@contoh.test", "role": role,
            "_permissions": list(perms), "_role_perms": list(perms)}


def run(coro):
    return asyncio.run(coro)


def _lolos_sync(fn, user) -> bool:
    try:
        out = fn(user)
    except HTTPException as e:
        assert e.status_code == 403, e.detail
        return False
    return True if out is None else bool(out)


def _status(coro_factory):
    """403 → 'ditolak'; lainnya (berhasil, 400, 404, galat data uji kosong) → 'lolos' (gerbang sudah dilewati)."""
    try:
        run(coro_factory())
    except HTTPException as e:
        return "ditolak" if e.status_code == 403 else "lolos"
    except Exception:  # noqa: BLE001 — gerbang sudah dilewati; data uji sengaja kosong
        return "lolos"
    return "lolos"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 1. Mesin: auth.check_role (beberapa kunci) dan core.authz.require_roles(perm=)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_check_role_beberapa_kunci_salah_satu_cukup():
    roles = ("hr",)
    assert auth.check_role(U("hr"), roles, ("hr.manage", "salary.manage"))
    assert auth.check_role(U(PERAN_BUATAN, "salary.manage"), roles, ("hr.manage", "salary.manage"))
    assert auth.check_role(U(PERAN_BUATAN, "hr.manage"), roles, "hr.manage")
    assert not auth.check_role(U(PERAN_BUATAN, IZIN_LAIN), roles, ("hr.manage", "salary.manage"))
    assert not auth.check_role(U(PERAN_BUATAN), roles, None)
    assert auth.check_role(U("superadmin"), roles, None)
    assert auth.check_role(U("admin", "*"), roles, None)


class _ReqJWT:
    """Request dengan JWT asli (peran dibaca `core.authz._role_of`)."""

    def __init__(self, role, uid="u-uji"):
        tok = auth.create_token({"id": uid, "email": f"{uid}@contoh.test", "role": role, "name": "Uji"})
        self.headers = {"Authorization": f"Bearer {tok}"}
        self.query_params = {}

        class _S:
            pass
        self.state = _S()


def _pasang_auth(monkeypatch, user):
    async def _auth(_req):
        return user
    monkeypatch.setattr(authz._auth, "require_auth", _auth)


def test_require_roles_tanpa_perm_kode_peran_hanya_bila_belum_diatur(monkeypatch):
    """14 Nov 2026 (owner: centang = penentu): kode peran di daftar hanya berlaku selama owner belum mengatur centang
    peran itu (pola routes.shared.can_act); peran dibaca LIVE dari akun, bukan dari token."""
    dep = authz.require_roles("hr")
    _pasang_auth(monkeypatch, U("hr"))                         # belum diatur → kode peran lama
    run(dep(_ReqJWT("hr")))
    _pasang_auth(monkeypatch, U("hr", IZIN_LAIN))              # sudah diatur tanpa centang aksi ini → ditolak
    with pytest.raises(HTTPException) as e:
        run(dep(_ReqJWT("hr")))
    assert e.value.status_code == 403 and "Peran & Hak Akses" in e.value.detail
    _pasang_auth(monkeypatch, U(PERAN_BUATAN, "hr.manage"))
    with pytest.raises(HTTPException):
        run(dep(_ReqJWT(PERAN_BUATAN)))           # tanpa perm= izin lama tidak dibaca sama sekali


def test_require_roles_dengan_perm(monkeypatch):
    dep = authz.require_roles("hr", perm=("hr.attendance.manage", "hr.manage"))
    run(dep(_ReqJWT("hr")))                                        # (a)
    _pasang_auth(monkeypatch, U(PERAN_BUATAN, "hr.attendance.manage"))
    run(dep(_ReqJWT(PERAN_BUATAN)))                                # (b)
    _pasang_auth(monkeypatch, U(PERAN_BUATAN, IZIN_LAIN))
    with pytest.raises(HTTPException) as e:
        run(dep(_ReqJWT(PERAN_BUATAN)))                            # (c)
    assert e.value.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 2. Gerbang berupa fungsi (bool / raise 403)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _m(name):
    return importlib.import_module(name)


GERBANG_FUNGSI = [
    # (modul, pemanggil, kode peran lama, izin yang meloloskan peran buatan)
    ("routes.dewi_job_board", lambda m, u: m._require_job_board_hr(u, "x"), "hr", "hr.manage"),
    ("routes.dewi_job_board", lambda m, u: m._require_job_board_hr(u, "x"), "manager", "hr.manage"),
    ("routes.dewi_skill_gap", lambda m, u: m._require_skill_gap(u, ["superadmin", "hr", "manager"], "x"), "manager", "hr.manage"),
    ("routes.dewi_skill_gap", lambda m, u: m._require_skill_gap(u, ["superadmin", "hr"], "x"), "hr", "hr.manage"),
    ("routes.dewi_kpi_shared", lambda m, u: m.is_kpi_hr(u), "supervisor", "hr.manage"),
    ("routes.rahaza_overtime", lambda m, u: m.is_ot_approver(u), "manager", "hr.approve"),
    ("routes.rahaza_resignation", lambda m, u: m.is_resign_hr(u), "hr", "hr.employee.manage"),
    ("routes.rahaza_resignation", lambda m, u: m.is_resign_hr(u), "manager", "hr.manage"),
    ("routes.rahaza_salary_adjustments", lambda m, u: m.is_salary_hr(u), "hr", "salary.manage"),
    ("routes.rahaza_salary_adjustments", lambda m, u: m.is_salary_hr(u), "owner", "hr.manage"),
    ("routes.employee_per_diem", lambda m, u: m._admin_only(u), "hr", "fin.expense.manage"),
    ("routes.rahaza_auto_attendance_approvals", lambda m, u: m._require_attendance_approver(u), "hr", "hr.approve"),
    ("routes.rahaza_auto_attendance_zkteco", lambda m, u: m._require_fp(u), "hr", "hr.attendance.manage"),
    ("routes.employee_travel_requests", lambda m, u: m.can_view_all_travel(u), "manager", "hr.approve"),
    ("routes.employee_travel_requests", lambda m, u: m.can_view_all_travel(u), "hr", "fin.payment.manage"),
    ("routes.employee_travel_requests", lambda m, u: m.is_travel_approver(u), "accounting", "hr.approve"),
    ("routes.employee_travel_settlements", lambda m, u: m.can_view_all_settlements(u), "hr", "finance.approve"),
    ("routes.employee_travel_settlements", lambda m, u: m.is_settlement_approver(u), "manager", "finance.approve"),
    ("routes.employee_travel_settlements", lambda m, u: m.is_settlement_approver(u), "hr_manager", "hr.approve"),
    ("routes.employee_travel_settlements", lambda m, u: m.is_settlement_poster(u), "accounting", "finance.manage"),
    ("routes.employee_expense_claims", lambda m, u: m.can_view_all_claims(u), "hr", "finance.manage"),
    ("routes.employee_expense_claims", lambda m, u: m.is_claim_approver(u), "manager", "hr.approve"),
    ("routes.employee_expense_claims", lambda m, u: m.is_claim_payer(u), "staff_keuangan", "fin.payment.manage"),
    ("routes.employee_expense_gl_mapping", lambda m, u: m._is_gl_admin(u), "accounting", "finance.manage"),
    ("routes.employee_expense_category_master", lambda m, u: m._is_category_admin(u), "manager_keuangan", "finance.manage"),
    ("routes.rahaza_bank_transfers", lambda m, u: m._is_cash_officer(u), "accounting", "fin.cash.manage"),
    ("routes.rahaza_petty_cash", lambda m, u: m._is_finance(u), "staff_keuangan", "fin.cash.manage"),
    ("routes.rahaza_petty_cash", lambda m, u: m._is_cash_user(u), "cashier", "finance.manage"),
    ("routes.marketing_shared", lambda m, u: m._is_pic_role(u), "pic_toko", "toko.approve"),
    ("routes.marketing_shared", lambda m, u: m._is_pic_role(u), "manager_marketing", "toko.approve"),
    ("routes.dewi_okr", lambda m, u: m.can_write_objective(u), "manager", "management.manage"),
]


@pytest.mark.parametrize("modul,panggil,peran_lama,izin", GERBANG_FUNGSI,
                         ids=[f"{g[0].split('.')[-1]}-{g[2]}-{g[3]}" for g in GERBANG_FUNGSI])
def test_gerbang_fungsi_peran_atau_izin(modul, panggil, peran_lama, izin):
    m = _m(modul)
    assert _lolos_sync(lambda u: panggil(m, u), U(peran_lama)), "(a) kode peran lama harus tetap lolos"
    assert _lolos_sync(lambda u: panggil(m, u), U(PERAN_BUATAN, izin)), "(b) peran buatan + izin harus lolos"
    assert not _lolos_sync(lambda u: panggil(m, u), U(PERAN_BUATAN, IZIN_LAIN)), "(c) tanpa izin tetap 403"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3. Gerbang `async _require_*(request)`
# ══════════════════════════════════════════════════════════════════════════════════════════════════
GERBANG_REQUEST = [
    ("routes.dewi_kpi_shared", "_require_hr", "manager", "hr.manage"),
    ("routes.rahaza_leave_balances", "_require_admin", "manager", "hr.attendance.manage"),
    ("routes.rahaza_leave_balances", "_require_admin", "hr", "hr.manage"),
    ("routes.rahaza_overtime", "_require_approver", "hr", "hr.approve"),
    ("routes.rahaza_resignation", "_require_hr", "hr", "hr.employee.manage"),
    ("routes.rahaza_salary_grades", "_require_admin", "hr", "salary.manage"),
    ("routes.rahaza_alerts", "_require_admin", "manager_production", "production.manage"),
    ("routes.rahaza_sop", "_require_admin", "manager_production", "prod.master.manage"),
    ("routes.rahaza_styles", "_require_admin", "gudang", "rnd.manage"),
]


@pytest.mark.parametrize("modul,fungsi,peran_lama,izin", GERBANG_REQUEST,
                         ids=[f"{g[0].split('.')[-1]}.{g[1]}-{g[3]}" for g in GERBANG_REQUEST])
def test_gerbang_request_peran_atau_izin(monkeypatch, modul, fungsi, peran_lama, izin):
    m = _m(modul)

    def coba(user):
        async def _auth(_req):
            return user
        monkeypatch.setattr(m, "require_auth", _auth)
        return _status(lambda: getattr(m, fungsi)(FakeRequest()))

    assert coba(U(peran_lama)) == "lolos"
    assert coba(U(PERAN_BUATAN, izin)) == "lolos"
    assert coba(U(PERAN_BUATAN, IZIN_LAIN)) == "ditolak"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 4. Gerbang di dalam handler (dipanggil lewat fungsi route ASLI di atas Mongo palsu)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _handler(monkeypatch, m, user, db=None):
    async def _auth(_req):
        return user
    monkeypatch.setattr(m, "require_auth", _auth)
    monkeypatch.setattr(m, "get_db", lambda: db or FakeDB())
    req = FakeRequest()
    req.state.user = user
    return req


def _tiga(monkeypatch, modul, peran_lama, izin, panggil, db_factory=FakeDB):
    m = _m(modul)
    hasil = []
    for user in (U(peran_lama), U(PERAN_BUATAN, izin), U(PERAN_BUATAN, IZIN_LAIN)):
        req = _handler(monkeypatch, m, user, db_factory())
        hasil.append(_status(lambda: panggil(m, req, user)))
    assert hasil == ["lolos", "lolos", "ditolak"], hasil


def test_job_board_post_lowongan(monkeypatch):
    m = _m("routes.dewi_job_board")
    job = m.JobPosting(title="Staf SDM", department="SDM", location="Bandung", job_type="full-time", level="mid",
                       description="x", responsibilities=[], required_skills=[], deadline="2026-12-31")
    _tiga(monkeypatch, "routes.dewi_job_board", "hr", "hr.manage",
          lambda mm, req, u: mm.create_job_posting(req, job))


def test_job_board_kelola_lamaran(monkeypatch):
    _tiga(monkeypatch, "routes.dewi_job_board", "manager", "hr.manage",
          lambda mm, req, u: mm.update_application_status(req, "app-1", status="shortlisted"))
    _tiga(monkeypatch, "routes.dewi_job_board", "hr", "hr.manage",
          lambda mm, req, u: mm.list_applications(req, job_id=None, status=None, limit=10))


def test_skill_gap_kebutuhan_dan_analisis(monkeypatch):
    m = _m("routes.dewi_skill_gap")
    analisis = m.AnalysisRequest(level="department", target_id="SDM")
    _tiga(monkeypatch, "routes.dewi_skill_gap", "manager", "hr.manage",
          lambda mm, req, u: mm.analyze_department(req, analisis))
    _tiga(monkeypatch, "routes.dewi_skill_gap", "hr", "hr.manage",
          lambda mm, req, u: mm.analyze_company(req, analisis))


def test_kpi_daftar_goal_hr_melihat_semua(monkeypatch):
    m = _m("routes.dewi_kpi_reports")

    def db():
        d = FakeDB()
        d.da_kpi_goals.docs = [{"id": "g1", "employee_id": "e1", "created_at": 1},
                               {"id": "g2", "employee_id": "e2", "created_at": 2}]
        d.rahaza_employees.docs = [{"id": "e1", "user_id": "u-uji"}]
        return d

    jumlah = []
    for user in (U("hr"), U(PERAN_BUATAN, "hr.manage"), U(PERAN_BUATAN, IZIN_LAIN)):
        req = _handler(monkeypatch, m, user, db())
        jumlah.append(len(run(m.list_goals(req))["goals"]))
    assert jumlah == [2, 2, 1]          # tanpa izin: hanya goal miliknya sendiri


def test_kinerja_isi_penilaian_atas_nama_karyawan(monkeypatch):
    m = _m("routes.dewi_hris_performance")

    def db():
        d = FakeDB()
        d.dewi_perf_reviews.docs = [{"id": "r1", "employee_id": "e-lain", "manager_id": "e-atasan"}]
        return d
    payload = m.ReviewSubmitIn(actor="self", scores=[])
    hasil = []
    for user in (U("staff_hr"), U(PERAN_BUATAN, "hr.manage"), U(PERAN_BUATAN, IZIN_LAIN)):
        monkeypatch.setattr(m, "get_db", lambda d=db(): d)
        hasil.append(_status(lambda u=user: m.submit_review("r1", payload, u)))
    assert hasil == ["lolos", "lolos", "ditolak"], hasil


def test_360_tutup_siklus(monkeypatch):
    _tiga(monkeypatch, "routes.rahaza_360_feedback", "manager", "hr.manage",
          lambda mm, req, u: mm.close_cycle("c-1", req))


def test_lembur_daftar_dan_batal(monkeypatch):
    m = _m("routes.rahaza_overtime")

    def db():
        d = FakeDB()
        d.rahaza_overtime_requests.docs = [{"id": "ot1", "employee_id": "e-lain", "submitted_by": "u-lain",
                                            "status": "approved"}]
        return d
    _tiga(monkeypatch, "routes.rahaza_overtime", "hr", "hr.approve",
          lambda mm, req, u: mm.cancel_request("ot1", req), db_factory=db)
    jumlah = []
    for user in (U("manager"), U(PERAN_BUATAN, "hr.approve"), U(PERAN_BUATAN, IZIN_LAIN)):
        req = _handler(monkeypatch, m, user, db())
        out = run(m.list_overtime(req, status=None, employee_id=None, date_from=None, date_to=None, limit=50))
        jumlah.append(len(out.get("overtime") or []))
    assert jumlah == [1, 1, 0]


def test_penyesuaian_gaji_tolak_oleh_hr(monkeypatch):
    def db():
        d = FakeDB()
        d.rahaza_salary_adjustments.docs = [{"id": "adj1", "employee_id": "e-lain", "manager_id": "e-atasan",
                                             "status": "pending_hr"}]
        return d
    _tiga(monkeypatch, "routes.rahaza_salary_adjustments", "hr", "salary.manage",
          lambda mm, req, u: mm.reject_adjustment("adj1", req), db_factory=db)


def test_penyesuaian_gaji_lewati_atasan(monkeypatch):
    def db():
        d = FakeDB()
        d.rahaza_salary_adjustments.docs = [{"id": "adj1", "employee_id": "e-lain", "manager_id": "e-atasan",
                                             "status": "pending_manager"}]
        return d
    _tiga(monkeypatch, "routes.rahaza_salary_adjustments", "owner", "hr.manage",
          lambda mm, req, u: mm.approve_by_manager("adj1", req), db_factory=db)


def test_tautkan_akun_ke_karyawan(monkeypatch):
    _tiga(monkeypatch, "routes.rahaza_self", "hr", "hr.employee.manage",
          lambda mm, req, u: mm.admin_link_employee(req))


def test_lokasi_kantor_dan_konfigurasi_absen(monkeypatch):
    _tiga(monkeypatch, "routes.rahaza_attendance", "hr", "hr.attendance.manage",
          lambda mm, req, u: mm.set_office_location(req))
    _tiga(monkeypatch, "routes.rahaza_auto_attendance_config", "owner", "hr.attendance.manage",
          lambda mm, req, u: mm.update_auto_config(req))


def test_antrean_persetujuan_absen(monkeypatch):
    _tiga(monkeypatch, "routes.rahaza_auto_attendance_approvals", "hr", "hr.approve",
          lambda mm, req, u: mm.approve_attendance("ev-1", req))
    _tiga(monkeypatch, "routes.rahaza_auto_attendance_approvals", "admin", "hr.approve",
          lambda mm, req, u: mm.list_approval_queue(req, status="pending", from_date=None, to_date=None,
                                                    employee_id=None))


def test_biometrik_cabut_dan_daftar(monkeypatch):
    def db():
        d = FakeDB()
        d.rahaza_webauthn_credentials.docs = [{"id": "cr1", "employee_id": "e-lain", "user_id": "u-lain",
                                               "revoked_at": None}]
        d.rahaza_employees.docs = [{"id": "e-saya", "user_id": "u-uji"}]
        return d
    _tiga(monkeypatch, "routes.rahaza_auto_attendance_webauthn", "staff_hr", "hr.attendance.manage",
          lambda mm, req, u: mm.revoke_webauthn_device("cr1", req), db_factory=db)
    m = _m("routes.rahaza_auto_attendance_webauthn")
    jumlah = []
    for user in (U("hr"), U(PERAN_BUATAN, "hr.attendance.manage"), U(PERAN_BUATAN, IZIN_LAIN)):
        req = _handler(monkeypatch, m, user, db())
        out = run(m.list_webauthn_devices(req, employee_id=None))
        rows = out if isinstance(out, list) else (out.get("devices") or out.get("items") or out.get("data") or [])
        jumlah.append(len(rows))
    assert jumlah[0] == jumlah[1] == 1 and jumlah[2] == 0, jumlah


def test_retur_material_setujui_tolak(monkeypatch):
    m = _m("routes.production_material_returns")
    body = m.ActionModel(note="ok")
    _tiga(monkeypatch, "routes.production_material_returns", "manager", "inventory.approve",
          lambda mm, req, u: mm.approve_return(req, "ret-1", body))
    _tiga(monkeypatch, "routes.production_material_returns", "owner", "production.approve",
          lambda mm, req, u: mm.reject_return(req, "ret-1", body))


def test_pemicu_tugas_marketing(monkeypatch):
    import utils.scheduler as sch

    async def _job():
        return None
    monkeypatch.setattr(sch, "job_auto_create_marketing_tasks", _job)
    _tiga(monkeypatch, "routes.marketing_task_templates", "pic_marketing", "toko.manage",
          lambda mm, req, u: mm.trigger_auto_create_tasks(req))


def test_bulk_approve_klaim_dan_penyelesaian():
    from core.bulk_approve import bulk_approve
    from core.roles import SETTLEMENT_APPROVE_PERMS

    def coba(user, **kw):
        return _status(lambda: bulk_approve(FakeDB(), user, [], collection="rahaza_expense_claims",
                                            number_field="claim_number", module="expense_claim", **kw))
    assert [coba(U("hr_manager")), coba(U(PERAN_BUATAN, "hr.approve")), coba(U(PERAN_BUATAN, IZIN_LAIN))] \
        == ["lolos", "lolos", "ditolak"]
    assert coba(U(PERAN_BUATAN, "finance.approve")) == "ditolak"   # klaim: hanya hr.approve
    assert coba(U(PERAN_BUATAN, "finance.approve"), allowed_perms=SETTLEMENT_APPROVE_PERMS) == "lolos"


def test_lencana_hr_untuk_penyetuju_buatan_owner():
    from routes.approval_badge import approval_groups
    keys = lambda user: {g["key"] for g in run(approval_groups(FakeDB(), user))}  # noqa: E731
    assert "hr" in keys(U("hr"))
    assert "hr" in keys(U(PERAN_BUATAN, "hr.approve"))
    assert "hr" not in keys(U(PERAN_BUATAN, IZIN_LAIN))


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 5. Pemisahan tugas K25: izin modul SDM tidak pernah membuka pembayaran / jurnal
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_izin_modul_sdm_tidak_membuka_pembayaran():
    from data.module_catalog import expand_permissions
    izin_hr = expand_permissions(["mod.hr_expense.edit", "mod.hr_expense.approve", "mod.hr_kasbon.approve",
                                  "hr.manage", "hr.approve"])
    hr_buatan = U(PERAN_BUATAN, *izin_hr)
    claims = _m("routes.employee_expense_claims")
    travel = _m("routes.employee_travel_requests")
    stl = _m("routes.employee_travel_settlements")
    petty = _m("routes.rahaza_petty_cash")
    bank = _m("routes.rahaza_bank_transfers")
    assert claims.is_claim_approver(hr_buatan)                 # boleh menyetujui klaim …
    assert not claims.is_claim_payer(hr_buatan)                # … tetapi TIDAK mencairkannya
    assert not auth.check_role(hr_buatan, travel.ADVANCE_PAYER_ROLES, travel.FINANCE_PAY_PERMS)
    assert not stl.is_settlement_poster(hr_buatan)
    assert not petty._is_finance(hr_buatan) and not petty._is_cash_user(hr_buatan)
    assert not bank._is_cash_officer(hr_buatan)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 6. Gerbang DELETE / tulis `only(*ROLES, perm=...)` — semua rute yang dipasangi izin
# ══════════════════════════════════════════════════════════════════════════════════════════════════
MODUL_ONLY = [
    "dewi_accessory_requests", "dewi_cmt_component_requests", "dewi_cmt_packing", "dewi_job_board", "dewi_kasbon",
    "dewi_kreator_requests", "dewi_lms", "dewi_maklon", "dewi_maklon_billing", "dewi_maklon_bom_templates",
    "dewi_maklon_buyer_catalog", "dewi_maklon_finance", "dewi_maklon_qc", "dewi_maklon_quote", "dewi_maklon_samples",
    "dewi_okr", "dewi_onboarding", "dewi_org", "dewi_recruitment", "dewi_shift_scheduler", "dewi_toko",
    "dewi_wh_returns", "hr_shifts", "marketing_ads_routes", "marketing_budget", "marketing_content_calendar_routes",
    "marketing_data_import", "marketing_discounts_routes", "marketing_kol_incentive", "marketing_live_sessions_routes",
    "marketing_livehost_portal", "marketing_livehost_scripts", "marketing_livehost_shifts",
    "marketing_livehost_training", "marketing_product_launches_routes", "marketing_returns_routes",
    "marketing_reviews_routes", "marketing_samples_routes", "marketing_task_templates", "marketing_tasks",
    "marketing_webhooks", "production_material_returns", "rahaza_accruals", "rahaza_budget", "rahaza_downtime",
    "rahaza_notifications", "rahaza_payroll_allowances", "rahaza_production_calendar", "rahaza_shift_handover",
    "rahaza_shipments", "sku_bridge", "warehouse", "wms_capacity_planning", "wms_delivery_notes",
    "wms_fabric_rolls", "wms_legacy", "wms_picklist", "wms_structure", "wms_units",
]
_NAMA = re.compile(r"^require_roles\[([^|\]]*)\|([^\]]+)\]$")


def _gerbang_only():
    out = []
    for nama in MODUL_ONLY:
        m = _m(f"routes.{nama}")
        for r in m.router.routes:
            for d in getattr(r, "dependencies", []) or []:
                mm = _NAMA.match(getattr(d.dependency, "__name__", ""))
                if mm:
                    roles = [x for x in mm.group(1).split(",") if x not in ("superadmin", "admin")]
                    out.append((nama, f"{sorted(r.methods)[0]} {r.path}", roles, mm.group(2).split(","),
                                d.dependency))
    return out


GERBANG_ONLY = _gerbang_only()


def test_jumlah_gerbang_only_berizin():
    # 85 rute di 59 berkas dipasangi izin (lihat routes/*: `only(*ROLES, perm=...)`)
    assert len(GERBANG_ONLY) >= 85, len(GERBANG_ONLY)
    assert {g[0] for g in GERBANG_ONLY} == set(MODUL_ONLY)


@pytest.mark.parametrize("nama,rute,roles,izin,dep", GERBANG_ONLY, ids=[f"{g[0]}:{g[1]}" for g in GERBANG_ONLY])
def test_gerbang_only_peran_atau_izin(monkeypatch, nama, rute, roles, izin, dep):
    run(dep(_ReqJWT(roles[0])))                                            # (a) kode peran lama
    _pasang_auth(monkeypatch, U(PERAN_BUATAN, izin[0]))
    run(dep(_ReqJWT(PERAN_BUATAN)))                                        # (b) peran buatan + izin
    _pasang_auth(monkeypatch, U(PERAN_BUATAN, IZIN_LAIN))
    with pytest.raises(HTTPException) as e:                                # (c) tanpa izin
        run(dep(_ReqJWT(PERAN_BUATAN)))
    assert e.value.status_code == 403


def _izin_rute(nama, rute):
    hit = [g[3] for g in GERBANG_ONLY if g[0] == nama and g[1] == rute]
    assert hit, (nama, rute)
    return set(hit[0])


def test_kunci_izin_only_yang_penting():
    assert _izin_rute("dewi_job_board", "DELETE /api/hr/job-board/jobs/{job_id}") == {"hr.manage"}
    assert _izin_rute("hr_shifts", "DELETE /api/hr/shifts/assignments/{assignment_id}") == \
        {"hr.attendance.manage", "hr.manage"}
    assert _izin_rute("rahaza_production_calendar", "POST /api/rahaza/production-calendar") == {"hr.attendance.manage"}
    assert _izin_rute("dewi_kasbon", "PATCH /api/dewi/kasbon/requests/{req_id}/hr-review") == {"hr.approve"}
    # K25: pencairan kasbon = uang keluar → izin bayar Keuangan, BUKAN fin.expense.manage (tersirat modul SDM)
    assert _izin_rute("dewi_kasbon", "PATCH /api/dewi/kasbon/requests/{req_id}/disburse") == \
        {"finance.manage", "fin.payment.manage"}
    assert _izin_rute("wms_structure", "DELETE /api/wms/racks/{rack_id}") == {"wh.bin.manage"}
    assert _izin_rute("marketing_tasks", "DELETE /api/marketing/tasks/{task_id}") == {"toko.manage"}


def test_gerbang_only_yang_sengaja_tidak_diubah():
    """Pengaturan Sistem (SY2: owner/admin saja) dan hapus tingkat manajemen tetap kode peran saja."""
    for nama in ("dewi_system_config", "dewi_ai_actions", "operations", "operations_pdf_configs",
                 "marketing_integration_settings_routes"):
        m = _m(f"routes.{nama}")
        for r in m.router.routes:
            for d in getattr(r, "dependencies", []) or []:
                n = getattr(d.dependency, "__name__", "")
                assert not (n.startswith("require_roles[") and "|" in n), (nama, r.path, n)
