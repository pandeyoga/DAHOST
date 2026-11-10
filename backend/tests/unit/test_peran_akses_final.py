"""Akses per peran (keputusan owner 10 Nov 2026) — uji HERMETIK, tanpa server dan tanpa Mongo.

  1. Portal yang dicentang owner di Manajemen Role = FINAL (bawaan kode tidak ditambahkan lagi) —
     sama di pemeriksa portal, daftar portal, `resolve_role_access` (/auth/me & login) dan gerbang modul.
  2. Peran yang portalnya belum dicentang sama sekali → bawaan `PORTAL_ACCESS`; portal per orang ditambahkan.
  3. Peran bawaan hanya diisi pada instalasi baru — peran yang diganti nama/dihapus owner tidak dibuat ulang.
  4. Nama peran yang ejaannya mirip (cuting vs cutting) diperingatkan (409 PERAN_MIRIP), bisa dilanjutkan.
  5. Migrasi rapikan peran kembar: pratinjau tidak menulis, hanya peran kosong tanpa akun yang dihapus.

Jalankan:  cd backend && python -m pytest tests/unit/test_peran_akses_final.py -n 0 -q
"""
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
import auth  # noqa: E402
import middleware.module_permission_gate as gate  # noqa: E402
from core import reference_dedup as rd  # noqa: E402
from routes import shared  # noqa: E402
from routes.shared import (  # noqa: E402
    check_portal_access, default_portals, effective_portals, get_user_portals, resolve_role_access,
)

ADMIN = {"id": "u-adm", "name": "Admin", "role": "superadmin", "email": "a@x"}


def run(coro):
    return asyncio.run(coro)


# ═════════════════════════ 1–2. aturan portal ═════════════════════════
def test_portal_dicentang_final_bawaan_tidak_ditambahkan():
    # Keluhan owner: Supervisor Cutting dicentang Cutting + Gudang tapi tetap melihat Produksi + Pengadaan.
    assert {"production", "cutting", "procurement"} <= set(default_portals("spv_cuting"))
    got = set(effective_portals("spv_cuting", ["cutting", "warehouse"]))
    assert got == {"cutting", "warehouse", "self", "collaboration"}
    assert set(effective_portals("pic_toko", ["toko", "rnd"])) == {"toko", "rnd", "self", "collaboration"}
    assert "warehouse" not in effective_portals("tim_packing", ["production", "maklon"])


def test_portal_kosong_memakai_bawaan_dan_portal_per_orang_ditambahkan():
    assert set(effective_portals("tim_packing", [])) == {"warehouse", "self", "collaboration"}
    assert set(effective_portals("tim_packing", None, ["finance"])) == {"warehouse", "finance", "self", "collaboration"}
    assert set(effective_portals("spv_cuting", ["cutting"], ["procurement"])) == {
        "cutting", "procurement", "self", "collaboration"}
    # peran buatan owner tanpa portal & tanpa bawaan → hanya portal semua orang
    assert set(effective_portals("Host Live", [])) == {"self", "collaboration"}


def test_peran_super_selalu_semua_portal():
    for role in ("superadmin", "admin", "owner", "Owner"):
        assert set(effective_portals(role, ["self"])) == set(shared.PORTAL_ACCESS)
        assert check_portal_access({"role": role, "_role_portals": ["self"]}, "finance")


@pytest.mark.parametrize("user", [
    {"role": "spv_cuting", "_role_portals": ["cutting", "warehouse"], "_extra_portals": []},
    {"role": "spv_cuting", "_portals": ["cutting", "warehouse"]},          # pemanggil lama: _portals = centangan
    {"role": "tim_packing", "_role_portals": [], "_extra_portals": ["maklon"]},
    {"role": "pic_toko"},
])
def test_pemeriksa_portal_sama_dengan_daftar_portal(user):
    portals = set(get_user_portals(user))
    for pid in shared.PORTAL_ACCESS:
        assert check_portal_access(user, pid) == (pid in portals), pid


def test_resolve_role_access_centangan_final(monkeypatch):
    db = FakeDB()
    db.roles.docs = [{"id": "r-spv", "name": "spv_cuting", "portals": ["cutting", "warehouse"]},
                     {"id": "r-tp", "name": "tim_packing", "portals": []}]
    db.users.docs = [{"id": "u1", "role": "spv_cuting", "role_id": "r-spv"},
                     {"id": "u2", "role": "tim_packing", "role_id": "r-tp", "extra_portals": ["maklon"]}]
    acc = run(resolve_role_access(db, {"id": "u1", "role": "spv_cuting"}))
    assert set(acc["portals"]) == {"cutting", "warehouse", "self", "collaboration"}
    assert acc["portal_source"] == "peran"
    acc2 = run(resolve_role_access(db, {"id": "u2", "role": "tim_packing"}))
    assert set(acc2["portals"]) == {"warehouse", "maklon", "self", "collaboration"}
    assert acc2["portal_source"] == "bawaan"


