"""Pemeriksa akses lintas lapisan + layanan ikut terbuka otomatis (owner 14 Nov 2026).

Owner: "bisakah dibuatkan sehingga otomatis cek lapisan yang lain untuk semua akses role" lalu "saya tidak ingin ada
seperti ini dimanapun di setiap role … apa yang harus di ceklis di portal lain ikut juga". Tiga kasus nyata hari itu:
  1. R&D: Master Produk RnD › Buat varian → layanan modul Produksi `prod_master_product`.
  2. PIC toko: Dashboard Marketing / Target & Anggaran → siklus Portal Manajemen `mgmt_marketing_cycle`.
  3. PIC toko: Kelola Akun › Saldo platform → Keuangan `fin_marketplace`.
Arah balik: Laporan Marketing › "Input biaya iklan" (modul iklan) tampil bila peran punya centang modul iklan.
Hermetik: tanpa Mongo. Peta menu → layanan yang dipakai = berkas nyata `backend/data/peta_menu_layanan.json`.
"""
from __future__ import annotations

import asyncio
import json
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

import data.module_catalog as mc  # noqa: E402
import middleware.module_permission_gate as gate  # noqa: E402
from core import cek_akses  # noqa: E402
from routes.shared import lolos_centang  # noqa: E402

RND_PENUH = [f"mod.rnd_master_product.{a}" for a in mc.MODULE_BY_ID["rnd_master_product"]["actions"]]
PIC_TOKO = ["mod.mkt_dashboard.view", "mod.mkt_targets.view"]


def run(coro):
    return asyncio.run(coro)


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


@pytest.fixture
def tanpa_setara(monkeypatch):
    """Keadaan SEBELUM perbaikan 14 Nov: MODUL_SETARA kasus R&D & Marketing dicabut, layanan ikut-otomatis mati."""
    cabut = ("rnd_master_product", "mkt_targets", "mgmt_marketing_cycle")
    monkeypatch.setattr(mc, "_MODUL_SETARA_RX", [(rx, m) for rx, m in mc._MODUL_SETARA_RX if m["id"] not in cabut])
    monkeypatch.setattr(mc, "_OTOMATIS_INDEKS", {})


@pytest.fixture
def peta_tiruan():
    asli = {m: [list(x) for x in v] for m, v in mc._PETA.items()}

    def _pasang(peta):
        mc.pasang_peta(peta)
    yield _pasang
    mc.pasang_peta(asli)


def _temuan(hasil, jenis=None, layanan=None, menu=None):
    return [t for t in hasil["temuan"] if (jenis is None or t["jenis"] == jenis)
            and (layanan is None or t["layanan"] == layanan) and (menu is None or t["menu"] == menu)]


# ═══════════════════════ peta menu → layanan (berkas nyata dari kode layar) ═══════════════════════
def test_peta_memuat_kasus_nyata():
    assert ["POST", "/api/rahaza/models/x/variants/generate"] in [list(x) for x in mc.layanan_menu("rnd-master-product-hub")]
    for menu in ("toko-dashboard", "marketing-targets"):
        assert ("GET", "/api/marketing/cycle/overview") in mc.layanan_menu(menu), menu
    assert ("GET", "/api/marketing/settlements/platform-balance") in mc.layanan_menu("marketing-accounts")
    assert ("POST", "/api/marketing/ads/campaigns") in mc.layanan_menu("marketing-reports")
    label = cek_akses.label_menu()
    assert label["marketing-accounts"]["label"] and "toko" in label["marketing-accounts"]["portal"]


def test_peta_hilang_atau_rusak_tidak_menjatuhkan(monkeypatch, tmp_path):
    monkeypatch.setattr(mc, "_PETA_PATH", str(tmp_path / "tidak-ada.json"))
    assert mc._muat_peta() == {}
    rusak = tmp_path / "rusak.json"
    rusak.write_text("{ini bukan json", encoding="utf-8")
    monkeypatch.setattr(mc, "_PETA_PATH", str(rusak))
    assert mc._muat_peta() == {}
    aneh = tmp_path / "aneh.json"
    aneh.write_text(json.dumps({"m": [["GET", "/api/x/y"], ["GET"], "z", ["POST", "bukan-api"]]}), encoding="utf-8")
    monkeypatch.setattr(mc, "_PETA_PATH", str(aneh))
    assert mc._muat_peta() == {"m": [("GET", "/api/x/y")]}


