"""Uji HERMETIK Tahap 4 — pola P5 (angka tetap / fallback diam-diam) & P7 (batas to_list yang memotong data).

Tanpa server/Mongo (FakeDB in-memory). Angka harapan dihitung tangan di komentar.
  A. Preset libur nasional 2026/2027 (SKB 3 Menteri) + layar + migrasi 2026_11_07_libur_nasional
  B. P5: hari kerja (kalender produksi, KPI, shift, cuti), nilai sisa aset, overhead HPP, PPN, prorata bulan
  C. P7: ringkasan katalog, MI massal, matriks FG, potongan yatim, BOM, lembur, rekap absen, dsb.
"""
import asyncio
import importlib
import importlib.util
import os
import re
import sys
from datetime import date

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeCollection, FakeCursor, FakeDB, FakeRequest, match  # noqa: E402
from core import catalog_stock as cstock  # noqa: E402
from core import cut_panel_health as cph  # noqa: E402
from core import marketing_cycle as mcycle  # noqa: E402
from core import national_holidays as nh  # noqa: E402

run = asyncio.run
U = {"id": "u1", "name": "Uji", "role": "admin"}


def _src(*parts):
    p = os.path.join(REPO, *parts)
    if not os.path.exists(p):
        pytest.skip(f"sumber tidak tersedia: {p}")
    return open(p, encoding="utf-8").read()


async def _auth(*a, **k):
    return dict(U)


def _patch(monkeypatch, mod, db):
    monkeypatch.setattr(mod, "get_db", lambda: db)
    if hasattr(mod, "require_auth"):
        monkeypatch.setattr(mod, "require_auth", _auth)


