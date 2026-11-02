# ruff: noqa: F401
"""
rahaza_payroll_shared.py — Shared Helpers & Constants

Created: Session #11.19 Phase 3.2 Batch #4
Expanded: Session #11.20 — added _require_hr, _to_date, _date_range_filter,
          _generate_run_number, _compute_payslip_for_employee,
          _get_applicable_allowances (proper async versions)

FASE 15 (2026-07-26) — MESIN HITUNG SLIP DISATUKAN.
  Dulu ada DUA fungsi bernama sama `_compute_payslip_for_employee`:
    · di sini                             → punya Kasbon, TAPI komentarnya sendiri
                                             berbunyi "BPJS, PPh, dll. (placeholder —
                                             disconnect from rahaza_tax for now)".
    · di `rahaza_payroll_profiles.py:192`  → punya PPh21 + BPJS + LWOP, TAPI
                                             tidak pernah dipanggil siapa pun.
  `rahaza_payroll_runs.py` mengimpor versi DI SINI ⇒ pada payroll run SUNGGUHAN,
  **BPJS & PPh21 tidak pernah dipotong** (dibuktikan lewat API 2026-07-26: slip
  `deductions` kosong), dan tombol "Bayar BPJS"/"Bayar PPh21" SELALU gagal 400
  karena menjumlahkan potongan yang memang tidak ada.
  Sekarang: SATU fungsi di sini yang memuat SEMUA komponen. Versi di
  `rahaza_payroll_profiles.py` dihapus dan modul itu mengimpor dari sini.
  Sentinel: `scripts/verify_fase15.py` bagian S6.
"""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from auth import require_auth
from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

# 2026-11-02 (P5): keputusan owner No.54(a) — tanggal bisnis = WIB, tidak bergantung TZ container.
WIB = ZoneInfo("Asia/Jakarta")

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
VALID_SCHEMES = ["pcs", "hourly", "weekly", "monthly"]
VALID_PERIOD_TYPES = ["weekly", "monthly"]
VALID_RUN_STATUS = ["draft", "finalized", "cancelled"]

# Jenis perhitungan tunjangan yang BENAR-BENAR didukung mesin hitung.
# FASE 15: dulu `calc_type` apa pun diterima HTTP 200 lalu diam-diam dihitung
# sebagai `fixed`. Akibat nyata: "Insentif Makan" Rp 10.000/hari × 26 hari hadir
# tercatat Rp 10.000 (bukan Rp 260.000) TANPA peringatan apa pun — kelas bug yang
# sama dengan BUG-B/B2 FASE 12 (harga fallback diam-diam).
VALID_ALLOWANCE_CALC_TYPES = [
    "fixed",              # nominal tetap per periode
    "percentage_gross",   # persen dari penghasilan bruto
    "per_day_attendance",  # nominal × HARI HADIR  (mis. insentif makan Rp 10.000/hari)
    "per_hour_worked",    # nominal × JAM KERJA BERSIH
]


# ═══════════════════════════════════════════════════════════════════════════════
# BASIC HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _uid():
    """Generate UUID"""
    return str(uuid.uuid4())


def _now():
    """Get current UTC timestamp"""
    return datetime.now(timezone.utc)


def _to_date(s: str) -> date:
    """Parse YYYY-MM-DD string into date object"""
    return datetime.strptime(s, "%Y-%m-%d").date()


def _date_range_filter(from_iso: str, to_iso: str) -> dict:
    """MongoDB $gte/$lte filter for ISO date range"""
    return {"$gte": from_iso, "$lte": to_iso}


# ═══════════════════════════════════════════════════════════════════════════════
# UANG: SSOT PERHITUNGAN PAYSLIP + SINKRONISASI HEADER RUN  (FASE 20)
# ═══════════════════════════════════════════════════════════════════════════════
# Kenapa dua fungsi ini ada:
#   1. Ada DUA jalur yang mengubah angka payslip (`PUT /payslips/{pid}` untuk
#      mengganti daftar potongan, dan `POST .../payslips/{sid}/adjust` untuk
#      penyesuaian manual). Kalau masing-masing menghitung sendiri, keduanya
#      pasti menyimpang cepat atau lambat ⇒ satu rumus, satu tempat.
#   2. `post_payroll_run()` menyusun JURNAL GL dari HEADER run
#      (`total_gross`/`total_deductions`/`total_net`), BUKAN dari payslip.
#      Jadi setiap perubahan payslip WAJIB menyinkronkan header — kalau tidak,
#      jurnal yang diposting saat finalize NYATA-NYATA salah dan tidak balance.
#      (Bug lama: `PUT /payslips/{pid}` mengubah slip tanpa menyentuh header.)