# ═══════════════════════ pemeriksa: pola bug terdeteksi bila setara dicabut ═══════════════════════
def test_kasus_rnd_terdeteksi_kuat_bila_setara_dicabut(tanpa_setara):
    h = cek_akses.periksa(RND_PENUH, ["rnd"], "research_development")
    t = _temuan(h, "kuat", "/api/rahaza/models/x/variants/generate", "rnd-master-product-hub")
    assert t and t[0]["butuh_modul"] == "prod_master_product" and t[0]["butuh_aksi"] == "create"
    assert t[0]["kunci"] == "mod.prod_master_product.create" and t[0]["alasan"] == "centang"
    assert t[0]["label_modul"] == "Master Produk (Model & Varian)" and t[0]["label_portal_modul"] == "Produksi"


def test_kasus_marketing_terdeteksi_kuat_bila_setara_dicabut(tanpa_setara):
    h = cek_akses.periksa(PIC_TOKO, ["toko"], "pic_toko")
    for menu in ("toko-dashboard", "marketing-targets"):
        t = _temuan(h, "kuat", "/api/marketing/cycle/overview", menu)
        assert t and t[0]["kunci"] == "mod.mgmt_marketing_cycle.view", menu


def test_kasus_nyata_tidak_terdeteksi_dengan_setara_sekarang(monkeypatch):
    # Hanya MODUL_SETARA manual (tanpa ikut-otomatis): dua kasus nyata sudah tertutup.
    monkeypatch.setattr(mc, "_OTOMATIS_INDEKS", {})
    h = cek_akses.periksa(RND_PENUH, ["rnd"], "research_development")
    assert not _temuan(h, layanan="/api/rahaza/models/x/variants/generate")
    h = cek_akses.periksa(PIC_TOKO, ["toko"], "pic_toko")
    assert not _temuan(h, layanan="/api/marketing/cycle/overview", menu="marketing-targets")


def test_dengan_ikut_otomatis_temuan_kuat_nol_dan_dijelaskan():
    h = cek_akses.periksa(PIC_TOKO + ["mod.mkt_accounts.view"], ["toko"], "pic_toko")
    assert h["jumlah"]["kuat"] == 0 and not _temuan(h, layanan="/api/marketing/cycle/overview")
    o = [x for x in h["otomatis"] if x["layanan"] == "/api/marketing/settlements/platform-balance"]
    assert o and o[0]["butuh_modul"] == "fin_marketplace" and o[0]["lewat_modul"] == ["mkt_accounts"]
    assert o[0]["label_menu"] and o[0]["label_aksi"] == "Lihat"
    # Laporan Marketing: tombol iklan butuh centang modul iklan (modul laporan tidak punya aksi Tambah) → informasi
    t = _temuan(h, "informasi", "/api/marketing/ads/campaigns", "marketing-reports")
    assert t and t[0]["metode"] == "POST" and t[0]["kunci"] == "mod.mkt_content.create"
    assert cek_akses.periksa(["*"])["temuan"] == [] and cek_akses.periksa(["x"], role_name="owner")["temuan"] == []


def test_kotak_centang_sendiri_bukan_temuan_kuat():
    h = cek_akses.periksa(RND_PENUH, ["rnd"], "research_development")
    assert h["jumlah"]["kuat"] == 0
    t = _temuan(h, "terpisah", "/api/rahaza/models/x")
    assert t and "Produksi" in t[0]["sebab"]


# ═══════════════════════ gerbang: layanan ikut terbuka otomatis ═══════════════════════
def test_kelola_akun_saldo_platform_lolos_dengan_centang_kelola_akun(gerbang):
    p = "/api/marketing/settlements/platform-balance"
    assert run(gate.evaluate("GET", p, gerbang("pic_toko", ["toko"], ["mod.mkt_accounts.view"]))) is None
    d = run(gate.evaluate("GET", p, gerbang("pic_toko", ["toko"], ["mod.mkt_dashboard.view"])))
    assert d and d[0]["id"] == "fin_marketplace" and d[2] == "perm"
    # penjaga di kode (lolos_centang) memakai kunci setara yang sama
    u = {"role": "pic_toko", "_permissions": ["mod.mkt_accounts.view"], "_aksi_request": mc.request_key("GET", p),
         "_aksi_setara": mc.request_keys_setara("GET", p)}
    assert lolos_centang(u)


def test_dashboard_marketing_semua_layanan_lolos_dengan_centang_dashboard(gerbang):
    assert mc.MENU_PEMILIK["toko-dashboard"][0]["id"] == "mkt_dashboard"
    layanan = mc.layanan_menu("toko-dashboard")
    for bagian in ("/cycle/", "/ads/", "/budget/", "/targets", "/livehost", "/kol/"):
        assert any(bagian in p for _, p in layanan), bagian
    for method, path in layanan:
        contoh = path.replace("/x/", "/a1/")
        assert run(gate.evaluate(method, contoh, gerbang("pic_toko", ["toko"], ["mod.mkt_dashboard.view"]))) is None, path


