"""Centang owner = satu-satunya penentu (owner 13 Nov 2026: "bisa semuanya, jangan setengah-setengah").

Kasus nyata dari laporan staf dipakai sebagai uji (nama peran, tanpa data orang):
  1. Content Creator dicentang Kelola Akun › Tambah → boleh menambah toko (owner 13 Nov: "bisa menambahkan hak kelola
     akun"); tanpa centang itu ditolak, walau kode perannya dulu ada di daftar.
  2. Koordinator Packing dicentang Stok › Tambah → boleh penyesuaian stok; "Setujui" Stok TIDAK lagi membuka setuju
     opname (owner 13 Nov: "nanti dulu") — opname punya kotak sendiri, Gudang › Opname Stok Gudang.
  3. Supervisor cutting / Admin Aksesoris: setuju opname hanya bila dicentang (terlihat di layar).
  4. R&D: Master Produk (Produksi) bisa diberikan lewat centang dari portal RnD.
  5. PIC toko: Order Cutting tambah/ubah dan Nota Penjualan mengikuti centang.
  6. Peran tanpa portal tercentang tetapi berizin lama (admin_produksi) → migrasi mencentangkan setara izin lamanya.
Ditambah: pemisahan tugas K25 (centang SDM tidak membuka pencairan uang), centang Lihat tidak meloloskan perubahan
data, gerbang modul tanpa aturan lama per portal, dan migrasi hanya menambah centang.
Hermetik: tanpa Mongo.
"""
from __future__ import annotations

import asyncio
import importlib.util
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

import middleware.module_permission_gate as gate  # noqa: E402
from data.module_catalog import ENDPOINT_RULES, MODULE_BY_ID, request_key, resolve  # noqa: E402
from routes.shared import lolos_centang  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def U(role, *perms, method="GET", path="/"):
    return {"id": f"u-{role}", "role": role, "_permissions": list(perms), "_aksi_request": request_key(method, path)}


# ═══════════════════════════ katalog: kunci tiap permintaan ═══════════════════════════
@pytest.mark.parametrize("method,path,key", [
    ("POST", "/api/marketing/accounts", "mod.mkt_accounts.create"),
    ("PUT", "/api/marketing/accounts/a1", "mod.mkt_accounts.edit"),
    ("DELETE", "/api/marketing/accounts/a1", "mod.mkt_accounts.delete"),
    ("DELETE", "/api/marketing/accounts/a1/permanent", "mod.mkt_accounts.delete"),
    ("GET", "/api/marketing/accounts", "mod.mkt_accounts.view"),
    ("PUT", "/api/marketing/accounts/a1/ship-sla", "mod.mkt_accounts.edit"),
    ("PATCH", "/api/dewi/kasbon/requests/k1/disburse", "mod.fin_pencairan.approve"),
    ("POST", "/api/hr/expenses/claims/c1/disburse", "mod.fin_pencairan.approve"),
    ("POST", "/api/rahaza/payroll-runs/r1/pay-bpjs", "mod.hr_payroll.approve"),
    ("POST", "/api/rahaza/grn-qc/inspect/g1", "mod.wh_receiving.approve"),
    ("POST", "/api/wms/opname3/s1/approve", "mod.wh_opname.approve"),
    ("POST", "/api/rahaza/material-adjust", "mod.wh_stock.create"),
])
def test_kunci_centang_per_endpoint(method, path, key):
    assert request_key(method, path) == key


def test_aturan_endpoint_valid_dan_centang_lihat_tidak_meloloskan_tulis():
    assert all(act in MODULE_BY_ID[mid]["actions"] for _, _, mid, act in ENDPOINT_RULES)
    # Modul hanya Lihat/Unduh: perintah hapus jatuh ke "Lihat" di gerbang, tetapi TIDAK boleh meloloskan penjaga kode.
    mod, act = resolve("DELETE", "/api/dewi/toko/flashsales/f1")
    assert act == "view" and request_key("DELETE", "/api/dewi/toko/flashsales/f1") is None
    assert request_key("POST", "/api/wms/fabric-rolls/import/preview") is not None   # POST baca tetap Lihat


# ═══════════════════════════ penjaga di kode menghormati centang ═══════════════════════════
def test_lolos_centang_hanya_untuk_aksi_endpoint_ini():
    assert lolos_centang(U("Content Creator", "mod.mkt_accounts.create", method="POST", path="/api/marketing/accounts"))
    assert not lolos_centang(U("Content Creator", "mod.mkt_accounts.view", method="POST", path="/api/marketing/accounts"))
    assert not lolos_centang(U("Content Creator", "mod.mkt_accounts.create", method="PUT", path="/api/marketing/accounts/a"))
    assert lolos_centang(U("owner", method="POST", path="/api/marketing/accounts"))
    assert not lolos_centang({"role": "Koordinator Packing", "_permissions": ["mod.wh_stock.edit"]})  # tanpa endpoint


