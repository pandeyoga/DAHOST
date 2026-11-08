# ruff: noqa: F401
"""
rahaza_payroll_runs.py — Payroll Run Operations
Extracted from rahaza_payroll.py (1539 LOC monolith)

Refactored: Session #11.19 Phase 3.2 Batch #4
Endpoints: GET /payroll-runs, POST /payroll-runs, GET /payroll-runs/{id}, POST finalize/post-to-gl/retry-post/pay/void-payment, DELETE, POST pay-bpjs/pay-pph21, GET export/pdf
"""
from fastapi import APIRouter, Request, HTTPException, Depends
from routes.shared import require_portal_dep
from fastapi.responses import StreamingResponse
from database import get_db
from auth import require_auth, serialize_doc, log_activity
from routes.rahaza_payroll_shared import (
    _uid, _now, VALID_SCHEMES, VALID_PERIOD_TYPES, VALID_RUN_STATUS,
    _get_applicable_allowances,
    _require_hr, _to_date, _date_range_filter,
    _generate_run_number, _compute_payslip_for_employee,
    employee_is_active, find_duplicate_run_conflicts,
    list_payment_cash_accounts, resolve_payment_account, parse_ymd,
    kasbon_deducted_elsewhere,
    run_warnings, negative_net_slips, carry_manual_adjustments, check_segregation, apply_correction_trail,
)
from routes.rahaza_posting import post_payroll_run, payroll_deduction_totals
from core.roles import FINANCE_ROLES, HR_ROLES
from utils.saga import SagaExecutor
import uuid
import io
import csv
import logging
import openpyxl
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers as xl_numbers
)
from openpyxl.utils import get_column_letter
from datetime import datetime, timezone, date, timedelta
from typing import Optional
from utils.waktu import today_wib

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rahaza", tags=["rahaza-payroll-runs"],
                   dependencies=[Depends(require_portal_dep("hr", "finance"))])  # RBAC: HR/finance (BUG-RBAC-1)

@router.get("/payroll-runs")
async def list_runs(request: Request, status: Optional[str] = None, limit: int = 50, skip: int = 0):
    await require_auth(request)
    db = get_db()
    q = {}
    if status:
        q["status"] = status
    rows = await db.rahaza_payroll_runs.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(500)
    return serialize_doc(rows)


@router.post("/payroll-runs")
async def create_run(request: Request):
    user = await _require_hr(request)
    db = get_db()
    body = await request.json()
    period_from = (body.get("period_from") or "").strip()
    period_to = (body.get("period_to") or "").strip()
    if not (period_from and period_to):
        raise HTTPException(400, "period_from & period_to wajib (YYYY-MM-DD).")
    try:
        _to_date(period_from)
        _to_date(period_to)
    except Exception:
        raise HTTPException(400, "Format tanggal harus YYYY-MM-DD.")
    if period_from > period_to:
        raise HTTPException(400, "period_from tidak boleh > period_to.")

    # Ambil profile aktif
    employee_ids = body.get("employee_ids") or []
    q = {"active": True}
    if employee_ids:
        q["employee_id"] = {"$in": employee_ids}
    profiles = await db.rahaza_payroll_profiles.find(q, {"_id": 0}).to_list(500)
    if not profiles:
        raise HTTPException(400, "Tidak ada payroll profile aktif untuk diproses. Buat profile dulu di menu Payroll Profiles.")

    emp_ids = [p["employee_id"] for p in profiles]
    emps = await db.rahaza_employees.find({"id": {"$in": emp_ids}}, {"_id": 0}).to_list(500)
    e_map = {e["id"]: e for e in emps}

    # 2026-11-02 (P5 butir 2): karyawan NONAKTIF di master SDM tidak ikut digaji walau profil gajinya
    # masih aktif. Dulu run hanya melihat status profil → Tanti (active=False) tetap dibayar 2.700.000.
    # 2026-11-06 (Tahap 2): kecuali yang KELUAR di tengah periode (tanggal keluar ≥ awal periode) — ikut run
    # periode itu dan dibayar prorata; yang belum mulai bekerja / sudah keluar sebelum periode dikecualikan.
    from routes.rahaza_payroll_rules import payroll_exclusion_reason
    pf_d, pt_d = _to_date(period_from), _to_date(period_to)
    excluded = []
    for p in profiles:
        e = e_map.get(p["employee_id"])
        reason = payroll_exclusion_reason(e, pf_d, pt_d) if e else None
        if reason:
            excluded.append({"employee_id": p["employee_id"], "employee_name": e.get("name") or "", "reason": reason})
    excluded_ids = {x["employee_id"] for x in excluded}
    profiles = [p for p in profiles if p["employee_id"] not in excluded_ids and p["employee_id"] in e_map]
    if not profiles:
        raise HTTPException(400, "Tidak ada karyawan AKTIF dengan profil gaji aktif untuk diproses"
                                 + (f" ({len(excluded)} karyawan nonaktif dikecualikan)." if excluded else "."))

    # 2026-11-02 (P5 butir 1): tolak run kedua untuk periode + skema yang sama (termasuk periode yang
    # beririsan) kecuali run sebelumnya dibatalkan (status 'cancelled'). Run draft yang salah: hapus dulu.
    conflicts = await find_duplicate_run_conflicts(db, period_from, period_to, profiles)
    if conflicts:
        runs_txt = ", ".join(sorted({f"{c['run_number']} ({c['period_from']}–{c['period_to']}, {c['run_status']})"
                                     for c in conflicts}))
        names = sorted({c["employee_name"] or c["employee_id"] for c in conflicts})
        raise HTTPException(409, (
            f"Penggajian ganda ditolak: {len(names)} karyawan sudah masuk run lain dengan periode beririsan "
            f"dan skema yang sama — {runs_txt}. Contoh: {', '.join(names[:5])}"
            f"{' …' if len(names) > 5 else ''}. Hapus run draft tersebut (atau batalkan run-nya) dulu, "
            "atau buat run hanya untuk karyawan lain."))

    # Create run header
    run_number = await _generate_run_number(db)
    run_id = _uid()
    now = _now()

    # Generate payslips
    payslips = []
    for p in profiles:
        emp = e_map.get(p["employee_id"])
        if not emp:
            continue
        slip = await _compute_payslip_for_employee(db, p, period_from, period_to, emp)
        slip.update({
            "run_id": run_id,
            "run_number": run_number,
            "created_at": now,
            "updated_at": now,
        })
        payslips.append(slip)

    # ── Saga pattern: atomic payslip insert + run header insert ─────────────────
    # Since MongoDB standalone doesn't support multi-document transactions,
    # we use a compensation saga: if run header insert fails, payslips are deleted.
    payslips_inserted = False

    total_gross = sum(s["gross_pay"] for s in payslips)
    total_ded = sum(s["deductions_total"] for s in payslips)
    total_net = sum(s["net_pay"] for s in payslips)
    # 2026-11-02 (K24) + 2026-11-06 (Tahap 2): peringatan di layar run gaji — lembur bertarif 0 / tanpa
    # pengajuan, hari kerja tanpa catatan absen, gaji bersih minus, PPh21 lebih potong, dll.
    warnings = run_warnings(payslips)

    run_doc = {
        "id": run_id,
        "run_number": run_number,
        "period_from": period_from,
        "period_to": period_to,
        "status": "draft",
        "total_employees": len(payslips),
        "total_gross": total_gross,
        "total_deductions": total_ded,
        "total_net": total_net,
        "excluded_employees": excluded,  # 2026-11-02: jejak siapa yang tidak digaji & kenapa
        "warnings": warnings,
        "notes": body.get("notes") or "",
        "created_at": now,
        "created_by": user["id"],
        "created_by_name": user.get("name", ""),
        "updated_at": now,
    }

    async def _insert_payslips():
        nonlocal payslips_inserted
        if payslips:
            await db.rahaza_payslips.insert_many(payslips)
        payslips_inserted = True

    async def _compensate_payslips():
        await db.rahaza_payslips.delete_many({"run_id": run_id})

    async def _insert_run_header():
        await db.rahaza_payroll_runs.insert_one(run_doc)

    saga = SagaExecutor(name="create_payroll_run")
    saga.add_step(
        name="insert_payslips",
        action=_insert_payslips,
        compensate=_compensate_payslips,
    )
    saga.add_step(
        name="insert_run_header",
        action=_insert_run_header,
        compensate=lambda: db.rahaza_payroll_runs.delete_one({"id": run_id}),
    )
    saga_result = await saga.execute()
    if not saga_result.success:
        log.error(f"Saga failed creating payroll run {run_number}: {saga_result.error_detail}")
        raise HTTPException(500, f"Gagal membuat payroll run: {saga_result.error_detail}")

    await log_activity(user["id"], user.get("name", ""), "create", "rahaza.payroll_run", run_number)
    out = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    return serialize_doc(out)


async def _payroll_view_mode(request: Request) -> tuple[dict, str]:
    """(user, 'detail' | 'transfer'). 2026-11-09 (Q8): rincian slip per orang hanya peran penggajian;
    Keuangan hanya total & nilai transfer; selain itu 403 (dulu cukup lolos gerbang portal SDM/Keuangan)."""
    from routes.rahaza_payroll_shared import can_view_payroll_detail, can_view_payroll_transfer
    user = await require_auth(request)
    if can_view_payroll_detail(user):
        return user, "detail"
    if can_view_payroll_transfer(user):
        return user, "transfer"
    raise HTTPException(403, "Rincian gaji per karyawan hanya untuk peran penggajian (owner, admin, HR); "
                             "Keuangan melihat total dan nilai transfer.")


async def _transfer_rows(db, payslips: list) -> list:
    from routes.rahaza_payroll_shared import transfer_row
    ids = list({s.get("employee_id") for s in payslips if s.get("employee_id")})
    emps = {e["id"]: e for e in await db.rahaza_employees.find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "employee_code": 1, "department": 1, "bank_name": 1,
                               "bank_account_number": 1, "bank_account": 1}).to_list(len(ids) or 1)} if ids else {}
    return [transfer_row(s, emps.get(s.get("employee_id"))) for s in payslips]


