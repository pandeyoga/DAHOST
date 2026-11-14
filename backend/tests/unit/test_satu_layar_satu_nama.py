"""Keputusan owner 8 Nov 2026: satu layar = satu nama di mana pun.

Label menu (`portalNav.js`), judul layar (sentence case dari label menu), nama modul di Kontrol Akses
(`data/module_catalog.py`), panduan pengguna, dan basis pengetahuan Asisten AI (`data/portal_kb/*.json`)
memakai nama yang sama. Kata aksi di Kontrol Akses = kata tombol di layar (Setujui, Unduh).
Hermetik: hanya membaca berkas sumber.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from data import module_catalog as mc  # noqa: E402

ERP = BACKEND.parent / "frontend" / "src" / "components" / "erp"
NAV = ERP / "portal-shell" / "portalNav.js"


def _src(*parts) -> str:
    return (ERP.joinpath(*parts)).read_text(encoding="utf-8")


def _nav_per_portal() -> dict:
    """portal → {id menu: label} dari blok `PORTAL_NAV` (urutan kunci portal di berkas)."""
    s = NAV.read_text(encoding="utf-8")
    s = s[s.index("export const PORTAL_NAV = {"):]
    out, portal = {}, None
    for line in s.splitlines():
        m = re.match(r"^  ([a-z]+): \{", line)
        if m:
            portal = m.group(1)
            out[portal] = {}
            continue
        if portal:
            for mid, label in re.findall(r"\{\s*id:\s*'([^']+)',\s*label:\s*'([^']+)'", line):
                out[portal][mid] = label
        if line == "};":
            break
    return out


def _label_by_id() -> dict:
    out: dict = {}
    for menus in _nav_per_portal().values():
        for mid, label in menus.items():
            out.setdefault(mid, set()).add(label)
    return out


# ══ 1. Label menu ═════════════════════════════════════════════════════════════
LABEL_BARU = {
    ("accessories", "accessories-dashboard"): "Dashboard Aksesoris",
    ("production", "production-dashboard"): "Dashboard Produksi",
    ("maklon", "maklon-dashboard"): "Dashboard Maklon",
    ("management", "rnd-dashboard"): "Dashboard RnD",
    ("rnd", "rnd-dashboard"): "Dashboard RnD",
    ("sysadmin", "maklon-notifications"): "Notifikasi",
    ("toko", "maklon-notifications"): "Notifikasi",
    ("management", "mgmt-marketing-cycle"): "Target & Anggaran",
    ("toko", "marketing-targets"): "Target & Anggaran",
    ("management", "mgmt-marketing-change-log"): "Jejak Marketing",
    ("toko", "marketing-change-log"): "Jejak Marketing",
    ("production", "prod-master-product-hub"): "Master Produk",
    ("rnd", "rnd-master-product-hub"): "Master Produk",
}


def test_label_menu_baru():
    nav = _nav_per_portal()
    for (portal, mid), label in LABEL_BARU.items():
        assert nav[portal][mid] == label, (portal, mid, nav[portal].get(mid))


def test_label_baru_lolos_aturan_nama_menu():
    """Aturan gerbang INV-NAV-01 (≤ 3 kata bermakna, tanpa tanda kurung, bukan HURUF BESAR SEMUA)."""
    import importlib.util
    path = BACKEND.parent / "scripts" / "guardrails" / "check_nav_map.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("_cek_nav_map", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for label in set(LABEL_BARU.values()):
        assert mod.label_problems(label) == [], label


def test_satu_id_menu_satu_label_di_semua_portal():
    ganda = {mid: labels for mid, labels in _label_by_id().items() if len(labels) > 1}
    assert not ganda, ganda


def test_tidak_ada_lagi_label_dashboard_polos_di_portal_kerja():
    nav = _nav_per_portal()
    polos = [(p, mid) for p, menus in nav.items() for mid, lb in menus.items() if lb == "Dashboard" and p != "self"]
    assert not polos, polos
    lama = {"Ringkasan RnD", "Siklus Marketing", "Target & Budget", "Jejak Perubahan", "Notifikasi Maklon"}
    assert not lama & {lb for labels in _label_by_id().values() for lb in labels}


# ══ 2. Judul layar = label menu (sentence case) ═══════════════════════════════
@pytest.mark.parametrize("berkas,judul", [
    (("RahazaFGValuationModule.jsx",), 'title="Nilai persediaan"'),
    (("MaklonBillingModule.jsx",), 'title="Piutang klien"'),
    (("ProductionCMTBillingModule.jsx",), 'title="Tagihan CMT"'),
    (("CMTPermakModule.jsx",), 'title="Perbaikan"'),
    (("engine", "ProductionPOModule.jsx"), "title={isInternal ? 'PO internal' : 'PO maklon'}"),
    (("RnDPortalDashboard.jsx",), 'title="Dashboard RnD"'),
    (("marketing", "MarketingChangeLogModule.jsx"), 'title="Jejak marketing"'),
    (("marketing", "AccountTargetsModule.jsx"), 'title="Target & anggaran"'),
    (("WMSModule.jsx",), 'title="Audit trail"'),
    (("AccessoriesDashboard.jsx",), 'title="Dashboard aksesoris"'),
    (("AnnouncementModule.jsx",), 'title="Papan pengumuman"'),
    (("moduleRegistry.js",), "headerTitle: 'Request aksesoris',"),
])
def test_judul_layar_sama_dengan_label_menu(berkas, judul):
    assert judul in _src(*berkas)


def test_judul_lama_tidak_tersisa():
    for berkas, lama in ((("RahazaFGValuationModule.jsx",), 'title="Nilai Persediaan Barang Jadi"'),
                         (("ProductionCMTBillingModule.jsx",), 'title="Tagihan vendor CMT"'),
                         (("CMTPermakModule.jsx",), "Perbaikan (permak)"),
                         (("engine", "ProductionPOModule.jsx"), "'PO Produksi Internal'"),
                         (("marketing", "AccountTargetsModule.jsx"), "Siklus target, anggaran & omzet"),
                         (("marketing", "MarketingChangeLogModule.jsx"), "Jejak perubahan marketing"),
                         (("WMSModule.jsx",), "Audit trail gudang"),
                         (("moduleRegistry.js",), "Request Pembelian Aksesoris")):
        assert lama not in _src(*berkas), (berkas, lama)


# ══ 3. Kontrol Akses ═════════════════════════════════════════════════════════
def test_label_aksi_sama_dengan_kata_tombol_kunci_tetap():
    assert mc.ACTIONS == ("view", "create", "edit", "delete", "approve", "export")
    assert mc.ACTION_LABELS == {"view": "Lihat", "create": "Tambah", "edit": "Ubah", "delete": "Hapus",
                                "approve": "Setujui", "export": "Unduh"}
    assert mc.perm_key("prod_po", "approve") == "mod.prod_po.approve"
    assert "mod.wh_audit.export" in mc.all_granular_keys()
    deskripsi = [p["description"] for m in mc.grouped_modules("production") for p in m["perms"]]
    assert "Setujui — PO Internal & Tutup PO" in deskripsi
    assert not [d for d in deskripsi if d.startswith(("Approve —", "Export —"))]
    for berkas in (("portal-shell", "ModuleAccessBadge.jsx"), ("GranularModuleRow.jsx",), ("AccessSyncModule.jsx",)):
        teks = _src(*berkas)
        assert "approve: 'Setujui'" in teks and "export: 'Unduh'" in teks, berkas
        assert "'Approve'" not in teks and "'Export'" not in teks, berkas


@pytest.mark.parametrize("mid,label", [
    ("prod_jobs", "Pantau Produksi"),
    ("prod_variance", "Laporan Selisih"),
    ("rnd_samples", "Sample Request & Persetujuan Sample"),
    ("wh_fulfillment", "Pemenuhan Pesanan & Daftar Ambil"),
    ("mgmt_marketing_cycle", "Target & Anggaran"),
    ("mkt_targets", "Target & Anggaran"),
    ("mkt_changelog", "Jejak Marketing"),
    ("prod_po", "PO Internal & Tutup PO"),
    ("prod_cmt_billing", "Tagihan CMT"),
    ("prod_cmt_permak", "Perbaikan"),
    ("mak_billing", "Piutang Klien"),
    ("wh_audit", "Audit Trail"),
])
def test_label_modul_akses_memakai_nama_menu(mid, label):
    assert mc.MODULE_BY_ID[mid]["label"] == label


def test_label_modul_tanpa_nama_menu_lama():
    lama = ("Production Jobs", "Variance", "Approval", "Fulfillment", "Pick List", "Siklus Marketing",
            "Jejak Perubahan", "Target & Budget", "Ringkasan RnD", "Notifikasi Maklon", "Invoice CMT")
    salah = [(m["id"], m["label"]) for m in mc.MODULES if any(x in m["label"] for x in lama)]
    assert not salah, salah


def test_semua_menu_portal_granular_punya_modul():
    """`maklon-notifications` (Notifikasi) dulu satu-satunya menu tanpa modul; kini ikut modul Integrasi Marketing."""
    nav = _nav_per_portal()
    tercakup = {menu for m in mc.MODULES for menu in m["menus"]}
    kosong = sorted((p, mid) for p, menus in nav.items() if p in mc.GRANULAR_PORTALS
                    for mid in menus if mid not in tercakup)
    assert not kosong, kosong
    assert "maklon-notifications" in mc.MODULE_BY_ID["mkt_integrations"]["menus"]
    # hanya pintu menu: API notifikasi tetap dijaga handler-nya, tidak masuk gerbang modul Marketing
    assert mc.match_module("/api/dewi/notifications") is None


def test_izin_lihat_integrasi_membuka_menu_notifikasi():
    hidden, access = mc.menu_access(["mod.mkt_integrations.view"])
    assert (set(access["maklon-notifications"]) & set(mc.MODULE_BY_ID[[m["id"] for m in mc.MODULES if "maklon-notifications" in m["menus"]][0]]["actions"])) == {"view"} and "maklon-notifications" not in hidden
    hidden, _ = mc.menu_access(["mod.mkt_dashboard.view"])
    assert "maklon-notifications" in hidden


# ══ 4. Panduan pengguna & basis pengetahuan Asisten AI ═══════════════════════
def test_basis_pengetahuan_memakai_nama_menu_sekarang():
    labels = _label_by_id()
    salah = []
    for p in sorted((BACKEND / "data" / "portal_kb").glob("*.json")):
        for f in json.loads(p.read_text(encoding="utf-8")).get("fitur", []):
            mid = f.get("modul")
            if mid in labels and f["nama"] not in labels[mid]:
                salah.append((p.name, mid, f["nama"], labels[mid]))
    assert not salah, salah


def test_basis_pengetahuan_kata_tombol_sekarang():
    for p in (BACKEND / "data" / "portal_kb").glob("*.json"):
        teks = p.read_text(encoding="utf-8")
        for lama in ("Approve", "Ekspor Excel", "'Kirim Material CMT'", "'Terima FG dari CMT'", "'Dispatch ke Buyer'",
                     "'Serah Terima FG'", "'Kas & Bank'", "Target & Budget", "Ringkasan RnD", "Notifikasi Maklon"):
            assert lama not in teks, (p.name, lama)


def test_panduan_judul_layar_aktif_sama_dengan_menu():
    labels = _label_by_id()
    teks = _src("userGuide", "moduleHelpData.js")
    entri = re.findall(r"\n  '?([a-z0-9-]+)'?: \{\r?\n    title: '([^']+)'", teks)
    salah = [(mid, t) for mid, t in entri if mid in labels and t not in labels[mid]]
    assert not salah, salah
    for berkas in ("moduleHelpData.js", "guideData.js"):
        isi = _src("userGuide", berkas)
        assert "label: 'Export" not in isi and "label: 'Ekspor" not in isi and "'Approve" not in isi, berkas


def test_asisten_ai_dan_pesan_server_memakai_nama_menu():
    for rel in ("core/asisten_ai/alat/target_marketing.py", "core/asisten_ai/alat/tindakan_menengah.py",
                "core/asisten_ai/alat/tindakan_pemasaran.py", "core/marketing_cycle.py",
                "routes/marketing_budget.py", "routes/marketing_data_import.py"):
        teks = (BACKEND / rel).read_text(encoding="utf-8")
        for lama in ("Target & Budget", "Siklus Marketing", "Jejak Perubahan"):
            assert lama not in teks, (rel, lama)