@pytest.mark.parametrize("method,path,aksi", [
    ("POST", "/api/rahaza/models/m1/variants/generate", "create"),
    ("GET", "/api/rahaza/models/m1/variants", "view"),
    ("PUT", "/api/rahaza/variants/v1", "edit"),
])
def test_varian_rnd_tetap_lolos(gerbang, method, path, aksi):
    assert run(gate.evaluate(method, path, gerbang("research_development", ["rnd"],
                                                   [f"mod.rnd_master_product.{aksi}"]))) is None


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/marketing/settlements"),            # modul Marketplace, tetapi TIDAK dipanggil layar Kelola Akun
    ("GET", "/api/marketing/withdrawals"),
    ("GET", "/api/rahaza/hpp/p1"),                    # modul lain sama sekali
    ("POST", "/api/marketing/settlements/platform-balance"),   # aksi tulis tidak dipanggil layar
])
def test_layanan_yang_tidak_dipanggil_layar_tetap_ditolak(gerbang, method, path):
    perms = [f"mod.mkt_accounts.{a}" for a in mc.MODULE_BY_ID["mkt_accounts"]["actions"]]
    assert run(gate.evaluate(method, path, gerbang("pic_toko", ["toko"], perms)))


def test_aksi_tulis_butuh_centang_tulis_yang_sama(gerbang):
    # Layar Target & Anggaran (mkt_targets) memanggil kunci periode (modul Input Sales, aksi Setujui).
    assert ("POST", "/api/marketing/periods/lock") in mc.layanan_menu("marketing-targets")
    p = "/api/marketing/periods/lock"
    assert run(gate.evaluate("POST", p, gerbang("pic_toko", ["toko"], ["mod.mkt_targets.view"])))
    assert run(gate.evaluate("POST", p, gerbang("pic_toko", ["toko"], ["mod.mkt_targets.view", "mod.mkt_targets.edit"])))
    assert run(gate.evaluate("POST", p, gerbang("pic_toko", ["toko"], ["mod.mkt_targets.approve"]))) is None


def test_aksi_tulis_peta_tiruan(gerbang, peta_tiruan):
    peta_tiruan({"marketing-accounts": [["GET", "/api/marketing/withdrawals/x"], ["POST", "/api/marketing/withdrawals"]]})
    perms = ["mod.mkt_accounts.view"]
    assert run(gate.evaluate("GET", "/api/marketing/withdrawals/w9", gerbang("pic_toko", ["toko"], perms))) is None
    assert run(gate.evaluate("POST", "/api/marketing/withdrawals", gerbang("pic_toko", ["toko"], perms)))
    assert run(gate.evaluate("POST", "/api/marketing/withdrawals",
                             gerbang("pic_toko", ["toko"], perms + ["mod.mkt_accounts.create"]))) is None
    # segmen generik `x` hanya mewakili SATU segmen
    assert run(gate.evaluate("GET", "/api/marketing/withdrawals/w9/detail", gerbang("pic_toko", ["toko"], perms)))


def test_kotak_centang_sendiri_tidak_ikut_otomatis(gerbang, peta_tiruan):
    peta_tiruan({"hr-expense-hub": [["POST", "/api/hr/expenses/claims/x/disburse"]],
                 "hr-employees": [["GET", "/api/rahaza/payroll-profiles"]],
                 "rnd-master-product-hub": [["PUT", "/api/rahaza/models/x"]]})
    # K25: uang keluar tidak pernah terbuka dari centang SDM
    assert run(gate.evaluate("POST", "/api/hr/expenses/claims/c1/disburse",
                             gerbang("hr", ["hr"], ["mod.hr_expense.view", "mod.hr_expense.approve"])))
    # data gaji dicentang sendiri
    assert run(gate.evaluate("GET", "/api/rahaza/payroll-profiles", gerbang("hr", ["hr"], ["mod.hr_employees.view"])))
    # owner: ubah model tetap mengikuti modul Produksi
    assert run(gate.evaluate("PUT", "/api/rahaza/models/m1",
                             gerbang("research_development", ["rnd"], ["mod.rnd_master_product.edit"])))
    assert mc.modul_setara("PUT", "/api/rahaza/models/m1") == []


# ═══════════════════════ arah balik: aksi efektif menu (tombol layar) ═══════════════════════
def test_laporan_marketing_tombol_iklan_ikut_centang_modul_iklan():
    _, acc = mc.menu_access(["mod.mkt_dashboard.view", "mod.mkt_dashboard.export", "mod.mkt_content.create"])
    assert "create" in acc["marketing-reports"]


