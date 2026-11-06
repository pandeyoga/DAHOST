"""Tahap 6 — keputusan owner 7 Nov 2026 (Administrasi Sistem + Marketing).

  SY2  Pengaturan Sistem hanya boleh DIUBAH admin / owner / superadmin (membaca tetap seperti semula).
  SY3  Pengguna baru tanpa peran bawaan: peran wajib dipilih (sandi bawaan User@123 TIDAK berubah).
  SY4  Setelan "Penyedia WhatsApp" (`notification_whatsapp_provider`) dipensiunkan.
  MK1  Tugas dari template diberikan ke PIC toko template itu; kosong hanya bila toko tanpa PIC.
  MK2  Permintaan Kreator: warna model acuan tampil dulu (layar).
  MK3  Pilihan PIC toko hanya pengguna yang punya akses Portal Toko (aturan akses yang sama dengan menu).
  MK4  Hapus permanen toko hanya menghitung jurnal di sub-ledger MILIK toko itu, bukan akun pendapatan bersama.
"""
import asyncio
import os
import re
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402

FRONTEND = ROOT.parent / "frontend" / "src"
SUPER = {"id": "u-sa", "name": "Super", "role": "superadmin", "email": "sa@x.test"}


def run(coro):
    return asyncio.run(coro)


def _fe(rel):
    p = FRONTEND / rel
    if not p.exists():
        pytest.skip("frontend/src tidak tersedia di lingkungan uji ini")
    return p.read_text(encoding="utf-8")


def _patch(monkeypatch, mod, db, user=SUPER):
    async def _auth(_req):
        return user
    if hasattr(mod, "require_auth"):
        monkeypatch.setattr(mod, "require_auth", _auth)
    monkeypatch.setattr(mod, "get_db", lambda: db)


# ══ SY2 · ubah Pengaturan Sistem hanya admin/owner/superadmin ══════════════════
def _route(router, path, method):
    from fastapi.routing import APIRoute
    for r in router.routes:
        if isinstance(r, APIRoute) and r.path == path and method in r.methods:
            return r
    raise AssertionError(f"route {method} {path} tidak ada")


def _dep_status(route, role):
    import auth
    tok = auth.create_token({"id": f"u-{role}", "email": f"{role}@x.test", "role": role, "name": role})
    req = Request({"type": "http", "method": "PUT", "path": route.path, "query_string": b"",
                   "headers": [(b"authorization", f"Bearer {tok}".encode())]})

    async def _go():
        for d in route.dependencies:
            await d.dependency(req)
    try:
        run(_go())
        return 200
    except HTTPException as e:
        return e.status_code


@pytest.mark.parametrize("path,method", [("/api/dewi/system/config/{key}", "PUT"),
                                         ("/api/dewi/system/config/bulk", "POST")])
def test_sy2_ubah_pengaturan_hanya_admin_owner_superadmin(path, method):
    import routes.dewi_system_config as cfg
    from core.roles import SYSTEM_CONFIG_ROLES
    assert set(SYSTEM_CONFIG_ROLES) == {"superadmin", "admin", "owner"}
    route = _route(cfg.router, path, method)
    for role in ("superadmin", "admin", "owner"):
        assert _dep_status(route, role) == 200, role
    for role in ("manager", "hr", "accounting", "admin_gudang", "manager_marketing"):
        assert _dep_status(route, role) == 403, role


def test_sy2_membaca_tetap_terbuka_dan_rahasia_tetap_disamarkan(monkeypatch):
    import routes.dewi_system_config as cfg
    assert not _route(cfg.router, "/api/dewi/system/config", "GET").dependencies   # baca: tanpa gerbang baru
    db = FakeDB()
    db.dewi_system_config.docs = [
        {"key": "notification_telegram_bot_token", "value": "rahasia-1234", "is_secret": True,
         "data_type": "string", "category": "notification"},
        {"key": "maklon_invoice_prefix", "value": "INV-MKL", "data_type": "string", "category": "maklon"},
    ]
    _patch(monkeypatch, cfg, db)

    async def _no_defaults(_db):
        return 0
    monkeypatch.setattr(cfg, "ensure_defaults", _no_defaults)
    rows = {r["key"]: r for r in run(cfg.list_configs(category=None, user={"id": "m", "role": "manager"}))}
    assert "value" not in rows["notification_telegram_bot_token"]
    assert rows["notification_telegram_bot_token"]["value_masked"].endswith("1234")
    assert rows["maklon_invoice_prefix"]["value"] == "INV-MKL"


