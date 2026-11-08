"""Uji HERMETIK keputusan pemilik 8 Nov 2026 (uji ketajaman SDM + Marketing). Tanpa server/Mongo.

1. Cuti › setuju massal hanya `leave_ids` → lihat `test_tahap2_absen.py::TestSatuFungsiPersetujuan`.
2. Job Board: tombol "Pasang lowongan" memakai peran akun yang masuk; daftar peran = pemeriksaan server.
3. Skor sehat toko: skor basi dihitung ulang & disimpan saat dibaca; snapshot memicu hitung ulang; migrasi.
4. Rekap host live per bulan (pengganti layar Pembayaran) + pesan "sync" yang jujur.
5. Grup toko: pemetaan teks bebas → daftar tetap (pratinjau/tulis, nilai yang tak terpetakan dibiarkan).
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("DB_NAME", "uji")

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
REPO = BACKEND.parent
for p in (str(BACKEND), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402

import routes.marketing_shared as ms  # noqa: E402
from utils.waktu import today_wib  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _mig(name):
    p = BACKEND / "scripts" / "migrations" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mig_{name}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _src(*parts):
    p = REPO.joinpath(*parts)
    if not p.exists():
        pytest.skip(f"sumber tidak tersedia: {p}")
    return p.read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════════════
# 2 · Job Board
# ═════════════════════════════════════════════════════════════════════════════
def test_job_board_peran_dari_akun_dan_sama_dengan_server():
    fe = _src("frontend", "src", "components", "erp", "hr", "JobBoardModule.jsx")
    be = _src("backend", "routes", "dewi_job_board.py")
    assert "setUserRole('user')" not in fe
    assert re.search(r"function JobBoardModule\(\{[^}]*\buser\b", fe)
    fe_roles = re.search(r"PERAN_PASANG_LOWONGAN = \[([^\]]+)\]", fe).group(1)
    # 2026-11-08: server = `check_role(user, JOB_BOARD_ROLES, JOB_BOARD_PERM)` (kode peran ATAU izin hr.manage)
    be_roles = re.search(r'JOB_BOARD_ROLES = \[([^\]]+)\]', be).group(1)
    norm = lambda s: sorted(x.strip().strip("'\"") for x in s.split(","))  # noqa: E731
    assert norm(fe_roles) == norm(be_roles) == ["hr", "manager", "superadmin"]
    fe_perm = re.search(r"IZIN_JOB_BOARD = '([^']+)'", fe).group(1)
    be_perm = re.search(r'JOB_BOARD_PERM = "([^"]+)"', be).group(1)
    assert fe_perm == be_perm == "hr.manage"
    assert "checkPerm({ user, roles: PERAN_PASANG_LOWONGAN, perm: IZIN_JOB_BOARD })" in fe


# ═════════════════════════════════════════════════════════════════════════════
# 3 · Skor sehat toko
# ═════════════════════════════════════════════════════════════════════════════
def _sales(db, aid, n_days=8, revenue=2_000_000, orders=20):
    for i in range(1, n_days + 1):
        d = (today_wib() - timedelta(days=i)).isoformat()
        db.marketing_sales_data.docs.append({
            "id": f"s-{aid}-{i}", "account_id": aid, "date": d, "revenue_type": "total",
            "metrics": {"revenue": revenue, "orders": orders, "conversion_rate": 3.0}})


def test_skor_basi_dihitung_ulang_dan_disimpan_skor_segar_dibiarkan():
    db = FakeDB()
    kemarin = datetime.now(timezone.utc) - timedelta(days=2)
    db.marketing_platform_accounts.docs += [
        {"id": "a1", "account_name": "Toko A", "health_score": None, "health_label": "Belum ada data"},
        {"id": "a2", "account_name": "Toko B", "health_score": 90, "health_updated_at": kemarin},
        {"id": "a3", "account_name": "Toko C", "health_score": 42, "health_grade": 2,
         "health_updated_at": datetime.now(timezone.utc)},
    ]
    _sales(db, "a1")
    accounts = [dict(d) for d in db.marketing_platform_accounts.docs]
    n = run(ms.refresh_stale_health_scores(db, accounts))
    assert n == 2                                                   # a1 (belum pernah) + a2 (kemarin)
    a1, a2, a3 = accounts
    assert isinstance(a1["health_score"], int) and a1["health_score"] > 0 and a1["health_grade"] in (1, 2, 3, 4, 5)
    assert a2["health_score"] is None and a2["health_label"] == ms.HEALTH_NO_DATA_LABEL   # tanpa data 30 hari
    assert a3["health_score"] == 42                                 # dihitung hari ini → tidak disentuh
    stored = {d["id"]: d for d in db.marketing_platform_accounts.docs}
    assert stored["a1"]["health_score"] == a1["health_score"] and stored["a2"]["health_score"] is None
    assert ms.health_is_stale(stored["a1"]) is False
    # pembacaan kedua di hari yang sama tidak menghitung ulang
    assert run(ms.refresh_stale_health_scores(db, [dict(d) for d in db.marketing_platform_accounts.docs])) == 0


def test_hitung_ulang_sama_dengan_rumus_lama_dan_gagal_tidak_menggagalkan_layar():
    db = FakeDB()
    db.marketing_platform_accounts.docs.append({"id": "a1", "account_name": "Toko A"})
    _sales(db, "a1")
    score = run(ms._recalculate_health_score(db, "a1"))
    fields = run(ms.compute_health_fields(db, "a1"))
    assert score == fields["health_score"] == db.marketing_platform_accounts.docs[0]["health_score"]

    bad = FakeDB()

    def meledak(*a, **k):
        raise RuntimeError("db putus")
    bad.marketing_sales_data.find = meledak
    acc = [{"id": "x", "health_score": 77}]
    assert run(ms.refresh_stale_health_scores(bad, acc)) == 0 and acc[0]["health_score"] == 77


def test_layar_dan_laporan_memakai_skor_segar():
    for parts in (("marketing_accounts.py",), ("marketing_reports.py",), ("marketing_dashboard.py",)):
        src = _src("backend", "routes", *parts)
        assert "refresh_stale_health_scores(db" in src, parts
    src = _src("backend", "routes", "marketing_account_health_routes.py")
    assert not re.search(r"^\s*from routes\.marketing import", src, re.M)   # modul hantu → tak pernah jalan
    assert "from routes.marketing_shared import _recalculate_health_score" in src


def test_get_akun_menghitung_ulang_skor_basi(monkeypatch):
    import routes.marketing_accounts as macc
    db = FakeDB()
    db.marketing_platform_accounts.docs.append({"id": "a1", "account_name": "Toko A", "health_score": None})
    _sales(db, "a1")
    monkeypatch.setattr(macc, "get_db", lambda: db)

    async def _auth(*a, **k):
        return {"id": "u1", "role": "superadmin"}
    monkeypatch.setattr(macc, "require_auth", _auth)
    out = run(macc.get_platform_account("a1", FakeRequest()))
    assert out["health_score"] and out["health_score"] > 0


def test_migrasi_skor_sehat_pratinjau_lalu_tulis(capsys):
    mig = _mig("2026_11_08_skor_sehat_toko")
    db = FakeDB()
    db.marketing_platform_accounts.docs += [
        {"id": "a1", "account_name": "Toko A", "health_score": None, "health_label": "Belum ada data"},
        {"id": "a2", "account_name": "Toko B", "health_score": 88, "health_label": "Sangat Sehat"},
    ]
    _sales(db, "a1")
    pre = run(mig.run(db, apply=False))
    assert pre["toko"] == 2 and pre["berubah"] == 2 and pre["punya_skor"] == 1 and pre["belum_ada_data"] == 1
    assert db.marketing_platform_accounts.docs[0]["health_score"] is None              # pratinjau tidak menulis
    assert "→" in capsys.readouterr().out
    out = run(mig.run(db, apply=True))
    assert out["ditulis"] == 2
    docs = {d["id"]: d for d in db.marketing_platform_accounts.docs}
    assert docs["a1"]["health_score"] > 0 and docs["a2"]["health_score"] is None
    again = run(mig.run(db, apply=False))
    assert again["berubah"] == 0 and again["tetap"] == 2                                 # idempoten


# ═════════════════════════════════════════════════════════════════════════════
# 4 · Rekap host live
# ═════════════════════════════════════════════════════════════════════════════
# marketing_livehost_shared membuat /app/uploads/livehost saat diimpor — di runner CI (bukan root) itu ditolak.
# Sama seperti test_portal_eksternal_kreator_livehost: matikan makedirs sebentar saat impor.
_makedirs_asli = os.makedirs
os.makedirs = lambda *a, **k: None
try:
    import routes.marketing_livehost_analytics as lha  # noqa: E402
finally:
    os.makedirs = _makedirs_asli


def test_rekap_per_host_fungsi_murni():
    hosts = [{"id": "h1", "name": "Ayu", "employee_id": "e1", "status": "active"},
             {"id": "h2", "name": "Bima", "status": "active"},
             {"id": "h3", "name": "Cici", "status": "inactive"}]
    sessions = [
        {"host_id": "h1", "duration_minutes": 90, "revenue": 1_500_000, "orders": 10, "status": "completed"},
        {"host_id": "h1", "duration_minutes": 30, "gmv": 500_000, "total_orders": 4},          # ejaan lama
        {"host_id": "h1", "duration_minutes": 60, "revenue": 9_999, "status": "cancelled"},   # tidak dihitung
        {"host_id": "h1", "duration_minutes": 60, "revenue": 9_999, "status": "scheduled"},   # tidak dihitung
        {"host_id": "h1", "duration_minutes": 60, "revenue": 9_999, "_seed_origin": True},    # data contoh
        {"host_id": "h3", "duration_minutes": 45, "revenue": "250000", "status": "live"},
    ]
    shifts = [{"host_id": "h1", "attendance_status": "completed", "actual_duration_minutes": 240},
              {"host_id": "h1", "attendance_status": "late", "actual_duration_minutes": 240},
              {"host_id": "h2", "attendance_status": "completed", "actual_duration_minutes": 180}]
    rows = {r["host_id"]: r for r in lha.rekap_per_host(hosts, sessions, shifts)}
    h1 = rows["h1"]
    assert (h1["sessions"], h1["live_hours"], h1["revenue"], h1["orders"]) == (2, 2.0, 2_000_000, 14)
    assert (h1["shifts_completed"], h1["shift_hours"], h1["employee_id"]) == (1, 4.0, "e1")
    assert (rows["h2"]["sessions"], rows["h2"]["shifts_completed"], rows["h2"]["shift_hours"]) == (0, 1, 3.0)
    assert rows["h3"]["sessions"] == 1 and rows["h3"]["revenue"] == 250_000   # host nonaktif tetap muncul bila bekerja
    assert [r["host_id"] for r in lha.rekap_per_host(hosts, sessions, shifts)][0] == "h1"   # urut omzet
    sepi = lha.rekap_per_host(hosts, [], [], include_idle=False)
    assert sepi == []


def test_endpoint_rekap_bulan_dan_lingkup(monkeypatch):
    db = FakeDB()
    db.marketing_livehosts.docs += [{"id": "h1", "name": "Ayu", "employee_id": "e1", "status": "active"},
                                    {"id": "h2", "name": "Bima", "status": "active"}]
    db.rahaza_employees.docs.append({"id": "e1", "name": "Ayu Lestari"})
    db.marketing_live_sessions.docs += [
        {"id": "s1", "account_id": "t1", "host_id": "h1", "session_date": datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
         "duration_minutes": 120, "revenue": 3_000_000, "orders": 30, "status": "completed"},
        {"id": "s2", "account_id": "t1", "host_id": "h1", "session_date": "2026-10-31",
         "duration_minutes": 60, "revenue": 1_000_000, "orders": 5, "status": "completed"},
        {"id": "s3", "account_id": "t1", "host_id": "h1", "session_date": "2026-11-01",                # bulan lain
         "duration_minutes": 60, "revenue": 7_000_000, "status": "completed"},
        {"id": "s4", "account_id": "t2", "host_id": "h2", "session_date": "2026-10-10",
         "duration_minutes": 30, "revenue": 500_000, "status": "completed"},
    ]
    db.marketing_livehost_shifts.docs.append({"id": "sh1", "account_id": "t1", "host_id": "h1", "date": "2026-10-05",
                                              "attendance_status": "completed", "actual_duration_minutes": 180})
    db.marketing_platform_accounts.docs += [{"id": "t1", "pic_user_id": "u-staf"}, {"id": "t2"}]
    monkeypatch.setattr(lha, "get_db", lambda: db)
    user = {"id": "u-spv", "role": "spv_marketing"}

    async def _auth(*a, **k):
        return dict(user)
    monkeypatch.setattr(lha, "require_auth", _auth)

    out = run(lha.get_host_recap(FakeRequest(), month="2026-10"))
    rows = {r["host_id"]: r for r in out["hosts"]}
    assert (rows["h1"]["sessions"], rows["h1"]["live_hours"], rows["h1"]["revenue"]) == (2, 3.0, 4_000_000)
    assert rows["h1"]["employee_name"] == "Ayu Lestari" and rows["h1"]["shifts_completed"] == 1
    assert out["totals"]["sessions"] == 3 and out["totals"]["unlinked"] == 1

    user.update(id="u-staf", role="staff_marketing")                     # staf pemegang toko t1 saja
    out = run(lha.get_host_recap(FakeRequest(), month="2026-10"))
    assert [r["host_id"] for r in out["hosts"]] == ["h1"] and out["totals"]["revenue"] == 4_000_000


def test_pesan_finalkan_tidak_lagi_menyebut_sync_ke_finance(monkeypatch):
    db = FakeDB()
    db.marketing_livehost_shifts.docs.append({"id": "sh1", "host_id": "h1", "host_name": "Ayu", "date": "2026-10-05",
                                              "payment_status": "calculated", "total_pay": 0})
    monkeypatch.setattr(lha, "get_db", lambda: db)

    async def _auth(*a, **k):
        return {"id": "u1", "role": "superadmin"}

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(lha, "require_auth", _auth)
    monkeypatch.setattr(lha, "log_activity", _noop)
    monkeypatch.setattr(lha, "publish_livehost_notification", _noop)
    out = run(lha.sync_payments_to_finance(FakeRequest(), month="2026-10"))
    assert "Finance" not in out["message"] and "Tidak ada jurnal atau payroll yang dibuat" in out["message"]
    assert db.marketing_livehost_shifts.docs[0]["payment_status"] == "synced_to_finance"   # perilaku tetap
    fe = _src("frontend", "src", "components", "erp", "marketing", "PaymentTab.jsx")
    assert "payment/recap" in fe and "hr-payroll-hub" in fe
    assert "calculate-payment-btn" not in fe and "sync-to-finance-btn" not in fe     # tombol lama hilang
    assert "payment/calculate" not in fe and "sync-to-finance" not in fe


# ═════════════════════════════════════════════════════════════════════════════
# 5 · Grup toko + Kesehatan Akun satu pemilih
# ═════════════════════════════════════════════════════════════════════════════
def test_petakan_grup():
    """Grup toko = MEREK (keputusan owner 8 Nov 2026): Rayona · Daluna · Outfit Boutique · Lainnya."""
    mig = _mig("2026_11_08_grup_toko")
    p = mig.petakan_grup
    assert p("rayona") == p("Rayona") == p(" RAYONA ") == "rayona"
    assert p("Daluna") == "daluna"
    assert p("Outfit Boutique") == p("outfit-boutique") == p("outfit_boutique") == "outfit_boutique"
    assert p("other") == p("Lainnya") == p("lain-lain") == "other"
    # kosong / jenis toko versi lama → merek dari nama toko bila tepat satu, selain itu Lainnya
    assert p("official_store", "Shopee Outfit Boutique") == "outfit_boutique"
    assert p(None, "TikTok Rayona") == "rayona"
    assert p("Reseller", "Shopee GHS") == p("grosir") == p("") == p("-") == "other"
    assert p("Rayona Daluna", None) is None                         # teks tak dikenal → dibiarkan
    assert p("Official Store", "Rayona x Daluna") == "other"         # dua merek di nama → tidak menebak
    assert p(5) is None
    fe = _src("frontend", "src", "components", "erp", "AccountManagementModule.jsx")
    kode_fe = sorted(re.findall(r"\{ value: '([a-z_]+)', label: '[^']+' \}",
                                fe.split("const GROUPS = [")[1].split("];")[0]))
    assert kode_fe == sorted(mig.GRUP_TETAP)                         # daftar tetap = pilihan form


def test_migrasi_grup_pratinjau_lalu_tulis(capsys):
    mig = _mig("2026_11_08_grup_toko")
    db = FakeDB()
    db.marketing_platform_accounts.docs += [
        {"id": "t1", "group": "rayona", "account_name": "Shopee Rayona"},
        {"id": "t2", "group": "Rayona", "account_name": "Shopee Sukma"},
        {"id": "t3", "group": "Daluna", "account_name": "Shopee GHS"},
        {"id": "t4", "group": "Outfit Boutique", "account_name": "Tiktok Outfit Boutique"},
        {"id": "t5", "group": "official_store", "account_name": "Shopee Outfit Boutique"},
        {"id": "t6", "account_name": "Toko Baru"},
        {"id": "t7", "group": "Merek Lain", "account_name": "Shopee X"},
    ]
    pre = run(mig.run(db, apply=False))
    assert (pre["toko"], pre["sudah_benar"], pre["dipetakan"], pre["tidak_dipetakan"]) == (7, 1, 5, 1)
    assert pre["nilai_tidak_dipetakan"] == {"Merek Lain": 1}
    teks = capsys.readouterr().out
    assert "Tidak bisa dipetakan" in teks and "'Merek Lain': 1 toko" in teks
    assert db.marketing_platform_accounts.docs[1]["group"] == "Rayona"                    # pratinjau tidak menulis
    out = run(mig.run(db, apply=True))
    assert out["ditulis"] == 5
    grup = {d["id"]: d.get("group") for d in db.marketing_platform_accounts.docs}
    assert grup == {"t1": "rayona", "t2": "rayona", "t3": "daluna", "t4": "outfit_boutique",
                    "t5": "outfit_boutique", "t6": "other", "t7": "Merek Lain"}
    again = run(mig.run(db, apply=False))
    assert again["dipetakan"] == 0 and again["tidak_dipetakan"] == 1                      # idempoten


def test_kesehatan_akun_satu_pemilih_akun():
    fe = _src("frontend", "src", "components", "erp", "marketing", "AccountHealthDashboard.jsx")
    assert "health-filter-account" not in fe and "/api/marketing/health/accounts" not in fe
    assert fe.count("<ActiveAccountBar") == 1
    assert "const accountFilter = activeAccount?.account_name || ''" in fe