def test_aksi_dimiliki_modul_menu_tetap_disembunyikan_kecuali_centang_modul_layanan():
    # Target & Anggaran punya aksi Setujui: tanpa centang Setujui di modul itu tombolnya disembunyikan, KECUALI peran
    # punya Setujui pada modul layanan yang dipanggil layar (kunci periode = modul Input Sales).
    _, acc = mc.menu_access(["mod.mkt_targets.view"])
    assert "approve" not in acc["marketing-targets"]
    _, acc = mc.menu_access(["mod.mkt_targets.view", "mod.mkt_sales.approve"])
    assert "approve" in acc["marketing-targets"]
    # terlihat/tersembunyi tetap mengikuti centang Lihat modul pemilik menu
    hidden, acc = mc.menu_access(["mod.mkt_content.view", "mod.mkt_content.create"])
    assert "marketing-reports" in hidden and "view" not in acc["marketing-reports"]


# ═══════════════════════ API Kontrol Akses ═══════════════════════
def test_api_cek_akses_penjaga_dan_hasil(monkeypatch):
    import routes.admin as admin
    from _fake_mongo import FakeDB, FakeRequest
    db = FakeDB()
    db.roles.docs = [{"id": "r1", "name": "pic_toko", "portals": ["toko"]},
                      {"id": "r2", "name": "research_development", "portals": ["rnd"]}]
    db.role_permissions.docs = [{"role_id": "r1", "permission_key": k} for k in PIC_TOKO] + [
        {"role_id": "r2", "permission_key": k} for k in RND_PENUH]
    monkeypatch.setattr(admin, "get_db", lambda: db)
    pengguna = {"u": {"id": "u1", "role": "pic_toko", "_permissions": []}}

    async def auth(req):
        return dict(pengguna["u"])
    monkeypatch.setattr(admin, "require_auth", auth)
    with pytest.raises(HTTPException) as e:
        run(admin.cek_akses_peran(FakeRequest({"permissions": PIC_TOKO})))
    assert e.value.status_code == 403
    pengguna["u"] = {"id": "u2", "role": "staf_it", "_permissions": ["roles.manage"]}
    h = run(admin.cek_akses_peran(FakeRequest({"permissions": PIC_TOKO + ["bukan.kunci"], "portals": ["toko"],
                                               "role_name": "pic_toko"})))
    assert h["jumlah"]["kuat"] == 0 and h["otomatis"]
    pengguna["u"] = {"id": "u3", "role": "superadmin"}
    items = {r["role_id"]: r for r in run(admin.cek_akses_ringkasan(FakeRequest()))["items"]}
    assert set(items) == {"r1", "r2"} and items["r1"]["kuat"] == 0 and items["r2"]["terpisah"] >= 1


# ═══════════════════════ tombol layar yang dijaga centang modul lain (frontend, 14 Nov 2026) ═══════════════════════
def test_kunci_tombol_layar_sama_dengan_aturan_server():
    """Frontend menyembunyikan tombol ini dengan `punyaCentang(null, kunci)` / `aksiCentang(modul)`; kuncinya HARUS
    sama dengan yang diminta gerbang server, kalau tidak tombol tampil lalu ditolak (atau hilang padahal boleh)."""
    pasang = {
        ("POST", "/api/kirim-cmt/shipments/s1/repost-journal"): "mod.fin_journal.approve",      # KirimanDetail
        ("POST", "/api/kirim-cmt/nota-aksesoris/n1/potong"): "mod.prod_cmt_billing.approve",    # NotaAksesorisKiriman
        ("POST", "/api/rahaza/boms/relink-materials"): "mod.prod_master_product.approve",       # RahazaBOMModuleV2
        ("POST", "/api/dewi/maklon/finance/cmt-payments/b1/resolve-variance"): "mod.mak_billing.approve",
        ("POST", "/api/rahaza/models"): "mod.prod_master_product.create",                       # Tambah model
        ("PUT", "/api/rahaza/models/m1"): "mod.prod_master_product.edit",                       # Ubah model
        ("DELETE", "/api/rahaza/models/m1"): "mod.prod_master_product.delete",                  # Nonaktifkan/Hapus
        ("POST", "/api/wms/opname3/sessions"): "mod.wh_opname.create",                          # tab Opname
    }
    for (method, path), kunci in pasang.items():
        mod, act = mc.resolve(method, path)
        assert mc.perm_key(mod["id"], act) == kunci, (method, path)
    # relink BOM juga lolos lewat Master Produk RnD; opname lewat Opname Aksesoris (aksiCentang memakai keduanya)
    assert "rnd_master_product" in [m["id"] for m in mc.modul_setara("POST", "/api/rahaza/boms/relink-materials")]
    assert "acc_opname" in [m["id"] for m in mc.modul_setara("POST", "/api/wms/opname3/sessions")]