def test_sy2_layar_mode_baca_saja_untuk_peran_lain():
    src = _fe("components/erp/MaklonSystemConfigModule.jsx")
    assert "isCurrentUserConfigAdmin" in src and "cfg-readonly-note" in src
    assert "{canEdit && (" in src                                   # tombol Simpan hanya untuk yang berhak
    assert src.count("disabled={!canEdit}") >= 5                    # semua isian terkunci
    roles = _fe("lib/systemConfigRoles.js")
    assert re.search(r"SYSTEM_CONFIG_ROLES = \['superadmin', 'admin', 'owner'\]", roles)


# ══ SY3 · peran wajib dipilih (sandi bawaan tetap) ═══════════════════════════
def _admin(monkeypatch, db):
    import routes.admin as admin
    _patch(monkeypatch, admin, db)
    monkeypatch.setattr(admin, "bump_rbac_cache", lambda: None)
    return admin


@pytest.mark.parametrize("body_role", [{}, {"role": ""}, {"role": "   "}, {"role": None, "role_id": ""}])
def test_sy3_buat_pengguna_tanpa_peran_ditolak(monkeypatch, body_role):
    db = FakeDB()
    admin = _admin(monkeypatch, db)
    body = {"name": "Uji", "email": "uji@x.test", "password": "", **body_role}
    with pytest.raises(HTTPException) as e:
        run(admin.create_user(FakeRequest(body)))
    assert e.value.status_code == 400 and e.value.detail == "Peran wajib dipilih"
    assert db.users.docs == []


def test_sy3_peran_dari_master_diterima_dan_sandi_bawaan_tetap(monkeypatch):
    from auth import verify_password
    db = FakeDB()
    db.roles.docs = [{"id": "r-pic", "name": "pic_toko"}]
    admin = _admin(monkeypatch, db)
    assert admin.DEFAULT_USER_PASSWORD == "User@123"                # keputusan owner: tidak diubah
    resp = run(admin.create_user(FakeRequest({"name": "A", "email": "a@x.test", "password": "", "role": "pic_toko"})))
    assert resp.status_code == 201
    assert verify_password("User@123", db.users.docs[0]["password"])
    resp = run(admin.create_user(FakeRequest({"name": "B", "email": "b@x.test", "role_id": "r-pic"})))
    assert resp.status_code == 201 and db.users.docs[1]["role"] == "pic_toko"
    with pytest.raises(HTTPException) as e:                           # role_id yang tidak menunjuk peran mana pun
        run(admin.create_user(FakeRequest({"name": "C", "email": "c@x.test", "role_id": "r-hantu"})))
    assert e.value.status_code == 400 and len(db.users.docs) == 2


def test_sy3_ubah_pengguna_tidak_boleh_mengosongkan_peran(monkeypatch):
    db = FakeDB()
    db.users.docs = [{"id": "u1", "email": "u1@x.test", "role": "pic_toko", "status": "active"}]
    admin = _admin(monkeypatch, db)
    with pytest.raises(HTTPException) as e:
        run(admin.update_user("u1", FakeRequest({"name": "U1", "role": ""})))
    assert e.value.status_code == 400 and db.users.docs[0]["role"] == "pic_toko"
    run(admin.update_user("u1", FakeRequest({"status": "inactive"})))   # ubah status saja tetap jalan
    assert db.users.docs[0]["status"] == "inactive" and db.users.docs[0]["role"] == "pic_toko"


def test_sy3_form_tanpa_peran_bawaan():
    src = _fe("components/erp/UserManagementModule.jsx")
    assert "role: 'admin'" not in src
    assert "role: ''" in src and "— Pilih peran —" in src and "Peran wajib dipilih" in src
    assert "User@123" in src                                         # keterangan sandi bawaan tetap