def test_k25_centang_sdm_tidak_membuka_pencairan_uang():
    from data.module_catalog import expand_permissions
    hr = expand_permissions(["mod.hr_expense.create", "mod.hr_expense.edit", "mod.hr_expense.approve",
                             "mod.fin_kasbon.edit", "mod.hr_payroll.approve"])
    for method, path in (("POST", "/api/hr/expenses/claims/c1/disburse"), ("PATCH", "/api/dewi/kasbon/requests/k/disburse"),
                         ("POST", "/api/rahaza/hr/employee-loans/disburse")):
        assert not lolos_centang(U("HR Generalist", *hr, method=method, path=path)), path
        assert lolos_centang(U("Finance & Purchase", "mod.fin_pencairan.approve", method=method, path=path)), path
    # "Pembayaran & Pencairan" menyiratkan izin bayar lama → penjaga lama (FINANCE_PAY_PERMS) juga lolos
    assert "fin.payment.manage" in expand_permissions(["mod.fin_pencairan.approve"])


@pytest.fixture
def masuk(monkeypatch):
    """require_auth palsu yang mengisi kunci aksi persis seperti auth.require_auth."""
    state = {}

    async def _auth(req):
        u = dict(state["user"])
        u["_aksi_request"] = request_key(req.method, req.url.path)
        return u

    class _Url:
        def __init__(self, path):
            self.path = path

    class _Req:
        def __init__(self, method, path):
            self.method, self.url = method, _Url(path)
            self.headers, self.query_params = {}, {}

            class _S:
                pass
            self.state = _S()

    def _pakai(mod, role, perms, method, path):
        state["user"] = {"id": f"u-{role}", "role": role, "_permissions": list(perms), "_role_perms": list(perms)}
        import auth
        monkeypatch.setattr(auth, "require_auth", _auth)      # dipakai routes.shared.require_perm
        if hasattr(mod, "require_auth"):
            monkeypatch.setattr(mod, "require_auth", _auth)
        return _Req(method, path)
    return _pakai


def test_kasus_1_content_creator_master_toko(masuk):
    import routes.marketing_accounts as ma
    req = masuk(ma, "Content Creator", ["mod.mkt_accounts.view", "mod.mkt_accounts.create"], "POST",
                "/api/marketing/accounts")
    assert run(ma._assert_can_manage_stores(req))["role"] == "Content Creator"
    req = masuk(ma, "Content Creator", ["mod.mkt_accounts.view"], "POST", "/api/marketing/accounts")
    with pytest.raises(HTTPException) as e:
        run(ma._assert_can_manage_stores(req))
    assert e.value.status_code == 403 and "Kelola Akun" in e.value.detail
    assert ma.can_manage_stores({"role": "pic_toko", "_permissions": ["mod.mkt_accounts.edit"]})
    assert not ma.can_manage_stores({"role": "manager_marketing", "_permissions": []})  # kode peran tidak cukup lagi


def test_kasus_2_koordinator_packing_opname_dan_penyesuaian(masuk):
    import routes.rahaza_inventory_shared as inv
    from routes.wms_opname3 import assert_can_approve
    from data.module_catalog import expand_permissions
    # Owner 13 Nov: setuju opname Koordinator Packing "nanti dulu" — Setujui Stok + izin lama warehouse.approve
    # (yang dimiliki peran itu) TIDAK lagi membuka setuju opname.
    kp = expand_permissions(["mod.wh_stock.approve", "mod.wh_stock.edit", "warehouse.approve", "warehouse.manage"])
    with pytest.raises(HTTPException):
        assert_can_approve({"role": "Koordinator Packing", "_permissions": kp, "_role_perms": kp})
    assert_can_approve({"role": "Koordinator Packing", "_permissions": kp + ["mod.wh_opname.approve"], "_role_perms": kp})
    req = masuk(inv, "Koordinator Packing", ["mod.wh_stock.create"], "POST", "/api/rahaza/material-adjust")
    assert run(inv._require_admin(req))["role"] == "Koordinator Packing"
    req = masuk(inv, "Koordinator Packing", ["mod.wh_stock.view"], "POST", "/api/rahaza/material-adjust")
    with pytest.raises(HTTPException):
        run(inv._require_admin(req))


