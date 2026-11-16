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
        return list(ROLE_PORTALS.get(role, [])), []

    monkeypatch.setattr(gate, "_load_live_user", live)
    monkeypatch.setattr(gate, "_load_rbac", rbac)
    monkeypatch.setattr(gate, "_load_portal_config", portals)

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
    # 13 Nov 2026: centang = satu-satunya penentu. Layar pintasan lintas portal boleh menulis BILA aksi modul
    # pemiliknya dicentang (dulu: lolos tanpa centang selama portal pemiliknya belum diatur per modul).
    from data.module_catalog import request_key
    assert _denied(method, path, as_role(role)) is not None              # tanpa centang → ditolak
    assert _denied(method, path, as_role(role, perms=[request_key(method, path)])) is None


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


# ── 16 Nov 2026: SEMUA panggilan layar Portal Saya + halaman Absen dibaca langsung dari kode layar ──────────────
# Layar owner: Portal Saya › Cuti & Lembur "Jenis izin/cuti" kosong untuk Host Live — GET /api/rahaza/leave-types
# ditolak gerbang (milik modul SDM) sehingga Promise.all gagal dan daftar cuti/saldo ikut kosong. Uji di atas hanya
# memuat daftar tangan; uji ini memindai berkas layar supaya panggilan baru yang ditolak gerbang langsung merah.
import re  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FE_SRC = os.path.join(REPO, "frontend", "src")
LAYAR_PORTAL_SAYA = [
    "components/erp/PortalSayaAbsen.jsx", "components/erp/PortalSayaCuti.jsx",
    "components/erp/PortalSayaDashboard.jsx", "components/erp/PortalSayaNotifikasi.jsx",
    "components/erp/PortalSayaPayslip.jsx", "components/erp/PortalSayaProfile.jsx",
    "components/erp/PortalSayaTraining.jsx", "components/erp/SelfServicePortal.jsx", "pages/AbsenPage.jsx",
]
# Path yang tidak diperiksa gerbang modul (login belum ber-token).
BUKAN_GERBANG = ("/api/auth/",)


def _panggilan_layar(rel):
    """[(METHOD, path)] dari satu berkas layar: `${...}` → x, query dibuang, komentar diabaikan."""
    teks = open(os.path.join(FE_SRC, rel), encoding="utf-8").read()
    # komentar blok hanya yang diawali di awal baris / `{/* … */}` (bukan `accept="image/*"`), lalu komentar baris
    teks = re.sub(r"(?ms)^\s*/\*.*?\*/", "", teks)
    teks = re.sub(r"\{/\*.*?\*/\}", "", teks, flags=re.S)
    teks = re.sub(r"(?m)^\s*//.*$", "", teks)
    hasil = []
    for m in re.finditer(r"[`'\"](?:\$\{[A-Z_]+\})?(/api/[^`'\"?\s]*)", teks):
        path = re.sub(r"\$\{[^}]*\}", "x", m.group(1)).rstrip("/")
        if not path or path.startswith(BUKAN_GERBANG):
            continue
        sebelum = teks[max(0, m.start() - 40):m.start()].rstrip()
        sesudah = teks[m.end():m.end() + 160].split(")")[0]
        cocok = re.search(r"axios\.(get|post|put|patch|delete)\s*\($", sebelum)
        if cocok:
            method = cocok.group(1).upper()
        else:
            mm = re.search(r"method:\s*['\"]([A-Z]+)['\"]", sesudah)
            method = mm.group(1) if mm else "GET"
            # alamat disimpan di variabel dulu (`const url = cond ? `…` : `…`; axios.post(url, …)`)
            var = re.search(r"(?:const|let)\s+(\w+)\s*=[^;]*$", teks[max(0, m.start() - 200):m.start()])
            mv = var and re.search(r"axios\.(get|post|put|patch|delete)\s*\(\s*" + re.escape(var.group(1)) + r"[\s,)]",
                                   teks[m.end():m.end() + 800])
            if mv:
                method = mv.group(1).upper()
        hasil.append((method, path))
    return hasil


@pytest.mark.skipif(not os.path.isdir(FE_SRC), reason="frontend tidak tersedia")
def test_pemindai_layar_menemukan_panggilan_portal_saya():
    semua = {c for rel in LAYAR_PORTAL_SAYA for c in _panggilan_layar(rel)}
    # contoh yang wajib terbaca (pemindai tidak boleh diam-diam kosong)
    for c in [("GET", "/api/rahaza/leave-types"), ("GET", "/api/rahaza/overtime"),
              ("POST", "/api/rahaza/attendance/webauthn/clock-in"), ("DELETE", "/api/rahaza/overtime/x"),
              ("PUT", "/api/portal/profile"), ("POST", "/api/rahaza/leaves/upload-document"),
              ("GET", "/api/rahaza/payslips/x/pdf")]:
        assert c in semua, c
    assert len(semua) >= 35


@pytest.mark.skipif(not os.path.isdir(FE_SRC), reason="frontend tidak tersedia")
@pytest.mark.parametrize("perms", [(), ("mod.marketing_dashboard.view",)], ids=["tanpa-centang", "centang-lain"])
@pytest.mark.parametrize("role", sorted(ROLE_PORTALS))
def test_semua_panggilan_layar_portal_saya_lolos_gerbang(as_role, role, perms):
    ditolak = []
    for rel in LAYAR_PORTAL_SAYA:
        for method, path in _panggilan_layar(rel):
            r = _denied(method, path, as_role(role, perms=perms))
            if r is not None:
                ditolak.append(f"{rel}: {method} {path} → {r[0]['id']}.{r[1]} ({r[2]})")
    assert not ditolak, "Panggilan Portal Saya ditolak gerbang:\n" + "\n".join(ditolak)


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/rahaza/leave-types/lt-1/extra"), ("POST", "/api/rahaza/leave-types"),
    ("PUT", "/api/rahaza/overtime/ot-1"), ("POST", "/api/rahaza/overtime/ot-1/approve"),
    ("GET", "/api/rahaza/attendance/corrections"), ("GET", "/api/rahaza/attendance/webauthn/devices"),
    ("DELETE", "/api/rahaza/attendance/webauthn/devices/d-1"),
])
def test_swalayan_baru_tidak_membuka_aksi_sdm_lain(method, path):
    assert not is_self_service(method, path)