# ══ SY4 · setelan Penyedia WhatsApp dipensiunkan ════════════════════════════
def test_sy4_penyedia_whatsapp_pensiun_dan_tidak_tampil(monkeypatch):
    import routes.dewi_system_config as cfg
    key = "notification_whatsapp_provider"
    assert key not in {c["key"] for c in cfg.DEFAULT_CONFIGS}
    assert key in cfg.RETIRED_KEYS and key not in cfg.CONFIG_CHOICES
    db = FakeDB()
    db.dewi_system_config.docs = [{"key": key, "value": "twilio", "data_type": "string", "category": "notification"}]
    _patch(monkeypatch, cfg, db)
    run(cfg.ensure_defaults(db))
    assert sum(1 for d in db.dewi_system_config.docs if d["key"] == key) == 1     # tidak dibuat ulang
    keys = {r["key"] for r in run(cfg.list_configs(category=None, user=SUPER))}
    assert key not in keys and "notification_whatsapp_enabled" in keys


# ══ MK1 · tugas template → PIC toko ═══════════════════════════════════════════
STORE_PIC = {"id": "acc-1", "account_code": "UJI-1", "account_name": "Toko Uji", "status": "active",
             "pic_user_id": "u-pic", "pic_user_name": "Pic Uji"}
STORE_NOPIC = {"id": "acc-2", "account_code": "UJI-2", "account_name": "Toko Tanpa PIC", "status": "active"}
TPL = {"template_name": "Input harian", "title": "Input sales", "description": None, "task_type": "data_entry",
       "priority": "medium", "recurrence": "daily",
       "recurrence_config": {"frequency": "daily", "time": "09:00", "auto_create": True},
       "default_assigned_role": "staff", "is_active": True, "checklist_template": []}


def _tpl_mod(monkeypatch, db):
    import routes.marketing_task_templates as mtt

    async def _no_log(*a, **k):
        return None
    _patch(monkeypatch, mtt, db)
    monkeypatch.setattr(mtt, "log_activity", _no_log)
    monkeypatch.setattr(mtt, "_get_user", lambda _r: SUPER)
    return mtt


def test_mk1_template_menyimpan_toko_dan_penanggung_jawab_pic(monkeypatch):
    from routes.marketing_shared import TaskTemplateCreate
    db = FakeDB()
    db.marketing_platform_accounts.docs = [dict(STORE_PIC)]
    mtt = _tpl_mod(monkeypatch, db)
    run(mtt.create_task_template(TaskTemplateCreate(**TPL, account_id="acc-1"), FakeRequest()))
    t = db.marketing_task_templates.docs[0]
    assert t["account_id"] == "acc-1" and t["default_assigned_role"] == mtt.TEMPLATE_ASSIGNEE_PIC == "pic_toko"
    with pytest.raises(HTTPException) as e:
        run(mtt.create_task_template(TaskTemplateCreate(**TPL, account_id="acc-hantu"), FakeRequest()))
    assert e.value.status_code == 400
    # layar lama (tombol Aktifkan) tidak mengirim account_id → toko tersimpan tidak hilang
    run(mtt.update_task_template(t["id"], TaskTemplateCreate(**{**TPL, "is_active": False}), FakeRequest()))
    assert db.marketing_task_templates.docs[0]["account_id"] == "acc-1"
    run(mtt.update_task_template(t["id"], TaskTemplateCreate(**TPL, account_id=None), FakeRequest()))
    assert db.marketing_task_templates.docs[0]["account_id"] is None   # dikosongkan dengan sengaja


def test_mk1_tugas_otomatis_diberikan_ke_pic_toko(monkeypatch):
    from utils import scheduler as sch
    db = FakeDB()
    db.marketing_platform_accounts.docs = [dict(STORE_PIC), dict(STORE_NOPIC)]
    base = {"is_active": True, "recurrence": "daily", "recurrence_config": {}, "title": "t", "checklist_template": []}
    db.marketing_task_templates.docs = [
        {**base, "id": "tpl-baru", "account_id": "acc-1", "default_assigned_role": "pic_toko"},
        {**base, "id": "tpl-lama", "account_id": "acc-1", "default_assigned_role": "staff"},   # template lama
        {**base, "id": "tpl-tanpa-pic", "account_id": "acc-2", "default_assigned_role": "pic"},
        {**base, "id": "tpl-tanpa-toko", "default_assigned_role": "staff"},
    ]
    monkeypatch.setattr(sch, "get_db", lambda: db)
    monkeypatch.setattr(sch, "today_wib", lambda: date(2026, 11, 7))
    run(sch.job_auto_create_tasks_from_templates())
    by = {t["template_id"]: t for t in db.marketing_tasks.docs}
    assert set(by) == {"tpl-baru", "tpl-lama", "tpl-tanpa-pic", "tpl-tanpa-toko"}
    for tid in ("tpl-baru", "tpl-lama"):
        assert by[tid]["assigned_to"] == "u-pic" and by[tid]["assigned_to_name"] == "Pic Uji"
        assert by[tid]["assigned_role"] == "pic_toko"
    for tid in ("tpl-tanpa-pic", "tpl-tanpa-toko"):
        assert by[tid]["assigned_to"] is None