def _payslip_totals(slip: dict, deductions=None, manual_deduction=None):
    """Kembalikan (deductions_total, net_pay) untuk sebuah payslip.

    `manual_deduction` sengaja DIPISAH dari array `deductions` supaya:
      - `deductions` tetap murni hasil hitungan sistem (kasbon/BPJS/PPh21) dan
        tidak pernah tertimpa oleh penyesuaian manual, dan sebaliknya;
      - FE (`s.manual_deduction`) bisa menampilkan nilai penyesuaian apa adanya.
    Keduanya tetap masuk `deductions_total` supaya identitas
    `net = gross - deductions_total` selalu benar untuk jurnal GL.
    """
    ded = slip.get("deductions") if deductions is None else deductions
    man = slip.get("manual_deduction") if manual_deduction is None else manual_deduction
    base = sum(round(float(d.get("amount") or 0)) for d in (ded or []))
    try:
        man_val = max(0.0, float(man or 0))
    except (TypeError, ValueError):
        man_val = 0.0
    total = base + round(man_val)
    gross = float(slip.get("gross_pay") or 0)
    return total, max(0, gross - total)


async def _recompute_run_totals(db, run_id: str) -> dict:
    """Sinkronkan header run dari payslip-nya (SSOT: payslip → header).

    Dipakai rumus yang SAMA dengan saat run dibuat (`sum` tanpa pembulatan ulang)
    agar tidak menimbulkan drift terhadap baseline yang sudah ada.
    """
    slips = await db.rahaza_payslips.find(
        {"run_id": run_id},
        {"_id": 0, "gross_pay": 1, "deductions_total": 1, "net_pay": 1},
    ).to_list(1000)
    totals = {
        "total_employees": len(slips),
        "total_gross": sum(float(s.get("gross_pay") or 0) for s in slips),
        "total_deductions": sum(float(s.get("deductions_total") or 0) for s in slips),
        "total_net": sum(float(s.get("net_pay") or 0) for s in slips),
        "updated_at": _now(),
    }
    await db.rahaza_payroll_runs.update_one({"id": run_id}, {"$set": totals})
    return totals


# ═══════════════════════════════════════════════════════════════════════════════
# RBAC
# ═══════════════════════════════════════════════════════════════════════════════

async def _require_hr(request: Request):
    """Authorization: only HR/Manager/Admin/Owner roles can access payroll runs."""
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role in ("superadmin", "admin", "owner", "hr", "manager"):
        return user
    perms = user.get("_permissions") or []
    if "*" in perms or "hr.manage" in perms or "payroll.manage" in perms:
        return user
    raise HTTPException(403, "Forbidden: butuh permission HR/payroll.")


# ═══════════════════════════════════════════════════════════════════════════════
# RUN NUMBER GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

async def _generate_run_number(db) -> str:
    """Generate unique run number: PR-YYYYMMDD-NNN (RC-5 fix: atomic counter)."""
    from utils.counters import gen_prefixed_number
    today = date.today().strftime("%Y%m%d")
    return await gen_prefixed_number(db, "rahaza_payroll_runs", "run_number", f"PR-{today}-", 3)


# ═══════════════════════════════════════════════════════════════════════════════
# ALLOWANCE HELPER (PROPER ASYNC VERSION)
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_applicable_allowances(db, employee: dict) -> list:
    """
    Ambil semua tunjangan tetap yang berlaku untuk karyawan ini.
    applicable_to: 'all' | 'department' | 'employee'
    """
    emp_id = employee.get("id") or employee.get("employee_id")
    dept = employee.get("department") or ""

    all_templates = await db.da_payroll_allowances.find(
        {"is_active": True}, {"_id": 0}
    ).to_list(500)

    applicable = []
    for t in all_templates:
        scope = t.get("applicable_to", "all")
        if scope == "all":
            applicable.append(t)
        elif scope == "department" and dept and t.get("department") == dept:
            applicable.append(t)
        elif scope == "employee":
            if emp_id in (t.get("employee_ids") or []):
                applicable.append(t)

    return applicable


# ═══════════════════════════════════════════════════════════════════════════════
# PAYSLIP COMPUTATION — SATU-SATUNYA SSOT (FASE 15)
# ═══════════════════════════════════════════════════════════════════════════════

