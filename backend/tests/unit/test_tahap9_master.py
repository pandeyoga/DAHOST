"""Tahap 9 (agen master, 7 Nov 2026) — layar master Produksi & Maklon + pensiun Master Proses / Perawatan Mesin /
Estimasi AI Produksi. Hermetik (FakeDB, tanpa server).

Yang dikunci (keputusan owner 7 Nov 2026, `private/audit/keputusan_tahap9_2026-11-07.md` keputusan 2):
  * Vendor CMT: ubah vendor TIDAK lagi menghapus catatan (PUT = pembaruan sebagian); hitungan & pengaman hapus
    memakai SSOT `production_jobs`/`production_pos`, bukan `vendor_jobs` lama;
  * tab "Semua job" dihapus — layar tidak memanggil `/vendor-portal/jobs`, dan tulis ke `vendor_jobs` ditolak 410;
  * kalender libur: SATU sumber (`core.workdays.holidays_between`) dipakai hitung cuti & jadwal; layarnya di SDM
    (`hr-holiday-calendar`), tulis hanya peran SDM; izin modul `/api/rahaza/production-calendar` milik SDM;
  * id lama yang dipensiunkan diarahkan (registry), rute Perawatan Mesin & Estimasi AI Produksi dilepas;
  * menu baru `maklon-klien-katalog` (Klien · Katalog · Estimasi harga) + layar memakai cetakan PageLayout.
"""
import asyncio
import os
import re
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
ERP = REPO / "frontend" / "src" / "components" / "erp"
ADMIN = {"id": "u-admin", "name": "Admin Uji", "role": "admin"}


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


def src(*parts) -> str:
    return (REPO.joinpath(*parts)).read_text(encoding="utf-8")


def erp(rel: str) -> str:
    return (ERP / rel).read_text(encoding="utf-8")


# ══════════════════════════════ 1. Vendor CMT: catatan tidak terhapus ══════════════════════════════
@pytest.fixture
def vp(monkeypatch):
    import routes.vendor_portal as vp
    db = fm.FakeDB()
    db.vendor_partners.docs = [{"id": "v1", "name": "Vendor Uji", "code": "VU1", "contact_name": "Kontak A",
                                "contact_phone": "0800", "address": "Jalan Uji 1", "notes": "Catatan penting vendor",
                                "is_active": True, "capacity_pcs": 300, "capacity_note": "2 lini", "owner_entity": None}]

    async def auth(_req):
        return dict(ADMIN)

    monkeypatch.setattr(vp, "get_db", lambda: db)
    monkeypatch.setattr(vp, "require_auth", auth)
    monkeypatch.setattr(vp, "log_activity", _noop)
    return vp, db


def test_ubah_vendor_tanpa_catatan_tidak_menghapus_catatan(vp):
    mod, db = vp
    # form ubah lama hanya mengirim nama/kontak — dulu `notes` ikut tertimpa ''
    run(mod.update_partner("v1", mod.PartnerUpdate(name="Vendor Uji Baru", contact_name="Kontak B"), fm.FakeRequest()))
    doc = db.vendor_partners.docs[0]
    assert doc["notes"] == "Catatan penting vendor"
    assert doc["name"] == "Vendor Uji Baru" and doc["contact_name"] == "Kontak B"
    assert doc["address"] == "Jalan Uji 1" and doc["capacity_pcs"] == 300 and doc["code"] == "VU1"


def test_catatan_bisa_diubah_dan_dikosongkan_bila_dikirim(vp):
    mod, db = vp
    run(mod.update_partner("v1", mod.PartnerUpdate(notes="Catatan baru"), fm.FakeRequest()))
    assert db.vendor_partners.docs[0]["notes"] == "Catatan baru"
    assert db.vendor_partners.docs[0]["name"] == "Vendor Uji"        # nama tidak dikirim → tetap
    run(mod.update_partner("v1", mod.PartnerUpdate(notes=""), fm.FakeRequest()))
    assert db.vendor_partners.docs[0]["notes"] == ""


def test_aktifkan_lagi_hanya_mengirim_status(vp):
    mod, db = vp
    db.vendor_partners.docs[0]["is_active"] = False
    run(mod.update_partner("v1", mod.PartnerUpdate(is_active=True), fm.FakeRequest()))
    doc = db.vendor_partners.docs[0]
    assert doc["is_active"] is True and doc["notes"] == "Catatan penting vendor" and doc["contact_phone"] == "0800"