def test_mk1_layar_template_tanpa_isian_peran_lama():
    src = _fe("components/erp/TaskTemplatesModule.jsx")
    assert "Default Assigned Role" not in src and "Staff Marketing" not in src
    assert "Penanggung jawab" in src and "tpl-store-select" in src and "ASSIGNEE_PIC_TOKO" in src
    toggle = src[src.index("const toggleActive"):src.index("const recurrenceLabel")]
    assert "account_id: tpl.account_id" in toggle                    # aktifkan ulang tidak menghapus toko
    card = _fe("components/erp/TaskCard.jsx")
    assert "assigned_to_name ||" in card


# ══ MK2 · warna model acuan tampil dulu ══════════════════════════════════════
def test_mk2_warna_model_acuan_tampil_dulu():
    src = _fe("components/erp/KREATORRequestModule.jsx")
    assert "/api/rahaza/variants" in src and "modelColors" in src
    assert 'priority={modelColors} priorityLabel="Warna model ini" otherLabel="Warna lain"' in src
    pk = _fe("components/erp/marketing/pickers/MarketingPickers.jsx")
    block = pk[pk.index("export function MasterChipsSelect"):pk.index("export function useStorePlatforms")]
    assert "priority = []" in block and "first.map" in block and "rest.map" in block


# ══ MK3 · PIC toko = pengguna Portal Toko ════════════════════════════════════
class _QReq(FakeRequest):
    def __init__(self, qp):
        super().__init__()
        self.query_params = qp


def _users_db():
    db = FakeDB()
    db.users.docs = [
        {"id": "u-pic", "name": "A Pic", "role": "pic_toko", "status": "active"},
        {"id": "u-kol", "name": "B Kol", "role": "marketing_kol", "status": "active"},
        {"id": "u-gdg", "name": "C Gudang", "role": "admin_gudang", "status": "active"},
        {"id": "u-hr", "name": "D Hr", "role": "hr", "status": "active"},              # portal toko dari owner
        {"id": "u-x", "name": "E Ekstra", "role": "operator", "status": "active", "extra_portals": ["toko"]},
        {"id": "u-own", "name": "F Owner", "role": "owner", "status": "active"},
        {"id": "u-off", "name": "G Nonaktif", "role": "pic_toko", "status": "inactive", "active": False},
    ]
    db.roles.docs = [{"id": "r-hr", "name": "hr", "portals": ["hr", "toko", "self"]},
                     {"id": "r-gdg", "name": "admin_gudang", "portals": ["warehouse", "self"]}]
    return db


def test_mk3_daftar_pengguna_portal_toko_memakai_akses_efektif(monkeypatch):
    import routes.auth_routes as ar
    db = _users_db()
    _patch(monkeypatch, ar, db)
    out = run(ar.list_users_for_assignment(_QReq({"portal": "toko", "limit": "500"})))
    assert {u["id"] for u in out} == {"u-pic", "u-kol", "u-hr", "u-x", "u-own"}
    everyone = run(ar.list_users_for_assignment(_QReq({"limit": "500"})))   # tanpa penyaring: tidak berubah
    assert len(everyone) == 6


