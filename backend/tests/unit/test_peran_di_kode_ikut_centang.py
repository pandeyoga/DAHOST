"""Penjaga di kode yang dulu berupa daftar kode peran kini ikut centang owner (14 Nov 2026).

Owner: "dari awal saya minta perbaikan role access ternyata masih banyak gap … terakhir kalinya saya tidak ingin ada
masalah lagi". Aturan yang dikunci uji ini, per kelompok:
  * mesin (`core.authz`): kode peran di daftar hanya berlaku selama owner BELUM mengatur centang peran itu; centang
    aksi endpoint atau kunci izin yang disebut meloloskan; peran super selalu boleh; pesan tolak menyebut aksi, modul,
    dan letak centang tanpa kunci program;
  * Produksi/Maklon, Vendor CMT, pengingat vendor, piutang klien maklon, SDM/penggajian, Marketing, persetujuan
    bertingkat, impor/ekspor data, pelepasan aset, dan gerbang peran portal marketing.
Untuk tiap kelompok: peran non-super DENGAN centang yang tepat → boleh; peran yang centangnya sudah diatur TANPA
centang itu → ditolak (walau kode perannya ada di daftar lama). Aturan bisnis (pemisahan tugas) tetap.
Hermetik: tanpa Mongo.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import auth  # noqa: E402
from core import authz  # noqa: E402
from data.module_catalog import request_key  # noqa: E402

TEMPAT = "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses"
SUDAH_DIATUR = "mod.mgmt_dashboard.view"      # centang lain: tanda owner sudah mengatur centang peran ini


def run(coro):
    return asyncio.run(coro)


def U(role, *perms, method=None, path=None):
    u = {"id": f"u-{role}", "name": "Uji", "email": "uji@contoh.test", "role": role,
         "_permissions": list(perms), "_role_perms": list(perms)}
    if method:
        u["_aksi_request"] = request_key(method, path)
        u["_aksi_setara"] = []
    return u


class _Req:
    def __init__(self, role="", method="GET", path="/"):
        tok = auth.create_token({"id": f"u-{role}", "email": "uji@contoh.test", "role": role, "name": "Uji"})
        self.headers = {"Authorization": f"Bearer {tok}"}
        self.query_params = {}
        self.method = method

        class _Url:
            pass
        self.url = _Url()
        self.url.path = path

        class _S:
            pass
        self.state = _S()


def _pasang(monkeypatch, modul, user):
    async def _auth(_req):
        return dict(user)
    monkeypatch.setattr(modul, "require_auth", _auth, raising=False)
    monkeypatch.setattr(authz._auth, "require_auth", _auth)


# ═══════════════════════════════ 1. mesin core.authz ═══════════════════════════════
def test_pesan_centang_sebut_aksi_modul_letak_tanpa_kunci():
    p = authz.pesan_centang(U("x", method="POST", path="/api/rahaza/payroll-runs/r1/pay"))
    assert "\"Setujui\"" in p and "Penggajian" in p and TEMPAT in p
    assert "mod." not in p and "hanya SPV" not in p.lower()
    p2 = authz.pesan_centang(None, "mod.mak_billing.create")
    assert "\"Tambah\"" in p2 and "Piutang Klien" in p2 and "Portal Maklon" in p2
    p3 = authz.pesan_centang(None, apa="mengunci periode")
    assert "mengunci periode" in p3 and TEMPAT in p3


def test_izin_atau_peran_lama_kode_peran_hanya_selama_belum_diatur():
    peran = ("hr", "manager")
    assert authz.izin_atau_peran_lama(U("hr"), peran, "hr.manage")                    # belum diatur → kode peran
    assert not authz.izin_atau_peran_lama(U("hr", SUDAH_DIATUR), peran, "hr.manage")  # diatur tanpa izin → ditolak
    assert authz.izin_atau_peran_lama(U("HR Generalist", "hr.manage"), peran, "hr.manage")
    assert authz.izin_atau_peran_lama(U("owner", SUDAH_DIATUR), peran, "hr.manage")   # peran super
    assert not authz.izin_atau_peran_lama(U("Kepala Gudang"), peran, "hr.manage")


def test_boleh_centang_aksi_endpoint():
    m, p = "POST", "/api/vendor-portal/partners"
    assert authz.boleh_centang(U("admin_produksi", "mod.prod_vendor_cmt.create", method=m, path=p))
    assert not authz.boleh_centang(U("ppic", "mod.prod_vendor_cmt.view", method=m, path=p), peran_lama=("ppic",))
    with pytest.raises(HTTPException) as e:
        authz.wajib_centang(U("ppic", "mod.prod_vendor_cmt.view", method=m, path=p), peran_lama=("ppic",))
    assert e.value.status_code == 403 and "Vendor CMT" in e.value.detail and TEMPAT in e.value.detail


def test_require_roles_kode_peran_tidak_mengalahkan_centang(monkeypatch):
    dep = authz.require_roles("manager", perm="mod.acc_master.delete")
    req = _Req("manager", "DELETE", "/api/accessory-shipments/s1")
    _pasang(monkeypatch, authz._auth, U("manager", SUDAH_DIATUR))
    with pytest.raises(HTTPException) as e:                       # kode peran ada di daftar, centang sudah diatur
        run(dep(req))
    assert e.value.status_code == 403 and "Master & Stok Aksesoris" in e.value.detail
    _pasang(monkeypatch, authz._auth, U("Kepala Gudang", "mod.acc_master.delete"))
    run(dep(_Req("Kepala Gudang", "DELETE", "/api/accessory-shipments/s1")))   # centang yang disebut → boleh
    _pasang(monkeypatch, authz._auth, U("manager"))                             # belum diatur → kode peran lama
    run(dep(req))
    run(dep(_Req("owner", "DELETE", "/api/x")))                                  # super: tanpa kueri


def test_require_roles_centang_aksi_endpoint_katalog(monkeypatch):
    dep = authz.require_roles("hr", perm="hr.manage")
    path = "/api/dewi/org/units/u1"
    _pasang(monkeypatch, authz._auth, U("Staf Org", "mod.hr_org.delete", method="DELETE", path=path))
    run(dep(_Req("Staf Org", "DELETE", path)))
    _pasang(monkeypatch, authz._auth, U("hr", "mod.hr_org.view", method="DELETE", path=path))
    with pytest.raises(HTTPException):
        run(dep(_Req("hr", "DELETE", path)))


# ═══════════════════════════════ 2. Produksi / Maklon ═══════════════════════════════
def test_produksi_penjaga_staf_ikut_centang():
    from routes.production_rbac import assert_prod_admin, can_po_action, prod_admin_ok, require_write_actor
    m, p = "POST", "/api/production-pos/po1/close"
    assert prod_admin_ok(U("Kepala Produksi", "mod.prod_po.approve", method=m, path=p))
    assert not prod_admin_ok(U("admin_produksi", "mod.prod_po.view", method=m, path=p))   # dulu lolos kode peran
    assert prod_admin_ok(U("admin_produksi", method=m, path=p))                            # belum diatur
    with pytest.raises(HTTPException) as e:
        assert_prod_admin(U("ppic", "mod.prod_po.view", method=m, path=p))
    assert "PO Internal" in e.value.detail and TEMPAT in e.value.detail
    require_write_actor({"role": "cmt_vendor", "_permissions": ["cmt.my_jobs.view"]})     # vendor: penjaga sendiri
    # PO: centang modul jenisnya; kode peran bawaan hanya bila belum diatur
    assert can_po_action(U("Admin PO", "mod.prod_po.create"), "create", "internal")
    assert not can_po_action(U("admin_maklon", "mod.prod_po.create"), "create", "maklon")
    assert can_po_action(U("admin_maklon"), "create", "maklon")


def test_vendor_cmt_master_ikut_centang():
    from routes.vendor_portal import _require_admin
    m, p = "POST", "/api/vendor-portal/accounts"
    _require_admin(U("admin_produksi", "mod.prod_vendor_cmt.create", method=m, path=p))   # dulu 403 (bukan daftar)
    with pytest.raises(HTTPException):
        _require_admin(U("ppic", "mod.prod_vendor_cmt.view", method=m, path=p))           # dulu lolos kode peran
    # /jobs di luar katalog: kunci Lihat disebut handler
    _require_admin(U("Staf CMT", "mod.prod_vendor_cmt.view", method="GET", path="/api/vendor-portal/jobs"),
                   "mod.prod_vendor_cmt.view")


def test_pengingat_vendor_di_luar_katalog_pakai_centang_vendor_cmt():
    from routes.operations_reminders import REMINDER_PERM, VENDOR_REMINDER_WRITER_ROLES
    assert request_key("POST", "/api/reminders") is None
    ok = authz.izin_atau_peran_lama
    assert ok(U("Koordinator CMT", REMINDER_PERM["create"]), VENDOR_REMINDER_WRITER_ROLES, REMINDER_PERM["create"])
    assert not ok(U("ppic", SUDAH_DIATUR), VENDOR_REMINDER_WRITER_ROLES, REMINDER_PERM["create"])


def test_piutang_klien_maklon_di_luar_katalog():
    from routes.dewi_maklon_billing import _require_payment_role
    _require_payment_role(U("Kasir", "mod.fin_ar.create"))
    _require_payment_role(U("Admin Maklon", "mod.mak_billing.edit"), "edit")
    with pytest.raises(HTTPException) as e:
        _require_payment_role(U("admin_maklon", "mod.mak_billing.view"))      # dulu lolos kode peran
    assert "Piutang Klien" in e.value.detail


def test_selisih_kirim_cmt_butuh_setujui_bukan_lihat():
    from data.module_catalog import resolve
    # katalog membaca "resolve" sebagai Lihat — handler memakai kunci Setujui Terima & QC
    assert resolve("POST", "/api/prod/short-shipments/s1/resolve")[1] == "view"
    ok = authz.izin_atau_peran_lama
    roles = ["admin_produksi"]
    assert ok(U("QC", "mod.prod_cmt_receive.approve"), roles, "mod.prod_cmt_receive.approve")
    assert not ok(U("admin_produksi", "mod.prod_cmt_receive.view"), roles, "mod.prod_cmt_receive.approve")


# ═══════════════════════════════ 3. SDM & penggajian ═══════════════════════════════
def test_penggajian_izin_penggajian_bukan_kode_peran(monkeypatch):
    import routes.rahaza_payroll_shared as ps
    from data.module_catalog import expand_permissions
    path = "/api/rahaza/payroll-runs/r1/slips"
    _pasang(monkeypatch, ps, U("Staf Gaji", *expand_permissions(["mod.hr_payroll.edit"]), method="GET", path=path))
    assert run(ps._require_hr(_Req("x", "GET", path)))["role"] == "Staf Gaji"
    _pasang(monkeypatch, ps, U("manager", "mod.hr_payroll.view", method="GET", path=path))   # dulu lolos kode peran
    with pytest.raises(HTTPException) as e:
        run(ps._require_hr(_Req("x", "GET", path)))
    assert "Penggajian" in e.value.detail and TEMPAT in e.value.detail
    # Q8: rincian gaji per orang = izin penggajian, bukan kode peran manager yang sudah diatur
    assert not ps.can_view_payroll_detail(U("manager", "mod.hr_payroll.view"))
    assert ps.can_view_payroll_detail(U("Payroll", "payroll.manage"))


def test_batal_run_gaji_pemisahan_tugas_tetap():
    from data.module_catalog import expand_permissions
    from routes.rahaza_payroll_runs import _is_finance_actor, _is_hr_actor
    hr = expand_permissions(["mod.hr_payroll.create", "mod.hr_payroll.approve"])
    assert _is_hr_actor(U("HR Generalist", *hr)) and not _is_finance_actor(U("HR Generalist", *hr))
    fin = expand_permissions(["mod.fin_journal.approve"])
    assert _is_finance_actor(U("Accounting & Finance", *fin))
    assert not _is_finance_actor(U("accounting", SUDAH_DIATUR))      # kode peran Keuangan tidak cukup lagi


def test_sdm_bertindak_atas_nama_karyawan():
    from utils.employee_identity import is_hr
    from data.module_catalog import expand_permissions
    assert is_hr(U("Admin Absensi", *expand_permissions(["mod.hr_attendance.edit"])))
    assert not is_hr(U("supervisor", SUDAH_DIATUR))
    assert is_hr(U("supervisor"))


# ═══════════════════════════════ 4. Marketing ═══════════════════════════════
def test_marketing_spv_ikut_centang():
    from routes.marketing_shared import _is_pic_role, can_create_task
    assert _is_pic_role(U("Kepala Tugas", "mod.mkt_tasks.approve"), "mod.mkt_tasks.approve")
    assert not _is_pic_role(U("pic_toko", "mod.mkt_tasks.view"), "mod.mkt_tasks.approve")   # dulu lolos kode peran
    assert _is_pic_role(U("pic_toko"))                                                      # belum diatur
    assert can_create_task(U("Content Creator", "mod.mkt_tasks.create"))
    assert not can_create_task(U("manager_marketing", "mod.mkt_tasks.view"))


# ═══════════════════════════════ 5. Manajemen & lintas portal ═══════════════════════════════
def test_persetujuan_bertingkat_level_lewat_centang():
    from services.approval_chain_service import _may_act_on_level
    assert _may_act_on_level(U("Kepala Bagian", "mod.mgmt_approval.approve"), {"role": "manager"})
    assert _may_act_on_level(U("HR Generalist", "hr.approve"), {"role": "hr"})
    assert not _may_act_on_level(U("Kepala Bagian", "mod.mgmt_approval.approve"), {"role": "owner"})
    assert not _may_act_on_level(U("Staf"), {"role": "finance"})


def test_impor_ekspor_data_ikut_centang():
    from routes.data_transfer import REGISTRY, _can_export, _can_import
    assert _can_export(U("Kepala Gudang", "mod.wh_stock.export"), REGISTRY["material_stock"])
    assert not _can_export(U("Kepala Gudang", "mod.wh_stock.view"), REGISTRY["material_stock"])
    assert _can_import(U("Admin Libur", "mod.hr_holiday_calendar.create"), REGISTRY["holidays"])
    assert not _can_import(U("hr", SUDAH_DIATUR), REGISTRY["holidays"])          # kode peran tidak cukup lagi
    assert not _can_import(U("Kepala Gudang", "mod.wh_stock.create"), REGISTRY["users"])   # pengguna: owner/admin


def test_pelepasan_aset_keputusan_keuangan():
    from routes.asset.disposal import _can_decide_finance
    assert _can_decide_finance(U("Aset", "mod.fin_fixed_assets.approve"))
    assert not _can_decide_finance({**U("manager", SUDAH_DIATUR), "_role_portals": ["management"]})


def test_peran_portal_marketing_modul_bercentang_tanpa_lihat(monkeypatch):
    """pic_toko dicentang Order Cutting › Tambah (tanpa Lihat, portal Cutting tidak dicentang) → tidak ditolak
    gerbang 'khusus staf internal'; tanpa centang modul itu tetap ditolak."""
    async def live(uid):
        return {"role": "pic_toko", "blocked": False}

    async def portals(role, uid):
        return ["toko"], []
    state = {"perms": ["mod.cut_orders.create"]}

    async def rbac(role, uid):
        return list(state["perms"]), []
    monkeypatch.setattr(authz._auth, "_load_live_user", live)
    monkeypatch.setattr(authz._auth, "_load_portal_config", portals)
    monkeypatch.setattr(authz._auth, "_load_rbac", rbac)
    payload = {"id": "u-pic", "role": "pic_toko"}
    assert run(authz._portal_diberikan_owner(payload, "pic_toko", "/api/cutting/orders"))
    state["perms"] = ["mod.mkt_sales.create"]
    assert not run(authz._portal_diberikan_owner(payload, "pic_toko", "/api/cutting/orders"))