def test_nama_kosong_ditolak(vp):
    mod, _ = vp
    with pytest.raises(HTTPException) as e:
        run(mod.update_partner("v1", mod.PartnerUpdate(name="  "), fm.FakeRequest()))
    assert e.value.status_code == 400


def test_partner_update_fields_hanya_yang_dikirim():
    import routes.vendor_portal as mod
    out = mod.partner_update_fields(mod.PartnerUpdate(contact_phone="0811", capacity_pcs=0))
    assert out == {"contact_phone": "0811", "capacity_pcs": 0}
    assert "notes" not in mod.partner_update_fields(mod.PartnerUpdate(name="X"))


def test_hitungan_dan_pengaman_dari_ssot_produksi(vp):
    mod, db = vp
    db.production_pos.docs = [{"id": "po1", "vendor_id": "v1"}]
    db.production_jobs.docs = [{"id": "j1", "vendor_id": "v1", "status": "In Progress"},
                               {"id": "j2", "vendor_id": "v1", "status": "Completed"}]
    rows = run(mod.list_partners(fm.FakeRequest()))
    assert rows[0]["po_count"] == 1 and rows[0]["job_count"] == 2 and rows[0]["active_job_count"] == 1
    # hapus permanen vendor yang sudah dipakai PO/job → ditolak (dulu hanya cek vendor_jobs yang selalu 0)
    with pytest.raises(HTTPException) as e:
        run(mod.delete_partner("v1", fm.FakeRequest(), hard=True))
    assert e.value.status_code == 400 and "PO" in e.value.detail
    # nonaktifkan vendor dengan job berjalan → ditolak
    with pytest.raises(HTTPException) as e:
        run(mod.delete_partner("v1", fm.FakeRequest(), hard=False))
    assert e.value.status_code == 400 and "job berjalan" in e.value.detail
    db.production_jobs.docs[0]["status"] = "Completed"
    run(mod.delete_partner("v1", fm.FakeRequest(), hard=False))
    assert db.vendor_partners.docs[0]["is_active"] is False


def test_layar_vendor_kirim_isian_berubah_saja_dan_tampilkan_catatan():
    s = erp("VendorAccountsAdminModule.jsx")
    assert "changedPartnerFields" in s and "partner-notes" in s and "partner-detail-notes" in s
    assert "PageLayout" in s and "DetailPanel" in s and "confirmDialog" in s
    assert "max-w-3xl mx-auto" not in s and "<h1" not in s and "<button" not in s


# ══════════════════════════════ 2. Tab "Semua job" dihapus + tulis vendor_jobs ditolak ══════════════════════════════
def test_layar_tidak_lagi_memanggil_job_lama():
    s = erp("VendorAccountsAdminModule.jsx")
    assert "/vendor-portal/jobs" not in s and "label: 'Semua job'" not in s and "AllJobsTab" not in s
    assert "'vendor'" in s and "'akun'" in s          # dua tab: Vendor · Akun vendor


@pytest.mark.parametrize("call", ["create", "update", "delete"])
def test_tulis_vendor_jobs_ditolak_410(vp, call):
    mod, db = vp
    req = fm.FakeRequest()
    with pytest.raises(HTTPException) as e:
        if call == "create":
            run(mod.create_job(mod.VendorJobIn(title="Uji", partner_id="v1"), req))
        elif call == "update":
            run(mod.update_job("j-lama", mod.VendorJobUpdate(status="done"), req))
        else:
            run(mod.delete_job("j-lama", req))
    assert e.value.status_code == 410
    assert db.vendor_jobs.docs == []


# ══════════════════════════════ 3. Kalender libur: satu sumber, di SDM ══════════════════════════════
def test_cuti_menghitung_libur_dari_satu_sumber(monkeypatch):
    from core import leave_engine as le
    from core import workdays
    db = fm.FakeDB()
    db[workdays.HOLIDAY_COLLECTION].docs = [
        {"date": "2026-11-17", "type": "holiday", "name": "Libur uji"},
        {"date": "2026-11-18", "type": "special", "name": "Acara khusus (bukan libur)"},
    ]
    seen = []
    real = workdays.holidays_between

    async def spy(db_, a, b, limit=400):
        seen.append((str(a), str(b)))
        return await real(db_, a, b, limit)

    monkeypatch.setattr(workdays, "holidays_between", spy)
    info = run(le.leave_period_info(db, "2026-11-16", "2026-11-18"))
    assert seen, "hitung cuti wajib membaca kalender lewat core.workdays.holidays_between"
    assert info["holiday_days"] == 1 and info["working_days"] == 2
    assert info["holidays"] == [{"date": "2026-11-17", "name": "Libur uji"}]
    assert run(workdays.holiday_set(db, date(2026, 11, 1), date(2026, 11, 30))) == {"2026-11-17"}