def test_mk3_pic_baru_wajib_punya_akses_portal_toko(monkeypatch):
    import routes.marketing_accounts as ma
    db = _users_db()
    assert run(ma._resolve_pic(db, "u-pic")) == ("u-pic", "A Pic")
    assert run(ma._resolve_pic(db, "u-hr")) == ("u-hr", "D Hr")
    with pytest.raises(HTTPException) as e:
        run(ma._resolve_pic(db, "u-gdg"))
    assert e.value.status_code == 400 and "Portal Toko" in e.value.detail
    # PIC lama yang tidak diganti tidak diperiksa ulang (simpan perubahan lain tetap jalan)
    assert run(ma._resolve_pic(db, "u-gdg", current="u-gdg")) == ("u-gdg", "C Gudang")


def test_mk3_layar_pemilih_pic_memakai_penyaring_portal():
    for rel in ("components/erp/AccountManagementModule.jsx", "components/erp/marketing/AccountBulkReviewModule.jsx"):
        src = _fe(rel)
        assert "/api/auth/users?portal=toko" in src, rel
        assert "/api/auth/users?limit=200" not in src, rel


# ══ MK4 · hapus permanen: hanya sub-ledger milik toko ════════════════════════
NEW_STORE = {"id": "acc-baru", "account_code": "UJI-BARU", "account_name": "Toko Baru", "status": "active",
             "coa_revenue_code": "4-1100", "coa_receivable_code": "1-1303-UJI-BARU"}


def _store_db():
    db = FakeDB()
    db.marketing_platform_accounts.docs = [dict(NEW_STORE),
                                           {"id": "acc-lain", "account_code": "UJI-LAIN", "coa_revenue_code": "4-1100"}]
    db.rahaza_coa_accounts.docs = [
        {"code": "4-1100", "name": "Penjualan Garment", "active": True, "flags": {"is_sales": True}},
        {"code": "1-1303-UJI-BARU", "name": "Piutang Channel — Toko Baru", "active": True,
         "created_by": "system", "flags": {"subledger": True, "subledger_entity_id": "acc-baru"}},
    ]
    # akun pendapatan BERSAMA sudah dijurnal toko lain / penjualan langsung
    db.rahaza_journal_lines.docs = [{"id": f"jl{i}", "account_code": "4-1100", "debit": 0, "credit": 1000}
                                    for i in range(3)]
    db.rahaza_journal_entries.docs = [{"id": "je1", "lines": [{"account_code": "4-1100", "credit": 1000}]}]
    return db


def test_mk4_akun_pendapatan_bersama_tidak_menghalangi_hapus(monkeypatch):
    from core import coa_bindings as cb
    from core import store_cleanup

    async def _no_bindings(db, codes=None, **kw):
        return {c: [] for c in (codes or [])}
    monkeypatch.setattr(cb, "collect_bindings", _no_bindings)
    db = _store_db()
    assert run(store_cleanup.own_coa_codes(db, NEW_STORE)) == ["1-1303-UJI-BARU"]
    assert run(store_cleanup.store_data_refs(db, NEW_STORE)) == {}
    res = run(store_cleanup.delete_store_permanently(db, dict(NEW_STORE), SUPER))
    assert not [a for a in db.marketing_platform_accounts.docs if a["id"] == "acc-baru"]
    assert "4-1100" not in res["coa_deleted"] + res["coa_deactivated"]        # akun bersama tidak disentuh
    assert any(a["code"] == "4-1100" and a["active"] for a in db.rahaza_coa_accounts.docs)


def test_mk4_jurnal_di_sub_ledger_toko_sendiri_tetap_menghalangi():
    from core import store_cleanup
    db = _store_db()
    db.rahaza_journal_lines.docs.append({"id": "jl-own", "account_code": "1-1303-UJI-BARU", "debit": 500})
    with pytest.raises(ValueError) as e:
        run(store_cleanup.delete_store_permanently(db, dict(NEW_STORE), SUPER))
    assert "1 jurnal di akun COA toko ini" in str(e.value)
    assert [a for a in db.marketing_platform_accounts.docs if a["id"] == "acc-baru"]
    # akun penjualan KHUSUS toko (bertanda kode toko) juga milik toko itu
    store = dict(NEW_STORE, coa_revenue_code="4-1199")
    db.rahaza_coa_accounts.docs.append({"code": "4-1199", "flags": {"store_account_code": "UJI-BARU"}})
    assert run(store_cleanup.own_coa_codes(db, store)) == ["1-1303-UJI-BARU", "4-1199"]
