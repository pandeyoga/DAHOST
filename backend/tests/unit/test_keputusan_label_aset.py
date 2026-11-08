"""Uji keputusan owner 8 Nov 2026 (setelah Standar UI/UX v2) — label menu, aset, dan nama akun.

1. Label menu Indonesia (`portalNav.js`): tidak ada lagi label berisi "Approval"; label Portal Saya diterjemahkan;
   judul layar = label menu (huruf besar hanya di awal); tab Penggajian "Pengaturan gaji".
2. Portal Aset: tombol "Posting penyusutan" (satu aset / massal) yang selalu ditolak server sejak K18 diganti
   tautan ke Keuangan › Aset Tetap (tab Penyusutan); layar tidak lagi memanggil endpoint yang dimatikan.
3. Kotak persetujuan Pengadaan di Portal Aset: Setujui/Tolak memakai endpoint sesuai jenis baris
   (Permintaan Pengadaan · Request Pembelian Aksesoris · Purchase Order) — sama dengan `api_base` dari server.
4. Nama akun 6-3500 & 6-4400: seed berbahasa Indonesia + migrasi pratinjau/tulis yang hanya mengganti nama lama.
Hermetik: Mongo palsu, sumber frontend dibaca sebagai teks.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402

ERP = ("frontend", "src", "components", "erp")


def run(coro):
    return asyncio.run(coro)


def _src(*parts):
    p = REPO.joinpath(*parts)
    if not p.exists():
        pytest.skip(f"sumber frontend tidak tersedia: {p}")
    return p.read_text(encoding="utf-8")


def _tanpa_komentar(js: str) -> str:
    """Kode JS/JSX tanpa komentar blok & baris — yang diuji adalah perilaku/teks layar, bukan catatan sejarah."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(^|\s)//[^\n]*", r"\1", js)


def _mig(name):
    p = BACKEND / "scripts" / "migrations" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mig_{name}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _nav_labels() -> dict:
    """id menu → label (semua portal; id yang muncul di beberapa portal harus berlabel sama)."""
    s = _src(*ERP, "portal-shell", "portalNav.js")
    out: dict = {}
    for mid, label in re.findall(r"\{\s*id:\s*'([^']+)',\s*label:\s*'([^']+)'", s):
        out.setdefault(mid, set()).add(label)
    return out


# ══ 1. Label menu & judul layar ═══════════════════════════════════════════════
LABEL_BARU = {
    "unified-approval-hub": "Pusat Persetujuan",
    "approval-multilevel": "Persetujuan Bertingkat",
    "accessories-inbox": "Inbox Persetujuan",
    "sys-rbac-audit": "Audit Persetujuan & Notifikasi",
    "rnd-kreator-requests": "Persetujuan Kreator",
    "portal-peer-feedback": "Umpan Balik Rekan",
    "portal-career-coach": "Pendamping Karier",
    "portal-annual-review": "Tinjauan Tahunan",
}


def test_label_menu_baru_dan_tanpa_kata_approval():
    s = _src(*ERP, "portal-shell", "portalNav.js")
    labels = _nav_labels()
    for mid, label in LABEL_BARU.items():
        assert labels.get(mid) == {label}, (mid, labels.get(mid))
    semua = re.findall(r"label:\s*'([^']+)'", s)
    assert not [lb for lb in semua if "approval" in lb.lower()], "masih ada label menu berisi 'Approval'"
    for lama in ("Peer Feedback", "Career Coach", "Annual Review"):
        assert f"'{lama}'" not in s


@pytest.mark.parametrize("berkas,judul", [
    (("UnifiedApprovalHub.jsx",), 'title="Pusat persetujuan"'),
    (("MultiLevelApprovalModule.jsx",), 'title="Persetujuan bertingkat"'),
    (("AccessoryRequestInbox.jsx",), "'Inbox persetujuan'"),
    (("RbacAuditModule.jsx",), 'title="Audit persetujuan & notifikasi"'),
    (("KREATORRequestModule.jsx",), "title={isRndScope ? 'Persetujuan kreator'"),
    (("portal", "PeerFeedbackModule.jsx"), 'title="Umpan balik rekan"'),
    (("portal", "CareerCoachModule.jsx"), 'title="Pendamping karier"'),
    (("portal", "MyAnnualReviewModule.jsx"), 'title="Tinjauan tahunan"'),
])
def test_judul_layar_sama_dengan_label_menu(berkas, judul):
    assert judul in _src(*ERP, *berkas)