def test_kasus_3_setuju_opname_hanya_bila_dicentang():
    from routes.wms_opname3 import assert_can_approve
    # 14 Nov 2026: sesi aksesoris (Portal Aksesoris › Stok Opname) disetujui dengan centang Stok Opname Aksesoris.
    sesi_aksesoris = {"mode": "cycle", "source": "aksesoris", "kinds": ["aksesoris"]}
    with pytest.raises(HTTPException) as e:
        assert_can_approve({"role": "Admin Aksesoris", "_permissions": ["mod.acc_opname.create"], "_role_perms": ["x"]},
                           "menyetujui opname aksesoris", sesi_aksesoris)
    assert "Setujui" in e.value.detail and "Stok Opname Aksesoris" in e.value.detail
    assert "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses" in e.value.detail
    assert "Manajemen Role" not in e.value.detail
    assert_can_approve({"role": "Admin Aksesoris", "_permissions": ["mod.acc_opname.approve"], "_role_perms": ["x"]},
                       "menyetujui opname aksesoris", sesi_aksesoris)


@pytest.fixture
def gerbang(monkeypatch):
    state = {}

    async def live(uid):
        return {"id": uid, "role": state["role"]}

    async def rbac(role, uid):
        return list(state["perms"]), []

    async def cfg(role, uid):
        return list(state["portals"]), []
    monkeypatch.setattr(gate, "_load_live_user", live)
    monkeypatch.setattr(gate, "_load_rbac", rbac)
    monkeypatch.setattr(gate, "_load_portal_config", cfg)

    def _login(role, portals, perms):
        state.update(role=role, portals=portals, perms=perms)
        return {"id": f"u-{role}", "role": role}
    return _login


def test_kasus_4_rnd_master_produk_lewat_centang(gerbang):
    p = "/api/rahaza/models/m1"
    assert run(gate.evaluate("PUT", p, gerbang("research_development", ["rnd"], ["mod.rnd_master_product.edit"])))
    assert run(gate.evaluate("PUT", p, gerbang("research_development", ["rnd"],
                                               ["mod.prod_master_product.edit"]))) is None


@pytest.mark.parametrize("method,path,aksi", [
    ("POST", "/api/rahaza/models/m1/variants/generate", "create"),
    ("POST", "/api/rahaza/variants", "create"),
    ("PUT", "/api/rahaza/variants/v1", "edit"),
    ("DELETE", "/api/rahaza/variants/v1", "delete"),
    ("POST", "/api/rahaza/boms/relink-materials", "approve"),
])
def test_rnd_varian_lewat_centang_master_produk_rnd(gerbang, method, path, aksi):
    """14 Nov 2026 (owner, R&D ditolak "Buat varian"): centang 'Master Produk RnD (Kategori, Varian, …)' meloloskan
    layanan varian; centang modul Produksi tetap berlaku; tanpa centang aksi yang sama tetap ditolak."""
    rnd = ["rnd"]
    assert run(gate.evaluate(method, path, gerbang("research_development", rnd, [f"mod.rnd_master_product.{aksi}"]))) is None
    assert run(gate.evaluate(method, path, gerbang("research_development", rnd,
                                                   [f"mod.prod_master_product.{aksi}"]))) is None
    lain = "view" if aksi != "view" else "edit"
    assert run(gate.evaluate(method, path, gerbang("research_development", rnd, [f"mod.rnd_master_product.{lain}"])))
    # penjaga di kode (lolos_centang) memakai kunci setara yang sama
    u = U("research_development", f"mod.rnd_master_product.{aksi}", method=method, path=path)
    assert not lolos_centang(u)
    from data.module_catalog import request_keys_setara
    u["_aksi_setara"] = request_keys_setara(method, path)
    assert lolos_centang(u)


def test_rnd_model_tetap_modul_produksi():
    from data.module_catalog import modul_setara
    assert modul_setara("PUT", "/api/rahaza/models/m1") == []           # ubah model: hanya modul Produksi
    assert modul_setara("POST", "/api/rahaza/models") == []
    assert [m["id"] for m in modul_setara("POST", "/api/rahaza/models/m1/variants/generate")] == ["rnd_master_product"]