@router.get("/payroll-runs/{run_id}")
async def get_run(run_id: str, request: Request):
    _, mode = await _payroll_view_mode(request)
    db = get_db()
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    payslips = await db.rahaza_payslips.find({"run_id": run_id}, {"_id": 0}).sort("employee_code", 1).to_list(500)
    if mode == "transfer":
        # Keuangan: total run + nilai transfer per karyawan, tanpa komponen slip / peringatan per orang.
        safe_run = {k: v for k, v in run.items() if k not in ("warnings", "excluded_employees")}
        return serialize_doc({"run": safe_run, "payslips": [], "transfers": await _transfer_rows(db, payslips),
                              "detail_hidden": True})
    return serialize_doc({"run": run, "payslips": payslips, "transfers": await _transfer_rows(db, payslips),
                          "detail_hidden": False})


async def _json_body(request: Request) -> dict:
    """Badan JSON opsional (tombol lama mengirim POST tanpa badan)."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


@router.post("/payroll-runs/{run_id}/recalculate")
async def recalculate_run(run_id: str, request: Request):
    """Hitung ulang run DRAFT (Tahap 2, 2026-11-06): semua slip dihitung lagi dari absensi, profil gaji,
    dan pengaturan TERKINI; penyesuaian manual HR (tombol Adj) DIPERTAHANKAN. Karyawan di run tetap sama."""
    user = await _require_hr(request)
    db = get_db()
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    if run.get("status") != "draft":
        raise HTTPException(400, "Hanya run DRAFT yang bisa dihitung ulang.")
    old_slips = await db.rahaza_payslips.find({"run_id": run_id}, {"_id": 0}).to_list(1000)
    emp_ids = [s["employee_id"] for s in old_slips if s.get("employee_id")]
    prof_map = {p["employee_id"]: p for p in await db.rahaza_payroll_profiles.find(
        {"employee_id": {"$in": emp_ids}, "active": True}, {"_id": 0}).to_list(1000)}
    e_map = {e["id"]: e for e in await db.rahaza_employees.find({"id": {"$in": emp_ids}}, {"_id": 0}).to_list(1000)}
    now = _now()
    new_slips, skipped = [], []
    for old in old_slips:
        prof, emp = prof_map.get(old.get("employee_id")), e_map.get(old.get("employee_id"))
        if not prof or not emp:
            skipped.append({"employee_id": old.get("employee_id"), "employee_name": old.get("employee_name") or "",
                            "reason": "profil gaji / data karyawan tidak aktif — slip lama dipertahankan"})
            new_slips.append(old)
            continue
        fresh = await _compute_payslip_for_employee(db, prof, run["period_from"], run["period_to"], emp, run_id=run_id)
        slip = carry_manual_adjustments(old, fresh)
        if round(float(slip.get("manual_addition") or 0)) or any(d.get("adjusted") for d in slip.get("deductions") or []):
            # 2026-11-09 (H3): penyesuaian yang dibawa ikut bruto kena pajak (rumus sama dengan tombol Adj).
            from routes.rahaza_payroll_shared import _payslip_totals, recompute_slip_pph21
            slip = await recompute_slip_pph21(db, slip, emp, run_id=run_id)
            slip["deductions_total"], _net = _payslip_totals(slip)
            slip["net_pay"] = float(slip["gross_pay"]) - slip["deductions_total"]
        slip.update(run_id=run_id, run_number=run.get("run_number"), updated_at=now, recalculated_at=now)
        await db.rahaza_payslips.update_one({"id": old["id"]}, {"$set": slip})
        new_slips.append(slip)
    totals = {
        "total_employees": len(new_slips),
        "total_gross": sum(float(s.get("gross_pay") or 0) for s in new_slips),
        "total_deductions": sum(float(s.get("deductions_total") or 0) for s in new_slips),
        "total_net": sum(float(s.get("net_pay") or 0) for s in new_slips),
        "warnings": run_warnings(new_slips) + [{"type": "recalc_skipped", **x, "message": x["reason"]} for x in skipped],
        "recalculated_at": now, "recalculated_by": user["id"], "recalculated_by_name": user.get("name", ""),
        "updated_at": now,
    }
    await db.rahaza_payroll_runs.update_one({"id": run_id, "status": "draft"}, {"$set": totals})
    await log_activity(user["id"], user.get("name", ""), "recalculate", "rahaza.payroll_run",
                       f"{run.get('run_number')} — {len(new_slips)} slip")
    return serialize_doc(await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0}))


async def _apply_run_kasbon(db, run: dict, payslips: list, user: dict):
    """Catat potongan kasbon dari slip run yang SUDAH final + jurnalnya (idempoten per run_id).

    2026-11-02 (P5 butir 3/5): hanya dipanggil setelah jurnal gaji sukses (finalize / retry-post);
    kasbon yang jurnal potongannya gagal TIDAK ditandai lunas (lihat apply_payroll_deductions_core)."""
    run_id = run.get("id")
    kasbon_deds = [{"kasbon_id": d.get("kasbon_id"), "amount": d.get("amount"), "employee_id": s.get("employee_id")}
                   for s in payslips for d in (s.get("deductions") or [])
                   if (d.get("type") or "").lower() == "kasbon" and d.get("kasbon_id")]
    if not kasbon_deds:
        return None
    try:
        from routes.dewi_kasbon import apply_payroll_deductions_core
        from routes.rahaza_payroll_rules import payroll_month   # 2026-11-09 (M2)
        res = await apply_payroll_deductions_core(
            db, payroll_month(run.get("period_from"), run.get("period_to")), kasbon_deds, user,
            run_id=run_id, run_number=run.get("run_number") or "", je_date=run.get("period_to"))
        await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": {
            "kasbon_applied_at": _now(), "kasbon_applied": res.get("results"),
            "kasbon_apply_error": res.get("message")}})
        return res
    except Exception as e:  # noqa: BLE001
        log.exception("Payroll kasbon deduction apply failed")
        await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": {"kasbon_apply_error": str(e)}})
        return {"ok": False, "error": str(e)}


@router.get("/payment-cash-accounts")
async def payment_cash_accounts(request: Request):
    """2026-11-02 (P5 butir 7): daftar rekening kas/bank AKTIF yang nyata untuk semua form pembayaran
    SDM↔Keuangan (gaji, kasbon, uang muka dinas, klaim). Router ini terbuka bagi portal SDM & Keuangan."""
    await require_auth(request)
    return await list_payment_cash_accounts(get_db())


@router.post("/payroll-runs/{run_id}/finalize")
async def finalize_run(run_id: str, request: Request):
    user = await _require_hr(request)
    db = get_db()
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    if run.get("status") != "draft":
        raise HTTPException(400, f"Run sudah ber-status '{run.get('status')}', tidak bisa finalize.")
    body = await _json_body(request)
    # 2026-11-06 (Tahap 2, K25): pembuat run tidak memfinalisasi sendiri (admin/owner boleh dengan alasan).
    sod = check_segregation(run, user, "finalize", body.get("override_reason") or body.get("reason"))
    # Recalc totals dari payslips (in case deductions diubah)
    payslips = await db.rahaza_payslips.find({"run_id": run_id}, {"_id": 0}).to_list(500)
    # 2026-11-06 (Tahap 2): gaji bersih minus diblokir — daftar karyawannya disebut.
    neg = negative_net_slips(payslips)
    if neg:
        rows = "; ".join(f"{n['employee_name']} (Rp {n['net_pay']:,.0f})".replace(",", ".") for n in neg)
        raise HTTPException(400, (f"Finalisasi ditolak: {len(neg)} karyawan bergaji bersih minus — {rows}. "
                                  "Kurangi potongan lewat tombol Adj atau perbaiki datanya, lalu Hitung ulang."))
    # Tahap 1: satu cicilan kasbon per bulan hanya untuk satu run (run draft lama bisa masih dobel).
    dup_kasbon = await kasbon_deducted_elsewhere(db, run, payslips)
    if dup_kasbon:
        rows = "; ".join(f"{d['request_number']} sudah dipotong di {d['run_number']}" for d in dup_kasbon)
        raise HTTPException(409, (
            f"Finalisasi ditolak: potongan kasbon bulan {(run.get('period_to') or run.get('period_from') or '')[:7]} akan terpotong dua kali "
            f"({rows}). Hapus run draft ini lalu buat ulang — run baru tidak memotong kasbon yang sama lagi."))
    total_gross = sum(s.get("gross_pay", 0) for s in payslips)
    total_ded = sum(s.get("deductions_total", 0) for s in payslips)
    total_net = sum(s.get("net_pay", 0) for s in payslips)
    comp = payroll_deduction_totals(payslips)  # H-02: komponen potongan disimpan di run
    totals = {
        "total_gross": total_gross,
        "total_deductions": total_ded,
        "total_net": total_net,
        "total_pph21": comp["pph21"],
        "total_bpjs_employee": comp["bpjs"],
        "total_kasbon": comp["kasbon"],
        "total_other_deductions": comp["other"],
        "deductions_by_type": comp["by_type"],
    }
    # 2026-11-02 (K22): iuran BPJS perusahaan dari slip + status saklar owner SAAT finalisasi.
    from routes.rahaza_payroll_settings import get_bpjs_settings
    bpjs_cfg = await get_bpjs_settings(db)
    er_kes = round(sum(float((s.get("bpjs_employer") or {}).get("kes_total") or 0) for s in payslips), 2)
    er_tk = round(sum(float((s.get("bpjs_employer") or {}).get("tk_total") or 0) for s in payslips), 2)
    totals["bpjs_employer_totals"] = {"kes": er_kes, "tk": er_tk, "total": round(er_kes + er_tk, 2)}
    totals["bpjs_employer_journal"] = bool(bpjs_cfg.get("employer_contribution_journal"))

    # ── 2026-11-02 (P5 butir 3): JURNAL DULU, status final SESUDAH jurnal sukses.
    # Dulu status 'finalized' ditulis lebih dulu lalu jurnal dicoba; bila jurnal ditolak (mis. tanggal
    # >31 hari ke depan, komponen potongan tak konsisten) run tetap 'finalized' TANPA jurnal dan kasbon
    # karyawan ditandai lunas walau gajinya tidak pernah dibukukan. Sekarang: gagal → tetap DRAFT, kasbon
    # tidak disentuh, pesan galat jelas. post_payroll_run idempoten (source_ref payroll:{run_id}).
    candidate = {**run, **totals}
    try:
        posting_result = await post_payroll_run(db, candidate, user)
    except Exception as e:  # noqa: BLE001
        log.exception("Payroll auto-post failed")
        posting_result = {"ok": False, "error": str(e)}
    if not (posting_result or {}).get("ok"):
        err = (posting_result or {}).get("error") or "posting jurnal gagal"
        await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": {
            "post_error": err, "post_error_at": _now(), "updated_at": _now()}})
        raise HTTPException(400, (
            f"Finalisasi DIBATALKAN — jurnal gaji gagal diposting: {err} "
            "Run tetap DRAFT dan potongan kasbon belum dicatat. Perbaiki penyebabnya lalu finalisasi ulang."))

    fin_set = {
        **totals,
        "status": "finalized",
        "finalized_at": _now(),
        "finalized_by": user["id"],
        "finalized_by_name": user.get("name", ""),
        "updated_at": _now(),
    }
    if sod:
        fin_set["sod_overrides"] = list(run.get("sod_overrides") or []) + [sod]
    await db.rahaza_payroll_runs.update_one({"id": run_id, "status": "draft"}, {"$set": fin_set})
    await log_activity(user["id"], user.get("name", ""), "finalize", "rahaza.payroll_run",
                       (run.get("run_number") or "") + (f" — pengecualian pemisahan tugas: {sod['reason']}" if sod else ""))
    # 2026-11-06 (Tahap 2): absensi periode ini kini terkunci (is_attendance_locked); koreksi absen periode
    # final sebelumnya yang dibawa run ini ditandai sudah dibayar.
    await apply_correction_trail(db, payslips)

    # ── Iter 119 (B-07): potongan kasbon di slip → saldo kasbon berkurang + JE Dr Hutang Gaji / Cr Piutang.
    # Sebelumnya tidak ada yang memanggil ini ⇒ kasbon dipotong lagi di run berikutnya & 2-1200 tersisa.
    kasbon_result = await _apply_run_kasbon(db, run, payslips, user)
    out = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    try:
        from routes.rahaza_notifications import publish_notification
        # Kumpulkan user_id dari employees dalam run
        payslip_emps = await db.rahaza_payslips.find(
            {"run_id": run_id}, {"_id": 0, "id": 1, "employee_id": 1, "net_pay": 1}
        ).to_list(500)
        emp_ids_in_run = [s["employee_id"] for s in payslip_emps]
        from routes.rahaza_payroll_rules import payroll_month
        from utils.waktu import periode_label
        _periode_gaji = periode_label(payroll_month(out.get("period_from"), out.get("period_to")))
        if emp_ids_in_run:
            # Tahap 1: proyeksi WAJIB memuat `id` — dulu tanpa `id`, slip tidak pernah cocok sehingga
            # kabar selalu berbunyi "Rp 0", dan tautannya ke layar Kehadiran (bukan Slip Gaji).
            linked_emps = await db.rahaza_employees.find(
                {"id": {"$in": emp_ids_in_run}, "user_id": {"$exists": True, "$ne": None}},
                {"_id": 0, "id": 1, "user_id": 1, "name": 1}
            ).to_list(500)
            slip_by_emp = {s["employee_id"]: s for s in payslip_emps}
            for le in linked_emps:
                slip = slip_by_emp.get(le.get("id")) or {}
                net = f"{round(float(slip.get('net_pay') or 0)):,}".replace(",", ".")
                await publish_notification(
                    db,
                    type_="payslip_ready",
                    severity="info",
                    title="Slip gaji tersedia",
                    message=(
                        # 2026-11-09 (M2): bulan gaji = bulan tanggal akhir periode ("November 2026")
                        f"Slip gaji {_periode_gaji} sudah tersedia. "
                        f"Gaji bersih diterima: Rp {net}."
                    ),
                    link_module="portal-payslip",
                    link_id=slip.get("id"),
                    target_user_ids=[le["user_id"]],
                    dedup_key=f"payslip_ready_{run_id}_{le['user_id']}",
                )
    except Exception as ne:
        log.warning(f"[payroll] payslip notif failed: {ne}")

    out["_posting_result"] = posting_result
    out["_kasbon_result"] = kasbon_result
    return serialize_doc(out)


@router.post("/payroll-runs/{run_id}/post-to-gl")
async def retry_post_payroll(run_id: str, request: Request):
    """F3: manual retry post payroll run to GL (idempotent)."""
    user = await _require_hr(request)
    db = get_db()
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    if run.get("status") != "finalized":
        raise HTTPException(400, "Hanya run yang sudah finalized yang bisa di-post.")
    result = await post_payroll_run(db, run, user)
    # 2026-11-02 (P5 butir 3): run lama yang final tanpa jurnal — begitu jurnal gaji akhirnya sukses,
    # potongan kasbonnya dicatat (idempoten per run_id; yang sudah tercatat dilewati).
    kasbon_result = None
    if result.get("ok"):
        payslips = await db.rahaza_payslips.find({"run_id": run_id}, {"_id": 0}).to_list(500)
        kasbon_result = await _apply_run_kasbon(db, run, payslips, user)
    out = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    out["_posting_result"] = result
    out["_kasbon_result"] = kasbon_result
    return serialize_doc(out)


@router.post("/payroll-runs/{run_id}/retry-post")
async def retry_post_alias(run_id: str, request: Request):
    """Alias untuk /post-to-gl (backward compat frontend)."""
    return await retry_post_payroll(run_id, request)


@router.post("/payroll-runs/{run_id}/pay")
async def pay_payroll_run(run_id: str, request: Request):
    """
    Tandai gaji sebagai sudah dibayar dan buat Payment JE.
    Dr 2-1200 Hutang Gaji / Cr [bank_account_code].
    Body: { payment_date, bank_account_code, payment_method, notes }
    """
    user = await _require_hr(request)
    db   = get_db()
    body = await request.json()

    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    if run.get("status") != "finalized":
        raise HTTPException(400, "Hanya run FINALIZED yang bisa dibayar.")
    if run.get("payment_status") == "paid":
        raise HTTPException(400,
            f"Penggajian {run.get('run_number')} sudah dibayar "
            f"({run.get('payment_gl_je_number')}). "
            "Gunakan void-payment untuk membatalkan.")
    # 2026-11-06 (Tahap 2, K25): pembuat run tidak membayar sendiri (admin/owner boleh dengan alasan).
    sod = check_segregation(run, user, "pay", body.get("override_reason"))

    payment_date   = (body.get("payment_date") or str(today_wib()))[:10]
    # L-03: default bank dari profil posting payroll_payment (bukan hard-code)
    from routes.rahaza_posting_profiles import get_mapping as _get_mapping
    _pp_map = await _get_mapping(db, "payroll_payment")
    payment_method = body.get("payment_method") or "bank_transfer"
    notes          = (body.get("notes") or "").strip()

    # 2026-11-02 (P5 butir 4): rekening bayar gaji WAJIB akun kas/bank postable. Dulu akun aktif apa pun
    # diterima → bayar ke 6-2900 (beban) menghasilkan JE Dr 2-1200 / Cr 6-2900 57.972.992.
    acc = await resolve_payment_account(
        db, cash_account_id=body.get("cash_account_id"), gl_code=body.get("bank_account_code"),
        default_code=_pp_map.get("credit_bank_default"), purpose="Pembayaran gaji")
    bank_code = acc["gl_code"]
    bank_acc = {"name": acc["name"]}

    from routes.rahaza_posting import post_payroll_payment
    result = await post_payroll_payment(db, run, payment_date, bank_code, user)

    update = {
        "payment_status":       "paid" if result.get("ok") else "payment_error",
        "payment_method":       payment_method,
        "payment_date":         payment_date,
        "payment_bank_code":    bank_code,
        "payment_bank_name":    bank_acc.get("name", ""),
        "payment_notes":        notes,
        "payment_gl_je_id":     result.get("je_id"),
        "payment_gl_je_number": result.get("je_number"),
        "payment_error":        result.get("error"),
        "paid_at":              _now(),
        "paid_by":              user["id"],
        "paid_by_name":         user.get("name", ""),
        "updated_at":           _now(),
    }
    if sod:
        update["sod_overrides"] = list(run.get("sod_overrides") or []) + [sod]
    await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": update})
    await log_activity(user["id"], user.get("name", ""), "pay_payroll", "rahaza.payroll_run",
                       f"{run.get('run_number')} → {bank_code} {payment_date}")
    out = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    out["_payment_result"] = result
    return serialize_doc(out)


@router.post("/payroll-runs/{run_id}/void-payment")
async def void_payroll_payment_endpoint(run_id: str, request: Request):
    """
    Batalkan jurnal pembayaran gaji (void payment JE).
    Hanya bisa dilakukan jika payment JE masih aktif.
    Body: { reason }
    """
    user = await _require_hr(request)
    db   = get_db()
    body = await request.json()
    reason = body.get("reason") or "Pembatalan pembayaran gaji"

    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    if run.get("payment_status") != "paid":
        raise HTTPException(400, "Tidak ada pembayaran aktif yang bisa dibatalkan.")

    from routes.rahaza_posting import void_payroll_payment
    # Tahap 1 (2026-11-06): hasil pembatalan jurnal WAJIB diperiksa. Dulu kegagalan (mis. periode
    # jurnal pembayaran sudah ditutup) diabaikan lalu status tetap diubah 'void' ⇒ run tampak belum
    # dibayar padahal jurnal pembayarannya masih aktif, dan gaji bisa dibayar dua kali.
    res = await void_payroll_payment(db, run_id, user, reason) or {}
    if not res.get("ok"):
        raise HTTPException(400, (
            f"Pembatalan pembayaran {run.get('run_number') or ''} gagal: "
            f"{res.get('error') or 'jurnal pembayaran tidak bisa dibatalkan.'} "
            "Status tetap sudah dibayar. Perbaiki penyebabnya (mis. minta Keuangan membuka kembali "
            "periode jurnal pembayaran), lalu ulangi.").replace("  ", " "))
    await db.rahaza_payroll_runs.update_one(
        {"id": run_id},
        {"$set": {"payment_status": "void", "updated_at": _now()}}
    )
    await log_activity(user["id"], user.get("name", ""), "void_payment", "rahaza.payroll_run",
                       f"{run.get('run_number')} — {reason}")
    out = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    return serialize_doc(out)


@router.delete("/payroll-runs/{run_id}")
async def delete_run(run_id: str, request: Request):
    await _require_hr(request)
    db = get_db()
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    if run.get("status") != "draft":
        # 2026-11-02 (K34): run FINAL dibatalkan lewat POST /payroll-runs/{id}/cancel (jurnal pembalik);
        # run yang sudah dibatalkan disimpan sebagai jejak audit.
        raise HTTPException(400, f"Run berstatus '{run.get('status')}' tidak bisa dihapus. Run FINAL dibatalkan "
                                 "lewat tombol Batalkan Run (jurnal pembalik); hanya run DRAFT yang bisa dihapus.")
    await db.rahaza_payslips.delete_many({"run_id": run_id})
    await db.rahaza_payroll_runs.delete_one({"id": run_id})
    return {"status": "deleted"}


BPJS_AGENCY_LABELS = {"kes": "BPJS Kesehatan", "tk": "BPJS Ketenagakerjaan"}


async def _run_bpjs_breakdown(db, run: dict) -> dict:
    """Rincian hutang BPJS per lembaga untuk satu run FINAL.

    Run baru: `bpjs_breakdown` yang disimpan saat jurnal finalisasi dibuat (akun & nilai = jurnal).
    Run lama (sebelum 2026-11-02): potongan per tipe dari slip, akun = `credit_bpjs_payable` (2-1500)
    karena jurnal finalisasinya dulu mengkredit satu akun itu; iuran perusahaan = 0 (tidak dijurnal)."""
    if run.get("bpjs_breakdown"):
        return run["bpjs_breakdown"]
    from routes.rahaza_posting import payroll_bpjs_breakdown
    from routes.rahaza_posting_profiles import get_mapping
    fin_map = await get_mapping(db, "payroll_finalize")
    by_type = run.get("deductions_by_type")
    if by_type is None:
        slips = await db.rahaza_payslips.find({"run_id": run["id"]}, {"_id": 0, "deductions": 1}).to_list(2000)
        by_type = payroll_deduction_totals(slips)["by_type"]
    return payroll_bpjs_breakdown(by_type, None, {"credit_bpjs_payable": fin_map.get("credit_bpjs_payable")}, False)


@router.post("/payroll-runs/{run_id}/pay-bpjs")
async def pay_bpjs(run_id: str, request: Request):
    """
    Bayar BPJS dari payroll run ini — PER LEMBAGA (K22, 2026-11-02).
    Nilai = potongan karyawan + iuran perusahaan yang sudah dijurnal untuk lembaga itu.
    Dr Hutang BPJS lembaga (2-1501 Kes / 2-1502 TK; run lama 2-1500) / Cr rekening kas/bank dipilih.
    Body: { agency: 'kes'|'tk', cash_account_id | bank_account_code, payment_date (YYYY-MM-DD), notes }
    """
    user = await _require_hr(request)
    db   = get_db()
    body = await request.json()
    agency = (body.get("agency") or "").strip().lower()
    if agency not in BPJS_AGENCY_LABELS:
        raise HTTPException(400, "Pilih lembaga BPJS: 'kes' (BPJS Kesehatan) atau 'tk' (BPJS Ketenagakerjaan).")
    label = BPJS_AGENCY_LABELS[agency]
    run  = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run tidak ditemukan.")
    if run.get("status") != "finalized":
        raise HTTPException(400, "Hanya run FINALIZED.")
    pays = dict(run.get("bpjs_payments") or {})
    if run.get("bpjs_payment_status") == "paid" and not pays:
        raise HTTPException(400, "BPJS run ini sudah dibayar (pembayaran gabungan versi lama).")
    if (pays.get(agency) or {}).get("status") == "paid":
        raise HTTPException(400, f"{label} run ini sudah dibayar ({pays[agency].get('je_number')}).")

    bk = await _run_bpjs_breakdown(db, run)
    part = bk.get(agency) or {}
    employee_amt = float(part.get("employee") or 0)
    employer_amt = float(part.get("employer") or 0)
    amount = round(employee_amt + employer_amt, 2)
    if amount <= 0:
        raise HTTPException(400, f"Tidak ada hutang {label} di run ini.")
    liab_code = part.get("payable_code")
    if not liab_code:
        raise HTTPException(400, f"Akun hutang {label} belum diatur di Profil Posting payroll_finalize.")

    pay_date = parse_ymd(body.get("payment_date"), field="tanggal pembayaran BPJS")
    from routes.rahaza_posting_profiles import get_mapping
    pay_map = await get_mapping(db, "payroll_payment")
    # 2026-11-02 (P5 butir 4): rekening wajib kas/bank postable.
    _acc = await resolve_payment_account(
        db, cash_account_id=body.get("cash_account_id"), gl_code=body.get("bank_account_code"),
        default_code=pay_map.get("credit_bank_default"), purpose=f"Pembayaran {label}")
    bank_code = _acc["gl_code"]

    from routes.rahaza_posting import _create_posted_je
    memo  = f"Bayar {label} {run.get('run_number')} · {run.get('period_from')}–{run.get('period_to')}"
    detail = f"karyawan {employee_amt:,.0f} + perusahaan {employer_amt:,.0f}".replace(",", ".")
    lines = [
        {"account_code": liab_code, "debit": amount, "credit": 0, "description": f"{memo} ({detail})"},
        {"account_code": bank_code, "debit": 0, "credit": amount, "description": memo},
    ]
    result = await _create_posted_je(db, pay_date, memo, "bpjs_payment", f"bpjspay:{run_id}:{agency}", lines, user)
    if not result.get("ok"):
        await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": {
            "bpjs_payment_error": result.get("error"), "updated_at": _now()}})
        raise HTTPException(400, f"Pembayaran {label} TIDAK dicatat — jurnal gagal: {result.get('error')}")

    pays[agency] = {
        "status": "paid", "date": pay_date.isoformat(), "amount": amount,
        "employee": employee_amt, "employer": employer_amt,
        "je_id": result.get("je_id"), "je_number": result.get("je_number"),
        "account_code": bank_code, "account_name": _acc.get("name"), "cash_account_id": _acc.get("cash_account_id"),
        "notes": (body.get("notes") or "").strip(), "paid_by": user["id"], "paid_by_name": user.get("name", ""),
    }
    due = [a for a in BPJS_AGENCY_LABELS
           if float((bk.get(a) or {}).get("employee") or 0) + float((bk.get(a) or {}).get("employer") or 0) > 0]
    all_paid = all((pays.get(a) or {}).get("status") == "paid" for a in due)
    update = {
        "bpjs_payments":        pays,
        "bpjs_payment_status":  "paid" if all_paid else "partial",
        "bpjs_payment_date":    pay_date.isoformat(),
        "bpjs_payment_amount":  round(sum(float(p.get("amount") or 0) for p in pays.values()
                                          if p.get("status") == "paid"), 2),
        "bpjs_payment_je":      result.get("je_number"),
        "bpjs_payment_error":   None,
        "updated_at":           _now(),
    }
    await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": update})
    await log_activity(user["id"], user.get("name",""), "pay_bpjs", "rahaza.payroll_run",
                       f"{run.get('run_number')} {label} Rp {amount:,.0f}")
    out = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    out["_payment_result"] = result
    return serialize_doc(out)


@router.post("/payroll-runs/{run_id}/pay-pph21")
async def pay_pph21(run_id: str, request: Request):
    """
    Bayar PPh21 dari payroll run ini ke DJP.
    Dr 2-1301 Hutang PPh21 / Cr [bank_code].
    Body: { payment_date, bank_account_code, notes }
    """
    user = await _require_hr(request)
    db   = get_db()
    body = await request.json()
    run  = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Run tidak ditemukan.")
    if run.get("status") != "finalized":
        raise HTTPException(400, "Hanya run FINALIZED.")
    if run.get("pph21_payment_status") == "paid":
        raise HTTPException(400, "PPh21 run ini sudah dibayar.")

    payment_date = (body.get("payment_date") or str(today_wib()))[:10]
    from routes.rahaza_posting_profiles import get_mapping
    fin_map = await get_mapping(db, "payroll_finalize")
    pay_map = await get_mapping(db, "payroll_payment")
    liab_code = fin_map.get("credit_tax_pph21")
    if not liab_code:
        raise HTTPException(400, "Mapping payroll_finalize.credit_tax_pph21 belum lengkap.")

    slips = await db.rahaza_payslips.find({"run_id": run_id}, {"_id": 0, "deductions": 1}).to_list(500)
    pph_total = payroll_deduction_totals(slips)["pph21"]

    if pph_total <= 0:
        raise HTTPException(400, "Tidak ada potongan PPh21 di run ini.")

    # 2026-11-02 (P5 butir 4): rekening wajib kas/bank postable.
    _acc = await resolve_payment_account(
        db, cash_account_id=body.get("cash_account_id"), gl_code=body.get("bank_account_code"),
        default_code=pay_map.get("credit_bank_default"), purpose="Pembayaran PPh21")
    bank_code = _acc["gl_code"]

    from routes.rahaza_posting import _create_posted_je
    run_id_ref = f"pph21pay:{run_id}"
    try:
        je_date = date.fromisoformat(payment_date)
    except Exception:
        je_date = today_wib()
    memo  = f"Bayar PPh21 {run.get('run_number')} · {run.get('period_from')}–{run.get('period_to')}"
    lines = [
        {"account_code": liab_code, "debit": pph_total, "credit": 0, "description": memo},
        {"account_code": bank_code, "debit": 0, "credit": pph_total, "description": memo},
    ]
    result = await _create_posted_je(db, je_date, memo, "pph21_payment", run_id_ref, lines, user)
    update = {
        "pph21_payment_status": "paid" if result.get("ok") else "error",
        "pph21_payment_date":   payment_date,
        "pph21_payment_amount": pph_total,
        "pph21_payment_je":     result.get("je_number"),
        "pph21_payment_error":  result.get("error"),
        "updated_at":           _now(),
    }
    await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": update})
    await log_activity(user["id"], user.get("name",""), "pay_pph21", "rahaza.payroll_run",
                       f"{run.get('run_number')} PPh21 Rp {pph_total:,.0f}")
    out = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    out["_payment_result"] = result
    return serialize_doc(out)


@router.post("/payroll-runs/{run_id}/void-obligation-payment")
async def void_obligation_payment(run_id: str, request: Request):
    """2026-11-02 (K34): batalkan jurnal pembayaran BPJS (per lembaga) atau PPh21 — pola yang SAMA dengan
    void-payment gaji. Diperlukan sebelum run FINAL boleh dibatalkan.
    Body: { type: 'bpjs'|'pph21', agency: 'kes'|'tk' (untuk bpjs), reason }"""
    user = await _require_hr(request)
    db = get_db()
    body = await request.json()
    kind = (body.get("type") or "").strip().lower()
    reason = (body.get("reason") or "").strip() or "Pembatalan pembayaran"
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    from routes.rahaza_posting import _void_je_by_source
    if kind == "pph21":
        if run.get("pph21_payment_status") != "paid":
            raise HTTPException(400, "Tidak ada pembayaran PPh21 aktif.")
        res = await _void_je_by_source(db, "pph21_payment", f"pph21pay:{run_id}", user, reason)
        if not res.get("ok"):
            raise HTTPException(400, f"Void gagal: {res.get('error')}")
        await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": {
            "pph21_payment_status": "void", "pph21_payment_je": None, "updated_at": _now()}})
    elif kind == "bpjs":
        pays = dict(run.get("bpjs_payments") or {})
        agency = (body.get("agency") or "").strip().lower()
        if not pays and run.get("bpjs_payment_status") == "paid":   # pembayaran gabungan versi lama
            res = await _void_je_by_source(db, "bpjs_payment", f"bpjspay:{run_id}", user, reason)
            if not res.get("ok"):
                raise HTTPException(400, f"Void gagal: {res.get('error')}")
            await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": {
                "bpjs_payment_status": "void", "bpjs_payment_je": None, "updated_at": _now()}})
        else:
            if (pays.get(agency) or {}).get("status") != "paid":
                raise HTTPException(400, f"Tidak ada pembayaran {BPJS_AGENCY_LABELS.get(agency, 'BPJS')} aktif.")
            res = await _void_je_by_source(db, "bpjs_payment", f"bpjspay:{run_id}:{agency}", user, reason)
            if not res.get("ok"):
                raise HTTPException(400, f"Void gagal: {res.get('error')}")
            pays[agency] = {**pays[agency], "status": "void", "voided_at": _now(), "void_reason": reason}
            still = any((p or {}).get("status") == "paid" for p in pays.values())
            await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": {
                "bpjs_payments": pays, "bpjs_payment_status": "partial" if still else "void", "updated_at": _now()}})
    else:
        raise HTTPException(400, "type harus 'bpjs' atau 'pph21'.")
    await log_activity(user["id"], user.get("name", ""), "void_obligation_payment", "rahaza.payroll_run",
                       f"{run.get('run_number')} {kind} {body.get('agency') or ''} — {reason}")
    return serialize_doc(await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0}))


# ─── PEMBATALAN RUN FINAL (K34, 2026-11-02) ──────────────────────────────────
# Keputusan owner: run final boleh dibatalkan oleh HR + Keuangan (dua langkah: diajukan HR, disetujui
# Keuangan — orang yang berbeda) atau satu langkah oleh owner/superadmin. Hasil: jurnal PEMBALIK untuk
# semua jurnal run (finalisasi + potongan kasbon), potongan kasbon dikembalikan, status 'cancelled'
# sehingga periode bisa dibuat ulang (find_duplicate_run_conflicts mengabaikan run cancelled).
# Ditolak bila gaji/BPJS/PPh21 run itu sudah dibayar — batalkan pembayarannya dulu.
CANCEL_ONE_STEP_ROLES = ("owner", "superadmin")


def _is_hr_actor(user: dict) -> bool:
    role = (user.get("role") or "").lower()
    perms = set(user.get("_permissions") or [])
    return role in HR_ROLES or bool(perms & {"*", "hr.manage", "payroll.manage"})


def _is_finance_actor(user: dict) -> bool:
    return (user.get("role") or "").lower() in FINANCE_ROLES


# 2026-11-02 (K30) — "PERLU TINDAKAN" untuk Keuangan: pengajuan pembatalan run gaji FINAL.
# Penerima = peran nyata Portal Keuangan (lolos `_is_finance_actor`); pengaju (HR) TIDAK ikut
# menerima. Ditutup otomatis oleh resolver (`SOURCE_RULES['payroll_cancel']`: cancel_request.status).
async def notify_payroll_cancel_request(db, run: dict, cr: dict):
    try:
        from utils.notif_unified import decider_roles, notif_insert
        return await notif_insert(
            db, type="rahaza", subtype="payroll_cancel_requested", severity="warning",
            title=f"Pembatalan run gaji {run.get('run_number') or ''} menunggu persetujuan Keuangan".replace("  ", " "),
            body=(f"{cr.get('requested_by_name') or 'HR'} mengajukan pembatalan run "
                  f"{run.get('run_number') or run.get('id')} (periode {run.get('period') or run.get('period_code') or '-'}). "
                  f"Alasan: {cr.get('reason') or '-'}. Persetujuan membuat jurnal pembalik."),
            source_type="payroll_run", source_id=run["id"], source_ref=run.get("run_number"),
            target_roles=decider_roles("finance", FINANCE_ROLES),
            exclude_user_ids=[cr.get("requested_by")] if cr.get("requested_by") else None,
            status="sent", meta={"link_module": "hr-payroll-run"})
    except Exception as ne:  # noqa: BLE001 — notifikasi tidak boleh menggagalkan pengajuan
        log.warning(f"[payroll] notif pengajuan batal run gagal: {ne}")
        return None


async def close_payroll_cancel_notifs(db, run_id: str) -> int:
    try:
        from utils.notif_unified import resolve_for_source
        return await resolve_for_source(db, "rahaza_payroll_runs", run_id)
    except Exception:  # noqa: BLE001
        return 0


def run_cancel_blockers(run: dict) -> list:
    """Alasan run belum boleh dibatalkan (murni)."""
    out = []
    if run.get("payment_status") == "paid":
        out.append(f"gaji sudah dibayar ({run.get('payment_gl_je_number') or 'JE pembayaran'}) — void pembayaran gaji dulu")
    pays = run.get("bpjs_payments") or {}
    paid_bpjs = [BPJS_AGENCY_LABELS.get(a, a) for a, p in pays.items() if (p or {}).get("status") == "paid"]
    if paid_bpjs or (not pays and run.get("bpjs_payment_status") == "paid"):
        out.append(f"{', '.join(paid_bpjs) or 'BPJS'} sudah dibayar — batalkan pembayaran BPJS dulu")
    if run.get("pph21_payment_status") == "paid":
        out.append("PPh21 sudah dibayar — batalkan pembayaran PPh21 dulu")
    return out


async def _execute_run_cancel(db, run: dict, user: dict, reason: str) -> dict:
    run_id = run["id"]
    from routes.rahaza_posting import payroll_run_journals, reverse_journal_entry
    reversed_rows, errors = [], []
    for je in await payroll_run_journals(db, run_id):
        res = await reverse_journal_entry(db, je, user, f"Batal run {run.get('run_number')}: {reason}")
        (reversed_rows if res.get("ok") else errors).append(
            {"original": je.get("je_number"), "reversal": res.get("je_number"), "date": res.get("date"),
             "error": res.get("error")})
    if errors:
        await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": {
            "cancel_error": "; ".join(f"{e['original']}: {e['error']}" for e in errors), "updated_at": _now()}})
        raise HTTPException(400, (
            "Pembatalan TERHENTI — jurnal pembalik gagal: "
            + "; ".join(f"{e['original']}: {e['error']}" for e in errors)
            + ". Run tetap FINAL; jurnal pembalik yang sudah terbentuk dipakai ulang saat diulang."))
    from routes.dewi_kasbon import restore_payroll_deductions_core
    kasbon = await restore_payroll_deductions_core(db, run_id, user, reason=reason)
    # 2026-11-06 (Tahap 2): koreksi absen yang dibawa run ini dikembalikan → dibawa lagi run berikutnya.
    await apply_correction_trail(db, await db.rahaza_payslips.find(
        {"run_id": run_id}, {"_id": 0, "corrections": 1}).to_list(1000), revert=True)
    now = _now()
    cr = dict(run.get("cancel_request") or {})
    if cr:
        cr.update(status="approved", approved_by=user["id"], approved_by_name=user.get("name", ""), approved_at=now)
    await db.rahaza_payroll_runs.update_one({"id": run_id, "status": "finalized"}, {"$set": {
        "status": "cancelled", "cancelled_at": now, "cancelled_by": user["id"],
        "cancelled_by_name": user.get("name", ""), "cancel_reason": reason, "cancel_request": cr or None,
        "cancel_reversal_jes": reversed_rows, "cancel_kasbon_restored": kasbon.get("results"),
        "cancel_error": None, "updated_at": now}})
    await log_activity(user["id"], user.get("name", ""), "cancel", "rahaza.payroll_run",
                       f"{run.get('run_number')} — {reason} — pembalik "
                       + ", ".join(r["reversal"] or "-" for r in reversed_rows))
    return {"reversals": reversed_rows, "kasbon": kasbon}


@router.post("/payroll-runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request):
    """Batalkan run FINAL (K34). Body: { action: 'request'|'approve'|'reject' (opsional), reason }.

    - HR: action 'request' (alasan wajib) → menunggu persetujuan Keuangan.
    - Keuangan (orang lain dari pengaju): 'approve' → eksekusi; 'reject' → tolak pengajuan.
    - owner/superadmin: satu langkah (tanpa pengajuan) atau menyetujui pengajuan."""
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    action = (body.get("action") or "").strip().lower()
    reason = (body.get("reason") or "").strip()
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    if run.get("status") == "cancelled":
        raise HTTPException(400, "Run ini sudah dibatalkan.")
    if run.get("status") != "finalized":
        raise HTTPException(400, "Hanya run FINAL yang dibatalkan; run DRAFT cukup dihapus.")
    role = (user.get("role") or "").lower()
    one_step = role in CANCEL_ONE_STEP_ROLES
    fin = _is_finance_actor(user)
    pending = run.get("cancel_request") if (run.get("cancel_request") or {}).get("status") == "pending" else None
    if not action:
        action = "approve" if (one_step or (fin and pending)) else "request"

    if action == "request":
        if not (_is_hr_actor(user) or one_step):
            raise HTTPException(403, "Pengajuan pembatalan run gaji dilakukan oleh HR.")
        if pending:
            raise HTTPException(400, f"Sudah ada pengajuan pembatalan oleh {pending.get('requested_by_name')} — menunggu Keuangan.")
        if not reason:
            raise HTTPException(400, "Alasan pembatalan wajib diisi.")
        blockers = run_cancel_blockers(run)
        if blockers:
            raise HTTPException(400, "Run belum bisa dibatalkan: " + "; ".join(blockers) + ".")
        cr = {"status": "pending", "reason": reason, "requested_by": user["id"],
              "requested_by_name": user.get("name", ""), "requested_at": _now()}
        await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": {"cancel_request": cr, "updated_at": _now()}})
        await log_activity(user["id"], user.get("name", ""), "cancel_request", "rahaza.payroll_run",
                           f"{run.get('run_number')} — {reason}")
        await notify_payroll_cancel_request(db, run, cr)   # 2026-11-02 (K30)
        return serialize_doc(await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0}))

    if action == "reject":
        if not pending:
            raise HTTPException(400, "Tidak ada pengajuan pembatalan yang menunggu.")
        if not (fin or one_step or user["id"] == pending.get("requested_by")):
            raise HTTPException(403, "Hanya Keuangan/owner (atau pengaju sendiri) yang boleh menolak pengajuan ini.")
        cr = {**pending, "status": "rejected", "rejected_by": user["id"], "rejected_by_name": user.get("name", ""),
              "rejected_at": _now(), "reject_reason": reason}
        await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": {"cancel_request": cr, "updated_at": _now()}})
        await close_payroll_cancel_notifs(db, run_id)   # 2026-11-02 (K30)
        return serialize_doc(await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0}))

    if action != "approve":
        raise HTTPException(400, "action harus 'request', 'approve', atau 'reject'.")
    if not one_step:
        if not fin:
            raise HTTPException(403, "Persetujuan pembatalan run gaji oleh Keuangan (atau owner).")
        if not pending:
            raise HTTPException(400, "Belum ada pengajuan pembatalan dari HR untuk run ini.")
        if user["id"] == pending.get("requested_by"):
            raise HTTPException(403, "Pemisahan tugas: pengaju pembatalan tidak boleh menyetujuinya sendiri.")
    reason = reason or (pending or {}).get("reason") or ""
    if not reason:
        raise HTTPException(400, "Alasan pembatalan wajib diisi.")
    blockers = run_cancel_blockers(run)
    if blockers:
        raise HTTPException(400, "Run belum bisa dibatalkan: " + "; ".join(blockers) + ".")
    result = await _execute_run_cancel(db, run, user, reason)
    await close_payroll_cancel_notifs(db, run_id)   # 2026-11-02 (K30)
    out = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    out["_cancel_result"] = result
    return serialize_doc(out)


@router.get("/payroll-runs/{run_id}/export-excel")
async def export_run_excel(run_id: str, request: Request):
    """Export payroll run ke Excel — 1 sheet rekapitulasi + 1 sheet per karyawan + data transfer bank.

    2026-11-09 (Q8): Keuangan (tanpa hak rincian gaji) hanya menerima lembar "Data Transfer Bank"."""
    _, mode = await _payroll_view_mode(request)
    db = get_db()
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    payslips = await db.rahaza_payslips.find(
        {"$or": [{"run_id": run_id}, {"payroll_run_id": run_id}]}, {"_id": 0}
    ).sort("employee_code", 1).to_list(500)

    # ── Style helpers ────────────────────────────────────────────────────────
    BG_HEADER   = PatternFill("solid", fgColor="1A3A5C")   # Navy gelap
    BG_SUBHDR   = PatternFill("solid", fgColor="2D6A9F")   # Biru sedang
    BG_ALTROW   = PatternFill("solid", fgColor="EBF3FB")   # Biru muda alt row
    BG_TOTAL    = PatternFill("solid", fgColor="FFF3CD")   # Kuning total
    BG_GREEN    = PatternFill("solid", fgColor="D4EDDA")   # Hijau net
    FG_WHITE    = Font(name="Calibri", color="FFFFFF", bold=True, size=10)
    FG_DARK     = Font(name="Calibri", color="1A1A1A", size=9)
    FG_DARK_B   = Font(name="Calibri", color="1A1A1A", bold=True, size=9)
    FG_TITLE    = Font(name="Calibri", color="1A3A5C", bold=True, size=14)
    FG_SUBTITLE = Font(name="Calibri", color="2D6A9F", bold=False, size=10)
    BORDER_THIN = Border(
        left=Side(style="thin", color="BBBBBB"),
        right=Side(style="thin", color="BBBBBB"),
        top=Side(style="thin", color="BBBBBB"),
        bottom=Side(style="thin", color="BBBBBB"),
    )
    BORDER_MED  = Border(
        left=Side(style="medium", color="1A3A5C"),
        right=Side(style="medium", color="1A3A5C"),
        top=Side(style="medium", color="1A3A5C"),
        bottom=Side(style="medium", color="1A3A5C"),
    )
    IDR_FMT = '#,##0'
    CENTER  = Alignment(horizontal="center", vertical="center", wrap_text=True)
    LEFT    = Alignment(horizontal="left",   vertical="center", wrap_text=True)
    RIGHT   = Alignment(horizontal="right",  vertical="center")

    def _cell(ws, row, col, value, font=None, fill=None, align=None, border=None, num_fmt=None):
        c = ws.cell(row=row, column=col, value=value)
        if font:
            c.font = font
        if fill:
            c.fill = fill
        if align:
            c.alignment = align
        if border:
            c.border = border
        if num_fmt:
            c.number_format = num_fmt
        return c

    # ── Workbook ──────────────────────────────────────────────────────────────
    wb = openpyxl.Workbook()
    run_num    = run.get("run_number", "PAYROLL")
    period_from = run.get("period_from", "")
    period_to   = run.get("period_to", "")
    period_lbl  = f"{period_from} s/d {period_to}"

    # ─────────────────────────────────────────────────────────────────────────
    # SHEET 1: Rekapitulasi
    # ─────────────────────────────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Rekapitulasi"
    ws1.freeze_panes = "A8"
    ws1.sheet_view.showGridLines = False

    # Company header
    ws1.merge_cells("A1:P1")
    _cell(ws1, 1, 1, "CV. DEWI ADITYA", font=FG_TITLE, align=CENTER)
    ws1.row_dimensions[1].height = 26

    ws1.merge_cells("A2:P2")
    _cell(ws1, 2, 1, "Jl. Garmen Indah No. 1, Solo, Jawa Tengah | Telp: (0271) 123456", font=FG_SUBTITLE, align=CENTER)

    ws1.merge_cells("A3:P3")
    _cell(ws1, 3, 1, f"SLIP GAJI REKAPITULASI — {run_num} | Periode: {period_lbl}", font=Font(name="Calibri", bold=True, size=11, color="1A3A5C"), align=CENTER)
    ws1.row_dimensions[3].height = 20

    ws1.merge_cells("A4:P4")
    ws1.row_dimensions[4].height = 8

    # Run summary box
    summary_items = [
        ("Run Number", run_num), ("Status", run.get("status","").upper()),
        ("Total Karyawan", run.get("total_employees", len(payslips))),
        ("Total Bruto", run.get("total_gross_pay", 0)),
        ("Total Potongan", run.get("total_deductions", 0)),
        ("Total Neto", run.get("total_net_pay", 0)),
    ]
    for i, (lbl, val) in enumerate(summary_items):
        col = (i % 3) * 2 + 1
        row = 5 + (i // 3)
        _cell(ws1, row, col, lbl, font=FG_DARK_B, fill=BG_SUBHDR, align=LEFT,
              border=BORDER_THIN)
        ws1.cell(row=row, column=col).font = Font(name="Calibri", color="FFFFFF", bold=True, size=9)
        c = _cell(ws1, row, col+1, val, font=FG_DARK_B, align=RIGHT, border=BORDER_THIN)
        if isinstance(val, (int, float)) and val > 1000:
            c.number_format = IDR_FMT
    ws1.row_dimensions[5].height = 18
    ws1.row_dimensions[6].height = 18

    # Empty row
    ws1.row_dimensions[7].height = 6

    # Table headers — row 8
    RECAP_COLS = [
        ("No", 4), ("NIK", 10), ("Nama Karyawan", 24), ("Departemen", 18),
        ("Skema", 10), ("Gaji Pokok", 14), ("Tunjangan", 13), ("Lembur", 11),
        ("Total Bruto", 14), ("Terlambat", 11), ("Kasbon", 11), ("BPJS Kes", 11),
        ("BPJS TK JHT", 12), ("BPJS TK JP", 11), ("PPh 21", 11),
        ("Total Potongan", 15), ("Gaji Bersih", 14),
    ]
    for ci, (hdr, w) in enumerate(RECAP_COLS, 1):
        _cell(ws1, 8, ci, hdr, font=FG_WHITE, fill=BG_HEADER, align=CENTER, border=BORDER_THIN)
        ws1.column_dimensions[get_column_letter(ci)].width = w
    ws1.row_dimensions[8].height = 36

    # FASE 15 — ambil angka dari STRUKTUR YANG MEMANG DITULIS mesin hitung
    # (`deductions[]` / `allowances[]`), bukan field datar yang tidak pernah ada.
    def _ded(slip: dict, *types: str) -> float:
        total = 0.0
        for d in (slip.get("deductions") or []):
            if d.get("type") in types:
                total += float(d.get("amount") or 0)
        return total

    # Data rows
    NUM_COLS = {6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17}  # IDR columns
    total_row = {i: 0 for i in NUM_COLS}

    for idx, slip in enumerate(payslips):
        r = 9 + idx
        fill = BG_ALTROW if idx % 2 == 1 else None
        bsalary    = slip.get("earnings_total", 0) or 0
        allowances = slip.get("allowance_total", 0) or 0
        ot_amt     = slip.get("overtime_amount", 0) or 0
        gross      = slip.get("gross_pay", 0) or 0
        late_ded   = _ded(slip, "late")
        kasbon     = _ded(slip, "kasbon")
        bpjs_kes   = _ded(slip, "bpjs_kesehatan")
        bpjs_jht   = _ded(slip, "bpjs_jht")
        bpjs_jp    = _ded(slip, "bpjs_jp")
        pph21      = _ded(slip, "pph21")
        ded_total  = slip.get("deductions_total", 0) or 0
        net        = slip.get("net_pay", 0) or 0

        vals = [
            idx+1,
            slip.get("employee_code",""),
            slip.get("employee_name",""),
            slip.get("department",""),
            slip.get("pay_scheme","monthly"),
            bsalary, allowances, ot_amt, gross,
            late_ded, kasbon, bpjs_kes, bpjs_jht, bpjs_jp, pph21, ded_total, net,
        ]
        for ci, val in enumerate(vals, 1):
            c = _cell(ws1, r, ci, val, font=FG_DARK, fill=fill, border=BORDER_THIN,
                      align=CENTER if ci <= 2 else (LEFT if ci <= 5 else RIGHT))
            if ci in NUM_COLS:
                c.number_format = IDR_FMT
                total_row[ci] = total_row.get(ci, 0) + (val or 0)

        # Net gaji hijau
        net_cell = ws1.cell(row=r, column=17)
        net_cell.fill = BG_GREEN
        net_cell.font = Font(name="Calibri", bold=True, size=9, color="155724")
        ws1.row_dimensions[r].height = 16

    # Total row
    tr = 9 + len(payslips)
    ws1.merge_cells(f"A{tr}:E{tr}")
    _cell(ws1, tr, 1, "TOTAL", font=FG_DARK_B, fill=BG_TOTAL, align=CENTER, border=BORDER_MED)
    for ci in NUM_COLS:
        c = _cell(ws1, tr, ci, total_row.get(ci, 0), font=FG_DARK_B, fill=BG_TOTAL,
                  align=RIGHT, border=BORDER_MED, num_fmt=IDR_FMT)
    ws1.row_dimensions[tr].height = 20

    # Signature block
    sig_row = tr + 3
    ws1.merge_cells(f"A{sig_row}:D{sig_row}")
    _cell(ws1, sig_row, 1, "Disetujui Oleh:", font=FG_DARK_B, align=LEFT)
    ws1.merge_cells(f"N{sig_row}:Q{sig_row}")
    _cell(ws1, sig_row, 14, "Mengetahui:", font=FG_DARK_B, align=LEFT)
    ws1.merge_cells(f"A{sig_row+4}:D{sig_row+4}")
    _cell(ws1, sig_row+4, 1, "( Manager Finance )", font=FG_DARK, align=CENTER)
    ws1.merge_cells(f"N{sig_row+4}:Q{sig_row+4}")
    _cell(ws1, sig_row+4, 14, "( Direktur )", font=FG_DARK, align=CENTER)
    ws1.merge_cells(f"A{sig_row+5}:D{sig_row+5}")
    _cell(ws1, sig_row+5, 1, "CV. Dewi Aditya", font=FG_DARK, align=CENTER)
    ws1.merge_cells(f"N{sig_row+5}:Q{sig_row+5}")
    _cell(ws1, sig_row+5, 14, "CV. Dewi Aditya", font=FG_DARK, align=CENTER)

    # ─────────────────────────────────────────────────────────────────────────
    # SHEET 2: Slip Gaji Individual (satu baris per karyawan, format slip)
    # ─────────────────────────────────────────────────────────────────────────
    ws2 = wb.create_sheet("Slip Individual")
    ws2.sheet_view.showGridLines = False
    ws2.column_dimensions["A"].width = 3
    ws2.column_dimensions["B"].width = 26
    ws2.column_dimensions["C"].width = 20
    ws2.column_dimensions["D"].width = 3
    ws2.column_dimensions["E"].width = 26
    ws2.column_dimensions["F"].width = 20

    current_row = 1
    for slip in payslips:
        # FASE 15 — BACA STRUKTUR YANG BENAR.
        # Dulu blok ini membaca field DATAR (`transport_allowance`, `meal_allowance`,
        # `bpjs_kes_employee`, `pph21_amount`, `kasbon_deduction`, …) yang TIDAK
        # PERNAH ditulis mesin hitung — mesin hitung menyimpannya sebagai DAFTAR
        # (`earnings[]`, `allowances[]`, `deductions[]`). Terbukti 2026-07-26:
        # tunjangan transport Rp 600.000 ADA di payslip tapi sel Excel-nya 0,
        # sehingga kolom Penghasilan tidak menjumlah ke Total Bruto (slip yang
        # dibagikan ke karyawan terlihat salah). Slip PDF sudah benar; sekarang
        # kedua kanal cetak membaca SUMBER YANG SAMA.
        ot_hrs    = slip.get("overtime_hours", 0) or 0
        ot_amt    = slip.get("overtime_amount", slip.get("overtime_pay", 0)) or 0
        gross     = slip.get("gross_pay", slip.get("gross_salary", 0))
        ded_total = slip.get("deductions_total", 0)
        net       = slip.get("net_pay", slip.get("net_salary", 0))

        # Sisi PENGHASILAN: setiap baris earnings + setiap tunjangan + lembur.
        left_items = [
            (e.get("label") or e.get("process_code") or "Penghasilan", e.get("amount") or 0)
            for e in (slip.get("earnings") or [])
        ]
        for a in (slip.get("allowances") or []):
            nm = a.get("name") or a.get("label") or "Tunjangan"
            if a.get("calc_type") == "per_day_attendance":
                nm = f"{nm} ({a.get('qty', 0)} hr × {int(a.get('rate') or 0):,})".replace(",", ".")
            left_items.append((nm, a.get("amount") or 0))
        if ot_amt:
            left_items.append((f"Lembur ({float(ot_hrs):.1f} jam)", ot_amt))
        if round(float(slip.get("manual_addition") or 0)):   # 2026-11-02 (K34)
            left_items.append((f"Penyesuaian ({slip.get('adjustment_notes') or '-'})", slip.get("manual_addition")))
        if not left_items:
            left_items = [("Gaji Pokok", slip.get("earnings_total", 0) or 0)]

        # Sisi POTONGAN: apa adanya dari mesin hitung (BPJS, PPh21, kasbon,
        # LWOP, keterlambatan) — tidak lagi menebak nama field.
        right_items = [
            (d.get("label") or d.get("type") or "Potongan", d.get("amount") or 0)
            for d in (slip.get("deductions") or [])
        ]
        if round(float(slip.get("manual_deduction") or 0)):  # 2026-11-02 (K34): dulu tidak tercetak
            right_items.append((f"Potongan penyesuaian ({slip.get('adjustment_notes') or '-'})", slip.get("manual_deduction")))

        r = current_row
        # Header slip
        ws2.merge_cells(f"B{r}:F{r}")
        _cell(ws2, r, 2, "CV. DEWI ADITYA — SLIP GAJI", font=Font(name="Calibri", bold=True, size=11, color="1A3A5C"), align=CENTER)
        ws2.row_dimensions[r].height = 20
        r += 1

        ws2.merge_cells(f"B{r}:F{r}")
        _cell(ws2, r, 2, f"Periode: {period_lbl}  |  {run_num}", font=FG_SUBTITLE, align=CENTER)
        ws2.row_dimensions[r].height = 14
        r += 1

        # Identitas karyawan
        info = [
            ("NIK", slip.get("employee_code","")),
            ("Nama", slip.get("employee_name","")),
            ("Departemen", slip.get("department","")),
            ("Skema", slip.get("pay_scheme","monthly")),
            ("Hari Hadir", f"{slip.get('days_hadir', slip.get('days_present', 0))} hari"),
        ]
        for lbl, val in info:
            _cell(ws2, r, 2, lbl, font=FG_DARK_B, align=LEFT)
            _cell(ws2, r, 3, val, font=FG_DARK, align=LEFT)
            ws2.row_dimensions[r].height = 14
            r += 1
        r += 1  # spacer

        # Penghasilan
        _cell(ws2, r, 2, "PENGHASILAN", font=FG_WHITE, fill=BG_HEADER, align=LEFT, border=BORDER_THIN)
        _cell(ws2, r, 3, "", fill=BG_HEADER, border=BORDER_THIN)
        _cell(ws2, r, 5, "POTONGAN", font=FG_WHITE, fill=BG_HEADER, align=LEFT, border=BORDER_THIN)
        _cell(ws2, r, 6, "", fill=BG_HEADER, border=BORDER_THIN)
        ws2.row_dimensions[r].height = 16
        r += 1

        max_rows = max(len(left_items), len(right_items))
        for i in range(max_rows):
            lbl_l, val_l = left_items[i] if i < len(left_items) else ("", "")
            lbl_r, val_r = right_items[i] if i < len(right_items) else ("", "")
            _cell(ws2, r, 2, lbl_l, font=FG_DARK, align=LEFT, border=BORDER_THIN)
            c = _cell(ws2, r, 3, val_l or "", font=FG_DARK, align=RIGHT, border=BORDER_THIN)
            if isinstance(val_l, (int, float)) and val_l:
                c.number_format = IDR_FMT
            _cell(ws2, r, 5, lbl_r, font=FG_DARK, align=LEFT, border=BORDER_THIN)
            c2 = _cell(ws2, r, 6, val_r or "", font=FG_DARK, align=RIGHT, border=BORDER_THIN)
            if isinstance(val_r, (int, float)) and val_r:
                c2.number_format = IDR_FMT
            ws2.row_dimensions[r].height = 14
            r += 1

        # Total baris
        _cell(ws2, r, 2, "Total Bruto", font=FG_DARK_B, fill=BG_TOTAL, align=LEFT, border=BORDER_THIN)
        c = _cell(ws2, r, 3, gross, font=FG_DARK_B, fill=BG_TOTAL, align=RIGHT, border=BORDER_THIN, num_fmt=IDR_FMT)
        _cell(ws2, r, 5, "Total Potongan", font=FG_DARK_B, fill=BG_TOTAL, align=LEFT, border=BORDER_THIN)
        c2 = _cell(ws2, r, 6, ded_total, font=FG_DARK_B, fill=BG_TOTAL, align=RIGHT, border=BORDER_THIN, num_fmt=IDR_FMT)
        ws2.row_dimensions[r].height = 16
        r += 1

        # GAJI BERSIH
        ws2.merge_cells(f"B{r}:E{r}")
        _cell(ws2, r, 2, "GAJI BERSIH DITERIMA", font=Font(name="Calibri", bold=True, size=10, color="FFFFFF"),
              fill=PatternFill("solid", fgColor="1D6F42"), align=LEFT, border=BORDER_MED)
        c = _cell(ws2, r, 6, net, font=Font(name="Calibri", bold=True, size=11, color="155724"),
                  fill=BG_GREEN, align=RIGHT, border=BORDER_MED, num_fmt=IDR_FMT)
        ws2.row_dimensions[r].height = 22
        r += 3  # gap antar slip

        current_row = r

    # ─────────────────────────────────────────────────────────────────────────
    # SHEET 3: Data Bank (untuk proses transfer)
    # ─────────────────────────────────────────────────────────────────────────
    ws3 = wb.create_sheet("Data Transfer Bank")
    ws3.sheet_view.showGridLines = False
    BANK_COLS = [("NIK", 10), ("Nama", 28), ("Bank", 10), ("No. Rekening", 20),
                 ("Gaji Bersih", 16), ("Keterangan", 22)]
    ws3.merge_cells("A1:F1")
    _cell(ws3, 1, 1, f"DATA TRANSFER GAJI — {run_num} | Periode: {period_lbl}",
          font=Font(name="Calibri", bold=True, size=11, color="1A3A5C"),
          fill=PatternFill("solid", fgColor="D6E4F0"), align=CENTER)
    ws3.row_dimensions[1].height = 22

    for ci, (hdr, w) in enumerate(BANK_COLS, 1):
        _cell(ws3, 2, ci, hdr, font=FG_WHITE, fill=BG_HEADER, align=CENTER, border=BORDER_THIN)
        ws3.column_dimensions[get_column_letter(ci)].width = w
    ws3.row_dimensions[2].height = 18

    emp_cache: dict = {}
    for idx, slip in enumerate(payslips):
        nik = slip.get("employee_code", "")
        if nik not in emp_cache:
            emp_doc = await db.rahaza_employees.find_one({"employee_code": nik}, {"_id": 0})
            emp_cache[nik] = emp_doc or {}
        emp = emp_cache[nik]
        net = slip.get("net_pay", slip.get("net_salary", 0))
        r = 3 + idx
        fill = BG_ALTROW if idx % 2 == 1 else None
        vals = [
            nik, slip.get("employee_name",""),
            # 2026-11-09: master karyawan menyimpan `bank_account_number` (dulu dibaca `bank_account` → kolom
            # No. Rekening selalu kosong di lembar transfer).
            emp.get("bank_name",""), emp.get("bank_account_number") or emp.get("bank_account", ""),
            net, f"Gaji {period_lbl}",
        ]
        for ci, val in enumerate(vals, 1):
            c = _cell(ws3, r, ci, val, font=FG_DARK, fill=fill, border=BORDER_THIN,
                      align=CENTER if ci == 1 else RIGHT if ci == 5 else LEFT)
            if ci == 5:
                c.number_format = IDR_FMT
        ws3.row_dimensions[r].height = 15

    # Total
    tr3 = 3 + len(payslips)
    ws3.merge_cells(f"A{tr3}:D{tr3}")
    _cell(ws3, tr3, 1, "TOTAL TRANSFER", font=FG_DARK_B, fill=BG_TOTAL, align=CENTER, border=BORDER_MED)
    total_net = sum(s.get("net_pay", s.get("net_salary", 0)) for s in payslips)
    _cell(ws3, tr3, 5, total_net, font=FG_DARK_B, fill=BG_TOTAL, align=RIGHT, border=BORDER_MED, num_fmt=IDR_FMT)
    ws3.row_dimensions[tr3].height = 20

    if mode == "transfer":   # Q8: Keuangan — tanpa rekap komponen & slip per karyawan
        for title in ("Rekapitulasi", "Slip Individual"):
            if title in wb.sheetnames:
                wb.remove(wb[title])

    # ── Stream ke response ────────────────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    safe_num = run_num.replace("/", "-")
    filename = f"payroll_{safe_num}_{period_from}_{period_to}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── EXPORT CSV ──────────────────────────────────────────────────────────────
# FASE 20 — BUG NYATA YANG LOLOS SEMUA GATE:
# Badan fungsi di bawah ini dulu MENYATU di dalam `export_run_excel()`, tepat
# SETELAH `return StreamingResponse(...)`-nya. Artinya 31 baris ini adalah KODE
# MATI dan dekorator `@router.get(".../export")`-nya HILANG, sehingga
# `GET /api/rahaza/payroll-runs/{id}/export` TIDAK PERNAH terdaftar di FastAPI.
# Akibat: tombol "Download CSV" di `RahazaPayrollRunModule` selalu 404 senyap.
#
# Kenapa tak terdeteksi:
#   - CHECK D (orphan handler) butuh sebuah `def` tanpa dekorator → di sini
#     tidak ada `def` baru sama sekali, jadi tak ada yang bisa dilihat.
#   - CHECK B hanya bisa bilang "FE memanggil path yang tak ada", tanpa tahu
#     implementasinya SUDAH ADA namun tak terjangkau.
# Sentinel baru: scripts/probe_unreachable_after_return.py (terdaftar di gate.sh)
@router.get("/payroll-runs/{run_id}/export")
async def export_run_csv(run_id: str, request: Request):
    """Export payroll run ke CSV (1 baris per karyawan). 2026-11-09 (Q8): Keuangan = kolom transfer saja."""
    _, mode = await _payroll_view_mode(request)
    db = get_db()
    run = await db.rahaza_payroll_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(404, "Payroll run tidak ditemukan.")
    payslips = await db.rahaza_payslips.find({"run_id": run_id}, {"_id": 0}).sort("employee_code", 1).to_list(500)

    buf = io.StringIO()
    w = csv.writer(buf)
    if mode == "transfer":
        w.writerow(["run_number", "period_from", "period_to", "employee_code", "employee_name", "bank_name",
                    "bank_account_number", "net_pay"])
        for t in await _transfer_rows(db, payslips):
            w.writerow([run.get("run_number"), run.get("period_from"), run.get("period_to"), t["employee_code"],
                        t["employee_name"], t["bank_name"], t["bank_account_number"], t["net_pay"]])
        buf.seek(0)
        safe_num = str(run.get("run_number") or run_id).replace("/", "-")
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="transfer_{safe_num}.csv"'})
    w.writerow([
        "run_number", "period_from", "period_to",
        "employee_code", "employee_name", "pay_scheme",
        "earnings_total", "overtime_hours", "overtime_amount",
        "gross_pay", "deductions_total", "manual_deduction", "net_pay",
        "days_hadir", "total_hours_worked", "adjustment_notes",
    ])
    for s in payslips:
        w.writerow([
            run.get("run_number"), run.get("period_from"), run.get("period_to"),
            s.get("employee_code"), s.get("employee_name"), s.get("pay_scheme"),
            s.get("earnings_total", 0), s.get("overtime_hours", 0), s.get("overtime_amount", 0),
            s.get("gross_pay", 0), s.get("deductions_total", 0),
            s.get("manual_deduction", 0), s.get("net_pay", 0),
            s.get("days_hadir", 0), s.get("total_hours_worked", 0),
            s.get("adjustment_notes", ""),
        ])
    buf.seek(0)
    # Nomor run bisa memuat "/" (mis. PR/2026/07/001) → harus disanitasi, kalau
    # tidak header Content-Disposition rusak & browser menyimpan nama aneh.
    safe_num = str(run.get("run_number") or run_id).replace("/", "-")
    filename = f"payroll_{safe_num}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