async def _compute_payslip_for_employee(db, profile: dict, period_from: str,
                                        period_to: str, emp: dict) -> dict:
    """Hitung slip payroll untuk 1 pegawai. SATU-SATUNYA mesin hitung.

    Komponen (mengikuti sheet "Data THP" milik user):
      PENDAPATAN  gaji pokok / borongan pcs / jam · lembur · tunjangan
                  (fixed · % bruto · per HARI HADIR · per JAM BERSIH)
      POTONGAN    keterlambatan · LWOP · kasbon/pinjaman · BPJS · PPh21
    """
    scheme = profile["pay_scheme"]
    base_rate = float(profile.get("base_rate") or 0)
    ot_rate = float(profile.get("overtime_rate") or 0)
    emp_id = profile["employee_id"]

    earnings: list = []
    source_refs: dict = {"wip_event_count": 0, "attendance_event_count": 0,
                         "process_breakdown": {}}

    # ─── ABSENSI ──────────────────────────────────────────────────────────────
    att_rows = await db.rahaza_attendance_events.find({
        "employee_id": emp_id,
        "date": _date_range_filter(period_from, period_to),
    }, {"_id": 0}).to_list(500)
    source_refs["attendance_event_count"] = len(att_rows)

    total_hours = sum(float(r.get("hours_worked") or 0) for r in att_rows)
    # FASE 15: jam BERSIH (sudah dikurangi istirahat & izin keluar). Pakai
    # `net_hours_worked` bila ada; kalau tidak, jatuh ke jam kotor (record lama).
    total_net_hours = sum(
        float(r.get("net_hours_worked") if r.get("net_hours_worked") is not None
              else (r.get("hours_worked") or 0))
        for r in att_rows
    )
    total_ot = sum(float(r.get("overtime_hours") or 0) for r in att_rows)
    days_hadir = sum(1 for r in att_rows if r.get("status") == "hadir")
    total_late_minutes = sum(int(r.get("late_minutes") or 0) for r in att_rows)
    days_late = sum(1 for r in att_rows if int(r.get("late_minutes") or 0) > 0)
    total_break_minutes = sum(int(r.get("break_minutes") or 0) for r in att_rows)
    total_permit_minutes = sum(int(r.get("permit_minutes") or 0) for r in att_rows)
    source_refs.update({
        "late_minutes": total_late_minutes, "days_late": days_late,
        "break_minutes": total_break_minutes, "permit_minutes": total_permit_minutes,
    })

    # ─── LEMBUR YANG DISETUJUI ────────────────────────────────────────────────
    try:
        ot_approved = await db.rahaza_overtime_requests.find({
            "employee_id": emp_id,
            "status": "approved",
            "date": _date_range_filter(period_from, period_to),
        }, {"_id": 0}).to_list(500)
        for ot in ot_approved:
            hours = float(ot.get("hours") or 0)
            multiplier = float(ot.get("rate_multiplier") or 1.5)
            total_ot += hours * (multiplier / 1.5) if multiplier else hours
        source_refs["overtime_request_count"] = len(ot_approved)
    except Exception as e:  # noqa: BLE001
        log.warning(f"Overtime request aggregation failed for {emp_id}: {e}")

    # ─── PENDAPATAN per skema ─────────────────────────────────────────────────
    if scheme == "pcs":
        # Dua penulis event WIP dengan nama field berbeda (temuan FASE 15):
        #   routes/rahaza_production.py       → operator_id · event_type='output' · qty
        #   routes/production_internal_adapter.py → operator_id+employee_id ·
        #                                        event_type='complete' · qty_done · rate_per_pcs
        # Versi lama di shared.py HANYA mencocokkan employee_id+'complete' ⇒ output
        # dari lantai produksi TIDAK TERBAYAR. Sekarang keduanya diterima.
        wip_rows = await db.rahaza_wip_events.find({
            "$or": [{"operator_id": emp_id}, {"employee_id": emp_id}],
            "event_type": {"$in": ["output", "complete"]},
            "event_date": _date_range_filter(period_from, period_to),
        }, {"_id": 0}).to_list(2000)
        source_refs["wip_event_count"] = len(wip_rows)

        rate_overrides = {r["process_id"]: r["rate"]
                          for r in (profile.get("pcs_process_rates") or [])
                          if r.get("process_id")}
        proc_map: dict = {}
        for ev in wip_rows:
            pid = ev.get("process_id") or "unknown"
            qty = int(ev.get("qty_done") or ev.get("qty") or 0)
            slot = proc_map.setdefault(pid, {
                "qty": 0, "process_code": ev.get("process_code") or "",
                "rate_from_event": None,
            })
            slot["qty"] += qty
            if ev.get("process_code"):
                slot["process_code"] = ev["process_code"]
            if ev.get("rate_per_pcs"):
                slot["rate_from_event"] = float(ev["rate_per_pcs"])

        for pid, info in proc_map.items():
            rate = float(rate_overrides.get(
                pid, info["rate_from_event"] if info["rate_from_event"] is not None else base_rate))
            amount = round(info["qty"] * rate)
            code = info.get("process_code") or pid
            earnings.append({
                "type": "pcs", "label": f"Borongan pcs · {code}",
                "process_code": code, "qty": info["qty"], "unit": "pcs",
                "rate": rate, "amount": amount,
            })
            source_refs["process_breakdown"][code] = {
                "qty": info["qty"], "rate": rate, "amount": amount}

    elif scheme == "hourly":
        amount = round(total_net_hours * base_rate)
        earnings.append({
            "type": "hourly", "label": "Borongan jam",
            "qty": round(total_net_hours, 2), "unit": "jam",
            "rate": base_rate, "amount": amount,
        })

    elif scheme == "weekly":
        try:
            days = (_to_date(period_to) - _to_date(period_from)).days + 1
            weeks = max(1, round(days / 7))
        except Exception:  # noqa: BLE001
            weeks = 1
        earnings.append({
            "type": "weekly", "label": "Gaji mingguan", "qty": weeks,
            "unit": "minggu", "rate": base_rate, "amount": round(weeks * base_rate),
        })

    elif scheme == "monthly":
        earnings.append({
            "type": "monthly", "label": "Gaji pokok (bulanan)", "qty": 1,
            "unit": "bulan", "rate": base_rate, "amount": round(base_rate),
        })

    earnings_total = sum(e["amount"] for e in earnings)
    overtime_amount = round(total_ot * ot_rate) if total_ot > 0 else 0

    # ─── TUNJANGAN ────────────────────────────────────────────────────────────
    allowance_items: list = []
    allowance_total = 0.0
    fixed_wage_allowance = 0.0   # dasar iuran BPJS (upah tetap)
    base_for_pct = earnings_total + overtime_amount

    for al in await _get_applicable_allowances(db, emp):
        amt_cfg = float(al.get("amount") or 0)
        calc_type = al.get("calc_type") or "fixed"
        warning = None

        if calc_type == "percentage_gross":
            amount = base_for_pct * (amt_cfg / 100.0)
        elif calc_type == "per_day_attendance":
            amount = amt_cfg * days_hadir
        elif calc_type == "per_hour_worked":
            amount = amt_cfg * total_net_hours
        elif calc_type == "fixed":
            amount = amt_cfg
        else:
            # Jangan diam-diam salah: hitung sebagai fixed TAPI beri tanda jelas.
            amount = amt_cfg
            warning = (f"calc_type '{calc_type}' tidak dikenal — dihitung sebagai "
                       f"'fixed'. Perbaiki template tunjangan.")
            log.warning(f"[payroll] allowance {al.get('name')} calc_type tidak dikenal: {calc_type}")

        item = {
            "allowance_id": al.get("allowance_id"),
            "name": al.get("name", "Tunjangan"),
            "label": al.get("name", "Tunjangan"),
            "calc_type": calc_type,
            "rate": amt_cfg,
            "qty": (days_hadir if calc_type == "per_day_attendance"
                    else round(total_net_hours, 2) if calc_type == "per_hour_worked" else 1),
            "amount": round(amount),
            "is_fixed_wage": bool(al.get("is_fixed_wage")),
        }
        if warning:
            item["warning"] = warning
        allowance_items.append(item)
        allowance_total += item["amount"]
        if item["is_fixed_wage"]:
            fixed_wage_allowance += item["amount"]

    gross = earnings_total + overtime_amount + allowance_total

    # ─── POTONGAN ─────────────────────────────────────────────────────────────
    deductions: list = []
    deductions_total = 0.0

    # (1) KETERLAMBATAN — aturan disimpan di `rahaza_payroll_settings` supaya HR
    #     bisa mengubahnya tanpa deploy. Tanpa aturan → TIDAK memotong apa pun
    #     (lebih baik tidak memotong daripada memotong dengan angka karangan).
    late_rule = await db.rahaza_payroll_settings.find_one(
        {"key": "late_penalty"}, {"_id": 0}) or {}
    if total_late_minutes > 0 and late_rule.get("enabled"):
        mode = late_rule.get("mode") or "per_minute"
        amount = 0.0
        if mode == "per_minute":
            amount = total_late_minutes * float(late_rule.get("amount_per_minute") or 0)
        elif mode == "tiered":
            for r in (late_rule.get("tiers") or []):
                lo = int(r.get("from_minutes") or 0)
                hi = r.get("to_minutes")
                for row in att_rows:
                    lm = int(row.get("late_minutes") or 0)
                    if lm > 0 and lm >= lo and (hi is None or lm <= int(hi)):
                        amount += float(r.get("amount") or 0)
        elif mode == "per_occurrence":
            amount = days_late * float(late_rule.get("amount_per_occurrence") or 0)
        if amount > 0:
            deductions.append({
                "type": "late", "label": f"Potongan terlambat ({total_late_minutes} menit)",
                "minutes": total_late_minutes, "days": days_late,
                "amount": round(amount),
            })
            deductions_total += round(amount)

    # (2) CUTI TANPA GAJI (LWOP)
    try:
        lwop_type_ids = set()
        async for lt in db.rahaza_leave_types.find({"unpaid": True, "active": True},
                                                   {"_id": 0, "id": 1}):
            lwop_type_ids.add(lt["id"])
        if lwop_type_ids and scheme == "monthly" and base_rate > 0:
            lwop_leaves = await db.rahaza_leave_requests.find({
                "employee_id": emp_id,
                "status": "approved",
                "leave_type_id": {"$in": list(lwop_type_ids)},
                "from_date": {"$lte": period_to},
                "to_date": {"$gte": period_from},
            }, {"_id": 0}).to_list(100)
            lwop_days = sum(
                float(lv.get("duration_working_days") or lv.get("duration_days") or 0)
                for lv in lwop_leaves)
            if lwop_days > 0:
                try:
                    pf, pt = _to_date(period_from[:10]), _to_date(period_to[:10])
                    hol = await db.rahaza_production_calendar.find(
                        {"date": {"$gte": period_from[:10], "$lte": period_to[:10]},
                         "type": "holiday"}, {"_id": 0, "date": 1}).to_list(50)
                    holiday_set = {h["date"] for h in hol}
                    working_days = 0
                    cur = pf
                    while cur <= pt:
                        if cur.weekday() < 5 and cur.isoformat() not in holiday_set:
                            working_days += 1
                        cur += timedelta(days=1)
                    working_days = working_days or 22
                except Exception:  # noqa: BLE001
                    # F13 — DULU diam-diam memakai 22 hari. Ini PEMBAGI potongan
                    # gaji tanpa upah (LWOP): kalau hari kerja sebenarnya 20 dan
                    # kita memakai 22, potongan karyawan salah hitung setiap
                    # periode dan tidak ada jejak kenapa. Tetap non-blocking
                    # (payroll harus tetap bisa dihitung), tapi bersuara.
                    log.exception(
                        "[payroll] hari kerja periode %s..%s tidak bisa dihitung — "
                        "potongan LWOP memakai pembagi cadangan 22 hari; angka "
                        "potongan perlu diverifikasi manual", period_from, period_to)
                    working_days = 22
                daily_rate = round(base_rate / working_days)
                lwop_amount = round(daily_rate * lwop_days)
                deductions.append({
                    "type": "lwop",
                    "label": f"Potongan cuti tanpa gaji ({lwop_days:.1f} hari)",
                    "days": lwop_days, "daily_rate": daily_rate, "amount": lwop_amount,
                })
                deductions_total += lwop_amount
                source_refs["lwop_days"] = lwop_days
                source_refs["lwop_amount"] = lwop_amount
    except Exception as e:  # noqa: BLE001
        log.warning(f"LWOP deduction calculation failed for {emp_id}: {e}")

    # (3) BPJS + PPh21  (dihitung SEBELUM kasbon: potongan wajib didahulukan)
    #     Dasar iuran BPJS = UPAH TETAP (gaji pokok + tunjangan tetap), sesuai
    #     PP 84/2013 & praktik di sheet THP user: 1% × (pokok + tunj. jabatan).
    #     PPh21 tetap memakai bruto (seluruh penghasilan) sesuai UU PPh.
    bpjs_pph = {"deductions": [], "total_deductions": 0.0}
    try:
        from routes.rahaza_payroll_tax import compute_full_tax_and_bpjs
        apply_bpjs = bool(emp.get("bpjs_kesehatan_number") or emp.get("bpjs_ketenagakerjaan_number"))
        apply_pph21 = bool(emp.get("npwp_number"))
        if scheme in ("monthly", "bulanan") and (apply_bpjs or apply_pph21):
            gross_after = gross - float(source_refs.get("lwop_amount") or 0)
            upah_tetap = earnings_total + fixed_wage_allowance
            bpjs_pph = compute_full_tax_and_bpjs(
                monthly_gross=max(0.0, gross_after),
                ptkp_code=emp.get("tax_ptkp") or "TK/0",
                apply_bpjs=apply_bpjs,
                apply_pph21=apply_pph21,
                include_ketenagakerjaan=bool(emp.get("bpjs_ketenagakerjaan_number")),
                jkk_risk_tier="very_low",
                bpjs_base=max(0.0, upah_tetap) or None,
            )
            deductions = deductions + list(bpjs_pph.get("deductions") or [])
            deductions_total += float(bpjs_pph.get("total_deductions") or 0)
            source_refs["bpjs_base_upah_tetap"] = round(upah_tetap)
    except Exception as e:  # noqa: BLE001
        log.warning(f"PPh21/BPJS calculation failed for {emp_id}: {e}")

    # (4) KASBON / PINJAMAN — dibatasi sisa gaji yang tersedia (THP tidak boleh negatif).
    #     Iter 120: dulu memotong SELURUH saldo kasbon walau gaji periode lebih kecil ⇒ net_pay minus,
    #     JE payroll tak seimbang, dan saldo kasbon dianggap lunas dengan uang yang tidak ada.
    #     Sisa yang belum terpotong tetap outstanding dan dipotong lagi di periode berikutnya.
    try:
        period_ym = period_from[:7]
        active_ks = await db.dewi_kasbon_requests.find({
            "employee_id": emp_id,
            "status": "disbursed",
            "deduction_start_period": {"$lte": period_ym},
        }, {"_id": 0, "documents": 0}).sort("disbursed_at", 1).to_list(20)
        available = max(round(gross - deductions_total), 0)
        for ks in active_ks:
            if available <= 0:
                break
            outstanding = float(ks.get("outstanding_balance", 0))
            if outstanding <= 0:
                continue
            # FIN-16: potongan payroll yang SUDAH dicatat Keuangan untuk periode ini tidak dipotong lagi
            if any(r.get("period") == period_ym and r.get("method") == "payroll_deduction"
                   for r in (ks.get("repayments") or [])):
                continue
            deduct_amt = (outstanding if ks.get("type") == "kasbon"
                          else min(float(ks.get("installment_amount", 0)), outstanding))
            deduct_amt = round(min(deduct_amt, available))
            if deduct_amt > 0:
                row = {
                    "type": "kasbon", "kasbon_id": ks.get("id"),
                    "label": f"Potongan {ks.get('type_label', 'Kasbon')} {ks.get('request_number', '')}".strip(),
                    "amount": deduct_amt,
                }
                if deduct_amt < round(outstanding):
                    row["capped"] = True
                    row["outstanding_after"] = round(outstanding - deduct_amt)
                    sisa = f"{round(outstanding - deduct_amt):,}".replace(",", ".")
                    row["label"] += f" (sebagian, sisa {sisa})"
                deductions.append(row)
                deductions_total += deduct_amt
                available -= deduct_amt
    except Exception as e:  # noqa: BLE001
        log.warning(f"Kasbon deduction failed for {emp_id}: {e}")

    net_pay = gross - deductions_total

    return {
        "id": _uid(),
        "employee_id": emp_id,
        "employee_code": emp.get("employee_code") or "",
        "employee_name": emp.get("name") or emp.get("full_name") or "",
        "department": emp.get("department") or "",
        "job_title": emp.get("job_title") or "",
        "pay_scheme": scheme,
        "period_from": period_from,
        "period_to": period_to,
        "earnings": earnings,
        "earnings_total": earnings_total,
        "overtime_hours": round(total_ot, 2),
        "overtime_rate": ot_rate,
        "overtime_amount": overtime_amount,
        "allowances": allowance_items,
        "allowance_total": round(allowance_total),
        "total_hours_worked": round(total_hours, 2),
        "net_hours_worked": round(total_net_hours, 2),
        "days_hadir": days_hadir,
        "days_late": days_late,
        "late_minutes": total_late_minutes,
        "break_minutes": total_break_minutes,
        "permit_minutes": total_permit_minutes,
        "gross_pay": gross,
        "deductions": deductions,
        "deductions_total": deductions_total,
        "net_pay": net_pay,
        "source_refs": source_refs,
        "notes": "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER BERSAMA SDM ↔ KEUANGAN (2026-11-02, paket P5)
# Dipakai payroll, kasbon, uang muka dinas, penyelesaian dinas, dan klaim biaya
# supaya aturan "tanggal WIB", "rekening = kas/bank nyata", "run tidak ganda", dan
# "notifikasi ke pemohon" punya SATU definisi, bukan salinan per modul.
# ═══════════════════════════════════════════════════════════════════════════════

def _today_wib() -> date:
    """Tanggal hari ini menurut WIB (No.54(a))."""
    return datetime.now(WIB).date()


def parse_ymd(value, *, field: str = "tanggal", default: date | None = None) -> date:
    """'YYYY-MM-DD' → date. Kosong → `default` (bawaan: hari ini WIB). Format salah → HTTP 400.

    2026-11-02: dulu tanggal transaksi yang diisi pengguna (tanggal cair/bayar) diabaikan dan
    jurnal selalu bertanggal hari ini — kasbon cair 15 Okt tercatat 1 Nov (laporan Okt meleset)."""
    if value in (None, ""):
        return default or _today_wib()
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise HTTPException(400, f"Format {field} harus YYYY-MM-DD (diterima: {value!r}).")


def employee_is_active(emp: dict | None) -> bool:
    """Karyawan dianggap aktif kecuali `active` eksplisit False (data master SDM)."""
    return emp is not None and emp.get("active") is not False


def periods_overlap(a_from: str, a_to: str, b_from: str, b_to: str) -> bool:
    """Dua periode ISO (YYYY-MM-DD) beririsan (batas inklusif)."""
    return str(a_from)[:10] <= str(b_to)[:10] and str(b_from)[:10] <= str(a_to)[:10]


async def find_duplicate_run_conflicts(db, period_from: str, period_to: str, profiles: list,
                                       exclude_run_id: str | None = None) -> list:
    """Slip yang SUDAH ada di run lain (status ≠ cancelled) untuk karyawan + skema yang sama dan
    periode beririsan.

    2026-11-02 (P5 butir 1): dulu run kedua Okt dibuat & difinalisasi → 6-2100 = 2× 58.170.500.
    Dicek per karyawan+skema (bukan sekadar tanggal header) supaya run parsial (mis. hanya Satria)
    juga tidak bisa digaji dua kali, dan periode tumpang-tindih (30 Sep–31 Okt vs 1–31 Okt) ikut tertangkap."""
    q = {"status": {"$ne": "cancelled"}, "period_from": {"$lte": period_to}, "period_to": {"$gte": period_from}}
    if exclude_run_id:
        q["id"] = {"$ne": exclude_run_id}
    runs = await db.rahaza_payroll_runs.find(
        q, {"_id": 0, "id": 1, "run_number": 1, "period_from": 1, "period_to": 1, "status": 1}).to_list(500)
    runs = [r for r in runs if periods_overlap(period_from, period_to, r.get("period_from"), r.get("period_to"))]
    if not runs or not profiles:
        return []
    scheme_of = {p["employee_id"]: p.get("pay_scheme") for p in profiles}
    run_map = {r["id"]: r for r in runs}
    slips = await db.rahaza_payslips.find(
        {"run_id": {"$in": list(run_map)}, "employee_id": {"$in": list(scheme_of)}},
        {"_id": 0, "run_id": 1, "employee_id": 1, "employee_name": 1, "pay_scheme": 1}).to_list(5000)
    out = []
    for s in slips:
        want = scheme_of.get(s.get("employee_id"))
        # slip lama tanpa pay_scheme dianggap skema yang sama (lebih aman menolak daripada gaji ganda)
        if s.get("pay_scheme") in (None, "", want):
            r = run_map[s["run_id"]]
            out.append({"employee_id": s.get("employee_id"), "employee_name": s.get("employee_name") or "",
                        "pay_scheme": want, "run_id": r["id"], "run_number": r.get("run_number"),
                        "run_status": r.get("status"), "period_from": r.get("period_from"),
                        "period_to": r.get("period_to")})
    return out


async def list_payment_cash_accounts(db) -> list:
    """Rekening kas/bank AKTIF yang nyata (master Kas & Bank) dan akun GL-nya postable.

    2026-11-02 (P5 butir 7): pengganti daftar hard-code di layar (berisi 1-1200 = akun header
    dan 1-1203 = tidak ada di bagan akun)."""
    from core.fin_statements import cash_account_codes
    codes = await cash_account_codes(db)
    postable = {a["code"]: a async for a in db.rahaza_coa_accounts.find(
        {"code": {"$in": sorted(codes)}, "active": True, "is_group": {"$ne": True}}, {"_id": 0, "code": 1, "name": 1})}
    rows = await db.rahaza_cash_accounts.find({"active": True}, {"_id": 0}).sort("code", 1).to_list(500)
    return [{"id": r.get("id"), "code": r.get("code"), "name": r.get("name") or postable[r["gl_account_code"]].get("name"),
             "gl_account_code": r.get("gl_account_code"), "type": r.get("type") or "",
             "bank_name": r.get("bank_name") or "", "account_number": r.get("account_number") or ""}
            for r in rows if r.get("gl_account_code") in postable]


async def resolve_payment_account(db, *, cash_account_id: str | None = None, gl_code: str | None = None,
                                  default_code: str | None = None, purpose: str = "Pembayaran") -> dict:
    """SATU pintu memilih rekening uang keluar/masuk. Return {gl_code, name, cash_account_id}.

    Urutan: rekening yang dipilih (`cash_account_id`) → kode akun yang dikirim → bawaan profil.
    Ditolak (HTTP 400) bila bukan akun kas/bank postable — 2026-11-02 (P5 butir 4/7): dulu
    pembayaran gaji ke 6-2900 (akun beban) diterima, dan rekening pilihan pengguna diabaikan."""
    from core.fin_statements import cash_account_codes
    acc_id = (cash_account_id or "").strip()
    code = (gl_code or "").strip()
    ca = None
    if acc_id:
        ca = await db.rahaza_cash_accounts.find_one({"id": acc_id}, {"_id": 0})
        if not ca or ca.get("active") is False:
            raise HTTPException(400, f"{purpose}: rekening yang dipilih tidak ditemukan atau tidak aktif.")
        code = (ca.get("gl_account_code") or "").strip()
        if not code:
            raise HTTPException(400, f"{purpose}: rekening '{ca.get('name')}' belum tertaut ke akun GL "
                                     "(sinkronkan di Keuangan → Kas & Bank).")
    if not code:
        code = (default_code or "").strip()
    if not code:
        raise HTTPException(400, f"{purpose}: rekening kas/bank wajib dipilih.")
    coa = await db.rahaza_coa_accounts.find_one({"code": code, "active": True}, {"_id": 0, "name": 1, "is_group": 1})
    if not coa:
        raise HTTPException(400, f"{purpose}: akun GL '{code}' tidak ditemukan atau tidak aktif.")
    if coa.get("is_group"):
        raise HTTPException(400, f"{purpose}: akun '{code} {coa.get('name', '')}' adalah akun header — "
                                 "pilih rekening kas/bank yang spesifik.")
    if code not in await cash_account_codes(db):
        raise HTTPException(400, f"{purpose}: akun '{code} {coa.get('name', '')}' bukan akun kas/bank. "
                                 "Uang hanya boleh keluar/masuk lewat rekening kas atau bank.")
    if not ca:
        ca = await db.rahaza_cash_accounts.find_one({"gl_account_code": code, "active": {"$ne": False}},
                                                    {"_id": 0, "id": 1, "name": 1})
    return {"gl_code": code, "name": (ca or {}).get("name") or coa.get("name") or code,
            "cash_account_id": (ca or {}).get("id")}


async def notify_requester(db, *, user_id: str | None, subtype: str, title: str, body: str,
                           link_module: str, source_type: str, source_id: str, source_ref: str | None = None,
                           severity: str = "info") -> bool:
    """Notifikasi personal ke user pemohon (kasbon/klaim/dinas disetujui/ditolak). Tidak pernah raise.

    2026-11-02 (P5 butir 12): dulu hanya approver yang diberi tahu saat pengajuan masuk; pemohon
    tidak pernah tahu hasilnya. `link_module` wajib id menu Portal Saya yang benar-benar ada."""
    if not user_id:
        return False
    try:
        from utils.notif_unified import notif_insert
        await notif_insert(db, type="rahaza", subtype=subtype, severity=severity, user_id=str(user_id),
                           title=title, body=body, source_type=source_type, source_id=source_id,
                           source_ref=source_ref, status="sent", meta={"link_module": link_module})
        return True
    except Exception:  # noqa: BLE001 — notifikasi tidak boleh menggagalkan transaksi
        log.exception("[notif] gagal mengirim notifikasi %s ke user %s", subtype, user_id)
        return False