def test_kasus_5_pic_toko_cutting_dan_nota(masuk):
    import routes.cutting as cut
    import routes.sales_direct as sd
    req = masuk(cut, "pic_toko", ["mod.cut_orders.create"], "POST", "/api/cutting/orders")
    assert run(cut._require_cutting_user(req))
    req = masuk(sd, "Host Live", ["mod.sales_direct.create"], "POST", "/api/sales/direct-sales")
    assert run(sd._require_write(req))
    req = masuk(sd, "Host Live", [], "POST", "/api/sales/direct-sales")
    with pytest.raises(HTTPException):
        run(sd._require_write(req))


def test_gerbang_tanpa_aturan_lama_per_portal(gerbang):
    # Dulu: peran tanpa satu pun centang mod.* di Portal Gudang lolos gerbang (aturan lama). Kini wajib dicentang.
    d = run(gate.evaluate("POST", "/api/rahaza/material-adjust", gerbang("tim_packing", ["warehouse"], ["warehouse.manage"])))
    assert d is not None and d[2] == "perm"
    assert run(gate.evaluate("GET", "/api/rahaza/models", gerbang("tim_packing", ["warehouse"], []))) is None  # data acuan
    assert run(gate.evaluate("POST", "/api/rahaza/leaves/request", gerbang("tim_packing", [], []))) is None   # Portal Saya


# ═══════════════════════════ migrasi: centang = akses sekarang ═══════════════════════════
def _migrasi():
    path = BACKEND / "scripts" / "migrations" / "2026_11_13_centang_akses_penuh.py"
    spec = importlib.util.spec_from_file_location("centang_akses_penuh", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_kasus_6_admin_produksi_tanpa_portal_dicentangkan_setara_izin_lama():
    baru, cat = _migrasi().usulan("admin_produksi", [], ["production.view", "production.manage", "bom.view",
                                                         "bom.manage", "cutting.view", "maklon.view"])
    portals = {k.split(".")[1] for k in baru}
    assert {MODULE_BY_ID[m]["portal"] for m in portals} >= {"production", "cutting", "maklon"}
    assert "mod.prod_master_product.approve" in baru            # perbaikan massal BOM: dulu boleh (kode peran)
    assert any(c.startswith("A portal production") for c in cat)


def test_migrasi_hanya_menambah_dan_tidak_menyentuh_portal_yang_sudah_diatur():
    m = _migrasi()
    punya = ["mod.wh_stock.view", "mod.wh_stock.approve"]
    baru, _ = m.usulan("Koordinator Packing", ["warehouse", "self", "collaboration"], punya)
    assert not set(baru) & set(punya)
    # portal Gudang sudah diatur per modul: modul lamanya tidak disentuh; hanya modul baru Opname disalin dari Stok
    assert {k for k in baru if MODULE_BY_ID[k.split(".")[1]]["portal"] == "warehouse"} == {"mod.wh_opname.view"}


def test_migrasi_master_toko_dan_pencairan_untuk_yang_dulu_boleh():
    m = _migrasi()
    assert {"mod.mkt_accounts.create", "mod.mkt_accounts.edit", "mod.mkt_accounts.delete"} <= set(
        m.usulan("manager_marketing", ["toko"], ["mod.mkt_accounts.view"])[0])
    assert not [k for k in m.usulan("pic_toko", ["toko"], ["mod.mkt_accounts.view"])[0] if "mkt_accounts" in k]


def test_migrasi_opname_salin_hak_lama_kecuali_keputusan_owner():
    m = _migrasi()
    stok = [f"mod.wh_stock.{a}" for a in ("view", "create", "edit", "delete", "approve", "export")]
    kp, _ = m.usulan("Koordinator Packing", ["warehouse"], stok + ["warehouse.approve", "warehouse.manage"])
    assert {"mod.wh_opname.view", "mod.wh_opname.create", "mod.wh_opname.edit"} <= set(kp)
    assert "mod.wh_opname.approve" not in kp                       # owner: "nanti dulu"
    spv, _ = m.usulan("spv_cuting", ["cutting", "warehouse"], stok + ["wh.opname.approve", "wh.opname.manage"])
    assert "mod.wh_opname.approve" in spv                          # dulu boleh, tetap boleh (kini terlihat di layar)
    opc, _ = m.usulan("Operator Cutting", ["warehouse", "cutting"], ["mod.wh_stock.view", "wh.opname.approve"])
    assert "mod.wh_opname.approve" not in opc and "mod.wh_opname.view" in opc   # gerbang dulu menolak Setujui
    assert "mod.fin_pencairan.approve" in m.usulan("Finance & Purchase", ["finance"], ["finance.manage",
                                                                                        "mod.fin_ar.view"])[0]
    assert "mod.fin_pencairan.approve" not in m.usulan("HR Generalist", ["hr"], ["hr.manage"])[0]