def test_require_auth_memisahkan_portal_peran_dan_per_orang(monkeypatch):
    from starlette.requests import Request

    async def live(uid):
        return {"id": uid, "role": "spv_cuting"}

    async def rbac(role, uid):
        return [], []

    async def cfg(role, uid):
        return ["cutting"], ["procurement"]
    monkeypatch.setattr(auth, "_load_live_user", live)
    monkeypatch.setattr(auth, "_load_rbac", rbac)
    monkeypatch.setattr(auth, "_load_portal_config", cfg)
    tok = auth.create_token({"id": "u1", "email": "s@x.test", "role": "spv_cuting", "name": "S"})
    req = Request({"type": "http", "method": "GET", "path": "/", "query_string": b"",
                   "headers": [(b"authorization", f"Bearer {tok}".encode())]})
    user = run(auth.require_auth(req))
    assert user["_role_portals"] == ["cutting"] and user["_extra_portals"] == ["procurement"]
    assert check_portal_access(user, "procurement") and not check_portal_access(user, "production")


@pytest.fixture
def gerbang(monkeypatch):
    state = {}

    async def live(uid):
        return {"id": uid, "role": state["role"]}

    async def rbac(role, uid):
        return [], []

    async def cfg(role, uid):
        return list(state["portals"]), []
    monkeypatch.setattr(gate, "_load_live_user", live)
    monkeypatch.setattr(gate, "_load_rbac", rbac)
    monkeypatch.setattr(gate, "_load_portal_config", cfg)

    def _login(role, portals):
        state.update(role=role, portals=portals)
        return {"id": f"u-{role}", "role": role}
    return _login


def test_gerbang_modul_menolak_portal_bawaan_yang_tidak_dicentang(gerbang):
    from data.module_catalog import MODULE_BY_ID
    prefix = MODULE_BY_ID["proc_requests"]["paths"][0]
    # Pengadaan = bawaan spv_cuting, tapi owner hanya mencentang Cutting + Gudang → aksi tulis ditolak.
    denied = run(gate.evaluate("POST", f"{prefix}/pr-1/approve", gerbang("spv_cuting", ["cutting", "warehouse"])))
    assert denied is not None and denied[2] == "portal"
    # Dicentang → lolos; peran belum diatur → aturan lama (tidak dicek portalnya).
    assert run(gate.evaluate("POST", f"{prefix}/pr-1/approve", gerbang("spv_cuting", ["cutting", "procurement"]))) is None
    assert run(gate.evaluate("POST", f"{prefix}/pr-1/approve", gerbang("spv_cuting", []))) is None


# ═════════════════════════ 3. benih peran hanya instalasi baru ═════════════════════════
def test_benih_peran_hanya_pada_instalasi_baru():
    db = FakeDB()
    n = run(auth._seed_default_roles(db))
    names = {r["name"] for r in db.roles.docs}
    assert n == len(names) and {"spv_cuting", "operator_cuting", "admin_aksesoris"} <= names
    assert len({r["id"] for r in db.roles.docs}) == len(db.roles.docs)
    assert run(auth._seed_default_roles(db)) == 0 and len(db.roles.docs) == n


def test_benih_tidak_membuat_ulang_peran_yang_diganti_nama_atau_dihapus():
    db = FakeDB()
    # Owner mengganti "admin_aksesoris" → "Admin Aksesoris" dan menghapus "operator_cuting".
    db.roles.docs = [{"id": "r1", "name": "Admin Aksesoris"}, {"id": "r2", "name": "spv_cuting"}]
    assert run(auth._seed_default_roles(db)) == 0
    assert [r["name"] for r in db.roles.docs] == ["Admin Aksesoris", "spv_cuting"]


# ═════════════════════════ 4. peringatan nama mirip ═════════════════════════
@pytest.mark.parametrize("a,b,mirip", [
    ("operator cutting", "Operator Cuting", True),
    ("Assistant Accounting", "Assistan Accounting", True),
    ("spv_cuting", "spv_gudang", False),
    ("admin_gudang", "admin_maklon", False),
    ("hr", "HRD", False),                       # nama pendek tidak dibandingkan
    ("operator_cuting", "Operator Cuting", False),  # sama persis → ditangani aturan nama setara (400)
])
def test_similar_ref(a, b, mirip):
    assert rd.similar_ref(a, b) is mirip


def _routes_admin(monkeypatch, db):
    import routes.admin as adm

    async def as_admin(_r):
        return ADMIN
    monkeypatch.setattr(adm, "require_auth", as_admin)
    monkeypatch.setattr(adm, "get_db", lambda: db)
    return adm


