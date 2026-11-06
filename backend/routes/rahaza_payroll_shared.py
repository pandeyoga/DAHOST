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

from auth import require_auth
from fastapi import HTTPException, Request
from utils.waktu import today_wib, WIB

log = logging.getLogger(__name__)

# 2026-11-02 (P5): keputusan owner No.54(a) — tanggal bisnis = WIB, tidak bergantung TZ container.
# `WIB` di-impor dari SSOT utils.waktu (tetap tersedia sebagai `rahaza_payroll_shared.WIB`).

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

# Peran yang boleh membuka & mengelola penggajian (aturan gaji, tunjangan, run, slip semua karyawan).
# Keputusan owner 6 Nov 2026: tetap seperti semula — HR Manager & Staf HR TIDAK ditambahkan
# (gaji semua karyawan bersifat rahasia). Tahap 1 hanya memakai gerbang ini di endpoint yang dulu terbuka.
PAYROLL_HR_ROLES = ("superadmin", "admin", "owner", "hr", "manager")


async def _require_hr(request: Request):
    """Authorization: hanya peran PAYROLL_HR_ROLES (atau izin hr.manage / payroll.manage) yang boleh mengelola payroll."""
    user = await require_auth(request)
    role = (user.get("role") or "").lower()
    if role in PAYROLL_HR_ROLES:
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
    today = today_wib().strftime("%Y%m%d")
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


def lwop_days_in_period(leaves: list, period_from: date, period_to: date, holiday_set: set) -> float:
    """Hari cuti tanpa gaji yang jatuh DI DALAM periode (Tahap 1, 2026-11-06).

    Aturan hari kerja = pembagi LWOP di mesin hitung: Senin–Jumat dan bukan libur kalender produksi.
    Cuti setengah hari bernilai 0,5 per hari kerja. Cuti yang melintasi dua periode hanya dihitung
    bagian yang ada di periode yang sedang dihitung.
    """
    total = 0.0
    for lv in leaves or []:
        try:
            start = max(period_from, _to_date(str(lv.get("from_date"))[:10]))
            end = min(period_to, _to_date(str(lv.get("to_date") or lv.get("from_date"))[:10]))
        except (TypeError, ValueError):
            log.warning("[payroll] cuti tanpa gaji %s: tanggal tidak valid — dilewati", lv.get("id"))
            continue
        weight = 0.5 if lv.get("is_half_day") else 1.0
        cur = start
        while cur <= end:
            if cur.weekday() < 5 and cur.isoformat() not in holiday_set:
                total += weight
            cur += timedelta(days=1)
    return total


# ═══════════════════════════════════════════════════════════════════════════════
# KASBON: SATU CICILAN PER BULAN HANYA UNTUK SATU RUN (Tahap 1, 2026-11-06)
# ═══════════════════════════════════════════════════════════════════════════════

async def kasbon_claimed_by_other_runs(db, employee_id: str, period_ym: str, kasbon_ids: list) -> dict:
    """{kasbon_id: nomor run} untuk kasbon yang potongan bulan `period_ym`-nya SUDAH ada di slip run
    lain yang belum dibatalkan (draft maupun final).

    Dulu dua run draft di bulan yang sama (mis. dua run mingguan) sama-sama memotong kasbon yang sama:
    karyawan menerima gaji kurang dua kali, sementara modul kasbon hanya mencatat satu potongan
    (dedupe periode saat finalisasi) ⇒ selisih tertinggal di Hutang Gaji. Bulan = `period_from[:7]`,
    sama dengan kunci dedupe kasbon (FIN-16)."""
    if not kasbon_ids:
        return {}
    slips = await db.rahaza_payslips.find({
        "employee_id": employee_id,
        "period_from": {"$gte": f"{period_ym}-01", "$lte": f"{period_ym}-31"},
        "deductions": {"$elemMatch": {"type": "kasbon", "kasbon_id": {"$in": list(kasbon_ids)}}},
    }, {"_id": 0, "run_id": 1, "deductions": 1}).to_list(100)
    run_ids = list({s.get("run_id") for s in slips if s.get("run_id")})
    if not run_ids:
        return {}
    live = {r["id"]: r for r in await db.rahaza_payroll_runs.find(
        {"id": {"$in": run_ids}, "status": {"$ne": "cancelled"}},
        {"_id": 0, "id": 1, "run_number": 1}).to_list(len(run_ids))}
    out: dict = {}
    for s in slips:
        run = live.get(s.get("run_id"))
        if not run:
            continue
        for d in s.get("deductions") or []:
            if (d.get("type") or "").lower() == "kasbon" and d.get("kasbon_id") in kasbon_ids:
                out.setdefault(d["kasbon_id"], run.get("run_number") or run["id"])
    return out


