"""Uji FASE 3 PLAN_PERBAIKAN_AUDIT (T-03 wo_reader, T-17 koleksi hantu, T-18/T-19, gate 3.1) lewat API nyata + DB.

Jalankan:  cd /app/backend && set -a && . .env && set +a && python ../tests/test_fase3_ssot.py
Membuat data uji (perf cycle/assignment/review, penerimaan CMT, absensi, capacity_config) lalu membersihkannya sendiri.
"""
import asyncio
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

API = os.environ.get("API_URL") or "http://localhost:8001"
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
FAILS = []
TAG = f"UJI3-{uuid.uuid4().hex[:6]}"
now = datetime.now(timezone.utc)
today = now.strftime("%Y-%m-%d")


def login(email, pw):
    r = requests.post(f"{API}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def check(name, cond, info=""):
    print(("PASS" if cond else "FAIL"), name, "" if cond else info)
    if not cond:
        FAILS.append(name)


H = login("admin@garment.com", "Admin@123")
H_OP = login("uji.operator@dewiaditya.id", "Dewi@123")
H_HR = login("uji.hr@dewiaditya.id", "Dewi@123")
uid = lambda: str(uuid.uuid4())  # noqa: E731


async def t17_hris_perf():
    """annual-review (portal saya) harus membaca dewi_perf_* yang ditulis dewi_hris_performance."""
    hr_user = await db.users.find_one({"email": "uji.hr@dewiaditya.id"}, {"_id": 0, "id": 1})
    emp_id = uid()
    await db.rahaza_employees.insert_one({"id": emp_id, "employee_code": TAG, "nik": TAG, "name": f"Karyawan {TAG}",
                                          "user_id": hr_user["id"], "email": "uji.hr@dewiaditya.id",
                                          "employment_status": "active", "is_active": True, "active": True,
                                          "department": "HR", "created_at": now})
    r = requests.post(f"{API}/api/dewi/hris/performance/cycles", headers=H, json={
        "cycle_code": TAG, "name": f"Siklus {TAG}", "period_type": "quarterly",
        "start_date": today, "end_date": (now + timedelta(days=90)).strftime("%Y-%m-%d"), "status": "active"})
    check("perf: buat cycle 200", r.status_code == 200, r.text[:200])
    cycle = r.json()
    r = requests.post(f"{API}/api/dewi/hris/performance/kpis", headers=H, json={
        "kpi_code": TAG, "name": f"KPI {TAG}", "category": "productivity", "target_value": 90, "weight_default": 100})
    check("perf: buat kpi 200", r.status_code == 200, r.text[:200])
    kpi = r.json()
    r = requests.post(f"{API}/api/dewi/hris/performance/assignments", headers=H, json={
        "cycle_id": cycle["id"], "employee_id": emp_id, "kpis": [{"kpi_id": kpi["id"], "weight": 100, "target_value": 90}]})
    check("perf: buat assignment 200", r.status_code == 200, r.text[:200])
    asg = r.json()
    r = requests.post(f"{API}/api/dewi/hris/performance/reviews", headers=H, params={"assignment_id": asg["id"]})
    check("perf: buat review 200", r.status_code == 200, r.text[:200])

    r = requests.get(f"{API}/api/portal-saya/annual-review", headers=H_HR)
    check("annual-review 200", r.status_code == 200, r.text[:200])
    d = r.json().get("data", {})
    check("annual-review: assignment saya terbaca dari dewi_perf_assignments",
          any(a.get("id") == asg["id"] for a in d.get("assignments", [])), str(d)[:300])
    check("annual-review: review saya terbaca dari dewi_perf_reviews",
          any(rv.get("assignment_id") == asg["id"] for rv in d.get("reviews", [])), str(d.get("reviews"))[:300])
    check("annual-review: cycle aktif terbaca dari dewi_perf_cycles",
          any(c.get("id") == cycle["id"] for c in d.get("cycles", [])), str(d.get("cycles"))[:300])
    check("annual-review: kpi assignment saya terbaca (tertanam di dewi_perf_assignments)",
          any(k.get("kpi_id") == kpi["id"] and k.get("assignment_id") == asg["id"] for k in d.get("kpis", [])), str(d.get("kpis"))[:300])
    # hris_* tidak boleh dibaca lagi
    for coll in ("hris_assignments", "hris_reviews", "hris_cycles", "hris_kpi_assignments", "hris_training_completions"):
        out = subprocess.run(["grep", "-rln", f"db.{coll}", "/app/backend/routes", "/app/backend/core", "/app/backend/services"],
                             capture_output=True, text=True).stdout
        check(f"tidak ada pembaca db.{coll}", out.strip() == "", out)

    await db.dewi_perf_reviews.delete_many({"assignment_id": asg["id"]})
    await db.dewi_perf_assignments.delete_many({"id": asg["id"]})
    await db.dewi_perf_kpis.delete_many({"id": kpi["id"]})
    await db.dewi_perf_cycles.delete_many({"id": cycle["id"]})
    await db.rahaza_employees.delete_many({"id": emp_id})


def t17_td011_migration_safe():
    src = open("/app/backend/migrations/td011_cleanup_orphan_collections.py").read()
    cats = src[src.index("CATEGORIES"):]
    check("td011: dewi_perf_* TIDAK ada di daftar koleksi yang dihapus",
          "'dewi_perf_" not in cats and '"dewi_perf_' not in cats)


async def t17_qc_from_cmt_receipts():
    """defect_rate laporan eksekutif & daily-summary AI = inspeksi penerimaan FG dari CMT."""
    r = requests.get(f"{API}/api/reports/executive/production-snapshot", headers=H)
    before = r.json()["current"]["defect_rate_pct"]
    r = requests.post(f"{API}/api/prod/cmt-receipts", headers=H, json={"cmt_name": f"CMT {TAG}", "receipt_date": today})
    check("cmt-receipt: buat 200/201", r.status_code in (200, 201), r.text[:200])
    rc = r.json()
    rid = rc.get("id") or rc.get("data", {}).get("id")
    r = requests.post(f"{API}/api/prod/cmt-receipts/{rid}/lines", headers=H, json={
        "sku_code": f"{TAG}-SKU", "product_name": f"Produk {TAG}", "qty_expected": 100, "qty_shipped_by_cmt": 100,
        "qty_actual": 90, "reject_qty": 10, "reject_reason": "jahitan lepas"})
    check("cmt-receipt: tambah baris 200/201", r.status_code in (200, 201), r.text[:200])
    doc = await db.cmt_receipts.find_one({"id": rid}, {"_id": 0})
    check("cmt-receipt: total_actual=90 & total_rejected=10", doc and doc.get("total_actual") == 90 and doc.get("total_rejected") == 10, str(doc)[:200])

    from core.qc_reader import qc_summary, qc_event_rows
    s = await qc_summary(db, d_start=today, d_end=today)
    check("qc_reader.qc_summary menghitung penerimaan uji", s["checked"] >= 100 and s["fail"] >= 10 and s["events"] >= 1, str(s))
    rows = await qc_event_rows(db, d_start=today, d_end=today)
    mine = [x for x in rows if x["id"] == rid]
    check("qc_reader.qc_event_rows: baris uji (line=vendor, defect_reasons)",
          mine and mine[0]["checked_qty"] == 100 and mine[0]["fail_qty"] == 10 and mine[0]["defect_reasons"] == ["jahitan lepas"], str(mine)[:300])

    r = requests.get(f"{API}/api/reports/executive/production-snapshot", headers=H)
    after = r.json()["current"]["defect_rate_pct"]
    check("executive production-snapshot: defect_rate_pct > 0 setelah ada reject", after > 0, f"before={before} after={after}")
    r = requests.get(f"{API}/api/rahaza/ai/daily-summary", headers=H)
    ctx = r.json().get("context", {})
    check("rahaza ai daily-summary: total_qc_checked ≥ 100 & fail ≥ 10",
          ctx.get("total_qc_checked", 0) >= 100 and ctx.get("total_qc_fail", 0) >= 10, str(ctx)[:300])

    r = requests.post(f"{API}/api/analytics/ai/qc/rca", headers=H, json={"days": 30})
    check("analytics qc/rca: bukan 500 (400 'belum cukup' atau 200)", r.status_code in (200, 400), f"{r.status_code} {r.text[:200]}")

    await db.cmt_receipt_lines.delete_many({"receipt_id": rid})
    await db.cmt_receipts.delete_many({"id": rid})


async def t17_attendance_alerts():
    from services.ai_aggregates import hr_aggregates, rahaza_aggregates
    emp_id = uid()
    await db.rahaza_attendance_events.insert_one({"id": uid(), "employee_id": emp_id, "date": today, "status": "hadir",
                                                  "is_late": True, "late_minutes": 15, "source": "uji", "created_at": now})
    n = await hr_aggregates.attendance_issues(db, since=now - timedelta(days=1))
    check("hr_aggregates.attendance_issues membaca rahaza_attendance_events (is_late)", n >= 1, str(n))
    await db.rahaza_attendance_events.delete_many({"employee_id": emp_id})

    nid = uid()
    await db.notifications.insert_one({"id": nid, "type": "rahaza", "severity": "warning", "title": f"Alert {TAG}",
                                       "body": "", "read": False, "status": "sent", "created_at": now + timedelta(days=1)})
    alerts = await rahaza_aggregates.active_alerts(db, limit=50)
    check("rahaza_aggregates.active_alerts membaca notifications (SSOT)", any(a["id"] == nid and a["message"] == f"Alert {TAG}" for a in alerts), str(alerts)[:200])
    await db.notifications.delete_many({"id": nid})


def t17_capacity_config():
    r = requests.get(f"{API}/api/capacity/config", headers=H_OP)
    check("capacity GET /config 200 (semua peran internal)", r.status_code == 200 and "config" in r.json(), r.text[:200])
    orig = r.json()["config"]
    r = requests.put(f"{API}/api/capacity/config", headers=H_OP, json={"daily_capacity_pcs": 999})
    check("capacity PUT /config operator → 403", r.status_code == 403, f"{r.status_code} {r.text[:120]}")
    r = requests.put(f"{API}/api/capacity/config", headers=H, json={"daily_capacity_pcs": 1234, "lead_time_buffer_days": 3})
    check("capacity PUT /config admin 200", r.status_code == 200 and r.json()["config"]["daily_capacity_pcs"] == 1234, r.text[:200])
    r = requests.put(f"{API}/api/capacity/config", headers=H, json={"overload_threshold": 1.5, "critical_threshold": 1.2})
    check("capacity PUT /config critical ≤ overload → 400", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
    r = requests.put(f"{API}/api/capacity/config", headers=H, json={})
    check("capacity PUT /config kosong → 400", r.status_code == 400, f"{r.status_code}")
    r = requests.get(f"{API}/api/capacity/overview", headers=H)
    check("capacity overview memakai config tersimpan", r.status_code == 200 and r.json()["config"]["daily_capacity_pcs"] == 1234, r.text[:200])
    requests.put(f"{API}/api/capacity/config", headers=H, json={k: orig[k] for k in ("daily_capacity_pcs", "lead_time_buffer_days")})


def t03_t18_t19_gate():
    check("T-18: backend/services/stock_service.py dihapus (yang benar core/stock_service.py)",
          not os.path.exists("/app/backend/services/stock_service.py") and os.path.exists("/app/backend/core/stock_service.py"))
    check("T-19: core/collection_registry.py dipertahankan (dipakai scripts/gate_marketing_ssot.py)",
          os.path.exists("/app/backend/core/collection_registry.py"))
    out = subprocess.run(["grep", "-rlE", r"db\.rahaza_work_orders\.", "/app/backend/routes", "/app/backend/core", "/app/backend/services"],
                         capture_output=True, text=True).stdout
    out = "\n".join(l for l in out.splitlines() if "_archive" not in l and "__pycache__" not in l and "core/wo_reader.py" not in l)
    check("T-03: tidak ada pembaca db.rahaza_work_orders di routes/core/services", out.strip() == "", out)
    p = subprocess.run([sys.executable, "/app/scripts/check_collection_writers.py", "--gate"], capture_output=True, text=True, cwd="/app")
    check("gate check_collection_writers --gate lolos", p.returncode == 0, p.stdout[-300:])
    for coll in ("rahaza_qc_events", "rahaza_attendance", "rahaza_alerts", "capacity_config", "hris_"):
        check(f"koleksi hantu '{coll}' tidak lagi di laporan gate", coll not in p.stdout, p.stdout[-400:])
    r = requests.get(f"{API}/api/capacity/overview", headers=H)
    check("wo_reader: capacity overview 200 (production_jobs)", r.status_code == 200 and "load" in r.json(), r.text[:200])


async def main():
    await t17_hris_perf()
    t17_td011_migration_safe()
    await t17_qc_from_cmt_receipts()
    await t17_attendance_alerts()
    t17_capacity_config()
    t03_t18_t19_gate()
    print(f"\n{'GAGAL ' + str(len(FAILS)) + ': ' + ', '.join(FAILS) if FAILS else 'SEMUA PASS'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
