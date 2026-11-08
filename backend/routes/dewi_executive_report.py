"""Executive Report Hub — Phase 3 P1.

Consolidated cross-module KPI dashboard for management.

Endpoints:
  GET  /api/reports/executive/summary          — full executive snapshot
  GET  /api/reports/executive/kpi-comparison   — month-on-month KPI comparison
  GET  /api/reports/executive/finance-snapshot — finance KPIs (AR, revenue, cash)
  GET  /api/reports/executive/production-snapshot — production KPIs
  GET  /api/reports/executive/hr-snapshot      — HR KPIs
  GET  /api/reports/executive/marketing-snapshot — marketing KPIs
  GET  /api/reports/executive/trend            — multi-KPI trend (last N months)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from auth import require_auth
from database import get_db
from utils.waktu import today_wib, now_wib

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Akses (2026-11-02, keputusan owner K33)
# ---------------------------------------------------------------------------
# Dulu semua handler hanya `require_auth` → peran apa pun (mis. `operator`) membaca total gaji
# lewat `hr-snapshot`. Kini satu penjaga (`require_exec_report`, dipanggil SEMUA handler), dikonfigurasi
# lewat Manajemen Role yang SUDAH ada
# (modul granular `fin_exec_report` di data/module_catalog.py, menu `fin-executive-report`):
#   1. owner/superadmin/admin atau izin "*"                      → selalu boleh;
#   2. menu "Laporan Eksekutif" disembunyikan untuk peran/pengguna → DITOLAK (termasuk peran yang
#      izin per modul Portal Keuangan-nya sudah diatur owner tanpa centang "Lihat — Laporan Eksekutif");
#   3. izin `mod.fin_exec_report.view`                           → boleh (peran apa pun yang dicentang);
#   4. belum diatur owner (bawaan)                               → hanya peran yang bisa membuka
#      Portal Manajemen atau Portal Keuangan (accounting, staff_keuangan, manager_*, …).
EXEC_REPORT_MODULE = "fin_exec_report"
EXEC_REPORT_MENU = "fin-executive-report"
EXEC_REPORT_DEFAULT_PORTALS = ("management", "finance")


async def exec_report_access(db, user: dict) -> tuple[bool, str]:
    """(boleh?, alasan) untuk Laporan Eksekutif — lihat aturan di atas."""
    from data.module_catalog import granular_portals, perm_key
    from routes.shared import SUPER_ROLES, resolve_role_access, user_permissions
    role = (user.get("role") or "").lower()
    if role in SUPER_ROLES:
        return True, "super"
    perms = user_permissions(user)
    if "*" in perms:
        return True, "wildcard"
    access = await resolve_role_access(db, {"id": user.get("id"), "role": role})
    if EXEC_REPORT_MENU in (access.get("hidden_modules") or []):
        return False, "hidden"
    if perm_key(EXEC_REPORT_MODULE, "view") in perms:
        return True, "permission"
    if "finance" in granular_portals(perms):
        return False, "not_granted"
    if set(access.get("portals") or []) & set(EXEC_REPORT_DEFAULT_PORTALS):
        return True, "default_portal"
    return False, "default_portal"


async def require_exec_report(request: Request) -> dict:
    user = await require_auth(request)
    ok, _why = await exec_report_access(get_db(), user)
    if not ok:
        raise HTTPException(
            403, "Akses ditolak: peran Anda tidak diberi izin 'Lihat — Laporan Eksekutif' "
                 f"(mod.{EXEC_REPORT_MODULE}.view). Owner dapat mengaturnya di Administrasi Sistem › "
                 "Manajemen Role (Izin per modul › Portal Keuangan).")
    return user


# Penjaga dipanggil di SETIAP handler (bukan dependency router) supaya dependency route tetap persis
# yang dipasang server.py (_DENY_EXTERNAL; diuji test_p1_router_guards).
router = APIRouter(prefix="/api/reports/executive", tags=["executive-report"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _month_range(year: int, month: int) -> tuple[str, str]:
    start = date(year, month, 1).isoformat()
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end.isoformat()


def _prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _delta_pct(curr: float, prev: float) -> Optional[float]:
    if not prev:
        return None
    return round((curr - prev) / prev * 100, 1)


# ---------------------------------------------------------------------------
# Finance aggregations
# ---------------------------------------------------------------------------
# 2026-11-02 (audit No.51): status faktur yang benar-benar terbit. Draft & batal/void tidak pernah
# menjadi pendapatan.
REAL_AR_STATUSES = ["paid", "partial", "partial_paid", "sent", "issued", "overdue", "written_off"]


async def _gl_revenue(db, start: str, end: str) -> float:
    """2026-11-02 (audit No.51): pendapatan = saldo akun REVENUE buku besar periode itu
    (kredit − debit, tanpa jurnal penutup tahun) — rumus yang SAMA dengan Laporan Laba/Rugi.
    Artinya DPP tanpa PPN (PPN keluaran = hutang 2-1400), sudah dikurangi retur/diskon/potongan
    platform, dan pendapatan pencairan marketplace (yang menurut D2 hanya ada di GL) ikut."""
    codes = [a["code"] async for a in db.rahaza_coa_accounts.find(
        {"type": "REVENUE", "is_group": False}, {"_id": 0, "code": 1})]
    if not codes:
        return 0.0
    rows = await db.rahaza_journal_lines.aggregate([
        {"$match": {"date": {"$gte": start, "$lte": end}, "source_module": {"$ne": "year_end_close"},
                    "account_code": {"$in": codes}}},
        {"$group": {"_id": None, "d": {"$sum": {"$ifNull": ["$debit", 0]}},
                    "c": {"$sum": {"$ifNull": ["$credit", 0]}}}},
    ]).to_list(1)
    r = rows[0] if rows else {}
    return round(float(r.get("c") or 0) - float(r.get("d") or 0), 2)


AR_OVERDUE_STATUSES = ["sent", "issued", "partial", "partial_paid", "overdue"]


def ar_overdue_match(today_iso: str) -> dict:
    """Saringan faktur piutang lewat jatuh tempo: belum lunas & jatuh tempo SEBELUM `today_iso` (WIB).

    8 Nov 2026 (keputusan owner): faktur yang jatuh tempo hari ini belum terlambat — aturan yang sama dengan
    Umur piutang (`rahaza_ar_canonical`), Ringkasan Bisnis, dan tugas `cron/mark-overdue`."""
    return {"status": {"$in": AR_OVERDUE_STATUSES}, "due_date": {"$lt": today_iso}}


async def _finance_kpis(db, year: int, month: int) -> dict:
    start, end = _month_range(year, month)

    # Revenue (finalized invoices) — RC-02: SSOT rahaza_ar_invoices (field: total/balance/issue_date)
    rev_pipeline = [
        {"$match": {
            "issue_date": {"$gte": start, "$lte": end},
            "status": {"$in": REAL_AR_STATUSES},  # FIN-09: pendapatan diakui saat terbit (hapus-buku = beban, bukan pengurang pendapatan)
        }},
        {"$group": {"_id": None,
                    "total_revenue": {"$sum": {"$ifNull": ["$total", 0]}},
                    # 2026-11-02: DPP faktur = total − PPN (pembanding; angka utama dari GL)
                    "total_dpp": {"$sum": {"$subtract": [{"$ifNull": ["$total", 0]},
                                                         {"$ifNull": ["$tax_amount", 0]}]}},
                    "total_paid": {"$sum": {"$subtract": [{"$ifNull": ["$total", 0]}, {"$ifNull": ["$balance", 0]}]}},
                    "invoice_count": {"$sum": 1}}},
    ]
    rev_rows = await db.rahaza_ar_invoices.aggregate(rev_pipeline).to_list(1)
    rev_data = rev_rows[0] if rev_rows else {}

    # 2026-11-02 (K33): biaya & laba bersih dari rumus Laba/Rugi buku besar yang SAMA dengan layar L/R
    # (routes.rahaza_fin_reports.compute_profit_loss). Dulu Σ DEBIT akun EXPENSE/COGS saja → retur/
    # koreksi sisi kredit (mis. pembalikan HPP, reklas beban) tidak mengurangi biaya, laba bersih
    # terlalu kecil; pendapatan lain-lain & beban lain-lain juga tidak ikut.
    from routes.rahaza_fin_reports import compute_profit_loss
    pl_totals = (await compute_profit_loss(db, start, end))["totals"]
    total_expenses = round(pl_totals["cogs"] + pl_totals["expense"] + pl_totals["other_expense"], 2)

    # AR overdue — SSOT rahaza_ar_invoices: belum lunas & due_date lewat.
    # 8 Nov 2026 (keputusan owner): lewat jatuh tempo = jatuh tempo SEBELUM hari ini (WIB). Faktur yang jatuh
    # tempo HARI INI belum terlambat (dulu `$lte` → 6 faktur/111 jt vs 5/88,4 jt di Umur piutang & Ringkasan).
    ar_overdue_pipeline = [
        {"$match": ar_overdue_match(today_wib().isoformat())},  # FIN-09
        {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$balance", 0]}}, "count": {"$sum": 1}}},
    ]
    ar_rows = await db.rahaza_ar_invoices.aggregate(ar_overdue_pipeline).to_list(1)
    ar_data = ar_rows[0] if ar_rows else {}

    # 2026-11-02 (audit No.51): dulu Σ `total` faktur (termasuk PPN 11%) dan pencairan marketplace
    # tidak terbaca (revenue 0 untuk toko online). Kini dari akun pendapatan GL.
    revenue = await _gl_revenue(db, start, end)
    net_income = round(revenue + pl_totals["other_income"] - total_expenses, 2)  # = laba bersih L/R

    return {
        "revenue_rp": revenue,
        "revenue_source": "gl_revenue_accounts",
        "invoice_revenue_dpp_rp": round(float(rev_data.get("total_dpp") or 0), 2),
        "invoice_revenue_gross_rp": round(float(rev_data.get("total_revenue") or 0), 2),
        "paid_revenue_rp": float(rev_data.get("total_paid") or 0),
        "invoice_count": int(rev_data.get("invoice_count") or 0),
        "total_expenses_rp": total_expenses,
        "other_income_rp": round(pl_totals["other_income"], 2),
        "gross_profit_rp": round(revenue - pl_totals["cogs"], 2),
        "net_income_rp": net_income,
        "net_income_source": "gl_profit_loss",
        "profit_margin_pct": round(net_income / max(revenue, 1) * 100, 1),
        "ar_overdue_rp": float(ar_data.get("total") or 0),
        "ar_overdue_count": int(ar_data.get("count") or 0),
    }


# ---------------------------------------------------------------------------
# Production aggregations
# ---------------------------------------------------------------------------
async def _production_kpis(db, year: int, month: int) -> dict:
    start, end = _month_range(year, month)
    # T-03 (FASE 3): SSOT production_jobs via core.wo_reader (start_date = created_at job).
    from core.wo_reader import load_wos
    wo_by_status: dict = {}
    for w in await load_wos(db, extra_filter={"created_at": {"$gte": start, "$lte": end + "T23:59:59+00:00"}}):
        b = wo_by_status.setdefault(w["status"], {"count": 0, "qty": 0, "completed": 0})
        b["count"] += 1
        b["qty"] += w.get("qty") or 0
        b["completed"] += w.get("completed_qty") or 0

    total_wo = sum(v["count"] for v in wo_by_status.values())
    completed_wo = wo_by_status.get("completed", {}).get("count", 0)
    active_wo = sum(v["count"] for k, v in wo_by_status.items() if k in ("in_progress", "pending", "released", "planned"))
    total_qty = sum(v["qty"] for v in wo_by_status.values())
    total_completed = sum(v["completed"] for v in wo_by_status.values())

    # CMT/Maklon orders — RC-02: SSOT dewi_maklon_pos (dewi_cmt_orders = phantom tanpa writer)
    cmt_count = await db.dewi_maklon_pos.count_documents(
        {"po_date": {"$gte": start, "$lte": end}}
    )

    # QC defect rate — T-17 (FASE 3): SSOT inspeksi penerimaan FG dari CMT (core.qc_reader);
    # rahaza_qc_events tak pernah ditulis sehingga angka ini selalu 0.
    from core.qc_reader import qc_summary
    qc = await qc_summary(db, d_start=start, d_end=end)
    total_inspected = float(qc["checked"])
    total_defects = float(qc["fail"])
    defect_rate = round(total_defects / max(total_inspected, 1) * 100, 2)

    return {
        "total_wo": total_wo,
        "completed_wo": completed_wo,
        "active_wo": active_wo,
        "completion_rate_pct": round(completed_wo / max(total_wo, 1) * 100, 1),
        "total_qty_ordered": total_qty,
        "total_qty_completed": total_completed,
        "fulfillment_rate_pct": round(total_completed / max(total_qty, 1) * 100, 1),
        "cmt_orders": cmt_count,
        "defect_rate_pct": defect_rate,
    }


# ---------------------------------------------------------------------------
# HR aggregations
# ---------------------------------------------------------------------------
async def _hr_kpis(db, year: int, month: int) -> dict:
    start, end = _month_range(year, month)

    # 2026-11-02 (K33): penulis karyawan memakai `active: True` — field `employment_status` tidak
    # pernah ditulis (seed: 0 dokumen) sehingga kartu "karyawan aktif" selalu 0.
    total_active = await db.rahaza_employees.count_documents({"active": True})

    # Attendance rate — RC-01: SSOT live rahaza_attendance_events (status hadir/izin/sakit;
    # 'present' ikut dihitung utk kompatibilitas seed demo)
    att_pipeline = [
        {"$match": {"date": {"$gte": start, "$lte": end}}},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
        }},
    ]
    att_rows = await db.rahaza_attendance_events.aggregate(att_pipeline).to_list(20)
    att_by_status: dict = {s["_id"]: s["count"] for s in att_rows}
    present = sum(v for k, v in att_by_status.items() if k in ("present", "hadir", "H"))
    absent = att_by_status.get("absent", 0) + att_by_status.get("alpha", 0)
    total_att = sum(att_by_status.values())
    attendance_rate = round(present / max(total_att, 1) * 100, 1)

    # Overtime hours — RC-01: SSOT rahaza_overtime_requests (field hours, status approved)
    ot_pipeline = [
        {"$match": {"date": {"$gte": start, "$lte": end}, "status": "approved"}},
        {"$group": {"_id": None, "total_hours": {"$sum": {"$ifNull": ["$hours", 0]}}}},
    ]
    ot_rows = await db.rahaza_overtime_requests.aggregate(ot_pipeline).to_list(1)
    ot_hours = ot_rows[0]["total_hours"] if ot_rows else 0

    # New hires this month
    new_hires = await db.rahaza_employees.count_documents(
        {"join_date": {"$gte": start, "$lte": end}}
    )

    # Payroll total (finalized runs this month)
    # 2026-11-02: dulu `created_at` (datetime) dibandingkan dengan string tanggal → selalu 0.
    # Bulan gaji ditentukan oleh akhir periode run (string YYYY-MM-DD), bukan kapan run dibuat.
    payroll_pipeline = [
        {"$match": {"status": "finalized", "period_to": {"$gte": start, "$lte": end}}},
        {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$total_net_pay", {"$ifNull": ["$total_net", 0]}]}}}},  # FIN-09: penulis menulis total_net
    ]
    pr_rows = await db.rahaza_payroll_runs.aggregate(payroll_pipeline).to_list(1)
    payroll_total = pr_rows[0]["total"] if pr_rows else 0

    return {
        "total_active_employees": total_active,
        "new_hires": new_hires,
        "attendance_rate_pct": attendance_rate,
        "absent_count": absent,
        "overtime_hours": round(float(ot_hours), 1),
        "payroll_total_rp": payroll_total,
    }


# ---------------------------------------------------------------------------
# Marketing aggregations
# ---------------------------------------------------------------------------
async def _marketing_kpis(db, year: int, month: int) -> dict:
    start, end = _month_range(year, month)

    # Live sessions — RC-02: field SSOT = gmv/total_orders; session_date string "YYYY-MM-DD"
    live_pipeline = [
        {"$match": {"session_date": {"$gte": start, "$lte": end}}},
        {"$group": {
            "_id": None,
            "total_sessions": {"$sum": 1},
            "total_revenue": {"$sum": {"$ifNull": ["$gmv", 0]}},
            "total_orders": {"$sum": {"$ifNull": ["$total_orders", 0]}},
        }},
    ]
    live_rows = await db.marketing_live_sessions.aggregate(live_pipeline).to_list(1)
    live_data = live_rows[0] if live_rows else {}

    # Webhook orders (from marketplace)
    webhook_orders = await db.marketing_orders.count_documents(
        {"created_at": {"$gte": start, "$lte": end}, "source": "webhook"}
    )

    # ── F10 (2026-08-13) — METRIK MATI DIGANTI SUMBER YANG BENAR ─────────────
    # Sebelumnya di sini ada hitungan koleksi `marketing_kol_campaigns`
    # yang hasilnya bahkan TIDAK pernah dipakai. Koleksi itu tidak pernah ditulis
    # oleh satu pun jalur aplikasi — jadi metrik "kampanye KOL" adalah metrik mati:
    # selalu 0, dan pembaca laporan menyimpulkan "bulan ini tidak ada kampanye".
    # Sumber yang benar untuk pekerjaan kreator adalah kalender konten (F7).
    # `start`/`end` di modul ini adalah string "YYYY-MM-DD" (lihat `_month_range`),
    # sama bentuknya dengan `marketing_content_calendar.date` — jadi bisa dibandingkan
    # langsung tanpa konversi (dan tanpa jebakan zona waktu).
    posted_q = {"status": "posted", "date": {"$gte": start, "$lte": end}}
    content_posted = await db.marketing_content_calendar.count_documents(posted_q)
    creators_rows = await db.marketing_content_calendar.distinct("creator_id", posted_q)
    content_gmv = 0.0
    async for c in db.marketing_content_calendar.find(
            {**posted_q, "kpi.gmv": {"$gt": 0}}, {"_id": 0, "kpi": 1}):
        content_gmv += float((c.get("kpi") or {}).get("gmv") or 0)

    return {
        "live_sessions": int(live_data.get("total_sessions") or 0),
        "live_revenue_rp": float(live_data.get("total_revenue") or 0),
        "live_orders": int(live_data.get("total_orders") or 0),
        "marketplace_orders_via_webhook": webhook_orders,
        # pekerjaan kreator — menggantikan metrik mati `marketing_kol_campaigns`
        "content_posted": content_posted,
        "active_creators": len([c for c in creators_rows if c]),
        # GMV KPI konten (angka PLATFORM). JANGAN dijumlah dengan omzet pesanan —
        # itu menghitung satu penjualan dua kali (aturan yang sama seperti F7.4).
        "content_gmv_kpi_rp": round(content_gmv, 2),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/summary")
async def executive_summary(
    request: Request,
    year: int = Query(default=None, ge=1970, le=2999),
    month: int = Query(default=None, ge=1, le=12),
):
    """Full cross-module executive snapshot for given year/month (default: current month)."""
    await require_exec_report(request)  # K33
    db = get_db()
    now = _now()
    wib = now_wib()   # periode bawaan = bulan berjalan WIB (No.54a)
    y = year or wib.year
    m = month or wib.month

    prev_y, prev_m = _prev_month(y, m)
    start, end = _month_range(y, m)

    # Parallel fetch all domains
    import asyncio
    finance, production, hr = await asyncio.gather(
        _finance_kpis(db, y, m),
        _production_kpis(db, y, m),
        _hr_kpis(db, y, m),
    )

    # Marketing (sequential to avoid db.list_collection_names issues)
    try:
        marketing = await _marketing_kpis(db, y, m)
    except Exception as e:
        logger.warning("Marketing KPI error: %s", e)
        marketing = {"live_sessions": 0, "live_revenue_rp": 0, "live_orders": 0, "marketplace_orders_via_webhook": 0}

    # Prev period finance for delta
    try:
        prev_finance = await _finance_kpis(db, prev_y, prev_m)
    except Exception:
        prev_finance = {"revenue_rp": 0}

    return {
        "ok": True,
        "period": {"year": y, "month": m, "label": f"{y}-{m:02d}", "range": {"from": start, "to": end}},
        "finance": {
            **finance,
            "revenue_delta_vs_prev_pct": _delta_pct(finance["revenue_rp"], prev_finance["revenue_rp"]),
        },
        "production": production,
        "hr": hr,
        "marketing": marketing,
        "generated_at": now.isoformat(),
    }


def metrics_for_ai(metrics: dict) -> str:
    """Isi prompt narasi eksekutif TANPA nominal total gaji (audit AI 7 Nov 2026).

    `sdm.payroll_total_rp` diganti kisaran kasar (`kisaran_biaya_tenaga_kerja`), lalu `ai_json` membuang kunci
    gaji/payroll yang tersisa (pertahanan berlapis K27). `metrics` milik respons layar tidak diubah."""
    from services.ai.privacy import ai_json, rupiah_band
    sdm = dict(metrics.get("sdm") or {})
    total = sdm.pop("payroll_total_rp", None)
    if total:
        sdm["kisaran_biaya_tenaga_kerja"] = rupiah_band(total)
    return ai_json({**metrics, "sdm": sdm}, indent=None)


@router.get("/ai-narrative")
async def executive_ai_narrative(
    request: Request,
    year: int = Query(default=None, ge=1970, le=2999),
    month: int = Query(default=None, ge=1, le=12),
    refresh: bool = Query(default=False),
):
    """WS-B (a) — AI-generated executive narrative + strategic recommendations.

    Reuses the same cross-module KPI data as /summary, then asks the central AI
    wrapper (tier 'executive' = Opus) to produce a concise management report.
    Cached 1h per period (bypass with refresh=true).
    """
    user = await require_exec_report(request)  # K33
    db = get_db()
    now = _now()
    wib = now_wib()   # periode bawaan = bulan berjalan WIB (No.54a)
    y = year or wib.year
    m = month or wib.month
    prev_y, prev_m = _prev_month(y, m)

    import asyncio
    finance, production, hr = await asyncio.gather(
        _finance_kpis(db, y, m),
        _production_kpis(db, y, m),
        _hr_kpis(db, y, m),
    )
    try:
        marketing = await _marketing_kpis(db, y, m)
    except Exception:
        marketing = {}
    try:
        prev_finance = await _finance_kpis(db, prev_y, prev_m)
    except Exception:
        prev_finance = {"revenue_rp": 0}

    metrics = {
        "periode": f"{y}-{m:02d}",
        "keuangan": {
            **finance,
            "revenue_delta_vs_prev_pct": _delta_pct(finance.get("revenue_rp", 0), prev_finance.get("revenue_rp", 0)),
        },
        "produksi": production,
        "sdm": hr,
        "marketing": marketing,
    }

    system = (
        "Anda adalah analis bisnis eksekutif untuk CV. Dewi Aditya, sebuah perusahaan "
        "garment dengan dua lini: produksi Internal dan jasa Maklon (CMT). "
        "Berdasarkan data KPI lintas divisi (JSON) untuk periode berjalan, tulis LAPORAN "
        "EKSEKUTIF ringkas dalam Bahasa Indonesia, format Markdown, dengan struktur PERSIS:\n"
        "## Ringkasan Eksekutif\n(2-3 kalimat kondisi bisnis periode ini)\n"
        "## Sorotan per Divisi\n- **Keuangan**: ...\n- **Produksi**: ...\n- **SDM**: ...\n- **Marketing**: ...\n"
        "(sebutkan angka kunci & bandingkan tren bila ada delta)\n"
        "## Risiko & Perhatian\n(bullet singkat)\n"
        "## Rekomendasi Strategis\n(3-5 bullet actionable, urut prioritas)\n\n"
        "Aturan: tulis nominal dengan format Rupiah Indonesia (mis. Rp 1.500.000). "
        "JANGAN mengarang data di luar yang diberikan; bila nilai 0/kosong, sampaikan apa adanya "
        "dan beri saran perbaikan. Biaya tenaga kerja hanya diberikan sebagai kisaran; sebutkan kisarannya, "
        "jangan menebak angka pastinya. Maksimal ~400 kata."
    )

    from services.ai import cached_call_claude

    extra = [f"{y}-{m:02d}"]
    if refresh:
        extra.append(now.isoformat())  # force cache miss for a fresh generation

    try:
        res = await cached_call_claude(
            db,
            system_message=system,
            user_message=metrics_for_ai(metrics),
            cache_namespace="exec_narrative",
            cache_key_extra=extra,
            ttl_seconds=3600,
            session_tag="executive-narrative",
            tier="executive",
            user_id=user.get("id"),  # 2026-11-07: Monitor AI tahu pemicunya
        )
    except Exception as e:
        # Surface AI/budget errors gracefully so the KPI dashboard still works.
        from fastapi import HTTPException as _HTTPExc
        if isinstance(e, _HTTPExc):
            raise
        logger.warning("Executive AI narrative failed: %s", e)
        return {
            "ok": False,
            "period": metrics["periode"],
            "narrative": "",
            "error": str(e),
            "generated_at": now.isoformat(),
        }

    return {
        "ok": True,
        "period": metrics["periode"],
        "narrative": res.get("text", ""),
        "cache_hit": res.get("cache_hit", False),
        "generated_at": res.get("generated_at", now.isoformat()),
        "metrics": metrics,
    }


@router.get("/kpi-comparison")
async def kpi_comparison(
    request: Request,
    months: int = Query(6, ge=2, le=24),
):
    """Month-on-month KPI comparison across the last N months."""
    await require_exec_report(request)  # K33
    db = get_db()
    now = now_wib()   # bulan-bulan dihitung dari bulan berjalan WIB (No.54a)
    results = []

    for i in range(months - 1, -1, -1):
        target = now - timedelta(days=i * 30)
        y, m = target.year, target.month
        try:
            finance = await _finance_kpis(db, y, m)
            production = await _production_kpis(db, y, m)
        except Exception as e:
            logger.warning("KPI comparison error for %d-%02d: %s", y, m, e)
            continue
        results.append({
            "period": f"{y}-{m:02d}",
            "revenue_rp": finance["revenue_rp"],
            "net_income_rp": finance["net_income_rp"],
            "wo_completed": production["completed_wo"],
            "defect_rate_pct": production["defect_rate_pct"],
            "ar_overdue_rp": finance["ar_overdue_rp"],
        })

    return {"ok": True, "months": months, "data": results}


@router.get("/finance-snapshot")
async def finance_snapshot(
    request: Request,
    year: Optional[int] = Query(None, ge=1970, le=2999),
    month: Optional[int] = Query(None, ge=1, le=12),
):
    await require_exec_report(request)  # K33
    db = get_db()
    now = now_wib()   # periode bawaan = bulan berjalan WIB (No.54a)
    y, m = (year or now.year), (month or now.month)
    data = await _finance_kpis(db, y, m)
    prev_y, prev_m = _prev_month(y, m)
    prev = await _finance_kpis(db, prev_y, prev_m)
    return {
        "ok": True,
        "period": f"{y}-{m:02d}",
        "current": data,
        "previous": prev,
        "deltas": {
            "revenue_pct": _delta_pct(data["revenue_rp"], prev["revenue_rp"]),
            "net_income_pct": _delta_pct(data["net_income_rp"], prev["net_income_rp"]),
            "ar_overdue_pct": _delta_pct(data["ar_overdue_rp"], prev["ar_overdue_rp"]),
        },
    }


@router.get("/production-snapshot")
async def production_snapshot(
    request: Request,
    year: Optional[int] = Query(None, ge=1970, le=2999),
    month: Optional[int] = Query(None, ge=1, le=12),
):
    await require_exec_report(request)  # K33
    db = get_db()
    now = now_wib()   # periode bawaan = bulan berjalan WIB (No.54a)
    y, m = (year or now.year), (month or now.month)
    data = await _production_kpis(db, y, m)
    prev_y, prev_m = _prev_month(y, m)
    prev = await _production_kpis(db, prev_y, prev_m)
    return {
        "ok": True,
        "period": f"{y}-{m:02d}",
        "current": data,
        "previous": prev,
        "deltas": {
            "completion_rate_pct": _delta_pct(data["completion_rate_pct"], prev["completion_rate_pct"]),
            "defect_rate_pct": _delta_pct(data["defect_rate_pct"], prev["defect_rate_pct"]),
        },
    }


@router.get("/hr-snapshot")
async def hr_snapshot(
    request: Request,
    year: Optional[int] = Query(None, ge=1970, le=2999),
    month: Optional[int] = Query(None, ge=1, le=12),
):
    await require_exec_report(request)  # K33
    db = get_db()
    now = now_wib()   # periode bawaan = bulan berjalan WIB (No.54a)
    y, m = (year or now.year), (month or now.month)
    data = await _hr_kpis(db, y, m)
    return {"ok": True, "period": f"{y}-{m:02d}", "data": data}


@router.get("/marketing-snapshot")
async def marketing_snapshot(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    await require_exec_report(request)  # K33
    db = get_db()
    now = now_wib()   # periode bawaan = bulan berjalan WIB (No.54a)
    y, m = (year or now.year), (month or now.month)
    try:
        data = await _marketing_kpis(db, y, m)
    except Exception as e:
        data = {"error": str(e)}
    return {"ok": True, "period": f"{y}-{m:02d}", "data": data}


@router.get("/trend")
async def executive_trend(
    request: Request,
    months: int = Query(6, ge=2, le=12),
):
    """Multi-KPI revenue + production + HR trend for last N months."""
    await require_exec_report(request)  # K33
    db = get_db()
    now = now_wib()   # bulan-bulan dihitung dari bulan berjalan WIB (No.54a)
    data = []
    for i in range(months - 1, -1, -1):
        target = now - timedelta(days=i * 30)
        y, m = target.year, target.month
        label = f"{y}-{m:02d}"
        try:
            fin = await _finance_kpis(db, y, m)
            prod = await _production_kpis(db, y, m)
            hr = await _hr_kpis(db, y, m)
        except Exception:
            continue
        data.append({
            "period": label,
            "revenue_rp": fin["revenue_rp"],
            "net_income_rp": fin["net_income_rp"],
            "ar_overdue_rp": fin["ar_overdue_rp"],
            "wo_completed": prod["completed_wo"],
            "defect_rate_pct": prod["defect_rate_pct"],
            "attendance_rate_pct": hr["attendance_rate_pct"],
            "payroll_total_rp": hr["payroll_total_rp"],
        })
    return {"ok": True, "months": months, "data": data}