async def kasbon_deducted_elsewhere(db, run: dict, payslips: list) -> list:
    """Potongan kasbon di slip `run` yang untuk bulan yang sama SUDAH tercatat dari run lain (atau
    potong gaji manual Keuangan). Dipakai finalisasi sebagai pengaman run draft lama yang dibuat
    sebelum aturan satu-cicilan-satu-run: run itu harus dihapus lalu dibuat ulang."""
    period_ym = (run.get("period_from") or "")[:7]
    ids = list({d.get("kasbon_id") for s in payslips for d in (s.get("deductions") or [])
                if (d.get("type") or "").lower() == "kasbon" and d.get("kasbon_id")})
    if not ids:
        return []
    docs = await db.dewi_kasbon_requests.find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "request_number": 1, "repayments": 1}).to_list(len(ids))
    out = []
    for k in docs:
        for r in k.get("repayments") or []:
            if (r.get("period") == period_ym and r.get("method") == "payroll_deduction"
                    and r.get("run_id") != run.get("id")):
                out.append({"kasbon_id": k["id"], "request_number": k.get("request_number") or k["id"],
                            "run_number": r.get("run_number") or "potong gaji manual"})
                break
    return out


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
    # Tahap 1 (keputusan owner): selfie DITOLAK HR bukan kehadiran — tidak dihitung hadir, jam kerja,
    # lembur, maupun terlambat. Selfie yang masih menunggu review tetap dihitung (SSOT attendance_policy).
    from utils.attendance_policy import attendance_counts
    rejected = [r for r in att_rows if not attendance_counts(r)]
    if rejected:
        att_rows = [r for r in att_rows if attendance_counts(r)]
        source_refs["attendance_rejected_count"] = len(rejected)

    total_hours = sum(float(r.get("hours_worked") or 0) for r in att_rows)
    # FASE 15: jam BERSIH (sudah dikurangi istirahat & izin keluar). Pakai
    # `net_hours_worked` bila ada; kalau tidak, jatuh ke jam kotor (record lama).
    total_net_hours = sum(
        float(r.get("net_hours_worked") if r.get("net_hours_worked") is not None
              else (r.get("hours_worked") or 0))
        for r in att_rows
    )
    days_hadir = sum(1 for r in att_rows if r.get("status") == "hadir")
    total_late_minutes = sum(int(r.get("late_minutes") or 0) for r in att_rows)
    days_late = sum(1 for r in att_rows if int(r.get("late_minutes") or 0) > 0)
    total_break_minutes = sum(int(r.get("break_minutes") or 0) for r in att_rows)
    total_permit_minutes = sum(int(r.get("permit_minutes") or 0) for r in att_rows)
    source_refs.update({
        "late_minutes": total_late_minutes, "days_late": days_late,
        "break_minutes": total_break_minutes, "permit_minutes": total_permit_minutes,
    })

    # ─── LEMBUR: absensi + pengajuan DISETUJUI, satu sumber per HARI ──────────
    # 2026-11-02 (K24): dulu `overtime_hours` absensi dan jam pengajuan disetujui DIJUMLAH berdua,
    # sehingga satu lembur bisa terbayar dua kali bila keduanya terisi. Sekarang pengajuan disetujui
    # adalah sumber resmi untuk tanggalnya; jam lembur absensi pada tanggal yang SAMA dilewati
    # (dicatat di source_refs). Absensi tanpa pengajuan pada hari itu tetap dihitung.
    ot_entries: list = []
    try:
        ot_approved = await db.rahaza_overtime_requests.find({
            "employee_id": emp_id,
            "status": "approved",
            "date": _date_range_filter(period_from, period_to),
        }, {"_id": 0}).to_list(500)
        source_refs["overtime_request_count"] = len(ot_approved)
    except Exception as e:  # noqa: BLE001
        ot_approved = []
        log.warning(f"Overtime request aggregation failed for {emp_id}: {e}")
    req_dates = {str(o.get("date") or "")[:10] for o in ot_approved}
    att_ot_skipped = 0.0
    for r in att_rows:
        h = float(r.get("overtime_hours") or 0)
        if h <= 0:
            continue
        if str(r.get("date") or "")[:10] in req_dates:
            att_ot_skipped += h
            continue
        ot_entries.append({"date": str(r.get("date") or "")[:10], "source": "absensi", "hours": h,
                           "multiplier": None})
    for ot in ot_approved:
        hours = float(ot.get("hours") or 0)
        if hours <= 0:
            continue
        ot_entries.append({"date": str(ot.get("date") or "")[:10], "source": "pengajuan", "hours": hours,
                           "multiplier": float(ot.get("rate_multiplier") or 1.5)})
    if att_ot_skipped:
        source_refs["overtime_attendance_hours_skipped"] = round(att_ot_skipped, 2)
    # Jam ternormalisasi setara 1,5× (rumus lama, dipakai bila tarif Profil Gaji > 0).
    total_ot = sum(e["hours"] * (e["multiplier"] / 1.5 if e["multiplier"] else 1) for e in ot_entries)

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
    applicable_allowances = await _get_applicable_allowances(db, emp)

    # ─── NILAI LEMBUR (K24, 2026-11-02) ───────────────────────────────────────
    # 1) Tarif Profil Gaji (`overtime_rate`) > 0 → rumus lama: jam ternormalisasi × tarif.
    # 2) Tarif 0 → aturan cadangan `rahaza_payroll_settings.overtime`: 1/173 × upah tetap (gaji pokok
    #    bulanan + tunjangan TETAP bernominal tetap), per hari jam ke-1 × 1,5 dan berikutnya × 2;
    #    pengajuan berpengali selain 1,5 (hari libur 2×/3×) memakai pengali pengajuan itu apa adanya.
    #    Hanya skema bulanan (upah tetap per bulan terdefinisi).
    # 3) Selain itu lembur tidak dibayar dan slip diberi `overtime_warning` (tampil di layar run gaji).
    overtime_amount = 0
    overtime_basis = "none"
    overtime_base_hourly = 0.0
    overtime_warning = None
    ot_hours_raw = sum(e["hours"] for e in ot_entries)
    if total_ot > 0 and ot_rate > 0:
        overtime_amount = round(total_ot * ot_rate)
        overtime_basis = "profile"
    elif ot_hours_raw > 0:
        try:
            from routes.rahaza_payroll_settings import get_overtime_settings
            from routes.rahaza_payroll_tax import overtime_tier_factor
            ot_cfg = await get_overtime_settings(db)
        except Exception as e:  # noqa: BLE001
            ot_cfg = {"basis": "manual"}
            log.warning(f"Overtime settings unavailable for {emp_id}: {e}")
        upah_tetap_ot = earnings_total + sum(
            float(al.get("amount") or 0) for al in applicable_allowances
            if al.get("is_fixed_wage") and (al.get("calc_type") or "fixed") == "fixed")
        if ot_cfg.get("basis") == "upah_tetap_div_173" and scheme == "monthly" and upah_tetap_ot > 0:
            m1 = float(ot_cfg.get("first_hour_multiplier") or 1.5)
            m2 = float(ot_cfg.get("next_hours_multiplier") or 2.0)
            overtime_base_hourly = upah_tetap_ot / float(ot_cfg.get("divisor") or 173)
            factor = 0.0
            for e in ot_entries:
                mult = e["multiplier"]
                if mult is None or abs(mult - 1.5) < 1e-9:
                    e["factor"] = round(overtime_tier_factor(e["hours"], m1, m2), 4)
                else:
                    e["factor"] = round(e["hours"] * mult, 4)
                factor += e["factor"]
            overtime_amount = round(overtime_base_hourly * factor)
            overtime_basis = "upah_tetap_div_173"
            source_refs["overtime_factor"] = round(factor, 4)
        else:
            overtime_warning = (f"Ada {ot_hours_raw:g} jam lembur tetapi tarif lembur Profil Gaji = 0 dan aturan "
                                "cadangan tidak berlaku (bukan skema bulanan / basis 'manual') — lembur TIDAK dibayar. "
                                "Isi tarif lembur di Profil Gaji atau Pengaturan Payroll.")

    # ─── TUNJANGAN ────────────────────────────────────────────────────────────
    allowance_items: list = []
    allowance_total = 0.0
    fixed_wage_allowance = 0.0   # dasar iuran BPJS (upah tetap)
    base_for_pct = earnings_total + overtime_amount

    for al in applicable_allowances:
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
            if lwop_leaves:
                pf, pt = _to_date(period_from[:10]), _to_date(period_to[:10])
                holiday_set: set = set()
                try:
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
                # Tahap 1 (2026-11-06): hanya hari cuti yang JATUH DI PERIODE INI, dengan aturan hari
                # kerja yang sama dengan pembagi di atas (Senin–Jumat, bukan libur kalender produksi).
                # Dulu seluruh durasi cuti dihitung di SETIAP periode yang beririsan ⇒ cuti 28 Okt–5 Nov
                # dipotong penuh di run Oktober DAN di run November.
                lwop_days = lwop_days_in_period(lwop_leaves, pf, pt, holiday_set)
                if lwop_days > 0:
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
    #     2026-11-02 (K22/K23): kepesertaan PER PROGRAM (resolve_bpjs_programs) dan tarif/plafon/kelas
    #     risiko JKK dari `rahaza_payroll_settings.bpjs`. Iuran PERUSAHAAN ikut dihitung & disimpan di
    #     slip (`bpjs_employer`) — bukan potongan; dijurnal saat finalisasi bila saklar owner menyala.
    bpjs_pph = {"deductions": [], "total_deductions": 0.0}
    bpjs_employer = {"kes": 0, "jht": 0, "jp": 0, "jkk": 0, "jkm": 0, "kes_total": 0, "tk_total": 0, "total": 0}
    bpjs_programs = {"kes": False, "jht": False, "jp": False, "jkk_jkm": False}
    try:
        from routes.rahaza_payroll_tax import compute_full_tax_and_bpjs, resolve_bpjs_programs
        bpjs_programs = resolve_bpjs_programs(emp)
        apply_bpjs = any(bpjs_programs.values())
        apply_pph21 = bool(emp.get("npwp_number"))
        if scheme in ("monthly", "bulanan") and (apply_bpjs or apply_pph21):
            from routes.rahaza_payroll_settings import get_bpjs_settings
            bpjs_cfg = await get_bpjs_settings(db)
            gross_after = gross - float(source_refs.get("lwop_amount") or 0)
            upah_tetap = earnings_total + fixed_wage_allowance
            bpjs_pph = compute_full_tax_and_bpjs(
                monthly_gross=max(0.0, gross_after),
                ptkp_code=emp.get("tax_ptkp") or "TK/0",
                apply_bpjs=apply_bpjs,
                apply_pph21=apply_pph21,
                include_ketenagakerjaan=bool(bpjs_programs["jht"] or bpjs_programs["jp"] or bpjs_programs["jkk_jkm"]),
                jkk_risk_tier=bpjs_cfg.get("jkk_risk_tier") or "very_low",
                bpjs_base=max(0.0, upah_tetap) or None,
                programs=bpjs_programs,
                bpjs_cfg=bpjs_cfg,
            )
            deductions = deductions + list(bpjs_pph.get("deductions") or [])
            deductions_total += float(bpjs_pph.get("total_deductions") or 0)
            source_refs["bpjs_base_upah_tetap"] = round(upah_tetap)
            b = bpjs_pph.get("bpjs") or {}
            if apply_bpjs:
                bpjs_employer = {
                    "kes": b.get("kes_comp", 0), "jht": b.get("jht_comp", 0), "jp": b.get("jp_comp", 0),
                    "jkk": b.get("jkk_comp", 0), "jkm": b.get("jkm_comp", 0),
                    "kes_total": b.get("kes_company", 0), "tk_total": b.get("tk_company", 0),
                    "total": b.get("total_company", 0), "jkk_risk_tier": b.get("jkk_risk_tier"),
                }
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
        # Tahap 1: cicilan bulan ini yang sudah diklaim slip run lain (draft/final) tidak dipotong lagi.
        claimed = await kasbon_claimed_by_other_runs(
            db, emp_id, period_ym, [ks.get("id") for ks in active_ks if ks.get("id")])
        if claimed:
            source_refs["kasbon_skipped_other_run"] = [
                {"kasbon_id": k, "run_number": rn} for k, rn in claimed.items()]
        for ks in active_ks:
            if available <= 0:
                break
            outstanding = float(ks.get("outstanding_balance", 0))
            if outstanding <= 0:
                continue
            if ks.get("id") in claimed:
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
        "overtime_rate": ot_rate if overtime_basis != "upah_tetap_div_173" else round(overtime_base_hourly, 2),
        "overtime_amount": overtime_amount,
        # 2026-11-02 (K24): asal tarif lembur + rincian per hari + peringatan tarif 0
        "overtime_basis": overtime_basis,
        "overtime_base_hourly": round(overtime_base_hourly, 2),
        "overtime_entries": ot_entries,
        "overtime_warning": overtime_warning,
        # 2026-11-02 (K22/K23): kepesertaan BPJS yang dipakai + iuran perusahaan (informasi & jurnal)
        "bpjs_programs": bpjs_programs,
        "bpjs_employer": bpjs_employer,
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
    """Tanggal hari ini menurut WIB (No.54(a)) — delegasi ke SSOT utils.waktu.today_wib."""
    return today_wib()