def test_tab_pengaturan_gaji_dan_rujukan_layar():
    hub = _src(*ERP, "hubs", "HRPayrollHub.jsx")
    assert "label: 'Pengaturan gaji'" in hub and "Pengaturan Payroll'" not in hub
    for berkas in ("PortalSayaCuti.jsx", "RahazaOvertimeModule.jsx", "RahazaProductionCalendarModule.jsx"):
        teks = _tanpa_komentar(_src(*ERP, berkas))
        assert "Pengaturan Payroll" not in teks and "Pengaturan gaji" in teks, berkas


def test_basis_pengetahuan_asisten_memakai_nama_menu_baru():
    import json
    kb = BACKEND / "data" / "portal_kb"
    nama = {f["modul"]: f["nama"] for p in kb.glob("*.json")
            for f in json.loads(p.read_text(encoding="utf-8")).get("fitur", []) if "modul" in f}
    for mid, label in LABEL_BARU.items():
        if mid in nama:
            assert nama[mid] == label, (mid, nama[mid])


# ══ 2. Penyusutan di Portal Aset → tautan ke Keuangan › Aset Tetap ════════════
def test_portal_aset_tidak_lagi_memanggil_endpoint_penyusutan_yang_dimatikan():
    drawer = _src(*ERP, "asset", "drawers", "AssetDetailDrawer.jsx")
    portal = _src(*ERP, "AssetManagementPortal.jsx")
    tab = _src(*ERP, "asset", "tabs", "AssetsTab.jsx")
    for teks in map(_tanpa_komentar, (drawer, portal, tab)):
        assert "/depreciate/" not in teks and "batch-depreciate" not in teks
        assert "Posting penyusutan" not in teks
    konst = _src(*ERP, "asset", "constants.js")
    assert "MENU_PENYUSUTAN = { modul: 'fin-fixed-assets', tab: 'depreciation' }" in konst
    assert "KALIMAT_PENYUSUTAN = 'Penyusutan aset diposting di Keuangan › Aset Tetap" in konst
    # tautan hanya bila pengguna boleh membuka Portal Keuangan; kalimat tetap tampil
    assert "canAccessPortal(user?.role, 'finance')" in portal
    assert "onNavigate(MENU_PENYUSUTAN.modul, { tab: MENU_PENYUSUTAN.tab })" in portal
    assert "{KALIMAT_PENYUSUTAN}" in drawer and "{KALIMAT_PENYUSUTAN}" in tab
    # tujuan tautan benar-benar ada: menu Keuangan + tab Penyusutan di hub Aset Tetap
    assert "{ id: 'fin-fixed-assets'" in _src(*ERP, "portal-shell", "portalNav.js")
    assert "key: 'depreciation'" in _src(*ERP, "hubs", "FinanceAssetsHub.jsx")


def test_endpoint_penyusutan_aset_tetap_ditolak_server_k18():
    """Alasan tombol dihapus: kedua endpoint lama selalu 410 (tidak diubah oleh perubahan ini)."""
    for berkas in ("depreciation_batch.py", "depreciation_per.py"):
        teks = (BACKEND / "routes" / "asset" / berkas).read_text(encoding="utf-8")
        assert "raise HTTPException(410, DEPRECIATION_MOVED_MSG)" in teks


# ══ 3. Kotak persetujuan: endpoint per jenis baris ════════════════════════════
def _basis_frontend() -> dict:
    s = _src(*ERP, "asset", "drawers", "PRDetailDrawer.jsx")
    blok = re.search(r"BASIS_KEPUTUSAN = \{(.*?)\};", s, re.S).group(1)
    return dict(re.findall(r"(\w+):\s*'([^']+)'", blok))


def test_basis_keputusan_sama_dengan_api_base_server():
    from core.pr_approval import normalize_acc_pr, normalize_po
    basis = _basis_frontend()
    assert basis["pr"] == "/api/procurement/requests"
    assert basis["acc_pr"] == normalize_acc_pr({})["api_base"] == "/api/acc/purchase-requests"
    assert basis["po"] == normalize_po({})["api_base"] == "/api/rahaza/purchase-orders"


def test_setujui_tolak_memakai_basis_per_jenis():
    s = _src(*ERP, "asset", "drawers", "PRDetailDrawer.jsx")
    assert "`${basisKeputusan(pr)}/${pr.id}/${endpoint}`" in s
    assert "/api/procurement/requests/${pr.id}" not in s
    # Ajukan/Batalkan hanya untuk Permintaan Pengadaan (jenis lain tidak punya endpoint itu)
    assert "const canSubmit = jenisPengadaan &&" in s and "const canCancel = jenisPengadaan &&" in s