def test_tidak_ada_pembaca_kalender_libur_kedua():
    assert workdays_const() == "rahaza_production_calendar"
    for rel in ("core/leave_engine.py", "routes/rahaza_auto_attendance_config.py", "routes/rahaza_leave.py"):
        assert "db.rahaza_production_calendar" not in (BACKEND / rel).read_text(encoding="utf-8"), rel
    # tidak ada master libur SDM kedua
    hits = []
    for base in ("routes", "core", "services"):
        for p in (BACKEND / base).rglob("*.py"):
            t = p.read_text(encoding="utf-8", errors="ignore")
            hits += re.findall(r"\bdb\.(\w*holiday\w*|\w*libur\w*)\.", t)
    assert hits == [], hits


def workdays_const():
    from core import workdays
    return workdays.HOLIDAY_COLLECTION


def test_tulis_kalender_hanya_peran_sdm_dan_izin_modul_milik_sdm():
    from core.roles import HR_ROLES
    from data.module_catalog import MODULE_BY_ID, match_module
    import routes.rahaza_production_calendar as cal
    assert cal.CALENDAR_WRITE_ROLES == HR_ROLES
    guarded = {}
    for r in cal.router.routes:
        names = [getattr(d.dependency, "__name__", "") for d in getattr(r, "dependencies", [])]
        for m in getattr(r, "methods", set()):
            guarded[(m, r.path)] = names
    for key in (("POST", "/api/rahaza/production-calendar"), ("PUT", "/api/rahaza/production-calendar/{entry_id}"),
                ("DELETE", "/api/rahaza/production-calendar/{entry_id}"),
                ("POST", "/api/rahaza/production-calendar/seed-national")):
        assert any(n.startswith("require_roles[") and "hr" in n for n in guarded[key]), key
    assert guarded[("GET", "/api/rahaza/production-calendar")] == []          # baca: semua staf
    mod = match_module("/api/rahaza/production-calendar/abc")
    assert mod["id"] == "hr_holiday_calendar" and mod["portal"] == "hr"
    assert MODULE_BY_ID["hr_holiday_calendar"]["menus"] == ["hr-holiday-calendar"]
    assert "/api/rahaza/production-calendar" not in MODULE_BY_ID["prod_master_process"]["paths"]


def test_layar_kalender_sdm_terdaftar_dan_memakai_cetakan():
    reg = erp("moduleRegistry.js")
    assert re.search(r"'hr-holiday-calendar':\s+RahazaProductionCalendarModule,", reg)
    s = erp("RahazaProductionCalendarModule.jsx")
    assert "<PageLayout" in s and "DetailPanel" in s and "<h2" not in s and "confirmDialog" in s
    assert "Kalender libur" in s


# ══════════════════════════════ 4. Id lama dipensiunkan → diarahkan ══════════════════════════════
RETIRED = {
    "prod-predictive-maintenance": "production-dashboard",
    "prod-ai-insights": "production-dashboard",
    "prod-master-process-hub": "fin-hpp",
    "prod-processes": "fin-hpp",
    "prod-sop": "production-dashboard",
    "prod-production-calendar": "hr-holiday-calendar",
}


def test_id_pensiun_diarahkan_dan_tujuan_ada():
    reg = erp("moduleRegistry.js")
    blk = reg[reg.index("export const TAHAP9_MASTER_REDIRECTS = {"):]
    blk = blk[:blk.index("};")]
    for mid, target in RETIRED.items():
        assert re.search(rf"'{mid}':\s+makeRedirect\('{target}'\)", blk), mid
        assert f"'{target}':" in reg, f"tujuan {target} tidak ada di registry"
    # penyebaran di AKHIR MODULE_REGISTRY → menimpa entri lama (spread terakhir menang)
    body = reg[reg.index("export const MODULE_REGISTRY = {"):reg.index("export const DEFAULT_MODULE")]
    assert body.replace("\r\n", "\n").rstrip().endswith("...TAHAP9_MASTER_REDIRECTS,\n};")