def parse_ymd(value, *, field: str = "tanggal", default: date | None = None) -> date:
    """'YYYY-MM-DD' → date. Kosong → `default` (bawaan: hari ini WIB). Format salah → HTTP 400.

    2026-11-02: dulu tanggal transaksi yang diisi pengguna (tanggal cair/bayar) diabaikan dan
    jurnal selalu bertanggal hari ini — kasbon cair 15 Okt tercatat 1 Nov (laporan Okt meleset)."""
    if value in (None, ""):
        return default or today_wib()
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


def is_own_request(doc: dict | None, user: dict | None, own_employee_ids=()) -> bool:
    """True bila `user` adalah pengaju/pemilik dokumen (kasbon, dinas, penyelesaian dinas, klaim).

    Dicocokkan: employee_id / created_by = id akun login, submitted_by = email login, atau
    employee_id ∈ id karyawan milik akun login (`own_employee_ids`)."""
    if not doc or not user:
        return False
    uid = user.get("id")
    if uid and uid in {doc.get("employee_id"), doc.get("created_by")}:
        return True
    email = str(user.get("email") or "").strip().lower()
    if email and email == str(doc.get("submitted_by") or "").strip().lower():
        return True
    return bool(own_employee_ids) and doc.get("employee_id") in set(own_employee_ids)