def _migration():
    p = os.path.join(BACKEND, "scripts", "migrations", "2026_11_07_libur_nasional.py")
    spec = importlib.util.spec_from_file_location("mig_libur_nasional", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ═════════════════════════════════════════════════════════════════════════════
# A. Preset libur nasional
# ═════════════════════════════════════════════════════════════════════════════
HARI = {"Senin": 0, "Selasa": 1, "Rabu": 2, "Kamis": 3, "Jumat": 4, "Sabtu": 5, "Minggu": 6}
# hari yang tertulis di SKB (setneg.go.id / kemenkopmk.go.id) — memeriksa salinan tanggal kita
SKB_HARI = {
    "2026-01-01": "Kamis", "2026-01-16": "Jumat", "2026-02-16": "Senin", "2026-02-17": "Selasa",
    "2026-03-18": "Rabu", "2026-03-19": "Kamis", "2026-03-20": "Jumat", "2026-03-21": "Sabtu",
    "2026-03-22": "Minggu", "2026-03-23": "Senin", "2026-03-24": "Selasa", "2026-04-03": "Jumat",
    "2026-04-05": "Minggu", "2026-05-01": "Jumat", "2026-05-14": "Kamis", "2026-05-15": "Jumat",
    "2026-05-27": "Rabu", "2026-05-28": "Kamis", "2026-05-31": "Minggu", "2026-06-01": "Senin",
    "2026-06-16": "Selasa", "2026-08-17": "Senin", "2026-08-25": "Selasa", "2026-12-24": "Kamis",
    "2026-12-25": "Jumat",
    "2027-01-01": "Jumat", "2027-01-05": "Selasa", "2027-02-05": "Jumat", "2027-02-06": "Sabtu",
    "2027-03-08": "Senin", "2027-03-09": "Selasa", "2027-03-10": "Rabu", "2027-03-11": "Kamis",
    "2027-03-12": "Jumat", "2027-03-15": "Senin", "2027-03-25": "Kamis", "2027-03-26": "Jumat",
    "2027-03-28": "Minggu", "2027-05-01": "Sabtu", "2027-05-06": "Kamis", "2027-05-17": "Senin",
    "2027-05-18": "Selasa", "2027-05-19": "Rabu", "2027-05-20": "Kamis", "2027-06-01": "Selasa",
    "2027-06-06": "Minggu", "2027-08-15": "Minggu", "2027-08-17": "Selasa", "2027-12-24": "Jumat",
    "2027-12-25": "Sabtu", "2027-12-26": "Minggu",
}


class TestPresetLiburNasional:
    def test_jumlah_sesuai_skb(self):
        # SKB 2026: 17 libur nasional + 8 cuti bersama; SKB 2027: 18 + 8
        for year, libur, cuti in ((2026, 17, 8), (2027, 18, 8)):
            rows = nh.holidays_for(year)
            assert sum(r["kind"] == nh.KIND_LIBUR for r in rows) == libur
            assert sum(r["kind"] == nh.KIND_CUTI for r in rows) == cuti
            assert len({r["date"] for r in rows}) == len(rows)          # tanggal unik
            assert all(r["date"].startswith(str(year)) for r in rows)

    def test_hari_sesuai_yang_tertulis_di_skb(self):
        got = {r["date"] for y in nh.available_years() for r in nh.holidays_for(y)}
        assert got == set(SKB_HARI)
        for d, hari in SKB_HARI.items():
            assert date.fromisoformat(d).weekday() == HARI[hari], d

    def test_tanggal_lama_yang_salah_sudah_tidak_ada(self):
        d2026 = {r["date"]: r for r in nh.holidays_for(2026)}
        for wrong in ("2026-04-06", "2026-04-07", "2026-03-14", "2026-05-24", "2026-06-13", "2026-09-12"):
            assert wrong not in d2026
        assert d2026["2026-03-21"]["name"].startswith("Idulfitri")
        assert {r["date"] for r in nh.holidays_for(2027) if r["name"].startswith("Idulfitri")} == {
            "2027-03-10", "2027-03-11"}

    def test_kalender_keagamaan_ditandai_perkiraan(self):
        rows = {r["date"]: r for r in nh.holidays_for(2027)}
        assert rows["2027-03-10"]["perkiraan"] is True       # Idulfitri (Hijriah)
        assert rows["2027-05-17"]["perkiraan"] is True       # Iduladha
        assert rows["2027-03-08"]["perkiraan"] is True       # Nyepi (Saka)
        assert rows["2027-01-01"]["perkiraan"] is False      # Masehi
        assert rows["2027-03-28"]["perkiraan"] is False      # Paskah (kalender gereja, pasti)
        doc = nh.calendar_doc(rows["2027-03-10"], uid="x", now_iso="t")
        assert "Perkiraan, cek SKB" in doc["notes"] and "1205/2026" in doc["notes"]
        assert doc["type"] == "holiday" and doc["created_by"] == "system"

    def test_tahun_tanpa_data_dikatakan(self):
        assert nh.holidays_for(2028) is None
        msg = nh.missing_year_message(2028)
        assert "2028" in msg and "2026, 2027" in msg


@pytest.fixture
def cal(monkeypatch):
    import routes.rahaza_production_calendar as cal_mod
    db = FakeDB()
    _patch(monkeypatch, cal_mod, db)
    return cal_mod, db


class TestIsiLiburNasional:
    def test_isi_2027_lalu_ulang_idempoten(self, cal):
        mod, db = cal
        out = run(mod.seed_national_holidays(FakeRequest(), year=2027))
        assert out["seeded"] == 26 and out["skipped"] == 0 and out["cuti_bersama"] == 8
        assert out["perkiraan"] > 0 and 2027 in out["available_years"]
        again = run(mod.seed_national_holidays(FakeRequest(), year=2027))
        assert again["seeded"] == 0 and again["skipped"] == 26
        assert len(db.rahaza_production_calendar.docs) == 26

    def test_entri_manual_tidak_ditimpa(self, cal):
        mod, db = cal
        db.rahaza_production_calendar.docs.append(
            {"id": "m1", "date": "2026-12-24", "name": "Masuk (stok opname)", "type": "exception",
             "created_by": "u1"})
        out = run(mod.seed_national_holidays(FakeRequest(), year=2026))
        assert out["seeded"] == 24 and out["skipped"] == 1
        row = next(r for r in db.rahaza_production_calendar.docs if r["date"] == "2026-12-24")
        assert row["id"] == "m1"

    def test_tahun_tanpa_preset_ditolak_dengan_pesan(self, cal):
        mod, db = cal
        with pytest.raises(HTTPException) as ei:
            run(mod.seed_national_holidays(FakeRequest(), year=2028))
        assert ei.value.status_code == 404 and "2028" in ei.value.detail
        assert db.rahaza_production_calendar.docs == []

    def test_layar_memakai_tahun_yang_dilihat_dan_menampilkan_galat(self):
        src = _src("frontend", "src", "components", "erp", "RahazaProductionCalendarModule.jsx")
        assert "seed-national?year=${year}" in src
        assert "Isi libur nasional 2026" not in src
        assert "d.detail" in src and "Perkiraan, cek SKB" in src


class TestMigrasiLiburNasional:
    def _old_rows(self, mig):
        return [{"id": f"o{i}", "date": d, "year": 2026, "name": n, "type": "holiday",
                 "notes": "Hari libur nasional Indonesia 2026", "created_by": "system"}
                for i, (d, n) in enumerate(sorted(mig.OLD_PRESET_2026.items()))]

    def test_pratinjau_lalu_tulis_lalu_idempoten(self):
        mig = _migration()
        db = FakeDB()
        db.rahaza_production_calendar.docs = self._old_rows(mig) + [
            {"id": "man", "date": "2026-08-25", "year": 2026, "name": "Maulid (manual)", "type": "holiday",
             "created_by": "u1"}]
        prev = run(mig.run(False, db=db))
        # 20 baris lama: 8 tanggalnya ada di SKB (diselaraskan), 12 salah (dihapus);
        # 25 tanggal SKB − 8 yang sudah ada − 1 entri manual = 16 ditambah
        assert prev == {"years": [2026], "updated": 8, "deleted": 12, "inserted": 16, "skip_manual": 1}
        assert len(db.rahaza_production_calendar.docs) == 21          # pratinjau tidak menulis
        done = run(mig.run(True, db=db))
        assert done["deleted"] == 12 and done["inserted"] == 16
        rows = {r["date"]: r for r in db.rahaza_production_calendar.docs}
        assert len(rows) == 25
        assert "2026-04-06" not in rows and rows["2026-03-21"]["name"] == "Idulfitri 1447 H"
        assert rows["2026-03-20"]["name"] == "Cuti bersama Idulfitri 1447 H"   # dulu "Wafat Yesus Kristus"
        assert rows["2026-08-25"]["name"] == "Maulid (manual)"                 # manual tidak disentuh
        again = run(mig.run(True, db=db))
        assert (again["updated"], again["deleted"], again["inserted"]) == (0, 0, 0)

    def test_entri_pengguna_bernama_sama_tidak_dihapus(self):
        mig = _migration()
        rows = [{"id": "u", "date": "2026-04-06", "year": 2026, "name": "Hari Raya Idul Fitri",
                 "type": "holiday", "created_by": "u1"}]
        p = mig.plan(rows)
        assert p["delete"] == [] and p["years"] == []


# ═════════════════════════════════════════════════════════════════════════════
# B. P5 — angka tetap
# ═════════════════════════════════════════════════════════════════════════════
class TestHariKerjaEnamHari:
    def test_kalkulator_kalender_ikut_setelan_6_hari(self, cal):
        mod, db = cal
        # Senin 2 Nov – Minggu 8 Nov 2026: 6 hari kerja (dulu 5 karena Sabtu selalu dibuang)
        out = run(mod.get_working_days(FakeRequest(), from_date="2026-11-02", to_date="2026-11-08"))
        assert out["working_days"] == 6 and out["include_saturday"] is True and out["work_days_per_week"] == 6
        out5 = run(mod.get_working_days(FakeRequest(), from_date="2026-11-02", to_date="2026-11-08",
                                        include_saturday=False))
        assert out5["working_days"] == 5

    def test_kalkulator_ikut_setelan_5_hari_dan_libur(self, cal):
        mod, db = cal
        db.rahaza_payroll_settings.docs.append({"key": "work_calendar", "work_days_per_week": 5})
        db.rahaza_production_calendar.docs.append({"id": "h", "date": "2026-11-03", "type": "holiday"})
        out = run(mod.get_working_days(FakeRequest(), from_date="2026-11-02", to_date="2026-11-08"))
        assert out["working_days"] == 4 and out["holidays"] == 1 and out["include_saturday"] is False

    def test_kpi_hari_kerja_kosong_dihitung_bukan_26(self):
        from routes import dewi_kpi_shared as ks
        db = FakeDB()
        # November 2026: 30 hari − 5 Minggu = 25 hari kerja; + libur 17 Nov → 24
        assert run(ks.resolve_working_days(db, None, "2026-11-01", "2026-11-30")) == 25
        assert run(ks.resolve_working_days(db, 22, "2026-11-01", "2026-11-30")) == 22   # isian HR dipakai
        db.rahaza_production_calendar.docs.append({"date": "2026-11-17", "type": "holiday"})
        assert run(ks.resolve_working_days(db, "", "2026-11-01", "2026-11-30")) == 24
        db.da_kpi_periods.docs.append({"period_id": "p", "period_from": "2026-11-01", "period_to": "2026-11-30"})
        db.rahaza_attendance_events.docs.append({"employee_id": "e", "date": "2026-11-05", "status": "alfa"})
        out = run(ks._calc_absensi_score(db, "p", "e"))
        assert out["working_days"] == 24 and out["absensi_score"] == round((1 - 1 / 24) * 100, 2)

    def test_kpi_layar_tidak_lagi_memasang_26(self):
        src = _src("frontend", "src", "components", "erp", "HRKPIModule.jsx")
        assert "working_days: 26" not in src and "|| 26" not in src

    def test_shift_bawaan_senin_sabtu(self):
        from routes.hr_shifts import ShiftCreateModel
        from services.hr_shift_service import DEFAULT_SHIFT
        assert "Sat" in DEFAULT_SHIFT["days_active"]
        fields = getattr(ShiftCreateModel, "model_fields", None) or ShiftCreateModel.__fields__
        f = fields["days_active"]
        factory = getattr(f, "default_factory", None)
        assert "Sat" in factory()

    def test_durasi_cuti_lama_enam_hari(self):
        from services.leave_service import calculate_duration
        assert calculate_duration("2026-11-02", "2026-11-08") == 6

    def test_tidak_ada_lagi_weekday_kurang_dari_5(self):
        rx = re.compile(r"weekday\(\)\s*<\s*5")
        hits = []
        for base in ("routes", "core", "services", "utils"):
            for dp, _, fs in os.walk(os.path.join(BACKEND, base)):
                if "_archive" in dp:
                    continue
                for f in fs:
                    if f.endswith(".py"):
                        for i, ln in enumerate(open(os.path.join(dp, f), encoding="utf-8").read().split("\n")):
                            code = ln.split("#")[0]
                            if rx.search(code) and "`" not in ln:
                                hits.append(f"{f}:{i + 1}")
        assert hits == []


class TestNilaiSisaAset:
    def _create(self, monkeypatch, body, fa=None):
        import routes.asset.assets_core as ac
        db = FakeDB()
        _patch(monkeypatch, ac, db)

        async def noop(*a, **k):
            return None

        async def num(*a, **k):
            return "AST-UJI-0001"

        async def link(db_, fid):
            return fa

        async def fin(db_, ids):
            return {}
        monkeypatch.setattr(ac, "_ensure_default_categories", noop)
        monkeypatch.setattr(ac, "_gen_asset_number", num)
        monkeypatch.setattr(ac, "validate_finance_link", link)
        monkeypatch.setattr(ac, "load_finance_assets", fin)
        monkeypatch.setattr(ac, "apply_finance_overlay", lambda d, f: d)
        run(ac.create_asset(FakeRequest({"name": "Mesin jahit", **body})))
        return db.dewi_assets.docs[0]

    def test_nol_yang_diisi_tetap_nol(self, monkeypatch):
        doc = self._create(monkeypatch, {"purchase_cost": 10_000_000, "residual_value": 0,
                                         "useful_life_months": 50})
        assert doc["residual_value"] == 0.0 and doc["monthly_depreciation"] == 200_000.0

    def test_kosong_ikut_registri_keuangan(self, monkeypatch):
        doc = self._create(monkeypatch, {"fixed_asset_id": "fa1", "useful_life_months": 50},
                           fa={"id": "fa1", "purchase_cost": 10_000_000, "residual_value": 1_000_000})
        assert doc["residual_value"] == 1_000_000.0

    def test_kosong_tanpa_tautan_tetap_bawaan_5_persen(self, monkeypatch):
        doc = self._create(monkeypatch, {"purchase_cost": 10_000_000, "useful_life_months": 50})
        assert doc["residual_value"] == 500_000.0


class TestSetelanDanTarif:
    def test_overhead_hpp_pensiun(self):
        from routes import dewi_system_config as sc
        assert "hpp_overhead_pct" in sc.RETIRED_KEYS
        assert "hpp_overhead_pct" not in {c["key"] for c in sc.DEFAULT_CONFIGS}

    def test_ppn_maklon_dari_ssot_pajak(self):
        src = _src("backend", "core", "maklon_ledger.py")
        assert "'ppn_rate': 12.0" not in src and "PPN_RATE if kena" in src

    def test_porsi_bulan_kalender(self):
        assert mcycle.month_share("2027-02-01", "2027-02-28") == pytest.approx(1.0)   # dulu 28/30
        assert mcycle.month_share("2026-12-01", "2026-12-31") == pytest.approx(1.0)
        assert mcycle.month_share("2026-12-01", "2026-12-07") == pytest.approx(7 / 31)  # dulu 7/30
        # 29 Jan – 4 Feb 2027: 3/31 + 4/28
        assert mcycle.month_share("2027-01-29", "2027-02-04") == pytest.approx(3 / 31 + 4 / 28)
        assert mcycle.month_share("2026-12-07", "2026-12-01") == 0.0
        for parts in (("backend", "core", "marketing_cycle.py"), ("backend", "routes", "marketing_budget.py")):
            assert "days / 30.0" not in _src(*parts)


# ═════════════════════════════════════════════════════════════════════════════
# C. P7 — batas to_list
# ═════════════════════════════════════════════════════════════════════════════
class TestRingkasanKatalog:
    def test_semua_item_dihitung(self):
        db = FakeDB()
        db.marketing_catalogs.docs.append({"id": "c1"})
        for i in range(620):
            st = "out_of_stock" if i < 50 else "low_stock" if i < 150 else "in_stock"
            db.marketing_catalog_items.docs.append(
                {"id": f"i{i}", "catalog_id": "c1", "is_active": True, "stock_quantity": 0 if i < 50 else 2,
                 "stock_status": st})
        db.marketing_catalog_items.docs.append({"id": "x", "catalog_id": "c1", "is_active": False,
                                                "stock_quantity": 99})
        out = run(cstock.refresh_catalog_stats(db, "c1"))
        # 620 item aktif (dulu terpotong 500); stok = 570 × 2
        assert out == {"item_count": 620, "total_stock": 1140.0, "low_stock_count": 100, "out_of_stock_count": 50}
        assert db.marketing_catalogs.docs[0]["item_count"] == 620

    def test_empat_salinan_memakai_satu_fungsi(self):
        for f in ("marketing_catalog_items.py", "marketing_catalog_mgmt.py", "marketing_catalog_stock.py",
                  "marketing_catalog_shared.py"):
            src = _src("backend", "routes", f)
            body = src.split("async def _refresh_catalog_stats", 1)[1].split("\n\n", 1)[0]
            code = "\n".join(ln.split("#")[0] for ln in body.split("\n"))
            assert "refresh_catalog_stats(db, catalog_id)" in code and "to_list" not in code

    def test_stok_rendah_tidak_terpotong(self, monkeypatch):
        import pathlib
        monkeypatch.setattr(pathlib.Path, "mkdir", lambda self, *a, **k: None)   # impor membuat folder unggah
        mcs = importlib.import_module("routes.marketing_catalog_stock")
        db = FakeDB()
        _patch(monkeypatch, mcs, db)
        for i in range(550):
            db.marketing_catalog_items.docs.append({"id": f"i{i}", "catalog_id": "c1", "is_active": True,
                                                    "stock_status": "out_of_stock", "stock_quantity": 0})
        out = run(mcs.get_low_stock_items("c1", FakeRequest()))
        assert out["count"] == 550 and out["out_of_stock"] == 550


class TestMIMassal:
    def test_stok_dan_nama_material_di_luar_500_pertama(self):
        from routes import rahaza_sprint22 as s22
        db = FakeDB()
        for i in range(700):
            db.rahaza_materials.docs.append({"id": f"m{i}", "code": f"K{i}", "name": f"Kain {i}", "unit": "kg",
                                             "active": True})
            db.rahaza_material_stock.docs.append({"material_id": f"m{i}", "qty": 1})
        db.rahaza_material_stock.docs.append({"material_id": "m699", "qty": 4})   # lokasi kedua
        wo_map = {"w1": {"id": "w1", "bom_snapshot": [{"material_id": "m699", "qty": 1}]},
                  "w2": {"id": "w2", "model_id": "md", "size_id": "s"}}
        bom_by_key = {("md", "s"): {"materials": [{"material_id": "m650", "quantity": 2}]}}
        ids = s22._bom_material_ids(["w1", "w2"], wo_map, bom_by_key)
        assert ids == {"m699", "m650"}
        stock, mats = run(s22._stock_and_materials(db, ids))
        assert stock == {"m699": 5.0, "m650": 1.0}
        assert mats["m699"]["code"] == "K699" and mats["m650"]["name"] == "Kain 650"


class TestMatriksFG:
    def test_lebih_dari_2000_fg_dan_stok_non_fg_diabaikan(self, monkeypatch):
        import routes.rahaza_fg_matrix as fgm
        db = FakeDB()
        _patch(monkeypatch, fgm, db)
        for i in range(2050):
            db.rahaza_materials.docs.append({"id": f"f{i}", "type": "fg", "active": True,
                                             "code": f"M{i:04d}-BLK-M", "name": f"FG {i}"})
            db.rahaza_material_stock.docs.append({"material_id": f"f{i}", "qty": 1})
        for i in range(300):
            db.rahaza_material_stock.docs.append({"material_id": f"kain{i}", "qty": 50})
        out = run(fgm.get_fg_matrix(FakeRequest(), model=None, only_with_stock=False))
        assert out["summary"]["total_skus"] == 2050 and out["summary"]["total_qty"] == 2050
        models = run(fgm.get_fg_models(FakeRequest()))
        assert len(models) == 2050


class TestPotonganYatim:
    def test_total_dan_hitungan_semua_potongan(self, monkeypatch):
        db = FakeDB()

        async def inspect(db_, p, onhand=None):
            orphan = p["n"] % 2 == 0
            return {"orphan": orphan, "cleanable": orphan, "value_status": "valued"}
        monkeypatch.setattr(cph, "inspect", inspect)
        for i in range(620):
            db.rahaza_materials.docs.append({"id": f"p{i}", "code": f"CUT-{i:04d}", "is_cut_panel": True, "n": i})
        out = run(cph.scan(db, limit=500, only_orphan=False))
        assert out["panel_total"] == 620 and out["orphan_count"] == 310
        assert len(out["items"]) == 500 and out["items_truncated"] is True
        res = run(cph.cleanup(db, None, dry_run=True))
        assert res["removed"] == 310 and res["kept"] == 310          # dulu hanya 1.000 pertama diperiksa


class _BomColl(FakeCollection):
    """FakeCollection + `$type: "string"` pada `version` (dipakai langkah 1 migrasi BOM saat startup)."""

    def find(self, q=None, projection=None):
        q = dict(q or {})
        v = q.get("version")
        if isinstance(v, dict) and v.get("$type") == "string":
            q.pop("version")
            return FakeCursor([d for d in self.docs if match(d, q) and isinstance(d.get("version"), str)])
        return super().find(q, projection)


class TestBOMStartup:
    def test_semua_bom_dirapikan(self):
        from routes import rahaza_bom as rb
        db = FakeDB()
        db._cols["rahaza_boms"] = coll = _BomColl("rahaza_boms")
        for i in range(620):
            coll.docs.append({"id": f"b{i}", "model_id": f"m{i}", "size_id": "s", "version": "v2",
                              "active": True, "is_active": None, "materials": []})
        run(rb.migrate_bom_data(db))
        # 620 BOM (dulu 500 pertama saja): versi teks → angka, dan tiap model+ukuran punya satu BOM aktif
        assert {b["version"] for b in coll.docs} == {2}
        assert all(b["is_active"] is True for b in coll.docs)


class TestRekapAbsenDanLembur:
    def _rows(self, db, n):
        for i in range(n):
            db.rahaza_attendance_events.docs.append(
                {"employee_id": f"e{i % 25}", "date": f"2026-10-{1 + i // 25:02d}", "status": "hadir",
                 "hours_worked": 8, "overtime_hours": 1})

    def test_lembur_bulanan_tidak_terpotong(self, monkeypatch):
        import routes.rahaza_hr_reports as hr
        db = FakeDB()
        _patch(monkeypatch, hr, db)
        monkeypatch.setattr(hr, "_require_hr_admin", _auth)
        for i in range(25):
            db.rahaza_employees.docs.append({"id": f"e{i}", "active": True, "name": f"K{i}"})
        self._rows(db, 650)                      # 25 karyawan × 26 hari
        out = run(hr.get_overtime_summary(FakeRequest(), from_date="2026-10-01", to_date="2026-10-31"))
        assert out["aggregates"]["total_ot_hours"] == 650     # dulu 500

    def test_rekap_absen_tidak_terpotong(self, monkeypatch):
        import routes.rahaza_attendance as att
        db = FakeDB()
        _patch(monkeypatch, att, db)
        self._rows(db, 650)
        out = run(att.attendance_summary(FakeRequest(), from_="2026-10-01", to="2026-10-31"))
        assert sum(r["days_hadir"] for r in out) == 650 and sum(r["total_hours"] for r in out) == 5200


class TestBacaanLain:
    def test_varian_rnd_tanpa_penyaring(self, monkeypatch):
        import routes.dewi_rnd_design as rd
        db = FakeDB()
        monkeypatch.setattr(rd, "get_db", lambda: db)
        for i in range(921):
            db.dewi_rnd_variants.docs.append({"id": f"v{i}", "style_id": "s", "created_at": f"{i:05d}"})
        assert len(run(rd.list_variants(style_id=None, user=U))) == 921

    def test_perbandingan_toko_satu_tahun(self, monkeypatch):
        import routes.marketing_dashboard as md
        db = FakeDB()
        _patch(monkeypatch, md, db)

        async def visible(*a, **k):
            return None
        monkeypatch.setattr(md._scope, "assert_account_visible", visible)
        for a in ("a1", "a2"):
            db.marketing_platform_accounts.docs.append({"id": a, "account_code": a, "account_name": a,
                                                        "platform": "shopee"})
            for i in range(365):
                d = date.fromordinal(date(2026, 1, 1).toordinal() + i).isoformat()
                db.marketing_sales_data.docs.append({"account_id": a, "date": d, "revenue_type": "total",
                                                     "metrics": {"revenue": 1000, "orders": 1}})
        out = run(md.get_comparison_dashboard(FakeRequest(), accounts="a1,a2", date_from="2026-01-01",
                                              date_to="2026-12-31"))
        assert [r["total_orders"] for r in out["accounts"]] == [365, 365]   # dulu toko kedua terpotong

    def test_scan_keluar_total_hari_ramai(self, monkeypatch):
        import routes.wh_scan_out as wso
        db = FakeDB()
        _patch(monkeypatch, wso, db)
        so = wso.so

        async def empty(*a, **k):
            return []

        async def l2(*a, **k):
            return {}
        monkeypatch.setattr(so, "sheets_still_open", empty)
        monkeypatch.setattr(so, "retry_queue", empty)
        monkeypatch.setattr(so, "langkah2_status", l2)
        monkeypatch.setattr(so, "today_str", lambda: "2026-11-06")
        monkeypatch.setattr(wso, "check_role", lambda *a, **k: True)
        for i in range(2300):
            db[so.LINES].docs.append({"id": f"l{i}", "date": "2026-11-06", "location_id": "loc", "status": "active",
                                      "qty": 1, "material_id": f"m{i % 10}", "scanned_at": f"{i:05d}"})
        out = run(wso.today(FakeRequest(), location_id="loc"))
        assert out["totals"]["lines"] == 2300 and len(out["lines"]) == 500   # dulu total berhenti di 2000