def test_rute_perawatan_mesin_dan_ai_produksi_dilepas():
    server = (BACKEND / "server.py").read_text(encoding="utf-8")
    assert "from routes.analytics_ai import" not in server
    assert "from routes.dewi_predictive_maintenance import" not in server
    assert not (BACKEND / "routes" / "analytics_ai.py").exists()
    assert not (BACKEND / "routes" / "dewi_predictive_maintenance.py").exists()
    from data.module_catalog import MODULE_BY_ID, match_module
    assert "prod_maintenance" not in MODULE_BY_ID
    assert match_module("/api/analytics/ai/production/rca") is None
    assert "prod-ai-insights" not in MODULE_BY_ID["prod_analytics"]["menus"]


# ══════════════════════════════ 5. Menu baru Klien & Katalog Buyer + layar standar ══════════════════════════════
def test_hub_klien_katalog_terdaftar_dengan_tiga_tab():
    reg = erp("moduleRegistry.js")
    assert re.search(r"'maklon-klien-katalog':\s+MaklonKlienKatalogHub,", reg)
    assert "import('./maklon/KlienKatalogHub')" in reg
    hub = erp("maklon/KlienKatalogHub.jsx")
    for key, label in (("klien", "Klien"), ("katalog", "Katalog"), ("estimasi", "Estimasi harga")):
        assert f"key: '{key}', label: '{label}'" in hub
    from data.module_catalog import MODULE_BY_ID
    for mid in ("mak_clients", "mak_buyer_catalog", "mak_ai_quote"):
        assert "maklon-klien-katalog" in MODULE_BY_ID[mid]["menus"], mid


SCREENS = ["VendorAccountsAdminModule.jsx", "CMTOverridePortalModule.jsx", "MaklonClientManagement.jsx",
           "MaklonBuyerCatalogModule.jsx", "MaklonAIQuoteModule.jsx", "RahazaProductionCalendarModule.jsx",
           "hubs/ProductionMasterProductHub.jsx", "cmt-override/CMTOverrideRecapPanel.jsx"]
OWNED = SCREENS + ["maklon/KlienKatalogHub.jsx", "maklon/KatalogArtikelForm.jsx", "maklon/KatalogArtikelDetail.jsx",
                   "cmt-override/CMTOverrideDailyRecap.jsx", "cmt-override/CMTOverrideWeeklyRecap.jsx"]


@pytest.mark.parametrize("rel", SCREENS)
def test_layar_memakai_pagelayout(rel):
    assert "<PageLayout" in erp(rel), rel


@pytest.mark.parametrize("rel", OWNED)
def test_tanpa_pola_terlarang(rel):
    s = erp(rel)
    assert "<" + "select" not in s
    assert not re.search(r"(?<![\w.])(?:window\.)?(?:confirm|alert)\(", s), "pakai confirmDialog/toast"
    assert "<h1" not in s and "<TabsList" not in s
    assert not re.search(r'className="[^"]*\bmax-w-(?:[3-7]xl)\b[^"]*\bmx-auto\b', s)
    assert not re.search(r"(?<![\w-])(?:p-6|py-12|mt-8)(?![\w-])", s)


def test_detail_katalog_di_halaman_bukan_dialog():
    assert not (ERP / "MaklonBuyerCatalogDetailDialog.jsx").exists()
    d = erp("maklon/KatalogArtikelDetail.jsx")
    assert "DetailPanel" in d and "<Dialog" not in d
    for part in ("/samples", "/price-history", "/bom-templates", "variants/generate"):
        assert part in d, part
    m = erp("MaklonBuyerCatalogModule.jsx")
    assert "KatalogArtikelDetail" in m and "MaklonBuyerCatalogDetailDialog" not in m and "<Table" in m


def test_input_atas_nama_cmt_pilih_dari_tabel_vendor_aktif():
    s = erp("CMTOverridePortalModule.jsx")
    assert "cmt-override-vendor-table" in s and "VendorCard" not in s
    assert "include_inactive" not in s and "is_active !== false" in s
    assert "<HubTabs" in s and "onValueChange={setActiveModule}" in s
    assert "clearCmtOverrideVendor" in s and "setCmtOverrideVendor(v.id)" in s
    hub = erp("hubs/HubTabs.jsx")
    assert "value, onValueChange" in hub          # mode terkendali opsional