@pytest.mark.parametrize("berkas,awalan", [
    ("dewi_accessories_purchase.py", '@router.post("/purchase-requests/{pr_id}/'),
    ("rahaza_po.py", '@router.post("/purchase-orders/{po_id}/'),
    ("dewi_procurement.py", '@router.post("/requests/{req_id}/'),
])
def test_endpoint_tujuan_ada_dan_memeriksa_hak(berkas, awalan):
    teks = (BACKEND / "routes" / berkas).read_text(encoding="utf-8")
    for aksi in ("approve", "reject"):
        i = teks.find(f'{awalan}{aksi}")')
        assert i >= 0, (berkas, aksi)
        badan = teks[i:i + 2500]
        assert "require_auth(request)" in badan, (berkas, aksi)
        assert f'ev["can_{aksi}"]' in badan, (berkas, aksi)        # hak dari eval_approval (SSOT)


# ══ 4. Nama akun 6-3500 & 6-4400 ══════════════════════════════════════════════
MIG = "2026_11_08_nama_akun_indonesia"


def test_seed_bagan_akun_dan_pemetaan_memakai_nama_baru():
    from routes.rahaza_coa import SEED_TEMPLATE
    from routes.employee_expense_gl_mapping import DEFAULT_GL_SEED
    mig = _mig(MIG)
    seed = {c: n for c, n, *_ in SEED_TEMPLATE}
    for code, (lama, baru) in mig.GANTI_NAMA.items():
        assert seed[code] == baru
        assert lama not in seed.values()
    assert {n for c, n in DEFAULT_GL_SEED.values() if c == "6-3500"} == {"Biaya Penggantian Klaim Karyawan"}
    assert not re.search(r"[Rr]eimbursement|Bad Debt", "".join(mig.GANTI_NAMA[c][1] for c in mig.GANTI_NAMA))


def _db():
    db = FakeDB()
    db.rahaza_coa_accounts.docs += [
        {"id": "a1", "code": "6-3500", "name": "Biaya Reimbursement Karyawan", "type": "EXPENSE"},
        {"id": "a2", "code": "6-4400", "name": "Beban Kerugian Piutang (Bad Debt Expense)", "type": "EXPENSE"},
        {"id": "a3", "code": "6-3400", "name": "Biaya Perjalanan Dinas", "type": "EXPENSE"},
    ]
    db.employee_expense_gl_mappings.docs += [
        {"id": "m1", "category": "Konsumsi / Makan", "gl_account_code": "6-3500",
         "gl_account_name": "Biaya Reimbursement Karyawan"},
        {"id": "m2", "category": "Biaya Kesehatan", "gl_account_code": "6-3500", "gl_account_name": "Klaim Kesehatan"},
    ]
    return db


def test_migrasi_pratinjau_tidak_menulis(capsys):
    mig = _mig(MIG)
    db = _db()
    out = run(mig.run(db, apply=False))
    assert out["akun"]["6-3500"]["perlu"] == 1 and out["akun"]["6-4400"]["perlu"] == 1
    assert out["pemetaan_gl"]["6-3500"]["perlu"] == 1 and out["diganti"] == 0
    names = {d["code"]: d["name"] for d in db.rahaza_coa_accounts.docs}
    assert names["6-3500"] == "Biaya Reimbursement Karyawan"
    assert "PRATINJAU" in capsys.readouterr().out


def test_migrasi_tulis_hanya_nama_lama_lalu_idempoten():
    mig = _mig(MIG)
    db = _db()
    out = run(mig.run(db, apply=True))
    assert out["diganti"] == 2 and out["pemetaan_diganti"] == 1
    names = {d["code"]: d["name"] for d in db.rahaza_coa_accounts.docs}
    assert names == {"6-3500": "Biaya Penggantian Klaim Karyawan", "6-4400": "Beban Kerugian Piutang Tak Tertagih",
                     "6-3400": "Biaya Perjalanan Dinas"}
    maps = {d["id"]: d["gl_account_name"] for d in db.employee_expense_gl_mappings.docs}
    assert maps == {"m1": "Biaya Penggantian Klaim Karyawan", "m2": "Klaim Kesehatan"}   # nama buatan pengguna tetap
    lagi = run(mig.run(db, apply=True))
    assert lagi["diganti"] == 0 and lagi["pemetaan_diganti"] == 0
    assert lagi["akun"]["6-3500"]["sudah"] == 1


def test_migrasi_tidak_menyentuh_nama_yang_sudah_diubah_pengguna():
    mig = _mig(MIG)
    db = FakeDB()
    db.rahaza_coa_accounts.docs.append({"id": "a1", "code": "6-4400", "name": "Beban Piutang Macet"})
    out = run(mig.run(db, apply=True))
    assert out["diganti"] == 0 and out["akun"]["6-4400"]["nama_lain"] == ["Beban Piutang Macet"]
    assert db.rahaza_coa_accounts.docs[0]["name"] == "Beban Piutang Macet"
    assert out["akun"]["6-3500"] == {"perlu": 0, "sudah": 0, "nama_lain": [], "diganti": 0}