def test_tambah_peran_mirip_diperingatkan_lalu_boleh_lanjut(monkeypatch):
    db = FakeDB()
    db.roles.docs = [{"id": "r1", "name": "Operator Cuting", "active": True}]
    adm = _routes_admin(monkeypatch, db)
    res = run(adm.create_role(FakeRequest({"name": "operator cutting"})))
    body = json.loads(res.body)
    assert res.status_code == 409 and body["code"] == "PERAN_MIRIP" and body["mirip"] == ["Operator Cuting"]
    assert len(db.roles.docs) == 1                                   # belum ada yang tersimpan
    res2 = run(adm.create_role(FakeRequest({"name": "operator cutting", "izinkan_mirip": True})))
    assert res2.status_code == 201 and len(db.roles.docs) == 2
    # nama setara (hanya beda huruf/garis bawah) tetap DITOLAK, bukan sekadar diperingatkan
    with pytest.raises(HTTPException) as e:
        run(adm.create_role(FakeRequest({"name": "operator_cuting", "izinkan_mirip": True})))
    assert e.value.status_code == 400


def test_ganti_nama_peran_mirip_diperingatkan(monkeypatch):
    db = FakeDB()
    db.roles.docs = [{"id": "r1", "name": "Operator Cuting", "active": True},
                     {"id": "r2", "name": "tim potong", "active": True}]
    adm = _routes_admin(monkeypatch, db)
    res = run(adm.update_role("r2", FakeRequest({"name": "Operator Cutting"})))
    assert res.status_code == 409 and json.loads(res.body)["code"] == "PERAN_MIRIP"
    assert db.roles.docs[1]["name"] == "tim potong"
    # menyimpan tanpa mengganti nama tidak diperingatkan
    out = run(adm.update_role("r1", FakeRequest({"name": "Operator Cuting", "portals": ["cutting"]})))
    assert out["portals"] == ["cutting"]


def test_daftar_peran_menyebut_portal_bawaan(monkeypatch):
    db = FakeDB()
    db.roles.docs = [{"id": "r1", "name": "spv_cuting", "portals": ["cutting"]},
                     {"id": "r2", "name": "owner", "portals": []}, {"id": "r3", "name": "Host Live"}]
    adm = _routes_admin(monkeypatch, db)

    async def counts(_db, roles):
        return {}
    monkeypatch.setattr(adm, "_role_user_counts", counts)
    rows = {r["name"]: r for r in run(adm.get_roles(FakeRequest()))}
    assert set(rows["spv_cuting"]["portal_bawaan"]) == {"production", "cutting", "procurement"}
    assert rows["owner"]["portal_bawaan"] == [] and rows["Host Live"]["portal_bawaan"] == []


# ═════════════════════════ 5. migrasi rapikan peran kembar ═════════════════════════
def _migrasi():
    path = BACKEND / "scripts" / "migrations" / "2026_11_10_rapikan_peran_kembar.py"
    spec = importlib.util.spec_from_file_location("rapikan_peran_kembar", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _db_vps_mini():
    db = FakeDB()
    db.roles.docs = [
        {"id": "a", "name": "Operator Cuting", "portals": ["cutting"]},
        {"id": "b", "name": "operator cutting", "portals": []},
        {"id": "c", "name": "Admin Aksesoris", "portals": ["accessories"]},
        {"id": "d", "name": "admin_aksesoris"},
        {"id": "e", "name": "admin_gudang"},
        {"id": "f", "name": "cs_staff", "portals": ["toko"]},       # sudah diatur → tidak boleh dihapus
    ]
    db.users.docs = [{"id": "u1", "role": "Operator Cuting", "role_id": "a"},
                     {"id": "u2", "role": "operator cuting"},
                     {"id": "u3", "role": "Admin Aksesoris", "role_id": "c"}]
    return db


def test_migrasi_pratinjau_tidak_menulis():
    db = _db_vps_mini()
    before = json.dumps([db.roles.docs, db.users.docs], sort_keys=True)
    out = run(_migrasi().run(db, apply=False, termasuk_bawaan_kosong=True, ganti_nama=True))
    assert set(out["hapus"]) == {"operator cutting", "admin_aksesoris", "admin_gudang"}
    assert "cs_staff" in out["dilewati"] and out["ganti"] == ["Operator Cuting"]
    assert json.dumps([db.roles.docs, db.users.docs], sort_keys=True) == before
    assert not db.rahaza_audit_logs.docs


def test_migrasi_apply_hapus_kembar_kosong_dan_ganti_nama_idempoten():
    db = _db_vps_mini()
    mig = _migrasi()
    run(mig.run(db, apply=True, termasuk_bawaan_kosong=False, ganti_nama=True))
    names = {r["name"] for r in db.roles.docs}
    assert names == {"Operator Cutting", "Admin Aksesoris", "admin_gudang", "cs_staff"}  # bawaan kosong tetap (tanpa flag)
    assert {u["role"] for u in db.users.docs if u["id"] in ("u1", "u2")} == {"Operator Cutting"}
    assert all(u.get("role_id") == "a" for u in db.users.docs if u["id"] in ("u1", "u2"))
    assert {a["action"] for a in db.rahaza_audit_logs.docs} == {"delete", "update"}
    again = run(mig.run(db, apply=True, termasuk_bawaan_kosong=False, ganti_nama=True))
    assert again["hapus"] == [] and again["ganti"] == []