def ensure_not_self_approval(doc: dict, user: dict, *, own_employee_ids=(), what: str = "pengajuan") -> None:
    """K25 (keputusan owner 2026-11-02): pemisahan tugas uang keluar — pengaju ≠ penyetuju.
    Penyetuju TIDAK boleh menyetujui miliknya sendiri (berlaku untuk semua peran)."""
    if is_own_request(doc, user, own_employee_ids):
        raise HTTPException(403, (f"Pemisahan tugas: Anda tidak boleh menyetujui {what} milik/ajuan Anda sendiri. "
                                  "Minta penyetuju lain."))


async def split_own_requests(db, collection: str, ids, user: dict):
    """K25: pisahkan dokumen milik/ajuan penyetuju sendiri dari persetujuan MASSAL (core.bulk_approve
    tidak memeriksa pemisahan tugas). Return (ids_boleh, [{id, reason}])."""
    ok, own = [], []
    for doc_id in ids or []:
        doc = await db[collection].find_one({"id": doc_id}, {"_id": 0, "employee_id": 1, "created_by": 1,
                                                             "submitted_by": 1})
        if doc and is_own_request(doc, user):
            own.append({"id": doc_id, "reason": "Pemisahan tugas: tidak boleh menyetujui ajuan sendiri"})
        else:
            ok.append(doc_id)
    return ok, own


def merge_own_failures(res: dict, own: list, total: int) -> dict:
    """Gabungkan dokumen yang ditolak split_own_requests ke hasil bulk_approve."""
    if own:
        res.setdefault("results", {}).setdefault("failed", []).extend(own)
        res["failed_count"] = len(res["results"]["failed"])
    res["total"] = total
    return res


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
